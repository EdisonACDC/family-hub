"""Copy the panel of the add-on into the guests' web app, for "Completa" (Family Hub 0.10.0b2).

The guest's "Completa" is the panel itself: the same script, style and page, so it looks and
works the same now and after every change to the panel. Only the channel differs: bridge.js
answers the panel's requests with the guests' API (see guest_www/bridge.js).

Run after every change to addon/app/static (tests/test_guest_panel_sync.py fails until then):

    python scripts/sync_guest_panel.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANEL = ROOT / "addon" / "app" / "static"
WWW = ROOT / "custom_components" / "family_hub" / "guest_www"
BASE = "/api/family_hub/guest/"

# The panel's file -> its copy in the web app (unchanged, byte for byte).
COPIES = {
    "app.js": "panel-app.js",
    "i18n.js": "panel-i18n.js",
    "mdi.js": "panel-mdi.js",
    "app.css": "panel.css",
}


def version() -> str:
    manifest = json.loads((ROOT / "custom_components/family_hub/manifest.json").read_text("utf-8"))
    return str(manifest["version"])


def full_page() -> str:
    """The panel's page, pointing at the copies, with the bridge before the panel's script.
    The QR code script is left out: it is used by Condivisione only, never by a guest."""
    page = (PANEL / "index.html").read_text("utf-8")
    ver = version()
    page = page.replace("__VERSION__", ver)
    page = page.replace(
        f'<link rel="stylesheet" href="static/app.css?v={ver}">',
        f'<meta name="referrer" content="no-referrer">\n'
        f'  <meta name="theme-color" content="#2563EB">\n'
        f'  <link rel="manifest" href="{BASE}manifest.json">\n'
        f'  <link rel="icon" href="{BASE}icon-192.png">\n'
        f'  <link rel="apple-touch-icon" href="{BASE}apple-touch-icon.png">\n'
        f'  <link rel="stylesheet" href="{BASE}panel.css?v={ver}">\n'
        f'  <link rel="stylesheet" href="{BASE}full.css?v={ver}">',
    )
    page = page.replace(f'  <script src="static/qr.js?v={ver}"></script>\n', "")
    page = page.replace(
        f'<script src="static/app.js?v={ver}"></script>',
        f'<script src="{BASE}bridge.js?v={ver}"></script>\n'
        f'  <script src="{BASE}panel-app.js?v={ver}"></script>',
    )
    for name in ("i18n.js", "mdi.js"):
        page = page.replace(f'src="static/{name}?v={ver}"', f'src="{BASE}panel-{name}?v={ver}"')
    if "static/" in page:
        raise SystemExit("index.html of the panel refers to a file this script does not copy")
    return page


def expected() -> dict[str, bytes]:
    files = {copy: (PANEL / name).read_bytes() for name, copy in COPIES.items()}
    files["full.html"] = full_page().encode("utf-8")
    return files


def main() -> int:
    for name, data in expected().items():
        (WWW / name).write_bytes(data)
        print(f"{name}: {len(data)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
