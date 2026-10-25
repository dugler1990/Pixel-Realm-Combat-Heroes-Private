"""CLI for cutting / matting sprite sheets into frame folders.

Examples:
  python -m tools.sprite_assets.cli cut path/to/sheet.png --out tmp/cells --debug
  python -m tools.sprite_assets.cli matte tmp/cells --out tmp/matted
  python -m tools.sprite_assets.cli extract-meteor \\
      --bulk path/to/bulk.png --linger path/to/linger.png \\
      --out Graphics/Particles/Meteor
  python -m tools.sprite_assets.cli extract-meteor \\
      --bulk path/to/black_bg.png --bg black \\
      --out Graphics/Particles/Meteor
  python -m tools.sprite_assets.cli extract-props path/to/sheets/*.jpg \\
      --out Graphics/Props/pyramid
  python -m tools.sprite_assets.cli write-tileset Graphics/Props/pyramid
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

# Allow `python tools/sprite_assets/cli.py` from repo root.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.sprite_assets.cut_sheet import (  # noqa: E402
    cells_from_grid,
    cut_cells,
    detect_gutter_grid,
    save_debug_overlay,
)
from tools.sprite_assets.pack_sequence import pack_sequence, write_contact_sheet  # noqa: E402
from tools.sprite_assets.props import (  # noqa: E402
    extract_sheet,
    load_catalog,
    refresh_contact_sheets,
    save_catalog,
    write_tileset,
)
from tools.sprite_assets.remove_bg import (  # noqa: E402
    matte_black_bg,
    matte_stone_floor,
    trim_transparent,
)


# Hand-tuned layouts for the first meteor sheets (1408x768 bulk, 1024x1024 linger).
METEOR_BULK_LAYOUT = {
    "row_names": ["targeting", "descent", "impact", "residual"],
    "cols_per_row": [5, 8, 8, 8],
    "row_spans": [(48, 172), (218, 368), (414, 562), (608, 750)],
    "col_spans": [
        (28, 176),
        (194, 344),
        (364, 516),
        (538, 690),
        (714, 866),
        (888, 1038),
        (1060, 1210),
        (1232, 1380),
    ],
    "inset": [2, 12, 2, 4],
}

# gpt-image black-bg sheet (1024x1024): 4 rows x 8 cols, title strip above.
METEOR_BULK_BLACK_LAYOUT = {
    "row_names": ["targeting", "descent", "impact", "residual"],
    "cols_per_row": [8, 8, 8, 8],
    "row_spans": [(138, 279), (336, 484), (538, 685), (782, 902)],
    "col_spans": [
        (18, 128),
        (131, 250),
        (259, 380),
        (384, 511),
        (518, 637),
        (646, 765),
        (772, 887),
        (896, 1013),
    ],
    "inset": [2, 4, 2, 4],
}

METEOR_LINGER_LAYOUT = {
    "row_names": ["residual_v"],
    "cols_per_row": [2, 2],
    "named_boxes": [
        ["residual_v_01", [70, 110, 470, 470]],
        ["residual_v_02", [570, 110, 970, 470]],
        ["residual_v_03", [70, 560, 470, 820]],
        ["residual_v_04", [570, 560, 970, 820]],
    ],
}


def _load_image(path: Path) -> Image.Image:
    return Image.open(path).convert("RGBA")


def _clear_pngs(dest: Path) -> None:
    if not dest.exists():
        return
    for old in dest.glob("*.png"):
        old.unlink()


def cmd_cut(args: argparse.Namespace) -> int:
    img = _load_image(args.sheet)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.layout:
        layout = json.loads(Path(args.layout).read_text(encoding="utf-8"))
        from tools.sprite_assets.cut_sheet import cells_from_boxes

        if "named_boxes" in layout:
            cells = cells_from_boxes((n, tuple(b)) for n, b in layout["named_boxes"])
        else:
            cells = cells_from_grid(
                [tuple(s) for s in layout["row_spans"]],
                [tuple(s) for s in layout["col_spans"]],
                row_names=layout.get("row_names"),
                cols_per_row=layout.get("cols_per_row"),
                inset=tuple(layout.get("inset", [4, 10, 4, 4])),
            )
    else:
        rows, cols = detect_gutter_grid(img)
        cells = cells_from_grid(rows, cols, inset=(4, 10, 4, 4))
        print(f"detected {len(rows)} rows x {len(cols)} cols -> {len(cells)} cells")

    if args.debug:
        save_debug_overlay(img, cells, out / "_debug_overlay.png")

    cropped = cut_cells(img, cells)
    for cell, crop in cropped:
        crop.save(out / f"{cell.name}.png")
    print(f"wrote {len(cropped)} cells -> {out}")
    return 0


def cmd_matte(args: argparse.Namespace) -> int:
    src = Path(args.src)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    paths = sorted(src.glob("*.png"))
    if not paths:
        print(f"no pngs in {src}", file=sys.stderr)
        return 1
    frames = []
    for path in paths:
        if path.name.startswith("_"):
            continue
        matted = matte_stone_floor(
            Image.open(path),
            dist_thr=args.dist_thr,
            soft=args.soft,
        )
        if args.trim:
            matted = trim_transparent(matted)
        dest = out / path.name
        matted.save(dest)
        frames.append(matted)
    write_contact_sheet(frames, out / "_contact.png", cols=min(8, max(1, len(frames))))
    print(f"matted {len(frames)} frames -> {out}")
    return 0


def _extract_with_layout(
    sheet: Path,
    layout: dict,
    out_root: Path,
    *,
    dist_thr: float,
    soft: float,
    trim: bool,
    bg: str = "stone",
) -> dict[str, list[Image.Image]]:
    from tools.sprite_assets.cut_sheet import cells_from_boxes

    img = _load_image(sheet)
    if "named_boxes" in layout:
        cells = cells_from_boxes((n, tuple(b)) for n, b in layout["named_boxes"])
    else:
        cells = cells_from_grid(
            [tuple(s) for s in layout["row_spans"]],
            [tuple(s) for s in layout["col_spans"]],
            row_names=layout.get("row_names"),
            cols_per_row=layout.get("cols_per_row"),
            inset=tuple(layout.get("inset", [4, 10, 4, 4])),
        )
    debug_dir = out_root / "_debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    save_debug_overlay(img, cells, debug_dir / f"{sheet.stem}_overlay.png")

    by_seq: dict[str, list[tuple[str, Image.Image]]] = {}
    for cell, crop in cut_cells(img, cells):
        if bg == "black":
            matted = matte_black_bg(crop, black_thr=max(8.0, dist_thr * 0.35), soft=soft + 6.0)
        else:
            matted = matte_stone_floor(crop, dist_thr=dist_thr, soft=soft)
        if trim:
            matted = trim_transparent(matted)
        seq = cell.name.rsplit("_", 1)[0]
        by_seq.setdefault(seq, []).append((cell.name, matted))

    result: dict[str, list[Image.Image]] = {}
    for seq, items in by_seq.items():
        items.sort(key=lambda t: t[0])
        dest = out_root / seq
        _clear_pngs(dest)
        pack_sequence(items, dest)
        imgs = [im for _, im in items]
        write_contact_sheet(imgs, out_root / f"_contact_{seq}.png", cols=min(8, len(imgs)))
        result[seq] = imgs
        print(f"  {seq}: {len(imgs)} frames -> {dest}")
    return result


def cmd_extract_meteor(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "layouts").mkdir(exist_ok=True)

    bulk_layout = METEOR_BULK_BLACK_LAYOUT if args.bg == "black" else METEOR_BULK_LAYOUT
    (out / "layouts" / "bulk.json").write_text(json.dumps(bulk_layout, indent=2), encoding="utf-8")
    (out / "layouts" / "linger.json").write_text(json.dumps(METEOR_LINGER_LAYOUT, indent=2), encoding="utf-8")

    by_seq: dict[str, list[Image.Image]] = {}
    if args.bulk:
        print(f"bulk sheet: {args.bulk} (bg={args.bg})")
        by_seq.update(
            _extract_with_layout(
                Path(args.bulk),
                bulk_layout,
                out,
                dist_thr=args.dist_thr,
                soft=args.soft,
                trim=not args.no_trim,
                bg=args.bg,
            )
        )
    if args.linger:
        print(f"linger sheet: {args.linger}")
        by_seq.update(
            _extract_with_layout(
                Path(args.linger),
                METEOR_LINGER_LAYOUT,
                out,
                dist_thr=args.dist_thr,
                soft=args.soft,
                trim=not args.no_trim,
                bg="stone",
            )
        )
    elif args.bg == "black" and "residual" in by_seq and len(by_seq["residual"]) >= 4:
        # No separate linger sheet: loop the cooling scorch frames.
        items = [(f"residual_v_{i + 1:02d}", im.copy()) for i, im in enumerate(by_seq["residual"][-4:])]
        dest = out / "residual_v"
        _clear_pngs(dest)
        pack_sequence(items, dest)
        write_contact_sheet([im for _, im in items], out / "_contact_residual_v.png", cols=4)
        print(f"  residual_v: {len(items)} frames (from residual tail) -> {dest}")
    print(f"done -> {out}")
    return 0


def _expand_sheets(raw: list[str]) -> list[Path]:
    """Sheet args as files, folders (every image in it) or wildcards — cmd.exe won't expand them."""
    import glob

    sheets: list[Path] = []
    for arg in raw:
        path = Path(arg)
        if path.is_dir():
            sheets.extend(sorted(p for p in path.iterdir()
                                 if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")))
        elif any(ch in arg for ch in "*?["):
            sheets.extend(Path(p) for p in sorted(glob.glob(arg)))
        else:
            sheets.append(path)
    return sheets


def cmd_extract_props(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sheets = _expand_sheets(args.sheets)
    if not sheets:
        print("no sheets matched", file=sys.stderr)
        return 1
    catalog = load_catalog(out, args.set or out.name)
    for sheet in sheets:
        props = extract_sheet(catalog, sheet, out)
        print(f"  {sheet.name[:70]}: {len(props)} objects")
    save_catalog(out, catalog)
    tsx = write_tileset(out, catalog)
    print(f"done -> {out}: {len(catalog['props'])} props in props.json, tileset {tsx.name}")
    return 0


def cmd_write_tileset(args: argparse.Namespace) -> int:
    out = Path(args.dir)
    catalog = load_catalog(out, out.name)
    if not catalog["props"]:
        print(f"no props.json in {out}", file=sys.stderr)
        return 1
    refresh_contact_sheets(out, catalog)
    tsx = write_tileset(out, catalog)
    kept = sum(1 for p in catalog["props"] if p.get("keep", True))
    print(f"wrote {tsx} ({kept} of {len(catalog['props'])} props kept)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Sprite sheet extract / matte tools")
    sub = p.add_subparsers(dest="cmd", required=True)

    cut = sub.add_parser("cut", help="Crop cells from a sheet")
    cut.add_argument("sheet")
    cut.add_argument("--out", required=True)
    cut.add_argument("--layout", help="JSON layout (row_spans/col_spans or named_boxes)")
    cut.add_argument("--debug", action="store_true")
    cut.set_defaults(func=cmd_cut)

    matte = sub.add_parser("matte", help="Matte stone floor from cropped cells")
    matte.add_argument("src")
    matte.add_argument("--out", required=True)
    matte.add_argument("--dist-thr", type=float, default=28.0)
    matte.add_argument("--soft", type=float, default=14.0)
    matte.add_argument("--trim", action="store_true")
    matte.set_defaults(func=cmd_matte)

    ex = sub.add_parser("extract-meteor", help="Cut+matte the meteor sheets into sequences")
    ex.add_argument("--bulk", help="Full meteor phase sheet")
    ex.add_argument("--linger", help="Residual fire variants sheet")
    ex.add_argument("--out", required=True)
    ex.add_argument("--bg", choices=("stone", "black"), default="stone",
                    help="stone = Gemini floor matte; black = solid black bg sheet")
    ex.add_argument("--dist-thr", type=float, default=34.0)
    ex.add_argument("--soft", type=float, default=12.0)
    ex.add_argument("--no-trim", action="store_true")
    ex.set_defaults(func=cmd_extract_meteor)

    props = sub.add_parser("extract-props",
                           help="Cut every object off black prop sheets into a catalogued set")
    props.add_argument("sheets", nargs="+", help="sheet files, folders or wildcards")
    props.add_argument("--out", required=True, help="prop set folder, e.g. Graphics/Props/pyramid")
    props.add_argument("--set", help="set name (default: the --out folder name)")
    props.set_defaults(func=cmd_extract_props)

    tsx = sub.add_parser("write-tileset",
                         help="Rebuild the Tiled tileset and previews after editing props.json")
    tsx.add_argument("dir", help="prop set folder")
    tsx.set_defaults(func=cmd_write_tileset)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
