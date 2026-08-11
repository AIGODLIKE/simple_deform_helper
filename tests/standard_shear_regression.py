"""Verify that a Standard cage can evaluate an ordered Shear layer."""
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


def evaluated_positions(target):
    bpy.context.view_layer.update()
    evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    result = evaluated.to_mesh()
    try:
        return tuple(vertex.co.copy() for vertex in result.vertices)
    finally:
        evaluated.to_mesh_clear()


mesh = bpy.data.meshes.new("SDH Standard Shear Mesh")
mesh.from_pydata(
    [(-0.5, -1.0, 0.0), (0.5, -1.0, 0.0),
     (-0.5, 1.0, 0.0), (0.5, 1.0, 0.0)],
    (),
    (),
)
target = bpy.data.objects.new("SDH Standard Shear", mesh)
bpy.context.collection.objects.link(target)
bpy.context.view_layer.objects.active = target
target.select_set(True)

try:
    modifier, controller, _previous = core.create_deform_stage(
        bpy.context, target, cage_type="STANDARD")
    properties = controller.sdh_cage_deform
    properties.size = (1.0, 2.0, 1.0)
    core.set_deform_layers(properties, ("SHEAR",), bpy.context)
    properties.shear_factors = (0.0, 0.0)
    core.sync_controller(controller, pull_transform=False)
    before = evaluated_positions(target)
    properties.shear_factors = (0.5, -0.25)
    core.sync_controller(controller, pull_transform=False)
    after = evaluated_positions(target)

    if properties.cage_type != "STANDARD":
        raise AssertionError("Shear layer changed the Standard cage type")
    if set(properties.deform_types) != {"SHEAR"}:
        raise AssertionError("Standard cage did not retain the Shear layer")
    if not any((first - second).length > 1.0e-5
               for first, second in zip(before, after)):
        raise AssertionError("Standard Shear layer did not deform geometry")
    if abs(after[-1].x - before[-1].x) <= 0.1:
        raise AssertionError("Standard Shear layer did not move the upper section")

    print("SDH_STANDARD_SHEAR::PASS")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
