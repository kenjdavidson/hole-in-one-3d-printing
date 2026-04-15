"""LiDAR + SVG topology pipeline for the Hole-In-One generator."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .plaque_builder import carve_plaque
from .plaque_request import PlaqueRequest


def _iter_elevation_values(node):
    if isinstance(node, (int, float)):
        yield float(node)
        return

    if isinstance(node, dict):
        for key in ("elevation", "z", "height"):
            value = node.get(key)
            if isinstance(value, (int, float)):
                yield float(value)
        for child in node.values():
            yield from _iter_elevation_values(child)
        return

    if isinstance(node, list):
        for child in node:
            yield from _iter_elevation_values(child)


def _load_elevations(lidar_path: str) -> list[float]:
    path = Path(lidar_path)
    if not path.is_file():
        raise ValueError(f"LiDAR file not found: {lidar_path}")
    suffix = path.suffix.lower()

    if suffix == ".csv":
        values: list[float] = []
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            for row in reader:
                for item in row:
                    try:
                        values.append(float(item))
                    except ValueError:
                        continue
        return values

    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return list(_iter_elevation_values(data))


def build_topology_from_params(params: dict, lidar_path: str) -> None:
    """Build a plaque using SVG geometry and LiDAR-derived height span."""
    valid_fields = set(PlaqueRequest.__dataclass_fields__)
    filtered = {k: v for k, v in params.items() if k in valid_fields}
    req = PlaqueRequest(**filtered)

    elevations = _load_elevations(lidar_path)
    if not elevations:
        raise ValueError("No numeric LiDAR elevation values were found")

    lidar_span = max(elevations) - min(elevations)
    lidar_height_scale = float(params.get("lidar_height_scale", 0.01))
    topology_base_thickness = float(params.get("topology_base_thickness", req.plaque_thick))

    req.use_auto_thickness = False
    # Keep whichever baseline is thicker between incoming plaque settings and
    # topology-specific minimum, then add LiDAR-derived topology height.
    req.plaque_thick = max(req.plaque_thick, topology_base_thickness) + (lidar_span * lidar_height_scale)

    print(
        "[topology_builder] "
        f"LiDAR span={lidar_span:.4f}, scale={lidar_height_scale:.4f}, plaque_thick={req.plaque_thick:.4f}"
    )
    carve_plaque(req)


def build_topology(props) -> None:
    """Blender-addon entry point for topology builds."""
    params = {}
    for field_name in PlaqueRequest.__dataclass_fields__:
        if hasattr(props, field_name):
            params[field_name] = getattr(props, field_name)
    params["lidar_height_scale"] = props.lidar_height_scale
    params["topology_base_thickness"] = props.topology_base_thickness
    build_topology_from_params(params, props.lidar_file_path)
