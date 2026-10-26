"""Login, logout and the home redirect."""
from flask import Blueprint, redirect, render_template, request, session
from werkzeug.security import check_password_hash

from database import get_db
from security import LoginThrottle

auth_bp = Blueprint("auth", __name__)

# In-memory throttle: 5 failures per (ip, email) and 30 per ip within 15 minutes.
login_throttle = LoginThrottle(max_attempts=5, window=900, ip_max=30)


def get_client_ip():
    # Behind Render's proxy the real client is the LAST X-Forwarded-For entry
    # (the one the proxy appended); earlier entries can be forged by the client.
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.remote_addr or "unknown"


@auth_bp.route('/')
def home():

    if 'user_id' in session:
        return redirect('/dashboard')

    return render_template("login.html")


@auth_bp.route('/login', methods=['POST'])
def login():

    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')

    # Check Remember Me
    remember = request.form.get('remember') == '1'

    if not email or not password:
        return render_template(
            "login.html",
            error="Please enter your email and password."
        )

    client_ip = get_client_ip()

    if login_throttle.blocked(client_ip, email):
        return render_template(
            "login.html",
            error="Too many failed attempts. Please wait 15 minutes and try again."
        ), 429

    conn = get_db()
    c = conn.cursor()

    c.execute(
        """
        SELECT *
        FROM employees
        WHERE email=%s
        """,
        (email,)
    )

    user = c.fetchone()
    conn.close()

    if user and check_password_hash(user['password'], password):

        login_throttle.reset(client_ip, email)

        # Clear old session data
        session.clear()

        # Store logged-in user
        session['user_id'] = user['id']
        session['name'] = user['name']
        session['role'] = user['role']

        # Remember Me
        if remember:
            session.permanent = True
        else:
            session.permanent = False

        return redirect('/dashboard')

    login_throttle.record_failure(client_ip, email)

    return render_template(
        "login.html",
        error="Invalid email or password."
    )


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect('/')
