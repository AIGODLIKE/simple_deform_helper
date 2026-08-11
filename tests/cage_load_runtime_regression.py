"""Cold-load regression for animated cages opened after an empty startup."""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
INSTALLED_PACKAGE = os.environ.get("SDH_TEST_MODULE")
PACKAGE = INSTALLED_PACKAGE or SOURCE.name
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(SOURCE.parent))


def check(condition, message):
    if not condition:
        raise AssertionError(message)


addon = importlib.import_module(PACKAGE)
entry = None
if not INSTALLED_PACKAGE:
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon.register()
core = importlib.import_module(f"{PACKAGE}.cage_deform.core")

temporary_path = None
try:
    # Registration happens against the empty startup scene. The permanent
    # discovery hook must remain even though no expensive handlers are needed.
    core._runtime_bootstrap_timer()
    check(not core._RUNTIME_HANDLERS_REGISTERED,
          "empty startup unexpectedly enabled cage runtime handlers")
    check(core._runtime_load_discovery in bpy.app.handlers.load_post,
          "empty startup did not retain cage load discovery")

    bpy.ops.mesh.primitive_cube_add()
    target = bpy.context.object
    target.name = "Cold Load Animated Target"
    modifier, controller, _previous = core.create_deform_stage(
        bpy.context, target, cage_type="STANDARD")
    properties = controller.sdh_cage_deform

    bpy.context.scene.frame_set(1)
    properties.bend_strength = -0.75
    properties.keyframe_insert(data_path="bend_strength", frame=1)
    bpy.context.scene.frame_set(20)
    properties.bend_strength = 0.85
    properties.keyframe_insert(data_path="bend_strength", frame=20)
    core.sync_controller(controller, pull_transform=False)
    controller_name = controller.name

    handle, temporary_path = tempfile.mkstemp(
        prefix="sdh_cold_load_", suffix=".blend")
    os.close(handle)
    bpy.ops.wm.save_as_mainfile(filepath=temporary_path)

    # Reproduce startup with no active cage callbacks, then open the saved
    # file. Only the permanent discovery handler is allowed to recover it.
    core.disable_runtime_handlers()
    check(core._runtime_load_discovery in bpy.app.handlers.load_post,
          "disabling heavy handlers also removed load discovery")
    bpy.ops.wm.open_mainfile(filepath=temporary_path)
    check(bpy.app.timers.is_registered(core._runtime_bootstrap_timer),
          "opening the cage file did not schedule runtime discovery")
    core._runtime_bootstrap_timer()

    controller = bpy.data.objects.get(controller_name)
    check(controller is not None, "animated controller was not restored")
    target = core.find_target(controller)
    modifier = core.find_modifier(target, controller)
    check(target is not None and modifier is not None,
          "cold-loaded cage ownership was not restored")
    check(core._RUNTIME_HANDLERS_REGISTERED,
          "cold-loaded cage did not enable runtime handlers")
    check(core._frame_change_sync in bpy.app.handlers.frame_change_post,
          "cold-loaded cage did not restore frame synchronization")

    values = []
    for frame in (1, 20):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        properties = controller.sdh_cage_deform
        authored = float(properties.bend_strength)
        socket = float(core.modifier_input(modifier, "Bend Angle"))
        check(abs(authored - socket) < 1.0e-6,
              f"frame {frame} cage value did not reach the modifier")
        values.append(socket)
    check(abs(values[0] - values[1]) > 0.5,
          "cold-loaded animated modifier remained frozen")

    print("SDH_CAGE_LOAD_RUNTIME::PASS")
finally:
    if not INSTALLED_PACKAGE:
        addon.unregister()
        bpy.context.preferences.addons.remove(entry)
    if temporary_path:
        try:
            Path(temporary_path).unlink(missing_ok=True)
        except OSError:
            pass
