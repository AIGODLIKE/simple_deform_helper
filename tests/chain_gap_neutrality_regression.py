"""Keep Standard chain gaps rigid while preserving the incoming end frame."""
from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path

import bpy
SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))

DEPTH = 6.0
RING_COUNT = 241
SIDE_COUNT = 4
STAGE_COUNT = 3
GAP = 0.6
TOLERANCE = 7.5e-4


def fail(message):
    raise AssertionError(message)


def activate(target):
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target


def make_target(name="SDH Chain Gap Neutrality"):
    corners = ((-0.5, -0.35), (-0.5, 0.35),
               (0.5, -0.35), (0.5, 0.35))
    vertices = []
    for ring in range(RING_COUNT):
        y = -DEPTH * 0.5 + DEPTH * ring / (RING_COUNT - 1)
        vertices.extend((x, y, z) for x, z in corners)
    mesh = bpy.data.meshes.new(f"{name} Mesh")
    mesh.from_pydata(vertices, (), ())
    target = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(target)
    activate(target)
    return target


def evaluated_points(target):
    bpy.context.view_layer.update()
    evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return tuple(vertex.co.copy() for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def ring_index(source_y):
    value = round((source_y + DEPTH * 0.5) / DEPTH * (RING_COUNT - 1))
    actual = -DEPTH * 0.5 + DEPTH * value / (RING_COUNT - 1)
    if abs(actual - source_y) > 1.0e-7:
        fail(f"test ring does not represent source coordinate {source_y}")
    return int(value)


def ring(points, source_y):
    start = ring_index(source_y) * SIDE_COUNT
    return points[start:start + SIDE_COUNT]


def gap_linearity(points, gap_start, gap_end):
    gap_length = gap_end - gap_start
    start = ring(points, gap_start)
    end = ring(points, gap_end)
    maximum = 0.0
    for fraction in (0.25, 0.5, 0.75):
        sample = ring(points, gap_start + gap_length * fraction)
        for actual, first, last in zip(sample, start, end):
            maximum = max(
                maximum, (actual - first.lerp(last, fraction)).length)
    return maximum


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")

targets = []
try:
    target = make_target()
    targets.append(target)
    result = bpy.ops.sdh.add_cage_chain(
        count=STAGE_COUNT,
        connection_mode="CHAINED",
        gap=GAP,
        auto_reconnect=True,
        sync_shared_end_scale=True,
        alignment="POS_Y",
        origin="BOTTOM",
    )
    if result != {"FINISHED"}:
        fail(f"chain creation failed: {result!r}")
    stages = tuple(deform.chain.chain_stages(target))
    controllers = tuple(
        deform.find_controller(target, stage) for stage in stages)
    if len(controllers) != STAGE_COUNT or not all(controllers):
        fail("chain is incomplete")

    for controller in controllers:
        properties = controller.sdh_cage_deform
        deform.core.set_deform_layers(properties, ("BEND",), bpy.context)
        properties.bend_strength = 0.0
        properties.bend_direction = 0.0
        properties.top_scale = (1.0, 1.0)
        properties.bottom_scale = (1.0, 1.0)
        deform.sync_controller(controller, pull_transform=False)
    controllers[0].sdh_cage_deform.bend_strength = math.radians(80.0)
    deform.sync_controller(controllers[0], pull_transform=False)
    deform.core.flush_pending_chain_updates(target)

    root = controllers[0]
    root_domain = deform.core._chain_domain_input_values(root, stages[0])
    gap_start = (
        float(root_domain["Chain Source Start"]) +
        abs(float(root.sdh_cage_deform.size[1])))
    gap_end = float(root_domain["Chain Source End"])
    if abs((gap_end - gap_start) - GAP) > 1.0e-6:
        fail(f"unexpected authored gap: {gap_start} -> {gap_end}")

    maximum = gap_linearity(evaluated_points(target), gap_start, gap_end)
    if maximum > TOLERANCE:
        fail(f"chain gap accumulated deformation: {maximum}")

    root_properties = root.sdh_cage_deform
    deform.core.set_deform_layers(
        root_properties,
        ("TWIST", "BEND", "STRETCH", "TAPER", "SHEAR"),
        bpy.context,
    )
    root_properties.twist_strength = math.radians(55.0)
    root_properties.bend_strength = math.radians(80.0)
    root_properties.stretch_factor = 0.35
    root_properties.taper_factor = 0.3
    root_properties.shear_factors = (0.18, -0.12)
    root_properties.top_scale = (1.3, 0.8)
    deform.sync_controller(root, pull_transform=False)
    deform.core.flush_pending_chain_updates(target)
    mixed_error = gap_linearity(
        evaluated_points(target), gap_start, gap_end)
    if mixed_error > TOLERANCE:
        fail(f"mixed Standard stack deformed its chain gap: {mixed_error}")

    top_frame = deform.chain._stage_boundary_frame(target, root, "TOP")
    extended = deform.chain._stage_top_frame(target, root, extension=GAP)
    frame_errors = [
        (extended[0] - (top_frame[0] + top_frame[2] * GAP)).length]
    frame_errors.extend(
        (extended[index] - top_frame[index]).length
        for index in range(1, 4))
    frame_error = max(frame_errors)
    if frame_error > 1.0e-6:
        fail(f"reconnected gap frame changed orientation: {frame_error}")

    subdivided = make_target("SDH Subdivided Gap Neutrality")
    targets.append(subdivided)
    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, subdivided)
    deform.core.fit_controller_to_alignment(
        bpy.context, subdivided, modifier, controller, "POS_Y")
    properties = controller.sdh_cage_deform
    properties.origin = "BOTTOM"
    deform.core.set_deform_layers(
        properties, ("TWIST", "BEND", "STRETCH", "TAPER"), bpy.context)
    properties.twist_strength = math.radians(55.0)
    properties.bend_strength = math.radians(80.0)
    properties.stretch_factor = 0.35
    properties.taper_factor = 0.3
    deform.sync_controller(controller, pull_transform=False)
    subdivided.modifiers.active = modifier
    activate(subdivided)
    result = bpy.ops.sdh.subdivide_cage_to_chain(
        count=STAGE_COUNT,
        gap=GAP,
        auto_reconnect=True,
        sync_shared_end_scale=True,
        allow_mixed_bend_approximation=True,
    )
    if result != {"FINISHED"}:
        fail(f"gapped subdivision failed: {result!r}")
    subdivided_stages = tuple(deform.chain.chain_stages(subdivided))
    subdivided_controllers = tuple(
        deform.find_controller(subdivided, stage)
        for stage in subdivided_stages)
    if len(subdivided_controllers) != STAGE_COUNT or not all(
            subdivided_controllers):
        fail("gapped subdivision produced an incomplete chain")
    deform.core.flush_pending_chain_updates(subdivided)
    subdivided_root = subdivided_controllers[0]
    subdivided_domain = deform.core._chain_domain_input_values(
        subdivided_root, subdivided_stages[0])
    subdivided_gap_start = (
        float(subdivided_domain["Chain Source Start"]) +
        abs(float(subdivided_root.sdh_cage_deform.size[1])))
    subdivided_gap_end = float(subdivided_domain["Chain Source End"])
    subdivided_error = gap_linearity(
        evaluated_points(subdivided),
        subdivided_gap_start,
        subdivided_gap_end,
    )
    if subdivided_error > TOLERANCE:
        fail(
            "subdivided mixed Standard stack deformed its chain gap: "
            f"{subdivided_error}")

    print(
        "SDH_CHAIN_GAP_NEUTRALITY::"
        f"BEND_ERROR={maximum:.9f}::MIXED_ERROR={mixed_error:.9f}::"
        f"SUBDIVIDED_ERROR={subdivided_error:.9f}::"
        f"FRAME_ERROR={frame_error:.9f}::PASS")
finally:
    for target in targets:
        if target.name not in bpy.data.objects:
            continue
        mesh = target.data
        bpy.data.objects.remove(target, do_unlink=True)
        if mesh is not None and mesh.name in bpy.data.meshes:
            bpy.data.meshes.remove(mesh)
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
