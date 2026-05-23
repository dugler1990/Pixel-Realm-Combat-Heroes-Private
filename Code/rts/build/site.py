import pygame

from ..assets import load_sprite, normalize_faction_id

SITE_UNBUILT = "unbuilt"
SITE_CLEARING = "clearing"
SITE_BUILDING = "building"
SITE_COMPLETED = "completed"


class BuildSite(pygame.sprite.Sprite):
    """Build pad discovered from TMX tile properties (e.g. deep_snow)."""

    def __init__(self, rect, faction_id, requires="deep_snow", site_id=None, groups=None):
        if groups:
            super().__init__(groups)
        else:
            super().__init__()
        self.kind = "build_site"
        self.site_id = site_id or id(self)
        self.faction_id = normalize_faction_id(faction_id)
        self.requires = str(requires or "deep_snow").strip()
        self.state = SITE_UNBUILT
        self.highlighted = False
        self.rts_selectable = True

        self.image = load_sprite("node_ice_shelf", fallback_size=(max(8, rect.width), max(8, rect.height)))
        self.rect = pygame.Rect(rect)
        self.display_name = "Build Site"
        self.rts_definition = {
            "id": f"build_site_{self.site_id}",
            "display_name": self.display_name,
            "description": f"Clear snow and build ({self.requires}).",
            "actions": [],
        }

    def is_available(self):
        return self.state == SITE_UNBUILT

    @property
    def build_center(self):
        return self.rect.center
