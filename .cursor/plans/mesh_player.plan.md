# Plan: the player as a live 3D mesh (barb), next to the sprite players

Goal: pick "Barbarian (mesh)" at character select and see him as a skinned 3D model facing any angle, with
every control the sprite player has. Naked barb first; armour pieces later ride on the same skeleton. Sprite
players unchanged.

Design (after two reviews, 2026-11-13): the mesh is **draw-only**. The sprite barb keeps animating as the
gameplay body (image, mask, hits, feet placement, sitting, collision, server footprint, CPU fallback). The mesh
hangs on a new attribute `mesh_skin`, which only the camera's draw checks. `.mesh_boss` is NOT set on the
player: it switches collision to capsules (`Entity.wall_foot`, `body_contact.is_mesh`) and drops the shadow.

## What exists (checked 2026-11-13 on main)
- `Code/mesh_boss.py`: `MeshBossPack` / `MeshBoss` (`set_action`, `advance(dt, loop=)`, `draw`); a skin pack
  needs `body.json` whose sha1 matches `skin.npz`. `_HALF_SPEED` slows `idle` / `settle_*`.
- `Code/YsortCameraGroup.py` `_draw_sorted_sprite`: draws `.mesh_boss` at the feet, falls back to the
  `sprite.image` blit when `draw` returns False (CPU backend).
- `Code/Player.py`: walk statuses `up/down/left/right`; `*_idle`; attack via `self.attacking` (400 ms + weapon
  cooldown); dash / leap zero `direction` in `get_status`. No `get_facing_deg`.
- Selection passes only `player_info_dir` (`PlayerSelection.select_player` → Main2 → Level4 → SpecificPlayer).
- Barb clips: `anim_test/retarget/animated.blend` "walk" is not a walk (legs barely move,
  PROCESS_explode2.md). Real locomotion in the anunaki set: `jokesillyrun`. Idle: `settle_01` (the demon's).

## Branch / folder
`feat/mesh-player`, worktree `C:\Users\Douglas\Pixel-Realm-mesh-player` (venv junction). Barb sources live
only in the Boss worktree (gitignored): `C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\barb\`.

## Steps
1. **Clips**: retarget `settle_01`, `jokesillyrun`, `overheadchop` onto `rigfix/barb_final_nb.glb`
   (`retarget_bvh.py --source anunaki --target barb anim_test/bvh_player anim_test/retarget_player`).
   `tools/boss_sprite_pipeline/player_clips.py`: rename to `idle`, `move` (one stride cycle, horizontal root
   travel removed), `attack` (arm up f45-60 + the chop f108-138) → `player.blend`.
   Attack candidates seen on the barb (2026-11-13): twohandswing = arms spread, no strike; bigpunch = barely
   moves; hammerdown2 = bent-over smash; overheadchop = raise + chop (taken; the chop lands at his side).
2. **Pack**: `export_mesh_runtime.py player.blend Graphics/Meshes/barb --skin --only idle,move,attack`, then
   `bake_body_capsules.py barb`. Check: loads, frames per clip, size on disk.
3. **Selection → player**: `mesh_pack` from the selected entry passed through Main2 → Level4 → SpecificPlayer
   (both barbs share `Graphics/barb/`, so the folder can't tell them apart). Remote players: out of scope (others
   see the sprite barb).
4. **Player** (additive, only when `mesh_pack` is set): `self.mesh_skin = MeshBoss(pack)`,
   `self.mesh_height_px` from the sprite barb's height. Per frame: clip from state (`self.attacking` →
   `attack`, played once and restarted on each new attack; moving → `move`; else `idle`); `advance(dt or 1/FPS)`.
   `get_facing_deg`: angle of the movement vector, last one kept when stopped (survives dash / leap zeroing);
   while attacking, snapped to the attack's 4-way direction so the swing matches the hit.
5. **Draw**: `_draw_sorted_sprite` also draws `mesh_skin`; falls back to the sprite blit if the draw fails. The
   weapon's slash picture is not drawn while its owner's mesh drew (draw skipped, image untouched, so hits that
   read it are unchanged).
6. **Character select**: entry `barb_mesh` ("Barbarian (mesh)"): the barb's stats, painting, `player_info_dir`,
   plus `"mesh_pack": "barb"`. Existing entries untouched.
7. **Tests**: clip choice, facing latch, attack snap (no GL); pack loads; selection's `mesh_pack` reaches the
   player; existing tests pass. Manual: walk 8 directions, attack on a diagonal, slide / abilities, take a hit,
   bump a wall, sit.

## Known, not fixed here
- Hits stay 4-way (weapon placed from the status).
- Feet sliding: the run clip's fps vs his speed is tuned by eye.
- Door / roof checks use the sprite-sized rect.

## Not in this plan (next)
Armour pieces as skinned meshes on the same bones; more clips (Kimodo).
