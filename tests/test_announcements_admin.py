"""Admin announcement routes: same database-checked admin gate, same responses as before. No PostgreSQL needed."""
from contextlib import ExitStack
from unittest.mock import Mock, patch

from flask import session

import routes.announcements as ann
from helpers import FakeDB, make_app, set_session
from routes.announcements import announcements_bp

WHO = "SELECT id, name, email, role FROM employees"


def account(role):
    return {"id": 1, "name": "Admin", "email": "a@x.test", "role": role}


def client(cookie_role="admin", logged_in=True):
    c = make_app(announcements_bp).test_client()
    if logged_in:
        set_session(c, user_id=1, role=cookie_role, name="Admin")
    return c


def using(db):
    stack = ExitStack()
    stack.enter_context(patch("decorators.get_db", db))
    stack.enter_context(patch("routes.announcements.get_db", db))
    return stack


def test_logged_out_responses_are_unchanged():
    c = client(logged_in=False)
    assert c.get("/admin/announcements").status_code == 302                      # back to login
    assert c.get("/admin/announcement/file/5").status_code == 302
    r = c.post("/admin/announcements/upload-signature", json={})
    assert r.status_code == 403 and r.get_json() == {"status": "error", "message": "Access denied."}
    r = c.post("/admin/update_announcement/5", json={})
    assert r.status_code == 401 and r.get_json()["message"] == "Please log in."
    r = c.post("/admin/delete_announcement/5")
    assert r.status_code == 401 and r.get_json()["message"] == "Unauthorized"


def test_real_employee_is_denied_with_the_original_messages():
    db = FakeDB([(WHO, account("employee"), 1)])
    c = client("employee")
    with using(db):
        r = c.get("/admin/announcements")
        assert r.status_code == 403 and r.get_data(as_text=True) == "Access Denied"
        r = c.post("/admin/announcements/upload-signature", json={})
        assert r.status_code == 403 and r.get_json()["message"] == "Access denied."
        r = c.post("/admin/update_announcement/5", json={"title": "x"})
        assert r.status_code == 403 and r.get_json() == {"status": "error", "message": "Access denied."}
        r = c.post("/admin/delete_announcement/5")
        assert r.status_code == 403 and r.get_json() == {"status": "error", "message": "Access Denied"}


def test_a_stale_admin_cookie_is_not_enough():
    c = client("admin")                                           # cookie says admin ...
    with using(FakeDB([(WHO, account("employee"), 1)])):          # ... database says employee
        for method, url in [("get", "/admin/announcements"), ("post", "/admin/announcements/upload-signature"),
                            ("post", "/admin/update_announcement/5"), ("post", "/admin/delete_announcement/5")]:
            assert getattr(c, method)(url).status_code == 403, url


def test_real_admin_gets_past_the_gate():
    c = client("admin")
    with using(FakeDB([(WHO, account("admin"), 1)])):
        r = c.post("/admin/update_announcement/5")                 # no JSON body
        assert r.status_code == 400 and r.get_json()["message"] == "Please use the current announcement editor."
        r = c.post("/admin/delete_announcement/5")                 # announcement does not exist
        assert r.status_code == 404 and r.get_json()["message"] == "Announcement not found."


def test_the_helper_asks_the_database():
    app = make_app()
    with app.test_request_context("/"):
        session["user_id"], session["role"] = 1, "admin"
        with patch("decorators.get_db", FakeDB([(WHO, account("employee"), 1)])):
            assert ann._announcement_admin_required() is False
    with app.test_request_context("/"):
        session["user_id"], session["role"] = 1, "employee"
        with patch("decorators.get_db", FakeDB([(WHO, account("admin"), 1)])):
            assert ann._announcement_admin_required() is True


def test_background_task_goes_through_the_apps_socketio():
    app, sio = make_app(), Mock()
    app.extensions["socketio"] = sio
    with app.app_context():
        ann._start_background_task(print, "audience", "msg", 1)
    sio.start_background_task.assert_called_once_with(print, "audience", "msg", 1)


def test_upload_limits_moved_with_the_code():
    assert ann.ANNOUNCEMENT_MAX_FILE_SIZE == 10 * 1024 * 1024
    assert {"pdf", "docx", "xlsx"} <= set(ann.ANNOUNCEMENT_ALLOWED_EXTENSIONS)
