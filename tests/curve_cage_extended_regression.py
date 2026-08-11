"""Regression coverage for closed, editable, resampled Curve cages."""
from __future__ import annotations

import importlib
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


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def close_tuple(values, expected, tolerance=1.0e-5):
    return len(values) == len(expected) and all(
        abs(float(left) - float(right)) <= tolerance
        for left, right in zip(values, expected))


def activate(obj):
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


def average(points):
    result = Vector((0.0, 0.0, 0.0))
    for point in points:
        result += Vector(point)
    return result / max(len(points), 1)


def action_paths(id_data):
    animation = getattr(id_data, "animation_data", None)
    action = getattr(animation, "action", None) if animation else None
    return {
        str(fcurve.data_path)
        for fcurve in deform.core._iter_baked_action_fcurves(action)
    }


def make_circle(spline, radius=2.0):
    data = spline.id_data
    data.splines.clear()
    spline = data.splines.new("BEZIER")
    spline.bezier_points.add(3)
    spline.use_cyclic_u = True
    kappa = radius * 0.5522847498307936
    values = (
        ((0.0, -radius, 0.0), (-kappa, -radius, 0.0),
         (kappa, -radius, 0.0)),
        ((radius, 0.0, 0.0), (radius, -kappa, 0.0),
         (radius, kappa, 0.0)),
        ((0.0, radius, 0.0), (kappa, radius, 0.0),
         (-kappa, radius, 0.0)),
        ((-radius, 0.0, 0.0), (-radius, kappa, 0.0),
         (-radius, -kappa, 0.0)),
    )
    for point, (co, left, right) in zip(spline.bezier_points, values):
        point.co = co
        point.handle_left_type = "FREE"
        point.handle_right_type = "FREE"
        point.handle_left = left
        point.handle_right = right
        point.tilt = 0.0
        point.radius = 1.0
    data.update_tag()
    return spline


addon = importlib.import_module(PACKAGE)
entry = None
if not INSTALLED_PACKAGE:
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
curve = importlib.import_module(f"{PACKAGE}.cage_deform.curve")

mesh = bpy.data.meshes.new("SDH Extended Curve Mesh")
vertices = [
    (x, y, z)
    for z in (-3.0, -1.5, 0.0, 1.5, 3.0)
    for y in (-0.2, 0.2)
    for x in (-0.4, 0.4)
]
mesh.from_pydata(vertices, (), ())
target = bpy.data.objects.new("SDH Extended Curve", mesh)
bpy.context.collection.objects.link(target)
activate(target)

try:
    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, target, cage_type="CURVE")
    properties = controller.sdh_cage_deform
    guide = curve.curve_guide_object(target, modifier)
    spline = curve.curve_guide_spline(guide)

    check(properties.curve_mode == "LIMITED", "Curve mode default is not Limited")

    # Curve handles edit only a normalized effect range inside the stable
    # source domain. The cage and complete guide stay fixed. Limited restores
    # the excluded axial residual along the boundary tangent instead of
    # collapsing every outside cross section onto the boundary frame.
    middle = spline.bezier_points[1]
    middle.co.x += 1.25
    guide.data.update_tag()
    initial_evaluated = evaluated_coordinates(target)
    initial_target_matrix = target.matrix_world.copy()
    initial_size = tuple(properties.size)
    initial_location = tuple(controller.location)
    initial_guide = tuple(
        guide.matrix_world @ Vector(point.co) for point in spline.bezier_points)
    initial_range = (
        float(properties.curve_range_start),
        float(properties.curve_range_end),
    )
    range_axis_length = abs(float(initial_size[1]))
    check(close_tuple(initial_range, (0.0, 1.0), 1.0e-7),
          f"Curve effect range default changed: {initial_range!r}")
    properties.curve_mode = "UNLIMITED"
    unlimited_baseline = evaluated_coordinates(target)

    def check_stable_curve_domain(label):
        check(close_tuple(properties.size, initial_size, 1.0e-7),
              f"{label} changed the Curve cage size")
        check(
            (Vector(controller.location) - Vector(initial_location)).length <
            1.0e-7,
            f"{label} changed the Curve cage location")
        current_guide = tuple(
            guide.matrix_world @ Vector(point.co)
            for point in spline.bezier_points)
        check(max((left - right).length for left, right in zip(
            current_guide, initial_guide)) < 1.0e-5,
            f"{label} moved the complete Curve guide")

    deform.move_curve_effect_boundary(
        controller, "TOP", -range_axis_length * 0.5,
        initial_range=initial_range,
        axis_limits=None,
        boundary_mode="SINGLE",
    )
    check(
        close_tuple(
            (properties.curve_range_start, properties.curve_range_end),
            (0.0, 0.5), 1.0e-7),
        "Top handle did not edit only Curve Range End")
    check_stable_curve_domain("Top effect boundary")

    properties.curve_mode = "LIMITED"
    top_limited = evaluated_coordinates(target)
    top_step_vectors = tuple(
        top_limited[16 + index] - top_limited[12 + index]
        for index in range(4))
    check(
        abs((average(top_limited[16:20]) -
             average(top_limited[12:16])).length - 1.5) < 2.0e-4 and
        max((step - top_step_vectors[0]).length
            for step in top_step_vectors) < 2.0e-4,
        "Limited did not continue top outside rings rigidly along the tangent")
    properties.curve_mode = "WITHIN_BOX"
    top_within = evaluated_coordinates(target)
    check(
        max((top_within[index] - Vector(vertices[index])).length
            for index in range(12, 20)) < 1.0e-4,
        "Within Box changed geometry above the top effect range")
    properties.curve_mode = "UNLIMITED"
    top_unlimited = evaluated_coordinates(target)
    check(max((left - right).length for left, right in zip(
        top_unlimited, unlimited_baseline)) < 2.0e-4,
        "Unlimited was affected by the inward top effect range")
    check(
        max(abs(float(a) - float(b)) for row_a, row_b in zip(
            initial_target_matrix, target.matrix_world) for a, b in zip(row_a, row_b))
        < 1.0e-7,
        "Curve boundary movement changed the controlled object's transform")

    properties.curve_mode = "LIMITED"
    deform.move_curve_effect_boundary(
        controller, "TOP", 0.0,
        initial_range=initial_range,
        axis_limits=None,
        boundary_mode="SINGLE",
    )
    check(
        close_tuple(
            (properties.curve_range_start, properties.curve_range_end),
            initial_range, 1.0e-7),
        "Curve top boundary cancellation did not restore the effect range")
    check_stable_curve_domain("Top boundary cancellation")
    check(
        max((left - right).length for left, right in zip(
            initial_evaluated, evaluated_coordinates(target))) < 1.0e-4,
        "Curve top boundary cancellation did not restore the object")

    deform.move_curve_effect_boundary(
        controller, "BOTTOM", range_axis_length * 0.5,
        initial_range=initial_range,
        axis_limits=None,
        boundary_mode="SINGLE",
    )
    check(
        close_tuple(
            (properties.curve_range_start, properties.curve_range_end),
            (0.5, 1.0), 1.0e-7),
        "Bottom handle did not edit only Curve Range Start")
    check_stable_curve_domain("Bottom effect boundary")
    properties.curve_mode = "LIMITED"
    bottom_limited = evaluated_coordinates(target)
    bottom_step_vectors = tuple(
        bottom_limited[4 + index] - bottom_limited[index]
        for index in range(4))
    check(
        abs((average(bottom_limited[4:8]) -
             average(bottom_limited[:4])).length - 1.5) < 2.0e-4 and
        max((step - bottom_step_vectors[0]).length
            for step in bottom_step_vectors) < 2.0e-4,
        "Limited did not continue bottom outside rings rigidly along the tangent")
    properties.curve_mode = "WITHIN_BOX"
    bottom_within = evaluated_coordinates(target)
    check(
        max((bottom_within[index] - Vector(vertices[index])).length
            for index in range(8)) < 1.0e-4,
        "Within Box changed geometry below the bottom effect range")
    properties.curve_mode = "UNLIMITED"
    bottom_unlimited = evaluated_coordinates(target)
    check(max((left - right).length for left, right in zip(
        bottom_unlimited, unlimited_baseline)) < 2.0e-4,
        "Unlimited was affected by the inward bottom effect range")

    properties.curve_mode = "LIMITED"
    deform.move_curve_effect_boundary(
        controller, "BOTTOM", 0.0,
        initial_range=initial_range,
        axis_limits=None,
        boundary_mode="SINGLE",
    )
    check(
        close_tuple(
            (properties.curve_range_start, properties.curve_range_end),
            initial_range, 1.0e-7),
        "Curve bottom boundary cancellation did not restore the effect range")
    check_stable_curve_domain("Bottom boundary cancellation")
    check(
        max((left - right).length for left, right in zip(
            initial_evaluated, evaluated_coordinates(target))) < 1.0e-4,
        "Curve bottom boundary cancellation did not restore the object")

    # Ctrl translates both boundaries together; Alt moves them oppositely.
    translated_range = (0.2, 0.8)
    properties.curve_range_start, properties.curve_range_end = translated_range
    deform.move_curve_effect_boundary(
        controller, "TOP", range_axis_length * 0.1,
        initial_range=translated_range,
        axis_limits=None,
        boundary_mode="TRANSLATE",
    )
    check(
        close_tuple(
            (properties.curve_range_start, properties.curve_range_end),
            (0.3, 0.9), 1.0e-7),
        "Ctrl/Translate did not move both Curve effect boundaries together")
    check_stable_curve_domain("Translated effect range")
    deform.move_curve_effect_boundary(
        controller, "TOP", 0.0,
        initial_range=translated_range,
        axis_limits=None,
        boundary_mode="TRANSLATE",
    )
    check(
        close_tuple(
            (properties.curve_range_start, properties.curve_range_end),
            translated_range, 1.0e-7),
        "Ctrl/Translate cancellation did not restore both boundaries")

    symmetric_range = (0.2, 0.8)
    properties.curve_range_start, properties.curve_range_end = symmetric_range
    deform.move_curve_effect_boundary(
        controller, "TOP", -range_axis_length * 0.1,
        initial_range=symmetric_range,
        axis_limits=None,
        boundary_mode="SYMMETRIC",
    )
    check(
        close_tuple(
            (properties.curve_range_start, properties.curve_range_end),
            (0.3, 0.7), 1.0e-7),
        "Alt/Symmetric did not move Curve boundaries in opposite directions")
    check_stable_curve_domain("Symmetric effect range")
    deform.move_curve_effect_boundary(
        controller, "TOP", 0.0,
        initial_range=symmetric_range,
        axis_limits=None,
        boundary_mode="SYMMETRIC",
    )
    check(
        close_tuple(
            (properties.curve_range_start, properties.curve_range_end),
            symmetric_range, 1.0e-7),
        "Alt/Symmetric cancellation did not restore both boundaries")
    properties.curve_range_start, properties.curve_range_end = initial_range

    properties.curve_mode = "WITHIN_BOX"
    check(
        properties.curve_boundary_mode == "CAGE_ONLY",
        "Within Box did not mirror to the compatible boundary enum")
    properties.curve_boundary_mode = "EXTEND"
    check(
        properties.curve_mode == "UNLIMITED",
        "Legacy boundary changes did not update the Curve mode")

    properties.top_scale = (1.3, 0.8)
    properties.bottom_scale = (0.7, 1.2)
    properties.top_offset = (0.3, -0.2)
    properties.bottom_offset = (-0.4, 0.1)
    properties.curve_stations[0].scale = (0.85, 1.15)
    properties.curve_stations[0].offset = (0.2, -0.15)
    properties.curve_stations[-1].scale = (1.4, 0.65)
    properties.curve_stations[-1].offset = (-0.3, 0.25)

    spline = make_circle(spline)
    properties.curve_closed = True
    properties.curve_mode = "UNLIMITED"
    properties.curve_length_mode = "STRETCH"
    curve.ensure_curve_point_collection(properties, guide, reset=True)
    deform.sync_controller(controller, pull_transform=False, sync_mode="push")
    check(spline.use_cyclic_u, "Closed Curve did not set the native spline cyclic")
    check(
        close_tuple(properties.top_scale, (0.7, 1.2)) and
        close_tuple(properties.bottom_scale, (0.7, 1.2)),
        "Closing Curve did not synchronize end scale from its authored start")
    check(
        close_tuple(properties.top_offset, (-0.4, 0.1)) and
        close_tuple(properties.bottom_offset, (-0.4, 0.1)),
        "Closing Curve did not synchronize end offset from its authored start")
    check(
        close_tuple(properties.curve_stations[0].scale, (0.85, 1.15)) and
        close_tuple(properties.curve_stations[-1].scale, (0.85, 1.15)) and
        close_tuple(properties.curve_stations[0].offset, (0.2, -0.15)) and
        close_tuple(properties.curve_stations[-1].offset, (0.2, -0.15)),
        "Closing Curve did not synchronize its first and last cross sections")

    properties.top_scale = (1.1, 0.9)
    check(
        close_tuple(properties.bottom_scale, (1.1, 0.9)),
        "Closed Curve top scale did not mirror to the bottom control")
    properties.bottom_offset = (-0.15, 0.35)
    check(
        close_tuple(properties.top_offset, (-0.15, 0.35)),
        "Closed Curve bottom offset did not mirror to the top control")
    properties.curve_stations[-1].scale = (1.25, 0.75)
    check(
        close_tuple(properties.curve_stations[0].scale, (1.25, 0.75)),
        "Closed Curve terminal cross-section scale did not mirror to the start")
    properties.curve_stations[0].offset = (0.1, 0.2)
    check(
        close_tuple(properties.curve_stations[-1].offset, (0.1, 0.2)),
        "Closed Curve start cross-section offset did not mirror to the end")

    closed_size = tuple(properties.size)
    closed_location = tuple(controller.location)
    closed_guide = tuple(
        guide.matrix_world @ Vector(point.co) for point in spline.bezier_points)
    closed_range = (
        float(properties.curve_range_start),
        float(properties.curve_range_end),
    )
    closed_axis_length = abs(float(closed_size[1]))
    closed_unlimited = evaluated_coordinates(target)
    deform.move_curve_effect_boundary(
        controller, "TOP", -closed_axis_length * 0.25,
        initial_range=closed_range,
        axis_limits=None,
        boundary_mode="SINGLE",
    )
    check(
        close_tuple(
            (properties.curve_range_start, properties.curve_range_end),
            (0.25, 0.75), 1.0e-7),
        "Closed Curve top handle did not edit only its effect range")
    check(
        close_tuple(properties.size, closed_size, 1.0e-7) and
        (Vector(controller.location) - Vector(closed_location)).length < 1.0e-7 and
        max((guide.matrix_world @ Vector(point.co) - authored).length
            for point, authored in zip(spline.bezier_points, closed_guide)) <
        1.0e-5,
        "Closed Curve top effect range changed its cage or guide")
    check(max((left - right).length for left, right in zip(
        evaluated_coordinates(target), closed_unlimited)) < 2.0e-4,
        "Closed Unlimited Curve was affected by its top effect range")
    deform.move_curve_effect_boundary(
        controller, "TOP", 0.0,
        initial_range=closed_range,
        axis_limits=None,
        boundary_mode="SINGLE",
    )
    deform.move_curve_effect_boundary(
        controller, "BOTTOM", closed_axis_length * 0.2,
        initial_range=closed_range,
        axis_limits=None,
        boundary_mode="SINGLE",
    )
    check(
        close_tuple(
            (properties.curve_range_start, properties.curve_range_end),
            (0.2, 0.8), 1.0e-7),
        "Closed Curve bottom handle did not edit only its effect range")
    check(
        close_tuple(properties.size, closed_size, 1.0e-7) and
        (Vector(controller.location) - Vector(closed_location)).length < 1.0e-7,
        "Closed Curve bottom effect range changed its cage")
    check(max((left - right).length for left, right in zip(
        evaluated_coordinates(target), closed_unlimited)) < 2.0e-4,
        "Closed Unlimited Curve was affected by its bottom effect range")
    deform.move_curve_effect_boundary(
        controller, "BOTTOM", 0.0,
        initial_range=closed_range,
        axis_limits=None,
        boundary_mode="SINGLE",
    )
    check(
        bool(deform.modifier_input(modifier, "Curve Closed", False)),
        "Closed Curve did not reach the Geometry Nodes input")

    signature, _guide, _relative = curve._curve_guide_signature(properties)
    state = curve._build_preview_sample_state(properties, signature)
    first = state["samples"][0]
    last = state["samples"][-1]
    check((first[1] - last[1]).length < 1.0e-4, "Closed guide seam is open")
    check(
        first[3].dot(last[3]) > 0.999 and first[4].dot(last[4]) > 0.999,
        "Closed guide frame twists at its seam")

    local_deformer = curve.curve_preview_deformer(properties)
    cage_length = float(properties.size[1])
    source = Vector((0.25, 0.0, -0.15))
    wrapped_a = local_deformer(source, -cage_length * 0.25, properties.size)
    wrapped_b = local_deformer(source, cage_length * 0.75, properties.size)
    check(
        (wrapped_a - wrapped_b).length < 1.0e-4,
        "Unlimited closed Curve did not repeat after one authored period")

    actual = evaluated_coordinates(target)
    preview = preview_coordinates(target, controller)
    error = max((left - right).length for left, right in zip(actual, preview))
    if error >= 0.09:
        print("SDH_CLOSED_PREVIEW_DIAGNOSTIC::", sorted(
            (
                round((left - right).length, 6), index,
                tuple(round(float(value), 4) for value in left),
                tuple(round(float(value), 4) for value in right),
            )
            for index, (left, right) in enumerate(zip(actual, preview))
        )[-8:])
    check(error < 0.09, f"Closed Curve preview differs from GN: {error}")

    properties.curve_equalize_count = 8
    activate(target)
    target.modifiers.active = modifier
    check(
        bpy.ops.sdh.equalize_curve_points() == {"FINISHED"},
        "Equalize Curve Points operator failed")
    spline = curve.curve_guide_spline(guide)
    check(len(spline.bezier_points) == 8, "Equalize did not create eight points")
    check(spline.use_cyclic_u, "Equalize opened the closed Curve")
    check(
        len(properties.curve_points) == 8,
        "Object-mode point controls did not follow equalization")
    positions = tuple(Vector(point.co) for point in spline.bezier_points)
    chords = tuple(
        (positions[(index + 1) % len(positions)] - position).length
        for index, position in enumerate(positions))
    check(
        max(chords) - min(chords) < 0.08,
        f"Equalized closed points are not uniform: {chords!r}")

    point = spline.bezier_points[1]
    original_left = Vector(point.handle_left)
    properties.curve_points[1].bevel = 0.0
    properties.curve_points[1].tension = 0.35
    check(
        (Vector(point.handle_left) - original_left).length > 1.0e-3,
        "Point Bevel/Tension did not update the Bezier handles")
    check(
        point.handle_left_type == "FREE" and point.handle_right_type == "FREE",
        "Point shaping did not author explicit handles")

    for guide_point in spline.bezier_points:
        guide_point.select_control_point = False
        guide_point.select_left_handle = False
        guide_point.select_right_handle = False
    properties.curve_active_point = 0
    spline.bezier_points[3].select_control_point = True
    active_control = curve.active_curve_control(controller, guide)
    check(
        active_control == properties.curve_points[3],
        "Native Curve selection did not select the matching point controls")
    spline.bezier_points[3].select_control_point = False

    activate(target)
    target.modifiers.active = modifier
    check(
        bpy.ops.sdh.insert_cage_keyframes() == {"FINISHED"},
        "Curve keyframe insertion failed")
    controller_paths = action_paths(controller)
    expected = {
        "sdh_cage_deform.curve_mode",
        "sdh_cage_deform.curve_range_start",
        "sdh_cage_deform.curve_range_end",
        "sdh_cage_deform.curve_closed",
        "sdh_cage_deform.curve_points[1].bevel",
        "sdh_cage_deform.curve_points[1].tension",
    }
    check(
        expected <= controller_paths,
        f"Curve point animation paths are missing: {expected - controller_paths!r}")
    guide_paths = action_paths(guide.data)
    check(
        "splines[0].bezier_points[1].co" in guide_paths and
        "splines[0].bezier_points[1].handle_left" in guide_paths,
        "Guide coordinates/handles are not animated")

    print("SDH_CURVE_CAGE_EXTENDED::PASS")
finally:
    if not INSTALLED_PACKAGE:
        addon.unregister()
        bpy.context.preferences.addons.remove(entry)
