"""Weather on the screen in a real browser: top bar, day columns, the phone, and guests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack, tablet_as
from tests.helpers import GUEST_USER


@contextmanager
def _phone(browser: Browser) -> Iterator[Page]:
    from tests.helpers import ADULT_USER

    context = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True)
    context.set_extra_http_headers({"X-Remote-User-Id": ADULT_USER})
    page = context.new_page()
    try:
        yield page
    finally:
        context.close()


def test_top_bar_shows_the_weather_now(stack_full: Stack, tablet: Page) -> None:
    tablet.goto(stack_full.url + "/?lang=it")
    expect(tablet.locator("#weather-now")).to_be_visible(timeout=5000)
    expect(tablet.locator("#weather-now")).to_contain_text("5°C")
    expect(tablet.locator("#weather-now")).to_contain_text("Nuvoloso")


def test_day_columns_show_high_and_low_where_there_is_a_forecast(
    stack_full: Stack, tablet: Page
) -> None:
    tablet.goto(stack_full.url + "/?lang=it")
    today = date.today().isoformat()
    column = tablet.locator(f".day[aria-label='{today}']")
    expect(column.locator(".day-weather")).to_be_visible(timeout=5000)
    expect(column.locator(".wx-max")).to_have_text("8°")
    expect(column.locator(".wx-min")).to_have_text("2°")
    # Days without a forecast show no weather at all.
    assert tablet.locator(".day-weather").count() <= 5


def test_phone_shows_today_and_tomorrow_weather(stack_full: Stack, browser: Browser) -> None:
    with _phone(browser) as page:
        page.goto(stack_full.url + "/?lang=it")
        expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
        today = date.today().isoformat()
        expect(page.locator(f".day[aria-label='{today}'] .day-weather")).to_be_visible(timeout=5000)
        # Every day of Giorni with a forecast shows it (the fake has five days).
        expect(page.locator(".week.agenda .day-weather")).to_have_count(5)


def test_guests_see_the_weather_too(stack_full: Stack, browser: Browser) -> None:
    with tablet_as(browser, GUEST_USER) as page:
        page.goto(stack_full.url + "/?lang=it")
        expect(page.locator("#weather-now")).to_be_visible(timeout=5000)
