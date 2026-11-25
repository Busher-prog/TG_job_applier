from typing import Any

from app.providers.llm import set_llm
from app.providers.llm.mock_provider import MockLLMProvider
from app.services.cv.heuristic_parser import find_phones, heuristic_parse
from app.services.cv.parser import compute_experience_months, parse_cv_text
from app.services.cv.text_extraction import extract_text
from app.schemas.cv import ParsedCV


def test_heuristic_parse_pdf(sample_pdf: bytes) -> None:
    ext = extract_text(sample_pdf, "pdf")
    data = ParsedCV.model_validate(heuristic_parse(ext.text, ext.links))
    assert data.candidate.full_name == "Anna Berger"
    assert data.candidate.email == "anna.berger@example.com"
    assert data.candidate.linkedin_url and "linkedin.com/in/anna-berger-example" in data.candidate.linkedin_url
    langs = {lang.language: lang.level for lang in data.languages}
    assert langs == {"English": "C1", "German": "A2", "Ukrainian": "Native"}
    assert len(data.experience) == 2
    assert data.experience[0].is_current is True
    assert "CapCut" in data.skills.hard


def test_phone_detection_ignores_date_ranges() -> None:
    assert find_phones("2016 – 2019\n03/2022 – 04/2023") == []
    assert find_phones("Call +49 151 2345678") == ["+49 151 2345678"]


def test_experience_months_merges_overlaps() -> None:
    cv = ParsedCV.model_validate(
        {"experience": [
            {"company": "A", "start_date": "2020-01", "end_date": "2021-01"},
            {"company": "B", "start_date": "2020-07", "end_date": "2021-07"},
            {"company": "C", "start_date": "2023-01", "end_date": "2023-07", "employment_type": "volunteer"},
        ]}
    )
    assert compute_experience_months(cv) == 18


class HallucinatingLLM(MockLLMProvider):
    async def _complete_json(self, **kwargs: Any):  # type: ignore[override]
        data, usage = await super()._complete_json(**kwargs)
        data["candidate"]["email"] = "invented@fake.example"
        data["candidate"]["portfolio_url"] = "https://invented.example.net"
        data["candidate"]["phone"] = "+1 555 000 9999"
        return data, usage


async def test_grounding_removes_invented_contacts(sample_pdf: bytes) -> None:
    set_llm(HallucinatingLLM())
    ext = extract_text(sample_pdf, "pdf")
    parsed = await parse_cv_text(ext.text, ext.links)
    assert parsed.candidate.email == "anna.berger@example.com"  # restored from document
    assert parsed.candidate.portfolio_url is None
    assert parsed.candidate.phone == "+43 660 1234567"
    assert parsed.total_experience_months and parsed.total_experience_months > 50
