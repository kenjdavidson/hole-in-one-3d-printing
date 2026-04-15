"""Topology-mode pipeline runner."""


def run(params: dict, lidar_path: str | None = None) -> None:
    """Execute the LiDAR-informed topology plaque pipeline."""
    if not lidar_path:
        raise ValueError("topology mode requires a LiDAR data file")

    from golf.topology_builder import build_topology_from_params  # noqa: PLC0415

    print(f"[worker:topology] Running topology pipeline with lidar={lidar_path}")
    build_topology_from_params(params, lidar_path)
