"""Wall thickness: asked, not invented.

The chamber is the footprint minus its walls, and something has to say how thick those are.
Every way of deciding that in code is a guess wearing a formula: a constant cannot fit both a
pyramid and a hut, and a fraction of the bounding box is the same constant with a percent
sign. It is a judgement about a picture, so it is put to something that can see the picture.

Asked through the Claude Code CLI in print mode, not the Messages API. The API bills
separately from the subscription this project is already worked on; `claude -p` does not. Same
shape as `sam_local.py`: a subprocess and a parsed result, which is also why neither needs a
key managed in this tree.

Asked once per building and cached into the spec, for the reason the spec exists at all --
"a plan can be traced, emitted and rendered in separate sessions against identical geometry".
A number that changed between runs would move the chamber under an already-traced plan.

There is deliberately no fallback. A guessed thickness is not a degraded answer, it is a wrong
chamber written into `interior.json` and trusted by every step after it. If the question cannot
be asked, that is an error and the run stops.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

TILE = 150

# The range outside which a reply is not a wall but a mistake. Not clamped into range --
# an answer that lands outside these is a signal that the question or the crop was wrong.
MIN_WALL = 8
MAX_WALL_FRACTION = 0.25   # of the building's shorter side

# Where the CLI lives when it is not on PATH. The VS Code extension ships its own build, and
# on this machine that is the only copy -- there is no node, so no npm-installed `claude`.
EXTENSION_GLOB = ".vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude.exe"


class WallThicknessError(RuntimeError):
    pass


def claude_cli() -> Path:
    """The Claude Code binary. PATH first, then the VS Code extension's bundled copy."""
    override = os.environ.get("CLAUDE_CLI")
    if override:
        if not Path(override).exists():
            raise WallThicknessError(f"CLAUDE_CLI points at {override}, which does not exist")
        return Path(override)

    found = shutil.which("claude")
    if found:
        return Path(found)

    matches = sorted(Path.home().glob(EXTENSION_GLOB))
    if matches:
        return matches[-1]                       # newest version installed
    raise WallThicknessError(
        "cannot find the Claude Code CLI. It is on PATH as `claude`, or bundled in the VS "
        "Code extension; set CLAUDE_CLI to its path if it lives somewhere else.")


def _question(crop_path: Path, size, intent: str = "") -> str:
    inside = f" It will be a {intent.strip()}." if intent.strip() else ""
    return (
        f"Read the image at {Path(crop_path).resolve()}\n\n"
        f"It is the exterior art of one building on a top-down game map, cropped to its own "
        f"bounding box: {size[0]} x {size[1]} pixels. One player character is {TILE} pixels "
        f"tall, so that is the scale.{inside}\n\n"
        f"The interior is about to be painted inside this silhouette, and the walls have to be "
        f"reserved first. Looking at the masonry in the image, how thick is this building's "
        f"outer wall, in pixels of this image?\n\n"
        f"Answer with a single integer and nothing else. No units, no explanation."
    )


def _cache_path(crop_path: Path) -> Path:
    return Path(crop_path).with_name(Path(crop_path).stem + "_wall.json")


def _request(crop_path: Path, size, intent: str) -> dict:
    """What was asked. A different crop or a different intent is a different question."""
    return {"crop": str(Path(crop_path).resolve()), "size": list(size),
            "intent": intent.strip()}


def cached(crop_path: Path, size, intent: str):
    """The previous answer to this exact question, or None."""
    path = _cache_path(crop_path)
    if not path.exists():
        return None
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if stored.get("request") != _request(crop_path, size, intent):
        return None
    return stored.get("wall")


def wall_thickness(crop_path: Path, size, *, intent: str = "", timeout: int = 300,
                   refresh: bool = False) -> int:
    """Pixels of wall between the silhouette edge and the chamber. Raises rather than guess.

    Cached per crop. Not only to save the call: the model gives a different number run to run
    -- 200 px one time and 300 the next for the same pyramid -- and the wall decides the
    chamber, so an uncached answer means the interior's shape moves under a plan that was
    already traced against it. The cache is what makes the geometry reproducible.
    """
    crop_path = Path(crop_path)
    if not crop_path.exists():
        raise WallThicknessError(f"no crop at {crop_path}")

    if not refresh:
        stored = cached(crop_path, size, intent)
        if stored:
            print(f"  wall thickness: {stored}px ({stored / TILE:.2f} tiles) -- from the last "
                  f"run, pass --rescan to ask again")
            return int(stored)

    command = [
        str(claude_cli()),
        "-p", _question(crop_path, size, intent),
        "--allowed-tools", "Read",           # pre-approved, so nothing prompts and it cannot hang
        "--output-format", "text",
    ]
    print(f"  asking how thick the walls are in {crop_path.name} ...", flush=True)
    try:
        finished = subprocess.run(command, timeout=timeout, capture_output=True, text=True)
    except subprocess.TimeoutExpired as exc:
        raise WallThicknessError(
            f"the wall-thickness question timed out after {timeout}s") from exc
    if finished.returncode != 0:
        raise WallThicknessError(
            f"claude -p failed ({finished.returncode}):\n{finished.stdout}\n{finished.stderr}")

    text = (finished.stdout or "").strip()
    found = re.search(r"\d+", text)
    if not found:
        raise WallThicknessError(f"no number in the reply: {text[:200]!r}")

    thickness = int(found.group())
    ceiling = max(1, min(size)) * MAX_WALL_FRACTION
    if not MIN_WALL <= thickness <= ceiling:
        raise WallThicknessError(
            f"{thickness}px is not a wall for a {size[0]}x{size[1]} building "
            f"(expected {MIN_WALL}-{ceiling:.0f}px). The crop or the question is wrong; "
            f"pass a sane value yourself rather than letting this through.")

    print(f"  wall thickness: {thickness}px ({thickness / TILE:.2f} tiles)")
    try:
        _cache_path(crop_path).write_text(
            json.dumps({"request": _request(crop_path, size, intent), "wall": thickness},
                       indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass                                    # a cache that cannot be written is fine
    return thickness
