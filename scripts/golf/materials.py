"""Material helpers for the golf plaque generator."""

import bpy


def setup_material(name, color):
    """Return an existing ``Mat_<name>`` material or create a new one."""
    mat_name = f"Mat_{name}"
    mat = bpy.data.materials.get(mat_name) or bpy.data.materials.new(name=mat_name)
    mat.diffuse_color = color
    return mat