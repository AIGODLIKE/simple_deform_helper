"""Regression coverage for Curve radius/twist profiles and guide presets."""
from __future__ import annotations

import importlib
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
INSTALLED_PACKAGE = os.environ.get("SDH_TEST_MODULE")
PACKAGE = INSTALLED_PACKAGE or SOURCE.name
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(SOURCE.parent))


def fail(message):
    raise AssertionError(message)


def close(left, right, tolerance=1.0e-5):
    return abs(float(left) - float(right)) <= tolerance


def close_vector(left, right, tolerance=1.0e-5):
    return len(left) == len(right) and all(
        close(a, b, tolerance) for a, b in zip(left, right))


def activate(obj):
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.hide_set(False)
    obj.hide_select = False
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def evaluated_coordinates(obj):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return tuple(Vector(vertex.co) for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def preview_coordinates(obj, controller):
    cage_matrix = deform.cage_local_matrix(obj, controller)
    cage_inverse = cage_matrix.inverted_safe()
    object_inverse = obj.matrix_world.inverted_safe()
    local_points = tuple(
        cage_inverse @ (obj.matrix_world @ vertex.co)
        for vertex in obj.data.vertices)
    return tuple(
        object_inverse @ (
            cage_matrix @ deform.deform_point_from_properties(
                local_point,
                controller.sdh_cage_deform,
                chain_preview=True,
            )
        )
        for local_point in local_points
    )


def maximum_error(left, right):
    return max((Vector(a) - Vector(b)).length for a, b in zip(left, right))


def assert_preview(label, target, controller, tolerance=3.0e-3):
    actual = evaluated_coordinates(target)
    preview = preview_coordinates(target, controller)
    error = maximum_error(actual, preview)
    if error > tolerance:
        fail(f"{label} GN/Python preview mismatch: {error}")
    return actual


def action_paths(id_data):
    animation = getattr(id_data, "animation_data", None)
    action = getattr(animation, "action", None) if animation else None
    return {
        str(fcurve.data_path)
        for fcurve in deform.core._iter_baked_action_fcurves(action)
    }


def attribute_values(mesh, name):
    attribute = mesh.attributes.get(name)
    if attribute is None:
        fail(f"Curve station helper is missing {name!r}")
    return tuple(float(item.value) for item in attribute.data)


def preset_coordinates(guide):
    spline = curve.curve_guide_spline(guide)
    return spline, tuple(Vector(point.co) for point in spline.bezier_points)


def expected_preset_coordinate(
        preset, factor, half_length, amplitude, cycles, phase):
    y = -half_length + 2.0 * half_length * factor
    angle = phase + math.tau * cycles * factor
    if preset == "SINE":
        return Vector((amplitude * math.sin(angle), y, 0.0))
    if preset == "WAVE":
        return Vector((
            amplitude * math.sin(angle),
            y,
            amplitude * 0.35 * math.sin(2.0 * angle),
        ))
    if preset == "HELIX":
        return Vector((amplitude * math.cos(angle), y, amplitude * math.sin(angle)))
    return Vector((0.0, y, 0.0))


addon = importlib.import_module(PACKAGE)
entry = None
if not INSTALLED_PACKAGE:
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
curve = importlib.import_module(f"{PACKAGE}.cage_deform.curve")
presets = importlib.import_module(f"{PACKAGE}.cage_deform.curve_presets")


vertices = [
    (x, y, z)
    for z in (-2.0, -1.0, 0.0, 1.0, 2.0)
    for y in (-0.35, 0.2)
    for x in (-0.6, 0.3)
]
mesh = bpy.data.meshes.new("SDH Curve Radius Twist Mesh")
mesh.from_pydata(vertices, (), ())
target = bpy.data.objects.new("SDH Curve Radius Twist", mesh)
bpy.context.collection.objects.link(target)
activate(target)

try:
    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, target, cage_type="CURVE")
    properties = controller.sdh_cage_deform
    guide = curve.curve_guide_object(target, modifier)
    station_object = curve.curve_station_object(target, modifier)
    if guide is None or station_object is None:
        fail("Curve radius/twist test did not create its managed helpers")
    if not close(properties.curve_global_radius, 1.0):
        fail("Curve Global Radius no longer defaults to 1.0")
    if not close(properties.curve_global_twist, 0.0):
        fail("Curve Global Twist no longer defaults to zero")
    if any(
            not close(station.radius, 1.0) or not close(station.twist, 0.0)
            for station in properties.curve_stations):
        fail("Curve cross-section radius/twist defaults changed")

    # Explicit defaults must preserve the pre-feature Curve result.
    default_result = assert_preview("Default Curve profile", target, controller)
    default_error = maximum_error(default_result, tuple(Vector(v) for v in vertices))
    if default_error > 2.0e-4:
        fail(f"Default radius/twist changed legacy Curve output: {default_error}")

    properties.curve_global_radius = 1.55
    properties.curve_global_twist = 0.0
    deform.sync_controller(controller, pull_transform=False, sync_mode="push")
    radius_result = assert_preview("Global Curve radius", target, controller)
    if maximum_error(radius_result, default_result) < 0.2:
        fail("Global Curve radius did not affect evaluated geometry")
    properties.curve_global_twist = math.radians(32.0)
    global_result = assert_preview("Global Curve twist", target, controller)
    if maximum_error(global_result, radius_result) < 0.1:
        fail("Global Curve twist did not affect evaluated geometry")

    authored = (
        ((0.8, 1.2), (0.12, -0.05), 0.7, math.radians(-20.0)),
        ((1.1, 0.9), (-0.08, 0.1), 1.2, math.radians(10.0)),
        ((1.4, 0.75), (0.2, 0.06), 1.6, math.radians(45.0)),
    )
    for station, (_scale, _offset, radius, twist) in zip(
            properties.curve_stations, authored):
        station.scale = (1.0, 1.0)
        station.offset = (0.0, 0.0)
        station.radius = radius
        station.twist = twist
    curve.update_curve_station_mesh(target, modifier, controller)
    profiled_result = assert_preview(
        "Station Curve radius/twist", target, controller)
    if maximum_error(profiled_result, global_result) < 0.1:
        fail("Station radius/twist gradient did not affect evaluated geometry")

    for station, (scale, offset, _radius, _twist) in zip(
            properties.curve_stations, authored):
        station.scale = scale
        station.offset = offset
    curve.update_curve_station_mesh(target, modifier, controller)
    assert_preview("Combined Curve profile layers", target, controller)

    midpoint = curve._curve_station_values(properties, 0.25)
    if not close_vector(midpoint[0], (0.95, 1.05)):
        fail(f"Station scale interpolation changed: {tuple(midpoint[0])!r}")
    if not close_vector(midpoint[1], (0.02, 0.025)):
        fail(f"Station offset interpolation changed: {tuple(midpoint[1])!r}")
    if not close(midpoint[2], 0.95):
        fail(f"Station radius interpolation changed: {midpoint[2]}")
    if not close(midpoint[3], math.radians(-5.0)):
        fail(f"Station twist interpolation changed: {midpoint[3]}")

    station_mesh = station_object.data
    if not close_vector(
            attribute_values(station_mesh, curve.CURVE_RADIUS_ATTRIBUTE),
            (0.7, 1.2, 1.6)):
        fail("Station radius values were not written to the GN helper mesh")
    if not close_vector(
            attribute_values(station_mesh, curve.CURVE_TWIST_ATTRIBUTE),
            tuple(item[3] for item in authored)):
        fail("Station twist values were not written to the GN helper mesh")

    properties.curve_active_station = 0
    activate(target)
    target.modifiers.active = modifier
    if bpy.ops.sdh.add_curve_station() != {"FINISHED"}:
        fail("Adding an interpolated Curve cross section failed")
    inserted = properties.curve_stations[1]
    if (
            not close(inserted.factor, 1.0 / 3.0) or
            not close(inserted.radius, 0.95) or
            not close(inserted.twist, math.radians(-5.0))
    ):
        fail(
            "Inserted Curve cross section did not interpolate radius/twist: "
            f"{inserted.factor}, {inserted.radius}, {inserted.twist}")

    # Radius only scales coordinates around the authored station offset.
    properties.curve_global_twist = 0.0
    for station in properties.curve_stations:
        station.scale = (1.0, 1.0)
        station.offset = (0.25, -0.15)
        station.radius = 1.0
        station.twist = 0.0
    properties.curve_global_radius = 1.0
    center_one = curve.curve_preview_deformer(properties)(
        Vector((0.0, 0.0, 0.0)), 0.0, properties.size)
    properties.curve_global_radius = 2.0
    center_two = curve.curve_preview_deformer(properties)(
        Vector((0.0, 0.0, 0.0)), 0.0, properties.size)
    if (center_one - center_two).length > 1.0e-5:
        fail("Curve radius incorrectly scaled the station center offset")

    # Native Bezier point Radius/Roll remains the base layer under the new
    # global and station profile rather than being replaced by it.
    spline = curve.curve_guide_spline(guide)
    properties.curve_global_radius = 1.25
    properties.curve_global_twist = math.radians(15.0)
    for point in spline.bezier_points:
        point.radius = 1.0
        point.tilt = 0.0
    guide.data.update_tag()
    before_native = assert_preview(
        "Curve profile before native point layers", target, controller)
    for point in spline.bezier_points:
        point.radius = 1.2
        point.tilt = math.radians(12.0)
    guide.data.update_tag()
    native_result = assert_preview(
        "Native point plus Curve profile", target, controller)
    if maximum_error(native_result, before_native) < 0.1:
        fail("Native point Radius/Roll did not compose with the Curve profile")

    # Stretch compensation must still compose with native/global/station
    # radius. Doubling guide length shrinks cross sections by sqrt(2).
    for point in spline.bezier_points:
        point.co.y *= 2.0
        point.handle_left.y *= 2.0
        point.handle_right.y *= 2.0
    guide.data.update_tag()
    properties.curve_length_mode = "STRETCH"
    properties.curve_preserve_volume = False
    uncompensated = assert_preview(
        "Uncompensated Curve profile", target, controller)
    properties.curve_preserve_volume = True
    compensated = assert_preview(
        "Volume-compensated Curve profile", target, controller)
    uncompensated_width = (uncompensated[9] - uncompensated[8]).length
    compensated_width = (compensated[9] - compensated[8]).length
    expected_ratio = math.sqrt(0.5)
    if not close(
            compensated_width / max(uncompensated_width, 1.0e-8),
            expected_ratio, 2.0e-3):
        fail(
            "Curve radius did not compose with volume compensation: "
            f"{uncompensated_width} -> {compensated_width}")

    # Non-default radius/twist must agree with the GN result in every effect
    # boundary mode, including excluded source geometry.
    properties.curve_range_start = 0.25
    properties.curve_range_end = 0.75
    for mode in ("LIMITED", "WITHIN_BOX", "UNLIMITED"):
        properties.curve_mode = mode
        assert_preview(f"Curve {mode} radius/twist", target, controller, 5.0e-3)
    properties.curve_range_start = 0.0
    properties.curve_range_end = 1.0
    properties.curve_mode = "LIMITED"
    properties.curve_preserve_volume = False

    # Closed guides have one physical seam, so all profile fields must match
    # at the first and last stations.
    properties.curve_stations[0].radius = 0.85
    properties.curve_stations[0].twist = math.radians(24.0)
    properties.curve_stations[-1].radius = 1.4
    properties.curve_stations[-1].twist = math.radians(-35.0)
    properties.curve_closed = True
    if (
            not close(properties.curve_stations[-1].radius, 0.85) or
            not close(properties.curve_stations[-1].twist, math.radians(24.0))
    ):
        fail("Closing a Curve did not synchronize station radius/twist")
    properties.curve_stations[-1].radius = 1.1
    properties.curve_stations[-1].twist = math.radians(-18.0)
    if (
            not close(properties.curve_stations[0].radius, 1.1) or
            not close(properties.curve_stations[0].twist, math.radians(-18.0))
    ):
        fail("Editing a closed Curve seam did not mirror radius/twist")
    properties.curve_closed = False

    # The modifier-to-controller restore path is the node-group upgrade path
    # used by existing files.
    deform.core.set_modifier_input(modifier, "Curve Global Radius", 1.375)
    deform.core.set_modifier_input(
        modifier, "Curve Global Twist", math.radians(27.0))
    deform.core._restore_controller_from_modifier(controller, modifier)
    if (
            not close(properties.curve_global_radius, 1.375) or
            not close(properties.curve_global_twist, math.radians(27.0))
    ):
        fail("Curve global radius/twist were not restored from modifier inputs")

    # Topology-changing presets and equalization must reject every Blender
    # feature that retains one channel or value per existing guide point.
    activate(target)
    target.modifiers.active = modifier
    driver_path = "splines[0].bezier_points[0].co"
    guide.data.driver_add(driver_path, 0)
    try:
        before_count = len(curve.curve_guide_spline(guide).bezier_points)
        before_coordinates = preset_coordinates(guide)[1]
        if not curve._curve_data_has_point_animation(guide.data):
            fail("Curve point driver was not detected as a topology dependency")
        properties.curve_preset = "SINE"
        if preset_coordinates(guide)[1] != before_coordinates:
            fail("Live Curve preset overwrote a driver-backed guide")
        if bpy.ops.sdh.apply_curve_preset(preset="SINE") != {"CANCELLED"}:
            fail("Curve preset overwrote a driver-backed guide")
        if len(curve.curve_guide_spline(guide).bezier_points) != before_count:
            fail("Rejected Curve preset still changed driver-backed topology")
    finally:
        guide.data.driver_remove(driver_path, 0)

    guide.data.keyframe_insert(driver_path, index=1, frame=1.0)
    animation = guide.data.animation_data
    nla_action = animation.action
    nla_track = animation.nla_tracks.new()
    nla_track.name = "Topology Guard"
    nla_track.strips.new("Topology Guard", 1, nla_action)
    animation.action = None
    try:
        before_count = len(curve.curve_guide_spline(guide).bezier_points)
        before_coordinates = preset_coordinates(guide)[1]
        if not curve._curve_data_has_point_animation(guide.data):
            fail("Curve NLA point animation was not detected")
        properties.curve_preset = "WAVE"
        if preset_coordinates(guide)[1] != before_coordinates:
            fail("Live Curve preset overwrote an NLA-backed guide")
        if bpy.ops.sdh.apply_curve_preset(preset="WAVE") != {"CANCELLED"}:
            fail("Curve preset overwrote an NLA-backed guide")
        if len(curve.curve_guide_spline(guide).bezier_points) != before_count:
            fail("Rejected Curve preset still changed NLA-backed topology")
    finally:
        guide.data.animation_data_clear()
        if nla_action.users == 0:
            bpy.data.actions.remove(nla_action)

    guide.shape_key_add(name="Basis")
    guide.shape_key_add(name="Topology Guard")
    try:
        before_count = len(curve.curve_guide_spline(guide).bezier_points)
        before_coordinates = preset_coordinates(guide)[1]
        if not curve._curve_data_has_point_animation(guide.data):
            fail("Curve shape keys were not detected as a topology dependency")
        properties.curve_preset = "HELIX"
        if preset_coordinates(guide)[1] != before_coordinates:
            fail("Live Curve preset overwrote a shape-key-backed guide")
        if bpy.ops.sdh.apply_curve_preset(preset="HELIX") != {"CANCELLED"}:
            fail("Curve preset overwrote a shape-key-backed guide")
        if len(curve.curve_guide_spline(guide).bezier_points) != before_count:
            fail("Rejected Curve preset still changed shape-key topology")
    finally:
        guide.shape_key_clear()

    # Panel properties are live controls. Every edit must regenerate the
    # guide immediately without requiring the compatibility operator.
    half_length = max(abs(float(properties.size[1])) * 0.5, 1.0e-5)
    properties.curve_preset_points = 10
    properties.curve_preset_amplitude = 0.65
    properties.curve_preset_cycles = 1.25
    properties.curve_preset_phase = 0.2
    properties.curve_preset = "SINE"
    live_spline, live_coordinates = preset_coordinates(guide)
    if len(live_coordinates) != 10:
        fail("Live Curve preset point count was not applied")
    for index, coordinate in enumerate(live_coordinates):
        factor = index / float(len(live_coordinates) - 1)
        expected = expected_preset_coordinate(
            "SINE", factor, half_length, 0.65, 1.25, 0.2)
        if (coordinate - expected).length > 1.0e-6:
            fail("Changing the Curve preset did not update the guide live")

    live_pointer = live_spline.as_pointer()
    before_live_result = evaluated_coordinates(target)
    properties.curve_preset_amplitude = 0.9
    properties.curve_preset_cycles = 1.5
    properties.curve_preset_phase = -0.35
    updated_spline, updated_coordinates = preset_coordinates(guide)
    if updated_spline.as_pointer() != live_pointer:
        fail("Continuous Curve preset controls rebuilt unchanged topology")
    for index, coordinate in enumerate(updated_coordinates):
        factor = index / float(len(updated_coordinates) - 1)
        expected = expected_preset_coordinate(
            "SINE", factor, half_length, 0.9, 1.5, -0.35)
        if (coordinate - expected).length > 1.0e-6:
            fail("Curve preset parameters did not update the guide live")
    after_live_result = evaluated_coordinates(target)
    if maximum_error(before_live_result, after_live_result) < 1.0e-3:
        fail("Live Curve preset controls did not update evaluated geometry")

    properties.curve_preset_points = 13
    if len(preset_coordinates(guide)[1]) != 13:
        fail("Live Preset Points did not update guide topology")
    properties.curve_preset = "STRAIGHT"
    straight_spline, straight_coordinates = preset_coordinates(guide)
    if len(straight_coordinates) != 3 or any(
            abs(float(point.x)) > 1.0e-7 or abs(float(point.z)) > 1.0e-7
            for point in straight_coordinates):
        fail("Live Straight preset did not reset the guide")

    preset_cases = (
        ("STRAIGHT", 3, 0.7, 1.0, 0.0),
        ("SINE", 9, 0.7, 1.0, 0.0),
        ("WAVE", 11, 0.6, 1.25, 0.3),
        ("HELIX", 12, 0.8, 1.5, -0.2),
    )
    for preset, requested_count, amplitude, cycles, phase in preset_cases:
        if not presets.apply_curve_preset(
                guide, properties, preset,
                amplitude=amplitude,
                cycles=cycles,
                phase=phase,
                point_count=requested_count):
            fail(f"{preset} Curve preset was not applied")
        preset_spline, coordinates = preset_coordinates(guide)
        expected_count = 3 if preset == "STRAIGHT" else requested_count
        if len(coordinates) != expected_count:
            fail(
                f"{preset} preset created {len(coordinates)} points, "
                f"expected {expected_count}")
        if preset_spline.use_cyclic_u:
            fail(f"{preset} preset unexpectedly created a closed spline")
        for index, (point, coordinate) in enumerate(zip(
                preset_spline.bezier_points, coordinates)):
            factor = index / float(max(expected_count - 1, 1))
            expected = expected_preset_coordinate(
                preset, factor, half_length, amplitude, cycles, phase)
            if (coordinate - expected).length > 1.0e-6:
                fail(
                    f"{preset} preset point {index} is incorrect: "
                    f"{tuple(coordinate)!r} != {tuple(expected)!r}")
            if (
                    point.handle_left_type not in {"AUTO", "FREE"} or
                    point.handle_right_type not in {"AUTO", "FREE"} or
                    not all(math.isfinite(value) for value in point.handle_left) or
                    not all(math.isfinite(value) for value in point.handle_right) or
                    not close(point.radius, 1.0) or
                    not close(point.tilt, 0.0)
            ):
                fail(f"{preset} preset points are not clean editable Bezier points")
        if preset == "STRAIGHT" and any(
                abs(float(point.x)) > 1.0e-7 or abs(float(point.z)) > 1.0e-7
                for point in coordinates):
            fail("Straight preset is not aligned to the cage axis")
        if preset == "SINE" and (
                max(abs(float(point.x)) for point in coordinates) < amplitude * 0.9 or
                any(abs(float(point.z)) > 1.0e-7 for point in coordinates)):
            fail("Sine preset did not create a planar amplitude profile")
        if preset == "WAVE" and (
                max(abs(float(point.x)) for point in coordinates) < amplitude * 0.8 or
                max(abs(float(point.z)) for point in coordinates) < amplitude * 0.2):
            fail("Wave preset did not create both transverse wave components")
        if preset == "HELIX" and any(
                not close(math.hypot(float(point.x), float(point.z)), amplitude)
                for point in coordinates):
            fail("Helix preset did not preserve its authored radius")
        if len(properties.curve_points) != expected_count:
            fail(f"{preset} preset did not refresh native point controls")
        result = evaluated_coordinates(target)
        if not all(math.isfinite(value) for point in result for value in point):
            fail(f"{preset} preset produced non-finite evaluated geometry")

    # All new profile fields participate in keyframing.
    activate(target)
    target.modifiers.active = modifier
    if bpy.ops.sdh.insert_cage_keyframes() != {"FINISHED"}:
        fail("Curve profile keyframe insertion failed")
    expected_paths = {
        "sdh_cage_deform.curve_global_radius",
        "sdh_cage_deform.curve_global_twist",
    }
    expected_paths.update(
        f"sdh_cage_deform.curve_stations[{index}].{suffix}"
        for index in range(len(properties.curve_stations))
        for suffix in ("radius", "twist")
    )
    missing_paths = expected_paths - action_paths(controller)
    if missing_paths:
        fail(f"Curve radius/twist animation paths are missing: {missing_paths!r}")

    # Property copying is used by stage duplication and must preserve both
    # global values and every station profile.
    copy_mesh = mesh.copy()
    copy_target = bpy.data.objects.new("SDH Curve Radius Twist Copy", copy_mesh)
    bpy.context.collection.objects.link(copy_target)
    activate(copy_target)
    copy_modifier, copy_controller, _previous = deform.create_deform_stage(
        bpy.context, copy_target, cage_type="CURVE")
    deform.core._copy_controller_state(copy_controller, controller)
    copied = copy_controller.sdh_cage_deform
    if (
            not close(copied.curve_global_radius, properties.curve_global_radius) or
            not close(copied.curve_global_twist, properties.curve_global_twist) or
            len(copied.curve_stations) != len(properties.curve_stations)
    ):
        fail("Copied Curve controller lost global radius/twist state")
    for index, (source_station, copied_station) in enumerate(zip(
            properties.curve_stations, copied.curve_stations)):
        if (
                not close(source_station.radius, copied_station.radius) or
                not close(source_station.twist, copied_station.twist)
        ):
            fail(f"Copied Curve controller lost station {index} radius/twist")
    if copy_modifier is None:
        fail("Copied Curve test did not create its destination stage")

    print("SDH_CURVE_RADIUS_TWIST_PRESETS::PASS")
finally:
    if not INSTALLED_PACKAGE:
        addon.unregister()
        if entry is not None:
            try:
                bpy.context.preferences.addons.remove(entry)
            except (ReferenceError, RuntimeError):
                pass
