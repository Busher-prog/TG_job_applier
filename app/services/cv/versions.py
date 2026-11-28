"""Generated CVs: rendering, storage, version history, regeneration, restore."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Resume, ResumeVersion
from app.database.models.enums import ResumeKind, ResumeStatus
from app.database.repositories.audit import audit
from app.database.repositories.profiles import ProfileRepository
from app.database.repositories.resumes import ResumeRepository
from app.providers.storage import get_storage, user_prefix
from app.schemas.resume import ResumeDocument, StructurePlan
from app.services.cv.facts import profile_to_facts
from app.services.cv.generator import generate_resume
from app.services.cv.renderer import RenderResult, render_docx, render_pdf

logger = logging.getLogger(__name__)

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class RenderingError(RuntimeError):
    pass


@dataclass(slots=True)
class VersionResult:
    resume: Resume
    version: ResumeVersion
    render: RenderResult


def _render_both(doc: ResumeDocument) -> tuple[RenderResult, bytes]:
    result = render_pdf(doc)
    return result, render_docx(doc.model_copy(update={"density": result.density}))


async def _store_version(
    session: AsyncSession, resume: Resume, doc: ResumeDocument, note: str | None, created_by: str
) -> VersionResult:
    result, docx_bytes = await asyncio.to_thread(_render_both, doc)
    if result.missing:
        # Never hand out a document that lost information during rendering.
        logger.error("rendering lost %d essential facts (resume_id=%s)", len(result.missing), resume.id)
        raise RenderingError("render_verification_failed")
    doc = doc.model_copy(update={"density": result.density})
    number = (await session.scalar(
        select(func.coalesce(func.max(ResumeVersion.version_number), 0)).where(ResumeVersion.resume_id == resume.id)
    )) + 1
    storage = get_storage()
    base = f"{user_prefix(resume.user_id)}resumes/{resume.id}/v{number}-{uuid.uuid4().hex[:8]}"
    await storage.put(f"{base}.pdf", result.pdf, PDF_MIME)
    await storage.put(f"{base}.docx", docx_bytes, DOCX_MIME)
    version = ResumeVersion(
        resume_id=resume.id, version_number=number, content=doc.model_dump(mode="json"),
        template_code=doc.template, document_language=doc.document_language,
        pdf_file_key=f"{base}.pdf", docx_file_key=f"{base}.docx", page_count=result.page_count,
        change_note=(note or "")[:500] or None, created_by=created_by,
    )
    session.add(version)
    await session.flush()
    resume.current_version_id = version.id
    resume.template_code = doc.template
    resume.document_language = doc.document_language
    resume.status = ResumeStatus.READY.value
    await session.flush()
    return VersionResult(resume=resume, version=version, render=result)


async def create_generated_resume(
    session: AsyncSession,
    user_id: int,
    doc: ResumeDocument,
    *,
    kind: str = ResumeKind.GENERATED.value,
    plan: StructurePlan | None = None,
    meta: dict[str, Any] | None = None,
    parent_resume_id: int | None = None,
    job_listing_id: int | None = None,
) -> VersionResult:
    title = f"CV {doc.candidate.full_name} ({doc.template}, {doc.document_language})"
    resume = Resume(
        user_id=user_id, title=title[:200], kind=kind, status=ResumeStatus.PROCESSING.value,
        document_language=doc.document_language, template_code=doc.template,
        parent_resume_id=parent_resume_id, job_listing_id=job_listing_id,
        analysis={**(meta or {}), "plan": plan.model_dump() if plan else None},
    )
    session.add(resume)
    await session.flush()
    result = await _store_version(session, resume, doc, "initial", "ai")
    await audit(session, "cv.generated", user_id=user_id, entity_type="resume", entity_id=resume.id, kind=kind,
                template=doc.template, pages=result.render.page_count)
    return result


async def current_version(session: AsyncSession, resume: Resume) -> ResumeVersion | None:
    if resume.current_version_id:
        return await session.get(ResumeVersion, resume.current_version_id)
    return None


async def add_version(
    session: AsyncSession, resume: Resume, doc: ResumeDocument, note: str, created_by: str = "user"
) -> VersionResult:
    result = await _store_version(session, resume, doc, note, created_by)
    await audit(session, "cv.version_added", user_id=resume.user_id, entity_type="resume", entity_id=resume.id,
                version=result.version.version_number)
    return result


async def regenerate(
    session: AsyncSession,
    resume: Resume,
    base: ResumeDocument,
    *,
    instructions: list[str] | None = None,
    language: str | None = None,
    note: str,
) -> VersionResult:
    """Re-run content generation from the profile facts, keeping structure/template edits."""
    profile = await ProfileRepository(session).get_full(resume.user_id)
    if profile is None:
        raise RenderingError("no_profile")
    facts = profile_to_facts(profile)
    analysis = dict(resume.analysis or {})
    all_instructions = [*analysis.get("instructions", []), *(instructions or [])][-10:]
    plan = StructurePlan.model_validate(analysis["plan"]) if analysis.get("plan") else None
    if plan is not None:
        plan.section_order = [s for s in base.section_order]  # type: ignore[assignment]
    doc, plan = await generate_resume(
        facts,
        target_roles=base.target_roles,
        language=language or base.document_language,
        template=base.template,
        instructions=all_instructions,
        page_limit=base.page_limit,
        plan=plan,
        extra=analysis.get("extra_facts"),
    )
    # Keep user-made contact/portfolio edits that live only on the document.
    doc.candidate = base.candidate
    if base.portfolio:
        doc.portfolio = base.portfolio
    doc.section_order = [s for s in base.section_order if s in doc.section_order or doc.has_content(s)]  # type: ignore[assignment]
    analysis["instructions"] = all_instructions
    analysis["plan"] = plan.model_dump()
    resume.analysis = analysis
    return await add_version(session, resume, doc, note, created_by="ai")


async def restore_version(session: AsyncSession, resume: Resume, version_id: int) -> VersionResult:
    version = await ResumeRepository(session).get_version_for_user(resume.user_id, version_id)
    if version is None or version.resume_id != resume.id:
        raise RenderingError("version_not_found")
    doc = ResumeDocument.model_validate(version.content)
    return await add_version(session, resume, doc, f"restored v{version.version_number}", created_by="user")


async def list_versions(session: AsyncSession, resume_id: int) -> list[ResumeVersion]:
    rows = await session.scalars(
        select(ResumeVersion).where(ResumeVersion.resume_id == resume_id).order_by(ResumeVersion.version_number.desc())
    )
    return list(rows)
