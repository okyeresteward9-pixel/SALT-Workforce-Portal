"""Step 4d-3 - chat polish that goes with the new unread badge.

Run from the project root:   python step4d3_chat_fixes.py
Optional:                    python step4d3_chat_fixes.py --keep-bell-entries

  1. routes/chat.py   live chat events now carry `sender_name`, so the toast on every page says WHO wrote
                      ("Kojo: Are you there?") instead of just "New message".
  2. routes/chat.py   stop adding a "New message from X" row to the bell on every chat message.
                      Chat now has its own count (sidebar / top bar / mobile) plus the toast and the push
                      notification, so each message was being counted twice and a busy chat flooded the bell.
                      (Skip this with --keep-bell-entries.)
  3. templates/messages.html   chat.js?v=3 -> v=4. Your service worker serves cached scripts first, so a
                      changed chat.js needs a new version number to reach users straight away.

Aborts without changing anything if an anchor is not found exactly once.
"""
import re
import sys

KEEP_BELL = "--keep-bell-entries" in sys.argv


def die(msg):
    sys.exit("STOPPED - nothing was changed.\n" + msg)


def read(path):
    raw = open(path, "rb").read().decode("utf-8")
    return ("\r\n" if "\r\n" in raw else "\n"), raw.replace("\r\n", "\n")


def once(text, old, new, label):
    if text.count(old) != 1:
        die(f"{label}: expected 1 match, found {text.count(old)}.")
    return text.replace(old, new)


chat_nl, chat = read("routes/chat.py")
msg_nl, msg = read("templates/messages.html")

if "_sender_name" in chat:
    sys.exit("Already applied - nothing to do.")

# ---- 1. sender_name on live events -------------------------------------------------------
chat = once(chat, "    jsonify,\n    current_app\n)", "    jsonify,\n    current_app,\n    has_request_context\n)", "chat.py flask import")
chat = once(
    chat,
    "def emit_new_message(message):\n",
    '''def _sender_name(message):
    """Name of whoever sent/edited the message: the logged-in user when they are the sender."""
    if has_request_context() and session.get("user_id") == message.get("sender_id"):
        return session.get("name")
    return None


def emit_new_message(message):
''',
    "emit_new_message",
)
chat = once(
    chat,
    "    serialized = serialize_message(message)\n\n    # Receiver gets the event even when another conversation is open.",
    '    serialized = serialize_message(message)\n    serialized["sender_name"] = _sender_name(message)\n\n    # Receiver gets the event even when another conversation is open.',
    "new_message payload",
)
chat = once(
    chat,
    '    serialized = serialize_message(message)\n\n    socketio.emit(\n        "message_updated",',
    '    serialized = serialize_message(message)\n    serialized["sender_name"] = _sender_name(message)\n\n    socketio.emit(\n        "message_updated",',
    "message_updated payload",
)

# ---- 2. no duplicate bell entry ----------------------------------------------------------
removed_bell = False
if not KEEP_BELL:
    pattern = re.compile(
        r"        # notification\n        c\.execute\(\"\"\"\n.*?INSERT INTO notifications\(.*?"
        r"f\"New message from \{session\['name'\]\}\"\n\s*\n\s*\)\)\n\n?",
        re.S,
    )
    found = pattern.findall(chat)
    if len(found) != 1 or found[0].count("INSERT INTO notifications") != 1:
        die("chat.py: could not find the single 'New message from ...' bell insert. "
            "Re-run with --keep-bell-entries to skip this part, or send me that block.")
    chat = pattern.sub("", chat, count=1)
    removed_bell = True

# ---- 3. cache-buster ---------------------------------------------------------------------
bumped = False
if "filename='js/chat.js', v='3'" in msg:
    msg = once(msg, "filename='js/chat.js', v='3'", "filename='js/chat.js', v='4'", "messages.html chat.js version")
    bumped = True

open("routes/chat.py", "wb").write(chat.replace("\n", chat_nl).encode("utf-8"))
open("templates/messages.html", "wb").write(msg.replace("\n", msg_nl).encode("utf-8"))
print("routes/chat.py: live events now include sender_name")
print("routes/chat.py: chat messages no longer add a bell entry" if removed_bell else "routes/chat.py: bell entries kept (--keep-bell-entries)")
print("templates/messages.html: chat.js version -> 4" if bumped else "templates/messages.html: chat.js version already bumped")
