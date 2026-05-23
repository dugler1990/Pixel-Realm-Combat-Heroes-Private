import pygame


def nearest_sprite_in_direction(origin, sprites, direction, current=None):
    """Pick the sprite best aligned with direction (all candidates, ignores camera)."""
    if direction.length_squared() == 0 or not sprites:
        return current
    direction = direction.normalize()
    if hasattr(origin, "rect"):
        origin_pt = pygame.math.Vector2(origin.rect.center)
    else:
        origin_pt = pygame.math.Vector2(origin)

    best = None
    best_score = None
    for sprite in sprites:
        if current is not None and sprite is current:
            continue
        delta = pygame.math.Vector2(sprite.rect.center) - origin_pt
        if delta.length_squared() == 0:
            continue
        candidate_direction = delta.normalize()
        alignment = candidate_direction.dot(direction)
        if alignment <= 0.25:
            continue
        distance = delta.length()
        score = (1.0 - alignment) * 1000.0 + distance
        if best_score is None or score < best_score:
            best = sprite
            best_score = score
    return best if best is not None else current


class RtsSelectable:
    """Lightweight selectable wrapper around a world sprite."""

    def __init__(self, sprite, selectable_id=None, display_name=None, description=None, image=None, actions=None):
        self.sprite = sprite
        self.selectable_id = selectable_id or getattr(sprite, "profile_id", "") or str(id(sprite))
        self.display_name = display_name or self._default_name(sprite)
        self.description = description or self._default_description(sprite)
        self.image = image or getattr(sprite, "image", None)
        self.actions = actions or []

    @staticmethod
    def _default_name(sprite):
        profile_id = getattr(sprite, "profile_id", "")
        if profile_id:
            return str(profile_id).replace("_", " ").title()
        kind = getattr(sprite, "kind", "")
        if kind:
            return str(kind).replace("_", " ").title()
        return sprite.__class__.__name__

    @staticmethod
    def _default_description(sprite):
        kind = getattr(sprite, "kind", "")
        if kind == "seat":
            return "A command throne used to direct the tribe."
        return "Selectable world object."

    @property
    def rect(self):
        return self.sprite.rect


class SelectableRegistry:
    """Builds and navigates RTS selectables without mutating world sprites."""

    def __init__(self):
        self.selectables = []
        self.selected = None

    def rebuild(self, sprites):
        previous_sprite = self.selected.sprite if self.selected is not None else None
        self.selectables = [self._wrap(sprite) for sprite in sprites if self._is_selectable(sprite)]
        self.selected = None
        if previous_sprite is not None:
            for selectable in self.selectables:
                if selectable.sprite is previous_sprite:
                    self.selected = selectable
                    break

    def _is_selectable(self, sprite):
        if not hasattr(sprite, "rect"):
            return False
        if getattr(sprite, "rts_selectable", False):
            return True
        kind = str(getattr(sprite, "kind", "")).strip().lower()
        return kind in (
            "seat",
            "chief",
            "rts_building",
            "rts_unit",
            "resource_node",
            "build_site",
        )

    def _wrap(self, sprite):
        rts_def = getattr(sprite, "rts_definition", None)
        if isinstance(rts_def, dict):
            return RtsSelectable(
                sprite,
                selectable_id=rts_def.get("id"),
                display_name=rts_def.get("display_name"),
                description=rts_def.get("description"),
                image=rts_def.get("image"),
                actions=rts_def.get("actions") or [],
            )
        return RtsSelectable(sprite)

    def select_bottom_left(self, camera_rect=None):
        candidates = self._visible_candidates(camera_rect) or self.selectables
        if not candidates:
            self.selected = None
            return None
        self.selected = sorted(candidates, key=lambda item: (-item.rect.centery, item.rect.centerx))[0]
        return self.selected

    def _visible_candidates(self, camera_rect):
        if camera_rect is None:
            return []
        return [item for item in self.selectables if camera_rect.colliderect(item.rect)]

    def move_selection(self, direction, camera_rect=None):
        if direction.length_squared() == 0:
            return self.selected
        if self.selected is None:
            return self.select_bottom_left(camera_rect)
        direction = direction.normalize()
        origin = pygame.math.Vector2(self.selected.rect.center)
        candidates = self._visible_candidates(camera_rect) or self.selectables
        best = None
        best_score = None
        for candidate in candidates:
            if candidate is self.selected:
                continue
            delta = pygame.math.Vector2(candidate.rect.center) - origin
            if delta.length_squared() == 0:
                continue
            candidate_direction = delta.normalize()
            alignment = candidate_direction.dot(direction)
            if alignment <= 0.25:
                continue
            distance = delta.length()
            score = (1.0 - alignment) * 1000.0 + distance
            if best_score is None or score < best_score:
                best = candidate
                best_score = score
        if best is not None:
            self.selected = best
        return self.selected
