"""Rendering engine: ResumeDocument -> HTML -> PDF (WeasyPrint) and DOCX (python-docx).

The AI never produces markup. Content is escaped by Jinja2 autoescape; links
are validated URLs from the schema.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, pass_context, select_autoescape

from app.schemas.resume import ResumeDocument, ResumeExperience
from app.services.cv.section_titles import level_label, titles_for

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
SIDEBAR_SECTIONS = ("skills", "software", "languages", "certifications")
MAX_DENSITY = 3


@pass_context
def _level(ctx, value: str) -> str:  # type: ignore[no-untyped-def]
    return level_label(ctx.get("lang", "en"), value)


def _cvdate(value: str | None) -> str:
    if not value:
        return ""
    if len(value) >= 7:
        return f"{value[5:7]}/{value[:4]}"
    return value


def _prettyurl(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"^https?://(www\.)?", "", value).rstrip("/")


_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters.update(cvdate=_cvdate, prettyurl=_prettyurl, level=_level)


def contact_list(doc: ResumeDocument) -> list[tuple[str, str | None]]:
    c = doc.candidate
    items: list[tuple[str, str | None]] = []
    if c.location:
        items.append((c.location, None))
    if c.email:
        items.append((c.email, f"mailto:{c.email}"))
    if c.phone:
        items.append((c.phone, "tel:" + re.sub(r"[^\d+]", "", c.phone)))
    if c.linkedin_url:
        items.append((_prettyurl(c.linkedin_url), c.linkedin_url))
    if c.portfolio_url:
        items.append((_prettyurl(c.portfolio_url), c.portfolio_url))
    return items


def render_html(doc: ResumeDocument) -> str:
    template_dir = TEMPLATES_DIR / doc.template
    css = (template_dir / "style.css").read_text(encoding="utf-8")
    sections = doc.visible_sections()
    lang = doc.document_language.split("-")[0].lower()
    ctx = {
        "doc": doc,
        "css": css,
        "t": titles_for(lang),
        "lang": lang,
        "sections": sections,
        "main_sections": [s for s in sections if s not in SIDEBAR_SECTIONS],
        "side_sections": [s for s in sections if s in SIDEBAR_SECTIONS],
        "contacts": contact_list(doc),
    }
    return _env.get_template(f"{doc.template}/template.html").render(**ctx)


@dataclass(slots=True)
class RenderResult:
    pdf: bytes
    page_count: int
    density: int
    missing: list[str] = field(default_factory=list)
    within_page_limit: bool = True


def html_to_pdf(html: str) -> tuple[bytes, int]:
    from weasyprint import HTML

    document = HTML(string=html, base_url=str(TEMPLATES_DIR)).render()
    return document.write_pdf(), len(document.pages)


def render_pdf(doc: ResumeDocument) -> RenderResult:
    """Render; if a page limit is set, increase density until it fits (max 3 steps)."""
    current = doc.model_copy()
    pdf, pages = html_to_pdf(render_html(current))
    while doc.page_limit and pages > doc.page_limit and current.density < MAX_DENSITY:
        current = current.model_copy(update={"density": current.density + 1})
        pdf, pages = html_to_pdf(render_html(current))
    missing = verify_pdf(pdf, current)
    return RenderResult(
        pdf=pdf, page_count=pages, density=current.density, missing=missing,
        within_page_limit=not doc.page_limit or pages <= doc.page_limit,
    )


def _norm(text: str) -> str:
    text = text.replace("­", "").replace(" ", " ")
    text = re.sub(r"-\n", "", text)
    return re.sub(r"\s+", " ", text).lower()


def essential_facts(doc: ResumeDocument) -> list[str]:
    """Strings that must survive rendering."""
    c = doc.candidate
    items: list[str] = [c.full_name]
    if c.email:
        items.append(c.email)
    exps: list[ResumeExperience] = [*doc.experience, *doc.additional_experience]
    for e in exps:
        items += [x for x in (e.company, e.job_title) if x]
    for ed in doc.education:
        items += [x for x in (ed.institution,) if x]
    items += [lang.language for lang in doc.languages]
    return items


def verify_pdf(pdf: bytes, doc: ResumeDocument) -> list[str]:
    """Check that the PDF has extractable text containing every essential fact."""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf)) as document:
        text = _norm("\n".join(page.extract_text() or "" for page in document.pages))
    flat = text.replace(" ", "")
    missing = []
    for fact in essential_facts(doc):
        f = _norm(fact)
        if f not in text and f.replace(" ", "") not in flat:
            missing.append(fact)
    return missing


# ----------------------------------------------------------------------------- DOCX


def _add_hyperlink(paragraph, url: str, text: str) -> None:  # type: ignore[no-untyped-def]
    from docx.opc.constants import RELATIONSHIP_TYPE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    part = paragraph.part
    r_id = part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "1F4E79")
    rpr.append(color)
    run.append(rpr)
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    run.append(t)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def render_docx(doc: ResumeDocument) -> bytes:
    import docx
    from docx.enum.text import WD_TAB_ALIGNMENT
    from docx.shared import Mm, Pt, RGBColor

    lang = doc.document_language.split("-")[0].lower()
    t = titles_for(lang)
    accent = {"classic_ats": RGBColor(0x11, 0x11, 0x11), "modern": RGBColor(0x1E, 0x3A, 0x5F),
              "creative": RGBColor(0xC4, 0x56, 0x2B)}[doc.template]

    d = docx.Document()
    section = d.sections[0]
    section.page_height, section.page_width = Mm(297), Mm(210)
    for side in ("left_margin", "right_margin"):
        setattr(section, side, Mm(17))
    section.top_margin = section.bottom_margin = Mm(15)
    normal = d.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(10)
    normal.paragraph_format.space_after = Pt(2)

    name = d.add_paragraph()
    run = name.add_run(doc.candidate.full_name)
    run.bold = True
    run.font.size = Pt(20)
    run.font.color.rgb = accent
    if doc.candidate.headline:
        p = d.add_paragraph()
        p.add_run(doc.candidate.headline).font.size = Pt(12)

    c = doc.candidate
    contact = d.add_paragraph()
    parts: list[tuple[str, str | None]] = []
    if c.location:
        parts.append((c.location, None))
    if c.email:
        parts.append((c.email, f"mailto:{c.email}"))
    if c.phone:
        parts.append((c.phone, None))
    if c.linkedin_url:
        parts.append((_prettyurl(c.linkedin_url), c.linkedin_url))
    if c.portfolio_url:
        parts.append((_prettyurl(c.portfolio_url), c.portfolio_url))
    for i, (text, url) in enumerate(parts):
        if i:
            contact.add_run("  |  ")
        if url:
            _add_hyperlink(contact, url, text)
        else:
            contact.add_run(text)

    def heading(text: str) -> None:
        p = d.add_paragraph()
        p.paragraph_format.space_before = Pt(10)
        p.paragraph_format.keep_with_next = True
        r = p.add_run(text.upper())
        r.bold = True
        r.font.size = Pt(11)
        r.font.color.rgb = accent

    def bullet(text: str) -> None:
        d.add_paragraph(text, style="List Bullet")

    def dates(item) -> str:  # type: ignore[no-untyped-def]
        start = _cvdate(item.start_date)
        end = t["present"] if getattr(item, "is_current", False) else _cvdate(item.end_date)
        return f"{start} – {end}" if start and end else (start or end)

    def entry_line(title: str, meta: str) -> None:
        p = d.add_paragraph()
        p.paragraph_format.keep_with_next = True
        p.paragraph_format.tab_stops.add_tab_stop(Mm(176), WD_TAB_ALIGNMENT.RIGHT)
        r = p.add_run(title)
        r.bold = True
        if meta:
            p.add_run("\t" + meta)

    def experiences(items: list[ResumeExperience]) -> None:
        for e in items:
            title = " · ".join(x for x in (e.job_title, e.company) if x)
            meta = " · ".join(x for x in (dates(e), e.location or "") if x)
            entry_line(title, meta)
            for b in e.bullets:
                bullet(b)
            if e.tools:
                d.add_paragraph(", ".join(e.tools)).runs[0].italic = True

    for key in doc.visible_sections():
        heading(t[key])
        if key == "professional_summary":
            d.add_paragraph(doc.professional_summary or "")
        elif key == "experience":
            experiences(doc.experience)
        elif key == "additional_experience":
            experiences(doc.additional_experience)
        elif key == "achievements":
            for a in doc.achievements:
                bullet(a)
        elif key == "skills":
            if doc.skills:
                d.add_paragraph(" · ".join(doc.skills))
            if doc.soft_skills:
                p = d.add_paragraph()
                p.add_run(t["soft_skills"] + ": ").bold = True
                p.add_run(" · ".join(doc.soft_skills))
        elif key == "software":
            d.add_paragraph(" · ".join(doc.software))
        elif key == "transferable_skills":
            for s in doc.transferable_skills:
                bullet(s)
        elif key == "education":
            for e in doc.education:
                title = ", ".join(x for x in (e.degree, e.specialization) if x)
                title = " · ".join(x for x in (title, e.institution or "") if x)
                meta = dates(e) + (f" ({t['in_progress']})" if e.status == "in_progress" else "")
                entry_line(title, meta)
                for det in e.details:
                    bullet(det)
        elif key == "languages":
            d.add_paragraph(" · ".join(
                f"{x.language} — {level_label(lang, x.level)}" if level_label(lang, x.level) else x.language
                for x in doc.languages
            ))
        elif key == "projects":
            for p in doc.projects:
                para = d.add_paragraph()
                para.add_run(p.name).bold = True
                if p.role:
                    para.add_run(f" · {p.role}")
                if p.url:
                    para.add_run(" · ")
                    _add_hyperlink(para, p.url, _prettyurl(p.url))
                if p.description:
                    d.add_paragraph(p.description)
        elif key == "certifications":
            for cert in doc.certifications:
                bullet(", ".join(x for x in (cert.name, cert.issuer or "", _cvdate(cert.date)) if x))
        elif key == "portfolio":
            for link in doc.portfolio:
                para = d.add_paragraph(style="List Bullet")
                if link.title:
                    para.add_run(f"{link.title}: ")
                _add_hyperlink(para, link.url or "", _prettyurl(link.url))

    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def render_preview_png(pdf: bytes, scale: float = 1.4) -> bytes:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf)
    try:
        image = document[0].render(scale=scale).to_pil()
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    finally:
        document.close()
