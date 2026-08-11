"""Exercise the traditional Twist gizmo through Blender's real event queue."""
from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

import bpy
from bpy_extras import view3d_utils


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
    angle_module = importlib.import_module(f"{PACKAGE}.gizmo.angle_and_factor")
    utils_module = importlib.import_module(f"{PACKAGE}.utils")

    state = {
        "step": 0,
        "draw_calls": 0,
        "draw_select_calls": 0,
        "invoke_calls": 0,
        "modal_calls": 0,
        "exit_calls": 0,
        "handle": None,
        "snapshots": [],
    }
    original_draw = angle_module.AngleGizmo.draw
    original_draw_select = angle_module.AngleGizmo.draw_select
    original_invoke = angle_module.AngleGizmo.invoke
    original_modal = angle_module.AngleGizmo.modal
    original_exit = angle_module.AngleGizmo.exit

    def snapshot(label, context, handle=None):
        with bpy.context.temp_override(
                window=window, area=area, region=region, space_data=space):
            obj = getattr(bpy.context, "object", None)
            modifier = getattr(
                getattr(obj, "modifiers", None), "active", None)
            poll = bool(angle_module.AngleGizmoGroup.poll(bpy.context))
        state["snapshots"].append({
            "label": label,
            "object": getattr(obj, "name", None),
            "modifier": getattr(modifier, "name", None),
            "method": getattr(modifier, "deform_method", None),
            "poll": poll,
            "origin_available": bool(
                getattr(handle, "modifier_origin_is_available", False)
                if handle is not None else False
            ),
            "highlight": bool(getattr(handle, "is_highlight", False)),
        })

    def tracked_draw(self, context):
        state["draw_calls"] += 1
        state["handle"] = self
        return original_draw(self, context)

    def tracked_draw_select(self, context, select_id):
        state["draw_select_calls"] += 1
        state["handle"] = self
        return original_draw_select(self, context, select_id)

    def tracked_invoke(self, context, event):
        state["invoke_calls"] += 1
        snapshot("invoke_before", context, self)
        result = original_invoke(self, context, event)
        snapshot("invoke_after", context, self)
        return result

    def tracked_modal(self, context, event, tweak):
        state["modal_calls"] += 1
        snapshot(f"modal_{event.type}_{event.value}_before", context, self)
        result = original_modal(self, context, event, tweak)
        snapshot(f"modal_{event.type}_{event.value}_after", context, self)
        return result

    def tracked_exit(self, context, cancel):
        state["exit_calls"] += 1
        snapshot(f"exit_{bool(cancel)}_before", context, self)
        result = original_exit(self, context, cancel)
        snapshot(f"exit_{bool(cancel)}_after", context, self)
        return result

    # Gizmo callbacks are cached during RNA registration.
    angle_module.AngleGizmo.draw = tracked_draw
    angle_module.AngleGizmo.draw_select = tracked_draw_select
    angle_module.AngleGizmo.invoke = tracked_invoke
    angle_module.AngleGizmo.modal = tracked_modal
    angle_module.AngleGizmo.exit = tracked_exit
    addon.register()

    bpy.ops.mesh.primitive_cube_add()
    target = bpy.context.object
    target.name = "Traditional Twist Gizmo Target"
    target.scale = (1.0, 1.0, 3.0)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bpy.ops.sdh.add_legacy_simple_deform() != {"FINISHED"}:
        raise RuntimeError("could not add traditional Simple Deform stage")
    modifier = target.modifiers.active
    modifier.deform_method = "TWIST"
    modifier.deform_axis = "Z"
    modifier.angle = 0.0
    preferences = utils_module.get_pref()
    preferences.show_gizmo = True
    preferences.display_bend_axis_switch_gizmo = False

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
            if state["step"] < 8:
                area.tag_redraw()
                return 0.15

            handle = state["handle"]
            if handle is None:
                return finish("FAIL: traditional angle Gizmo never drew")
            screen = view3d_utils.location_3d_to_region_2d(
                region, space.region_3d, handle.matrix_basis.translation)
            if screen is None:
                return finish("FAIL: traditional angle Gizmo is outside the viewport")
            x = int(round(region.x + screen.x))
            y = int(round(region.y + screen.y))

            if state["step"] == 8:
                snapshot("before_hover", bpy.context, handle)
                window.event_simulate(
                    type="MOUSEMOVE", value="NOTHING", x=x, y=y)
                return 0.25
            if state["step"] == 9:
                snapshot("after_hover", bpy.context, handle)
                window.event_simulate(
                    type="LEFTMOUSE", value="PRESS", x=x, y=y)
                return 0.25
            if state["step"] == 10:
                snapshot("after_press", bpy.context, handle)
                if state["invoke_calls"] != 1:
                    return finish(
                        "FAIL: Twist Gizmo was not invoked; "
                        f"state={state!r}")
                window.event_simulate(
                    type="MOUSEMOVE", value="NOTHING", x=x + 30, y=y)
                return 0.25
            if state["step"] == 11:
                snapshot("after_drag", bpy.context, handle)
                window.event_simulate(
                    type="LEFTMOUSE", value="RELEASE", x=x + 30, y=y)
                return 0.35
            if state["step"] == 12:
                snapshot("after_release", bpy.context, handle)
                area.tag_redraw()
                return 0.35
            if state["step"] == 13:
                snapshot("final", bpy.context, handle)
                if SCREENSHOT is not None:
                    with bpy.context.temp_override(
                            window=window, area=area, region=region):
                        bpy.ops.screen.screenshot_area(filepath=str(SCREENSHOT))
                final = state["snapshots"][-1]
                if not final["poll"]:
                    return finish(f"FAIL: Twist Gizmo poll became false: {state!r}")
                if not final["origin_available"]:
                    return finish(
                        "FAIL: Twist Gizmo lost its bound geometry: "
                        f"{state!r}")
                if state["modal_calls"] < 1 or state["exit_calls"] != 1:
                    return finish(
                        "FAIL: Twist Gizmo modal lifecycle was incomplete: "
                        f"{state!r}")
                return finish(f"PASS: {state!r}")
            if state["step"] > 20:
                return finish(f"FAIL: real event test timed out: {state!r}")
            return 0.15
        except Exception:
            return finish("FAIL:\n" + traceback.format_exc())

    bpy.app.timers.register(run_steps, first_interval=0.2)
except Exception:
    finish("FAIL:\n" + traceback.format_exc())
