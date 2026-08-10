from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    session,
    jsonify,
    current_app
)

from flask_socketio import join_room

from psycopg2.extras import RealDictCursor

from database import (
    get_db,
    allowed_file,
    UPLOAD_FOLDER
)

from werkzeug.utils import secure_filename

from flask_socketio import emit

from datetime import datetime

import time
import os

from cloudinary import uploader
import cloudinary_config


# ==========================================
# BLUEPRINT
# ==========================================

chat_bp = Blueprint(
    "chat",
    __name__
)

# SocketIO instance will be attached later
socketio = None


# ==========================================
# REGISTER SOCKETIO
# ==========================================

def register_chat_socketio(socket):

    global socketio
    socketio = socket

    @socketio.on("connect")
    def chat_connect():

        if "user_id" in session:

            print(
                f"{session['name']} connected."
            )

    @socketio.on("join_chat")
    def join_chat(data):

        if "user_id" not in session:
            return

        other_user = int(data["user_id"])

        room = get_room_name(
            session["user_id"],
            other_user
        )

        join_room(room)

        print(f"{session['name']} joined {room}")

    @socketio.on("disconnect")
    def chat_disconnect():

        if "user_id" in session:

            print(
                f"{session['name']} disconnected."
            )

# ==========================================
# HELPERS
# ==========================================

def get_room_name(user1, user2):

    """
    Generates the same room name
    regardless of sender/receiver order.
    """

    return "_".join(
        map(
            str,
            sorted([user1, user2])
        )
    )


def save_uploaded_file(file):

    if not file or file.filename == "":
        return None, None

    filename = secure_filename(file.filename)

    result = uploader.upload(
        file,
        folder="salt_portal/chat",
        public_id=os.path.splitext(filename)[0],
        resource_type="auto"
    )

    return (
        filename,
        result["secure_url"]
    )

# ==========================================
# SERIALIZE MESSAGE
# ==========================================

def serialize_message(message):
    """
    Convert PostgreSQL row to JSON-safe dict.
    """

    message = dict(message)

    created_at = message.get("created_at")

    if isinstance(created_at, datetime):
        message["created_at"] = created_at.isoformat()

    elif created_at is None:
        message["created_at"] = ""

    else:
        message["created_at"] = str(created_at)

    return message

def emit_new_message(message):

    if socketio is None:
        return

    room = get_room_name(
        message["sender_id"],
        message["receiver_id"]
    )

    socketio.emit(
        "new_message",
        serialize_message(message),
        room=room
    )


def emit_message_update(message):

    if socketio is None:
        return

    room = get_room_name(
        message["sender_id"],
        message["receiver_id"]
    )

    socketio.emit(
        "message_updated",
        serialize_message(message),
        room=room
    )


def current_user_required():

    """
    Small helper to avoid repeating
    login checks.
    """

    return "user_id" in session

# ==========================================
# MESSAGES PAGE
# ==========================================

@chat_bp.route("/messages", methods=["GET", "POST"])
@chat_bp.route("/messages/<int:user_id>", methods=["GET", "POST"])
def messages(user_id=None):

    if not current_user_required():
        return redirect("/")

    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)

    # ----------------------------------
    # SEND MESSAGE
    # ----------------------------------

    if request.method == "POST" and user_id:

        message = request.form.get(
            "message",
            ""
        ).strip()

        file = request.files.get("file")

        file_name, file_path = save_uploaded_file(file)

        # don't save completely empty messages
        if not message and not file_name:
            conn.close()
            return jsonify({
                "success": False
            })

        c.execute("""

            INSERT INTO messages(
                sender_id,
                receiver_id,
                message,
                file_name,
                file_path
            )
            VALUES(
                %s,
                %s,
                %s,
                %s,
                %s
            )
            RETURNING *;

        """, (

            session["user_id"],
            user_id,
            message,
            file_name,
            file_path

        ))

        new_message = c.fetchone()

        # notification
        c.execute("""

            INSERT INTO notifications(

                user_id,
                message,
                created_at

            )

            VALUES(

                %s,
                %s,
                NOW()

            )

        """, (

            user_id,
            f"New message from {session['name']}"

        ))

        conn.commit()

        emit_new_message(new_message)

        conn.close()

        return jsonify({

            "success": True,
            "message": serialize_message(new_message)

        })

    # ----------------------------------
    # USERS
    # ----------------------------------

    c.execute("""

        SELECT
            id,
            name

        FROM employees

        WHERE id != %s

        ORDER BY name

    """, (

        session["user_id"],

    ))

    users = c.fetchall()

    chats = []

    receiver = None

    # ----------------------------------
    # LOAD CHAT
    # ----------------------------------

    if user_id:

        c.execute("""

            SELECT *

            FROM messages

            WHERE

            (

                sender_id=%s

                AND

                receiver_id=%s

            )

            OR

            (

                sender_id=%s

                AND

                receiver_id=%s

            )

            ORDER BY created_at

        """, (

            session["user_id"],
            user_id,

            user_id,
            session["user_id"]

        ))

        chats = c.fetchall()

        c.execute("""

            SELECT *

            FROM employees

            WHERE id=%s

        """, (

            user_id,

        ))

        receiver = c.fetchone()

        c.execute("""

            UPDATE messages

            SET seen=TRUE

            WHERE

                receiver_id=%s

            AND

                sender_id=%s

            AND

                seen=FALSE

        """, (

            session["user_id"],
            user_id

        ))

        conn.commit()

    conn.close()

    return render_template(
        "messages.html",
        users=users,
        chats=chats,
        receiver=receiver
    )


# ==========================================
# GET MESSAGES
# ==========================================

@chat_bp.route("/get_messages/<int:user_id>")
def get_messages(user_id):

    if not current_user_required():
        return jsonify([])

    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)

    c.execute("""

        SELECT *

        FROM messages

        WHERE

        (

            sender_id=%s

            AND

            receiver_id=%s

        )

        OR

        (

            sender_id=%s

            AND

            receiver_id=%s

        )

        ORDER BY created_at

    """, (

        session["user_id"],
        user_id,

        user_id,
        session["user_id"]

    ))

    chats = c.fetchall()

    conn.close()

    return jsonify([
        serialize_message(chat)
        for chat in chats
    ])    

# ==========================================
# EDIT MESSAGE
# ==========================================

@chat_bp.route("/edit_message/<int:message_id>", methods=["POST"])
def edit_message(message_id):

    if not current_user_required():
        return jsonify({"success": False})

    new_message = request.form.get("message", "").strip()

    if new_message == "":
        return jsonify({"success": False})

    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)

    c.execute("""
        UPDATE messages
        SET
            message=%s,
            edited=TRUE
        WHERE
            id=%s
            AND sender_id=%s
        RETURNING *
    """, (

        new_message,
        message_id,
        session["user_id"]

    ))

    updated = c.fetchone()

    conn.commit()
    conn.close()

    if not updated:
        return jsonify({"success": False})

    emit_message_update(updated)

    return jsonify({
        "success": True,
        "message": serialize_message(updated)
    })   

# ==========================================
# DELETE MESSAGE
# ==========================================

@chat_bp.route("/delete_message/<int:message_id>", methods=["POST"])
def delete_message(message_id):

    if not current_user_required():
        return jsonify({"success": False})

    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)

    c.execute("""
        UPDATE messages
        SET
            deleted=TRUE,
            message='',
            file_name=NULL,
            file_path=NULL
        WHERE
            id=%s
            AND sender_id=%s
        RETURNING *
    """, (

        message_id,
        session["user_id"]

    ))

    deleted_message = c.fetchone()

    conn.commit()
    conn.close()

    if not deleted_message:
        return jsonify({"success": False})

    emit_message_update(deleted_message)

    return jsonify({
        "success": True,
        "message": serialize_message(deleted_message)
    })    

