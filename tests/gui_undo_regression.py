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
            obj.modifiers.new("Undo Twist", "SIMPLE_DEFORM")
            obj.modifiers.active = first
            restored = obj

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

            # Cage Gizmos write controller RNA directly.  Their explicit
            # before/after snapshots must make the first undo restore only the
            # dragged value, leaving the just-created cage intact.
            cage_stage = cage_module.cage_modifiers(restored)[0]
            cage_controller = cage_module.find_controller(restored, cage_stage)
            cage_properties = cage_controller.sdh_cage_deform
            initial_bend = float(cage_properties.bend_strength)
            gizmo_module = importlib.import_module(
                f"{PACKAGE}.cage_deform.gizmos")
            transaction = object()
            if not gizmo_module._SDHCageParameterGizmo._set_float_if_changed(
                    transaction,
                    cage_properties,
                    "bend_strength",
                    initial_bend + 0.5,
                    bpy.context,
            ):
                raise AssertionError("cage control did not write its value")
            gizmo_module._finish_gizmo_undo(
                transaction, message="Cage Bend Angle")
            if bpy.ops.ed.undo() != {"FINISHED"}:
                raise AssertionError("cage control undo failed")
            restored_active = bpy.context.view_layer.objects.active
            restored = (
                cage_module.find_target(restored_active)
                if cage_module.is_cage_controller(restored_active)
                else restored_active
            )
            restored_stages = cage_module.cage_modifiers(restored)
            if len(restored_stages) != 1:
                raise AssertionError(
                    "cage control undo removed the newly-created cage")
            restored_controller = cage_module.find_controller(
                restored, restored_stages[0])
            if abs(
                    float(restored_controller.sdh_cage_deform.bend_strength) -
                    initial_bend
            ) > 1.0e-6:
                raise AssertionError(
                    "cage control undo did not restore the previous value")

            # The next undo is still the cage-creation action.
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
            restored_active = bpy.context.view_layer.objects.active
            restored = (
                cage_module.find_target(restored_active)
                if cage_module.is_cage_controller(restored_active)
                else restored_active
            )
            if restored is None:
                raise AssertionError("whole-stack undo lost the cage target")
            restored_stages = cage_module.cage_modifiers(restored)
            restored_controllers = [
                    item for item in bpy.data.objects
                    if cage_module.is_cage_controller(item) and item.parent == restored
            ]
            if len(restored_stages) != 2:
                raise AssertionError(
                    "whole-stack undo did not restore both stages: "
                    f"active={getattr(restored, 'name', None)!r}, "
                    f"stages={[item.name for item in restored_stages]!r}, "
                    f"controllers={[item.name for item in restored_controllers]!r}")
            if len(restored_controllers) != 2:
                raise AssertionError(
                    "whole-stack undo did not restore both controllers: "
                    f"{[item.name for item in restored_controllers]!r}")
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
