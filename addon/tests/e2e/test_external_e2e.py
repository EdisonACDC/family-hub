"""External calendars in a real browser: add from a link, upload a file, refresh, errors, and
who sees the menu entry."""

from __future__ import annotations

from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack, tablet_as
from tests.e2e.test_tablet import _shot
from tests.helpers import CHILD_USER

ICS = (
    b"BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:x\nDTSTART;VALUE=DATE:20261201\n"
    b"DTEND;VALUE=DATE:20261202\nSUMMARY:Ferien\nEND:VEVENT\nEND:VCALENDAR\n"
)


def _open(page: Page, stack: Stack) -> None:
    page.goto(stack.url + "/?lang=it")
    expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
    page.locator("#menu-btn").click()
    page.locator("#menu-ics").click()
    expect(page.locator("#ics-overlay")).to_be_visible()


def test_adult_adds_a_calendar_from_a_link(stack_full: Stack, tablet: Page) -> None:
    _open(tablet, stack_full)
    form = tablet.locator("#ics-body form")
    form.get_by_label("Nome", exact=True).fill("Rifiuti Bianco")
    form.get_by_label("Indirizzo (https:// o webcal://)").fill("https://example.org/rifiuti.ics")
    form.get_by_role("button", name="Aggiungi").click()
    expect(tablet.locator("#status-note")).to_contain_text("Calendario aggiunto", timeout=3000)
    added = stack_full.fake.ics
    assert any(c["url"] == "https://example.org/rifiuti.ics" for c in added.values())
    expect(tablet.locator("#ics-body h3", has_text="Rifiuti Bianco")).to_be_visible()


def test_adult_uploads_an_ics_file(stack_full: Stack, tablet: Page) -> None:
    _open(tablet, stack_full)
    form = tablet.locator("#ics-body form")
    form.get_by_label("Nome", exact=True).fill("Ferien")
    form.get_by_label("Tipo").select_option("vacanze_scuola")
    form.locator("input[type='file']").set_input_files(
        {"name": "ferien.ics", "mimeType": "text/calendar", "buffer": ICS}
    )
    form.get_by_role("button", name="Aggiungi").click()
    expect(tablet.locator("#status-note")).to_contain_text("Calendario aggiunto", timeout=3000)
    assert any(c["content"].startswith("BEGIN:VCALENDAR") for c in stack_full.fake.ics.values())


def test_a_bad_file_shows_the_error_and_adds_nothing(stack_full: Stack, tablet: Page) -> None:
    _open(tablet, stack_full)
    before = len(stack_full.fake.ics)
    form = tablet.locator("#ics-body form")
    form.get_by_label("Nome", exact=True).fill("Rotto")
    form.locator("input[type='file']").set_input_files(
        {"name": "rotto.ics", "mimeType": "text/calendar", "buffer": b"ciao"}
    )
    form.get_by_role("button", name="Aggiungi").click()
    expect(tablet.locator("#ics-error")).to_contain_text(
        "non è un calendario ICS valido", timeout=3000
    )
    assert len(stack_full.fake.ics) == before


def test_refresh_button_on_a_link_calendar(stack_full: Stack, tablet: Page) -> None:
    stack_full.fake.ics["lnk"] = {
        "name": "Scuola",
        "type": "vacanze_scuola",
        "color": "#2563EB",
        "icon": "calendar",
        "persons": [],
        "url": "https://example.org/s.ics",
        "content": "BEGIN:VCALENDAR\nEND:VCALENDAR\n",
        "source": "link",
    }
    try:
        _open(tablet, stack_full)
        card = tablet.locator("#ics-body .notify-card", has_text="Scuola")
        card.get_by_role("button", name="Aggiorna ora").click()
        expect(tablet.locator("#status-note")).to_contain_text("Aggiornato", timeout=3000)
    finally:
        stack_full.fake.ics.pop("lnk", None)


def test_children_do_not_see_the_menu_entry(stack_full: Stack, browser: Browser) -> None:
    with tablet_as(browser, CHILD_USER) as page:
        page.goto(stack_full.url + "/?lang=it")
        expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
        page.locator("#menu-btn").click()
        expect(page.locator("#menu-ics")).to_be_hidden()


def test_segmented_control_switches_between_link_and_file(stack_full: Stack, tablet: Page) -> None:
    _open(tablet, stack_full)
    form = tablet.locator("#ics-body form.ics-form").first
    expect(form.locator(".segment", has_text="Da link")).to_have_attribute("aria-pressed", "true")
    form.locator(".segment", has_text="Da file").click()
    expect(form.locator(".segment", has_text="Da file")).to_have_attribute("aria-pressed", "true")
    expect(form.locator(".file-button", has_text="Scegli file .ics")).to_be_visible()
    expect(form.locator(".file-name")).to_have_text("Nessun file scelto")
    # The browser's own file button is never shown: the chooser is the glass button.
    expect(form.locator("input[type='file']")).to_have_class("visually-hidden")
    form.locator("input[type='file']").set_input_files(
        {"name": "ferien.ics", "mimeType": "text/calendar", "buffer": ICS}
    )
    expect(form.locator(".file-name")).to_have_text("ferien.ics")


def test_rubbish_pickups_show_their_icon_and_colour_in_the_week(
    stack_full: Stack, tablet: Page
) -> None:
    from datetime import date

    today = date.today().isoformat()
    stack_full.fake.ics["abfuhr"] = {
        "name": "Abfuhrtermine",
        "type": "rifiuti",
        "color": "#64748B",
        "icon": "calendar",
        "persons": [],
        "url": "",
        "content": "BEGIN:VCALENDAR\nEND:VCALENDAR\n",
        "source": "file",
    }
    key = "calendar.family_hub_ext_abfuhr"
    stack_full.fake.states.append(
        {
            "entity_id": key,
            "state": "off",
            "attributes": {"friendly_name": "Abfuhrtermine", "source_id": "abfuhr"},
        }
    )
    stack_full.fake.events[key] = [
        {
            "summary": "Restmüll, Biotonne",
            "start": today,
            "end": today,
            "location": "",
            "record_id": "",
            "shift_id": "",
            "person_ids": "",
        },
    ]
    try:
        tablet.goto(stack_full.url + "/?lang=it")
        # Shown as the type, as in the TrashCard: "Indifferenziato" with its icon.
        event = tablet.locator(".event", has_text="Indifferenziato")
        expect(event).to_be_visible(timeout=5000)
        expect(event.locator(".waste-icon.mdi svg path")).to_have_count(1)
        assert (
            event.evaluate("e => getComputedStyle(e).getPropertyValue('--ev').trim()") == "#9E9E9E"
        )
        _shot(tablet, "tablet_rubbish_week")
    finally:
        stack_full.fake.ics.pop("abfuhr", None)
        stack_full.fake.events.pop(key, None)
        stack_full.fake.states[:] = [s for s in stack_full.fake.states if s["entity_id"] != key]


def test_calendar_page_screenshots(stack_full: Stack, tablet: Page, browser: Browser) -> None:
    _open(tablet, stack_full)
    expect(tablet.locator("#ics-overlay .dialog")).to_have_css("opacity", "1")
    _shot(tablet, "tablet_external_calendars")
    with _phone(browser) as phone:
        _open(phone, stack_full)
        expect(phone.locator("#ics-overlay .dialog")).to_have_css("opacity", "1")
        _shot(phone, "phone_external_calendars")


from collections.abc import Iterator  # noqa: E402
from contextlib import contextmanager  # noqa: E402


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


def _add_rubbish_calendar(stack: Stack, key: str, source: str, events: list[dict]) -> None:  # type: ignore[type-arg]
    stack.fake.ics[source] = {
        "name": "Abfuhr",
        "type": "rifiuti",
        "color": "#64748B",
        "icon": "calendar",
        "persons": [],
        "url": "",
        "content": "BEGIN:VCALENDAR\nEND:VCALENDAR\n",
        "source": "file",
    }
    stack.fake.states.append(
        {
            "entity_id": key,
            "state": "off",
            "attributes": {"friendly_name": "Abfuhr", "source_id": source},
        }
    )
    stack.fake.events[key] = events


def _remove_rubbish_calendar(stack: Stack, key: str, source: str) -> None:
    stack.fake.ics.pop(source, None)
    stack.fake.events.pop(key, None)
    stack.fake.states[:] = [s for s in stack.fake.states if s["entity_id"] != key]


def test_rubbish_types_are_edited_and_the_week_shows_the_new_label(
    stack_full: Stack, tablet: Page
) -> None:
    from datetime import date

    today = date.today().isoformat()
    key = "calendar.family_hub_ext_farben"
    _add_rubbish_calendar(
        stack_full,
        key,
        "farben",
        [
            {
                "summary": "Abfuhr: Bioabfall",
                "start": today,
                "end": today,
                "location": "",
                "record_id": "",
                "shift_id": "",
                "person_ids": "",
            }
        ],
    )
    saved = [dict(t) for t in stack_full.fake.waste_types]
    try:
        _open(tablet, stack_full)
        rows = tablet.locator("#ics-body .waste-type")
        expect(rows).to_have_count(5)
        for i in range(5):
            expect(rows.nth(i).locator(".waste-icon.mdi svg path")).to_have_count(1)
        organico = rows.nth(1)
        expect(organico.get_by_label("Etichetta")).to_have_value("Organico")
        organico.get_by_label("Etichetta").fill("Umido")
        organico.locator("input[type='color']").fill("#112233")
        _shot(tablet, "tablet_rubbish_types")
        tablet.locator("#ics-body").get_by_role("button", name="Salva tipi").click()
        expect(tablet.locator("#status-note")).to_contain_text(
            "Tipi di rifiuti salvati", timeout=3000
        )
        assert stack_full.fake.waste_types[1]["label"] == "Umido"
        tablet.locator("#ics-close").click()
        event = tablet.locator(".event.allday", has_text="Umido")
        expect(event).to_be_visible(timeout=5000)
        assert (
            event.evaluate("e => getComputedStyle(e).getPropertyValue('--ev').trim()") == "#112233"
        )
    finally:
        _remove_rubbish_calendar(stack_full, key, "farben")
        stack_full.fake.waste_types = saved
        stack_full.fake.waste_styles = {t["id"]: t["color"] for t in saved}


def test_trashcard_types_are_proposed_from_a_dashboard(stack_full: Stack, tablet: Page) -> None:
    stack_full.fake.dashboards["casa"] = {
        "views": [
            {
                "cards": [
                    {
                        "type": "vertical-stack",
                        "cards": [
                            {
                                "type": "custom:trash-card",
                                "entities": ["calendar.rifiuti"],
                                "pattern": [
                                    {
                                        "label": "Bio",
                                        "icon": "mdi:flower",
                                        "pattern": "Bioabfall",
                                        "color": "light-green",
                                        "type": "organic",
                                    },
                                    {"label": "Resto", "type": "waste", "pattern": "Rest"},
                                ],
                            }
                        ],
                    }
                ]
            }
        ]
    }
    try:
        _open(tablet, stack_full)
        tablet.locator("#ics-body").get_by_role("button", name="Importa da TrashCard").click()
        expect(tablet.locator("#status-note")).to_contain_text("TrashCard", timeout=3000)
        rows = tablet.locator("#ics-body .waste-type")
        expect(rows).to_have_count(2)
        expect(rows.nth(0).get_by_label("Etichetta")).to_have_value("Bio")
        expect(rows.nth(0).locator("input[type='color']")).to_have_value("#8bc34a")
        expect(rows.nth(1).get_by_label("Icona")).to_have_value("mdi:trash-can-outline")
    finally:
        stack_full.fake.dashboards.pop("casa", None)


def test_all_day_rubbish_is_one_compact_row_with_dots(stack_full: Stack, tablet: Page) -> None:
    from datetime import date

    today = date.today().isoformat()
    key = "calendar.family_hub_ext_kompakt"
    _add_rubbish_calendar(
        stack_full,
        key,
        "kompakt",
        [
            {
                "summary": "Glascontainer-Abholung-Mitte-Nord",
                "start": today,
                "end": today,
                "location": "",
                "record_id": "",
                "shift_id": "",
                "person_ids": "",
            }
        ],
    )
    try:
        tablet.goto(stack_full.url + "/?lang=it")
        # Glass is not one of the default types: it is "Altro", the raw title in the tooltip.
        row = tablet.locator(".event.allday", has_text="Altro")
        expect(row).to_be_visible(timeout=5000)
        # One line. The week is drawn again when the weather and the calendars arrive, so the
        # height is checked once the drawing has settled, not on the very first frame.
        tablet.wait_for_function(
            """() => [...document.querySelectorAll('.event.allday')].some(
                e => e.textContent.includes('Altro') && e.getBoundingClientRect().height < 40)""",
            timeout=5000,
        )
        assert row.locator(".allday-name").evaluate("e => e.scrollWidth > e.clientWidth") in (
            True,
            False,
        )
        assert (
            row.locator(".allday-name").get_attribute("title")
            == "Glascontainer-Abholung-Mitte-Nord"
        )
        assert row.evaluate("e => getComputedStyle(e).hyphens") == "none"
    finally:
        _remove_rubbish_calendar(stack_full, key, "kompakt")


def test_removing_asks_in_the_family_hub_window_first(stack_full: Stack, tablet: Page) -> None:
    stack_full.fake.ics["weg"] = {
        "name": "Abfuhrtermine",
        "type": "rifiuti",
        "color": "#64748B",
        "icon": "calendar",
        "persons": [],
        "url": "",
        "content": "BEGIN:VCALENDAR\nEND:VCALENDAR\n",
        "source": "file",
    }
    try:
        _open(tablet, stack_full)
        card = tablet.locator("#ics-body .ics-card", has_text="Abfuhrtermine")
        card.get_by_role("button", name="Rimuovi").click()
        expect(tablet.locator("#confirm-overlay")).to_be_visible()
        expect(tablet.locator("#confirm-text")).to_contain_text("Rimuovere «Abfuhrtermine»?")
        tablet.get_by_role("button", name="Annulla").click()
        expect(tablet.locator("#confirm-overlay")).to_be_hidden()
        assert "weg" in stack_full.fake.ics
        card.get_by_role("button", name="Rimuovi").click()
        tablet.get_by_role("button", name="Rimuovi").last.click()
        expect(tablet.locator("#status-note")).to_contain_text("Calendario rimosso", timeout=3000)
        assert "weg" not in stack_full.fake.ics
    finally:
        stack_full.fake.ics.pop("weg", None)


def test_external_chips_show_the_type_icon_not_an_emoji(stack_full: Stack, tablet: Page) -> None:
    key = "calendar.family_hub_ext_chipicon"
    _add_rubbish_calendar(stack_full, key, "chipicon", [])
    try:
        tablet.goto(stack_full.url + "/?lang=it")
        # In "Calendari ▾" an external calendar shows the icon of its type, not an emoji.
        expect(tablet.locator("#filters .cal-switch", has_text="Abfuhr")).to_have_count(
            1, timeout=5000
        )
        tablet.locator("#calendars-btn").click()
        row = tablet.locator("#filters .cal-switch", has_text="Abfuhr")
        expect(row).to_be_visible(timeout=5000)
        expect(row.locator(".waste-icon svg")).to_have_count(1)
        assert "📅" not in row.inner_text()
    finally:
        _remove_rubbish_calendar(stack_full, key, "chipicon")
