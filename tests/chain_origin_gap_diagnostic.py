"""Measure chained-cage continuity for non-zero gaps and Origin modes.

Run with:
    blender --background --factory-startup --python-exit-code 1 \
        --python tests/chain_origin_gap_diagnostic.py -- output.json
"""

from __future__ import annotations

import importlib
import json
import math
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
OUTPUT = (
    Path(sys.argv[sys.argv.index("--") + 1]).resolve()
    if "--" in sys.argv and len(sys.argv) > sys.argv.index("--") + 1
    else SOURCE / "outputs" / "chain_origin_gap_diagnostic_2.1.6.json"
)
RING_COUNT = 241
SIDE_COUNT = 32
DEPTH = 6.0
RADIUS = 0.65
GAPS = (0.0, 0.4)
STAGE_COUNT = 3
ORIGINS = ("BOTTOM", "TOP", "CENTER", "SYMMETRIC")


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def make_cylinder(name):
    vertices = []
    faces = []
    for ring in range(RING_COUNT):
        z = -DEPTH * 0.5 + DEPTH * ring / (RING_COUNT - 1)
        for side in range(SIDE_COUNT):
            angle = math.tau * side / SIDE_COUNT
            vertices.append((
                RADIUS * math.cos(angle),
                RADIUS * math.sin(angle),
                z,
            ))
    for ring in range(RING_COUNT - 1):
        lower = ring * SIDE_COUNT
        upper = (ring + 1) * SIDE_COUNT
        for side in range(SIDE_COUNT):
            next_side = (side + 1) % SIDE_COUNT
            faces.append((
                lower + side,
                lower + next_side,
                upper + next_side,
                upper + side,
            ))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, (), faces)
    mesh.update()
    target = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(target)
    activate(target)
    return target, tuple(Vector(point) for point in vertices)


def evaluated_points(target):
    bpy.context.view_layer.update()
    evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        if len(mesh.vertices) != RING_COUNT * SIDE_COUNT:
            raise AssertionError(
                f"topology changed from {RING_COUNT * SIDE_COUNT} "
                f"to {len(mesh.vertices)} vertices")
        return tuple(vertex.co.copy() for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def ring_points(points, index):
    start = index * SIDE_COUNT
    return points[start:start + SIDE_COUNT]


def ring_z(index):
    return -DEPTH * 0.5 + DEPTH * index / (RING_COUNT - 1)


def extrapolate(first, second, first_z, second_z, boundary_z):
    factor = (boundary_z - first_z) / (second_z - first_z)
    return first.lerp(second, factor)


def median(values):
    ordered = sorted(float(value) for value in values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) * 0.5


def boundary_diagnostic(source, evaluated, boundary_z):
    interval = min(max(
        int(math.floor(
            (boundary_z + DEPTH * 0.5) / DEPTH * (RING_COUNT - 1))),
        1,
    ), RING_COUNT - 3)
    lower_pair = (interval - 1, interval)
    upper_pair = (interval + 1, interval + 2)
    lower_ring = ring_points(evaluated, interval)
    upper_ring = ring_points(evaluated, interval + 1)

    c0_jumps = []
    crossing_edges = []
    for side in range(SIDE_COUNT):
        source_lower = ring_points(source, lower_pair[0])[side]
        source_lower_near = ring_points(source, lower_pair[1])[side]
        source_upper_near = ring_points(source, upper_pair[0])[side]
        source_upper = ring_points(source, upper_pair[1])[side]
        evaluated_lower = ring_points(evaluated, lower_pair[0])[side]
        evaluated_lower_near = ring_points(evaluated, lower_pair[1])[side]
        evaluated_upper_near = ring_points(evaluated, upper_pair[0])[side]
        evaluated_upper = ring_points(evaluated, upper_pair[1])[side]

        displacement_lower = evaluated_lower - source_lower
        displacement_lower_near = evaluated_lower_near - source_lower_near
        displacement_upper_near = evaluated_upper_near - source_upper_near
        displacement_upper = evaluated_upper - source_upper
        left = extrapolate(
            displacement_lower,
            displacement_lower_near,
            ring_z(lower_pair[0]),
            ring_z(lower_pair[1]),
            boundary_z,
        )
        right = extrapolate(
            displacement_upper_near,
            displacement_upper,
            ring_z(upper_pair[0]),
            ring_z(upper_pair[1]),
            boundary_z,
        )
        c0_jumps.append((right - left).length)
        crossing_edges.append((upper_ring[side] - lower_ring[side]).length)

    neighbor_edges = [[] for _side in range(SIDE_COUNT)]
    for edge_index in (
            interval - 2, interval - 1, interval + 1, interval + 2):
        first = ring_points(evaluated, edge_index)
        second = ring_points(evaluated, edge_index + 1)
        for side in range(SIDE_COUNT):
            neighbor_edges[side].append(
                (second[side] - first[side]).length)
    side_baselines = tuple(median(values) for values in neighbor_edges)
    spike_ratios = tuple(
        crossing_edges[side] / side_baselines[side]
        for side in range(SIDE_COUNT)
    )
    baseline = median(side_baselines)
    crossing_mean = sum(crossing_edges) / len(crossing_edges)
    return {
        "boundary_z": round(boundary_z, 7),
        "source_interval": (interval, interval + 1),
        "source_interval_z": (round(ring_z(interval), 7),
                              round(ring_z(interval + 1), 7)),
        "c0_displacement_jump_mean": sum(c0_jumps) / len(c0_jumps),
        "c0_displacement_jump_max": max(c0_jumps),
        "crossing_edge_mean": crossing_mean,
        "crossing_edge_max": max(crossing_edges),
        "neighbor_edge_median": baseline,
        "edge_spike_ratio_mean": sum(spike_ratios) / len(spike_ratios),
        "edge_spike_ratio_max": max(spike_ratios),
    }


def vector_tuple(value):
    return tuple(round(float(component), 9) for component in value)


def ring_centroid(points, index):
    result = Vector((0.0, 0.0, 0.0))
    for point in ring_points(points, index):
        result += point
    return result / SIDE_COUNT


def run_case(deform, origin, gap):
    target, source = make_cylinder(
        f"SDH Gap Diagnostic {origin} {gap:.1f}")
    result = bpy.ops.sdh.add_cage_chain(
        count=STAGE_COUNT,
        connection_mode="CHAINED",
        gap=gap,
        auto_reconnect=True,
        sync_shared_end_scale=True,
        alignment="POS_Z",
        origin=origin,
    )
    if result != {"FINISHED"}:
        raise AssertionError(f"chain creation failed for {origin}")
    stages = deform.chain.chain_stages(target)
    controllers = tuple(deform.find_controller(target, stage)
                        for stage in stages)
    if len(controllers) != STAGE_COUNT or not all(controllers):
        raise AssertionError(f"incomplete chain for {origin}")
    root = controllers[0]
    root_properties = root.sdh_cage_deform
    root_matrix = deform.chain._stage_local_matrix(target, root)
    root_inverse = root_matrix.inverted_safe()
    root_half_y = float(root_properties.size[1]) * 0.5
    usable_length = DEPTH - gap * (STAGE_COUNT - 1)
    segment_length = usable_length / STAGE_COUNT
    stage_bottoms = tuple(
        -DEPTH * 0.5 + index * (segment_length + gap)
        for index in range(STAGE_COUNT)
    )
    stage_tops = tuple(bottom + segment_length for bottom in stage_bottoms)
    source_bottom_center = Vector((0.0, 0.0, -DEPTH * 0.5))
    source_root_top_center = Vector((0.0, 0.0, stage_tops[0]))
    root_source_bottom_local = root_inverse @ source_bottom_center
    root_source_top_local = root_inverse @ source_root_top_center
    root_authored_bottom = root_matrix @ Vector((0.0, -root_half_y, 0.0))
    root_deformed_bottom, *_root_frame = deform.chain._stage_boundary_frame(
        target, root, "BOTTOM")
    root_initial = {
        "requested_origin": origin,
        "controller_origin": str(root_properties.origin),
        "controller_location": vector_tuple(root.location),
        "controller_rotation": vector_tuple(root.rotation_euler),
        "controller_size": vector_tuple(root_properties.size),
        "source_bottom_local": vector_tuple(root_source_bottom_local),
        "source_root_top_local": vector_tuple(root_source_top_local),
        "lower_axis_coverage_error": (
            root_source_bottom_local.y + root_half_y),
        "upper_axis_coverage_error": (
            root_source_top_local.y - root_half_y),
        "authored_bottom": vector_tuple(root_authored_bottom),
        "authored_bottom_source_error": (
            root_authored_bottom - source_bottom_center).length,
        "deformed_bottom": vector_tuple(root_deformed_bottom),
    }
    for controller in controllers:
        properties = controller.sdh_cage_deform
        deform.core.set_deform_layers(properties, ("BEND",), bpy.context)
        if properties.origin != origin:
            raise AssertionError(
                f"create-time Origin changed for {controller.name}: "
                f"{properties.origin} != {origin}")
        properties.bend_strength = math.radians(45.0)
        properties.bend_direction = 0.0
        properties.twist_strength = 0.0
        properties.taper_factor = 0.0
        properties.stretch_factor = 0.0
        properties.bottom_scale = (1.0, 1.0)
        properties.top_scale = (1.0, 1.0)
        properties.bottom_offset = (0.0, 0.0)
        properties.top_offset = (0.0, 0.0)
        deform.sync_controller(controller, pull_transform=False)
    deform.core.flush_pending_chain_updates(target)
    evaluated = evaluated_points(target)
    root_initial["model_bottom_centroid"] = vector_tuple(
        ring_centroid(evaluated, 0))
    root_initial["deformed_bottom_model_error"] = (
        ring_centroid(evaluated, 0) - Vector(root_deformed_bottom)).length
    boundaries = {
        "stage_1_top": stage_tops[0],
        "stage_2_bottom": stage_bottoms[1],
        "stage_2_top": stage_tops[1],
        "stage_3_bottom": stage_bottoms[2],
    }
    diagnostics = {
        name: boundary_diagnostic(source, evaluated, value)
        for name, value in boundaries.items()
    }
    interior = tuple(diagnostics.values())
    return target, {
        "origin": origin,
        "ring_count": RING_COUNT,
        "side_count": SIDE_COUNT,
        "vertex_count": RING_COUNT * SIDE_COUNT,
        "face_count": (RING_COUNT - 1) * SIDE_COUNT,
        "axis_step": DEPTH / (RING_COUNT - 1),
        "gap": gap,
        "segment_length": segment_length,
        "root_initial": root_initial,
        "boundaries": diagnostics,
        "worst_c0_displacement_jump": max(
            item["c0_displacement_jump_max"] for item in interior),
        "worst_edge_spike_ratio": max(
            item["edge_spike_ratio_max"] for item in interior),
    }


def main():
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon = importlib.import_module(PACKAGE)
    addon.register()
    deform = importlib.import_module(f"{PACKAGE}.cage_deform")
    results = {}
    for origin in ORIGINS:
        results[origin] = {}
        for gap in GAPS:
            target, result = run_case(deform, origin, gap)
            results[origin][f"{gap:.1f}"] = result
            print(
                "SDH_GAP_DIAGNOSTIC::"
                f"{origin}::GAP={gap:.1f}::"
                f"C0={result['worst_c0_displacement_jump']:.9f}::"
                f"EDGE={result['worst_edge_spike_ratio']:.6f}::"
                "ROOT_LOWER="
                f"{result['root_initial']['lower_axis_coverage_error']:.9f}"
            )
            bpy.data.objects.remove(target, do_unlink=True)
    payload = {
        "blender_version": bpy.app.version_string,
        "conditions": {
            "axis": "POS_Z",
            "origins": ORIGINS,
            "gaps": GAPS,
            "stage_count": STAGE_COUNT,
            "bend_degrees_per_stage": 45.0,
            "enabled_deformations": ("BEND",),
            "depth": DEPTH,
            "radius": RADIUS,
            "ring_count": RING_COUNT,
            "side_count": SIDE_COUNT,
        },
        "results": results,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"SDH_GAP_DIAGNOSTIC::OUTPUT::{OUTPUT}")


try:
    sys.path.insert(0, str(SOURCE.parent))
    main()
except Exception:
    traceback.print_exc()
    raise
