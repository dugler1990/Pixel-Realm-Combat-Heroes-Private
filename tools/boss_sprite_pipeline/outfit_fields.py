"""Every setting of a character file and an outfit file: one row each. The checks, the web page's forms and the tests
come from this table; a new setting is a new row.

Row: name; level (character: outfits/<c>/character.json, outfit: outfits/<c>/<outfit>.json; an outfit may still
override a character field); kinds (outfit kinds that need it; empty: optional); type; help.
Types: image / glb / blend / json (a file: paths relative to the data root, repo files for looks and configs),
text, number, bool, list, dict, choice (one of `choices`).
Keys starting with "_" and ending in "_note" are notes, allowed anywhere.
"""
from __future__ import annotations

from dataclasses import dataclass

ALL = ("body", "armour", "cut")
TRELLIS_MODELS = ("front_only", "front_back", "front_back_sides", "eight_views")   # = outfit.MODEL_VIEWS keys
KINDS = ALL


@dataclass(frozen=True)
class Field:
    name: str
    level: str
    kinds: tuple
    type: str
    help: str
    choices: tuple = ()


FIELDS = (
    # --- character -------------------------------------------------------------------------------------------
    Field("rig_fit", "character", ALL, "glb",
          "The character's own rig (UniRig, reweighted). The skeleton step fits every new mesh onto it by height and "
          "head, and worn tests pose pieces on it: it must be this character's body, never another character's."),
    Field("rig_game", "character", ("armour", "cut"), "glb",
          "The game rig: rig_fit with neutral-bone vertices rehomed (*_nb.glb). Slots go on it; retarget's target."),
    Field("roles", "character", ALL, "json", "Bone roles of the rig (anun_roles.py): which bone is which."),
    Field("clips_blend", "character", ALL, "blend",
          "player_clips.py output: the rig with the idle / move / attack actions every pack is skinned to."),
    Field("greedy_dirs", "character", ("armour", "cut"), "json", "Camera directions for the cut views."),
    Field("views", "character", (), "number", "How many of the greedy directions the cut renders (32)."),
    Field("clips_from", "character", ("body",), "text", "Mesh pack whose clips.json a body export copies."),
    Field("roster", "character", ("body",), "dict",
          "The hero entry in PlayerSelectionDict.json: display_name, painting, player_info_dir, roster_stats, "
          "base_stats, evasion_loadout."),
    Field("clips", "character", (), "dict",
          "player_clips.py's picks: idle, move, attack (retargeted clip names), attack_frames ([[from, to], ...])."),
    Field("retarget", "character", (), "dict", "retarget_bvh.py's quirks: bind_match, arm_elev_cap, digitigrade."),
    # --- outfit ----------------------------------------------------------------------------------------------
    Field("character", "outfit", ALL, "text", "The character folder this outfit belongs to."),
    Field("kind", "outfit", ALL, "choice", "body: a new body; armour: drawn over the body; cut: cut from a mesh.",
          KINDS),
    Field("pack", "outfit", ALL, "text", "Mesh pack name in Graphics/Meshes/ (<character>_<outfit>)."),
    Field("concept", "outfit", ("body", "armour"), "image", "The image the front drawing starts from."),
    Field("source_mesh", "outfit", ("cut",), "glb", "The painted mesh a cut outfit is cut from."),
    Field("paint_look", "outfit", ("body", "armour"), "json", "Paint look (repaint/looks/*.json)."),
    Field("front", "outfit", ("body", "armour"), "text", "Front drawing prompt."),
    Field("back", "outfit", ("body", "armour"), "text", "Back drawing prompt."),
    Field("side", "outfit", (), "text", "Side view prompt."),
    Field("quarter", "outfit", (), "text", "3/4 view prompt."),
    Field("side_config", "outfit", (), "json", "Image model config for the side views."),
    Field("mirror_right", "outfit", (), "bool", "Right-hand views mirrored from the left (true)."),
    Field("front_check", "outfit", (), "choice", "cover: armour covers the outline; match: the body matches it.",
          ("cover", "match")),
    Field("margin", "outfit", (), "number", "Outline margin for the front check."),
    Field("display_joints", "outfit", (), "bool", "Show the joints on the outline sent with the front."),
    Field("retry_bigger", "outfit", (), "text", "The 'rb' redraw line (armour too tight)."),
    Field("trellis_models", "outfit", (), "list", "TRELLIS models to build (each needs its drawings).",
          TRELLIS_MODELS),
    Field("sam", "outfit", ("armour", "cut"), "dict", "SAM3 prompts: {prompts: file or table, prompt_to_part}."),
    Field("holopart", "outfit", (), "bool", "Run HoloPart on the cut (true)."),
    Field("worn_on", "outfit", (), "text", "Body outfit the worn test uses once painted (else rig_fit)."),
    Field("material", "outfit", (), "text", "Item base prefix for the pieces (plate -> plate_chest)."),
    Field("display_name", "outfit", (), "text", "Hero name in the roster (body)."),
    Field("start_equipment", "outfit", (), "dict", "What the hero starts with: {wear: [ids], pack: [ids]}."),
    Field("existing", "outfit", (), "dict", "Outputs made before the pipeline, for --backfill."),
)
BY_NAME = {f.name: f for f in FIELDS}
FILE_TYPES = ("image", "glb", "blend", "json")
_PY = {"text": str, "number": (int, float), "bool": bool, "list": list, "dict": dict}


def is_note(key: str) -> bool:
    return key.startswith("_") or key.endswith("_note")


def value_problem(key: str, v) -> str | None:
    """What is wrong with one value (unknown key, wrong type), else None."""
    f = BY_NAME.get(key)
    if f is None:
        return f"unknown field {key!r}"
    if f.type in FILE_TYPES and not isinstance(v, str):
        return f"{key} must be a path"
    if f.type == "choice" and v not in f.choices:
        return f"{key} must be one of {list(f.choices)}"
    if f.type in _PY and (not isinstance(v, _PY[f.type]) or (f.type == "number" and isinstance(v, bool))):
        return f"{key} must be a {f.type}"
    if f.type == "list" and f.choices and not set(v) <= set(f.choices):
        return f"{key}: each one of {list(f.choices)}"
    return None


def file_problems(data: dict, level: str) -> list[str]:
    """One file's own problems: unknown keys, wrong types; a character file holds only character fields."""
    out = []
    for key, v in data.items():
        if is_note(key):
            continue
        bad = value_problem(key, v)
        if bad:
            out.append(bad)
        elif level == "character" and BY_NAME[key].level != "character":
            out.append(f"{key} belongs in an outfit file")
    return out


def problems(o: dict, where: str = "") -> list[str]:
    """What is wrong with a merged character + outfit: missing fields its kind needs, unknown keys, wrong types."""
    kind = o.get("kind")
    if kind not in KINDS:
        return [f"{where}kind must be one of {list(KINDS)}, not {kind!r}"]
    out = [f"{where}no {f.name} ({f.level} file): {f.help}" for f in FIELDS if kind in f.kinds and f.name not in o]
    return out + [f"{where}{p}" for p in file_problems(o, "outfit")]
