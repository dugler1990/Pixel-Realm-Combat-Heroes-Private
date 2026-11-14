# Outfit web page: process

The outfit pipeline (`outfit.py`, `PROCESS_outfit.md`) in the browser. Plan: `.cursor/plans/outfit_web.plan.md`.

## Method that works

Launch (PowerShell, repo root):
```
$env:OUTFIT_DATA_ROOT = "C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss"
Code\sprite_venv\Scripts\python.exe -m tools.boss_sprite_pipeline.outfit_web      # opens http://127.0.0.1:8767/
```
`--port N`, `--no-browser`. A link `http://127.0.0.1:8767/#<character>/<outfit>/<step>` opens that outfit at
that step; `#new` the new-character form, `#new/<character>` the new-outfit form.

- Keys: copy a key, press its "from clipboard" (OpenAI, Leonardo, HF). The page shows set / –, never the value.
- Pod: paste RunPod's ssh line (`…@ssh.runpod.io …`) → Set: `pod.py address` asks the proxy for the direct
  IP / port. `IP:port` works too. The bar shows GPU %, memory, what runs, what is installed (every 10 s).
  Red **stop the pod** shows whenever a pod is set and no pod step runs. The page never starts or stops a pod.
- TRELLIS models: tick, Save (`--models`, kept in run.json). They decide which drawings the run asks for.
- Each step chip opens its panel; "Run <step>" runs `outfit.py <c> <o> --only <step>`. Gates: Accept N, Redraw
  (r / r1 / rb, a reason, an image: uploaded to `<run>/gate/uploads/`, sent as `@path`), Pick (TRELLIS), Accept
  paint / Repaint views.
- Two lanes: a pod step and a local step can run at once, for different outfits.
- Names on the page (outfit_web.py KIND_UI / STEP_UI / PHASES; files and driver keep theirs): kinds Body variant
  (body), Armour set (armour), Pieces from a mesh (cut); steps by phase Views / 3D model / Pieces / Game with plain
  labels (sam3 = Find parts, holopart = Complete parts, skeleton = Fit to rig ...), the step name small beside.
- Left list: one block per character (name: its page; + outfit), its outfits by name with kind, next step, and
  one pill per phase (done / total). Character page (`#character/<c>`): each character field set / not set / file
  missing, which steps read it, its outfits. Forms: the kind as cards; only the fields that kind's steps read (or
  already set), under phase headings.
- New character / + outfit: name, character, start from (blank or a copy) in the form. Forms per file from
  `outfit_fields.py`; files picked from the character's data folder or uploaded to
  `<data>/generated/bosses/<character>/inputs/`. Save refuses wrong values only; a missing field is named by the
  step that reads it (`steps` in the field table), so a new character runs to TRELLIS with no rig. A new
  character's Save opens its first outfit (body). The page writes `outfits/<c>/*.json` (repo: review and commit).
  `#settings/<c>[/<outfit>]` opens a form.
- Your own images: outfit form → images, one slot per view (upload / pick; "needed" = the ticked models'
  views). A given view is used, not drawn: `view_gate --use`, accepted when its check passes (a given front with
  no concept: always, nothing to compare); a failed check waits at the gate and is not redrawn on its own. Given
  right-hand views are not mirrored. A given front / back needs no prompt; a given front no concept.
- Outfit view: the views strip (your image / drawn / mirrored, done), "Still to fill in" (field, file, steps).
- Run on from <step>: `outfit.py <c> <o> --to <next step in the other lane>`: the not-done steps up to a gate,
  a failure or the pod / local switch (a pod run needs the pod set).
- "Use this image" under a view's redraw form: the image as the next attempt (`--use`), then Accept.
- install: missing piece stats as a form (start from an existing base) → `item_bases.json`; a body's hero entry
  with a write button → `PlayerSelectionDict.json`.

Files: `outfit_web.py` (server), `web/outfit.html` (page), `tests/test_outfit_web.py` (fake driver).

## Known errors

| Symptom | Cause | Fix |
|---|---|---|
| Pod bar: "no answer from <ip>:<port>" | pod stopped, or restarted with a new address | paste the new ssh line |
| "the X lane is busy" | one command per lane | wait; the log shows it |
| Page shows old buttons after a code change | an older server still on the port: Windows lets two listen on 8767, the old one answers | close the old one (Ctrl+C in its window), start again; `netstat -ano \| findstr :8767` shows both |

## Log

- 2026-11-14: built. 14 tests pass (`tests/test_outfit_pipeline.py`, `tests/test_outfit_web.py`). Checked on the
  real runs (barb fullplate, loincloth, naked) with headless Chrome screenshots: outfit list, TRELLIS gate with
  the 2-model sheet, sides strip of 8 views, paint grid. Pod status against a stopped pod: the error shows.
- Not yet done: a step run from a button on a real outfit (paid calls / a pod); clicking in a real browser.

- 2026-11-14: settings forms, use-an-image, install panel (`feat/outfit-config`). 24 tests
  (`test_outfit_pipeline.py`, `test_outfit_web.py`). Headless Chrome: fullplate outfit form, barb character form,
  fullplate run view, looked at. Not yet: a real save / use / install clicked in a browser.
- 2026-11-14: your own images per view, fields checked per step, run on, list by character, new forms in the
  page. 29 tests (`test_outfit_pipeline.py`, `test_outfit_web.py`). Barb record (`_checks/barb_unchanged.py`)
  identical to the previous one: commands, looks, export, retarget, clips. Headless Chrome on port 8768, no
  console errors: list, new outfit (8 view slots), new character, naked run view (views strip), looked at. Not
  yet: a new outfit from real images run through TRELLIS (pod).
- 2026-11-14: page names: kinds, phases, step labels, character page, forms by kind and phase. 29 tests. Headless
  Chrome on 8768, no console errors: list, fullplate view, new outfit, loincloth settings, barb page, looked at.

## Tried and dropped

(none yet)
