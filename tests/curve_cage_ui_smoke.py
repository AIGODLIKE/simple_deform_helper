"""Interactive smoke test for Curve cage object-mode controls."""
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


def event(event_type, value="PRESS", **values):
    defaults = {
        "type": event_type,
        "value": value,
        "mouse_x": 0,
        "mouse_y": 0,
        "mouse_region_x": 0,
        "mouse_region_y": 0,
        "shift": False,
        "ctrl": False,
        "alt": False,
    }
    defaults.update(values)
    return type("CurveSmokeEvent", (), defaults)()


try:
    bpy.context.preferences.view.show_splash = False
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon = importlib.import_module(PACKAGE)
    addon.register()
    try:
        bpy.ops.wm.splash_close()
    except (AttributeError, RuntimeError):
        pass
    deform = importlib.import_module(f"{PACKAGE}.cage_deform")
    curve = importlib.import_module(f"{PACKAGE}.cage_deform.curve")

    bpy.ops.mesh.primitive_cube_add()
    target = bpy.context.object
    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, target, cage_type="CURVE")
    properties = controller.sdh_cage_deform
    guide = curve.curve_guide_object(target, modifier)
    spline = curve.curve_guide_spline(guide)

    window = bpy.context.window_manager.windows[0]
    area = next(item for item in window.screen.areas if item.type == "VIEW_3D")
    region = next(item for item in area.regions if item.type == "WINDOW")
    sidebar = next(item for item in area.regions if item.type == "UI")
    area.spaces.active.show_region_ui = True
    area.spaces.active.region_3d.view_distance = 8.0
    area.spaces.active.region_3d.view_matrix

    state = {"step": 0, "draws": 0, "setups": 0}
    gizmo_class = curve.SDHCurveControlGizmo
    original_setup = gizmo_class.setup
    original_draw = gizmo_class.draw

    def tracked_setup(self):
        result = original_setup(self)
        state["setups"] += 1
        return result

    def tracked_draw(self, context):
        if not self.hide:
            state["draws"] += 1
        return original_draw(self, context)

    gizmo_class.setup = tracked_setup
    gizmo_class.draw = tracked_draw

    def run_steps():
        try:
            state["step"] += 1
            if state["step"] == 1:
                try:
                    bpy.ops.wm.splash_close()
                except (AttributeError, RuntimeError):
                    pass
                area.tag_redraw()
                return 0.2
            if state["step"] == 2:
                probe = type("CurveGizmoProbe", (), {})()
                probe._stage = lambda: (target, modifier, controller)
                probe.element_kind = "POINT"
                probe.point_index = 1
                mouse_x = region.width // 2
                mouse_y = region.height // 2
                with bpy.context.temp_override(
                        window=window, area=area, region=region):
                    result = curve.SDHCurveControlGizmo.invoke(
                        probe,
                        bpy.context,
                        event(
                            "LEFTMOUSE",
                            mouse_x=region.x + mouse_x,
                            mouse_y=region.y + mouse_y,
                            mouse_region_x=mouse_x,
                            mouse_region_y=mouse_y,
                        ),
                    )
                if result != {"FINISHED"}:
                    return finish(f"FAIL: Curve Gizmo invoke returned {result!r}")
                if not properties.curve_object_edit_active:
                    return finish("FAIL: Curve Gizmo did not enable object edit mode")
                if not curve._CURVE_MODAL_OPERATORS:
                    return finish("FAIL: Curve Gizmo did not start a persistent modal")
                operator = curve._CURVE_MODAL_OPERATORS[0]
                if operator._state != "TRANSFORM":
                    return finish("FAIL: Curve Gizmo did not begin direct point drag")
                operator.modal(
                    bpy.context,
                    event(
                        "LEFTMOUSE", "RELEASE",
                        mouse_x=region.x + mouse_x,
                        mouse_y=region.y + mouse_y,
                        mouse_region_x=mouse_x,
                        mouse_region_y=mouse_y,
                    ),
                )
                if operator._state != "WAITING":
                    return finish("FAIL: Curve Gizmo release did not keep edit mode active")
                if not (target.select_get() and controller.select_get() and guide.select_get()):
                    return finish("FAIL: animation owners were not selected")
                if bpy.context.view_layer.objects.active != target:
                    return finish("FAIL: controlled target is not active")
                area.tag_redraw()
                return 0.2

            if state["step"] == 3:
                if not curve._CURVE_MODAL_OPERATORS:
                    return finish("FAIL: persistent Curve modal is missing")
                operator = curve._CURVE_MODAL_OPERATORS[0]
                ui_x = sidebar.x + max(sidebar.width // 2, 1)
                ui_y = sidebar.y + max(sidebar.height // 2, 1)
                result = operator.modal(
                    bpy.context,
                    event("LEFTMOUSE", mouse_x=ui_x, mouse_y=ui_y))
                if result != {"PASS_THROUGH"}:
                    return finish("FAIL: Curve modal consumed an N-panel click")

                # A boundary Gizmo must receive the same press instead of
                # turning it into a blank Curve box drag.  This reproduces
                # the reported failure when switching from Curve points to
                # the top/bottom boundary controls.
                properties.show_boundary_handles = True
                bpy.context.view_layer.update()
                boundary_world = deform.core.cage_boundary_handle_world(
                    target, controller, "TOP")
                boundary_screen = view3d_utils.location_3d_to_region_2d(
                    region, area.spaces.active.region_3d, boundary_world)
                if boundary_screen is None:
                    return finish("FAIL: top boundary was not projectable")
                boundary_event = event(
                    "LEFTMOUSE", mouse_x=region.x + int(boundary_screen.x),
                    mouse_y=region.y + int(boundary_screen.y),
                    mouse_region_x=int(boundary_screen.x),
                    mouse_region_y=int(boundary_screen.y),
                )
                if not operator._over_other_gizmo(
                        bpy.context, boundary_event):
                    return finish(
                        "FAIL: Curve modal did not hit-test the top boundary")
                result = operator.modal(bpy.context, boundary_event)
                if result != {"PASS_THROUGH"}:
                    return finish(
                        f"FAIL: boundary press returned {result!r}")
                if properties.curve_object_edit_active:
                    return finish(
                        "FAIL: boundary press left Curve edit mode active")
                if curve._CURVE_MODAL_OPERATORS:
                    return finish(
                        "FAIL: boundary press left a Curve modal operator")

                with bpy.context.temp_override(
                        window=window, area=area, region=region):
                    result = bpy.ops.sdh.edit_curve_cage_object(
                        "INVOKE_DEFAULT",
                        controller_uuid=str(controller.get(
                            deform.core.CONTROLLER_UUID, "")),
                        toggle=False,
                    )
                if "RUNNING_MODAL" not in result:
                    return finish(
                        f"FAIL: Curve edit did not restart after boundary handoff: {result!r}")
                if not curve._CURVE_MODAL_OPERATORS:
                    return finish(
                        "FAIL: Curve modal did not restart after boundary handoff")
                operator = curve._CURVE_MODAL_OPERATORS[0]

                properties.curve_points[1].selected = True
                properties.curve_active_point = 1
                point = spline.bezier_points[1]
                original = Vector(point.co)
                mouse_x = region.width // 2
                mouse_y = region.height // 2
                operator._begin_transform(
                    bpy.context,
                    event(
                        "G", mouse_region_x=mouse_x,
                        mouse_region_y=mouse_y),
                    "MOVE", kind="POINT", index=1)
                operator.modal(
                    bpy.context,
                    event(
                        "MOUSEMOVE", "NOTHING",
                        mouse_x=region.x + mouse_x + 80,
                        mouse_y=region.y + mouse_y,
                        mouse_region_x=mouse_x + 80,
                        mouse_region_y=mouse_y))
                operator.modal(bpy.context, event("ESC"))
                if (Vector(point.co) - original).length > 1.0e-6:
                    return finish("FAIL: transform cancel did not restore the point")
                if not properties.curve_object_edit_active:
                    return finish("FAIL: transform cancel exited Curve edit mode")

                properties.curve_active_point = 1
                point = spline.bezier_points[1]
                original_right = Vector(point.handle_right)
                operator._begin_transform(
                    bpy.context,
                    event(
                        "LEFTMOUSE", mouse_region_x=mouse_x,
                        mouse_region_y=mouse_y),
                    "MOVE", kind="RIGHT", index=1)
                operator.modal(
                    bpy.context,
                    event(
                        "MOUSEMOVE", "NOTHING",
                        mouse_x=region.x + mouse_x + 60,
                        mouse_y=region.y + mouse_y,
                        mouse_region_x=mouse_x + 60,
                        mouse_region_y=mouse_y))
                if (Vector(point.handle_right) - original_right).length < 1.0e-5:
                    return finish("FAIL: direct Bezier handle drag did not move")
                if (Vector(point.handle_left) + Vector(point.handle_right) -
                        Vector(point.co) * 2.0).length > 1.0e-5:
                    return finish("FAIL: normal Bezier handle drag was not symmetric")
                operator.modal(bpy.context, event("LEFTMOUSE", "RELEASE"))

                bpy.context.view_layer.update()
                opposite_before = guide.matrix_world @ Vector(point.handle_left)
                dragged_before = guide.matrix_world @ Vector(point.handle_right)
                operator._begin_transform(
                    bpy.context,
                    event(
                        "LEFTMOUSE", mouse_region_x=mouse_x,
                        mouse_region_y=mouse_y),
                    "MOVE", kind="RIGHT", index=1)
                operator.modal(
                    bpy.context,
                    event(
                        "MOUSEMOVE", "NOTHING", alt=True,
                        mouse_x=region.x + mouse_x - 45,
                        mouse_y=region.y + mouse_y + 20,
                        mouse_region_x=mouse_x - 45,
                        mouse_region_y=mouse_y + 20))
                bpy.context.view_layer.update()
                if (guide.matrix_world @ Vector(point.handle_left) -
                        opposite_before).length > 1.0e-6:
                    return finish("FAIL: Alt Bezier drag changed the opposite handle")
                if (guide.matrix_world @ Vector(point.handle_right) -
                        dragged_before).length < 1.0e-5:
                    return finish("FAIL: Alt Bezier drag did not move its own handle")
                operator.modal(bpy.context, event("LEFTMOUSE", "RELEASE"))

                bpy.context.view_layer.update()
                free_opposite = guide.matrix_world @ Vector(point.handle_left)
                free_dragged = guide.matrix_world @ Vector(point.handle_right)
                operator._begin_transform(
                    bpy.context,
                    event(
                        "LEFTMOUSE", mouse_region_x=mouse_x,
                        mouse_region_y=mouse_y),
                    "MOVE", kind="RIGHT", index=1)
                operator.modal(
                    bpy.context,
                    event(
                        "MOUSEMOVE", "NOTHING",
                        mouse_x=region.x + mouse_x + 35,
                        mouse_y=region.y + mouse_y - 15,
                        mouse_region_x=mouse_x + 35,
                        mouse_region_y=mouse_y - 15))
                bpy.context.view_layer.update()
                if (guide.matrix_world @ Vector(point.handle_left) -
                        free_opposite).length > 1.0e-6:
                    return finish(
                        "FAIL: normal drag relinked an Alt-separated handle")
                if (guide.matrix_world @ Vector(point.handle_right) -
                        free_dragged).length < 1.0e-5:
                    return finish(
                        "FAIL: free Bezier handle did not move after Alt separation")
                operator.modal(bpy.context, event("LEFTMOUSE", "RELEASE"))
                area.tag_redraw()
                return 0.2

            if state["step"] == 4:
                operator = curve._CURVE_MODAL_OPERATORS[0]
                operator.modal(bpy.context, event("A", alt=True))
                if any(item.selected for item in properties.curve_points):
                    return finish("FAIL: Alt+A did not clear Curve point selection")
                operator.modal(bpy.context, event("A"))
                if not all(item.selected for item in properties.curve_points):
                    return finish("FAIL: A did not select every Curve point")

                mouse_x = region.width // 2
                mouse_y = region.height // 2
                press = event(
                    "LEFTMOUSE", "PRESS",
                    mouse_x=region.x + mouse_x,
                    mouse_y=region.y + mouse_y,
                    mouse_region_x=mouse_x,
                    mouse_region_y=mouse_y,
                )
                if not operator._begin_pointer_transform(
                        bpy.context, press, properties, spline,
                        "POINT", 1, False):
                    return finish("FAIL: selected Curve point drag did not start")
                operator.modal(
                    bpy.context,
                    event(
                        "MOUSEMOVE", "NOTHING",
                        mouse_x=region.x + mouse_x + 20,
                        mouse_y=region.y + mouse_y,
                        mouse_region_x=mouse_x + 20,
                        mouse_region_y=mouse_y,
                    ),
                )
                operator.modal(bpy.context, event("ESC"))
                if not all(item.selected for item in properties.curve_points):
                    return finish("FAIL: Curve group drag collapsed multi-selection")

                if not operator._begin_pointer_transform(
                        bpy.context, press, properties, spline,
                        "POINT", 1, False):
                    return finish("FAIL: selected Curve point press did not start")
                operator.modal(
                    bpy.context,
                    event(
                        "LEFTMOUSE", "RELEASE",
                        mouse_x=region.x + mouse_x,
                        mouse_y=region.y + mouse_y,
                        mouse_region_x=mouse_x,
                        mouse_region_y=mouse_y,
                    ),
                )
                selected = tuple(
                    index for index, item in enumerate(properties.curve_points)
                    if item.selected)
                if selected != (1,):
                    return finish(
                        f"FAIL: point click did not collapse selection: {selected!r}")

                operator.modal(bpy.context, event("A"))
                blank_press = None
                for x_factor, y_factor in (
                        (0.12, 0.12), (0.88, 0.12),
                        (0.12, 0.88), (0.88, 0.88)):
                    blank_x = int(region.width * x_factor)
                    blank_y = int(region.height * y_factor)
                    candidate = event(
                        "LEFTMOUSE", "PRESS",
                        mouse_x=region.x + blank_x,
                        mouse_y=region.y + blank_y,
                        mouse_region_x=blank_x,
                        mouse_region_y=blank_y,
                    )
                    if operator._hit_element(bpy.context, candidate) is None:
                        blank_press = candidate
                        break
                if blank_press is None:
                    return finish("FAIL: no empty viewport position for blank click")
                if operator.modal(bpy.context, blank_press) != {"RUNNING_MODAL"}:
                    return finish("FAIL: blank press was not consumed by Curve edit")
                blank_release = event(
                    "LEFTMOUSE", "RELEASE",
                    mouse_x=blank_press.mouse_x,
                    mouse_y=blank_press.mouse_y,
                    mouse_region_x=blank_press.mouse_region_x,
                    mouse_region_y=blank_press.mouse_region_y,
                )
                if operator.modal(
                        bpy.context, blank_release) != {"RUNNING_MODAL"}:
                    return finish("FAIL: blank click exited Curve edit mode")
                if any(item.selected for item in properties.curve_points):
                    return finish("FAIL: blank click did not clear Curve selection")

                point_screen = view3d_utils.location_3d_to_region_2d(
                    region,
                    area.spaces.active.region_3d,
                    guide.matrix_world @ Vector(spline.bezier_points[1].co),
                )
                if point_screen is None:
                    return finish("FAIL: Curve point was not projectable")
                drag_press = None
                for offset in (
                        Vector((36.0, 36.0)), Vector((-36.0, 36.0)),
                        Vector((36.0, -36.0)), Vector((-36.0, -36.0))):
                    start = Vector(point_screen) + offset
                    if not (
                            2.0 <= start.x < region.width - 2.0 and
                            2.0 <= start.y < region.height - 2.0):
                        continue
                    candidate = event(
                        "LEFTMOUSE", "PRESS",
                        mouse_x=region.x + int(start.x),
                        mouse_y=region.y + int(start.y),
                        mouse_region_x=int(start.x),
                        mouse_region_y=int(start.y),
                    )
                    if operator._hit_element(bpy.context, candidate) is None:
                        drag_press = candidate
                        break
                if drag_press is None:
                    return finish("FAIL: no blank Curve box-drag origin")
                if operator.modal(
                        bpy.context, drag_press) != {"RUNNING_MODAL"}:
                    return finish("FAIL: blank drag press was not consumed")
                if operator._state != "DRAGGING":
                    return finish("FAIL: blank drag did not enter DRAGGING")
                if operator.modal(
                        bpy.context,
                        event("TIMER", "NOTHING")) != {"RUNNING_MODAL"}:
                    return finish("FAIL: intermediate event cancelled Curve box")
                drag_end = Vector(point_screen) - Vector((3.0, 3.0))
                move = event(
                    "INBETWEEN_MOUSEMOVE", "NOTHING",
                    mouse_x=region.x + int(drag_end.x),
                    mouse_y=region.y + int(drag_end.y),
                    mouse_region_x=int(drag_end.x),
                    mouse_region_y=int(drag_end.y),
                )
                if operator.modal(bpy.context, move) != {"RUNNING_MODAL"}:
                    return finish("FAIL: Curve box move was not retained")
                release = event(
                    "LEFTMOUSE", "RELEASE",
                    mouse_x=move.mouse_x,
                    mouse_y=move.mouse_y,
                    mouse_region_x=move.mouse_region_x,
                    mouse_region_y=move.mouse_region_y,
                )
                if operator.modal(
                        bpy.context, release) != {"RUNNING_MODAL"}:
                    return finish("FAIL: Curve box release ended the editor")
                if operator._state != "WAITING":
                    return finish("FAIL: Curve box release did not finish selection")
                if not properties.curve_points[1].selected:
                    return finish("FAIL: direct blank drag selected no Curve point")

                if operator.modal(
                        bpy.context, drag_press) != {"RUNNING_MODAL"}:
                    return finish("FAIL: boundary box press was not consumed")
                outside_release = event(
                    "LEFTMOUSE", "RELEASE",
                    mouse_x=sidebar.x + max(sidebar.width // 2, 1),
                    mouse_y=sidebar.y + max(sidebar.height // 2, 1),
                    mouse_region_x=region.width + max(sidebar.width // 2, 1),
                    mouse_region_y=max(sidebar.height // 2, 1),
                )
                if operator.modal(
                        bpy.context, outside_release) != {"RUNNING_MODAL"}:
                    return finish("FAIL: outside release cancelled Curve box")
                if operator._state != "WAITING":
                    return finish("FAIL: outside release left Curve box stuck")
                operator.modal(bpy.context, event("A"))
                area.tag_redraw()
                return 0.4

            if state["step"] == 5:
                operator = curve._CURVE_MODAL_OPERATORS[0]
                if SCREENSHOT is not None:
                    with bpy.context.temp_override(
                            window=window, area=area, region=region):
                        bpy.ops.screen.screenshot_area(filepath=str(SCREENSHOT))
                    if not SCREENSHOT.exists() or SCREENSHOT.stat().st_size < 1000:
                        return finish("FAIL: Curve screenshot was not created")
                blank_event = None
                for x_factor, y_factor in (
                        (0.12, 0.12), (0.88, 0.12),
                        (0.12, 0.88), (0.88, 0.88),
                        (0.25, 0.75), (0.75, 0.25)):
                    blank_x = int(region.width * x_factor)
                    blank_y = int(region.height * y_factor)
                    candidate = event(
                        "LEFTMOUSE", "DOUBLE_CLICK",
                        mouse_x=region.x + blank_x,
                        mouse_y=region.y + blank_y,
                        mouse_region_x=blank_x,
                        mouse_region_y=blank_y,
                    )
                    if (
                            not operator._inside_ui_region(bpy.context, candidate) and
                            operator._hit_element(bpy.context, candidate) is None
                    ):
                        blank_event = candidate
                        break
                if blank_event is None:
                    return finish("FAIL: no empty viewport position for double-click")
                exit_result = operator.modal(
                    bpy.context,
                    blank_event)
                if exit_result != {"FINISHED"}:
                    return finish(
                        f"FAIL: blank double-click returned {exit_result!r}")
                if properties.curve_object_edit_active:
                    return finish("FAIL: blank double-click did not exit Curve edit mode")
                if curve._CURVE_MODAL_OPERATORS:
                    return finish("FAIL: Curve modal was not released")
                if curve._CURVE_DRAW_HANDLERS:
                    return finish("FAIL: Curve draw handler was not removed")
                if state["setups"] < len(spline.bezier_points) * 3:
                    return finish(
                        f"FAIL: not all Curve Gizmos were allocated ({state['setups']})")
                if state["draws"] < len(spline.bezier_points):
                    return finish(
                        f"FAIL: Curve point Gizmos did not draw ({state['draws']})")
                return finish("PASS")

            if state["step"] > 40:
                return finish("FAIL: Curve UI smoke timed out")
            area.tag_redraw()
            return 0.2
        except Exception:
            return finish("FAIL:\n" + traceback.format_exc())

    bpy.app.timers.register(run_steps, first_interval=0.2)
except Exception:
    finish("FAIL:\n" + traceback.format_exc())
