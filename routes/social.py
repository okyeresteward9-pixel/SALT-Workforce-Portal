from flask import Blueprint, request, jsonify, session
from psycopg2.extras import RealDictCursor
from database import get_db
from werkzeug.utils import secure_filename
from cloudinary import uploader
import cloudinary_config  # noqa: F401 - ensures Cloudinary is configured
import re

social_bp = Blueprint("social", __name__)

ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
ALLOWED_VIDEO_EXTENSIONS = {"mp4", "mov", "webm"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 90 * 1024 * 1024


def _auth():
    return session.get("user_id")


def _serialize_dt(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _profile_path(row):
    return row.get("profile_pic") if row else None


def _create_main_notification(c, recipient_id, message):
    """Write Social activity into the portal's single notifications table.

    The caller commits the transaction so the Social action and notification
    are saved together.
    """
    if not recipient_id or not message:
        return
    c.execute("""
        INSERT INTO notifications (user_id, message, is_read, created_at)
        VALUES (%s, %s, FALSE, NOW())
    """, (recipient_id, message))


def _get_poll_for_post(c, post_id, user_id):
    c.execute("""
        SELECT sp.id, sp.question, sp.expires_at,
               COALESCE(v.total_votes, 0) AS total_votes,
               uv.option_id AS viewer_option_id
        FROM social_polls sp
        LEFT JOIN (
            SELECT poll_id, COUNT(*) AS total_votes
            FROM social_poll_votes GROUP BY poll_id
        ) v ON v.poll_id = sp.id
        LEFT JOIN social_poll_votes uv
          ON uv.poll_id = sp.id AND uv.user_id = %s
        WHERE sp.post_id = %s
    """, (user_id, post_id))
    poll = c.fetchone()
    if not poll:
        return None
    c.execute("""
        SELECT o.id, o.label, o.position, COUNT(v.id) AS votes
        FROM social_poll_options o
        LEFT JOIN social_poll_votes v ON v.option_id=o.id
        WHERE o.poll_id=%s
        GROUP BY o.id, o.label, o.position
        ORDER BY o.position, o.id
    """, (poll["id"],))
    options=[]
    total=int(poll["total_votes"] or 0)
    for r in c.fetchall():
        votes=int(r["votes"] or 0)
        options.append({
            "id": r["id"],
            "text": r["label"],
            "label": r["label"],
            "votes": votes,
            "percentage": round((votes/total)*100, 1) if total else 0
        })
    expires = poll["expires_at"]
    return {
        "id": poll["id"],
        "question": poll["question"],
        "expires_at": _serialize_dt(expires),
        "total_votes": total,
        "viewer_option_id": poll["viewer_option_id"],
        "closed": bool(expires and hasattr(expires, "timestamp") and expires.timestamp() <= __import__("time").time()),
        "options": options
    }


def _serialize_post(row, poll=None):
    if not row:
        return None
    return {
        "id": row["id"],
        "author_id": row["author_id"],
        "author_name": row.get("author_name") or "User",
        "author_profile_pic": _profile_path(row),
        "content": row.get("content") or "",
        "visibility": row.get("visibility") or "everyone",
        "post_type": row.get("post_type") or "post",
        "created_at": _serialize_dt(row.get("created_at")),
        "is_pinned": bool(row.get("is_pinned")),
        "like_count": int(row.get("like_count") or 0),
        "comment_count": int(row.get("comment_count") or 0),
        "share_count": int(row.get("share_count") or 0),
        "bookmark_count": int(row.get("bookmark_count") or 0),
        "viewer_liked": bool(row.get("viewer_liked")),
        "viewer_shared": bool(row.get("viewer_shared")),
        "viewer_bookmarked": bool(row.get("viewer_bookmarked")),
        "media": row.get("media") or [],
        "hashtags": row.get("hashtags") or [],
        "poll": poll,
    }


def _post_select_sql():
    return """
        SELECT
            p.id, p.author_id, p.content, p.visibility, p.post_type,
            p.created_at, p.is_pinned,
            e.name AS author_name, e.profile_pic,
            COALESCE(l.like_count, 0) AS like_count,
            COALESCE(cm.comment_count, 0) AS comment_count,
            COALESCE(sh.share_count, 0) AS share_count,
            COALESCE(bm.bookmark_count, 0) AS bookmark_count,
            EXISTS (SELECT 1 FROM social_reactions r
                    WHERE r.post_id=p.id AND r.user_id=%s) AS viewer_liked,
            EXISTS (SELECT 1 FROM social_shares s
                    WHERE s.post_id=p.id AND s.user_id=%s) AS viewer_shared,
            EXISTS (SELECT 1 FROM social_bookmarks b
                    WHERE b.post_id=p.id AND b.user_id=%s) AS viewer_bookmarked,
            COALESCE((SELECT json_agg(json_build_object(
                'url', m.media_url, 'type', m.media_type, 'name', m.original_name
            ) ORDER BY m.id) FROM social_post_media m WHERE m.post_id=p.id), '[]'::json) AS media,
            COALESCE((SELECT json_agg(h.tag ORDER BY h.tag)
                FROM social_post_hashtags ph JOIN social_hashtags h ON h.id=ph.hashtag_id
                WHERE ph.post_id=p.id), '[]'::json) AS hashtags
        FROM social_posts p
        JOIN employees e ON e.id=p.author_id
        LEFT JOIN (SELECT post_id, COUNT(*) AS like_count FROM social_reactions GROUP BY post_id) l
            ON l.post_id=p.id
        LEFT JOIN (SELECT post_id, COUNT(*) AS comment_count FROM social_comments
                   WHERE is_deleted=FALSE GROUP BY post_id) cm ON cm.post_id=p.id
        LEFT JOIN (SELECT post_id, COUNT(*) AS share_count FROM social_shares GROUP BY post_id) sh
            ON sh.post_id=p.id
        LEFT JOIN (SELECT post_id, COUNT(*) AS bookmark_count FROM social_bookmarks GROUP BY post_id) bm
            ON bm.post_id=p.id
    """


def _save_hashtags(c, post_id, content):
    tags = []
    seen = set()
    for raw in re.findall(r"(?<!\w)#([\w-]{1,50})", content or "", flags=re.UNICODE):
        tag = raw.lower()
        if tag not in seen:
            seen.add(tag)
            tags.append(tag)
    for tag in tags[:20]:
        c.execute("""
            INSERT INTO social_hashtags(tag) VALUES(%s)
            ON CONFLICT(tag) DO UPDATE SET tag=EXCLUDED.tag
            RETURNING id
        """, (tag,))
        hid = c.fetchone()["id"]
        c.execute("""
            INSERT INTO social_post_hashtags(post_id, hashtag_id)
            VALUES(%s, %s) ON CONFLICT DO NOTHING
        """, (post_id, hid))


@social_bp.get("/api/social/feed")
def social_feed():
    user_id = _auth()
    if not user_id:
        return jsonify({"success": False, "message": "Authentication required."}), 401

    post_type = (request.args.get("type") or "all").strip().lower()
    search = (request.args.get("q") or "").strip()
    author_only = request.args.get("mine") == "1"
    allowed_types = {"all", "post", "announcement", "achievement", "poll"}
    if post_type not in allowed_types:
        post_type = "all"

    conn = get_db()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        sql = _post_select_sql() + """
            WHERE p.is_deleted=FALSE
              AND (p.visibility='everyone' OR p.author_id=%s)
        """
        params = [user_id, user_id, user_id, user_id]
        if post_type != "all":
            sql += " AND p.post_type=%s"
            params.append(post_type)
        if author_only:
            sql += " AND p.author_id=%s"
            params.append(user_id)
        if search:
            sql += " AND (p.content ILIKE %s OR e.name ILIKE %s)"
            like = f"%{search}%"
            params.extend([like, like])
        sql += " ORDER BY p.is_pinned DESC, p.created_at DESC LIMIT 50"
        c.execute(sql, tuple(params))
        rows = c.fetchall()
        posts = []
        for r in rows:
            poll = _get_poll_for_post(c, r["id"], user_id) if r.get("post_type") == "poll" else None
            posts.append(_serialize_post(r, poll))
        return jsonify({"success": True, "posts": posts})
    except Exception as e:
        conn.rollback()
        print("SOCIAL FEED ERROR:", repr(e))
        return jsonify({"success": False, "message": "Could not load Social feed."}), 500
    finally:
        conn.close()


@social_bp.post("/api/social/posts")
def create_social_post():
    user_id = _auth()
    if not user_id:
        return jsonify({"success": False, "message": "Authentication required."}), 401

    content = ""
    visibility = "everyone"
    post_type = "post"
    uploaded_file = request.files.get("media")

    data = {}
    if request.content_type and request.content_type.startswith("multipart/form-data"):
        content = (request.form.get("content") or "").strip()
        visibility = (request.form.get("visibility") or "everyone").strip().lower()
        post_type = (request.form.get("post_type") or "post").strip().lower()
    else:
        data = request.get_json(silent=True) or {}
        content = (data.get("content") or "").strip()
        visibility = (data.get("visibility") or "everyone").strip().lower()
        post_type = (data.get("post_type") or "post").strip().lower()

    if not content and not uploaded_file:
        return jsonify({"success": False, "message": "Write something or add a photo before posting."}), 400
    if len(content) > 5000:
        return jsonify({"success": False, "message": "Post is too long. Maximum is 5,000 characters."}), 400
    if visibility not in {"everyone", "staff"}:
        visibility = "everyone"
    if post_type not in {"post", "achievement", "poll", "announcement"}:
        post_type = "post"

    upload_result = None
    upload_kind = None
    original_filename = None

    if uploaded_file and uploaded_file.filename:
        original_filename = secure_filename(uploaded_file.filename)
        ext = original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else ""

        if ext in ALLOWED_IMAGE_EXTENSIONS:
            upload_kind = "image"
            max_bytes = MAX_IMAGE_BYTES
        elif ext in ALLOWED_VIDEO_EXTENSIONS:
            upload_kind = "video"
            max_bytes = MAX_VIDEO_BYTES
        else:
            return jsonify({
                "success": False,
                "message": "Unsupported file. Use JPG, PNG, GIF or WEBP images, or MP4, MOV or WEBM videos."
            }), 400

        uploaded_file.seek(0, 2)
        size = uploaded_file.tell()
        uploaded_file.seek(0)

        if size > max_bytes:
            limit = "10 MB" if upload_kind == "image" else "90 MB"
            return jsonify({
                "success": False,
                "message": f"{upload_kind.title()} is too large. Maximum size is {limit}."
            }), 400

        try:
            upload_result = uploader.upload(
                uploaded_file,
                folder="salt_workforce/social",
                resource_type="video" if upload_kind == "video" else "image",
                use_filename=True,
                unique_filename=True,
                overwrite=False,
            )
        except Exception as e:
            print("SOCIAL CLOUDINARY UPLOAD ERROR:", repr(e))
            return jsonify({
                "success": False,
                "message": "Video upload failed." if upload_kind == "video" else "Photo upload failed."
            }), 500


    conn = get_db()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute("""
            INSERT INTO social_posts(author_id, content, visibility, post_type)
            VALUES(%s,%s,%s,%s)
            RETURNING id, author_id, content, visibility, post_type, created_at, is_pinned
        """, (user_id, content, visibility, post_type))
        post = c.fetchone()

        if upload_result:
            c.execute("""
                INSERT INTO social_post_media(post_id, media_url, media_type, original_name)
                VALUES(%s,%s,%s,%s)
            """, (post["id"], upload_result.get("secure_url"), upload_kind, original_filename))

        _save_hashtags(c, post["id"], content)

        # Poll data is created atomically with the Social post.
        if post_type == "poll":
            poll_options = data.get("poll_options") or []
            if not isinstance(poll_options, list):
                poll_options = []
            cleaned = []
            seen = set()
            for item in poll_options:
                label = str(item).strip()[:150]
                key = label.casefold()
                if label and key not in seen:
                    seen.add(key)
                    cleaned.append(label)
            if len(cleaned) < 2 or len(cleaned) > 5:
                raise ValueError("A poll must contain between 2 and 5 different options.")
            try:
                duration = int(data.get("poll_duration_days") or 3)
            except (TypeError, ValueError):
                duration = 3
            duration = max(1, min(duration, 30))
            c.execute("""
                INSERT INTO social_polls(post_id, question, expires_at)
                VALUES(%s,%s,NOW() + (%s || ' days')::interval)
                RETURNING id
            """, (post["id"], content[:300], duration))
            poll_id = c.fetchone()["id"]
            for pos, label in enumerate(cleaned):
                c.execute("""
                    INSERT INTO social_poll_options(poll_id,label,position)
                    VALUES(%s,%s,%s)
                """, (poll_id, label, pos))

        # Achievement posts link an existing employee achievement record.
        if post_type == "achievement":
            try:
                achievement_employee_id = int(data.get("achievement_employee_id"))
                achievement_id = int(data.get("achievement_id"))
            except (TypeError, ValueError):
                achievement_employee_id = achievement_id = None
            if achievement_employee_id and achievement_id:
                c.execute("""
                    SELECT 1 FROM employee_achievements
                    WHERE employee_id=%s AND achievement_id=%s
                """, (achievement_employee_id, achievement_id))
                if not c.fetchone():
                    raise ValueError("That achievement has not been earned by the selected employee.")
                c.execute("""
                    INSERT INTO social_post_achievements(post_id, employee_id, achievement_id)
                    VALUES(%s,%s,%s)
                """, (post["id"], achievement_employee_id, achievement_id))

        c.execute("SELECT name, profile_pic FROM employees WHERE id=%s", (user_id,))
        author = c.fetchone()
        conn.commit()

        post["author_name"] = author["name"] if author else "User"
        post["profile_pic"] = author["profile_pic"] if author else None
        post["like_count"] = post["comment_count"] = post["share_count"] = post["bookmark_count"] = 0
        post["viewer_liked"] = post["viewer_shared"] = post["viewer_bookmarked"] = False
        post["media"] = ([{"url": upload_result.get("secure_url"), "type": upload_kind, "name": original_filename}]
                         if upload_result else [])
        post["hashtags"] = re.findall(r"(?<!\w)#([\w-]{1,50})", content, flags=re.UNICODE)
        poll_data = _get_poll_for_post(c, post["id"], user_id) if post_type == "poll" else None
        return jsonify({"success": True, "post": _serialize_post(post, poll_data)}), 201
    except Exception as e:
        conn.rollback()
        print("CREATE SOCIAL POST ERROR:", repr(e))
        return jsonify({"success": False, "message": "Could not create post."}), 500
    finally:
        conn.close()


@social_bp.post("/api/social/posts/<int:post_id>/like")
def toggle_social_like(post_id):
    user_id = _auth()
    if not user_id:
        return jsonify({"success": False, "message": "Authentication required."}), 401
    conn = get_db()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute("SELECT id, author_id FROM social_posts WHERE id=%s AND is_deleted=FALSE", (post_id,))
        post = c.fetchone()
        if not post:
            return jsonify({"success": False, "message": "Post not found."}), 404
        c.execute("SELECT id FROM social_reactions WHERE post_id=%s AND user_id=%s", (post_id, user_id))
        existing = c.fetchone()
        if existing:
            c.execute("DELETE FROM social_reactions WHERE id=%s", (existing["id"],))
            liked = False
        else:
            c.execute("""INSERT INTO social_reactions(post_id,user_id,reaction_type)
                         VALUES(%s,%s,'like') ON CONFLICT(post_id,user_id) DO NOTHING""", (post_id, user_id))
            liked = True
        c.execute("SELECT COUNT(*) AS count FROM social_reactions WHERE post_id=%s", (post_id,))
        count = int(c.fetchone()["count"])
        if liked and post["author_id"] != user_id:
            c.execute("SELECT name FROM employees WHERE id=%s", (user_id,))
            actor = c.fetchone()
            actor_name = actor["name"] if actor else "Someone"
            _create_main_notification(
                c, post["author_id"], f"{actor_name} liked your Social post."
            )
        conn.commit()
        return jsonify({"success": True, "liked": liked, "like_count": count})
    except Exception as e:
        conn.rollback(); print("SOCIAL LIKE ERROR:", repr(e))
        return jsonify({"success": False, "message": "Could not update like."}), 500
    finally:
        conn.close()


@social_bp.get("/api/social/posts/<int:post_id>/comments")
def social_comments(post_id):
    user_id = _auth()
    if not user_id:
        return jsonify({"success": False, "message": "Authentication required."}), 401
    conn = get_db()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute("""SELECT c.id,c.post_id,c.user_id,c.parent_comment_id,c.content,c.created_at,
                            e.name AS author_name,e.profile_pic
                     FROM social_comments c JOIN employees e ON e.id=c.user_id
                     WHERE c.post_id=%s AND c.is_deleted=FALSE ORDER BY c.created_at ASC""", (post_id,))
        return jsonify({"success": True, "comments": [
            {"id":r["id"],"post_id":r["post_id"],"user_id":r["user_id"],
             "parent_comment_id":r["parent_comment_id"],"content":r["content"],
             "created_at":_serialize_dt(r["created_at"]),"author_name":r["author_name"],
             "author_profile_pic":r["profile_pic"]} for r in c.fetchall()
        ]})
    except Exception as e:
        conn.rollback(); print("SOCIAL COMMENTS ERROR:", repr(e))
        return jsonify({"success": False, "message": "Could not load comments."}), 500
    finally:
        conn.close()


@social_bp.post("/api/social/posts/<int:post_id>/comments")
def add_social_comment(post_id):
    user_id = _auth()
    if not user_id:
        return jsonify({"success": False, "message": "Authentication required."}), 401
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    parent_id = data.get("parent_comment_id")
    if not content:
        return jsonify({"success": False, "message": "Comment cannot be empty."}), 400
    if len(content) > 2000:
        return jsonify({"success": False, "message": "Comment is too long."}), 400
    conn = get_db()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute("SELECT id,author_id FROM social_posts WHERE id=%s AND is_deleted=FALSE", (post_id,))
        post = c.fetchone()
        if not post: return jsonify({"success":False,"message":"Post not found."}),404
        if parent_id:
            c.execute("SELECT id FROM social_comments WHERE id=%s AND post_id=%s AND is_deleted=FALSE", (parent_id,post_id))
            if not c.fetchone(): return jsonify({"success":False,"message":"Parent comment not found."}),400
        c.execute("""INSERT INTO social_comments(post_id,user_id,parent_comment_id,content)
                     VALUES(%s,%s,%s,%s)
                     RETURNING id,post_id,user_id,parent_comment_id,content,created_at""", (post_id,user_id,parent_id,content))
        comment=c.fetchone()
        c.execute("SELECT name,profile_pic FROM employees WHERE id=%s",(user_id,)); author=c.fetchone()
        if post["author_id"] != user_id:
            actor_name = author["name"] if author else "Someone"
            _create_main_notification(
                c, post["author_id"], f"{actor_name} commented on your Social post."
            )
        conn.commit()
        return jsonify({"success":True,"comment":{
            "id":comment["id"],"post_id":comment["post_id"],"user_id":comment["user_id"],
            "parent_comment_id":comment["parent_comment_id"],"content":comment["content"],
            "created_at":_serialize_dt(comment["created_at"]),"author_name":author["name"] if author else "User",
            "author_profile_pic":author["profile_pic"] if author else None}}),201
    except Exception as e:
        conn.rollback(); print("ADD SOCIAL COMMENT ERROR:",repr(e))
        return jsonify({"success":False,"message":"Could not add comment."}),500
    finally: conn.close()


@social_bp.post("/api/social/posts/<int:post_id>/share")
def share_social_post(post_id):
    """Share a Social post into the current user's own Social feed.

    The original post remains intact. The new post contains a clear
    'Shared from' attribution and copies the original media, if any.
    """
    user_id = _auth()
    if not user_id:
        return jsonify({"success": False, "message": "Authentication required."}), 401

    data = request.get_json(silent=True) or {}
    mode = (data.get("mode") or "feed").strip().lower()
    if mode != "feed":
        return jsonify({"success": False, "message": "Unsupported share option."}), 400

    conn = get_db()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)

        c.execute("""
            SELECT p.id, p.author_id, p.content, p.visibility, p.post_type,
                   e.name AS author_name, e.profile_pic
            FROM social_posts p
            JOIN employees e ON e.id=p.author_id
            WHERE p.id=%s AND p.is_deleted=FALSE
        """, (post_id,))
        post = c.fetchone()
        if not post:
            return jsonify({"success": False, "message": "Post not found."}), 404

        # Prevent accidental duplicate shares by the same employee.
        c.execute("""
            SELECT id FROM social_shares
            WHERE post_id=%s AND user_id=%s
        """, (post_id, user_id))
        existing = c.fetchone()
        if existing:
            c.execute("SELECT COUNT(*) AS count FROM social_shares WHERE post_id=%s", (post_id,))
            count = int(c.fetchone()["count"])
            conn.commit()
            return jsonify({
                "success": True,
                "shared": True,
                "already_shared": True,
                "share_count": count,
                "message": "You have already shared this post."
            })

        # Record the share.
        c.execute("""
            INSERT INTO social_shares(post_id,user_id)
            VALUES(%s,%s)
        """, (post_id, user_id))

        # Create a real post in the sharer's feed with attribution.
        original_content = (post["content"] or "").strip()
        shared_text = f"🔄 Shared from {post['author_name']}"

        if original_content:
            shared_text += f"\n\n{original_content}"

        c.execute("""
            INSERT INTO social_posts(author_id, content, visibility, post_type)
            VALUES(%s,%s,%s,'post')
            RETURNING id, author_id, content, visibility, post_type, created_at, is_pinned
        """, (user_id, shared_text, post["visibility"] or "everyone"))
        shared_post = c.fetchone()

        # Copy original media onto the newly-created shared post.
        c.execute("""
            SELECT media_url, media_type, original_name
            FROM social_post_media
            WHERE post_id=%s
            ORDER BY id
        """, (post_id,))
        for media in c.fetchall():
            c.execute("""
                INSERT INTO social_post_media(post_id, media_url, media_type, original_name)
                VALUES(%s,%s,%s,%s)
            """, (
                shared_post["id"],
                media["media_url"],
                media["media_type"],
                media["original_name"]
            ))

        # Copy hashtags so the shared post remains discoverable.
        c.execute("""
            SELECT h.tag
            FROM social_post_hashtags ph
            JOIN social_hashtags h ON h.id=ph.hashtag_id
            WHERE ph.post_id=%s
        """, (post_id,))
        for h in c.fetchall():
            tag = h["tag"]
            c.execute("""
                INSERT INTO social_hashtags(tag)
                VALUES(%s)
                ON CONFLICT(tag) DO UPDATE SET tag=EXCLUDED.tag
                RETURNING id
            """, (tag,))
            hid = c.fetchone()["id"]
            c.execute("""
                INSERT INTO social_post_hashtags(post_id, hashtag_id)
                VALUES(%s,%s) ON CONFLICT DO NOTHING
            """, (shared_post["id"], hid))

        # Notify the original author.
        if post["author_id"] != user_id:
            c.execute("SELECT name FROM employees WHERE id=%s", (user_id,))
            actor = c.fetchone()
            actor_name = actor["name"] if actor else "Someone"
            _create_main_notification(
                c,
                post["author_id"],
                f"{actor_name} shared your Social post."
            )

        c.execute(
            "SELECT COUNT(*) AS count FROM social_shares WHERE post_id=%s",
            (post_id,)
        )
        count = int(c.fetchone()["count"])

        # Return the new post so the browser can place it into the feed immediately.
        c.execute(
            "SELECT name, profile_pic FROM employees WHERE id=%s",
            (user_id,)
        )
        author = c.fetchone()

        shared_post["author_name"] = author["name"] if author else "User"
        shared_post["profile_pic"] = author["profile_pic"] if author else None
        shared_post["like_count"] = 0
        shared_post["comment_count"] = 0
        shared_post["share_count"] = 0
        shared_post["bookmark_count"] = 0
        shared_post["viewer_liked"] = False
        shared_post["viewer_shared"] = False
        shared_post["viewer_bookmarked"] = False

        c.execute("""
            SELECT media_url, media_type, original_name
            FROM social_post_media
            WHERE post_id=%s ORDER BY id
        """, (shared_post["id"],))
        shared_post["media"] = [
            {"url": r["media_url"], "type": r["media_type"], "name": r["original_name"]}
            for r in c.fetchall()
        ]

        shared_post["hashtags"] = []
        c.execute("""
            SELECT h.tag
            FROM social_post_hashtags ph
            JOIN social_hashtags h ON h.id=ph.hashtag_id
            WHERE ph.post_id=%s ORDER BY h.tag
        """, (shared_post["id"],))
        shared_post["hashtags"] = [r["tag"] for r in c.fetchall()]

        conn.commit()

        return jsonify({
            "success": True,
            "shared": True,
            "already_shared": False,
            "share_count": count,
            "post": _serialize_post(shared_post)
        })
    except Exception as e:
        conn.rollback()
        print("SOCIAL SHARE ERROR:", repr(e))
        return jsonify({"success": False, "message": "Could not share post."}), 500
    finally:
        conn.close()


@social_bp.post("/api/social/posts/<int:post_id>/bookmark")
def toggle_social_bookmark(post_id):
    user_id=_auth()
    if not user_id: return jsonify({"success":False,"message":"Authentication required."}),401
    conn=get_db()
    try:
        c=conn.cursor(cursor_factory=RealDictCursor)
        c.execute("SELECT id FROM social_posts WHERE id=%s AND is_deleted=FALSE",(post_id,))
        if not c.fetchone(): return jsonify({"success":False,"message":"Post not found."}),404
        c.execute("SELECT id FROM social_bookmarks WHERE post_id=%s AND user_id=%s",(post_id,user_id)); existing=c.fetchone()
        if existing:
            c.execute("DELETE FROM social_bookmarks WHERE id=%s",(existing["id"],)); bookmarked=False
        else:
            c.execute("INSERT INTO social_bookmarks(post_id,user_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",(post_id,user_id)); bookmarked=True
        c.execute("SELECT COUNT(*) AS count FROM social_bookmarks WHERE post_id=%s",(post_id,)); count=int(c.fetchone()["count"])
        conn.commit(); return jsonify({"success":True,"bookmarked":bookmarked,"bookmark_count":count})
    except Exception as e:
        conn.rollback(); print("SOCIAL BOOKMARK ERROR:",repr(e)); return jsonify({"success":False,"message":"Could not update bookmark."}),500
    finally: conn.close()


@social_bp.get("/api/social/bookmarks")
def social_bookmarks():
    user_id=_auth()
    if not user_id: return jsonify({"success":False,"message":"Authentication required."}),401
    conn=get_db()
    try:
        c=conn.cursor(cursor_factory=RealDictCursor)
        c.execute(_post_select_sql()+""" JOIN social_bookmarks myb ON myb.post_id=p.id AND myb.user_id=%s
                   WHERE p.is_deleted=FALSE AND (p.visibility='everyone' OR p.author_id=%s)
                   ORDER BY myb.created_at DESC LIMIT 50""",(user_id,user_id,user_id,user_id,user_id))
        return jsonify({"success":True,"posts":[_serialize_post(r) for r in c.fetchall()]})
    except Exception as e:
        conn.rollback(); print("SOCIAL BOOKMARKS ERROR:",repr(e)); return jsonify({"success":False,"message":"Could not load bookmarks."}),500
    finally: conn.close()


@social_bp.get("/api/social/notifications")
def social_notifications():
    """Compatibility endpoint: Social now uses the main portal notifications."""
    user_id = _auth()
    if not user_id:
        return jsonify({"success": False, "message": "Authentication required."}), 401
    conn = get_db()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute("""
            SELECT id, message, is_read, created_at
            FROM notifications
            WHERE user_id=%s
            ORDER BY created_at DESC
            LIMIT 50
        """, (user_id,))
        rows = c.fetchall()
        unread = sum(1 for r in rows if not r["is_read"])
        return jsonify({"success": True, "unread_count": unread, "notifications": [
            {
                "id": r["id"], "type": "portal", "is_read": r["is_read"],
                "created_at": _serialize_dt(r["created_at"]),
                "actor_name": None, "actor_profile_pic": None,
                "post_id": None, "comment_id": None, "message": r["message"]
            } for r in rows
        ]})
    except Exception as e:
        conn.rollback()
        print("SOCIAL NOTIFICATIONS ERROR:", repr(e))
        return jsonify({"success": False, "message": "Could not load notifications."}), 500
    finally:
        conn.close()


@social_bp.post("/api/social/notifications/read")
def social_notifications_read():
    """Compatibility endpoint: mark the main portal notifications as read."""
    user_id = _auth()
    if not user_id:
        return jsonify({"success": False, "message": "Authentication required."}), 401
    data = request.get_json(silent=True) or {}
    ids = data.get("ids")
    conn = get_db()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        if isinstance(ids, list) and ids:
            clean = []
            for item in ids:
                try:
                    clean.append(int(item))
                except (TypeError, ValueError):
                    pass
            if clean:
                c.execute("UPDATE notifications SET is_read=TRUE WHERE user_id=%s AND id=ANY(%s)", (user_id, clean))
        else:
            c.execute("UPDATE notifications SET is_read=TRUE WHERE user_id=%s", (user_id,))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        print("SOCIAL NOTIFICATIONS READ ERROR:", repr(e))
        return jsonify({"success": False, "message": "Could not update notifications."}), 500
    finally:
        conn.close()


@social_bp.post("/api/social/posts/<int:post_id>/poll/vote")
def vote_social_poll(post_id):
    user_id = _auth()
    if not user_id:
        return jsonify({"success": False, "message": "Authentication required."}), 401
    data = request.get_json(silent=True) or {}
    try:
        option_id = int(data.get("option_id"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Invalid poll option."}), 400

    conn = get_db()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute("""
            SELECT sp.id, sp.expires_at
            FROM social_polls sp
            JOIN social_posts p ON p.id=sp.post_id
            WHERE sp.post_id=%s AND p.is_deleted=FALSE
        """, (post_id,))
        poll = c.fetchone()
        if not poll:
            return jsonify({"success": False, "message": "Poll not found."}), 404
        if poll["expires_at"] and poll["expires_at"].timestamp() <= __import__("time").time():
            return jsonify({"success": False, "message": "This poll has closed."}), 400

        c.execute("SELECT id FROM social_poll_options WHERE id=%s AND poll_id=%s",
                  (option_id, poll["id"]))
        if not c.fetchone():
            return jsonify({"success": False, "message": "That option does not belong to this poll."}), 400

        # One vote per employee, but allow the employee to change that vote.
        c.execute("""
            INSERT INTO social_poll_votes(poll_id, option_id, user_id)
            VALUES(%s,%s,%s)
            ON CONFLICT(poll_id,user_id)
            DO UPDATE SET option_id=EXCLUDED.option_id, created_at=NOW()
            RETURNING option_id
        """, (poll["id"], option_id, user_id))
        saved = c.fetchone()
        if not saved:
            raise RuntimeError("Vote could not be saved.")

        conn.commit()

        # Return the complete current poll so the browser can reconcile quietly.
        poll_data = _get_poll_for_post(c, post_id, user_id)
        return jsonify({
            "success": True,
            "total_votes": poll_data["total_votes"],
            "viewer_option_id": poll_data["viewer_option_id"],
            "options": poll_data["options"]
        })
    except Exception as e:
        conn.rollback()
        print("SOCIAL POLL VOTE ERROR:", repr(e))
        return jsonify({"success": False, "message": "Could not save your vote."}), 500
    finally:
        conn.close()


@social_bp.get("/api/social/sidebar")
def social_sidebar():
    user_id = _auth()
    if not user_id:
        return jsonify({"success": False, "message": "Authentication required."}), 401
    conn = get_db()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)

        # Real trending hashtags from Social posts.
        c.execute("""
            SELECT h.tag, COUNT(ph.post_id) AS post_count
            FROM social_hashtags h
            JOIN social_post_hashtags ph ON ph.hashtag_id=h.id
            JOIN social_posts p ON p.id=ph.post_id AND p.is_deleted=FALSE
            WHERE p.created_at >= NOW() - INTERVAL '7 days'
              AND (p.visibility='everyone' OR p.author_id=%s)
            GROUP BY h.id, h.tag
            ORDER BY post_count DESC, h.tag ASC
            LIMIT 5
        """, (user_id,))
        trending = [{"tag": r["tag"], "post_count": int(r["post_count"])} for r in c.fetchall()]

        # Real recent achievements from the gamification tables.
        c.execute("""
            SELECT e.id AS employee_id, e.name, e.profile_pic,
                   a.id AS achievement_id, a.name AS achievement_name,
                   a.icon, ea.earned_at
            FROM employee_achievements ea
            JOIN employees e ON e.id=ea.employee_id
            JOIN achievements a ON a.id=ea.achievement_id
            ORDER BY ea.earned_at DESC
            LIMIT 5
        """)
        achievements = [{
            "employee_id": r["employee_id"], "name": r["name"],
            "profile_pic": r["profile_pic"], "achievement_id": r["achievement_id"],
            "achievement_name": r["achievement_name"], "icon": r["icon"],
            "earned_at": _serialize_dt(r["earned_at"])
        } for r in c.fetchall()]

        # Birthday support: use the birthday column when present. Older databases
        # may not have it yet, so return an empty list rather than breaking Social.
        c.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name='employees' AND column_name='birthday'
        """)
        has_birthday = bool(c.fetchone())
        birthdays = []
        if has_birthday:
            c.execute("""
                SELECT id, name, profile_pic, birthday
                FROM employees
                WHERE birthday IS NOT NULL
                  AND (EXTRACT(MONTH FROM birthday), EXTRACT(DAY FROM birthday)) >=
                      (EXTRACT(MONTH FROM CURRENT_DATE), EXTRACT(DAY FROM CURRENT_DATE))
                ORDER BY EXTRACT(MONTH FROM birthday), EXTRACT(DAY FROM birthday)
                LIMIT 5
            """)
            birthdays = [{
                "employee_id": r["id"], "name": r["name"], "profile_pic": r["profile_pic"],
                "birthday": r["birthday"].isoformat() if r["birthday"] else None
            } for r in c.fetchall()]
            if not birthdays:
                c.execute("""
                    SELECT id, name, profile_pic, birthday
                    FROM employees
                    WHERE birthday IS NOT NULL
                    ORDER BY EXTRACT(MONTH FROM birthday), EXTRACT(DAY FROM birthday)
                    LIMIT 5
                """)
                birthdays = [{
                    "employee_id": r["id"], "name": r["name"], "profile_pic": r["profile_pic"],
                    "birthday": r["birthday"].isoformat() if r["birthday"] else None
                } for r in c.fetchall()]

        return jsonify({"success": True, "trending": trending,
                        "achievements": achievements, "birthdays": birthdays})
    except Exception as e:
        conn.rollback()
        print("SOCIAL SIDEBAR ERROR:", repr(e))
        return jsonify({"success": False, "message": "Could not load Social sidebar data."}), 500
    finally:
        conn.close()


@social_bp.get("/api/social/achievement-options")
def social_achievement_options():
    user_id = _auth()
    if not user_id:
        return jsonify({"success": False, "message": "Authentication required."}), 401
    conn = get_db()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute("""
            SELECT DISTINCT e.id AS employee_id, e.name AS employee_name,
                            e.profile_pic, a.id AS achievement_id,
                            a.name AS achievement_name, a.icon
            FROM employee_achievements ea
            JOIN employees e ON e.id=ea.employee_id
            JOIN achievements a ON a.id=ea.achievement_id
            ORDER BY e.name, a.name
        """)
        return jsonify({"success": True, "options": [dict(r) for r in c.fetchall()]})
    except Exception as e:
        conn.rollback()
        print("SOCIAL ACHIEVEMENT OPTIONS ERROR:", repr(e))
        return jsonify({"success": False, "message": "Could not load achievements."}), 500
    finally:
        conn.close()
