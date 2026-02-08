"""HTTP server for peer-to-peer communication and client for talking to peers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiohttp import web
import httpx

if TYPE_CHECKING:
    from mesh.discovery import Discovery, PeerInfo
    from mesh.ollama import OllamaClient
    from mesh.config import AgentConfig
    from mesh.executor import ExecResult

log = logging.getLogger(__name__)


class PeerServer:
    """HTTP server that other mesh nodes talk to."""

    def __init__(
        self,
        agent: AgentConfig,
        ollama: OllamaClient,
        discovery: Discovery,
        port: int,
    ):
        self.agent = agent
        self.ollama = ollama
        self.discovery = discovery
        self.port = port
        self._app = web.Application()
        self._app.router.add_get("/health", self._handle_health)
        self._app.router.add_get("/info", self._handle_info)
        self._app.router.add_post("/chat", self._handle_chat)
        self._app.router.add_post("/exec", self._handle_exec)
        self._runner: web.AppRunner | None = None

    async def start(self):
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self.port)
        await site.start()
        log.info("Peer server listening on :%d", self.port)

    async def stop(self):
        if self._runner:
            await self._runner.cleanup()

    # --- Handlers ---

    async def _handle_health(self, request: web.Request) -> web.Response:
        ollama_ok = await self.ollama.healthy()
        return web.json_response({
            "status": "ok" if ollama_ok else "degraded",
            "node": self.agent.name,
            "ollama": ollama_ok,
        })

    async def _handle_info(self, request: web.Request) -> web.Response:
        return web.json_response({
            "name": self.agent.name,
            "model": self.agent.model,
            "role": self.agent.role,
            "peers": [
                {"name": p.name, "host": p.host, "port": p.port, "model": p.model, "skills": p.skills}
                for p in self.discovery.peers.values()
            ],
        })

    async def _handle_chat(self, request: web.Request) -> web.Response:
        body = await request.json()
        message = body.get("message", "")
        from_peer = body.get("from", "unknown")

        log.info("Chat from %s: %s", from_peer, message[:120])

        messages = [{"role": "user", "content": f"[From peer: {from_peer}]\n{message}"}]
        reply = await self.ollama.chat(
            model=self.agent.model,
            messages=messages,
            system=self.agent.system_prompt(),
        )

        return web.json_response({"reply": reply, "from": self.agent.name})

    async def _handle_exec(self, request: web.Request) -> web.Response:
        from mesh.executor import run_bash, run_python

        body = await request.json()
        lang = body.get("lang", "bash")
        code = body.get("code", "")
        from_peer = body.get("from", "unknown")

        log.info("Exec request (%s) from %s: %s", lang, from_peer, code[:120])

        if lang == "python":
            result: ExecResult = await run_python(code)
        else:
            result = await run_bash(code)

        return web.json_response({
            "exit_code": result.exit_code,
            "output": result.output,
            "from": self.agent.name,
        })


class PeerClient:
    """Client for sending requests to other mesh peers."""

    def __init__(self):
        self._client = httpx.AsyncClient(timeout=60.0)

    async def chat(self, peer: PeerInfo, message: str, from_name: str) -> str:
        resp = await self._client.post(
            f"{peer.base_url}/chat",
            json={"message": message, "from": from_name},
        )
        resp.raise_for_status()
        return resp.json()["reply"]

    async def exec_on(self, peer: PeerInfo, code: str, lang: str, from_name: str) -> dict:
        resp = await self._client.post(
            f"{peer.base_url}/exec",
            json={"code": code, "lang": lang, "from": from_name},
        )
        resp.raise_for_status()
        return resp.json()

    async def health(self, peer: PeerInfo) -> dict:
        resp = await self._client.get(f"{peer.base_url}/health")
        resp.raise_for_status()
        return resp.json()

    async def info(self, peer: PeerInfo) -> dict:
        resp = await self._client.get(f"{peer.base_url}/info")
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self._client.aclose()
