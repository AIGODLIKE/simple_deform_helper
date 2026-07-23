import bpy
from bpy.types import Panel

from ..ops import KeyFrame, RemoveFrame
from ..ops.stage import SimpleDeformStageCycle, AddSimpleDeformTopology
from ..stages import StageCache
from ..utils import PublicPoll, GizmoUtils, get_pref


class Info:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tool"


class SimpleDeformPanel(Panel, Info):
    bl_idname = "SIMPLE_DEFORM_PT_PANEL"
    bl_label = "Simple Deform Helper"

    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tool"
    bl_options = set()

    @classmethod
    def poll(cls, context):
        return PublicPoll.poll_simple_deform_public(context)

    def draw(self, context):
        ...

    def draw_header(self, context):
        layout = self.layout
        layout.prop(get_pref(), "show_gizmo", text="")


class SimpleDeformPropertyPanel(Panel, Info):
    bl_idname = "SIMPLE_DEFORM_PROPERTY_PT_PANEL"
    bl_label = "Property"

    bl_parent_id = SimpleDeformPanel.bl_idname

    # bl_options = {"HIDE_HEADER"}

    def draw(self, context):
        layout = self.layout
        layout.scale_y = 1.2
        column = layout.column(align=True)

        pref = get_pref()

        obj = context.object
        mod = obj.modifiers.active
        prop = obj.SimpleDeformGizmo_PropertyGroup

        ctrl_obj = mod.origin.SimpleDeformGizmo_PropertyGroup if mod.origin else prop

        stage_index, stage_count = StageCache.position_for(obj, mod)
        stage_row = column.row(align=True)
        if stage_count > 1:
            previous = stage_row.operator(
                SimpleDeformStageCycle.bl_idname,
                text="", icon="TRIA_LEFT")
            previous.direction = "PREVIOUS"
        stage_row.label(
            text=f"Stage {stage_index or 1} of {stage_count or 1}: {mod.name}",
            icon="MOD_SIMPLEDEFORM")
        if stage_count > 1:
            following = stage_row.operator(
                SimpleDeformStageCycle.bl_idname,
                text="", icon="TRIA_RIGHT")
            following.direction = "NEXT"

        if stage_count > 1:
            stage_list = column.box().column(align=True)
            stage_list.label(text="Simple Deform Stack", icon="MODIFIER")
            for index, stage_modifier in enumerate(
                    item for item in obj.modifiers
                    if item.type == "SIMPLE_DEFORM"):
                stage_button = stage_list.operator(
                    SimpleDeformStageCycle.bl_idname,
                    text=f"{index + 1}. {stage_modifier.name}",
                    icon=(
                        "RADIOBUT_ON" if stage_modifier == mod
                        else "RADIOBUT_OFF"
                    ),
                )
                stage_button.index = index

        if pref.warn_low_topology:
            sample_count = GizmoUtils.topology_axis_sample_count(
                obj, mod.deform_axis)
            stack_index = tuple(obj.modifiers).index(mod)
            has_subdivision = any(
                previous.show_viewport and previous.type in {"SUBSURF", "MULTIRES", "REMESH"}
                for previous in tuple(obj.modifiers)[:stack_index]
            )
            if sample_count < 4 and not has_subdivision:
                warning = column.box()
                warning.alert = True
                warning.label(
                    text=f"Low topology on {mod.deform_axis}: {sample_count} levels",
                    icon="ERROR")
                warning.label(text="Simple Deform needs more segments to bend smoothly.")
                if obj.type == "MESH":
                    warning.operator(
                        AddSimpleDeformTopology.bl_idname,
                        icon="MOD_SUBSURF")

        origin_control = column.column()
        origin_control.enabled = (
            not mod.origin or
            GizmoUtils.is_managed_origin(mod.origin, obj)
        )
        origin_control.prop(ctrl_obj,
                            "origin_mode",
                            text="")
        if mod.origin and not GizmoUtils.is_managed_origin(mod.origin, obj):
            protected = column.box()
            protected.label(text="User Origin is protected", icon="LOCKED")
            protected.label(text="Follow-limit Origin modes are disabled.")
        column.prop(pref,
                    "update_deform_wireframe",
                    icon="MOD_WIREFRAME", )
        column.prop(pref,
                    "show_set_axis_button",
                    icon="EMPTY_AXIS", )
        column.prop(pref,
                    "show_wireframe_in_front",
                    icon="AXIS_FRONT", )
        column.prop(pref,
                    "show_other_stage_bounds",
                    icon="MOD_SIMPLEDEFORM", )
        if pref.modifier_deform_method_is_bend:
            column.prop(pref,
                        "display_bend_axis_switch_gizmo",
                        toggle=1)
        column.prop(pref,
                    "modifiers_limits_tolerance",
                    text="")
        if pref.update_deform_wireframe:
            column.prop(pref, "wireframe_preview_fps")


class SimpleDeformAnimatedPanel(Panel, Info):
    bl_idname = "SIMPLE_DEFORM_ANIMATED_PT_PANEL"
    bl_label = "Animated"

    bl_parent_id = SimpleDeformPanel.bl_idname

    def draw(self, context):
        layout = self.layout
        layout.scale_y = 1.2
        row = layout.row(align=True)
        row.operator(KeyFrame.bl_idname)
        row.operator(RemoveFrame.bl_idname)


def gizmo_panel(self, context):
    layout = self.layout
    layout.prop(get_pref(), "show_gizmo", text="Show Simple Deform Gizmo")


classes = [
    SimpleDeformPanel,
    SimpleDeformPropertyPanel,
    SimpleDeformAnimatedPanel
]
reg_class, un_reg_class = bpy.utils.register_classes_factory(classes)


def register():
    reg_class()
    bpy.types.VIEW3D_PT_gizmo_display.prepend(gizmo_panel)


def unregister():
    bpy.types.VIEW3D_PT_gizmo_display.remove(gizmo_panel)
    un_reg_class()
