/* SALT Workforce Portal Service Worker
 * Handles PWA static caching and Web Push notifications.
 * Sensitive portal/API pages are deliberately NOT cached.
 */

const CACHE_NAME = 'salt-workforce-static-v1';
const OFFLINE_URL = '/offline';

const STATIC_ASSETS = [
    OFFLINE_URL,
    '/static/manifest.json',
    '/static/style.css',
    '/static/salt-logo.png',
    '/static/salt-mascot.png',
    '/static/icons/icon-192.png',
    '/static/icons/icon-512.png',
    '/static/js/pwa.js'
];

self.addEventListener('install', function (event) {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(function (cache) {
                return cache.addAll(STATIC_ASSETS);
            })
            .then(function () {
                return self.skipWaiting();
            })
    );
});

self.addEventListener('activate', function (event) {
    event.waitUntil(
        caches.keys().then(function (keys) {
            return Promise.all(
                keys
                    .filter(function (key) {
                        return key !== CACHE_NAME;
                    })
                    .map(function (key) {
                        return caches.delete(key);
                    })
            );
        }).then(function () {
            return self.clients.claim();
        })
    );
});


self.addEventListener('message', function (event) {
    if (event.data && event.data.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }
});

self.addEventListener('fetch', function (event) {
    const request = event.request;

    if (request.method !== 'GET') return;

    const url = new URL(request.url);

    // Only handle requests belonging to this portal.
    if (url.origin !== self.location.origin) return;

    // Never cache authenticated pages, APIs, uploads, or dynamic data.
    if (
        url.pathname.startsWith('/api/') ||
        url.pathname.startsWith('/static/uploads/') ||
        url.pathname.startsWith('/static/profiles/') ||
        url.pathname === '/dashboard' ||
        url.pathname === '/attendance' ||
        url.pathname === '/tasks' ||
        url.pathname === '/notifications' ||
        url.pathname.startsWith('/admin/') ||
        url.pathname.startsWith('/requests') ||
        url.pathname.startsWith('/chat') ||
        url.pathname.startsWith('/messages')
    ) {
        return;
    }

    // Static assets: cache-first, then network.
    if (url.pathname.startsWith('/static/')) {
        event.respondWith(
            caches.match(request).then(function (cached) {
                return cached || fetch(request).then(function (response) {
                    if (response.ok) {
                        const copy = response.clone();
                        caches.open(CACHE_NAME).then(function (cache) {
                            cache.put(request, copy);
                        });
                    }
                    return response;
                });
            })
        );
        return;
    }

    // Public navigation: network-first, offline fallback.
    if (request.mode === 'navigate') {
        event.respondWith(
            fetch(request).catch(function () {
                return caches.match(OFFLINE_URL);
            })
        );
    }
});

self.addEventListener('push', function (event) {
    let data = {};

    try {
        data = event.data ? event.data.json() : {};
    } catch (error) {
        data = {
            title: 'SALT Workforce',
            body: event.data ? event.data.text() : 'You have a new notification.'
        };
    }

    const title = data.title || 'SALT Workforce';
    const options = {
        body: data.body || 'You have a new notification.',
        icon: data.icon || '/static/icons/icon-192.png',
        badge: data.badge || '/static/icons/icon-192.png',
        tag: data.tag || 'salt-workforce-notification',
        renotify: true,
        data: {
            url: data.url || '/dashboard'
        }
    };

    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', function (event) {
    event.notification.close();

    const targetUrl = event.notification.data && event.notification.data.url
        ? event.notification.data.url
        : '/dashboard';

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true })
            .then(function (clientList) {
                for (const client of clientList) {
                    if ('focus' in client) {
                        return client.focus().then(function () {
                            if ('navigate' in client) return client.navigate(targetUrl);
                        });
                    }
                }
                if (clients.openWindow) return clients.openWindow(targetUrl);
            })
    );
});
