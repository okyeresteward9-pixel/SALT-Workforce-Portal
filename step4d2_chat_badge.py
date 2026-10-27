"""Step 4d-2 - unread CHAT count on the sidebar, top bar and mobile bar (every page that uses base.html).

Run from the project root (after step4c2 and step4d):   python step4d2_chat_badge.py
Aborts without changing anything if an anchor is not found exactly once.

Adds
  * GET /api/chat/unread-count      -> {"count": N}   (messages sent to you that are not 'seen')
  * red count badges: sidebar "Chat", top-bar chat icon, mobile "Chat" tab
  * live updates: +1 the moment a message arrives over Socket.IO, refreshed on edit/delete/reconnect,
    plus a 30-second safety refresh. Opening a conversation marks it seen (existing behaviour), so the
    number drops the next time you land on any page.
"""
import os
import sys


def die(msg):
    sys.exit("STOPPED - nothing was changed.\n" + msg)


def read(path):
    raw = open(path, "rb").read().decode("utf-8")
    return ("\r\n" if "\r\n" in raw else "\n"), raw.replace("\r\n", "\n")


def once(text, old, new, label):
    if text.count(old) != 1:
        die(f"{label}: expected 1 match, found {text.count(old)}."
            + ("  (Was step4c2_ui_fix.py applied first?)" if "notification" in label.lower() else ""))
    return text.replace(old, new)


for f in ("decorators.py", "routes/chat.py", "templates/base.html"):
    if not os.path.exists(f):
        die(f"Missing {f}. Run this from the project root (steps 4b and 4c2 must be applied).")

chat_nl, chat = read("routes/chat.py")
base_nl, base = read("templates/base.html")
if "/api/chat/unread-count" in chat or "salt-chat-badge-client" in base:
    sys.exit("Already applied - nothing to do.")

# ------------------------------------------------------------------ routes/chat.py
chat = once(chat, "from werkzeug.utils import secure_filename\n",
            "from decorators import login_required\nfrom werkzeug.utils import secure_filename\n",
            "chat.py imports")
chat = once(
    chat,
    '@chat_bp.route("/chat/download/<int:message_id>")\n',
    '''@chat_bp.route("/api/chat/unread-count")
@login_required
def chat_unread_count():
    """Total unread chat messages for the logged-in user (drives the layout badges)."""

    conn = get_db()

    try:
        c = conn.cursor(cursor_factory=RealDictCursor)

        c.execute("""
            SELECT COUNT(*) AS count
            FROM messages
            WHERE receiver_id = %s
            AND COALESCE(seen, FALSE) = FALSE
        """, (session["user_id"],))

        row = c.fetchone()

    finally:
        conn.close()

    return jsonify({"count": int(row["count"]) if row else 0})


@chat_bp.route("/chat/download/<int:message_id>")
''',
    "chat.py download route",
)

# ------------------------------------------------------------------ templates/base.html
# 1. badges
base = once(
    base,
    '''                    <i class="fa-solid fa-comments"></i>
                    <span>Chat</span>
                </a>''',
    '''                    <i class="fa-solid fa-comments"></i>
                    <span>Chat</span>
                    <span id="saltChatBadge" class="salt-notification-badge" hidden></span>
                </a>''',
    "sidebar chat link",
)
base = once(
    base,
    '''                        <i class="fa-regular fa-comments"></i>
                    </a>''',
    '''                        <i class="fa-regular fa-comments"></i>
                        <span id="saltTopChatBadge" class="salt-count-badge" hidden></span>
                    </a>''',
    "top bar chat button",
)
base = once(
    base,
    '''        <a href="{{ url_for('chat.messages') }}"
           class="{% if request.endpoint == 'chat.messages' %}active{% endif %}">
            <i class="fa-solid fa-comments"></i>
            <span>Chat</span>
        </a>''',
    '''        <a href="{{ url_for('chat.messages') }}"
           class="{% if request.endpoint == 'chat.messages' %}active{% endif %}"
           style="position:relative">
            <i class="fa-solid fa-comments"></i>
            <span>Chat</span>
            <span id="saltMobileChatBadge" class="salt-count-badge" style="right:calc(50% - 26px)" hidden></span>
        </a>''',
    "mobile chat link",
)

# 2. styles (appended to the block added by step4c2)
base = once(
    base,
    "    #saltMobileNotifications{position:relative}\n",
    '''    #saltMobileNotifications{position:relative}
    .salt-count-badge{position:absolute;top:2px;right:2px;min-width:17px;height:17px;padding:0 4px;box-sizing:border-box;border-radius:99px;background:#F04444;color:#fff;font-size:10px;font-weight:800;line-height:17px;text-align:center}
    .salt-count-badge[hidden]{display:none}
    a.salt-icon-button[aria-label="Chat"]{position:relative}
''',
    "notification client styles",
)

# 3. share the notification client's socket instead of opening a second connection
base = once(
    base,
    "            socket.on('connect', () => socket.emit('join', { room: 'user_' + USER_ID }));\n",
    '''            socket.on('connect', () => socket.emit('join', { room: 'user_' + USER_ID }));
            window.saltSocket = socket;
            window.dispatchEvent(new CustomEvent('salt-socket', { detail: socket }));
''',
    "notification client socket",
)

# 4. the chat badge client
CLIENT = r"""    <script id="salt-chat-badge-client">
    (() => {
        const USER_ID = {{ session.get('user_id')|tojson }};
        const badges = ['saltChatBadge', 'saltTopChatBadge', 'saltMobileChatBadge']
            .map(id => document.getElementById(id)).filter(Boolean);
        if (USER_ID === null || !badges.length) return;

        let count = 0;

        function show(value) {
            count = Math.max(0, value);
            const text = count > 99 ? '99+' : String(count);
            badges.forEach(badge => { badge.textContent = text; badge.hidden = count === 0; });
        }

        async function refresh() {
            try {
                const response = await fetch('/api/chat/unread-count', { cache: 'no-store', credentials: 'same-origin' });
                if (!response.ok) return;
                const data = await response.json();
                if (typeof data.count === 'number') show(data.count);
            } catch (error) { /* offline: keep the last number */ }
        }

        function toast(text) {
            const el = document.createElement('div');
            el.className = 'salt-live-toast';
            el.style.top = 'calc(76px + env(safe-area-inset-top, 0px))';
            el.setAttribute('role', 'status');
            el.textContent = text;
            document.body.appendChild(el);
            setTimeout(() => el.remove(), 6000);
        }

        function attach(socket) {
            socket.on('new_message', message => {
                // Only messages sent TO me by someone else count.
                if (Number(message.receiver_id) !== Number(USER_ID) || Number(message.sender_id) === Number(USER_ID)) return;
                show(count + 1);
                const who = message.sender_name || message.sender || 'New message';
                const what = message.message || (message.file_name ? 'Sent an attachment' : 'New message');
                toast(who + ': ' + what);
            });
            socket.on('message_updated', refresh);   // edits and deletions
            socket.on('connect', refresh);           // catch up after a reconnect
        }

        if (window.saltSocket) attach(window.saltSocket);
        else window.addEventListener('salt-socket', event => attach(event.detail), { once: true });

        refresh();
        window.addEventListener('focus', refresh);
        setInterval(() => { if (document.visibilityState === 'visible') refresh(); }, 30000);
    })();
    </script>

"""
base = once(
    base,
    "    <!-- =============================================================\n         GLOBAL SHELL BEHAVIOUR\n",
    CLIENT + "    <!-- =============================================================\n         GLOBAL SHELL BEHAVIOUR\n",
    "global shell behaviour comment",
)

# keep the route-inventory test in step with the new endpoint
snap_path = "tests/route_snapshot.json"
snap = None
if os.path.exists(snap_path):
    import json
    snap = json.load(open(snap_path, encoding="utf-8"))
    if not any(r["rule"] == "/api/chat/unread-count" for r in snap):
        snap.append({"rule": "/api/chat/unread-count", "methods": "GET"})
        snap.sort(key=lambda r: (r["rule"], r["methods"]))

open("routes/chat.py", "wb").write(chat.replace("\n", chat_nl).encode("utf-8"))
open("templates/base.html", "wb").write(base.replace("\n", base_nl).encode("utf-8"))
if snap is not None:
    open(snap_path, "w", encoding="utf-8").write(json.dumps(snap, indent=2) + "\n")
print("routes/chat.py: added GET /api/chat/unread-count")
print("templates/base.html: chat count badges (sidebar, top bar, mobile) with live updates")
print("tests/route_snapshot.json: new route recorded" if snap is not None else "(no route snapshot found - skipped)")
