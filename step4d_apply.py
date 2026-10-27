"""Step 4d - move tasks (+ gamification helpers) out of app.py and make task actions POST-only.

Unzip step4d.zip into the project root, then run:   python step4d_apply.py

What changes
  * routes/tasks.py        the 14 task routes (verbatim, except the 3 actions below)
  * services/gamification.py  XP / streak / achievement helpers (verbatim)
  * /start_task/<id>, /complete_task/<id>, /delete_task/<id>  (GET links that changed data)
      become POST-only:  /tasks/<id>/start, /tasks/<id>/complete, /tasks/<id>/delete
  * tasks.html buttons + script, base.html menu links, test files and route snapshot follow.

Every moved function is compared with the exact text it was built from; if your app.py
differs, NOTHING is changed and the script names the function.
"""
import ast
import hashlib
import json
import os
import re
import sys

EXPECTED = {
    "_ensure_gamification_profile": "58e838e971dec841513d24be3f71caf2080987bf851fb174a44192ea3a3c178f",
    "_calculate_level": "4e16b80104ff7a51d4afe51e4f70a97dcf185d6665966be0a1256b5621d780d9",
    "award_xp": "ae55b8d741b2e6fd72adce4cb9d1744babb5eb740ca7c8cee4b77637740b8818",
    "update_attendance_streak": "9c6dddf8f675a065e6eec787bb797fab7ef033726dd0f2694a78f5d805c27b5a",
    "award_achievement": "34c63729396567f3e37ad287f2bb5793e6f0f5949ef618f0e679de9e9c37d2a1",
    "process_attendance_rewards": "7b3e71fc3e4f5a87fe4e04cfe6fa34b44f91461be703ab72f9799e30471d2035",
    "process_task_completion_rewards": "4517e753c539ba1e3bffc09c034625102f6d797bf1c1f6466a61b98b5cb06481",
    "build_comment_tree": "ec0e12bcc33b0855db4a134ed3ecbaba3cac3b08b88087af55d7d87845828604",
    "admin_tasks": "0abc588d68d2eea0ed88b4a05230924545f6021b2e0d478d779e8b5c6980de13",
    "admin_reply_task": "c67acb09302307d888f4cf0ea6064f576828160e5d75460f59893292af63b70a",
    "delete_task_route": "e1e0a81f66abc7666c649217391d3ad0de681aa2f45601d3d52f17ff330658d4",
    "assign_task": "46982a8c606c0e6541d7fd03afc8ba1b3bf9c4c6451b8e30b9dd3ff02a54e479",
    "tasks": "a9100517a5d80300e334222db785caf899a275765d6bd8fd31d475e2320481f3",
    "reply_task": "072aafcea72de5b9c3aa2341d3fdf6c3adde64d200be3070964175545866e731",
    "add_task_note": "a795e3d292c6dac6e86e78df425452946580744e156da52a75a0e5ee1e298202",
    "task_history": "0cef58a0092fc042101f70b2b7aeda43014402b3242c84af161048dcb8dca6ce",
    "export_task_history": "e35d20a022a2749db1315ad18f0def45b3becdc88599c813bba3759aa4ce77da",
    "complete_task": "72bb6708ebe4dc19be85d5db23873ba98a28f5f31323b8befaebe6895c622df2",
    "create_task": "1741a0053bcd0dff0d0f7bac373a22981b8114dfeb868f2d129ed676a8a21116",
    "start_task": "583c6fff00528a5216d3ebd432abafc00f52e94bb511d6029cc0f1029b77e817",
    "delete_task": "e632b97c091bc521fbdf453284b6b7b1aad965e9664d9757a13c6f972ca9ee38",
    "edit_task": "2694757d9608c228d1f3b41b4e0a566931ae2d39166d2aad98f316705f9a0011"
}
APP_NEEDS = ["_calculate_level", "_ensure_gamification_profile", "process_attendance_rewards"]
NEEDED_FILES = ["routes/tasks.py", "services/gamification.py", "decorators.py", "routes/notifications.py"]


def die(msg):
    sys.exit("STOPPED - nothing was changed.\n" + msg)


def read(path):
    raw = open(path, "rb").read().decode("utf-8")
    return ("\r\n" if "\r\n" in raw else "\n"), raw.replace("\r\n", "\n")


def write(path, nl, text):
    open(path, "wb").write(text.replace("\n", nl).encode("utf-8"))


def once(text, old, new, label, count=1):
    if text.count(old) != count:
        die(f"{label}: expected {count} match(es), found {text.count(old)}.")
    return text.replace(old, new)


for f in NEEDED_FILES:
    if not os.path.exists(f):
        die(f"Missing {f}. Unzip step4d.zip into the project root first "
            "(and make sure steps 4b/4c were applied).")

nl, src = read("app.py")
if "from routes.tasks import tasks_bp" in src:
    sys.exit("app.py is already converted - nothing to do.")
lines = src.split("\n")
tree = ast.parse(src)

# ---- 1. verify every function that moves --------------------------------------------------
spans, bad = {}, []
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in EXPECTED:
        start = min([d.lineno for d in node.decorator_list] + [node.lineno])
        text = "\n".join(lines[start - 1:node.end_lineno])
        if hashlib.sha256(text.encode()).hexdigest() != EXPECTED[node.name]:
            bad.append(node.name)
        spans[node.name] = (start, node.end_lineno)
missing = [n for n in EXPECTED if n not in spans]
if missing:
    die("Not found in app.py: " + ", ".join(missing))
if bad:
    die("These functions differ from the version I built against: " + ", ".join(bad)
        + "\nSend me those functions and I will rebuild the package.")

# ---- 2. prepare + check everything BEFORE writing anything ---------------------------------
base_nl, base = read("templates/base.html")
tasks_nl, tasks_html = read("templates/tasks.html")

# 2a. app.py: delete moved functions (bottom-up) incl. banner comments directly above them
for name, (start, end) in sorted(spans.items(), key=lambda kv: -kv[1][0]):
    while start - 2 >= 0 and lines[start - 2].lstrip().startswith("#"):
        start -= 1
    del lines[start - 1:end]
src = re.sub(r"\n{4,}", "\n\n\n", "\n".join(lines))

# 2b. app.py: imports, blueprint, and drop the temporary GET guard from Step 4a
gam_import = "from services.gamification import (\n" + "".join(f"    {n},\n" for n in APP_NEEDS) + ")\n"
src = once(src, "from request_workflow import register_request_workflow\n",
           "from routes.tasks import tasks_bp\n" + gam_import + "from request_workflow import register_request_workflow\n",
           "request_workflow import")
src = once(src, "app.register_blueprint(notifications_bp)\n",
           "app.register_blueprint(notifications_bp)\napp.register_blueprint(tasks_bp)\n",
           "notifications blueprint registration")
GUARD_OLD = (
    "# Legacy task links change data via GET (see tasks.html). Until they become POST\n"
    "# (planned in the tasks refactor), refuse them when the request comes from another site.\n"
    'MUTATING_GET_PREFIXES = ("/start_task/", "/complete_task/", "/delete_task/")\n'
    "\n\n"
    "@app.before_request\n"
    "def block_cross_site_writes():\n"
    "    if request.method in SAFE_METHODS and not request.path.startswith(MUTATING_GET_PREFIXES):\n"
    "        return None\n"
)
GUARD_NEW = (
    "@app.before_request\n"
    "def block_cross_site_writes():\n"
    "    if request.method in SAFE_METHODS:\n"
    "        return None\n"
)
src = once(src, GUARD_OLD, GUARD_NEW, "Step 4a cross-site GET guard")
try:
    ast.parse(src)
except SyntaxError as e:
    die(f"The converted app.py would not compile ({e}). Please send me this message.")

# 2c. base.html: endpoint names moved into the 'tasks' blueprint
for old, new, n in [
    ("url_for('tasks')", "url_for('tasks.tasks')", 2),
    ("url_for('admin_tasks')", "url_for('tasks.admin_tasks')", 1),
    ("url_for('assign_task')", "url_for('tasks.assign_task')", 1),
    ("request.endpoint == 'tasks'", "request.endpoint == 'tasks.tasks'", 2),
    ("request.endpoint == 'admin_tasks'", "request.endpoint == 'tasks.admin_tasks'", 1),
    ("request.endpoint == 'assign_task'", "request.endpoint == 'tasks.assign_task'", 1),
]:
    base = once(base, old, new, f"base.html {old}", n)

# 2d. tasks.html: links -> buttons, GET -> POST
for cls, action, endpoint, icon, label, href in [
    ("action-start", "start", "tasks.start_task", "fas fa-play", "Start", "/start_task/"),
    ("action-complete", "complete", "tasks.complete_task", "fas fa-check", "Complete", "/complete_task/"),
]:
    old = ('<a href="' + href + '{{ task.id }}" class="action-button ' + cls + '">\n'
           '                                        <i class="' + icon + '"></i> ' + label + '\n'
           '                                    </a>')
    new = ('<button type="button" class="action-button ' + cls + '" data-task-action="' + action + '" '
           'data-task-url="{{ url_for(\'' + endpoint + '\', id=task.id) }}">\n'
           '                                        <i class="' + icon + '"></i> ' + label + '\n'
           '                                    </button>')
    tasks_html = once(tasks_html, old, new, f"tasks.html {label} link")

tasks_html = once(
    tasks_html,
    '<a href="/delete_task/{{ task.id }}" class="action-button action-delete">\n'
    '                                    <i class="fas fa-trash"></i> Delete\n'
    '                                </a>',
    '<button type="button" class="action-button action-delete" data-task-action="delete" '
    'data-task-url="{{ url_for(\'tasks.delete_task\', id=task.id) }}">\n'
    '                                    <i class="fas fa-trash"></i> Delete\n'
    '                                </button>',
    "tasks.html Delete link")

tasks_html = once(
    tasks_html,
    "        const actionLink = target.closest(\n"
    "            'a[href*=\"/start_task/\"], a[href*=\"/complete_task/\"], a[href*=\"/delete_task/\"]'\n"
    "        );",
    '        const actionLink = target.closest("[data-task-action]");',
    "tasks.html click handler")
tasks_html = once(
    tasks_html,
    '        const href = link.getAttribute("href");\n'
    '        if (!href || link.getAttribute("aria-busy") === "true") return;\n'
    '\n'
    '        const isDelete = href.includes("/delete_task/");\n'
    '        const isStart = href.includes("/start_task/");',
    '        const href = link.dataset.taskUrl;\n'
    '        if (!href || link.getAttribute("aria-busy") === "true") return;\n'
    '\n'
    '        const isDelete = link.dataset.taskAction === "delete";\n'
    '        const isStart = link.dataset.taskAction === "start";',
    "tasks.html action handler")
tasks_html = once(tasks_html, '        fetch(href, {\n            method: "GET",',
                  '        fetch(href, {\n            method: "POST",', "tasks.html fetch method")

# 2e. tests + route snapshot that mention the old URLs
smoke_nl = smoke = None
if os.path.exists("tests/test_smoke.py"):
    smoke_nl, smoke = read("tests/test_smoke.py")
    a = smoke.find('@pytest.mark.parametrize("path", ["/start_task/1", "/complete_task/1", "/delete_task/1"])')
    b = smoke.find("def test_employee_login_and_dashboard")
    if a != -1 and b != -1 and a < b:
        replacement = (
            '@pytest.mark.parametrize("action", ["start", "complete", "delete"])\n'
            'def test_task_actions_are_post_only(client, action):\n'
            '    assert client.get(f"/tasks/1/{action}").status_code == 405           # no state change via links\n'
            '    assert client.get(f"/{action}_task/1").status_code in (404, 405)      # old URLs are gone\n'
            '\n\n'
            '@pytest.mark.parametrize("action", ["start", "complete", "delete"])\n'
            'def test_task_actions_reject_cross_site_and_logged_out_posts(client, fresh_ip, action):\n'
            '    r = client.post(f"/tasks/1/{action}", headers={**fresh_ip, "Origin": "https://evil.example"})\n'
            '    assert r.status_code == 403\n'
            '    r = client.post(f"/tasks/1/{action}", headers={**fresh_ip, "X-Requested-With": "XMLHttpRequest"})\n'
            '    assert r.status_code == 401\n'
            '\n\n'
        )
        smoke = smoke[:a] + replacement + smoke[b:]

snap_path = "tests/route_snapshot.json"
snap = None
if os.path.exists(snap_path):
    snap = json.load(open(snap_path, encoding="utf-8"))
    drop = {("/start_task/<int:id>", "GET"), ("/complete_task/<int:id>", "GET"), ("/delete_task/<int:id>", "GET")}
    have = {(r["rule"], r["methods"]) for r in snap}
    if not drop <= have:
        die("tests/route_snapshot.json does not contain the three old task routes; "
            "regenerate it with:  python tools/dump_routes.py   and run this script again.")
    snap = [r for r in snap if (r["rule"], r["methods"]) not in drop]
    for rule in ("/tasks/<int:id>/start", "/tasks/<int:id>/complete", "/tasks/<int:id>/delete"):
        snap.append({"rule": rule, "methods": "POST"})
    snap.sort(key=lambda r: (r["rule"], r["methods"]))

# ---- 3. write everything --------------------------------------------------------------------
write("app.py", nl, src)
write("templates/base.html", base_nl, base)
write("templates/tasks.html", tasks_nl, tasks_html)
if smoke is not None:
    write("tests/test_smoke.py", smoke_nl, smoke)
if snap is not None:
    open(snap_path, "w", encoding="utf-8").write(json.dumps(snap, indent=2) + "\n")

print(f"app.py: {len(src.splitlines())} lines now (tasks + gamification moved out).")
print("Task actions are now POST-only:  /tasks/<id>/start | /complete | /delete")
print("tasks.html, base.html, tests and route snapshot updated.")
print("\nNext: python -m pytest, then python app.py and try Start / Complete / Delete on the Tasks page.")
