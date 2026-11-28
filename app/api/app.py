"""FastAPI application: health, legal pages, webhooks, OAuth callbacks."""

from __future__ import annotations

from fastapi import FastAPI

from app.api import health, legal, webhooks


def create_app() -> FastAPI:
    app = FastAPI(title="AI Job Copilot API", docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(health.router)
    app.include_router(legal.router)
    app.include_router(webhooks.router)
    try:
        from app.api import oauth

        app.include_router(oauth.router)
    except ImportError:  # OAuth is added in Phase 4
        pass
    return app
