"""Rule-based CV extraction.

Used (1) as the CV Parser in MOCK_MODE and (2) in production to cross-check
contact details returned by the LLM against the source document. It only
copies values that literally appear in the text.
"""

from __future__ import annotations

import re
from typing import Any

from app.schemas.common import normalize_email, normalize_phone, normalize_url

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<![\w/])(\+?\d[\d ()./-]{7,}\d)(?![\w/])")
URL_RE = re.compile(r"(https?://[^\s<>\"')]+|www\.[^\s<>\"')]+|linkedin\.com/[^\s<>\"')]+)", re.I)
DATE_TOKEN = r"(?:\d{1,2}[./])?\d{4}|[A-Za-zÄäÖöÜü]{3,9}\.?\s+\d{4}"
PRESENT_TOKEN = r"present|current|now|today|heute|aktuell|jetzt|настоящее время|н\.в\.|сейчас|теперішній час|дотепер|зараз"
RANGE_RE = re.compile(rf"({DATE_TOKEN})\s*(?:-|–|—|bis|по|до|to)\s*({DATE_TOKEN}|{PRESENT_TOKEN})", re.I)

SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "summary": ("summary", "profile", "about me", "professional summary", "profil", "über mich",
                "kurzprofil", "о себе", "профиль", "резюме", "про себе", "профіль"),
    "experience": ("experience", "work experience", "professional experience", "employment history",
                   "work history", "berufserfahrung", "berufliche erfahrung", "praxiserfahrung",
                   "опыт работы", "опыт", "досвід роботи", "досвід", "трудовой опыт"),
    "education": ("education", "academic background", "ausbildung", "bildung", "bildungsweg",
                  "studium", "образование", "освіта"),
    "skills": ("skills", "key skills", "technical skills", "core competencies", "competencies",
               "kenntnisse", "fähigkeiten", "kompetenzen", "skills & tools", "навыки",
               "навички", "ключевые навыки", "ключові навички", "software", "tools", "программы",
               "програми", "edv-kenntnisse", "it-kenntnisse"),
    "languages": ("languages", "language skills", "sprachen", "sprachkenntnisse", "языки",
                  "знание языков", "мови", "знання мов", "мовні навички"),
    "certifications": ("certifications", "certificates", "courses", "trainings", "zertifikate",
                       "weiterbildung", "kurse", "сертификаты", "курсы", "сертифікати", "курси"),
    "projects": ("projects", "portfolio", "projekte", "проекты", "проєкти", "проекти"),
}

LANGUAGE_NAMES: dict[str, str] = {
    "english": "English", "englisch": "English", "английский": "English", "англійська": "English",
    "german": "German", "deutsch": "German", "немецкий": "German", "німецька": "German",
    "ukrainian": "Ukrainian", "ukrainisch": "Ukrainian", "украинский": "Ukrainian", "українська": "Ukrainian",
    "russian": "Russian", "russisch": "Russian", "русский": "Russian", "російська": "Russian",
    "polish": "Polish", "polnisch": "Polish", "польский": "Polish", "польська": "Polish",
    "french": "French", "französisch": "French", "французский": "French", "французька": "French",
    "spanish": "Spanish", "spanisch": "Spanish", "испанский": "Spanish", "іспанська": "Spanish",
    "italian": "Italian", "italienisch": "Italian", "итальянский": "Italian", "італійська": "Italian",
}

LEVEL_RE = re.compile(
    r"\b(A1|A2|B1|B2|C1|C2)\b|native|mother tongue|muttersprache|fluent|fließend|"
    r"родной|рідна|свободно|вільно|свободный|вільний",
    re.I,
)


def _heading_key(line: str) -> str | None:
    cleaned = re.sub(r"[:\-–—•|_*#]+", " ", line).strip().lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned or len(cleaned) > 40:
        return None
    for key, aliases in SECTION_ALIASES.items():
        if cleaned in aliases:
            return key
    return None


def split_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        key = _heading_key(line)
        if key:
            current = key
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


def find_emails(text: str) -> list[str]:
    return list(dict.fromkeys(e for e in (normalize_email(m) for m in EMAIL_RE.findall(text)) if e))


def find_phones(text: str) -> list[str]:
    out: list[str] = []
    for match in PHONE_RE.findall(text):
        if RANGE_RE.fullmatch(match.strip()) or re.fullmatch(r"[\d./ -]*\d{4}\s*[-–]\s*\d{4}", match):
            continue  # date range, not a phone
        digits = re.sub(r"\D", "", match)
        if len(digits) < 9:
            continue
        phone = normalize_phone(match)
        if phone and phone not in out:
            out.append(phone)
    return out


def find_urls(text: str, extra_links: list[str] | None = None) -> list[str]:
    urls: list[str] = []
    for candidate in [*URL_RE.findall(text), *(extra_links or [])]:
        if candidate.lower().startswith("mailto:"):
            continue
        url = normalize_url(candidate)
        if url and "@" not in url.split("//", 1)[-1].split("/", 1)[0] and url not in urls:
            urls.append(url)
    return urls


def _guess_name(header_lines: list[str]) -> str | None:
    for line in header_lines[:6]:
        if EMAIL_RE.search(line) or URL_RE.search(line) or any(ch.isdigit() for ch in line):
            continue
        words = line.replace(",", " ").split()
        if 2 <= len(words) <= 4 and all(re.fullmatch(r"[A-Za-zÀ-ÿА-Яа-яЁёІіЇїЄєҐґ'’.-]+", w) for w in words):
            if all(w[:1].isupper() for w in words):
                return " ".join(words)
    return None


def _parse_languages(lines: list[str], full_text: str) -> list[dict[str, Any]]:
    found: dict[str, str] = {}
    source = lines or full_text.split("\n")
    for line in source:
        lower = line.lower()
        for token, name in LANGUAGE_NAMES.items():
            for m in re.finditer(rf"\b{re.escape(token)}\b", lower):
                window = line[m.end(): m.end() + 40]
                level_match = LEVEL_RE.search(window)
                level = level_match.group(0) if level_match else "Unknown"
                if name not in found or found[name] == "Unknown":
                    found[name] = level
    # Without a languages section, only keep languages with an explicit level.
    if not lines:
        found = {k: v for k, v in found.items() if v != "Unknown"}
    return [{"language": k, "level": v} for k, v in found.items()]


def _parse_skills(lines: list[str]) -> list[str]:
    items: list[str] = []
    for line in lines:
        line = re.sub(r"^[•\-*·▪●]\s*", "", line)
        if ":" in line and len(line.split(":", 1)[0]) < 30:
            line = line.split(":", 1)[1]
        for part in re.split(r"[,;|•·]", line):
            part = part.strip(" .")
            if 1 < len(part) <= 40 and part not in items:
                items.append(part)
    return items[:40]


def _parse_experience(lines: list[str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for idx, line in enumerate(lines):
        rng = RANGE_RE.search(line)
        if rng:
            if current:
                entries.append(current)
            head = (line[: rng.start()] + line[rng.end():]).strip(" |,–-")
            title, company = None, None
            if head:
                parts = [p.strip() for p in re.split(r"\s[|@–—-]\s|,\s| at | bei | в ", head) if p.strip()]
                title = parts[0] if parts else None
                company = parts[1] if len(parts) > 1 else None
            elif idx > 0:
                title = lines[idx - 1]
            current = {
                "job_title": title,
                "company": company,
                "start_date": rng.group(1),
                "end_date": rng.group(2),
                "responsibilities": [],
            }
        elif current is not None:
            bullet = re.sub(r"^[•\-*·▪●]\s*", "", line)
            if current["company"] is None and not line[:1] in "•-*·▪●" and len(line) < 80:
                current["company"] = bullet
            else:
                current["responsibilities"].append(bullet)
    if current:
        entries.append(current)
    return entries[:15]


def _parse_education(lines: list[str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for idx, line in enumerate(lines):
        rng = RANGE_RE.search(line)
        if rng:
            head = (line[: rng.start()] + line[rng.end():]).strip(" |,–-") or (lines[idx - 1] if idx else "")
            entries.append(
                {"institution": head or None, "start_date": rng.group(1), "end_date": rng.group(2)}
            )
    if not entries and lines:
        entries.append({"institution": lines[0]})
    return entries[:10]


def months_between(start: str | None, end: str | None, current_ym: str) -> int:
    if not start:
        return 0
    def to_months(v: str) -> int:
        year = int(v[:4])
        month = int(v[5:7]) if len(v) >= 7 else 1
        return year * 12 + month
    end_val = end or current_ym
    return max(0, to_months(end_val) - to_months(start))


def heuristic_parse(text: str, links: list[str] | None = None) -> dict[str, Any]:
    """Return a dict compatible with :class:`app.schemas.cv.ParsedCV`."""
    sections = split_sections(text)
    header = sections.get("header", [])
    emails = find_emails(text)
    phones = find_phones("\n".join(header) or text)
    urls = find_urls(text, links)
    linkedin = next((u for u in urls if "linkedin.com" in u.lower()), None)
    others = [u for u in urls if u != linkedin]

    software_lines = sections.get("skills", [])
    return {
        "candidate": {
            "full_name": _guess_name(header),
            "email": emails[0] if emails else None,
            "phone": phones[0] if phones else None,
            "linkedin_url": linkedin,
            "portfolio_url": others[0] if others else None,
            "other_links": others[1:],
        },
        "summary": " ".join(sections.get("summary", []))[:1500] or None,
        "experience": _parse_experience(sections.get("experience", [])),
        "education": _parse_education(sections.get("education", [])),
        "skills": {"hard": _parse_skills(software_lines)},
        "languages": _parse_languages(sections.get("languages", []), text),
        "certifications": [{"name": line[:200]} for line in sections.get("certifications", [])[:10]],
        "projects": [{"name": line[:200]} for line in sections.get("projects", [])[:10]],
        "warnings": ["parsed_without_ai"],
    }
