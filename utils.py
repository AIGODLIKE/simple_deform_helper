# SPDX-License-Identifier: GPL-2.0-or-later

import math
import uuid

import bpy
import numpy as np
from bpy.types import AddonPreferences
from mathutils import Vector, Matrix

from .data import G_ADDON_NAME, G_NAME, G_INDICES, G_MODIFIERS_PROPERTY, G_CON_LIMIT_NAME, Data


class Pref:
    @staticmethod
    def _pref() -> "AddonPreferences":
        return bpy.context.preferences.addons[G_ADDON_NAME].preferences

    @property
    def pref(self=None) -> 'AddonPreferences':
        """
        :return: AddonPreferences
        """
        return Pref._pref()


class Utils(Data):
    @classmethod
    def set_reduce(cls, list_a, list_b, operation_type='-') -> list:
        """
        :param list_a: 列表a
        :type list_a: list or set
        :param list_b: 列表b
        :type list_b:list or set
        :param operation_type :运算方法Enumerator in ['+','-','*','/'].
        :type operation_type :str
        :return list: 反回运算后的列表
        """
        if operation_type == '-':
            return [list_a[i] - list_b[i] for i in range(0, len(list_a))]
        elif operation_type == '+':
            return [list_a[i] + list_b[i] for i in range(0, len(list_a))]
        elif operation_type == '/':
            return [list_a[i] / list_b[i] for i in range(0, len(list_a))]
        elif operation_type == '*':
            return [list_a[i] * list_b[i] for i in range(0, len(list_a))]

    @classmethod
    def value_limit(cls, value, max_value=1, min_value=0) -> float:
        """
        :param value: 输入值
        :type value: float
        :param max_value: 允许的最大值
        :type max_value: float
        :param min_value: 允许的最小值
        :type min_value: float
        :return float: 反回小于最大值及大于最小值的浮点数
        """
        if value > max_value:
            return max_value
        elif value < min_value:
            return min_value
        else:
            return value

    @classmethod
    def is_positive(cls, number: 'int') -> bool:
        """return bool value
        if number is positive return True else return False
        """
        return number == abs(number)

    @classmethod
    def get_depsgraph(cls, obj: 'bpy.context.object'):
        """
        :param obj: 要被评估的物体
        :type obj: bpy.types.Object
        :return bpy.types.Object: 反回评估后的物体,计算应用修改器和实例化的数据
        如果未输入物休将会评估活动物体
        """
        context = bpy.context
        if obj is None:
            obj = context.object
        depsgraph = context.evaluated_depsgraph_get()
        return obj.evaluated_get(depsgraph)

    @classmethod
    def link_active_collection(cls,
                               obj: 'bpy.context.object') -> \
            'bpy.context.view_layer.active_layer_collection.collection.objects':
        context = bpy.context
        if obj.name not in context.view_layer.active_layer_collection.collection.objects:
            context.view_layer.active_layer_collection.collection.objects.link(
                obj)
        return context.view_layer.active_layer_collection.collection.objects

    @classmethod
    def properties_is_modifier(cls) -> bool:
        """
        反回活动窗口内是否有修改器属性面板被打开,如果打开则反回True else False
        """
        for area in bpy.context.screen.areas:
            if area.type == 'PROPERTIES':
                for space in area.spaces:
                    if space.type == 'PROPERTIES' and space.context == 'MODIFIER':
                        return True
        return False

    @classmethod
    def simple_deform_poll(cls, context: 'bpy.context') -> bool:
        """
        :param context:输入一个上下文
        :type context:bpy.context
        :return bool:反回布尔值,如果活动物体为网格或晶格并且活动修改器为简易形变反回 True else False
        """
        obj = context.object
        mesh = (obj.type in ('MESH', 'LATTICE')) if obj else False
        modifiers_type = (obj.modifiers.active.type ==
                          'SIMPLE_DEFORM') if (obj and (obj.modifiers.active is not None)) else False
        obj_ok = context and obj and modifiers_type and mesh
        module_ok = (context.mode == 'OBJECT')
        view = context.space_data
        show_gizmo = view.show_gizmo
        return obj_ok and module_ok and show_gizmo

    @classmethod
    def bound_box_to_list(cls, obj: 'bpy.context.object') -> tuple:
        """
        :param obj:输入一个物体,反回物体的边界框列表
        :type obj:bpy.types.Object
        :return tuple:
        """
        return tuple(i[:] for i in obj.bound_box)

    @classmethod
    def get_origin_bounds(cls, obj: 'bpy.context.object') -> list:
        modifiers_list = {}
        for mod in obj.modifiers:
            if (mod == obj.modifiers.active) or (modifiers_list != {}):
                modifiers_list[mod] = (mod.show_render, mod.show_viewport)
                mod.show_viewport = False
                mod.show_render = False
        matrix_obj = obj.matrix_world.copy()
        obj.matrix_world.zero()
        obj.scale = (1, 1, 1)
        bound = cls.bound_box_to_list(obj)
        obj.matrix_world = matrix_obj
        for mod in modifiers_list:
            show_render, show_viewport = modifiers_list[mod]
            mod.show_render = show_render
            mod.show_viewport = show_viewport
        return list(bound)

    @classmethod
    def get_mesh_max_min_co(cls, obj: 'bpy.context.object') -> tuple:
        if obj.type == 'MESH':
            ver_len = obj.data.vertices.__len__()
            list_vertices = np.zeros(ver_len * 3, dtype=np.float32)
            obj.data.vertices.foreach_get('co', list_vertices)
            list_vertices = list_vertices.reshape(ver_len, 3)
        elif obj.type == 'LATTICE':
            ver_len = obj.data.points.__len__()
            list_vertices = np.zeros(ver_len * 3, dtype=np.float32)
            obj.data.points.foreach_get('co', list_vertices)
            list_vertices = list_vertices.reshape(ver_len, 3)
        return tuple(list_vertices.min(axis=0)), tuple(list_vertices.max(axis=0))

    @classmethod
    def matrix_calculation(cls, mat: 'Matrix', calculation_list: 'list') -> list:
        return [mat @ Vector(i) for i in calculation_list]

    @classmethod
    def get_origin_property_group(cls, mod, ob):
        if mod.origin:
            return mod.origin.SimpleDeformGizmo_PropertyGroup
        else:
            return ob.SimpleDeformGizmo_PropertyGroup

    @classmethod
    def set_empty_obj_matrix(cls, origin_mode, empty_object, up_, down_, up, down):
        tow = (2, 2, 2)
        if origin_mode == 'UP_LIMITS':
            empty_object.matrix_world.translation = Vector(up_)
        elif origin_mode == 'DOWN_LIMITS':
            empty_object.matrix_world.translation = Vector(
                down_)
        elif origin_mode == 'LIMITS_MIDDLE':
            empty_object.matrix_world.translation = cls.set_reduce(
                cls.set_reduce(up_, down_, '+'), tow, '/')
        elif origin_mode == 'MIDDLE':
            empty_object.matrix_world.translation = cls.set_reduce(
                cls.set_reduce(up, down, '+'), tow, '/')

    @classmethod
    def get_vector_axis(cls, mod):
        axis = mod.deform_axis
        if 'BEND' == mod.deform_method:
            vector_axis = Vector((0, 0, 1)) if axis in (
                'Y', 'X') else Vector((1, 0, 0))
        else:
            vector = (Vector((1, 0, 0)) if (
                    axis == 'X') else Vector((0, 1, 0)))
            vector_axis = Vector((0, 0, 1)) if (
                    axis == 'Z') else vector
        return vector_axis

    @classmethod
    def point_to_angle(cls, i, j, f, axis_):
        if i == j:
            if f == 0:
                i[0] += 0.1
                j[0] -= 0.1
            elif f == 1:
                i[1] -= 0.1
                j[1] += 0.1

            else:
                i[2] -= 0.1
                j[2] += 0.1
        vector_value = i - j
        angle = (180 * vector_value.angle(axis_) / math.pi)
        return angle

    @classmethod
    def get_up_down(cls, mod, axis, top, bottom, left, right, front, back):
        if 'BEND' == mod.deform_method:
            if axis in ('X', 'Y'):
                return top, bottom
            elif axis == 'Z':
                return right, left
        else:
            if axis == 'X':
                return right, left
            elif axis == 'Y':
                return back, front
            elif axis == 'Z':
                return top, bottom

    @classmethod
    def get_limits_pos(cls, mod, data):
        top, bottom, left, right, front, back = data
        up_limits = mod.limits[1]
        down_limits = mod.limits[0]
        axis = mod.deform_axis

        if mod.origin:
            vector_axis = cls.get_vector_axis(mod)
            origin_mat = mod.origin.matrix_world.to_3x3()
            axis_ = origin_mat @ vector_axis
            point_lit = [[top, bottom], [left, right], [front, back]]

            for f in range(point_lit.__len__()):
                i = point_lit[f][0]
                j = point_lit[f][1]
                angle = cls.point_to_angle(i, j, f, axis_)
                if abs(angle - 180) < 0.00001:
                    up, down = j, i
                elif abs(angle) < 0.00001:
                    up, down = i, j
        else:
            up, down = cls.get_up_down(mod, axis, top, bottom,
                                       left, right, front, back)

        ex = lambda a: cls.set_reduce(down, cls.set_reduce(cls.set_reduce(
            up, down, '-'), (a, a, a), '*'), '+')

        up_ = ex(up_limits)
        down_ = ex(down_limits)
        return (up, down), (up_, down_)

    @classmethod
    def update_bound_box(cls, object):

        context = bpy.context
        data = bpy.data
        obj = object
        matrix = obj.matrix_world.copy()  # 物体矩阵

        # add simple_deform mesh
        (min_x, min_y, min_z), (max_x, max_y,
                                max_z) = cls.get_mesh_max_min_co(object)
        vertexes = ((max_x, min_y, min_z),
                    (min_x, min_y, min_z),
                    (max_x, max_y, min_z),
                    (min_x, max_y, min_z),
                    (max_x, min_y, max_z),
                    (min_x, min_y, max_z),
                    (max_x, max_y, max_z),
                    (min_x, max_y, max_z))
        if data.objects.get(G_NAME):
            data.objects.remove(data.objects.get(G_NAME))

        if data.meshes.get(G_NAME):
            data.meshes.remove(data.meshes.get(G_NAME))
        mesh = data.meshes.new(G_NAME)
        mesh.from_pydata(vertexes, G_INDICES, [])
        mesh.update()

        new_object = data.objects.new(G_NAME, mesh)

        cls.link_active_collection(new_object)

        if new_object.parent != obj:
            new_object.parent = obj

        new_object.modifiers.clear()
        subdivision = new_object.modifiers.new('1', 'SUBSURF')
        subdivision.levels = 7
        cls.G_SimpleDeformGizmoHandlerDit['modifiers_co'] = {}
        cls.G_SimpleDeformGizmoHandlerDit['modifiers_co']['co'] = (
            min_x, min_y, min_z), (max_x, max_y, max_z)
        for mo in context.object.modifiers:
            if mo.type == 'SIMPLE_DEFORM':
                simple_deform = new_object.modifiers.new(
                    mo.name, 'SIMPLE_DEFORM')
                simple_deform.deform_method = mo.deform_method
                simple_deform.deform_axis = mo.deform_axis
                simple_deform.lock_x = mo.lock_x
                simple_deform.lock_y = mo.lock_y
                simple_deform.lock_z = mo.lock_z
                simple_deform.origin = mo.origin
                simple_deform.limits[1] = mo.limits[1]
                simple_deform.limits[0] = mo.limits[0]
                simple_deform.angle = mo.angle
                simple_deform.show_viewport = mo.show_viewport
                obj = Utils.get_depsgraph(new_object)
                cls.G_SimpleDeformGizmoHandlerDit['modifiers_co'][mo.name] = cls.get_mesh_max_min_co(
                    obj)
        new_object.hide_set(True)
        new_object.hide_viewport = False
        new_object.hide_select = True
        new_object.hide_render = True
        new_object.hide_viewport = True
        new_object.hide_set(True)
        ver_len = obj.data.vertices.__len__()
        edge_len = obj.data.edges.__len__()

        if 'numpy_data' not in cls.G_SimpleDeformGizmoHandlerDit:
            cls.G_SimpleDeformGizmoHandlerDit['numpy_data'] = {}

        numpy_data = cls.G_SimpleDeformGizmoHandlerDit['numpy_data']
        key = (ver_len, edge_len)
        if key in numpy_data:
            list_edges, list_vertices = numpy_data[key]
        else:
            list_edges = np.zeros(edge_len * 2, dtype=np.int32)
            list_vertices = np.zeros(ver_len * 3, dtype=np.float32)
            numpy_data[key] = (list_edges, list_vertices)
        obj.data.vertices.foreach_get('co', list_vertices)
        ver = list_vertices.reshape((ver_len, 3))
        ver = np.insert(ver, 3, 1, axis=1).T
        ver[:] = np.dot(matrix, ver)

        ver /= ver[3, :]
        ver = ver.T
        ver = ver[:, :3]
        obj.data.edges.foreach_get('vertices', list_edges)
        indices = list_edges.reshape((edge_len, 2))

        limits = context.object.modifiers.active.limits[:]
        modifiers = [getattr(context.object.modifiers.active, i)
                     for i in G_MODIFIERS_PROPERTY]

        cls.G_SimpleDeformGizmoHandlerDit['draw'] = (ver, indices, matrix, modifiers, limits)

    @classmethod
    def update_co_data(cls, ob, mod):
        handler_dit = cls.G_SimpleDeformGizmoHandlerDit

        if 'modifiers_co' in cls.G_SimpleDeformGizmoHandlerDit and ob.type in ('MESH', 'LATTICE'):
            modifiers_co = cls.G_SimpleDeformGizmoHandlerDit['modifiers_co']
            for index, mod_name in enumerate(modifiers_co):
                co_items = list(modifiers_co.items())
                if mod.name == mod_name:
                    cls.G_SimpleDeformGizmoHandlerDit['co'] = co_items[index - 1][1] if (index or (index != 1)) else \
                        modifiers_co['co']

    @classmethod
    def generate_co_data(cls):
        handler_dit = cls.G_SimpleDeformGizmoHandlerDit

        if 'co' not in handler_dit:
            handler_dit['co'] = cls.get_mesh_max_min_co(
                bpy.context.object)
        return handler_dit['co']

    @classmethod
    def new_empty(cls, obj, mod):
        origin = mod.origin
        if origin is None:
            new_name = G_NAME + '_Empty_' + str(uuid.uuid4())
            origin_object = bpy.data.objects.new(new_name, None)
            cls.link_active_collection(origin_object)
            origin_object.hide_set(True)
            origin_object.empty_display_size = min(obj.dimensions)
            mod.origin = origin_object
        else:
            origin_object = mod.origin
            origin_object.hide_viewport = False

        if origin_object.parent != obj:
            origin_object.parent = obj

        # add constraints
        if G_CON_LIMIT_NAME in origin_object.constraints.keys():
            limit_constraints = origin.constraints.get(G_CON_LIMIT_NAME)
        else:
            limit_constraints = origin_object.constraints.new(
                'LIMIT_ROTATION')
            limit_constraints.name = G_CON_LIMIT_NAME
            limit_constraints.owner_space = 'WORLD'
            limit_constraints.space_object = obj
        limit_constraints.use_transform_limit = True
        limit_constraints.use_limit_x = True
        limit_constraints.use_limit_y = True
        limit_constraints.use_limit_z = True
        con_copy_name = G_NAME + 'constraints_copy_rotation'
        if con_copy_name in origin_object.constraints.keys():
            copy_constraints = origin.constraints.get(con_copy_name)
        else:
            copy_constraints = origin_object.constraints.new(
                'COPY_ROTATION')
            copy_constraints.name = con_copy_name
        copy_constraints.target = obj
        copy_constraints.mix_mode = 'BEFORE'
        copy_constraints.target_space = 'WORLD'
        copy_constraints.owner_space = 'WORLD'
        origin_object.rotation_euler.zero()
        origin_object.scale = 1, 1, 1
        return origin_object, G_CON_LIMIT_NAME

    @classmethod
    def co_to_direction(cls, mat, data):
        (min_x, min_y, min_z), (max_x, max_y,
                                max_z) = data
        a = mat @ Vector((max_x, max_y, max_z))
        b = mat @ Vector((max_x, min_y, min_z))
        c = mat @ Vector((min_x, max_y, min_z))
        d = mat @ Vector((min_x, min_y, max_z))

        def pos_get(a, b):
            return cls.set_reduce(cls.set_reduce(a, b, '+'), (2, 2, 2), '/')

        top = Vector(pos_get(a, d))
        bottom = Vector(pos_get(c, b))
        left = Vector(pos_get(c, d))
        right = Vector(pos_get(a, b))
        front = Vector(pos_get(d, b))
        back = Vector(pos_get(c, a))
        return top, bottom, left, right, front, back

    @classmethod
    def each_face_pos(cls, mat: 'Matrix' = None):
        if mat is None:
            mat = Matrix()
        return cls.co_to_direction(mat, cls.G_SimpleDeformGizmoHandlerDit['co'])

    @classmethod
    def update_matrix(cls, mod, ob):
        if mod.deform_method == 'BEND':
            cls.new_empty(ob, mod)
        if mod.origin:
            empty_object = mod.origin
            modifiers_co = cls.G_SimpleDeformGizmoHandlerDit['modifiers_co']
            for index, mod_name in enumerate(modifiers_co):
                co_items = list(modifiers_co.items())
                if mod.name == mod_name:
                    data = co_items[index - 1][1] if (
                            index or (index != 1)) else modifiers_co['co']
                    (up, down), (up_, down_) = cls.get_limits_pos(
                        mod, cls.co_to_direction(ob.matrix_world.copy(), data))
                    origin_mode = cls.get_origin_property_group(
                        mod, ob).origin_mode
                    cls.set_empty_obj_matrix(
                        origin_mode, empty_object, up_, down_, up, down)

    @classmethod
    def update_empty_matrix(cls):
        ob = bpy.context.object
        for mod in ob.modifiers:
            if mod.type == 'SIMPLE_DEFORM':
                cls.update_matrix(mod, ob)

    @classmethod
    def get_up_down_return_list(cls, mod, axis, up_, down_, data):
        top, bottom, left, right, front, back = data
        if 'BEND' == mod.deform_method:
            if axis in ('X', 'Y'):
                top = up_
                bottom = down_
            elif axis == 'Z':
                right = up_
                left = down_
        else:
            if axis == 'X':
                right = up_
                left = down_
            elif axis == 'Y':
                back = up_
                front = down_
            elif axis == 'Z':
                top = up_
                bottom = down_
        return top, bottom, left, right, front, back


def register():
    Pref.load_gizmo_data()


def unregister():
    ...
