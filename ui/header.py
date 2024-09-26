import bpy
from bpy.types import Panel, VIEW3D_HT_tool_header

from ..utils import GizmoUtils, get_pref


class SimpleDeformHelperToolHeader(Panel, GizmoUtils):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Tool'
    bl_context = '.objectmode'
    bl_label = 'Simple Deform Helper'
    bl_idname = 'VIEW3D_PT_simple_deform_helper'
    bl_parent_id = 'VIEW3D_PT_tools_object_options'

    @classmethod
    def poll(cls, context):
        show_in_tool_options = get_pref().show_gizmo_property_location == 'ToolOptions'
        return cls.poll_simple_deform_public(context) and show_in_tool_options

    def draw(self, context):
        if self.poll(context):
            self.draw_property(self.layout, context)

    @staticmethod
    def draw_property(layout, context):
        if GizmoUtils.poll_simple_deform_public(context):
            pref = get_pref()

            obj = context.object
            mod = obj.modifiers.active
            prop = obj.SimpleDeformGizmo_PropertyGroup

            ctrl_obj = mod.origin.SimpleDeformGizmo_PropertyGroup if mod.origin else prop

            row = layout.row(align=True)
            row.prop(ctrl_obj,
                     'origin_mode',
                     text='')
            row.prop(pref,
                     'update_deform_wireframe',
                     icon='MOD_WIREFRAME',
                     text='')
            row.prop(pref,
                     'show_set_axis_button',
                     icon='EMPTY_AXIS',
                     text='')
            row.prop(pref,
                     'show_wireframe_in_front',
                     icon='AXIS_FRONT',
                     text='')
            if pref.modifier_deform_method_is_bend:
                row.prop(pref,
                         'display_bend_axis_switch_gizmo',
                         toggle=1)
            row.prop(pref,
                     'modifiers_limits_tolerance',
                     text='')

    def draw_settings(self, context):
        show_in_settings = get_pref().show_gizmo_property_location == 'ToolSettings'
        if show_in_settings:
            SimpleDeformHelperToolHeader.draw_property(self.layout, context)


def register():
    bpy.utils.register_class(SimpleDeformHelperToolHeader)
    VIEW3D_HT_tool_header.append(SimpleDeformHelperToolHeader.draw_settings)


def unregister():
    bpy.utils.unregister_class(SimpleDeformHelperToolHeader)
    VIEW3D_HT_tool_header.remove(SimpleDeformHelperToolHeader.draw_settings)
