"""Steps 4b + 4c - move auth, PWA and notification code out of app.py.

Unzip step4bc.zip into the project root first, then run:   python step4bc_apply.py

Safe by design: every function is compared with the exact text it was built from. If your
app.py differs in any of them, NOTHING is changed and the script says which one.
"""
import ast
import hashlib
import re
import sys

EXPECTED = {
    "home": "888d8228a24f906504d7f7fd017f0fc54e811e8485d6b66de842620fdbfb18f5",
    "login": "ebfce8098e170f7315f87e645f6f5f2daba50fef72eb2e19c2ba70b4cc344751",
    "logout": "b2f6226961737e5ef7372c3e960940a3fa9ecc71ffcd08424779e57428d4238f",
    "offline": "7bfb275b9f76796cc47f89b79a927e543107cdb698969aea4cf9ceb20fcf90ba",
    "service_worker": "46a334db18be128964fac3665fede7e99a2e99b0a9ab6da238c66a7a7b219964",
    "push_public_key": "68c2be8609137bfa308802fe3715fcc016135cda3d06cca4a59a8ac3fef86907",
    "push_subscribe": "0f3d8bf7591468a9dfe913eb62f215843108c566fef1f05c4c2bddc9d708fd12",
    "create_notification": "7e504c8b67b32d1936a1ef69e57ef4e8582f4635b886c27b087949f1684f56a6",
    "notify_users": "8ee669d7d4404641877ca00c201ba59325fd7117f322d0a4c4fcf72565ea547b",
    "notify_announcement": "6ac13e9a6445c13e8d29d56c026e250b4854c90eef5eb3f168d6cfb0f16e1ccb",
    "get_notification_count": "368ea116081a43de58a4aba13d8278579e40fd00abf57f0ece84b5609988a4be",
    "api_notifications": "d22b1bc78673b413bc01df4548aba03a7a59951ca9de8ed395136d1912793725",
    "mark_notifications_read": "d06f6d362fe7540b8cfc6c91c270f3d4b239daa2e6372a24a38bf53d3f2fc6fc",
    "clear_all_notifications": "4d11c56c62d91dc424ca9ef640b763d2f5de6c605368c79c2cf905faf592a5de"
}

MOVED_ORDER = list(EXPECTED)
NEEDED_FILES = [
    "decorators.py", "routes/auth.py", "routes/pwa.py", "routes/notifications.py",
    "services/__init__.py", "services/notifications.py",
]


def die(msg):
    sys.exit("STOPPED - nothing was changed.\n" + msg)


def read(path):
    raw = open(path, "rb").read().decode("utf-8")
    return ("\r\n" if "\r\n" in raw else "\n"), raw.replace("\r\n", "\n")


def write(path, nl, text):
    open(path, "wb").write(text.replace("\n", nl).encode("utf-8"))


import os
for f in NEEDED_FILES:
    if not os.path.exists(f):
        die(f"Missing {f}. Unzip step4bc.zip into the project root first.")

nl, src = read("app.py")
if "from routes.auth import auth_bp" in src:
    sys.exit("app.py is already converted - nothing to do.")

lines = src.split("\n")
tree = ast.parse(src)

# ---- 1. locate + verify every function that moves ---------------------------------------
spans = {}
mismatched = []
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in EXPECTED:
        start = min([d.lineno for d in node.decorator_list] + [node.lineno])
        text = "\n".join(lines[start - 1:node.end_lineno])
        if hashlib.sha256(text.encode()).hexdigest() != EXPECTED[node.name]:
            mismatched.append(node.name)
        spans[node.name] = (start, node.end_lineno)

missing = [n for n in MOVED_ORDER if n not in spans]
if missing:
    die("These functions were not found in app.py: " + ", ".join(missing))
if mismatched:
    die("These functions in your app.py differ from the version I built against: "
        + ", ".join(mismatched) + "\nSend me those functions and I will rebuild the package.")

# also remove the old login throttle objects (now living in routes/auth.py)
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name == "_client_ip":
        spans["_client_ip"] = (node.lineno, node.end_lineno)
    if (isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "login_throttle" for t in node.targets)):
        spans["login_throttle"] = (node.lineno, node.end_lineno)
for needed in ("_client_ip", "login_throttle"):
    if needed not in spans:
        die(f"Could not find {needed} in app.py (was Step 2 applied?).")

# ---- 2. delete the spans (bottom-up), together with banner comments directly above ------
for name, (start, end) in sorted(spans.items(), key=lambda kv: -kv[1][0]):
    while start - 2 >= 0 and lines[start - 2].lstrip().startswith("#"):
        start -= 1
    del lines[start - 1:end]
src = "\n".join(lines)
src = re.sub(r"\n{4,}", "\n\n\n", src)


def replace_once(text, old, new, label):
    if text.count(old) != 1:
        die(f"app.py: expected exactly 1 match for {label}, found {text.count(old)}.")
    return text.replace(old, new)


# ---- 3. imports + registrations ----------------------------------------------------------
src = replace_once(
    src,
    "from request_workflow import register_request_workflow\n",
    "from routes.auth import auth_bp\n"
    "from routes.pwa import pwa_bp\n"
    "from routes.notifications import notifications_bp\n"
    "from services.notifications import (\n"
    "    init_notifications,\n"
    "    create_notification,\n"
    "    notify_users,\n"
    "    notify_announcement,\n"
    "    get_notification_count,\n"
    ")\n"
    "from request_workflow import register_request_workflow\n",
    "request_workflow import",
)
src = replace_once(
    src,
    "app.register_blueprint(chat_bp)\n",
    "app.register_blueprint(chat_bp)\n"
    "app.register_blueprint(auth_bp)\n"
    "app.register_blueprint(pwa_bp)\n"
    "app.register_blueprint(notifications_bp)\n",
    "chat blueprint registration",
)
src = replace_once(
    src,
    "register_chat_socketio(socketio)\n",
    "register_chat_socketio(socketio)\ninit_notifications(socketio)\n",
    "register_chat_socketio call",
)
src = replace_once(
    src,
    "from security import LoginThrottle, origin_allowed, SAFE_METHODS",
    "from security import origin_allowed, SAFE_METHODS",
    "security import",
)
if src.count("get_vapid_public_key") == 1:  # only the import is left
    src = src.replace("from push_notifications import get_vapid_public_key\n", "")

try:
    ast.parse(src)
except SyntaxError as e:
    die(f"The converted app.py would not compile ({e}). Please send me this message.")

# ---- 4. templates + tests that mention the renamed endpoints -----------------------------
base_nl, base = read("templates/base.html")
if base.count("url_for('logout')") != 1:
    die("templates/base.html: expected exactly one url_for('logout').")
base = base.replace("url_for('logout')", "url_for('auth.logout')")

test_nl, smoke = (None, None)
if os.path.exists("tests/test_smoke.py"):
    test_nl, smoke = read("tests/test_smoke.py")
    old = 'PUBLIC_ENDPOINTS = {"home", "offline", "service_worker", "static"}'
    if old in smoke:
        smoke = smoke.replace(
            old,
            'PUBLIC_ENDPOINTS = {"auth.home", "pwa.offline", "pwa.service_worker", "static"}',
        )

# ---- 5. write everything ------------------------------------------------------------------
before = len(lines)
write("app.py", nl, src)
write("templates/base.html", base_nl, base)
if smoke is not None:
    write("tests/test_smoke.py", test_nl, smoke)

print(f"app.py: {len(tree.body)} top-level items before, {len(ast.parse(src).body)} after; "
      f"{len(src.splitlines())} lines now.")
print("Moved to routes/auth.py, routes/pwa.py, routes/notifications.py, services/notifications.py")
print("base.html logout link -> auth.logout; smoke-test public endpoint names updated.")
print("\nNext: pytest, then python app.py and click through login, notifications, logout.")
