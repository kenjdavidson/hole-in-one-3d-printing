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
    "version": (1, 0, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Golf",
    "description": "Generate a 3D-printable golf course commemorative plaque from SVG traces",
    "category": "Object",
}

import bpy
from . import geometry_utils
from . import ui_panel


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
    use_manual_scale: bpy.props.BoolProperty(
        name="Manual Scale Override",
        description=(
            "When enabled, scale is fitted to the largest imported SVG "
            "object instead of anchoring to Plaque_Base/Plaque_Frame "
            "(or Rough when no plaque base exists)"
        ),
        default=False,
    )
    generate_protective_frame: bpy.props.BoolProperty(
        name="Generate Protective Frame",
        description=(
            "When no Plaque_Base is imported from the SVG, automatically "
            "create a base slightly larger than the Rough area to form a "
            "protective lip around the carved surface"
        ),
        default=False,
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
