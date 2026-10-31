"""Splitting a typed retry into criticism and an attached picture.

Lifted out of ``review_run.parse_retry`` unchanged so the building-interiors gates can use the
same syntax rather than growing a second one. What is shared is only the parsing: which
overlay ``r1`` reaches for is per-pipeline, because the two keep their attempts in different
places, so each caller supplies its own path and this stays about the text.
"""

from __future__ import annotations

from pathlib import Path

from ..review_gate import split_retry  # noqa: F401  (review_run and interiors/cli import it from here)


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
