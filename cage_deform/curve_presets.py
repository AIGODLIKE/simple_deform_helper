"""Parametric guide presets for managed Curve cages."""
from __future__ import annotations

import math

from bpy.app.translations import pgettext_iface as iface_
from bpy.props import EnumProperty
from bpy.types import Operator


CURVE_PRESET_ITEMS = (
    ("STRAIGHT", "Straight", "Create a straight guide along the cage axis"),
    ("WAVE", "Wave", "Create a two-plane flowing wave guide"),
    ("SINE", "Sine", "Create a planar sine-wave guide"),
    ("HELIX", "Helix", "Create a helical guide around the cage axis"),
)


def _preset_coordinate(preset, factor, half_length, amplitude, cycles, phase):
    y = -half_length + half_length * 2.0 * factor
    angle = phase + math.tau * cycles * factor
    if preset == "SINE":
        return amplitude * math.sin(angle), y, 0.0
    if preset == "WAVE":
        return (
            amplitude * math.sin(angle),
            y,
            amplitude * 0.35 * math.sin(angle * 2.0),
        )
    if preset == "HELIX":
        return amplitude * math.cos(angle), y, amplitude * math.sin(angle)
    return 0.0, y, 0.0


def apply_curve_preset(
        guide, properties, preset, *, amplitude=None, cycles=None,
        phase=None, point_count=None):
    """Replace one managed guide with an editable parametric Bezier preset."""
    from . import curve

    data = getattr(guide, "data", None)
    if data is None:
        return False
    preset = str(preset or "STRAIGHT").upper()
    identifiers = {item[0] for item in CURVE_PRESET_ITEMS}
    if preset not in identifiers:
        preset = "STRAIGHT"
    amplitude = max(float(
        getattr(properties, "curve_preset_amplitude", 0.5)
        if amplitude is None else amplitude), 0.0)
    cycles = max(float(
        getattr(properties, "curve_preset_cycles", 1.0)
        if cycles is None else cycles), 0.01)
    phase = float(
        getattr(properties, "curve_preset_phase", 0.0)
        if phase is None else phase)
    point_count = min(max(int(
        getattr(properties, "curve_preset_points", 9)
        if point_count is None else point_count), 3), curve.CURVE_POINT_MAXIMUM)
    if preset == "STRAIGHT":
        point_count = 3

    spline = (
        data.splines[0]
        if (
            len(data.splines) == 1 and
            data.splines[0].type == "BEZIER" and
            len(data.splines[0].bezier_points) == point_count
        ) else None
    )
    if spline is None:
        data.splines.clear()
        spline = data.splines.new("BEZIER")
        spline.bezier_points.add(point_count - 1)
    half_length = max(abs(float(properties.size[1])) * 0.5, 1.0e-5)
    for index, point in enumerate(spline.bezier_points):
        factor = index / float(max(point_count - 1, 1))
        point.co = _preset_coordinate(
            preset, factor, half_length, amplitude, cycles, phase)
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"
        point.tilt = 0.0
        point.radius = 1.0
        point.select_control_point = False
        point.select_left_handle = False
        point.select_right_handle = False
    spline.use_cyclic_u = False
    data.update_tag()

    controller = getattr(properties, "id_data", None)
    pointer = curve._pointer(controller)
    syncing = getattr(curve._core(), "_SYNCING", set())
    if pointer:
        syncing.add(pointer)
    try:
        properties.curve_closed = False
        properties.curve_active_point = 0
    finally:
        if pointer:
            syncing.discard(pointer)
    curve.ensure_curve_point_collection(
        properties, guide, reset=len(properties.curve_points) != point_count)
    curve.apply_all_curve_point_handles(controller)
    target = curve._core().find_target(controller)
    if target is not None:
        target.update_tag()
    curve.sync_curve_cage_relation(controller, force=True)
    curve._core().sync_controller(
        controller, pull_transform=False, sync_mode="push")
    return True


def resample_stations_by_arc_length(guide, properties):
    """Distribute the existing stations evenly by guide arc length."""
    from . import curve

    spline = curve.curve_guide_spline(guide)
    stations = getattr(properties, "curve_stations", None)
    if spline is None or stations is None or len(stations) < 2:
        return False
    resolution = max(
        int(getattr(properties, "curve_resolution", 24)) * 4, 64)
    samples, total_length = curve._local_curve_samples(spline, resolution)
    if len(samples) < 2 or total_length <= 1.0e-9:
        return False
    distances = tuple(item[0] for item in samples)
    last_index = len(samples) - 1
    # Keep each station's identity (scale/offset/radius/twist) while its
    # position becomes arc-length even, ordered along the current guide.
    order = sorted(
        range(len(stations)),
        key=lambda index: float(stations[index].factor))
    from bisect import bisect_right
    for rank, station_index in enumerate(order):
        goal = total_length * rank / float(len(order) - 1)
        segment = min(max(
            bisect_right(distances, goal) - 1, 0), last_index - 1)
        span = max(float(distances[segment + 1] - distances[segment]), 1.0e-9)
        parameter = (
            segment + (goal - float(distances[segment])) / span
        ) / float(last_index)
        stations[station_index].factor = min(max(parameter, 0.0), 1.0)
    return True


class SDH_OT_resample_curve_stations(Operator):
    bl_idname = "sdh.resample_curve_stations"
    bl_label = "Even Stations by Arc Length"
    bl_description = (
        "Redistribute the existing cross-section stations evenly along the "
        "guide's arc length")
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        from . import core

        _target, modifier, controller = core.resolve_context_deform(context)
        properties = getattr(controller, "sdh_cage_deform", None)
        return bool(
            modifier is not None and properties is not None and
            str(properties.cage_type) == "CURVE" and
            len(getattr(properties, "curve_stations", ())) >= 2)

    def execute(self, context):
        from . import core, curve

        target, modifier, controller = core.resolve_context_deform(context)
        properties = getattr(controller, "sdh_cage_deform", None)
        if properties is None:
            return {"CANCELLED"}
        guide = curve.curve_guide_object(target, modifier)
        if guide is None:
            return {"CANCELLED"}
        if not resample_stations_by_arc_length(guide, properties):
            return {"CANCELLED"}
        core.sync_controller(
            controller, pull_transform=False, sync_mode="push")
        if context.area:
            context.area.tag_redraw()
        self.report(
            {"INFO"},
            iface_("Stations redistributed by arc length"),
        )
        return {"FINISHED"}


class SDH_OT_apply_curve_preset(Operator):
    bl_idname = "sdh.apply_curve_preset"
    bl_label = "Apply Curve Preset"
    bl_description = (
        "Replace the managed guide with the selected editable Curve preset")
    bl_options = {"REGISTER", "UNDO"}

    preset: EnumProperty(
        name="Preset",
        items=CURVE_PRESET_ITEMS,
        default="STRAIGHT",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        from . import core

        target, modifier, controller = core.resolve_context_deform(context)
        properties = getattr(controller, "sdh_cage_deform", None)
        return bool(
            target is not None and modifier is not None and
            properties is not None and str(properties.cage_type) == "CURVE")

    def execute(self, context):
        from . import core, curve

        target, modifier, controller = core.resolve_context_deform(context)
        properties = getattr(controller, "sdh_cage_deform", None)
        guide = curve.curve_guide_object(target, modifier)
        if properties is None or guide is None:
            return {"CANCELLED"}
        if curve._curve_data_has_point_animation(guide.data):
            self.report({"WARNING"}, iface_(
                "Remove guide shape keys, drivers, NLA, or point animation "
                "before applying a preset"))
            return {"CANCELLED"}
        preset = str(self.preset)
        if not apply_curve_preset(guide, properties, preset):
            return {"CANCELLED"}
        core.refresh_controller_display(context, force=True)
        label = dict((identifier, name) for identifier, name, _description in
                     CURVE_PRESET_ITEMS).get(preset, preset.title())
        self.report(
            {"INFO"}, iface_("Applied {preset} Curve preset").format(
                preset=iface_(label)))
        return {"FINISHED"}


classes = (
    SDH_OT_apply_curve_preset,
    SDH_OT_resample_curve_stations,
)
