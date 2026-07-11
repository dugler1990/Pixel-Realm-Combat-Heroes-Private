"""Tests for SAM3 polygon tagging."""

import pytest

from tools.painted_map_pipeline.collision.sam3.merge_polygon_obstacles import _polygon_to_tmx_object
from tools.painted_map_pipeline.collision.sam3.polygon_filters import (
    normalize_sam3_class,
    tag_polygon,
)


def test_tree_gets_canopy():
    tagged = tag_polygon({"class": "tree", "points": [[0, 0], [1, 0], [1, 1]]})
    assert tagged["sam3_class"] == "tree"
    assert tagged["collision_mode"] == "canopy"


def test_rock_gets_solid():
    tagged = tag_polygon({"class": "Rock", "points": [[0, 0], [1, 0], [1, 1]]})
    assert tagged["sam3_class"] == "rock"
    assert tagged["collision_mode"] == "solid"


def test_cliff_gets_solid():
    tagged = tag_polygon({"class": "cliff", "points": [[0, 0], [1, 0], [1, 1]]})
    assert tagged["collision_mode"] == "solid"


def test_tag_uses_prompt_when_class_missing():
    tagged = tag_polygon({"prompt": "tree", "confidence": 0.5, "points": [[0, 0], [1, 0], [1, 1]]})
    assert tagged["sam3_class"] == "tree"
    assert tagged["collision_mode"] == "canopy"


def test_missing_class_raises():
    with pytest.raises(ValueError, match="missing class"):
        normalize_sam3_class(None)
    with pytest.raises(ValueError, match="missing class"):
        normalize_sam3_class("  ")


def test_polygon_to_tmx_object_always_writes_tags():
    obj = _polygon_to_tmx_object(
        [[0, 0], [10, 0], [10, 10]],
        world_x=100,
        world_y=200,
        object_id=1,
        chunk_id="chunk_00_00",
        sam3_class="tree",
        sam3_confidence=0.5,
        collision_mode="canopy",
    )
    props = {p.get("name"): p.get("value") for p in obj.find("properties")}
    assert props["sam3_class"] == "tree"
    assert props["collision_mode"] == "canopy"
    assert props["chunk_id"] == "chunk_00_00"
    assert props["sam3_confidence"] == "0.5"
