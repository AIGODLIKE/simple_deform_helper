"""Cage Deform package: Geometry Nodes cage deformation for Simple Deform Helper."""
from __future__ import annotations

import bpy

# ``core`` must initialize before ``animation_io`` (core re-exports its
# names mid-file), so keep it ahead of the extracted feature modules here.
from . import (
    chain,
    core,
    animation_io,  # noqa: F401 — imported for registration completeness
    curve,
    curve_presets,
    ffd_native_edit,
    gizmos,
    merge,
    stack_presets,
    stage_apply,
    stage_mirror,
    ui,
)
from .core import (  # noqa: F401 — public API for draw.py / siblings
    CONTROLLER_MARKER,
    CONTROLLER_STYLES,
    CONTROLLER_UUID,
    GROUP_MARKER,
    GROUP_VERSION,
    MODIFIER_MARKER,
    MODIFIER_UUID,
    RUNTIME_EVALUATOR,
    TARGET_UUID,
    active_deform_types,
    cage_axis_sample_count,
    cage_boundary_points_local,
    cage_input_axis_limits,
    cage_local_matrix,
    cage_modifier_uuid,
    cage_modifiers,
    create_deform_stage,
    curve_effect_range,
    deform_point_for_display,
    deform_point_local,
    deform_point_from_properties,
    deform_stack_modifiers,
    evaluator_end_scales,
    find_controller,
    find_target,
    ffd_expand_selection,
    ffd_selection_anchor_indices,
    ffd_selection_indices,
    ffd_selection_modes,
    ffd_proportional_weight,
    ffd_symmetry_axes,
    is_cage_controller,
    is_cage_modifier,
    migrate_legacy_stages,
    modifier_input,
    move_cage_boundary,
    move_curve_effect_boundary,
    resolve_context_deform,
    sync_controller,
    upgrade_managed_stages,
)
from .gizmos import (  # noqa: F401 — compatibility API for tests and scripts
    AXIS_VECTORS,
    BEND_TREND_BASES,
    CONTROLLER_STYLES as GIZMO_CONTROLLER_STYLES,
    SDHCageBoundaryGizmo,
    SDHCageEndShapeGizmo,
    bend_trend_handle_matrix,
    bend_trend_reference_bounds,
)

classes = (
    *merge.classes,
    core.SDHFFDPoint,
    curve.SDHCurvePoint,
    curve.SDHCurveStation,
    core.SDHCageControllerProperties,
    *curve.classes[1:],
    *curve_presets.classes,
    core.SDH_OT_add_cage_deform,
    core.SDH_OT_add_legacy_simple_deform,
    core.SDH_OT_add_cage_topology,
    core.SDH_OT_add_deform_layer,
    core.SDH_OT_select_deform_layer,
    core.SDH_OT_expand_all_deform_layers,
    core.SDH_OT_remove_deform_layer,
    core.SDH_OT_toggle_deform_layer_mute,
    core.SDH_OT_move_deform_layer,
    core.SDH_OT_fit_cage_deform,
    core.SDH_OT_reset_cage_ends,
    core.SDH_OT_select_ffd_points,
    core.SDH_OT_set_ffd_selection_mode,
    core.SDH_OT_set_ffd_symmetry_axes,
    core.SDH_OT_box_select_ffd_points,
    ffd_native_edit.SDH_OT_edit_ffd_native,
    core.SDH_OT_reset_ffd,
    core.SDH_OT_insert_cage_keyframes,
    core.SDH_OT_delete_cage_keyframes,
    core.SDH_OT_bake_cage_animation,
    core.SDH_OT_select_cage_stage,
    core.SDH_OT_select_cage_controller,
    core.SDH_OT_select_cage_target,
    core.SDH_OT_cage_transform,
    core.SDH_OT_set_cage_axis,
    core.SDH_OT_set_bend_trend,
    core.SDH_OT_duplicate_cage_deform,
    core.SDH_OT_move_cage_deform,
    core.SDH_OT_remove_cage_deform,
    core.SDH_OT_remove_cage_stack,
    chain.SDH_OT_add_cage_chain,
    chain.SDH_OT_subdivide_cage_to_chain,
    chain.SDH_OT_batch_edit_cage_chain,
    chain.SDH_OT_reconnect_cage_chain,
    *stage_apply.classes,
    *stage_mirror.classes,
    *stack_presets.classes,
    gizmos.SDHCageBendStrengthGizmo,
    gizmos.SDHCageTwistStrengthGizmo,
    gizmos.SDHCageTaperFactorGizmo,
    gizmos.SDHCageStretchFactorGizmo,
    gizmos.SDHCageShearGizmo,
    gizmos.SDHCageFFDCornerGizmo,
    gizmos.SDHCageFFDAggregateGizmo,
    gizmos.SDHCageDirectionGizmo,
    gizmos.SDHCageBendTrendGizmo,
    gizmos.SDHCageAxisGizmo,
    gizmos.SDHCageEndShapeGizmo,
    gizmos.SDHCageBoundaryGizmo,
    gizmos.SDHCageStagePickerGizmo,
    gizmos.SDHCageDeformGizmoGroup,
    gizmos.SDHCageStagePickerGizmoGroup,
    ui.SDH_MT_add_standard_cage_type,
    ui.SDH_MT_add_standard_chain_type,
    ui.SDH_CAGE_PT_deform,
)

_registered_classes = []
_pointer_registered = False


def _cleanup_registration(*, remove_runtime=True):
    """Best-effort cleanup shared by unregister and failed registration."""
    global _pointer_registered
    gizmos._GIZMO_UNDO_ACTIVE.clear()
    gizmos.clear_throttled_redraw()
    merge.unregister_runtime()
    curve.finish_curve_edit_sessions(bpy.context, restore_target=False)
    ffd_native_edit.finish_native_edit_sessions(
        bpy.context, restore_target=False)
    curve.remove_curve_draw_handlers()
    curve.clear_curve_relation_sync()
    core.unregister_ffd_workspace_tool()
    core.restore_controller_relationship_lines()
    core.unregister_runtime_discovery_handler()
    core.disable_runtime_handlers()
    core.clear_chain_reconnect_state()
    core.remove_ffd_draw_handlers()
    if _pointer_registered or hasattr(bpy.types.Object, "sdh_cage_deform"):
        try:
            del bpy.types.Object.sdh_cage_deform
        except (AttributeError, RuntimeError):
            pass
        _pointer_registered = False
    for item in reversed(tuple(_registered_classes)):
        try:
            bpy.utils.unregister_class(item)
        except (RuntimeError, ValueError):
            pass
    _registered_classes.clear()
    if not remove_runtime:
        return
    try:
        runtime_objects = tuple(bpy.data.objects)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        runtime_objects = ()
    for obj in runtime_objects:
        try:
            if obj.get(core.RUNTIME_EVALUATOR, False):
                bpy.data.objects.remove(obj, do_unlink=True)
        except (ReferenceError, RuntimeError):
            pass


def register():
    global _pointer_registered
    if _registered_classes:
        return
    core._LEGACY_MIGRATION_PENDING = True
    try:
        for item in classes:
            bpy.utils.register_class(item)
            _registered_classes.append(item)
        bpy.types.Object.sdh_cage_deform = bpy.props.PointerProperty(
            type=core.SDHCageControllerProperties)
        _pointer_registered = True
        core.register_runtime_discovery_handler()
        core.register_ffd_workspace_tool()
        merge.register_runtime()
        # Blender 5.x restricts data access while an extension is registering.
        # Discover cages from a one-shot callback after registration returns.
        core.schedule_runtime_bootstrap()
    except Exception:
        _cleanup_registration(remove_runtime=False)
        raise


def unregister():
    _cleanup_registration(remove_runtime=True)
