"""Plaque construction pipeline for the golf plaque generator."""

import bpy

from .collection_utils import (
    clear_collection,
    ensure_cutters_collection,
    ensure_output_collection,
    move_object_to_collection,
)
from .config import (
    BASE_OBJECT_NAME,
    COLOR_MAP,
    CUTTER_EPSILON,
    PLAQUE_BASE_PREFIXES,
    PROTECTIVE_FRAME_MARGIN,
)
from .materials import setup_material
from .svg_utils import find_plaque_base, sanitize_geometry

# Tolerance (in Blender units / mm) used when identifying coplanar bottom-face
# vertices after the Solidify modifier is applied.  Floating-point arithmetic
# can leave vertices very slightly off the exact minimum-Z plane, so we accept
# anything within this epsilon as "on the floor".
_FLOOR_VERTEX_TOLERANCE = 1e-4

# Maps a layer prefix to its floor-texture settings.
# ``type`` is a Blender legacy-texture type string; ``noise_scale`` controls the
# grain frequency (in global/world units); ``strength`` is the Displace modifier
# strength in mm.
_FLOOR_TEXTURE_CONFIG = {
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


def _apply_floor_texture(cutter, prefix, solidify_mod):
    """Apply a procedural displacement texture to the bottom face of *cutter*.

    The Solidify modifier is applied first so that the actual bottom-face
    vertices are accessible.  A vertex group is created for those vertices so
    that the Displace modifier only moves the floor of the carved well; the
    clean top edges that meet the plaque surface are left untouched.

    Global texture coordinates are used so that the grain/ripple looks
    consistent regardless of how large or small the individual feature is.

    Args:
        cutter: The Blender mesh object that will be used as a Boolean cutter.
        prefix: Layer name prefix (``"Water"`` or ``"Sand"``).
        solidify_mod: The Solidify modifier instance already attached to *cutter*.
    """
    config = _FLOOR_TEXTURE_CONFIG.get(prefix)
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
        v.index for v in mesh.vertices if abs(v.co.z - min_z) < _FLOOR_VERTEX_TOLERANCE
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


def carve_plaque(props):
    """Build the base plaque cube and Boolean-carve each SVG layer into it."""
    output_collection = ensure_output_collection()
    cutters_collection = ensure_cutters_collection()
    clear_collection(output_collection)
    clear_collection(cutters_collection)

    all_known_prefixes = tuple(COLOR_MAP.keys()) + PLAQUE_BASE_PREFIXES
    all_svg_objs = [
        obj
        for obj in bpy.data.objects
        if any(obj.name.startswith(pre) for pre in all_known_prefixes)
    ]

    all_svg_objs = sanitize_geometry(all_svg_objs, props, cutters_collection)

    plaque_base_svg = find_plaque_base(all_svg_objs)
    rough_obj = next(
        (o for o in all_svg_objs if o.name.startswith("Rough")), None
    )

    if plaque_base_svg is not None:
        base_x = plaque_base_svg.dimensions.x
        base_y = plaque_base_svg.dimensions.y
        move_object_to_collection(plaque_base_svg, output_collection)
        plaque_base_svg.display_type = "WIRE"
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
    base.scale = (base_x, base_y, props.plaque_thick)
    bpy.ops.object.transform_apply(scale=True)
    base.data.materials.append(setup_material("Rough", COLOR_MAP["Rough"][1]))

    sorted_items = sorted(COLOR_MAP.items(), key=lambda item: item[1][0])

    for prefix, (depth, color) in sorted_items:
        cutters = [obj for obj in all_svg_objs if obj.name.startswith(prefix)]
        mat = setup_material(prefix, color)

        for cutter in cutters:
            solidify = cutter.modifiers.new(name="Solidify", type="SOLIDIFY")
            solidify.thickness = depth + CUTTER_EPSILON
            solidify.offset = -1.0

            cutter.location.z = props.plaque_thick / 2 + CUTTER_EPSILON

            if prefix in _FLOOR_TEXTURE_CONFIG:
                _apply_floor_texture(cutter, prefix, solidify)

            if not cutter.data.materials:
                cutter.data.materials.append(mat)

            bool_mod = base.modifiers.new(
                type="BOOLEAN", name=f"Cut_{cutter.name}"
            )
            bool_mod.object = cutter
            bool_mod.operation = "DIFFERENCE"
            bool_mod.solver = "EXACT"

            cutter.display_type = "WIRE"
            cutter.hide_render = True