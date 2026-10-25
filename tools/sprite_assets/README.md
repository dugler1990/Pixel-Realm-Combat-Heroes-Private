# Sprite asset tools

Cut labeled AI sprite sheets, matte painted floor backgrounds, pack frame folders.

```bash
# Full meteor extract (first customer)
python -m tools.sprite_assets.cli extract-meteor \
  --bulk path/to/bulk.png \
  --linger path/to/linger_variants.png \
  --out Graphics/Particles/Meteor

# Generic cut / matte
python -m tools.sprite_assets.cli cut sheet.png --out tmp/cells --debug
python -m tools.sprite_assets.cli matte tmp/cells --out tmp/matted --trim
```

## Props (interior ornaments)

Prop sheets on one flat background colour -- black, or the magenta the furnishing walkthrough
draws on; it is read off the sheet's border -- (sections, headings, captions; not a grid) → one
transparent PNG per object, a `props.json` catalogue and a Tiled tileset:

```bash
python tools/sprite_assets/cli.py extract-props "path/to/Downloads/*.jpg" --out Graphics/Props/pyramid
# after editing props.json (name, category, mount floor|wall, keep false to drop one):
python tools/sprite_assets/cli.py write-tileset Graphics/Props/pyramid
```

Review with `_contact_sNN.png` (ids under each cut) and `_debug/sNN_overlay.png` (what was
found on each sheet). Re-running keeps hand edits and tile ids. In Tiled: add
`pyramid_props.tsx` as an external tileset and place props on an object layer named
`Props` — the game draws them depth-sorted, solid at the base only (`mount=wall`: not solid).

Output layout for meteor:

```
Graphics/Particles/Meteor/
  targeting/00.png …
  descent/00.png …
  impact/00.png …
  residual/00.png …
  residual_v/00.png …   # flicker variants
  _contact_*.png
  _debug/*_overlay.png
```
