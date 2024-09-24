import bpy
from bpy.props import (FloatProperty,
                       FloatVectorProperty,
                       EnumProperty,
                       BoolProperty)
from bpy.types import AddonPreferences

from .utils import GizmoUtils


class SimpleDeformGizmoAddonPreferences(AddonPreferences, GizmoUtils):
    bl_idname = __package__

    deform_wireframe_color: FloatVectorProperty(
        name='Deform Wireframe',
        description='Draw Deform Wireframe Color',
        default=(1, 1, 1, 0.3),
        soft_max=1,
        soft_min=0,
        size=4, subtype='COLOR')
    bound_box_color: FloatVectorProperty(
        name='Bound Box',
        description='Draw Bound Box Color',
        default=(1, 0, 0, 0.5),
        soft_max=1,
        soft_min=0,
        size=4,
        subtype='COLOR')
    limits_bound_box_color: FloatVectorProperty(
        name='Upper and lower limit Bound Box Color',
        description='Draw Upper and lower limit Bound Box Color',
        default=(0.3, 1, 0.2, 0.5),
        soft_max=1,
        soft_min=0,
        size=4,
        subtype='COLOR')
    modifiers_limits_tolerance: FloatProperty(
        name='Upper and lower limit tolerance',
        description='Minimum value between upper and lower limits',
        default=0.05,
        max=1,
        min=0.0001
    )
    display_bend_axis_switch_gizmo: BoolProperty(
        name='Show Toggle Bend Axis Gizmo',
        default=False,
        options={'SKIP_SAVE'})

    update_deform_wireframe: BoolProperty(
        name='Show Deform Wireframe',
        default=False)

    show_wireframe_in_front: BoolProperty(name="In Front", default=False)

    show_set_axis_button: BoolProperty(
        name='Show Set Axis Button',
        default=False)

    show_gizmo_property_location: EnumProperty(
        name='Gizmo Property Show Location',
        items=[('ToolSettings', 'Tool Settings', ''),
               ('ToolOptions', 'Tool Options', ''),
               ],
        default='ToolSettings'
    )

    def draw(self, context):
        col = self.layout.column()
        box = col.box()
        for text in ("You can press the following shortcut keys when dragging values",
                     "    Wheel:   Switch Origin Ctrl Mode",
                     "    X,Y,Z:  Switch Modifier Deform Axis",
                     "    W:       Switch Deform Wireframe Show",
                     "    A:       Switch To Select Bend Axis Mode(deform_method=='BEND')",):
            box.label(text=text)

        col.prop(self, 'deform_wireframe_color')
        col.prop(self, 'bound_box_color')
        col.prop(self, 'limits_bound_box_color')

        col.label(text='Gizmo Property Show Location')
        col.prop(self, 'show_gizmo_property_location', expand=True)

    def draw_header_tool_settings(self, context):
        if GizmoUtils.poll_simple_deform_public(context):
            row = self.layout.row()
            obj = context.object
            mod = obj.modifiers.active

            row.separator(factor=0.2)
            row.prop(mod,
                     'deform_method',
                     expand=True)
            row.prop(mod,
                     'deform_axis',
                     expand=True)

            row = row.row(align=True)

            show_type = 'angle' if mod.deform_method in ('BEND', 'TWIST') else 'factor'
            row.prop(mod, show_type)

            from .gizmo.z_rotate import ZRotateGizmoGroup
            if ZRotateGizmoGroup.poll(context):
                row.prop(mod.origin, "simple_deform_helper_rotate_angle", text="Z Rotate")


def register():
    bpy.utils.register_class(SimpleDeformGizmoAddonPreferences)

    GizmoUtils.pref_().display_bend_axis_switch_gizmo = False
    bpy.types.VIEW3D_MT_editor_menus.append(SimpleDeformGizmoAddonPreferences.draw_header_tool_settings)


def unregister():
    bpy.utils.unregister_class(SimpleDeformGizmoAddonPreferences)
    bpy.types.VIEW3D_MT_editor_menus.remove(SimpleDeformGizmoAddonPreferences.draw_header_tool_settings)
