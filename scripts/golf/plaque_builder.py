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


def _solidify_plaque_shape(obj, plaque_thickness):
    """Solidify a flat SVG outline to create the 3-D plaque base.

    Applies Weld → Triangulate → Solidify with a symmetric offset so the
    resulting solid spans from ``-plaque_thickness/2`` to
    ``+plaque_thickness/2`` in Z.  This matches the positioning of the
    fallback :func:`bpy.ops.mesh.primitive_cube_add` used when no SVG base
    is present, so all downstream cutter logic remains unchanged.

    Args:
        obj:               The flat Blender mesh object to solidify.
        plaque_thickness:  Full thickness of the resulting solid (mm).
    """
    bpy.context.view_layer.objects.active = obj

    weld = obj.modifiers.new(name="Weld", type="WELD")
    weld.merge_threshold = 0.0001
    bpy.ops.object.modifier_apply(modifier=weld.name)

    tri = obj.modifiers.new(name="Triangulate", type="TRIANGULATE")
    tri.quad_method = "BEAUTY"
    tri.ngon_method = "BEAUTY"
    bpy.ops.object.modifier_apply(modifier=tri.name)

    solidify = obj.modifiers.new(name="Solidify", type="SOLIDIFY")
    solidify.thickness = plaque_thickness
    # offset=0 extrudes symmetrically: z from -thick/2 to +thick/2,
    # matching the cube primitive used in the fallback path.
    solidify.offset = 0.0
    solidify.use_even_offset = False
    solidify.use_quality_normals = True
    bpy.ops.object.modifier_apply(modifier=solidify.name)


def carve_plaque(props):
    """Build the base plaque and process each SVG layer through its strategy.

    When a ``Plaque_Base`` or ``Plaque_Frame`` SVG object is present in the
    scene its outline is solidified and used **directly** as the 3-D base,
    so any shape drawn in Inkscape (rectangle, rounded rectangle, circle,
    custom polygon …) is faithfully reproduced in the final plaque.

    When no such SVG object is found a primitive is created from the manual
    dimension properties.  ``plaque_shape == "CIRCLE"`` produces a cylinder
    (diameter = ``min(plaque_width, plaque_height)``); ``"RECTANGLE"``
    (default) produces the classic rectangular slab.

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
        # Use the SVG outline directly as the base shape.  This supports any
        # shape the designer provides — rectangles, rounded rectangles,
        # circles, or fully custom outlines.
        base_x = plaque_base_svg.dimensions.x
        base_y = plaque_base_svg.dimensions.y
        move_object_to_collection(plaque_base_svg, output_collection)
        _solidify_plaque_shape(plaque_base_svg, plaque_thickness)
        base = plaque_base_svg
        base.name = BASE_OBJECT_NAME
    else:
        base_x = props.plaque_width
        base_y = props.plaque_height
        plaque_shape = getattr(props, "plaque_shape", "RECTANGLE")
        if plaque_shape == "CIRCLE":
            radius = min(base_x, base_y) / 2.0
            # Clamp both dimensions to the actual circle diameter so that the
            # BuildContext oversized-cutter limits are calculated correctly.
            base_x = radius * 2.0
            base_y = radius * 2.0
            bpy.ops.mesh.primitive_cylinder_add(
                radius=radius,
                depth=plaque_thickness,
                vertices=64,
            )
            base = bpy.context.active_object
        else:
            bpy.ops.mesh.primitive_cube_add(size=1)
            base = bpy.context.active_object
            base.scale = (base_x, base_y, plaque_thickness)
            bpy.ops.object.transform_apply(scale=True)
        base.name = BASE_OBJECT_NAME
        move_object_to_collection(base, output_collection)

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

