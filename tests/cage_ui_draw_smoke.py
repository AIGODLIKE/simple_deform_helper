"""Open the Cage Deform sidebar briefly and fail on setup errors."""
from __future__ import annotations

import importlib
import math
import os
import sys
import traceback
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
INSTALLED_PACKAGE = os.environ.get("SDH_TEST_MODULE")
PACKAGE = INSTALLED_PACKAGE or SOURCE.name
SCRIPT_ARGS = sys.argv[sys.argv.index("--") + 1:]
RESULT = Path(SCRIPT_ARGS[0]).resolve()
SCREENSHOT = Path(SCRIPT_ARGS[1]).resolve() if len(SCRIPT_ARGS) > 1 else None
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(SOURCE.parent))


addon = None
draw_count = 0
attempts = 0
picker_setup_count = 0
picker_draw_count = 0
standard_layer_tree_draw_count = 0
mixed_stack_draw_count = 0
legacy_stage_draw_count = 0
legacy_stage_selected = False
picker_scale_errors = []
ui_draw_errors = []
screenshot_scrolled = False


def quit_with(result):
    RESULT.write_text(result, encoding="utf-8")
    bpy.ops.wm.quit_blender()
    return None


try:
    addon = importlib.import_module(PACKAGE)
    cage_module = importlib.import_module(f"{PACKAGE}.cage_deform")
    gizmos_module = importlib.import_module(f"{PACKAGE}.cage_deform.gizmos")
    picker_class = gizmos_module.SDHCageStagePickerGizmo
    original_picker_setup = picker_class.setup
    original_picker_draw = picker_class.draw

    def tracked_picker_setup(self):
        global picker_setup_count
        result = original_picker_setup(self)
        picker_setup_count += 1
        if self.use_draw_scale:
            picker_scale_errors.append("picker retained Blender draw scaling")
        return result

    def tracked_picker_draw(self, context):
        global picker_draw_count
        if not self.hide:
            picker_draw_count += 1
            basis = self.matrix_basis
            final = self.matrix_world
            basis_scales = tuple(basis.to_3x3().col[index].length
                                 for index in range(3))
            final_scales = tuple(final.to_3x3().col[index].length
                                 for index in range(3))
            if max(abs(left - right) for left, right in zip(
                    basis_scales, final_scales)) > 1.0e-5:
                picker_scale_errors.append(
                    f"picker final scale drifted: {basis_scales!r} -> "
                    f"{final_scales!r}")
        return original_picker_draw(self, context)

    picker_class.setup = tracked_picker_setup
    picker_class.draw = tracked_picker_draw
    if not INSTALLED_PACKAGE:
        entry = bpy.context.preferences.addons.new()
        entry.module = PACKAGE
        addon.register()
    if hasattr(bpy.types, "SIMPLE_DEFORM_PT_PANEL"):
        raise RuntimeError("obsolete traditional Tool panel is still registered")
    if hasattr(bpy.types, "VIEW3D_PT_simple_deform_helper"):
        raise RuntimeError("obsolete traditional Tool Settings panel is still registered")

    bpy.ops.mesh.primitive_cube_add()
    if bpy.ops.sdh.add_cage_deform() != {"FINISHED"}:
        raise RuntimeError("could not create Cage Deform stage for UI smoke test")
    target, _modifier, controller = cage_module.resolve_context_deform(
        bpy.context)
    if target is None or controller is None:
        raise RuntimeError("could not resolve Cage Deform stage for UI smoke test")
    properties = controller.sdh_cage_deform
    properties.bend_strength = math.radians(15.0)
    properties.bottom_scale = (0.75, 1.1)
    properties.top_scale = (1.55, 0.7)
    cage_module.sync_controller(controller, pull_transform=False)
    if bpy.ops.sdh.select_deform_layer(index=0) != {"FINISHED"}:
        raise RuntimeError("could not collapse deformation layer for UI smoke test")
    if bpy.ops.sdh.subdivide_cage_to_chain(count=3) != {"FINISHED"}:
        raise RuntimeError("could not subdivide cage for Gizmo smoke test")
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    if bpy.ops.sdh.add_legacy_simple_deform() != {"FINISHED"}:
        raise RuntimeError("could not add traditional stage for UI smoke test")
    legacy_modifier = target.modifiers.active
    if bpy.ops.sdh.select_cage_stage(
            index=0, include_legacy=True) != {"FINISHED"}:
        raise RuntimeError("could not reactivate cage in mixed UI stack")

    window = bpy.context.window_manager.windows[0]
    area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    area.spaces.active.show_region_ui = True
    sidebar = next(region for region in area.regions if region.type == "UI")

    ui_module = importlib.import_module(f"{PACKAGE}.cage_deform.ui")
    original_draw_deform_layer = ui_module._draw_deform_layer
    original_draw_deformation_stack = ui_module._draw_deformation_stack
    original_draw_legacy_deform_stage = ui_module._draw_legacy_deform_stage

    def tracked_draw_deform_layer(*args, **kwargs):
        global standard_layer_tree_draw_count
        if kwargs.get("tree_controls", True):
            standard_layer_tree_draw_count += 1
        return original_draw_deform_layer(*args, **kwargs)

    def tracked_draw_deformation_stack(
            layout, stack_target, active_modifier, active_controller):
        global mixed_stack_draw_count
        stages = cage_module.deform_stack_modifiers(stack_target)
        if (
                any(cage_module.is_cage_modifier(stage) for stage in stages) and
                any(stage.type == "SIMPLE_DEFORM" for stage in stages)
        ):
            mixed_stack_draw_count += 1
        return original_draw_deformation_stack(
            layout, stack_target, active_modifier, active_controller)

    def tracked_draw_legacy_deform_stage(*args, **kwargs):
        global legacy_stage_draw_count
        legacy_stage_draw_count += 1
        return original_draw_legacy_deform_stage(*args, **kwargs)

    ui_module._draw_deform_layer = tracked_draw_deform_layer
    ui_module._draw_deformation_stack = tracked_draw_deformation_stack
    ui_module._draw_legacy_deform_stage = tracked_draw_legacy_deform_stage
    panel_class = ui_module.SDH_CAGE_PT_deform
    original_draw = panel_class.draw

    def counted_draw(self, context):
        global draw_count
        draw_count += 1
        try:
            return original_draw(self, context)
        except Exception:
            ui_draw_errors.append(traceback.format_exc())
            raise

    # The active sidebar category is read-only in Blender 5.x. Register the
    # panel into that category so a real region redraw exercises its draw().
    active_category = sidebar.active_panel_category
    if not active_category or active_category == "UNSUPPORTED":
        active_category = "Item"
    bpy.utils.unregister_class(panel_class)
    panel_class.bl_category = active_category
    panel_class.draw = counted_draw
    bpy.utils.register_class(panel_class)
    area.tag_redraw()

    def finish_after_draw():
        global attempts, screenshot_scrolled, legacy_stage_selected
        attempts += 1
        if ui_draw_errors:
            return quit_with("FAIL: " + ui_draw_errors[-1])
        if picker_scale_errors:
            return quit_with("FAIL: " + "; ".join(picker_scale_errors))
        cage_coverage = (
                draw_count and picker_setup_count and picker_draw_count and
                standard_layer_tree_draw_count and mixed_stack_draw_count)
        if cage_coverage and not legacy_stage_selected:
            bpy.ops.object.select_all(action="DESELECT")
            target.select_set(True)
            bpy.context.view_layer.objects.active = target
            target.modifiers.active = legacy_modifier
            legacy_stage_selected = True
            area.tag_redraw()
            return 0.2
        if cage_coverage and legacy_stage_draw_count and attempts >= 10:
            if SCREENSHOT is not None:
                if not screenshot_scrolled:
                    with bpy.context.temp_override(
                            window=window, area=area, region=sidebar):
                        for _index in range(6):
                            bpy.ops.view2d.scroll_down(page=True)
                    screenshot_scrolled = True
                    area.tag_redraw()
                    return 0.2
                viewport = next(
                    region for region in area.regions if region.type == "WINDOW")
                with bpy.context.temp_override(
                        window=window, area=area, region=viewport):
                    bpy.ops.screen.screenshot_area(filepath=str(SCREENSHOT))
                if not SCREENSHOT.exists() or SCREENSHOT.stat().st_size < 1000:
                    return quit_with("FAIL: sidebar screenshot was not created")
            return quit_with("PASS")
        if attempts >= 40:
            return quit_with(
                "FAIL: redraw coverage was incomplete "
                f"(panel={draw_count}, picker_setup={picker_setup_count}, "
                f"picker_draw={picker_draw_count}, "
                f"standard_layers={standard_layer_tree_draw_count}, "
                f"mixed_stack={mixed_stack_draw_count}, "
                f"legacy_stage={legacy_stage_draw_count})")
        area.tag_redraw()
        return 0.1

    bpy.app.timers.register(finish_after_draw, first_interval=0.1)
except Exception:
    quit_with("FAIL:\n" + traceback.format_exc())
