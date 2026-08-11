"""Open an installed FFD Native Edit session and monitor manual undo/redo."""
from __future__ import annotations

import importlib
import os
import sys
import traceback
from pathlib import Path

import addon_utils
import bpy
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
INSTALLED_PACKAGE = os.environ.get("SDH_TEST_MODULE")
PACKAGE = INSTALLED_PACKAGE or SOURCE.name
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(SOURCE.parent))
ARGS = sys.argv[sys.argv.index("--") + 1:]
RESULT = Path(ARGS[0]).resolve()
SCENE = Path(ARGS[1]).resolve()
RESULT.write_text("STARTING::FFD_NATIVE_UNDO_MANUAL", encoding="utf-8")


def finish(message):
    RESULT.write_text(message, encoding="utf-8")
    bpy.ops.wm.quit_blender()
    return None


try:
    addon = importlib.import_module(PACKAGE)
    if INSTALLED_PACKAGE:
        addon_utils.enable(PACKAGE, default_set=False)
    else:
        entry = bpy.context.preferences.addons.new()
        entry.module = PACKAGE
        addon.register()
    cage = importlib.import_module(f"{PACKAGE}.cage_deform")

    bpy.ops.mesh.primitive_cube_add()
    target = bpy.context.object
    target.name = "SDH Native Undo Manual"
    target.scale = (1.5, 1.0, 2.5)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
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
    bpy.ops.wm.save_as_mainfile(filepath=str(SCENE))

    window = bpy.context.window_manager.windows[0]
    area = next(item for item in window.screen.areas if item.type == "VIEW_3D")
    region = next(item for item in area.regions if item.type == "WINDOW")
    space = area.spaces.active
    state = {"step": 0, "phase": "STARTING", "moved": None}

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
        proxy = (
            cage.ffd_native_edit.native_edit_lattice(current_controller)
            if current_controller is not None else None)
        runtime = cage.core.ffd_lattice_object(
            current_target, current_modifier)
        return (
            current_target, current_controller, current_properties,
            proxy, runtime,
        )

    def raw_offset(proxy, index=0):
        scale = cage.ffd_native_edit._runtime_scale(proxy)
        return Vector(tuple(
            float(component) * float(axis_scale)
            for component, axis_scale in zip(
                Vector(proxy.data.points[index].co_deform) -
                cage.ffd_native_edit._native_base_coordinate(proxy, index),
                scale,
            )
        ))

    def monitor():
        try:
            state["step"] += 1
            if state["step"] < 5:
                return 0.15
            if state["phase"] == "STARTING":
                with bpy.context.temp_override(
                        window=window, area=area, region=region,
                        space_data=space):
                    result = bpy.ops.sdh.edit_ffd_native()
                    bpy.ops.view3d.view_axis(type="FRONT", align_active=False)
                    bpy.ops.view3d.view_selected(use_all_regions=False)
                if result != {"FINISHED"}:
                    return finish(
                        f"FAIL: Native Edit did not start: {result}")
                state["phase"] = "READY"
                RESULT.write_text(
                    "READY::Move selected point, confirm, Ctrl+Z, then Ctrl+Shift+Z",
                    encoding="utf-8",
                )
                return 0.1

            (current_target, current_controller, current_properties,
             proxy, runtime) = resolve()
            if (
                    proxy is None or current_properties is None or
                    not current_properties.ffd_native_edit_mode_active
            ):
                return finish(
                    f"FAIL::SESSION_ENDED::{state['phase']}")
            current = raw_offset(proxy)
            baseline = Vector((0.2, 0.0, 0.0))
            if state["phase"] == "READY":
                if (current - baseline).length > 1.0e-5:
                    state["moved"] = current.copy()
                    state["phase"] = "MOVED"
                    RESULT.write_text(
                        f"MOVED::{tuple(current)!r}::Now press Ctrl+Z",
                        encoding="utf-8",
                    )
            elif state["phase"] == "MOVED":
                if (current - baseline).length <= 1.0e-5:
                    state["phase"] = "UNDONE"
                    RESULT.write_text(
                        f"UNDONE::{tuple(current)!r}::Now press Ctrl+Shift+Z",
                        encoding="utf-8",
                    )
            elif state["phase"] == "UNDONE":
                if (current - state["moved"]).length <= 1.0e-5:
                    runtime_point = runtime.data.points[0]
                    runtime_scale = cage.ffd_native_edit._runtime_scale(runtime)
                    effective = Vector(tuple(
                        float(component) * float(axis_scale)
                        for component, axis_scale in zip(
                            Vector(runtime_point.co_deform) -
                            Vector(runtime_point.co),
                            runtime_scale,
                        )
                    ))
                    if (effective - current * 0.5).length > 1.0e-5:
                        return finish("FAIL::WEIGHTED_RUNTIME_AFTER_REDO")
                    return finish(
                        "PASS::FFD_NATIVE_UNDO_REDO_MANUAL::weight=0.5")
            if state["step"] > 3600:
                return finish(f"TIMEOUT::{state['phase']}")
            return 0.1
        except Exception:
            return finish("FAIL:\n" + traceback.format_exc())

    bpy.app.timers.register(monitor, first_interval=0.2)
except Exception:
    finish("FAIL:\n" + traceback.format_exc())
