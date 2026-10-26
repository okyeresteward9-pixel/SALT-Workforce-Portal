"""services/notifications.py - saving + live Socket.IO delivery, without PostgreSQL."""
from unittest.mock import Mock, patch

import services.notifications as svc
from helpers import FakeDB


class FakeSocket:
    def __init__(self):
        self.events = []

    def emit(self, name, payload, room=None):
        self.events.append((name, payload, room))


def test_create_notification_saves_and_emits_to_the_users_room():
    sock = FakeSocket()
    svc.init_notifications(sock)
    db = FakeDB([("INSERT INTO notifications", {"id": 5}, 1)])
    try:
        with patch("services.notifications.get_db", db):
            assert svc.create_notification(7, "Hello") == 5
    finally:
        svc.init_notifications(None)
    name, payload, room = sock.events[0]
    assert name == "new_notification" and room == "user_7"
    assert payload["message"] == "Hello" and payload["id"] == 5 and payload["is_read"] is False
    assert db.committed


def test_create_notification_still_saves_when_socketio_not_initialised():
    svc.init_notifications(None)
    db = FakeDB([("INSERT INTO notifications", {"id": 9}, 1)])
    with patch("services.notifications.get_db", db):
        assert svc.create_notification(3, "No sockets") == 9


def test_blank_user_or_message_is_ignored():
    assert svc.create_notification(None, "x") is None
    assert svc.create_notification(5, "") is None


def test_notify_users_skips_duplicates():
    with patch("services.notifications.create_notification", Mock(side_effect=[1, 2])) as create:
        assert sorted(svc.notify_users([1, 1, 2], "m")) == [1, 2]
        assert create.call_count == 2
