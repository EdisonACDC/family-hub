"""0.7.0: the persons in front (chips that filter every view, dots on the events) and the sound
of the reminders on the phone (Avvisi per person, "Avvisa su" per event)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

from playwright.sync_api import Page, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_tablet import _shot
from tests.fake_ha import FAMILY, SCHOOL, stored_event


@contextmanager
def _two_persons_events(stack: Stack) -> Iterator[None]:
    today = date.today().isoformat()
    mamma = stored_event("Solo Mamma", f"{today} 09:00:00", f"{today} 10:00:00", "mamma")
    sofia = stored_event("Solo Sofia", f"{today} 11:00:00", f"{today} 12:00:00", "sofia")
    family = stored_event("Tutta la famiglia", f"{today} 19:00:00", f"{today} 20:00:00", "")
    stack.fake.events[FAMILY].extend([mamma, family])
    stack.fake.events[SCHOOL].append(sofia)
    try:
        yield
    finally:
        stack.fake.events[FAMILY].remove(mamma)
        stack.fake.events[FAMILY].remove(family)
        stack.fake.events[SCHOOL].remove(sofia)


def _open(page: Page, stack: Stack) -> None:
    page.goto(stack.url + "/?lang=it")
    expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)


def test_person_chips_filter_the_week_and_stay_chosen(stack_full: Stack, tablet: Page) -> None:
    with _two_persons_events(stack_full):
        _open(tablet, stack_full)
        week = tablet.locator("#week")
        expect(week.locator(".event", has_text="Solo Mamma")).to_be_visible(timeout=5000)
        # Each event shows the dots of its persons.
        expect(week.locator(".event", has_text="Solo Mamma").locator(".person-dot")).to_have_count(
            1
        )
        tablet.locator("#persons-bar [data-person='sofia']").click()
        expect(tablet.locator("#persons-bar [data-person='sofia']")).to_have_attribute(
            "aria-pressed", "true"
        )
        expect(week.locator(".event", has_text="Solo Mamma")).to_have_count(0)
        expect(week.locator(".event", has_text="Solo Sofia")).to_be_visible()
        expect(week.locator(".event", has_text="Tutta la famiglia")).to_be_visible()
        _shot(tablet, "layout_persons_filter")
        # The choice stays on this screen.
        tablet.reload()
        expect(tablet.locator("#persons-bar [data-person='sofia']")).to_have_attribute(
            "aria-pressed", "true", timeout=5000
        )
        expect(tablet.locator("#week .event", has_text="Solo Mamma")).to_have_count(0)
        # The list follows the person too.
        tablet.locator("#view-switch [data-view='list']").click()
        expect(tablet.locator("#list-scroll .list-row", has_text="Solo Sofia")).to_be_visible(
            timeout=5000
        )
        expect(tablet.locator("#list-scroll .list-row", has_text="Solo Mamma")).to_have_count(0)
        tablet.locator("#persons-bar [data-person='']").click()
        expect(tablet.locator("#list-scroll .list-row", has_text="Solo Mamma")).to_be_visible()
        tablet.locator("#view-switch [data-view='week']").click()


def test_reminder_sound_in_avvisi_and_in_the_event(stack_full: Stack, tablet: Page) -> None:
    _open(tablet, stack_full)
    tablet.locator("#menu-btn").click()
    tablet.locator("#menu-notify").click()
    card = tablet.locator("#notify-body .notify-card").first
    expect(card).to_be_visible(timeout=5000)
    sound = card.locator("label", has_text="Suono del promemoria").locator("select")
    expect(sound).to_have_value("important")
    expect(card).to_contain_text("Avvisi critici")
    sound.select_option("critical")
    tablet.get_by_role("button", name="Salva avvisi").click()
    expect(tablet.locator("#status-note")).to_contain_text("Avvisi salvati", timeout=3000)
    person_id = card.get_attribute("data-person") or ""
    saved = [p for p in stack_full.fake.config["persons"] if p.get("phone_sound") == "critical"]
    assert saved, (person_id, stack_full.fake.config["persons"])
    tablet.locator("#notify-close").click()

    # "Avvisa su" of one event: the sound can be changed for it.
    tablet.locator("#add-btn").click()
    form = tablet.locator("#event-form")
    form.locator("input[name='summary']").fill("Con suono")
    form.locator("#event-persons label", has_text="Mamma").click()
    notify = tablet.locator("#event-notify")
    phone = notify.locator("label", has_text="Telefono").locator("input")
    if not phone.is_checked():
        notify.locator("label", has_text="Telefono").click()
    select = notify.locator("select[name='phone_sound']")
    expect(select).to_be_visible()
    select.select_option("normal")
    form.locator("button[type='submit']").click()
    expect(tablet.locator("#event-overlay")).to_be_hidden(timeout=3000)
    added = [c["data"] for c in stack_full.fake.calls if c["service"] == "add_event"]
    data = [d for d in added if d.get("summary") == "Con suono"][-1]
    assert data["phone_sound"] == "normal"
    assert "phone" in data["channels"]
