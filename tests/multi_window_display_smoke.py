"""Exercise independent display state and drawing in two real Blender windows."""
from __future__ import annotations

import importlib
import json
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Quaternion


SOURCE = Path(__file__).resolve().parents[1]
ARGS = sys.argv[sys.argv.index("--") + 1:]
RESULT = Path(ARGS[0]).resolve()
SCREENSHOT = Path(ARGS[1]).resolve() if len(ARGS) > 1 else None
sys.path.insert(0, str(SOURCE.parent))
addon = importlib.import_module(SOURCE.name)
display = importlib.import_module(f"{SOURCE.name}.view_state")
gizmos = importlib.import_module(f"{SOURCE.name}.cage_deform.gizmos")
draws = {}
step = 0
attempts = 0
windows = ()
first_key = None
second_key = None
original_draw = gizmos.SDHCageBendStrengthGizmo.draw


def tracked_draw(self, context):
    key = context.window.as_pointer()
    draws[key] = draws.get(key, 0) + 1
    return original_draw(self, context)


def view(window):
    area = next(item for item in window.screen.areas if item.type == "VIEW_3D")
    region = next(item for item in area.regions if item.type == "WINDOW")
    return dict(window=window, area=area, region=region)


def finish(message):
    gizmos.SDHCageBendStrengthGizmo.draw = original_draw
    RESULT.write_text(message, encoding="utf-8")
    bpy.ops.wm.quit_blender()
    return None


def tick():
    global step, attempts, windows, first_key, second_key
    try:
        attempts += 1
        if attempts > 60:
            raise AssertionError(f"two-window drawing timed out: {draws!r}")
        if step == 0:
            entry = bpy.context.preferences.addons.new()
            entry.module = SOURCE.name
            gizmos.SDHCageBendStrengthGizmo.draw = tracked_draw
            addon.register()
            window = bpy.context.window_manager.windows[0]
            with bpy.context.temp_override(**view(window)):
                for obj in tuple(bpy.data.objects):
                    bpy.data.objects.remove(obj, do_unlink=True)
                bpy.ops.mesh.primitive_cube_add()
                bpy.ops.object.mode_set(mode="EDIT")
                bpy.ops.mesh.subdivide(number_cuts=8)
                bpy.ops.object.mode_set(mode="OBJECT")
                assert bpy.ops.sdh.add_cage_deform() == {"FINISHED"}
                controller = bpy.context.object
                controller.sdh_cage_deform.bend_strength = 0.5
                assert bpy.ops.wm.window_new() == {"FINISHED"}
            step = 1
            return 0.5
        if step == 1:
            windows = tuple(bpy.context.window_manager.windows)
            assert len(windows) == 2, "second window was not created"
            for window in windows:
                with bpy.context.temp_override(**view(window)):
                    space = bpy.context.space_data
                    space.region_3d.view_distance = 8.0
                    space.region_3d.view_location = (0.0, 0.0, 0.0)
                    space.region_3d.view_rotation = Quaternion((0.82, 0.42, 0.18, 0.35)).normalized()
                    space.show_region_ui = False
                    bpy.context.area.tag_redraw()
            step = 2
            return 0.5
        if step == 2:
            if not all(draws.get(window.as_pointer(), 0) > 0 for window in windows):
                for window in windows:
                    view(window)["area"].tag_redraw()
                return 0.25
            with bpy.context.temp_override(**view(windows[0])):
                first_key = display.view_key(bpy.context)
                for kind in ("cage", "gizmo", "guides"):
                    assert bpy.ops.sdh.toggle_view_display(kind=kind) == {"FINISHED"}
                assert not display.viewport_cage_overlay_enabled(bpy.context)
                assert not display.viewport_cage_gizmos_enabled(bpy.context)
            with bpy.context.temp_override(**view(windows[1])):
                second_key = display.view_key(bpy.context)
                assert second_key != first_key
                assert display.viewport_cage_overlay_enabled(bpy.context)
                assert display.viewport_cage_gizmos_enabled(bpy.context)
                assert bpy.ops.sdh.toggle_view_display(kind="guides") == {"FINISHED"}
                assert not display.viewport_cage_guides_enabled(bpy.context)
            step = 3
            return 0.5
        if step == 3:
            if SCREENSHOT:
                for index, window in enumerate(windows):
                    path = SCREENSHOT.with_name(f"{SCREENSHOT.stem}-{index + 1}.png")
                    with bpy.context.temp_override(**view(window)):
                        bpy.ops.screen.screenshot(filepath=str(path))
            with bpy.context.temp_override(**view(windows[1])):
                assert bpy.ops.wm.window_close() == {"FINISHED"}
            step = 4
            return 0.5
        assert len(bpy.context.window_manager.windows) == 1
        with bpy.context.temp_override(**view(windows[0])):
            display.prune_view_states(bpy.context, force=True)
            assert second_key not in display._VIEW_STATES
            assert first_key in display._VIEW_STATES
            addon.unregister()
            assert not display._VIEW_STATES and not display._PANEL_CALLBACKS
            addon.register()
            assert display.viewport_cage_overlay_enabled(bpy.context)
            assert display.viewport_cage_gizmos_enabled(bpy.context)
            addon.unregister()
        return finish("PASS::MULTI_WINDOW_DISPLAY\n" + json.dumps({
            "blender": bpy.app.version_string, "draws_per_window": draws,
            "independent_toggles": True, "closed_window_pruned": True,
            "disable_reenable": True,
        }, sort_keys=True))
    except Exception:
        return finish("FAIL::MULTI_WINDOW_DISPLAY\n" + traceback.format_exc())


bpy.app.timers.register(tick, first_interval=0.5)
