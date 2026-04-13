"""Blender headless worker for the golf plaque GaaS API.

This script is invoked by ``api/main.py`` via ``subprocess.run()`` using
Blender's ``--python`` flag:

    blender --background \\
            --python /app/api/blender_worker.py \\
            -- \\
            --input       /tmp/<uuid>.svg \\
            --output      /tmp/<uuid>_out \\
            --format      stl|blend \\
            --mode        engrave|insert \\
            --params-file /tmp/<uuid>_params.json

Everything before ``--`` is consumed by Blender itself; everything after is
parsed by :func:`_parse_args`.

Export behaviour
----------------
blend
    Saves the entire Blender scene as ``result.blend`` in the output directory.

stl
    Exports mesh objects from the output collection into per-layer-group STL
    files (one file per colour prefix, plus ``base_and_text.stl``).  All files
    are written to the output directory so that ``api/main.py`` can zip them.

    Layer grouping
    ~~~~~~~~~~~~~~
    - ``Hole_In_One_Base`` + any ``Text.*`` objects → ``base_and_text.stl``
    - ``Water.*``   → ``water.stl``
    - ``Sand.*``    → ``sand.stl``
    - ``Green.*``   → ``green.stl``
    - ``Tee.*``     → ``tee.stl``
    - ``Fairway.*`` → ``fairway.stl``
    - ``Rough.*``   → ``rough.stl``
    - anything else → ``misc.stl``
"""

import argparse
import json
import os
import sys


# ---------------------------------------------------------------------------
# Argument parsing  (must happen before any bpy import)
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    """Parse worker-specific arguments from after the ``--`` separator."""
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []

    parser = argparse.ArgumentParser(
        prog="blender_worker",
        description="Blender headless plaque-generation worker",
    )
    parser.add_argument("--input",  required=True, help="Path to the source SVG file")
    parser.add_argument("--output", required=True, help="Output directory for generated files")
    parser.add_argument(
        "--format", required=True, choices=["stl", "blend"], help="Export format"
    )
    parser.add_argument(
        "--mode", required=True, choices=["engrave", "insert"], help="Generation mode"
    )
    parser.add_argument(
        "--params-file",
        dest="params_file",
        default=None,
        help="Path to a JSON file containing build parameters (preferred over --params)",
    )
    parser.add_argument(
        "--params", default="{}", help="JSON string of build parameters (legacy fallback)"
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# sys.path setup  (makes the golf package importable)
# ---------------------------------------------------------------------------

def _setup_sys_path() -> None:
    """Add /app and /app/scripts to ``sys.path`` so that the golf package can
    be imported inside Blender's embedded Python interpreter.

    Expected layout inside the Docker container::

        /app/
          api/blender_worker.py   ← this file
          scripts/
            golf/
              plaque_builder.py
              insert_builder.py
              ...
    """
    api_dir = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.dirname(api_dir)
    scripts_dir = os.path.join(app_dir, "scripts")

    for path in (app_dir, scripts_dir):
        if path not in sys.path:
            sys.path.insert(0, path)


# ---------------------------------------------------------------------------
# SVG import
# ---------------------------------------------------------------------------

def _import_svg(filepath: str) -> None:
    """Import an SVG file into the current Blender scene.

    Blender's SVG importer creates Curve objects whose names match the SVG
    layer / group names (e.g. ``Water.001``, ``Text.002``).  The golf pipeline
    then selects objects by these name prefixes.
    """
    import bpy

    print(f"[blender_worker] Importing SVG: {filepath}")
    bpy.ops.import_curve.svg(filepath=filepath)

    imported = [o.name for o in bpy.data.objects if o.type in {"CURVE", "MESH"}]
    print(f"[blender_worker] Scene objects after import: {imported}")


# ---------------------------------------------------------------------------
# STL export helpers
# ---------------------------------------------------------------------------

def _stl_group_name(obj_name: str) -> str:
    """Map a Blender object name to an STL export-group label.

    The base plaque and any Text objects are combined into a single file
    because they are typically printed as one piece.  Every other colour
    prefix gets its own file.
    """
    from golf.config import BASE_OBJECT_NAME, COLOR_MAP  # noqa: PLC0415

    if obj_name == BASE_OBJECT_NAME or obj_name.startswith("Text"):
        return "base_and_text"

    for prefix in COLOR_MAP:
        if obj_name.startswith(prefix):
            return prefix.lower()

    return "misc"


def _export_stl_operator(filepath: str, use_selection: bool) -> None:
    """Invoke the appropriate STL export operator for the running Blender version.

    Blender 3.3+ ships a built-in ``wm.stl_export``; older versions used the
    legacy ``export_mesh.stl`` add-on operator.
    """
    import bpy

    if hasattr(bpy.ops.wm, "stl_export"):
        # Blender 3.3+ native exporter
        bpy.ops.wm.stl_export(
            filepath=filepath,
            export_selected_objects=use_selection,
            ascii_format=False,
            apply_modifiers=True,
        )
    else:
        # Legacy add-on exporter (Blender < 3.3)
        bpy.ops.export_mesh.stl(
            filepath=filepath,
            use_selection=use_selection,
            use_mesh_modifiers=True,
        )


def _export_stl_groups(output_dir: str, mode: str) -> None:
    """Export objects from the output collection into per-group STL files.

    Objects are grouped by their name prefix (see :func:`_stl_group_name`).
    Each group is exported as a separate ``.stl`` file so that a multi-colour
    3-D print can be sliced with individual filament assignments.
    """
    import bpy
    from golf.config import (  # noqa: PLC0415
        INSERTS_COLLECTION_NAME,
        OUTPUT_COLLECTION_NAME,
    )

    collection_name = (
        INSERTS_COLLECTION_NAME if mode == "insert" else OUTPUT_COLLECTION_NAME
    )
    collection = bpy.data.collections.get(collection_name)

    if collection is not None:
        candidates = [
            o for o in collection.objects
            if o.type == "MESH" and not o.hide_render
        ]
    else:
        print(
            f"[blender_worker] WARNING: collection '{collection_name}' not found; "
            "falling back to all visible mesh objects"
        )
        candidates = [
            o for o in bpy.data.objects
            if o.type == "MESH" and not o.hide_render
        ]

    if not candidates:
        print("[blender_worker] WARNING: no exportable mesh objects found")
        return

    # Build groups
    groups: dict[str, list] = {}
    for obj in candidates:
        group = _stl_group_name(obj.name)
        groups.setdefault(group, []).append(obj)

    summary = ", ".join(f"{g}({len(o)})" for g, o in groups.items())
    print(f"[blender_worker] STL export groups: {summary}")

    # Ensure object mode before selecting / exporting
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    for group_name, objects in groups.items():
        filepath = os.path.join(output_dir, f"{group_name}.stl")

        bpy.ops.object.select_all(action="DESELECT")
        for obj in objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objects[0]

        _export_stl_operator(filepath, use_selection=True)
        print(f"[blender_worker] Exported: {filepath}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    _setup_sys_path()
    args = _parse_args()

    try:
        if args.params_file:
            with open(args.params_file, encoding="utf-8") as fh:
                params = json.load(fh)
        else:
            params = json.loads(args.params)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[blender_worker] ERROR: could not load build parameters: {exc}")
        sys.exit(1)

    import bpy

    # Start from a clean, empty scene to avoid interference from the default
    # Blender startup file (cube, camera, light, etc.).
    bpy.ops.wm.read_homefile(use_empty=True)

    # ── Import SVG ─────────────────────────────────────────────────────────
    _import_svg(args.input)

    # ── Run the generation pipeline ────────────────────────────────────────
    if args.mode == "engrave":
        from golf.plaque_request import PlaqueRequest   # noqa: PLC0415
        from golf.plaque_builder import carve_plaque    # noqa: PLC0415

        valid_fields = set(PlaqueRequest.__dataclass_fields__)
        filtered = {k: v for k, v in params.items() if k in valid_fields}
        req = PlaqueRequest(**filtered)

        print(f"[blender_worker] carve_plaque params: {filtered}")
        carve_plaque(req)

    elif args.mode == "insert":
        from golf.insert_request import InsertRequest   # noqa: PLC0415
        from golf.insert_builder import build_inserts   # noqa: PLC0415

        valid_fields = set(InsertRequest.__dataclass_fields__)
        filtered = {k: v for k, v in params.items() if k in valid_fields}
        req = InsertRequest(**filtered)

        print(f"[blender_worker] build_inserts params: {filtered}")
        build_inserts(req)

    # ── Export the result ──────────────────────────────────────────────────
    os.makedirs(args.output, exist_ok=True)

    if args.format == "blend":
        blend_path = os.path.join(args.output, "result.blend")
        bpy.ops.wm.save_as_mainfile(filepath=blend_path)
        print(f"[blender_worker] Saved .blend: {blend_path}")

    elif args.format == "stl":
        _export_stl_groups(args.output, args.mode)

    print("[blender_worker] Done.")


main()
