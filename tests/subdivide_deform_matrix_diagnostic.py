"""Measure geometry drift for all 325 ordered standard-deform stacks.

This is a diagnostic matrix, not a pass/fail regression.  It compares one
evaluated cage with the chain produced by ``sdh.subdivide_cage_to_chain`` for
every ordered non-empty subset of Bend, Twist, Taper, Stretch, and Shear.  The
default run uses one canonical origin and segment count so it contains exactly
325 executions.  Repeated ``--origin`` or ``--segments`` options deliberately
expand that execution matrix while preserving the same stable stack case IDs.

Run with:
    blender --background --factory-startup --python-exit-code 1 \
        --python tests/subdivide_deform_matrix_diagnostic.py \
        -- --output path/to/report.json

The JSON report and its sibling CSV contain stable ``SDH-STACK-001`` through
``SDH-STACK-325`` IDs plus finite/error/runtime fields suitable for comparing
Blender builds.  Pass ``--csv-output`` to override the derived CSV path.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import itertools
import json
import math
import sys
import time
from pathlib import Path

import bpy
from mathutils import Euler, Vector


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))

ORIGINS = ("BOTTOM", "TOP", "CENTER", "SYMMETRIC")
SEGMENT_COUNTS = (2, 3, 4, 5)
ALIGNMENTS = ("POS_X", "NEG_X", "POS_Y", "NEG_Y", "POS_Z", "NEG_Z")
DEFAULT_ORIGIN = "BOTTOM"
DEFAULT_SEGMENT_COUNT = 3
DEFAULT_ALIGNMENT = "POS_Z"
STANDARD_DEFORM_TYPES = ("BEND", "TWIST", "TAPER", "STRETCH", "SHEAR")
EXPECTED_LAYER_CASE_COUNT = 325


def ordered_nonempty_subsets(values):
    """Return every permutation of every non-empty subset, length first."""
    values = tuple(values)
    return tuple(
        permutation
        for length in range(1, len(values) + 1)
        for permutation in itertools.permutations(values, length)
    )


LAYER_CASES = ordered_nonempty_subsets(STANDARD_DEFORM_TYPES)
if (
    len(LAYER_CASES) != EXPECTED_LAYER_CASE_COUNT
    or len(set(LAYER_CASES)) != EXPECTED_LAYER_CASE_COUNT
):
    raise AssertionError(
        "standard deformation catalog must contain exactly 325 unique stacks"
    )

LAYER_CATALOG = tuple(
    {
        "case_id": f"SDH-STACK-{index:03d}",
        "case_index": index,
        "stack_size": len(layers),
        "case": "+".join(layers),
        "deform_types": layers,
    }
    for index, layers in enumerate(LAYER_CASES, 1)
)
LAYER_CATALOG_BY_STACK = {tuple(item["deform_types"]): item for item in LAYER_CATALOG}

RING_COUNT = 41
SIDE_COUNT = 11
AXIS_MIN = -3.0
AXIS_MAX = 3.0
CHAIN_GAP = 0.0


def parse_args():
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else ()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        "--json-output",
        dest="output",
        type=Path,
        help="Write the complete JSON report to this path.",
    )
    parser.add_argument(
        "--csv-output",
        type=Path,
        help=(
            "Write one flat row per execution. Defaults to the JSON output "
            "path with a .csv suffix."
        ),
    )
    parser.add_argument(
        "--preserve-volume",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--gap", type=float, default=CHAIN_GAP)
    parser.add_argument(
        "--alignment",
        choices=ALIGNMENTS,
        default=DEFAULT_ALIGNMENT,
        help=f"World-space cage alignment. Default: {DEFAULT_ALIGNMENT}.",
    )
    parser.add_argument(
        "--layers",
        action="append",
        help="Only run a stack such as BEND+TWIST; may be repeated.",
    )
    parser.add_argument(
        "--origin",
        action="append",
        choices=ORIGINS,
        help=(f"Run this origin; may be repeated. Default: {DEFAULT_ORIGIN}."),
    )
    parser.add_argument(
        "--segments",
        action="append",
        type=int,
        choices=SEGMENT_COUNTS,
        help=(
            "Run this segment count; may be repeated. "
            f"Default: {DEFAULT_SEGMENT_COUNT}."
        ),
    )
    parser.add_argument(
        "--distribution",
        choices=(
            "split",
            "root-non-bend",
            "tip-non-bend",
            "root-bend",
            "tip-bend",
            "linear-stretch",
        ),
        default="split",
        help="Diagnostic parameter distribution applied after subdivision.",
    )
    parser.add_argument("--stretch-exponent-multiplier", type=float, default=1.0)
    parser.add_argument(
        "--max-normalized-error",
        type=float,
        help=(
            "Fail when any case exceeds this maximum vertex error divided "
            "by the source-bounds diagonal."
        ),
    )
    parser.add_argument(
        "--end-profile",
        choices=("identity", "scale", "offset", "combined"),
        default="identity",
        help="Optional asymmetric end scale/offset profile for split diagnostics.",
    )
    parser.add_argument(
        "--zero-deform",
        action="store_true",
        help="Keep the requested stack but set all operation strengths to zero.",
    )
    parser.add_argument(
        "--verbose-cases",
        action="store_true",
        help="Print each complete case record instead of a compact progress line.",
    )
    return parser.parse_args(arguments)


def mesh_data():
    """Return an asymmetric tube with enough axial samples for every mode."""
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
            vertices.append(
                (
                    center_x + radius_x * math.cos(angle),
                    y,
                    center_z + radius_z * math.sin(angle),
                )
            )
    for ring in range(RING_COUNT - 1):
        current = ring * SIDE_COUNT
        following = (ring + 1) * SIDE_COUNT
        for side in range(SIDE_COUNT):
            next_side = (side + 1) % SIDE_COUNT
            faces.append(
                (
                    current + side,
                    current + next_side,
                    following + next_side,
                    following + side,
                )
            )
    return tuple(vertices), tuple(faces)


VERTICES, FACES = mesh_data()


def alignment_rotation(alignment):
    """Return the controller rotation used by the production axis fitter."""
    return {
        "POS_X": Euler((0.0, 0.0, -math.pi * 0.5)),
        "NEG_X": Euler((0.0, 0.0, math.pi * 0.5)),
        "POS_Y": Euler((0.0, 0.0, 0.0)),
        "NEG_Y": Euler((math.pi, 0.0, 0.0)),
        "POS_Z": Euler((math.pi * 0.5, 0.0, 0.0)),
        "NEG_Z": Euler((-math.pi * 0.5, 0.0, 0.0)),
    }[alignment]


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


def bounds(points):
    minimum = Vector(
        tuple(min(getattr(point, axis) for point in points) for axis in "xyz")
    )
    maximum = Vector(
        tuple(max(getattr(point, axis) for point in points) for axis in "xyz")
    )
    return minimum, maximum


def rms(values):
    return math.sqrt(sum(value * value for value in values) / max(len(values), 1))


def percentile(values, proportion):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(round((len(ordered) - 1) * proportion), len(ordered) - 1)
    return ordered[index]


def finite_point(point):
    return all(math.isfinite(float(component)) for component in point)


def finite_bounds(points):
    points = tuple(point for point in points if finite_point(point))
    if not points:
        zero = Vector((0.0, 0.0, 0.0))
        return zero.copy(), zero.copy()
    return bounds(points)


def geometry_metrics(before, after):
    if len(before) != len(after):
        raise AssertionError(
            f"subdivision changed vertex count: {len(before)} -> {len(after)}"
        )

    finite_before = tuple(finite_point(point) for point in before)
    finite_after = tuple(finite_point(point) for point in after)
    finite_pairs = tuple(
        before_ok and after_ok
        for before_ok, after_ok in zip(finite_before, finite_after)
    )
    indexed_vertex_errors = tuple(
        (after_point - before_point).length if is_finite else None
        for before_point, after_point, is_finite in zip(before, after, finite_pairs)
    )
    vertex_errors = tuple(value for value in indexed_vertex_errors if value is not None)
    ring_max_errors = tuple(
        max(
            (
                value
                for value in indexed_vertex_errors[
                    ring * SIDE_COUNT : (ring + 1) * SIDE_COUNT
                ]
                if value is not None
            ),
            default=0.0,
        )
        for ring in range(RING_COUNT)
    )
    before_min, before_max = finite_bounds(before)
    after_min, after_max = finite_bounds(after)
    finite_before_points = tuple(
        point for point, is_finite in zip(before, finite_before) if is_finite
    )
    finite_after_points = tuple(
        point for point, is_finite in zip(after, finite_after) if is_finite
    )
    before_center = (before_min + before_max) * 0.5
    after_center = (after_min + after_max) * 0.5
    bounds_shift = after_center - before_center
    centroid_shift = average(finite_after_points) - average(finite_before_points)
    centered_errors = tuple(
        ((after_point - after_center) - (before_point - before_center)).length
        for before_point, after_point, is_finite in zip(before, after, finite_pairs)
        if is_finite
    )
    diagonal = max((before_max - before_min).length, 1.0e-9)

    edge_errors = []

    def append_edge_error(left, right):
        if not (
            finite_pairs[left]
            and finite_pairs[right]
            and finite_point(after[right] - after[left])
            and finite_point(before[right] - before[left])
        ):
            return
        edge_errors.append(
            abs(
                (after[right] - after[left]).length
                - (before[right] - before[left]).length
            )
        )

    for ring in range(RING_COUNT):
        current = ring * SIDE_COUNT
        for side in range(SIDE_COUNT):
            append_edge_error(
                current + side,
                current + (side + 1) % SIDE_COUNT,
            )
    for ring in range(RING_COUNT - 1):
        current = ring * SIDE_COUNT
        following = (ring + 1) * SIDE_COUNT
        for side in range(SIDE_COUNT):
            append_edge_error(current + side, following + side)

    finite_vertex_count = sum(finite_after)
    non_finite_vertex_count = len(after) - finite_vertex_count
    finite_coordinate_count = sum(
        math.isfinite(float(component)) for point in after for component in point
    )
    coordinate_count = len(after) * 3

    return {
        "finite": non_finite_vertex_count == 0,
        "metrics_complete": all(finite_pairs),
        "finite_vertex_count": finite_vertex_count,
        "non_finite_vertex_count": non_finite_vertex_count,
        "finite_coordinate_count": finite_coordinate_count,
        "non_finite_coordinate_count": (coordinate_count - finite_coordinate_count),
        "finite_error_count": len(vertex_errors),
        "vertex_count": len(before),
        "before_bounds": (tuple(before_min), tuple(before_max)),
        "after_bounds": (tuple(after_min), tuple(after_max)),
        "source_bounds_diagonal": diagonal,
        "max_vertex_error": max(vertex_errors, default=0.0),
        "ring_max_errors": ring_max_errors,
        "p95_vertex_error": percentile(vertex_errors, 0.95),
        "rms_vertex_error": rms(vertex_errors),
        "normalized_max_vertex_error": (max(vertex_errors, default=0.0) / diagonal),
        "bounds_center_shift": tuple(bounds_shift),
        "bounds_center_shift_length": bounds_shift.length,
        "centroid_shift": tuple(centroid_shift),
        "centroid_shift_length": centroid_shift.length,
        "max_centered_shape_error": max(centered_errors, default=0.0),
        "rms_centered_shape_error": rms(centered_errors),
        "max_edge_length_error": max(edge_errors, default=0.0),
        "rms_edge_length_error": rms(edge_errors),
    }


def remove_case(target, controllers, node_groups):
    invalidate = getattr(deform.core, "invalidate_chain_affine_cache", None)
    if invalidate is not None:
        invalidate(target)
    # The cache is intentionally process-global in the add-on.  Clearing it
    # here prevents a freed Blender pointer being reused by the next case in
    # this long-running diagnostic matrix.
    cache = getattr(deform.core, "_CHAIN_AFFINE_FRAME_CACHE", None)
    if cache is not None:
        cache.clear()
    activate(target)
    for controller in controllers:
        if controller is not None and controller.name in bpy.data.objects:
            bpy.data.objects.remove(controller, do_unlink=True)
    mesh = target.data
    if target.name in bpy.data.objects:
        bpy.data.objects.remove(target, do_unlink=True)
    if mesh is not None and mesh.name in bpy.data.meshes:
        bpy.data.meshes.remove(mesh)
    for node_group in node_groups:
        if node_group is not None and node_group.name in bpy.data.node_groups:
            bpy.data.node_groups.remove(node_group)


def run_case(
    deform,
    chain,
    case_spec,
    origin,
    segment_count,
    preserve_volume,
    gap,
    distribution,
    stretch_exponent_multiplier,
    end_profile,
    zero_deform,
    alignment,
    verbose_cases,
):
    case_started = time.perf_counter()
    layers = tuple(case_spec["deform_types"])
    case_id = str(case_spec["case_id"])
    case_name = "+".join(layers)
    execution_id = (
        f"{case_id}:{alignment}:{origin}:N{segment_count}:"
        f"G{gap:g}:P{end_profile}:D{distribution}"
    )
    rotation = alignment_rotation(alignment)
    rotation_matrix = rotation.to_matrix()
    source_vertices = tuple(
        rotation_matrix @ Vector(point) for point in VERTICES
    )
    mesh = bpy.data.meshes.new(f"SDH Matrix {case_name} {origin} {segment_count} Mesh")
    mesh.from_pydata(source_vertices, (), FACES)
    target = bpy.data.objects.new(
        f"SDH Matrix {case_name} {origin} {segment_count}", mesh
    )
    bpy.context.collection.objects.link(target)
    activate(target)

    modifier, controller, _previous = deform.create_deform_stage(bpy.context, target)
    properties = controller.sdh_cage_deform
    properties.alignment = alignment
    properties.size = (2.2, AXIS_MAX - AXIS_MIN, 1.8)
    properties.mode = "LIMITED"
    properties.origin = origin
    properties.preserve_volume = preserve_volume
    properties.bend_direction = math.radians(23.0)
    properties.bend_strength = (
        0.0 if zero_deform else (math.radians(74.0) if "BEND" in layers else 0.0)
    )
    properties.twist_strength = (
        0.0 if zero_deform else (math.radians(-67.0) if "TWIST" in layers else 0.0)
    )
    properties.taper_factor = (
        0.0 if zero_deform else (0.48 if "TAPER" in layers else 0.0)
    )
    properties.stretch_factor = (
        0.0 if zero_deform else (0.36 if "STRETCH" in layers else 0.0)
    )
    properties.shear_factors = (
        (0.0, 0.0) if zero_deform or "SHEAR" not in layers else (0.31, -0.19)
    )
    properties.bottom_scale = (
        (0.82, 1.08) if end_profile in {"scale", "combined"} else (1.0, 1.0)
    )
    properties.top_scale = (
        (1.35, 0.76) if end_profile in {"scale", "combined"} else (1.0, 1.0)
    )
    properties.bottom_offset = (
        (-0.22, 0.13) if end_profile in {"offset", "combined"} else (0.0, 0.0)
    )
    properties.top_offset = (
        (0.37, -0.18) if end_profile in {"offset", "combined"} else (0.0, 0.0)
    )
    controller.location = (0.0, 0.0, 0.0)
    controller.rotation_mode = "XYZ"
    controller.rotation_euler = rotation
    deform.core.set_deform_layers(properties, layers, bpy.context)
    authored_order = tuple(deform.core.ordered_deform_types(properties))
    if authored_order != layers:
        raise AssertionError(
            f"{case_name}/{origin}/{segment_count}: stack is {authored_order!r}"
        )
    deform.sync_controller(controller, pull_transform=False)
    bpy.context.view_layer.update()

    before = evaluated_points(target)
    target.modifiers.active = modifier
    activate(target)
    subdivision_started = time.perf_counter()
    result = bpy.ops.sdh.subdivide_cage_to_chain(
        count=segment_count,
        gap=gap,
        auto_reconnect=True,
        sync_shared_end_scale=True,
    )
    if result != {"FINISHED"}:
        raise AssertionError(
            f"{case_name}/{origin}/{segment_count}: operator returned {result!r}"
        )
    deform.core.flush_pending_chain_updates(target)
    subdivision_runtime = time.perf_counter() - subdivision_started
    stages_after_split = tuple(chain.chain_stages(target))
    controllers_after_split = tuple(
        deform.find_controller(target, stage) for stage in stages_after_split
    )
    if "STRETCH" in layers and abs(stretch_exponent_multiplier - 1.0) > 1.0e-9:
        stage_scale = 1.36 ** (stretch_exponent_multiplier / segment_count)
        for stage_controller in controllers_after_split:
            stage_controller.sdh_cage_deform.stretch_factor = stage_scale - 1.0
            deform.sync_controller(stage_controller, pull_transform=False)
        chain.reconnect_chain(target, chain.stage_chain_uuid(stages_after_split[0]))
        deform.core.flush_pending_chain_updates(target)
    if distribution != "split":
        bend_total = math.radians(74.0) if "BEND" in layers else 0.0
        twist_total = math.radians(-67.0) if "TWIST" in layers else 0.0
        taper_total = 0.48 if "TAPER" in layers else 0.0
        stretch_total = 0.36 if "STRETCH" in layers else 0.0
        shear_total = (0.31, -0.19) if "SHEAR" in layers else (0.0, 0.0)
        for index, stage_controller in enumerate(controllers_after_split):
            props = stage_controller.sdh_cage_deform
            if distribution == "linear-stretch":
                props.stretch_factor = stretch_total / segment_count
            elif distribution in {"root-non-bend", "tip-non-bend"}:
                owner = 0 if distribution == "root-non-bend" else segment_count - 1
                props.twist_strength = twist_total if index == owner else 0.0
                props.taper_factor = taper_total if index == owner else 0.0
                props.stretch_factor = stretch_total if index == owner else 0.0
                props.shear_factors = shear_total if index == owner else (0.0, 0.0)
            else:
                owner = 0 if distribution == "root-bend" else segment_count - 1
                props.bend_strength = bend_total if index == owner else 0.0
            deform.sync_controller(stage_controller, pull_transform=False)
        chain.reconnect_chain(target, chain.stage_chain_uuid(stages_after_split[0]))
        deform.core.flush_pending_chain_updates(target)
    bpy.context.view_layer.update()
    after = evaluated_points(target)

    stages = tuple(chain.chain_stages(target))
    controllers = tuple(deform.find_controller(target, stage) for stage in stages)
    if len(stages) != segment_count or not all(controllers):
        raise AssertionError(f"{case_name}/{origin}/{segment_count}: incomplete chain")

    stage_matrices = tuple(
        chain._stage_local_matrix(target, item) for item in controllers
    )
    source_starts = tuple(
        deform.core._chain_domain_input_values(item, stage)["Chain Source Start"]
        for item, stage in zip(controllers, stages)
    )
    # Isolate the root modifier so a frame mismatch can be distinguished from
    # downstream conjugation errors while developing chain profiles.
    viewport_states = tuple(bool(stage.show_viewport) for stage in stages)
    for stage in stages[1:]:
        stage.show_viewport = False
    try:
        target.update_tag()
        bpy.context.view_layer.update()
        root_only = evaluated_points(target)
    finally:
        for stage, state in zip(stages, viewport_states):
            stage.show_viewport = state
        target.update_tag()
        bpy.context.view_layer.update()
    root_matrix = stage_matrices[0]
    root_properties = controllers[0].sdh_cage_deform
    root_python = []
    root_python_raw = []
    for source_point in source_vertices:
        source_world = Vector(source_point)
        source_local = root_matrix.inverted_safe() @ source_world
        root_python.append(
            root_matrix
            @ deform.deform_point_from_properties(
                source_local,
                root_properties,
                evaluator=True,
                chain_eligible=True,
                chain_source_coordinate=source_local.y,
                chain_source_start=source_starts[0],
            )
        )
        root_python_raw.append(
            root_matrix
            @ deform.deform_point_from_properties(
                source_local,
                root_properties,
                evaluator=True,
                apply_chain_input_offset=False,
                chain_source_coordinate=source_local.y,
                chain_source_start=source_starts[0],
            )
        )
    global_values = deform.core._chain_domain_input_values(controllers[0], stages[0])
    global_active = bool(global_values.get("Chain Global Stretch Active", False))
    suffix_active = bool(global_values.get("Chain Global Suffix Active", False))
    global_origin = global_values.get(
        "Chain Global Stretch Origin", deform.core.ORIGIN_VALUES["BOTTOM"]
    )
    global_factor = global_values.get("Chain Global Stretch Factor", 0.0)
    global_center = global_values.get("Chain Global Stretch Center", (0.0, 0.0, 0.0))
    global_rotation = global_values.get(
        "Chain Global Stretch Rotation", (0.0, 0.0, 0.0)
    )
    global_offset = global_values.get("Chain Global Stretch Source Offset", 0.0)
    global_length = global_values.get("Chain Global Stretch Length", 2.0)
    global_preserve_volume = bool(controllers[0].sdh_cage_deform.preserve_volume)
    python_after = []
    for source_point in source_vertices:
        point = Vector(source_point)
        source_coordinate = (stage_matrices[0].inverted_safe() @ point).y
        for index, (stage, stage_controller, matrix, source_start) in enumerate(
            zip(stages, controllers, stage_matrices, source_starts)
        ):
            local = matrix.inverted_safe() @ point
            point = matrix @ deform.deform_point_from_properties(
                local,
                stage_controller.sdh_cage_deform,
                evaluator=True,
                chain_eligible=(
                    index == 0 or source_coordinate >= source_start - 1.0e-5
                ),
                chain_source_coordinate=source_coordinate,
                chain_source_start=source_start,
            )
        if suffix_active:
            point = deform.core.apply_chain_global_suffix(
                point,
                source_coordinate,
                deform_mask=global_values.get(
                    "Chain Global Suffix Types", 0),
                twist=global_values.get("Chain Global Suffix Twist", 0.0),
                taper=global_values.get("Chain Global Suffix Taper", 0.0),
                stretch=global_factor,
                shear=global_values.get(
                    "Chain Global Suffix Shear", (0.0, 0.0, 0.0)),
                pre_shear_mask=global_values.get(
                    "Chain Global Suffix Pre Shear Types", 0),
                post_shear_mask=global_values.get(
                    "Chain Global Suffix Post Shear Types", 0),
                center=global_center,
                rotation=global_rotation,
                source_offset=global_offset,
                length=global_length,
                origin=global_origin,
                preserve_volume=global_preserve_volume,
            )
        elif global_active:
            point = deform.core.apply_chain_global_stretch(
                point,
                source_coordinate,
                factor=global_factor,
                center=global_center,
                rotation=global_rotation,
                source_offset=global_offset,
                length=global_length,
                origin=global_origin,
                preserve_volume=global_preserve_volume,
            )
        python_after.append(point)

    incoming_frame_residuals = []
    fitted_incoming_residuals = []
    fitted_frame_deltas = []
    for current_index in range(1, len(stages)):
        current_matrix = stage_matrices[current_index]
        half_y = controllers[current_index].sdh_cage_deform.size[1] * 0.5
        input_frame = deform.core.chain_conjugation_frames_for_controller(
            controllers[current_index], stages[current_index]
        )[0]
        input_affine = deform.core._chain_input_affine(input_frame, half_y)

        def actual_incoming(authored):
            source_world = current_matrix @ Vector(authored)
            source_coordinate = (stage_matrices[0].inverted_safe() @ source_world).y
            point = source_world.copy()
            for prior_index in range(current_index):
                prior_matrix = stage_matrices[prior_index]
                prior_start = source_starts[prior_index]
                local = prior_matrix.inverted_safe() @ point
                point = prior_matrix @ deform.deform_point_from_properties(
                    local,
                    controllers[prior_index].sdh_cage_deform,
                    evaluator=True,
                    chain_eligible=(
                        prior_index == 0 or source_coordinate >= prior_start - 1.0e-5
                    ),
                    chain_source_coordinate=source_coordinate,
                    chain_source_start=prior_start,
                )
            return current_matrix.inverted_safe() @ point

        fitted_affine = deform.core._sample_chain_affine(
            actual_incoming, -half_y, half_y, sample_fraction=0.001
        )
        residual = 0.0
        fitted_residual = 0.0
        for source_point in source_vertices:
            source_world = Vector(source_point)
            source_coordinate = (stage_matrices[0].inverted_safe() @ source_world).y
            if source_coordinate < source_starts[current_index] - 1.0e-5:
                continue
            authored = current_matrix.inverted_safe() @ source_world
            point = source_world.copy()
            for prior_index in range(current_index):
                prior_matrix = stage_matrices[prior_index]
                prior_start = source_starts[prior_index]
                local = prior_matrix.inverted_safe() @ point
                point = prior_matrix @ deform.deform_point_from_properties(
                    local,
                    controllers[prior_index].sdh_cage_deform,
                    evaluator=True,
                    chain_eligible=(
                        prior_index == 0 or source_coordinate >= prior_start - 1.0e-5
                    ),
                    chain_source_coordinate=source_coordinate,
                    chain_source_start=prior_start,
                )
            incoming = current_matrix.inverted_safe() @ point
            residual = max(residual, (incoming - input_affine @ authored).length)
            fitted_residual = max(
                fitted_residual, (incoming - fitted_affine @ authored).length
            )
        incoming_frame_residuals.append(residual)
        fitted_incoming_residuals.append(fitted_residual)
        fitted_frame_deltas.append(
            max(
                abs(input_affine[row][column] - fitted_affine[row][column])
                for row in range(4)
                for column in range(4)
            )
        )

    report = geometry_metrics(before, after)
    python_metrics = geometry_metrics(before, python_after)
    report["python_max_vertex_error"] = python_metrics["max_vertex_error"]
    report["gn_python_max_error"] = max(
        ((gn - py).length for gn, py in zip(after, python_after)),
        default=0.0,
    )
    report["root_only_max_error"] = max(
        ((gn - py).length for gn, py in zip(root_only, root_python)),
        default=0.0,
    )
    root_delta_index = max(
        range(len(root_only)),
        key=lambda index: (root_only[index] - root_python[index]).length,
        default=0,
    )
    report["root_delta_index"] = root_delta_index
    report["root_delta"] = tuple(
        root_only[root_delta_index] - root_python[root_delta_index]
    )
    report["root_only_sample"] = tuple(root_only[root_delta_index])
    report["root_python_sample"] = tuple(root_python[root_delta_index])
    report["root_python_raw_sample"] = tuple(root_python_raw[root_delta_index])
    report["root_output_delta"] = tuple(
        root_python[root_delta_index] - root_python_raw[root_delta_index]
    )
    report["incoming_frame_residuals"] = incoming_frame_residuals
    report["fitted_incoming_residuals"] = fitted_incoming_residuals
    report["fitted_frame_deltas"] = fitted_frame_deltas
    report.update(
        {
            "case_id": case_id,
            "case_index": int(case_spec["case_index"]),
            "execution_id": execution_id,
            "stack_size": len(layers),
            "case": case_name,
            "deform_types": layers,
            "alignment": alignment,
            "origin": origin,
            "segment_count": segment_count,
            "gap": gap,
            "preserve_volume": preserve_volume,
            "subdivision_runtime_seconds": subdivision_runtime,
            "stage_origins": tuple(item.sdh_cage_deform.origin for item in controllers),
            "stage_centers": tuple(tuple(item.location) for item in controllers),
            "stage_sizes": tuple(
                tuple(item.sdh_cage_deform.size) for item in controllers
            ),
            "stage_source_starts": source_starts,
            "stage_source_ends": tuple(
                deform.core._chain_domain_input_values(item, stage)["Chain Source End"]
                for item, stage in zip(controllers, stages)
            ),
            "stage_chain_input_frames": tuple(
                tuple(tuple(vector) for vector in frame)
                for item, stage in zip(controllers, stages)
                for frame in (
                    deform.core.chain_conjugation_frames_for_controller(item, stage)[0],
                )
            ),
            "stage_chain_output_frames": tuple(
                tuple(tuple(vector) for vector in frame)
                for item, stage in zip(controllers, stages)
                for frame in (
                    deform.core.chain_conjugation_frames_for_controller(item, stage)[1],
                )
            ),
            "stage_bend_strengths": tuple(
                item.sdh_cage_deform.bend_strength for item in controllers
            ),
            "stage_twist_strengths": tuple(
                item.sdh_cage_deform.twist_strength for item in controllers
            ),
            "stage_taper_factors": tuple(
                item.sdh_cage_deform.taper_factor for item in controllers
            ),
            "stage_stretch_factors": tuple(
                item.sdh_cage_deform.stretch_factor for item in controllers
            ),
            "stage_shear_factors": tuple(
                tuple(item.sdh_cage_deform.shear_factors) for item in controllers
            ),
            "stage_bottom_scales": tuple(
                tuple(item.sdh_cage_deform.bottom_scale) for item in controllers
            ),
            "stage_top_scales": tuple(
                tuple(item.sdh_cage_deform.top_scale) for item in controllers
            ),
            "stage_bottom_offsets": tuple(
                tuple(item.sdh_cage_deform.bottom_offset) for item in controllers
            ),
            "stage_top_offsets": tuple(
                tuple(item.sdh_cage_deform.top_offset) for item in controllers
            ),
            "stage_deform_masks": tuple(
                deform.core.modifier_input(stage, "Deform Types") for stage in stages
            ),
            "stage_shear_socket_values": tuple(
                tuple(deform.core.modifier_input(stage, "Shear"))
                for stage in stages
            ),
            "stage_global_prefix_active": tuple(
                bool(deform.core.modifier_input(
                    stage, "Chain Global Prefix Active"))
                for stage in stages
            ),
            "stage_global_prefix_masks": tuple(
                int(deform.core.modifier_input(
                    stage, "Chain Global Prefix Types"))
                for stage in stages
            ),
            "stage_global_prefix_pre_shear_masks": tuple(
                int(deform.core.modifier_input(
                    stage, "Chain Global Prefix Pre Shear Types"))
                for stage in stages
            ),
            "stage_global_prefix_post_shear_masks": tuple(
                int(deform.core.modifier_input(
                    stage, "Chain Global Prefix Post Shear Types"))
                for stage in stages
            ),
            "stage_global_prefix_shear": tuple(
                tuple(deform.core.modifier_input(
                    stage, "Chain Global Prefix Shear"))
                for stage in stages
            ),
            "stage_global_baseline_masks": tuple(
                int(deform.core._chain_domain_input_values(
                    item, stage).get("Chain Global Baseline Types", 0))
                for item, stage in zip(controllers, stages)
            ),
            "stage_base_shear": tuple(
                tuple(deform.core._chain_domain_input_values(
                    item, stage).get(
                        "Chain Prefix Base Shear", (0.0, 0.0, 0.0)))
                for item, stage in zip(controllers, stages)
            ),
            "stage_global_suffix_active": tuple(
                bool(deform.core.modifier_input(
                    stage, "Chain Global Suffix Active"))
                for stage in stages
            ),
            "stage_global_suffix_masks": tuple(
                int(deform.core.modifier_input(
                    stage, "Chain Global Suffix Types"))
                for stage in stages
            ),
            "stage_global_stretch_active": tuple(
                deform.core.modifier_input(stage, "Chain Global Stretch Active")
                for stage in stages
            ),
            "stage_global_stretch_factor": tuple(
                deform.core.modifier_input(stage, "Chain Global Stretch Factor")
                for stage in stages
            ),
            "stage_tip_flags": tuple(
                deform.core.modifier_input(stage, "Chain Tip Stage") for stage in stages
            ),
            "stage_global_stretch_origin": tuple(
                deform.core.modifier_input(stage, "Chain Global Stretch Origin")
                for stage in stages
            ),
            "stage_global_profile_active": tuple(
                deform.core.modifier_input(stage, "Chain Global Profile Active")
                for stage in stages
            ),
            "stage_global_profile_bottom_scale": tuple(
                tuple(
                    deform.core.modifier_input(
                        stage, "Chain Global Profile Bottom Scale"
                    )
                )
                for stage in stages
            ),
            "stage_global_profile_top_scale": tuple(
                tuple(
                    deform.core.modifier_input(stage, "Chain Global Profile Top Scale")
                )
                for stage in stages
            ),
            "stage_global_profile_bottom_offset": tuple(
                tuple(
                    deform.core.modifier_input(
                        stage, "Chain Global Profile Bottom Offset"
                    )
                )
                for stage in stages
            ),
            "stage_global_profile_top_offset": tuple(
                tuple(
                    deform.core.modifier_input(stage, "Chain Global Profile Top Offset")
                )
                for stage in stages
            ),
            "stage_global_prefix_offset": tuple(
                deform.core.modifier_input(stage, "Chain Global Prefix Source Offset")
                for stage in stages
            ),
            "stage_global_prefix_length": tuple(
                deform.core.modifier_input(stage, "Chain Global Prefix Length")
                for stage in stages
            ),
            "stage_root_flags": tuple(
                deform.core.modifier_input(stage, "Chain Root Stage")
                for stage in stages
            ),
            "stage_root_output_flags": tuple(
                deform.core.modifier_input(stage, "Chain Root Output Active")
                for stage in stages
            ),
            "stage_modes": tuple(
                deform.core.modifier_input(stage, "Mode") for stage in stages
            ),
            "stage_enabled": tuple(
                deform.core.modifier_input(stage, "Stage Enabled") for stage in stages
            ),
            "profile_socket_links": tuple(
                len(
                    group.nodes.get("Group Input")
                    .outputs[
                        group.interface.items_tree.get(
                            "Chain Global Profile Active"
                        ).identifier
                    ]
                    .links
                )
                for group in (stages[0].node_group,)
            ),
            "profile_socket_targets": tuple(
                (
                    link.to_node.name,
                    link.to_socket.name,
                )
                for group in (stages[0].node_group,)
                for link in group.nodes.get("Group Input")
                .outputs[
                    group.interface.items_tree.get(
                        "Chain Global Profile Active"
                    ).identifier
                ]
                .links
            ),
        }
    )
    node_groups = tuple(stage.node_group for stage in stages)
    remove_case(target, controllers, node_groups)
    report["runtime_seconds"] = time.perf_counter() - case_started
    if verbose_cases:
        print(
            "SDH_SUBDIVIDE_MATRIX::CASE::"
            + json.dumps(json_safe(report), sort_keys=True, allow_nan=False)
        )
    else:
        progress = {
            "case_id": case_id,
            "case": case_name,
            "alignment": alignment,
            "finite": report["finite"],
            "max_vertex_error": report["max_vertex_error"],
            "runtime_seconds": report["runtime_seconds"],
        }
        print(
            "SDH_SUBDIVIDE_MATRIX::PROGRESS::"
            + json.dumps(progress, sort_keys=True, allow_nan=False)
        )
    return report


def summarize(reports):
    ranking = sorted(
        reports,
        key=lambda report: (
            not bool(report["finite"]),
            float(report["max_vertex_error"]),
        ),
        reverse=True,
    )

    def aggregate(key_function):
        groups = {}
        for report in reports:
            key = key_function(report)
            groups.setdefault(key, []).append(report)
        result = []
        for key, values in groups.items():
            result.append(
                {
                    "key": key,
                    "case_count": len(values),
                    "finite_case_count": sum(bool(value["finite"]) for value in values),
                    "non_finite_case_count": sum(
                        not bool(value["finite"]) for value in values
                    ),
                    "maximum": max(value["max_vertex_error"] for value in values),
                    "mean": sum(value["max_vertex_error"] for value in values)
                    / len(values),
                    "rms_mean": sum(value["rms_vertex_error"] for value in values)
                    / len(values),
                    "runtime_seconds": sum(
                        value["runtime_seconds"] for value in values
                    ),
                    "mean_runtime_seconds": sum(
                        value["runtime_seconds"] for value in values
                    )
                    / len(values),
                }
            )
        return sorted(result, key=lambda value: value["maximum"], reverse=True)

    return {
        "case_count": len(reports),
        "finite_case_count": sum(bool(report["finite"]) for report in reports),
        "non_finite_case_count": sum(not bool(report["finite"]) for report in reports),
        "runtime_seconds": sum(float(report["runtime_seconds"]) for report in reports),
        "worst_cases": ranking[:20],
        "by_stack": aggregate(lambda report: report["case"]),
        "by_origin": aggregate(lambda report: report["origin"]),
        "by_segment_count": aggregate(lambda report: str(report["segment_count"])),
    }


def selected_case_specs(requested_layers):
    if not requested_layers:
        return LAYER_CATALOG
    selected = []
    seen = set()
    for value in requested_layers:
        layers = tuple(
            item.strip().upper() for item in str(value).split("+") if item.strip()
        )
        if not layers or len(layers) != len(set(layers)):
            raise ValueError(f"invalid ordered deformation stack: {value!r}")
        unknown = tuple(item for item in layers if item not in STANDARD_DEFORM_TYPES)
        if unknown:
            raise ValueError(
                f"unsupported deformation type(s) {unknown!r} in {value!r}"
            )
        case_spec = LAYER_CATALOG_BY_STACK.get(layers)
        if case_spec is None:
            raise ValueError(f"stack is not in the 325-case catalog: {value!r}")
        if layers not in seen:
            selected.append(case_spec)
            seen.add(layers)
    return tuple(selected)


def json_safe(value):
    """Replace non-finite floats with null so reports remain strict JSON."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_safe(item) for item in value]
    return value


CSV_FIELDS = (
    "case_id",
    "case_index",
    "execution_id",
    "stack_size",
    "case",
    "deform_types",
    "alignment",
    "origin",
    "segment_count",
    "gap",
    "preserve_volume",
    "finite",
    "metrics_complete",
    "finite_vertex_count",
    "non_finite_vertex_count",
    "finite_coordinate_count",
    "non_finite_coordinate_count",
    "max_vertex_error",
    "rms_vertex_error",
    "p95_vertex_error",
    "normalized_max_vertex_error",
    "max_centered_shape_error",
    "rms_centered_shape_error",
    "max_edge_length_error",
    "rms_edge_length_error",
    "subdivision_runtime_seconds",
    "runtime_seconds",
)


def write_csv(path, reports):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for report in reports:
            row = {key: report.get(key) for key in CSV_FIELDS}
            row["deform_types"] = "+".join(report["deform_types"])
            writer.writerow(row)


args = parse_args()
entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
chain = deform.chain

try:
    case_specs = selected_case_specs(args.layers)
    origins = tuple(dict.fromkeys(args.origin or (DEFAULT_ORIGIN,)))
    segment_counts = tuple(dict.fromkeys(args.segments or (DEFAULT_SEGMENT_COUNT,)))
    planned_execution_count = len(case_specs) * len(origins) * len(segment_counts)
    is_default_matrix = not args.layers and not args.origin and not args.segments
    if is_default_matrix and planned_execution_count != EXPECTED_LAYER_CASE_COUNT:
        raise AssertionError(
            "default matrix must execute exactly 325 ordered stacks, got "
            f"{planned_execution_count}"
        )
    matrix_started = time.perf_counter()
    reports = tuple(
        run_case(
            deform,
            chain,
            case_spec,
            origin,
            segment_count,
            args.preserve_volume,
            args.gap,
            args.distribution,
            args.stretch_exponent_multiplier,
            args.end_profile,
            args.zero_deform,
            args.alignment,
            args.verbose_cases,
        )
        for case_spec in case_specs
        for origin in origins
        for segment_count in segment_counts
    )
    matrix_runtime = time.perf_counter() - matrix_started
    payload = {
        "schema_version": 1,
        "configuration": {
            "standard_deform_types": STANDARD_DEFORM_TYPES,
            "catalog_case_count": len(LAYER_CATALOG),
            "expected_catalog_case_count": EXPECTED_LAYER_CASE_COUNT,
            "selected_case_count": len(case_specs),
            "planned_execution_count": planned_execution_count,
            "origins": origins,
            "segment_counts": segment_counts,
            "alignment": args.alignment,
            "default_alignment": DEFAULT_ALIGNMENT,
            "default_origin": DEFAULT_ORIGIN,
            "default_segment_count": DEFAULT_SEGMENT_COUNT,
            "chain_gap": args.gap,
            "preserve_volume": args.preserve_volume,
            "evaluation": "analytic_chain_mapping_without_vertex_residual",
            "distribution": args.distribution,
            "end_profile": args.end_profile,
            "parameters": {
                "bend_strength_degrees": 74.0,
                "bend_direction_degrees": 23.0,
                "twist_strength_degrees": -67.0,
                "taper_factor": 0.48,
                "stretch_factor": 0.36,
                "shear_factors": (0.31, -0.19),
            },
        },
        "catalog": LAYER_CATALOG,
        "summary": summarize(reports),
        "cases": reports,
    }
    payload["summary"]["wall_runtime_seconds"] = matrix_runtime
    encoded = json.dumps(json_safe(payload), indent=2, sort_keys=True, allow_nan=False)
    console_summary = {
        "catalog_case_count": len(LAYER_CATALOG),
        "case_count": payload["summary"]["case_count"],
        "finite_case_count": payload["summary"]["finite_case_count"],
        "non_finite_case_count": payload["summary"]["non_finite_case_count"],
        "wall_runtime_seconds": matrix_runtime,
        "by_stack": payload["summary"]["by_stack"],
        "by_origin": payload["summary"]["by_origin"],
        "by_segment_count": payload["summary"]["by_segment_count"],
        "worst_cases": tuple(
            {
                "case_id": report["case_id"],
                "case": report["case"],
                "origin": report["origin"],
                "segment_count": report["segment_count"],
                "max_vertex_error": report["max_vertex_error"],
                "rms_vertex_error": report["rms_vertex_error"],
            }
            for report in payload["summary"]["worst_cases"][:10]
        ),
    }
    print(
        "SDH_SUBDIVIDE_MATRIX::SUMMARY::" + json.dumps(console_summary, sort_keys=True)
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
        print(f"SDH_SUBDIVIDE_MATRIX::JSON::{args.output.resolve()}")
    csv_output = args.csv_output
    if csv_output is None and args.output is not None:
        csv_output = args.output.with_suffix(".csv")
    if csv_output is not None:
        write_csv(csv_output, reports)
        print(f"SDH_SUBDIVIDE_MATRIX::CSV::{csv_output.resolve()}")
    if args.max_normalized_error is not None:
        non_finite = tuple(report for report in reports if not report["finite"])
        if non_finite:
            raise AssertionError(
                "subdivision produced non-finite geometry for "
                f"{non_finite[0]['execution_id']}"
            )
        worst = max(
            reports,
            key=lambda report: report["normalized_max_vertex_error"],
        )
        measured = float(worst["normalized_max_vertex_error"])
        if measured > args.max_normalized_error:
            raise AssertionError(
                "subdivision normalized error "
                f"{measured:.9f} exceeds {args.max_normalized_error:.9f} "
                f"for {worst['case']} / {worst['origin']} / "
                f"{worst['segment_count']} segments"
            )
    print("SDH_SUBDIVIDE_MATRIX::DONE")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
