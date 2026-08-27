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
import json
import mimetypes
import requests

from cloudinary import uploader
import cloudinary_config
from push_notifications import send_web_push


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

            user_room = get_user_room(
                session["user_id"]
            )

            join_room(user_room)

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

def get_user_room(user_id):
    """Personal Socket.IO room for global chat notifications."""
    return f"user_{user_id}"


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
    """
    Upload a chat attachment to Cloudinary.

    IMPORTANT:
    - Images use Cloudinary's image delivery URL.
    - Video/audio use Cloudinary's video delivery URL.
    - PDFs use Cloudinary's normal delivery URL so they can be previewed.
    - Office/text/archive files are raw assets and keep their extension in
      the Cloudinary public_id.
    - Raw files are NOT given an fl_attachment URL here. Their download is
      handled by /chat/download/<message_id>, which streams the exact asset
      through Flask and sets the original filename/extension reliably.
    """
    if not file or not file.filename:
        return None, None

    filename = secure_filename(file.filename)
    if not filename:
        return None, None

    extension = os.path.splitext(filename)[1].lower()

    allowed_extensions = {
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg",
        ".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv",
        ".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac",
        ".pdf",
        ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".txt", ".csv", ".json", ".xml",
        ".zip", ".rar", ".7z",
    }

    if extension not in allowed_extensions:
        raise ValueError(
            "Unsupported file type. Please upload an image, video, "
            "audio, document, or supported archive."
        )

    raw_extensions = {
        ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".txt", ".csv", ".json", ".xml", ".zip", ".rar", ".7z"
    }

    video_extensions = {
        ".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv",
        ".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"
    }

    image_extensions = {
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"
    }

    is_raw = extension in raw_extensions

    # Cloudinary public IDs:
    # raw assets MUST include their extension.
    # image/video public IDs MUST NOT include their extension.
    base_name = os.path.splitext(filename)[0]
    safe_base = secure_filename(base_name) or "file"
    unique_base = f"{safe_base}_{int(time.time() * 1000)}"

    if is_raw:
        public_id = f"{unique_base}{extension}"
        resource_type = "raw"
    elif extension in video_extensions:
        public_id = unique_base
        resource_type = "video"
    elif extension in image_extensions:
        public_id = unique_base
        resource_type = "image"
    else:
        # PDF: let Cloudinary auto-detect it. This keeps the normal delivery
        # URL and allows the browser to preview PDFs instead of forcing a
        # download.
        public_id = unique_base
        resource_type = "auto"

    import cloudinary_config  # noqa: F401
    from cloudinary import uploader

    file_size = None
    try:
        current_position = file.tell()
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(current_position)
    except Exception:
        pass

    upload_options = {
        "folder": "salt_portal/chat",
        "public_id": public_id,
        "resource_type": resource_type,
        "use_filename": False,
        "unique_filename": False,
    }

    if file_size and file_size > 20 * 1024 * 1024:
        result = uploader.upload_large(
            file,
            chunk_size=6 * 1024 * 1024,
            **upload_options
        )
    else:
        result = uploader.upload(
            file,
            **upload_options
        )

    secure_url = result.get("secure_url")
    if not secure_url:
        raise RuntimeError("Cloudinary did not return a secure file URL.")

    # Always return the normal Cloudinary URL here. The exact original
    # filename is preserved separately in messages.file_name.
    #
    # For raw files, /chat/download/<message_id> will fetch this URL and send
    # it back with Content-Disposition: attachment; filename="<original>".
    return filename, secure_url


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

    # Frontend uses this for documents/archives. Media keeps using file_path
    # directly so images, video, audio and PDFs remain previewable/playable.
    file_name = message.get("file_name")
    if message.get("id") and file_name:
        raw_extensions = {
            ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
            ".txt", ".csv", ".json", ".xml", ".zip", ".rar", ".7z"
        }
        ext = os.path.splitext(file_name)[1].lower()
        if ext in raw_extensions:
            message["download_url"] = f"/chat/download/{message['id']}"
        else:
            message["download_url"] = message.get("file_path")
    else:
        message["download_url"] = None

    return message

def emit_new_message(message):

    if socketio is None:
        return

    serialized = serialize_message(message)

    # Receiver gets the event even when another conversation is open.
    socketio.emit(
        "new_message",
        serialized,
        room=get_user_room(message["receiver_id"])
    )

    # Keep the existing open-conversation delivery.
    socketio.emit(
        "new_message",
        serialized,
        room=get_room_name(
            message["sender_id"],
            message["receiver_id"]
        )
    )


def emit_message_update(message):

    if socketio is None:
        return

    serialized = serialize_message(message)

    socketio.emit(
        "message_updated",
        serialized,
        room=get_user_room(message["receiver_id"])
    )

    socketio.emit(
        "message_updated",
        serialized,
        room=get_room_name(
            message["sender_id"],
            message["receiver_id"]
        )
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

        try:
            file_name, file_path = save_uploaded_file(file)
        except ValueError as upload_error:
            conn.close()
            return jsonify({
                "success": False,
                "error": str(upload_error)
            }), 400
        except Exception as upload_error:
            conn.close()
            print("CHAT FILE UPLOAD ERROR:", repr(upload_error))
            return jsonify({
                "success": False,
                "error": "The attachment could not be uploaded. Please try again."
            }), 500

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
                file_path,
                created_at
            )
            VALUES(
                %s,
                %s,
                %s,
                %s,
                %s,
                NOW()
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

        # Existing instant in-app delivery.
        emit_new_message(new_message)

        # Desktop/browser push notification.
        # Best-effort: a push failure must never break chat.
        try:

            c.execute("""
                SELECT subscription
                FROM push_subscriptions
                WHERE user_id=%s
            """, (
                user_id,
            ))

            push_rows = c.fetchall()

            push_body = (
                message
                if message
                else "📎 Sent an attachment"
            )

            for push_row in push_rows:

                subscription = push_row["subscription"]

                if isinstance(subscription, str):
                    subscription = json.loads(subscription)

                send_web_push(
                    subscription=subscription,
                    title=f"New message from {session['name']}",
                    body=push_body,
                    url=f"/messages/{session['user_id']}",
                    tag=f"chat-message-{new_message['id']}"
                )

        except Exception as push_error:

            print(
                "CHAT DESKTOP PUSH SKIPPED:",
                repr(push_error)
            )

        conn.close()

        return jsonify({

            "success": True,
            "message": serialize_message(new_message)

        })

    users = []

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

    # ----------------------------------
    # USERS / CONVERSATION LIST
    # ----------------------------------
    # Latest message, latest time and unread count are returned
    # so the sidebar can behave like WhatsApp.

    c.execute("""

        SELECT
            e.id,
            e.name,

            COUNT(m.id) FILTER (
                WHERE
                    m.sender_id = e.id
                    AND m.receiver_id = %s
                    AND COALESCE(m.seen, FALSE) = FALSE
            ) AS unread_count,

            MAX(m.created_at) AS latest_created_at,

            (
                SELECT lm.message
                FROM messages lm
                WHERE
                    (
                        lm.sender_id = e.id
                        AND lm.receiver_id = %s
                    )
                    OR
                    (
                        lm.sender_id = %s
                        AND lm.receiver_id = e.id
                    )
                ORDER BY lm.created_at DESC, lm.id DESC
                LIMIT 1
            ) AS latest_message,

            (
                SELECT lm.sender_id
                FROM messages lm
                WHERE ((lm.sender_id = e.id AND lm.receiver_id = %s)
                   OR (lm.sender_id = %s AND lm.receiver_id = e.id))
                ORDER BY lm.created_at DESC, lm.id DESC
                LIMIT 1
            ) AS latest_sender_id,

            (
                SELECT lm.file_name
                FROM messages lm
                WHERE ((lm.sender_id = e.id AND lm.receiver_id = %s)
                   OR (lm.sender_id = %s AND lm.receiver_id = e.id))
                ORDER BY lm.created_at DESC, lm.id DESC
                LIMIT 1
            ) AS latest_file_name

        FROM employees e

        LEFT JOIN messages m
            ON (
                (
                    m.sender_id = e.id
                    AND m.receiver_id = %s
                )
                OR
                (
                    m.sender_id = %s
                    AND m.receiver_id = e.id
                )
            )

        WHERE e.id != %s

        GROUP BY e.id, e.name

        ORDER BY
            latest_created_at DESC NULLS LAST,
            e.name ASC

    """, (
        session["user_id"],
        session["user_id"],
        session["user_id"],
        session["user_id"],
        session["user_id"],
        session["user_id"],
        session["user_id"],
        session["user_id"],
        session["user_id"],
        session["user_id"]
    ))

    users = c.fetchall()

    conn.close()

    return render_template(
        "messages.html",
        users=users,
        chats=chats,
        receiver=receiver
    )


# ==========================================
# DOWNLOAD ORIGINAL CHAT ATTACHMENT
# ==========================================

@chat_bp.route("/chat/download/<int:message_id>")
def download_chat_attachment(message_id):
    """
    Download a document/archive using the exact original filename.

    We proxy raw Cloudinary files through Flask because the browser's
    cross-origin download attribute cannot reliably control the filename
    of a Cloudinary URL. The server response explicitly sets the filename
    and MIME type, so .docx/.xlsx/.pptx/.zip/etc. remain unchanged.
    """
    if not current_user_required():
        return redirect("/")

    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)

    c.execute("""
        SELECT
            id,
            sender_id,
            receiver_id,
            file_name,
            file_path
        FROM messages
        WHERE id=%s
          AND (sender_id=%s OR receiver_id=%s)
        LIMIT 1
    """, (
        message_id,
        session["user_id"],
        session["user_id"]
    ))

    message = c.fetchone()
    conn.close()

    if not message or not message.get("file_name") or not message.get("file_path"):
        return "Attachment not found.", 404

    filename = secure_filename(message["file_name"]) or "download"
    file_url = message["file_path"]

    try:
        upstream = requests.get(
            file_url,
            stream=True,
            timeout=60,
            allow_redirects=True
        )
        upstream.raise_for_status()
    except requests.RequestException as exc:
        print("CHAT DOWNLOAD ERROR:", repr(exc))
        return "Unable to retrieve attachment.", 502

    # Download into memory. Chat documents/archives are normally modest in
    # size, and this guarantees Flask can set the original filename.
    try:
        content = upstream.content
    finally:
        upstream.close()

    mimetype = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    response = current_app.response_class(
        content,
        status=200,
        mimetype=mimetype
    )
    response.headers["Content-Disposition"] = (
        f"attachment; filename=\"{filename}\""
    )
    response.headers["Content-Length"] = str(len(content))
    response.headers["Cache-Control"] = "private, no-store"

    return response


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

