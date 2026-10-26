"""Login / admin guards that check the DATABASE, not just the cookie.

Why: the session cookie stores the role from login time. Without a re-check, a user who is
demoted or deleted keeps their old access until the cookie expires (up to 30 days).
These helpers look the user up once per request and keep the session in sync.
"""
from functools import wraps

from flask import g, jsonify, redirect, request, session
from psycopg2.extras import RealDictCursor

from database import get_db


def _wants_json():
    return (
        request.path.startswith("/api/")
        or request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )


def current_user():
    """The logged-in employee row (id, name, email, role), or None.

    Cached on flask.g for the request. If the account no longer exists the session is cleared.
    """
    if "user_id" not in session:
        return None

    if not hasattr(g, "_salt_current_user"):
        conn = get_db()
        try:
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute(
                "SELECT id, name, email, role FROM employees WHERE id=%s",
                (session["user_id"],),
            )
            g._salt_current_user = c.fetchone()
        finally:
            conn.close()

    user = g._salt_current_user

    if user is None:
        session.clear()
        return None

    # Keep the cookie in step with the database (only write when something changed).
    if session.get("role") != user["role"]:
        session["role"] = user["role"]
    if session.get("name") != user["name"]:
        session["name"] = user["name"]

    return user


def _unauthorized():
    if _wants_json():
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    return redirect("/")


def _forbidden():
    if _wants_json():
        return jsonify({"success": False, "message": "Access denied."}), 403
    return "Access Denied", 403


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return _unauthorized()
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            return _unauthorized()
        if user["role"] != "admin":
            return _forbidden()
        return view(*args, **kwargs)

    return wrapped
