"""Exercise the managed-Origin rotation ring on a real Gizmo instance."""
from __future__ import annotations

import importlib
import math
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))
ARGS = sys.argv[sys.argv.index("--") + 1:]
RESULT = Path(ARGS[0]).resolve()


def finish(message):
    RESULT.write_text(message, encoding="utf-8")
    bpy.ops.wm.quit_blender()
    return None


try:
    bpy.context.preferences.view.show_splash = False
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon = importlib.import_module(PACKAGE)
    gizmo_module = importlib.import_module(f"{PACKAGE}.gizmo.z_rotate")
    utils_module = importlib.import_module(f"{PACKAGE}.utils")

    state = {
        "step": 0,
        "draw_calls": 0,
        "invoke_calls": 0,
        "modal_calls": 0,
        "exit_calls": 0,
        "handle": None,
        "snapshots": [],
    }
    original_draw = gizmo_module.ZRotateGizmo.draw
    original_invoke = gizmo_module.ZRotateGizmo.invoke
    original_modal = gizmo_module.ZRotateGizmo.modal
    original_exit = gizmo_module.ZRotateGizmo.exit

    def snapshot(label, context, handle=None):
        with bpy.context.temp_override(
                window=window, area=area, region=region, space_data=space):
            obj = getattr(bpy.context, "object", None)
            modifier = getattr(
                getattr(obj, "modifiers", None), "active", None)
            poll = bool(gizmo_module.ZRotateGizmoGroup.poll(bpy.context))
        state["snapshots"].append({
            "label": label,
            "method": getattr(modifier, "deform_method", None),
            "angle": round(float(
                getattr(getattr(modifier, "origin", None),
                        "simple_deform_helper_rotate_angle", 0.0)), 6),
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

    gizmo_module.ZRotateGizmo.draw = tracked_draw
    gizmo_module.ZRotateGizmo.invoke = tracked_invoke
    gizmo_module.ZRotateGizmo.modal = tracked_modal
    gizmo_module.ZRotateGizmo.exit = tracked_exit
    addon.register()

    bpy.ops.mesh.primitive_cube_add()
    target = bpy.context.object
    target.name = "Traditional Origin Gizmo Target"
    target.scale = (3.0, 3.0, 3.0)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bpy.ops.sdh.add_legacy_simple_deform() != {"FINISHED"}:
        raise RuntimeError("could not add traditional Simple Deform stage")
    modifier = target.modifiers.active
    modifier.deform_method = "BEND"
    modifier.deform_axis = "Z"
    modifier.angle = math.radians(30.0)
    preferences = utils_module.get_pref()
    preferences.show_gizmo = True
    preferences.display_bend_axis_switch_gizmo = False

    window = bpy.context.window_manager.windows[0]
    area = next(item for item in window.screen.areas if item.type == "VIEW_3D")
    region = next(item for item in area.regions if item.type == "WINDOW")
    space = area.spaces.active
    space.show_region_ui = False
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.view3d.view_axis(type="TOP", align_active=False)
        bpy.ops.view3d.view_selected(use_all_regions=False)
    space.region_3d.view_distance *= 1.8
    area.tag_redraw()

    def run_steps():
        try:
            state["step"] += 1
            if state["step"] < 8:
                area.tag_redraw()
                return 0.15

            handle = state["handle"]
            if handle is None:
                return finish("FAIL: Origin rotation Gizmo never drew")
            event = SimpleNamespace(
                type="LEFTMOUSE",
                value="PRESS",
                mouse_region_x=120,
                mouse_region_y=120,
                shift=False,
                ctrl=False,
                alt=False,
                is_repeat=False,
            )
            if state["step"] == 8:
                snapshot("before_press", bpy.context, handle)
                with bpy.context.temp_override(
                        window=window, area=area, region=region,
                        space_data=space):
                    handle.invoke(bpy.context, event)
                return 0.2
            if state["step"] == 9:
                snapshot("after_press", bpy.context, handle)
                if state["invoke_calls"] != 1:
                    return finish(f"FAIL: rotation ring invoke failed: {state!r}")
                event.type = "MOUSEMOVE"
                event.value = "NOTHING"
                event.mouse_region_x += 25
                with bpy.context.temp_override(
                        window=window, area=area, region=region,
                        space_data=space):
                    handle.modal(bpy.context, event, ())
                return 0.2
            if state["step"] == 10:
                snapshot("after_drag", bpy.context, handle)
                with bpy.context.temp_override(
                        window=window, area=area, region=region,
                        space_data=space):
                    handle.exit(bpy.context, False)
                return 0.3
            if state["step"] == 11:
                snapshot("after_release", bpy.context, handle)
                area.tag_redraw()
                return 0.3
            if state["step"] == 12:
                snapshot("final", bpy.context, handle)
                final = state["snapshots"][-1]
                if not final["poll"] or not final["origin_available"]:
                    return finish(f"FAIL: rotation ring disappeared: {state!r}")
                if state["modal_calls"] < 1 or state["exit_calls"] != 1:
                    return finish(f"FAIL: rotation ring lifecycle incomplete: {state!r}")
                return finish(f"PASS: {state!r}")
            if state["step"] > 20:
                return finish(f"FAIL: rotation ring test timed out: {state!r}")
            return 0.15
        except Exception:
            return finish("FAIL:\n" + traceback.format_exc())

    bpy.app.timers.register(run_steps, first_interval=0.2)
except Exception:
    finish("FAIL:\n" + traceback.format_exc())
