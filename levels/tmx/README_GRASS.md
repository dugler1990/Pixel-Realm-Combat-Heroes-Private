# TMX grass (`grass_profile`)

Procedural grass uses [`GrassManager`](../../Code/GrassManager.py). Profiles now resolve to a full placement config, and multiple profiles can merge into the same map cell.

## Layer naming (required)

Grass is only applied when the **Tiled layer name** contains **`grass`** (case-insensitive), for both:

- **Tile layers** — tileset `grass_profile` is read only on these layers.
- **Object layers** — each object uses **object** custom property `grass_profile`; cells under the object’s bbox are filled.

If your layer is named e.g. `Ground` with no `grass` substring, **no grass** is placed from tile properties (rename to e.g. `GroundGrass` or add a `GrassOverlay` tile layer).

## Tile layers

1. Name the layer with **`grass`** in the name (e.g. `Grass`, `GrassOverlay`).
2. On the **tileset tile**, add custom property **`grass_profile`** (string): `default`, `big`, or a key from [`grass_profiles.json`](grass_profiles.json).

Paint as usual; each painted cell with that tile gets blades where the property is set.

## Object layers

1. Name the layer with **`grass`** in the name (e.g. `grass1`, `GrassPatches`).
2. On **each object** (rectangle, tile object, etc.), add **`grass_profile`** (string).

No `Tile` sprite is created for these objects (grass-only). All **tile cells overlapping** the object’s axis-aligned rectangle get `place_tile` (same grid as the map). Point/zero-size objects use one **TILESIZE** cell.

### Object layer dispatch order

If a layer name matches multiple rules, processing order is: **spawner** → **grass** → **Effect / shape-only** → **default objects**. Avoid ambiguous names like `GrassEffect`.

## Profile file

[`levels/tmx/grass_profiles.json`](grass_profiles.json) maps each name to:

- **`grass_options`**: list of int (blade image indices)
- **`density_mean`** / **`density_sigma`**: optional; density = `round(random.gauss(mean, sigma))`, clamped to at least 1
- **`density`**: optional fixed int (if set, mean/sigma are ignored)
- **`wind_scale`**: optional float multiplier applied to the shared wind angle
- **`force_scale`**: optional float multiplier applied to disturbance forces
- **`stiffness`**: optional float settling speed override for blades from this profile
- **`z_index`**: optional int render-order key inside a cell; lower renders first

## Layout-specific override (optional)

If a layout folder contains its own `grass_profiles.json`, it is loaded first; otherwise the shared file under `levels/tmx/` is used.

## Overlapping cells

Overlapping placements now **merge into one grass cell**. This means `default` and `big` can both contribute blades to the same map tile:

- all blades in that cell render through one grass system
- shared wind still comes from one global patch angle
- per-profile `wind_scale`, `force_scale`, `stiffness`, and `z_index` still apply

## Migration

Maps that used **`grass_profile` on tiles in a layer not named with `grass`**: rename that layer to include **`grass`**, or move grass tiles to a dedicated **`Grass*`** tile layer.
