"""Natural-language CV editing: User Intent Interpreter + deterministic application."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.prompts import load_prompt, untrusted
from app.providers.llm import LLMError, get_llm
from app.schemas.common import normalize_email, normalize_phone, normalize_url
from app.schemas.resume import SECTION_KEYS, TEMPLATE_CODES, PortfolioLink, ResumeDocument

OpName = Literal[
    "move_section", "remove_section", "emphasize", "shorten", "set_page_limit", "add_link",
    "change_template", "change_language", "update_contact", "rewrite",
]


class EditOperation(BaseModel):
    op: OpName
    section: str | None = None
    position: Literal["up", "down", "top", "bottom"] | None = None
    target: str | None = None
    value: str | None = None

    @field_validator("section", mode="before")
    @classmethod
    def _section(cls, v: object) -> object:
        return v if v in SECTION_KEYS else None


class EditIntent(BaseModel):
    operations: list[EditOperation] = Field(default_factory=list)
    needs_new_facts: bool = False
    clarification_question: str | None = None


# ------------------------------------------------------------------ rule-based interpreter

SECTION_WORDS: dict[str, tuple[str, ...]] = {
    "education": ("education", "образован", "освіт", "ausbildung", "bildung", "studium"),
    "experience": ("experience", "опыт", "досвід", "berufserfahrung", "erfahrung", "work history"),
    "skills": ("skills", "навык", "навич", "kenntnisse", "fähigkeiten"),
    "languages": ("languages", "язык", "мови", "мов ", "sprachen"),
    "projects": ("projects", "проект", "проєкт", "projekte"),
    "professional_summary": ("summary", "резюме", "о себе", "профиль", "profil", "про себе"),
    "certifications": ("certificat", "сертифик", "сертифік", "zertifikat", "курсы", "курси"),
    "portfolio": ("portfolio", "портфолио", "портфоліо"),
    "software": ("software", "программ", "програм", "tools"),
}
DOWN = ("lower", "down", "below", "ниже", "вниз", "нижче", "unten", "nach unten", "в конец", "end")
UP = ("higher", "up", "above", "top", "выше", "вверх", "вище", "нагору", "oben", "nach oben", "в начало")
SHORT = ("short", "корот", "сократ", "скорот", "kürz", "kurz", "compact")
ONE_PAGE = ("one page", "1 page", "одну страниц", "1 страниц", "одну сторінк", "1 сторінк", "eine seite", "1 seite")
EMPHASIS = ("emphasi", "focus", "highlight", "акцент", "подчеркн", "підкресл", "fokus", "hervorheb", "betone")
TEMPLATES = {"classic": "classic_ats", "ats": "classic_ats", "modern": "modern", "creative": "creative",
             "креатив": "creative", "классич": "classic_ats", "класич": "classic_ats", "модерн": "modern"}
LANGS = {"english": "en", "англ": "en", "englisch": "en", "german": "de", "deutsch": "de", "немец": "de",
         "німец": "de", "ukrainian": "uk", "украин": "uk", "україн": "uk", "russian": "ru", "русск": "ru",
         "росій": "ru"}
ADD_FACT_WORDS = ("add experience", "add a job", "добавь опыт", "добавь работ", "додай досвід", "füge erfahrung")


def rule_based_intent(text: str) -> EditIntent:
    lower = text.lower()
    ops: list[EditOperation] = []
    url = next(iter(re.findall(r"https?://\S+|www\.\S+", text)), None)
    if url:
        target = "linkedin" if "linkedin" in url.lower() else "portfolio"
        ops.append(EditOperation(op="add_link", value=url.rstrip(".,"), target=target))
    if any(w in lower for w in ONE_PAGE):
        ops.append(EditOperation(op="set_page_limit", value="1"))
    for key, words in SECTION_WORDS.items():
        if key == "portfolio" and url:
            continue
        if any(w in lower for w in words):
            if any(w in lower for w in DOWN):
                ops.append(EditOperation(op="move_section", section=key, position="down"))
            elif any(w in lower for w in UP):
                ops.append(EditOperation(op="move_section", section=key, position="up"))
    if any(w in lower for w in EMPHASIS):
        m = re.search(r"(?:на|on|auf)\s+(.+)$", text.strip().rstrip("."), re.I)
        ops.append(EditOperation(op="emphasize", value=(m.group(1) if m else text)[:200]))
    if any(w in lower for w in SHORT) and not any(o.op == "set_page_limit" for o in ops):
        m = re.search(r"(?:работы|job|work|роботи|stelle|bei)\s+(?:в|у|at|in|bei)?\s*(.+)$", text.strip().rstrip("."), re.I)
        ops.append(EditOperation(op="shorten", target=m.group(1).strip() if m else None))
    for word, code in TEMPLATES.items():
        if word in lower and ("design" in lower or "дизайн" in lower or "шаблон" in lower or "template" in lower
                              or "vorlage" in lower or "оформлен" in lower):
            ops.append(EditOperation(op="change_template", value=code))
            break
    for word, code in LANGS.items():
        if word in lower and any(w in lower for w in ("translate", "перевед", "переклади", "übersetz", "language", "язык", "мов", "sprache")):
            ops.append(EditOperation(op="change_language", value=code))
            break
    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    if email:
        ops.append(EditOperation(op="update_contact", target="email", value=email.group(0)))
    return EditIntent(
        operations=ops,
        needs_new_facts=any(w in lower for w in ADD_FACT_WORDS),
    )


async def interpret_edit(text: str, doc: ResumeDocument, ui_language: str) -> EditIntent:
    try:
        return await get_llm().generate_json(
            task="user_intent_interpreter",
            system=load_prompt("user_intent_interpreter"),
            user=untrusted("cv_sections", {"section_order": doc.visible_sections(),
                                           "experience": [{"company": e.company, "job_title": e.job_title}
                                                          for e in doc.experience]})
            + "\nUser request:\n" + untrusted("user_request", text[:1500])
            + f"\nInterface language: {ui_language}",
            schema=EditIntent,
            context={"text": text},
            temperature=0.0,
        )
    except LLMError:
        return rule_based_intent(text)


@dataclass(slots=True)
class EditOutcome:
    doc: ResumeDocument
    regenerate: bool = False
    instructions: list[str] = field(default_factory=list)
    new_language: str | None = None
    profile_updates: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    applied: int = 0


def apply_operations(doc: ResumeDocument, intent: EditIntent) -> EditOutcome:
    """Apply structural edits directly; collect wording edits for regeneration."""
    out = EditOutcome(doc=doc.model_copy(deep=True))
    d = out.doc
    order = d.visible_sections()
    for op in intent.operations:
        if op.op == "move_section" and op.section in order:
            i = order.index(op.section)
            order.pop(i)
            j = {"up": max(0, i - 1), "down": min(len(order), i + 1), "top": 0, "bottom": len(order)}[op.position or "down"]
            order.insert(j, op.section)
            out.applied += 1
        elif op.op == "remove_section" and op.section in order:
            order.remove(op.section)
            out.applied += 1
        elif op.op == "set_page_limit" and op.value in ("1", "2"):
            d.page_limit = int(op.value)
            out.regenerate = True
            out.instructions.append(f"Fit the CV on {op.value} page(s): keep only the most relevant bullets.")
            out.applied += 1
        elif op.op == "shorten":
            out.regenerate = True
            out.instructions.append(
                f"Shorten the description of {op.target}." if op.target else "Make the whole CV more concise."
            )
            out.applied += 1
        elif op.op in ("emphasize", "rewrite") and op.value:
            out.regenerate = True
            prefix = "Emphasise" if op.op == "emphasize" else "Rewrite"
            out.instructions.append(f"{prefix}: {op.value[:200]}")
            out.applied += 1
        elif op.op == "add_link":
            url = normalize_url(op.value)
            if not url:
                out.errors.append("invalid_url")
                continue
            if op.target == "linkedin":
                d.candidate.linkedin_url = url
                out.profile_updates["linkedin"] = url
            else:
                if not d.candidate.portfolio_url:
                    d.candidate.portfolio_url = url
                if url not in {p.url for p in d.portfolio}:
                    d.portfolio.append(PortfolioLink(url=url))
                if "portfolio" not in order:
                    order.insert(1 if order else 0, "portfolio")
                out.profile_updates["portfolio"] = url
            out.applied += 1
        elif op.op == "change_template" and op.value in TEMPLATE_CODES:
            d.template = op.value  # type: ignore[assignment]
            out.applied += 1
        elif op.op == "change_language" and op.value:
            out.new_language = op.value[:8]
            out.regenerate = True
            out.applied += 1
        elif op.op == "update_contact" and op.value:
            if op.target == "email":
                value = normalize_email(op.value)
            elif op.target == "phone":
                value = normalize_phone(op.value)
            else:
                value = op.value.strip()[:200] or None
            if not value:
                out.errors.append(f"invalid_{op.target}")
                continue
            if op.target == "location":
                d.candidate.location = value
            elif op.target == "full_name":
                d.candidate.full_name = value
            elif op.target in ("email", "phone"):
                setattr(d.candidate, op.target, value)
            out.profile_updates[op.target or ""] = value
            out.applied += 1
    d.section_order = order  # type: ignore[assignment]
    # Sections the user removed must not reappear through visible_sections().
    for section in [s for s in SECTION_KEYS if s not in order and d.has_content(s)]:
        _clear_section(d, section)
    return out


def _clear_section(d: ResumeDocument, section: str) -> None:
    empty: dict[str, object] = {
        "professional_summary": None, "skills": [], "software": [], "transferable_skills": [],
        "achievements": [], "projects": [], "certifications": [], "portfolio": [], "languages": [],
        "education": [], "additional_experience": [], "experience": [],
    }
    if section in empty:
        setattr(d, section, empty[section])
        if section == "skills":
            d.soft_skills = []
