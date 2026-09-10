# SALT Workforce PWA Update

This project now includes a Progressive Web App foundation.

## Added
- `static/manifest.json` with proper PWA metadata and 192/512 icons.
- `static/icons/icon-192.png` and `icon-512.png`.
- `static/js/pwa.js` for service-worker registration, install prompt handling, online/offline state, and update detection.
- Updated `static/js/service-worker.js` for safe static-asset caching, offline fallback, app updates, and existing Web Push notifications.
- `/offline` route and `templates/offline.html`.
- PWA metadata and bootstrap script across full HTML templates.
- Existing push-notification registrations now use `/service-worker.js` so the portal uses one service worker.
- Dashboard includes an Install App control when the browser exposes the install prompt.

## Security approach
Authenticated pages, API endpoints, uploaded files, profile images, admin routes, requests, chat/messages and other dynamic portal data are deliberately not cached by the service worker.

## Deployment
PWA installation requires a secure context in production. Deploy the portal over HTTPS (your Render deployment should use its HTTPS URL).

## Testing
After deployment:
1. Open the portal in Chrome/Edge on Android or desktop.
2. Log in and open the dashboard.
3. Look for the browser's Install App option or the dashboard Install App button.
4. Test the installed app.
5. Test notification permission/push separately.
6. Test the offline page by temporarily disabling the network and visiting a public navigation page.
