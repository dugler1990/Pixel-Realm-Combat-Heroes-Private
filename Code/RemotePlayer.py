"""Network-driven player sprite for the rudimentary multiplayer milestone.

`RemotePlayer` is a thin sibling of `SpecificPlayer`: it reuses the ENTIRE
`BasePlayer` asset/animation/mask/hitbox pipeline via inheritance, and only
overrides the input -> movement path so its position/facing/animation come
from server snapshots instead of the local `InputManager`.

See the multiplayer plan (.claude/plans/ok-lets-make-a-drifting-yeti.md),
"THE CRUX" section, for why this subclasses `BasePlayer` (not `SpecificPlayer`,
not `Entity`, not a flag on `Player`) and the per-method ownership table.

v0 is movement-sync only: position, facing direction, and the server-derived
animation `status` string. No combat/health/collision is synced -- the
inherited `move()`/`collision()`/`cooldowns()`/`get_status()`/regen/death
methods exist but are deliberately never driven here (that is Stage C/D in
the plan's convergence roadmap).
"""

import pygame

from Settings import HITBOX_OFFSET
from Player import BasePlayer


class RemotePlayer(BasePlayer):
    # Distinct from the local player's "player" type so any future code that
    # filters sprites by .type won't mistake a network puppet for the local one.
    casts_shadow = True

    def __init__(self,
                 player_id,
                 character_assets,
                 center,
                 groups,
                 obstacle_sprites,
                 initial_stats,
                 level,
                 input_manager,
                 QuadTree,
                 entity_quad_tree):
        # No-op combat callbacks: RemotePlayer never attacks/casts/evades in v0
        # (input() is overridden; the combat methods are inherited-but-unused),
        # so we intentionally do NOT wire the level's real create_attack/etc.
        # -- keeps the remote puppet fully decoupled from local combat side
        # effects. Stage C (combat sync) is where these get re-enabled.
        def _noop(*args, **kwargs):
            return None

        # Deliberately pass layout_callback_update_quad_tree=None (the default):
        # RemotePlayer must NOT register in the obstacle/entity quad trees, so
        # local enemies don't aggro on a puppet whose health/hit-reactions
        # aren't synced yet (plan: "remote players become aggro-able once
        # combat sync lands").
        super().__init__(
            center,
            groups,
            obstacle_sprites,
            _noop,             # create_attack
            _noop,             # destroy_attack
            _noop,             # create_magic
            _noop,             # create_evasion
            initial_stats,
            level,
            input_manager,
            character_assets,  # character_assets (player_info_dir path)
            QuadTree,
            entity_quad_tree,
        )

        self.player_id = player_id
        self.type = "remote_player"

        # Mirror SpecificPlayer's image/rect/hitbox setup (BasePlayer.__init__
        # sets up animations/masks but leaves the live image/rect/hitbox to the
        # concrete subclass). `center` is the authoritative position from the
        # wire protocol (x, y are centers -- see Server/common.to_snapshot).
        self.image = pygame.image.load(character_assets + "down_idle/0.png").convert_alpha()
        self.rect = self.image.get_rect(center=center)
        self.hitbox = self.rect.inflate(-6, HITBOX_OFFSET["player"])

        # Latest authoritative network values, consumed in update(). Seeded so
        # the puppet sits idle at its spawn until the first snapshot arrives.
        self._net_x, self._net_y = self.rect.center
        self._net_dx = 0.0
        self._net_dy = 0.0
        self._net_status = "down_idle"
        # Override BasePlayer.__init__'s default "down" so the puppet shows the
        # idle frame coherently even before its first update() tick.
        self.status = self._net_status

    def apply_snapshot(self, x, y, direction_x, direction_y, status):
        """Store the latest authoritative network values + reposition NOW.

        Called once per received state_update by Level4's inbox drain, which
        runs at the TOP of run() -- before custom_draw. We reposition the
        sprite here (not only in update()) because in the daytime path
        custom_draw runs BEFORE update_parallel; if we waited for update() the
        sprite would be drawn at the *previous* snapshot, one frame stale. By
        snapping position on receipt, what's drawn this frame == what just
        arrived. (update() still re-syncs, harmlessly, for frames with no new
        snapshot.) Main thread only.
        """
        self._net_x = x
        self._net_y = y
        self._net_dx = direction_x
        self._net_dy = direction_y
        self._net_status = status
        self._sync_position_from_snapshot()

    def input(self):
        # Overridden: no InputManager polling. Drive facing/animation purely
        # from the server-shipped direction + status (the server is the single
        # source of truth for `status` -- see plan "Wire protocol").
        self.direction.x = self._net_dx
        self.direction.y = self._net_dy
        self.status = self._net_status

    def update(self, QuadTree=None, entity_quad_tree=None, dt=None, layout_switch=False):
        # Overridden + trimmed vs BasePlayer.update(): input() -> animate() ->
        # position sync. Deliberately skips move()/collision()/cooldowns()/
        # get_status()/energy_recovery()/health_recovery()/player_death() --
        # the server owns position & status; nothing local should fight it.
        #
        # Signature matches what YSortCameraGroup._update_single_sprite passes
        # to every Entity: update(dt=..., QuadTree=..., entity_quad_tree=...).
        self.input()
        self.animate()
        self._sync_position_from_snapshot()

    def _sync_position_from_snapshot(self):
        # v0 "snap" (no interpolation): teleport to each authoritative position.
        # animate() rebuilds self.rect centered on the *previous* hitbox, so we
        # re-anchor both hitbox and rect to the latest network center here.
        # tick/server_time_ms already ride in the protocol for a Stage D lerp
        # upgrade if testing shows visible popping.
        self.hitbox.center = (self._net_x, self._net_y)
        self.rect.center = self.hitbox.center

    # -- v0 isolation: keep the puppet inert wrt the LOCAL world simulation.
    #    Level4.run() calls these on every Entity in visible_sprites; the
    #    server will own effects/environmental damage for remote players in
    #    Stage C, so locally they are no-ops (no unsynced health/effect drift).
    def check_effects(self, *args, **kwargs):
        return None

    def apply_environmental_damage(self, *args, **kwargs):
        return None
