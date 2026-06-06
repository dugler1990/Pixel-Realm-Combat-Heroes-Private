from ..assets import load_sprite, normalize_faction_id

import pygame


class DropoffBuilding(pygame.sprite.Sprite):
    def __init__(self, pos, groups, config, registry=None):
        super().__init__(groups)
        self.kind = "rts_building"
        self.config = dict(config)
        self.dropoff_kind = str(config.get("dropoff_kind", "dropoff"))
        self.faction_id = normalize_faction_id(config.get("faction_id", ""))
        raw = str(config.get("accepts_categories", ""))
        self.accepts_categories = {
            c.strip().lower() for c in raw.split(",") if c.strip()
        }
        self.sprite_key = str(config.get("sprite", f"building_{self.dropoff_kind}"))
        self.rts_selectable = True

        self.image = load_sprite(self.sprite_key)
        self.rect = self.image.get_rect(center=pos)
        self.mask = pygame.mask.from_surface(self.image)
        offset_x = int(config.get("dropoff_offset_x", 0) or 0)
        offset_y = int(config.get("dropoff_offset_y", 36) or 36)
        self.dropoff_point = (
            self.rect.centerx + offset_x,
            self.rect.centery + offset_y,
        )
        self.display_name = self.dropoff_kind.replace("_", " ").title()
        self.rts_definition = {
            "id": self.dropoff_kind,
            "display_name": self.display_name,
            "description": "Resource dropoff",
            "actions": [],
        }
        if registry is not None:
            registry.register_dropoff(self)

    def accepts(self, category):
        return str(category).lower() in self.accepts_categories
