"""SVG/object preparation helpers for the golf plaque generator."""

import bmesh
import bpy
from mathutils import Matrix, Vector

from .config import PLAQUE_BASE_PREFIXES


def ensure_upward_normals(mesh_data):
    """Recalculate mesh normals and ensure every face normal points +Z.

    ``bmesh.ops.recalc_face_normals`` makes normals consistent *within each
    connected face island*, but letters with inner loops (R, O, B, D, P …)
    produce a separate, disconnected island for their counter (the enclosed
    hole).  The outer letter body has more faces, so when only the global
    average was checked the counter island — whose normals point -Z after
    curve-to-mesh conversion — was left untouched.  Solidify then extruded
    those counter faces *downward* through the plaque, creating the visible
    spike artefacts and open mesh boundaries that Cura flags as non-watertight.

    Flipping each face individually (rather than using a global average) fixes
    all islands regardless of their relative size.
    """
    if mesh_data is None:
        return

    bm = bmesh.new()
    bm.from_mesh(mesh_data)
    if not bm.faces:
        bm.free()
        return

    # Make normals consistent within each connected island first.
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.normal_update()

    # Flip any face whose normal still points downward.  This corrects counter
    # islands that recalc_face_normals leaves pointing -Z because SVG inner
    # contours are wound in the opposite direction to the outer silhouette.
    faces_to_flip = [f for f in bm.faces if f.normal.z < 0]
    if faces_to_flip:
        bmesh.ops.reverse_faces(bm, faces=faces_to_flip)

    bm.to_mesh(mesh_data)
    bm.free()
    mesh_data.update()


def find_plaque_base(objects=None):
    """Return the first object named ``Plaque_Base`` or ``Plaque_Frame``, or ``None``."""
    search = objects if objects is not None else bpy.data.objects
    for obj in search:
        if any(obj.name.startswith(pre) for pre in PLAQUE_BASE_PREFIXES):
            return obj
    return None


def get_world_bounds_center(obj):
    """Return the world-space XY center of an object's bounding box."""
    world_points = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    min_x = min(point.x for point in world_points)
    max_x = max(point.x for point in world_points)
    min_y = min(point.y for point in world_points)
    max_y = max(point.y for point in world_points)
    return ((min_x + max_x) / 2, (min_y + max_y) / 2)


def sanitize_geometry(objects, props, output_collection):
    """Convert curves to meshes, scale imported geometry, and center the layout."""
    if not objects:
        return []

    depsgraph = bpy.context.evaluated_depsgraph_get()
    sanitized_objects = []

    for obj in objects:
        if obj.type == "CURVE":
            obj_eval = obj.evaluated_get(depsgraph)
            mesh = bpy.data.meshes.new_from_object(obj_eval)
            working_obj = bpy.data.objects.new(obj.name, mesh)
        else:
            working_obj = obj.copy()
            if obj.data is not None:
                working_obj.data = obj.data.copy()

        working_obj.matrix_world = obj.matrix_world.copy()
        output_collection.objects.link(working_obj)

        if working_obj.data is not None:
            working_obj.data.transform(working_obj.matrix_world)
        working_obj.matrix_world = Matrix.Identity(4)

        # Imported SVG objects should behave as flat 2D outlines on the plaque
        # plane. Flatten any baked Z extent from the importer so later cutter
        # thickness comes only from the explicit Solidify modifier.
        if working_obj.data is not None and hasattr(working_obj.data, "vertices"):
            for vertex in working_obj.data.vertices:
                vertex.co.z = 0.0

        # Keep face orientation consistent so later solidify offset has
        # predictable "downward" behavior relative to +Z.
        ensure_upward_normals(working_obj.data)

        working_obj.location.z = 0.0

        sanitized_objects.append(working_obj)

    anchor = find_plaque_base(sanitized_objects)

    if anchor:
        anchor_w = anchor.dimensions.x
        anchor_h = anchor.dimensions.y

        width_ratio = props.plaque_width / anchor_w if anchor_w > 0 else None
        height_ratio = props.plaque_height / anchor_h if anchor_h > 0 else None

        if width_ratio is not None and height_ratio is not None:
            scale_ratio = min(width_ratio, height_ratio)
        else:
            scale_ratio = width_ratio or height_ratio or 1.0
    else:
        max_svg_dim = max(
            max(obj.dimensions.x, obj.dimensions.y) for obj in sanitized_objects
        )
        scale_ratio = min(props.plaque_width, props.plaque_height) / max_svg_dim

    scale_matrix = Matrix.Diagonal((scale_ratio, scale_ratio, 1.0, 1.0))
    for obj in sanitized_objects:
        if obj.data is not None:
            obj.data.transform(scale_matrix)
        obj.scale = (1.0, 1.0, 1.0)

    bpy.context.view_layer.update()

    if anchor is not None:
        center_x, center_y = get_world_bounds_center(anchor)
    else:
        min_x = min(obj.location.x for obj in sanitized_objects)
        max_x = max(obj.location.x for obj in sanitized_objects)
        min_y = min(obj.location.y for obj in sanitized_objects)
        max_y = max(obj.location.y for obj in sanitized_objects)
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2

    for obj in sanitized_objects:
        obj.location.x -= center_x
        obj.location.y -= center_y

    bpy.context.view_layer.update()

    return sanitized_objects