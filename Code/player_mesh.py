"""A player drawn as a skinned 3D mesh (Graphics/Meshes/<pack>), draw-only.

The sprite body stays the gameplay body: image, mask, hitbox, hits, feet placement, sitting, collision
and the server's footprint are all the sprite player's, unchanged. This only picks a clip, advances it
and gives the camera a facing. It is NOT `.mesh_boss` (that switches collision to posed capsules and
drops the shadow); the camera draws it from `player.mesh_skin` and blits the sprite if the draw fails
(CPU backend).

Pack clips: `idle`, `move` (one stride, in place), `attack` (tools/boss_sprite_pipeline/player_clips.py).
"""
from __future__ import annotations

import json
import math
import os

from Settings import FPS

# Screen degrees (y down) the 4-way attack statuses point at; the weapon is placed from the same status.
CARDINAL_DEG = {"right": 0.0, "down": 90.0, "left": 180.0, "up": 270.0}
# Model-space heading the rig faces at rest (degrees from +X, Blender Z-up). UniRig / TRELLIS rigs face -Y.
MODEL_FORWARD_DEG = -90.0


def choose_clip(attacking, moving):
    if attacking:
        return "attack"
    return "move" if moving else "idle"


def next_facing(last_deg, dx, dy, attacking, status):
    """Screen heading (degrees, y down). Attacks snap to their 4-way direction so the swing faces the hit;
    standing still (and dash / leap, which zero the direction) keeps the last heading."""
    if attacking:
        base = str(status).split("_")[0]
        if base in CARDINAL_DEG:
            return CARDINAL_DEG[base]
    if dx == 0 and dy == 0:
        return float(last_deg)
    return math.degrees(math.atan2(dy, dx)) % 360.0


def yaw_for_heading(heading_deg, forward_deg=MODEL_FORWARD_DEG):
    """The draw's yaw that turns the model to face `heading_deg` on the ground.

    model_to_ground maps a model direction at angle a, turned by yaw t, to ground angle -(a + t)
    (model +Y is screen up, ground y is screen down). Solving -(a + t) = heading gives t."""
    return (-heading_deg - forward_deg) % 360.0


class PlayerMesh:
    def __init__(self, pack_name, figure_px):
        from mesh_boss import MeshBoss
        import numpy as np

        self.skin = MeshBoss(pack_name, "idle")
        pack = self.skin.pack
        self.forward_deg = float(pack.meta.get("forward_deg", MODEL_FORWARD_DEG))
        clips = {}
        clips_path = os.path.join(pack.root, "clips.json")
        if os.path.isfile(clips_path):
            with open(clips_path, encoding="utf-8") as fh:
                clips = json.load(fh)
        # Size: his rest pose, facing the camera, as tall on screen as the sprite figure (the
        # projection, so the depth of his feet counts as it does in the draw).
        from mesh_boss import project_model_points
        rest = getattr(pack, "rest_pos", None)
        if rest is None:
            rest = np.array([pack.bbox_lo, pack.bbox_hi], dtype=np.float64)
        screen = project_model_points(rest, pack.pivot, yaw_for_heading(90.0, self.forward_deg), 1.0)
        scale = float(figure_px) / max(float(np.ptp(screen[:, 1])), 1e-6)   # screen px per model unit
        self.height_px = scale * pack.height_units               # what MeshBoss.draw takes
        travel = float((clips.get("move") or {}).get("travel_per_frame", 0.0))
        self.px_per_frame = travel * scale                       # ground px walked per move frame
        self.facing_deg = 90.0
        self._attack_time = None

    def update(self, player, dt=None):
        if dt is None or dt <= 0:
            dt = 1.0 / float(FPS)
        attacking = bool(getattr(player, "attacking", False))
        moved = float(getattr(player, "distance_moved", 0.0) or 0.0)
        direction = player.direction
        self.facing_deg = next_facing(self.facing_deg, direction.x, direction.y, attacking, player.status)
        skin = self.skin
        clip = choose_clip(attacking, moved > 0.0)
        if clip == "attack":
            if player.attack_time != self._attack_time:          # a new swing: from its first frame
                self._attack_time = player.attack_time
                skin.set_action("attack")
                skin.frame = 0.0
            lo, hi = skin.pack.ranges[skin.action]
            from Settings import weapon_data
            ms = player.attack_cooldown + weapon_data[player.weapon]["cooldown"]
            skin.advance(dt, fps=(hi - lo + 1) / max(ms / 1000.0, 1e-3), loop=False)
            return
        skin.set_action(clip)
        if clip == "move" and self.px_per_frame > 0:
            skin.advance_frames(moved / self.px_per_frame)        # the stride matches the ground covered
        else:
            skin.advance(dt)

    def yaw_deg(self):
        return yaw_for_heading(self.facing_deg, self.forward_deg)

    # --- worn pieces -------------------------------------------------------------------------
    # A piece (armour slot, loincloth: Graphics/Meshes/<outfit>/<slot>) is a skinned pack on the same skeleton
    # and clips as the body, in the same model space; each pack has its own pivot (its bottom centre). So a
    # piece is drawn about the BODY's pivot, at the body's scale, on the body's frame.
    pieces: dict = {}
    PIECE_CLEAR_PAD = 0.15        # the body clears depth this much wider: pauldrons stick out of his outline

    def set_pieces(self, names):
        """The worn pieces, by pack name; packs are loaded once and kept."""
        from mesh_boss import MeshBoss
        cache = self.__dict__.setdefault("_piece_cache", {})
        pieces = {}
        for name in names:
            if name not in cache:
                try:
                    cache[name] = MeshBoss(name, self.skin.action)
                except Exception as exc:                     # a missing pack: draw the rest
                    import logging
                    logging.getLogger(__name__).warning("piece %r not loaded: %s", name, exc)
                    cache[name] = None
            if cache[name] is not None:
                pieces[name] = cache[name]
        self.pieces = pieces

    def draw(self, backend, feet, light_dir=(-0.4, -0.5, 0.75), ambient=0.35):
        """The body, then each worn piece in its depth. False when the backend has no mesh pass."""
        draw = getattr(backend, "draw_mesh_boss", None)
        if draw is None:
            return False
        from Settings import VIEW_ELEVATION_DEG
        body = self.skin.pack
        yaw = self.yaw_deg()
        scale = self.height_px / max(body.height_units, 1e-6)
        frame = self.skin.frame_index
        if not self.pieces:
            return self.skin.draw(backend, feet, yaw, self.height_px)
        if not draw(body, frame, feet, yaw, scale, VIEW_ELEVATION_DEG, light_dir, ambient,
                    clear_pad=self.PIECE_CLEAR_PAD):
            return False
        action, step = self.skin.action, int(self.skin.frame)
        for piece in self.pieces.values():
            # the body's clip and frame in the clip, looked up in the piece's own ranges (export_outfit.py makes
            # them from one clips blend, so today they are the same numbers)
            lo, hi = piece.pack.ranges.get(action, (frame, frame))
            draw(piece.pack, min(lo + step, hi), feet, yaw, scale, VIEW_ELEVATION_DEG, light_dir, ambient,
                 pivot=body.pivot, clear_depth=False)
        return True
