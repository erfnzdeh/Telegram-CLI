"""Autoforward background job — real-time message forwarding."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from telethon import events, errors
from telethon.tl.types import Message

from tlgr.core.client import ClientWrapper
from tlgr.core.config import JobConfig, DestinationConfig
from tlgr.filters import (
    MessageFilter,
    is_forwardable,
    detect_message_type,
    create_filter_from_job_config,
)
from tlgr.transforms import TransformChain, create_chain_from_config
from tlgr.jobs.base import BaseJob

log = logging.getLogger("tlgr.jobs.autoforward")


class AutoforwardJob(BaseJob):
    def __init__(self, config: JobConfig, client: ClientWrapper, webhook=None):
        super().__init__(config, client, webhook)
        self._source_id: int = 0
        self._dest_configs: list[tuple[int, DestinationConfig | None]] = []
        self._route_filter: MessageFilter | None = None
        self._route_transforms: TransformChain | None = None
        self._handler = None
        self._stats = {"forwarded": 0, "skipped": 0, "failed": 0}

    async def setup(self) -> None:
        self._source_id = await self.client.resolve_chat(self.config.source)
        for dest in self.config.destinations:
            if isinstance(dest, str):
                did = await self.client.resolve_chat(dest)
                self._dest_configs.append((did, None))
            else:
                did = await self.client.resolve_chat(dest.chat)
                self._dest_configs.append((did, dest))
        self._route_filter = create_filter_from_job_config(self.config.filters)
        if self.config.transforms:
            self._route_transforms = create_chain_from_config(self.config.transforms)
        log.info(
            "[%s] source=%s destinations=%s",
            self.name,
            self._source_id,
            [d[0] for d in self._dest_configs],
        )

    async def run(self) -> None:
        @self.client.client.on(events.NewMessage(chats=[self._source_id]))
        async def handler(event):
            await self._handle_message(event.message)

        self._handler = handler
        # Keep running until cancelled
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            raise

    async def teardown(self) -> None:
        if self._handler:
            self.client.client.remove_event_handler(self._handler)
            self._handler = None
        log.info(
            "[%s] stopped — forwarded=%d skipped=%d failed=%d",
            self.name,
            self._stats["forwarded"],
            self._stats["skipped"],
            self._stats["failed"],
        )

    async def _handle_message(self, message: Message) -> None:
        ok, reason = is_forwardable(message)
        if not ok:
            self._stats["skipped"] += 1
            return

        if self._route_filter:
            ok, reason = self._route_filter.matches(message)
            if not ok:
                self._stats["skipped"] += 1
                return

        success = 0
        for dest_id, dest_cfg in self._dest_configs:
            try:
                # Destination-level filter
                if dest_cfg and dest_cfg.filters:
                    df = create_filter_from_job_config(dest_cfg.filters)
                    if df:
                        ok, _ = df.matches(message)
                        if not ok:
                            continue

                # Determine transforms: destination overrides route
                tc = None
                if dest_cfg and dest_cfg.transforms:
                    tc = create_chain_from_config(dest_cfg.transforms)
                elif self._route_transforms:
                    tc = self._route_transforms

                if tc:
                    await self._send_transformed(message, dest_id, tc)
                else:
                    await self.client.client.forward_messages(
                        dest_id,
                        message,
                        drop_author=self.config.drop_author,
                    )
                success += 1
            except errors.ChatWriteForbiddenError:
                log.warning("[%s] Cannot write to %s", self.name, dest_id)
            except errors.ChannelPrivateError:
                log.warning("[%s] Channel %s is private", self.name, dest_id)
            except Exception as e:
                log.error("[%s] Forward to %s failed: %s", self.name, dest_id, e)

            if len(self._dest_configs) > 1:
                await asyncio.sleep(0.3)

        if success > 0:
            self._stats["forwarded"] += 1
            if self.config.delete_after and success == len(self._dest_configs):
                try:
                    await self.client.client.delete_messages(
                        self._source_id, [message.id], revoke=True
                    )
                except Exception as e:
                    log.warning("[%s] Delete failed: %s", self.name, e)
            if self.webhook:
                text_preview = (message.text or "")[:100]
                await self.webhook.push(
                    "autoforward",
                    {
                        "job": self.name,
                        "msg_id": message.id,
                        "source": self._source_id,
                        "preview": text_preview,
                    },
                    account=self.config.account,
                )
        else:
            self._stats["failed"] += 1

    async def _send_transformed(
        self,
        message: Message,
        dest_id: int,
        chain: TransformChain,
    ) -> None:
        original = message.text or message.message or ""
        transformed = chain.apply(original) if original else ""
        if message.media:
            await self.client.client.send_file(
                dest_id, message.media, caption=transformed
            )
        else:
            await self.client.client.send_message(dest_id, transformed)
