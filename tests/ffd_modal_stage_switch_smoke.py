"""Exercise cross-stage FFD modal switching in a real VIEW_3D area."""
from __future__ import annotations

import importlib
import os
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

import bpy
from bpy_extras import view3d_utils


SOURCE = Path(__file__).resolve().parents[1]
RESULT = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
INSTALLED_PACKAGE = os.environ.get("SDH_TEST_MODULE")
PACKAGE = INSTALLED_PACKAGE or SOURCE.name
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(SOURCE.parent))


def finish(value):
    RESULT.write_text(value, encoding="utf-8")
    try:
        if "core" in globals():
            core.finish_ffd_edit_sessions(bpy.context, restore_target=False)
    except Exception:
        pass

    def quit_after_startup():
        bpy.ops.wm.quit_blender()
        return None

    bpy.app.timers.register(quit_after_startup, first_interval=0.05)
    return None


def event_at(region, point, *, event_type="LEFTMOUSE", value="PRESS"):
    x = int(round(point.x))
    y = int(round(point.y))
    return SimpleNamespace(
        type=event_type,
        value=value,
        mouse_region_x=x,
        mouse_region_y=y,
        mouse_x=region.x + x,
        mouse_y=region.y + y,
        shift=False,
        ctrl=False,
        alt=False,
    )


try:
    package = PACKAGE
    addon = importlib.import_module(package)
    if not INSTALLED_PACKAGE:
        entry = bpy.context.preferences.addons.new()
        entry.module = package
        addon.register()
    cage = importlib.import_module(f"{package}.cage_deform")
    core = cage.core
    gizmos = importlib.import_module(f"{package}.cage_deform.gizmos")

    bpy.ops.mesh.primitive_cube_add()
    target = bpy.context.object

    stages = []
    for cage_type in ("FFD", "FFD", "STANDARD"):
        if bpy.ops.sdh.add_cage_deform(cage_type=cage_type) != {"FINISHED"}:
            raise RuntimeError(f"could not create {cage_type} stage")
        modifier = target.modifiers.active
        controller = cage.find_controller(target, modifier)
        if controller is None:
            raise RuntimeError(f"could not resolve {cage_type} controller")
        controller.sdh_cage_deform.show_other_cages = True
        controller.sdh_cage_deform.show_cage = True
        stages.append((modifier, controller))

    first_modifier, first_controller = stages[0]
    second_modifier, second_controller = stages[1]
    standard_modifier, standard_controller = stages[2]
    second_controller.location.x += 1.5
    standard_controller.location.x -= 1.5
    cage.sync_controller(second_controller, pull_transform=False)
    cage.sync_controller(standard_controller, pull_transform=False)

    window = bpy.context.window_manager.windows[0]
    area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    region = next(region for region in area.regions if region.type == "WINDOW")
    space = area.spaces.active
    target.modifiers.active = first_modifier
    bpy.context.view_layer.objects.active = target
    target.select_set(True)

    with bpy.context.temp_override(
            window=window, area=area, region=region, space_data=space):
        # The standard B box-select entry starts as a temporary picker. It must
        # not enter edit mode until it actually selects a visible FFD entity.
        first_properties = first_controller.sdh_cage_deform
        first_properties.ffd_selection_modes = {"POINT"}
        first_properties.ffd_edit_mode_active = False
        result = bpy.ops.sdh.box_select_ffd_points(
            "INVOKE_DEFAULT",
            controller_name=first_controller.name,
            toggle=False,
            arm_box_select=True,
        )
        if "RUNNING_MODAL" not in result:
            raise RuntimeError(
                f"pre-edit FFD box picker did not start: {result!r}")
        if first_properties.ffd_edit_mode_active:
            raise RuntimeError("pre-edit FFD box picker entered edit mode early")
        if len(core._FFD_MODAL_OPERATORS) != 1:
            raise RuntimeError("pre-edit FFD box picker did not register a session")
        pre_edit_operator = core._FFD_MODAL_OPERATORS[0]
        if pre_edit_operator._state != "BOX_READY":
            raise RuntimeError("B FFD box picker did not arm before its drag")
        first_world = pre_edit_operator._point_world(
            target, first_controller, first_properties, 7)
        first_screen = view3d_utils.location_3d_to_region_2d(
            region, space.region_3d, first_world)
        if first_screen is None:
            raise RuntimeError("pre-edit FFD point is outside the viewport")
        start_screen = first_screen.copy()
        start_screen.x -= 12.0
        start_screen.y -= 12.0
        press_result = pre_edit_operator.modal(
            bpy.context, event_at(region, start_screen))
        if "RUNNING_MODAL" not in press_result or pre_edit_operator._state != "DRAGGING":
            raise RuntimeError("B FFD box picker did not begin its drag")
        pre_edit_operator.modal(
            bpy.context, event_at(
                region, first_screen, event_type="MOUSEMOVE", value="NOTHING"))
        release_result = pre_edit_operator.modal(
            bpy.context, event_at(region, first_screen, value="RELEASE"))
        if "RUNNING_MODAL" not in release_result:
            raise RuntimeError(
                f"pre-edit FFD box selection did not finish: {release_result!r}")
        if not first_properties.ffd_edit_mode_active:
            raise RuntimeError("pre-edit FFD box selection did not enter edit mode")
        if not first_properties.ffd_points[7].selected:
            raise RuntimeError("pre-edit FFD box selection did not select its point")
        core.finish_ffd_edit_sessions(bpy.context, restore_target=False)
        if core._FFD_MODAL_OPERATORS or first_properties.ffd_edit_mode_active:
            raise RuntimeError("pre-edit FFD box selection did not cleanly exit")
        core._activate(bpy.context, target)
        target.modifiers.active = first_modifier

        result = bpy.ops.sdh.box_select_ffd_points(
            "INVOKE_DEFAULT",
            controller_name=first_controller.name,
            toggle=False,
        )
        if "RUNNING_MODAL" not in result:
            raise RuntimeError(f"first FFD editor did not start: {result!r}")
        if len(core._FFD_MODAL_OPERATORS) != 1:
            raise RuntimeError("first FFD editor did not register one session")
        first_operator = core._FFD_MODAL_OPERATORS[0]

        second_properties = second_controller.sdh_cage_deform
        second_world = first_operator._point_world(
            target, second_controller, second_properties, 7)
        second_screen = view3d_utils.location_3d_to_region_2d(
            region, space.region_3d, second_world)
        if second_screen is None:
            raise RuntimeError("second FFD point is outside the viewport")
        second_event = event_at(region, second_screen)
        picked = first_operator._other_ffd_selection_at_event(
            bpy.context, second_event)
        if picked is None or picked[1] != second_controller:
            raise RuntimeError("clicking the second FFD point did not hit it")
        if not first_operator._switch_ffd_stage_from_event(
                bpy.context, second_event, *picked):
            raise RuntimeError("clicking the second FFD point did not switch")
        if len(core._FFD_MODAL_OPERATORS) != 1:
            raise RuntimeError("FFD switch did not replace the modal session")
        second_operator = core._FFD_MODAL_OPERATORS[0]
        if second_operator._controller() != second_controller:
            raise RuntimeError("replacement FFD editor owns the wrong cage")
        if first_controller.sdh_cage_deform.ffd_edit_mode_active:
            raise RuntimeError("first FFD remained in edit mode after switch")
        if not second_properties.ffd_edit_mode_active:
            raise RuntimeError("second FFD did not enter edit mode")

        release_result = second_operator.modal(
            bpy.context, event_at(region, second_screen, value="RELEASE"))
        if "RUNNING_MODAL" not in release_result:
            raise RuntimeError("replacement FFD pointer drag did not finish")

        standard_world = gizmos.parameter_handle_world(
            bpy.context, target, standard_controller, "BEND", separate=True)
        standard_screen = view3d_utils.location_3d_to_region_2d(
            region, space.region_3d, standard_world)
        if standard_screen is None:
            raise RuntimeError("standard cage handle is outside the viewport")
        standard_event = event_at(region, standard_screen)
        other_stage = second_operator._other_stage_gizmo_at_event(
            bpy.context, standard_event)
        if other_stage is None or other_stage[1] != standard_controller:
            raise RuntimeError("standard cage Gizmo was not detected")
        exit_result = second_operator.modal(bpy.context, standard_event)
        if "PASS_THROUGH" not in exit_result:
            raise RuntimeError(
                f"standard cage click was not passed through: {exit_result!r}")
        if core._FFD_MODAL_OPERATORS or second_properties.ffd_edit_mode_active:
            raise RuntimeError("standard cage click left the FFD editor active")

    finish("PASS::FFD_A_TO_FFD_B::FFD_TO_STANDARD_EXIT")
except Exception:
    finish("FAIL:\n" + traceback.format_exc())
