"""Pure unit tests - no database or app needed."""
from security import LoginThrottle, origin_allowed

HOST = "portal.onrender.com"


def test_throttle_blocks_after_limit_and_expires():
    t = LoginThrottle(max_attempts=5, window=900, ip_max=30)
    for i in range(5):
        t.record_failure("1.2.3.4", "a@b.com", now=1000 + i)
    assert t.blocked("1.2.3.4", "a@b.com", now=1010)
    assert t.blocked("1.2.3.4", " A@B.com ", now=1010)       # case/space-insensitive
    assert not t.blocked("9.9.9.9", "a@b.com", now=1010)      # other IP unaffected
    assert not t.blocked("1.2.3.4", "a@b.com", now=2000)      # window passed


def test_throttle_reset_and_per_ip_cap():
    t = LoginThrottle(max_attempts=5, window=900, ip_max=3)
    t.record_failure("1.2.3.4", "a@b.com")
    t.reset("1.2.3.4", "a@b.com")
    assert not t.blocked("1.2.3.4", "a@b.com")
    for i in range(3):
        t.record_failure("5.5.5.5", f"u{i}@x.com", now=50)
    assert t.blocked("5.5.5.5", "someone-new@x.com", now=60)


def test_same_origin_allowed():
    assert origin_allowed("https://portal.onrender.com", None, HOST)
    assert origin_allowed(None, "https://portal.onrender.com/tasks", HOST)
    assert origin_allowed(None, None, HOST)                   # non-browser client


def test_cross_site_blocked():
    assert not origin_allowed("https://evil.com", None, HOST)
    assert not origin_allowed("null", None, HOST)
    assert not origin_allowed("https://portal.onrender.com.evil.com", None, HOST)
    assert not origin_allowed(None, "https://evil.com/page", HOST)           # GET link from another site
    assert not origin_allowed(None, None, HOST, fetch_site="cross-site")     # browser says cross-site


def test_allowed_origins_list():
    assert origin_allowed("https://other.app", None, HOST, ["https://other.app/"])
