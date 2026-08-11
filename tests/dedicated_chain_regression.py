"""Regression coverage for same-type Shear/FFD chains and subdivision."""
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


def fail(message):
    raise AssertionError(message)


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
gizmos = importlib.import_module(f"{PACKAGE}.cage_deform.gizmos")


def make_target(name):
    mesh = bpy.data.meshes.new(f"{name} Mesh")
    vertices = []
    faces = []
    for y in range(-4, 5):
        row = len(vertices)
        vertices.extend(((-1.0, float(y), -1.0), (1.0, float(y), -1.0),
                         (1.0, float(y), 1.0), (-1.0, float(y), 1.0)))
        if y < 4:
            next_row = row + 4
            faces.extend((
                (row, row + 1, next_row + 1, next_row),
                (row + 1, row + 2, next_row + 2, next_row + 1),
                (row + 2, row + 3, next_row + 3, next_row + 2),
                (row + 3, row, next_row, next_row + 3),
            ))
    mesh.from_pydata(vertices, (), faces)
    target = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(target)
    return target


def evaluated_positions(target):
    bpy.context.view_layer.update()
    evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    result = evaluated.to_mesh()
    try:
        return tuple(vertex.co.copy() for vertex in result.vertices)
    finally:
        evaluated.to_mesh_clear()


def make_z_chain_target(name):
    """Create non-degenerate section samples at three equal +Z stages."""
    levels = (-4.0, -4.0 / 3.0, 4.0 / 3.0, 4.0)
    vertices = []
    center_indices = []
    for z in levels:
        center_indices.append(len(vertices))
        vertices.extend((
            (0.0, 0.0, z),
            (-1.0, -1.0, z),
            (1.0, -1.0, z),
            (1.0, 1.0, z),
            (-1.0, 1.0, z),
        ))
    mesh = bpy.data.meshes.new(f"{name} Mesh")
    mesh.from_pydata(vertices, (), ())
    target = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(target)
    return target, tuple(center_indices), levels


try:
    shear_target = make_target("SDH Shear Chain Regression")
    bpy.ops.object.select_all(action="DESELECT")
    shear_target.select_set(True)
    bpy.context.view_layer.objects.active = shear_target
    result = bpy.ops.sdh.add_cage_chain(
        cage_type="SHEAR", count=3, connection_mode="CHAINED")
    if result != {"FINISHED"}:
        fail(f"Shear chain creation failed: {result!r}")
    shear_stages = tuple(deform.chain.chain_stages(shear_target))
    if len(shear_stages) != 3:
        fail("Shear chain did not create three stages")
    if any(
            shear_target.modifiers[index].type != "NODES"
            for index in range(len(shear_stages))):
        fail("Shear chain contains a non-node stage")
    if any(
            getattr(deform.find_controller(shear_target, stage).sdh_cage_deform,
                   "cage_type", "") != "SHEAR"
            for stage in shear_stages):
        fail("Shear chain contains a non-Shear controller")
    shear_root = deform.find_controller(shear_target, shear_stages[0])
    if shear_root.sdh_cage_deform.alignment != "POS_Z":
        fail("New cage chain did not default to +Z")
    if not shear_root.sdh_cage_deform.is_property_set("alignment"):
        fail("New cage chain did not persist its +Z alignment")
    if abs(float(shear_root.rotation_euler.x) - math.pi * 0.5) > 1.0e-5:
        fail("New +Z cage chain frame was not rotated onto target Z")

    shear_motion_target, center_indices, source_levels = make_z_chain_target(
        "SDH Shear Chain Motion Regression")
    bpy.ops.object.select_all(action="DESELECT")
    shear_motion_target.select_set(True)
    bpy.context.view_layer.objects.active = shear_motion_target
    if bpy.ops.sdh.add_cage_chain(
            cage_type="SHEAR", count=3, connection_mode="CHAINED",
            alignment="POS_Z", origin="BOTTOM") != {"FINISHED"}:
        fail("Shear motion chain creation failed")
    motion_stages = tuple(deform.chain.chain_stages(shear_motion_target))
    motion_controllers = tuple(
        deform.find_controller(shear_motion_target, stage)
        for stage in motion_stages)
    authored_shear = ((0.8, 0.2), (-0.6, 0.15), (0.5, -0.25))
    expected_displacement = Vector((0.0, 0.0, 0.0))
    for stage_index, (controller, shear_value) in enumerate(zip(
            motion_controllers, authored_shear)):
        before_positions = evaluated_positions(shear_motion_target)
        before_handle = gizmos.shear_handle_world(
            shear_motion_target, controller)
        response_x, response_z = gizmos.shear_drag_response_vectors(
            shear_motion_target, controller)
        solved = gizmos.shear_factor_delta_from_world(
            response_x * shear_value[0] + response_z * shear_value[1],
            response_x,
            response_z,
        )
        if (
                abs(float(solved.x) - shear_value[0]) > 1.0e-5 or
                abs(float(solved.z) - shear_value[1]) > 1.0e-5
        ):
            fail(f"Shear drag basis solve failed on stage {stage_index + 1}")
        controller.sdh_cage_deform.shear_factors = shear_value
        deform.core._drain_chain_reconnect_queue()
        bpy.context.view_layer.update()
        after_positions = evaluated_positions(shear_motion_target)
        after_handle = gizmos.shear_handle_world(
            shear_motion_target, controller)
        expected_handle = (
            before_handle + response_x * shear_value[0] +
            response_z * shear_value[1])
        if (after_handle - expected_handle).length > 0.005:
            fail(
                f"Shear stage {stage_index + 1} handle did not follow its "
                f"authored value: {(after_handle - expected_handle).length:.6f}")
        for fixed_index in center_indices[:stage_index + 1]:
            if (after_positions[fixed_index] - before_positions[fixed_index]).length > 0.001:
                fail(
                    f"Shear stage {stage_index + 1} moved an upstream boundary")

        expected_displacement += (
            response_x * shear_value[0] + response_z * shear_value[1])
        expected_boundary = (
            Vector((0.0, 0.0, source_levels[stage_index + 1])) +
            expected_displacement)
        actual_boundary = after_positions[center_indices[stage_index + 1]]
        if (actual_boundary - expected_boundary).length > 0.005:
            fail(
                f"Shear stage {stage_index + 1} was cancelled by its chain "
                f"frame: {(actual_boundary - expected_boundary).length:.6f}")
        if (after_handle - actual_boundary).length > 0.005:
            fail(
                f"Shear stage {stage_index + 1} handle does not match the "
                f"evaluated boundary: {(after_handle - actual_boundary).length:.6f}")

    shear_sub_target = make_target("SDH Shear Subdivision Regression")
    bpy.ops.object.select_all(action="DESELECT")
    shear_sub_target.select_set(True)
    bpy.context.view_layer.objects.active = shear_sub_target
    if bpy.ops.sdh.add_cage_deform(cage_type="SHEAR") != {"FINISHED"}:
        fail("Shear source cage creation failed")
    shear_source = shear_sub_target.modifiers.active
    shear_controller = deform.find_controller(shear_sub_target, shear_source)
    shear_controller.sdh_cage_deform.shear_factors = (0.35, -0.2)
    deform.sync_controller(shear_controller, pull_transform=False)
    if bpy.ops.sdh.subdivide_cage_to_chain(
            count=3, gap=0.0, auto_reconnect=True,
            sync_shared_end_scale=True) != {"FINISHED"}:
        fail("Shear cage subdivision failed")
    shear_sub_stages = tuple(deform.chain.chain_stages(shear_sub_target))
    if len(shear_sub_stages) != 3 or any(
            deform.find_controller(
                shear_sub_target, stage).sdh_cage_deform.cage_type != "SHEAR"
            for stage in shear_sub_stages):
        fail("Shear subdivision did not produce a same-type chain")
    if not any(
            max(abs(value) for value in deform.find_controller(
                shear_sub_target, stage).sdh_cage_deform.shear_factors) > 1.0e-5
            for stage in shear_sub_stages):
        fail("Shear subdivision discarded its authored deformation")

    direct_ffd_target = make_target("SDH Direct FFD Chain Regression")
    bpy.ops.object.select_all(action="DESELECT")
    direct_ffd_target.select_set(True)
    bpy.context.view_layer.objects.active = direct_ffd_target
    if bpy.ops.sdh.add_cage_chain(
            cage_type="FFD", count=2,
            connection_mode="CHAINED") != {"FINISHED"}:
        fail("Direct FFD chain creation failed")
    direct_ffd_stages = tuple(deform.chain.chain_stages(direct_ffd_target))
    if len(direct_ffd_stages) != 2 or any(
            deform.find_controller(
                direct_ffd_target, stage).sdh_cage_deform.cage_type != "FFD"
            for stage in direct_ffd_stages):
        fail("Direct FFD chain did not preserve its cage type")
    if len(tuple(
            item for item in direct_ffd_target.modifiers
            if item.type == "LATTICE")) != 2:
        fail("Direct FFD chain did not create one native lattice per stage")

    default_ffd_target = make_target("SDH Default FFD Subdivision Regression")
    bpy.ops.object.select_all(action="DESELECT")
    default_ffd_target.select_set(True)
    bpy.context.view_layer.objects.active = default_ffd_target
    if bpy.ops.sdh.add_cage_deform(cage_type="FFD") != {"FINISHED"}:
        fail("Default FFD cage creation failed")
    default_modifier = default_ffd_target.modifiers.active
    default_controller = deform.find_controller(
        default_ffd_target, default_modifier)
    default_properties = default_controller.sdh_cage_deform
    if deform.core.ffd_resolution(default_properties) != (2, 2, 2):
        fail("Default FFD subdivision fixture is not 2x2x2")
    default_properties.ffd_points[0].offset = (0.35, 0.0, 0.0)
    default_properties.ffd_points[-1].offset = (-0.2, 0.1, 0.0)
    deform.sync_controller(default_controller, pull_transform=False)
    default_before = evaluated_positions(default_ffd_target)
    if bpy.ops.sdh.subdivide_cage_to_chain(
            count=3, gap=0.0, auto_reconnect=True,
            sync_shared_end_scale=True) != {"FINISHED"}:
        fail("Default 2x2x2 FFD subdivision failed")
    default_after = evaluated_positions(default_ffd_target)
    default_error = max(
        (before - after).length
        for before, after in zip(default_before, default_after)
    )
    if default_error > 0.01:
        fail(
            "Default 2x2x2 FFD subdivision changed the source shape by "
            f"{default_error:.6f}")

    ffd_target = make_target("SDH FFD Chain Regression")
    bpy.ops.object.select_all(action="DESELECT")
    ffd_target.select_set(True)
    bpy.context.view_layer.objects.active = ffd_target
    result = bpy.ops.sdh.add_cage_deform(cage_type="FFD")
    if result != {"FINISHED"}:
        fail(f"FFD cage creation failed: {result!r}")
    source_modifier = ffd_target.modifiers.active
    source_controller = deform.find_controller(ffd_target, source_modifier)
    properties = source_controller.sdh_cage_deform
    properties.ffd_resolution_u = 3
    properties.ffd_resolution_v = 4
    properties.ffd_resolution_w = 3
    deform.core.ensure_ffd_point_collection(properties, preserve=False)
    properties.ffd_points[0].offset = (0.4, 0.0, 0.0)
    properties.ffd_points[-1].offset = (-0.2, 0.1, 0.0)
    # Selection belongs to the editable FFD state, not to the old point
    # indices.  Subdivision rebuilds each stage's point collection, so retain
    # anchors from the lower, middle, and upper V slices for the regression.
    selected_before = {
        deform.core.ffd_point_index(u, v, w, (3, 4, 3))
        for u, v, w in ((0, 0, 0), (2, 2, 2), (1, 3, 1))
    }
    deform.core.ffd_set_selection(properties, selected_before, active=min(selected_before))
    deform.sync_controller(source_controller, pull_transform=False)
    before_ffd_subdivision = evaluated_positions(ffd_target)
    ffd_target.modifiers.active = source_modifier
    result = bpy.ops.sdh.subdivide_cage_to_chain(
        count=3, gap=0.0, auto_reconnect=True, sync_shared_end_scale=True)
    if result != {"FINISHED"}:
        fail(f"FFD subdivision failed: {result!r}")
    ffd_stages = tuple(deform.chain.chain_stages(ffd_target))
    if len(ffd_stages) != 3:
        fail("FFD subdivision did not create three stages")
    if any(
            getattr(deform.find_controller(ffd_target, stage).sdh_cage_deform,
                   "cage_type", "") != "FFD"
            for stage in ffd_stages):
        fail("FFD subdivision changed a stage cage type")
    selected_after = []
    active_after = []
    for stage in ffd_stages:
        stage_properties = deform.find_controller(
            ffd_target, stage).sdh_cage_deform
        stage_selected = tuple(
            index for index, point in enumerate(stage_properties.ffd_points)
            if point.selected
        )
        selected_after.extend(stage_selected)
        active_after.append(
            int(stage_properties.ffd_active_point) in stage_selected)
    if len(selected_after) < len(selected_before):
        fail(
            "FFD subdivision discarded selected control points: "
            f"before={len(selected_before)} after={len(selected_after)}")
    if not any(active_after):
        fail("FFD subdivision did not retain an active control point")
    if not any(
            any(Vector(point.offset).length > 1.0e-5
                for point in deform.find_controller(
                    ffd_target, stage).sdh_cage_deform.ffd_points)
            for stage in ffd_stages):
        fail("FFD subdivision discarded all source offsets")
    after_ffd_subdivision = evaluated_positions(ffd_target)
    ffd_error = max(
        (before - after).length
        for before, after in zip(
            before_ffd_subdivision, after_ffd_subdivision)
    )
    if ffd_error > 0.01:
        worst = sorted(
            (
                ((before - after).length, index, tuple(before), tuple(after))
                for index, (before, after) in enumerate(zip(
                    before_ffd_subdivision, after_ffd_subdivision))
            ),
            reverse=True,
        )[:6]
        stage_debug = []
        for stage in ffd_stages:
            stage_controller = deform.find_controller(ffd_target, stage)
            stage_properties = stage_controller.sdh_cage_deform
            stage_lattice = deform.core.ffd_lattice_object(
                ffd_target, stage)
            stage_debug.append({
                "size": tuple(stage_properties.size),
                "location": tuple(stage_controller.location),
                "resolution": tuple(deform.core.ffd_resolution(stage_properties)),
                "offsets": [tuple(point.offset) for point in stage_properties.ffd_points],
                "lattice": tuple(stage_lattice.dimensions) if stage_lattice else None,
            })
        fail(
            f"FFD subdivision changed the source shape by {ffd_error:.6f}; "
            f"worst={worst!r}; stages={stage_debug!r}")
    report = deform.chain.validate_chain(ffd_target)
    if report["broken"] or report["cage_type_mismatch"]:
        fail(f"FFD chain metadata is broken: {report}")
    print("SDH_DEDICATED_CHAIN::PASS")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
