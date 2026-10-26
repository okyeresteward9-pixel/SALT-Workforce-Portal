"""Offline page and the versioned service worker."""
import os

from flask import Blueprint, current_app, render_template

pwa_bp = Blueprint("pwa", __name__)


@pwa_bp.route("/offline")
def offline():
    return render_template("offline.html")


@pwa_bp.route("/service-worker.js")
def service_worker():
    # The deploy's commit id (Render sets RENDER_GIT_COMMIT) becomes the cache
    # version, so every deploy gets a fresh cache and a clean update prompt.
    path = os.path.join(current_app.root_path, "static", "js", "service-worker.js")
    with open(path, encoding="utf-8") as f:
        script = f.read()
    version = (os.environ.get("RENDER_GIT_COMMIT") or str(int(os.path.getmtime(path))))[:12]
    response = current_app.response_class(
        script.replace("__APP_VERSION__", version),
        mimetype="application/javascript"
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response
