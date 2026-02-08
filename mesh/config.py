"""Parse AGENT.md, HEARTBEAT.md, and SKILLS.md into structured config."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentConfig:
    name: str = "mesh-node"
    model: str = "deepseek-v3.2:cloud"
    role: str = "general-purpose assistant"
    persona: str = ""
    rules: list[str] = field(default_factory=list)
    context: str = ""

    def system_prompt(self) -> str:
        rules_block = "\n".join(f"- {r}" for r in self.rules)
        return f"""{self.persona}

Rules:
{rules_block}

Context:
{self.context}""".strip()


@dataclass
class HeartbeatTask:
    name: str
    schedule: str
    prompt: str
    broadcast: bool = False


@dataclass
class Skill:
    name: str
    description: str
    tags: list[str] = field(default_factory=list)


def _extract_field(block: str, field_name: str) -> str:
    """Extract a **field**: value line from a markdown block."""
    m = re.search(
        rf"\*\*{field_name}\*\*:\s*(.+)", block, re.IGNORECASE
    )
    return m.group(1).strip() if m else ""


def parse_agent(path: Path) -> AgentConfig:
    text = path.read_text()
    cfg = AgentConfig()

    cfg.name = _extract_field(text, "name") or cfg.name
    cfg.model = _extract_field(text, "model") or cfg.model
    cfg.role = _extract_field(text, "role") or cfg.role

    # Persona section
    m = re.search(r"## Persona\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if m:
        cfg.persona = m.group(1).strip()

    # Rules section — grab bullet points
    m = re.search(r"## Rules\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if m:
        cfg.rules = [
            line.lstrip("- ").strip()
            for line in m.group(1).strip().splitlines()
            if line.strip().startswith("-")
        ]

    # Context section
    m = re.search(r"## Context\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if m:
        cfg.context = m.group(1).strip()

    return cfg


def parse_heartbeat(path: Path) -> list[HeartbeatTask]:
    text = path.read_text()
    tasks: list[HeartbeatTask] = []

    # Split on h3 headings
    chunks = re.split(r"^### (.+)$", text, flags=re.MULTILINE)
    # chunks = [preamble, name1, body1, name2, body2, ...]
    for i in range(1, len(chunks), 2):
        name = chunks[i].strip()
        body = chunks[i + 1] if i + 1 < len(chunks) else ""
        schedule = _extract_field(body, "schedule")
        prompt = _extract_field(body, "prompt")
        broadcast_raw = _extract_field(body, "broadcast").lower()
        broadcast = broadcast_raw in ("true", "yes", "1")
        if schedule and prompt:
            tasks.append(HeartbeatTask(name=name, schedule=schedule, prompt=prompt, broadcast=broadcast))

    return tasks


def parse_skills(path: Path) -> list[Skill]:
    text = path.read_text()
    skills: list[Skill] = []

    chunks = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
    for i in range(1, len(chunks), 2):
        name = chunks[i].strip()
        body = chunks[i + 1] if i + 1 < len(chunks) else ""
        description = _extract_field(body, "description")
        tags_raw = _extract_field(body, "tags")
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
        if description:
            skills.append(Skill(name=name, description=description, tags=tags))

    return skills


def load_config(config_dir: Path) -> tuple[AgentConfig, list[HeartbeatTask], list[Skill]]:
    agent = parse_agent(config_dir / "AGENT.md")
    heartbeat = parse_heartbeat(config_dir / "HEARTBEAT.md")
    skills = parse_skills(config_dir / "SKILLS.md")
    return agent, heartbeat, skills
