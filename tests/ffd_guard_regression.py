"""Blender regression for optional FFD anti-foldover protection."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import bpy
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))

entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
core = importlib.import_module(f"{PACKAGE}.cage_deform.core")
guard = importlib.import_module(f"{PACKAGE}.cage_deform.ffd_guard")
native_edit = importlib.import_module(f"{PACKAGE}.cage_deform.ffd_native_edit")


def check(condition, message):
    if not condition:
        raise AssertionError(message)


mesh = bpy.data.meshes.new("SDH FFD Guard Mesh")
mesh.from_pydata(
    (
        (-1.0, -1.0, -1.0), (1.0, -1.0, -1.0),
        (1.0, 1.0, -1.0), (-1.0, 1.0, -1.0),
        (-1.0, -1.0, 1.0), (1.0, -1.0, 1.0),
        (1.0, 1.0, 1.0), (-1.0, 1.0, 1.0),
    ), (), ()
)
target = bpy.data.objects.new("SDH FFD Guard", mesh)
bpy.context.collection.objects.link(target)
bpy.context.view_layer.objects.active = target
target.select_set(True)

try:
    modifier, controller, _previous = core.create_deform_stage(
        bpy.context, target, cage_type="FFD")
    properties = controller.sdh_cage_deform
    properties.ffd_resolution_u = 2
    properties.ffd_resolution_v = 2
    properties.ffd_resolution_w = 2
    properties.ffd_guard_mode = "SAFE"
    properties.ffd_interpolation_u = "KEY_BSPLINE"
    properties.ffd_interpolation_v = "KEY_BSPLINE"
    properties.ffd_interpolation_w = "KEY_BSPLINE"
    core.ensure_ffd_point_collection(properties)
    core.ensure_ffd_lattice(target, modifier, controller)

    lattice = core.ffd_lattice_object(target, modifier)
    check(lattice is not None, "SAFE FFD did not create a native lattice")
    check(tuple(
        getattr(lattice.data, f"interpolation_type_{axis}")
        for axis in ("u", "v", "w")
    ) == ("KEY_LINEAR",) * 3,
          "SAFE FFD did not use linear runtime interpolation")

    zero = tuple((0.0, 0.0, 0.0) for _index in range(8))
    folded = list(zero)
    for index in (4, 6):
        folded[index] = (3.0, 0.0, 0.0)
    for index in (5, 7):
        folded[index] = (-3.0, 0.0, 0.0)
    safe, fraction, baseline_ratio, candidate_ratio = core.ffd_guard_offsets(
        properties, tuple(folded), baseline_offsets=zero)
    check(0.0 < fraction < 1.0,
          f"SAFE FFD did not clamp a folded candidate: {fraction}")
    check(baseline_ratio >= guard.MIN_JACOBIAN_RATIO,
          f"SAFE FFD rejected its baseline: {baseline_ratio}")
    check(candidate_ratio < guard.MIN_JACOBIAN_RATIO,
          f"folded candidate unexpectedly passed: {candidate_ratio}")
    effective = guard._effective_points(
        tuple(properties.size), (2, 2, 2), safe, (1.0,) * 8)
    check(guard.minimum_jacobian_ratio(
        effective, tuple(properties.size), (2, 2, 2)) >=
          guard.MIN_JACOBIAN_RATIO,
          "SAFE FFD returned an inverted field")

    # Unlimited controls how points outside the authored cage domain are
    # evaluated; it must not disable protection against an inverted cage.
    properties.mode = "UNLIMITED"
    unlimited_safe, unlimited_fraction, _, _ = core.ffd_guard_offsets(
        properties, tuple(folded), baseline_offsets=zero)
    check(0.0 < unlimited_fraction < 1.0 and
          unlimited_safe != tuple(folded),
          "UNLIMITED SAFE FFD allowed a folded field")
    properties.mode = "LIMITED"

    # Changing weight or cage size invalidates the cached baseline ratio.
    properties.ffd_guard_mode = "OFF"
    for point, value in zip(properties.ffd_points, zero):
        point.offset = value
        point.influence = 1.0
    properties.ffd_guard_mode = "SAFE"
    core.ensure_ffd_lattice(target, modifier, controller)
    properties.ffd_points[4].influence = 0.9
    changed_weight, weight_fraction, _, _ = core.ffd_guard_offsets(
        properties, tuple(folded), baseline_offsets=zero)
    check(0.0 < weight_fraction < 1.0 and
          changed_weight != tuple(folded),
          "SAFE FFD reused a stale weight baseline")
    properties.ffd_points[4].influence = 1.0
    properties.size = (4.0, 2.0, 2.0)
    changed_size, size_fraction, _, _ = core.ffd_guard_offsets(
        properties, tuple(folded), baseline_offsets=zero)
    check(0.0 < size_fraction < 1.0 and
          changed_size != tuple(folded),
          "SAFE FFD reused a stale size baseline")

    operator_type = core.SDH_OT_box_select_ffd_points
    sources = {
        index: operator_type._point_source_local(properties, index)
        for index in range(8)
    }
    initial_points = dict(sources)
    operator = type("GuardOperator", (), {})()
    operator._controller = lambda: controller
    operator._transform_source_points = sources
    operator._transform_initial_points = initial_points
    operator._transform_initial_offsets = {
        index: (0.0, 0.0, 0.0) for index in range(8)
    }
    operator._area = None
    requested = {
        index: sources[index] + Vector(folded[index]) for index in range(8)
    }
    check(operator_type._write_transform_points(
        operator, bpy.context, properties, requested),
          "SAFE FFD Object Edit write failed")
    check(tuple(tuple(point.offset) for point in properties.ffd_points) !=
          tuple(folded),
          "SAFE FFD Object Edit allowed a folded field")

    lattice = core.ffd_lattice_object(target, modifier)
    proxy = native_edit._create_edit_proxy(
        bpy.context, target, modifier, controller, lattice)
    scale = native_edit._runtime_scale(proxy)
    for index, point in enumerate(proxy.data.points):
        point.co_deform = native_edit._native_base_coordinate(proxy, index) + Vector(
            tuple(
                component / max(float(axis_scale), 1.0e-8)
                for component, axis_scale in zip(folded[index], scale)
            )
        )
    check(native_edit._pull(controller, proxy),
          "SAFE FFD Native Edit pull failed")
    check(tuple(tuple(point.offset) for point in properties.ffd_points) !=
          tuple(folded),
          "SAFE FFD Native Edit allowed a folded field")
    native_edit._remove_proxy(proxy)

    properties.ffd_guard_mode = "OFF"
    for point, value in zip(properties.ffd_points, folded):
        point.offset = value
    properties.ffd_guard_mode = "SAFE"
    core.ensure_ffd_lattice(target, modifier, controller)
    stored = tuple(tuple(point.offset) for point in properties.ffd_points)
    check(stored != tuple(folded),
          "SAFE FFD allowed a direct folded property edit")

    properties.ffd_guard_mode = "OFF"
    core.ensure_ffd_lattice(target, modifier, controller)
    lattice = core.ffd_lattice_object(target, modifier)
    check(tuple(
        getattr(lattice.data, f"interpolation_type_{axis}")
        for axis in ("u", "v", "w")
    ) == ("KEY_BSPLINE",) * 3,
          "OFF FFD did not restore authored interpolation")

    print("SDH_FFD_GUARD::PASS")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
