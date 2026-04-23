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

import bmesh
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
from .container_builder import build_container
from .cutter_pipeline import (
    CUTTER_TOP_POKE_MM,
    cleanup_base_mesh,
    is_valid_cutter_mesh,
)
from .draft_angle import apply_flat_inset, apply_flat_outset
from .element_strategy import BuildContext, get_strategy
from .materials import setup_material
from .svg_utils import find_plaque_base, sanitize_geometry

# Horizontal gap between adjacent insert display objects (mm).
_INSERT_DISPLAY_GAP_MM = 10.0
# Extra clearance between the base and the first displayed insert (mm).
_BASE_INSERT_START_CLEARANCE_MM = 0.5
_BORDER_SOCKET_MIN_WIDTH_MM = 0.05


def _dispose_temp_object(obj):
    """Remove an unlinked temporary object and its mesh datablock if orphaned."""
    if obj is None:
        return

    # Keep cleanup conservative for Blender stability: remove object only.
    if obj.name in bpy.data.objects:
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except RuntimeError:
            pass


def _xy_segments_intersect(p1, p2, q1, q2, eps=1e-9):
    """Return True when two XY line segments intersect (including collinear overlap)."""

    def _orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def _on_segment(a, b, c):
        return (
            min(a[0], b[0]) - eps <= c[0] <= max(a[0], b[0]) + eps
            and min(a[1], b[1]) - eps <= c[1] <= max(a[1], b[1]) + eps
        )

    o1 = _orient(p1, p2, q1)
    o2 = _orient(p1, p2, q2)
    o3 = _orient(q1, q2, p1)
    o4 = _orient(q1, q2, p2)

    if (o1 > eps and o2 < -eps or o1 < -eps and o2 > eps) and (
        o3 > eps and o4 < -eps or o3 < -eps and o4 > eps
    ):
        return True

    if abs(o1) <= eps and _on_segment(p1, p2, q1):
        return True
    if abs(o2) <= eps and _on_segment(p1, p2, q2):
        return True
    if abs(o3) <= eps and _on_segment(q1, q2, p1):
        return True
    if abs(o4) <= eps and _on_segment(q1, q2, p2):
        return True
    return False


def _has_xy_self_intersections(obj):
    """Detect non-adjacent edge intersections in a flat XY outline mesh."""
    if obj is None or obj.data is None:
        return False

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    edges = list(bm.edges)
    edge_count = len(edges)
    if edge_count < 4:
        bm.free()
        return False

    intersections_found = False
    for idx_a in range(edge_count):
        edge_a = edges[idx_a]
        a1 = (edge_a.verts[0].co.x, edge_a.verts[0].co.y)
        a2 = (edge_a.verts[1].co.x, edge_a.verts[1].co.y)
        verts_a = {edge_a.verts[0], edge_a.verts[1]}

        for idx_b in range(idx_a + 1, edge_count):
            edge_b = edges[idx_b]
            # Adjacent edges are expected to meet; ignore those pairs.
            if edge_b.verts[0] in verts_a or edge_b.verts[1] in verts_a:
                continue

            b1 = (edge_b.verts[0].co.x, edge_b.verts[0].co.y)
            b2 = (edge_b.verts[1].co.x, edge_b.verts[1].co.y)
            if _xy_segments_intersect(a1, a2, b1, b2):
                intersections_found = True
                break

        if intersections_found:
            break

    bm.free()
    return intersections_found


def _apply_flat_inset_safe(obj, inset_mm):
    """Inset with rollback when the resulting outline self-intersects."""
    if obj is None or obj.data is None or inset_mm <= 0.0:
        return False

    original_coords = [vertex.co.copy() for vertex in obj.data.vertices]
    apply_flat_inset(obj, inset_mm)

    if _has_xy_self_intersections(obj):
        for vertex, original in zip(obj.data.vertices, original_coords):
            vertex.co = original
        obj.data.update()
        return False

    return True


def _apply_flat_outset_safe(obj, outset_mm):
    """Outset with rollback when the resulting outline self-intersects."""
    if obj is None or obj.data is None or outset_mm <= 0.0:
        return False

    original_coords = [vertex.co.copy() for vertex in obj.data.vertices]
    apply_flat_outset(obj, outset_mm)

    if _has_xy_self_intersections(obj):
        for vertex, original in zip(obj.data.vertices, original_coords):
            vertex.co = original
        obj.data.update()
        return False

    return True


def _apply_uniform_xy_shrink(obj, per_side_mm):
    """Uniformly shrink a flat XY outline about its centroid by per-side mm."""
    if obj is None or obj.data is None or per_side_mm <= 0.0:
        return 0.0

    vertices = getattr(obj.data, "vertices", None)
    if not vertices:
        return 0.0

    min_x = min(vertex.co.x for vertex in vertices)
    max_x = max(vertex.co.x for vertex in vertices)
    min_y = min(vertex.co.y for vertex in vertices)
    max_y = max(vertex.co.y for vertex in vertices)

    width = max_x - min_x
    height = max_y - min_y
    if width <= 1e-9 or height <= 1e-9:
        return 0.0

    # Prevent pathological collapse on very thin islands.
    max_per_side = min(width, height) * 0.45
    applied = min(per_side_mm, max_per_side)
    if applied <= 0.0:
        return 0.0

    scale_x = max(0.01, (width - (2.0 * applied)) / width)
    scale_y = max(0.01, (height - (2.0 * applied)) / height)
    center_x = (min_x + max_x) * 0.5
    center_y = (min_y + max_y) * 0.5

    for vertex in vertices:
        vertex.co.x = center_x + (vertex.co.x - center_x) * scale_x
        vertex.co.y = center_y + (vertex.co.y - center_y) * scale_y

    obj.data.update()
    return applied


def _find_max_safe_inset(source_obj, target_inset_mm, iterations=12):
    """Return the largest inset <= target that avoids outline self-intersection."""
    if source_obj is None or source_obj.data is None or target_inset_mm <= 0.0:
        return 0.0

    # Fast path: requested clearance already works.
    temp_obj = source_obj.copy()
    temp_obj.data = source_obj.data.copy()
    try:
        if _apply_flat_inset_safe(temp_obj, target_inset_mm):
            return target_inset_mm
    finally:
        _dispose_temp_object(temp_obj)

    # Binary search for the largest safe inset.
    low = 0.0
    high = target_inset_mm
    best = 0.0

    for _ in range(max(1, int(iterations))):
        mid = (low + high) * 0.5
        temp_obj = source_obj.copy()
        temp_obj.data = source_obj.data.copy()
        try:
            if _apply_flat_inset_safe(temp_obj, mid):
                best = mid
                low = mid
            else:
                high = mid
        finally:
            _dispose_temp_object(temp_obj)

    return best


def _find_max_safe_outset(source_obj, target_outset_mm, iterations=12):
    """Return the largest outset <= target that avoids outline self-intersection."""
    if source_obj is None or source_obj.data is None or target_outset_mm <= 0.0:
        return 0.0

    # Fast path: requested compensation already works.
    temp_obj = source_obj.copy()
    temp_obj.data = source_obj.data.copy()
    try:
        if _apply_flat_outset_safe(temp_obj, target_outset_mm):
            return target_outset_mm
    finally:
        _dispose_temp_object(temp_obj)

    # Binary search for the largest safe outset.
    low = 0.0
    high = target_outset_mm
    best = 0.0

    for _ in range(max(1, int(iterations))):
        mid = (low + high) * 0.5
        temp_obj = source_obj.copy()
        temp_obj.data = source_obj.data.copy()
        try:
            if _apply_flat_outset_safe(temp_obj, mid):
                best = mid
                low = mid
            else:
                high = mid
        finally:
            _dispose_temp_object(temp_obj)

    return best


def _get_source_inset_amount(source_obj, source_clearance_map, default_clearance):
    """Return the effective inset used for a source object (mm)."""
    if source_obj is None:
        return 0.0
    return float(source_clearance_map.get(source_obj.name, default_clearance))


def _extract_name_layer_number(object_name):
    """Return numeric layer parsed from object name tokens like *.001.*."""
    if not object_name:
        return None

    parts = str(object_name).split(".")
    for token in parts[1:]:
        if token.isdigit():
            return int(token)
    return None


def _source_name(obj):
    """Return stable imported object name preserved during sanitize step."""
    if obj is None:
        return ""
    return str(obj.get("_golf_src_name", obj.name))


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
    if obj.data is None:
        return

    # Remove duplicate boundary vertices and triangulate n-gons before
    # solidify. Imported SVG meshes can contain coincident points and holed
    # n-gons that trigger one-off downward spikes on concave outlines.
    bpy.context.view_layer.objects.active = obj
    weld = obj.modifiers.new(name="Weld", type="WELD")
    weld.merge_threshold = 0.0001
    bpy.ops.object.modifier_apply(modifier=weld.name)

    tri = obj.modifiers.new(name="Triangulate", type="TRIANGULATE")
    tri.quad_method = "BEAUTY"
    tri.ngon_method = "BEAUTY"
    bpy.ops.object.modifier_apply(modifier=tri.name)

    solidify = obj.modifiers.new(name="Solidify", type="SOLIDIFY")
    solidify.thickness = thickness
    solidify.offset = offset
    # Even-offset can generate extreme spikes at sharp concave corners.
    solidify.use_even_offset = False
    solidify.use_quality_normals = True
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


def _boolean_union(target, operand, name_prefix="InsertUnion"):
    """Apply a Boolean union from *operand* into *target*."""
    mod = target.modifiers.new(type="BOOLEAN", name=f"{name_prefix}_{operand.name}")
    mod.object = operand
    mod.operation = "UNION"
    mod.solver = "EXACT"
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.modifier_apply(modifier=mod.name)


def _cleanup_insert_mesh(obj):
    """Repair common mesh artefacts that can manifest as extrusion spikes."""
    if obj is None or obj.data is None:
        return

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    if not bm.verts:
        bm.free()
        return

    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)
    bmesh.ops.dissolve_degenerate(bm, dist=0.000001, edges=bm.edges)

    loose_verts = [vertex for vertex in bm.verts if not vertex.link_edges]
    if loose_verts:
        bmesh.ops.delete(bm, geom=loose_verts, context="VERTS")

    loose_edges = [edge for edge in bm.edges if not edge.link_faces]
    if loose_edges:
        bmesh.ops.delete(bm, geom=loose_edges, context="EDGES")

    if bm.faces:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def _enforce_insert_z_bounds(obj, min_z, max_z):
    """Clamp insert-vertex Z values to the expected printable band."""
    if obj is None or obj.data is None:
        return

    for vertex in obj.data.vertices:
        if vertex.co.z < min_z:
            vertex.co.z = min_z
        elif vertex.co.z > max_z:
            vertex.co.z = max_z
    obj.data.update()


def _resolve_text_element_type(props):
    """Return EMBOSS/ENGRAVE mode for Text based on user settings."""
    if getattr(props, "text_mode", "EMBOSS") == "ENGRAVE":
        return ElementType.ENGRAVE
    return ElementType.EMBOSS


def _create_circle_outline_obj(name, radius, collection):
    """Create a flat filled-circle mesh object centered at the origin.

    Used by :func:`_create_border_outline_objects` when the plaque shape is
    ``"CIRCLE"`` and no SVG base outline is available.

    Args:
        name:       Object name.
        radius:     Circle radius in mm.
        collection: Blender collection to link the new object into.

    Returns:
        The newly created Blender mesh object, or ``None`` if *radius* <= 0.
    """
    if radius <= 0:
        return None
    bpy.ops.mesh.primitive_circle_add(vertices=64, radius=radius, fill_type="TRIFAN")
    obj = bpy.context.active_object
    obj.name = name
    move_object_to_collection(obj, collection)
    obj.location = (0.0, 0.0, 0.0)
    return obj


def _create_border_outline_objects(
    base_x,
    base_y,
    plaque_base_svg,
    collection,
    outer_name,
    inner_name,
    outer_inset,
    inner_inset,
    plaque_shape="RECTANGLE",
):
    """Create flat outer/inner border outline objects from plaque geometry.

    When *plaque_base_svg* is provided its outline is duplicated and inset to
    produce the two rings — this supports any SVG shape.

    When no SVG is available the outlines are created from the manual
    dimensions.  ``plaque_shape == "CIRCLE"`` produces filled-circle outlines;
    ``"RECTANGLE"`` (default) produces the existing rectangular cubes.
    """
    if inner_inset <= outer_inset + _BORDER_SOCKET_MIN_WIDTH_MM:
        return None, None

    if plaque_base_svg is not None:
        outer_obj = _duplicate_mesh_obj(plaque_base_svg, outer_name, collection)
        if outer_inset > 0.0 and not _apply_flat_inset_safe(outer_obj, outer_inset):
            _dispose_temp_object(outer_obj)
            return None, None

        inner_obj = _duplicate_mesh_obj(plaque_base_svg, inner_name, collection)
        if inner_inset > 0.0 and not _apply_flat_inset_safe(inner_obj, inner_inset):
            _dispose_temp_object(outer_obj)
            _dispose_temp_object(inner_obj)
            return None, None
        return outer_obj, inner_obj

    if plaque_shape == "CIRCLE":
        base_radius = min(float(base_x), float(base_y)) / 2.0
        outer_radius = base_radius - outer_inset
        inner_radius = base_radius - inner_inset
        if outer_radius <= 0.0 or inner_radius <= 0.0 or inner_radius >= outer_radius:
            return None, None
        outer_obj = _create_circle_outline_obj(outer_name, outer_radius, collection)
        inner_obj = _create_circle_outline_obj(inner_name, inner_radius, collection)
        if outer_obj is None or inner_obj is None:
            _dispose_temp_object(outer_obj)
            _dispose_temp_object(inner_obj)
            return None, None
        return outer_obj, inner_obj

    outer_x = float(base_x) - (2.0 * outer_inset)
    outer_y = float(base_y) - (2.0 * outer_inset)
    inner_x = float(base_x) - (2.0 * inner_inset)
    inner_y = float(base_y) - (2.0 * inner_inset)
    if min(outer_x, outer_y, inner_x, inner_y) <= 0.0:
        return None, None
    if inner_x >= outer_x or inner_y >= outer_y:
        return None, None

    bpy.ops.mesh.primitive_cube_add(size=1)
    outer_obj = bpy.context.active_object
    outer_obj.name = outer_name
    move_object_to_collection(outer_obj, collection)
    outer_obj.scale = (outer_x, outer_y, 1.0)
    bpy.ops.object.transform_apply(scale=True)
    outer_obj.location = (0.0, 0.0, 0.0)

    bpy.ops.mesh.primitive_cube_add(size=1)
    inner_obj = bpy.context.active_object
    inner_obj.name = inner_name
    move_object_to_collection(inner_obj, collection)
    inner_obj.scale = (inner_x, inner_y, 1.0)
    bpy.ops.object.transform_apply(scale=True)
    inner_obj.location = (0.0, 0.0, 0.0)
    return outer_obj, inner_obj


def _solidify_border_ring(outer_obj, inner_obj, thickness, z_location):
    """Turn flat outer/inner outlines into a ring mesh at the target Z."""
    _apply_solidify_and_bake(outer_obj, thickness, offset=1.0)
    _cleanup_insert_mesh(outer_obj)
    outer_obj.location.z = z_location

    _apply_solidify_and_bake(inner_obj, thickness + CUTTER_TOP_POKE_MM + CUTTER_EPSILON, offset=1.0)
    _cleanup_insert_mesh(inner_obj)
    inner_obj.location.z = z_location - CUTTER_TOP_POKE_MM

    _boolean_subtract(outer_obj, inner_obj)
    _cleanup_insert_mesh(outer_obj)
    _dispose_temp_object(inner_obj)
    return outer_obj


def _apply_text_to_base(
    props,
    all_svg_objs,
    base,
    plaque_thick,
    base_x,
    base_y,
    inserts_collection,
    cutters_collection,
):
    """Apply Text.* objects to the insert base using emboss/engrave strategies."""
    text_config = COLOR_MAP.get("Text")
    if text_config is None:
        return 0

    text_objs = [obj for obj in all_svg_objs if obj.name.startswith("Text")]
    if not text_objs:
        return 0

    text_material = setup_material("Text", text_config.color)
    ctx = BuildContext(
        base=base,
        plaque_thickness=plaque_thick,
        base_x=base_x,
        base_y=base_y,
        output_collection=inserts_collection,
        cutters_collection=cutters_collection,
    )
    strategy = get_strategy(_resolve_text_element_type(props))
    strategy.process(text_objs, "Text", text_config, props, ctx, text_material)
    return len(text_objs)


def _apply_embossed_border_to_base(
    props,
    base,
    plaque_thick,
    base_x,
    base_y,
    plaque_base_svg,
    inserts_collection,
    cutters_collection,
    border_socket_depth,
    plaque_shape="RECTANGLE",
):
    """Optionally add a raised border ring to the insert base."""
    if not getattr(props, "use_embossed_border", False):
        return False, []

    border_height = float(max(0.0, getattr(props, "text_extrusion_height", 0.0)))
    border_inset = float(max(0.0, getattr(props, "border_inset", 0.0)))
    border_width = float(max(0.0, getattr(props, "border_width", 0.8)))
    separate_border_insert = bool(getattr(props, "separate_border_insert", False))

    if border_height <= 0.0 or border_width <= 0.0:
        print("[golf_tools] Embossed border skipped: non-positive height/width")
        return False, []

    inner_inset = border_inset + border_width
    border_pieces = []
    text_cfg = COLOR_MAP.get("Text")

    if separate_border_insert:
        fit_clearance = float(max(0.0, getattr(props, "insert_clearance", 0.0)))
        if getattr(props, "use_shrink_element", True):
            piece_outer_inset = border_inset + fit_clearance
            piece_inner_inset = inner_inset - fit_clearance
            pocket_outer_inset = border_inset
            pocket_inner_inset = inner_inset
        else:
            piece_outer_inset = border_inset
            piece_inner_inset = inner_inset
            pocket_outer_inset = max(0.0, border_inset - fit_clearance)
            pocket_inner_inset = inner_inset + fit_clearance

        piece_outer, piece_inner = _create_border_outline_objects(
            base_x,
            base_y,
            plaque_base_svg,
            inserts_collection,
            "Insert_Base_Border",
            "_Insert_Base_BorderInnerCut",
            piece_outer_inset,
            piece_inner_inset,
            plaque_shape,
        )
        if piece_outer is None or piece_inner is None:
            print("[golf_tools] Separate border skipped: invalid border insert geometry")
            return False, []

        piece_thickness = border_height + border_socket_depth
        border_obj = _solidify_border_ring(piece_outer, piece_inner, piece_thickness, 0.0)
        border_pieces.append(border_obj)

        pocket_outer, pocket_inner = _create_border_outline_objects(
            base_x,
            base_y,
            plaque_base_svg,
            cutters_collection,
            "_Insert_Base_BorderPocket",
            "_Insert_Base_BorderPocketInnerCut",
            pocket_outer_inset,
            pocket_inner_inset,
            plaque_shape,
        )
        if pocket_outer is None or pocket_inner is None:
            print("[golf_tools] Separate border skipped: invalid border pocket geometry")
            _dispose_temp_object(border_obj)
            return False, []

        pocket_cutter = _solidify_border_ring(
            pocket_outer,
            pocket_inner,
            border_socket_depth + CUTTER_TOP_POKE_MM + CUTTER_EPSILON,
            plaque_thick / 2.0 - border_socket_depth,
        )
        if is_valid_cutter_mesh(pocket_cutter):
            _boolean_subtract(base, pocket_cutter)
        pocket_cutter.display_type = "WIRE"
        pocket_cutter.hide_render = True
    else:
        border_outer, inner_cutter = _create_border_outline_objects(
            base_x,
            base_y,
            plaque_base_svg,
            inserts_collection,
            "Insert_Base_Border",
            "_Insert_Base_BorderInnerCut",
            border_inset,
            inner_inset,
            plaque_shape,
        )
        if border_outer is None or inner_cutter is None:
            print("[golf_tools] Embossed border skipped: invalid border geometry")
            return False, []

        border_obj = _solidify_border_ring(
            border_outer,
            inner_cutter,
            border_height,
            plaque_thick / 2.0,
        )
        _boolean_union(base, border_obj, name_prefix="InsertBorder")
        border_obj.hide_render = True

    if text_cfg is not None and not border_obj.data.materials:
        border_obj.data.materials.append(setup_material("Text", text_cfg.color))

    print(
        "[golf_tools] Embossed border added:",
        "inset=", round(border_inset, 3),
        "width=", round(border_width, 3),
        "height=", round(border_height, 3),
        "separate=", separate_border_insert,
    )
    return True, border_pieces


def build_inserts(props):
    """Generate printable insert pieces from the imported SVG golf-course layers.

    For each CARVE-type terrain layer present in the scene (Rough, Fairway,
    Green, Tee, Sand, Water) this function produces:

    * A **base plaque** with a receiving hole sized to the outermost terrain
      element's outline.
        * One **insert slab** per terrain element, sized smaller than its receiving
            hole by ``props.insert_clearance``, with receiving pockets cut for every
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
    effective_hole_depth = min(hole_depth, element_height)
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

    source_clearance_map = {}
    source_compensation_map = {}
    source_extra_shrink_map = {}
    source_extra_shrink_applied_map = {}
    fit_validation_rows = []
    fit_compromises_made = False
    fit_compromise_rows = []
    if use_shrink and clearance > 0.0:
        adjusted_sources = []
        for prefix, _ in present_layers:
            for source in (obj for obj in all_svg_objs if obj.name.startswith(prefix)):
                safe_clearance = _find_max_safe_inset(source, clearance)
                source_clearance_map[source.name] = safe_clearance
                compensation_needed = max(0.0, clearance - safe_clearance)
                safe_compensation = 0.0
                if compensation_needed > 0.0:
                    safe_compensation = _find_max_safe_outset(source, compensation_needed)
                source_compensation_map[source.name] = safe_compensation

                achieved_clearance = safe_clearance + safe_compensation
                source_extra_shrink_map[source.name] = max(0.0, clearance - achieved_clearance)

                if safe_clearance + 1e-6 < clearance:
                    adjusted_sources.append((_source_name(source), safe_clearance))

        if adjusted_sources:
            print("[golf_tools] Clearance reduced for invalid inset outlines:")
            for source_name, safe_clearance in sorted(adjusted_sources):
                print(
                    "  -",
                    source_name,
                    "requested=",
                    round(clearance, 4),
                    "applied=",
                    round(safe_clearance, 4),
                )

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
        plaque_shape = getattr(props, "plaque_shape", "RECTANGLE")
        if plaque_shape == "CIRCLE":
            radius = min(base_x, base_y) / 2.0
            # Clamp both dimensions to the actual circle diameter so that the
            # oversized-cutter limits and border-ring math are calculated correctly.
            base_x = radius * 2.0
            base_y = radius * 2.0

    plaque_thick = float(props.plaque_thick)
    border_socket_depth = min(effective_hole_depth, plaque_thick)
    deep_layer_bias = float(max(0.0, getattr(props, "deep_layer_clearance_bias", 0.0)))
    deep_layer_prefixes = {"Green", "Tee", "Sand", "Water"}

    source_layer_map = {}
    for prefix, _ in present_layers:
        for source in (obj for obj in all_svg_objs if obj.name.startswith(prefix)):
            source_layer_map[source.name] = _extract_name_layer_number(_source_name(source))

    # ── Build the base plaque with a receiving hole for the outermost layer ─
    if plaque_base_svg is not None:
        # Use the SVG outline directly as the base shape (supports any SVG shape).
        base = _duplicate_mesh_obj(
            plaque_base_svg, f"{BASE_OBJECT_NAME}_Inserts", inserts_collection
        )
        _apply_solidify_and_bake(base, plaque_thick, offset=0.0)
        _cleanup_insert_mesh(base)
    else:
        plaque_shape = getattr(props, "plaque_shape", "RECTANGLE")
        if plaque_shape == "CIRCLE":
            radius = base_x / 2.0
            bpy.ops.mesh.primitive_cylinder_add(
                radius=radius,
                depth=plaque_thick,
                vertices=64,
            )
            base = bpy.context.active_object
        else:
            bpy.ops.mesh.primitive_cube_add(size=1)
            base = bpy.context.active_object
            base.scale = (base_x, base_y, plaque_thick)
            bpy.ops.object.transform_apply(scale=True)
        base.name = f"{BASE_OBJECT_NAME}_Inserts"
        move_object_to_collection(base, inserts_collection)

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
        inset_amount = 0.0
        compensation = 0.0
        applied_compensation = 0.0
        if clearance > 0.0:
            if not use_shrink:
                # Grow base hole only when hole-growth mode is selected.
                apply_flat_outset(hole_cutter, clearance)
                applied_compensation = clearance
            else:
                # If an insert had to use reduced safe inset, grow the hole by
                # the remainder so the final fit still equals requested gap.
                inset_amount = _get_source_inset_amount(
                    svg_src,
                    source_clearance_map,
                    clearance,
                )
                compensation = max(0.0, clearance - inset_amount)
                if compensation > 0.0:
                    safe_compensation = source_compensation_map.get(svg_src.name, 0.0)
                    if safe_compensation > 0.0:
                        apply_flat_outset(hole_cutter, safe_compensation)
                        applied_compensation = safe_compensation
                    else:
                        local_safe = _find_max_safe_outset(hole_cutter, compensation)
                        if local_safe > 0.0:
                            apply_flat_outset(hole_cutter, local_safe)
                            applied_compensation = local_safe
                            fit_compromises_made = True
                            fit_compromise_rows.append(
                                (
                                    "Base",
                                    outermost_prefix,
                                    _source_name(svg_src),
                                    "compensation_clamped",
                                    compensation - local_safe,
                                )
                            )
                        else:
                            fit_compromises_made = True
                            fit_compromise_rows.append(
                                (
                                    "Base",
                                    outermost_prefix,
                                    _source_name(svg_src),
                                    "compensation_skipped",
                                    compensation,
                                )
                            )
                            print(
                                "[golf_tools] Compensation outset skipped for",
                                hole_cutter.name,
                                "(requested=",
                                round(compensation, 4),
                                ")",
                            )

        if clearance > 0.0 and use_shrink:
            extra_shrink = source_extra_shrink_map.get(svg_src.name, 0.0)
            # Use actual applied shrink if available (e.g., from later insert build).
            # For now, record the planned value; it will be updated during insert build.
            actual_extra_shrink = source_extra_shrink_applied_map.get(svg_src.name, extra_shrink)
            achieved_clearance = inset_amount + applied_compensation + actual_extra_shrink
            fit_validation_rows.append(
                (
                    "Base",
                    outermost_prefix,
                    _source_name(svg_src),
                    clearance,
                    achieved_clearance,
                    inset_amount,
                    compensation,
                    applied_compensation,
                    actual_extra_shrink,
                )
            )
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

    # ── Build an insert slab for each terrain layer ──────────────────────────
    # Start inserts a full base-width plus a small clearance to the right so
    # the first piece never overlaps the base in preview/output layout.
    display_x_offset = base_x + _BASE_INSERT_START_CLEARANCE_MM

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
                inset_amount = source_clearance_map.get(svg_src.name, clearance)
                if inset_amount > 0.0 and not _apply_flat_inset_safe(insert, inset_amount):
                    # Last-resort numerical fallback: build the piece unshrunk
                    # rather than emitting broken topology.
                    fit_compromises_made = True
                    fit_compromise_rows.append(
                        (
                            prefix,
                            prefix,
                            _source_name(svg_src),
                            "inset_skipped",
                            inset_amount,
                        )
                    )
                    print(
                        "[golf_tools] Inset skipped after safety check for",
                        insert.name,
                        "(requested=",
                        round(inset_amount, 4),
                        ")",
                    )

                # Fit-first fallback: if safe inset + safe pocket compensation
                # still cannot meet requested clearance, uniformly shrink the
                # child insert a bit more so the assembled fit is not tighter
                # than requested.
                extra_shrink = source_extra_shrink_map.get(svg_src.name, 0.0)
                if extra_shrink > 0.0:
                    applied_extra = _apply_uniform_xy_shrink(insert, extra_shrink)
                    source_extra_shrink_applied_map[svg_src.name] = applied_extra
                    if applied_extra + 1e-6 < extra_shrink:
                        fit_compromises_made = True
                        fit_compromise_rows.append(
                            (
                                prefix,
                                prefix,
                                _source_name(svg_src),
                                "extra_shrink_clamped",
                                extra_shrink - applied_extra,
                            )
                        )
                        print(
                            "[golf_tools] Extra shrink clamped for",
                            insert.name,
                            "requested=",
                            round(extra_shrink, 4),
                            "applied=",
                            round(applied_extra, 4),
                        )

            # Extrude the flat outline upward to element_height.
            # offset = 1.0 → original face (Z=0) becomes the bottom face;
            # the solidify extends upward.
            _apply_solidify_and_bake(insert, element_height, offset=1.0)
            _cleanup_insert_mesh(insert)
            _enforce_insert_z_bounds(insert, 0.0, element_height)

            if not insert.data.materials:
                insert.data.materials.append(mat)

            # ── Cut receiving pockets for all higher-numbered name layers ─────
            # Numeric naming (e.g., Rough.001, Fairway.002, Green.003) is the
            # sole relationship rule: child_layer > parent_layer.
            parent_layer_number = source_layer_map.get(svg_src.name)
            if parent_layer_number is None:
                continue

            for inner_prefix, _ in present_layers:
                if inner_prefix == prefix:
                    continue
                inner_sources = [
                    obj
                    for obj in all_svg_objs
                    if obj.name.startswith(inner_prefix)
                ]
                for inner_index, inner_src in enumerate(inner_sources):
                    child_layer_number = source_layer_map.get(inner_src.name)
                    if child_layer_number is None:
                        continue
                    if child_layer_number <= parent_layer_number:
                        continue

                    inner_cutter = _duplicate_mesh_obj(
                        inner_src,
                        f"_InsertHole_{prefix}_{inner_prefix}_{inner_index:02d}",
                        cutters_collection,
                    )
                    inset_amount = 0.0
                    compensation = 0.0
                    applied_compensation = 0.0
                    if clearance > 0.0:
                        if not use_shrink:
                            # When growing holes rather than shrinking inserts,
                            # expand the inner cutout so the child insert fits
                            # with clearance.
                            apply_flat_outset(inner_cutter, clearance)
                            applied_compensation = clearance
                        else:
                            # Maintain requested fit even when this child layer
                            # needed reduced inset to avoid invalid geometry.
                            inset_amount = _get_source_inset_amount(
                                inner_src,
                                source_clearance_map,
                                clearance,
                            )
                            compensation = max(0.0, clearance - inset_amount)
                            if compensation > 0.0:
                                safe_compensation = source_compensation_map.get(
                                    inner_src.name,
                                    0.0,
                                )
                                if safe_compensation > 0.0:
                                    apply_flat_outset(inner_cutter, safe_compensation)
                                    applied_compensation = safe_compensation
                                else:
                                    local_safe = _find_max_safe_outset(inner_cutter, compensation)
                                    if local_safe > 0.0:
                                        apply_flat_outset(inner_cutter, local_safe)
                                        applied_compensation = local_safe
                                        fit_compromises_made = True
                                        fit_compromise_rows.append(
                                            (
                                                prefix,
                                                inner_prefix,
                                                _source_name(inner_src),
                                                "compensation_clamped",
                                                compensation - local_safe,
                                            )
                                        )
                                    else:
                                        fit_compromises_made = True
                                        fit_compromise_rows.append(
                                            (
                                                prefix,
                                                inner_prefix,
                                                _source_name(inner_src),
                                                "compensation_skipped",
                                                compensation,
                                            )
                                        )
                                        print(
                                            "[golf_tools] Compensation outset skipped for",
                                            inner_cutter.name,
                                            "(requested=",
                                            round(compensation, 4),
                                            ")",
                                        )

                            # Apply deep layer bias for inner layers if geometry prevented full fit.
                            if deep_layer_bias > 0.0 and inner_prefix in deep_layer_prefixes:
                                safe_bias = _find_max_safe_outset(inner_cutter, deep_layer_bias)
                                if safe_bias > 0.0:
                                    apply_flat_outset(inner_cutter, safe_bias)
                                    applied_compensation += safe_bias
                                    if safe_bias + 1e-6 < deep_layer_bias:
                                        fit_compromises_made = True
                                        fit_compromise_rows.append(
                                            (
                                                prefix,
                                                inner_prefix,
                                                _source_name(inner_src),
                                                "deep_bias_clamped",
                                                deep_layer_bias - safe_bias,
                                            )
                                        )
                                else:
                                    fit_compromises_made = True
                                    fit_compromise_rows.append(
                                        (
                                            prefix,
                                            inner_prefix,
                                            _source_name(inner_src),
                                            "deep_bias_failed",
                                            deep_layer_bias,
                                        )
                                    )

                    if clearance > 0.0 and use_shrink:
                        extra_shrink = source_extra_shrink_map.get(inner_src.name, 0.0)
                        actual_extra_shrink = source_extra_shrink_applied_map.get(inner_src.name, extra_shrink)
                        achieved_clearance = inset_amount + applied_compensation + actual_extra_shrink
                        fit_validation_rows.append(
                            (
                                prefix,
                                inner_prefix,
                                _source_name(inner_src),
                                clearance,
                                achieved_clearance,
                                inset_amount,
                                compensation,
                                applied_compensation,
                                actual_extra_shrink,
                            )
                        )
                    # Position the cutter above the insert top and cut only a
                    # pocket depth (hole_layers), leaving lower parent layers
                    # intact so stacked elements preserve visible height steps.
                    inner_cutter.location.z = element_height + CUTTER_TOP_POKE_MM
                    _apply_solidify_and_bake(
                        inner_cutter,
                        effective_hole_depth + CUTTER_TOP_POKE_MM + CUTTER_EPSILON,
                        offset=-1.0,
                    )
                    if is_valid_cutter_mesh(inner_cutter):
                        _boolean_subtract(insert, inner_cutter)
                        _cleanup_insert_mesh(insert)
                        _enforce_insert_z_bounds(insert, 0.0, element_height)
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

    # Text is not an insert layer. It is always applied on the base using
    # the same emboss/engrave options as the Engrave Builder.
    applied_text_count = _apply_text_to_base(
        props,
        all_svg_objs,
        base,
        plaque_thick,
        base_x,
        base_y,
        inserts_collection,
        cutters_collection,
    )

    border_added, border_pieces = _apply_embossed_border_to_base(
        props,
        base,
        plaque_thick,
        base_x,
        base_y,
        plaque_base_svg,
        inserts_collection,
        cutters_collection,
        border_socket_depth,
        getattr(props, "plaque_shape", "RECTANGLE"),
    )

    for border_piece in border_pieces:
        border_piece.location.x += display_x_offset
        display_x_offset += border_piece.dimensions.x + _INSERT_DISPLAY_GAP_MM

    # ── Cut strap holes all the way through the base ─────────────────────────
    # StrapHole objects bypass layer logic and always produce a full-depth
    # through-hole so the strap/hardware can be attached after printing.
    strap_hole_objs = [
        obj for obj in all_svg_objs
        if any(obj.name.startswith(pre) for pre in STRAP_HOLE_PREFIXES)
    ]

    if getattr(props, "generate_container", False):
        build_container(props, base, strap_hole_objs, inserts_collection, cutters_collection)

    for sh_index, sh_src in enumerate(strap_hole_objs):
        sh_cutter = _duplicate_mesh_obj(
            sh_src,
            f"_StrapHoleCut_{sh_index:02d}",
            cutters_collection,
        )
        # Position above the top surface and solidify downward through the
        # full base thickness with margins to avoid coplanar artefacts.
        sh_cutter.location.z = plaque_thick / 2.0 + CUTTER_TOP_POKE_MM
        _apply_solidify_and_bake(
            sh_cutter,
            plaque_thick + CUTTER_TOP_POKE_MM * 2.0 + CUTTER_EPSILON,
            offset=-1.0,
        )
        if is_valid_cutter_mesh(sh_cutter):
            _boolean_subtract(base, sh_cutter)
        sh_cutter.display_type = "WIRE"
        sh_cutter.hide_render = True
        print("[golf_tools] Strap hole cut:", sh_src.name)

    cleanup_base_mesh(base)

    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    print(
        "[golf_tools] Insert build complete --",
        len(present_layers), "layers,",
        "text_objs=", applied_text_count,
        "text_mode=", getattr(props, "text_mode", "EMBOSS"),
        "element_height=", round(element_height, 3), "mm,",
        "hole_depth=", round(effective_hole_depth, 3), "mm,",
        "clearance=", round(clearance, 3), "mm",
        "(shrink_element=", use_shrink, ")",
        "strap_holes=", len(strap_hole_objs),
        "border=", border_added,
    )

    if clearance > 0.0 and use_shrink and fit_validation_rows:
        fit_tolerance = 0.01
        tight_rows = [
            row for row in fit_validation_rows
            if row[4] + fit_tolerance < row[3]
        ]
        if tight_rows or fit_compromises_made:
            print("[golf_tools] FIT VALIDATION: WARN -- some boundaries may be tighter than requested")
            for parent, child, source_name, requested, achieved, inset_amt, needed, applied, extra_shrink in tight_rows:
                print(
                    "  -",
                    f"{parent}->{child}",
                    source_name,
                    "requested=", round(requested, 4),
                    "achieved=", round(achieved, 4),
                    "inset=", round(inset_amt, 4),
                    "needed_outset=", round(needed, 4),
                    "applied_outset=", round(applied, 4),
                    "extra_shrink=", round(extra_shrink, 4),
                )
            if fit_compromise_rows:
                for parent, child, source_name, reason, amount in fit_compromise_rows[:12]:
                    print(
                        "  -",
                        f"{parent}->{child}",
                        source_name,
                        reason,
                        "amount=",
                        round(amount, 4),
                    )
                if len(fit_compromise_rows) > 12:
                    print("  -", "...", len(fit_compromise_rows) - 12, "more compromise rows")
            print("[golf_tools] Recommendation: increase insert_clearance slightly or test-fit these pairs first")
        else:
            print("[golf_tools] FIT VALIDATION: PASS -- all boundaries met requested clearance")

