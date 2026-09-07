import bpy
from bpy.app.handlers import persistent

from .utils import GizmoUtils, PublicData

owner = object()
_registered = False

remember_deform_method = {}


def _refresh_managed_origin(*, update_rotation=False):
    obj = bpy.context.object
    if not obj:
        return
    ma = obj.modifiers.active
    if not ma or ma.type != "SIMPLE_DEFORM":
        return

    origin = ma.origin
    if not GizmoUtils.is_managed_origin(origin, obj):
        return
    if update_rotation:
        constraint = origin.constraints.get(PublicData.G_NAME_CON_LIMIT)
        if constraint:
            for index, axis in enumerate(("X", "Y", "Z")):
                value = origin.simple_deform_helper_rotate_xyz[index]
                setattr(constraint, f"max_{axis.lower()}", value)
                setattr(constraint, f"min_{axis.lower()}", value)
    helper = GizmoUtils()
    helper.clear_point_cache()
    helper.update_object_origin_matrix()


def modify_deform_method():
    obj = bpy.context.object
    ma = getattr(getattr(obj, "modifiers", None), "active", None)
    if ma is None or ma.type != "SIMPLE_DEFORM":
        return
    key = (int(obj.as_pointer()), int(ma.as_pointer()))
    previous = remember_deform_method.get(key)
    remember_deform_method[key] = ma.deform_method
    _refresh_managed_origin(
        update_rotation=previous is not None and previous != ma.deform_method)


def modify_deform_frame():
    _refresh_managed_origin()


def _subscribe():
    bpy.msgbus.clear_by_owner(owner)
    for property_name, callback in (
            ("deform_method", modify_deform_method),
            ("deform_axis", modify_deform_frame),
            ("limits", modify_deform_frame)):
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.SimpleDeformModifier, property_name),
            owner=owner,
            args=(),
            notify=callback,
        )


@persistent
def _load_post(_unused):
    if not _registered:
        return
    remember_deform_method.clear()
    _subscribe()


def register():
    global _registered
    try:
        _subscribe()
        if _load_post not in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.append(_load_post)
        _registered = True
    except Exception:
        unregister()
        raise


def unregister():
    global _registered
    _registered = False
    while _load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post)
    bpy.msgbus.clear_by_owner(owner)
    remember_deform_method.clear()
