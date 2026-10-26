"""Notification helpers shared by every feature (tasks, announcements, requests, ...).

app.py calls init_notifications(socketio) once at start-up so create_notification can
push live updates over Socket.IO.
"""
import json
from datetime import datetime

from psycopg2.extras import RealDictCursor

from database import get_db

_socketio = None


def init_notifications(socketio_instance):
    global _socketio
    _socketio = socketio_instance


def _emit(*args, **kwargs):
    if _socketio is not None:
        _socketio.emit(*args, **kwargs)


def create_notification(user_id, message, created_at=None):
    """
    Create a persistent notification and immediately push it
    to the user's Socket.IO room.

    This is the single notification entry point for the portal.
    It is intentionally generic so tasks, announcements,
    comments, workflow events, and future features can all use
    the same notification system.
    """
    if not user_id or not message:
        return None

    created_at = created_at or datetime.now()

    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)

    try:
        c.execute("""
            INSERT INTO notifications
            (
                user_id,
                message,
                is_read,
                created_at
            )
            VALUES
            (
                %s,
                %s,
                FALSE,
                %s
            )
            RETURNING id
        """, (
            int(user_id),
            message,
            created_at
        ))

        row = c.fetchone()
        notification_id = row["id"]

        conn.commit()

        _emit(
            "new_notification",
            {
                "id": notification_id,
                "message": message,
                "created_at": created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "is_read": False
            },
            room=f"user_{int(user_id)}"
        )

        # Browser/desktop push is deliberately best-effort.
        # If push is unavailable, the normal SALT notification
        # system above continues to work normally.
        try:
            from push_notifications import send_web_push

            c.execute("""
                SELECT subscription
                FROM push_subscriptions
                WHERE user_id=%s
            """, (int(user_id),))

            push_rows = c.fetchall()

            def drop_dead_subscription(endpoint):
                # Called when the push service reports 404/410 (expired).
                if not endpoint:
                    return
                c.execute(
                    "DELETE FROM push_subscriptions WHERE endpoint=%s",
                    (endpoint,)
                )
                conn.commit()

            for push_row in push_rows:
                subscription = push_row["subscription"]

                if isinstance(subscription, str):
                    subscription = json.loads(subscription)

                send_web_push(
                    subscription=subscription,
                    title="SALT Portal",
                    body=message,
                    url="/dashboard",
                    tag=f"salt-notification-{notification_id}",
                    on_expired=drop_dead_subscription
                )

        except Exception as push_error:
            print(
                "DESKTOP PUSH SKIPPED:",
                repr(push_error)
            )

        return notification_id

    except Exception as e:
        conn.rollback()
        print("CREATE NOTIFICATION ERROR:", repr(e))
        return None

    finally:
        conn.close()


def notify_users(user_ids, message):
    """
    Send the same notification to multiple users.
    Duplicate user IDs are ignored.
    """
    sent = []

    for user_id in set(user_ids or []):
        notification_id = create_notification(
            user_id,
            message
        )

        if notification_id is not None:
            sent.append(notification_id)

    return sent


def notify_announcement(audience, message, exclude_user_id=None):
    """
    Notify users according to an announcement audience:
      - everyone -> all employees
      - staff    -> staff users only
      - admin    -> admin users only
    """
    conn = get_db()
    c = conn.cursor()

    try:
        if audience == "admin":
            c.execute("""
                SELECT id
                FROM employees
                WHERE role='admin'
            """)
        elif audience == "staff":
            c.execute("""
                SELECT id
                FROM employees
                WHERE role <> 'admin'
            """)
        else:
            c.execute("""
                SELECT id
                FROM employees
            """)

        user_ids = [
            row["id"]
            for row in c.fetchall()
            if row["id"] != exclude_user_id
        ]

    finally:
        conn.close()

    return notify_users(
        user_ids,
        message
    )


def get_notification_count(user_id):

    conn = get_db()
    c = conn.cursor()

    c.execute("""
    SELECT COUNT(*) AS total
    FROM notifications
    WHERE user_id=%s AND is_read=FALSE
    """, (user_id,))

    count = c.fetchone()["total"]

    conn.close()

    return count
