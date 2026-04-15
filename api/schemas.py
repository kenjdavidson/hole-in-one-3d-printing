"""Pydantic schemas for the Golf Plaque GaaS API.

These models serve two purposes:

1. **Validation** – Pydantic enforces types and constraints before the request
   reaches the Blender worker.
2. **Swagger UI** – Because these models are used with FastAPI's ``Form()``
   annotation, every field is rendered as a named, typed, individually-editable
   input in the Swagger UI at ``/docs``.

Each schema mirrors the corresponding pipeline dataclass exactly so that
``model.model_dump()`` can be passed directly to the worker without any
field-name translation.
"""

from typing import Literal

from pydantic import BaseModel, Field


class EngraveSettings(BaseModel):
    """Build parameters for the carved / engraved plaque pipeline.

    Mirrors :class:`~scripts.golf.plaque_request.PlaqueRequest`.
    All fields are optional; omitting a field uses the pipeline default.
    """

    # ── Plaque dimensions ────────────────────────────────────────────────────
    plaque_width: float = Field(
        default=100.0, gt=0,
        description="Plaque width in millimetres.",
    )
    plaque_height: float = Field(
        default=140.0, gt=0,
        description="Plaque height in millimetres.",
    )
    plaque_thick: float = Field(
        default=6.0, gt=0,
        description="Manual plaque thickness (mm). Used when use_auto_thickness is False.",
    )

    # ── Auto-thickness ───────────────────────────────────────────────────────
    use_auto_thickness: bool = Field(
        default=True,
        description=(
            "Derive total plaque thickness from layer counts when True. "
            "Set to False to use plaque_thick directly."
        ),
    )
    print_layer_height: float = Field(
        default=0.2, gt=0,
        description="Per-layer print height used for auto-thickness calculation (mm).",
    )
    base_print_layers: int = Field(
        default=3, ge=1,
        description="Minimum solid base layers before carved segments.",
    )
    segment_print_layers: int = Field(
        default=3, ge=1,
        description="Print layers allocated to each detected golf segment.",
    )

    # ── Container ────────────────────────────────────────────────────────────
    generate_container: bool = Field(
        default=False,
        description="Create a printable container with a cavity sized to the plaque outline.",
    )
    container_clearance: float = Field(
        default=0.25, ge=0,
        description="Gap added per side between plaque and container cavity (mm).",
    )
    container_wall_thickness: float = Field(
        default=2.0, gt=0,
        description="Container wall thickness around the cavity (mm).",
    )
    container_back_thickness: float = Field(
        default=2.0, gt=0,
        description="Solid back thickness below the cavity (mm).",
    )

    # ── Text / fine-detail ───────────────────────────────────────────────────
    text_mode: Literal["EMBOSS", "ENGRAVE"] = Field(
        default="EMBOSS",
        description=(
            "Processing mode for Text.* SVG layers. "
            "EMBOSS raises text above the surface; ENGRAVE cuts it in."
        ),
    )
    text_extrusion_height: float = Field(
        default=1.0, gt=0,
        description="Emboss height above surface or engrave depth below surface (mm).",
    )

    # ── Advanced carving ─────────────────────────────────────────────────────
    use_top_taper: bool = Field(
        default=False,
        description="Expand the top perimeter of each cutter to create drafted walls.",
    )
    top_taper_width: float = Field(
        default=0.6, ge=0,
        description="Outward offset applied only to the top perimeter (mm).",
    )
    use_stepped_walls: bool = Field(
        default=False,
        description="Create terraced walls by stacking multiple shallower, wider cutters.",
    )
    stepped_wall_width: float = Field(
        default=1.5, ge=0,
        description="Total added width from deepest cut to top-most terrace (mm).",
    )
    stepped_wall_steps: int = Field(
        default=3, ge=1,
        description="Number of stacked terraces used to approximate a draft angle.",
    )
    use_floor_texture: bool = Field(
        default=False,
        description="Add procedural displacement to the floor of Water and Sand cutters.",
    )

    # ── Custom layer depths ───────────────────────────────────────────────────
    use_layer_depths: bool = Field(
        default=False,
        description="Override the default carved depth for each layer type when True.",
    )
    depth_water: float = Field(
        default=3.0, gt=0,
        description="Carved depth of Water layers (mm). Requires use_layer_depths=True.",
    )
    depth_sand: float = Field(
        default=2.4, gt=0,
        description="Carved depth of Sand layers (mm). Requires use_layer_depths=True.",
    )
    depth_green: float = Field(
        default=1.8, gt=0,
        description="Carved depth of Green layers (mm). Requires use_layer_depths=True.",
    )
    depth_fairway: float = Field(
        default=1.2, gt=0,
        description="Carved depth of Fairway layers (mm). Requires use_layer_depths=True.",
    )


class InsertSettings(BaseModel):
    """Build parameters for the colour-insert set pipeline.

    Mirrors :class:`~scripts.golf.insert_request.InsertRequest`.
    All fields are optional; omitting a field uses the pipeline default.
    """

    # ── Plaque dimensions ────────────────────────────────────────────────────
    plaque_width: float = Field(
        default=100.0, gt=0,
        description="Plaque width in millimetres.",
    )
    plaque_height: float = Field(
        default=140.0, gt=0,
        description="Plaque height in millimetres.",
    )
    plaque_thick: float = Field(
        default=6.0, gt=0,
        description="Base plaque thickness in millimetres.",
    )

    # ── Print layer settings ─────────────────────────────────────────────────
    print_layer_height: float = Field(
        default=0.2, gt=0,
        description="Per-layer print height in millimetres.",
    )
    insert_element_layers: int = Field(
        default=4, ge=1,
        description=(
            "Print layers that determine each insert piece's height. "
            "element_height = insert_element_layers × print_layer_height."
        ),
    )
    insert_hole_layers: int = Field(
        default=2, ge=1,
        description=(
            "Print layers that determine the depth of the receiving hole. "
            "hole_depth = insert_hole_layers × print_layer_height."
        ),
    )

    # ── Clearance / fit ──────────────────────────────────────────────────────
    insert_clearance: float = Field(
        default=0.25, ge=0,
        description="Per-side clearance between insert piece and receiving hole (mm).",
    )
    deep_layer_clearance_bias: float = Field(
        default=0.0, ge=0,
        description=(
            "Extra clearance per side for deep layers (Green, Tee, Sand, Water) (mm). "
            "Try 0.1–0.15 if deep-layer pieces are tight."
        ),
    )
    use_shrink_element: bool = Field(
        default=True,
        description=(
            "When True, shrink each insert outline by insert_clearance. "
            "When False, grow the receiving hole instead."
        ),
    )

    # ── Text on base ─────────────────────────────────────────────────────────
    text_mode: Literal["EMBOSS", "ENGRAVE"] = Field(
        default="EMBOSS",
        description=(
            "Processing mode for Text.* layers on the insert base. "
            "EMBOSS raises text; ENGRAVE cuts it in."
        ),
    )
    text_extrusion_height: float = Field(
        default=1.0, gt=0,
        description="Emboss height / engrave depth for Text.* on the insert base (mm).",
    )

    # ── Container ────────────────────────────────────────────────────────────
    generate_container: bool = Field(
        default=False,
        description="Generate a slide-in container sized to the insert base.",
    )
    container_clearance: float = Field(
        default=0.25, ge=0,
        description="Gap added per side between insert base and container cavity (mm).",
    )
    container_wall_thickness: float = Field(
        default=2.0, gt=0,
        description="Container wall thickness around the cavity (mm).",
    )
    container_back_thickness: float = Field(
        default=2.0, gt=0,
        description="Container back thickness below the cavity (mm).",
    )
    container_cavity_extra_depth: float = Field(
        default=0.5, ge=0,
        description=(
            "Extra cavity depth beyond insert base thickness (mm). "
            "Positive values make container walls taller than the assembly."
        ),
    )

    # ── Border ───────────────────────────────────────────────────────────────
    use_embossed_border: bool = Field(
        default=False,
        description="Add a raised border ring on the base top surface.",
    )
    separate_border_insert: bool = Field(
        default=False,
        description="Generate the border as a separate keyed insert ring.",
    )
    border_inset: float = Field(
        default=0.0, ge=0,
        description="Inset from the base edge to the border outer edge (mm).",
    )
    border_width: float = Field(
        default=0.8, gt=0,
        description="Raised border width measured inward from the outer border edge (mm).",
    )


class HealthResponse(BaseModel):
    """Response schema for the ``/health`` endpoint."""

    status: str = Field(description="'ok' if Blender is available, 'degraded' otherwise.")
    blender_bin: str = Field(description="Configured path to the Blender binary.")
    blender_available: bool = Field(description="True when the binary exists and is executable.")


# ---------------------------------------------------------------------------
# Form dependency factory
# ---------------------------------------------------------------------------

import inspect


def make_form_depends(model_cls: type[BaseModel]):
    """Return an async FastAPI dependency function whose signature mirrors
    every field in *model_cls* as an individual multipart ``Form()`` parameter.

    Using this instead of ``Annotated[Model, Form()]`` causes Swagger UI to
    render each model field as a separate named input (with its type, default,
    description, and – for ``Literal`` fields – a dropdown of allowed values)
    rather than as a single opaque JSON blob.

    Usage::

        EngraveForm = make_form_depends(EngraveSettings)

        @app.post("/generate/engrave")
        async def endpoint(settings: EngraveSettings = Depends(EngraveForm)):
            ...

    Args:
        model_cls: A Pydantic ``BaseModel`` subclass.  All fields must use
                   types that are form-encodeable (primitives, ``Literal``,
                   ``bool``, ``int``, ``float``, ``str``).

    Returns:
        An async callable suitable for use with ``fastapi.Depends``.
    """
    from fastapi import Form  # noqa: PLC0415  (avoids circular import at module level)

    params = []
    for field_name, field_info in model_cls.model_fields.items():
        form_default = ... if field_info.is_required() else field_info.default

        params.append(
            inspect.Parameter(
                field_name,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=field_info.annotation,
                default=Form(
                    default=form_default,
                    description=field_info.description or "",
                ),
            )
        )

    async def _form_dep(**kwargs) -> BaseModel:
        return model_cls(**kwargs)

    _form_dep.__signature__ = inspect.Signature(params)
    return _form_dep
