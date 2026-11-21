"""Where the data lives. ANIM_DATA_ROOT, else OUTFIT_DATA_ROOT, else the Boss worktree beside this one."""
from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PIPE = REPO / "tools" / "boss_sprite_pipeline"


def data_root() -> Path:
    for key in ("ANIM_DATA_ROOT", "OUTFIT_DATA_ROOT"):
        if os.environ.get(key):
            return Path(os.environ[key])
    if (REPO / "generated" / "bosses").is_dir():
        return REPO
    boss = REPO.parent / "Pixel-Realm-Combat-Heroes-Boss"
    if (boss / "generated" / "bosses").is_dir():
        return boss
    return REPO


def generated() -> Path:
    return data_root() / "generated"


def characters() -> Path:
    # under bosses/ because generated/bosses/** is git-ignored in every worktree (allowlist only
    # state.json / manifest.json / bones.json); a new top-level generated/ folder would show untracked
    return generated() / "bosses" / "characters"


def character_dir(cid: str) -> Path:
    return characters() / cid


def rel(path: Path) -> str:
    """generated-relative posix path, or absolute when outside generated/."""
    path = Path(path).resolve()
    try:
        return path.relative_to(generated().resolve()).as_posix()
    except ValueError:
        return str(path)


def resolve(p: str) -> Path:
    p = str(p).replace("\\", "/")
    q = Path(p)
    return q if q.is_absolute() else generated() / p


def bpy_python() -> Path:
    env = os.environ.get("ANIM_BPY")
    if env:
        return Path(env)
    for c in (PIPE / ".venv-bpy" / "Scripts" / "python.exe",
              REPO.parent / "Pixel-Realm-Combat-Heroes-Boss" / "tools" / "boss_sprite_pipeline" / ".venv-bpy"
              / "Scripts" / "python.exe"):
        if c.is_file():
            return c
    raise FileNotFoundError("no .venv-bpy python (set ANIM_BPY)")
