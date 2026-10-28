"""Step 4e - move admin employees + announcements out of app.py; role checks now ask the DATABASE.

Unzip step4e.zip into the project root, then run:   python step4e_apply.py

  * routes/employees.py      6 admin employee routes (verbatim, except the admin check)
  * routes/announcements.py  5 announcement routes + Cloudinary helpers + limits (verbatim, except the admin check)
  * decorators.is_admin()    asks the database for the current role, so a demoted or deleted admin loses
                             access immediately instead of when the cookie expires (up to 30 days).
                             Every denial message / status code stays exactly as it was.
  * templates               url_for(...) / request.endpoint names follow the move (employees.*, announcements.*)

SAFETY: every moved function is compared with the exact text it was built from, and every url_for /
request.endpoint in the files about to be written is checked against the endpoints that will exist.
If anything is off, NOTHING is changed and the script says why.
"""
import ast
import hashlib
import os
import re
import sys

EXPECTED = {
    "admin_employees": "05e5ba5feff9e2249f8fd94f625e0f456ad6624aa0973e6c354f1dae92dc11da",
    "add_employee": "44d914039f5e12b0c5b51a81b40bac2bab17cbe96638ae410285f127166a7367",
    "save_employee": "7b878c2c64c2b0ce4ea083565596598f4e15f7652aae57bbbf77372edd6ed7a7",
    "edit_employee": "a53f1f65ef60f7e967086150754d0c03af371a93f60f46b745043cd5c3dc6bce",
    "reset_employee_password": "3208db1422712a0d251b7c1c860611bf237767cf5073378c70e71b8b0394334e",
    "delete_employee": "d5240e11155940c8c14f99f63f53ff086dd13d1bc8e98e4060f48251e1e5d206",
    "_announcement_admin_required": "70e2281ad954dac71f26de18c9a41c078b5e9a0d6051e6ba79dd6ad3c2164804",
    "_cloudinary_config_values": "caefa1ffbe9c3f6f8aabdb94b47738a952b85733a07d3ac583757ffb89d0a4ef",
    "_delete_cloudinary_asset": "9afb2cfee6eaccd990459929444bccfc606f71a1a4645acd52b746b3d9b4d32e",
    "_verify_cloudinary_asset": "c4c9204cc18c00b1b9378d9313aa5174142284f1494cc4553a70bc11ba36d4b5",
    "announcement_upload_signature": "80108ac17d73e17b7ff134faa6627d728c7121148b18eb30b9926db5fe9f7b18",
    "admin_announcements": "6fc16f058c00ee22d8e283ebaf9b846de58ef7a2c3cf46e9d62238bd55f06fb2",
    "download_announcement_file": "9a9211b0c6436e0482fd47bd0d3db2f933bd7a2aede31759d9a923d1333577f9",
    "update_announcement": "2b9d56a7144d20b85aedfcdaca3f8e92461474a70625350e6180a13a34eb602c",
    "delete_announcement": "04de2dde0829ac9bc55e35d9dfc809246d104b80977c50afc0304d57e3366d6e",
    "ANNOUNCEMENT_MAX_FILE_SIZE": "76e8e4b2214b281d0888ada14b4a724dd380980b6d4064982a7408c252414315",
    "ANNOUNCEMENT_ALLOWED_EXTENSIONS": "7da138261a66d1dc7755f01bec2f517c97a482513f3289985557026c21951f4c"
}
EMP_ENDPOINTS = ["admin_employees", "add_employee", "save_employee", "edit_employee",
                 "reset_employee_password", "delete_employee"]
ANN_ENDPOINTS = ["announcement_upload_signature", "admin_announcements", "download_announcement_file",
                 "update_announcement", "delete_announcement"]
RENAME = {**{n: "employees." + n for n in EMP_ENDPOINTS}, **{n: "announcements." + n for n in ANN_ENDPOINTS}}
NEEDED_FILES = ["routes/employees.py", "routes/announcements.py", "decorators.py", "routes/tasks.py"]


def die(msg):
    sys.exit("STOPPED - nothing was changed.\n" + msg)


def read(path):
    raw = open(path, "rb").read().decode("utf-8")
    return ("\r\n" if "\r\n" in raw else "\n"), raw.replace("\r\n", "\n")


def once(text, old, new, label):
    if text.count(old) != 1:
        die(f"{label}: expected exactly 1 match, found {text.count(old)}.")
    return text.replace(old, new)


for f in NEEDED_FILES:
    if not os.path.exists(f):
        die(f"Missing {f}. Unzip step4e.zip into the project root first (steps up to 4d must be applied).")

app_nl, src = read("app.py")
if "from routes.employees import employees_bp" in src:
    sys.exit("app.py is already converted - nothing to do.")
lines = src.split("\n")
tree = ast.parse(src)

# ---- 1. verify everything that moves --------------------------------------------------------
spans, bad = {}, []
for node in tree.body:
    names = []
    if isinstance(node, ast.FunctionDef):
        names = [node.name]
    elif isinstance(node, ast.Assign):
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
    for name in names:
        if name in EXPECTED:
            start = min([d.lineno for d in getattr(node, "decorator_list", [])] + [node.lineno])
            text = "\n".join(lines[start - 1:node.end_lineno])
            if hashlib.sha256(text.encode()).hexdigest() != EXPECTED[name]:
                bad.append(name)
            spans[name] = (start, node.end_lineno)
missing = [n for n in EXPECTED if n not in spans]
if missing:
    die("Not found in app.py: " + ", ".join(missing))
if bad:
    die("These differ from the version I built against: " + ", ".join(bad)
        + "\nSend me those functions and I will rebuild the package.")

# ---- 2. app.py: delete moved code, add imports + registration -------------------------------
for name, (start, end) in sorted(spans.items(), key=lambda kv: -kv[1][0]):
    while start - 2 >= 0 and lines[start - 2].lstrip().startswith("#"):
        start -= 1
    del lines[start - 1:end]
new_app = re.sub(r"\n{4,}", "\n\n\n", "\n".join(lines))
new_app = once(new_app, "from routes.tasks import tasks_bp\n",
               "from routes.tasks import tasks_bp\nfrom routes.employees import employees_bp\n"
               "from routes.announcements import announcements_bp\n", "tasks blueprint import")
new_app = once(new_app, "app.register_blueprint(tasks_bp)\n",
               "app.register_blueprint(tasks_bp)\napp.register_blueprint(employees_bp)\n"
               "app.register_blueprint(announcements_bp)\n", "tasks blueprint registration")
try:
    ast.parse(new_app)
except SyntaxError as e:
    die(f"The converted app.py would not compile ({e}). Please send me this message.")

# ---- 3. templates: endpoint names follow the move ---------------------------------------------
overlay = {"app.py": new_app}
changed_templates = {}
for name in sorted(os.listdir("templates")):
    if not name.endswith(".html"):
        continue
    nl, text = read(os.path.join("templates", name))
    new = text
    for old_name, full in RENAME.items():
        new = re.sub(r"(url_for\(\s*)(['\"])" + old_name + r"\2", lambda m: f"{m.group(1)}{m.group(2)}{full}{m.group(2)}", new)
        new = re.sub(r"(request\.endpoint\s*(?:==|!=)\s*)(['\"])" + old_name + r"\2",
                     lambda m: f"{m.group(1)}{m.group(2)}{full}{m.group(2)}", new)
    if new != text:
        changed_templates[name] = (nl, new)
        overlay["templates/" + name] = new

# ---- 4. decorators.py: is_admin() ---------------------------------------------------------------
dec_nl, dec = read("decorators.py")
if "def is_admin" not in dec:
    dec = once(dec, "def login_required(view):\n",
               'def is_admin():\n'
               '    """True if the logged-in user is an admin according to the DATABASE (not the cookie)."""\n'
               '    user = current_user()\n'
               '    return bool(user and user["role"] == "admin")\n'
               '\n\n'
               'def login_required(view):\n', "decorators.py login_required")

# ---- 5. final safety net: every url_for / request.endpoint must name a real endpoint -----------
def source_of(path):
    return overlay[path] if path in overlay else read(path)[1]


python_files = [p for p in
                [f for f in os.listdir(".") if f.endswith(".py")]
                + ["routes/" + f for f in os.listdir("routes") if f.endswith(".py")]
                + ["services/" + f for f in os.listdir("services") if f.endswith(".py")]]
blueprints, endpoints = {}, {"static"}
trees = {}
for path in python_files:
    t = ast.parse(source_of(path))
    trees[path] = t
    for n in ast.walk(t):
        if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", "") == "Blueprint"
                and n.value.args and isinstance(n.value.args[0], ast.Constant)):
            for tg in n.targets:
                if isinstance(tg, ast.Name):
                    blueprints[tg.id] = n.value.args[0].value
for path, t in trees.items():
    for n in ast.walk(t):
        if isinstance(n, ast.FunctionDef):
            for d in n.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ("route", "get", "post"):
                    owner = getattr(d.func.value, "id", None)
                    endpoint = n.name
                    for kw in d.keywords:
                        if kw.arg == "endpoint" and isinstance(kw.value, ast.Constant):
                            endpoint = kw.value.value
                    endpoints.add(f"{blueprints[owner]}.{endpoint}" if owner in blueprints else endpoint)

problems = []
for path, t in trees.items():
    for n in ast.walk(t):
        if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "url_for" and n.args:
            a = n.args[0]
            if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value not in endpoints:
                problems.append(f"{path}:{n.lineno} url_for('{a.value}')")
for name in sorted(os.listdir("templates")):
    if not name.endswith(".html"):
        continue
    text = source_of("templates/" + name)
    for m in re.finditer(r"url_for\(\s*['\"]([\w.]+)['\"]", text):
        if m.group(1) not in endpoints:
            problems.append(f"templates/{name}:{text[:m.start()].count(chr(10)) + 1} url_for('{m.group(1)}')")
    for m in re.finditer(r"request\.endpoint\s*(?:==|!=)\s*['\"]([\w.]+)['\"]", text):
        if m.group(1) not in endpoints:
            problems.append(f"templates/{name}:{text[:m.start()].count(chr(10)) + 1} request.endpoint == '{m.group(1)}'")
if problems:
    die("These references would point at endpoints that do not exist:\n  " + "\n  ".join(problems)
        + "\nSend me this list and I will fix the package.")

# ---- 6. write -------------------------------------------------------------------------------------
open("app.py", "wb").write(new_app.replace("\n", app_nl).encode("utf-8"))
open("decorators.py", "wb").write(dec.replace("\n", dec_nl).encode("utf-8"))
for name, (nl, text) in changed_templates.items():
    open(os.path.join("templates", name), "wb").write(text.replace("\n", nl).encode("utf-8"))

print(f"app.py: {len(new_app.splitlines())} lines now (employees + announcements moved out).")
print("decorators.py: is_admin() added (role is read from the database).")
print("templates updated: " + (", ".join(sorted(changed_templates)) or "none"))
print(f"endpoint check: {len(endpoints)} endpoints, 0 broken url_for / request.endpoint references.")
print("\nNext: python -m pytest, then python app.py and open Employees and Announcements as an admin.")
