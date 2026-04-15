"""Golf Plaque GaaS API – application entry point.

Route configuration only. See api/README.md for full usage documentation,
api/schemas.py for the typed request models, and api/generation.py for the
Blender-worker orchestration logic.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, UploadFile
from fastapi.responses import Response

from .generation import run_generation
from .schemas import (
    EngraveSettings,
    HealthResponse,
    InsertSettings,
    TopologySettings,
    make_form_depends,
)

logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------

_README = Path(__file__).parent / "README.md"
_description = _README.read_text(encoding="utf-8") if _README.exists() else ""

BLENDER_BIN = os.environ.get("BLENDER_BIN", "/usr/local/bin/blender")

app = FastAPI(
    title="Golf Plaque GaaS API",
    description=_description,
    version="1.0.0",
)

# Pre-build the form dependency functions once at import time.
_engrave_form = make_form_depends(EngraveSettings)
_insert_form = make_form_depends(InsertSettings)
_topology_form = make_form_depends(TopologySettings)

# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@app.get(
    "/health",
    summary="Service health check",
    tags=["Status"],
    response_model=HealthResponse,
)
def health() -> HealthResponse:
    """Return service health; verifies the Blender binary is present and executable."""
    blender_ok = os.path.isfile(BLENDER_BIN) and os.access(BLENDER_BIN, os.X_OK)
    return HealthResponse(
        status="ok" if blender_ok else "degraded",
        blender_bin=BLENDER_BIN,
        blender_available=blender_ok,
    )


# ---------------------------------------------------------------------------
# Generation endpoints
# ---------------------------------------------------------------------------


@app.post(
    "/generate/engrave",
    summary="Generate a carved / engraved golf plaque",
    tags=["Generation"],
    response_description=(
        "ZIP of per-layer STL files (model/stl) "
        "or a .blend project (application/x-blender)"
    ),
    responses={
        200: {"description": "Generated model returned in the requested format"},
        500: {"description": "Blender worker failure – response includes stdout/stderr"},
        504: {"description": "Blender worker timed out"},
    },
)
async def generate_engrave(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(
        ...,
        description="SVG file containing the golf-course artwork layers.",
    ),
    settings: EngraveSettings = Depends(_engrave_form),
    accept: Optional[str] = Header(
        default="model/stl",
        description=(
            "Desired output format. "
            "Use `model/stl` (default) for a ZIP of STL files, "
            "or `application/x-blender` for a .blend project file."
        ),
    ),
) -> Response:
    """Generate a carved / engraved plaque from an SVG file.

    The SVG layers are mapped to golf-course elements (`Water`, `Sand`, `Green`,
    `Tee`, `Fairway`, `Rough`, `Text`) and processed by the `carve_plaque`
    pipeline inside Blender running in headless mode.

    All settings fields are optional and fall back to sensible defaults.
    """
    return await run_generation(
        file, settings.model_dump(), "engrave", accept, background_tasks
    )


@app.post(
    "/generate/insert",
    summary="Generate a 3-D–printed colour-insert set",
    tags=["Generation"],
    response_description=(
        "ZIP of per-layer STL files (model/stl) "
        "or a .blend project (application/x-blender)"
    ),
    responses={
        200: {"description": "Generated model returned in the requested format"},
        500: {"description": "Blender worker failure – response includes stdout/stderr"},
        504: {"description": "Blender worker timed out"},
    },
)
async def generate_insert(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(
        ...,
        description="SVG file containing the golf-course artwork layers.",
    ),
    settings: InsertSettings = Depends(_insert_form),
    accept: Optional[str] = Header(
        default="model/stl",
        description=(
            "Desired output format. "
            "Use `model/stl` (default) for a ZIP of STL files, "
            "or `application/x-blender` for a .blend project file."
        ),
    ),
) -> Response:
    """Generate a colour-insert set from an SVG file.

    Each colour layer (`Water`, `Sand`, `Green`, `Tee`, `Fairway`, `Rough`) is
    built as a press-fit insert piece using the `build_inserts` pipeline inside
    Blender running in headless mode.

    All settings fields are optional and fall back to sensible defaults.
    """
    return await run_generation(
        file, settings.model_dump(), "insert", accept, background_tasks
    )


@app.post(
    "/generate/topology",
    summary="Generate a LiDAR-informed topology plaque",
    tags=["Generation"],
    response_description=(
        "ZIP of per-layer STL files (model/stl) "
        "or a .blend project (application/x-blender)"
    ),
    responses={
        200: {"description": "Generated model returned in the requested format"},
        500: {"description": "Blender worker failure – response includes stdout/stderr"},
        504: {"description": "Blender worker timed out"},
    },
)
async def generate_topology(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(
        ...,
        description="SVG file containing the golf-course artwork layers.",
    ),
    lidar_file: UploadFile = File(
        ...,
        description="LiDAR-derived JSON/CSV data file used to drive topology thickness.",
    ),
    settings: TopologySettings = Depends(_topology_form),
    accept: Optional[str] = Header(
        default="model/stl",
        description=(
            "Desired output format. "
            "Use `model/stl` (default) for a ZIP of STL files, "
            "or `application/x-blender` for a .blend project file."
        ),
    ),
) -> Response:
    """Generate a topology-aware plaque from SVG and LiDAR inputs."""
    return await run_generation(
        file,
        settings.model_dump(),
        "topology",
        accept,
        background_tasks,
        extra_uploads={"lidar": lidar_file},
    )
