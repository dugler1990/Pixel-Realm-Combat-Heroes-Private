# Plan: damage foundation cleanup

Branch `refactor/damage-path` (`..\Pixel-Realm-damage-path`), on top of `a5e6aa45` (one damage path).
One commit per step. Targeted test set run before and after each step; FAILED names compared to baseline.
Each step updates `NOTES_damage_and_armour.md` (Log, Known errors, deletions with commit hash).

## Rules agreed
- No legacy folder. Git history is the archive. Each deletion: one line in the notes with the hash
  and the restore command `git show <hash>^:<path>`.
- One damage path: every hit goes through `InteractionResolver`; no fallbacks that subtract health directly.
- No invulnerability by default. It is an attribute a source grants (a boss trait, a passive ability),
  never a general post-hit grace. Repeat hits stay with `rehit_ms`.
- Attacker memory: two distinct rules, one shared fact.
- Damage numbers live only in attack defs (`config/damage/attacks.json`).

## Steps
1. **Deletions**
   - `Code/Enemy.py`, `Code/friendly.py`, `tribey_geom_probe.py` (TEMP probe), and their use in
     `test_walk_animation_phasing.py`.
   - The 30 inert `'damage_player': True` keys in `Settings.py` `combat_context`.
   - The dead multiplier/bonus in `Level4_tmxdev._resolve_projectile_damage_payload`.
     (Level4_tmxdev is the live level; only this part is dead.)
2. **Resolver only**
   - Remove no-resolver fallbacks: `Entity` lava and effect_state paths, `IceClone`, `leap_slam` x2.
   - Remove leap_slam's own team prefilter; the resolver's team rule decides.
3. **Death in one place**
   - `Entity.die()`: condition-clock notice, lookup-tree removal, `kill()`, then `on_death()`.
   - `on_death()` per class for extras: XP, particles, death sound, RTS notice; Player: game over.
   - `take_damage` calls `die()` when health reaches 0. The 6 per-frame `check_death` copies go.
4. **Sounds**
   - Shared cache: each file loaded once (`sounds.get(path)`).
   - Per-entity sound table (hit, death, attack) from data. Per-instance `Hit.wav` loads go.
   - Later: player hit/impact sound from the weapon or attack def.
5. **Attacker memory**
   - One record (`last_attacker`: team, until_ms) written by the resolver.
   - Two named readers: permission in `FactionPolicy` (passive faction may only attack its attacker);
     preference in `CombatUnit` (target the team that hit me). Both documented in the notes.
6. **Invulnerability as a condition**
   - `invulnerable` timed condition on the `ConditionClock`; the resolver checks it.
   - Granted only by sources that declare it (boss trait, passive ability). No default grace.
   - Remove `vulnerable` flags, `invulnerability_duration`, the reset code in 4 classes, the dead flicker.
7. **Damage numbers from defs only**
   - Projectile, weapon, magic damage priced from `attacks.json`; copies in `Settings`
     (`ranged_attacks` damage, `weapon_data`) removed.
   - Holy-only attacks get a def rule; the `get_full_*_damage` tier in `_price` goes.
   - `apply` returns an explicit result: landed / spent / refused.
8. **Then** the temperature rebuild on top: `temperature.py`, sources table, weighted pull,
   `settle` through the resolver with `over_time`.

## Not in this plan
- Eskimo / PolarBear move to CombatUnit + roam driver + tile-job driver (RTS-style nomad).
  Own initiative, later. Now they only get shared death and sounds.
- Dash invulnerability: a possible later source for step 6.
