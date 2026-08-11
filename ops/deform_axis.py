from bpy.app.translations import pgettext_iface as iface_
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from bpy.types import Operator

from ..utils import GizmoUtils


class SetDeformAxisOperator(Operator, GizmoUtils):
    bl_idname = "simple_deform_gizmo.set_deform_axis"
    bl_label = "Set Deform Axis"
    bl_description = "Set the axis used by the traditional Simple Deform modifier"
    bl_options = {"INTERNAL"}

    axis: EnumProperty(
        items=(
            ("X", "X", "Use the X axis"),
            ("Y", "Y", "Use the Y axis"),
            ("Z", "Z", "Use the Z axis"),
        ),
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return cls.poll_modifier_type_is_simple(context)

    def execute(self, context):
        modifier = context.object.modifiers.active
        if modifier.deform_axis == self.axis:
            return {"CANCELLED"}
        undo = self._legacy_undo_module()
        undo.begin(self, "Before Traditional Deform Axis")
        modifier.deform_axis = self.axis
        self.clear_point_cache()
        self.update_deform_wireframe(force=True)
        self.tag_redraw(context)
        undo.finish(self, message="Traditional Deform Axis")
        return {"FINISHED"}


class DeformAxisOperator(Operator, GizmoUtils):
    bl_idname = "simple_deform_gizmo.deform_axis"
    bl_label = "deform_axis"
    bl_description = "deform_axis operator"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return cls.poll_modifier_type_is_simple(context)

    Deform_Axis: StringProperty(default="X", options={"SKIP_SAVE"})
    z_rotate: StringProperty(default="X", options={"SKIP_SAVE"})

    X_Value: FloatProperty(default=-0, options={"SKIP_SAVE"})
    Y_Value: FloatProperty(default=-0, options={"SKIP_SAVE"})
    Z_Value: FloatProperty(default=-0, options={"SKIP_SAVE"})

    Is_Positive: BoolProperty(default=True, options={"SKIP_SAVE"})

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        self.clear_point_cache()
        mod = context.object.modifiers.active
        undo = self._legacy_undo_module()
        undo.begin(self, "Before Traditional Bend Axis")
        mod.deform_axis = self.Deform_Axis

        empty = self.new_origin_empty_object(force_managed=True)
        if empty is None:
            self.report({"INFO"}, iface_(
                "Deform axis changed; the user-supplied Origin was preserved"))
            self.pref.display_bend_axis_switch_gizmo = False
            undo.finish(self, message="Traditional Bend Axis")
            return {"FINISHED"}
        is_positive = self.number_is_positive(mod.angle)

        for limit, value in (("max_x", self.X_Value),
                             ("min_x", self.X_Value),
                             ("max_y", self.Y_Value),
                             ("min_y", self.Y_Value),
                             ("max_z", self.Z_Value),
                             ("min_z", self.Z_Value),
                             ):
            setattr(empty.constraints[self.G_NAME_CON_LIMIT], limit, value)

        if ((not is_positive) and self.Is_Positive) or (is_positive and (not self.Is_Positive)):
            mod.angle = mod.angle * -1

        if not event.ctrl:
            self.pref.display_bend_axis_switch_gizmo = False

        origin_object = empty
        origin_object.simple_deform_helper_rotate_axis = self.z_rotate
        origin_object.simple_deform_helper_rotate_xyz = (self.X_Value, self.Y_Value, self.Z_Value)
        undo.finish(self, message="Traditional Bend Axis")
        return {"FINISHED"}

    def cancel(self, context):
        undo = self._legacy_undo_module()
        undo.finish(self, cancel=True, message="Traditional Bend Axis")
