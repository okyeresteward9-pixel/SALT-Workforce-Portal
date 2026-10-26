"""Step 4c-2 - (1) show the uploaded profile photo in the sidebar + top bar,
(2) make the notification panel in base.html actually work on every page
    (list, unread badges, Mark all read, Clear all, live toast).

Run from the project root:   python step4c2_ui_fix.py
Aborts without changing anything if an anchor is not found exactly once.
"""
import sys


def load(path):
    raw = open(path, "rb").read().decode("utf-8")
    return ("\r\n" if "\r\n" in raw else "\n"), raw.replace("\r\n", "\n")


def once(text, old, new, label):
    if text.count(old) != 1:
        sys.exit(f"STOPPED - nothing was changed. {label}: expected 1 match, found {text.count(old)}.")
    return text.replace(old, new)


# ------------------------------------------------------------------ app.py
app_nl, app = load("app.py")
base_nl, base = load("templates/base.html")

if "current_avatar" in app or "salt-notification-client" in base:
    sys.exit("Already applied - nothing to do.")

app = once(
    app,
    """        return dict(user=user)

    return dict(user=None)
""",
    """        return dict(
            user=user,
            current_avatar=(user or {}).get("profile_pic")
        )

    return dict(user=None, current_avatar=None)
""",
    "inject_user context processor",
)

# ------------------------------------------------------------ base.html: avatar
base = once(base, "{% set avatar = session.get('profile_pic') %}",
            "{% set avatar = current_avatar %}", "sidebar avatar")
base = once(base, "{% set top_avatar = session.get('profile_pic') %}",
            "{% set top_avatar = current_avatar %}", "top bar avatar")

# ------------------------------------------- base.html: panel buttons
base = once(
    base,
    '        <div id="saltNotificationList" class="salt-notification-list">',
    """        <div class="salt-notification-actions" id="saltNotificationActions">
            <button type="button" id="saltMarkAllRead" class="salt-notification-action">
                <i class="fa-solid fa-check-double"></i> Mark all read
            </button>
            <button type="button" id="saltClearAllNotifications" class="salt-notification-action is-danger">
                <i class="fa-regular fa-trash-can"></i> Clear all
            </button>
        </div>

        <div id="saltNotificationList" class="salt-notification-list">""",
    "notification list container",
)

# ------------------------------------------- base.html: styles + client script
CLIENT = r"""    <style id="salt-notification-ui">
    .salt-notification-actions{display:flex;gap:8px;padding:10px 18px;border-bottom:1px solid var(--salt-border,#e3eaf3)}
    .salt-notification-action{flex:1;display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:9px 10px;border:1px solid var(--salt-border,#d5deea);border-radius:10px;background:#fff;color:#16345c;font-weight:600;font-size:13px;font-family:inherit;cursor:pointer}
    .salt-notification-action:hover:not([disabled]){background:#f2f6fb}
    .salt-notification-action.is-danger{color:#b42318}
    .salt-notification-action[disabled]{opacity:.5;cursor:default}
    .salt-notification-item{display:flex;gap:12px;padding:12px 4px;border-bottom:1px solid var(--salt-border,#e8eef6)}
    .salt-notification-item .dot{flex:0 0 9px;width:9px;height:9px;margin-top:6px;border-radius:50%;background:#cbd5e1}
    .salt-notification-item.is-unread .dot{background:#1769c2}
    .salt-notification-item .msg{color:#16345c;font-size:14px;line-height:1.4;word-break:break-word}
    .salt-notification-item.is-unread .msg{font-weight:650}
    .salt-notification-item .time{color:var(--salt-muted,#64748b);font-size:12px;margin-top:3px}
    #saltMobileNotifications{position:relative}
    #saltMobileNotifications.has-unread::after{content:"";position:absolute;top:6px;left:calc(50% + 6px);width:8px;height:8px;border-radius:50%;background:#F04444}
    .salt-live-toast{position:fixed;top:calc(16px + env(safe-area-inset-top,0px));right:16px;z-index:2000;max-width:min(360px,90vw);padding:12px 14px;border-radius:12px;background:#0b3d91;color:#fff;font-size:14px;line-height:1.4;box-shadow:0 10px 30px rgba(0,0,0,.25)}
    </style>

    <script id="salt-notification-client">
    (() => {
        const list = document.getElementById('saltNotificationList');
        if (!list) return;

        const USER_ID = {{ session.get('user_id')|tojson }};
        const panel = document.getElementById('saltNotificationPanel');
        const badges = [
            document.getElementById('saltNotificationBadge'),
            document.getElementById('saltTopNotificationBadge')
        ];
        const mobileButton = document.getElementById('saltMobileNotifications');
        const markButton = document.getElementById('saltMarkAllRead');
        const clearButton = document.getElementById('saltClearAllNotifications');
        const triggers = ['saltNotificationsButton', 'saltTopNotifications', 'saltMobileNotifications']
            .map(id => document.getElementById(id)).filter(Boolean);

        const emptyState = list.innerHTML;   // the "No new notifications" markup from the shell
        let items = [];

        function formatTime(value) {
            let text = String(value || '');
            if (/^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$/.test(text)) text = text.replace(' ', 'T') + 'Z';
            const date = new Date(text);
            return isNaN(date) ? String(value || '') : date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
        }

        function updateBadges(unread) {
            badges.forEach(badge => {
                if (!badge) return;
                if (badge.id === 'saltNotificationBadge') badge.textContent = unread > 99 ? '99+' : String(unread);
                badge.hidden = unread === 0;
            });
            if (mobileButton) mobileButton.classList.toggle('has-unread', unread > 0);
        }

        function render() {
            const unread = items.filter(n => !n.is_read).length;
            updateBadges(unread);
            if (markButton) markButton.disabled = unread === 0;
            if (clearButton) clearButton.disabled = items.length === 0;

            if (!items.length) {
                list.innerHTML = emptyState;
                return;
            }
            list.textContent = '';
            items.forEach(note => {
                const row = document.createElement('div');
                row.className = 'salt-notification-item' + (note.is_read ? '' : ' is-unread');
                const dot = document.createElement('span');
                dot.className = 'dot';
                const body = document.createElement('div');
                const message = document.createElement('div');
                message.className = 'msg';
                message.textContent = note.message;
                const time = document.createElement('div');
                time.className = 'time';
                time.textContent = formatTime(note.created_at);
                body.append(message, time);
                row.append(dot, body);
                list.appendChild(row);
            });
        }

        async function load() {
            try {
                const response = await fetch('/api/notifications', { cache: 'no-store', credentials: 'same-origin' });
                if (!response.ok) return;
                const data = await response.json();
                if (Array.isArray(data)) { items = data; render(); }
            } catch (error) { /* offline: keep what we have */ }
        }

        const post = url => fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        }).then(response => response.json());

        if (markButton) markButton.addEventListener('click', async () => {
            try {
                const result = await post('/api/notifications/mark-read');
                if (result.success) { items = items.map(n => ({ ...n, is_read: true })); render(); }
            } catch (error) { /* ignore */ }
        });

        if (clearButton) clearButton.addEventListener('click', async () => {
            if (!items.length || !confirm('Clear all notifications? This cannot be undone.')) return;
            try {
                const result = await post('/api/notifications/clear-all');
                if (result.success) { items = []; render(); }
                else alert(result.message || 'Unable to clear notifications.');
            } catch (error) { /* ignore */ }
        });

        // Refresh the list whenever the panel is about to open.
        triggers.forEach(button => button.addEventListener('click', () => {
            if (!panel || !panel.classList.contains('is-open')) load();
        }));

        function toast(text) {
            const el = document.createElement('div');
            el.className = 'salt-live-toast';
            el.setAttribute('role', 'status');
            el.textContent = text;
            document.body.appendChild(el);
            setTimeout(() => el.remove(), 6000);
        }

        // Live updates over Socket.IO (falls back to the 30s refresh below if it cannot connect).
        function connectLive() {
            if (typeof io !== 'function' || USER_ID === null) return;
            const socket = io();
            socket.on('connect', () => socket.emit('join', { room: 'user_' + USER_ID }));
            socket.on('new_notification', note => {
                items.unshift({ id: note.id, message: note.message, created_at: note.created_at, is_read: false });
                render();
                toast(note.message);
            });
        }
        if (typeof io === 'function') {
            connectLive();
        } else if (USER_ID !== null) {
            const script = document.createElement('script');
            script.src = 'https://cdn.socket.io/4.7.5/socket.io.min.js';
            script.onload = connectLive;
            document.head.appendChild(script);
        }

        load();
        setInterval(() => { if (document.visibilityState === 'visible') load(); }, 30000);
    })();
    </script>

"""
base = once(
    base,
    "    <!-- =============================================================\n         GLOBAL SHELL BEHAVIOUR\n",
    CLIENT + "    <!-- =============================================================\n         GLOBAL SHELL BEHAVIOUR\n",
    "global shell behaviour comment",
)

open("app.py", "wb").write(app.replace("\n", app_nl).encode("utf-8"))
open("templates/base.html", "wb").write(base.replace("\n", base_nl).encode("utf-8"))
print("app.py: inject_user now provides current_avatar.")
print("templates/base.html: avatar fixed; notification panel now loads, shows badges, Mark all read, Clear all, live toast.")
print("\nRestart the app and hard-refresh (Ctrl+F5).")
