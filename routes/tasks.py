"""Employee and admin task pages and actions."""
import logging
from database import get_db
from datetime import date, datetime, timedelta
from flask import (
    Blueprint,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from io import BytesIO
from openpyxl import Workbook
from psycopg2.extras import RealDictCursor
from services.gamification import process_task_completion_rewards
from services.notifications import create_notification
from decorators import login_required

tasks_bp = Blueprint("tasks", __name__)


def build_comment_tree(comments):
    comment_map = {}
    tree = []

    for c in comments:
        c["children"] = []
        comment_map[c["id"]] = c

    for c in comments:
        parent_id = c["parent_comment_id"]

        if parent_id:
            parent = comment_map.get(parent_id)
            if parent:
                parent["children"].append(c)
        else:
            tree.append(c)

    return tree


@tasks_bp.route("/admin/tasks")
def admin_tasks():
    # =========================================================
    # ACCESS CONTROL
    # =========================================================
    if "role" not in session or session["role"] != "admin":
        return "Access Denied", 403

    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # =====================================================
        # FILTERS
        # =====================================================
        status = request.args.get("status", "").strip() or None
        employee_id = request.args.get("employee_id", "").strip() or None

        period = request.args.get("period", "").strip()

        # Accept only supported date filters.
        if period not in ("this_week", "last_week"):
            period = ""

        # Use Monday as the first day of the week.
        today = date.today()
        this_monday = today - timedelta(days=today.weekday())
        next_monday = this_monday + timedelta(days=7)

        if period == "this_week":
            period_start = this_monday
            period_end = today + timedelta(days=1)

        elif period == "last_week":
            period_start = this_monday - timedelta(days=7)
            period_end = this_monday

        else:
            period_start = None
            period_end = None

        # =====================================================
        # LOAD EMPLOYEES
        # =====================================================
        c.execute("""
            SELECT id, name
            FROM employees
            ORDER BY name ASC
        """)

        employees = c.fetchall()

        # =====================================================
        # LOAD TASKS
        # =====================================================
        base_query = """
            SELECT
                tasks.id,
                tasks.title,
                tasks.description,
                tasks.note,
                tasks.reply,
                tasks.admin_reply,
                tasks.deadline,
                tasks.status,
                COALESCE(tasks.priority, 'Medium') AS priority,
                tasks.created_by,
                tasks.assigned_to,
                tasks.carried_forward,
                tasks.task_scope,
                tasks.created_at,
                tasks.admin_deleted,
                tasks.employee_deleted,
                employees.name AS employee_name

            FROM tasks

            LEFT JOIN employees
                ON tasks.assigned_to = employees.id

            WHERE COALESCE(tasks.admin_deleted, FALSE) = FALSE
        """

        params = []

        # Employee filter
        if employee_id:
            base_query += """
                AND tasks.assigned_to = %s
            """
            params.append(employee_id)

        # Date filter
        if period:
            base_query += """
                AND tasks.created_at >= %s
                AND tasks.created_at < %s
            """
            params.extend([period_start, period_end])

        # Status filter
        if status:
            base_query += """
                AND tasks.status = %s
            """
            params.append(status)

        base_query += """
            ORDER BY tasks.id DESC
        """

        c.execute(base_query, params)
        tasks = c.fetchall()

        # =====================================================
        # NORMALIZE DEADLINES
        # =====================================================
        for task in tasks:
            deadline = task.get("deadline")

            if isinstance(deadline, datetime):
                task["deadline_date"] = deadline.date()

            elif isinstance(deadline, date):
                task["deadline_date"] = deadline

            elif isinstance(deadline, str):
                try:
                    task["deadline_date"] = datetime.strptime(
                        deadline[:10], "%Y-%m-%d"
                    ).date()
                except (ValueError, TypeError):
                    task["deadline_date"] = None

            else:
                task["deadline_date"] = None

        # =====================================================
        # LOAD DISCUSSIONS AND BUILD NESTED REPLIES
        # =====================================================
        for task in tasks:
            c.execute("""
                SELECT *
                FROM task_comments
                WHERE task_id = %s
                ORDER BY created_at ASC, id ASC
            """, (task["id"],))

            comments = c.fetchall()

            task["comments"] = build_comment_tree(comments)

        # =====================================================
        # STATISTICS
        #
        # Follow employee and date filters.
        # Do not apply the selected status filter to the cards.
        # =====================================================
        stats_where = """
            WHERE COALESCE(admin_deleted, FALSE) = FALSE
        """

        stats_params = []

        if employee_id:
            stats_where += """
                AND assigned_to = %s
            """
            stats_params.append(employee_id)

        if period:
            stats_where += """
                AND created_at >= %s
                AND created_at < %s
            """
            stats_params.extend([period_start, period_end])

        c.execute(f"""
            SELECT COUNT(*) AS count
            FROM tasks
            {stats_where}
            AND status = 'Pending'
        """, stats_params)

        pending_count = c.fetchone()["count"]

        c.execute(f"""
            SELECT COUNT(*) AS count
            FROM tasks
            {stats_where}
            AND status = 'In Progress'
        """, stats_params)

        progress_count = c.fetchone()["count"]

        c.execute(f"""
            SELECT COUNT(*) AS count
            FROM tasks
            {stats_where}
            AND status = 'Completed'
        """, stats_params)

        completed_count = c.fetchone()["count"]

        c.execute(f"""
            SELECT COUNT(*) AS count
            FROM tasks
            {stats_where}
            AND status != 'Completed'
            AND deadline IS NOT NULL
            AND deadline < %s
        """, stats_params + [today])

        overdue_count = c.fetchone()["count"]

        # =====================================================
        # RENDER
        # =====================================================
        return render_template(
            "admin_tasks.html",
            tasks=tasks,
            employees=employees,
            selected_employee=employee_id,
            selected_status=status,
            selected_period=period,
            pending_count=pending_count,
            progress_count=progress_count,
            completed_count=completed_count,
            overdue_count=overdue_count,
            today=today
        )

    finally:
        c.close()
        conn.close()


@tasks_bp.route('/admin/reply_task/<int:id>', methods=['POST'])
def admin_reply_task(id):

    if 'role' not in session or session['role'] != 'admin':
        return jsonify({
            "status": "error",
            "message": "Access Denied"
        }), 403

    message = request.form.get(
        'admin_reply',
        ''
    ).strip()

    parent_comment_id = request.form.get(
        'parent_comment_id'
    )

    if not message:
        return jsonify({
            "status": "error",
            "message": "Reply cannot be empty."
        }), 400

    conn = get_db()

    c = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        # =====================================================
        # FIND TASK
        # =====================================================

        c.execute("""
            SELECT
                id,
                assigned_to,
                title
            FROM tasks
            WHERE id = %s
        """, (id,))

        task_owner = c.fetchone()

        if not task_owner:

            return jsonify({
                "status": "error",
                "message": "Task not found."
            }), 404


        # =====================================================
        # INSERT ADMIN REPLY
        # =====================================================

        c.execute("""
            INSERT INTO task_comments
            (
                task_id,
                sender_id,
                sender_role,
                message,
                parent_comment_id,
                visibility,
                created_at
            )
            VALUES
            (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
            RETURNING id
        """,
        (
            id,
            session['user_id'],
            'admin',
            message,
            parent_comment_id,
            'public',
            datetime.now()
        ))

        new_comment = c.fetchone()

        comment_id = (
            new_comment["id"]
            if new_comment
            else None
        )


        # =====================================================
        # SAVE
        # =====================================================

        conn.commit()


        # =====================================================
        # NOTIFY EMPLOYEE
        # =====================================================

        employee_id = task_owner["assigned_to"]

        if employee_id:

            try:

                create_notification(
                    employee_id,
                    f"Admin replied to your task: {task_owner['title']}"
                )

            except Exception as notification_error:

                print(
                    "ADMIN REPLY NOTIFICATION ERROR:",
                    notification_error
                )


        # =====================================================
        # JSON RESPONSE
        # =====================================================

        return jsonify({

            "status": "success",

            "message":
                "Reply posted successfully.",

            "task_id": id,

            "comment_id": comment_id

        }), 200


    except Exception as e:

        conn.rollback()

        print(
            "ADMIN REPLY TASK ERROR:",
            repr(e)
        )

        return jsonify({

            "status": "error",

            "message":
                "Unable to post the reply."

        }), 500


    finally:

        conn.close()


@tasks_bp.route(
    '/delete_task/<int:task_id>',
    methods=['POST']
)
def delete_task_route(task_id):

    # =====================================================
    # AUTHENTICATION
    # =====================================================

    if 'user_id' not in session:

        return jsonify({

            "status": "error",

            "message": "Please log in."

        }), 401


    # =====================================================
    # ADMIN ONLY
    # =====================================================

    if session.get('role') != 'admin':

        return jsonify({

            "status": "error",

            "message": "Access Denied"

        }), 403


    conn = get_db()

    c = conn.cursor(
        cursor_factory=RealDictCursor
    )


    try:

        # =================================================
        # CHECK TASK
        # =================================================

        c.execute("""

            SELECT
                id,
                title,
                admin_deleted

            FROM tasks

            WHERE id = %s

        """,
        (
            task_id,
        ))


        task = c.fetchone()


        if not task:

            conn.close()

            return jsonify({

                "status": "error",

                "message": "Task not found."

            }), 404


        # =================================================
        # HIDE FROM ADMIN VIEW ONLY
        #
        # DO NOT DELETE THE TASK.
        # DO NOT DELETE COMMENTS.
        # =================================================

        c.execute("""

            UPDATE tasks

            SET admin_deleted = TRUE

            WHERE id = %s

        """,
        (
            task_id,
        ))


        conn.commit()

        conn.close()


        # =================================================
        # AJAX RESPONSE
        # =================================================

        return jsonify({

            "status": "success",

            "message":
                "Task removed from the Admin Task Board.",

            "task_id": task_id

        }), 200


    except Exception as e:

        conn.rollback()

        conn.close()


        print(
            "ADMIN DELETE TASK ERROR:",
            e
        )


        return jsonify({

            "status": "error",

            "message":
                "Unable to remove task."

        }), 500


@tasks_bp.route('/admin/assign_task', methods=['GET', 'POST'])
def assign_task():

    if 'role' not in session or session['role'] != 'admin':
        return "Access Denied", 403

    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Load employees first: needed for the form AND to validate the posted ids
        c.execute("""
            SELECT id, name
            FROM employees
            ORDER BY name ASC
        """)
        employees = c.fetchall()

        if request.method == 'POST':

            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            note = request.form.get('note', '').strip()
            priority = request.form.get('priority', 'Medium').strip().title()
            if priority not in {'High', 'Medium', 'Low'}:
                priority = 'Medium'
            deadline_raw = request.form.get('deadline') or None

            # Unique ids, original order, only real employees
            employee_lookup = {str(e['id']): e['id'] for e in employees}
            assignee_ids = [
                employee_lookup[rid]
                for rid in dict.fromkeys(request.form.getlist('assigned_to'))
                if rid in employee_lookup
            ]

            # Validation
            form_error = None
            deadline = None

            if not title or not description:
                form_error = "Please enter a task title and description."
            elif not assignee_ids:
                form_error = "Choose at least one employee."
            elif deadline_raw:
                try:
                    deadline = datetime.strptime(deadline_raw, "%Y-%m-%d").date()
                    if deadline < date.today():
                        form_error = "The deadline cannot be in the past."
                except ValueError:
                    form_error = "The deadline is not a valid date."

            if form_error:
                return render_template(
                    "assign_task.html",
                    employees=employees,
                    form_error=form_error
                ), 400

            # One task per employee, all in a single transaction
            created_at = datetime.now()

            try:
                for emp_id in assignee_ids:
                    c.execute("""
                        INSERT INTO tasks
                        (
                            title, description, note, assigned_to, deadline,
                            status, created_by, task_scope, created_at, priority
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        title, description, note, emp_id, deadline,
                        "Pending", session['user_id'], "admin_board", created_at, priority
                    ))
                conn.commit()
            except Exception:
                conn.rollback()
                logging.exception("Assign task failed")
                return render_template(
                    "assign_task.html",
                    employees=employees,
                    form_error="Something went wrong while saving. No tasks were created."
                ), 500

            # 🔔 Notify each employee. A failed notification must not break the others.
            for emp_id in assignee_ids:
                try:
                    create_notification(emp_id, f"New Task Assigned: {title}")
                except Exception:
                    logging.exception("Notification failed for employee %s", emp_id)

            return redirect('/admin/tasks')

        return render_template("assign_task.html", employees=employees)

    finally:
        conn.close()


@tasks_bp.route('/tasks')
def tasks():

    if 'user_id' not in session:
        return redirect('/')

    conn = get_db()

    c = conn.cursor(
        cursor_factory=RealDictCursor
    )

    today = datetime.now().date()

    # =====================================================
    # TASK-PAGE-ONLY MESSAGES
    # =====================================================
    #
    # Task success/error messages are passed through the
    # /tasks URL instead of Flask flash(). This prevents
    # task messages from appearing later on unrelated
    # pages such as Profile Settings.
    # =====================================================

    task_message = request.args.get("task_message")
    task_message_type = request.args.get(
        "task_message_type",
        "success"
    )

    if request.args.get("task_created") == "1":
        task_message = "Task created successfully."
        task_message_type = "success"

    # =====================================================
    # AUTO CARRY FORWARD OVERDUE TASKS
    # =====================================================

    c.execute("""
        SELECT
            id,
            deadline,
            status
        FROM tasks
        WHERE assigned_to = %s
        AND status <> 'Completed'
        AND COALESCE(
            employee_deleted,
            FALSE
        ) = FALSE
        AND deadline IS NOT NULL
    """, (
        session['user_id'],
    ))

    pending_tasks = c.fetchall()

    for task in pending_tasks:

        deadline = task["deadline"]

        # -------------------------------------------------
        # Convert deadline to a Python date
        # -------------------------------------------------

        if isinstance(deadline, datetime):

            deadline = deadline.date()

        elif isinstance(deadline, date):

            pass

        elif isinstance(deadline, str):

            try:

                deadline = datetime.strptime(
                    deadline[:10],
                    "%Y-%m-%d"
                ).date()

            except (
                ValueError,
                TypeError
            ):

                deadline = None

        else:

            deadline = None


        # -------------------------------------------------
        # Move overdue task forward
        # -------------------------------------------------

        if deadline and deadline < today:

            new_deadline = deadline

            # Keep moving the deadline forward by one week
            # until it reaches the current/future week.

            while new_deadline < today:

                new_deadline += timedelta(
                    days=7
                )


            c.execute("""
                UPDATE tasks
                SET
                    deadline = %s,
                    carried_forward = TRUE
                WHERE id = %s
            """, (
                new_deadline,
                task["id"]
            ))


    conn.commit()


    # =====================================================
    # LOAD EMPLOYEE TASKS
    # =====================================================

    c.execute("""
        SELECT

            id,
            title,
            description,
            note,
            reply,
            admin_reply,
            deadline,
            status,
            COALESCE(priority, 'Medium') AS priority,
            created_by,
            assigned_to,
            carried_forward,
            completed_at,
            created_at,
            admin_deleted,
            employee_deleted

        FROM tasks

        WHERE assigned_to = %s

        AND COALESCE(
            employee_deleted,
            FALSE
        ) = FALSE

        ORDER BY id DESC

    """, (
        session['user_id'],
    ))

    tasks_list = c.fetchall()


    # =====================================================
    # COMMENTS / DISCUSSIONS
    # =====================================================

    for task in tasks_list:

        c.execute("""
            SELECT *
            FROM task_comments
            WHERE task_id = %s
            AND visibility = 'public'
            ORDER BY created_at ASC
        """, (
            task["id"],
        ))

        comments = c.fetchall()

        task["comments"] = build_comment_tree(
            comments
        )


    conn.close()


    return render_template(
        "tasks.html",
        tasks=tasks_list,
        name=session["name"],
        role=session["role"],
        task_message=task_message,
        task_message_type=task_message_type
    )


@tasks_bp.route('/reply_task/<int:id>', methods=['POST'])
def reply_task(id):

    if 'user_id' not in session:
        return redirect('/')

    message = request.form["reply"]

    parent_comment_id = request.form.get(
        "parent_comment_id"
    )

    conn = get_db()

    c = conn.cursor()

    c.execute("""
        INSERT INTO task_comments
        (
            task_id,
            sender_id,
            sender_role,
            message,
            parent_comment_id,
            visibility,
            created_at
        )
        VALUES
        (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s
        )
    """,
    (
        id,
        session["user_id"],
        "employee",
        message,
        parent_comment_id,
        "public",
        datetime.now()
    ))

    # Find the task creator
    c.execute("""
        SELECT created_by, title
        FROM tasks
        WHERE id=%s
    """, (id,))

    task_owner = c.fetchone()

    conn.commit()
    conn.close()

    # Notify the task creator
    if task_owner and task_owner["created_by"] != session["user_id"]:

        create_notification(
            task_owner["created_by"],
            f"New reply on task: {task_owner['title']}"
        )

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":

        return jsonify({
            "status": "success"
        })

    return redirect("/tasks")


@tasks_bp.route('/task/add_note/<int:id>', methods=['POST'])
def add_task_note(id):

    if 'user_id' not in session:
        return redirect('/')

    note = request.form["note"]

    conn = get_db()

    c = conn.cursor()

    c.execute("""

        INSERT INTO task_comments
        (
            task_id,
            sender_id,
            sender_role,
            message,
            visibility,
            comment_type,
            created_at
        )

        VALUES
        (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s
        )

    """,
    (
        id,
        session["user_id"],
        session["role"],
        note,
        "public",
        "note",
        datetime.now()
    ))

    conn.commit()

    conn.close()

    return redirect("/tasks")


@tasks_bp.route('/task-history')
def task_history():

    if 'user_id' not in session:
        return redirect('/')

    filter_type = request.args.get("filter", "all")

    search = request.args.get("search", "")

    conn = get_db()

    c = conn.cursor(cursor_factory=RealDictCursor)

    query = """
        SELECT *

        FROM tasks

        WHERE assigned_to=%s

        AND status='Completed'
    """

    params = [session["user_id"]]

    # ==========================
    # SEARCH
    # ==========================

    if search:

        query += """

            AND
            (
                title ILIKE %s
                OR description ILIKE %s
            )

        """

        params.extend([
            f"%{search}%",
            f"%{search}%"
        ])

    # ==========================
    # FILTERS
    # ==========================

    if filter_type == "this_week":

        query += """
            AND completed_at >=
            date_trunc('week', CURRENT_DATE)
        """

    elif filter_type == "last_week":

        query += """
            AND completed_at >=
                date_trunc('week', CURRENT_DATE)
                - interval '1 week'

            AND completed_at <
                date_trunc('week', CURRENT_DATE)
        """

    elif filter_type == "this_month":

        query += """
            AND date_part(
                'month',
                completed_at
            )
            =
            date_part(
                'month',
                CURRENT_DATE
            )

            AND date_part(
                'year',
                completed_at
            )
            =
            date_part(
                'year',
                CURRENT_DATE
            )
        """

    elif filter_type == "last_month":

        query += """
            AND date_part(
                'month',
                completed_at
            )
            =
            date_part(
                'month',
                CURRENT_DATE - interval '1 month'
            )

            AND date_part(
                'year',
                completed_at
            )
            =
            date_part(
                'year',
                CURRENT_DATE - interval '1 month'
            )
        """

    query += """

        ORDER BY completed_at DESC

    """

    c.execute(query, params)

    tasks = c.fetchall()

    conn.close()

    return render_template(
        "task_history.html",
        tasks=tasks,
        current_filter=filter_type,
        search=search
    )


@tasks_bp.route('/export-task-history')
def export_task_history():

    if 'user_id' not in session:
        return redirect('/')

    export_type = request.args.get('type', 'all')

    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)

    query = """
        SELECT
            id,
            title,
            description,
            deadline,
            status,
            completed_at,
            carried_forward
        FROM tasks
        WHERE assigned_to=%s
        AND status='Completed'
    """

    params = [session['user_id']]

    if export_type == "my":

        query += """
            AND created_by = assigned_to
        """

    elif export_type == "assigned":

        query += """
            AND created_by <> assigned_to
        """

    query += """
        ORDER BY completed_at DESC
    """

    c.execute(query, params)

    rows = c.fetchall()

    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = "Task History"

    ws.append([
        "ID",
        "Title",
        "Description",
        "Deadline",
        "Status",
        "Completed At",
        "Carried Forward"
    ])

    for row in rows:

        ws.append([
            row["id"],
            row["title"],
            row["description"],
            row["deadline"],
            row["status"],
            row["completed_at"],
            "Yes" if row["carried_forward"] else "No"
        ])

    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].width = 45
    ws.column_dimensions["D"].width = 18
    ws.column_dimensions["E"].width = 15
    ws.column_dimensions["F"].width = 25
    ws.column_dimensions["G"].width = 18

    output = BytesIO()

    wb.save(output)

    output.seek(0)

    if export_type == "my":
        filename = "my_tasks.xlsx"

    elif export_type == "assigned":
        filename = "assigned_tasks.xlsx"

    else:
        filename = "all_tasks.xlsx"

    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@tasks_bp.route('/tasks/<int:id>/complete', methods=['POST'])
@login_required
def complete_task(id):

    user_id = session['user_id']

    conn = get_db()

    c = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        # ==========================================
        # GET TASK
        # ==========================================

        c.execute("""
            SELECT
                id,
                title,
                created_by,
                assigned_to,
                status,
                deadline
            FROM tasks
            WHERE id = %s
        """, (id,))

        task = c.fetchone()


        if not task:

            conn.close()

            return redirect(
                url_for(
                    "tasks",
                    task_message="Task not found.",
                    task_message_type="error"
                )
            )


        # ==========================================
        # CHECK OWNERSHIP
        # ==========================================
        #
        # A user can complete:
        #
        # 1. A task assigned to them
        # 2. A self-created task
        #
        # This also supports your current
        # self-task structure.
        # ==========================================

        assigned_to = task.get(
            "assigned_to"
        )

        created_by = task.get(
            "created_by"
        )


        if (
            assigned_to != user_id
            and created_by != user_id
        ):

            conn.close()

            return redirect(
                url_for(
                    "tasks",
                    task_message="You are not authorized to complete this task.",
                    task_message_type="error"
                )
            )


        # ==========================================
        # ALREADY COMPLETED
        # ==========================================

        if task.get("status") == "Completed":

            conn.close()

            return redirect(
                url_for(
                    "tasks",
                    task_message="This task is already completed.",
                    task_message_type="info"
                )
            )


        # ==========================================
        # COMPLETE TASK
        # ==========================================

        c.execute("""
            UPDATE tasks
            SET
                status = 'Completed',
                completed_at = %s
            WHERE id = %s
        """, (
            datetime.now(),
            id
        ))


        # ==========================================
        # COMMIT
        # ==========================================

        conn.commit()


        # ==========================================
        # GAMIFICATION / REWARDS
        # ==========================================
        process_task_completion_rewards(
            user_id,
            id,
            task.get('deadline'),
            datetime.now()
        )

        # ==========================================
        # NOTIFY CREATOR
        # ==========================================
        #
        # Only notify if another employee completed
        # the task.
        #
        # Self-created task:
        # created_by == user_id
        # → no notification needed.
        # ==========================================

        if (
            created_by
            and created_by != user_id
        ):

            try:

                create_notification(
                    created_by,
                    f"Task Completed: {task['title']}"
                )

            except Exception as notification_error:

                print(
                    "TASK COMPLETION NOTIFICATION ERROR:",
                    notification_error
                )


        conn.close()


        return redirect(
            url_for(
                "tasks",
                task_message="Task completed successfully.",
                task_message_type="success"
            )
        )


    except Exception as e:

        conn.rollback()

        conn.close()

        print(
            "COMPLETE TASK ERROR:",
            e
        )

        return redirect(
            url_for(
                "tasks",
                task_message="Unable to complete task.",
                task_message_type="error"
            )
        )


@tasks_bp.route('/tasks/create', methods=['POST'])
def create_task():

    if 'user_id' not in session:
        return redirect('/')

    title = request.form.get(
        "title",
        ""
    ).strip()

    description = request.form.get(
        "description",
        ""
    ).strip()

    priority = request.form.get("priority", "Medium").strip().title()
    if priority not in {"High", "Medium", "Low"}:
        priority = "Medium"

    deadline = request.form.get(
        "deadline"
    ) or None

    conn = get_db()

    c = conn.cursor()

    c.execute("""
        INSERT INTO tasks
        (
            title,
            description,
            assigned_to,
            deadline,
            status,
            created_by,
            created_at,
            original_deadline,
            carried_forward,
            priority
        )
        VALUES
        (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s
        )
    """, (
        title,
        description,
        session["user_id"],
        deadline,
        "Pending",
        session["user_id"],
        datetime.now(),
        deadline,
        False,
        priority
    ))

    conn.commit()
    conn.close()

    return redirect(
        url_for(
            "tasks.tasks",
            task_created=1
        )
    )


@tasks_bp.route('/tasks/<int:id>/start', methods=['POST'])
@login_required
def start_task(id):

    conn = get_db()

    c = conn.cursor()

    c.execute("""
        SELECT created_by, title
        FROM tasks
        WHERE id=%s
        AND assigned_to=%s
    """, (
        id,
        session['user_id']
    ))

    task_owner = c.fetchone()

    c.execute("""
        UPDATE tasks
        SET status='In Progress'
        WHERE id=%s
        AND assigned_to=%s
    """, (
        id,
        session['user_id']
    ))

    conn.commit()

    conn.close()

    # 🔔 Notify the task creator when an assigned task is started.
    if task_owner and task_owner["created_by"] != session["user_id"]:

        create_notification(
            task_owner["created_by"],
            f"Task Started: {task_owner['title']}"
        )

    return redirect('/tasks')


@tasks_bp.route('/tasks/<int:id>/delete', methods=['POST'])
@login_required
def delete_task(id):

    conn = get_db()
    c = conn.cursor()

    # Only hide the task from the employee's own list
    c.execute("""
        UPDATE tasks
        SET employee_deleted = TRUE
        WHERE id=%s
        AND assigned_to=%s
    """, (id, session['user_id']))

    conn.commit()
    conn.close()

    return redirect('/tasks')


@tasks_bp.route('/edit_task/<int:id>', methods=['POST'])
def edit_task(id):

    if 'user_id' not in session:
        return jsonify({
            "status":"unauthorized"
        }),403

    data = request.get_json()

    conn = get_db()

    c = conn.cursor()

    c.execute("""

        UPDATE tasks

        SET

            title=%s,

            description=%s

        WHERE id=%s

    """,
    (
        data["title"],
        data["description"],
        id
    ))

    conn.commit()

    conn.close()

    return jsonify({
        "status":"success"
    })
