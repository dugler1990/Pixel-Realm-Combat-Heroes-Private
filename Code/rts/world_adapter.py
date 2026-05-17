class RtsWorldAdapter:
    """Small host-world interface consumed by the RTS subsystem.

    Implementations may wrap the current action-RPG level or a future
    standalone RTS map. Keep concrete Level4 knowledge out of the RTS package.
    """

    def get_player(self):
        raise NotImplementedError

    def get_display_surface(self):
        raise NotImplementedError

    def get_visible_sprites(self):
        raise NotImplementedError

    def get_selectable_sprites(self):
        raise NotImplementedError

    def get_map_bounds(self):
        raise NotImplementedError

    def request_player_stand(self):
        raise NotImplementedError

    def is_player_dead(self):
        raise NotImplementedError
