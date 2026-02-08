"""Main daemon — ties everything together."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path

from mesh.config import load_config
from mesh.discovery import Discovery
from mesh.heartbeat import HeartbeatScheduler
from mesh.ollama import OllamaClient
from mesh.peer import PeerClient, PeerServer
from mesh.repl import MeshREPL

log = logging.getLogger("mesh")


async def run(config_dir: Path, port: int, ollama_url: str):
    # Load config from markdown files
    agent, heartbeat_tasks, skills = load_config(config_dir)
    skill_names = [s.name for s in skills]

    log.info("Agent: %s (model=%s, skills=%s)", agent.name, agent.model, skill_names)
    log.info("Heartbeat tasks: %d", len(heartbeat_tasks))

    # Init components
    ollama = OllamaClient(base_url=ollama_url)
    discovery = Discovery(
        node_name=agent.name,
        port=port,
        model=agent.model,
        skills=skill_names,
    )
    peer_client = PeerClient()
    server = PeerServer(agent=agent, ollama=ollama, discovery=discovery, port=port)
    scheduler = HeartbeatScheduler(
        tasks=heartbeat_tasks,
        agent=agent,
        ollama=ollama,
        peer_client=peer_client,
        discovery=discovery,
    )

    # Start
    await server.start()
    await discovery.start()
    await scheduler.start()

    healthy = await ollama.healthy()
    log.info("Ollama connection: %s", "OK" if healthy else "UNREACHABLE (will retry on requests)")

    # Wait for shutdown signal
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    log.info("Mesh daemon running — press Ctrl+C to stop")
    await stop_event.wait()

    # Teardown
    log.info("Shutting down...")
    await scheduler.stop()
    await discovery.stop()
    await server.stop()
    await peer_client.close()
    await ollama.close()
    log.info("Goodbye.")


async def run_ui(config_dir: Path, ollama_url: str):
    """UI-only mode: discovery + REPL, no server or heartbeat."""
    agent, _, _ = load_config(config_dir)
    skill_names: list[str] = []

    discovery = Discovery(
        node_name=f"{agent.name}-ui",
        port=0,
        model=agent.model,
        skills=skill_names,
    )
    peer_client = PeerClient()

    await discovery.start()
    log.info("UI mode — discovering peers...")

    # Give discovery a moment to find peers
    await asyncio.sleep(1)

    repl = MeshREPL(discovery, peer_client)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    try:
        await repl.run()
    finally:
        log.info("Shutting down UI...")
        await discovery.stop()
        await peer_client.close()
        log.info("Goodbye.")


def main():
    parser = argparse.ArgumentParser(description="ollama-mesh daemon")
    parser.add_argument(
        "-c", "--config-dir",
        type=Path,
        default=Path.cwd(),
        help="Directory containing AGENT.md, HEARTBEAT.md, SKILLS.md (default: cwd)",
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=7331,
        help="Port for the peer HTTP server (default: 7331)",
    )
    parser.add_argument(
        "--ollama-url",
        default="http://localhost:11434",
        help="Ollama API base URL (default: http://localhost:11434)",
    )
    parser.add_argument(
        "-u", "--ui",
        action="store_true",
        help="Launch interactive REPL (client-only, no server)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)-12s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.ui:
        asyncio.run(run_ui(args.config_dir, args.ollama_url))
    else:
        asyncio.run(run(args.config_dir, args.port, args.ollama_url))


if __name__ == "__main__":
    main()
