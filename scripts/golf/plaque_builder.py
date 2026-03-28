"""Plaque construction pipeline for the golf plaque generator."""

import bpy

from .collection_utils import (
    clear_collection,
    ensure_cutters_collection,
    ensure_output_collection,
    move_object_to_collection,
)
from .container_builder import build_container
from .config import (
    BASE_OBJECT_NAME,
    COLOR_MAP,
    CUTTER_EPSILON,
    PLAQUE_BASE_PREFIXES,
    PROTECTIVE_FRAME_MARGIN,
    STRAP_HOLE_PREFIXES,
)
from .cutter_pipeline import (
    apply_solidify_if_present,
    apply_boolean_cut,
    cleanup_base_mesh,
    CUTTER_TOP_POKE_MM,
    duplicate_cutter,
    is_oversized_cutter,
    is_valid_cutter_mesh,
    log_oversized_cutter,
    postprocess_cutter_geometry,
    prepare_active_cutters,
    prepare_strap_hole_cutter,
    resolve_effective_depth,
)
from .materials import setup_material
from .svg_utils import find_plaque_base, sanitize_geometry
from .text_extrusion import extrude_text_objects, engrave_text_objects

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


def _resolve_plaque_thickness(props, objects):
    """Return plaque thickness in mm based on either auto-layer or manual mode."""
    if not getattr(props, "use_auto_thickness", False):
        return props.plaque_thick

    segment_count = _count_present_segments(objects)
    base_layers = max(3, int(props.base_print_layers))
    per_segment_layers = max(1, int(props.segment_print_layers))
    total_layers = base_layers + (segment_count * per_segment_layers)
    return props.print_layer_height * total_layers


def carve_plaque(props):
    """Build the base plaque cube and Boolean-carve each SVG layer into it."""
    output_collection = ensure_output_collection()
    cutters_collection = ensure_cutters_collection()
    clear_collection(output_collection)
    clear_collection(cutters_collection)

    all_known_prefixes = (
        tuple(COLOR_MAP.keys()) + PLAQUE_BASE_PREFIXES + STRAP_HOLE_PREFIXES
    )
    all_svg_objs = [
        obj
        for obj in bpy.data.objects
        if any(obj.name.startswith(pre) for pre in all_known_prefixes)
    ]

    all_svg_objs = sanitize_geometry(all_svg_objs, props, cutters_collection)
    plaque_thickness = _resolve_plaque_thickness(props, all_svg_objs)

    plaque_base_svg = find_plaque_base(all_svg_objs)
    rough_obj = next(
        (o for o in all_svg_objs if o.name.startswith("Rough")), None
    )

    if plaque_base_svg is not None:
        base_x = plaque_base_svg.dimensions.x
        base_y = plaque_base_svg.dimensions.y
        move_object_to_collection(plaque_base_svg, output_collection)
        plaque_base_svg.display_type = "WIRE"
        plaque_base_svg.hide_viewport = True
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
    base.scale = (base_x, base_y, plaque_thickness)
    bpy.ops.object.transform_apply(scale=True)
    base.data.materials.append(setup_material("Rough", COLOR_MAP["Rough"][1]))

    max_cutter_x = base_x * 3.0
    max_cutter_y = base_y * 3.0

    # Apply deeper cuts first so overlapping tapered cutters carve into solid
    # material before surrounding shallower layers are removed.
    sorted_items = sorted(COLOR_MAP.items(), key=lambda item: item[1][0], reverse=True)

    for prefix, (depth, color) in sorted_items:
        # Skip Text objects – they are extruded, not carved
        if prefix == "Text":
            continue

        cutters = [obj for obj in all_svg_objs if obj.name.startswith(prefix)]
        mat = setup_material(prefix, color)

        for cutter in cutters:
            effective_depth = resolve_effective_depth(
                props, prefix, depth, plaque_thickness
            )

            cutter.location.z = plaque_thickness / 2 + CUTTER_TOP_POKE_MM

            (
                active_cutters,
                use_top_taper,
                use_stepped_walls,
            ) = prepare_active_cutters(cutter, props, effective_depth)

            for active_cutter in active_cutters:
                fallback_cutter = None
                if use_top_taper and not use_stepped_walls:
                    fallback_cutter = duplicate_cutter(active_cutter)

                postprocess_cutter_geometry(
                    active_cutter,
                    prefix,
                    props,
                    effective_depth,
                    plaque_thickness,
                    use_top_taper,
                    use_stepped_walls,
                )

                if not active_cutter.data.materials:
                    active_cutter.data.materials.append(mat)

                if not is_valid_cutter_mesh(active_cutter):
                    continue

                if is_oversized_cutter(active_cutter, max_cutter_x, max_cutter_y):
                    log_oversized_cutter(active_cutter, max_cutter_x, max_cutter_y)
                    continue

                cut_applied = apply_boolean_cut(
                    base, active_cutter, base_x, base_y, plaque_thickness
                )

                active_cutter.display_type = "WIRE"
                active_cutter.hide_render = True

                if not cut_applied and fallback_cutter is not None:
                    fallback_cutter.location = active_cutter.location.copy()
                    apply_solidify_if_present(fallback_cutter)

                    if not fallback_cutter.data.materials:
                        fallback_cutter.data.materials.append(mat)

                    if is_valid_cutter_mesh(fallback_cutter) and not is_oversized_cutter(
                        fallback_cutter, max_cutter_x, max_cutter_y
                    ):
                        cut_applied = apply_boolean_cut(
                            base,
                            fallback_cutter,
                            base_x,
                            base_y,
                            plaque_thickness,
                        )

                    fallback_cutter.display_type = "WIRE"
                    fallback_cutter.hide_render = True

                if not cut_applied:
                    continue

    strap_holes = [
        obj for obj in all_svg_objs if any(obj.name.startswith(pre) for pre in STRAP_HOLE_PREFIXES)
    ]

    if getattr(props, "generate_container", False):
        build_container(props, base, strap_holes, output_collection, cutters_collection)

    for strap_hole in strap_holes:
        prepared_cutter = prepare_strap_hole_cutter(strap_hole, plaque_thickness)
        apply_solidify_if_present(prepared_cutter)

        if not is_valid_cutter_mesh(prepared_cutter):
            continue

        if is_oversized_cutter(prepared_cutter, max_cutter_x, max_cutter_y):
            log_oversized_cutter(prepared_cutter, max_cutter_x, max_cutter_y)
            continue

        apply_boolean_cut(base, prepared_cutter, base_x, base_y, plaque_thickness)
        prepared_cutter.display_type = "WIRE"
        prepared_cutter.hide_render = True

    cleanup_base_mesh(base)

    # Process text objects as raised emboss or engraved cuts
    text_objects = [
        obj for obj in all_svg_objs if obj.name.startswith("Text")
    ]
    if text_objects:
        text_material = setup_material("Text", COLOR_MAP["Text"][1])
        if getattr(props, "text_mode", "EMBOSS") == "ENGRAVE":
            engrave_text_objects(
                text_objects,
                base,
                plaque_thickness,
                props.text_extrusion_height,
                text_material,
                cutters_collection,
            )
        else:
            extrude_text_objects(
                text_objects,
                plaque_thickness,
                props.text_extrusion_height,
                text_material,
                output_collection,
            )

    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

