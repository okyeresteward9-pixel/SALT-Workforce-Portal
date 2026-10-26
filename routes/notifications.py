"""Notification and Web Push API endpoints."""
import json

from flask import Blueprint, jsonify, request, session

from database import get_db
from decorators import login_required
from push_notifications import get_vapid_public_key

notifications_bp = Blueprint("notifications", __name__)

# NOTE: push_public_key, api_notifications and mark_notifications_read keep their own
# logged-out answers ({"publicKey": ""} / [] / {"success": false}) because the front-end
# polls them, so they do not use @login_required.


# -------------------------
# WEB PUSH
# -------------------------

@notifications_bp.route("/api/push/public-key")
def push_public_key():

    if 'user_id' not in session:
        return jsonify({"publicKey": ""}), 401

    return jsonify({
        "publicKey": get_vapid_public_key()
    })


@notifications_bp.route("/api/push/subscribe", methods=["POST"])
@login_required
def push_subscribe():

    subscription = request.get_json(silent=True)

    if not subscription or not subscription.get("endpoint"):
        return jsonify({
            "success": False,
            "message": "Invalid push subscription."
        }), 400

    conn = get_db()
    c = conn.cursor()

    try:
        c.execute("""
            INSERT INTO push_subscriptions
            (
                user_id,
                endpoint,
                subscription
            )
            VALUES
            (
                %s,
                %s,
                %s::jsonb
            )
            ON CONFLICT (endpoint)
            DO UPDATE SET
                user_id = EXCLUDED.user_id,
                subscription = EXCLUDED.subscription
        """, (
            session['user_id'],
            subscription['endpoint'],
            json.dumps(subscription)
        ))

        conn.commit()

        return jsonify({
            "success": True
        })

    except Exception as e:
        conn.rollback()
        print("PUSH SUBSCRIPTION ERROR:", repr(e))

        return jsonify({
            "success": False,
            "message": "Unable to save push subscription."
        }), 500

    finally:
        conn.close()


# -------------------------
# Get notifications (AJAX)
# -------------------------
@notifications_bp.route('/api/notifications')
def api_notifications():

    if 'user_id' not in session:
        return jsonify([])


    conn = get_db()

    c = conn.cursor()


    c.execute("""
        SELECT id, message, created_at, is_read
        FROM notifications
        WHERE user_id=%s
        ORDER BY created_at DESC
        LIMIT 10
    """,
    (session['user_id'],))


    notes = c.fetchall()


    conn.close()


    return jsonify(notes)


# -------------------------
# Mark all notifications read
# -------------------------
@notifications_bp.route('/api/notifications/mark-read', methods=['POST'])
def mark_notifications_read():

    if 'user_id' not in session:
        return jsonify({"success": False})


    conn = get_db()
    c = conn.cursor()


    c.execute("""
        UPDATE notifications
        SET is_read=TRUE
        WHERE user_id=%s
    """,
    (session['user_id'],))


    conn.commit()
    conn.close()


    return jsonify({"success": True})


# -------------------------
# Clear all notifications
# -------------------------
@notifications_bp.route('/api/notifications/clear-all', methods=['POST'])
@login_required
def clear_all_notifications():

    conn = get_db()
    c = conn.cursor()

    try:

        c.execute("""
            DELETE FROM notifications
            WHERE user_id=%s
        """, (
            session['user_id'],
        ))

        deleted_count = c.rowcount

        conn.commit()

        return jsonify({
            "success": True,
            "deleted": deleted_count
        })

    except Exception as e:

        conn.rollback()

        print(
            "CLEAR NOTIFICATIONS ERROR:",
            e
        )

        return jsonify({
            "success": False,
            "message": "Unable to clear notifications."
        }), 500

    finally:

        conn.close()
