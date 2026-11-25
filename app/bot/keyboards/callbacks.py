"""Typed callback data (kept short: Telegram limits callback_data to 64 bytes)."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class NavCb(CallbackData, prefix="nav"):
    to: str  # welcome | how | lang | consent | resume_options | menu | continue


class LangCb(CallbackData, prefix="lng"):
    scope: str  # ui | cv | letter
    code: str


class ConsentCb(CallbackData, prefix="cns"):
    action: str  # agree | read | decline


class ResumeOptCb(CallbackData, prefix="ro"):
    option: str  # upload | create | improve | examples


class ProfileCb(CallbackData, prefix="pf"):
    action: str  # ok | edit | other | field | back
    field: str = ""


class MenuCb(CallbackData, prefix="m"):
    section: str


class CvCb(CallbackData, prefix="cv"):
    action: str  # open | download | primary | delete | delete_yes | list | upload
    resume_id: int = 0


class SettingsCb(CallbackData, prefix="st"):
    action: str  # main | ui | cv | letter | privacy | export | delete | delete_yes
