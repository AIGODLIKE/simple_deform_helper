"""Regression checks for opt-in auto fitting in an ordinary cage stack."""
from __future__ import annotations

import importlib
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
INSTALLED_PACKAGE = os.environ.get("SDH_TEST_MODULE")
PACKAGE = INSTALLED_PACKAGE or SOURCE.name
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(SOURCE.parent))

addon = importlib.import_module(PACKAGE)
if not INSTALLED_PACKAGE:
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def controller_state(controller):
    properties = controller.sdh_cage_deform
    return (
        Vector(controller.location),
        Vector(properties.size),
        Vector(controller.rotation_euler),
    )


def state_changed(first, second, tolerance=1.0e-5):
    return any((left - right).length > tolerance
               for left, right in zip(first, second))


def check_frame_change_defers_structural_updates():
    """A new-frame callback must never run clone-based maintenance inline."""
    core = deform.core
    original_chain_drain = core._drain_chain_reconnect_queue
    original_fit_drain = core._drain_stack_auto_fit_queue
    unsafe_calls = []

    def record_chain_drain(*_args, **_kwargs):
        unsafe_calls.append("chain")

    def record_fit_drain(*_args, **_kwargs):
        unsafe_calls.append("fit")

    core._drain_chain_reconnect_queue = record_chain_drain
    core._drain_stack_auto_fit_queue = record_fit_drain
    try:
        core._frame_change_sync(bpy.context.scene)
    finally:
        core._drain_chain_reconnect_queue = original_chain_drain
        core._drain_stack_auto_fit_queue = original_fit_drain
    check(not unsafe_calls,
          f"frame-change handler ran structural maintenance: {unsafe_calls!r}")


def main():
    check_frame_change_defers_structural_updates()
    vertices = []
    faces = []
    for row in range(9):
        y = -2.0 + row * 0.5
        vertices.extend(((-0.5, y, -0.25), (0.5, y, 0.25)))
        if row:
            base = row * 2
            faces.append((base - 2, base, base + 1, base - 1))
    mesh = bpy.data.meshes.new("SDH Stack Auto Sync Mesh")
    mesh.from_pydata(vertices, (), faces)
    target = bpy.data.objects.new("SDH Stack Auto Sync", mesh)
    bpy.context.collection.objects.link(target)
    bpy.context.view_layer.objects.active = target
    target.select_set(True)

    try:
        first, first_controller, _previous = deform.create_deform_stage(
            bpy.context, target, name="Auto Sync Upstream")
        second, second_controller, _previous = deform.create_deform_stage(
            bpy.context, target, name="Auto Sync Downstream",
            after_modifier=first)
        first_properties = first_controller.sdh_cage_deform
        second_properties = second_controller.sdh_cage_deform
        first_properties.alignment = "POS_Y"
        second_properties.alignment = "POS_Y"

        runtime_clone = target.copy()
        runtime_clone[deform.core.RUNTIME_EVALUATOR] = True
        bpy.context.collection.objects.link(runtime_clone)
        try:
            check(not deform.core.request_stack_auto_fit(runtime_clone),
                  "runtime evaluator clone entered the Auto Sync queue")
        finally:
            bpy.data.objects.remove(runtime_clone, do_unlink=True)
        second_properties.auto_sync_upstream = True
        deform.core._drain_stack_auto_fit_queue(bpy.context)
        before = controller_state(second_controller)

        first_properties.bend_strength = math.radians(80.0)
        deform.sync_controller(first_controller, pull_transform=False)
        bpy.context.view_layer.update()
        check(deform.core.request_stack_auto_fit(first_controller, first),
              "upstream edit did not queue the ordinary downstream cage")
        check(deform.core._drain_stack_auto_fit_queue(bpy.context) == 1,
              "ordinary downstream cage was not fitted exactly once")
        check(not deform.core._STACK_AUTO_FIT_QUEUE,
              "ordinary Auto Sync requeued itself while measuring bounds: "
              f"{deform.core._STACK_AUTO_FIT_QUEUE!r}")
        after = controller_state(second_controller)
        check(state_changed(before, after),
              "ordinary Auto Sync did not respond to upstream deformation")

        second_properties.auto_sync_upstream = False
        disabled_state = controller_state(second_controller)
        first_properties.bend_strength = math.radians(20.0)
        deform.sync_controller(first_controller, pull_transform=False)
        bpy.context.view_layer.update()
        deform.core._drain_stack_auto_fit_queue(bpy.context)
        check(not state_changed(disabled_state, controller_state(second_controller)),
              "disabled ordinary Auto Sync still changed the cage frame")

        # Match the reported crash sequence: key the downstream cage, enable
        # Auto Sync, key it again, then evaluate animated upstream deformation
        # across multiple frames.  The frame handler only queues the clone-
        # based fit; the timer drains it after Blender finishes the new frame.
        scene = bpy.context.scene
        scene.frame_set(1)
        deform.core._activate(bpy.context, second_controller)
        check(bpy.ops.sdh.insert_cage_keyframes() == {"FINISHED"},
              "first downstream key insertion failed")
        second_properties.auto_sync_upstream = True
        deform.core._drain_stack_auto_fit_queue(bpy.context)
        check(bpy.ops.sdh.insert_cage_keyframes() == {"FINISHED"},
              "second downstream key insertion failed")

        first_properties.bend_strength = math.radians(10.0)
        first_controller.keyframe_insert(
            data_path="sdh_cage_deform.bend_strength", frame=1)
        first_properties.bend_strength = math.radians(85.0)
        first_controller.keyframe_insert(
            data_path="sdh_cage_deform.bend_strength", frame=12)

        animated_states = []
        for frame in (1, 4, 8, 12, 4, 12):
            scene.frame_set(frame)
            deform.core._chain_reconnect_timer()
            bpy.context.view_layer.update()
            animated_states.append(controller_state(second_controller))
        deform.core._chain_reconnect_timer()
        check(not deform.core._STACK_AUTO_FIT_QUEUE,
              "animated Auto Sync left a self-generated queue request")
        check(state_changed(animated_states[0], animated_states[3]),
              "deferred Auto Sync did not follow animated upstream geometry")
        print("SDH_STACK_AUTO_SYNC::PASS")
    finally:
        if not INSTALLED_PACKAGE:
            try:
                addon.unregister()
            except Exception:
                pass


try:
    main()
except Exception:
    import traceback
    traceback.print_exc()
    raise
finally:
    if not INSTALLED_PACKAGE:
        try:
            bpy.context.preferences.addons.remove(entry)
        except Exception:
            pass
