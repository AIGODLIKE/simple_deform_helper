"""Open a disposable FFD scene for real viewport input diagnostics."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
STATE_FILE = SOURCE.parents[1] / "validation_reports" / "ffd_preedit_live_state.json"
KEYMAP_FILE = SOURCE.parents[1] / "validation_reports" / "ffd_preedit_live_keymaps.json"
POLL_FILE = SOURCE.parents[1] / "validation_reports" / "ffd_preedit_live_poll.json"
sys.path.insert(0, str(SOURCE.parent))

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)

entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
KEYMAP_FILE.write_text(json.dumps([
    {
        "config": keyconfig.name,
        "keymap": keymap.name,
        "space_type": keymap.space_type,
        "region_type": keymap.region_type,
        "idname": item.idname,
        "type": item.type,
        "value": item.value,
        "active": bool(item.active),
    }
    for keyconfig in bpy.context.window_manager.keyconfigs
    for keymap in keyconfig.keymaps
    for item in keymap.keymap_items
    if item.type == "B"
], indent=2), encoding="utf-8")

bpy.ops.mesh.primitive_cube_add(size=2.0)
target = bpy.context.object
target.name = "FFD Box Select Target"
if bpy.ops.sdh.add_cage_deform(cage_type="FFD") != {"FINISHED"}:
    raise RuntimeError("Could not create FFD test cage")

cage = importlib.import_module(f"{PACKAGE}.cage_deform")
modifier = target.modifiers.active
controller = cage.find_controller(target, modifier)
if controller is None:
    raise RuntimeError("Could not resolve FFD test controller")
controller.name = "FFD Box Select Controller"
properties = controller.sdh_cage_deform
properties.cage_type = "FFD"
properties.ffd_resolution_u = 3
properties.ffd_resolution_v = 3
properties.ffd_resolution_w = 3
properties.ffd_selection_modes = {"POINT"}
properties.show_cage = True
cage.sync_controller(controller, pull_transform=False)


def frame_target():
    window = bpy.context.window_manager.windows[0]
    area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    region = next(region for region in area.regions if region.type == "WINDOW")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    with bpy.context.temp_override(
            window=window, area=area, region=region, space_data=area.spaces.active):
        bpy.ops.view3d.view_selected(use_all_regions=False)
        cage.refresh_controller_display(bpy.context, force=True)
        POLL_FILE.write_text(json.dumps({
            "box_poll": bool(cage.core.SDH_OT_box_select_ffd_points.poll(
                bpy.context)),
            "active_object": getattr(bpy.context.view_layer.objects.active, "name", ""),
            "active_modifier": getattr(target.modifiers.active, "name", ""),
        }), encoding="utf-8")
    return None


def record_state():
    core = cage.core
    STATE_FILE.write_text(json.dumps({
        "edit_mode": bool(properties.ffd_edit_mode_active),
        "selected_points": [
            index for index, point in enumerate(properties.ffd_points)
            if point.selected
        ],
        "modal_count": len(core._FFD_MODAL_OPERATORS),
        "modal_state": [
            getattr(operator, "_state", None)
            for operator in core._FFD_MODAL_OPERATORS
        ],
    }), encoding="utf-8")
    return 0.15


bpy.app.timers.register(frame_target, first_interval=0.2)
bpy.app.timers.register(record_state, first_interval=0.15)
