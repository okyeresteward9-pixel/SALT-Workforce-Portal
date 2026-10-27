"""Two different views must never answer the same URL + method. Needs TEST_DATABASE_URL (CI has it)."""
import re


def test_no_two_routes_share_a_url_and_method(app):
    seen = {}
    for rule in app.url_map.iter_rules():
        shape = re.sub(r"<(?:\w+:)?\w+>", "<>", rule.rule)
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            key = (shape, method)
            assert key not in seen, f"{rule.rule} and {seen[key]} both handle {method}"
            seen[key] = rule.rule
