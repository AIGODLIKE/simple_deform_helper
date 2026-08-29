"""Check direct multi-object cage creation for every cage type."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))


def cube(name, location):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    return obj


def select(objects, active):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
core = importlib.import_module(f"{PACKAGE}.cage_deform.core")
merge_module = importlib.import_module(f"{PACKAGE}.cage_deform.merge")

try:
    for cage_type in ("STANDARD", "SHEAR", "FFD", "CURVE"):
        first = cube(f"Multi {cage_type} First", (-2.0, 0.0, 0.0))
        second = cube(f"Multi {cage_type} Second", (2.0, 0.0, 0.0))
        select((first, second), first)
        result = bpy.ops.sdh.add_cage_deform(cage_type=cage_type)
        if result != {"FINISHED"}:
            raise AssertionError(f"{cage_type} add failed: {result!r}")
        merge = bpy.context.object
        if not merge_module.is_deform_merge(merge) or not merge.select_get():
            raise AssertionError(f"{cage_type} merge is not active/selected")
        stages = core.cage_modifiers(merge)
        if len(stages) != 1:
            raise AssertionError(f"{cage_type} stage count: {len(stages)}")
        controller = core.find_controller(merge, stages[0])
        if controller is None or not controller.select_get():
            raise AssertionError(f"{cage_type} controller is not selected")
        if bpy.context.view_layer.objects.active != merge:
            raise AssertionError(f"{cage_type} merge is not active")
        if not merge_module.release_deform_merge(bpy.context, merge):
            raise AssertionError(f"{cage_type} merge release failed")
        for obj in (first, second):
            if obj.name in bpy.data.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
    print("SDH_MULTI_CAGE_TYPES::PASS")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
