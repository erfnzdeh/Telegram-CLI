"""Auto-reply background job — static reply to incoming messages."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from telethon import events

from tlgr.core.client import ClientWrapper
from tlgr.core.config import JobConfig
from tlgr.filters import create_filter_from_job_config
from tlgr.jobs.base import BaseJob

log = logging.getLogger("tlgr.jobs.autoreply")


class AutoreplyJob(BaseJob):
    def __init__(self, config: JobConfig, client: ClientWrapper, webhook=None):
        super().__init__(config, client, webhook)
        self._chat_ids: list[int] | None = None
        self._filter = None
        self._handler = None
        self._stats = {"replied": 0, "skipped": 0}

    async def setup(self) -> None:
        if self.config.chats and self.config.chats != ["*"]:
            self._chat_ids = []
            for c in self.config.chats:
                cid = await self.client.resolve_chat(c)
                self._chat_ids.append(cid)
        self._filter = create_filter_from_job_config(self.config.filters)
        log.info("[%s] reply='%s' chats=%s", self.name, self.config.reply[:50], self._chat_ids or "all")

    async def run(self) -> None:
        handler_kwargs: dict[str, Any] = {"incoming": True}
        if self._chat_ids:
            handler_kwargs["chats"] = self._chat_ids

        @self.client.client.on(events.NewMessage(**handler_kwargs))
        async def handler(event):
            if self._filter:
                ok, _ = self._filter.matches(event.message)
                if not ok:
                    self._stats["skipped"] += 1
                    return
            try:
                await event.reply(self.config.reply)
                self._stats["replied"] += 1
                log.debug("[%s] Replied to msg %d in %s", self.name, event.message.id, event.chat_id)
            except Exception as e:
                log.warning("[%s] Reply failed: %s", self.name, e)

        self._handler = handler
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            raise

    async def teardown(self) -> None:
        if self._handler:
            self.client.client.remove_event_handler(self._handler)
            self._handler = None
        log.info("[%s] stopped — replied=%d skipped=%d", self.name, self._stats["replied"], self._stats["skipped"])
