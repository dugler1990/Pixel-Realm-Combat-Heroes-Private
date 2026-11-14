"""Splitting a typed retry into criticism and an attached picture.

Lifted out of ``review_run.parse_retry`` unchanged so the building-interiors gates can use the
same syntax rather than growing a second one. What is shared is only the parsing: which
overlay ``r1`` reaches for is per-pipeline, because the two keep their attempts in different
places, so each caller supplies its own path and this stays about the text.
"""

from __future__ import annotations

from pathlib import Path

from ..review_gate import split_retry  # review_run imports it from here too


def shape_retry(line: str, overlay: Path, note: str, directive: str) -> tuple[str, Path, str]:
    """`r1`: the shape-error overlay for this draw, with the standing wording for it.

    By far the commonest retry, and typing the paragraph out each time invites it drifting --
    which is the whole reason the two texts are constants rather than literals at a call site.
    Anything typed after the `r1` is appended, so `r1 the doorway is still sealed` works.
    """
    extra = line[2:].strip()
    full = f"{note}. {directive}"
    if extra:
        full = f"{full} {extra}"
    return "", Path(overlay), full.encode("ascii", "ignore").decode("ascii")


def parse_gate_retry(raw: str, overlay, note: str, directive: str) -> tuple[str, list]:
    """`r1` / `r <why> @image <note>` at a gate -> (criticism, attachments).

    One syntax for every gate: `r1` attaches this draw's shape overlay with the gate's own `note`
    and `directive`; anything else is `split_retry`'s criticism. A bare `r` is NOT handled here: it
    means "draw more" in every gate, and the caller checks for it first.
    """
    if raw[:2].lower() == "r1":
        if not overlay or not Path(overlay).is_file():
            raise FileNotFoundError(
                "no shape overlay for this draw (nothing to point at) -- draw one first")
        _reason, image, text = shape_retry(raw, Path(overlay), note, directive)
        return text, [image]
    reason, image, extra = split_retry(raw)
    criticism = " ".join(part for part in (reason, extra) if part).strip()
    return criticism, ([image] if image else [])
