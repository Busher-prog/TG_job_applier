import pytest
from sqlalchemy import func, select

from app.database.models import AuditLog, CandidateProfile, Resume
from app.database.repositories.profiles import ProfileRepository
from app.providers.llm import LLMError, set_llm
from app.providers.llm.mock_provider import MockLLMProvider
from app.providers.storage import get_storage
from app.services.cv.file_validation import CVFileError
from app.services.cv.upload import process_cv_upload
from app.services.users.service import get_or_create_user

pytestmark = pytest.mark.integration


async def test_pdf_upload_creates_profile(session, sample_pdf):  # type: ignore[no-untyped-def]
    user, _ = await get_or_create_user(session, 1, "u", "U", "en")
    result = await process_cv_upload(session, user.id, sample_pdf, "Anna CV.pdf")
    await session.commit()

    assert result.used_ai
    assert result.resume.status == "ready" and result.resume.is_primary
    assert await get_storage().get(result.resume.original_file_key) == sample_pdf

    profile = await ProfileRepository(session).get_full(user.id)
    assert profile is not None
    assert profile.full_name == "Anna Berger"
    assert profile.email == "anna.berger@example.com"
    assert [e.company for e in profile.experiences][:1] == ["Bright Media GmbH"]
    assert {lang.language for lang in profile.languages} == {"English", "German", "Ukrainian"}
    assert any(s.name == "CapCut" for s in profile.skills)
    assert profile.total_experience_months and profile.total_experience_months >= 50
    # Audit entries carry no personal data.
    logs = (await session.scalars(select(AuditLog).where(AuditLog.action == "cv.uploaded"))).all()
    assert logs and "anna" not in str(logs[0].meta).lower()


async def test_reupload_replaces_cv_sections_keeps_user_skills(session, sample_pdf, sample_docx):  # type: ignore[no-untyped-def]
    from app.services.users.profile_edit import update_profile_field

    user, _ = await get_or_create_user(session, 2, None, None, "de")
    await process_cv_upload(session, user.id, sample_pdf, "a.pdf")
    await update_profile_field(session, user.id, "software", "Final Cut Pro")
    await process_cv_upload(session, user.id, sample_docx, "b.docx")
    await session.commit()

    profile = await ProfileRepository(session).get_full(user.id)
    assert profile is not None
    assert [e.company for e in profile.experiences] == ["Spedition Muster GmbH"]
    names = {s.name for s in profile.skills}
    assert "Final Cut Pro" in names and "CapCut" not in names
    assert await session.scalar(select(func.count()).select_from(CandidateProfile)) == 1
    primary = await session.scalars(select(Resume).where(Resume.user_id == user.id, Resume.is_primary))
    assert [r.title for r in primary] == ["b.docx"]


async def test_llm_failure_falls_back_to_document_extraction(session, sample_pdf):  # type: ignore[no-untyped-def]
    class Broken(MockLLMProvider):
        async def _complete_json(self, **kwargs):  # type: ignore[no-untyped-def,override]
            raise LLMError("down")

    set_llm(Broken())
    user, _ = await get_or_create_user(session, 3, None, None, "en")
    result = await process_cv_upload(session, user.id, sample_pdf, "cv.pdf")
    assert not result.used_ai
    assert result.profile.email == "anna.berger@example.com"


async def test_invalid_file_records_nothing_personal(session):  # type: ignore[no-untyped-def]
    user, _ = await get_or_create_user(session, 4, None, None, "en")
    with pytest.raises(CVFileError):
        await process_cv_upload(session, user.id, b"not a cv", "cv.txt")
    assert await session.scalar(select(func.count()).select_from(Resume)) == 0
