"""Numerical regression for dedicated FFD outside modes and interpolation."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import bpy

SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))
entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
core = importlib.import_module(f"{PACKAGE}.cage_deform.core")


def evaluated_x(target):
    bpy.context.view_layer.update()
    evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    result = evaluated.to_mesh()
    try:
        return tuple(round(float(vertex.co.x), 5) for vertex in result.vertices)
    finally:
        evaluated.to_mesh_clear()


mesh = bpy.data.meshes.new("SDH FFD Scope Mesh")
mesh.from_pydata(
    [(0.0, y, 0.0) for y in (-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0)],
    (),
    (),
)
target = bpy.data.objects.new("SDH FFD Scope", mesh)
bpy.context.collection.objects.link(target)
bpy.context.view_layer.objects.active = target
target.select_set(True)

try:
    modifier, controller, _previous = core.create_deform_stage(
        bpy.context, target, cage_type="FFD")
    core.fit_controller_to_alignment(
        bpy.context, target, modifier, controller, "POS_Y")
    properties = controller.sdh_cage_deform
    properties.size = (2.0, 2.0, 2.0)
    properties.ffd_interpolation_u = "KEY_CARDINAL"
    properties.ffd_interpolation_v = "KEY_LINEAR"
    properties.ffd_interpolation_w = "KEY_CATMULL_ROM"
    for index, point in enumerate(properties.ffd_points):
        _u, v, _w = core.ffd_point_coordinates(index, (2, 2, 2))
        point.offset = (0.5 if v else 0.0, 0.0, 0.0)

    lattice = core.ensure_ffd_lattice(target, modifier, controller)

    def native_state():
        current_lattice = core.ffd_lattice_object(target, modifier)
        current_modifier = next(
            item for item in target.modifiers
            if item.type == "LATTICE" and item.object == current_lattice
        )
        return current_lattice, current_modifier

    lattice, lattice_modifier = native_state()
    expected_interpolation = {
        "u": "KEY_CARDINAL",
        "v": "KEY_LINEAR",
        "w": "KEY_CATMULL_ROM",
    }
    for axis, expected in expected_interpolation.items():
        actual = getattr(lattice.data, f"interpolation_type_{axis}")
        if actual != expected:
            raise AssertionError(
                f"FFD {axis.upper()} interpolation was not synchronized")

    properties.mode = "LIMITED"
    core.sync_controller(controller, pull_transform=False)
    limited = evaluated_x(target)
    if limited[0] != 0.0 or limited[-1] != 0.5:
        raise AssertionError(f"Limited FFD did not hold its end planes: {limited}")
    if lattice_modifier.vertex_group:
        raise AssertionError("Limited FFD unexpectedly retained a scope group")

    properties.mode = "WITHIN_BOX"
    core.sync_controller(controller, pull_transform=False)
    lattice, lattice_modifier = native_state()
    within = evaluated_x(target)
    if within[:2] != (0.0, 0.0) or within[-2:] != (0.0, 0.0):
        raise AssertionError(f"Within Box FFD affected outside points: {within}")
    if not lattice_modifier.vertex_group:
        raise AssertionError("Within Box FFD did not assign its managed scope")

    properties.mode = "UNLIMITED"
    core.sync_controller(controller, pull_transform=False)
    lattice, lattice_modifier = native_state()
    unlimited = evaluated_x(target)
    if unlimited[0] >= -0.49 or unlimited[-1] <= 0.99:
        raise AssertionError(
            f"Unlimited FFD did not continue the boundary slope: {unlimited}")
    if unlimited == limited:
        raise AssertionError("Unlimited FFD collapsed to Limited behavior")
    if lattice_modifier.vertex_group:
        raise AssertionError("Unlimited FFD retained a stale scope group")
    if tuple((lattice.data.points_u, lattice.data.points_v,
              lattice.data.points_w)) == (2, 2, 2):
        raise AssertionError("Unlimited FFD did not extend its hidden lattice")

    properties.mode = "CHAINED"
    core.sync_controller(controller, pull_transform=False)
    lattice, lattice_modifier = native_state()
    chained = evaluated_x(target)
    if chained[:2] != (0.0, 0.0) or chained[-2:] != (0.0, 0.0):
        raise AssertionError(f"Chained FFD escaped its owned slice: {chained}")
    if not lattice_modifier.vertex_group:
        raise AssertionError("Chained FFD did not assign its axial scope")

    properties.mode = "LIMITED"
    core.sync_controller(controller, pull_transform=False)
    lattice, lattice_modifier = native_state()
    if (lattice.data.points_u, lattice.data.points_v,
            lattice.data.points_w) != (2, 2, 2):
        raise AssertionError("leaving Unlimited did not restore authored resolution")

    print("SDH_FFD_SCOPE::PASS")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
