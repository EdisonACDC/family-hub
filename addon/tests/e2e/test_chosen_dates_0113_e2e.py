"""0.11.0b3: an ordinary appointment has no "Date scelte" line and no choice of dates when it is
deleted or changed (Home Assistant's "False" is not "True"). An adult can list only the private
appointments, to check them. A time in a date row is shown whole, on the tablet and the phone."""

from __future__ import annotations

import re
from datetime import date

from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack, tablet_as
from tests.e2e.test_layout_071_e2e import _open, _view
from tests.e2e.test_tablet import _device
from tests.fake_ha import FAMILY, stored_event
from tests.helpers import ADULT_USER

ORDINARY = "Visita normale"
PRIVATE = "Colloquio riservato"


def _seed(stack: Stack, private_title: str | None = None) -> None:
    today = date.today().isoformat()
    stack.fake.events[FAMILY][:] = [
        stored_event(ORDINARY, f"{today} 10:00:00", f"{today} 11:00:00", "mamma"),
    ]
    if private_title:
        record = stored_event(private_title, f"{today} 15:00:00", f"{today} 16:00:00", "mamma")
        record["private"] = True
        stack.fake.events[FAMILY].append(record)
    stack.fake.guest.update({"invites": [], "devices": [], "pending": [], "log": []})
    stack.fake.calls.clear()


def _fit(page: Page, selector: str) -> str:
    """Empty when the field's text fits; otherwise the numbers (text width, room, field width)."""
    report = page.locator(selector).first.evaluate(
        """e => {
            const cs = getComputedStyle(e);
            const ctx = document.createElement('canvas').getContext('2d');
            ctx.font = cs.fontWeight + ' ' + cs.fontSize + ' ' + cs.fontFamily;
            const need = ctx.measureText(e.value).width;
            const room = e.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
            return {need, room, width: e.clientWidth, font: ctx.font,
                    value: e.value};
        }"""
    )
    if report["need"] <= report["room"]:
        return ""
    return f"{report}"


def test_an_ordinary_appointment_has_no_dates_line_and_no_choice_of_dates(
    stack_full: Stack, browser: Browser
) -> None:
    _seed(stack_full)
    with _device(browser, 1280, 800) as page:
        _open(page, stack_full)
        _view(page, "week")
        page.locator(".event", has_text=ORDINARY).first.click()
        expect(page.locator("#card-overlay")).to_be_visible(timeout=3000)
        expect(page.locator(".card-chosen")).to_have_count(0)
        page.locator("#card-foot button", has_text=re.compile("Elimina|Delete|Löschen")).click()
        # One question for one appointment: no choice of dates, no "Solo questo" or "Tutti".
        expect(page.locator("#scope-overlay")).to_be_hidden(timeout=3000)
        expect(page.locator("#scope-all")).to_be_hidden()


def test_an_ordinary_appointment_has_no_choice_of_dates_in_the_form(
    stack_full: Stack, browser: Browser
) -> None:
    _seed(stack_full)
    with _device(browser, 1280, 800) as page:
        _open(page, stack_full)
        _view(page, "week")
        page.locator(".event", has_text=ORDINARY).first.click()
        expect(page.locator("#card-overlay")).to_be_visible(timeout=3000)
        page.locator("#card-foot button", has_text=re.compile("Modifica|Edit|Bearbeiten")).click()
        expect(page.locator("#event-form")).to_be_visible(timeout=3000)
        expect(page.locator("#event-scope")).to_be_hidden()
        expect(page.locator("#chosen-box")).to_be_hidden()


def test_adults_can_list_only_the_private_appointments(stack_full: Stack, browser: Browser) -> None:
    _seed(stack_full, private_title=PRIVATE)
    with tablet_as(browser, ADULT_USER) as page:
        _open(page, stack_full)
        _view(page, "list")
        expect(page.locator("#list-scroll")).to_be_visible(timeout=5000)
        everything = page.locator(".list-row").count()
        assert page.locator(".list-row", has_text=ORDINARY).count() == 1
        assert page.locator(".list-row", has_text=PRIVATE).count() == 1
        switch = page.locator("label.switch", has_text="Solo privati").locator("input")
        switch.check()
        expect(page.locator(".list-row", has_text=ORDINARY)).to_have_count(0)
        expect(page.locator(".list-row", has_text=PRIVATE)).to_have_count(1)
        # Only the private ones are listed: fewer rows than the whole list (the others are gone).
        assert page.locator(".list-row").count() < everything
        switch.uncheck()
        expect(page.locator(".list-row", has_text=ORDINARY)).to_have_count(1)
        expect(page.locator(".list-row")).to_have_count(everything)


def test_a_time_in_a_date_row_is_shown_whole_on_the_tablet_and_the_phone(
    stack_full: Stack, browser: Browser
) -> None:
    _seed(stack_full)
    for width, height in [(1150, 800), (390, 844)]:
        with _device(browser, width, height) as page:
            _open(page, stack_full)
            page.locator("#add-btn").click()
            form = page.locator("#event-form")
            expect(form).to_be_visible(timeout=3000)
            form.locator("input[name='summary']").fill("Recita di Natale")
            form.locator("input[name='date']").fill("14/11/2026")
            form.locator("#repeat-kind").select_option("chosen")
            expect(page.locator("#chosen-box")).to_be_visible(timeout=3000)
            month_next = page.locator("#chosen-box .month-nav button", has_text="→")
            month_next.click()
            page.locator("#chosen-box .chosen-grid .day-cell", has_text=re.compile(r"^22$")).click()
            rows = page.locator("#chosen-box .chosen-row")
            expect(rows).to_have_count(2)
            for index in range(2):
                for name in ("start", "end"):
                    row = f"#chosen-box .chosen-row >> nth={index} >> .chosen-{name}"
                    cut = _fit(page, row)
                    assert not cut, f"{name} of row {index} is cut at {width} px: {cut}"


def test_a_date_is_one_line_in_the_form_on_a_pc_panel_of_1150_px(
    stack_full: Stack, browser: Browser
) -> None:
    """The panel is about 1150 px wide in Chrome: the times and the switch are on the date's line,
    and the switch is inside the form (not pushed out of it)."""
    _seed(stack_full)
    with _device(browser, 1150, 800) as page:
        _open(page, stack_full)
        page.locator("#add-btn").click()
        form = page.locator("#event-form")
        expect(form).to_be_visible(timeout=3000)
        form.locator("input[name='summary']").fill("Recita di Natale")
        form.locator("input[name='date']").fill("14/11/2026")
        form.locator("#repeat-kind").select_option("chosen")
        expect(page.locator("#chosen-box")).to_be_visible(timeout=3000)
        page.locator("#chosen-box .month-nav button", has_text="→").click()
        page.locator("#chosen-box .chosen-grid .day-cell", has_text=re.compile(r"^22$")).click()
        row = page.locator("#chosen-box .chosen-row").nth(1)
        expect(row).to_be_visible(timeout=3000)
        start = row.locator(".chosen-start").bounding_box()
        switch = row.locator(".chosen-allday").bounding_box()
        dialog = page.locator("#event-overlay .dialog").bounding_box()
        assert start and switch and dialog
        assert abs(switch["y"] + switch["height"] / 2 - (start["y"] + start["height"] / 2)) < 12
        assert switch["x"] + switch["width"] <= dialog["x"] + dialog["width"], "switch inside form"
