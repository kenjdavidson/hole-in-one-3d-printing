"""Plaque construction pipeline for the golf plaque generator."""

import bpy

from .collection_utils import (
    clear_collection,
    ensure_cutters_collection,
    ensure_output_collection,
    move_object_to_collection,
)
from .config import (
    BASE_OBJECT_NAME,
    COLOR_MAP,
    CUTTER_EPSILON,
    PLAQUE_BASE_PREFIXES,
    PROTECTIVE_FRAME_MARGIN,
)
from .draft_angle import apply_taper
from .floor_texture import FLOOR_TEXTURE_CONFIG, apply_floor_texture
from .materials import setup_material
from .svg_utils import find_plaque_base, sanitize_geometry
from .utils import get_val

# Maps a layer-name prefix to the corresponding data_source key so that
# depth can be read from either scene properties or a plain dict when
# use_layer_depths is enabled.
_DEPTH_PROP_MAP = {
    "Water": "depth_water",
    "Sand": "depth_sand",
    "Green": "depth_green",
    "Fairway": "depth_fairway",
    "Rough": "depth_rough",
}


def _count_present_segments(objects):
    """Count how many carveable segment prefixes are present in the SVG set."""
    carveable_prefixes = [
        prefix for prefix, (depth, _) in COLOR_MAP.items() if depth > 0
    ]
    return sum(
        1
        for prefix in carveable_prefixes
        if any(obj.name.startswith(prefix) for obj in objects)
    )


def _resolve_plaque_thickness(data_source, objects):
    """Return plaque thickness in mm based on either auto-layer or manual mode."""
    use_auto_thickness = get_val(data_source, "use_auto_thickness", False)
    if not use_auto_thickness:
        return get_val(data_source, "plaque_thick", 6.0)

    segment_count = _count_present_segments(objects)
    base_layers = max(3, int(get_val(data_source, "base_print_layers", 3)))
    per_segment_layers = max(1, int(get_val(data_source, "segment_print_layers", 3)))
    total_layers = base_layers + (segment_count * per_segment_layers)
    return get_val(data_source, "print_layer_height", 0.2) * total_layers


def carve_plaque(data_source):
    """Build the base plaque cube and Boolean-carve each SVG layer into it.

    Args:
        data_source: Either a :class:`bpy.types.PropertyGroup` (Blender Addon
            UI) or a plain :class:`dict` (headless / Docker API).  Both are
            resolved transparently via :func:`~.utils.get_val`.
    """
    output_collection = ensure_output_collection()
    cutters_collection = ensure_cutters_collection()
    clear_collection(output_collection)
    clear_collection(cutters_collection)

    all_known_prefixes = tuple(COLOR_MAP.keys()) + PLAQUE_BASE_PREFIXES
    all_svg_objs = [
        obj
        for obj in bpy.data.objects
        if any(obj.name.startswith(pre) for pre in all_known_prefixes)
    ]

    all_svg_objs = sanitize_geometry(all_svg_objs, data_source, cutters_collection)
    plaque_thickness = _resolve_plaque_thickness(data_source, all_svg_objs)

    plaque_base_svg = find_plaque_base(all_svg_objs)
    rough_obj = next(
        (o for o in all_svg_objs if o.name.startswith("Rough")), None
    )

    plaque_width = get_val(data_source, "plaque_width", 100.0)
    plaque_height = get_val(data_source, "plaque_height", 140.0)
    generate_protective_frame = get_val(data_source, "generate_protective_frame", False)
    use_layer_depths = get_val(data_source, "use_layer_depths", False)
    use_floor_texture = get_val(data_source, "use_floor_texture", False)
    use_draft_angle = get_val(data_source, "use_draft_angle", False)
    draft_factor = get_val(data_source, "draft_factor", 1.1)

    if plaque_base_svg is not None:
        base_x = plaque_base_svg.dimensions.x
        base_y = plaque_base_svg.dimensions.y
        move_object_to_collection(plaque_base_svg, output_collection)
        plaque_base_svg.display_type = "WIRE"
        plaque_base_svg.hide_render = True
    elif generate_protective_frame and rough_obj is not None:
        base_x = rough_obj.dimensions.x + PROTECTIVE_FRAME_MARGIN * 2
        base_y = rough_obj.dimensions.y + PROTECTIVE_FRAME_MARGIN * 2
    else:
        base_x = plaque_width
        base_y = plaque_height

    bpy.ops.mesh.primitive_cube_add(size=1)
    base = bpy.context.active_object
    base.name = BASE_OBJECT_NAME
    move_object_to_collection(base, output_collection)
    base.scale = (base_x, base_y, plaque_thickness)
    bpy.ops.object.transform_apply(scale=True)
    base.data.materials.append(setup_material("Rough", COLOR_MAP["Rough"][1]))

    sorted_items = sorted(COLOR_MAP.items(), key=lambda item: item[1][0])

    for prefix, (depth, color) in sorted_items:
        cutters = [obj for obj in all_svg_objs if obj.name.startswith(prefix)]
        mat = setup_material(prefix, color)

        for cutter in cutters:
            # ── Resolve carve depth ───────────────────────────────────────────
            # When custom layer depths are enabled, read the per-layer value
            # from data_source and clamp it so the cut cannot reach the bottom
            # of the plaque.  Fall back to the COLOR_MAP default when the
            # feature is off or the layer has no dedicated key (e.g. Tee, Text).
            if use_layer_depths and prefix in _DEPTH_PROP_MAP:
                raw_depth = get_val(data_source, _DEPTH_PROP_MAP[prefix], depth)
                # Clamp: leave at least CUTTER_EPSILON of material at the base.
                effective_depth = min(raw_depth, plaque_thickness - CUTTER_EPSILON)
            else:
                effective_depth = depth

            solidify = cutter.modifiers.new(name="Solidify", type="SOLIDIFY")
            solidify.thickness = effective_depth + CUTTER_EPSILON
            solidify.offset = -1.0

            cutter.location.z = plaque_thickness / 2 + CUTTER_EPSILON

            if use_floor_texture and prefix in FLOOR_TEXTURE_CONFIG:
                apply_floor_texture(cutter, prefix, solidify)

            if use_draft_angle:
                bpy.context.view_layer.objects.active = cutter
                bpy.ops.object.modifier_apply(modifier="Solidify")
                apply_taper(cutter, draft_factor)

            if not cutter.data.materials:
                cutter.data.materials.append(mat)

            bool_mod = base.modifiers.new(
                type="BOOLEAN", name=f"Cut_{cutter.name}"
            )
            bool_mod.object = cutter
            bool_mod.operation = "DIFFERENCE"
            bool_mod.solver = "EXACT"

            cutter.display_type = "WIRE"
            cutter.hide_render = True
