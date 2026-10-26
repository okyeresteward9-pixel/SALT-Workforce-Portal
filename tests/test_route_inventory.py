"""Refactor safety net: the set of URLs + methods must not change while code moves into blueprints.

Create the snapshot ONCE, before refactoring:   python tools/dump_routes.py
Commit tests/route_snapshot.json. After that, any lost or accidentally added route fails this test.
If you add/remove a route ON PURPOSE, run the tool again and commit the new snapshot.
"""
import json
from pathlib import Path

import pytest

SNAPSHOT = Path(__file__).parent / "route_snapshot.json"


def current_routes(app):
    out = set()
    for rule in app.url_map.iter_rules():
        methods = sorted(m for m in rule.methods if m not in ("HEAD", "OPTIONS"))
        out.add((rule.rule, ",".join(methods)))
    return out


def test_routes_match_snapshot(app):
    if not SNAPSHOT.exists():
        pytest.skip("tests/route_snapshot.json not created yet - run: python tools/dump_routes.py")
    expected = {(r["rule"], r["methods"]) for r in json.loads(SNAPSHOT.read_text(encoding="utf-8"))}
    actual = current_routes(app)
    missing, extra = sorted(expected - actual), sorted(actual - expected)
    assert not missing and not extra, f"\nMISSING routes: {missing}\nNEW routes: {extra}"
