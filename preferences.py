# SPDX-License-Identifier: GPL-2.0-or-later

import os
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

from .data import G_ADDON_NAME
from .utils import Pref, Utils


class SimpleDeformGizmoAddonPreferences(AddonPreferences, Pref):
    bl_idname = G_ADDON_NAME

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
        default=(1, 0, 0, 0.1),
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
        name='Show Toggle Axis Gizmo',
        default=False,
        options={'SKIP_SAVE'})

    def draw(self, context):
        layout = self.layout
        if __name__ is None:
            from bpy.types import Panel
            layout = Panel.layout
        layout.prop(self, 'deform_wireframe_color')
        layout.prop(self, 'bound_box_color')
        layout.prop(self, 'limits_bound_box_color')
        layout.prop(self, 'modifiers_limits_tolerance')
        layout.prop(self, 'display_bend_axis_switch_gizmo')

    def draw_header_tool_settings(self, context):
        layout = self.layout
        if Utils.simple_deform_poll(context):
            layout.separator(factor=5)
            active_mod = context.object.modifiers.active
            prop = context.object.SimpleDeformGizmo_PropertyGroup
            pref = Pref._pref()

            if active_mod.origin:
                layout.prop(active_mod.origin.SimpleDeformGizmo_PropertyGroup,
                            'origin_mode',
                            text='')
            else:
                layout.prop(prop,
                            'origin_mode',
                            text='')
            layout.prop(pref,
                        'modifiers_limits_tolerance',
                        text='')
            if active_mod.deform_method == 'BEND':
                layout.prop(pref,
                            'display_bend_axis_switch_gizmo',
                            toggle=1)
            layout.separator(factor=0.5)
            layout.prop(active_mod,
                        'deform_method',
                        expand=True)
            layout.prop(active_mod,
                        'deform_axis',
                        expand=True)
            layout.prop(active_mod,
                        'angle')
            layout.prop(active_mod,
                        'factor')


class SimpleDeformGizmoObjectPropertyGroup(PropertyGroup):

    def _limits_up(self, context):
        mod = context.object.modifiers
        if mod and (mod.active.type == 'SIMPLE_DEFORM'):
            mod = mod.active
            mod.limits[1] = self.up_limits

    up_limits: FloatProperty(name='up',
                             description='UP Limits(Red)',
                             default=1,
                             update=_limits_up,
                             max=1,
                             min=0)

    def _limits_down(self, context):
        mod = context.object.modifiers
        if mod and (mod.active.type == 'SIMPLE_DEFORM'):
            mod = mod.active
            mod.limits[0] = self.down_limits

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

    Pref._pref().display_bend_axis_switch_gizmo = False
    bpy.types.Object.SimpleDeformGizmo_PropertyGroup = PointerProperty(
        type=SimpleDeformGizmoObjectPropertyGroup,
        name='SimpleDeformGizmo_PropertyGroup')
    bpy.types.VIEW3D_MT_editor_menus.append(
        SimpleDeformGizmoAddonPreferences.draw_header_tool_settings)


def unregister():
    unregister_class()
    bpy.types.VIEW3D_MT_editor_menus.remove(
        SimpleDeformGizmoAddonPreferences.draw_header_tool_settings)
