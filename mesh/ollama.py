"""Ollama HTTP API client — uses /api/chat exclusively."""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)


class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=120.0)

    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        system: str | None = None,
    ) -> str:
        msgs = list(messages)
        if system:
            msgs = [{"role": "system", "content": system}] + msgs

        resp = await self._client.post(
            "/api/chat", json={"model": model, "messages": msgs, "stream": False}
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    async def list_models(self) -> list[str]:
        resp = await self._client.get("/api/tags")
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]

    async def healthy(self) -> bool:
        try:
            resp = await self._client.get("/api/tags")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def close(self):
        await self._client.aclose()
