"""
Hole-In-One UI Panel
======================
Defines the Sidebar panel that exposes plaque dimensions and the
"Generate 3D Plaque" button in the **Golf** N-panel category.
"""

import bpy


class HOLEINONE_PT_Panel(bpy.types.Panel):
    """Sidebar panel for the Engrave Builder"""

    bl_label = "Engrave Builder"
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
        col.prop(props, "plaque_shape")

        layout.separator()
        layout.prop(props, "use_auto_thickness")
        if props.use_auto_thickness:
            sub = layout.column(align=True)
            sub.prop(props, "print_layer_height")
            sub.prop(props, "base_print_layers")
            sub.prop(props, "segment_print_layers")
        else:
            layout.prop(props, "plaque_thick")

        layout.separator()
        layout.prop(props, "generate_container")
        sub = layout.column(align=True)
        sub.enabled = props.generate_container
        sub.prop(props, "container_clearance")
        sub.prop(props, "container_wall_thickness")
        sub.prop(props, "container_back_thickness")
        sub.prop(props, "container_cavity_extra_depth")

        layout.separator()
        layout.prop(props, "text_mode")
        layout.prop(props, "text_extrusion_height")

        layout.separator()
        box = layout.box()
        row = box.row()
        row.prop(
            props,
            "show_advanced",
            icon="TRIA_DOWN" if props.show_advanced else "TRIA_RIGHT",
            emboss=False,
        )
        if props.show_advanced:
            col = box.column(align=True)
            col.prop(props, "use_top_taper")
            sub = col.column(align=True)
            sub.enabled = props.use_top_taper
            sub.prop(props, "top_taper_width")

            col.separator()
            col.prop(props, "use_stepped_walls")
            sub = col.column(align=True)
            sub.enabled = props.use_stepped_walls
            sub.prop(props, "stepped_wall_width")
            sub.prop(props, "stepped_wall_steps")

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


class HOLEINONE_PT_InsertPanel(bpy.types.Panel):
    """Sidebar panel for the Insert Builder.

    Generates a set of printable raised insert pieces (one per terrain layer)
    that slot into corresponding holes in their parent layer.  The finished
    inserts can be glued together to create a multi-colour, raised design.
    """

    bl_label = "Insert Builder"
    bl_idname = "HOLEINONE_PT_InsertPanel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Golf"

    def draw(self, context):
        layout = self.layout
        props = context.scene.golf_insert_props

        col = layout.column(align=True)
        col.label(text="Plaque Dimensions:")
        col.prop(props, "plaque_width")
        col.prop(props, "plaque_height")
        col.prop(props, "plaque_shape")
        col.prop(props, "plaque_thick")

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Print Settings:")
        col.prop(props, "print_layer_height")
        col.prop(props, "insert_element_layers")
        col.prop(props, "insert_hole_layers")

        # Show computed element height and hole depth as read-only info.
        element_h = props.insert_element_layers * props.print_layer_height
        hole_d = props.insert_hole_layers * props.print_layer_height
        info = col.column(align=True)
        info.enabled = False
        info.label(text=f"Element height: {element_h:.2f} mm")
        info.label(text=f"Hole depth:     {hole_d:.2f} mm")

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Fit / Clearance:")
        col.prop(props, "insert_clearance")
        col.prop(props, "deep_layer_clearance_bias")
        col.prop(props, "use_shrink_element")

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Text Options (Plaque Base):")
        col.prop(props, "text_mode")
        col.prop(props, "text_extrusion_height")

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Embossed Border (Base):")
        col.prop(props, "use_embossed_border")
        sub = col.column(align=True)
        sub.enabled = props.use_embossed_border
        sub.prop(props, "separate_border_insert")
        sub.prop(props, "border_inset")
        sub.prop(props, "border_width")

        layout.separator()
        layout.prop(props, "generate_container")
        sub = layout.column(align=True)
        sub.enabled = props.generate_container
        sub.prop(props, "container_clearance")
        sub.prop(props, "container_wall_thickness")
        sub.prop(props, "container_back_thickness")
        sub.prop(props, "container_cavity_extra_depth")

        layout.separator()
        layout.operator("object.build_inserts", icon="MESH_CUBE")


class HOLEINONE_PT_TopologyPanel(bpy.types.Panel):
    """Sidebar panel for the Topology Builder."""

    bl_label = "Topology Builder"
    bl_idname = "HOLEINONE_PT_TopologyPanel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Golf"

    def draw(self, context):
        layout = self.layout
        props = context.scene.golf_topology_props

        col = layout.column(align=True)
        col.label(text="LiDAR Input:")
        col.prop(props, "lidar_file_path")
        col.prop(props, "lidar_height_scale")
        col.prop(props, "topology_base_thickness")

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Plaque Dimensions:")
        col.prop(props, "plaque_width")
        col.prop(props, "plaque_height")
        col.prop(props, "plaque_shape")
        col.prop(props, "plaque_thick")

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Text Options:")
        col.prop(props, "text_mode")
        col.prop(props, "text_extrusion_height")

        layout.separator()
        layout.operator("object.build_topology", icon="MESH_GRID")
