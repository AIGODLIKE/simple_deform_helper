"""Keep disk-writing preset actions out of Blender's F9 redo history."""
from __future__ import annotations

import importlib
import os
import sys
import traceback
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
ARGS = sys.argv[sys.argv.index("--") + 1:]
RESULT = Path(ARGS[0]).resolve()
PACKAGE = os.environ.get("SDH_TEST_MODULE", SOURCE.name)
STATE = {"step": 0}
addon = None


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def finish(message):
    if addon is not None:
        try:
            addon.unregister()
        except Exception:
            message = "FAIL::STACK_PRESET_REDO_TEARDOWN\n" + message + "\n" + traceback.format_exc()
    RESULT.write_text(message, encoding="utf-8")
    print(message, flush=True)
    bpy.ops.wm.quit_blender()
    return None


def event(kind):
    window.event_simulate(type=kind, value="PRESS", x=400, y=400)
    window.event_simulate(type=kind, value="RELEASE", x=400, y=400)


def check_redo_history():
    forbidden = {
        "SDH_OT_save_cage_stack_preset", "SDH_OT_delete_cage_stack_preset",
        "OBJECT_OT_sdh_save_cage_stack_preset", "OBJECT_OT_sdh_delete_cage_stack_preset",
    }
    check(not any(operator.bl_idname in forbidden
                  for operator in bpy.context.window_manager.operators),
          "a disk-writing preset action entered the redo history")


def files_snapshot():
    return {path.name: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in preset_directory.glob("*.json")}


def tick():
    try:
        step = STATE["step"]
        if step == 0:
            event("ESC")
        elif step == 1:
            with bpy.context.temp_override(window=window, area=area, region=region):
                check(bpy.ops.object.sdh_save_cage_stack_preset("INVOKE_DEFAULT") ==
                      {"RUNNING_MODAL"}, "Save Preset no longer opens its name dialog")
        elif step == 2:
            event("RET")
        elif step == 3:
            check(saved_file.exists(), "Save Preset dialog did not write its file")
            check_redo_history()
            STATE["after_save"] = files_snapshot()
            event("F9")
        elif step == 4:
            check(files_snapshot() == STATE["after_save"], "F9 repeated the preset save")
            bpy.ops.screen.screenshot(filepath=str(RESULT.with_suffix(".save-f9.png")))
            event("ESC")
        elif step == 5:
            check(bpy.ops.sdh.save_cage_stack_preset(preset_name="ZZ Retained Preset") ==
                  {"FINISHED"}, "legacy preset save call stopped working")
            STATE["retained"] = retained_file.read_bytes()
            check_redo_history()
            with bpy.context.temp_override(window=window, area=area, region=region):
                check(bpy.ops.object.sdh_delete_cage_stack_preset("INVOKE_DEFAULT") ==
                      {"RUNNING_MODAL"}, "Delete Preset no longer opens its search popup")
        elif step == 6:
            event("RET")
        elif step == 7:
            check(not saved_file.exists(), "Delete Preset popup did not remove the selected file")
            check(retained_file.read_bytes() == STATE["retained"],
                  "Delete Preset removed an unrelated preset")
            check_redo_history()
            STATE["after_delete"] = files_snapshot()
            event("F9")
        elif step == 8:
            check(files_snapshot() == STATE["after_delete"], "F9 repeated the preset deletion")
            bpy.ops.screen.screenshot(filepath=str(RESULT.with_suffix(".delete-f9.png")))
            event("ESC")
        elif step == 9:
            check(bpy.ops.sdh.delete_cage_stack_preset(preset="ZZ Retained Preset") ==
                  {"FINISHED"}, "legacy preset deletion stopped working")
            check(not retained_file.exists(), "legacy deletion left the preset behind")
            check_redo_history()
            return finish(
                "PASS::STACK_PRESET_REDO::" + bpy.app.version_string +
                "::save_dialog::delete_popup::f9_no_disk_changes::legacy_calls")
        STATE["step"] += 1
        return 0.5
    except Exception:
        return finish("FAIL::STACK_PRESET_REDO\n" + traceback.format_exc())


try:
    check(not bpy.app.background, "preset redo requires a GUI event loop")
    check(RESULT.parent.is_dir(), "result directory must already exist")
    for variable, resource in (
            ("BLENDER_USER_CONFIG", "CONFIG"),
            ("BLENDER_USER_SCRIPTS", "SCRIPTS"),
            ("BLENDER_USER_EXTENSIONS", "EXTENSIONS"),
            ("BLENDER_USER_DATAFILES", "DATAFILES")):
        expected = Path(os.environ[variable]).resolve()
        check(expected.is_dir(), f"isolated {variable} directory must already exist")
        check(Path(bpy.utils.user_resource(resource)).resolve() == expected,
              f"Blender did not use isolated {resource}")
    bpy.context.preferences.use_preferences_save = False
    bpy.context.preferences.view.show_splash = False
    if "SDH_TEST_MODULE" not in os.environ:
        sys.path.insert(0, str(SOURCE.parent))
    addon = importlib.import_module(PACKAGE)
    if "SDH_TEST_MODULE" not in os.environ:
        entry = bpy.context.preferences.addons.new()
        entry.module = PACKAGE
        addon.register()
    target = bpy.context.object
    target.name = "AA Redo Regression"
    preference = bpy.context.preferences.addons[PACKAGE].preferences
    preference.show_gizmo = False
    preference.update_deform_wireframe = False
    check(bpy.ops.sdh.add_cage_deform() == {"FINISHED"}, "cage creation failed")
    bpy.context.view_layer.objects.active = target
    target.select_set(True)
    window = bpy.context.window_manager.windows[0]
    area = next(item for item in window.screen.areas if item.type == "VIEW_3D")
    region = next(item for item in area.regions if item.type == "WINDOW")
    area.spaces.active.show_gizmo = False
    preset_directory = addon.cage_deform.stack_presets._preset_directory()
    config = Path(os.environ["BLENDER_USER_CONFIG"]).resolve()
    extensions = Path(os.environ["BLENDER_USER_EXTENSIONS"]).resolve()
    check(preset_directory.resolve().is_relative_to(config) or
          preset_directory.resolve().is_relative_to(extensions),
          "preset directory escaped the isolated profile")
    saved_file = preset_directory / "AA Redo Regression Stack.json"
    retained_file = preset_directory / "ZZ Retained Preset.json"
    check(not tuple(preset_directory.glob("*.json")), "preset profile must start empty")
    bpy.app.timers.register(tick, first_interval=0.6)
except Exception:
    finish("FAIL::STACK_PRESET_REDO\n" + traceback.format_exc())
