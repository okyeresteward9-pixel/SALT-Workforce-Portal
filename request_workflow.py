from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_from_directory, abort
from datetime import datetime
from werkzeug.utils import secure_filename
import os
import uuid
import json

from database import get_db
from push_notifications import send_web_push

requests_bp = Blueprint("requests_bp", __name__, url_prefix="/requests")

ALLOWED_EXTENSIONS = {
    "pdf", "doc", "docx", "xls", "xlsx", "csv",
    "png", "jpg", "jpeg", "webp"
}

APPROVER_POSITIONS = {
    "supervisor": "Immediate Supervisor",
    "registrar": "Registrar / Ag. Registrar",
    "president": "President",
    "auditor": "Internal Auditor",
    "accountant": "Accountant",
}

POSITION_OPTIONS = [
    "Registrar",
    "Ag. Registrar",
    "President",
    "Internal Auditor",
    "Accountant",
]

def now():
    return datetime.now()

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def init_request_tables():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id SERIAL PRIMARY KEY,
            request_no TEXT UNIQUE NOT NULL,
            requester_id INTEGER NOT NULL,
            request_type TEXT NOT NULL DEFAULT 'memo',
            title TEXT NOT NULL,
            memo_to TEXT,
            memo_from TEXT,
            memo_cc TEXT,
            memo_date TEXT,
            memo_subject TEXT,
            memo_body TEXT,
            is_finance_related BOOLEAN NOT NULL DEFAULT FALSE,
            total_amount NUMERIC(14,2) DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'draft',
            current_step INTEGER DEFAULT 0,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            completed_at TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS request_steps (
            id SERIAL PRIMARY KEY,
            request_id INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
            step_order INTEGER NOT NULL,
            approver_id INTEGER NOT NULL REFERENCES employees(id),
            position TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            decision TEXT,
            comment TEXT,
            signature_path TEXT,
            acted_at TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS request_attachments (
            id SERIAL PRIMARY KEY,
            request_id INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
            original_name TEXT NOT NULL,
            stored_name TEXT NOT NULL,
            uploaded_by INTEGER NOT NULL REFERENCES employees(id),
            uploaded_at TIMESTAMP NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS request_requisition_items (
            id SERIAL PRIMARY KEY,
            request_id INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
            description TEXT NOT NULL,
            quantity NUMERIC(14,2) DEFAULT 1,
            unit_price NUMERIC(14,2) DEFAULT 0,
            amount NUMERIC(14,2) DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS request_history (
            id SERIAL PRIMARY KEY,
            request_id INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
            actor_id INTEGER NOT NULL REFERENCES employees(id),
            action TEXT NOT NULL,
            comment TEXT,
            created_at TIMESTAMP NOT NULL
        )
    """)
    # Employee signature storage used by the approval workflow.
    c.execute("ALTER TABLE employees ADD COLUMN IF NOT EXISTS signature_path TEXT")
    conn.commit()
    conn.close()

def next_request_no(c):
    year = datetime.now().year
    prefix = f"REQ-{year}-"
    c.execute(
        "SELECT request_no FROM requests WHERE request_no LIKE %s ORDER BY id DESC LIMIT 1",
        (prefix + "%",)
    )
    row = c.fetchone()
    if not row:
        return prefix + "0001"
    try:
        number = int(row["request_no"].split("-")[-1]) + 1
    except Exception:
        number = 1
    return prefix + f"{number:04d}"

def notify(conn, user_id, message):
    """
    Create the normal SALT notification and also send a desktop
    browser push notification to every registered device for
    the recipient.

    Web Push is best-effort: a push failure must never break
    the request approval workflow.
    """

    c = conn.cursor()

    c.execute(
        "INSERT INTO notifications (user_id, message, created_at) VALUES (%s,%s,%s)",
        (user_id, message, now())
    )

    try:

        c.execute("""
            SELECT subscription
            FROM push_subscriptions
            WHERE user_id=%s
        """, (
            user_id,
        ))

        push_rows = c.fetchall()

        for push_row in push_rows:

            subscription = push_row["subscription"]

            if isinstance(subscription, str):
                subscription = json.loads(subscription)

            send_web_push(
                subscription=subscription,
                title="SALT Portal",
                body=message,
                url="/requests/",
                tag=f"request-notification-{user_id}"
            )

    except Exception as push_error:

        print(
            "REQUEST DESKTOP PUSH SKIPPED:",
            repr(push_error)
        )

def add_history(conn, request_id, actor_id, action, comment=None):
    c = conn.cursor()
    c.execute(
        "INSERT INTO request_history (request_id, actor_id, action, comment, created_at) VALUES (%s,%s,%s,%s,%s)",
        (request_id, actor_id, action, comment, now())
    )

def get_request(conn, request_id):
    c = conn.cursor()
    c.execute("""
        SELECT r.*, e.name AS requester_name, e.email AS requester_email,
               e.department AS requester_department
        FROM requests r
        JOIN employees e ON e.id = r.requester_id
        WHERE r.id=%s
    """, (request_id,))
    return c.fetchone()

def can_view_request(conn, req):
    uid = session["user_id"]
    if session.get("role") == "admin" or req["requester_id"] == uid:
        return True
    c = conn.cursor()
    c.execute(
        "SELECT 1 FROM request_steps WHERE request_id=%s AND approver_id=%s LIMIT 1",
        (req["id"], uid)
    )
    return bool(c.fetchone())

def save_attachments(conn, request_id, files, upload_root):
    folder = os.path.join(upload_root, str(request_id))
    os.makedirs(folder, exist_ok=True)

    c = conn.cursor()

    try:
        for file in files:
            if not file or not file.filename or not allowed_file(file.filename):
                continue

            original = secure_filename(file.filename)
            stored = f"{uuid.uuid4().hex}_{original}"

            file.save(os.path.join(folder, stored))

            c.execute("""
                INSERT INTO request_attachments
                (request_id, original_name, stored_name, uploaded_by, uploaded_at)
                VALUES (%s,%s,%s,%s,%s)
            """, (
                request_id,
                original,
                stored,
                session["user_id"],
                now()
            ))
    finally:
        c.close()

def approvers_for_position(conn, positions):
    """Return only employees authorized to approve for the specified office positions."""
    if not positions:
        return []
    placeholders = ",".join(["%s"] * len(positions))
    c = conn.cursor()
    c.execute(f"""
        SELECT id, name, email, role, department, position
        FROM employees
        WHERE COALESCE(can_approve_requests, FALSE)=TRUE
          AND position IN ({placeholders})
        ORDER BY name
    """, tuple(positions))
    return c.fetchall()


def employees_for_supervisor(conn):
    """Immediate supervisor is optional and may be any employee."""
    c = conn.cursor()
    c.execute("""
        SELECT id, name, email, role, department, position
        FROM employees
        ORDER BY name
    """)
    return c.fetchall()

@requests_bp.route("/")
def index():
    if "user_id" not in session:
        return redirect("/")
    conn = get_db()
    c = conn.cursor()
    uid = session["user_id"]
    c.execute("""
        SELECT * FROM requests
        WHERE requester_id=%s
        ORDER BY id DESC
    """, (uid,))
    my_requests = c.fetchall()
    c.execute("""
        SELECT COUNT(*) AS count
        FROM request_steps
        WHERE approver_id=%s AND status='pending'
    """, (uid,))
    pending = c.fetchone()["count"]
    conn.close()
    return render_template("requests.html", my_requests=my_requests, pending=pending)

@requests_bp.route("/new", methods=["GET", "POST"])
def new_request():
    if "user_id" not in session:
        return redirect("/")

    conn = get_db()
    c = conn.cursor()

    # Immediate Supervisor is optional and may be ANY employee.
    # The remaining stages are restricted to authorized office positions.
    supervisors = employees_for_supervisor(conn)
    registrars = approvers_for_position(conn, ["Registrar", "Ag. Registrar"])
    presidents = approvers_for_position(conn, ["President"])
    auditors = approvers_for_position(conn, ["Internal Auditor"])
    accountants = approvers_for_position(conn, ["Accountant"])

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        request_type = request.form.get("request_type", "memo")
        memo_to = request.form.get("memo_to", "").strip()
        memo_from = request.form.get("memo_from", session.get("name", "")).strip()
        memo_cc = request.form.get("memo_cc", "").strip()
        memo_date = request.form.get("memo_date", datetime.now().strftime("%Y-%m-%d"))
        memo_subject = request.form.get("memo_subject", title).strip()
        memo_body = request.form.get("memo_body", "").strip()
        finance = request.form.get("finance_related") == "yes"

        if not title or not memo_body:
            flash("Please complete the request title and memo body.", "error")
            conn.close()
            return redirect(url_for("requests_bp.new_request"))

        selected = []
        supervisor_id = request.form.get("supervisor_id")
        registrar_id = request.form.get("registrar_id")
        president_id = request.form.get("president_id")
        auditor_id = request.form.get("auditor_id")
        accountant_id = request.form.get("accountant_id")

        # Validate restricted approval stages against their authorized lists.
        # The immediate supervisor is different: any existing employee may be selected.
        def valid_id(rows, value):
            if not value:
                return False
            try:
                target = int(value)
            except ValueError:
                return False
            return any(int(row["id"]) == target for row in rows)

        if supervisor_id:
            try:
                supervisor_id_int = int(supervisor_id)
            except (TypeError, ValueError):
                flash("Invalid immediate supervisor selected.", "error")
                conn.close()
                return redirect(url_for("requests_bp.new_request"))

            c.execute(
                "SELECT id FROM employees WHERE id=%s",
                (supervisor_id_int,)
            )
            if not c.fetchone():
                flash("Selected immediate supervisor does not exist.", "error")
                conn.close()
                return redirect(url_for("requests_bp.new_request"))

            selected.append((supervisor_id_int, "supervisor"))

        if not valid_id(registrars, registrar_id):
            flash("Please select an authorized Registrar or Ag. Registrar.", "error")
            conn.close()
            return redirect(url_for("requests_bp.new_request"))
        if not valid_id(presidents, president_id):
            flash("Please select an authorized President.", "error")
            conn.close()
            return redirect(url_for("requests_bp.new_request"))

        selected.append((int(registrar_id), "registrar"))
        selected.append((int(president_id), "president"))

        if finance:
            if not valid_id(auditors, auditor_id):
                flash("Please select an authorized Internal Auditor.", "error")
                conn.close()
                return redirect(url_for("requests_bp.new_request"))
            if not valid_id(accountants, accountant_id):
                flash("Please select an authorized Accountant.", "error")
                conn.close()
                return redirect(url_for("requests_bp.new_request"))
            selected.append((int(auditor_id), "auditor"))
            selected.append((int(accountant_id), "accountant"))

        approver_ids = [x[0] for x in selected]
        if len(approver_ids) != len(set(approver_ids)):
            flash("Each approval stage must use a different person.", "error")
            conn.close()
            return redirect(url_for("requests_bp.new_request"))

        req_no = next_request_no(c)
        created = now()

        c.execute("""
            INSERT INTO requests
            (request_no, requester_id, request_type, title, memo_to, memo_from,
             memo_cc, memo_date, memo_subject, memo_body, is_finance_related,
             status, current_step, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (
            req_no, session["user_id"], request_type, title, memo_to, memo_from,
            memo_cc, memo_date, memo_subject, memo_body, finance,
            "submitted", 1, created, created
        ))
        request_id = c.fetchone()["id"]

        for order, (approver_id, position_key) in enumerate(selected, start=1):
            c.execute("""
                INSERT INTO request_steps
                (request_id, step_order, approver_id, position, status)
                VALUES (%s,%s,%s,%s,%s)
            """, (
                request_id, order, approver_id,
                APPROVER_POSITIONS[position_key],
                "pending" if order == 1 else "waiting"
            ))

        descriptions = request.form.getlist("item_description[]")
        quantities = request.form.getlist("item_quantity[]")
        prices = request.form.getlist("item_unit_price[]")
        total = 0.0

        for i, description in enumerate(descriptions):
            description = description.strip()
            if not description:
                continue
            try:
                quantity = float(quantities[i] or 0)
                unit_price = float(prices[i] or 0)
            except (ValueError, IndexError):
                quantity, unit_price = 0, 0
            amount = quantity * unit_price
            total += amount
            c.execute("""
                INSERT INTO request_requisition_items
                (request_id, description, quantity, unit_price, amount)
                VALUES (%s,%s,%s,%s,%s)
            """, (request_id, description, quantity, unit_price, amount))

        c.execute(
            "UPDATE requests SET total_amount=%s WHERE id=%s",
            (total, request_id)
        )

        save_attachments(
            conn,
            request_id,
            request.files.getlist("attachments"),
            os.path.join("static", "request_uploads")
        )

        first = selected[0][0]
        first_position = APPROVER_POSITIONS[selected[0][1]]
        notify(conn, first, f"New request {req_no} requires your approval ({first_position}).")
        add_history(conn, request_id, session["user_id"], "Submitted")

        conn.commit()
        conn.close()
        return redirect(url_for("requests_bp.detail", request_id=request_id))

    conn.close()
    return render_template(
        "new_request.html",
        supervisors=supervisors,
        registrars=registrars,
        presidents=presidents,
        auditors=auditors,
        accountants=accountants,
        today=datetime.now().strftime("%Y-%m-%d")
    )

@requests_bp.route("/<int:request_id>")
def detail(request_id):
    if "user_id" not in session:
        return redirect("/")
    conn = get_db()
    req = get_request(conn, request_id)
    if not req or not can_view_request(conn, req):
        conn.close()
        return "Access Denied", 403
    c = conn.cursor()
    c.execute("""
        SELECT s.*, e.name AS approver_name, e.department
        FROM request_steps s
        JOIN employees e ON e.id=s.approver_id
        WHERE s.request_id=%s
        ORDER BY s.step_order
    """, (request_id,))
    steps = c.fetchall()
    c.execute("SELECT * FROM request_attachments WHERE request_id=%s ORDER BY id", (request_id,))
    attachments = c.fetchall()
    c.execute("SELECT * FROM request_requisition_items WHERE request_id=%s ORDER BY id", (request_id,))
    items = c.fetchall()
    c.execute("""
        SELECT h.*, e.name AS actor_name
        FROM request_history h
        JOIN employees e ON e.id=h.actor_id
        WHERE h.request_id=%s ORDER BY h.id
    """, (request_id,))
    history = c.fetchall()
    c.execute("""
        SELECT s.*, e.name AS approver_name
        FROM request_steps s
        JOIN employees e ON e.id=s.approver_id
        WHERE s.request_id=%s AND s.status='pending'
        ORDER BY s.step_order LIMIT 1
    """, (request_id,))
    current = c.fetchone()
    is_current_approver = bool(current and current["approver_id"] == session["user_id"])
    conn.close()
    return render_template(
        "request_detail.html",
        req=req, steps=steps, attachments=attachments, items=items,
        history=history, current=current, is_current_approver=is_current_approver
    )

@requests_bp.route("/<int:request_id>/approve", methods=["POST"])
def approve(request_id):
    return _decision(request_id, "approved")

@requests_bp.route("/<int:request_id>/reject", methods=["POST"])
def reject(request_id):
    return _decision(request_id, "rejected")

@requests_bp.route("/<int:request_id>/return", methods=["POST"])
def return_request(request_id):
    return _decision(request_id, "returned")

def _decision(request_id, decision):
    if "user_id" not in session:
        return redirect("/")

    conn = get_db()
    req = get_request(conn, request_id)
    if not req:
        conn.close()
        return "Request not found", 404

    c = conn.cursor()
    c.execute("""
        SELECT * FROM request_steps
        WHERE request_id=%s AND approver_id=%s AND status='pending'
        ORDER BY step_order LIMIT 1
    """, (request_id, session["user_id"]))
    step = c.fetchone()

    if not step:
        conn.close()
        return "This request is not awaiting your approval.", 403

    comment = request.form.get("comment", "").strip()
    signature_path = None
    signature = request.files.get("signature")
    if signature and signature.filename:
        ext = signature.filename.rsplit(".", 1)[-1].lower()
        if ext in {"png", "jpg", "jpeg", "webp"}:
            folder = os.path.join("static", "signatures")
            os.makedirs(folder, exist_ok=True)
            filename = f"{session['user_id']}_{uuid.uuid4().hex}.{ext}"
            signature.save(os.path.join(folder, filename))
            signature_path = f"signatures/{filename}"

    acted = now()
    c.execute("""
        UPDATE request_steps
        SET status=%s, decision=%s, comment=%s, signature_path=%s, acted_at=%s
        WHERE id=%s
    """, ("approved" if decision == "approved" else decision,
          decision, comment, signature_path, acted, step["id"]))

    add_history(conn, request_id, session["user_id"], decision.title(), comment)

    if decision in {"rejected", "returned"}:
        new_status = "rejected" if decision == "rejected" else "returned"
        c.execute("UPDATE requests SET status=%s, updated_at=%s WHERE id=%s",
                  (new_status, acted, request_id))
        notify(conn, req["requester_id"],
               f"Request {req['request_no']} was {new_status}. {comment}".strip())
    else:
        c.execute("""
            SELECT * FROM request_steps
            WHERE request_id=%s AND step_order=%s
        """, (request_id, step["step_order"] + 1))
        next_step = c.fetchone()

        if next_step:
            c.execute("UPDATE request_steps SET status='pending' WHERE id=%s", (next_step["id"],))
            c.execute("""
                UPDATE requests
                SET current_step=%s, status='pending_approval', updated_at=%s
                WHERE id=%s
            """, (next_step["step_order"], acted, request_id))
            notify(conn, next_step["approver_id"],
                   f"Request {req['request_no']} is now awaiting your approval.")
            notify(conn, req["requester_id"],
                   f"Request {req['request_no']} was approved by {session.get('name')} and moved to the next stage.")
        else:
            c.execute("""
                UPDATE requests
                SET status='completed', completed_at=%s, updated_at=%s
                WHERE id=%s
            """, (acted, acted, request_id))
            notify(conn, req["requester_id"], f"Request {req['request_no']} has been completed.")

    conn.commit()
    conn.close()
    return redirect(url_for("requests_bp.detail", request_id=request_id))

@requests_bp.route("/approvals")
def approvals():
    if "user_id" not in session:
        return redirect("/")
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT r.*, e.name AS requester_name, s.position
        FROM request_steps s
        JOIN requests r ON r.id=s.request_id
        JOIN employees e ON e.id=r.requester_id
        WHERE s.approver_id=%s AND s.status='pending'
        ORDER BY r.created_at DESC
    """, (session["user_id"],))
    rows = c.fetchall()
    conn.close()
    return render_template("approval_inbox.html", requests=rows)

@requests_bp.route("/<int:request_id>/attachment/<int:attachment_id>")
def attachment(request_id, attachment_id):

    if "user_id" not in session:
        return redirect("/")

    conn = get_db()

    try:
        req = get_request(conn, request_id)

        if not req or not can_view_request(conn, req):
            return "Access Denied", 403

        c = conn.cursor()

        c.execute("""
            SELECT
                id,
                request_id,
                original_name,
                stored_name
            FROM request_attachments
            WHERE id=%s
              AND request_id=%s
        """, (
            attachment_id,
            request_id
        ))

        att = c.fetchone()

        if not att:
            return "Attachment not found", 404

        # --------------------------------------------------
        # ACTUAL UPLOAD DIRECTORY
        # --------------------------------------------------

        upload_folder = os.path.join(
            os.getcwd(),
            "static",
            "request_uploads",
            str(request_id)
        )

        # --------------------------------------------------
        # SECURITY
        # Never allow the database filename to escape
        # the request's upload folder.
        # --------------------------------------------------

        filename = os.path.basename(
            att["stored_name"]
        )

        full_path = os.path.join(
            upload_folder,
            filename
        )

        # --------------------------------------------------
        # CHECK FILE EXISTS
        # --------------------------------------------------

        if not os.path.isfile(full_path):
            print(
                "REQUEST ATTACHMENT NOT FOUND:",
                full_path
            )

            return "Attachment file not found", 404

        # --------------------------------------------------
        # SHOW FILE IN BROWSER
        # --------------------------------------------------

        return send_from_directory(
            upload_folder,
            filename,
            as_attachment=False,
            download_name=att["original_name"]
        )

    finally:
        conn.close()

@requests_bp.route("/<int:request_id>/print")
def print_request(request_id):
    if "user_id" not in session:
        return redirect("/")
    conn = get_db()
    req = get_request(conn, request_id)
    if not req or not can_view_request(conn, req):
        conn.close()
        return "Access Denied", 403
    c = conn.cursor()
    c.execute("""
        SELECT s.*, e.name AS approver_name
        FROM request_steps s
        JOIN employees e ON e.id=s.approver_id
        WHERE s.request_id=%s ORDER BY s.step_order
    """, (request_id,))
    steps = c.fetchall()
    c.execute("""
        SELECT * FROM request_requisition_items
        WHERE request_id=%s ORDER BY id
    """, (request_id,))
    items = c.fetchall()
    conn.close()
    return render_template("print_request.html", req=req, steps=steps, items=items)

@requests_bp.route("/profile/signature", methods=["POST"])
def save_signature():
    if "user_id" not in session:
        return redirect("/")
    file = request.files.get("signature")
    if not file or not file.filename:
        flash("Please choose a signature image.", "error")
        return redirect("/settings/profile")
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in {"png", "jpg", "jpeg", "webp"}:
        flash("Signature must be PNG, JPG or WEBP.", "error")
        return redirect("/settings/profile")
    folder = os.path.join("static", "signatures")
    os.makedirs(folder, exist_ok=True)
    filename = f"{session['user_id']}_signature.{ext}"
    file.save(os.path.join(folder, filename))
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "UPDATE employees SET signature_path=%s WHERE id=%s",
        (f"signatures/{filename}", session["user_id"])
    )
    conn.commit()
    conn.close()
    flash("Signature saved.", "success")
    return redirect("/settings/profile")

def register_request_workflow(app):
    init_request_tables()
    app.register_blueprint(requests_bp)

    @app.context_processor
    def request_dashboard_counts():
        if "user_id" not in session:
            return {}
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute("""
                SELECT COUNT(*) AS count FROM request_steps
                WHERE approver_id=%s AND status='pending'
            """, (session["user_id"],))
            pending_approvals = c.fetchone()["count"]
            c.execute("""
                SELECT COUNT(*) AS count FROM requests
                WHERE requester_id=%s
                  AND status NOT IN ('completed','rejected')
            """, (session["user_id"],))
            my_pending = c.fetchone()["count"]
            conn.close()
            return {
                "request_pending_approvals": pending_approvals,
                "request_my_pending": my_pending
            }
        except Exception as e:
            print("REQUEST DASHBOARD COUNTER ERROR:", repr(e))
            return {}