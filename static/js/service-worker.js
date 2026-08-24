/* SALT Portal Web Push Service Worker */

self.addEventListener("push", function (event) {
    let data = {};

    try {
        data = event.data ? event.data.json() : {};
    } catch (e) {
        data = {
            title: "SALT Portal",
            body: event.data ? event.data.text() : "You have a new notification."
        };
    }

    const title = data.title || "SALT Portal";

    const options = {
        body: data.body || "You have a new notification.",
        icon: data.icon || "/static/salt-logo.png",
        badge: data.badge || "/static/salt-logo.png",
        tag: data.tag || "salt-portal-notification",
        renotify: true,
        data: {
            url: data.url || "/dashboard"
        }
    };

    event.waitUntil(
        self.registration.showNotification(title, options)
    );
});

self.addEventListener("notificationclick", function (event) {
    event.notification.close();

    const targetUrl =
        event.notification.data?.url || "/dashboard";

    event.waitUntil(
        clients.matchAll({
            type: "window",
            includeUncontrolled: true
        }).then(function (clientList) {

            for (const client of clientList) {
                if ("focus" in client) {
                    return client.focus().then(function () {
                        if ("navigate" in client) {
                            return client.navigate(targetUrl);
                        }
                    });
                }
            }

            if (clients.openWindow) {
                return clients.openWindow(targetUrl);
            }
        })
    );
});
