
/* SALT Workforce — mobile navigation + PWA install UX */
(function () {
  "use strict";

  function currentPath() {
    return window.location.pathname.replace(/\/+$/, "") || "/";
  }

  function addMobileNav() {
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
      var a = document.createElement("a");
      a.href = item[0];
      a.innerHTML = '<i class="fa-solid ' + item[1] + '" aria-hidden="true"></i><span>' + item[2] + '</span>';
      if (currentPath() === item[0]) a.classList.add("active");
      nav.appendChild(a);
    });

    document.body.appendChild(nav);

    var main = document.querySelector("main, .main-content, .content, .dashboard-content");
    if (main) main.classList.add("salt-mobile-content");
  }

  var deferredPrompt = null;

  function addInstallBanner() {
    if (document.querySelector(".salt-install-banner")) return;

    var banner = document.createElement("div");
    banner.className = "salt-install-banner";
    banner.innerHTML =
      '<div class="install-copy">' +
        '<strong>Install SALT Workforce</strong>' +
        '<small>Use the portal like an app from your home screen.</small>' +
      '</div>' +
      '<button class="install-btn" type="button">Install</button>' +
      '<button class="dismiss" type="button" aria-label="Dismiss">×</button>';

    document.body.appendChild(banner);

    banner.querySelector(".install-btn").addEventListener("click", async function () {
      if (!deferredPrompt) return;
      deferredPrompt.prompt();
      try { await deferredPrompt.userChoice; } catch (e) {}
      deferredPrompt = null;
      banner.classList.remove("show");
    });

    banner.querySelector(".dismiss").addEventListener("click", function () {
      banner.classList.remove("show");
      try { sessionStorage.setItem("salt-pwa-install-dismissed", "1"); } catch (e) {}
    });

    window.addEventListener("beforeinstallprompt", function (event) {
      event.preventDefault();
      deferredPrompt = event;
      var dismissed = false;
      try { dismissed = sessionStorage.getItem("salt-pwa-install-dismissed") === "1"; } catch (e) {}
      if (!dismissed) banner.classList.add("show");
    });

    window.addEventListener("appinstalled", function () {
      deferredPrompt = null;
      banner.classList.remove("show");
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (window.matchMedia("(max-width: 768px)").matches) {
      addMobileNav();
    }
    addInstallBanner();
  });
})();
