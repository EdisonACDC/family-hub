"""The top bar shows the next three days of weather, and the week on the tablet starts today
(by default) or on the family's first day when the screen setting is off."""

from __future__ import annotations

from datetime import date, timedelta

from playwright.sync_api import Page, expect

from tests.e2e.conftest import Stack


def _load(page: Page, stack: Stack) -> None:
    page.goto(stack.url + "/?lang=en")
    expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
    expect(page.locator("#week .day")).to_have_count(7)


def test_top_bar_shows_the_next_three_days_beside_the_weather(
    stack_full: Stack, tablet: Page
) -> None:
    _load(tablet, stack_full)
    # On a 1024 px tablet the next three days are in the second row (top bar from 1280 px).
    days = tablet.locator("#weather-days-sub .wx-day")
    expect(days).to_have_count(3, timeout=5000)
    expect(tablet.locator("#weather-days-sub")).to_be_visible()
    expect(days.first.locator(".wx-day-name")).not_to_be_empty()
    expect(days.first.locator(".wx-max")).to_contain_text("°")
    expect(days.first.locator("svg")).to_be_attached()
    # The current weather is still there, next to them.
    expect(tablet.locator("#weather-now")).to_be_visible()


def test_week_starts_today_and_the_arrows_move_seven_days(stack_full: Stack, tablet: Page) -> None:
    _load(tablet, stack_full)
    today = date.today()
    columns = tablet.locator("#week .day")
    expect(columns.first).to_have_attribute("aria-label", today.isoformat())
    expect(columns.nth(6)).to_have_attribute("aria-label", (today + timedelta(days=6)).isoformat())

    tablet.locator("#next-week").click()
    expect(columns.first).to_have_attribute("aria-label", (today + timedelta(days=7)).isoformat())
    expect(columns.nth(6)).to_have_attribute("aria-label", (today + timedelta(days=13)).isoformat())

    tablet.locator("#this-week").click()
    expect(columns.first).to_have_attribute("aria-label", today.isoformat())


def test_week_can_start_on_the_family_first_day(stack_full: Stack, tablet: Page) -> None:
    fake = stack_full.fake
    fake.config["screen"]["week_from_today"] = False
    try:
        _load(tablet, stack_full)
        today = date.today()
        first_day = fake.config["family"].get("first_weekday", "monday")
        offset = (today.weekday() + 1) % 7 if first_day == "sunday" else today.weekday()
        start = today - timedelta(days=offset)
        expect(tablet.locator("#week .day").first).to_have_attribute(
            "aria-label", start.isoformat()
        )
        # "Oggi" goes back to the week of today, which here starts on the family's first day.
        tablet.locator("#next-week").click()
        tablet.locator("#this-week").click()
        expect(tablet.locator("#week .day").first).to_have_attribute(
            "aria-label", start.isoformat()
        )
    finally:
        fake.config["screen"]["week_from_today"] = True
