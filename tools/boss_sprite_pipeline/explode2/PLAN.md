# Plan: painted, posed, near-full-coverage explode → rigid swappable pieces

Agreed 2026-11-02. A distinct attempt, not a rerun of the v1 explode: old scripts are reused only where a
step is identical (the SAM call, the render loop). Run on the full plate (`gear_test/barb_fullplate_from_front.glb`) first, then the
breastplate (`gear_test/barb_breastplate_from_front.glb`). Status is kept here; what happened goes in
`PROCESS_explode2.md` (this folder).

Base for everything: `generated/bosses/barb/rigfix/barb_final.glb` (painted 4096, bone-heat rig).
Coverage facts (Step 10 of PROCESS_explode.md): 96 views see 52.8 % of the outfit's surface, 68.2 % is
the ceiling for any outside camera, the other 31.8 % is a covered inner layer.

| # | Step | Where | Status |
|---|---|---|---|
| 0 | Give the outfit the base skeleton: `outfit_skeleton.py` (align, bone heat on outfit+body proxy) | local | **done** (full plate) |
| 1 | Paint the outfit at rest with `repaint.py` (views → gen → project) | local + OpenAI (user's key) | todo |
| 2 | ~~Pose it for the cut~~ — measured: +0.6 points coverage only | — | **dropped** |
| 3 | Render the greedy camera directions (`greedy_dirs.json`: 128 → 96 % of the visible ceiling, vs 77 % for the regular 96) of the painted outfit | local | todo |
| 4 | SAM3 on every view | pod | todo |
| 5 | Combine: each face's part from the views facing it head-on; target ≈ 100 % of the outside (`explode_visibility.py` on the posed mesh) | local | todo |
| 6 | Hidden inner layer takes the part of the outside surface directly above it | local | todo |
| 7 | Snap part borders to the nearest crease where the plates meet | local | todo |
| 8 | HoloPart: each piece whole (only for showing a piece alone) | pod | todo |
| 9 | Clean pieces: drop loose bits, tidy edges | local | todo |
| 10 | Rigid export: each piece aligned to `barb_final`, own rigged GLB; plate → 1 bone, pauldron ½ collarbone ½ upper arm, skirt hips → thighs | local | todo |
| 11 | Hide the body under each worn piece | local | todo |
| 12 | Breastplate fit: widest chest over all poses + small gap | local | todo |
| 13 | Swap test: `barb_final` with/without pieces, mixing both outfits, 6 poses | local | todo |

Rules: tell the user to stop the pod the moment pod results are copied back; one heavy local job at
a time; max quality settings.
