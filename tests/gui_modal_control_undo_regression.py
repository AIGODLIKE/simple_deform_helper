"""Window-context undo coverage for FFD and Curve modal controls."""

import importlib
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

import bpy
from mathutils import Vector


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
        area = next(item for item in window.screen.areas if item.type == "VIEW_3D")
        region = next(item for item in area.regions if item.type == "WINDOW")
        with bpy.context.temp_override(window=window, area=area, region=region):
            addon_entry = bpy.context.preferences.addons.new()
            addon_entry.module = PACKAGE
            addon = importlib.import_module(PACKAGE)
            addon.register()
            core = importlib.import_module(f"{PACKAGE}.cage_deform.core")
            curve = importlib.import_module(f"{PACKAGE}.cage_deform.curve")

            def add_cage(cage_type, label):
                bpy.ops.mesh.primitive_cube_add()
                target = bpy.context.object
                target.name = f"Modal Undo {label}"
                bpy.ops.ed.undo_push(message=f"Before {label} cage")
                if bpy.ops.sdh.add_cage_deform(cage_type=cage_type) != {"FINISHED"}:
                    raise AssertionError(f"failed to add {label} cage")
                controller = bpy.context.object
                target = core.find_target(controller)
                stages = core.cage_modifiers(target)
                if len(stages) != 1:
                    raise AssertionError(f"{label} cage stage was not created")
                modifier = stages[0]
                controller = core.find_controller(target, modifier)
                return target.name, target, modifier, controller

            def restored_stage(target_name):
                target = bpy.data.objects.get(target_name)
                if target is None:
                    raise AssertionError(f"target {target_name!r} disappeared")
                stages = core.cage_modifiers(target)
                if len(stages) != 1:
                    raise AssertionError(
                        f"expected one restored cage on {target_name!r}, got {len(stages)}")
                modifier = stages[0]
                controller = core.find_controller(target, modifier)
                if controller is None:
                    raise AssertionError(f"controller for {target_name!r} disappeared")
                return target, modifier, controller

            def ffd_case(mode, axis):
                label = f"FFD {mode}"
                target_name, _target, _modifier, controller = add_cage("FFD", label)
                properties = controller.sdh_cage_deform
                core.ensure_ffd_point_collection(properties)
                indices = core.ffd_selection_indices(
                    properties, 0, mode, axis=axis)
                expected_count = {"POINT": 1, "LINE": 2, "FACE": 4}[mode]
                if len(indices) != expected_count:
                    raise AssertionError(
                        f"{mode} selected {len(indices)} points, expected {expected_count}")
                core.ffd_set_selection(properties, indices, active=indices[0])
                before = {
                    index: Vector(properties.ffd_points[index].offset)
                    for index in indices
                }
                if bpy.ops.sdh.box_select_ffd_points(
                        "INVOKE_DEFAULT",
                        controller_name=controller.name,
                        toggle=False,
                ) != {"RUNNING_MODAL"}:
                    raise AssertionError(f"{mode} editor did not start")
                operator = core._FFD_MODAL_OPERATORS[-1]
                event = SimpleNamespace(mouse_region_x=200, mouse_region_y=200)
                if not operator._begin_transform(
                        bpy.context, event, "MOVE", initial_mouse=(200, 200)):
                    raise AssertionError(f"{mode} transform did not begin")
                values = {
                    index: point.copy()
                    for index, point in operator._transform_initial_points.items()
                }
                for index in indices:
                    values[index] += Vector((0.25, 0.0, 0.0))
                if not operator._write_transform_points(
                        bpy.context, properties, values):
                    raise AssertionError(f"{mode} transform did not write")
                operator._finish_transform(bpy.context, properties)
                if not any(
                        (Vector(properties.ffd_points[index].offset) - value).length > 1.0e-5
                        for index, value in before.items()):
                    raise AssertionError(f"{mode} transform changed no FFD points")
                if bpy.ops.ed.undo() != {"FINISHED"}:
                    raise AssertionError(f"{mode} control undo failed")
                _target, _modifier, restored = restored_stage(target_name)
                restored_properties = restored.sdh_cage_deform
                for index, value in before.items():
                    if (
                            Vector(restored_properties.ffd_points[index].offset) - value
                    ).length > 1.0e-6:
                        raise AssertionError(f"{mode} undo did not restore point {index}")
                core.finish_ffd_edit_sessions(
                    bpy.context, restore_target=False)

            target_name, _target, _modifier, controller = add_cage(
                "FFD", "FFD No Motion")
            properties = controller.sdh_cage_deform
            core.ensure_ffd_point_collection(properties)
            core.ffd_set_selection(properties, (0,), active=0)
            if bpy.ops.sdh.box_select_ffd_points(
                    "INVOKE_DEFAULT",
                    controller_name=controller.name,
                    toggle=False,
            ) != {"RUNNING_MODAL"}:
                raise AssertionError("motionless FFD editor did not start")
            operator = core._FFD_MODAL_OPERATORS[-1]
            event = SimpleNamespace(mouse_region_x=200, mouse_region_y=200)
            if not operator._begin_transform(
                    bpy.context, event, "MOVE", initial_mouse=(200, 200)):
                raise AssertionError("motionless FFD transform did not begin")
            operator._finish_transform(bpy.context, properties)
            undo_module = importlib.import_module(
                f"{PACKAGE}.cage_deform.undo")
            if undo_module.ACTIVE_TRANSACTIONS:
                raise AssertionError("motionless FFD transform left an active transaction")
            if bpy.ops.ed.undo() != {"FINISHED"}:
                raise AssertionError("motionless FFD undo failed")
            target = bpy.context.view_layer.objects.active
            if core.is_cage_controller(target):
                target = core.find_target(target)
            if target is not None and core.cage_modifiers(target):
                raise AssertionError("motionless FFD transform created an undo record")
            core.finish_ffd_edit_sessions(
                bpy.context, restore_target=False)

            ffd_case("POINT", None)
            ffd_case("LINE", "U")
            ffd_case("FACE", "UW")

            target_name, _target, _modifier, controller = add_cage(
                "CURVE", "Curve Point")
            properties = controller.sdh_cage_deform
            guide, _stations = curve.ensure_curve_companions(
                _target, _modifier, controller)
            spline = curve.curve_guide_spline(guide)
            curve.ensure_curve_point_collection(properties, guide)
            properties.curve_active_point = 0
            for index, item in enumerate(properties.curve_points):
                item.selected = index == 0
            before = Vector(spline.bezier_points[0].co)
            if bpy.ops.sdh.edit_curve_cage_object(
                    "INVOKE_DEFAULT",
                    controller_uuid=str(controller.get(core.CONTROLLER_UUID, "")),
                    toggle=False,
            ) != {"RUNNING_MODAL"}:
                raise AssertionError("Curve point editor did not start")
            operator = curve._CURVE_MODAL_OPERATORS[-1]
            start = SimpleNamespace(mouse_region_x=200, mouse_region_y=200)
            moved = SimpleNamespace(
                mouse_region_x=250, mouse_region_y=215,
                shift=False, ctrl=False, alt=False)
            if not operator._begin_transform(
                    bpy.context, start, "MOVE", kind="POINT", index=0):
                raise AssertionError("Curve point transform did not begin")
            if not operator._apply_transform(bpy.context, moved):
                raise AssertionError("Curve point transform did not write")
            operator._finish_transform(bpy.context)
            if (Vector(spline.bezier_points[0].co) - before).length <= 1.0e-5:
                raise AssertionError("Curve point transform changed no point")
            if bpy.ops.ed.undo() != {"FINISHED"}:
                raise AssertionError("Curve point control undo failed")
            target, modifier, restored = restored_stage(target_name)
            guide = curve.curve_guide_object(target, modifier)
            spline = curve.curve_guide_spline(guide)
            if (Vector(spline.bezier_points[0].co) - before).length > 1.0e-6:
                raise AssertionError("Curve point undo did not restore the guide")
            curve.finish_curve_object_edit_sessions(
                bpy.context, restore_target=False)

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
        print(f"SDH::MODAL_CONTROL_UNDO::{result.splitlines()[0]}")
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run_test, first_interval=0.5)
