import math

from bpy.types import Gizmo, GizmoGroup
from mathutils import Matrix

from ..update import ChangeActiveModifierParameter
from ..utils import GizmoUtils, GizmoGroupUtils


class AngleUpdate(GizmoUtils):
    int_value_degrees: float
    tmp_value_angle: float

    def update_prop_value(self, event, tweak):
        def v(va):
            self.target_set_value("angle", math.radians(va))

        not_c_l = not event.alt and not event.ctrl
        is_only_shift = event.shift and not_c_l

        change_angle = self.get_delta(event)
        if is_only_shift:
            change_angle /= 50
        new_value = self.tmp_value_angle - change_angle
        old_value = self.target_get_value("angle")
        snap_value = self.get_snap(new_value, tweak)

        is_shift = event.type == "LEFT_SHIFT"
        is_release = event.value == "RELEASE"
        if is_only_shift:
            if event.value == "PRESS":
                self.init_mouse_region_x = event.mouse_region_x
                self.tmp_value_angle = int(math.degrees(old_value))
                v(self.tmp_value_angle)
                return

            value = (self.tmp_value_angle - change_angle) // 0.01 * 0.01
            v(value)
            return

        elif not_c_l and not event.shift and is_shift and is_release:
            self.init_mouse_region_x = event.mouse_region_x
            return
        v(snap_value)

    def update_gizmo_matrix(self, context):
        matrix = context.object.matrix_world
        point = self.modifier_bound_co[1]
        rot = matrix.to_quaternion().to_matrix().to_4x4()
        self.matrix_basis = rot
        self.matrix_basis.translation = matrix @ point

    def update_header_text(self, context):
        te = self.translate_text
        text = te(self.modifier.deform_method.title()) + "    "

        if self.modifier_is_use_angle_value:
            value = round(math.degrees(self.modifier_angle), 3)
            text += self.translate_header_text("Angle", value)
        else:
            value = round(self.modifier.factor, 3)
            text += self.translate_header_text("Coefficient", value)
        context.area.header_text_set(text)


class AngleGizmo(Gizmo, AngleUpdate):
    bl_idname = "ViewSimpleAngleGizmo"

    bl_target_properties = (
        {"id": "up_limits", "type": "FLOAT", "array_length": 1},
        {"id": "down_limits", "type": "FLOAT", "array_length": 1},
        {"id": "angle", "type": "FLOAT", "array_length": 1}
    )

    __slots__ = (
        "draw_type",
        "mouse_dpi",
        "empty_object",
        "custom_shape",
        "tmp_value_angle",
        "int_value_degrees",
        "init_mouse_region_y",
        "init_mouse_region_x",
    )

    def setup(self):
        self.init_setup()

    def invoke(self, context, event):
        self.init_invoke(context, event)
        self.int_value_degrees = self.target_get_value("angle")
        angle = math.degrees(self.int_value_degrees)
        self.tmp_value_angle = angle
        return {"RUNNING_MODAL"}

    def modal(self, context, event, tweak):
        self.clear_point_cache()

        self.update_prop_value(event, tweak)
        self.update_deform_wireframe()
        self.update_object_origin_matrix()
        self.update_header_text(context)
        ChangeActiveModifierParameter.update_modifier_parameter()
        self.tag_redraw(context)
        return self.event_handle(event)

    def exit(self, context, cancel):
        context.area.header_text_set(None)
        if cancel:
            self.target_set_value("angle", self.int_value_degrees)


class AngleGizmoGroup(GizmoGroup, GizmoGroupUtils):
    """ShowGizmo
    """
    bl_idname = "OBJECT_GGT_SimpleDeformGizmoGroup"
    bl_label = "AngleGizmoGroup"

    @classmethod
    def poll(cls, context):
        return cls.simple_deform_show_gizmo_poll(context)

    def setup(self, context):
        sd_name = AngleGizmo.bl_idname

        add_data = [
            ("angle",
             sd_name,
             {"draw_type": "SimpleDeform_GizmoGroup_",
              "color": (1.0, 0.5, 1.0),
              "alpha": 0.3,
              "color_highlight": (1.0, 1.0, 1.0),
              "alpha_highlight": 0.3,
              "use_draw_modal": True,
              "scale_basis": 0.1,
              "use_draw_value": True,
              "mouse_dpi": 5,
              }),
        ]

        self.generate_gizmo(add_data)

    def refresh(self, context):
        self.angle.target_set_prop("angle",
                                   context.object.modifiers.active,
                                   "angle")
