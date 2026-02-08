"""Ollama HTTP API client — auto-detects /api/chat vs /api/generate."""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)


class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=120.0)
        self._use_chat: bool | None = None  # None = not yet probed

    async def _probe_endpoints(self):
        """Check which generation endpoint is available."""
        try:
            resp = await self._client.post(
                "/api/chat",
                json={"model": "probe", "messages": [], "stream": False},
            )
            # 404 means the route doesn't exist; anything else (400, model-not-found, etc.)
            # means the endpoint IS there, just our probe payload was bad.
            self._use_chat = resp.status_code != 404
        except httpx.HTTPError:
            self._use_chat = False

        endpoint = "/api/chat" if self._use_chat else "/api/generate"
        log.info("Ollama endpoint detected: %s", endpoint)

    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        system: str | None = None,
    ) -> str:
        if self._use_chat is None:
            await self._probe_endpoints()

        if self._use_chat:
            return await self._chat_api(model, messages, system)
        return await self._generate_api(model, messages, system)

    async def _chat_api(
        self, model: str, messages: list[dict[str, str]], system: str | None
    ) -> str:
        msgs = list(messages)
        if system:
            msgs = [{"role": "system", "content": system}] + msgs

        resp = await self._client.post(
            "/api/chat", json={"model": model, "messages": msgs, "stream": False}
        )
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
