"""Regression for root TOP resizing with a global profile chain.

The root controller can become longer than its downstream stages after a TOP
boundary drag.  Every stage's viewport preview must still use the live root
frame when the chain-global profile path is active.
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

BOUNDARIES = (-3.0, -1.0, 1.0, 3.0)
SECTION = (
    (0.0, 0.0),
    (-1.1, -0.9),
    (-1.1, 0.9),
    (1.1, 0.9),
    (1.1, -0.9),
    (1.1, 0.0),
)
CAGE_ROTATION = Euler((math.pi * 0.5, 0.0, 0.0), "XYZ").to_matrix()
VERTICES = tuple(
    tuple(CAGE_ROTATION @ Vector((x, y, z)))
    for y in BOUNDARIES
    for x, z in SECTION
)


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


addon = importlib.import_module(PACKAGE)
if not INSTALLED_PACKAGE:
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
chain = deform.chain

mesh = bpy.data.meshes.new("SDH Root TOP Profile Mesh")
mesh.from_pydata(VERTICES, (), ())
target = bpy.data.objects.new("SDH Root TOP Profile", mesh)
bpy.context.collection.objects.link(target)
activate(target)

try:
    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, target, show_other_default=True)
    properties = controller.sdh_cage_deform
    properties.size = (2.2, 6.0, 1.8)
    properties.mode = "LIMITED"
    properties.origin = "BOTTOM"
    properties.preserve_volume = True
    properties.bend_strength = math.radians(33.0)
    properties.bottom_offset = (-0.38, 0.24)
    properties.top_offset = (0.64, -0.31)
    controller.rotation_euler = (math.pi * 0.5, 0.0, 0.0)
    deform.core.set_deform_layers(properties, ("BEND",), bpy.context)
    deform.sync_controller(controller, pull_transform=False)
    target.modifiers.active = modifier
    result = bpy.ops.sdh.subdivide_cage_to_chain(
        count=3,
        gap=0.0,
        auto_reconnect=True,
        sync_shared_end_scale=True,
    )
    if result != {"FINISHED"}:
        raise AssertionError(f"subdivide returned {result!r}")
    deform.core.flush_pending_chain_updates(target)
    bpy.context.view_layer.update()

    stages = tuple(chain.chain_stages(target))
    controllers = tuple(deform.find_controller(target, stage) for stage in stages)
    if len(stages) != 3 or not all(controllers):
        raise AssertionError("expected a complete three-stage chain")
    root = controllers[0]
    root_properties = root.sdh_cage_deform
    root_initial_size = tuple(root_properties.size)
    root_initial_location = tuple(root.location)
    applied, _length = deform.move_cage_boundary(
        root, "TOP", 0.08, root_initial_size, root_initial_location, None)
    deform.core.flush_pending_chain_updates(target)
    bpy.context.view_layer.update()
    if abs(float(applied) - 0.08) > 1.0e-5:
        raise AssertionError(f"root TOP drag was clamped: {applied!r}")

    domain = deform.core._chain_domain_input_values(root, stages[0])
    if not bool(domain.get("Chain Global Profile Active", False)):
        raise AssertionError("root chain-global profile was not active")
    if abs(float(root_properties.size[1])) <= 2.0:
        raise AssertionError("root TOP drag did not create a non-uniform stage")

    half_y = abs(float(root_properties.size[1])) * 0.5
    source_start = float(domain.get("Chain Source Start", 0.0))
    samples = (
        Vector((0.0, half_y, 0.0)),
        Vector((-float(root_properties.size[0]) * 0.5, half_y, -float(root_properties.size[2]) * 0.5)),
        Vector((-float(root_properties.size[0]) * 0.5, half_y, float(root_properties.size[2]) * 0.5)),
        Vector((float(root_properties.size[0]) * 0.5, half_y, float(root_properties.size[2]) * 0.5)),
        Vector((float(root_properties.size[0]) * 0.5, half_y, -float(root_properties.size[2]) * 0.5)),
    )
    errors = []
    for sample in samples:
        source_coordinate = source_start + sample.y + half_y
        expected = deform.deform_point_from_properties(
            sample,
            root_properties,
            evaluator=True,
            chain_eligible=True,
            chain_source_coordinate=source_coordinate,
            chain_source_start=source_start,
        )
        displayed = deform.deform_point_for_display(sample, root_properties)
        errors.append((Vector(displayed) - Vector(expected)).length)

    maximum = max(errors, default=0.0)
    # Downstream controllers use the same root-frame source coordinate.  The
    # explicit cumulative preview is an independent reference path; a stale
    # global-prefix reconstruction separates the two as soon as the root
    # boundary changes the stage lengths.
    downstream_error = 0.0
    for stage_index, stage_controller in enumerate(controllers[1:], 1):
        stage_properties = stage_controller.sdh_cage_deform
        stage_half = abs(float(stage_properties.size[1])) * 0.5
        stage_half_x = abs(float(stage_properties.size[0])) * 0.5
        stage_half_z = abs(float(stage_properties.size[2])) * 0.5
        for y in (-stage_half, 0.0, stage_half):
            for x, z in (
                    (0.0, 0.0),
                    (-stage_half_x, -stage_half_z),
                    (stage_half_x, stage_half_z)):
                local = Vector((x, y, z))
                default = deform.deform_point_for_display(
                    local, stage_properties)
                cumulative = deform.deform_point_for_display(
                    local, stage_properties, chain_prefix_state=None)
                if default is None or cumulative is None:
                    raise AssertionError(
                        f"stage {stage_index} preview could not be evaluated")
                downstream_error = max(
                    downstream_error,
                    (Vector(default) - Vector(cumulative)).length,
                )
    report = {
        "applied_top_delta": float(applied),
        "root_size_y": float(root_properties.size[1]),
        "downstream_size_y": float(controllers[1].sdh_cage_deform.size[1]),
        "max_preview_evaluator_error": maximum,
        "max_downstream_preview_error": downstream_error,
    }
    print("SDH_CHAIN_ROOT_TOP_PROFILE::" + json.dumps(report))
    if maximum > 5.0e-4:
        raise AssertionError(
            f"root TOP preview drifted from evaluator by {maximum:.9g}")
    if downstream_error > 5.0e-4:
        raise AssertionError(
            "downstream preview drifted after root TOP resize: "
            f"{downstream_error:.9g}")
    print("SDH_CHAIN_ROOT_TOP_PROFILE::PASS")
finally:
    if target.name in bpy.data.objects:
        bpy.data.objects.remove(target, do_unlink=True)
    if mesh.name in bpy.data.meshes:
        bpy.data.meshes.remove(mesh)
    if not INSTALLED_PACKAGE:
        addon.unregister()
        bpy.context.preferences.addons.remove(entry)
