"""Concept image → 3D → rig → N-direction sprite frames → Graphics/Monsters/<name>.

See PLAN.md for the design and README.md for how to run it.
"""
from pathlib import Path


def bpy_python(here: Path) -> Path:
    """Return the bpy venv interpreter on POSIX or Windows."""
    posix = here / ".venv-bpy" / "bin" / "python"
    if posix.exists():
        return posix
    windows = here / ".venv-bpy" / "Scripts" / "python.exe"
    if windows.exists():
        return windows
    raise SystemExit(
        "bpy environment missing — follow tools/boss_sprite_pipeline/README.md "
        "to create tools/boss_sprite_pipeline/.venv-bpy"
    )
