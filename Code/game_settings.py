from dataclasses import dataclass, field

from Settings import DEBUG_DRAW_FACTION_OUTLINES


@dataclass
class GameSettings:
    """Session-only game settings with discrete, D-pad-friendly values."""

    music_volume_options: list[int] = field(
        default_factory=lambda: [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    )
    sfx_volume_options: list[int] = field(
        default_factory=lambda: [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    )
    environment_speed_options: list[float] = field(
        default_factory=lambda: [0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0]
    )
    fps_cap_options: list[int] = field(
        default_factory=lambda: [30, 45, 60, 75, 90, 120, 144]
    )

    music_volume_index: int = 5  # 50%
    sfx_volume_index: int = 5  # 50%
    environment_speed_index: int = 2  # 1.0x
    fps_cap_index: int = 0  # 30 fps (matches existing default)
    debug_mode: bool = False
    debug_faction_outlines: bool = DEBUG_DRAW_FACTION_OUTLINES
    gold_pickup_popup: bool = True

    MENU_ROWS: tuple[str, ...] = (
        "music_volume",
        "sfx_volume",
        "environment_speed",
        "fps_cap",
        "debug_mode",
        "debug_faction_outlines",
        "gold_pickup_popup",
    )

    @property
    def music_volume(self) -> int:
        return self.music_volume_options[self.music_volume_index]

    @property
    def sfx_volume(self) -> int:
        return self.sfx_volume_options[self.sfx_volume_index]

    @property
    def environment_speed(self) -> float:
        return self.environment_speed_options[self.environment_speed_index]

    @property
    def fps_cap(self) -> int:
        return self.fps_cap_options[self.fps_cap_index]

    def step_left(self, setting_id: str) -> None:
        self._step(setting_id, -1)

    def step_right(self, setting_id: str) -> None:
        self._step(setting_id, 1)

    def activate_row(self, setting_id: str) -> None:
        if setting_id == "debug_mode":
            self.debug_mode = not self.debug_mode
        elif setting_id == "debug_faction_outlines":
            self.debug_faction_outlines = not self.debug_faction_outlines
        elif setting_id == "gold_pickup_popup":
            self.gold_pickup_popup = not self.gold_pickup_popup

    def _step(self, setting_id: str, direction: int) -> None:
        if setting_id == "music_volume":
            self.music_volume_index = self._clamp_index(
                self.music_volume_index + direction, self.music_volume_options
            )
            return
        if setting_id == "sfx_volume":
            self.sfx_volume_index = self._clamp_index(
                self.sfx_volume_index + direction, self.sfx_volume_options
            )
            return
        if setting_id == "environment_speed":
            self.environment_speed_index = self._clamp_index(
                self.environment_speed_index + direction, self.environment_speed_options
            )
            return
        if setting_id == "fps_cap":
            self.fps_cap_index = self._clamp_index(
                self.fps_cap_index + direction, self.fps_cap_options
            )
            return
        if setting_id == "debug_mode" and direction != 0:
            self.debug_mode = not self.debug_mode
            return
        if setting_id == "debug_faction_outlines" and direction != 0:
            self.debug_faction_outlines = not self.debug_faction_outlines
            return
        if setting_id == "gold_pickup_popup" and direction != 0:
            self.gold_pickup_popup = not self.gold_pickup_popup

    def _clamp_index(self, idx: int, options: list) -> int:
        return max(0, min(len(options) - 1, idx))
