"""Privacy Policy and Terms of Service pages."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import SUPPORTED_LANGUAGES, get_settings

router = APIRouter()
_env = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent.parent / "templates" / "legal"),
    autoescape=select_autoescape(["html"]),
)


def _render(doc: str, lang: str) -> HTMLResponse:
    lang = lang if lang in SUPPORTED_LANGUAGES else "en"
    try:
        template = _env.get_template(f"{doc}_{lang}.html")
    except Exception:
        template = _env.get_template(f"{doc}_en.html")
    s = get_settings()
    return HTMLResponse(template.render(version=s.privacy_policy_version, support=s.support_contact,
                                        base_url=s.app_base_url))


@router.get("/privacy", response_class=HTMLResponse)
async def privacy(lang: str = Query("en", max_length=5)) -> HTMLResponse:
    return _render("privacy", lang)


@router.get("/terms", response_class=HTMLResponse)
async def terms(lang: str = Query("en", max_length=5)) -> HTMLResponse:
    return _render("terms", lang)
