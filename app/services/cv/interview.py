"""Adaptive interview for the CV Builder: extraction, follow-ups, profession questions."""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from app.prompts import load_prompt, untrusted
from app.providers.llm import LLMError, get_llm
from app.schemas.common import StrList, clean_list, normalize_email, normalize_phone, normalize_url
from app.schemas.cv import (
    CandidateContact,
    CertificationItem,
    EducationItem,
    ExperienceItem,
    LanguageItem,
    ParsedCV,
    ProjectItem,
    SkillsBlock,
)
from app.services.cv import heuristic_parser as hp
from app.services.cv.facts import facts_payload, tokens
from app.services.users.profile_edit import parse_languages

logger = logging.getLogger(__name__)


class InterviewExtraction(BaseModel):
    candidate: CandidateContact = Field(default_factory=CandidateContact)
    target_role: str | None = None
    experience: list[ExperienceItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    skills: SkillsBlock = Field(default_factory=SkillsBlock)
    languages: list[LanguageItem] = Field(default_factory=list)
    certifications: list[CertificationItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    follow_up_questions: StrList = Field(default_factory=list)


class AdaptiveQuestions(BaseModel):
    questions: StrList = Field(default_factory=list)


class SkillSuggestions(BaseModel):
    skills: StrList = Field(default_factory=list)


# ---------------------------------------------------------------- deterministic helpers

KNOWN_TOOLS = (
    "CapCut", "Adobe Premiere Pro", "Premiere Pro", "Premiere", "After Effects", "DaVinci Resolve", "Final Cut Pro",
    "Photoshop", "Illustrator", "Figma", "Canva", "Lightroom", "Salesforce", "HubSpot", "Pipedrive", "SAP", "SAP TM",
    "Excel", "MS Office", "Word", "PowerPoint", "Google Sheets", "Jira", "Notion", "Trello", "Python", "SQL",
    "1C", "Bitrix24", "AmoCRM", "Transporeon", "TimoCom", "Shopify", "WordPress", "Instagram", "TikTok", "YouTube",
)


def find_tools(text: str) -> list[str]:
    found: list[str] = []
    lower = text.lower()
    for tool in sorted(KNOWN_TOOLS, key=len, reverse=True):
        if re.search(rf"(?<![\w]){re.escape(tool.lower())}(?![\w])", lower) and not any(
            tool.lower() in f.lower() for f in found
        ):
            found.append(tool)
    return found


def ground_contacts(contact: CandidateContact, answer: str) -> CandidateContact:
    """Contacts must literally occur in the answer (protects against model invention)."""
    lower = answer.lower()
    digits = re.sub(r"\D", "", answer)
    if contact.email and contact.email.lower() not in lower:
        contact.email = None
    if contact.phone and re.sub(r"\D", "", contact.phone)[-7:] not in digits:
        contact.phone = None
    for attr in ("linkedin_url", "portfolio_url"):
        url = getattr(contact, attr)
        if url and re.sub(r"^https?://(www\.)?", "", url).rstrip("/").lower()[:20] not in lower:
            setattr(contact, attr, None)
    emails = hp.find_emails(answer)
    if not contact.email and emails:
        contact.email = emails[0]
    phones = hp.find_phones(answer)
    if not contact.phone and phones:
        contact.phone = phones[0]
    for url in hp.find_urls(answer):
        if "linkedin.com" in url.lower():
            contact.linkedin_url = contact.linkedin_url or url
        elif not contact.portfolio_url:
            contact.portfolio_url = url
    return contact


def heuristic_extract(stage: str, answer: str, expected_field: str | None = None) -> dict[str, Any]:
    """Deterministic extraction (MOCK_MODE and AI fallback)."""
    text = answer.strip()
    out: dict[str, Any] = {"candidate": {}}
    cand = out["candidate"]
    if stage == "name":
        stripped = hp.EMAIL_RE.sub(" ", text)
        stripped = hp.URL_RE.sub(" ", stripped)
        stripped = hp.PHONE_RE.sub(" ", stripped)
        first_line = re.split(r"[,\n;]", stripped.strip(" ,;"))[0].strip()
        words = first_line.split()
        if 1 <= len(words) <= 5 and not any(ch.isdigit() or ch == "@" for ch in first_line):
            cand["full_name"] = " ".join(w[:1].upper() + w[1:] for w in words)
    elif stage == "location":
        parts = [p.strip() for p in text.split(",") if p.strip()]
        if parts and "@" not in parts[0]:
            cand["city"] = parts[0]
            if len(parts) > 1:
                cand["country"] = parts[1]
    elif stage == "target_role":
        out["target_role"] = text[:120]
    elif stage in ("experience", "exp_followup"):
        if stage == "exp_followup" and expected_field:
            item: dict[str, Any] = {}
            if expected_field == "dates":
                m = hp.RANGE_RE.search(text)
                if m:
                    item["start_date"], item["end_date"] = m.group(1), m.group(2)
                else:
                    years = re.findall(r"\d{1,2}[./]\d{4}|\d{4}", text)
                    if years:
                        item["start_date"] = years[0]
                        item["end_date"] = years[1] if len(years) > 1 else None
            elif expected_field == "responsibilities":
                item["responsibilities"] = [s.strip() for s in re.split(r"[.;\n]+", text) if len(s.strip()) > 3]
            else:
                item[expected_field] = text[:200]
            item["tools"] = find_tools(text)
            out["experience"] = [item]
        else:
            m = hp.RANGE_RE.search(text)
            first = re.split(r"[.\n;]", text)[0]
            head = first[: m.start()] if m and m.start() < len(first) else first
            title = company = None
            parts = re.split(r"\s+(?:at|@|bei|в|у|in)\s+|\s[|–—-]\s|,\s*", head.strip(), maxsplit=2, flags=re.I)
            parts = [p.strip(" ,") for p in parts if p.strip(" ,")]
            if parts:
                title = parts[0][:120]
            if len(parts) > 1:
                company = parts[1][:120]
            rest = text[len(first):]
            item = {
                "job_title": title, "company": company,
                "start_date": m.group(1) if m else None, "end_date": m.group(2) if m else None,
                "responsibilities": [s.strip() for s in re.split(r"[.;\n]+", rest) if len(s.strip()) > 3][:6],
                "tools": find_tools(text),
            }
            out["experience"] = [item]
    elif stage == "education":
        m = hp.RANGE_RE.search(text)
        body = (text[: m.start()] + text[m.end():]) if m else text
        parts = [p.strip() for p in re.split(r",|\n", body) if p.strip()]
        out["education"] = [{
            "institution": parts[0] if parts else None,
            "degree": parts[1] if len(parts) > 1 else None,
            "specialization": parts[2] if len(parts) > 2 else None,
            "start_date": m.group(1) if m else None,
            "end_date": m.group(2) if m else None,
            "status": "in_progress" if m and hp.is_present_token(m.group(2)) else ("completed" if m else "unknown"),
        }]
    elif stage == "skills":
        out["skills"] = {"hard": clean_list(re.split(r"[,;\n]+", text), 30, 80)}
    elif stage == "languages":
        out["languages"] = [{"language": n, "level": lvl} for n, lvl in parse_languages(text)]
    elif stage == "extras":
        lines = [x.strip(" -•") for x in re.split(r"[\n;]+", text) if x.strip(" -•")]
        out["certifications"] = [{"name": x[:200]} for x in lines if not normalize_url(x)][:10]
    elif stage == "adaptive":
        out["skills"] = {"software": find_tools(text)}
    if stage not in ("experience", "exp_followup"):
        tools = find_tools(text)
        if tools and stage not in ("skills",):
            out.setdefault("skills", {}).setdefault("software", tools)
    return out


# ---------------------------------------------------------------- agent calls


async def extract_answer(
    stage: str,
    question: str,
    answer: str,
    facts: ParsedCV,
    ui_language: str,
    expected_field: str | None = None,
) -> InterviewExtraction:
    request = {"stage": stage, "question": question, "expected_field": expected_field,
               "interface_language": ui_language}
    try:
        result = await get_llm().generate_json(
            task="interview_extract",
            system=load_prompt("interview_agent"),
            user=untrusted("context", request) + "\nAlready known facts:\n" + untrusted("facts", facts_payload(facts))
            + "\nCandidate answer:\n" + untrusted("answer", answer[:4000]),
            schema=InterviewExtraction,
            context={"stage": stage, "answer": answer, "expected_field": expected_field},
            temperature=0.0,
        )
    except LLMError:
        result = InterviewExtraction.model_validate(heuristic_extract(stage, answer, expected_field))
    result.candidate = ground_contacts(result.candidate, answer)
    if stage != "name":
        result.candidate.full_name = None if not result.candidate.full_name or result.candidate.full_name.lower() not in answer.lower() else result.candidate.full_name
    result.follow_up_questions = result.follow_up_questions[:2]
    return result


QUESTION_BANKS = {
    "video": ("video", "editor", "videographer", "монтаж", "відео", "видео", "content", "creator", "контент", "cutter"),
    "sales": ("sales", "account", "продаж", "vertrieb", "verkauf", "business development", "менеджер по продажам"),
    "logistics": ("logistic", "logistik", "логист", "dispatch", "disponent", "transport", "spedition", "supply"),
}


def question_bank_key(facts: ParsedCV, target_roles: list[str]) -> str:
    if not facts.experience:
        return "no_experience"
    text = " ".join([*target_roles, facts.primary_field or "", *(e.job_title or "" for e in facts.experience)]).lower()
    for key, hints in QUESTION_BANKS.items():
        if any(h in text for h in hints):
            return key
    return "generic"


async def adaptive_questions(facts: ParsedCV, target_roles: list[str], ui_language: str) -> list[str]:
    """AI-generated profession questions; falls back to the localised question bank."""
    try:
        result = await get_llm().generate_json(
            task="interview_questions",
            system=load_prompt("interview_questions"),
            user=untrusted("facts", facts_payload(facts)) + "\n"
            + untrusted("request", {"target_roles": target_roles, "interface_language": ui_language}),
            schema=AdaptiveQuestions,
            context={"facts": facts, "target_roles": target_roles, "language": ui_language},
            temperature=0.4,
        )
        questions = result.questions[:4]
    except LLMError:
        questions = []
    if not questions:
        from app.services.i18n import gettext, load_locale

        key = question_bank_key(facts, target_roles)
        loc = load_locale(ui_language)
        questions = [gettext(ui_language, k) for k in sorted(loc) if k.startswith(f"builder.bank.{key}.")]
    return questions


async def suggest_skills(facts: ParsedCV, target_roles: list[str], answers: list[str]) -> list[str]:
    known = {s.lower() for s in facts.skills.all()}
    try:
        result = await get_llm().generate_json(
            task="skill_suggester",
            system=load_prompt("skill_suggester"),
            user=untrusted("facts", facts_payload(facts, {"answers": answers})) + "\n"
            + untrusted("target_roles", target_roles),
            schema=SkillSuggestions,
            context={"facts": facts, "answers": answers},
            temperature=0.3,
        )
        items = result.skills
    except LLMError:
        items = []
    if not items:
        pool = " ".join([*answers, *(" ".join(e.responsibilities + e.tools) for e in facts.experience)])
        items = find_tools(pool)
    return [s for s in dict.fromkeys(items) if s.lower() not in known][:12]


# ---------------------------------------------------------------- merging


def _merge_contact(facts: ParsedCV, c: CandidateContact) -> None:
    for attr in ("full_name", "email", "phone", "city", "country", "linkedin_url", "portfolio_url"):
        value = getattr(c, attr)
        if value:
            setattr(facts.candidate, attr, value)


def merge_extraction(
    facts: ParsedCV, ext: InterviewExtraction, stage: str, exp_index: int | None = None
) -> int | None:
    """Merge extracted facts into the draft. Returns index of the experience being built."""
    _merge_contact(facts, ext.candidate)
    if stage == "exp_followup" and exp_index is not None and ext.experience and exp_index < len(facts.experience):
        target = facts.experience[exp_index]
        new = ext.experience[0]
        for attr in ("company", "job_title", "location", "start_date", "end_date", "employment_type"):
            if getattr(new, attr) and not getattr(target, attr):
                setattr(target, attr, getattr(new, attr))
        if new.is_current:
            target.is_current, target.end_date = True, None
        target.responsibilities = list(dict.fromkeys([*target.responsibilities, *new.responsibilities]))
        target.achievements = list(dict.fromkeys([*target.achievements, *new.achievements]))
        target.tools = list(dict.fromkeys([*target.tools, *new.tools]))
    elif ext.experience:
        for item in ext.experience:
            if item.company or item.job_title:
                facts.experience.append(item)
                exp_index = facts.experience.index(item)
    for edu in ext.education:
        if edu.institution or edu.degree:
            facts.education.append(edu)
    for attr in ("hard", "soft", "software", "tools", "technical"):
        current = getattr(facts.skills, attr)
        for name in getattr(ext.skills, attr):
            if name.lower() not in {x.lower() for x in current}:
                current.append(name)
    known_langs = {lang.language.lower(): lang for lang in facts.languages}
    for lang in ext.languages:
        if lang.language.lower() in known_langs:
            if lang.level != "Unknown":
                known_langs[lang.language.lower()].level = lang.level
        else:
            facts.languages.append(lang)
    facts.certifications.extend(ext.certifications)
    facts.projects.extend(ext.projects)
    return exp_index


def missing_experience_fields(item: ExperienceItem) -> list[str]:
    missing = []
    if not item.job_title:
        missing.append("job_title")
    if not item.company:
        missing.append("company")
    if not item.start_date:
        missing.append("dates")
    if not item.responsibilities and not item.achievements:
        missing.append("responsibilities")
    return missing


def role_tokens_match(a: str, b: str) -> bool:
    return bool(tokens(a) & tokens(b))


__all__ = [
    "InterviewExtraction", "adaptive_questions", "extract_answer", "merge_extraction",
    "missing_experience_fields", "suggest_skills", "normalize_email", "normalize_phone",
]
