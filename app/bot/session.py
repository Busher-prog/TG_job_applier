"""aiohttp session for aiogram that respects standard proxy / CA environment variables.

aiogram's default session ignores HTTPS_PROXY and uses only certifi's CA bundle.
Servers behind a corporate proxy (TLS inspection) need both, so this session:
* passes ``trust_env=True`` to aiohttp (HTTPS_PROXY / NO_PROXY are honoured);
* adds the CA file from SSL_CERT_FILE or REQUESTS_CA_BUNDLE, if set, to the trust store.
"""

from __future__ import annotations

import os
import ssl

import certifi
from aiogram import __version__
from aiogram.client.session.aiohttp import AiohttpSession
from aiohttp import ClientSession, TCPConnector
from aiohttp.hdrs import USER_AGENT
from aiohttp.http import SERVER_SOFTWARE


def build_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=certifi.where())
    extra = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if extra and os.path.isfile(extra):
        context.load_verify_locations(cafile=extra)
    return context


class EnvAwareAiohttpSession(AiohttpSession):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._connector_init["ssl"] = build_ssl_context()

    async def create_session(self) -> ClientSession:
        if self._should_reset_connector:
            await self.close()
        if self._session is None or self._session.closed:
            self._session = ClientSession(
                connector=TCPConnector(**self._connector_init),
                headers={USER_AGENT: f"{SERVER_SOFTWARE} aiogram/{__version__}"},
                trust_env=True,
            )
            self._should_reset_connector = False
        return self._session
