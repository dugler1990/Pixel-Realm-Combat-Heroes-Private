import pygame

from rts.world_adapter import RtsWorldAdapter


class FakeSprite:
    def __init__(
        self,
        center=(0, 0),
        size=(20, 20),
        kind="",
        profile_id="",
        rts_selectable=False,
        rts_definition=None,
    ):
        self.rect = pygame.Rect(0, 0, *size)
        self.rect.center = center
        self.kind = kind
        self.profile_id = profile_id
        self.rts_selectable = rts_selectable
        if rts_definition is not None:
            self.rts_definition = rts_definition


class FakeInputManager:
    def __init__(self):
        self.pressed = set()
        self.just_pressed = set()

    def hold(self, key):
        self.pressed.add(key)

    def press(self, key):
        self.pressed.add(key)
        self.just_pressed.add(key)

    def release(self, key):
        self.pressed.discard(key)

    def clear_just_pressed(self):
        self.just_pressed.clear()

    def is_key_pressed(self, key):
        return key in self.pressed

    def is_key_just_pressed(self, key):
        return key in self.just_pressed


class FakeWorldAdapter(RtsWorldAdapter):
    def __init__(
        self,
        player=None,
        selectables=None,
        map_bounds=(0, 0, 1000, 1000),
        surface_size=(800, 400),
    ):
        self.player = player or FakeSprite(center=(100, 100), kind="player")
        self.selectables = list(selectables or [])
        self.map_bounds = pygame.Rect(map_bounds) if map_bounds is not None else None
        self.surface = pygame.Surface(surface_size)
        self.stand_requested = False
        self.player_dead = False

    def get_player(self):
        return self.player

    def get_display_surface(self):
        return self.surface

    def get_visible_sprites(self):
        return self.selectables

    def get_selectable_sprites(self):
        return self.selectables

    def get_map_bounds(self):
        return self.map_bounds

    def request_player_stand(self):
        self.stand_requested = True

    def is_player_dead(self):
        return self.player_dead
