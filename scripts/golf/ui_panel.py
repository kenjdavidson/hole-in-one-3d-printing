"""
Hole-In-One UI Panel
======================
Defines the Sidebar panel that exposes plaque dimensions and the
"Generate 3D Plaque" button in the **Golf** N-panel category.
"""

import bpy


class HOLEINONE_PT_Panel(bpy.types.Panel):
    """Sidebar panel for the Hole-In-One Commemorative Generator"""

    bl_label = "Hole-In-One Generator"
    bl_idname = "HOLEINONE_PT_Panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Golf"

    def draw(self, context):
        layout = self.layout
        props = context.scene.golf_props

        col = layout.column(align=True)
        col.label(text="Plaque Dimensions:")
        col.prop(props, "plaque_width")
        col.prop(props, "plaque_height")
        col.prop(props, "use_auto_thickness")
        if props.use_auto_thickness:
            sub = col.column(align=True)
            sub.prop(props, "print_layer_height")
            sub.prop(props, "base_print_layers")
            sub.prop(props, "segment_print_layers")
        else:
            col.prop(props, "plaque_thick")

        layout.separator()
        layout.prop(props, "use_manual_scale")

        layout.separator()
        layout.prop(props, "generate_protective_frame")

        layout.separator()
        box = layout.box()
        row = box.row()
        row.prop(
            props,
            "show_advanced",
            icon="TRIA_DOWN" if props.show_advanced else "TRIA_RIGHT",
            emboss=False,
        )
        if props.show_advanced or props.use_manual_scale:
            col = box.column(align=True)
            col.prop(props, "use_draft_angle")
            sub = col.column(align=True)
            sub.enabled = props.use_draft_angle
            sub.prop(props, "draft_factor", slider=True)

            col.separator()
            col.prop(props, "use_floor_texture")

            col.separator()
            col.prop(props, "use_layer_depths")
            sub = col.column(align=True)
            sub.enabled = props.use_layer_depths
            sub.label(text="Layer Depths:")
            sub.prop(props, "depth_water")
            sub.prop(props, "depth_sand")
            sub.prop(props, "depth_green")
            sub.prop(props, "depth_fairway")

        layout.separator()
        layout.operator("object.generate_commemorative", icon="MESH_CUBE")
