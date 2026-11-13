# explode2: what is where

How to run it: `PROCESS_explode2.md`, section "Method". What was tried and why it was dropped: its last
section, "Tried and dropped".

## Used by the method (run these)
| Script | Step |
|---|---|
| `outfit_skeleton.py` | 0: the outfit mesh gets the base character's skeleton |
| `pose_render.py` | check sheet of a rigged GLB at rest and posed (also used by `explode/explode_render.py`) |
| `prompts_v2.json` | the SAM3 prompts (upper / lower / full crops) |
| `diag.py` | one page with every setting and number of a run: `<work>/DIAGNOSTICS.md` |
| `fix_neutral_bone.py` | rehomes vertices parked on glTF's `neutral_bone` (made `rigfix/barb_final_nb.glb`) |

The other method steps live in `../explode/` (render, SAM, label, merge, show, pose) and `../repaint/`
(`paint_outfit.py`).

## `options/`: built, not in the method
| Script | Status |
|---|---|
| `fit_set.py` | fits a worn set to the body and tucks the skin. Rejected as the method 2026-11-05 (its push bends the plates); kept as an option until a fit that keeps each piece's shape replaces it |
| `fit_piece.py` | the first fit, torso only; `fit_set.py` generalised it |

## `measure/`: one-off measurements behind numbers in the log
Not part of a run. Each answered one question in `PROCESS_explode2.md`; rerun them to check a number.
| Script | Question |
|---|---|
| `shell_check.py` | is his skin inside the armour, how far does the plate stand off (before any cut) |
| `skin_metric.py` | how much body shows through the worn set, per pose |
| `skin_probe.py` | why the body shows at given pixels |
| `sam_check.py` | is a bad cut SAM's fault or the merge's |
| `compare_cuts.py` | how much the cut changes as views are added |
| `border_zoom.py` | close-ups of piece borders, cuts side by side |
| `hole_check.py` | holes per piece, small ones filled |
| `holo_value.py` | what HoloPart's infill buys |
| `merge_explain.py` | what of HoloPart's piece the merge keeps |
| `anim_compare.py` | a clip without and with the pieces, frame by frame |
| `swap_sheet.py` | swap test sheet: poses without and with the pieces |

## Removed (in git history, see "Tried and dropped")
`buffer_set.py`, `outline_check.py`, `body_silhouette.py` (this folder's copy).
