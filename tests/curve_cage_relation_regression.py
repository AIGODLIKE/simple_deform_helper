"""Focused regression coverage for Curve-driven and Cage-driven relations."""
from __future__ import annotations

import importlib
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


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.hide_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def guide_world_points(guide, spline):
    bpy.context.view_layer.update()
    return tuple(guide.matrix_world @ Vector(point.co)
                 for point in spline.bezier_points)


def evaluated_world_points(obj):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    evaluated_mesh = evaluated.to_mesh()
    try:
        return tuple(
            obj.matrix_world @ Vector(vertex.co)
            for vertex in evaluated_mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def preview_world_points(obj, controller, curve_module):
    cage_matrix = deform.cage_local_matrix(obj, controller)
    cage_inverse = cage_matrix.inverted_safe()
    source_world = tuple(
        obj.matrix_world @ Vector(vertex.co) for vertex in obj.data.vertices)
    source_local = tuple(cage_inverse @ point for point in source_world)
    mapper = curve_module.curve_preview_deformer(
        controller.sdh_cage_deform)
    return tuple(
        cage_matrix @ mapper(point, point.y, controller.sdh_cage_deform.size)
        for point in source_local)


addon = importlib.import_module(PACKAGE)
entry = None
if not INSTALLED_PACKAGE:
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
curve = importlib.import_module(f"{PACKAGE}.cage_deform.curve")


mesh = bpy.data.meshes.new("SDH Curve Relation Mesh")
mesh.from_pydata((
    (-0.5, -0.5, -2.0), (0.5, -0.5, -2.0),
    (-0.5, 0.5, 0.0), (0.5, 0.5, 0.0),
    (-0.5, -0.5, 2.0), (0.5, -0.5, 2.0),
    (0.0, 0.0, -2.0), (0.0, 0.0, 0.0), (0.0, 0.0, 2.0),
), (), ())
target = bpy.data.objects.new("SDH Curve Relation", mesh)
bpy.context.collection.objects.link(target)
activate(target)


try:
    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, target, cage_type="CURVE")
    properties = controller.sdh_cage_deform
    guide = curve.curve_guide_object(target, modifier)
    spline = curve.curve_guide_spline(guide)

    check(properties.curve_control_mode == "CURVE",
          "Curve relationship is not the default")
    check(properties.curve_length_mode == "STRETCH",
          "Curve relationship did not use the complete guide")

    source_size = tuple(properties.size)
    source_location = tuple(controller.location)
    middle = spline.bezier_points[1]
    middle.co.x += 1.25
    middle.handle_left.x += 1.25
    middle.handle_right.x += 1.25
    guide.data.update_tag()
    authored_world = guide_world_points(guide, spline)
    changed, local_shift = curve.sync_curve_cage_relation(
        controller, force=True)
    check(not changed and abs(local_shift) < 1.0e-8,
          "Curve editing unexpectedly rewrote the source cage domain")
    check((Vector(properties.size) - Vector(source_size)).length < 1.0e-7,
          "Curve editing changed the source cage size")
    check((Vector(controller.location) - Vector(source_location)).length < 1.0e-7,
          "Curve editing changed the source cage location")
    fitted_world = guide_world_points(guide, spline)
    check(max((left - right).length for left, right in zip(
        authored_world, fitted_world)) < 1.0e-5,
        "Curve relation synchronization moved the authored guide")

    evaluated_world = evaluated_world_points(target)
    guide_endpoints = guide_world_points(guide, spline)
    check((evaluated_world[6] - guide_endpoints[0]).length < 2.0e-4,
          "Curve mode object bottom does not reach the complete guide start")
    check((evaluated_world[8] - guide_endpoints[-1]).length < 2.0e-4,
          "Curve mode object top does not reach the complete guide end")

    # Curve Mode keeps a stable source domain mapped across the complete guide.
    # Its top/bottom handles edit only a normalized effect mask: cage size,
    # cage location, and every authored guide point must remain untouched.
    source_world = tuple(
        target.matrix_world @ Vector(vertex.co) for vertex in target.data.vertices)
    relation_size = tuple(properties.size)
    relation_location = tuple(controller.location)
    relation_guide = guide_world_points(guide, spline)
    relation_range = (
        float(properties.curve_range_start),
        float(properties.curve_range_end),
    )
    relation_axis_length = abs(float(relation_size[1]))
    check(max(abs(value - expected) for value, expected in zip(
        relation_range, (0.0, 1.0))) < 1.0e-7,
        "Curve effect range default changed")

    def check_relation_domain(label):
        check((Vector(properties.size) - Vector(relation_size)).length < 1.0e-7,
              f"{label} changed the stable Curve cage size")
        check(
            (Vector(controller.location) - Vector(relation_location)).length <
            1.0e-7,
            f"{label} changed the stable Curve cage location")
        check(max((left - right).length for left, right in zip(
            guide_world_points(guide, spline), relation_guide)) < 1.0e-5,
            f"{label} moved the authored Curve guide")

    properties.curve_mode = "UNLIMITED"
    unlimited_baseline = evaluated_world_points(target)
    deform.move_curve_effect_boundary(
        controller, "TOP", -relation_axis_length * 0.5,
        initial_range=relation_range,
        axis_limits=None,
        boundary_mode="SINGLE",
    )
    check(
        abs(float(properties.curve_range_start)) < 1.0e-7 and
        abs(float(properties.curve_range_end) - 0.5) < 1.0e-7,
        "Curve top handle did not edit only the effect-range end")
    check_relation_domain("Curve top effect boundary")
    properties.curve_mode = "LIMITED"
    top_limited = evaluated_world_points(target)
    check(abs((top_limited[8] - top_limited[7]).length - 2.0) < 2.0e-4,
          "Limited collapsed or rescaled the top outside axial spacing")
    top_preview = preview_world_points(target, controller, curve)
    check(max((actual - preview).length for actual, preview in zip(
        top_limited, top_preview)) < 0.08,
        "Curve top effect-range preview differs from evaluated geometry")
    properties.curve_mode = "WITHIN_BOX"
    top_within = evaluated_world_points(target)
    check((top_within[8] - source_world[8]).length < 2.0e-4,
          "Within Box changed geometry above the top effect range")
    properties.curve_mode = "UNLIMITED"
    top_unlimited = evaluated_world_points(target)
    check(max((left - right).length for left, right in zip(
        top_unlimited, unlimited_baseline)) < 2.0e-4,
        "Unlimited was affected by the top effect range")
    properties.curve_mode = "LIMITED"
    deform.move_curve_effect_boundary(
        controller, "TOP", 0.0,
        initial_range=relation_range,
        axis_limits=None,
        boundary_mode="SINGLE",
    )
    check(
        abs(float(properties.curve_range_start) - relation_range[0]) < 1.0e-7 and
        abs(float(properties.curve_range_end) - relation_range[1]) < 1.0e-7,
        "Curve top boundary cancellation did not restore its effect range")
    check_relation_domain("Curve top boundary cancellation")
    restored_top = evaluated_world_points(target)
    restored_guide = guide_world_points(guide, spline)
    check((restored_top[6] - restored_guide[0]).length < 2.0e-4 and
          (restored_top[8] - restored_guide[-1]).length < 2.0e-4,
          "Restoring the top boundary did not restore complete guide mapping")

    deform.move_curve_effect_boundary(
        controller, "BOTTOM", relation_axis_length * 0.5,
        initial_range=relation_range,
        axis_limits=None,
        boundary_mode="SINGLE",
    )
    check(
        abs(float(properties.curve_range_start) - 0.5) < 1.0e-7 and
        abs(float(properties.curve_range_end) - 1.0) < 1.0e-7,
        "Curve bottom handle did not edit only the effect-range start")
    check_relation_domain("Curve bottom effect boundary")
    properties.curve_mode = "LIMITED"
    bottom_limited = evaluated_world_points(target)
    check(abs((bottom_limited[7] - bottom_limited[6]).length - 2.0) < 2.0e-4,
          "Limited collapsed or rescaled the bottom outside axial spacing")
    properties.curve_mode = "WITHIN_BOX"
    bottom_within = evaluated_world_points(target)
    check((bottom_within[6] - source_world[6]).length < 2.0e-4,
          "Within Box changed geometry below the bottom effect range")
    properties.curve_mode = "UNLIMITED"
    bottom_unlimited = evaluated_world_points(target)
    check(max((left - right).length for left, right in zip(
        bottom_unlimited, unlimited_baseline)) < 2.0e-4,
        "Unlimited was affected by the bottom effect range")
    properties.curve_mode = "LIMITED"
    deform.move_curve_effect_boundary(
        controller, "BOTTOM", 0.0,
        initial_range=relation_range,
        axis_limits=None,
        boundary_mode="SINGLE",
    )
    check(
        abs(float(properties.curve_range_start) - relation_range[0]) < 1.0e-7 and
        abs(float(properties.curve_range_end) - relation_range[1]) < 1.0e-7,
        "Curve bottom boundary cancellation did not restore its effect range")
    check_relation_domain("Curve bottom boundary cancellation")
    restored_bottom = evaluated_world_points(target)
    restored_guide = guide_world_points(guide, spline)
    check((restored_bottom[6] - restored_guide[0]).length < 2.0e-4 and
          (restored_bottom[8] - restored_guide[-1]).length < 2.0e-4,
          "Restoring the bottom boundary did not restore complete guide mapping")

    properties.curve_control_mode = "CAGE"
    check(properties.curve_length_mode == "PRESERVE",
          "Cage relationship did not preserve physical cage distance")
    curve.reset_curve_guide_data(guide, properties)
    spline = curve.curve_guide_spline(guide)
    middle = spline.bezier_points[1]
    middle.co = Vector((0.8, 0.2, 0.25))
    middle.handle_left += Vector((0.8, 0.2, 0.25))
    middle.handle_right += Vector((0.8, 0.2, 0.25))
    guide.data.update_tag()
    curve.sync_curve_cage_relation(controller, force=True)

    initial_size = tuple(properties.size)
    initial_location = tuple(controller.location)
    before = guide_world_points(guide, spline)
    cage_mode_range = (
        float(properties.curve_range_start),
        float(properties.curve_range_end),
    )
    deform.move_curve_effect_boundary(
        controller, "TOP", -abs(float(initial_size[1])) * 0.25,
        initial_range=cage_mode_range,
        axis_limits=None,
        boundary_mode="SINGLE",
    )
    after = guide_world_points(guide, spline)
    check(
        abs(float(properties.curve_range_start) - cage_mode_range[0]) <
        1.0e-7 and
        abs(float(properties.curve_range_end) - 0.75) < 1.0e-7,
        "Cage-control relationship changed Curve-handle range semantics")
    check((Vector(properties.size) - Vector(initial_size)).length < 1.0e-7 and
          (Vector(controller.location) - Vector(initial_location)).length < 1.0e-7,
          "Cage-control relationship let an effect handle change its cage")
    check(max((left - right).length for left, right in zip(
        after, before)) < 1.0e-5,
        "Cage-control relationship let an effect handle move its guide")
    deform.move_curve_effect_boundary(
        controller, "TOP", 0.0,
        initial_range=cage_mode_range,
        axis_limits=None,
        boundary_mode="SINGLE",
    )

    endpoint = spline.bezier_points[-1]
    endpoint.co += Vector((100.0, 100.0, -100.0))
    endpoint.handle_left += Vector((100.0, 100.0, -100.0))
    endpoint.handle_right += Vector((100.0, 100.0, -100.0))
    guide.data.update_tag()
    curve.sync_curve_cage_relation(controller, force=True)
    half = Vector(properties.size) * 0.5
    check(all(abs(float(endpoint.co[axis])) <= float(half[axis]) + 1.0e-6
              for axis in range(3)),
          "Cage mode did not constrain the guide endpoint inside the cage")
    check((Vector(properties.size) - Vector(initial_size)).length < 1.0e-7 and
          (Vector(controller.location) - Vector(initial_location)).length < 1.0e-7,
          "Cage-mode endpoint constraint changed its source domain")

    relation = properties.curve_control_mode
    results = {}
    authored = Vector((0.15, float(properties.size[1]), -0.1))
    for mode in ("LIMITED", "WITHIN_BOX", "UNLIMITED"):
        properties.curve_mode = mode
        mapper = curve.curve_preview_deformer(properties)
        results[mode] = mapper(authored, authored.y, properties.size)
        check(properties.curve_control_mode == relation,
              f"Range mode {mode} changed the Curve/cage relationship")
    check((results["WITHIN_BOX"] - authored).length < 1.0e-6,
          "Within Box changed geometry outside the cage")
    check((results["LIMITED"] - results["UNLIMITED"]).length > 1.0e-4,
          "Limited and Unlimited no longer have distinct range behavior")

    properties.curve_control_mode = "CURVE"
    curve.reset_curve_guide_data(guide, properties)
    curve.sync_curve_cage_relation(controller, force=True)
    queued_size = tuple(properties.size)
    queued_location = tuple(controller.location)
    spline = curve.curve_guide_spline(guide)
    spline.bezier_points[1].co.x += 1.1
    spline.bezier_points[1].handle_left.x += 1.1
    spline.bezier_points[1].handle_right.x += 1.1
    guide.data.update_tag()
    check(curve.request_curve_relation_sync_from_update(guide.data),
          "Native Curve datablock update was not queued")
    curve._curve_relation_timer()
    check((Vector(properties.size) - Vector(queued_size)).length < 1.0e-7,
          "Deferred Curve editing changed the source cage size")
    check((Vector(controller.location) - Vector(queued_location)).length < 1.0e-7,
          "Deferred Curve editing changed the source cage location")
    deferred_world = evaluated_world_points(target)
    deferred_endpoints = guide_world_points(guide, spline)
    check((deferred_world[6] - deferred_endpoints[0]).length < 2.0e-4 and
          (deferred_world[8] - deferred_endpoints[-1]).length < 2.0e-4,
          "Deferred Curve editing lost complete source-to-guide mapping")

    properties.property_unset("curve_control_mode")
    properties.curve_length_mode = "PRESERVE"
    check(deform.core.curve_control_mode_identifier(properties) == "CAGE",
          "Legacy Preserve Length did not migrate to Cage mode")
    properties.curve_length_mode = "FIT_GUIDE"
    check(deform.core.curve_control_mode_identifier(properties) == "CURVE",
          "Legacy Fit Guide did not migrate to Curve mode")

    print("SDH_CURVE_CAGE_RELATION::PASS")
finally:
    curve.clear_curve_relation_sync()
    if not INSTALLED_PACKAGE:
        addon.unregister()
        bpy.context.preferences.addons.remove(entry)
