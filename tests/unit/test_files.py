import io
import zipfile

import pytest

from app.services.cv.file_validation import CVFileError, validate_cv_file
from app.services.cv.text_extraction import extract_text

MAX = 10 * 1024 * 1024


def test_valid_pdf(sample_pdf: bytes) -> None:
    v = validate_cv_file(sample_pdf, "My CV.pdf", MAX)
    assert v.kind == "pdf" and v.safe_filename == "My CV.pdf" and len(v.sha256) == 64


def test_valid_docx(sample_docx: bytes) -> None:
    assert validate_cv_file(sample_docx, "cv.docx", MAX).kind == "docx"


@pytest.mark.parametrize(
    ("data", "name", "code"),
    [
        (b"", "cv.pdf", "empty_file"),
        (b"hello world", "cv.txt", "unsupported_format"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 100, "cv.doc", "legacy_doc"),
        (b"%PDF-1.4 garbage", "cv.pdf", "corrupted"),
        (b"PK\x03\x04garbage", "cv.docx", "corrupted"),
    ],
)
def test_invalid_files(data: bytes, name: str, code: str) -> None:
    with pytest.raises(CVFileError) as exc:
        validate_cv_file(data, name, MAX)
    assert exc.value.code == code


def test_too_large(sample_pdf: bytes) -> None:
    with pytest.raises(CVFileError) as exc:
        validate_cv_file(sample_pdf, "cv.pdf", 100)
    assert exc.value.code == "too_large"


def test_extension_mismatch(sample_pdf: bytes) -> None:
    with pytest.raises(CVFileError):
        validate_cv_file(sample_pdf, "cv.docx", MAX)


def test_zip_without_word_document() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hello.txt", "x")
    with pytest.raises(CVFileError) as exc:
        validate_cv_file(buf.getvalue(), "cv.docx", MAX)
    assert exc.value.code == "unsupported_format"


def test_zip_bomb_rejected(sample_docx: bytes) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(sample_docx)) as src, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            dst.writestr(item, src.read(item.filename))
        dst.writestr("word/media/bomb.bin", b"\0" * (70 * 1024 * 1024))
    with pytest.raises(CVFileError) as exc:
        validate_cv_file(buf.getvalue(), "cv.docx", MAX)
    assert exc.value.code == "too_large"


def test_extract_pdf(sample_pdf: bytes) -> None:
    result = extract_text(sample_pdf, "pdf")
    assert "Anna Berger" in result.text and "Bright Media GmbH" in result.text
    assert "Привет" not in result.text
    assert any("linkedin.com/in/anna-berger-example" in link for link in result.links)
    assert result.method == "text"


def test_extract_docx_includes_header_and_tables(sample_docx: bytes) -> None:
    result = extract_text(sample_docx, "docx")
    assert "oleh.k@example.org" in result.text
    assert "SAP" in result.text and "Excel" in result.text
    assert result.text.index("Oleh Kovalenko") < result.text.index("Berufserfahrung")


def test_cyrillic_pdf_text_extractable() -> None:
    from weasyprint import HTML

    html = "<p>" + "Іван Петренко — монтажер відео, досвід роботи з DaVinci Resolve. " * 5 + "</p>"
    pdf = HTML(string=html).write_pdf()
    assert "Іван Петренко" in extract_text(pdf, "pdf").text


def test_scanned_pdf_without_text_is_reported() -> None:
    from weasyprint import HTML

    pdf = HTML(string="<div style='width:100px;height:100px;background:#000'></div>").write_pdf()
    with pytest.raises(CVFileError) as exc:
        extract_text(pdf, "pdf")
    assert exc.value.code == "no_text"


@pytest.mark.skipif(not __import__("app.services.cv.text_extraction", fromlist=["x"]).ocr_available(),
                    reason="tesseract not installed")
def test_scanned_pdf_is_ocred(sample_pdf: bytes) -> None:
    import pypdfium2 as pdfium

    page = pdfium.PdfDocument(sample_pdf)[0]
    image = page.render(scale=2).to_pil().convert("RGB")
    buf = io.BytesIO()
    image.save(buf, format="PDF", resolution=144)
    scanned = buf.getvalue()
    result = extract_text(scanned, "pdf", "eng")
    assert result.method == "ocr"
    assert "Anna Berger" in result.text and "Bright Media" in result.text
