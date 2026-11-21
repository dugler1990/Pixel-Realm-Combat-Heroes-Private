"""Wind whisper panel variant — non-blocking ConversationPanel."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import pygame

pygame.init()
pygame.display.set_mode((800, 600))

from dialogue.session import DialogueSession
from ice_fog.whisper import load_wind_whispers, whisper_event, whisper_panel_snapshot


class _Keys:
    def __init__(self, pressed):
        self.pressed = set(pressed)

    def is_key_just_pressed(self, key):
        return key in self.pressed


class _Backend:
    def __init__(self):
        self.rects = []
        self.blits = []

    def get_size(self):
        return (800, 600)

    def draw_rect(self, color, rect, width=0):
        self.rects.append(pygame.Rect(rect))

    def blit(self, surface, dest, **kwargs):
        self.blits.append(dest)

    def invalidate_texture(self, surface):
        return None


def test_whisper_event_from_wind_json():
    table = load_wind_whispers()
    event = whisper_event("fog_enter", table)
    assert event is not None
    assert event.kind == "whisper"
    assert event.speaker_name == "Wind"
    assert "white" in event.text.lower() or "walk" in event.text.lower()
    snap = whisper_panel_snapshot(event)
    assert snap["kind"] == "whisper"
    assert snap["choices"] == []
    assert snap["revealed"] is True


def test_push_whisper_does_not_block_or_start_runner():
    session = DialogueSession()
    assert session.push_whisper_line("fog_enter", now_ms=1000)
    assert session.whisper_active()
    assert not session.runner.active
    assert not session.blocks_gameplay()
    backend = _Backend()
    session.draw(backend, SimpleNamespace(x=0, y=0))
    assert backend.rects  # panel drew


def test_whisper_expires():
    session = DialogueSession()
    session.push_whisper("A soft gust…", now_ms=0, line_id="tmp")
    session.update_world(
        SimpleNamespace(rect=pygame.Rect(0, 0, 1, 1)),
        [],
        [],
        now_ms=4000,
        dt=0.016,
    )
    assert not session.whisper_active()


def test_whisper_space_dismisses_without_runner():
    session = DialogueSession()
    session.push_whisper("…", now_ms=0, line_id="tmp2")
    handled = session.handle_input(_Keys({pygame.K_SPACE}))
    assert handled
    assert not session.whisper_active()


def test_whisper_cooldown_on_line_id():
    session = DialogueSession()
    assert session.push_whisper("one", now_ms=0, line_id="fog_enter", cooldown_ms=5000)
    assert not session.push_whisper("two", now_ms=100, line_id="fog_enter", cooldown_ms=5000)
