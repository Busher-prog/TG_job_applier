"""Main menu sections and slash commands for features of later phases."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards as kb
from app.bot.keyboards.callbacks import MenuCb
from app.bot.utils import show
from app.config import get_settings
from app.database.models import User
from app.services.i18n import Translator
from app.services.users.service import has_valid_consent

router = Router(name="menu")

# section -> slash command
COMMANDS = {
    "find_jobs": "jobs",
    "new_jobs": "newjobs",
    "my_cvs": "cv",
    "create_cv": "createcv",
    "improve_cv": "optimizecv",
    "saved_jobs": "saved",
    "applications": "applications",
    "profile": "profile",
    "search_settings": "search",
    "subscription": "subscription",
    "settings": "settings",
    "support": "help",
}


async def open_section(
    target: Message | CallbackQuery, section: str, user: User, _: Translator,
    session: AsyncSession, state: FSMContext,
) -> None:
    await state.set_state(None)
    if section == "support":
        await show(target, _("help.text", support=get_settings().support_contact), kb.to_menu_kb(_))
        return
    if section == "settings":
        from app.bot.handlers.settings import show_settings

        await show_settings(target, _, user)
        return
    if not await has_valid_consent(session, user):
        from app.bot.handlers.start import send_consent_screen

        await send_consent_screen(target, _, user.interface_language)
        return
    if section == "my_cvs":
        from app.bot.handlers.resumes import show_cv_list

        await show_cv_list(target, _, user, session)
    elif section == "profile":
        from app.bot.handlers.profile import show_profile

        await show_profile(target, _, user, session)
    elif section == "create_cv":
        from app.bot.handlers.cv_builder import start_builder

        await start_builder(target, user, _, session, state)
    elif section == "improve_cv":
        from app.bot.handlers.onboarding import ask_for_upload

        await ask_for_upload(target, _, state, "improve")
    else:
        handler = SECTION_HANDLERS.get(section)
        if handler is None:
            await show(target, _("common.coming_soon"), kb.to_menu_kb(_))
        else:
            await handler(target, user, _, session, state)


# Filled in by later phases: section -> async handler(target, user, _, session, state)
SECTION_HANDLERS: dict = {}


@router.callback_query(MenuCb.filter())
async def menu_section(
    call: CallbackQuery, callback_data: MenuCb, user: User, _: Translator,
    session: AsyncSession, state: FSMContext,
) -> None:
    await call.answer()
    await open_section(call, callback_data.section, user, _, session, state)


@router.message(Command("jobs", "newjobs", "createcv", "optimizecv", "saved", "applications", "subscription"))
async def section_command(
    message: Message, user: User, _: Translator, session: AsyncSession, state: FSMContext
) -> None:
    command = (message.text or "").split()[0].lstrip("/").split("@")[0]
    section = next((s for s, c in COMMANDS.items() if c == command), None)
    if section:
        await open_section(message, section, user, _, session, state)
