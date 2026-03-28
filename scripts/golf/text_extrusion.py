"""Text extrusion helpers for the golf plaque generator.

Text objects are imported as outlines and extruded upward from the plaque
top surface as raised features (not carved cutouts).
"""

import bpy

from .cutter_pipeline import CUTTER_TOP_POKE_MM


def extrude_text_objects(text_objects, plaque_thickness, extrusion_height, material, output_collection):
    """Extrude text objects upward from the plaque surface.
    
    Args:
        text_objects: List of text outline objects to extrude.
        plaque_thickness: Thickness of the base plaque in mm.
        extrusion_height: Height to extrude text above the plaque top in mm.
        material: Material to apply to all text objects.
        output_collection: Collection to move text objects into.
    """
    if not text_objects:
        return

    for text_obj in text_objects:
        if text_obj.data is None:
            continue

        # Position text flush with the top surface of the plaque so the
        # extrusion is directly connected to the base with no gap.
        text_obj.location.z = plaque_thickness / 2

        # Apply material
        if not text_obj.data.materials:
            text_obj.data.materials.append(material)

        # Add Solidify modifier to extrude the text outline upward
        solidify = text_obj.modifiers.new(name="Solidify", type="SOLIDIFY")
        solidify.thickness = extrusion_height
        solidify.offset = 1.0  # Extrude only upward (positive Z)

        # Apply the modifier to bake the extrusion
        bpy.context.view_layer.objects.active = text_obj
        bpy.ops.object.modifier_apply(modifier=solidify.name)

        # Move to output collection (alongside the base)
        for collection in text_obj.users_collection:
            collection.objects.unlink(text_obj)
        output_collection.objects.link(text_obj)

        print(
            "[golf_tools] Text extruded:",
            text_obj.name,
            "height=",
            round(extrusion_height, 2),
        )


def engrave_text_objects(
    text_objects,
    base,
    plaque_thickness,
    engrave_depth,
    material,
    cutters_collection,
):
    """Cut text objects downward into the plaque as engraved features."""
    if not text_objects:
        return

    for text_obj in text_objects:
        if text_obj.data is None:
            continue

        if not text_obj.data.materials:
            text_obj.data.materials.append(material)

        cutter = text_obj.copy()
        cutter.data = text_obj.data.copy()
        for collection in text_obj.users_collection:
            collection.objects.link(cutter)

        for collection in list(cutter.users_collection):
            collection.objects.unlink(cutter)
        cutters_collection.objects.link(cutter)

        # Normals-independent cutter: center the cutter thickness around the
        # target engraved band, so winding inconsistencies cannot flip letters.
        cutter.location.z = plaque_thickness / 2 - engrave_depth / 2

        solidify = cutter.modifiers.new(name="Solidify", type="SOLIDIFY")
        solidify.thickness = engrave_depth + (CUTTER_TOP_POKE_MM * 2)
        solidify.offset = 0.0
        solidify.use_even_offset = True
        solidify.use_quality_normals = True

        bpy.context.view_layer.objects.active = cutter
        bpy.ops.object.modifier_apply(modifier=solidify.name)

        bool_mod = base.modifiers.new(type="BOOLEAN", name=f"TextCut_{text_obj.name}")
        bool_mod.object = cutter
        bool_mod.operation = "DIFFERENCE"
        bool_mod.solver = "EXACT"

        bpy.context.view_layer.objects.active = base
        bpy.ops.object.modifier_apply(modifier=bool_mod.name)

        cutter.display_type = "WIRE"
        cutter.hide_render = True
        cutter.hide_viewport = True
        text_obj.hide_viewport = True
        text_obj.hide_render = True

        print(
            "[golf_tools] Text engraved:",
            text_obj.name,
            "depth=",
            round(engrave_depth, 2),
        )
