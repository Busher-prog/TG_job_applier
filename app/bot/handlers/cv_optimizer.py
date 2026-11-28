"""AI CV Optimizer (Scenario C): analysis report, auto-improve, clarifying questions."""

from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.enums import ChatAction
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.bot.keyboards.callbacks import NavCb, OptimizerCb
from app.bot.middlewares.consent import ConsentRequiredMiddleware
from app.bot.states import OptimizerStates
from app.bot.utils import esc, get_text_input, show
from app.database.models import Resume, User
from app.database.models.enums import OnboardingStep, ResumeKind
from app.database.repositories.profiles import ProfileRepository
from app.database.repositories.resumes import ResumeRepository
from app.providers.llm import LLMError
from app.services.cv.facts import profile_to_facts
from app.services.cv.generator import generate_resume
from app.services.cv.interview import extract_answer, merge_extraction
from app.services.cv.optimizer import OptimizerReport, analyze_cv
from app.services.cv.profile_service import apply_parsed_cv
from app.services.cv.versions import RenderingError, create_generated_resume
from app.services.i18n import Translator

logger = logging.getLogger(__name__)

router = Router(name="cv_optimizer")
router.message.middleware(ConsentRequiredMiddleware())
router.callback_query.middleware(ConsentRequiredMiddleware())


def _kb(_: Translator, rid: int, include_recs: bool = True) -> InlineKeyboardMarkup:
    def b(key: str, action: str) -> list[InlineKeyboardButton]:
        return [InlineKeyboardButton(text=_(key), callback_data=OptimizerCb(action=action, resume_id=rid).pack())]

    rows = [b("optimizer.btn_auto", "auto"), b("optimizer.btn_questions", "questions")]
    if include_recs:
        rows.append(b("optimizer.btn_recommendations", "recs"))
    rows.append(b("optimizer.btn_keep", "keep"))
    rows.append([InlineKeyboardButton(text=_("common.main_menu"), callback_data=NavCb(to="menu").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _bullets(items: list[str]) -> str:
    return "\n".join(f"• {esc(i)}" for i in items)


def format_report(_: Translator, report: OptimizerReport, detailed: bool = False) -> str:
    parts = [_("optimizer.title"), _("optimizer.score", score=report.ats_score), _("optimizer.disclaimer")]
    strengths = [_(f"optimizer.s.{c}") for c in report.strengths] + report.review.strengths
    issues = [_(f"optimizer.i.{c}") for c in report.issues] + report.review.issues
    if strengths:
        parts.append(_("optimizer.strengths") + "\n" + _bullets(strengths[:6]))
    if issues:
        parts.append(_("optimizer.issues") + "\n" + _bullets(issues[: 10 if detailed else 5]))
    if detailed:
        recs = report.review.recommendations
        parts.append(_("optimizer.recommendations") + "\n" + (_bullets(recs) if recs else _("optimizer.no_recommendations")))
        if report.review.missing_information:
            parts.append(_("optimizer.missing") + "\n" + _bullets(report.review.missing_information))
    elif report.review.missing_information:
        parts.append(_("optimizer.missing") + "\n" + _bullets(report.review.missing_information[:4]))
    return "\n\n".join(parts)[:4000]


def _questions(_: Translator, report: OptimizerReport) -> list[str]:
    questions = list(report.review.clarifying_questions[:4])
    if not questions:
        for code in report.issues:
            key = f"optimizer.fallback_q.{code}"
            text = _(key)
            if text != key:
                questions.append(text)
    return questions[:4]


async def start_optimizer(
    target: Message | CallbackQuery, user: User, _: Translator, session: AsyncSession,
    state: FSMContext, resume_id: int,
) -> None:
    message = target.message if isinstance(target, CallbackQuery) else target
    assert isinstance(message, Message)
    resume = await ResumeRepository(session).get_for_user(user.id, resume_id)
    profile = await ProfileRepository(session).get_full(user.id)
    if resume is None or profile is None or not resume.extracted_text:
        await message.answer(_("common.not_found"))
        return
    status = await message.answer(_("optimizer.analyzing"))
    facts = profile_to_facts(profile)
    report = await analyze_cv(
        facts, resume.extracted_text, ui_language=user.interface_language,
        target_roles=list(profile.target_roles or []), extraction_method=resume.extraction_method or "text",
    )
    analysis = dict(resume.analysis or {})
    analysis["optimizer"] = report.to_dict()
    resume.analysis = analysis
    flag_modified(resume, "analysis")
    try:
        await status.delete()
    except Exception:  # pragma: no cover
        pass
    await message.answer(format_report(_, report), reply_markup=_kb(_, resume.id))


def _report(resume: Resume) -> OptimizerReport | None:
    raw = (resume.analysis or {}).get("optimizer")
    return OptimizerReport.from_dict(raw) if raw else None


async def improve_automatically(
    message: Message, user: User, _: Translator, session: AsyncSession, state: FSMContext, resume: Resume
) -> None:
    from app.bot.handlers.cv_preview import send_preview

    report = _report(resume)
    profile = await ProfileRepository(session).get_full(user.id)
    assert profile is not None
    facts = profile_to_facts(profile)
    extra = (resume.analysis or {}).get("extra_facts")
    instructions = [*(report.review.recommendations[:5] if report else []),
                    *(f"Fix: {code}" for code in (report.issues if report else []))]
    language = user.cv_language or resume.document_language or user.interface_language
    status = await message.answer(_("builder.generating"))
    await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_DOCUMENT)  # type: ignore[union-attr]
    try:
        doc, plan = await generate_resume(
            facts, target_roles=list(profile.target_roles or []), language=language,
            instructions=instructions, extra=extra,
        )
        result = await create_generated_resume(
            session, user.id, doc, kind=ResumeKind.OPTIMIZED.value, plan=plan,
            meta={"extra_facts": extra, "source": "optimizer", "instructions": instructions},
            parent_resume_id=resume.id,
        )
    except (ValidationError, LLMError, RenderingError) as exc:
        logger.warning("optimizer generation failed: %s", type(exc).__name__)
        await status.edit_text(_("builder.generation_failed"))
        return
    try:
        await status.delete()
    except Exception:  # pragma: no cover
        pass
    await send_preview(message, _, state, result.resume, result.version, result.render, first=True)


async def _ask_next_question(message: Message, _: Translator, state: FSMContext) -> bool:
    data = await state.get_data()
    questions: list[str] = data.get("opt_questions", [])
    idx: int = data.get("opt_index", 0)
    if idx >= len(questions):
        return False
    rid = data.get("opt_resume_id", 0)
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=_("common.skip"), callback_data=OptimizerCb(action="qskip", resume_id=rid).pack())
    ]])
    await message.answer(
        f"<i>{_('builder.question_counter', n=idx + 1, total=len(questions))}</i>\n{esc(questions[idx])}",
        reply_markup=markup,
    )
    return True


@router.callback_query(OptimizerCb.filter())
async def optimizer_action(
    call: CallbackQuery, callback_data: OptimizerCb, user: User, _: Translator,
    session: AsyncSession, state: FSMContext,
) -> None:
    resume = await ResumeRepository(session).get_for_user(user.id, callback_data.resume_id)
    message = call.message if isinstance(call.message, Message) else None
    if resume is None or message is None:
        await call.answer(_("common.not_found"), show_alert=True)
        return
    await call.answer()
    report = _report(resume)
    action = callback_data.action
    if action == "auto":
        await improve_automatically(message, user, _, session, state, resume)
    elif action == "recs" and report:
        await show(call, format_report(_, report, detailed=True), _kb(_, resume.id, include_recs=False))
    elif action == "questions" and report:
        questions = _questions(_, report)
        if not questions:
            await improve_automatically(message, user, _, session, state, resume)
            return
        await state.set_state(OptimizerStates.answering)
        await state.update_data(opt_questions=questions, opt_index=0, opt_resume_id=resume.id)
        await _ask_next_question(message, _, state)
    elif action == "qskip":
        data = await state.get_data()
        await state.update_data(opt_index=data.get("opt_index", 0) + 1)
        if not await _ask_next_question(message, _, state):
            await state.set_state(None)
            await improve_automatically(message, user, _, session, state, resume)
    elif action == "keep":
        await state.set_state(None)
        await message.answer(_("optimizer.kept"))
        if not user.onboarding_completed:
            from app.bot.handlers.onboarding import show_profile_confirmation

            user.onboarding_step = OnboardingStep.PROFILE_CONFIRM.value
            await show_profile_confirmation(message, _, user, session, edit=False)
        else:
            from app.bot.handlers.start import show_main_menu

            await show_main_menu(message, _, user, edit=False)


@router.message(StateFilter(OptimizerStates.answering))
async def optimizer_answer(
    message: Message, bot: Bot, user: User, _: Translator, session: AsyncSession, state: FSMContext
) -> None:
    text = await get_text_input(message, bot, _, user.interface_language)
    if text is None:
        return
    data = await state.get_data()
    questions: list[str] = data.get("opt_questions", [])
    idx: int = data.get("opt_index", 0)
    resume = await ResumeRepository(session).get_for_user(user.id, data.get("opt_resume_id", 0))
    profile = await ProfileRepository(session).get_full(user.id)
    if resume is None or profile is None or idx >= len(questions):
        await state.set_state(None)
        return
    question = questions[idx]
    facts = profile_to_facts(profile)
    ext = await extract_answer("adaptive", question, text, facts, user.interface_language)
    merge_extraction(facts, ext, "adaptive")
    await apply_parsed_cv(session, user.id, facts, source=profile.source or "upload")
    analysis = dict(resume.analysis or {})
    extra = dict(analysis.get("extra_facts") or {})
    extra.setdefault("answers", []).append({"q": question, "a": text[:1000]})
    analysis["extra_facts"] = extra
    resume.analysis = analysis
    flag_modified(resume, "analysis")
    await state.update_data(opt_index=idx + 1)
    if not await _ask_next_question(message, _, state):
        await state.set_state(None)
        await improve_automatically(message, user, _, session, state, resume)
