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
from .materials import setup_material
from .svg_utils import find_plaque_base, sanitize_geometry


def carve_plaque(props):
    """Build the base plaque cube and Boolean-carve each SVG layer into it."""
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

    all_svg_objs = sanitize_geometry(all_svg_objs, props, cutters_collection)

    plaque_base_svg = find_plaque_base(all_svg_objs)
    rough_obj = next(
        (o for o in all_svg_objs if o.name.startswith("Rough")), None
    )

    if plaque_base_svg is not None:
        base_x = plaque_base_svg.dimensions.x
        base_y = plaque_base_svg.dimensions.y
        move_object_to_collection(plaque_base_svg, output_collection)
        plaque_base_svg.display_type = "WIRE"
        plaque_base_svg.hide_render = True
    elif props.generate_protective_frame and rough_obj is not None:
        base_x = rough_obj.dimensions.x + PROTECTIVE_FRAME_MARGIN * 2
        base_y = rough_obj.dimensions.y + PROTECTIVE_FRAME_MARGIN * 2
    else:
        base_x = props.plaque_width
        base_y = props.plaque_height

    bpy.ops.mesh.primitive_cube_add(size=1)
    base = bpy.context.active_object
    base.name = BASE_OBJECT_NAME
    move_object_to_collection(base, output_collection)
    base.scale = (base_x, base_y, props.plaque_thick)
    bpy.ops.object.transform_apply(scale=True)
    base.data.materials.append(setup_material("Rough", COLOR_MAP["Rough"][1]))

    sorted_items = sorted(COLOR_MAP.items(), key=lambda item: item[1][0])

    for prefix, (depth, color) in sorted_items:
        cutters = [obj for obj in all_svg_objs if obj.name.startswith(prefix)]
        mat = setup_material(prefix, color)

        for cutter in cutters:
            solidify = cutter.modifiers.new(name="Solidify", type="SOLIDIFY")
            solidify.thickness = depth + CUTTER_EPSILON
            solidify.offset = -1.0

            cutter.location.z = props.plaque_thick / 2 + CUTTER_EPSILON

            if getattr(props, "use_draft_angle", False):
                bpy.context.view_layer.objects.active = cutter
                bpy.ops.object.modifier_apply(modifier="Solidify")
                apply_taper(cutter, props.draft_factor)

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