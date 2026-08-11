"""Exercise weighted Native FFD undo/redo through Blender's GUI event loop."""
from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

import bpy
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

    bpy.ops.mesh.primitive_cube_add()
    target = bpy.context.object
    target.name = "SDH Native Undo Target"
    modifier, controller, _previous = cage.create_deform_stage(
        bpy.context, target, cage_type="FFD")
    properties = controller.sdh_cage_deform
    cage.core.ensure_ffd_point_collection(properties)
    cage.core.ffd_set_selection(properties, (0,), active=0)
    properties.ffd_points[0].offset = (0.2, 0.0, 0.0)
    properties.ffd_points[0].influence = 0.5
    cage.sync_controller(controller, pull_transform=False)
    target_uuid = str(target.get(cage.core.TARGET_UUID, ""))
    modifier_uuid = cage.core.cage_modifier_uuid(modifier)

    window = bpy.context.window_manager.windows[0]
    area = next(item for item in window.screen.areas if item.type == "VIEW_3D")
    region = next(item for item in area.regions if item.type == "WINDOW")
    space = area.spaces.active
    state = {"step": 0, "moved": None}

    def send_mouse(event_type, value, x, y):
        window.event_simulate(
            type=event_type,
            value=value,
            x=int(x),
            y=int(y),
        )

    def send_key(event_type, value, unicode=None):
        x, y = state["mouse_start"]
        keywords = dict(
            type=event_type,
            value=value,
            x=int(x),
            y=int(y),
        )
        if unicode is not None:
            keywords["unicode"] = unicode
        window.event_simulate(**keywords)

    def resolve():
        current_target = next((
            obj for obj in bpy.data.objects
            if (
                not cage.is_cage_controller(obj) and
                str(obj.get(cage.core.TARGET_UUID, "")) == target_uuid
            )
        ), None)
        current_modifier = cage.core.find_modifier(
            current_target, modifier_uuid=modifier_uuid)
        current_controller = cage.find_controller(
            current_target, current_modifier)
        current_properties = getattr(
            current_controller, "sdh_cage_deform", None)
        current_proxy = cage.ffd_native_edit.native_edit_lattice(
            current_controller) if current_controller is not None else None
        current_runtime = cage.core.ffd_lattice_object(
            current_target, current_modifier)
        return (
            current_target, current_modifier, current_controller,
            current_properties, current_proxy, current_runtime,
        )

    def proxy_raw(proxy, index=0):
        scale = cage.ffd_native_edit._runtime_scale(proxy)
        return Vector(tuple(
            float(component) * float(axis_scale)
            for component, axis_scale in zip(
                Vector(proxy.data.points[index].co_deform) -
                cage.ffd_native_edit._native_base_coordinate(proxy, index),
                scale,
            )
        ))

    def debug_snapshot(properties, proxy):
        point = proxy.data.points[0] if proxy is not None else None
        return {
            "active": getattr(
                bpy.context.view_layer.objects.active, "name", None),
            "mode": getattr(proxy, "mode", None),
            "scale": tuple(proxy.matrix_world.to_scale())
            if proxy is not None else None,
            "co": tuple(point.co) if point is not None else None,
            "co_deform": tuple(point.co_deform) if point is not None else None,
            "offset": tuple(properties.ffd_points[0].offset)
            if properties is not None else None,
        }

    def run_steps():
        try:
            state["step"] += 1
            if state["step"] < 5:
                return 0.15
            if state["step"] == 5:
                with bpy.context.temp_override(
                        window=window, area=area, region=region,
                        space_data=space):
                    result = bpy.ops.sdh.edit_ffd_native()
                if result != {"FINISHED"}:
                    return finish(f"FAIL: Native Edit did not start: {result}")
                (_target, _modifier, _controller, _properties, proxy,
                 _runtime) = resolve()
                if proxy is None or proxy.mode != "EDIT":
                    return finish("FAIL: Native Edit proxy is unavailable")
                with bpy.context.temp_override(
                        window=window, area=area, region=region,
                        space_data=space):
                    bpy.ops.lattice.select_all(action="SELECT")
                state["mouse_start"] = (
                    int(region.x + max(region.width // 2, 1)),
                    int(region.y + max(region.height // 2, 1)),
                )
                window.cursor_warp(*state["mouse_start"])
                send_mouse(
                    "MOUSEMOVE", "NOTHING", *state["mouse_start"])
                return 0.2
            if state["step"] < 10:
                area.tag_redraw()
                return 0.15
            if state["step"] == 10:
                keyconfig = bpy.context.window_manager.keyconfigs.active
                state["lattice_g"] = any(
                    keymap.name == "Lattice" and
                    item.idname == "transform.translate"
                    for keymap in keyconfig.keymaps
                    for item in keymap.keymap_items
                    if item.type == "G" and item.value == "PRESS"
                )
                send_key("G", "PRESS")
                return 0.2
            if state["step"] == 11:
                area.tag_redraw()
                return 0.2
            if state["step"] == 12:
                x, y = state["mouse_start"]
                send_mouse("MOUSEMOVE", "NOTHING", x + 36, y + 18)
                return 0.25
            if state["step"] == 13:
                x, y = state["mouse_start"]
                send_mouse("LEFTMOUSE", "PRESS", x + 36, y + 18)
                return 0.2
            if state["step"] == 14:
                x, y = state["mouse_start"]
                send_mouse("LEFTMOUSE", "RELEASE", x + 36, y + 18)
                return 0.45
            if state["step"] == 15:
                (_target, _modifier, current_controller, current_properties,
                 proxy, _runtime) = resolve()
                if proxy is None:
                    return finish("FAIL: Native transform lost its proxy")
                state["moved"] = proxy_raw(proxy)
                state["before_undo"] = debug_snapshot(
                    current_properties, proxy)
                if (
                        state["moved"] - Vector((0.2, 0.0, 0.0))
                ).length <= 1.0e-5:
                    return finish(
                        "SKIP::Blender keyboard event simulation did not "
                        "dispatch Lattice G; "
                        f"lattice_g={int(state.get('lattice_g', False))}")
                with bpy.context.temp_override(
                        window=window, area=area, region=region,
                        space_data=space):
                    result = bpy.ops.ed.undo()
                if result != {"FINISHED"}:
                    return finish(f"FAIL: Native undo failed: {result}")
                return 0.65
            if state["step"] == 16:
                (_target, _modifier, current_controller, current_properties,
                 proxy, _runtime) = resolve()
                if (
                        proxy is None or current_properties is None or
                        not current_properties.ffd_native_edit_mode_active
                ):
                    return finish("FAIL: Native undo ended the edit session")
                restored = proxy_raw(proxy)
                if (restored - Vector((0.2, 0.0, 0.0))).length > 1.0e-5:
                    return finish(
                        "FAIL: Native undo did not restore authored data: "
                        f"{tuple(restored)!r}; "
                        f"before={state.get('before_undo')!r}; "
                        f"after={debug_snapshot(current_properties, proxy)!r}")
                with bpy.context.temp_override(
                        window=window, area=area, region=region,
                        space_data=space):
                    result = bpy.ops.ed.redo()
                if result != {"FINISHED"}:
                    return finish(f"FAIL: Native redo failed: {result}")
                return 0.65
            if state["step"] == 17:
                (current_target, _modifier, current_controller,
                 current_properties, proxy, runtime) = resolve()
                if proxy is None:
                    return finish("FAIL: Native redo lost its edit proxy")
                redone = proxy_raw(proxy)
                if (redone - state["moved"]).length > 1.0e-5:
                    return finish(
                        "FAIL: Native redo did not restore authored data: "
                        f"{tuple(redone)!r} != {tuple(state['moved'])!r}")
                with bpy.context.temp_override(
                        window=window, area=area, region=region,
                        space_data=space):
                    bpy.ops.object.mode_set(mode="OBJECT")
                cage.ffd_native_edit._pull(current_controller, proxy)
                cage.ffd_native_edit._watch_sessions()
                if current_properties.ffd_native_edit_mode_active:
                    return finish("FAIL: Native session did not finalize")
                if bpy.context.view_layer.objects.active != current_target:
                    return finish("FAIL: Native session did not restore target")
                committed = Vector(current_properties.ffd_points[0].offset)
                if (committed - redone).length > 1.0e-5:
                    return finish("FAIL: Native redo was not committed on exit")
                runtime_point = runtime.data.points[0]
                runtime_scale = Vector(tuple(
                    max(abs(float(value)), cage.core.EPSILON)
                    for value in runtime.matrix_world.to_scale()))
                effective = Vector(tuple(
                    float(component) * float(scale)
                    for component, scale in zip(
                        Vector(runtime_point.co_deform) -
                        Vector(runtime_point.co),
                        runtime_scale,
                    )
                ))
                if (effective - redone * 0.5).length > 1.0e-5:
                    return finish("FAIL: Native redo lost weighted evaluation")
                return finish("PASS::FFD_NATIVE_UNDO_REDO::weight=0.5")
            if state["step"] > 22:
                return finish("FAIL: Native undo/redo event smoke timed out")
            return 0.15
        except Exception:
            return finish("FAIL:\n" + traceback.format_exc())

    bpy.app.timers.register(run_steps, first_interval=0.2)
except Exception:
    finish("FAIL:\n" + traceback.format_exc())
