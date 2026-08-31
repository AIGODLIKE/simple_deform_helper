"""Replay the supplied ``bug.blend`` root TOP boundary case.

This fixture was saved with the previous node-group schema.  The test opens it
under a factory Blender startup, registers the checkout under test, upgrades
the managed groups, and then performs the same root TOP boundary edit.  It
checks the preview path against the evaluator for every chain stage without
writing the source blend file.  Set ``SDH_ADDON_ROOT`` to an extracted add-on
directory to compare another build; the default is this checkout.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(os.environ.get("SDH_ADDON_ROOT", SOURCE)).resolve()
BLEND = Path(os.environ["SDH_BUG_BLEND"]).resolve() if os.environ.get(
    "SDH_BUG_BLEND") else SOURCE / "tests" / "fixtures" / "bug.blend"
PACKAGE = ADDON_ROOT.name
sys.path.insert(0, str(ADDON_ROOT.parent))


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


if not BLEND.is_file():
    print(f"SDH_BUG_BLEND_ROOT_TOP::SKIP fixture not found: {BLEND}")
    raise SystemExit(0)

bpy.ops.wm.open_mainfile(filepath=str(BLEND))
addon = importlib.import_module(PACKAGE)
entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
chain = deform.chain

target = bpy.data.objects.get("Cylinder")
if target is None or target.type != "MESH":
    raise AssertionError("bug.blend does not contain the Cylinder target")
activate(target)

try:
    upgraded = deform.upgrade_managed_stages()
    deform.core.flush_pending_chain_updates(target)
    bpy.context.view_layer.update()
    stages = tuple(chain.chain_stages(target))
    controllers = tuple(deform.find_controller(target, stage)
                        for stage in stages)
    if len(stages) != 3 or not all(controllers):
        raise AssertionError("fixture chain is incomplete")
    markers = tuple(int(stage.node_group.get(deform.GROUP_MARKER, -1))
                    for stage in stages)
    if markers != (deform.GROUP_VERSION,) * len(stages):
        raise AssertionError(f"managed groups were not upgraded: {markers!r}")

    root = controllers[0]
    root_properties = root.sdh_cage_deform
    initial_size = tuple(root_properties.size)
    initial_location = tuple(root.location)
    initial_matrix = chain._stage_local_matrix(target, root)
    initial_half = abs(float(root_properties.size[1])) * 0.5
    initial_bottom = initial_matrix @ Vector((0.0, -initial_half, 0.0))
    initial_top = initial_matrix @ Vector((0.0, initial_half, 0.0))
    applied, _new_length = deform.move_cage_boundary(
        root, "TOP", 0.08, initial_size, initial_location, None)
    deform.core.flush_pending_chain_updates(target)
    bpy.context.view_layer.update()
    if abs(float(applied) - 0.08) > 1.0e-5:
        raise AssertionError(f"root TOP drag was clamped: {applied!r}")
    moved_matrix = chain._stage_local_matrix(target, root)
    moved_half = abs(float(root_properties.size[1])) * 0.5
    moved_bottom = moved_matrix @ Vector((0.0, -moved_half, 0.0))
    moved_top = moved_matrix @ Vector((0.0, moved_half, 0.0))
    bottom_motion = (moved_bottom - initial_bottom).length
    top_motion = (moved_top - initial_top).length
    if bottom_motion > 5.0e-5 or abs(top_motion - 0.08) > 5.0e-5:
        raise AssertionError(
            f"root endpoints moved unexpectedly: bottom={bottom_motion}, "
            f"top={top_motion}")

    evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    evaluated_mesh = evaluated.to_mesh()
    try:
        evaluated_points = tuple(vertex.co.copy()
                                 for vertex in evaluated_mesh.vertices)
    finally:
        evaluated.to_mesh_clear()
    raw_points = tuple(vertex.co.copy() for vertex in target.data.vertices)
    mesh_preview_error = 0.0
    mesh_preview_count = 0
    stage_errors = [0.0] * len(stages)
    root_matrix = chain._stage_local_matrix(target, controllers[0])
    root_inverse = root_matrix.inverted_safe()
    root_half = max(abs(float(controllers[0].sdh_cage_deform.size[1])) * 0.5,
                    1.0e-8)
    domains = tuple(deform.core._chain_domain_input_values(c, s)
                    for c, s in zip(controllers, stages))
    for raw, evaluated_point in zip(raw_points, evaluated_points):
        source_local = root_inverse @ raw
        source_coordinate = (
            float(domains[0].get("Chain Source Start", 0.0)) +
            float(source_local.y) + root_half)
        owner = None
        for index, domain in enumerate(domains):
            start = float(domain.get("Chain Source Start", 0.0))
            end = float(domain.get("Chain Source End", 1.0e20))
            if (
                    source_coordinate >= start - 1.0e-5 and
                    source_coordinate <= end + 1.0e-5
            ):
                owner = index
                break
        if owner is None:
            continue
        owner_properties = controllers[owner].sdh_cage_deform
        owner_half = max(abs(float(owner_properties.size[1])) * 0.5, 1.0e-8)
        local = Vector((
            float(source_local.x),
            source_coordinate - float(domains[owner].get(
                "Chain Source Start", 0.0)) - owner_half,
            float(source_local.z),
        ))
        displayed = Vector(deform.deform_point_for_display(
            local, owner_properties))
        displayed_target = (
            chain._stage_local_matrix(target, controllers[owner]) @ displayed)
        error = (displayed_target - evaluated_point).length
        mesh_preview_error = max(mesh_preview_error, error)
        stage_errors[owner] = max(stage_errors[owner], error)
        mesh_preview_count += 1
    if mesh_preview_count != len(raw_points):
        raise AssertionError(
            f"only mapped {mesh_preview_count}/{len(raw_points)} source points")

    report = {
        "upgraded_groups": int(upgraded),
        "group_version": int(deform.GROUP_VERSION),
        "applied_top_delta": float(applied),
        "root_size_y": float(root_properties.size[1]),
        "bottom_motion": float(bottom_motion),
        "top_motion": float(top_motion),
        "mesh_preview_error": float(mesh_preview_error),
        "mesh_preview_count": int(mesh_preview_count),
        "stage_preview_errors": [float(value) for value in stage_errors],
    }
    print("SDH_BUG_BLEND_ROOT_TOP::" + json.dumps(report, sort_keys=True))
    if mesh_preview_error > 5.0e-4:
        raise AssertionError(f"root TOP preview drifted: {report!r}")
    print("SDH_BUG_BLEND_ROOT_TOP::PASS")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
