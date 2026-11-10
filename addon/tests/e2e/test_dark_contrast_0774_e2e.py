"""0.7.7b2: in the dark theme every text has at least 4.5:1 contrast with what is behind it: the
clock, the date, the weather, the period title and the month title, and every other text on every
screen. Light colours from the light theme must not stay in the dark one."""

from __future__ import annotations

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_layout_071_e2e import _open, _screens, _seeded, _view
from tests.e2e.test_tablet import _device

# The night glass's base colour (the body), as RGB; the contrast of each text is measured against
# what lies behind it: its ancestors' backgrounds, composited over this base.
NIGHT_BASE = "rgb(11, 18, 32)"

CONTRAST_JS = """
(base) => {
  const parse = (c) => {
    const m = c.match(/[\\d.]+/g);
    if (!m) return null;
    const n = m.map(Number);
    return { r: n[0], g: n[1], b: n[2], a: n.length > 3 ? n[3] : 1 };
  };
  const over = (top, bottom) => ({
    r: top.r * top.a + bottom.r * (1 - top.a),
    g: top.g * top.a + bottom.g * (1 - top.a),
    b: top.b * top.a + bottom.b * (1 - top.a),
    a: 1,
  });
  const lum = (c) => {
    const f = (v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const behind = (el) => {
    const chain = [];
    for (let n = el; n; n = n.parentElement) chain.unshift(n);
    let acc = parse(base);
    for (const n of chain) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c && c.a > 0) acc = over(c, acc);
    }
    return acc;
  };
  const problems = [];
  for (const el of document.querySelectorAll("body *")) {
    const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    if (!own || el.getClientRects().length === 0) continue;
    const style = getComputedStyle(el);
    if (style.visibility === "hidden" || style.display === "none") continue;
    const fg = parse(style.color);
    if (!fg) continue;
    const bg = behind(el);
    const text = over(fg, bg);
    const hi = Math.max(lum(text), lum(bg));
    const lo = Math.min(lum(text), lum(bg));
    const ratio = (hi + 0.05) / (lo + 0.05);
    if (ratio < 4.5) {
      const cls = String(el.className).split(" ")[0];
      const name = el.id ? "#" + el.id : cls ? "." + cls : el.tagName;
      const behind = [bg.r, bg.g, bg.b].map((v) => v.toFixed(0)).join(",");
      problems.push(name + " " + ratio.toFixed(2) + " " + style.color + " on " + behind);
    }
  }
  return problems;
}
"""


def _night(stack: Stack) -> None:
    stack.fake.config["screen"] = {**stack.fake.config.get("screen", {}), "theme": "dark"}


def _reset(stack: Stack) -> None:
    stack.fake.config["screen"] = {**stack.fake.config.get("screen", {}), "theme": "auto"}


@pytest.mark.parametrize(("width", "height"), [(390, 844), (1024, 768)])
def test_the_top_bar_and_the_titles_are_readable_in_the_dark_theme(
    stack_full: Stack, browser: Browser, width: int, height: int
) -> None:
    _night(stack_full)
    try:
        with _seeded(stack_full), _device(browser, width, height) as page:
            _open(page, stack_full)
            expect(page.locator("html")).to_have_attribute("data-theme", "dark")
            for selector in ["#clock-time", "#clock-date", "#period-title"]:
                ratio = _ratio(page, selector)
                assert ratio >= 4.5, (selector, ratio)
            if page.locator(".weather-now").count():
                assert _ratio(page, ".weather-now") >= 4.5
    finally:
        _reset(stack_full)


@pytest.mark.parametrize(("width", "height"), [(390, 844), (1024, 768)])
def test_the_month_title_is_readable_in_the_dark_theme(
    stack_full: Stack, browser: Browser, width: int, height: int
) -> None:
    _night(stack_full)
    try:
        with _seeded(stack_full), _device(browser, width, height) as page:
            _open(page, stack_full)
            _view(page, "month")
            expect(page.locator("#month-scroll")).to_be_visible(timeout=5000)
            expect(page.locator(".month-block .month-title").first).to_be_visible(timeout=5000)
            assert _ratio(page, ".month-block .month-title") >= 4.5
    finally:
        _reset(stack_full)


@pytest.mark.parametrize(("width", "height"), [(390, 844), (1024, 768)])
def test_every_text_on_every_screen_is_readable_in_the_dark_theme(
    stack_full: Stack, browser: Browser, width: int, height: int
) -> None:
    _night(stack_full)
    problems: list[str] = []
    try:
        with _seeded(stack_full), _device(browser, width, height) as page:
            for name, go in _screens(stack_full):
                _open(page, stack_full)
                try:
                    go(page)
                    page.wait_for_timeout(150)
                    for item in page.evaluate(CONTRAST_JS, NIGHT_BASE):
                        problems.append(f"{name}: {item}")
                except Exception as err:  # the screen could not be reached at this size
                    problems.append(
                        f"{name}: could not open ({type(err).__name__}: {str(err)[:120]})"
                    )
    finally:
        _reset(stack_full)
    assert not problems, f"dark theme at {width}x{height}:\n" + "\n".join(problems)


RATIO_JS = r"""
(sel) => {
  const el = document.querySelector(sel);
  const parse = (c) => {
    const m = c.match(/[\d.]+/g).map(Number);
    return { r: m[0], g: m[1], b: m[2], a: m.length > 3 ? m[3] : 1 };
  };
  const over = (t, b) => ({
    r: t.r * t.a + b.r * (1 - t.a),
    g: t.g * t.a + b.g * (1 - t.a),
    b: t.b * t.a + b.b * (1 - t.a),
    a: 1,
  });
  const lum = (c) => {
    const f = (v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const chain = [];
  for (let n = el; n; n = n.parentElement) chain.unshift(n);
  let bg = parse("rgb(11, 18, 32)");
  for (const n of chain) {
    const c = parse(getComputedStyle(n).backgroundColor);
    if (c.a > 0) bg = over(c, bg);
  }
  const text = over(parse(getComputedStyle(el).color), bg);
  const hi = Math.max(lum(text), lum(bg));
  const lo = Math.min(lum(text), lum(bg));
  return (hi + 0.05) / (lo + 0.05);
}
"""


def _ratio(page: Page, selector: str) -> float:
    return float(page.evaluate(RATIO_JS, selector))
