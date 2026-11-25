import re

import pytest

from app.config import SUPPORTED_LANGUAGES
from app.services.i18n import Translator, load_locale, plural_form

PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _placeholders(value: object) -> set[str]:
    if isinstance(value, dict):
        return set().union(*(_placeholders(v) for v in value.values()))
    return set(PLACEHOLDER.findall(str(value)))


def test_all_locales_have_same_keys() -> None:
    reference = set(load_locale("en"))
    for lang in SUPPORTED_LANGUAGES:
        keys = set(load_locale(lang))
        assert keys == reference, f"{lang}: missing={reference - keys} extra={keys - reference}"


@pytest.mark.parametrize("lang", SUPPORTED_LANGUAGES)
def test_placeholders_match_english(lang: str) -> None:
    en = load_locale("en")
    other = load_locale(lang)
    for key, value in en.items():
        assert _placeholders(other[key]) == _placeholders(value), f"{lang}:{key}"


def test_html_tags_balanced() -> None:
    for lang in SUPPORTED_LANGUAGES:
        for key, value in load_locale(lang).items():
            text = str(value)
            for tag in ("b", "i", "code", "a"):
                assert text.count(f"<{tag}") == text.count(f"</{tag}>"), f"{lang}:{key}"


def test_translator_and_fallback() -> None:
    _ = Translator("de")
    assert "Lebenslauf" in _("resume.btn_upload")
    assert _("does.not.exist") == "does.not.exist"
    assert Translator("xx").lang == "en"


@pytest.mark.parametrize(
    ("lang", "n", "form"),
    [("ru", 1, "one"), ("ru", 2, "few"), ("ru", 5, "many"), ("ru", 11, "many"), ("ru", 21, "one"),
     ("uk", 3, "few"), ("en", 1, "one"), ("en", 2, "other"), ("de", 0, "other")],
)
def test_plural_forms(lang: str, n: int, form: str) -> None:
    assert plural_form(lang, n) == form


def test_plural_render() -> None:
    assert Translator("ru").plural("units.years", 2) == "2 лет"
    assert Translator("ru").plural("units.years", 1) == "1 года"
    assert Translator("en").plural("units.years", 1) == "1 year"
