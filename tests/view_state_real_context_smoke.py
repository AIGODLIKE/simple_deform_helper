"""Exercise the per-view display operator through a real Blender context."""
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
state = importlib.import_module(f"{PACKAGE}.view_state")

try:
    window = bpy.context.window_manager.windows[0]
    area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    region = next(region for region in area.regions if region.type == "WINDOW")
    with bpy.context.temp_override(window=window, area=area, region=region):
        if not state.viewport_cage_overlay_enabled(bpy.context):
            fail("real 3D View did not default to cage enabled")
        if bpy.ops.sdh.toggle_view_display(kind="cage") != {"FINISHED"}:
            fail("cage display operator did not finish")
        if state.viewport_cage_overlay_enabled(bpy.context):
            fail("cage display operator did not toggle the current view")
        if bpy.ops.sdh.toggle_view_display(kind="cage") != {"FINISHED"}:
            fail("cage display reset toggle did not finish")
        if not state.viewport_cage_overlay_enabled(bpy.context):
            fail("cage display toggle did not restore the current view")
    print("SDH_VIEW_STATE_REAL::PASS")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
    bpy.ops.wm.quit_blender()
