"""Capture stale-v17 and rebuilt chain geometry from a saved fixture."""

from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
SCREENSHOT = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
RESULT = Path(sys.argv[sys.argv.index("--") + 2]).resolve()
TARGET_NAME = sys.argv[sys.argv.index("--") + 3]
FORCE_REBUILD = (
    len(sys.argv) > sys.argv.index("--") + 4 and
    sys.argv[sys.argv.index("--") + 4].upper() == "REBUILD"
)
sys.path.insert(0, str(SOURCE.parent))
state = {"phase": 0}


def finish(result):
    RESULT.write_text(result, encoding="utf-8")
    print(f"SDH_V17_VISUAL::{result.splitlines()[0]}")
    bpy.ops.wm.quit_blender()


def run():
    try:
        if state["phase"] == 0:
            entry = bpy.context.preferences.addons.new()
            entry.module = PACKAGE
            addon = importlib.import_module(PACKAGE)
            addon.register()
            deform = importlib.import_module(f"{PACKAGE}.cage_deform")
            try:
                bpy.ops.wm.splash_close()
            except (AttributeError, RuntimeError):
                pass

            target = bpy.data.objects.get(TARGET_NAME)
            if target is None:
                raise AssertionError(f"fixture target not found: {TARGET_NAME}")
            for obj in bpy.context.scene.objects:
                obj.hide_viewport = obj != target
                obj.hide_set(obj != target)
            if FORCE_REBUILD:
                groups = {
                    modifier.node_group for modifier in target.modifiers
                    if deform.is_cage_modifier(modifier)
                }
                for group in groups:
                    group[deform.GROUP_MARKER] = deform.GROUP_VERSION - 1
                count = deform.upgrade_managed_stages()
                if count < 1:
                    raise AssertionError("forced node-group rebuild did not run")
                deform.core.sync_all_controllers(
                    pull_transform=False, sync_mode="timer")
                deform.core.flush_pending_chain_updates(target)

            bpy.ops.object.select_all(action="DESELECT")
            target.hide_viewport = False
            target.hide_set(False)
            target.select_set(True)
            bpy.context.view_layer.objects.active = target

            window = bpy.context.window_manager.windows[0]
            area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
            region = next(region for region in area.regions if region.type == "WINDOW")
            space = area.spaces.active
            space.show_region_ui = False
            space.overlay.show_floor = True
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.view3d.view_axis(type="FRONT", align_active=False)
                bpy.ops.view3d.view_selected(use_all_regions=False)
            state.update(window=window, area=area, region=region, phase=1)
            return 0.8

        if state["phase"] == 1:
            bpy.context.view_layer.update()
            state["phase"] = 2
            return 0.5

        with bpy.context.temp_override(
                window=state["window"], area=state["area"],
                region=state["region"]):
            bpy.ops.screen.screenshot_area(filepath=str(SCREENSHOT))
        if not SCREENSHOT.exists() or SCREENSHOT.stat().st_size < 1000:
            raise AssertionError("viewport screenshot was not created")
        finish("PASS")
        return None
    except Exception:
        finish("FAIL\n" + traceback.format_exc())
        return None


bpy.app.timers.register(run, first_interval=0.5)
