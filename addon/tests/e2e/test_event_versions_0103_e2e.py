"""0.10.3: simultaneous changes in the panel. The form and the delete send the version they read;
when someone else changed the appointment meanwhile, nothing is overwritten: the person is told
("Questo appuntamento è stato modificato da qualcun altro. Ricarica.") and the screen is
read again."""

from __future__ import annotations

import uuid
from datetime import date

from playwright.sync_api import Page, expect

from tests.e2e.conftest import Stack
from tests.fake_ha import FAMILY, stored_event

CHANGED = "Questo appuntamento è stato modificato da qualcun altro. Ricarica."


def _seed(stack: Stack, summary: str) -> dict[str, object]:
    today = date.today().isoformat()
    event = stored_event(summary, f"{today} 10:00:00", f"{today} 11:00:00", "mamma")
    stack.fake.events[FAMILY].append(event)
    return event


def _open(page: Page, stack: Stack) -> None:
    page.goto(stack.url + "/?lang=it")
    expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)


def _calls(stack: Stack, service: str) -> list[dict[str, object]]:
    return [c["data"] for c in stack.fake.calls if c["service"] == service]


def test_a_change_on_an_old_version_is_refused_and_told(stack_full: Stack, tablet: Page) -> None:
    event = _seed(stack_full, "Visita contesa")
    read = event["version"]
    _open(tablet, stack_full)
    tablet.locator(".event", has_text="Visita contesa").click()
    tablet.locator("#card-foot").get_by_role("button", name="Modifica").click()
    form = tablet.locator("#event-form")
    expect(form).to_be_visible()
    # Someone else changes it while the form is open.
    event["summary"] = "Cambiata da altri"
    event["version"] = uuid.uuid4().hex[:12]
    form.locator("input[name='summary']").fill("La mia modifica")
    form.get_by_role("button", name="Salva").click()
    expect(tablet.locator("#event-error")).to_contain_text(CHANGED)
    assert event["summary"] == "Cambiata da altri"  # nothing was written over it
    # The form sent the version it read, which is not the one the appointment has now.
    sent = _calls(stack_full, "update_event")
    assert sent[-1]["version"] == read and event["version"] != read


def test_a_delete_on_an_old_version_is_refused_and_told(stack_full: Stack, tablet: Page) -> None:
    event = _seed(stack_full, "Da non cancellare")
    _open(tablet, stack_full)
    tablet.locator(".event", has_text="Da non cancellare").click()
    event["version"] = uuid.uuid4().hex[:12]  # someone else changed it
    tablet.locator("#card-foot").get_by_role("button", name="Elimina").click()
    tablet.get_by_role("button", name="Elimina").last.click()
    expect(tablet.locator("#status-note")).to_contain_text(CHANGED)
    assert event in stack_full.fake.events[FAMILY]  # still there


def test_the_version_that_was_read_goes_with_a_change(stack_full: Stack, tablet: Page) -> None:
    event = _seed(stack_full, "Visita tranquilla")
    read = event["version"]
    _open(tablet, stack_full)
    tablet.locator(".event", has_text="Visita tranquilla").click()
    tablet.locator("#card-foot").get_by_role("button", name="Modifica").click()
    form = tablet.locator("#event-form")
    form.locator("input[name='summary']").fill("Visita tranquilla 2")
    form.get_by_role("button", name="Salva").click()
    expect(tablet.locator("#event-overlay")).to_be_hidden(timeout=3000)
    sent = _calls(stack_full, "update_event")
    assert sent[-1]["version"] == read and sent[-1]["summary"] == "Visita tranquilla 2"
