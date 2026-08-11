"""Behavioral coverage for Curve length, boundary, and volume modes."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import bpy
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))


def fail(message):
    raise AssertionError(message)


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.hide_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def coordinates(obj):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return tuple(Vector(vertex.co) for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def guide_endpoints_local(obj, guide):
    bpy.context.view_layer.update()
    spline = guide.data.splines[0]
    matrix = obj.matrix_world.inverted_safe() @ guide.matrix_world
    return (
        matrix @ Vector(spline.bezier_points[0].co),
        matrix @ Vector(spline.bezier_points[-1].co),
    )


def guide_points_local(obj, guide):
    bpy.context.view_layer.update()
    spline = guide.data.splines[0]
    matrix = obj.matrix_world.inverted_safe() @ guide.matrix_world
    return tuple(matrix @ Vector(point.co) for point in spline.bezier_points)


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
curve = importlib.import_module(f"{PACKAGE}.cage_deform.curve")

source = (
    (-1.0, 0.0, -3.0), (0.0, 0.0, -3.0), (1.0, 0.0, -3.0),
    (-1.0, 0.0, 0.0), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
    (-1.0, 0.0, 3.0), (0.0, 0.0, 3.0), (1.0, 0.0, 3.0),
)
mesh = bpy.data.meshes.new("SDH Curve Modes Mesh")
mesh.from_pydata(source, (), ())
target = bpy.data.objects.new("SDH Curve Modes", mesh)
bpy.context.collection.objects.link(target)
activate(target)

try:
    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, target, cage_type="CURVE")
    properties = controller.sdh_cage_deform
    guide = curve.curve_guide_object(target, modifier)
    points = guide.data.splines[0].bezier_points
    points[1].co.x = 2.0
    points[2].co.y = 6.0
    guide.data.update_tag()

    properties.curve_boundary_mode = "CLAMP"
    properties.curve_preserve_volume = False
    properties.curve_length_mode = "STRETCH"
    deform.sync_controller(controller, pull_transform=False, sync_mode="push")
    stretched = coordinates(target)
    properties.curve_length_mode = "PRESERVE"
    preserved = coordinates(target)
    properties.curve_length_mode = "FIT_GUIDE"
    fitted = coordinates(target)
    if (stretched[7] - preserved[7]).length < 0.5:
        fail("Preserve Length did not differ from Stretch to Path")
    if (stretched[7] - fitted[7]).length < 0.5:
        fail("Fit Guide to Cage did not rescale the complete guide")

    properties.curve_length_mode = "STRETCH"
    properties.curve_preserve_volume = False
    uncompensated = coordinates(target)
    uncompensated_radius = (uncompensated[5] - uncompensated[4]).length
    properties.curve_preserve_volume = True
    compensated = coordinates(target)
    compensated_radius = (compensated[5] - compensated[4]).length
    if not compensated_radius < uncompensated_radius * 0.95:
        fail(
            "Curve volume compensation did not reduce the stretched section: "
            f"{uncompensated_radius} -> {compensated_radius}")

    # Curve range handles are an effect mask inside an immutable source
    # domain. They must never resize/recenter the cage or rewrite the guide.
    # Limited continues excluded geometry rigidly along the nearest boundary
    # tangent, Within Box leaves it untouched, and Unlimited ignores the mask.
    properties.curve_control_mode = "CURVE"
    properties.curve_preserve_volume = False
    properties.curve_length_mode = "STRETCH"
    initial_size = tuple(properties.size)
    initial_location = tuple(controller.location)
    initial_guide = guide_points_local(target, guide)
    initial_range = (
        float(properties.curve_range_start),
        float(properties.curve_range_end),
    )
    range_axis_length = abs(float(initial_size[1]))
    if any(abs(value - expected) > 1.0e-7 for value, expected in zip(
            initial_range, (0.0, 1.0))):
        fail(f"Curve effect range default changed: {initial_range!r}")
    full_mapping = coordinates(target)
    properties.curve_mode = "UNLIMITED"
    unlimited_baseline = coordinates(target)

    def assert_domain_unchanged(label):
        if max(abs(float(left) - float(right)) for left, right in zip(
                properties.size, initial_size)) > 1.0e-7:
            fail(f"{label} changed the Curve cage size")
        if (Vector(controller.location) - Vector(initial_location)).length > 1.0e-7:
            fail(f"{label} changed the Curve cage location")
        current_guide = guide_points_local(target, guide)
        if max((left - right).length for left, right in zip(
                current_guide, initial_guide)) > 1.0e-5:
            fail(f"{label} moved the Curve guide")

    deform.move_curve_effect_boundary(
        controller, "TOP", -range_axis_length * 0.5,
        initial_range=initial_range,
        axis_limits=None,
        boundary_mode="SINGLE",
    )
    if abs(float(properties.curve_range_start)) > 1.0e-7 or abs(
            float(properties.curve_range_end) - 0.5) > 1.0e-7:
        fail("Top handle did not edit only Curve Range End")
    assert_domain_unchanged("Top effect boundary")
    properties.curve_mode = "LIMITED"
    top_limited = coordinates(target)
    properties.curve_mode = "WITHIN_BOX"
    top_within = coordinates(target)
    properties.curve_mode = "UNLIMITED"
    top_unlimited = coordinates(target)
    top_spacing = (top_limited[7] - top_limited[4]).length
    if abs(top_spacing - 3.0) > 2.0e-4:
        fail(
            "Limited collapsed or rescaled geometry above its range: "
            f"{top_spacing}")
    if (top_within[7] - Vector(source[7])).length > 2.0e-4:
        fail("Within Box changed geometry above its effect range")
    if max((left - right).length for left, right in zip(
            top_unlimited, unlimited_baseline)) > 2.0e-4:
        fail("Unlimited was affected by the inward top range")
    properties.curve_mode = "LIMITED"
    deform.move_curve_effect_boundary(
        controller, "TOP", 0.0,
        initial_range=initial_range,
        axis_limits=None,
        boundary_mode="SINGLE",
    )
    if (
            abs(float(properties.curve_range_start) - initial_range[0]) > 1.0e-7 or
            abs(float(properties.curve_range_end) - initial_range[1]) > 1.0e-7
    ):
        fail("Top boundary cancellation did not restore the complete range")
    assert_domain_unchanged("Top boundary cancellation")
    restored_top = coordinates(target)
    if max((left - right).length for left, right in zip(
            restored_top, full_mapping)) > 2.0e-4:
        fail("Restoring the top boundary lost complete guide mapping")

    deform.move_curve_effect_boundary(
        controller, "BOTTOM", range_axis_length * 0.5,
        initial_range=initial_range,
        axis_limits=None,
        boundary_mode="SINGLE",
    )
    if abs(float(properties.curve_range_start) - 0.5) > 1.0e-7 or abs(
            float(properties.curve_range_end) - 1.0) > 1.0e-7:
        fail("Bottom handle did not edit only Curve Range Start")
    assert_domain_unchanged("Bottom effect boundary")
    properties.curve_mode = "LIMITED"
    bottom_limited = coordinates(target)
    properties.curve_mode = "WITHIN_BOX"
    bottom_within = coordinates(target)
    properties.curve_mode = "UNLIMITED"
    bottom_unlimited = coordinates(target)
    bottom_spacing = (bottom_limited[4] - bottom_limited[1]).length
    if abs(bottom_spacing - 3.0) > 2.0e-4:
        fail(
            "Limited collapsed or rescaled geometry below its range: "
            f"{bottom_spacing}")
    if (bottom_within[1] - Vector(source[1])).length > 2.0e-4:
        fail("Within Box changed geometry below its effect range")
    if max((left - right).length for left, right in zip(
            bottom_unlimited, unlimited_baseline)) > 2.0e-4:
        fail("Unlimited was affected by the inward bottom range")
    properties.curve_mode = "LIMITED"
    deform.move_curve_effect_boundary(
        controller, "BOTTOM", 0.0,
        initial_range=initial_range,
        axis_limits=None,
        boundary_mode="SINGLE",
    )
    if (
            abs(float(properties.curve_range_start) - initial_range[0]) > 1.0e-7 or
            abs(float(properties.curve_range_end) - initial_range[1]) > 1.0e-7
    ):
        fail("Bottom boundary cancellation did not restore the complete range")
    assert_domain_unchanged("Bottom boundary cancellation")
    restored_bottom = coordinates(target)
    if max((left - right).length for left, right in zip(
            restored_bottom, full_mapping)) > 2.0e-4:
        fail("Restoring the bottom boundary lost complete guide mapping")
    restored_guide = guide_endpoints_local(target, guide)
    if (
            (restored_bottom[1] - restored_guide[0]).length > 2.0e-4 or
            (restored_bottom[7] - restored_guide[1]).length > 2.0e-4
    ):
        fail("Complete source domain no longer maps to the complete guide")

    print("SDH_CURVE_CAGE_MODES::PASS")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
