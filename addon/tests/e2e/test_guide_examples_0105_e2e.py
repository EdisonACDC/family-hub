"""0.10.5b1: the guide's example for the family name is written in each language (it, de, en): the
text the wizard draws for the Family step has no placeholder from another language."""

from __future__ import annotations

import pytest
from playwright.sync_api import Browser

from tests.e2e.conftest import Stack
from tests.e2e.test_tablet import _device


@pytest.mark.parametrize(
    ("language", "example", "other_examples"),
    [
        ("it", "Famiglia Rossi", ["Familie Müller", "The Smith family", "Esempio family"]),
        ("de", "Familie Müller", ["Famiglia Rossi", "The Smith family", "Esempio family"]),
        ("en", "The Smith family", ["Famiglia Rossi", "Familie Müller", "Esempio family"]),
    ],
)
def test_the_family_example_is_in_the_language(
    stack_empty: Stack, browser: Browser, language: str, example: str, other_examples: list[str]
) -> None:
    with _device(browser, 1280, 800) as page:
        # The language comes from the integration's settings, so the test sets them.
        stack_empty.fake.config["family"] = {
            **stack_empty.fake.config.get("family", {}),
            "language": language,
        }
        page.goto(stack_empty.url + f"/?lang={language}")
        page.wait_for_function("lang => window.FH_I18N.lang === lang", arg=language)
        # Step 0 is the Family step; its example is the one the wizard draws.
        text = page.evaluate("() => window.FH_I18N.steps[0][2]")
        assert example in text, f"{language}: {text!r}"
        for other in other_examples:
            assert other not in text, f"{language}: shows {other!r}"
