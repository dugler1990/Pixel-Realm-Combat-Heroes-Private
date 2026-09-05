from cmath import rect
import logging
import pygame
import os
import math
import collision_core
from hashRect import HashableRect
from game_logging import get_collision_mask_logger
from Support import print_mask, position_surface_mask_midbottom_at, mask_midbottom_world
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
# Legitimate movement stays far below: the fastest speed in Settings is 15, and collision
# pushback is capped at MAX_DISPLACEMENT, so a real tick lands around 21px at the very most.
MAX_PHASED_STEP = 40.0

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
        # Pixels actually covered by the last move(), after collision. Not velocity: nothing
        # in collision() clears velocity, so an entity pressed against a wall keeps a full
        # velocity vector forever and phasing on it would spin the legs while stuck.
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
        self._collision_probe_rect = pygame.Rect(0, 0, 1, 1)
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
        mask = getattr(self, "mask", None)
        if mask is None:
            mask = pygame.mask.from_surface(self.image)
        feet_y = mask_midbottom_world(self.rect, mask)[1]
        self.anchor_offset = feet_y - self.hitbox.midbottom[1]

    def plant_sprite_on_hitbox(self):
        """Hang the sprite so opaque feet sit on hitbox.midbottom + anchor_offset.

        Hitbox stays the world-position authority; rect is derived for draw/y-sort.
        """
        if not hasattr(self, "hitbox") or getattr(self, "image", None) is None:
            return
        if self.anchor_offset is None:
            self.capture_feet_anchor()
        mask = getattr(self, "mask", None)
        target = (
            self.hitbox.midbottom[0],
            self.hitbox.midbottom[1] + int(self.anchor_offset or 0),
        )
        self.rect = position_surface_mask_midbottom_at(self.image, mask, target)

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
        
        
        
            self.layout_callback_update_quad_tree(HashableRect(self.rect,
                                                               self.id,
                                                               self.direction,
                                                               sprite_type,
                                                               mask),
                                                  alive = True,
                                                  remove_existing = remove_existing)
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
        
        # Apply velocity to position
        self.hitbox.x += self.velocity.x
        self.hitbox.y += self.velocity.y
        
        
        # if hasattr(self, "type" ): 
        #     if self.type == "player":
        #         print(f"hitbo pre : {self.hitbox}")
     
        
        #self.collision("Vertical",QuadTree=QuadTree)
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

    def _use_mask_obstacle_collision_normal(self):
        cfg = getattr(self, "combat_config", None) or {}
        return bool(cfg.get("use_mask_obstacle_collision_normal", False))

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
        new_left = self_hitbox.left + displacement_x
        new_top = self_hitbox.top + displacement_y

        self._collision_probe_rect.update(new_left, new_top, self_hitbox.width, self_hitbox.height)
        obstacles_hit = QuadTree.hit(HashableRect(self._collision_probe_rect, self.id))
        if obstacles_hit:
            obstacle = next(iter(obstacles_hit))
            if self_rect.left < obstacle.left:
                self_hitbox.right = obstacle.left
                self_hitbox.top = new_top
            elif self_rect.left > obstacle.right:
                self_hitbox.left = obstacle.right
                self_hitbox.top = new_top
            elif self_rect.top < obstacle.top:
                self_hitbox.bottom = obstacle.top
                self_hitbox.left = new_left
            else:
                self_hitbox.top = obstacle.bottom
                self_hitbox.left = new_left
        else:
            self_hitbox.left += displacement_x
            self_hitbox.top += displacement_y

    def _resolve_obstacle_collisions(
        self,
        nearby_obstacles,
        self_rect,
        self_hitbox,
        self_mask,
        self_centerx,
        self_centery,
        speed,
        mask_log,
    ):
        displacement_obstacles = 1
        total_displacement_x = 0
        total_displacement_y = 0
        max_penetration_depth = 0

        for obstacle in nearby_obstacles:
            do_collision = True
            normal = None

            if mask_log.isEnabledFor(logging.DEBUG):
                parts = [
                    "Obstacle collision - self.mask: %s, obstacle.mask: %s"
                    % (self.mask is not None, getattr(obstacle, "mask", None) is not None),
                ]
                if self.mask:
                    parts.append("  self.mask size: %s" % (self.mask.get_size(),))
                if hasattr(obstacle, "mask") and obstacle.mask:
                    parts.append("  obstacle.mask size: %s" % (obstacle.mask.get_size(),))
                mask_log.debug("\n".join(parts))

            obstacle_rect = obstacle.rect
            if self_mask and obstacle.mask:
                dx = obstacle_rect.x - self_rect.x
                dy = obstacle_rect.y - self_rect.y

                if mask_log.isEnabledFor(logging.DEBUG):
                    entity_mask_size = self_mask.get_size()
                    entity_rect_size = (self_rect.width, self_rect.height)
                    obstacle_mask_size = obstacle.mask.get_size()
                    obstacle_rect_size = (obstacle_rect.width, obstacle_rect.height)
                    parts = [
                        "  Entity rect: %s (x=%s, y=%s, w=%s, h=%s)"
                        % (self_rect, self_rect.x, self_rect.y, self_rect.width, self_rect.height),
                        "  Obstacle rect: %s (x=%s, y=%s, w=%s, h=%s)"
                        % (
                            obstacle_rect,
                            obstacle_rect.x,
                            obstacle_rect.y,
                            obstacle_rect.width,
                            obstacle_rect.height,
                        ),
                        "  Entity mask size: %s, Entity rect size: %s"
                        % (entity_mask_size, entity_rect_size),
                        "  Obstacle mask size: %s, Obstacle rect size: %s"
                        % (obstacle_mask_size, obstacle_rect_size),
                    ]
                    if entity_mask_size != entity_rect_size:
                        parts.append(
                            "  WARNING: Entity mask size %s != rect size %s"
                            % (entity_mask_size, entity_rect_size)
                        )
                    if obstacle_mask_size != obstacle_rect_size:
                        parts.append(
                            "  WARNING: Obstacle mask size %s != rect size %s"
                            % (obstacle_mask_size, obstacle_rect_size)
                        )
                    parts.append("  Offset (dx, dy): (%s, %s)" % (dx, dy))
                    mask_log.debug("\n".join(parts))

                if self._use_mask_obstacle_collision_normal():
                    has_overlap, normal = self._mask_collision_push_normal(
                        self_mask, self_rect, obstacle.mask, obstacle_rect
                    )
                    if mask_log.isEnabledFor(logging.DEBUG):
                        mask_log.debug(
                            "  Mask overlap check - dx: %s, dy: %s, overlap: %s",
                            dx,
                            dy,
                            has_overlap,
                        )
                    if not has_overlap:
                        do_collision = False
                        if mask_log.isEnabledFor(logging.DEBUG):
                            mask_log.debug("  Mask filter worked - no collision (overlap == 0)")
                    elif mask_log.isEnabledFor(logging.DEBUG):
                        mask_log.debug("  Mask collision confirmed")
                else:
                    overlap = self_mask.overlap_area(obstacle.mask, (dx, dy))

                    if mask_log.isEnabledFor(logging.DEBUG):
                        mask_log.debug(
                            "  Mask overlap check - dx: %s, dy: %s, overlap: %s", dx, dy, overlap
                        )

                    if overlap == 0:
                        do_collision = False
                        if mask_log.isEnabledFor(logging.DEBUG):
                            mask_log.debug("  Mask filter worked - no collision (overlap == 0)")
                    else:
                        if mask_log.isEnabledFor(logging.DEBUG):
                            mask_log.debug(
                                "  Mask collision confirmed - overlap: %s pixels", overlap
                            )
                    normal = None
            else:
                if mask_log.isEnabledFor(logging.DEBUG):
                    mask_log.debug("  Skipping mask check - using rect collision")

            if do_collision:
                # Push-out math lives in collision_core so the headless server
                # runs the IDENTICAL rect resolution (multiplayer plan, Stage B2).
                penetration_depth = collision_core.rect_penetration(self_rect, obstacle_rect)
                if normal:
                    total_displacement_x += normal[0]
                    total_displacement_y += normal[1]
                else:
                    rebound_dx, rebound_dy = collision_core.rect_rebound_dir(self_rect, obstacle_rect)
                    total_displacement_x += rebound_dx
                    total_displacement_y += rebound_dy
                max_penetration_depth = max(max_penetration_depth, penetration_depth)

        scaled_x, scaled_y = collision_core.finalize_pushout(
            total_displacement_x, total_displacement_y, max_penetration_depth,
            speed, displacement_obstacles,
        )
        self_hitbox.left += scaled_x
        self_hitbox.top += scaled_y

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
        if self_mask and entity.mask:
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
                self_hitbox.left += displacement_x
                self_hitbox.top += displacement_y
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
    def collision(self, QuadTree, entity_quad_tree, speed = 0):# Speed is just to adjust displacement when colliding with objects so you dont go through
                                                                  # Maybe i should do the same with entity collisions.
        
        """
        Issues with this function : i have a bunch of conditions and each one actually
        moved the player, as opposed to keeping track of a displacement, 
        this is because if there is a collision and then we notice a obstacle collision of the deflection of that 
        collision, we do not make the movement change in terms of displacement, we use the obstacle 
        boundry. We could surely fix this but this is just so that you dont get too lost.
        
        explanation of function 
        
        check collisions with any obstacles, if that happens, thats all that happens, 
        
        if there are no imediate obstacle collisions, check entity collisions, 
        
            if entity is stationary , consider the collision like into a wall
                 TODO, they should take some impact depending on size
                 
            if the entity is moving, we do some basic calcs about increasing rebound based on relative velocity
            but we just rebound on the normal of the collision , rbound is larger if the entity is bigger
            
            if rebounding from an entity would result in you colliding with an object, you appear at theb oundry of the object
            im still worrid you could get hit simultansouly by a bunch of entites and go through an obstacle
            lets see.
            
            seems to work ok , being in a corner ( secondary collision with vertical and horizontal wall can go wrong.)
            
            would be cool if there was some dampening some how, like, at the moment if you get stuck in a corner
            you bound around like crazy, would be nice if... you needed speed for that, i dno.
        
        
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
        nearby_obstacles = QuadTree.hit(query_self)
        nearby_entities = entity_quad_tree.hit(query_self)
        mask_log = get_collision_mask_logger()

        self._resolve_obstacle_collisions(
            nearby_obstacles,
            self_rect,
            self_hitbox,
            self_mask,
            self_centerx,
            self_centery,
            speed,
            mask_log,
        )

        if nearby_obstacles:
            return

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



    #@profile
    def collision__(self, QuadTree, entity_quad_tree):
        # Define displacement for collision resolution with obstacles
        displacement_obstacles = 20  # Adjust this value as needed
        
        # Define base displacement for entity collisions
        base_displacement_entities = 10  # Adjust this value as needed
        exponent = 3 # Adjust this exponent for the desired relationship
        
        # Check for nearby obstacles using the QuadTree
        nearby_obstacles = QuadTree.hit(HashableRect(self.rect, self.id))
        nearby_entities = entity_quad_tree.hit(HashableRect(self.rect, self.id))
        
        # Iterate over nearby obstacles (walls)
        for obstacle in nearby_obstacles:
            # Calculate the angle of collision relative to the entity's movement direction
            angle_radians = math.atan2(self.direction.y, self.direction.x)
            angle_degrees = math.degrees(angle_radians)
            
            # Calculate the angle between the entity's direction and the collision normal
            collision_normal = math.atan2(obstacle.rect.centery - self.rect.centery, obstacle.rect.centerx - self.rect.centerx)
            
            # Calculate the rebound angle (opposite angle)
            rebound_angle = collision_normal + math.pi 
            
            # Adjust the position of the entity based on the rebound angle for obstacles
            self.hitbox.left += displacement_obstacles * math.cos(rebound_angle)
            self.hitbox.top += displacement_obstacles * math.sin(rebound_angle)
        
        # If not colliding with a wall, handle entity collisions
        if not nearby_obstacles:
            for entity in nearby_entities:
                # Calculate the size ratio of the colliding entities (for example, based on widths)
                
                #print(f"size ratio : {size_ratio}")
                # Calculate the displacement based on the size ratio and apply it for entities
                
                
                if hasattr(self,'type'):
                    if self.type == "player" :
                        self_size = self.rect.width*20
                        #print(self.rect.size)
                    else: self_size = self.rect.width
                        #print(f"entity.direction: {entity.direction}")
                size_ratio = self_size / entity.rect.width
                
                displacement_entities = base_displacement_entities + base_displacement_entities * (1 + math.exp(-exponent * (1 - size_ratio)))
                #print(displacement_entities)
                # Calculate relative velocity (speed) between the entities
                relative_velocity = self.direction.magnitude() - entity.direction.magnitude()
                # Calculate the direction vector from the other entity to self
                
                
                
                
                
                #### Here if the other entity is stationary, we just get the direction of self as with wall
                #     Regardless, this must be what is going wrong.
                
                direction_vector = pygame.math.Vector2(self.rect.center) - pygame.math.Vector2(entity.rect.center)
                
                # Calculate the angle between the direction vector and the collision normal
                collision_normal = math.atan2(direction_vector.y, direction_vector.x)
                
                # Calculate the rebound angle based on the collision normal and relative velocity
                rebound_angle = collision_normal + math.pi
               # # Adjust the displacement based on the relative velocity
                # if relative_velocity > 0:  # Entities are moving towards each other
                #     displacement_entities *= 1.5  # Increase displacement
                # elif relative_velocity < 0:  # Entities are moving away from each other
                #     displacement_entities *= 0.5  # Decrease displacement
                
                
                displacement_y = displacement_entities * math.sin(rebound_angle)
                displacement_x = displacement_entities * math.cos(rebound_angle)
                     
                    # if math.sin(rebound_angle) > 0:
                    #     displacement_y *= -1
                    
                    # # # Adjust displacement_x based on the sign of math.cos(rebound_angle)
                    # if math.cos(rebound_angle) > 0:
                    #     displacement_x *= -1
               
                    # #displacement_x *= abs(math.sin(collision_normal))
                    # #displacement_y *= abs(math.cos(collision_normal))
           
                # Determine which vertex to adjust based on the rebound angle
                #if rebound_angle < math.pi:  
                #new_left = self.rect.left + displacement_x
                #new_top = self.rect.top + displacement_y
                #else:  # Collision from the left or above
                #    new_left = self.rect.left - displacement_x
                #    new_top = self.rect.top - displacement_y            
               
                # new_left = self.rect.left + displacement_x
                # new_top = self.rect.top + displacement_y
                
                # Check if the new position collides with any obstacles
                # obstacles_hit = QuadTree.hit(HashableRect(pygame.Rect(new_left, new_top, self.hitbox.width, self.hitbox.height), self.id))
                # obstacles_hit=False
                # if hasattr(self,'type'):
                #     if self.type == "player" :
                #         print(f"entity.direction: {entity.direction}")
                #         print(f"self.direction: {self.direction}")
                #         print(f"relative_velocity: {relative_velocity}")
                #         print(f"self.direction.magnitude() : {self.direction.magnitude() }")
                #         print(f"entity.direction.magnitude(): {entity.direction.magnitude()}")
                #         print(f"direction_vector: {direction_vector}")
                #         print(f"collision_normal: {collision_normal}")
                #         print(f"displacement_y: {displacement_y}")
                #         print(f"displacement_x: {displacement_x}")
                    
                
                # # If there are obstacles in the path, adjust the position
                # if obstacles_hit:
                #     obstacle = next(iter(obstacles_hit))  # Get the closest obstacle
                #     if self.rect.left < obstacle.left:  # Intersection with left side
                #         self.hitbox.right = obstacle.left
                #         self.hitbox.top = new_top
                #     elif self.rect.left > obstacle.right:  # Intersection with right side
                #         self.hitbox.left = obstacle.right
                #         self.hitbox.top = new_top
                #     elif self.rect.top < obstacle.top:  # Intersection with top side
                #         self.hitbox.bottom = obstacle.top
                #         self.hitbox.left = new_left
                #     else:  # Intersection with bottom side
                #         self.hitbox.top = obstacle.bottom
                #         self.hitbox.left = new_left
                #else:
                    # Move the entity to the calculated new position
                self.hitbox.left += displacement_x
                self.hitbox.top += displacement_y
    
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
          
              
    ###@profile
    def collision_old3(self, direction):
        for sprite in self.obstacle_sprites:
            # Calculate the distance between the entity and the obstacle sprite
            #print(f"sprite.rect.center:{sprite.rect.center}, self.hitbox.center : {self.hitbox.center}")
            #distance = pygame.math.Vector2(sprite.rect.center) - pygame.math.Vector2(self.hitbox.center)
            # Check if the obstacle is within the maximum collision distance
            #if distance.length() <= self.max_collision_distance.length():
                         # Calculate the distance between the entity and the obstacle sprite
            dx = sprite.rect.centerx - self.hitbox.centerx
            dy = sprite.rect.centery - self.hitbox.centery
            if min(dx,dy) < 100:
            #print(dy)
            #print(dx)
            #distance_squared = dx ** 2 + dy ** 2
            #print(distance_squared)
            # Check if the obstacle is within the maximum collision distance
            #if distance_squared <= self.max_collision_distance_squared:
                if sprite.hitbox.colliderect(self.hitbox):
                    if direction == "Horizontal":
                        if self.direction.x > 0:  # Moving Right
                            self.hitbox.right = sprite.hitbox.left
                        elif self.direction.x < 0:  # Moving Left
                            self.hitbox.left = sprite.hitbox.right
                    
                    elif direction == "Vertical":
                        if self.direction.y > 0:  # Moving Down
                            self.hitbox.bottom = sprite.hitbox.top
                        elif self.direction.y < 0:  # Moving Up
                            self.hitbox.top = sprite.hitbox.bottom
                    return
                
    ###@profile
    def collision_old2(self, direction):
        if direction == "Horizontal":
            for sprite in self.obstacle_sprites:
                if sprite.hitbox.colliderect(self.hitbox):
                    if self.direction.x > 0: # Moving Right
                        self.hitbox.right = sprite.hitbox.left
                    elif self.direction.x < 0: # Moving Left
                        self.hitbox.left = sprite.hitbox.right
                    return                  
        if direction == "Vertical":
            for sprite in self.obstacle_sprites:
                if sprite.hitbox.colliderect(self.hitbox):
                    if self.direction.y > 0: # Moving Down
                        self.hitbox.bottom = sprite.hitbox.top
                    elif self.direction.y < 0: # Moving Up
                        self.hitbox.top = sprite.hitbox.bottom
                    return
    ###@profile
    def collision_old(self, direction):
        if direction == "Horizontal":
            for sprite in self.obstacle_sprites:
                if sprite.hitbox.colliderect(self.hitbox):
                    if self.direction.x > 0: # Moving Right
                        self.hitbox.right = sprite.hitbox.left
                    if self.direction.x < 0: # Moving Left
                        self.hitbox.left = sprite.hitbox.right
                        
        if direction == "Vertical":
            for sprite in self.obstacle_sprites:
                if sprite.hitbox.colliderect(self.hitbox):
                    if self.direction.y > 0: # Moving Down
                        self.hitbox.bottom = sprite.hitbox.top
                    if self.direction.y < 0: # Moving Up
                        self.hitbox.top = sprite.hitbox.bottom

    def wave_value(self):
        value = sin(pygame.time.get_ticks())
        if value >= 0:
            return 255
        else:
            return 0
