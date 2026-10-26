"""Write tests/route_snapshot.json from the running app's URL map.
Run from the project root with your normal local setup (.env + local database):
    python tools/dump_routes.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402  (initialises your local database exactly like a normal start)

routes = sorted(
    {
        (rule.rule, ",".join(sorted(m for m in rule.methods if m not in ("HEAD", "OPTIONS"))))
        for rule in app.url_map.iter_rules()
    }
)
out = ROOT / "tests" / "route_snapshot.json"
out.write_text(
    json.dumps([{"rule": r, "methods": m} for r, m in routes], indent=2) + "\n", encoding="utf-8"
)
print(f"Wrote {len(routes)} routes to {out}")
