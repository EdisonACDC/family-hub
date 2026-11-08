"""The event card: tap an event to see it, change or delete it (roles apply), external events and
shifts read only, and the buttons of every window stay at the foot."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack, tablet_as
from tests.fake_ha import FAMILY, SCHOOL, WASTE, stored_event
from tests.helpers import ADULT_USER, CHILD_USER, GUEST_USER


@contextmanager
def _phone(browser: Browser) -> Iterator[Page]:
    context = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True)
    context.set_extra_http_headers({"X-Remote-User-Id": ADULT_USER})
    page = context.new_page()
    try:
        yield page
    finally:
        context.close()


def _today() -> str:
    return date.today().isoformat()


def _open(page: Page, stack: Stack) -> None:
    page.goto(stack.url + "/?lang=it")
    expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)


def _seed_mamma_event(stack: Stack, summary: str = "Visita dentista") -> None:
    today = _today()
    stack.fake.events[FAMILY].append(
        stored_event(summary, f"{today} 10:00:00", f"{today} 11:00:00", "mamma")
    )


def _calls(stack: Stack, service: str) -> list[dict[str, object]]:
    return [c["data"] for c in stack.fake.calls if c["service"] == service]


def test_tapping_an_event_opens_its_card_with_edit_and_delete(
    stack_full: Stack, tablet: Page
) -> None:
    _seed_mamma_event(stack_full, "Visita dentista")
    _open(tablet, stack_full)
    tablet.locator(".event", has_text="Visita dentista").click()
    card = tablet.locator("#card-overlay")
    expect(card).to_be_visible()
    expect(card.locator("#card-body .card-title")).to_have_text("Visita dentista")
    expect(card.get_by_role("button", name="Modifica")).to_be_visible()
    expect(card.get_by_role("button", name="Elimina")).to_be_visible()


def test_editing_from_the_card_sends_update_event(stack_full: Stack, tablet: Page) -> None:
    _seed_mamma_event(stack_full, "Visita da modificare")
    _open(tablet, stack_full)
    tablet.locator(".event", has_text="Visita da modificare").click()
    tablet.locator("#card-foot").get_by_role("button", name="Modifica").click()
    form = tablet.locator("#event-form")
    expect(form).to_be_visible()
    expect(form.locator("input[name='summary']")).to_have_value("Visita da modificare")
    expect(form.locator(".switch", has_text="Mamma").locator("input")).to_be_checked()
    form.locator("input[name='summary']").fill("Visita di controllo")
    form.get_by_role("button", name="Salva").click()
    expect(tablet.locator("#event-overlay")).to_be_hidden(timeout=3000)
    updated = _calls(stack_full, "update_event")
    assert updated and updated[-1]["summary"] == "Visita di controllo"
    assert updated[-1]["uid"] == stack_full.fake.events[FAMILY][-1]["record_id"]


def test_deleting_asks_first_in_the_family_hub_window(stack_full: Stack, tablet: Page) -> None:
    _seed_mamma_event(stack_full, "Da cancellare")
    _open(tablet, stack_full)
    tablet.locator(".event", has_text="Da cancellare").click()
    tablet.locator("#card-foot").get_by_role("button", name="Elimina").click()
    expect(tablet.locator("#confirm-overlay")).to_be_visible()
    expect(tablet.locator("#confirm-text")).to_contain_text("Eliminare «Da cancellare»?")
    tablet.get_by_role("button", name="Annulla").click()
    assert not _calls(stack_full, "delete_event")
    tablet.locator("#card-foot").get_by_role("button", name="Elimina").click()
    tablet.get_by_role("button", name="Elimina").last.click()
    expect(tablet.locator("#card-overlay")).to_be_hidden(timeout=3000)
    assert _calls(stack_full, "delete_event")


def test_external_event_card_is_read_only(stack_full: Stack, tablet: Page) -> None:
    today = _today()
    stack_full.fake.events[WASTE].append(
        {
            "summary": "Ritiro indifferenziato",
            "start": f"{today} 07:00:00",
            "end": f"{today} 08:00:00",
            "location": "",
            "record_id": "",
            "shift_id": "",
            "person_ids": "",
        }
    )
    _open(tablet, stack_full)
    tablet.locator(".event.external", has_text="Ritiro indifferenziato").click()
    card = tablet.locator("#card-overlay")
    expect(card).to_be_visible()
    expect(card.get_by_role("button", name="Modifica")).to_have_count(0)
    expect(card).to_contain_text("sola lettura")


def test_guest_card_has_no_buttons(stack_full: Stack, browser: Browser) -> None:
    _seed_mamma_event(stack_full, "Visita ospite")
    with tablet_as(browser, GUEST_USER) as page:
        _open(page, stack_full)
        page.locator(".event", has_text="Visita ospite").click()
        expect(page.locator("#card-overlay")).to_be_visible()
        expect(page.locator("#card-foot").get_by_role("button")).to_have_count(1)  # only Chiudi


def test_child_can_change_only_their_own_events(stack_full: Stack, browser: Browser) -> None:
    today = _today()
    stack_full.fake.events[SCHOOL].append(
        stored_event("Recita di Sofia", f"{today} 11:00:00", f"{today} 12:00:00", "sofia")
    )
    stack_full.fake.events[FAMILY].append(
        stored_event("Visita di mamma", f"{today} 13:00:00", f"{today} 14:00:00", "mamma")
    )
    with tablet_as(browser, CHILD_USER) as page:
        _open(page, stack_full)
        page.locator(".event", has_text="Recita di Sofia").click()
        expect(page.locator("#card-foot").get_by_role("button", name="Modifica")).to_be_visible()
        page.locator("#card-foot").get_by_role("button", name="Chiudi").click()
        expect(page.locator("#card-overlay")).to_be_hidden()


def test_window_buttons_stay_at_the_foot_on_the_phone(stack_full: Stack, browser: Browser) -> None:
    with _phone(browser) as page:
        _open(page, stack_full)
        page.locator("#add-btn").click()
        form = page.locator("#event-form")
        expect(form).to_be_visible()
        foot = form.locator(".dialog-foot").bounding_box()
        assert foot["y"] + foot["height"] <= 844 + 1
        assert form.locator(".dialog-body").evaluate("e => getComputedStyle(e).overflowY") == "auto"
        assert form.evaluate("e => getComputedStyle(e).overflow") == "hidden"
