"""Shared configuration constants for the golf plaque generator."""

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

# Extra margin (mm) added to each side when auto-generating a protective frame
# from the Rough boundary.
PROTECTIVE_FRAME_MARGIN = 2.0

# Each entry maps a layer name prefix to (z_depth_from_surface_mm, RGBA_color).
COLOR_MAP = {
    "Water": (3.0, (0.0, 0.3, 0.8, 1)),
    "Sand": (2.4, (0.9, 0.8, 0.5, 1)),
    "Green": (1.8, (0.1, 0.8, 0.1, 1)),
    "Tee": (1.8, (0.9, 0.9, 0.9, 1)),
    "Fairway": (1.2, (0.05, 0.5, 0.05, 1)),
    "Rough": (0.6, (0.02, 0.2, 0.02, 1)),
    "Text": (0.0, (1.0, 1.0, 1.0, 1)),
}