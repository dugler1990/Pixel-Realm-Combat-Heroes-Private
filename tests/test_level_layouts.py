"""One level table: the client, its Level4 and the server resolve every level the same way."""

import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT / "Server", REPO_ROOT / "Code"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import level_layouts  # noqa: E402


def test_server_and_client_resolve_every_level_number_to_the_same_path():
    import headless_level
    import Level4_tmxdev
    import Main2
    import server

    assert Main2.LEVEL_TO_LAYOUT is level_layouts.LEVEL_TO_LAYOUT
    assert headless_level.LEVEL_TO_LAYOUT is level_layouts.LEVEL_TO_LAYOUT
    assert Level4_tmxdev.LAYOUT_TO_LEVEL is level_layouts.LAYOUT_TO_LEVEL
    assert server.MP_LEVEL_NUMBER == Main2.MP_LEVEL_NUMBER == level_layouts.MP_LEVEL_NUMBER


def test_the_table_is_complete_and_round_trips():
    table = level_layouts.LEVEL_TO_LAYOUT
    assert {11, 12} <= set(table)  # the levels the server's old copy was missing
    for number, path in table.items():
        assert level_layouts.LAYOUT_TO_LEVEL[path] == number
        assert (REPO_ROOT / "Code" / path).resolve().is_dir(), path
    assert level_layouts.MP_LEVEL_NUMBER in table
    assert level_layouts.DEFAULT_LAYOUT in level_layouts.LAYOUT_TO_LEVEL
