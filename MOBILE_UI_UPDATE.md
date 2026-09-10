# SALT Workforce Mobile UI Update

All HTML templates now load the shared SALT Workforce design system.

The shared system provides:
- consistent SALT blue/white colour variables
- consistent surfaces, borders, shadows and radii
- professional status colours
- touch-friendly controls
- mobile bottom navigation
- separate admin mobile destinations
- no cartoon/emoji interface icons

Existing page-specific functionality and styles are preserved.


## v2 fix
The mobile authenticated navigation is now disabled on the login/public authentication routes.


## v3
Fixed dashboard mobile navigation injection and corrected the Alerts route to `/notifications`. Added cache-busting to dashboard navigation assets.
