"""Small, dependency-free security helpers for the SALT portal.

* LoginThrottle  - blocks repeated failed logins (in-memory, per process).
* origin_allowed - CSRF defence: rejects cross-site state-changing requests.
"""
import threading
import time
from urllib.parse import urlparse

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class LoginThrottle:
    """Allow `max_attempts` failures per (ip, email) per `window` seconds,
    and `ip_max` failures per ip, then refuse further tries until the window
    passes. State lives in memory, so with several gunicorn workers each worker
    counts separately (fine for brute-force protection; use Redis if you need
    exact global limits)."""

    def __init__(self, max_attempts=5, window=900, ip_max=30):
        self.max_attempts = max_attempts
        self.window = window
        self.ip_max = ip_max
        self._lock = threading.Lock()
        self._failures = {}

    @staticmethod
    def _keys(ip, email):
        return (("pair", ip, (email or "").strip().lower()), ("ip", ip))

    def _prune(self, key, now):
        recent = [t for t in self._failures.get(key, []) if now - t < self.window]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def blocked(self, ip, email, now=None):
        now = now or time.time()
        pair_key, ip_key = self._keys(ip, email)
        with self._lock:
            return (
                len(self._prune(pair_key, now)) >= self.max_attempts
                or len(self._prune(ip_key, now)) >= self.ip_max
            )

    def record_failure(self, ip, email, now=None):
        now = now or time.time()
        with self._lock:
            for key in self._keys(ip, email):
                self._prune(key, now)
                self._failures.setdefault(key, []).append(now)

    def reset(self, ip, email):
        with self._lock:
            self._failures.pop(self._keys(ip, email)[0], None)


def origin_allowed(origin, referer, host, allowed_origins=(), fetch_site=None):
    """Return True if a state-changing request looks same-origin.

    Browsers always send Origin (or at least Referer) on cross-site POSTs, so a
    forged request from another site is rejected. Requests with neither header
    come from non-browser clients, which carry no ambient session cookie.
    """
    if fetch_site == "cross-site":
        return False
    if origin == "null":
        return False
    source = origin or referer
    if not source:
        return True
    parsed = urlparse(source)
    if not parsed.netloc:
        return False
    if parsed.netloc.lower() == (host or "").lower():
        return True
    base = f"{parsed.scheme}://{parsed.netloc}".lower()
    return base in {a.strip().lower().rstrip("/") for a in allowed_origins}
