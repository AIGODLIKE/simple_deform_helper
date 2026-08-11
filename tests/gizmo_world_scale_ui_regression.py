"""Verify Twist and Shear use the same fixed screen scale as Bend."""
from __future__ import annotations

import importlib
import math
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Euler, Vector


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))
SCRIPT_ARGS = sys.argv[sys.argv.index("--") + 1:]
RESULT = Path(SCRIPT_ARGS[0]).resolve()
SCREENSHOT = Path(SCRIPT_ARGS[1]).resolve() if len(SCRIPT_ARGS) > 1 else None

observed = {}
errors = []
attempts = 0
phase = "LARGE"
large_observed = None
settle_remaining = 2


def finish(result):
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(result, encoding="utf-8")
    bpy.ops.wm.quit_blender()
    return None


try:
    addon = importlib.import_module(PACKAGE)
    deform = importlib.import_module(f"{PACKAGE}.cage_deform")
    core = importlib.import_module(f"{PACKAGE}.cage_deform.core")
    gizmos = importlib.import_module(f"{PACKAGE}.cage_deform.gizmos")

    def track_draw(gizmo_class, label, shape_name):
        original = gizmo_class.draw

        def tracked(self, context):
            result = original(self, context)
            if self.hide:
                return result
            try:
                basis = self.matrix_basis
                final = self.matrix_world
                basis_scales = tuple(
                    Vector(basis.to_3x3().col[index]).length
                    for index in range(3))
                final_scales = tuple(
                    Vector(final.to_3x3().col[index]).length
                    for index in range(3))
                center = gizmos._project_world(context, final.translation)
                projected = tuple(
                    gizmos._project_world(context, final @ Vector(vertex))
                    for vertex in gizmos._shape_vertices(shape_name))
                pixel_extent = (
                    max((point - center).length for point in projected
                        if point is not None)
                    if center is not None else -1.0)
                observed[label] = {
                    "basis": basis_scales,
                    "final": final_scales,
                    "pixel_extent": pixel_extent,
                    "draw_scale": bool(self.use_draw_scale),
                    "scale_basis": float(self.scale_basis),
                    "region": (context.region.width, context.region.height),
                    "screen_center": (
                        tuple(center) if center is not None else None),
                }
                if label == "SHEAR" and center is not None:
                    x_end = gizmos._project_world(
                        context,
                        final.translation + Vector(final.to_3x3().col[0]) * 1.12)
                    z_end = gizmos._project_world(
                        context,
                        final.translation + Vector(final.to_3x3().col[1]) * 1.12)
                    if x_end is not None and z_end is not None:
                        observed[label]["x_pick"] = gizmos.shear_drag_axis(
                            context, final, center.lerp(x_end, 0.82))
                        observed[label]["z_pick"] = gizmos.shear_drag_axis(
                            context, final, center.lerp(z_end, 0.82))
            except Exception:
                errors.append(traceback.format_exc())
            return result

        gizmo_class.draw = tracked

    track_draw(gizmos.SDHCageBendStrengthGizmo, "BEND", "STRETCH")
    track_draw(gizmos.SDHCageTwistStrengthGizmo, "TWIST", "TWIST")
    track_draw(gizmos.SDHCageShearGizmo, "SHEAR", "SHEAR")
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon.register()

    bpy.ops.mesh.primitive_cube_add()
    source_object = bpy.context.object
    source_object.name = "Gizmo World Scale Regression"
    source_object.scale = (12.0, 7.0, 9.0)
    if bpy.ops.sdh.add_cage_deform() != {"FINISHED"}:
        raise RuntimeError("could not create the regression cage")
    target, modifier, controller = deform.resolve_context_deform(bpy.context)
    if target is None or modifier is None or controller is None:
        raise RuntimeError("could not resolve the regression cage")
    properties = controller.sdh_cage_deform
    core.set_deform_layers(properties, ("BEND", "TWIST", "SHEAR"), bpy.context)
    properties.twist_strength = math.radians(35.0)
    properties.shear_factors = (0.16, -0.11)
    deform.sync_controller(controller, pull_transform=False)

    window = bpy.context.window_manager.windows[0]
    area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    space = area.spaces.active
    space.region_3d.view_location = Vector((0.0, 0.0, 0.0))
    space.region_3d.view_distance = 38.0
    space.region_3d.view_rotation = Euler((
        math.radians(67.0), 0.0, math.radians(38.0))).to_quaternion()
    area.tag_redraw()

    def verify_after_draw():
        global attempts, phase, large_observed, settle_remaining
        attempts += 1
        if errors:
            return finish("FAIL:\n" + errors[-1])
        if {"BEND", "TWIST", "SHEAR"}.issubset(observed):
            if settle_remaining > 0:
                settle_remaining -= 1
                observed.clear()
                area.tag_redraw()
                return 0.1
            expected_scales = {
                "BEND": gizmos.STRENGTH_ARROW_SCALE,
                "TWIST": gizmos.COMPACT_PARAMETER_SCALE,
                "SHEAR": gizmos.COMPACT_PARAMETER_SCALE,
            }
            for label, sample in observed.items():
                if not sample["draw_scale"]:
                    return finish(f"FAIL: {label} disabled fixed screen scaling")
                if abs(sample["scale_basis"] -
                       expected_scales[label]) > 1.0e-6:
                    return finish(
                        f"FAIL: {label} scale_basis "
                        f"{sample['scale_basis']:.6f} is not fixed")
                if max(abs(value - 1.0)
                       for value in sample["basis"]) > 2.0e-4:
                    return finish(
                        f"FAIL: {label} basis retained cage scale: "
                        f"{sample['basis']!r}")
                if not 8.0 <= sample["pixel_extent"] <= 48.0:
                    return finish(
                        f"FAIL: {label} screen extent "
                        f"{sample['pixel_extent']:.3f}px is not compact")
            bend_extent = observed["BEND"]["pixel_extent"]
            for label in ("TWIST", "SHEAR"):
                ratio = observed[label]["pixel_extent"] / bend_extent
                if not 0.65 <= ratio <= 1.55:
                    return finish(
                        f"FAIL: {label} screen-size ratio to Bend is "
                        f"{ratio:.3f}; observed={observed!r}")
            bend_center = Vector(observed["BEND"]["screen_center"])
            twist_center = Vector(observed["TWIST"]["screen_center"])
            shear_center = Vector(observed["SHEAR"]["screen_center"])
            if twist_center.x - bend_center.x < 90.0:
                return finish(
                    f"FAIL: Bend and Twist remain crowded: {observed!r}")
            if shear_center.x - twist_center.x < 48.0:
                return finish(
                    f"FAIL: Twist and Shear remain crowded: {observed!r}")
            if (
                    observed["SHEAR"].get("x_pick") != "X" or
                    observed["SHEAR"].get("z_pick") != "Z"
            ):
                return finish(
                    f"FAIL: Shear fixed-screen arm picking failed: "
                    f"{observed['SHEAR']!r}")
            if phase == "LARGE":
                large_observed = {
                    label: dict(sample) for label, sample in observed.items()}
                if SCREENSHOT is not None:
                    viewport = next(
                        region for region in area.regions
                        if region.type == "WINDOW")
                    with bpy.context.temp_override(
                            window=window, area=area, region=viewport):
                        bpy.ops.screen.screenshot_area(filepath=str(SCREENSHOT))
                target.scale = (1.0, 7.0 / 12.0, 9.0 / 12.0)
                bpy.context.view_layer.update()
                observed.clear()
                phase = "SMALL"
                settle_remaining = 2
                area.tag_redraw()
                return 0.2
            for label in ("TWIST", "SHEAR"):
                sample = observed[label]
                difference = abs(
                    sample["pixel_extent"] -
                    large_observed[label]["pixel_extent"])
                if difference > 1.5:
                    return finish(
                        f"FAIL: {label} changed by {difference:.3f}px when "
                        f"object scale changed; LARGE={large_observed[label]!r}; "
                        f"SMALL={sample!r}")
            large_separation = (
                Vector(large_observed["SHEAR"]["screen_center"]) -
                Vector(large_observed["TWIST"]["screen_center"])).length
            small_separation = (
                Vector(observed["SHEAR"]["screen_center"]) -
                Vector(observed["TWIST"]["screen_center"])).length
            if abs(large_separation - small_separation) > 2.0:
                return finish(
                    "FAIL: Twist/Shear screen separation changed with scale")
            if SCREENSHOT is not None:
                if not SCREENSHOT.exists() or SCREENSHOT.stat().st_size < 1000:
                    return finish("FAIL: large-scale screenshot was not created")
            return finish(
                f"PASS: LARGE={large_observed!r}; SMALL={observed!r}")
        if attempts >= 60:
            return finish(f"FAIL: Gizmos were not drawn: {observed!r}")
        area.tag_redraw()
        return 0.1

    bpy.app.timers.register(verify_after_draw, first_interval=0.1)
except Exception:
    finish("FAIL:\n" + traceback.format_exc())
