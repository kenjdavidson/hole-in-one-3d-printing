"""
Draft Angle (Tapered Walls) Utility
=====================================
Provides :func:`apply_taper` which widens the top face of a cutter mesh so
that carved features are wider at the surface than at the bottom.  This
improves visual definition of the layered pockets when the finished plaque is
viewed at an angle.

The function is intentionally standalone so it can be imported and called as a
single line inside :mod:`geometry_utils` without touching the rest of the
carve pipeline.
"""

import bpy
import bmesh

# Floating-point tolerance for identifying vertices that share the same Z level.
Z_TOLERANCE = 1e-4


def apply_taper(obj, factor):
    """Scale the top-most vertices of *obj* outward by *factor* in XY.

    This creates a draft angle (tapered wall) effect: the cutter is slightly
    wider at the top than at the bottom, giving carved pockets a visible
    chamfered lip for better definition when printed or painted.

    Steps
    -----
    1. Enter Edit mode and run ``mesh.dissolve_limited`` so the top face is a
       single clean polygon (makes vertex selection reliable).
    2. Deselect all geometry, then select only vertices whose Z coordinate
       matches the mesh maximum (i.e. the top face).
    3. Scale the selection by *factor* in XY (Z unchanged) around the mesh
       origin.
    4. Return to Object mode.

    Parameters
    ----------
    obj : bpy.types.Object
        A mesh object to taper.  Must already be a ``MESH`` type (call this
        after ``bpy.ops.object.convert(target='MESH')``).
    factor : float
        XY scale factor for the top vertices.  Values in the range ``1.0``
        (no taper) to ``1.5`` (50 % wider at top) are recommended.
    """
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.dissolve_limited()
    bpy.ops.mesh.select_mode(type="VERT")
    bpy.ops.mesh.select_all(action="DESELECT")

    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    z_max = max(v.co.z for v in bm.verts)
    for v in bm.verts:
        v.select = abs(v.co.z - z_max) < Z_TOLERANCE
    bmesh.update_edit_mesh(obj.data)

    bpy.ops.transform.resize(value=(factor, factor, 1.0))
    bpy.ops.object.mode_set(mode="OBJECT")
