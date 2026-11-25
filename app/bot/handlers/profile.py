"""/profile — view and edit the candidate profile."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards as kb
from app.bot.keyboards.callbacks import NavCb, ProfileCb, ResumeOptCb
from app.bot.middlewares.consent import ConsentRequiredMiddleware
from app.bot.utils import format_profile, show
from app.database.models import User
from app.database.repositories.profiles import ProfileRepository
from app.services.i18n import Translator

router = Router(name="profile")
router.message.middleware(ConsentRequiredMiddleware())
router.callback_query.middleware(ConsentRequiredMiddleware())


async def show_profile(target: Message | CallbackQuery, _: Translator, user: User, session: AsyncSession) -> None:
    profile = await ProfileRepository(session).get_full(user.id)
    if profile is None or not (profile.full_name or profile.experiences or profile.skills):
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=_("resume.btn_upload"), callback_data=ResumeOptCb(option="upload").pack())],
                [InlineKeyboardButton(text=_("resume.btn_create"), callback_data=ResumeOptCb(option="create").pack())],
                [InlineKeyboardButton(text=_("common.main_menu"), callback_data=NavCb(to="menu").pack())],
            ]
        )
        await show(target, _("profile.empty"), markup)
        return
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=_("profile.btn_edit"), callback_data=ProfileCb(action="edit").pack())],
            [InlineKeyboardButton(text=_("profile.btn_other_cv"), callback_data=ProfileCb(action="other").pack())],
            [InlineKeyboardButton(text=_("common.main_menu"), callback_data=NavCb(to="menu").pack())],
        ]
    )
    await show(target, f"{_('profile.title')}\n\n{format_profile(_, profile, detailed=True)}", markup)


@router.message(Command("profile"))
async def cmd_profile(message: Message, user: User, _: Translator, session: AsyncSession) -> None:
    await show_profile(message, _, user, session)


__all__ = ["router", "show_profile", "kb"]
