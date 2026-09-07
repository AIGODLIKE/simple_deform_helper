"""Measure event-guard cost; selection timers have no periodic idle tick."""
import importlib
import json
import statistics
import sys
import time
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
records = []

try:
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=17, y_subdivisions=17)
    target = bpy.context.object
    bpy.ops.sdh.add_cage_chain(count=8, connection_mode="CHAINED", gap=0.0)
    bpy.context.view_layer.objects.active = target
    for selected_state in (False, True):
        for selected in tuple(bpy.context.selected_objects):
            selected.select_set(False)
        target.select_set(selected_state)
        core._selection_sync_notify()
        for _ in range(12):
            if core._selection_watch_timer() is None:
                break
        else:
            raise AssertionError("selection confirmation did not finish")
        if bpy.app.timers.is_registered(core._selection_watch_timer):
            bpy.app.timers.unregister(core._selection_watch_timer)
        graph = SimpleNamespace(updates=())
        for event, callback in (
                ("depsgraph", lambda: core._depsgraph_sync(bpy.context.scene, graph)),
                ("redraw", core._selection_redraw_notify)):
            samples = []
            for _ in range(120):
                started = time.perf_counter()
                callback()
                samples.append((time.perf_counter() - started) * 1000)
            assert not bpy.app.timers.is_registered(core._selection_watch_timer)
            records.append({
                "event": event, "selected": selected_state, "samples": len(samples),
                "unchanged_event_ms_median": statistics.median(samples),
                "unchanged_event_ms_p95": sorted(samples)[114],
                "selection_timer_scheduled": False,
            })
    payload = {"blender": bpy.app.version_string, "chain_stages": 8,
               "periodic_selection_timer": False, "records": records}
    print("SDH_SELECTION_EVENT_BENCHMARK::" + json.dumps(payload))
    if RESULT is not None:
        RESULT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
