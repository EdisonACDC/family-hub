"""0.7.7b2: the page speaks the family's language, whatever the browser says; a change in the guide
shows at once and goes back when the guide is left without saving; and no Italian label is left
on any screen in German or English."""

from __future__ import annotations

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack
from tests.e2e.settle import settle
from tests.e2e.test_layout_071_e2e import _open, _screens, _seeded
from tests.e2e.test_tablet import _device

# Italian labels of the page itself, matched exactly (a family's own names are not in the list).
ITALIAN_LABELS = [
    "Nuovo",
    "Oggi",
    "Mese",
    "Settimana",
    "Elenco",
    "Chiudi",
    "Salva",
    "Annulla",
    "Indietro",
    "Avanti",
    "Fatto",
    "Ferma",
    "Persone",
    "Persona",
    "Turni",
    "Avvisi",
    "Liste",
    "Calendari",
    "Calendario",
    "Titolo",
    "Inizio",
    "Fine",
    "Data",
    "Modelli",
    "Vista",
    "Viste",
    "Giorni",
    "Procedura guidata",
    "Tutto il giorno",
    "Nuovo evento",
    "Riduci trasparenza",
    "Prossimi ritiri",
    "Calendari esterni",
    "Posticipa 10 min",
    "Posticipa 1 ora",
    "Eventi della settimana",
    "Prossimi eventi",
    "Evento",
    "Salta, lo faccio dopo",
    "Promemoria",
    "Vuoto: quelli di famiglia.",
    "Per chi? Scegli le persone qui sotto.",
    "Settimana precedente",
    "Settimana successiva",
    "Eventi",
    "Liste",
    "Promemoria",
    "Sett.",
    "Continua",
    "Esci",
    "Uscire senza salvare?",
]
# Words that are German too: "Liste" and "Promemoria" are not Italian in a German page.
GERMAN_WORDS = {"Liste", "Promemoria"}

FIND_ITALIAN_JS = """
(words) => {
  const found = [];
  const visible = (el) => el.getClientRects().length > 0
    && getComputedStyle(el).visibility !== "hidden";
  for (const el of document.querySelectorAll("body *")) {
    if (!visible(el)) continue;
    // The reminder's own title is the event's text, not a label of the page.
    if (el.closest("#reminder-overlay")) continue;
    for (const node of el.childNodes) {
      if (node.nodeType !== 3) continue;
      const text = node.nodeValue.trim();
      const where = el.id || el.className || el.tagName;
      if (text && words.includes(text)) found.push(text + " in " + where);
    }
    for (const attr of ["aria-label", "title", "placeholder"]) {
      const value = el.getAttribute(attr);
      const on = el.id || el.tagName;
      if (value && words.includes(value.trim())) found.push(attr + "=" + value + " on " + on);
    }
  }
  return found;
}
"""


def _family_language(stack: Stack, language: str) -> None:
    stack.fake.config["family"] = {**stack.fake.config.get("family", {}), "language": language}


@pytest.mark.parametrize(
    ("language", "week", "month"),
    [("de", "Woche", "Monat"), ("en", "Week", "Month")],
    ids=["german", "english"],
)
def test_the_page_speaks_the_family_language_not_the_browsers(
    stack_full: Stack, browser: Browser, language: str, week: str, month: str
) -> None:
    _family_language(stack_full, language)
    try:
        # The page is opened with ?lang=it, as the tests always do: the family's language wins.
        with _device(browser, 1024, 768) as page:
            _open(page, stack_full)
            expect(page.locator("[data-i18n='sWeek']").first).to_have_text(week, timeout=5000)
            expect(page.locator("#view-switch [data-view='week'] .label-short")).to_have_text(week)
            expect(page.locator("[data-i18n='sMonth']").first).to_have_text(month)
            assert page.evaluate("document.documentElement.lang") == language
    finally:
        _family_language(stack_full, "it")


def test_a_language_chosen_in_the_guide_shows_at_once_and_goes_back_when_left(
    stack_empty: Stack, admin_tablet: Page
) -> None:
    stack_empty.fake.config["configured"] = False  # the guide opens by itself
    before = len(stack_empty.fake.saved_configs)
    tablet = admin_tablet
    tablet.goto(stack_empty.url + "/?lang=it")
    expect(tablet.locator("#wizard-overlay")).to_be_visible(timeout=3000)
    tablet.get_by_label("Lingua").select_option("en")
    expect(tablet.locator("#wizard-next")).to_have_text("Next")
    assert tablet.evaluate("document.documentElement.lang") == "en"

    tablet.keyboard.press("Escape")
    tablet.locator("#wizard-leave-exit").click()  # "Leave": nothing is saved
    expect(tablet.locator("#wizard-overlay")).to_be_hidden()
    assert tablet.evaluate("document.documentElement.lang") == "it"
    expect(tablet.locator("#guide-start")).to_have_text("Avvia la procedura guidata")
    assert len(stack_empty.fake.saved_configs) == before


@pytest.mark.parametrize("language", ["de", "en"])
def test_no_italian_label_is_left_on_any_screen(
    stack_full: Stack, browser: Browser, language: str
) -> None:
    _family_language(stack_full, language)
    problems: list[str] = []
    try:
        with _seeded(stack_full), _device(browser, 390, 844) as page:
            for name, go in _screens(stack_full):
                _open(page, stack_full)
                try:
                    go(page)
                    settle(page)
                    words = [
                        w for w in ITALIAN_LABELS if not (language == "de" and w in GERMAN_WORDS)
                    ]
                    for item in page.evaluate(FIND_ITALIAN_JS, words):
                        problems.append(f"{name}: {item}")
                except Exception as err:  # the screen could not be reached at this size
                    problems.append(
                        f"{name}: could not open ({type(err).__name__}: {str(err)[:120]})"
                    )
    finally:
        _family_language(stack_full, "it")
    assert not problems, f"Italian left in {language}:\n" + "\n".join(problems)


def test_no_italian_is_left_after_a_live_switch(stack_empty: Stack, admin_tablet: Page) -> None:
    """Switching to German in the guide redraws the page at once: the view buttons, the guide and
    its question about leaving are all German, and nothing drawn afterwards is Italian."""
    stack_empty.fake.config["configured"] = False  # the guide opens by itself
    tablet = admin_tablet
    tablet.goto(stack_empty.url + "/?lang=it")
    expect(tablet.locator("#wizard-overlay")).to_be_visible(timeout=3000)
    tablet.get_by_label("Lingua").select_option("de")
    expect(tablet.locator("#view-switch [data-view='week'] .label-short")).to_have_text("Woche")

    tablet.keyboard.press("Escape")  # changes were made: the question is asked
    expect(tablet.locator("#wizard-leave")).to_be_visible()
    expect(tablet.locator("#wizard-leave-title")).to_have_text("Ohne Speichern verlassen?")
    expect(tablet.locator("#wizard-leave-stay")).to_have_text("Weiter bearbeiten")
    expect(tablet.locator("#wizard-leave-exit")).to_have_text("Verlassen")

    words = [w for w in ITALIAN_LABELS if w not in GERMAN_WORDS]
    problems = tablet.evaluate(FIND_ITALIAN_JS, words)
    assert not problems, "\n".join(problems)

    tablet.locator("#wizard-leave-exit").click()
    expect(tablet.locator("#wizard-overlay")).to_be_hidden()
