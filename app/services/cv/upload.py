"""End-to-end processing of an uploaded CV file (Scenario A)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.models import CandidateProfile, Resume
from app.database.models.enums import ResumeKind, ResumeStatus
from app.database.repositories.audit import audit
from app.database.repositories.resumes import ResumeRepository
from app.providers.llm import LLMError
from app.providers.storage import get_storage, user_prefix
from app.schemas.cv import ParsedCV
from app.services.cv.file_validation import CVFileError, validate_cv_file
from app.services.cv.heuristic_parser import heuristic_parse
from app.services.cv.parser import ground_parsed_cv, parse_cv_text
from app.services.cv.profile_service import apply_parsed_cv
from app.services.cv.text_extraction import extract_text

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class UploadResult:
    resume: Resume
    profile: CandidateProfile
    parsed: ParsedCV
    used_ai: bool


async def process_cv_upload(
    session: AsyncSession,
    user_id: int,
    data: bytes,
    filename: str | None,
    purpose: str = "profile",
) -> UploadResult:
    """Validate, store, extract, parse and save. Raises CVFileError for user errors."""
    settings = get_settings()
    validated = validate_cv_file(data, filename, settings.max_upload_bytes)

    key = f"{user_prefix(user_id)}resumes/{uuid.uuid4().hex}.{validated.kind}"
    await get_storage().put(key, data, validated.mime_type)

    resume = Resume(
        user_id=user_id,
        title=validated.safe_filename,
        kind=ResumeKind.UPLOADED.value,
        status=ResumeStatus.PROCESSING.value,
        original_file_key=key,
        original_filename=validated.safe_filename,
        mime_type=validated.mime_type,
        file_size=validated.size,
        file_sha256=validated.sha256,
    )
    session.add(resume)
    await session.flush()

    try:
        extraction = await asyncio.to_thread(extract_text, data, validated.kind, settings.ocr_languages)
    except CVFileError as exc:
        resume.status = ResumeStatus.FAILED.value
        resume.error_code = exc.code
        await audit(session, "cv.upload_failed", user_id=user_id, entity_type="resume",
                    entity_id=resume.id, code=exc.code)
        await session.commit()  # keep the failure record; nothing personal was extracted
        raise

    resume.extracted_text = extraction.text
    resume.extraction_method = extraction.method

    used_ai = True
    try:
        parsed = await parse_cv_text(extraction.text, extraction.links)
    except LLMError:
        # AI unavailable: fall back to deterministic extraction of facts present in the file.
        logger.warning("cv_parser LLM failed; using heuristic parser (resume_id=%s)", resume.id)
        parsed = ground_parsed_cv(
            ParsedCV.model_validate(heuristic_parse(extraction.text, extraction.links)),
            extraction.text,
            extraction.links,
        )
        used_ai = False

    resume.document_language = parsed.detected_language
    resume.analysis = {"warnings": parsed.warnings, "used_ai": used_ai, "purpose": purpose}
    resume.status = ResumeStatus.READY.value
    repo = ResumeRepository(session)
    profile = await apply_parsed_cv(session, user_id, parsed, source="upload")
    await session.flush()
    await repo.set_primary(user_id, resume.id)
    await audit(session, "cv.uploaded", user_id=user_id, entity_type="resume", entity_id=resume.id,
                kind=validated.kind, method=extraction.method, used_ai=used_ai)
    await session.refresh(resume)
    return UploadResult(resume=resume, profile=profile, parsed=parsed, used_ai=used_ai)
