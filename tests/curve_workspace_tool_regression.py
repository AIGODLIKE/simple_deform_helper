"""Verify Curve controls can enter Object Edit from outside its modal."""
from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

import bpy
from bpy_extras import view3d_utils
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
RESULT = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))


def finish(value):
    RESULT.write_text(value, encoding="utf-8")

    def quit_blender():
        bpy.ops.wm.quit_blender()
        return None

    bpy.app.timers.register(quit_blender, first_interval=0.05)


try:
    addon = importlib.import_module(PACKAGE)
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon.register()
    cage = importlib.import_module(f"{PACKAGE}.cage_deform")
    core = cage.core
    curve = importlib.import_module(f"{PACKAGE}.cage_deform.curve")

    if not core._CURVE_WORKSPACE_TOOL_REGISTERED:
        raise RuntimeError("Curve Workspace Tool was not registered")
    drag_items = tuple(
        item for item in core.SDH_WST_curve_edit.bl_keymap
        if item[0] == "sdh.edit_curve_cage_object" and
        item[1].get("value") == "CLICK_DRAG"
    )
    if len(drag_items) != 4:
        raise RuntimeError(
            f"expected four Curve drag variants, got {len(drag_items)}")
    curve_b_bindings = tuple(
        item for item in core.SDH_WST_curve_edit.bl_keymap
        if item[0] == "sdh.edit_curve_cage_object" and
        item[1].get("type") == "B" and item[1].get("value") == "PRESS"
    )
    if len(curve_b_bindings) != 1:
        raise RuntimeError(
            f"expected one scoped Curve B shortcut, got {len(curve_b_bindings)}")

    window = bpy.context.window_manager.windows[0]
    area = next(item for item in window.screen.areas if item.type == "VIEW_3D")
    region = next(item for item in area.regions if item.type == "WINDOW")
    space = area.spaces.active
    region_data = space.region_3d
    with bpy.context.temp_override(
            window=window, area=area, region=region, space_data=space):
        bpy.ops.mesh.primitive_cube_add()
        target = bpy.context.object
        initial_tool = bpy.context.workspace.tools.from_space_view3d_mode(
            "OBJECT", create=False)
        initial_tool_id = getattr(
            initial_tool, "idname", "builtin.select_box")
        if bpy.ops.sdh.add_cage_deform(cage_type="CURVE") != {"FINISHED"}:
            raise RuntimeError("could not create Curve cage")
        modifier = target.modifiers.active
        controller = cage.find_controller(target, modifier)
        guide = curve.curve_guide_object(target, modifier)
        spline = curve.curve_guide_spline(guide)
        if controller is None or spline is None:
            raise RuntimeError("could not resolve Curve controls")
        active_tool = bpy.context.workspace.tools.from_space_view3d_mode(
            "OBJECT", create=False)
        if getattr(active_tool, "idname", "") != core._CURVE_WORKSPACE_TOOL_ID:
            raise RuntimeError("creating Curve did not activate its Workspace Tool")

        result = bpy.ops.sdh.edit_curve_cage_object(
            "INVOKE_DEFAULT",
            controller_uuid=str(controller.get(core.CONTROLLER_UUID, "")),
            toggle=False,
            start_box_select=True,
        )
        if "RUNNING_MODAL" not in result or not curve._CURVE_MODAL_OPERATORS:
            raise RuntimeError("external Curve box selection did not start")
        operator = curve._CURVE_MODAL_OPERATORS[-1]
        if operator._state != "DRAGGING" or not operator._pre_edit_box_select:
            raise RuntimeError("external Curve box selection lost pre-edit state")
        bpy.context.view_layer.update()
        projected = next((
            view3d_utils.location_3d_to_region_2d(
                region, region_data,
                guide.matrix_world @ Vector(point.co))
            for point in spline.bezier_points
            if view3d_utils.location_3d_to_region_2d(
                region, region_data,
                guide.matrix_world @ Vector(point.co)) is not None
        ), None)
        if projected is None:
            raise RuntimeError("Curve point could not be projected")
        operator._box_start = Vector(projected) - Vector((8.0, 8.0))
        box_end = Vector(projected) + Vector((8.0, 8.0))
        move = type("CurveWorkspaceMove", (), {
            "type": "INBETWEEN_MOUSEMOVE",
            "value": "NOTHING",
            "mouse_x": region.x + int(box_end.x),
            "mouse_y": region.y + int(box_end.y),
            "mouse_region_x": int(box_end.x),
            "mouse_region_y": int(box_end.y),
            "shift": False,
            "ctrl": False,
            "alt": False,
        })()
        if operator.modal(bpy.context, move) != {"RUNNING_MODAL"}:
            raise RuntimeError("external Curve box move cancelled the modal")
        release = type("CurveWorkspaceRelease", (), {
            "type": "LEFTMOUSE",
            "value": "RELEASE",
            "mouse_x": move.mouse_x,
            "mouse_y": move.mouse_y,
            "mouse_region_x": move.mouse_region_x,
            "mouse_region_y": move.mouse_region_y,
            "shift": False,
            "ctrl": False,
            "alt": False,
        })()
        if operator.modal(bpy.context, release) != {"RUNNING_MODAL"}:
            raise RuntimeError("external Curve box release ended the editor")
        if operator._state != "WAITING":
            raise RuntimeError("external Curve box did not finish selection")
        if not any(point.selected for point in controller.sdh_cage_deform.curve_points):
            raise RuntimeError("external Curve box selection selected no points")
        operator._finish_modal(bpy.context)

        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = None
        core._selection_sync_timer()
        active_tool = bpy.context.workspace.tools.from_space_view3d_mode(
            "OBJECT", create=False)
        if getattr(active_tool, "idname", "") != initial_tool_id:
            raise RuntimeError(
                "empty selection did not release the Curve Workspace Tool")

        target.select_set(True)
        bpy.context.view_layer.objects.active = target
        target.modifiers.active = modifier
        core._selection_sync_timer()
        active_tool = bpy.context.workspace.tools.from_space_view3d_mode(
            "OBJECT", create=False)
        if getattr(active_tool, "idname", "") != core._CURVE_WORKSPACE_TOOL_ID:
            raise RuntimeError(
                "reselecting the Curve target did not restore its Workspace Tool")

        if bpy.ops.sdh.add_cage_deform(cage_type="STANDARD") != {"FINISHED"}:
            raise RuntimeError("could not leave Curve for Standard cage")
        active_tool = bpy.context.workspace.tools.from_space_view3d_mode(
            "OBJECT", create=False)
        if getattr(active_tool, "idname", "") != initial_tool_id:
            raise RuntimeError("leaving Curve did not restore the previous tool")

    addon.unregister()
    if core._CURVE_WORKSPACE_TOOL_REGISTERED:
        raise RuntimeError("Curve Workspace Tool survived unregister")
    remaining = tuple(
        item
        for keymap in bpy.context.window_manager.keyconfigs.addon.keymaps
        for item in keymap.keymap_items
        if item.idname == "sdh.edit_curve_cage_object"
    )
    if remaining:
        raise RuntimeError("Curve leaked a global shortcut")
    finish("PASS::CURVE_WORKSPACE_TOOL::EXTERNAL_SELECTION")
except Exception:
    finish("FAIL:\n" + traceback.format_exc())
