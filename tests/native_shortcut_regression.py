"""Assign a shortcut through Blender's native button menu and execute it."""
from __future__ import annotations

import ast
import importlib
import inspect
import os
import sys
import textwrap
import traceback
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
ARGS = sys.argv[sys.argv.index("--") + 1:]
RESULT = Path(ARGS[0]).resolve()
PACKAGE = os.environ.get("SDH_TEST_MODULE", SOURCE.name)
OLD_ID = "sdh.add_legacy_simple_deform"
NEW_ID = "object.sdh_add_legacy_simple_deform"
STATE = {"step": 0}
addon = None
panel_registered = False


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def finish(message):
    if addon is not None:
        try:
            addon.unregister()
        except Exception:
            message = "FAIL::NATIVE_SHORTCUT_TEARDOWN\n" + message + "\n" + traceback.format_exc()
    if panel_registered:
        bpy.utils.unregister_class(SDH_TEST_PT_shortcut)
    RESULT.write_text(message, encoding="utf-8")
    print(message, flush=True)
    bpy.ops.wm.quit_blender()
    return None


class SDH_TEST_PT_shortcut(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_label = "Shortcut Regression"

    def draw(self, _context):
        self.layout.operator(NEW_ID, text="Legacy Deform")


def event(kind, *, value="PRESS", **modifiers):
    window.event_simulate(type=kind, value=value, x=400, y=400, **modifiers)
    if value == "PRESS":
        window.event_simulate(
            type=kind, value="RELEASE", x=400, y=400, **modifiers)


def matching_keys(identifier):
    return tuple(
        (keymap, item)
        for keymap in bpy.context.window_manager.keyconfigs.user.keymaps
        for item in keymap.keymap_items
        if item.idname == identifier)


def deformation_count():
    return sum(item.type == "SIMPLE_DEFORM" for item in target.modifiers)


def check_alias_implementation(source):
    # Copied methods must not depend on the original class's identity.
    tree = ast.parse(textwrap.dedent(inspect.getsource(source)))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            check(node.id not in {"super", "__class__", source.__name__},
                  f"alias implementation depends on its source class: {source.__name__}")
        if isinstance(node, ast.Attribute):
            check(node.attr != "__class__", f"alias uses class identity: {source.__name__}")
            check(not (node.attr == "bl_idname" and isinstance(node.value, ast.Name)
                       and node.value.id in {"self", "cls"}),
                  f"alias uses its changed operator identifier: {source.__name__}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            check(not (node.func.id == "type" and node.args
                       and isinstance(node.args[0], ast.Name)
                       and node.args[0].id in {"self", "cls"}),
                  f"alias uses concrete class identity: {source.__name__}")


def tick():
    try:
        step = STATE["step"]
        if step == 0:
            event("ESC")
        elif step == 1:
            event("MOUSEMOVE", value="NOTHING")
        elif step == 2:
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.wm.call_panel(
                    "INVOKE_DEFAULT", name=SDH_TEST_PT_shortcut.__name__, keep_open=True)
        elif step == 3:
            event("RIGHTMOUSE")
        elif step == 4:
            bpy.ops.screen.screenshot(filepath=str(RESULT.with_suffix(".menu.png")))
            event("DOWN_ARROW")
        elif step == 5:
            event("RET")
        elif step == 6:
            event("F6", ctrl=True, alt=True, shift=True)
        elif step == 7:
            matches = matching_keys(NEW_ID)
            check(len(matches) == 1, "native Assign Shortcut did not create one keymap item")
            keymap, item = matches[0]
            check(keymap.name == "Object Mode", "shortcut was assigned to the wrong context")
            check(item.type == "F6" and item.ctrl and item.alt and item.shift,
                  "native shortcut did not preserve the entered key event")
            event("ESC")
        elif step == 8:
            STATE["before"] = deformation_count()
            event("F6", ctrl=True, alt=True, shift=True)
        elif step == 9:
            check(deformation_count() == STATE["before"] + 1,
                  "assigned native shortcut did not create a deformation")
            STATE["before"] = deformation_count()
            event("F7", ctrl=True, alt=True, shift=True)
        elif step == 10:
            check(deformation_count() == STATE["before"] + 1,
                  "existing legacy shortcut stopped working")
            check(bpy.ops.sdh.add_legacy_simple_deform() == {"FINISHED"},
                  "legacy Python operator call stopped working")
            STATE["key_items"] = tuple(
                (item.idname, item.type, item.ctrl, item.alt, item.shift)
                for identifier in (OLD_ID, NEW_ID)
                for _keymap, item in matching_keys(identifier))
            addon.unregister()
            check(not addon.operator_aliases._registered_classes,
                  "disable left alias classes registered")
            addon.register()
            addon.operator_aliases.register()
            current = tuple(
                (item.idname, item.type, item.ctrl, item.alt, item.shift)
                for identifier in (OLD_ID, NEW_ID)
                for _keymap, item in matching_keys(identifier))
            check(current == STATE["key_items"], "lifecycle changed user shortcut settings")
            check(len(addon.operator_aliases._registered_classes) == STATE["alias_count"],
                  "repeated registration duplicated alias classes")
        elif step == 11:
            return finish(
                "PASS::NATIVE_SHORTCUT::" + bpy.app.version_string +
                f"::aliases={STATE['alias_count']}::native_assign_and_execute"
                "::legacy_key_and_python_preserved::lifecycle")
        STATE["step"] += 1
        return 0.45
    except Exception:
        return finish("FAIL::NATIVE_SHORTCUT\n" + traceback.format_exc())


try:
    check(not bpy.app.background, "the native shortcut test requires a GUI event loop")
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
    STATE["alias_count"] = len(addon.operator_aliases._registered_classes)
    for old_id in addon.operator_aliases._ui_identifiers():
        new_id = addon.operator_aliases.native_operator_idname(old_id)
        old_namespace, old_name = old_id.split(".")
        new_namespace, new_name = new_id.split(".")
        original = getattr(getattr(bpy.ops, old_namespace), old_name)
        alias = getattr(getattr(bpy.ops, new_namespace), new_name)
        source = bpy.types.Operator.bl_rna_get_subclass_py(
            original.get_rna_type().identifier)
        check_alias_implementation(source)
        check(set(original.get_rna_type().properties.keys()) ==
              set(alias.get_rna_type().properties.keys()),
              f"alias changed RNA properties: {old_id}")
        check(original.poll() == alias.poll(), f"alias changed poll: {old_id}")
    target = bpy.context.object
    target.name = "Native Shortcut Target"
    preference = bpy.context.preferences.addons[PACKAGE].preferences
    preference.show_gizmo = False
    preference.update_deform_wireframe = False
    window = bpy.context.window_manager.windows[0]
    area = next(item for item in window.screen.areas if item.type == "VIEW_3D")
    region = next(item for item in area.regions if item.type == "WINDOW")
    area.spaces.active.show_gizmo = False
    keymap = bpy.context.window_manager.keyconfigs.user.keymaps["Object Mode"]
    keymap.keymap_items.new(OLD_ID, "F7", "PRESS", ctrl=True, alt=True, shift=True)
    bpy.utils.register_class(SDH_TEST_PT_shortcut)
    panel_registered = True
    bpy.app.timers.register(tick, first_interval=0.6)
except Exception:
    finish("FAIL::NATIVE_SHORTCUT\n" + traceback.format_exc())
