import ast
import math
import re
import uuid
from functools import cache
from time import monotonic

import bpy
import numpy as np
from bpy.types import AddonPreferences
from mathutils import Vector, Matrix, Euler

from .stages import StageCache, hide_runtime_object, render_job_running


CONTROL_COLLECTION_NAME = "Simple Deform Controls"
CONTROL_COLLECTION_MARKER = "_simple_deform_helper_controls"


def _collection_contains(root, collection):
    if root == collection:
        return True
    return any(_collection_contains(child, collection) for child in root.children)


def control_collection(scene=None, create=True):
    """Return the scene-local collection used for persistent helper objects."""
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None:
        return None
    for collection in bpy.data.collections:
        if (
                collection.get(CONTROL_COLLECTION_MARKER, False) and
                _collection_contains(scene.collection, collection)
        ):
            return collection
    if not create:
        return None
    collection = bpy.data.collections.new(CONTROL_COLLECTION_NAME)
    collection[CONTROL_COLLECTION_MARKER] = True
    collection.hide_render = True
    try:
        collection.color_tag = "COLOR_05"
    except (AttributeError, TypeError):
        pass
    scene.collection.children.link(collection)
    return collection


def move_object_to_control_collection(obj, scene=None):
    """Consolidate an add-on-owned helper without touching user objects."""
    collection = control_collection(scene)
    if obj is None or collection is None:
        return collection
    if obj.name not in collection.objects:
        collection.objects.link(obj)
    for owner in tuple(obj.users_collection):
        if owner != collection:
            owner.objects.unlink(obj)
    return collection


def set_helper_object_visible(obj, visible, view_layer=None):
    """Hide helpers by default while allowing an explicit editing session."""
    if obj is None:
        return
    obj.hide_render = True
    obj.hide_select = not visible
    layers = (view_layer,) if view_layer is not None else tuple(
        layer for scene in bpy.data.scenes for layer in scene.view_layers)
    for layer in layers:
        try:
            obj.hide_set(not visible, view_layer=layer)
        except (ReferenceError, RuntimeError, TypeError):
            pass


def remove_unused_control_collections():
    for collection in tuple(bpy.data.collections):
        if (
                collection.get(CONTROL_COLLECTION_MARKER, False) and
                not collection.objects and not collection.children
        ):
            bpy.data.collections.remove(collection)


def get_pref():
    return bpy.context.preferences.addons[__package__].preferences


def get_loc_matrix(location: Vector) -> Matrix:
    return Matrix.Translation(location)


def get_rot_matrix(rotation: Euler) -> Matrix:
    return rotation.to_matrix().to_4x4()


def get_sca_matrix(scale: Vector):
    scale_mx = Matrix()
    for i in range(3):
        scale_mx[i][i] = scale[i]
    return scale_mx


def from_curve_get_animation_offset(obj: bpy.types.Object, default=None) -> Vector:
    """When the curve is animated, the origin will be changed to the start of the curve.
    """
    if obj.type == "CURVE" and obj.data.use_path:
        # 处理曲线使用动画路径情况
        try:
            dep = bpy.context.evaluated_depsgraph_get()
            spline = obj.evaluated_get(dep).data.splines[0]
            if spline.type == "BEZIER":
                # bpy.data.curves["BézierCircle.001"].splines[1].bezier_points[2].co[0]
                sl = Vector(spline.bezier_points[0].co[:])
            else:
                # "POLY", "BEZIER", "NURBS"
                sl = Vector(spline.points[0].co[:3])
                # bpy.data.curves["BézierCircle.001"].splines[0].points[0].co[1]
            return sl
        except Exception as e:
            print("Curve use_path Error", e.args)
    return default


def get_language_list() -> list:
    """
    Traceback (most recent call last):
  File "<blender_console>", line 1, in <module>
TypeError: bpy_struct: item.attr = val: enum "a" not found in ("DEFAULT", "en_US", "es", "ja_JP", "sk_SK", "vi_VN", "zh_HANS", "ar_EG", "de_DE", "fr_FR", "it_IT", "ko_KR", "pt_BR", "pt_PT", "ru_RU", "uk_UA", "zh_TW", "ab", "ca_AD", "cs_CZ", "eo", "eu_EU", "fa_IR", "ha", "he_IL", "hi_IN", "hr_HR", "hu_HU", "id_ID", "ky_KG", "nl_NL", "pl_PL", "sr_RS", "sr_RS@latin", "sv_SE", "th_TH", "tr_TR")
    """
    try:
        bpy.context.preferences.view.language = ""
    except TypeError as e:
        matches = re.findall(r"\(([^()]*)\)", e.args[-1])
        return ast.literal_eval(f"({matches[-1]})")


class PublicData:
    """Public data class, where all fixed data will be placed
Classify each different type of data separately and cache it to avoid getting
stuck due to excessive update frequency
    """

    G_DeformDrawData = {}
    # Save Deform Vertex And Indices,Update data only when updating
    # deformation boxes

    G_MultipleModifiersBoundData = {}  # Legacy compatibility; stage data lives in StageCache.

    G_INDICES = (
        (0, 1), (0, 2), (1, 3), (2, 3),
        (4, 5), (4, 6), (5, 7), (6, 7),
        (0, 4), (1, 5), (2, 6), (3, 7))
    # The order in which the 8 points of the bounding box are drawn
    G_NAME = "ViewSimpleDeformGizmo_"  # Temporary use files prefix

    G_DEFORM_MESH_NAME = G_NAME + "DeformMesh"
    G_TMP_MULTIPLE_MODIFIERS_MESH = "TMP_" + G_NAME + "MultipleModifiersMesh"
    G_PREVIEW_SEGMENTS = 24
    G_PREVIEW_INTERVAL = 1.0 / 30.0
    G_PREVIEW_LAST_UPDATE = 0.0

    G_NAME_EMPTY_AXIS = G_NAME + "_Empty_"
    G_NAME_CON_LIMIT = G_NAME + "Constraints_Limit_Rotation"  # constraints name
    G_NAME_CON_COPY_ROTATION = G_NAME + "Constraints_Copy_Rotation"

    G_OWNER_PROP = "_simple_deform_helper_owned"
    G_OWNER_VERSION_PROP = "_simple_deform_helper_owner_version"
    G_OWNER_UUID_PROP = "_simple_deform_helper_owner_uuid"
    G_OBJECT_UUID_PROP = "_simple_deform_helper_uuid"
    G_OWNER_VERSION = 1

    G_MODIFIERS_PROPERTY = [  # Copy modifier data
        "angle",
        "deform_axis",
        "deform_method",
        "factor",
        "invert_vertex_group",
        "limits",  # bpy.types.bpy_prop_array
        "lock_x",
        "lock_y",
        "lock_z",
        "origin",
        "vertex_group",
    ]


class PublicClass(PublicData):

    @property
    def pref(self) -> "AddonPreferences":
        """
        :return: AddonPreferences
        """
        return get_pref()


class PublicPoll(PublicClass):
    @classmethod
    def poll_context_mode_is_object(cls) -> bool:
        return bpy.context.mode == "OBJECT"

    @classmethod
    def poll_modifier_type_is_simple(cls, context):
        """
        Active Object in ("MESH",  "LATTICE")
        Active Modifier Type Is "SIMPLE_DEFORM" and show_viewport
        :param context:bpy.types.Object
        :return:
        """

        obj = context.object
        if not obj:
            return False
        mod = obj.modifiers.active
        if not mod:
            return False

        available_obj_type = GizmoClassMethod.obj_type_is_usable(obj)
        is_available_obj = GizmoClassMethod.mod_is_simple_deform_type(
            mod) and available_obj_type
        is_obj_mode = PublicPoll.poll_context_mode_is_object()
        show_mod = mod.show_viewport
        return is_available_obj and is_obj_mode and show_mod

    @classmethod
    def poll_object_is_show(cls, context: "bpy.types.Context") -> bool:
        """
        hava active object and object is show
        :param context:
        :return:
        """
        obj = context.object
        return obj and (not obj.hide_viewport) and (not obj.hide_get())

    @classmethod
    def poll_simple_deform_public(cls, context: "bpy.types.context") -> bool:
        """Public poll
        In 3D View
        return True
        """
        space = context.space_data
        if not space:
            return False
        pref = get_pref()
        if not pref.show_gizmo:
            return False
        show_gizmo = space.show_gizmo if space.type == "VIEW_3D" else True
        is_simple = cls.poll_modifier_type_is_simple(context)
        is_show = cls.poll_object_is_show(context)
        return is_simple and show_gizmo and is_show

    @classmethod
    def poll_simple_deform_modifier_is_bend(cls, context):
        """
        Public poll
        active modifier deform_method =="BEND"
        """
        simple = cls.poll_simple_deform_public(context)
        is_bend = simple and (
                context.object.modifiers.active.deform_method == "BEND")
        return simple and is_bend

    @classmethod
    def poll_simple_deform_show_bend_axis_witch(cls, context):
        """
        Show D
        """
        switch_axis = get_pref().display_bend_axis_switch_gizmo
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
        return cls.translate_text(mode) + ":{}".format(value)


class GizmoClassMethod(PublicTranslate):

    @classmethod
    def get_depsgraph(cls, obj: "bpy.types.Object"):
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
        if "BEND" == mod.deform_method:
            vector_axis = Vector((0, 0, 1)) if axis in (
                "Y", "X") else Vector((1, 0, 0))
        else:
            vector = (Vector((1, 0, 0)) if (
                    axis == "X") else Vector((0, 1, 0)))
            vector_axis = Vector((0, 0, 1)) if (
                    axis == "Z") else vector
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
    def get_constraints_parameter_from_object(cls, obj):
        def get_prop(bl_prop):
            return {
                pn.identifier: getattr(bl_prop, pn.identifier)
                for pn in bl_prop.bl_rna.properties
            }

        return {
            c.name: get_prop(c)
            for c in obj.constraints
        }

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
    def number_is_positive(cls, number: "int") -> bool:
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
    def link_obj_to_active_collection(cls, obj: "bpy.types.Object"):
        cls._link_obj(obj, True)

    @classmethod
    def unlink_obj_to_active_collection(cls, obj: "bpy.types.Object"):
        cls._link_obj(obj, False)

    @classmethod
    def get_mesh_max_min_co(cls,
                            obj: "bpy.context.object") -> "[Vector,Vector]":
        list_vertices = None
        if obj.type == "MESH":
            ver_len = obj.data.vertices.__len__()
            if ver_len:
                list_vertices = np.zeros(ver_len * 3, dtype=np.float32)
                obj.data.vertices.foreach_get("co", list_vertices)
                list_vertices = list_vertices.reshape(ver_len, 3)
        elif obj.type == "LATTICE":
            ver_len = obj.data.points.__len__()
            if ver_len:
                list_vertices = np.zeros(ver_len * 3, dtype=np.float32)
                obj.data.points.foreach_get("co_deform", list_vertices)
                list_vertices = list_vertices.reshape(ver_len, 3)
        elif obj.type == "CURVE":
            for spline in obj.data.splines:
                pl = spline.points.__len__()
                bl = spline.bezier_points.__len__()
                data = None
                if pl:
                    # SplinePoint.co is a four-dimensional homogeneous value.
                    p_co = np.zeros(pl * 4, dtype=np.float32)
                    spline.points.foreach_get("co", p_co)
                    data = p_co.reshape(pl, 4)[:, :3]
                if bl:
                    b_co = np.zeros(bl * 3, dtype=np.float32)
                    spline.bezier_points.foreach_get("co", b_co)
                    data = b_co.reshape(bl, 3)
                if data is not None:
                    if list_vertices is None:
                        list_vertices = data
                    else:
                        list_vertices = np.concatenate((list_vertices, data))
        if list_vertices is None or list_vertices.size == 0:
            bound_box = tuple(Vector(point) for point in getattr(obj, "bound_box", ()))
            is_invalid = (
                not bound_box or
                (len(bound_box) == 8 and all(point == Vector((-1, -1, -1)) for point in bound_box))
            )
            if is_invalid:
                zero = Vector((0.0, 0.0, 0.0))
                zero.freeze()
                return zero, zero
            list_vertices = np.asarray(bound_box, dtype=np.float32)
        return (
            Vector(list_vertices.min(axis=0)).freeze(),
            Vector(list_vertices.max(axis=0)).freeze(),
        )

    @classmethod
    def matrix_calculation(cls, mat: "Matrix",
                           calculation_list: "list") -> list:
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
        return mod and mod.type == "SIMPLE_DEFORM"

    @classmethod
    def obj_type_is_usable(cls, obj: "bpy.types.Object"):
        return obj and (obj.type in ("MESH", "LATTICE", "CURVE", "FONT"))

    @classmethod
    def topology_axis_sample_count(cls, obj, axis):
        axis_index = {"X": 0, "Y": 1, "Z": 2}.get(axis, 2)
        values = []
        if not obj:
            return 0
        if obj.type == "MESH":
            values = [vertex.co[axis_index] for vertex in obj.data.vertices]
        elif obj.type == "LATTICE":
            values = [point.co_deform[axis_index] for point in obj.data.points]
        elif obj.type == "CURVE":
            for spline in obj.data.splines:
                values.extend(point.co[axis_index] for point in spline.points)
                values.extend(point.co[axis_index] for point in spline.bezier_points)
        elif obj.type == "FONT":
            # Text is evaluated procedurally; its resolution is not represented
            # by editable object-space points.
            return 4
        return len({round(float(value), 6) for value in values})

    @classmethod
    def from_vertices_new_mesh(cls, name, vertices):
        new_mesh = bpy.data.meshes.new(name)
        new_mesh.from_pydata(vertices, cls.G_INDICES, [])
        new_mesh.update()
        return new_mesh

    @classmethod
    def copy_modifier_parameter(cls, old_mod, new_mod, include_vertex_group=True):
        for prop_name in cls.G_MODIFIERS_PROPERTY:
            if prop_name in {"vertex_group", "invert_vertex_group"} and not include_vertex_group:
                continue
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
            if "BEND" == self.modifier.deform_method:
                if axis in ("X", "Y"):
                    up_point, down_point = top, bottom
                    top, bottom = up_limits, down_limits = g_l(top, bottom)
                elif axis == "Z":
                    up_point, down_point = right, left
                    right, left = up_limits, down_limits = g_l(right, left)
            else:
                if axis == "X":
                    up_point, down_point = right, left
                    right, left = up_limits, down_limits = g_l(right, left)
                elif axis == "Y":
                    up_point, down_point = back, front
                    back, front = up_limits, down_limits = g_l(back, front)

                elif axis == "Z":
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
        StageCache.clear()

    @classmethod
    def clear_deform_data(cls):
        cls.G_DeformDrawData.clear()
        PublicData.G_PREVIEW_LAST_UPDATE = 0.0

    # --------------- Cache Data ----------------------
    @property
    def modifier_bound_co(self):
        obj = self.obj
        modifier = self.modifier
        if obj and modifier:
            stage_bounds = StageCache.bounds_for(obj, modifier)
            if stage_bounds is not None:
                return stage_bounds
        return self.get_mesh_max_min_co(obj)

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
            return self.modifier.deform_method in ("TWIST", "BEND")

    @property
    def modifier_deform_method_is_bend(self):
        if self.active_modifier_is_simple_deform:
            return self.modifier.deform_method == "BEND"

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
        return self.origin_mode == "LIMITS_MIDDLE"

    @property
    def is_middle_mode(self):
        return self.origin_mode in ("LIMITS_MIDDLE", "MIDDLE")

    @property
    def modifier_is_use_origin_axis(self):
        return self.obj_origin_property_group.origin_mode != "NOT"

    @property
    def modifier_is_have_origin(self):
        return self.modifier_is_use_origin_axis and self.modifier.origin


class GizmoUpdate(PublicProperty):
    @classmethod
    def ensure_object_uuid(cls, obj):
        value = str(obj.get(cls.G_OBJECT_UUID_PROP, ""))
        duplicate = value and any(
            other != obj and str(other.get(cls.G_OBJECT_UUID_PROP, "")) == value
            for other in bpy.data.objects
        )
        if not value or duplicate:
            value = str(uuid.uuid4())
            obj[cls.G_OBJECT_UUID_PROP] = value
        return value

    @classmethod
    def is_managed_origin(cls, origin, owner=None):
        if not origin:
            return False
        try:
            if not bool(origin.get(cls.G_OWNER_PROP, False)):
                return False
            if owner is None:
                return True
            owner_uuid = str(owner.get(cls.G_OBJECT_UUID_PROP, ""))
            origin_owner_uuid = str(origin.get(cls.G_OWNER_UUID_PROP, ""))
            return bool(owner_uuid and owner_uuid == origin_owner_uuid)
        except ReferenceError:
            return False

    def fix_origin_parent_and_angle(self):
        obj = self.obj
        mod = self.modifier
        if not obj or not mod or not getattr(mod, "origin", False):
            return

        origin = mod.origin
        if not self.is_managed_origin(origin, obj):
            return

        if origin.parent != obj:
            world_matrix = origin.matrix_world.copy()
            origin.parent = obj
            origin.matrix_parent_inverse = obj.matrix_world.inverted_safe()
            origin.matrix_world = world_matrix
        origin.rotation_euler.zero()
        if not self.modifier_origin_is_available:
            origin.location.zero()
        origin.scale = 1, 1, 1

    def new_origin_empty_object(self, force_managed=False):
        mod = self.modifier
        obj = self.obj
        if not mod or not obj:
            return None

        origin = mod.origin
        if origin and not self.is_managed_origin(origin, obj):
            # User-supplied origins are read-only. Features that need to move or
            # constrain an origin must not take ownership implicitly.
            return None

        if not origin:
            if not force_managed and not self.modifier_is_use_origin_axis:
                return None
            new_name = self.G_NAME_EMPTY_AXIS + str(uuid.uuid4())
            origin_object = bpy.data.objects.new(new_name, None)
            origin_object[self.G_OWNER_PROP] = True
            origin_object[self.G_OWNER_VERSION_PROP] = self.G_OWNER_VERSION
            origin_object[self.G_OWNER_UUID_PROP] = self.ensure_object_uuid(obj)
            self.link_obj_to_active_collection(origin_object)
            move_object_to_control_collection(origin_object, bpy.context.scene)
            set_helper_object_visible(origin_object, False)
            origin_object.empty_display_size = max(min(obj.dimensions), 0.1)
            mod.origin = origin_object
            origin_mode = self.obj.SimpleDeformGizmo_PropertyGroup.origin_mode
            origin_object.SimpleDeformGizmo_PropertyGroup.origin_mode = origin_mode
        else:
            origin_object = mod.origin
        if origin_object == obj:
            return None

        # add constraints
        name = self.G_NAME_CON_LIMIT
        if name in origin_object.constraints.keys():
            limit_constraints = origin_object.constraints.get(name)
            if limit_constraints.type != "LIMIT_ROTATION":
                origin_object.constraints.remove(limit_constraints)
                limit_constraints = None
        else:
            limit_constraints = None
        if limit_constraints is None:
            limit_constraints = origin_object.constraints.new(
                "LIMIT_ROTATION")
            limit_constraints.name = name
        limit_constraints.owner_space = "WORLD"
        if hasattr(limit_constraints, "space_object"):
            limit_constraints.space_object = obj
        limit_constraints.use_transform_limit = True
        limit_constraints.use_limit_x = True
        limit_constraints.use_limit_y = True
        limit_constraints.use_limit_z = True

        con_copy_name = self.G_NAME_CON_COPY_ROTATION
        if con_copy_name in origin_object.constraints.keys():
            copy_constraints = origin_object.constraints.get(con_copy_name)
            if copy_constraints.type != "COPY_ROTATION":
                origin_object.constraints.remove(copy_constraints)
                copy_constraints = None
        else:
            copy_constraints = None
        if copy_constraints is None:
            copy_constraints = origin_object.constraints.new(
                "COPY_ROTATION")
            copy_constraints.name = con_copy_name
        copy_constraints.target = obj
        copy_constraints.mix_mode = "BEFORE"
        copy_constraints.target_space = "WORLD"
        copy_constraints.owner_space = "WORLD"
        self.fix_origin_parent_and_angle()
        return origin_object

    def update_object_origin_matrix(self):
        if (
                self.modifier_is_have_origin and
                self.modifier_origin_is_available and
                self.is_managed_origin(self.modifier.origin, self.obj)
        ):
            origin_mode = self.origin_mode
            origin_object = self.modifier.origin

            loc = None
            if origin_mode == "UP_LIMITS":
                loc = Vector(self.point_limits_up)
            elif origin_mode == "DOWN_LIMITS":
                loc = Vector(self.point_limits_down)
            elif origin_mode == "LIMITS_MIDDLE":
                loc = (self.point_limits_up + self.point_limits_down) / 2
            elif origin_mode == "MIDDLE":
                loc = (self.point_up + self.point_down) / 2

            # set matrix
            if loc:
                loc_mat = get_loc_matrix(loc)
                rot = get_rot_matrix(self.obj.matrix_world.to_euler())
                scl = get_sca_matrix(self.obj.matrix_world.to_scale())

                curve_offset = from_curve_get_animation_offset(self.obj)
                if curve_offset is not None:
                    mat = loc_mat @ (scl @ rot @ get_loc_matrix(curve_offset).inverted())
                    origin_object.matrix_world = mat
                    return

                origin_object.matrix_world = loc_mat  # @ rot

    def update_multiple_modifiers_data(self):
        obj = self.obj
        context = bpy.context
        if not self.obj_type_is_usable(
                obj) or not self.poll_modifier_type_is_simple(context):
            return False
        self.clear_point_cache()
        self.G_MultipleModifiersBoundData.clear()
        return StageCache.rebuild(context, obj)

    @classmethod
    def _preview_box_geometry(cls, bounds, segments=None):
        segments = max(2, int(segments or cls.G_PREVIEW_SEGMENTS))
        corners = cls.tow_co_to_coordinate(bounds)
        vertices = []
        edges = []
        for start_index, end_index in cls.G_INDICES:
            start = Vector(corners[start_index])
            end = Vector(corners[end_index])
            base = len(vertices)
            for segment in range(segments + 1):
                factor = segment / segments
                vertices.append(start.lerp(end, factor))
                if segment:
                    edges.append((base + segment - 1, base + segment))
        return vertices, edges

    def preview_signature(self):
        mod = self.modifier
        obj = self.obj
        if not mod or not obj:
            return None
        origin = mod.origin
        origin_matrix = None
        if origin:
            origin_matrix = tuple(tuple(row) for row in origin.matrix_world)
        return (
            int(obj.as_pointer()),
            int(mod.as_pointer()),
            tuple(repr(value) for value in self.get_modifiers_parameter(mod)),
            tuple(tuple(row) for row in obj.matrix_world),
            origin_matrix,
        )

    def preview_context_signature(self):
        """Stable identity used to keep the last good preview while throttled."""
        mod = self.modifier
        obj = self.obj
        if not mod or not obj:
            return None
        return int(obj.as_pointer()), int(mod.as_pointer())

    def preview_data_matches_context(self, data):
        return bool(
            data and
            data.get("context_signature") == self.preview_context_signature()
        )

    def update_deform_wireframe(self, force=False):
        if not self.pref.update_deform_wireframe:
            self.clear_deform_data()
            return False
        if render_job_running() or not self.active_modifier_is_simple_deform:
            return False

        now = monotonic()
        preview_fps = max(1, int(getattr(self.pref, "wireframe_preview_fps", 30)))
        preview_interval = 1.0 / preview_fps
        current_data = self.G_DeformDrawData.get("simple_deform_bound_data")
        if not self.preview_data_matches_context(current_data):
            # A newly selected object or modifier must not inherit the previous
            # stage's throttle delay.
            force = True
        if not force and now - PublicData.G_PREVIEW_LAST_UPDATE < preview_interval:
            return False
        PublicData.G_PREVIEW_LAST_UPDATE = now

        context = bpy.context
        collection = getattr(context, "collection", None)
        if collection is None:
            layer_collection = getattr(context.view_layer, "active_layer_collection", None)
            collection = getattr(layer_collection, "collection", None)
        if collection is None:
            return False

        preview_mesh = None
        preview_obj = None
        try:
            vertices, edges = self._preview_box_geometry(self.modifier_bound_co)
            unique = str(uuid.uuid4())
            preview_mesh = bpy.data.meshes.new(f"SDH_PreviewMesh_{unique}")
            preview_mesh.from_pydata(vertices, edges, [])
            preview_mesh.update()
            preview_obj = bpy.data.objects.new(f"SDH_Preview_{unique}", preview_mesh)
            preview_obj[self.G_OWNER_PROP] = True
            preview_obj[self.G_OWNER_VERSION_PROP] = self.G_OWNER_VERSION
            preview_obj.hide_render = True
            preview_obj.hide_select = True
            preview_obj.display_type = "WIRE"
            preview_obj.matrix_world = self.obj_matrix_world
            collection.objects.link(preview_obj)
            hide_runtime_object(preview_obj, getattr(context, "scene", None))

            preview_modifier = preview_obj.modifiers.new(
                self.modifier.name, "SIMPLE_DEFORM")
            self.copy_modifier_parameter(
                self.modifier, preview_modifier, include_vertex_group=False)

            context.view_layer.update()
            evaluated = preview_obj.evaluated_get(context.evaluated_depsgraph_get())
            matrix = preview_obj.matrix_world.copy()
            ver_len = len(evaluated.data.vertices)
            edge_len = len(evaluated.data.edges)
            list_vertices = np.zeros(ver_len * 3, dtype=np.float32)
            list_edges = np.zeros(edge_len * 2, dtype=np.int32)
            evaluated.data.vertices.foreach_get("co", list_vertices)
            evaluated.data.edges.foreach_get("vertices", list_edges)

            ver = list_vertices.reshape((ver_len, 3))
            ver = np.insert(ver, 3, 1, axis=1).T
            ver[:] = np.dot(matrix, ver)
            ver /= ver[3, :]
            positions = ver.T[:, :3]
            indices = list_edges.reshape((edge_len, 2))

            self.G_DeformDrawData["simple_deform_bound_data"] = {
                "positions": positions,
                "indices": indices,
                "signature": self.preview_signature(),
                "context_signature": self.preview_context_signature(),
            }
            self.G_DeformDrawData.pop("preview_error", None)
            return True
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            if self.G_DeformDrawData.get("preview_error") != message:
                print("Simple Deform Helper preview:", message)
                self.G_DeformDrawData["preview_error"] = message
            return False
        finally:
            if preview_obj is not None:
                try:
                    bpy.data.objects.remove(preview_obj, do_unlink=True)
                except (ReferenceError, RuntimeError):
                    pass
            if preview_mesh is not None and preview_mesh.users == 0:
                try:
                    bpy.data.meshes.remove(preview_mesh)
                except (ReferenceError, RuntimeError):
                    pass


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
                if f == "target_set_operator":
                    gizmo.target_set_operator(k[f])
                elif f == "target_set_prop":
                    gizmo.target_set_prop(*k[f])
                else:
                    setattr(gizmo, f, k[f])

    def init_shape(self):
        if not hasattr(self, "custom_shape"):
            self.custom_shape = {}
            from .src.shape import __shape__
            for key, value in __shape__.items():
                self.custom_shape[key] = self.new_custom_shape("TRIS", value)

    def init_setup(self):
        self.init_shape()

    def init_invoke(self, context, event):
        self.init_mouse_region_y = event.mouse_region_y
        self.init_mouse_region_x = event.mouse_region_x

    def __update_matrix_func(self, context):
        func = getattr(self, "update_gizmo_matrix", None)
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
        if getattr(event, "is_repeat", False):
            return {"RUNNING_MODAL"}

        if event.type in ("WHEELUPMOUSE", "WHEELDOWNMOUSE"):
            reverse = (event.type == "WHEELUPMOUSE")
            if self.modifier.origin:
                if not self.is_managed_origin(self.modifier.origin, self.obj):
                    return {"RUNNING_MODAL"}
                path = "object.modifiers.active.origin.SimpleDeformGizmo_PropertyGroup.origin_mode"
            else:
                path = "object.SimpleDeformGizmo_PropertyGroup.origin_mode"
            try:
                bpy.ops.wm.context_cycle_enum(
                    data_path=path, reverse=reverse, wrap=True)
            except RuntimeError:
                pass
        elif event.type in ("X", "Y", "Z") and event.value == "PRESS":
            self.obj.modifiers.active.deform_axis = event.type
        elif (
                event.type == "A" and event.value == "PRESS" and
                "BEND" == self.modifier.deform_method
        ):
            self.pref.display_bend_axis_switch_gizmo = True
            return {"FINISHED"}
        elif event.type == "W" and event.value == "RELEASE":
            self.pref.update_deform_wireframe = \
                self.pref.update_deform_wireframe ^ True
        return {"RUNNING_MODAL"}

    @staticmethod
    def tag_redraw(context):
        if context.area:
            context.area.tag_redraw()

    def get_snap(self, delta, tweak):
        is_snap = "SNAP" in tweak
        is_precise = "PRECISE" in tweak
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
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}


class Tmp:
    @classmethod
    def get_origin_bounds(cls, obj: "bpy.types.Object") -> list:
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
            if axis == "X" and (not self.is_positive(mod.angle)):
                rot.z = math.pi

            elif axis == "Y":
                if self.is_positive(mod.angle):
                    rot.z = -(math.pi / 2)
                else:
                    rot.z = math.pi / 2
            elif axis == "Z":
                if self.is_positive(mod.angle):
                    rot.x = rot.z = rot.y = math.pi / 2
                else:
                    rot.z = rot.y = math.pi / 2
                    rot.x = -(math.pi / 2)

            rot = rot.to_matrix()
            self.matrix_basis = self.matrix_basis @ rot.to_4x4()

    @classmethod
    def bound_box_to_list(cls, obj: "bpy.types.Object"):
        return tuple(i[:] for i in obj.bound_box)

    @classmethod
    def properties_is_modifier(cls) -> bool:
        """Returns whether there is a modifier property panel open in the
        active window.
         If it is open, it returns to True else False
        """
        for area in bpy.context.screen.areas:
            if area.type == "PROPERTIES":
                for space in area.spaces:
                    is_m = space.context == "MODIFIER"
                    if space.type == "PROPERTIES" and is_m:
                        return True
        return False
