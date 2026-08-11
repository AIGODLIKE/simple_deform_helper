"""Numerically test full-affine bottom normalization for chained stages.

This is a read-only production-code experiment.  A downstream stage uses

    H = B_in @ inverse(B_current) @ F @ inverse(B_in)

where ``B_in`` is the actual incoming boundary frame expressed in the
current controller's local space and ``B_current`` is that stage's authored
F(bottom) frame.  Both frames retain shear and scale.
"""

from __future__ import annotations

import importlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
OUTPUT = (
    Path(sys.argv[sys.argv.index("--") + 1]).resolve()
    if "--" in sys.argv and len(sys.argv) > sys.argv.index("--") + 1
    else SOURCE / "outputs" / "chain_affine_conjugation_probe.json"
)
sys.path.insert(0, str(SOURCE.parent))

SOURCE_MIN = -3.0
SOURCE_MAX = 3.0
RADIUS = 0.65
SIDES = 16
LIMIT_STEP = 0.002
FRAME_STEP = 0.001

CASES = (
    (2, 0.0, ("TOP", "TOP")),
    (2, 0.4, ("TOP", "TOP")),
    (2, 0.0, ("CENTER", "TOP")),
    (2, 0.4, ("CENTER", "TOP")),
    (2, 0.0, ("SYMMETRIC", "CENTER")),
    (2, 0.4, ("SYMMETRIC", "CENTER")),
    (3, 0.0, ("TOP", "TOP", "TOP")),
    (3, 0.4, ("TOP", "TOP", "TOP")),
    (3, 0.0, ("BOTTOM", "TOP", "CENTER")),
    (3, 0.4, ("BOTTOM", "TOP", "CENTER")),
    (3, 0.0, ("CENTER", "SYMMETRIC", "TOP")),
    (3, 0.4, ("CENTER", "SYMMETRIC", "TOP")),
)


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def boundaries_for(count, gap):
    segment = ((SOURCE_MAX - SOURCE_MIN) - gap * (count - 1)) / count
    bottoms = tuple(
        SOURCE_MIN + index * (segment + gap) for index in range(count))
    tops = tuple(value + segment for value in bottoms)
    return segment, bottoms, tops


def sample_ys(bottoms):
    values = {SOURCE_MIN, SOURCE_MAX}
    for boundary in bottoms[1:]:
        values.add(boundary)
        for offset in (-3, -2, -1, 1, 2, 3):
            values.add(boundary + offset * LIMIT_STEP)
    return tuple(sorted(round(value, 10) for value in values))


def make_target(name, bottoms):
    vertices = []
    starts = {}
    for y in sample_ys(bottoms):
        starts[round(y, 10)] = len(vertices)
        vertices.append((0.0, y, 0.0))
        for side in range(SIDES):
            angle = math.tau * side / SIDES
            vertices.append((
                RADIUS * math.cos(angle), y,
                RADIUS * math.sin(angle),
            ))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, (), ())
    target = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(target)
    activate(target)
    return target, mesh, starts, tuple(Vector(value) for value in vertices)


def evaluated_points(target):
    bpy.context.view_layer.update()
    evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        matrix = evaluated.matrix_world
        return tuple(matrix @ vertex.co for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def affine_frame(authored_origin, evaluated_origin, x_axis, y_axis, z_axis):
    linear = Matrix((
        (x_axis.x, y_axis.x, z_axis.x),
        (x_axis.y, y_axis.y, z_axis.y),
        (x_axis.z, y_axis.z, z_axis.z),
    ))
    translation = Vector(evaluated_origin) - linear @ Vector(authored_origin)
    matrix = linear.to_4x4()
    matrix.translation = translation
    return matrix


def sampled_frame(function, bottom_y):
    authored = Vector((0.0, bottom_y, 0.0))
    center = Vector(function(authored))
    x_axis = (
        Vector(function(authored + Vector((1.0, 0.0, 0.0)))) -
        Vector(function(authored - Vector((1.0, 0.0, 0.0))))
    ) * 0.5
    z_axis = (
        Vector(function(authored + Vector((0.0, 0.0, 1.0)))) -
        Vector(function(authored - Vector((0.0, 0.0, 1.0))))
    ) * 0.5
    y_axis = (
        Vector(function(authored + Vector((0.0, FRAME_STEP, 0.0)))) -
        center
    ) / FRAME_STEP
    return affine_frame(authored, center, x_axis, y_axis, z_axis)


def point(matrix, value):
    return matrix @ Vector(value)


def matrix_values(matrix):
    return tuple(
        tuple(round(float(value), 10) for value in row)
        for row in matrix
    )


def frame_values(matrix, bottom_y):
    linear = matrix.to_3x3()
    origin = matrix @ Vector((0.0, bottom_y, 0.0))
    columns = tuple(Vector((linear[0][index], linear[1][index],
                            linear[2][index])) for index in range(3))
    return {
        "origin": tuple(float(value) for value in origin),
        "x": tuple(float(value) for value in columns[0]),
        "y": tuple(float(value) for value in columns[1]),
        "z": tuple(float(value) for value in columns[2]),
        "determinant": float(linear.determinant()),
    }


def configure(deform, controllers, origins):
    bends = (math.radians(48.0), math.radians(-37.0), math.radians(55.0))
    directions = (math.radians(17.0), math.radians(-29.0), math.radians(43.0))
    twists = (math.radians(31.0), math.radians(-46.0), math.radians(27.0))
    for index, (controller, origin) in enumerate(zip(controllers, origins)):
        properties = controller.sdh_cage_deform
        deform.core.set_deform_layers(
            properties, ("BEND", "TWIST"), bpy.context)
        properties.origin = origin
        properties.bend_strength = bends[index]
        properties.bend_direction = directions[index]
        properties.twist_strength = twists[index]
        properties.taper_factor = 0.0
        properties.stretch_factor = 0.0
        properties.top_scale = (1.0, 1.0)
        properties.bottom_scale = (1.0, 1.0)
        properties.top_offset = (0.0, 0.0)
        properties.bottom_offset = (0.0, 0.0)
        deform.sync_controller(controller, pull_transform=False)


def extrapolated(first, second, third):
    return first * 3.0 - second * 3.0 + third


def mean_radius(ring):
    center = ring[0]
    return sum((value - center).length for value in ring[1:]) / SIDES


def seam_metrics(points_by_y, boundary):
    left = tuple(
        points_by_y[round(boundary - offset * LIMIT_STEP, 10)]
        for offset in (1, 2, 3)
    )
    right = tuple(
        points_by_y[round(boundary + offset * LIMIT_STEP, 10)]
        for offset in (1, 2, 3)
    )
    exact = points_by_y[round(boundary, 10)]
    c0 = 0.0
    exact_error = 0.0
    for slot in range(SIDES + 1):
        left_limit = extrapolated(
            left[0][slot], left[1][slot], left[2][slot])
        right_limit = extrapolated(
            right[0][slot], right[1][slot], right[2][slot])
        c0 = max(c0, (right_limit - left_limit).length)
        exact_error = max(
            exact_error, (exact[slot] - left_limit).length,
            (exact[slot] - right_limit).length)
    left_radius = extrapolated(*(mean_radius(value) for value in left))
    right_radius = extrapolated(*(mean_radius(value) for value in right))
    exact_radius = mean_radius(exact)
    return {
        "c0_limits": c0,
        "c0_exact": exact_error,
        "radius_left": left_radius,
        "radius_right": right_radius,
        "radius_exact": exact_radius,
        "radius_jump": max(
            abs(right_radius - left_radius),
            abs(exact_radius - left_radius),
            abs(exact_radius - right_radius),
        ),
    }


def grouped(points, starts):
    return {
        y: points[start:start + SIDES + 1]
        for y, start in starts.items()
    }


def run_case(deform, count, gap, origins):
    segment, bottoms, _tops = boundaries_for(count, gap)
    label = f"SDH Affine {count} {gap:.1f} {'-'.join(origins)}"
    target, mesh, starts, source = make_target(label, bottoms)
    controllers = ()
    try:
        result = bpy.ops.sdh.add_cage_chain(
            count=count, connection_mode="CHAINED", gap=gap,
            auto_reconnect=True, sync_shared_end_scale=True,
            alignment="POS_Y", origin=origins[0])
        check(result == {"FINISHED"}, f"chain creation failed: {label}")
        stages = deform.chain.chain_stages(target)
        controllers = tuple(
            deform.find_controller(target, stage) for stage in stages)
        check(len(controllers) == count and all(controllers),
              f"incomplete chain: {label}")
        configure(deform, controllers, origins)
        deform.core.flush_pending_chain_updates(target)
        # One explicit reconnect makes this experiment independent of timer
        # delivery while preserving the exact production placement algorithm.
        deform.chain.reconnect_chain(target, deform.chain.stage_chain_uuid(stages[0]))
        deform.core.flush_pending_chain_updates(target)

        matrices = tuple(
            deform.chain._stage_local_matrix(target, controller)
            for controller in controllers)
        inverses = tuple(matrix.inverted_safe() for matrix in matrices)
        frames = [None] * count

        def raw_stage_f(index, value):
            return deform.deform_point_from_properties(
                value, controllers[index].sdh_cage_deform,
                evaluator=True, apply_chain_input_offset=False)

        def proposed(source_point, through=None):
            source_point = Vector(source_point)
            source_y = float(source_point.y)
            result_point = source_point.copy()
            stop = count if through is None else int(through)
            for index in range(stop):
                if index > 0 and source_y < bottoms[index] - 1.0e-10:
                    continue
                local = inverses[index] @ result_point
                if index == 0:
                    output = Vector(raw_stage_f(index, local))
                else:
                    pre, post, _incoming, _current = frames[index]
                    authored = pre @ local
                    deformed = Vector(raw_stage_f(index, authored))
                    output = post @ deformed
                result_point = matrices[index] @ output
            return result_point

        frame_reports = []
        for index in range(1, count):
            half_y = float(controllers[index].sdh_cage_deform.size[1]) * 0.5
            bottom_y = -half_y

            def incoming(local_authored, stage_index=index, half=half_y):
                local_authored = Vector(local_authored)
                source_point = Vector((
                    local_authored.x,
                    bottoms[stage_index] + local_authored.y + half,
                    local_authored.z,
                ))
                target_local = proposed(source_point, through=stage_index)
                return inverses[stage_index] @ target_local

            incoming_frame = sampled_frame(incoming, bottom_y)
            current_frame = sampled_frame(
                lambda value, stage_index=index: raw_stage_f(
                    stage_index, value),
                bottom_y,
            )
            pre = incoming_frame.inverted_safe()
            post = incoming_frame @ current_frame.inverted_safe()
            frames[index] = (pre, post, incoming_frame, current_frame)

            identity_error = 0.0
            for side in range(SIDES):
                angle = math.tau * side / SIDES
                authored = Vector((
                    RADIUS * math.cos(angle), bottom_y,
                    RADIUS * math.sin(angle),
                ))
                incoming_point = incoming_frame @ authored
                normalized = post @ Vector(raw_stage_f(
                    index, pre @ incoming_point))
                identity_error = max(
                    identity_error, (normalized - incoming_point).length)
            frame_reports.append({
                "stage": index + 1,
                "incoming": frame_values(incoming_frame, bottom_y),
                "current_bottom": frame_values(current_frame, bottom_y),
                "pre_inverse_incoming": matrix_values(pre),
                "post_incoming_inverse_current": matrix_values(post),
                "bottom_identity_error": identity_error,
            })

        proposed_points = tuple(proposed(value) for value in source)
        baseline_points = evaluated_points(target)
        check(len(baseline_points) == len(source),
              f"topology changed: {label}")
        proposed_grouped = grouped(proposed_points, starts)
        baseline_grouped = grouped(baseline_points, starts)
        proposed_seams = tuple(
            seam_metrics(proposed_grouped, boundary)
            for boundary in bottoms[1:])
        baseline_seams = tuple(
            seam_metrics(baseline_grouped, boundary)
            for boundary in bottoms[1:])
        report = {
            "count": count,
            "gap": gap,
            "origins": origins,
            "segment_length": segment,
            "baseline": baseline_seams,
            "conjugated": proposed_seams,
            "frames": frame_reports,
            "max_baseline_c0": max(max(
                item["c0_limits"], item["c0_exact"])
                for item in baseline_seams),
            "max_conjugated_c0": max(max(
                item["c0_limits"], item["c0_exact"])
                for item in proposed_seams),
            "max_baseline_radius_jump": max(
                item["radius_jump"] for item in baseline_seams),
            "max_conjugated_radius_jump": max(
                item["radius_jump"] for item in proposed_seams),
            "max_bottom_identity_error": max(
                item["bottom_identity_error"] for item in frame_reports),
        }
        print(
            "SDH_AFFINE_CONJUGATION::CASE::"
            f"{count}::{gap:.1f}::{origins!r}::"
            f"BASE_C0={report['max_baseline_c0']:.9f}::"
            f"NEW_C0={report['max_conjugated_c0']:.9f}::"
            f"BASE_RADIUS={report['max_baseline_radius_jump']:.9f}::"
            f"NEW_RADIUS={report['max_conjugated_radius_jump']:.9f}::"
            f"IDENTITY={report['max_bottom_identity_error']:.9f}"
        )
        return report
    finally:
        for controller in controllers:
            if controller is not None and controller.name in bpy.data.objects:
                bpy.data.objects.remove(controller, do_unlink=True)
        if target.name in bpy.data.objects:
            bpy.data.objects.remove(target, do_unlink=True)
        if mesh.name in bpy.data.meshes:
            bpy.data.meshes.remove(mesh)


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
try:
    reports = tuple(run_case(deform, *case) for case in CASES)
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)

payload = {
    "formula": "H = B_in * inverse(B_current) * F * inverse(B_in)",
    "frame_convention": (
        "4x4 authored-absolute to evaluated-affine; columns are full "
        "dF/dx, dF/dy, dF/dz without orthogonalization"
    ),
    "cases": reports,
}
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
print(f"SDH_AFFINE_CONJUGATION::OUTPUT::{OUTPUT}")
