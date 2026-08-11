"""Verify the scoped FFD Workspace Tool and add-on-owned shortcut."""
from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

import bpy


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
    core = importlib.import_module(f"{PACKAGE}.cage_deform.core")
    cage = importlib.import_module(f"{PACKAGE}.cage_deform")

    if not core._FFD_WORKSPACE_TOOL_REGISTERED:
        raise RuntimeError("FFD Workspace Tool was not registered")

    addon_keyconfig = bpy.context.window_manager.keyconfigs.addon
    addon_items = tuple(
        (keymap, item)
        for keymap in addon_keyconfig.keymaps
        for item in keymap.keymap_items
        if item.idname == "sdh.box_select_ffd_points"
    )
    b_bindings = tuple(
        item for item in core.SDH_WST_ffd_edit.bl_keymap
        if item[0] == "sdh.box_select_ffd_points" and
        item[1].get("type") == "B" and item[1].get("value") == "PRESS"
    )
    if len(b_bindings) != 1:
        raise RuntimeError(
            f"expected one scoped FFD B shortcut, got {len(b_bindings)}")
    drag_items = tuple(
        (keymap, item) for keymap, item in addon_items
        if item.type == "LEFTMOUSE" and item.value == "CLICK_DRAG"
    )
    if len(drag_items) != 4:
        raise RuntimeError(
            f"expected four Workspace Tool drag variants, got {len(drag_items)}")
    forbidden_keymaps = {
        "3D View Tool: Select Box",
        "3D View Tool: Select Box (fallback)",
    }
    if any(keymap.name in forbidden_keymaps for keymap, _item in addon_items):
        raise RuntimeError("FFD entries were injected into Blender's Select Box tool")

    window = bpy.context.window_manager.windows[0]
    area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    region = next(region for region in area.regions if region.type == "WINDOW")
    space = area.spaces.active
    with bpy.context.temp_override(
            window=window, area=area, region=region, space_data=space):
        bpy.ops.mesh.primitive_cube_add()
        target = bpy.context.object
        initial_tool = bpy.context.workspace.tools.from_space_view3d_mode(
            "OBJECT", create=False)
        initial_tool_id = getattr(initial_tool, "idname", "builtin.select_box")
        if bpy.ops.sdh.add_cage_deform(cage_type="FFD") != {"FINISHED"}:
            raise RuntimeError("could not create the FFD stage")
        modifier = target.modifiers.active
        controller = cage.find_controller(target, modifier)
        if controller is None:
            raise RuntimeError("could not resolve the FFD controller")
        active_tool = bpy.context.workspace.tools.from_space_view3d_mode(
            "OBJECT", create=False)
        if getattr(active_tool, "idname", "") != core._FFD_WORKSPACE_TOOL_ID:
            raise RuntimeError("creating FFD did not activate its Workspace Tool")

        if bpy.ops.sdh.add_cage_deform(cage_type="STANDARD") != {"FINISHED"}:
            raise RuntimeError("could not create the Standard stage")
        active_tool = bpy.context.workspace.tools.from_space_view3d_mode(
            "OBJECT", create=False)
        if getattr(active_tool, "idname", "") != initial_tool_id:
            raise RuntimeError("leaving FFD did not restore the prior Workspace Tool")

        # Reproduce the video path: a Standard cage is active, then an
        # inactive FFD control is pressed directly in the viewport. Entering
        # the FFD modal must switch stages and repair Blender's late
        # active-but-unselected target result without another mouse click.
        standard_modifier = target.modifiers.active
        target.modifiers.active = modifier
        if not core._activate_ffd_edit_selection(
                bpy.context, target, controller):
            raise RuntimeError("inactive FFD Gizmo could not prepare its stage")
        if not core.SDH_OT_box_select_ffd_points.poll(bpy.context):
            raise RuntimeError(
                "inactive FFD editor poll failed; "
                f"area={getattr(bpy.context.area, 'type', None)!r}, "
                f"active={getattr(bpy.context.view_layer.objects.active, 'name', None)!r}, "
                f"selected={[obj.name for obj in bpy.context.selected_objects]!r}, "
                f"resolved={tuple(getattr(item, 'name', None) for item in core.resolve_context_deform(bpy.context))!r}")
        direct_result = bpy.ops.sdh.box_select_ffd_points(
            "INVOKE_DEFAULT",
            controller_name=controller.name,
            toggle=False,
            start_drag=True,
            start_anchor=0,
            start_selection_mode="POINT",
            start_selection_axis="POINT",
            start_mouse_region_x=0,
            start_mouse_region_y=0,
        )
        if "RUNNING_MODAL" not in direct_result:
            raise RuntimeError(
                f"inactive FFD control did not start editing: {direct_result!r}")
        if target.modifiers.active != modifier:
            raise RuntimeError("inactive FFD control did not switch cage stages")
        bpy.ops.object.select_all(action="DESELECT")
        target.select_set(False)
        bpy.context.view_layer.objects.active = target
        core._SELECTION_SYNC_SIGNATURE = None
        core._selection_sync_timer()
        core._selection_sync_timer()
        if bpy.context.view_layer.objects.active != target or not target.select_get():
            raise RuntimeError("inactive FFD click left the target unselected")
        if not controller.select_get():
            raise RuntimeError("inactive FFD click did not restore its controller")
        core.finish_ffd_edit_sessions(bpy.context, restore_target=False)
        target.modifiers.active = standard_modifier
        core._activate(bpy.context, target)
        core.refresh_controller_display(bpy.context, force=True)
        core.deactivate_ffd_workspace_tool(bpy.context)

        if bpy.ops.sdh.select_cage_stage(index=0) != {"FINISHED"}:
            raise RuntimeError("could not reselect the FFD stage")
        active_tool = bpy.context.workspace.tools.from_space_view3d_mode(
            "OBJECT", create=False)
        if getattr(active_tool, "idname", "") != core._FFD_WORKSPACE_TOOL_ID:
            raise RuntimeError("selecting FFD did not reactivate its Workspace Tool")
        if bpy.context.view_layer.objects.active != target or not target.select_get():
            raise RuntimeError("selecting FFD did not keep the target active")
        stage_controllers = tuple(
            cage.find_controller(target, stage_modifier)
            for stage_modifier in cage.cage_modifiers(target)
        )
        if any(
                stage_controller is None or not stage_controller.select_get()
                for stage_controller in stage_controllers
        ):
            raise RuntimeError("selecting FFD hid another cage controller")

        # Reproduce Blender's late object-pick result after clicking an
        # inactive FFD cage: the helper Empty briefly becomes the sole active
        # selection after the stage operator has returned.
        bpy.ops.object.select_all(action="DESELECT")
        target.select_set(False)
        bpy.context.view_layer.objects.active = target
        core._queue_stage_selection_restore(target, modifier)
        core._SELECTION_SYNC_SIGNATURE = None
        core._selection_sync_timer()
        core._selection_sync_timer()
        if bpy.context.view_layer.objects.active != target or not target.select_get():
            raise RuntimeError("FFD tool did not restore the controlled target")
        if any(
                stage_controller is None or not stage_controller.select_get()
                for stage_controller in stage_controllers
        ):
            raise RuntimeError("FFD target restoration did not restore all cages")

        result = bpy.ops.sdh.box_select_ffd_points(
            "INVOKE_DEFAULT",
            controller_name=controller.name,
            toggle=False,
        )
        if "RUNNING_MODAL" not in result:
            raise RuntimeError(f"FFD editor did not start: {result!r}")
        active_tool = bpy.context.workspace.tools.from_space_view3d_mode(
            "OBJECT", create=False)
        if getattr(active_tool, "idname", "") != core._FFD_WORKSPACE_TOOL_ID:
            raise RuntimeError("starting FFD editing did not activate its Workspace Tool")
        core.finish_ffd_edit_sessions(bpy.context, restore_target=False)

        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = None
        core._selection_sync_timer()
        active_tool = bpy.context.workspace.tools.from_space_view3d_mode(
            "OBJECT", create=False)
        if getattr(active_tool, "idname", "") != initial_tool_id:
            raise RuntimeError(
                "empty selection did not release the FFD Workspace Tool")

        target.select_set(True)
        bpy.context.view_layer.objects.active = target
        target.modifiers.active = modifier
        core._selection_sync_timer()
        active_tool = bpy.context.workspace.tools.from_space_view3d_mode(
            "OBJECT", create=False)
        if getattr(active_tool, "idname", "") != core._FFD_WORKSPACE_TOOL_ID:
            raise RuntimeError(
                "reselecting the FFD target did not restore its Workspace Tool")

        if not core.deactivate_ffd_workspace_tool(bpy.context):
            raise RuntimeError("FFD Workspace Tool did not restore its predecessor")
        active_tool = bpy.context.workspace.tools.from_space_view3d_mode(
            "OBJECT", create=False)
        if getattr(active_tool, "idname", "") != initial_tool_id:
            raise RuntimeError("FFD Workspace Tool restored the wrong predecessor")

    addon.unregister()
    remaining = tuple(
        item
        for keymap in addon_keyconfig.keymaps
        for item in keymap.keymap_items
        if item.idname == "sdh.box_select_ffd_points"
    )
    if remaining:
        raise RuntimeError("FFD leaked a global shortcut")
    if core._FFD_WORKSPACE_TOOL_REGISTERED:
        raise RuntimeError("FFD Workspace Tool survived unregister")
    finish("PASS::FFD_WORKSPACE_TOOL::ADDON_KEYMAP_CLEAN")
except Exception:
    finish("FAIL:\n" + traceback.format_exc())
