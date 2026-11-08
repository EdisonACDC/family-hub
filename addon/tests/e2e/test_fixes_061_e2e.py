"""Fixes for 0.6.1 in the browser: the new-event title, the overlap warning that ignores the event
being edited, the time picker's foot, and the "Altri calendari" chip's contrast."""

from __future__ import annotations

from datetime import date

from playwright.sync_api import Page, expect

from tests.e2e.conftest import Stack
from tests.fake_ha import FAMILY, stored_event


def _seed(stack: Stack) -> None:
    today = date.today().isoformat()
    stack.fake.events[FAMILY].append(
        stored_event("Visita dentista", f"{today} 10:00:00", f"{today} 11:00:00", "mamma")
    )


def _open(page: Page, stack: Stack) -> None:
    page.goto(stack.url + "/?lang=it")
    expect(page.locator(".chip").first).to_be_visible(timeout=5000)


def test_new_event_title_is_translated(stack_full: Stack, tablet: Page) -> None:
    _open(tablet, stack_full)
    tablet.locator("#add-btn").click()
    expect(tablet.locator("#event-title")).to_have_text("Nuovo evento")


def test_overlap_warning_names_other_events_but_not_the_one_being_edited(
    stack_full: Stack, tablet: Page
) -> None:
    _seed(stack_full)
    _open(tablet, stack_full)
    tablet.locator(".event", has_text="Visita dentista").click()
    tablet.locator("#card-foot").get_by_role("button", name="Modifica").click()
    form = tablet.locator("#event-form")
    expect(tablet.locator("#date-info")).to_contain_text("Visita dentista")
    form.locator("input[name='start_time']").fill("10:30")
    form.locator("input[name='end_time']").fill("10:45")
    # The event is not in conflict with itself: no overlap line.
    expect(tablet.locator("#date-info .day-warning")).to_have_count(0)

    # A new event at the same time does conflict with it: the warning names it.
    tablet.locator("#event-overlay button", has_text="Annulla").first.click()
    tablet.locator("#add-btn").click()
    tablet.locator("#event-form input[name='start_time']").fill("10:30")
    tablet.locator("#event-form input[name='end_time']").fill("10:45")
    expect(tablet.locator("#date-info .day-warning")).to_contain_text("Visita dentista")


def test_time_picker_has_its_title_and_buttons_below_the_columns(
    stack_full: Stack, tablet: Page
) -> None:
    _open(tablet, stack_full)
    tablet.locator("#add-btn").click()
    start = tablet.locator("#event-form input[name='start_time']")
    start.click()
    picker = tablet.locator(".timepick")
    expect(picker).to_be_visible()
    expect(picker.locator("h2")).not_to_be_empty()
    columns = picker.locator(".timepick-columns").bounding_box()
    done = picker.get_by_role("button", name="Fatto").bounding_box()
    cancel = picker.get_by_role("button", name="Annulla").bounding_box()
    assert columns and done and cancel
    columns_bottom = columns["y"] + columns["height"]
    assert done["y"] >= columns_bottom - 1, "Fatto must sit below the columns, not over them"
    assert cancel["y"] >= columns_bottom - 1, "Annulla must sit below the columns"


def test_altri_calendari_chip_is_readable_not_faded(stack_full: Stack, tablet: Page) -> None:
    _open(tablet, stack_full)
    toggle = tablet.locator(".more-toggle")
    expect(toggle).to_be_visible()
    style = toggle.evaluate(
        "e => ({opacity: getComputedStyle(e).opacity, color: getComputedStyle(e).color})"
    )
    assert style["opacity"] == "1"
    channels = [int(v) for v in style["color"][style["color"].index("(") + 1 : -1].split(",")[:3]]
    # WCAG contrast of the text against the light pill (about white).
    lum = 0.0
    for value, weight in zip(channels, (0.2126, 0.7152, 0.0722), strict=True):
        c = value / 255
        lum += weight * (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    contrast = 1.05 / (lum + 0.05)
    assert contrast >= 4.5, f"contrast {contrast:.2f} is below 4.5:1"
