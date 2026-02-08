"""Cron-based heartbeat scheduler — runs periodic LLM tasks."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from croniter import croniter

from mesh.config import AgentConfig, HeartbeatTask
from mesh.ollama import OllamaClient
from mesh.peer import PeerClient
from mesh.discovery import Discovery

log = logging.getLogger(__name__)


class HeartbeatScheduler:
    def __init__(
        self,
        tasks: list[HeartbeatTask],
        agent: AgentConfig,
        ollama: OllamaClient,
        peer_client: PeerClient,
        discovery: Discovery,
    ):
        self.tasks = tasks
        self.agent = agent
        self.ollama = ollama
        self.peer_client = peer_client
        self.discovery = discovery
        self._running = False
        self._task_handles: list[asyncio.Task] = []

    async def start(self):
        self._running = True
        for ht in self.tasks:
            handle = asyncio.create_task(self._run_loop(ht))
            self._task_handles.append(handle)
        log.info("Heartbeat scheduler started with %d tasks", len(self.tasks))

    async def stop(self):
        self._running = False
        for h in self._task_handles:
            h.cancel()
        await asyncio.gather(*self._task_handles, return_exceptions=True)

    async def _run_loop(self, ht: HeartbeatTask):
        cron = croniter(ht.schedule, datetime.now(timezone.utc))
        while self._running:
            next_dt = cron.get_next(datetime)
            now = datetime.now(timezone.utc)
            delay = (next_dt - now).total_seconds()
            if delay > 0:
                await asyncio.sleep(delay)

            if not self._running:
                break

            log.info("Heartbeat firing: %s", ht.name)
            try:
                reply = await self.ollama.chat(
                    model=self.agent.model,
                    messages=[{"role": "user", "content": ht.prompt}],
                    system=self.agent.system_prompt(),
                )
                log.info("Heartbeat [%s] result: %s", ht.name, reply[:200])

                if ht.broadcast:
                    await self._broadcast(ht.name, reply)

            except Exception:
                log.exception("Heartbeat task %s failed", ht.name)

    async def _broadcast(self, task_name: str, message: str):
        for peer in self.discovery.peers.values():
            try:
                await self.peer_client.chat(
                    peer,
                    f"[Broadcast from heartbeat:{task_name}]\n{message}",
                    self.agent.name,
                )
            except Exception:
                log.warning("Failed to broadcast to %s", peer.name)
