import bpy

from .utils import GizmoUtils, PublicData

owner = object()

remember_deform_method = {}


def modify_deform_method():
    obj = bpy.context.object
    if not obj:
        return
    ma = obj.modifiers.active
    if not ma or ma.type != "SIMPLE_DEFORM":
        return

    key = (int(obj.as_pointer()), int(ma.as_pointer()))
    previous = remember_deform_method.get(key)
    remember_deform_method[key] = ma.deform_method
    if previous is None or previous == ma.deform_method:
        return

    origin = ma.origin
    if not GizmoUtils.is_managed_origin(origin, obj):
        return
    constraint = origin.constraints.get(PublicData.G_NAME_CON_LIMIT)
    if not constraint:
        return
    for index, axis in enumerate(("X", "Y", "Z")):
        value = origin.simple_deform_helper_rotate_xyz[index]
        setattr(constraint, f"max_{axis.lower()}", value)
        setattr(constraint, f"min_{axis.lower()}", value)


def register():
    bpy.msgbus.subscribe_rna(
        key=(bpy.types.SimpleDeformModifier, "deform_method"),
        owner=owner,
        args=(),
        notify=modify_deform_method,
    )

def unregister():
    bpy.msgbus.clear_by_owner(owner)
    remember_deform_method.clear()
