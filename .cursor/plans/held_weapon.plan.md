# Plan: weapons, two routes tried side by side

Goal: weapons a character holds, made on the outfit page like the other outfits (an outfit of the character who holds
it, its own kind, steps in `outfit.py`, fields in `outfit_fields.py`, gates on the page, run folder
`<data>/generated/bosses/<character>/outfits/<outfit>/`). Two routes, both tried; both end the same way in the game:
a rigid weapon on a hand bone, moved by the clips.
- **Route A, alone (cheap):** the weapon drawn alone, TRELLIS, put in his hand by its shape and a preset per weapon
  type. Mostly built (`kind weapon` today, `weapon_grip.py`).
- **Route B, held (the armour flow):** he is drawn holding it naturally, TRELLIS on the whole figure, SAM3 finds the
  weapon, cut, HoloPart; the pose is read off the figure (rtmlib) and his rig is posed to match; the weapon is
  attached to his hand bone. The user's route.
Proof throughout: the barb's outfits do not change (`_checks/barb_unchanged.py`, `_checks/view_prompts_unchanged.py`).
Reviews (2026-11-14, two) folded in: screen size, the game side first, arm-length gap, mirrored views, wrist roll,
HoloPart on a gripped handle, the side check, the piece steps' inputs.

## Status 2026-11-14
Route A: concept, views, TRELLIS, grip built (kind `weapon`), checked on a box sword in the barb's hand; no paid run,
no export. Route B: written, nothing built. Branch `feat/new-character` (worktree `Pixel-Realm-new-character`).

## Facts that bound both routes
- Screen size: the hero is drawn about 60 px tall (`Graphics/barb/down_idle/0.png` 64x63; `PlayerMesh` sized to it);
  a sword is about 25 px long, 2-3 px wide. Judge every result at that size.
- The game today: `Code/Weapon.py` draws `Graphics/Weapons/<W>/<Dir>.png` at fixed offsets from the sprite rect, and
  that image's mask is the hit. `equipment.PIECES` has no weapon slot. Players have no ranged attack (arrows are only
  enemy `ranged_attacks` in `Settings.py`).
- A pack holds one idle, move, attack (`player_clips.py`). The anunaki clips have no weapon moves: a weapon type
  (two-handed, bow) needs its own clips in either route.

## Step 1 (both routes need it): the game side
Decide, with `mask_hit_collision.plan.md`:
- the mesh weapon replaces the `Weapon.py` sprite for mesh heroes, or is drawn alongside it;
- where the hit comes from (the mesh blade's screen projection, or the old mask);
- how `weapon_data` / `player.weapon` relate to `equipment` (a hand slot `weapon_r` / `weapon_l`, its item base).
Free check: the barb with the box sword at game size through `draw_equipment.py`: idle, move, attack, 4 facings.

## Route A: alone (do first)
Steps (kind `weapon`, renamed `weapon_alone` when route B lands): `concept front back sides trellis grip export
install`.
- concept: `view_prompts/weapon.json` (upright, handle down; `weapon_guide.png` placement only); object check (one
  piece, upright, clear of the edges, white background).
- grip: `weapon_grip.py`: long axis by PCA, handle = the thinner end, sized to `weapon_length` x his height, grip
  point at the palm, pointing where his feet point, `grip_turn` about the hand bone; parented to the hand bone.
- Presets per weapon type (one-hand, two-hand, staff): `weapon_length`, `grip_offset`, `grip_turn` in
  `explode2/weapon_presets.json`, picked by `weapon_type`, tuned once on the sheet; an outfit may override.
- Optional later: grip marked in colour in the drawing (magenta main hand, cyan off hand / string point), found on
  the TRELLIS mesh's texture, replacing "the thinner end" for bows and odd shapes. Only if the shape guess fails.
- export / install: a weapon pack (rigid, 100 % hand bone), item base `<material>_<type>`, equip in a hand slot.
- Check: one sword through to the game, hitting, judged at 60 px.

## Route B: held (do second)
Steps (kind `weapon`): `concept front back sides trellis views sam3 cut holopart merge hand_pose align sheet export
install`.
1. Prompts (config): `view_prompts/held_weapon.json`: "{holder} holding {weapon} in a natural pose for it, whole
   figure, orthographic front, white background"; back / side / 3/4 "the same figure, same pose". Fields `held` (the
   weapon), `hands` (one | two | bow carried), `look_refs` (optional). Concept check: one person (rtmlib), clear of
   the edges, white background; the weapon by eye.
2. Views: `mirror_right: false` for this kind (a mirrored right view puts the sword in the other hand; drawn right
   views have failed before on bodies: budget retries). The side check (head / feet heights) is weak when the weapon
   sticks above the head or points at the camera: by eye at the gate for this kind.
3. TRELLIS on the whole posed figure. The weapon prompt holds the blade clear of the body.
4. Pieces, as armour with these inputs: `views` renders the picked TRELLIS mesh (no paint step; `ctx.painted()`
   gives it for this kind), the shared `greedy_dirs`; `sam` = `explode2/weapon_prompts/<type>.json` (sword,
   greatsword, axe, staff; keywords -> part `weapon`, "hand" -> `hand`, the rest `body`; no belt line, so
   `--belt-gate` has nothing to do). SAM runs on the TRELLIS texture, weaker than the painted renders the armour
   prompts were tuned on: **the first paid run stops at the masks**, looked at before HoloPart.
5. HoloPart: optional cleanup. It completes unseen backs of shells, not a handle's missing middle inside a fist: a
   blob there fails the sheet, and the route A mesh of the same weapon is swapped in.
6. pose (the main way, user 2026-11-14): a 3D pose model on the drawn front (HMR 2.0 / 4D-Humans, SMPLer-X or Meta
   Sapiens: never set up here; a pod install and a test first) gives the holder's whole 3D pose. His rig is posed
   into it (the model's joints mapped to his bone roles, as `retarget_bvh.py` maps clip skeletons), the TRELLIS figure
   fitted onto the posed rig (as `outfit_skeleton.py` fits armour onto the A-pose rig: height and head), and from
   there it is the armour flow in posed space: cut the weapon, attach it to the hand bone, rig back to rest. This
   removes "it is not in the A-pose" for the whole body and most of the arm-length gap. Check first: licences (SMPL's
   body model is non-commercial; prefer a model not tied to it) and the joint mapping. Fallback: the two-view rtmlib
   step below.
6b. hand_pose fallback (`explode2/weapon_hand_pose.py`): render the posed figure front and side, orthographic, **on white**;
   rtmlib body model (shoulder, elbow, wrist per side; the `.venv-pose` detector). Front gives x and height, side
   gives depth and height. Match a side joint to a front joint by height, not by the detector's left / right labels
   (they swap in profile). Gate when the two views disagree in height, not only on low scores. Greatsword: both hands
   at similar heights and overlapping in the side view, the hardest case.
7. align (`explode2/weapon_align.py`):
   - his rig (`rig_fit`, `roles`) posed: the arm bones aimed along the found shoulder -> elbow -> wrist directions;
   - the weapon placed **relative to the found wrist frame** (position: the found wrist; orientation: forearm
     direction + the weapon's second principal axis, the blade's flat), then moved onto **his rig's hand after the
     pose**, grip point (the weapon vertices that touched the `hand` part) on his palm;
   - wrist roll: from the blade's flat (a round staff has none); no knuckles needed;
   - attached to the hand bone, rig back to rest. `grip.json` records the gap left (found wrist vs his posed wrist,
     a share of height) and the grip points (two-handed: the off hand's, for later).
8. sheet: rest, his rig in the found pose beside the TRELLIS figure, frames of his attack clip. Accept "grip on the
   palm, angle close"; the recorded gap shown. Two-handed and bow runs: judged on the mesh and the main-hand grip
   (the second hand leaving the weapon in clips is out of scope).
9. export / install: as route A.
Not in route B: shields (a plane on the forearm, not a hand slot) until a forearm slot exists.

## Clips for weapon types (both routes)
- One Kimodo run with a two-handed sword prompt, both hands pinned with its LeftHand / RightHand constraints
  (`NOTES_kimodo_api.md`, never used for this), retargeted to the barb (`retarget_bvh.py --source anunaki`): measure
  the gap between his hands over the clip. Small and steady: a weapon bone (main hand -> off hand) baked in
  `player_clips.py` is enough; large: hand IK is the real work.
- A pack then needs a clip set per weapon type (`attack_2h`, `idle_2h` ...), picked by the equipped weapon. A new
  bone means re-exporting the packs on the new skeleton (not checked how packs store bones).
- Bow: needs a player ranged attack in the game first; the string as a drawn line (not checked the GPU draw can).

## Checks
- Free, both: the box sword at game size (step 1); barb's 16 view cases and outfits unchanged.
- Free, route B: pose the barb's rig (arm raised and bent), box sword in that hand, render as a TRELLIS figure, run
  hand_pose + align: found joints vs true bones. **Plus a wrong-arm-length case** (the figure's forearm 20 % longer):
  print the rig-palm-to-grip distance, the number the first version treated as zero.
- Paid, route A: one sword concept + views + TRELLIS, through to the game.
- Paid, route B: one one-handed sword held by the barb; stop at the SAM masks; then HoloPart, hand_pose, align,
  sheet. Then a greatsword.
- Paid, clips: the one Kimodo two-handed run above.

## Order
1. Game side decision + the free 60 px check.
2. Route A: one sword to the game.
3. Route B: free checks, then the one-handed sword paid run, then the greatsword.
4. Weapon clips (Kimodo two-handed run), then bows once a player ranged attack exists.
Route A stays if B wins; it is dropped if it gets in the way.

## Not in this plan
- The second hand kept on a two-handed weapon during clips (IK); a closed-hand pose; the bowstring bone.
