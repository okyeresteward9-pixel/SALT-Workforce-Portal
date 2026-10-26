"""Guards the Step 3 PWA work. No database needed."""
import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def png_size(path):
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    return struct.unpack(">II", data[16:24])


def test_manifest_icons_exist_with_declared_sizes():
    manifest = json.loads((ROOT / "static" / "manifest.json").read_text(encoding="utf-8"))
    purposes = set()
    for icon in manifest["icons"]:
        path = ROOT / icon["src"].lstrip("/")
        assert path.exists(), f"missing icon file {icon['src']}"
        w, h = (int(x) for x in icon["sizes"].split("x"))
        assert png_size(path) == (w, h), f"{icon['src']} is not really {icon['sizes']}"
        purposes.add(icon.get("purpose"))
    assert {"any", "maskable"} <= purposes, "need separate 'any' and 'maskable' icons"
    assert {192, 512} <= {int(i["sizes"].split("x")[0]) for i in manifest["icons"]}


def test_manifest_shortcuts_and_start_url():
    manifest = json.loads((ROOT / "static" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["start_url"].startswith("/")
    assert manifest["display"] == "standalone"
    for shortcut in manifest.get("shortcuts", []):
        assert shortcut["url"].startswith("/")


def test_service_worker_has_exactly_one_version_placeholder():
    sw = (ROOT / "static" / "js" / "service-worker.js").read_text(encoding="utf-8")
    assert sw.count("__APP_VERSION__") == 1
    assert "skipWaiting()" in sw


def test_base_template_loads_pwa_assets():
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert "manifest.json" in base and "js/pwa.js" in base and "apple-touch-icon" in base


def test_no_second_service_worker_registration():
    for js in (ROOT / "static" / "js").glob("*.js"):
        if js.name == "pwa.js":
            continue
        assert not re.search(r"serviceWorker\.register\(\s*['\"]/static", js.read_text(encoding="utf-8")), js.name
