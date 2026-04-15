# 3D Printing Blender Scripts

A collection of Blender Python addons and helper scripts used to build 3D-printing workflows.

## What this project provides

- **Animation utilities** (`scripts/animation/`)
- **Geometry utilities** (`scripts/geometry/`)
- **Material utilities** (`scripts/materials/`)
- **Scene utilities** (`scripts/utilities/`)
- **Golf plaque generator addon** (`scripts/golf/`) for layered hole-in-one commemorative builds
- **Topology builder workflow** (`/generate/topology` + `scripts/golf/topology_builder.py`) for LiDAR-informed plaque generation

## Repository layout

```text
scripts/
  animation/
  geometry/
  golf/
  materials/
  utilities/
api/
```

## Getting started

1. Clone this repository.
2. Install one or more addon folders from `scripts/` into Blender (`Edit > Preferences > Add-ons > Install`).
3. Enable the addon and use it from `View3D > Sidebar`.

For contributor-oriented setup, detailed module documentation, and guidance for adding or editing features, see [`CONTRIBUTING.md`](./CONTRIBUTING.md).
