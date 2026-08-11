"""Inspect real GN chain-domain attributes and cage/geometry alignment."""

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

PATTERNS = (
    ("BOTTOM", "BOTTOM", "BOTTOM"),
    ("TOP", "TOP", "TOP"),
    ("CENTER", "CENTER", "CENTER"),
    ("SYMMETRIC", "SYMMETRIC", "SYMMETRIC"),
    ("BOTTOM", "TOP", "CENTER"),
    ("TOP", "CENTER", "SYMMETRIC"),
    ("CENTER", "SYMMETRIC", "BOTTOM"),
    ("SYMMETRIC", "BOTTOM", "TOP"),
)
GAPS = (0.0, 0.4)
CONFIGS = ("BEND", "BEND_TWIST")
COUNT = 3
SOURCE_MIN = -3.0
SOURCE_MAX = 3.0
RADIUS = 0.65
SIDES = 8
STEP = 0.025


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def partition(gap):
    segment = ((SOURCE_MAX - SOURCE_MIN) - gap * (COUNT - 1)) / COUNT
    tops = tuple(
        SOURCE_MIN + (index + 1) * segment + index * gap
        for index in range(COUNT)
    )
    bottoms = tuple(
        SOURCE_MIN + index * segment + index * gap
        for index in range(COUNT)
    )
    return segment, tops, bottoms


def y_values(gap):
    _segment, tops, bottoms = partition(gap)
    steps = int(round((SOURCE_MAX - SOURCE_MIN) / STEP))
    values = {
        round(SOURCE_MIN + (SOURCE_MAX - SOURCE_MIN) * index / steps, 10)
        for index in range(steps + 1)
    }
    for boundary in (*tops[:-1], *bottoms[1:]):
        for offset in (-0.001, 0.0, 0.001):
            values.add(round(boundary + offset, 10))
    return tuple(sorted(values))


def make_target(name, gap):
    vertices = []
    source_y = []
    center_indices = {}
    for y in y_values(gap):
        center_indices[y] = len(vertices)
        vertices.append((0.0, y, 0.0))
        source_y.append(y)
        for side in range(SIDES):
            angle = math.tau * side / SIDES
            vertices.append((RADIUS * math.cos(angle), y,
                             RADIUS * math.sin(angle)))
            source_y.append(y)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, (), ())
    target = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(target)
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    return target, mesh, tuple(vertices), tuple(source_y), center_indices


def configure(deform, controllers, pattern, config):
    bend_angles = (math.radians(48.0), math.radians(-37.0), math.radians(55.0))
    directions = (math.radians(17.0), math.radians(-29.0), math.radians(43.0))
    twists = (math.radians(31.0), math.radians(-46.0), math.radians(27.0))
    layers = ("BEND",) if config == "BEND" else ("BEND", "TWIST")
    for index, (controller, origin) in enumerate(zip(controllers, pattern)):
        properties = controller.sdh_cage_deform
        deform.core.set_deform_layers(properties, layers, bpy.context)
        properties.origin = origin
        properties.bend_strength = bend_angles[index]
        properties.bend_direction = directions[index]
        properties.twist_strength = 0.0 if config == "BEND" else twists[index]
        properties.taper_factor = 0.0
        properties.stretch_factor = 0.0
        deform.sync_controller(controller, pull_transform=False)


def evaluated_points(target):
    bpy.context.view_layer.update()
    evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        matrix = evaluated.matrix_world
        return tuple(matrix @ vertex.co for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def coordinate_values_after_prefix(
        target, stages, prefix, attribute_name, *, required=True):
    states = tuple(modifier.show_viewport for modifier in stages)
    try:
        for index, modifier in enumerate(stages):
            modifier.show_viewport = index <= prefix
        target.update_tag()
        bpy.context.view_layer.update()
        evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        try:
            attribute = mesh.attributes.get(attribute_name)
            if attribute is None:
                check(not required,
                      f"{attribute_name!r} missing after stage {prefix}")
                return None
            check(attribute.domain == "POINT",
                  f"{attribute_name!r} has domain {attribute.domain!r}")
            check(attribute.data_type == "FLOAT",
                  f"{attribute_name!r} has type {attribute.data_type!r}")
            return tuple(float(item.value) for item in attribute.data)
        finally:
            evaluated.to_mesh_clear()
    finally:
        for modifier, state in zip(stages, states):
            modifier.show_viewport = state
        target.update_tag()
        bpy.context.view_layer.update()


def points_after_prefix(target, stages, prefix):
    states = tuple(modifier.show_viewport for modifier in stages)
    try:
        for index, modifier in enumerate(stages):
            modifier.show_viewport = index <= prefix
        target.update_tag()
        return evaluated_points(target)
    finally:
        for modifier, state in zip(stages, states):
            modifier.show_viewport = state
        target.update_tag()
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
    for gap in GAPS:
        _segment, tops, bottoms = partition(gap)
        for config in CONFIGS:
            for pattern in PATTERNS:
                target = mesh = None
                controllers = ()
                name = f"SDH Domain {gap:.1f} {config} {'-'.join(pattern)}"
                try:
                    target, mesh, source_points, source_y, center_indices = (
                        make_target(name, gap))
                    result = bpy.ops.sdh.add_cage_chain(
                        count=COUNT,
                        connection_mode="CHAINED",
                        gap=gap,
                        auto_reconnect=True,
                        sync_shared_end_scale=True,
                        alignment="POS_Y",
                        origin=pattern[0],
                    )
                    check(result == {"FINISHED"}, f"could not create {name}")
                    stages = chain.chain_stages(target)
                    controllers = tuple(
                        deform.find_controller(target, stage) for stage in stages)
                    check(len(stages) == COUNT and all(controllers),
                          f"incomplete chain {name}")
                    configure(deform, controllers, pattern, config)
                    deform.core.flush_pending_chain_updates(target)
                    attribute_name = deform.modifier_input(
                        stages[0], "Chain Domain Attribute")
                    check(attribute_name, f"no domain attribute on {name}")

                    root_inverse = chain._stage_local_matrix(
                        target, controllers[0]).inverted_safe()
                    source_coordinates = tuple(
                        (root_inverse @ Vector(point)).y
                        for point in source_points)

                    prefix_reports = []
                    for prefix in range(COUNT - 1):
                        actual = coordinate_values_after_prefix(
                            target, stages, prefix, attribute_name)
                        errors = tuple(
                            abs(value - expected)
                            for value, expected in zip(
                                actual, source_coordinates))
                        prefix_reports.append({
                            "prefix": prefix,
                            "max_coordinate_error": max(errors, default=0.0),
                            "mismatches": sum(
                                error > 1.0e-5 for error in errors),
                        })

                    check(coordinate_values_after_prefix(
                        target, stages, COUNT - 1, attribute_name,
                        required=False) is None,
                        f"chain coordinate was not cleaned up at tip: {name}")

                    stage_reports = []
                    before_points = points_after_prefix(target, stages, -1)
                    for index, (stage, controller) in enumerate(
                            zip(stages, controllers)):
                        after_points = points_after_prefix(
                            target, stages, index)
                        source_start = float(deform.modifier_input(
                            stage, "Chain Source Start"))
                        source_length = abs(float(
                            controller.sdh_cage_deform.size[1]))
                        source_end = source_start + source_length
                        expected_start = (
                            root_inverse @ Vector(
                                (0.0, bottoms[index], 0.0))).y
                        expected_end = (
                            root_inverse @ Vector(
                                (0.0, tops[index], 0.0))).y
                        eligible = tuple(
                            coordinate >= source_start -
                            deform.core.CHAIN_BOUNDARY_EPSILON
                            for coordinate in source_coordinates)
                        at_or_after_end = tuple(
                            coordinate >= source_end -
                            deform.core.CHAIN_BOUNDARY_EPSILON
                            for coordinate in source_coordinates)
                        displacements = tuple(
                            (after - before).length
                            for before, after in zip(
                                before_points, after_points))
                        ineligible_displacement = max(
                            (distance for distance, is_eligible in zip(
                                displacements, eligible) if not is_eligible),
                            default=0.0,
                        )
                        stage_reports.append({
                            "index": index,
                            "source_start": source_start,
                            "source_end": source_end,
                            "start_error": abs(
                                source_start - expected_start),
                            "end_error": abs(source_end - expected_end),
                            "eligible": sum(eligible),
                            "at_or_after_end": sum(at_or_after_end),
                            "changed_eligible": sum(
                                distance > 1.0e-5 and is_eligible
                                for distance, is_eligible in zip(
                                    displacements, eligible)),
                            "max_ineligible_displacement": (
                                ineligible_displacement),
                        })
                        before_points = after_points

                    final_points = evaluated_points(target)
                    alignment = []
                    for index in range(1, COUNT):
                        bottom, _x, _y, _z = chain._stage_boundary_frame(
                            target, controllers[index], "BOTTOM")
                        bottom_world = target.matrix_world @ bottom
                        center_index = center_indices[round(bottoms[index], 10)]
                        center_world = final_points[center_index]
                        alignment.append((bottom_world - center_world).length)
                    record = {
                        "gap": gap,
                        "config": config,
                        "pattern": pattern,
                        "prefixes": tuple(prefix_reports),
                        "stages": tuple(stage_reports),
                        "max_coordinate_error": max(
                            item["max_coordinate_error"]
                            for item in prefix_reports),
                        "max_start_error": max(
                            item["start_error"] for item in stage_reports),
                        "max_end_error": max(
                            item["end_error"] for item in stage_reports),
                        "max_ineligible_displacement": max(
                            item["max_ineligible_displacement"]
                            for item in stage_reports),
                        "bottom_alignment": tuple(alignment),
                        "max_bottom_alignment": max(alignment),
                    }
                    records.append(record)
                    print(f"SDH_CHAIN_DOMAIN::CASE::{record!r}")
                    if (
                            record["max_coordinate_error"] > 1.0e-5 or
                            record["max_start_error"] > 1.0e-5 or
                            record["max_end_error"] > 1.0e-5 or
                            record["max_ineligible_displacement"] > 5.0e-5 or
                            record["max_bottom_alignment"] > 5.0e-4
                    ):
                        failures.append(record)
                finally:
                    remove_setup(target, mesh, controllers)
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)

summary = {
    "cases": len(records),
    "failures": len(failures),
    "max_coordinate_error": max(
        record["max_coordinate_error"] for record in records),
    "max_start_error": max(
        record["max_start_error"] for record in records),
    "max_end_error": max(
        record["max_end_error"] for record in records),
    "max_ineligible_displacement": max(
        record["max_ineligible_displacement"] for record in records),
    "max_bottom_alignment": max(
        record["max_bottom_alignment"] for record in records),
}
print(f"SDH_CHAIN_DOMAIN::SUMMARY::{summary!r}")
if failures:
    print(f"SDH_CHAIN_DOMAIN::FAILURES::{failures!r}")
    raise AssertionError(f"chain domain/alignment failures: {len(failures)}")
print("SDH_CHAIN_DOMAIN::PASS")
