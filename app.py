from gevent import monkey
monkey.patch_all()

from dotenv import load_dotenv
load_dotenv()  # reads .env for local development; harmless on Render

from psycogreen.gevent import patch_psycopg
patch_psycopg()

from flask import Flask, render_template, request, redirect, session, jsonify, flash, url_for
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_socketio import SocketIO, join_room  # pyright: ignore[reportMissingModuleSource]
from werkzeug.utils import secure_filename
import os
import time
import logging
from flask import send_from_directory
from datetime import date
from openpyxl import Workbook
from flask import send_file
import io
from io import BytesIO
from database import get_db, allowed_file, UPLOAD_FOLDER, ALLOWED_EXTENSIONS
from routes.chat import (
    chat_bp,
    register_chat_socketio
)

from routes.auth import auth_bp
from routes.pwa import pwa_bp
from routes.notifications import notifications_bp
from services.notifications import (
    init_notifications,
    create_notification,
    notify_users,
    notify_announcement,
    get_notification_count,
)
from routes.tasks import tasks_bp
from services.gamification import (
    _calculate_level,
    _ensure_gamification_profile,
    process_attendance_rewards,
)
from request_workflow import register_request_workflow
from cloudinary import uploader
from cloudinary import api as cloudinary_api
import cloudinary
import cloudinary_config
import json
from security import origin_allowed, SAFE_METHODS

app = Flask(__name__)


app.register_blueprint(chat_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(pwa_bp)
app.register_blueprint(notifications_bp)
app.register_blueprint(tasks_bp)

# APP_ENV=development enables debug mode and an insecure local-only key.
# Anything else (including unset) is treated as production.
IS_PRODUCTION = os.environ.get("APP_ENV", "production").strip().lower() != "development"

_secret_key = os.environ.get("SECRET_KEY")
if not _secret_key:
    if IS_PRODUCTION:
        raise RuntimeError(
            "SECRET_KEY environment variable is required. "
            "For local work set APP_ENV=development in your .env file."
        )
    _secret_key = "dev-only-insecure-key"
app.secret_key = _secret_key

# Comma-separated list, e.g. https://your-portal.onrender.com
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()
]

# Session settings
app.permanent_session_lifetime = timedelta(days=30)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PRODUCTION
)

socketio = SocketIO(
    app,
    cors_allowed_origins=ALLOWED_ORIGINS or None,  # None = same-origin only
    async_mode="gevent"
)

register_chat_socketio(socketio)
init_notifications(socketio)


@app.before_request
def block_cross_site_writes():
    if request.method in SAFE_METHODS:
        return None
    if not origin_allowed(
        request.headers.get("Origin"),
        request.headers.get("Referer"),
        request.host,
        ALLOWED_ORIGINS,
        request.headers.get("Sec-Fetch-Site"),
    ):
        return jsonify({"status": "error", "message": "Cross-site request blocked."}), 403
    return None


def format_datetime(value):

    if not value:
        return {
            "date": "",
            "time": ""
        }

    dt = value if isinstance(value, datetime) else datetime.fromisoformat(value)

    return {
        "date": dt.strftime("%Y-%m-%d"),
        "time": dt.strftime("%H:%M")
    }


# -------------------------
# Initialize database
# -------------------------
def init_db():
    """
    Initialize and migrate the PostgreSQL database safely.

    IMPORTANT:
    PostgreSQL marks the current transaction as aborted after a failed SQL
    statement. The previous version used `try/except: pass` around ALTER TABLE
    statements, which left the transaction aborted and caused:

        current transaction is aborted, commands ignored until end of transaction block

    All migrations below therefore use PostgreSQL's IF NOT EXISTS where
    possible, and each logical migration is committed independently.
    """
    conn = get_db()
    c = conn.cursor()

    try:
        # ============================================================
        # CORE TABLES
        # ============================================================
        c.execute("""
            CREATE TABLE IF NOT EXISTS employees (
                id SERIAL PRIMARY KEY,
                name TEXT,
                email TEXT,
                password TEXT,
                role TEXT,
                phone TEXT,
                department TEXT,
                profile_pic TEXT,
                theme TEXT DEFAULT 'light'
            )
        """)

        c.execute("""
            ALTER TABLE employees
            ADD COLUMN IF NOT EXISTS birthday DATE
        """)

        # Birthday visibility controls whether a staff member appears in
        # SALT Connect's Upcoming Birthdays section. Existing employees
        # remain visible by default so this migration does not hide birthdays.
        c.execute("""
            ALTER TABLE employees
            ADD COLUMN IF NOT EXISTS birthday_visible BOOLEAN DEFAULT TRUE
        """)

        c.execute("""
            UPDATE employees
            SET birthday_visible=TRUE
            WHERE birthday_visible IS NULL
        """)

        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_employees_birthday
            ON employees (birthday)
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id SERIAL PRIMARY KEY,
                employee_id INTEGER,
                clock_in TEXT,
                clock_out TEXT,
                latitude TEXT,
                longitude TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                title TEXT,
                description TEXT,
                assigned_to INTEGER,
                deadline TEXT,
                status TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                user_id INTEGER,
                message TEXT,
                is_read BOOLEAN DEFAULT FALSE,
                created_at TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL
                    REFERENCES employees(id)
                    ON DELETE CASCADE,
                endpoint TEXT NOT NULL UNIQUE,
                subscription JSONB NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS announcements (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                audience TEXT DEFAULT 'everyone',
                file_name TEXT,
                file_path TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS user_presence (
                user_id INTEGER PRIMARY KEY
                    REFERENCES employees(id)
                    ON DELETE CASCADE,
                online BOOLEAN DEFAULT FALSE,
                last_seen TIMESTAMP
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS task_comments (
                id SERIAL PRIMARY KEY,
                task_id INTEGER,
                sender_id INTEGER,
                sender_role TEXT,
                message TEXT,
                parent_comment_id INTEGER,
                created_at TEXT
            )
        """)

        # ============================================================
        # EMPLOYEE MIGRATIONS
        # ============================================================
        c.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS phone TEXT")
        c.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS department TEXT")
        c.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS profile_pic TEXT")
        c.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS theme TEXT DEFAULT 'light'")
        c.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS position TEXT")
        c.execute("""
            ALTER TABLE employees
            ADD COLUMN IF NOT EXISTS can_approve_requests BOOLEAN DEFAULT FALSE
        """)
        c.execute("""
            ALTER TABLE employees
            ADD COLUMN IF NOT EXISTS immediate_supervisor_id INTEGER
        """)
        c.execute("""
            ALTER TABLE employees
            ADD COLUMN IF NOT EXISTS signature_path TEXT
        """)
        c.execute("""
            ALTER TABLE employees
            ADD COLUMN IF NOT EXISTS profile_pic_public_id TEXT
        """)
        conn.commit()

        # ============================================================
        # ANNOUNCEMENT MIGRATIONS
        # ============================================================
        c.execute("""
            ALTER TABLE announcements
            ADD COLUMN IF NOT EXISTS file_path TEXT
        """)
        c.execute("""
            ALTER TABLE announcements
            ADD COLUMN IF NOT EXISTS file_name TEXT
        """)
        c.execute("""
            ALTER TABLE announcements
            ADD COLUMN IF NOT EXISTS cloudinary_public_id TEXT
        """)
        c.execute("""
            ALTER TABLE announcements
            ADD COLUMN IF NOT EXISTS cloudinary_resource_type TEXT
        """)
        c.execute("""
            ALTER TABLE announcements
            ADD COLUMN IF NOT EXISTS cloudinary_asset_id TEXT
        """)
        c.execute("""
            ALTER TABLE announcements
            ADD COLUMN IF NOT EXISTS audience TEXT DEFAULT 'everyone'
        """)
        c.execute("""
            ALTER TABLE announcements
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP
        """)

        c.execute("""
            UPDATE announcements
            SET audience = 'everyone'
            WHERE audience IS NULL OR audience = ''
        """)

        c.execute("""
            UPDATE announcements
            SET updated_at = created_at::timestamp
            WHERE updated_at IS NULL
        """)

        conn.commit()

        # ============================================================
        # TASK MIGRATIONS
        # ============================================================
        c.execute("""
            ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS created_by INTEGER
        """)
        c.execute("""
            ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS created_at TIMESTAMP
        """)
        c.execute("""
            ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP
        """)
        c.execute("""
            ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS carried_forward BOOLEAN DEFAULT FALSE
        """)
        c.execute("""
            ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS original_deadline TEXT
        """)
        c.execute("""
            ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS note TEXT
        """)
        c.execute("""
            ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS reply TEXT
        """)
        c.execute("""
            ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS admin_reply TEXT
        """)
        c.execute("""
            ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS task_scope TEXT DEFAULT 'personal'
        """)
        c.execute("""
            ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS admin_deleted BOOLEAN DEFAULT FALSE
        """)
        c.execute("""
            ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS employee_deleted BOOLEAN DEFAULT FALSE
        """)
        # Task priority: safe, idempotent PostgreSQL migration.
        # Existing tasks are backfilled to Medium; new tasks default to Medium.
        c.execute("""
            ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS priority TEXT DEFAULT 'Medium'
        """)
        c.execute("""
            UPDATE tasks
            SET priority = 'Medium'
            WHERE priority IS NULL OR priority NOT IN ('High', 'Medium', 'Low')
        """)
        c.execute("""
            ALTER TABLE tasks
            ALTER COLUMN priority SET DEFAULT 'Medium'
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_priority
            ON tasks (priority)
        """)

        c.execute("""
            UPDATE tasks
            SET status = 'Pending'
            WHERE status IS NULL OR status = ''
        """)

        c.execute("""
            UPDATE tasks
            SET admin_deleted = FALSE
            WHERE admin_deleted IS NULL
        """)

        c.execute("""
            UPDATE tasks
            SET employee_deleted = FALSE
            WHERE employee_deleted IS NULL
        """)

        conn.commit()

        # ============================================================
        # TASK COMMENT MIGRATIONS
        # ============================================================
        c.execute("""
            ALTER TABLE task_comments
            ADD COLUMN IF NOT EXISTS visibility TEXT DEFAULT 'public'
        """)
        c.execute("""
            ALTER TABLE task_comments
            ADD COLUMN IF NOT EXISTS comment_type TEXT DEFAULT 'reply'
        """)

        conn.commit()

        # ============================================================
        # GAMIFICATION / REWARDS
        # ============================================================
        c.execute("""
            CREATE TABLE IF NOT EXISTS employee_gamification (
                employee_id INTEGER PRIMARY KEY
                    REFERENCES employees(id)
                    ON DELETE CASCADE,
                xp INTEGER NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 1,
                current_streak INTEGER NOT NULL DEFAULT 0,
                longest_streak INTEGER NOT NULL DEFAULT 0,
                last_attendance_date DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS xp_transactions (
                id SERIAL PRIMARY KEY,
                employee_id INTEGER NOT NULL
                    REFERENCES employees(id)
                    ON DELETE CASCADE,
                xp INTEGER NOT NULL,
                reason TEXT NOT NULL,
                reference_type TEXT,
                reference_key TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(employee_id, reference_type, reference_key)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                id SERIAL PRIMARY KEY,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                icon TEXT DEFAULT 'fa-trophy',
                xp_reward INTEGER NOT NULL DEFAULT 0
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS employee_achievements (
                employee_id INTEGER NOT NULL
                    REFERENCES employees(id)
                    ON DELETE CASCADE,
                achievement_id INTEGER NOT NULL
                    REFERENCES achievements(id)
                    ON DELETE CASCADE,
                earned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(employee_id, achievement_id)
            )
        """)


        achievements_seed = [
            ('first_step', 'First Step',
             'Complete your first attendance check-in.',
             'fa-shoe-prints', 25),

            ('task_finisher', 'Task Finisher',
             'Complete your first task.',
             'fa-check-circle', 25),

            ('five_day_streak', '5-Day Streak',
             'Maintain attendance for five consecutive days.',
             'fa-fire', 50),

            ('ten_day_streak', '10-Day Streak',
             'Maintain attendance for ten consecutive days.',
             'fa-fire-flame-curved', 100),

            ('thirty_day_streak', '30-Day Streak',
             'Maintain attendance for thirty consecutive days.',
             'fa-medal', 300),

            ('ten_tasks', 'Task Champion',
             'Complete ten tasks.',
             'fa-list-check', 100),

            ('early_bird', 'Early Bird',
             'Check in before 9:00 AM.',
             'fa-sun', 15)
        ]

        for code, name, description, icon, reward in achievements_seed:
            c.execute("""
                INSERT INTO achievements
                    (code, name, description, icon, xp_reward)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (code) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    icon = EXCLUDED.icon,
                    xp_reward = EXCLUDED.xp_reward
            """, (code, name, description, icon, reward))

        conn.commit()

    except Exception as e:
        conn.rollback()
        print("DATABASE INITIALIZATION ERROR:", repr(e))
        raise

    finally:
        c.close()
        conn.close()


def get_gamification_data(employee_id):
    """Return dashboard-ready XP, level, streak and achievement data."""
    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)
    try:
        _ensure_gamification_profile(c, employee_id)
        conn.commit()

        c.execute("""
            SELECT xp, level, current_streak, longest_streak, last_attendance_date
            FROM employee_gamification
            WHERE employee_id=%s
        """, (employee_id,))
        profile = c.fetchone() or {
            'xp': 0, 'level': 1, 'current_streak': 0,
            'longest_streak': 0, 'last_attendance_date': None
        }

        xp = int(profile['xp'] or 0)
        level = _calculate_level(xp)
        xp_into_level = xp % 100
        xp_to_next = 100 - xp_into_level

        c.execute("""
            SELECT
                a.code, a.name, a.description, a.icon, a.xp_reward,
                ea.earned_at
            FROM employee_achievements ea
            JOIN achievements a ON a.id=ea.achievement_id
            WHERE ea.employee_id=%s
            ORDER BY ea.earned_at DESC
        """, (employee_id,))
        achievements = c.fetchall()

        c.execute("""
            SELECT xp, reason, created_at
            FROM xp_transactions
            WHERE employee_id=%s
            ORDER BY created_at DESC
            LIMIT 5
        """, (employee_id,))
        recent_rewards = c.fetchall()

        return {
            'xp': xp,
            'level': level,
            'xp_into_level': xp_into_level,
            'xp_to_next': xp_to_next,
            'level_progress': xp_into_level,
            'current_streak': int(profile['current_streak'] or 0),
            'longest_streak': int(profile['longest_streak'] or 0),
            'last_attendance_date': profile['last_attendance_date'],
            'achievements': achievements,
            'recent_rewards': recent_rewards
        }
    finally:
        conn.close()

# -------------------------
# Create admin if not exists
# -------------------------
def create_admin():
    admin_password = os.environ.get("ADMIN_PASSWORD")

    if not admin_password:
        print("ADMIN_PASSWORD not set, skipping admin creation.")
        return

    conn = get_db()
    c = conn.cursor()

    admin_email = "admin@salt.com"

    c.execute("SELECT id FROM employees WHERE email=%s", (admin_email,))
    admin = c.fetchone()

    if not admin:
        c.execute("""
            INSERT INTO employees
            (name, email, password, role, theme)
            VALUES (%s,%s,%s,%s,%s)
        """, (
            "System Administrator",
            admin_email,
            generate_password_hash(admin_password),
            "admin",
            "light"
        ))
        conn.commit()

    conn.close()
# -------------------------
# Routes
# -------------------------


@app.route('/settings/profile', methods=['GET', 'POST'])
def profile_settings():

    if 'user_id' not in session:
        return redirect('/')

    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)

    user_id = session['user_id']

    # ==========================================
    # UPDATE PROFILE
    # ==========================================

    if request.method == 'POST':

        # -------------------------
        # FORM DATA
        # -------------------------

        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        theme = request.form.get('theme', 'light')
        position = request.form.get('position', '').strip()

        # Birthday is stored as a DATE. Keep the full date private in the
        # database; SALT Connect can display only month/day.
        birthday_raw = request.form.get('birthday', '').strip()
        birthday_visible = request.form.get('birthday_visible') == '1'
        birthday = None

        if birthday_raw:
            try:
                birthday = datetime.strptime(
                    birthday_raw,
                    '%Y-%m-%d'
                ).date()
            except ValueError:
                conn.close()
                flash(
                    "Please enter a valid birthday.",
                    "error"
                )
                return redirect('/settings/profile')

            if birthday > datetime.now().date():
                conn.close()
                flash(
                    "Birthday cannot be a future date.",
                    "error"
                )
                return redirect('/settings/profile')

        new_password = request.form.get(
            'new_password',
            ''
        ).strip()

        confirm_password = request.form.get(
            'confirm_password',
            ''
        ).strip()

        current_password = request.form.get(
            'current_password',
            ''
        ).strip()


        # ==========================================
        # GET CURRENT USER
        # ==========================================

        c.execute(
            """
            SELECT
                password,
                department,
                profile_pic,
                profile_pic_public_id
            FROM employees
            WHERE id=%s
            """,
            (user_id,)
        )

        current_user = c.fetchone()

        if not current_user:
            conn.close()

            flash(
                "User account not found.",
                "error"
            )

            return redirect('/settings/profile')


        # ==========================================
        # PROFILE PICTURE
        # ==========================================

        profile_url = None
        profile_public_id = None

        file = request.files.get('image')

        if file and file.filename:

            filename = secure_filename(
                file.filename
            )

            if not filename:
                conn.close()

                flash(
                    "Invalid profile picture.",
                    "error"
                )

                return redirect('/settings/profile')


            ext = filename.rsplit(
                '.',
                1
            )[-1].lower()


            if ext not in {"png", "jpg", "jpeg"}:

                conn.close()

                flash(
                    "Invalid file type. Only PNG, JPG and JPEG are allowed.",
                    "error"
                )

                return redirect('/settings/profile')


            try:

                # -------------------------
                # UPLOAD TO CLOUDINARY
                # -------------------------

                result = uploader.upload(
                    file,
                    folder="salt_portal/profiles",
                    public_id=f"user_{user_id}",
                    resource_type="image",
                    overwrite=True
                )


                profile_url = result.get(
                    "secure_url"
                )

                profile_public_id = result.get(
                    "public_id"
                )


                if not profile_url:

                    raise Exception(
                        "Cloudinary did not return a secure URL."
                    )


            except Exception as e:

                print(
                    "Cloudinary profile upload error:",
                    e
                )

                conn.close()

                flash(
                    "Unable to upload profile picture. Please try again.",
                    "error"
                )

                return redirect('/settings/profile')


        # ==========================================
        # DEPARTMENT CONTROL
        # ==========================================

        if session.get("role") == "admin":

            department = request.form.get(
                'department',
                ''
            ).strip()

        else:

            department = current_user.get(
                'department'
            )


        # ==========================================
        # PASSWORD VALIDATION
        # ==========================================

        update_password = False
        hashed_password = None


        if new_password:

            if not current_password:

                conn.close()

                flash(
                    "Please enter your current password.",
                    "error"
                )

                return redirect('/settings/profile')


            if new_password != confirm_password:

                conn.close()

                flash(
                    "Passwords do not match.",
                    "error"
                )

                return redirect('/settings/profile')


            stored_password = current_user.get(
                'password'
            )


            if not check_password_hash(
                stored_password,
                current_password
            ):

                conn.close()

                flash(
                    "Current password is incorrect.",
                    "error"
                )

                return redirect('/settings/profile')


            hashed_password = generate_password_hash(
                new_password
            )

            update_password = True


        # ==========================================
        # BUILD UPDATE QUERY
        # ==========================================

        query = """
            UPDATE employees
            SET
                name=%s,
                phone=%s,
                position=%s,
                department=%s,
                theme=%s,
                birthday=%s,
                birthday_visible=%s
        """

        params = [
            name,
            phone,
            position,
            department,
            theme,
            birthday,
            birthday_visible
        ]


        # -------------------------
        # PASSWORD
        # -------------------------

        if update_password:

            query += """
                ,
                password=%s
            """

            params.append(
                hashed_password
            )


        # -------------------------
        # PROFILE PICTURE
        # -------------------------

        if profile_url:

            query += """
                ,
                profile_pic=%s,
                profile_pic_public_id=%s
            """

            params.extend([
                profile_url,
                profile_public_id
            ])


        query += """
            WHERE id=%s
        """

        params.append(
            user_id
        )


        # ==========================================
        # SAVE DATABASE
        # ==========================================

        c.execute(
            query,
            tuple(params)
        )

        conn.commit()


        # ==========================================
        # DELETE OLD CLOUDINARY IMAGE
        # ==========================================
        #
        # IMPORTANT:
        # We use the same public_id with overwrite=True.
        # Therefore, Cloudinary has already replaced the
        # old image. DO NOT destroy it here.
        #

        if profile_url:

            print(
                "Profile image uploaded successfully:",
                profile_public_id
            )


        conn.close()


        # ==========================================
        # UPDATE SESSION
        # ==========================================

        session['name'] = name
        session['position'] = position


        flash(
            "Profile updated successfully!",
            "success"
        )

        return redirect(
            '/settings/profile'
        )


    # ==========================================
    # LOAD PROFILE
    # ==========================================

    c.execute(
        """
        SELECT *
        FROM employees
        WHERE id=%s
        """,
        (user_id,)
    )

    user = c.fetchone()

    conn.close()


    return render_template(
        "settings.html",
        user=user,
        role=session.get("role")
    )

@app.context_processor
def inject_user():

    if 'user_id' in session:

        conn = get_db()

        c = conn.cursor(cursor_factory=RealDictCursor)

        c.execute(
            """
            SELECT * 
            FROM employees 
            WHERE id=%s
            """,
            (session['user_id'],)
        )

        user = c.fetchone()

        conn.close()

        return dict(
            user=user,
            current_avatar=(user or {}).get("profile_pic")
        )

    return dict(user=None, current_avatar=None)

# -------------------------
# WEB PUSH
# -------------------------


# -------------------------
# Dashboard
# -------------------------
@app.route('/dashboard')
def dashboard():

    if 'user_id' not in session:
        return redirect('/')


    role = session.get('role')


    conn = get_db()
    c = conn.cursor()


    # -------------------------
    # Attendance logic
    # -------------------------

    today = datetime.now().date()
    today_str = today.strftime("%Y-%m-%d")


    c.execute("""
        SELECT clock_in, clock_out
        FROM attendance
        WHERE employee_id=%s
        AND DATE(clock_in)=DATE(%s)
        ORDER BY id DESC
        LIMIT 1
    """,
    (
        session['user_id'],
        today_str
    ))


    attendance_record = c.fetchone()


    clocked_in = False
    clocked_out = False


    if attendance_record:

        clocked_in = True

        if attendance_record['clock_out'] is not None:
            clocked_out = True


    # -------------------------
    # Dashboard stats
    # -------------------------

    total_employees = 0
    present_today = 0
    absent_today = 0
    clockins_today = 0


    if role == 'admin':

        c.execute(
            "SELECT COUNT(*) AS count FROM employees"
        )

        total_employees = c.fetchone()['count']


        c.execute("""
            SELECT COUNT(DISTINCT employee_id) AS count
            FROM attendance
            WHERE DATE(clock_in)=%s
        """,
        (today_str,))


        present_today = c.fetchone()['count']


        absent_today = total_employees - present_today


        c.execute("""
            SELECT COUNT(*) AS count
            FROM attendance
            WHERE DATE(clock_in)=%s
        """,
        (today_str,))


        clockins_today = c.fetchone()['count']


    else:


        c.execute("""
            SELECT COUNT(*) AS count
            FROM attendance
            WHERE employee_id=%s
            AND DATE(clock_in)=%s
        """,
        (
            session['user_id'],
            today_str
        ))


        clockins_today = c.fetchone()['count']


    # -------------------------
    # Weekly chart data
    # -------------------------

    week_data = []
    labels = []


    for i in range(7):

        day = today - timedelta(days=6-i)

        c.execute("""
            SELECT COUNT(DISTINCT employee_id) AS count
            FROM attendance
            WHERE DATE(clock_in)=%s
        """,
        (
            day.strftime("%Y-%m-%d"),
        ))


        week_data.append(
            c.fetchone()['count']
        )

        labels.append(
            day.strftime("%a")
        )


    # -------------------------
    # Working employees
    # -------------------------

    if role == 'admin':

        c.execute("""
            SELECT 
                employees.name,
                attendance.clock_in,
                attendance.latitude,
                attendance.longitude
            FROM attendance

            JOIN employees
            ON attendance.employee_id = employees.id

            WHERE DATE(clock_in)=%s
            AND clock_out IS NULL
        """,
        (today_str,))


        working_employees = c.fetchall()


    else:

        working_employees = []


    # -------------------------
    # Format clock-in time
    # -------------------------

    formatted_employees = []


    for emp in working_employees:


        emp = dict(emp)


        try:

            dt = emp['clock_in']

            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt)


            emp['clock_in'] = dt.strftime("%H:%M")


        except Exception:
            pass


        formatted_employees.append(emp)


    working_employees = formatted_employees


    # -------------------------
    # Task stats
    # -------------------------

    if role == 'admin':

        c.execute("""
            SELECT COUNT(*) AS count
            FROM tasks
            WHERE status='Completed'
        """)

        tasks_completed = c.fetchone()['count']


        c.execute("""
            SELECT COUNT(*) AS count
            FROM tasks
            WHERE status!='Completed'
        """)

        tasks_pending = c.fetchone()['count']


    else:


        c.execute("""
            SELECT COUNT(*) AS count
            FROM tasks
            WHERE assigned_to=%s
            AND status='Completed'
        """,
        (session['user_id'],))


        tasks_completed = c.fetchone()['count']


        c.execute("""
            SELECT COUNT(*) AS count
            FROM tasks
            WHERE assigned_to=%s
            AND status!='Completed'
        """,
        (session['user_id'],))


        tasks_pending = c.fetchone()['count']


    # -------------------------
    # Notifications
    # -------------------------

    notification_count = get_notification_count(
        session['user_id']
    )

    # -------------------------
    # Request workflow counters
    # -------------------------
    request_pending_approvals = 0
    request_my_pending = 0

    try:
        c.execute("""
            SELECT COUNT(*) AS count
            FROM request_steps
            WHERE approver_id=%s AND status='pending'
        """, (session['user_id'],))
        request_pending_approvals = c.fetchone()['count']

        c.execute("""
            SELECT COUNT(*) AS count
            FROM requests
            WHERE requester_id=%s
              AND status NOT IN ('completed','rejected')
        """, (session['user_id'],))
        request_my_pending = c.fetchone()['count']
    except Exception:
        request_pending_approvals = 0
        request_my_pending = 0


    # -------------------------
    # Announcements
    # -------------------------

    if role == 'admin':

        # Admins can see:
        # - Everyone announcements
        # - Staff announcements
        # - Admin announcements

        c.execute("""
            SELECT
                announcements.id,
                announcements.title,
                announcements.message,
                announcements.created_at,
                announcements.updated_at,
                announcements.audience,
                announcements.file_name,
                announcements.file_path,

                COALESCE(
                    employees.name,
                    'Unknown'
                ) AS created_by_name

            FROM announcements

            LEFT JOIN employees
                ON announcements.created_by = employees.id

            WHERE announcements.audience IN (
                'everyone',
                'staff',
                'admin'
            )

            ORDER BY announcements.created_at DESC

            LIMIT 5
        """)

    else:

        # Staff can see:
        # - Everyone announcements
        # - Staff announcements
        #
        # Admin-only announcements are hidden.

        c.execute("""
            SELECT
                announcements.id,
                announcements.title,
                announcements.message,
                announcements.created_at,
                announcements.updated_at,
                announcements.audience,
                announcements.file_name,
                announcements.file_path,

                COALESCE(
                    employees.name,
                    'Unknown'
                ) AS created_by_name

            FROM announcements

            LEFT JOIN employees
                ON announcements.created_by = employees.id

            WHERE announcements.audience IN (
                'everyone',
                'staff'
            )

            ORDER BY announcements.created_at DESC

            LIMIT 5
        """)

    latest_announcements = c.fetchall()

    # -------------------------
    # Gamification / rewards
    # -------------------------
    gamification = get_gamification_data(
        session['user_id']
    )

    # -------------------------
    # Daily welcome / progress card
    # -------------------------
    welcome_tasks = []
    welcome_tasks_remaining = 0
    welcome_xp_today = 0
    welcome_clock_in = None
    welcome_now = datetime.now()

    try:
        c.execute("""
            SELECT clock_in
            FROM attendance
            WHERE employee_id=%s
              AND DATE(clock_in)=%s
            ORDER BY clock_in DESC
            LIMIT 1
        """, (session['user_id'], today_str))
        welcome_attendance = c.fetchone()

        if welcome_attendance and welcome_attendance.get('clock_in'):
            welcome_clock_in = welcome_attendance['clock_in']

            # PostgreSQL may return TEXT values as strings. Convert
            # them to datetime before the Jinja template calls strftime().
            if isinstance(welcome_clock_in, str):
                try:
                    welcome_clock_in = datetime.fromisoformat(
                        welcome_clock_in.replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    try:
                        welcome_clock_in = datetime.strptime(
                            welcome_clock_in,
                            "%Y-%m-%d %H:%M:%S"
                        )
                    except (ValueError, TypeError):
                        welcome_clock_in = None

        c.execute("""
            SELECT id, title, status, deadline
            FROM tasks
            WHERE assigned_to=%s
              AND status!='Completed'
            ORDER BY
                CASE WHEN deadline IS NULL THEN 1 ELSE 0 END,
                deadline ASC NULLS LAST,
                id DESC
            LIMIT 5
        """, (session['user_id'],))
        welcome_tasks = c.fetchall()
        welcome_tasks_remaining = len(welcome_tasks)

        c.execute("""
            SELECT COALESCE(SUM(xp), 0) AS xp
            FROM xp_transactions
            WHERE employee_id=%s
              AND DATE(created_at)=%s
        """, (session['user_id'], today_str))
        welcome_xp_today = int((c.fetchone() or {}).get('xp') or 0)
    except Exception as e:
        print('DAILY WELCOME DATA ERROR:', repr(e))

    show_daily_welcome = bool(session.pop('show_daily_welcome', False))

    c.close()
    conn.close()


    # -------------------------
    # Employee Locations
    # -------------------------

    employee_locations = []


    for emp in working_employees:

        try:

            lat_f = float(emp['latitude'])
            lon_f = float(emp['longitude'])


        except (TypeError, ValueError):

            continue


        employee_locations.append({

            "name": emp['name'],
            "time": emp['clock_in'],
            "lat": lat_f,
            "lon": lon_f

        })


    return render_template(
        "dashboard.html",

        name=session['name'],
        role=role,

        total_employees=total_employees,
        present_today=present_today,
        absent_today=absent_today,
        clockins_today=clockins_today,

        notification_count=notification_count,

        request_pending_approvals=request_pending_approvals,
        request_my_pending=request_my_pending,

        clocked_in=clocked_in,
        clocked_out=clocked_out,

        week_data=week_data,
        labels=labels,

        working_employees=working_employees,

        tasks_completed=tasks_completed,
        tasks_pending=tasks_pending,

        latest_announcements=latest_announcements,

        employee_locations=employee_locations,

        gamification=gamification,
        show_daily_welcome=show_daily_welcome,
        welcome_tasks=welcome_tasks,
        welcome_tasks_remaining=welcome_tasks_remaining,
        welcome_xp_today=welcome_xp_today,
        welcome_clock_in=welcome_clock_in,
        welcome_now=welcome_now
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


    conn = get_db()
    c = conn.cursor()


    now = datetime.now()


    c.execute("""
        INSERT INTO attendance 
        (
            employee_id,
            clock_in,
            latitude,
            longitude
        )
        VALUES (%s, %s, %s, %s)
        RETURNING id
    """,
    (
        session['user_id'],
        now,
        lat,
        lon
    ))

    attendance_row = c.fetchone()

    conn.commit()
    conn.close()

    # Gamification is processed after the attendance record is safely saved.
    process_attendance_rewards(
        session['user_id'],
        now
    )

    # Show the personalized daily welcome card after a successful clock-in.
    session['show_daily_welcome'] = True

    return redirect('/dashboard')
# -------------------------
# Clock-out
# -------------------------
@app.route('/clockout', methods=['POST'])
def clockout():

    if 'user_id' not in session:
        return redirect('/')


    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)


    c.execute("""
        UPDATE attendance
        SET clock_out=%s
        WHERE employee_id=%s
        AND DATE(clock_in)=CURRENT_DATE
        AND clock_out IS NULL
    """,
    (
        datetime.now(),
        session['user_id']
    ))


    conn.commit()
    conn.close()


    return redirect('/dashboard')


# -------------------------
# Clear all notifications
def get_attendance_date_range(period, start_date_value, end_date_value):
    """
    Return (start_datetime, end_datetime) for the selected filter.

    end_datetime is exclusive.

    Custom dates are treated as whole calendar days:
        From 2026-08-01
        To   2026-08-10

    means:
        >= 2026-08-01 00:00:00
        <  2026-08-11 00:00:00
    """

    today = date.today()

    # ------------------------------------------------------------
    # QUICK FILTERS
    # ------------------------------------------------------------

    if period == "today":

        start_date = today
        end_date = today

    elif period == "yesterday":

        start_date = today - timedelta(days=1)
        end_date = start_date

    elif period == "this_week":

        # Monday -> Sunday
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=6)

    elif period == "last_week":

        this_week_start = today - timedelta(days=today.weekday())

        start_date = this_week_start - timedelta(days=7)
        end_date = this_week_start - timedelta(days=1)

    elif period == "this_month":

        start_date = today.replace(day=1)

        if today.month == 12:
            next_month = date(
                today.year + 1,
                1,
                1
            )
        else:
            next_month = date(
                today.year,
                today.month + 1,
                1
            )

        end_date = next_month - timedelta(days=1)

    elif period == "last_month":

        first_this_month = today.replace(day=1)

        last_day_last_month = (
            first_this_month - timedelta(days=1)
        )

        start_date = last_day_last_month.replace(day=1)
        end_date = last_day_last_month

    # ------------------------------------------------------------
    # CUSTOM DATE RANGE
    # ------------------------------------------------------------

    elif start_date_value or end_date_value:

        try:

            start_date = (
                datetime.strptime(
                    start_date_value,
                    "%Y-%m-%d"
                ).date()
                if start_date_value
                else None
            )

            end_date = (
                datetime.strptime(
                    end_date_value,
                    "%Y-%m-%d"
                ).date()
                if end_date_value
                else None
            )

        except (
            ValueError,
            TypeError
        ):

            start_date = None
            end_date = None

    else:

        start_date = None
        end_date = None

    # ------------------------------------------------------------
    # CONVERT DATES TO DATETIME BOUNDARIES
    # ------------------------------------------------------------

    start_datetime = None
    end_datetime = None

    if start_date:
        start_datetime = datetime.combine(
            start_date,
            datetime.min.time()
        )

    if end_date:
        # End is exclusive, therefore use the next day.
        end_datetime = datetime.combine(
            end_date + timedelta(days=1),
            datetime.min.time()
        )

    return start_datetime, end_datetime


@app.route('/attendance')
def attendance():

    if 'user_id' not in session:
        return redirect('/')


    conn = get_db()

    c = conn.cursor()


    role = session.get('role')


    # ============================================================
    # FILTER VALUES
    # ============================================================

    period = request.args.get(
        "period",
        ""
    ).strip()

    employee_id = request.args.get(
        "employee_id",
        ""
    ).strip()

    status = request.args.get(
        "status",
        ""
    ).strip().lower()

    start_date_value = request.args.get(
        "start_date",
        ""
    ).strip()

    end_date_value = request.args.get(
        "end_date",
        ""
    ).strip()


    # ============================================================
    # DATE RANGE
    # ============================================================

    start_datetime, end_datetime = (
        get_attendance_date_range(
            period,
            start_date_value,
            end_date_value
        )
    )


    # ============================================================
    # BASE QUERY
    # ============================================================

    query = """

        SELECT

            employees.name,

            attendance.clock_in,

            attendance.clock_out

        FROM attendance

        JOIN employees

            ON attendance.employee_id =
               employees.id

        WHERE 1=1

    """


    params = []


    # ============================================================
    # STAFF SECURITY
    #
    # Staff can ONLY see their own attendance.
    # ============================================================

    if role != 'admin':

        query += """

            AND attendance.employee_id = %s

        """

        params.append(
            session['user_id']
        )


    # ============================================================
    # ADMIN → EMPLOYEE FILTER
    # ============================================================

    elif employee_id:

        try:

            selected_employee_id = int(
                employee_id
            )

            query += """

                AND attendance.employee_id = %s

            """

            params.append(
                selected_employee_id
            )

        except (
            ValueError,
            TypeError
        ):

            employee_id = ""


    # ============================================================
    # DATE FILTER
    # ============================================================

    if start_datetime:

        query += """

            AND attendance.clock_in::timestamp >= %s

        """

        params.append(
            start_datetime
        )


    if end_datetime:

        query += """

            AND attendance.clock_in::timestamp < %s

        """

        params.append(
            end_datetime
        )


    # ============================================================
    # STATUS FILTER
    # ============================================================

    if status == "active":

        query += """

            AND attendance.clock_out IS NULL

        """

    elif status == "completed":

        query += """

            AND attendance.clock_out IS NOT NULL

        """


    # ============================================================
    # ORDER
    # ============================================================

    query += """

        ORDER BY attendance.clock_in DESC

    """


    c.execute(
        query,
        params
    )


    raw_records = c.fetchall()


    # ============================================================
    # ADMIN EMPLOYEE LIST
    # ============================================================

    employees = []


    if role == 'admin':

        c.execute("""

            SELECT
                id,
                name

            FROM employees

            ORDER BY name ASC

        """)

        employees = c.fetchall()


    conn.close()


    # ============================================================
    # FORMAT DATA
    # ============================================================

    records = []


    for r in raw_records:

        clock_in = format_datetime(
            r["clock_in"]
        )

        clock_out = format_datetime(
            r["clock_out"]
        )


        records.append({

            "name":
                r["name"]
                if role == 'admin'
                else None,

            "clock_in_date":
                clock_in["date"],

            "clock_in_time":
                clock_in["time"],

            "clock_out_date":
                clock_out["date"],

            "clock_out_time":
                clock_out["time"],

            "is_active":
                r["clock_out"] is None

        })


    # ============================================================
    # RENDER
    # ============================================================

    return render_template(

        "attendance.html",

        records=records,

        role=role,

        employees=employees,

        selected_employee=employee_id,

        status=status,

        period=period,

        start_date=start_date_value,

        end_date=end_date_value

    )


# ============================================================
# EXPORT ATTENDANCE
# ============================================================

@app.route('/export/attendance')
def export_attendance():

    if 'user_id' not in session:
        return redirect('/')


    role = session.get('role')


    conn = get_db()

    c = conn.cursor()


    # ============================================================
    # SAME FILTERS AS ATTENDANCE PAGE
    # ============================================================

    period = request.args.get(
        "period",
        ""
    ).strip()

    employee_id = request.args.get(
        "employee_id",
        ""
    ).strip()

    status = request.args.get(
        "status",
        ""
    ).strip().lower()

    start_date_value = request.args.get(
        "start_date",
        ""
    ).strip()

    end_date_value = request.args.get(
        "end_date",
        ""
    ).strip()


    start_datetime, end_datetime = (
        get_attendance_date_range(
            period,
            start_date_value,
            end_date_value
        )
    )


    # ============================================================
    # BASE QUERY
    # ============================================================

    query = """

        SELECT

            employees.name,

            attendance.clock_in,

            attendance.clock_out

        FROM attendance

        JOIN employees

            ON attendance.employee_id =
               employees.id

        WHERE 1=1

    """


    params = []


    # ============================================================
    # STAFF SECURITY
    # ============================================================

    if role != 'admin':

        query += """

            AND attendance.employee_id = %s

        """

        params.append(
            session['user_id']
        )


    # ============================================================
    # ADMIN → EMPLOYEE FILTER
    # ============================================================

    elif employee_id:

        try:

            selected_employee_id = int(
                employee_id
            )

            query += """

                AND attendance.employee_id = %s

            """

            params.append(
                selected_employee_id
            )

        except (
            ValueError,
            TypeError
        ):

            employee_id = ""


    # ============================================================
    # DATE FILTER
    # ============================================================

    if start_datetime:

        query += """

            AND attendance.clock_in::timestamp >= %s

        """

        params.append(
            start_datetime
        )


    if end_datetime:

        query += """

            AND attendance.clock_in::timestamp < %s

        """

        params.append(
            end_datetime
        )


    # ============================================================
    # STATUS FILTER
    # ============================================================

    if status == "active":

        query += """

            AND attendance.clock_out IS NULL

        """

    elif status == "completed":

        query += """

            AND attendance.clock_out IS NOT NULL

        """


    query += """

        ORDER BY attendance.clock_in DESC

    """


    c.execute(
        query,
        params
    )


    records = c.fetchall()


    conn.close()


    # ============================================================
    # CREATE EXCEL
    # ============================================================

    wb = Workbook()

    ws = wb.active

    ws.title = "Attendance"


    # ============================================================
    # HEADERS
    # ============================================================

    if role == 'admin':

        ws.append([

            "Employee",
            "Clock In",
            "Clock Out",
            "Status"

        ])

    else:

        ws.append([

            "Clock In",
            "Clock Out",
            "Status"

        ])


    # ============================================================
    # DATA
    # ============================================================

    for r in records:

        clock_in = r["clock_in"]

        clock_out = r["clock_out"]


        status_text = (

            "Active"

            if clock_out is None

            else "Completed"

        )


        if role == 'admin':

            ws.append([

                r["name"],

                clock_in,

                clock_out
                or "Still working",

                status_text

            ])

        else:

            ws.append([

                clock_in,

                clock_out
                or "Still working",

                status_text

            ])


    # ============================================================
    # BASIC EXCEL FORMATTING
    # ============================================================

    for cell in ws[1]:

        cell.font = cell.font.copy(
            bold=True
        )


    ws.freeze_panes = "A2"


    for column in ws.columns:

        max_length = 0

        column_letter = column[0].column_letter

        for cell in column:

            value = cell.value

            if value is not None:

                max_length = max(
                    max_length,
                    len(str(value))
                )

        ws.column_dimensions[
            column_letter
        ].width = min(
            max_length + 3,
            35
        )


    # ============================================================
    # SAVE TO MEMORY
    # ============================================================

    file_stream = io.BytesIO()

    wb.save(
        file_stream
    )

    file_stream.seek(0)


    return send_file(

        file_stream,

        as_attachment=True,

        download_name="attendance.xlsx",

        mimetype=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        )

    )


@app.route('/admin/employees')
def admin_employees():

    if 'role' not in session or session['role'] != 'admin':
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

@app.route("/admin/add_employee", methods=["GET", "POST"])
def add_employee():


    if 'role' not in session or session['role'] != 'admin':
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

@app.route('/admin/save_employee', methods=['POST'])
def save_employee():

    if session.get('role') != 'admin':
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


@app.route('/admin/edit_employee/<int:id>', methods=['GET', 'POST'])
def edit_employee(id):

    if session.get('role') != 'admin':
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


@app.route('/admin/reset_password/<int:id>', methods=['POST'])
def reset_employee_password(id):

    if session.get('role') != 'admin':
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


@app.route('/admin/delete_employee/<int:id>', methods=['POST'])
def delete_employee(id):

    if session.get('role') != 'admin':
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


# =====================================================
# ANNOUNCEMENT DIRECT CLOUDINARY UPLOAD
# =====================================================

ANNOUNCEMENT_MAX_FILE_SIZE = 10 * 1024 * 1024

ANNOUNCEMENT_ALLOWED_EXTENSIONS = {
    'pdf', 'doc', 'docx', 'xls', 'xlsx',
    'ppt', 'pptx', 'txt', 'csv',
    'jpg', 'jpeg', 'png', 'gif', 'webp'
}


def _announcement_admin_required():
    return (
        'user_id' in session
        and session.get('role') == 'admin'
    )


def _cloudinary_config_values():
    config = cloudinary.config()

    return (
        config.cloud_name,
        config.api_key,
        config.api_secret
    )


def _delete_cloudinary_asset(public_id, resource_type):
    """
    Best-effort deletion of an announcement asset.

    New direct-upload announcements store the public_id and resource_type,
    so cleanup does not need to guess from a delivery URL.
    """
    if not public_id:
        return

    try:
        uploader.destroy(
            public_id,
            resource_type=resource_type or 'image',
            type='upload',
            invalidate=True
        )
    except Exception as exc:
        print(
            "CLOUDINARY ANNOUNCEMENT CLEANUP ERROR:",
            repr(exc)
        )


def _verify_cloudinary_asset(
    public_id,
    resource_type,
    secure_url,
    original_name
):
    """
    Verify the uploaded Cloudinary asset server-side.

    The browser never sends the file through Flask, so the finalization
    endpoint verifies the actual Cloudinary asset metadata before the
    announcement is saved.
    """

    if not public_id or not secure_url:
        raise ValueError(
            "Cloudinary did not return a valid uploaded asset."
        )

    cloud_name, _, _ = _cloudinary_config_values()

    expected_prefix = (
        f"https://res.cloudinary.com/{cloud_name}/"
    )

    if not secure_url.startswith(expected_prefix):
        raise ValueError(
            "Invalid Cloudinary asset URL."
        )

    extension = (
        secure_filename(original_name or "")
        .rsplit('.', 1)[1].lower()
        if '.' in secure_filename(original_name or "")
        else ''
    )

    if extension not in ANNOUNCEMENT_ALLOWED_EXTENSIONS:
        raise ValueError(
            "Invalid attachment type."
        )

    asset = cloudinary_api.resource(
        public_id,
        resource_type=resource_type or 'image',
        type='upload'
    )

    actual_bytes = int(
        asset.get('bytes') or 0
    )

    if actual_bytes > ANNOUNCEMENT_MAX_FILE_SIZE:

        _delete_cloudinary_asset(
            public_id,
            resource_type
        )

        raise ValueError(
            "Attachment is too large. Maximum allowed size is 10 MB."
        )

    actual_format = (
        str(asset.get('format') or '').lower()
    )

    # Cloudinary may represent some document formats differently,
    # so the original extension remains the primary allow-list check.
    if not actual_format:
        raise ValueError(
            "Cloudinary could not verify the attachment format."
        )

    return {
        "bytes": actual_bytes,
        "format": actual_format,
        "public_id": public_id,
        "resource_type": resource_type or 'image',
        "secure_url": secure_url,
        "asset_id": asset.get('asset_id')
    }


@app.route(
    '/admin/announcements/upload-signature',
    methods=['POST']
)
def announcement_upload_signature():

    if not _announcement_admin_required():
        return jsonify({
            "status": "error",
            "message": "Access denied."
        }), 403

    data = request.get_json(
        silent=True
    ) or {}

    audience = str(
        data.get('audience') or 'everyone'
    ).strip().lower()

    if audience not in (
        'everyone',
        'staff',
        'admin'
    ):
        audience = 'everyone'

    cloud_name, api_key, api_secret = (
        _cloudinary_config_values()
    )

    if not cloud_name or not api_key or not api_secret:
        return jsonify({
            "status": "error",
            "message": "Cloudinary is not configured on the server."
        }), 500

    # Use a SIGNED upload preset so Cloudinary itself can enforce
    # the 10 MB limit and allowed formats.
    upload_preset = os.environ.get(
        "CLOUDINARY_ANNOUNCEMENT_UPLOAD_PRESET"
    )

    if not upload_preset:
        return jsonify({
            "status": "error",
            "message": (
                "CLOUDINARY_ANNOUNCEMENT_UPLOAD_PRESET "
                "is not configured."
            )
        }), 500

    timestamp = int(
        time.time()
    )

    folder = (
        f"salt_portal/announcements/{audience}"
    )

    # Cloudinary requires the same signed fields to be sent unchanged
    # with the browser upload.
    params_to_sign = {
        "folder": folder,
        "timestamp": timestamp,
        "upload_preset": upload_preset
    }

    signature = cloudinary.utils.api_sign_request(
        params_to_sign,
        api_secret
    )

    return jsonify({
        "status": "success",
        "cloud_name": cloud_name,
        "api_key": api_key,
        "timestamp": timestamp,
        "signature": signature,
        "folder": folder,
        "upload_preset": upload_preset,
        "resource_type": "auto",
        "max_file_size": ANNOUNCEMENT_MAX_FILE_SIZE
    })


@app.route(
    '/admin/announcements',
    methods=['GET', 'POST']
)
def admin_announcements():

    # -------------------------
    # ACCESS CONTROL
    # -------------------------
    if 'user_id' not in session:
        return redirect('/')

    if session.get('role') != 'admin':
        return "Access Denied", 403

    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)

    # =====================================================
    # CREATE ANNOUNCEMENT
    # =====================================================
    if request.method == 'POST':

        # The new browser flow sends JSON only.
        # No multipart file is ever sent to Flask.
        payload = request.get_json(
            silent=True
        )

        if payload is None:
            conn.close()

            return jsonify({
                "status": "error",
                "message": (
                    "Please use the current announcement form. "
                    "File uploads now go directly to Cloudinary."
                )
            }), 400

        title = str(
            payload.get('title') or ''
        ).strip()

        message = str(
            payload.get('message') or ''
        ).strip()

        audience = str(
            payload.get('audience') or 'everyone'
        ).strip().lower()

        if not title:
            conn.close()

            return jsonify({
                "status": "error",
                "message": "Please enter an announcement title."
            }), 400

        if not message:
            conn.close()

            return jsonify({
                "status": "error",
                "message": "Please enter an announcement message."
            }), 400

        if audience not in (
            'everyone',
            'staff',
            'admin'
        ):
            audience = 'everyone'

        uploaded_asset = (
            payload.get('file')
            if isinstance(payload.get('file'), dict)
            else None
        )

        file_name = None
        file_path = None
        public_id = None
        resource_type = None
        asset_id = None

        # -------------------------
        # VERIFY CLOUDINARY ASSET
        # -------------------------
        if uploaded_asset:

            file_name = secure_filename(
                str(
                    uploaded_asset.get('name') or ''
                )
            )

            file_path = str(
                uploaded_asset.get('secure_url') or ''
            )

            public_id = str(
                uploaded_asset.get('public_id') or ''
            )

            resource_type = str(
                uploaded_asset.get('resource_type')
                or 'image'
            )

            try:

                verified = _verify_cloudinary_asset(
                    public_id,
                    resource_type,
                    file_path,
                    file_name
                )

                asset_id = verified.get(
                    "asset_id"
                )

            except Exception as exc:

                _delete_cloudinary_asset(
                    public_id,
                    resource_type
                )

                conn.close()

                print(
                    "ANNOUNCEMENT ASSET VERIFICATION ERROR:",
                    repr(exc)
                )

                return jsonify({
                    "status": "error",
                    "message": str(exc)
                }), 400

        # -------------------------
        # CREATE DATABASE RECORD
        # -------------------------
        now = datetime.now()

        try:

            c.execute("""
                INSERT INTO announcements
                (
                    title,
                    message,
                    created_by,
                    created_at,
                    updated_at,
                    audience,
                    file_name,
                    file_path,
                    cloudinary_public_id,
                    cloudinary_resource_type,
                    cloudinary_asset_id
                )
                VALUES
                (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                )
            """, (
                title,
                message,
                session['user_id'],
                now,
                now,
                audience,
                file_name,
                file_path,
                public_id,
                resource_type,
                asset_id
            ))

            conn.commit()

        except Exception as exc:

            conn.rollback()

            if public_id:
                _delete_cloudinary_asset(
                    public_id,
                    resource_type
                )

            print(
                "CREATE ANNOUNCEMENT DATABASE ERROR:",
                repr(exc)
            )

            conn.close()

            return jsonify({
                "status": "error",
                "message": f"Database error: {str(exc)}"
            }), 500

        conn.close()

        # Notifications happen in the background so the admin
        # receives the success response immediately.
        socketio.start_background_task(
            notify_announcement,
            audience,
            f"New Announcement: {title}",
            session['user_id']
        )

        return jsonify({
            "status": "success",
            "message": "Announcement published successfully."
        })

    # =====================================================
    # SEARCH
    # =====================================================
    search = request.args.get(
        'search',
        ''
    ).strip()

    # =====================================================
    # AUDIENCE FILTER
    # =====================================================
    audience_filter = request.args.get(
        'audience',
        'all'
    ).strip().lower()

    # Only accept valid filters
    if audience_filter not in (
        'all',
        'everyone',
        'staff',
        'admin'
    ):
        audience_filter = 'all'

    # =====================================================
    # BUILD ANNOUNCEMENT QUERY
    # =====================================================
    query = """
        SELECT
            announcements.id,
            announcements.title,
            announcements.message,
            announcements.created_by,
            announcements.created_at,
            announcements.updated_at,
            announcements.audience,
            announcements.file_name,
            announcements.file_path,

            COALESCE(
                employees.name,
                'Unknown'
            ) AS name

        FROM announcements

        LEFT JOIN employees
            ON announcements.created_by = employees.id

        WHERE 1=1
    """

    params = []

    # -------------------------
    # SEARCH FILTER
    # -------------------------
    if search:

        query += """
            AND (
                announcements.title ILIKE %s
                OR announcements.message ILIKE %s
                OR employees.name ILIKE %s
            )
        """

        search_value = f"%{search}%"

        params.extend([
            search_value,
            search_value,
            search_value
        ])

    # -------------------------
    # AUDIENCE FILTER
    # -------------------------
    if audience_filter != 'all':

        query += """
            AND announcements.audience=%s
        """

        params.append(
            audience_filter
        )

    # -------------------------
    # SORT
    # -------------------------
    query += """
        ORDER BY announcements.created_at DESC
    """

    c.execute(
        query,
        params
    )

    announcements = c.fetchall()

    # =====================================================
    # ANNOUNCEMENT STATISTICS
    # =====================================================

    # Total
    c.execute("""
        SELECT COUNT(*) AS count
        FROM announcements
    """)

    total_announcements = c.fetchone()['count']

    # Everyone
    c.execute("""
        SELECT COUNT(*) AS count
        FROM announcements
        WHERE audience='everyone'
           OR audience IS NULL
    """)

    everyone_count = c.fetchone()['count']

    # Staff
    c.execute("""
        SELECT COUNT(*) AS count
        FROM announcements
        WHERE audience='staff'
    """)

    staff_count = c.fetchone()['count']

    # Admin
    c.execute("""
        SELECT COUNT(*) AS count
        FROM announcements
        WHERE audience='admin'
    """)

    admin_count = c.fetchone()['count']

    conn.close()

    # =====================================================
    # RENDER PAGE
    # =====================================================
    return render_template(
        "admin_announcements.html",

        announcements=announcements,

        search=search,

        audience_filter=audience_filter,

        total_announcements=total_announcements,

        everyone_count=everyone_count,

        staff_count=staff_count,

        admin_count=admin_count
    )

# =====================================================
# DOWNLOAD ANNOUNCEMENT ATTACHMENT
# =====================================================

@app.route('/admin/announcement/file/<int:id>')
def download_announcement_file(id):

    if 'user_id' not in session:
        return redirect('/')

    conn = get_db()
    c = conn.cursor(
        cursor_factory=RealDictCursor
    )

    c.execute("""
        SELECT file_path, file_name
        FROM announcements
        WHERE id=%s
    """, (id,))

    announcement = c.fetchone()
    conn.close()

    if not announcement:
        return "Announcement not found", 404

    if not announcement['file_path']:
        return "No attachment", 404

    cloudinary_url = announcement['file_path']

    # View mode: preserve the original secure delivery URL.
    # Download mode: ask Cloudinary to force attachment delivery.
    if request.args.get("download") == "1":
        if "/upload/" in cloudinary_url:
            cloudinary_url = cloudinary_url.replace(
                "/upload/",
                "/upload/fl_attachment/"
            )

    return redirect(cloudinary_url)

# =====================================================
# UPDATE ANNOUNCEMENT
# =====================================================

@app.route(
    '/admin/update_announcement/<int:id>',
    methods=['POST']
)
def update_announcement(id):

    if 'user_id' not in session:
        return jsonify({
            "status": "error",
            "message": "Please log in."
        }), 401

    if session.get('role') != 'admin':
        return jsonify({
            "status": "error",
            "message": "Access denied."
        }), 403

    payload = request.get_json(
        silent=True
    )

    if payload is None:
        return jsonify({
            "status": "error",
            "message": (
                "Please use the current announcement editor."
            )
        }), 400

    title = str(
        payload.get('title') or ''
    ).strip()

    message = str(
        payload.get('message') or ''
    ).strip()

    audience = str(
        payload.get('audience') or 'everyone'
    ).strip().lower()

    remove_file = bool(
        payload.get('remove_file')
    )

    uploaded_asset = (
        payload.get('file')
        if isinstance(payload.get('file'), dict)
        else None
    )

    if not title:
        return jsonify({
            "status": "error",
            "message": "Announcement title is required."
        }), 400

    if not message:
        return jsonify({
            "status": "error",
            "message": "Announcement message is required."
        }), 400

    if audience not in (
        'everyone',
        'staff',
        'admin'
    ):
        audience = 'everyone'

    conn = get_db()
    c = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        c.execute("""
            SELECT
                id,
                title,
                message,
                audience,
                file_name,
                file_path,
                cloudinary_public_id,
                cloudinary_resource_type,
                cloudinary_asset_id
            FROM announcements
            WHERE id=%s
        """, (id,))

        announcement = c.fetchone()

        if not announcement:
            return jsonify({
                "status": "error",
                "message": "Announcement not found."
            }), 404

        old_public_id = (
            announcement['cloudinary_public_id']
        )

        old_resource_type = (
            announcement['cloudinary_resource_type']
            or 'image'
        )

        new_file_name = announcement['file_name']
        new_file_path = announcement['file_path']
        new_public_id = old_public_id
        new_resource_type = old_resource_type
        new_asset_id = announcement['cloudinary_asset_id']

        uploaded_public_id = None
        uploaded_resource_type = None

        # -------------------------
        # REPLACEMENT ATTACHMENT
        # -------------------------
        if uploaded_asset:

            new_file_name = secure_filename(
                str(
                    uploaded_asset.get('name') or ''
                )
            )

            new_file_path = str(
                uploaded_asset.get('secure_url') or ''
            )

            uploaded_public_id = str(
                uploaded_asset.get('public_id') or ''
            )

            uploaded_resource_type = str(
                uploaded_asset.get('resource_type')
                or 'image'
            )

            try:

                verified = _verify_cloudinary_asset(
                    uploaded_public_id,
                    uploaded_resource_type,
                    new_file_path,
                    new_file_name
                )

                new_public_id = verified['public_id']
                new_resource_type = verified['resource_type']
                new_asset_id = verified.get('asset_id')

            except Exception as exc:

                _delete_cloudinary_asset(
                    uploaded_public_id,
                    uploaded_resource_type
                )

                return jsonify({
                    "status": "error",
                    "message": str(exc)
                }), 400

        elif remove_file:

            new_file_name = None
            new_file_path = None
            new_public_id = None
            new_resource_type = None
            new_asset_id = None

        # -------------------------
        # UPDATE DATABASE
        # -------------------------
        c.execute("""
            UPDATE announcements
            SET
                title=%s,
                message=%s,
                audience=%s,
                updated_at=%s,
                file_name=%s,
                file_path=%s,
                cloudinary_public_id=%s,
                cloudinary_resource_type=%s,
                cloudinary_asset_id=%s
            WHERE id=%s
        """, (
            title,
            message,
            audience,
            datetime.now(),
            new_file_name,
            new_file_path,
            new_public_id,
            new_resource_type,
            new_asset_id,
            id
        ))

        conn.commit()

        # Delete the previous Cloudinary asset only after the
        # database has successfully switched to the new one.
        if (
            uploaded_asset
            and old_public_id
            and old_public_id != new_public_id
        ):
            _delete_cloudinary_asset(
                old_public_id,
                old_resource_type
            )

        if (
            remove_file
            and old_public_id
        ):
            _delete_cloudinary_asset(
                old_public_id,
                old_resource_type
            )

        socketio.start_background_task(
            notify_announcement,
            audience,
            f"Announcement Updated: {title}",
            session['user_id']
        )

        return jsonify({
            "status": "success",
            "message": "Announcement updated successfully."
        })

    except Exception as exc:

        conn.rollback()

        # If a newly uploaded asset was not committed, clean it up.
        if uploaded_public_id:
            _delete_cloudinary_asset(
                uploaded_public_id,
                uploaded_resource_type
            )

        print(
            "UPDATE ANNOUNCEMENT ERROR:",
            repr(exc)
        )

        return jsonify({
            "status": "error",
            "message": "Failed to update announcement."
        }), 500

    finally:

        conn.close()

# =====================================================
# DELETE ANNOUNCEMENT
# =====================================================

@app.route(
    '/admin/delete_announcement/<int:id>',
    methods=['POST']
)
def delete_announcement(id):

    if 'user_id' not in session:
        return jsonify({
            "status": "error",
            "message": "Unauthorized"
        }), 401

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

        c.execute("""
            SELECT
                id,
                title,
                cloudinary_public_id,
                cloudinary_resource_type
            FROM announcements
            WHERE id=%s
        """, (id,))

        announcement = c.fetchone()

        if not announcement:
            return jsonify({
                "status": "error",
                "message": "Announcement not found."
            }), 404

        c.execute("""
            DELETE FROM announcements
            WHERE id=%s
        """, (id,))

        conn.commit()

        if announcement['cloudinary_public_id']:
            _delete_cloudinary_asset(
                announcement['cloudinary_public_id'],
                announcement['cloudinary_resource_type']
            )

        return jsonify({
            "status": "success",
            "message": "Announcement deleted successfully."
        })

    except Exception as exc:

        conn.rollback()

        print(
            "DELETE ANNOUNCEMENT ERROR:",
            repr(exc)
        )

        return jsonify({
            "status": "error",
            "message": "Unable to delete announcement."
        }), 500

    finally:
        conn.close()


# SALTY AI API (FIXED + OPTIMIZED)
@app.route('/api/salty', methods=['POST'])
def salty_ai():

    if 'user_id' not in session:
        return jsonify({"reply": "Unauthorized"}), 403

    data = request.get_json() or {}
    msg = data.get("message", "").lower().strip()

    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)

    today = datetime.now().date()

    # -------------------------
    # CORE DATA
    # -------------------------

    c.execute("SELECT COUNT(*) AS total FROM employees")
    total = c.fetchone()["total"]

    c.execute("""
        SELECT COUNT(DISTINCT employee_id) AS present
        FROM attendance
        WHERE DATE(clock_in)=%s
    """, (today,))

    present = c.fetchone()["present"]

    absent = total - present

    c.execute("""
        SELECT e.name
        FROM employees e
        JOIN attendance a
            ON e.id = a.employee_id
        WHERE DATE(a.clock_in)=%s
        AND a.clock_out IS NULL
    """, (today,))

    working = [row["name"] for row in c.fetchall()]

    conn.close()

    # -------------------------
    # Navigation
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
    # Questions
    # -------------------------

    if "who is working" in msg:

        return jsonify({
            "reply": ", ".join(working) if working else "No one is currently working.",
            "type": "info"
        })

    if msg in ["working", "currently working"]:

        return jsonify({
            "reply": ", ".join(working) if working else "No active workers.",
            "type": "info"
        })

    if "present" in msg:

        return jsonify({
            "reply": f"{present} employees are present today.",
            "type": "stats"
        })

    if "absent" in msg:

        return jsonify({
            "reply": f"{absent} employees are absent today.",
            "type": "stats"
        })

    if "attendance" in msg:

        return jsonify({
            "reply": f"{present} present, {absent} absent today.",
            "type": "stats"
        })

    if "help" in msg:

        return jsonify({
            "reply": "Try: open dashboard, attendance, who is working, present, absent, open tasks",
            "type": "help"
        })

    return jsonify({
        "reply": "I can help with dashboard navigation, attendance, employees and tasks.",
        "type": "fallback"
    })


@app.route('/api/live-dashboard')
def live_dashboard():

    if 'user_id' not in session:
        return jsonify({
            "error":"unauthorized"
        }),403

    conn = get_db()

    c = conn.cursor(cursor_factory=RealDictCursor)

    today = datetime.now().date()

    c.execute("""
        SELECT COUNT(*) AS total
        FROM employees
    """)

    total = c.fetchone()["total"]

    c.execute("""
        SELECT COUNT(DISTINCT employee_id) AS present
        FROM attendance
        WHERE DATE(clock_in)=%s
    """,
    (
        today,
    ))

    present = c.fetchone()["present"]

    absent = total - present

    c.execute("""
        SELECT e.name

        FROM employees e

        JOIN attendance a

            ON e.id=a.employee_id

        WHERE DATE(a.clock_in)=%s

        AND a.clock_out IS NULL

        ORDER BY e.name
    """,
    (
        today,
    ))

    working = [
        row["name"]
        for row in c.fetchall()
    ]

    conn.close()

    return jsonify({

        "total":total,

        "present":present,

        "absent":absent,

        "working":working

    })

@socketio.on("join")
def on_join(data):

    if 'user_id' not in session:
        return

    expected_room = f"user_{session['user_id']}"
    requested_room = data.get("room")

    # Only allow a client to join its own notification room.
    if requested_room != expected_room:
        return

    join_room(expected_room)

    print(
        f"User {session['user_id']} joined notification room "
        f"{expected_room}"
    )

# -------------------------
# Initialize app
# -------------------------
try:
    init_db()
    create_admin()
    register_request_workflow(app, socketio)

    print("✅ Database initialized successfully.")

except Exception as e:
    print("\n==============================")
    print(" Application Startup Error")
    print("==============================")
    print(e)
    raise SystemExit(1)


if __name__ == "__main__":
    socketio.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=not IS_PRODUCTION
    )
