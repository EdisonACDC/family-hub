"""Notifications per event ("Avvisa su"), the Alexa volume slider, and the month's person filter.

- The form shows "Avvisa su" filled in from the chosen persons; if left alone, the event is saved
  without channels (the persons' own settings apply); if changed, the channels, the Echo and
  the volume go with the event, and the card shows them.
- The volume slider is never disabled: touching it turns "predefinito" off; turning
  "predefinito" on greys the slider again. The value is shown in %.
- The month's person filter has no empty extra option.
"""

from __future__ import annotations

from datetime import date

from playwright.sync_api import Page, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_tablet import _shot
from tests.fake_ha import FAMILY, stored_event


def _open(page: Page, stack: Stack) -> None:
    page.goto(stack.url + "/?lang=it")
    expect(page.locator(".chip").first).to_be_visible(timeout=5000)


def _added(stack: Stack, summary: str) -> dict[str, object]:
    calls = [c["data"] for c in stack.fake.calls if c["service"] == "add_event"]
    found = [c for c in calls if c.get("summary") == summary]
    assert found, calls
    return found[-1]


def test_untouched_notify_section_keeps_the_persons_settings(
    stack_full: Stack, tablet: Page
) -> None:
    _open(tablet, stack_full)
    tablet.locator("#add-btn").click()
    form = tablet.locator("#event-form")
    form.locator("input[name='summary']").fill("Senza avvisi propri")
    form.locator("#event-persons label", has_text="Mamma").click()
    notify = tablet.locator("#event-notify")
    expect(notify).to_be_visible(timeout=5000)
    expect(notify).to_contain_text("Avvisa su")
    form.locator("button[type='submit']").click()
    expect(tablet.locator("#event-overlay")).to_be_hidden(timeout=3000)
    data = _added(stack_full, "Senza avvisi propri")
    assert "channels" not in data and "alexa_target" not in data


def test_event_notify_is_saved_and_shown_on_the_card(stack_full: Stack, tablet: Page) -> None:
    _open(tablet, stack_full)
    tablet.locator("#add-btn").click()
    form = tablet.locator("#event-form")
    form.locator("input[name='summary']").fill("Dentista Sofia")
    form.locator("#event-persons label", has_text="Sofia").click()
    notify = tablet.locator("#event-notify")
    expect(notify).to_be_visible(timeout=5000)
    phone = notify.locator("label", has_text="Telefono").locator("input")
    alexa = notify.locator("label", has_text="Alexa").first.locator("input")
    tablet_switch = notify.locator("label", has_text="Finestra sul tablet").locator("input")
    if phone.is_checked():
        notify.locator("label", has_text="Telefono").click()
    if not alexa.is_checked():
        notify.locator("label", has_text="Alexa").first.click()
    if tablet_switch.is_checked():
        notify.locator("label", has_text="Finestra sul tablet").click()
    echo = notify.locator("select[name='alexa_target']")
    expect(echo).to_be_visible()
    options = echo.locator("option").evaluate_all("os => os.map(o => o.value)")
    assert "all" in options and len(options) >= 3, options
    echo.select_option(options[-1])
    slider = notify.locator("input[type='range']")
    slider.fill("80")
    expect(notify.locator(".volume-value")).to_have_text("80 %")
    _shot(tablet, "tablet_event_notify")
    form.locator("button[type='submit']").click()
    expect(tablet.locator("#event-overlay")).to_be_hidden(timeout=3000)
    data = _added(stack_full, "Dentista Sofia")
    assert data["channels"] == ["alexa"]
    assert data["alexa_target"] == options[-1]
    assert data["alexa_volume"] == 80

    # The card says where the reminders go.
    tablet.locator(".event", has_text="Dentista Sofia").first.click()
    line = tablet.locator("#card-body .card-notify")
    expect(line).to_contain_text("Avvisa su: Alexa")
    expect(line).to_contain_text("80%")


def test_card_shows_phone_alexa_name_and_volume(stack_full: Stack, tablet: Page) -> None:
    today = date.today().isoformat()
    event = stored_event("Riunione", f"{today} 18:00:00", f"{today} 19:00:00", "mamma")
    event["notify"] = "phone,alexa|all|80"
    stack_full.fake.events[FAMILY].append(event)
    try:
        _open(tablet, stack_full)
        tablet.locator(".event", has_text="Riunione").first.click()
        expect(tablet.locator("#card-body .card-notify")).to_have_text(
            "Avvisa su: Telefono · Alexa Tutti gli Echo 80%"
        )
    finally:
        stack_full.fake.events[FAMILY].remove(event)


def test_volume_slider_turns_default_off_and_shows_percent(stack_full: Stack, tablet: Page) -> None:
    _open(tablet, stack_full)
    tablet.locator("#menu-btn").click()
    tablet.locator("#menu-notify").click()
    card = tablet.locator("#notify-body .notify-card").first
    expect(card).to_be_visible(timeout=5000)
    volume = card.locator(".volume")
    default = volume.locator("label", has_text="predefinito").locator("input")
    if not default.is_checked():
        volume.locator("label", has_text="predefinito").click()
    expect(volume).to_have_class("volume is-default")
    slider = volume.locator("input[type='range']")
    assert slider.is_enabled()
    box = slider.bounding_box()
    assert box
    tablet.mouse.click(box["x"] + box["width"] * 0.9, box["y"] + box["height"] / 2)
    expect(default).not_to_be_checked()
    expect(volume).not_to_have_class("volume is-default")
    expect(volume.locator(".volume-value")).to_contain_text("%")
    value = int(slider.input_value())
    assert value >= 80, value
    volume.locator("label", has_text="predefinito").click()
    expect(volume).to_have_class("volume is-default")


def test_month_person_filter_has_no_empty_extra_option(stack_full: Stack, tablet: Page) -> None:
    _open(tablet, stack_full)
    tablet.locator("#view-switch [data-view='month']").click()
    options = tablet.locator("#month-person option")
    expect(options.first).to_be_attached(timeout=5000)
    values = options.evaluate_all("os => os.map(o => o.value)")
    assert values[0] == ""  # "Tutti"
    assert all(values[1:]) and "undefined" not in values, values
    assert len(values) == len(set(values))
    tablet.locator("#view-switch [data-view='week']").click()
