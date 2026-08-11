"""Keep the active FFD stage visible while U/V/W topology changes."""

from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
ARGS = sys.argv[sys.argv.index("--") + 1:]
RESULT = Path(ARGS[0]).resolve()
SCREENSHOT = Path(ARGS[1]).resolve() if len(ARGS) > 1 else None
sys.path.insert(0, str(SOURCE.parent))

addon = None
panel_class = None
original_draw = None
draw_count = 0
post_resize_draw_count = 0
resized = False
draw_errors = []


def quit_with(message):
    RESULT.write_text(message, encoding="utf-8")
    bpy.ops.wm.quit_blender()
    return None


try:
    addon = importlib.import_module(PACKAGE)
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon.register()
    deform = importlib.import_module(f"{PACKAGE}.cage_deform")

    bpy.ops.mesh.primitive_cube_add()
    target = bpy.context.object
    if bpy.ops.sdh.add_cage_deform(cage_type="FFD") != {"FINISHED"}:
        raise RuntimeError("could not create FFD stage")
    target, modifier, controller = deform.resolve_context_deform(bpy.context)
    if target is None or modifier is None or controller is None:
        raise RuntimeError("could not resolve the new FFD stage")
    properties = controller.sdh_cage_deform

    window = bpy.context.window_manager.windows[0]
    area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    area.spaces.active.show_region_ui = True
    sidebar = next(region for region in area.regions if region.type == "UI")

    ui_module = importlib.import_module(f"{PACKAGE}.cage_deform.ui")
    panel_class = ui_module.SDH_CAGE_PT_deform
    original_draw = panel_class.draw

    def tracked_draw(self, context):
        global draw_count, post_resize_draw_count
        draw_count += 1
        if resized:
            try:
                resolved = deform.resolve_context_deform(context)
                if resolved != (target, modifier, controller):
                    raise RuntimeError(
                        "sidebar lost the active FFD stage after resolution edit")
                if target.modifiers.active != modifier:
                    raise RuntimeError(
                        "sidebar received the internal Lattice modifier as active")
                post_resize_draw_count += 1
            except Exception:
                draw_errors.append(traceback.format_exc())
                raise
        return original_draw(self, context)

    active_category = sidebar.active_panel_category
    if not active_category or active_category == "UNSUPPORTED":
        active_category = "Item"
    bpy.utils.unregister_class(panel_class)
    panel_class.bl_category = active_category
    panel_class.draw = tracked_draw
    bpy.utils.register_class(panel_class)
    area.tag_redraw()

    sequence = iter((
        ("u", 3), ("u", 4), ("u", 5), ("u", 6),
        ("v", 3), ("v", 4), ("v", 5), ("v", 6),
        ("w", 3), ("w", 4), ("w", 5), ("w", 6),
    ))
    settle_attempts = 0

    def resize_and_verify():
        global resized, settle_attempts
        if draw_errors:
            return quit_with("FAIL:\n" + draw_errors[-1])
        try:
            axis, value = next(sequence)
        except StopIteration:
            settle_attempts += 1
            if post_resize_draw_count >= 3:
                if SCREENSHOT is not None:
                    viewport = next(
                        region for region in area.regions if region.type == "WINDOW")
                    with bpy.context.temp_override(
                            window=window, area=area, region=viewport):
                        bpy.ops.screen.screenshot_area(filepath=str(SCREENSHOT))
                    if not SCREENSHOT.exists() or SCREENSHOT.stat().st_size < 1000:
                        return quit_with("FAIL: screenshot was not created")
                return quit_with(
                    "PASS: FFD U/V/W edits retained the active stage and panel")
            if settle_attempts >= 30:
                return quit_with(
                    "FAIL: sidebar did not redraw after FFD resolution edits "
                    f"(draws={draw_count}, post_resize={post_resize_draw_count})")
            area.tag_redraw()
            return 0.1

        setattr(properties, f"ffd_resolution_{axis}", value)
        resized = True
        if target.modifiers.active != modifier:
            active = target.modifiers.active
            return quit_with(
                "FAIL: active modifier changed to "
                f"{getattr(active, 'type', None)} "
                f"{getattr(active, 'name', None)!r}")
        if deform.resolve_context_deform(bpy.context) != (
                target, modifier, controller):
            return quit_with("FAIL: panel context lost the active FFD stage")
        area.tag_redraw()
        return 0.08

    bpy.app.timers.register(resize_and_verify, first_interval=0.2)
except Exception:
    quit_with("FAIL:\n" + traceback.format_exc())
