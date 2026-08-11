"""Undo regression for the legacy Simple Deform angle Gizmo."""

import importlib
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
RESULT = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
sys.path.insert(0, str(SOURCE.parent))


def run_test():
    entry = None
    addon = None
    result = "PASS"
    try:
        window = bpy.context.window_manager.windows[0]
        area = next(item for item in window.screen.areas if item.type == "VIEW_3D")
        region = next(item for item in area.regions if item.type == "WINDOW")
        space = area.spaces.active
        with bpy.context.temp_override(
                window=window, area=area, region=region, space_data=space):
            entry = bpy.context.preferences.addons.new()
            entry.module = PACKAGE
            addon = importlib.import_module(PACKAGE)
            angle_module = importlib.import_module(
                f"{PACKAGE}.gizmo.angle_and_factor")
            utils_module = importlib.import_module(f"{PACKAGE}.utils")
            state = {"handle": None, "ticks": 0}
            original_draw = angle_module.AngleGizmo.draw

            def tracked_draw(handle, context):
                state["handle"] = handle
                return original_draw(handle, context)

            angle_module.AngleGizmo.draw = tracked_draw
            addon.register()
            bpy.ops.mesh.primitive_cube_add()
            target = bpy.context.object
            target.name = "Traditional Gizmo Undo Target"
            target.scale = (1.0, 1.0, 3.0)
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            if bpy.ops.sdh.add_legacy_simple_deform() != {"FINISHED"}:
                raise AssertionError("could not add traditional modifier")
            modifier = target.modifiers.active
            modifier.deform_method = "TWIST"
            modifier.deform_axis = "Z"
            modifier.angle = 0.0
            preferences = utils_module.get_pref()
            preferences.show_gizmo = True
            preferences.display_bend_axis_switch_gizmo = False
            bpy.ops.view3d.view_axis(type="FRONT", align_active=False)
            bpy.ops.view3d.view_selected(use_all_regions=False)

        target_name = target.name

        def finish(message):
            RESULT.write_text(message, encoding="utf-8")
            if addon is not None:
                try:
                    addon.unregister()
                except Exception:
                    message += "\nUNREGISTER FAIL\n" + traceback.format_exc()
            if entry is not None:
                try:
                    bpy.context.preferences.addons.remove(entry)
                except Exception:
                    message += "\nPREFERENCES CLEANUP FAIL\n" + traceback.format_exc()
            RESULT.write_text(message, encoding="utf-8")
            bpy.ops.wm.quit_blender()
            return None

        def step():
            try:
                state["ticks"] += 1
                handle = state["handle"]
                if handle is None:
                    if state["ticks"] > 30:
                        raise AssertionError("traditional angle Gizmo did not draw")
                    area.tag_redraw()
                    return 0.1
                event = SimpleNamespace(
                    type="LEFTMOUSE", value="PRESS",
                    mouse_region_x=200, mouse_region_y=200,
                    shift=False, ctrl=False, alt=False, is_repeat=False,
                )
                with bpy.context.temp_override(
                        window=window, area=area, region=region, space_data=space):
                    handle.invoke(bpy.context, event)
                    event.type = "MOUSEMOVE"
                    event.value = "NOTHING"
                    event.mouse_region_x = 260
                    handle.modal(bpy.context, event, ())
                    event.type = "X"
                    event.value = "PRESS"
                    handle.event_handle(event)
                    handle.exit(bpy.context, False)
                changed = float(modifier.angle)
                if abs(changed) <= 1.0e-6:
                    raise AssertionError("traditional Gizmo did not change angle")
                if modifier.deform_axis != "X":
                    raise AssertionError("traditional keyboard axis change failed")
                if bpy.ops.ed.undo() != {"FINISHED"}:
                    raise AssertionError("traditional Gizmo undo failed")
                restored_target = bpy.data.objects.get(target_name)
                if restored_target is None:
                    raise AssertionError("target disappeared after traditional undo")
                restored_modifier = next(
                    (item for item in restored_target.modifiers
                     if item.type == "SIMPLE_DEFORM"), None)
                if restored_modifier is None:
                    raise AssertionError(
                        "traditional undo removed the Simple Deform modifier")
                if abs(float(restored_modifier.angle)) > 1.0e-6:
                    raise AssertionError(
                        f"traditional undo did not restore angle: {restored_modifier.angle}")
                if restored_modifier.deform_axis != "Z":
                    raise AssertionError(
                        "traditional undo did not restore the keyboard axis change")

                restored_modifier.deform_axis = "Z"
                if bpy.ops.simple_deform_gizmo.set_deform_axis(
                        axis="X") != {"FINISHED"}:
                    raise AssertionError("traditional axis Gizmo operator failed")
                if restored_modifier.deform_axis != "X":
                    raise AssertionError("traditional axis Gizmo did not set X")
                if bpy.ops.ed.undo() != {"FINISHED"}:
                    raise AssertionError("traditional axis Gizmo undo failed")
                restored_target = bpy.data.objects.get(target_name)
                restored_modifier = next(
                    (item for item in restored_target.modifiers
                     if item.type == "SIMPLE_DEFORM"), None)
                if restored_modifier is None:
                    raise AssertionError(
                        "axis undo removed the Simple Deform modifier")
                if restored_modifier.deform_axis != "Z":
                    raise AssertionError(
                        "traditional axis undo did not restore the Z axis")
                return finish("PASS")
            except Exception:
                return finish("FAIL\n" + traceback.format_exc())

        bpy.app.timers.register(step, first_interval=0.5)
        return None
    except Exception:
        result = "FAIL\n" + traceback.format_exc()
        RESULT.write_text(result, encoding="utf-8")
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run_test, first_interval=0.5)
