"""Focused regression checks for Blender proportional editing on FFD controls."""
from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))

entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
core = importlib.import_module(f"{PACKAGE}.cage_deform.core")


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def make_target():
    mesh = bpy.data.meshes.new("SDH Proportional FFD Mesh")
    mesh.from_pydata(
        (
            (-1.0, -1.0, -1.0), (1.0, -1.0, -1.0),
            (1.0, 1.0, -1.0), (-1.0, 1.0, -1.0),
            (-1.0, -1.0, 1.0), (1.0, -1.0, 1.0),
            (1.0, 1.0, 1.0), (-1.0, 1.0, 1.0),
        ), (), ()
    )
    target = bpy.data.objects.new("SDH Proportional FFD", mesh)
    bpy.context.collection.objects.link(target)
    bpy.context.view_layer.objects.active = target
    target.select_set(True)
    return target


def main():
    falloffs = core.FFD_PROPORTIONAL_FALLOFFS
    for falloff in falloffs:
        values = [
            core.ffd_proportional_weight(distance, 2.0, falloff, index=3)
            for distance in (0.0, 0.5, 1.0, 1.5, 2.0, math.inf)
        ]
        check(all(math.isfinite(value) for value in values),
              f"non-finite {falloff} proportional weight")
        check(all(0.0 <= value <= 1.0 for value in values),
              f"out-of-range {falloff} proportional weight")
        if falloff == "RANDOM":
            check(values[-1] == 0.0,
                  "RANDOM falloff did not reach zero outside its radius")
        else:
            check(values[0] == 1.0 and values[-1] == 0.0,
                  f"{falloff} endpoints do not match Blender falloff contract")

    target = make_target()
    try:
        _modifier, controller, _previous = core.create_deform_stage(
            bpy.context, target)
        properties = controller.sdh_cage_deform
        properties.cage_type = "FFD"
        properties.ffd_resolution_u = 3
        properties.ffd_resolution_v = 3
        properties.ffd_resolution_w = 3
        core.ensure_ffd_point_collection(properties)
        core.ffd_set_selection(properties, {0}, active=0)

        operator = SimpleNamespace(
            _controller=lambda: controller,
            _selected_transform_indices=lambda value: tuple(
                index for index, point in enumerate(value.ffd_points)
                if point.selected and index in set(core.ffd_visible_indices(value))),
            _point_local=lambda value, index: (
                core.SDH_OT_box_select_ffd_points._point_local(value, index)),
            _point_source_local=lambda value, index: (
                core.SDH_OT_box_select_ffd_points._point_source_local(
                    value, index)),
            _tool_settings=lambda value: (
                core.SDH_OT_box_select_ffd_points._tool_settings(value)),
            _proportional_enabled=lambda value: (
                core.SDH_OT_box_select_ffd_points._proportional_enabled(value)),
            _initialize_proportional_radius=None,
            _set_header=lambda _context: None,
            _window_region=SimpleNamespace(x=0, y=0, width=100, height=100),
            _area=None,
            report=lambda *_args, **_kwargs: None,
        )
        operator._initialize_proportional_radius = lambda value=None: (
            core.SDH_OT_box_select_ffd_points._initialize_proportional_radius(
                operator, value))
        context = bpy.context
        settings = context.scene.tool_settings
        old_enabled = bool(settings.use_proportional_edit_objects)
        old_size = float(settings.proportional_size)
        old_falloff = settings.proportional_edit_falloff
        try:
            settings.use_proportional_edit_objects = True
            settings.proportional_size = 10.0
            settings.proportional_edit_falloff = "LINEAR"
            check(core.SDH_OT_box_select_ffd_points._begin_transform(
                operator, context, None, "MOVE", initial_mouse=(10, 10)),
                  "FFD transform initialization failed")
            check(abs(operator._proportional_radius - 10.0) < 1.0e-6,
                  "FFD did not inherit Blender proportional_size")
            weights = core.SDH_OT_box_select_ffd_points._proportional_weights(
                operator, context)
            check(weights[0] == 1.0, "selected FFD point lost full influence")
            check(any(0.0 < weight < 1.0 for index, weight in weights.items()
                      if index != 0),
                  "nearby FFD points did not receive proportional influence")

            # A line selection must feed all of its endpoints into the same
            # multi-source distance field, just like a native edge selection.
            core.ffd_set_selection(properties, {
                *core.ffd_selection_indices(properties, 0, "LINE", axis="U")
            }, active=0)
            operator._proportional_radius = math.nan
            check(core.SDH_OT_box_select_ffd_points._begin_transform(
                operator, context, None, "MOVE", initial_mouse=(10, 10)),
                  "FFD line transform initialization failed")
            check(set(operator._transform_selected_indices) == {0, 1},
                  "FFD line selection did not reach proportional transform")
            line_weights = core.SDH_OT_box_select_ffd_points._proportional_weights(
                operator, context)
            check(line_weights[0] == 1.0 and line_weights[1] == 1.0,
                  "FFD line endpoints did not retain full influence")
        finally:
            settings.use_proportional_edit_objects = old_enabled
            settings.proportional_size = old_size
            settings.proportional_edit_falloff = old_falloff
    finally:
        bpy.ops.object.select_all(action="DESELECT")
        for obj in tuple(bpy.data.objects):
            if obj.name.startswith("SDH Proportional FFD"):
                bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in tuple(bpy.data.meshes):
            if mesh.name.startswith("SDH Proportional FFD"):
                bpy.data.meshes.remove(mesh)

    print("SDH_FFD_PROPORTIONAL::PASS")


try:
    main()
except Exception:
    import traceback
    traceback.print_exc()
    raise
finally:
    try:
        addon.unregister()
    except Exception:
        pass
