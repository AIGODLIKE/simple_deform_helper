"""Create and screenshot an interactive Curve cage in a real View3D."""
from __future__ import annotations

import importlib
import math
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Euler


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
ARGS = sys.argv[sys.argv.index("--") + 1:]
RESULT = Path(ARGS[0]).resolve()
SCREENSHOT = Path(ARGS[1]).resolve()
sys.path.insert(0, str(SOURCE.parent))


def finish(value):
    RESULT.write_text(value, encoding="utf-8")
    bpy.ops.wm.quit_blender()
    return None


def tube_mesh(name, rings=17, sides=16, length=6.0, radius=0.65):
    vertices = []
    faces = []
    for ring in range(rings):
        z = -length * 0.5 + length * ring / float(rings - 1)
        for side in range(sides):
            angle = math.tau * side / float(sides)
            vertices.append((
                math.cos(angle) * radius,
                math.sin(angle) * radius,
                z,
            ))
    for ring in range(rings - 1):
        for side in range(sides):
            next_side = (side + 1) % sides
            first = ring * sides + side
            second = ring * sides + next_side
            third = (ring + 1) * sides + next_side
            fourth = (ring + 1) * sides + side
            faces.append((first, second, third, fourth))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, (), faces)
    mesh.update()
    return mesh


addon = None
draw_count = 0
attempts = 0

try:
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon = importlib.import_module(PACKAGE)
    addon.register()
    try:
        bpy.ops.wm.splash_close()
    except (AttributeError, RuntimeError):
        pass
    deform = importlib.import_module(f"{PACKAGE}.cage_deform")
    curve = importlib.import_module(f"{PACKAGE}.cage_deform.curve")
    ui = importlib.import_module(f"{PACKAGE}.cage_deform.ui")

    for scene_object in tuple(bpy.context.scene.objects):
        bpy.data.objects.remove(scene_object, do_unlink=True)

    target = bpy.data.objects.new(
        "Curve Cage Visual", tube_mesh("Curve Cage Visual Mesh"))
    bpy.context.collection.objects.link(target)
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, target, cage_type="CURVE")
    properties = controller.sdh_cage_deform
    properties.curve_length_mode = "STRETCH"
    properties.curve_boundary_mode = "EXTEND"
    properties.curve_preserve_volume = True
    properties.curve_range_start = 0.12
    properties.curve_range_end = 0.86
    properties.curve_stations[1].scale = (1.45, 0.72)
    properties.curve_stations[1].offset = (0.18, -0.12)
    guide = curve.curve_guide_object(target, modifier)
    points = guide.data.splines[0].bezier_points
    points[0].co = (-0.25, -3.0, -0.15)
    points[1].co = (1.65, -0.15, 0.35)
    points[2].co = (0.25, 3.0, 1.15)
    points[1].tilt = math.radians(28.0)
    points[2].tilt = math.radians(62.0)
    points[1].radius = 0.82
    points[2].radius = 1.18
    guide.data.update_tag()
    target.modifiers.active = modifier
    deform.sync_controller(controller, pull_transform=False, sync_mode="push")
    deform.core._activate(bpy.context, target)
    deform.core.refresh_controller_display(bpy.context, force=True)

    window = bpy.context.window_manager.windows[0]
    area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    viewport = next(region for region in area.regions if region.type == "WINDOW")
    sidebar = next(region for region in area.regions if region.type == "UI")
    area.spaces.active.show_region_ui = True
    area.spaces.active.overlay.show_relationship_lines = False
    region_3d = area.spaces.active.region_3d
    region_3d.view_location = (0.35, 0.0, 0.15)
    region_3d.view_distance = 9.0
    region_3d.view_rotation = Euler((
        math.radians(66.0),
        0.0,
        math.radians(36.0),
    ), "XYZ").to_quaternion()

    panel_class = ui.SDH_CAGE_PT_deform
    original_draw = panel_class.draw

    def counted_draw(self, context):
        global draw_count
        draw_count += 1
        return original_draw(self, context)

    active_category = sidebar.active_panel_category
    if not active_category or active_category == "UNSUPPORTED":
        active_category = "Item"
    bpy.utils.unregister_class(panel_class)
    panel_class.bl_category = active_category
    panel_class.draw = counted_draw
    bpy.utils.register_class(panel_class)

    bpy.context.preferences.view.show_splash = False
    area.tag_redraw()

    def capture():
        global attempts
        attempts += 1
        if attempts == 1:
            try:
                bpy.ops.wm.splash_close()
            except (AttributeError, RuntimeError):
                pass
            area.tag_redraw()
            return 0.1
        if draw_count and attempts >= 12:
            with bpy.context.temp_override(
                    window=window, area=area, region=viewport):
                bpy.ops.screen.screenshot_area(filepath=str(SCREENSHOT))
            if not SCREENSHOT.exists() or SCREENSHOT.stat().st_size < 1000:
                return finish("FAIL: screenshot was not created")
            return finish("PASS")
        if attempts >= 50:
            return finish(f"FAIL: Curve panel did not draw ({draw_count})")
        area.tag_redraw()
        return 0.1

    bpy.app.timers.register(capture, first_interval=0.1)
except Exception:
    finish("FAIL:\n" + traceback.format_exc())
