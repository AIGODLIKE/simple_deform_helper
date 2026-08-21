"""Keep direct cage previews point-for-point aligned with evaluated geometry."""
from __future__ import annotations

import importlib
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
INSTALLED_PACKAGE = os.environ.get("SDH_TEST_MODULE")
PACKAGE = INSTALLED_PACKAGE or SOURCE.name
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(SOURCE.parent))

TOLERANCE = 2.5e-4


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def make_target():
    vertices = []
    samples = []
    for y in (-4.0, 4.0):
        for x, z in ((-0.7, -0.5), (-0.7, 0.5), (0.7, -0.5), (0.7, 0.5)):
            vertices.append((x, y, z))
    for stage_index in range(4):
        center_y = -3.0 + stage_index * 2.0
        for y_offset in (-0.7, 0.0, 0.7):
            for x, z in (
                    (-0.7, -0.5), (-0.7, 0.5),
                    (0.7, -0.5), (0.7, 0.5)):
                samples.append((len(vertices), stage_index, Vector((
                    x, center_y + y_offset, z))))
                vertices.append(tuple(samples[-1][2]))
    mesh = bpy.data.meshes.new("SDH Preview Sync Mesh")
    mesh.from_pydata(vertices, (), ())
    target = bpy.data.objects.new("SDH Preview Evaluator Sync", mesh)
    bpy.context.collection.objects.link(target)
    activate(target)
    return target, tuple(samples)


def evaluated_points(target):
    bpy.context.view_layer.update()
    evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return tuple(vertex.co.copy() for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


addon = importlib.import_module(PACKAGE)
entry = None
if not INSTALLED_PACKAGE:
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")

target = None
try:
    target, samples = make_target()
    result = bpy.ops.sdh.add_cage_chain(
        count=4,
        cage_type="STANDARD",
        connection_mode="CHAINED",
        gap=0.0,
        auto_reconnect=True,
        sync_shared_end_scale=True,
        alignment="POS_Y",
        origin="BOTTOM",
    )
    check(result == {"FINISHED"}, "chain creation failed")
    stages = tuple(deform.chain.chain_stages(target))
    controllers = tuple(
        deform.find_controller(target, stage) for stage in stages)
    check(len(controllers) == 4 and all(controllers), "chain is incomplete")

    for controller, bend in zip(
            controllers, (math.radians(24.0), math.radians(-17.0),
                          math.radians(13.0), math.radians(-9.0))):
        properties = controller.sdh_cage_deform
        properties.bend_strength = bend
        properties.bend_direction = math.radians(18.0)
        deform.sync_controller(controller, pull_transform=False)
    controllers[0].sdh_cage_deform.bottom_scale = (0.82, 1.12)
    for controller, scale in zip(
            controllers,
            ((1.48, 0.72), (0.76, 1.34), (1.27, 0.83), (0.91, 1.18))):
        controller.sdh_cage_deform.top_scale = scale
    deform.core.flush_pending_chain_updates(target)

    actual = evaluated_points(target)
    maxima = [0.0, 0.0, 0.0, 0.0]
    for vertex_index, stage_index, source_point in samples:
        controller = controllers[stage_index]
        properties = controller.sdh_cage_deform
        cage_matrix = deform.cage_local_matrix(target, controller)
        source_local = Vector((
            source_point.x,
            source_point.y - (-3.0 + stage_index * 2.0),
            source_point.z,
        ))
        _signature, preview_output_frame = (
            deform.gizmos.cage_preview_geometry_state(properties))
        preview_local = deform.core.deform_point_for_display(
            source_local,
            properties,
            preview_output_frame=preview_output_frame,
        )
        expected = cage_matrix @ Vector(preview_local)
        maxima[stage_index] = max(
            maxima[stage_index],
            (actual[vertex_index] - expected).length,
        )
    check(
        max(maxima) <= TOLERANCE,
        f"cage preview diverged from evaluated geometry: {tuple(maxima)!r}",
    )
    print(
        "SDH_CHAIN_PREVIEW_EVALUATOR_SYNC::"
        f"{tuple(round(value, 8) for value in maxima)}::PASS")
finally:
    if target is not None:
        bpy.data.objects.remove(target, do_unlink=True)
    if entry is not None:
        addon.unregister()
        bpy.context.preferences.addons.remove(entry)
