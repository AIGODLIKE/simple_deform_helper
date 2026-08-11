"""Verify root-cage lower-boundary continuation for every Origin mode.

The interactive failure moves the first cage's bottom boundary upward.  Mesh
points below the new boundary must inherit the deformed bottom frame instead
of snapping back to their undeformed source coordinates.  A Bottom origin is
the identity-frame control; Top, Center, and Symmetric expose the regression.
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
RING_STEP = 0.02
SIDE_COUNT = 12
RADIUS = 0.55
BOUNDARY_DELTA = 0.6
EXTERIOR_OFFSETS = (0.02, 0.2, 0.4, 0.58)
MAX_BOUNDARY_POSITION_ERROR = 2.0e-5
MAX_CONTINUATION_ERROR = 2.0e-3
MAX_PARITY_ERROR = 5.0e-4
MAX_UPSTREAM_INVARIANCE_ERROR = 5.0e-5
MAX_TANGENT_ANGLE_DEGREES = 0.1
ORIGINS = ("BOTTOM", "TOP", "CENTER", "SYMMETRIC")


ring_values = tuple(
    round(SOURCE_MIN + index * RING_STEP, 8)
    for index in range(round((SOURCE_MAX - SOURCE_MIN) / RING_STEP) + 1)
)
vertices = []
vertex_indices = {}
for y in ring_values:
    for side in range(SIDE_COUNT):
        angle = math.tau * side / SIDE_COUNT
        vertex_indices[(y, side)] = len(vertices)
        vertices.append((RADIUS * math.cos(angle), y, RADIUS * math.sin(angle)))
faces = []
for ring_index in range(len(ring_values) - 1):
    current = ring_index * SIDE_COUNT
    following = (ring_index + 1) * SIDE_COUNT
    for side in range(SIDE_COUNT):
        next_side = (side + 1) % SIDE_COUNT
        faces.append((
            current + side,
            current + next_side,
            following + next_side,
            following + side,
        ))


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
chain = deform.chain


def close_vector(left, right, tolerance=MAX_BOUNDARY_POSITION_ERROR):
    return (Vector(left) - Vector(right)).length <= tolerance


def evaluated_points(target):
    evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return tuple(vertex.co.copy() for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def nearest_ring(value):
    result = min(ring_values, key=lambda candidate: abs(candidate - value))
    if abs(result - value) > MAX_BOUNDARY_POSITION_ERROR:
        raise AssertionError(
            f"No source ring at moved root boundary {value:.9g}; nearest={result:.9g}")
    return result


def ring(points, y):
    key = nearest_ring(y)
    return tuple(points[vertex_indices[(key, side)]] for side in range(SIDE_COUNT))


def average(points):
    result = Vector((0.0, 0.0, 0.0))
    for point in points:
        result += point
    return result / max(len(points), 1)


def run_case(origin):
    mesh = bpy.data.meshes.new(f"SDH Root Boundary {origin} Mesh")
    mesh.from_pydata(vertices, (), faces)
    target = bpy.data.objects.new(f"SDH Root Boundary {origin}", mesh)
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
        origin=origin,
    )
    if result != {"FINISHED"}:
        raise AssertionError(f"{origin}: chain creation failed")

    stages = tuple(chain.chain_stages(target))
    controllers = tuple(deform.find_controller(target, stage) for stage in stages)
    if len(stages) != COUNT or not all(controllers):
        raise AssertionError(f"{origin}: incomplete three-stage chain")

    stage_origins = (origin, "CENTER", "SYMMETRIC")
    bend_angles = (50.0, -32.0, 37.0)
    bend_directions = (0.0, 17.0, -21.0)
    for index, controller in enumerate(controllers):
        properties = controller.sdh_cage_deform
        layers = (
            ("BEND", "TWIST")
            if index == 0 and origin == "TOP" else
            ("BEND",)
        )
        deform.core.set_deform_layers(properties, layers, bpy.context)
        properties.origin = stage_origins[index]
        properties.bend_strength = math.radians(bend_angles[index])
        properties.bend_direction = math.radians(bend_directions[index])
        properties.twist_strength = (
            math.radians(28.0)
            if index == 0 and origin == "TOP" else
            0.0
        )
        properties.taper_factor = 0.0
        properties.stretch_factor = 0.0
        deform.sync_controller(controller, pull_transform=False)
    deform.core.flush_pending_chain_updates(target)
    bpy.context.view_layer.update()

    root = controllers[0]
    properties = root.sdh_cage_deform
    initial_size = tuple(properties.size)
    initial_location = tuple(root.location)
    initial_matrix = chain._stage_local_matrix(target, root)
    initial_half = Vector(initial_size) * 0.5
    initial_bottom = initial_matrix @ Vector((0.0, -initial_half.y, 0.0))
    initial_top = initial_matrix @ Vector((0.0, initial_half.y, 0.0))

    applied, _new_length = deform.move_cage_boundary(
        root,
        "BOTTOM",
        BOUNDARY_DELTA,
        initial_size,
        initial_location,
        None,
    )
    deform.core.flush_pending_chain_updates(target)
    bpy.context.view_layer.update()

    moved_half = Vector(properties.size) * 0.5
    moved_matrix = chain._stage_local_matrix(target, root)
    moved_bottom = moved_matrix @ Vector((0.0, -moved_half.y, 0.0))
    moved_top = moved_matrix @ Vector((0.0, moved_half.y, 0.0))
    if abs(applied - BOUNDARY_DELTA) > MAX_BOUNDARY_POSITION_ERROR:
        raise AssertionError(f"{origin}: bottom drag was clamped unexpectedly")
    if not close_vector(moved_top, initial_top):
        raise AssertionError(f"{origin}: bottom drag moved the root top boundary")
    if abs((moved_bottom - initial_bottom).length - BOUNDARY_DELTA) > 2.0e-5:
        raise AssertionError(f"{origin}: root bottom did not move by requested delta")
    if abs(moved_bottom.x) > 2.0e-5 or abs(moved_bottom.z) > 2.0e-5:
        raise AssertionError(f"{origin}: POS_Y root boundary left the source Y axis")

    boundary_y = nearest_ring(moved_bottom.y)
    actual = evaluated_points(target)
    boundary_ring = ring(actual, boundary_y)

    endpoint, _x_axis, _inside_y_axis, _z_axis = chain._stage_boundary_frame(
        target, root, "BOTTOM")
    center_error = (average(boundary_ring) - Vector(endpoint)).length
    raw_boundary_center = Vector((0.0, boundary_y, 0.0))
    frame_motion = (Vector(endpoint) - raw_boundary_center).length

    # A composed Twist stops accumulating outside the lower limit, so its
    # exterior tangent need not equal the cage-interior derivative returned by
    # _stage_boundary_frame.  Derive the terminal exterior axis from the Python
    # evaluator and independently verify GN point parity below.
    local_boundary_center = Vector((0.0, -moved_half.y, 0.0))
    local_exterior_center = local_boundary_center - Vector((0.0, RING_STEP, 0.0))
    python_boundary_center = moved_matrix @ deform.deform_point_from_properties(
        local_boundary_center,
        properties,
        evaluator=True,
        chain_eligible=True,
    )
    python_exterior_center = moved_matrix @ deform.deform_point_from_properties(
        local_exterior_center,
        properties,
        evaluator=True,
        chain_eligible=True,
    )
    terminal_step = python_boundary_center - python_exterior_center
    if terminal_step.length <= 1.0e-8:
        raise AssertionError(f"{origin}: Python terminal exterior collapsed")
    terminal_axis = terminal_step.normalized()
    terminal_step_error = abs(terminal_step.length - RING_STEP)
    inside_terminal_angle = math.degrees(
        terminal_axis.angle(Vector(_inside_y_axis)))

    source_starts = tuple(
        float(deform.modifier_input(stage, "Chain Source Start"))
        for stage in stages)
    root_flags = tuple(
        bool(deform.modifier_input(stage, "Chain Root Stage"))
        for stage in stages)
    if root_flags != (True, False, False):
        raise AssertionError(f"{origin}: invalid chain-root flags {root_flags!r}")
    modifier_center = tuple(deform.modifier_input(stages[0], "Center"))
    modifier_size = tuple(deform.modifier_input(stages[0], "Size"))
    if not close_vector(root.location, modifier_center):
        raise AssertionError(f"{origin}: root controller/modifier centers diverged")
    if not close_vector(properties.size, modifier_size):
        raise AssertionError(f"{origin}: root controller/modifier sizes diverged")
    gaps = tuple(chain.stage_chain_gap(stage) for stage in stages[1:])
    if any(abs(gap - GAP) > MAX_BOUNDARY_POSITION_ERROR for gap in gaps):
        raise AssertionError(f"{origin}: outer-boundary drag changed chain gaps")

    continuation_errors = []
    span_errors = []
    step_errors = []
    tangent_angles = []
    rigidity_errors = []
    parity_errors = []
    exterior_indices = []
    moved_inverse = moved_matrix.inverted_safe()
    for offset in EXTERIOR_OFFSETS:
        exterior_y = nearest_ring(boundary_y - offset)
        actual_offset = boundary_y - exterior_y
        exterior_ring = ring(actual, exterior_y)
        expected_ring = tuple(
            point - terminal_axis * actual_offset for point in boundary_ring)
        continuation_errors.extend(
            (actual_point - expected_point).length
            for actual_point, expected_point in zip(exterior_ring, expected_ring)
        )
        span_errors.append(abs(
            (average(boundary_ring) - average(exterior_ring)).length -
            actual_offset
        ))
        section_steps = tuple(
            boundary_point - exterior_point
            for boundary_point, exterior_point in zip(
                boundary_ring, exterior_ring)
        )
        average_step = average(section_steps)
        rigidity_errors.extend(
            (step - average_step).length for step in section_steps)
        for side, step in enumerate(section_steps):
            step_errors.append(abs(step.length - actual_offset))
            if step.length > 1.0e-8:
                tangent_angles.append(math.degrees(
                    step.normalized().angle(terminal_axis)))

            source_index = vertex_indices[(exterior_y, side)]
            exterior_indices.append(source_index)
            source_point = Vector(target.data.vertices[source_index].co)
            local_point = moved_inverse @ source_point
            python_point = moved_matrix @ deform.deform_point_from_properties(
                local_point,
                properties,
                evaluator=True,
                chain_eligible=True,
            )
            parity_errors.append((actual[source_index] - python_point).length)

    maximum_continuation_error = max(continuation_errors, default=0.0)
    maximum_span_error = max(span_errors, default=0.0)
    maximum_step_error = max(step_errors, default=0.0)
    maximum_tangent_angle = max(tangent_angles, default=0.0)
    maximum_rigidity_error = max(rigidity_errors, default=0.0)
    maximum_parity_error = max(parity_errors, default=0.0)
    if center_error > MAX_CONTINUATION_ERROR:
        raise AssertionError(
            f"{origin}: evaluated bottom section missed its cage frame")
    if origin != "BOTTOM" and frame_motion < 0.05:
        raise AssertionError(
            f"{origin}: bottom frame did not move enough to exercise the bug")
    if maximum_continuation_error > MAX_CONTINUATION_ERROR:
        raise AssertionError(
            f"{origin}: root exterior missed its bottom-frame continuation "
            f"({maximum_continuation_error:.9g})")
    if maximum_span_error > MAX_CONTINUATION_ERROR:
        raise AssertionError(
            f"{origin}: root exterior axial span collapsed "
            f"({maximum_span_error:.9g})")
    if maximum_step_error > MAX_CONTINUATION_ERROR:
        raise AssertionError(
            f"{origin}: root exterior step length changed "
            f"({maximum_step_error:.9g})")
    if terminal_step_error > MAX_CONTINUATION_ERROR:
        raise AssertionError(
            f"{origin}: Python terminal step length changed "
            f"({terminal_step_error:.9g})")
    if maximum_tangent_angle > MAX_TANGENT_ANGLE_DEGREES:
        raise AssertionError(
            f"{origin}: root exterior left the bottom tangent "
            f"({maximum_tangent_angle:.9g} degrees)")
    if origin != "TOP" and inside_terminal_angle > MAX_TANGENT_ANGLE_DEGREES:
        raise AssertionError(
            f"{origin}: pure-Bend inside/outside tangents diverged "
            f"({inside_terminal_angle:.9g} degrees)")
    if maximum_rigidity_error > MAX_CONTINUATION_ERROR:
        raise AssertionError(
            f"{origin}: root exterior cross-section was not rigid "
            f"({maximum_rigidity_error:.9g})")
    if maximum_parity_error > MAX_PARITY_ERROR:
        raise AssertionError(
            f"{origin}: GN/Python root-exterior parity failed "
            f"({maximum_parity_error:.9g})")

    exterior_before_downstream_edit = tuple(
        actual[index].copy() for index in exterior_indices)
    downstream = controllers[1].sdh_cage_deform
    deform.core.set_deform_layers(
        downstream, ("BEND", "TWIST"), bpy.context)
    downstream.bend_strength = math.radians(73.0)
    downstream.bend_direction = math.radians(-36.0)
    downstream.twist_strength = math.radians(61.0)
    deform.sync_controller(controllers[1], pull_transform=False)
    deform.core.flush_pending_chain_updates(target)
    bpy.context.view_layer.update()
    changed = evaluated_points(target)
    maximum_upstream_change = max(
        (changed[index] - before).length
        for index, before in zip(
            exterior_indices, exterior_before_downstream_edit)
    )
    if maximum_upstream_change > MAX_UPSTREAM_INVARIANCE_ERROR:
        raise AssertionError(
            f"{origin}: second-stage edit changed the root exterior "
            f"({maximum_upstream_change:.9g})")

    root_types = tuple(sorted(deform.core.active_deform_types(properties)))
    if origin == "TOP" and "TWIST" not in root_types:
        raise AssertionError("TOP: Bend+Twist coverage was not activated")

    report = {
        "origin": origin,
        "gap": GAP,
        "gaps_after_drag": gaps,
        "applied_boundary_delta": applied,
        "boundary_y": boundary_y,
        "source_starts": source_starts,
        "chain_root_flags": root_flags,
        "bottom_frame_motion": frame_motion,
        "bottom_center_error": center_error,
        "root_deform_types": root_types,
        "exterior_offsets": EXTERIOR_OFFSETS,
        "max_continuation_error": maximum_continuation_error,
        "max_span_error": maximum_span_error,
        "max_step_error": maximum_step_error,
        "python_terminal_step_error": terminal_step_error,
        "max_tangent_angle_degrees": maximum_tangent_angle,
        "inside_to_terminal_angle_degrees": inside_terminal_angle,
        "max_cross_section_rigidity_error": maximum_rigidity_error,
        "max_gn_python_parity_error": maximum_parity_error,
        "max_change_after_second_stage_edit": maximum_upstream_change,
    }
    print(f"SDH_ROOT_BOUNDARY::CASE::{report!r}")
    return report


try:
    reports = tuple(run_case(origin) for origin in ORIGINS)
    print(f"SDH_ROOT_BOUNDARY::REPORT::{reports!r}")
    print("SDH_ROOT_BOUNDARY::PASS")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
