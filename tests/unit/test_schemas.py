import pytest

from app.schemas.common import normalize_email, normalize_partial_date, normalize_phone, normalize_url
from app.schemas.cv import ExperienceItem, LanguageItem, ParsedCV, normalize_level


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("2023-04", "2023-04"), ("04/2023", "2023-04"), ("4.2023", "2023-04"), ("2023", "2023"),
     ("Mar 2021", "2021-03"), ("März 2021", "2021-03"), ("13/2023", None), ("present", None),
     ("sometime", None), (None, None), ("1900", None), ("12.05.2020", "2020-05")],
)
def test_partial_dates(raw: object, expected: str | None) -> None:
    assert normalize_partial_date(raw) == expected


def test_urls_and_contacts() -> None:
    assert normalize_url("linkedin.com/in/x") == "https://linkedin.com/in/x"
    assert normalize_url("javascript:alert(1)") is None
    assert normalize_url("not a url") is None
    assert normalize_email("Mailto:A.B@Example.COM") == "a.b@example.com"
    assert normalize_email("a@b") is None
    assert normalize_phone("+43 660 1234567") == "+43 660 1234567"
    assert normalize_phone("123") is None


def test_language_level_not_invented() -> None:
    assert normalize_level("C1 (advanced)") == "C1"
    assert normalize_level("Muttersprache") == "Native"
    assert normalize_level("good") == "Unknown"
    assert LanguageItem(language="english", level=None).level == "Unknown"


def test_experience_present_and_chronology() -> None:
    e = ExperienceItem(company="X", start_date="2022-01", end_date="heute")
    assert e.is_current and e.end_date is None
    bad = ExperienceItem(company="X", start_date="2022-05", end_date="2021-01")
    assert bad.end_date is None


def test_parsed_cv_drops_empty_and_dedupes() -> None:
    cv = ParsedCV.model_validate(
        {
            "experience": [{"responsibilities": ["x"]}, {"company": "Acme"}],
            "languages": [{"language": "English", "level": "Unknown"}, {"language": "english", "level": "B2"}],
            "candidate": {"email": "broken", "other_links": ["https://a.example.com", "nope"]},
        }
    )
    assert len(cv.experience) == 1
    assert cv.languages[0].level == "B2" and len(cv.languages) == 1
    assert cv.candidate.email is None
    assert cv.candidate.other_links == ["https://a.example.com"]
