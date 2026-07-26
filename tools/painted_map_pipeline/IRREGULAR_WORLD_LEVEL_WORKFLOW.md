# Irregular World-Level Generation Guardrails

This workflow converts a world-map image and an irregular polygon plan into
reproducible AI-generation packages. Geometry, scale, blank padding, and shared
pixels are controlled by code. The image generator renders detail inside that
contract.

## Inputs

The current authoritative inputs are:

- `levels/Frostreach/Generated_image the one.png`
- `levels/Frostreach/proposed_25_level_areas.csv`

The labelled review overlay is regenerated from those inputs during `prepare`;
it is not a geometry input.

Each CSV row supplies a crop rectangle, core polygon, generation polygon, and
connections. Polygon strings use global world-image pixels encoded as
`x:y|x:y|...`.

## Geometry contract

- **Crop rectangle:** source-map rectangle placed on the output canvas.
- **Core polygon:** territory principally owned by the level.
- **Generation polygon:** complete area that may contain generated art.
- **Shared overlap:** intersection of two connected generation polygons.
- **Locked overlap:** accepted neighbor pixels inside a shared overlap.
- **Pending mask:** generation mask minus locked overlap.

`overlap_buffer_px` is retained as planning metadata. The generation polygons
and declared connections are the actual overlap authority.

Boat connections are topological links and do not require geographic overlap.

## Configuration

See `world_levels/config.example.json`. A run config specifies:

- world map, plan, review overlay, and output root;
- one scale for the complete run;
- explicit or derived canvas dimensions;
- crop placement and canvas margin;
- outside color and source resampling;
- manual or automatic approval;
- retry and failure behavior;
- image-generation backend and style prompt.

With `canvas.mode = "explicit"`, width and height are required. With
`canvas.mode = "derived"`, code chooses the smallest canvas that holds the
largest scaled crop plus the configured margin. Individual levels are never
scaled independently to fill the canvas.

## Coordinate conversion

World coordinates first enter one scaled-global integer grid:

```text
global_x = round_half_up(world_x * scale)
global_y = round_half_up(world_y * scale)
```

Each level then translates that grid into its canvas:

```text
local_x = global_x - scaled_crop_left + canvas_offset_x
local_y = global_y - scaled_crop_top  + canvas_offset_y
```

Scaled crop edges are calculated from global edge coordinates, not by rounding
the width separately. This keeps shared boundaries identical.

## Exact mask generation

`prepare` performs these steps for every level:

1. Transform core and generation vertices to scaled-global coordinates.
2. Translate them into the level canvas.
3. Rasterize binary, non-antialiased `L` masks using values `0` and `255`.
4. Confirm every core pixel is inside the generation mask.
5. Calculate `outside = NOT generation`.
6. Initially calculate `pending = generation AND NOT locked`.

Connected pair overlaps are calculated in a shared scaled-global bounding box:

1. Rasterize both generation polygons in that same box.
2. Calculate their bitwise intersection.
3. Store the global bounding box and intersection pixels.
4. Translate that one raster into each level canvas.

The overlap is never independently rasterized in the two local canvases.

## Prepared package

```text
generated/world_levels/<run>/
  config.resolved.json
  run.json
  events.jsonl
  plan_validation.json
  plan_validation_overlay.png
  levels/<id>/
    manifest.json
    base_template.png
    generation_input.png
    locator.png
    source/world_crop.png
    masks/core.png
    masks/generation.png
    masks/outside.png
    masks/pending.png
    masks/overlaps/<neighbor>.png
    locked/canonical_overlap.png
    locked/canonical_overlap_mask.png
    jobs/attempt_NNN/
    attempts/attempt_NNN/
    accepted/image.png
```

`base_template.png` contains the scaled source crop inside the generation mask
and the configured blank color outside it.

## Embedding accepted neighbor art

`refresh` rebuilds an unfinished level from its clean base template:

1. Find all connected neighbors whose state is `accepted`.
2. Compute each shared-global overlap.
3. Map the overlap box into the accepted neighbor canvas.
4. Extract those exact RGBA pixels.
5. Map the same global box into the target canvas.
6. Paste the pixels through the shared overlap mask.
7. Union the pasted pixels into the target locked mask.
8. Recalculate the pending mask.
9. Write the composed result to `generation_input.png`.

The primary image passed to the AI therefore already contains the generated
padding from accepted neighbors in its exact final position. Neighbor art is
not merely attached as a separate reference.

If accepted contexts reach the same target pixel, the earliest canonical value
is retained. The manifest records every contributing accepted image and hash.

## Immutable jobs

Creating a job snapshots:

- `input.png`, which is the composed generation input;
- generation, pending, and locked masks;
- exact locked RGBA pixels;
- locator image and deterministic prompt;
- canvas size, context revision, neighbor sources, and hashes.

Jobs live under monotonically numbered attempt directories and are never
rewritten. An output generated from a stale context revision is rejected.

## Ingestion and acceptance

Ingestion verifies the output size, job identity, input hash, and context
revision. It rejects transparent holes inside the generation mask. It then:

```text
normalized[outside generation] = configured blank color
normalized[locked mask] = exact locked neighbor pixels
```

The raw and normalized attempts are retained. In manual mode the normalized
candidate waits for `accept`; in automatic mode it is accepted immediately
after deterministic validation.

Acceptance copies the normalized image to `accepted/image.png`, records its
hash and acceptance order, and automatically refreshes every unfinished
connected package.

## Batch execution

Examples:

```bash
python -m tools.painted_map_pipeline.world_levels.orchestrate prepare \
  tools/painted_map_pipeline/world_levels/config.example.json

python -m tools.painted_map_pipeline.world_levels.orchestrate run \
  generated/world_levels/frostreach --levels 01-05

python -m tools.painted_map_pipeline.world_levels.orchestrate run \
  generated/world_levels/frostreach --levels 01,04,06

python -m tools.painted_map_pipeline.world_levels.orchestrate resume \
  generated/world_levels/frostreach
```

For each selected level, `run` performs:

```text
refresh accepted context
    -> create immutable job
    -> invoke generation backend
    -> ingest and normalize
    -> accept or pause for approval
    -> refresh all connected unfinished packages
```

Refresh propagation is not restricted to the selected range. If accepted level
05 touches unselected level 06, level 06 receives the new overlap immediately.

A manifest-only backend prepares the next immutable job and pauses for an
external image. Callable providers can continue automatically. Manual approval
pauses the batch after ingestion; `resume` continues after acceptance.

## Commands

```text
prepare CONFIG
refresh ROOT [--levels 01-05]
job ROOT --level 04
ingest ROOT --level 04 --image IMAGE [--attempt N] [--accept]
accept ROOT --level 04 [--attempt N]
run ROOT [--levels SELECTOR | --region NAME | --state STATE]
resume ROOT
status ROOT
validate ROOT
```

## State and recovery

States are:

```text
unprepared -> prepared -> ready -> generating -> generated -> accepted
                                      |
                                      -> failed
```

`run.json` stores current state. `events.jsonl` is append-only. JSON state
writes use temporary files followed by atomic replacement. Attempts and
accepted images are not overwritten. Provider failures are retried according
to configuration; `resume` selects prepared, ready, and failed levels.

## Continuity invariant

For any connected accepted pair:

```text
pixels_A(shared_overlap) == pixels_B(shared_overlap)
```

`validate` maps both accepted images through the same shared-global overlap and
reports any differing pixels in `continuity_report.json`.

## Review boundary

The tooling guarantees coordinates, masks, scale, blank exterior, exact
accepted padding, reproducible packages, and pixel continuity. Art quality,
terrain richness, monumental scale, route quality, and fantasy tone remain
review decisions made against the normalized candidate.
# Deterministic Irregular World-Level Art Workflow

This document defines how a world-map illustration and polygon plan become
multiple connected TMX levels without relying on an image generator to guess
scale, placement, or continuity.

The image generator is an art renderer. It is **not** responsible for geometry,
coordinate transforms, level boundaries, overlap placement, chunk placement, or
seam validation. Those responsibilities belong to deterministic scripts.

This workflow extends:

- `LEVEL_ART_WORKFLOW.md`
- `AGENT_WORKFLOW.md`
- `collision/COLLISION_WORKFLOW.md`

## Current Frostreach inputs

- World image:
  `levels/Frostreach/Generated_image the one.png`
- Level plan:
  `levels/Frostreach/proposed_25_level_areas.csv`
- Review overlay:
  `levels/Frostreach/proposed_25_irregular_level_divisions.png`

The current generated level images are style studies. They are not canonical
production geometry and must not be used as coordinate authorities.

## Hard rules

1. There is one global world-image coordinate system.
2. Every level uses the same global scale factor.
3. A level is never independently stretched to fill its canvas.
4. TMX/background canvases are rectangular.
5. Playable ownership is defined by an irregular `core_polygon`.
6. Generation context is defined by a larger `generation_polygon`.
7. Pixels outside the generation polygon are transparent or black.
8. Shared overlap pixels are copied exactly. They are never independently
   regenerated by both levels.
9. A generated neighbor may influence art only inside its exact shared overlap
   and a small inward blending band.
10. No generated image is accepted until automated coordinate, mask, scale,
    coverage, and overlap checks pass.
11. SAM3 and TMX placement use manifest coordinates. They must never infer
    placement from image appearance.

## Coordinate systems

### World source coordinates

The accepted Frostreach world image is `1536 x 1024` pixels.

The CSV polygons and crop rectangles are expressed in this coordinate system.
The origin is the image's upper-left corner:

```text
(0, 0) ----------------------> +x
  |
  |
  v
 +y
```

### Canonical art scale

Choose one integer scale for an entire production pass:

```text
master_x = world_x * scale
master_y = world_y * scale
```

Recommended first production test:

```text
scale = 12
```

The current maximum level crop is `613 x 333` source pixels. At scale 12, a
standard maximum canvas is:

```text
7356 x 3996 pixels
```

Scale 16 would produce a maximum canvas of `9808 x 5328`, which is more
expensive and should follow only after the scale-12 workflow is validated.

### Level-local coordinates

Each level has a rectangular crop origin and an optional placement offset
inside the standard canvas:

```text
local_x = (world_x - crop_x) * scale + canvas_offset_x
local_y = (world_y - crop_y) * scale + canvas_offset_y
```

This transform must be written into the level manifest and reused by art,
collision, transitions, SAM3, chunking, and TMX insertion.

## Polygon meanings

The CSV contains two different polygons:

### Core polygon

`core_polygon_points_px` defines the territory owned by the level.

- It is the default camera/playable ownership boundary.
- Transitions occur before the player reaches unsupported canvas space.
- Neighboring core polygons should not materially overlap.

### Generation polygon

`generation_polygon_points_px` defines all terrain that must be rendered for
the level.

- It includes the core territory.
- It includes the overlap needed to transition to connected levels.
- It may include non-playable visual terrain.
- Pixels outside it are transparent or black.

### Pair overlap

For connected levels A and B:

```text
shared_overlap = generation_polygon_A ∩ generation_polygon_B
```

The shared overlap is computed from masks. It is not guessed from bounding
boxes and is not assumed to be a straight edge.

Boat/special links may intentionally have no geographic overlap.

## Standard level package

Each prepared level should use this structure:

```text
generated/world_levels/frostreach/<level_id>/
  manifest.json
  source/
    world_crop.png
    world_crop_upscaled.png
  masks/
    core.png
    generation.png
    outside.png
    overlaps/
      <neighbor_id>.png
  locked/
    canonical_overlap.png
    canonical_overlap_mask.png
  control/
    geography.png
    terrain_classes.png
    height_hint.png
  generation/
    jobs.json
    tiles/
      <tile_id>/
        source.png
        mask.png
        locked_context.png
        prompt.txt
        generated.png
  assembled/
    albedo.png
    coverage_preview.png
    overlap_preview.png
  export/
    chunks/
    chunks_manifest.json
```

## Orchestrator lifecycle

The guardrail tooling should expose one rerunnable orchestration entry point
with explicit subcommands. It should not rely on chat history or an agent
remembering which images were generated.

Proposed interface:

```bash
python -m tools.painted_map_pipeline.world_levels.orchestrate prepare \
  --world-image "levels/Frostreach/Generated_image the one.png" \
  --plan levels/Frostreach/proposed_25_level_areas.csv \
  --output generated/world_levels/frostreach \
  --scale 12

python -m tools.painted_map_pipeline.world_levels.orchestrate ingest \
  --root generated/world_levels/frostreach \
  --level 04 \
  --job tile_02_01 \
  --image /absolute/path/to/generated.png

python -m tools.painted_map_pipeline.world_levels.orchestrate refresh \
  --root generated/world_levels/frostreach

python -m tools.painted_map_pipeline.world_levels.orchestrate status \
  --root generated/world_levels/frostreach

python -m tools.painted_map_pipeline.world_levels.orchestrate validate \
  --root generated/world_levels/frostreach
```

These commands do not exist yet. They define the implementation target.

### First run: `prepare`

`prepare` consumes:

- the clean world image;
- the CSV plan;
- the chosen global scale;
- generation tile dimensions;
- prompt/style configuration.

It then:

1. validates the plan;
2. creates every standardized level canvas;
3. rasterizes core and generation masks;
4. computes every pairwise overlap mask;
5. creates upscaled geography/control images;
6. creates internal generation jobs;
7. creates placeholder locked-overlap images;
8. writes prompts and manifests;
9. marks seed jobs as ready.

The review illustration with polygon labels is not a machine input. It should be
regenerated from the world image and CSV so it cannot drift from the plan.

### Image generation

An agent or person reads one prepared job package and generates exactly one
image with the required dimensions.

The generator receives:

- exact source/control crop;
- locator image;
- generation mask;
- immutable locked pixels and mask;
- accepted neighbor context;
- terrain/height hints;
- deterministic prompt;
- output dimensions.

The generator does not choose the crop, scale, placement, or overlap.

### Accepting work: `ingest`

Generated files should not become canonical merely because they appear in a
folder. `ingest` is explicit and must:

1. verify level and job IDs;
2. verify exact dimensions;
3. verify generation-mask coverage;
4. restore immutable locked pixels;
5. assemble the job into the level candidate;
6. run local seam and continuity checks;
7. record hashes and provenance;
8. mark the job accepted only after validation.

This prevents an old, incorrectly sized, or experimental image from being
silently propagated to neighboring levels.

### Rerun after accepted images: `refresh`

`refresh` scans manifests for newly accepted jobs and levels. For each accepted
result it:

1. maps accepted pixels back into canonical world coordinates;
2. extracts exact pixels for every connected overlap;
3. writes those pixels into each unfinished neighbor's
   `locked/canonical_overlap.png`;
4. updates the neighbor's immutable overlap mask;
5. refreshes neighbor context images;
6. rebuilds affected generation-job packages and prompts;
7. marks newly constrained jobs as ready;
8. records which accepted output supplied each locked pixel.

This is the deterministic version of "generate one map, then give its border to
the next map."

Accepted overlap pixels are never reinterpreted. They are copied exactly.

### Multiple completed neighbors

If a new level touches several accepted maps, `refresh` unions all neighbor
overlap masks into one locked mask before preparing generation jobs.

If two accepted neighbors supply different pixels for the same canonical world
location:

1. mark the target level blocked;
2. write a conflict image and report;
3. do not generate the target;
4. resolve the conflict through a seam repair pass;
5. rerun `refresh`.

The image generator must never be asked to choose between conflicting accepted
neighbors.

### State machine

Every level and internal generation job should use explicit states:

```text
planned
prepared
ready
generated
validated
accepted
propagated
blocked
rejected
```

Only `accepted` artifacts may supply canonical pixels to neighbors.

`status` should show:

- accepted levels and jobs;
- ready jobs;
- jobs waiting for neighbor context;
- blocked overlap conflicts;
- stale packages requiring refresh;
- validation failures.

### Idempotency

Running `prepare`, `refresh`, or `validate` repeatedly with unchanged inputs
must produce identical manifests and masks.

The orchestrator must use content hashes to avoid:

- overwriting accepted art;
- rebuilding unaffected packages;
- propagating the same result twice;
- treating stale context as current;
- changing coordinates because of filesystem ordering.

## Deterministic pipeline

### Stage 1: Validate the world plan

Code must reject the plan when:

- polygon coordinates exceed the source image;
- a polygon is invalid or self-intersecting;
- a core polygon contains disconnected islands unintentionally;
- two core polygons materially overlap;
- a non-boat connection has no generation overlap;
- a land connection is not symmetric in the CSV;
- a crop rectangle does not contain its generation polygon;
- unassigned mainland coverage exceeds the accepted tolerance.

The validator should emit:

```text
plan_validation.json
plan_validation_overlay.png
```

### Stage 2: Prepare standardized canvases

For every level:

1. Read its crop and polygons from the CSV.
2. Apply the global scale.
3. Place the crop into the standard canvas without stretching.
4. Rasterize core and generation masks.
5. Fill outside-generation pixels with transparent black.
6. Upscale the world crop only as a structural control image.
7. Write the exact world-to-local transform to `manifest.json`.

No image-generation decision occurs during this stage.

### Stage 3: Prepare exact neighbor overlaps

For each connection:

1. Compute the shared world-space overlap mask.
2. Transform it into both level-local canvases.
3. If one neighbor is already accepted, extract those exact pixels.
4. Store them as immutable canonical overlap pixels.
5. Hash the overlap image and record the hash in both manifests.

When several completed neighbors touch a new level, all accepted overlap pixels
are placed before any new art is generated.

If accepted neighbors disagree at a multi-level corner, stop. Do not ask the
generator to choose between them. Repair the canonical overlap first.

### Stage 4: Split the canvas into generation jobs

The art service cannot generate a `7356 x 3996` image in one request. Code must
create a regular internal generation grid.

Recommended working job size:

```text
1536 x 1024
```

Each generation job contains:

- the exact upscaled source-map control crop;
- the local generation mask;
- already accepted locked pixels;
- neighbor overlap context;
- terrain/height hints;
- a generated prompt containing level-specific requirements;
- fixed output dimensions and placement coordinates.

Internal job overlap should be large enough for seam repair, for example
`192-256` working pixels. This is separate from cross-level overlap.

### Stage 5: Generate art

The agent or image provider may decide:

- texture;
- local geological detail;
- identifiable props;
- material richness;
- atmosphere within the approved art rules.

The agent may not decide:

- canvas dimensions;
- crop origin;
- polygon shape;
- global scale;
- locked overlap pixels;
- coastline, mountain-range, river, road, or exit placement;
- output placement.

The source/control image is the composition authority. Neighbor images are
edge context only.

### Stage 6: Ingest generated jobs

The ingest script must:

1. Verify exact output dimensions.
2. Reject unexpected alpha or black holes inside the requested mask.
3. Restore locked overlap pixels exactly.
4. Blend only within the designated inward blend band.
5. Assemble jobs using manifest coordinates.
6. Preserve generation-mask transparency.
7. Record provider, prompt, source hash, output hash, and timestamp.

An agent must never manually choose image coordinates.

### Stage 7: Automated continuity validation

For connected levels A and B, transform both accepted images back into global
master coordinates and compare the shared overlap.

Required invariant:

```text
pixels_A(shared_overlap) == pixels_B(shared_overlap)
```

The exact locked overlap should have zero pixel difference.

The validator should additionally check:

- matching scale;
- matching world-coordinate placement;
- no missing coverage inside generation polygons;
- no art outside generation polygons;
- no disconnected playable masks;
- no seam-crossing feature endpoint without a matching continuation;
- no camera-visible black area reachable from the core.

Outputs:

```text
continuity_report.json
continuity_diff.png
global_assembled_preview.png
```

Semantic checks for roads, rivers, cliffs, and exits should reuse the existing
seam tools:

- `make_seam_contexts.py`
- `seam_issues.py`
- `apply_seam_patch.py`

### Stage 8: Extract level background chunks

After a full level albedo is accepted:

1. Divide it into the required runtime background grid, such as 8 by 5.
2. Preserve exact world rectangles in the chunks manifest.
3. Do not resize individual chunks.
4. Build an assembled preview and verify it pixel-matches the accepted level.

Reuse:

- `slice_chunks.py`
- `assemble_preview.py`
- `insert_chunks.py`

### Stage 9: SAM3 and gameplay layers

Run SAM3 only after visual art and seams are accepted.

SAM3 output is placed using `world_rect` from the chunks manifest, as documented
in `collision/COLLISION_WORKFLOW.md`.

Generate or author:

- blocking polygons;
- water/deep-water polygons;
- unstable ice;
- slippery zones;
- canopy/overhead regions;
- spawn regions;
- transition triggers;
- named arrival points.

The final TMX remains rectangular. Collision, camera limits, darkness, and
terrain enforce the irregular playable polygon.

## Runtime transition contract

Each connected map pair needs:

- a named source transition;
- a named destination spawn;
- an exact shared-art overlap;
- a trigger before the player can see unsupported canvas;
- a reverse-transition cooldown;
- camera clamping to valid rendered terrain;
- a short weather/fade handoff when needed.

Only one TMX map needs to be loaded at a time.

## Required guardrail scripts

The following orchestration should be implemented before mass generation:

```text
tools/painted_map_pipeline/world_levels/
  validate_plan.py
  prepare_level.py
  prepare_generation_jobs.py
  ingest_generation_job.py
  validate_continuity.py
  export_level_chunks.py
```

Suggested responsibilities:

### `validate_plan.py`

- Parse the CSV.
- Validate polygons, connections, coverage, and overlaps.
- Render the authoritative review overlay.

### `prepare_level.py`

- Apply global scale.
- Build standard canvas and masks.
- Compute world-to-local transforms.
- Insert accepted neighbor overlap pixels.

### `prepare_generation_jobs.py`

- Slice the standard canvas into working-size AI jobs.
- Build control/reference packs.
- Generate deterministic prompts.

### `ingest_generation_job.py`

- Validate dimensions.
- Restore locked pixels.
- Composite the generated result at manifest coordinates.
- Record hashes and provenance.

### `validate_continuity.py`

- Compare adjacent level overlap pixels in global coordinates.
- Fail on any exact-overlap mismatch.
- Build a global continuity preview.

### `export_level_chunks.py`

- Split accepted level art into runtime chunks.
- Reuse the existing TMX painted-ground insertion contract.

## Generation order

Do not independently generate all 25 levels.

1. Choose one seed level.
2. Accept its art.
3. Prepare adjacent levels with the seed's overlap locked.
4. Work breadth-first through the connection graph.
5. Refresh context after every accepted level.
6. Stop immediately when a continuity validator fails.

For the current test, levels 03, 04, and 06 should be regenerated through this
workflow as one coordinate-controlled cluster. Existing attempts should remain
style references only.

## Acceptance checklist

A level is not production-ready until:

- [ ] CSV plan validation passes.
- [ ] Global scale and canvas transform are recorded.
- [ ] Core and generation masks are present.
- [ ] All completed neighbor overlaps are locked.
- [ ] Generated jobs pass dimension and coverage checks.
- [ ] Assembled level contains no holes.
- [ ] Exact neighbor overlap pixel comparison passes.
- [ ] Global assembled preview is geographically correct.
- [ ] Runtime chunk assembly pixel-matches the accepted level.
- [ ] SAM3 output aligns through manifest world rectangles.
- [ ] TMX loads with expected PaintedGround and gameplay layers.
- [ ] Camera cannot expose transparent/black canvas.

## What must remain human- or agent-reviewed

Deterministic code can guarantee geometry and pixel continuity. It cannot judge:

- whether a mountain feels monumental;
- whether terrain is visually repetitive;
- whether small details represent meaningful objects;
- whether a route is enjoyable;
- whether the art matches the intended fantasy tone.

Those remain review decisions, but they happen only after the deterministic
contracts pass.
