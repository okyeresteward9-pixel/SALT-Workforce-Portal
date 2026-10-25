"""Step 2 - security patch for app.py. Run from the project root:  python step2_apply.py
Idempotent-safe: aborts without changing anything if an anchor is not found exactly once."""
import sys

PATH = "app.py"
raw = open(PATH, "rb").read().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
src = raw.replace("\r\n", "\n")

if "from security import" in src:
    sys.exit("app.py already patched - nothing to do.")

EDITS = [
# 1. load .env before anything reads os.environ
("""from gevent import monkey
monkey.patch_all()
""",
"""from gevent import monkey
monkey.patch_all()

from dotenv import load_dotenv
load_dotenv()  # reads .env for local development; harmless on Render
"""),

# 2. import helpers
("""from push_notifications import get_vapid_public_key
""",
"""from push_notifications import get_vapid_public_key
from security import LoginThrottle, origin_allowed, SAFE_METHODS
"""),

# 3. secret key, cookie flag, CORS
("""app.secret_key = os.environ.get(
    "SECRET_KEY",
    "fallback-secret"
)
""",
"""# APP_ENV=development enables debug mode and an insecure local-only key.
# Anything else (including unset) is treated as production.
IS_PRODUCTION = os.environ.get("APP_ENV", "production").strip().lower() != "development"

_secret_key = os.environ.get("SECRET_KEY")
if not _secret_key:
    if IS_PRODUCTION:
        raise RuntimeError(
            "SECRET_KEY environment variable is required. "
            "For local work set APP_ENV=development in your .env file."
        )
    _secret_key = "dev-only-insecure-key"
app.secret_key = _secret_key

# Comma-separated list, e.g. https://your-portal.onrender.com
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()
]
"""),
("""    SESSION_COOKIE_SECURE=True
)""",
"""    SESSION_COOKIE_SECURE=IS_PRODUCTION
)"""),
("""    cors_allowed_origins="*",""",
"""    cors_allowed_origins=ALLOWED_ORIGINS or None,  # None = same-origin only"""),

# 4. CSRF origin check + login throttle object
("""register_chat_socketio(socketio)
""",
"""register_chat_socketio(socketio)

login_throttle = LoginThrottle(max_attempts=5, window=900, ip_max=30)


def _client_ip():
    # Behind Render's proxy the real client is the LAST X-Forwarded-For entry
    # (the one the proxy appended); earlier entries can be forged by the client.
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.remote_addr or "unknown"


@app.before_request
def block_cross_site_writes():
    if request.method in SAFE_METHODS:
        return None
    if not origin_allowed(
        request.headers.get("Origin"),
        request.headers.get("Referer"),
        request.host,
        ALLOWED_ORIGINS,
        request.headers.get("Sec-Fetch-Site"),
    ):
        return jsonify({"status": "error", "message": "Cross-site request blocked."}), 403
    return None
"""),

# 5. login throttling
("""    conn = get_db()
    c = conn.cursor()

    c.execute(
        \"\"\"
        SELECT *
        FROM employees
        WHERE email=%s
        \"\"\",
        (email,)
    )

    user = c.fetchone()
    conn.close()

    if user and check_password_hash(user['password'], password):

        # Clear old session data
        session.clear()
""",
"""    client_ip = _client_ip()

    if login_throttle.blocked(client_ip, email):
        return render_template(
            "login.html",
            error="Too many failed attempts. Please wait 15 minutes and try again."
        ), 429

    conn = get_db()
    c = conn.cursor()

    c.execute(
        \"\"\"
        SELECT *
        FROM employees
        WHERE email=%s
        \"\"\",
        (email,)
    )

    user = c.fetchone()
    conn.close()

    if user and check_password_hash(user['password'], password):

        login_throttle.reset(client_ip, email)

        # Clear old session data
        session.clear()
"""),
("""    return render_template(
        "login.html",
        error="Invalid email or password."
    )
""",
"""    login_throttle.record_failure(client_ip, email)

    return render_template(
        "login.html",
        error="Invalid email or password."
    )
"""),

# 6. profile picture: images only (message already promised this)
("""            if ext not in ALLOWED_EXTENSIONS:

                conn.close()

                flash(
                    "Invalid file type. Only PNG, JPG and JPEG are allowed.",""",
"""            if ext not in {"png", "jpg", "jpeg"}:

                conn.close()

                flash(
                    "Invalid file type. Only PNG, JPG and JPEG are allowed.","""),

# 7. dev server
("""        port=5000,
        debug=True
    )""",
"""        port=int(os.environ.get("PORT", 5000)),
        debug=not IS_PRODUCTION
    )"""),
]

for i, (old, new) in enumerate(EDITS, 1):
    n = src.count(old)
    if n != 1:
        sys.exit(f"Edit {i}: expected 1 match, found {n}. Nothing was changed.")
    src = src.replace(old, new)

open(PATH, "wb").write(src.replace("\n", nl).encode("utf-8"))
print(f"Patched {PATH} ({len(EDITS)} edits). Copy security.py next to app.py and set the env vars.")
