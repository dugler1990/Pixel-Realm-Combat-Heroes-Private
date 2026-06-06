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

    def get_selectable_sprites(self, throne_profile_id=""):
        raise NotImplementedError

    def get_map_bounds(self):
        raise NotImplementedError

    def request_player_stand(self):
        raise NotImplementedError

    def is_player_dead(self):
        raise NotImplementedError

    def get_rts_population_count(self, faction_id=""):
        registry = self.get_rts_registry()
        if registry is not None and faction_id:
            from .assets import normalize_faction_id

            fid = normalize_faction_id(faction_id)
            return len(registry.workers_by_faction.get(fid, []))
        count = 0
        for sprite in self.get_selectable_sprites():
            if str(getattr(sprite, "kind", "")).strip().lower() == "rts_unit":
                count += 1
        return count

    def get_obstacle_sprites(self):
        return None

    def get_obstacle_quad_tree(self):
        return None

    def get_walk_grid_cache(self):
        return None

    def get_rts_registry(self):
        return None

    def get_selectable_sprites_for_throne(self, throne_profile_id):
        return self.get_selectable_sprites()

    def get_sprite_groups(self):
        return []
