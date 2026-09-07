"""Exercise native selection events and verify no selection timer stays idle."""
import importlib
import json
import sys
import time
import traceback
from pathlib import Path

import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d

SOURCE = Path(__file__).resolve().parents[1]
RESULT = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
sys.path.insert(0, str(SOURCE.parent))
addon = importlib.import_module(SOURCE.name)
entry = bpy.context.preferences.addons.new()
entry.module = SOURCE.name
addon.register()
core = addon.cage_deform.core
window = bpy.context.window_manager.windows[0]
area = next(item for item in window.screen.areas if item.type == "VIEW_3D")
region = next(item for item in area.regions if item.type == "WINDOW")
outliner = next(item for item in window.screen.areas if item.type == "OUTLINER")
outliner_region = next(item for item in outliner.regions if item.type == "WINDOW")
records = []
calls = []
original_watch = core._selection_watch_timer


def measured_watch():
    started = time.perf_counter()
    result = original_watch()
    calls.append((time.perf_counter() - started) * 1000)
    return result


core._selection_watch_timer = measured_watch
for obj in tuple(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
with bpy.context.temp_override(window=window, area=area, region=region):
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=17, y_subdivisions=17)
    target = bpy.context.object
    bpy.ops.sdh.add_cage_chain(count=8, connection_mode="CHAINED", gap=0.0)
    bpy.context.view_layer.objects.active = target
    bpy.ops.view3d.view_axis(type="TOP", align_active=False)
    bpy.ops.view3d.view_selected(use_all_regions=False)


def native_box_select():
    with bpy.context.temp_override(window=window, area=area, region=region):
        point = location_3d_to_region_2d(
            region, area.spaces.active.region_3d, target.matrix_world.translation)
        assert point is not None
        bpy.ops.view3d.select_box(
            xmin=int(point.x) - 50, xmax=int(point.x) + 50,
            ymin=int(point.y) - 50, ymax=int(point.y) + 50,
            mode="SET", wait_for_input=False)


def outliner_selection(action):
    with bpy.context.temp_override(
            window=window, area=outliner, region=outliner_region):
        bpy.ops.outliner.select_all(action=action)


def direct_selection(selected):
    for obj in tuple(bpy.context.selected_objects):
        obj.select_set(False)
    target.select_set(selected)


actions = (
    ("select_set_false", lambda: direct_selection(False), False),
    ("select_set_true", lambda: direct_selection(True), True),
    ("native_deselect", lambda: bpy.ops.object.select_all(action="DESELECT"), False),
    ("native_box_select", native_box_select, True),
    ("outliner_deselect", lambda: outliner_selection("DESELECT"), False),
    ("outliner_select", lambda: outliner_selection("SELECT"), True),
)
state = {"index": 0, "phase": "start", "calls": 0, "idle_start": 0}


def finish(error=None):
    payload = {"blender": bpy.app.version_string, "chain_stages": 8,
               "records": records, "error": error}
    RESULT.write_text(("FAIL\n" if error else "PASS\n") +
                      json.dumps(payload, indent=2), encoding="utf-8")
    print("SDH_SELECTION_EVENTS::" + ("FAIL" if error else "PASS"))
    bpy.ops.wm.quit_blender()
    return None


def step():
    try:
        if state["index"] == len(actions):
            return finish()
        name, action, expected = actions[state["index"]]
        if state["phase"] == "start":
            state["calls"] = len(calls)
            action()
            state["deadline"] = time.monotonic() + 3.0
            state["phase"] = "settled"
            return 0.6
        controllers = [core.find_controller(target, modifier)
                       for modifier in core.cage_modifiers(target)]
        ready = (target.select_get() == expected and
                 all(obj.select_get() == expected for obj in controllers) and
                 not bpy.app.timers.is_registered(core._selection_watch_timer))
        if (state["phase"] == "settled" and not ready and
                time.monotonic() < state["deadline"]):
            return 0.1
        assert target.select_get() == expected, name
        assert all(obj.select_get() == expected for obj in controllers), name
        assert not bpy.app.timers.is_registered(core._selection_watch_timer), (
            name, "selection timer did not stop", len(calls),
            core._SELECTION_SYNC_DIRTY,
            core._selection_signature(bpy.context) == core._SELECTION_SYNC_SIGNATURE,
            len(bpy.data.objects), core._ORPHAN_HELPER_OBJECT_COUNT,
            repr(core._WORKSPACE_TOOL_CONFIRMATIONS))
        if state["phase"] == "settled":
            state["idle_start"] = len(calls)
            state["phase"] = "idle"
            return 1.0
        assert len(calls) == state["idle_start"], (name, "idle callback ran")
        records.append({"action": name, "selected": expected,
                        "event_callbacks": state["idle_start"] - state["calls"],
                        "event_callback_ms": sum(calls[state["calls"]:]),
                        "idle_seconds": 1.0, "idle_callbacks": 0})
        state["index"] += 1
        state["phase"] = "start"
        return 0.05
    except Exception:
        return finish(traceback.format_exc())


bpy.app.timers.register(step, first_interval=1.5)
