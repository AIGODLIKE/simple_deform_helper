"""Preserve evaluated geometry when subdividing one cage into a chain.

The regression compares the same asymmetric, densely sampled mesh before and
after ``sdh.subdivide_cage_to_chain``.  A machine-readable report separates a
global shift from residual shape change so an origin-reference error cannot be
hidden by checking only cage metadata or authored range.

Run with:
    blender --background --factory-startup --python-exit-code 1 \
        --python tests/subdivide_origin_geometry_regression.py

Append ``-- --diagnostic`` to print all metrics without enforcing thresholds.
"""

from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))

ORIGINS = ("BOTTOM", "TOP", "CENTER", "SYMMETRIC")
PRIMARY_LAYER_CASES = (
    ("BEND", ("BEND",)),
    ("TWIST", ("TWIST",)),
    ("TAPER", ("TAPER",)),
    ("TWIST_BEND", ("TWIST", "BEND")),
)
DIAGNOSTIC_LAYER_CASES = (
    ("STRETCH", ("STRETCH",)),
    ("BEND_TWIST", ("BEND", "TWIST")),
    ("TAPER_BEND", ("TAPER", "BEND")),
    ("STRETCH_BEND", ("STRETCH", "BEND")),
    ("TWIST_TAPER_BEND", ("TWIST", "TAPER", "BEND")),
    ("STRETCH_TWIST_BEND", ("STRETCH", "TWIST", "BEND")),
    ("TWIST_BEND_TAPER", ("TWIST", "BEND", "TAPER")),
    ("TAPER_TWIST_BEND_STRETCH",
     ("TAPER", "TWIST", "BEND", "STRETCH")),
    ("TAPER_STRETCH", ("TAPER", "STRETCH")),
    ("STRETCH_TAPER", ("STRETCH", "TAPER")),
)
RING_COUNT = 41
SIDE_COUNT = 11
AXIS_MIN = -3.0
AXIS_MAX = 3.0
CHAIN_COUNT = 3
CHAIN_GAP = 0.0
MAX_VERTEX_ERROR = 2.0e-3
MAX_BOUNDS_CENTER_SHIFT = 2.0e-3
MAX_CENTERED_SHAPE_ERROR = 2.0e-3
MAX_EDGE_LENGTH_ERROR = 5.0e-4
DIAGNOSTIC_ONLY = "--diagnostic" in sys.argv
LAYER_CASES = (
    PRIMARY_LAYER_CASES + DIAGNOSTIC_LAYER_CASES
    if DIAGNOSTIC_ONLY else PRIMARY_LAYER_CASES
)


def mesh_data():
    """Return a non-symmetric tube with enough axial topology for Bend."""
    vertices = []
    faces = []
    for ring in range(RING_COUNT):
        t = ring / (RING_COUNT - 1)
        y = AXIS_MIN + (AXIS_MAX - AXIS_MIN) * t
        center_x = 0.11 + 0.07 * math.sin(1.15 * y)
        center_z = -0.08 + 0.05 * math.cos(0.83 * y)
        radius_x = 0.48 + 0.09 * t
        radius_z = 0.33 + 0.05 * math.sin(math.pi * t)
        for side in range(SIDE_COUNT):
            angle = math.tau * side / SIDE_COUNT
            vertices.append((
                center_x + radius_x * math.cos(angle),
                y,
                center_z + radius_z * math.sin(angle),
            ))
    for ring in range(RING_COUNT - 1):
        current = ring * SIDE_COUNT
        following = (ring + 1) * SIDE_COUNT
        for side in range(SIDE_COUNT):
            next_side = (side + 1) % SIDE_COUNT
            faces.append((
                current + side,
                current + next_side,
                following + next_side,
                following + side,
            ))
    return tuple(vertices), tuple(faces)


VERTICES, FACES = mesh_data()


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def evaluated_points(obj):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return tuple(vertex.co.copy() for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def average(points):
    result = Vector((0.0, 0.0, 0.0))
    for point in points:
        result += point
    return result / max(len(points), 1)


def bounds_center(points):
    minimum = Vector((
        min(point.x for point in points),
        min(point.y for point in points),
        min(point.z for point in points),
    ))
    maximum = Vector((
        max(point.x for point in points),
        max(point.y for point in points),
        max(point.z for point in points),
    ))
    return (minimum + maximum) * 0.5


def rms(values):
    return math.sqrt(sum(value * value for value in values) / max(len(values), 1))


def metrics(before, after):
    if len(before) != len(after):
        raise AssertionError(
            f"subdivision changed evaluated vertex count: {len(before)} -> {len(after)}")

    vertex_errors = tuple(
        (after_point - before_point).length
        for before_point, after_point in zip(before, after)
    )
    before_bounds_center = bounds_center(before)
    after_bounds_center = bounds_center(after)
    bounds_shift = after_bounds_center - before_bounds_center
    before_centroid = average(before)
    after_centroid = average(after)
    centroid_shift = after_centroid - before_centroid
    centered_errors = tuple(
        ((after_point - after_bounds_center) -
         (before_point - before_bounds_center)).length
        for before_point, after_point in zip(before, after)
    )

    edge_errors = []
    for ring in range(RING_COUNT):
        current = ring * SIDE_COUNT
        for side in range(SIDE_COUNT):
            left = current + side
            right = current + (side + 1) % SIDE_COUNT
            edge_errors.append(abs(
                (after[right] - after[left]).length -
                (before[right] - before[left]).length
            ))
    for ring in range(RING_COUNT - 1):
        current = ring * SIDE_COUNT
        following = (ring + 1) * SIDE_COUNT
        for side in range(SIDE_COUNT):
            left = current + side
            right = following + side
            edge_errors.append(abs(
                (after[right] - after[left]).length -
                (before[right] - before[left]).length
            ))

    return {
        "vertex_count": len(before),
        "max_vertex_error": max(vertex_errors, default=0.0),
        "rms_vertex_error": rms(vertex_errors),
        "bounds_center_shift": tuple(bounds_shift),
        "bounds_center_shift_length": bounds_shift.length,
        "centroid_shift": tuple(centroid_shift),
        "centroid_shift_length": centroid_shift.length,
        "max_centered_shape_error": max(centered_errors, default=0.0),
        "rms_centered_shape_error": rms(centered_errors),
        "max_edge_length_error": max(edge_errors, default=0.0),
        "rms_edge_length_error": rms(edge_errors),
    }


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
chain = deform.chain


def run_case(case_name, layers, origin):
    mesh = bpy.data.meshes.new(
        f"SDH Subdivide Origin {case_name} {origin} Mesh")
    mesh.from_pydata(VERTICES, (), FACES)
    target = bpy.data.objects.new(
        f"SDH Subdivide Origin {case_name} {origin}", mesh)
    bpy.context.collection.objects.link(target)
    activate(target)

    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, target)
    properties = controller.sdh_cage_deform
    properties.size = (2.2, AXIS_MAX - AXIS_MIN, 1.8)
    properties.mode = "LIMITED"
    properties.origin = origin
    properties.bend_direction = math.radians(23.0)
    properties.bend_strength = (
        math.radians(74.0) if "BEND" in layers else 0.0)
    properties.twist_strength = (
        math.radians(-39.0) if "TWIST" in layers else 0.0)
    properties.taper_factor = 0.42 if "TAPER" in layers else 0.0
    properties.stretch_factor = 0.36 if "STRETCH" in layers else 0.0
    properties.bottom_scale = (1.0, 1.0)
    properties.top_scale = (1.0, 1.0)
    properties.bottom_offset = (0.0, 0.0)
    properties.top_offset = (0.0, 0.0)
    controller.location = (0.0, 0.0, 0.0)
    controller.rotation_euler = (0.0, 0.0, 0.0)
    deform.core.set_deform_layers(properties, layers, bpy.context)
    if tuple(deform.core.ordered_deform_types(properties)) != layers:
        raise AssertionError(f"{case_name}/{origin}: could not create layer stack")
    deform.sync_controller(controller, pull_transform=False)
    bpy.context.view_layer.update()

    before = evaluated_points(target)
    target.modifiers.active = modifier
    activate(target)
    result = bpy.ops.sdh.subdivide_cage_to_chain(
        count=CHAIN_COUNT,
        gap=CHAIN_GAP,
        auto_reconnect=True,
        sync_shared_end_scale=True,
        allow_mixed_bend_approximation=DIAGNOSTIC_ONLY,
    )
    if result != {"FINISHED"}:
        raise AssertionError(
            f"{case_name}/{origin}: subdivision operator failed: {result!r}")
    deform.core.flush_pending_chain_updates(target)
    bpy.context.view_layer.update()
    after = evaluated_points(target)

    stages = tuple(chain.chain_stages(target))
    controllers = tuple(deform.find_controller(target, stage) for stage in stages)
    if len(stages) != CHAIN_COUNT or not all(controllers):
        raise AssertionError(f"{case_name}/{origin}: incomplete subdivided chain")

    report = metrics(before, after)
    report.update({
        "case": case_name,
        "origin": origin,
        "deform_types": tuple(
            deform.core.ordered_deform_types(properties)),
        "stage_origins": tuple(
            item.sdh_cage_deform.origin for item in controllers),
        "stage_centers": tuple(tuple(item.location) for item in controllers),
        "stage_sizes": tuple(
            tuple(item.sdh_cage_deform.size) for item in controllers),
        "stage_bend_angles": tuple(
            float(item.sdh_cage_deform.bend_strength)
            for item in controllers),
        "stage_twist_angles": tuple(
            float(item.sdh_cage_deform.twist_strength)
            for item in controllers),
    })
    print(f"SDH_SUBDIVIDE_ORIGIN::CASE::{report!r}")

    return report


def geometry_failures(report):
    failures = []
    for key, limit in (
            ("max_vertex_error", MAX_VERTEX_ERROR),
            ("bounds_center_shift_length", MAX_BOUNDS_CENTER_SHIFT),
            ("max_centered_shape_error", MAX_CENTERED_SHAPE_ERROR),
            ("max_edge_length_error", MAX_EDGE_LENGTH_ERROR)):
        if report[key] > limit:
            failures.append(f"{key}={report[key]:.9g} > {limit:.9g}")
    return tuple(failures)


try:
    reports = tuple(
        run_case(case_name, layers, origin)
        for case_name, layers in LAYER_CASES
        for origin in ORIGINS
    )
    maxima = tuple(
        (
            case_name,
            max(
                report["max_vertex_error"]
                for report in reports
                if report["case"] == case_name),
        )
        for case_name, _layers in LAYER_CASES
    )
    print(f"SDH_SUBDIVIDE_ORIGIN::MAXIMA::{maxima!r}")
    print(f"SDH_SUBDIVIDE_ORIGIN::REPORT::{reports!r}")
    if DIAGNOSTIC_ONLY:
        print("SDH_SUBDIVIDE_ORIGIN::DIAGNOSTIC")
    else:
        failed = tuple(
            (report["case"], report["origin"], geometry_failures(report))
            for report in reports
            if geometry_failures(report)
        )
        if failed:
            print(f"SDH_SUBDIVIDE_ORIGIN::FAIL::{failed!r}")
            raise AssertionError(
                "subdivision changed evaluated geometry in "
                f"{len(failed)} of {len(reports)} cases")
        print("SDH_SUBDIVIDE_ORIGIN::PASS")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
