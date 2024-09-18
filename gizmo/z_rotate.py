from bpy.types import Gizmo, GizmoGroup

from ..utils import GizmoGroupUtils, GizmoUtils


class ZRotateGizmo(Gizmo, GizmoUtils):
    bl_idname = 'ZRotateGizmo'

    # bl_target_properties = (
    #     {'id': 'rotate_angle', 'type': 'FLOAT', 'array_length': 1},
    # )

    __slots__ = (
        'draw_type',
        'mouse_dpi',
        'empty_object',
        'custom_shape',
        'tmp_value_angle',
        'int_value_degrees',
        'init_mouse_region_y',
        'init_mouse_region_x',
    )

    def setup(self):
        print("setup")

    def invoke(self, context, event):
        print("invoke")
        self.int_value = self.target_get_value('rotate_angle')
        return {"RUNNING_MODAL"}

    def modal(self, context, event, tweak):
        print("Modal")
        return {'RUNNING_MODAL'}

    def exit(self, context, cancel):
        context.area.header_text_set(None)
        if cancel:
            self.target_set_value('rotate_angle', self.int_value_degrees)


class ZRotateGizmoGroup(GizmoGroup, GizmoGroupUtils):
    bl_idname = 'OBJECT_GGT_SimpleDeformGizmoGroup'
    bl_label = 'AngleGizmoGroup'

    @classmethod
    def poll(cls, context):
        return cls.simple_deform_show_gizmo_poll(context)

    def setup(self, context):
        add_data = [
            ('rotate_angle',
             ZRotateGizmo.bl_idname,
             {'draw_type': 'Z_Rotate',
              'color': (1.0, 0.5, 1.0),
              'alpha': 0.3,
              'color_highlight': (1.0, 1.0, 1.0),
              'alpha_highlight': 0.3,
              'use_draw_modal': True,
              'scale_basis': 0.1,
              'use_draw_value': True,
              'mouse_dpi': 5,
              }),
        ]

        self.generate_gizmo(add_data)

    def refresh(self, context):
        # self.rotate_angle.target_set_prop('rotate_angle',
        #                            context.object.modifiers.active,
        #                            'rotate_angle')
        print("refresh", self.rotate_angle)
