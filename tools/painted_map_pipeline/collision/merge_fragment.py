"""Optional: merge a collision_layer.fragment.xml into an existing map.tmx."""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


def merge_fragment(map_path: Path, fragment_path: Path, *, replace: bool = True) -> None:
    map_root = ET.parse(map_path).getroot()
    fragment_root = ET.parse(fragment_path).getroot()
    if fragment_root.tag != "objectgroup":
        raise ValueError(f"Expected objectgroup fragment, got {fragment_root.tag}")

    layer_name = fragment_root.attrib.get("name", "PaintedCollision")
    if replace:
        for node in list(map_root):
            if node.tag == "objectgroup" and node.attrib.get("name") == layer_name:
                map_root.remove(node)

    max_layer_id = 0
    max_object_id = 0
    for node in map_root:
        if node.attrib.get("id"):
            try:
                max_layer_id = max(max_layer_id, int(node.attrib["id"]))
            except ValueError:
                pass
        if node.tag == "objectgroup":
            for obj in node.findall("object"):
                if obj.attrib.get("id"):
                    try:
                        max_object_id = max(max_object_id, int(obj.attrib["id"]))
                    except ValueError:
                        pass

    new_layer = ET.fromstring(ET.tostring(fragment_root, encoding="unicode"))
    new_layer.attrib["id"] = str(max_layer_id + 1)
    for obj in new_layer.findall("object"):
        max_object_id += 1
        obj.attrib["id"] = str(max_object_id)

    map_root.append(new_layer)
    next_layer = int(map_root.attrib.get("nextlayerid", str(max_layer_id + 2)))
    map_root.attrib["nextlayerid"] = str(max(next_layer, max_layer_id + 2))
    map_root.attrib["nextobjectid"] = str(max_object_id + 1)

    tsx_name = "collision.tsx"
    fragment_dir = fragment_path.parent
    target_tsx = map_path.parent / tsx_name
    source_tsx = fragment_dir / tsx_name
    if source_tsx.exists() and source_tsx.resolve() != target_tsx.resolve():
        target_tsx.write_bytes(source_tsx.read_bytes())

    tileset_exists = any(
        node.tag == "tileset" and node.attrib.get("source", "").endswith(tsx_name)
        for node in map_root
    )
    if not tileset_exists and target_tsx.exists():
        max_gid = 0
        for layer in map_root.findall("layer"):
            data = layer.find("data")
            if data is not None and data.text:
                for part in data.text.replace("\n", ",").split(","):
                    part = part.strip()
                    if part:
                        max_gid = max(max_gid, int(part) & 0x1FFFFFFF)
        for og in map_root.findall("objectgroup"):
            for obj in og.findall("object"):
                if obj.attrib.get("gid"):
                    max_gid = max(max_gid, int(obj.attrib["gid"]) & 0x1FFFFFFF)
        new_firstgid = max_gid + 1
        ET.SubElement(map_root, "tileset", {"firstgid": str(new_firstgid), "source": tsx_name})
        for obj in new_layer.findall("object"):
            if obj.attrib.get("gid"):
                obj.attrib["gid"] = str(new_firstgid)

    ET.indent(map_root, space=" ")
    ET.ElementTree(map_root).write(map_path, encoding="utf-8", xml_declaration=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge collision fragment into map.tmx (optional, manual step).")
    parser.add_argument("--map", required=True)
    parser.add_argument("--fragment", required=True)
    parser.add_argument("--no-replace", action="store_true")
    args = parser.parse_args(argv)
    merge_fragment(Path(args.map), Path(args.fragment), replace=not args.no_replace)
    print(f"Merged {args.fragment} into {args.map}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
