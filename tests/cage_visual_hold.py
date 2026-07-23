"""Open a saved, isolated Cage Deform scene for manual viewport QA."""

import importlib
import math
import sys
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
OUTPUT = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
DIAGNOSTICS = Path(sys.argv[sys.argv.index("--") + 2]).resolve()
DEFORM_TYPE = (
    sys.argv[sys.argv.index("--") + 3]
    if len(sys.argv) > sys.argv.index("--") + 3 else "BEND"
)
sys.path.insert(0, str(SOURCE.parent))
state = {}


def build_scene():
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon = importlib.import_module(PACKAGE)
    addon.register()
    try:
        bpy.ops.wm.splash_close()
    except (AttributeError, RuntimeError):
        pass
    bpy.context.preferences.view.language = "zh_HANS"
    bpy.context.preferences.view.use_translate_interface = True
    bpy.context.preferences.view.use_translate_tooltips = True

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_cube_add()
    obj = bpy.context.object
    obj.name = "SDH Cage Deform Visual QA"
    obj.scale = (0.65, 3.0, 0.65)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.subdivide(number_cuts=24)
    bpy.ops.object.mode_set(mode="OBJECT")

    deform = importlib.import_module(f"{PACKAGE}.cage_deform")
    modifier, controller, _previous = deform.create_deform_stage(bpy.context, obj)
    modifier.name = "Cage Deform - Limited"
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

    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT), check_existing=False)
    state["deform"] = deform
    state["object"] = obj
    state["modifier"] = modifier
    state["controller"] = controller
    print(f"SDH_CAGE::VISUAL_HOLD::READY::{OUTPUT}")
    bpy.app.timers.register(write_diagnostics, first_interval=2.0)
    return None


def write_diagnostics():
    deform = state["deform"]
    obj = state["object"]
    target, modifier, controller = deform.resolve_context_deform(
        bpy.context, fallback=False)
    draw = importlib.import_module(f"{PACKAGE}.draw").Draw3D
    lines = (
        f"context_object={getattr(bpy.context.object, 'name', None)!r}",
        f"active_modifier={getattr(obj.modifiers.active, 'name', None)!r}",
        f"resolved_target={getattr(target, 'name', None)!r}",
        f"resolved_modifier={getattr(modifier, 'name', None)!r}",
        f"resolved_controller={getattr(controller, 'name', None)!r}",
        f"expected_modifier={state['modifier'].name!r}",
        f"expected_controller={state['controller'].name!r}",
        f"draw_handles={tuple(draw.G_HandleData)!r}",
        f"draw_error={draw.G_HandleData.get('draw_error')!r}",
    )
    DIAGNOSTICS.write_text("\n".join(lines), encoding="utf-8")
    return 1.0


bpy.app.timers.register(build_scene, first_interval=0.5)
