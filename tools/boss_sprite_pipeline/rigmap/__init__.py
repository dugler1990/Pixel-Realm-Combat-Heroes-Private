"""Role match between a Kimodo skeleton and one of our rigs. No Blender."""

from .bvh import Skeleton, load_bvh
from .fit import apply_patch, edits, fit, knob_env
from .label import label_bvh, label_roles
from .legacy import as_legacy_map
from .match import match

__all__ = [
    "Skeleton", "load_bvh", "label_bvh", "label_roles", "match", "fit",
    "apply_patch", "edits", "knob_env", "as_legacy_map",
]
