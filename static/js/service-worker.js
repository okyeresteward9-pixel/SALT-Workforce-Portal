/* SALT Workforce Portal Service Worker
 *
 * - Caches only public static assets (stale-while-revalidate).
 * - NEVER caches pages, API calls, uploads, profile photos or chat data.
 * - Shows /offline when a page cannot be reached.
 * - Handles Web Push notifications.
 *
 * The version placeholder below is filled in by the Flask /service-worker.js route
 * with the deploy's commit id, so every deploy gets a fresh cache and a clean update.
 */
const VERSION = '__APP_VERSION__';
const CACHE_PREFIX = 'salt-static-';
const CACHE_NAME = CACHE_PREFIX + VERSION;
const OFFLINE_URL = '/offline';

// Everything the offline page needs to render.
const PRECACHE = [
    OFFLINE_URL,
    '/static/manifest.json',
    '/static/icons/icon-192.png',
    '/static/css/salt-design-system.css',
    '/static/js/salt-mobile-navigation.js'
];

// User content and dynamic data: always straight to the network.
const NEVER_CACHE_PREFIXES = [
    '/static/uploads/',
    '/static/profiles/',
    '/static/request_uploads/',
    '/static/announcements/',
    '/api/',
    '/socket.io/'
];
const CACHEABLE_EXT = /\.(?:css|js|png|jpe?g|gif|svg|webp|ico|woff2?|mp3|json)$/i;

self.addEventListener('install', function (event) {
    // No skipWaiting() here: a new version waits until the user taps
    // "Refresh" in the update banner (or closes all portal tabs).
    event.waitUntil(
        caches.open(CACHE_NAME).then(function (cache) {
            return Promise.all(PRECACHE.map(function (url) {
                return cache.add(new Request(url, { cache: 'reload' })).catch(function () {});
            }));
        })
    );
});

self.addEventListener('activate', function (event) {
    event.waitUntil(
        caches.keys().then(function (keys) {
            return Promise.all(keys
                .filter(function (key) { return key !== CACHE_NAME; })
                .map(function (key) { return caches.delete(key); }));
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
    if (url.origin !== self.location.origin) return;

    // Pages are private and dynamic: always the network. If it fails, show the
    // offline page (this now also covers /dashboard, /tasks, /messages, ...).
    if (request.mode === 'navigate') {
        event.respondWith(
            fetch(request).catch(function () {
                return caches.match(OFFLINE_URL).then(function (cached) {
                    return cached || Response.error();
                });
            })
        );
        return;
    }

    if (url.pathname === '/service-worker.js') return;
    if (!url.pathname.startsWith('/static/')) return;
    if (NEVER_CACHE_PREFIXES.some(function (p) { return url.pathname.startsWith(p); })) return;
    if (!CACHEABLE_EXT.test(url.pathname)) return;
    if (request.headers.has('range')) return; // audio/video range requests can't be cached

    // Stale-while-revalidate: instant from cache, refreshed in the background.
    event.respondWith(
        caches.open(CACHE_NAME).then(function (cache) {
            return cache.match(request).then(function (cached) {
                const network = fetch(request).then(function (response) {
                    if (response && response.ok && response.type === 'basic') {
                        cache.put(request, response.clone());
                    }
                    return response;
                }).catch(function () { return null; });

                if (cached) {
                    event.waitUntil(network);
                    return cached;
                }
                return network.then(function (response) {
                    return response || Response.error();
                });
            });
        })
    );
});

// ---------------------------------------------------------------- Web Push
function safeTarget(raw) {
    try {
        const target = new URL(raw || '/dashboard', self.location.origin);
        return target.origin === self.location.origin ? target.href : '/dashboard';
    } catch (e) {
        return '/dashboard';
    }
}

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

    event.waitUntil(self.registration.showNotification(data.title || 'SALT Workforce', {
        body: data.body || 'You have a new notification.',
        icon: data.icon || '/static/icons/icon-192.png',
        badge: data.badge || '/static/icons/icon-192.png',
        tag: data.tag || 'salt-workforce-notification',
        renotify: true,
        data: { url: safeTarget(data.url) }
    }));
});

self.addEventListener('notificationclick', function (event) {
    event.notification.close();
    const targetUrl = safeTarget(event.notification.data && event.notification.data.url);

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (list) {
            for (const client of list) {
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
