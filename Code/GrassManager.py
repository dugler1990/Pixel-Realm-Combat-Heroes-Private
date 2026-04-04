'''
Version 1.0

An efficient pure Python/Pygame grass module written by DaFluffyPotato. Feel free to use however you'd like.

Please see grass_demo.py for an example of how to use GrassManager.

Important functions and objects:

-> grass.GrassManager(grass_path, tile_size=15, shade_amount=100, stiffness=360, max_unique=10, place_range=[1, 1], padding=13)
Initialize a grass manager object.

-> grass.GrassManager.enable_ground_shadows(shadow_strength=40, shadow_radius=2, shadow_color=(0, 0, 1), shadow_shift=(0, 0))
Enables shadows for individual blades (or disables if shadow_strength is set to 0). shadow_radius determines the radius of the
shadow circle, shadow_color determines the base color of the shadow, and shadow_shift is the offset of the shadow relative to
the base of the blade.

-> grass.GrassManager.place_tile(location, density, grass_options)
Adds new grass. location specifies which "tile" the grass should be placed at, so the pixel-position of the tile will depend
on the GrassManager's tile size. density specifies the number of blades the tile should have and grass_options is a list of blade
image IDs that can be used to form the grass tile. The blade image IDs are the alphabetical index of the image in the asset folder
provided for the blades. Please note that you can specify the same ID multiple times in the grass options to make it more likely
to appear.

-> grass.GrassManager.apply_force(location, radius, dropoff)
Applies a physical force to the grass at the given location. The radius is the range at which the grass should be fully bent over at.
The dropoff is the distance past the end of the "radius" that it should take for the force to be eased into nothing.

-> grass.GrassManager.update_render(surf, dt, offset=(0, 0), rot_function=None)
Renders the grass onto a surface and applies updates. surf is the surface rendered onto, dt is the amount of seconds passed since the
last update, offset is the camera's offset, and the rot_function is for custom rotational modifiers. The rot_function passed as an
argument should take an X and Y value while returning a rotation value. Take a look at grass_demo.py to how you can create a wind
effect with this.

Notes about configuration of the GrassManager:

<grass_path>
The only required argument. It points to a folder with all of the blade images. The names of the images don't matter. When creating
tiles, you provide a list of IDs, which are the indexes of the blade images that can be used. The indexes are based on alphabetical
order, so if be careful with numbers like img_2.png and img_10.png because img_10.png will come first. It's recommended that you do
img_02.png and img_10.png if you need double digits.

<tile_size>
This is used to define the "tile size" for the grass. If your game is tile based, your actual tile size should be some multiple of the
number given here. This affects a couple things. First, it defines the smallest section of grass that can be individually affected by
efficient rotation modifications (such as wind). Second, it affects performance. If the size is too large, an unnecessary amount of
calculations will be made for applied forces. If the size is too small, there will be too many images render, which will also reduce
performance. It's good to play around with this number for proper optimization.

<shade_amount>
The shade amount determines the maximum amount of transparency that can be applied to a blade as it tilts away from its base angle.
This should be a value from 0 to 255.

<stiffness>
This determines how fast the blades of grass bounce back into place after being rotated by an applied force.

<max_unique>
This determines the maximum amount of variants that can be used for a specific tile configuration (a configuration is the combination
of the amount of blades of grass and the possible set of blade images that can be used for a tile). If the number is too high, the
application will use a large amount of RAM to store all of the cached tile images. If the number is too low, you'll start to see
consistent patterns appear in the layout of your grass tiles.

<place_range>
This determines the vertical range that the base of the blades can be placed at. The range should be any range in the range of 0 to 1.
Use [1, 1] when you want the base of the blades to be placed at the bottom of the tile (useful for platformers) or [0, 1] if you want
the blades to be placed anywhere in the tile (useful for top-down games).

<padding>
This is the amount of spacial padding the tile images have to fit the blades spilling outside the bounds of the tile. This should
probably be set to the height of your tallest blade of grass.
'''

import os
import random
import math
from collections import defaultdict
from copy import deepcopy

import pygame

BLADE_POS = 0
BLADE_ID = 1
BLADE_ROT = 2
BLADE_WIND_SCALE = 3
BLADE_FORCE_SCALE = 4
BLADE_STIFFNESS = 5
BLADE_Z_INDEX = 6


def _cluster_follower_jitter_deg(seed, loc, bx, by, blade_idx, max_jitter):
    if max_jitter <= 0:
        return 0.0
    tx = int(loc[0]) & 0xFFFFFFFF
    ty = int(loc[1]) & 0xFFFFFFFF
    x = (
        (int(seed) & 0xFFFFFFFF)
        ^ (tx * 0x9E3779B1)
        ^ (ty * 0x85EBCA6B)
        ^ (int(bx) * 0xC2B2AE3D)
        ^ (int(by) * 0x27D4EB2F)
        ^ (int(blade_idx) * 0x165667B1)
    ) & 0xFFFFFFFF
    u = (x / 4294967295.0) * 2.0 - 1.0
    return u * max_jitter


def normalize(val, amt, target):
    if val > target + amt:
        val -= amt
    elif val < target - amt:
        val += amt
    else:
        val = target
    return val

# the main object that manages the grass system
class GrassManager:
    def __init__(self, grass_path, tile_size=15, shade_amount=100, stiffness=360, max_unique=10, place_range=[1, 1], padding=13, rotation_bucket_degrees=6):
        # asset manager
        self.ga = GrassAssets(grass_path, self)

        # caching variables
        self.grass_id = 0
        self.grass_cache = {}
        self.shadow_cache = {}
        self.formats = {}

        # tile data
        self.grass_tiles = {}

        # config
        self.tile_size = tile_size
        self.shade_amount = shade_amount
        self.stiffness = stiffness
        self.max_unique = max_unique
        self.vertical_place_range = place_range
        self.ground_shadow = [0, (0, 0, 0), 100, (0, 0)]
        self.padding = padding
        self.rotation_bucket_degrees = max(1, int(rotation_bucket_degrees))

    def _normalize_placement(self, density_or_profile, grass_options=None, **kwargs):
        if isinstance(density_or_profile, dict) and grass_options is None:
            raw = dict(density_or_profile)
        else:
            raw = dict(kwargs)
            raw["density"] = density_or_profile
            raw["grass_options"] = grass_options

        options = raw.get("grass_options")
        if not isinstance(options, (list, tuple)) or len(options) == 0:
            raise ValueError("grass_options must be a non-empty list")
        try:
            options = tuple(int(x) for x in options)
        except (TypeError, ValueError) as exc:
            raise ValueError("grass_options must contain integers") from exc

        try:
            density = max(1, int(raw.get("density", 1)))
        except (TypeError, ValueError) as exc:
            raise ValueError("density must be an integer") from exc

        def _float_value(name, default):
            try:
                return float(raw.get(name, default))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} must be numeric") from exc

        def _int_value(name, default):
            try:
                return int(raw.get(name, default))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} must be an integer") from exc

        profile_key = str(raw.get("profile_key", raw.get("layer", "default"))).strip() or "default"
        return {
            "profile_key": profile_key,
            "density": density,
            "grass_options": options,
            "wind_scale": _float_value("wind_scale", 1.0),
            "force_scale": _float_value("force_scale", 1.0),
            "stiffness": _float_value("stiffness", self.stiffness),
            "z_index": _int_value("z_index", 0),
        }

    # enables circular shadows that appear below each blade of grass
    def enable_ground_shadows(self, shadow_strength=40, shadow_radius=2, shadow_color=(0, 0, 1), shadow_shift=(0, 0)):
        # don't interfere with colorkey
        if shadow_color == (0, 0, 0):
            shadow_color = (0, 0, 1)

        self.ground_shadow = [shadow_radius, shadow_color, shadow_strength, shadow_shift]

    # either creates a new grass tile layout or returns an existing one if the cap has been hit
    def get_format(self, format_id, data, tile_id):
        if format_id not in self.formats:
            self.formats[format_id] = {'count': 1, 'data': [(tile_id, data)]}
        elif self.formats[format_id]['count'] >= self.max_unique:
            return deepcopy(random.choice(self.formats[format_id]['data']))
        else:
            self.formats[format_id]['count'] += 1
            self.formats[format_id]['data'].append((tile_id, data))

    # attempt to place new grass in a map cell
    def place_tile(self, location, density, grass_options=None, **kwargs):
        try:
            placement = self._normalize_placement(
                density,
                grass_options=grass_options,
                **kwargs,
            )
        except ValueError:
            return

        pos = tuple(location)
        if pos not in self.grass_tiles:
            self.grass_tiles[pos] = GrassCell(
                self.tile_size,
                (pos[0] * self.tile_size, pos[1] * self.tile_size),
                self.ga,
                self,
            )
        self.grass_tiles[pos].add_placement(placement)

    # apply a force to the grass that causes the grass to bend away
    def apply_force(
        self,
        location,
        radius,
        dropoff,
        cluster_anchor=None,
        cluster_cfg=None,
        stats_out=None,
    ):
        location = (int(location[0]), int(location[1]))
        grid_pos = (int(location[0] // self.tile_size), int(location[1] // self.tile_size))
        tile_range = math.ceil((radius + dropoff) / self.tile_size)
        #print(f"Location: {location}, Grid Position: {grid_pos}, Tile Range: {tile_range}")

        for y in range(tile_range * 2 + 1):
            y = y - tile_range
            for x in range(tile_range * 2 + 1):
                x = x - tile_range
                pos = (grid_pos[0] + x, grid_pos[1] + y)
                if pos in self.grass_tiles:
                    self.grass_tiles[pos].apply_force(
                        location,
                        radius,
                        dropoff,
                        cluster_anchor=cluster_anchor,
                        cluster_cfg=cluster_cfg,
                        stats_out=stats_out,
                    )

    # an update and render combination function
    def update_render(self, surf, dt, offset=(0, 0), rot_function=None, collect_stats=False):
        visible_tile_range = (int(surf.get_width() // self.tile_size) + 1, int(surf.get_height() // self.tile_size) + 1)
        base_pos = (int(offset[0] // self.tile_size), int(offset[1] // self.tile_size))

        # get list of grass tiles to render based on visible area
        render_list = []
        for y in range(visible_tile_range[1]):
            for x in range(visible_tile_range[0]):
                pos = (base_pos[0] + x, base_pos[1] + y)
                if pos in self.grass_tiles:
                    render_list.append(pos)

        # render shadow if applicable
        if self.ground_shadow[0]:
            for pos in render_list:
                self.grass_tiles[pos].render_shadow(surf, offset=(offset[0] - self.ground_shadow[3][0], offset[1] - self.ground_shadow[3][1]))

        # render the grass tiles
        custom_tiles = 0
        for pos in render_list:
            tile = self.grass_tiles[pos]
            if collect_stats and tile.custom_blade_data:
                custom_tiles += 1
            tile.render(surf, dt, offset=offset)
            if rot_function:
                tile.set_rotation(rot_function(tile.loc[0], tile.loc[1]))
        if collect_stats:
            return {
                "visible_tiles": len(render_list),
                "custom_tiles": custom_tiles,
            }
        return None

# an asset manager that contains functionality for rendering blades of grass
class GrassAssets:
    def __init__(self, path, gm):
        self.gm = gm
        self.blades = []

        # load in blade images
        for blade in sorted(os.listdir(path)):
            img = pygame.image.load(path + '/' + blade).convert()
            img.set_colorkey((0, 0, 0))
            self.blades.append(img)

    def render_blade(self, surf, blade_id, location, rotation):
        # rotate the blade
        rot_img = pygame.transform.rotate(self.blades[blade_id], rotation)

        # shade the blade of grass based on its rotation
        shade_amt = self.gm.shade_amount * (abs(rotation) / 90)
        if shade_amt > 0:
            shade = pygame.Surface(rot_img.get_size())
            shade.set_alpha(shade_amt)
            rot_img.blit(shade, (0, 0))

        # render the blade
        surf.blit(rot_img, (location[0] - rot_img.get_width() // 2, location[1] - rot_img.get_height() // 2))

# the grass tile object that contains data for one map cell of blades
class GrassCell:
    def __init__(self, tile_size, location, ga, gm):
        self.ga = ga
        self.gm = gm
        self.loc = location
        self.size = tile_size
        self.placements = []
        self.blades = []
        self.master_rotation = 0
        self.precision = 30
        self.padding = self.gm.padding
        self.rotation_scale = 90 / self.precision
        self.base_id = self.gm.grass_id
        self.gm.grass_id += 1

        # custom_blade_data is used when the blade's current state should not be cached. all grass tiles will try to return to a cached state
        self.custom_blade_data = None

        self.update_render_data()

    def add_placement(self, placement):
        self.placements.append(placement)
        self._rebuild_blades()

    def _placement_sort_key(self, placement):
        return (
            placement["z_index"],
            placement["profile_key"],
            placement["density"],
            placement["grass_options"],
        )

    def _placement_signature(self):
        signature = []
        for placement in sorted(self.placements, key=self._placement_sort_key):
            signature.append(
                (
                    placement["profile_key"],
                    placement["density"],
                    placement["grass_options"],
                    round(placement["wind_scale"], 4),
                    round(placement["force_scale"], 4),
                    round(placement["stiffness"], 4),
                    placement["z_index"],
                )
            )
        return tuple(signature)

    def _generate_blades_for_placement(self, placement):
        blades = []
        y_range = self.gm.vertical_place_range[1] - self.gm.vertical_place_range[0]
        for _ in range(placement["density"]):
            blade_id = random.choice(placement["grass_options"])
            y_pos = self.gm.vertical_place_range[0]
            if y_range:
                y_pos = random.random() * y_range + self.gm.vertical_place_range[0]
            blades.append(
                [
                    (random.random() * self.size, y_pos * self.size),
                    blade_id,
                    random.random() * 30 - 15,
                    placement["wind_scale"],
                    placement["force_scale"],
                    placement["stiffness"],
                    placement["z_index"],
                ]
            )
        return blades

    def _rebuild_blades(self):
        combined_blades = []
        for placement in sorted(self.placements, key=self._placement_sort_key):
            combined_blades.extend(self._generate_blades_for_placement(placement))

        combined_blades.sort(
            key=lambda blade: (
                blade[BLADE_Z_INDEX],
                blade[BLADE_POS][1],
                blade[BLADE_ID],
            )
        )

        new_base_id = self.gm.grass_id
        self.gm.grass_id += 1
        overwrite = self.gm.get_format(
            self._placement_signature(),
            combined_blades,
            new_base_id,
        )
        if overwrite:
            self.blades = overwrite[1]
            self.base_id = overwrite[0]
        else:
            self.blades = combined_blades
            self.base_id = new_base_id
        self.custom_blade_data = None
        self.update_render_data()

    def _ensure_custom_blade_data(self):
        if not self.custom_blade_data:
            self.custom_blade_data = [list(blade) for blade in self.blades]

    def _apply_force_one_blade(self, i, force_point, force_radius, force_dropoff):
        blade = self.blades[i]
        blade_x = self.loc[0] + blade[0][0]
        blade_y = self.loc[1] + blade[0][1]
        dx = blade_x - force_point[0]
        dy = blade_y - force_point[1]
        dist_sq = dx * dx + dy * dy

        force_radius_sq = force_radius * force_radius
        outer_radius = force_radius + force_dropoff
        outer_radius_sq = outer_radius * outer_radius

        if dist_sq < force_radius_sq:
            force = 2
        elif dist_sq >= outer_radius_sq:
            return
        else:
            dis = math.sqrt(dist_sq)
            dis = max(0, dis - force_radius)
            force = 1 - min(dis / force_dropoff, 1)
        force *= blade[BLADE_FORCE_SCALE]
        dir_ = 1 if force_point[0] > blade_x else -1
        if (
            not self.custom_blade_data[i]
            or abs(self.custom_blade_data[i][BLADE_ROT] - self.blades[i][BLADE_ROT])
            <= abs(force) * 90
        ):
            updated = list(self.blades[i])
            updated[BLADE_ROT] = blade[BLADE_ROT] + dir_ * force * 90
            self.custom_blade_data[i] = updated

    # apply a force that affects each blade individually based on distance instead of the rotation of the entire tile
    def apply_force(
        self,
        force_point,
        force_radius,
        force_dropoff,
        cluster_anchor=None,
        cluster_cfg=None,
        stats_out=None,
    ):
        if not self.blades:
            return

        use_cluster = (
            cluster_cfg
            and cluster_cfg.get("enabled")
            and cluster_anchor is not None
        )

        if not use_cluster:
            self._ensure_custom_blade_data()
            for i in range(len(self.blades)):
                self._apply_force_one_blade(i, force_point, force_radius, force_dropoff)
            return

        ax, ay = float(cluster_anchor[0]), float(cluster_anchor[1])
        r_sq = float(cluster_cfg["player_radius_px"]) ** 2
        sub = int(cluster_cfg["subcell_px"])
        gs = int(cluster_cfg["group_size"])
        jitter_max = float(cluster_cfg["jitter_deg"])
        jseed = int(cluster_cfg["jitter_seed"])

        self._ensure_custom_blade_data()

        near = []
        far = []
        for i, blade in enumerate(self.blades):
            wx = self.loc[0] + blade[0][0]
            wy = self.loc[1] + blade[0][1]
            d_sq = (wx - ax) * (wx - ax) + (wy - ay) * (wy - ay)
            if d_sq <= r_sq:
                near.append(i)
            else:
                far.append(i)

        for i in near:
            self._apply_force_one_blade(i, force_point, force_radius, force_dropoff)

        buckets = defaultdict(list)
        for i in far:
            blade = self.blades[i]
            wx = self.loc[0] + blade[0][0]
            wy = self.loc[1] + blade[0][1]
            bx = int(wx // sub)
            by = int(wy // sub)
            buckets[(bx, by)].append((wx, wy, i))

        for (bx, by), items in buckets.items():
            items.sort(key=lambda t: (t[0], t[1], t[2]))
            idx_list = [t[2] for t in items]
            for k in range(0, len(idx_list), gs):
                chunk = idx_list[k : k + gs]
                if not chunk:
                    continue
                leader = chunk[0]
                self._apply_force_one_blade(leader, force_point, force_radius, force_dropoff)
                leader_row = self.custom_blade_data[leader]
                if leader_row is None:
                    continue
                leader_rot = leader_row[BLADE_ROT]
                for fj in chunk[1:]:
                    row = list(self.blades[fj])
                    jitter = _cluster_follower_jitter_deg(
                        jseed, self.loc, bx, by, fj, jitter_max
                    )
                    row[BLADE_ROT] = max(-90, min(90, leader_rot + jitter))
                    self.custom_blade_data[fj] = row
                    if stats_out is not None:
                        stats_out["cluster_follower_copies"] = (
                            stats_out.get("cluster_follower_copies", 0) + 1
                        )

    # update the identifier used to find a valid cached image
    def update_render_data(self):
        quantized_rotation = self._quantize_rotation(self.master_rotation)
        self.render_data = (self.base_id, quantized_rotation)
        self.true_rotation = self.rotation_scale * quantized_rotation

    def _quantize_rotation(self, rotation):
        bucket = self.gm.rotation_bucket_degrees
        return int(round(rotation / bucket) * bucket)

    # set new master tile rotation
    def set_rotation(self, rotation):
        quantized_rotation = self._quantize_rotation(rotation)
        if quantized_rotation != self.master_rotation:
            self.master_rotation = quantized_rotation
            self.update_render_data()
            return True
        return False

    def _blade_render_rotation(self, blade):
        return max(
            -90,
            min(
                90,
                blade[BLADE_ROT] + self.true_rotation * blade[BLADE_WIND_SCALE],
            ),
        )

    # render the tile's image based on its current state and return the data
    def render_tile(self, render_shadow=False):
        # make a new padded surface (to fit blades spilling out of the tile)
        surf = pygame.Surface((self.size + self.padding * 2, self.size + self.padding * 2))
        surf.set_colorkey((0, 0, 0))

        # use custom_blade_data if it's active (uncached). otherwise use the base data (cached).
        if self.custom_blade_data:
            blades = self.custom_blade_data
        else:
            blades = self.blades

        # render the shadows of each blade if applicable
        if render_shadow:
            shadow_surf = pygame.Surface(surf.get_size())
            shadow_surf.set_colorkey((0, 0, 0))
            for blade in self.blades:
                pygame.draw.circle(
                    shadow_surf,
                    self.gm.ground_shadow[1],
                    (
                        blade[BLADE_POS][0] + self.padding,
                        blade[BLADE_POS][1] + self.padding,
                    ),
                    self.gm.ground_shadow[0],
                )
            shadow_surf.set_alpha(self.gm.ground_shadow[2])

        # render each blade using the asset manager
        for i, blade in enumerate(blades):
            if blade is None:
                # Defensive fallback for partial custom data; should be rare.
                blade = self.blades[i]
            self.ga.render_blade(
                surf,
                blade[BLADE_ID],
                (
                    blade[BLADE_POS][0] + self.padding,
                    blade[BLADE_POS][1] + self.padding,
                ),
                self._blade_render_rotation(blade),
            )

        # return surf and shadow_surf if applicable
        if render_shadow:
            return surf, shadow_surf
        else:
            return surf

    # draw the shadow image for the tile
    def render_shadow(self, surf, offset=(0, 0)):
        if self.gm.ground_shadow[0] and (self.base_id in self.gm.shadow_cache):
            surf.blit(self.gm.shadow_cache[self.base_id], (self.loc[0] - offset[0] - self.padding, self.loc[1] - offset[1] - self.padding))

    # draw the grass itself
    def render(self, surf, dt, offset=(0, 0)):
        # render a new grass tile image if using custom uncached data otherwise use cached data if possible
        if self.custom_blade_data:
            surf.blit(self.render_tile(), (self.loc[0] - offset[0] - self.padding, self.loc[1] - offset[1] - self.padding))

        else:
            # check if a new cached image needs to be generated and use the cached data if not (also cache shadow if necessary)
            if (self.render_data not in self.gm.grass_cache) and (self.gm.ground_shadow[0] and (self.base_id not in self.gm.shadow_cache)):
                grass_img, shadow_img = self.render_tile(render_shadow=True)
                self.gm.grass_cache[self.render_data] = grass_img
                self.gm.shadow_cache[self.base_id] = shadow_img
            elif self.render_data not in self.gm.grass_cache:
                self.gm.grass_cache[self.render_data] = self.render_tile()

            # render image from the cache
            surf.blit(self.gm.grass_cache[self.render_data], (self.loc[0] - offset[0] - self.padding, self.loc[1] - offset[1] - self.padding))

        # attempt to move blades back to their base position
        if self.custom_blade_data:
            matching = True
            settle_epsilon = 0.1
            for i, blade in enumerate(self.custom_blade_data):
                if blade is None:
                    blade = list(self.blades[i])
                    self.custom_blade_data[i] = blade
                blade[BLADE_ROT] = normalize(
                    blade[BLADE_ROT],
                    blade[BLADE_STIFFNESS] * dt,
                    self.blades[i][BLADE_ROT],
                )
                if abs(blade[BLADE_ROT] - self.blades[i][BLADE_ROT]) <= settle_epsilon:
                    blade[BLADE_ROT] = self.blades[i][BLADE_ROT]
                else:
                    matching = False
            # mark the data as non-custom once in base position so the cache can be used
            if matching:
                self.custom_blade_data = None


GrassTile = GrassCell