"""Custom per-level composition pass.

A hand-authored creative generation that re-composes a sub-level's accepted art to establish
the level's identity (open desert, a set of pyramids, ruins, ...) BEFORE it is upscaled and
diced into a fine grid. Unlike the grid detail pass, this pass is *allowed to add and reshape*
features; the grid pass later preserves whatever this produces and only adds resolution.

Reuses the existing gpt-image-2 call (``openai_api.edit_image``); keeps numbered attempts and
an accept step, mirroring the generation pipeline. The prompt is a hand-authored file, one per
custom level.

Two player-scale helpers, both via ``_composite_players``:
- **input anchor** (``player_px`` set): unmarked player-sized figures composited onto the input
  so the model sizes features to what it can *see*, not to a text px number.
- **review overlay** (always): the finished output gets a copy with marked player figures
  (``composed_with_player.png``) so the scale is instantly judgeable.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from ..openai_api import edit_image
from .state_store import read_json

_DEFAULT_PLAYER_SPRITE = Path("image_assets/barbwalk/0.png")
_REVIEW_PLAYER_PX = 8  # "the appropriate size we decided" for the review overlay, for now
_SCALE_REFERENCE_NOTE = (
    "Scattered across the sand are several small human figures, each drawn in bright magenta, "
    "ringed with a magenta outline, and captioned with an '8px player' label. Every one of "
    "those marked figures is the PLAYER at its true height of EXACTLY 8 PIXELS -- that 8-pixel "
    "height sets the scale for the whole map. Wherever a bright magenta outlined figure "
    "appears, keep a human there at exactly 8 pixels tall; size every rock, ruin, statue, "
    "obelisk and pyramid relative to it. You may drop the magenta colour, ring and label, but "
    "the human stays exactly 8 pixels."
)


def _next_attempt(composed_dir: Path) -> int:
    numbers = [
        int(path.name.split("_")[-1])
        for path in composed_dir.glob("attempt_*")
        if path.name.split("_")[-1].isdigit()
    ]
    return (max(numbers) + 1) if numbers else 1


def _composite_players(
    source: Path,
    dest: Path,
    sprite: Path,
    player_px: int,
    count: int,
    *,
    mark: bool = False,
    label: str | None = None,
    bright: bool = False,
    label_all: bool = False,
) -> None:
    """Composite ``count`` player-sized figures onto a copy of ``source`` (feet on non-black
    ground), deterministic placement. ``bright`` tints each figure magenta so it is
    unmistakable, ``mark`` rings each, ``label`` captions (the first, or all with
    ``label_all``) -- used both for the model-facing input anchor (all on) and the review
    overlay (mark + one label)."""
    art = Image.open(source).convert("RGBA")
    width, height = art.size
    land = np.asarray(art)[..., :3].sum(axis=2) > 40
    with Image.open(sprite) as raw:
        barb = raw.convert("RGBA")
    alpha = np.asarray(barb)[..., 3] > 10
    ys, xs = np.where(alpha)
    barb = barb.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
    w = max(1, round(barb.width * player_px / barb.height))
    stamp = barb.resize((w, player_px))
    if bright:
        pix = np.asarray(stamp).copy()
        opaque = pix[..., 3] > 10
        pix[opaque, 0], pix[opaque, 1], pix[opaque, 2] = 255, 0, 255  # bright magenta figure
        stamp = Image.fromarray(pix, "RGBA")
    draw = ImageDraw.Draw(art) if (mark or label) else None
    rng = np.random.default_rng(0)
    placed = tries = 0
    positions: list[tuple[int, int, int]] = []
    while placed < count and tries < 4000:
        tries += 1
        x = int(rng.integers(0, max(1, width - w)))
        y = int(rng.integers(0, max(1, height - player_px)))
        if not land[min(y + player_px - 1, height - 1), min(x + w // 2, width - 1)]:
            continue
        art.alpha_composite(stamp, (x, y))
        if draw is not None and mark:
            draw.ellipse([x - 6, y - 6, x + w + 6, y + player_px + 6], outline=(255, 0, 255, 255), width=2)
        positions.append((x, y, w))
        placed += 1
    if draw is not None and label and positions:
        for x, y, fw in (positions if label_all else positions[:1]):
            tx, ty = x + fw + 8, y - 5
            draw.rectangle([tx - 2, ty - 2, tx + 8 * len(label) + 6, ty + 15], fill=(0, 0, 0, 230))
            draw.text((tx, ty), label, fill=(255, 0, 255, 255))
    art.convert("RGB").save(dest)


def compose_level(
    root: Path,
    level_id: str,
    prompt_path: Path,
    *,
    player_px: int | None = None,
    player_sprite: Path | None = None,
    player_count: int = 6,
) -> dict[str, Any]:
    """Re-compose ``levels/<id>/accepted/image.png`` per the prompt file and write a new
    ``composed/attempt_NNN/{composed.png, prompt.txt, composed_with_player.png}``. Generates at
    the accepted art's own size; the generation config comes from the run's ``config.json``
    ``generation`` block. With ``player_px`` set, a scale-anchored copy of the input
    (``input_stamped.png``) is what gets sent; the review overlay is always produced."""
    root = Path(root)
    accepted = root / "levels" / level_id / "accepted" / "image.png"
    if not accepted.is_file():
        raise ValueError(f"level {level_id} has no accepted image to compose from ({accepted})")
    prompt = Path(prompt_path).read_text(encoding="utf-8").strip()
    generation = read_json(root / "config.json").get("generation") or {}
    sprite = Path(player_sprite) if player_sprite else _DEFAULT_PLAYER_SPRITE

    with Image.open(accepted) as img:
        width, height = img.size

    composed_dir = root / "levels" / level_id / "composed"
    attempt = _next_attempt(composed_dir)
    attempt_dir = composed_dir / f"attempt_{attempt:03d}"
    attempt_dir.mkdir(parents=True, exist_ok=True)

    input_image = accepted
    if player_px:
        input_image = attempt_dir / "input_stamped.png"
        _composite_players(
            accepted, input_image, sprite, player_px, player_count,
            mark=True, label=f"{player_px}px player", bright=True, label_all=True,
        )
        prompt = f"{prompt}\n\n{_SCALE_REFERENCE_NOTE}"

    output_path = attempt_dir / "composed.png"
    (attempt_dir / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")

    edit_image(
        prompt=prompt,
        input_images=[input_image],
        mask=None,
        output_path=output_path,
        width=width,
        height=height,
        config=generation,
    )

    review_path = write_player_overlay(output_path, sprite, player_px or _REVIEW_PLAYER_PX)
    return {
        "level_id": level_id,
        "attempt": attempt,
        "prompt_path": str(prompt_path),
        "input_path": str(input_image),
        "composed_path": str(output_path),
        "review_path": str(review_path) if review_path else None,
    }


def write_player_overlay(composed_path: Path, sprite: Path, player_px: int, count: int = 5) -> Path | None:
    """Write ``composed_with_player.png`` beside a composed output: the finished art with a few
    marked player-sized figures, so the scale is judgeable at a glance. Best-effort (skips if the
    sprite is missing)."""
    composed_path = Path(composed_path)
    sprite = Path(sprite)
    if not sprite.is_file():
        return None
    dest = composed_path.parent / "composed_with_player.png"
    _composite_players(
        composed_path, dest, sprite, player_px, count, mark=True, label=f"player {player_px}px"
    )
    return dest


def accept_composition(root: Path, level_id: str, attempt: int) -> dict[str, Any]:
    """Promote a chosen composed attempt to the design-locked ``composed/composed.png``."""
    root = Path(root)
    composed_dir = root / "levels" / level_id / "composed"
    source = composed_dir / f"attempt_{int(attempt):03d}" / "composed.png"
    if not source.is_file():
        raise ValueError(f"no composed attempt {attempt} for level {level_id} ({source})")
    destination = composed_dir / "composed.png"
    shutil.copy2(source, destination)
    return {"level_id": level_id, "attempt": int(attempt), "composed_path": str(destination)}
