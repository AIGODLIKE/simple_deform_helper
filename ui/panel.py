import bpy
from bpy.app.translations import pgettext_iface as iface_
from bpy.types import Panel

from ..ops import KeyFrame, RemoveFrame
from ..ops.stage import SimpleDeformStageCycle
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
        pref = get_pref()
        if pref is not None:
            layout.prop(pref, "show_gizmo", text="")


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
        if pref is None:
            return

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
            text=iface_("Stage {stage_index} of {stage_count}: {modifier}").format(
                stage_index=stage_index or 1,
                stage_count=stage_count or 1,
                modifier=mod.name,
            ),
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
                    text=iface_("Low topology on {axis}: {sample_count} levels").format(
                        axis=mod.deform_axis,
                        sample_count=sample_count,
                    ),
                    icon="ERROR")
                warning.label(text="Simple Deform needs more segments to bend smoothly.")

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
    pref = get_pref()
    if pref is None:
        return
    layout = self.layout
    layout.prop(pref, "show_gizmo", text="Show Simple Deform Gizmo")


classes = [
    SimpleDeformPanel,
    SimpleDeformPropertyPanel,
    SimpleDeformAnimatedPanel
]
_registered_classes = []
_gizmo_panel_attached = False


def _cleanup_registration():
    global _gizmo_panel_attached
    if _gizmo_panel_attached:
        try:
            bpy.types.VIEW3D_PT_gizmo_display.remove(gizmo_panel)
        except (RuntimeError, ValueError):
            pass
        finally:
            _gizmo_panel_attached = False
    for item in reversed(tuple(_registered_classes)):
        try:
            bpy.utils.unregister_class(item)
        except (RuntimeError, ValueError):
            pass
    _registered_classes.clear()


def register():
    global _gizmo_panel_attached
    if _registered_classes or _gizmo_panel_attached:
        return
    try:
        for item in classes:
            bpy.utils.register_class(item)
            _registered_classes.append(item)
        bpy.types.VIEW3D_PT_gizmo_display.prepend(gizmo_panel)
        _gizmo_panel_attached = True
    except Exception:
        _cleanup_registration()
        raise


def unregister():
    _cleanup_registration()
