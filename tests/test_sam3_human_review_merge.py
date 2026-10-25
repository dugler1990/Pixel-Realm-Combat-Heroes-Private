from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from tools.painted_map_pipeline.collision.sam3.class_filters import ClassFilterConfig
from tools.painted_map_pipeline.collision.sam3.merge_polygon_obstacles import (
    merge_polygon_obstacles,
)


def _run_merge(tmp_path: Path, *, reviewed: bool) -> tuple[dict, ET.Element]:
    map_path = tmp_path / ("reviewed.tmx" if reviewed else "legacy.tmx")
    map_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<map nextlayerid="1" nextobjectid="1"></map>',
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "chunks": [
                    {
                        "chunk_id": "chunk",
                        "world_rect": [10, 20, 100, 100],
                        "image_size": [100, 100],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    root = tmp_path / ("reviewed" if reviewed else "legacy")
    chunk = root / "chunk"
    chunk.mkdir(parents=True)
    document = {
        "image_size": [100, 100],
        "polygons": [
            {
                "class": "rock",
                "prompt": "stone",
                "confidence": 0.1,
                "review_id": "P01-G01-C01000-0001",
                "points": [[0, 0], [10, 0], [10, 10], [0, 10]],
            }
        ],
    }
    if reviewed:
        document["review"] = {"accepted": True, "revision": 3}
    (chunk / "polygons.json").write_text(json.dumps(document), encoding="utf-8")

    summary = merge_polygon_obstacles(
        map_path=map_path,
        manifest_path=manifest,
        sam3_root=root,
        class_filter=ClassFilterConfig.from_mapping(
            {"min_confidence": {"rock": 0.9}, "max_area": 50}
        ),
        speck_cull=True,
        containment_cull=True,
    )
    return summary, ET.parse(map_path).getroot()


def test_human_accepted_chunk_bypasses_automatic_culls_and_carries_id(tmp_path: Path):
    summary, root = _run_merge(tmp_path, reviewed=True)
    assert summary["inserted_objects"] == 1
    assert summary["human_reviewed_chunks"] == ["chunk"]
    properties = {
        prop.attrib["name"]: prop.attrib["value"]
        for prop in root.find("objectgroup").find("object").find("properties")
    }
    assert properties["review_id"] == "P01-G01-C01000-0001"
    assert properties["sam3_confidence"] == "0.1"
    assert properties["collision_mode"] == "solid"


def test_full_map_accepted_file_is_merged_in_world_space(tmp_path: Path):
    map_path = tmp_path / "map.tmx"
    map_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><map nextlayerid="1" nextobjectid="1"></map>',
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"chunks": []}), encoding="utf-8")
    root = tmp_path / "sam3"
    (root / "full_map").mkdir(parents=True)
    (root / "full_map" / "polygons.json").write_text(
        json.dumps(
            {
                "image_size": [100, 100],
                "review": {"accepted": True, "revision": 1},
                "polygons": [
                    {
                        "class": "pyramid",
                        "prompt": "pyramid",
                        "confidence": 0.9,
                        "review_id": "P01-L-0001",
                        "points": [[5, 5], [25, 5], [25, 25], [5, 25]],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    summary = merge_polygon_obstacles(
        map_path=map_path,
        manifest_path=manifest,
        sam3_root=root,
        speck_cull=True,
        containment_cull=True,
    )
    assert summary["inserted_objects"] == 1
    assert summary["human_reviewed_chunks"] == ["full_map"]


def test_legacy_chunk_keeps_existing_automatic_culls(tmp_path: Path):
    summary, root = _run_merge(tmp_path, reviewed=False)
    assert summary["inserted_objects"] == 0
    assert summary["human_reviewed_count"] == 0
    assert len(root.find("objectgroup").findall("object")) == 0
