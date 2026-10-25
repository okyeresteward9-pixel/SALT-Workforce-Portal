SALT Workforce Portal — UI/UX Refactor — Step 1

Added:
1. templates/base.html — new global application shell.
2. static/css/salt-core.css — isolated core shell styling.

Important:
- Existing templates and CSS are NOT overwritten.
- Existing chat/PWA/request functionality is intentionally preserved.
- The next migration should convert dashboard.html first, then tasks/attendance/employees, then the request workflow.
- Copy base.html into the project's templates/ directory and salt-core.css into static/css/.
- Do not delete the existing CSS files yet.
