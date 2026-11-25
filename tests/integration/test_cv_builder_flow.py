"""Phase 2 end-to-end: CV builder interview, preview edits, versions, optimizer, examples."""

import io

import pdfplumber
import pytest
from sqlalchemy import func, select

from app.bot.keyboards.callbacks import BuilderCb, PreviewCb
from app.database.models import CandidateProfile, Resume, ResumeVersion, User
from app.database.models.enums import OnboardingStep
from app.schemas.resume import ResumeDocument
from tests.bot_harness import BotHarness

pytestmark = pytest.mark.integration


@pytest.fixture
def harness(dispatcher, session_factory):  # type: ignore[no-untyped-def]
    dispatcher.storage.storage.clear()
    return BotHarness(dispatcher, user_id=901, language_code="ru")


def pdf_text(doc_file) -> str:  # type: ignore[no-untyped-def]
    with pdfplumber.open(io.BytesIO(doc_file.data)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


async def _latest(session_factory) -> tuple[Resume, ResumeVersion, ResumeDocument]:  # type: ignore[no-untyped-def]
    async with session_factory() as s:
        resume = await s.scalar(select(Resume).order_by(Resume.id.desc()).limit(1))
        version = await s.get(ResumeVersion, resume.current_version_id)
        return resume, version, ResumeDocument.model_validate(version.content)


def b(action: str, value: str = "") -> str:
    return BuilderCb(action=action, value=value).pack()


async def test_builder_interview_to_preview_and_edits(harness, session_factory):  # type: ignore[no-untyped-def]
    await harness.send("/start")
    await harness.click("cns:agree")
    calls = await harness.click("ro:create")
    texts = harness.texts(calls)
    assert any("Давай создадим профессиональное резюме" in t for t in texts)
    assert "Как тебя зовут" in texts[-1]

    # Several facts in one answer: email and phone must not be asked again.
    calls = await harness.send("Olena Shevchenko, olena@example.com, +43 660 7654321")
    assert "В каком городе" in harness.texts(calls)[-1]
    calls = await harness.send("Вена, Австрия")
    assert "LinkedIn" in harness.texts(calls)[-1]
    calls = await harness.click(b("skip"))
    assert "портфолио" in harness.texts(calls)[-1]
    calls = await harness.send("https://olena-video.example.com")
    assert "Какую работу ты хотел бы найти" in harness.texts(calls)[-1]
    calls = await harness.click(b("dir", "known"))
    calls = await harness.send("Video Editor")
    assert "последнем или текущем месте работы" in harness.texts(calls)[-1]

    # Vague answer -> only the missing details are asked.
    calls = await harness.send("Монтажер видео")
    assert "Как называется компания" in harness.texts(calls)[-1]
    calls = await harness.send("Pixel Studio")
    assert "Когда ты там работал" in harness.texts(calls)[-1]
    calls = await harness.send("03/2022 – по настоящее время")
    assert "основные задачи" in harness.texts(calls)[-1]
    calls = await harness.send("Монтаж рилсов в CapCut и Premiere Pro; цветокоррекция")
    assert "Твой опыт работы" in harness.texts(calls)[-1]
    calls = await harness.click(b("next"))
    # Adaptive profession questions (video bank in MOCK_MODE).
    assert "В каких программах ты работаешь" in harness.texts(calls)[-1]
    calls = await harness.send("DaVinci Resolve, After Effects")
    assert "Вопрос 2 из 4" in harness.texts(calls)[-1]
    for _ in range(3):
        calls = await harness.click(b("skip"))
    assert "Расскажи об образовании" in harness.texts(calls)[-1]
    calls = await harness.send("Київський університет, бакалавр, журналістика, 2015 – 2019")
    assert "Твоё образование" in harness.texts(calls)[-1]
    calls = await harness.click(b("next"))
    assert "навыками и программами" in harness.texts(calls)[-1]
    buttons = harness.buttons(calls)
    first_skill = next(k for k, v in buttons.items() if v.startswith("b:skill"))
    calls = await harness.click(buttons[first_skill])
    assert "✓ " + first_skill in harness.buttons(calls)
    await harness.send("Storytelling, Color grading")
    calls = await harness.click(b("skills_done"))
    assert "Какими языками" in harness.texts(calls)[-1]
    calls = await harness.send("English - C1\nDeutsch - A2")
    assert "сертификаты" in harness.texts(calls)[-1]
    calls = await harness.click(b("skip"))
    assert "На каком языке создать" in harness.texts(calls)[-1]
    calls = await harness.click(b("lang", "en"))
    assert "⭐ Creative" in harness.buttons(calls)  # recommended for video roles
    calls = await harness.click(b("tpl", "auto"))

    docs = harness.documents(calls)
    assert len(docs) == 1
    text = pdf_text(docs[0])
    for fact in ("Olena Shevchenko", "olena@example.com", "Pixel Studio", "English", "DaVinci Resolve"):
        assert fact in text
    assert any("Твоё CV готово" in t for t in harness.texts(calls))
    resume, version, doc = await _latest(session_factory)
    assert resume.kind == "generated" and version.version_number == 1 and doc.template == "creative"
    async with session_factory() as s:
        profile = await s.scalar(select(CandidateProfile))
        assert profile.target_roles == ["Video Editor"]
        assert "builder" not in profile.extra  # draft cleared

    # Natural-language edits from the spec.
    order_before = doc.visible_sections()
    calls = await harness.send("Перемести образование ниже.")
    _r, v2, doc2 = await _latest(session_factory)
    assert v2.version_number == 2
    assert doc2.visible_sections().index("education") == order_before.index("education") + 1
    calls = await harness.send("Сделай резюме на одну страницу.")
    _r, v3, doc3 = await _latest(session_factory)
    assert doc3.page_limit == 1 and v3.page_count == 1
    calls = await harness.send("Добавь портфолио https://vimeo.com/olena")
    _r, _v4, doc4 = await _latest(session_factory)
    assert any(p.url == "https://vimeo.com/olena" for p in doc4.portfolio)

    # Buttons: design, language, DOCX, versions restore.
    rid = resume.id
    await harness.click(PreviewCb(action="tpl", resume_id=rid, value="classic_ats").pack())
    _r, _v5, doc5 = await _latest(session_factory)
    assert doc5.template == "classic_ats"
    calls = await harness.click(PreviewCb(action="lang", resume_id=rid, value="de").pack())
    assert "Berufserfahrung" in pdf_text(harness.documents(calls)[0])
    calls = await harness.click(PreviewCb(action="docx", resume_id=rid).pack())
    assert harness.documents(calls)[0].filename.endswith(".docx")
    calls = await harness.click(PreviewCb(action="versions", resume_id=rid).pack())
    v1_button = next(v for k, v in harness.buttons(calls).items() if k.lstrip("• ").startswith("v1 "))
    await harness.click(v1_button)
    _r, v_restored, doc_restored = await _latest(session_factory)
    assert doc_restored.template == "creative" and v_restored.version_number == 7

    calls = await harness.click(PreviewCb(action="confirm", resume_id=rid).pack())
    assert any("Твоё резюме проанализировано" in t for t in harness.texts(calls))
    async with session_factory() as s:
        user = await s.scalar(select(User))
        assert user.onboarding_step == OnboardingStep.PROFILE_CONFIRM
        assert (await s.get(Resume, rid)).is_primary


async def test_builder_progress_survives_and_resumes(harness, session_factory):  # type: ignore[no-untyped-def]
    await harness.send("/start")
    await harness.click("cns:agree")
    await harness.click("ro:create")
    await harness.send("Max Muster")
    await harness.send("/help")  # leave mid-interview
    calls = await harness.send("/createcv")
    assert "незаконченное CV" in harness.texts(calls)[-1]
    calls = await harness.click(b("resume"))
    assert "email" in harness.texts(calls)[-1].lower()
    calls = await harness.click(b("back"))
    assert "Как тебя зовут" in harness.texts(calls)[-1]


async def test_no_experience_path(harness, session_factory):  # type: ignore[no-untyped-def]
    await harness.send("/start")
    await harness.click("cns:agree")
    await harness.click("ro:create")
    await harness.send("Lisa Neu lisa@example.com")
    for _ in range(4):
        await harness.click(b("skip"))
    await harness.click(b("dir", "exploring"))
    calls = await harness.click(b("noexp"))
    assert "учебные проекты" in harness.texts(calls)[-1]


async def test_optimizer_flow(harness, session_factory, sample_pdf):  # type: ignore[no-untyped-def]
    await harness.send("/start")
    await harness.click("cns:agree")
    await harness.click("ro:improve")
    calls = await harness.send_document(sample_pdf, "old_cv.pdf", "application/pdf")
    report = harness.texts(calls)[-1]
    assert "Читаемость для ATS (ориентировочно)" in report and "/100" in report
    assert "не гарантирует" in report
    buttons = harness.buttons(calls)
    calls = await harness.click(buttons["💬 Ответить на уточняющие вопросы"])
    assert "Вопрос 1 из" in harness.texts(calls)[-1]
    calls = await harness.send("Использую DaVinci Resolve и CapCut")
    for _ in range(5):
        if harness.documents(calls):
            break
        calls = await harness.click(next(v for k, v in harness.buttons(calls).items() if v.startswith("op:qskip")))
    assert harness.documents(calls), "optimizer should produce an improved CV"
    resume, _v, doc = await _latest(session_factory)
    assert resume.kind == "optimized" and resume.parent_resume_id is not None
    assert doc.candidate.full_name == "Anna Berger"


async def test_examples_and_create_similar(harness):  # type: ignore[no-untyped-def]
    await harness.send("/start")
    await harness.click("cns:agree")
    calls = await harness.click("ro:examples")
    photos = [c for c in calls if type(c).__name__ == "SendPhoto"]
    docs = harness.documents(calls)
    assert len(photos) == 3 and len(docs) == 3
    assert all(d.data.startswith(b"%PDF") for d in docs)
    calls = await harness.click(harness.buttons(calls)["✨ Создать похожее: Modern Professional"])
    assert "Как тебя зовут" in harness.texts(calls)[-1]


async def test_resume_isolation_between_users(dispatcher, session_factory, sample_pdf):  # type: ignore[no-untyped-def]
    owner = BotHarness(dispatcher, user_id=1001, language_code="en")
    await owner.send("/start")
    await owner.click("cns:agree")
    await owner.send_document(sample_pdf, "cv.pdf", "application/pdf")
    async with session_factory() as s:
        rid = await s.scalar(select(func.max(Resume.id)))
    intruder = BotHarness(dispatcher, user_id=1002, language_code="en")
    await intruder.send("/start")
    await intruder.click("cns:agree")
    calls = await intruder.click(f"cv:download:{rid}")
    assert not intruder.documents(calls)
    assert any("couldn't find" in a for a in intruder.alerts(calls))
