import pygame

from ..assets import load_sprite, normalize_faction_id
from ..visual_sequence import TimedPhaseVisual

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
        self._phase_visual = None
        self._visual_active = False

    def setup_visual_from_building(self, building):
        phases = getattr(building, "visual_phases", None) or []
        if phases:
            self._phase_visual = TimedPhaseVisual(
                phases, fallback_size=(max(8, self.rect.width), max(8, self.rect.height))
            )
        else:
            self._phase_visual = None
        self._visual_active = False

    def start_visual(self):
        if self._phase_visual is not None:
            self._phase_visual.reset()
            self._phase_visual.start()
            self._visual_active = True
            self._phase_visual.apply_to_sprite(self)

    def update_visual(self, dt):
        if not self._visual_active or self._phase_visual is None:
            return
        self._phase_visual.update(float(dt or 0))
        self._phase_visual.apply_to_sprite(self)

    def freeze_visual(self):
        self._visual_active = False
        if self._phase_visual is not None:
            self._phase_visual.apply_to_sprite(self)

    def is_available(self):
        return self.state == SITE_UNBUILT

    @property
    def build_center(self):
        return self.rect.center
