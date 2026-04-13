"""FastAPI service for the golf plaque Geometry-as-a-Service (GaaS) platform.

Endpoints
---------
POST /generate/engrave
    Generate a carved / engraved golf plaque from an SVG input.

POST /generate/insert
    Generate a 3-D–printed colour-insert set from an SVG input.

Content negotiation (Accept header)
------------------------------------
model/stl               Returns a ZIP archive containing one STL per layer group.
application/x-blender   Returns a .blend project file openable in desktop Blender.

Usage examples (curl)
---------------------
# STL output (default)
curl -X POST http://localhost:8000/generate/engrave \\
     -F "file=@course.svg" \\
     -F 'settings={"plaque_width":120,"text_mode":"ENGRAVE"}' \\
     -H "Accept: model/stl" \\
     -o plaque.zip

# Blender project output
curl -X POST http://localhost:8000/generate/engrave \\
     -F "file=@course.svg" \\
     -F 'settings={}' \\
     -H "Accept: application/x-blender" \\
     -o plaque.blend
"""

import io
import json
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, Header, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Path to the Blender binary – override via environment variable in Docker.
BLENDER_BIN = os.environ.get("BLENDER_BIN", "/usr/local/bin/blender")

# Absolute path to blender_worker.py (same directory as this file).
WORKER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blender_worker.py")

app = FastAPI(
    title="Golf Plaque GaaS API",
    description=(
        "**Geometry-as-a-Service** – generate 3-D golf plaque models via REST.\n\n"
        "Submit an SVG file and design parameters; receive per-layer STL files "
        "(zipped) or a full `.blend` project file.\n\n"
        "### Content negotiation\n"
        "Set the `Accept` header to control the output format:\n"
        "- `model/stl` *(default)* – ZIP archive of per-layer STL files\n"
        "- `application/x-blender` – `.blend` project file\n\n"
        "### Generation modes\n"
        "- `/generate/engrave` – carved / engraved golf-course plaque "
        "(uses `PlaqueRequest` parameters)\n"
        "- `/generate/insert` – colour-insert set "
        "(uses `InsertRequest` parameters)\n"
    ),
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get(
    "/health",
    summary="Service health check",
    tags=["Status"],
    response_description="Service status and Blender binary availability",
)
def health() -> dict:
    """Return the health of the service.

    Checks that the Blender binary is present and executable.
    This endpoint is used by the Docker healthcheck and monitoring systems.
    """
    blender_ok = os.path.isfile(BLENDER_BIN) and os.access(BLENDER_BIN, os.X_OK)
    return {
        "status": "ok" if blender_ok else "degraded",
        "blender_bin": BLENDER_BIN,
        "blender_available": blender_ok,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _determine_format(accept: Optional[str]) -> str:
    """Resolve the Blender export format from the Accept header value."""
    if accept and "application/x-blender" in accept:
        return "blend"
    return "stl"


async def _run_generation(
    file: UploadFile,
    settings: str,
    mode: str,
    accept: Optional[str],
    background_tasks: BackgroundTasks,
) -> StreamingResponse:
    """Core handler: persist SVG, invoke Blender worker, stream the result."""
    fmt = _determine_format(accept)
    job_id = uuid.uuid4().hex

    work_dir = os.path.join(tempfile.gettempdir(), f"plaque_{job_id}")
    os.makedirs(work_dir, exist_ok=True)

    # Schedule /tmp cleanup so it always runs after the response is sent.
    background_tasks.add_task(shutil.rmtree, work_dir, True)

    # Write the uploaded SVG to a UUID-named temp file.
    svg_path = os.path.join(work_dir, f"{job_id}.svg")
    svg_bytes = await file.read()
    with open(svg_path, "wb") as fh:
        fh.write(svg_bytes)

    output_dir = os.path.join(work_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    # Validate the JSON settings before handing off to Blender.
    try:
        params = json.loads(settings)
    except json.JSONDecodeError:
        return JSONResponse(
            status_code=422,
            content={"detail": "The 'settings' field must be a valid JSON object."},
        )
    if not isinstance(params, dict):
        return JSONResponse(
            status_code=422,
            content={"detail": "The 'settings' field must be a JSON object (dict)."},
        )

    # Write params to a temp file so that arbitrary user-supplied values never
    # appear as raw strings in the subprocess argv list.  This avoids any
    # risk of argv injection and also sidesteps OS command-line length limits.
    params_path = os.path.join(work_dir, "params.json")
    with open(params_path, "w", encoding="utf-8") as fh:
        json.dump(params, fh)

    # All variable parts of cmd are paths we created (UUID-based) or are
    # fixed literals ("--background", choices from _determine_format / mode).
    # subprocess.run() with a list never invokes a shell, so there is no
    # shell-injection risk regardless of the file contents.
    cmd = [
        BLENDER_BIN,
        "--background",
        "--python", WORKER_SCRIPT,
        "--",
        "--input",       svg_path,
        "--output",      output_dir,
        "--format",      fmt,
        "--mode",        mode,
        "--params-file", params_path,
    ]

    logger.info("Job %s [%s/%s]: %s", job_id, mode, fmt, " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return JSONResponse(
            status_code=504,
            content={"detail": "Blender worker timed out after 300 seconds", "job_id": job_id},
        )

    logger.info("Job %s stdout:\n%s", job_id, result.stdout)
    if result.stderr:
        logger.warning("Job %s stderr:\n%s", job_id, result.stderr)

    if result.returncode != 0:
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Blender worker exited with non-zero status",
                "job_id": job_id,
                "returncode": result.returncode,
                "stdout": result.stdout[-4000:],
                "stderr": result.stderr[-2000:],
            },
        )

    # ── Stream the result ──────────────────────────────────────────────────

    if fmt == "blend":
        blend_path = os.path.join(output_dir, "result.blend")
        if not os.path.isfile(blend_path):
            return JSONResponse(
                status_code=500,
                content={
                    "detail": ".blend file was not produced by the worker",
                    "job_id": job_id,
                    "stdout": result.stdout[-4000:],
                },
            )
        with open(blend_path, "rb") as fh:
            data = fh.read()
        return StreamingResponse(
            io.BytesIO(data),
            media_type="application/x-blender",
            headers={
                "Content-Disposition": f'attachment; filename="plaque_{job_id}.blend"',
                "X-Job-Id": job_id,
            },
        )

    # fmt == "stl"  →  zip all generated .stl files
    stl_files = sorted(f for f in os.listdir(output_dir) if f.endswith(".stl"))
    if not stl_files:
        return JSONResponse(
            status_code=500,
            content={
                "detail": "No STL files were produced by the worker",
                "job_id": job_id,
                "stdout": result.stdout[-4000:],
            },
        )

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for stl_name in stl_files:
            zf.write(os.path.join(output_dir, stl_name), arcname=stl_name)
    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="plaque_{job_id}.zip"',
            "X-Job-Id": job_id,
            "X-Stl-Files": ",".join(stl_files),
        },
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post(
    "/generate/engrave",
    summary="Generate a carved / engraved golf plaque",
    response_description=(
        "ZIP of per-layer STL files (model/stl) "
        "or a .blend project (application/x-blender)"
    ),
    tags=["Generation"],
    responses={
        200: {"description": "Generated model returned in the requested format"},
        422: {"description": "Invalid settings JSON"},
        500: {"description": "Blender worker failure – includes stdout/stderr"},
        504: {"description": "Blender worker timed out"},
    },
)
async def generate_engrave(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(
        ...,
        description="SVG file containing the golf-course artwork layers",
    ),
    settings: str = Form(
        default="{}",
        description=(
            "JSON string with `PlaqueRequest` build parameters.  "
            "All keys are optional and fall back to sensible defaults.  "
            "Example: `{\"plaque_width\": 120, \"text_mode\": \"ENGRAVE\"}`"
        ),
    ),
    accept: Optional[str] = Header(
        default="model/stl",
        description="Desired output format: `model/stl` (default) or `application/x-blender`",
    ),
):
    """Generate a carved / engraved plaque from an SVG file.

    The SVG layers are mapped to golf-course elements (Water, Sand, Green, Tee,
    Fairway, Rough, Text) and processed by the `carve_plaque` pipeline inside
    Blender.

    **Settings keys** (all optional – see `PlaqueRequest` dataclass):

    | Key | Type | Default | Description |
    |-----|------|---------|-------------|
    | `plaque_width` | float | 100.0 | Plaque width (mm) |
    | `plaque_height` | float | 140.0 | Plaque height (mm) |
    | `plaque_thick` | float | 6.0 | Manual thickness (mm) |
    | `text_mode` | str | `"EMBOSS"` | `"EMBOSS"` or `"ENGRAVE"` |
    | `text_extrusion_height` | float | 1.0 | Text height / depth (mm) |
    | `use_auto_thickness` | bool | true | Layer-based thickness |
    | `use_top_taper` | bool | false | Draft walls |
    | `use_stepped_walls` | bool | false | Terraced walls |
    | `use_layer_depths` | bool | false | Custom per-layer depths |
    | `depth_water` | float | 3.0 | Water carve depth (mm) |
    | `depth_sand` | float | 2.4 | Sand carve depth (mm) |
    | `depth_green` | float | 1.8 | Green carve depth (mm) |
    | `depth_fairway` | float | 1.2 | Fairway carve depth (mm) |
    """
    return await _run_generation(file, settings, "engrave", accept, background_tasks)


@app.post(
    "/generate/insert",
    summary="Generate a 3-D–printed colour-insert set",
    response_description=(
        "ZIP of per-layer STL files (model/stl) "
        "or a .blend project (application/x-blender)"
    ),
    tags=["Generation"],
    responses={
        200: {"description": "Generated model returned in the requested format"},
        422: {"description": "Invalid settings JSON"},
        500: {"description": "Blender worker failure – includes stdout/stderr"},
        504: {"description": "Blender worker timed out"},
    },
)
async def generate_insert(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(
        ...,
        description="SVG file containing the golf-course artwork layers",
    ),
    settings: str = Form(
        default="{}",
        description=(
            "JSON string with `InsertRequest` build parameters.  "
            "All keys are optional.  "
            "Example: `{\"plaque_width\": 120, \"insert_clearance\": 0.25}`"
        ),
    ),
    accept: Optional[str] = Header(
        default="model/stl",
        description="Desired output format: `model/stl` (default) or `application/x-blender`",
    ),
):
    """Generate a colour-insert set from an SVG file.

    Each colour layer (Water, Sand, Green, Tee, Fairway, Rough) is built as a
    press-fit insert piece using the `build_inserts` pipeline inside Blender.

    **Settings keys** (all optional – see `InsertRequest` dataclass):

    | Key | Type | Default | Description |
    |-----|------|---------|-------------|
    | `plaque_width` | float | 100.0 | Plaque width (mm) |
    | `plaque_height` | float | 140.0 | Plaque height (mm) |
    | `plaque_thick` | float | 6.0 | Base thickness (mm) |
    | `insert_clearance` | float | 0.25 | Per-side clearance (mm) |
    | `insert_element_layers` | int | 4 | Print layers per insert |
    | `insert_hole_layers` | int | 2 | Print layers per hole |
    | `text_mode` | str | `"EMBOSS"` | `"EMBOSS"` or `"ENGRAVE"` |
    | `use_shrink_element` | bool | true | Shrink insert vs grow hole |
    | `generate_container` | bool | false | Generate slide-in container |
    """
    return await _run_generation(file, settings, "insert", accept, background_tasks)
