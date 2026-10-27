"""Live chat events carry the sender's name (used by the toast on every page). No PostgreSQL needed."""
from unittest.mock import patch

import routes.chat as chat_module
from helpers import make_app

MESSAGE = {"id": 1, "sender_id": 7, "receiver_id": 3, "message": "hi",
           "file_name": None, "file_path": None, "created_at": None, "seen": False}


class FakeSocket:
    def __init__(self):
        self.events = []

    def emit(self, name, payload, room=None):
        self.events.append((name, payload, room))


def emit_as(session_user_id, function):
    app, sock = make_app(), FakeSocket()
    with app.test_request_context("/"):
        from flask import session
        session["user_id"], session["name"] = session_user_id, "Kojo"
        with patch.object(chat_module, "socketio", sock):
            function(MESSAGE)
    return sock.events


def test_new_message_event_names_the_sender_in_both_rooms():
    events = emit_as(7, chat_module.emit_new_message)
    assert [e[0] for e in events] == ["new_message", "new_message"]
    assert all(e[1]["sender_name"] == "Kojo" for e in events)
    assert events[0][2] == chat_module.get_user_room(3)          # the receiver's personal room


def test_edit_event_also_names_the_sender():
    events = emit_as(7, chat_module.emit_message_update)
    assert all(e[0] == "message_updated" and e[1]["sender_name"] == "Kojo" for e in events)


def test_name_is_not_guessed_when_someone_else_triggers_the_event():
    events = emit_as(9, chat_module.emit_new_message)             # logged-in user is not the sender
    assert all(e[1]["sender_name"] is None for e in events)


def test_send_route_no_longer_floods_the_bell():
    """Chat has its own unread badge, toast and push, so it must not also add a bell notification per message."""
    source = open(chat_module.__file__, encoding="utf-8").read()
    assert "INSERT INTO notifications" not in source, (
        "chat.py adds a bell entry per message again - re-run step4d3 (without --keep-bell-entries) "
        "or delete this test if you want that behaviour")
