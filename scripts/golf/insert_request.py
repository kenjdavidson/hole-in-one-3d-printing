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

    use_shrink_element: bool = True
    """When ``True`` (default), shrink each insert outline by
    :attr:`insert_clearance` so that it fits inside a hole sized to the raw
    SVG outline.

    When ``False``, keep the insert at full SVG size and instead grow the
    receiving hole by :attr:`insert_clearance`."""

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
