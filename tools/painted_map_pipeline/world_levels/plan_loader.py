from __future__ import annotations

import csv
from pathlib import Path

from .geometry import validate_simple_polygon
from .models import Connection, LevelSpec, Point


def _parse_polygon(value: str, field: str, level_id: str) -> tuple[Point, ...]:
    points: list[Point] = []
    for encoded in value.split("|"):
        try:
            x_text, y_text = encoded.split(":", 1)
            points.append((int(x_text), int(y_text)))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"level {level_id}: invalid {field} point {encoded!r}") from exc
    if len(points) < 3:
        raise ValueError(f"level {level_id}: {field} requires at least three points")
    if len(set(points)) != len(points):
        raise ValueError(f"level {level_id}: {field} contains duplicate vertices")
    return tuple(points)


def _parse_connections(value: str) -> tuple[Connection, ...]:
    connections: list[Connection] = []
    for encoded in filter(None, (part.strip() for part in value.split(";"))):
        level_id, separator, kind = encoded.partition(":")
        connections.append(Connection(level_id.zfill(2), kind if separator else "land"))
    return tuple(connections)


def _validate_spec(spec: LevelSpec, world_size: tuple[int, int] | None) -> None:
    if spec.crop_width <= 0 or spec.crop_height <= 0:
        raise ValueError(f"level {spec.level_id}: crop dimensions must be positive")
    validate_simple_polygon(spec.core_polygon, "core polygon", spec.level_id)
    validate_simple_polygon(spec.generation_polygon, "generation polygon", spec.level_id)
    left, top, right, bottom = spec.crop_box
    for field, polygon in (
        ("core polygon", spec.core_polygon),
        ("generation polygon", spec.generation_polygon),
    ):
        for x, y in polygon:
            if not (left <= x <= right and top <= y <= bottom):
                raise ValueError(f"level {spec.level_id}: {field} point {(x, y)} lies outside its crop")
            if world_size and not (0 <= x < world_size[0] and 0 <= y < world_size[1]):
                raise ValueError(f"level {spec.level_id}: {field} point {(x, y)} lies outside the world image")
    if world_size and (left < 0 or top < 0 or right > world_size[0] or bottom > world_size[1]):
        raise ValueError(f"level {spec.level_id}: crop lies outside the world image")


def load_level_plan(path: str | Path, world_size: tuple[int, int] | None = None) -> dict[str, LevelSpec]:
    plan_path = Path(path)
    levels: dict[str, LevelSpec] = {}
    with plan_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {
            "id",
            "name",
            "region",
            "crop_x_px",
            "crop_y_px",
            "crop_width_px",
            "crop_height_px",
            "overlap_buffer_px",
            "core_polygon_points_px",
            "generation_polygon_points_px",
            "connections",
        }
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"level plan is missing columns: {', '.join(sorted(missing))}")
        for row in reader:
            level_id = str(row["id"]).strip().zfill(2)
            if level_id in levels:
                raise ValueError(f"duplicate level id: {level_id}")
            spec = LevelSpec(
                level_id=level_id,
                name=str(row["name"]).strip(),
                region=str(row["region"]).strip(),
                crop_x=int(row["crop_x_px"]),
                crop_y=int(row["crop_y_px"]),
                crop_width=int(row["crop_width_px"]),
                crop_height=int(row["crop_height_px"]),
                overlap_buffer=int(row["overlap_buffer_px"]),
                core_polygon=_parse_polygon(row["core_polygon_points_px"], "core polygon", level_id),
                generation_polygon=_parse_polygon(
                    row["generation_polygon_points_px"], "generation polygon", level_id
                ),
                connections=_parse_connections(row["connections"]),
            )
            _validate_spec(spec, world_size)
            levels[level_id] = spec

    for spec in levels.values():
        for connection in spec.connections:
            neighbor = levels.get(connection.level_id)
            if neighbor is None:
                raise ValueError(f"level {spec.level_id}: unknown connection {connection.level_id}")
            reverse = neighbor.connection_to(spec.level_id)
            if reverse is None:
                raise ValueError(f"connection {spec.level_id}-{neighbor.level_id} is not symmetric")
            if reverse.kind != connection.kind:
                raise ValueError(f"connection {spec.level_id}-{neighbor.level_id} has mismatched kinds")
    return levels
