from bpy.types import Operator


class KeyFrame(Operator):
    bl_idname = 'simple_deform_gizmo.key_frame'
    bl_label = 'Key Frame'

    def execute(self, context):
        return {"FINISHED"}


class RemoveFrame(Operator):
    bl_idname = 'simple_deform_gizmo.key_remove_frame'
    bl_label = 'Remove Frame'

    def execute(self, context):
        return {"FINISHED"}
