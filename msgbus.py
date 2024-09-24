import bpy

from .utils import PublicData

owner = object()

remember_deform_method = {}


def modify_deform_method():
    obj = bpy.context.object
    ma = obj.modifiers.active
    if ma:
        if ma.name not in remember_deform_method:
            remember_deform_method[ma.name] = ma.deform_method
        else:
            if remember_deform_method[ma.name] != ma.deform_method:
                """Modify deform method , update data"""
                remember_deform_method[ma.name] = ma.deform_method
                origin = ma.origin
                if origin:
                    for index, axis in enumerate(("X", "Y", "Z")):
                        value = origin.simple_deform_helper_rotate_xyz[index]
                        o = origin.constraints[PublicData.G_NAME_CON_LIMIT]
                        setattr(o, f"max_{axis.lower()}", value)
                        setattr(o, f"min_{axis.lower()}", value)


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
