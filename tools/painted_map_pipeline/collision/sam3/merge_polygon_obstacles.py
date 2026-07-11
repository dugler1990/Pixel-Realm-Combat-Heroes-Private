"""Merge SAM3 chunk polygons into map TMX Objects objectgroup."""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ..emit import load_manifest
from .class_filters import ClassFilterConfig, filter_polygons_by_class
from .containment_cull import ContainmentCullConfig, filter_contained_polygons
from .isolation_cull import SpeckCullConfig, filter_specks_by_size_openness
from .polygon_filters import tag_polygon

LEGACY_OBJECT_LAYER_NAMES = ("ObstaclePolygons", "Objects")


def _next_layer_id(root: ET.Element) -> int:
    max_id = 0
    for node in root:
        raw = node.attrib.get("id")
        if raw:
            try:
                max_id = max(max_id, int(raw))
            except ValueError:
                pass
    return max_id + 1


def _next_object_id(root: ET.Element) -> int:
    max_id = 0
    for objectgroup in root.findall("objectgroup"):
        for obj in objectgroup.findall("object"):
            raw = obj.attrib.get("id")
            if raw:
                try:
                    max_id = max(max_id, int(raw))
                except ValueError:
                    pass
    raw = root.attrib.get("nextobjectid")
    try:
        max_id = max(max_id, int(raw) - 1)
    except (TypeError, ValueError):
        pass
    return max_id + 1


def _remove_layer(root: ET.Element, layer_name: str) -> None:
    for node in list(root):
        if node.tag == "objectgroup" and node.attrib.get("name") == layer_name:
            root.remove(node)


def _remove_object_layers(root: ET.Element, layer_names: tuple[str, ...]) -> None:
    for name in layer_names:
        _remove_layer(root, name)


def _add_property(parent: ET.Element, name: str, value: Any, *, prop_type: str | None = None) -> None:
    attrs: dict[str, str] = {"name": name, "value": str(value)}
    if prop_type:
        attrs["type"] = prop_type
    ET.SubElement(parent, "property", attrs)


def _polygon_to_tmx_object(
    points: list[list[float]],
    *,
    world_x: float,
    world_y: float,
    object_id: int,
    chunk_id: str,
    sam3_class: str,
    sam3_confidence: float | None = None,
    collision_mode: str,
) -> ET.Element | None:
    if len(points) < 3:
        return None
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    min_x = min(xs)
    min_y = min(ys)
    rel_points = " ".join(f"{float(x - min_x):g},{float(y - min_y):g}" for x, y in zip(xs, ys))
    obj = ET.Element(
        "object",
        {
            "id": str(object_id),
            "x": str(int(round(world_x + min_x))),
            "y": str(int(round(world_y + min_y))),
            "width": "0",
            "height": "0",
        },
    )
    ET.SubElement(obj, "polygon", {"points": rel_points})
    props = ET.SubElement(obj, "properties")
    _add_property(props, "chunk_id", chunk_id)
    _add_property(props, "sam3_class", sam3_class)
    if sam3_confidence is not None:
        _add_property(props, "sam3_confidence", sam3_confidence, prop_type="float")
    _add_property(props, "collision_mode", collision_mode)
    return obj


def _chunk_world_origin(chunk: dict[str, Any]) -> tuple[float, float]:
    world_rect = chunk.get("world_rect")
    if not world_rect or len(world_rect) < 2:
        chunk_id = chunk.get("chunk_id") or Path(chunk.get("painted_image", "")).stem
        raise ValueError(f"chunk {chunk_id!r} missing world_rect top-left")
    return float(world_rect[0]), float(world_rect[1])


def merge_polygon_obstacles(
    *,
    map_path: Path,
    manifest_path: Path,
    sam3_root: Path,
    layer_name: str = "Objects",
    require_all: bool = False,
    speck_cull: bool = True,
    cull_config: SpeckCullConfig | None = None,
    class_filter: ClassFilterConfig | None = None,
    containment_cull: bool = True,
    containment_config: ContainmentCullConfig | None = None,
) -> dict[str, Any]:
    map_path = Path(map_path).resolve()
    manifest = load_manifest(Path(manifest_path).resolve())
    sam3_root = Path(sam3_root).resolve()

    root = ET.parse(map_path).getroot()
    _remove_object_layers(root, tuple(dict.fromkeys((layer_name, *LEGACY_OBJECT_LAYER_NAMES))))

    layer = ET.Element("objectgroup", {"id": str(_next_layer_id(root)), "name": layer_name})
    object_id = _next_object_id(root)
    inserted = 0
    input_polygons = 0
    skipped_invalid_geometry = 0
    missing: list[str] = []
    cull_totals: dict[str, int] = {
        "input": 0,
        "kept": 0,
        "dropped": 0,
        "blobs_total": 0,
        "blobs_dropped": 0,
    }
    chunk_cull_stats: dict[str, dict[str, Any]] = {}
    class_filter_totals: dict[str, int] = {}
    containment_totals: dict[str, int] = {"input": 0, "kept": 0, "dropped": 0}

    for chunk in manifest.get("chunks", []):
        chunk_id = chunk.get("chunk_id") or Path(chunk["painted_image"]).stem
        poly_path = sam3_root / chunk_id / "polygons.json"
        if not poly_path.exists():
            missing.append(chunk_id)
            continue

        data = json.loads(poly_path.read_text(encoding="utf-8"))
        world_x, world_y = _chunk_world_origin(chunk)
        raw_polygons = data.get("polygons") or []
        tagged = [tag_polygon(poly) for poly in raw_polygons]
        input_polygons += len(tagged)

        image_size = tuple(data.get("image_size") or chunk.get("image_size") or (5056, 3392))

        if class_filter is not None and class_filter.is_active() and tagged:
            tagged, cf_stats = filter_polygons_by_class(tagged, class_filter)
            for cls, n in cf_stats["dropped_by_class"].items():
                class_filter_totals[cls] = class_filter_totals.get(cls, 0) + n

        survivors = tagged
        if speck_cull and tagged:
            survivors, chunk_stats = filter_specks_by_size_openness(
                tagged,
                image_size=image_size,
                config=cull_config,
            )
            chunk_cull_stats[chunk_id] = chunk_stats
            for key in cull_totals:
                cull_totals[key] += int(chunk_stats.get(key, 0))

        if containment_cull and survivors:
            survivors, ct_stats = filter_contained_polygons(
                survivors,
                image_size=image_size,
                config=containment_config,
            )
            for key in containment_totals:
                containment_totals[key] += int(ct_stats.get(key, 0))

        for poly in survivors:
            tagged_poly = poly
            obj = _polygon_to_tmx_object(
                poly.get("points") or [],
                world_x=world_x,
                world_y=world_y,
                object_id=object_id,
                chunk_id=chunk_id,
                sam3_class=tagged_poly["sam3_class"],
                sam3_confidence=poly.get("confidence"),
                collision_mode=tagged_poly["collision_mode"],
            )
            if obj is None:
                skipped_invalid_geometry += 1
                continue
            layer.append(obj)
            object_id += 1
            inserted += 1

    if require_all and missing:
        raise FileNotFoundError(
            f"Missing SAM3 polygons for {len(missing)} chunks (e.g. {missing[:5]})"
        )

    insert_at = len(root)
    for idx, node in enumerate(list(root)):
        if node.tag == "objectgroup" and node.attrib.get("name", "").lower() == "paintedground":
            insert_at = idx + 1
            break
    root.insert(insert_at, layer)

    root.attrib["nextobjectid"] = str(object_id)
    root.attrib["nextlayerid"] = str(max(_next_layer_id(root), int(root.attrib.get("nextlayerid", 1))))

    ET.indent(root, space=" ")
    ET.ElementTree(root).write(map_path, encoding="utf-8", xml_declaration=True)

    return {
        "map": str(map_path),
        "layer_name": layer_name,
        "input_polygons": input_polygons,
        "inserted_objects": inserted,
        "skipped_invalid_geometry": skipped_invalid_geometry,
        "missing_chunks": missing,
        "missing_count": len(missing),
        "speck_cull_enabled": speck_cull,
        "speck_cull_totals": cull_totals,
        "speck_cull_by_chunk": chunk_cull_stats,
        "class_filter_dropped": class_filter_totals,
        "containment_cull_enabled": containment_cull,
        "containment_cull_totals": containment_totals,
    }


def main(argv: list[str] | None = None) -> int:
    repo = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description="Merge SAM3 polygons into map TMX.")
    parser.add_argument("--map", default="levels/Frostreach/expanse/map.tmx")
    parser.add_argument(
        "--manifest",
        default="levels/Frostreach/expanse/export/painted_4k_leonardo/insert_manifest.json",
    )
    parser.add_argument(
        "--sam3-root",
        default="levels/Frostreach/expanse/export/sam3_obstacle",
    )
    parser.add_argument("--layer-name", default="Objects")
    parser.add_argument("--require-all", action="store_true")
    parser.add_argument(
        "--no-speck-cull",
        action="store_true",
        help="Disable the size x openness speck cull before merge",
    )
    parser.add_argument(
        "--cull-config",
        default=None,
        help="Optional JSON file with SpeckCullConfig overrides",
    )
    parser.add_argument(
        "--class-config",
        default=None,
        help='Optional JSON file with ClassFilterConfig, e.g. {"drop_classes": ["cliff"]}',
    )
    parser.add_argument(
        "--no-containment-cull",
        action="store_true",
        help="Disable dropping obstacles fully contained in a larger one",
    )
    parser.add_argument(
        "--containment-config",
        default=None,
        help="Optional JSON file with ContainmentCullConfig overrides",
    )
    args = parser.parse_args(argv)

    cull_config = None
    if args.cull_config:
        cull_config = SpeckCullConfig.from_mapping(
            json.loads(Path(args.cull_config).read_text(encoding="utf-8"))
        )

    class_filter = None
    if args.class_config:
        class_filter = ClassFilterConfig.from_mapping(
            json.loads(Path(args.class_config).read_text(encoding="utf-8"))
        )

    containment_config = None
    if args.containment_config:
        containment_config = ContainmentCullConfig.from_mapping(
            json.loads(Path(args.containment_config).read_text(encoding="utf-8"))
        )

    summary = merge_polygon_obstacles(
        map_path=(repo / args.map).resolve(),
        manifest_path=(repo / args.manifest).resolve(),
        sam3_root=(repo / args.sam3_root).resolve(),
        layer_name=args.layer_name,
        require_all=args.require_all,
        speck_cull=not args.no_speck_cull,
        cull_config=cull_config,
        class_filter=class_filter,
        containment_cull=not args.no_containment_cull,
        containment_config=containment_config,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
