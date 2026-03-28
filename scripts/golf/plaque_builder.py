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
    PLAQUE_BASE_PREFIXES,
    STRAP_HOLE_PREFIXES,
    ElementType,
)
from .cutter_pipeline import (
    apply_boolean_cut,
    apply_solidify_if_present,
    cleanup_base_mesh,
    is_oversized_cutter,
    is_valid_cutter_mesh,
    log_oversized_cutter,
    prepare_strap_hole_cutter,
)
from .element_strategy import BuildContext, get_strategy
from .materials import setup_material
from .svg_utils import find_plaque_base, sanitize_geometry


def _count_present_segments(objects):
    """Count how many carveable segment prefixes are present in the SVG set."""
    carveable_prefixes = [
        prefix
        for prefix, config in COLOR_MAP.items()
        if config.element_type == ElementType.CARVE and config.depth > 0
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


def _resolve_element_type(prefix, layer_config, props):
    """Resolve the effective :class:`~config.ElementType` for *prefix*.

    Most layers use the type declared in :data:`~config.COLOR_MAP`.  The
    ``Text`` prefix additionally honours ``props.text_mode`` so that the UI
    toggle overrides the config-level default.
    """
    if prefix == "Text":
        if getattr(props, "text_mode", "EMBOSS") == "ENGRAVE":
            return ElementType.ENGRAVE
        return ElementType.EMBOSS
    return layer_config.element_type


def carve_plaque(props):
    """Build the base plaque and process each SVG layer through its strategy.

    Args:
        props: Blender scene property group or a
               :class:`~plaque_request.PlaqueRequest` dataclass instance.
    """
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
    if plaque_base_svg is not None:
        base_x = plaque_base_svg.dimensions.x
        base_y = plaque_base_svg.dimensions.y
        move_object_to_collection(plaque_base_svg, output_collection)
        plaque_base_svg.display_type = "WIRE"
        plaque_base_svg.hide_viewport = True
        plaque_base_svg.hide_render = True
    else:
        base_x = props.plaque_width
        base_y = props.plaque_height

    bpy.ops.mesh.primitive_cube_add(size=1)
    base = bpy.context.active_object
    base.name = BASE_OBJECT_NAME
    move_object_to_collection(base, output_collection)
    base.scale = (base_x, base_y, plaque_thickness)
    bpy.ops.object.transform_apply(scale=True)
    base.data.materials.append(setup_material("Rough", COLOR_MAP["Rough"].color))

    ctx = BuildContext(
        base=base,
        plaque_thickness=plaque_thickness,
        base_x=base_x,
        base_y=base_y,
        output_collection=output_collection,
        cutters_collection=cutters_collection,
    )

    # Apply deeper cuts first so overlapping tapered cutters carve into solid
    # material before surrounding shallower layers are removed.
    sorted_items = sorted(
        COLOR_MAP.items(),
        key=lambda item: item[1].depth,
        reverse=True,
    )

    for prefix, layer_config in sorted_items:
        cutters = [obj for obj in all_svg_objs if obj.name.startswith(prefix)]
        if not cutters:
            continue

        mat = setup_material(prefix, layer_config.color)
        element_type = _resolve_element_type(prefix, layer_config, props)
        strategy = get_strategy(element_type)
        strategy.process(cutters, prefix, layer_config, props, ctx, mat)

    strap_holes = [
        obj
        for obj in all_svg_objs
        if any(obj.name.startswith(pre) for pre in STRAP_HOLE_PREFIXES)
    ]

    if getattr(props, "generate_container", False):
        build_container(props, base, strap_holes, output_collection, cutters_collection)

    for strap_hole in strap_holes:
        prepared_cutter = prepare_strap_hole_cutter(strap_hole, plaque_thickness)
        apply_solidify_if_present(prepared_cutter)

        if not is_valid_cutter_mesh(prepared_cutter):
            continue

        if is_oversized_cutter(prepared_cutter, ctx.max_cutter_x, ctx.max_cutter_y):
            log_oversized_cutter(prepared_cutter, ctx.max_cutter_x, ctx.max_cutter_y)
            continue

        apply_boolean_cut(base, prepared_cutter, base_x, base_y, plaque_thickness)
        prepared_cutter.display_type = "WIRE"
        prepared_cutter.hide_render = True

    cleanup_base_mesh(base)

    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

