"""Scenario D: example CVs (fictional data) for each template."""

from __future__ import annotations

from pathlib import Path

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.callbacks import ExampleCb, NavCb, ResumeOptCb
from app.database.models import User
from app.services.i18n import Translator

router = Router(name="cv_examples")

EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "examples"
TEMPLATE_NAMES = {"classic_ats": "Classic ATS", "modern": "Modern Professional", "creative": "Creative"}


async def show_examples(target: Message | CallbackQuery, _: Translator, state: FSMContext) -> None:
    message = target.message if isinstance(target, CallbackQuery) else target
    assert isinstance(message, Message)
    await state.set_state(None)
    available = [c for c in TEMPLATE_NAMES if (EXAMPLES_DIR / f"{c}.pdf").exists()]
    if not available:
        await message.answer(_("examples.unavailable"))
        return
    await message.answer(_("examples.intro"))
    for code in available:
        png = EXAMPLES_DIR / f"{code}.png"
        if png.exists():
            await message.answer_photo(BufferedInputFile(png.read_bytes(), filename=f"{code}.png"),
                                       caption=_(f"examples.{code}"))
        else:
            await message.answer(_(f"examples.{code}"))
        await message.answer_document(
            BufferedInputFile((EXAMPLES_DIR / f"{code}.pdf").read_bytes(), filename=f"Example_CV_{code}.pdf")
        )
    rows = [[InlineKeyboardButton(text=_("examples.btn_similar", name=TEMPLATE_NAMES[c]),
                                  callback_data=ExampleCb(template=c).pack())] for c in available]
    rows.append([InlineKeyboardButton(text=_("resume.btn_upload"), callback_data=ResumeOptCb(option="upload").pack())])
    rows.append([InlineKeyboardButton(text=_("common.back"), callback_data=NavCb(to="resume_options").pack())])
    await message.answer(_("examples.outro"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(ExampleCb.filter())
async def create_similar(
    call: CallbackQuery, callback_data: ExampleCb, user: User, _: Translator,
    session: AsyncSession, state: FSMContext,
) -> None:
    from app.bot.handlers.cv_builder import start_builder
    from app.services.users.service import has_valid_consent

    await call.answer()
    if not await has_valid_consent(session, user):
        from app.bot.handlers.start import send_consent_screen

        await send_consent_screen(call, _, user.interface_language)
        return
    template = callback_data.template if callback_data.template in TEMPLATE_NAMES else None
    await start_builder(call, user, _, session, state, preset_template=template)
