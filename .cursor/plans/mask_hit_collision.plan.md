---
name: mask hit collision
overview: "Every attack lands only where its pixels touch the target's pixels. One module (Code/hit_core.py) answers 'did this touch that' for every attack, and one resolver method (InteractionResolver.strike) applies flat-damage hits with one repeat rule: once per attack by default, or again every rehit_ms. Work happens on branch refactor/attack-mask-collision."
todos:
  - id: core
    content: "Phase 1, steps 1-3: Code/hit_core.py (shapes, find_hits, bodies_near, ground_reach); collision_core.solid_mask; InteractionResolver.strike with the repeat rule."
    status: completed
  - id: bodies
    content: "Phase 2, steps 4-7: mesh boss hit_shape; build_body_mask docstring; server-side remote player mask; its entity-tree entry names its owner."
    status: completed
  - id: attack-sprites
    content: "Phase 3, steps 8-14: the AttackSprite contract; Weapon art cache + mask; particle masks; rehit_ms from magic_data and ranged attacks; one shared loop that reads the contract and keeps arrows stopping; parry reset; EnemyPuppet docstring."
    status: completed
  - id: abilities
    content: "Phase 4, steps 15-16: dash finds bodies through the entity tree; leap slam hits by ground circle with ground-distance falloff (fixes the snapshot bug in both)."
    status: completed
  - id: ground-blasts
    content: "Phase 5, steps 17-19: meteor blast vs footprint with ground-distance knockback; meteors aim at the feet; ice clone explode and freeze on the ground circle."
    status: completed
  - id: melee
    content: "Phase 6, steps 20-22: enemy swing restarts its clip, hits every hostile body its frame touches (entity tree), applied through strike; ranged attacks pass rehit_ms; Enemy and Friendly tick the swing too."
    status: completed
  - id: cleanup
    content: "Phase 7, steps 23-25: delete the unused damage evaluators, the old enemy_melee_hit hook, Level4.py and CombatStrategy1.py."
    status: completed
isProject: false
---

# Mask hit collision

## Read this first

- Branch: `refactor/attack-mask-collision`, cut from `main` at `2f7dead`. That commit already has everything this plan builds on: the `Entity.py` and `collision_core.py` rewrite, and the ranged-enemy work (`b8be8b6`: retreat AI, arrows and stones that stop on the first body they hit).
- The branch is checked out in the shared folder `C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Private`. While it is, every session in this folder is on this branch, and their commits land here too. Switch back to `main` once the refactor is merged into it.
- Do the phases in order and commit after each one. The game keeps working after each phase.
- Find functions **by name** (`def player_attack_logic(`), not by line number. Line numbers move. Re-read a file right before you edit it.
- Code in this plan is complete. Copy it as written. Do not rename anything, do not "improve" it, do not add features.

## How a hit flows when this is done

```
an attack: Weapon, spell or projectile sprite, an enemy swing, a dash, a ground blast
  -> hit_core.shape_of(attacker)  or  hit_core.ground_disc(...)    where its pixels are
  -> candidates:
       attack sprites, ground blasts:  level.attackable_sprites
       swings, dashes:                 hit_core.bodies_near(entity tree)  (+ the swing's target)
  -> hit_core.find_hits(shape, candidates)       rect test first, then mask test
  -> flat damage (attack sprites, dash, swing):
       InteractionResolver.strike(targets, hits, rehit_ms, ...)   team check + repeat rule
     per-target damage and knockback (leap slam, meteor, ice clone):
       their own loop, falloff from hit_core.ground_reach
  -> InteractionResolver.apply(ctx) -> target.receive_interaction(ctx)    unchanged
```

## What the player sees when this is done

- A sword hits an enemy only when the sword's pixels touch the enemy's pixels, not when the two rectangles overlap.
- An enemy's swing lands only on bodies its attack frame touches: its target, and any other hostile body caught in the swing. Swing at the air and nothing happens. Today the damage lands on the target alone when the cooldown ends, as long as the two sprite centres are within `melee_attack_radius`.
- Projectiles hit on their pixels. Arrows and stones still stop at the first body they hit.
- Meteors, the leap slam and the ice clone (explosion and freeze) hit you when their circle on the ground touches your feet. Today they test the distance to your sprite's centre. Meteors aim at your feet, the leap slam's dust shows where its blast is, and the closer your feet are to the centre of a blast on the ground, the harder it hits.
- Each attack hits each body once by default: one sword swing, one flame particle, one projectile, one dash, one enemy swing. An attack configured with `rehit_ms` hits the same body again every `rehit_ms` while it still touches. Meteor damage-over-time still ticks on its own timer.
- Player attacks deal much less damage than today until their numbers are retuned (see "What to watch").
- In co-op, an enemy swing or dash on the server hits every networked player it touches. Projectiles and meteors still don't hit networked players, as today (see "Not in this plan").
- Dash damage (`collision_mode: "damage_on_hit"`) and leap slam damage work. Today the leap slam reads `.hitbox` off broadphase snapshots, which don't have one (`AttributeError`). Dash passes the snapshot to the resolver as the target, which rejects it, so dash damage never lands.

## Decisions (already made)

1. **Melee shape** is the attacker's whole current frame mask, weapon pixels included. For mesh bosses it is the posed capsule mask. A swing hits every hostile body it touches. `melee_attack_radius` keeps one job: deciding when to start a swing. A swing restarts the attack clip from frame 0.
2. **Ground blasts** are a circle on the ground, drawn squashed the way the camera sees it, tested against each target's footprint (the ellipse the walls stop). Falloff is the ground distance from the blast's centre to the footprint's edge (`hit_core.ground_reach`), the same circle the hit test used. Meteors aim at the target's feet. Anything without `hitbox` and `wall_foot`, such as `Flyer`, is not hit by ground blasts.
3. **Who can be hit** follows two rules:
   - Attack sprites (weapon, spells, projectiles) and ground blasts (meteor, leap slam) search `level.attackable_sprites`, as player attacks, projectiles and the meteor already do. Co-op puppets are in that group, so a joiner's hits on them still relay to the host.
   - Body attacks (an enemy's swing, a dash) search the entity tree around the attacker (`hit_core.bodies_near`), plus the swing's chosen target. Only nearby bodies are tested, so the cost doesn't grow with the number of units. The tree holds every moving entity, including the server's networked players (step 7). The chosen target covers anything without a tree entry, such as RTS workers spawned without a tree callback.
   - The ice clone keeps searching its own group.
   - So a new kind of hittable entity has to be in both places: in `attackable_sprites` (its spawn groups) for sprite attacks and blasts, and in the entity tree with `owner=self` (`Entity.move` does this) for swings and dashes. The split exists because co-op puppets are in the group but must stay out of the tree, where they would collide.
4. **No mask means the whole rect**, today's behaviour, so nothing gets harder to hit by accident. A mask that doesn't fit its rect also falls back to the rect, and the `collision_mask` debug channel names the class the first time.
5. **The repeat rule: once per attack by default, configurable per attack.** Each attack keeps `hits`, a record of when it last hit each body (`AttackSprite.hits` on weapons and particles, `runtime["hits"]` for dash, `swing["hits"]` for melee). `rehit_ms` on the attack decides what happens while it keeps touching the same body:
   - absent or `None`: once per attack (the default);
   - a number: again after that many ms;
   - `0`: every frame.

   Set it next to the attack's damage:

   | Attack | Where | Example |
   |---|---|---|
   | Weapon | `weapon_data` in `Settings.py` | `"sword": {"cooldown": 100, "damage": 15, ..., "rehit_ms": 250}` |
   | Spell | `magic_data` in `Settings.py` | `"flame": {"strength": 5, "cost": 20, ..., "rehit_ms": 200}` |
   | Monster swing | its `melee_attacks` entry | `{"damage": 8, "cooldown": 1500, "rehit_ms": 300}` |
   | Monster projectile | its `ranged_attacks` entry | `{"type": "demon_dog_projectile", "damage": 15, "cooldown": 1500, "rehit_ms": 500}` |
   | Monster dash | its `Dash` special attack | `{"name": "Dash", ..., "rehit_ms": 200}` |

   A projectile with `stops` set (arrows, stones) stops at the first body it lands on, whatever its `rehit_ms`.
6. **A hit soaked up by i-frames still counts** for the repeat rule: `apply` returns True whether or not damage lands. Today a sword still out could land once the i-frames end.
7. **Flat-damage attacks apply through `InteractionResolver.strike`**: weapon, spells, projectiles, dash and enemy swings. Leap slam, meteor and ice clone keep their own apply loops, because their damage and knockback vary per target; they share the hit test, not `strike`. `Level4.emit_enemy_melee_hit` and the `enemy_melee_hit` context hook go away in Phase 7.

## What stays distance-based

These are AI decisions, not hits. Leave them as they are:

- `melee_attack_radius`, `notice_radius` and `ranged_attack_radius` in `CombatStrategy.decide_action` and `execute_attack`: when to swing, chase or shoot.
- `CombatStrategy.parry`: when to deflect a projectile.
- `SpecialAttacks.in_range_of_player`: when a special attack may trigger.
- `Flyer._player_in_range`: when a flyer starts an attack.

## Speed

- The rect test always runs first. The mask test runs only for pairs whose rects overlap. One mask overlap costs about 2 µs (`Code/stats_tottime.txt`: 179,128 `overlap_area` calls in 0.369 s).
- Swings and dashes test only the bodies the entity tree returns around them, so a large swarm doesn't multiply the cost.
- Attack sprites keep today's cost: the loop over `attackable_sprites` is the same loop `pygame.sprite.spritecollide` runs now.
- Masks are built once and reused:
  - entity frames: already built per frame;
  - weapons: one per weapon and direction, on the first swing;
  - particles: one set per animation type (turned arrows get one per shot, a single 16×5 frame);
  - ground circles: one per size, radius rounded to 2 px;
  - mesh bosses: the capsule mask LRU in `mesh_boss.py`.
- `Weapon` stops reading its PNG from disk on every swing.

## Do not

1. Do not import anything into `hit_core.py` except `logging`, `math`, `pygame`, `collision_core` and `hashRect`. The headless server imports it. Same rule as `collision_core.py`.
2. Do not convert the checks in "What stays distance-based".
3. Do not drop the chosen target from the swing's candidates (see Decision 3).
4. Do not touch body bumping (`Entity.collision`, `body_contact`). Bumping already uses masks and is not an attack.
5. Do not treat entity-tree items as entities. They are `HashableRect` snapshots; `hit_core.bodies_near` returns their owners.
6. Do not iterate an attack-sprite group directly while hits can call `stop()`: `stop()` kills the sprite and takes it out of the group. Iterate a copy.
7. Do not put a sprite in `attack_sprites` or `enemy_attack_sprites` unless it is an `AttackSprite` that called `init_attack()`. The hit loop reads its fields directly.

---

## Phase 1: the shared hit test

### Step 1. Create `Code/hit_core.py`

```python
"""Did an attack touch a body: the one hit test for every attack, client and server.

An attack and a body are each a Shape: a pygame Mask plus the world position of its
top-left pixel. A hit is the two rects overlapping and then the two masks overlapping,
so the mask test only runs for pairs that are already close.

- A sprite's shape is its own hit_shape() when it has one (mesh bosses), else its
  current frame mask at rect.topleft, else its whole rect. A hit_shape() must lie
  inside the sprite's rect.
- A ground blast (meteor, leap slam, ice clone) is a circle on the ground, tested against
  each body's footprint: the ellipse the walls stop (collision_core). ground_reach gives
  the blast's falloff distance on the same circle.
- Candidates are a sprite group, or the entity tree through bodies_near, which turns
  the tree's snapshots back into their entities.

Rect, Mask and plain Surfaces only: no display and no game imports, so it is safe on the
headless server.
"""

import logging
import math

import pygame

import collision_core
from hashRect import HashableRect

# The collision_mask channel in debug_logging.json.
_log = logging.getLogger("game.collision.mask")

_DISCS = {}
_RECT_FALLBACK_LOGGED = set()


class Shape:
    """A mask placed in the world, its top-left pixel at rect.topleft."""

    __slots__ = ("mask", "rect")

    def __init__(self, mask, x, y):
        self.mask = mask
        self.rect = pygame.Rect((int(x), int(y)), mask.get_size())


def rect_shape(rect):
    """A solid rect: the shape of anything without a mask."""
    return Shape(collision_core.solid_mask(rect.width, rect.height), rect.x, rect.y)


def frame_masks(frames):
    """One mask per frame, from its opaque pixels."""
    return [pygame.mask.from_surface(frame) for frame in frames]


def shape_of(sprite):
    """Where this sprite's pixels are right now; None if it has no rect."""
    own = getattr(sprite, "hit_shape", None)
    if own is not None:
        shape = own()
        if shape is not None:
            return shape
    rect = getattr(sprite, "rect", None)
    if rect is None:
        return None
    mask = getattr(sprite, "mask", None)
    if mask is not None:
        if mask.get_size() == rect.size:
            return Shape(mask, rect.x, rect.y)
        kind = type(sprite).__name__
        if kind not in _RECT_FALLBACK_LOGGED:
            # Once per class: a mask that doesn't fit its rect quietly means rect hits.
            _RECT_FALLBACK_LOGGED.add(kind)
            _log.debug(
                "hit shape falls back to the rect: %s mask %s, rect %s",
                kind, mask.get_size(), rect.size,
            )
    return rect_shape(rect)


def _disc_mask(w, h):
    key = (w, h)
    mask = _DISCS.get(key)
    if mask is None:
        surf = pygame.Surface(key, pygame.SRCALPHA)
        pygame.draw.ellipse(surf, (255, 255, 255, 255), surf.get_rect())
        mask = pygame.mask.from_surface(surf)
        _DISCS[key] = mask
    return mask


def ground_disc(center, radius, elevation_deg):
    """A circle of `radius` on the ground around `center`, as the camera sees it.

    The radius is rounded to 2 px so blasts of every size share a few hundred masks.
    """
    r = max(1, int(round(float(radius) / 2.0))) * 2
    w = 2 * r
    h = max(1, int(round(2.0 * r * math.sin(math.radians(float(elevation_deg))))))
    return Shape(_disc_mask(w, h), int(center[0]) - w // 2, int(center[1]) - h // 2)


def foot_shape(sprite):
    """The footprint the walls stop; None for anything without a hitbox and wall_foot."""
    wall_foot = getattr(sprite, "wall_foot", None)
    hitbox = getattr(sprite, "hitbox", None)
    if wall_foot is None or hitbox is None:
        return None
    foot = collision_core.foot_rect(hitbox, wall_foot())
    return Shape(collision_core.foot_mask(foot.width, foot.height), foot.x, foot.y)


def ground_reach(center, foot, elevation_deg):
    """Ground distance from a blast's `center` to the nearest edge of footprint `foot`.

    Screen y is stretched back by 1 / sin(elevation), so a blast's squashed ellipse reads
    as the circle it is on the ground: a footprint touching the ellipse anywhere on its
    edge is about `radius` away. 0 when the centre is inside the footprint.
    """
    s = math.sin(math.radians(float(elevation_deg)))
    fx, fy = foot.rect.center
    dx = fx - center[0]
    dy = (fy - center[1]) / s if s > 0 else fy - center[1]
    return max(0.0, math.hypot(dx, dy) - foot.rect.width / 2.0)


def touching(a, b):
    """True if two shapes share at least one pixel."""
    if a is None or b is None or not a.rect.colliderect(b.rect):
        return False
    return a.mask.overlap(b.mask, (b.rect.x - a.rect.x, b.rect.y - a.rect.y)) is not None


def bodies_near(tree, rect, query_id, margin=32):
    """The entities whose entity-tree entry overlaps `rect` grown by `margin`.

    The tree holds snapshots (HashableRect) from each entity's last move, with the entity
    as `owner`. The margin covers a tick of movement and snapshot rects smaller than the
    sprite (server-side players store their hitbox). Entries without an owner, such as
    projectiles, are skipped, and so is the entry whose id is `query_id` (the attacker).
    """
    if tree is None:
        return []
    area = rect.inflate(2 * margin, 2 * margin)
    owners = []
    for item in tree.hit(HashableRect(area, query_id)):
        owner = getattr(item, "owner", None)
        if owner is not None:
            owners.append(owner)
    return owners


def find_hits(shape, candidates, exclude=(), body=shape_of):
    """Every candidate whose body touches `shape`, each once, in candidate order.

    `body` gives a target's shape: shape_of for swings, projectiles and dashes,
    foot_shape for ground blasts. With shape_of the target's shape lies inside its rect,
    so the rect test runs first and only targets already close get the mask test.
    """
    if shape is None:
        return []
    area = shape.rect
    hits = []
    seen = set()
    for sprite in candidates:
        if sprite in exclude or id(sprite) in seen:
            continue
        seen.add(id(sprite))
        if body is shape_of:
            rect = getattr(sprite, "rect", None)
            if rect is None or not area.colliderect(rect):
                continue
        if touching(shape, body(sprite)):
            hits.append(sprite)
    return hits
```

### Step 2. `Code/collision_core.py`: make the solid mask public

`hit_core` reuses the solid-mask cache.

- Rename `def _solid_mask(w, h):` to `def solid_mask(w, h):`.
- In `_overlaps`, change `mask = _solid_mask(rect.width, rect.height)` to `mask = solid_mask(rect.width, rect.height)`.

Nothing else uses `_solid_mask` (checked across `Code/` and `tests/`).

### Step 3. `Code/Interaction.py`: add `InteractionResolver.strike`

Add this method to `class InteractionResolver`, after the whole `apply` method:

```python
    def strike(self, targets, hits=None, rehit_ms=None, **fields) -> list:
        """Apply one flat-damage attack to every target it touched: team prefilter, the
        attack's repeat rule, then apply.

        `hits` is the attack's own record, target id -> time of its last hit (ms); None
        keeps no record, so every call applies. With a record, `rehit_ms` None hits each
        target once per attack, and a number lets the same target be hit again after that
        many ms (0 = every frame). `fields` are InteractionContext fields; strike fills in
        `target`. Returns the targets the attack landed on.
        """
        landed = []
        kind = fields.get("kind", "damage")
        source_team = fields.get("source_team")
        now = self._now_ms()
        for target in targets:
            key = id(target)
            if hits is not None and key in hits:
                if rehit_ms is None or now - hits[key] < rehit_ms:
                    continue
            if not self.can_potentially_affect(source_team, getattr(target, "team_id", None), kind):
                continue
            if self.apply(InteractionContext(target=target, **fields)):
                landed.append(target)
                if hits is not None:
                    hits[key] = now
        return landed
```

---

## Phase 2: every body has a shape

### Step 4. `Code/combat_unit.py`: mesh bosses get `hit_shape`

- Add `import hit_core` after `from hashRect import HashableRect`.
- Add this method to `class CombatUnit`, after the whole `plant_sprite_on_hitbox` method:

```python
    def hit_shape(self):
        """Mesh bosses: the posed capsule mask on the feet, the same box plant_sprite_on_hitbox
        sets as rect. Sprite units: None, so hit_core uses self.mask at self.rect."""
        if self.mesh_boss is None:
            return None
        facing = self.get_facing_deg() if hasattr(self, "get_facing_deg") else 0.0
        mask, dx, dy = self.mesh_boss.body_mask(facing, self.mesh_height_px)
        mx, my = self.hitbox.midbottom
        return hit_core.Shape(mask, int(mx + dx), int(my + dy))
```

`body_mask` and `capsule_screen_bounds` both come from `_capsule_projection`, so the mask sits exactly on the rect `plant_sprite_on_hitbox` sets.

### Step 5. `Code/mesh_boss.py`: correct the `build_body_mask` docstring

In `def build_body_mask(`, replace the line

```
    Tools/tests only — gameplay uses ``capsule_screen_bounds`` instead.
```

with

```
    Gameplay uses it for attack hits (CombatUnit.hit_shape); walls and bumps use
    ``capsule_screen_bounds``.
```

### Step 6. `Code/RemotePlayer.py`: give the server's remote players a mask

On the server a `RemotePlayer` never animates, so `self.mask` is never set. `set_network_state` already plants `rect` on the hitbox for the idle frame, so the idle frame's mask is the body.

In `RemotePlayer.__init__`, directly after `self._server_mode = bool(server_mode)`, add

```python
        if self._server_mode:
            # The server never animates this player: its body for enemy hits is this idle
            # frame, which set_network_state plants on the reported hitbox.
            self.mask = pygame.mask.from_surface(self.image)
```

Server only: on a client, a mask set at spawn changes where the puppet is planted before its first animate() (two multiplayer tests caught that).

### Step 7. `Code/RemotePlayer.py`: the server-side player's tree entry names its owner

Every other entity puts itself in the entity tree with `owner=self` (`Entity.move`). The server-side `RemotePlayer` leaves the owner out, so `hit_core.bodies_near` (swings and dashes) can't find it.

In `RemotePlayer.update`, inside `if self._server_mode:`, change

```python
                    HashableRect(self.hitbox, self.id),
```

to

```python
                    HashableRect(self.hitbox, self.id, owner=self),
```

Side effect: a mesh boss bumping into this player now gets its real upright body from `body_contact.collision_body`, as it already does for the local player, instead of a box guessed from the hitbox.

`tests/test_server_players.py` checks that the server player is not in `attackable_sprites`. That still holds: this plan keeps server players out of the group.

---

## Phase 3: attack sprites

**Reminder:** this phase edits `Particles.py` and `Level4_tmxdev.py`, which other sessions also work on. Run `git status` first; if another session has uncommitted edits in either file, get them committed before you start. Keep the arrow code (`_face_direction`, `stops`, `stop()`).

### Step 8. The attack-sprite contract, and `Code/Weapon.py`

`Weapon` and `ParticleEffect` are the only sprites that go into `attack_sprites` and `enemy_attack_sprites`. Today each sets its attack fields by hand, and the hit loops read them with `getattr` and a default, so a misspelt field quietly becomes the default. Give both one contract.

Create `Code/attack_sprite.py`:

```python
"""What every attack sprite carries: the one contract the hit loop reads.

Weapon and ParticleEffect are the only sprites in Level4's attack_sprites and
enemy_attack_sprites groups. Each calls init_attack() in its __init__, and
Level4._strike_with_attack_sprites reads these fields directly, so a sprite that skips
init_attack fails loudly (AttributeError) instead of quietly hitting with defaults.
"""


class AttackSprite:
    """Mixin for sprites that hit things. Call init_attack() in __init__."""

    def init_attack(self, *, owner, source_team, source_kind, attack_type,
                    amount=None, tags=(), rehit_ms=None, stops=False):
        self.owner = owner
        self.source_team = source_team
        self.source_kind = source_kind
        self.attack_type = attack_type
        self.interaction_kind = "damage"
        self.amount = amount
        self.tags = set(tags)
        # Repeat rule (InteractionResolver.strike): when this attack last hit each body,
        # and how long before it may hit the same body again (None = once per attack).
        self.hits = {}
        self.rehit_ms = rehit_ms
        # Stops at the first body it lands on (arrows, stones); the sprite defines stop().
        self.stops = stops
```

In `Code/Weapon.py`:

- Add `from Settings import weapon_data` and `from attack_sprite import AttackSprite` after `import pygame`.
- Change `class Weapon(pygame.sprite.Sprite):` to `class Weapon(AttackSprite, pygame.sprite.Sprite):`.
- Add above `class Weapon`:

```python
# path -> (image, mask). Loaded once; every swing of that weapon in that direction shares it.
_WEAPON_ART = {}


def _weapon_art(path):
    art = _WEAPON_ART.get(path)
    if art is None:
        image = pygame.image.load(path).convert_alpha()
        art = (image, pygame.mask.from_surface(image))
        _WEAPON_ART[path] = art
    return art
```

- In `Weapon.__init__`, keep `self.sprite_type = "weapon"` and replace

```python
        self.owner = player
        self.source_team = getattr(player, "team_id", "player")
        self.source_kind = "player_attack"
        self.attack_type = "weapon"
        self.interaction_kind = "damage"
        self.tags = {"weapon", "player_attack"}
        self.amount = None
```

  with

```python
        self.init_attack(
            owner=player,
            source_team=getattr(player, "team_id", "player"),
            source_kind="player_attack",
            attack_type="weapon",
            tags={"weapon", "player_attack"},
            rehit_ms=weapon_data.get(player.weapon, {}).get("rehit_ms"),
        )
```

- Replace `self.image = pygame.image.load(full_path).convert_alpha()` with `self.image, self.mask = _weapon_art(full_path)`, and right after it add:

```python
        # Unarmed art has no opaque pixels: the punch is the player's own body (hit_shape).
        self._unarmed = self.mask.count() == 0
```

- Add `import hit_core` at the top, and this method at the end of `class Weapon`:

```python
    def hit_shape(self):
        """Unarmed: the player's current frame, so a punch lands where the player's sprite
        touches (the same rule as enemy swings). Weapons with art: None, so hit_core uses
        the art's mask."""
        if self._unarmed:
            return hit_core.shape_of(self.owner)
        return None
```

  Decided during Phase 3: `Graphics/Weapons/Unarmed/{Right,Left,Up,Down}.png` have no opaque pixels, so a mask-only unarmed attack could never land. Today it hits through the image's 64×64 box.

### Step 9. `Code/Particles.py`: particles carry masks and the attack contract

- Add `import hit_core` and `from attack_sprite import AttackSprite` after `from Support import import_folder`.
- At the end of `AnimationPlayer.__init__`, add `self.masks = {}`.
- Add this method to `class AnimationPlayer`, directly before `def create_particles(`:

```python
    def _masks_for(self, animation_type, frames):
        """Hit masks for a particle's frames, built once per animation type. A turned arrow
        gets new frames on every shot, so its masks are built per shot (one small frame)."""
        if frames is not self.frames.get(animation_type):
            return hit_core.frame_masks(frames)
        masks = self.masks.get(animation_type)
        if masks is None:
            masks = hit_core.frame_masks(frames)
            self.masks[animation_type] = masks
        return masks
```

- In `create_particles`, add `rehit_ms=None` as the last parameter. In its `ParticleEffect(...)` call, add these as the last arguments:

```python
                       rehit_ms=rehit_ms,
                       masks=self._masks_for(animation_type, animation_frames),
```

- Change `class ParticleEffect(pygame.sprite.Sprite):` to `class ParticleEffect(AttackSprite, pygame.sprite.Sprite):`.
- In `ParticleEffect.__init__`, add `rehit_ms=None, masks=None` as the last parameters. Replace the commented line `#self.masks = convert_animations_to_masks(self.animations)` with:

```python
        # Hit masks, one per frame (AnimationPlayer._masks_for); None = the rect is the hit area.
        self.masks = masks
        self.mask = masks[0] if masks else None
```

- Further down `__init__`, keep `self.sprite_type = "magic"` and replace

```python
        self.owner = owner
        self.source_team = source_team or getattr(owner, "team_id", None)
        self.source_kind = source_kind or ("enemy_projectile" if self.source_team == "enemy" else "player_attack")
        self.attack_type = attack_type or self.sprite_type
        self.interaction_kind = "damage"
        self.amount = amount
        self.stops = stops
        self.tags = set(interaction_tags or [])
```

  with

```python
        team = source_team or getattr(owner, "team_id", None)
        self.init_attack(
            owner=owner,
            source_team=team,
            source_kind=source_kind or ("enemy_projectile" if team == "enemy" else "player_attack"),
            attack_type=attack_type or self.sprite_type,
            amount=amount,
            tags=interaction_tags or (),
            rehit_ms=rehit_ms,
            stops=stops,
        )
```

  Particles that never attack (leaves, heal, aura) get the fields too; nothing reads them there.

- In `ParticleEffect.update`, directly after `self.image = self.frames[self.frame_index]`, add:

```python
            if self.masks:
                self.mask = self.masks[self.frame_index]
```

### Step 10. Spells take `rehit_ms` from `magic_data`

`Code/Magic.py`:

- Change `def flame(self, player, cost, groups):` to `def flame(self, player, cost, groups, rehit_ms=None):`, and add `rehit_ms=rehit_ms,` after `attack_type="magic",` in both of its `create_particles(...)` calls.
- Change `def ice_ball2(self, player, cost, groups, quad_tree):` to `def ice_ball2(self, player, cost, groups, quad_tree, rehit_ms=None):`, and add `rehit_ms=rehit_ms,` after `attack_type="magic",` in its `create_particles(...)` call.

`Code/Level4_tmxdev.py`, in `def create_magic(`:

- Change `self.magic_player.flame(self.player, cost, [self.layout_manager.visible_sprites, self.attack_sprites])` to:

```python
            self.magic_player.flame(self.player, cost, [self.layout_manager.visible_sprites, self.attack_sprites],
                                    rehit_ms=magic_data["flame"].get("rehit_ms"))
```

- Change `particle = self.magic_player.ice_ball2(self.player, cost, [self.layout_manager.visible_sprites, self.attack_sprites], self.layout_manager.entity_quad_tree)` to:

```python
            particle = self.magic_player.ice_ball2(self.player, cost, [self.layout_manager.visible_sprites, self.attack_sprites], self.layout_manager.entity_quad_tree,
                                                   rehit_ms=magic_data["ice_ball"].get("rehit_ms"))
```

`magic_data` comes in through `from Settings import *`, already at the top of both files.

### Step 11. `Code/Level4_tmxdev.py`: enemy projectiles take `rehit_ms`

- In `def fire_projectile(`, add `rehit_ms=None` after `amount=None` in the signature. Keep the comment at the end of the line.
- In its `self.animation_player.create_particles(...)` call, add `rehit_ms=rehit_ms,` after the `stops=...` argument.

Step 21 makes the monster AI pass each ranged attack's `rehit_ms` in.

### Step 12. `Code/Level4_tmxdev.py`: one loop for every attack sprite

- Add `import hit_core` beside the other local imports at the top.
- `player_attack_logic` and `enemy_projectile_logic` sit next to each other. Replace both whole methods (their TODO comments and debug logging go too) with these three:

```python
    def _strike_with_attack_sprites(self, group, also_exclude=()):
        """Every attack sprite in `group` hits each body its pixels touch.

        Each sprite is an AttackSprite (attack_sprite.py): it carries its owner, team, kind,
        damage, tags and repeat rule (hits, rehit_ms; see InteractionResolver.strike). A
        sprite never hits its owner or itself; one without an owner (a parried projectile)
        is its own source. A sprite with `stops` set (arrows, stones) stops at the first
        body it lands on.
        """
        # A copy: stop() kills the sprite, which takes it out of the group.
        for attack_sprite in list(group):
            owner = attack_sprite.owner
            targets = hit_core.find_hits(
                hit_core.shape_of(attack_sprite),
                self.attackable_sprites,
                exclude=(owner, attack_sprite) + tuple(also_exclude),
            )
            if not targets:
                continue
            fields = dict(
                kind=attack_sprite.interaction_kind,
                source_kind=attack_sprite.source_kind,
                source=owner if owner is not None else attack_sprite,
                owner=owner,
                source_team=attack_sprite.source_team,
                amount=attack_sprite.amount,
                attack_type=attack_sprite.attack_type,
                tags=set(attack_sprite.tags),
            )
            hits, rehit_ms = attack_sprite.hits, attack_sprite.rehit_ms
            if attack_sprite.stops:
                for target in targets:
                    if self.interaction_resolver.strike([target], hits, rehit_ms, **fields):
                        attack_sprite.stop()
                        break
            else:
                self.interaction_resolver.strike(targets, hits, rehit_ms, **fields)

    def player_attack_logic(self):
        """The player's weapon swings and spells."""
        self._strike_with_attack_sprites(self.attack_sprites, also_exclude=(self.player,))

    def enemy_projectile_logic(self):
        """Enemy projectiles, and player projectiles a parry turned around."""
        self._strike_with_attack_sprites(self.enemy_attack_sprites)
```

The old `_hit_id` attribute is gone; nothing else reads it. The resolver still logs every hit and rejection on the `combat` channel.

### Step 13. `Code/Level4_tmxdev.py`: a parried projectile can hit again

In `def redirect_projectile_callback(`, directly after `projectile.distance_moved = 0`, add:

```python
            # Turned around by a parry: it is a new attack and may hit anyone again.
            projectile.hits = {}
```

### Step 14. `Code/EnemyPuppet.py`: the relay follows the attack's repeat rule

In the `receive_interaction` docstring, replace

```
        Relayed every overlapping frame (no i-frames here) -- the host's real
        enemy gates repeats exactly as it does for the host's own hits.
```

with

```
        Relayed by the attack's repeat rule (InteractionResolver.strike): once per
        attack by default, or again every rehit_ms.
```

---

## Phase 4: dash and leap slam

### Step 15. Dash: bodies through the entity tree, and a repeat rule

`Code/abilities/dash.py`:

- Add `import hit_core` after `from abilities.protocol import ...`.
- Delete `from hashRect import HashableRect` if nothing else in the file uses it after this step.
- In `try_start`, in the `entity._dash_runtime = {...}` dict, replace `"hit_targets": set(),` with:

```python
            "hits": {},
            "rehit_ms": self.config.get("rehit_ms"),
```

- Replace the whole method `def _apply_damage_on_hit(self, entity, context, entity_quad_tree, runtime) -> None:` with:

```python
    def _apply_damage_on_hit(self, entity, context, entity_quad_tree, runtime) -> None:
        """Damage every body the dasher's pixels touch, by the dash's repeat rule.

        Bodies come from the entity tree around the dasher (hit_core.bodies_near).
        hit_once_per_target False keeps no record, so it hits every frame.
        """
        if runtime.get("damage") is None:
            return
        level = getattr(entity, "level", None)
        if level is None and isinstance(context, CombatAbilityContext):
            level = (context.combat_context or {}).get("level")
        resolver = getattr(level, "interaction_resolver", None)
        shape = hit_core.shape_of(entity)
        if resolver is None or shape is None:
            return
        nearby = hit_core.bodies_near(entity_quad_tree, shape.rect, getattr(entity, "id", -1))
        targets = hit_core.find_hits(shape, nearby, exclude=(entity,))
        resolver.strike(
            targets,
            hits=runtime["hits"] if runtime["hit_once_per_target"] else None,
            rehit_ms=runtime["rehit_ms"],
            kind="damage",
            source_kind="dash",
            source=entity,
            owner=entity,
            source_team=getattr(entity, "team_id", None),
            amount=runtime["damage"],
            attack_type=runtime["attack_type"],
        )
```

`Code/SpecialAttacks.py`, in `DashAttack.__init__`: in `dash_config`, add `"rehit_ms": attack_config.get("rehit_ms"),` after the `"hit_once_per_target": ...` line.

`tests/abilities/test_dash_damage_on_hit.py` needs a rewrite in this step, not a stub tweak. Its fake tree returns entities, which is how the snapshot bug hid. It has to:
- return `HashableRect(target_rect, target_id, owner=target)` snapshots, like the real tree;
- give targets real `pygame.Rect` rects that overlap the dasher's;
- reach an `interaction_resolver` through `entity.level` or a `CombatAbilityContext` whose `combat_context` has a `level`;
- read `runtime["hits"]` where it read `runtime["hit_targets"]`.

### Step 16. `Code/abilities/leap_slam.py`: `_resolve_landing_aoe`

- Add `import hit_core` and `from Settings import VIEW_ELEVATION_DEG` after `from abilities.protocol import PlayerAbilityContext`.
- Delete `from hashRect import HashableRect` if nothing else in the file uses it after this step.
- Replace

```python
    def _resolve_landing_aoe(self, entity, context, entity_quad_tree, runtime) -> None:
        if entity_quad_tree is None:
            return
```

  with

```python
    def _resolve_landing_aoe(self, entity, context, entity_quad_tree, runtime) -> None:
        level = getattr(entity, "level", None)
        # No group (a stub level): nobody is hit, but the landing effect still plays.
        attackable = getattr(level, "attackable_sprites", None) or ()
```

- Replace

```python
        center_x, center_y = runtime.get("impact_center", entity.hitbox.center)
        query_rect = pygame.Rect(0, 0, int(radius * 2), int(radius * 2))
        query_rect.center = (center_x, center_y)
        entity_id = getattr(entity, "id", None)
        nearby = entity_quad_tree.hit(HashableRect(query_rect, entity_id))

        resolver = None
        level = getattr(entity, "level", None)
        if level is not None:
            resolver = getattr(level, "interaction_resolver", None)
```

  with

```python
        center_x, center_y = runtime.get("impact_center", entity.hitbox.center)
        # The blast is a circle on the ground around the slammer's feet.
        own_foot = hit_core.foot_shape(entity)
        ground = own_foot.rect.center if own_foot is not None else (center_x, center_y)
        blast = hit_core.ground_disc(ground, radius, VIEW_ELEVATION_DEG)
        nearby = hit_core.find_hits(blast, attackable, exclude=(entity,), body=hit_core.foot_shape)

        resolver = getattr(level, "interaction_resolver", None)
```

- In the particle code that follows, change the `create_particles` position argument `(center_x, center_y),` to `ground,`, so the dust shows where the blast is.
- In the `for target in nearby:` loop, replace

```python
            if target is entity:
                continue
            tx, ty = target.hitbox.center
            dist = math.hypot(tx - center_x, ty - center_y)
            if dist > radius:
                continue
            falloff = max(0.0, 1.0 - dist / radius) if radius > 0 else 0.0
```

  with

```python
            foot = hit_core.foot_shape(target)
            tx, ty = foot.rect.center
            gx, gy = ground
            dist = math.hypot(tx - gx, ty - gy)
            # Falloff by ground distance to the footprint's edge: the circle the hit test used.
            reach = hit_core.ground_reach(ground, foot, VIEW_ELEVATION_DEG)
            falloff = max(0.0, 1.0 - min(reach, radius) / radius) if radius > 0 else 0.0
```

- A few lines below, replace

```python
                nx = (tx - center_x) / dist
                ny = (ty - center_y) / dist
```

  with

```python
                nx = (tx - gx) / dist
                ny = (ty - gy) / dist
```

`tests/abilities/test_charged_leap_slam.py` needs a rewrite in this step. Its targets have to be in `level.attackable_sprites` and have `hitbox` and `wall_foot`. Its expected falloff becomes `1 - ground_reach / radius`, measured to the footprint's edge, instead of `1 - 100/120` between hitbox centres.

---

## Phase 5: ground blasts

### Step 17. `Code/meteor_strike.py`: the blast hits feet

- Add `import hit_core` and `from Settings import VIEW_ELEVATION_DEG` after `from Interaction import InteractionContext`.
- Replace the whole method `def _hosts_in_radius(self):` with:

```python
    def _hosts_in_radius(self):
        """Every body whose footprint the blast's ground circle touches."""
        attackable = getattr(self.level, "attackable_sprites", None)
        if attackable is None:
            return []
        blast = hit_core.ground_disc(self.ground_pos, self.impact_radius, VIEW_ELEVATION_DEG)
        return hit_core.find_hits(
            blast, attackable.sprites(), exclude=(self.owner,), body=hit_core.foot_shape
        )
```

- In `def _apply_explosion_knockback(self):`, delete

```python
            if dist > radius:
                continue
```

  and replace `falloff = max(0.35, 1.0 - dist / radius)` with

```python
            reach = hit_core.ground_reach((cx, cy), hit_core.foot_shape(target), VIEW_ELEVATION_DEG)
            falloff = max(0.35, 1.0 - min(reach, radius) / radius)
```

  The shove's direction still comes from `dx, dy`.

### Step 18. `Code/SpecialAttacks.py`: meteors aim at the feet

`MeteorShower` aims around `player.rect.center` and draws the crater there. With the blast tested against the feet, a small meteor (radius 31 px, ground ellipse about 44 px tall at 45°) aimed dead at your sprite's centre would land above your feet and miss.

- Add `import hit_core` after `from abilities.protocol import CombatAbilityContext`.
- In `MeteorShower.update`, replace

```python
        anchor = getattr(player, "rect", None)
        center = anchor.center if anchor is not None else enemy.rect.center
```

  with

```python
        # Aim at the feet: the blast is tested against the footprint (hit_core.foot_shape).
        foot = hit_core.foot_shape(player)
        if foot is not None:
            center = foot.rect.center
        else:
            anchor = getattr(player, "rect", None)
            center = anchor.center if anchor is not None else enemy.rect.center
```

### Step 19. `Code/IceClone.py`: explode and freeze on the ground circle

- Add `import hit_core` and `from Settings import VIEW_ELEVATION_DEG` after `from Interaction import InteractionContext`.
- Replace the whole method `def freeze_enemies(self):` (its commented-out lines go too) with:

```python
    def freeze_enemies(self):
        """Freeze every unit whose feet the freeze circle (radius + 180) touches."""
        blast = hit_core.ground_disc(self.rect.midbottom, self.radius + 180, VIEW_ELEVATION_DEG)
        for sprite in hit_core.find_hits(
            blast, self.groups[0], exclude=(self,), body=hit_core.foot_shape
        ):
            if isinstance(sprite, CombatUnit) and not sprite.frozen:
                sprite.freeze()
```

- In `def explode(self):`, replace

```python
        affected_sprites = pygame.sprite.spritecollide(self, self.groups[0], False, pygame.sprite.collide_circle)
```

  with

```python
        blast = hit_core.ground_disc(self.rect.midbottom, self.radius, VIEW_ELEVATION_DEG)
        affected_sprites = hit_core.find_hits(
            blast, self.groups[0], exclude=(self,), body=hit_core.foot_shape
        )
```

---

## Phase 6: enemy melee

**Reminder:** this phase edits `CombatStrategy.py`, which other sessions also work on. Run `git status` first; if another session has uncommitted edits in it, get them committed before you start. Keep the `RangedCombatStrategy` retreat code.

### Step 20. `Code/CombatStrategy.py`: swings land on their hit frames

- Add `import hit_core` after `from  hashRect import HashableRect`.
- Add these two methods to the base `class CombatStrategy`, after the whole `handle_special_attacks` method:

```python
    def start_melee_swing(self, enemy, attack):
        """Begin a swing. It lands later, in land_melee_swing, on whatever it touches.

        The attack clip starts at frame 0. Otherwise frame_index carries over from the walk
        cycle, and if that is past the end of the attack clip, the next animate() ends the
        attack before any frame of it is checked.
        """
        enemy.frame_index = 0
        enemy.melee_swing = {"attack": attack, "hits": {}}

    def land_melee_swing(self, enemy, target, entity_tree):
        """Every tick: a swing hits each hostile body its frame touches, by its repeat rule.

        With the clip restarted at frame 0 (start_melee_swing), every attack frame gets
        checked whether animate() runs before or after actions(). Bodies come
        from the entity tree around the attacker (hit_core.bodies_near), plus the chosen
        target for anything without a tree entry; find_hits drops the duplicate.
        attack["hit_frames"] lists the attack-animation frames that can hit; without it
        every frame of the swing can. attack["rehit_ms"] is the repeat rule (default once).
        The swing ends when the enemy leaves "attack": the clip ended, or decide_action
        cancelled it.
        """
        swing = getattr(enemy, "melee_swing", None)
        if swing is None:
            return
        if enemy.status != "attack":
            enemy.melee_swing = None
            return
        attack = swing["attack"]
        hit_frames = attack.get("hit_frames")
        if hit_frames is not None and int(enemy.frame_index) not in hit_frames:
            return
        context = self.combat_context if isinstance(self.combat_context, dict) else {}
        resolver = getattr(context.get("level"), "interaction_resolver", None)
        shape = hit_core.shape_of(enemy)
        if resolver is None or shape is None:
            return
        candidates = hit_core.bodies_near(entity_tree, shape.rect, enemy.id)
        if target is not None:
            candidates.append(target)
        targets = hit_core.find_hits(shape, candidates, exclude=(enemy,))
        if not targets:
            return
        resolver.strike(
            targets,
            hits=swing["hits"],
            rehit_ms=attack.get("rehit_ms"),
            kind="damage",
            source_kind="enemy_melee",
            source=enemy,
            owner=enemy,
            source_team=getattr(enemy, "team_id", "enemy"),
            amount=attack.get("damage"),
            attack_type=attack.get("type", "melee"),
            tags={"enemy_melee"},
        )
```

The context fields are the ones `emit_enemy_melee_hit` builds today, so `receive_interaction` sees the same hit.

### Step 21. `Code/CombatStrategy.py`: start a swing instead of hitting; pass `rehit_ms` to projectiles

In **both** `MeleeCombatStrategy.execute_attack` and `MixedCombatStrategy.execute_attack`, replace

```python
                    if "enemy_melee_hit" in self.combat_context:
                        self.combat_context["enemy_melee_hit"](enemy, target, attack)
```

with

```python
                    self.start_melee_swing(enemy, attack)
```

Leave the distance check, the sound and the cooldown lines as they are.

In **both** `RangedCombatStrategy.execute_attack` and `MixedCombatStrategy.execute_attack`, add `rehit_ms=attack.get("rehit_ms"),` to the `self.combat_context["fire_projectile"](...)` call, after its `amount=attack.get("damage")` argument.

### Step 22. Tick the swing every frame

`actions` already receives the entity tree as `quadtree`; `combat_update` passes it in. Make this the first line of `def actions(self, player, quadtree=None):`, before anything else in it, so the swing ticks even on frames a special attack or dash returns early:

```python
        self.combat_strategy.land_melee_swing(self, player, quadtree)
```

Add it in all three classes that drive a `CombatStrategy`:

- `CombatUnit.actions` in `Code/combat_unit.py`: every enemy the game spawns.
- `Enemy.actions` in `Code/Enemy.py` and `Friendly.actions` in `Code/friendly.py`: the game no longer spawns these (tests and probes still build them). Without the line, they would start swings and never land them.

A melee attack can now say which frames hit, for example `"melee_attacks": [{"damage": 8, "cooldown": 1500, "hit_frames": [2, 3]}]`. Without `hit_frames`, any frame of the attack animation can hit.

---

## Phase 7: cleanup

**Reminder:** this phase deletes code from `Level4_tmxdev.py`, which other sessions also work on. Run `git status` first; if another session has uncommitted edits in it, get them committed before you start.

### Step 23. `Code/Level4_tmxdev.py`: delete the unused damage evaluators

Delete the comment `### Single function to do all damage evaluation ( Not currently being used )`, `def evaluate_damage(self):` and `def evaluate_team_damage(team):` with its whole docstring. Nothing calls them. The notes in that docstring are this plan.

### Step 24. Delete the old melee hook

Every swing applies through `strike` now (step 20), so nothing calls these:

- `Code/Level4_tmxdev.py`: delete `def emit_enemy_melee_hit(self, enemy, target, attack):`.
- `Code/Spawner.py`, in `generate_combat_context`: delete

```python
        if 'damage_player' in combat_config.keys():
            context['enemy_melee_hit'] = level.emit_enemy_melee_hit
```

  Keep the `if` above it, which sets `context['damage_player']`.
- `Code/rts/combat_context.py`, in `make_rts_combat_context`: delete

```python
    if level is not None and hasattr(level, "emit_enemy_melee_hit"):
        ctx["enemy_melee_hit"] = level.emit_enemy_melee_hit
```

Search for `enemy_melee_hit` once more afterwards. Nothing should be left.

### Step 25. Delete `Code/Level4.py` and `Code/CombatStrategy1.py`

Nothing imports either (the game, server and tests import `Level4_tmxdev`). Search for `Level4 import`, `import Level4` and `CombatStrategy1` once more right before deleting.

---

## What to watch

- **Player damage drops a lot until it is retuned.** Enemies have no i-frames (`self.vulnerable = False` is commented out in `CombatUnit.get_damage`), so today a sword, each flame particle and an ice ball deal damage on every frame they overlap an enemy, and co-op puppets relay every frame. Once per attack makes each of those one hit. Retune weapon and spell damage (or enemy health), or give an attack a `rehit_ms`.
- **Bumping keeps bodies apart (left for later).** Entities push apart when their masks overlap, so a swing lands only if its attack frame reaches past the walk frame. A monster whose attack art doesn't reach out will miss every swing. Fix that monster's art or its `melee_attack_radius` later, not the hit test. For new monsters that is the entity pipeline's attack clip, and its `wire` step is the natural place to write `hit_frames`.
- **Frozen units are hit as rects.** A frozen unit shows its frozen image, so its last frame mask no longer fits its rect. The `collision_mask` debug channel will name `CombatUnit` the first time that happens.
- **Mesh boss capsule masks** rasterise the first time each (frame, whole-degree facing) is used: a few milliseconds, then cached. They are only built when an attack's rect overlaps the boss's rect.
- **Ground blasts skip anything without feet.** Flyers, and any other sprite with only a rect, stop being hit by meteors, the leap slam and the ice clone. The ice clone's circle is also centred on its `rect.midbottom` now, not `rect.center`.

## Not in this plan

- **Co-op projectiles and meteors.** Clients are never sent enemy projectiles or meteors: there is no message for them in `Code/network/protocol.py`, and nothing in `Server/` sends them. So the server's networked players stay out of `attackable_sprites`, or they'd be hit by things they can't see. Once those are sent, adding `self.attackable_sprites` to the groups in `add_server_player` is a one-line change (and `tests/test_server_players.py` changes with it).
- **Attack sprites through the entity tree.** Weapons, spells and projectiles still test every attackable sprite, the same cost as today. Moving them to the tree needs co-op puppets in it, and they are kept out on purpose: they mustn't collide.
- **Weapon-only masks** (blade pixels without the body) would need the entity pipeline to export a separate weapon layer.
- **Damage numbers.** This plan changes how often attacks hit, not how much each hit deals.
