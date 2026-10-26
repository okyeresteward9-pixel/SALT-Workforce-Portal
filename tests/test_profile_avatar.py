"""End-to-end regression for 'uploaded photo does not show in sidebar/top bar'. Needs TEST_DATABASE_URL."""
from conftest import login
from database import get_db

URL = "https://res.example.test/avatar-regression.png"


def set_avatar(email, url):
    conn = get_db()
    try:
        conn.cursor().execute("UPDATE employees SET profile_pic=%s WHERE email=%s", (url, email))
        conn.commit()
    finally:
        conn.close()


def test_saved_profile_photo_shows_on_every_page_shell(client, users, fresh_ip):
    set_avatar(users["employee"], URL)
    try:
        login(client, users["employee"], fresh_ip)
        html = client.get("/dashboard").get_data(as_text=True)
        assert html.count(URL) >= 2, "photo should appear in the sidebar and the top bar"
    finally:
        set_avatar(users["employee"], None)


def test_dashboard_has_notification_controls(client, users, fresh_ip):
    login(client, users["employee"], fresh_ip)
    html = client.get("/dashboard").get_data(as_text=True)
    assert 'id="saltMarkAllRead"' in html and 'id="saltClearAllNotifications"' in html
