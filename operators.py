import bpy
from bpy.props import FloatProperty, StringProperty, BoolProperty
from bpy.types import Operator

from .utils import GizmoUtils


class DeformAxisOperator(Operator, GizmoUtils):
    bl_idname = 'simple_deform_gizmo.deform_axis'
    bl_label = 'deform_axis'
    bl_description = 'deform_axis operator'
    bl_options = {'REGISTER'}

    Deform_Axis: StringProperty(default='X', options={'SKIP_SAVE'})
    z_rotate: StringProperty(default='X', options={'SKIP_SAVE'})

    X_Value: FloatProperty(default=-0, options={'SKIP_SAVE'})
    Y_Value: FloatProperty(default=-0, options={'SKIP_SAVE'})
    Z_Value: FloatProperty(default=-0, options={'SKIP_SAVE'})

    Is_Positive: BoolProperty(default=True, options={'SKIP_SAVE'})

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        self.clear_point_cache()
        mod = context.object.modifiers.active
        mod.deform_axis = self.Deform_Axis

        empty = self.new_origin_empty_object()
        is_positive = self.number_is_positive(mod.angle)

        for limit, value in (('max_x', self.X_Value),
                             ('min_x', self.X_Value),
                             ('max_y', self.Y_Value),
                             ('min_y', self.Y_Value),
                             ('max_z', self.Z_Value),
                             ('min_z', self.Z_Value),
                             ):
            setattr(empty.constraints[self.G_NAME_CON_LIMIT], limit, value)

        if ((not is_positive) and self.Is_Positive) or (is_positive and (not self.Is_Positive)):
            mod.angle = mod.angle * -1

        if not event.ctrl:
            self.pref.display_bend_axis_switch_gizmo = False

        origin_object = empty
        origin_object.simple_deform_helper_rotate_axis = self.z_rotate
        origin_object.simple_deform_helper_rotate_xyz = (self.X_Value, self.Y_Value, self.Z_Value)


        return {'FINISHED'}


class Refresh(Operator, GizmoUtils):
    bl_idname = 'simple_deform_gizmo.refresh'
    bl_label = 'Refresh'

    def invoke(self, context, event):
        self.update_deform_wireframe()
        self.update_object_origin_matrix()
        return {"FINISHED"}


class_list = (
    DeformAxisOperator,
    Refresh,
)

register_class, unregister_class = bpy.utils.register_classes_factory(class_list)


def register():
    register_class()


def unregister():
    unregister_class()
