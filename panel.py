# SPDX-License-Identifier: GPL-2.0-or-later
import bpy
from bpy.types import Panel, VIEW3D_HT_tool_header

from .utils import GizmoUtils


class SimpleDeformHelperToolPanel(Panel, GizmoUtils):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Tool'
    bl_context = '.objectmode'
    bl_label = 'Simple Deform Helper'
    bl_idname = 'VIEW3D_PT_simple_deform_helper'
    bl_parent_id = 'VIEW3D_PT_tools_object_options'

    @classmethod
    def poll(cls, context):
        show_in_tool_options = GizmoUtils.pref_().show_gizmo_property_location == 'ToolOptions'
        return cls.poll_simple_deform_public(context) and show_in_tool_options

    def draw(self, context):
        if self.poll(context):
            self.draw_property(self.layout, context)

    @staticmethod
    def draw_property(layout, context):
        if GizmoUtils.poll_simple_deform_public(context):
            cls = SimpleDeformHelperToolPanel
            pref = cls.pref_()

            obj = context.object
            mod = obj.modifiers.active
            prop = obj.SimpleDeformGizmo_PropertyGroup

            ctrl_obj = mod.origin.SimpleDeformGizmo_PropertyGroup if mod.origin else prop

            layout.prop(ctrl_obj,
                        'origin_mode',
                        text='')
            layout.prop(pref,
                        'update_deform_wireframe',
                        icon='MOD_WIREFRAME',
                        text='')
            layout.prop(pref,
                        'show_set_axis_button',
                        icon='EMPTY_AXIS',
                        text='')
            if pref.modifier_deform_method_is_bend:
                layout.prop(pref,
                            'display_bend_axis_switch_gizmo',
                            toggle=1)
            layout.prop(pref,
                        'modifiers_limits_tolerance',
                        text='')

    def draw_settings(self, context):
        show_in_settings = GizmoUtils.pref_().show_gizmo_property_location == 'ToolSettings'
        if show_in_settings:
            SimpleDeformHelperToolPanel.draw_property(self.layout, context)


class_list = (
    SimpleDeformHelperToolPanel,
)

register_class, unregister_class = bpy.utils.register_classes_factory(class_list)


def register():
    register_class()
    VIEW3D_HT_tool_header.append(SimpleDeformHelperToolPanel.draw_settings)


def unregister():
    unregister_class()
    VIEW3D_HT_tool_header.remove(SimpleDeformHelperToolPanel.draw_settings)
