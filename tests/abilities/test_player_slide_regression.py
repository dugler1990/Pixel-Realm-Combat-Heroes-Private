"""Regression: old slide control flow must not return to Player.py."""

from pathlib import Path


PLAYER_PATH = Path(__file__).resolve().parents[2] / "Code" / "Player.py"
FORBIDDEN = (
    "move_slide",
    "'slide' in self.status",
    "slide_end_time",
    "maintain_slide_status",
    "create_evasion",
    "ChargedLeapSlamAbility",
    "leap_slam",
    "_resolve_landing_aoe",
    "_launch(",
)


def test_player_has_no_legacy_slide_or_leap_control_flow():
    source = PLAYER_PATH.read_text(encoding="utf-8")
    for token in FORBIDDEN:
        assert token not in source, f"ability control flow leaked into Player.py: {token!r}"
