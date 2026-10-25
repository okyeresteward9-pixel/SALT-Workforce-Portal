"""Step 2b - make login.html show server errors and skip the startup animation after a failed login.
Run from the project root:  python step2b_login_fix.py"""
import sys

PATH = "templates/login.html"
raw = open(PATH, "rb").read().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
src = raw.replace("\r\n", "\n")

if "{{ error" in src:
    sys.exit("login.html already patched - nothing to do.")

EDITS = [
# 1. show the server's error message
("""      <div class="error-box" id="errorBox">
        <i class="fa-solid fa-circle-exclamation"></i>
        <span id="errorText">Invalid email or password.</span>
      </div>""",
"""      <div class="error-box{% if error %} show{% endif %}" id="errorBox" role="alert">
        <i class="fa-solid fa-circle-exclamation"></i>
        <span id="errorText">{{ error or "Invalid email or password." }}</span>
      </div>"""),
# 2. no 5-second startup animation when the page is re-shown with an error
("""<div id="saltTechLoader" aria-label="Loading SALT Workforce">""",
"""{% if not error %}
<div id="saltTechLoader" aria-label="Loading SALT Workforce">"""),
]

for i, (old, new) in enumerate(EDITS, 1):
    n = src.count(old)
    if n != 1:
        sys.exit(f"Edit {i}: expected 1 match, found {n}. Nothing was changed.")
    src = src.replace(old, new)

# close the {% if %} after the loader's closing </div>
start = src.index("{% if not error %}")
marker = "</div>\n"
end_idx = src.index('<div class="salt-loader-core">', start)
# find the end of the loader block: the first line that is exactly "</div>" at column 0 after the core
close = src.index("\n</div>\n", end_idx) + len("\n</div>\n")
src = src[:close] + "{% endif %}\n" + src[close:]

open(PATH, "wb").write(src.replace("\n", nl).encode("utf-8"))
print("Patched templates/login.html")
