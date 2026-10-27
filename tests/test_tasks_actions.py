"""Task actions are POST-only and still do their job. No PostgreSQL needed."""
from unittest.mock import Mock, patch

from helpers import FakeDB, make_app, set_session
from routes.tasks import tasks_bp

EMPLOYEE = {"id": 7, "name": "Ada", "email": "ada@example.test", "role": "employee"}
ACTIONS = ("start", "complete", "delete")


def client():
    return make_app(tasks_bp).test_client()


def logged_in():
    c = client()
    set_session(c, user_id=7, role="employee", name="Ada")
    return c


def db(*extra_rules):
    return FakeDB([("FROM employees WHERE id", EMPLOYEE, 1), *extra_rules])


def test_actions_cannot_be_triggered_with_a_plain_link():
    c = client()
    for action in ACTIONS:
        assert c.get(f"/tasks/5/{action}").status_code == 405, action


def test_old_get_urls_are_gone():
    c = client()
    assert c.get("/start_task/5").status_code == 404
    assert c.get("/complete_task/5").status_code == 404
    # /delete_task/<id> still exists, but only as the admin POST action, so a link gets "405 wrong method".
    assert c.get("/delete_task/5").status_code == 405


def test_logged_out_posts_are_refused():
    c = client()
    for action in ACTIONS:
        r = c.post(f"/tasks/5/{action}")
        assert r.status_code == 302 and r.headers["Location"].endswith("/"), action          # normal request
        r = c.post(f"/tasks/5/{action}", headers={"X-Requested-With": "XMLHttpRequest"})
        assert r.status_code == 401 and r.get_json()["success"] is False, action               # the page's fetch()


def test_start_marks_in_progress_and_tells_the_creator():
    d = db(("SELECT created_by, title", {"created_by": 2, "title": "Report"}, 1))
    c, notify = logged_in(), Mock()
    with patch("decorators.get_db", d), patch("routes.tasks.get_db", d), patch("routes.tasks.create_notification", notify):
        r = c.post("/tasks/5/start")
    assert r.status_code == 302 and r.headers["Location"].endswith("/tasks")
    assert ("UPDATE tasks SET status='In Progress' WHERE id=%s AND assigned_to=%s", (5, 7)) in d.executed
    notify.assert_called_once_with(2, "Task Started: Report")
    assert d.committed


def test_start_does_not_notify_when_you_created_the_task_yourself():
    d = db(("SELECT created_by, title", {"created_by": 7, "title": "Mine"}, 1))
    c, notify = logged_in(), Mock()
    with patch("decorators.get_db", d), patch("routes.tasks.get_db", d), patch("routes.tasks.create_notification", notify):
        c.post("/tasks/5/start")
    notify.assert_not_called()


def test_delete_only_hides_the_task_from_the_employees_own_list():
    d = db()
    c = logged_in()
    with patch("decorators.get_db", d), patch("routes.tasks.get_db", d):
        r = c.post("/tasks/5/delete")
    assert r.status_code == 302 and r.headers["Location"].endswith("/tasks")
    assert ("UPDATE tasks SET employee_deleted = TRUE WHERE id=%s AND assigned_to=%s", (5, 7)) in d.executed
    assert not any(sql.startswith("DELETE") for sql, _ in d.executed)


def test_admin_delete_route_is_untouched_and_does_not_clash():
    app = make_app(tasks_bp)
    rules = {(r.rule, m) for r in app.url_map.iter_rules() for m in r.methods if m not in ("HEAD", "OPTIONS")}
    assert ("/delete_task/<int:task_id>", "POST") in rules
    assert ("/delete_task/<int:id>", "GET") not in rules
