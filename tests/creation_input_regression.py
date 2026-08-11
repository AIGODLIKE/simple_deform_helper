"""Ensure a new cage fits the evaluated output of the preceding cage."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import bpy
from mathutils import Vector

SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))


def bounds_from_object(obj):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        points = tuple(vertex.co.copy() for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()
    minimum = Vector((
        min(point[index] for point in points) for index in range(3)))
    maximum = Vector((
        max(point[index] for point in points) for index in range(3)))
    return minimum, maximum


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")

mesh = bpy.data.meshes.new("SDH Creation Input Regression Mesh")
mesh.from_pydata(
    ((-1.0, -2.0, -1.0), (1.0, -2.0, -1.0),
     (1.0, 2.0, 1.0), (-1.0, 2.0, 1.0)),
    (), ((0, 1, 2, 3),),
)
target = bpy.data.objects.new("SDH Creation Input Regression", mesh)
bpy.context.collection.objects.link(target)
bpy.ops.object.select_all(action="DESELECT")
bpy.context.view_layer.objects.active = target
target.select_set(True)

try:
    target.modifiers.active = None
    first_result = bpy.ops.sdh.add_cage_deform(cage_type="SHEAR")
    if first_result != {"FINISHED"}:
        raise AssertionError(f"shear cage creation failed: {first_result!r}")
    first = deform.cage_modifiers(target)[0]
    first_controller = deform.find_controller(target, first)
    first_properties = first_controller.sdh_cage_deform
    if first_properties.alignment != "POS_Z":
        raise AssertionError(
            f"new cage did not default to +Z: {first_properties.alignment!r}")
    if not first_properties.is_property_set("alignment"):
        raise AssertionError("new cage did not persist its +Z alignment")
    if abs(float(first_controller.rotation_euler.x) - 1.5707963267948966) > 1.0e-5:
        raise AssertionError("new +Z cage frame was not rotated onto target Z")
    first_properties.cage_type = "SHEAR"
    first_properties.shear_factors = (1.25, 0.0)
    before = bounds_from_object(target)
    before_size = before[1] - before[0]

    second_result = bpy.ops.sdh.add_cage_deform(cage_type="STANDARD")
    if second_result != {"FINISHED"}:
        raise AssertionError(
            f"standard cage creation failed: {second_result!r}")
    second = deform.cage_modifiers(target)[-1]
    second_controller = deform.find_controller(target, second)
    second_size = Vector(second_controller.sdh_cage_deform.size)
    # The explicit +Z default maps target Z to cage V. All three extents must
    # still come from the evaluated shear result, not the source.
    expected = sorted(round(float(value), 5) for value in before_size)
    actual = sorted(round(float(value), 5) for value in second_size)
    print(f"SDH_CREATION_INPUT::BOUNDS::{expected!r}::{actual!r}")
    if actual != expected:
        raise AssertionError(
            f"new cage ignored preceding evaluated stage: {actual!r} != {expected!r}")
    print("SDH_CREATION_INPUT::PASS")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
