import bpy
from bpy.types import Panel

from ..ops import KeyFrame, RemoveFrame
from ..utils import PublicPoll, get_pref


class Info:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"


class SimpleDeformPanel(Panel, Info):
    bl_idname = 'SIMPLE_DEFORM_PT_PANEL'
    bl_label = 'Simple Deform Helper'

    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return PublicPoll.poll_simple_deform_public(context)

    def draw(self, context):
        ...


class SimpleDeformPropertyPanel(Panel, Info):
    bl_idname = 'SIMPLE_DEFORM_PROPERTY_PT_PANEL'
    bl_label = 'Property'

    bl_parent_id = SimpleDeformPanel.bl_idname

    # bl_options = {"HIDE_HEADER"}

    def draw(self, context):
        layout = self.layout
        layout.scale_y = 1.2
        column = layout.column(align=True)

        pref = get_pref()

        obj = context.object
        mod = obj.modifiers.active
        prop = obj.SimpleDeformGizmo_PropertyGroup

        ctrl_obj = mod.origin.SimpleDeformGizmo_PropertyGroup if mod.origin else prop

        column.prop(ctrl_obj,
                    'origin_mode',
                    text='')
        column.prop(pref,
                    'update_deform_wireframe',
                    icon='MOD_WIREFRAME', )
        column.prop(pref,
                    'show_set_axis_button',
                    icon='EMPTY_AXIS', )
        column.prop(pref,
                    'show_wireframe_in_front',
                    icon='AXIS_FRONT', )
        if pref.modifier_deform_method_is_bend:
            column.prop(pref,
                        'display_bend_axis_switch_gizmo',
                        toggle=1)
        column.prop(pref,
                    'modifiers_limits_tolerance',
                    text='')


class SimpleDeformAnimatedPanel(Panel, Info):
    bl_idname = 'SIMPLE_DEFORM_ANIMATED_PT_PANEL'
    bl_label = 'Animated'

    bl_parent_id = SimpleDeformPanel.bl_idname

    # bl_options = {"HIDE_HEADER"}

    def draw(self, context):
        layout = self.layout
        layout.scale_y = 1.2
        row = layout.row(align=True)
        row.operator(KeyFrame.bl_idname)
        row.operator(RemoveFrame.bl_idname)


classes = [
    SimpleDeformPanel,
    SimpleDeformPropertyPanel,
    SimpleDeformAnimatedPanel
]
reg_class, un_reg_class = bpy.utils.register_classes_factory(classes)


def register():
    reg_class()


def unregister():
    un_reg_class()
