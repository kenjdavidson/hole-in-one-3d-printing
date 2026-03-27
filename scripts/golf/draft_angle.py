"""Top-taper and stepped-wall geometry helpers for cutter meshes."""

import bmesh
from mathutils import Vector

# Floating-point tolerance for identifying vertices that share the same Z level.
Z_TOLERANCE = 1e-4


def _iter_boundary_loops(boundary_edges):
    """Yield ordered vertex loops from a set of boundary edges."""
    remaining_edges = set(boundary_edges)
    vertex_edges = {}
    for edge in boundary_edges:
        for vertex in edge.verts:
            vertex_edges.setdefault(vertex, []).append(edge)

    loops = []
    while remaining_edges:
        start_edge = remaining_edges.pop()
        start_vert, next_vert = start_edge.verts[:]
        loop = [start_vert, next_vert]
        prev_vert = start_vert
        current_vert = next_vert

        while current_vert != start_vert:
            candidates = [
                edge
                for edge in vertex_edges[current_vert]
                if edge in remaining_edges
            ]
            next_edge = None
            for candidate in candidates:
                other = candidate.other_vert(current_vert)
                if other != prev_vert:
                    next_edge = candidate
                    break

            if next_edge is None:
                break

            remaining_edges.remove(next_edge)
            next_vertex = next_edge.other_vert(current_vert)
            if next_vertex == start_vert:
                break
            loop.append(next_vertex)
            prev_vert = current_vert
            current_vert = next_vertex

        if len(loop) >= 3:
            loops.append(loop)

    return loops


def _signed_loop_area(loop):
    """Return signed polygon area for an ordered XY loop."""
    area = 0.0
    for index, vertex in enumerate(loop):
        next_vertex = loop[(index + 1) % len(loop)]
        area += (vertex.co.x * next_vertex.co.y) - (next_vertex.co.x * vertex.co.y)
    return area * 0.5


def _offset_line_intersection(point_a, direction_a, point_b, direction_b):
    """Return XY intersection of two offset lines, or None if parallel."""
    determinant = (direction_a.x * direction_b.y) - (direction_a.y * direction_b.x)
    if abs(determinant) < 1e-9:
        return None

    delta = point_b - point_a
    t_value = ((delta.x * direction_b.y) - (delta.y * direction_b.x)) / determinant
    return point_a + (direction_a * t_value)


def _offset_loops_xy(bm, loops, signed_offset):
    """Offset provided ordered loops in XY by a signed distance."""
    new_positions = {}

    for loop in loops:
        area = _signed_loop_area(loop)
        normal_sign = -1.0 if area >= 0.0 else 1.0

        for index, vertex in enumerate(loop):
            prev_vertex = loop[index - 1]
            next_vertex = loop[(index + 1) % len(loop)]

            prev_edge = Vector(
                (vertex.co.x - prev_vertex.co.x, vertex.co.y - prev_vertex.co.y)
            )
            next_edge = Vector(
                (next_vertex.co.x - vertex.co.x, next_vertex.co.y - vertex.co.y)
            )

            if prev_edge.length < 1e-9 or next_edge.length < 1e-9:
                continue

            prev_dir = prev_edge.normalized()
            next_dir = next_edge.normalized()
            prev_normal = Vector((prev_dir.y, -prev_dir.x)) * normal_sign
            next_normal = Vector((next_dir.y, -next_dir.x)) * normal_sign

            prev_point = Vector((vertex.co.x, vertex.co.y)) + (prev_normal * signed_offset)
            next_point = Vector((vertex.co.x, vertex.co.y)) + (next_normal * signed_offset)
            intersection = _offset_line_intersection(
                prev_point, prev_dir, next_point, next_dir
            )

            if intersection is None:
                average_normal = prev_normal + next_normal
                if average_normal.length < 1e-9:
                    average_normal = prev_normal
                intersection = (
                    Vector((vertex.co.x, vertex.co.y))
                    + average_normal.normalized() * signed_offset
                )

            if (
                intersection - Vector((vertex.co.x, vertex.co.y))
            ).length > abs(signed_offset) * 3.0:
                average_normal = prev_normal + next_normal
                if average_normal.length < 1e-9:
                    average_normal = prev_normal
                intersection = (
                    Vector((vertex.co.x, vertex.co.y))
                    + average_normal.normalized() * signed_offset
                )

            new_positions[vertex] = intersection

    if not new_positions:
        return False

    for vertex, position in new_positions.items():
        vertex.co.x = position.x
        vertex.co.y = position.y

    return True


def apply_flat_outset(obj, offset_mm):
    """Expand a flat cutter outline by a constant XY offset."""
    if offset_mm <= 0.0:
        return

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    if not bm.verts:
        bm.free()
        return

    original_coords = [vertex.co.copy() for vertex in bm.verts]

    def _bbox_area():
        xs = [vertex.co.x for vertex in bm.verts]
        ys = [vertex.co.y for vertex in bm.verts]
        return (max(xs) - min(xs)) * (max(ys) - min(ys))

    boundary_edges = [edge for edge in bm.edges if len(edge.link_faces) == 1]
    loops = _iter_boundary_loops(boundary_edges) if boundary_edges else []
    if not loops:
        bm.free()
        return

    before_area = _bbox_area()
    if not _offset_loops_xy(bm, loops, offset_mm):
        bm.free()
        return

    after_area = _bbox_area()
    if after_area < before_area:
        for vertex, original in zip(bm.verts, original_coords):
            vertex.co = original
        if not _offset_loops_xy(bm, loops, -offset_mm):
            bm.free()
            return

    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def apply_top_taper(obj, taper_width_mm):
    """Offset only the top perimeter loop(s) outward to create draft walls."""
    if taper_width_mm <= 0.0:
        return

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    if not bm.verts:
        bm.free()
        return

    z_max = max(vertex.co.z for vertex in bm.verts)
    top_faces = {
        face
        for face in bm.faces
        if all(abs(vertex.co.z - z_max) < Z_TOLERANCE for vertex in face.verts)
    }
    if not top_faces:
        bm.free()
        return

    top_perimeter_edges = []
    for edge in bm.edges:
        if not all(abs(vertex.co.z - z_max) < Z_TOLERANCE for vertex in edge.verts):
            continue
        linked_faces = set(edge.link_faces)
        if (linked_faces & top_faces) and (linked_faces - top_faces):
            top_perimeter_edges.append(edge)

    loops = _iter_boundary_loops(top_perimeter_edges) if top_perimeter_edges else []
    if not loops:
        bm.free()
        return

    top_vertices = []
    seen_vertices = set()
    for loop in loops:
        for vertex in loop:
            if vertex not in seen_vertices:
                seen_vertices.add(vertex)
                top_vertices.append(vertex)

    def _top_bbox_area():
        xs = [vertex.co.x for vertex in top_vertices]
        ys = [vertex.co.y for vertex in top_vertices]
        return (max(xs) - min(xs)) * (max(ys) - min(ys))

    before_area = _top_bbox_area()

    original_coords = [vertex.co.copy() for vertex in bm.verts]
    if not _offset_loops_xy(bm, loops, taper_width_mm):
        bm.free()
        return

    after_area = _top_bbox_area()

    if after_area < before_area:
        for vertex, original in zip(bm.verts, original_coords):
            vertex.co = original
        if not _offset_loops_xy(bm, loops, -taper_width_mm):
            bm.free()
            return

    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def create_stepped_cutters(base_obj, total_width_mm, step_count, effective_depth, epsilon):
    """Create progressively wider, shallower cutter objects for terraced walls."""
    steps = max(2, int(step_count))
    total_width = max(0.0, total_width_mm)
    base_depth = max(0.0, effective_depth)
    if base_depth <= 0.0:
        return [base_obj]

    min_planar_dim = max(0.001, min(base_obj.dimensions.x, base_obj.dimensions.y))
    max_total_width = min(min_planar_dim * 0.2, base_depth * 0.8)
    applied_total_width = min(total_width, max_total_width)
    width_per_step = (
        applied_total_width / (steps - 1) if steps > 1 else applied_total_width
    )

    collection = base_obj.users_collection[0] if base_obj.users_collection else None
    stepped_cutters = []

    for modifier in list(base_obj.modifiers):
        base_obj.modifiers.remove(modifier)

    max_raise_span = min(base_depth - epsilon, 0.4)
    per_step_raise = max_raise_span / (steps - 1) if steps > 1 else 0.0

    for step_index in range(steps):
        cutter = base_obj if step_index == 0 else base_obj.copy()
        if step_index != 0 and base_obj.data is not None:
            cutter.data = base_obj.data.copy()
            if collection is not None:
                collection.objects.link(cutter)

        for modifier in list(cutter.modifiers):
            cutter.modifiers.remove(modifier)

        if step_index > 0:
            apply_flat_outset(cutter, width_per_step * step_index)

        step_raise = min(base_depth - epsilon, per_step_raise * step_index)
        cutter["_step_raise_z"] = step_raise

        solidify = cutter.modifiers.new(
            name=f"Solidify_Step_{step_index + 1}", type="SOLIDIFY"
        )
        solidify.thickness = base_depth + epsilon
        solidify.offset = -1.0

        stepped_cutters.append(cutter)

    return stepped_cutters


def apply_taper(obj, factor, depth=None):
    """Compatibility wrapper for legacy callers using factor/depth style taper."""
    if factor <= 1.0:
        return
    width = (factor - 1.0) * depth if depth is not None else (factor - 1.0)
    apply_top_taper(obj, width)
