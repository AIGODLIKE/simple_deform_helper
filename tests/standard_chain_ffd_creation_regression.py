"""Ensure adding an FFD cage after a Standard chain keeps it independent."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")

try:
    bpy.ops.mesh.primitive_cube_add()
    target = bpy.context.object
    activate(target)
    if bpy.ops.sdh.add_cage_chain(
            cage_type="STANDARD", count=3,
            connection_mode="CHAINED") != {"FINISHED"}:
        raise AssertionError("could not create the Standard chain")

    standard_stages = tuple(deform.cage_modifiers(target))
    if len(standard_stages) != 3:
        raise AssertionError(
            f"expected three Standard stages, got {len(standard_stages)}")
    standard_types = tuple(
        deform.find_controller(target, stage).sdh_cage_deform.cage_type
        for stage in standard_stages)
    if standard_types != ("STANDARD",) * 3:
        raise AssertionError(f"initial chain types changed: {standard_types!r}")

    if bpy.ops.sdh.add_cage_deform(cage_type="FFD") != {"FINISHED"}:
        raise AssertionError("could not create the FFD stage")
    stages = tuple(deform.cage_modifiers(target))
    ffd_modifier = target.modifiers.active
    ffd_controller = deform.find_controller(target, ffd_modifier)
    if ffd_modifier not in stages or ffd_controller is None:
        raise AssertionError("new FFD stage could not be resolved")
    actual_type = str(ffd_controller.sdh_cage_deform.cage_type)
    if actual_type != "FFD":
        raise AssertionError(
            f"FFD creation inherited the wrong type: {actual_type!r}")
    if set(ffd_controller.sdh_cage_deform.deform_types) != {"FFD"}:
        raise AssertionError("new FFD stage did not lock to its FFD operation")
    if deform.core.ffd_lattice_object(target, ffd_modifier) is None:
        raise AssertionError("new FFD stage has no native lattice companion")
    if deform.chain.stage_chain_uuid(ffd_modifier):
        raise AssertionError("independent FFD stage inherited a chain UUID")
    print("SDH_STANDARD_CHAIN_FFD_CREATION::PASS")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
