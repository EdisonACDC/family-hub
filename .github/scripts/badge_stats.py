"""Numbers for the README badges, stable versions only.

- downloads.json: downloads of the assets of every release that is not a pre-release.
- installs.json: active installations from Home Assistant Analytics
  (custom_integrations.json -> family_hub.versions), summing only versions without
  a/b/rc/dev or local suffixes.

Both files use the shields.io "endpoint" format; the README sets the label in its language.
Usage: python badge_stats.py <output dir>   (GITHUB_TOKEN and GITHUB_REPOSITORY from Actions)
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

DOMAIN = "family_hub"
ANALYTICS_URL = "https://analytics.home-assistant.io/custom_integrations.json"
STABLE = re.compile(r"v?\d+(\.\d+)*")


def is_stable(version: str) -> bool:
    """0.9.0 yes; 0.9.0b9, 0.9.0rc1, 0.9.0.dev3, 1.0.0+local, 2.0.6-dev-x no."""
    return bool(STABLE.fullmatch(version.strip()))


def stable_downloads(releases: list[dict[str, Any]]) -> int:
    total = 0
    for release in releases:
        if release.get("prerelease") or release.get("draft"):
            continue
        total += sum(int(asset.get("download_count", 0)) for asset in release.get("assets", []))
    return total


def stable_installs(analytics: dict[str, Any], domain: str = DOMAIN) -> int:
    versions = (analytics.get(domain) or {}).get("versions") or {}
    return sum(int(count) for version, count in versions.items() if is_stable(str(version)))


def badge(count: int) -> dict[str, Any]:
    return {"schemaVersion": 1, "label": "", "message": str(count), "color": "blue"}


def _get(url: str, token: str | None = None) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "family-hub-badges"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
        request.add_header("Accept", "application/vnd.github+json")
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 (fixed https URLs)
        return json.load(response)


def _releases(repository: str, token: str | None) -> list[dict[str, Any]]:
    releases: list[dict[str, Any]] = []
    page = 1
    while True:
        url = f"https://api.github.com/repos/{repository}/releases?per_page=100&page={page}"
        batch = _get(url, token)
        releases.extend(batch)
        if len(batch) < 100:
            return releases
        page += 1


def main(out_dir: str) -> None:
    repository = os.environ.get("GITHUB_REPOSITORY", "EdisonACDC/family-hub")
    token = os.environ.get("GITHUB_TOKEN")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    downloads = stable_downloads(_releases(repository, token))
    installs = stable_installs(_get(ANALYTICS_URL))
    (out / "downloads.json").write_text(json.dumps(badge(downloads)), encoding="utf-8")
    (out / "installs.json").write_text(json.dumps(badge(installs)), encoding="utf-8")
    print(f"downloads={downloads} installs={installs}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "badges")
