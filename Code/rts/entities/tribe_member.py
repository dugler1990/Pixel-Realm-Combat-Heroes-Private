import math
import random

import pygame

from Support import import_folder, normalize_animation_frames
from combat_unit import CombatUnit
from hashRect import HashableRect
from Interaction import InteractionContext

from ..assets import load_sprite, normalize_faction_id
from ..behavior_drivers import WALK_STATUSES, pick_driver, DriverContext
from ..tribe_monsters import monster_name_for_faction


class RtsTribeMember(CombatUnit):
    """RTS worker/chief using CombatUnit locomotion and pluggable behavior drivers."""

    def __init__(
        self,
        pos,
        groups,
        faction_id,
        obstacle_sprites,
        combat_context,
        *,
        sprite_key="worker_eskimo",
        monster_name=None,
        behavior="job",
        persistent=False,
        layout_callback_update_quad_tree=None,
        center_pos=True,
        health=None,
        team_id="enemy",
        sprite_type=None,
    ):
        self._tribe_sprite_key = sprite_key
        self._center_pos = center_pos
        self._spawn_center = pygame.math.Vector2(pos)
        monster = monster_name or monster_name_for_faction(faction_id, sprite_key)
        if layout_callback_update_quad_tree is None and isinstance(combat_context, dict):
            layout_callback_update_quad_tree = combat_context.get("update_quad_tree")
        if layout_callback_update_quad_tree is None:
            layout_callback_update_quad_tree = lambda **_kwargs: None

        placeholder = load_sprite(sprite_key)
        topleft = pos
        if center_pos:
            topleft = (
                int(pos[0] - placeholder.get_width() / 2),
                int(pos[1] - placeholder.get_height() / 2),
            )

        super().__init__(
            monster,
            topleft,
            groups,
            obstacle_sprites,
            combat_context,
            persistent,
            layout_callback_update_quad_tree=layout_callback_update_quad_tree,
            team_id=team_id,
            sprite_type=sprite_type,
        )

        self.faction_id = normalize_faction_id(faction_id)
        self.behavior = str(behavior or "job")
        self.move_target = None
        self._roam_wait_timer = 0.0
        self._roam_target = None
        self.spawn_center = pygame.math.Vector2(self._spawn_center)
        self.rts_selectable = True
        if health is not None:
            self.health = int(health)

    def import_graphics_left_right(self, name):
        self.animations = {
            "idle": {"right": [], "left": []},
            "move": {"right": [], "left": []},
            "attack": {"right": [], "left": []},
            "gather": {"right": [], "left": []},
            "build": {"right": [], "left": []},
            "haul_ice": {"right": [], "left": []},
        }
        main_path = f"../Graphics/Monsters/{name}/"
        fallback = load_sprite(self._tribe_sprite_key or name)
        for animation in self.animations.keys():
            right = import_folder(main_path + animation)
            if not right:
                right = [fallback]
            if name == "eskimo_worker":
                right = normalize_animation_frames(right)
            self.animations[animation]["right"] = right
            self.animations[animation]["left"] = [
                pygame.transform.flip(img, True, False) for img in right
            ]

    def steer_toward(self, point):
        pos = pygame.math.Vector2(self.rect.center)
        goal = pygame.math.Vector2(point)
        delta = goal - pos
        if delta.length_squared() <= 0:
            self.direction = pygame.math.Vector2(0, 0)
            self.status = "idle"
            return
        self.direction = delta.normalize()
        if self.direction.x >= 0:
            self.direction_string = "right"
        else:
            self.direction_string = "left"
        self.status = "move"

    def _pick_roam_target(self):
        radius = float(getattr(self, "roam_radius", 80))
        angle = random.uniform(0, 360)
        dist = random.uniform(0, radius)
        rad = math.radians(angle)
        center = getattr(self, "spawn_center", self._spawn_center)
        self._roam_target = (
            int(center.x + math.cos(rad) * dist),
            int(center.y + math.sin(rad) * dist),
        )

    def _should_walk(self):
        if getattr(self, "frozen", False):
            return False
        return self.status in WALK_STATUSES and self.direction.length_squared() > 0

    def update(self, dt=None, QuadTree=None, entity_quad_tree=None, **kwargs):
        current_time = pygame.time.get_ticks()
        if getattr(self, "frozen", False) and current_time - self.freeze_time > self.freeze_duration:
            self.thaw()
        ctx = DriverContext(entity_quad_tree=entity_quad_tree, dt=dt)
        driver = pick_driver(self.behavior)
        driver.steer(self, dt, ctx)
        if self._should_walk():
            self.move(self.speed, QuadTree, entity_quad_tree)
            self.hit_reaction()
        self.animate()
        self.cooldowns()
        self.check_death()

    def can_receive_interaction(self, ctx: InteractionContext):
        if ctx.kind == "effect_state":
            return True
        if ctx.kind != "damage":
            return False
        if ctx.source_team == self.team_id:
            return False
        return self.health > 0

    def receive_interaction(self, ctx: InteractionContext):
        if ctx.kind == "effect_state":
            super().receive_interaction(ctx)
            return
        if ctx.kind != "damage":
            return
        amount = ctx.amount
        if amount is None:
            source = ctx.source
            if source is not None and hasattr(source, "get_full_weapon_damage"):
                if ctx.attack_type == "weapon":
                    amount = source.get_full_weapon_damage()
                elif hasattr(source, "get_full_magic_damage"):
                    amount = source.get_full_magic_damage()
        if amount is None:
            return
        if self.vulnerable:
            self.health -= int(amount)
            self.check_death()

    def check_death(self):
        if self.health > 0:
            return
        if getattr(self, "_quad_tree_callback_provided", False):
            self.layout_callback_update_quad_tree(
                obstacle_sprite=HashableRect(self.rect, self.id),
                remove_existing=True,
                alive=False,
            )
        sim = getattr(self, "world_sim", None)
        if sim is not None:
            sim.on_worker_death(self)
        self.kill()
