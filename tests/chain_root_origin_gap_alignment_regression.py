"""Verify non-Bottom chain roots against full evaluated cross-sections.

The reported failure used non-Bottom root Origins together with mixed
downstream Origins and chain gaps.  Center samples alone can hide a rotated or
twisted cage mismatch, so every scenario compares all four section corners at
five positions in every cage.  A matching Bottom-root baseline also proves
that the requested root Origin was not silently normalized away.
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

COUNT = 3
GAP = 0.4
SOURCE_MIN = -3.0
SOURCE_MAX = 3.0
HALF_WIDTH = 0.65
RING_POSITIONS = (0.0, 0.25, 0.5, 0.75, 1.0)
CORNER_SIGNS = ((-1, -1), (-1, 1), (1, 1), (1, -1))
MAX_ALIGNMENT_ERROR = 5.0e-4
MIN_BASELINE_DELTA = 1.0e-3
BEND_ANGLES = (38.0, -28.0, 42.0)
BEND_DIRECTIONS = (0.0, 15.0, -20.0)
TWIST_ANGLES = (15.0, -22.0, 18.0)
CASES = (
    ("ROOT_TOP", ("TOP", "CENTER", "SYMMETRIC")),
    ("ROOT_CENTER", ("CENTER", "CENTER", "SYMMETRIC")),
    ("ROOT_SYMMETRIC", ("SYMMETRIC", "CENTER", "SYMMETRIC")),
)


segment = ((SOURCE_MAX - SOURCE_MIN) - GAP * (COUNT - 1)) / COUNT
bottoms = tuple(
    SOURCE_MIN + index * segment + index * GAP for index in range(COUNT))

vertices = []
sample_indices = {}
for stage_index, bottom in enumerate(bottoms):
    for ring_t in RING_POSITIONS:
        y = bottom + segment * ring_t
        for x_sign, z_sign in CORNER_SIGNS:
            sample_indices[(stage_index, ring_t, x_sign, z_sign)] = len(vertices)
            vertices.append((x_sign * HALF_WIDTH, y, z_sign * HALF_WIDTH))

entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
gizmos = importlib.import_module(f"{PACKAGE}.cage_deform.gizmos")
chain = deform.chain


def run_case(label, origins):
    mesh = bpy.data.meshes.new(f"SDH {label} Mesh")
    mesh.from_pydata(vertices, (), ())
    target = bpy.data.objects.new(f"SDH {label}", mesh)
    bpy.context.collection.objects.link(target)
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target

    result = bpy.ops.sdh.add_cage_chain(
        count=COUNT,
        connection_mode="CHAINED",
        gap=GAP,
        auto_reconnect=True,
        sync_shared_end_scale=True,
        alignment="POS_Y",
        origin=origins[0],
    )
    if result != {"FINISHED"}:
        raise AssertionError(f"{label}: chain creation failed")
    stages = tuple(chain.chain_stages(target))
    controllers = tuple(deform.find_controller(target, stage) for stage in stages)
    if len(stages) != COUNT or not all(controllers):
        raise AssertionError(f"{label}: chain is incomplete")

    for index, (controller, origin) in enumerate(zip(controllers, origins)):
        properties = controller.sdh_cage_deform
        deform.core.set_deform_layers(
            properties, ("BEND", "TWIST"), bpy.context)
        properties.origin = origin
        properties.bend_strength = math.radians(BEND_ANGLES[index])
        properties.bend_direction = math.radians(BEND_DIRECTIONS[index])
        properties.twist_strength = math.radians(TWIST_ANGLES[index])
        deform.sync_controller(controller, pull_transform=False)
    deform.core.flush_pending_chain_updates(target)
    bpy.context.view_layer.update()

    evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    evaluated_mesh = evaluated.to_mesh()
    try:
        actual = tuple(vertex.co.copy() for vertex in evaluated_mesh.vertices)
    finally:
        evaluated.to_mesh_clear()

    root_matrix = chain._stage_local_matrix(target, controllers[0])
    stage_errors = []
    for stage, controller in zip(stages, controllers):
        properties = controller.sdh_cage_deform
        stage_matrix = chain._stage_local_matrix(target, controller)
        source_start = float(deform.modifier_input(stage, "Chain Source Start"))
        half = Vector(properties.size) * 0.5
        preview_state = gizmos.cage_preview_geometry_state(properties)
        errors = []
        for ring_t in RING_POSITIONS:
            local_y = -half.y + properties.size.y * ring_t
            root_y = source_start + local_y + half.y
            for x_sign, z_sign in CORNER_SIGNS:
                local = Vector((x_sign * half.x, local_y, z_sign * half.z))
                preview_local = deform.deform_point_from_properties(
                    local,
                    properties,
                    chain_preview=True,
                    preview_output_frame=preview_state[1],
                )
                preview = stage_matrix @ Vector(preview_local)
                source = root_matrix @ Vector((
                    x_sign * half.x,
                    root_y,
                    z_sign * half.z,
                ))
                source_index = min(
                    range(len(vertices)),
                    key=lambda candidate: (
                        Vector(vertices[candidate]) - source).length,
                )
                if (Vector(vertices[source_index]) - source).length > 1.0e-5:
                    raise AssertionError(
                        f"{label}: source sample was not found")
                error = (actual[source_index] - preview).length
                errors.append(error)
        stage_errors.append(max(errors, default=0.0))

    report = {
        "label": label,
        "origins": origins,
        "gap": GAP,
        "stage_cross_section_errors": tuple(stage_errors),
        "max_cross_section_error": max(stage_errors),
    }
    print(f"SDH_CHAIN_ROOT_ORIGIN::CASE::{report!r}")
    if max(stage_errors) > MAX_ALIGNMENT_ERROR:
        raise AssertionError(
            f"{label}: cage/model cross-section mismatch: {stage_errors!r}")
    if tuple(controller.sdh_cage_deform.origin for controller in controllers) != origins:
        raise AssertionError(f"{label}: Origin values were rewritten")
    return actual, report


try:
    reports = []
    for label, origins in CASES:
        actual, report = run_case(label, origins)
        baseline_origins = ("BOTTOM", *origins[1:])
        baseline, baseline_report = run_case(
            f"{label}_BOTTOM_BASELINE", baseline_origins)
        maximum_delta = max(
            (point - baseline_point).length
            for point, baseline_point in zip(actual, baseline))
        if maximum_delta <= MIN_BASELINE_DELTA:
            raise AssertionError(
                f"{label}: root Origin collapsed to Bottom "
                f"({maximum_delta:.9g})")
        report["bottom_baseline_origins"] = baseline_origins
        report["bottom_baseline_max_delta"] = maximum_delta
        reports.append(report)
        print(
            "SDH_CHAIN_ROOT_ORIGIN::BASELINE::"
            f"{label}::{maximum_delta:.9g}")

    print(f"SDH_CHAIN_ROOT_ORIGIN::REPORT::{reports!r}")
    print("SDH_CHAIN_ROOT_ORIGIN::PASS")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
