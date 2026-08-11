"""Verify dedicated FFD creation/evaluation for Curve and Surface targets."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import bpy

SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))
entry = bpy.context.preferences.addons.new()
addon = importlib.import_module(PACKAGE)
addon.register()
core = importlib.import_module(f"{PACKAGE}.cage_deform.core")


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def evaluated_curve_x(obj):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    result = evaluated.to_mesh()
    try:
        return tuple(
            round(float(vertex.co.x), 5) for vertex in result.vertices
        )
    finally:
        evaluated.to_mesh_clear()


def check_curve():
    data = bpy.data.curves.new("SDH FFD Curve", "CURVE")
    data.dimensions = "3D"
    data.bevel_depth = 0.01
    data.bevel_resolution = 0
    data.resolution_u = 1
    spline = data.splines.new("POLY")
    spline.points.add(3)
    for point, y in zip(spline.points, (-2.0, -0.5, 0.5, 2.0)):
        point.co = (0.0, y, 0.0, 1.0)
    obj = bpy.data.objects.new("SDH FFD Curve", data)
    bpy.context.collection.objects.link(obj)
    activate(obj)
    modifier, controller, _previous = core.create_deform_stage(
        bpy.context, obj, cage_type="FFD")
    core.fit_controller_to_alignment(
        bpy.context, obj, modifier, controller, "POS_Y")
    properties = controller.sdh_cage_deform
    properties.size = (1.0, 2.0, 1.0)
    properties.ffd_interpolation_u = "KEY_LINEAR"
    properties.ffd_interpolation_v = "KEY_LINEAR"
    properties.ffd_interpolation_w = "KEY_LINEAR"
    for index, point in enumerate(properties.ffd_points):
        _u, v, _w = core.ffd_point_coordinates(index, (2, 2, 2))
        point.offset = (0.5 if v else 0.0, 0.0, 0.0)
    properties.mode = "LIMITED"
    core.sync_controller(controller, pull_transform=False)
    if core.ffd_lattice_object(obj, modifier) is None:
        raise AssertionError("Curve FFD did not create a native lattice")
    limited = evaluated_curve_x(obj)
    properties.mode = "UNLIMITED"
    core.sync_controller(controller, pull_transform=False)
    unlimited = evaluated_curve_x(obj)
    if min(limited) < -0.02 or max(limited) < 0.49 or max(limited) > 0.52:
        raise AssertionError(f"Curve Limited FFD did not hold its ends: {limited}")
    if min(unlimited) >= -0.24 or max(unlimited) <= 0.74:
        raise AssertionError(
            f"Curve Unlimited FFD did not extend beyond the cage: {unlimited}")
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    evaluated.to_curve(bpy.context.evaluated_depsgraph_get())
    evaluated.to_curve_clear()
    bpy.data.objects.remove(obj, do_unlink=True)


def check_surface():
    bpy.ops.surface.primitive_nurbs_surface_surface_add(enter_editmode=False)
    obj = bpy.context.object
    obj.name = "SDH FFD Surface"
    activate(obj)
    modifier, controller, _previous = core.create_deform_stage(
        bpy.context, obj, cage_type="FFD")
    if obj.type != "MESH":
        raise AssertionError("Surface FFD target was not prepared for evaluation")
    if core.ffd_lattice_object(obj, modifier) is None:
        raise AssertionError("Converted Surface FFD did not create a lattice")
    bpy.context.view_layer.update()
    obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    bpy.data.objects.remove(obj, do_unlink=True)


try:
    check_curve()
    check_surface()
    print("SDH_FFD_NON_MESH::PASS")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
