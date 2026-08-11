"""Exercise the first FFD point drag through Blender's real event queue."""
from __future__ import annotations

import importlib
import os
import sys
import traceback
from pathlib import Path

import bpy
from bpy_extras import view3d_utils
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
INSTALLED_PACKAGE = os.environ.get("SDH_TEST_MODULE")
PACKAGE = INSTALLED_PACKAGE or SOURCE.name
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(SOURCE.parent))
ARGS = sys.argv[sys.argv.index("--") + 1:]
RESULT = Path(ARGS[0]).resolve()
SCREENSHOT = Path(ARGS[1]).resolve() if len(ARGS) > 1 else None
RESULT.write_text("RUNNING::startup", encoding="utf-8")


def finish(message):
    RESULT.write_text(message, encoding="utf-8")
    bpy.ops.wm.quit_blender()
    return None


try:
    bpy.context.preferences.view.show_splash = False
    addon = importlib.import_module(PACKAGE)
    if INSTALLED_PACKAGE:
        import addon_utils
        addon_utils.disable(PACKAGE, default_set=False)
    cage = importlib.import_module(f"{PACKAGE}.cage_deform")
    core = importlib.import_module(f"{PACKAGE}.cage_deform.core")
    gizmos = importlib.import_module(f"{PACKAGE}.cage_deform.gizmos")

    state = {
        "step": 0,
        "handle": None,
        "gizmo_invoke_calls": 0,
        "gizmo_invoke_results": [],
        "operator_invoke_calls": 0,
        "operator_invoke_results": [],
        "picked": None,
        "origin_xy": None,
        "drag_offsets": [],
    }
    original_draw = gizmos.SDHCageFFDAggregateGizmo.draw
    original_gizmo_invoke = gizmos.SDHCageFFDAggregateGizmo.invoke
    original_operator_invoke = core.SDH_OT_box_select_ffd_points.invoke

    def tracked_draw(self, context):
        state["handle"] = self
        return original_draw(self, context)

    def tracked_gizmo_invoke(self, context, event):
        state["gizmo_invoke_calls"] += 1
        state["picked"] = tuple(getattr(self, "picked_entity", ()) or ())
        result = original_gizmo_invoke(self, context, event)
        state["gizmo_invoke_results"].append(tuple(sorted(result)))
        return result

    def tracked_operator_invoke(self, context, event):
        state["operator_invoke_calls"] += 1
        result = original_operator_invoke(self, context, event)
        state["operator_invoke_results"].append(tuple(sorted(result)))
        return result

    # Blender caches Gizmo callbacks while the RNA class is registered.
    gizmos.SDHCageFFDAggregateGizmo.draw = tracked_draw
    gizmos.SDHCageFFDAggregateGizmo.invoke = tracked_gizmo_invoke
    core.SDH_OT_box_select_ffd_points.invoke = tracked_operator_invoke
    if not INSTALLED_PACKAGE:
        entry = bpy.context.preferences.addons.new()
        entry.module = PACKAGE
        addon.register()
    else:
        addon_utils.enable(PACKAGE, default_set=False)

    bpy.ops.mesh.primitive_cube_add()
    target = bpy.context.object
    target.name = "FFD First Click Target"
    target.scale = (1.5, 1.0, 2.5)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bpy.ops.sdh.add_cage_deform(cage_type="FFD") != {"FINISHED"}:
        raise RuntimeError("could not create the FFD stage")
    modifier = target.modifiers.active
    controller = cage.find_controller(target, modifier)
    if controller is None:
        raise RuntimeError("could not resolve the FFD controller")
    properties = controller.sdh_cage_deform
    properties.ffd_selection_modes = {"POINT"}
    core.ensure_ffd_point_collection(properties)
    properties.ffd_points[7].influence = 0.25
    core.sync_controller(controller, pull_transform=False)
    initial_offsets = tuple(tuple(point.offset) for point in properties.ffd_points)

    window = bpy.context.window_manager.windows[0]
    area = next(item for item in window.screen.areas if item.type == "VIEW_3D")
    region = next(item for item in area.regions if item.type == "WINDOW")
    space = area.spaces.active
    space.show_region_ui = False
    with bpy.context.temp_override(
            window=window, area=area, region=region, space_data=space):
        bpy.ops.view3d.view_axis(type="FRONT", align_active=False)
        bpy.ops.view3d.view_selected(use_all_regions=False)
    area.tag_redraw()

    def run_steps():
        try:
            state["step"] += 1
            RESULT.write_text(
                f"RUNNING::step={state['step']}", encoding="utf-8")
            if state["step"] < 8:
                area.tag_redraw()
                return 0.15

            handle = state["handle"]
            if handle is None:
                return finish("FAIL: aggregate FFD Gizmo never drew")
            if state["origin_xy"] is None:
                point_world = gizmos.ffd_point_world(target, controller, 7)
                point_screen = view3d_utils.location_3d_to_region_2d(
                    region, space.region_3d, point_world)
                if point_screen is None:
                    return finish("FAIL: FFD point is outside the viewport")
                state["origin_xy"] = (
                    int(round(region.x + point_screen.x)),
                    int(round(region.y + point_screen.y)),
                )
            x, y = state["origin_xy"]

            if state["step"] == 8:
                window.event_simulate(
                    type="MOUSEMOVE", value="NOTHING", x=x, y=y)
                return 0.25
            if state["step"] == 9:
                if not bool(getattr(handle, "is_highlight", False)):
                    return finish(
                        "FAIL: first FFD point did not highlight; "
                        f"picked={getattr(handle, 'picked_entity', None)!r}")
                window.event_simulate(
                    type="LEFTMOUSE", value="PRESS", x=x, y=y)
                return 0.2
            if state["step"] == 10:
                if state["gizmo_invoke_calls"] != 1:
                    return finish(
                        "FAIL: first FFD point press was not dispatched; "
                        f"state={state!r}")
                window.event_simulate(
                    type="MOUSEMOVE", value="NOTHING", x=x + 18, y=y + 9)
                return 0.2
            if state["step"] == 11:
                state["drag_offsets"].append(Vector(
                    properties.ffd_points[7].offset))
                window.event_simulate(
                    type="MOUSEMOVE", value="NOTHING", x=x + 36, y=y + 18)
                return 0.2
            if state["step"] == 12:
                state["drag_offsets"].append(Vector(
                    properties.ffd_points[7].offset))
                window.event_simulate(
                    type="MOUSEMOVE", value="NOTHING", x=x + 36, y=y + 18)
                return 0.2
            if state["step"] == 13:
                state["drag_offsets"].append(Vector(
                    properties.ffd_points[7].offset))
                window.event_simulate(
                    type="LEFTMOUSE", value="RELEASE", x=x + 36, y=y + 18)
                return 0.35
            if state["step"] == 14:
                selected = tuple(bpy.context.selected_objects)
                active = bpy.context.view_layer.objects.active
                changed = tuple(
                    index for index, point in enumerate(properties.ffd_points)
                    if tuple(point.offset) != initial_offsets[index]
                )
                if state["gizmo_invoke_calls"] != 1:
                    return finish(
                        "FAIL: first FFD point did not invoke its Gizmo; "
                        f"state={state!r}")
                if state["gizmo_invoke_results"] != [("FINISHED",)]:
                    return finish(
                        "FAIL: first FFD Gizmo returned "
                        f"{state['gizmo_invoke_results']!r}")
                if state["operator_invoke_calls"] != 1:
                    return finish(
                        "FAIL: first FFD Gizmo did not start its editor; "
                        f"state={state!r}")
                if state["operator_invoke_results"] != [("RUNNING_MODAL",)]:
                    return finish(
                        "FAIL: first FFD editor returned "
                        f"{state['operator_invoke_results']!r}")
                if active != target or target not in selected:
                    return finish(
                        "FAIL: first FFD point drag lost the controlled target; "
                        f"active={getattr(active, 'name', None)!r}, "
                        f"selected={[obj.name for obj in selected]!r}")
                if controller not in selected:
                    return finish(
                        "FAIL: first FFD point drag lost its controller; "
                        f"selected={[obj.name for obj in selected]!r}")
                if not properties.ffd_edit_mode_active:
                    return finish("FAIL: first FFD point drag closed edit mode")
                if len(core._FFD_MODAL_OPERATORS) != 1:
                    return finish(
                        "FAIL: first FFD point drag did not retain one editor; "
                        f"count={len(core._FFD_MODAL_OPERATORS)}")
                if not changed:
                    return finish("FAIL: first FFD point drag changed no point")
                samples = state["drag_offsets"]
                if len(samples) != 3:
                    return finish(
                        f"FAIL: weighted drag recorded {len(samples)} samples")
                if (samples[1] - samples[2]).length > 1.0e-5:
                    return finish(
                        "FAIL: repeated weighted drag event accumulated offset: "
                        f"{tuple(samples[1])!r} != {tuple(samples[2])!r}")
                final_world = gizmos.ffd_point_world(target, controller, 7)
                final_screen = view3d_utils.location_3d_to_region_2d(
                    region, space.region_3d, final_world)
                expected_screen = Vector((
                    x - region.x + 36,
                    y - region.y + 18,
                ))
                screen_error = (
                    (Vector(final_screen) - expected_screen).length
                    if final_screen is not None else float("inf")
                )
                if screen_error > 5.0:
                    return finish(
                        "FAIL: weighted FFD handle did not follow the pointer: "
                        f"screen_error={screen_error:.3f}")
                raw = Vector(properties.ffd_points[7].offset)
                effective = core.ffd_point_effective_offset(properties, 7)
                if (effective - raw * 0.25).length > 1.0e-6:
                    return finish(
                        "FAIL: weighted FFD runtime did not attenuate the drag")
                if SCREENSHOT is not None:
                    with bpy.context.temp_override(
                            window=window, area=area, region=region,
                            space_data=space):
                        bpy.ops.screen.screenshot_area(filepath=str(SCREENSHOT))
                return finish(
                    "PASS::FFD_FIRST_CLICK_DRAG::"
                    f"picked={state['picked']!r}::changed={changed!r}::"
                    f"weight=0.25::screen_error={screen_error:.3f}")
            if state["step"] > 16:
                return finish(f"FAIL: real event test timed out: {state!r}")
            return 0.15
        except Exception:
            return finish("FAIL:\n" + traceback.format_exc())

    bpy.app.timers.register(run_steps, first_interval=0.2)
except Exception:
    finish("FAIL:\n" + traceback.format_exc())
