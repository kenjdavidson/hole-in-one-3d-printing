"""Insert-layer construction pipeline for the golf plaque generator.

Builds a set of printable **insert pieces** from SVG golf-course traces.
Each terrain element (Water, Sand, Green, Tee, Fairway, Rough) becomes a
raised slab that fits into a matching hole in its parent layer:

.. code-block:: text

    Base ← Rough insert (has holes for Fairway, Sand, Green, Tee, Water)
               └── Fairway insert (has holes for Green, Tee, Sand, Water)
                       └── Green  insert  (has holes for Water)
                       └── Tee    insert  (has holes for Water)
                       └── Sand   insert  (has holes for Water)
                               └── Water  insert  (innermost, no holes)

Each insert sits slightly smaller than its receiving hole (controlled by
``props.insert_clearance`` and ``props.use_shrink_element``) so it can be
glued in place to create a multi-colour, raised, layered design.

This pipeline is deliberately separate from :mod:`plaque_builder` so that
the two workflows can evolve independently and can be triggered from distinct
operators or API endpoints.
"""

import bpy

from .collection_utils import (
    clear_collection,
    ensure_cutters_collection,
    ensure_inserts_collection,
    move_object_to_collection,
)
from .config import (
    BASE_OBJECT_NAME,
    COLOR_MAP,
    CUTTER_EPSILON,
    ElementType,
    PLAQUE_BASE_PREFIXES,
    STRAP_HOLE_PREFIXES,
)
from .cutter_pipeline import (
    CUTTER_TOP_POKE_MM,
    cleanup_base_mesh,
    is_valid_cutter_mesh,
)
from .draft_angle import apply_flat_inset, apply_flat_outset
from .materials import setup_material
from .svg_utils import find_plaque_base, sanitize_geometry

# Horizontal gap between adjacent insert display objects (mm).
_INSERT_DISPLAY_GAP_MM = 10.0


def _carveable_layers_sorted():
    """Return CARVE-type layers sorted by depth ascending (shallowest / outermost first)."""
    return sorted(
        [
            (prefix, config)
            for prefix, config in COLOR_MAP.items()
            if config.element_type == ElementType.CARVE
        ],
        key=lambda item: item[1].depth,
    )


def _duplicate_mesh_obj(source, name, collection):
    """Return a standalone mesh copy of *source*, linked to *collection*."""
    dup = source.copy()
    if source.data is not None:
        dup.data = source.data.copy()
    dup.name = name
    collection.objects.link(dup)
    return dup


def _apply_solidify_and_bake(obj, thickness, offset=-1.0):
    """Add a Solidify modifier to *obj* and immediately apply it.

    Args:
        obj:       The Blender mesh object to solidify.
        thickness: Solidify thickness in mm.
        offset:    Solidify offset direction (``-1.0`` = extend downward from
                   the original face; ``1.0`` = extend upward).
    """
    solidify = obj.modifiers.new(name="Solidify", type="SOLIDIFY")
    solidify.thickness = thickness
    solidify.offset = offset
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=solidify.name)


def _boolean_subtract(target, cutter):
    """Apply a Boolean difference from *cutter* into *target*."""
    mod = target.modifiers.new(
        type="BOOLEAN", name=f"InsertCut_{cutter.name}"
    )
    mod.object = cutter
    mod.operation = "DIFFERENCE"
    mod.solver = "EXACT"
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.modifier_apply(modifier=mod.name)


def build_inserts(props):
    """Generate printable insert pieces from the imported SVG golf-course layers.

    For each CARVE-type terrain layer present in the scene (Rough, Fairway,
    Green, Tee, Sand, Water) this function produces:

    * A **base plaque** with a receiving hole sized to the outermost terrain
      element's outline.
    * One **insert slab** per terrain element, sized smaller than its receiving
      hole by ``props.insert_clearance``, with through-holes cut for every
      deeper / inner terrain element.

    All generated objects are placed in the ``Hole_In_One_Inserts`` collection.

    The layers are processed in the order determined by their ``depth`` value
    in :data:`~config.COLOR_MAP`: shallowest layers (e.g. Rough at 0.6 mm) are
    the outermost pieces; deepest layers (e.g. Water at 3.0 mm) are the
    innermost pieces.  This naturally satisfies the requirement that
    water/hazards always cut through all surrounding elements.

    Args:
        props: A Blender scene property group (``HOLEINONE_InsertProperties``)
               or an :class:`~insert_request.InsertRequest` dataclass instance.
    """
    inserts_collection = ensure_inserts_collection()
    cutters_collection = ensure_cutters_collection()
    clear_collection(inserts_collection)
    clear_collection(cutters_collection)

    element_height = (
        max(1, int(props.insert_element_layers)) * float(props.print_layer_height)
    )
    hole_depth = (
        max(1, int(props.insert_hole_layers)) * float(props.print_layer_height)
    )
    clearance = float(max(0.0, props.insert_clearance))
    use_shrink = getattr(props, "use_shrink_element", True)

    # ── Collect and sanitize SVG objects ────────────────────────────────────
    all_known_prefixes = (
        tuple(COLOR_MAP.keys()) + PLAQUE_BASE_PREFIXES + STRAP_HOLE_PREFIXES
    )
    all_svg_objs = [
        obj
        for obj in bpy.data.objects
        if any(obj.name.startswith(pre) for pre in all_known_prefixes)
    ]
    all_svg_objs = sanitize_geometry(all_svg_objs, props, cutters_collection)

    # ── Determine layers present in the SVG ─────────────────────────────────
    ordered_layers = _carveable_layers_sorted()
    present_layers = [
        (prefix, config)
        for prefix, config in ordered_layers
        if any(obj.name.startswith(prefix) for obj in all_svg_objs)
    ]

    if not present_layers:
        print("[golf_tools] No carveable SVG layers found; insert build skipped.")
        return

    # ── Determine plaque dimensions ──────────────────────────────────────────
    plaque_base_svg = find_plaque_base(all_svg_objs)
    if plaque_base_svg is not None:
        base_x = plaque_base_svg.dimensions.x
        base_y = plaque_base_svg.dimensions.y
    else:
        base_x = float(props.plaque_width)
        base_y = float(props.plaque_height)

    plaque_thick = float(props.plaque_thick)

    # ── Build the base plaque with a receiving hole for the outermost layer ─
    bpy.ops.mesh.primitive_cube_add(size=1)
    base = bpy.context.active_object
    base.name = f"{BASE_OBJECT_NAME}_Inserts"
    move_object_to_collection(base, inserts_collection)
    base.scale = (base_x, base_y, plaque_thick)
    bpy.ops.object.transform_apply(scale=True)

    outermost_prefix, _ = present_layers[0]
    outermost_svgs = [
        obj for obj in all_svg_objs if obj.name.startswith(outermost_prefix)
    ]

    for svg_src in outermost_svgs:
        hole_cutter = _duplicate_mesh_obj(
            svg_src,
            f"_InsertBaseHole_{outermost_prefix}",
            cutters_collection,
        )
        if not use_shrink and clearance > 0.0:
            # When growing holes rather than shrinking inserts, expand the
            # base hole so the outermost insert fits with clearance.
            apply_flat_outset(hole_cutter, clearance)
        # Position cutter at the top surface of the base and extend downward.
        hole_cutter.location.z = plaque_thick / 2.0 + CUTTER_TOP_POKE_MM
        _apply_solidify_and_bake(
            hole_cutter,
            hole_depth + CUTTER_TOP_POKE_MM + CUTTER_EPSILON,
            offset=-1.0,
        )
        if is_valid_cutter_mesh(hole_cutter):
            _boolean_subtract(base, hole_cutter)
        hole_cutter.display_type = "WIRE"
        hole_cutter.hide_render = True

    cleanup_base_mesh(base)

    # ── Build an insert slab for each terrain layer ──────────────────────────
    # Start display offset to the right of the base plaque.
    display_x_offset = base_x / 2.0 + _INSERT_DISPLAY_GAP_MM

    for layer_index, (prefix, config) in enumerate(present_layers):
        svg_sources = [obj for obj in all_svg_objs if obj.name.startswith(prefix)]
        if not svg_sources:
            continue

        mat = setup_material(prefix, config.color)
        insert_pieces = []
        max_piece_width = 0.0

        for piece_index, svg_src in enumerate(svg_sources):
            insert = _duplicate_mesh_obj(
                svg_src,
                f"Insert_{prefix}_{piece_index:02d}",
                inserts_collection,
            )

            # Apply clearance: shrink the insert so it fits in its parent hole.
            if use_shrink and clearance > 0.0:
                apply_flat_inset(insert, clearance)

            # Extrude the flat outline upward to element_height.
            # offset = 1.0 → original face (Z=0) becomes the bottom face;
            # the solidify extends upward.
            _apply_solidify_and_bake(insert, element_height, offset=1.0)

            if not insert.data.materials:
                insert.data.materials.append(mat)

            # ── Cut through-holes for all deeper (inner) elements ────────────
            # Layers are sorted shallowest→deepest so everything after
            # layer_index is geometrically "inside" the current element.
            deeper_layers = present_layers[layer_index + 1 :]
            for inner_prefix, _ in deeper_layers:
                inner_sources = [
                    obj
                    for obj in all_svg_objs
                    if obj.name.startswith(inner_prefix)
                ]
                for inner_index, inner_src in enumerate(inner_sources):
                    inner_cutter = _duplicate_mesh_obj(
                        inner_src,
                        f"_InsertHole_{prefix}_{inner_prefix}_{inner_index:02d}",
                        cutters_collection,
                    )
                    # When growing holes rather than shrinking inserts, expand
                    # the inner cutout so the child insert fits with clearance.
                    if not use_shrink and clearance > 0.0:
                        apply_flat_outset(inner_cutter, clearance)
                    # Position the cutter above the insert top and extend
                    # downward through the full element height plus margins.
                    inner_cutter.location.z = element_height + CUTTER_TOP_POKE_MM
                    _apply_solidify_and_bake(
                        inner_cutter,
                        element_height + CUTTER_TOP_POKE_MM * 2.0,
                        offset=-1.0,
                    )
                    if is_valid_cutter_mesh(inner_cutter):
                        _boolean_subtract(insert, inner_cutter)
                    inner_cutter.display_type = "WIRE"
                    inner_cutter.hide_render = True

            insert_pieces.append(insert)
            if insert.dimensions.x > max_piece_width:
                max_piece_width = insert.dimensions.x

        # ── Offset inserts for display ────────────────────────────────────────
        # Insert mesh data is already centered; advance each layer rightward.
        for insert_piece in insert_pieces:
            insert_piece.location.x += display_x_offset

        display_x_offset += max_piece_width + _INSERT_DISPLAY_GAP_MM

    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    print(
        "[golf_tools] Insert build complete --",
        len(present_layers), "layers,",
        "element_height=", round(element_height, 3), "mm,",
        "hole_depth=", round(hole_depth, 3), "mm,",
        "clearance=", round(clearance, 3), "mm",
        "(shrink_element=", use_shrink, ")",
    )
