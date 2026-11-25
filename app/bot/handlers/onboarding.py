"""Step 2 (resume options), CV upload (Scenario A), profile confirmation & editing."""

from __future__ import annotations

import io
import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards as kb
from app.bot.keyboards.callbacks import NavCb, ProfileCb, ResumeOptCb
from app.bot.middlewares.consent import ConsentRequiredMiddleware
from app.bot.states import ProfileEditStates, UploadStates
from app.bot.utils import format_profile, get_text_input, progress, show
from app.config import get_settings
from app.database.models import User
from app.database.models.enums import OnboardingStep
from app.database.repositories.profiles import ProfileRepository
from app.services.cv.file_validation import CVFileError
from app.services.cv.upload import process_cv_upload
from app.services.i18n import Translator
from app.services.users.profile_edit import ProfileEditError, update_profile_field

logger = logging.getLogger(__name__)

router = Router(name="onboarding")
router.message.middleware(ConsentRequiredMiddleware())
router.callback_query.middleware(ConsentRequiredMiddleware())

FIELD_LABELS = {
    "name": "profile.field_name", "email": "profile.field_email", "phone": "profile.field_phone",
    "location": "profile.field_location", "linkedin": "profile.field_linkedin",
    "portfolio": "profile.field_portfolio", "languages": "profile.field_languages",
    "software": "profile.field_software", "skills": "profile.field_skills",
}


async def show_resume_options(target: Message | CallbackQuery, _: Translator, state: FSMContext) -> None:
    await state.set_state(None)
    await show(target, progress(_, "step_cv") + _("resume.options_text"), kb.resume_options_kb(_))


async def ask_for_upload(target: Message | CallbackQuery, _: Translator, state: FSMContext, purpose: str) -> None:
    await state.set_state(UploadStates.waiting_file)
    await state.update_data(upload_purpose=purpose)
    key = "upload.prompt_improve" if purpose == "improve" else "upload.prompt"
    back = "menu" if purpose == "new" else "resume_options"
    await show(target, _(key, max_mb=get_settings().max_upload_mb), kb.back_kb(_, back))


async def show_profile_confirmation(
    target: Message | CallbackQuery, _: Translator, user: User, session: AsyncSession, *, edit: bool = True
) -> None:
    profile = await ProfileRepository(session).get_full(user.id)
    if profile is None:
        await show(target, _("profile.empty"), kb.resume_options_kb(_), edit=edit)
        return
    header = progress(_, "step_profile") if not user.onboarding_completed else ""
    text = f"{header}{_('profile.analyzed_title')}\n\n{format_profile(_, profile)}\n\n{_('profile.question')}"
    await show(target, text, kb.profile_confirm_kb(_), edit=edit)


@router.callback_query(NavCb.filter(F.to == "resume_options"))
async def nav_resume_options(call: CallbackQuery, _: Translator, state: FSMContext) -> None:
    await call.answer()
    await show_resume_options(call, _, state)


@router.callback_query(ResumeOptCb.filter())
async def resume_option(
    call: CallbackQuery, callback_data: ResumeOptCb, user: User, _: Translator,
    session: AsyncSession, state: FSMContext,
) -> None:
    await call.answer()
    option = callback_data.option
    if option == "upload":
        await ask_for_upload(call, _, state, "profile")
    elif option == "improve":
        await ask_for_upload(call, _, state, "improve")
    elif option == "create":
        from app.bot.handlers.cv_builder import start_builder

        await start_builder(call, user, _, session, state)
    elif option == "examples":
        from app.bot.handlers.cv_examples import show_examples

        await show_examples(call, _, state)


@router.message(StateFilter(UploadStates.waiting_file), ~F.document)
async def upload_wrong_type(message: Message, _: Translator) -> None:
    await message.answer(_("upload.no_document"))


@router.message(F.document, StateFilter(UploadStates.waiting_file, None))
async def handle_cv_document(
    message: Message, bot: Bot, user: User, _: Translator, session: AsyncSession, state: FSMContext
) -> None:
    settings = get_settings()
    data = await state.get_data()
    purpose = data.get("upload_purpose", "profile")
    document = message.document
    assert document is not None
    if document.file_size and document.file_size > settings.max_upload_bytes:
        await message.answer(_("upload.errors.too_large", max_mb=settings.max_upload_mb))
        return

    status = await message.answer(_("upload.processing"))
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        buffer = io.BytesIO()
        await bot.download(document, destination=buffer)
        content = buffer.getvalue()
    except Exception as exc:
        logger.warning("cv download failed: %s", type(exc).__name__)
        await status.edit_text(_("upload.errors.download_failed"))
        return

    try:
        result = await process_cv_upload(session, user.id, content, document.file_name, purpose=purpose)
    except CVFileError as exc:
        await status.edit_text(
            _(f"upload.errors.{exc.code}", max_mb=settings.max_upload_mb),
            reply_markup=kb.back_kb(_, "resume_options") if not user.onboarding_completed else None,
        )
        return

    await state.set_state(None)
    try:
        await status.delete()
    except TelegramBadRequest:
        pass
    if not result.used_ai:
        await message.answer(_("upload.fallback_note"))

    if purpose == "improve":
        from app.bot.handlers.cv_optimizer import start_optimizer

        await start_optimizer(message, user, _, session, state, result.resume.id)
        return

    if not user.onboarding_completed:
        user.onboarding_step = OnboardingStep.PROFILE_CONFIRM.value
    await show_profile_confirmation(message, _, user, session)


@router.callback_query(ProfileCb.filter(F.action == "ok"))
async def profile_ok(
    call: CallbackQuery, user: User, _: Translator, session: AsyncSession, state: FSMContext
) -> None:
    profile = await ProfileRepository(session).get_full(user.id)
    if profile is None:
        await call.answer(_("profile.empty"), show_alert=True)
        return
    from app.services.cv.profile_service import confirm_profile

    await confirm_profile(profile)
    await call.answer(_("profile.confirmed"))
    if not user.onboarding_completed:
        user.onboarding_step = OnboardingStep.TARGET_JOBS.value
        from app.bot.handlers import search_onboarding

        await search_onboarding.resume_step(call, user, _, session, state)
    else:
        from app.bot.handlers.start import show_main_menu

        await show_main_menu(call, _, user)


@router.callback_query(ProfileCb.filter(F.action == "other"))
async def profile_other_cv(call: CallbackQuery, _: Translator, state: FSMContext) -> None:
    await call.answer()
    await ask_for_upload(call, _, state, "profile")


@router.callback_query(ProfileCb.filter(F.action == "edit"))
async def profile_edit_menu(call: CallbackQuery, _: Translator, state: FSMContext) -> None:
    await state.set_state(None)
    await call.answer()
    await show(call, _("profile.edit_choose"), kb.profile_edit_kb(_))


@router.callback_query(ProfileCb.filter(F.action == "back"))
async def profile_edit_back(call: CallbackQuery, user: User, _: Translator, session: AsyncSession) -> None:
    await call.answer()
    if user.onboarding_completed:
        from app.bot.handlers.profile import show_profile

        await show_profile(call, _, user, session)
    else:
        await show_profile_confirmation(call, _, user, session)


@router.callback_query(ProfileCb.filter(F.action == "field"))
async def profile_edit_field(call: CallbackQuery, callback_data: ProfileCb, _: Translator, state: FSMContext) -> None:
    field = callback_data.field
    if field not in FIELD_LABELS:
        await call.answer()
        return
    await state.set_state(ProfileEditStates.waiting_value)
    await state.update_data(edit_field=field)
    await call.answer()
    label = _(FIELD_LABELS[field])
    if field == "languages":
        text = _("profile.edit_prompt_languages")
    elif field in ("software", "skills"):
        text = _("profile.edit_prompt_list", field=label)
    else:
        text = _("profile.edit_prompt", field=label)
    await show(call, text, kb.cancel_edit_kb(_))


@router.message(StateFilter(ProfileEditStates.waiting_value))
async def profile_edit_value(
    message: Message, bot: Bot, user: User, _: Translator, session: AsyncSession, state: FSMContext
) -> None:
    text = await get_text_input(message, bot, _)
    if text is None:
        return
    field = (await state.get_data()).get("edit_field", "")
    try:
        await update_profile_field(session, user.id, field, text)
    except ProfileEditError as exc:
        await message.answer(_(f"profile.{exc.code}"), reply_markup=kb.cancel_edit_kb(_))
        return
    await state.set_state(None)
    await message.answer(_("profile.edit_saved"))
    if user.onboarding_completed:
        from app.bot.handlers.profile import show_profile

        await show_profile(message, _, user, session)
    else:
        await show_profile_confirmation(message, _, user, session)
