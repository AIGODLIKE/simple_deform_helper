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
        inserted = 0
        for data_path in active_paths(mod):
            if mod.keyframe_insert(data_path, group=group_name):
                inserted += 1

        origin = managed_origin(mod)
        if origin:
            if origin.keyframe_insert("location", group=group_name):
                inserted += 1
            for constraint, data_path in origin_constraint_paths(origin):
                if constraint.keyframe_insert(data_path, group=group_name):
                    inserted += 1

        self.report({"INFO"}, f"Inserted {inserted} Simple Deform keyframe channels")
        return {"FINISHED"}


class RemoveFrame(Operator):
    bl_idname = "simple_deform_gizmo.key_remove_frame"
    bl_label = "Remove Keyframe"
    bl_description = "Remove the current-frame keys created for the active Simple Deform"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return GizmoUtils.poll_modifier_type_is_simple(context)

    @staticmethod
    def delete_key(owner, data_path):
        try:
            return bool(owner.keyframe_delete(data_path, group=group_name))
        except (RuntimeError, TypeError):
            return False

    def execute(self, context):
        mod = context.object.modifiers.active
        removed = sum(
            self.delete_key(mod, data_path)
            for data_path in active_paths(mod)
        )

        origin = managed_origin(mod)
        if origin:
            removed += self.delete_key(origin, "location")
            removed += sum(
                self.delete_key(constraint, data_path)
                for constraint, data_path in origin_constraint_paths(origin)
            )

        self.report({"INFO"}, f"Removed {removed} Simple Deform keyframe channels")
        return {"FINISHED"}
