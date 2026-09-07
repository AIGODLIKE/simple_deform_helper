"""Check selection reconciliation for two windows with different view layers."""
import importlib
import sys
import time
import traceback
from pathlib import Path

import bpy

SOURCE = Path(__file__).resolve().parents[1]
RESULT = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
sys.path.insert(0, str(SOURCE.parent))
addon = importlib.import_module(SOURCE.name)
entry = bpy.context.preferences.addons.new()
entry.module = SOURCE.name
addon.register()
core = addon.cage_deform.core
bpy.ops.mesh.primitive_cube_add()
target = bpy.context.object
_modifier, controller, _previous = core.create_deform_stage(bpy.context, target)
first = bpy.context.window
first.view_layer.name = "Selection First"
second_layer = bpy.context.scene.view_layers.new("Selection Second")
bpy.ops.wm.window_new_main()
second = next(window for window in bpy.context.window_manager.windows if window != first)
second.view_layer = second_layer
assert first.view_layer != second.view_layer, "test windows need separate workspace view layers"
windows = (first, second)
state = {"phase": "start", "round": 0, "deadline": 0.0}
calls = []
original_watch = core._selection_watch_timer


def measured_watch():
    calls.append(time.monotonic())
    return original_watch()


core._selection_watch_timer = measured_watch


def finish(message):
    RESULT.write_text(message + "\n", encoding="utf-8")
    bpy.ops.wm.quit_blender()
    return None


def step():
    try:
        expected = (state["round"] == 0, state["round"] != 0)
        if state["phase"] == "start":
            for window, selected in zip(windows, expected):
                with bpy.context.temp_override(window=window):
                    for obj in bpy.context.view_layer.objects:
                        obj.select_set(False)
                    target.select_set(selected)
                    window.view_layer.objects.active = target
                    core._selection_redraw_notify()
            state["deadline"] = time.monotonic() + 3.0
            state["phase"] = "settle"
            return 0.5
        matches = all(
            target.select_get(view_layer=window.view_layer) == selected and
            controller.select_get(view_layer=window.view_layer) == selected
            for window, selected in zip(windows, expected))
        ready = matches and not bpy.app.timers.is_registered(core._selection_watch_timer)
        if state["phase"] == "settle" and not ready and time.monotonic() < state["deadline"]:
            return 0.1
        assert ready, ("window selection did not settle", state,
                       [(window.view_layer.name, target.select_get(view_layer=window.view_layer),
                         controller.select_get(view_layer=window.view_layer),
                         controller.hide_get(view_layer=window.view_layer)) for window in windows],
                       len(calls), core._SELECTION_PENDING_WINDOWS,
                       core._SELECTION_WINDOW_SIGNATURES)
        if state["phase"] == "settle":
            assert len(core._SELECTION_WINDOW_SIGNATURES) == 2
            for _ in range(20):
                for window in windows:
                    with bpy.context.temp_override(window=window):
                        core._selection_redraw_notify()
            assert not bpy.app.timers.is_registered(core._selection_watch_timer)
            state["idle_calls"] = len(calls)
            state["phase"] = "idle"
            return 1.0
        assert len(calls) == state["idle_calls"], "stable windows scheduled work"
        if state["round"] == 0:
            state["round"] = 1
            state["phase"] = "start"
            return 0.1
        addon.unregister()
        assert not core._SELECTION_DRAW_HANDLERS
        assert not core._SELECTION_WINDOW_SIGNATURES
        assert not core._SELECTION_PENDING_WINDOWS
        return finish("PASS::SELECTION_MULTIWINDOW::two_view_layers::idle_zero::unregister")
    except Exception:
        return finish("FAIL\n" + traceback.format_exc())


bpy.app.timers.register(step, first_interval=1.0)
