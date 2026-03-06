"""Outbound webhook pusher — POSTs Telegram events to an external URL."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiohttp

from tlgr.core.config import WebhookConfig

log = logging.getLogger("tlgr.webhook")


class WebhookPusher:
    def __init__(self, config: WebhookConfig):
        self.config = config
        self._session: aiohttp.ClientSession | None = None
        self._resolved_chat_ids: set[int] = set()

    async def start(self) -> None:
        if not self.config.enabled:
            return
        self._session = aiohttp.ClientSession()
        log.info("Webhook pusher started → %s", self.config.url)

    async def stop(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    def set_resolved_chats(self, chat_ids: set[int]) -> None:
        """Set resolved numeric chat IDs for filtering."""
        self._resolved_chat_ids = chat_ids

    def should_push(self, event_type: str, chat_id: int | None = None) -> bool:
        if not self.config.enabled:
            return False
        if event_type not in self.config.events:
            return False
        if self.config.filters.chats and chat_id is not None:
            if chat_id not in self._resolved_chat_ids:
                return False
        return True

    async def push(
        self,
        event_type: str,
        data: dict[str, Any],
        account: str = "",
    ) -> None:
        if not self._session:
            return

        payload = {
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "account": account,
            "data": data,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.token}",
        }

        retry = self.config.retry
        max_attempts = retry.max_attempts if retry.enabled else 1

        for attempt in range(max_attempts):
            try:
                async with self._session.post(
                    self.config.url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status < 400:
                        log.debug("Webhook push OK (%s): %s", resp.status, event_type)
                        return
                    body = await resp.text()
                    log.warning(
                        "Webhook push failed (%s): %s",
                        resp.status,
                        body[:200],
                    )
            except Exception as e:
                log.warning("Webhook push error (attempt %d): %s", attempt + 1, e)

            if attempt < max_attempts - 1:
                wait = retry.backoff_base ** attempt
                log.debug("Retrying webhook in %ds", wait)
                await asyncio.sleep(wait)

        log.error("Webhook push exhausted retries for event %s", event_type)
