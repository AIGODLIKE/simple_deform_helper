"""Keep the first pre-edit box selection alive after creating FFD/Curve cages."""
from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
RESULT = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
sys.path.insert(0, str(SOURCE.parent))


def finish(value):
    RESULT.write_text(value, encoding="utf-8")

    def quit_blender():
        bpy.ops.wm.quit_blender()
        return None

    bpy.app.timers.register(quit_blender, first_interval=0.05)


addon = None
try:
    addon = importlib.import_module(PACKAGE)
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon.register()
    cage = importlib.import_module(f"{PACKAGE}.cage_deform")
    core = cage.core
    curve = importlib.import_module(f"{PACKAGE}.cage_deform.curve")

    window = bpy.context.window_manager.windows[0]
    area = next(item for item in window.screen.areas if item.type == "VIEW_3D")
    region = next(item for item in area.regions if item.type == "WINDOW")
    space = area.spaces.active
    expected_tools = {
        "FFD": core._FFD_WORKSPACE_TOOL_ID,
        "CURVE": core._CURVE_WORKSPACE_TOOL_ID,
    }

    with bpy.context.temp_override(
            window=window, area=area, region=region, space_data=space):
        for index, cage_type in enumerate(("FFD", "CURVE")):
            bpy.ops.object.select_all(action="DESELECT")
            bpy.ops.mesh.primitive_cube_add(location=(index * 4.0, 0.0, 0.0))
            target = bpy.context.object
            target.name = f"First External {cage_type} Target"
            if bpy.ops.sdh.add_cage_deform(
                    cage_type=cage_type) != {"FINISHED"}:
                raise AssertionError(f"could not create the first {cage_type} cage")
            modifier = target.modifiers.active
            controller = cage.find_controller(target, modifier)
            if controller is None:
                raise AssertionError(f"{cage_type} controller was not created")

            if bpy.context.view_layer.objects.active != target:
                raise AssertionError(
                    f"first {cage_type} creation exposed its controller as active")
            if not target.select_get() or not controller.select_get():
                raise AssertionError(
                    f"first {cage_type} creation did not select target and controller")

            # Reproduce the deferred selection pass that used to restore the
            # native tool before the user's first blank drag reached the cage.
            core._SELECTION_SYNC_SIGNATURE = None
            core._SELECTION_SYNC_DIRTY = True
            for _pass in range(3):
                core._selection_sync_timer()
            if core._active_workspace_tool_id(
                    bpy.context) != expected_tools[cage_type]:
                raise AssertionError(
                    f"first {cage_type} selection sync dropped its Workspace Tool")

            if cage_type == "FFD":
                if not core.SDH_OT_box_select_ffd_points.poll(bpy.context):
                    raise AssertionError(
                        "first external FFD editor poll failed; "
                        f"area={getattr(bpy.context.area, 'type', None)!r}, "
                        f"active={getattr(bpy.context.view_layer.objects.active, 'name', None)!r}, "
                        f"selected={[obj.name for obj in bpy.context.selected_objects]!r}, "
                        f"resolved={tuple(getattr(item, 'name', None) for item in core.resolve_context_deform(bpy.context))!r}")
                result = bpy.ops.sdh.box_select_ffd_points(
                    "INVOKE_DEFAULT",
                    controller_name=controller.name,
                    start_box_select=True,
                    toggle=False,
                )
                sessions = tuple(core._FFD_MODAL_OPERATORS)
                if "RUNNING_MODAL" not in result or not sessions:
                    raise AssertionError(
                        "first external FFD box selection did not enter pre-edit")
                operator = sessions[-1]
                if (
                        operator._state != "DRAGGING" or
                        not operator._pre_edit_box_select
                ):
                    raise AssertionError(
                        "first external FFD box selection lost its drag state")
                core.finish_ffd_edit_sessions(
                    bpy.context, restore_target=False)
            else:
                result = bpy.ops.sdh.edit_curve_cage_object(
                    "INVOKE_DEFAULT",
                    controller_uuid=str(controller.get(
                        core.CONTROLLER_UUID, "")),
                    start_box_select=True,
                    toggle=False,
                )
                sessions = tuple(curve._CURVE_MODAL_OPERATORS)
                if "RUNNING_MODAL" not in result or not sessions:
                    raise AssertionError(
                        "first external Curve box selection did not enter pre-edit")
                operator = sessions[-1]
                if (
                        operator._state != "DRAGGING" or
                        not operator._pre_edit_box_select
                ):
                    raise AssertionError(
                        "first external Curve box selection lost its drag state")
                curve.finish_curve_object_edit_sessions(
                    bpy.context, restore_target=False)

    addon.unregister()
    addon = None
    finish("PASS::FIRST_EXTERNAL_BOX_SELECT")
except Exception:
    try:
        if addon is not None:
            addon.unregister()
    except Exception:
        pass
    finish("FAIL:\n" + traceback.format_exc())
