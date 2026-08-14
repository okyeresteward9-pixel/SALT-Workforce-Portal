class ChatApp {

    constructor() {

        // =====================================================
        // ELEMENTS
        // =====================================================

        this.chatBox = document.getElementById("chat-box");
        this.form = document.getElementById("chat-form");
        this.messageInput = document.getElementById("message-input");

        this.fileInput = document.getElementById("file-input");

        this.previewContainer =
            document.getElementById("preview-container");

        this.previewImage =
            document.getElementById("preview-image");

        this.previewFile =
            document.getElementById("preview-file");

        this.removePreview =
            document.getElementById("remove-preview");

        this.emojiBtn =
            document.getElementById("emoji-btn");

        this.emojiPicker =
            document.getElementById("emoji-picker");

        this.sidebar =
            document.getElementById("sidebar");

        this.overlay =
            document.getElementById("overlay");

        this.menuBtn =
            document.getElementById("menu-btn");

        this.searchInput =
            document.getElementById("search-users");

        this.noUsersFound =
            document.getElementById("no-users-found");


        // =====================================================
        // USER
        // =====================================================

        this.currentUser =
            window.CURRENT_USER;

        this.receiver =
            window.RECEIVER_ID;


        // =====================================================
        // STATE
        // =====================================================

        this.messages = new Map();

        this.isSending = false;

        this.typingTimer = null;

        // Chat notification UI
        this.notificationSound =
            document.getElementById("chatNotificationSound");

        this.toastContainer =
            document.getElementById("chat-notification-toast-container");

        this.soundUnlocked = false;


        // =====================================================
        // SOCKET
        // =====================================================

        this.socket = io();

        this.init();

    }


    // =====================================================
    // INITIALIZE
    // =====================================================

    init() {

        this.initSocket();

        this.initEvents();

        this.initConversationNavigation();

        this.updateChatHeader(
            window.RECEIVER_NAME || ""
        );

        this.highlightCurrentUser();

        this.loadMessages();

        this.highlightCurrentUser();

    }


    // =====================================================
    // SOCKET
    // =====================================================

    initSocket() {

        this.socket.on("connect", () => {

            console.log(
                "SALTY connected:",
                this.socket.id
            );

            this.socket.emit(
                "join_chat",
                {
                    user_id: this.receiver
                }
            );

            this.setStatus(
                "Active",
                "text-green-500"
            );

            // Opening this conversation marks its unread messages as seen
            // on the backend, so remove the sidebar badge immediately.
            this.clearSidebarUnread(
                this.receiver
            );

        });


        this.socket.on("disconnect", () => {

            this.setStatus(
                "Reconnecting...",
                "text-amber-500"
            );

        });


        this.socket.on(
            "connect_error",
            (error) => {

                console.error(
                    "SALTY socket error:",
                    error
                );

                this.setStatus(
                    "Connection problem",
                    "text-red-500"
                );

            }
        );


        this.socket.on(
            "user_online",
            data => {

                if (
                    Number(data.user_id) ===
                    Number(this.receiver)
                ) {

                    this.setStatus(
                        "🟢 Online",
                        "text-green-500"
                    );

                }

            }
        );


        this.socket.on(
            "user_offline",
            data => {

                if (
                    Number(data.user_id) ===
                    Number(this.receiver)
                ) {

                    this.setStatus(
                        "Last seen just now",
                        "text-gray-500"
                    );

                }

            }
        );


        this.socket.on(
            "new_message",
            chat => {

                console.log(
                    "Incoming:",
                    chat
                );

                // Do not notify the sender about their own message.
                if (
                    Number(chat.sender_id) !==
                    Number(this.currentUser)
                ) {

                    this.playIncomingSound();
                    this.showIncomingMessageToast(chat);

                    const senderId =
                        Number(chat.sender_id);

                    // If this conversation is currently open,
                    // the backend marks incoming messages as seen.
                    if (
                        Number(this.receiver) !==
                        senderId
                    ) {

                        this.updateSidebarUnread(
                            senderId,
                            chat.message ||
                            (
                                chat.file_name
                                    ? "📎 Attachment"
                                    : "New message"
                            )
                        );

                    }

                }

                this.append(chat);

            }
        );


        this.socket.on(
            "message_updated",
            chat => {

                console.log(
                    "Updated:",
                    chat
                );

                this.update(chat);

            }
        );

    }


    // =====================================================
    // SIDEBAR UNREAD COUNTS
    // =====================================================

    updateSidebarUnread(senderId, message) {

        const id = String(senderId);

        const userItem =
            document.querySelector(
                `.user-item[data-user-id="${CSS.escape(id)}"]`
            );

        if (!userItem) {
            return;
        }

        let badge =
            userItem.querySelector(
                ".chat-unread-badge"
            );

        let count = 0;

        if (badge) {
            count = parseInt(badge.textContent, 10) || 0;
        }

        count += 1;

        if (!badge) {

            badge =
                document.createElement("span");

            badge.className =
                "chat-unread-badge";

            badge.dataset.userId = id;

            const info =
                userItem.querySelector(
                    ".flex-1.min-w-0"
                );

            const header =
                info?.querySelector(
                    ".flex.items-center.justify-between"
                );

            if (header) {

                let actions =
                    header.querySelector(
                        ".flex.items-center.gap-2"
                    );

                if (!actions) {

                    actions =
                        document.createElement("div");

                    actions.className =
                        "flex items-center gap-2 flex-shrink-0";

                    header.appendChild(actions);

                }

                actions.prepend(badge);
            }
        }

        badge.textContent =
            count > 99 ? "99+" : String(count);

        userItem.classList.add(
            "has-unread"
        );

        const preview =
            userItem.querySelector(
                ".chat-user-preview"
            );

        if (preview) {

            preview.textContent =
                message || "New message";

            preview.classList.remove(
                "text-gray-400"
            );

            preview.classList.add(
                "text-gray-600",
                "font-semibold"
            );
        }

        // WhatsApp-style: conversation jumps to the top.
        const usersList =
            document.getElementById("users-list");

        if (usersList) {
            usersList.prepend(userItem);
        }
    }


    clearSidebarUnread(userId) {

        const id = String(userId);

        const userItem =
            document.querySelector(
                `.user-item[data-user-id="${CSS.escape(id)}"]`
            );

        if (!userItem) {
            return;
        }

        const badge =
            userItem.querySelector(
                ".chat-unread-badge"
            );

        if (badge) {
            badge.remove();
        }

        userItem.classList.remove(
            "has-unread"
        );

        const preview =
            userItem.querySelector(
                ".chat-user-preview"
            );

        if (preview) {

            preview.classList.remove(
                "text-gray-600",
                "font-semibold"
            );

            preview.classList.add(
                "text-gray-400"
            );
        }
    }


    updateChatHeader(userName) {

        const title =
            document.getElementById("chatReceiverName");

        if (title) {
            title.textContent =
                userName || "Chat";
        }
    }


    // =====================================================
    // INSTANT CONVERSATION SWITCHING
    // =====================================================

    async switchConversation(userId, userName, userLink = null) {

        const id = Number(userId);

        if (!id || id === Number(this.currentUser)) {
            return;
        }

        if (Number(this.receiver) === id) {
            this.highlightCurrentUser();
            return;
        }

        const oldReceiver = this.receiver;

        // Remove active state immediately.
        document
            .querySelectorAll(".user-item")
            .forEach(item => {
                item.classList.remove("active");
            });

        if (userLink) {
            userLink.classList.add("active");
        }

        // Update receiver without reloading the page.
        this.receiver = id;
        window.RECEIVER_ID = id;

        // Update URL without navigation.
        window.history.pushState(
            {
                receiver: id
            },
            "",
            `/messages/${id}`
        );

        // Update the selected user's name immediately.
        this.updateChatHeader(userName);

        // Reset status while loading.
        this.setStatus(
            "Loading...",
            "text-gray-400"
        );

        // Clear unread badge immediately.
        this.clearSidebarUnread(id);

        // Join the new Socket.IO conversation room.
        if (this.socket) {

            this.socket.emit(
                "join_chat",
                {
                    user_id: id
                }
            );

        }

        // Load only the messages — no full page reload.
        await this.loadMessages();

        // Keep the new conversation active.
        this.updateChatHeader(userName);
        this.highlightCurrentUser();

        // If loading failed, restore the previous receiver.
        // loadMessages already displays its error state.
        if (!this.chatBox) {
            this.receiver = oldReceiver;
            window.RECEIVER_ID = oldReceiver;
        }
    }


    updateOwnMessageSidebar(message) {

        const userItem =
            document.querySelector(
                `.user-item[data-user-id="${CSS.escape(String(this.receiver))}"]`
            );

        if (!userItem) {
            return;
        }

        // Show the latest message preview.
        const preview =
            userItem.querySelector(".chat-user-preview");

        if (preview) {

            preview.textContent =
                message || "Message sent";

            preview.classList.remove(
                "text-gray-600",
                "font-semibold"
            );

            preview.classList.add(
                "text-gray-400"
            );
        }

        // IMPORTANT:
        // Do NOT create or increase an unread badge for our own message.
        // The conversation is simply moved to the top because it is active.
        const usersList =
            document.getElementById("users-list");

        if (usersList) {
            usersList.prepend(userItem);
        }
    }


    // =====================================================
    // STATUS
    // =====================================================

    setStatus(text, color) {

        const status =
            document.getElementById(
                "chat-status"
            );

        if (!status) {
            return;
        }

        status.className =
            `text-sm font-medium ${color}`;

        status.textContent = text;

    }


    // =====================================================
    // LOAD MESSAGES
    // =====================================================

    async loadMessages() {

        if (
            !this.chatBox ||
            !this.receiver
        ) {
            return;
        }


        try {

            const response =
                await fetch(
                    `/get_messages/${encodeURIComponent(this.receiver)}`,
                    {
                        headers: {
                            "Accept": "application/json"
                        }
                    }
                );


            if (!response.ok) {

                throw new Error(
                    `Unable to load messages (${response.status})`
                );

            }


            const messages =
                await response.json();


            this.chatBox.innerHTML = "";

            this.messages.clear();


            messages.forEach(
                chat => {

                    this.append(
                        chat,
                        false
                    );

                }
            );


            this.scrollBottom(
                true,
                "auto"
            );


            this.setStatus(
                "Active",
                "text-green-500"
            );

            this.clearSidebarUnread(
                this.receiver
            );

        }

        catch (error) {

            console.error(
                "Load messages error:",
                error
            );


            this.chatBox.innerHTML = `

                <div class="flex h-full items-center justify-center p-6 text-center">

                    <div>

                        <div class="text-3xl mb-3">
                            ⚠️
                        </div>

                        <p class="font-semibold text-gray-700">
                            Unable to load messages
                        </p>

                        <p class="text-sm text-gray-400 mt-1">
                            Please refresh and try again.
                        </p>

                    </div>

                </div>

            `;


            this.setStatus(
                "Unable to connect",
                "text-red-500"
            );

        }

    }


    // =====================================================
    // SCROLL
    // =====================================================

    isNearBottom() {

        if (!this.chatBox) {
            return true;
        }


        return (
            this.chatBox.scrollHeight -
            this.chatBox.scrollTop -
            this.chatBox.clientHeight
        ) < 150;

    }


    scrollBottom(
        force = false,
        behavior = "smooth"
    ) {

        if (!this.chatBox) {
            return;
        }


        if (
            force ||
            this.isNearBottom()
        ) {

            this.chatBox.scrollTo({

                top:
                    this.chatBox.scrollHeight,

                behavior:
                    behavior

            });

        }

    }


    // =====================================================
    // ESCAPE HTML
    // =====================================================

    escapeHTML(value) {

        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");

    }


    // =====================================================
    // FILE HTML
    // =====================================================

    renderFile(chat) {

        if (!chat.file_path) {
            return "";
        }


        const filePath =
            this.escapeHTML(
                chat.file_path
            );


        const fileName =
            this.escapeHTML(
                chat.file_name ||
                "Attachment"
            );


        const image =
            /\.(jpg|jpeg|png|gif|webp)$/i
                .test(
                    chat.file_name || ""
                );


        if (image) {

            return `

                <a
                    href="${filePath}"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="block mt-3"
                >

                    <img
                        src="${filePath}"
                        alt="${fileName}"
                        loading="lazy"
                        class="max-w-[240px] max-h-[280px] object-cover rounded-2xl shadow-lg border border-white/20 hover:scale-[1.02] transition"
                    >

                </a>

            `;

        }


        return `

            <a
                href="${filePath}"
                target="_blank"
                rel="noopener noreferrer"
                class="flex items-center gap-3 mt-3 bg-gray-100 hover:bg-gray-200 rounded-2xl p-3 transition"
            >

                <div class="text-2xl">
                    📄
                </div>


                <div class="overflow-hidden min-w-0">

                    <div class="font-semibold truncate">
                        ${fileName}
                    </div>

                    <div class="text-xs text-gray-500">
                        Click to open
                    </div>

                </div>

            </a>

        `;

    }


    // =====================================================
    // MESSAGE TIME
    // =====================================================

    formatTime(value) {

        if (!value) {
            return "";
        }


        const date =
            value instanceof Date
                ? value
                : new Date(value);


        if (
            Number.isNaN(
                date.getTime()
            )
        ) {

            return "";

        }


        return new Intl.DateTimeFormat(
            [],
            {
                hour: "2-digit",
                minute: "2-digit"
            }
        ).format(date);

    }


    // =====================================================
    // RENDER MESSAGE
    // =====================================================

    render(chat) {

        const mine =
            Number(chat.sender_id) ===
            Number(this.currentUser);


        const deleted =
            Boolean(chat.deleted);


        let menu = "";


        if (
            mine &&
            !deleted
        ) {

            menu = `

                <div
                    class="absolute top-1 -left-11 message-menu-wrapper"
                >

                    <button
                        type="button"
                        onclick="toggleMenu(${Number(chat.id)})"
                        aria-label="Message options"
                        class="w-8 h-8 rounded-full bg-white text-gray-700 shadow border hover:bg-gray-100 transition"
                    >
                        ⋮
                    </button>


                    <div
                        id="menu-${Number(chat.id)}"
                        class="hidden absolute top-9 left-0 bg-white rounded-2xl shadow-xl border overflow-hidden z-50 min-w-[170px]"
                    >

                        <button
                            type="button"
                            onclick="editMessage(${Number(chat.id)})"
                            class="flex items-center gap-3 w-full px-4 py-3 hover:bg-gray-100 text-left"
                        >
                            ✏
                            <span>Edit</span>
                        </button>


                        <button
                            type="button"
                            onclick="copyMessage(${Number(chat.id)})"
                            class="flex items-center gap-3 w-full px-4 py-3 hover:bg-gray-100 text-left"
                        >
                            📋
                            <span>Copy</span>
                        </button>


                        <hr>


                        <button
                            type="button"
                            onclick="deleteMessage(${Number(chat.id)})"
                            class="flex items-center gap-3 w-full px-4 py-3 text-red-600 hover:bg-red-50 text-left"
                        >
                            🗑
                            <span>Delete</span>
                        </button>

                    </div>

                </div>

            `;

        }


        const messageText =
            deleted

                ? "<i class='opacity-70'>This message was deleted</i>"

                : this.escapeHTML(
                    chat.message || ""
                ).replace(
                    /\n/g,
                    "<br>"
                );


        const edited =
            chat.edited

                ? `

                    <div class="text-[10px] italic opacity-60 mt-1">
                        edited
                    </div>

                `

                : "";


        const time =
            this.formatTime(
                chat.created_at
            );


        const ticks =
            mine

                ? (
                    chat.seen

                        ? "<span class='text-cyan-300'>✔✔</span>"

                        : "<span>✔</span>"
                )

                : "";


        return `

            <div class="relative">

                ${menu}


                <div class="${
                    mine

                        ? "bg-gradient-to-r from-blue-600 to-indigo-600 text-white ml-auto"

                        : "bg-white border border-gray-200 text-gray-800"

                } px-4 md:px-5 py-3 rounded-3xl max-w-[85%] md:max-w-md shadow-sm">


                    <div class="break-words leading-relaxed">

                        ${messageText}

                        ${
                            deleted
                                ? ""
                                : this.renderFile(chat)
                        }

                    </div>


                    ${edited}


                    <div class="flex justify-end items-center gap-2 mt-2 text-[10px] opacity-70">

                        ${time}

                        ${ticks}

                    </div>

                </div>

            </div>

        `;

    }


    // =====================================================
    // APPEND MESSAGE
    // =====================================================

    append(
        chat,
        scroll = true
    ) {

        if (
            !chat ||
            chat.id === undefined ||
            chat.id === null
        ) {

            return;

        }


        if (
            this.messages.has(
                chat.id
            )
        ) {

            return;

        }


        const shouldScroll =
            this.isNearBottom();


        this.messages.set(
            chat.id,
            chat
        );


        const wrapper =
            document.createElement(
                "div"
            );


        wrapper.id =
            "msg-" + chat.id;


        wrapper.className =
            Number(chat.sender_id) ===
            Number(this.currentUser)

                ? "flex justify-end mb-4"

                : "flex justify-start mb-4";


        wrapper.innerHTML =
            this.render(chat);


        this.chatBox.appendChild(
            wrapper
        );


        if (
            scroll &&
            shouldScroll
        ) {

            this.scrollBottom(
                true
            );

        }

    }


    // =====================================================
    // UPDATE MESSAGE
    // =====================================================

    update(chat) {

        if (!chat) {
            return;
        }


        this.messages.set(
            chat.id,
            chat
        );


        const wrapper =
            document.getElementById(
                "msg-" + chat.id
            );


        if (!wrapper) {

            this.append(
                chat
            );

            return;

        }


        wrapper.innerHTML =
            this.render(chat);

    }


    // =====================================================
    // SEND MESSAGE
    // =====================================================

    async send() {

        if (
            this.isSending ||
            !this.form
        ) {

            return;

        }


        const message =
            (
                this.messageInput?.value ||
                ""
            ).trim();


        const hasFile =
            Boolean(
                this.fileInput?.files?.length
            );


        if (
            !message &&
            !hasFile
        ) {

            return;

        }


        const sendButton =
            this.form.querySelector(
                "button[type='submit']"
            );


        const originalButtonHTML =
            sendButton
                ? sendButton.innerHTML
                : "";


        this.isSending = true;


        if (sendButton) {

            sendButton.disabled = true;

            sendButton.innerHTML =
                `<i class="fas fa-spinner fa-spin"></i>`;

            sendButton.classList.add(
                "opacity-70"
            );

        }


        try {

            const formData =
                new FormData(
                    this.form
                );


            const response =
                await fetch(
                    `/messages/${encodeURIComponent(this.receiver)}`,
                    {
                        method: "POST",
                        body: formData,
                        headers: {
                            "Accept": "application/json"
                        }
                    }
                );


            const contentType =
                response.headers.get(
                    "content-type"
                ) || "";


            if (
                !contentType.includes(
                    "application/json"
                )
            ) {

                const serverText =
                    await response.text();


                console.error(
                    "Unexpected server response:",
                    serverText
                );


                throw new Error(
                    "The server returned an unexpected response."
                );

            }


            const data =
                await response.json();


            if (
                !response.ok ||
                !data.success
            ) {

                throw new Error(
                    data.message ||
                    "Message could not be sent."
                );

            }


            this.messageInput.value = "";

            this.form.reset();

            this.hidePreview();

            // Our own message moves the conversation to the top,
            // but NEVER increments the unread count.
            this.updateOwnMessageSidebar(
                message || "📎 Attachment"
            );

            this.scrollBottom(
                true
            );

        }

        catch (error) {

            console.error(
                "Send message error:",
                error
            );


            this.showToast(
                error.message ||
                "Unable to send message."
            );

        }

        finally {

            this.isSending = false;


            if (sendButton) {

                sendButton.disabled = false;

                sendButton.innerHTML =
                    originalButtonHTML;

                sendButton.classList.remove(
                    "opacity-70"
                );

            }

        }

    }


    // =====================================================
    // FILE PREVIEW
    // =====================================================

    showPreview(file) {

        if (
            !file ||
            !this.previewContainer
        ) {

            return;

        }


        this.previewContainer.classList.remove(
            "hidden"
        );


        if (
            file.type.startsWith(
                "image/"
            )
        ) {

            this.previewImage?.classList.remove(
                "hidden"
            );

            this.previewFile?.classList.add(
                "hidden"
            );


            const reader =
                new FileReader();


            reader.onload =
                event => {

                    if (this.previewImage) {

                        this.previewImage.src =
                            event.target.result;

                    }

                };


            reader.readAsDataURL(
                file
            );

        }

        else {

            this.previewImage?.classList.add(
                "hidden"
            );

            this.previewFile?.classList.remove(
                "hidden"
            );


            if (this.previewFile) {

                this.previewFile.innerHTML = `

                    📎 <strong>
                        ${this.escapeHTML(file.name)}
                    </strong>

                    <br>

                    <span class="text-xs text-gray-500">
                        ${(file.size / 1024).toFixed(1)} KB
                    </span>

                `;

            }

        }

    }


    hidePreview() {

        if (this.fileInput) {

            this.fileInput.value = "";

        }


        this.previewContainer?.classList.add(
            "hidden"
        );

        this.previewImage?.classList.add(
            "hidden"
        );

        this.previewFile?.classList.add(
            "hidden"
        );


        if (this.previewImage) {

            this.previewImage.src = "";

        }


        if (this.previewFile) {

            this.previewFile.innerHTML = "";

        }

    }


    // =====================================================
    // EMOJI
    // =====================================================

    toggleEmoji() {

        this.emojiPicker?.classList.toggle(
            "hidden"
        );

    }


    insertEmoji(emoji) {

        if (!this.messageInput) {
            return;
        }


        const start =
            this.messageInput.selectionStart ??
            this.messageInput.value.length;


        const end =
            this.messageInput.selectionEnd ??
            this.messageInput.value.length;


        this.messageInput.value =

            this.messageInput.value.slice(
                0,
                start
            ) +

            emoji +

            this.messageInput.value.slice(
                end
            );


        this.messageInput.focus();


        const cursor =
            start +
            emoji.length;


        this.messageInput.setSelectionRange(
            cursor,
            cursor
        );


        this.emojiPicker?.classList.add(
            "hidden"
        );

    }


    // =====================================================
    // SIDEBAR
    // =====================================================

    openSidebar() {

        if (!this.sidebar) {
            return;
        }


        this.sidebar.classList.remove(
            "-translate-x-full"
        );


        this.sidebar.classList.add(
            "translate-x-0"
        );


        this.overlay?.classList.remove(
            "hidden"
        );


        this.menuBtn?.setAttribute(
            "aria-expanded",
            "true"
        );


        document.body.classList.add(
            "overflow-hidden"
        );

    }


    closeSidebar() {

        if (!this.sidebar) {
            return;
        }


        if (
            window.innerWidth >= 768
        ) {

            return;

        }


        this.sidebar.classList.remove(
            "translate-x-0"
        );


        this.sidebar.classList.add(
            "-translate-x-full"
        );


        this.overlay?.classList.add(
            "hidden"
        );


        this.menuBtn?.setAttribute(
            "aria-expanded",
            "false"
        );


        document.body.classList.remove(
            "overflow-hidden"
        );

    }


    // =====================================================
    // SEARCH USERS
    // =====================================================

    searchUsers(text) {

        const query =
            String(text || "")
                .trim()
                .toLowerCase();


        const users =
            Array.from(
                document.querySelectorAll(
                    ".user-item"
                )
            );


        let visible = 0;


        users.forEach(
            user => {

                const name =
                    (
                        user.dataset.userName ||
                        ""
                    ).toLowerCase();


                const email =
                    (
                        user.dataset.userEmail ||
                        ""
                    ).toLowerCase();


                const content =
                    user.innerText.toLowerCase();


                const match =
                    !query ||
                    name.includes(query) ||
                    email.includes(query) ||
                    content.includes(query);


                user.classList.toggle(
                    "hidden",
                    !match
                );


                if (match) {

                    visible++;

                }

            }
        );


        this.noUsersFound?.classList.toggle(
            "hidden",
            visible !== 0
        );

    }


    // =====================================================
    // ACTIVE USER
    // =====================================================

    highlightCurrentUser() {

        const currentPath =
            window.location.pathname;


        document
            .querySelectorAll(
                ".user-item"
            )
            .forEach(
                item => {

                    const href =
                        item.getAttribute(
                            "href"
                        );


                    item.classList.toggle(
                        "active",
                        href === currentPath
                    );

                }
            );

    }


    // =====================================================
    // TOAST
    // =====================================================

    showToast(message) {

        let toast =
            document.getElementById(
                "salty-toast"
            );


        if (!toast) {

            toast =
                document.createElement(
                    "div"
                );


            toast.id =
                "salty-toast";


            toast.className = `

                fixed

                left-1/2

                -translate-x-1/2

                bottom-6

                z-[100]

                max-w-[90vw]

                rounded-2xl

                bg-gray-900

                text-white

                px-5

                py-3

                text-sm

                shadow-2xl

            `;


            document.body.appendChild(
                toast
            );

        }


        toast.textContent =
            message;


        toast.classList.remove(
            "hidden"
        );


        clearTimeout(
            this.toastTimer
        );


        this.toastTimer =
            setTimeout(
                () => {

                    toast.classList.add(
                        "hidden"
                    );

                },
                3000
            );

    }


    // =====================================================
    // EVENTS
    // =====================================================

    initConversationNavigation() {

        const usersList =
            document.getElementById("users-list");

        if (!usersList) {
            return;
        }

        usersList.addEventListener(
            "click",
            async event => {

                const link =
                    event.target.closest(
                        ".user-item"
                    );

                if (!link) {
                    return;
                }

                // Let Ctrl/Cmd-click and middle-click behave normally.
                if (
                    event.ctrlKey ||
                    event.metaKey ||
                    event.shiftKey ||
                    event.altKey ||
                    event.button === 1
                ) {
                    return;
                }

                event.preventDefault();

                const userId =
                    link.dataset.userId ||
                    link.getAttribute("href")
                        ?.split("/")
                        .pop();

                const userName =
                    link.dataset.userName ||
                    link.querySelector(
                        "p.font-semibold"
                    )?.textContent.trim();

                link.classList.add("switching");

                try {

                    await this.switchConversation(
                        userId,
                        userName,
                        link
                    );

                } catch (error) {

                    console.error(
                        "Conversation switch error:",
                        error
                    );

                    // If something genuinely fails,
                    // allow the normal URL to recover.
                    window.location.href =
                        link.getAttribute("href");

                } finally {

                    link.classList.remove(
                        "switching"
                    );

                }
            }
        );
    }


    initEvents() {

        // Browser autoplay policy: unlock sound after first user interaction.
        document.addEventListener(
            "click",
            () => this.unlockNotificationSound(),
            { once: true }
        );

        document.addEventListener(
            "keydown",
            () => this.unlockNotificationSound(),
            { once: true }
        );

        // SEND

        this.form?.addEventListener(
            "submit",
            event => {

                event.preventDefault();

                this.send();

            }
        );


        // ENTER

        this.messageInput?.addEventListener(
            "keydown",
            event => {

                if (
                    event.key === "Enter" &&
                    !event.shiftKey
                ) {

                    event.preventDefault();

                    this.send();

                }

            }
        );


        // FILE

        this.fileInput?.addEventListener(
            "change",
            event => {

                this.showPreview(
                    event.target.files?.[0]
                );

            }
        );


        // REMOVE FILE

        this.removePreview?.addEventListener(
            "click",
            () => {

                this.hidePreview();

            }
        );


        // EMOJI

        this.emojiBtn?.addEventListener(
            "click",
            event => {

                event.stopPropagation();

                this.toggleEmoji();

            }
        );


        document
            .querySelectorAll(
                ".emoji"
            )
            .forEach(
                item => {

                    item.addEventListener(
                        "click",
                        () => {

                            this.insertEmoji(
                                item.innerText
                            );

                        }
                    );

                }
            );


        // SEARCH

        this.searchInput?.addEventListener(
            "input",
            event => {

                this.searchUsers(
                    event.target.value
                );

            }
        );


        // CTRL + K SEARCH

        document.addEventListener(
            "keydown",
            event => {

                if (
                    (event.ctrlKey ||
                     event.metaKey) &&
                    event.key.toLowerCase() === "k"
                ) {

                    event.preventDefault();

                    this.searchInput?.focus();

                    this.searchInput?.select();

                }

            }
        );


        // MOBILE SIDEBAR

        this.menuBtn?.addEventListener(
            "click",
            event => {

                event.preventDefault();

                this.openSidebar();

            }
        );


        this.overlay?.addEventListener(
            "click",
            () => {

                this.closeSidebar();

            }
        );


        // ESCAPE

        document.addEventListener(
            "keydown",
            event => {

                if (
                    event.key === "Escape" &&
                    window.innerWidth < 768
                ) {

                    this.closeSidebar();

                }

            }
        );


        // CLOSE EMOJI

        document.addEventListener(
            "click",
            event => {

                if (
                    !event.target.closest(
                        "#emoji-picker"
                    ) &&
                    !event.target.closest(
                        "#emoji-btn"
                    )
                ) {

                    this.emojiPicker?.classList.add(
                        "hidden"
                    );

                }

            }
        );


        // CLOSE MESSAGE MENUS

        document.addEventListener(
            "click",
            event => {

                if (
                    !event.target.closest(
                        ".message-menu-wrapper"
                    )
                ) {

                    document
                        .querySelectorAll(
                            "[id^='menu-']"
                        )
                        .forEach(
                            menu => {

                                menu.classList.add(
                                    "hidden"
                                );

                            }
                        );

                }

            }
        );


        // CLOSE SIDEBAR AFTER USER SELECTION

        document
            .getElementById(
                "users-list"
            )
            ?.addEventListener(
                "click",
                event => {

                    const link =
                        event.target.closest(
                            ".user-item"
                        );


                    if (link) {

                        this.closeSidebar();

                    }

                }
            );


        // RESIZE

        window.addEventListener(
            "resize",
            () => {

                if (
                    window.innerWidth >= 768
                ) {

                    this.overlay?.classList.add(
                        "hidden"
                    );


                    document.body.classList.remove(
                        "overflow-hidden"
                    );


                    this.sidebar?.classList.remove(
                        "-translate-x-full"
                    );


                    this.sidebar?.classList.add(
                        "translate-x-0"
                    );

                }

            }
        );

    }


    // =====================================================
    // TOGGLE MESSAGE MENU
    // =====================================================

    toggleMenu(messageId) {

        document
            .querySelectorAll(
                "[id^='menu-']"
            )
            .forEach(
                menu => {

                    if (
                        menu.id !==
                        `menu-${messageId}`
                    ) {

                        menu.classList.add(
                            "hidden"
                        );

                    }

                }
            );


        const menu =
            document.getElementById(
                `menu-${messageId}`
            );


        if (menu) {

            menu.classList.toggle(
                "hidden"
            );

        }

    }


    // =====================================================
    // EDIT MESSAGE
    // =====================================================

    async editMessage(messageId) {

        const chat =
            this.messages.get(
                messageId
            );


        if (!chat) {
            return;
        }


        const newMessage =
            prompt(
                "Edit message",
                chat.message || ""
            );


        if (
            newMessage === null
        ) {

            return;

        }


        if (
            !newMessage.trim()
        ) {

            this.showToast(
                "Message cannot be empty."
            );

            return;

        }


        const formData =
            new FormData();


        formData.append(
            "message",
            newMessage.trim()
        );


        try {

            const response =
                await fetch(
                    `/edit_message/${encodeURIComponent(messageId)}`,
                    {
                        method: "POST",
                        body: formData,
                        headers: {
                            "Accept": "application/json"
                        }
                    }
                );


            const data =
                await this.readJSON(
                    response
                );


            if (
                !response.ok ||
                !data.success
            ) {

                throw new Error(
                    data.message ||
                    "Unable to edit message."
                );

            }


            this.update(
                data.message
            );

        }

        catch (error) {

            console.error(
                "Edit message error:",
                error
            );


            this.showToast(
                error.message ||
                "Unable to edit message."
            );

        }

    }


    // =====================================================
    // DELETE MESSAGE
    // =====================================================

    async deleteMessage(messageId) {

        if (
            !confirm(
                "Delete this message?"
            )
        ) {

            return;

        }


        try {

            const response =
                await fetch(
                    `/delete_message/${encodeURIComponent(messageId)}`,
                    {
                        method: "POST",
                        headers: {
                            "Accept": "application/json"
                        }
                    }
                );


            const data =
                await this.readJSON(
                    response
                );


            if (
                !response.ok ||
                !data.success
            ) {

                throw new Error(
                    data.message ||
                    "Unable to delete message."
                );

            }


            this.update(
                data.message
            );

        }

        catch (error) {

            console.error(
                "Delete message error:",
                error
            );


            this.showToast(
                error.message ||
                "Unable to delete message."
            );

        }

    }


    // =====================================================
    // COPY MESSAGE
    // =====================================================

    async copyMessage(messageId) {

        const chat =
            this.messages.get(
                messageId
            );


        if (!chat) {
            return;
        }


        if (
            !chat.message
        ) {

            this.showToast(
                "There is no text to copy."
            );

            return;

        }


        try {

            await navigator.clipboard.writeText(
                chat.message
            );


            this.showToast(
                "Message copied."
            );

        }

        catch (error) {

            console.error(
                "Copy error:",
                error
            );


            this.showToast(
                "Unable to copy message."
            );

        }

    }

}


// =========================================================
// START CHAT
// =========================================================

document.addEventListener(
    "DOMContentLoaded",
    () => {

        if (
            !window.RECEIVER_ID
        ) {

            return;

        }


        window.chat =
            new ChatApp();

    }
);


// =========================================================
// GLOBAL FUNCTIONS
// =========================================================

window.toggleMenu =
    function(id) {

        window.chat?.toggleMenu(
            id
        );

    };


window.editMessage =
    function(id) {

        window.chat?.editMessage(
            id
        );

    };


window.deleteMessage =
    function(id) {

        window.chat?.deleteMessage(
            id
        );

    };


window.copyMessage =
    function(id) {

        window.chat?.copyMessage(
            id
        );

    };

// =========================================================
// BROWSER BACK / FORWARD
// =========================================================

window.addEventListener(
    "popstate",
    function () {

        if (!window.chat) {
            return;
        }

        const match =
            window.location.pathname.match(
                /^\/messages\/(\d+)/
            );

        if (!match) {
            return;
        }

        const id = Number(match[1]);

        const link =
            document.querySelector(
                `.user-item[data-user-id="${CSS.escape(String(id))}"]`
            );

        const name =
            link?.dataset.userName ||
            link?.querySelector(
                "p.font-semibold"
            )?.textContent.trim() ||
            "Chat";

        window.chat.switchConversation(
            id,
            name,
            link
        );

    }
);
