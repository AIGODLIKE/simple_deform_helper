"""Exercise animated ordinary-stack Auto Sync in Blender's event loop."""
from __future__ import annotations

import importlib
import math
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
SCRIPT_ARGS = sys.argv[sys.argv.index("--") + 1:]
RESULT = Path(SCRIPT_ARGS[0]).resolve()
sys.path.insert(0, str(SOURCE.parent))


def finish(message):
    RESULT.write_text(message, encoding="utf-8")
    bpy.ops.wm.quit_blender()
    return None


try:
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon = importlib.import_module(PACKAGE)
    addon.register()
    deform = importlib.import_module(f"{PACKAGE}.cage_deform")

    vertices = []
    faces = []
    for row in range(9):
        y = -2.0 + row * 0.5
        vertices.extend(((-0.5, y, -0.25), (0.5, y, 0.25)))
        if row:
            base = row * 2
            faces.append((base - 2, base, base + 1, base - 1))
    mesh = bpy.data.meshes.new("SDH Auto Sync UI Mesh")
    mesh.from_pydata(vertices, (), faces)
    target = bpy.data.objects.new("SDH Auto Sync UI", mesh)
    bpy.context.collection.objects.link(target)
    bpy.context.view_layer.objects.active = target
    target.select_set(True)

    first, first_controller, _previous = deform.create_deform_stage(
        bpy.context, target, name="Animated Upstream")
    second, second_controller, _previous = deform.create_deform_stage(
        bpy.context, target, name="Animated Downstream", after_modifier=first)
    first_properties = first_controller.sdh_cage_deform
    second_properties = second_controller.sdh_cage_deform
    first_properties.alignment = "POS_Y"
    second_properties.alignment = "POS_Y"

    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 12
    scene.frame_set(1)
    deform.core._activate(bpy.context, second_controller)
    if bpy.ops.sdh.insert_cage_keyframes() != {"FINISHED"}:
        raise RuntimeError("first cage key insertion failed")
    second_properties.auto_sync_upstream = True
    if bpy.ops.sdh.insert_cage_keyframes() != {"FINISHED"}:
        raise RuntimeError("second cage key insertion failed")

    first_properties.bend_strength = math.radians(10.0)
    first_controller.keyframe_insert(
        data_path="sdh_cage_deform.bend_strength", frame=1)
    first_properties.bend_strength = math.radians(85.0)
    first_controller.keyframe_insert(
        data_path="sdh_cage_deform.bend_strength", frame=12)

    original_fit = deform.core.fit_controller_to_bounds
    state = {"index": 0, "settle": 0, "fits": 0}
    frames = tuple(range(1, 13)) + tuple(range(12, 0, -1))

    def tracked_fit(*args, **kwargs):
        result = original_fit(*args, **kwargs)
        if result is not None:
            state["fits"] += 1
        return result

    deform.core.fit_controller_to_bounds = tracked_fit

    def advance_frames():
        try:
            if state["index"] < len(frames):
                scene.frame_set(frames[state["index"]])
                state["index"] += 1
                return 0.02
            if state["settle"] < 3:
                state["settle"] += 1
                return 0.05
            if deform.core._STACK_AUTO_FIT_QUEUE:
                raise RuntimeError(
                    "Auto Sync queue did not settle: "
                    f"{deform.core._STACK_AUTO_FIT_QUEUE!r}; "
                    f"fits={state['fits']}")
            if state["fits"] < 2:
                raise RuntimeError(
                    f"Auto Sync ran only {state['fits']} evaluated fits")
            before = (
                second_controller.location.copy(),
                Vector(second_properties.size),
                Vector(second_controller.rotation_euler),
            )
            deform.core.fit_controller(
                bpy.context, target, second, second_controller)
            after = (
                second_controller.location.copy(),
                Vector(second_properties.size),
                Vector(second_controller.rotation_euler),
            )
            if any((left - right).length > 1.0e-4
                   for left, right in zip(before, after)):
                raise RuntimeError("deferred Auto Sync left a stale final frame")
            return finish(f"PASS fits={state['fits']}")
        except Exception:
            return finish("FAIL:\n" + traceback.format_exc())

    bpy.app.timers.register(advance_frames, first_interval=0.1)
except Exception:
    finish("FAIL:\n" + traceback.format_exc())
