"""AI CV Builder: adaptive interview -> facts -> generated CV (Part II of the spec)."""

from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.enums import ChatAction
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.callbacks import BuilderCb, NavCb
from app.bot.middlewares.consent import ConsentRequiredMiddleware
from app.bot.states import BuilderStates
from app.bot.utils import esc, get_text_input, show
from app.database.models import User
from app.database.repositories.profiles import ProfileRepository
from app.providers.llm import LLMError
from app.schemas.cv import ParsedCV
from app.services.cv.builder_state import OPTIONAL, SECTION_OF, BuilderDraft, load_draft, save_draft
from app.services.cv.facts import profile_to_facts
from app.services.cv.interview import (
    KNOWN_TOOLS,
    adaptive_questions,
    extract_answer,
    merge_extraction,
    missing_experience_fields,
    suggest_skills,
)
from app.services.cv.profile_service import apply_parsed_cv
from app.services.cv.structure import rule_based_plan
from app.services.i18n import Translator

logger = logging.getLogger(__name__)

router = Router(name="cv_builder")
router.message.middleware(ConsentRequiredMiddleware())
router.callback_query.middleware(ConsentRequiredMiddleware())

TEMPLATE_NAMES = {"classic_ats": "Classic ATS", "modern": "Modern Professional", "creative": "Creative"}
PERSONAL_FIELDS = {
    "name": "full_name", "email": "email", "phone": "phone", "location": "city",
    "linkedin": "linkedin_url", "portfolio": "portfolio_url",
}


def _b(text: str, action: str, value: str = "") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=BuilderCb(action=action, value=value).pack())


def _has_profile_data(profile) -> bool:  # type: ignore[no-untyped-def]
    return bool(profile.full_name or profile.experiences or profile.education or profile.skills)


def _exp_line(e) -> str:  # type: ignore[no-untyped-def]
    period = " – ".join(x for x in (e.start_date or "", "…" if e.is_current else (e.end_date or "")) if x)
    return "• " + esc(" · ".join(x for x in (e.job_title, e.company, period) if x))


def _edu_line(e) -> str:  # type: ignore[no-untyped-def]
    return "• " + esc(" · ".join(x for x in (e.degree, e.specialization, e.institution, e.end_date) if x))


def _mark_known_personal(draft: BuilderDraft) -> None:
    for stage, attr in PERSONAL_FIELDS.items():
        if getattr(draft.facts.candidate, attr):
            draft.mark_done(stage)


# --------------------------------------------------------------------------- entry points


async def start_builder(
    target: Message | CallbackQuery, user: User, _: Translator, session: AsyncSession, state: FSMContext,
    preset_template: str | None = None,
) -> None:
    profile = await ProfileRepository(session).get_or_create(user.id)
    draft = load_draft(profile)
    if draft and draft.done and preset_template is None:
        await show(target, _("builder.resume_or_restart"), InlineKeyboardMarkup(inline_keyboard=[
            [_b(_("builder.btn_resume"), "resume")],
            [_b(_("builder.btn_restart"), "restart")],
            [InlineKeyboardButton(text=_("common.main_menu"), callback_data=NavCb(to="menu").pack())],
        ]))
        return
    await _begin(target, user, _, session, state, preset_template)


async def _begin(
    target: Message | CallbackQuery, user: User, _: Translator, session: AsyncSession, state: FSMContext,
    preset_template: str | None = None,
) -> None:
    profile = await ProfileRepository(session).get_or_create(user.id)
    facts = profile_to_facts(profile) if _has_profile_data(profile) else ParsedCV()
    draft = BuilderDraft(facts=facts, preset_template=preset_template, template=preset_template,
                         target_roles=list(profile.target_roles or []))
    if draft.target_roles:
        draft.direction = "known"
        draft.mark_done("direction")
    draft.prefill_from_facts(user.cv_language)
    await save_draft(session, user.id, draft)
    await show(target, _("builder.intro"), None)
    message = target.message if isinstance(target, CallbackQuery) else target
    assert isinstance(message, Message)
    await advance(message, user, _, session, state, draft)


async def advance(
    target: Message | CallbackQuery, user: User, _: Translator, session: AsyncSession,
    state: FSMContext, draft: BuilderDraft,
) -> None:
    """Move to the next unanswered question (auto-saved after every step)."""
    while True:
        stage = draft.next_stage()
        if stage == "adaptive" and not draft.adaptive_generated:
            draft.adaptive = await adaptive_questions(draft.facts, draft.target_roles, user.interface_language)
            draft.adaptive_generated = True
            draft.adaptive_index = 0
            if not draft.adaptive:
                draft.mark_done("adaptive")
                continue
        if stage == "skills" and not draft.suggestions:
            answers = [a["a"] for a in draft.answers]
            draft.suggestions = await suggest_skills(draft.facts, draft.target_roles, answers)
        break
    draft.stage = stage
    await save_draft(session, user.id, draft)
    if stage == "generate":
        await state.set_state(None)
        await generate_cv(target, user, _, session, state, draft)
        return
    await state.set_state(BuilderStates.answering)
    await ask_stage(target, draft, _)


def _nav_row(_: Translator, draft: BuilderDraft) -> list[InlineKeyboardButton]:
    row = []
    if draft.history:
        row.append(_b(_("common.back"), "back"))
    if draft.stage in OPTIONAL and not (draft.stage == "phone" and not draft.facts.candidate.email):
        row.append(_b(_("common.skip"), "skip"))
    return row


async def ask_stage(target: Message | CallbackQuery, draft: BuilderDraft, _: Translator) -> None:
    stage = draft.stage
    header = _("builder.header", section=_(f"builder.section_{SECTION_OF.get(stage, 'final')}"))
    rows: list[list[InlineKeyboardButton]] = []
    if stage in ("name", "email", "phone", "location", "linkedin", "portfolio", "target_role", "languages",
                 "extras", "education"):
        text = _(f"builder.ask_{stage}")
    elif stage == "direction":
        text = _("builder.ask_direction")
        rows += [[_b(_("builder.btn_dir_known"), "dir", "known")],
                 [_b(_("builder.btn_dir_help"), "dir", "help")],
                 [_b(_("builder.btn_dir_exploring"), "dir", "exploring")]]
    elif stage == "experience":
        text = _("builder.ask_experience_more" if draft.facts.experience else "builder.ask_experience")
        if not draft.facts.experience:
            rows.append([_b(_("builder.btn_no_experience"), "noexp")])
    elif stage == "exp_followup":
        text = draft.followups[0]["question"]
        rows.append([_b(_("common.skip"), "skip")])
    elif stage == "exp_more":
        text = _("builder.exp_list", items="\n".join(_exp_line(e) for e in draft.facts.experience))
        rows += [[_b(_("builder.btn_add_job"), "addjob")], [_b(_("common.continue"), "next")]]
    elif stage == "adaptive":
        n = draft.adaptive_index + 1
        intro = _("builder.adaptive_intro") + "\n\n" if draft.adaptive_index == 0 else ""
        text = f"{intro}<i>{_('builder.question_counter', n=n, total=len(draft.adaptive))}</i>\n{esc(draft.adaptive[draft.adaptive_index])}"
    elif stage == "education_more":
        text = _("builder.edu_list", items="\n".join(_edu_line(e) for e in draft.facts.education))
        rows += [[_b(_("builder.btn_add_education"), "addedu")], [_b(_("common.continue"), "next")]]
    elif stage == "skills":
        text = _("builder.ask_skills" if draft.suggestions else "builder.ask_skills_none")
        pair: list[InlineKeyboardButton] = []
        for i, name in enumerate(draft.suggestions[:12]):
            mark = "✓ " if name in draft.selected else ""
            pair.append(_b(f"{mark}{name}"[:40], "skill", str(i)))
            if len(pair) == 2:
                rows.append(pair)
                pair = []
        if pair:
            rows.append(pair)
        if draft.selected:
            text += "\n\n" + _("builder.skills_added", items=esc(", ".join(draft.selected)))
        rows.append([_b(_("builder.btn_skills_done"), "skills_done")])
    elif stage == "cv_language":
        text = _("builder.ask_cv_language")
        rows += [[_b(_("languages.en"), "lang", "en"), _b(_("languages.de"), "lang", "de")],
                 [_b(_("languages.uk"), "lang", "uk"), _b(_("languages.ru"), "lang", "ru")],
                 [_b(_("languages.other"), "lang", "other")]]
    elif stage == "design":
        text = _("builder.ask_design")
        recommended = rule_based_plan(draft.facts, draft.target_roles, draft.direction).recommended_template
        for code, name in TEMPLATE_NAMES.items():
            rows.append([_b(("⭐ " if code == recommended else "") + name, "tpl", code)])
        rows.append([_b(_("builder.btn_choose_for_me"), "tpl", "auto")])
    else:  # pragma: no cover
        text = _("common.unknown_input")
    nav = _nav_row(_, draft)
    if nav and stage != "exp_followup":
        rows.append(nav)
    elif stage == "exp_followup" and draft.history:
        rows[-1].insert(0, _b(_("common.back"), "back"))
    rows.append([InlineKeyboardButton(text=_("common.main_menu"), callback_data=NavCb(to="menu").pack())])
    await show(target, header + text, InlineKeyboardMarkup(inline_keyboard=rows))


async def _load(session: AsyncSession, user: User) -> BuilderDraft | None:
    profile = await ProfileRepository(session).get_or_create(user.id)
    return load_draft(profile)


# --------------------------------------------------------------------------- text answers


async def _handle_experience_text(draft: BuilderDraft, text: str, user: User, _: Translator) -> bool:
    ext = await extract_answer("experience", _("builder.ask_experience"), text, draft.facts, user.interface_language)
    before = len(draft.facts.experience)
    idx = merge_extraction(draft.facts, ext, "experience")
    if len(draft.facts.experience) == before or idx is None:
        return False
    item = draft.facts.experience[idx]
    draft.exp_index = idx
    draft.followups = [{"field": f, "question": _(f"builder.followup_{f}")} for f in missing_experience_fields(item)][:3]
    draft.followups += [{"field": "free", "question": q} for q in ext.follow_up_questions[:1]]
    draft.mark_done("experience")
    for s in ("exp_followup", "exp_more"):
        if s in draft.done:
            draft.done.remove(s)
    if not draft.followups:
        draft.mark_done("exp_followup")
    return True


@router.message(StateFilter(BuilderStates.answering))
async def builder_answer(
    message: Message, bot: Bot, user: User, _: Translator, session: AsyncSession, state: FSMContext
) -> None:
    draft = await _load(session, user)
    if draft is None:
        await state.set_state(None)
        await message.answer(_("common.unknown_input"))
        return
    text = await get_text_input(message, bot, _, user.interface_language)
    if text is None:
        return
    stage = draft.stage
    lang = user.interface_language
    error: str | None = None

    if stage in PERSONAL_FIELDS:
        ext = await extract_answer(stage, _(f"builder.ask_{stage}"), text, draft.facts, lang)
        merge_extraction(draft.facts, ext, stage)
        if not getattr(draft.facts.candidate, PERSONAL_FIELDS[stage]):
            error = {"name": "builder.need_name", "email": "profile.invalid_email", "phone": "profile.invalid_phone",
                     "linkedin": "profile.invalid_url", "portfolio": "profile.invalid_url",
                     "location": "profile.invalid_value"}[stage]
        else:
            _mark_known_personal(draft)
    elif stage in ("direction", "target_role"):
        draft.direction = "known"
        draft.target_roles = [text.strip()[:120]]
        draft.mark_done("direction")
        draft.mark_done("target_role")
    elif stage in ("experience", "exp_more"):
        if not await _handle_experience_text(draft, text, user, _):
            error = "builder.nothing_found"
    elif stage == "exp_followup" and draft.followups:
        fu = draft.followups.pop(0)
        field = None if fu["field"] == "free" else fu["field"]
        ext = await extract_answer("exp_followup", fu["question"], text, draft.facts, lang, expected_field=field)
        merge_extraction(draft.facts, ext, "exp_followup", draft.exp_index)
        if field is None:
            draft.answers.append({"q": fu["question"], "a": text[:1000]})
        if not draft.followups:
            draft.mark_done("exp_followup")
    elif stage == "adaptive" and draft.adaptive_index < len(draft.adaptive):
        question = draft.adaptive[draft.adaptive_index]
        ext = await extract_answer("adaptive", question, text, draft.facts, lang)
        merge_extraction(draft.facts, ext, "adaptive")
        draft.answers.append({"q": question, "a": text[:1000]})
        draft.adaptive_index += 1
        if draft.adaptive_index >= len(draft.adaptive):
            draft.mark_done("adaptive")
    elif stage in ("education", "education_more"):
        ext = await extract_answer("education", _("builder.ask_education"), text, draft.facts, lang)
        before = len(draft.facts.education)
        merge_extraction(draft.facts, ext, "education")
        if len(draft.facts.education) == before:
            error = "builder.nothing_found"
        else:
            draft.mark_done("education")
            if "education_more" in draft.done:
                draft.done.remove("education_more")
    elif stage == "skills":
        items = [x.strip() for x in text.replace(";", ",").replace("\n", ",").split(",") if x.strip()]
        for item in items[:30]:
            if item not in draft.selected:
                draft.selected.append(item[:80])
        await save_draft(session, user.id, draft)
        await ask_stage(message, draft, _)
        return
    elif stage == "languages":
        ext = await extract_answer("languages", _("builder.ask_languages"), text, draft.facts, lang)
        before = len(draft.facts.languages)
        merge_extraction(draft.facts, ext, "languages")
        if len(draft.facts.languages) == before and not ext.languages:
            error = "builder.nothing_found"
        else:
            draft.mark_done("languages")
    elif stage == "extras":
        ext = await extract_answer("extras", _("builder.ask_extras"), text, draft.facts, lang)
        merge_extraction(draft.facts, ext, "extras")
        _mark_known_personal(draft)
        draft.answers.append({"q": _("builder.ask_extras"), "a": text[:1000]})
        draft.mark_done("extras")
    elif stage == "cv_language":
        value = text.strip()[:16]
        draft.cv_language = value
        user.cv_language = value
        draft.mark_done("cv_language")
    else:
        await ask_stage(message, draft, _)
        return

    if error:
        await save_draft(session, user.id, draft)
        await message.answer(_(error))
        return
    if stage not in draft.history[-1:]:
        draft.history.append(stage)
    await advance(message, user, _, session, state, draft)


# --------------------------------------------------------------------------- buttons


@router.callback_query(BuilderCb.filter())
async def builder_button(
    call: CallbackQuery, callback_data: BuilderCb, user: User, _: Translator,
    session: AsyncSession, state: FSMContext,
) -> None:
    action, value = callback_data.action, callback_data.value
    if action == "restart":
        await call.answer()
        await save_draft(session, user.id, None)
        await _begin(call, user, _, session, state)
        return
    draft = await _load(session, user)
    if draft is None:
        await call.answer()
        await _begin(call, user, _, session, state)
        return
    await call.answer()
    stage = draft.stage

    if action == "resume":
        await advance(call, user, _, session, state, draft)
        return
    if action == "back" and draft.history:
        prev = draft.history.pop()
        if prev in draft.done:
            draft.done.remove(prev)
        if prev == "adaptive":
            draft.adaptive_index = max(0, draft.adaptive_index - 1)
        draft.stage = prev
        await save_draft(session, user.id, draft)
        await state.set_state(BuilderStates.answering)
        await ask_stage(call, draft, _)
        return
    if action == "skip":
        if stage == "adaptive":
            draft.adaptive_index += 1
            if draft.adaptive_index >= len(draft.adaptive):
                draft.mark_done("adaptive")
        elif stage == "exp_followup":
            if draft.followups:
                draft.followups.pop(0)
            if not draft.followups:
                draft.mark_done("exp_followup")
        elif stage in OPTIONAL:
            draft.mark_done(stage)
    elif action == "dir":
        draft.direction = value if value in ("known", "help", "exploring") else "exploring"
        draft.mark_done("direction")
    elif action == "noexp":
        draft.no_experience = True
        for s in ("experience", "exp_followup", "exp_more"):
            draft.mark_done(s)
    elif action == "addjob":
        draft.exp_index = None
        for s in ("experience", "exp_followup", "exp_more"):
            if s in draft.done:
                draft.done.remove(s)
    elif action == "addedu":
        for s in ("education", "education_more"):
            if s in draft.done:
                draft.done.remove(s)
    elif action == "next":
        draft.mark_done(stage)
    elif action == "skill":
        try:
            name = draft.suggestions[int(value)]
        except (ValueError, IndexError):
            return
        if name in draft.selected:
            draft.selected.remove(name)
        else:
            draft.selected.append(name)
        await save_draft(session, user.id, draft)
        await ask_stage(call, draft, _)
        return
    elif action == "skills_done":
        tools_lower = {t.lower() for t in KNOWN_TOOLS}
        for name in draft.selected:
            bucket = draft.facts.skills.software if name.lower() in tools_lower else draft.facts.skills.hard
            if name.lower() not in {x.lower() for x in draft.facts.skills.all()}:
                bucket.append(name)
        draft.mark_done("skills")
    elif action == "lang":
        if value == "other":
            draft.stage = "cv_language"
            await save_draft(session, user.id, draft)
            await state.set_state(BuilderStates.answering)
            await show(call, _("builder.ask_cv_language_other"), None)
            return
        draft.cv_language = value
        user.cv_language = value
        draft.mark_done("cv_language")
    elif action == "tpl":
        draft.template = value if value in TEMPLATE_NAMES else None
        draft.mark_done("design")
    else:
        return
    if stage not in draft.history[-1:] and action not in ("addjob", "addedu"):
        draft.history.append(stage)
    await advance(call, user, _, session, state, draft)


# --------------------------------------------------------------------------- generation


async def generate_cv(
    target: Message | CallbackQuery, user: User, _: Translator, session: AsyncSession,
    state: FSMContext, draft: BuilderDraft,
) -> None:
    from app.bot.handlers.cv_preview import send_preview
    from app.services.cv.generator import generate_resume
    from app.services.cv.versions import RenderingError, create_generated_resume

    message = target.message if isinstance(target, CallbackQuery) else target
    assert isinstance(message, Message)
    c = draft.facts.candidate
    if not c.full_name or not (c.email or c.phone):
        for s in ("name", "email") if not c.full_name else ("email", "phone"):
            if s in draft.done:
                draft.done.remove(s)
        await save_draft(session, user.id, draft)
        await message.answer(_("builder.need_name" if not c.full_name else "builder.need_contact"))
        await advance(message, user, _, session, state, draft)
        return

    status = await message.answer(_("builder.generating"))
    await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_DOCUMENT)  # type: ignore[union-attr]
    from app.services.cv.parser import compute_experience_months

    draft.facts.total_experience_months = compute_experience_months(draft.facts)
    profile = await apply_parsed_cv(session, user.id, draft.facts, source="builder")
    profile.target_roles = draft.target_roles
    profile.career_direction = draft.direction
    profile = await ProfileRepository(session).get_full(user.id)
    assert profile is not None
    facts = profile_to_facts(profile)
    language = draft.cv_language or user.cv_language or user.interface_language
    extra = {"answers": draft.answers} if draft.answers else None
    try:
        doc, plan = await generate_resume(
            facts, target_roles=draft.target_roles, language=language, template=draft.template,
            direction=draft.direction, extra=extra,
        )
        result = await create_generated_resume(
            session, user.id, doc, plan=plan,
            meta={"extra_facts": extra, "direction": draft.direction, "source": "builder"},
        )
    except (ValidationError, LLMError, RenderingError) as exc:
        logger.warning("cv generation failed: %s", type(exc).__name__)
        await status.edit_text(_("builder.generation_failed"))
        return
    await save_draft(session, user.id, None)
    try:
        await status.delete()
    except Exception:  # pragma: no cover
        pass
    await send_preview(message, _, state, result.resume, result.version, result.render, first=True)
