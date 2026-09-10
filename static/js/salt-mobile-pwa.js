/* SALT Workforce - Professional Mobile/PWA UI */
(function () {
    "use strict";

    function path() {
        return window.location.pathname.replace(/\/+$/, "") || "/";
    }

    function addMobileNavigation() {
        if (document.querySelector(".salt-mobile-nav")) return;

        var nav = document.createElement("nav");
        nav.className = "salt-mobile-nav";
        nav.setAttribute("aria-label", "Mobile navigation");

        var items = [
            ["/dashboard", "fa-house", "Home"],
            ["/tasks", "fa-list-check", "Tasks"],
            ["/attendance", "fa-clock", "Attendance"],
            ["/notifications", "fa-bell", "Alerts"],
            ["/settings/profile", "fa-user", "Profile"]
        ];

        items.forEach(function (item) {
            var link = document.createElement("a");
            link.href = item[0];
            link.innerHTML =
                '<i class="fa-solid ' + item[1] + '" aria-hidden="true"></i>' +
                '<span>' + item[2] + '</span>';

            if (path() === item[0]) {
                link.classList.add("active");
            }

            nav.appendChild(link);
        });

        document.body.appendChild(nav);
        document.body.classList.add("salt-mobile-pwa");
    }

    var deferredPrompt = null;

    function setupInstallPrompt() {
        var banner = document.querySelector(".salt-install-banner");

        if (!banner) {
            banner = document.createElement("div");
            banner.className = "salt-install-banner";
            banner.innerHTML =
                '<div class="install-copy">' +
                    '<strong>Install SALT Workforce</strong>' +
                    '<small>Access the portal quickly from your home screen.</small>' +
                '</div>' +
                '<button type="button" class="install-btn">Install</button>' +
                '<button type="button" class="dismiss" aria-label="Dismiss">×</button>';

            document.body.appendChild(banner);
        }

        var installButton = banner.querySelector(".install-btn");
        var dismissButton = banner.querySelector(".dismiss");

        if (installButton) {
            installButton.addEventListener("click", async function () {
                if (!deferredPrompt) return;

                deferredPrompt.prompt();

                try {
                    await deferredPrompt.userChoice;
                } catch (e) {}

                deferredPrompt = null;
                banner.classList.remove("show");
            });
        }

        if (dismissButton) {
            dismissButton.addEventListener("click", function () {
                banner.classList.remove("show");
                try {
                    sessionStorage.setItem("salt-install-dismissed", "1");
                } catch (e) {}
            });
        }

        window.addEventListener("beforeinstallprompt", function (event) {
            event.preventDefault();
            deferredPrompt = event;

            var dismissed = false;
            try {
                dismissed = sessionStorage.getItem("salt-install-dismissed") === "1";
            } catch (e) {}

            if (!dismissed) {
                banner.classList.add("show");
            }
        });

        window.addEventListener("appinstalled", function () {
            deferredPrompt = null;
            banner.classList.remove("show");
        });
    }

    function init() {
        if (window.matchMedia("(max-width: 768px)").matches) {
            addMobileNavigation();
        }

        setupInstallPrompt();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
