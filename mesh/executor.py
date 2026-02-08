"""Sandboxed bash/python code execution."""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass

TIMEOUT_SECONDS = 30
MAX_OUTPUT_BYTES = 64 * 1024  # 64 KiB


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def output(self) -> str:
        return self.stdout if self.ok else f"STDERR:\n{self.stderr}\nSTDOUT:\n{self.stdout}"


async def run_bash(code: str, timeout: float = TIMEOUT_SECONDS) -> ExecResult:
    proc = await asyncio.create_subprocess_shell(
        code,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return ExecResult(exit_code=-1, stdout="", stderr=f"Timed out after {timeout}s")

    return ExecResult(
        exit_code=proc.returncode or 0,
        stdout=stdout.decode(errors="replace")[:MAX_OUTPUT_BYTES],
        stderr=stderr.decode(errors="replace")[:MAX_OUTPUT_BYTES],
    )


async def run_python(code: str, timeout: float = TIMEOUT_SECONDS) -> ExecResult:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        f.flush()
        return await run_bash(f"python3 {f.name}", timeout=timeout)
