# Plan: weapons, held, through the armour flow

Goal: a weapon made like an armour set, except he is drawn holding it naturally (not the A-pose): views, TRELLIS on
the whole figure, SAM3 finds the weapon by its keywords, cut, HoloPart completes what the fist hides. Then the pose
is read off the figure (rtmlib), his real rig is posed the same way, and the weapon, already in that hand, is
attached to his hand bone. Any held thing (sword, greatsword, axe, bow, staff, shield) is a prompt and a keyword
list, not new code.
Same pipeline as the other outfits: an outfit of the character who holds it, its own kind, steps in `outfit.py`,
fields in `outfit_fields.py` (each needed when its step runs), gates on the page, run folder
`<data>/generated/bosses/<character>/outfits/<outfit>/`.
Proof throughout: the barb's outfits do not change (`_checks/barb_unchanged.py`, `_checks/view_prompts_unchanged.py`).

## Status 2026-11-14
Written, nothing built. Replaces this file's earlier version (A-pose carry, dropped: a held weapon in the A-pose is
not believable). Branch `feat/new-character` (worktree `Pixel-Realm-new-character`).
The standalone weapon (weapon drawn alone, `weapon_grip.py`: handle = thinner end) stays as a cheap test, renamed
kind `weapon_alone`; dropped if it gets in the way.

## Kind `weapon`: steps
| Phase | Step | Tool | New? |
|---|---|---|---|
| Views | concept | `concept_gate.py`, block from `view_prompts/held_weapon.json`: him holding it, natural pose, whole figure | prompt file |
| Views | front back sides | `view_gate.py` (back / side checks hold for any pose: mirrored outline, head and feet heights) | prompt file |
| 3D model | trellis | `pod.py trellis` on the whole posed figure | - |
| Pieces | views sam3 cut holopart merge | as armour; `views` renders the TRELLIS mesh as is (no paint first) | small |
| Pieces | hand_pose | render the figure front + side; rtmlib finds the joints; 3D joints | new script |
| Pieces | align | pose his rig's arm(s) to those joints; the weapon is then in his hand; attach to the hand bone | new script |
| Pieces | sheet | the weapon in his hand: rest, the drawn pose, frames of his attack clip | new |
| Game | paint (optional), export, install | TRELLIS texture first; export / install with the hand slot | later |

## 1. Prompts (config)
- `view_prompts/held_weapon.json`: concept "{character look} holding {weapon} in a natural pose for it ({hands}),
  whole figure, orthographic front, white background"; back / side / 3/4: "the same figure, same pose, from ...".
- Outfit fields: `held` (the weapon: "a short iron sword"), `hands` (one | two | bow), `look_refs` (images of the
  character so the drawn holder looks like him; optional: only the weapon is kept).
- Concept check: one person (rtmlib), clear of the edges, white background; the weapon by eye at the gate.

## 2. SAM3 (config)
- `explode2/weapon_prompts/<type>.json` (sword, greatsword, axe, bow, staff, shield): keywords per crop ("sword",
  "blade", "hilt", "crossguard"; bow: "bow", "bowstring") -> part `weapon`; "hand" -> `hand`; the rest `body`.
- The outfit's `sam` names one of them (as the barb's fullplate names `prompts_v2.json`).

## 3. hand_pose (new: `explode2/weapon_hand_pose.py`)
- Render the posed TRELLIS figure, orthographic, front and side (Workbench, as `pose_render.py`).
- rtmlib whole-body (the `.venv-pose` venv, `pose_heights.py`'s detector; add the hand keypoints) on both: shoulder,
  elbow, wrist, knuckles per arm.
- Orthographic: the front view gives x and height, the side view gives depth and height, so each joint is a 3D point
  with no triangulation (heights cross-checked between the two views).
- Writes `hand_pose.json`: the 3D joints per arm, the figure's height, the detector's scores. Gate if a score is low.

## 4. align (new: `explode2/weapon_align.py`)
- His rig (`rig_fit`, `roles`) scaled to the figure's height, shoulders on the figure's shoulders.
- Pose the arm bones (shoulder, elbow, wrist) to point along the found joints; wrist roll from the knuckles, else
  from the weapon's axis.
- The weapon (the `weapon` part after merge) moved by the same scale and offset: it now sits in his posed hand.
- Attach it to the hand bone (two hands: the main hand; the other grip point recorded in `grip.json`), rig back to
  rest: the weapon keeps its place in the hand. Writes the weapon in hand-bone space + `grip.json`.

## 5. sheet
The weapon in his hand: rest, the drawn pose (his rig posed as found, beside a render of the TRELLIS figure: should
look the same), and frames of his attack clip (`clips_blend`). Gate: accept, or nudge offset / turn and rerun.

## 6. Game (later, own step)
- `equipment.PIECES`: `weapon_r` / `weapon_l` (hand slots); `piece_base` -> `<material>_<type>` stats.
- Slot pack: the weapon rigid on the hand bone (`piece_weights` rule `weapon`: 100 % hand; `armour_slots.py`
  part `weapon` -> slot).
- The player draws it with the hand, equip / unequip from the inventory.

## Checks (free first, then one paid run)
- 1, 2: dry-run the prompts; barb's 16 view cases and his outfits unchanged.
- 3 and 4 without a drawing: pose the barb's own rig (arm raised and bent, known angles), put a box sword in that
  hand, render it as if it were a TRELLIS figure; run hand_pose + align; compare the found joints with the true
  bones (target: under 2 % of his height) and the placed sword with the true one (position, angle).
- First real run (paid calls + pod, yours): a one-handed sword held by the barb. Look at the TRELLIS figure (blade
  joined to the body?), the SAM masks, the HoloPart grip, the sheet.
- Then a greatsword (two hands), then a bow.

## Risks
- rtmlib has only run on drawings, not renders of a TRELLIS mesh; fingers around a handle may not be found
  (wrist and elbow plus the weapon's axis are the fallback). Fallback for the whole step: UniRig on the posed
  figure (a pod run per weapon) and read its hand bone.
- A thin blade may join the body in TRELLIS; the prompt holds it clear.
- Wrists in the retargeted clips: the weapon follows the hand bone exactly, so wrist twist shows. Measured on the
  sheet; fixing it is the clips' job.

## Not in this plan
- Keeping the second hand on a two-handed weapon during clips (IK); weapon clips (bow draw, two-handed sets) through
  `retarget_bvh.py`; the bowstring bone; a closed-hand pose.
