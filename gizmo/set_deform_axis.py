from bpy.types import GizmoGroup
from mathutils import Vector

from ..utils import GizmoGroupUtils,get_pref


class SetDeformGizmoGroup(GizmoGroup, GizmoGroupUtils):
    bl_idname = 'OBJECT_GGT_SetDeformGizmoGroup'
    bl_label = 'SetDeformGizmoGroup'

    @classmethod
    def poll(cls, context):
        return cls.simple_deform_show_gizmo_poll(context) and get_pref().show_set_axis_button

    def setup(self, context):
        data_path = 'object.modifiers.active.deform_axis'
        set_enum = 'wm.context_set_enum'

        for axis in ('X', 'Y', 'Z'):
            # show toggle axis button
            gizmo = self.gizmos.new('GIZMO_GT_button_2d')
            gizmo.icon = f'EVENT_{axis.upper()}'
            gizmo.draw_options = {'BACKDROP', 'HELPLINE'}
            ops = gizmo.target_set_operator(set_enum)
            ops.data_path = data_path
            ops.value = axis
            gizmo.color = (0, 0, 0)
            gizmo.alpha = 0.3
            gizmo.color_highlight = 1.0, 1.0, 1.0
            gizmo.alpha_highlight = 0.3
            gizmo.use_draw_modal = True
            gizmo.use_draw_value = True
            gizmo.scale_basis = 0.1
            setattr(self, f'deform_axis_{axis.lower()}', gizmo)

    def draw_prepare(self, context):
        bound = self.modifier_bound_co
        if bound:
            obj = self.get_depsgraph(self.obj)
            dimensions = obj.dimensions

            def mat(f):
                b = bound[0]
                co = (b[0] + (max(dimensions) * f),
                      b[1],
                      b[2] - (min(dimensions) * 0.3))
                return self.obj_matrix_world @ Vector(co)

            self.deform_axis_x.matrix_basis.translation = mat(0)
            self.deform_axis_y.matrix_basis.translation = mat(0.3)
            self.deform_axis_z.matrix_basis.translation = mat(0.6)
