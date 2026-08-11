"""Numerical continuity probe for physical bottoms in chained cages.

Run with:
    blender --background --factory-startup --python-exit-code 1 \
        --python tests/chain_physical_seam_probe.py

This intentionally does not compare Geometry Nodes with the add-on's Python
deformation evaluator.  Every metric is reconstructed from densely sampled
source rings after Blender has evaluated the complete modifier stack.
"""

from __future__ import annotations

import importlib
import itertools
import math
import sys
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))

ORIGINS = ("BOTTOM", "TOP", "CENTER", "SYMMETRIC")
GAPS = (0.0, 0.1, 0.4)
CHAIN_COUNTS = (2, 3)
DEFORM_CONFIGS = ("BEND", "BEND_TWIST")

SOURCE_MIN = -3.0
SOURCE_MAX = 3.0
SOURCE_RADIUS = 0.65
RING_SIDES = 12
DENSE_STEP = 0.025
LIMIT_STEP = 0.005

# These limits are deliberately wider than Blender's float noise while still
# catching a viewport-visible seam discontinuity.
C0_TOLERANCE = 5.0e-4
TANGENT_ANGLE_TOLERANCE_DEG = 0.5
TANGENT_SPEED_TOLERANCE = 0.02
RADIUS_GROWTH_ABS_TOLERANCE = 5.0e-4
RADIUS_GROWTH_REL_TOLERANCE = 0.002


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def rounded_y(value):
    return round(float(value), 10)


def source_boundaries(count, gap):
    usable = (SOURCE_MAX - SOURCE_MIN) - gap * (count - 1)
    segment = usable / count
    return tuple(
        SOURCE_MIN + index * segment + index * gap
        for index in range(1, count)
    )


def sample_y_values(boundaries):
    span = SOURCE_MAX - SOURCE_MIN
    steps = int(round(span / DENSE_STEP))
    values = {
        rounded_y(SOURCE_MIN + span * index / steps)
        for index in range(steps + 1)
    }
    for boundary in boundaries:
        for offset in range(-3, 4):
            values.add(rounded_y(boundary + offset * LIMIT_STEP))
    return tuple(sorted(values))


def make_probe_target(name, boundaries):
    vertices = []
    ring_starts = {}
    for y in sample_y_values(boundaries):
        ring_starts[y] = len(vertices)
        vertices.append((0.0, y, 0.0))
        for side in range(RING_SIDES):
            angle = math.tau * side / RING_SIDES
            vertices.append((
                SOURCE_RADIUS * math.cos(angle),
                y,
                SOURCE_RADIUS * math.sin(angle),
            ))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, (), ())
    target = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(target)
    activate(target)
    return target, mesh, ring_starts


def evaluated_world_points(target):
    bpy.context.view_layer.update()
    evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        matrix = evaluated.matrix_world
        return tuple(matrix @ vertex.co for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def extrapolated_limit(first, second, third):
    return first * 3.0 - second * 3.0 + third


def left_derivative(first, second, third):
    return (first * 2.5 - second * 4.0 + third * 1.5) / LIMIT_STEP


def right_derivative(first, second, third):
    return (first * -2.5 + second * 4.0 - third * 1.5) / LIMIT_STEP


def angle_degrees(left, right):
    if left.length <= 1.0e-10 or right.length <= 1.0e-10:
        return math.inf
    cosine = max(min(left.normalized().dot(right.normalized()), 1.0), -1.0)
    return math.degrees(math.acos(cosine))


def ring(points, ring_starts, y):
    start = ring_starts[rounded_y(y)]
    return points[start:start + RING_SIDES + 1]


def mean_radius(sample):
    center = sample[0]
    return sum((point - center).length for point in sample[1:]) / RING_SIDES


def seam_metrics(points, ring_starts, boundary):
    left_rings = tuple(
        ring(points, ring_starts, boundary - LIMIT_STEP * offset)
        for offset in (1, 2, 3)
    )
    right_rings = tuple(
        ring(points, ring_starts, boundary + LIMIT_STEP * offset)
        for offset in (1, 2, 3)
    )
    exact_ring = ring(points, ring_starts, boundary)

    c0_limit_jump = 0.0
    c0_exact_residual = 0.0
    tangent_angle = 0.0
    tangent_speed_change = 0.0
    worst_slot = 0
    for slot in range(RING_SIDES + 1):
        left_limit = extrapolated_limit(
            left_rings[0][slot], left_rings[1][slot], left_rings[2][slot])
        right_limit = extrapolated_limit(
            right_rings[0][slot], right_rings[1][slot], right_rings[2][slot])
        jump = (right_limit - left_limit).length
        exact_residual = max(
            (exact_ring[slot] - left_limit).length,
            (exact_ring[slot] - right_limit).length,
        )
        left_tangent = left_derivative(
            left_rings[0][slot], left_rings[1][slot], left_rings[2][slot])
        right_tangent = right_derivative(
            right_rings[0][slot], right_rings[1][slot], right_rings[2][slot])
        angle = angle_degrees(left_tangent, right_tangent)
        speed = abs(left_tangent.length - right_tangent.length) / max(
            left_tangent.length, right_tangent.length, 1.0e-10)
        if max(jump, exact_residual) > max(c0_limit_jump, c0_exact_residual):
            worst_slot = slot
        c0_limit_jump = max(c0_limit_jump, jump)
        c0_exact_residual = max(c0_exact_residual, exact_residual)
        tangent_angle = max(tangent_angle, angle)
        tangent_speed_change = max(tangent_speed_change, speed)

    left_radii = tuple(mean_radius(sample) for sample in left_rings)
    right_radii = tuple(mean_radius(sample) for sample in right_rings)
    left_radius = extrapolated_limit(*left_radii)
    right_radius = extrapolated_limit(*right_radii)
    exact_radius = mean_radius(exact_ring)
    radius_growth = max(
        right_radius - left_radius,
        exact_radius - max(left_radius, right_radius),
        0.0,
    )
    radius_growth_relative = radius_growth / max(
        left_radius, SOURCE_RADIUS, 1.0e-10)

    return {
        "source_y": boundary,
        "world_seam": tuple(float(value) for value in exact_ring[0]),
        "c0_limit_jump": c0_limit_jump,
        "c0_exact_residual": c0_exact_residual,
        "tangent_angle_deg": tangent_angle,
        "tangent_speed_change": tangent_speed_change,
        "radius_left": left_radius,
        "radius_right": right_radius,
        "radius_exact": exact_radius,
        "radius_growth": radius_growth,
        "radius_growth_relative": radius_growth_relative,
        "worst_slot": worst_slot,
    }


def failure_reasons(metrics):
    """Return visual seam failures, not intentional derivative changes.

    Adjacent cages own independent deformation parameters, so their tangent
    angle and speed are allowed to differ.  Keep those C1 measurements in the
    report, but gate the regression on C0 position and section-radius jumps.
    """
    reasons = []
    if max(metrics["c0_limit_jump"], metrics["c0_exact_residual"]) > C0_TOLERANCE:
        reasons.append("C0")
    allowed_growth = max(
        RADIUS_GROWTH_ABS_TOLERANCE,
        metrics["radius_left"] * RADIUS_GROWTH_REL_TOLERANCE,
    )
    if metrics["radius_growth"] > allowed_growth:
        reasons.append("RADIUS_GROWTH")
    return tuple(reasons)


def configure_chain(deform, controllers, config):
    bend_angles = (math.radians(48.0), math.radians(-37.0), math.radians(55.0))
    bend_directions = (math.radians(17.0), math.radians(-29.0), math.radians(43.0))
    twist_angles = (math.radians(31.0), math.radians(-46.0), math.radians(27.0))
    layers = ("BEND",) if config == "BEND" else ("BEND", "TWIST")
    for index, controller in enumerate(controllers):
        properties = controller.sdh_cage_deform
        deform.core.set_deform_layers(properties, layers, bpy.context)
        check(deform.core.ordered_deform_types(properties) == layers,
              f"could not set {config} layers on stage {index}")
        properties.bend_strength = bend_angles[index]
        properties.bend_direction = bend_directions[index]
        properties.twist_strength = (
            0.0 if config == "BEND" else twist_angles[index])
        properties.taper_factor = 0.0
        properties.stretch_factor = 0.0
        properties.top_scale = (1.0, 1.0)
        properties.bottom_scale = (1.0, 1.0)
        properties.top_offset = (0.0, 0.0)
        properties.bottom_offset = (0.0, 0.0)
        deform.sync_controller(controller, pull_transform=False)


def set_origins(deform, target, controllers, pattern):
    for controller, origin in zip(controllers, pattern):
        controller.sdh_cage_deform.origin = origin
        deform.sync_controller(controller, pull_transform=False)
    deform.core.flush_pending_chain_updates(target)
    bpy.context.view_layer.update()


def remove_setup(target, mesh, controllers):
    for controller in controllers:
        if controller is not None and controller.name in bpy.data.objects:
            bpy.data.objects.remove(controller, do_unlink=True)
    if target is not None and target.name in bpy.data.objects:
        bpy.data.objects.remove(target, do_unlink=True)
    if mesh is not None and mesh.name in bpy.data.meshes:
        bpy.data.meshes.remove(mesh)


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
chain = deform.chain

records = []
failures = []
try:
    for count in CHAIN_COUNTS:
        for gap in GAPS:
            boundaries = source_boundaries(count, gap)
            for config in DEFORM_CONFIGS:
                target = mesh = None
                controllers = ()
                name = f"SDH Physical Seam {count} {gap:.1f} {config}"
                try:
                    target, mesh, ring_starts = make_probe_target(name, boundaries)
                    result = bpy.ops.sdh.add_cage_chain(
                        count=count,
                        connection_mode="CHAINED",
                        gap=gap,
                        auto_reconnect=True,
                        sync_shared_end_scale=True,
                        alignment="POS_Y",
                        origin="BOTTOM",
                    )
                    check(result == {"FINISHED"}, f"chain creation failed: {name}")
                    stages = chain.chain_stages(target)
                    controllers = tuple(
                        deform.find_controller(target, stage) for stage in stages)
                    check(len(controllers) == count and all(controllers),
                          f"incomplete chain: {name}")
                    configure_chain(deform, controllers, config)
                    deform.core.flush_pending_chain_updates(target)

                    for pattern in itertools.product(ORIGINS, repeat=count):
                        set_origins(deform, target, controllers, pattern)
                        points = evaluated_world_points(target)
                        check(len(points) == len(ring_starts) * (RING_SIDES + 1),
                              f"topology changed: {name}, {pattern!r}")
                        for seam_index, boundary in enumerate(boundaries, start=1):
                            metrics = seam_metrics(points, ring_starts, boundary)
                            record = {
                                "path": "BOTTOM_THEN_SWITCH",
                                "count": count,
                                "gap": gap,
                                "config": config,
                                "pattern": pattern,
                                "seam": seam_index,
                                **metrics,
                            }
                            records.append(record)
                            reasons = failure_reasons(metrics)
                            if reasons:
                                failures.append((reasons, record))
                finally:
                    remove_setup(target, mesh, controllers)

    # Direct creation is a separate path: chain frames are authored while the
    # requested Origin is already active.  Reusing the Bottom-created chain
    # above would miss bugs in add_cage_chain's initial root/downstream setup.
    for count in CHAIN_COUNTS:
        for gap in GAPS:
            boundaries = source_boundaries(count, gap)
            for config in DEFORM_CONFIGS:
                for origin in ORIGINS:
                    target = mesh = None
                    controllers = ()
                    name = (
                        f"SDH Direct Physical Seam {count} {gap:.1f} "
                        f"{config} {origin}")
                    try:
                        target, mesh, ring_starts = make_probe_target(
                            name, boundaries)
                        result = bpy.ops.sdh.add_cage_chain(
                            count=count,
                            connection_mode="CHAINED",
                            gap=gap,
                            auto_reconnect=True,
                            sync_shared_end_scale=True,
                            alignment="POS_Y",
                            origin=origin,
                        )
                        check(result == {"FINISHED"},
                              f"direct chain creation failed: {name}")
                        stages = chain.chain_stages(target)
                        controllers = tuple(
                            deform.find_controller(target, stage)
                            for stage in stages)
                        check(len(controllers) == count and all(controllers),
                              f"incomplete direct chain: {name}")
                        configure_chain(deform, controllers, config)
                        deform.core.flush_pending_chain_updates(target)
                        bpy.context.view_layer.update()
                        pattern = (origin,) * count
                        check(all(
                            controller.sdh_cage_deform.origin == origin
                            for controller in controllers),
                            f"direct origin was rewritten: {name}")
                        points = evaluated_world_points(target)
                        check(
                            len(points) == len(ring_starts) * (RING_SIDES + 1),
                            f"direct topology changed: {name}")
                        for seam_index, boundary in enumerate(
                                boundaries, start=1):
                            metrics = seam_metrics(
                                points, ring_starts, boundary)
                            record = {
                                "path": "DIRECT_CREATE",
                                "count": count,
                                "gap": gap,
                                "config": config,
                                "pattern": pattern,
                                "seam": seam_index,
                                **metrics,
                            }
                            records.append(record)
                            reasons = failure_reasons(metrics)
                            if reasons:
                                failures.append((reasons, record))
                    finally:
                        remove_setup(target, mesh, controllers)
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)


def metric_record(key):
    return max(records, key=lambda record: record[key])


worst_c0 = max(
    records,
    key=lambda record: max(
        record["c0_limit_jump"], record["c0_exact_residual"]),
)
worst_angle = metric_record("tangent_angle_deg")
worst_speed = metric_record("tangent_speed_change")
worst_radius = metric_record("radius_growth_relative")

summary = {
    "cases": (
        sum(len(tuple(itertools.product(ORIGINS, repeat=count)))
            for count in CHAIN_COUNTS) * len(GAPS) * len(DEFORM_CONFIGS) +
        len(CHAIN_COUNTS) * len(GAPS) * len(DEFORM_CONFIGS) * len(ORIGINS)
    ),
    "seams": len(records),
    "failures": len(failures),
    "c1_diagnostics": sum(
        record["tangent_angle_deg"] > TANGENT_ANGLE_TOLERANCE_DEG or
        record["tangent_speed_change"] > TANGENT_SPEED_TOLERANCE
        for record in records
    ),
    "thresholds": {
        "c0": C0_TOLERANCE,
        "tangent_angle_deg": TANGENT_ANGLE_TOLERANCE_DEG,
        "tangent_speed_relative": TANGENT_SPEED_TOLERANCE,
        "radius_growth_absolute": RADIUS_GROWTH_ABS_TOLERANCE,
        "radius_growth_relative": RADIUS_GROWTH_REL_TOLERANCE,
    },
}
print(f"SDH_PHYSICAL_SEAM::SUMMARY::{summary!r}")
print(f"SDH_PHYSICAL_SEAM::WORST_C0::{worst_c0!r}")
print(f"SDH_PHYSICAL_SEAM::WORST_TANGENT_ANGLE::{worst_angle!r}")
print(f"SDH_PHYSICAL_SEAM::WORST_TANGENT_SPEED::{worst_speed!r}")
print(f"SDH_PHYSICAL_SEAM::WORST_RADIUS::{worst_radius!r}")

if failures:
    matrix = {}
    for reasons, record in failures:
        key = (
            record["path"], record["count"], record["gap"],
            record["config"],
        )
        matrix.setdefault(key, {"count": 0, "reasons": set(), "worst": None})
        item = matrix[key]
        item["count"] += 1
        item["reasons"].update(reasons)
        score = max(
            record["c0_limit_jump"] / C0_TOLERANCE,
            record["c0_exact_residual"] / C0_TOLERANCE,
            record["tangent_angle_deg"] / TANGENT_ANGLE_TOLERANCE_DEG,
            record["tangent_speed_change"] / TANGENT_SPEED_TOLERANCE,
            record["radius_growth_relative"] / RADIUS_GROWTH_REL_TOLERANCE,
        )
        if item["worst"] is None or score > item["worst"][0]:
            item["worst"] = (score, record)
    for key in sorted(matrix):
        item = matrix[key]
        report = {
            "count": item["count"],
            "reasons": tuple(sorted(item["reasons"])),
            "worst": item["worst"][1],
        }
        print(f"SDH_PHYSICAL_SEAM::FAIL_MATRIX::{key!r}::{report!r}")
    raise AssertionError(
        f"physical chain seam probe found {len(failures)} failing seam samples")

print("SDH_PHYSICAL_SEAM::PASS")
