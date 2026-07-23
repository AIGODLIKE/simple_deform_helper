import math

from bpy.types import Gizmo, GizmoGroup
from mathutils import Matrix

from ..update import ChangeActiveModifierParameter
from ..utils import GizmoUtils, GizmoGroupUtils


class AngleUpdate(GizmoUtils):
    initial_value: float

    def update_prop_value(self, event, tweak):
        raw_delta = self.get_delta(event)
        precise = event.shift or "PRECISE" in tweak
        snap = event.ctrl or "SNAP" in tweak

        if self.modifier_is_use_angle_value:
            delta = math.radians(raw_delta)
            if precise:
                delta /= 10.0
            value = self.initial_value - delta
            if snap:
                step = math.radians(5.0)
                value = round(value / step) * step
        else:
            delta = raw_delta * 0.01
            if precise:
                delta /= 10.0
            value = self.initial_value - delta
            if snap:
                value = round(value * 10.0) / 10.0

        self.target_set_value("value", value)

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
        if self.pref.show_drag_hud:
            text += "    |    X/Y/Z Axis · Wheel Origin · W Wire · A Bend Axis · Shift Precise"
        context.area.header_text_set(text)


class AngleGizmo(Gizmo, AngleUpdate):
    bl_idname = "ViewSimpleAngleGizmo"

    bl_target_properties = (
        {"id": "value", "type": "FLOAT", "array_length": 1},
    )

    __slots__ = (
        "draw_type",
        "mouse_dpi",
        "empty_object",
        "custom_shape",
        "initial_value",
        "init_mouse_region_y",
        "init_mouse_region_x",
    )

    def setup(self):
        self.init_setup()

    def invoke(self, context, event):
        self.init_invoke(context, event)
        self.initial_value = self.target_get_value("value")
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
            self.target_set_value("value", self.initial_value)
        self.update_multiple_modifiers_data()
        self.update_deform_wireframe(force=True)


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
        modifier = context.object.modifiers.active
        property_name = (
            "angle" if modifier.deform_method in {"BEND", "TWIST"}
            else "factor"
        )
        self.angle.target_set_prop("value", modifier, property_name)
