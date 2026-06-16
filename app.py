from flask import Flask, render_template, request, redirect, session, jsonify, flash
import sqlite3
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_socketio import SocketIO, emit, join_room  # pyright: ignore[reportMissingModuleSource]
from werkzeug.utils import secure_filename
import os
import time
from flask import send_from_directory
from datetime import date
from openpyxl import Workbook
from flask import send_file
import io


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "fallback-secret")
socketio = SocketIO(app, cors_allowed_origins="*")

UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {
    'png', 'jpg', 'jpeg', 'gif', 'webp',
    'pdf', 'docx', 'xlsx', 'txt'
}

def get_db():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

def format_datetime(value):
    """Turn stored ISO datetime (or None) into display date/time parts."""
    if not value:
        return {"date": "", "time": ""}
    dt = datetime.fromisoformat(value)
    return {"date": dt.strftime("%Y-%m-%d"), "time": dt.strftime("%H:%M")}

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

def allowed_file(filename):
    return (
        '.' in filename and
        filename.rsplit('.', 1)[1].lower()
        in ALLOWED_EXTENSIONS
    )

# -------------------------
# Initialize database
# -------------------------
def init_db():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # -------------------------
    # CREATE TABLES
    # -------------------------
    c.execute('''CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        email TEXT,
        password TEXT,
        role TEXT,
        phone TEXT,
        department TEXT,
        profile_pic TEXT,
        theme TEXT DEFAULT 'light'
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER,
        clock_in TEXT,
        clock_out TEXT,
        latitude TEXT,
        longitude TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        description TEXT,
        assigned_to INTEGER,
        deadline TEXT,
        status TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message TEXT,
        is_read INTEGER DEFAULT 0,
        created_at TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        message TEXT,
        created_by INTEGER,
        created_at TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER,
        receiver_id INTEGER,
        message TEXT,
        created_at TEXT,
        is_read INTEGER DEFAULT 0
    )''')

    # -------------------------
    # TASK COMMENTS TABLE
    # -------------------------
    c.execute('''
    CREATE TABLE IF NOT EXISTS task_comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER,
        sender_id INTEGER,
        sender_role TEXT,
        message TEXT,
        parent_comment_id INTEGER,
        created_at TEXT
    )''')

    # -------------------------
    # AUTO-FIX MISSING COLUMNS
    # -------------------------
    try:
        c.execute("ALTER TABLE employees ADD COLUMN phone TEXT")
    except:
        pass

    try:
        c.execute("ALTER TABLE employees ADD COLUMN department TEXT")
    except:
        pass

    try:
        c.execute("ALTER TABLE employees ADD COLUMN profile_pic TEXT")
    except:
        pass

    try:
        c.execute("ALTER TABLE employees ADD COLUMN theme TEXT DEFAULT 'light'")
    except:
        pass
    
    try:
        c.execute("ALTER TABLE announcements ADD COLUMN file_path TEXT")
    except:
        pass

    try:
        c.execute("ALTER TABLE tasks ADD COLUMN created_by INTEGER")
    except:
        pass
    try:
        c.execute("UPDATE tasks SET status='Pending' WHERE status IS NULL")
    except:
        pass

    try:
        c.execute("ALTER TABLE messages ADD COLUMN seen INTEGER DEFAULT 0")
    except:
        pass

    try:
        c. execute("ALTER TABLE tasks ADD COLUMN created_at TEXT;")
    except:
        pass

    try:
        c. execute("ALTER TABLE tasks ADD COLUMN completed_at TEXT;")
    except:
        pass

    try:
        c.execute("ALTER TABLE tasks ADD COLUMN carried_forward INTEGER DEFAULT 0;")
    except:
        pass
    try:
        c. execute("ALTER TABLE tasks ADD COLUMN original_deadline TEXT;")
    except:
        pass
    # Add note and reply columns safely
    try:
        c.execute("ALTER TABLE tasks ADD COLUMN note TEXT")
    except:
        pass

    try:
        c.execute("ALTER TABLE tasks ADD COLUMN reply TEXT")
    except:
        pass
    
    try:
        c.execute("ALTER TABLE tasks ADD COLUMN admin_reply TEXT")
    except:
        pass
    
    try:
        c.execute("ALTER TABLE tasks ADD COLUMN task_scope TEXT DEFAULT 'personal'")
    except:
        pass

    try:
        c.execute("""
            ALTER TABLE task_comments
            ADD COLUMN visibility TEXT DEFAULT 'public'
        """)
    except:
        pass
    
    try:
        c.execute("""
            ALTER TABLE task_comments
            ADD COLUMN comment_type TEXT DEFAULT 'reply'
        """)
    except:
        pass

    try:
        c.execute("ALTER TABLE messages ADD COLUMN file_name TEXT")
    except:
        pass

    try:
        c.execute("ALTER TABLE messages ADD COLUMN file_path TEXT")
    except:
        pass    

    try:
        c.execute("ALTER TABLE messages ADD COLUMN deleted INTEGER DEFAULT 0")
    except:
        pass

    try:
        c.execute("ALTER TABLE messages ADD COLUMN edited INTEGER DEFAULT 0")
    except:
        pass

    conn.commit()
    conn.close()

# -------------------------
# Create admin if not exists
# -------------------------
def create_admin():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    hashed_password = generate_password_hash("Stgh2@&$%#3")

    # Check if admin exists
    c.execute("SELECT * FROM employees WHERE email=?", ("admin@salt.com",))
    existing_admin = c.fetchone()

    if existing_admin:
        # ✅ FIX ROLE if wrong
        c.execute("""UPDATE employees SET role='admin' WHERE email=?""", ("admin@salt.com",))
        print("Admin role fixed!")
    else:
        # ✅ CREATE ADMIN
        c.execute("""INSERT INTO employees (name, email, password, role) VALUES (?,?,?,?)""",
                  ("Admin", "admin@salt.com", hashed_password, "admin"))
        print("Admin created!")

    conn.commit()
    conn.close()


# -------------------------
# Routes
# -------------------------
@app.route('/')
def home():
    return render_template("login.html")

@app.route('/login', methods=['POST'])
def login():
    email = request.form['email']
    password = request.form['password']

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM employees WHERE email=?", (email,))
    user = c.fetchone()
    conn.close()

    if user and check_password_hash(user['password'], password):
        session['user_id'] = user['id']
        session['name'] = user['name']
        session['role'] = user['role']
        return redirect('/dashboard')
    else:
        return "Invalid login"

@app.route('/settings/profile', methods=['GET', 'POST'])
def profile_settings():
    if 'user_id' not in session:
        return redirect('/')

    conn = get_db()
    c = conn.cursor()

    if request.method == 'POST':

        # -------------------------
        # 📥 FORM DATA
        # -------------------------
        name = request.form.get('name')
        phone = request.form.get('phone')
        theme = request.form.get('theme')

        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        current_password = request.form.get('current_password')

        # -------------------------
        # 🖼️ IMAGE UPLOAD
        # -------------------------
        file = request.files.get('image')
        profile_path = None

        if file and file.filename:
            ext = file.filename.rsplit('.', 1)[-1].lower()

            if ext not in ALLOWED_EXTENSIONS:
                flash("Invalid file type. Only PNG, JPG, JPEG allowed.", "error")
                return redirect('/settings/profile')

            base_dir = os.path.dirname(os.path.abspath(__file__))
            upload_folder = os.path.join(base_dir, "static", "profiles")
            os.makedirs(upload_folder, exist_ok=True)

            filename = f"{session['user_id']}_{int(time.time())}.{ext}"
            file_path = os.path.join(upload_folder, filename)

            file.save(file_path)
            profile_path = filename

        # -------------------------
        # 🏢 DEPARTMENT CONTROL
        # -------------------------
        if session.get("role") == "admin":
            department = request.form.get('department')
        else:
            c.execute("SELECT department FROM employees WHERE id=?", (session['user_id'],))
            department = c.fetchone()['department']

        # -------------------------
        # 🔐 PASSWORD VALIDATION
        # -------------------------
        update_password = False
        hashed_password = None

        if new_password and new_password.strip() != "":

            if not current_password or current_password.strip() == "":
                flash("Please enter your current password", "error")
                return redirect('/settings/profile')

            if new_password != confirm_password:
                flash("Passwords do not match", "error")
                return redirect('/settings/profile')

            c.execute("SELECT password FROM employees WHERE id=?", (session['user_id'],))
            stored_password = c.fetchone()['password']

            if not check_password_hash(stored_password, current_password):
                flash("Current password is incorrect", "error")
                return redirect('/settings/profile')

            hashed_password = generate_password_hash(new_password)
            update_password = True

        # -------------------------
        # 🧠 BUILD UPDATE QUERY
        # -------------------------
        query = """
            UPDATE employees
            SET name=?, phone=?, department=?, theme=?
        """
        params = [name, phone, department, theme]

        if update_password:
            query += ", password=?"
            params.append(hashed_password)

        if profile_path:
            query += ", profile_pic=?"
            params.append(profile_path)

        query += " WHERE id=?"
        params.append(session['user_id'])

        c.execute(query, tuple(params))

        # -------------------------
        # 💾 SAVE
        # -------------------------
        conn.commit()
        conn.close()

        session['name'] = name

        flash("Profile updated successfully!", "success")
        return redirect('/settings/profile')

    # -------------------------
    # 📤 GET USER DATA
    # -------------------------
    c.execute("SELECT * FROM employees WHERE id=?", (session['user_id'],))
    user = c.fetchone()
    conn.close()

    return render_template("settings.html", user=user, role=session.get("role"))

@app.context_processor
def inject_user():
    if 'user_id' in session:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM employees WHERE id=?", (session['user_id'],))
        user = c.fetchone()
        conn.close()
        return dict(user=user)
    return dict(user=None)

# -------------------------
# Dashboard
# -------------------------
@app.route('/dashboard')
def dashboard():

    if 'user_id' not in session:
        return redirect('/')

    role = session.get('role')

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # -------------------------
    # Attendance logic
    # -------------------------
    today = datetime.now().date()
    today_str = today.strftime("%Y-%m-%d")

    c.execute("""
    SELECT clock_in, clock_out 
    FROM attendance
    WHERE employee_id=? AND DATE(clock_in) = DATE(?)
    ORDER BY id DESC LIMIT 1
    """, (session['user_id'], today_str))

    attendance_record = c.fetchone()

    clocked_in = False
    clocked_out = False

    if attendance_record:
        clocked_in = True
        if attendance_record[1] is not None:
            clocked_out = True

    # -------------------------
    # Dashboard stats
    # -------------------------
    total_employees = 0
    present_today = 0
    absent_today = 0
    clockins_today = 0

    if role == 'admin':
        c.execute("SELECT COUNT(*) FROM employees")
        total_employees = c.fetchone()[0]

        c.execute("SELECT COUNT(DISTINCT employee_id) FROM attendance WHERE DATE(clock_in)=?", (today_str,))
        present_today = c.fetchone()[0]

        absent_today = total_employees - present_today

        c.execute("SELECT COUNT(*) FROM attendance WHERE DATE(clock_in)=?", (today_str,))
        clockins_today = c.fetchone()[0]
    else:
        c.execute("SELECT COUNT(*) FROM attendance WHERE employee_id=? AND DATE(clock_in)=?", (session['user_id'], today_str))
        clockins_today = c.fetchone()[0]

    # -------------------------
    # Weekly chart data
    # -------------------------
    week_data = []
    labels = []
    for i in range(7):
        day = today - timedelta(days=6 - i)
        c.execute("SELECT COUNT(DISTINCT employee_id) FROM attendance WHERE DATE(clock_in)=?", (day.strftime("%Y-%m-%d"),))
        week_data.append(c.fetchone()[0])
        labels.append(day.strftime("%a"))

    # -------------------------
    # Working employees (admin only)
    # -------------------------
    if role == 'admin':
        c.execute("""
        SELECT employees.name, attendance.clock_in, attendance.latitude, attendance.longitude
        FROM attendance
        JOIN employees ON attendance.employee_id = employees.id
        WHERE DATE(clock_in) = ? AND clock_out IS NULL
        """, (today_str,))

        working_employees = c.fetchall()
    else:
        working_employees = []

    # -------------------------
    # Format clock-in time (HH:MM)
    # -------------------------
    formatted_employees = []

    for emp in working_employees:
        emp = dict(emp)

        try:
            dt = datetime.fromisoformat(emp['clock_in'])
            emp['clock_in'] = dt.strftime("%H:%M")
        except Exception:
            pass

        formatted_employees.append(emp)

    working_employees = formatted_employees

    # -------------------------
    # Task stats
    # -------------------------
    if role == 'admin':
        c.execute("SELECT COUNT(*) FROM tasks WHERE status='Completed'")
        tasks_completed = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM tasks WHERE status!='Completed'")
        tasks_pending = c.fetchone()[0]
    else:
        c.execute("SELECT COUNT(*) FROM tasks WHERE assigned_to=? AND status='Completed'", (session['user_id'],))
        tasks_completed = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM tasks WHERE assigned_to=? AND status!='Completed'", (session['user_id'],))
        tasks_pending = c.fetchone()[0]

    # -------------------------
    # Notifications
    # -------------------------
    notification_count = get_notification_count(session['user_id'])

    # -------------------------
    # Latest announcements
    # -------------------------
    c.execute("""
    SELECT title, message, created_at,file_path 
    FROM announcements
    ORDER BY created_at DESC
    LIMIT 5
    """)
    latest_announcements = c.fetchall()

    conn.close()

    # -------------------------
    # Employee Locations for Map
    # -------------------------
    employee_locations = []

    for emp in working_employees:
        lat = emp['latitude']
        lon = emp['longitude']

        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            continue

        employee_locations.append({
            "name": emp['name'],
            "time": emp['clock_in'],
            "lat": lat_f,
            "lon": lon_f
        })

    # -------------------------
    # Render
    # -------------------------
    return render_template(
        "dashboard.html",
        name=session['name'],
        role=role,
        total_employees=total_employees,
        present_today=present_today,
        absent_today=absent_today,
        clockins_today=clockins_today,
        notification_count=notification_count,
        clocked_in=clocked_in,
        clocked_out=clocked_out,
        week_data=week_data,
        labels=labels,
        working_employees=working_employees,
        tasks_completed=tasks_completed,
        tasks_pending=tasks_pending,
        latest_announcements=latest_announcements,
        employee_locations=employee_locations
    )
# -------------------------
# Clock-in
# -------------------------
@app.route('/clockin', methods=['POST'])
def clockin():
    if 'user_id' not in session:
        return redirect('/')

    lat = request.form['latitude']
    lon = request.form['longitude']

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    now = datetime.now().isoformat()

    c.execute("""
    INSERT INTO attendance (employee_id, clock_in, latitude, longitude)
    VALUES (?,?,?,?)
    """, (session['user_id'], now, lat, lon))

    conn.commit()
    conn.close()

    return redirect('/dashboard')

# -------------------------
# Clock-out
# -------------------------
@app.route('/clockout', methods=['POST'])
def clockout():
    if 'user_id' not in session:
        return redirect('/')

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    now = datetime.now().isoformat()
    today_str = datetime.now().strftime("%Y-%m-%d")

    c.execute("""
    UPDATE attendance
    SET clock_out = ?
    WHERE employee_id=? AND DATE(clock_in) = ? AND clock_out IS NULL
    """, (now, session['user_id'], today_str))

    conn.commit()
    conn.close()

    return redirect('/dashboard')

# -------------------------
# Notifications helper
# -------------------------
def get_notification_count(user_id):
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
    SELECT COUNT(*) FROM notifications
    WHERE user_id=? AND is_read=0
    """, (user_id,))

    count = c.fetchone()[0]

    conn.close()
    return count

# -------------------------
# Get notifications (AJAX)
# -------------------------
@app.route('/api/notifications')
def api_notifications():

    if 'user_id' not in session:
        return jsonify([])

    conn = get_db()
    c = conn.cursor()

    c.execute("""
    SELECT id, message, created_at, is_read
    FROM notifications
    WHERE user_id=?
    ORDER BY created_at DESC
    LIMIT 10
    """, (session['user_id'],))

    notes = c.fetchall()

    conn.close()

    return jsonify([dict(n) for n in notes])


# -------------------------
# Mark all notifications read
# -------------------------
@app.route('/api/notifications/mark-read', methods=['POST'])
def mark_notifications_read():

    if 'user_id' not in session:
        return jsonify({"success": False})

    conn = get_db()
    c = conn.cursor()

    c.execute("""
    UPDATE notifications
    SET is_read=1
    WHERE user_id=?
    """, (session['user_id'],))

    conn.commit()
    conn.close()

    return jsonify({"success": True})

@app.route('/attendance')
def attendance():
    if 'user_id' not in session:
        return redirect('/')

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    role = session.get('role')

    # 👑 ADMIN → see all
    if role == 'admin':
        c.execute("""
            SELECT employees.name, attendance.clock_in, attendance.clock_out
            FROM attendance
            JOIN employees ON attendance.employee_id = employees.id
            ORDER BY attendance.clock_in DESC
        """)
    else:
        # 👤 STAFF → see only theirs
        c.execute("""
            SELECT NULL as name, clock_in, clock_out
            FROM attendance
            WHERE employee_id=?
            ORDER BY clock_in DESC
        """, (session['user_id'],))

    raw_records = c.fetchall()
    conn.close()

    # ✅ Format data (your best practice)
    records = []

    for r in raw_records:
        clock_in = format_datetime(r["clock_in"])
        clock_out = format_datetime(r["clock_out"])

        records.append({
            "name": r["name"] if role == 'admin' else None,
            "clock_in_date": clock_in["date"],
            "clock_in_time": clock_in["time"],
            "clock_out_date": clock_out["date"],
            "clock_out_time": clock_out["time"],
            "is_active": r["clock_out"] is None
        })

    return render_template("attendance.html", records=records, role=role)

@app.route('/export/attendance')
def export_attendance():
    if 'user_id' not in session:
        return redirect('/')

    role = session.get('role')

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Admin → all records
    if role == 'admin':
        c.execute("""
            SELECT employees.name, attendance.clock_in, attendance.clock_out
            FROM attendance
            JOIN employees ON attendance.employee_id = employees.id
            ORDER BY attendance.clock_in DESC
        """)
    else:
        # Staff → only theirs
        c.execute("""
            SELECT NULL as name, clock_in, clock_out
            FROM attendance
            WHERE employee_id=?
            ORDER BY clock_in DESC
        """, (session['user_id'],))

    records = c.fetchall()
    conn.close()

    # ✅ Create Excel file
    wb = Workbook()
    ws = wb.active
    ws.title = "Attendance"

    # Headers
    if role == 'admin':
        ws.append(["Employee", "Clock In", "Clock Out", "Status"])
    else:
        ws.append(["Clock In", "Clock Out", "Status"])

    # Fill data
    for r in records:
        clock_in = r["clock_in"]
        clock_out = r["clock_out"]

        status = "Active" if clock_out is None else "Completed"

        if role == 'admin':
            ws.append([r["name"], clock_in, clock_out or "Still working", status])
        else:
            ws.append([clock_in, clock_out or "Still working", status])

    # Save to memory
    file_stream = io.BytesIO()
    wb.save(file_stream)
    file_stream.seek(0)

    return send_file(
        file_stream,
        as_attachment=True,
        download_name="attendance.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route('/admin/tasks')
def admin_tasks():
    if 'role' not in session or session['role'] != 'admin':
        return "Access Denied"

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    status = request.args.get("status")

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
            tasks.created_by,
            tasks.assigned_to,
            tasks.carried_forward,
            employees.name as employee_name
        FROM tasks
        LEFT JOIN employees ON tasks.assigned_to = employees.id
    """

    params = []

    if status:
        base_query += " WHERE tasks.status = ?"
        params.append(status)

    base_query += " ORDER BY tasks.id DESC"

    c.execute(base_query, params)
    tasks = [dict(row) for row in c.fetchall()]

    # ----------------------------
    # COMMENTS (FIXED LOGIC)
    # ----------------------------
    for task in tasks:
        c.execute("""
            SELECT *
            FROM task_comments
            WHERE task_id=?
            ORDER BY created_at ASC
        """, (task['id'],))

        comments = [dict(x) for x in c.fetchall()]

        # 👇 IMPORTANT FIX:
        # Admin board sees ALL comments (no filtering)
        task['comments'] = build_comment_tree(comments)

    # ----------------------------
    # STATS
    # ----------------------------
    c.execute("SELECT COUNT(*) FROM tasks WHERE status='Pending'")
    pending_count = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM tasks WHERE status='In Progress'")
    progress_count = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM tasks WHERE status='Completed'")
    completed_count = c.fetchone()[0]

    conn.close()

    today = date.today().isoformat()

    return render_template(
        "admin_tasks.html",
        tasks=tasks,
        pending_count=pending_count,
        progress_count=progress_count,
        completed_count=completed_count,
        today=today
    )

@app.route('/admin/reply_task/<int:id>', methods=['POST'])
def admin_reply_task(id):

    if 'role' not in session or session['role'] != 'admin':
        return "Access Denied"

    message = request.form['admin_reply']
    parent_comment_id = request.form.get('parent_comment_id')

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("""
        INSERT INTO task_comments (
            task_id,
            sender_id,
            sender_role,
            message,
            parent_comment_id,
            visibility,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        id,
        session['user_id'],
        'admin',
        message,
        parent_comment_id,
        'public',
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()

    return redirect('/admin/tasks')

@app.route('/delete_task/<int:task_id>')
def delete_task_route(task_id):

    if 'role' not in session or session['role'] != 'admin':
        return "Access Denied"

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    # 🔥 only delete admin board tasks (prevents breaking personal tasks)
    c.execute("""
        DELETE FROM tasks 
        WHERE id=? AND task_scope='admin_board'
    """, (task_id,))

    conn.commit()
    conn.close()

    return redirect('/admin/tasks')

@app.route('/admin/assign_task', methods=['GET','POST'])
def assign_task():
    if 'role' not in session or session['role'] != 'admin':
        return "Access Denied"

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    try:
        c.execute("ALTER TABLE tasks ADD COLUMN note TEXT")
    except:
        pass

    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        note = request.form['note']
        assigned_to = request.form['assigned_to']
        deadline = request.form['deadline']

        # 🔥 IMPORTANT FIX
        created_at = datetime.now().isoformat()

        c.execute("""
            INSERT INTO tasks 
            (title, description, note, assigned_to, deadline, status, created_by, task_scope, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            title,
            description,
            note,
            assigned_to,
            deadline,
            "Pending",
            session['user_id'],
            "admin_board",
            created_at
        ))

        # notification
        c.execute("""
            INSERT INTO notifications (user_id, message, created_at)
            VALUES (?,?,?)
        """, (
            assigned_to,
            f"New Task Assigned: {title}",
            datetime.now().isoformat()
        ))

        conn.commit()
        conn.close()

        return redirect('/admin/tasks')

    c.execute("SELECT id,name FROM employees")
    employees = c.fetchall()
    conn.close()

    return render_template("assign_task.html", employees=employees)

@app.route('/admin/employees')
def admin_employees():
    if 'role' not in session or session['role'] != 'admin':
        return "Access Denied"

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT id, name, email, role FROM employees")
    employees = c.fetchall()

    conn.close()

    return render_template("employees.html", employees=employees)

@app.route("/admin/add_employee", methods=["GET", "POST"])
def add_employee():
    if request.method == "POST":
        # Get form data
        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")
        role = request.form.get("role", "staff")

        # Simple validation (optional)
        if not name or not email or not password:
            return "Please fill all fields", 400

        hashed_password = generate_password_hash(password)

        # Insert into DB
        conn = sqlite3.connect("database.db")
        c = conn.cursor()
        c.execute(
            "INSERT INTO employees (name, email, password, role) VALUES (?,?,?,?)",
            (name, email, hashed_password, role)
        )
        conn.commit()
        conn.close()

        # Redirect to employee list
        return redirect("/admin/employees")  # <--- must return something!

    # GET request → render the form
    return render_template("add_employee.html")

@app.route('/admin/edit_employee/<int:id>', methods=['GET','POST'])
def edit_employee(id):

    if 'role' not in session or session['role'] != 'admin':
        return "Access Denied"

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        role = request.form['role']

        c.execute("""
        UPDATE employees
        SET name=?, email=?, role=?
        WHERE id=?
        """,(name,email,role,id))

        conn.commit()
        conn.close()

        return redirect('/admin/employees')

    c.execute("SELECT * FROM employees WHERE id=?", (id,))
    employee = c.fetchone()

    conn.close()

    return render_template("edit_employee.html", employee=employee)

@app.route('/admin/delete_employee/<int:id>')
def delete_employee(id):

    if 'role' not in session or session['role'] != 'admin':
        return "Access Denied"

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("DELETE FROM employees WHERE id=?", (id,))

    conn.commit()
    conn.close()

    return redirect('/admin/employees')


@app.route('/messages', methods=['GET', 'POST'])
@app.route('/messages/<int:user_id>', methods=['GET', 'POST'])
def messages(user_id=None):

    if 'user_id' not in session:
        return redirect('/')

    conn = get_db()
    c = conn.cursor()

    # -------------------------
    # Send message
    # -------------------------
    if request.method == 'POST' and user_id:

        message = request.form.get('message', '').strip()

        # default file values
        file_name = None
        file_path = None

        # uploaded file
        file = request.files.get("file")

        # save uploaded file
        if file and file.filename != "" and allowed_file(file.filename):

            from werkzeug.utils import secure_filename
            import time

            filename = secure_filename(file.filename)
            filename = f"{int(time.time())}_{filename}"

            save_path = os.path.join(UPLOAD_FOLDER, filename)

            print("UPLOAD ACCEPTED")
            print("SAVE PATH:", save_path)

            file.save(save_path)

            print("FILE SAVED")

            file_name = file.filename
            file_path = f"static/uploads/{filename}"

        # stop empty messages
        if not message and not file_name:
            conn.close()
            return redirect(f'/messages/{user_id}')

        # save message
        c.execute("""
            INSERT INTO messages (
                sender_id,
                receiver_id,
                message,
                created_at,
                file_name,
                file_path
            )
            VALUES (?,?,?,?,?,?)
        """, (
            session['user_id'],
            user_id,
            message,
            datetime.now().isoformat(),
            file_name,
            file_path
        ))

        # notification
        c.execute("""
            INSERT INTO notifications (
                user_id,
                message,
                created_at
            )
            VALUES (?,?,?)
        """, (
            user_id,
            f"New message from {session['name']}",
            datetime.now().isoformat()
        ))

        conn.commit()
        room = "_".join(
            map(
                str,
                sorted([session['user_id'], user_id])
            )
        )

        socketio.emit(
            'new_message',
            {
                'message': message,
                'sender_id': session['user_id'],
                'file_name': file_name,
                'file_path': file_path,
                'seen': 0
            },
            room=room
        )


        return redirect(f'/messages/{user_id}')

    # -------------------------
    # Get all users
    # -------------------------
    c.execute("""
        SELECT id, name
        FROM employees
        WHERE id != ?
    """, (session['user_id'],))

    users = c.fetchall()

    chats = []
    receiver = None

    # -------------------------
    # Load selected chat
    # -------------------------
    if user_id:

        c.execute("""
            SELECT *
            FROM messages
            WHERE
            (sender_id=? AND receiver_id=?)
            OR
            (sender_id=? AND receiver_id=?)
            ORDER BY created_at ASC
        """, (
            session['user_id'],
            user_id,
            user_id,
            session['user_id']
        ))

        chats = c.fetchall()

        c.execute("""
            SELECT *
            FROM employees
            WHERE id=?
        """, (user_id,))

        receiver = c.fetchone()
        # mark received messages as seen
        c.execute("""
            UPDATE messages
            SET seen=1
            WHERE receiver_id=? AND sender_id=?
        """, (
            session['user_id'],
            user_id
        ))

        conn.commit()
    conn.close()

    return render_template(
        "messages.html",
        users=users,
        chats=chats,
        receiver=receiver
    )


@app.route('/get_messages/<int:user_id>')
def get_messages(user_id):

    if 'user_id' not in session:
        return jsonify([])

    conn = get_db()
    c = conn.cursor()

    c.execute("""
        SELECT *
        FROM messages
        WHERE
        (sender_id=? AND receiver_id=?)
        OR
        (sender_id=? AND receiver_id=?)
        ORDER BY created_at ASC
    """, (
        session['user_id'],
        user_id,
        user_id,
        session['user_id']
    ))

    chats = c.fetchall()

    messages = []

    for chat in chats:

        messages.append({
            "id": chat["id"],
            "message": chat["message"],
            "sender_id": chat["sender_id"],
            "seen": chat["seen"],
            "file_name": chat["file_name"],
            "file_path": chat["file_path"],
            "deleted": chat["deleted"],
            "edited": chat["edited"]
        })

    conn.close()

    return jsonify(messages)

@app.route('/delete_message/<int:message_id>', methods=['POST'])
def delete_message(message_id):

    if 'user_id' not in session:
        return '', 403

    conn = get_db()
    c = conn.cursor()

    c.execute("""
    SELECT file_path
    FROM messages
    WHERE id=? AND sender_id=?
    """, (
        message_id,
        session['user_id']
    ))

    msg = c.fetchone()

    if msg:

        if msg["file_path"] and os.path.exists(msg["file_path"]):
            os.remove(msg["file_path"])

        c.execute("""
            UPDATE messages
            SET
                deleted = 1,
                message = '',
                file_name = NULL,
                file_path = NULL
            WHERE id=? AND sender_id=?
        """, (
            message_id,
            session['user_id']
        ))

        conn.commit()

    conn.close()

    return '', 200

@app.route('/edit_message/<int:message_id>', methods=['POST'])
def edit_message(message_id):

    if 'user_id' not in session:
        return jsonify({"success": False})

    new_message = request.form.get("message", "").strip()

    conn = get_db()
    c = conn.cursor()

    c.execute("""
        UPDATE messages
        SET message=?,
            edited=1
        WHERE id=?
        AND sender_id=?
    """, (
        new_message,
        message_id,
        session['user_id']
    ))

    conn.commit()
    conn.close()

    return jsonify({"success": True})

@app.route('/admin/announcements', methods=['GET', 'POST'])
def admin_announcements():

    if 'user_id' not in session:
        return redirect('/')

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    if request.method == 'POST':

        title = request.form['title']
        message = request.form['message']

        file = request.files.get('file')   # ✅ MOVE THIS UP
        file_path = None

        if file and file.filename != "":

            import os, time
            from werkzeug.utils import secure_filename

            upload_folder = os.path.join(app.root_path, "static", "announcements")
            os.makedirs(upload_folder, exist_ok=True)

            original = secure_filename(file.filename)
            unique_name = f"{int(time.time())}_{original}"

            full_save_path = os.path.join(upload_folder, unique_name)

            file.save(full_save_path)

            print("SAVED TO:", full_save_path)  # DEBUG

            file_path = unique_name   # ✅ this is what you store in DB

        c.execute("""
            INSERT INTO announcements (title, message, created_by, created_at, file_path)
            VALUES (?, ?, ?, ?, ?)
        """, (title, message, session['user_id'], datetime.now().isoformat(), file_path))

        conn.commit()
        return redirect('/admin/announcements')

    # GET ONLY
    c.execute("""
    SELECT 
        announcements.*,
        COALESCE(employees.name, 'Unknown') AS name
    FROM announcements
    LEFT JOIN employees 
        ON announcements.created_by = employees.id
    ORDER BY announcements.created_at DESC
    """)
    announcements = c.fetchall()

    conn.close()

    return render_template("admin_announcements.html", announcements=announcements)

@app.route('/admin/announcement/file/<filename>')
def download_announcement_file(filename):

    import os

    folder = os.path.join(app.root_path, "static", "announcements")
    full_path = os.path.join(folder, filename)

    print("REQUESTED FILE:", filename)
    print("FULL PATH:", full_path)
    print("EXISTS?", os.path.exists(full_path))

    return send_from_directory(folder, filename, as_attachment=True)

@app.route('/admin/update_announcement/<int:id>', methods=['POST'])
def update_announcement(id):

    if 'role' not in session or session['role'] != 'admin':
        return jsonify({"status": "error"}), 403

    data = request.get_json()
    title = data.get("title")
    message = data.get("message")

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("""
    UPDATE announcements
    SET title=?, message=?
    WHERE id=?
    """, (title, message, id))

    conn.commit()
    conn.close()

    return jsonify({"status": "success"})

@app.route('/admin/delete_announcement/<int:id>', methods=['POST'])
def delete_announcement(id):

    if 'role' not in session or session['role'] != 'admin':
        return jsonify({"status": "error"}), 403

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 🔹 Get file first (so we delete from disk)
    c.execute("SELECT file_path FROM announcements WHERE id=?", (id,))
    ann = c.fetchone()

    if ann and ann["file_path"]:
        file_path = os.path.join(app.root_path, "static", "announcements", ann["file_path"])

        if os.path.exists(file_path):
            os.remove(file_path)

    # 🔹 Delete from DB
    c.execute("DELETE FROM announcements WHERE id=?", (id,))
    conn.commit()
    conn.close()

    return jsonify({"status": "success"})

@app.route('/tasks')
def tasks():

    if 'user_id' not in session:
        return redirect('/')

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    today = datetime.now().date()

    # -------------------------
    # AUTO OVERDUE LOGIC
    # -------------------------
    c.execute("""
    SELECT id, deadline, status
    FROM tasks
    WHERE assigned_to=?
    AND status != 'Completed'
    """, (session['user_id'],))

    pending_tasks = c.fetchall()

    for task in pending_tasks:

        if task['deadline']:
            try:
                deadline = datetime.strptime(task['deadline'], "%Y-%m-%d").date()

                if deadline < today:
                    new_deadline = deadline + timedelta(days=7)

                    c.execute("""
                        UPDATE tasks
                        SET deadline=?,
                            carried_forward=1
                        WHERE id=?
                    """, (new_deadline.strftime("%Y-%m-%d"), task['id']))

            except Exception as e:
                print("Deadline error:", e)

    conn.commit()

    # -------------------------
    # PERSONAL TASKS ONLY
    # -------------------------
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
        created_by,
        assigned_to,
        carried_forward,
        completed_at,
        created_at
    FROM tasks
    WHERE assigned_to=?
    AND status != 'Completed'
    ORDER BY id DESC
    """, (session['user_id'],))

    tasks_list = [dict(t) for t in c.fetchall()]

    # -------------------------
    # COMMENTS (FIXED FILTER)
    # -------------------------
    for task in tasks_list:

        c.execute("""
            SELECT *
            FROM task_comments
            WHERE task_id=?
            AND visibility='public'
            ORDER BY created_at ASC
        """, (task['id'],))

        comments = [dict(x) for x in c.fetchall()]

        # 👇 IMPORTANT DIFFERENCE:
        # personal view = filter admin noise if needed later
        task['comments'] = build_comment_tree(comments)

    conn.close()

    return render_template(
        "tasks.html",
        tasks=tasks_list,
        name=session['name'],
        role=session['role']
    )

@app.route('/reply_task/<int:id>', methods=['POST'])
def reply_task(id):

    if 'user_id' not in session:
        return redirect('/')

    message = request.form['reply']
    parent_comment_id = request.form.get('parent_comment_id')

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("""
        INSERT INTO task_comments (
            task_id,
            sender_id,
            sender_role,
            message,
            parent_comment_id,
            visibility,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        id,
        session['user_id'],
        'employee',
        message,
        parent_comment_id,
        'public',
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()

    return redirect('/tasks')

@app.route('/task/add_note/<int:id>', methods=['POST'])
def add_task_note(id):

    if 'user_id' not in session:
        return redirect('/')

    note = request.form['note']

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("""
        INSERT INTO task_comments (
            task_id,
            sender_id,
            sender_role,
            message,
            visibility,
            comment_type,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        id,
        session['user_id'],
        session['role'],
        note,
        'public',
        'note',
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()

    return redirect('/tasks')

@app.route('/task-history')
def task_history():

    if 'user_id' not in session:
        return redirect('/')

    filter_type = request.args.get('filter', 'all')
    search = request.args.get('search', '')

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    query = """
    SELECT *
    FROM tasks
    WHERE assigned_to=?
    AND status='Completed'
    """

    params = [session['user_id']]

    # SEARCH
    if search:

        query += """
        AND (
            title LIKE ?
            OR description LIKE ?
        )
        """

        params.extend([
            f"%{search}%",
            f"%{search}%"
        ])

    # FILTERS
    if filter_type == "this_week":

        query += """
        AND date(completed_at)
        >= date('now','weekday 1','-7 days')
        """

    elif filter_type == "last_week":

        query += """
        AND date(completed_at)
        BETWEEN date('now','weekday 1','-14 days')
        AND date('now','weekday 1','-7 days')
        """

    elif filter_type == "this_month":

        query += """
        AND strftime('%m', completed_at)
        = strftime('%m','now')
        """

    elif filter_type == "last_month":

        query += """
        AND strftime('%m', completed_at)
        = strftime('%m','now','-1 month')
        """

    query += " ORDER BY completed_at DESC"

    c.execute(query, params)

    tasks = c.fetchall()

    conn.close()

    return render_template(
        "task_history.html",
        tasks=tasks,
        current_filter=filter_type,
        search=search
    )

from io import BytesIO
from openpyxl import Workbook
from flask import send_file

@app.route('/export-task-history')
def export_task_history():

    if 'user_id' not in session:
        return redirect('/')

    export_type = request.args.get('type', 'all')

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

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
    WHERE assigned_to=?
    AND status='Completed'
    """

    params = [session['user_id']]

    # EXPORT TYPES
    if export_type == "my":

        query += """
        AND created_by = assigned_to
        """

    elif export_type == "assigned":

        query += """
        AND created_by != assigned_to
        """

    query += " ORDER BY completed_at DESC"

    c.execute(query, params)

    rows = c.fetchall()

    conn.close()

    # CREATE WORKBOOK
    wb = Workbook()
    ws = wb.active

    ws.title = "Task History"

    # HEADERS
    ws.append([
        "ID",
        "Title",
        "Description",
        "Deadline",
        "Status",
        "Completed At",
        "Carried Forward"
    ])

    # DATA
    for row in rows:

        ws.append([
            row['id'],
            row['title'],
            row['description'],
            row['deadline'],
            row['status'],
            row['completed_at'],
            "Yes" if row['carried_forward'] == 1 else "No"
        ])

    # COLUMN WIDTHS
    ws.column_dimensions['A'].width = 10
    ws.column_dimensions['B'].width = 30
    ws.column_dimensions['C'].width = 45
    ws.column_dimensions['D'].width = 18
    ws.column_dimensions['E'].width = 15
    ws.column_dimensions['F'].width = 25
    ws.column_dimensions['G'].width = 18

    # MEMORY EXPORT
    output = BytesIO()
    wb.save(output)
    output.seek(0)

    # FILE NAME
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

@app.route('/complete_task/<int:id>')
def complete_task(id):
    if 'user_id' not in session:
        return redirect('/')

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    completed_at = datetime.now().isoformat()

    c.execute("""
    UPDATE tasks
    SET status='Completed',
        completed_at=?
    WHERE id=?
    """, (completed_at, id))

    conn.commit()
    conn.close()

    return redirect('/tasks')

@app.route('/tasks/create', methods=['POST'])
def create_task():

    if 'user_id' not in session:
        return redirect('/')

    title = request.form['title']
    description = request.form['description']
    deadline = request.form['deadline']

    created_at = datetime.now().isoformat()

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("""
    INSERT INTO tasks (
        title,
        description,
        assigned_to,
        deadline,
        status,
        created_by,
        created_at,
        original_deadline,
        carried_forward
    )
    VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        title,
        description,
        session['user_id'],
        deadline,
        "Pending",
        session['user_id'],
        created_at,
        deadline,
        0
    ))

    conn.commit()
    conn.close()

    return redirect('/tasks')

@app.route('/start_task/<int:id>')
def start_task(id):
    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("UPDATE tasks SET status='In Progress' WHERE id=?", (id,))
    conn.commit()
    conn.close()

    return redirect('/tasks')

@app.route('/delete_task/<int:id>')
def delete_task(id):
    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("DELETE FROM tasks WHERE id=?", (id,))
    conn.commit()
    conn.close()

    return redirect('/tasks')

@app.route('/edit_task/<int:id>', methods=['POST'])
def edit_task(id):
    data = request.get_json()

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("""
        UPDATE tasks 
        SET title=?, description=? 
        WHERE id=?
    """, (data['title'], data['description'], id))

    conn.commit()
    conn.close()

    return jsonify({"status":"success"})

# SALTY AI API (FIXED + OPTIMIZED)
@app.route('/api/salty', methods=['POST'])
def salty_ai():

    if 'user_id' not in session:
        return jsonify({"reply": "Unauthorized"}), 403

    data = request.get_json()
    msg = data.get("message", "").lower().strip()

    conn = get_db()
    c = conn.cursor()

    today = datetime.now().strftime("%Y-%m-%d")

    # -------------------------
    # 📊 CORE DATA
    # -------------------------
    c.execute("SELECT COUNT(*) FROM employees")
    total = c.fetchone()[0]

    c.execute("""
        SELECT COUNT(DISTINCT employee_id)
        FROM attendance
        WHERE DATE(clock_in)=?
    """, (today,))
    present = c.fetchone()[0]

    absent = total - present

    c.execute("""
        SELECT e.name
        FROM employees e
        JOIN attendance a ON e.id = a.employee_id
        WHERE DATE(a.clock_in)=? AND a.clock_out IS NULL
    """, (today,))
    working = [r[0] for r in c.fetchall()]

    conn.close()

    # -------------------------
    # 🧠 CLEAN NAVIGATION MAP (STRICT MATCH)
    # -------------------------
    nav_commands = {
        "open dashboard": "/dashboard",
        "dashboard": "/dashboard",
        "open attendance": "/attendance",
        "attendance": "/attendance",
        "open tasks": "/tasks",
        "tasks": "/tasks",
        "open employees": "/admin/employees",
        "employees": "/admin/employees",
        "logout": "/logout"
    }

    for cmd, route in nav_commands.items():
        if cmd in msg:
            return jsonify({
                "reply": f"Opening {cmd.replace('open ', '')}...",
                "action": route,
                "type": "navigation"
            })

    # -------------------------
    # 📊 INTELLIGENT QUERIES
    # -------------------------

    if "who is working" in msg:
        return jsonify({
            "reply": ", ".join(working) if working else "No one is currently working.",
            "type": "info"
        })

    if msg in ["working", "currently working"]:
        return jsonify({
            "reply": ", ".join(working) if working else "No active workers right now.",
            "type": "info"
        })

    if "absent" in msg:
        return jsonify({
            "reply": f"{absent} employees are absent today.",
            "type": "stats"
        })

    if "present" in msg:
        return jsonify({
            "reply": f"{present} employees are present today.",
            "type": "stats"
        })

    if "attendance" in msg:
        return jsonify({
            "reply": f"{present} present, {absent} absent today.",
            "type": "stats"
        })

    # -------------------------
    # 🧠 SYSTEM HELP
    # -------------------------
    if "help" in msg:
        return jsonify({
            "reply": "Try: open dashboard, attendance, who is working, present, absent, open tasks",
            "type": "help"
        })

    # -------------------------
    # 🤖 FALLBACK INTELLIGENCE
    # -------------------------
    return jsonify({
        "reply": "I can control dashboard navigation, attendance, employees, and tasks. Try 'open dashboard' or 'who is working'.",
        "type": "fallback"
    })


@app.route('/api/live-dashboard')
def live_dashboard():
    if 'user_id' not in session:
        return jsonify({"error": "unauthorized"}), 403

    conn = get_db()
    c = conn.cursor()

    today = datetime.now().strftime("%Y-%m-%d")

    c.execute("SELECT COUNT(*) FROM employees")
    total_employees = c.fetchone()[0]

    c.execute("""
        SELECT COUNT(DISTINCT employee_id)
        FROM attendance
        WHERE DATE(clock_in)=?
    """, (today,))
    present_today = c.fetchone()[0]

    absent_today = total_employees - present_today

    c.execute("""
        SELECT e.name
        FROM employees e
        JOIN attendance a ON e.id = a.employee_id
        WHERE DATE(a.clock_in)=? AND a.clock_out IS NULL
    """, (today,))
    working = [r[0] for r in c.fetchall()]

    conn.close()

    return jsonify({
        "total": total_employees,
        "present": present_today,
        "absent": absent_today,
        "working": working
    })

@socketio.on('join')
def on_join(data):

    room = data['room']

    join_room(room)

    print(f"Joined room {room}")

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')
# -------------------------
# Initialize app
# -------------------------
init_db()
create_admin()

if __name__ == "__main__":
    socketio.run(
        app,
        debug=True,
        host="0.0.0.0",
        port=5000
    )