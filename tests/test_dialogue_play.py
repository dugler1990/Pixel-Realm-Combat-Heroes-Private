"""Open the black benchmark room and talk to an Eskimo.

Not part of a normal pytest run. It stays on screen until the window is closed.

    pytest tests/test_dialogue_play.py
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "Code"


def test_dialogue_in_the_benchmark_room(request):
    invoked = request.config.invocation_params.args
    if not any("test_dialogue_play.py" in str(arg) for arg in invoked):
        pytest.skip("opens the game window; run pytest tests/test_dialogue_play.py")
    print(
        "\nBenchmark room: black, wall ring, Eskimo to your right.\n"
        "Walk up. Space talks. Up/Down choose. Esc leaves.\n"
        "Close the window when you are done.\n",
        flush=True,
    )
    env = os.environ.copy()
    for key in ("SDL_VIDEODRIVER", "SDL_AUDIODRIVER"):
        env.pop(key, None)
    env["PRCH_RTS_VALIDATION_ENABLED"] = "1"
    env["PRCH_RTS_VALIDATION_VISIBLE"] = "1"
    env["PRCH_RTS_VALIDATION_FAST"] = "0"
    env["PRCH_RTS_VALIDATION_SCENARIOS"] = "dialogue_talk"
    env["PRCH_RTS_VALIDATION_LAYOUT_DIR"] = "../levels/benchmark"
    env["PRCH_RTS_VALIDATION_OUTPUT"] = str(REPO_ROOT / "logs" / "dialogue_play.json")
    env["PRCH_RTS_VALIDATION_MAX_SECONDS"] = "30"
    env["PRCH_RTS_VALIDATION_HOLD_SECONDS"] = "0"
    proc = subprocess.run([sys.executable, "Main2.py"], cwd=str(CODE_DIR), env=env)
    assert proc.returncode == 0
