from cmath import rect
import logging
import pygame
import os
import math
import collision_core
from hashRect import HashableRect
from game_logging import get_collision_mask_logger
from Support import (
    print_mask,
    position_surface_mask_midbottom_at,
    mask_midbottom_world,
    _mask_opaque_bounds,
)
from Effect import EFFECT_REGISTRY, SlipperyEffect
from benchmark_runtime import BENCHMARK_RUNTIME
from Interaction import InteractionContext
from terrain_height import GRADE_SMOOTH, PHYSICS_GRADIENT_STEP, grade_acceleration
# This is for file (images specifically) importing (This line changes the directory to where the project is saved)
os.chdir(os.path.dirname(os.path.abspath(__file__)))
MAX_DISPLACEMENT = 5.5

# Movement constants
BASE_ACCELERATION = 0.4  # Base acceleration rate (higher = faster acceleration, lower = more control)
DEFAULT_FRICTION = 0.5  # Default friction multiplier for normal movement (0.95 = 5% velocity loss per frame, minimal inertia)
MAX_VELOCITY_MULTIPLIER = 1  # Max velocity can be this much higher than base speed
# While holding input, extra damping when mean surface friction is below DEFAULT (see move())
HELD_SURFACE_DRAG_BLEND = 0.72
# Momentum-aware response gains for input-held movement.
PARALLEL_RESPONSE_GAIN = 1.0  # How strongly velocity magnitude aligns along current momentum axis.
PERP_RESPONSE_GAIN = 1.0  # How strongly velocity can rotate away from current momentum axis.
SLIP_PARALLEL_SUPPRESSION = 0.12  # Mildly reduce along-momentum response on high-slip surfaces.
SLIP_PERP_SUPPRESSION = 0.72  # Strongly reduce turning authority on high-slip surfaces (main drift control).
LOW_SPEED_MOMENTUM_EPS = 0.1  # Use input axis as momentum axis below this speed.

# Ground covered, in pixels, for each frame of a walk cycle. Walk animations advance on
# distance travelled rather than on the clock, so the feet cannot slide: at half speed the
# legs cycle at half rate, and an entity held against a wall stops cycling entirely.
#
# 10 is chosen, not measured: the barb's 19-frame cycle then covers 190px, which at speed 6
# (180 px/s at 30fps) is ~0.95 cycles/sec -- about the cadence of a real walk. Anatomically
# the stride should be ~1.6 body heights, i.e. 83px per cycle and a value near 4, but at
# these speeds that reads as frantic. Lower this for shorter, faster steps.
PIXELS_PER_ANIM_FRAME = 15.0

# A single tick that covers more ground than this was not walking: a spawn, a respawn, a
# level entry, or a remote puppet snapping to its first authoritative position. Those have no
# gait, so they phase nothing -- without this, a puppet placed 781px from its spawn point
# spins its legs through 78 frames in one tick and plants the sprite on an arbitrary pose.
# Legitimate movement stays far below: the fastest speed in Settings is 15, and walls only
# ever shorten a step, so a real tick lands around 21px at the very most.
MAX_PHASED_STEP = 40.0


def _pixel_step(rect, dx, dy):
    """The integer step `rect.x += dx; rect.y += dy` would take (pygame rounds floats)."""
    probe = rect.copy()
    probe.x += dx
    probe.y += dy
    return probe.x - rect.x, probe.y - rect.y

class Entity(pygame.sprite.Sprite):
    casts_shadow = True  # entities (player/enemies/friendlies) drop directional shadows
    # Statuses whose animation is a walk cycle, and so phased on distance rather than time.
    # Declared per subclass because each has its own vocabulary: the player uses bare
    # direction names, enemies and friendlies "move", neutrals "walking". A status missing
    # from here stays on the clock, which is what idle, attack and sit want.
    WALK_STATUSES = frozenset()
    # Class-level variable to keep track of IDs
    id_counter = 0
    benchmark_runtime = BENCHMARK_RUNTIME
    def __init__(self, groups, layout_callback_update_quad_tree = None):
        super().__init__(groups)
        Entity.id_counter += 1
        self.id = Entity.id_counter
        self.frame_index = 0
        self.animation_speed = 0.25
        # Pixels actually covered by the last move(), after collision. Not velocity: an entity
        # shoved by others or held by sub-pixel rounding can carry velocity without moving,
        # and phasing on it would spin the legs while stuck.
        self.distance_moved = 0.0
        self.direction = pygame.math.Vector2()
        self.velocity = pygame.math.Vector2(0, 0)  # Current velocity for movement
        self.weight = 1.0  # Weight affects acceleration (higher weight = slower acceleration)
        self.max_collision_distance_squared = 10000
        self.max_collision_distance = 10
        self.mask = None
        self.anchor_offset = None  # idle feet_y - hitbox.midbottom; captured once at first plant
        # Gravity along the painted slope. Added to velocity after input/friction.
        self.terrain_grade = pygame.math.Vector2(0, 0)
        self.terrain_grade_mag = 0.0
        self.terrain_tilt_deg = 0.0
        self._wall_foot = None  # captured by wall_foot() on first use
        self._wall_tree = None  # the obstacle tree of the last step_against_walls
        self._stuck_at = None  # the last step the walls stopped dead (see step_against_walls)
        # Flag to track whether move method has been called before
        self.move_not_called_before = True
        # Active effects tracking: {effect_area_id: effect_instance}
        self.active_effects = {}
        # Interaction-driven effect state keyed by effect name, e.g. {"slippery": {...}}
        self.effect_state = {}
        self.fire_resistance = 0  # Reduces heat (and future fire) damage; can be set from stats later
        if layout_callback_update_quad_tree :
            self.layout_callback_update_quad_tree = layout_callback_update_quad_tree
        else:
            def empty_func_is_not_nicey(*args, alive = True, remove_existing = True):pass
            self.layout_callback_update_quad_tree  =  empty_func_is_not_nicey

    def capture_feet_anchor(self):
        """Record idle soles vs hitbox.midbottom so planting does not teleport."""
        if not hasattr(self, "hitbox") or getattr(self, "image", None) is None:
            self.anchor_offset = 0
            return
        if getattr(self, "sprite_anchor_px", None) is not None:
            self.anchor_offset = 0  # the manifest anchor *is* the ground contact point
            return
        mask = getattr(self, "mask", None)
        if mask is None:
            mask = pygame.mask.from_surface(self.image)
        feet_y = mask_midbottom_world(self.rect, mask)[1]
        self.anchor_offset = feet_y - self.hitbox.midbottom[1]

    def _frame_anchor_px(self):
        """The ground pixel of the frame being drawn.

        With ``trim: per_frame`` packs every frame is cropped to its own bbox and carries its own
        anchor; otherwise one anchor serves the whole set.
        """
        per_frame = getattr(self, "sprite_frame_anchors", None)
        if per_frame:
            try:
                entry = per_frame[self.status][self.direction_string][int(self.frame_index)]
                return entry["anchor"]
            except (KeyError, IndexError, TypeError, AttributeError):
                pass
        return getattr(self, "sprite_anchor_px", None)

    def plant_sprite_on_hitbox(self):
        """Hang the sprite so opaque feet sit on hitbox.midbottom + anchor_offset.

        Hitbox stays the world-position authority; rect is derived for draw/y-sort.
        """
        if not hasattr(self, "hitbox") or getattr(self, "image", None) is None:
            return
        if self.anchor_offset is None:
            self.capture_feet_anchor()
        anchor = self._frame_anchor_px()
        if anchor is not None:
            # Pre-rendered N-direction sprites: the manifest gives the ground pixel directly, so
            # plant that instead of the mask's lowest row (which the ground shadow moves).
            self.rect = self.image.get_rect(topleft=(
                self.hitbox.midbottom[0] - int(round(anchor[0])),
                self.hitbox.midbottom[1] - int(round(anchor[1])),
            ))
            self.refresh_collision_reach_px()
            return
        mask = getattr(self, "mask", None)
        target = (
            self.hitbox.midbottom[0],
            self.hitbox.midbottom[1] + int(self.anchor_offset or 0),
        )
        self.rect = position_surface_mask_midbottom_at(self.image, mask, target)
        self.refresh_collision_reach_px()

    def refresh_collision_reach_px(self):
        """How tall this body stands above its feet, in screen pixels.

        Also refreshes collision_ground_radius_px for upright sprite capsules.
        """
        mask = getattr(self, "mask", None)
        hitbox = getattr(self, "hitbox", None)
        rect = getattr(self, "rect", None)
        if mask is None or hitbox is None or rect is None:
            self.collision_reach_px = float(getattr(rect, "height", 0) or 0)
        else:
            bounds = _mask_opaque_bounds(mask)
            if bounds is None:
                self.collision_reach_px = float(rect.height)
            else:
                world_top = rect.y + bounds.top
                feet_y = hitbox.midbottom[1]
                self.collision_reach_px = max(0.0, float(feet_y - world_top))

        cfg = getattr(self, "combat_config", None) or {}
        override = cfg.get("collision_ground_radius_px")
        if override is not None:
            self.collision_ground_radius_px = float(override)
            self._ground_radius_src = mask
            return

        if mask is getattr(self, "_ground_radius_src", object()) and hasattr(
            self, "collision_ground_radius_px"
        ):
            return

        if mask is None or rect is None:
            self.collision_ground_radius_px = float(getattr(rect, "width", 0) or 0) / 4.0
            self._ground_radius_src = mask
            return

        bounds = _mask_opaque_bounds(mask)
        if bounds is None:
            self.collision_ground_radius_px = float(rect.width) / 4.0
        else:
            h = max(1, bounds.height // 4)
            band = pygame.Mask((bounds.width, h), fill=True)
            overlap = mask.overlap_mask(band, (bounds.left, bounds.bottom - h))
            rects = overlap.get_bounding_rects()
            width = max((r.width for r in rects), default=0)
            if width > 0:
                self.collision_ground_radius_px = float(width) / 2.0
            else:
                self.collision_ground_radius_px = float(rect.width) / 4.0
        self._ground_radius_src = mask

    def wall_foot(self):
        """The footprint walls collide with: (dx, dy, w, h) relative to hitbox.topleft.

        A ground circle of radius collision_ground_radius_px at the drawn feet
        (hitbox.midbottom + anchor_offset, where plant_sprite_on_hitbox puts them), seen as
        an ellipse. Captured once, so animation frames can't change it, and the server
        rebuilds it exactly from a reported hitbox.
        """
        foot = getattr(self, "_wall_foot", None)
        if foot is None:
            from Settings import VIEW_ELEVATION_DEG

            if getattr(self, "mesh_boss", None) is not None:
                feet_offset = 0  # the mesh boss plants its feet on hitbox.midbottom
            else:
                if getattr(self, "anchor_offset", None) is None:
                    self.capture_feet_anchor()
                feet_offset = int(self.anchor_offset or 0)
            if getattr(self, "collision_ground_radius_px", None) is None:
                self.refresh_collision_reach_px()
            radius = float(getattr(self, "collision_ground_radius_px", 0.0) or 0.0)
            if radius <= 0.0:
                rect = getattr(self, "rect", None)
                radius = float(rect.width) / 4.0 if rect is not None else 8.0
            foot = collision_core.wall_foot_for(
                self.hitbox.size, feet_offset, radius, VIEW_ELEVATION_DEG
            )
            self._wall_foot = foot
        return foot

    def step_against_walls(self, dx, dy, tree):
        """Move the hitbox by the integer step (dx, dy) as far as the walls let the feet go.

        Returns the step actually taken. Remembers `tree` so knockback, which arrives
        without one, blocks on the same walls.

        A step the walls stopped dead stays stopped while nothing changes: the same feet,
        the same step and the same walls skip the checks. A crowd pressing into a wall is
        mostly that, and a stuck step is the most expensive one.
        """
        if tree is not None:
            self._wall_tree = tree
        foot = collision_core.foot_rect(self.hitbox, self.wall_foot())
        key = (tuple(foot), dx, dy, tree, collision_core.walls_version(tree))
        if key == getattr(self, "_stuck_at", None):
            return 0, 0
        took_x, took_y = collision_core.blocked_step(foot, dx, dy, tree)
        stuck = took_x == 0 and took_y == 0 and (dx or dy)
        self._stuck_at = key if stuck else None
        self.hitbox.x += took_x
        self.hitbox.y += took_y
        return took_x, took_y

    def get_collision_reach_px(self):
        reach = getattr(self, "collision_reach_px", None)
        if reach is None:
            self.refresh_collision_reach_px()
            reach = getattr(self, "collision_reach_px", 0.0)
        return float(reach or 0.0)

    #@profile
    def move(self, speed, QuadTree,entity_quad_tree, update_quad_tree = True):

        # Where this tick started, so the walk animation can be phased on ground actually
        # covered. Read before anything moves and compared after collision has had its say.
        move_origin_x, move_origin_y = self.hitbox.x, self.hitbox.y

        #print(f'speed as stated in move method: {speed}')
        #print(f"Quadtree in move method : {entity_quad_tree.manager.item_mapping}")
        #print( f"self.move_not_called_before : {self.move_not_called_before}" )
        remove_existing = not self.move_not_called_before
        #print(f"remove existing : {remove_existing}")
        if update_quad_tree:
            if hasattr(self, 'sprite_type'):
                sprite_type = self.sprite_type
            else:
                sprite_type = None
                
            if hasattr(self, 'mask'):
                mask = self.mask
            else:
                mask = None

            self.layout_callback_update_quad_tree(
                HashableRect(
                    self.rect,
                    self.id,
                    self.direction,
                    sprite_type,
                    mask,
                    owner=self,
                ),
                alive=True,
                remove_existing=remove_existing,
            )
            # Update flag after the first call
            self.move_not_called_before = False
        # if hasattr(self, "type" ): 
        #     if self.type == "player":
        #         print(f"hitbo pre : {self.hitbox}")
        #         print(f"self.animation spee : {self.animation_speed}")
     
        # Normalize direction if not zero
        input_direction = pygame.math.Vector2(0, 0)
        direction_length_sq = self.direction.x * self.direction.x + self.direction.y * self.direction.y
        if direction_length_sq > 0:
            input_direction = self.direction.normalize()
        
        # Surface effects (SlipperyEffect): one monotonic slippery_factor scale.
        # Acceleration: MIN (strictest surface wins when overlapping zones).
        # Friction: arithmetic mean of each active effect's friction mult (avoids product blow-up when zones overlap).
        acceleration_multiplier = 1.0  # Start with normal (1.0)
        friction_samples = []
        
        slippery_state = self.effect_state.get("slippery")
        if slippery_state:
            acc_mult = slippery_state.get("acceleration_multiplier")
            fric_mult = slippery_state.get("friction_multiplier")
            if acc_mult is not None and acc_mult < acceleration_multiplier:
                acceleration_multiplier = acc_mult
            if fric_mult is not None:
                friction_samples.append(fric_mult)
        elif self.active_effects:
            # Backward-compatible fallback while effect-state migration settles.
            for effect in self.active_effects.values():
                acc_mult = effect.get_acceleration_multiplier()
                fric_mult = effect.get_friction_multiplier()
                if acc_mult < acceleration_multiplier:
                    acceleration_multiplier = acc_mult
                friction_samples.append(fric_mult)
        
        if friction_samples:
            friction_multiplier = sum(friction_samples) / len(friction_samples)
        else:
            friction_multiplier = DEFAULT_FRICTION
        
        # Apply input acceleration
        if input_direction.x != 0 or input_direction.y != 0:
            # Momentum-aware input response: split desired change into parallel/perpendicular components.
            # Weight affects response: heavier entities respond slower.
            weight_factor = 1.0 / self.weight  # Inverse relationship
            base_response = BASE_ACCELERATION * weight_factor
            # Derive a slip-strength proxy from mean friction; >DEFAULT means more slip.
            slip_strength = 0.0
            if friction_multiplier > DEFAULT_FRICTION:
                slip_strength = (friction_multiplier - DEFAULT_FRICTION) / max(1e-6, (1.0 - DEFAULT_FRICTION))
                slip_strength = max(0.0, min(1.0, slip_strength))
            parallel_surface_response = acceleration_multiplier * (1.0 - SLIP_PARALLEL_SUPPRESSION * slip_strength)
            perp_surface_response = acceleration_multiplier * (1.0 - SLIP_PERP_SUPPRESSION * slip_strength)
            parallel_gain = base_response * PARALLEL_RESPONSE_GAIN * parallel_surface_response
            perp_gain = base_response * PERP_RESPONSE_GAIN * perp_surface_response
            target_velocity = input_direction * speed * MAX_VELOCITY_MULTIPLIER
            desired_delta = target_velocity - self.velocity
            # Momentum axis is current velocity direction; if too slow, fall back to current input.
            velocity_length_sq = self.velocity.x * self.velocity.x + self.velocity.y * self.velocity.y
            if velocity_length_sq > (LOW_SPEED_MOMENTUM_EPS * LOW_SPEED_MOMENTUM_EPS):
                momentum_axis = self.velocity.normalize()
            else:
                momentum_axis = input_direction
            delta_parallel = momentum_axis * desired_delta.dot(momentum_axis)
            delta_perp = desired_delta - delta_parallel
            self.velocity += (delta_parallel * parallel_gain) + (delta_perp * perp_gain)
            # Continuous drag while pushing if mean friction below DEFAULT; high-slip surfaces skip this.
            if friction_multiplier < DEFAULT_FRICTION - 1e-9:
                r = max(friction_multiplier / DEFAULT_FRICTION, 0.05)
                self.velocity *= (1.0 - HELD_SURFACE_DRAG_BLEND) + HELD_SURFACE_DRAG_BLEND * r
        else:
            # Apply friction when no input: velocity *= friction_multiplier each frame.
            # Higher mult = keep more speed when coasting; lower = lose speed faster.
            self.velocity *= friction_multiplier
            # Stop very small velocities to prevent jitter
            if (self.velocity.x * self.velocity.x + self.velocity.y * self.velocity.y) < 0.01:
                self.velocity = pygame.math.Vector2(0, 0)

        self._apply_terrain_grade()

        # Apply velocity to position: the integer step `hitbox.x += velocity.x` takes (pygame
        # rounds), as far as the walls let the feet go.
        want_x, want_y = _pixel_step(self.hitbox, self.velocity.x, self.velocity.y)
        took_x, took_y = self.step_against_walls(want_x, want_y, QuadTree)
        # A wall that cut the step keeps only the motion it allowed: no pressing into walls,
        # no bounce.
        if took_x != want_x:
            self.velocity.x = float(took_x)
        if took_y != want_y:
            self.velocity.y = float(took_y)

        self.collision(
                        QuadTree=QuadTree ,
                        entity_quad_tree = entity_quad_tree,
                        speed = speed
                        )
        self.distance_moved = math.hypot(self.hitbox.x - move_origin_x,
                                         self.hitbox.y - move_origin_y)
        self.plant_sprite_on_hitbox()

    def _apply_terrain_grade(self):
        """Add downhill gravity from the heightmap. Walk accel already fights it."""
        ax, ay = 0.0, 0.0
        level = getattr(self, "level", None)
        hm = getattr(getattr(level, "layout_manager", None), "heightmap", None)
        if hm is not None:
            sample_xy = None
            if getattr(self, "rect", None) is not None and getattr(self, "mask", None) is not None:
                fx, fy = mask_midbottom_world(self.rect, self.mask)
                if hm.sample(fx, fy) is not None:
                    sample_xy = (fx, fy)
            if sample_xy is None and getattr(self, "hitbox", None) is not None:
                cx, cy = self.hitbox.center
                if hm.sample(cx, cy) is not None:
                    sample_xy = (cx, cy)
            if sample_xy is not None:
                g = hm.gradient(sample_xy[0], sample_xy[1], step=PHYSICS_GRADIENT_STEP)
                ax, ay = grade_acceleration(g)
        s = GRADE_SMOOTH
        self.terrain_grade.x += s * (ax - self.terrain_grade.x)
        self.terrain_grade.y += s * (ay - self.terrain_grade.y)
        self.terrain_grade_mag = (
            self.terrain_grade.x * self.terrain_grade.x
            + self.terrain_grade.y * self.terrain_grade.y
        ) ** 0.5
        self.velocity.x += self.terrain_grade.x
        self.velocity.y += self.terrain_grade.y

    def advance_frame(self):
        """Frames to advance this tick: distance-phased while walking, time-based otherwise.

        Idle, attack and sit stay on the clock. They are not locomotion, so phasing them on
        distance would freeze them the moment the entity stood still.
        """
        if self.status in self.WALK_STATUSES:
            if self.distance_moved > MAX_PHASED_STEP:
                return 0.0  # a teleport, not a stride
            return self.distance_moved / PIXELS_PER_ANIM_FRAME
        return self.animation_speed


    def _collision_mode(self):
        mode = getattr(self.benchmark_runtime, "collision_mode", "simple_swarm")
        if mode in {"legacy", "simple_swarm"}:
            return mode
        return "simple_swarm"

    def _is_simple_swarm_enemy(self, entity=None):
        target = self if entity is None else entity
        return getattr(target, "sprite_type", None) == "enemy"

    def _apply_benchmark_pushback_tuners(self, displacement):
        if self.benchmark_runtime.enabled and self.benchmark_runtime.pushback_floor_enabled:
            if abs(displacement) < self.benchmark_runtime.pushback_min_threshold:
                displacement = 0.0
        if self.benchmark_runtime.enabled and self.benchmark_runtime.pushback_cap_enabled:
            displacement = max(
                -self.benchmark_runtime.pushback_max_cap,
                min(self.benchmark_runtime.pushback_max_cap, displacement),
            )
        return displacement

    def _use_mask_entity_collision_normal(self):
        cfg = getattr(self, "combat_config", None) or {}
        return bool(cfg.get("use_mask_entity_collision_normal", False))

    def _mask_normal_from_overlap_mask(self, self_mask, overlap_mask):
        """Unit push-out normal from overlap pixels; None if degenerate."""
        try:
            cx, cy = overlap_mask.centroid()
        except AttributeError:
            rects = overlap_mask.get_bounding_rects()
            if not rects:
                return None
            br = rects[0]
            cx = br.centerx
            cy = br.centery
        mw, mh = self_mask.get_size()
        scx = mw / 2.0
        scy = mh / 2.0
        nx = scx - cx
        ny = scy - cy
        length = math.sqrt(nx * nx + ny * ny)
        if length < 1e-6:
            return None
        return nx / length, ny / length

    def _apply_mask_collision_min_deflect(self, nx, ny):
        cfg = getattr(self, "combat_config", None) or {}
        min_deg = float(cfg.get("mask_collision_min_deflect_deg", 0) or 0)
        if min_deg <= 0:
            return nx, ny

        direction = getattr(self, "direction", None)
        if direction is None or direction.length_squared() <= 0:
            return nx, ny

        mag = direction.length()
        ax = direction.x / mag
        ay = direction.y / mag
        para = nx * ax + ny * ay
        perp = nx * (-ay) + ny * ax
        min_sin = math.sin(math.radians(min_deg))
        if abs(perp) >= min_sin:
            return nx, ny

        sign = 1 if perp >= 0 else -1
        if abs(perp) < 1e-9:
            sign = 1
        tx = -ay * sign
        ty = ax * sign
        new_nx = para * ax + min_sin * tx
        new_ny = para * ay + min_sin * ty
        length = math.sqrt(new_nx * new_nx + new_ny * new_ny)
        if length < 1e-6:
            return nx, ny
        return new_nx / length, new_ny / length

    def _mask_collision_push_normal(self, self_mask, self_rect, other_mask, other_rect):
        """Single overlap_mask pass: (has_overlap, normal). normal None => rect fallback."""
        dx = other_rect.x - self_rect.x
        dy = other_rect.y - self_rect.y
        try:
            overlap_mask = self_mask.overlap_mask(other_mask, (dx, dy))
        except Exception:
            return False, None
        if overlap_mask.count() == 0:
            return False, None
        raw = self._mask_normal_from_overlap_mask(self_mask, overlap_mask)
        if raw is None:
            return True, None
        return True, self._apply_mask_collision_min_deflect(raw[0], raw[1])

    def _apply_entity_displacement(self, QuadTree, self_rect, self_hitbox, displacement_x, displacement_y):
        # Shoved by another body: as far as the walls let the feet go, never into a wall.
        self.step_against_walls(*_pixel_step(self_hitbox, displacement_x, displacement_y), QuadTree)

    def _resolve_entity_collision_legacy(
        self,
        entity,
        QuadTree,
        self_rect,
        self_hitbox,
        self_mask,
        self_centerx,
        self_centery,
        self_direction_mag,
        self_collision_size,
        displacement_obstacles,
        base_displacement_entities,
        exponent,
    ):
        do_colision = True
        normal = None
        from Settings import VIEW_ELEVATION_DEG
        import body_contact
        E = VIEW_ELEVATION_DEG
        if body_contact.is_mesh(self) or body_contact.is_mesh(entity):
            c = body_contact.mesh_contact(
                body_contact.collision_body(self, E),
                body_contact.collision_body(entity, E),
                E,
            )
            do_colision = c.touching
            normal = (
                self._apply_mask_collision_min_deflect(*c.normal)
                if c.normal
                else None
            )
        elif self_mask and entity.mask:
            entity_rect = entity.rect
            dx = entity_rect.x - self_rect.x
            dy = entity_rect.y - self_rect.y
            if self._use_mask_entity_collision_normal():
                has_overlap, normal = self._mask_collision_push_normal(
                    self_mask, self_rect, entity.mask, entity_rect
                )
                if not has_overlap:
                    do_colision = False
            else:
                if self_mask.overlap_area(entity.mask, (dx, dy)) == 0:
                    do_colision = False

        if do_colision and entity.direction:
            entity_direction_mag = entity.direction.magnitude()
            if entity_direction_mag == 0:
                if normal:
                    nx, ny = normal
                    displacement_x = displacement_obstacles * nx
                    displacement_y = displacement_obstacles * ny
                else:
                    collision_normal = math.atan2(
                        entity.rect.centery - self_centery,
                        entity.rect.centerx - self_centerx,
                    )
                    rebound_angle = collision_normal + math.pi
                    displacement_x = displacement_obstacles * math.cos(rebound_angle)
                    displacement_y = displacement_obstacles * math.sin(rebound_angle)
                self.step_against_walls(
                    *_pixel_step(self_hitbox, displacement_x, displacement_y), QuadTree
                )
                if self.benchmark_runtime.enabled:
                    self.benchmark_runtime.metrics.record_collision_resolved()
            else:
                size_ratio = self_collision_size / (entity.rect.width * entity.rect.height)
                displacement_entities = base_displacement_entities + base_displacement_entities * (
                    1 + math.exp(exponent * (1 - size_ratio))
                )
                relative_velocity = self_direction_mag - entity_direction_mag
                displacement_entities *= (
                    1.5 if relative_velocity > 0 else 0.5 if relative_velocity < 0 else 1
                )
                displacement_entities = self._apply_benchmark_pushback_tuners(
                    displacement_entities
                )
                if normal:
                    nx, ny = normal
                    displacement_x = displacement_entities * nx
                    displacement_y = displacement_entities * ny
                else:
                    direction_dx = self_centerx - entity.rect.centerx
                    direction_dy = self_centery - entity.rect.centery
                    collision_normal = math.atan2(direction_dy, direction_dx)
                    displacement_x = displacement_entities * math.cos(collision_normal)
                    displacement_y = displacement_entities * math.sin(collision_normal)
                self._apply_entity_displacement(
                    QuadTree, self_rect, self_hitbox, displacement_x, displacement_y
                )
                if self.benchmark_runtime.enabled and displacement_entities != 0:
                    self.benchmark_runtime.metrics.record_collision_resolved()

    def _resolve_entity_collisions_legacy(
        self,
        nearby_entities,
        QuadTree,
        self_rect,
        self_hitbox,
        self_mask,
        self_centerx,
        self_centery,
        self_direction_mag,
        self_collision_size,
        displacement_obstacles,
        base_displacement_entities,
        exponent,
    ):
        for entity in nearby_entities:
            self._resolve_entity_collision_legacy(
                entity,
                QuadTree,
                self_rect,
                self_hitbox,
                self_mask,
                self_centerx,
                self_centery,
                self_direction_mag,
                self_collision_size,
                displacement_obstacles,
                base_displacement_entities,
                exponent,
            )

    def _resolve_entity_collisions_simple(
        self,
        nearby_entities,
        QuadTree,
        self_rect,
        self_hitbox,
        self_centerx,
        self_centery,
        self_direction_mag,
        self_collision_size,
        displacement_obstacles,
        base_displacement_entities,
        exponent,
    ):
        neighbor_limit = max(
            1, int(getattr(self.benchmark_runtime, "simple_swarm_neighbor_limit", 4) or 4)
        )
        enemy_neighbors = []

        for entity in nearby_entities:
            if not self._is_simple_swarm_enemy(entity):
                self._resolve_entity_collision_legacy(
                    entity,
                    QuadTree,
                    self_rect,
                    self_hitbox,
                    self.mask,
                    self_centerx,
                    self_centery,
                    self_direction_mag,
                    self_collision_size,
                    displacement_obstacles,
                    base_displacement_entities,
                    exponent,
                )
                continue

            dx = self_centerx - entity.rect.centerx
            dy = self_centery - entity.rect.centery
            dist_sq = dx * dx + dy * dy
            enemy_neighbors.append((dist_sq, dx, dy, entity))

        enemy_neighbors.sort(key=lambda item: item[0])
        for dist_sq, dx, dy, entity in enemy_neighbors[:neighbor_limit]:
            self_radius = max(self_rect.width, self_rect.height) * 0.35
            entity_radius = max(entity.rect.width, entity.rect.height) * 0.35
            target_distance = self_radius + entity_radius

            if dist_sq == 0:
                dx = 1.0
                dy = 0.0
                dist_sq = 1.0

            if dist_sq >= target_distance * target_distance:
                continue

            distance = math.sqrt(dist_sq)
            if distance == 0:
                distance = 1.0

            overlap = max(0.0, target_distance - distance)
            relative_velocity = self_direction_mag - entity.direction.magnitude()
            displacement_entities = base_displacement_entities + (overlap * 0.35)
            displacement_entities *= (
                1.35 if relative_velocity > 0 else 0.65 if relative_velocity < 0 else 1.0
            )
            displacement_entities = self._apply_benchmark_pushback_tuners(
                displacement_entities
            )
            if displacement_entities == 0:
                continue

            normal = None
            if (
                self._use_mask_entity_collision_normal()
                and self.mask
                and entity.mask
            ):
                _, normal = self._mask_collision_push_normal(
                    self.mask, self_rect, entity.mask, entity.rect
                )
            if normal:
                normal_x, normal_y = normal
            else:
                normal_x = dx / distance
                normal_y = dy / distance
            displacement_x = displacement_entities * normal_x
            displacement_y = displacement_entities * normal_y
            self._apply_entity_displacement(
                QuadTree, self_rect, self_hitbox, displacement_x, displacement_y
            )
            if self.benchmark_runtime.enabled:
                self.benchmark_runtime.metrics.record_collision_resolved()

    def _entity_entity_push_params(self):
        cfg = getattr(self, "combat_config", None) or {}
        return (
            cfg.get("entity_collision_push_static", 1),
            cfg.get("entity_collision_push_moving", 1.1),
        )

    #@profile
    def collision(self, QuadTree, entity_quad_tree, speed = 0):
        """
        Entity-to-entity bumping. Walls are not handled here: move() has already stepped
        the feet against them (step_against_walls), and every shove below goes through
        step_against_walls too, so a bump can never push you into a wall.

            if entity is stationary , consider the collision like into a wall
                 TODO, they should take some impact depending on size

            if the entity is moving, we do some basic calcs about increasing rebound based on relative velocity
            but we just rebound on the normal of the collision , rbound is larger if the entity is bigger

        `speed` is unused now that walls block instead of pushing back; kept for callers.
            """

        displacement_obstacles, base_displacement_entities = self._entity_entity_push_params()
        exponent = 4

        self_rect = self.rect
        self_hitbox = self.hitbox
        self_mask = self.mask
        self_centerx = self_rect.centerx
        self_centery = self_rect.centery
        self_direction = self.direction
        self_direction_mag = self_direction.magnitude()
        player_size_scale = 3.5 if getattr(self, "type", None) == "player" else 1.0
        self_collision_size = (self_rect.width * self_rect.height) * player_size_scale
        query_self = HashableRect(self_rect, self.id)
        nearby_entities = entity_quad_tree.hit(query_self)

        if self._collision_mode() == "simple_swarm" and self._is_simple_swarm_enemy():
            self._resolve_entity_collisions_simple(
                nearby_entities,
                QuadTree,
                self_rect,
                self_hitbox,
                self_centerx,
                self_centery,
                self_direction_mag,
                self_collision_size,
                displacement_obstacles,
                base_displacement_entities,
                exponent,
            )
            return

        self._resolve_entity_collisions_legacy(
            nearby_entities,
            QuadTree,
            self_rect,
            self_hitbox,
            self_mask,
            self_centerx,
            self_centery,
            self_direction_mag,
            self_collision_size,
            displacement_obstacles,
            base_displacement_entities,
            exponent,
        )



    def check_effects(self, effect_quad_trees, effect_cell_grid=None):
        """
        Check if entity is colliding with any effect areas.
        Effects don't block movement - they just detect presence and apply properties.
        Uses two-phase collision: broad phase (rect) then narrow phase (mask-on-mask).
        Same pattern as entity/obstacle collisions for consistency.
        """
        if not effect_quad_trees:
            return

        if not self.active_effects and effect_cell_grid is not None:
            if not effect_cell_grid.intersects_rect(self.rect):
                return

        _mask_log = get_collision_mask_logger()

        # Track currently colliding effect instances (area + effect key)
        current_effect_instance_ids = set()
        
        # BROAD PHASE: Use rect for quad tree query (same as entity/obstacle collisions)
        entity_rect = HashableRect(self.rect, self.id)
        
        # Check each effect layer's quad tree
        for layer_name, effect_tree in effect_quad_trees.items():
            nearby_effects = effect_tree.hit(entity_rect)
            
            # NARROW PHASE: For each nearby effect, check mask-on-mask collision
            for effect_area in nearby_effects:
                do_collision = True  # Assume collision from broad phase

                if _mask_log.isEnabledFor(logging.DEBUG):
                    parts = [
                        "Effect collision - self.mask: %s, effect_area.mask: %s"
                        % (self.mask is not None, getattr(effect_area, "mask", None) is not None),
                    ]
                    if self.mask:
                        parts.append("  self.mask size: %s" % (self.mask.get_size(),))
                    if hasattr(effect_area, "mask") and effect_area.mask:
                        parts.append(
                            "  effect_area.mask size: %s" % (effect_area.mask.get_size(),)
                        )
                    _mask_log.debug("\n".join(parts))

                # If both have masks, do precise mask-on-mask check (same as entity collisions)
                if self.mask and effect_area.mask:
                    # Calculate offset using rect positions (same as entity collisions)
                    # IMPORTANT: Both masks are created from surfaces starting at (0,0)
                    # The rect positions represent where those surfaces are in world space
                    dx = effect_area.rect.x - self.rect.x
                    dy = effect_area.rect.y - self.rect.y

                    if _mask_log.isEnabledFor(logging.DEBUG):
                        entity_mask_size = self.mask.get_size()
                        effect_mask_size = effect_area.mask.get_size()
                        parts = [
                            "  Entity rect: %s (x=%s, y=%s, w=%s, h=%s)"
                            % (
                                self.rect,
                                self.rect.x,
                                self.rect.y,
                                self.rect.width,
                                self.rect.height,
                            ),
                            "  Effect rect: %s (x=%s, y=%s, w=%s, h=%s)"
                            % (
                                effect_area.rect,
                                effect_area.rect.x,
                                effect_area.rect.y,
                                effect_area.rect.width,
                                effect_area.rect.height,
                            ),
                            "  Entity mask size: %s, Effect mask size: %s"
                            % (entity_mask_size, effect_mask_size),
                            "  Entity rect size: (%s, %s), Effect rect size: (%s, %s)"
                            % (
                                self.rect.width,
                                self.rect.height,
                                effect_area.rect.width,
                                effect_area.rect.height,
                            ),
                            "  Offset (dx, dy): (%s, %s)" % (dx, dy),
                        ]
                        if entity_mask_size != (self.rect.width, self.rect.height):
                            parts.append(
                                "  WARNING: Entity mask size %s != rect size (%s, %s)"
                                % (
                                    entity_mask_size,
                                    self.rect.width,
                                    self.rect.height,
                                )
                            )
                        if effect_mask_size != (
                            effect_area.rect.width,
                            effect_area.rect.height,
                        ):
                            parts.append(
                                "  WARNING: Effect mask size %s != rect size (%s, %s)"
                                % (
                                    effect_mask_size,
                                    effect_area.rect.width,
                                    effect_area.rect.height,
                                )
                            )
                        _mask_log.debug("\n".join(parts))

                    overlap = self.mask.overlap_area(effect_area.mask, (dx, dy))

                    if _mask_log.isEnabledFor(logging.DEBUG):
                        reverse_overlap = effect_area.mask.overlap_area(
                            self.mask, (-dx, -dy)
                        )
                        _mask_log.debug(
                            "  Mask overlap check - dx: %s, dy: %s, overlap: %s",
                            dx,
                            dy,
                            overlap,
                        )
                        _mask_log.debug(
                            "  Reverse overlap check (effect->entity): overlap: %s",
                            reverse_overlap,
                        )

                    if overlap == 0:
                        do_collision = False  # No overlap, no collision
                        if _mask_log.isEnabledFor(logging.DEBUG):
                            _mask_log.debug(
                                "  Mask filter worked - no collision (overlap == 0)"
                            )
                    else:
                        if _mask_log.isEnabledFor(logging.DEBUG):
                            _mask_log.debug(
                                "  Mask collision confirmed - overlap: %s pixels, effect_id: %s",
                                overlap,
                                effect_area._id,
                            )
                else:
                    if _mask_log.isEnabledFor(logging.DEBUG):
                        _mask_log.debug(
                            "  Skipping mask check for effect - using rect collision"
                        )

                if do_collision:
                    effect_area_id = effect_area._id

                    # Allow mixed effect areas: process each matching registry key independently.
                    for prop_key, effect_class in EFFECT_REGISTRY.items():
                        if prop_key not in effect_area.properties:
                            continue
                        effect_instance_id = (effect_area_id, prop_key)
                        current_effect_instance_ids.add(effect_instance_id)

                        if _mask_log.isEnabledFor(logging.DEBUG):
                            _mask_log.debug(
                                "  Effect instance in current set: %s", effect_instance_id
                            )

                        if effect_instance_id not in self.active_effects:
                            effect_instance = effect_class(effect_area.properties)
                            self.active_effects[effect_instance_id] = effect_instance
                            effect_instance.apply(self)
                            self._emit_effect_state_interaction(
                                effect_key=prop_key,
                                phase="begin",
                                effect_instance=effect_instance,
                                effect_area_id=effect_area_id,
                            )
                            if _mask_log.isEnabledFor(logging.DEBUG):
                                _mask_log.debug(
                                    "  Effect APPLIED: %s, velocity: %s",
                                    effect_instance_id,
                                    self.velocity,
                                )
                        else:
                            effect_instance = self.active_effects[effect_instance_id]
                            self._emit_effect_state_interaction(
                                effect_key=prop_key,
                                phase="tick",
                                effect_instance=effect_instance,
                                effect_area_id=effect_area_id,
                            )
        
        # Remove effects that are no longer colliding
        effects_to_remove = []
        for effect_instance_id, effect_instance in self.active_effects.items():
            if effect_instance_id not in current_effect_instance_ids:
                # Check if effect should persist after exit
                if not effect_instance.should_persist_after_exit():
                    effect_instance.remove(self)
                    effect_area_id, effect_key = effect_instance_id
                    self._emit_effect_state_interaction(
                        effect_key=effect_key,
                        phase="end",
                        effect_instance=effect_instance,
                        effect_area_id=effect_area_id,
                    )
                    effects_to_remove.append(effect_instance_id)
                    if _mask_log.isEnabledFor(logging.DEBUG):
                        _mask_log.debug(
                            "  Effect REMOVED: %s (no longer colliding, velocity: %s)",
                            effect_instance_id,
                            self.velocity,
                        )
        
        # Remove effects that shouldn't persist
        for effect_instance_id in effects_to_remove:
            del self.active_effects[effect_instance_id]
        
        if _mask_log.isEnabledFor(logging.DEBUG):
            if self.active_effects:
                _mask_log.debug(
                    "  Active effects after cleanup: %s, velocity: %s",
                    list(self.active_effects.keys()),
                    self.velocity,
                )
            elif effects_to_remove:
                _mask_log.debug(
                    "  All effects removed, velocity: %s", self.velocity
                )

    def apply_environmental_damage(self, dt):
        """Apply damage from active effects that provide environmental damage (e.g. heat)."""
        #print(f"applying environmental damage")
        #print(self.active_effects)
        resolver = self._get_interaction_resolver()
        for (effect_area_id, effect_key), effect in self.active_effects.items():
            if hasattr(effect, 'get_environmental_damage'):
                result = effect.get_environmental_damage(self, dt)
                if result:
                    amount, damage_type = result
                    if amount > 0:
                        ctx = InteractionContext(
                            kind="damage",
                            source_kind="environment",
                            source=effect,
                            owner=None,
                            source_team="environment",
                            target=self,
                            amount=amount,
                            attack_type=damage_type,
                            effect_key=effect_key,
                            effect_area_id=effect_area_id,
                            tags={"environment", effect_key},
                        )
                        if resolver is not None:
                            resolver.apply(ctx)
                        elif self.can_receive_interaction(ctx):
                            self.receive_interaction(ctx)

    def _get_interaction_resolver(self):
        if hasattr(self, "level") and hasattr(self.level, "interaction_resolver"):
            return self.level.interaction_resolver
        return None

    def _emit_effect_state_interaction(self, effect_key, phase, effect_instance, effect_area_id):
        ctx = InteractionContext(
            kind="effect_state",
            source_kind="environment",
            source=effect_instance,
            owner=None,
            source_team="environment",
            target=self,
            phase=phase,
            effect_key=effect_key,
            effect_area_id=effect_area_id,
            tags={"environment", "effect_state", effect_key, phase},
        )
        resolver = self._get_interaction_resolver()
        if resolver is not None:
            resolver.apply(ctx)
        elif self.can_receive_interaction(ctx):
            self.receive_interaction(ctx)

    def take_environmental_damage(self, amount, damage_type):
        """Override in subclasses that have health. Base Entity does nothing."""
        pass

    def can_receive_interaction(self, ctx: InteractionContext):
        if ctx.kind == "effect_state":
            return True
        if ctx.kind == "impulse":
            if "friendly_fire_impulse" in ctx.tags:
                return True
            if ctx.source_team is not None and ctx.source_team == getattr(self, "team_id", None):
                return False
            return True
        return True

    def cancel_displacement_abilities(self) -> None:
        for attr in ("_dash_runtime", "_leap_runtime"):
            runtime = getattr(self, attr, None)
            if runtime is None:
                continue
            ability = runtime.get("_ability")
            if ability is not None and hasattr(ability, "_end"):
                ability._end(self, runtime)
            else:
                setattr(self, attr, None)

    def apply_impulse(self, force, follow_through=0.5) -> None:
        self.cancel_displacement_abilities()
        if force is None:
            return
        if not hasattr(self, "velocity"):
            self.velocity = pygame.math.Vector2(0, 0)
        dx = float(force[0]) if hasattr(force, "__getitem__") else float(force.x)
        dy = float(force[1]) if hasattr(force, "__getitem__") else float(force.y)
        if hasattr(self, "hitbox"):
            tree = getattr(self, "_wall_tree", None)
            if tree is not None:
                # Knocked back against the walls it last moved among: never into one.
                self.step_against_walls(int(dx), int(dy), tree)
            else:
                self.hitbox.x += int(dx)
                self.hitbox.y += int(dy)
        self.plant_sprite_on_hitbox()
        self.velocity.x += dx * follow_through
        self.velocity.y += dy * follow_through

    def receive_interaction(self, ctx: InteractionContext):
        if ctx.kind == "impulse":
            force = pygame.math.Vector2(ctx.impulse_x or 0, ctx.impulse_y or 0)
            follow_through = 0.5
            if ctx.source is not None:
                follow_through = float(getattr(ctx.source, "impulse_follow_through", 0.5))
            self.apply_impulse(force, follow_through=follow_through)
            return
        if ctx.kind == "effect_state":
            effect_key = ctx.effect_key
            if not effect_key:
                return
            phase = ctx.phase or "tick"
            if phase == "end":
                self.effect_state.pop(effect_key, None)
                return
            payload = {"phase": phase, "source": ctx.source}
            if effect_key == "slippery" and isinstance(ctx.source, SlipperyEffect):
                payload["acceleration_multiplier"] = ctx.source.get_acceleration_multiplier()
                payload["friction_multiplier"] = ctx.source.get_friction_multiplier()
            self.effect_state[effect_key] = payload
            return
        return

    def line_rect_intersection(start_point, end_point, rect):
        x1, y1 = start_point
        x2, y2 = end_point
    
        # Determine the side of the rectangle the line intersects with
        if x1 < rect.left:  # Intersection with left side
            x = rect.left
            y = y1 + (y2 - y1) * (x - x1) / (x2 - x1)
        elif x1 > rect.right:  # Intersection with right side
            x = rect.right
            y = y1 + (y2 - y1) * (x - x1) / (x2 - x1)
        elif y1 < rect.top:  # Intersection with top side
            y = rect.top
            x = x1 + (x2 - x1) * (y - y1) / (y2 - y1)
        else:  # Intersection with bottom side
            y = rect.bottom
            x = x1 + (x2 - x1) * (y - y1) / (y2 - y1)
    
        return x, y
          
              
    def wave_value(self):
        value = sin(pygame.time.get_ticks())
        if value >= 0:
            return 255
        else:
            return 0
