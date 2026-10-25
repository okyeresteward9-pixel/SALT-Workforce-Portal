# SALT Workforce PWA

## Files
- `static/manifest.json` - app identity, icons (any + maskable), shortcuts (Attendance, Tasks, Messages).
- `static/js/service-worker.js` - caches public static assets only; shows `/offline` when a page can't load; handles push.
- `static/js/pwa.js` - registers the service worker, shows the "new version" banner, handles install + online/offline state.
- `static/icons/` - `icon-192/512` (any), `icon-maskable-192/512`, `apple-touch-icon` (180), `favicon-32`.
- `templates/base.html` - loads the manifest, iOS tags and `pwa.js` for every page that extends it.

## Versioning
`/service-worker.js` is served by Flask, which replaces `__APP_VERSION__` with `RENDER_GIT_COMMIT`
(falls back to the file's modified time). Each deploy = new version = old cache deleted automatically.
No manual cache-name edits.

## Updates
A new version waits until the user taps **Refresh** in the banner (or closes every portal tab).
Installed apps check for updates hourly and when returning to the foreground.

## Never cached
Pages, `/api/`, `/socket.io/`, uploads, profile photos, request uploads and announcements.

## Testing (Chrome DevTools -> Application)
1. Manifest: no warnings; icons show 192, 512 and maskable.
2. Service Workers: status "activated and running".
3. Tick "Offline", open /dashboard: the offline page appears.
4. Deploy a change: the "new version" banner appears; Refresh loads it.
