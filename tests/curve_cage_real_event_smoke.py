"""Exercise Curve-cage Gizmos through Blender's real window event queue."""
from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

import bpy
from bpy_extras import view3d_utils
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))
ARGS = sys.argv[sys.argv.index("--") + 1:]
RESULT = Path(ARGS[0]).resolve()
SCREENSHOT = Path(ARGS[1]).resolve() if len(ARGS) > 1 else None


def finish(message):
    RESULT.write_text(message, encoding="utf-8")
    bpy.ops.wm.quit_blender()
    return None


try:
    bpy.context.preferences.view.show_splash = False
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon = importlib.import_module(PACKAGE)
    deform = importlib.import_module(f"{PACKAGE}.cage_deform")
    curve = importlib.import_module(f"{PACKAGE}.cage_deform.curve")
    gizmos = importlib.import_module(f"{PACKAGE}.cage_deform.gizmos")

    state = {
        "step": 0,
        "invoke_calls": 0,
        "invoke_results": [],
        "handles": [],
        "highlighted": [],
        "boundary_invoke_calls": 0,
        "boundary_invoke_results": [],
        "boundary_handles": [],
        "boundary_highlighted": [],
        "boundary_xy": None,
    }
    original_invoke = curve.SDHCurveControlGizmo.invoke
    original_draw = curve.SDHCurveControlGizmo.draw
    original_boundary_invoke = gizmos.SDHCageBoundaryGizmo.invoke
    original_boundary_draw = gizmos.SDHCageBoundaryGizmo.draw

    def tracked_invoke(self, context, event):
        state["invoke_calls"] += 1
        result = original_invoke(self, context, event)
        state["invoke_results"].append(tuple(sorted(result)))
        return result

    def tracked_draw(self, context):
        if self not in state["handles"]:
            state["handles"].append(self)
        return original_draw(self, context)

    def tracked_boundary_invoke(self, context, event):
        state["boundary_invoke_calls"] += 1
        result = original_boundary_invoke(self, context, event)
        state["boundary_invoke_results"].append(tuple(sorted(result)))
        return result

    def tracked_boundary_draw(self, context):
        if self not in state["boundary_handles"]:
            state["boundary_handles"].append(self)
        return original_boundary_draw(self, context)

    # Gizmo callbacks are cached when the RNA class is registered, so install
    # the tracker before add-on registration.
    curve.SDHCurveControlGizmo.invoke = tracked_invoke
    curve.SDHCurveControlGizmo.draw = tracked_draw
    gizmos.SDHCageBoundaryGizmo.invoke = tracked_boundary_invoke
    gizmos.SDHCageBoundaryGizmo.draw = tracked_boundary_draw
    addon.register()

    bpy.ops.mesh.primitive_cube_add()
    target = bpy.context.object
    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, target, cage_type="CURVE")
    properties = controller.sdh_cage_deform
    properties.show_boundary_handles = True
    deform.sync_controller(controller, pull_transform=False)
    guide = curve.curve_guide_object(target, modifier)
    spline = curve.curve_guide_spline(guide)
    middle = spline.bezier_points[len(spline.bezier_points) // 2]
    middle.co.x += 2.5
    middle.handle_left.x += 2.5
    middle.handle_right.x += 2.5
    guide.data.update_tag()
    target.update_tag()

    window = bpy.context.window_manager.windows[0]
    area = next(item for item in window.screen.areas if item.type == "VIEW_3D")
    region = next(item for item in area.regions if item.type == "WINDOW")
    space = area.spaces.active
    space.show_region_ui = False

    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.view3d.view_axis(type="FRONT", align_active=False)
        bpy.ops.view3d.view_selected(use_all_regions=False)
    area.tag_redraw()

    def run_steps():
        try:
            state["step"] += 1
            if state["step"] < 5:
                area.tag_redraw()
                return 0.2

            world = guide.matrix_world @ Vector(middle.co)
            screen = view3d_utils.location_3d_to_region_2d(
                region, space.region_3d, world)
            if screen is None:
                return finish("FAIL: Curve point is outside the viewport")
            x = int(region.x + screen.x)
            y = int(region.y + screen.y)

            if state["step"] == 5:
                window.event_simulate(
                    type="MOUSEMOVE", value="NOTHING", x=x, y=y)
                return 0.2
            if state["step"] == 6:
                state["highlighted"] = [
                    (int(handle.point_index), str(handle.element_kind))
                    for handle in state["handles"] if handle.is_highlight
                ]
                window.event_simulate(
                    type="LEFTMOUSE", value="PRESS", x=x, y=y)
                return 0.2
            if state["step"] == 7:
                if state["invoke_calls"] != 1:
                    return finish(
                        "FAIL: Curve Gizmo was not invoked by mouse press; "
                        f"highlighted={state['highlighted']!r}")
                if not properties.curve_object_edit_active:
                    return finish(
                        "FAIL: mouse press did not enter Curve edit mode")
                window.event_simulate(
                    type="LEFTMOUSE", value="RELEASE", x=x, y=y)
                return 0.4
            if state["step"] == 8:
                if state["invoke_calls"] != 1:
                    return finish(
                        "FAIL: real click invoked Curve Gizmo "
                        f"{state['invoke_calls']} times; highlighted="
                        f"{state['highlighted']!r}")
                if state["invoke_results"] != [("FINISHED",)]:
                    return finish(
                        f"FAIL: Curve Gizmo returned {state['invoke_results']!r}")
                if not properties.curve_object_edit_active:
                    return finish("FAIL: real click did not enter Curve edit mode")
                if not curve._CURVE_MODAL_OPERATORS:
                    return finish("FAIL: real click did not retain Curve modal")
                boundary_world = deform.core.cage_boundary_handle_world(
                    target, controller, "TOP")
                boundary_screen = view3d_utils.location_3d_to_region_2d(
                    region, space.region_3d, boundary_world)
                if boundary_screen is None:
                    return finish("FAIL: top boundary is outside the viewport")
                state["boundary_xy"] = (
                    int(region.x + boundary_screen.x),
                    int(region.y + boundary_screen.y),
                )
                window.event_simulate(
                    type="MOUSEMOVE", value="NOTHING",
                    x=state["boundary_xy"][0], y=state["boundary_xy"][1])
                return 0.3
            if state["step"] == 9:
                state["boundary_highlighted"] = [
                    str(getattr(handle, "side", ""))
                    for handle in state["boundary_handles"]
                    if handle.is_highlight
                ]
                window.event_simulate(
                    type="LEFTMOUSE", value="PRESS",
                    x=state["boundary_xy"][0], y=state["boundary_xy"][1])
                return 0.3
            if state["step"] == 10:
                if properties.curve_object_edit_active:
                    return finish(
                        "FAIL: real boundary press left Curve edit mode active")
                if curve._CURVE_MODAL_OPERATORS:
                    return finish(
                        "FAIL: real boundary press left a Curve modal")
                if state["boundary_invoke_calls"] != 1:
                    return finish(
                        "FAIL: real boundary press did not invoke its Gizmo; "
                        f"highlighted={state['boundary_highlighted']!r}")
                window.event_simulate(
                    type="MOUSEMOVE", value="NOTHING",
                    x=state["boundary_xy"][0],
                    y=state["boundary_xy"][1] + 12)
                return 0.2
            if state["step"] == 11:
                window.event_simulate(
                    type="LEFTMOUSE", value="RELEASE",
                    x=state["boundary_xy"][0],
                    y=state["boundary_xy"][1] + 12)
                return 0.3
            if state["step"] == 12:
                if state["boundary_invoke_results"] != [("RUNNING_MODAL",)]:
                    return finish(
                        "FAIL: boundary Gizmo returned "
                        f"{state['boundary_invoke_results']!r}")
                if SCREENSHOT is not None:
                    with bpy.context.temp_override(
                            window=window, area=area, region=region):
                        bpy.ops.screen.screenshot_area(filepath=str(SCREENSHOT))
                return finish("PASS")
            if state["step"] > 20:
                return finish("FAIL: real event test timed out")
            return 0.2
        except Exception:
            return finish("FAIL:\n" + traceback.format_exc())

    bpy.app.timers.register(run_steps, first_interval=0.2)
except Exception:
    finish("FAIL:\n" + traceback.format_exc())
