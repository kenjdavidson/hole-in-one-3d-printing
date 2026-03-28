"""Cutter preparation and boolean-application helpers for plaque building."""

import bpy

from .config import CUTTER_EPSILON
from .draft_angle import apply_top_taper, create_stepped_cutters
from .floor_texture import FLOOR_TEXTURE_CONFIG, apply_floor_texture

# Explicit anti-coplanar overlap settings for boolean cutters.
CUTTER_OVERLAP_MM = 1.0
CUTTER_TOP_POKE_MM = 0.5

# Maps a layer-name prefix to the corresponding props attribute name so that
# depth can be read from the scene properties when use_layer_depths is enabled.
DEPTH_PROP_MAP = {
    "Water": "depth_water",
    "Sand": "depth_sand",
    "Green": "depth_green",
    "Fairway": "depth_fairway",
}


def resolve_effective_depth(props, prefix, default_depth, plaque_thickness):
    """Resolve carve depth for a layer prefix with optional custom overrides."""
    if getattr(props, "use_layer_depths", False) and prefix in DEPTH_PROP_MAP:
        raw_depth = getattr(props, DEPTH_PROP_MAP[prefix], default_depth)
        return min(raw_depth, plaque_thickness - CUTTER_EPSILON)
    return default_depth


def prepare_active_cutters(cutter, props, effective_depth):
    """Create and return active cutter objects for one source cutter."""
    use_top_taper = getattr(props, "use_top_taper", False)
    use_stepped_walls = getattr(props, "use_stepped_walls", False)

    if use_stepped_walls:
        active_cutters = create_stepped_cutters(
            cutter,
            props.stepped_wall_width,
            props.stepped_wall_steps,
            effective_depth,
            CUTTER_EPSILON,
        )
    else:
        solidify = cutter.modifiers.new(name="Solidify", type="SOLIDIFY")
        solidify.thickness = effective_depth + CUTTER_OVERLAP_MM
        solidify.offset = -1.0
        active_cutters = [cutter]

    return active_cutters, use_top_taper, use_stepped_walls


def prepare_strap_hole_cutter(cutter, plaque_thickness):
    """Prepare a dedicated cutter that bores fully through the plaque."""
    solidify = cutter.modifiers.new(name="Solidify", type="SOLIDIFY")
    solidify.thickness = plaque_thickness + CUTTER_OVERLAP_MM
    solidify.offset = -1.0
    cutter.location.z = plaque_thickness / 2 + CUTTER_TOP_POKE_MM
    return cutter


def postprocess_cutter_geometry(
    active_cutter,
    prefix,
    props,
    effective_depth,
    plaque_thickness,
    use_top_taper,
    use_stepped_walls,
):
    """Apply per-cutter geometry modifiers and positioning before boolean."""
    step_raise = float(active_cutter.get("_step_raise_z", 0.0))
    active_cutter.location.z = (
        plaque_thickness / 2 + CUTTER_TOP_POKE_MM + step_raise
    )

    solidify = next(
        (modifier for modifier in active_cutter.modifiers if modifier.type == "SOLIDIFY"),
        None,
    )

    if (
        getattr(props, "use_floor_texture", False)
        and prefix in FLOOR_TEXTURE_CONFIG
        and solidify is not None
    ):
        apply_floor_texture(active_cutter, prefix, solidify)
    elif (use_stepped_walls or use_top_taper) and solidify is not None:
        bpy.context.view_layer.objects.active = active_cutter
        bpy.ops.object.modifier_apply(modifier=solidify.name)

    if use_top_taper:
        apply_top_taper(active_cutter, props.top_taper_width)


def duplicate_cutter(active_cutter):
    """Create a linked duplicate with copied mesh data for fallback operations."""
    duplicate = active_cutter.copy()
    if active_cutter.data is not None:
        duplicate.data = active_cutter.data.copy()
    for collection in active_cutter.users_collection:
        collection.objects.link(duplicate)
    return duplicate


def apply_solidify_if_present(active_cutter):
    """Apply the first solidify modifier if present."""
    solidify = next(
        (modifier for modifier in active_cutter.modifiers if modifier.type == "SOLIDIFY"),
        None,
    )
    if solidify is None:
        return

    bpy.context.view_layer.objects.active = active_cutter
    bpy.ops.object.modifier_apply(modifier=solidify.name)


def is_valid_cutter_mesh(active_cutter):
    """Return True if the cutter has mesh data with vertices."""
    return active_cutter.data is not None and bool(active_cutter.data.vertices)


def is_oversized_cutter(active_cutter, max_cutter_x, max_cutter_y):
    """Return True if cutter dimensions exceed configured safety limits."""
    return (
        active_cutter.dimensions.x > max_cutter_x
        or active_cutter.dimensions.y > max_cutter_y
    )


def log_oversized_cutter(active_cutter, max_cutter_x, max_cutter_y):
    """Print diagnostic information for oversized skipped cutters."""
    print(
        "[golf_tools] Skipping oversized cutter:",
        active_cutter.name,
        "dims=",
        tuple(round(value, 3) for value in active_cutter.dimensions),
        "limit=",
        (round(max_cutter_x, 3), round(max_cutter_y, 3)),
    )


def apply_boolean_cut(base, active_cutter, base_x, base_y, plaque_thickness):
    """Apply one difference boolean cut, with rollback safety on failure."""
    bool_mod = base.modifiers.new(type="BOOLEAN", name=f"Cut_{active_cutter.name}")
    bool_mod.object = active_cutter
    bool_mod.operation = "DIFFERENCE"
    bool_mod.solver = "EXACT"

    bpy.context.view_layer.objects.active = base
    pre_cut_mesh = base.data.copy()
    bpy.ops.object.modifier_apply(modifier=bool_mod.name)

    dims = base.dimensions
    invalid_cut = (
        dims.x < base_x * 0.8
        or dims.y < base_y * 0.8
        or dims.z < plaque_thickness * 0.5
    )
    if invalid_cut:
        failed_mesh = base.data
        base.data = pre_cut_mesh
        if failed_mesh.users == 0:
            bpy.data.meshes.remove(failed_mesh)
        print(
            "[golf_tools] Reverted pathological cut:",
            active_cutter.name,
            "result_dims=",
            tuple(round(value, 3) for value in dims),
        )
        return False

    if pre_cut_mesh.users == 0:
        bpy.data.meshes.remove(pre_cut_mesh)
    return True


def cleanup_base_mesh(base):
    """Merge duplicate vertices and recalculate outward normals on base mesh."""
    if base.data is None:
        return

    import bmesh

    bm = bmesh.new()
    bm.from_mesh(base.data)

    # Ensure all vertices have proper positions (remove any degenerate geometry)
    # by recalculating normals first
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    # Check average normal Z and flip all faces if majority points downward
    if bm.faces:
        avg_z = sum(face.normal.z for face in bm.faces) / len(bm.faces)
        if avg_z < 0:
            bmesh.ops.reverse_faces(bm, faces=list(bm.faces))

    bm.to_mesh(base.data)
    bm.free()
    base.data.update()
