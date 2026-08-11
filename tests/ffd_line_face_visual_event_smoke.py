"""Exercise LINE/FACE hover and selected state through Blender's event queue."""
from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

import bpy
from bpy_extras import view3d_utils
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
ARGS = sys.argv[sys.argv.index("--") + 1:]
RESULT = Path(ARGS[0]).resolve()
SCREENSHOT = Path(ARGS[1]).resolve() if len(ARGS) > 1 else None
sys.path.insert(0, str(SOURCE.parent))


def finish(message):
    RESULT.write_text(message, encoding="utf-8")
    bpy.ops.wm.quit_blender()
    return None


try:
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon = importlib.import_module(PACKAGE)
    addon.register()
    cage = importlib.import_module(f"{PACKAGE}.cage_deform")
    core = cage.core
    gizmos = cage.gizmos

    bpy.ops.mesh.primitive_cube_add()
    if bpy.ops.sdh.add_cage_deform(cage_type="FFD") != {"FINISHED"}:
        raise RuntimeError("could not create FFD cage")
    target, modifier, controller = cage.resolve_context_deform(bpy.context)
    properties = controller.sdh_cage_deform
    properties.ffd_resolution_u = 3
    properties.ffd_resolution_v = 3
    properties.ffd_resolution_w = 3
    properties.ffd_selection_modes = {"LINE"}
    core.ensure_ffd_point_collection(properties)

    window = bpy.context.window_manager.windows[0]
    area = next(item for item in window.screen.areas if item.type == "VIEW_3D")
    region = next(item for item in area.regions if item.type == "WINDOW")
    space = area.spaces.active
    space.show_region_ui = False
    with bpy.context.temp_override(
            window=window, area=area, region=region, space_data=space):
        bpy.ops.view3d.view_axis(type="FRONT", align_active=False)
        bpy.ops.view3d.view_selected(use_all_regions=False)

    state = {
        "step": 0, "line": None, "face": None,
        "line_retries": 0, "face_retries": 0,
    }

    def projected(index):
        world = gizmos.ffd_point_world(target, controller, index)
        screen = view3d_utils.location_3d_to_region_2d(
            region, space.region_3d, world)
        if screen is None:
            return None
        depth = -float((space.region_3d.view_matrix @ world).z)
        return float(screen.x), float(screen.y), depth

    def entity_position(mode, orientation):
        candidates = [
            (anchor, mode, axis)
            for anchor, axis in core.ffd_selection_entities(
                properties, mode, ensure=False)
            if str(axis) == orientation
        ]
        for entity in candidates:
            group = core.ffd_selection_indices(
                properties, entity[0], mode, axis=entity[2], ensure=False)
            screens = tuple(projected(index) for index in group)
            if not screens or any(screen is None for screen in screens):
                continue
            position = Vector((
                sum(screen[0] for screen in screens) / len(screens),
                sum(screen[1] for screen in screens) / len(screens),
            ))
            picked = core.ffd_screen_selection_entity(
                properties, projected, position,
                line_ratio=0.60, face_ratio=0.35,
                point_radius=10.0, line_radius=8.0, face_margin=4.0)
            if picked is not None and str(picked[1]) == mode:
                return tuple(picked), position
        raise RuntimeError(f"could not project a {mode} entity")

    def send(event_type, value, position):
        window.event_simulate(
            type=event_type,
            value=value,
            x=int(round(region.x + position.x)),
            y=int(round(region.y + position.y)),
        )

    def check_selected(entity):
        group = set(core.ffd_selection_indices(
            properties, entity[0], entity[1], axis=entity[2]))
        selected = {
            index for index, point in enumerate(properties.ffd_points)
            if point.selected
        }
        return group, selected

    def run_steps():
        try:
            state["step"] += 1
            if state["step"] < 5:
                area.tag_redraw()
                return 0.12
            if state["step"] == 5:
                with bpy.context.temp_override(
                        window=window, area=area, region=region,
                        space_data=space):
                    result = bpy.ops.sdh.box_select_ffd_points(
                        "INVOKE_DEFAULT", toggle=False)
                if result != {"RUNNING_MODAL"}:
                    return finish(
                        f"FAIL: could not start persistent FFD edit: {result}")
                return 0.20
            if state["step"] == 6:
                window.event_simulate(
                    type="MOUSEMOVE", value="NOTHING",
                    x=region.x + 20, y=region.y + 20)
                return 0.12
            if state["step"] == 7:
                state["line"] = entity_position("LINE", "U")
                send("MOUSEMOVE", "NOTHING", state["line"][1])
                return 0.20
            if state["step"] == 8:
                if core.ffd_hover_entity(controller) != state["line"][0]:
                    if state["line_retries"] < 3:
                        state["line_retries"] += 1
                        state["step"] = 7
                        send("MOUSEMOVE", "NOTHING", state["line"][1])
                        return 0.30
                    position = state["line"][1]
                    operator = core._FFD_MODAL_OPERATORS[0]
                    fake_event = SimpleNamespace(
                        mouse_x=region.x + position.x,
                        mouse_y=region.y + position.y,
                        mouse_region_x=position.x,
                        mouse_region_y=position.y,
                    )
                    direct = operator._selection_at_event(
                        bpy.context,
                        fake_event,
                    )
                    return finish(
                        "FAIL: LINE hover cache did not follow the pointer: "
                        f"{core.ffd_hover_entity(controller)!r} != "
                        f"{state['line'][0]!r}; direct={direct!r}; "
                        f"last={getattr(operator, '_last_mouse_position', None)!r}; "
                        f"inside={operator._inside_region(region, fake_event)!r}; "
                        f"state={getattr(operator, '_state', None)!r}")
                send("LEFTMOUSE", "PRESS", state["line"][1])
                return 0.12
            if state["step"] == 9:
                send("LEFTMOUSE", "RELEASE", state["line"][1])
                return 0.20
            if state["step"] == 10:
                group, selected = check_selected(state["line"][0])
                if group != selected:
                    return finish(
                        f"FAIL: LINE click selected {selected}, expected {group}")
                properties.ffd_selection_modes = {"FACE"}
                area.tag_redraw()
                window.event_simulate(
                    type="MOUSEMOVE", value="NOTHING",
                    x=region.x + 24, y=region.y + 24)
                return 0.20
            if state["step"] == 11:
                state["face"] = entity_position("FACE", "UW")
                send("MOUSEMOVE", "NOTHING", state["face"][1])
                return 0.20
            if state["step"] == 12:
                if core.ffd_hover_entity(controller) != state["face"][0]:
                    if state["face_retries"] < 3:
                        state["face_retries"] += 1
                        state["step"] = 11
                        send("MOUSEMOVE", "NOTHING", state["face"][1])
                        return 0.30
                    return finish(
                        "FAIL: FACE hover cache did not follow the pointer: "
                        f"{core.ffd_hover_entity(controller)!r} != "
                        f"{state['face'][0]!r}")
                send("LEFTMOUSE", "PRESS", state["face"][1])
                return 0.12
            if state["step"] == 13:
                send("LEFTMOUSE", "RELEASE", state["face"][1])
                return 0.20
            if state["step"] == 14:
                group, selected = check_selected(state["face"][0])
                if group != selected:
                    return finish(
                        f"FAIL: FACE click selected {selected}, expected {group}")
                colors = {
                    gizmos.SDHCageFFDAggregateGizmo._entity_color(
                        properties, state["face"][0], tuple(group), value)
                    for value in (False, True)
                }
                if len(colors) != 2:
                    return finish("FAIL: FACE normal and hover colors match")
                if SCREENSHOT is not None:
                    with bpy.context.temp_override(
                            window=window, area=area, region=region,
                            space_data=space):
                        bpy.ops.screen.screenshot_area(filepath=str(SCREENSHOT))
                core.finish_ffd_edit_sessions(bpy.context, restore_target=True)
                return finish(
                    f"PASS::FFD_LINE_FACE_VISUAL::line={state['line'][0]}::"
                    f"face={state['face'][0]}")
            if state["step"] > 20:
                return finish("FAIL: LINE/FACE event smoke timed out")
            return 0.12
        except Exception:
            return finish("FAIL:\n" + traceback.format_exc())

    bpy.app.timers.register(run_steps, first_interval=0.2)
except Exception:
    finish("FAIL:\n" + traceback.format_exc())
