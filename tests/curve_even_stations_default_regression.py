"""Ensure newly-created Curve cages enable even cross sections by default."""

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

bpy.ops.mesh.primitive_cube_add()
target = bpy.context.object
if bpy.ops.sdh.add_cage_deform(cage_type="CURVE") != {"FINISHED"}:
    raise RuntimeError("could not create a Curve cage")

core = importlib.import_module(f"{PACKAGE}.cage_deform.core")
controller = core.find_controller(target, core.cage_modifiers(target)[0])
if controller is None:
    raise RuntimeError("Curve cage controller was not created")
if not controller.sdh_cage_deform.curve_even_stations:
    raise RuntimeError("Curve cages do not enable Even Cross Sections by default")

addon.unregister()
bpy.context.preferences.addons.remove(entry)
print("SDH::CURVE_EVEN_STATIONS_DEFAULT::PASS")
