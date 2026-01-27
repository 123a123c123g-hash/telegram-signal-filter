from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections import deque
from dataclasses import dataclass

from telethon import TelegramClient, events
from telethon.errors import AuthRestartError, SessionPasswordNeededError

from filters import format_notification, parse_distance
from screenshotter import GraphScreenshotter, config_from_dict, extract_graph_url


SESSION_PATH = os.path.join(os.path.dirname(__file__), "session")


@dataclass
class ChatInfo:
    title: str
    username: str | None
    chat_id: int
    is_channel: bool
    is_group: bool

    def display_name(self) -> str:
        username_part = f"@{self.username}" if self.username else "no-username"
        return f"{self.title} ({username_part}) [{self.chat_id}]"


class TGClient:
    def __init__(self, api_id: int, api_hash: str, logger: logging.Logger, screenshot_config: dict) -> None:
        self._api_id = api_id
        self._api_hash = api_hash
        self._logger = logger
        base_dir = os.path.dirname(__file__)
        self._screenshotter = GraphScreenshotter(config_from_dict(screenshot_config, base_dir), logger)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._client: TelegramClient | None = None
        self._connected = False
        self._monitoring = False
        self._handler = None
        self._recent_ids: deque[tuple[int | None, int]] = deque()
        self._recent_set: set[tuple[int | None, int]] = set()
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def connect(self) -> None:
        if self._connected:
            return
        self._run(self._connect())
        self._connected = True

    async def _connect(self) -> None:
        self._client = TelegramClient(SESSION_PATH, self._api_id, self._api_hash)
        await self._client.connect()

    def is_connected(self) -> bool:
        return self._connected

    def request_code(self, phone: str) -> None:
        self._run(self._request_code(phone))

    async def _request_code(self, phone: str) -> None:
        if self._client is None:
            raise RuntimeError("Client not connected")
        if not self._client.is_connected():
            await self._client.connect()
        for attempt in range(2):
            try:
                await self._client.send_code_request(phone)
                return
            except AuthRestartError:
                self._logger.warning("AuthRestartError on send_code_request, retrying (attempt %s)", attempt + 1)
                await self._client.disconnect()
                await self._client.connect()
        raise AuthRestartError("AuthRestartError: Restart the authorization process")

    def login(self, phone: str, code: str, password: str | None, send_code: bool = True) -> None:
        self._run(self._login(phone, code, password, send_code))

    async def _login(self, phone: str, code: str, password: str | None, send_code: bool) -> None:
        if self._client is None:
            raise RuntimeError("Client not connected")
        if await self._client.is_user_authorized():
            return
        if send_code:
            await self._request_code(phone)
        try:
            await self._client.sign_in(phone=phone, code=code)
        except SessionPasswordNeededError:
            if not password:
                raise
            await self._client.sign_in(password=password)

    def load_chats(self) -> list[ChatInfo]:
        return self._run(self._load_chats())

    async def _load_chats(self) -> list[ChatInfo]:
        if self._client is None:
            raise RuntimeError("Client not connected")
        dialogs = await self._client.get_dialogs(limit=500)
        items: list[ChatInfo] = []
        for d in dialogs:
            entity = d.entity
            title = getattr(entity, "title", None) or getattr(entity, "first_name", "") or "Unknown"
            username = getattr(entity, "username", None)
            chat_id = getattr(entity, "id", None)
            if chat_id is None:
                continue
            is_channel = bool(getattr(entity, "broadcast", False))
            is_group = bool(getattr(entity, "megagroup", False)) or entity.__class__.__name__ == "Chat"
            items.append(
                ChatInfo(
                    title=title,
                    username=username,
                    chat_id=int(chat_id),
                    is_channel=is_channel,
                    is_group=is_group,
                )
            )
        return items

    def start_monitoring(
        self,
        *,
        source: ChatInfo,
        notify: ChatInfo,
        min_distance: float,
        ignore_forwarded: bool,
        on_signal,
    ) -> None:
        if self._monitoring:
            return
        self._monitoring = True
        self._run(
            self._start_monitoring(
                source=source,
                notify=notify,
                min_distance=min_distance,
                ignore_forwarded=ignore_forwarded,
                on_signal=on_signal,
            )
        )

    async def _start_monitoring(
        self,
        *,
        source: ChatInfo,
        notify: ChatInfo,
        min_distance: float,
        ignore_forwarded: bool,
        on_signal,
    ) -> None:
        if self._client is None:
            raise RuntimeError("Client not connected")

        self._recent_ids.clear()
        self._recent_set.clear()

        async def handler(event: events.NewMessage.Event) -> None:
            if not self._monitoring:
                return
            msg = event.message
            if msg is None or msg.message is None:
                return
            if ignore_forwarded and msg.fwd_from is not None:
                return
            msg_id = msg.id
            chat_id = event.chat_id
            msg_key = (chat_id, msg_id)
            if msg_key in self._recent_set:
                return

            parsed = parse_distance(msg.message)
            if parsed is None or abs(parsed.distance) < min_distance:
                return

            if len(self._recent_ids) >= 200:
                old = self._recent_ids.popleft()
                self._recent_set.discard(old)
            self._recent_ids.append(msg_key)
            self._recent_set.add(msg_key)

            link = None
            source_title = source.title
            try:
                chat = await event.get_chat()
                username = getattr(chat, "username", None)
                source_title = getattr(chat, "title", None) or getattr(chat, "first_name", "") or source.title
                if username:
                    link = f"https://t.me/{username}/{msg_id}"
            except Exception:
                link = None

            notify_text = format_notification(
                min_distance=min_distance,
                coin=parsed.coin,
                distance=parsed.distance,
                source_title=source_title,
                chat_id=chat_id if chat_id is not None else source.chat_id,
                timestamp=msg.date,
                link=link,
                original_text=msg.message,
                msg_id=msg_id,
            )

            screenshot_path = None
            raw_text = msg.raw_text or msg.message
            url = extract_graph_url(raw_text)
            if url:
                screenshot_path = await self._screenshotter.take_screenshot(url)
            else:
                self._logger.info("No graph URL found for msg_id=%s", msg_id)

            if screenshot_path:
                await self._client.send_file(notify.chat_id, screenshot_path, caption=notify_text)
            else:
                await self._client.send_message(notify.chat_id, notify_text)

            self._logger.info("Signal sent chat_id=%s msg_id=%s", chat_id, msg_id)
            if on_signal:
                on_signal(parsed.distance)

        self._handler = self._client.add_event_handler(
            handler, events.NewMessage(chats=source.chat_id)
        )

    def stop_monitoring(self) -> None:
        if not self._monitoring:
            return
        self._monitoring = False
        self._run(self._stop_monitoring())

    async def _stop_monitoring(self) -> None:
        if self._client is None:
            return
        if self._handler is not None:
            self._client.remove_event_handler(self._handler)
            self._handler = None

    def disconnect(self) -> None:
        if not self._connected:
            return
        self._run(self._disconnect())
        self._connected = False

    async def _disconnect(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
