
/* SALT Workforce — Unified mobile navigation */
(function () {
  "use strict";

  function normalizedPath() {
    return window.location.pathname.replace(/\/+$/, "") || "/";
  }

  function isAdminPath() {
    return normalizedPath().indexOf("/admin/") === 0;
  }

  function addNav() {
    if (document.querySelector(".salt-mobile-nav")) return;

    var items = [
      ["/dashboard", "fa-house", "Home"],
      ["/tasks", "fa-list-check", "Tasks"],
      ["/attendance", "fa-clock", "Attendance"],
      ["/notifications", "fa-bell", "Alerts"],
      ["/settings/profile", "fa-user", "Profile"]
    ];

    /* On admin pages keep the same visual system but make the navigation
       point to useful admin destinations. */
    if (isAdminPath()) {
      items = [
        ["/dashboard", "fa-house", "Home"],
        ["/admin/tasks", "fa-list-check", "Tasks"],
        ["/admin/employees", "fa-users", "Staff"],
        ["/admin/announcements", "fa-bullhorn", "News"],
        ["/settings/profile", "fa-user", "Profile"]
      ];
    }

    var nav = document.createElement("nav");
    nav.className = "salt-mobile-nav";
    nav.setAttribute("aria-label", "Mobile navigation");

    items.forEach(function (item) {
      var a = document.createElement("a");
      a.href = item[0];
      a.innerHTML =
        '<i class="fa-solid ' + item[1] + '" aria-hidden="true"></i>' +
        '<span>' + item[2] + '</span>';

      var p = normalizedPath();
      if (p === item[0] || (item[0] !== "/dashboard" && p.indexOf(item[0]) === 0)) {
        a.classList.add("active");
      }

      nav.appendChild(a);
    });

    document.body.appendChild(nav);
    document.body.classList.add("salt-mobile-template");
  }

  function init() {
    if (window.matchMedia("(max-width: 768px)").matches) {
      addNav();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
