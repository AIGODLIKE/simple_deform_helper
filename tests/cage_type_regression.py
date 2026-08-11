"""Smoke-test dedicated Shear/FFD cage type restrictions on Blender 5+."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import bpy

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

mesh = bpy.data.meshes.new("SDH Cage Type Regression Mesh")
mesh.from_pydata(
    ((-1.0, -2.0, -1.0), (1.0, -2.0, -1.0),
     (1.0, 2.0, 1.0), (-1.0, 2.0, 1.0)),
    (), ((0, 1, 2, 3),),
)
target = bpy.data.objects.new("SDH Cage Type Regression", mesh)
bpy.context.collection.objects.link(target)
bpy.context.view_layer.objects.active = target
target.select_set(True)

try:
    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, target)
    properties = controller.sdh_cage_deform

    if not deform.core.add_deform_layer(properties, "SHEAR", context=bpy.context):
        fail("Standard cage did not accept Shear as a deformation layer")
    if deform.core.add_deform_layer(properties, "FFD", context=bpy.context):
        fail("Standard cage accepted dedicated FFD as a layer")

    if set(properties.deform_types) != {"BEND", "SHEAR"}:
        fail("Standard cage did not retain Bend and Shear layers")
    properties.cage_type = "SHEAR"
    if set(properties.deform_types) != {"SHEAR"}:
        fail("Shear cage did not lock its deformation layer")
    if properties.mode == "CHAINED":
        fail("Shear cage unexpectedly inherited chained mode")
    if deform.core.add_deform_layer(properties, "BEND", context=bpy.context):
        fail("Shear cage accepted a second deformation layer")

    before = len(tuple(target.modifiers))
    target.modifiers.active = modifier
    result = bpy.ops.sdh.add_cage_chain(
        count=2, cage_type="SHEAR", connection_mode="CHAINED")
    if result != {"FINISHED"} or len(tuple(target.modifiers)) != before + 2:
        fail(f"Shear cage chain creation failed: {result!r}")

    ffd_mesh = bpy.data.meshes.new("SDH FFD Type Regression Mesh")
    ffd_mesh.from_pydata(((-1.0, -1.0, -1.0), (1.0, -1.0, -1.0),
                          (1.0, 1.0, 1.0), (-1.0, 1.0, 1.0)), (),
                         ((0, 1, 2, 3),))
    ffd_target = bpy.data.objects.new("SDH FFD Type Regression", ffd_mesh)
    bpy.context.collection.objects.link(ffd_target)
    bpy.ops.object.select_all(action="DESELECT")
    ffd_target.select_set(True)
    bpy.context.view_layer.objects.active = ffd_target
    ffd_modifier, ffd_controller, _previous = deform.create_deform_stage(
        bpy.context, ffd_target, cage_type="FFD")
    ffd_properties = ffd_controller.sdh_cage_deform
    if set(ffd_properties.deform_types) != {"FFD"}:
        fail("FFD cage did not lock its deformation layer")
    if deform.core.add_deform_layer(
            ffd_properties, "BEND", context=bpy.context):
        fail("FFD cage accepted a second deformation layer")
    print("SDH_CAGE_TYPE::PASS")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
