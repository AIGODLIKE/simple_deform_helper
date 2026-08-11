"""Focused Curve falloff and cross-section equalization regressions."""
from __future__ import annotations

import importlib
import math
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
INSTALLED_PACKAGE = os.environ.get("SDH_TEST_MODULE")
PACKAGE = INSTALLED_PACKAGE or SOURCE.name
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(SOURCE.parent))


def check(condition, message):
    if not condition:
        raise AssertionError(message)


addon = importlib.import_module(PACKAGE)
entry = None
if not INSTALLED_PACKAGE:
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
curve = importlib.import_module(f"{PACKAGE}.cage_deform.curve")
core = deform.core


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def operator_proxy(target, modifier, controller, guide, spline):
    operator = SimpleNamespace(
        _guide_context=lambda: (
            target, modifier, controller, guide, spline),
        _selected_indices=lambda properties: tuple(
            index for index, point in enumerate(properties.curve_points)
            if point.selected),
        _element_world=lambda item, points, kind, index: (
            curve.SDH_OT_edit_curve_cage_object._element_world(
                operator, item, points, kind, index)),
        _set_header=lambda _context: None,
        _area=None,
        _proportional_radius=math.nan,
    )
    operator._initialize_proportional_radius = lambda context: (
        curve.SDH_OT_edit_curve_cage_object._initialize_proportional_radius(
            operator, context))
    operator._proportional_weights = lambda context, force_global=False: (
        curve.SDH_OT_edit_curve_cage_object._proportional_weights(
            operator, context, force_global=force_global))
    operator._local_move_delta = lambda _event, _guide: Vector((1.0, 0.0, 0.0))
    return operator


def main():
    check(core._CURVE_WORKSPACE_TOOL_REGISTERED,
          "Curve Workspace Tool was not registered")
    curve_drag_items = tuple(
        item for item in core.SDH_WST_curve_edit.bl_keymap
        if item[0] == "sdh.edit_curve_cage_object" and
        item[1].get("value") == "CLICK_DRAG")
    check(len(curve_drag_items) == 4,
          "Curve Workspace Tool lost modifier-aware drag variants")

    mesh = bpy.data.meshes.new("SDH Curve Falloff Mesh")
    mesh.from_pydata(((-1.0, -2.0, 0.0), (1.0, 2.0, 0.0)), (), ())
    target = bpy.data.objects.new("SDH Curve Falloff", mesh)
    bpy.context.collection.objects.link(target)
    activate(target)
    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, target, cage_type="CURVE")
    properties = controller.sdh_cage_deform
    guide = curve.curve_guide_object(target, modifier)
    spline = curve.curve_guide_spline(guide)
    curve.ensure_curve_point_collection(properties, guide)
    check(len(spline.bezier_points) >= 3, "Curve guide has too few points")

    active = len(spline.bezier_points) // 2
    for index, control in enumerate(properties.curve_points):
        control.selected = index == active
    properties.curve_active_point = active

    settings = bpy.context.scene.tool_settings
    previous = (
        bool(settings.use_proportional_edit_objects),
        float(settings.proportional_size),
        str(settings.proportional_edit_falloff),
    )
    try:
        settings.use_proportional_edit_objects = True
        settings.proportional_size = max(float(properties.size[1]), 1.0)
        settings.proportional_edit_falloff = "LINEAR"

        original_x = tuple(float(point.co.x) for point in spline.bezier_points)
        operator = operator_proxy(
            target, modifier, controller, guide, spline)
        event = SimpleNamespace(
            mouse_region_x=10, mouse_region_y=10,
            shift=False, ctrl=False, alt=False)
        check(curve.SDH_OT_edit_curve_cage_object._begin_transform(
            operator, bpy.context, event, "MOVE"),
              "Curve proportional Move did not start")
        check(len(operator._transform_original) == len(spline.bezier_points),
              "Curve transform did not snapshot falloff neighbors")
        check(curve.SDH_OT_edit_curve_cage_object._apply_transform(
            operator, bpy.context, event),
              "Curve proportional Move did not apply")
        moved = tuple(float(point.co.x) for point in spline.bezier_points)
        check(abs(moved[active] - original_x[active] - 1.0) < 1.0e-5,
              "Selected Curve point lost full Move influence")
        check(any(
            1.0e-5 < moved[index] - original_x[index] < 1.0 - 1.0e-5
            for index in range(len(moved)) if index != active),
              "Nearby Curve points received no proportional Move")
        curve.SDH_OT_edit_curve_cage_object._finish_transform(
            operator, bpy.context, cancel=True)

        point_control = properties.curve_points[active]
        original_radii = tuple(
            float(point.radius) for point in spline.bezier_points)
        point_control.edit_radius = original_radii[active] + 1.0
        radii = tuple(float(point.radius) for point in spline.bezier_points)
        check(abs(radii[active] - original_radii[active] - 1.0) < 1.0e-5,
              "Active guide-point radius lost full influence")
        check(any(
            original_radii[index] < radii[index] < original_radii[index] + 1.0
            for index in range(len(radii)) if index != active),
              "Guide-point radius did not use proportional falloff")

        original_tilts = tuple(
            float(point.tilt) for point in spline.bezier_points)
        point_control.edit_tilt = original_tilts[active] + 0.75
        tilts = tuple(float(point.tilt) for point in spline.bezier_points)
        check(abs(tilts[active] - original_tilts[active] - 0.75) < 1.0e-5,
              "Active guide-point twist lost full influence")
        check(any(
            original_tilts[index] < tilts[index] < original_tilts[index] + 0.75
            for index in range(len(tilts)) if index != active),
              "Guide-point twist did not use proportional falloff")

        points = properties.curve_points
        selected_pair = {active, min(active + 1, len(points) - 1)}
        for index, control in enumerate(points):
            control.selected = index in selected_pair
        settings.use_proportional_edit_objects = False
        original_bevels = tuple(float(control.bevel) for control in points)
        point_control.edit_bevel = original_bevels[active] - 0.25
        changed_bevels = tuple(float(control.bevel) for control in points)
        check(all(
            abs(changed_bevels[index] - original_bevels[index] + 0.25) < 1.0e-5
            for index in selected_pair),
              "Selected guide-point bevels did not edit together")
        check(all(
            abs(changed_bevels[index] - original_bevels[index]) < 1.0e-5
            for index in range(len(points)) if index not in selected_pair),
              "Guide-point bevel changed outside the selection")

        original_tensions = tuple(float(control.tension) for control in points)
        point_control.edit_tension = original_tensions[active] + 0.5
        changed_tensions = tuple(float(control.tension) for control in points)
        check(all(
            abs(changed_tensions[index] - original_tensions[index] - 0.5) < 1.0e-5
            for index in selected_pair),
              "Selected guide-point tensions did not edit together")
        check(all(
            abs(changed_tensions[index] - original_tensions[index]) < 1.0e-5
            for index in range(len(points)) if index not in selected_pair),
            "Guide-point tension changed outside the selection")

        # Native Curve Edit Mode can own the selection when a box-select is
        # performed outside the persistent editor.  Panel edits must retain
        # that multi-point selection even if the mirrored PropertyGroup flags
        # have not been refreshed yet.
        for control in points:
            control.selected = False
        for native_point in spline.bezier_points:
            native_point.select_control_point = False
            native_point.select_left_handle = False
            native_point.select_right_handle = False
        native_pair = {active, min(active + 2, len(points) - 1)}
        for index in native_pair:
            spline.bezier_points[index].select_control_point = True
        native_radii = tuple(float(point.radius) for point in spline.bezier_points)
        point_control.edit_radius = native_radii[active] + 0.15
        changed_native_radii = tuple(
            float(point.radius) for point in spline.bezier_points)
        check(all(
            abs(changed_native_radii[index] - native_radii[index] - 0.15) < 1.0e-5
            for index in native_pair),
            "Native Curve multi-selection was not retained for radius")
        native_bevels = tuple(float(control.bevel) for control in points)
        point_control.edit_bevel = native_bevels[active] - 0.1
        changed_native_bevels = tuple(float(control.bevel) for control in points)
        check(all(
            abs(changed_native_bevels[index] - native_bevels[index] + 0.1) < 1.0e-5
            for index in native_pair),
            "Native Curve multi-selection was not retained for bevel")

        properties.curve_point_global_falloff = True
        world_points = {
            index: guide.matrix_world @ Vector(point.co)
            for index, point in enumerate(spline.bezier_points)
        }
        weights, global_radius = curve.curve_proportional_weights(
            world_points, selected_pair, bpy.context,
            force=True, cover_all=True)
        check(global_radius > 0.0 and all(weight > 0.0 for weight in weights.values()),
              "Full Curve Falloff did not cover every guide point")

        global_radii = tuple(
            float(point.radius) for point in spline.bezier_points)
        point_control.edit_radius = global_radii[active] + 0.2
        changed_global_radii = tuple(
            float(point.radius) for point in spline.bezier_points)
        check(all(
            changed_global_radii[index] > global_radii[index]
            for index in range(len(global_radii))),
              "Full Curve Falloff did not reach every point radius")

        global_tilts = tuple(
            float(point.tilt) for point in spline.bezier_points)
        point_control.edit_tilt = global_tilts[active] + 0.2
        changed_global_tilts = tuple(
            float(point.tilt) for point in spline.bezier_points)
        check(all(
            changed_global_tilts[index] > global_tilts[index]
            for index in range(len(global_tilts))),
              "Full Curve Falloff did not reach every point roll")

        global_bevels = tuple(float(control.bevel) for control in points)
        point_control.edit_bevel = global_bevels[active] - 0.1
        changed_global_bevels = tuple(float(control.bevel) for control in points)
        check(all(
            changed_global_bevels[index] < global_bevels[index]
            for index in range(len(global_bevels))),
              "Full Curve Falloff did not reach every point bevel")

        global_tensions = tuple(float(control.tension) for control in points)
        point_control.edit_tension = global_tensions[active] + 0.2
        changed_global_tensions = tuple(
            float(control.tension) for control in points)
        check(all(
            changed_global_tensions[index] > global_tensions[index]
            for index in range(len(global_tensions))),
              "Full Curve Falloff did not reach every point tension")

        # The same Full Curve mode must apply to the modal Alt+S / Ctrl+T
        # profile transforms even when Blender proportional editing is off.
        settings.use_proportional_edit_objects = False
        for index, control in enumerate(points):
            control.selected = index in selected_pair
        modal_profile = operator_proxy(
            target, modifier, controller, guide, spline)
        profile_start = SimpleNamespace(
            mouse_region_x=10, mouse_region_y=10,
            shift=False, ctrl=False, alt=False)
        profile_drag = SimpleNamespace(
            mouse_region_x=30, mouse_region_y=10,
            shift=False, ctrl=False, alt=False)
        before_modal_radius = tuple(
            float(point.radius) for point in spline.bezier_points)
        check(curve.SDH_OT_edit_curve_cage_object._begin_transform(
            modal_profile, bpy.context, profile_start, "RADIUS"),
              "Full Curve modal radius transform did not start")
        check(curve.SDH_OT_edit_curve_cage_object._apply_transform(
            modal_profile, bpy.context, profile_drag),
              "Full Curve modal radius transform did not apply")
        after_modal_radius = tuple(
            float(point.radius) for point in spline.bezier_points)
        check(all(
            after_modal_radius[index] > before_modal_radius[index]
            for index in range(len(after_modal_radius))),
              "Full Curve modal radius did not reach every guide point")
        curve.SDH_OT_edit_curve_cage_object._finish_transform(
            modal_profile, bpy.context, cancel=True)

        modal_profile = operator_proxy(
            target, modifier, controller, guide, spline)
        before_modal_tilt = tuple(
            float(point.tilt) for point in spline.bezier_points)
        check(curve.SDH_OT_edit_curve_cage_object._begin_transform(
            modal_profile, bpy.context, profile_start, "TILT"),
              "Full Curve modal twist transform did not start")
        check(curve.SDH_OT_edit_curve_cage_object._apply_transform(
            modal_profile, bpy.context, profile_drag),
              "Full Curve modal twist transform did not apply")
        after_modal_tilt = tuple(
            float(point.tilt) for point in spline.bezier_points)
        check(all(
            after_modal_tilt[index] > before_modal_tilt[index]
            for index in range(len(after_modal_tilt))),
              "Full Curve modal twist did not reach every guide point")
        curve.SDH_OT_edit_curve_cage_object._finish_transform(
            modal_profile, bpy.context, cancel=True)
        properties.curve_point_global_falloff = False
        settings.use_proportional_edit_objects = True

        activate(target)
        target.modifiers.active = modifier
        bpy.ops.sdh.add_curve_station()
        bpy.ops.sdh.add_curve_station()
        stations = properties.curve_stations
        controller_pointer = int(controller.as_pointer())
        curve._STATION_SYNC_GUARD.add(controller_pointer)
        try:
            irregular = (0.0, 0.08, 0.61, 0.93, 1.0)
            for station, factor in zip(stations, irregular):
                station.factor = factor
        finally:
            curve._STATION_SYNC_GUARD.discard(controller_pointer)
        check(bpy.ops.sdh.equalize_curve_stations() == {"FINISHED"},
              "Cross-section equalize operator failed")
        expected = tuple(
            index / (len(stations) - 1) for index in range(len(stations)))
        check(all(
            abs(float(station.factor) - factor) < 1.0e-7
            for station, factor in zip(stations, expected)),
              "Cross sections were not evenly distributed")

        properties.curve_even_stations = True
        stations[len(stations) // 2].factor = 0.11
        expected = tuple(
            index / (len(stations) - 1) for index in range(len(stations)))
        check(all(
            abs(float(station.factor) - factor) < 1.0e-7
            for station, factor in zip(stations, expected)),
              "Even Cross Sections did not reject an uneven adjustment")

        before_add = len(stations)
        bpy.ops.sdh.add_curve_station()
        check(len(stations) == before_add + 1,
              "Even Cross Sections prevented station insertion")
        expected = tuple(
            index / (len(stations) - 1) for index in range(len(stations)))
        check(all(
            abs(float(station.factor) - factor) < 1.0e-7
            for station, factor in zip(stations, expected)),
              "Even Cross Sections did not redistribute after insertion")
        properties.curve_active_station = len(stations) // 2
        bpy.ops.sdh.remove_curve_station()
        check(len(stations) == before_add,
              "Even Cross Sections prevented station removal")
        expected = tuple(
            index / (len(stations) - 1) for index in range(len(stations)))
        check(all(
            abs(float(station.factor) - factor) < 1.0e-7
            for station, factor in zip(stations, expected)),
              "Even Cross Sections did not redistribute after removal")

        station_active = len(stations) // 2
        properties.curve_active_station = station_active
        station = stations[station_active]
        station_radii = tuple(float(item.radius) for item in stations)
        station.edit_radius = station_radii[station_active] + 1.0
        changed_radii = tuple(float(item.radius) for item in stations)
        check(abs(
            changed_radii[station_active] -
            station_radii[station_active] - 1.0) < 1.0e-5,
              "Active cross-section radius lost full influence")
        check(any(
            station_radii[index] < changed_radii[index] <
            station_radii[index] + 1.0
            for index in range(len(stations)) if index != station_active),
              "Cross-section radius did not use proportional falloff")

        station_twists = tuple(float(item.twist) for item in stations)
        station.edit_twist = station_twists[station_active] + 0.5
        changed_twists = tuple(float(item.twist) for item in stations)
        check(abs(
            changed_twists[station_active] -
            station_twists[station_active] - 0.5) < 1.0e-5,
              "Active cross-section twist lost full influence")
        check(any(
            station_twists[index] < changed_twists[index] <
            station_twists[index] + 0.5
            for index in range(len(stations)) if index != station_active),
              "Cross-section twist did not use proportional falloff")
    finally:
        (
            settings.use_proportional_edit_objects,
            settings.proportional_size,
            settings.proportional_edit_falloff,
        ) = previous
    print("SDH_CURVE_PROPORTIONAL::PASS")


try:
    main()
finally:
    if not INSTALLED_PACKAGE:
        try:
            addon.unregister()
        except Exception:
            pass
        if entry is not None:
            try:
                bpy.context.preferences.addons.remove(entry)
            except (ReferenceError, RuntimeError):
                pass
