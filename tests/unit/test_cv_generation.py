import io

import pdfplumber
import pytest

from app.providers.llm import set_llm
from app.providers.llm.mock_provider import MockLLMProvider
from app.schemas.cv import ParsedCV
from app.schemas.resume import GeneratedContent, ResumeDocument
from app.services.cv.facts import facts_payload
from app.services.cv.generator import assemble_document, deterministic_summary, generate_resume
from app.services.cv.structure import rule_based_plan, sanitize_plan


def facts(**kw) -> ParsedCV:  # type: ignore[no-untyped-def]
    base = {
        "candidate": {"full_name": "Iryna Test", "email": "iryna@example.com", "city": "Graz", "country": "Austria"},
        "experience": [
            {"company": "Cafe Uno", "job_title": "Waitress", "start_date": "2019-01", "end_date": "2021-12",
             "responsibilities": ["Served guests", "Handled cash register"]},
            {"company": "Pixel Studio", "job_title": "Video Editor", "start_date": "2022-01", "is_current": True,
             "responsibilities": ["Edited 30 reels per month", "Colour grading"], "tools": ["DaVinci Resolve"]},
        ],
        "education": [{"institution": "FH Graz", "degree": "BA", "start_date": "2015", "end_date": "2018"}],
        "skills": {"hard": ["Video editing"], "software": ["DaVinci Resolve", "CapCut"], "soft": ["Teamwork"]},
        "languages": [{"language": "German", "level": "B2"}],
        "total_experience_months": 70,
    }
    base.update(kw)
    return ParsedCV.model_validate(base)


def test_plan_types() -> None:
    assert rule_based_plan(facts(), ["Logistics Manager"]).profile_type == "career_change"
    creative = rule_based_plan(facts(candidate={"full_name": "X", "email": "x@example.com",
                                                "portfolio_url": "https://p.example.com"}), ["Video Editor"])
    assert creative.profile_type == "creative" and creative.section_order[1] == "portfolio"
    student = rule_based_plan(facts(experience=[], total_experience_months=0,
                                    education=[{"institution": "Uni", "status": "in_progress"}]), [])
    assert student.profile_type == "student" and student.section_order[1] == "education"
    exp = rule_based_plan(facts(), [])
    assert exp.profile_type == "experienced" and exp.section_order[:2] == ["professional_summary", "experience"]


def test_career_change_keeps_irrelevant_experience_secondary() -> None:
    f = facts()
    plan = sanitize_plan(rule_based_plan(f, ["Video Editor"], direction="change"), f)
    assert plan.relevant_experience_ids == ["exp2"]
    assert plan.additional_experience_ids == ["exp1"]  # not dropped, just not central
    doc = assemble_document(f, plan, None, template="classic_ats", language="en", target_roles=["Video Editor"])
    assert [e.company for e in doc.experience] == ["Pixel Studio"]
    assert [e.company for e in doc.additional_experience] == ["Cafe Uno"]


def test_sanitize_plan_never_drops_employers() -> None:
    f = facts()
    plan = rule_based_plan(f, [])
    plan.relevant_experience_ids = ["exp9"]
    plan.additional_experience_ids = []
    assert sanitize_plan(plan, f).relevant_experience_ids == ["exp1", "exp2"]


def test_assembly_enforces_facts() -> None:
    f = facts()
    plan = sanitize_plan(rule_based_plan(f, []), f)
    content = GeneratedContent.model_validate({
        "professional_summary": "Video editor who grew revenue by 300% for 50 clients.",  # invented numbers
        "experience": [
            {"id": "exp2", "bullets": ["Edited 30 reels per month for brand accounts", "Increased views by 250%"]},
            {"id": "exp1", "bullets": ["Served guests"]},
        ],
        "skills": ["Video editing", "Kubernetes"],  # invented skill
        "software": ["DaVinci Resolve", "Avid Media Composer"],
    })
    doc = assemble_document(f, plan, content, template="modern", language="en", target_roles=[])
    current = doc.experience[0]
    assert current.company == "Pixel Studio" and current.start_date == "2022-01" and current.is_current
    assert current.bullets == ["Edited 30 reels per month for brand accounts"]
    assert "300" not in (doc.professional_summary or "")
    assert doc.skills == ["Video editing"]
    assert doc.software == ["DaVinci Resolve"]
    assert [e.company for e in doc.experience] == ["Pixel Studio", "Cafe Uno"]  # reverse chronological


@pytest.mark.parametrize("lang", ["en", "de", "ru", "uk"])
def test_deterministic_summary_languages(lang: str) -> None:
    text = deterministic_summary(facts(), ["Video Editor"], lang)
    assert "Waitress" in text or "Video Editor" in text
    assert "5" in text  # 70 months -> 5 years


def test_facts_payload_has_ids() -> None:
    data = facts_payload(facts())
    assert [e["id"] for e in data["experience"]] == ["exp1", "exp2"]


async def test_generate_and_render_all_templates() -> None:
    from app.services.cv.renderer import render_docx, render_pdf

    set_llm(MockLLMProvider())
    f = facts(candidate={"full_name": "Іван Петренко", "email": "ivan@example.com",
                         "linkedin_url": "https://www.linkedin.com/in/ivan-example"})
    for template in ("classic_ats", "modern", "creative"):
        for lang in ("en", "uk"):
            doc, _plan = await generate_resume(f, target_roles=["Video Editor"], language=lang, template=template)
            result = render_pdf(doc)
            assert result.missing == [], (template, lang, result.missing)
            with pdfplumber.open(io.BytesIO(result.pdf)) as pdf:
                text = pdf.pages[0].extract_text()
                uris = [h["uri"] for p in pdf.pages for h in p.hyperlinks]
                width, height = pdf.pages[0].width, pdf.pages[0].height
            assert "Іван Петренко" in text and "Pixel Studio" in text
            assert text.index("Іван Петренко") < text.index("Pixel Studio")  # reading order
            assert "https://www.linkedin.com/in/ivan-example" in uris  # clickable links
            assert abs(width - 595) < 2 and abs(height - 842) < 2  # A4
            import docx

            d = docx.Document(io.BytesIO(render_docx(doc)))
            assert "Іван Петренко" in "\n".join(p.text for p in d.paragraphs)


def test_page_limit_compaction() -> None:
    from app.services.cv.renderer import render_pdf

    long_doc = ResumeDocument.model_validate({
        "candidate": {"full_name": "Long Example", "email": "long@example.com"},
        "professional_summary": "Summary. " * 30,
        "experience": [
            {"id": f"exp{i}", "company": f"Company {i}", "job_title": "Engineer", "start_date": "2010",
             "end_date": "2012", "bullets": [f"Did important thing number {j} for the team" for j in range(8)]}
            for i in range(9)
        ],
        "section_order": ["professional_summary", "experience"],
        "page_limit": 1,
    })
    unlimited = render_pdf(long_doc.model_copy(update={"page_limit": None}))
    limited = render_pdf(long_doc)
    assert unlimited.page_count >= 2
    assert limited.density > 0
    assert limited.missing == []


def test_html_is_escaped() -> None:
    from app.services.cv.renderer import render_html

    doc = ResumeDocument.model_validate({
        "candidate": {"full_name": "<script>alert(1)</script> Name", "email": "a@example.com"},
        "professional_summary": "<img src=x onerror=alert(1)>",
        "section_order": ["professional_summary"],
    })
    html = render_html(doc)
    assert "<script>alert" not in html and "<img src=x" not in html


def test_document_requires_contact() -> None:
    with pytest.raises(ValueError):
        ResumeDocument.model_validate({"candidate": {"full_name": "No Contact"}})
