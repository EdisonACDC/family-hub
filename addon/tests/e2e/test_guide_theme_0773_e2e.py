"""0.7.7b1: the guide can be left (X, Esc, a tap outside) without saving; leaving with changes asks
first and puts the saved theme back; the theme follows the choice, and "Automatico" follows the
system; the screens fit in the dark theme too."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_layout_071_e2e import CHECK_JS, _open, _screens, _seeded
from tests.e2e.test_tablet import _device


def _open_guide(tablet: Page, stack: Stack) -> None:
    tablet.goto(stack.url + "/?lang=it")
    expect(tablet.locator("#wizard-overlay")).to_be_visible(timeout=3000)


def test_the_x_esc_and_a_tap_outside_leave_without_saving(
    stack_empty: Stack, admin_tablet: Page
) -> None:
    stack_empty.fake.config["configured"] = False  # a new install: the guide opens by itself
    before = len(stack_empty.fake.saved_configs)
    tablet = admin_tablet
    _open_guide(tablet, stack_empty)
    tablet.locator("#wizard-close").click()
    expect(tablet.locator("#wizard-overlay")).to_be_hidden()

    # The page then offers the guide again.
    expect(tablet.locator("#guide-start")).to_be_visible()
    tablet.locator("#guide-start").click()
    expect(tablet.locator("#wizard-overlay")).to_be_visible()
    tablet.keyboard.press("Escape")
    expect(tablet.locator("#wizard-overlay")).to_be_hidden()

    tablet.locator("#guide-start").click()
    expect(tablet.locator("#wizard-overlay")).to_be_visible()
    tablet.mouse.click(4, 4)  # the veil, outside the window
    expect(tablet.locator("#wizard-overlay")).to_be_hidden()
    assert len(stack_empty.fake.saved_configs) == before


def test_leaving_with_changes_asks_first_and_saves_nothing(
    stack_empty: Stack, admin_tablet: Page
) -> None:
    stack_empty.fake.config["configured"] = False
    before = len(stack_empty.fake.saved_configs)
    tablet = admin_tablet
    _open_guide(tablet, stack_empty)
    tablet.get_by_label("Nome della famiglia").fill("Famiglia di prova")

    tablet.keyboard.press("Escape")
    expect(tablet.locator("#wizard-leave")).to_be_visible()
    expect(tablet.locator("#wizard-leave-title")).to_have_text("Uscire senza salvare?")
    # "Continua" keeps the guide open with the changes.
    tablet.locator("#wizard-leave-stay").click()
    expect(tablet.locator("#wizard-leave")).to_be_hidden()
    expect(tablet.locator("#wizard-overlay")).to_be_visible()
    assert tablet.get_by_label("Nome della famiglia").input_value() == "Famiglia di prova"

    tablet.locator("#wizard-close").click()
    expect(tablet.locator("#wizard-leave")).to_be_visible()
    tablet.locator("#wizard-leave-exit").click()  # "Esci"
    expect(tablet.locator("#wizard-overlay")).to_be_hidden()
    assert len(stack_empty.fake.saved_configs) == before


def test_leaving_puts_the_saved_theme_back(stack_empty: Stack, admin_tablet: Page) -> None:
    stack_empty.fake.config["configured"] = False
    before = len(stack_empty.fake.saved_configs)
    tablet = admin_tablet
    _open_guide(tablet, stack_empty)
    for _ in range(5):
        tablet.locator("#wizard-skip").click()  # to the last step, the screen
    tablet.get_by_label("Tema").select_option("dark")
    assert tablet.evaluate("document.documentElement.getAttribute('data-theme')") == "dark"

    tablet.keyboard.press("Escape")
    tablet.locator("#wizard-leave-exit").click()
    expect(tablet.locator("#wizard-overlay")).to_be_hidden()
    # The theme the family saved (automatic) is back; the preview is gone.
    assert tablet.evaluate("document.documentElement.getAttribute('data-theme')") is None
    assert len(stack_empty.fake.saved_configs) == before


def _luminance(colour: str) -> float:
    numbers = [float(n) for n in re.findall(r"[\d.]+", colour)[:3]]
    red, green, blue = numbers
    return (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255


@pytest.mark.parametrize(
    ("theme", "system", "dark"),
    [
        ("dark", "light", True),
        ("light", "dark", False),
        ("auto", "dark", True),
        ("auto", "light", False),
    ],
    ids=["dark-over-light-system", "light-over-dark-system", "auto-dark", "auto-light"],
)
def test_the_theme_decides_the_colours(
    stack_empty: Stack, admin_tablet: Page, theme: str, system: str, dark: bool
) -> None:
    stack_empty.fake.config["configured"] = False
    stack_empty.fake.config["screen"] = {
        **stack_empty.fake.config.get("screen", {}),
        "theme": theme,
    }
    try:
        tablet = admin_tablet
        tablet.emulate_media(color_scheme=system)
        _open_guide(tablet, stack_empty)
        dialog = tablet.locator("#wizard-overlay .dialog").evaluate(
            "el => getComputedStyle(el).backgroundColor"
        )
        body = tablet.evaluate("getComputedStyle(document.body).backgroundImage")
        if dark:
            assert _luminance(dialog) < 0.15, dialog
            assert "rgb(11, 18, 32)" in body, body  # #0B1220, the night glass
        else:
            assert _luminance(dialog) > 0.3, dialog
            assert "rgb(205, 184, 158)" in body, body  # #CDB89E, the warm glass
    finally:
        stack_empty.fake.config["screen"] = {
            **stack_empty.fake.config.get("screen", {}),
            "theme": "auto",
        }


@pytest.mark.parametrize(("width", "height"), [(320, 640), (390, 844)])
def test_every_screen_fits_in_the_dark_theme(
    stack_full: Stack, browser: Browser, width: int, height: int
) -> None:
    stack_full.fake.config["screen"] = {**stack_full.fake.config.get("screen", {}), "theme": "dark"}
    problems: list[str] = []
    try:
        with _seeded(stack_full), _device(browser, width, height) as page:
            for name, go in _screens(stack_full):
                _open(page, stack_full)
                try:
                    go(page)
                    page.wait_for_timeout(150)
                    for item in page.evaluate(CHECK_JS):
                        problems.append(f"{name}: {item}")
                except Exception as err:  # the screen could not be reached at this size
                    problems.append(
                        f"{name}: could not open ({type(err).__name__}: {str(err)[:120]})"
                    )
    finally:
        stack_full.fake.config["screen"] = {
            **stack_full.fake.config.get("screen", {}),
            "theme": "auto",
        }
    assert not problems, f"dark theme at {width}x{height}:\n" + "\n".join(problems)
