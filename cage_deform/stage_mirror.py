"""Mirrored duplication of a cage stage across a target-local axis.

The duplicated controller transform is conjugated by the target-local
mirror ``M`` together with a fixed cage-local X reflection ``S``:
``C' = M @ C @ S`` keeps the controller a proper rotation while the
stage's local parameters are reflected across the cage-local X axis, so
the composition reproduces an exact world-space mirror of the original
deformation: ``D' = M ∘ D ∘ M``.
"""
from __future__ import annotations

import math

import bpy
from bpy.app.translations import pgettext_iface as iface_
from bpy.props import EnumProperty
from bpy.types import Operator
from mathutils import Matrix, Vector

from . import core


def _wrap_angle(value):
    return (float(value) + math.pi) % math.tau - math.pi


def _stage_has_animation(target, modifier, controller):
    """Reject current-frame-only mirrors until F-Curves can be transformed."""
    owners = [controller]
    try:
        lattice = core.ffd_lattice_object(target, modifier)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        lattice = None
    if lattice is not None:
        owners.extend((lattice, getattr(lattice, "data", None)))
    try:
        from . import curve
        guide = curve.curve_guide_object(target, modifier)
        if guide is not None:
            owners.extend((guide, getattr(guide, "data", None)))
    except (ImportError, AttributeError, ReferenceError, RuntimeError,
            TypeError):
        pass
    return any(core._animation_paths(owner) for owner in owners if owner)


def _mirror_ffd_points(properties):
    """Reflect the FFD point grid across the cage-local X (U) axis."""
    core.ensure_ffd_point_collection(properties)
    resolution = core.ffd_resolution(properties)
    points_u, points_v, points_w = resolution
    points = properties.ffd_points
    if len(points) != points_u * points_v * points_w:
        return
    snapshot = tuple(
        (tuple(point.offset), float(point.influence), bool(point.selected))
        for point in points
    )

    def index_of(u, v, w):
        return w * points_u * points_v + v * points_u + u

    for w in range(points_w):
        for v in range(points_v):
            for u in range(points_u):
                offset, influence, selected = snapshot[
                    index_of(points_u - 1 - u, v, w)]
                point = points[index_of(u, v, w)]
                point.offset = (-offset[0], offset[1], offset[2])
                point.influence = influence
                point.selected = selected


def _mirror_legacy_ffd_offsets(properties):
    """Reflect the legacy eight-corner FFD offsets across local X."""
    values = tuple(float(value) for value in properties.ffd_offsets)
    if len(values) != len(core.FFD_CORNERS) * 3:
        return
    corners = [values[index * 3:index * 3 + 3]
               for index in range(len(core.FFD_CORNERS))]
    swap = {0: 1, 1: 0, 2: 3, 3: 2, 4: 5, 5: 4, 6: 7, 7: 6}
    mirrored = []
    for index in range(len(corners)):
        source = corners[swap[index]]
        mirrored.extend((-source[0], source[1], source[2]))
    properties.ffd_offsets = tuple(mirrored)


def _mirror_curve_guide(target, modifier, controller, properties, report):
    """Reflect the managed guide (and rest guide) across cage-local X."""
    try:
        from . import curve
    except ImportError:
        return
    guide = curve.curve_guide_object(target, modifier)
    if guide is None or getattr(guide, "data", None) is None:
        return
    if curve._curve_data_has_point_animation(guide.data):
        if report is not None:
            report(
                {"WARNING"},
                iface_(
                    "Guide point animation is not mirrored; remove it and "
                    "mirror again for an exact result"),
            )
        return
    rest = curve.curve_rest_guide_object(target, modifier)
    for holder in (guide, rest):
        data = getattr(holder, "data", None)
        if data is None:
            continue
        for spline in data.splines:
            for point in getattr(spline, "bezier_points", ()):
                co = point.co
                point.co = (-co.x, co.y, co.z)
                left = point.handle_left
                point.handle_left = (-left.x, left.y, left.z)
                right = point.handle_right
                point.handle_right = (-right.x, right.y, right.z)
                point.tilt = -float(point.tilt)
            for point in getattr(spline, "points", ()):
                co = point.co
                point.co = (-co[0], co[1], co[2], co[3])
                point.tilt = -float(point.tilt)
        data.update_tag()
    try:
        curve.ensure_curve_point_collection(properties, guide, reset=False)
        curve.apply_all_curve_point_handles(controller)
        curve.sync_curve_cage_relation(controller, force=True)
    except (AttributeError, ReferenceError, RuntimeError, TypeError,
            ValueError):
        pass


def mirror_stage_in_place(
        target, modifier, controller, axis="X", report=None):
    """Reflect one duplicated stage across a target-local axis."""
    properties = controller.sdh_cage_deform
    axis_index = {"X": 0, "Y": 1, "Z": 2}.get(str(axis).upper(), 0)
    mirror = Matrix.Identity(3)
    mirror[axis_index][axis_index] = -1.0
    local_reflection = Matrix.Identity(3)
    local_reflection[0][0] = -1.0

    pointer = core._pointer(controller)
    core._SYNCING.add(pointer)
    try:
        location = mirror @ Vector(controller.location)
        rotation = core._controller_rotation_xyz(controller).to_matrix()
        mirrored_rotation = mirror @ rotation @ local_reflection
        try:
            controller.rotation_mode = "XYZ"
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            pass
        controller.location = location
        controller.rotation_euler = mirrored_rotation.to_euler("XYZ")

        properties.bend_direction = _wrap_angle(
            math.pi - float(properties.bend_direction))
        properties.direction = _wrap_angle(
            math.pi - float(properties.direction))
        properties.twist_strength = -float(properties.twist_strength)
        shear = tuple(float(value) for value in properties.shear_factors)
        if len(shear) >= 2:
            properties.shear_factors = (-shear[0], shear[1])
        # End-shape offsets are 2D (cage-local X, Y) vectors.
        top_offset = tuple(float(value) for value in properties.top_offset)
        properties.top_offset = (-top_offset[0], top_offset[1])
        bottom_offset = tuple(
            float(value) for value in properties.bottom_offset)
        properties.bottom_offset = (-bottom_offset[0], bottom_offset[1])
        properties.curve_global_twist = -float(properties.curve_global_twist)
        _mirror_legacy_ffd_offsets(properties)
        if str(getattr(properties, "cage_type", "STANDARD")) == "FFD":
            _mirror_ffd_points(properties)
        for station in getattr(properties, "curve_stations", ()):
            offset = tuple(float(value) for value in station.offset)
            if len(offset) >= 2:
                station.offset = (-offset[0], offset[1])
            station.twist = -float(station.twist)
    finally:
        core._SYNCING.discard(pointer)

    if str(getattr(properties, "cage_type", "STANDARD")) == "CURVE":
        _mirror_curve_guide(target, modifier, controller, properties, report)
    core.sync_controller(controller, pull_transform=False, sync_mode="push")


class SDH_OT_mirror_cage_deform(Operator):
    bl_idname = "sdh.mirror_cage_deform"
    bl_label = "Mirror Cage Stage"
    bl_description = (
        "Duplicate this cage stage mirrored across a target-local axis"
    )
    bl_options = {"REGISTER", "UNDO"}

    axis: EnumProperty(
        name="Mirror Axis",
        description="Target-local axis to mirror across",
        items=(
            ("X", "X", "Mirror across the target-local X axis"),
            ("Y", "Y", "Mirror across the target-local Y axis"),
            ("Z", "Z", "Mirror across the target-local Z axis"),
        ),
        default="X",
    )

    @classmethod
    def poll(cls, context):
        return bool(core.resolve_context_deform(context)[1])

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self, width=280)

    def draw(self, _context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "axis", expand=True)

    def execute(self, context):
        target, source_modifier, source_controller = (
            core.resolve_context_deform(context))
        if target is None or source_modifier is None or (
                source_controller is None):
            return {"CANCELLED"}
        if _stage_has_animation(target, source_modifier, source_controller):
            self.report(
                {"ERROR"},
                iface_(
                    "Animated stages cannot be mirrored yet; bake or remove "
                    "their animation first"),
            )
            return {"CANCELLED"}
        modifier, controller, _previous = core.create_deform_stage(
            context, target, name=f"{source_modifier.name} Mirror",
            after_modifier=source_modifier)
        core._copy_controller_state(controller, source_controller)
        try:
            from .curve import copy_curve_state
            if str(controller.sdh_cage_deform.cage_type) == "CURVE":
                copy_curve_state(
                    target, source_modifier, source_controller,
                    modifier, controller)
        except (AttributeError, ImportError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            pass
        core.ensure_ffd_companion_order(target)
        mirror_stage_in_place(
            target, modifier, controller, self.axis, self.report)
        target.modifiers.active = modifier
        core._activate(context, controller)
        core.refresh_controller_display(context)
        self.report(
            {"INFO"},
            iface_("Mirrored cage stage across {axis}").format(
                axis=self.axis),
        )
        return {"FINISHED"}


classes = (SDH_OT_mirror_cage_deform,)
