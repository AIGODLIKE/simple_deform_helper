import math
from time import time

import bpy
from bpy.types import Gizmo, GizmoGroup
from bpy_extras import view3d_utils
from mathutils import Vector

from ..update import ChangeActiveModifierParameter
from ..utils import GizmoUtils, GizmoGroupUtils


class GizmoProperty(GizmoUtils):
    ctrl_mode: str
    int_value_up_limits: int
    int_value_down_limits: int

    @property
    def is_up_limits_mode(self):
        return self.ctrl_mode == 'up_limits'

    @property
    def is_down_limits_mode(self):
        return self.ctrl_mode == 'down_limits'

    @property
    def limit_scope(self):
        return self.pref.modifiers_limits_tolerance

    @property
    def limits_min_value(self):
        return self.modifier_down_limits + self.limit_scope

    @property
    def limits_max_value(self):
        return self.modifier_up_limits - self.limit_scope

    # ----get func

    def get_up_limits_value(self, event):
        delta = self.get_delta(event)
        mid = self.middle_limits_value + self.limit_scope
        min_value = mid if self.is_middle_mode else self.limits_min_value
        return self.value_limit(delta, min_value=min_value)

    def get_down_limits_value(self, event):
        delta = self.get_delta(event)
        mid = self.middle_limits_value - self.limit_scope
        max_value = mid if self.is_middle_mode else self.limits_max_value
        return self.value_limit(delta, max_value=max_value)

    def get_delta(self, event):
        context = bpy.context
        x, y = view3d_utils.location_3d_to_region_2d(
            context.region, context.space_data.region_3d, self.point_up)
        x2, y2 = view3d_utils.location_3d_to_region_2d(
            context.region, context.space_data.region_3d, self.point_down)

        mouse_line_distance = math.sqrt(((event.mouse_region_x - x2) ** 2) +
                                        ((event.mouse_region_y - y2) ** 2))
        straight_line_distance = math.sqrt(((x2 - x) ** 2) +
                                           ((y2 - y) ** 2))
        delta = mouse_line_distance / straight_line_distance + 0

        v_up = Vector((x, y))
        v_down = Vector((x2, y2))
        limits_angle = v_up - v_down

        mouse_v = Vector((event.mouse_region_x, event.mouse_region_y))

        mouse_angle = mouse_v - v_down
        angle_ = mouse_angle.angle(limits_angle)
        if angle_ > (math.pi / 2):
            delta = 0
        return delta


class GizmoUpdate(GizmoProperty):
    # ---update gizmo matrix
    def update_gizmo_matrix(self, context):
        self.align_orientation_to_user_perspective(context)
        self.align_point_to_limits_point()

    def align_orientation_to_user_perspective(self, context):
        rotation = context.space_data.region_3d.view_matrix.inverted().to_quaternion()
        matrix = rotation.to_matrix().to_4x4()
        self.matrix_basis = matrix

    def align_point_to_limits_point(self):
        if self.is_up_limits_mode:
            self.matrix_basis.translation = self.point_limits_up
        elif self.is_down_limits_mode:
            self.matrix_basis.translation = self.point_limits_down

    # ---- set prop
    def set_prop_value(self, event):
        if self.is_up_limits_mode:
            self.set_up_value(event)
        elif self.is_down_limits_mode:
            self.set_down_value(event)

    def set_down_value(self, event):
        value = self.get_down_limits_value(event)
        self.target_set_value('down_limits', value)
        if event.ctrl:
            self.target_set_value('up_limits', value + self.difference_value)
        elif self.is_middle_mode:
            if self.origin_mode == 'LIMITS_MIDDLE':
                mu = self.middle_limits_value
                v = mu - (value - mu)
                self.target_set_value('up_limits', v)
            elif self.origin_mode == 'MIDDLE':
                self.target_set_value('up_limits', 1 - value)
            else:
                self.target_set_value('up_limits', self.modifier_up_limits)
        else:
            self.target_set_value('up_limits', self.modifier_up_limits)

    def set_up_value(self, event):
        value = self.get_up_limits_value(event)
        self.target_set_value('up_limits', value)
        if event.ctrl:
            self.target_set_value('down_limits', value - self.difference_value)
        elif self.is_middle_mode:
            if self.origin_mode == 'LIMITS_MIDDLE':
                mu = self.middle_limits_value
                value = mu - (value - mu)
                self.target_set_value('down_limits', value)
            elif self.origin_mode == 'MIDDLE':
                self.target_set_value('down_limits', 1 - value)
            else:
                self.target_set_value('down_limits', self.modifier_down_limits)
        else:
            self.target_set_value('down_limits', self.modifier_down_limits)

    # -------
    def update_header_text(self, context):
        origin = self.obj_origin_property_group
        mode = origin.bl_rna.properties['origin_mode'].enum_items[origin.origin_mode].name

        te = self.translate_text
        t = self.translate_header_text
        text = te(self.modifier.deform_method.title()) + '       ' + te(mode) + '       '
        if self.is_up_limits_mode:
            value = round(self.modifier_up_limits, 3)
            text += t('Up limit', value)
        elif self.is_down_limits_mode:
            value = round(self.modifier_down_limits, 3)
            text += t('Down limit', value)
        context.area.header_text_set(text)


class UpDownLimitsGizmo(Gizmo, GizmoUpdate):
    bl_idname = 'UpDownLimitsGizmo'
    bl_label = 'UpDownLimitsGizmo'
    bl_target_properties = (
        {'id': 'up_limits', 'type': 'FLOAT', 'array_length': 1},
        {'id': 'down_limits', 'type': 'FLOAT', 'array_length': 1},
    )
    bl_options = {'UNDO', 'GRAB_CURSOR'}

    __slots__ = (
        'mod',
        'up_limits',
        'down_limits',
        'draw_type',
        'mouse_dpi',
        'ctrl_mode',
        'difference_value',
        'middle_limits_value',
        'init_mouse_region_y',
        'init_mouse_region_x',
        'custom_shape',
        'int_value_up_limits',
        'int_value_down_limits',
    )
    difference_value: float
    middle_limits_value: float

    def setup(self):
        self.mouse_dpi = 10
        self.init_setup()

    def invoke(self, context, event):
        self.init_invoke(context, event)

        if self.is_up_limits_mode:
            self.int_value_up_limits = up_limits = self.modifier_up_limits
            self.target_set_value('up_limits', up_limits)
        elif self.is_down_limits_mode:
            self.int_value_down_limits = down_limits = self.modifier_down_limits
            self.target_set_value('down_limits', down_limits)
        return {'RUNNING_MODAL'}

    def exit(self, context, cancel):
        context.area.header_text_set(None)
        if cancel:
            if self.is_up_limits_mode:
                self.target_set_value('up_limits', self.int_value_up_limits)
            elif self.is_down_limits_mode:
                self.target_set_value(
                    'down_limits', self.int_value_down_limits)

    def modal(self, context, event, tweak):
        st = time()
        self.clear_point_cache()

        if self.modifier_is_use_origin_axis:
            self.new_origin_empty_object()
            # return {'RUNNING_MODAL'}

        self.difference_value = self.modifier_up_limits - self.modifier_down_limits
        self.middle_limits_value = (self.modifier_up_limits + self.modifier_down_limits) / 2

        try:
            self.set_prop_value(event)
            self.clear_point_cache()
            self.update_object_origin_matrix()
        except Exception as e:
            print(e.args)
            # ...
            # return {'FINISHED'}
        self.update_header_text(context)
        return_handle = self.event_handle(event)
        ChangeActiveModifierParameter.update_modifier_parameter()
        self.update_deform_wireframe()
        print('run modal time:', time() - st)
        return return_handle


class UpDownLimitsGizmoGroup(GizmoGroup, GizmoGroupUtils):
    bl_idname = 'OBJECT_GGT_UpDownLimitsGizmoGroup'
    bl_label = 'UpDownLimitsGizmoGroup'

    @classmethod
    def poll(cls, context):

        return cls.simple_deform_show_gizmo_poll(context)

    def setup(self, context):
        sd_name = UpDownLimitsGizmo.bl_idname
        gizmo_data = [
            ('up_limits',
             sd_name,
             {'ctrl_mode': 'up_limits',
              'draw_type': 'Sphere_GizmoGroup_',
              'mouse_dpi': 1000,
              'color': (1.0, 0, 0),
              'alpha': 0.5,
              'color_highlight': (1.0, 1.0, 1.0),
              'alpha_highlight': 0.3,
              'use_draw_modal': True,
              'scale_basis': 0.1,
              'use_draw_value': True, }),
            ('down_limits',
             sd_name,
             {'ctrl_mode': 'down_limits',
              'draw_type': 'Sphere_GizmoGroup_',
              'mouse_dpi': 1000,
              'color': (0, 1.0, 0),
              'alpha': 0.5,
              'color_highlight': (1.0, 1.0, 1.0),
              'alpha_highlight': 0.3,
              'use_draw_modal': True,
              'scale_basis': 0.1,
              'use_draw_value': True, }),
        ]
        self.generate_gizmo(gizmo_data)

    def refresh(self, context):
        pro = context.object.SimpleDeformGizmo_PropertyGroup
        for i in (self.down_limits, self.up_limits):
            for j in ('down_limits', 'up_limits'):
                i.target_set_prop(j, pro, j)
