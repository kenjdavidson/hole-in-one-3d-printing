"""Blender headless worker entry point for the Golf Plaque GaaS API.

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
parsed here.

The actual pipeline and export logic lives in the ``worker/`` sub-package:

* :mod:`worker.scene`   – scene setup and SVG import
* :mod:`worker.engrave` – ``carve_plaque`` runner
* :mod:`worker.insert`  – ``build_inserts`` runner
* :mod:`worker.export`  – ``.blend`` / STL export
"""

import argparse
import json
import os
import sys


# ---------------------------------------------------------------------------
# Argument parsing  (before any bpy import)
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    """Parse worker arguments from after the ``--`` separator."""
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
        help="Path to a JSON file containing build parameters (preferred)",
    )
    parser.add_argument(
        "--params",
        default="{}",
        help="JSON string of build parameters (legacy fallback)",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# sys.path setup  (makes the golf package importable inside Blender's Python)
# ---------------------------------------------------------------------------

def _setup_sys_path() -> None:
    """Ensure the golf package and worker sub-package are importable.

    Expected Docker layout::

        /app/
          api/                    ← added to sys.path (enables `from worker.xxx import …`)
            blender_worker.py
            worker/
              engrave.py
              insert.py
              export.py
              scene.py
          scripts/                ← added to sys.path (enables `from golf.xxx import …`)
            golf/
              plaque_builder.py
              insert_builder.py
              …
    """
    api_dir = os.path.dirname(os.path.abspath(__file__))   # /app/api
    app_dir = os.path.dirname(api_dir)                     # /app
    scripts_dir = os.path.join(app_dir, "scripts")         # /app/scripts

    for path in (api_dir, app_dir, scripts_dir):
        if path not in sys.path:
            sys.path.insert(0, path)


# ---------------------------------------------------------------------------
# Parameter loading
# ---------------------------------------------------------------------------

def _load_params(args: argparse.Namespace) -> dict:
    """Load build parameters from ``--params-file`` or the ``--params`` string."""
    try:
        if args.params_file:
            with open(args.params_file, encoding="utf-8") as fh:
                return json.load(fh)
        return json.loads(args.params)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[blender_worker] ERROR: could not load build parameters: {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

_RUNNERS = {
    "engrave": "worker.engrave",
    "insert":  "worker.insert",
}


def main() -> None:
    _setup_sys_path()
    args = _parse_args()
    params = _load_params(args)

    import bpy                          # noqa: PLC0415  (Blender-only; not available in tests)
    from worker import scene, export    # noqa: PLC0415

    scene.setup_scene()
    scene.import_svg(args.input)

    # Import and run the mode-specific pipeline runner.
    import importlib
    runner_module = importlib.import_module(_RUNNERS[args.mode])
    runner_module.run(params)

    os.makedirs(args.output, exist_ok=True)
    export.export_result(args.format, args.mode, args.output)

    print("[blender_worker] Done.")


main()
