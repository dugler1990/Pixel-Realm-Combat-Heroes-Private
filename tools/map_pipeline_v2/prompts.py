"""Prompt assembly from versioned templates.

Two templates, selected by continuity state:
- `seed` — no neighbor pad (the v1 04/attempt_007 wording that worked).
- `pad`  — has neighbor pad (the v1 07/attempt_003 SHORT continuity block — NOT the
           A/B "two kinds of land" essay that regressed to full-frame).

Both lead with the silhouette/black-footprint rules and the world's projection.
Templates are plain strings here; they can move to files without changing callers.
"""

from __future__ import annotations

from .config import PromptConfig
from .models import Level, World

_SHARED_SHAPE_RULES = [
    "In input.png, land is the non-black region on a pure black (#000000) background.",
    "That non-black footprint is the exact output shape: every land edge, coastline, and corner must match it.",
    "Paint terrain only on those non-black pixels.",
    "Outside that footprint must stay pure black (#000000) — same black as the reference, no grey, vignette, fade, or fill to the rectangle border.",
    "Do not enlarge, shrink, round, straighten, or otherwise change the land outline.",
    "If land reaches the image border where the reference has black, that is wrong.",
]

_SEED_BODY = [
    "Treat input.png as a locked layout to repaint, not as inspiration.",
    "Keep the same ridges, plains, water, ice floes, and coastlines in the same places and proportions.",
    "Do not invent a new map layout, new peak pattern, or relocated coastline.",
    "Upgrade materials and detail only; the geography must remain recognizable as the same chunk.",
    "No neighbor padding is present. This is a seed level.",
]

_PAD_BODY = [
    "input.png already contains final neighbor padding from level(s): {neighbors}.",
    "That already-painted padding strip is final art and the visual source of truth for color, materials, texture scale, and lighting.",
    "Do not restyle, recolor, or reinterpret the padding. Generate only the unfinished land as a continuous extension of it, as if the whole level were painted in one pass.",
    "Unfinished land must follow the locked layout rules above and match the padding's visual language — not a different style that only meets it at the edge.",
]


def render_prompt(
    level: Level,
    world: World,
    prompt_cfg: PromptConfig,
    locked_neighbor_ids: list[str],
) -> str:
    lines: list[str] = [
        f"Render level {level.level_id}: {level.name} ({level.region}).",
        f"Return exactly {world.size.width}x{world.size.height} pixels.",
        f"Projection: strict {world.projection.replace('_', '-')} — no perspective, no horizon, no camera tilt.",
        "Reference image: input.png only.",
        *_SHARED_SHAPE_RULES,
    ]
    if locked_neighbor_ids:
        neighbors = ", ".join(locked_neighbor_ids)
        lines += [line.format(neighbors=neighbors) for line in _PAD_BODY]
    else:
        lines += _SEED_BODY

    if prompt_cfg.negatives:
        lines.append("Do not add: " + ", ".join(prompt_cfg.negatives) + ".")
    lines.append("Keep lighting diffuse and shadow-neutral: local form shading allowed, directional cast shadows not.")
    lines.append("Style (materials and lighting only — must not override the layout/padding rules above):")
    lines.append(prompt_cfg.style_prompt)
    return "\n".join(lines).strip() + "\n"
