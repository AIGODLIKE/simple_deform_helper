"""Exercise real FFD point/line/face gizmo drawing in a VIEW_3D area."""
from __future__ import annotations

import importlib
import os
import statistics
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

import bpy

SOURCE = Path(os.environ.get(
    "SDH_TEST_SOURCE", Path(__file__).resolve().parents[1])).resolve()
arguments = sys.argv[sys.argv.index("--") + 1:]
RESULT = Path(arguments[0]).resolve()
SCREENSHOT = Path(arguments[1]).resolve() if len(arguments) > 1 else None
sys.path.insert(0, str(SOURCE.parent))

addon = None
updates = {"LINE": 0, "FACE": 0, "POINT": 0}
batched = {"LINE": 0, "FACE": 0}
errors = []
instances = []
injected = set()
draw_calls = 0
draw_times_ms = []
cache_result = None


def finish(value):
    RESULT.write_text(value, encoding="utf-8")
    bpy.ops.wm.quit_blender()
    return None


try:
    package = SOURCE.name
    entry = bpy.context.preferences.addons.new()
    entry.module = package
    addon = importlib.import_module(package)
    cage = importlib.import_module(f"{package}.cage_deform")
    gizmo_module = importlib.import_module(f"{package}.cage_deform.gizmos")
    gizmo_class = gizmo_module.SDHCageFFDAggregateGizmo
    original_setup = gizmo_class.setup
    original_update = gizmo_class._update_matrix
    original_draw = gizmo_class.draw

    def tracked_setup(self):
        original_setup(self)
        instances.append(self)

    def tracked_update(self, context):
        try:
            result = original_update(self, context)
            if result and not self.hide:
                mode = str(getattr(self, "selection_mode", "POINT"))
                updates[mode] = updates.get(mode, 0) + 1
            return result
        except Exception as error:
            errors.append(repr(error))
            return False

    def tracked_draw(self, context):
        global draw_calls
        started = time.perf_counter()
        try:
            entities = tuple(getattr(self, "ffd_entities", ()))
            if len(entities) > 1 and id(self) not in injected:
                self.picked_entity = entities[-1]
                self._set_entity(self.picked_entity)
                injected.add(id(self))
            result = original_draw(self, context)
            for mode, count in getattr(
                    self, "last_batch_counts", {}).items():
                batched[mode] = max(batched.get(mode, 0), int(count))
            draw_calls += 1
            if entities:
                expected = (
                    self.picked_entity
                    if self.picked_entity in entities else entities[0])
                current = (
                    int(self.corner_index), str(self.selection_mode),
                    str(self.selection_axis))
                if current != expected:
                    errors.append(
                        f"aggregate state drifted: {current!r} != {expected!r}")
            return result
        except Exception as error:
            errors.append(repr(error))
            return None
        finally:
            draw_times_ms.append((time.perf_counter() - started) * 1000.0)

    gizmo_class.setup = tracked_setup
    gizmo_class._update_matrix = tracked_update
    gizmo_class.draw = tracked_draw
    addon.register()
    bpy.ops.mesh.primitive_cube_add()
    if bpy.ops.sdh.add_cage_deform(cage_type="FFD") != {"FINISHED"}:
        raise RuntimeError("could not create FFD cage")
    target, _modifier, controller = cage.resolve_context_deform(bpy.context)
    if target is None or controller is None:
        raise RuntimeError("could not resolve FFD cage")
    properties = controller.sdh_cage_deform
    properties.ffd_resolution_u = 6
    properties.ffd_resolution_v = 6
    properties.ffd_resolution_w = 6
    properties.ffd_selection_modes = {"POINT", "LINE", "FACE"}
    properties.show_ffd_handles = True
    cage.sync_controller(controller, pull_transform=False)
    window = bpy.context.window_manager.windows[0]
    area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    region = next(region for region in area.regions if region.type == "WINDOW")
    space = area.spaces.active
    area.tag_redraw()
    attempts = 0

    def verify_cache_and_invoke():
        from bpy_extras import view3d_utils

        if not instances:
            raise RuntimeError("aggregate FFD Gizmo was not created")
        handle = instances[0]
        with bpy.context.temp_override(
                window=window, area=area, region=region, space_data=space):
            world = gizmo_module.ffd_point_world(target, controller, 0)
            screen = view3d_utils.location_3d_to_region_2d(
                region, space.region_3d, world)
            if screen is None:
                raise RuntimeError("FFD point is outside the viewport")
            before = gizmo_module._ffd_projected_entity_cache_info()
            location = (int(round(screen.x)), int(round(screen.y)))
            if handle.test_select(bpy.context, location) != 0:
                raise RuntimeError("aggregate FFD hit test missed a visible point")
            if handle.test_select(bpy.context, location) != 0:
                raise RuntimeError("cached aggregate FFD hit test missed")

            projected = {}

            def project_point(index):
                if index not in projected:
                    point_world = gizmo_module.ffd_point_world(
                        target, controller, index)
                    point_screen = view3d_utils.location_3d_to_region_2d(
                        region, space.region_3d, point_world)
                    if point_screen is None:
                        projected[index] = None
                    else:
                        depth = -float(
                            (space.region_3d.view_matrix @ point_world).z)
                        projected[index] = (
                            float(point_screen.x), float(point_screen.y), depth)
                return projected[index]

            boxed, _active, _mode = cage.core.ffd_box_selection_indices(
                properties,
                project_point,
                (screen.x - 4.0, screen.x + 4.0,
                 screen.y - 4.0, screen.y + 4.0),
            )
            if not boxed:
                raise RuntimeError("FFD box selection missed the cached point")
            after = gizmo_module._ffd_projected_entity_cache_info()
            if after["hits"] - before["hits"] < 2:
                raise RuntimeError(
                    f"hit and box paths did not reuse the screen cache: "
                    f"{before!r} -> {after!r}")

            picked = tuple(handle.picked_entity)
            handle._set_entity(handle.ffd_entities[-1])
            captured = {}
            original_invoke = gizmo_module.SDHCageFFDCornerGizmo.invoke

            def probe_invoke(self, _context, _event):
                captured["entity"] = (
                    int(self.corner_index), str(self.selection_mode),
                    str(self.selection_axis))
                return {"FINISHED"}

            try:
                gizmo_module.SDHCageFFDCornerGizmo.invoke = probe_invoke
                result = handle.invoke(
                    bpy.context,
                    SimpleNamespace(
                        mouse_region_x=location[0], mouse_region_y=location[1],
                        shift=False, ctrl=False, alt=False),
                )
            finally:
                gizmo_module.SDHCageFFDCornerGizmo.invoke = original_invoke
            if result != {"FINISHED"} or captured.get("entity") != picked:
                raise RuntimeError(
                    f"aggregate invoke did not restore picked entity: "
                    f"{captured!r}, expected {picked!r}")
            line_entity = next(
                entity for entity in handle.ffd_entities
                if str(entity[1]) == "LINE")
            line_group = tuple(cage.core.ffd_selection_indices(
                properties,
                int(line_entity[0]),
                "LINE",
                axis=str(line_entity[2]),
            ))
            cage.core.ffd_set_selection(properties, (), active=0)
            idle_color = handle._entity_color(
                properties, line_entity, line_group, False)
            hover_color = handle._entity_color(
                properties, line_entity, line_group, True)
            cage.core.ffd_set_selection(
                properties, line_group, active=int(line_entity[0]))
            selected_color = handle._entity_color(
                properties, line_entity, line_group, False)
            if len({idle_color, hover_color, selected_color}) != 3:
                raise RuntimeError(
                    "FFD line hover/selected palettes are not distinct")
            return after

    def check():
        global attempts, cache_result
        attempts += 1
        if errors:
            return finish("FAIL: " + "; ".join(errors))
        if (
                draw_calls and
                updates["POINT"] and
                all(batched[mode] for mode in ("LINE", "FACE")) and
                cache_result is None
        ):
            try:
                cache_result = verify_cache_and_invoke()
            except Exception as error:
                errors.append(repr(error))
                return 0.0
        if cache_result is not None and draw_calls < 6:
            area.tag_redraw()
            return 0.05
        if cache_result is not None:
            steady_draw_times = draw_times_ms[1:] or draw_times_ms
            if SCREENSHOT is not None:
                with bpy.context.temp_override(
                        window=window, area=area, region=region,
                        space_data=space):
                    bpy.ops.screen.screenshot_area(filepath=str(SCREENSHOT))
                if not SCREENSHOT.exists():
                    return finish("FAIL: FFD screenshot was not created")
            return finish(
                f"PASS::point={updates['POINT']}::line={batched['LINE']}::"
                f"face={batched['FACE']}::"
                f"aggregate={len(instances)}::"
                f"cache_hits={cache_result['hits']}::"
                f"draw_ms={statistics.median(steady_draw_times):.3f}"
            )
        if attempts >= 60:
            return finish(f"FAIL: incomplete gizmo draw {updates!r}")
        area.tag_redraw()
        return 0.1

    bpy.app.timers.register(check, first_interval=0.1)
except Exception:
    finish("FAIL:\n" + traceback.format_exc())
