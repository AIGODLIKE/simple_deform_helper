"""Regression for chained cages with mixed per-stage Origin modes.

Run with:
    blender --background --factory-startup --python-exit-code 1 \
        --python tests/mixed_chain_origin_regression.py

The test compares the evaluated Geometry Nodes result with the same staged
reference evaluator used by the existing chain regression.  The important
case is that each stage may use a different Origin; a chain must still pass
its point-domain eligibility through the full stack and preserve its seams.
"""

from __future__ import annotations

import importlib
import math
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))


def _activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _make_target(name="SDH Mixed Chain Origin"):
    vertices = []
    ring_count = 25
    side_count = 8
    for ring in range(ring_count):
        y = -3.0 + 6.0 * ring / (ring_count - 1)
        for side in range(side_count):
            angle = math.tau * side / side_count
            vertices.append((0.65 * math.cos(angle), y,
                             0.65 * math.sin(angle)))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, (), ())
    target = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(target)
    _activate(target)
    return target, tuple(Vector(vertex) for vertex in vertices)


def _evaluated_points(target):
    bpy.context.view_layer.update()
    evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return tuple(vertex.co.copy() for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def _check(condition, message):
    if not condition:
        raise AssertionError(message)


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
chain = deform.chain


def _run_pattern(target, source, origins, gap=0.0):
    label = f"{origins!r}, gap={gap:.3f}"
    _check(
        bpy.ops.sdh.add_cage_chain(
            count=3,
            connection_mode="CHAINED",
            gap=gap,
            auto_reconnect=True,
            sync_shared_end_scale=True,
            alignment="POS_Y",
            origin="BOTTOM",
        ) == {"FINISHED"},
        f"chain creation failed for {label}",
    )
    stages = chain.chain_stages(target)
    controllers = tuple(deform.find_controller(target, stage)
                        for stage in stages)
    _check(len(stages) == 3 and all(controllers),
           f"chain is incomplete for {label}")

    # Keep the deformation intentionally different per stage.  Mixed origins
    # must not cause an upstream stage to lose ownership of the suffix.  Set
    # all continuous values first and settle the chain so the transient check
    # below isolates the discrete Origin edit itself.
    length_scale = max((6.0 - gap * 2.0) / 6.0, 1.0e-5)
    stage_sizes = tuple(
        (size_x, size_y * length_scale, size_z)
        for size_x, size_y, size_z in (
            (1.45, 2.0, 1.85),
            (1.95, 1.5, 1.35),
            (1.60, 2.5, 2.10),
        )
    )
    for index, controller in enumerate(controllers):
        properties = controller.sdh_cage_deform
        properties.origin = "BOTTOM"
        # Different segment lengths and cross-section sizes exercise the
        # reconnect frame rather than only the default equal partition.
        properties.size = stage_sizes[index]
        properties.bend_strength = math.radians((32.0, -41.0, 27.0)[index])
        properties.bend_direction = math.radians((13.0, -21.0, 39.0)[index])
        properties.twist_strength = math.radians((17.0, 29.0, -23.0)[index])
        properties.taper_factor = (0.12, -0.18, 0.08)[index]
        properties.stretch_factor = (0.05, -0.07, 0.09)[index]
        deform.sync_controller(controller, pull_transform=False)
    deform.core.flush_pending_chain_updates(target)

    # Change only Origin after the settled baseline.  A connected stage's
    # frame must be propagated synchronously, without exposing a stale
    # downstream frame until the timer queue is drained.
    for controller, origin in zip(controllers, origins):
        controller.sdh_cage_deform.origin = origin
    # Property callbacks queue a debounced reconnect.  Capture the immediate
    # pre-flush geometry so this regression can report whether a mixed Origin
    # edit exposes a stale downstream frame during the same UI event.
    pre_flush = _evaluated_points(target)
    deform.core.flush_pending_chain_updates(target)
    post_flush = _evaluated_points(target)
    transient_delta = max(
        ((before - after).length for before, after in zip(pre_flush, post_flush)),
        default=0.0,
    )
    _check(
        transient_delta < 5.0e-4,
        f"{label} exposed stale downstream frame: {transient_delta}",
    )

    expected = []
    for source_point in source:
        point = Vector(source_point)
        eligible = True
        for controller in controllers:
            matrix = chain._stage_local_matrix(target, controller)
            local = matrix.inverted_safe() @ point
            domain_local = deform.core.chain_input_point_from_properties(
                local, controller.sdh_cage_deform)
            half_y = float(controller.sdh_cage_deform.size[1]) * 0.5
            next_eligible = (
                eligible and domain_local.y >= half_y - 1.0e-4)
            deformed = deform.deform_point_from_properties(
                local,
                controller.sdh_cage_deform,
                evaluator=True,
                chain_eligible=eligible,
            )
            point = matrix @ deformed
            eligible = next_eligible
        expected.append(point)

    actual = _evaluated_points(target)
    errors = tuple((actual_point - expected_point).length
                   for actual_point, expected_point in zip(actual, expected))
    maximum = max(errors, default=0.0)
    if maximum >= 5.0e-4:
        worst = errors.index(maximum)
        print("SDH_MIXED_ORIGIN::DEBUG", {
            "pattern": origins,
            "gap": gap,
            "index": worst,
            "source": tuple(round(value, 6) for value in source[worst]),
            "actual": tuple(round(value, 6) for value in actual[worst]),
            "expected": tuple(round(value, 6) for value in expected[worst]),
        })
        point = Vector(source[worst])
        eligible = True
        for stage, controller in zip(stages, controllers):
            matrix = chain._stage_local_matrix(target, controller)
            local = matrix.inverted_safe() @ point
            properties = controller.sdh_cage_deform
            frame = deform.core.chain_input_frame_for_controller(
                controller, stage, properties)
            delta = local - frame[0]
            adjusted = Vector((
                delta.dot(frame[1]),
                delta.dot(frame[2]) - properties.size[1] * 0.5,
                delta.dot(frame[3]),
            )) if chain.stage_chain_index(stage, 0) > 0 else local
            output = deform.deform_point_from_properties(
                local, properties, evaluator=True,
                chain_eligible=eligible)
            print("SDH_MIXED_ORIGIN::STAGE", {
                "index": chain.stage_chain_index(stage, 0),
                "eligible": eligible,
                "local": tuple(round(value, 6) for value in local),
                "adjusted": tuple(round(value, 6) for value in adjusted),
                "output": tuple(round(value, 6) for value in output),
            })
            half_y = properties.size[1] * 0.5
            eligible = eligible and adjusted.y >= half_y - 1.0e-4
            point = matrix @ output
    _check(maximum < 5.0e-4,
           f"{label} GN/reference mismatch: {maximum}")

    changed_rings = {
        index // 8
        for index, (actual_point, source_point)
        in enumerate(zip(actual, source))
        if (actual_point - source_point).length > 1.0e-3
    }
    _check(len(changed_rings) >= 23,
           f"{label} deformed only {len(changed_rings)}/25 rings")
    report = chain.validate_chain(target, chain.stage_chain_uuid(stages[0]))
    _check(not report["broken"],
           f"{label} chain metadata became broken: {report['messages']!r}")
    return round(maximum, 7), tuple(sorted(changed_rings)), round(transient_delta, 7)


cases = (
    (("BOTTOM", "TOP", "CENTER"), 0.0),
    (("TOP", "CENTER", "SYMMETRIC"), 0.0),
    (("CENTER", "SYMMETRIC", "BOTTOM"), 0.0),
    (("SYMMETRIC", "BOTTOM", "TOP"), 0.0),
    # A nonzero gap exercises the identity branch between adjacent cages.
    # These two cases failed before the GN branch returned raw input there.
    (("BOTTOM", "TOP", "CENTER"), 0.4),
    (("TOP", "TOP", "TOP"), 0.4),
)
results = {}
try:
    for pattern, gap in cases:
        target, source = _make_target()
        results[(pattern, gap)] = _run_pattern(target, source, pattern, gap)
except Exception as exc:
    print(f"SDH_MIXED_ORIGIN::FAIL::{type(exc).__name__}::{exc}")
    traceback.print_exc()
    raise
else:
    print(f"SDH_MIXED_ORIGIN::PASS::{results!r}")
finally:
    # Remove generated targets and their controller objects before Blender
    # exits so a failure cannot leak state into a later test process.
    for obj in tuple(bpy.data.objects):
        if obj.name.startswith("SDH Mixed Chain Origin"):
            bpy.data.objects.remove(obj, do_unlink=True)
