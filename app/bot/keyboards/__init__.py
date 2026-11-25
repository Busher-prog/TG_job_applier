"""Inline keyboard builders."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.callbacks import (
    ConsentCb,
    CvCb,
    LangCb,
    MenuCb,
    NavCb,
    ProfileCb,
    ResumeOptCb,
    SettingsCb,
)
from app.config import SUPPORTED_LANGUAGES, get_settings
from app.services.i18n import Translator

MENU_SECTIONS: tuple[str, ...] = (
    "find_jobs",
    "new_jobs",
    "my_cvs",
    "create_cv",
    "improve_cv",
    "saved_jobs",
    "applications",
    "profile",
    "search_settings",
    "subscription",
    "settings",
    "support",
)

PROFILE_EDIT_FIELDS: tuple[str, ...] = (
    "name", "email", "phone", "location", "linkedin", "portfolio", "languages", "software", "skills",
)


def _btn(text: str, cb: object) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=cb.pack())  # type: ignore[attr-defined]


def welcome_kb(_: Translator) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(_("welcome.btn_start"), NavCb(to="consent"))],
            [_btn(_("welcome.btn_how"), NavCb(to="how"))],
            [_btn(_("welcome.btn_language"), NavCb(to="lang"))],
        ]
    )


def how_kb(_: Translator) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(_("welcome.btn_start"), NavCb(to="consent"))],
            [_btn(_("common.back"), NavCb(to="welcome"))],
        ]
    )


def language_kb(_: Translator, scope: str = "ui", back_to: str = "welcome", include_other: bool = False,
                include_auto: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    order = ("en", "de", "uk", "ru")
    for code in order:
        builder.add(_btn(_(f"languages.{code}"), LangCb(scope=scope, code=code)))
    builder.adjust(2)
    if include_auto:
        builder.row(_btn(_("settings.letter_lang_auto"), LangCb(scope=scope, code="auto")))
    if include_other:
        builder.row(_btn(_("languages.other"), LangCb(scope=scope, code="other")))
    builder.row(_btn(_("common.back"), NavCb(to=back_to) if back_to != "settings" else SettingsCb(action="main")))
    return builder.as_markup()


def consent_kb(_: Translator) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(_("consent.btn_agree"), ConsentCb(action="agree"))],
            [_btn(_("consent.btn_read"), ConsentCb(action="read"))],
            [_btn(_("consent.btn_decline"), ConsentCb(action="decline"))],
        ]
    )


def consent_declined_kb(_: Translator) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn(_("consent.btn_review_again"), NavCb(to="consent"))]]
    )


def resume_options_kb(_: Translator) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(_("resume.btn_upload"), ResumeOptCb(option="upload"))],
            [_btn(_("resume.btn_create"), ResumeOptCb(option="create"))],
            [_btn(_("resume.btn_improve"), ResumeOptCb(option="improve"))],
            [_btn(_("resume.btn_examples"), ResumeOptCb(option="examples"))],
            [_btn(_("common.main_menu"), NavCb(to="menu"))],
        ]
    )


def back_kb(_: Translator, to: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn(_("common.back"), NavCb(to=to))]])


def profile_confirm_kb(_: Translator) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(_("profile.btn_ok"), ProfileCb(action="ok"))],
            [_btn(_("profile.btn_edit"), ProfileCb(action="edit"))],
            [_btn(_("profile.btn_other_cv"), ProfileCb(action="other"))],
        ]
    )


def profile_edit_kb(_: Translator, back_action: str = "back") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    labels = {
        "name": "profile.field_name", "email": "profile.field_email", "phone": "profile.field_phone",
        "location": "profile.field_location", "linkedin": "profile.field_linkedin",
        "portfolio": "profile.field_portfolio", "languages": "profile.field_languages",
        "software": "profile.field_software", "skills": "profile.field_skills",
    }
    for field in PROFILE_EDIT_FIELDS:
        builder.add(_btn(_(labels[field]), ProfileCb(action="field", field=field)))
    builder.adjust(2)
    builder.row(_btn(_("common.back"), ProfileCb(action=back_action)))
    return builder.as_markup()


def cancel_edit_kb(_: Translator) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn(_("common.cancel"), ProfileCb(action="edit"))]])


def main_menu_kb(_: Translator, onboarding_pending: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if onboarding_pending:
        builder.row(_btn(_("welcome.btn_resume_onboarding"), NavCb(to="continue")))
    buttons = [_btn(_(f"menu.{s}"), MenuCb(section=s)) for s in MENU_SECTIONS]
    for i in range(0, len(buttons), 2):
        builder.row(*buttons[i : i + 2])
    return builder.as_markup()


def to_menu_kb(_: Translator) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn(_("common.main_menu"), NavCb(to="menu"))]])


def cv_list_kb(_: Translator, items: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for resume_id, label in items:
        builder.row(_btn(label[:60], CvCb(action="open", resume_id=resume_id)))
    builder.row(_btn(_("cv.btn_upload_new"), CvCb(action="upload")))
    builder.row(_btn(_("common.main_menu"), NavCb(to="menu")))
    return builder.as_markup()


def cv_detail_kb(_: Translator, resume_id: int, has_file: bool, is_primary: bool) -> InlineKeyboardMarkup:
    rows = []
    if has_file:
        rows.append([_btn(_("cv.btn_download"), CvCb(action="download", resume_id=resume_id))])
    if not is_primary:
        rows.append([_btn(_("cv.btn_make_primary"), CvCb(action="primary", resume_id=resume_id))])
    rows.append([_btn(_("cv.btn_delete"), CvCb(action="delete", resume_id=resume_id))])
    rows.append([_btn(_("common.back"), CvCb(action="list"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_kb(_: Translator, yes_text: str, yes_cb: object, no_cb: object) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn(yes_text, yes_cb), _btn(_("common.cancel"), no_cb)]]
    )


def settings_kb(_: Translator) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(_("settings.btn_ui_lang"), SettingsCb(action="ui"))],
            [_btn(_("settings.btn_cv_lang"), SettingsCb(action="cv"))],
            [_btn(_("settings.btn_letter_lang"), SettingsCb(action="letter"))],
            [_btn(_("settings.btn_privacy"), SettingsCb(action="privacy"))],
            [_btn(_("common.main_menu"), NavCb(to="menu"))],
        ]
    )


def privacy_kb(_: Translator, lang: str) -> InlineKeyboardMarkup:
    base = get_settings().app_base_url.rstrip("/")
    rows = [
        [_btn(_("settings.btn_export"), SettingsCb(action="export"))],
        [_btn(_("settings.btn_delete_account"), SettingsCb(action="delete"))],
    ]
    if base.startswith("https://"):
        rows.append([InlineKeyboardButton(text=_("settings.btn_policy"), url=f"{base}/privacy?lang={lang}")])
    rows.append([_btn(_("common.back"), SettingsCb(action="main"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


__all__ = [n for n in dir() if n.endswith("_kb")] + ["MENU_SECTIONS", "PROFILE_EDIT_FIELDS", "SUPPORTED_LANGUAGES"]
