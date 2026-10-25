"""Prop sheets -> catalogued cut-outs -> Tiled tileset.

A synthetic black sheet stands in for the Leonardo ones: a statue with a dark body, a
torch whose flame floats a few pixels above it, a hanging ring with the sheet's black
showing through, plus the clutter the finder must skip -- a heading and a divider line.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from tools.sprite_assets.cut_sheet import find_objects
from tools.sprite_assets.props import (
    extract_sheet,
    load_catalog,
    save_catalog,
    write_tileset,
)
from tools.sprite_assets.remove_bg import matte_object

GOLD = (200, 150, 60)
DARK_BODY = (20, 18, 24)  # darker than the lit threshold, but not the sheet's black
FLAME = (255, 220, 120)

STATUE = (40, 60, 72, 160)
CREVICE = (54, 128, 56, 130)  # a pure-black nick in the statue's body
TORCH_STICK = (150, 100, 156, 160)
FLAME_BLOB = (144, 70, 162, 96)  # 4 px above the stick
RING = (260, 90, 340, 170)
HEADING_Y = 20
DIVIDER_X = 380


def _sheet() -> Image.Image:
    img = Image.new("RGB", (420, 320), (0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle(STATUE, fill=DARK_BODY, outline=GOLD, width=4)
    d.rectangle(CREVICE, fill=(0, 0, 0))
    d.rectangle(TORCH_STICK, fill=GOLD)
    d.ellipse(FLAME_BLOB, fill=FLAME)
    d.ellipse(RING, outline=GOLD, width=5)
    for i in range(7):  # a heading: letters 3 px apart
        x = 30 + i * 13
        d.rectangle((x, HEADING_Y, x + 9, HEADING_Y + 12), fill=GOLD)
    d.rectangle((DIVIDER_X, 20, DIVIDER_X + 1, 300), fill=(60, 50, 40))
    return img


def _containing(found, box):
    return [f for f in found
            if f.cell.box[0] <= box[0] and f.cell.box[1] <= box[1]
            and f.cell.box[2] >= box[2] and f.cell.box[3] >= box[3]]


def test_finds_each_object_and_skips_heading_and_divider():
    found = find_objects(_sheet())
    assert len(found) == 3
    assert len(_containing(found, STATUE)) == 1
    assert len(_containing(found, RING)) == 1
    torch = _containing(found, (FLAME_BLOB[0], FLAME_BLOB[1], TORCH_STICK[2], TORCH_STICK[3]))
    assert len(torch) == 1, "flame and stick should be one object"
    for f in found:
        assert f.cell.box[1] > HEADING_Y + 12, f"{f.cell.name} took in the heading"
        assert f.cell.box[2] < DIVIDER_X, f"{f.cell.name} took in the divider"


def test_matte_keeps_a_dark_body_solid_and_the_sheet_black_open():
    sheet = _sheet()
    found = find_objects(sheet)

    def alpha_at(box, x, y):
        f = _containing(found, box)[0]
        cut = matte_object(sheet.crop(f.cell.box), f.mask, black_thr=f.black_thr)
        return np.asarray(cut)[y - f.cell.box[1], x - f.cell.box[0], 3]

    assert alpha_at(STATUE, 56, 110) == 255
    assert alpha_at(STATUE, 55, 129) == 255, "a small black crevice is art, not a hole"
    assert alpha_at(RING, 300, 130) == 0
    assert alpha_at(STATUE, 38, 110) == 0  # just beside it: the sheet


MAGENTA = (255, 0, 255)
BLACK_STATUE = (40, 60, 90, 170)      # near-black, no gold trim: on a black sheet it vanishes
PALE_URN = (150, 90, 230, 170)        # nearly white
URN_GAP = (188, 128, 191, 131)        # a 4 px fleck of the sheet inside the urn
GOLD_RING = (260, 90, 340, 170)


def _coloured_sheet(background) -> Image.Image:
    """A furnishing sheet: one flat colour, a black statue with a soft (blended) outline, a
    pale urn with a fleck of the sheet inside it, and a ring the sheet shows through."""
    img = Image.new("RGB", (420, 320), background)
    d = ImageDraw.Draw(img)
    blend = tuple((a + b) // 2 for a, b in zip(DARK_BODY, background))
    d.rectangle(BLACK_STATUE, fill=blend)
    d.rectangle((BLACK_STATUE[0] + 1, BLACK_STATUE[1] + 1, BLACK_STATUE[2] - 1,
                 BLACK_STATUE[3] - 1), fill=DARK_BODY)
    d.ellipse(PALE_URN, fill=(240, 236, 224))
    d.rectangle(URN_GAP, fill=background)
    d.ellipse(GOLD_RING, outline=GOLD, width=5)
    return img


@pytest.mark.parametrize("background", [MAGENTA, (255, 255, 255)], ids=["magenta", "white"])
def test_a_coloured_sheet_cuts_dark_and_pale_objects_whole_with_no_rim(background):
    sheet = _coloured_sheet(background)
    found = find_objects(sheet)
    assert len(found) == 3 and all(f.background == background for f in found)

    def cut_of(box):
        f = _containing(found, box)[0]
        cut = np.asarray(matte_object(sheet.crop(f.cell.box), f.mask, black_thr=f.black_thr,
                                      background=f.background))
        return f, cut

    statue_found, statue = cut_of(BLACK_STATUE)
    x0, y0 = statue_found.cell.box[:2]
    assert statue[110 - y0, 65 - x0, 3] == 255, "a black body on magenta is solid"
    ring_found, ring = cut_of(GOLD_RING)
    assert ring[130 - ring_found.cell.box[1], 300 - ring_found.cell.box[0], 3] == 0, \
        "the sheet showing through the ring is open"
    urn_found, urn = cut_of(PALE_URN)
    assert urn[129 - urn_found.cell.box[1], 189 - urn_found.cell.box[0], 3] == 0, \
        "a fleck of the sheet's colour inside an object is a hole, however small"
    for _f, cut in (cut_of(BLACK_STATUE), cut_of(PALE_URN), cut_of(GOLD_RING)):
        shown = cut[..., 3] > 0
        sheet_coloured = np.abs(cut[..., :3].astype(int) - np.asarray(background)).max(axis=2) < 20
        assert not (sheet_coloured & shown).any(), "the sheet's colour is taken out of the outline"


def _extract(tmp_path: Path) -> tuple[Path, dict]:
    sheet = tmp_path / "leonardo_download.png"
    _sheet().save(sheet)
    out = tmp_path / "pyramid"
    out.mkdir()
    catalog = load_catalog(out, "pyramid")
    extract_sheet(catalog, sheet, out)
    save_catalog(out, catalog)
    return out, catalog


def test_catalog_logs_every_cut_and_copies_the_sheet(tmp_path):
    out, catalog = _extract(tmp_path)
    assert [s["source_name"] for s in catalog["sheets"]] == ["leonardo_download.png"]
    assert (out / catalog["sheets"][0]["file"]).exists()
    props = catalog["props"]
    assert [p["tile_id"] for p in props] == [0, 1, 2]
    for p in props:
        img = Image.open(out / p["file"])
        assert list(img.size) == p["size"] and img.mode == "RGBA"
        assert p["mount"] == "floor" and p["keep"] is True
    assert (out / "_contact_s01.png").exists()
    assert (out / "_debug" / "s01_overlay.png").exists()


def test_rerun_keeps_hand_edits_and_tile_ids(tmp_path):
    out, catalog = _extract(tmp_path)
    first = catalog["props"][0]
    first.update(name="anubis statue", category="statue", mount="wall")
    save_catalog(out, catalog)

    again = load_catalog(out, "pyramid")
    extract_sheet(again, tmp_path / "leonardo_download.png", out)
    assert len(again["sheets"]) == 1, "same sheet must not be registered twice"
    assert len(again["props"]) == 3
    kept = next(p for p in again["props"] if p["id"] == first["id"])
    assert (kept["tile_id"], kept["name"], kept["category"], kept["mount"]) == (
        first["tile_id"], "anubis statue", "statue", "wall")


def test_tileset_skips_struck_props_without_shifting_the_rest(tmp_path):
    out, catalog = _extract(tmp_path)
    catalog["props"][1]["keep"] = False
    catalog["props"][2].update(name="hanging ring", category="brazier")
    tsx = write_tileset(out, catalog)

    root = ET.parse(tsx).getroot()
    tiles = {t.get("id"): t for t in root.iter("tile")}
    assert set(tiles) == {"0", "2"}
    assert root.get("tilecount") == "2" and root.get("columns") == "0"
    ring = tiles["2"]
    assert ring.get("type") == "brazier"
    props = {p.get("name"): p.get("value") for p in ring.iter("property")}
    assert props == {"prop_id": catalog["props"][2]["id"], "name": "hanging ring", "mount": "floor"}
    assert ring.find("image").get("source") == catalog["props"][2]["file"]


def test_pytmx_puts_tile_properties_on_placed_props(tmp_path):
    pytmx = pytest.importorskip("pytmx")
    out, catalog = _extract(tmp_path)
    catalog["props"][0]["mount"] = "wall"
    write_tileset(out, catalog)
    w, h = catalog["props"][0]["size"]
    (out / "room.tmx").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<map version="1.10" orientation="orthogonal" renderorder="right-down" width="10" '
        'height="10" tilewidth="32" tileheight="32" infinite="0" nextlayerid="2" nextobjectid="2">\n'
        ' <tileset firstgid="1" source="pyramid_props.tsx"/>\n'
        ' <objectgroup id="1" name="Props">\n'
        f'  <object id="1" gid="1" x="100" y="200" width="{w}" height="{h}"/>\n'
        ' </objectgroup>\n'
        '</map>\n',
        encoding="utf-8",
    )
    tmx = pytmx.TiledMap(str(out / "room.tmx"))
    placed = tmx.get_layer_by_name("Props")[0]
    assert placed.properties["mount"] == "wall"
    assert placed.properties["prop_id"] == catalog["props"][0]["id"]
    assert placed.y == 200 - h, "pytmx gives the top edge"
