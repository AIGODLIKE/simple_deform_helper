"""Reproduce the reported first-cage TOP/Bend boundary interaction.

The recorded workflow uses a three-stage CHAINED cage, moves the root bottom
boundary upward, then changes its Bend angle from about 47 to -110 degrees.
Rings below the moved boundary must continue from the deformed bottom frame;
they must never fall back to the undeformed cylinder.

Set ``SDH_ADDON_ROOT`` to test an extracted release package instead of the
current source tree.
"""

from __future__ import annotations

import importlib
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(os.environ.get("SDH_ADDON_ROOT", SOURCE)).resolve()
PACKAGE = ADDON_ROOT.name
sys.path.insert(0, str(ADDON_ROOT.parent))

ENTRY_CASES = ("CREATE_CHAIN", "SUBDIVIDE", "MIGRATE_V19")
RING_STEP = 0.03
AXIS_MIN = -3.0
AXIS_MAX = 3.0
RING_COUNT = round((AXIS_MAX - AXIS_MIN) / RING_STEP) + 1
SIDE_COUNT = 16
RADIUS = 0.6
BOUNDARY_DELTA = 0.36
BEND_ANGLES = (47.0, -110.0)
MAX_PARITY_ERROR = 7.5e-4
MAX_CONTINUATION_ERROR = 2.0e-3
MIN_EXTERIOR_MOTION = 0.1


def cylinder_data():
    vertices = []
    faces = []
    for ring_index in range(RING_COUNT):
        y = AXIS_MIN + ring_index * RING_STEP
        for side in range(SIDE_COUNT):
            angle = math.tau * side / SIDE_COUNT
            vertices.append((
                RADIUS * math.cos(angle),
                y,
                RADIUS * math.sin(angle),
            ))
    for ring_index in range(RING_COUNT - 1):
        current = ring_index * SIDE_COUNT
        following = current + SIDE_COUNT
        for side in range(SIDE_COUNT):
            next_side = (side + 1) % SIDE_COUNT
            faces.append((
                current + side,
                current + next_side,
                following + next_side,
                following + side,
            ))
    return tuple(vertices), tuple(faces)


VERTICES, FACES = cylinder_data()


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


def ring_indices(ring_index):
    start = ring_index * SIDE_COUNT
    return tuple(range(start, start + SIDE_COUNT))


def create_target(entry_case):
    mesh = bpy.data.meshes.new(f"SDH Video Root TOP {entry_case} Mesh")
    mesh.from_pydata(VERTICES, (), FACES)
    target = bpy.data.objects.new(f"SDH Video Root TOP {entry_case}", mesh)
    bpy.context.collection.objects.link(target)
    activate(target)

    if entry_case in {"CREATE_CHAIN", "MIGRATE_V19"}:
        result = bpy.ops.sdh.add_cage_chain(
            count=3,
            connection_mode="CHAINED",
            gap=0.0,
            auto_reconnect=True,
            sync_shared_end_scale=True,
            alignment="POS_Y",
            origin="TOP",
        )
    else:
        modifier, controller, _previous = deform.create_deform_stage(
            bpy.context, target)
        deform.core.fit_controller_to_alignment(
            bpy.context, target, modifier, controller, "POS_Y")
        properties = controller.sdh_cage_deform
        properties.size = (1.2, AXIS_MAX - AXIS_MIN, 1.2)
        properties.origin = "TOP"
        properties.mode = "LIMITED"
        deform.core.set_deform_layers(properties, ("BEND",), bpy.context)
        properties.bend_strength = 0.0
        deform.sync_controller(controller, pull_transform=False)
        target.modifiers.active = modifier
        activate(target)
        result = bpy.ops.sdh.subdivide_cage_to_chain(
            count=3,
            gap=0.0,
            auto_reconnect=True,
            sync_shared_end_scale=True,
        )
    if result != {"FINISHED"}:
        raise AssertionError(f"{entry_case}: chain construction failed: {result!r}")
    return target


def configure_chain(target):
    stages = tuple(chain.chain_stages(target))
    controllers = tuple(deform.find_controller(target, stage) for stage in stages)
    if len(stages) != 3 or not all(controllers):
        raise AssertionError("expected one complete three-stage chain")

    for index, controller in enumerate(controllers):
        properties = controller.sdh_cage_deform
        deform.core.set_deform_layers(properties, ("BEND",), bpy.context)
        properties.origin = "TOP" if index == 0 else "BOTTOM"
        properties.mode = "LIMITED"
        properties.bend_strength = math.radians(47.0) if index == 0 else 0.0
        properties.bend_direction = 0.0
        properties.twist_strength = 0.0
        properties.taper_factor = 0.0
        properties.stretch_factor = 0.0
        deform.sync_controller(controller, pull_transform=False)
    deform.core.flush_pending_chain_updates(target)
    bpy.context.view_layer.update()
    return stages, controllers


def migrate_v19_groups(entry_case, stages):
    if entry_case != "MIGRATE_V19":
        return 0
    for stage in stages:
        stage.node_group[deform.GROUP_MARKER] = 19
    upgraded = deform.upgrade_managed_stages()
    if upgraded != len(stages):
        raise AssertionError(
            f"v19 migration rebuilt {upgraded} groups, expected {len(stages)}")
    markers = tuple(
        int(stage.node_group.get(deform.GROUP_MARKER, -1))
        for stage in stages)
    if markers != (deform.GROUP_VERSION,) * len(stages):
        raise AssertionError(f"v19 migration left stale markers: {markers!r}")
    deform.core.flush_pending_chain_updates(stages[0].id_data)
    bpy.context.view_layer.update()
    return upgraded


def move_root_bottom(target, root):
    properties = root.sdh_cage_deform
    initial_size = tuple(properties.size)
    initial_location = tuple(root.location)
    initial_matrix = chain._stage_local_matrix(target, root)
    initial_half_y = float(properties.size[1]) * 0.5
    initial_bottom = initial_matrix @ Vector((0.0, -initial_half_y, 0.0))
    initial_top = initial_matrix @ Vector((0.0, initial_half_y, 0.0))

    applied, _length = deform.move_cage_boundary(
        root,
        "BOTTOM",
        BOUNDARY_DELTA,
        initial_size,
        initial_location,
        None,
    )
    deform.core.flush_pending_chain_updates(target)
    bpy.context.view_layer.update()

    moved_matrix = chain._stage_local_matrix(target, root)
    moved_half_y = float(properties.size[1]) * 0.5
    moved_bottom = moved_matrix @ Vector((0.0, -moved_half_y, 0.0))
    moved_top = moved_matrix @ Vector((0.0, moved_half_y, 0.0))
    if abs(applied - BOUNDARY_DELTA) > 1.0e-5:
        raise AssertionError(f"root boundary drag was clamped: {applied!r}")
    if (moved_top - initial_top).length > 2.0e-5:
        raise AssertionError("moving the root bottom also moved its top")
    if abs((moved_bottom - initial_bottom).length - BOUNDARY_DELTA) > 2.0e-5:
        raise AssertionError("root bottom did not move by 0.36")
    return moved_bottom


def verify_angle(entry_case, target, stages, root, angle_degrees, moved_bottom):
    properties = root.sdh_cage_deform
    properties.bend_strength = math.radians(angle_degrees)
    deform.sync_controller(root, pull_transform=False)
    deform.core.flush_pending_chain_updates(target)
    bpy.context.view_layer.update()

    actual = evaluated_points(target)
    root_matrix = chain._stage_local_matrix(target, root)
    root_inverse = root_matrix.inverted_safe()
    boundary_ring_index = round((moved_bottom.y - AXIS_MIN) / RING_STEP)
    if abs(
            AXIS_MIN + boundary_ring_index * RING_STEP - moved_bottom.y
    ) > 2.0e-5:
        raise AssertionError("the video boundary does not coincide with a mesh ring")
    boundary_indices = ring_indices(boundary_ring_index)
    boundary_points = tuple(actual[index] for index in boundary_indices)
    boundary_center = average(boundary_points)

    exterior_indices = tuple(
        index
        for ring_index in range(boundary_ring_index)
        for index in ring_indices(ring_index)
    )
    parity_errors = []
    exterior_motion = []
    for index in exterior_indices:
        source = Vector(VERTICES[index])
        local = root_inverse @ source
        expected = root_matrix @ deform.deform_point_from_properties(
            local,
            properties,
            evaluator=True,
            chain_eligible=True,
        )
        parity_errors.append((actual[index] - expected).length)
        exterior_motion.append((actual[index] - source).length)

    endpoint, _x_axis, bottom_tangent, _z_axis = chain._stage_boundary_frame(
        target, root, "BOTTOM")
    endpoint_error = (boundary_center - Vector(endpoint)).length
    continuation_errors = []
    for ring_index in range(boundary_ring_index):
        y = AXIS_MIN + ring_index * RING_STEP
        offset = moved_bottom.y - y
        exterior_points = tuple(actual[index] for index in ring_indices(ring_index))
        expected_points = tuple(
            point - Vector(bottom_tangent) * offset for point in boundary_points)
        continuation_errors.extend(
            (point - expected).length
            for point, expected in zip(exterior_points, expected_points)
        )

    maximum_parity_error = max(parity_errors, default=0.0)
    maximum_continuation_error = max(continuation_errors, default=0.0)
    minimum_exterior_motion = min(exterior_motion, default=0.0)
    if maximum_parity_error > MAX_PARITY_ERROR:
        raise AssertionError(
            f"{entry_case}/{angle_degrees:g}: GN/Python mismatch "
            f"{maximum_parity_error:.9g}")
    if endpoint_error > MAX_CONTINUATION_ERROR:
        raise AssertionError(
            f"{entry_case}/{angle_degrees:g}: boundary missed bottom frame "
            f"{endpoint_error:.9g}")
    if maximum_continuation_error > MAX_CONTINUATION_ERROR:
        raise AssertionError(
            f"{entry_case}/{angle_degrees:g}: outside mesh did not continue "
            f"from bottom frame ({maximum_continuation_error:.9g})")
    if minimum_exterior_motion < MIN_EXTERIOR_MOTION:
        raise AssertionError(
            f"{entry_case}/{angle_degrees:g}: outside mesh returned to the "
            f"straight source ({minimum_exterior_motion:.9g})")

    report = {
        "entry": entry_case,
        "angle_degrees": angle_degrees,
        "root_origin": properties.origin,
        "root_deform_types": tuple(deform.core.ordered_deform_types(properties)),
        "moved_bottom": tuple(moved_bottom),
        "chain_source_starts": tuple(
            float(deform.modifier_input(stage, "Chain Source Start"))
            for stage in stages),
        "max_gn_python_error": maximum_parity_error,
        "bottom_endpoint_error": endpoint_error,
        "max_continuation_error": maximum_continuation_error,
        "min_exterior_motion": minimum_exterior_motion,
    }
    print(f"SDH_VIDEO_ROOT_TOP::CASE::{report!r}")
    return report


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
chain = deform.chain

try:
    reports = []
    for entry_case in ENTRY_CASES:
        target = create_target(entry_case)
        stages, controllers = configure_chain(target)
        migrate_v19_groups(entry_case, stages)
        moved_bottom = move_root_bottom(target, controllers[0])
        for angle_degrees in BEND_ANGLES:
            reports.append(verify_angle(
                entry_case,
                target,
                stages,
                controllers[0],
                angle_degrees,
                moved_bottom,
            ))
    print(f"SDH_VIDEO_ROOT_TOP::REPORT::{tuple(reports)!r}")
    print("SDH_VIDEO_ROOT_TOP::PASS")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
