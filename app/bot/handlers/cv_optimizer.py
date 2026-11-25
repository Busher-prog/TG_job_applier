"""AI CV Optimizer (implemented in Phase 2)."""

from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.onboarding import show_profile_confirmation
from app.database.models import User
from app.database.models.enums import OnboardingStep
from app.services.i18n import Translator

router = Router(name="cv_optimizer")


async def start_optimizer(
    target: Message | CallbackQuery, user: User, _: Translator, session: AsyncSession,
    state: FSMContext, resume_id: int,
) -> None:
    # Until the optimizer exists, an uploaded CV continues as a normal upload.
    if not user.onboarding_completed:
        user.onboarding_step = OnboardingStep.PROFILE_CONFIRM.value
    await show_profile_confirmation(target, _, user, session)
