"""Create and capture a real viewport scene for Cage Deform visual QA."""

import importlib
import math
import sys
import traceback
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
SCREENSHOT = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
RESULT = Path(sys.argv[sys.argv.index("--") + 2]).resolve()
DEFORM_TYPE = (
    sys.argv[sys.argv.index("--") + 3]
    if len(sys.argv) > sys.argv.index("--") + 3 else "BEND"
)
sys.path.insert(0, str(SOURCE.parent))

state = {"addon": None, "entry": None, "phase": 0}


def finish(result):
    RESULT.write_text(result, encoding="utf-8")
    print(f"SDH_CAGE::VISUAL::{result.splitlines()[0]}")
    bpy.ops.wm.quit_blender()


def run():
    try:
        if state["phase"] == 0:
            entry = bpy.context.preferences.addons.new()
            entry.module = PACKAGE
            addon = importlib.import_module(PACKAGE)
            addon.register()
            try:
                bpy.ops.wm.splash_close()
            except (AttributeError, RuntimeError):
                pass
            state["entry"] = entry
            state["addon"] = addon

            bpy.ops.object.select_all(action="SELECT")
            bpy.ops.object.delete(use_global=False)
            bpy.ops.mesh.primitive_cube_add()
            obj = bpy.context.object
            obj.name = "Cage Deform Visual QA"
            obj.scale = (0.65, 3.0, 0.65)
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.subdivide(number_cuts=20)
            bpy.ops.object.mode_set(mode="OBJECT")

            deform = importlib.import_module(f"{PACKAGE}.cage_deform")
            modifier, controller, _previous = deform.create_deform_stage(bpy.context, obj)
            properties = controller.sdh_cage_deform
            properties.deform_type = DEFORM_TYPE
            properties.strength = math.radians(
                210.0 if DEFORM_TYPE == "TWIST" else 105.0)
            properties.factor = 0.85
            properties.direction = math.radians(15.0)
            properties.mode = "LIMITED"
            properties.origin = "BOTTOM"
            properties.top_scale = (1.65, 0.7)
            properties.top_offset = (0.45, 0.0)
            properties.bottom_scale = (0.8, 1.15)
            properties.bottom_offset = (-0.15, 0.0)
            properties.show_cage = True
            properties.show_axis_gizmo = DEFORM_TYPE == "BEND"
            properties.show_direction_handle = False
            properties.show_end_handles = True
            properties.show_boundary_handles = True
            deform.sync_controller(controller, pull_transform=False)
            obj.modifiers.active = modifier

            window = bpy.context.window_manager.windows[0]
            area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
            region = next(region for region in area.regions if region.type == "WINDOW")
            space = area.spaces.active
            space.show_region_ui = True
            space.overlay.show_floor = True
            space.overlay.show_axis_x = True
            space.overlay.show_axis_y = True
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.view3d.view_axis(type="FRONT", align_active=False)
                bpy.ops.view3d.view_selected(use_all_regions=False)
                bpy.ops.view3d.view_orbit(type="ORBITRIGHT")
                bpy.ops.view3d.view_orbit(type="ORBITUP")
            state["window"] = window
            state["area"] = area
            state["region"] = region
            state["phase"] = 1
            return 0.8

        if state["phase"] == 1:
            try:
                bpy.ops.wm.splash_close()
            except (AttributeError, RuntimeError):
                pass
            state["phase"] = 2
            return 0.4

        bpy.context.view_layer.update()
        with bpy.context.temp_override(
                window=state["window"], area=state["area"], region=state["region"]):
            bpy.ops.screen.screenshot_area(filepath=str(SCREENSHOT))
        if not SCREENSHOT.exists() or SCREENSHOT.stat().st_size < 1000:
            raise AssertionError("viewport screenshot was not created")
        finish("PASS")
        return None
    except Exception:
        finish("FAIL\n" + traceback.format_exc())
        return None


bpy.app.timers.register(run, first_interval=0.5)
