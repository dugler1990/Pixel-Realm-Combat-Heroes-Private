# TMX world interactables (`env_interactable_profiles`)

Object-layer props (not ground tiles) for **sprites the player interacts with** (Space), separate from tile `valid_interaction_types` / `get_tile_valid_actions`.

## Tiled object layer

Use an **object layer whose name contains `interactable`** (case-insensitive), e.g. `Interactables` or `WorldInteractables`. The layout manager runs the same object pipeline as `Object Layer 1`, so tile objects with `interactable_profile` / `interactable_type` spawn as world interactables.

Dispatch order (first match wins): **spawner** → **item** → **grass** → **interactable** → **effect / shape-only** → **default objects**.

## Graphics layout (chests)

Authoring tree under [`Graphics/EnvInteractables/chests/`](../../Graphics/EnvInteractables/chests/):

- **`hit_animation`** — folder of PNGs (same idea as **`open_animation`**): proximity “hit” reaction. **Sorted filenames** (see [`import_folder`](../../Code/Support.py)): the **first** frame is also the **idle / closed** chest sprite at rest (no separate idle PNG required at runtime).
- **`open_animation`** — folder of PNGs for the open transition (or use **`image_open`** for a single final still).

Where **`material`** is `ice`, `gold`, `metal`, or `wooden`, paths use **`chests/{material}/default/`** (base) and **`chests/{material}/snow/`** (snow).

Profile ids: **`chest_{material}`** for the base variant, **`chest_{material}_snow`** for snow (e.g. `chest_metal`, `chest_metal_snow`). Legacy **`interactable_type: chest`** uses **`chest_default`** (wooden + default paths). **`default_loot`** is defined per material on **`chest_{material}`**; snow profiles can leave **`default_loot`** empty and inherit that material’s table. Paths in JSON use `../Graphics/EnvInteractables/chests/...` relative to the project root (resolved with `Code/` and the map folder). **Loot chests do not use the Tiled object tile image as the runtime sprite.**

**Required for each loot chest profile:** **`hit_animation`** must resolve to a non-empty folder of loadable PNGs; otherwise the chest is not spawned and an error is logged (`tmx_layout`).

Optional: run [`tools/generate_chest_idle_from_hit.py`](../../tools/generate_chest_idle_from_hit.py) to write an **`idle.png`** next to each **`hit_animation`** folder (first sorted frame) for version control or art review — the game does not read that file if idle is derived from **`hit_frames[0]`** at load.

## Profile file

[`env_interactable_profiles.json`](env_interactable_profiles.json) maps each **profile id** to defaults:

- **`kind`**: behavior (`loot_container` today; extensible).
- **`interaction_margin`**: default inflate for proximity (pixels).
- **`default_loot`**: loot table shape when the TMX object has **no** `loot_json` property (same schema as [`resolve_loot_table`](../../Code/loot_table.py)).
- **`open_animation`** / **`image_open`**: optional paths (TMX can override).
- **`frame_ms`**: delay between frames when playing the hit clip (ms).
- **`hit_animation`**: folder of PNGs; first sorted frame = idle; entering interaction range plays the full sequence once, then returns to idle (first frame).

At runtime, when the player is in range of an unopened loot chest (and the game is not paused with inventory open), a bottom-screen prompt **`[Space] Interact`** is shown.

Loading order: **layout folder** first, then shared `levels/tmx/` (same idea as `grass_profiles.json`).

## TMX properties

- **`interactable_profile`**: profile id (preferred for new assets).
- **`interactable_type`**: legacy `chest` maps to profile `chest_default` when `interactable_profile` is omitted.
- **`loot_json`**: per-instance override (stringified JSON).
- **`interaction_margin`**, **`hit_animation`**, **`open_animation`**, **`image_open`**: optional per-instance overrides (same merge rules as profile defaults).

Merge order: **profile defaults**, then **explicit TMX properties** win.
