"""Exercise cage Workspace Tool reconciliation through real app timers."""
from __future__ import annotations

import importlib
import os
import sys
import traceback
from pathlib import Path

import bpy
from bpy.app.handlers import persistent


SOURCE = Path(__file__).resolve().parents[1]
ARGS = sys.argv[sys.argv.index("--") + 1:]
RESULT = Path(ARGS[0]).resolve()
RELOAD_FILE = RESULT.with_suffix(".blend")
INSTALLED_PACKAGE = os.environ.get("SDH_TEST_MODULE")
PACKAGE = INSTALLED_PACKAGE or SOURCE.name
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(SOURCE.parent))


def finish(message):
    RESULT.write_text(message, encoding="utf-8")
    try:
        if resume_after_load in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.remove(resume_after_load)
    except (NameError, ValueError):
        pass
    bpy.ops.wm.quit_blender()
    return None


try:
    addon = importlib.import_module(PACKAGE)
    if not INSTALLED_PACKAGE:
        entry = bpy.context.preferences.addons.new()
        entry.module = PACKAGE
        addon.register()
    cage = importlib.import_module(f"{PACKAGE}.cage_deform")
    core = cage.core

    window = bpy.context.window_manager.windows[0]
    area = next(item for item in window.screen.areas if item.type == "VIEW_3D")
    region = next(item for item in area.regions if item.type == "WINDOW")
    space = area.spaces.active
    with bpy.context.temp_override(
            window=window, area=area, region=region, space_data=space):
        bpy.ops.wm.tool_set_by_id(
            name="builtin.select_box", space_type="VIEW_3D")
        initial_tool = core._active_workspace_tool_id(bpy.context)
        bpy.ops.mesh.primitive_cube_add()
        target = bpy.context.object
        target.name = "SDH Workspace State Target"
        ffd_modifier, _ffd_controller, _previous = cage.create_deform_stage(
            bpy.context, target, cage_type="FFD")
        curve_modifier, _curve_controller, _previous = cage.create_deform_stage(
            bpy.context, target, cage_type="CURVE")
        standard_modifier, _standard_controller, _previous = (
            cage.create_deform_stage(
                bpy.context, target, cage_type="STANDARD"))
        bpy.ops.mesh.primitive_cube_add(location=(-4.0, 0.0, 0.0))
        plain_mesh = bpy.context.object
        plain_mesh.name = "SDH Workspace State Plain Mesh"
        bpy.ops.object.light_add(type="POINT", location=(4.0, 0.0, 0.0))
        light = bpy.context.object
        light.name = "SDH Workspace State Light"
        plain_empty = bpy.data.objects.new("SDH Workspace State Empty", None)
        bpy.context.collection.objects.link(plain_empty)

    if initial_tool in {core._FFD_WORKSPACE_TOOL_ID, core._CURVE_WORKSPACE_TOOL_ID}:
        raise RuntimeError("test did not start from a native Workspace Tool")

    def select_object(obj, modifier=None):
        for selected in tuple(bpy.context.selected_objects):
            selected.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        if modifier is not None:
            obj.modifiers.active = modifier

    def select_none():
        for selected in tuple(bpy.context.selected_objects):
            selected.select_set(False)
        bpy.context.view_layer.objects.active = None

    def active_but_unselected():
        for selected in tuple(bpy.context.selected_objects):
            selected.select_set(False)
        target.modifiers.active = ffd_modifier
        bpy.context.view_layer.objects.active = target

    def change_stage(modifier):
        target.modifiers.active = modifier

    def set_native_tool(tool_id):
        with bpy.context.temp_override(
                window=window, area=area, region=region, space_data=space):
            bpy.ops.wm.tool_set_by_id(
                name=tool_id, space_type="VIEW_3D")

    def expected_id(kind):
        return {
            "FFD": core._FFD_WORKSPACE_TOOL_ID,
            "CURVE": core._CURVE_WORKSPACE_TOOL_ID,
            "NATIVE": initial_tool,
            "MOVE": "builtin.move",
        }[kind]

    transitions = []
    for cycle in range(5):
        transitions.extend((
            (
                f"cycle {cycle + 1} select FFD",
                lambda modifier=ffd_modifier: select_object(target, modifier),
                "FFD",
            ),
            (f"cycle {cycle + 1} clear selection", select_none, "NATIVE"),
        ))
    transitions.extend((
        ("active target without selection", active_but_unselected, "NATIVE"),
        ("select ordinary mesh", lambda: select_object(plain_mesh), "NATIVE"),
        ("select ordinary light", lambda: select_object(light), "NATIVE"),
        ("select ordinary Empty", lambda: select_object(plain_empty), "NATIVE"),
        (
            "select Curve target",
            lambda: select_object(target, curve_modifier),
            "CURVE",
        ),
        (
            "same selection Curve to FFD",
            lambda: change_stage(ffd_modifier),
            "FFD",
        ),
        (
            "same selection FFD to Standard",
            lambda: change_stage(standard_modifier),
            "NATIVE",
        ),
        (
            "same selection Standard to Curve",
            lambda: change_stage(curve_modifier),
            "CURVE",
        ),
        (
            "explicit native tool remains user-controlled",
            lambda: set_native_tool("builtin.move"),
            "MOVE",
        ),
        (
            "restore native test tool",
            lambda: set_native_tool(initial_tool),
            "NATIVE",
        ),
        ("final clear selection", select_none, "NATIVE"),
    ))
    state = {"index": 0, "applied": False, "saw_arealess": False}

    def run_transitions():
        try:
            state["saw_arealess"] = bool(
                state["saw_arealess"] or bpy.context.area is None)
            if state["index"] >= len(transitions):
                if not state["saw_arealess"]:
                    return finish(
                        "FAIL: state regression never ran without an area")
                select_object(target, standard_modifier)
                bpy.ops.wm.save_as_mainfile(filepath=str(RELOAD_FILE))
                if resume_after_load not in bpy.app.handlers.load_post:
                    bpy.app.handlers.load_post.append(resume_after_load)
                bpy.ops.wm.open_mainfile(filepath=str(RELOAD_FILE))
                return None
            label, apply_state, expected = transitions[state["index"]]
            if not state["applied"]:
                apply_state()
                state["applied"] = True
                return 0.4
            actual = core._active_workspace_tool_id(bpy.context)
            if actual != expected_id(expected):
                return finish(
                    f"FAIL: {label}: expected {expected_id(expected)!r}, "
                    f"got {actual!r}")
            state["index"] += 1
            state["applied"] = False
            return 0.05
        except Exception:
            return finish("FAIL:\n" + traceback.format_exc())

    reload_state = {"step": 0}

    def run_after_load():
        try:
            loaded_target = bpy.data.objects.get("SDH Workspace State Target")
            if loaded_target is None:
                return finish("FAIL: reloaded target is missing")
            loaded_modifiers = cage.cage_modifiers(loaded_target)
            loaded_ffd = next((
                modifier for modifier in loaded_modifiers
                if str(getattr(
                    getattr(cage.find_controller(
                        loaded_target, modifier), "sdh_cage_deform", None),
                    "cage_type", "")) == "FFD"
            ), None)
            if loaded_ffd is None:
                return finish("FAIL: reloaded FFD stage is missing")
            reload_state["step"] += 1
            if reload_state["step"] == 1:
                select_object(loaded_target, loaded_ffd)
                return 0.5
            if reload_state["step"] == 2:
                actual = core._active_workspace_tool_id(bpy.context)
                if actual != core._FFD_WORKSPACE_TOOL_ID:
                    return finish(
                        "FAIL: file-load selection runtime did not restore FFD")
                select_none()
                return 0.5
            actual = core._active_workspace_tool_id(bpy.context)
            if actual != initial_tool:
                return finish(
                    "FAIL: file-load selection runtime did not restore native")
            return finish("PASS::WORKSPACE_TOOL_STATE")
        except Exception:
            return finish("FAIL:\n" + traceback.format_exc())

    @persistent
    def resume_after_load(_unused):
        try:
            bpy.app.handlers.load_post.remove(resume_after_load)
        except ValueError:
            pass
        bpy.app.timers.register(run_after_load, first_interval=0.2)

    bpy.app.timers.register(run_transitions, first_interval=0.2)
except Exception:
    finish("FAIL:\n" + traceback.format_exc())
