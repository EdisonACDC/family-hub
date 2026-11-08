"""The touch time picker of 0.6.2: its title is the field's name (never the error message), the
time already written is selected, and the column scrolls to it."""

from __future__ import annotations

from playwright.sync_api import Page, expect

from tests.e2e.conftest import Stack


def _open_picker_for(page: Page, stack: Stack, value: str) -> None:
    page.goto(stack.url + "/?lang=it")
    expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
    page.locator("#add-btn").click()
    start = page.locator("#event-form input[name='start_time']")
    start.fill(value)
    start.click()
    expect(page.locator(".timepick")).to_be_visible()


def test_title_is_the_field_name_even_with_an_error_shown(stack_full: Stack, tablet: Page) -> None:
    _open_picker_for(tablet, stack_full, "25:99")
    expect(tablet.locator(".timepick h2")).to_have_text("Inizio")
    assert "non valido" not in (tablet.locator(".timepick h2").text_content() or "")


def test_the_written_time_is_selected_and_in_view(stack_full: Stack, tablet: Page) -> None:
    _open_picker_for(tablet, stack_full, "09:00")
    picker = tablet.locator(".timepick")
    expect(picker.locator(".timepick-col").nth(0).locator(".timepick-cell.on")).to_have_text("09")
    expect(picker.locator(".timepick-col").nth(1).locator(".timepick-cell.on")).to_have_text("00")


def test_a_late_hour_is_scrolled_into_view(stack_full: Stack, tablet: Page) -> None:
    _open_picker_for(tablet, stack_full, "23:45")
    picker = tablet.locator(".timepick")
    hours = picker.locator(".timepick-col").nth(0)
    on = hours.locator(".timepick-cell.on")
    expect(on).to_have_text("23")
    col = hours.bounding_box()
    cell = on.bounding_box()
    assert col and cell
    assert col["y"] - 1 <= cell["y"] and cell["y"] + cell["height"] <= col["y"] + col["height"] + 1
