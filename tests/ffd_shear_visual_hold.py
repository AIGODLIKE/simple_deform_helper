"""Open a focused Blender UI scene for FFD and Shear interaction checks."""
from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path

import bpy
from mathutils import Euler, Vector

SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))

entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")

for obj in tuple(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=20)
target = bpy.context.object
target.name = "FFD Visual Check"
target.scale = (1.3, 2.8, 1.3)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

modifier, controller, _previous = deform.create_deform_stage(
    bpy.context, target, name="FFD Cage")
properties = controller.sdh_cage_deform
properties.cage_type = "FFD"
deform.sync_controller(controller, pull_transform=False)
target.modifiers.active = modifier

bpy.ops.mesh.primitive_cube_add(location=(4.2, 0.0, 0.0))
shear_target = bpy.context.object
shear_target.name = "Shear Visual Check"
shear_target.scale = (1.2, 2.4, 1.2)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
shear_modifier, shear_controller, _previous = deform.create_deform_stage(
    bpy.context, shear_target, name="Shear Cage")
shear_properties = shear_controller.sdh_cage_deform
shear_properties.cage_type = "SHEAR"
shear_properties.shear_factors = (0.32, 0.0)
deform.sync_controller(shear_controller, pull_transform=False)

for obj in tuple(bpy.context.selected_objects):
    obj.select_set(False)
shear_target.select_set(True)
bpy.context.view_layer.objects.active = shear_target
shear_target.modifiers.active = shear_modifier

for area in bpy.context.screen.areas:
    if area.type != "VIEW_3D":
        continue
    space = area.spaces.active
    space.show_region_ui = True
    region_3d = space.region_3d
    region_3d.view_location = Vector((1.8, 0.0, 0.0))
    region_3d.view_distance = 10.5
    region_3d.view_rotation = Euler((math.radians(67.0), 0.0, math.radians(42.0))).to_quaternion()
    for region in area.regions:
        if region.type == "UI":
            try:
                region.active_panel_category = "Simple Deformer V2"
            except (AttributeError, RuntimeError):
                pass

bpy.ops.wm.save_as_mainfile(
    filepath=str(SOURCE / "validation_runtime" / "SDH_FFD_SHEAR_VISUAL.blend"))
print("SDH_FFD_SHEAR_VISUAL::READY")
