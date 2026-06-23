"""Held abilities must not suppress locomotion during attack."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[2]
CODE_DIR = REPO_ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from abilities.held import HeldMagicAbility, HeldWeaponAbility  # noqa: E402


def test_weapon_and_magic_do_not_suppress_locomotion():
    player = SimpleNamespace(attacking=True)
    weapon = HeldWeaponAbility(lambda: None, None)
    magic = HeldMagicAbility(lambda *a, **k: None)
    assert weapon.suppresses_locomotion(player) is False
    assert magic.suppresses_locomotion(player) is False
