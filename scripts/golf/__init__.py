"""
Hole-In-One Commemorative Generator – Blender Addon
=====================================================
Entry point for the Hole-In-One Commemorative Generator addon.  Registers the
PropertyGroup, Operator, and Sidebar panel that together let you convert an
imported SVG golf-course trace into a layered, 3D-printable plaque.

Install this addon by zipping the ``golf/`` folder and installing it
via ``Edit > Preferences > Add-ons > Install``, or by copying/symlinking the
folder into Blender's user addons directory.

Workflow
--------
1. **Inkscape** – draw a 100 × 140 mm box named ``Rough``, trace course
   features (Green, Sand, Water, …), convert everything to Paths
   (``Path > Object to Path``), and save as **Plain SVG**.
2. **Blender** – import the SVG, then open the **Golf** tab in the Sidebar
   (press ``N`` in the 3D Viewport) and click **Generate 3D Plaque**.
"""

bl_info = {
    "name": "Hole-In-One Commemorative Generator",
    "author": "Ken J. Davidson",
    "version": (1, 2, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Golf",
    "description": (
        "Generate a 3D-printable golf course commemorative plaque from SVG traces. "
        "Supports CARVE, EMBOSS, and ENGRAVE element strategies per layer, plus a "
        "separate Insert Builder that produces raised insert pieces for each terrain."
    ),
    "category": "Object",
}

import bpy
from . import geometry_utils
from . import ui_panel
from . import draft_angle       # noqa: F401 – registers the module for use by plaque_builder
from . import element_strategy  # noqa: F401 – ensures strategy registry is populated
from . import insert_builder    # noqa: F401 – registers the insert pipeline module


# ── PropertyGroup ─────────────────────────────────────────────────────────────


class HOLEINONE_Properties(bpy.types.PropertyGroup):
    """Scene-level properties for the Hole-In-One plaque generator."""

    plaque_width: bpy.props.FloatProperty(
        name="Width (mm)",
        description="Plaque width in millimetres",
        default=100.0,
        min=10.0,
    )
    plaque_height: bpy.props.FloatProperty(
        name="Height (mm)",
        description="Plaque height in millimetres",
        default=140.0,
        min=10.0,
    )
    plaque_thick: bpy.props.FloatProperty(
        name="Thickness (mm)",
        description="Plaque thickness in millimetres",
        default=6.0,
        min=1.0,
    )
    use_auto_thickness: bpy.props.BoolProperty(
        name="Auto Thickness (Layer Based)",
        description=(
            "Compute total plaque thickness from print layer height, base "
            "layers, and detected golf segments"
        ),
        default=True,
    )
    print_layer_height: bpy.props.FloatProperty(
        name="Print Layer Height (mm)",
        description="Per-layer print height used to compute plaque thickness",
        default=0.2,
        min=0.05,
        max=1.0,
        precision=3,
    )
    base_print_layers: bpy.props.IntProperty(
        name="Base Layers",
        description="Minimum solid base layers before carved segments",
        default=3,
        min=3,
    )
    segment_print_layers: bpy.props.IntProperty(
        name="Layers per Segment",
        description="Printed layers allocated to each detected golf segment",
        default=3,
        min=1,
    )
    generate_container: bpy.props.BoolProperty(
        name="Generate Container",
        description=(
            "Create a printable container with a cavity sized to the plaque "
            "outline and optional clearance"
        ),
        default=False,
    )
    container_clearance: bpy.props.FloatProperty(
        name="Container Clearance (mm)",
        description="Gap added per side between plaque and container cavity",
        default=0.25,
        min=0.0,
        max=2.0,
        precision=3,
    )
    container_wall_thickness: bpy.props.FloatProperty(
        name="Container Wall (mm)",
        description="Container wall thickness around the cavity",
        default=2.0,
        min=0.5,
        max=10.0,
        precision=3,
    )
    container_back_thickness: bpy.props.FloatProperty(
        name="Container Back (mm)",
        description="Solid back thickness below the cavity",
        default=2.0,
        min=0.5,
        max=10.0,
        precision=3,
    )
    container_cavity_extra_depth: bpy.props.FloatProperty(
        name="Container Cavity Extra Depth (mm)",
        description=(
            "Extra cavity depth beyond plaque thickness so the container walls "
            "stand proud above the inserted part"
        ),
        default=0.5,
        min=0.0,
        max=10.0,
        precision=3,
    )
    text_extrusion_height: bpy.props.FloatProperty(
        name="Text Height/Depth (mm)",
        description=(
            "Emboss height above plaque surface or engrave depth below surface "
            "for Text.XXX objects"
        ),
        default=1.0,
        min=0.1,
        max=10.0,
        precision=2,
    )
    text_mode: bpy.props.EnumProperty(
        name="Text Mode",
        description="Choose whether Text.XXX is raised or cut into the plaque",
        items=(
            ("EMBOSS", "Emboss", "Raise text above the top surface"),
            ("ENGRAVE", "Engrave", "Cut text into the top surface"),
        ),
        default="EMBOSS",
    )
    show_advanced: bpy.props.BoolProperty(
        name="Advanced Settings",
        description="Show advanced carving options",
        default=False,
    )
    use_top_taper: bpy.props.BoolProperty(
        name="Use Top Taper",
        description=(
            "Expand only the top perimeter of each cutter before boolean, "
            "creating a uniform drafted wall"
        ),
        default=False,
    )
    top_taper_width: bpy.props.FloatProperty(
        name="Top Taper Width (mm)",
        description="Outward offset applied only to the top perimeter",
        default=0.6,
        min=0.0,
        max=5.0,
        precision=3,
    )
    use_stepped_walls: bpy.props.BoolProperty(
        name="Use Stepped Walls",
        description=(
            "Create a visible terraced wall by stacking multiple shallower, "
            "progressively wider cutters"
        ),
        default=False,
    )
    stepped_wall_width: bpy.props.FloatProperty(
        name="Stepped Wall Width (mm)",
        description="Total added width from deepest cut to top-most terrace",
        default=1.5,
        min=0.0,
        max=10.0,
        precision=3,
    )
    stepped_wall_steps: bpy.props.IntProperty(
        name="Stepped Wall Steps",
        description="Number of stacked terraces used to approximate an angle",
        default=3,
        min=2,
        max=10,
    )
    use_floor_texture: bpy.props.BoolProperty(
        name="Floor Texturing",
        description=(
            "Add a procedural displacement texture to the floor of Water "
            "(Musgrave ripple) and Sand (Clouds grain) cutters"
        ),
        default=False,
    )
    use_layer_depths: bpy.props.BoolProperty(
        name="Custom Layer Depths",
        description=(
            "Override the default carved depth for each layer type. "
            "Values are clamped to the plaque thickness to prevent cut-through"
        ),
        default=False,
    )
    depth_water: bpy.props.FloatProperty(
        name="Water (mm)",
        description="Carved depth of Water layers in millimetres",
        default=3.0,
        min=0.1,
        precision=2,
    )
    depth_sand: bpy.props.FloatProperty(
        name="Sand (mm)",
        description="Carved depth of Sand layers in millimetres",
        default=2.4,
        min=0.1,
        precision=2,
    )
    depth_green: bpy.props.FloatProperty(
        name="Green (mm)",
        description="Carved depth of Green layers in millimetres",
        default=1.8,
        min=0.1,
        precision=2,
    )
    depth_fairway: bpy.props.FloatProperty(
        name="Fairway (mm)",
        description="Carved depth of Fairway layers in millimetres",
        default=1.2,
        min=0.1,
        precision=2,
    )


# ── Operator ─────────────────────────────────────────────────────────────────


class HOLEINONE_OT_Generate(bpy.types.Operator):
    """Build the commemorative plaque from imported SVG objects"""

    bl_idname = "object.generate_commemorative"
    bl_label = "Generate 3D Plaque"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.golf_props
        geometry_utils.carve_plaque(props)
        self.report({"INFO"}, "Plaque generated successfully")
        return {"FINISHED"}


# ── Insert-builder PropertyGroup ──────────────────────────────────────────────


class HOLEINONE_InsertProperties(bpy.types.PropertyGroup):
    """Scene-level properties for the Insert Builder."""

    plaque_width: bpy.props.FloatProperty(
        name="Width (mm)",
        description="Plaque width in millimetres",
        default=100.0,
        min=10.0,
    )
    plaque_height: bpy.props.FloatProperty(
        name="Height (mm)",
        description="Plaque height in millimetres",
        default=140.0,
        min=10.0,
    )
    plaque_thick: bpy.props.FloatProperty(
        name="Base Thickness (mm)",
        description="Thickness of the base plaque that receives the outermost insert",
        default=6.0,
        min=1.0,
    )
    print_layer_height: bpy.props.FloatProperty(
        name="Print Layer Height (mm)",
        description="Per-layer print height used to compute element and hole depths",
        default=0.2,
        min=0.05,
        max=1.0,
        precision=3,
    )
    insert_element_layers: bpy.props.IntProperty(
        name="Element Layers",
        description=(
            "Number of print layers that determine each insert piece height. "
            "element_height = insert_element_layers × print_layer_height"
        ),
        default=4,
        min=1,
    )
    insert_hole_layers: bpy.props.IntProperty(
        name="Hole Layers",
        description=(
            "Number of print layers that determine the depth of the receiving "
            "hole carved into each parent piece. "
            "hole_depth = insert_hole_layers × print_layer_height"
        ),
        default=2,
        min=1,
    )
    insert_clearance: bpy.props.FloatProperty(
        name="Clearance (mm)",
        description=(
            "Per-side gap between each insert piece and its receiving hole. "
            "Typical values: 0.2–0.25 mm"
        ),
        default=0.25,
        min=0.0,
        max=2.0,
        precision=3,
    )
    deep_layer_clearance_bias: bpy.props.FloatProperty(
        name="Deep Layer Bias (mm)",
        description=(
            "Extra clearance added to Green/Tee/Sand/Water layer pockets when "
            "geometry safety limits prevent tight fit on inner layers. "
            "Try 0.1–0.15 if deep layers don't fit. Default 0.0."
        ),
        default=0.0,
        min=0.0,
        max=1.0,
        precision=3,
    )
    use_shrink_element: bpy.props.BoolProperty(
        name="Shrink Insert",
        description=(
            "When enabled, shrink the insert outline by the clearance amount "
            "so it fits inside a hole sized to the raw SVG outline. "
            "When disabled, keep the insert at full SVG size and grow the "
            "receiving hole instead"
        ),
        default=True,
    )
    text_extrusion_height: bpy.props.FloatProperty(
        name="Text Height/Depth (mm)",
        description=(
            "Emboss height above base surface or engrave depth below surface "
            "for Text.XXX objects in Insert Builder"
        ),
        default=1.0,
        min=0.1,
        max=10.0,
        precision=2,
    )
    text_mode: bpy.props.EnumProperty(
        name="Text Mode",
        description="Choose whether Text.XXX is embossed or engraved on the base",
        items=(
            ("EMBOSS", "Emboss", "Raise text above the top surface"),
            ("ENGRAVE", "Engrave", "Cut text into the top surface"),
        ),
        default="EMBOSS",
    )
    generate_container: bpy.props.BoolProperty(
        name="Generate Container",
        description=(
            "Create a printable container with a cavity sized to the insert "
            "base and optional clearance"
        ),
        default=False,
    )
    container_clearance: bpy.props.FloatProperty(
        name="Container Clearance (mm)",
        description="Gap added per side between insert base and container cavity",
        default=0.25,
        min=0.0,
        max=2.0,
        precision=3,
    )
    container_wall_thickness: bpy.props.FloatProperty(
        name="Container Wall (mm)",
        description="Container wall thickness around the cavity",
        default=2.0,
        min=0.5,
        max=10.0,
        precision=3,
    )
    container_back_thickness: bpy.props.FloatProperty(
        name="Container Back (mm)",
        description="Solid back thickness below the cavity",
        default=2.0,
        min=0.5,
        max=10.0,
        precision=3,
    )
    container_cavity_extra_depth: bpy.props.FloatProperty(
        name="Container Cavity Extra Depth (mm)",
        description=(
            "Extra cavity depth beyond insert base thickness so the container "
            "walls stand proud above the inserted assembly"
        ),
        default=0.5,
        min=0.0,
        max=10.0,
        precision=3,
    )
    use_embossed_border: bpy.props.BoolProperty(
        name="Embossed Border",
        description="Add a raised border ring around the outside of the base",
        default=False,
    )
    separate_border_insert: bpy.props.BoolProperty(
        name="Separate Border Insert",
        description=(
            "Generate the border as a separate ring with a matching socket cut "
            "into the base so it can be glued in"
        ),
        default=False,
    )
    border_inset: bpy.props.FloatProperty(
        name="Border Inset (mm)",
        description="Inset distance from the base edge to the outer border edge",
        default=0.0,
        min=0.0,
        max=20.0,
        precision=3,
    )
    border_width: bpy.props.FloatProperty(
        name="Border Width (mm)",
        description="Width of the raised border ring",
        default=0.8,
        min=0.05,
        max=20.0,
        precision=3,
    )


# ── Insert-builder Operator ───────────────────────────────────────────────────


class HOLEINONE_OT_BuildInserts(bpy.types.Operator):
    """Build printable insert pieces from the imported SVG golf-course layers"""

    bl_idname = "object.build_inserts"
    bl_label = "Build Insert Pieces"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        insert_builder.build_inserts(context.scene.golf_insert_props)
        self.report({"INFO"}, "Insert pieces generated successfully")
        return {"FINISHED"}


# ── Registration ──────────────────────────────────────────────────────────────

_classes = (
    HOLEINONE_Properties,
    HOLEINONE_OT_Generate,
    HOLEINONE_InsertProperties,
    HOLEINONE_OT_BuildInserts,
    ui_panel.HOLEINONE_PT_Panel,
    ui_panel.HOLEINONE_PT_InsertPanel,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.golf_props = bpy.props.PointerProperty(
        type=HOLEINONE_Properties
    )
    bpy.types.Scene.golf_insert_props = bpy.props.PointerProperty(
        type=HOLEINONE_InsertProperties
    )


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.golf_props
    del bpy.types.Scene.golf_insert_props


if __name__ == "__main__":
    register()
