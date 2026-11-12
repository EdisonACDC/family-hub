"""Waits that do not depend on time: they wait for the page to have drawn what the test reads."""

from __future__ import annotations

from playwright.sync_api import Page


def settle(page: Page) -> None:
    """Every CSS animation and transition has finished, and two frames have been drawn after it."""
    page.evaluate(
        "() => Promise.all(document.getAnimations().map(a => a.finished.catch(() => null)))"
        ".then(() => new Promise(resolve => requestAnimationFrame(() =>"
        " requestAnimationFrame(() => resolve(true)))))"
    )
