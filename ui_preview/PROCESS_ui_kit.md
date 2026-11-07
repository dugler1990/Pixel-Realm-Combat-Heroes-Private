# Legion polish pass: process log

Goal (from the Legion critique): finish Legion only. Rain behind the interface, light that moves,
the scene changes, and five painted pieces instead of stretched photos and CSS strokes.

## 2026-11-07 — code, no new art

Changes in `index.html`, Legion look only unless noted:

- **Rain is part of the scene.** The old rain was one `.stage::before` layer above the player,
  roster and level cards (they were set to `z-index: 1`, under the rain at 2). Now `backdrop()`
  builds a `.scene` box with the painting and its rain, under the scrim and every panel.
  Two layers: 60 fine blurred drops per 180×360 tile falling at ~380 px/s, and 8 sharp drops per
  420×640 tile at ~1520 px/s. Tiles are SVG built by `rainTile()` from a seeded random, so the lit
  copy lines up drop for drop.
- **Rain only outdoors.** Gate (`hall-sharp.jpg`) and battlefield (`field.jpg`) have rain; the
  shrine and war room are interiors and have none.
- **Torches warm the rain.** Flame and reflection positions were measured from `hall-sharp.jpg`
  (bright orange blobs): 51%/56%, 84%/54%, reflection 51%/80%. A copy of both rain layers in torch
  orange is masked to ellipses there. The `.scene` box keeps the painting's 16:9 cover geometry
  with container units, so the percentages hold at any window size.
  Mistake found: the first warm drops had the cold drops' random opacity (0.35–1) and read as pale
  yellow on top of the white ones. Lit drops are now full strength (`faintest = 1`).
- **Rain no longer restarts on every keypress.** `render()` rebuilds the stage, so the fall
  animation takes `animation-delay: var(--now)` = minus the page clock. Measured in Chrome: the near
  layer's offset went 175.7 → 242.3 px across a re-render (~43 ms of fall), not back to 0.
- **Title no longer clipped.** The 84 px `h1` sat in the 440 px menu column and showed
  "COMBA / HEROE"; it now takes its own width.
- **Selected bar:** a highlight runs along it every 3.4 s. **Pressed:** the bar drops 2 px while
  the mouse or Enter is down (measured `translateY(2px)`).
- **Hero steps into the shaft** on the Player and Attributes screens: from dark, smaller and
  lower, up into the light (1.1 s, starts 0.3 s in so it plays while the gate opens).
- **Level grows to fill the screen** on Enter, then the world screen takes over without the gate.
  Checked in Chrome: ends on `world` with the chosen level and the grown picture removed.
- **Inventory is a fixed 5:4 slab**, centred, instead of a full-screen panel with a dark field to
  the right; the 12 pack cells are a 4×3 grid of squares. 16:10 was tried first and gave
  ~180 px empty pits.

Checked: every Legion screen screenshotted in Chrome (Playwright, real time), no console errors;
the Vessel look still renders as before.

Found, not in the critique, left alone: the Frostreach Gate level card is a debug tile map; the
Levels heading names Level 10 while the Level 8 card is highlighted; the Barbarian's portrait file
is 64×64, so he stands tiny on the dais.

## Art: `ui_preview/make_kit.py`

`python ui_preview/make_kit.py` paints every missing piece with gpt-image-2 (quality high), then
cuts them into `assets/kit/`. Paintings are kept in `generated/ui_kit/` (not in git) with every
call's prompt and usage in `calls.jsonl`. `--cut` re-cuts without calling the API.

| piece | size | from | cut into |
|---|---|---|---|
| sigil | 1024×1024 | prompt | `sigil.png` |
| bar | 2400×800 | prompt | `bar_l/_c/_r.png` (caps found where the column height leaves the bar's) |
| bar_on | 2400×800 | edit of bar + sigil | `bar_on_l/_c/_r.png` |
| logo | 2048×1024 | sigil as reference | `logo.png` |
| wizard | 1024×1536 | his portrait | `wizard.png`, full length, lit only from above |
| barbarian | 1024×1536 | face + sprite, wizard for style | `barbarian.png` (also the Small card) |
| slab | 1600×1280 (5:4) | prompt | `slab.png` |
| items | 1024×1024 | prompt | `bandage/torch/ration/key.png` |
| doll | 1024×1536 | wizard portrait | `doll.png`, front-facing, rim-lit |

Cut-outs are painted on flat green and keyed softly (alpha from green over max(red, blue), then
despill). The sprite cutter in `tools/entity_pipeline/figures.py` was not used: it peels bright
and grey pixels off outlines, which would eat steel highlights and rim light. Key and bar split
were checked on a synthetic bar: caps found at the exact edge, an off-green speck removed.

## 2026-11-07 — the kit painted and wired in

Run: `python ui_preview/make_kit.py` (key read from the user environment). 9 calls, all accepted on
the first painting, 32–94 s each; prompts, sizes and token usage per call are in
`generated/ui_kit/calls.jsonl`.

| piece | verdict |
|---|---|
| bar / bar_on | Same silhouette; gold bevels and the sigil on the left cap of the selected one. Caps cut at 134 px of 261 (0.51 × height). Steel body fills rows 6–94 %. |
| logo | Spells COMBAT HEROES; sigil between the lines, its stem sits between R and O of HEROES. |
| sigil | Distinct, not a known symbol. |
| wizard / barbarian | Full length, feet in frame, clean key (no green fringe at beard or staff). Painted evenly lit. |
| slab | Iron frame takes ~5 % each side, carved border inside, plain stone centre. |
| items | Four clean marks. |
| doll | Front-facing, arms out, hands, belt and feet separate; slots placed from a 10 % grid over it. |

Wiring (Legion): the logo replaces the type title; every bar is left cap + repeating centre +
right cap at a fixed height (46 px menus, 52 px rows, 40 px choices, 64 px roster), gold set on the
selected one, the CSS gold stroke removed; the highlight is kept to the steel by the padding box.
The hero stands inside the shrine painting at 50 %, feet on the dais at 79 % of its height, 52 %
tall, with a contact shadow; roster cards crop the same paintings to the head, so the Small
Barbarian's debug card is gone. The inventory slab is `slab.png` at its own 5:4, the doll is the
painted figure with its slots on head, chest, belt, hands, weapons and feet, the sigil is in the
helm slot, and pack, belt and HUD show item marks.

Mistakes and fixes:
- The first top-light used CSS masks on the hero painting. Chrome blocks image masks for pages
  opened from disk (CORS on file://), so the shading silently vanished. The shaft light is now baked
  into `wizard.png` / `barbarian.png` by `shaft_light()` in the cut: warm screen on the top third,
  up to 72 % darker toward the feet.
- Roster text overflowed the bars (name and stats wrapped to four lines). The roster column is now
  330 px, the stat line is one line in the body font, and the cards are full width (buttons
  otherwise shrink to their text).
- Pieces are saved with PNG `optimize`: 11.7 → 11.3 MB, pixels checked identical.

Checked in Chrome (real time): every Legion screen, no console errors; pressed bar 2 px; level grow
ends on the world with the clone removed; rain keeps its phase across a re-render.

## 2026-11-07 — second pass: the gate, the upgrade tab, everything else framed

Feedback: some pieces were better, but not everything; the gate was basic, the upgrade tab weak.
Still CSS before this pass: the gate (the brushed-steel photo stretched to cover, with two CSS
bosses), every panel (78 % black and a 1 px gold line), text fields, the HUD health bar, the
upgrade meters, the map and level-picture frames.

Run: `python ui_preview/make_kit.py gate frame gauge fills icons field`. 6 calls, 30–76 s each, all
painted usable on the first try.

| piece | verdict / measured |
|---|---|
| gate | Black oak, iron straps, the sigil seal split by the seam. Seam found at the darkest column near the middle; halves cut equal (1019 px) so the seal meets at one scale. |
| frame | Thin iron, sculpted corners. 9-slice measured: corners 137 px, plain edge 0.26 of that. |
| gauge | Spear-tipped trough with a hollow inside. Caps 0.84 × height; opening rows 24–76 %. |
| fills | Molten gold and blood bands, made to repeat by cross-fading the ends. |
| icons | All ten in the asked order. |
| field | Painted fine, but its square end caps read as empty checkboxes beside the text; not used, removed from the kit (fields use a small copy of the frame instead). |

Mistakes and fixes:
- Fill bands were found by mean luminance over 35 % of the brightest row: for the deep red band
  only its 10-px highlight passed. Then by strongest channel at 45 % of the 90th percentile, which
  took in the stone rim above and below. Now: the longest unbroken run of rows over that line,
  minus 6 px at each edge (gold 348 rows, blood 359).
- The gold fill at the opening's height repeated every ~60 px and read as a chain; it is now
  drawn at 400 % of the opening so a slice of the swirl shows.

Wiring (Legion):
- Every panel (pause, settings, death, find, create, lobby and its board, roster, stats,
  attributes, upgrade) is the frame, 9-sliced, around `stone.png` (plain stone cropped from inside
  the slab's carving). The border is the frame's plain edge and the 9-slice is wider, so the stone
  starts at the gold line and the corners overlap it.
- The gate: painted leaves, slam (6 px shudder), dust off the seam, the seal kindles, a light line
  at the seam before they part. The hold while shut went from 220 to 480 ms so the slam reads.
- Upgrade: a framed 3:2 panel, the hero standing in a pool of light, each stat a 74 px steel bar
  (gold when chosen) with its icon, its price in soul gems, its value and a gold meter; the purse
  of soul gems top right.
- Stat icons in the attribute rows (now steel bars) and the player's stat list; HUD health is the
  meter with the blood fill (brightened 1.5×); level and map pictures sit under the frame, drawn on
  top of them.

Kit size is now 21.5 MB of PNG; the largest are the slab (3.7 MB), logo (2.5 MB) and the gate
halves (2.1 MB each).

Not UI and left alone: the Frostreach Gate level picture is a debug tile map and Level 6 is a
plain snow texture; those come from `Graphics/Level/`.

# In the game

Plan: `.cursor/plans/legion_ui_ingame.plan.md`. Worktree `..\Pixel-Realm-legion-ingame`, branch
`feat/legion-ingame` from `main` (8dea3cf) with `feat/online-foundation` merged in: no conflicts.
Venv junctioned, 70 level-art files and the 20 raw kit paintings (`generated/ui_kit`) hard-linked.

## 2026-11-07 — Phase 0: the kit in the game

- **Art in one place.** `ui_preview/assets/kit/` moved to `Graphics/UI/kit/`, the four backdrops to
  `Graphics/UI/backdrops/`, `slot-sharp.jpg` to `Graphics/UI/kit/slot.jpg` (git mv). The preview's
  36 references point at `../Graphics/UI/`; `metal-plate.jpg`, `frame.jpg`, `leather.jpg`,
  `slot.jpg` and `hall.jpg` stay with the other looks.
- **`make_kit.py`** writes to `Graphics/UI/kit/` and also writes `kit.json` (the same numbers as
  `kit.css`, plus the slot frame's slice, 112). A re-cut after the move left every existing piece
  byte-identical.
- **Energy fill**: new piece `fill_energy`, 1536 x 512, painted in 36.8 s, cut with the same band
  finder as the gold and blood fills (now one function, `band_strip`): 1344 x 202.
- **Fonts**: Google's variable Cinzel and Outfit (OFL) instanced with fontTools 4.64 into static
  `Cinzel-SemiBold.ttf` (wght 600), `Outfit-Regular.ttf` (400), `Outfit-Medium.ttf` (500), with the
  two licence files. Pygame can't choose a weight in a variable font.
- **`ImageCache.load_smooth`**: smoothscale, its own cache key; `load_scaled` callers untouched.
- **`Code/legion_ui.py`**: `kit_for(backend)`; sizes from `u = window height / 860` (0.753 at
  1152 x 648: bars 35 px, the start column 331 px); panels (frame 9-sliced over the stone), slot
  boxes, three-part bars with the travelling light kept at six strengths, meters that cut each fill
  width once, `TextSlot`, fixed labels with letter spacing and the preview's hard shadow, the scene
  with two scrolling rain tiles and torch-lit drops as 10 kept frames per torch, and the gate.
  Rendered headless first: every builder matched the preview's pieces.

## 2026-11-07 — Phase 1: start, settings, death, and the gate

- **StartMenu**: the gate painting with rain and warm torches, the left shade and vignette, the
  logo, four steel bars, the hint, the notice line. Settings opens the overlay (it used to only log).
- **SettingsMenu**: framed panel of seven bars with their values, drawn through the backend over a
  dim; Main2 now draws every screen beneath it (`_draw_screen_only`), not only a level or death.
- **DeathMenu**: the gate painting under the red shade, a framed panel, three bars.
- **The gate** (`legion_ui.Gate`, Main2): leaving the start menu, and after death. The state
  switches at once; while the leaves close Main2 draws only the old screen; restart, main menu and
  leaving a match run while the leaves are shut; input is dropped (key releases pass) until they
  are open.
- Checked in the real game loop (scripted keys, `drive_game.py` in the session scratchpad), CPU
  backend headless and GPU in a window. GPU, from the backend's own counters: start menu 78 blits
  a frame, 88 % from the atlas, **0 uploaded per frame**; settings over it 103 blits, 0 uploaded;
  the gate 66 blits, 0 uploaded; 30 fps at the cap.

Mistake found: the first GPU screenshots had no settings panel. The backend batches atlas draws
until `present()`, and the capture read the frame before that, so the frame's last draws were
missing from the image. The capture now flushes the batch first; on screen nothing was wrong.

## 2026-11-07 — Phase 2: choosing a hero and a level

- **PlayerSelection**: the shrine; the hero on the dais (`legion_ui.Dais`: feet at 79 % of the
  painting's height, 52 % tall, a floor shadow; the step-in is 8 kept frames of scale, light and
  opacity over 1.1 s, 0.3 s after the pick); the roster as 64-px bars with head crops; the stats
  with icons. Up/Down picks; the 4 x 3 grid and its crash on an empty cell are gone. Heroes gain
  `display_name`, `painting` and `roster_stats` in `Graphics/PlayerSelectionDict.json`.
- **PlayerConfiguration**: one class, drawn through the backend. Before the game Main2 gives it the
  hero's name and `stage` (the shrine with the hero); at level-up it is a framed panel on black.
  The stickman and the plus boxes are gone; keys unchanged (Enter spends, Backspace returns, Enter
  on Ready finishes).
- **LevelSelection**: the gate painting without rain; framed cards cropped to cover, with names
  from the new `LEVEL_NAMES` in `level_layouts.py`; the chosen card's name as the heading; moves
  only between cards. Enter starts `level_grow`: the picture grows from inside its card to cover
  the window in 0.75 s, one full-size frame reaches the screen, then the level is built behind it.
- GPU counters: player screen 68 blits, attributes 54, levels 42, grow 42, **0 uploaded per frame**
  on each.

Fixes found while checking: roster names ran past their bars (pygame's 12 px floor makes small
text wider than the preview's), so the roster panel is 380 preview px and names are tracked
tighter; hints overflowed narrow panels, so they wrap, and `Kit.lines` now measures letter spacing.

Found, not this work: level 8 (`levels/Map8`) has no `map.tmx`, so choosing it crashes on `main`
too.

## 2026-11-07 — Phase 3: the online screens

- **`menu_widgets.py`** draws through `legion_ui` and the backend; input untouched. Buttons and
  choices are steel bars (gold with focus, the choice's value on the right), text fields are framed
  plaques (`Kit.plaque`) with the gold highlight when focused, list rows are bars, `panel()` is the
  framed stone panel over the window. Fixed words are kept labels; typed text, list cells, notices
  and chat lines each have one `TextSlot` per place (`text_slot`). Heights are preview px.
- **Lobby**: seats as 60-px bars (yours gold, character under the name, "Ready" right; 52 px was
  too short for two lines at the 12-px floor), the chat board as a framed panel.
- **Main2._draw_screen**: the war-room painting and the dim instead of a flat colour.
- Checked by rendering the four screens with sample lobbies, seats and chat (no server in this
  folder: "Play online" shows its notice, and no gate runs because the state doesn't change).
