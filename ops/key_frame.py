from bpy.app.translations import pgettext_iface as iface_
from bpy.types import Operator

from ..utils import GizmoUtils, PublicData


group_name = "Simple Deform Helper"


def active_paths(modifier):
    strength = "angle" if modifier.deform_method in {"BEND", "TWIST"} else "factor"
    return strength, "limits"


def managed_origin(modifier):
    origin = modifier.origin
    if GizmoUtils.is_managed_origin(origin, modifier.id_data):
        return origin
    return None


def origin_constraint_paths(origin):
    constraint = origin.constraints.get(PublicData.G_NAME_CON_LIMIT)
    if not constraint:
        return ()
    return tuple(
        (constraint, f"{prefix}_{axis}")
        for axis in "xyz"
        for prefix in ("min", "max")
    )


def _delete_key(owner, data_path):
    try:
        return bool(owner.keyframe_delete(data_path, group=group_name))
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return False


def keyframe_simple_deform(modifier, *, delete=False):
    """Insert or delete the complete managed traditional deformation state."""
    if modifier is None or getattr(modifier, "type", None) != "SIMPLE_DEFORM":
        return 0
    keyframe = _delete_key if delete else (
        lambda owner, data_path: bool(owner.keyframe_insert(
            data_path, group=group_name)))
    changed = 0
    for data_path in active_paths(modifier):
        try:
            changed += int(keyframe(modifier, data_path))
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass

    origin = managed_origin(modifier)
    if origin:
        try:
            changed += int(keyframe(origin, "location"))
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
        for constraint, data_path in origin_constraint_paths(origin):
            try:
                changed += int(keyframe(constraint, data_path))
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                pass
    return changed


class KeyFrame(Operator):
    bl_idname = "simple_deform_gizmo.key_frame"
    bl_label = "Insert Keyframe"
    bl_description = "Key the active strength, limits, and managed Origin controls"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return GizmoUtils.poll_modifier_type_is_simple(context)

    def execute(self, context):
        mod = context.object.modifiers.active
        inserted = keyframe_simple_deform(mod)

        self.report({"INFO"}, iface_(
            "Inserted {inserted} Simple Deform keyframe channels").format(
                inserted=inserted))
        return {"FINISHED"}


class RemoveFrame(Operator):
    bl_idname = "simple_deform_gizmo.key_remove_frame"
    bl_label = "Remove Keyframe"
    bl_description = "Remove the current-frame keys created for the active Simple Deform"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return GizmoUtils.poll_modifier_type_is_simple(context)

    def execute(self, context):
        mod = context.object.modifiers.active
        removed = keyframe_simple_deform(mod, delete=True)

        self.report({"INFO"}, iface_(
            "Removed {removed} Simple Deform keyframe channels").format(
                removed=removed))
        return {"FINISHED"}
