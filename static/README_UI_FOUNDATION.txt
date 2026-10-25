SALT UI FOUNDATION — STATIC FOLDER

This package keeps the existing SALT assets and page styling, removes the duplicate static/css/css copy, and uses one active CSS stack.

Active CSS order in base.html:
1. /static/style.css                 — existing page/content styles
2. /static/css/salt-design-system.css — shared SALT tokens/components
3. /static/css/salt-mobile-pwa.css    — existing mobile/PWA rules
4. /static/css/salt-core.css          — new global shell

Do not delete style.css yet. It still contains important page-level classes used by existing templates.
