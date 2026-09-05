"""Reaching into the game's own modules from the pipeline.

The polygon maths and the render loop live in ``Code/``, and the pipeline has to use them
rather than reimplement them -- a second copy of the door plane is how the art and the
collision drift apart, and a second copy of the draw order is how a preview stops predicting
what the game will show.

``Code/`` is not a package, so it is reached by a ``sys.path`` insert, the way the tests
already do it. Imports are lazy and behind functions: ``building_geometry`` is pure and safe
to pull in anywhere, but ``Settings`` (and therefore anything importing it) calls
``os.chdir`` at module scope, so importing the game eagerly would move the working directory
out from under whatever else the process was doing.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

CODE = Path(__file__).resolve().parents[3] / "Code"


def _ensure_path() -> None:
    if str(CODE) not in sys.path:
        sys.path.insert(0, str(CODE))


def building_geometry():
    """The pure polygon module. No pygame, no Settings, no chdir."""
    _ensure_path()
    import building_geometry  # noqa: PLC0415

    return building_geometry


class chdir_guard:
    """Restore the working directory after importing anything that pulls in Settings.

    Settings.py chdirs to Code/ at import so the game can load its art by relative path.
    That is load-bearing for the game and hostile to everything else: a pipeline command
    that imports the engine and then writes a relative output path would put the file
    somewhere the caller never asked for.
    """

    def __enter__(self):
        self._cwd = os.getcwd()
        return self

    def __exit__(self, *exc):
        os.chdir(self._cwd)
        return False
