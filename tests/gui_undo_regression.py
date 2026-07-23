"""Window-context undo regression for Blender or xvfb-run."""

import importlib
import sys
import traceback
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
RESULT = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
sys.path.insert(0, str(SOURCE.parent))


def run_test():
    addon_entry = None
    addon = None
    result = "PASS"
    try:
        window = bpy.context.window_manager.windows[0]
        area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
        region = next(region for region in area.regions if region.type == "WINDOW")
        with bpy.context.temp_override(window=window, area=area, region=region):
            addon_entry = bpy.context.preferences.addons.new()
            addon_entry.module = PACKAGE
            addon = importlib.import_module(PACKAGE)
            addon.register()

            bpy.ops.mesh.primitive_cube_add()
            obj = bpy.context.object
            first = obj.modifiers.new("Undo Bend", "SIMPLE_DEFORM")
            second = obj.modifiers.new("Undo Twist", "SIMPLE_DEFORM")
            obj.modifiers.active = first
            bpy.ops.ed.undo_push(message="Before topology helper")

            if bpy.ops.simple_deform_gizmo.add_topology() != {"FINISHED"}:
                raise AssertionError("topology operator failed")
            if len(obj.modifiers) != 3:
                raise AssertionError("topology modifier was not added")
            # Python runs this test inside a timer callback, so Blender has not
            # yet returned to the event loop to commit the operator's automatic
            # UNDO boundary. Push the same post-operator state explicitly.
            bpy.ops.ed.undo_push(message="After topology helper")
            if bpy.ops.ed.undo() != {"FINISHED"}:
                raise AssertionError("undo operator failed")

            restored = bpy.context.view_layer.objects.active
            if restored is None:
                raise AssertionError("active object was lost after undo")
            if len(restored.modifiers) != 2:
                raise AssertionError("topology modifier survived undo")
            if [modifier.type for modifier in restored.modifiers] != [
                    "SIMPLE_DEFORM", "SIMPLE_DEFORM"]:
                raise AssertionError("Simple Deform stack changed after undo")

            stages = importlib.import_module(f"{PACKAGE}.stages").StageCache
            if not stages.rebuild(bpy.context, restored):
                raise AssertionError("stage rebuild failed after undo")
            if len(stages.stages_for(restored)) != 2:
                raise AssertionError("stage count was not restored after undo")

            # Cage Deform creates a modifier, node group, and controller
            # object as one undoable action.
            bpy.ops.ed.undo_push(message="Before cage deform")
            if bpy.ops.sdh.add_cage_deform() != {"FINISHED"}:
                raise AssertionError("cage deform operator failed")
            cage_module = importlib.import_module(f"{PACKAGE}.cage_deform")
            if len(cage_module.cage_modifiers(restored)) != 1:
                raise AssertionError("cage deform modifier was not added")
            if not any(cage_module.is_cage_controller(obj) for obj in bpy.data.objects):
                raise AssertionError("cage controller was not added")
            bpy.ops.ed.undo_push(message="After cage deform")
            if bpy.ops.ed.undo() != {"FINISHED"}:
                raise AssertionError("cage deform undo failed")
            restored = bpy.context.view_layer.objects.active
            if cage_module.cage_modifiers(restored):
                raise AssertionError("cage deform modifier survived undo")
            if any(cage_module.is_cage_controller(obj) for obj in bpy.data.objects):
                raise AssertionError("cage controller survived undo")
            utils_module = importlib.import_module(f"{PACKAGE}.utils")
            if any(
                    collection.get(utils_module.CONTROL_COLLECTION_MARKER, False)
                    for collection in bpy.data.collections):
                raise AssertionError("helper collection survived cage undo")

            # Whole-stack deletion is also a single undoable N-panel action.
            if bpy.ops.sdh.add_cage_deform() != {"FINISHED"}:
                raise AssertionError("first stack-removal stage failed")
            if bpy.ops.sdh.add_cage_deform() != {"FINISHED"}:
                raise AssertionError("second stack-removal stage failed")
            bpy.ops.ed.undo_push(message="Before removing cage stack")
            if bpy.ops.sdh.remove_cage_stack() != {"FINISHED"}:
                raise AssertionError("whole-stack removal failed")
            if cage_module.cage_modifiers(restored):
                raise AssertionError("whole-stack removal left modifiers")
            bpy.ops.ed.undo_push(message="After removing cage stack")
            if bpy.ops.ed.undo() != {"FINISHED"}:
                raise AssertionError("whole-stack removal undo failed")
            restored = bpy.context.view_layer.objects.active
            if len(cage_module.cage_modifiers(restored)) != 2:
                raise AssertionError("whole-stack undo did not restore both stages")
            if len([
                    item for item in bpy.data.objects
                    if cage_module.is_cage_controller(item) and item.parent == restored
            ]) != 2:
                raise AssertionError("whole-stack undo did not restore both controllers")
            if bpy.ops.sdh.remove_cage_stack() != {"FINISHED"}:
                raise AssertionError("whole-stack cleanup failed")

    except Exception:
        result = "FAIL\n" + traceback.format_exc()
    finally:
        if addon is not None:
            try:
                addon.unregister()
            except Exception:
                result += "\nUNREGISTER FAIL\n" + traceback.format_exc()
        if addon_entry is not None:
            try:
                bpy.context.preferences.addons.remove(addon_entry)
            except Exception:
                result += "\nPREFERENCES CLEANUP FAIL\n" + traceback.format_exc()
        RESULT.write_text(result, encoding="utf-8")
        print(f"SDH::GUI_UNDO::{result.splitlines()[0]}")
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run_test, first_interval=0.5)
