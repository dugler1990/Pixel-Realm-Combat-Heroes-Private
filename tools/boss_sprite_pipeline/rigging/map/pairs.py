"""Source x character exceptions: facts about one source on one body, not about either alone."""
from __future__ import annotations

PAIRS = {
    # A flat-footed source onto a digitigrade target: bind match would aim his metatarsus along the
    # flat foot and splay it. Skipped bones keep their rest orientation and take the motion on top.
    ("g1", "demon"): {"bind": {"ankle.L": False, "foot.L": False, "ankle.R": False, "foot.R": False}},
}


def get(source: str, cid: str) -> dict:
    return PAIRS.get((source, cid), {})
