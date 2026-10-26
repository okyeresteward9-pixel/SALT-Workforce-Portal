"""End-to-end smoke tests. Need a Postgres test database (TEST_DATABASE_URL)."""
import re

import pytest

from conftest import login

PUBLIC_ENDPOINTS = {"home", "offline", "service_worker", "static"}
# Public GET pages that are allowed to answer 200 without logging in (add yours here on purpose).
PUBLIC_PATHS = {"/", "/offline", "/service-worker.js"}
# Background-polling endpoints that deliberately answer a logged-out visitor with an empty list.
EMPTY_LIST_WHEN_LOGGED_OUT = {"/api/notifications", "/get_messages/1"}


def test_login_page_loads(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Welcome back" in r.data


def test_offline_page_and_service_worker(client):
    assert client.get("/offline").status_code == 200
    sw = client.get("/service-worker.js")
    assert sw.status_code == 200
    assert "javascript" in sw.mimetype
    assert b"__APP_VERSION__" not in sw.data
    assert sw.headers["Cache-Control"] == "no-cache"
    assert sw.headers["Service-Worker-Allowed"] == "/"


def test_every_get_page_requires_login(app, client):
    """Generic sweep: any GET route not on the public list must NOT return 200 when logged out."""
    offenders = []
    for rule in app.url_map.iter_rules():
        if "GET" not in rule.methods or rule.endpoint in PUBLIC_ENDPOINTS:
            continue
        path = re.sub(r"<(?:int:|path:|string:)?\w+>", "1", rule.rule)
        if path in PUBLIC_PATHS or path.startswith("/socket.io"):
            continue
        response = client.get(path)
        status = response.status_code
        if status == 200 and path in EMPTY_LIST_WHEN_LOGGED_OUT and response.get_json(silent=True) == []:
            continue
        if status == 200 or status >= 500:
            offenders.append((path, status))
    assert not offenders, f"Pages reachable without login (or crashing): {offenders}"


def test_wrong_password_shows_error(client, fresh_ip):
    r = client.post("/login", data={"email": "nobody@example.test", "password": "x"}, headers=fresh_ip)
    assert r.status_code == 200
    assert b"Invalid email or password" in r.data


def test_login_is_throttled_after_five_failures(client, fresh_ip):
    for _ in range(5):
        client.post("/login", data={"email": "nobody@example.test", "password": "x"}, headers=fresh_ip)
    r = client.post("/login", data={"email": "nobody@example.test", "password": "x"}, headers=fresh_ip)
    assert r.status_code == 429
    assert b"Too many failed attempts" in r.data


def test_cross_site_post_is_blocked(client, fresh_ip):
    r = client.post("/login", data={"email": "a@b.test", "password": "x"},
                    headers={**fresh_ip, "Origin": "https://evil.example"})
    assert r.status_code == 403


@pytest.mark.parametrize("path", ["/start_task/1", "/complete_task/1", "/delete_task/1"])
def test_cross_site_links_cannot_trigger_task_actions(client, path):
    r = client.get(path, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r = client.get(path, headers={"Referer": "https://evil.example/page"})
    assert r.status_code == 403


def test_employee_login_and_dashboard(client, users, fresh_ip):
    r = login(client, users["employee"], fresh_ip)
    assert r.status_code == 302 and r.headers["Location"].endswith("/dashboard")
    assert client.get("/dashboard").status_code == 200


def test_employee_cannot_open_admin_pages(client, users, fresh_ip):
    login(client, users["employee"], fresh_ip)
    for path in ("/admin/employees", "/admin/tasks", "/admin/announcements"):
        assert client.get(path).status_code != 200, path


def test_admin_can_open_admin_pages(client, users, fresh_ip):
    login(client, users["admin"], fresh_ip)
    assert client.get("/admin/employees").status_code == 200
