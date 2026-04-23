"""Serialisable build request for the plaque pipeline.

:class:`PlaqueRequest` mirrors every attribute read from the Blender
``HOLEINONE_Properties`` scene property group as a plain Python dataclass.
This means the pipeline (:func:`~plaque_builder.carve_plaque`) can be driven
from a web API, CLI, or automated test without an active Blender UI session —
just construct a :class:`PlaqueRequest` and pass it where ``props`` is
expected.

Example (headless Python / web handler)::

    from scripts.golf.plaque_request import PlaqueRequest
    from scripts.golf.plaque_builder import carve_plaque

    req = PlaqueRequest(
        plaque_width=120.0,
        plaque_height=160.0,
        text_mode="ENGRAVE",
    )
    carve_plaque(req)
"""

from dataclasses import dataclass


@dataclass
class PlaqueRequest:
    """Complete specification for a single plaque build.

    All attributes have the same names, types, and defaults as the
    corresponding Blender ``HOLEINONE_Properties`` entries so that they
    work as drop-in replacements for the Blender property group object.
    """

    # ── Plaque dimensions ────────────────────────────────────────────────────
    plaque_width: float = 100.0
    """Plaque width in millimetres."""

    plaque_height: float = 140.0
    """Plaque height in millimetres."""

    plaque_shape: str = "RECTANGLE"
    """Base shape used when no ``Plaque_Base`` SVG object is present.

    Valid values are ``"RECTANGLE"`` (default – a rectangular slab) and
    ``"CIRCLE"`` (a cylinder whose diameter equals the smaller of
    ``plaque_width`` and ``plaque_height``).

    When a ``Plaque_Base`` or ``Plaque_Frame`` SVG object *is* present it is
    used directly as the base shape regardless of this setting, so rounded
    rectangles, circles, and any custom outlines drawn in Inkscape are all
    supported automatically through the SVG workflow.
    """

    plaque_thick: float = 6.0
    """Manual plaque thickness in millimetres (used when ``use_auto_thickness`` is ``False``)."""

    # ── Auto-thickness (layer-based) ─────────────────────────────────────────
    use_auto_thickness: bool = True
    """Derive total plaque thickness from layer counts when ``True``."""

    print_layer_height: float = 0.2
    """Per-layer print height used to compute plaque thickness (mm)."""

    base_print_layers: int = 3
    """Minimum solid base layers before carved segments."""

    segment_print_layers: int = 3
    """Printed layers allocated to each detected golf segment."""

    # ── Container generation ─────────────────────────────────────────────────
    generate_container: bool = False
    """Create a printable container with a cavity sized to the plaque outline."""

    container_clearance: float = 0.25
    """Gap added per side between plaque and container cavity (mm)."""

    container_wall_thickness: float = 2.0
    """Container wall thickness around the cavity (mm)."""

    container_back_thickness: float = 2.0
    """Solid back thickness below the cavity (mm)."""

    # ── Text / fine-detail options ────────────────────────────────────────────
    text_mode: str = "EMBOSS"
    """Processing mode for ``Text.*`` objects: ``"EMBOSS"`` or ``"ENGRAVE"``.

    Uses a plain string rather than :class:`~config.ElementType` so that a
    ``PlaqueRequest`` is a drop-in replacement for the Blender
    ``HOLEINONE_Properties`` group, whose ``EnumProperty`` also returns
    identifier strings.  Valid values are ``"EMBOSS"`` and ``"ENGRAVE"``.
    """

    text_extrusion_height: float = 1.0
    """Emboss height above surface or engrave depth below surface (mm)."""

    # ── Advanced carving options ─────────────────────────────────────────────
    show_advanced: bool = False
    """UI helper — not used by the pipeline."""

    use_top_taper: bool = False
    """Expand the top perimeter of each cutter to create drafted walls."""

    top_taper_width: float = 0.6
    """Outward offset applied only to the top perimeter (mm)."""

    use_stepped_walls: bool = False
    """Create terraced walls by stacking multiple shallower, wider cutters."""

    stepped_wall_width: float = 1.5
    """Total added width from deepest cut to top-most terrace (mm)."""

    stepped_wall_steps: int = 3
    """Number of stacked terraces used to approximate a draft angle."""

    use_floor_texture: bool = False
    """Add procedural displacement to the floor of Water and Sand cutters."""

    # ── Custom layer depths ───────────────────────────────────────────────────
    use_layer_depths: bool = False
    """Override the default carved depth for each layer type when ``True``."""

    depth_water: float = 3.0
    """Carved depth of Water layers (mm)."""

    depth_sand: float = 2.4
    """Carved depth of Sand layers (mm)."""

    depth_green: float = 1.8
    """Carved depth of Green layers (mm)."""

    depth_fairway: float = 1.2
    """Carved depth of Fairway layers (mm)."""

    # ── Validation ────────────────────────────────────────────────────────────

    _VALID_TEXT_MODES = {"EMBOSS", "ENGRAVE"}
    _VALID_PLAQUE_SHAPES = {"RECTANGLE", "CIRCLE"}

    def __post_init__(self):
        if self.text_mode not in self._VALID_TEXT_MODES:
            raise ValueError(
                f"Invalid text_mode {self.text_mode!r}. "
                f"Expected one of: {sorted(self._VALID_TEXT_MODES)}"
            )
        if self.plaque_shape not in self._VALID_PLAQUE_SHAPES:
            raise ValueError(
                f"Invalid plaque_shape {self.plaque_shape!r}. "
                f"Expected one of: {sorted(self._VALID_PLAQUE_SHAPES)}"
            )
