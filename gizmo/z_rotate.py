import math

import bpy
from bpy.types import Gizmo, GizmoGroup
from mathutils import Vector, Matrix, Euler

from ..utils import GizmoGroupUtils, GizmoUtils, PublicData


class ZRotateGizmo(Gizmo, GizmoUtils):
    bl_idname = 'ZRotateGizmo'

    bl_target_properties = (
        {'id': 'angle_value', 'type': 'FLOAT', 'array_length': 1},
    )
    start_point: Vector
    start_angle: float

    @property
    def origin_object(self):
        return bpy.context.active_object.modifiers.active.origin

    def setup(self):
        self.init_setup()
        print("setup")

    def invoke(self, context, event):
        self.init_invoke(context, event)

        self.start_angle = self.origin_object.simple_deform_helper_rotate_angle
        self.start_point = Vector((event.mouse_region_x, event.mouse_region_y))
        return {"RUNNING_MODAL"}

    def modal(self, context, event, tweak):
        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        diff = mouse.x - self.start_point.x
        v = self.get_snap(diff, tweak) * 0.005
        angle = (180 * v / math.pi)
        self.target_set_value('angle_value', self.start_angle + math.radians(angle))
        self.update_deform_wireframe()
        self.update_object_origin_matrix()
        self.tag_redraw(context)
        return {'RUNNING_MODAL'}

    def exit(self, context, cancel):
        context.area.header_text_set(None)
        if cancel:
            self.target_set_value('angle_value', self.start_angle)

    def update_gizmo_matrix(self, context):
        origin = self.origin_object
        off = Matrix.Translation(origin.location)
        con = origin.constraints[PublicData.G_NAME_CON_LIMIT]
        rotate = Euler((con.max_x, con.max_y, con.max_z), 'XYZ').to_matrix().to_4x4()
        self.matrix_basis = self.obj_matrix_world @ off @ rotate


class ZRotateGizmoGroup(GizmoGroup, GizmoGroupUtils):
    bl_idname = 'OBJECT_GGT_SimpleDeform_Z_Rotate_GizmoGroup'
    bl_label = 'Z Rotate'

    @classmethod
    def check_origin_object(cls, context) -> bool:
        """ check object hava simple default origin object"""
        from ..utils import PublicData
        obj = context.object
        if not obj:
            return False
        active_modify = obj.modifiers.active
        if not active_modify or active_modify.type != "SIMPLE_DEFORM":
            return False
        if active_modify.deform_method != "BEND":
            return False
        origin_object = active_modify.origin
        if not origin_object:
            return False
        if PublicData.G_NAME_CON_LIMIT not in origin_object.constraints:
            return False
        return True

    @classmethod
    def poll(cls, context):
        gizmo = cls.simple_deform_show_gizmo_poll(context)
        origin = cls.check_origin_object(context)
        return gizmo and origin

    def setup(self, context):
        add_data = [
            ('angle_value',
             ZRotateGizmo.bl_idname,
             {'draw_type': 'Z_Rotate',
              'color': (1.0, 0.5, 1.0),
              'alpha': 0.3,
              'color_highlight': (1.0, 1.0, 1.0),
              'alpha_highlight': 0.3,
              'use_draw_modal': False,
              'scale_basis': 2.5,
              'use_draw_value': False,
              'use_draw_scale': False,
              'mouse_dpi': 5,
              }),
        ]

        self.generate_gizmo(add_data)

    def refresh(self, context):
        self.angle_value.target_set_prop('angle_value',
                                         self.angle_value.origin_object,
                                         'simple_deform_helper_rotate_angle')
        # print("refresh", self.angle_value)
