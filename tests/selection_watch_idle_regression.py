"""Verify selection synchronization is scheduled only by changed state."""
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy

SOURCE = Path(__file__).resolve().parents[1]
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
RESULT = Path(ARGS[0]).resolve() if ARGS else None
sys.path.insert(0, str(SOURCE.parent))
addon = importlib.import_module(SOURCE.name)
entry = bpy.context.preferences.addons.new()
entry.module = SOURCE.name
addon.register()
core = addon.cage_deform.core


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def drain():
    for _ in range(12):
        if core._selection_watch_timer() is None:
            break
    else:
        raise AssertionError("selection confirmation did not finish")
    if bpy.app.timers.is_registered(core._selection_watch_timer):
        bpy.app.timers.unregister(core._selection_watch_timer)


try:
    bpy.ops.mesh.primitive_cube_add()
    target = bpy.context.object
    _, controller, _ = core.create_deform_stage(bpy.context, target)
    for selected in tuple(bpy.context.selected_objects):
        selected.select_set(False)
    bpy.context.view_layer.objects.active = target
    drain()
    for selected_state in (False, True):
        target.select_set(selected_state)
        # Native selection paths need not publish RNA notifications. The
        # existing depsgraph handler must schedule, not perform, the mutation.
        core._depsgraph_sync(bpy.context.scene, SimpleNamespace(updates=()))
        check(bpy.app.timers.is_registered(core._selection_watch_timer) or
              not selected_state, "selection change did not schedule its timer")
        if selected_state:
            check(not controller.select_get(), "depsgraph callback changed selection")
        drain()
        check(controller.select_get() == selected_state,
              "controller selection did not follow target")
        for _ in range(30):
            core._depsgraph_sync(bpy.context.scene, SimpleNamespace(updates=()))
        check(not bpy.app.timers.is_registered(core._selection_watch_timer),
              "unchanged dependency graph scheduled selection work")
    for _ in range(20):
        core._selection_sync_notify()
    check(bpy.app.timers.is_registered(core._selection_watch_timer),
          "RNA notification did not schedule reconciliation")
    drain()
    message = "PASS::SELECTION_EVENT_IDLE"
    print(message)
    if RESULT is not None:
        RESULT.write_text(message + "\n", encoding="utf-8")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
