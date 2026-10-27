"""Unread-chat badge: endpoint + layout. No PostgreSQL needed."""
from unittest.mock import patch

from helpers import FakeDB, make_app, set_session
from routes.chat import chat_bp
from test_base_template import get_page

EMPLOYEE = {"id": 7, "name": "Ada", "email": "ada@example.test", "role": "employee"}


def logged_in():
    c = make_app(chat_bp).test_client()
    set_session(c, user_id=7, role="employee", name="Ada")
    return c


def test_unread_count_requires_login():
    r = make_app(chat_bp).test_client().get("/api/chat/unread-count")
    assert r.status_code == 401 and r.get_json() == {"success": False, "message": "Unauthorized"}


def test_unread_count_counts_only_my_unseen_messages():
    d = FakeDB([("FROM employees WHERE id", EMPLOYEE, 1), ("FROM messages", {"count": 3}, 1)])
    with patch("decorators.get_db", d), patch("routes.chat.get_db", d):
        r = logged_in().get("/api/chat/unread-count")
    assert r.get_json() == {"count": 3}
    sql, params = [e for e in d.executed if "FROM messages" in e[0]][0]
    assert "receiver_id = %s" in sql and "COALESCE(seen, FALSE) = FALSE" in sql
    assert params == (7,)


def test_unread_count_is_zero_when_nothing_is_waiting():
    d = FakeDB([("FROM employees WHERE id", EMPLOYEE, 1), ("FROM messages", {"count": 0}, 1)])
    with patch("decorators.get_db", d), patch("routes.chat.get_db", d):
        assert logged_in().get("/api/chat/unread-count").get_json() == {"count": 0}


def test_layout_has_a_hidden_badge_in_the_sidebar_top_bar_and_mobile_tab():
    html = get_page()
    for badge_id in ("saltChatBadge", "saltTopChatBadge", "saltMobileChatBadge"):
        assert f'id="{badge_id}"' in html, badge_id
    assert html.count("hidden></span>") >= 3
    assert "/api/chat/unread-count" in html and "salt-chat-badge-client" in html
