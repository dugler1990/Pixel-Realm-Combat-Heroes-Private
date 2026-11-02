import pygame
from Settings import weapon_data
from attack_sprite import AttackSprite
import hit_core

# path -> (image, mask). Loaded once; every swing of that weapon in that direction shares it.
_WEAPON_ART = {}


def _weapon_art(path):
    art = _WEAPON_ART.get(path)
    if art is None:
        image = pygame.image.load(path).convert_alpha()
        art = (image, pygame.mask.from_surface(image))
        _WEAPON_ART[path] = art
    return art


class Weapon(AttackSprite, pygame.sprite.Sprite):
    def __init__(self, player, groups):
        super().__init__(groups)
        self.sprite_type = "weapon"
        self.init_attack(
            owner=player,
            source_team=getattr(player, "team_id", "player"),
            source_kind="player_attack",
            attack_type="weapon",
            tags={"weapon", "player_attack"},
            rehit_ms=weapon_data.get(player.weapon, {}).get("rehit_ms"),
        )
        direction = player.status.split("_")[0]
        direction = direction.capitalize()
        # Graphics
        full_path = f"../Graphics/Weapons/{player.weapon.capitalize()}/{direction}.png"
        self.image, self.mask = _weapon_art(full_path)
        # Unarmed art has no opaque pixels: the punch is the player's own body (hit_shape).
        self._unarmed = self.mask.count() == 0

        # Print the direction for debugging
        #print(f"Weapon direction: {direction}")

        # Placement
        if direction == "Right":
            self.rect = self.image.get_rect(midleft=player.rect.midright + pygame.math.Vector2(0, 16))
            #print(f"Weapon position (Right): {self.rect.topleft}")
        elif direction == "Left":
            self.rect = self.image.get_rect(midright=player.rect.midleft + pygame.math.Vector2(0, 16))
            #print(f"Weapon position (Left): {self.rect.topright}")
        elif direction == "Down":
            self.rect = self.image.get_rect(midtop=player.rect.midbottom + pygame.math.Vector2(-10, 0))
            #print(f"Weapon position (Down): {self.rect.midtop}")
        else:  # Assuming Up
            self.rect = self.image.get_rect(midbottom=player.rect.midtop + pygame.math.Vector2(-10, 0))
            #print(f"Weapon position (Up): {self.rect.midbottom}")

    def hit_shape(self):
        """Unarmed: the player's current frame, so a punch lands where the player's sprite
        touches (the same rule as enemy swings). Weapons with art: None, so hit_core uses
        the art's mask."""
        if self._unarmed:
            return hit_core.shape_of(self.owner)
        return None
