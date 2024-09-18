import math

from bpy.types import GizmoGroup,Gizmo
from mathutils import Euler, Vector

from ..utils import GizmoUtils, GizmoGroupUtils


class CustomGizmo(Gizmo, GizmoUtils):
    """Draw Custom Gizmo"""
    bl_idname = '_Custom_Gizmo'
    draw_type: str
    custom_shape: dict

    def setup(self):
        self.init_setup()

    def draw(self, context):
        self.draw_custom_shape(self.custom_shape[self.draw_type])

    def draw_select(self, context, select_id):
        self.draw_custom_shape(
            self.custom_shape[self.draw_type], select_id=select_id)

    def invoke(self, context, event):
        self.init_invoke(context, event)
        return {'RUNNING_MODAL'}

    def modal(self, context, event, tweak):
        self.update_empty_matrix()
        return {'RUNNING_MODAL'}


class BendAxiSwitchGizmoGroup(GizmoGroup, GizmoGroupUtils):
    bl_idname = 'OBJECT_GGT_SimpleDeformGizmoGroup_display_bend_axis_switch_gizmo'
    bl_label = 'SimpleDeformGizmoGroup_display_bend_axis_switch_gizmo'

    @classmethod
    def poll(cls, context):
        return cls.poll_simple_deform_show_bend_axis_witch(context)

    def setup(self, context):
        _draw_type = 'SimpleDeform_Bend_Direction_'
        _color_a = 1, 0, 0
        _color_b = 0, 1, 0

        for na, axis, rot, positive in (
                ('top_a', 'X', (math.radians(90), 0, math.radians(90)), True),
                ('top_b', 'X', (math.radians(90), 0, 0), True),

                ('bottom_a', 'X', (math.radians(90), 0, math.radians(90)), False),
                ('bottom_b', 'X', (math.radians(90), 0, 0), False),

                ('left_a', 'Y', (math.radians(90), 0, 0), False),
                ('left_b', 'Y', (0, 0, 0), False),

                ('right_a', 'Y', (math.radians(90), 0, 0), True),
                ('right_b', 'Y', (0, 0, 0), True),

                ('front_a', 'Z', (0, 0, 0), False),
                ('front_b', 'X', (0, 0, 0), False),

                ('back_a', 'Z', (0, 0, 0), True),
                ('back_b', 'X', (0, 0, 0), True),):
            _a = (na.split('_')[1] == 'a')
            setattr(self, na, self.gizmos.new(CustomGizmo.bl_idname))
            gizmo = getattr(self, na)
            gizmo.mode = na
            gizmo.draw_type = _draw_type
            gizmo.color = _color_a if _a else _color_b
            gizmo.alpha = 0.3
            gizmo.color_highlight = 1.0, 1.0, 1.0
            gizmo.alpha_highlight = 1
            gizmo.use_draw_modal = True
            gizmo.scale_basis = 0.2
            gizmo.use_draw_value = True
            ops = gizmo.target_set_operator(
                'simple_deform_gizmo.deform_axis')
            ops.Deform_Axis = axis
            ops.X_Value = rot[0]
            ops.Y_Value = rot[1]
            ops.Z_Value = rot[2]
            ops.Is_Positive = positive

    def draw_prepare(self, context):
        ob = context.object
        mat = ob.matrix_world
        top, bottom, left, right, front, back = self.modifier_bound_box_pos

        rad = math.radians
        for_list = (
            ('top_a', top, (0, 0, 0),),
            ('top_b', top, (0, 0, rad(90)),),

            ('bottom_a', bottom, (0, rad(180), 0),),
            ('bottom_b', bottom, (0, rad(180), rad(90)),),

            ('left_a', left, (rad(-90), 0, rad(90)),),
            ('left_b', left, (0, rad(-90), 0),),

            ('right_a', right, (rad(90), 0, rad(90)),),
            ('right_b', right, (0, rad(90), 0),),

            ('front_a', front, (rad(90), 0, 0),),
            ('front_b', front, (rad(90), rad(90), 0),),

            ('back_a', back, (rad(-90), 0, 0),),
            ('back_b', back, (rad(-90), rad(-90), 0),),
        )
        for i, j, w, in for_list:
            gizmo = getattr(self, i, False)
            rot = Euler(w, 'XYZ').to_matrix().to_4x4()
            gizmo.matrix_basis = mat.to_euler().to_matrix().to_4x4() @ rot
            gizmo.matrix_basis.translation = self.obj_matrix_world @ Vector(j)
