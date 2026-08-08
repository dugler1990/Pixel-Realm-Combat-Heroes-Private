# map_pipeline_v2 — Design

Clean-room rewrite of the irregular world-level map-art pipeline
(`tools/painted_map_pipeline/world_levels/`). v1 stays untouched as reference.

Goal: generate per-level top-down map art for irregular land silhouettes on a
black canvas, with neighbor overlap ("pad") baked into the next level's input for
visual continuity — but architected so the model/operation is a swappable,
capability-declaring plugin, and so a bad generation can never silently melt or
auto-accept.

---

## Why a rewrite (the v1 lessons this design encodes)

v1 worked "almost perfectly" with a **mask-locked edit model** (gpt-image via
Cursor), then regressed when generation was swapped to **Leonardo
`image_reference`** (a soft global style guide with no mask). The failure stack:

1. The swap silently removed the spatial lock — "keep the black background" went
   from *enforced* to *hoped-for in the prompt*. Outputs began filling the frame.
2. Prompt escalation to compensate (the "A/B two-kinds-of-land" essay) pushed even
   harder toward full-frame and dropped the shape-holding language.
3. `land_fit` RBF-warped a full-frame output onto the small silhouette → melt.
4. `approval_mode: automatic` accepted the melt and propagated it to neighbors.

Every one of those is designed out here:

| v1 failure | v2 answer |
|---|---|
| Model operation hardcoded to soft-reference | Backend **capability contract**; pipeline adapts to it |
| Always RBF-warp → melt on overflow | `conform/` strategy = f(capability, measured fit); **crop, don't warp** |
| No QA before accept | `qa/` gate runs before any accept; fail → retry/escalate |
| Auto-accept of garbage | `approval_mode: auto_if_pass` (never "accept whatever") |
| Prompt logic in Python `if` branches | Versioned prompt **templates**, config-selected |
| Projection drift (04 oblique vs 07 top-down) | `projection` is a first-class, enforced world property |
| JPEG near-black degraded shape cue | Reference **encoding is config** (png default) |
| Reset footgun | `reset` is a first-class command |

---

## Principles

1. **Functional core, imperative shell.** Geometry, masks, conform math, QA
   metrics, prompt assembly = pure functions, unit-testable on tiny synthetic
   fixtures with no API key. API calls, file writes, state mutation = thin shell.
2. **Backend capability is explicit.** A backend declares whether it enforces the
   frozen region (mask-locked) or merely suggests it (soft reference). The
   pipeline picks conform + QA strategy from that declaration.
3. **Nothing is accepted without passing a gate.**
4. **Every attempt is a reproducible, self-describing bundle** (prompt, params,
   model, seed, request id, raw, conformed, qa).
5. **Config-driven, not code-driven.** Prompts are versioned templates; thresholds,
   projection, strengths, encodings are config.

---

## Architecture (dependency stack; each layer depends only on those above)

| Layer | Module | Owns | Pure? |
|---|---|---|---|
| Geometry/topology | `models` (+ future `world/`) | plan, sizes, silhouettes, neighbor graph, overlaps, transforms | ✅ |
| Asset prep | `pipeline.prepare_*` (→ `assets/`) | per-level static files: masks, base template, locator | mostly |
| Continuity | `pipeline.compose_*` (→ `continuity/`) | locked pad from accepted neighbors; paint/freeze masks | mostly |
| Prompting | `prompts` | level + continuity + style → prompt from templates | ✅ |
| Generation | `backends/`, `service` | provider abstraction + adapters; retry/log/artifact wrapper | shell |
| Conform | `conform` | raw → silhouette-fit candidate; strategy by capability + fit | ✅ |
| QA | `qa` | IoU, area-ratio, black-purity, seam-delta → pass/fail report | ✅ |
| Acceptance | `pipeline.accept_*` (→ `accept/`) | gate → write accepted → propagate pad → bump revisions | shell |
| State/orchestration | `store`, `pipeline` | state machine, event log, resume, reset | shell |
| CLI/report | `cli` | prepare/run/ingest/accept/reject/reset/validate/report; dry-run | shell |

Note: some layers are single modules today and become sub-packages as they grow
(`world/`, `assets/`, `continuity/`, `accept/`). The boundaries are the contract;
the file layout follows need.

---

## The backend contract (the spine)

Three things v1 conflated, separated here:

- **Operation** — what we ask for: `EDIT_MASKED`, `REFERENCE_GUIDED`,
  `STRUCTURAL`, `TXT2IMG`.
- **Provider/model** — who does it: OpenAI gpt-image, Gemini/nano-banana direct,
  Leonardo (nano-banana-2), future (Flux, SDXL, local).
- **Capability** — what it *guarantees*: freezes pixels? accepts a mask? refs? size?

```python
@dataclass(frozen=True)
class GenerationRequest:
    prompt: str
    canvas: ImageRef            # composed input (pad baked, placeholder inside)
    paint_mask: MaskRef         # where the model MAY paint (pending region)
    freeze_mask: MaskRef | None # pixels that MUST survive (pad + outside black)
    size: Size
    seed: int | None
    params: Mapping[str, Any]   # neutral knobs: strength, guidance, candidates

@dataclass(frozen=True)
class BackendCapabilities:
    enforces_region: bool       # True => freeze_mask honored by construction
    accepts_mask: bool
    max_refs: int
    native_size: Size | None
    supports_seed: bool

class GenerationBackend(ABC):
    name: str
    def capabilities(self) -> BackendCapabilities: ...
    def validate_config(self) -> list[str]: ...   # preflight: keys, params, sizes
    def generate(self, req, *, workdir) -> GenerationResult: ...
```

The request always carries **both** `paint_mask` and `freeze_mask`. A mask-edit
backend uses them directly; a soft-reference backend ignores `freeze_mask` but
declares `enforces_region=False`, and the pipeline compensates in `conform`/`qa`.
Switching backends can never again silently melt.

Adding a backend = one adapter + `@register_backend("name")` + a config block. No
pipeline changes.

Cross-cutting concerns (retries, seed variation, logging, artifact capture, cost/
rate-limit) live in `GenerationService` wrapping the backend — adapters stay tiny.

Planned adapters:
- `copy` / `dryrun` / `overflow_demo` — key-free, for the loop + tests.
- `leonardo_image_reference` — current v1 path. `enforces_region=False`.
- `gpt_image_edit` — mask inpaint. `enforces_region=True`. The "almost perfect" path.
- `gemini_edit` — nano-banana as a direct instructed editor.
- `leonardo_controlnet` / `leonardo_canvas` — if/when verified available.

---

## Conform (generalized melt fix)

`conform` never blindly warps. Strategy is chosen from capability + measured fit:

- `enforces_region=True` → **identity** (+ paste freeze region for safety).
- overflow (content area ≫ mask area) → **crop** to silhouette.
- near-fit, opt-in only → **warp** (v1 `land_fit`, demoted to one strategy).
- then paste locked pad + feather seam.

---

## QA gate

Runs before accept; emits a report: `iou`, `content_area_ratio`, `black_purity`,
`seam_delta`, verdict. Fail → retry policy (reseed / prompt-variant / escalate to
manual). Never a silent accept.

---

## State machine

`prepared → ready → generating → generated → qa_passed | qa_failed → accepted`
(`failed` on backend error). `reset` clears accepted + state + fields atomically.

---

## Config (layered, resolved + snapshotted per run)

- `world` — canvas size, **projection**, outside_color, scale, placement.
- `generation` — provider, operation, model, strength, **reference_encoding
  (png|jpeg)**, size, seed, candidates.
- `prompt` — template ids per mode, style prompt, negatives.
- `continuity` — pad width, source ordering, feather radius, seam blend.
- `conform` — strategy + thresholds.
- `qa` — gate thresholds (min_iou, max_area_ratio, black_purity_tol, seam_delta).
- `execution` — approval_mode (`manual` | `auto_if_pass`), retry limit + strategy,
  stop_on_failure, concurrency.
- `observability` — log level, artifact retention, report on/off.

---

## Observability

- `events.jsonl` structured log (kept from v1).
- Per-attempt bundle: `input.png`, `prompt.txt`, `params.json`, `raw.png`,
  `conformed.png`, `qa.json`, `backend_response.json`.
- Per-run **HTML contact sheet**: input │ raw │ conformed │ accepted + QA verdict,
  so regressions are seen, not read.

---

## Build phases

- **Phase 0 (this scaffold)** — runnable spine on `copy`/`overflow_demo` backends
  over a **toy** world (no keys, no cost). Proves loop + state + conform + QA +
  logging. `python -m tools.map_pipeline_v2.cli demo <workdir>`.
- **Phase 1** — port real geometry (`world/assets/continuity`) from v1 with
  synthetic-fixture unit tests + parity check.
- **Phase 2** — harden conform strategies + QA thresholds; reproduce the melt in a
  test and prove crop fixes it; port `land_fit` as the opt-in warp strategy.
- **Phase 3** — real backends: `leonardo_image_reference` (you have the key), then
  `gpt_image_edit` / `gemini_edit`.
- **Phase 4** — run 04→07 through both backends; HTML compare; tune.
- **Phase 5** — acceptance/propagation, reset, polish.

Status is tracked in `README.md`.
