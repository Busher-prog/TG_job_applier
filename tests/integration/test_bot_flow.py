"""End-to-end conversation through the real Dispatcher, DB and handlers."""

import json
import re

import pytest
from sqlalchemy import func, select

from app.bot.factory import create_dispatcher
from app.bot.keyboards.callbacks import ProfileCb
from app.database.models import ConsentRecord, Resume, User
from app.database.models.enums import OnboardingStep
from tests.bot_harness import BotHarness

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def dispatcher(engine):  # type: ignore[no-untyped-def]
    from sqlalchemy.ext.asyncio import async_sessionmaker

    return create_dispatcher(async_sessionmaker(engine, expire_on_commit=False))


@pytest.fixture
def harness(dispatcher, session_factory):  # type: ignore[no-untyped-def]
    dispatcher.storage.storage.clear()  # fresh FSM per test (MemoryStorage)
    return BotHarness(dispatcher, user_id=555, language_code="ru")


async def _user(session_factory) -> User:  # type: ignore[no-untyped-def]
    async with session_factory() as s:
        return await s.scalar(select(User).where(User.telegram_id == 555))


async def test_full_phase1_onboarding(harness, session_factory, sample_pdf):  # type: ignore[no-untyped-def]
    calls = await harness.send("/start")
    assert "AI Job Copilot" in harness.texts(calls)[0]
    btns = harness.buttons(calls)
    assert set(btns) == {"🚀 Начать", "ℹ️ Как это работает", "🌐 Выбрать язык"}

    # Language switch to English and back to Russian.
    calls = await harness.click(btns["🌐 Выбрать язык"])
    calls = await harness.click(harness.buttons(calls)["English"])
    assert "Hi! I'm AI Job Copilot" in harness.texts(calls)[-1]
    calls = await harness.click("lng:ui:ru")
    assert "Привет" in harness.texts(calls)[-1]

    # Uploading before consent is blocked.
    calls = await harness.send_document(sample_pdf, "cv.pdf", "application/pdf")
    assert any("условия обработки данных" in t for t in harness.texts(calls))
    async with session_factory() as s:
        assert await s.scalar(select(func.count()).select_from(Resume)) == 0

    calls = await harness.click("nav:consent")
    assert "Политикой конфиденциальности" in harness.texts(calls)[-1]
    assert "https://copilot.example.com/privacy?lang=ru" in harness.texts(calls)[-1]
    calls = await harness.click("cns:agree")
    text = harness.texts(calls)[-1]
    assert "Шаг 1 из 6" in text and "мне понадобится твоё резюме" in text
    assert set(harness.buttons(calls)) >= {
        "📤 Загрузить своё CV", "✨ Создать CV с помощью AI", "🛠 Улучшить существующее CV",
        "👀 Посмотреть пример хорошего CV",
    }
    async with session_factory() as s:
        consents = (await s.scalars(select(ConsentRecord))).all()
        assert {c.consent_type for c in consents} == {"privacy_policy", "data_processing"}

    calls = await harness.click("ro:upload")
    assert "PDF" in harness.texts(calls)[-1]
    calls = await harness.send("просто текст")
    assert "файлом" in harness.texts(calls)[-1]

    calls = await harness.send_document(sample_pdf, "Anna.pdf", "application/pdf")
    summary = harness.texts(calls)[-1]
    assert "Твоё резюме проанализировано" in summary
    assert "Anna Berger" in summary and "English:</b> C1" in summary and "German:</b> A2" in summary
    assert re.search(r"Опыт:</b> более \d+ (лет|года)", summary)
    assert set(harness.buttons(calls)) == {"✅ Всё верно", "✏️ Изменить данные", "📤 Загрузить другое CV"}
    assert (await _user(session_factory)).onboarding_step == OnboardingStep.PROFILE_CONFIRM

    # Edit email with invalid then valid input.
    calls = await harness.click(ProfileCb(action="edit").pack())
    assert "📧" not in harness.texts(calls)[-1] and "Что ты хочешь изменить?" in harness.texts(calls)[-1]
    await harness.click(ProfileCb(action="field", field="email").pack())
    calls = await harness.send("not-an-email")
    assert "некорректный email" in harness.texts(calls)[-1]
    calls = await harness.send("anna.new@example.com")
    assert "Сохранено" in harness.texts(calls)[0]

    # Leaving to the main menu mid-onboarding keeps progress.
    calls = await harness.send("/start")
    assert "С возвращением" in harness.texts(calls)[-1]
    calls = await harness.click("nav:continue")
    assert "Твоё резюме проанализировано" in harness.texts(calls)[-1]

    calls = await harness.click(ProfileCb(action="ok").pack())
    user = await _user(session_factory)
    assert user.onboarding_step == OnboardingStep.TARGET_JOBS

    calls = await harness.send("/profile")
    assert "anna.new@example.com" in harness.texts(calls)[-1]


async def test_cv_list_download_delete(harness, session_factory, sample_docx):  # type: ignore[no-untyped-def]
    await harness.send("/start")
    await harness.click("cns:agree")
    await harness.send_document(sample_docx, "Oleh.docx",
                                "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    calls = await harness.send("/cv")
    btns = harness.buttons(calls)
    item = next(k for k in btns if k.startswith("Oleh.docx"))
    calls = await harness.click(btns[item])
    calls = await harness.click(harness.buttons(calls)["⬇️ Скачать"])
    assert any(type(c).__name__ == "SendDocument" for c in calls)
    calls = await harness.click(btns[item].replace("open", "delete_yes"))
    async with session_factory() as s:
        assert await s.scalar(select(func.count()).select_from(Resume)) == 0


async def test_settings_languages_export_and_delete(harness, session_factory, sample_pdf):  # type: ignore[no-untyped-def]
    await harness.send("/start")
    await harness.click("cns:agree")
    await harness.send_document(sample_pdf, "cv.pdf", "application/pdf")
    await harness.click("lng:cv:de")
    await harness.click("lng:letter:auto")
    calls = await harness.send("/settings")
    assert "Язык CV: Deutsch" in harness.texts(calls)[-1]
    assert "Язык писем: Как в вакансии" in harness.texts(calls)[-1]
    user = await _user(session_factory)
    assert user.interface_language == "ru" and user.cv_language == "de" and user.letter_language == "auto"

    calls = await harness.click("st:export")
    doc = next(c for c in calls if type(c).__name__ == "SendDocument")
    exported = json.loads(doc.document.data)  # type: ignore[attr-defined]
    assert exported["profile"]["full_name"] == "Anna Berger"
    assert "extracted_text" not in exported["resumes"][0]

    await harness.click("st:delete_yes")
    async with session_factory() as s:
        assert await s.scalar(select(func.count()).select_from(User)) == 0
        assert await s.scalar(select(func.count()).select_from(Resume)) == 0


async def test_commands_work_from_any_state(harness):  # type: ignore[no-untyped-def]
    await harness.send("/start")
    await harness.click("cns:agree")
    await harness.click("ro:upload")
    calls = await harness.send("/help")
    assert "/createcv" in harness.texts(calls)[-1]
    calls = await harness.send("hello")  # no longer waiting for a file
    assert "Я не совсем понял" in harness.texts(calls)[-1]


async def test_unsupported_file_shows_friendly_error(harness):  # type: ignore[no-untyped-def]
    await harness.send("/start")
    await harness.click("cns:agree")
    calls = await harness.send_document(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 64, "old.doc", "application/msword")
    assert "старый формат .doc" in harness.texts(calls)[-1]
