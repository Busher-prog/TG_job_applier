"""/cv — list, download, set primary, delete CVs."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards as kb
from app.bot.keyboards.callbacks import CvCb
from app.bot.middlewares.consent import ConsentRequiredMiddleware
from app.bot.utils import esc, show
from app.database.models import Resume, User
from app.database.models.enums import ResumeStatus
from app.database.repositories.audit import audit
from app.database.repositories.resumes import ResumeRepository
from app.providers.storage import StorageError, get_storage
from app.services.i18n import Translator

router = Router(name="resumes")
router.message.middleware(ConsentRequiredMiddleware())
router.callback_query.middleware(ConsentRequiredMiddleware())


def _label(_: Translator, r: Resume) -> str:
    parts = [r.title, _(f"cv.kind_{r.kind}")]
    if r.is_primary:
        parts.append(_("cv.item_primary"))
    if r.status == ResumeStatus.FAILED.value:
        parts.append(_("cv.status_failed"))
    return " · ".join(parts)


async def show_cv_list(target: Message | CallbackQuery, _: Translator, user: User, session: AsyncSession) -> None:
    resumes = await ResumeRepository(session).list_for_user(user.id)
    if not resumes:
        await show(target, f"{_('cv.list_title')}\n\n{_('cv.empty')}", kb.cv_list_kb(_, []))
        return
    await show(target, _("cv.list_title"), kb.cv_list_kb(_, [(r.id, _label(_, r)) for r in resumes[:20]]))


@router.message(Command("cv"))
async def cmd_cv(message: Message, user: User, _: Translator, session: AsyncSession) -> None:
    await show_cv_list(message, _, user, session)


@router.callback_query(CvCb.filter(F.action == "list"))
async def cv_list(call: CallbackQuery, user: User, _: Translator, session: AsyncSession) -> None:
    await call.answer()
    await show_cv_list(call, _, user, session)


@router.callback_query(CvCb.filter(F.action == "upload"))
async def cv_upload(call: CallbackQuery, _: Translator, state: FSMContext) -> None:
    from app.bot.handlers.onboarding import ask_for_upload

    await call.answer()
    await ask_for_upload(call, _, state, "profile")


@router.callback_query(CvCb.filter(F.action == "open"))
async def cv_open(call: CallbackQuery, callback_data: CvCb, user: User, _: Translator, session: AsyncSession) -> None:
    resume = await ResumeRepository(session).get_for_user(user.id, callback_data.resume_id)
    if resume is None:
        await call.answer(_("common.not_found"), show_alert=True)
        return
    await call.answer()
    has_file = bool(resume.original_file_key) or bool(resume.versions and resume.versions[-1].pdf_file_key)
    await show(
        call,
        f"📄 <b>{esc(resume.title)}</b>\n{esc(_label(_, resume))}\n{resume.created_at:%d.%m.%Y}",
        kb.cv_detail_kb(_, resume.id, has_file, resume.is_primary, editable=resume.current_version_id is not None),
    )


@router.callback_query(CvCb.filter(F.action == "download"))
async def cv_download(call: CallbackQuery, callback_data: CvCb, user: User, _: Translator, session: AsyncSession) -> None:
    resume = await ResumeRepository(session).get_for_user(user.id, callback_data.resume_id)
    if resume is None:
        await call.answer(_("common.not_found"), show_alert=True)
        return
    version = resume.versions[-1] if resume.versions else None
    key = (version.pdf_file_key if version and version.pdf_file_key else None) or resume.original_file_key
    if not key:
        await call.answer(_("common.not_found"), show_alert=True)
        return
    try:
        data = await get_storage().get(key)
    except StorageError:
        await call.answer(_("common.not_found"), show_alert=True)
        return
    await call.answer()
    filename = resume.original_filename if key == resume.original_file_key else f"{resume.title}.pdf"
    if isinstance(call.message, Message):
        await call.message.answer_document(BufferedInputFile(data, filename=filename or "cv.pdf"))


@router.callback_query(CvCb.filter(F.action == "primary"))
async def cv_primary(call: CallbackQuery, callback_data: CvCb, user: User, _: Translator, session: AsyncSession) -> None:
    repo = ResumeRepository(session)
    resume = await repo.get_for_user(user.id, callback_data.resume_id)
    if resume is None:
        await call.answer(_("common.not_found"), show_alert=True)
        return
    await repo.set_primary(user.id, resume.id)
    await call.answer(_("cv.primary_set"))
    await show_cv_list(call, _, user, session)


@router.callback_query(CvCb.filter(F.action == "delete"))
async def cv_delete(call: CallbackQuery, callback_data: CvCb, _: Translator) -> None:
    await call.answer()
    await show(
        call,
        _("cv.delete_confirm"),
        kb.confirm_kb(
            _, _("cv.btn_delete"),
            CvCb(action="delete_yes", resume_id=callback_data.resume_id),
            CvCb(action="open", resume_id=callback_data.resume_id),
        ),
    )


@router.callback_query(CvCb.filter(F.action == "delete_yes"))
async def cv_delete_yes(call: CallbackQuery, callback_data: CvCb, user: User, _: Translator, session: AsyncSession) -> None:
    resume = await ResumeRepository(session).get_for_user(user.id, callback_data.resume_id)
    if resume is None:
        await call.answer(_("common.not_found"), show_alert=True)
        return
    storage = get_storage()
    keys = [resume.original_file_key] + [k for v in resume.versions for k in (v.pdf_file_key, v.docx_file_key)]
    for key in filter(None, keys):
        await storage.delete(key)
    resume.current_version_id = None
    await session.flush()
    await session.delete(resume)
    await audit(session, "cv.deleted", user_id=user.id, entity_type="resume", entity_id=callback_data.resume_id)
    await session.flush()
    await call.answer(_("cv.deleted"))
    await show_cv_list(call, _, user, session)


@router.callback_query(CvCb.filter(F.action == "preview"))
async def cv_preview(
    call: CallbackQuery, callback_data: CvCb, user: User, _: Translator, session: AsyncSession, state: FSMContext
) -> None:
    from app.bot.handlers.cv_preview import open_preview

    await call.answer()
    if not isinstance(call.message, Message) or not await open_preview(
        call.message, _, user, session, state, callback_data.resume_id
    ):
        await call.answer(_("common.not_found"), show_alert=True)
