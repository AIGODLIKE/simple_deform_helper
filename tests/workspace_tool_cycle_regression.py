"""Preserve native selection cycling and cage tools across real W-key events.

Run in an isolated GUI profile with --factory-startup --enable-event-simulate
--python tests/workspace_tool_cycle_regression.py -- RESULT_PATH.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
import traceback

import bpy
from bl_ui.space_toolsystem_common import ToolSelectPanelHelper


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = os.environ.get("SDH_TEST_MODULE", SOURCE.name)
RESULT = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
addon = None
completed = []


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def finish(message):
    if not message.startswith("PASS"):
        bpy.ops.screen.screenshot(filepath=str(RESULT.with_suffix(".png")))
    if addon is not None:
        try:
            addon.unregister()
        except Exception:
            message = "FAIL::TEARDOWN\n" + message + "\n" + traceback.format_exc()
    RESULT.write_text(message, encoding="utf-8")
    print(message, flush=True)
    bpy.ops.wm.quit_blender()
    return None


def exercise():
    global addon
    check(not bpy.app.background, "real W-key coverage requires the GUI event loop")
    bpy.context.preferences.use_preferences_save = False
    bpy.context.preferences.view.show_splash = False
    window = bpy.context.window_manager.windows[0]
    area = next(item for item in window.screen.areas if item.type == "VIEW_3D")
    region = next(item for item in area.regions if item.type == "WINDOW")
    # A fresh isolated profile can already have the startup splash open.
    x, y = region.x + region.width // 2, region.y + region.height // 2
    window.event_simulate(type="ESC", value="PRESS", x=x, y=y)
    window.event_simulate(type="ESC", value="RELEASE", x=x, y=y)
    yield 0.3

    def view_context():
        return bpy.context.temp_override(window=window, area=area, region=region)

    def active_id():
        tool = window.workspace.tools.from_space_view3d_mode("OBJECT", create=False)
        return getattr(tool, "idname", "")

    def select_group():
        with view_context():
            cls = ToolSelectPanelHelper._tool_class_from_space_type("VIEW_3D")
            return next(group for group in cls.tools_from_context(bpy.context)
                        if type(group) is tuple and any(
                            getattr(item, "idname", None) == "builtin.select_box"
                            for item in group))

    def group_ids():
        return tuple(getattr(item, "idname", None) for item in select_group())

    if "SDH_TEST_MODULE" not in os.environ:
        sys.path.insert(0, str(SOURCE.parent))
    addon = importlib.import_module(PACKAGE)
    if "SDH_TEST_MODULE" in os.environ:
        # Capture native tools without the already-enabled installed extension.
        addon.unregister()
    else:
        bpy.context.preferences.addons.new().module = PACKAGE
    native_ids = group_ids()
    check(None not in native_ids, "factory selection group already has a separator")
    check(len(native_ids) >= 4, f"unexpected native selection group: {native_ids}")

    def check_native_cycle(label):
        check(group_ids() == native_ids, f"{label}: extension changed native selection group")
        visited = set()
        with view_context():
            for _index in range(len(native_ids) * 3):
                check(bpy.ops.wm.tool_set_by_id(
                    name="builtin.select_box", space_type="VIEW_3D", cycle=True
                ) == {"FINISHED"}, f"{label}: cycle operator failed")
                visited.add(active_id())
        check(visited == set(native_ids), f"{label}: native cycle skipped or added tools: {visited}")

    def real_w_cycle(label):
        x, y = region.x + region.width // 2, region.y + region.height // 2
        window.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y)
        yield 0.15
        visited = set()
        for _index in range(len(native_ids) * 2):
            before = active_id()
            window.event_simulate(type="W", value="PRESS", x=x, y=y)
            window.event_simulate(type="W", value="RELEASE", x=x, y=y)
            yield 0.15
            after = active_id()
            check(after in native_ids and after != before,
                  f"{label}: W did not advance the native tool: {before} -> {after}")
            visited.add(after)
        check(visited == set(native_ids), f"{label}: W did not visit every native tool")
        completed.append(label)

    with view_context():
        bpy.ops.wm.tool_set_by_id(name="builtin.select_box", space_type="VIEW_3D")
    check_native_cycle("before_enable")
    addon.register()
    yield 0.25
    core = importlib.import_module(f"{PACKAGE}.cage_deform.core")
    core.register_ffd_workspace_tool()
    core.register_ffd_workspace_tool()
    check_native_cycle("enabled_without_cage")

    for index, cage_type in enumerate(("STANDARD", "SHEAR", "FFD", "CURVE")):
        with view_context():
            bpy.ops.object.select_all(action="DESELECT")
            bpy.ops.mesh.primitive_cube_add(location=(index * 4.0, 0.0, 0.0))
            check(bpy.ops.sdh.add_cage_deform(cage_type=cage_type) == {"FINISHED"},
                  f"could not add {cage_type} cage")
        yield 0.25
        tool_id = {"FFD": core._FFD_WORKSPACE_TOOL_ID,
                   "CURVE": core._CURVE_WORKSPACE_TOOL_ID}.get(cage_type)
        if tool_id:
            check(active_id() == tool_id, f"{cage_type} editor did not activate")
        check_native_cycle(cage_type)
        yield from real_w_cycle(cage_type)
        if tool_id:
            with view_context():
                check(bpy.ops.wm.tool_set_by_id(
                    name=tool_id, space_type="VIEW_3D") == {"FINISHED"},
                    f"{cage_type} editor became unreachable after W")
                check(active_id() == tool_id, f"{cage_type} editor did not restore")
            check_native_cycle(f"leave_{cage_type}_editor")

    addon.unregister()
    yield 0.2
    check_native_cycle("disabled")
    yield from real_w_cycle("disabled")
    addon.register()
    yield 0.25
    check_native_cycle("reenabled")
    yield from real_w_cycle("reenabled")


steps = exercise()


def tick():
    try:
        return next(steps)
    except StopIteration:
        return finish("PASS::WORKSPACE_TOOL_CYCLE::" + bpy.app.version_string +
                      "::" + ",".join(completed))
    except Exception:
        return finish("FAIL::WORKSPACE_TOOL_CYCLE\n" + traceback.format_exc())


bpy.app.timers.register(tick, first_interval=0.5)
