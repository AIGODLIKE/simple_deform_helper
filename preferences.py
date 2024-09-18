# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
from bpy.props import (FloatProperty,
                       PointerProperty,
                       FloatVectorProperty,
                       EnumProperty,
                       BoolProperty)
from bpy.types import (
    AddonPreferences,
    PropertyGroup,
)

from .utils import GizmoUtils


class SimpleDeformGizmoAddonPreferences(AddonPreferences, GizmoUtils):
    bl_idname = GizmoUtils.G_ADDON_NAME

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

            show_type = 'angle' if mod.deform_method in ('BEND', 'TWIST') else 'factor'
            row.prop(mod, show_type)


class SimpleDeformGizmoObjectPropertyGroup(PropertyGroup, GizmoUtils):
    def _limits_up(self, context):
        if self.active_modifier_is_simple_deform:
            self.modifier.limits[1] = self.up_limits

    up_limits: FloatProperty(name='up',
                             description='UP Limits(Red)',
                             default=1,
                             update=_limits_up,
                             max=1,
                             min=0)

    def _limits_down(self, context):
        if self.active_modifier_is_simple_deform:
            self.modifier.limits[0] = self.down_limits

    down_limits: FloatProperty(name='down',
                               description='Lower limit(Green)',
                               default=0,
                               update=_limits_down,
                               max=1,
                               min=0)

    origin_mode_items = (
        ('UP_LIMITS',
         'Follow Upper Limit(Red)',
         'Add an empty object origin as the rotation axis (if there is an origin, do not add it), and set the origin '
         'position as the upper limit during operation'),
        ('DOWN_LIMITS',
         'Follow Lower Limit(Green)',
         'Add an empty object origin as the rotation axis (if there is an origin, do not add it), and set the origin '
         'position as the lower limit during operation'),
        ('LIMITS_MIDDLE',
         'Middle',
         'Add an empty object origin as the rotation axis (if there is an origin, do not add it), and set the '
         'origin position between the upper and lower limits during operation'),
        ('MIDDLE',
         'Bound Middle',
         'Add an empty object origin as the rotation axis (if there is an origin, do not add it), and set the origin '
         'position as the position between the bounding boxes during operation'),
        ('NOT', 'No origin operation', ''),
    )

    origin_mode: EnumProperty(name='Origin control mode',
                              default='NOT',
                              items=origin_mode_items)


class_list = (
    SimpleDeformGizmoAddonPreferences,
    SimpleDeformGizmoObjectPropertyGroup,
)

register_class, unregister_class = bpy.utils.register_classes_factory(class_list)


def register():
    register_class()

    GizmoUtils.pref_().display_bend_axis_switch_gizmo = False
    bpy.types.Object.SimpleDeformGizmo_PropertyGroup = PointerProperty(
        type=SimpleDeformGizmoObjectPropertyGroup,
        name='SimpleDeformGizmo_PropertyGroup')
    bpy.types.VIEW3D_MT_editor_menus.append(
        SimpleDeformGizmoAddonPreferences.draw_header_tool_settings)


def unregister():
    unregister_class()
    bpy.types.VIEW3D_MT_editor_menus.remove(
        SimpleDeformGizmoAddonPreferences.draw_header_tool_settings)
