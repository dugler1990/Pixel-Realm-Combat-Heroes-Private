"""Furnishing an accepted interior: decorate, sprite sheet, extract, locate, place.

Step 1, decorate, here. The building is made in the test -- no map, no API: a 1024x768
canvas, the smallest the edit path accepts, with its exterior and accepted interior written
to tmp. The copy backend stands in for the model, so a draw is the room handed back as it was:
enough to prove a variant registers with the room, and is tracked against its line in
styles.txt and the room it was drawn on.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from tools.painted_map_pipeline.interiors import cli as cli_mod
from tools.painted_map_pipeline.interiors import decorate as decor_mod
from tools.painted_map_pipeline.interiors.plan import Plan, geometry_masks
from tools.painted_map_pipeline.interiors.spec import InteriorSpec
from tools.painted_map_pipeline.world_levels.masks import rasterize_polygon

SIZE = (1024, 768)
SILHOUETTE = ((512.0, 40.0), (980.0, 384.0), (512.0, 728.0), (44.0, 384.0))
CHAMBER = ((512.0, 140.0), (850.0, 384.0), (512.0, 628.0), (174.0, 384.0))
COPY = {"provider": "copy"}


def _spec(tmp_path, intent="gilded tomb") -> InteriorSpec:
    roof = tmp_path / "roof.png"
    Image.new("RGBA", SIZE, (150, 120, 80, 255)).save(roof)
    inside = np.asarray(rasterize_polygon(SIZE, SILHOUETTE)) > 0
    asset = np.zeros((SIZE[1], SIZE[0], 4), np.uint8)
    asset[inside] = (90, 80, 70, 255)
    interior = tmp_path / "interior.png"
    Image.fromarray(asset, "RGBA").save(interior)
    return InteriorSpec(building="test_tomb", map_path=str(tmp_path / "map.tmx"), origin=(0, 0),
                        size=SIZE, silhouette=SILHOUETTE, chamber=CHAMBER, doors=(),
                        roof_image=str(roof), interior_image=str(interior), intent=intent)


def _plan(spec) -> Plan:
    silhouette, chamber, _editable = geometry_masks(spec)
    empty = np.zeros_like(chamber)
    classes = {"floor": chamber, "wall": silhouette & ~chamber, "outer": empty, "solid": empty}
    return Plan(spec=spec, floor=chamber, chamber=chamber, silhouette=silhouette,
                classes=classes, report={"passed": True, "failed": [], "checks": []})


def _fake_draw(work, number, additions, base_sha1, kept=True):
    """A variant as a draw leaves it, without making the draw."""
    folder = decor_mod.variant_folder(work, number)
    folder.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", SIZE, (200, 180, 40)).save(folder / decor_mod.COMPOSITED)
    (folder / decor_mod.DRIFT).write_text("0.0800\n", encoding="utf-8")
    (folder / decor_mod.META).write_text(json.dumps({
        "additions": additions, "base_sha1": base_sha1, "kept": kept,
        "composited": decor_mod.COMPOSITED}), encoding="utf-8")


# ---------------------------------------------------------------- the styles file

def test_a_new_styles_file_starts_from_the_intent_and_is_never_rewritten(tmp_path):
    spec = _spec(tmp_path)
    path = decor_mod.ensure_styles(spec, tmp_path, 6)
    lines = decor_mod.read_styles(path)
    assert len(lines) == 6
    assert all(line.endswith("; gilded tomb") for line in lines)
    assert lines[4] == lines[0], "more variants than starter lines: they cycle"

    path.write_text("# mine\n\nonly this one\n", encoding="utf-8")
    decor_mod.ensure_styles(spec, tmp_path, 6)
    assert decor_mod.read_styles(path) == ["only this one"]


# ---------------------------------------------------------------- variants

def test_a_draw_on_the_copy_backend_registers_with_the_room(tmp_path):
    spec = _spec(tmp_path)
    work = tmp_path / "work"
    decor_mod.ensure_styles(spec, work, 2)
    base, sha1 = decor_mod.write_base(spec, work)
    found = decor_mod.variants(work, sha1)
    assert [v.status() for v in found] == ["not drawn", "not drawn"]

    out = decor_mod.draw_variant(_plan(spec), COPY, found[0], base, sha1)

    drawn = np.asarray(Image.open(out).convert("RGB"))
    room = np.asarray(Image.open(base).convert("RGB"))
    assert drawn.shape == room.shape
    outside = ~geometry_masks(spec)[0]
    assert np.array_equal(drawn[outside], room[outside]), "the exterior is written back exactly"
    first, second = decor_mod.variants(work, sha1, dry_run=True)
    assert first.usable and first.drift is not None and first.drift < 0.01
    assert not second.drawn
    assert "dry-run" in decor_mod.variants(work, sha1)[0].stale, \
        "outside a dry run, the copy backend's undecorated room never passes for a decoration"


def test_editing_its_line_or_rerendering_the_room_makes_a_variant_stale(tmp_path):
    spec = _spec(tmp_path)
    work = tmp_path / "work"
    styles = decor_mod.ensure_styles(spec, work, 1)
    line = decor_mod.read_styles(styles)[0]
    _base, sha1 = decor_mod.write_base(spec, work)
    _fake_draw(work, 1, line, sha1)
    assert decor_mod.variants(work, sha1)[0].usable

    styles.write_text(f"{line} and a golden barge\n", encoding="utf-8")
    assert "edited" in decor_mod.variants(work, sha1)[0].stale
    styles.write_text(f"{line}\n", encoding="utf-8")
    assert decor_mod.variants(work, sha1)[0].usable

    asset = np.asarray(Image.open(spec.interior_image)).copy()
    asset[asset[..., 3] > 0] = (20, 200, 20, 255)
    Image.fromarray(asset, "RGBA").save(spec.interior_image)
    _base, rerendered = decor_mod.write_base(spec, work)
    assert rerendered != sha1
    assert "re-rendered" in decor_mod.variants(work, rerendered)[0].stale


def test_a_drop_keeps_the_draw_and_a_folder_without_a_line_is_not_kept(tmp_path):
    spec = _spec(tmp_path)
    work = tmp_path / "work"
    styles = decor_mod.ensure_styles(spec, work, 2)
    lines = decor_mod.read_styles(styles)
    _base, sha1 = decor_mod.write_base(spec, work)
    _fake_draw(work, 1, lines[0], sha1)
    _fake_draw(work, 3, "a line since deleted", sha1)

    first = decor_mod.variants(work, sha1)[0]
    decor_mod.set_kept(first, False)
    first, second, third = decor_mod.variants(work, sha1)
    assert first.status() == "dropped" and first.drawn, "dropping never throws a draw away"
    decor_mod.set_kept(first, True)
    assert decor_mod.variants(work, sha1)[0].usable
    assert not second.drawn and second.kept
    assert not third.kept and "no line" in third.stale


def test_the_strip_has_a_tile_for_the_room_and_each_variant(tmp_path):
    spec = _spec(tmp_path)
    work = tmp_path / "work"
    decor_mod.ensure_styles(spec, work, 5)
    base, sha1 = decor_mod.write_base(spec, work)
    lines = decor_mod.read_styles(decor_mod.decor_dir(work) / decor_mod.STYLES)
    _fake_draw(work, 1, lines[0], sha1)
    _fake_draw(work, 2, lines[1], sha1, kept=False)

    strip = decor_mod.decor_strip(base, decor_mod.variants(work, sha1),
                                  work / "strip.png", width=520, per_row=4)

    # The room and five variants, four to a row: two rows of 520x390 tiles under a label.
    assert Image.open(strip).size == (4 * 520 + 3 * 10, 2 * (390 + 30) + 10)


# ---------------------------------------------------------------- the gate

def test_the_gate_draws_on_arrival_then_goes_on_with_what_was_kept(tmp_path, monkeypatch):
    spec = _spec(tmp_path)
    work = tmp_path / "work"
    monkeypatch.setattr(cli_mod, "_show", lambda path: None)
    monkeypatch.setattr(cli_mod, "_config", lambda args: dict(COPY))
    replies = iter(["x 2", ""])
    monkeypatch.setattr(cli_mod, "_ask", lambda question, default="": next(replies))
    args = SimpleNamespace(variants=2, redraw=False, dry_run=True)

    kept = cli_mod._decorate_gate(_plan(spec), spec, work, args)

    assert [v.tag for v in kept] == ["v01"]
    second = decor_mod.variants(work, decor_mod.write_base(spec, work)[1], dry_run=True)[1]
    assert second.drawn and not second.kept, "dropped at the gate, its draw still on disk"
    assert (decor_mod.decor_dir(work) / decor_mod.STRIP).exists()


def test_a_redraw_moves_the_old_draw_aside(tmp_path, monkeypatch):
    spec = _spec(tmp_path)
    work = tmp_path / "work"
    monkeypatch.setattr(cli_mod, "_show", lambda path: None)
    monkeypatch.setattr(cli_mod, "_config", lambda args: dict(COPY))
    replies = iter(["r 1 fewer urns", "q"])
    monkeypatch.setattr(cli_mod, "_ask", lambda question, default="": next(replies))
    args = SimpleNamespace(variants=1, redraw=False, dry_run=True)

    assert cli_mod._decorate_gate(_plan(spec), spec, work, args) is None

    folder = decor_mod.variant_folder(work, 1)
    assert "fewer urns" in (folder / decor_mod.PROMPT).read_text(encoding="utf-8")
    set_aside = list((folder / "old").glob("*/" + decor_mod.COMPOSITED))
    assert len(set_aside) == 1, "the first draw is kept in old/, not overwritten"


# ---------------------------------------------------------------- step 2: what was added

GOLD = (210, 170, 70)
URN = (400, 380, 45)                  # centre and radius: a gold urn
STATUE = (600, 300, 650, 420)         # a dark statue with a gold trim


def _add_objects(image: Image.Image, shift=(0, 0)) -> Image.Image:
    from PIL import ImageDraw

    out = image.convert("RGB").copy()
    draw = ImageDraw.Draw(out)
    x, y, r = URN[0] + shift[0], URN[1] + shift[1], URN[2]
    draw.ellipse((x - r, y - r, x + r, y + r), fill=GOLD)
    draw.rectangle((STATUE[0] + shift[0], STATUE[1] + shift[1], STATUE[2] + shift[0],
                    STATUE[3] + shift[1]), fill=(25, 22, 28), outline=GOLD, width=4)
    return out


def _urn_box(shift=(0, 0)):
    return (URN[0] - URN[2] + shift[0], URN[1] - URN[2] + shift[1],
            URN[0] + URN[2] + shift[0], URN[1] + URN[2] + shift[1])


def _statue_box(shift=(0, 0)):
    return (STATUE[0] + shift[0], STATUE[1] + shift[1], STATUE[2] + shift[0], STATUE[3] + shift[1])


def _decorated(spec, work, number=1, shift=(0, 0)):
    """A variant as step 1 leaves it, its room with an urn and a statue added."""
    styles = decor_mod.ensure_styles(spec, work, 2)
    line = decor_mod.read_styles(styles)[number - 1]
    base, sha1 = decor_mod.write_base(spec, work)
    folder = decor_mod.variant_folder(work, number)
    folder.mkdir(parents=True, exist_ok=True)
    _add_objects(Image.open(base), shift).save(folder / decor_mod.COMPOSITED)
    (folder / decor_mod.META).write_text(json.dumps({
        "additions": line, "base_sha1": sha1, "kept": True,
        "composited": decor_mod.COMPOSITED, "provider": "openai"}), encoding="utf-8")
    return base, decor_mod.variants(work, sha1)[number - 1]


# ---------------------------------------------------------------- steps 3-4: cut, put back

def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / union if union else 0.0


def _sheeted(tmp_path, monkeypatch, number=1, shift=(0, 0)):
    """(spec, work, base, state): a variant decorated and its copy-backend sheet drawn."""
    from tools.painted_map_pipeline.interiors import kit as kit_mod

    monkeypatch.setattr(kit_mod, "PROPS_ROOT", tmp_path / "Props")
    spec = _spec(tmp_path)
    work = tmp_path / "work"
    base, variant = _decorated(spec, work, number, shift)
    kit_mod.draw_sheet(_plan(spec), dict(COPY, width=1024, height=1024), variant, base)
    return spec, work, base, kit_mod.sheet_state(variant, dry_run=True)


REAL_WORK = Path("generated/building_interiors/great_pyramid")
REAL_SET = Path("Graphics/Props/pyramid")
PASTED = ["s01_00", "s01_09", "s01_13", "s01_15", "s01_26"]     # statue, brazier, sarcophagus,
DECOYS = ["s01_01", "s01_03", "s01_08", "s01_10", "s01_14",     # chest, pottery; then their
          "s01_16", "s01_17", "s01_18", "s01_29"]               # look-alikes


# ---------------------------------------------------------------- step 5: into the map

def _level(tmp_path):
    """A small level folder: a map with one external tileset of 4 tiles."""
    level = tmp_path / "level"
    level.mkdir()
    Image.new("RGB", (64, 64), (60, 90, 60)).save(level / "ground.png")
    (level / "ground.tsx").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<tileset version="1.10" name="ground" tilewidth="32" tileheight="32" tilecount="4" '
        'columns="2">\n <image source="ground.png" width="64" height="64"/>\n</tileset>\n',
        encoding="utf-8")
    (level / "map.tmx").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<map version="1.10" orientation="orthogonal" renderorder="right-down" width="40" '
        'height="40" tilewidth="32" tileheight="32" infinite="0" nextlayerid="2" '
        'nextobjectid="2">\n'
        ' <tileset firstgid="1" source="ground.tsx"/>\n'
        ' <objectgroup id="1" name="Buildings">\n'
        '  <object id="1" name="test_tomb" x="100" y="200">\n'
        '   <polygon points="0,0 1024,0 1024,768"/>\n'
        '  </object>\n'
        ' </objectgroup>\n'
        '</map>\n', encoding="utf-8")
    return level / "map.tmx"


