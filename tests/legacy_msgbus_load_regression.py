"""Verify legacy origin notifications across real file loads and lifecycle changes."""
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
RELOAD_FILE = RESULT.with_suffix(".blend")
INSTALLED_PACKAGE = os.environ.get("SDH_TEST_MODULE")
PACKAGE = INSTALLED_PACKAGE or SOURCE.name
TARGET_NAME = "SDH Legacy Message Bus Target"
STATE = {"step": 0, "notifications": 0, "checks": []}
addon = None
message_bus = None
original_refresh = None


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def finish(message):
    if addon is not None:
        try:
            addon.unregister()
        except Exception:
            message += "\nCleanup failure:\n" + traceback.format_exc()
    if message_bus is not None and original_refresh is not None:
        message_bus._refresh_managed_origin = original_refresh
    RESULT.write_text(message, encoding="utf-8")
    print(message, flush=True)
    bpy.ops.wm.quit_blender()
    return None


def active_modifier():
    target = bpy.data.objects.get(TARGET_NAME)
    check(target is not None, "saved target was not restored")
    bpy.context.view_layer.objects.active = target
    target.select_set(True)
    modifier = target.modifiers.active
    check(modifier is not None and modifier.type == "SIMPLE_DEFORM",
          "saved Simple Deform modifier was not restored")
    return modifier


def publish(property_name):
    STATE["before_notifications"] = STATE["notifications"]
    bpy.msgbus.publish_rna(key=(bpy.types.SimpleDeformModifier, property_name))


def expect_notifications(label, expected=1):
    actual = STATE["notifications"] - STATE["before_notifications"]
    check(actual == expected,
          f"{label}: expected {expected} notification(s), got {actual}")
    STATE["checks"].append(label)


def move_limit(value):
    modifier = active_modifier()
    check(modifier.origin is not None, "managed origin is missing")
    STATE["before_location"] = tuple(modifier.origin.matrix_world.translation)
    modifier.limits[0] = value
    publish("limits")


def expect_origin_moved(label):
    expect_notifications(label)
    position = active_modifier().origin.matrix_world.translation
    delta = sum((value - previous) ** 2 for value, previous in
                zip(position, STATE["before_location"]))
    check(delta > 1.0e-8, f"{label}: managed origin did not follow changed limits")


def tick():
    try:
        step = STATE["step"]
        if step == 0:
            message_bus.register()
            message_bus.register()
            check(bpy.app.handlers.load_post.count(message_bus._load_post) == 1,
                  "repeated registration duplicated the load handler")
            move_limit(0.25)
        elif step == 1:
            expect_origin_moved("before load, repeated register is idempotent")
            message_bus.remember_deform_method[(-1, -1)] = "STALE"
            bpy.ops.wm.save_as_mainfile(
                filepath=str(RELOAD_FILE), check_existing=False)
            bpy.ops.wm.open_mainfile(filepath=str(RELOAD_FILE))
        elif step == 2:
            check((-1, -1) not in message_bus.remember_deform_method,
                  "file loading kept pointer keys from the previous file")
            check(bpy.app.handlers.load_post.count(message_bus._load_post) == 1,
                  "file loading duplicated the load handler")
            move_limit(0.5)
        elif step == 3:
            expect_origin_moved("limits notification restored after file load")
            publish("deform_axis")
        elif step == 4:
            expect_notifications("axis notification restored after file load")
            publish("deform_method")
        elif step == 5:
            expect_notifications("method notification restored after file load")
            addon.unregister()
            check(message_bus._load_post not in bpy.app.handlers.load_post,
                  "disable left a persistent load handler")
            check(not message_bus.remember_deform_method,
                  "disable kept the deform-method cache")
            publish("limits")
        elif step == 6:
            expect_notifications("disable removes subscriptions", expected=0)
            bpy.ops.wm.open_mainfile(filepath=str(RELOAD_FILE))
        elif step == 7:
            check(message_bus._load_post not in bpy.app.handlers.load_post,
                  "loading a file restored the disabled load handler")
            publish("limits")
        elif step == 8:
            expect_notifications("disabled file load stays disabled", expected=0)
            addon.register()
            check(bpy.app.handlers.load_post.count(message_bus._load_post) == 1,
                  "re-enable did not restore exactly one load handler")
        elif step == 9:
            move_limit(0.75)
        elif step == 10:
            expect_origin_moved("re-enable restores origin notifications")
            addon.unregister()
            message_bus.unregister()
            check(message_bus._load_post not in bpy.app.handlers.load_post,
                  "repeated unregister left a load handler")
            publish("deform_method")
        elif step == 11:
            expect_notifications("repeated unregister is idempotent", expected=0)
            return finish(
                "PASS::LEGACY_MSGBUS_LOAD::" + bpy.app.version_string + "\n" +
                "\n".join(STATE["checks"]))
        STATE["step"] += 1
        return 0.4
    except Exception:
        return finish("FAIL::LEGACY_MSGBUS_LOAD\n" + traceback.format_exc())


try:
    check(not bpy.app.background, "this test requires the GUI event loop")
    check(RESULT.parent.is_dir(), "test output directory must already exist")
    expected_config = os.environ.get("BLENDER_USER_CONFIG")
    check(bool(expected_config), "BLENDER_USER_CONFIG must isolate the test")
    expected_config = Path(expected_config).resolve()
    check(expected_config.is_dir(), "isolated config directory must already exist")
    actual_config = Path(bpy.utils.user_resource("CONFIG")).resolve()
    check(actual_config == expected_config,
          f"Blender config is not isolated: {actual_config}")
    for name in ("BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES",
                 "BLENDER_USER_EXTENSIONS"):
        value = os.environ.get(name)
        check(bool(value) and Path(value).is_dir(),
              f"{name} must point to an existing isolated directory")
    bpy.context.preferences.use_preferences_save = False
    if not INSTALLED_PACKAGE:
        sys.path.insert(0, str(SOURCE.parent))
    addon = importlib.import_module(PACKAGE)
    if not INSTALLED_PACKAGE:
        entry = bpy.context.preferences.addons.new()
        entry.module = PACKAGE
        addon.register()
    preference = bpy.context.preferences.addons[PACKAGE].preferences
    preference.show_gizmo = False
    preference.update_deform_wireframe = False
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.show_gizmo = False
    message_bus = addon.msgbus
    original_refresh = message_bus._refresh_managed_origin

    def counted_refresh(*, update_rotation=False):
        STATE["notifications"] += 1
        original_refresh(update_rotation=update_rotation)

    message_bus._refresh_managed_origin = counted_refresh
    bpy.ops.mesh.primitive_cube_add()
    target = bpy.context.object
    target.name = TARGET_NAME
    check(bpy.ops.sdh.add_legacy_simple_deform() == {"FINISHED"},
          "legacy deformation creation failed")
    bpy.app.timers.register(tick, first_interval=0.5, persistent=True)
except Exception:
    finish("FAIL::LEGACY_MSGBUS_LOAD\n" + traceback.format_exc())
