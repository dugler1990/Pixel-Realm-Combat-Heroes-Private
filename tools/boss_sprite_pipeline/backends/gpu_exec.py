"""Run a ``gpu_box/<tool>_cli.py`` wrapper locally or on ``gpu_host``.

All paths are repo-relative on both machines (the repo is checked out at
``remote_root`` on the box), so the same argv works either side. Remote mode
rsyncs the stage's input files up, runs the wrapper over ssh in the tool's own
venv, and rsyncs the declared outputs back.
"""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path


class GpuExec:
    def __init__(self, repo_root: Path, gpu_host: str | None = None, remote_root: str | None = None):
        self.repo_root = repo_root.resolve()
        self.gpu_host = gpu_host or None
        self.remote_root = remote_root or "~/Pixel-Realm-Combat-Heroes-public"

    # -- helpers -----------------------------------------------------------
    def rel(self, path: Path) -> str:
        path = Path(path).resolve()
        try:
            return path.relative_to(self.repo_root).as_posix()
        except ValueError:
            raise SystemExit(f"{path} is outside the repo; GpuExec paths must be repo-relative") from None

    def tool_python(self, tool: str) -> str:
        return f"tools/boss_sprite_pipeline/gpu_box/vendor/{tool}/.venv/bin/python"

    # -- public --------------------------------------------------------------
    def run(self, tool: str, args: list[str], *, inputs: list[Path], outputs: list[Path]) -> None:
        cli = f"tools/boss_sprite_pipeline/gpu_box/{tool}_cli.py"
        argv = [self.tool_python(tool), cli, *args]
        if self.gpu_host is None:
            self._local(argv)
        else:
            self._remote(argv, inputs, outputs)
        missing = [p for p in outputs if not Path(p).exists()]
        if missing:
            raise SystemExit(f"{tool}: expected outputs missing: {missing}")

    # -- transports ------------------------------------------------------------
    def _local(self, argv: list[str]) -> None:
        print("  $", " ".join(shlex.quote(a) for a in argv), flush=True)
        subprocess.run(argv, cwd=self.repo_root, check=True)

    def _remote(self, argv: list[str], inputs: list[Path], outputs: list[Path]) -> None:
        host, root = self.gpu_host, self.remote_root
        for p in inputs:
            rel = self.rel(p)
            self._sh(["ssh", host, f"mkdir -p {shlex.quote(root)}/{shlex.quote(str(Path(rel).parent))}"])
            self._sh(["rsync", "-az", str(p), f"{host}:{root}/{rel}"])
        cmd = f"cd {shlex.quote(root)} && " + " ".join(shlex.quote(a) for a in argv)
        self._sh(["ssh", host, cmd])
        for p in outputs:
            rel = self.rel(p)
            Path(p).parent.mkdir(parents=True, exist_ok=True)
            self._sh(["rsync", "-az", f"{host}:{root}/{rel}", str(p)])

    @staticmethod
    def _sh(argv: list[str]) -> None:
        print("  $", " ".join(shlex.quote(a) for a in argv), flush=True)
        subprocess.run(argv, check=True)
