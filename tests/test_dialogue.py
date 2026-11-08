"""Dialogue runner, focus, barks, and the level Space hook. No windowed level."""

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
import pytest

pygame.init()
pygame.display.set_mode((800, 600))

from dialogue.barks import BarkDirector
from dialogue.commands import CommandDispatcher
from dialogue.flags import DialogueFlags
from dialogue.focus import nearest_focus
from dialogue.graph import load_graph
from dialogue.runner import DialogueRunner
from dialogue.session import DialogueSession
from dialogue.trade import category_of, make_item, resolve_image
from dialogue.voice import VoiceChannel
from game_settings import GameSettings
from SettingsMenu import SettingsMenu


class _Keys:
    def __init__(self, pressed):
        self.pressed = set(pressed)

    def is_key_just_pressed(self, key):
        return key in self.pressed


class _Voice:
    def __init__(self):
        self.calls = []

    def play(self, audio_key, enabled=True):
        self.calls.append(("play", audio_key, enabled))
        return bool(enabled and audio_key)

    def stop(self):
        self.calls.append(("stop", None, True))


class _Backend:
    def __init__(self):
        self.blits = []
        self.rects = []

    def get_size(self):
        return (800, 600)

    def draw_rect(self, color, rect, width=0):
        self.rects.append(pygame.Rect(rect))

    def blit(self, surface, dest, **kwargs):
        self.blits.append(getattr(surface, "get_size", lambda: None)())

    def invalidate_texture(self, surface):
        return None


def _line_graph():
    return load_graph(
        {
            "id": "t",
            "start": "hello",
            "nodes": {
                "hello": {
                    "speaker": "Eskimo",
                    "text": "Hello there friend",
                    "audio": "vo/hello.ogg",
                    "command": "set_flag:met=1",
                    "next": "ask",
                },
                "ask": {
                    "choices": [
                        {"text": "Work", "next": "job", "command": "offer_quest:ice_hunt", "require": "met"},
                        {"text": "Secret", "next": "end", "require": "not:met"},
                        {"text": "Bye", "next": "end"},
                    ]
                },
                "job": {"speaker": "Eskimo", "text": "Go.", "next": "end"},
                "end": {"end": True},
            },
        }
    )


def test_bad_graph_is_rejected():
    with pytest.raises(ValueError):
        load_graph({"id": "x", "start": "missing", "nodes": {"a": {"text": "Hi"}}})


def test_runner_skip_choice_and_command():
    flags = DialogueFlags()
    commands = CommandDispatcher(flags)
    commands.register("offer_quest", lambda arg: None)
    runner = DialogueRunner(commands, chars_per_sec=1)
    runner.start(_line_graph())

    assert runner.kind == "line"
    assert runner.visible_text() == ""
    assert flags.has("met")
    runner.tick(0.5)
    assert runner.visible_text() != runner.text
    runner.interact()
    assert runner.revealed
    runner.interact()
    assert runner.kind == "choice"
    labels = [choice["text"] for choice in runner.choices]
    assert labels == ["Work", "Bye"]
    runner.move_choice(1)
    runner.interact()
    assert runner.active is False
    assert ("offer_quest", "ice_hunt") not in commands.pending

    runner.start(_line_graph())
    runner.interact()
    runner.interact()
    runner.interact()
    assert ("offer_quest", "ice_hunt") in commands.take_pending()
    assert runner.kind == "line"
    assert runner.text == "Go."


def test_bark_cooldown_and_cap():
    director = BarkDirector(
        {
            "a": {"speaker": "A", "text": "one", "cooldown_ms": 1000},
            "b": {"speaker": "B", "text": "two"},
            "c": {"speaker": "C", "text": "three"},
        },
        max_active=2,
        active_ms=5000,
    )
    assert director.try_play("a", 0).text == "one"
    assert director.try_play("a", 500) is None
    assert director.try_play("b", 500) is not None
    assert director.try_play("c", 500) is None
    assert director.try_play("a", 5000).text == "one"


def test_focus_picks_nearest_and_skips_opened():
    player = SimpleNamespace(rect=pygame.Rect(0, 0, 10, 10))
    far = SimpleNamespace(kind="loot_container", rect=pygame.Rect(40, 0, 10, 10), interaction_margin=80, opened=False)
    near = SimpleNamespace(kind="talk", rect=pygame.Rect(12, 0, 10, 10), interaction_margin=48, opened=False, prompt_text="[Space] Talk")
    opened = SimpleNamespace(kind="loot_container", rect=pygame.Rect(0, 0, 10, 10), interaction_margin=48, opened=True)
    focus = nearest_focus(player, [far, opened, near])
    assert focus.target is near
    assert focus.prompt == "[Space] Talk"
    assert nearest_focus(player, [opened]) is None


def test_session_bark_talk_and_settings():
    voice = _Voice()
    session = DialogueSession(voice=voice)
    sprite = SimpleNamespace(sprite_type="Eskimo", name="Eskimo", rect=pygame.Rect(100, 80, 32, 48))
    player = SimpleNamespace(rect=pygame.Rect(110, 90, 32, 32))
    settings = GameSettings()
    settings.voice_enabled = False
    settings.speech_bubbles = False
    session.update_world(player, [sprite], [], 0, 0.0, settings)
    assert session.focus.kind == "talk"
    assert session.focus_prompt() == "[Space] Talk"
    assert len(session.bubbles.items) == 1
    session.update_world(player, [sprite], [], 1000, 0.0, settings)
    assert len(session.bubbles.items) == 1

    backend = _Backend()
    session.draw(backend, SimpleNamespace(x=0, y=0), settings)
    assert backend.rects == []
    assert len(backend.blits) == 1

    assert session.try_start_focused() is True
    assert session.blocks_gameplay()
    assert session.focus_prompt() is None
    session.handle_input(_Keys({pygame.K_SPACE}))
    session.handle_input(_Keys({pygame.K_SPACE}))
    session.handle_input(_Keys({pygame.K_RETURN}))
    pending = session.commands.take_pending()
    assert ("set_flag", "met_eskimo=1") in pending
    assert ("offer_quest", "ice_hunt") in pending
    assert session.runner.text == "Ice bears have been bold."

    settings.conversation_text = False
    settings.speech_bubbles = True
    session.draw(backend, SimpleNamespace(x=0, y=0), settings)
    assert backend.rects

    session.handle_input(_Keys({pygame.K_ESCAPE}))
    assert session.blocks_gameplay() is False


class _Pack:
    def __init__(self, accept=True):
        self.items = []
        self.accept = accept

    def add_item(self, item):
        if not self.accept:
            return False
        self.items.append(item)
        return True


def test_trade_choice_opens_the_shop_and_buys():
    session = DialogueSession(voice=_Voice())
    pack = _Pack()
    player = SimpleNamespace(rect=pygame.Rect(110, 90, 32, 32), gold=40, inventory=pack)
    sprite = SimpleNamespace(sprite_type="Eskimo", name="Eskimo", rect=pygame.Rect(100, 80, 32, 48))
    session.update_world(player, [sprite], [], 0, 0.0, GameSettings())
    assert session.try_start_focused() is True
    session.handle_input(_Keys({pygame.K_SPACE}))
    session.handle_input(_Keys({pygame.K_SPACE}))
    session.handle_input(_Keys({pygame.K_DOWN}))
    session.handle_input(_Keys({pygame.K_RETURN}))
    assert session.trade.visible is True
    assert session.trade.shop_id == "eskimo"
    assert session.blocks_gameplay()
    assert session.runner.active

    session.handle_input(_Keys({pygame.K_SPACE}))
    assert player.gold == 32
    assert pack.items[0].item_id == "frozen_fish"
    assert session.trade.notice == "Bought Frozen fish"

    player.gold = 0
    session.handle_input(_Keys({pygame.K_SPACE}))
    assert session.trade.notice == "Not enough gold"
    assert len(pack.items) == 1

    player.gold = 40
    player.inventory = _Pack(accept=False)
    session.handle_input(_Keys({pygame.K_SPACE}))
    assert session.trade.notice == "Pack is full"
    assert player.gold == 40

    backend = _Backend()
    session.draw(backend, SimpleNamespace(x=0, y=0), GameSettings())
    assert backend.blits

    session.handle_input(_Keys({pygame.K_ESCAPE}))
    assert session.trade.visible is False
    assert session.runner.active
    assert session.blocks_gameplay()


def test_trade_pack_sells_and_tabs_filter():
    session = DialogueSession(voice=_Voice())
    fish = make_item("frozen_fish")
    feather = make_item("arctic_feather")
    key = make_item("boss_key")
    assert resolve_image(fish.image_path)
    assert category_of("frozen_fish") == "goods"
    assert category_of("arctic_feather") == "gear"
    slots = [
        SimpleNamespace(item=fish, quantity=2),
        SimpleNamespace(item=feather, quantity=1),
        SimpleNamespace(item=key, quantity=1),
    ]
    pack = _Pack()
    pack.slots = slots
    pack.backpack_start_index = 0
    player = SimpleNamespace(rect=pygame.Rect(110, 90, 32, 32), gold=10, inventory=pack)
    sprite = SimpleNamespace(sprite_type="Eskimo", name="Eskimo", rect=pygame.Rect(100, 80, 32, 48))
    session.update_world(player, [sprite], [], 0, 0.0, GameSettings())
    assert session.try_start_focused() is True
    session.handle_input(_Keys({pygame.K_SPACE}))
    session.handle_input(_Keys({pygame.K_SPACE}))
    session.handle_input(_Keys({pygame.K_DOWN}))
    session.handle_input(_Keys({pygame.K_RETURN}))

    session.handle_input(_Keys({pygame.K_e}))
    assert [row["item_id"] for row in session.trade._shop_rows()] == ["frozen_fish", "frost_potion"]

    session.handle_input(_Keys({pygame.K_TAB}))
    session.handle_input(_Keys({pygame.K_SPACE}))
    assert player.gold == 14
    assert slots[0].quantity == 1
    assert session.trade.notice == "Sold Frozen fish for 4"

    session.handle_input(_Keys({pygame.K_RIGHT}))
    session.handle_input(_Keys({pygame.K_RIGHT}))
    session.handle_input(_Keys({pygame.K_SPACE}))
    assert session.trade.notice == "He won't buy that"
    assert player.gold == 14
    assert slots[2].quantity == 1

    backend = _Backend()
    session.draw(backend, SimpleNamespace(x=0, y=0), GameSettings())
    assert backend.blits


def test_space_on_focused_chest_uses_that_chest():
    from Level4_tmxdev import Level4

    voice = _Voice()
    session = DialogueSession(voice=voice)
    player = SimpleNamespace(rect=pygame.Rect(0, 0, 10, 10))
    chest = SimpleNamespace(
        kind="loot_container",
        rect=pygame.Rect(8, 0, 10, 10),
        interaction_margin=40,
        opened=False,
    )
    session.focus = nearest_focus(player, [chest])
    opened = []
    level = SimpleNamespace(
        input_manager=_Keys({pygame.K_SPACE}),
        game_paused=False,
        inventory_open=False,
        dialogue=session,
        rts_session=None,
        _stand_from_seat=lambda: False,
        _open_loot_container=opened.append,
    )
    assert Level4.try_interact_nearby_environment(level) is True
    assert opened == [chest]


def test_voice_missing_file_and_mute():
    class _Sound:
        def __init__(self):
            self.played = 0

        def play(self):
            self.played += 1

        def stop(self):
            return None

    sound = _Sound()
    voice = VoiceChannel(loader=lambda key: sound if key == "ok" else None)
    assert voice.play("missing", enabled=True) is False
    assert voice.play("ok", enabled=False) is False
    assert voice.play("ok", enabled=True) is True
    assert sound.played == 1


def test_settings_rows_cover_speech_toggles():
    settings = GameSettings()
    menu = SettingsMenu(settings)
    assert len(menu._rows()) == len(settings.MENU_ROWS)
    settings.activate_row("speech_bubbles")
    settings.activate_row("conversation_text")
    settings.step_left("voice_enabled")
    assert settings.speech_bubbles is False
    assert settings.conversation_text is False
    assert settings.voice_enabled is False
    labels = [label for label, _value in menu._rows()]
    assert "Speech bubbles" in labels
    assert "Voice" in labels
