"""Exercise copied-cage ownership from Blender's read-only Panel.draw()."""
from __future__ import annotations

import importlib
import os
import sys
import traceback
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
INSTALLED_PACKAGE = os.environ.get("SDH_TEST_MODULE")
PACKAGE = INSTALLED_PACKAGE or SOURCE.name
SCRIPT_ARGS = sys.argv[sys.argv.index("--") + 1:]
RESULT = Path(SCRIPT_ARGS[0]).resolve()
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(SOURCE.parent))

addon = None
draw_count = 0
draw_errors = []
attempts = 0


def quit_with(result):
    RESULT.write_text(result, encoding="utf-8")
    bpy.ops.wm.quit_blender()
    return None


try:
    addon = importlib.import_module(PACKAGE)
    cage = importlib.import_module(f"{PACKAGE}.cage_deform")
    core = importlib.import_module(f"{PACKAGE}.cage_deform.core")
    ui = importlib.import_module(f"{PACKAGE}.cage_deform.ui")
    if not INSTALLED_PACKAGE:
        entry = bpy.context.preferences.addons.new()
        entry.module = PACKAGE
        addon.register()

    bpy.ops.mesh.primitive_cube_add()
    if bpy.ops.sdh.add_cage_deform() != {"FINISHED"}:
        raise RuntimeError("could not create source cage")
    source, source_modifier, _controller = cage.resolve_context_deform(
        bpy.context)
    source_uuid = str(source[cage.TARGET_UUID])
    source_group = source_modifier.node_group

    # Ensure the first ownership lookup after duplication comes from a real UI
    # redraw, not the regular selection/dependency-graph maintenance timers.
    core.disable_runtime_handlers()
    duplicate = source.copy()
    duplicate.data = source.data.copy()
    duplicate.name = "SDH Duplicate Draw Context"
    bpy.context.collection.objects.link(duplicate)
    bpy.ops.object.select_all(action="DESELECT")
    duplicate.select_set(True)
    bpy.context.view_layer.objects.active = duplicate
    if str(duplicate[cage.TARGET_UUID]) != source_uuid:
        raise RuntimeError("duplicate did not inherit source ownership")

    window = bpy.context.window_manager.windows[0]
    area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    area.spaces.active.show_region_ui = True
    sidebar = next(region for region in area.regions if region.type == "UI")
    panel_class = ui.SDH_CAGE_PT_deform
    original_draw = panel_class.draw

    def counted_draw(self, context):
        global draw_count
        draw_count += 1
        try:
            return original_draw(self, context)
        except Exception:
            draw_errors.append(traceback.format_exc())
            raise

    active_category = sidebar.active_panel_category
    if not active_category or active_category == "UNSUPPORTED":
        active_category = "Item"
    bpy.utils.unregister_class(panel_class)
    panel_class.bl_category = active_category
    panel_class.draw = counted_draw
    bpy.utils.register_class(panel_class)
    area.tag_redraw()

    def finish_after_draw():
        global attempts
        attempts += 1
        if draw_errors:
            return quit_with("FAIL:\n" + draw_errors[-1])
        stages = cage.cage_modifiers(duplicate)
        duplicate_uuid = str(duplicate.get(cage.TARGET_UUID, ""))
        copied_modifier = stages[0] if stages else None
        copied_controller = (
            cage.find_controller(duplicate, copied_modifier)
            if copied_modifier is not None and duplicate_uuid != source_uuid
            else None
        )
        if draw_count and copied_controller is not None:
            if str(source[cage.TARGET_UUID]) != source_uuid:
                return quit_with("FAIL: source ownership UUID changed")
            if copied_controller.parent != duplicate:
                return quit_with("FAIL: copied controller has the wrong parent")
            if copied_modifier.node_group == source_group:
                return quit_with("FAIL: copied stage still shares its node group")
            return quit_with("PASS")
        if attempts >= 60:
            return quit_with(
                "FAIL: deferred ownership repair did not finish "
                f"(draws={draw_count}, uuid={duplicate_uuid!r}, "
                f"pending={core.target_ownership_repair_pending(duplicate)})")
        area.tag_redraw()
        return 0.1

    bpy.app.timers.register(finish_after_draw, first_interval=0.1)
except Exception:
    quit_with("FAIL:\n" + traceback.format_exc())
