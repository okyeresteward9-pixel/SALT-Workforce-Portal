"""Admin: employee list, add, edit, password reset and delete."""
from database import get_db
from decorators import is_admin
from flask import Blueprint, jsonify, redirect, render_template, request, session
from psycopg2.extras import RealDictCursor
from werkzeug.security import generate_password_hash

employees_bp = Blueprint("employees", __name__)


@employees_bp.route('/admin/employees')
def admin_employees():

    if not is_admin():
        return "Access Denied", 403

    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)

    try:
        c.execute("""
            SELECT
                id,
                name,
                email,
                role,
                phone,
                department,
                position,
                can_approve_requests,
                immediate_supervisor_id,
                signature_path,
                profile_pic,
                theme,
                profile_pic_public_id
            FROM employees
            ORDER BY id DESC
        """)

        employees = c.fetchall()

    finally:
        conn.close()

    return render_template(
        "employees.html",
        employees=employees
    )


@employees_bp.route("/admin/add_employee", methods=["GET", "POST"])
def add_employee():


    if not is_admin():
        return "Access Denied", 403


    if request.method == "POST":


        # Get form data

        name = request.form.get("name")

        email = request.form.get("email")

        password = request.form.get("password")

        role = request.form.get("role", "staff")
        position = request.form.get("position", "").strip()
        can_approve_requests = request.form.get("can_approve_requests") == "1"
        immediate_supervisor_id = request.form.get("immediate_supervisor_id") or None


        # Validation

        if not name or not email or not password:

            return "Please fill all fields", 400


        hashed_password = generate_password_hash(password)


        conn = get_db()

        c = conn.cursor()


        c.execute("""
            INSERT INTO employees
            (
                name,
                email,
                password,
                role,
                position,
                can_approve_requests,
                immediate_supervisor_id
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
            name,
            email,
            hashed_password,
            role,
            position,
            can_approve_requests,
            immediate_supervisor_id
        ))


        conn.commit()

        conn.close()


        return redirect("/admin/employees")


    return render_template(
        "add_employee.html"
    )


@employees_bp.route('/admin/save_employee', methods=['POST'])
def save_employee():

    if not is_admin():
        return jsonify({
            "success": False,
            "message": "Access Denied"
        }), 403

    employee_id = request.form.get('employee_id', '').strip()
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip()
    department = request.form.get('department', '').strip()
    position = request.form.get('position', '').strip()
    can_approve_requests = request.form.get('can_approve_requests') == '1'
    immediate_supervisor_id = request.form.get('immediate_supervisor_id') or None
    role = request.form.get('role', 'employee').strip().lower()
    password = request.form.get('password', '').strip()

    if not name or not email:
        return jsonify({
            "success": False,
            "message": "Name and email are required."
        }), 400

    if role not in ('admin', 'employee', 'staff'):
        role = 'employee'

    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # -------------------------------------------------
        # EDIT EXISTING EMPLOYEE
        # -------------------------------------------------
        if employee_id:

            try:
                employee_id = int(employee_id)
            except ValueError:
                return jsonify({
                    "success": False,
                    "message": "Invalid employee ID."
                }), 400

            c.execute("""
                SELECT id
                FROM employees
                WHERE id=%s
            """, (employee_id,))

            if not c.fetchone():
                return jsonify({
                    "success": False,
                    "message": "Employee not found."
                }), 404

            # Do not replace the password when edit form is blank.
            if password:
                hashed_password = generate_password_hash(password)

                c.execute("""
                    UPDATE employees
                    SET
                        name=%s,
                        email=%s,
                        phone=%s,
                        department=%s,
                        position=%s,
                        can_approve_requests=%s,
                        immediate_supervisor_id=%s,
                        role=%s,
                        password=%s
                    WHERE id=%s
                """, (
                    name,
                    email,
                    phone,
                    department,
                    position,
                    can_approve_requests,
                    immediate_supervisor_id,
                    role,
                    hashed_password,
                    employee_id
                ))
            else:
                c.execute("""
                    UPDATE employees
                    SET
                        name=%s,
                        email=%s,
                        phone=%s,
                        department=%s,
                        position=%s,
                        can_approve_requests=%s,
                        immediate_supervisor_id=%s,
                        role=%s
                    WHERE id=%s
                """, (
                    name,
                    email,
                    phone,
                    department,
                    position,
                    can_approve_requests,
                    immediate_supervisor_id,
                    role,
                    employee_id
                ))

            conn.commit()

            # If an admin edited their own name, keep the session current.
            if employee_id == session.get('user_id'):
                session['name'] = name
                session['role'] = role

            return jsonify({
                "success": True,
                "message": f"{name}'s profile was updated successfully."
            })

        # -------------------------------------------------
        # CREATE NEW EMPLOYEE
        # -------------------------------------------------
        if not password:
            return jsonify({
                "success": False,
                "message": "Password is required when creating an employee."
            }), 400

        c.execute("""
            SELECT id
            FROM employees
            WHERE LOWER(email)=LOWER(%s)
        """, (email,))

        if c.fetchone():
            return jsonify({
                "success": False,
                "message": "An employee with that email already exists."
            }), 409

        hashed_password = generate_password_hash(password)

        c.execute("""
            INSERT INTO employees
            (
                name,
                email,
                password,
                role,
                phone,
                department,
                position,
                can_approve_requests,
                immediate_supervisor_id,
                theme
            )
            VALUES
            (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s
            )
            RETURNING id
        """, (
            name,
            email,
            hashed_password,
            role,
            phone,
            department,
            position,
            can_approve_requests,
            immediate_supervisor_id,
            'light'
        ))

        new_id = c.fetchone()['id']

        conn.commit()

        return jsonify({
            "success": True,
            "message": f"{name} was added successfully.",
            "employee_id": new_id
        })

    except Exception as e:
        conn.rollback()
        print("SAVE EMPLOYEE ERROR:", repr(e))

        return jsonify({
            "success": False,
            "message": "Unable to save employee."
        }), 500

    finally:
        conn.close()


@employees_bp.route('/admin/edit_employee/<int:id>', methods=['GET', 'POST'])
def edit_employee(id):

    if not is_admin():
        return "Access Denied", 403

    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)

    try:

        if request.method == 'POST':

            name = request.form.get('name', '').strip()
            email = request.form.get('email', '').strip()
            phone = request.form.get('phone', '').strip()
            department = request.form.get('department', '').strip()
            position = request.form.get('position', '').strip()
            can_approve_requests = request.form.get('can_approve_requests') == '1'
            immediate_supervisor_id = request.form.get('immediate_supervisor_id') or None

            role = request.form.get(
                'role',
                'staff'
            ).strip().lower()

            if not name or not email:
                return "Name and email are required.", 400

            # Only two roles are allowed.
            if role not in ('admin', 'staff'):
                role = 'staff'

            c.execute("""
                UPDATE employees
                SET
                    name=%s,
                    email=%s,
                    phone=%s,
                    department=%s,
                    position=%s,
                    can_approve_requests=%s,
                    immediate_supervisor_id=%s,
                    role=%s
                WHERE id=%s
            """, (
                name,
                email,
                phone,
                department,
                position,
                can_approve_requests,
                immediate_supervisor_id,
                role,
                id
            ))

            conn.commit()

            return redirect('/admin/employees')


        c.execute("""
            SELECT
                id,
                name,
                email,
                role,
                phone,
                department,
                position,
                can_approve_requests,
                immediate_supervisor_id,
                signature_path,
                profile_pic,
                theme,
                profile_pic_public_id
            FROM employees
            WHERE id=%s
        """, (id,))

        employee = c.fetchone()

        if not employee:
            return "Employee not found.", 404

        return render_template(
            "edit_employee.html",
            employee=employee
        )

    finally:
        conn.close()


@employees_bp.route('/admin/reset_password/<int:id>', methods=['POST'])
def reset_employee_password(id):

    if not is_admin():
        return jsonify({
            "success": False,
            "message": "Access Denied"
        }), 403

    password = request.form.get('password', '').strip()

    if len(password) < 4:
        return jsonify({
            "success": False,
            "message": "Password must be at least 4 characters."
        }), 400

    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)

    try:
        c.execute("""
            SELECT id, name
            FROM employees
            WHERE id=%s
        """, (id,))

        employee = c.fetchone()

        if not employee:
            return jsonify({
                "success": False,
                "message": "Employee not found."
            }), 404

        hashed_password = generate_password_hash(password)

        c.execute("""
            UPDATE employees
            SET password=%s
            WHERE id=%s
        """, (
            hashed_password,
            id
        ))

        conn.commit()

        return jsonify({
            "success": True,
            "message": f"Password for {employee['name']} has been reset."
        })

    except Exception as e:
        conn.rollback()
        print("RESET PASSWORD ERROR:", repr(e))

        return jsonify({
            "success": False,
            "message": "Could not reset password."
        }), 500

    finally:
        conn.close()


@employees_bp.route('/admin/delete_employee/<int:id>', methods=['POST'])
def delete_employee(id):

    if not is_admin():
        return jsonify({
            "success": False,
            "message": "Access Denied"
        }), 403

    # Prevent an administrator from deleting their own account.
    if id == session.get('user_id'):
        return jsonify({
            "success": False,
            "message": "You cannot delete your own account."
        }), 400

    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)

    try:

        # -----------------------------------------
        # Check employee exists
        # -----------------------------------------

        c.execute("""
            SELECT id, name
            FROM employees
            WHERE id=%s
        """, (id,))

        employee = c.fetchone()

        if not employee:
            return jsonify({
                "success": False,
                "message": "Employee not found."
            }), 404


        # -----------------------------------------
        # Delete attendance records
        # -----------------------------------------

        c.execute("""
            DELETE FROM attendance
            WHERE employee_id=%s
        """, (id,))


        # -----------------------------------------
        # Delete task comments
        # -----------------------------------------

        c.execute("""
            DELETE FROM task_comments
            WHERE sender_id=%s
        """, (id,))


        # -----------------------------------------
        # Delete assigned tasks
        # -----------------------------------------

        c.execute("""
            DELETE FROM tasks
            WHERE assigned_to=%s
        """, (id,))


        # -----------------------------------------
        # Delete notifications
        # -----------------------------------------

        c.execute("""
            DELETE FROM notifications
            WHERE user_id=%s
        """, (id,))


        # -----------------------------------------
        # Delete announcements created by employee
        # -----------------------------------------

        c.execute("""
            DELETE FROM announcements
            WHERE created_by=%s
        """, (id,))


        c.execute("""
            DELETE FROM messages
            WHERE sender_id=%s
        """, (id,))

        # -----------------------------------------
        # Finally delete employee
        # -----------------------------------------

        c.execute("""
            DELETE FROM employees
            WHERE id=%s
        """, (id,))


        conn.commit()


        return jsonify({
            "success": True,
            "message": f"{employee['name']} was deleted successfully."
        })


    except Exception as e:

        conn.rollback()

        print(
            "DELETE EMPLOYEE ERROR:",
            repr(e)
        )

        return jsonify({
            "success": False,
            "message": "Could not delete employee."
        }), 500


    finally:

        conn.close()
