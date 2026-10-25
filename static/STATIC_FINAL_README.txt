SALT Workforce Portal — Final Static Folder

- style.css is the single global/master stylesheet.
- Useful rules from salt-design-system.css, salt-core.css and salt-mobile-pwa.css
  were merged into style.css.
- Redundant global CSS files and duplicate css/css were removed.
- Existing JavaScript, PWA assets, images, icons, profiles, sounds, uploads and
  manifest were preserved.
- Service-worker cache version was bumped to v3.

Templates should load:
    /static/style.css
