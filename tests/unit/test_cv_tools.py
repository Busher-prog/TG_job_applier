from app.schemas.cv import ParsedCV
from app.schemas.resume import ResumeDocument
from app.services.cv.builder_state import BuilderDraft
from app.services.cv.editing import apply_operations, rule_based_intent
from app.services.cv.interview import (
    InterviewExtraction,
    find_tools,
    ground_contacts,
    heuristic_extract,
    merge_extraction,
    missing_experience_fields,
)
from app.services.cv.optimizer import ats_checks


def doc() -> ResumeDocument:
    return ResumeDocument.model_validate({
        "candidate": {"full_name": "A B", "email": "a@example.com"},
        "professional_summary": "Summary",
        "experience": [{"id": "exp1", "company": "X", "job_title": "Y", "bullets": ["b"]}],
        "education": [{"id": "edu1", "institution": "Uni"}],
        "skills": ["s"],
        "languages": [{"language": "English", "level": "B2"}],
        "section_order": ["professional_summary", "education", "experience", "skills", "languages"],
    })


def test_spec_edit_examples() -> None:
    d = doc()
    out = apply_operations(d, rule_based_intent("Перемести образование ниже."))
    assert out.doc.section_order.index("education") > out.doc.section_order.index("experience")
    assert not out.regenerate
    out = apply_operations(d, rule_based_intent("Сделай акцент на видеомонтаже."))
    assert out.regenerate and "видеомонтаже" in out.instructions[0]
    out = apply_operations(d, rule_based_intent("Сократи описание работы в ресторане."))
    assert out.regenerate and "ресторане" in out.instructions[0]
    out = apply_operations(d, rule_based_intent("Добавь портфолио https://folio.example.com/me"))
    assert out.doc.candidate.portfolio_url == "https://folio.example.com/me"
    assert "portfolio" in out.doc.section_order and out.profile_updates["portfolio"]
    out = apply_operations(d, rule_based_intent("Сделай резюме на одну страницу."))
    assert out.doc.page_limit == 1 and out.regenerate


def test_add_facts_request_is_flagged() -> None:
    assert rule_based_intent("Добавь опыт работы в Google").needs_new_facts


def test_invalid_link_rejected() -> None:
    from app.services.cv.editing import EditIntent, EditOperation

    out = apply_operations(doc(), EditIntent(operations=[EditOperation(op="add_link", value="javascript:alert(1)")]))
    assert out.applied == 0 and out.errors == ["invalid_url"]


def test_ats_checks() -> None:
    parsed = ParsedCV.model_validate({"candidate": {"full_name": "A"}, "experience": [{"company": "X"}]})
    report = ats_checks(parsed, "short text", "ocr")
    assert {"no_email", "missing_dates", "scanned", "too_short"} <= set(report.issues)
    assert report.ats_score < 50
    good = ParsedCV.model_validate({
        "candidate": {"full_name": "A", "email": "a@example.com", "phone": "+43 660 1234567"},
        "summary": "Summary",
        "experience": [{"company": "X", "start_date": "2020", "responsibilities": ["Grew sales 20%", "Led team"]}],
        "skills": {"hard": ["Sales"]}, "languages": [{"language": "English"}],
    })
    assert ats_checks(good, "\n\n".join(["word " * 30] * 10)).ats_score == 100


def test_interview_multi_fact_answer() -> None:
    answer = "Anna Berger, anna@example.com, +43 660 1234567"
    ext = InterviewExtraction.model_validate(heuristic_extract("name", answer))
    ext.candidate = ground_contacts(ext.candidate, answer)
    assert ext.candidate.full_name == "Anna Berger"
    assert ext.candidate.email == "anna@example.com" and ext.candidate.phone == "+43 660 1234567"


def test_interview_contact_grounding_blocks_invention() -> None:
    ext = InterviewExtraction.model_validate({"candidate": {"email": "made-up@example.com"}})
    assert ground_contacts(ext.candidate, "I don't have email").email is None


def test_experience_extraction_and_followups() -> None:
    facts = ParsedCV()
    ext = InterviewExtraction.model_validate(heuristic_extract(
        "experience", "Video editor at Pixel Studio 03/2022 - present. Edited reels in CapCut; managed archive"))
    idx = merge_extraction(facts, ext, "experience")
    item = facts.experience[idx]
    assert item.job_title == "Video editor" and item.company == "Pixel Studio"
    assert item.is_current and item.start_date == "2022-03"
    assert "CapCut" in item.tools
    assert missing_experience_fields(item) == []
    vague = InterviewExtraction.model_validate(heuristic_extract("experience", "Barista"))
    idx2 = merge_extraction(facts, vague, "experience")
    assert missing_experience_fields(facts.experience[idx2]) == ["company", "dates", "responsibilities"]
    follow = InterviewExtraction.model_validate(heuristic_extract("exp_followup", "Cafe Uno", "company"))
    merge_extraction(facts, follow, "exp_followup", idx2)
    assert facts.experience[idx2].company == "Cafe Uno"


def test_find_tools() -> None:
    assert find_tools("I use Adobe Premiere Pro and capcut daily") == ["Adobe Premiere Pro", "CapCut"]


def test_builder_skips_known_answers() -> None:
    d = BuilderDraft(facts=ParsedCV.model_validate({
        "candidate": {"full_name": "A B", "email": "a@example.com", "city": "Wien"},
        "experience": [{"company": "X", "job_title": "Y"}],
    }))
    d.prefill_from_facts("de")
    assert d.next_stage() == "phone"
    d.mark_done("phone")
    assert d.next_stage() == "linkedin"
    for s in ("linkedin", "portfolio"):
        d.mark_done(s)
    assert d.next_stage() == "direction"
    d.direction = "known"
    d.mark_done("direction")
    assert d.next_stage() == "target_role"
    d.target_roles = ["Editor"]
    assert d.next_stage() == "exp_more"
