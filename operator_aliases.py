"""Native-keymap names for UI buttons, preserving existing public operators."""

import bpy


_registered_classes = []


def native_operator_idname(identifier):
    namespace, name = identifier.split(".", 1)
    if namespace == "sdh":
        return f"object.sdh_{name}"
    if namespace == "simple_deform_gizmo":
        return f"object.sdh_legacy_{name}"
    return identifier


def _ui_identifiers():
    from .cage_deform import ui
    from .ops import KeyFrame, RemoveFrame, SimpleDeformStageCycle
    from .view_state import SDH_OT_reset_view_display, SDH_OT_toggle_view_display

    return (
        *(value for name, value in vars(ui).items()
          if name.startswith("_OP_") and value.startswith("sdh.")),
        KeyFrame.bl_idname,
        RemoveFrame.bl_idname,
        SimpleDeformStageCycle.bl_idname,
        SDH_OT_toggle_view_display.bl_idname,
        SDH_OT_reset_view_display.bl_idname,
    )


def register():
    if _registered_classes:
        return
    try:
        for identifier in dict.fromkeys(_ui_identifiers()):
            namespace, name = identifier.split(".", 1)
            operator = getattr(getattr(bpy.ops, namespace), name)
            source = bpy.types.Operator.bl_rna_get_subclass_py(
                operator.get_rna_type().identifier)
            # Subclassing a registered Operator replaces its RNA binding.
            # Reuse its implementation on the original unregistered bases.
            attributes = {
                key: value for key, value in vars(source).items()
                if key not in {"bl_rna", "rna_type", "__dict__", "__weakref__"}
            }
            alias_id = native_operator_idname(identifier)
            attributes["bl_idname"] = alias_id
            attributes["bl_options"] = set(source.bl_options) | {"INTERNAL"}
            alias = type(
                "OBJECT_OT_" + alias_id.split(".", 1)[1],
                source.__bases__, attributes)
            bpy.utils.register_class(alias)
            _registered_classes.append(alias)
    except Exception:
        unregister()
        raise


def unregister():
    for alias in reversed(_registered_classes):
        bpy.utils.unregister_class(alias)
    _registered_classes.clear()
