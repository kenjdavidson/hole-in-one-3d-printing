"""Serialisable build request for the insert/raise plaque pipeline.

:class:`InsertRequest` mirrors every attribute read from the Blender
``HOLEINONE_InsertProperties`` scene property group as a plain Python
dataclass.  This lets the insert pipeline (:func:`~insert_builder.build_inserts`)
be driven from a web API, CLI, or automated test without an active Blender
session — just construct an :class:`InsertRequest` and pass it where ``props``
is expected.

Example (headless Python / web handler)::

    from scripts.golf.insert_request import InsertRequest
    from scripts.golf.insert_builder import build_inserts

    req = InsertRequest(
        plaque_width=120.0,
        plaque_height=160.0,
        insert_clearance=0.25,
        use_shrink_element=True,
    )
    build_inserts(req)
"""

from dataclasses import dataclass


@dataclass
class InsertRequest:
    """Complete specification for a single insert-set build.

    Each attribute has the same name, type, and default as the corresponding
    Blender ``HOLEINONE_InsertProperties`` entry so that this dataclass is a
    drop-in replacement for the Blender property group object.
    """

    # ── Plaque dimensions ────────────────────────────────────────────────────
    plaque_width: float = 100.0
    """Plaque width in millimetres."""

    plaque_height: float = 140.0
    """Plaque height in millimetres."""

    plaque_thick: float = 6.0
    """Base plaque thickness in millimetres."""

    # ── Print layer settings ─────────────────────────────────────────────────
    print_layer_height: float = 0.2
    """Per-layer print height in millimetres."""

    insert_element_layers: int = 4
    """Number of print layers that determine each insert piece's height.

    ``element_height = insert_element_layers × print_layer_height``.
    """

    insert_hole_layers: int = 2
    """Number of print layers that determine the depth of the receiving hole
    carved into the parent piece.

    ``hole_depth = insert_hole_layers × print_layer_height``.
    """

    # ── Clearance / fit ──────────────────────────────────────────────────────
    insert_clearance: float = 0.25
    """Per-side clearance between the insert piece and its receiving hole (mm).

    Combined with :attr:`use_shrink_element`, this controls whether the insert
    is shrunk or the hole is grown to achieve the clearance gap.
    """

    deep_layer_clearance_bias: float = 0.0
    """Extra clearance added per side for Green, Tee, Sand, Water layers (mm).
    
    When insert geometry safety limits prevent full inset (e.g., Green can't be
    shrunk safely), increase this to add extra buffer to deep-layer pockets so
    the pieces still fit. Default 0.0; try 0.1–0.15 if deep layers are tight.
    """

    use_shrink_element: bool = True
    """When ``True`` (default), shrink each insert outline by
    :attr:`insert_clearance` so that it fits inside a hole sized to the raw
    SVG outline.

    When ``False``, keep the insert at full SVG size and instead grow the
    receiving hole by :attr:`insert_clearance`."""

    # ── Text-on-base controls ────────────────────────────────────────────────
    text_mode: str = "EMBOSS"
    """Text mode for Insert Builder base text processing.

    ``"EMBOSS"`` raises Text.* geometry above the base surface and
    ``"ENGRAVE"`` cuts Text.* geometry into the base.
    """

    text_extrusion_height: float = 1.0
    """Emboss height / engrave depth (mm) for Text.* on the insert base."""

    generate_container: bool = False
    """When ``True``, generate a slide-in container sized to the insert base."""

    container_clearance: float = 0.25
    """Gap added per side between insert base and container cavity (mm)."""

    container_wall_thickness: float = 2.0
    """Container wall thickness around the cavity (mm)."""

    container_back_thickness: float = 2.0
    """Container back thickness below the cavity (mm)."""

    container_cavity_extra_depth: float = 0.5
    """Extra cavity depth beyond insert base thickness (mm).

    Positive values make container walls taller than the inserted assembly,
    providing a protective raised edge.
    """

    use_embossed_border: bool = False
    """When ``True``, add a raised border ring on the base top surface."""

    separate_border_insert: bool = False
    """When ``True``, generate the border as a separate keyed insert ring."""

    border_inset: float = 0.0
    """Inset from the base edge to the border outer edge (mm)."""

    border_width: float = 0.8
    """Raised border width measured inward from the outer border edge (mm)."""

    # ── Validation ────────────────────────────────────────────────────────────

    def __post_init__(self):
        if self.insert_clearance < 0.0:
            raise ValueError(
                f"insert_clearance must be >= 0, got {self.insert_clearance!r}"
            )
        if self.insert_element_layers < 1:
            raise ValueError(
                f"insert_element_layers must be >= 1, got {self.insert_element_layers!r}"
            )
        if self.insert_hole_layers < 1:
            raise ValueError(
                f"insert_hole_layers must be >= 1, got {self.insert_hole_layers!r}"
            )
        if self.border_inset < 0.0:
            raise ValueError(
                f"border_inset must be >= 0, got {self.border_inset!r}"
            )
        if self.border_width <= 0.0:
            raise ValueError(
                f"border_width must be > 0, got {self.border_width!r}"
            )
        if self.container_clearance < 0.0:
            raise ValueError(
                f"container_clearance must be >= 0, got {self.container_clearance!r}"
            )
        if self.container_wall_thickness <= 0.0:
            raise ValueError(
                "container_wall_thickness must be > 0, "
                f"got {self.container_wall_thickness!r}"
            )
        if self.container_back_thickness <= 0.0:
            raise ValueError(
                "container_back_thickness must be > 0, "
                f"got {self.container_back_thickness!r}"
            )
        if self.container_cavity_extra_depth < 0.0:
            raise ValueError(
                "container_cavity_extra_depth must be >= 0, "
                f"got {self.container_cavity_extra_depth!r}"
            )
