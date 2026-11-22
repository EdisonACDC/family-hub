"""0.10.5b1: in the week view a name is never broken inside a word (it breaks between words, or
is hyphenated/cut when one word does not fit), the person dots take a line of their own, and the
period of the view stays on one line (it, de, en; desktop and phone widths)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from playwright.sync_api import Browser, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_layout_071_e2e import _open, _view
from tests.e2e.test_tablet import _device
from tests.fake_ha import FAMILY, PERSONS, stored_event

# A word split across two lines: the same word has text boxes on different lines.
WORDS_SPLIT_JS = """
(el) => {
  const broken = [];
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const re = /\\S+/g;
    let m;
    while ((m = re.exec(node.textContent))) {
      const r = document.createRange();
      r.setStart(node, m.index);
      r.setEnd(node, m.index + m[0].length);
      const tops = new Set(Array.from(r.getClientRects()).filter(x => x.width > 0)
        .map(x => Math.round(x.top)));
      if (tops.size > 1) broken.push(m[0]);
    }
  }
  return broken;
}
"""


def _seed_birthday(stack: Stack) -> None:
    today = date.today()
    everyone = ",".join(p["id"] for p in PERSONS)
    record = stored_event(
        "Grandma's birthday", today.isoformat(), (today + timedelta(1)).isoformat(), everyone
    )
    stack.fake.events[FAMILY].append({**record, "allday": True})


@pytest.mark.parametrize(("width", "height"), [(1280, 800), (1440, 900), (1920, 1080), (390, 844)])
def test_a_name_is_not_broken_inside_a_word_and_the_dots_have_their_own_line(
    stack_full: Stack, browser: Browser, width: int, height: int
) -> None:
    _seed_birthday(stack_full)
    try:
        with _device(browser, width, height) as page:
            _open(page, stack_full)
            _view(page, "week")
            # The visible row of the birthday that has the person dots (the week may also keep
            # hidden copies of the same row).
            row = page.locator(".event.allday:visible", has_text="Grandma").filter(
                has=page.locator(".person-dots")
            )
            expect(row.first).to_be_visible(timeout=5000)
            el = row.first.locator(".allday-name")
            assert el.evaluate(WORDS_SPLIT_JS) == [], f"broken inside a word at {width}px"
            dots = el.locator("xpath=..").locator(".person-dots")
            name_box = el.bounding_box()
            dots_box = dots.bounding_box()
            assert name_box and dots_box, "the person dots are not drawn"
            assert dots_box["y"] >= name_box["y"] + name_box["height"] - 2, (
                f"the dots share the line of the name at {width}px"
            )
    finally:
        stack_full.fake.events[FAMILY] = [
            e for e in stack_full.fake.events[FAMILY] if e.get("summary") != "Grandma's birthday"
        ]


@pytest.mark.parametrize("language", ["it", "de", "en"])
@pytest.mark.parametrize("view", ["week", "month", "list"])
def test_the_period_is_one_line_at_1280(
    stack_full: Stack, browser: Browser, language: str, view: str
) -> None:
    stack_full.fake.config["family"] = {
        **stack_full.fake.config.get("family", {}),
        "language": language,
    }
    try:
        with _device(browser, 1280, 800) as page:
            _open(page, stack_full)
            page.goto(stack_full.url + f"/?lang={language}")
            expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=8000)
            _view(page, view)
            period = page.locator("#period-title")
            expect(period).to_be_visible(timeout=3000)
            # The text sits on one line: all its text boxes share one top edge.
            lines = period.evaluate(
                "el => { const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);"
                " const tops = new Set(); let n;"
                " while ((n = w.nextNode())) { const r = document.createRange();"
                " r.selectNodeContents(n);"
                " for (const x of r.getClientRects()) {"
                " if (x.width > 0) tops.add(Math.round(x.top)); } }"
                " return tops.size; }"
            )
            fits = period.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
            text = period.inner_text()
            assert lines == 1 and fits, f"{language}/{view}: {text!r} on {lines} lines"
    finally:
        stack_full.fake.config["family"] = {
            **stack_full.fake.config.get("family", {}),
            "language": "it",
        }
