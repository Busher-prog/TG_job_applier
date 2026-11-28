"""CV preview: confirm, natural-language edits, structure/design/language, downloads, versions."""

from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.enums import ChatAction
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.callbacks import NavCb, PreviewCb
from app.bot.middlewares.consent import ConsentRequiredMiddleware
from app.bot.states import PreviewStates
from app.bot.utils import get_text_input, show
from app.database.models import Resume, ResumeVersion, User
from app.database.models.enums import OnboardingStep, ResumeStatus
from app.database.repositories.profiles import ProfileRepository
from app.database.repositories.resumes import ResumeRepository
from app.providers.llm import LLMError
from app.providers.storage import StorageError, get_storage
from app.schemas.resume import ResumeDocument
from app.services.cv.editing import EditIntent, EditOperation, apply_operations, interpret_edit
from app.services.cv.renderer import RenderResult
from app.services.cv.section_titles import titles_for
from app.services.cv.versions import (
    RenderingError,
    add_version,
    current_version,
    list_versions,
    regenerate,
    restore_version,
)
from app.services.i18n import Translator
from app.services.users.profile_edit import ProfileEditError, update_profile_field

logger = logging.getLogger(__name__)

router = Router(name="cv_preview")
router.message.middleware(ConsentRequiredMiddleware())
router.callback_query.middleware(ConsentRequiredMiddleware())

TEMPLATE_NAMES = {"classic_ats": "Classic ATS", "modern": "Modern Professional", "creative": "Creative"}


def _p(text: str, action: str, rid: int, value: str = "") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=PreviewCb(action=action, resume_id=rid, value=value).pack())


def preview_kb(_: Translator, rid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_p(_("preview.btn_confirm"), "confirm", rid)],
        [_p(_("preview.btn_edit_info"), "info", rid), _p(_("preview.btn_structure"), "structure", rid)],
        [_p(_("preview.btn_design"), "design", rid), _p(_("preview.btn_language"), "language", rid)],
        [_p(_("preview.btn_shorter"), "shorter", rid), _p(_("preview.btn_versions"), "versions", rid)],
        [_p(_("preview.btn_pdf"), "pdf", rid), _p(_("preview.btn_docx"), "docx", rid)],
        [InlineKeyboardButton(text=_("common.main_menu"), callback_data=NavCb(to="menu").pack())],
    ])


def _filename(doc: ResumeDocument, ext: str) -> str:
    base = "".join(ch for ch in doc.candidate.full_name if ch.isalnum() or ch in " -_").strip().replace(" ", "_")
    return f"CV_{base or 'resume'}_{doc.document_language}.{ext}"


async def send_preview(
    message: Message, _: Translator, state: FSMContext, resume: Resume, version: ResumeVersion,
    render: RenderResult | None = None, *, first: bool = False,
) -> None:
    doc = ResumeDocument.model_validate(version.content)
    data = await get_storage().get(version.pdf_file_key or "")
    caption = _("preview.ready") if first else _("preview.updated", n=version.version_number)
    await message.answer_document(
        BufferedInputFile(data, filename=_filename(doc, "pdf")),
        caption=caption[:1024],
        reply_markup=preview_kb(_, resume.id),
    )
    if render is not None and not render.within_page_limit:
        await message.answer(_("preview.page_limit_failed", pages=render.page_count))
    await state.set_state(PreviewStates.editing)
    await state.update_data(preview_resume_id=resume.id)


async def _resume_and_doc(
    session: AsyncSession, user: User, rid: int
) -> tuple[Resume, ResumeVersion, ResumeDocument] | None:
    resume = await ResumeRepository(session).get_for_user(user.id, rid)
    if resume is None:
        return None
    version = await current_version(session, resume)
    if version is None:
        return None
    return resume, version, ResumeDocument.model_validate(version.content)


async def _apply_and_send(
    message: Message, user: User, _: Translator, session: AsyncSession, state: FSMContext,
    resume: Resume, doc: ResumeDocument, intent: EditIntent, note: str,
) -> None:
    outcome = apply_operations(doc, intent)
    for field, value in outcome.profile_updates.items():
        mapped = {"full_name": "name"}.get(field, field)
        try:
            await update_profile_field(session, user.id, mapped, value)
        except ProfileEditError:
            pass
    if outcome.applied == 0:
        await message.answer(_("preview.invalid_value" if outcome.errors else "preview.nothing_changed"))
        return
    status = await message.answer(_("preview.updating"))
    await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_DOCUMENT)  # type: ignore[union-attr]
    try:
        if outcome.regenerate:
            result = await regenerate(session, resume, outcome.doc, instructions=outcome.instructions,
                                      language=outcome.new_language, note=note)
        else:
            result = await add_version(session, resume, outcome.doc, note)
    except (RenderingError, LLMError, ValidationError) as exc:
        logger.warning("cv update failed: %s", type(exc).__name__)
        await status.edit_text(_("preview.render_failed"))
        return
    try:
        await status.delete()
    except Exception:  # pragma: no cover
        pass
    if outcome.errors:
        await message.answer(_("preview.invalid_value"))
    await send_preview(message, _, state, result.resume, result.version, result.render)


@router.message(StateFilter(PreviewStates.editing))
async def natural_language_edit(
    message: Message, bot: Bot, user: User, _: Translator, session: AsyncSession, state: FSMContext
) -> None:
    rid = (await state.get_data()).get("preview_resume_id")
    loaded = await _resume_and_doc(session, user, int(rid or 0))
    if loaded is None:
        await state.set_state(None)
        await message.answer(_("common.not_found"))
        return
    text = await get_text_input(message, bot, _, user.interface_language)
    if text is None:
        return
    resume, _version, doc = loaded
    intent = await interpret_edit(text, doc, user.interface_language)
    if intent.clarification_question and not intent.operations:
        await message.answer(intent.clarification_question[:1000])
        return
    if intent.needs_new_facts and not intent.operations:
        await message.answer(_("preview.needs_new_facts"))
        return
    await _apply_and_send(message, user, _, session, state, resume, doc, intent, f"edit: {text[:200]}")
    if intent.needs_new_facts:
        await message.answer(_("preview.needs_new_facts"))


def _structure_kb(_: Translator, rid: int, order: list[str], lang: str) -> InlineKeyboardMarkup:
    titles = titles_for(lang)
    rows = []
    for i, key in enumerate(order):
        rows.append([
            InlineKeyboardButton(text=titles.get(key, key), callback_data=PreviewCb(action="noop", resume_id=rid).pack()),
            _p("⬆️", "mv", rid, f"{i}:up"),
            _p("⬇️", "mv", rid, f"{i}:down"),
        ])
    rows.append([_p(_("common.done"), "sdone", rid)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(PreviewCb.filter())
async def preview_action(
    call: CallbackQuery, callback_data: PreviewCb, user: User, _: Translator,
    session: AsyncSession, state: FSMContext,
) -> None:
    loaded = await _resume_and_doc(session, user, callback_data.resume_id)
    if loaded is None:
        await call.answer(_("common.not_found"), show_alert=True)
        return
    resume, version, doc = loaded
    message = call.message if isinstance(call.message, Message) else None
    action, rid, value = callback_data.action, resume.id, callback_data.value
    await state.update_data(preview_resume_id=rid)
    if message is None:
        await call.answer()
        return

    if action == "noop":
        await call.answer()
    elif action == "pdf" or action == "docx":
        key = version.pdf_file_key if action == "pdf" else version.docx_file_key
        try:
            data = await get_storage().get(key or "")
        except StorageError:
            await call.answer(_("common.not_found"), show_alert=True)
            return
        await call.answer()
        await message.answer_document(BufferedInputFile(data, filename=_filename(doc, action)))
    elif action == "confirm":
        version.confirmed = True
        resume.status = ResumeStatus.CONFIRMED.value
        await ResumeRepository(session).set_primary(user.id, resume.id)
        if not user.cv_language:
            user.cv_language = doc.document_language
        await state.set_state(None)
        await call.answer(_("preview.confirmed"))
        await message.answer(_("preview.confirmed"))
        if not user.onboarding_completed:
            from app.bot.handlers.onboarding import show_profile_confirmation

            user.onboarding_step = OnboardingStep.PROFILE_CONFIRM.value
            await show_profile_confirmation(message, _, user, session, edit=False)
        else:
            from app.bot.handlers.start import show_main_menu

            await show_main_menu(message, _, user, edit=False)
    elif action == "info":
        await call.answer()
        await state.set_state(PreviewStates.editing)
        await message.answer(_("preview.edit_hint"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=_("common.back"), callback_data=PreviewCb(action="noop", resume_id=rid).pack())]
        ]))
    elif action == "structure":
        await call.answer()
        order = doc.visible_sections()
        await state.update_data(pending_order=order)
        await message.answer(_("preview.structure_title"),
                             reply_markup=_structure_kb(_, rid, order, user.interface_language))
    elif action == "mv":
        order = list((await state.get_data()).get("pending_order") or doc.visible_sections())
        try:
            idx_s, direction = value.split(":")
            idx = int(idx_s)
        except ValueError:
            await call.answer()
            return
        new = idx - 1 if direction == "up" else idx + 1
        if 0 <= idx < len(order) and 0 <= new < len(order):
            order[idx], order[new] = order[new], order[idx]
            await state.update_data(pending_order=order)
            await show(call, _("preview.structure_title"), _structure_kb(_, rid, order, user.interface_language))
        await call.answer()
    elif action == "sdone":
        await call.answer()
        order = (await state.get_data()).get("pending_order")
        if not order or order == doc.visible_sections():
            await show(call, _("preview.nothing_changed"), None)
            return
        new_doc = doc.model_copy(update={"section_order": order})
        await show(call, _("preview.updating"), None)
        try:
            result = await add_version(session, resume, new_doc, "structure")
        except RenderingError:
            await message.answer(_("preview.render_failed"))
            return
        await send_preview(message, _, state, result.resume, result.version, result.render)
    elif action == "design":
        await call.answer()
        rows = [[_p(("• " if code == doc.template else "") + name, "tpl", rid, code)] for code, name in TEMPLATE_NAMES.items()]
        await message.answer(_("preview.design_title"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    elif action == "tpl":
        await call.answer()
        intent = EditIntent(operations=[EditOperation(op="change_template", value=value)])
        await _apply_and_send(message, user, _, session, state, resume, doc, intent, f"design: {value}")
    elif action == "language":
        await call.answer()
        rows = [[_p(_(f"languages.{c}"), "lang", rid, c) for c in ("en", "de")],
                [_p(_(f"languages.{c}"), "lang", rid, c) for c in ("uk", "ru")]]
        await message.answer(_("preview.language_title"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    elif action == "lang":
        await call.answer()
        intent = EditIntent(operations=[EditOperation(op="change_language", value=value)])
        await _apply_and_send(message, user, _, session, state, resume, doc, intent, f"language: {value}")
    elif action == "shorter":
        await call.answer()
        intent = EditIntent(operations=[EditOperation(op="set_page_limit", value="1"), EditOperation(op="shorten")])
        await _apply_and_send(message, user, _, session, state, resume, doc, intent, "shorter")
    elif action == "versions":
        await call.answer()
        versions = await list_versions(session, rid)
        rows = [[_p(f"{'• ' if v.id == resume.current_version_id else ''}v{v.version_number} · "
                    f"{(v.change_note or '')[:30]} · {v.created_at:%d.%m %H:%M}", "restore", rid, str(v.id))]
                for v in versions[:10]]
        await message.answer(_("preview.versions_title"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    elif action == "restore":
        if str(resume.current_version_id) == value:
            await call.answer()
            return
        try:
            result = await restore_version(session, resume, int(value))
        except (RenderingError, ValueError):
            await call.answer(_("common.not_found"), show_alert=True)
            return
        await call.answer(_("preview.restored"))
        await send_preview(message, _, state, result.resume, result.version, result.render)
    else:
        await call.answer()


async def open_preview(message: Message, _: Translator, user: User, session: AsyncSession, state: FSMContext,
                       resume_id: int) -> bool:
    loaded = await _resume_and_doc(session, user, resume_id)
    if loaded is None:
        return False
    resume, version, _doc = loaded
    await send_preview(message, _, state, resume, version)
    return True


__all__ = ["open_preview", "preview_kb", "router", "send_preview", "ProfileRepository"]
