"""Create a visible chained-cylinder viewport for computer-vision QA."""

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
ORIGINS = tuple(
    value.strip().upper()
    for value in (
        sys.argv[sys.argv.index("--") + 3]
        if len(sys.argv) > sys.argv.index("--") + 3
        else "BOTTOM,TOP,CENTER"
    ).split(",")
)
GAP = float(
    sys.argv[sys.argv.index("--") + 4]
    if len(sys.argv) > sys.argv.index("--") + 4
    else 0.0
)
SCALED_SEAMS = bool(int(
    sys.argv[sys.argv.index("--") + 5]
    if len(sys.argv) > sys.argv.index("--") + 5
    else "0"
))
sys.path.insert(0, str(SOURCE.parent))
state = {"phase": 0}


def finish(result):
    RESULT.write_text(result, encoding="utf-8")
    print(f"SDH_CHAIN::VISUAL::{result.splitlines()[0]}")
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
            bpy.ops.object.select_all(action="SELECT")
            bpy.ops.object.delete(use_global=False)

            bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.65, depth=6.0)
            target = bpy.context.object
            target.name = "SDH Chain Visual QA"
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.subdivide(number_cuts=36)
            bpy.ops.object.mode_set(mode="OBJECT")
            deform = importlib.import_module(f"{PACKAGE}.cage_deform")
            result = bpy.ops.sdh.add_cage_chain(
                count=3, connection_mode="CHAINED", gap=GAP,
                auto_reconnect=True, sync_shared_end_scale=True,
                alignment="POS_Z", origin=ORIGINS[0],
            )
            if result != {"FINISHED"}:
                raise AssertionError("chain creation failed")
            stages = deform.chain.chain_stages(target)
            controllers = tuple(deform.find_controller(target, item) for item in stages)
            if len(ORIGINS) != len(controllers):
                raise AssertionError(
                    f"expected {len(controllers)} origins, got {ORIGINS!r}")
            for controller, origin in zip(controllers, ORIGINS):
                properties = controller.sdh_cage_deform
                properties.origin = origin
                properties.bend_strength = math.radians(45.0)
                properties.bend_direction = 0.0
                properties.show_other_cages = True
                deform.sync_controller(controller, pull_transform=False)
            if SCALED_SEAMS:
                controllers[0].sdh_cage_deform.top_scale = (1.45, 0.75)
                controllers[1].sdh_cage_deform.top_scale = (0.85, 1.35)
                controllers[2].sdh_cage_deform.top_scale = (0.85, 1.35)
            deform.core.flush_pending_chain_updates(target)
            target.modifiers.active = stages[0]
            target.select_set(True)
            bpy.context.view_layer.objects.active = target
            deform.core.refresh_controller_display(bpy.context, force=True)

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
            try:
                bpy.ops.wm.splash_close()
            except (AttributeError, RuntimeError):
                pass
            for window in tuple(bpy.context.window_manager.windows):
                event_simulate = getattr(window, "event_simulate", None)
                if event_simulate is not None:
                    event_simulate(type="ESC", value="PRESS")
            state["phase"] = 2
            return 0.5

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
