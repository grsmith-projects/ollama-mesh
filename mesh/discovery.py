"""mDNS service registration and peer discovery using zeroconf."""

from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import dataclass, field

from zeroconf import IPVersion, ServiceStateChange, Zeroconf
from zeroconf.asyncio import (
    AsyncServiceBrowser,
    AsyncServiceInfo,
    AsyncZeroconf,
)

log = logging.getLogger(__name__)

SERVICE_TYPE = "_ollama-mesh._tcp.local."


@dataclass
class PeerInfo:
    name: str
    host: str
    port: int
    model: str = ""
    skills: list[str] = field(default_factory=list)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


class Discovery:
    """Handles mDNS registration of this node and discovery of peers."""

    def __init__(self, node_name: str, port: int, model: str, skills: list[str]):
        self.node_name = node_name
        self.port = port
        self.model = model
        self.skills = skills

        self._azc: AsyncZeroconf | None = None
        self._browser: AsyncServiceBrowser | None = None
        self._info: AsyncServiceInfo | None = None
        self.peers: dict[str, PeerInfo] = {}

    async def start(self):
        self._azc = AsyncZeroconf(ip_version=IPVersion.V4Only)

        # Register ourselves
        local_ip = self._get_local_ip()
        props = {
            b"model": self.model.encode(),
            b"skills": ",".join(self.skills).encode(),
        }
        self._info = AsyncServiceInfo(
            SERVICE_TYPE,
            f"{self.node_name}.{SERVICE_TYPE}",
            addresses=[socket.inet_aton(local_ip)],
            port=self.port,
            properties=props,
            server=f"{self.node_name}.local.",
        )
        await self._azc.async_register_service(self._info, allow_name_change=True)
        registered_name = self._info.name.replace(f".{SERVICE_TYPE}", "")
        if registered_name != self.node_name:
            log.warning("Name conflict — registered as %s instead of %s", registered_name, self.node_name)
            self.node_name = registered_name
        log.info("Registered mDNS service %s on %s:%d", self.node_name, local_ip, self.port)

        # Browse for peers
        self._browser = AsyncServiceBrowser(
            self._azc.zeroconf,
            SERVICE_TYPE,
            handlers=[self._on_state_change],
        )

    def _on_state_change(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ):
        asyncio.ensure_future(self._handle_state_change(zeroconf, service_type, name, state_change))

    async def _handle_state_change(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ):
        if state_change == ServiceStateChange.Removed:
            short = name.replace(f".{SERVICE_TYPE}", "")
            self.peers.pop(short, None)
            log.info("Peer removed: %s", short)
            return

        info = AsyncServiceInfo(service_type, name)
        await info.async_request(zeroconf, 3000)

        if not info.addresses:
            return

        short = name.replace(f".{SERVICE_TYPE}", "")
        if short == self.node_name:
            return  # skip self

        host = socket.inet_ntoa(info.addresses[0])
        props = {k.decode(): v.decode() for k, v in info.properties.items()} if info.properties else {}
        skills = [s.strip() for s in props.get("skills", "").split(",") if s.strip()]

        peer = PeerInfo(
            name=short,
            host=host,
            port=info.port or 0,
            model=props.get("model", ""),
            skills=skills,
        )
        self.peers[short] = peer
        log.info("Peer discovered: %s at %s:%d (model=%s, skills=%s)", short, host, peer.port, peer.model, skills)

    async def stop(self):
        if self._browser:
            # zeroconf >= 0.140 uses async_cancel(); older versions use cancel()
            if hasattr(self._browser, "async_cancel"):
                await self._browser.async_cancel()
            elif hasattr(self._browser, "cancel"):
                self._browser.cancel()
        if self._info and self._azc:
            await self._azc.async_unregister_service(self._info)
        if self._azc:
            await self._azc.async_close()

    @staticmethod
    def _get_local_ip() -> str:
        """Best-effort local IP that's reachable on the LAN."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"
        finally:
            s.close()
