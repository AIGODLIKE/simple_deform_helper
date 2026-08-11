"""Open a three-stage FFD chain for manual viewport verification."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
OUTPUT = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
cage = importlib.import_module(f"{PACKAGE}.cage_deform")

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_cylinder_add(vertices=32)
target = bpy.context.object
target.name = "SDH 2.4.52 FFD Chain Preview"
target.scale = (1.4, 1.4, 4.2)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

result = bpy.ops.sdh.add_cage_chain(
    count=3,
    cage_type="FFD",
    origin="BOTTOM",
    alignment="POS_Z",
)
if result != {"FINISHED"}:
    raise RuntimeError(f"could not create visual FFD chain: {result!r}")

modifiers = tuple(cage.cage_modifiers(target))
controllers = tuple(
    cage.find_controller(target, modifier) for modifier in modifiers)
core = importlib.import_module(f"{PACKAGE}.cage_deform.core")
for controller in controllers:
    properties = controller.sdh_cage_deform
    properties.show_cage = True
    properties.show_other_cages = True
    properties.ffd_resolution_u = 2
    properties.ffd_resolution_v = 4
    properties.ffd_resolution_w = 2
    core.ensure_ffd_point_collection(properties, preserve=False)

target.modifiers.active = modifiers[-1]
core._activate(bpy.context, target)
core.refresh_controller_display(bpy.context, force=True)

window = bpy.context.window_manager.windows[0]
area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
region = next(region for region in area.regions if region.type == "WINDOW")
area.spaces.active.show_region_ui = False
with bpy.context.temp_override(window=window, area=area, region=region):
    bpy.ops.view3d.view_axis(type="FRONT", align_active=False)
    bpy.ops.view3d.view_selected(use_all_regions=False)

bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT), check_existing=False)
area.tag_redraw()
print(f"SDH_2452_FFD_PREVIEW::READY::{OUTPUT}")
