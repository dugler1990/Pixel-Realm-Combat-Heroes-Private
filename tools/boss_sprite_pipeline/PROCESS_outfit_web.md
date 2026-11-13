# Outfit web page: process

The outfit pipeline (`outfit.py`, `PROCESS_outfit.md`) in the browser. Plan: `.cursor/plans/outfit_web.plan.md`.

## Method that works

Launch (PowerShell, repo root):
```
$env:OUTFIT_DATA_ROOT = "C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss"
Code\sprite_venv\Scripts\python.exe -m tools.boss_sprite_pipeline.outfit_web      # opens http://127.0.0.1:8767/
```
`--port N`, `--no-browser`. A link `http://127.0.0.1:8767/#barb/naked/trellis` opens that outfit at that step.

- Keys: copy a key, press its "from clipboard" (OpenAI, Leonardo, HF). The page shows set / –, never the value.
- Pod: paste RunPod's ssh line (`…@ssh.runpod.io …`) → Set: `pod.py address` asks the proxy for the direct
  IP / port. `IP:port` works too. The bar shows GPU %, memory, what runs, what is installed (every 10 s).
  Red **stop the pod** shows whenever a pod is set and no pod step runs. The page never starts or stops a pod.
- TRELLIS models: tick, Save (`--models`, kept in run.json). They decide which drawings the run asks for.
- Each step chip opens its panel; "Run <step>" runs `outfit.py <c> <o> --only <step>`. Gates: Accept N, Redraw
  (r / r1 / rb, a reason, an image: uploaded to `<run>/gate/uploads/`, sent as `@path`), Pick (TRELLIS), Accept
  paint / Repaint views.
- Two lanes: a pod step and a local step can run at once, for different outfits.

Files: `outfit_web.py` (server), `web/outfit.html` (page), `tests/test_outfit_web.py` (fake driver).

## Known errors

| Symptom | Cause | Fix |
|---|---|---|
| Pod bar: "no answer from <ip>:<port>" | pod stopped, or restarted with a new address | paste the new ssh line |
| "the X lane is busy" | one command per lane | wait; the log shows it |

## Log

- 2026-11-14: built. 14 tests pass (`tests/test_outfit_pipeline.py`, `tests/test_outfit_web.py`). Checked on the
  real runs (barb fullplate, loincloth, naked) with headless Chrome screenshots: outfit list, TRELLIS gate with
  the 2-model sheet, sides strip of 8 views, paint grid. Pod status against a stopped pod: the error shows.
- Not yet done: a step run from a button on a real outfit (paid calls / a pod); clicking in a real browser.

## Tried and dropped

(none yet)
