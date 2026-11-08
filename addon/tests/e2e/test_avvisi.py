"""End-to-end tests of the "Avvisi" page (notifications per person) in a real browser:
tablet, phone, and the roles. The fake Home Assistant records what the add-on asked for."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack, tablet_as
from tests.fake_ha import FAMILY, stored_event
from tests.helpers import ADULT_USER, CHILD_USER, GUEST_USER


@contextmanager
def _phone(browser: Browser, user: str = ADULT_USER) -> Iterator[Page]:
    context = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True)
    context.set_extra_http_headers({"X-Remote-User-Id": user})
    page = context.new_page()
    try:
        yield page
    finally:
        context.close()


def _open_notify(page: Page, stack: Stack) -> None:
    page.goto(stack.url + "/?lang=it")
    expect(page.locator(".chip").first).to_be_visible(timeout=5000)
    page.locator("#menu-btn").click()
    page.locator("#menu-notify").click()
    expect(page.locator("#notify-overlay")).to_be_visible()


def _card(page: Page, name: str):  # type: ignore[no-untyped-def]
    return page.locator(".notify-card", has=page.locator("h3", has_text=name))


def test_adult_sets_phone_echo_channels_and_volume(stack_full: Stack, tablet: Page) -> None:
    stack_full.fake.config["persons"][1].pop("phone_notify", None)
    _open_notify(tablet, stack_full)
    mamma = _card(tablet, "Mamma")
    mamma.locator("select").nth(1).select_option("mobile_app_mamma")
    mamma.locator("select").nth(2).select_option("all")
    # The volume slider: 40 %.
    mamma.locator("input[type='range']").evaluate(
        "(el) => { el.value = '40'; el.dispatchEvent(new Event('input', { bubbles: true })); }"
    )
    expect(mamma.locator(".volume-value")).to_have_text("40 %")
    mamma.locator(".switch", has_text="Finestra sul tablet").locator("input").uncheck()
    tablet.get_by_role("button", name="Salva avvisi").click()
    expect(tablet.locator("#status-note")).to_contain_text("Avvisi salvati", timeout=3000)
    saved = stack_full.fake.config["persons"][1]
    assert saved["phone_notify"] == "mobile_app_mamma"
    assert saved["alexa_notify"] == "all"
    assert saved["alexa_volume"] == 40
    assert "tablet" not in saved["channels"]


def test_unknown_phone_is_refused_on_screen(stack_full: Stack, tablet: Page) -> None:
    _open_notify(tablet, stack_full)
    mamma = _card(tablet, "Mamma")
    # A phone service that Home Assistant does not have (set in the page, as if it had vanished).
    mamma.locator("select").nth(1).evaluate(
        "(s) => { const o = document.createElement('option'); o.value = 'mobile_app_nessuno';"
        " o.textContent = 'x'; s.appendChild(o); s.value = 'mobile_app_nessuno';"
        " s.dispatchEvent(new Event('change')); }"
    )
    tablet.get_by_role("button", name="Salva avvisi").click()
    expect(tablet.locator("#notify-error")).to_contain_text("non esiste più", timeout=3000)
    assert "phone_notify" not in str(stack_full.fake.config["persons"][1]) or (
        stack_full.fake.config["persons"][1].get("phone_notify") != "mobile_app_nessuno"
    )


def test_test_message_goes_to_the_chosen_phone_only(stack_full: Stack, tablet: Page) -> None:
    stack_full.fake.config["persons"][1]["phone_notify"] = "mobile_app_mamma"
    _open_notify(tablet, stack_full)
    _card(tablet, "Mamma").get_by_role("button", name="Invia avviso di prova al telefono").click()
    expect(tablet.locator("#status-note")).to_contain_text("Prova inviata a 1", timeout=3000)
    assert stack_full.fake.notify_tests[-1]["person"] == "mamma"
    assert stack_full.fake.notify_tests[-1]["kind"] == "phone"


def test_child_sees_only_their_own_card(stack_full: Stack, browser: Browser) -> None:
    with tablet_as(browser, CHILD_USER) as page:
        _open_notify(page, stack_full)
        expect(page.locator(".notify-card")).to_have_count(1)
        expect(page.locator(".notify-card h3")).to_have_text("Sofia")
        expect(page.locator(".notify-card", has_text="Utente")).to_have_count(0)


def test_guest_has_no_notifications_entry(stack_full: Stack, browser: Browser) -> None:
    with tablet_as(browser, GUEST_USER) as page:
        page.goto(stack_full.url + "/?lang=it")
        expect(page.locator(".chip").first).to_be_visible(timeout=5000)
        expect(page.locator("#menu-btn")).to_be_hidden()


def test_quiet_hours_follow_the_twelve_hour_clock(stack_full: Stack, tablet: Page) -> None:
    family = stack_full.fake.config["family"]
    original = family["time_format"]
    family["time_format"] = "12h"
    stack_full.fake.config["persons"][1]["quiet_start"] = "22:00"
    try:
        _open_notify(tablet, stack_full)
        start = _card(tablet, "Mamma").get_by_label("Silenzio dalle")
        expect(start).to_have_value("10:00 PM")
    finally:
        family["time_format"] = original
        stack_full.fake.config["persons"][1].pop("quiet_start", None)


def test_notifications_work_on_the_phone(stack_full: Stack, browser: Browser) -> None:
    with _phone(browser) as page:
        _open_notify(page, stack_full)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        expect(_card(page, "Mamma")).to_be_visible()
        page.locator("#notify-close").click()
        expect(page.locator("#notify-overlay")).to_be_hidden()


def test_event_form_shows_times_in_the_family_clock_and_dates_as_day_first(
    stack_full: Stack, tablet: Page
) -> None:
    family = stack_full.fake.config["family"]
    original = family["time_format"]
    family["time_format"] = "12h"
    try:
        tablet.goto(stack_full.url + "/?lang=it")
        expect(tablet.locator(".chip").first).to_be_visible(timeout=5000)
        tablet.locator("#add-btn").click()
        expect(tablet.locator("input[name='start_time']")).to_have_value("09:00 AM")
        expect(tablet.locator("input[name='end_time']")).to_have_value("10:00 AM")
        assert tablet.locator("input[name='date']").input_value().count("/") == 2
    finally:
        family["time_format"] = original


def test_default_volume_sends_no_volume_and_labels_are_plain(
    stack_full: Stack, tablet: Page
) -> None:
    stack_full.fake.config["persons"][1]["alexa_volume"] = 30
    stack_full.fake.config["persons"][1]["alexa_notify"] = "media_player.kueche"
    _open_notify(tablet, stack_full)
    mamma = _card(tablet, "Mamma")
    expect(mamma.get_by_text("Utente Home Assistant", exact=False)).to_be_visible()
    expect(mamma.locator("label", has_text="Echo")).to_be_visible()
    expect(mamma.locator("label", has_text="(ID)")).to_have_count(0)
    expect(mamma.locator("label", has_text="notify.")).to_have_count(0)
    mamma.locator(".switch", has_text="predefinito").locator("input").check()
    expect(mamma.locator("input[type='range']")).to_be_disabled()
    tablet.get_by_role("button", name="Salva avvisi").click()
    expect(tablet.locator("#status-note")).to_contain_text("Avvisi salvati", timeout=3000)
    assert stack_full.fake.config["persons"][1].get("alexa_volume") is None


def test_quiet_hours_start_empty_with_a_hint(stack_full: Stack, tablet: Page) -> None:
    stack_full.fake.config["persons"][1].pop("quiet_start", None)
    _open_notify(tablet, stack_full)
    mamma = _card(tablet, "Mamma")
    start = mamma.get_by_label("Silenzio dalle")
    end = mamma.get_by_label("alle", exact=True)
    expect(start).to_have_value("")
    expect(start).to_have_attribute("placeholder", "22:00")
    expect(end).to_have_attribute("placeholder", "07:00")
    expect(mamma.locator(".hint", has_text="22:00 – 07:00")).to_be_visible()


def test_no_event_text_leaves_its_pill(stack_full: Stack, tablet: Page) -> None:
    from datetime import date

    today = date.today().isoformat()
    stack_full.fake.events[FAMILY].append(
        stored_event(
            "Compleanno di Würzburg, festa lunghissima", f"{today} 10:00:00", f"{today} 11:00:00"
        )
    )
    tablet.goto(stack_full.url + "/?lang=it")
    expect(tablet.locator(".event", has_text="Würzburg")).to_be_visible(timeout=5000)
    overflowing = tablet.evaluate(
        "[...document.querySelectorAll('.event')]"
        ".filter(e => e.scrollWidth > e.clientWidth + 1).length"
    )
    assert overflowing == 0


def test_menu_opens_under_the_menu_button_with_big_entries(stack_full: Stack, tablet: Page) -> None:
    _open_notify(tablet, stack_full)
    tablet.locator("#notify-close").click()
    tablet.locator("#menu-btn").click()
    menu = tablet.locator("#menu")
    expect(menu).to_be_visible()
    box = menu.bounding_box()
    bar = tablet.locator(".topbar").bounding_box()
    button = tablet.locator("#menu-btn").bounding_box()
    assert box["y"] >= bar["y"] + bar["height"] - 1
    assert box["y"] >= button["y"] + button["height"] - 1
    heights = tablet.evaluate(
        "[...document.querySelectorAll('#menu .btn')].map(e => e.getBoundingClientRect().height)"
    )
    assert heights and min(heights) >= 48
    expect(tablet.locator("#menu .switch-row", has_text="Riduci trasparenza")).to_be_visible()


def test_channel_rows_have_text_left_and_switch_right(stack_full: Stack, tablet: Page) -> None:
    _open_notify(tablet, stack_full)
    row = tablet.locator("#notify-body .notify-card").first.locator(".switch-row").first
    text = row.locator("span").bounding_box()
    switch = row.locator("input").bounding_box()
    assert abs(text["y"] - switch["y"]) < 20
    assert switch["x"] > text["x"] + text["width"]


def test_event_form_fields_stay_inside_the_dialog_on_the_phone(
    stack_full: Stack, browser: Browser
) -> None:
    with _phone(browser) as page:
        page.goto(stack_full.url + "/?lang=it")
        expect(page.locator(".chip").first).to_be_visible(timeout=5000)
        page.locator("#add-btn").click()
        dialog = page.locator("#event-form").bounding_box()
        for name in ("date", "start_time", "end_time"):
            field = page.locator(f"#event-form input[name='{name}']").bounding_box()
            assert field["x"] + field["width"] <= dialog["x"] + dialog["width"] + 1, name
            assert field["x"] >= dialog["x"] - 1, name


def test_switch_rows_are_ios_switches_and_clicking_the_row_toggles(
    stack_full: Stack, tablet: Page
) -> None:
    _open_notify(tablet, stack_full)
    row = tablet.locator("#notify-body .notify-card").first.locator(".switch-row").first
    switch = row.locator("input")
    assert switch.evaluate("e => getComputedStyle(e).appearance") == "none"
    assert switch.bounding_box()["width"] == 51
    before = switch.is_checked()
    row.click()
    assert switch.is_checked() != before
    expect(switch).to_have_attribute("aria-checked", "true" if not before else "false")


def test_all_day_is_one_switch_row_in_the_event_form(stack_full: Stack, tablet: Page) -> None:
    tablet.goto(stack_full.url + "/?lang=it")
    expect(tablet.locator(".chip").first).to_be_visible(timeout=5000)
    tablet.locator("#add-btn").click()
    row = tablet.locator("#event-form .check")
    expect(row).to_be_visible()
    assert row.locator("input").evaluate("e => getComputedStyle(e).appearance") == "none"
    text = row.locator("span").bounding_box()
    switch = row.locator("input").bounding_box()
    assert switch["x"] > text["x"] + text["width"]
    assert row.locator("span").bounding_box()["height"] < 30
    row.click()
    assert row.locator("input").is_checked()


@contextmanager
def _viewport(browser: Browser, width: int, height: int) -> Iterator[Page]:
    context = browser.new_context(viewport={"width": width, "height": height}, has_touch=True)
    context.set_extra_http_headers({"X-Remote-User-Id": ADULT_USER})
    page = context.new_page()
    try:
        yield page
    finally:
        context.close()


def test_events_stay_in_order_after_a_new_one_at_14_00(stack_full: Stack, browser: Browser) -> None:
    from datetime import date

    today = date.today().isoformat()
    # Only these two events today: the others of this module are set aside.
    stack_full.fake.events[FAMILY] = [
        e for e in stack_full.fake.events[FAMILY] if not e["start"].startswith(today)
    ]
    # The morning event is stored in ISO form, the new one in the form the add-on writes.
    stack_full.fake.events[FAMILY].append(
        stored_event("Mercato", f"{today}T09:00:00", f"{today}T10:00:00")
    )
    stack_full.fake.events[FAMILY].append(
        stored_event("Gita a Würzburg", f"{today} 14:00:00", f"{today} 15:00:00")
    )
    expected = ["Mercato", "Gita a Würzburg"]
    day = f".day[aria-label='{today}'] .ev-title"

    with _viewport(browser, 1024, 768) as page:
        page.goto(stack_full.url + "/?lang=it")
        expect(page.locator(".event", has_text="Gita a Würzburg")).to_be_visible(timeout=5000)
        assert page.locator(day).all_text_contents() == expected

    with _phone(browser) as page:
        page.goto(stack_full.url + "/?lang=it")
        expect(page.locator(".event", has_text="Gita a Würzburg")).to_be_visible(timeout=5000)
        titles = page.locator(".week.agenda .day").first.locator(".ev-title").all_text_contents()
        assert titles == expected

    with _viewport(browser, 1280, 800) as page:
        page.goto(stack_full.url + "/?lang=it")
        expect(page.locator(".upcoming .event", has_text="Gita a Würzburg")).to_be_visible(
            timeout=5000
        )
        titles = page.locator(".upcoming-day").first.locator(".ev-title").all_text_contents()
        assert titles == expected


def test_all_day_switch_sits_at_the_right_end_of_its_row(stack_full: Stack, tablet: Page) -> None:
    tablet.goto(stack_full.url + "/?lang=it")
    expect(tablet.locator(".chip").first).to_be_visible(timeout=5000)
    tablet.locator("#add-btn").click()
    row = tablet.locator("#event-form .check").bounding_box()
    switch = tablet.locator("#event-form .check input").bounding_box()
    assert abs((row["x"] + row["width"]) - (switch["x"] + switch["width"])) < 4


def test_reduce_transparency_is_a_row_with_the_switch_on_the_right(
    stack_full: Stack, tablet: Page
) -> None:
    tablet.goto(stack_full.url + "/?lang=it")
    expect(tablet.locator(".chip").first).to_be_visible(timeout=5000)
    tablet.locator("#menu-btn").click()
    row = tablet.locator("#menu .switch-row").first
    text = row.locator("span").bounding_box()
    switch = row.locator("input").bounding_box()
    assert switch["x"] > text["x"] + text["width"]
    row.click()
    expect(tablet.locator("body")).to_have_class("reduce-transparency")
