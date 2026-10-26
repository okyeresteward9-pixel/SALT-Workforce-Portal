"""Decorator behaviour, no database needed."""
from unittest.mock import patch

from flask import jsonify

from decorators import admin_required, current_user, login_required
from helpers import FakeDB, make_app, set_session


def build():
    app = make_app()

    @app.route("/page")
    @login_required
    def page():
        return "page"

    @app.route("/api/thing", methods=["POST"])
    @login_required
    def thing():
        return jsonify(ok=True)

    @app.route("/admin/page")
    @admin_required
    def admin_page():
        return "admin"

    @app.route("/who")
    def who():
        user = current_user()
        return (user["role"] if user else "nobody")

    return app


def db_with(role="employee", name="Ada"):
    return FakeDB([("FROM employees WHERE id", {"id": 7, "name": name, "email": "a@b.test", "role": role}, 1)])


def test_logged_out_page_redirects_and_api_gets_json_401():
    client = build().test_client()
    r = client.get("/page")
    assert r.status_code == 302 and r.headers["Location"].endswith("/")
    r = client.post("/api/thing")
    assert r.status_code == 401 and r.get_json() == {"success": False, "message": "Unauthorized"}


def test_logged_in_user_passes():
    client = build().test_client()
    set_session(client, user_id=7, role="employee", name="Ada")
    with patch("decorators.get_db", db_with()):
        assert client.get("/page").data == b"page"


def test_employee_is_forbidden_on_admin_page():
    client = build().test_client()
    set_session(client, user_id=7, role="employee", name="Ada")
    with patch("decorators.get_db", db_with("employee")):
        assert client.get("/admin/page").status_code == 403


def test_demoted_admin_loses_access_immediately():
    """Cookie still says admin, database says employee -> blocked, and the cookie is corrected."""
    client = build().test_client()
    set_session(client, user_id=7, role="admin", name="Ada")
    with patch("decorators.get_db", db_with("employee")):
        assert client.get("/admin/page").status_code == 403
        assert client.get("/who").data == b"employee"
    with client.session_transaction() as s:
        assert s["role"] == "employee"


def test_promoted_user_gets_access_without_relogin():
    client = build().test_client()
    set_session(client, user_id=7, role="employee", name="Ada")
    with patch("decorators.get_db", db_with("admin")):
        assert client.get("/admin/page").data == b"admin"


def test_deleted_account_session_is_cleared():
    client = build().test_client()
    set_session(client, user_id=99, role="admin", name="Ghost")
    with patch("decorators.get_db", FakeDB([])):  # no matching employee row
        assert client.get("/admin/page").status_code == 302
    with client.session_transaction() as s:
        assert "user_id" not in s
