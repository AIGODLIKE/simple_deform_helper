import math
import uuid
from functools import cache

import bpy
import numpy as np
from bpy.types import AddonPreferences
from mathutils import Vector, Matrix, Euler


class PublicData:
    """Public data class, where all fixed data will be placed
Classify each different type of data separately and cache it to avoid getting
stuck due to excessive update frequency
    """

    G_DeformDrawData = {}
    # Save Deform Vertex And Indices,Update data only when updating
    # deformation boxes

    G_MultipleModifiersBoundData = {}

    G_INDICES = (
        (0, 1), (0, 2), (1, 3), (2, 3),
        (4, 5), (4, 6), (5, 7), (6, 7),
        (0, 4), (1, 5), (2, 6), (3, 7))
    # The order in which the 8 points of the bounding box are drawn
    G_NAME = 'ViewSimpleDeformGizmo_'  # Temporary use files prefix

    G_DEFORM_MESH_NAME = G_NAME + 'DeformMesh'
    G_TMP_MULTIPLE_MODIFIERS_MESH = 'TMP_' + G_NAME + 'MultipleModifiersMesh'
    G_SUB_LEVELS = 7

    G_NAME_EMPTY_AXIS = G_NAME + '_Empty_'
    G_NAME_CON_LIMIT = G_NAME + 'Constraints_Limit_Rotation'  # constraints name
    G_NAME_CON_COPY_ROTATION = G_NAME + 'Constraints_Copy_Rotation'

    G_MODIFIERS_PROPERTY = [  # Copy modifier data
        'angle',
        'deform_axis',
        'deform_method',
        'factor',
        'invert_vertex_group',
        'limits',  # bpy.types.bpy_prop_array
        'lock_x',
        'lock_y',
        'lock_z',
        'origin',
        'vertex_group',
    ]


class PublicClass(PublicData):
    @staticmethod
    def pref_() -> "AddonPreferences":
        return bpy.context.preferences.addons[__package__].preferences

    @property
    def pref(self=None) -> 'AddonPreferences':
        """
        :return: AddonPreferences
        """
        return PublicClass.pref_()


class PublicPoll(PublicClass):
    @classmethod
    def poll_context_mode_is_object(cls) -> bool:
        return bpy.context.mode == 'OBJECT'

    @classmethod
    def poll_modifier_type_is_simple(cls, context):
        """
        Active Object in ('MESH',  'LATTICE')
        Active Modifier Type Is 'SIMPLE_DEFORM' and show_viewport
        :param context:bpy.types.Object
        :return:
        """

        obj = context.object
        if not obj:
            return False
        mod = obj.modifiers.active
        if not mod:
            return False

        available_obj_type = cls.obj_type_is_mesh_or_lattice(obj)
        is_available_obj = cls.mod_is_simple_deform_type(
            mod) and available_obj_type
        is_obj_mode = cls.poll_context_mode_is_object()
        show_mod = mod.show_viewport
        not_is_self_mesh = obj.name != cls.G_NAME
        return is_available_obj and is_obj_mode and show_mod and \
            not_is_self_mesh

    @classmethod
    def poll_object_is_show(cls, context: 'bpy.types.Context') -> bool:
        """
        hava active object and object is show
        :param context:
        :return:
        """
        obj = context.object
        return obj and (not obj.hide_viewport) and (not obj.hide_get())

    @classmethod
    def poll_simple_deform_public(cls, context: 'bpy.types.context') -> bool:
        """Public poll
        In 3D View
        return True
        """
        space = context.space_data
        if not space:
            return False
        show_gizmo = space.show_gizmo if space.type == 'VIEW_3D' else True
        is_simple = cls.poll_modifier_type_is_simple(context)
        is_show = cls.poll_object_is_show(context)
        return is_simple and show_gizmo and is_show

    @classmethod
    def poll_simple_deform_modifier_is_bend(cls, context):
        """
        Public poll
        active modifier deform_method =='BEND'
        """
        simple = cls.poll_simple_deform_public(context)
        is_bend = simple and (
                context.object.modifiers.active.deform_method == 'BEND')
        return simple and is_bend

    @classmethod
    def poll_simple_deform_show_bend_axis_witch(cls, context):
        """
        Show D
        """
        switch_axis = cls.pref_().display_bend_axis_switch_gizmo
        bend = cls.poll_simple_deform_modifier_is_bend(context)
        return switch_axis and bend

    @classmethod
    def simple_deform_show_gizmo_poll(cls, context):
        poll = cls.poll_simple_deform_public(context)
        not_switch = (not cls.poll_simple_deform_show_bend_axis_witch(context))
        return poll and not_switch


class PublicTranslate(PublicPoll):
    @classmethod
    def translate_text(cls, text):
        return bpy.app.translations.pgettext(text)

    @classmethod
    def translate_header_text(cls, mode, value):
        return cls.translate_text(mode) + ':{}'.format(value)


class GizmoClassMethod(PublicTranslate):

    @classmethod
    def get_depsgraph(cls, obj: 'bpy.types.Object'):
        """
        @param obj: dep obj
        @return: If there is no input obj, reverse the active object evaluated
        """
        context = bpy.context
        if obj is None:
            obj = context.object
        dep = context.evaluated_depsgraph_get()
        return obj.evaluated_get(dep)

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
    def get_modifiers_parameter(cls, modifier):
        prop = bpy.types.bpy_prop_array
        return list(
            getattr(modifier, i)[:] if type(
                getattr(modifier, i)) == prop else getattr(modifier, i)
            for i in cls.G_MODIFIERS_PROPERTY
        )

    @classmethod
    def value_limit(cls, value, max_value=1, min_value=0):
        """
        @param value: limit value
        @param max_value: Maximum allowed
        @param min_value: Minimum allowed
        @return: If the input value is greater than the maximum value or less
        than the minimum value
        it will be limited to the maximum or minimum value
        """
        if value > max_value:
            return max_value
        elif value < min_value:
            return min_value
        else:
            return value

    @classmethod
    def number_is_positive(cls, number: 'int') -> bool:
        """return bool value
        if number is positive return True else return False
        """
        return number == abs(number)

    @classmethod
    def _link_obj(cls, obj, link):
        context = bpy.context
        objects = context.view_layer.active_layer_collection.collection.objects
        if obj.name not in objects:
            if link:
                objects.link(
                    obj)
            else:
                objects.unlink(
                    obj)

    @classmethod
    def link_obj_to_active_collection(cls, obj: 'bpy.types.Object'):
        cls._link_obj(obj, True)

    @classmethod
    def unlink_obj_to_active_collection(cls, obj: 'bpy.types.Object'):
        cls._link_obj(obj, False)

    @classmethod
    def get_mesh_max_min_co(cls,
                            obj: 'bpy.context.object') -> '[Vector,Vector]':
        if obj.type == 'MESH':
            ver_len = obj.data.vertices.__len__()
            list_vertices = np.zeros(ver_len * 3, dtype=np.float32)
            obj.data.vertices.foreach_get('co', list_vertices)
            list_vertices = list_vertices.reshape(ver_len, 3)
        elif obj.type == 'LATTICE':
            ver_len = obj.data.points.__len__()
            list_vertices = np.zeros(ver_len * 3, dtype=np.float32)
            obj.data.points.foreach_get('co_deform', list_vertices)
            list_vertices = list_vertices.reshape(ver_len, 3)
        else:
            list_vertices = np.zeros((3, 3), dtype=np.float32)
        return Vector(list_vertices.min(axis=0)).freeze(), Vector(
            list_vertices.max(axis=0)).freeze()

    @classmethod
    def matrix_calculation(cls, mat: 'Matrix',
                           calculation_list: 'list') -> list:
        return [mat @ Vector(i) for i in calculation_list]

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
    def co_to_direction(cls, mat, data):
        (min_x, min_y, min_z), (max_x, max_y,
                                max_z) = data
        a = mat @ Vector((max_x, max_y, max_z))
        b = mat @ Vector((max_x, min_y, min_z))
        c = mat @ Vector((min_x, max_y, min_z))
        d = mat @ Vector((min_x, min_y, max_z))
        point_list = ((a, d),
                      (c, b),
                      (c, d),
                      (a, b),
                      (d, b),
                      (c, a),)

        return list((aa + bb) / 2 for (aa, bb) in point_list)

    @classmethod
    def tow_co_to_coordinate(cls, data):
        ((min_x, min_y, min_z), (max_x, max_y, max_z)) = data
        return (
            Vector((max_x, min_y, min_z)),
            Vector((min_x, min_y, min_z)),
            Vector((max_x, max_y, min_z)),
            Vector((min_x, max_y, min_z)),
            Vector((max_x, min_y, max_z)),
            Vector((min_x, min_y, max_z)),
            Vector((max_x, max_y, max_z)),
            Vector((min_x, max_y, max_z))
        )

    @classmethod
    def mod_is_simple_deform_type(cls, mod):
        return mod and mod.type == 'SIMPLE_DEFORM'

    @classmethod
    def obj_type_is_mesh_or_lattice(cls, obj: 'bpy.types.Object'):
        return obj and (obj.type in ('MESH', 'LATTICE'))

    @classmethod
    def from_vertices_new_mesh(cls, name, vertices):
        new_mesh = bpy.data.meshes.new(name)
        new_mesh.from_pydata(vertices, cls.G_INDICES, [])
        new_mesh.update()
        return new_mesh

    @classmethod
    def copy_modifier_parameter(cls, old_mod, new_mod):
        for prop_name in cls.G_MODIFIERS_PROPERTY:
            origin_value = getattr(old_mod, prop_name, None)
            is_array_prop = type(origin_value) == bpy.types.bpy_prop_array
            value = origin_value[:] if is_array_prop else origin_value
            setattr(new_mod, prop_name, value)


class PublicProperty(GizmoClassMethod):

    def __from_up_down_point_get_limits_point(self, up_point, down_point):

        def ex(a):
            return down_point + ((up_point - down_point) * Vector((a, a, a)))

        up_limits = ex(self.modifier_up_limits)
        down_limits = ex(self.modifier_down_limits)
        return up_limits, down_limits

    @cache
    def _get_limits_point_and_bound_box_co(self):
        top, bottom, left, right, front, back = self.modifier_bound_box_pos
        mod = self.modifier
        g_l = self.__from_up_down_point_get_limits_point
        origin = self.modifier.origin
        if origin:
            vector_axis = self.get_vector_axis(mod)
            matrix = self.modifier.origin.matrix_local
            origin_mat = matrix.to_3x3()
            axis = origin_mat @ vector_axis
            point_lit = [[top, bottom], [left, right], [front, back]]
            for f in range(point_lit.__len__()):
                i = point_lit[f][0]
                j = point_lit[f][1]
                angle = self.point_to_angle(i, j, f, axis)
                if abs(angle - 180) < 0.00001:
                    up_point, down_point = j, i
                    up_limits, down_limits = g_l(j, i)
                    point_lit[f][1], point_lit[f][0] = up_limits, down_limits
                elif abs(angle) < 0.00001:
                    up_point, down_point = i, j
                    up_limits, down_limits = g_l(i, j)
                    point_lit[f][0], point_lit[f][1] = up_limits, down_limits
            [[top, bottom], [left, right], [front, back]] = point_lit
        else:
            axis = self.modifier_deform_axis
            if 'BEND' == self.modifier.deform_method:
                if axis in ('X', 'Y'):
                    up_point, down_point = top, bottom
                    top, bottom = up_limits, down_limits = g_l(top, bottom)
                elif axis == 'Z':
                    up_point, down_point = right, left
                    right, left = up_limits, down_limits = g_l(right, left)
            else:
                if axis == 'X':
                    up_point, down_point = right, left
                    right, left = up_limits, down_limits = g_l(right, left)
                elif axis == 'Y':
                    up_point, down_point = back, front
                    back, front = up_limits, down_limits = g_l(back, front)

                elif axis == 'Z':
                    up_point, down_point = top, bottom
                    top, bottom = up_limits, down_limits = g_l(top, bottom)

        points = (up_point, down_point, up_limits, down_limits)
        each_point = (
            (right[0], back[1], top[2]), (left[0], front[1], bottom[2],))
        return points, self.tow_co_to_coordinate(each_point)

    # ----------------------
    @cache
    def _each_face_pos(self, mat, co):
        return self.co_to_direction(mat, co)

    @classmethod
    def clear_cache(cls):
        cls.clear_point_cache()
        cls.clear_modifiers_data()

    @classmethod
    def clear_point_cache(cls):
        cls._get_limits_point_and_bound_box_co.cache_clear()

    @classmethod
    def clear_modifiers_data(cls):
        cls.G_MultipleModifiersBoundData.clear()

    @classmethod
    def clear_deform_data(cls):
        cls.G_DeformDrawData.clear()

    # --------------- Cache Data ----------------------
    @property
    def modifier_bound_co(self):
        def get_bound_co_data():
            key = 'self.modifier.name'
            if key not in self.G_MultipleModifiersBoundData:
                self.G_MultipleModifiersBoundData[
                    key] = self.get_mesh_max_min_co(self.obj)
            return self.G_MultipleModifiersBoundData[key]

        return self.G_MultipleModifiersBoundData.get(self.modifier.name,
                                                     get_bound_co_data())

    @property
    def modifier_bound_box_pos(self):
        matrix = Matrix()
        matrix.freeze()
        return self.co_to_direction(matrix, self.modifier_bound_co)

    @property
    def modifier_limits_point(self):
        points, _ = self._get_limits_point_and_bound_box_co()
        return self.matrix_calculation(self.obj_matrix_world, points)

    @property
    def modifier_limits_bound_box(self):
        _, bound = self._get_limits_point_and_bound_box_co()
        return self.matrix_calculation(self.obj_matrix_world, bound)

    @property
    def modifier_origin_is_available(self):
        try:
            self._get_limits_point_and_bound_box_co()
            return True
        except UnboundLocalError:
            self.clear_point_cache()
            return False

    #  --------------- Compute Data ----------------------
    @property
    def obj(self):
        return bpy.context.object

    @property
    def obj_matrix_world(self):
        if self.obj:
            mat = self.obj.matrix_world.copy()
            mat.freeze()
            return mat
        mat = Matrix()
        mat.freeze()
        return mat

    @property
    def modifier(self):
        obj = self.obj
        if not obj:
            return
        return obj.modifiers.active

    @property
    def modifier_deform_axis(self):
        mod = self.modifier
        if mod:
            return mod.deform_axis

    @property
    def modifier_angle(self):
        mod = self.modifier
        if mod:
            return mod.angle

    @property
    def modifier_is_use_angle_value(self):
        if self.active_modifier_is_simple_deform:
            return self.modifier.deform_method in ('TWIST', 'BEND')

    @property
    def modifier_deform_method_is_bend(self):
        if self.active_modifier_is_simple_deform:
            return self.modifier.deform_method == 'BEND'

    @property
    def modifier_up_limits(self):
        if self.modifier:
            return self.modifier.limits[1]

    @property
    def modifier_down_limits(self):
        if self.modifier:
            return self.modifier.limits[0]

    @property
    def active_modifier_is_simple_deform(self):
        return self.mod_is_simple_deform_type(self.modifier)

    # ----- point
    @property
    def point_up(self):
        return self.modifier_limits_point[0]

    @property
    def point_down(self):
        return self.modifier_limits_point[1]

    @property
    def point_limits_up(self):
        return self.modifier_limits_point[2]

    @property
    def point_limits_down(self):
        return self.modifier_limits_point[3]

    # ------

    @property
    def obj_origin_property_group(self):
        mod = self.modifier
        if mod.origin:
            return mod.origin.SimpleDeformGizmo_PropertyGroup
        else:
            return self.obj.SimpleDeformGizmo_PropertyGroup

    @property
    def origin_mode(self):
        return self.obj_origin_property_group.origin_mode

    @property
    def is_limits_middle_mode(self):
        return self.origin_mode == 'LIMITS_MIDDLE'

    @property
    def is_middle_mode(self):
        return self.origin_mode in ('LIMITS_MIDDLE', 'MIDDLE')

    @property
    def modifier_is_use_origin_axis(self):
        return self.obj_origin_property_group.origin_mode != 'NOT'

    @property
    def modifier_is_have_origin(self):
        return self.modifier_is_use_origin_axis and self.modifier.origin


class GizmoUpdate(PublicProperty):
    def fix_origin_parent_and_angle(self):
        obj = self.obj
        mod = self.modifier
        if not obj or not mod or not getattr(mod, 'origin', False):
            return

        origin = mod.origin
        if not origin:
            return

        if origin.parent != obj:
            origin.parent = obj
        origin.rotation_euler.zero()
        if not self.modifier_origin_is_available:
            origin.location.zero()
        origin.scale = 1, 1, 1

    def new_origin_empty_object(self):
        mod = self.modifier
        obj = self.obj
        origin = mod.origin
        if not origin:
            new_name = self.G_NAME_EMPTY_AXIS + str(uuid.uuid4())
            origin_object = bpy.data.objects.new(new_name, None)
            self.link_obj_to_active_collection(origin_object)
            origin_object.hide_set(True)
            origin_object.empty_display_size = min(obj.dimensions)
            mod.origin = origin_object
            origin_mode = self.obj.SimpleDeformGizmo_PropertyGroup.origin_mode
            origin_object.SimpleDeformGizmo_PropertyGroup.origin_mode = origin_mode
        else:
            origin_object = mod.origin
            origin_object.hide_viewport = False
        if origin_object == obj:
            return
        # add constraints
        name = self.G_NAME_CON_LIMIT
        if origin_object.constraints.keys().__len__() > 2:
            origin_object.constraints.clear()
        if name in origin_object.constraints.keys():
            limit_constraints = origin.constraints.get(name)
        else:
            limit_constraints = origin_object.constraints.new(
                'LIMIT_ROTATION')
            limit_constraints.name = name
            limit_constraints.owner_space = 'WORLD'
            limit_constraints.space_object = obj
        limit_constraints.use_transform_limit = True
        limit_constraints.use_limit_x = True
        limit_constraints.use_limit_y = True
        limit_constraints.use_limit_z = True
        con_copy_name = self.G_NAME_CON_COPY_ROTATION
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
        self.fix_origin_parent_and_angle()
        return origin_object

    def update_object_origin_matrix(self):
        if self.modifier_is_have_origin:
            origin_mode = self.origin_mode
            origin_object = self.modifier.origin
            if origin_mode == 'UP_LIMITS':
                origin_object.matrix_world.translation = Vector(
                    self.point_limits_up)
            elif origin_mode == 'DOWN_LIMITS':
                origin_object.matrix_world.translation = Vector(
                    self.point_limits_down)
            elif origin_mode == 'LIMITS_MIDDLE':
                translation = (
                                      self.point_limits_up +
                                      self.point_limits_down) / 2
                origin_object.matrix_world.translation = translation
            elif origin_mode == 'MIDDLE':
                translation = (self.point_up + self.point_down) / 2
                origin_object.matrix_world.translation = translation

    def update_multiple_modifiers_data(self):
        obj = self.obj
        context = bpy.context
        if not self.obj_type_is_mesh_or_lattice(
                obj) or not self.poll_modifier_type_is_simple(context):
            return
        self.clear_point_cache()
        self.clear_modifiers_data()
        data = bpy.data
        name = self.G_TMP_MULTIPLE_MODIFIERS_MESH

        # del old tmp object
        old_object = data.objects.get(name)
        if old_object:
            data.objects.remove(old_object)

        if data.meshes.get(name):
            data.meshes.remove(data.meshes.get(name))

        """get origin mesh bound box as multiple basic mesh 
        add multiple modifiers and get  depsgraph obj bound box
        """
        vertices = self.tow_co_to_coordinate(self.get_mesh_max_min_co(self.obj))
        new_mesh = self.from_vertices_new_mesh(name, vertices)
        modifiers_obj = data.objects.new(name, new_mesh)

        self.link_obj_to_active_collection(modifiers_obj)
        if modifiers_obj == obj:  # is cycles
            return
        if modifiers_obj.parent != obj:
            modifiers_obj.parent = obj

        modifiers_obj.modifiers.clear()
        subdivision = modifiers_obj.modifiers.new('1', 'SUBSURF')
        subdivision.levels = self.G_SUB_LEVELS

        for mod in context.object.modifiers:
            if self.mod_is_simple_deform_type(mod):
                dep_bound_tow_co = self.get_mesh_max_min_co(
                    self.get_depsgraph(modifiers_obj))
                self.G_MultipleModifiersBoundData[mod.name] = dep_bound_tow_co
                new_mod = modifiers_obj.modifiers.new(mod.name, 'SIMPLE_DEFORM')
                self.copy_modifier_parameter(mod, new_mod)
        data.objects.remove(modifiers_obj)

    def update_deform_wireframe(self):
        if not self.pref.update_deform_wireframe:
            return
        name = self.modifier.name
        deform_name = self.G_DEFORM_MESH_NAME

        co = self.G_MultipleModifiersBoundData[name]

        deform_obj = bpy.data.objects.get(deform_name, None)

        if not deform_obj:
            a, b = 0.5, -0.5
            vertices = self.tow_co_to_coordinate(((b, b, b), (a, a, a)))
            new_mesh = self.from_vertices_new_mesh(name, vertices)
            deform_obj = bpy.data.objects.new(deform_name, new_mesh)
            deform_obj.hide_select = True
            # deform_obj.hide_set(True)
            deform_obj.hide_render = True
            deform_obj.hide_viewport = True

        self.link_obj_to_active_collection(deform_obj)

        deform_obj.parent = self.obj

        tmv = deform_obj.hide_viewport
        tmh = deform_obj.hide_get()
        deform_obj.hide_viewport = False
        deform_obj.hide_set(False)

        # Update Matrix
        deform_obj.matrix_world = Matrix()
        center = (co[0] + co[1]) / 2
        scale = co[1] - co[0]
        deform_obj.matrix_world = self.obj_matrix_world @ \
                                  deform_obj.matrix_world
        deform_obj.location = center
        deform_obj.scale = scale

        # Update Modifier data
        mods = deform_obj.modifiers
        mods.clear()
        subdivision = mods.new('1', 'SUBSURF')
        subdivision.levels = self.G_SUB_LEVELS

        new_mod = mods.new(name, 'SIMPLE_DEFORM')
        self.copy_modifier_parameter(self.modifier, new_mod)

        # Get vertices data
        context = bpy.context
        obj = self.get_depsgraph(deform_obj)
        matrix = deform_obj.matrix_world.copy()
        ver_len = obj.data.vertices.__len__()
        edge_len = obj.data.edges.__len__()
        if 'numpy_data' not in self.G_DeformDrawData:
            self.G_DeformDrawData['numpy_data'] = {}
        numpy_data = self.G_DeformDrawData['numpy_data']
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

        modifiers = self.get_modifiers_parameter(self.modifier)
        limits = context.object.modifiers.active.limits[:]

        deform_obj.hide_viewport = tmv
        deform_obj.hide_set(tmh)

        self.G_DeformDrawData['simple_deform_bound_data'] = (
            ver, indices, self.obj_matrix_world, modifiers, limits[:]
        )


class GizmoUtils(GizmoUpdate):
    custom_shape: dict
    init_mouse_region_y: float
    init_mouse_region_x: float
    mouse_dpi: int
    matrix_basis: Matrix
    draw_type: str

    def generate_gizmo(self, gizmo_data):
        """Generate Gizmo From Input Data
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

    def init_shape(self):
        if not hasattr(self, 'custom_shape'):
            self.custom_shape = {}
            from .src.shape import  __shape__
            for key,value in __shape__.items():
                self.custom_shape[key] = self.new_custom_shape('TRIS', value)

    def init_setup(self):
        self.init_shape()

    def init_invoke(self, context, event):
        self.init_mouse_region_y = event.mouse_region_y
        self.init_mouse_region_x = event.mouse_region_x

    def __update_matrix_func(self, context):
        func = getattr(self, 'update_gizmo_matrix', None)
        if func and self.modifier_origin_is_available:
            func(context)

    def draw(self, context):
        if self.modifier_origin_is_available:
            self.draw_custom_shape(self.custom_shape[self.draw_type])
            self.__update_matrix_func(context)

    def draw_select(self, context, select_id):
        if self.modifier_origin_is_available:
            self.draw_custom_shape(
                self.custom_shape[self.draw_type], select_id=select_id)
            self.__update_matrix_func(context)

    def get_delta(self, event):
        delta = (
                        self.init_mouse_region_x - event.mouse_region_x) \
                / self.mouse_dpi
        return delta

    def event_handle(self, event):
        """General event triggering"""
        data_path = ('object.SimpleDeformGizmo_PropertyGroup.origin_mode',
                     'object.modifiers.active.origin.SimpleDeformGizmo_PropertyGroup.origin_mode')

        if event.type in ('WHEELUPMOUSE', 'WHEELDOWNMOUSE'):
            reverse = (event.type == 'WHEELUPMOUSE')
            for path in data_path:
                bpy.ops.wm.context_cycle_enum(
                    data_path=path, reverse=reverse, wrap=True)
        elif event.type in ('X', 'Y', 'Z'):
            self.obj.modifiers.active.deform_axis = event.type
        elif event.type == 'A' and 'BEND' == self.modifier.deform_method:
            self.pref.display_bend_axis_switch_gizmo = True
            return {'FINISHED'}
        elif event.type == 'W' and event.value == 'RELEASE':
            self.pref.update_deform_wireframe = \
                self.pref.update_deform_wireframe ^ True
        return {'RUNNING_MODAL'}

    @staticmethod
    def tag_redraw(context):
        if context.area:
            context.area.tag_redraw()

    def get_snap(self, delta, tweak):
        is_snap = 'SNAP' in tweak
        is_precise = 'PRECISE' in tweak
        if is_snap and is_precise:
            delta = round(delta)
        elif is_snap:
            delta //= 5
            delta *= 5
        elif is_precise:
            delta /= self.mouse_dpi
            delta //= 0.01
            delta *= 0.01
        return delta

class GizmoGroupUtils(GizmoUtils):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'3D',
                  'PERSISTENT',
                  }


class Tmp:
    @classmethod
    def get_origin_bounds(cls, obj: 'bpy.types.Object') -> list:
        modifiers_dict = {}
        for mod in obj.modifiers:
            if (mod == obj.modifiers.active) or (modifiers_dict != {}):
                modifiers_dict[mod] = (mod.show_render, mod.show_viewport)
                mod.show_viewport = False
                mod.show_render = False
        matrix_obj = obj.matrix_world.copy()
        obj.matrix_world.zero()
        obj.scale = (1, 1, 1)
        bound = cls.bound_box_to_list(obj)
        obj.matrix_world = matrix_obj
        for mod in modifiers_dict:
            show_render, show_viewport = modifiers_dict[mod]
            mod.show_render = show_render
            mod.show_viewport = show_viewport
        return list(bound)

    def update_gizmo_rotate(self):
        mod = self.modifier
        axis = self.modifier_deform_axis
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

    @classmethod
    def bound_box_to_list(cls, obj: 'bpy.types.Object'):
        return tuple(i[:] for i in obj.bound_box)

    @classmethod
    def properties_is_modifier(cls) -> bool:
        """Returns whether there is a modifier property panel open in the
        active window.
         If it is open, it returns to True else False
        """
        for area in bpy.context.screen.areas:
            if area.type == 'PROPERTIES':
                for space in area.spaces:
                    is_m = space.context == 'MODIFIER'
                    if space.type == 'PROPERTIES' and is_m:
                        return True
        return False
