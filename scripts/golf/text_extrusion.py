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

        previous_active = bpy.context.view_layer.objects.active
        bpy.context.view_layer.objects.active = text_obj

        # Merge coincident (duplicate) vertices produced by the SVG curve
        # importer.  When Blender converts spline curves to mesh it can emit
        # the shared endpoint of two adjacent segments as two separate
        # vertices at the same (or near-same) position.  Those degenerate
        # zero-area edges/faces have unpredictable normals and Solidify can
        # extrude them as small downward-pointing spikes.  A tiny merge
        # threshold (0.0001 units) is safe for all letter geometry.
        weld = text_obj.modifiers.new(name="Weld", type="WELD")
        weld.merge_threshold = 0.0001
        bpy.ops.object.modifier_apply(modifier=weld.name)

        # Triangulate the flat mesh before solidifying.  Letters with inner
        # loops (R, O, A, B, D, P …) produce N-gon faces with holes after
        # curve-to-mesh conversion.  Solidify applied directly to those faces
        # leaves the inner-loop edges non-manifold, causing open boundaries
        # that slicers like Cura report as "not watertight".  Triangulating
        # first converts every face — including holed N-gons — into clean
        # triangles so Solidify always closes into a proper solid volume.
        tri = text_obj.modifiers.new(name="Triangulate", type="TRIANGULATE")
        tri.quad_method = "BEAUTY"
        tri.ngon_method = "BEAUTY"
        bpy.ops.object.modifier_apply(modifier=tri.name)

        # Add Solidify modifier to extrude the text outline upward.
        # use_quality_normals ensures consistent extrusion direction and avoids
        # faces being pushed downward when winding is locally inconsistent.
        # Note: use_even_offset is intentionally omitted — it compensates corner
        # angles using a 1/cos(half-angle) factor which blows up at very sharp
        # concave corners (serif notches, inner angles of R, S, ...) and produces
        # self-intersecting triangular spike geometry on the side walls.  Without
        # even offset the extrusion uses a simple flat push in the normal
        # direction, which is spike-free and produces the expected smooth top face.
        solidify = text_obj.modifiers.new(name="Solidify", type="SOLIDIFY")
        solidify.thickness = extrusion_height
        solidify.offset = 1.0  # Extrude only upward (positive Z)
        solidify.use_quality_normals = True

        # Apply the modifier to bake the extrusion
        bpy.ops.object.modifier_apply(modifier=solidify.name)

        bpy.context.view_layer.objects.active = previous_active

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
