"""Splitting a typed retry into criticism and an attached picture.

Lifted out of ``review_run.parse_retry`` unchanged so the building-interiors gates can use the
same syntax rather than growing a second one. What is shared is only the parsing: which
overlay ``r1`` reaches for is per-pipeline, because the two keep their attempts in different
places, so each caller supplies its own path and this stays about the text.
"""

from __future__ import annotations

from pathlib import Path


def split_retry(line: str) -> tuple[str, Path | None, str]:
    """Split `r <why> @<image> <note about it>` into (reason, image, note).

    The path is the one token straight after the `@`; everything after that token is the note
    describing it, with or without an `@@` in front. Taking the whole remainder as the filename
    is how a sentence ends up being stat()ed.
    """
    body = line[1:]
    body, _, tail = body.partition("@@")
    reason, _, token = body.partition("@")
    parts = token.split(None, 1)
    token = parts[0] if parts else ""
    note = " ".join(part.strip() for part in (parts[1] if len(parts) > 1 else "", tail)
                    if part.strip())
    if not token:
        # A note with nothing to attach it to is still criticism; keep it as the reason rather
        # than dropping it silently.
        return " ".join(part for part in (reason.strip(), note) if part), None, ""

    path = Path(token).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"no such image: {path}")
    # A stray non-ASCII character from a paste would make ascii_prompt reject the whole job.
    return reason.strip(), path, note.encode("ascii", "ignore").decode("ascii")


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
