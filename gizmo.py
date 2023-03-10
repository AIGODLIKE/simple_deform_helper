# SPDX-License-Identifier: GPL-2.0-or-later
import bpy
import math
from bpy_extras import view3d_utils
from mathutils import Vector, Euler
from bpy.types import (
    Gizmo,
    GizmoGroup,
)

from .draw import Handler
from .utils import Utils, Pref
from .data import Data


class CustomGizmo(Gizmo, Utils, Handler, Data):
    """绘制自定义Gizmo"""
    bl_idname = '_Custom_Gizmo'

    def setup(self):
        self.draw_type = 'None_GizmoGroup_'
        if not hasattr(self, 'custom_shape'):
            self.custom_shape = {}
            for i in self.G_GizmoCustomShapeDict:
                self.custom_shape[i] = self.new_custom_shape(
                    'TRIS', self.G_GizmoCustomShapeDict[i])
        self.add_handler()

    def draw(self, context):
        self.draw_custom_shape(self.custom_shape[self.draw_type])

    def draw_select(self, context, select_id):
        self.draw_custom_shape(
            self.custom_shape[self.draw_type], select_id=select_id)

    def invoke(self, context, event):
        return {'RUNNING_MODAL'}

    def modal(self, context, event, tweak):
        self.add_handler()

        self.update_bound_box(context.object)
        self.update_empty_matrix()
        return {'RUNNING_MODAL'}


class ViewSimpleDeformGizmo(Gizmo, Utils, Handler, Data, Pref):
    """显示轴向切换拖动点Gizmo(两个点)
    """
    bl_idname = 'ViewSimpleDeformGizmo'

    bl_target_properties = (
        {'id': 'up_limits', 'type': 'FLOAT', 'array_length': 1},
        {'id': 'down_limits', 'type': 'FLOAT', 'array_length': 1},
        {'id': 'angle', 'type': 'FLOAT', 'array_length': 1},
    )

    __slots__ = (
        'mod',
        'up',
        'down',
        'up_',
        'down_',
        'draw_type',
        'mouse_dpi',
        'ctrl_mode',
        'empty_object',
        'init_mouse_y',
        'init_mouse_x',
        'custom_shape',
        'int_value_angle',
        'value_deform_axis',
        'int_value_up_limits',
        'int_value_down_limits',
        'rotate_follow_modifier',
    )

    def update_gizmo_rotate(self, axis, mod):
        if self.rotate_follow_modifier:
            rot = Euler()
            if axis == 'X' and (not self.is_positive(mod.angle)):
                rot.z = math.pi

            elif axis == 'Y':
                if self.is_positive(mod.angle):
                    rot.z = -(math.pi / 2)
                else:
                    rot.z = math.pi / 2
            elif axis == 'Z':
                if self.is_positive(mod.angle):
                    rot.x = rot.z = rot.y = math.pi / 2
                else:
                    rot.z = rot.y = math.pi / 2
                    rot.x = -(math.pi / 2)

            rot = rot.to_matrix()
            self.matrix_basis = self.matrix_basis @ rot.to_4x4()

    def update_draw_limits_bound_box(self, data, mod, axis, mat, up_, down_):
        top, bottom, left, right, front, back = data
        if mod.origin:
            vector_axis = self.get_vector_axis(mod)
            origin_mat = mod.origin.matrix_world.to_3x3()
            axis_ = origin_mat @ vector_axis
            point_lit = [[top, bottom], [left, right], [front, back]]
            for f in range(point_lit.__len__()):
                i = point_lit[f][0]
                j = point_lit[f][1]
                angle = self.point_to_angle(i, j, f, axis_)
                if abs(angle - 180) < 0.00001:
                    point_lit[f][1], point_lit[f][0] = up_, down_
                elif abs(angle) < 0.00001:
                    point_lit[f][0], point_lit[f][1] = up_, down_
            [[top, bottom], [left, right], [front, back]] = point_lit
        else:
            top, bottom, left, right, front, back = self.get_up_down_return_list(
                mod, axis, up_, down_, data)
        data = top, bottom, left, right, front, back
        (top, bottom, left, right, front,
         back) = self.matrix_calculation(mat.inverted(), data)
        self.G_SimpleDeformGizmoHandlerDit['draw_limits_bound_box'] = (
            mat, ((right[0], back[1], top[2]), (left[0], front[1], bottom[2],)))

    def update_matrix_basis_translation(self, co, mat, up_, down_):
        if 'angle' == self.ctrl_mode:
            self.matrix_basis.translation = mat @ Vector((co[1]))
        elif 'up_limits' == self.ctrl_mode:
            self.matrix_basis.translation = up_
        elif 'down_limits' == self.ctrl_mode:
            self.matrix_basis.translation = down_

    def update_gizmo_matrix(self, context):
        ob = context.object
        mat = ob.matrix_world
        mod = context.object.modifiers.active
        axis = mod.deform_axis
        if mod.origin:
            self.matrix_basis = mod.origin.matrix_world.normalized()
        else:
            self.matrix_basis = ob.matrix_world.normalized()

        co = self.generate_co_data()
        self.update_gizmo_rotate(axis, mod)
        # calculation  limits position
        top, bottom, left, right, front, back = self.each_face_pos(mat)
        (up, down), (up_, down_) = self.get_limits_pos(
            mod, (top, bottom, left, right, front, back))
        self.update_matrix_basis_translation(co, mat, up_, down_)

        self.up = up
        self.down = down
        self.up_ = up_
        self.down_ = down_
        self.G_SimpleDeformGizmoHandlerDit['draw_line'] = (
            (up, down), (up_, down_))
        data = top, bottom, left, right, front, back
        self.update_draw_limits_bound_box(data, mod, axis, mat, up_, down_)

    def setup(self):
        self.generate_co_data()
        self.draw_type = 'None_GizmoGroup_'
        self.ctrl_mode = 'angle'  # up_limits , down_limits
        self.mouse_dpi = 10
        self.rotate_follow_modifier = True
        if not hasattr(self, 'custom_shape'):
            self.custom_shape = {}
            for i in self.G_GizmoCustomShapeDict:
                item = self.G_GizmoCustomShapeDict[i]
                self.custom_shape[i] = self.new_custom_shape('TRIS', item)
        self.add_handler()

    def draw(self, context):
        self.add_handler()

        self.update_gizmo_matrix(context)
        self.draw_custom_shape(self.custom_shape[self.draw_type])

    def draw_select(self, context, select_id):
        self.update_gizmo_matrix(context)
        self.draw_custom_shape(
            self.custom_shape[self.draw_type], select_id=select_id)

    def invoke(self, context, event):
        self.init_mouse_y = event.mouse_y
        self.init_mouse_x = event.mouse_x
        mod = context.object.modifiers.active
        limits = mod.limits
        up_limits = limits[1]
        down_limits = limits[0]

        if 'angle' == self.ctrl_mode:
            self.int_value_angle = self.target_get_value('angle')
        elif 'up_limits' == self.ctrl_mode:
            self.int_value_up_limits = up_limits
            self.target_set_value('up_limits', self.int_value_up_limits)
        elif 'down_limits' == self.ctrl_mode:
            self.int_value_down_limits = down_limits
            self.target_set_value('down_limits', self.int_value_down_limits)
        return {'RUNNING_MODAL'}

    def exit(self, context, cancel):
        context.area.header_text_set(None)

        if cancel:
            if 'angle' == self.ctrl_mode:
                self.target_set_value('angle', self.int_value_angle)
            elif 'deform_axis' == self.ctrl_mode:
                self.target_set_value('deform_axis', self.value_deform_axis)
            elif 'up_limits' == self.ctrl_mode:
                self.target_set_value('up_limits', self.int_value_up_limits)

            elif 'down_limits' == self.ctrl_mode:
                self.target_set_value(
                    'down_limits', self.int_value_down_limits)

    def delta_update(self, context, event, delta):
        if ('draw_line' in self.G_SimpleDeformGizmoHandlerDit) and (self.ctrl_mode in ('up_limits', 'down_limits')):
            x, y = view3d_utils.location_3d_to_region_2d(
                context.region, context.space_data.region_3d, self.up)
            x2, y2 = view3d_utils.location_3d_to_region_2d(
                context.region, context.space_data.region_3d, self.down)

            mouse_line_distance = math.sqrt(((event.mouse_region_x - x2) ** 2) +
                                            ((event.mouse_region_y - y2) ** 2))
            straight_line_distance = math.sqrt(((x2 - x) ** 2) +
                                               ((y2 - y) ** 2))
            delta = mouse_line_distance / \
                    straight_line_distance + 0

            v_up = Vector((x, y))
            v_down = Vector((x2, y2))
            limits_angle = v_up - v_down

            mouse_v = Vector((event.mouse_region_x, event.mouse_region_y))

            mouse_angle = mouse_v - v_down
            angle_ = mouse_angle.angle(limits_angle)
            if angle_ > (math.pi / 2):
                delta = 0
        return delta

    def set_down_value(self, data, mu):
        up_limits, down_limits, delta, middle, min_value, max_value, limit_scope, difference_value, event, origin_mode = data
        value = self.value_limit(delta, max_value=mu -
                                                  limit_scope if middle else max_value)
        self.target_set_value('down_limits', value)
        if event.ctrl:
            self.target_set_value(
                'up_limits', value + difference_value)
        elif middle:
            if origin_mode == 'LIMITS_MIDDLE':
                self.target_set_value('up_limits', mu - (value - mu))
            elif origin_mode == 'MIDDLE':
                self.target_set_value('up_limits', 1 - value)
            else:
                self.target_set_value('up_limits', up_limits)
        else:
            self.target_set_value('up_limits', up_limits)

    def set_up_value(self, data, mu):
        up_limits, down_limits, delta, middle, min_value, max_value, limit_scope, difference_value, event, origin_mode = data
        value = self.value_limit(delta, min_value=mu +
                                                  limit_scope if middle else min_value)
        self.target_set_value('up_limits', value)
        if event.ctrl:
            self.target_set_value(
                'down_limits', value - difference_value)
        elif middle:
            if origin_mode == 'LIMITS_MIDDLE':
                self.target_set_value('down_limits', mu - (value - mu))
            elif origin_mode == 'MIDDLE':
                self.target_set_value('down_limits', 1 - value)
            else:
                self.target_set_value('down_limits', down_limits)
        else:
            self.target_set_value('down_limits', down_limits)

    def set_prop_value(self, data):
        up_limits, down_limits, delta, middle, min_value, max_value, limit_scope, difference_value, event, origin_mode = data
        mu = (up_limits + down_limits) / 2
        if 'angle' == self.ctrl_mode:
            value = self.int_value_angle - delta
            self.target_set_value('angle', value)
        elif 'up_limits' == self.ctrl_mode:
            self.set_up_value(data, mu)
        elif 'down_limits' == self.ctrl_mode:
            self.set_down_value(data, mu)

    def update_header_text(self, context, mod, origin, up_limits, down_limits):
        t = lambda a: bpy.app.translations.pgettext(a)

        if (mod.deform_method in ('TWIST', 'BEND')) and (self.ctrl_mode in ('angle',)):
            text = t("Angle") + ':{}'.format(math.degrees(mod.angle))
        elif 'up_limits' == self.ctrl_mode:
            text = t("Upper limit") + ':{}'.format(up_limits)
        elif 'down_limits' == self.ctrl_mode:
            text = t("Down limit") + ':{}'.format(down_limits)
        else:
            text = t("Coefficient") + ':{}'.format(mod.factor)
        text += '       '
        text += t(origin.bl_rna.properties[
            'origin_mode'].enum_items[origin.origin_mode].name)
        context.area.header_text_set(text)

    def event_ops(self, event, ob, origin):
        """通过输入键位来更改属性"""
        # event ctrl
        data_path = ('object.SimpleDeformGizmo_PropertyGroup.origin_mode',
                     'object.modifiers.active.origin.SimpleDeformGizmo_PropertyGroup.origin_mode')

        if event.type in ('WHEELUPMOUSE', 'WHEELDOWNMOUSE'):
            reverse = (event.type == 'WHEELUPMOUSE')
            for path in data_path:
                bpy.ops.wm.context_cycle_enum(
                    data_path=path, reverse=reverse, wrap=True)
        elif event.type in ('X', 'Y', 'Z'):
            ob.modifiers.active.deform_axis = event.type
        elif event.type == 'A':
            self.pref.display_bend_axis_switch_gizmo = True
            return {'FINISHED'}
        self.add_handler()

        return {'RUNNING_MODAL'}

    def modal(self, context, event, tweak):
        self.update_bound_box(context.object)

        delta = (self.init_mouse_x - event.mouse_x) / self.mouse_dpi
        ob = context.object
        mod = ob.modifiers.active
        limits = mod.limits
        up_limits = limits[1]
        down_limits = limits[0]
        origin = self.get_origin_property_group(mod, ob)
        origin_mode = origin.origin_mode
        middle = origin_mode in ('LIMITS_MIDDLE', 'MIDDLE')
        limit_scope = self.pref.modifiers_limits_tolerance
        max_value = up_limits - limit_scope
        min_value = down_limits + limit_scope
        difference_value = up_limits - down_limits

        if 'SNAP' in tweak:
            delta = round(delta)
        if 'PRECISE' in tweak:
            delta /= self.mouse_dpi
        delta = self.delta_update(context, event, delta)

        if origin_mode != 'NOT' and ('draw_line' in self.G_SimpleDeformGizmoHandlerDit):
            self.empty_object, _ = self.new_empty(ob, mod)
            self.G_SimpleDeformGizmoHandlerDit['empty_object'] = self.empty_object
        data = up_limits, down_limits, delta, middle, min_value, max_value, limit_scope, difference_value, event, origin_mode
        self.set_prop_value(data)
        self.update_gizmo_matrix(context)
        self.update_empty_matrix()
        self.update_bound_box(context.object)

        self.update_header_text(context, mod, origin, up_limits, down_limits)
        self.add_handler()

        return self.event_ops(event, ob, origin)


class SimpleDeformGizmoGroup(GizmoGroup, Utils, Handler, Pref, Data):
    """显示Gizmo
    """
    bl_idname = 'OBJECT_GGT_SimpleDeformGizmoGroup'
    bl_label = 'SimpleDeformGizmoGroup'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'3D', 'PERSISTENT', }

    @classmethod
    def poll(cls, context):
        pol = cls.simple_deform_poll(context)
        pref = cls._pref()
        deform_method = (
                pol and (context.object.modifiers.active.deform_method != 'BEND'))
        display_gizmo = pref.display_bend_axis_switch_gizmo
        switch = (not display_gizmo)
        return pol and (deform_method or switch)

    def generate_gizmo_mode(self, gizmo_data):
        """生成gizmo的上限下限及角度设置

        Args:
            gizmo_data (_type_): _description_
        """
        for i, j, k in gizmo_data:
            setattr(self, i, self.gizmos.new(j))
            gizmo = getattr(self, i)
            for f in k:
                if f == 'target_set_operator':
                    gizmo.target_set_operator(k[f])
                elif f == 'target_set_prop':
                    gizmo.target_set_prop(*k[f])
                else:
                    setattr(gizmo, f, k[f])

    def setup(self, context):
        sd_name = ViewSimpleDeformGizmo.bl_idname

        add_data = (('up_limits',
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
                    ('angle',
                     sd_name,
                     {'ctrl_mode': 'angle',
                      'draw_type': 'SimpleDeform_GizmoGroup_',
                      'color': (1.0, 0.5, 1.0),
                      'alpha': 0.3,
                      'color_highlight': (1.0, 1.0, 1.0),
                      'alpha_highlight': 0.3,
                      'use_draw_modal': True,
                      'scale_basis': 0.1,
                      'use_draw_value': True,
                      'mouse_dpi': 100,
                      }),
                    )

        self.generate_gizmo_mode(add_data)

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
        self.add_handler()

    def refresh(self, context):
        pro = context.object.SimpleDeformGizmo_PropertyGroup

        self.angle.target_set_prop('angle',
                                   context.object.modifiers.active,
                                   'angle')
        self.down_limits.target_set_prop('down_limits',
                                         pro,
                                         'down_limits')
        self.down_limits.target_set_prop('up_limits',
                                         pro,
                                         'up_limits')
        self.up_limits.target_set_prop('down_limits',
                                       pro,
                                       'down_limits')
        self.up_limits.target_set_prop('up_limits',
                                       pro,
                                       'up_limits')
        self.add_handler()

    def draw_prepare(self, context):
        ob = context.object
        mat = ob.matrix_world

        if 'co' in self.G_SimpleDeformGizmoHandlerDit:
            def _mat(f):
                co = self.G_SimpleDeformGizmoHandlerDit['co'][0]
                co = (co[0] + (max(ob.dimensions) * f), co[1],
                      co[2] - (min(ob.dimensions) * 0.3))
                return mat @ Vector(co)

            self.deform_axis_x.matrix_basis.translation = _mat(0)
            self.deform_axis_y.matrix_basis.translation = _mat(0.3)
            self.deform_axis_z.matrix_basis.translation = _mat(0.6)
        self.add_handler()

    def invoke_prepare(self, context, gizmo):
        self.add_handler()


class SimpleDeformGizmoGroupDisplayBendAxiSwitchGizmo(GizmoGroup, Utils, Handler, Pref):
    """绘制切换变型轴的
    变换方向
    """
    bl_idname = 'OBJECT_GGT_SimpleDeformGizmoGroup_display_bend_axis_switch_gizmo'
    bl_label = 'SimpleDeformGizmoGroup_display_bend_axis_switch_gizmo'

    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {
        '3D',
        'PERSISTENT',
    }

    @classmethod
    def poll(cls, context):
        pref = cls._pref()
        simple = cls.simple_deform_poll(context)
        bend = simple and (
                context.object.modifiers.active.deform_method == 'BEND')
        switch_axis = (pref.display_bend_axis_switch_gizmo == True)
        return switch_axis and bend

    def setup(self, context):
        _draw_type = 'SimpleDeform_Bend_Direction_'
        _color_a = 1, 0, 0
        _color_b = 0, 1, 0
        self.add_handler()

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
        top, bottom, left, right, front, back = self.each_face_pos(mat)

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
            gizmo.matrix_basis.translation = Vector(j)


class_list = (
    CustomGizmo,
    ViewSimpleDeformGizmo,
    SimpleDeformGizmoGroup,
    SimpleDeformGizmoGroupDisplayBendAxiSwitchGizmo,
)

register_class, unregister_class = bpy.utils.register_classes_factory(class_list)


def register():
    register_class()


def unregister():
    Handler.del_handler()
    unregister_class()
