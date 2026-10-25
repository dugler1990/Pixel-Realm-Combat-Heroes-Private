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


def test_find_added_sees_the_objects_not_the_rerendered_relit_room():
    from tools.painted_map_pipeline.interiors import locate

    rng = np.random.default_rng(3)
    inside = np.asarray(rasterize_polygon(SIZE, CHAMBER)) > 0
    yy, xx = np.mgrid[0:SIZE[1], 0:SIZE[0]]
    stone = np.where(((xx // 40) + (yy // 40)) % 2, 60.0, 78.0) + rng.normal(0, 4, inside.shape)
    base = np.repeat(stone[..., None], 3, axis=2)
    # Re-rendered: the same stone with fresh grain, the whole room 8% brighter.
    rerendered = base * 1.08 + 6 + rng.normal(0, 3, base.shape)
    to_image = lambda a: Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))   # noqa: E731
    decorated = _add_objects(to_image(rerendered))

    added = locate.find_added(to_image(base), decorated, inside, tile=150)

    assert len(added.blobs) == 2, [b.box for b in added.blobs]
    urn = added.labels[URN[1], URN[0]]
    statue = added.labels[(STATUE[1] + STATUE[3]) // 2, (STATUE[0] + STATUE[2]) // 2]
    assert urn and statue and urn != statue, "each object is its own blob, dark body included"
    assert added.mask.sum() < 3 * (np.pi * URN[2] ** 2 + 50 * 120), \
        "the brighter, re-grained stone round them is not taken for an object"


def test_pack_puts_every_patch_on_the_sheet_at_one_scale():
    from tools.sprite_assets.props import _iou
    from tools.painted_map_pipeline.interiors import kit as kit_mod

    sizes = [(300, 500), (120, 90), (400, 260), (60, 60), (220, 410)]
    scale, boxes = kit_mod.pack(sizes, (1024, 1024), gap=20, margin=30)

    assert 0 < scale <= kit_mod.MAX_UPSCALE
    for (w, h), box in zip(sizes, boxes):
        assert box[2] - box[0] == int(np.ceil(w * scale)) and box[3] - box[1] == int(np.ceil(h * scale))
        assert box[0] >= 30 and box[1] >= 30 and box[2] <= 1024 - 30 and box[3] <= 1024 - 30
    assert all(_iou(list(a), list(b)) == 0 for i, a in enumerate(boxes) for b in boxes[i + 1:])
    assert kit_mod._shelf(sizes, scale * 1.05, (1024, 1024), 20, 30) is None, "the largest that fits"


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


def test_a_copy_backend_sheet_is_the_packed_canvas_with_its_layout(tmp_path, monkeypatch):
    from tools.painted_map_pipeline.interiors import kit as kit_mod

    monkeypatch.setattr(kit_mod, "PROPS_ROOT", tmp_path / "Props")
    spec = _spec(tmp_path)
    work = tmp_path / "work"
    base, variant = _decorated(spec, work)

    sheet = kit_mod.draw_sheet(_plan(spec), dict(COPY, width=1024, height=1024), variant, base)

    assert np.array_equal(np.asarray(Image.open(sheet)),
                          np.asarray(Image.open(variant.folder / kit_mod.CANVAS))), \
        "the copy backend hands the canvas back: the patches are the sheet"
    layout = json.loads((variant.folder / kit_mod.LAYOUT).read_text(encoding="utf-8"))
    assert layout["size"] == [1024, 1024] and len(layout["slots"]) == 2
    corner = np.asarray(Image.open(sheet).convert("RGB"))[5, 5]
    assert tuple(corner) == kit_mod.KEY, "drawn on the key colour"
    urn_slot = next(s for s in layout["slots"]
                    if s["room_box"][0] <= URN[0] <= s["room_box"][2]
                    and s["room_box"][1] <= URN[1] <= s["room_box"][3])
    rx0, ry0, rx1, ry1 = urn_slot["room_box"]
    sx0, sy0, sx1, sy1 = urn_slot["sheet_box"]
    assert abs((sx1 - sx0) / (rx1 - rx0) - layout["scale"]) < 0.02, "one scale, room to sheet"

    assert "patches" not in kit_mod.sheet_state(variant).status(), \
        "a --dry-run sheet is never taken for a real one"
    assert kit_mod.sheet_state(variant, dry_run=True).usable
    Image.new("RGB", SIZE, (0, 0, 0)).save(variant.composited)
    assert "redrawn" in kit_mod.sheet_state(variant, dry_run=True).stale


def test_the_sheet_gate_draws_on_arrival_and_k_goes_on_without_a_sheet(tmp_path, monkeypatch):
    from tools.painted_map_pipeline.interiors import kit as kit_mod

    monkeypatch.setattr(kit_mod, "PROPS_ROOT", tmp_path / "Props")
    monkeypatch.setattr(kit_mod, "SHEET_SIZE", (1024, 1024))
    monkeypatch.setattr(cli_mod, "_show", lambda path: None)
    monkeypatch.setattr(cli_mod, "_config", lambda args: dict(COPY))
    spec = _spec(tmp_path)
    work = tmp_path / "work"
    _decorated(spec, work, 1)
    _base, second = _decorated(spec, work, 2)
    found = decor_mod.variants(work, decor_mod.write_base(spec, work)[1], dry_run=True)
    replies = iter(["k 2", ""])
    monkeypatch.setattr(cli_mod, "_ask", lambda question, default="": next(replies))
    args = SimpleNamespace(variants=2, redraw=False, dry_run=True)

    states = cli_mod._sheet_gate(_plan(spec), spec, work, args, found)

    assert [(s.tag, s.drawn, s.kit) for s in states] == [("v01", True, False), ("v02", False, True)]
    assert (decor_mod.decor_dir(work) / kit_mod.STRIP).exists()


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


def test_extract_logs_each_cut_with_the_patch_it_came_from(tmp_path, monkeypatch):
    from tools.painted_map_pipeline.interiors import extract as extract_mod
    from tools.painted_map_pipeline.interiors import kit as kit_mod

    spec, work, base, state = _sheeted(tmp_path, monkeypatch)
    catalog = extract_mod.load_catalog(spec)

    record = extract_mod.extract_variant(spec, state, catalog)

    layout = json.loads((state.variant.folder / kit_mod.LAYOUT).read_text(encoding="utf-8"))
    assert sorted(p["blob"] for p in record["props"]) == sorted(s["blob"] for s in layout["slots"])
    assert catalog["sheets"][0]["from"] == "test_tomb/v01"
    assert extract_mod.is_current(state)
    for prop in catalog["props"]:
        cut = np.asarray(Image.open(extract_mod.set_dir(spec) / prop["file"]))
        assert cut.shape[2] == 4 and cut[..., 3].max() == 255
        assert prop["image_box"][2] - prop["image_box"][0] == cut.shape[1]

    # Redrawn: the variant's new sheet is cut, and the old one's props are struck.
    Image.open(state.sheet).transpose(Image.FLIP_LEFT_RIGHT).save(state.sheet)
    extract_mod.extract_variant(spec, kit_mod.sheet_state(state.variant, dry_run=True), catalog)
    first = [p for p in catalog["props"] if p["sheet"] == "s01"]
    assert first and not any(p["keep"] for p in first)


def test_tags_fill_unnamed_props_only(tmp_path, monkeypatch):
    from tools.painted_map_pipeline.interiors import extract as extract_mod

    spec, work, base, state = _sheeted(tmp_path, monkeypatch)
    catalog = extract_mod.load_catalog(spec)
    record = extract_mod.extract_variant(spec, state, catalog)
    named, other = catalog["props"][0], catalog["props"][1]
    named["name"] = "my urn"
    asked = []

    def ask(sheet, ids, subject):
        asked.append(ids)
        reply = ('Here you go:\n[{"id": "%s", "name": "Gold Statue", "category": "statue", '
                 '"mount": "floor"}, {"id": "%s", "name": "x", "category": "spaceship", '
                 '"mount": "ceiling"}]' % (other["id"], named["id"]))
        return extract_mod.parse_tags(reply)

    assert extract_mod.tag_variant(spec, catalog, record["sheet"], ask=ask) == 1
    assert asked == [[other["id"]]], "a prop someone named is not asked about"
    assert (other["name"], other["category"], other["mount"]) == ("gold statue", "statue", "floor")
    assert named["name"] == "my urn"
    assert extract_mod.parse_tags('[{"id": "a", "category": "spaceship", "mount": "x"}]')["a"] \
        == {"name": "", "category": "other", "mount": "floor"}


def test_locate_puts_each_prop_back_where_it_stood(tmp_path, monkeypatch):
    from tools.painted_map_pipeline.interiors import extract as extract_mod
    from tools.painted_map_pipeline.interiors import locate

    spec, work, base, state = _sheeted(tmp_path, monkeypatch)
    catalog = extract_mod.load_catalog(spec)
    extract_mod.extract_variant(spec, state, catalog)

    placed, unfilled = locate.locate_variant(spec, _plan(spec), state, catalog, base)

    assert unfilled == [] and len(placed) == 2 and {p.how for p in placed} == {"patch"}
    for truth in (_urn_box(), _statue_box()):
        best = max(placed, key=lambda p: _iou(p.box, truth))
        # A copy-backend cut-out carries the scrap of floor its patch was cut with.
        assert _iou(best.box, truth) > 0.5
        fx, fy = best.feet
        assert abs(fx - (truth[0] + truth[2]) / 2) < 0.02 * SIZE[0]
        assert abs(fy - truth[3]) < 0.02 * SIZE[1]
    recreated = np.asarray(Image.open(state.variant.folder / locate.RECREATED).convert("RGB")).astype(int)
    decorated = np.asarray(Image.open(state.variant.composited).convert("RGB")).astype(int)
    x0, y0, x1, y1 = _statue_box()
    assert np.abs(recreated[y0:y1, x0:x1] - decorated[y0:y1, x0:x1]).mean() < 12, \
        "the rebuilt room shows the statue where the decorated one has it"
    for name in (locate.COMPARE, locate.LOCATED, locate.PLACEMENTS):
        assert (state.variant.folder / name).exists()


def test_a_variant_without_a_sheet_is_matched_by_shape_against_the_set(tmp_path, monkeypatch):
    from tools.painted_map_pipeline.interiors import extract as extract_mod
    from tools.painted_map_pipeline.interiors import kit as kit_mod
    from tools.painted_map_pipeline.interiors import locate

    spec, work, base, first = _sheeted(tmp_path, monkeypatch)
    catalog = extract_mod.load_catalog(spec)
    extract_mod.extract_variant(spec, first, catalog)
    moved = (-60, 40)
    _base, second = _decorated(spec, work, 2, shift=moved)
    kit_mod.set_kit(second, True)

    placed, unfilled = locate.locate_variant(spec, _plan(spec), kit_mod.sheet_state(second),
                                             catalog, base)

    assert unfilled == [] and {p.how for p in placed} == {"shape"}
    for truth in (_urn_box(moved), _statue_box(moved)):
        fx, fy = max(placed, key=lambda p: _iou(p.box, truth)).feet
        assert abs(fx - (truth[0] + truth[2]) / 2) < 0.03 * SIZE[0]
        assert abs(fy - truth[3]) < 0.03 * SIZE[1]


REAL_WORK = Path("generated/building_interiors/great_pyramid")
REAL_SET = Path("Graphics/Props/pyramid")
PASTED = ["s01_00", "s01_09", "s01_13", "s01_15", "s01_26"]     # statue, brazier, sarcophagus,
DECOYS = ["s01_01", "s01_03", "s01_08", "s01_10", "s01_14",     # chest, pottery; then their
          "s01_16", "s01_17", "s01_18", "s01_29"]               # look-alikes


def test_shape_matching_finds_real_props_pasted_on_the_real_room():
    """The plan's check: five props from the set pasted onto great_pyramid's bare floor at
    known feet, with colour jitter, +-10% size, a blur and floor noise, one pair touching --
    then found against the five plus nine look-alikes. Each must rank in the top 3 for its
    blob, with its feet within 2% of the room, and the pair must come apart into two."""
    import pytest
    from PIL import ImageFilter

    from tools.painted_map_pipeline.interiors import emit as emit_mod
    from tools.painted_map_pipeline.interiors import locate

    needed = [REAL_WORK / "interior.json", REAL_WORK / "floor_raw.png",
              REAL_WORK / "decor" / "base.png", REAL_SET / "props.json"]
    if not all(path.exists() for path in needed):
        pytest.skip("needs great_pyramid's decorated work folder and the pyramid prop set")
    import cv2

    spec = InteriorSpec.load(REAL_WORK / "interior.json")
    plan = decor_mod.room_plan(spec, REAL_WORK)
    base = Image.open(REAL_WORK / "decor" / "base.png").convert("RGB")
    by_id = {p["id"]: p for p in json.loads((REAL_SET / "props.json").read_text(encoding="utf-8"))["props"]}
    rng = np.random.default_rng(7)
    tile = spec.tile
    inner = cv2.erode(plan.floor.astype(np.uint8), np.ones((int(tile * 1.4),) * 2, np.uint8)) > 0
    ys, xs = np.nonzero(inner)
    points = []
    for i in rng.permutation(len(xs)):
        point = (int(xs[i]), int(ys[i]))
        if all(abs(point[0] - q[0]) + abs(point[1] - q[1]) > 3 * tile for q in points):
            points.append(point)
        if len(points) == 4:
            break

    room, truths = base.copy(), []
    for index, pid in enumerate(PASTED):
        sprite = Image.open(REAL_SET / by_id[pid]["file"]).convert("RGBA")
        height = tile * 1.3 * rng.uniform(0.9, 1.1)
        width = height * sprite.width / sprite.height
        if width > 2.2 * tile:
            width, height = 2.2 * tile, 2.2 * tile * sprite.height / sprite.width
        sprite = sprite.resize((round(width), round(height)), Image.LANCZOS)
        rgba = np.asarray(sprite).astype(np.float32)
        rgba[..., :3] *= rng.uniform(0.92, 1.08, 3)
        sprite = Image.fromarray(np.clip(rgba, 0, 255).astype(np.uint8))
        if index < 4:
            fx, fy = points[index]
        else:                                         # touching the chest, on its right
            fx, fy = truths[3][1][2] + sprite.width / 2 - 4, truths[3][1][3]
        box = (fx - sprite.width / 2, fy - sprite.height, fx + sprite.width / 2, fy)
        room.paste(sprite, (round(box[0]), round(box[1])), sprite)
        truths.append((pid, box))
    room = np.asarray(room.filter(ImageFilter.GaussianBlur(0.8))).astype(np.float32)
    decorated = Image.fromarray(np.clip(room + rng.normal(0, 3, room.shape), 0, 255).astype(np.uint8))

    added = locate.find_added(base, decorated, emit_mod.chamber_mask_from_plan(plan), tile)
    scene = locate.Scene(decorated, added, tile, floor=plan.floor)
    candidates = [locate.Prop(by_id[pid], REAL_SET) for pid in PASTED + DECOYS]
    placed, unfilled = locate.place_props(scene, [], candidates)

    assert unfilled == [] and len(placed) == len(PASTED), [p.prop for p in placed]
    for pid, box in truths:
        fx, fy = (box[0] + box[2]) / 2, box[3]
        blob = int(scene.labels[int((fy - 0.3 * (box[3] - box[1])) * scene.scale),
                                int(fx * scene.scale)])
        top = [prop.id for _score, prop, _box in locate.rank_fits(scene, scene.labels == blob,
                                                                    candidates)[:3]]
        assert pid in top, f"{pid} not in the top 3 for its blob: {top}"
        near = min(placed, key=lambda p: abs(p.feet[0] - fx) + abs(p.feet[1] - fy))
        assert abs(near.feet[0] - fx) < 0.02 * spec.size[0]
        assert abs(near.feet[1] - fy) < 0.02 * spec.size[1]
    pair = {p.prop for p in placed if p.blob == placed[[p.prop for p in placed].index("s01_26")].blob}
    assert pair == {"s01_15", "s01_26"}, "the touching pair comes apart into its two props"


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


def test_write_props_puts_one_tile_object_per_placement_and_is_idempotent(tmp_path, monkeypatch):
    pytmx = __import__("pytest").importorskip("pytmx")
    from tools.sprite_assets import props as props_mod
    from tools.painted_map_pipeline.interiors import emit as emit_mod
    from tools.painted_map_pipeline.interiors import extract as extract_mod
    from tools.painted_map_pipeline.interiors import locate

    spec, work, base, state = _sheeted(tmp_path, monkeypatch)
    spec.origin = (100, 200)
    catalog = extract_mod.load_catalog(spec)
    extract_mod.extract_variant(spec, state, catalog)
    locate.locate_variant(spec, _plan(spec), state, catalog, base)
    tsx = props_mod.write_tileset(extract_mod.set_dir(spec), catalog)
    placements = locate.read_placements(state.variant)["placements"]
    map_path = _level(tmp_path)
    variants = [("v01", placements), ("v02", placements[:1])]

    first = emit_mod.write_props(spec, variants, map_path, tsx, catalog["next_tile_id"])
    again = emit_mod.write_props(spec, variants, map_path, tsx, catalog["next_tile_id"])

    assert first["firstgid"] == again["firstgid"] == 5, "after the 4 tiles already there"
    xml = map_path.read_text(encoding="utf-8")
    assert xml.count('name="test_tomb_prop_') == len(placements) + 1, "a re-run replaces"
    assert xml.count("test_tomb_props.tsx") == 1, "the tileset is referenced once"
    tmx = pytmx.TiledMap(str(map_path))
    objects = list(tmx.get_layer_by_name("Props"))
    placed = placements[0]
    obj = next(o for o in objects if o.name == "test_tomb_prop_v01_00")
    assert obj.properties["building"] == "test_tomb" and obj.properties["variant"] == "v01"
    assert obj.properties["prop_id"] == placed["prop"], "the gid points at the right cut-out"
    assert abs(obj.x - (100 + placed["x"] - placed["w"] / 2)) <= 1
    assert abs(obj.y + obj.height - (200 + placed["y"])) <= 1, "anchored at its feet"


def test_the_whole_walk_on_the_copy_backend_with_back_and_resume(tmp_path, monkeypatch):
    from tools.painted_map_pipeline.interiors import kit as kit_mod

    monkeypatch.setattr(kit_mod, "PROPS_ROOT", tmp_path / "Props")
    monkeypatch.setattr(kit_mod, "SHEET_SIZE", (1024, 1024))
    monkeypatch.setattr(cli_mod, "WORK_ROOT", tmp_path / "work_root")
    monkeypatch.setattr(cli_mod, "_show", lambda path: None)
    spec = _spec(tmp_path)
    spec.map_path = str(_level(tmp_path))
    work = cli_mod._work(spec.building)
    work.mkdir(parents=True)
    spec.save(work / "interior.json")
    _decorated(spec, work, 1)
    monkeypatch.setattr(cli_mod, "_room_plan", lambda spec, work, args: _plan(spec))
    config = tmp_path / "copy.json"
    config.write_text('{"provider": "copy"}', encoding="utf-8")
    argv = ["furnish", "--building", spec.building, "--config", str(config), "--dry-run",
            "--variants", "1"]

    # decorate, sheet, extract, locate, then back from place to locate, and stop there.
    replies = iter(["", "", "", "", "b", "", "q"])
    monkeypatch.setattr(cli_mod, "_ask", lambda question, default="": next(replies))
    assert cli_mod.main(argv) == 2
    assert next(replies, None) is None, "every gate was reached and answered"
    folder = decor_mod.variant_folder(work, 1)
    drawn = (folder / kit_mod.SHEET).stat().st_mtime_ns
    assert "test_tomb_prop_v01_00" in (Path(spec.map_path).parent.parent / "level.plan" /
                                        "map.tmx").read_text(encoding="utf-8")
    assert "_prop_" not in Path(spec.map_path).read_text(encoding="utf-8"), \
        "a dry run never writes the shipped map"

    # Resumed: every gate reuses what is on disk, and [a] is refused under --dry-run.
    replies = iter(["", "", "", "", "a", "q"])
    monkeypatch.setattr(cli_mod, "_ask", lambda question, default="": next(replies))
    assert cli_mod.main(argv) == 2
    assert (folder / kit_mod.SHEET).stat().st_mtime_ns == drawn, "the sheet was not redrawn"
    assert "_prop_" not in Path(spec.map_path).read_text(encoding="utf-8")
    status = cli_mod.furnish_status(spec.building)
    assert "decorated 1" in status and "stale" in status, \
        "outside a dry run, the dry run's sheets count as stale"
