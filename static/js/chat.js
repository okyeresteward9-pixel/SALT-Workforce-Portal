/* SALT Workforce Portal - Current Chat JS updated for Cloudinary attachments */
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

        this.notificationSound = document.getElementById("chatNotificationSound");
        this.chatToastContainer = document.getElementById("chatToastContainer");
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

            if (this.receiver) {

                this.socket.emit(
                    "join_chat",
                    {
                        user_id: this.receiver
                    }
                );

            }

            this.setStatus(
                "Active",
                "text-green-500"
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

                const isMine =
                    Number(chat.sender_id) ===
                    Number(this.currentUser);

                /*
                 * The message is relevant to the currently open
                 * conversation only when the other user's ID matches
                 * the open receiver. Otherwise it belongs in the
                 * sidebar/unread system.
                 */
                const otherUserId = isMine
                    ? Number(chat.receiver_id)
                    : Number(chat.sender_id);

                const isOpenConversation =
                    this.receiver &&
                    Number(this.receiver) === otherUserId;

                /*
                 * Sender and receiver both see an open conversation
                 * update instantly. Messages for other conversations
                 * must NEVER be appended to the currently open chat.
                 */
                if (
                    isOpenConversation &&
                    this.chatBox
                ) {

                    this.append(chat);
                    this.scrollBottom(true);

                }

                /*
                 * Always update the conversation list. The helper
                 * moves the conversation to the top and increments
                 * unread only when the conversation is not open.
                 */
                this.updateChatListItem(
                    chat,
                    {
                        unread:
                            !isMine &&
                            !isOpenConversation
                    }
                );

                /*
                 * Only notify the receiver. If the conversation is
                 * currently open, still notify them as requested.
                 */
                if (!isMine) {

                    this.playChatNotificationSound();
                    this.showChatToast(chat);

                }

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
    // CHAT NOTIFICATION SOUND + TOAST
    // =====================================================

    unlockChatNotificationSound() {
        if (this.soundUnlocked || !this.notificationSound) return;

        this.notificationSound.volume = 0;
        const promise = this.notificationSound.play();

        if (promise !== undefined) {
            promise.then(() => {
                this.notificationSound.pause();
                this.notificationSound.currentTime = 0;
                this.notificationSound.volume = 1;
                this.soundUnlocked = true;
            }).catch(() => {
                this.notificationSound.volume = 1;
            });
        }
    }

    playChatNotificationSound() {
        if (!this.notificationSound) return;

        this.notificationSound.currentTime = 0;
        this.notificationSound.volume = 1;

        this.notificationSound.play().catch(error => {
            console.log("Chat notification sound blocked:", error);
        });
    }

    escapeToastHTML(value) {
        const div = document.createElement("div");
        div.textContent = value || "";
        return div.innerHTML;
    }

    removeChatToast(toast) {
        if (!toast || !toast.isConnected) return;

        toast.classList.add("chat-toast-removing");

        setTimeout(() => {
            if (toast.isConnected) toast.remove();
        }, 250);
    }

    showChatToast(chat) {
        if (!this.chatToastContainer) return;

        const senderItem =
            this.getUserItem(chat.sender_id);

        const senderName =
            chat.sender_name ||
            senderItem?.querySelector(".flex-1.min-w-0 p.font-semibold")?.textContent?.trim() ||
            senderItem?.querySelector(".flex-1.min-w-0 p")?.textContent?.trim() ||
            "New message";

        const message =
            chat.message ||
            (chat.file_name ? "Sent an attachment" : "You received a new message");

        const toast = document.createElement("div");
        toast.className = "chat-notification-toast";

        toast.innerHTML = `
            <div class="chat-notification-icon">
                <i class="fas fa-comment-dots"></i>
            </div>

            <div class="chat-notification-content">
                <div class="chat-notification-title">
                    ${this.escapeToastHTML(senderName)}
                </div>

                <div class="chat-notification-message">
                    ${this.escapeToastHTML(message)}
                </div>
            </div>

            <button type="button"
                    class="chat-notification-close"
                    aria-label="Close">
                <i class="fas fa-times"></i>
            </button>
        `;

        this.chatToastContainer.prepend(toast);

        toast.querySelector(".chat-notification-close")?.addEventListener(
            "click",
            () => this.removeChatToast(toast)
        );

        setTimeout(() => this.removeChatToast(toast), 6000);
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

        if (!this.chatBox || !this.receiver) {
            return;
        }

        try {

            const response = await fetch(
                `/get_messages/${encodeURIComponent(this.receiver)}`,
                {
                    headers: {
                        "Accept": "application/json"
                    },
                    cache: "no-store"
                }
            );

            if (!response.ok) {
                throw new Error(
                    `Unable to load messages (${response.status})`
                );
            }

            const serverMessages = await response.json();

            /*
             * IMPORTANT:
             * Socket.IO and HTTP can complete in either order.
             *
             * Take a snapshot of messages already received live,
             * then rebuild the display from the server history and
             * merge any live messages that were not in that history.
             */

            const liveMessages = new Map();

            this.messages.forEach((chat, id) => {
                liveMessages.set(String(id), chat);
            });

            /*
             * Rebuild the message state from PostgreSQL history.
             */
            this.chatBox.innerHTML = "";
            this.messages.clear();

            serverMessages.forEach(chat => {
                this.append(chat, false);
            });

            /*
             * Add messages received through Socket.IO while the
             * HTTP request was loading.
             *
             * append() performs another duplicate check.
             */
            liveMessages.forEach((chat, id) => {

                if (!this.messages.has(id)) {
                    this.append(chat, false);
                }

            });

            /*
             * Keep the conversation in chronological order after
             * merging live and server messages.
             */
            const allMessages = Array.from(
                this.messages.values()
            ).sort((a, b) => {

                const timeA =
                    new Date(a.created_at || 0).getTime();

                const timeB =
                    new Date(b.created_at || 0).getTime();

                if (timeA !== timeB) {
                    return timeA - timeB;
                }

                return Number(a.id) - Number(b.id);

            });

            this.chatBox.innerHTML = "";
            this.messages.clear();

            allMessages.forEach(chat => {
                this.append(chat, false);
            });

            this.scrollBottom(true, "auto");

            this.setStatus(
                "Active",
                "text-green-500"
            );

        }

        catch (error) {

            console.error(
                "Load messages error:",
                error
            );

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

        if (!chat || !chat.file_path) {
            return "";
        }

        const filePath = String(chat.file_path);
        const rawFileName =
            chat.file_name ||
            "Attachment";

        const fileName =
            this.escapeHTML(rawFileName);

        const lowerName =
            rawFileName.toLowerCase();

        /*
         * Determine the attachment type from the original filename.
         * This is deliberately done on the frontend as well as the
         * backend so older messages still render correctly.
         */
        const extensionMatch =
            lowerName.match(/\.([a-z0-9]+)$/);

        const extension =
            extensionMatch
                ? extensionMatch[1]
                : "";

        const imageExtensions = [
            "jpg", "jpeg", "png", "gif",
            "webp", "bmp", "svg"
        ];

        const videoExtensions = [
            "mp4", "webm", "mov", "m4v", "avi"
        ];

        const audioExtensions = [
            "mp3", "wav", "ogg", "m4a", "aac"
        ];

        const isImage =
            imageExtensions.includes(extension);

        const isPDF =
            extension === "pdf";

        const isVideo =
            videoExtensions.includes(extension);

        const isAudio =
            audioExtensions.includes(extension);

        /*
         * Keep the Cloudinary URL exactly as supplied by the backend.
         * Do NOT prepend "/" because file_path is now a full HTTPS URL.
         */
        const safeUrl =
            this.escapeHTML(filePath);

        /*
         * Images open in a new tab while remaining viewable inline.
         */
        if (isImage) {

            return `
                <a
                    href="${safeUrl}"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="block mt-3"
                    title="Open ${fileName}"
                >
                    <img
                        src="${safeUrl}"
                        alt="${fileName}"
                        loading="lazy"
                        class="max-w-[280px] max-h-[320px] object-contain rounded-2xl shadow-lg border border-white/20 hover:scale-[1.02] transition"
                    >
                </a>
            `;

        }

        /*
         * PDFs are browser-viewable, so open them in a new tab.
         * No download attribute is used.
         */
        if (isPDF) {

            return `
                <a
                    href="${safeUrl}"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="flex items-center gap-3 mt-3 bg-red-50 hover:bg-red-100 border border-red-100 rounded-2xl p-3 transition"
                    title="Open PDF"
                >
                    <div class="w-11 h-11 rounded-xl bg-red-100 text-red-600 flex items-center justify-center text-xl flex-shrink-0">
                        <i class="fas fa-file-pdf"></i>
                    </div>

                    <div class="overflow-hidden min-w-0">
                        <div class="font-semibold truncate">
                            ${fileName}
                        </div>

                        <div class="text-xs text-gray-500">
                            Open PDF
                        </div>
                    </div>

                    <i class="fas fa-external-link-alt text-gray-400 ml-auto"></i>
                </a>
            `;

        }

        /*
         * Videos and audio are rendered with native browser players.
         * This avoids forcing supported media to download.
         */
        if (isVideo) {

            return `
                <div class="mt-3 max-w-[320px]">
                    <video
                        controls
                        preload="metadata"
                        class="w-full rounded-2xl shadow-lg"
                    >
                        <source src="${safeUrl}">
                        Your browser cannot play this video.
                    </video>

                    <a
                        href="${safeUrl}"
                        target="_blank"
                        rel="noopener noreferrer"
                        class="mt-2 flex items-center gap-2 text-xs text-gray-500 hover:text-blue-600"
                    >
                        <i class="fas fa-external-link-alt"></i>
                        ${fileName}
                    </a>
                </div>
            `;

        }

        if (isAudio) {

            return `
                <div class="mt-3 rounded-2xl bg-gray-100 p-3">
                    <div class="flex items-center gap-2 mb-2">
                        <i class="fas fa-music text-blue-600"></i>
                        <span class="font-semibold truncate">
                            ${fileName}
                        </span>
                    </div>

                    <audio
                        controls
                        preload="metadata"
                        class="w-full"
                    >
                        <source src="${safeUrl}">
                        Your browser cannot play this audio.
                    </audio>
                </div>
            `;

        }

        /*
         * Office documents, ZIP files and other formats are represented
         * as downloadable files. The original filename/extension is
         * displayed exactly as received from the backend.
         *
         * No extension is changed by JavaScript.
         */
        let icon = "fa-file";
        let iconClass = "text-gray-600";
        let backgroundClass = "bg-gray-100 hover:bg-gray-200";

        if (
            ["doc", "docx", "odt", "rtf"].includes(extension)
        ) {
            icon = "fa-file-word";
            iconClass = "text-blue-600";
            backgroundClass = "bg-blue-50 hover:bg-blue-100";
        }
        else if (
            ["xls", "xlsx", "csv", "ods"].includes(extension)
        ) {
            icon = "fa-file-excel";
            iconClass = "text-green-600";
            backgroundClass = "bg-green-50 hover:bg-green-100";
        }
        else if (
            ["ppt", "pptx", "odp"].includes(extension)
        ) {
            icon = "fa-file-powerpoint";
            iconClass = "text-orange-600";
            backgroundClass = "bg-orange-50 hover:bg-orange-100";
        }
        else if (
            ["zip", "rar", "7z", "tar", "gz"].includes(extension)
        ) {
            icon = "fa-file-archive";
            iconClass = "text-amber-600";
            backgroundClass = "bg-amber-50 hover:bg-amber-100";
        }
        else if (
            ["txt", "md", "json", "xml"].includes(extension)
        ) {
            icon = "fa-file-lines";
            iconClass = "text-slate-600";
            backgroundClass = "bg-slate-50 hover:bg-slate-100";
        }

        return `
            <a
                href="${safeUrl}"
                target="_blank"
                rel="noopener noreferrer"
                download="${fileName}"
                class="flex items-center gap-3 mt-3 ${backgroundClass} rounded-2xl p-3 transition"
                title="Download ${fileName}"
            >
                <div class="w-11 h-11 rounded-xl bg-white flex items-center justify-center text-xl flex-shrink-0 shadow-sm">
                    <i class="fas ${icon} ${iconClass}"></i>
                </div>

                <div class="overflow-hidden min-w-0 flex-1">
                    <div class="font-semibold truncate">
                        ${fileName}
                    </div>

                    <div class="text-xs text-gray-500">
                        Download file
                    </div>
                </div>

                <i class="fas fa-download text-gray-400"></i>
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


        const messageId = String(chat.id);

        if (this.messages.has(messageId)) {
            return;
        }

        if (!this.chatBox) {
            console.error(
                "Cannot append message because #chat-box is missing.",
                chat
            );
            return;
        }

        const shouldScroll =
            this.isNearBottom();

        this.messages.set(
            messageId,
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


        const messageId = String(chat.id);

        this.messages.set(
            messageId,
            chat
        );

        const wrapper =
            document.getElementById(
                "msg-" + messageId
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
    // REAL-TIME CHAT LIST
    // =====================================================

    getUserItem(userId) {

        const targetId = String(userId);

        return Array.from(
            document.querySelectorAll(".user-item")
        ).find(item => {

            const href =
                item.getAttribute("href") || "";

            const match =
                href.match(/\/messages\/(\d+)(?:\/)?$/);

            return match &&
                String(match[1]) === targetId;

        }) || null;

    }


    getChatListTime(chat) {

        const formatted =
            this.formatTime(chat?.created_at);

        return formatted || "now";

    }


    getChatPreview(chat) {

        if (chat?.deleted) {
            return "This message was deleted";
        }

        if (chat?.file_name && !chat?.message) {
            return "📎 Attachment";
        }

        return (
            chat?.message ||
            (chat?.file_name
                ? "📎 Attachment"
                : "Start conversation...")
        );

    }


    getUnreadCount(item) {

        if (!item) {
            return 0;
        }

        const badge =
            item.querySelector(
                "[data-chat-unread]"
            );

        if (!badge) {
            return 0;
        }

        const count =
            Number.parseInt(
                badge.textContent,
                10
            );

        return Number.isFinite(count)
            ? count
            : 0;

    }


    setUnreadCount(item, count) {

        if (!item) {
            return;
        }

        const info =
            item.querySelector(
                ".flex-1.min-w-0"
            );

        if (!info) {
            return;
        }

        let badge =
            info.querySelector(
                "[data-chat-unread]"
            );

        if (count <= 0) {

            badge?.remove();
            return;

        }

        if (!badge) {

            badge =
                document.createElement("span");

            badge.dataset.chatUnread = "true";

            badge.className =
                "ml-2 min-w-[22px] h-[22px] px-1.5 rounded-full bg-blue-600 text-white text-[11px] font-bold flex items-center justify-center shadow-sm";

            const header =
                info.querySelector(
                    ".flex.items-center.justify-between"
                );

            if (header) {
                header.appendChild(badge);
            }
            else {
                info.appendChild(badge);
            }

        }

        badge.textContent =
            count > 99
                ? "99+"
                : String(count);

    }


    updateChatListItem(
        chat,
        options = {}
    ) {

        if (
            !chat ||
            chat.sender_id === undefined
        ) {
            return;
        }

        const isMine =
            Number(chat.sender_id) ===
            Number(this.currentUser);

        /*
         * Incoming message belongs to sender.
         * Outgoing message belongs to receiver.
         */
        const contactId =
            isMine
                ? String(chat.receiver_id)
                : String(chat.sender_id);

        const item =
            this.getUserItem(contactId);

        if (!item) {

            console.warn(
                "Chat user item not found:",
                senderId
            );

            return;

        }

        const info =
            item.querySelector(
                ".flex-1.min-w-0"
            );

        if (!info) {
            return;
        }

        const header =
            info.querySelector(
                ".flex.items-center.justify-between"
            );

        const name =
            header?.querySelector("p");

        const time =
            header?.querySelector("span");

        const preview =
            info.querySelector(
                "p.text-sm"
            );

        if (preview) {

            let latestText =
                this.getChatPreview(chat);

            if (isMine && latestText) {
                latestText =
                    `You: ${latestText}`;
            }

            preview.textContent =
                latestText;

            preview.classList.remove(
                "text-gray-400"
            );

            preview.classList.add(
                "text-gray-600"
            );

        }

        if (time) {

            time.textContent =
                this.getChatListTime(chat);

            time.classList.remove(
                "text-gray-300"
            );

            time.classList.add(
                "text-gray-500"
            );

        }

        const shouldUnread =
            options.unread === true;

        if (shouldUnread) {

            const count =
                this.getUnreadCount(item);

            this.setUnreadCount(
                item,
                count + 1
            );

            if (name) {

                name.classList.remove(
                    "text-gray-800"
                );

                name.classList.add(
                    "text-blue-700"
                );

            }

        }
        else {

            this.setUnreadCount(
                item,
                0
            );

        }

        /*
         * Move the conversation to the top without reloading.
         * Keep the search "no results" node and any other non-user
         * elements in place.
         */
        const usersList =
            document.getElementById(
                "users-list"
            );

        if (usersList) {

            usersList.prepend(item);

        }

        /*
         * Re-apply the active class after moving the item.
         */
        this.highlightCurrentUser();

    }


    clearUnreadForUser(userId) {

        const item =
            this.getUserItem(userId);

        if (!item) {
            return;
        }

        this.setUnreadCount(
            item,
            0
        );

        const name =
            item.querySelector(
                ".flex.items-center.justify-between p"
            );

        name?.classList.remove(
            "text-blue-700"
        );

        name?.classList.add(
            "text-gray-800"
        );

    }


    // =====================================================
    // REAL-TIME CONVERSATION LIST
    // =====================================================

    updateConversationList(chat, incrementUnread = false) {

        if (!chat) {
            return;
        }

        const isMine =
            Number(chat.sender_id) ===
            Number(this.currentUser);

        const userId =
            isMine
                ? Number(chat.receiver_id)
                : Number(chat.sender_id);

        if (!userId) {
            return;
        }

        const item =
            document.querySelector(
                `.user-item[data-user-id="${userId}"]`
            );

        if (!item) {
            return;
        }

        const preview =
            item.querySelector(".user-preview");

        const time =
            item.querySelector(".user-time");

        const badge =
            item.querySelector(".user-unread-badge");

        if (preview) {

            preview.textContent =
                chat.deleted
                    ? "Message deleted"
                    : (
                        chat.message ||
                        (
                            chat.file_name
                                ? "Sent an attachment"
                                : "New message"
                        )
                    );

        }

        if (time) {

            time.textContent =
                this.formatTime(chat.created_at) ||
                "now";

        }

        /*
         * Move the conversation to the top without reloading.
         */
        const list =
            document.getElementById("users-list");

        if (list) {
            list.prepend(item);
        }

        /*
         * Unread messages are counted only for incoming messages
         * whose conversation is not currently open.
         */
        if (incrementUnread && badge) {

            const current =
                Number(
                    badge.dataset.unreadCount ||
                    badge.textContent ||
                    0
                );

            const next =
                current + 1;

            badge.dataset.unreadCount =
                String(next);

            badge.textContent =
                next > 99
                    ? "99+"
                    : String(next);

            badge.classList.remove("hidden");
            badge.classList.add("inline-flex");

            item.classList.add("has-unread");

        }

        /*
         * If this conversation is open, clear its unread state.
         */
        if (
            this.receiver &&
            Number(this.receiver) === userId
        ) {

            this.clearConversationUnread(item);

        }

    }


    clearConversationUnread(item) {

        if (!item) {
            return;
        }

        const badge =
            item.querySelector(".user-unread-badge");

        if (badge) {

            badge.dataset.unreadCount = "0";
            badge.textContent = "0";
            badge.classList.add("hidden");
            badge.classList.remove("inline-flex");

        }

        item.classList.remove("has-unread");

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

    initEvents() {

        const unlockSound = () => this.unlockChatNotificationSound();

        document.addEventListener("click", unlockSound, { once: true, passive: true });
        document.addEventListener("keydown", unlockSound, { once: true, passive: true });

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

                        const href =
                            link.getAttribute("href") || "";

                        const match =
                            href.match(/\/messages\/(\d+)(?:\/)?$/);

                        if (match) {

                            this.clearUnreadForUser(
                                match[1]
                            );

                        }

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
        window.chat = new ChatApp();
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