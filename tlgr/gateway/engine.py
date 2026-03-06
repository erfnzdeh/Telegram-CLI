"""Gateway engine — generic event-driven pipeline.

Replaces AutoforwardJob and AutoreplyJob with a single class that runs:
    event -> filters -> processors -> actions
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from telethon import events

from tlgr.actions import get_action
from tlgr.core.client import ClientWrapper
from tlgr.filters.compose import evaluate
from tlgr.gateway.config import GatewayConfig, ActionConfig
from tlgr.gateway.event import Event
from tlgr.jobs.base import BaseJob
from tlgr.processors import ProcessorChain

log = logging.getLogger("tlgr.gateway")


class _GatewayJobConfig:
    """Minimal shim so Gateway can sit on top of BaseJob.

    BaseJob expects a config object with ``.name``, ``.type``, and
    ``.enabled`` attributes.
    """
    def __init__(self, gw: GatewayConfig) -> None:
        self.name = gw.name
        self.type = "gateway"
        self.enabled = gw.enabled
        self.account = gw.account


class Gateway(BaseJob):
    """Generic pipeline job: filters -> processors -> actions."""

    def __init__(
        self,
        config: GatewayConfig,
        client: ClientWrapper,
        webhook=None,
    ) -> None:
        self._gw = config
        shim = _GatewayJobConfig(config)
        super().__init__(shim, client, webhook)  # type: ignore[arg-type]
        self._handler = None
        self._stats: dict[str, int] = {"matched": 0, "skipped": 0, "errors": 0}

    async def setup(self) -> None:
        log.info(
            "[%s] filters=%s actions=%s",
            self.name,
            "yes" if self._gw.filters else "none",
            [a.name for a in self._gw.actions],
        )

    async def run(self) -> None:
        @self.client.client.on(events.NewMessage(incoming=True))
        async def handler(tg_event):
            await self._handle(tg_event)

        self._handler = handler

        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            raise

    async def teardown(self) -> None:
        if self._handler:
            self.client.client.remove_event_handler(self._handler)
            self._handler = None
        log.info(
            "[%s] stopped — matched=%d skipped=%d errors=%d",
            self.name,
            self._stats["matched"],
            self._stats["skipped"],
            self._stats["errors"],
        )

    async def _handle(self, tg_event) -> None:
        envelope = Event(
            source="telegram",
            raw=tg_event,
            account=self._gw.account,
        )

        ok, reason = evaluate(self._gw.filters, envelope)
        if not ok:
            self._stats["skipped"] += 1
            return

        self._stats["matched"] += 1

        for action_cfg in self._gw.actions:
            await self._run_action(action_cfg, envelope)

    async def _run_action(self, ac: ActionConfig, envelope: Event) -> None:
        if ac.filters:
            ok, reason = evaluate(ac.filters, envelope)
            if not ok:
                return

        func = get_action(ac.name)
        if func is None:
            log.warning("[%s] unknown action: %s", self.name, ac.name)
            self._stats["errors"] += 1
            return

        chain = ac.processors or self._gw.processors

        try:
            await func(envelope, ac.config, self.client, chain)
        except Exception as e:
            log.warning("[%s] action '%s' failed: %s", self.name, ac.name, e)
            self._stats["errors"] += 1
