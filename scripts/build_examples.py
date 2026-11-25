"""Render the fictional example CVs in examples/*.json to PDF, DOCX and PNG previews.

    python -m scripts.build_examples
"""

from __future__ import annotations

import json
from pathlib import Path

from app.schemas.resume import ResumeDocument
from app.services.cv.renderer import render_docx, render_pdf, render_preview_png

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def main() -> None:
    for path in sorted(EXAMPLES.glob("*.json")):
        doc = ResumeDocument.model_validate(json.loads(path.read_text(encoding="utf-8")))
        result = render_pdf(doc)
        if result.missing:
            raise SystemExit(f"{path.name}: missing in PDF: {result.missing}")
        (EXAMPLES / f"{path.stem}.pdf").write_bytes(result.pdf)
        (EXAMPLES / f"{path.stem}.docx").write_bytes(render_docx(doc))
        (EXAMPLES / f"{path.stem}.png").write_bytes(render_preview_png(result.pdf, scale=1.2))
        print(f"{path.stem}: {result.page_count} page(s)")


if __name__ == "__main__":
    main()
