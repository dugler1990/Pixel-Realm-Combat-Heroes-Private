"""find_hits: every candidate whose pixels touch the attack, each once, in candidate order."""
import sys
from pathlib import Path

import pygame

CODE_DIR = Path(__file__).resolve().parents[1] / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import hit_core  # noqa: E402


class _Body:
    """What find_hits reads from a sprite: a rect and a mask the size of the rect."""

    def __init__(self, x, y, solid=True):
        self.rect = pygame.Rect(x, y, 10, 10)
        self.mask = pygame.mask.Mask((10, 10), fill=solid)


def test_find_hits_keeps_each_touching_body_once_in_candidate_order():
    attack = hit_core.Shape(pygame.mask.Mask((20, 20), fill=True), 0, 0)
    near, also_near, owner = _Body(5, 5), _Body(12, 0), _Body(0, 0)
    far = _Body(100, 100)
    hollow = _Body(5, 5, solid=False)  # rect overlaps but no pixels: the mask test drops it
    candidates = [far, near, hollow, object(), owner, near, also_near]
    assert hit_core.find_hits(attack, candidates, exclude=(owner,)) == [near, also_near]
