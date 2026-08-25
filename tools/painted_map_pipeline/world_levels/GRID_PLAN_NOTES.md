# How a painted world map becomes levels

Written after spending an afternoon failing to find the step that makes `plan.csv`, because it
never existed as a file. Three of the four stages were committed tools; the plan generator was
written as throwaway code inside a session and vanished with it. If you are reading this
wondering where the grid comes from, it is `make_grid_plan.py`, and this is the chain it sits in.

## The four stages

```
concept / previous pass
        |  composed.png                       (the small painted source)
        v
[1] bootstrap_from_png.py                     SCALE
        --width-tiles 33 --height-tiles 18 --tile-size 550
        |  background.png  18150 x 9900       (33*550 x 18*550)
        v
[2] make_grid_plan.py                         DIVIDE
        --cols 6 --rows 5
        |  plan.csv  24 levels                (6x5 = 30 cells, 6 all black)
        v
[3] orchestrate prepare <config>.json         PACKAGE
        |  levels/NN/{source,masks,generation_input,locator,dense_template}
        v
[4] orchestrate run  /  review_run            GENERATE
        |  one gpt-image-2 call per level, padding carried between neighbours
```

## The scale

The native tile is **110px** (`frostreach_prototype_tiles.png` is 2750x1100 = 25x10 tiles).
`bootstrap_from_png --tile-size 550` renders at **5x**. That is the only place the map is
enlarged; `pixels_per_world_pixel` in the run config is 1 and does nothing.

The model is not reproducing source detail at that size, it is inventing it: measured on level
02, detail (laplacian variance) inside the polygon went 29.1 -> 335 in a single pass.

## Why the grid and the scale are one decision

Every level is rendered on one canvas, and the canvas is capped by gpt-image-2 at **8.3 MP,
3840px max edge, edges a multiple of 16**. The sunspine canvas is 3344x2288 = 7.65 MP, i.e. 92%
of the cap. There is no headroom.

So detail per unit of original map = canvas pixels / world area per cell, and the canvas cannot
grow. **More detail therefore requires smaller cells, which requires more cells, which requires
scaling the map up by the same factor.** They are not independent knobs.

Because area scales with the square of linear scale:

| grid  | cells | linear detail | tile-size | map         |
|-------|-------|---------------|-----------|-------------|
| 6x5   | 30    | 1.00x         | 550       | 18150x9900  |
| 7x6   | 42    | 1.24x         | 681       | 22484x12264 |
| 9x7   | 63    | 1.45x         | 797       | 26302x14346 |
| 12x10 | 120   | 2.00x         | 1100      | 36300x19800 |

12x10 is the only one that keeps the current cell size exactly; it is a clean 2x of everything.
Cells come out canvas-shaped only when `cols/rows` is near **1.254** (map aspect 1.833 over
canvas aspect 1.462) -- otherwise part of every canvas is wasted.

## What plan.csv actually contains

Columns: `id,name,region,crop_x_px,crop_y_px,crop_width_px,crop_height_px,overlap_buffer_px,`
`core_polygon_points_px,generation_polygon_points_px,connections`

Per cell, `make_grid_plan.py` does exactly this:

- cells tile the map exactly (`col*W//cols` boundaries)
- **core** = the landmass polygon clipped to the cell rectangle
- cells whose land is under 1% of a cell are dropped
- **generation** = the core GROWN by `overlap_buffer` (150), clipped to the expanded cell
- **crop** = the generation's bounding box plus 4px, clamped to the map
- **connections** = orthogonal neighbours whose generation polygons overlap. Orthogonality
  alone is wrong (two cells side by side can have land 2000px apart); overlap alone is wrong
  (it links diagonal cells whose padded boxes clip at a corner)
- the **canvas** is the largest crop, each edge rounded up to a multiple of 16. It is printed,
  and belongs in the run config

### Why the generation is grown from the core, and not clipped separately

The obvious construction is `core = land ∩ cell` and `generation = land ∩ expanded cell`. It
does not work, and this cost most of a day. Both cut the same coastline, but each quantises
that diagonal over a different range and each vertex rounds to a whole pixel on its own, so
the core ends up fractionally outside the generation -- 1367px of it on one level -- and
`prepare` rejects the pair with *"core polygon is not contained by generation polygon"*.

Nothing patches that reliably. Finer simplification, slack, unioning the core back in, rounding
outward -- each removed some failures and left others, because the two polygons were never the
same line to begin with. Growing one from the other has nothing to reconcile: a grown shape
contains what it grew from, always.

The cost is that the coastline must already BE a polygon, which is what `snap_landmass.py` is
for, and that the generation extends past the coast into black rather than stopping at it.
That second one is free: there are no neighbours out there to share padding with.

## Running it

```
python3 -m tools.painted_map_pipeline.world_levels.snap_landmass \
    levels/Frostreach/<level>/background.png \
    --out levels/Frostreach/<level>/background_snapped.png \
    --polygon-out levels/Frostreach/<level>/landmass_polygon.json \
    --overlay /tmp/snap_overlay.png --max-vertices 10

python3 -m tools.painted_map_pipeline.world_levels.make_grid_plan \
    levels/Frostreach/<level>/background_snapped.png \
    --landmass-polygon levels/Frostreach/<level>/landmass_polygon.json \
    --cols 7 --rows 6 --region "Sunspine Dunes" --name-prefix "Sunspine" \
    --out generated/world_levels/<run>/plan.csv \
    --overlay generated/world_levels/<run>/plan_overlay.png
```

snap_landmass takes about 3 minutes (it writes a 276 MP PNG). make_grid_plan takes **under a
second** -- it is arithmetic on ten vertices -- plus about a minute if you ask for the overlay,
which renders the full-size map. It prints the canvas size to put in the run config.

**The run config's `world_map` must be the SNAPPED image**, the one the plan was built from.
Point it at the original and every crop is cut from an image whose coast does not match the
coordinates.

**Look at the overlay** -- the plan is hard to read as numbers and obvious as a picture.

### How faithful is it to the original 6x5 plan

Regenerating the existing plan and diffing, which is the only real test:

| | |
|---|---|
| level count, ids | 24/24 |
| canvas 3344x2288 | exact |
| connections | 24/24 |
| core polygons | 6/24 exact, rest within 1-4px |
| crops | 8/24 exact |

The overlays are indistinguishable. The six exact cores are the interior cells that are plain
rectangles; coastal cells differ by a few pixels because the original traced the shoreline by
some route that could not be recovered -- land threshold was swept 0-255 and epsilon 0.001-0.05
and neither reproduces it. Three levels (05, 12, 24) come out with one fewer vertex, dropping a
small coastline feature.

That is immaterial for a NEW grid, where the coast is re-traced anyway. It would matter only if
you needed to regenerate the existing plan and keep current art aligned to it.

## Things that cost time before, so they are written down

- `input_fidelity` is rejected outright by gpt-image-2; the model is always high fidelity.
- The API `mask` polarity is the **reverse** of OpenAI's documentation. **Opaque (alpha 255) is
  the region it repaints**; transparent is left alone. Measured: alpha 255 over the polygon gave
  footprint IoU 0.970, the documented polarity gave 0.305 and full bleed. See `_alpha_mask`.
- The mask holds the shape, so the silhouette reference image and the outline paragraphs were
  removed from the prompt -- they were showing the model the same polygon twice.
- Remaining shape error after the mask is a soft fringe (95% of it within 25px of the edge), so
  `cut_to_mask` takes 0.970 -> 0.993 with no warping. `cut_iou` in the checks reports what a cut
  would give; a low `cut_iou` means holes, which a cut cannot fix.
