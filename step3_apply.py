"""Step 3 - PWA fixes. Unzip step3_pwa.zip into the project root, then run:
    python step3_apply.py
Changes app.py (versioned service-worker route) and templates/base.html (PWA tags on every page),
and deletes the unused static/js/web-push.js. Aborts without changes if an anchor is not found."""
import os
import sys


def load(path):
    raw = open(path, "rb").read().decode("utf-8")
    return raw, ("\r\n" if "\r\n" in raw else "\n"), raw.replace("\r\n", "\n")


def save(path, text, nl):
    open(path, "wb").write(text.replace("\n", nl).encode("utf-8"))


def patch(path, old, new, marker):
    raw, nl, src = load(path)
    if marker in src:
        print(f"{path}: already patched, skipped.")
        return
    if src.count(old) != 1:
        sys.exit(f"{path}: expected 1 match for the anchor, found {src.count(old)}. Nothing was changed.")
    save(path, src.replace(old, new), nl)
    print(f"{path}: patched.")


for needed in ("app.py", "templates/base.html", "static/js/service-worker.js", "static/js/pwa.js"):
    if not os.path.exists(needed):
        sys.exit(f"Missing {needed}. Run this from the project root after unzipping step3_pwa.zip there.")

# 1. Flask serves the service worker with a per-deploy version + correct headers
patch(
    "app.py",
    '''@app.route("/service-worker.js")
def service_worker():
    return send_from_directory(
        os.path.join(app.root_path, "static", "js"),
        "service-worker.js",
        mimetype="application/javascript"
    )
''',
    '''@app.route("/service-worker.js")
def service_worker():
    # The deploy's commit id (Render sets RENDER_GIT_COMMIT) becomes the cache
    # version, so every deploy gets a fresh cache and a clean update prompt.
    path = os.path.join(app.root_path, "static", "js", "service-worker.js")
    with open(path, encoding="utf-8") as f:
        script = f.read()
    version = (os.environ.get("RENDER_GIT_COMMIT") or str(int(os.path.getmtime(path))))[:12]
    response = app.response_class(
        script.replace("__APP_VERSION__", version),
        mimetype="application/javascript"
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response
''',
    "RENDER_GIT_COMMIT",
)

# 2. PWA tags on every page that extends base.html
patch(
    "templates/base.html",
    '''    <meta name="theme-color" content="#0B3D91">
''',
    '''    <meta name="theme-color" content="#0B3D91">
    <link rel="manifest" href="{{ url_for('static', filename='manifest.json') }}">
    <link rel="icon" type="image/png" sizes="32x32" href="{{ url_for('static', filename='icons/favicon-32.png') }}">
    <link rel="apple-touch-icon" href="{{ url_for('static', filename='icons/apple-touch-icon.png') }}">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="default">
    <meta name="apple-mobile-web-app-title" content="SALT Workforce">
    <script src="{{ url_for('static', filename='js/pwa.js') }}" defer></script>
''',
    "js/pwa.js",
)

# 3. Remove the unused file that registered a second, wrongly-scoped service worker
dead = "static/js/web-push.js"
if os.path.exists(dead):
    os.remove(dead)
    print(f"{dead}: removed (nothing referenced it).")

print("\nDone. Restart the app and hard-refresh (Ctrl+F5).")
