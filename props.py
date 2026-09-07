import math

import bpy
from bpy.props import PointerProperty, StringProperty, FloatProperty, EnumProperty, FloatVectorProperty
from bpy.types import PropertyGroup

from .utils import PublicData, GizmoUtils, remove_unused_control_collections


_class_registered = False
_registered_object_properties = []


def _managed_origin_target(origin):
    if not GizmoUtils.is_managed_origin(origin):
        return None

    def owns_origin(candidate):
        return (
            candidate is not None and
            GizmoUtils.is_managed_origin(origin, candidate) and
            any(modifier.type == "SIMPLE_DEFORM" and modifier.origin == origin
                for modifier in candidate.modifiers)
        )

    parent = origin.parent
    if owns_origin(parent):
        return parent
    # Lattice Origins are unparented to avoid a dependency cycle. Duplicated
    # UUIDs must not let a detached helper choose an unrelated target.
    targets = tuple(candidate for candidate in bpy.data.objects
                    if owns_origin(candidate))
    return targets[0] if len(targets) == 1 else None


class SimpleDeformGizmoObjectPropertyGroup(PropertyGroup, GizmoUtils):
    def _limits_up(self, context):
        if self.active_modifier_is_simple_deform:
            self.modifier.limits[1] = self.up_limits

    up_limits: FloatProperty(name="up",
                             description="UP Limits(Red)",
                             default=1,
                             update=_limits_up,
                             max=1,
                             min=0)

    def _limits_down(self, context):
        if self.active_modifier_is_simple_deform:
            self.modifier.limits[0] = self.down_limits

    down_limits: FloatProperty(name="down",
                               description="Lower limit(Green)",
                               default=0,
                               update=_limits_down,
                               max=1,
                               min=0)

    origin_mode_items = (
        ("UP_LIMITS",
         "Follow Upper Limit(Red)",
         "Create a managed Origin and keep it at the upper limit while dragging"),
        ("DOWN_LIMITS",
         "Follow Lower Limit(Green)",
         "Create a managed Origin and keep it at the lower limit while dragging"),
        ("LIMITS_MIDDLE",
         "Middle",
         "Create a managed Origin between the upper and lower limits"),
        ("MIDDLE",
         "Bound Middle",
         "Create a managed Origin at the deformation bounds center"),
        ("NOT", "No origin operation", ""),
    )

    def update_origin_mode(self, context):
        obj = getattr(self, "id_data", None)
        if not isinstance(obj, bpy.types.Object):
            return
        if self.origin_mode != "NOT":
            if self.is_managed_origin(obj):
                target = _managed_origin_target(obj)
                modifier = next(
                    (
                        candidate for candidate in getattr(target, "modifiers", ())
                        if getattr(candidate, "origin", None) == obj
                    ),
                    None,
                )
            else:
                target = obj
                modifier = getattr(
                    getattr(target, "modifiers", None), "active", None)
            if (
                    target != getattr(context, "object", None) or
                    modifier is None or modifier.type != "SIMPLE_DEFORM"
            ):
                return
            helper = GizmoUtils()
            if getattr(modifier, "origin", None) is None:
                managed = helper.new_origin_empty_object(force_managed=True)
                if managed is None:
                    return
                managed.SimpleDeformGizmo_PropertyGroup.origin_mode = (
                    self.origin_mode)
            helper.clear_point_cache()
            helper.update_object_origin_matrix()
            return
        target = _managed_origin_target(obj)
        if target is None:
            return

        modifiers = tuple(
            modifier for modifier in target.modifiers
            if modifier.type == "SIMPLE_DEFORM" and modifier.origin == obj)
        # Keep shared helpers attached: detaching the owner would let the
        # orphan cleanup remove an object still referenced elsewhere.
        shared_origin = any(
            getattr(modifier, "origin", None) == obj
            for candidate in bpy.data.objects if candidate != target
            for modifier in candidate.modifiers)
        if shared_origin or obj.users > len(obj.users_collection) + len(modifiers):
            return
        for modifier in modifiers:
            modifier.origin = self.source_origin
        target.SimpleDeformGizmo_PropertyGroup.origin_mode = "NOT"
        bpy.data.objects.remove(obj, do_unlink=True)
        remove_unused_control_collections()

    origin_mode: EnumProperty(
        name="Origin control mode",
        default="NOT",
        items=origin_mode_items,
        update=update_origin_mode
    )

    source_origin: PointerProperty(
        name="Original Origin",
        type=bpy.types.Object,
        options={"HIDDEN", "SKIP_SAVE"},
    )


def __get_rotate__(self):
    name = PublicData.G_NAME_CON_LIMIT
    if name not in self.constraints:
        return -111
    con = self.constraints[name]
    axis = self.simple_deform_helper_rotate_axis
    return getattr(con, f"min_{axis.lower()}", -999)


def __set_rotate__(self, value):
    name = PublicData.G_NAME_CON_LIMIT
    if name not in self.constraints:
        return
    con = self.constraints[name]
    axis = self.simple_deform_helper_rotate_axis
    value = value % (math.pi * 2)
    setattr(con, f"max_{axis.lower()}", value)
    setattr(con, f"min_{axis.lower()}", value)


def _register_object_property(name, value):
    if hasattr(bpy.types.Object, name):
        raise RuntimeError(f"Object property already registered: {name}")
    setattr(bpy.types.Object, name, value)
    _registered_object_properties.append(name)


def _cleanup_registration():
    global _class_registered
    for name in reversed(tuple(_registered_object_properties)):
        try:
            delattr(bpy.types.Object, name)
        except (AttributeError, RuntimeError):
            pass
    _registered_object_properties.clear()
    if _class_registered:
        try:
            bpy.utils.unregister_class(SimpleDeformGizmoObjectPropertyGroup)
        except (RuntimeError, ValueError):
            pass
        finally:
            _class_registered = False


def register():
    global _class_registered
    if _class_registered or _registered_object_properties:
        return
    try:
        bpy.utils.register_class(SimpleDeformGizmoObjectPropertyGroup)
        _class_registered = True
        _register_object_property(
            "SimpleDeformGizmo_PropertyGroup",
            PointerProperty(
                type=SimpleDeformGizmoObjectPropertyGroup,
                name="SimpleDeformGizmo_PropertyGroup"))
        _register_object_property(
            "simple_deform_helper_rotate_xyz",
            FloatVectorProperty(step=3, default=(0, 0, 0)))
        _register_object_property(
            "simple_deform_helper_rotate_angle",
            FloatProperty(
                name="Origin Object Rotate Angle",
                default=0,
                get=__get_rotate__,
                set=__set_rotate__,
                subtype="ANGLE"))
        _register_object_property(
            "simple_deform_helper_rotate_axis",
            StringProperty(
                name="Origin Object Rotate Axis",
                default="Z"))
    except Exception:
        _cleanup_registration()
        raise


def unregister():
    _cleanup_registration()
