"""Container generation helpers for the golf plaque generator."""

import bpy

from .collection_utils import move_object_to_collection

CONTAINER_OBJECT_NAME = "HoleInOneContainer"

_CONTAINER_CUTTER_POKE_MM = 0.5


def _apply_difference(target, cutter):
    modifier = target.modifiers.new(type="BOOLEAN", name=f"Cut_{cutter.name}")
    modifier.object = cutter
    modifier.operation = "DIFFERENCE"
    modifier.solver = "EXACT"
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.modifier_apply(modifier=modifier.name)


def _create_box(name, dimensions, location, collection):
    bpy.ops.mesh.primitive_cube_add(size=1)
    obj = bpy.context.active_object
    obj.name = name
    move_object_to_collection(obj, collection)
    obj.scale = dimensions
    bpy.ops.object.transform_apply(scale=True)
    obj.location = location
    return obj


def build_container(props, base, strap_holes, output_collection, cutters_collection):
    """Create a fitted container and cut matching strap-hole openings."""
    clearance = float(max(0.0, props.container_clearance))
    wall_thickness = float(max(0.1, props.container_wall_thickness))
    back_thickness = float(max(0.1, props.container_back_thickness))
    cavity_extra_depth = float(max(0.0, getattr(props, "container_cavity_extra_depth", 0.0)))

    plaque_x = float(base.dimensions.x)
    plaque_y = float(base.dimensions.y)
    plaque_z = float(base.dimensions.z)

    cavity_x = plaque_x + (clearance * 2.0)
    cavity_y = plaque_y + (clearance * 2.0)
    cavity_depth = plaque_z + clearance + cavity_extra_depth

    container_x = cavity_x + (wall_thickness * 2.0)
    container_y = cavity_y + (wall_thickness * 2.0)
    container_z = cavity_depth + back_thickness

    offset_x = (plaque_x * 0.5) + (container_x * 0.5) + 5.0
    container_location = (offset_x, 0.0, 0.0)

    container = _create_box(
        CONTAINER_OBJECT_NAME,
        (container_x, container_y, container_z),
        container_location,
        output_collection,
    )

    cavity_top_z = container.location.z + (container_z * 0.5)
    cavity_location = (
        container.location.x,
        container.location.y,
        cavity_top_z - (cavity_depth * 0.5) + _CONTAINER_CUTTER_POKE_MM,
    )
    cavity_cutter = _create_box(
        f"{CONTAINER_OBJECT_NAME}_Cavity_Cutter",
        (cavity_x, cavity_y, cavity_depth + _CONTAINER_CUTTER_POKE_MM),
        cavity_location,
        cutters_collection,
    )
    _apply_difference(container, cavity_cutter)
    cavity_cutter.display_type = "WIRE"
    cavity_cutter.hide_render = True

    for strap_hole in strap_holes:
        hole_copy = strap_hole.copy()
        if strap_hole.data is not None:
            hole_copy.data = strap_hole.data.copy()
        cutters_collection.objects.link(hole_copy)

        solidify = hole_copy.modifiers.new(name="Solidify", type="SOLIDIFY")
        solidify.thickness = container_z + 2.0
        solidify.offset = -1.0

        hole_copy.location.x += container.location.x
        hole_copy.location.y += container.location.y
        hole_copy.location.z = cavity_top_z + _CONTAINER_CUTTER_POKE_MM

        bpy.context.view_layer.objects.active = hole_copy
        bpy.ops.object.modifier_apply(modifier=solidify.name)

        _apply_difference(container, hole_copy)
        hole_copy.display_type = "WIRE"
        hole_copy.hide_render = True

    container.select_set(True)
    bpy.context.view_layer.objects.active = container

    print(
        "[golf_tools] Container generated:",
        container.name,
        "location=",
        tuple(round(value, 3) for value in container.location),
        "cavity_extra_depth=",
        round(cavity_extra_depth, 3),
        "strap_holes=",
        len(strap_holes),
    )

    return container
