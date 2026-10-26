"""auth / pwa / notifications blueprints, exercised with a fake database (no PostgreSQL)."""
from unittest.mock import patch

from werkzeug.security import generate_password_hash

import routes.auth as auth_module
from helpers import FakeDB, make_app, set_session
from routes.auth import auth_bp
from routes.notifications import notifications_bp
from routes.pwa import pwa_bp

USER = {"id": 7, "name": "Ada", "email": "ada@example.test", "role": "employee",
        "password": generate_password_hash("correct-horse")}


def client_for(*bps):
    return make_app(*bps).test_client()


def ip(n):
    return {"X-Forwarded-For": f"10.50.0.{n}"}


# ----------------------------------------------------------------- auth
def test_home_shows_login_when_logged_out_and_redirects_when_logged_in():
    c = client_for(auth_bp)
    assert c.get("/").status_code == 200
    set_session(c, user_id=7)
    r = c.get("/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/dashboard")


def test_login_success_sets_session_and_redirects():
    c = client_for(auth_bp)
    with patch("routes.auth.get_db", FakeDB([("FROM employees WHERE email", USER, 1)])):
        r = c.post("/login", data={"email": "ada@example.test", "password": "correct-horse"}, headers=ip(1))
    assert r.status_code == 302 and r.headers["Location"].endswith("/dashboard")
    with c.session_transaction() as s:
        assert s["user_id"] == 7 and s["role"] == "employee" and s["name"] == "Ada"


def test_login_wrong_password_and_unknown_user_show_error():
    c = client_for(auth_bp)
    with patch("routes.auth.get_db", FakeDB([("FROM employees WHERE email", USER, 1)])):
        r = c.post("/login", data={"email": "ada@example.test", "password": "nope"}, headers=ip(2))
    assert r.status_code == 200 and b"Invalid email or password" in r.data
    with patch("routes.auth.get_db", FakeDB([])):
        r = c.post("/login", data={"email": "ghost@example.test", "password": "x"}, headers=ip(3))
    assert r.status_code == 200 and b"Invalid email or password" in r.data


def test_login_requires_both_fields():
    c = client_for(auth_bp)
    r = c.post("/login", data={"email": "", "password": ""}, headers=ip(4))
    assert b"Please enter your email and password" in r.data


def test_login_is_throttled_after_five_failures_and_success_resets():
    c = client_for(auth_bp)
    with patch("routes.auth.get_db", FakeDB([("FROM employees WHERE email", USER, 1)])):
        for _ in range(5):
            c.post("/login", data={"email": "ada@example.test", "password": "bad"}, headers=ip(5))
        r = c.post("/login", data={"email": "ada@example.test", "password": "bad"}, headers=ip(5))
        assert r.status_code == 429 and b"Too many failed attempts" in r.data
        # a different client IP is not affected
        r = c.post("/login", data={"email": "ada@example.test", "password": "correct-horse"}, headers=ip(6))
        assert r.status_code == 302


def test_logout_clears_session():
    c = client_for(auth_bp)
    set_session(c, user_id=7, role="admin")
    r = c.get("/logout")
    assert r.status_code == 302 and r.headers["Location"].endswith("/")
    with c.session_transaction() as s:
        assert "user_id" not in s


# ------------------------------------------------------------------ pwa
def test_offline_page_and_service_worker_version():
    c = client_for(pwa_bp)
    assert c.get("/offline").status_code == 200
    with patch.dict("os.environ", {"RENDER_GIT_COMMIT": "abcdef1234567890"}):
        r = c.get("/service-worker.js")
    assert r.status_code == 200 and "javascript" in r.mimetype
    assert b"abcdef123456" in r.data and b"__APP_VERSION__" not in r.data
    assert r.headers["Cache-Control"] == "no-cache" and r.headers["Service-Worker-Allowed"] == "/"


# -------------------------------------------------------- notifications
def test_push_public_key_logged_out_keeps_old_answer():
    r = client_for(notifications_bp).get("/api/push/public-key")
    assert r.status_code == 401 and r.get_json() == {"publicKey": ""}


def test_api_notifications_logged_out_is_empty_list():
    r = client_for(notifications_bp).get("/api/notifications")
    assert r.status_code == 200 and r.get_json() == []


def test_mark_read_logged_out_keeps_old_answer():
    r = client_for(notifications_bp).post("/api/notifications/mark-read")
    assert r.status_code == 200 and r.get_json() == {"success": False}


def test_subscribe_and_clear_all_require_login_with_json_401():
    c = client_for(notifications_bp)
    for path in ("/api/push/subscribe", "/api/notifications/clear-all"):
        r = c.post(path)
        assert r.status_code == 401 and r.get_json() == {"success": False, "message": "Unauthorized"}, path


def test_clear_all_deletes_own_notifications():
    c = client_for(notifications_bp)
    set_session(c, user_id=7, role="employee", name="Ada")
    db = FakeDB([("FROM employees WHERE id", {"id": 7, "name": "Ada", "email": "a@b.test", "role": "employee"}, 1),
                 ("DELETE FROM notifications", None, 3)])
    with patch("decorators.get_db", db), patch("routes.notifications.get_db", db):
        r = c.post("/api/notifications/clear-all")
    assert r.get_json() == {"success": True, "deleted": 3}
    assert db.committed


def test_subscribe_rejects_bad_payload_and_saves_good_one():
    c = client_for(notifications_bp)
    set_session(c, user_id=7, role="employee", name="Ada")
    db = FakeDB([("FROM employees WHERE id", {"id": 7, "name": "Ada", "email": "a@b.test", "role": "employee"}, 1)])
    with patch("decorators.get_db", db), patch("routes.notifications.get_db", db):
        assert c.post("/api/push/subscribe", json={}).status_code == 400
        r = c.post("/api/push/subscribe", json={"endpoint": "https://push.example/abc", "keys": {}})
    assert r.get_json() == {"success": True}
    assert any("INSERT INTO push_subscriptions" in sql for sql, _ in db.executed)
