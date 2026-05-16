import pygame

from Support import mask_midbottom_world


class InteractableSeat(pygame.sprite.Sprite):
    """Static world seat interactable used by composite sit animations."""

    def __init__(
        self,
        pos,
        groups,
        env_list,
        idle_surface,
        profile_id="",
        kind="seat",
        interaction_margin=48,
        merged_config=None,
        display_size=None,
    ):
        super().__init__(groups)
        self.profile_id = profile_id or ""
        self.kind = kind
        self.interaction_margin = int(interaction_margin)
        self.env_config = merged_config or {}
        self.display_size = display_size
        self.opened = False

        self.image = idle_surface.copy()
        self.mask = pygame.mask.from_surface(self.image)
        self.rect = self.image.get_rect(topleft=pos)

        self.player_offset = self._parse_xy(self.env_config.get("player_offset"), (0, 0))
        self.seat_anchor_mode = str(
            self.env_config.get("seat_anchor_mode", "mask_midbottom")
        ).strip().lower()
        self.seat_anchor_offset = self._parse_xy(
            self.env_config.get("seat_anchor_offset"), (0, 0)
        )

        env_list.append(self)

    def _parse_xy(self, raw_value, default):
        if isinstance(raw_value, dict):
            try:
                return (int(raw_value.get("x", default[0])), int(raw_value.get("y", default[1])))
            except (TypeError, ValueError):
                return default
        if isinstance(raw_value, (list, tuple)) and len(raw_value) >= 2:
            try:
                return (int(raw_value[0]), int(raw_value[1]))
            except (TypeError, ValueError):
                return default
        return default

    def get_seat_anchor(self):
        mode = self.seat_anchor_mode
        if mode == "center":
            base = self.rect.center
        elif mode == "topleft":
            base = self.rect.topleft
        elif mode in ("mask_midbottom", "mask"):
            base = mask_midbottom_world(self.rect, self.mask)
        elif mode == "midbottom":
            base = self.rect.midbottom
        else:
            base = mask_midbottom_world(self.rect, self.mask)
        return (base[0] + self.seat_anchor_offset[0], base[1] + self.seat_anchor_offset[1])
