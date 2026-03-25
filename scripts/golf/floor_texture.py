"""
Floor Texture Utility
======================
Provides :func:`apply_floor_texture` which adds a procedural displacement
texture to the bottom face of a Boolean cutter mesh.

Water cutters receive a Musgrave (ripple) texture; Sand cutters receive a
Clouds (grain) texture.  Displacement is confined to the carved-well floor via
a vertex group so the clean plaque-surface cut edges are not affected.

Global texture coordinates are used so that the grain/ripple frequency is
world-space consistent — a tiny 5 mm bunker and a large 50 mm fairway share
the same visual texture scale.

The function is intentionally standalone so it can be imported and called as a
single conditional inside :mod:`plaque_builder` without touching the rest of
the carve pipeline.
"""

import bpy

# Floating-point tolerance (mm) for identifying coplanar bottom-face vertices
# after the Solidify modifier is applied.
_FLOOR_VERTEX_TOLERANCE = 1e-4

# Maps a layer-name prefix to its floor-texture settings.
# ``type`` is a Blender legacy-texture type string; ``noise_scale`` controls
# the grain frequency in global/world units; ``strength`` is the Displace
# modifier strength in mm.
FLOOR_TEXTURE_CONFIG = {
    "Water": {
        "type": "MUSGRAVE",
        "noise_scale": 5.0,
        "strength": 0.3,
    },
    "Sand": {
        "type": "CLOUDS",
        "noise_scale": 1.0,
        "strength": 0.15,
    },
}


def apply_floor_texture(cutter, prefix, solidify_mod):
    """Apply a procedural displacement texture to the bottom face of *cutter*.

    The Solidify modifier is applied first so that the actual bottom-face
    vertices are accessible.  A vertex group is created for those vertices so
    that the Displace modifier only moves the floor of the carved well; the
    clean top edges that meet the plaque surface are left untouched.

    Global texture coordinates are used so that the grain/ripple looks
    consistent regardless of how large or small the individual feature is.

    If *prefix* does not have a corresponding entry in
    :data:`FLOOR_TEXTURE_CONFIG` the function returns immediately without
    modifying *cutter*.

    Args:
        cutter: The Blender mesh object that will be used as a Boolean cutter.
        prefix: Layer name prefix (e.g. ``"Water"`` or ``"Sand"``).
        solidify_mod: The Solidify modifier instance already attached to *cutter*.
    """
    config = FLOOR_TEXTURE_CONFIG.get(prefix)
    if config is None:
        return

    # Apply the Solidify modifier so we can inspect the actual mesh vertices.
    bpy.context.view_layer.objects.active = cutter
    bpy.ops.object.modifier_apply(modifier=solidify_mod.name)

    mesh = cutter.data
    if not mesh.vertices:
        return

    # Bottom-face vertices are those at the minimum local-Z after solidification.
    min_z = min((v.co.z for v in mesh.vertices), default=None)
    if min_z is None:
        return
    floor_indices = [
        v.index
        for v in mesh.vertices
        if abs(v.co.z - min_z) < _FLOOR_VERTEX_TOLERANCE
    ]
    if not floor_indices:
        return

    vg = cutter.vertex_groups.new(name="Floor")
    vg.add(floor_indices, 1.0, "REPLACE")

    # Create a legacy texture of the appropriate type.
    tex = bpy.data.textures.new(
        name=f"FloorTex_{cutter.name}", type=config["type"]
    )
    tex.noise_scale = config["noise_scale"]

    # Displace only in Z so the floor gains relief without affecting XY edges.
    displace = cutter.modifiers.new(name="Floor_Texture", type="DISPLACE")
    displace.texture = tex
    # GLOBAL coordinates make the grain scale independent of object size,
    # so a tiny bunker and a large fairway share the same texture frequency.
    displace.texture_coords = "GLOBAL"
    displace.direction = "Z"
    displace.strength = config["strength"]
    displace.vertex_group = vg.name
