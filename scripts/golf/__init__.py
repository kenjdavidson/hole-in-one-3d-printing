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
    "version": (1, 1, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Golf",
    "description": (
        "Generate a 3D-printable golf course commemorative plaque from SVG traces. "
        "Supports CARVE, EMBOSS, and ENGRAVE element strategies per layer."
    ),
    "category": "Object",
}

import bpy
from . import geometry_utils
from . import ui_panel
from . import draft_angle       # noqa: F401 – registers the module for use by plaque_builder
from . import element_strategy  # noqa: F401 – ensures strategy registry is populated


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


# ── Registration ──────────────────────────────────────────────────────────────

_classes = (
    HOLEINONE_Properties,
    HOLEINONE_OT_Generate,
    ui_panel.HOLEINONE_PT_Panel,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.golf_props = bpy.props.PointerProperty(
        type=HOLEINONE_Properties
    )


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.golf_props


if __name__ == "__main__":
    register()
