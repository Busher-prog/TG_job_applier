"""CV Parser agent: text -> validated ParsedCV, grounded in the source document."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from app.prompts import load_prompt, untrusted
from app.providers.llm import get_llm
from app.schemas.cv import ParsedCV
from app.services.cv import heuristic_parser as hp

MAX_CV_CHARS = 30000


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _url_key(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url.lower()).rstrip("/")


def ground_parsed_cv(parsed: ParsedCV, text: str, links: list[str]) -> ParsedCV:
    """Drop contact data that does not literally occur in the document."""
    lower = text.lower()
    digits_text = _digits(text)
    link_keys = {_url_key(u) for u in hp.find_urls(text, links)}
    c = parsed.candidate

    if c.email and c.email.lower() not in lower:
        c.email = None
    if not c.email:
        emails = hp.find_emails(text)
        c.email = emails[0] if emails else None

    if c.phone and _digits(c.phone)[-7:] not in digits_text:
        c.phone = None
    if not c.phone:
        phones = hp.find_phones(text)
        c.phone = phones[0] if phones else None

    def grounded(url: str | None) -> str | None:
        if not url:
            return None
        key = _url_key(url)
        return url if any(key == k or key in k or k in key for k in link_keys) else None

    c.linkedin_url = grounded(c.linkedin_url)
    c.portfolio_url = grounded(c.portfolio_url)
    c.other_links = [u for u in (grounded(u) for u in c.other_links) if u]
    if not c.linkedin_url:
        c.linkedin_url = next((u for u in hp.find_urls(text, links) if "linkedin.com" in u.lower()), None)

    for proj in parsed.projects:
        proj.url = grounded(proj.url)
    for cert in parsed.certifications:
        cert.url = grounded(cert.url)

    for exp in parsed.experience:
        if exp.company and exp.company.lower()[:12] not in lower:
            parsed.warnings.append(f"unverified_company:{exp.company[:60]}")

    parsed.total_experience_months = compute_experience_months(parsed)
    return parsed


def compute_experience_months(parsed: ParsedCV, now: datetime | None = None) -> int | None:
    """Total months of paid experience with overlapping periods merged."""
    now = now or datetime.now(UTC)
    current = f"{now.year:04d}-{now.month:02d}"

    def to_m(v: str) -> int:
        return int(v[:4]) * 12 + (int(v[5:7]) if len(v) >= 7 else 1)

    intervals: list[tuple[int, int]] = []
    for e in parsed.experience:
        if not e.start_date or e.employment_type == "volunteer":
            continue
        end = e.end_date or (current if e.is_current else None)
        if end is None:
            continue
        start_m, end_m = to_m(e.start_date), to_m(end)
        if end_m >= start_m:
            intervals.append((start_m, end_m))
    if not intervals:
        return None
    intervals.sort()
    total, (cur_s, cur_e) = 0, intervals[0]
    for s, e in intervals[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            total += cur_e - cur_s
            cur_s, cur_e = s, e
    total += cur_e - cur_s
    return total


async def parse_cv_text(text: str, links: list[str] | None = None) -> ParsedCV:
    links = links or []
    clipped = text[:MAX_CV_CHARS]
    user_prompt = (
        "Extract structured data from the CV below.\n"
        + untrusted("cv_document", clipped)
        + "\nHyperlinks embedded in the file:\n"
        + untrusted("cv_links", links)
    )
    parsed = await get_llm().generate_json(
        task="cv_parser",
        system=load_prompt("cv_parser"),
        user=user_prompt,
        schema=ParsedCV,
        context={"text": clipped, "links": links},
        temperature=0.0,
    )
    return ground_parsed_cv(parsed, clipped, links)
