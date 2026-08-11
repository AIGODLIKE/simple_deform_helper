"""Runtime regression for the independent animated Curve cage."""
from __future__ import annotations

import importlib
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


SOURCE = Path(__file__).resolve().parents[1]
INSTALLED_PACKAGE = os.environ.get("SDH_TEST_MODULE")
PACKAGE = INSTALLED_PACKAGE or SOURCE.name
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(SOURCE.parent))


def fail(message):
    raise AssertionError(message)


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.hide_set(False)
    obj.hide_select = False
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def evaluated_coordinates(obj):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return tuple(Vector(vertex.co) for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def animated_data_paths(id_data):
    animation = getattr(id_data, "animation_data", None)
    action = getattr(animation, "action", None) if animation else None
    return {
        str(curve.data_path)
        for curve in deform.core._iter_baked_action_fcurves(action)
    }


def preview_coordinates(obj, controller):
    cage_matrix = deform.cage_local_matrix(obj, controller)
    cage_inverse = cage_matrix.inverted_safe()
    object_inverse = obj.matrix_world.inverted_safe()
    local_points = tuple(
        cage_inverse @ (obj.matrix_world @ vertex.co)
        for vertex in obj.data.vertices)
    return tuple(
        object_inverse @ (
            cage_matrix @ deform.deform_point_from_properties(
                local_point,
                controller.sdh_cage_deform,
                chain_preview=True,
            )
        )
        for local_point in local_points
    )


addon = importlib.import_module(PACKAGE)
entry = None
if not INSTALLED_PACKAGE:
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
curve = importlib.import_module(f"{PACKAGE}.cage_deform.curve")
gizmos = importlib.import_module(f"{PACKAGE}.cage_deform.gizmos")
draw_module = importlib.import_module(f"{PACKAGE}.draw")

mesh = bpy.data.meshes.new("SDH Curve Cage Regression Mesh")
vertices = [
    (x, y, z)
    for z in (-2.0, -1.0, 0.0, 1.0, 2.0)
    for y in (-0.25, 0.25)
    for x in (-0.5, 0.5)
]
mesh.from_pydata(vertices, (), ())
target = bpy.data.objects.new("SDH Curve Cage Regression", mesh)
bpy.context.collection.objects.link(target)
activate(target)

try:
    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, target, cage_type="CURVE")
    properties = controller.sdh_cage_deform
    if properties.cage_type != "CURVE":
        fail("Curve cage type was not preserved")
    if set(properties.deform_types) != {"CURVE"}:
        fail(f"Curve cage did not lock its operation: {set(properties.deform_types)!r}")

    guide = curve.curve_guide_object(target, modifier)
    stations = curve.curve_station_object(target, modifier)
    if guide is None or guide.type != "CURVE":
        fail("Managed Bezier guide was not created")
    if stations is None or stations.type != "MESH":
        fail("Managed station mesh was not created")
    if len(properties.curve_stations) != 3:
        fail("Curve cage did not create three default cross sections")
    if modifier.node_group.get("_sdh_cage_chain_uuid", ""):
        fail("Independent Curve cage unexpectedly received chain metadata")

    # Structural rails, cross-section rings, and movable effect caps are three
    # distinct draw layers.  A cap sampler must never duplicate the four full
    # longitudinal rails, which previously made one Curve cage read as two.
    structural_positions, layer_caps = (
        draw_module._curve_cage_layer_positions(
            (0.0, 0.5, 1.0), 0.2, 0.8))
    if structural_positions != (0.0, 0.5, 1.0):
        fail("Curve effect range leaked into the structural ring positions")
    if layer_caps != (("BOTTOM", 0.2), ("TOP", 0.8)):
        fail(f"Curve effect cap layers are incorrect: {layer_caps!r}")
    _default_positions, default_caps = (
        draw_module._curve_cage_layer_positions(
            (0.0, 0.5, 1.0), 0.0, 1.0))
    if default_caps:
        fail("Default Curve effect caps would double-draw the cage ends")

    properties.curve_range_start = 0.2
    properties.curve_range_end = 0.8
    preview_state = gizmos.cage_preview_geometry_state(properties)
    preview_steps = 8
    wire = gizmos.cage_preview_wire_vertices(
        properties,
        steps=preview_steps,
        ring_positions=structural_positions,
        preview_state=preview_state,
    )
    rings = gizmos.cage_preview_ring_vertices(
        properties,
        structural_positions,
        preview_state=preview_state,
    )
    rail_vertex_count = 4 * preview_steps * 2
    if len(rings) != len(structural_positions) * 4 * 2:
        fail("Curve ring sampler returned an unexpected vertex count")
    if tuple(wire[rail_vertex_count:]) != tuple(rings):
        fail("Curve ring-only preview differs from the structural cage rings")
    if rail_vertex_count != 64 or len(rings) != 24:
        fail("Curve structural preview no longer has 32 rails / 12 ring segments")
    effect_caps = gizmos.cage_preview_ring_vertices(
        properties, (0.2, 0.8), preview_state=preview_state)
    if len(effect_caps) != 2 * 4 * 2:
        fail("Curve effect caps unexpectedly duplicated structural rails")
    properties.curve_range_start = 0.3
    properties.curve_range_end = 0.7
    moved_range_state = gizmos.cage_preview_geometry_state(properties)
    moved_range_wire = gizmos.cage_preview_wire_vertices(
        properties,
        steps=preview_steps,
        ring_positions=structural_positions,
        preview_state=moved_range_state,
    )
    if tuple(moved_range_wire) != tuple(wire):
        fail("Moving the Curve effect range changed the structural cage wire")
    properties.curve_range_start = 0.0
    properties.curve_range_end = 1.0

    depth_colors = draw_module._depth_cued_line_colors(
        (
            (0.0, 0.0, -3.0), (1.0, 0.0, -3.0),
            (0.0, 0.0, -1.0), (1.0, 0.0, -1.0),
        ),
        ((0, 1), (2, 3)),
        Matrix.Identity(4),
        (0.0, 0.72, 1.0, 0.4),
    )
    if not depth_colors[0][3] < depth_colors[2][3]:
        fail("Curve cage far-side lines were not depth faded")
    chain_type_items = {
        item.identifier
        for item in bpy.ops.sdh.add_cage_chain.get_rna_type().properties[
            "cage_type"].enum_items
    }
    if "CURVE" in chain_type_items:
        fail("Curve Cage is exposed by the chained-creation operator")

    deform.sync_controller(controller, pull_transform=False, sync_mode="push")
    straight = evaluated_coordinates(target)
    maximum_identity_error = max(
        (result - Vector(source)).length
        for result, source in zip(straight, vertices)
    )
    if maximum_identity_error > 2.0e-4:
        print("SDH_CURVE_IDENTITY_DIAGNOSTIC::", [
            (tuple(round(float(value), 4) for value in source),
             tuple(round(float(value), 4) for value in result))
            for source, result in zip(vertices[:8], straight[:8])
        ])
        fail(f"Straight Curve cage is not identity: {maximum_identity_error}")

    spline = guide.data.splines[0]
    spline.bezier_points[1].co.x = 1.0
    bpy.context.view_layer.update()
    curved = evaluated_coordinates(target)
    if max((a - b).length for a, b in zip(curved, straight)) < 0.25:
        fail("Editing the guide did not deform the target")

    properties.curve_stations[1].scale = (1.8, 0.6)
    properties.curve_stations[1].offset = (0.2, -0.1)
    bpy.context.view_layer.update()
    profiled = evaluated_coordinates(target)
    if max((a - b).length for a, b in zip(profiled, curved)) < 0.05:
        fail("Cross-section station values did not affect deformation")
    previewed = preview_coordinates(target, controller)
    preview_error = max(
        (actual - preview).length
        for actual, preview in zip(profiled, previewed))
    if preview_error > 0.08:
        ranked = sorted(
            (
                (actual - preview).length,
                index,
                actual,
                preview,
            )
            for index, (actual, preview) in enumerate(
                zip(profiled, previewed)))
        print("SDH_CURVE_PREVIEW_DIAGNOSTIC::", [
            (
                index,
                round(float(error), 6),
                tuple(round(float(value), 4) for value in actual),
                tuple(round(float(value), 4) for value in preview),
            )
            for error, index, actual, preview in ranked[-8:]
        ])
        fail(
            "Curve cage wire preview does not follow evaluated geometry: "
            f"{preview_error}")

    activate(target)
    target.modifiers.active = modifier
    if bpy.ops.sdh.edit_curve_cage() != {"FINISHED"}:
        fail("Curve Edit Mode did not start")
    if guide.mode != "EDIT":
        fail("Managed guide did not enter native Curve Edit Mode")
    if not target.select_get() or not controller.select_get() or not guide.select_get():
        fail("Curve Edit Mode did not retain target/controller animation selection")
    resolved_target, resolved_modifier, resolved_controller = (
        deform.resolve_context_deform(bpy.context))
    if (
            resolved_target != target or resolved_modifier != modifier or
            resolved_controller != controller
    ):
        fail("Curve Edit Mode lost the controlled target context")
    if bpy.ops.sdh.edit_curve_cage() != {"FINISHED"} or guide.mode != "OBJECT":
        fail("Curve Edit Mode did not exit cleanly")
    activate(target)
    target.modifiers.active = modifier
    deform.core._sync_target_cage_selection(bpy.context, target)
    if not guide.select_get() or bpy.context.view_layer.objects.active != target:
        fail("Selecting the target did not expose Curve guide animation channels")

    properties.curve_length_mode = "PRESERVE"
    properties.curve_boundary_mode = "CLAMP"
    deform.sync_controller(controller, pull_transform=False, sync_mode="push")
    clamped = evaluated_coordinates(target)
    if not all(all(math.isfinite(value) for value in point) for point in clamped):
        fail("Preserve/Clamp mapping produced non-finite coordinates")

    properties.curve_length_mode = "STRETCH"
    properties.curve_boundary_mode = "EXTEND"
    properties.curve_preserve_volume = True
    activate(target)
    spline = guide.data.splines[0]
    bpy.context.scene.frame_set(1)
    spline.bezier_points[1].co.x = 0.0
    properties.curve_stations[1].offset = (0.0, 0.0)
    if bpy.ops.sdh.insert_cage_keyframes() != {"FINISHED"}:
        fail("Curve keyframe insertion failed at frame 1")
    bpy.context.scene.frame_set(10)
    spline.bezier_points[1].co.x = 1.25
    spline.bezier_points[1].tilt = 0.35
    spline.bezier_points[1].radius = 1.3
    properties.curve_stations[1].offset = (0.3, -0.2)
    if bpy.ops.sdh.insert_cage_keyframes() != {"FINISHED"}:
        fail("Curve keyframe insertion failed at frame 10")
    if getattr(guide.data, "animation_data", None) is None:
        fail("Guide point animation was not stored on Curve data")
    if getattr(controller, "animation_data", None) is None:
        fail("Cross-section animation was not stored on the controller")
    guide_paths = animated_data_paths(guide.data)
    expected_guide_paths = {
        f"splines[0].bezier_points[{point_index}].{suffix}"
        for point_index in range(len(spline.bezier_points))
        for suffix in ("co", "handle_left", "handle_right", "tilt", "radius")
    }
    missing_guide_paths = expected_guide_paths - guide_paths
    if missing_guide_paths:
        fail(f"Curve guide animation paths are missing: {missing_guide_paths!r}")
    controller_paths = animated_data_paths(controller)
    expected_controller_paths = {
        "sdh_cage_deform.curve_length_mode",
        "sdh_cage_deform.curve_boundary_mode",
        "sdh_cage_deform.curve_preserve_volume",
        "sdh_cage_deform.curve_stations[1].factor",
        "sdh_cage_deform.curve_stations[1].scale",
        "sdh_cage_deform.curve_stations[1].offset",
        "location",
        "rotation_euler",
    }
    missing_controller_paths = expected_controller_paths - controller_paths
    if missing_controller_paths:
        fail(
            "Curve cage animation paths are missing: "
            f"{missing_controller_paths!r}")

    bpy.context.scene.frame_set(1)
    frame_one = evaluated_coordinates(target)
    bpy.context.scene.frame_set(10)
    frame_ten = evaluated_coordinates(target)
    if max((a - b).length for a, b in zip(frame_one, frame_ten)) < 0.2:
        fail("Curve keyframes did not produce evaluated animation")

    # Object-only duplication shares the original node groups but not hidden
    # helper children. Ownership repair must preserve the authored guide while
    # giving the duplicate independent Curve data and animation.
    duplicate = target.copy()
    duplicate.data = target.data.copy()
    bpy.context.collection.objects.link(duplicate)
    activate(duplicate)
    if not deform.core.ensure_target_stage_ownership(
            bpy.context, duplicate, defer_restricted=False):
        fail("Duplicated Curve target ownership was not repaired")
    duplicate_modifier = deform.cage_modifiers(duplicate)[0]
    duplicate_controller = deform.find_controller(duplicate, duplicate_modifier)
    duplicate_guide = curve.curve_guide_object(duplicate, duplicate_modifier)
    if duplicate_controller is None or duplicate_guide is None:
        fail("Duplicated Curve cage did not receive independent companions")
    source_points = tuple(
        tuple(point.co) for point in guide.data.splines[0].bezier_points)
    duplicate_points = tuple(
        tuple(point.co)
        for point in duplicate_guide.data.splines[0].bezier_points)
    if source_points != duplicate_points:
        fail("Duplicated Curve cage lost its authored guide shape")
    if duplicate_guide.data == guide.data:
        fail("Duplicated Curve cage still shares the source guide data")
    source_action = getattr(
        getattr(guide.data, "animation_data", None), "action", None)
    duplicate_action = getattr(
        getattr(duplicate_guide.data, "animation_data", None), "action", None)
    if source_action is not None and duplicate_action == source_action:
        fail("Duplicated Curve guide still shares the source animation Action")

    # Deleting a managed modifier through Blender's native stack UI must not
    # leave the hidden guide and station objects behind.
    duplicate.modifiers.remove(duplicate_modifier)
    deform.core.remove_orphan_cage_controllers(duplicate)
    orphan_helpers = tuple(
        obj for obj in bpy.data.objects
        if curve.is_curve_helper(obj) and getattr(obj, "parent", None) == duplicate)
    if orphan_helpers:
        fail(f"Direct modifier deletion left Curve helpers: {orphan_helpers!r}")

    baked, frame_count = deform.core.bake_cage_animation_to_shape_keys(
        bpy.context, target, 1, 10, 9, "SDH Curve Cage Baked")
    if frame_count != 2:
        fail(f"Curve animation bake sampled {frame_count} frames instead of 2")
    if baked.data.shape_keys is None or len(baked.data.shape_keys.key_blocks) < 2:
        fail("Curve animation bake did not create absolute shape keys")
    bpy.context.scene.frame_set(1)
    baked_frame_one = evaluated_coordinates(baked)
    bpy.context.scene.frame_set(10)
    baked_frame_ten = evaluated_coordinates(baked)
    bake_error = max(
        (source - result).length
        for source_frame, baked_frame in (
            (frame_one, baked_frame_one),
            (frame_ten, baked_frame_ten),
        )
        for source, result in zip(source_frame, baked_frame)
    )
    if bake_error > 3.0e-4:
        fail(f"Baked Curve animation differs from evaluated geometry: {bake_error}")

    activate(target)
    target.modifiers.active = modifier
    result = bpy.ops.sdh.subdivide_cage_to_chain(count=3)
    if result != {"CANCELLED"}:
        fail(f"Curve cage subdivision unexpectedly succeeded: {result!r}")

    # A Curve cage added later in the stack must capture the upstream evaluated
    # form, not the source object's undeformed bounds.
    stack_mesh = bpy.data.meshes.new("SDH Curve Upstream Mesh")
    stack_mesh.from_pydata(vertices, (), ())
    stack_target = bpy.data.objects.new("SDH Curve Upstream", stack_mesh)
    bpy.context.collection.objects.link(stack_target)
    activate(stack_target)
    upstream_modifier, upstream_controller, _previous = (
        deform.create_deform_stage(
            bpy.context, stack_target, cage_type="STANDARD"))
    upstream_properties = upstream_controller.sdh_cage_deform
    upstream_properties.bend_strength = math.radians(42.0)
    deform.sync_controller(
        upstream_controller, pull_transform=False, sync_mode="push")
    upstream_result = evaluated_coordinates(stack_target)
    curve_modifier, curve_controller, _previous = deform.create_deform_stage(
        bpy.context,
        stack_target,
        after_modifier=upstream_modifier,
        cage_type="CURVE",
    )
    inherited_result = evaluated_coordinates(stack_target)
    inherited_error = max(
        (before - after).length
        for before, after in zip(upstream_result, inherited_result))
    if inherited_error > 3.0e-4:
        fail(
            "A new Curve cage changed the inherited upstream form: "
            f"{inherited_error}")
    inherited_guide = curve.curve_guide_object(
        stack_target, curve_modifier)
    if inherited_guide is None:
        fail("Upstream-fitted Curve cage did not create its guide")
    expected_half_length = abs(
        float(curve_controller.sdh_cage_deform.size[1])) * 0.5
    inherited_endpoints = inherited_guide.data.splines[0].bezier_points
    if (
            abs(float(inherited_endpoints[0].co.y) + expected_half_length) > 1.0e-5 or
            abs(float(inherited_endpoints[-1].co.y) - expected_half_length) > 1.0e-5
    ):
        fail("Upstream-fitted Curve guide did not match its evaluated cage range")
    second_curve_modifier, second_curve_controller, _previous = (
        deform.create_deform_stage(
            bpy.context,
            stack_target,
            after_modifier=curve_modifier,
            cage_type="CURVE",
        ))
    second_guide = curve.curve_guide_object(
        stack_target, second_curve_modifier)
    if second_curve_controller is None or second_guide is None:
        fail("Second independent Curve cage did not create its companions")
    curve.set_curve_guide_display(
        stack_target,
        second_curve_modifier,
        show_other=True,
        view_layer=bpy.context.view_layer,
    )
    if inherited_guide.hide_get() or second_guide.hide_get():
        fail("Show Other Cages did not retain both Curve guides")
    if tuple(inherited_guide.color) == tuple(second_guide.color):
        fail("Active and inactive Curve guides did not use distinct colors")
    curve.set_curve_guide_display(
        stack_target,
        second_curve_modifier,
        show_other=False,
        view_layer=bpy.context.view_layer,
    )
    if not inherited_guide.hide_get() or second_guide.hide_get():
        fail("Curve guide visibility did not follow Show Other Cages")

    print("SDH_CURVE_CAGE::PASS")
finally:
    try:
        if getattr(bpy.context.object, "mode", "OBJECT") != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except RuntimeError:
        pass
    if not INSTALLED_PACKAGE:
        addon.unregister()
        bpy.context.preferences.addons.remove(entry)
