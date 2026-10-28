"""Admin employee routes: only real (database) admins get in. No PostgreSQL needed."""
from contextlib import ExitStack
from unittest.mock import patch

from werkzeug.security import check_password_hash

from helpers import FakeDB, make_app, set_session
from routes.employees import employees_bp

WHO = "SELECT id, name, email, role FROM employees"      # the is_admin() lookup
GATED = [                                                 # (method, url)
    ("get", "/admin/employees"),
    ("get", "/admin/add_employee"),
    ("post", "/admin/save_employee"),
    ("get", "/admin/edit_employee/5"),
    ("post", "/admin/reset_password/5"),
    ("post", "/admin/delete_employee/5"),
]


def account(role, uid=1):
    return {"id": uid, "name": "Admin", "email": "a@x.test", "role": role}


def client(cookie_role="admin", logged_in=True):
    c = make_app(employees_bp).test_client()
    if logged_in:
        set_session(c, user_id=1, role=cookie_role, name="Admin")
    return c


def using(db):
    stack = ExitStack()
    stack.enter_context(patch("decorators.get_db", db))
    stack.enter_context(patch("routes.employees.get_db", db))
    return stack


def call(c, method, url, **kw):
    return getattr(c, method)(url, **kw)


def test_logged_out_visitors_are_denied_on_every_admin_employee_route():
    c = client(logged_in=False)
    for method, url in GATED:
        r = call(c, method, url)
        assert r.status_code == 403, url


def test_a_forged_or_stale_admin_cookie_is_not_enough():
    """Cookie says admin, the database says employee -> denied on all six routes."""
    for method, url in GATED:
        c = client("admin")
        with using(FakeDB([(WHO, account("employee"), 1)])):
            assert call(c, method, url).status_code == 403, url


def test_denials_keep_their_original_shape():
    c = client("admin")
    with using(FakeDB([(WHO, account("employee"), 1)])):
        assert c.get("/admin/employees").get_data(as_text=True) == "Access Denied"
        r = c.post("/admin/save_employee")
        assert r.get_json() == {"success": False, "message": "Access Denied"}
        assert c.post("/admin/reset_password/5").get_json() == {"success": False, "message": "Access Denied"}


def test_demoted_admins_cookie_is_corrected_on_the_next_request():
    c = client("admin")
    with using(FakeDB([(WHO, account("employee"), 1)])):
        c.get("/admin/employees")
    with c.session_transaction() as s:
        assert s["role"] == "employee"


def test_deleted_account_is_logged_out_and_denied():
    c = client("admin")
    with using(FakeDB([])):                                   # no employee row any more
        assert c.get("/admin/employees").status_code == 403
    with c.session_transaction() as s:
        assert "user_id" not in s


def test_real_admin_gets_past_the_gate_password_too_short():
    c = client("admin")
    with using(FakeDB([(WHO, account("admin"), 1)])):
        r = c.post("/admin/reset_password/5", data={"password": "abc"})
    assert r.status_code == 400 and r.get_json()["message"] == "Password must be at least 4 characters."


def test_password_reset_stores_a_hash_not_the_password():
    db = FakeDB([(WHO, account("admin"), 1), ("SELECT id, name FROM employees WHERE id", {"id": 5, "name": "Kojo"}, 1)])
    c = client("admin")
    with using(db):
        r = c.post("/admin/reset_password/5", data={"password": "new-secret"})
    assert r.get_json() == {"success": True, "message": "Password for Kojo has been reset."}
    sql, params = [e for e in db.executed if e[0].startswith("UPDATE employees SET password")][0]
    assert params[1] == 5 and params[0] != "new-secret" and check_password_hash(params[0], "new-secret")
    assert db.committed


def test_password_reset_for_unknown_employee_is_404():
    c = client("admin")
    with using(FakeDB([(WHO, account("admin"), 1)])):
        assert c.post("/admin/reset_password/5", data={"password": "long-enough"}).status_code == 404


def test_admin_cannot_delete_their_own_account():
    c = client("admin")
    with using(FakeDB([(WHO, account("admin"), 1)])):
        r = c.post("/admin/delete_employee/1")                 # session user_id is 1
    assert r.status_code == 400 and r.get_json()["message"] == "You cannot delete your own account."
