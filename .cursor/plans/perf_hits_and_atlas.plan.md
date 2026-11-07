---
name: perf hits and atlas
overview: "Two speed-ups from the ice-map profile (200+ entities): find_hits filters by rect before its Python loop, and every ImageCache sprite batches through the GPU atlas, packed the first time it is drawn. Each phase replaces the old path, is proven by a test, measured before and after on a fixed benchmark scene, and logged in Code/NOTES_performance.md. Branch perf/hits-and-atlas."
todos:
  - id: measure
    content: "Phase 0, steps 1-3: count real draw calls, write NOTES_performance.md, take the baseline."
    status: pending
  - id: hits
    content: "Phase 1, steps 4-5: a find_hits test that passes on today's code; find_hits filters by rect first. Measure, log, commit."
    status: pending
  - id: atlas
    content: "Phase 2, steps 6-11: ImageCache knows its surfaces; the backend packs them into the atlas on first draw; build_atlas goes; a GL test proves the batching. Measure, log, commit."
    status: pending
  - id: rts
    content: "Phase 3, step 12: RTS sprites load through ImageCache. Measure, log, commit."
    status: pending
isProject: false
---

# Speed: hit test and sprite atlas

## Why

Profile of the ice map with 200+ entities, 2026-11-02, per gameplay frame, with the profiler on:

- **Sprite drawing, 18.8 ms.** Of ~174 blits per frame (~140 of them sprites), ~133 miss the GPU atlas. Each miss is its own draw call with a buffer upload, about 100 µs with the profiler on. The atlas is built once in `Main2.start_level` from whatever `ImageCache` holds at that moment. The biggest groups of sprites that miss:

  | Sprites per frame | Class | Why they miss |
  |---|---|---|
  | 34 | combat units | frames load at spawn, after the atlas is built |
  | 20 | RTS resource nodes | `rts/assets.load_sprite` loads files itself, not through `ImageCache` |
  | 15.5 | dropped items | images load at drop time, after the atlas is built |

- **`find_hits`, 5.1 ms.** It runs about 20 times a frame, once per live attack sprite. Each run loops over every attackable sprite in Python, doing the `exclude` check, `seen` set and `getattr` before the rect test. That is 2.5M loop iterations; the mask tests themselves cost 0.04 s in total.

## Before you start

- Branch: `perf/hits-and-atlas`, from `main` at `28b04dd` (the HUD fill commit and its test fix). It is checked out in the shared folder, so other sessions in this folder are on it too. Re-check `git status` right before each edit.
- Other sessions' uncommitted files (`tests/test_entity_pipeline.py`, `tools/entity_pipeline/figures.py`, `tools/painted_map_pipeline/leonardo_api.py`) are not part of this work. Never stage them.
- Find functions **by name**, not line number. Re-read a file right before editing it.
- Copy the code as written. Do not rename, "improve" or add features.
- Each phase ends with:
  1. its tests pass;
  2. measure with step 3's command;
  3. add a row to the log in `Code/NOTES_performance.md`;
  4. update `.cursor/plans/perf_status.md`;
  5. commit only that phase's files.
- GL tests skip under the headless driver that `tests/test_render_backend.py` sets by default. Run that file as `$env:SDL_VIDEODRIVER = "windows"; .\Code\sprite_venv\Scripts\python.exe -m pytest tests/test_render_backend.py -k gpu` so they run. Its 3 CPU tests already fail for an unrelated reason (they don't force `RENDER_BACKEND=cpu`); leave them.

## Do not

1. Do not keep the old path beside the new one. `build_atlas` and the RTS loader's own file loading are deleted, not kept as fallbacks.
2. Do not pack surfaces that are not in `ImageCache` into the atlas. Only `ImageCache` surfaces live for the whole run, so only their `id()` can never be reused by a different image.
3. Do not let `ImageCache` drop or replace a surface it holds, for the same reason.
4. Do not change what can be hit. `find_hits` returns the same targets in the same order; it only skips work.
5. Do not touch the large-texture path (`_resident_texture`), the grass, smoke, light or mesh pipelines.

---

## Phase 0: measuring

### Step 1. `Code/render_backend.py`: count real draw calls

The benchmark's `gpu_draw_calls_total` counts blits today, not draw calls, so it can't show batching.

- In `def _flush_batch(self):`, directly after `glDrawArrays(GL_TRIANGLES, 0, n * _VERTS_PER_QUAD)`, add:

```python
        if BENCHMARK_RUNTIME.enabled and BENCHMARK_RUNTIME.metrics_enabled:
            BENCHMARK_RUNTIME.metrics.record_gpu_draw_call()
```

- At the end of `def blit(`, and at the end of `def blit_scaled(`, delete:

```python
        if BENCHMARK_RUNTIME.enabled and BENCHMARK_RUNTIME.metrics_enabled:
            BENCHMARK_RUNTIME.metrics.record_gpu_draw_call()
```

Keep the two in the mesh boss draws: those are real draw calls.

### Step 2. Create `Code/NOTES_performance.md`

```markdown
# Performance notes

Read this before writing anything that runs every frame. The rules are patterns measured to
be fast: use them without debate. The dangers each cost us frame time once. The log records
what each change measured.

## Rules

1. **Every image drawn more than once comes from ImageCache**: `ImageCache.load_image`,
   `load_scaled`, `keep_frames`, or `Support.import_folder` / `import_folder_flipped`. The GPU
   backend copies an ImageCache surface into its sprite atlas the first time it is drawn, and
   from then on it batches with every other sprite.
2. **Never make a surface per frame**: no `transform.rotate/scale/flip`, `.copy()` or
   `font.render` inside an update or draw. Build once, keep it, or cache it by a stable key.
   Text that changes: render it when it changes and call `backend.invalidate_texture` on the old one.
3. **`fill` and `draw_rect` are cheap**: they batch with the sprites (the atlas's white texel).
   A blend `flags=` value forces two flushes: use it only for full-screen overlays.
4. **"What does this touch" filters by rect first**: one `Rect.colliderect` per candidate in a
   list comprehension, before any other per-candidate work. Masks only for the survivors.
   See `hit_core.find_hits`.
5. **Direct GL draws flush first**: anything that draws outside the batch (grass, smoke,
   lights, mesh) calls `_flush_batch()` before it draws.

## Dangers

- **A sprite whose image is not an ImageCache surface** is one draw call per sprite per frame
  (~100 µs with the profiler on). Known today: rotated arrows (`Particles._face_direction`),
  chest copies (`InteractableChest`), per-instance scaled tribey snakes.
- **`id(surface)` as a cache key** is only safe for surfaces that never die. A freed surface's
  id is reused by the next one, which then draws the old image.
- **A Python loop over all entities, once per attack or once per entity, every frame.**
  At 200 entities that is tens of thousands of iterations per frame.
- **Loading from disk during play**: ~8 ms per PNG (profiled), a visible stall.

## How to measure

Fixed scene: the ice map in benchmark mode, 200 enemies from the map's own spawn mix. Each run
spawns them, warms up 10 s, measures 30 s, writes one row to `logs/perf_ice200.csv` and quits.
Counts (draw calls per frame, calls per frame) don't drift with the machine; times do, so take
a phase's before and after runs back to back. The map's own spawners keep adding enemies during
a run, so compare draw calls per sprite drawn as well as per frame.

## Log

| Date | Change | Scene | avg ms | p95 ms | draw calls / frame | Notes |
|---|---|---|---|---|---|---|
| 2026-11-02 | HUD fills batch with sprites (`36f7ba4`) | ice map, play, profiled | | | | `fill` + `draw_rect` 6.4 → 0.7 ms per frame |
```

Commit `Code/render_backend.py` and `Code/NOTES_performance.md`.

### Step 3. Take the baseline

Claude runs this from `Code/` in one PowerShell call (env vars don't carry between calls). It runs the game twice, about a minute each, with no input needed, then clears the variables so the next normal launch isn't a benchmark. If the game fails to start or shows no enemies, stop and report.

```
$label = "base"
New-Item -ItemType Directory -Force ..\logs\perf | Out-Null
$env:PRCH_BENCHMARK_ENABLED = "1"
$env:PRCH_BENCHMARK_LAYOUT_DIR = "../levels/tmx"
$env:PRCH_BENCHMARK_ENTITY_COUNT = "200"
$env:PRCH_BENCHMARK_ENEMY_MIX = "ice_ghost:60,raccoon:30,spirit:30,ice_mage:25,demon_dog:20,venom_plant:20,tribey_snake:15"
$env:PRCH_BENCHMARK_WARMUP_SECONDS = "10"
$env:PRCH_BENCHMARK_AUTO_RUN_SECONDS = "30"
$env:PRCH_BENCHMARK_METRICS_CSV_PATH = "../logs/perf_ice200.csv"
$env:PRCH_BENCHMARK_RUN_LABEL = $label
.\sprite_venv\Scripts\python.exe Main2.py
$env:PRCH_BENCHMARK_RUN_LABEL = "$label-prof"
.\sprite_venv\Scripts\python.exe -m cProfile -o "..\logs\perf\$label.prof" Main2.py
Get-ChildItem Env:PRCH_BENCHMARK_* | Remove-Item
```

Record:

- From the CSV row labelled `$label` (the run without the profiler): `avg_frame_ms`, `p95_frame_ms`, and `gpu_draw_calls_total / frames`.
- From `$label.prof`, per frame (divide by `custom_draw` calls):
  - sprites drawn (`_draw_sorted_sprite` calls);
  - `_flush_batch` calls;
  - `_resident_texture` calls;
  - `find_hits` cumulative ms.

Each later phase runs the same block with `$label` set to the phase id (`hits`, `atlas`, `rts`).

Benchmark enemies spawn before the first frame, so in the baseline their frames are already in the atlas. Enemies the map's spawners add during the run are not. Step 11's play check covers what the benchmark can't show.

---

## Phase 1: hit test

### Step 4. `tests/test_hit_core.py`: pin down what find_hits returns

Create the file, run it on today's code, and check that it passes before step 5. It must still pass after.

```python
"""find_hits: every candidate whose pixels touch the attack, each once, in candidate order."""
import sys
from pathlib import Path

import pygame

CODE_DIR = Path(__file__).resolve().parents[1] / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import hit_core  # noqa: E402


class _Body:
    """What find_hits reads from a sprite: a rect and a mask the size of the rect."""

    def __init__(self, x, y, solid=True):
        self.rect = pygame.Rect(x, y, 10, 10)
        self.mask = pygame.mask.Mask((10, 10), fill=solid)


def test_find_hits_keeps_each_touching_body_once_in_candidate_order():
    attack = hit_core.Shape(pygame.mask.Mask((20, 20), fill=True), 0, 0)
    near, also_near, owner = _Body(5, 5), _Body(12, 0), _Body(0, 0)
    far = _Body(100, 100)
    hollow = _Body(5, 5, solid=False)  # rect overlaps but no pixels: the mask test drops it
    candidates = [far, near, hollow, object(), owner, near, also_near]
    assert hit_core.find_hits(attack, candidates, exclude=(owner,)) == [near, also_near]
```

### Step 5. `Code/hit_core.py`: filter by rect before the loop

Replace the whole function `def find_hits(shape, candidates, exclude=(), body=shape_of):` with:

```python
def find_hits(shape, candidates, exclude=(), body=shape_of):
    """Every candidate whose body touches `shape`, each once, in candidate order.

    `body` gives a target's shape: shape_of for swings, projectiles and dashes,
    foot_shape for ground blasts. With shape_of the target's shape lies inside its rect,
    so candidates whose rect misses are dropped first, one cheap test each, and only
    the few close ones reach the loop and the mask test.
    """
    if shape is None:
        return []
    if body is shape_of:
        overlaps = shape.rect.colliderect
        candidates = [
            sprite for sprite in candidates
            if (rect := getattr(sprite, "rect", None)) is not None and overlaps(rect)
        ]
    hits = []
    seen = set()
    for sprite in candidates:
        if sprite in exclude or id(sprite) in seen:
            continue
        seen.add(id(sprite))
        if touching(shape, body(sprite)):
            hits.append(sprite)
    return hits
```

Same targets, same order: the rect test that used to run inside the loop now runs first. A duplicate candidate has the same rect, so it is dropped or kept with its first copy, exactly as before.

Tests:

- `tests/test_hit_core.py`
- `tests/abilities/test_dash_damage_on_hit.py`
- `tests/abilities/test_charged_leap_slam.py`
- `tests/abilities/test_enemy_dash.py`

Measure (`$label = "hits"`), log, update the status, then commit `Code/hit_core.py` and `tests/test_hit_core.py`.

---

## Phase 2: every ImageCache sprite batches

### Step 6. `Code/ImageCache.py`: know which surfaces it holds

Replace the whole file with:

```python
import os

import pygame


class ImageCache:
    """Images loaded once and kept for the whole run, shared by everything that draws them.

    A surface held here never changes and is never freed or replaced, so the GPU backend
    packs it into its sprite atlas the first time it is drawn (holds()). Its dicts are read
    and written only through these methods, so holds() knows every surface.
    """
    _images = {}
    _folder_cache = {}
    _scaled_cache = {}
    _held_ids = set()  # id() of every surface in the three dicts above

    @staticmethod
    def _normalize_path(path):
        return os.path.abspath(os.path.normpath(path))

    @staticmethod
    def _scale_key(scale):
        if scale is None:
            return None
        if isinstance(scale, (list, tuple)):
            return tuple(scale)
        return scale

    @staticmethod
    def folder_cache_key(folder, scale=None):
        return (ImageCache._normalize_path(folder), ImageCache._scale_key(scale))

    @staticmethod
    def holds(surface):
        """True for a surface this cache holds: it never changes and lives for the run."""
        return id(surface) in ImageCache._held_ids

    @staticmethod
    def clear():
        """Forget every image (tests)."""
        ImageCache._images.clear()
        ImageCache._folder_cache.clear()
        ImageCache._scaled_cache.clear()
        ImageCache._held_ids.clear()

    @staticmethod
    def frames(key):
        """The frame list stored under `key` (folder_cache_key), or None."""
        return ImageCache._folder_cache.get(key)

    @staticmethod
    def keep_frames(key, frames):
        """Store a frame list under `key` (folder_cache_key) and return the stored list.

        A key that already has frames keeps them: held surfaces are never replaced.
        """
        kept = ImageCache._folder_cache.setdefault(key, frames)
        if kept is frames:
            ImageCache._held_ids.update(id(frame) for frame in frames)
        return kept

    @staticmethod
    def load_image(path):
        """Load an image from a path, using the cache to avoid reloading from disk."""
        norm = ImageCache._normalize_path(path)
        image = ImageCache._images.get(norm)
        if image is None:
            image = pygame.image.load(norm)
            try:
                image = image.convert_alpha()
            except pygame.error:
                pass  # no display mode (headless server, tests): keep the file's own format
            ImageCache._images[norm] = image
            ImageCache._held_ids.add(id(image))
        return image

    @staticmethod
    def load_scaled(path, size):
        """Load and scale an image, caching by normalized path and target size."""
        scale = ImageCache._scale_key(size)
        if scale is None:
            raise ValueError("size is required for load_scaled")
        key = (ImageCache._normalize_path(path), scale)
        cached = ImageCache._scaled_cache.get(key)
        if cached is None:
            base = ImageCache.load_image(path)
            cached = pygame.transform.scale(base, tuple(scale))
            ImageCache._scaled_cache[key] = cached
            ImageCache._held_ids.add(id(cached))
        return cached
```

Compared with today's file: `cache` becomes the private `_images` (after this plan nothing outside reads it), `frames`, `keep_frames`, `holds` and `clear` are new, and the unused `load_folder` is gone (only a commented-out line in `Trap.py` names it).

In `tests/test_image_cache_scaled.py` and `tests/test_import_folder_cache.py`, replace each group of three lines

```python
    ImageCache.cache.clear()
    ImageCache._folder_cache.clear()
    ImageCache._scaled_cache.clear()
```

with `    ImageCache.clear()`.

### Step 7. Every write into ImageCache goes through `keep_frames`

- `Code/Support.py`, in `def import_folder(`: replace `    cached = ImageCache._folder_cache.get(cache_key)` with `    cached = ImageCache.frames(cache_key)`, and replace

```python
    ImageCache._folder_cache[cache_key] = surface_list
    return surface_list
```

  with `    return ImageCache.keep_frames(cache_key, surface_list)`.

- `Code/Support.py`: delete the whole unused function `def import_folder_old(path):` (it loads from disk without the cache; nothing calls it), and put this in its place, directly after `import_folder`:

```python
def import_folder_flipped(path):
    """import_folder's frames mirrored left-right: flipped once, shared by every instance."""
    cache_key = ImageCache.folder_cache_key(os.path.normpath(path) + "__flipped")
    cached = ImageCache.frames(cache_key)
    if cached is not None:
        return cached
    return ImageCache.keep_frames(
        cache_key, [pygame.transform.flip(frame, True, False) for frame in import_folder(path)]
    )
```

- `Code/combat_unit.py` and `Code/Enemy.py`: delete the whole unused method `def import_graphics_left_right_old(self,name):` from each (nothing calls either).

- `Code/combat_unit.py`: replace the whole method `def import_graphics_left_right(self, name):` with:

```python
    def import_graphics_left_right(self, name):
        main_path = f"../Graphics/Monsters/{name}/"
        # Left frames are the right frames mirrored, flipped once and shared by every instance.
        self.animations = {
            animation: {
                "right": import_folder(main_path + animation),
                "left": import_folder_flipped(main_path + animation),
            }
            for animation in ("idle", "move", "attack")
        }
        special_attacks_path = os.path.join(main_path, "SpecialAttacks")
        if os.path.isdir(special_attacks_path):
            for special_attack in os.listdir(special_attacks_path):
                special_attack_path = os.path.join(special_attacks_path, special_attack)
                if os.path.isdir(special_attack_path):
                    self.animations[special_attack] = {
                        "right": import_folder(special_attack_path),
                        "left": import_folder_flipped(special_attack_path),
                    }
```

- `Code/Enemy.py`: replace its `def import_graphics_left_right(self, name):` the same way, with the same body. Both files get `import_folder_flipped` through `from Support import *` (Support has no `__all__`).

- `Code/Level4_tmxdev.py`, in the benchmark wall setup: replace

```python
        ImageCache._folder_cache[ImageCache.folder_cache_key("__benchmark_wall__")] = [wall_surface]
```

  with

```python
        # A rerun of benchmark setup reuses the first wall surface: held surfaces are never replaced.
        wall_surface = ImageCache.keep_frames(
            ImageCache.folder_cache_key("__benchmark_wall__"), [wall_surface]
        )[0]
```

Afterwards, search `Code/` and `tests/` for `ImageCache._` and `ImageCache.cache`. Nothing outside `ImageCache.py` should be left: every read and write goes through its methods.

### Step 8. `Code/render_backend.py`: the atlas packs on first draw

- Add `from ImageCache import ImageCache` after `from benchmark_runtime import BENCHMARK_RUNTIME`.
- Add after `_BATCH_BUF_BYTES = ...`:

```python
# The sprite atlas (GPUBackend._atlas_pack). Sprites over _ATLAS_MAX_SPRITE px on a side
# (ground chunks, roofs, screen overlays) draw from their own texture instead.
_ATLAS_MAX_SIZE = 4096
_ATLAS_MAX_SPRITE = 512
_ATLAS_PAD = 1
_ATLAS_SHELF_STEP = 16
```

- In `GPUBackend.__init__`, replace

```python
        self._white_texture = self._make_texture(np.array([255, 255, 255, 255], dtype=np.uint8), 1, 1)
        self._atlas_texture = None
        self._atlas_uv = {}
        # fill() draws this white texel, tinted. build_atlas moves it into the atlas, so fills
        # join the sprite batch instead of each costing a draw call.
        self._fill_texture, self._fill_uv = self._white_texture, (0.0, 0.0, 1.0, 1.0)
```

  with

```python
        # The sprite atlas: every ImageCache surface is copied in the first time it is drawn
        # (_atlas_uv_for), so sprites batch into a few draw calls a frame.
        self._atlas_size = min(_ATLAS_MAX_SIZE, int(glGetIntegerv(GL_MAX_TEXTURE_SIZE)))
        self._atlas_texture = self._make_texture(
            np.zeros((self._atlas_size, self._atlas_size, 4), dtype=np.uint8),
            self._atlas_size, self._atlas_size,
        )
        self._atlas_uv = {}        # id(ImageCache surface) -> (u0, v0, u1, v1)
        self._atlas_shelves = {}   # shelf height -> [next free x, shelf y]
        self._atlas_top = _ATLAS_PAD
        self._atlas_full_logged = False
        white = pygame.Surface((1, 1), pygame.SRCALPHA)
        white.fill((255, 255, 255, 255))
        u0, v0, u1, v1 = self._atlas_pack(white)
        # fill() draws this texel tinted, sampled at its centre so nearest filtering never
        # reaches the padding beside it: fills batch with the sprites.
        self._white_uv = ((u0 + u1) / 2, (v0 + v1) / 2) * 2
```

- In the same `__init__`, replace the diagnostics comment and three counters

```python
        # Per-frame blit batching diagnostics. A blit only batches (no draw call of its own)
        # when it hits the atlas; the other two paths each force a flush. Split lets us tell a
        # timing-miss (had a cache_key but loaded after build_atlas -> prewarm fixes it) from
        # expected scratch (no stable id: UI/debug/recolored frames). Reset each present().
        self._blit_atlas = 0          # atlas hit -> batched
        self._blit_flush_keyed = 0    # had cache_key but missed atlas (large-cache / atlas-miss)
        self._blit_flush_nokey = 0    # no usable cache_key -> re-uploaded scratch every frame
```

  with

```python
        # Per-frame blit batching diagnostics. A blit only batches (no draw call of its own)
        # when it draws from the atlas; the other two paths each force a flush. Reset each present().
        self._blit_atlas = 0          # ImageCache surface -> atlas, batched
        self._blit_flush_keyed = 0    # cache_key but not ImageCache (large or changing surfaces)
        self._blit_flush_nokey = 0    # no cache_key -> re-uploaded on every draw
```

- Delete the whole method `def build_atlas(self):`, and put these two methods in its place:

```python
    def _atlas_uv_for(self, surface):
        """Where `surface` sits in the atlas, or None. An ImageCache surface is packed the
        first time it is drawn; anything else draws from its own texture."""
        key = id(surface)
        uv = self._atlas_uv.get(key)
        if uv is None and ImageCache.holds(surface):
            uv = self._atlas_pack(surface)
            if uv is not None:
                self._atlas_uv[key] = uv
        return uv

    def _atlas_pack(self, surface):
        """Copy `surface` into the atlas's free space and return its uv; None when it is over
        _ATLAS_MAX_SPRITE on a side or the atlas is full.

        Shelf packing: a shelf holds sprites up to its height, in _ATLAS_SHELF_STEP steps, so
        the frames of one animation share shelves. Nothing is ever removed: ImageCache
        surfaces live for the whole run.
        """
        w, h = surface.get_size()
        if w > _ATLAS_MAX_SPRITE or h > _ATLAS_MAX_SPRITE:
            return None
        size = self._atlas_size
        shelf_h = -(-(h + _ATLAS_PAD) // _ATLAS_SHELF_STEP) * _ATLAS_SHELF_STEP
        shelf = self._atlas_shelves.get(shelf_h)
        if shelf is None or shelf[0] + w + _ATLAS_PAD > size:
            if self._atlas_top + shelf_h > size:
                if not self._atlas_full_logged:
                    self._atlas_full_logged = True
                    print(f"[ATLAS] full at {len(self._atlas_uv)} sprites; "
                          f"later ones draw one call each", flush=True)
                return None
            shelf = [_ATLAS_PAD, self._atlas_top]
            self._atlas_shelves[shelf_h] = shelf
            self._atlas_top += shelf_h
        x, y = shelf
        shelf[0] = x + w + _ATLAS_PAD
        pixels = pygame.image.tostring(surface.convert_alpha(), "RGBA", False)
        glBindTexture(GL_TEXTURE_2D, self._atlas_texture)
        glTexSubImage2D(GL_TEXTURE_2D, 0, x, y, w, h, GL_RGBA, GL_UNSIGNED_BYTE, pixels)
        glBindTexture(GL_TEXTURE_2D, 0)
        return (x / size, y / size, (x + w) / size, (y + h) / size)
```

- In `def draw_shadow(`, replace

```python
        atlas_uv = self._atlas_uv.get(cache_key) if cache_key is not None else None
```

  with

```python
        atlas_uv = self._atlas_uv_for(image)
```

- In `def blit(`, replace

```python
        # area= calls cannot use atlas UV (which covers the full surface, not the sub-rect).
        # Guard kept even though no atlas-eligible sprite currently uses area=, because the
        # assumption is non-obvious and someone adding area= to a sprite blit later shouldn't
        # have to know about this constraint.
        atlas_uv = (self._atlas_uv.get(cache_key)
                    if (cache_key is not None and area is None) else None)
```

  with

```python
        # area= draws a sub-rect, which an atlas uv (the whole surface) can't express.
        atlas_uv = self._atlas_uv_for(src) if area is None else None
```

- In `def fill(`, replace both `self._push_batch(self._fill_texture, dest_rect, self._fill_uv, tint)` with:

```python
            self._push_batch(self._atlas_texture, dest_rect, self._white_uv, tint)
```

- `invalidate_texture` stays as it is: it is for surfaces that change, and ImageCache surfaces never do.

- In `def shutdown(self):`, replace

```python
        texture_ids = [self._texture, self._white_texture]
```

  with `        texture_ids = [self._texture, self._atlas_texture]`, and delete

```python
        if self._atlas_texture is not None:
            texture_ids.append(self._atlas_texture)
```

Afterwards, search `render_backend.py` for `_white_texture`, `_fill_texture`, `_fill_uv` and `build_atlas`. Nothing should be left.

### Step 9. `Code/Main2.py`: no atlas build at level start

In `def start_level(`, delete:

```python
            if hasattr(self.backend, 'build_atlas'):
                self.backend.build_atlas()
```

Afterwards, search the repo for `build_atlas(`. Nothing should be left.

### Step 10. `tests/test_render_backend.py`: prove ImageCache sprites batch

Add after `test_gpu_backend_blit_smoke`:

```python
@requires_gl
def test_gpu_backend_batches_imagecache_sprites(monkeypatch):
    import numpy as np
    from OpenGL.GL import GL_BACK, GL_RGBA, GL_UNSIGNED_BYTE, glReadBuffer, glReadPixels
    from ImageCache import ImageCache

    monkeypatch.setattr(render_backend, "RENDER_BACKEND", "gpu")
    backend = create_backend(64, 64)
    red = pygame.Surface((8, 8), pygame.SRCALPHA)
    red.fill((255, 0, 0, 255))
    blue = pygame.Surface((8, 8), pygame.SRCALPHA)
    blue.fill((0, 0, 255, 255))
    ImageCache.keep_frames(("test_atlas_batch", None), [red, blue])
    draws = []
    real_draw = render_backend.glDrawArrays
    monkeypatch.setattr(
        render_backend, "glDrawArrays", lambda *args: (draws.append(args), real_draw(*args))
    )

    backend.begin_frame((0, 0, 0))
    backend.blit(red, (10, 10))
    backend.blit(blue, (30, 30))
    backend.fill((0, 255, 0), pygame.Rect(50, 50, 8, 8))
    backend._flush_batch()

    assert len(draws) == 1  # two ImageCache sprites and a fill: one draw call
    glReadBuffer(GL_BACK)
    raw = glReadPixels(0, 0, 64, 64, GL_RGBA, GL_UNSIGNED_BYTE)
    arr = np.flipud(np.frombuffer(raw, dtype=np.uint8).reshape(64, 64, 4))
    assert tuple(arr[14, 14, :3]) == (255, 0, 0)
    assert tuple(arr[34, 34, :3]) == (0, 0, 255)
    assert tuple(arr[54, 54, :3]) == (0, 255, 0)
```

### Step 11. Test and measure

Tests:

- `tests/test_render_backend.py -k gpu`, with the Windows video driver (see "Before you start");
- `tests/test_image_cache_scaled.py`;
- `tests/test_import_folder_cache.py`;
- `tests/test_walk_animation_phasing.py` (uses `Enemy`);
- `tests/test_headless_level.py`.

Measure (`$label = "atlas"`). Expect draw calls per sprite to drop sharply.

**Play check (Douglas):** play the ice map past 200 entities under the profiler, the same way as on 2026-11-02:

```
cd C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private\Code
.\sprite_venv\Scripts\python.exe -m cProfile -o ..\logs\perf\play_atlas.prof Main2.py
```

Compare `_resident_texture` calls per frame (133 before) and `_flush_batch` calls per frame (336 before). While playing, check that monsters, items and the HUD look the same as before.

Log, update the status, and commit this phase's files.

---

## Phase 3: RTS sprites through ImageCache

### Step 12. `Code/rts/assets.py`

- Add `from ImageCache import ImageCache` after `import pygame`.
- Above `_cache = {}`, add the comment `# sprite key -> surface: ImageCache's surface for a file, else a flat fallback square.`
- In `def load_sprite(`, replace

```python
    if os.path.isfile(path):
        surf = pygame.image.load(path)
        try:
            surf = surf.convert_alpha()
        except pygame.error:
            pass
    elif key in PLACEHOLDER_SPECS:
        size, color = PLACEHOLDER_SPECS[key]
        surf = pygame.Surface(size, pygame.SRCALPHA)
        surf.fill(color)
    else:
```

  with

```python
    if os.path.isfile(path):
        surf = ImageCache.load_image(path)
    else:
```

`ensure_placeholder_files()` runs just above and writes a file for every `PLACEHOLDER_SPECS` key (or raises), so the deleted branch could never run. The headless `convert_alpha` guard now lives in `ImageCache.load_image`.

Tests: `tests/rts/`. Measure (`$label = "rts"`), log, update the status, then commit.

---

## What to watch

- **Atlas full.** It prints `[ATLAS] full at N sprites` once. The atlas only holds sprites that were actually drawn, where the old build packed all 708 cached surfaces, so the ice map should fit. It also keeps everything drawn in earlier levels of the same run. If it fills, the next step is a second atlas page, not a bigger texture.
- **First appearance of a new monster type** now copies its frames into the atlas as they first show, a few at a time. The disk load at spawn is unchanged.
- **Sprites still off the atlas:** rotated arrows, chest copies, scaled tribey snakes (see Dangers in the notes). Next plan.

## Not in this plan

- Belt HUD text and icons (~4 ms), enemy targeting (~6 ms), sprite updates (~14 ms).
- Loading monster frames before play to remove the spawn-time disk stalls.
- `Enemy.py` is an older copy of `CombatUnit`, used only by `tests/test_walk_animation_phasing.py` and `tribey_geom_probe.py`. This plan keeps it consistent (step 7). Removing it is its own cleanup.
- `BenchmarkMetrics.record_gpu_cache_hit` and its counter are never called; that belongs to a benchmark cleanup.
