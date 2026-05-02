import pygame
from game_logging import get_tmx_layout_logger


_tmx_layout_log = get_tmx_layout_logger()


class InteractableChest(pygame.sprite.Sprite):
    """World interactable with kind=loot_container; loot from merged profile + TMX loot_json."""

    def __init__(
        self,
        pos,
        groups,
        env_list,
        idle_surface,
        hit_frames,
        loot_info,
        profile_id="",
        kind="loot_container",
        interaction_margin=48,
        open_animation_path=None,
        image_open_path=None,
        merged_config=None,
        tmx_folder=None,
        display_size=None,
    ):
        super().__init__(groups)
        self.profile_id = profile_id or ""
        # (w, h) in game pixels when scaled from TMX object size; used for open visuals.
        self.display_size = display_size
        self.kind = kind
        self.env_config = merged_config or {}
        self.loot_info = loot_info or {}
        self.interaction_margin = int(interaction_margin)
        self.open_animation_path = open_animation_path
        self.image_open_path = image_open_path
        self.opened = False
        self.tmx_folder = tmx_folder

        self._idle_surface = idle_surface
        self.hit_frames = hit_frames

        cfg = self.env_config
        try:
            self.frame_ms = max(1, int(cfg.get("frame_ms", 100)))
        except (TypeError, ValueError):
            self.frame_ms = 100

        # Proximity hit animation state.
        self.hit_playing = False
        self.hit_frame_index = 0
        self.was_player_in_range = False
        self._hit_next_frame_at = 0

        # Open animation state (runs on this same sprite; no overlay sprite).
        self.open_frames = []
        self.open_playing = False
        self.open_frame_index = 0
        self._open_next_frame_at = 0
        self._open_final_surface = None
        self._open_anchor_midbottom = None

        self.image = self._idle_surface.copy()
        self.mask = pygame.mask.from_surface(self.image)
        self.rect = self.image.get_rect(topleft=pos)

        env_list.append(self)

    def _apply_surface(self, surf, keep_topleft=True, anchor_midbottom=None):
        if surf is None:
            return
        if anchor_midbottom is not None:
            self.image = surf.copy()
            self.mask = pygame.mask.from_surface(self.image)
            self.rect = self.image.get_rect(midbottom=anchor_midbottom)
            return
        if keep_topleft:
            top = self.rect.topleft
            self.image = surf.copy()
            self.mask = pygame.mask.from_surface(self.image)
            self.rect = self.image.get_rect(topleft=top)
            return
        self.image = surf.copy()
        self.mask = pygame.mask.from_surface(self.image)

    def _apply_idle(self):
        self._apply_surface(self._idle_surface, keep_topleft=True)

    def _apply_hit_frame(self, index):
        if not self.hit_frames or index < 0 or index >= len(self.hit_frames):
            return
        self._apply_surface(self.hit_frames[index], keep_topleft=True)

    def _apply_open_frame(self, index):
        if not self.open_frames or index < 0 or index >= len(self.open_frames):
            return
        self._apply_surface(
            self.open_frames[index],
            keep_topleft=False,
            anchor_midbottom=self._open_anchor_midbottom,
        )

    def prepare_for_open(self):
        """Stop hit animation before open loot / open visual."""
        self.hit_playing = False
        self.open_playing = False
        self._apply_idle()

    def start_open_animation(self, frames, final_surface=None, anchor_midbottom=None):
        """Start open sequence on this sprite (single-sprite path; no overlay)."""
        if not frames:
            if final_surface is not None:
                self._apply_surface(
                    final_surface,
                    keep_topleft=False,
                    anchor_midbottom=anchor_midbottom,
                )
            return
        self.open_frames = list(frames)
        self._open_final_surface = final_surface if final_surface is not None else frames[-1]
        self._open_anchor_midbottom = anchor_midbottom
        self.open_playing = True
        self.open_frame_index = 0
        now = pygame.time.get_ticks()
        self._open_next_frame_at = now + self.frame_ms
        self._apply_open_frame(0)
        _tmx_layout_log.debug(
            "Chest open start profile=%r frames=%d frame_ms=%s",
            self.profile_id,
            len(self.open_frames),
            self.frame_ms,
        )

    def _advance_open(self, now):
        if not self.open_playing:
            return
        if now < self._open_next_frame_at:
            return
        self.open_frame_index += 1
        if self.open_frame_index >= len(self.open_frames):
            self.open_playing = False
            self._apply_surface(
                self._open_final_surface,
                keep_topleft=False,
                anchor_midbottom=self._open_anchor_midbottom,
            )
            _tmx_layout_log.debug(
                "Chest open complete profile=%r",
                self.profile_id,
            )
            return
        self._apply_open_frame(self.open_frame_index)
        self._open_next_frame_at = now + self.frame_ms

    def _start_hit_animation(self, now, log_enter=False):
        if log_enter:
            _tmx_layout_log.debug(
                "Chest proximity enter profile=%r start hit animation frames=%d frame_ms=%s",
                self.profile_id,
                len(self.hit_frames),
                self.frame_ms,
            )
        self.hit_playing = True
        self.hit_frame_index = 0
        self._hit_next_frame_at = now + self.frame_ms
        self._apply_hit_frame(0)
        _tmx_layout_log.debug(
            "Chest hit frame apply profile=%r frame=%d/%d",
            self.profile_id,
            self.hit_frame_index,
            max(len(self.hit_frames) - 1, 0),
        )

    def notify_proximity(self, player_in_range):
        """Call each frame with whether the player is in interaction range."""
        if self.opened:
            return
        if not self.hit_frames:
            if player_in_range != self.was_player_in_range:
                _tmx_layout_log.debug(
                    "Chest proximity profile=%r in_range=%s but hit_frames is empty",
                    self.profile_id,
                    player_in_range,
                )
            self.was_player_in_range = player_in_range
            return

        now = pygame.time.get_ticks()

        if not player_in_range and self.was_player_in_range:
            _tmx_layout_log.debug(
                "Chest proximity exit profile=%r frame_ms=%s",
                self.profile_id,
                self.frame_ms,
            )
            self.hit_playing = False
            self.hit_frame_index = 0
            self._apply_idle()

        if player_in_range and not self.was_player_in_range:
            self._start_hit_animation(now, log_enter=True)

        self.was_player_in_range = player_in_range

        if self.hit_playing and now >= self._hit_next_frame_at:
            self.hit_frame_index += 1
            if self.hit_frame_index >= len(self.hit_frames):
                if player_in_range:
                    _tmx_layout_log.debug(
                        "Chest hit animation loop profile=%r restarting while in proximity",
                        self.profile_id,
                    )
                    self._start_hit_animation(now, log_enter=False)
                else:
                    _tmx_layout_log.debug(
                        "Chest hit animation complete profile=%r returning to idle",
                        self.profile_id,
                    )
                    self.hit_playing = False
                    self.hit_frame_index = 0
                    self._apply_idle()
            else:
                self._apply_hit_frame(self.hit_frame_index)
                _tmx_layout_log.debug(
                    "Chest hit frame apply profile=%r frame=%d/%d",
                    self.profile_id,
                    self.hit_frame_index,
                    max(len(self.hit_frames) - 1, 0),
                )
                self._hit_next_frame_at = now + self.frame_ms

    def update(self, dt=None):
        # Keep chest open animation advancing while opened.
        if self.open_playing:
            self._advance_open(pygame.time.get_ticks())
