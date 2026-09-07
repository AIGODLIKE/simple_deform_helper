"""Shared prefix edits must synchronize the complete evaluated chain at once.

Run with Blender --background --factory-startup --python-exit-code 1 --python
tests/chain_prefix_parameter_sync_regression.py.
"""

from __future__ import annotations

import importlib
import json
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Euler, Vector


SOURCE = Path(__file__).resolve().parents[1]
INSTALLED_PACKAGE = os.environ.get("SDH_TEST_MODULE")
PACKAGE = INSTALLED_PACKAGE or SOURCE.name
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(SOURCE.parent))

SECTION = (
    (0.0, 0.0), (-1.1, -0.9), (-1.1, 0.9),
    (1.1, 0.9), (1.1, -0.9), (1.1, 0.0),
)
CAGE_ROTATION = Euler((math.pi * 0.5, 0.0, 0.0), "XYZ").to_matrix()
VERTICES = tuple(
    tuple(CAGE_ROTATION @ Vector((x, -3.0 + index * 0.5, z)))
    for index in range(13)
    for x, z in SECTION
)
SYNC_TOLERANCE = 5.0e-5
RESTORE_TOLERANCE = 1.0e-4
PREVIEW_TOLERANCE = 4.0e-3
PREFIX = "SDH_CHAIN_PREFIX_PARAMETER_SYNC::"


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


def max_motion(before, after):
    if len(before) != len(after):
        raise AssertionError("prefix edit changed the vertex count")
    return max((a - b).length for a, b in zip(before, after))


def transforms(controllers):
    return tuple(
        tuple(float(value) for row in controller.matrix_basis for value in row)
        for controller in controllers
    )


def transform_error(before, after):
    return max(
        abs(a - b)
        for old_matrix, new_matrix in zip(before, after)
        for a, b in zip(old_matrix, new_matrix)
    )


def full_sync(deform, target, controllers):
    for controller in controllers:
        deform.sync_controller(controller, pull_transform=False)
    deform.core.flush_pending_chain_updates(target)
    return evaluated_points(target)


def preview_error(deform, target, controllers, points):
    error = 0.0
    for index, controller in enumerate(controllers):
        properties = controller.sdh_cage_deform
        matrix = deform.chain._stage_local_matrix(target, controller)
        wire = deform.gizmos.cage_preview_wire_vertices(
            properties, steps=8, ring_positions=(0.0, 1.0))
        for rail, section in enumerate(range(1, 5)):
            for offset, boundary in ((0, index), (15, index + 1)):
                displayed = matrix @ Vector(wire[rail * 16 + offset])
                expected = points[boundary * 4 * len(SECTION) + section]
                error = max(error, (displayed - expected).length)
        for operation in ("TWIST", "BEND"):
            displayed = deform.gizmos.parameter_handle_world(
                bpy.context, target, controller, operation, separate=False)
            displayed = target.matrix_world.inverted_safe() @ displayed
            expected = points[(index + 1) * 4 * len(SECTION)]
            error = max(error, (displayed - expected).length)
    return error


def create_fixture(deform, auto_reconnect):
    mesh = bpy.data.meshes.new("Prefix Sync Mesh")
    mesh.from_pydata(VERTICES, (), ())
    target = bpy.data.objects.new("Prefix Sync Target", mesh)
    bpy.context.collection.objects.link(target)
    activate(target)
    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, target, show_other_default=True)
    properties = controller.sdh_cage_deform
    properties.size = (2.2, 6.0, 1.8)
    properties.mode = "LIMITED"
    properties.origin = "BOTTOM"
    properties.alignment = "POS_Z"
    properties.preserve_volume = True
    properties.bend_strength = math.radians(74.0)
    properties.bend_direction = math.radians(23.0)
    properties.twist_strength = -3.2320472
    controller.location = (0.0, 0.0, 0.0)
    controller.rotation_euler = (math.pi * 0.5, 0.0, 0.0)
    if not deform.core.set_deform_layers(
            properties, ("TWIST", "BEND"), bpy.context):
        raise AssertionError("could not create Twist -> Bend stack")
    deform.sync_controller(controller, pull_transform=False)
    bpy.context.view_layer.update()
    target.modifiers.active = modifier
    result = bpy.ops.sdh.subdivide_cage_to_chain(
        count=3, gap=0.0, auto_reconnect=True, sync_shared_end_scale=True)
    if result != {"FINISHED"}:
        raise AssertionError(f"subdivide returned {result!r}")
    deform.core.flush_pending_chain_updates(target)
    stages = tuple(deform.chain.chain_stages(target))
    controllers = tuple(deform.find_controller(target, stage) for stage in stages)
    if len(stages) != 3 or not all(controllers):
        raise AssertionError("subdivision did not create three complete stages")
    chain_uuid = deform.chain.stage_chain_uuid(stages[0])
    for controller, strength, direction in zip(
            controllers, (0.6531525, 1.3663300, 2.2693651), (23.0, -38.0, 71.0)):
        controller.sdh_cage_deform.bend_strength = strength
        controller.sdh_cage_deform.bend_direction = math.radians(direction)
    deform.core.flush_pending_chain_updates(target)
    full_sync(deform, target, controllers)
    stable = full_sync(deform, target, controllers)
    settled = full_sync(deform, target, controllers)
    if max_motion(stable, settled) > SYNC_TOLERANCE:
        raise AssertionError("fixture did not converge before prefix editing")
    deform.chain.set_chain_auto_reconnect(target, chain_uuid, auto_reconnect)
    for stage, controller in zip(stages, controllers):
        domain = deform.core._chain_domain_input_values(controller, stage)
        if not domain.get("Chain Global Prefix Active"):
            raise AssertionError("fixture has no active global prefix")
        mask = int(domain.get("Chain Global Prefix Types", 0))
        if not mask & deform.core.DEFORM_BITS["TWIST"]:
            raise AssertionError("fixture has no global Twist prefix")
    return target, stages, controllers, chain_uuid


def exercise(deform, target, stages, controllers, chain_uuid, index,
             interactive, auto_reconnect):
    properties = controllers[index].sdh_cage_deform
    original_value = float(properties.twist_strength)
    original_values = tuple(
        float(c.sdh_cage_deform.twist_strength) for c in controllers)
    original_points = evaluated_points(target)
    original_transforms = transforms(controllers)
    previous = original_points
    metrics = {
        "stage": index, "interactive": interactive,
        "auto_reconnect": auto_reconnect, "minimum_immediate_motion": math.inf,
        "additional_sync_motion": 0.0, "preview_error": 0.0,
        "transform_error": 0.0,
    }
    if interactive and not deform.core.begin_chain_interaction(target, chain_uuid):
        raise AssertionError("could not begin chain interaction")
    try:
        for delta in (0.25, -0.45, 0.5):
            properties.twist_strength = original_value + delta
            immediate = evaluated_points(target)
            motion = max_motion(previous, immediate)
            metrics["minimum_immediate_motion"] = min(
                metrics["minimum_immediate_motion"], motion)
            if motion < 1.0e-3:
                raise AssertionError(f"prefix edit did not update mesh: {metrics}")
            if auto_reconnect:
                error = preview_error(deform, target, controllers, immediate)
                metrics["preview_error"] = max(metrics["preview_error"], error)
                if error > PREVIEW_TOLERANCE:
                    raise AssertionError(f"prefix preview differs from mesh: {metrics}")
            after_sync = full_sync(deform, target, controllers)
            error = max_motion(immediate, after_sync)
            metrics["additional_sync_motion"] = max(
                metrics["additional_sync_motion"], error)
            if error > SYNC_TOLERANCE:
                raise AssertionError(f"prefix edit left stale chain frames: {metrics}")
            if not auto_reconnect:
                error = transform_error(original_transforms, transforms(controllers))
                metrics["transform_error"] = max(metrics["transform_error"], error)
                if error > 1.0e-7:
                    raise AssertionError(f"disabled reconnect moved controllers: {metrics}")
            for stage in stages:
                if abs(float(deform.modifier_input(stage, "Twist Angle"))) > 1.0e-5:
                    raise AssertionError("prefix edit retained a local Twist residue")
            previous = immediate
        # The parameter Gizmo restores its invoke-time value through RNA on Esc.
        properties.twist_strength = original_value
        restored = evaluated_points(target)
        metrics["restoration_error"] = max_motion(original_points, restored)
        if metrics["restoration_error"] > RESTORE_TOLERANCE:
            raise AssertionError(f"prefix cancellation failed to restore mesh: {metrics}")
        values = tuple(float(c.sdh_cage_deform.twist_strength) for c in controllers)
        if max(abs(a - b) for a, b in zip(original_values, values)) > 1.0e-6:
            raise AssertionError("prefix cancellation failed to restore shared values")
    finally:
        if interactive:
            deform.core.end_chain_interaction(target, chain_uuid)
    if deform.core.chain_interaction_active(target, chain_uuid):
        raise AssertionError("prefix interaction marker survived completion")
    after_exit = full_sync(deform, target, controllers)
    metrics["exit_sync_motion"] = max_motion(restored, after_exit)
    if metrics["exit_sync_motion"] > SYNC_TOLERANCE:
        raise AssertionError(f"prefix exit changed restored geometry: {metrics}")
    if not auto_reconnect and transform_error(
            original_transforms, transforms(controllers)) > 1.0e-7:
        raise AssertionError("disabled reconnect moved controllers on cancellation")
    print(PREFIX + json.dumps(metrics))
    return metrics


addon = importlib.import_module(PACKAGE)
entry = None
try:
    if not INSTALLED_PACKAGE:
        entry = bpy.context.preferences.addons.new()
        entry.module = PACKAGE
        addon.register()
    deform = importlib.import_module(f"{PACKAGE}.cage_deform")
    results = []
    for auto_reconnect in (True, False):
        fixture = create_fixture(deform, auto_reconnect)
        for interactive in (False, True):
            for index in range(3):
                results.append(exercise(
                    deform, *fixture, index, interactive, auto_reconnect))
    print(PREFIX + json.dumps({"cases": len(results), "edits": len(results) * 3}))
finally:
    if not INSTALLED_PACKAGE and entry is not None:
        addon.unregister()
        bpy.context.preferences.addons.remove(entry)

print(PREFIX + "PASS")
