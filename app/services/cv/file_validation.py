"""Validation of uploaded CV files (format, size, structure, safety)."""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from pathlib import PurePath

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

MAX_DOCX_UNCOMPRESSED = 60 * 1024 * 1024
MAX_DOCX_ENTRIES = 3000
MAX_PDF_PAGES = 30


class CVFileError(ValueError):
    """User-facing validation failure. ``code`` maps to a localisation key."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(slots=True, frozen=True)
class ValidatedFile:
    kind: str  # "pdf" | "docx"
    mime_type: str
    sha256: str
    size: int
    safe_filename: str


def _safe_filename(name: str | None, kind: str) -> str:
    base = PurePath(name or f"cv.{kind}").name
    cleaned = "".join(c for c in base if c.isalnum() or c in "._- ()").strip() or f"cv.{kind}"
    if not cleaned.lower().endswith(f".{kind}"):
        cleaned = f"{cleaned}.{kind}"
    return cleaned[-120:]


def validate_cv_file(data: bytes, filename: str | None, max_bytes: int) -> ValidatedFile:
    if not data:
        raise CVFileError("empty_file")
    if len(data) > max_bytes:
        raise CVFileError("too_large")

    ext = PurePath(filename or "").suffix.lower()
    if ext == ".doc" or data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise CVFileError("legacy_doc")

    if data[:1024].find(b"%PDF-") != -1:
        kind = "pdf"
        _check_pdf(data)
    elif data[:4] == b"PK\x03\x04":
        kind = "docx"
        _check_docx(data)
    else:
        raise CVFileError("unsupported_format")

    if ext and ext not in (".pdf", ".docx"):
        raise CVFileError("unsupported_format")
    if ext and ext != f".{kind}":
        # Extension lies about content — reject rather than guess.
        raise CVFileError("unsupported_format")

    return ValidatedFile(
        kind=kind,
        mime_type=PDF_MIME if kind == "pdf" else DOCX_MIME,
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        safe_filename=_safe_filename(filename, kind),
    )


def _check_pdf(data: bytes) -> None:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            # Many CVs are "encrypted" with an empty owner password only.
            try:
                if not reader.decrypt(""):
                    raise CVFileError("encrypted")
            except Exception as exc:
                raise CVFileError("encrypted") from exc
        pages = len(reader.pages)
    except CVFileError:
        raise
    except (PdfReadError, ValueError, KeyError, OSError) as exc:
        raise CVFileError("corrupted") from exc
    if pages == 0:
        raise CVFileError("corrupted")
    if pages > MAX_PDF_PAGES:
        raise CVFileError("too_many_pages")


def _check_docx(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_DOCX_ENTRIES:
                raise CVFileError("corrupted")
            names = {i.filename for i in infos}
            if "word/document.xml" not in names or "[Content_Types].xml" not in names:
                raise CVFileError("unsupported_format")
            if any(i.flag_bits & 0x1 for i in infos):
                raise CVFileError("encrypted")
            if sum(i.file_size for i in infos) > MAX_DOCX_UNCOMPRESSED:
                raise CVFileError("too_large")  # zip bomb protection
            if any(i.filename.startswith("/") or ".." in i.filename.split("/") for i in infos):
                raise CVFileError("corrupted")
    except zipfile.BadZipFile as exc:
        raise CVFileError("corrupted") from exc
