"""Selection synchronization for Curve, Text, and Surface cage targets."""
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


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.hide_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def check_target(name, obj):
    activate(obj)
    modifier, controller, _previous = core.create_deform_stage(
        bpy.context, obj, name=f"{name} Cage")
    try:
        activate(obj)
        core._SELECTION_SYNC_SIGNATURE = None
        core._selection_watch_timer()
        if not obj.select_get() or not controller.select_get():
            raise AssertionError(
                f"{name} target selection did not include its controller")
        if bpy.context.view_layer.objects.active != obj:
            raise AssertionError(f"{name} target lost active-object status")
    finally:
        if modifier.name in obj.modifiers:
            obj.modifiers.remove(modifier)
        if controller.name in bpy.data.objects:
            bpy.data.objects.remove(controller, do_unlink=True)
        core.remove_unused_control_collections()


try:
    curve_data = bpy.data.curves.new("SDH Curve Selection", "CURVE")
    curve_data.dimensions = "3D"
    curve_data.bevel_depth = 0.2
    spline = curve_data.splines.new("POLY")
    spline.points.add(1)
    spline.points[0].co = (0.0, 0.0, -1.0, 1.0)
    spline.points[1].co = (0.0, 0.0, 1.0, 1.0)
    curve = bpy.data.objects.new("SDH Curve Selection", curve_data)
    bpy.context.collection.objects.link(curve)
    check_target("Curve", curve)

    text_data = bpy.data.curves.new("SDH Text Selection", "FONT")
    text_data.body = "SDH"
    text = bpy.data.objects.new("SDH Text Selection", text_data)
    bpy.context.collection.objects.link(text)
    check_target("Text", text)

    bpy.ops.surface.primitive_nurbs_surface_surface_add(
        enter_editmode=False, location=(0.0, 0.0, 0.0))
    surface = bpy.context.object
    surface.name = "SDH Surface Selection"
    check_target("Surface", surface)
    print("SDH_NON_MESH_SELECTION::PASS")
finally:
    for obj in tuple(bpy.data.objects):
        if obj.name.startswith("SDH Curve Selection") or \
                obj.name.startswith("SDH Text Selection") or \
                obj.name.startswith("SDH Surface Selection"):
            bpy.data.objects.remove(obj, do_unlink=True)
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
