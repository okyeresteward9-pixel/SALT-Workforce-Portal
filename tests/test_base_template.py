"""base.html renders the avatar and a working notification panel (no database needed)."""
import re
from pathlib import Path

from flask import render_template

from helpers import make_app, set_session

ROOT = Path(__file__).resolve().parent.parent
AVATAR = "https://res.cloudinary.test/salt/ada.png"


def build_app():
    app = make_app()
    names = set(re.findall(r"url_for\('([\w.]+)'", (ROOT / "templates" / "base.html").read_text(encoding="utf-8")))
    for i, name in enumerate(sorted(names - {"static"})):
        if name not in app.view_functions:  # make_app() already provides "dashboard"
            app.add_url_rule(f"/stub/{i}", endpoint=name, view_func=lambda: "stub")

    @app.route("/page")
    def page():
        from flask import request
        avatar = request.args.get("avatar") or None
        return render_template("base.html", user={"name": "Ada"}, current_avatar=avatar)

    return app


def get_page(avatar=None):
    client = build_app().test_client()
    set_session(client, user_id=7, role="employee", name="Ada")
    return client.get("/page", query_string={"avatar": avatar} if avatar else None).get_data(as_text=True)


def test_uploaded_photo_appears_in_sidebar_and_top_bar():
    html = get_page(AVATAR)
    assert html.count(f'src="{AVATAR}"') == 2


def test_initial_is_shown_when_there_is_no_photo():
    html = get_page(None)
    assert "ada.png" not in html
    assert html.count("salt-avatar-fallback") >= 2


def test_notification_panel_has_working_controls():
    html = get_page()
    for element_id in ("saltMarkAllRead", "saltClearAllNotifications", "saltNotificationList",
                       "saltNotificationBadge", "saltTopNotificationBadge", "saltMobileNotifications"):
        assert f'id="{element_id}"' in html, element_id
    assert "/api/notifications/mark-read" in html and "/api/notifications/clear-all" in html
    assert "var(--salt-border" in html or "salt-notification-ui" in html


def test_client_script_embeds_the_logged_in_user_id():
    html = get_page()
    assert "const USER_ID = 7;" in html
