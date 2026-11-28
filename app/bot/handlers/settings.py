"""/settings — languages (interface / CV / letters), privacy, export, deletion."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards as kb
from app.bot.keyboards.callbacks import LangCb, SettingsCb
from app.bot.states import SettingsStates
from app.bot.utils import esc, show
from app.database.models import User
from app.database.repositories.audit import audit
from app.schemas.common import clean_str
from app.services.i18n import Translator
from app.services.users import service as users

router = Router(name="settings")


def _lang_name(_: Translator, code: str | None) -> str:
    if not code:
        return _("common.not_set")
    if code == "auto":
        return _("settings.letter_lang_auto")
    name = _(f"languages.{code}")
    return name if not name.startswith("languages.") else code


async def show_settings(target: Message | CallbackQuery, _: Translator, user: User) -> None:
    text = _(
        "settings.title",
        ui=_lang_name(_, user.interface_language),
        cv=esc(_lang_name(_, user.cv_language)),
        letter=esc(_lang_name(_, user.letter_language)),
    )
    await show(target, text, kb.settings_kb(_))


@router.message(Command("settings"))
async def cmd_settings(message: Message, user: User, _: Translator) -> None:
    await show_settings(message, _, user)


@router.callback_query(SettingsCb.filter())
async def settings_action(
    call: CallbackQuery, callback_data: SettingsCb, user: User, _: Translator,
    session: AsyncSession, state: FSMContext,
) -> None:
    action = callback_data.action
    if action == "main":
        await state.set_state(None)
        await call.answer()
        await show_settings(call, _, user)
    elif action == "ui":
        await call.answer()
        await show(call, _("lang.choose"), kb.language_kb(_, scope="ui", back_to="settings"))
    elif action == "cv":
        await call.answer()
        await show(call, _("settings.choose_cv_lang"),
                   kb.language_kb(_, scope="cv", back_to="settings", include_other=True))
    elif action == "letter":
        await call.answer()
        await show(call, _("settings.choose_letter_lang"),
                   kb.language_kb(_, scope="letter", back_to="settings", include_auto=True))
    elif action == "privacy":
        await call.answer()
        await show(call, _("settings.privacy_title"), kb.privacy_kb(_, user.interface_language))
    elif action == "export":
        await call.answer()
        data = await users.export_user_data(session, user)
        if isinstance(call.message, Message):
            await call.message.answer_document(
                BufferedInputFile(data, filename="ai-job-copilot-data.json"), caption=_("settings.export_caption")
            )
    elif action == "delete":
        await call.answer()
        await show(call, _("settings.delete_confirm"),
                   kb.confirm_kb(_, _("settings.btn_delete_yes"), SettingsCb(action="delete_yes"),
                                 SettingsCb(action="privacy")))
    elif action == "delete_yes":
        await call.answer()
        await users.delete_account(session, user)
        await state.clear()
        await show(call, _("settings.account_deleted"), None)


@router.callback_query(LangCb.filter(F.scope.in_({"cv", "letter"})))
async def set_doc_language(
    call: CallbackQuery, callback_data: LangCb, user: User, _: Translator,
    session: AsyncSession, state: FSMContext,
) -> None:
    if callback_data.code == "other":
        await state.set_state(SettingsStates.waiting_other_cv_language)
        await call.answer()
        await show(call, _("settings.choose_cv_lang"), kb.back_kb(_, "menu"))
        return
    if callback_data.scope == "cv":
        user.cv_language = callback_data.code
    else:
        user.letter_language = callback_data.code
    await audit(session, f"settings.{callback_data.scope}_language", user_id=user.id, value=callback_data.code)
    await call.answer(_("common.saved"))
    await show_settings(call, _, user)


@router.message(StateFilter(SettingsStates.waiting_other_cv_language), F.text)
async def set_other_cv_language(message: Message, user: User, _: Translator, state: FSMContext) -> None:
    value = clean_str(message.text, 32)
    if not value:
        await message.answer(_("profile.invalid_value"))
        return
    user.cv_language = value
    await state.set_state(None)
    await message.answer(_("common.saved"))
    await show_settings(message, _, user)
