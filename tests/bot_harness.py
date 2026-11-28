"""Drive the real Dispatcher with a fake Telegram API (records outgoing calls)."""

from __future__ import annotations

import io
import itertools
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import (
    CallbackQuery,
    Chat,
    Document,
    InlineKeyboardMarkup,
    Message,
    Update,
    User,
)

from app.bot.factory import create_bot

_ids = itertools.count(1000)

MESSAGE_METHODS = {"SendMessage", "EditMessageText", "SendDocument", "SendPhoto", "SendMediaGroup"}


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []

    async def close(self) -> None:  # pragma: no cover
        pass

    async def make_request(self, bot: Bot, method: TelegramMethod[TelegramType], timeout: int | None = None) -> Any:
        self.calls.append(method)
        name = type(method).__name__
        if name in MESSAGE_METHODS:
            chat_id = getattr(method, "chat_id", None) or 1
            payload = {
                "message_id": getattr(method, "message_id", None) or next(_ids),
                "date": int(datetime.now(UTC).timestamp()),
                "chat": {"id": chat_id, "type": "private"},
                "text": getattr(method, "text", None),
            }
            if name == "SendMediaGroup":
                return [Message.model_validate(payload, context={"bot": bot})]
            return Message.model_validate(payload, context={"bot": bot})
        if name == "GetMe":
            return User(id=bot.id, is_bot=True, first_name="Copilot", username="copilot_bot")
        return True

    async def stream_content(self, *args: Any, **kwargs: Any):  # pragma: no cover
        raise NotImplementedError


class BotHarness:
    def __init__(self, dp: Any, user_id: int = 777, language_code: str = "ru") -> None:
        self.session = FakeSession()
        self.bot = create_bot()
        self.bot.session = self.session
        self.dp = dp
        self.user = User(id=user_id, is_bot=False, first_name="Test", language_code=language_code)
        self.chat = Chat(id=user_id, type="private")
        self.files: dict[str, bytes] = {}

        async def fake_download(file: Any, destination: io.BytesIO | None = None, **_: Any) -> io.BytesIO:
            data = self.files[file.file_id]
            destination = destination or io.BytesIO()
            destination.write(data)
            return destination

        self.bot.download = fake_download  # type: ignore[method-assign]

    def _message(self, **fields: Any) -> Message:
        return Message(
            message_id=next(_ids), date=datetime.now(UTC), chat=self.chat, from_user=self.user, **fields
        )

    async def send(self, text: str) -> list[TelegramMethod[Any]]:
        return await self._feed(Update(update_id=next(_ids), message=self._message(text=text)))

    async def send_document(self, data: bytes, filename: str, mime: str) -> list[TelegramMethod[Any]]:
        file_id = f"file{next(_ids)}"
        self.files[file_id] = data
        doc = Document(file_id=file_id, file_unique_id=file_id, file_name=filename, mime_type=mime,
                       file_size=len(data))
        return await self._feed(Update(update_id=next(_ids), message=self._message(document=doc)))

    async def click(self, callback_data: str) -> list[TelegramMethod[Any]]:
        msg = self._message(text="previous")
        call = CallbackQuery(id=str(next(_ids)), from_user=self.user, chat_instance="ci",
                             message=msg, data=callback_data)
        return await self._feed(Update(update_id=next(_ids), callback_query=call))

    async def _feed(self, update: Update) -> list[TelegramMethod[Any]]:
        start = len(self.session.calls)
        bound = Update.model_validate(update.model_dump(exclude_none=True), context={"bot": self.bot})
        await self.dp.feed_update(self.bot, bound)
        return self.session.calls[start:]

    @staticmethod
    def texts(calls: list[TelegramMethod[Any]]) -> list[str]:
        out = []
        for c in calls:
            value = getattr(c, "text", None) or getattr(c, "caption", None)
            if value:
                out.append(value)
        return out

    @staticmethod
    def documents(calls: list[TelegramMethod[Any]]) -> list[Any]:
        return [c.document for c in calls if type(c).__name__ == "SendDocument"]  # type: ignore[attr-defined]

    @staticmethod
    def last_markup(calls: list[TelegramMethod[Any]]) -> InlineKeyboardMarkup | None:
        for c in reversed(calls):
            markup = getattr(c, "reply_markup", None)
            if isinstance(markup, InlineKeyboardMarkup):
                return markup
        return None

    @classmethod
    def buttons(cls, calls: list[TelegramMethod[Any]]) -> dict[str, str]:
        markup = cls.last_markup(calls)
        if markup is None:
            return {}
        return {b.text: b.callback_data or b.url or "" for row in markup.inline_keyboard for b in row}

    @staticmethod
    def alerts(calls: list[TelegramMethod[Any]]) -> list[str]:
        return [c.text for c in calls if type(c).__name__ == "AnswerCallbackQuery" and c.text]  # type: ignore[attr-defined]
