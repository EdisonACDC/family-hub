"""End-to-end tests of the wall-tablet layout (1024 x 768, touch), in a real browser.

Home Assistant is replaced by tests/fake_ha.py; the add-on server and the page are real.
Set FH_SCREENSHOTS to a folder to save a screenshot of each main view there.
"""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack, tablet_as
from tests.fake_ha import FAMILY, SCHOOL, SHOP, WASTE, stored_event
from tests.helpers import ADULT_USER, CHILD_USER, GUEST_USER


def _local_iso(day: date, hour: int, minute: int = 0) -> str:
    moment = datetime(day.year, day.month, day.day, hour, minute).astimezone()
    return moment.isoformat()


def _shot(page: Page, name: str) -> None:
    folder = os.environ.get("FH_SCREENSHOTS")
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(folder) / f"{name}.png"))


def _seen_calls(stack: Stack, service: str) -> list[dict[str, Any]]:
    return [c for c in stack.fake.calls if c["service"] == service]


def _wait_for_call(stack: Stack, service: str, timeout: float = 3.0) -> dict[str, Any]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        calls = _seen_calls(stack, service)
        if calls:
            return calls[-1]
        time.sleep(0.02)
    raise AssertionError(f"Home Assistant did not receive {service}")


def _push(stack: Stack, event_type: str, data: dict[str, Any]) -> None:
    stack.run(stack.fake.push_event(event_type, data))


def test_week_view_loads_fast_and_fits_the_tablet(stack_full: Stack, tablet: Page) -> None:
    today = date.today()
    stack_full.fake.events[FAMILY].append(
        stored_event("Dentista Sofia", _local_iso(today, 15), _local_iso(today, 16), "mamma")
    )
    started = time.perf_counter()
    tablet.goto(stack_full.url + "/?lang=it")
    expect(tablet.locator(".event", has_text="Dentista Sofia")).to_be_visible(timeout=5000)
    load_seconds = time.perf_counter() - started
    print(f"\ntablet first load with events: {load_seconds:.2f} s")
    assert load_seconds < 2.0

    # Seven day columns, today highlighted, no horizontal page scroll.
    assert tablet.locator(".day").count() == 7
    assert tablet.locator(".day.today").count() == 1
    fits = tablet.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert fits

    # Every button of the top bar and of the days is at least 44 px high; the second row's
    # buttons (persons, Calendari) at least 40 px in its 48 px.
    heights = tablet.evaluate(
        "[...document.querySelectorAll('button, a.btn')]"
        ".filter(e => e.offsetParent !== null && !e.closest('#subbar'))"
        ".map(e => e.getBoundingClientRect().height)"
    )
    assert heights and min(heights) >= 44, heights
    small = tablet.evaluate(
        "[...document.querySelectorAll('#subbar button')]"
        ".filter(e => e.offsetParent !== null).map(e => e.getBoundingClientRect().height)"
    )
    assert small and min(small) >= 40, small

    # "+ Nuovo" is in the top bar (44 px), not a round button over the days.
    add = tablet.locator("#add-btn").bounding_box()
    top = tablet.locator("#topbar").bounding_box()
    assert (
        add and top and add["height"] >= 44 and add["y"] + add["height"] <= top["y"] + top["height"]
    )

    _shot(tablet, "tablet_week")


def test_calendar_filter_hides_and_shows_a_calendar(stack_full: Stack, tablet: Page) -> None:
    """ "Calendari ▾" opens a panel with a switch per calendar; off hides its events."""
    tablet.goto(stack_full.url + "/?lang=it")
    expect(tablet.locator("#filters .cal-switch")).to_have_count(3, timeout=5000)
    tablet.locator("#calendars-btn").click()
    school = tablet.locator("#filters .cal-switch", has_text="Scuola")
    expect(school).to_be_visible()
    switch = school.locator("input")
    expect(switch).to_be_checked()
    school.click()
    expect(switch).not_to_be_checked()
    expect(tablet.locator("#calendars-btn")).to_contain_text("2/3")
    school.click()
    expect(switch).to_be_checked()


def test_external_change_appears_within_a_second(stack_full: Stack, tablet: Page) -> None:
    tablet.goto(stack_full.url + "/?lang=it")
    expect(tablet.locator("#filters .cal-switch")).to_have_count(3, timeout=5000)
    today = date.today()
    started = time.perf_counter()
    stack_full.run(
        stack_full.fake.add_event(
            SCHOOL, "Visita scolastica", _local_iso(today, 9), _local_iso(today, 11)
        )
    )
    expect(tablet.locator(".event", has_text="Visita scolastica")).to_be_visible(timeout=3000)
    seconds = time.perf_counter() - started
    print(f"\nchange from another device shown after {seconds:.2f} s")
    assert seconds < 1.5


def test_new_event_form_sends_add_event(stack_full: Stack, tablet: Page) -> None:
    tablet.goto(stack_full.url + "/?lang=it")
    expect(tablet.locator("#filters .cal-switch")).to_have_count(3, timeout=5000)
    tablet.locator("#add-btn").click()
    dialog = tablet.locator("#event-form")
    expect(dialog).to_be_visible()
    tablet.fill("input[name='summary']", "Gita a Bolzano")
    tablet.select_option("select[name='category']", "scuola")
    tablet.fill("input[name='date']", date.today().strftime("%d/%m/%Y"))
    tablet.fill("input[name='start_time']", "09:00")
    tablet.fill("input[name='end_time']", "12:30")
    _shot(tablet, "tablet_new_event")
    tablet.locator("#event-form button[type='submit']").click()

    call = _wait_for_call(stack_full, "add_event")
    assert call["domain"] == "family_hub"
    assert call["data"]["category"] == "scuola"
    assert call["data"]["summary"] == "Gita a Bolzano"
    assert call["data"]["start"] == f"{date.today().isoformat()} 09:00:00"
    assert call["data"]["end"] == f"{date.today().isoformat()} 12:30:00"
    expect(dialog).to_be_hidden()
    expect(tablet.locator(".event", has_text="Gita a Bolzano")).to_be_visible(timeout=3000)


def test_reminder_popup_snooze_sends_action(stack_full: Stack, tablet: Page) -> None:
    tablet.goto(stack_full.url + "/?lang=it")
    expect(tablet.locator("#filters .cal-switch")).to_have_count(3, timeout=5000)
    _push(
        stack_full,
        "family_hub_reminder",
        {"uid": "rem-1", "title": "Promemoria", "message": "15:00 · Dentista Sofia"},
    )
    overlay = tablet.locator("#reminder-overlay")
    expect(overlay).to_be_visible(timeout=2000)
    expect(tablet.locator("#reminder-message")).to_have_text("15:00 · Dentista Sofia")
    _shot(tablet, "tablet_reminder")

    tablet.locator("#reminder-overlay [data-act='snooze'][data-minutes='10']").click()
    call = _wait_for_call(stack_full, "snooze_reminder")
    assert call["data"] == {"uid": "rem-1", "minutes": 10}
    expect(overlay).to_be_hidden()


def test_done_stops_the_reminder(stack_full: Stack, tablet: Page) -> None:
    tablet.goto(stack_full.url + "/?lang=it")
    expect(tablet.locator("#filters .cal-switch")).to_have_count(3, timeout=5000)
    _push(
        stack_full, "family_hub_reminder", {"uid": "rem-2", "title": "Promemoria", "message": "x"}
    )
    expect(tablet.locator("#reminder-overlay")).to_be_visible(timeout=2000)
    tablet.locator("#reminder-overlay [data-act='done']").click()
    call = _wait_for_call(stack_full, "stop_reminder")
    assert call["data"] == {"uid": "rem-2"}
    expect(tablet.locator("#reminder-overlay")).to_be_hidden()


def test_reminder_closes_when_closed_elsewhere(stack_full: Stack, tablet: Page) -> None:
    tablet.goto(stack_full.url + "/?lang=it")
    expect(tablet.locator("#filters .cal-switch")).to_have_count(3, timeout=5000)
    _push(
        stack_full, "family_hub_reminder", {"uid": "rem-3", "title": "Promemoria", "message": "y"}
    )
    expect(tablet.locator("#reminder-overlay")).to_be_visible(timeout=2000)
    _push(stack_full, "family_hub_reminder_closed", {"uid": "rem-3"})
    expect(tablet.locator("#reminder-overlay")).to_be_hidden(timeout=2000)


def test_adult_completes_the_guide_and_the_data_is_saved(
    stack_empty: Stack, admin_tablet: Page
) -> None:
    tablet = admin_tablet
    before = len(stack_empty.fake.saved_configs)
    tablet.goto(stack_empty.url + "/?lang=it")
    wizard = tablet.locator("#wizard-overlay")
    expect(wizard).to_be_visible(timeout=3000)
    expect(tablet.locator("#wizard-progress")).to_have_text("Passo 1 di 6")

    # 1 Famiglia
    tablet.get_by_label("Nome della famiglia").fill("Famiglia Esempio")
    tablet.get_by_label("Lingua").select_option("de")
    tablet.get_by_label("Paese").fill("Deutschland")
    tablet.locator("#wizard-next").click()

    # 2 Persone: a new install has none yet
    expect(tablet.locator("#wizard-progress")).to_have_text("Passo 2 di 6")
    tablet.locator("#wizard-body").get_by_role("button", name="Aggiungi").click()
    tablet.get_by_label("Nome", exact=True).last.fill("Sofia Esempio")
    tablet.get_by_label("Telefono").last.select_option("mobile_app_sofia")
    tablet.locator("#wizard-next").click()

    # 3 Calendari: add one
    expect(tablet.locator("#wizard-progress")).to_have_text("Passo 3 di 6")
    tablet.locator("#wizard-body").get_by_role("button", name="Aggiungi").click()
    tablet.get_by_label("Nome del calendario").last.fill("Sport")
    tablet.locator("#wizard-next").click()

    # 4 Promemoria
    expect(tablet.locator("#wizard-progress")).to_have_text("Passo 4 di 6")
    tablet.locator("#wizard-body .segment", has_text="15").click()
    tablet.locator("#wizard-next").click()

    # 5 Fonti: nothing to fill, skip it
    expect(tablet.locator("#wizard-progress")).to_have_text("Passo 5 di 6")
    tablet.locator("#wizard-skip").click()

    # 6 Schermo, then save
    expect(tablet.locator("#wizard-progress")).to_have_text("Passo 6 di 6")
    tablet.get_by_label("Tema").select_option("dark")
    tablet.locator("#wizard-next").click()  # "Salva"
    expect(wizard).to_be_hidden(timeout=3000)

    assert len(stack_empty.fake.saved_configs) == before + 1
    saved = stack_empty.fake.saved_configs[-1]
    assert saved["configured"] is True
    assert saved["family"]["family_name"] == "Famiglia Esempio"
    assert saved["family"]["language"] == "de"
    assert saved["family"]["country"] == "Deutschland"
    assert saved["persons"][0]["name"] == "Sofia Esempio"
    assert saved["persons"][0]["phone_notify"] == "mobile_app_sofia"
    assert "Sport" in [c["name"] for c in saved["categories"]]
    assert saved["reminders"]["snooze_minutes"] == 15
    assert saved["screen"]["theme"] == "dark"
    # The new calendar appears on the tablet without a reload.
    expect(tablet.locator("#filters .cal-switch", has_text="Sport")).to_have_count(1, timeout=6000)
    expect(tablet.locator("#wizard-overlay")).to_be_hidden()


def test_guide_stays_closed_once_configured(stack_full: Stack, admin_tablet: Page) -> None:
    tablet = admin_tablet
    tablet.goto(stack_full.url + "/?lang=it")
    expect(tablet.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
    expect(tablet.locator("#wizard-overlay")).to_be_hidden()


def test_skipping_every_step_saves_nothing(stack_empty: Stack, admin_tablet: Page) -> None:
    tablet = admin_tablet
    stack_empty.fake.config["configured"] = False  # as if the guide had never been finished
    before = len(stack_empty.fake.saved_configs)
    tablet.goto(stack_empty.url + "/?lang=it")
    expect(tablet.locator("#wizard-overlay")).to_be_visible(timeout=3000)
    for _ in range(6):
        tablet.locator("#wizard-skip").click()
    expect(tablet.locator("#wizard-overlay")).to_be_hidden()
    assert len(stack_empty.fake.saved_configs) == before


def test_child_cannot_open_or_save_the_guide(stack_full: Stack, browser: Browser) -> None:
    before = len(stack_full.fake.saved_configs)
    with tablet_as(browser, CHILD_USER) as page:
        page.goto(stack_full.url + "/?lang=it")
        expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
        expect(page.locator("#wizard-start")).to_be_hidden()
        expect(page.locator("#wizard-overlay")).to_be_hidden()
        # Even from the page's own script the server refuses the save.
        reply = page.evaluate(
            """() => new Promise(resolve => {
                const ws = new WebSocket('ws' + location.origin.slice(4) + '/ws');
                ws.onopen = () => ws.send(JSON.stringify({id: 1, op: 'config_save', config: {}}));
                ws.onmessage = m => {
                    const msg = JSON.parse(m.data);
                    if (msg.type === 'result') { ws.close(); resolve(msg); }
                };
            })"""
        )
    assert reply["ok"] is False and reply["error"] == "forbidden"
    assert len(stack_full.fake.saved_configs) == before


def test_week_fills_the_height_of_the_tablet(stack_full: Stack, tablet: Page) -> None:
    tablet.goto(stack_full.url + "/?lang=it")
    expect(tablet.locator(".day")).to_have_count(7)
    bottom = tablet.evaluate("document.querySelector('.day').getBoundingClientRect().bottom")
    height = tablet.evaluate("window.innerHeight")
    page_height = tablet.evaluate("document.documentElement.scrollHeight")
    assert bottom >= height - 40, (bottom, height)
    assert page_height <= height + 1, (page_height, height)


def test_guest_reads_but_cannot_add(stack_full: Stack, browser: Browser) -> None:
    with tablet_as(browser, GUEST_USER) as page:
        page.goto(stack_full.url + "/?lang=it")
        expect(page.locator("#filters .cal-switch")).to_have_count(3, timeout=5000)
        expect(page.locator(".event", has_text="Dentista Sofia")).to_be_visible(timeout=5000)
        expect(page.locator("#add-btn")).to_be_hidden()


def test_child_sees_only_their_own_events(stack_full: Stack, browser: Browser) -> None:
    today = date.today()
    stack_full.run(
        stack_full.fake.add_event(
            SCHOOL, "Recita di Sofia", _local_iso(today, 11), _local_iso(today, 12), "sofia"
        )
    )
    stack_full.run(
        stack_full.fake.add_event(
            FAMILY, "Riunione di mamma", _local_iso(today, 13), _local_iso(today, 14), "mamma"
        )
    )
    with tablet_as(browser, CHILD_USER) as page:
        page.goto(stack_full.url + "/?lang=it")
        expect(page.locator(".event", has_text="Recita di Sofia")).to_be_visible(timeout=5000)
        expect(page.locator(".event", has_text="Riunione di mamma")).to_have_count(0)
        expect(page.locator("#add-btn")).to_be_visible()


@contextlib.contextmanager
def _device(browser: Browser, width: int, height: int, user: str = ADULT_USER) -> Iterator[Page]:
    context = browser.new_context(viewport={"width": width, "height": height}, has_touch=True)
    context.set_extra_http_headers({"X-Remote-User-Id": user})
    page = context.new_page()
    try:
        yield page
    finally:
        context.close()


def _tomorrow_iso(hour: int) -> str:
    return _local_iso(date.today() + timedelta(days=1), hour)


def test_phone_shows_today_and_tomorrow_as_an_agenda(stack_full: Stack, browser: Browser) -> None:
    today = date.today()
    stack_full.run(
        stack_full.fake.add_event(
            FAMILY, "Agenda oggi", _local_iso(today, 17), _local_iso(today, 18), "mamma"
        )
    )
    stack_full.run(
        stack_full.fake.add_event(
            SCHOOL, "Agenda domani", _tomorrow_iso(9), _tomorrow_iso(10), "sofia"
        )
    )
    with _device(browser, 390, 844) as page:
        page.goto(stack_full.url + "/?lang=it")
        expect(page.locator(".week.agenda")).to_be_visible(timeout=5000)
        # Today and the next 13 days, one under the other.
        expect(page.locator(".week.agenda .day")).to_have_count(14)
        expect(page.locator(".event", has_text="Agenda oggi")).to_be_visible()
        expect(page.locator(".event", has_text="Agenda domani")).to_be_visible()
        expect(page.locator("#add-btn")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert page.locator("#add-btn").bounding_box()["width"] >= 56 - 1


def test_pc_shows_the_next_fourteen_days_beside_the_week(
    stack_full: Stack, browser: Browser
) -> None:
    today = date.today()
    stack_full.run(
        stack_full.fake.add_event(
            FAMILY, "Riunione PC", _local_iso(today, 16), _local_iso(today, 17), "mamma"
        )
    )
    # The next 14 days beside the calendar only from 1400 px.
    with _device(browser, 1600, 900) as page:
        page.goto(stack_full.url + "/?lang=it")
        expect(page.locator("#upcoming")).to_be_visible(timeout=5000)
        expect(page.locator("#upcoming .event", has_text="Riunione PC")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_saved_theme_is_applied(stack_full: Stack, tablet: Page) -> None:
    stack_full.fake.config["screen"]["theme"] = "dark"
    try:
        tablet.goto(stack_full.url + "/?lang=it")
        expect(tablet.locator("html")).to_have_attribute("data-theme", "dark", timeout=5000)
    finally:
        stack_full.fake.config["screen"]["theme"] = "auto"


def test_save_error_is_shown_in_the_guide_language(stack_empty: Stack, admin_tablet: Page) -> None:
    tablet = admin_tablet
    stack_empty.fake.config["configured"] = False
    tablet.goto(stack_empty.url + "/?lang=it")
    expect(tablet.locator("#wizard-overlay")).to_be_visible(timeout=3000)
    tablet.get_by_label("Nome della famiglia").fill("")
    for _ in range(5):
        tablet.locator("#wizard-next").click()
    tablet.locator("#wizard-next").click()  # "Salva" with an empty family name
    expect(tablet.locator("#wizard-error")).to_be_visible(timeout=3000)
    expect(tablet.locator("#wizard-error")).to_contain_text("Controlla i campi")
    expect(tablet.locator("#wizard-error")).not_to_contain_text("invalid_config")


def _open_lists(page: Page, stack: Stack) -> None:
    page.goto(stack.url + "/?lang=it")
    expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
    page.locator("#todo-btn").click()
    expect(page.locator("#todo-overlay")).to_be_visible()


def test_shopping_list_add_tick_and_remove(stack_full: Stack, tablet: Page) -> None:
    _open_lists(tablet, stack_full)
    expect(tablet.locator(".todo-row", has_text="Latte")).to_be_visible(timeout=5000)
    tablet.locator(".todo-add input").fill("Uova")
    tablet.locator(".todo-add button").click()
    expect(tablet.locator(".todo-row", has_text="Uova")).to_be_visible(timeout=3000)
    tablet.locator(".todo-row", has_text="Latte").locator("input[type=checkbox]").check()
    expect(tablet.locator(".todo-row span.done", has_text="Latte")).to_be_visible(timeout=3000)
    tablet.locator(".todo-row", has_text="Pane").get_by_role("button", name="Rimuovi").click()
    expect(tablet.locator(".todo-row", has_text="Pane")).to_have_count(0, timeout=3000)
    summaries = [i["summary"] for i in stack_full.fake.todo_items[SHOP]]
    assert "Uova" in summaries and "Pane" not in summaries
    assert {i["summary"]: i["status"] for i in stack_full.fake.todo_items[SHOP]}[
        "Latte"
    ] == "completed"


def test_child_adds_but_cannot_remove_and_guest_only_reads(
    stack_full: Stack, browser: Browser
) -> None:
    with tablet_as(browser, CHILD_USER) as page:
        _open_lists(page, stack_full)
        expect(page.locator(".todo-add")).to_be_visible(timeout=5000)
        expect(
            page.locator(".todo-row", has_text="Latte").get_by_role("button", name="Rimuovi")
        ).to_have_count(0)
    with tablet_as(browser, GUEST_USER) as page:
        _open_lists(page, stack_full)
        expect(page.locator(".todo-row", has_text="Latte")).to_be_visible(timeout=5000)
        expect(page.locator(".todo-add")).to_have_count(0)


def test_external_waste_calendar_is_shown_read_only(stack_full: Stack, tablet: Page) -> None:
    today = date.today()
    for event in stack_full.fake.events[WASTE]:
        event["start"] = _local_iso(today, 7)
        event["end"] = _local_iso(today, 8)
    tablet.goto(stack_full.url + "/?lang=it")
    expect(tablet.locator(".event.external", has_text="Ritiro indifferenziato")).to_be_visible(
        timeout=5000
    )
    tablet.locator("#calendars-btn").click()
    expect(tablet.locator("#filters .cal-switch", has_text="Rifiuti")).to_be_visible()
    tablet.locator("#calendars-btn").click()
    # Clicking an external event does not open anything to change it.
    tablet.locator(".event.external", has_text="Ritiro indifferenziato").click()
    expect(tablet.locator("#event-overlay")).to_be_hidden()


def test_phone_steps_between_days_and_offers_the_guide_in_a_menu(
    stack_full: Stack, browser: Browser
) -> None:
    today = date.today()
    stack_full.run(
        stack_full.fake.add_event(
            FAMILY,
            "Dopodomani",
            _local_iso(today + timedelta(days=2), 10),
            _local_iso(today + timedelta(days=2), 11),
            "mamma",
        )
    )
    with _device(browser, 390, 844) as page:
        page.goto(stack_full.url + "/?lang=it")
        expect(page.locator(".week.agenda")).to_be_visible(timeout=5000)
        # Giorni lists today and the next 13 days; a swipe moves one day, the title goes back.
        expect(page.locator(".event", has_text="Dopodomani")).to_be_visible(timeout=3000)
        first = page.locator("#week .day").first
        page.evaluate(
            """() => {
              const w = document.getElementById('week');
              const o = (x) => ({ clientX: x, clientY: 500, pointerType: 'touch', bubbles: true });
              w.dispatchEvent(new PointerEvent('pointerdown', o(330)));
              w.dispatchEvent(new PointerEvent('pointerup', o(40)));
            }"""
        )
        expect(first).to_have_attribute("aria-label", (today + timedelta(days=1)).isoformat())
        page.locator("#period-title").click()
        expect(first).to_have_attribute("aria-label", today.isoformat())
        page.locator("#menu-btn").click()
        expect(page.locator("#menu-wizard")).to_be_visible()
        page.locator("#menu-wizard").click()
        expect(page.locator("#wizard-overlay")).to_be_visible()


def test_sources_step_saves_the_chosen_lists(stack_full: Stack, tablet: Page) -> None:
    before = len(stack_full.fake.saved_configs)
    original = list(stack_full.fake.config["sources"]["todo"])
    try:
        tablet.goto(stack_full.url + "/?lang=it")
        expect(tablet.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
        tablet.locator("#menu-btn").click()
        tablet.locator("#menu-wizard").click()
        expect(tablet.locator("#wizard-overlay")).to_be_visible()
        for _ in range(4):
            tablet.locator("#wizard-next").click()
        expect(tablet.locator("#wizard-progress")).to_have_text("Passo 5 di 6")
        shop = tablet.get_by_label("Spesa")
        expect(shop).to_be_checked()
        shop.uncheck()
        for _ in range(2):
            tablet.locator("#wizard-next").click()
        expect(tablet.locator("#wizard-overlay")).to_be_hidden(timeout=3000)
        assert len(stack_full.fake.saved_configs) == before + 1
        assert stack_full.fake.saved_configs[-1]["sources"]["todo"] == []
    finally:
        stack_full.fake.config["sources"]["todo"] = original


def _open_shifts(page: Page, stack: Stack) -> None:
    page.goto(stack.url + "/?lang=it")
    expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
    page.locator("#menu-btn").click()
    page.locator("#menu-shifts").click()
    expect(page.locator("#shifts-overlay")).to_be_visible()


def test_mother_enters_her_five_shift_models_and_applies_k3(
    stack_full: Stack, tablet: Page
) -> None:
    stack_full.fake.config["shifts"] = {}
    _open_shifts(tablet, stack_full)
    tablet.locator("#shift-person").select_option("mamma")
    models = tablet.locator("#shifts-models")
    rows = [
        ("Mattina", "06:00", "14:00"),
        ("Pomeriggio", "14:00", "22:00"),
        ("Notte", "22:00", "06:00"),
        ("Giornata", "08:00", "16:00"),
        ("Mattina corta", "08:00", "13:30"),
    ]
    for index, (name, start, end) in enumerate(rows):
        models.get_by_role("button", name="Aggiungi turno").click()
        models.get_by_label("Nome", exact=True).nth(index).fill(name)
        models.get_by_label("Inizio").nth(index).fill(start)
        models.get_by_label("Fine").nth(index).fill(end)
    models.get_by_role("button", name="Salva turni").click()
    expect(tablet.locator("#shifts-overlay")).to_be_visible()
    expect(tablet.locator("#status-note")).to_contain_text("Turni salvati", timeout=3000)
    saved = stack_full.fake.config["shifts"]["mamma"]
    assert [(s["name"], s["start"], s["end"]) for s in saved] == rows

    # Apply Mattina to the first two days of the next month: they are in the future.
    tablet.locator("#tab-calendar").click()
    tablet.locator("#shifts-calendar .month-nav button").last.click()
    tablet.locator("#shifts-calendar .shift-pick select").select_option(label="Mattina")
    tablet.locator(".day-cell").nth(0).click()
    tablet.locator(".day-cell").nth(1).click()
    tablet.get_by_role("button", name="Applica ai giorni scelti").click()
    expect(tablet.locator("#status-note")).to_contain_text("2 turni inseriti", timeout=3000)
    adds = [
        c["data"]
        for c in stack_full.fake.calls
        if c["service"] == "add_event" and c["data"].get("shift_id")
    ]
    assert len(adds) == 2
    assert all(a["summary"] == "Mattina" and a["persons"] == ["mamma"] for a in adds)
    assert all(a["start"].endswith("06:00:00") and a["end"].endswith("14:00:00") for a in adds)


def test_changing_a_shift_time_asks_before_updating_future_days(
    stack_full: Stack, tablet: Page
) -> None:
    _open_shifts(tablet, stack_full)
    tablet.locator("#shift-person").select_option("mamma")
    tablet.locator("#shifts-models").get_by_label("Inizio").first.fill("08:00")
    tablet.locator("#shifts-models").get_by_role("button", name="Salva turni").click()
    # Family Hub's own dialog, not a browser prompt.
    question = tablet.locator("#confirm-overlay")
    expect(question).to_be_visible()
    expect(question).to_contain_text("2 turni")
    tablet.get_by_role("button", name="Sì").click()
    expect(question).to_be_hidden()
    expect(tablet.locator("#status-note")).to_contain_text("Aggiornati", timeout=5000)
    assert stack_full.fake.shift_saves[-1]["apply_future"] is True


def test_cancelling_the_future_question_saves_nothing(stack_full: Stack, tablet: Page) -> None:
    _open_shifts(tablet, stack_full)
    tablet.locator("#shift-person").select_option("mamma")
    before = len(stack_full.fake.shift_saves)
    tablet.locator("#shifts-models").get_by_label("Inizio").first.fill("09:00")
    tablet.locator("#shifts-models").get_by_role("button", name="Salva turni").click()
    expect(tablet.locator("#confirm-overlay")).to_be_visible()
    tablet.get_by_role("button", name="Annulla").click()
    expect(tablet.locator("#confirm-overlay")).to_be_hidden()
    assert len(stack_full.fake.shift_saves) == before


def test_shift_times_follow_the_family_time_format(stack_full: Stack, tablet: Page) -> None:
    # The module shares one stack: Mattina starts at 08:00 by now, and ends at 14:00.
    family = stack_full.fake.config["family"]
    original = family["time_format"]
    family["time_format"] = "12h"
    try:
        _open_shifts(tablet, stack_full)
        tablet.locator("#shift-person").select_option("mamma")
        models = tablet.locator("#shifts-models")
        expect(models.get_by_label("Fine").first).to_have_value("02:00 PM")
        start = models.get_by_label("Inizio").first
        start.fill("8:00 am")
        start.blur()
        expect(start).to_have_value("08:00 AM")
        models.get_by_role("button", name="Salva turni").click()
        expect(tablet.locator("#status-note")).to_contain_text("Turni salvati", timeout=3000)
        assert stack_full.fake.config["shifts"]["mamma"][0]["start"] == "08:00"
    finally:
        family["time_format"] = original


def test_child_sees_only_own_shifts(stack_full: Stack, browser: Browser) -> None:
    with tablet_as(browser, CHILD_USER) as page:
        _open_shifts(page, stack_full)
        options = page.locator("#shift-person option")
        expect(options).to_have_count(1)
        expect(options.first).to_have_text("Sofia")


def test_guest_has_no_shifts_entry(stack_full: Stack, browser: Browser) -> None:
    with tablet_as(browser, GUEST_USER) as page:
        page.goto(stack_full.url + "/?lang=it")
        expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
        expect(page.locator("#menu-btn")).to_be_hidden()


def test_shifts_work_on_the_phone(stack_full: Stack, browser: Browser) -> None:
    with _device(browser, 390, 844) as page:
        _open_shifts(page, stack_full)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        expect(page.locator("#shifts-models")).to_be_visible()
        page.locator("#shifts-close").click()
        expect(page.locator("#shifts-overlay")).to_be_hidden()
