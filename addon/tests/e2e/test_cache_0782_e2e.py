"""0.7.8b2: after an update the browser gets the new page and files. The page is sent no-cache; the
files named with their version are kept a year; a page of an older version reloads once by itself."""

from __future__ import annotations

import urllib.request

from playwright.sync_api import Browser, expect

from app.version import ADDON_VERSION
from tests.e2e.conftest import Stack
from tests.e2e.test_tablet import _device


def _headers(url: str) -> dict[str, str]:
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - the test server
        return {key.lower(): value for key, value in response.headers.items()}


def test_the_page_is_sent_no_cache_and_names_its_version(stack_full: Stack) -> None:
    headers = _headers(stack_full.url + "/")
    assert headers["cache-control"] == "no-cache"
    with urllib.request.urlopen(stack_full.url + "/", timeout=10) as response:  # noqa: S310
        page = response.read().decode("utf-8")
    assert f'name="fh-version" content="{ADDON_VERSION}"' in page
    for name in ("app.css", "i18n.js", "mdi.js", "app.js"):
        assert f"static/{name}?v={ADDON_VERSION}" in page, name
    assert "__VERSION__" not in page


def test_a_versioned_file_is_kept_a_year_and_an_unversioned_one_is_checked_again(
    stack_full: Stack,
) -> None:
    versioned = _headers(stack_full.url + f"/static/app.js?v={ADDON_VERSION}")
    assert versioned["cache-control"] == "public, max-age=31536000, immutable"
    plain = _headers(stack_full.url + "/static/app.js")
    assert plain["cache-control"] == "no-cache"


def test_an_old_page_reloads_once_by_itself(stack_full: Stack, browser: Browser) -> None:
    """The browser kept a page of an older version: the first load shows an old version mark; the
    page asks the add-on, sees another version, and reloads once. The second load shows the current
    version, and the mark in the session stops a second reload."""
    old_first = """
      document.addEventListener('DOMContentLoaded', function () {
        try {
          if (sessionStorage.getItem('fh-old-once')) return;
          sessionStorage.setItem('fh-old-once', '1');
        } catch (err) { return; }
        document.querySelector("meta[name='fh-version']").setAttribute('content', '0.7.0');
      });
    """
    with _device(browser, 390, 844) as page:
        page.add_init_script(old_first)
        page.goto(stack_full.url + "/?lang=it")
        page.wait_for_function(
            "sessionStorage.getItem('fh-reloaded-" + ADDON_VERSION + "') === '1'", timeout=10000
        )
        expect(page.locator("meta[name='fh-version']")).to_have_attribute(
            "content", ADDON_VERSION, timeout=8000
        )
