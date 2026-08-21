import bpy
from bpy.props import (FloatProperty,
                       FloatVectorProperty,
                       EnumProperty,
                       BoolProperty,
                       IntProperty)
from bpy.types import AddonPreferences

from .utils import GizmoUtils


_PREFERENCES_REGISTERED = False
# Compatibility state used by lifecycle diagnostics and partial-register
# rollback. The compact traditional controls are attached to the 3D header.
_HEADER_ATTACHED = False


def update_wireframe_preview(preferences, context):
    helper = GizmoUtils()
    if preferences.update_deform_wireframe:
        helper.update_multiple_modifiers_data()
        helper.update_deform_wireframe(force=True)
    else:
        helper.clear_deform_data()
    if context and context.area:
        context.area.tag_redraw()


def update_merge_final_state_preview(preferences, context):
    """Apply preview preference changes without importing the cage package early."""
    try:
        from .cage_deform import merge
        merge.sync_final_preview_preference(
            context, bool(preferences.show_merge_final_state_preview))
    except (AttributeError, ImportError, KeyError, ReferenceError, RuntimeError,
            TypeError):
        return
    try:
        if context and context.area:
            context.area.tag_redraw()
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass


def update_ffd_controller_display(_preferences, _context):
    """Refresh every viewport when an FFD handle display preference changes."""
    try:
        windows = bpy.context.window_manager.windows
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return
    for window in windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


class SimpleDeformGizmoAddonPreferences(AddonPreferences, GizmoUtils):
    bl_idname = __package__

    deform_wireframe_color: FloatVectorProperty(
        name="Deform Wireframe",
        description="Draw Deform Wireframe Color",
        default=(1, 1, 1, 0.3),
        soft_max=1,
        soft_min=0,
        size=4, subtype="COLOR")
    bound_box_color: FloatVectorProperty(
        name="Bound Box",
        description="Draw Bound Box Color",
        default=(1, 0, 0, 0.5),
        soft_max=1,
        soft_min=0,
        size=4,
        subtype="COLOR")
    limits_bound_box_color: FloatVectorProperty(
        name="Upper and lower limit Bound Box Color",
        description="Draw Upper and lower limit Bound Box Color",
        default=(0.3, 1, 0.2, 0.5),
        soft_max=1,
        soft_min=0,
        size=4,
        subtype="COLOR")
    modifiers_limits_tolerance: FloatProperty(
        name="Upper and lower limit tolerance",
        description="Minimum value between upper and lower limits",
        default=0.05,
        max=1,
        min=0.0001
    )
    display_bend_axis_switch_gizmo: BoolProperty(
        name="Show Toggle Bend Axis Gizmo",
        default=False,
        options={"SKIP_SAVE"})

    update_deform_wireframe: BoolProperty(
        name="Show Deform Wireframe",
        # Keep the global preference opt-in.  The legacy add operator enables
        # it for that newly-created modifier and performs one immediate build;
        # enabling it for every scene made ordinary viewport redraws costly.
        default=False,
        update=update_wireframe_preview)

    show_wireframe_in_front: BoolProperty(name="In Front", default=True)

    show_set_axis_button: BoolProperty(
        name="Show Set Axis Button",
        description="Show X, Y, and Z buttons beside the deformation bounds",
        default=False)

    show_gizmo_property_location: EnumProperty(
        name="Gizmo Property Show Location",
        items=[("ToolSettings", "Tool Settings", ""),
               ("ToolOptions", "Tool Options", ""),
               ],
        default="ToolSettings"
    )

    show_gizmo: BoolProperty(name="Show Gizmo", default=True)

    professional_mode: BoolProperty(
        name="Professional Mode",
        description=(
            "Show advanced Deform Axis, Independent Ends, and Numeric Controls"
        ),
        default=False,
    )

    append_cage_stage_to_end: BoolProperty(
        name="Add New Cages to End",
        description="Place newly-created cage stages at the end of the modifier stack",
        default=True,
    )

    default_cage_auto_sync: BoolProperty(
        name="Default Cage Auto Sync",
        description=(
            "Automatically fit newly-created non-chain cages when an earlier "
            "cage changes"
        ),
        default=False,
    )

    ffd_keyframe_scope: EnumProperty(
        name="FFD Keyframe Scope",
        description=(
            "Choose whether FFD I/Alt-I keys affect every visible point or "
            "only the selected points"
        ),
        items=(
            (
                "ALL_VISIBLE",
                "All Visible Points",
                "Key every visible FFD point; hidden hollow points are excluded",
            ),
            (
                "SELECTED",
                "Selected Points",
                "Key only the selected FFD points",
            ),
        ),
        default="ALL_VISIBLE",
    )

    ffd_line_handle_length: FloatProperty(
        name="FFD Line Length",
        description=(
            "Visible FFD line-controller length as a percentage of its control line"
        ),
        default=0.60,
        min=0.10,
        max=1.0,
        subtype="PERCENTAGE",
        update=update_ffd_controller_display,
    )

    ffd_line_handle_width: FloatProperty(
        name="FFD Line Width",
        description="Consistent viewport width for every FFD line controller",
        default=2.0,
        min=1.0,
        max=8.0,
        update=update_ffd_controller_display,
    )

    ffd_face_handle_size: FloatProperty(
        name="FFD Face Size",
        description=(
            "Visible FFD face-controller size as a percentage of its grid face"
        ),
        default=0.35,
        min=0.10,
        max=1.0,
        subtype="PERCENTAGE",
        update=update_ffd_controller_display,
    )

    show_ffd_handles: BoolProperty(
        name="Show FFD Handles",
        description="Show editable FFD control-point, line, and face handles",
        default=True,
        update=update_ffd_controller_display,
    )

    show_merge_final_state_preview: BoolProperty(
        name="Show Final Merged State While Editing Sources",
        description=(
            "Display the selected source after the merged object's full modifier stack"
        ),
        default=True,
        update=update_merge_final_state_preview,
    )

    show_other_stage_bounds: BoolProperty(
        name="Show Other Simple Deform Stages",
        description="Draw faint input bounds for other Simple Deform modifiers",
        default=True)

    show_drag_hud: BoolProperty(
        name="Show Drag Shortcuts in Header",
        default=True)

    warn_low_topology: BoolProperty(
        name="Warn About Low Topology",
        description="Warn when the active deformation axis has too few geometry points",
        default=True)

    wireframe_preview_fps: IntProperty(
        name="Wireframe Preview FPS",
        description="Maximum refresh rate for the optional deformed wireframe preview",
        default=30,
        min=5,
        max=60)

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "show_gizmo")
        col.prop(self, "professional_mode")
        col.prop(self, "append_cage_stage_to_end")
        col.prop(self, "default_cage_auto_sync")
        col.prop(self, "ffd_keyframe_scope")
        ffd_box = col.box()
        ffd_box.label(text="FFD Controller Display", icon="MOD_LATTICE")
        ffd_box.prop(self, "show_ffd_handles")
        ffd_box.prop(self, "ffd_line_handle_length")
        ffd_box.prop(self, "ffd_line_handle_width")
        ffd_box.prop(self, "ffd_face_handle_size")
        col.prop(self, "show_merge_final_state_preview")
        col.prop(self, "show_other_stage_bounds")
        col.prop(self, "show_drag_hud")
        col.prop(self, "warn_low_topology")
        col.prop(self, "wireframe_preview_fps")

        box = col.box()
        box.label(text="Shortcut Cheat Sheet", icon="EVENT_OS")
        cage = box.column(align=True)
        cage.label(text="Cage handles (drag):")
        cage.label(text="    Shift: precise   Ctrl: snap angle/value")
        cage.label(text="    Boundary drag - Ctrl: move both ends, Alt: opposite ends")
        cage.label(text="    Shear handle - Alt: X only, Shift: Z only, Ctrl: snap")
        ffd = box.column(align=True)
        ffd.label(text="FFD edit:")
        ffd.label(text="    Box select points; drag any selected point moves the group")
        ffd.label(text="    I / Alt+I: insert or delete point keys (scope preference above)")
        ffd.label(text="    Tab: leave Native Lattice Edit and sync back")
        legacy = box.column(align=True)
        legacy.label(text="Traditional Simple Deform (drag):")
        legacy.label(text="    Wheel: switch Origin mode    X/Y/Z: deform axis")
        legacy.label(text="    W: toggle deform wireframe   A: bend axis chooser")

        col.prop(self, "deform_wireframe_color")
        col.prop(self, "bound_box_color")
        col.prop(self, "limits_bound_box_color")


    def draw_header_tool_settings(self, context):
        if not GizmoUtils.poll_simple_deform_public(context):
            return
        row = self.layout.row()
        obj = context.object
        modifier = obj.modifiers.active

        row.separator(factor=0.2)
        row.prop(modifier, "deform_method", expand=True)
        row.prop(modifier, "deform_axis", expand=True)

        value_row = row.row(align=True)
        strength = (
            "angle" if modifier.deform_method in {"BEND", "TWIST"}
            else "factor")
        value_row.prop(modifier, strength)

        from .gizmo.z_rotate import ZRotateGizmoGroup
        if ZRotateGizmoGroup.poll(context):
            value_row.prop(
                modifier.origin,
                "simple_deform_helper_rotate_angle",
                text="Z Rotate",
            )


def register():
    global _PREFERENCES_REGISTERED, _HEADER_ATTACHED
    if _PREFERENCES_REGISTERED:
        return
    bpy.utils.register_class(SimpleDeformGizmoAddonPreferences)
    _PREFERENCES_REGISTERED = True
    try:
        bpy.types.VIEW3D_MT_editor_menus.append(
            SimpleDeformGizmoAddonPreferences.draw_header_tool_settings)
        _HEADER_ATTACHED = True
    except Exception:
        try:
            bpy.utils.unregister_class(SimpleDeformGizmoAddonPreferences)
        finally:
            _PREFERENCES_REGISTERED = False
        raise


def unregister():
    global _PREFERENCES_REGISTERED, _HEADER_ATTACHED
    if _HEADER_ATTACHED:
        try:
            bpy.types.VIEW3D_MT_editor_menus.remove(
                SimpleDeformGizmoAddonPreferences.draw_header_tool_settings)
        except (RuntimeError, ValueError):
            pass
        finally:
            _HEADER_ATTACHED = False
    if _PREFERENCES_REGISTERED:
        try:
            bpy.utils.unregister_class(SimpleDeformGizmoAddonPreferences)
        except (RuntimeError, ValueError):
            pass
        finally:
            _PREFERENCES_REGISTERED = False
