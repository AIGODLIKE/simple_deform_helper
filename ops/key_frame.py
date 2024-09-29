from bpy.types import Operator

group_name = "Simple Deform Gizmo"


class KeyFrame(Operator):
    bl_idname = 'simple_deform_gizmo.key_frame'
    bl_label = 'Insert Keyframe'

    def execute(self, context):
        mod = context.object.modifiers.active
        origin = mod.origin
        for prop in mod.bl_rna.properties:
            if prop.is_animatable:
                mod.keyframe_insert(prop.identifier, group=group_name)

        if origin and "ViewSimpleDeformGizmo__Empty_" in origin.name:
            origin.keyframe_insert("location", group=group_name)
            for con in origin.constraints:
                for prop in con.bl_rna.properties:
                    if prop.is_animatable:
                        con.keyframe_insert(prop.identifier, group=group_name)
        return {"FINISHED"}


class RemoveFrame(Operator):
    bl_idname = 'simple_deform_gizmo.key_remove_frame'
    bl_label = 'Remove Keyframe'

    def execute(self, context):
        mod = context.object.modifiers.active
        origin = mod.origin
        for prop in mod.bl_rna.properties:
            if prop.is_animatable:
                try:
                    mod.keyframe_delete(prop.identifier, group=group_name)
                except Exception:
                    pass

        if origin and "ViewSimpleDeformGizmo__Empty_" in origin.name:
            try:
                origin.keyframe_delete("location", group=group_name)
            except Exception:
                pass
            for con in origin.constraints:
                for prop in con.bl_rna.properties:
                    if prop.is_animatable:
                        try:
                            con.keyframe_delete(prop.identifier, group=group_name)
                        except Exception:
                            pass
        return {"FINISHED"}
