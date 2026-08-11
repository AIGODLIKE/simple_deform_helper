"""Regression for stale FFD/Curve edit flags and coalesced selection events."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE.parent))
PACKAGE = SOURCE.name


def check(condition, message):
    if not condition:
        raise AssertionError(message)


addon = importlib.import_module(PACKAGE)
entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon.register()
cage = importlib.import_module(f"{PACKAGE}.cage_deform")
core = cage.core


def select_none(active=None):
    for obj in tuple(bpy.context.selected_objects):
        obj.select_set(False)
    if active is not None:
        bpy.context.view_layer.objects.active = active


def main():
    bpy.ops.mesh.primitive_cube_add()
    target = bpy.context.object
    ffd_modifier, ffd_controller, _ = cage.create_deform_stage(
        bpy.context, target, cage_type="FFD")
    curve_modifier, curve_controller, _ = cage.create_deform_stage(
        bpy.context, target, cage_type="CURVE")

    # Simulate a cancelled modal that left its persistent flag behind.
    ffd_controller.sdh_cage_deform.ffd_edit_mode_active = True
    select_none(target)
    check(
        core._desired_cage_workspace_type(bpy.context) == "",
        "stale FFD flag kept the dedicated tool desired with empty selection",
    )
    core._selection_sync_timer()
    check(not target.select_get(), "empty selection resurrected the target")
    check(
        core._active_workspace_tool_id(bpy.context) not in {
            core._FFD_WORKSPACE_TOOL_ID,
            core._CURVE_WORKSPACE_TOOL_ID,
        },
        "empty selection left a cage Workspace Tool active",
    )

    curve_controller.sdh_cage_deform.curve_object_edit_active = True
    select_none(target)
    check(
        core._desired_cage_workspace_type(bpy.context) == "",
        "stale Curve flag kept the dedicated tool desired with empty selection",
    )
    core._selection_sync_timer()
    check(not target.select_get(), "Curve stale flag resurrected the target")

    # Force a notify while preserving the final RNA signature. The dirty bit
    # must still cause one reconciliation pass.
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    target.modifiers.active = ffd_modifier
    core._selection_sync_timer()
    core._selection_sync_notify()
    calls = []
    original = core._reconcile_cage_workspace_tool

    def wrapped(context, desired=None, *, force=False):
        calls.append(desired)
        return original(context, desired, force=force)

    core._reconcile_cage_workspace_tool = wrapped
    try:
        core._selection_sync_timer()
    finally:
        core._reconcile_cage_workspace_tool = original
    check(calls, "coalesced selection notify skipped reconciliation")

    print("SDH_WORKSPACE_STALE_STATE::PASS")


try:
    main()
finally:
    try:
        addon.unregister()
    except Exception:
        pass
