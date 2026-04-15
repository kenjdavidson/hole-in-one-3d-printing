"""Generation pipeline utilities for the Golf Plaque GaaS API.

This module handles all the work between receiving a validated API request and
returning the final response:

* Launching the Blender subprocess
* Streaming the result back as a ZIP of STL files or a ``.blend`` project
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

from fastapi import BackgroundTasks, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse

logger = logging.getLogger(__name__)

# Path to the Blender binary – override via environment variable in Docker.
BLENDER_BIN = os.environ.get("BLENDER_BIN", "/usr/local/bin/blender")

# Absolute path to blender_worker.py (same directory as this file).
WORKER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blender_worker.py")


# ---------------------------------------------------------------------------
# Format resolution
# ---------------------------------------------------------------------------


def determine_format(accept: Optional[str]) -> str:
    """Resolve the Blender export format from the ``Accept`` header value.

    Returns ``"blend"`` when the client requests ``application/x-blender``,
    otherwise ``"stl"`` (the default).
    """
    if accept and "application/x-blender" in accept:
        return "blend"
    return "stl"


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def _build_blend_response(output_dir: str, job_id: str, stdout: str) -> Response:
    """Read ``result.blend`` from *output_dir* and wrap it in a StreamingResponse."""
    blend_path = os.path.join(output_dir, "result.blend")
    if not os.path.isfile(blend_path):
        return JSONResponse(
            status_code=500,
            content={
                "detail": ".blend file was not produced by the worker",
                "job_id": job_id,
                "stdout": stdout[-4000:],
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


def _build_stl_response(output_dir: str, job_id: str, stdout: str) -> Response:
    """Zip all ``.stl`` files in *output_dir* and wrap them in a StreamingResponse."""
    stl_files = sorted(f for f in os.listdir(output_dir) if f.endswith(".stl"))
    if not stl_files:
        return JSONResponse(
            status_code=500,
            content={
                "detail": "No STL files were produced by the worker",
                "job_id": job_id,
                "stdout": stdout[-4000:],
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


_RESPONSE_BUILDERS = {
    "blend": _build_blend_response,
    "stl": _build_stl_response,
}


# ---------------------------------------------------------------------------
# Core generation handler
# ---------------------------------------------------------------------------


async def run_generation(
    file: UploadFile,
    params: dict,
    mode: str,
    accept: Optional[str],
    background_tasks: BackgroundTasks,
) -> Response:
    """Persist the SVG, invoke the Blender worker, and stream the result.

    Args:
        file:             Uploaded SVG file.
        params:           Validated build parameters (from a Pydantic model's
                          ``model_dump()``).
        mode:             ``"engrave"`` or ``"insert"``.
        accept:           Value of the client's ``Accept`` header.
        background_tasks: FastAPI background task queue; used to schedule
                          ``/tmp`` cleanup after the response is sent.

    Returns:
        A :class:`~fastapi.responses.StreamingResponse` containing either a
        ZIP of STL files or a ``.blend`` project file, or a
        :class:`~fastapi.responses.JSONResponse` describing the error.
    """
    fmt = determine_format(accept)
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

    # Write params to a temp file so that user-supplied values never appear as
    # raw strings in the subprocess argv list.
    params_path = os.path.join(work_dir, "params.json")
    with open(params_path, "w", encoding="utf-8") as fh:
        json.dump(params, fh)

    # All variable parts of cmd are paths we created (UUID-based) or fixed
    # literals. subprocess.run() with a list never invokes a shell.
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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
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

    return _RESPONSE_BUILDERS[fmt](output_dir, job_id, result.stdout)
