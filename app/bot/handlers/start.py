"""/start, welcome screen, language choice, how-it-works, consent, main menu."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards as kb
from app.bot.keyboards.callbacks import ConsentCb, LangCb, NavCb
from app.bot.utils import show
from app.config import get_settings
from app.database.models import User
from app.database.models.enums import OnboardingStep
from app.services.i18n import Translator
from app.services.users import service as users

router = Router(name="start")


def _legal_urls(lang: str) -> tuple[str, str]:
    base = get_settings().app_base_url.rstrip("/")
    return f"{base}/privacy?lang={lang}", f"{base}/terms?lang={lang}"


async def send_consent_screen(target: Message | CallbackQuery, _: Translator, lang: str) -> None:
    privacy, terms = _legal_urls(lang)
    await show(target, _("consent.text", privacy_url=privacy, terms_url=terms), kb.consent_kb(_))


async def show_main_menu(target: Message | CallbackQuery, _: Translator, user: User, *, edit: bool = True) -> None:
    await show(target, _("menu.title"), kb.main_menu_kb(_, onboarding_pending=not user.onboarding_completed), edit=edit)


async def continue_onboarding(
    target: Message | CallbackQuery, user: User, _: Translator, session: AsyncSession, state: FSMContext
) -> None:
    """Resume onboarding at the saved step (progress is stored in users.onboarding_step)."""
    from app.bot.handlers.onboarding import show_profile_confirmation, show_resume_options

    step = user.onboarding_step
    if not await users.has_valid_consent(session, user):
        await send_consent_screen(target, _, user.interface_language)
    elif step in (OnboardingStep.WELCOME, OnboardingStep.CONSENT, OnboardingStep.RESUME):
        await show_resume_options(target, _, state)
    elif step == OnboardingStep.PROFILE_CONFIRM:
        await show_profile_confirmation(target, _, user, session)
    else:
        from app.bot.handlers import search_onboarding

        await search_onboarding.resume_step(target, user, _, session, state)


@router.message(CommandStart())
async def cmd_start(message: Message, user: User, _: Translator, session: AsyncSession, state: FSMContext) -> None:
    has_consent = await users.has_valid_consent(session, user)
    if user.onboarding_completed and has_consent:
        await show_main_menu(message, _, user)
        return
    if has_consent and user.onboarding_step not in (OnboardingStep.WELCOME, OnboardingStep.CONSENT):
        await message.answer(
            _("welcome.resume_onboarding"),
            reply_markup=kb.main_menu_kb(_, onboarding_pending=True),
        )
        return
    await message.answer(_("welcome.text"), reply_markup=kb.welcome_kb(_))


@router.message(Command("help"))
async def cmd_help(message: Message, _: Translator) -> None:
    await message.answer(_("help.text", support=get_settings().support_contact), reply_markup=kb.to_menu_kb(_))


@router.callback_query(NavCb.filter(F.to == "welcome"))
async def nav_welcome(call: CallbackQuery, _: Translator) -> None:
    await show(call, _("welcome.text"), kb.welcome_kb(_))
    await call.answer()


@router.callback_query(NavCb.filter(F.to == "how"))
async def nav_how(call: CallbackQuery, _: Translator) -> None:
    await show(call, _("how.text"), kb.how_kb(_))
    await call.answer()


@router.callback_query(NavCb.filter(F.to == "lang"))
async def nav_lang(call: CallbackQuery, _: Translator) -> None:
    await show(call, _("lang.choose"), kb.language_kb(_, scope="ui", back_to="welcome"))
    await call.answer()


@router.callback_query(LangCb.filter(F.scope == "ui"))
async def set_ui_language(
    call: CallbackQuery, callback_data: LangCb, user: User, session: AsyncSession
) -> None:
    await users.set_interface_language(session, user, callback_data.code)
    _ = Translator(user.interface_language)
    await call.answer(_("lang.changed"))
    if user.onboarding_completed:
        from app.bot.handlers.settings import show_settings

        await show_settings(call, _, user)
    else:
        await show(call, _("welcome.text"), kb.welcome_kb(_))


@router.callback_query(NavCb.filter(F.to == "consent"))
async def nav_consent(
    call: CallbackQuery, user: User, _: Translator, session: AsyncSession, state: FSMContext
) -> None:
    await call.answer()
    if await users.has_valid_consent(session, user):
        await continue_onboarding(call, user, _, session, state)
        return
    user.onboarding_step = OnboardingStep.CONSENT.value
    await send_consent_screen(call, _, user.interface_language)


@router.callback_query(ConsentCb.filter())
async def consent_action(
    call: CallbackQuery,
    callback_data: ConsentCb,
    user: User,
    _: Translator,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    if callback_data.action == "read":
        await call.answer()
        await show(call, _("consent.summary"), kb.consent_kb(_))
        return
    if callback_data.action == "decline":
        await users.decline_consent(session, user)
        await call.answer()
        await show(call, _("consent.declined"), kb.consent_declined_kb(_))
        return
    await users.grant_consent(session, user)
    await call.answer(_("consent.accepted"))
    await continue_onboarding(call, user, _, session, state)


@router.callback_query(NavCb.filter(F.to == "menu"))
async def nav_menu(call: CallbackQuery, user: User, _: Translator, state: FSMContext) -> None:
    # Leaving to the menu keeps onboarding progress (stored on the user) but
    # cancels any pending text input so stray messages aren't misinterpreted.
    await state.set_state(None)
    await call.answer()
    await show_main_menu(call, _, user)


@router.callback_query(NavCb.filter(F.to == "continue"))
async def nav_continue(
    call: CallbackQuery, user: User, _: Translator, session: AsyncSession, state: FSMContext
) -> None:
    await call.answer()
    await continue_onboarding(call, user, _, session, state)
