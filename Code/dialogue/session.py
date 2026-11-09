import json
from pathlib import Path

import pygame

from dialogue.barks import BarkDirector
from dialogue.bubbles import SpeechBubblePool
from dialogue.commands import CommandDispatcher
from dialogue.flags import DialogueFlags
from dialogue.focus import nearest_focus
from dialogue.graph import load_graph
from dialogue.panel import ConversationPanel
from dialogue.runner import DialogueRunner
from dialogue.talkable import TalkAnchor
from dialogue.trade import TradeWindow
from dialogue.voice import VoiceChannel

CONTENT_DIR = Path(__file__).resolve().parent / "content"
_STUBS = ("offer_quest", "give_item")


class DialogueSession:
    """What a level talks to. Graphs, focus, barks, the panel, and voice.

    Chests and seats stay in the level. This session only says which one is
    focused, and it starts a graph when that one is a talker.
    """

    def __init__(self, content_dir=None, voice=None):
        self.flags = DialogueFlags()
        self.commands = CommandDispatcher(self.flags)
        for name in _STUBS:
            self.commands.register(name, _ignore)
        self.commands.register("open_shop", self._open_shop)
        self.runner = DialogueRunner(self.commands)
        self.trade = TradeWindow()
        self.shops = {}
        self._player = None
        self.barks = BarkDirector({})
        self.bubbles = SpeechBubblePool()
        self.panel = ConversationPanel()
        self.voice = voice if voice is not None else VoiceChannel(root=str(CONTENT_DIR))
        self.graphs = {}
        self.speakers = {}
        self.focus = None
        self._settings = None
        self._anchors = {}
        self._voice_token = None
        if content_dir is not False:
            self.load_content(CONTENT_DIR if content_dir is None else content_dir)

    def load_content(self, directory):
        directory = Path(directory)
        graphs = {}
        speakers = {}
        barks = {}
        shops = {}
        if directory.is_dir():
            for path in sorted(directory.glob("*.json")):
                payload = json.loads(path.read_text(encoding="utf-8"))
                if path.name == "barks.json":
                    barks = payload
                elif path.name == "speakers.json":
                    speakers = payload
                elif path.name == "shops.json":
                    shops = payload if isinstance(payload, dict) else {}
                else:
                    graph = load_graph(payload, source=path.name)
                    graphs[graph["id"]] = graph
        self.graphs = graphs
        self.speakers = speakers
        self.shops = shops
        self.barks = BarkDirector(barks)
        self._anchors = {}

    def blocks_gameplay(self):
        return self.runner.active or self.trade.visible

    def focus_prompt(self):
        if self.runner.active or self.trade.visible or self.focus is None:
            return None
        return self.focus.prompt

    def update_world(self, player, sprites, env_interactables, now_ms, dt, settings=None):
        self._player = player
        self._settings = settings
        anchors = self._anchors_for(sprites)
        self.focus = nearest_focus(player, list(env_interactables) + anchors)
        if not self.runner.active:
            self._bark_nearby(player, anchors, now_ms)
        self.runner.tick(dt)
        self.bubbles.tick(now_ms)
        self._sync_voice()

    def handle_input(self, input_manager):
        if self.trade.visible:
            return self.trade.handle_input(input_manager)
        if not self.runner.active:
            return False
        if input_manager.is_key_just_pressed(pygame.K_ESCAPE):
            self.runner.end()
            self.voice.stop()
            self._voice_token = None
            return True
        if input_manager.is_key_just_pressed(pygame.K_UP):
            self.runner.move_choice(-1)
        elif input_manager.is_key_just_pressed(pygame.K_DOWN):
            self.runner.move_choice(1)
        elif input_manager.is_key_just_pressed(pygame.K_RETURN) or input_manager.is_key_just_pressed(pygame.K_SPACE):
            self.runner.interact()
            self._sync_voice()
        return True

    def try_start_focused(self):
        focus = self.focus
        if focus is None or focus.kind != "talk" or self.runner.active:
            return False
        graph = self.graphs.get(getattr(focus.target, "graph_id", None))
        if graph is None:
            return False
        anchor = getattr(focus.target, "sprite", focus.target)
        self.runner.start(graph, anchor=anchor)
        self._sync_voice()
        return True

    def draw(self, backend, offset, settings=None):
        bubbles_on = _flag(settings, "speech_bubbles", True)
        text_on = _flag(settings, "conversation_text", True)
        self.bubbles.draw(backend, offset, enabled=bubbles_on)
        self._draw_marker(backend, offset)
        if self.trade.visible:
            self.trade.draw(backend)
        elif self.runner.active:
            self.panel.draw(backend, self.runner.snapshot(), show_text=text_on)

    def _anchors_for(self, sprites):
        live = {}
        for sprite in sprites:
            spec = self._spec_for(sprite)
            if spec is None:
                continue
            key = id(sprite)
            anchor = self._anchors.get(key)
            if anchor is None or anchor.sprite is not sprite:
                anchor = TalkAnchor(
                    sprite,
                    spec["graph"],
                    spec.get("name") or spec["graph"],
                    spec.get("barks") or [],
                    spec.get("margin", 48),
                )
            live[key] = anchor
        self._anchors = live
        return list(live.values())

    def _spec_for(self, sprite):
        for key in (getattr(sprite, "sprite_type", None), getattr(sprite, "name", None)):
            if key and key in self.speakers:
                return self.speakers[key]
        return None

    def _bark_nearby(self, player, anchors, now_ms):
        player_rect = getattr(player, "rect", None)
        if player_rect is None:
            return
        for anchor in anchors:
            margin = anchor.interaction_margin
            if not player_rect.colliderect(anchor.rect.inflate(margin, margin)):
                continue
            for bark_id in anchor.barks:
                event = self.barks.try_play(bark_id, now_ms, anchor=anchor.sprite)
                if event is None:
                    continue
                head = anchor.rect.midtop
                self.bubbles.spawn(event, (head[0], head[1] - 6), now_ms)
                self._play(event.audio_key)
                break

    def _sync_voice(self):
        event = self.runner.last_event
        if event is None:
            return
        token = (event.kind, event.node_id, event.text)
        if token == self._voice_token:
            return
        self._voice_token = token
        if event.kind == "end":
            self.voice.stop()
            return
        if event.kind == "line" and event.audio_key:
            self._play(event.audio_key)

    def _play(self, audio_key):
        self.voice.play(audio_key, enabled=_flag(self._settings, "voice_enabled", True))

    def _draw_marker(self, backend, offset):
        focus = self.focus
        if self.runner.active or self.trade.visible or focus is None or focus.kind != "talk":
            return
        target = focus.target
        rect = target.rect
        sx = int(rect.centerx - offset.x)
        sy = int(rect.top - offset.y - 4)
        width, height = backend.get_size()
        if sx < 0 or sy < 0 or sx > width or sy > height:
            return
        label = getattr(target, "display_name", None) or "Talk"
        surface = self.bubbles.label(label)
        dest = surface.get_rect(midbottom=(sx, sy))
        backend.blit(surface, dest, cache_key=id(surface))


    def _open_shop(self, shop_id):
        self.trade.open(str(shop_id), self.shops.get(shop_id), self._player)


def _ignore(_arg):
    return None


def _flag(settings, name, default):
    if settings is None:
        return default
    return bool(getattr(settings, name, default))
