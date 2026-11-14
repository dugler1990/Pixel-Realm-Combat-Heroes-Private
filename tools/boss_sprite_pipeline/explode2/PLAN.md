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
| 1 | Paint the outfit at rest: one command, `repaint/paint_outfit.py` (views → gen → project → diag; bad paintings repainted by rule) | local + Leonardo nano-banana-2 (user's key) | in progress |
| 2 | ~~Pose it for the cut~~ — measured: +0.6 points coverage only | — | **dropped** |
| 3 | Render the greedy camera directions (75° facing limit, `greedy_dirs_f75.json`) of the painted outfit | local | **done** (128 dirs; measured: 32 are enough — see step 5) |
| 4 | SAM3 on every view | pod | **done** (3 shards, 29 min for 226 views) |
| 5 | Combine: each face's part from the views facing it head-on (`explode_label.py --facing-power 8`) | local | **done**; the cut does not improve past 16–32 dirs (borders wobble 4–6 % per doubling) |
| 6 | Hidden inner layer takes the part of the outside surface directly above it | local | todo |
| 7 | Snap part borders to the nearest crease where the plates meet (`explode_label.py --crease-snap`, band 0.8 % h) | local | **done** |
| 8 | HoloPart: each piece whole — fills what neighbours hid (a piece worn without its neighbours, inventory) | pod | **done** (run on the 128-dir cut) |
| 9 | Clean pieces: drop loose bits, tidy edges (`hole_check.py --clean --fix`) | local | torso done on the plain cut piece (the merge added 3× the holes); other pieces todo |
| 10 | Rigid export: each piece aligned to `barb_final`, own rigged GLB; plate → 1 bone, pauldron ½ collarbone ½ upper arm, skirt hips → thighs | local | todo |
| 11 | Hide the body under each worn piece | local | todo |
| 12 | Breastplate fit: widest chest over all poses + small gap (`fit_piece.py`) | local | **done** for the full plate's torso |
| 12b | Every piece: `fit_set.py` (per-vertex push + tuck) — kept as an option only: it bends the plates (shins, skirt). Replace with a fit that never changes a piece's shape | local | **to replace** |
| 13 | Swap test: `barb_final` with/without pieces, mixing both outfits, 6 poses | local | todo |

## Next: an undergarment under the armour (planned 2026-11-04)

Real plate is worn over a padded arming doublet / gambeson and hose, so the gaps at the joints show black quilted
cloth, not skin. Keep the current bare version as well (both are variants of the base).

| # | Step | Where | Status |
|---|---|---|---|
| U1 | Reference: the barb's concept art edited into a black padded gambeson (quilted, sleeves to the wrist) and black hose; head, beard, hands, feet as they are | Leonardo Nano (~$0.04) | todo |
| U2 | Look file `repaint/looks/barb_gambeson.json` (black quilted cloth wording, which views) | local | todo |
| U3 | Repaint `barb_final_nb` with it: `paint_outfit.py` (views → gen → project with roles → diag) → a body variant with the same mesh and rig, new texture | local + Leonardo (~$0.80) | todo |
| U4 | Armour over it: the fitted set and the tuck are unchanged (same geometry) — render the same checks with the gambeson body | local | todo |
| U5 | Only if the garment must show real thickness when worn alone: a gambeson mesh (TRELLIS, pod), rigged (`outfit_skeleton.py`), fitted as the innermost layer by `fit_set.py` (armour stands above it), body tucked under it | pod + local | later |

Rules: tell the user to stop the pod the moment pod results are copied back; one heavy local job at
a time; max quality settings.
