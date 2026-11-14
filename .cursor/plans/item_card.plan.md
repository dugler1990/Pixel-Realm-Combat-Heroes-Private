# Plan: the item card, tied to the combat rules

Status 2026-11-14: chunk 1 built and chunk 3 without verdicts, plate armour and loincloth only (branch
`feat/item-card`): `item_bases.json`, `item_properties.py`, `item_card.py`, the card panel in
`inventory_view.py`, detail view on Shift, `tests/test_item_card.py`. Not played by hand yet.

Written 2026-11-14. Part of `docs/damage/NOTES_damage_and_armour.md` (chunk 12, pulled forward: the
card can ship before combat uses the numbers). Broad plan: shape and order, not every answer.

## The problem

Armour can be put on from the inventory (`equipment.py`, `inventory_view.py`, merged to main
`7d42ac5b`), but an item says nothing about itself:
- The inventory draws no description, tooltip or card.
- Armour items (`Graphics/Standard_Items/outfit_items.json`) carry only identity and mesh: slot, side,
  `mesh_piece`, `outfit`. No properties at all.
- `outfit_items.json` is **written by** `tools/boss_sprite_pipeline/equip_install.py` (this outfit's
  entries replaced): stats typed there get wiped on the next install.
- Old items (`Code/items.json`) have flat stats (`frost_resistance`, `magic_defense`) and hand-written
  descriptions that nothing checks against what the item does.

## What the card must do

- Tell the truth: every line comes from the same numbers and the same functions combat uses. No
  hand-written stat text. Change a number, the card changes; add a rule, the card can say it.
- Say facts a player uses in a fight ("stops darts, a mace still hurts"), numbers on request.
- Scale: new properties, magic properties, quality tiers, rarities, sets, without new card code.

## One source: item = base + quality + magic + state

| layer | holds | where |
|---|---|---|
| **base** | slot kind, physical properties (`stopping_power`, `absorb`, `weight`, `coverage`, `conductivity`, `insulation`, `flammability`, `sealed`, max `durability`), strength to wear | new hand-written `item_bases.json`, keyed by base id (`plate_chest`, `plate_boot`, `loincloth`) |
| **quality tier** | multipliers on base numbers (durability, stopping power, weight) | tier table: e.g. crude, standard, fine, masterwork (names open) |
| **magic properties** | rows that change a stat: `+20 fire resist`, `+0.1 absorb`, `sealed`, a buff on hit | affix table: id, stat, value range per tier, card line template |
| **rarity** | how many magic properties, name colour | rarity table: e.g. plain, magic, rare, unique (names open) |
| **set** | bonus for wearing n pieces of a set | set table: the fullplate is 12 pieces, natural set ("all 12: full coverage, gas sealed") |
| **instance state** | durability now, quality and affixes rolled, (later) heat | on the item instance, saved with the inventory |

- `outfit_items.json` items get one more field, `base` (written by `equip_install.py`), and nothing
  else: stats live in `item_bases.json`, so a re-install never wipes them.
- Old `items.json` stats move into the same scheme over time (their `frost_resistance` becomes a
  magic property `ice resist`).

## Registry: what makes the card generic

One row per property, loaded once:

| field | e.g. `stopping_power` |
|---|---|
| id, display name | `stopping_power`, "Stopping power" |
| group | physical / element / magic / cost / state |
| format | integer, percent, yes/no |
| better | higher / lower (for compare arrows) |
| card rule | `verdict` (feeds the Stops/Through lines), `line` (own line), `detail` (detail view only) |
| line template | "Conducts lightning", "+{v} fire resistance" |

A new property is a row. A new magic property is an affix row pointing at a property.

## The verdict lines: the card runs the combat rule

"Stops darts" is not typed anywhere. The card runs the **same pure function** the resolver will use
(penetration vs stopping power, force through absorb) against a short list of **reference attacks**
(data: dart, arrow, sword, axe, mace, crossbow bolt, ballista, fireball...):

- **Stops**: the point is stopped and the bruise is under a "speck" threshold.
- **Cushions**: stopped, bruise noticeable, or crush/blast force cut by a fair share.
- **Through**: gets through, or force arrives nearly whole.
- **Weak to**: element rules that make it worse (conductive → lightning; holds heat → fire).

The function lives in its own module (`damage_rules.py` or similar) from the first card chunk, so
the card and the resolver can never disagree. Reference attacks are rows; add a weapon kind, the
card says something new.

## Card layout (top to bottom)

```
 Masterwork Plate Cuirass            <- name, colour = rarity
 Chest · Heavy · Fullplate set       <- slot, weight class, set
 ------------------------------------
 Stops     darts, arrows, swords
 Cushions  axes, maces
 Through   crossbow bolts
 Weak to   lightning, fire (holds heat)
 ------------------------------------
 Heavy: −12% speed, thrown less       <- cost, from weight and the knockback rule
 Covers: chest, back, upper arms
 Needs 14 strength
 ------------------------------------
 +20 fire resistance                  <- magic properties, own colour
 Sealed: stops gas
 ------------------------------------
 Durability ████████░░  240/300  dented
 Fullplate 7/12: at 12, full coverage
 "Forged in ..."                      <- flavour, the only free text
```

- **Detail view** (hold a key): the raw numbers, from the registry `detail` rows.
- **Compare**: on a pack item that fits a worn slot, arrows per line against what is worn there.
- **Placement**: a fixed panel inside the inventory window (the cursor moves by d-pad, so no mouse
  tooltip); shows the item under the cursor, in pack or on the doll.
- **Body panel** (later): the doll coloured by region: what each region stops, gaps in red (no helmet
  = head open). Total weight, speed, resistances.

## Speed

- The card is built when the cursor lands on an item, cached per item instance with a version that
  bumps on change (durability, a new affix). Reference runs: ~10 calls of a pure function, once.
- Text through `legion_ui` `TextSlot` (one surface per place, as the gold count does).
- Nothing per frame while the card is unchanged.

## Chunks

1. **Bases and registry.** `item_bases.json`, `base` field written by `equip_install.py`, property
   registry, loader + tests. The fullplate and loincloth get first numbers.
2. **Rule function and reference attacks.** The pure physical rule (penetration, absorb, force) in its
   own module, reference attack table, verdict computation, tests.
3. **Card panel.** Name, type line, verdict lines, cost, covers, in the inventory window for the
   cursor's item. Text cached.
4. **Compare and detail view.**
5. **Quality tiers.** Tier table, multipliers, name prefix.
6. **Magic properties and rarity.** Affix table, roll on drop, lines and colours. Folds in old
   `items.json` stats.
7. **Durability line.** After armour wear (master chunk 10).
8. **Sets.** Set table, count worn, bonus line, bonus applied.
9. **Body panel.** Doll by region.

1–3 make a card that is true; 4–9 add to it without changing how it works.

## Open

- Tier and rarity names, and how many of each.
- Do magic items drop unidentified?
- Weight classes (light / medium / heavy) shown as words, from weight thresholds?
- Do left and right pieces count as two set pieces or one?
- Numbers shown by default anywhere, or detail view only?
- Strength requirement: hard (can't wear) or soft (wear it, slower)?
