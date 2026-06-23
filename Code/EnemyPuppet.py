"""Network-driven enemy sprite for co-op (Stage C, slice C1).

`EnemyPuppet` is to `CombatUnit` what `RemotePlayer` is to `BasePlayer`: a thin
sibling that reuses the ENTIRE enemy asset/animation/mask pipeline via
inheritance, and only replaces the per-frame *drive* so its position/facing/
animation-status come from the host's relayed enemy snapshots instead of local
AI.

Co-op is HOST-AUTHORITATIVE for enemies (see the multiplayer plan's Stage C):
exactly one client (the host) runs the real enemy simulation and relays each
enemy's render state; the joiner renders those as puppets and spawns none of its
own. So a puppet must NEVER run AI/movement/combat -- both `update()` (called by
the camera group's update_parallel) and `enemy_update()` (called by Level4's
per-frame `visible_sprites` sweep) are overridden to be render-only.

C1 is visibility only: puppets are in `visible_sprites` (so custom_draw
Y-sorts/draws them) but NOT in `attackable_sprites` or the quad-trees -- they
can't be hit and don't collide. C2 adds them to `attackable_sprites` so the
joiner's attacks register; C3 syncs health/death authoritative on the host.
"""

import pygame

from combat_unit import CombatUnit


class EnemyPuppet(CombatUnit):
    def __init__(self, enemy_id, monster_name, center, groups, obstacle_sprites, level):
        # Reuse CombatUnit.__init__ for the full graphics/mask/stat setup. Pass a
        # minimal combat_context (no "update_quad_tree" key -> the unit registers
        # in NO quad-tree, exactly what a render-only puppet wants) and empty
        # combat data (the AI/strategy is built but never driven here).
        super().__init__(
            monster_name=monster_name,
            pos=center,
            groups=groups,
            obstacle_sprites=obstacle_sprites,
            combat_context={"level": level},
            persistent=False,
            special_attacks=None,
            item_drop_info=None,
            team_id="enemy",
        )
        self.enemy_id = enemy_id
        self.type = monster_name
        self.level = level

        # Latest authoritative values from the host's relay, applied in update().
        self._net_x, self._net_y = center
        self._net_status = "idle"
        self._net_dir = "right"
        # C2.5a: brief local hit-flash window (ms tick) so the JOINER sees its
        # hits land -- the real enemy's hit reaction/sound happen on the host.
        self._hit_flash_until = 0

        # CombatUnit.__init__ anchored rect by topleft=pos; the wire relays
        # CENTERS (like players), so re-anchor on both rect and hitbox.
        self.rect.center = center
        self.hitbox.center = center

    def apply_snapshot(self, x, y, status, direction_string, health=None):
        """Store the host's latest render state for this enemy + reposition NOW.

        Called once per received enemy snapshot by Level4's inbox drain (top of
        run(), before custom_draw) -- same immediate-reposition rationale as
        RemotePlayer.apply_snapshot, so what's drawn this frame == what arrived.
        Main thread only.
        """
        self._net_x = x
        self._net_y = y
        self._net_status = status
        self._net_dir = direction_string
        if health is not None:
            self.health = health
        self._sync_from_snapshot()

    def _sync_from_snapshot(self):
        self.status = self._net_status
        # animate() derives facing from self.direction.x via
        # get_direction_as_string(); drive it from the relayed dir string.
        self.direction.x = -1.0 if self._net_dir == "left" else 1.0
        self.hitbox.center = (self._net_x, self._net_y)
        self.rect.center = self.hitbox.center

    def update(self, *args, **kwargs):
        # Render-only (camera group update_parallel calls this). Deliberately
        # skips CombatUnit.update's move()/cooldowns()/check_death() -- the host
        # owns position/death. animate() rebuilds the frame + re-centers rect.
        self._sync_from_snapshot()
        self.animate()
        # C2.5a: blink while recently hit so the joiner sees the hit land.
        # animate() rebuilt self.image this frame, so set_alpha is safe.
        if pygame.time.get_ticks() < self._hit_flash_until:
            self.image.set_alpha(110 if (pygame.time.get_ticks() // 40) % 2 else 255)

    def enemy_update(self, *args, **kwargs):
        # Render-only: NO AI/target-selection/attacks (Level4's per-frame
        # visible_sprites sweep calls this on anything with enemy_update).
        return None

    def combat_update(self, *args, **kwargs):
        return None

    def receive_interaction(self, ctx):
        """Co-op (C2): the JOINER's attack hit this puppet. The enemy is
        host-authoritative, so we DON'T change health here -- we resolve the
        damage from OUR player's stats (the host lacks them) the same way
        CombatUnit.receive_interaction would, and relay it to the host, which
        applies it to the real enemy. Health/death come back via the C1 relay.
        Relayed every overlapping frame (no i-frames here) -- the host's real
        enemy gates repeats exactly as it does for the host's own hits.
        """
        if getattr(ctx, "kind", None) != "damage":
            return
        amount = ctx.amount
        if amount is None:
            source = ctx.source
            if (source is not None and hasattr(source, "get_full_weapon_damage")
                    and hasattr(source, "get_full_magic_damage")):
                amount = (source.get_full_weapon_damage() if ctx.attack_type == "weapon"
                          else source.get_full_magic_damage())
        if amount is None:
            return
        self.level._queue_enemy_hit(self.enemy_id, amount, ctx.attack_type)
        # C2.5a: immediate local feedback so the joiner knows the hit landed
        # (the host plays the real hit reaction/sound; the joiner gets none).
        self._hit_flash_until = pygame.time.get_ticks() + 150
        try:
            self.hit_sound.play()
        except Exception:
            pass
