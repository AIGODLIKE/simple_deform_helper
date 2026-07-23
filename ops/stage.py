import bpy
from bpy.props import EnumProperty, IntProperty
from bpy.types import Operator

from ..stages import StageCache


def simple_deform_modifiers(obj):
    return tuple(modifier for modifier in obj.modifiers if modifier.type == "SIMPLE_DEFORM")


class SimpleDeformStageCycle(Operator):
    bl_idname = "simple_deform_gizmo.stage_cycle"
    bl_label = "Switch Simple Deform Stage"
    bl_description = "Make the previous or next Simple Deform modifier active"
    bl_options = {"REGISTER"}

    direction: EnumProperty(
        items=(
            ("PREVIOUS", "Previous", "Select the previous Simple Deform modifier"),
            ("NEXT", "Next", "Select the next Simple Deform modifier"),
        ),
        options={"SKIP_SAVE"},
    )
    index: IntProperty(
        name="Stage Index",
        default=-1,
        min=-1,
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(obj and len(simple_deform_modifiers(obj)) > 1)

    def execute(self, context):
        obj = context.object
        modifiers = simple_deform_modifiers(obj)
        active = obj.modifiers.active
        if 0 <= self.index < len(modifiers):
            target_index = self.index
        else:
            try:
                active_index = modifiers.index(active)
            except ValueError:
                active_index = 0
            offset = -1 if self.direction == "PREVIOUS" else 1
            target_index = (active_index + offset) % len(modifiers)
        obj.modifiers.active = modifiers[target_index]
        StageCache.rebuild(context, obj)
        for area in context.screen.areas if context.screen else ():
            if area.type == "VIEW_3D":
                area.tag_redraw()
        return {"FINISHED"}


class AddSimpleDeformTopology(Operator):
    bl_idname = "simple_deform_gizmo.add_topology"
    bl_label = "Add Subdivision Before Deform"
    bl_description = "Add a non-destructive subdivision modifier before the active Simple Deform"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        active = obj.modifiers.active if obj else None
        return bool(obj and obj.type == "MESH" and active and active.type == "SIMPLE_DEFORM")

    def execute(self, context):
        obj = context.object
        active = obj.modifiers.active
        target_index = tuple(obj.modifiers).index(active)
        subdivision = obj.modifiers.new("Simple Deform Topology", "SUBSURF")
        subdivision.subdivision_type = "SIMPLE"
        subdivision.levels = 2
        subdivision.render_levels = 2
        try:
            bpy.ops.object.modifier_move_to_index(
                modifier=subdivision.name,
                index=target_index,
            )
        except RuntimeError:
            self.report(
                {"WARNING"},
                "Subdivision was added at the end; move it before Simple Deform",
            )
        obj.modifiers.active = active
        StageCache.rebuild(context, obj)
        return {"FINISHED"}


classes = (
    SimpleDeformStageCycle,
    AddSimpleDeformTopology,
)
