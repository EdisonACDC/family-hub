"""Times and dates in the event window: typed times are completed, wrong ones are refused on
screen, the touch time picker works, and the date picker shows the day and overlaps."""

from __future__ import annotations

from datetime import date, timedelta

from playwright.sync_api import Page, expect

from tests.e2e.conftest import Stack
from tests.fake_ha import FAMILY, stored_event


def _open_form(page: Page, stack: Stack) -> None:
    page.goto(stack.url + "/?lang=it")
    expect(page.locator(".chip").first).to_be_visible(timeout=5000)
    page.locator("#add-btn").click()
    expect(page.locator("#event-form")).to_be_visible()


def test_typed_digits_become_a_time_when_the_field_is_left(stack_full: Stack, tablet: Page) -> None:
    _open_form(tablet, stack_full)
    start = tablet.locator("#event-form input[name='start_time']")
    start.fill("1030")
    start.press("Tab")
    expect(start).to_have_value("10:30")


def test_a_wrong_time_is_shown_in_red_and_blocks_saving(stack_full: Stack, tablet: Page) -> None:
    _open_form(tablet, stack_full)
    tablet.fill("#event-form input[name='summary']", "Orario sbagliato")
    start = tablet.locator("#event-form input[name='start_time']")
    start.fill("99")
    start.press("Tab")
    expect(start).to_have_attribute("aria-invalid", "true")
    expect(tablet.locator("#event-form input[name='start_time'] + .field-error")).to_be_visible()
    tablet.locator("#event-form button[type='submit']").click()
    expect(tablet.locator("#event-error")).to_be_visible()
    assert not [
        c
        for c in stack_full.fake.calls
        if c["service"] == "add_event" and c["data"].get("summary") == "Orario sbagliato"
    ]


def test_the_touch_time_picker_sets_hour_and_minute(stack_full: Stack, tablet: Page) -> None:
    _open_form(tablet, stack_full)
    start = tablet.locator("#event-form input[name='start_time']")
    start.click()
    picker = tablet.locator(".timepick")
    expect(picker).to_be_visible()
    picker.locator(".timepick-col").nth(0).locator(".timepick-cell", has_text="07").click()
    picker.locator(".timepick-col").nth(1).locator(".timepick-cell", has_text="15").click()
    picker.get_by_role("button", name="Fatto").click()
    expect(start).to_have_value("07:15")


def test_the_date_picker_shows_the_day_and_overlaps(stack_full: Stack, tablet: Page) -> None:
    target = date.today() + timedelta(days=3)
    stack_full.fake.events[FAMILY].append(
        stored_event(
            "Riunione lunga",
            f"{target.isoformat()}T09:00:00",
            f"{target.isoformat()}T10:00:00",
            "mamma",
        )
    )
    _open_form(tablet, stack_full)
    tablet.fill("#event-form input[name='summary']", "Nuovo appuntamento")
    tablet.locator("#event-form input[name='date']").click()
    expect(tablet.locator(".datepick")).to_be_visible()
    tablet.locator(".datepick .day-cell", has_text=str(target.day)).first.click()
    expect(tablet.locator(".datepick")).to_be_hidden()
    expect(tablet.locator("#event-form input[name='date']")).to_have_value(
        target.strftime("%d/%m/%Y")
    )
    tablet.locator("#event-form input[name='start_time']").fill("09:30")
    tablet.locator("#event-form input[name='start_time']").press("Tab")
    expect(tablet.locator("#date-info")).to_contain_text("Si sovrappone a")
    expect(tablet.locator("#date-info")).to_contain_text("Riunione lunga")
