"""Interactive REPL for talking to mesh peers."""

from __future__ import annotations

import asyncio
import logging
import sys

from mesh.discovery import Discovery
from mesh.peer import PeerClient

log = logging.getLogger(__name__)

HELP_TEXT = """\
Commands:
  chat <message>             Broadcast to all peers; leader aggregates replies
  dm <peer> <message>        Send a direct chat message to one peer
  list                       Show discovered peers
  info <peer>                Get detailed info from a peer
  exec <peer> <lang> <code>  Execute code on a peer (lang: bash|python)
  health <peer>              Check a peer's health
  help                       Show this help
  quit                       Exit the REPL
"""


class MeshREPL:
    def __init__(self, discovery: Discovery, client: PeerClient):
        self.discovery = discovery
        self.client = client
        self._stop = asyncio.Event()

    def _resolve_peer(self, name: str):
        """Find a peer by exact name or prefix match."""
        if name in self.discovery.peers:
            return self.discovery.peers[name]
        # prefix match
        matches = [p for n, p in self.discovery.peers.items() if n.startswith(name)]
        if len(matches) == 1:
            return matches[0]
        return None

    async def _broadcast_chat(self, message: str):
        """Send message to all peers, then have the leader aggregate responses."""
        peers = list(self.discovery.peers.values())
        if not peers:
            print("No peers discovered yet.")
            return

        from_name = self.discovery.node_name
        print(f"Broadcasting to {len(peers)} peer(s)...")

        # Fan out to all peers concurrently
        async def _ask(peer):
            try:
                reply = await self.client.chat(peer, message, from_name)
                return (peer.name, reply)
            except Exception as e:
                log.warning("Peer %s failed: %s", peer.name, e)
                return (peer.name, None)

        results = await asyncio.gather(*[_ask(p) for p in peers])
        responses = {name: reply for name, reply in results if reply is not None}

        if not responses:
            print("All peers failed to respond.")
            return

        if len(responses) == 1:
            name, reply = next(iter(responses.items()))
            print(f"  [{name}]: {reply}")
            return

        # Leader election: lexicographically first responding peer
        leader_name = sorted(responses.keys())[0]
        leader = self._resolve_peer(leader_name)

        # Show individual responses
        for name, reply in sorted(responses.items()):
            tag = " (leader)" if name == leader_name else ""
            print(f"  [{name}{tag}]: {reply}")

        # Ask leader to aggregate
        resp_block = "\n".join(f"[{n}]: {r}" for n, r in sorted(responses.items()))
        agg_prompt = (
            f'Multiple peers answered the following question:\n'
            f'"{message}"\n\n'
            f'Their responses:\n{resp_block}\n\n'
            f'Synthesize these into a single, most accurate response.'
        )

        print(f"\nAggregating via leader ({leader_name})...")
        try:
            final = await self.client.chat(leader, agg_prompt, from_name)
            print(f"\n  >> {final}")
        except Exception as e:
            print(f"Leader aggregation failed: {e}")

    async def _handle_line(self, line: str):
        parts = line.strip().split(None, 1)
        if not parts:
            return
        cmd = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        if cmd == "quit":
            self._stop.set()
            return

        if cmd == "help":
            print(HELP_TEXT)
            return

        if cmd == "list":
            peers = self.discovery.peers
            if not peers:
                print("No peers discovered yet.")
            else:
                for p in peers.values():
                    skills = ", ".join(p.skills) if p.skills else "none"
                    print(f"  {p.name:20s}  {p.host}:{p.port}  model={p.model}  skills=[{skills}]")
            return

        if cmd == "info":
            peer = self._resolve_peer(rest.strip())
            if not peer:
                print(f"Unknown peer: {rest.strip()}")
                return
            try:
                data = await self.client.info(peer)
                for k, v in data.items():
                    print(f"  {k}: {v}")
            except Exception as e:
                print(f"Error: {e}")
            return

        if cmd == "chat":
            if not rest.strip():
                print("Usage: chat <message>")
                return
            await self._broadcast_chat(rest.strip())
            return

        if cmd == "dm":
            parts2 = rest.split(None, 1)
            if len(parts2) < 2:
                print("Usage: dm <peer> <message>")
                return
            peer_name, message = parts2
            peer = self._resolve_peer(peer_name)
            if not peer:
                print(f"Unknown peer: {peer_name}")
                return
            try:
                print(f"Sending to {peer.name}...")
                reply = await self.client.chat(peer, message, self.discovery.node_name)
                print(f"  {peer.name}: {reply}")
            except Exception as e:
                print(f"Error: {e}")
            return

        if cmd == "exec":
            parts2 = rest.split(None, 2)
            if len(parts2) < 3:
                print("Usage: exec <peer> <lang> <code>")
                return
            peer_name, lang, code = parts2
            peer = self._resolve_peer(peer_name)
            if not peer:
                print(f"Unknown peer: {peer_name}")
                return
            if lang not in ("bash", "python"):
                print("lang must be 'bash' or 'python'")
                return
            try:
                result = await self.client.exec_on(peer, code, lang, self.discovery.node_name)
                print(f"  exit_code: {result['exit_code']}")
                print(f"  output: {result['output']}")
            except Exception as e:
                print(f"Error: {e}")
            return

        if cmd == "health":
            peer = self._resolve_peer(rest.strip())
            if not peer:
                print(f"Unknown peer: {rest.strip()}")
                return
            try:
                data = await self.client.health(peer)
                for k, v in data.items():
                    print(f"  {k}: {v}")
            except Exception as e:
                print(f"Error: {e}")
            return

        print(f"Unknown command: {cmd}  (type 'help' for usage)")

    async def run(self):
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str] = asyncio.Queue()

        def on_stdin():
            line = sys.stdin.readline()
            if not line:  # EOF / Ctrl-D
                loop.call_soon_threadsafe(self._stop.set)
                return
            loop.call_soon_threadsafe(queue.put_nowait, line)

        loop.add_reader(sys.stdin.fileno(), on_stdin)

        print("ollama-mesh REPL  (type 'help' for commands, 'quit' to exit)")
        print(f"Discovering peers as '{self.discovery.node_name}'...\n")
        sys.stdout.write("mesh> ")
        sys.stdout.flush()

        try:
            while not self._stop.is_set():
                try:
                    line = await asyncio.wait_for(queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                await self._handle_line(line)
                if not self._stop.is_set():
                    sys.stdout.write("mesh> ")
                    sys.stdout.flush()
        finally:
            loop.remove_reader(sys.stdin.fileno())
