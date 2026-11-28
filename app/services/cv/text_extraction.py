"""Text extraction from PDF / DOCX with OCR fallback for scanned PDFs."""

from __future__ import annotations

import io
import logging
import re
import shutil
from dataclasses import dataclass, field

from app.services.cv.file_validation import CVFileError

logger = logging.getLogger(__name__)

MIN_TEXT_CHARS = 150
OCR_MAX_PAGES = 5


@dataclass(slots=True)
class ExtractionResult:
    text: str
    method: str  # "text" | "ocr"
    page_count: int
    links: list[str] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return len(self.text)


def _normalize_text(text: str) -> str:
    text = text.replace(" ", " ").replace("​", "").replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def _dedupe(links: list[str]) -> list[str]:
    seen: list[str] = []
    for link in links:
        link = link.strip()
        if link and link not in seen and re.match(r"^(https?://|mailto:)", link, re.I):
            seen.append(link)
    return seen[:30]


def ocr_available() -> bool:
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return shutil.which("tesseract") is not None


def extract_pdf(data: bytes, ocr_languages: str = "eng") -> ExtractionResult:
    import pdfplumber

    pages_text: list[str] = []
    links: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages:
                pages_text.append(page.extract_text(x_tolerance=1.5, y_tolerance=3) or "")
                for link in page.hyperlinks or []:
                    uri = link.get("uri")
                    if uri:
                        links.append(uri)
    except Exception as exc:  # pdfminer raises many exception types
        raise CVFileError("corrupted") from exc

    text = _normalize_text("\n\n".join(pages_text))
    if len(text) >= MIN_TEXT_CHARS:
        return ExtractionResult(text=text, method="text", page_count=page_count, links=_dedupe(links))

    # Scanned document: try OCR.
    if not ocr_available():
        raise CVFileError("no_text")
    ocr_text = _ocr_pdf(data, ocr_languages)
    if len(ocr_text) < MIN_TEXT_CHARS // 2:
        raise CVFileError("no_text")
    return ExtractionResult(text=ocr_text, method="ocr", page_count=page_count, links=_dedupe(links))


def _ocr_pdf(data: bytes, languages: str) -> str:
    import pypdfium2 as pdfium
    import pytesseract

    doc = pdfium.PdfDocument(data)
    chunks: list[str] = []
    try:
        for index in range(min(len(doc), OCR_MAX_PAGES)):
            page = doc[index]
            image = page.render(scale=300 / 72).to_pil()
            try:
                chunks.append(pytesseract.image_to_string(image, lang=languages))
            except pytesseract.TesseractError:
                chunks.append(pytesseract.image_to_string(image))
    finally:
        doc.close()
    return _normalize_text("\n\n".join(chunks))


def extract_docx(data: bytes) -> ExtractionResult:
    import docx
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise CVFileError("corrupted") from exc

    lines: list[str] = []

    def walk_table(table: Table) -> None:
        for row in table.rows:
            seen_cells: set[int] = set()
            cells: list[str] = []
            for cell in row.cells:
                if id(cell._tc) in seen_cells:  # merged cells repeat
                    continue
                seen_cells.add(id(cell._tc))
                cell_text = "\n".join(p.text for p in cell.paragraphs if p.text.strip())
                if cell_text:
                    cells.append(cell_text)
                for nested in cell.tables:
                    walk_table(nested)
            if cells:
                lines.append(" | ".join(cells) if all("\n" not in c for c in cells) else "\n".join(cells))

    # Headers often hold the contact block.
    for section in document.sections:
        for p in section.header.paragraphs:
            if p.text.strip():
                lines.append(p.text)
        for t in section.header.tables:
            walk_table(t)

    for block in document.iter_inner_content():
        if isinstance(block, Paragraph):
            if block.text.strip():
                lines.append(block.text)
        elif isinstance(block, Table):
            walk_table(block)

    for section in document.sections:
        for p in section.footer.paragraphs:
            if p.text.strip():
                lines.append(p.text)

    links = [
        rel.target_ref
        for rel in document.part.rels.values()
        if rel.reltype == RT.HYPERLINK and rel.is_external
    ]
    text = _normalize_text("\n".join(lines))
    if len(text) < MIN_TEXT_CHARS // 2:
        raise CVFileError("no_text")
    return ExtractionResult(text=text, method="text", page_count=0, links=_dedupe(links))


def extract_text(data: bytes, kind: str, ocr_languages: str = "eng") -> ExtractionResult:
    if kind == "pdf":
        return extract_pdf(data, ocr_languages)
    if kind == "docx":
        return extract_docx(data)
    raise CVFileError("unsupported_format")
