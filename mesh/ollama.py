"""Ollama HTTP API client — defaults to /api/chat, falls back to /api/generate."""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)


class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=120.0)
        self._use_generate = False  # only set True if /api/chat returns 404

    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        system: str | None = None,
    ) -> str:
        if self._use_generate:
            return await self._generate_api(model, messages, system)

        # Try /api/chat first; fall back to /api/generate on 404
        msgs = list(messages)
        if system:
            msgs = [{"role": "system", "content": system}] + msgs

        resp = await self._client.post(
            "/api/chat", json={"model": model, "messages": msgs, "stream": False}
        )
        if resp.status_code == 404:
            log.info("Ollama /api/chat not available, falling back to /api/generate")
            self._use_generate = True
            return await self._generate_api(model, messages, system)

        resp.raise_for_status()
        return resp.json()["message"]["content"]

    async def _generate_api(
        self, model: str, messages: list[dict[str, str]], system: str | None
    ) -> str:
        # Flatten messages into a single prompt for /api/generate
        parts: list[str] = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "user":
                parts.append(f"User: {content}")
            elif role == "assistant":
                parts.append(f"Assistant: {content}")
        prompt = "\n\n".join(parts) + "\n\nAssistant:"

        payload: dict = {"model": model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system

        resp = await self._client.post("/api/generate", json=payload)
        resp.raise_for_status()
        return resp.json()["response"]

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
