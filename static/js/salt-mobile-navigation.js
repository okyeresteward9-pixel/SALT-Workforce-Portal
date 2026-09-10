/* SALT Workforce — Professional mobile navigation v3 */
(function () {
  "use strict";

  function path() {
    return window.location.pathname.replace(/\/+$/, "") || "/";
  }

  function isPublicPage() {
    var p = path();
    return p === "/" ||
           p === "/login" ||
           p === "/forgot-password" ||
           p === "/reset-password" ||
           p.indexOf("/login/") === 0;
  }

  function isAdminPath() {
    return path().indexOf("/admin/") === 0;
  }

  function addNav() {
    if (document.querySelector(".salt-mobile-nav")) return;

    var items = isAdminPath()
      ? [
          ["/dashboard", "fa-house", "Home"],
          ["/admin/tasks", "fa-list-check", "Tasks"],
          ["/admin/employees", "fa-users", "Staff"],
          ["/admin/announcements", "fa-bullhorn", "News"],
          ["/settings/profile", "fa-user", "Profile"]
        ]
      : [
          ["/dashboard", "fa-house", "Home"],
          ["/tasks", "fa-list-check", "Tasks"],
          ["/attendance", "fa-clock", "Attendance"],
          ["/notifications", "fa-bell", "Alerts"],
          ["/settings/profile", "fa-user", "Profile"]
        ];

    var nav = document.createElement("nav");
    nav.className = "salt-mobile-nav";
    nav.setAttribute("aria-label", "Mobile navigation");

    items.forEach(function (item) {
      var a = document.createElement("a");
      a.href = item[0];
      a.setAttribute("aria-label", item[2]);
      a.innerHTML =
        '<span class="salt-nav-icon" aria-hidden="true">' +
          '<i class="fa-solid ' + item[1] + '"></i>' +
        '</span>' +
        '<span class="salt-nav-label">' + item[2] + '</span>';

      var p = path();
      if (p === item[0] || (item[0] !== "/dashboard" && p.indexOf(item[0]) === 0)) {
        a.classList.add("active");
      }

      nav.appendChild(a);
    });

    document.body.appendChild(nav);
    document.body.classList.add("salt-mobile-template");
  }

  function init() {
    if (isPublicPage()) return;

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
