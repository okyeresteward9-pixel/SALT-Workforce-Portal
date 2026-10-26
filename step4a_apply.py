"""Step 4a - close the state-changing-GET hole until those routes become POST (Step 4d).
Run from the project root:  python step4a_apply.py"""
import sys

PATH = "app.py"
raw = open(PATH, "rb").read().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
src = raw.replace("\r\n", "\n")

if "MUTATING_GET_PREFIXES" in src:
    sys.exit("app.py already patched - nothing to do.")

old = '''@app.before_request
def block_cross_site_writes():
    if request.method in SAFE_METHODS:
        return None
'''
new = '''# Legacy task links change data via GET (see tasks.html). Until they become POST
# (planned in the tasks refactor), refuse them when the request comes from another site.
MUTATING_GET_PREFIXES = ("/start_task/", "/complete_task/", "/delete_task/")


@app.before_request
def block_cross_site_writes():
    if request.method in SAFE_METHODS and not request.path.startswith(MUTATING_GET_PREFIXES):
        return None
'''
if src.count(old) != 1:
    sys.exit(f"Expected 1 match for the anchor, found {src.count(old)}. Nothing was changed.")
open(PATH, "wb").write(src.replace(old, new).replace("\n", nl).encode("utf-8"))
print("app.py patched.")
