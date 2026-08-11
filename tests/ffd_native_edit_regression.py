"""Regression coverage for controlled Blender Lattice Edit Mode."""
from __future__ import annotations

import importlib
import os
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))

entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")

mesh = bpy.data.meshes.new("SDH Native FFD Mesh")
mesh.from_pydata(((-1, -1, -1), (1, -1, -1), (1, 1, 1), (-1, 1, 1)), (), ())
target = bpy.data.objects.new("SDH Native FFD", mesh)
bpy.context.collection.objects.link(target)
target.select_set(True)
bpy.context.view_layer.objects.active = target

success = False
try:
    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, target, cage_type="FFD")
    properties = controller.sdh_cage_deform
    properties.ffd_resolution_u = 3
    properties.ffd_resolution_v = 4
    properties.ffd_resolution_w = 2
    deform.core.ensure_ffd_point_collection(properties)
    properties.ffd_points[0].selected = True
    properties.ffd_points[0].influence = 0.5
    properties.ffd_points[0].offset = (0.2, 0.0, 0.0)
    deform.sync_controller(controller, pull_transform=False)
    bpy.context.view_layer.objects.active = target
    target.modifiers.active = modifier

    result = bpy.ops.sdh.edit_ffd_native()
    if result != {"FINISHED"}:
        raise AssertionError(f"native FFD edit did not start: {result}")
    runtime = deform.core.ffd_lattice_object(target, modifier)
    lattice = deform.ffd_native_edit.native_edit_lattice(controller)
    if lattice is None or lattice.mode != "EDIT":
        raise AssertionError("native FFD did not enter Lattice Edit Mode")
    if lattice.hide_get() or lattice.hide_select:
        raise AssertionError("native FFD lattice remained hidden or unselectable")
    if bpy.context.view_layer.objects.active != lattice:
        raise AssertionError("native FFD lattice was not the active object")
    if runtime is None or not runtime.hide_get() or not runtime.hide_select:
        raise AssertionError("weighted FFD runtime lattice became user-editable")
    if any(
            candidate.type == "LATTICE" and candidate.object == lattice
            for candidate in target.modifiers
    ):
        raise AssertionError("authored FFD edit proxy was attached as a modifier")
    if not properties.ffd_native_edit_mode_active:
        raise AssertionError("native FFD edit flag was not set")
    resolved = deform.core.resolve_context_deform(bpy.context)
    if resolved != (target, modifier, controller):
        raise AssertionError("native FFD helper context did not resolve its cage")
    result = bpy.ops.transform.translate(
        value=(0.25, -0.1, 0.2), orient_type="LOCAL")
    if result != {"FINISHED"}:
        raise AssertionError(f"native Lattice transform failed: {result}")
    point = lattice.data.points[0]
    runtime_scale = Vector(tuple(
        max(abs(float(value)), deform.core.EPSILON)
        for value in lattice.matrix_world.to_scale()))
    desired_raw = Vector(tuple(
        float(component) * float(scale)
        for component, scale in zip(
            Vector(point.co_deform) -
            deform.ffd_native_edit._native_base_coordinate(lattice, 0),
            runtime_scale,
        )
    ))
    deform.ffd_native_edit._pull(controller, lattice)
    if (Vector(properties.ffd_points[0].offset) - desired_raw).length > 1.0e-5:
        raise AssertionError("native FFD edit did not pull authored point data")
    bpy.ops.object.mode_set(mode="OBJECT")
    runtime_point = runtime.data.points[0]
    observed_effective = Vector(tuple(
        float(component) * float(scale)
        for component, scale in zip(
            Vector(runtime_point.co_deform) - Vector(runtime_point.co),
            runtime_scale,
        )
    ))
    if (observed_effective - desired_raw * 0.5).length > 1.0e-5:
        raise AssertionError("native FFD runtime ignored point weight")
    proxy_name = lattice.name
    proxy_data_name = lattice.data.name
    deform.ffd_native_edit._watch_sessions()
    if properties.ffd_native_edit_mode_active:
        raise AssertionError("direct native-mode exit left the session active")
    if proxy_name in bpy.data.objects:
        raise AssertionError("native FFD edit proxy survived session exit")
    if proxy_data_name in bpy.data.lattices:
        raise AssertionError("native FFD edit proxy data survived session exit")
    if not runtime.hide_get() or not runtime.hide_select:
        raise AssertionError("native FFD runtime helper did not stay hidden")
    if bpy.context.view_layer.objects.active != target:
        raise AssertionError("native FFD exit did not restore the target")

    properties.ffd_points[0].influence = 0.0
    deform.sync_controller(controller, pull_transform=False)
    zero_start = Vector(properties.ffd_points[0].offset)
    bpy.context.view_layer.objects.active = target
    target.select_set(True)
    target.modifiers.active = modifier
    if bpy.ops.sdh.edit_ffd_native() != {"FINISHED"}:
        raise AssertionError("zero-weight native FFD edit did not start")
    zero_proxy = deform.ffd_native_edit.native_edit_lattice(controller)
    if zero_proxy is None or zero_proxy.mode != "EDIT":
        raise AssertionError("zero-weight native FFD edit proxy is unavailable")
    zero_proxy_name = zero_proxy.name
    zero_proxy_data_name = zero_proxy.data.name
    if bpy.ops.transform.translate(
            value=(0.1, 0.0, 0.0), orient_type="LOCAL") != {"FINISHED"}:
        raise AssertionError("zero-weight native Lattice transform failed")
    bpy.ops.object.mode_set(mode="OBJECT")
    deform.ffd_native_edit._pull(controller, zero_proxy)
    if (Vector(properties.ffd_points[0].offset) - zero_start).length <= 1.0e-5:
        raise AssertionError("zero-weight native FFD point could not be authored")
    runtime_point = runtime.data.points[0]
    if (Vector(runtime_point.co_deform) - Vector(runtime_point.co)).length > 1.0e-6:
        raise AssertionError("zero-weight native FFD point affected the runtime")
    deform.ffd_native_edit._watch_sessions()
    if properties.ffd_native_edit_mode_active:
        raise AssertionError("zero-weight native FFD session did not finalize")
    if (
            zero_proxy_name in bpy.data.objects or
            zero_proxy_data_name in bpy.data.lattices
    ):
        raise AssertionError("zero-weight native FFD proxy was not cleaned up")

    stale_data = bpy.data.lattices.new("SDH Stale Native Edit Data")
    stale_proxy = bpy.data.objects.new("SDH Stale Native Edit", stale_data)
    bpy.context.collection.objects.link(stale_proxy)
    stale_proxy.parent = target
    stale_proxy[deform.core.FFD_NATIVE_EDIT_PROXY_MARKER] = True
    stale_proxy[deform.core.FFD_LATTICE_MODIFIER_MARKER] = (
        deform.core.cage_modifier_uuid(modifier))
    stale_name = stale_proxy.name
    stale_data_name = stale_data.name
    deform.core.cleanup_orphan_deform_helpers()
    if stale_name in bpy.data.objects or stale_data_name in bpy.data.lattices:
        raise AssertionError("stale native FFD edit proxy survived bootstrap cleanup")

    properties.mode = "UNLIMITED"
    bpy.context.view_layer.objects.active = target
    target.select_set(True)
    target.modifiers.active = modifier
    if bpy.ops.sdh.edit_ffd_native() != {"CANCELLED"}:
        raise AssertionError("Unlimited FFD unexpectedly entered native edit")
    print("PASS::FFD_NATIVE_EDIT")
    success = True
except Exception:
    traceback.print_exc()
finally:
    deform.ffd_native_edit.finish_native_edit_sessions(
        bpy.context, restore_target=False)
    addon.unregister()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if success else 1)
