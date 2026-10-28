"""Admin announcements: publish, edit, delete, file download, Cloudinary upload signing."""
import cloudinary
import os
import time
from cloudinary import api as cloudinary_api, uploader
from database import get_db
from datetime import datetime
from decorators import is_admin
from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    session,
)
from psycopg2.extras import RealDictCursor
from services.notifications import notify_announcement
from werkzeug.utils import secure_filename

announcements_bp = Blueprint("announcements", __name__)

ANNOUNCEMENT_MAX_FILE_SIZE = 10 * 1024 * 1024

ANNOUNCEMENT_ALLOWED_EXTENSIONS = {
    'pdf', 'doc', 'docx', 'xls', 'xlsx',
    'ppt', 'pptx', 'txt', 'csv',
    'jpg', 'jpeg', 'png', 'gif', 'webp'
}


def _start_background_task(*args, **kwargs):
    """Run a function in the background through the app's Socket.IO instance."""
    return current_app.extensions["socketio"].start_background_task(*args, **kwargs)


def _announcement_admin_required():
    return is_admin()


def _cloudinary_config_values():
    config = cloudinary.config()

    return (
        config.cloud_name,
        config.api_key,
        config.api_secret
    )


def _delete_cloudinary_asset(public_id, resource_type):
    """
    Best-effort deletion of an announcement asset.

    New direct-upload announcements store the public_id and resource_type,
    so cleanup does not need to guess from a delivery URL.
    """
    if not public_id:
        return

    try:
        uploader.destroy(
            public_id,
            resource_type=resource_type or 'image',
            type='upload',
            invalidate=True
        )
    except Exception as exc:
        print(
            "CLOUDINARY ANNOUNCEMENT CLEANUP ERROR:",
            repr(exc)
        )


def _verify_cloudinary_asset(
    public_id,
    resource_type,
    secure_url,
    original_name
):
    """
    Verify the uploaded Cloudinary asset server-side.

    The browser never sends the file through Flask, so the finalization
    endpoint verifies the actual Cloudinary asset metadata before the
    announcement is saved.
    """

    if not public_id or not secure_url:
        raise ValueError(
            "Cloudinary did not return a valid uploaded asset."
        )

    cloud_name, _, _ = _cloudinary_config_values()

    expected_prefix = (
        f"https://res.cloudinary.com/{cloud_name}/"
    )

    if not secure_url.startswith(expected_prefix):
        raise ValueError(
            "Invalid Cloudinary asset URL."
        )

    extension = (
        secure_filename(original_name or "")
        .rsplit('.', 1)[1].lower()
        if '.' in secure_filename(original_name or "")
        else ''
    )

    if extension not in ANNOUNCEMENT_ALLOWED_EXTENSIONS:
        raise ValueError(
            "Invalid attachment type."
        )

    asset = cloudinary_api.resource(
        public_id,
        resource_type=resource_type or 'image',
        type='upload'
    )

    actual_bytes = int(
        asset.get('bytes') or 0
    )

    if actual_bytes > ANNOUNCEMENT_MAX_FILE_SIZE:

        _delete_cloudinary_asset(
            public_id,
            resource_type
        )

        raise ValueError(
            "Attachment is too large. Maximum allowed size is 10 MB."
        )

    actual_format = (
        str(asset.get('format') or '').lower()
    )

    # Cloudinary may represent some document formats differently,
    # so the original extension remains the primary allow-list check.
    if not actual_format:
        raise ValueError(
            "Cloudinary could not verify the attachment format."
        )

    return {
        "bytes": actual_bytes,
        "format": actual_format,
        "public_id": public_id,
        "resource_type": resource_type or 'image',
        "secure_url": secure_url,
        "asset_id": asset.get('asset_id')
    }


@announcements_bp.route(
    '/admin/announcements/upload-signature',
    methods=['POST']
)
def announcement_upload_signature():

    if not _announcement_admin_required():
        return jsonify({
            "status": "error",
            "message": "Access denied."
        }), 403

    data = request.get_json(
        silent=True
    ) or {}

    audience = str(
        data.get('audience') or 'everyone'
    ).strip().lower()

    if audience not in (
        'everyone',
        'staff',
        'admin'
    ):
        audience = 'everyone'

    cloud_name, api_key, api_secret = (
        _cloudinary_config_values()
    )

    if not cloud_name or not api_key or not api_secret:
        return jsonify({
            "status": "error",
            "message": "Cloudinary is not configured on the server."
        }), 500

    # Use a SIGNED upload preset so Cloudinary itself can enforce
    # the 10 MB limit and allowed formats.
    upload_preset = os.environ.get(
        "CLOUDINARY_ANNOUNCEMENT_UPLOAD_PRESET"
    )

    if not upload_preset:
        return jsonify({
            "status": "error",
            "message": (
                "CLOUDINARY_ANNOUNCEMENT_UPLOAD_PRESET "
                "is not configured."
            )
        }), 500

    timestamp = int(
        time.time()
    )

    folder = (
        f"salt_portal/announcements/{audience}"
    )

    # Cloudinary requires the same signed fields to be sent unchanged
    # with the browser upload.
    params_to_sign = {
        "folder": folder,
        "timestamp": timestamp,
        "upload_preset": upload_preset
    }

    signature = cloudinary.utils.api_sign_request(
        params_to_sign,
        api_secret
    )

    return jsonify({
        "status": "success",
        "cloud_name": cloud_name,
        "api_key": api_key,
        "timestamp": timestamp,
        "signature": signature,
        "folder": folder,
        "upload_preset": upload_preset,
        "resource_type": "auto",
        "max_file_size": ANNOUNCEMENT_MAX_FILE_SIZE
    })


@announcements_bp.route(
    '/admin/announcements',
    methods=['GET', 'POST']
)
def admin_announcements():

    # -------------------------
    # ACCESS CONTROL
    # -------------------------
    if 'user_id' not in session:
        return redirect('/')

    if not is_admin():
        return "Access Denied", 403

    conn = get_db()
    c = conn.cursor(cursor_factory=RealDictCursor)

    # =====================================================
    # CREATE ANNOUNCEMENT
    # =====================================================
    if request.method == 'POST':

        # The new browser flow sends JSON only.
        # No multipart file is ever sent to Flask.
        payload = request.get_json(
            silent=True
        )

        if payload is None:
            conn.close()

            return jsonify({
                "status": "error",
                "message": (
                    "Please use the current announcement form. "
                    "File uploads now go directly to Cloudinary."
                )
            }), 400

        title = str(
            payload.get('title') or ''
        ).strip()

        message = str(
            payload.get('message') or ''
        ).strip()

        audience = str(
            payload.get('audience') or 'everyone'
        ).strip().lower()

        if not title:
            conn.close()

            return jsonify({
                "status": "error",
                "message": "Please enter an announcement title."
            }), 400

        if not message:
            conn.close()

            return jsonify({
                "status": "error",
                "message": "Please enter an announcement message."
            }), 400

        if audience not in (
            'everyone',
            'staff',
            'admin'
        ):
            audience = 'everyone'

        uploaded_asset = (
            payload.get('file')
            if isinstance(payload.get('file'), dict)
            else None
        )

        file_name = None
        file_path = None
        public_id = None
        resource_type = None
        asset_id = None

        # -------------------------
        # VERIFY CLOUDINARY ASSET
        # -------------------------
        if uploaded_asset:

            file_name = secure_filename(
                str(
                    uploaded_asset.get('name') or ''
                )
            )

            file_path = str(
                uploaded_asset.get('secure_url') or ''
            )

            public_id = str(
                uploaded_asset.get('public_id') or ''
            )

            resource_type = str(
                uploaded_asset.get('resource_type')
                or 'image'
            )

            try:

                verified = _verify_cloudinary_asset(
                    public_id,
                    resource_type,
                    file_path,
                    file_name
                )

                asset_id = verified.get(
                    "asset_id"
                )

            except Exception as exc:

                _delete_cloudinary_asset(
                    public_id,
                    resource_type
                )

                conn.close()

                print(
                    "ANNOUNCEMENT ASSET VERIFICATION ERROR:",
                    repr(exc)
                )

                return jsonify({
                    "status": "error",
                    "message": str(exc)
                }), 400

        # -------------------------
        # CREATE DATABASE RECORD
        # -------------------------
        now = datetime.now()

        try:

            c.execute("""
                INSERT INTO announcements
                (
                    title,
                    message,
                    created_by,
                    created_at,
                    updated_at,
                    audience,
                    file_name,
                    file_path,
                    cloudinary_public_id,
                    cloudinary_resource_type,
                    cloudinary_asset_id
                )
                VALUES
                (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                )
            """, (
                title,
                message,
                session['user_id'],
                now,
                now,
                audience,
                file_name,
                file_path,
                public_id,
                resource_type,
                asset_id
            ))

            conn.commit()

        except Exception as exc:

            conn.rollback()

            if public_id:
                _delete_cloudinary_asset(
                    public_id,
                    resource_type
                )

            print(
                "CREATE ANNOUNCEMENT DATABASE ERROR:",
                repr(exc)
            )

            conn.close()

            return jsonify({
                "status": "error",
                "message": f"Database error: {str(exc)}"
            }), 500

        conn.close()

        # Notifications happen in the background so the admin
        # receives the success response immediately.
        _start_background_task(
            notify_announcement,
            audience,
            f"New Announcement: {title}",
            session['user_id']
        )

        return jsonify({
            "status": "success",
            "message": "Announcement published successfully."
        })

    # =====================================================
    # SEARCH
    # =====================================================
    search = request.args.get(
        'search',
        ''
    ).strip()

    # =====================================================
    # AUDIENCE FILTER
    # =====================================================
    audience_filter = request.args.get(
        'audience',
        'all'
    ).strip().lower()

    # Only accept valid filters
    if audience_filter not in (
        'all',
        'everyone',
        'staff',
        'admin'
    ):
        audience_filter = 'all'

    # =====================================================
    # BUILD ANNOUNCEMENT QUERY
    # =====================================================
    query = """
        SELECT
            announcements.id,
            announcements.title,
            announcements.message,
            announcements.created_by,
            announcements.created_at,
            announcements.updated_at,
            announcements.audience,
            announcements.file_name,
            announcements.file_path,

            COALESCE(
                employees.name,
                'Unknown'
            ) AS name

        FROM announcements

        LEFT JOIN employees
            ON announcements.created_by = employees.id

        WHERE 1=1
    """

    params = []

    # -------------------------
    # SEARCH FILTER
    # -------------------------
    if search:

        query += """
            AND (
                announcements.title ILIKE %s
                OR announcements.message ILIKE %s
                OR employees.name ILIKE %s
            )
        """

        search_value = f"%{search}%"

        params.extend([
            search_value,
            search_value,
            search_value
        ])

    # -------------------------
    # AUDIENCE FILTER
    # -------------------------
    if audience_filter != 'all':

        query += """
            AND announcements.audience=%s
        """

        params.append(
            audience_filter
        )

    # -------------------------
    # SORT
    # -------------------------
    query += """
        ORDER BY announcements.created_at DESC
    """

    c.execute(
        query,
        params
    )

    announcements = c.fetchall()

    # =====================================================
    # ANNOUNCEMENT STATISTICS
    # =====================================================

    # Total
    c.execute("""
        SELECT COUNT(*) AS count
        FROM announcements
    """)

    total_announcements = c.fetchone()['count']

    # Everyone
    c.execute("""
        SELECT COUNT(*) AS count
        FROM announcements
        WHERE audience='everyone'
           OR audience IS NULL
    """)

    everyone_count = c.fetchone()['count']

    # Staff
    c.execute("""
        SELECT COUNT(*) AS count
        FROM announcements
        WHERE audience='staff'
    """)

    staff_count = c.fetchone()['count']

    # Admin
    c.execute("""
        SELECT COUNT(*) AS count
        FROM announcements
        WHERE audience='admin'
    """)

    admin_count = c.fetchone()['count']

    conn.close()

    # =====================================================
    # RENDER PAGE
    # =====================================================
    return render_template(
        "admin_announcements.html",

        announcements=announcements,

        search=search,

        audience_filter=audience_filter,

        total_announcements=total_announcements,

        everyone_count=everyone_count,

        staff_count=staff_count,

        admin_count=admin_count
    )


@announcements_bp.route('/admin/announcement/file/<int:id>')
def download_announcement_file(id):

    if 'user_id' not in session:
        return redirect('/')

    conn = get_db()
    c = conn.cursor(
        cursor_factory=RealDictCursor
    )

    c.execute("""
        SELECT file_path, file_name
        FROM announcements
        WHERE id=%s
    """, (id,))

    announcement = c.fetchone()
    conn.close()

    if not announcement:
        return "Announcement not found", 404

    if not announcement['file_path']:
        return "No attachment", 404

    cloudinary_url = announcement['file_path']

    # View mode: preserve the original secure delivery URL.
    # Download mode: ask Cloudinary to force attachment delivery.
    if request.args.get("download") == "1":
        if "/upload/" in cloudinary_url:
            cloudinary_url = cloudinary_url.replace(
                "/upload/",
                "/upload/fl_attachment/"
            )

    return redirect(cloudinary_url)


@announcements_bp.route(
    '/admin/update_announcement/<int:id>',
    methods=['POST']
)
def update_announcement(id):

    if 'user_id' not in session:
        return jsonify({
            "status": "error",
            "message": "Please log in."
        }), 401

    if not is_admin():
        return jsonify({
            "status": "error",
            "message": "Access denied."
        }), 403

    payload = request.get_json(
        silent=True
    )

    if payload is None:
        return jsonify({
            "status": "error",
            "message": (
                "Please use the current announcement editor."
            )
        }), 400

    title = str(
        payload.get('title') or ''
    ).strip()

    message = str(
        payload.get('message') or ''
    ).strip()

    audience = str(
        payload.get('audience') or 'everyone'
    ).strip().lower()

    remove_file = bool(
        payload.get('remove_file')
    )

    uploaded_asset = (
        payload.get('file')
        if isinstance(payload.get('file'), dict)
        else None
    )

    if not title:
        return jsonify({
            "status": "error",
            "message": "Announcement title is required."
        }), 400

    if not message:
        return jsonify({
            "status": "error",
            "message": "Announcement message is required."
        }), 400

    if audience not in (
        'everyone',
        'staff',
        'admin'
    ):
        audience = 'everyone'

    conn = get_db()
    c = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        c.execute("""
            SELECT
                id,
                title,
                message,
                audience,
                file_name,
                file_path,
                cloudinary_public_id,
                cloudinary_resource_type,
                cloudinary_asset_id
            FROM announcements
            WHERE id=%s
        """, (id,))

        announcement = c.fetchone()

        if not announcement:
            return jsonify({
                "status": "error",
                "message": "Announcement not found."
            }), 404

        old_public_id = (
            announcement['cloudinary_public_id']
        )

        old_resource_type = (
            announcement['cloudinary_resource_type']
            or 'image'
        )

        new_file_name = announcement['file_name']
        new_file_path = announcement['file_path']
        new_public_id = old_public_id
        new_resource_type = old_resource_type
        new_asset_id = announcement['cloudinary_asset_id']

        uploaded_public_id = None
        uploaded_resource_type = None

        # -------------------------
        # REPLACEMENT ATTACHMENT
        # -------------------------
        if uploaded_asset:

            new_file_name = secure_filename(
                str(
                    uploaded_asset.get('name') or ''
                )
            )

            new_file_path = str(
                uploaded_asset.get('secure_url') or ''
            )

            uploaded_public_id = str(
                uploaded_asset.get('public_id') or ''
            )

            uploaded_resource_type = str(
                uploaded_asset.get('resource_type')
                or 'image'
            )

            try:

                verified = _verify_cloudinary_asset(
                    uploaded_public_id,
                    uploaded_resource_type,
                    new_file_path,
                    new_file_name
                )

                new_public_id = verified['public_id']
                new_resource_type = verified['resource_type']
                new_asset_id = verified.get('asset_id')

            except Exception as exc:

                _delete_cloudinary_asset(
                    uploaded_public_id,
                    uploaded_resource_type
                )

                return jsonify({
                    "status": "error",
                    "message": str(exc)
                }), 400

        elif remove_file:

            new_file_name = None
            new_file_path = None
            new_public_id = None
            new_resource_type = None
            new_asset_id = None

        # -------------------------
        # UPDATE DATABASE
        # -------------------------
        c.execute("""
            UPDATE announcements
            SET
                title=%s,
                message=%s,
                audience=%s,
                updated_at=%s,
                file_name=%s,
                file_path=%s,
                cloudinary_public_id=%s,
                cloudinary_resource_type=%s,
                cloudinary_asset_id=%s
            WHERE id=%s
        """, (
            title,
            message,
            audience,
            datetime.now(),
            new_file_name,
            new_file_path,
            new_public_id,
            new_resource_type,
            new_asset_id,
            id
        ))

        conn.commit()

        # Delete the previous Cloudinary asset only after the
        # database has successfully switched to the new one.
        if (
            uploaded_asset
            and old_public_id
            and old_public_id != new_public_id
        ):
            _delete_cloudinary_asset(
                old_public_id,
                old_resource_type
            )

        if (
            remove_file
            and old_public_id
        ):
            _delete_cloudinary_asset(
                old_public_id,
                old_resource_type
            )

        _start_background_task(
            notify_announcement,
            audience,
            f"Announcement Updated: {title}",
            session['user_id']
        )

        return jsonify({
            "status": "success",
            "message": "Announcement updated successfully."
        })

    except Exception as exc:

        conn.rollback()

        # If a newly uploaded asset was not committed, clean it up.
        if uploaded_public_id:
            _delete_cloudinary_asset(
                uploaded_public_id,
                uploaded_resource_type
            )

        print(
            "UPDATE ANNOUNCEMENT ERROR:",
            repr(exc)
        )

        return jsonify({
            "status": "error",
            "message": "Failed to update announcement."
        }), 500

    finally:

        conn.close()


@announcements_bp.route(
    '/admin/delete_announcement/<int:id>',
    methods=['POST']
)
def delete_announcement(id):

    if 'user_id' not in session:
        return jsonify({
            "status": "error",
            "message": "Unauthorized"
        }), 401

    if not is_admin():
        return jsonify({
            "status": "error",
            "message": "Access Denied"
        }), 403

    conn = get_db()
    c = conn.cursor(
        cursor_factory=RealDictCursor
    )

    try:

        c.execute("""
            SELECT
                id,
                title,
                cloudinary_public_id,
                cloudinary_resource_type
            FROM announcements
            WHERE id=%s
        """, (id,))

        announcement = c.fetchone()

        if not announcement:
            return jsonify({
                "status": "error",
                "message": "Announcement not found."
            }), 404

        c.execute("""
            DELETE FROM announcements
            WHERE id=%s
        """, (id,))

        conn.commit()

        if announcement['cloudinary_public_id']:
            _delete_cloudinary_asset(
                announcement['cloudinary_public_id'],
                announcement['cloudinary_resource_type']
            )

        return jsonify({
            "status": "success",
            "message": "Announcement deleted successfully."
        })

    except Exception as exc:

        conn.rollback()

        print(
            "DELETE ANNOUNCEMENT ERROR:",
            repr(exc)
        )

        return jsonify({
            "status": "error",
            "message": "Unable to delete announcement."
        }), 500

    finally:
        conn.close()
