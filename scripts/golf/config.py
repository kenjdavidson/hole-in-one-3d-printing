"""Shared configuration constants for the golf plaque generator."""

from dataclasses import dataclass
from enum import Enum

BASE_OBJECT_NAME = "Hole_In_One_Base"
OUTPUT_COLLECTION_NAME = "Hole_In_One_Output"
CUTTERS_COLLECTION_NAME = "Hole_In_One_Cutters"
AUTO_SCALE_FACTOR = 0.9

# Small overlap (mm) added above the plaque surface and to each cutter's
# solidify thickness to avoid coplanar Boolean artefacts.
CUTTER_EPSILON = 0.1

# Name prefixes that identify a dedicated plaque base imported from SVG.
# These objects are NOT used as cutters – they define the outer frame boundary.
PLAQUE_BASE_PREFIXES = ("Plaque_Base", "Plaque_Frame")

# Name prefixes that identify dedicated through-hole cutters such as bag-tag
# strap holes. These bypass normal depth/taper logic and always cut through.
STRAP_HOLE_PREFIXES = ("StrapHole",)


class ElementType(Enum):
    """Defines how an SVG layer's geometry is built into the plaque.

    Strategies are implemented in :mod:`element_strategy`.  Adding a new
    entry here (e.g. ``RELIEF``) and a matching :class:`ElementStrategy`
    subclass is all that is needed to introduce a new effect.

    Attributes:
        CARVE:   Full Boolean-difference pipeline – geometry is carved *into*
                 the plaque surface.  Supports tapers, stepped walls, and floor
                 textures.
        EMBOSS:  Solidify-extrude pipeline – geometry is raised *above* the
                 plaque surface.
        ENGRAVE: Simplified shallow-cut pipeline – geometry is cut into the
                 surface with centred positioning; intended for fine detail
                 such as text.
    """

    CARVE = "carve"
    EMBOSS = "emboss"
    ENGRAVE = "engrave"


@dataclass(frozen=True)
class LayerConfig:
    """Configuration for a single named SVG layer.

    Attributes:
        depth:        Default depth in mm – carve/engrave depth below surface,
                      or emboss height above surface.
        color:        RGBA tuple used for the preview material.
        element_type: Default processing strategy for this layer.  The pipeline
                      may override this per-build via scene properties.
    """

    depth: float
    color: tuple
    element_type: ElementType = ElementType.CARVE


# Maps a layer name prefix to its :class:`LayerConfig`.
# Order is not significant here; ``plaque_builder`` sorts by depth at runtime.
COLOR_MAP: dict = {
    "Water":   LayerConfig(3.0,  (0.0, 0.3, 0.8, 1)),
    "Sand":    LayerConfig(2.4,  (0.9, 0.8, 0.5, 1)),
    "Green":   LayerConfig(1.8,  (0.1, 0.8, 0.1, 1)),
    "Tee":     LayerConfig(1.8,  (0.9, 0.9, 0.9, 1)),
    "Fairway": LayerConfig(1.2,  (0.05, 0.5, 0.05, 1)),
    "Rough":   LayerConfig(0.6,  (0.02, 0.2, 0.02, 1)),
    "Text":    LayerConfig(1.0,  (1.0, 1.0, 1.0, 1), ElementType.EMBOSS),
}