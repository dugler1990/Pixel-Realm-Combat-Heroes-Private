---
name: legion ui in the game
overview: "Bring the Legion look from ui_preview into the pygame game. One kit module loads the painted pieces smoothly scaled to the size each one is shown at and builds framed panels, steel bars and meters from them; every Legion screen draws through the backend with kept surfaces, never a full-window surface per frame. Then the screens in turn: start, settings and death with the gate, choosing a hero and a level, the online screens, the overlays in a level, and last the HUD, measured on the ice-200 benchmark. Branch feat/legion-ingame in its own worktree, from main with feat/online-foundation merged in."
todos:
  - id: base
    content: "Before you start: WORKTREES.md and CLAUDE.md committed to main; worktree feat/legion-ingame from main; feat/online-foundation merged into it."
    status: pending
  - id: kit
    content: "Phase 0: art moved to Graphics/UI (kit, backdrops, slot frame), energy fill painted, kit.json, static fonts, ImageCache.load_smooth, Code/legion_ui.py (sizes by role, panel/bar/meter builders, text slots, scene with rain)."
    status: pending
  - id: menus
    content: "Phase 1: start menu, settings overlay (over every screen, opened from the start menu too), death menu; the gate when leaving the start menu and after death."
    status: pending
  - id: choose
    content: "Phase 2: player selection (roster, hero on the dais), attributes before the game and at level-up, level selection with names and the grow that hides the level load."
    status: pending
  - id: online
    content: "Phase 3: menu_widgets and the lobby drawn through legion_ui on the war-room backdrop."
    status: pending
  - id: overlays
    content: "Phase 4: upgrade (stacked rows), inventory (slab, doll, 3 x 4 pack), attack selection restyled as it is."
    status: pending
  - id: hud
    content: "Phase 5: the HUD moved inside the window and drawn with kit meters and frames, measured before and after on the ice-200 benchmark."
    status: pending
isProject: false
---

# Legion UI in the game

## Why

The Legion look in `ui_preview/index.html` is finished and is the design reference for the game's
screens. The game's screens today are `pygame.draw.rect` boxes and the default font: `StartMenu`,
`SettingsMenu`, `DeathMenu`, `PlayerSelection`, `PlayerConfiguration`, `LevelSelection`, `Upgrade`,
`Inventory`, `AttackSelection`, the HUD in `UI.py`, and the online screens. The painted kit in
`ui_preview/assets/kit/` (made by `ui_preview/make_kit.py`, steps in `ui_preview/PROCESS_ui_kit.md`)
has most of what they need; Phase 0 adds the rest: a slot frame, an energy fill, the measured numbers
as JSON, and the fonts.

## How the game draws today

- **Screens are states in `Main2.py`.** `set_state` is one assignment and takes effect at once:
  handlers check `self.state` right after calling it, and `_state_player_selection` builds a
  `PlayerConfiguration` in the same frame it switches. Each menu draws onto `backend.compose()`, a
  full-window surface, and hands it to `backend.blit`, so the whole window is uploaded every frame.
- **Settings is an overlay**, opened only by Ctrl+Shift+S. The start menu's "Settings" option only
  logs. While it is open, Main2 draws the screen beneath only for a level or the death menu; over
  any other screen the panel sits on whatever was last in the buffer.
- **Overlays in a level** (upgrade on P, inventory on I, attack selection, and the level-up
  attributes screen) draw while `level.game_paused` is set. The world is not drawn while paused, so
  they sit on black. Upgrade moves Left/Right between columns and Space buys.
- **`PlayerConfiguration` has two uses:** the attributes screen before the game (10 points), and the
  level-up screen inside a level (`Level4_tmxdev`, 20 points, `player_config_open`).
- **The HUD** (`UI.display`, `draw_belt_hud`) draws through the backend every gameplay frame. The
  weapon and magic boxes sit at a fixed y of 630 and are 80 px tall, below the bottom of a 648-px
  window. Their pictures load with `pygame.image.load`, not `ImageCache`.
- **The GPU backend** packs a surface into its sprite atlas only if `ImageCache.holds()` it and it
  is at most 512 px a side. A blit with `area=` never uses the atlas and uploads a texture every
  frame. A blit with a `cache_key` keeps its texture resident. `ImageCache.load_scaled` scales with
  `pygame.transform.scale`, nearest-neighbour.
- **The window** is 60 % of the monitor, about 1152 × 648 on 1080p.
- **The online screens** (`online_menus.py`, drawn with `menu_widgets.py`) are only on
  `feat/online-foundation`. `Main2._draw_screen` fills them with a flat colour, `menu_widgets.font`
  is the default font, and `LobbyScreen.draw` draws its seats and chat board with plain rects.
  That branch also has the start menu's "Play online", "Local co-op (dev)" and notice line; `main`
  still has "Multiplayer (dev)". The kit is only on `main`.

## Decisions made

1. **Base:** `main` with `feat/online-foundation` merged into the new branch. Neither branch alone
   has both the kit and the online screens.
2. **The gate** runs when leaving the start menu and after death (restart or main menu). Every other
   change cuts straight: at 2.4 s a gate, a gate on every step would add about 7 s between start and
   a level.
3. **Settings stays an overlay**, never gated. The start menu's Settings option opens it, and the
   screen beneath is drawn for every state.
4. **Attributes:** one restyled `PlayerConfiguration`, shown on the shrine before the game and as a
   framed panel at level-up inside a level.
5. **Upgrade** becomes stacked rows: Up/Down move, Space buys, P closes. This is an input change.
6. **Attack selection** is restyled as it is. Moving an icon between its slots changes nothing in
   play today; what the screen should do is a separate decision.
7. **The pack** keeps the game's 3 wide × 4 tall, so the arrow keys don't change.
8. **Starting a level from the level screen:** the chosen card grows until it fills the window, the
   level is built while that picture covers the screen, then the level shows. Starts with no card
   (local co-op, the online ticket) cut straight; restart after death goes through the gate.

## Before you start

- Commit `docs/WORKTREES.md` and `CLAUDE.md` to `main`.
- Follow `docs/WORKTREES.md` for `legion-ingame`: worktree `..\Pixel-Realm-legion-ingame` on a new
  branch `feat/legion-ingame` from `main`, with the venv and the level art linked in.
- In that folder, `git merge feat/online-foundation`. Neither source branch changes. Expect at most
  a small conflict in `.gitignore`; keep both sides' lines.
- Find functions by name, not line number, and re-read a file right before editing it.
- Log each phase in `ui_preview/PROCESS_ui_kit.md` under a new heading "In the game": what changed,
  the game's screen beside the preview's at the same window size, and any numbers measured.

## How every Legion screen draws

These hold for every phase.

- **Through the backend, with kept surfaces.** Backdrops, panels, bars, text and rain are blitted
  with `backend.blit`, each surface either held by `ImageCache` (packed into the atlas when at most
  512 px a side) or blitted with a stable `cache_key`. No screen composes a full-window surface each
  frame.
- **Never `area=`.** A partial meter is its own kept surface (Phase 0); scrolling rain is whole
  tiles at an offset.
- **Sizes by role, not one scale.** `u = window height / 860` turns the preview's designed pixel
  sizes into the window's (the preview was laid out on an 860-px-tall stage): bar heights 46, 52,
  40, 64 and 74; text sizes, never below 12 px. Pictures are scaled to the size they are shown at:
  backdrops cover the window, a hero is a share of the window height, the slab fits 5:4 inside the
  overlay, the logo a set width. Each is scaled once, smoothly, when the window size is known.
- **Text:** one surface per place on screen, re-rendered only when its string changes, and the old
  one passed to `backend.invalidate_texture` (as `UI.show_exp` does). Fixed labels may be cached by
  their string.
- **Works on both backends**, CPU and GPU.

## Phase 0: the kit in the game

1. **One copy of the art.** Move `ui_preview/assets/kit/` to `Graphics/UI/kit/`, the four backdrops
   (`hall-sharp.jpg`, `shrine.jpg`, `warroom.jpg`, `field.jpg`) to `Graphics/UI/backdrops/`, and
   `ui_preview/assets/slot-sharp.jpg` (the slot frame, 9-sliced at 112 px) to
   `Graphics/UI/kit/slot.jpg`. `make_kit.py` writes to `Graphics/UI/kit/`; `index.html` points at
   `../Graphics/UI/` (it already reads `../Graphics/` for portraits). The preview must look the same.
2. **The energy fill.** A new `make_kit.py` piece, `fill_energy`: one horizontal band of cold blue
   light, painted and cut like the gold and blood fills. One API call.
3. **`kit.json`.** `make_kit.py` writes it next to `kit.css`, with the same measured values: bar and
   meter cap shares, the meter's opening, the frame's 9-slice, and the slot frame's slice (112).
4. **Fonts.** Static TTFs in `Graphics/Font/` with their OFL licence files: Cinzel SemiBold for
   titles and bar labels, Outfit Regular and Medium for body text. Pygame can't load the variable
   fonts the preview links. Joystix stays where it suits numbers.
5. **`ImageCache.load_smooth(path, size)`**: like `load_scaled` but `pygame.transform.smoothscale`,
   with its own cache key, so existing callers are untouched. Every kit picture loads through it.
6. **`Code/legion_ui.py`**, the only place that knows the kit:
   - `Kit(backend)` reads `kit.json` and loads pieces through `load_smooth` at their role's size.
   - `panel(size)`: the frame 9-sliced over the stone, built once per size and kept with
     `ImageCache.keep_frames`; panels over 512 px draw with a `cache_key` instead.
   - `bar(width, height, selected)`: caps plus the repeated centre, built once per size and state,
     kept.
   - `meter(width, height, fill)`: the trough built once; the fill cut to each whole-pixel width the
     first time that width is needed, kept, so a frame blits two kept surfaces and nothing is made
     per frame. Under 512 px a side, so HUD meters batch.
   - `TextSlot(font, size, colour)`: one surface for one place on screen, re-rendered on change.
   - `Scene(backdrop, rain, torches)`: the backdrop at cover size; rain as two kept drop tiles (fine
     soft drops behind, a few sharp in front) blitted whole at a scrolling offset; the torch-lit
     drops as a short loop of pre-made frames per torch, warm drops with a soft edge baked in,
     at the preview's positions (51/56, 84/54 and the reflection at 51/80 % of the painting). Rain
     only on the gate backdrop (start and death); the game's own weather is untouched.

## Phase 1: start, settings, death, and the gate

- **StartMenu**: the gate backdrop with rain and warm torches, the logo, and the options as steel
  bars (Start Game, Play online, Local co-op (dev), Settings). The selected bar is the gold one with
  the highlight running along it; a bar drops 2 px while Enter is held. The notice line stays.
  Settings opens the overlay.
- **SettingsMenu**: a framed panel over the dimmed screen; the seven rows as bars with their values
  on the right; same keys. It must fit a 648-px-tall window. Main2 draws the screen beneath for
  every state, through a draw-only call with no input (each screen's `draw`).
- **DeathMenu**: the gate backdrop tinted red, a framed panel, three bars.
- **The gate**, in Main2 around the state dispatch. The state switches at once, as today. While the
  leaves close (0.86 s), Main2 skips dispatch and calls only the old screen's draw, with no input.
  At the slam: a short shudder, dust off the seam, the seal kindles. The new state then runs; a level
  restart builds here, behind the closed leaves. The leaves hold 0.48 s and open over 1.05 s. Input
  is ignored until they are open. The two leaves are over 512 px, so they draw with `cache_key`s;
  the glow, dust and seam light are small kept surfaces. It runs when leaving the start menu (to any
  screen) and after death.

## Phase 2: choosing a hero and a level

- **PlayerSelection** becomes the preview's Player screen: the shrine backdrop, no rain; the hero
  standing on the dais in the light (`wizard.png`; `barbarian.png` for both barbarians), stepping in
  when picked; the roster as bars with head crops on the left; the stats with their icons on the
  right. Up/Down picks. The 4 × 3 grid goes, and with it the crash on Enter over an empty cell. A new
  hero needs its own full-length painting, added as a piece in `make_kit.py`.
- **PlayerConfiguration**, restyled once: the attributes as bars with icons, the points left, Ready.
  Before the game it shows on the shrine with the hero on the dais; at level-up inside a level it is
  a framed panel on black. The stickman goes.
- **LevelSelection**: the gate backdrop without rain, the levels as framed cards with their names,
  the chosen level's name as the heading. Names come from a new table in `level_layouts.py`
  (level number to name; starting from the preview's: Level 8, Level 7, Frostreach Gate, Frostreach
  Expanse, Sunspine Dunes, Level 6, Sunspine). Enter grows the chosen card to fill the window over
  0.75 s, then Main2 builds the level while that picture covers the screen, then the level shows.
  On the CPU backend the growing picture is rescaled each frame for those 0.75 s; on the GPU backend
  `blit_scaled` with a `cache_key` draws it without new surfaces. The Frostreach Gate and Level 6
  pictures are a debug map and a plain texture; new level pictures are a separate ask.
- Local co-op skips the attributes and level screens, and online play picks the hero in the lobby,
  so those paths show only Player selection or neither.

## Phase 3: the online screens

- `menu_widgets.py` draws through `legion_ui` and the backend instead of onto a composed surface:
  `Button` as a bar, `Choice` as a bar with its value, `TextField` as a framed plaque, `ListView`
  rows as bars, `panel()` as a framed stone panel with a Cinzel title; `font()` uses Cinzel and
  Outfit.
- `LobbyScreen.draw`: the seats as bars (yours gold), the chat board as a framed panel with its
  field.
- `Main2._draw_screen`: the war-room backdrop instead of the flat colour.

## Phase 4: the overlays in a level

All stay on black, as today.

- **Upgrade**: a framed panel; the hero standing on the left; one steel bar per stat, stacked, with
  its icon, its cost, its value and a gold meter; `player.exp` top right beside the gem icon (the gem
  is a picture of experience, not a second currency). Up/Down move, Space buys, P closes.
- **Inventory**: the slab at its own 5:4; the painted doll with the nine body slots on head, chest,
  belt, hands, weapons and feet; the sigil faint in the empty helmet slot; the pack 3 wide × 4 tall
  as today; the belt of four. Slots use the slot frame and show the game's own item pictures (the
  kit's four item marks were for the preview's stand-in items). Gold top right.
- **AttackSelection**: a framed panel; its slots in the slot frame; the game's attack icons.
- **Level-up**: the restyled `PlayerConfiguration` from Phase 2, as a framed panel.

## Phase 5: the HUD

- **Inside the window.** The weapon and magic boxes and the belt are placed from the window's
  bottom edge, not a fixed y.
- Health as a meter with the blood fill, energy with the energy fill; experience as the gem icon and
  the number; the level; the weapon and magic boxes in the slot frame. The weapon and magic
  pictures load through `ImageCache`, so they batch. Every HUD piece is under 512 px a side and kept.
- **Measure** before the first HUD change and after the last, back to back, from `Code/` in one
  PowerShell call (labels `legion-hud-before` and `legion-hud-after`):

  ```powershell
  $label = "legion-hud-before"
  New-Item -ItemType Directory -Force ..\logs\perf | Out-Null
  $env:PRCH_BENCHMARK_ENABLED = "1"
  $env:PRCH_BENCHMARK_LAYOUT_DIR = "../levels/tmx"
  $env:PRCH_BENCHMARK_ENTITY_COUNT = "200"
  $env:PRCH_BENCHMARK_ENEMY_MIX = "ice_ghost:60,raccoon:30,spirit:30,ice_mage:25,demon_dog:20,venom_plant:20,tribey_snake:15"
  $env:PRCH_BENCHMARK_BROADPHASE_BACKEND = "grid"
  $env:PRCH_BENCHMARK_GRID_CELL_SIZE = "450"
  $env:PRCH_BENCHMARK_WARMUP_SECONDS = "10"
  $env:PRCH_BENCHMARK_AUTO_RUN_SECONDS = "30"
  $env:PRCH_BENCHMARK_METRICS_CSV_PATH = "../logs/perf_ice200.csv"
  $env:PRCH_BENCHMARK_RUN_LABEL = $label
  .\sprite_venv\Scripts\python.exe Main2.py
  Get-ChildItem Env:PRCH_BENCHMARK_* | Remove-Item
  ```

  From each CSV row: average and p95 frame ms, and the draw-call counts per frame. Draw calls may
  rise only by the HUD pieces added. Log both rows in `Code/NOTES_performance.md`.

## Not in this plan

- **A pause menu.** The preview's pause screen (Resume, Inventory, Map, Attributes, Attacks,
  Upgrade, Settings, Main menu) has no counterpart in the game: each overlay has its own key.
- **What attack selection should do** (see decision 6).
- **Drawing the world beneath the overlays in a level.** They stay on black.
- **A world map screen**: not on `main` (the minimap is on `feature/minimap-fog`).
- **Rain or any change to the game's weather in a level.**
- **New level pictures.**
- **The other preview looks** (Vessel, Temple, Covenant, Bound, Citadel): only Legion goes in.
