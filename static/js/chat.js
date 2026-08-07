class ChatApp {

    constructor() {

        // -----------------------------
        // ELEMENTS
        // -----------------------------

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

        // -----------------------------
        // USER
        // -----------------------------

        this.currentUser =
            window.CURRENT_USER;

        this.receiver =
            window.RECEIVER_ID;

        // -----------------------------
        // STORAGE
        // -----------------------------

        this.messages = new Map();

        // -----------------------------
        // SOCKET
        // -----------------------------

        this.socket = io();

        this.init();

    }

    // =====================================
    // INITIALIZE
    // =====================================

    init() {

        this.initSocket();

        this.initEvents();

        this.loadMessages();

    }

    // =====================================
    // SOCKET
    // =====================================

    initSocket() {

        this.socket.on("connect", () => {

            console.log("Connected:", this.socket.id);

            this.socket.emit("join_chat", {

                user_id: this.receiver

            });

        });

        // this.socket.emit("online");
        
        this.socket.on(

            "user_online",
        
            data=>{
        
                if(
        
                    data.user_id ==
        
                    this.receiver
        
                ){
        
                    this.setStatus(
        
                        "🟢 Online",
        
                        "text-green-500"
        
                    );
        
                }
        
            }
        
        );

        this.socket.on(

            "user_offline",
        
            data=>{
        
                if(
        
                    data.user_id ==
        
                    this.receiver
        
                ){
        
                    this.setStatus(
        
                        "Last seen just now",
        
                        "text-gray-500"
        
                    );
        
                }
        
            }
        
        );

        this.socket.on("new_message", (chat) => {

            console.log("Incoming:", chat);

            this.append(chat);

        });

        this.socket.on("message_updated", (chat) => {

            console.log("Updated:", chat);

            this.update(chat);

        });

    }


    setStatus(text,color){

        const status =
    
            document.getElementById(
    
                "chat-status"
    
            );
    
        if(!status) return;
    
        status.className =
    
            `text-sm font-medium ${color}`;
    
        status.innerHTML = text;
    
    }
    // =====================================
    // LOAD ALL MESSAGES
    // =====================================

    async loadMessages() {

        try{

            const response =
                await fetch(`/get_messages/${this.receiver}`);

            const messages =
                await response.json();

            this.chatBox.innerHTML = "";

            this.messages.clear();

            messages.forEach(chat => {

                this.append(chat);

            });

            this.scrollBottom(true);

        }

        catch(error){

            console.error(error);

        }

    }

    // =====================================
    // SCROLL
    // =====================================

    scrollBottom(force=false){

        const nearBottom =

            this.chatBox.scrollHeight -

            this.chatBox.scrollTop -

            this.chatBox.clientHeight < 150;

        if(force || nearBottom){

            this.chatBox.scrollTop =

                this.chatBox.scrollHeight;

        }

    }

    // =====================================
    // FILE HTML
    // =====================================

    renderFile(chat){

        if(!chat.file_path){
    
            return "";
    
        }
    
        const image =
            /\.(jpg|jpeg|png|gif|webp)$/i
            .test(chat.file_name || "");
    
        if(image){
    
            return `
    
            <a href="/${chat.file_path}"
               target="_blank">
    
                <img
    
                    src="/${chat.file_path}"
    
                    class="mt-3 rounded-2xl max-w-[240px] shadow-lg hover:scale-[1.02] transition">
    
            </a>
    
            `;
    
        }
    
        return `
    
        <a
            href="/${chat.file_path}"
            target="_blank"
            class="flex items-center gap-3 mt-3 bg-gray-100 hover:bg-gray-200 rounded-2xl p-3">
    
            <div class="text-3xl">
    
                📄
    
            </div>
    
            <div class="overflow-hidden">
    
                <div class="font-semibold truncate">
    
                    ${chat.file_name}
    
                </div>
    
                <div class="text-xs text-gray-500">
    
                    Click to download
    
                </div>
    
            </div>
    
        </a>
    
        `;
    
    }

    // =====================================
    // RENDER MESSAGE
    // =====================================

    render(chat){

        const mine =
            chat.sender_id == this.currentUser;
    
        const safeMessage =
            (chat.message || "")
            .replace(/'/g,"\\'")
            .replace(/"/g,"&quot;");
    
        let menu = "";
    
        if(mine && !chat.deleted){
    
            menu = `
    
            <div class="absolute top-2 -left-12">
    
                <button
                    onclick="toggleMenu(${chat.id})"
                    class="w-8 h-8 rounded-full bg-white text-gray-700 shadow border hover:bg-gray-100 transition">
    
                    ⋮
    
                </button>
    
                <div
                    id="menu-${chat.id}"
                    class="hidden absolute top-10 left-0 bg-white rounded-2xl shadow-xl border overflow-hidden z-50 min-w-[180px]">
    
                    <button
                        onclick="editMessage(${chat.id})"
                        class="flex items-center gap-3 w-full px-4 py-3 hover:bg-gray-100">
    
                        ✏
                        <span>Edit</span>
    
                    </button>
    
                    <button
                        onclick="copyMessage(${chat.id})"
                        class="flex items-center gap-3 w-full px-4 py-3 hover:bg-gray-100">
    
                        📋
                        <span>Copy</span>
    
                    </button>
    
                    <hr>
    
                    <button
                        onclick="deleteMessage(${chat.id})"
                        class="flex items-center gap-3 w-full px-4 py-3 text-red-600 hover:bg-red-50">
    
                        🗑
                        <span>Delete</span>
    
                    </button>
    
                </div>
    
            </div>
    
            `;
    
        }
    
        return `
    
        <div class="relative">
    
            ${menu}
    
            <div class="${
                mine
                ? "bg-gradient-to-r from-blue-600 to-indigo-600 text-white ml-auto"
                : "bg-white border border-gray-200 text-gray-800"
            } px-5 py-3 rounded-3xl max-w-md shadow">
    
                <div class="break-words">
    
                    ${
                        chat.deleted
                        ? "<i class='opacity-70'>This message was deleted</i>"
                        : (chat.message || "")
                    }
    
                    ${
                        chat.deleted
                        ? ""
                        : this.renderFile(chat)
                    }
    
                </div>
    
                ${
                    chat.edited
                    ? `
                    <div class="text-[10px] italic opacity-60 mt-1">
    
                        edited
    
                    </div>
                    `
                    : ""
                }
    
                <div class="flex justify-end items-center gap-2 mt-2 text-[10px] opacity-70">
    
                    ${new Intl.DateTimeFormat([],{
                        hour:"2-digit",
                        minute:"2-digit"
                    }).format(new Date(chat.created_at))}
    
                    ${
                        mine
                        ? (
                            chat.seen
                            ? "<span class='text-cyan-300'>✔✔</span>"
                            : "<span>✔</span>"
                        )
                        : ""
                    }
    
                </div>
    
            </div>
    
        </div>
    
        `;
    
    }

    // =====================================
    // ADD MESSAGE
    // =====================================

    append(chat){

        if(this.messages.has(chat.id)){

            return;

        }

        this.messages.set(chat.id, chat);

        const wrapper =

            document.createElement("div");

        wrapper.id =

            "msg-" + chat.id;

        wrapper.className =

            chat.sender_id == this.currentUser

            ? "flex justify-end mb-4"

            : "flex justify-start mb-4";

        wrapper.innerHTML =

            this.render(chat);

        this.chatBox.appendChild(wrapper);

        this.scrollBottom();

    }

    // =====================================
    // UPDATE MESSAGE
    // =====================================

    update(chat){

        this.messages.set(chat.id, chat);

        const wrapper =

            document.getElementById(

                "msg-"+chat.id

            );

        if(!wrapper){

            this.append(chat);

            return;

        }

        wrapper.innerHTML =

            this.render(chat);

    }
        // =====================================
    // SEND MESSAGE
    // =====================================

    async send() {

        const formData = new FormData(this.form);

        try {

            const response = await fetch(

                `/messages/${this.receiver}`,

                {
                    method: "POST",
                    body: formData
                }

            );

            const data = await response.json();

            if (!data.success) return;

            // Clear input

            this.messageInput.value = "";

            this.form.reset();

            this.hidePreview();

            // Don't append here.
            // Socket.IO will deliver it.

        }

        catch (error) {

            console.error(error);

        }

    }

    // =====================================
    // FILE PREVIEW
    // =====================================

    showPreview(file) {

        if (!file) return;

        this.previewContainer.classList.remove("hidden");

        if (file.type.startsWith("image/")) {

            this.previewImage.classList.remove("hidden");

            this.previewFile.classList.add("hidden");

            const reader = new FileReader();

            reader.onload = (e) => {

                this.previewImage.src = e.target.result;

            };

            reader.readAsDataURL(file);

        }

        else {

            this.previewImage.classList.add("hidden");

            this.previewFile.classList.remove("hidden");

            this.previewFile.innerHTML = `

                📎 <strong>${file.name}</strong>

                <br>

                ${(file.size / 1024).toFixed(1)} KB

            `;

        }

    }

    hidePreview() {

        this.fileInput.value = "";

        this.previewContainer.classList.add("hidden");

        this.previewImage.classList.add("hidden");

        this.previewFile.classList.add("hidden");

        this.previewImage.src = "";

        this.previewFile.innerHTML = "";

    }

    // =====================================
    // EMOJI
    // =====================================

    toggleEmoji() {

        this.emojiPicker.classList.toggle("hidden");

    }

    insertEmoji(emoji) {

        this.messageInput.value += emoji;

        this.messageInput.focus();

        this.emojiPicker.classList.add("hidden");

    }

    // =====================================
    // SIDEBAR
    // =====================================

    openSidebar() {

        this.sidebar.classList.remove("-translate-x-full");

        this.overlay.classList.remove("hidden");

    }

    closeSidebar() {

        this.sidebar.classList.add("-translate-x-full");

        this.overlay.classList.add("hidden");

    }

    // =====================================
    // SEARCH USERS
    // =====================================

    searchUsers(text) {

        document
            .querySelectorAll(".user-item")
            .forEach(user => {

                user.style.display =

                    user.innerText
                        .toLowerCase()
                        .includes(text.toLowerCase())

                    ? "flex"

                    : "none";

            });

    }

    // =====================================
    // EVENTS
    // =====================================

    initEvents() {

        if (!this.form) return;

        // SEND

        this.form.addEventListener("submit", (e) => {

            e.preventDefault();

            this.send();

        });

        // ENTER

        this.messageInput.addEventListener("keydown", (e) => {

            if (e.key === "Enter" && !e.shiftKey) {

                e.preventDefault();

                this.send();

            }

        });

        // FILE

        this.fileInput?.addEventListener("change", (e) => {

            this.showPreview(e.target.files[0]);

        });

        // REMOVE PREVIEW

        this.removePreview?.addEventListener("click", () => {

            this.hidePreview();

        });

        // EMOJI

        this.emojiBtn?.addEventListener("click", () => {

            this.toggleEmoji();

        });

        document.querySelectorAll(".emoji").forEach(item => {

            item.addEventListener("click", () => {

                this.insertEmoji(item.innerText);

            });

        });

        // SEARCH

        this.searchInput?.addEventListener("keyup", (e) => {

            this.searchUsers(e.target.value);

        });

        // SIDEBAR

        this.menuBtn?.addEventListener("click", () => {

            this.openSidebar();

        });

        this.overlay?.addEventListener("click", () => {

            this.closeSidebar();

        });

    }
        // =====================================
    // TOGGLE MESSAGE MENU
    // =====================================

    toggleMenu(messageId) {

        document.querySelectorAll("[id^='menu-']").forEach(menu => {

            if (menu.id !== `menu-${messageId}`) {

                menu.classList.add("hidden");

            }

        });

        const menu = document.getElementById(`menu-${messageId}`);

        if (menu) {

            menu.classList.toggle("hidden");

        }

    }

    // =====================================
    // EDIT MESSAGE
    // =====================================

    async editMessage(messageId) {

        const chat = this.messages.get(messageId);

        if (!chat) return;

        const newMessage = prompt(

            "Edit message",

            chat.message || ""

        );

        if (newMessage === null) return;

        if (newMessage.trim() === "") return;

        const formData = new FormData();

        formData.append(

            "message",

            newMessage

        );

        try {

            const response = await fetch(

                `/edit_message/${messageId}`,

                {

                    method: "POST",

                    body: formData

                }

            );

            const data = await response.json();

            if (data.success) {

                this.update(data.message);

            }

        }

        catch (err) {

            console.error(err);

        }

    }

    // =====================================
    // DELETE MESSAGE
    // =====================================

    async deleteMessage(messageId) {

        if (!confirm("Delete this message?")) {

            return;

        }

        try {

            const response = await fetch(

                `/delete_message/${messageId}`,

                {

                    method: "POST"

                }

            );

            const data = await response.json();

            if (data.success) {

                this.update(data.message);

            }

        }

        catch (err) {

            console.error(err);

        }

    }

    // =====================================
    // COPY MESSAGE
    // =====================================

    copyMessage(messageId){

        const chat = this.messages.get(messageId);
    
        if(!chat) return;
    
        navigator.clipboard.writeText(
    
            chat.message || ""
    
        );
    
        alert("Copied");
    
    }

} // ===== END OF CLASS =====


// =====================================
// START CHAT
// =====================================

document.addEventListener("DOMContentLoaded", () => {

    if (!window.RECEIVER_ID) {

        return;

    }

    window.chat = new ChatApp();

});


// =====================================
// GLOBAL FUNCTIONS
// (called from HTML)
// =====================================

window.toggleMenu = function(id) {

    window.chat.toggleMenu(id);

};

window.editMessage = function(id) {

    window.chat.editMessage(id);

};

window.deleteMessage = function(id) {

    window.chat.deleteMessage(id);

};

window.copyMessage = function(id) {

    window.chat.copyMessage(id);

};


// =====================================
// CLOSE MENUS WHEN CLICKING OUTSIDE
// =====================================

document.addEventListener("click", function(e){

    if (

        !e.target.closest("[id^='menu-']") &&

        !e.target.closest("button")

    ){

        document.querySelectorAll("[id^='menu-']").forEach(menu=>{

            menu.classList.add("hidden");

        });

    }

});
