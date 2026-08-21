"""Managed guide and cross-section data for the Curve cage."""
from __future__ import annotations

from bisect import bisect_right
import math
import time
import uuid

import bpy
from bpy.app.translations import pgettext_iface as iface_
from bpy.props import (
    BoolProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Gizmo, GizmoGroup, Operator, PropertyGroup, UIList
from mathutils import Matrix, Vector

from ..utils import move_object_to_control_collection, set_helper_object_visible
from . import undo as _undo
from .viewport import draw_gizmo_custom_shape as draw_cage_custom_shape


CURVE_GUIDE_MARKER = "_sdh_curve_cage_guide"
CURVE_REST_GUIDE_MARKER = "_sdh_curve_cage_rest_guide"
CURVE_STATION_MARKER = "_sdh_curve_cage_stations"
CURVE_HELPER_MODIFIER_UUID = "_sdh_curve_cage_modifier_uuid"
CURVE_GUIDE_NAME = "_sdh_curve_cage_guide_name"
CURVE_REST_GUIDE_NAME = "_sdh_curve_cage_rest_guide_name"
CURVE_STATION_NAME = "_sdh_curve_cage_station_name"
CURVE_SCALE_ATTRIBUTE = "sdh_scale"
CURVE_OFFSET_ATTRIBUTE = "sdh_offset"
CURVE_RADIUS_ATTRIBUTE = "sdh_radius"
CURVE_TWIST_ATTRIBUTE = "sdh_twist"
CURVE_STATION_MINIMUM = 2
CURVE_STATION_MAXIMUM = 64
CURVE_POINT_MINIMUM = 2
CURVE_POINT_MAXIMUM = 128
CURVE_MODE_TO_BOUNDARY = {
    "LIMITED": "CLAMP",
    "WITHIN_BOX": "CAGE_ONLY",
    "UNLIMITED": "EXTEND",
}
CURVE_BOUNDARY_TO_MODE = {
    value: key for key, value in CURVE_MODE_TO_BOUNDARY.items()
}

_STATION_SYNC_GUARD = set()
_POINT_SYNC_GUARD = set()
_PREVIEW_SAMPLE_CACHE = {}
_PREVIEW_SAMPLE_CACHE_LIMIT = 32
_LATEST_PREVIEW_STATE = {}
_CURVE_MODAL_OPERATORS = []
_CURVE_DRAW_HANDLERS = []
_CURVE_RELATION_QUEUE = {}
_CURVE_RELATION_GUARD = set()
_CURVE_RELATION_SNAPSHOTS = {}


def _core():
    from . import core
    return core


def _pointer(value):
    try:
        return int(value.as_pointer())
    except (AttributeError, ReferenceError, TypeError, ValueError):
        return 0


def is_curve_helper(obj):
    if obj is None:
        return False
    try:
        return bool(
            obj.get(CURVE_GUIDE_MARKER, False) or
            obj.get(CURVE_REST_GUIDE_MARKER, False) or
            obj.get(CURVE_STATION_MARKER, False)
        )
    except (AttributeError, ReferenceError, TypeError):
        return False


def is_curve_guide(obj):
    try:
        return bool(obj and obj.get(CURVE_GUIDE_MARKER, False))
    except (AttributeError, ReferenceError, TypeError):
        return False


def target_from_helper(obj):
    if not is_curve_helper(obj):
        return None
    target = getattr(obj, "parent", None)
    if target is None or _core().is_cage_controller(target):
        return None
    return target


def modifier_from_helper(obj):
    target = target_from_helper(obj)
    if target is None:
        return None
    modifier_uuid = str(obj.get(CURVE_HELPER_MODIFIER_UUID, "") or "")
    return next((
        modifier for modifier in _core().cage_modifiers(target)
        if _core().cage_modifier_uuid(modifier) == modifier_uuid
    ), None)


def context_deform_from_helper(obj):
    target = target_from_helper(obj)
    modifier = modifier_from_helper(obj)
    controller = (
        _core().find_controller(target, modifier)
        if target is not None and modifier is not None else None
    )
    return target, modifier, controller


def _data_objects():
    try:
        return tuple(bpy.data.objects)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return ()


def controller_from_uuid(identifier):
    """Resolve a cage controller by its stable ownership UUID."""
    identifier = str(identifier or "")
    if not identifier:
        return None
    return next((
        obj for obj in _data_objects()
        if (
            _core().is_cage_controller(obj) and
            str(obj.get(_core().CONTROLLER_UUID, "")) == identifier
        )
    ), None)


def _helper_for_modifier(target, modifier, marker, group_key):
    if target is None or modifier is None:
        return None
    modifier_uuid = _core().cage_modifier_uuid(modifier)
    group = getattr(modifier, "node_group", None)
    stored_name = str(group.get(group_key, "") or "") if group else ""
    stored = bpy.data.objects.get(stored_name) if stored_name else None
    if (
            stored is not None and stored.get(marker, False) and
            str(stored.get(CURVE_HELPER_MODIFIER_UUID, "")) == modifier_uuid and
            getattr(stored, "parent", None) == target
    ):
        return stored
    return next((
        obj for obj in _data_objects()
        if (
            obj.get(marker, False) and
            str(obj.get(CURVE_HELPER_MODIFIER_UUID, "")) == modifier_uuid and
            getattr(obj, "parent", None) == target
        )
    ), None)


def curve_guide_object(target, modifier):
    return _helper_for_modifier(
        target, modifier, CURVE_GUIDE_MARKER, CURVE_GUIDE_NAME)


def curve_rest_guide_object(target, modifier):
    return _helper_for_modifier(
        target, modifier, CURVE_REST_GUIDE_MARKER, CURVE_REST_GUIDE_NAME)


def curve_station_object(target, modifier):
    return _helper_for_modifier(
        target, modifier, CURVE_STATION_MARKER, CURVE_STATION_NAME)


def _station_controller(station):
    controller = getattr(station, "id_data", None)
    return controller if _core().is_cage_controller(controller) else None


def _station_index(station, properties):
    pointer = _pointer(station)
    for index, item in enumerate(properties.curve_stations):
        if _pointer(item) == pointer:
            return index
    return -1


def _curve_tool_settings(context=None):
    context = context or bpy.context
    scene = getattr(context, "scene", None)
    return getattr(scene, "tool_settings", None) or getattr(
        context, "tool_settings", None)


def curve_proportional_enabled(context=None):
    """Match Blender's proportional-edit toggle in Object/Edit contexts."""
    settings = _curve_tool_settings(context)
    return bool(
        getattr(settings, "use_proportional_edit_objects", False) or
        getattr(settings, "use_proportional_edit", False))


def _curve_proportional_radius(
        world_points, selected_indices, context=None, radius=None,
        *, cover_all=False):
    points = {index: Vector(point) for index, point in world_points.items()}
    selected = {
        int(index) for index in selected_indices if int(index) in points}
    if cover_all and selected:
        farthest = max((
            min((point - points[other]).length for other in selected)
            for index, point in points.items()
            if index not in selected
        ), default=0.0)
        if farthest > 1.0e-8:
            # Blender falloff reaches zero at the exact radius. Keep the most
            # distant guide point inside the influence instead of on its edge.
            return farthest * 1.25
    try:
        value = float(radius)
    except (TypeError, ValueError):
        value = math.nan
    settings = _curve_tool_settings(context)
    if not math.isfinite(value) or value <= 1.0e-8:
        try:
            value = float(getattr(settings, "proportional_size", math.nan))
        except (AttributeError, TypeError, ValueError):
            value = math.nan
    if math.isfinite(value) and value > 1.0e-8:
        return value
    distances = tuple(
        min((point - points[other]).length for other in selected)
        for index, point in points.items()
        if index not in selected and selected
    )
    positive = tuple(distance for distance in distances if distance > 1.0e-8)
    if positive:
        return min(positive) * 2.5
    if len(points) > 1:
        minimum = Vector((
            min(point[axis] for point in points.values())
            for axis in range(3)))
        maximum = Vector((
            max(point[axis] for point in points.values())
            for axis in range(3)))
        return max((maximum - minimum).length * 0.35, 1.0e-8)
    return 1.0


def curve_proportional_weights(
        world_points, selected_indices, context=None, radius=None,
        *, force=False, cover_all=False):
    """Return FFD-compatible falloff weights for curve controls."""
    points = {index: Vector(point) for index, point in world_points.items()}
    selected = {
        int(index) for index in selected_indices if int(index) in points}
    if not selected:
        return ({index: 0.0 for index in points}, 1.0)
    if not force and not curve_proportional_enabled(context):
        return ({
            index: 1.0 if index in selected else 0.0
            for index in points
        }, 1.0)
    influence_radius = _curve_proportional_radius(
        points, selected, context, radius, cover_all=cover_all)
    settings = _curve_tool_settings(context)
    falloff = str(getattr(
        settings, "proportional_edit_falloff", "SMOOTH"))
    weights = {}
    for index, point in points.items():
        if index in selected:
            weights[index] = 1.0
            continue
        distance = min((point - points[other]).length for other in selected)
        weights[index] = _core().ffd_proportional_weight(
            distance, influence_radius, falloff, index)
    return weights, influence_radius


def sync_closed_curve_station_ends(properties, source_index=0):
    """Keep the first and last cross-sections identical on a closed guide."""
    stations = getattr(properties, "curve_stations", None)
    if (
            stations is None or len(stations) < 2 or
            not bool(getattr(properties, "curve_closed", False))
    ):
        return False
    source_index = 0 if int(source_index) <= 0 else len(stations) - 1
    target_index = len(stations) - 1 if source_index == 0 else 0
    source = stations[source_index]
    target = stations[target_index]
    source_scale = tuple(source.scale)
    source_offset = tuple(source.offset)
    source_radius = float(source.radius)
    source_twist = float(source.twist)
    if (
            tuple(target.scale) == source_scale and
            tuple(target.offset) == source_offset and
            abs(float(target.radius) - source_radius) <= 1.0e-7 and
            abs(float(target.twist) - source_twist) <= 1.0e-7
    ):
        return False
    pointer = _pointer(getattr(properties, "id_data", None))
    if pointer:
        _STATION_SYNC_GUARD.add(pointer)
    try:
        target.scale = source_scale
        target.offset = source_offset
        target.radius = source_radius
        target.twist = source_twist
    finally:
        if pointer:
            _STATION_SYNC_GUARD.discard(pointer)
    return True


def _equalize_curve_station_factors(properties):
    """Keep every existing cross-section at an even normalized position."""
    stations = getattr(properties, "curve_stations", None)
    count = len(stations) if stations is not None else 0
    if count < CURVE_STATION_MINIMUM:
        return False
    pointer = _pointer(getattr(properties, "id_data", None))
    changed = False
    if pointer:
        _STATION_SYNC_GUARD.add(pointer)
    try:
        denominator = max(count - 1, 1)
        for index, station in enumerate(stations):
            factor = index / denominator
            if abs(float(station.factor) - factor) <= 1.0e-7:
                continue
            station.factor = factor
            changed = True
    finally:
        if pointer:
            _STATION_SYNC_GUARD.discard(pointer)
    return changed


def _curve_station_update(station, context):
    controller = _station_controller(station)
    pointer = _pointer(controller)
    if (
            not pointer or pointer in _STATION_SYNC_GUARD or
            pointer in getattr(_core(), "_SYNCING", set())
    ):
        return
    target = _core().find_target(controller)
    modifier = _core().find_modifier(target, controller) if target else None
    if target is None or modifier is None:
        return
    properties = controller.sdh_cage_deform
    if bool(getattr(properties, "curve_even_stations", False)):
        _equalize_curve_station_factors(properties)
    index = _station_index(station, properties)
    if index >= 0:
        if index == 0:
            clamped = 0.0
        elif index == len(properties.curve_stations) - 1:
            clamped = 1.0
        else:
            lower = float(
                properties.curve_stations[index - 1].factor) + 1.0e-4
            upper = float(
                properties.curve_stations[index + 1].factor) - 1.0e-4
            clamped = min(max(float(station.factor), lower), upper)
        if abs(clamped - float(station.factor)) > 1.0e-7:
            _STATION_SYNC_GUARD.add(pointer)
            try:
                station.factor = clamped
            finally:
                _STATION_SYNC_GUARD.discard(pointer)
        if (
                bool(getattr(properties, "curve_closed", False)) and
                index in {0, len(properties.curve_stations) - 1}
        ):
            sync_closed_curve_station_ends(properties, index)
    update_curve_station_mesh(target, modifier, controller)
    try:
        target.update_tag()
    except (AttributeError, ReferenceError, RuntimeError):
        pass


def _curve_point_controller(point):
    controller = getattr(point, "id_data", None)
    return controller if _core().is_cage_controller(controller) else None


def _curve_point_index(point, properties):
    pointer = _pointer(point)
    for index, item in enumerate(properties.curve_points):
        if _pointer(item) == pointer:
            return index
    return -1


def _curve_point_shape_update(point, context):
    controller = _curve_point_controller(point)
    pointer = _pointer(controller)
    if (
            not pointer or pointer in _POINT_SYNC_GUARD or
            pointer in getattr(_core(), "_SYNCING", set())
    ):
        return
    properties = controller.sdh_cage_deform
    index = _curve_point_index(point, properties)
    if index < 0:
        return
    _apply_curve_point_handles(controller, index)
    target = _core().find_target(controller)
    if target is not None:
        try:
            target.update_tag()
        except (AttributeError, ReferenceError, RuntimeError):
            pass
    sync_curve_cage_relation(controller, force=True)


def _curve_point_native_state(control):
    controller = _curve_point_controller(control)
    properties = getattr(controller, "sdh_cage_deform", None)
    if properties is None:
        return None
    index = _curve_point_index(control, properties)
    target = _core().find_target(controller)
    modifier = _core().find_modifier(target, controller) if target else None
    guide = curve_guide_object(target, modifier)
    spline = curve_guide_spline(guide)
    if (
            index < 0 or spline is None or
            index >= len(spline.bezier_points)
    ):
        return None
    return target, controller, guide, spline, properties, index


def _curve_point_profile_get(control, attribute, default):
    state = _curve_point_native_state(control)
    if state is None:
        return default
    return float(getattr(state[3].bezier_points[state[5]], attribute))


def _curve_point_selected_indices(properties, points):
    """Return the union of addon and native Bezier point selections.

    The persistent Curve editor mirrors its selection into ``curve_points``,
    but Blender's native Curve Edit Mode and external box-selection paths can
    update only the Bezier RNA flags.  Treat both representations as the
    source of truth so panel edits retain a multi-point selection regardless
    of how it was made.
    """
    selected = {
        index for index, item in enumerate(properties.curve_points)
        if item.selected and index < len(points)
    }
    selected.update(
        index for index, point in enumerate(points)
        if point.select_control_point or point.select_left_handle or
        point.select_right_handle
    )
    return selected


def _curve_point_profile_set(control, value, attribute):
    state = _curve_point_native_state(control)
    if state is None:
        return
    target, controller, guide, spline, properties, active = state
    points = tuple(spline.bezier_points)
    selected = _curve_point_selected_indices(properties, points)
    selected.add(active)
    world_points = {
        index: guide.matrix_world @ Vector(point.co)
        for index, point in enumerate(points)
    }
    weights, _radius = curve_proportional_weights(
        world_points, selected, bpy.context,
        force=bool(getattr(
            properties, "curve_point_global_falloff", False)),
        cover_all=bool(getattr(
            properties, "curve_point_global_falloff", False)))
    active_point = points[active]
    previous = float(getattr(active_point, attribute))
    requested = float(value)
    delta = requested - previous
    if abs(delta) <= 1.0e-12:
        return
    for index, point in enumerate(points):
        weight = float(weights.get(index, 0.0))
        if weight <= 0.0:
            continue
        updated = float(getattr(point, attribute)) + delta * weight
        if attribute == "radius":
            updated = max(updated, 0.0)
        setattr(point, attribute, updated)
    guide.data.update_tag()
    target.update_tag()
    sync_curve_cage_relation(controller, force=True)


def _curve_point_edit_radius_get(control):
    return _curve_point_profile_get(control, "radius", 1.0)


def _curve_point_edit_radius_set(control, value):
    _curve_point_profile_set(control, value, "radius")


def _curve_point_edit_tilt_get(control):
    return _curve_point_profile_get(control, "tilt", 0.0)


def _curve_point_edit_tilt_set(control, value):
    _curve_point_profile_set(control, value, "tilt")


def _curve_point_shape_profile_get(control, attribute, default):
    if _curve_point_controller(control) is None:
        return default
    return float(getattr(control, attribute, default))


def _curve_point_shape_profile_set(control, value, attribute):
    state = _curve_point_native_state(control)
    if state is None:
        return
    target, controller, guide, spline, properties, active = state
    points = tuple(spline.bezier_points)
    selected = _curve_point_selected_indices(properties, points)
    selected.add(active)
    world_points = {
        index: guide.matrix_world @ Vector(point.co)
        for index, point in enumerate(points)
    }
    weights, _radius = curve_proportional_weights(
        world_points, selected, bpy.context,
        force=bool(getattr(
            properties, "curve_point_global_falloff", False)),
        cover_all=bool(getattr(
            properties, "curve_point_global_falloff", False)))
    previous = float(getattr(control, attribute))
    delta = float(value) - previous
    if abs(delta) <= 1.0e-12:
        return
    pointer = _pointer(controller)
    changed = []
    if pointer:
        _POINT_SYNC_GUARD.add(pointer)
    try:
        for index, item in enumerate(properties.curve_points):
            weight = float(weights.get(index, 0.0))
            if weight <= 0.0:
                continue
            updated = float(getattr(item, attribute)) + delta * weight
            if attribute == "bevel":
                updated = min(max(updated, 0.0), 1.0)
            else:
                updated = max(updated, 0.0)
            if abs(updated - float(getattr(item, attribute))) <= 1.0e-12:
                continue
            setattr(item, attribute, updated)
            changed.append(index)
        for index in changed:
            _apply_curve_point_handles(controller, index)
    finally:
        if pointer:
            _POINT_SYNC_GUARD.discard(pointer)
    if not changed:
        return
    guide.data.update_tag()
    target.update_tag()
    sync_curve_cage_relation(controller, force=True)


def _curve_point_edit_bevel_get(control):
    return _curve_point_shape_profile_get(control, "bevel", 1.0)


def _curve_point_edit_bevel_set(control, value):
    _curve_point_shape_profile_set(control, value, "bevel")


def _curve_point_edit_tension_get(control):
    return _curve_point_shape_profile_get(control, "tension", 1.0)


def _curve_point_edit_tension_set(control, value):
    _curve_point_shape_profile_set(control, value, "tension")


def _curve_station_world_points(properties):
    controller = getattr(properties, "id_data", None)
    target = _core().find_target(controller) if controller is not None else None
    modifier = (
        _core().find_modifier(target, controller) if target is not None else None)
    guide_signature, guide, relative = _curve_guide_signature(properties)
    state = _build_preview_sample_state(
        properties, guide_signature, guide, relative)
    cage_matrix = (
        _core().cage_local_matrix(target, controller)
        if target is not None and controller is not None else Matrix.Identity(4))
    points = {}
    for index, station in enumerate(properties.curve_stations):
        factor = min(max(float(station.factor), 0.0), 1.0)
        if state is not None:
            local = _sample_preview_state(
                state, factor * float(state["length"]))[0]
        else:
            local = Vector((0.0, factor, 0.0))
        points[index] = cage_matrix @ Vector(local)
    return target, modifier, controller, points


def _curve_station_profile_set(station, value, attribute):
    controller = _station_controller(station)
    properties = getattr(controller, "sdh_cage_deform", None)
    if properties is None:
        return
    active = _station_index(station, properties)
    if active < 0:
        return
    if bool(getattr(properties, "curve_even_stations", False)):
        _equalize_curve_station_factors(properties)
    target, modifier, controller, world_points = (
        _curve_station_world_points(properties))
    selected = {
        index for index, item in enumerate(properties.curve_stations)
        if item.selected
    }
    selected.add(active)
    weights, _radius = curve_proportional_weights(
        world_points, selected, bpy.context)
    previous = float(getattr(station, attribute))
    delta = float(value) - previous
    if abs(delta) <= 1.0e-12:
        return
    pointer = _pointer(controller)
    if pointer:
        _STATION_SYNC_GUARD.add(pointer)
    try:
        for index, item in enumerate(properties.curve_stations):
            weight = float(weights.get(index, 0.0))
            if weight <= 0.0:
                continue
            updated = float(getattr(item, attribute)) + delta * weight
            if attribute == "radius":
                updated = max(updated, 0.0)
            setattr(item, attribute, updated)
    finally:
        if pointer:
            _STATION_SYNC_GUARD.discard(pointer)
    if bool(getattr(properties, "curve_closed", False)):
        sync_closed_curve_station_ends(properties, 0)
    if target is not None and modifier is not None:
        update_curve_station_mesh(target, modifier, controller)
        target.update_tag()


def _curve_station_edit_radius_get(station):
    return float(station.radius)


def _curve_station_edit_radius_set(station, value):
    _curve_station_profile_set(station, value, "radius")


def _curve_station_edit_twist_get(station):
    return float(station.twist)


def _curve_station_edit_twist_set(station, value):
    _curve_station_profile_set(station, value, "twist")


class SDHCurvePoint(PropertyGroup):
    selected: BoolProperty(
        name="Selected",
        default=False,
        options={"HIDDEN"},
    )
    handles_linked: BoolProperty(
        name="Linked Handles",
        description=(
            "Keep both Bezier handles mirrored until Alt makes one side "
            "independent"),
        default=True,
        options={"HIDDEN"},
    )
    edit_radius: FloatProperty(
        name="Point Radius",
        description=(
            "Adjust selected guide-point radii with Blender proportional "
            "falloff"),
        default=1.0,
        min=0.0,
        soft_max=4.0,
        get=_curve_point_edit_radius_get,
        set=_curve_point_edit_radius_set,
        options={"SKIP_SAVE"},
    )
    edit_tilt: FloatProperty(
        name="Point Roll",
        description=(
            "Adjust selected guide-point roll with Blender proportional "
            "falloff"),
        subtype="ANGLE",
        default=0.0,
        soft_min=-math.tau,
        soft_max=math.tau,
        get=_curve_point_edit_tilt_get,
        set=_curve_point_edit_tilt_set,
        options={"SKIP_SAVE"},
    )
    bevel: FloatProperty(
        name="Bevel",
        description=(
            "Blend this guide point from a sharp corner to a shared smooth "
            "tangent"),
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        update=_curve_point_shape_update,
    )
    tension: FloatProperty(
        name="Tension",
        description="Scale the Bezier handles around this guide point",
        default=1.0,
        min=0.0,
        soft_max=3.0,
        update=_curve_point_shape_update,
    )
    edit_bevel: FloatProperty(
        name="Bevel",
        description=(
            "Adjust selected guide-point bevel with Blender proportional "
            "falloff"),
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        get=_curve_point_edit_bevel_get,
        set=_curve_point_edit_bevel_set,
        options={"SKIP_SAVE"},
    )
    edit_tension: FloatProperty(
        name="Tension",
        description=(
            "Adjust selected guide-point tension with Blender proportional "
            "falloff"),
        default=1.0,
        min=0.0,
        soft_max=3.0,
        get=_curve_point_edit_tension_get,
        set=_curve_point_edit_tension_set,
        options={"SKIP_SAVE"},
    )


class SDHCurveStation(PropertyGroup):
    factor: FloatProperty(
        name="Position",
        description="Normalized position of this cross-section along the guide",
        default=0.5,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        update=_curve_station_update,
    )
    scale: FloatVectorProperty(
        name="U / W Scale",
        description="Independent cross-section scale along the guide U and W axes",
        size=2,
        default=(1.0, 1.0),
        min=0.001,
        soft_max=4.0,
        update=_curve_station_update,
    )
    offset: FloatVectorProperty(
        name="U / W Offset",
        description="Cross-section center offset along the guide U and W axes",
        size=2,
        default=(0.0, 0.0),
        soft_min=-10.0,
        soft_max=10.0,
        update=_curve_station_update,
    )
    radius: FloatProperty(
        name="Radius",
        description=(
            "Cross-section radius multiplier interpolated along the guide"),
        default=1.0,
        min=0.0,
        soft_max=4.0,
        update=_curve_station_update,
    )
    twist: FloatProperty(
        name="Twist",
        description=(
            "Cross-section rotation around the guide tangent, interpolated "
            "between stations"),
        subtype="ANGLE",
        default=0.0,
        soft_min=-math.tau,
        soft_max=math.tau,
        update=_curve_station_update,
    )
    edit_radius: FloatProperty(
        name="Radius",
        description=(
            "Adjust cross-section radii with Blender proportional falloff"),
        default=1.0,
        min=0.0,
        soft_max=4.0,
        get=_curve_station_edit_radius_get,
        set=_curve_station_edit_radius_set,
        options={"SKIP_SAVE"},
    )
    edit_twist: FloatProperty(
        name="Twist",
        description=(
            "Adjust cross-section twist with Blender proportional falloff"),
        subtype="ANGLE",
        default=0.0,
        soft_min=-math.tau,
        soft_max=math.tau,
        get=_curve_station_edit_twist_get,
        set=_curve_station_edit_twist_set,
        options={"SKIP_SAVE"},
    )
    selected: BoolProperty(default=False, options={"HIDDEN"})


def ensure_curve_station_collection(properties):
    stations = properties.curve_stations
    if len(stations) >= CURVE_STATION_MINIMUM:
        properties.curve_active_station = min(
            max(int(properties.curve_active_station), 0), len(stations) - 1)
        return False
    pointer = _pointer(getattr(properties, "id_data", None))
    if pointer in _STATION_SYNC_GUARD:
        return False
    if pointer:
        _STATION_SYNC_GUARD.add(pointer)
    try:
        stations.clear()
        for index, factor in enumerate((0.0, 0.5, 1.0)):
            station = stations.add()
            station.name = iface_("Cross Section {index}").format(index=index + 1)
            station.factor = factor
            station.scale = (1.0, 1.0)
            station.offset = (0.0, 0.0)
            station.radius = 1.0
            station.twist = 0.0
        properties.curve_active_station = 1
    finally:
        if pointer:
            _STATION_SYNC_GUARD.discard(pointer)
    return True


def curve_guide_spline(guide):
    data = getattr(guide, "data", None)
    if data is None:
        return None
    return next((
        spline for spline in data.splines
        if spline.type == "BEZIER" and
        len(spline.bezier_points) >= CURVE_POINT_MINIMUM
    ), None)


def ensure_curve_point_collection(properties, guide=None, *, reset=False):
    """Keep controller-side point controls aligned with the managed spline."""
    controller = getattr(properties, "id_data", None)
    if guide is None and _core().is_cage_controller(controller):
        target = _core().find_target(controller)
        modifier = _core().find_modifier(target, controller) if target else None
        guide = curve_guide_object(target, modifier)
    spline = curve_guide_spline(guide)
    if spline is None:
        return False
    count = len(spline.bezier_points)
    points = properties.curve_points
    pointer = _pointer(controller)
    if pointer in _POINT_SYNC_GUARD:
        return False
    if pointer:
        _POINT_SYNC_GUARD.add(pointer)
    changed = bool(reset or len(points) != count)
    try:
        if reset:
            points.clear()
        while len(points) > count:
            points.remove(len(points) - 1)
        while len(points) < count:
            index = len(points)
            item = points.add()
            item.name = iface_("Guide Point {index}").format(index=index + 1)
            item.selected = False
            item.handles_linked = True
            item.bevel = 1.0
            item.tension = 1.0
        for index, item in enumerate(points):
            if not item.name:
                item.name = iface_("Guide Point {index}").format(index=index + 1)
        if count:
            properties.curve_active_point = min(
                max(int(properties.curve_active_point), 0), count - 1)
    finally:
        if pointer:
            _POINT_SYNC_GUARD.discard(pointer)
    return changed


def equalize_curve_stations(target, modifier, controller):
    """Distribute existing cross sections evenly without changing profiles."""
    properties = getattr(controller, "sdh_cage_deform", None)
    if properties is None:
        return False
    ensure_curve_station_collection(properties)
    stations = properties.curve_stations
    count = len(stations)
    if count < CURVE_STATION_MINIMUM:
        return False
    _equalize_curve_station_factors(properties)
    if bool(getattr(properties, "curve_closed", False)):
        sync_closed_curve_station_ends(properties, 0)
    update_curve_station_mesh(target, modifier, controller)
    try:
        target.update_tag()
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    return True


def _normalized_or(vector, fallback):
    vector = Vector(vector)
    if vector.length <= 1.0e-8:
        return Vector(fallback)
    vector.normalize()
    return vector


def _apply_curve_point_handles(controller, point_index):
    """Apply one point's bevel/tension controls to its native Bezier handles."""
    target = _core().find_target(controller)
    modifier = _core().find_modifier(target, controller) if target else None
    guide = curve_guide_object(target, modifier)
    spline = curve_guide_spline(guide)
    properties = getattr(controller, "sdh_cage_deform", None)
    if spline is None or properties is None:
        return False
    ensure_curve_point_collection(properties, guide)
    points = spline.bezier_points
    count = len(points)
    index = min(max(int(point_index), 0), count - 1)
    closed = bool(spline.use_cyclic_u)
    previous = points[(index - 1) % count] if closed or index > 0 else None
    following = points[(index + 1) % count] if closed or index + 1 < count else None
    point = points[index]
    control = properties.curve_points[index]
    bevel = min(max(float(control.bevel), 0.0), 1.0)
    tension = max(float(control.tension), 0.0)
    co = Vector(point.co)

    incoming = None
    outgoing = None
    previous_length = 0.0
    following_length = 0.0
    if previous is not None:
        delta = co - Vector(previous.co)
        previous_length = delta.length
        incoming = _normalized_or(delta, (0.0, 1.0, 0.0))
    if following is not None:
        delta = Vector(following.co) - co
        following_length = delta.length
        outgoing = _normalized_or(
            delta, incoming if incoming is not None else (0.0, 1.0, 0.0))

    if incoming is not None and outgoing is not None:
        smooth = incoming + outgoing
        if smooth.length <= 1.0e-8:
            smooth = outgoing.copy()
        smooth.normalize()
        left_direction = _normalized_or(
            incoming.lerp(smooth, bevel), incoming)
        right_direction = _normalized_or(
            outgoing.lerp(smooth, bevel), outgoing)
    else:
        direction = (
            incoming if incoming is not None else
            outgoing if outgoing is not None else
            Vector((0.0, 1.0, 0.0)))
        left_direction = Vector(direction)
        right_direction = Vector(direction)
        if previous is None:
            previous_length = following_length
        if following is None:
            following_length = previous_length

    point.handle_left_type = "FREE"
    point.handle_right_type = "FREE"
    point.handle_left = (
        co - left_direction * previous_length * tension / 3.0)
    point.handle_right = (
        co + right_direction * following_length * tension / 3.0)
    control.handles_linked = True
    try:
        guide.data.update_tag()
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    return True


def apply_all_curve_point_handles(controller):
    properties = getattr(controller, "sdh_cage_deform", None)
    if properties is None:
        return False
    target = _core().find_target(controller)
    modifier = _core().find_modifier(target, controller) if target else None
    guide = curve_guide_object(target, modifier)
    if not ensure_curve_point_collection(properties, guide) and not properties.curve_points:
        return False
    pointer = _pointer(controller)
    if pointer:
        _POINT_SYNC_GUARD.add(pointer)
    try:
        changed = False
        for index in range(len(properties.curve_points)):
            changed = _apply_curve_point_handles(controller, index) or changed
    finally:
        if pointer:
            _POINT_SYNC_GUARD.discard(pointer)
    return changed


def _set_curve_transform(obj, controller):
    try:
        rotation = _core()._controller_rotation_xyz(controller)
        if str(obj.rotation_mode) != "XYZ":
            obj.rotation_mode = "XYZ"
        if (Vector(obj.location) - Vector(controller.location)).length > 1.0e-7:
            obj.location = controller.location
        if any(abs(float(a) - float(b)) > 1.0e-7
               for a, b in zip(obj.rotation_euler, rotation)):
            obj.rotation_euler = rotation
        if any(abs(float(value) - 1.0) > 1.0e-7 for value in obj.scale):
            obj.scale = (1.0, 1.0, 1.0)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def _new_guide(target, modifier, controller):
    data = bpy.data.curves.new(f"{modifier.name} Guide Data", "CURVE")
    data.dimensions = "3D"
    data.resolution_u = 24
    data.render_resolution_u = 24
    data.twist_mode = "MINIMUM"
    data.use_radius = True
    spline = data.splines.new("BEZIER")
    spline.bezier_points.add(2)
    guide = bpy.data.objects.new(f"{modifier.name} Curve Guide", data)
    collection = _core()._collection_for(bpy.context, target)
    collection.objects.link(guide)
    guide.parent = target
    guide.matrix_parent_inverse = Matrix.Identity(4)
    guide[CURVE_GUIDE_MARKER] = True
    guide[CURVE_HELPER_MODIFIER_UUID] = _core().cage_modifier_uuid(modifier)
    guide["_sdh_curve_cage_guide_uuid"] = uuid.uuid4().hex
    guide.show_in_front = True
    guide.hide_render = True
    guide.display_type = "WIRE"
    guide.lock_location = (True, True, True)
    guide.lock_rotation = (True, True, True)
    guide.lock_scale = (True, True, True)
    move_object_to_control_collection(
        guide, next(iter(getattr(target, "users_scene", ())), None))
    _set_curve_transform(guide, controller)
    reset_curve_guide_data(guide, controller.sdh_cage_deform)
    set_helper_object_visible(guide, False)
    return guide


def _replace_rest_guide_data(rest_guide, source_guide):
    """Freeze a copy of the current guide without carrying its animation."""
    source_data = getattr(source_guide, "data", None)
    if source_data is None:
        return False
    copied_data = source_data.copy()
    try:
        copied_data.animation_data_clear()
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    old_data = getattr(rest_guide, "data", None)
    rest_guide.data = copied_data
    if old_data is not None and getattr(old_data, "users", 1) == 0:
        try:
            bpy.data.curves.remove(old_data)
        except (ReferenceError, RuntimeError, TypeError):
            pass
    return True


def _new_rest_guide(target, modifier, controller, source_guide):
    """Create the hidden immutable reference used by relative curve binding."""
    data = bpy.data.curves.new(f"{modifier.name} Rest Guide Data", "CURVE")
    data.dimensions = "3D"
    data.resolution_u = 24
    data.render_resolution_u = 24
    data.twist_mode = "MINIMUM"
    data.use_radius = True
    rest_guide = bpy.data.objects.new(
        f"{modifier.name} Curve Rest Guide", data)
    collection = _core()._collection_for(bpy.context, target)
    collection.objects.link(rest_guide)
    rest_guide.parent = target
    rest_guide.matrix_parent_inverse = Matrix.Identity(4)
    rest_guide[CURVE_REST_GUIDE_MARKER] = True
    rest_guide[CURVE_HELPER_MODIFIER_UUID] = _core().cage_modifier_uuid(
        modifier)
    rest_guide["_sdh_curve_cage_rest_guide_uuid"] = uuid.uuid4().hex
    rest_guide.hide_render = True
    rest_guide.hide_select = True
    rest_guide.display_type = "WIRE"
    rest_guide.lock_location = (True, True, True)
    rest_guide.lock_rotation = (True, True, True)
    rest_guide.lock_scale = (True, True, True)
    move_object_to_control_collection(
        rest_guide, next(iter(getattr(target, "users_scene", ())), None))
    _set_curve_transform(rest_guide, controller)
    _replace_rest_guide_data(rest_guide, source_guide)
    set_helper_object_visible(rest_guide, False)
    return rest_guide


def ensure_curve_rest_guide(
        target, modifier, controller, source_guide=None, *, reset=False):
    """Return the rest guide, optionally rebinding it to the control guide."""
    if target is None or modifier is None or controller is None:
        return None
    source_guide = source_guide or curve_guide_object(target, modifier)
    if source_guide is None:
        return None
    rest_guide = curve_rest_guide_object(target, modifier)
    if rest_guide is None:
        rest_guide = _new_rest_guide(
            target, modifier, controller, source_guide)
        reset = False
    else:
        _set_curve_transform(rest_guide, controller)
        rest_guide.hide_render = True
        rest_guide.hide_select = True
        rest_guide.lock_location = (True, True, True)
        rest_guide.lock_rotation = (True, True, True)
        rest_guide.lock_scale = (True, True, True)
        if reset:
            _replace_rest_guide_data(rest_guide, source_guide)
    rest_guide[CURVE_REST_GUIDE_MARKER] = True
    rest_guide[CURVE_HELPER_MODIFIER_UUID] = _core().cage_modifier_uuid(
        modifier)
    group = getattr(modifier, "node_group", None)
    if group is not None:
        group[CURVE_REST_GUIDE_NAME] = rest_guide.name
    set_helper_object_visible(rest_guide, False)
    return rest_guide


def rebind_curve_reference(target, modifier, controller):
    """Capture the visible guide as the no-deformation reference curve."""
    properties = getattr(controller, "sdh_cage_deform", None)
    guide = curve_guide_object(target, modifier)
    if properties is None or guide is None:
        return None
    rest_guide = ensure_curve_rest_guide(
        target, modifier, controller, guide, reset=True)
    if rest_guide is None:
        return None
    pointer = _pointer(controller)
    if pointer:
        _core()._SYNCING.add(pointer)
    try:
        properties.curve_relative_binding = True
    finally:
        if pointer:
            _core()._SYNCING.discard(pointer)
    try:
        target.update_tag()
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    return rest_guide


def reset_curve_guide_data(guide, properties):
    data = getattr(guide, "data", None)
    if data is None:
        return False
    spline = data.splines[0] if len(data.splines) == 1 else None
    if (
            spline is None or spline.type != "BEZIER" or
            len(spline.bezier_points) != 3
    ):
        data.splines.clear()
        spline = data.splines.new("BEZIER")
        spline.bezier_points.add(2)
    half_y = max(abs(float(properties.size[1])) * 0.5, 1.0e-5)
    for point, y in zip(spline.bezier_points, (-half_y, 0.0, half_y)):
        point.co = (0.0, y, 0.0)
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"
        point.tilt = 0.0
        point.radius = 1.0
        point.select_control_point = False
        point.select_left_handle = False
        point.select_right_handle = False
    spline.use_cyclic_u = bool(getattr(properties, "curve_closed", False))
    data.update_tag()
    return True


def _float_signature(values):
    return tuple(float(value).hex() for value in values)


def curve_mode_identifier(properties):
    mode = str(getattr(properties, "curve_mode", "") or "")
    if mode in CURVE_MODE_TO_BOUNDARY:
        return mode
    boundary = str(getattr(properties, "curve_boundary_mode", "EXTEND"))
    return CURVE_BOUNDARY_TO_MODE.get(boundary, "UNLIMITED")


def _curve_guide_signature(properties, guide=None, *, signature_tag="SDH_CURVE_GUIDE_V1"):
    """Return the exact guide state used by the viewport curve sampler."""
    controller = getattr(properties, "id_data", None)
    target = _core().find_target(controller) if controller is not None else None
    modifier = (
        _core().find_modifier(target, controller) if target is not None else None)
    if guide is None:
        guide = curve_guide_object(target, modifier)
    data = getattr(guide, "data", None)
    spline = None
    if data is not None:
        spline = next((
            item for item in data.splines
            if item.type == "BEZIER" and len(item.bezier_points) >= 2
        ), None)
    if guide is None or spline is None:
        return (
            f"{signature_tag}_MISSING", _pointer(controller)), None, None
    try:
        cage_matrix = _core().cage_local_matrix(target, controller)
        relative = cage_matrix.inverted_safe() @ guide.matrix_world
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        relative = Matrix.Identity(4)
    points = tuple(
        (
            _float_signature(point.co),
            _float_signature(point.handle_left),
            _float_signature(point.handle_right),
            float(point.tilt).hex(),
            float(point.radius).hex(),
            str(point.handle_left_type),
            str(point.handle_right_type),
        )
        for point in spline.bezier_points
    )
    signature = (
        signature_tag,
        _pointer(guide),
        _pointer(data),
        bool(spline.use_cyclic_u),
        int(max(getattr(properties, "curve_resolution", 24), 2)),
        tuple(float(value).hex() for row in relative for value in row),
        points,
    )
    return signature, guide, relative


def _curve_rest_guide_signature(properties):
    controller = getattr(properties, "id_data", None)
    target = _core().find_target(controller) if controller is not None else None
    modifier = (
        _core().find_modifier(target, controller) if target is not None else None)
    rest_guide = curve_rest_guide_object(target, modifier)
    return _curve_guide_signature(
        properties, rest_guide, signature_tag="SDH_CURVE_REST_GUIDE_V1")


def _bezier_sample(point_a, point_b, factor):
    factor = min(max(float(factor), 0.0), 1.0)
    inverse = 1.0 - factor
    p0 = Vector(point_a.co)
    p1 = Vector(point_a.handle_right)
    p2 = Vector(point_b.handle_left)
    p3 = Vector(point_b.co)
    position = (
        p0 * (inverse ** 3) +
        p1 * (3.0 * inverse * inverse * factor) +
        p2 * (3.0 * inverse * factor * factor) +
        p3 * (factor ** 3)
    )
    tangent = (
        (p1 - p0) * (3.0 * inverse * inverse) +
        (p2 - p1) * (6.0 * inverse * factor) +
        (p3 - p2) * (3.0 * factor * factor)
    )
    if tangent.length <= 1.0e-8:
        tangent = p3 - p0
    tilt = float(point_a.tilt) * inverse + float(point_b.tilt) * factor
    radius = float(point_a.radius) * inverse + float(point_b.radius) * factor
    return position, tangent, tilt, radius


def _normal_perpendicular_to(tangent, preferred=None):
    tangent = Vector(tangent)
    if tangent.length <= 1.0e-8:
        tangent = Vector((0.0, 1.0, 0.0))
    else:
        tangent.normalize()
    initial = Vector(preferred) if preferred is not None else tangent.cross(
        Vector((0.0, 0.0, 1.0)))
    if initial.length <= 1.0e-8:
        initial = tangent.cross(Vector((1.0, 0.0, 0.0)))
    candidates = (
        initial,
        Vector((1.0, 0.0, 0.0)),
        Vector((0.0, 0.0, 1.0)),
        Vector((0.0, 1.0, 0.0)),
    )
    for candidate in candidates:
        normal = candidate - tangent * candidate.dot(tangent)
        if normal.length > 1.0e-8:
            normal.normalize()
            return normal
    return Vector((1.0, 0.0, 0.0))


def _build_preview_sample_state(
        properties, guide_signature=None, guide=None, relative=None):
    if guide is None or relative is None:
        guide_signature, guide, relative = _curve_guide_signature(properties)
    cached = _PREVIEW_SAMPLE_CACHE.get(guide_signature)
    if cached is not None:
        return cached
    data = getattr(guide, "data", None)
    spline = None
    if data is not None:
        spline = next((
            item for item in data.splines
            if item.type == "BEZIER" and len(item.bezier_points) >= 2
        ), None)
    if spline is None:
        return None

    points = tuple(spline.bezier_points)
    segments = [(index, index + 1) for index in range(len(points) - 1)]
    if spline.use_cyclic_u:
        segments.append((len(points) - 1, 0))
    resolution = int(max(getattr(properties, "curve_resolution", 24), 2))
    basis = relative.to_3x3()
    raw_samples = []
    for segment_index, (first, second) in enumerate(segments):
        for step in range(resolution + 1):
            if segment_index and step == 0:
                continue
            factor = step / float(resolution)
            position, tangent, tilt, radius = _bezier_sample(
                points[first], points[second], factor)
            transformed_position = relative @ position
            transformed_tangent = basis @ tangent
            if transformed_tangent.length <= 1.0e-8:
                transformed_tangent = Vector((0.0, 1.0, 0.0))
            else:
                transformed_tangent.normalize()
            raw_samples.append((
                transformed_position, transformed_tangent, tilt, radius))
    if len(raw_samples) < 2:
        return None

    samples = []
    distance = 0.0
    previous_position = None
    previous_tangent = None
    transported_u = None
    for position, tangent, tilt, radius in raw_samples:
        if previous_position is not None:
            distance += (position - previous_position).length
        if previous_tangent is None:
            transported_u = _normal_perpendicular_to(tangent)
        else:
            try:
                transported_u = (
                    previous_tangent.rotation_difference(tangent) @ transported_u)
            except (ValueError, RuntimeError):
                pass
            transported_u = _normal_perpendicular_to(tangent, transported_u)
        try:
            u_axis = Matrix.Rotation(float(tilt), 3, tangent) @ transported_u
        except (TypeError, ValueError):
            u_axis = transported_u.copy()
        u_axis = _normal_perpendicular_to(tangent, u_axis)
        w_axis = u_axis.cross(tangent)
        if w_axis.length <= 1.0e-8:
            w_axis = Vector((0.0, 0.0, 1.0))
        else:
            w_axis.normalize()
        samples.append((
            distance,
            position.copy(),
            tangent.copy(),
            u_axis.copy(),
            w_axis,
            float(radius),
        ))
        previous_position = position
        previous_tangent = tangent
    if bool(spline.use_cyclic_u) and distance > 1.0e-8:
        first_u = Vector(samples[0][3])
        last_u = Vector(samples[-1][3])
        seam_axis = Vector(samples[0][2])
        if seam_axis.length <= 1.0e-8:
            seam_axis = Vector((0.0, 1.0, 0.0))
        else:
            seam_axis.normalize()
        residual = math.atan2(
            float(seam_axis.dot(last_u.cross(first_u))),
            min(max(float(last_u.dot(first_u)), -1.0), 1.0),
        )
        corrected = []
        for sample in samples:
            tangent = Vector(sample[2])
            correction = residual * float(sample[0]) / float(distance)
            u_axis = Matrix.Rotation(correction, 3, tangent) @ Vector(sample[3])
            u_axis = _normal_perpendicular_to(tangent, u_axis)
            w_axis = u_axis.cross(tangent)
            if w_axis.length <= 1.0e-8:
                w_axis = Vector(sample[4])
            else:
                w_axis.normalize()
            corrected.append((
                sample[0], sample[1], tangent, u_axis, w_axis, sample[5]))
        samples = corrected

    state = {
        "distances": tuple(sample[0] for sample in samples),
        "samples": tuple(samples),
        "length": max(float(distance), 1.0e-8),
        "start": samples[0][1].copy(),
        "closed": bool(spline.use_cyclic_u),
    }
    if len(_PREVIEW_SAMPLE_CACHE) >= _PREVIEW_SAMPLE_CACHE_LIMIT:
        _PREVIEW_SAMPLE_CACHE.clear()
    _PREVIEW_SAMPLE_CACHE[guide_signature] = state
    return state


def curve_preview_signature(properties):
    """Return a cache signature that also refreshes the sampled guide state."""
    guide_signature, _guide, _relative = _curve_guide_signature(properties)
    state = _build_preview_sample_state(properties, guide_signature)
    rest_signature = None
    if bool(getattr(properties, "curve_relative_binding", False)):
        rest_signature, rest_guide, rest_relative = _curve_rest_guide_signature(
            properties)
        _build_preview_sample_state(
            properties, rest_signature, rest_guide, rest_relative)
    controller = getattr(properties, "id_data", None)
    pointer = _pointer(controller)
    if pointer:
        _LATEST_PREVIEW_STATE[pointer] = (guide_signature, state)
    stations = tuple(
        (
            float(station.factor).hex(),
            _float_signature(station.scale),
            _float_signature(station.offset),
            float(station.radius).hex(),
            float(station.twist).hex(),
        )
        for station in properties.curve_stations
    )
    return (
        "SDH_CURVE_PREVIEW_V1",
        guide_signature,
        rest_signature,
        bool(getattr(properties, "curve_relative_binding", False)),
        str(properties.curve_length_mode),
        curve_mode_identifier(properties),
        float(getattr(properties, "curve_range_start", 0.0)).hex(),
        float(getattr(properties, "curve_range_end", 1.0)).hex(),
        bool(getattr(properties, "curve_closed", False)),
        bool(properties.curve_preserve_volume),
        float(getattr(properties, "curve_global_radius", 1.0)).hex(),
        float(getattr(properties, "curve_global_twist", 0.0)).hex(),
        stations,
    )


def _sample_preview_state(state, distance):
    samples = state["samples"]
    distances = state["distances"]
    distance = min(max(float(distance), 0.0), float(state["length"]))
    if distance <= distances[0]:
        return samples[0][1:]
    if distance >= distances[-1]:
        return samples[-1][1:]
    index = min(max(bisect_right(distances, distance) - 1, 0), len(samples) - 2)
    first = samples[index]
    second = samples[index + 1]
    span = max(float(second[0] - first[0]), 1.0e-8)
    factor = (distance - float(first[0])) / span
    position = first[1].lerp(second[1], factor)
    tangent = first[2].lerp(second[2], factor)
    if tangent.length <= 1.0e-8:
        tangent = first[2].copy()
    else:
        tangent.normalize()
    u_axis = first[3].lerp(second[3], factor)
    u_axis = _normal_perpendicular_to(tangent, u_axis)
    w_axis = u_axis.cross(tangent)
    if w_axis.length <= 1.0e-8:
        w_axis = first[4].copy()
    else:
        w_axis.normalize()
    radius = float(first[5]) + (float(second[5]) - float(first[5])) * factor
    return position, tangent, u_axis, w_axis, radius


def _curve_station_values(properties, factor):
    stations = tuple(properties.curve_stations)
    if not stations:
        return Vector((1.0, 1.0)), Vector((0.0, 0.0)), 1.0, 0.0
    factor = min(max(float(factor), 0.0), 1.0)
    if factor <= float(stations[0].factor):
        return (
            Vector(stations[0].scale), Vector(stations[0].offset),
            max(float(stations[0].radius), 0.0), float(stations[0].twist))
    if factor >= float(stations[-1].factor):
        return (
            Vector(stations[-1].scale), Vector(stations[-1].offset),
            max(float(stations[-1].radius), 0.0), float(stations[-1].twist))
    for lower, upper in zip(stations, stations[1:]):
        lower_factor = float(lower.factor)
        upper_factor = float(upper.factor)
        if factor > upper_factor:
            continue
        interpolation = (
            (factor - lower_factor) /
            max(upper_factor - lower_factor, 1.0e-8))
        return (
            Vector(lower.scale).lerp(Vector(upper.scale), interpolation),
            Vector(lower.offset).lerp(Vector(upper.offset), interpolation),
            max(
                float(lower.radius) +
                (float(upper.radius) - float(lower.radius)) * interpolation,
                0.0),
            float(lower.twist) +
            (float(upper.twist) - float(lower.twist)) * interpolation,
        )
    return (
        Vector(stations[-1].scale), Vector(stations[-1].offset),
        max(float(stations[-1].radius), 0.0), float(stations[-1].twist))


def curve_preview_deformer(properties, *, apply_effect_range=True):
    """Build one inexpensive point mapper matching the Curve GN operation.

    ``apply_effect_range=False`` is reserved for structural cage drawing.  The
    blue cage always communicates the stable full-domain mapping, while the
    two boundary handles mark the independently editable effect interval.
    """
    guide_signature, _guide, _relative = _curve_guide_signature(properties)
    state = _build_preview_sample_state(properties, guide_signature)
    rest_state = None
    relative_binding = bool(getattr(properties, "curve_relative_binding", False))
    if relative_binding:
        rest_signature, rest_guide, rest_relative = _curve_rest_guide_signature(
            properties)
        rest_state = _build_preview_sample_state(
            properties, rest_signature, rest_guide, rest_relative)
        relative_binding = rest_state is not None
    controller = getattr(properties, "id_data", None)
    pointer = _pointer(controller)
    if pointer:
        _LATEST_PREVIEW_STATE[pointer] = (guide_signature, state)
    if state is None:
        return None

    length_mode = str(properties.curve_length_mode)
    curve_mode = (
        curve_mode_identifier(properties)
        if apply_effect_range else "UNLIMITED")
    preserve_volume = bool(properties.curve_preserve_volume)
    guide_length = max(float(state["length"]), 1.0e-8)
    guide_start = Vector(state["start"])
    closed = bool(state.get("closed", False))
    range_start = min(max(
        float(getattr(properties, "curve_range_start", 0.0)), 0.0), 1.0)
    range_end = min(max(
        float(getattr(properties, "curve_range_end", 1.0)), 0.0), 1.0)
    if range_start > range_end:
        range_start, range_end = range_end, range_start

    def deform(point, authored_y, size):
        point = Vector(point)
        size = Vector(size)
        cage_length = max(abs(float(size.y)), 1.0e-8)
        distance = float(authored_y) + cage_length * 0.5
        range_lower = range_start * cage_length
        range_upper = range_end * cage_length
        outside = not (range_lower <= distance <= range_upper)
        sample_source_distance = (
            min(max(distance, range_lower), range_upper)
            if curve_mode == "LIMITED" else distance)
        if closed and curve_mode == "UNLIMITED":
            if length_mode == "PRESERVE":
                sample_distance = sample_source_distance % guide_length
                station_factor = sample_distance / guide_length
            else:
                station_factor = (
                    sample_source_distance / cage_length) % 1.0
                sample_distance = station_factor * guide_length
        else:
            cage_factor = min(max(
                sample_source_distance / cage_length, 0.0), 1.0)
            guide_distance = min(max(
                sample_source_distance, 0.0), guide_length)
            if length_mode == "PRESERVE":
                sample_distance = guide_distance
                station_factor = guide_distance / guide_length
            else:
                sample_distance = cage_factor * guide_length
                station_factor = cage_factor

        if relative_binding:
            binding_factor = (
                (sample_source_distance / cage_length) % 1.0
                if closed and curve_mode == "UNLIMITED" else
                min(max(sample_source_distance / cage_length, 0.0), 1.0)
            )
            current_position, current_tangent, current_u_axis, current_w_axis, current_radius = (
                _sample_preview_state(state, binding_factor * guide_length))
            rest_position, rest_tangent, rest_u_axis, rest_w_axis, rest_radius = (
                _sample_preview_state(
                    rest_state,
                    binding_factor * float(rest_state["length"])))
            station_scale, station_offset, station_radius, station_twist = (
                _curve_station_values(properties, binding_factor))
            axial_scale = (
                guide_length / cage_length if length_mode == "STRETCH" else 1.0)
            cross_compensation = (
                max(abs(axial_scale), 1.0e-8) ** -0.5
                if preserve_volume else 1.0)
            effective_radius = (
                float(current_radius) / max(float(rest_radius), 1.0e-8) *
                max(float(getattr(properties, "curve_global_radius", 1.0)), 0.0) *
                station_radius * cross_compensation)
            effective_twist = (
                float(getattr(properties, "curve_global_twist", 0.0)) +
                station_twist)
            if abs(effective_twist) > 1.0e-10:
                rotation = Matrix.Rotation(
                    effective_twist, 3, current_tangent)
                current_u_axis = _normal_perpendicular_to(
                    current_tangent, rotation @ current_u_axis)
                current_w_axis = current_u_axis.cross(current_tangent)
                if current_w_axis.length <= 1.0e-8:
                    current_w_axis = Vector((0.0, 0.0, 1.0))
                else:
                    current_w_axis.normalize()
            if curve_mode == "WITHIN_BOX" and outside:
                return point.copy()
            rest_delta = point - rest_position
            u_coordinate = (
                rest_delta.dot(rest_u_axis) * float(station_scale.x) *
                effective_radius + float(station_offset.x))
            t_coordinate = rest_delta.dot(rest_tangent)
            w_coordinate = (
                rest_delta.dot(rest_w_axis) * float(station_scale.y) *
                effective_radius + float(station_offset.y))
            return (
                current_position +
                current_u_axis * u_coordinate +
                current_tangent * t_coordinate +
                current_w_axis * w_coordinate)

        position, tangent, u_axis, w_axis, radius = _sample_preview_state(
            state, sample_distance)
        if length_mode == "FIT_GUIDE":
            position = guide_start + (
                position - guide_start) * (cage_length / guide_length)

        station_scale, station_offset, station_radius, station_twist = (
            _curve_station_values(properties, station_factor))
        axial_scale = (
            guide_length / cage_length if length_mode == "STRETCH" else 1.0)
        cross_compensation = (
            max(abs(axial_scale), 1.0e-8) ** -0.5
            if preserve_volume else 1.0)
        effective_radius = (
            float(radius) *
            max(float(getattr(properties, "curve_global_radius", 1.0)), 0.0) *
            station_radius * cross_compensation)
        effective_twist = (
            float(getattr(properties, "curve_global_twist", 0.0)) +
            station_twist)
        if abs(effective_twist) > 1.0e-10:
            rotation = Matrix.Rotation(effective_twist, 3, tangent)
            u_axis = _normal_perpendicular_to(tangent, rotation @ u_axis)
            w_axis = u_axis.cross(tangent)
            if w_axis.length <= 1.0e-8:
                w_axis = Vector((0.0, 0.0, 1.0))
            else:
                w_axis.normalize()
        u_coordinate = (
            float(point.x) * float(station_scale.x) * effective_radius +
            float(station_offset.x))
        w_coordinate = (
            float(point.z) * float(station_scale.y) * effective_radius +
            float(station_offset.y))

        if curve_mode == "WITHIN_BOX" and outside:
            return point.copy()
        endpoint_extension = 0.0
        if curve_mode == "LIMITED":
            if length_mode == "PRESERVE":
                canonical_extension = (
                    min(sample_source_distance, 0.0) +
                    max(sample_source_distance - guide_length, 0.0))
            else:
                canonical_extension = (
                    min(sample_source_distance, 0.0) +
                    max(sample_source_distance - cage_length, 0.0)
                ) * axial_scale
            # Range exclusion freezes the boundary frame, then continues the
            # source rigidly along its tangent instead of stacking every
            # excluded section at one endpoint.
            endpoint_extension = (
                canonical_extension + distance - sample_source_distance)
        elif not closed:
            if length_mode == "PRESERVE":
                endpoint_extension = (
                    min(distance, 0.0) +
                    max(distance - guide_length, 0.0))
            else:
                endpoint_extension = (
                    min(distance, 0.0) +
                    max(distance - cage_length, 0.0)
                ) * axial_scale
        return (
            position +
            u_axis * u_coordinate +
            w_axis * w_coordinate +
            tangent * endpoint_extension
        )

    return deform


def _new_station_object(target, modifier, controller):
    mesh = bpy.data.meshes.new(f"{modifier.name} Stations Data")
    obj = bpy.data.objects.new(f"{modifier.name} Curve Stations", mesh)
    collection = _core()._collection_for(bpy.context, target)
    collection.objects.link(obj)
    obj.parent = target
    obj.matrix_parent_inverse = Matrix.Identity(4)
    obj[CURVE_STATION_MARKER] = True
    obj[CURVE_HELPER_MODIFIER_UUID] = _core().cage_modifier_uuid(modifier)
    obj.hide_render = True
    obj.hide_select = True
    obj.display_type = "WIRE"
    move_object_to_control_collection(
        obj, next(iter(getattr(target, "users_scene", ())), None))
    _set_curve_transform(obj, controller)
    set_helper_object_visible(obj, False)
    return obj


def _write_vector_attribute(mesh, name, values):
    attribute = mesh.attributes.get(name)
    if attribute is None or attribute.data_type != "FLOAT_VECTOR" or attribute.domain != "POINT":
        if attribute is not None:
            mesh.attributes.remove(attribute)
        attribute = mesh.attributes.new(
            name=name, type="FLOAT_VECTOR", domain="POINT")
    for item, value in zip(attribute.data, values):
        item.vector = value


def _write_float_attribute(mesh, name, values):
    attribute = mesh.attributes.get(name)
    if (
            attribute is None or attribute.data_type != "FLOAT" or
            attribute.domain != "POINT"
    ):
        if attribute is not None:
            mesh.attributes.remove(attribute)
        attribute = mesh.attributes.new(
            name=name, type="FLOAT", domain="POINT")
    for item, value in zip(attribute.data, values):
        item.value = float(value)


def update_curve_station_mesh(target, modifier, controller):
    properties = getattr(controller, "sdh_cage_deform", None)
    if properties is None:
        return None
    ensure_curve_station_collection(properties)
    station_object = curve_station_object(target, modifier)
    if station_object is None:
        station_object = _new_station_object(target, modifier, controller)
    _set_curve_transform(station_object, controller)
    mesh = station_object.data
    stations = tuple(properties.curve_stations)
    signature = repr(tuple(
        (
            round(float(station.factor), 8),
            tuple(round(float(value), 8) for value in station.scale),
            tuple(round(float(value), 8) for value in station.offset),
            round(float(station.radius), 8),
            round(float(station.twist), 8),
        )
        for station in stations
    ))
    if str(mesh.get("_sdh_curve_station_signature", "")) == signature:
        return station_object
    vertices = [(0.0, float(station.factor), 0.0) for station in stations]
    edges = [(index, index + 1) for index in range(len(vertices) - 1)]
    mesh.clear_geometry()
    mesh.from_pydata(vertices, edges, ())
    _write_vector_attribute(mesh, CURVE_SCALE_ATTRIBUTE, (
        (float(station.scale[0]), 1.0, float(station.scale[1]))
        for station in stations
    ))
    _write_vector_attribute(mesh, CURVE_OFFSET_ATTRIBUTE, (
        (float(station.offset[0]), 0.0, float(station.offset[1]))
        for station in stations
    ))
    _write_float_attribute(mesh, CURVE_RADIUS_ATTRIBUTE, (
        max(float(station.radius), 0.0) for station in stations))
    _write_float_attribute(mesh, CURVE_TWIST_ATTRIBUTE, (
        float(station.twist) for station in stations))
    mesh.update()
    mesh["_sdh_curve_station_signature"] = signature
    group = getattr(modifier, "node_group", None)
    if group is not None:
        group[CURVE_STATION_NAME] = station_object.name
    return station_object


def ensure_curve_companions(
        target, modifier, controller, *, reset_guide=False):
    properties = getattr(controller, "sdh_cage_deform", None)
    if (
            target is None or modifier is None or properties is None or
            str(getattr(properties, "cage_type", "")) != "CURVE"
    ):
        return None, None
    ensure_curve_station_collection(properties)
    guide = curve_guide_object(target, modifier)
    guide_created = guide is None
    if guide is None:
        guide = _new_guide(target, modifier, controller)
    else:
        _set_curve_transform(guide, controller)
        guide.lock_location = (True, True, True)
        guide.lock_rotation = (True, True, True)
        guide.lock_scale = (True, True, True)
        if reset_guide:
            reset_curve_guide_data(guide, properties)
    reset_points = bool(guide_created or reset_guide)
    ensure_curve_point_collection(properties, guide, reset=reset_points)
    guide[CURVE_HELPER_MODIFIER_UUID] = _core().cage_modifier_uuid(modifier)
    group = getattr(modifier, "node_group", None)
    if group is not None:
        group[CURVE_GUIDE_NAME] = guide.name
    if bool(getattr(properties, "curve_relative_binding", False)):
        ensure_curve_rest_guide(
            target, modifier, controller, guide, reset=reset_guide)
    stations = update_curve_station_mesh(target, modifier, controller)
    return guide, stations


def _remove_curve_helper_object(obj):
    if obj is None:
        return False
    data = getattr(obj, "data", None)
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except (ReferenceError, RuntimeError):
        return False
    if data is not None and getattr(data, "users", 1) == 0:
        try:
            if isinstance(data, bpy.types.Curve):
                bpy.data.curves.remove(data)
            elif isinstance(data, bpy.types.Mesh):
                bpy.data.meshes.remove(data)
        except (ReferenceError, RuntimeError, TypeError):
            pass
    return True


def remove_curve_companions(target, modifier):
    removed = 0
    for obj in (
        curve_guide_object(target, modifier),
        curve_rest_guide_object(target, modifier),
        curve_station_object(target, modifier)):
        if obj is None:
            continue
        if _remove_curve_helper_object(obj):
            removed += 1
    group = getattr(modifier, "node_group", None)
    if group is not None:
        for key in (
                CURVE_GUIDE_NAME, CURVE_REST_GUIDE_NAME,
                CURVE_STATION_NAME):
            try:
                if key in group:
                    del group[key]
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                pass
    return removed


def remove_orphan_curve_companions(target, live_modifier_uuids=None):
    """Remove curve helpers whose owning modifier was deleted directly."""
    if target is None:
        return 0
    if live_modifier_uuids is None:
        live_modifier_uuids = {
            _core().cage_modifier_uuid(modifier)
            for modifier in _core().cage_modifiers(target)
        }
    live_modifier_uuids = {
        str(value) for value in live_modifier_uuids if str(value or "")}
    orphans = tuple(
        obj for obj in _data_objects()
        if (
            is_curve_helper(obj) and
            getattr(obj, "parent", None) == target and
            str(obj.get(CURVE_HELPER_MODIFIER_UUID, "")) not in
            live_modifier_uuids
        )
    )
    removed = sum(int(_remove_curve_helper_object(obj)) for obj in orphans)
    return removed


def copy_curve_guide_state(
        source_guide, target, destination_modifier, destination_controller):
    """Copy one already-resolved guide into a newly-owned Curve cage stage."""
    if source_guide is None:
        return False
    destination_guide, _stations = ensure_curve_companions(
        target, destination_modifier, destination_controller)
    if destination_guide is None:
        return False
    old_data = destination_guide.data
    copied_data = source_guide.data.copy()
    animation = getattr(copied_data, "animation_data", None)
    action = getattr(animation, "action", None)
    if action is not None:
        try:
            animation.action = action.copy()
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
    destination_guide.data = copied_data
    if old_data.users == 0:
        bpy.data.curves.remove(old_data)
    destination_properties = getattr(
        destination_controller, "sdh_cage_deform", None)
    source_target = target_from_helper(source_guide)
    source_modifier = modifier_from_helper(source_guide)
    source_rest_guide = curve_rest_guide_object(
        source_target, source_modifier)
    if (
            destination_properties is not None and
            bool(getattr(destination_properties, "curve_relative_binding", False))
            and source_rest_guide is not None
    ):
        ensure_curve_rest_guide(
            target, destination_modifier, destination_controller,
            source_rest_guide, reset=True)
    update_curve_station_mesh(
        target, destination_modifier, destination_controller)
    return True


def copy_curve_state(
        target, source_modifier, source_controller,
        destination_modifier, destination_controller):
    source_guide = curve_guide_object(target, source_modifier)
    return copy_curve_guide_state(
        source_guide, target, destination_modifier, destination_controller)


def set_curve_guide_display(target, active_modifier, show_other=True, *, view_layer=None):
    for obj in _data_objects():
        if (
                (is_curve_guide(obj) or
                 bool(obj.get(CURVE_REST_GUIDE_MARKER, False))) and
                getattr(obj, "parent", None) != target
        ):
            set_helper_object_visible(obj, False, view_layer)
    if target is None:
        return
    for modifier in _core().cage_modifiers(target):
        controller = _core().find_controller(target, modifier)
        properties = getattr(controller, "sdh_cage_deform", None)
        if properties is None or str(properties.cage_type) != "CURVE":
            continue
        guide, station_object = ensure_curve_companions(
            target, modifier, controller)
        active = modifier == active_modifier
        editing = bool(
            guide and getattr(guide, "mode", "OBJECT") == "EDIT")
        object_editing = bool(getattr(
            properties, "curve_object_edit_active", False))
        visible = bool(
            getattr(properties, "show_cage", True) and
            (active or show_other or editing or object_editing))
        set_helper_object_visible(guide, visible, view_layer)
        if guide is not None:
            guide.hide_select = not (editing or object_editing)
            try:
                guide.color = (
                    (0.1, 0.9, 1.0, 1.0) if active else
                    (0.18, 0.42, 0.5, 0.5))
            except (AttributeError, TypeError):
                pass
        rest_guide = curve_rest_guide_object(target, modifier)
        if rest_guide is not None:
            rest_guide.hide_select = True
            set_helper_object_visible(rest_guide, False, view_layer)
        set_helper_object_visible(station_object, False, view_layer)


def active_guide_point(guide):
    data = getattr(guide, "data", None)
    for spline in tuple(getattr(data, "splines", ())):
        if spline.type != "BEZIER":
            continue
        selected = tuple(
            point for point in spline.bezier_points
            if point.select_control_point or point.select_left_handle or
            point.select_right_handle)
        if selected:
            return selected[-1]
    target, modifier, controller = context_deform_from_helper(guide)
    properties = getattr(controller, "sdh_cage_deform", None)
    spline = curve_guide_spline(guide)
    if properties is None or spline is None:
        return None
    if not spline.bezier_points:
        return None
    index = min(max(
        int(properties.curve_active_point), 0), len(spline.bezier_points) - 1)
    return spline.bezier_points[index]


def active_curve_control(controller, guide=None):
    properties = getattr(controller, "sdh_cage_deform", None)
    if properties is None:
        return None
    if not properties.curve_points:
        return None
    spline = curve_guide_spline(guide)
    if spline is not None:
        points = tuple(spline.bezier_points)
        if len(properties.curve_points) != len(points):
            return None
        selected = tuple(
            index for index, point in enumerate(points)
            if point.select_control_point or point.select_left_handle or
            point.select_right_handle)
    else:
        selected = ()
    index = selected[-1] if selected else min(max(
        int(properties.curve_active_point), 0), len(properties.curve_points) - 1)
    return properties.curve_points[index]


def finish_curve_edit_sessions(context=None, *, restore_target=False):
    """Leave both Curve editors before a stack-changing operation."""
    context = context or bpy.context
    object_finished = finish_curve_object_edit_sessions(
        context, restore_target=restore_target)
    active = getattr(context, "object", None)
    if not is_curve_guide(active) or getattr(active, "mode", "OBJECT") != "EDIT":
        return bool(object_finished)
    target, _modifier, controller = context_deform_from_helper(active)
    try:
        bpy.ops.object.mode_set(mode="OBJECT")
    except (AttributeError, RuntimeError, TypeError):
        return False
    if controller is not None:
        controller.sdh_cage_deform.curve_edit_mode_active = False
    if restore_target and target is not None:
        _core()._activate(context, target)
    return True


def curve_animation_paths(controller):
    properties = getattr(controller, "sdh_cage_deform", None)
    if properties is None or str(properties.cage_type) != "CURVE":
        return ()
    ensure_curve_station_collection(properties)
    target = _core().find_target(controller)
    modifier = _core().find_modifier(target, controller) if target else None
    ensure_curve_point_collection(
        properties, curve_guide_object(target, modifier))
    paths = []
    for index in range(len(properties.curve_points)):
        prefix = f"sdh_cage_deform.curve_points[{index}]"
        paths.extend((f"{prefix}.bevel", f"{prefix}.tension"))
    for index in range(len(properties.curve_stations)):
        prefix = f"sdh_cage_deform.curve_stations[{index}]"
        paths.extend((
            f"{prefix}.factor", f"{prefix}.scale", f"{prefix}.offset",
            f"{prefix}.radius", f"{prefix}.twist"))
    return tuple(paths)


def keyframe_curve_guide(controller, *, delete=False, group="Simple Deform Cage"):
    target = _core().find_target(controller)
    modifier = _core().find_modifier(target, controller) if target else None
    guide = curve_guide_object(target, modifier)
    data = getattr(guide, "data", None)
    if data is None:
        return 0
    changed = 0
    for spline_index, spline in enumerate(data.splines):
        if spline.type != "BEZIER":
            continue
        for point_index, _point in enumerate(spline.bezier_points):
            prefix = f"splines[{spline_index}].bezier_points[{point_index}]"
            for suffix in (
                    "co", "handle_left", "handle_right", "tilt", "radius"):
                path = f"{prefix}.{suffix}"
                try:
                    result = (
                        data.keyframe_delete(path, group=group)
                        if delete else data.keyframe_insert(path, group=group)
                    )
                except (AttributeError, ReferenceError, RuntimeError, TypeError,
                        ValueError):
                    result = False
                changed += int(bool(result))
    return changed


def _curve_action_has_point_animation(action):
    if action is None:
        return False
    try:
        curves = tuple(_core()._iter_baked_action_fcurves(action))
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        curves = tuple(getattr(action, "fcurves", ()) or ())
    return any(
        "bezier_points[" in str(getattr(curve, "data_path", ""))
        for curve in curves)


def _curve_data_has_point_animation(data):
    """Protect every dependency that assumes the current spline topology."""
    if data is None:
        return False
    # Curve shape keys store one element per authored control point. Replacing
    # or resampling the guide while they exist leaves incompatible key blocks.
    if getattr(data, "shape_keys", None) is not None:
        return True
    animation = getattr(data, "animation_data", None)
    if animation is None:
        return False
    if _curve_action_has_point_animation(getattr(animation, "action", None)):
        return True
    if any(
            "bezier_points[" in str(getattr(driver, "data_path", ""))
            for driver in tuple(getattr(animation, "drivers", ()) or ())
    ):
        return True

    pending = [
        strip
        for track in tuple(getattr(animation, "nla_tracks", ()) or ())
        for strip in tuple(getattr(track, "strips", ()) or ())
    ]
    while pending:
        strip = pending.pop()
        if _curve_action_has_point_animation(getattr(strip, "action", None)):
            return True
        pending.extend(tuple(getattr(strip, "strips", ()) or ()))
    return False


def _local_curve_samples(spline, resolution):
    points = tuple(spline.bezier_points)
    segments = [(index, index + 1) for index in range(len(points) - 1)]
    if spline.use_cyclic_u:
        segments.append((len(points) - 1, 0))
    samples = []
    distance = 0.0
    previous = None
    for segment_index, (first, second) in enumerate(segments):
        for step in range(resolution + 1):
            if segment_index and step == 0:
                continue
            factor = step / float(resolution)
            position, tangent, tilt, radius = _bezier_sample(
                points[first], points[second], factor)
            if previous is not None:
                distance += (position - previous).length
            samples.append((
                distance, Vector(position), Vector(tangent),
                float(tilt), float(radius)))
            previous = position
    return tuple(samples), max(float(distance), 1.0e-8)


def _sample_local_curve(samples, distance):
    distances = tuple(item[0] for item in samples)
    distance = min(max(float(distance), 0.0), float(distances[-1]))
    if distance <= distances[0]:
        return samples[0][1:]
    if distance >= distances[-1]:
        return samples[-1][1:]
    index = min(max(
        bisect_right(distances, distance) - 1, 0), len(samples) - 2)
    first = samples[index]
    second = samples[index + 1]
    factor = (
        (distance - float(first[0])) /
        max(float(second[0] - first[0]), 1.0e-8))
    position = first[1].lerp(second[1], factor)
    tangent = _normalized_or(first[2].lerp(second[2], factor), first[2])
    tilt = float(first[3]) + (float(second[3]) - float(first[3])) * factor
    radius = float(first[4]) + (float(second[4]) - float(first[4])) * factor
    return position, tangent, tilt, radius


def _curve_relation_context(controller):
    properties = getattr(controller, "sdh_cage_deform", None)
    if (
            properties is None or
            str(getattr(properties, "cage_type", "")) != "CURVE"
    ):
        return None, None, None, None, None
    target = _core().find_target(controller)
    modifier = _core().find_modifier(target, controller) if target else None
    guide = curve_guide_object(target, modifier)
    return target, modifier, properties, guide, curve_guide_spline(guide)


def _curve_relation_signature(controller):
    target, modifier, properties, guide, spline = _curve_relation_context(
        controller)
    if target is None or modifier is None or spline is None:
        return None
    guide_signature, _guide, _relative = _curve_guide_signature(properties)
    try:
        rotation = tuple(float(value).hex() for value in
                         _core()._controller_rotation_xyz(controller))
        location = tuple(float(value).hex() for value in controller.location)
        size = tuple(float(value).hex() for value in properties.size)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None
    return (
        "SDH_CURVE_RELATION_V1",
        _core().curve_control_mode_identifier(properties),
        bool(spline.use_cyclic_u),
        location,
        rotation,
        size,
        guide_signature,
    )


def _offset_curve_data_y(guide, delta):
    delta = float(delta)
    data = getattr(guide, "data", None)
    if data is None or abs(delta) <= 1.0e-9:
        return False
    changed = False
    for spline in tuple(getattr(data, "splines", ())):
        if str(getattr(spline, "type", "")) != "BEZIER":
            continue
        for point in spline.bezier_points:
            for attribute in ("co", "handle_left", "handle_right"):
                value = Vector(getattr(point, attribute))
                value.y += delta
                setattr(point, attribute, value)
            changed = True
    if changed:
        data.update_tag()
    return changed


def _constrain_curve_endpoints(properties, spline):
    """Keep the two open-guide endpoints inside the authored cage box."""
    if spline is None or bool(spline.use_cyclic_u):
        return False
    points = tuple(spline.bezier_points)
    if len(points) < 2:
        return False
    half = Vector((
        max(abs(float(properties.size[0])) * 0.5, 1.0e-8),
        max(abs(float(properties.size[1])) * 0.5, 1.0e-8),
        max(abs(float(properties.size[2])) * 0.5, 1.0e-8),
    ))
    changed = False
    for point in (points[0], points[-1]):
        original = Vector(point.co)
        clamped = Vector(
            min(max(float(original[axis]), -half[axis]), half[axis])
            for axis in range(3))
        correction = clamped - original
        if correction.length <= 1.0e-9:
            continue
        point.co = clamped
        point.handle_left = Vector(point.handle_left) + correction
        point.handle_right = Vector(point.handle_right) + correction
        changed = True
    return changed


def sync_curve_cage_relation(controller, *, force=False):
    """Apply the active Curve/cage relationship outside depsgraph evaluation."""
    pointer = _pointer(controller)
    if not pointer or pointer in _CURVE_RELATION_GUARD:
        return False, 0.0
    before = _curve_relation_signature(controller)
    if before is None:
        return False, 0.0
    if not force and _CURVE_RELATION_SNAPSHOTS.get(pointer) == before:
        return False, 0.0

    target, _modifier, properties, guide, spline = _curve_relation_context(
        controller)
    if target is None or guide is None or spline is None:
        return False, 0.0
    changed = False
    local_shift = 0.0
    _CURVE_RELATION_GUARD.add(pointer)
    try:
        if (
                not bool(spline.use_cyclic_u) and
                _core().curve_control_mode_identifier(properties) == "CAGE"
        ):
            changed = _constrain_curve_endpoints(properties, spline)
            if changed:
                guide.data.update_tag()
                target.update_tag()
        if changed:
            _core().sync_controller(
                controller, pull_transform=False, sync_mode="push")
        _CURVE_RELATION_SNAPSHOTS[pointer] = _curve_relation_signature(controller)
    finally:
        _CURVE_RELATION_GUARD.discard(pointer)
    return changed, local_shift


def apply_curve_source_boundary_relation(controller, center_shift_local):
    """Keep the Curve-mode guide fixed while its source domain moves."""
    pointer = _pointer(controller)
    if not pointer or pointer in _CURVE_RELATION_GUARD:
        return False
    target, _modifier, properties, guide, _spline = _curve_relation_context(
        controller)
    if (
            target is None or guide is None or
            _core().curve_control_mode_identifier(properties) != "CURVE"
    ):
        return False
    _CURVE_RELATION_GUARD.add(pointer)
    try:
        changed = _offset_curve_data_y(guide, -float(center_shift_local))
        if changed:
            guide.data.update_tag()
            target.update_tag()
        return changed
    finally:
        _CURVE_RELATION_GUARD.discard(pointer)


def apply_curve_cage_boundary_relation(
        controller, center_shift_local, boundary_mode):
    """Preserve the guide while a Cage-mode boundary moves, then clamp ends."""
    pointer = _pointer(controller)
    if not pointer or pointer in _CURVE_RELATION_GUARD:
        return False
    target, _modifier, properties, guide, spline = _curve_relation_context(
        controller)
    if (
            target is None or guide is None or spline is None or
            bool(spline.use_cyclic_u) or
            _core().curve_control_mode_identifier(properties) != "CAGE"
    ):
        return False
    changed = False
    _CURVE_RELATION_GUARD.add(pointer)
    try:
        if str(boundary_mode).upper() != "TRANSLATE":
            changed = _offset_curve_data_y(
                guide, -float(center_shift_local)) or changed
        changed = _constrain_curve_endpoints(properties, spline) or changed
        if changed:
            guide.data.update_tag()
            target.update_tag()
    finally:
        _CURVE_RELATION_GUARD.discard(pointer)
    return changed


def record_curve_relation_snapshot(controller):
    pointer = _pointer(controller)
    if pointer:
        _CURVE_RELATION_SNAPSHOTS[pointer] = _curve_relation_signature(controller)


def _curve_relation_timer():
    queued = tuple(_CURVE_RELATION_QUEUE.values())
    _CURVE_RELATION_QUEUE.clear()
    for controller in queued:
        try:
            sync_curve_cage_relation(controller)
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            continue
    return 0.01 if _CURVE_RELATION_QUEUE else None


def request_curve_relation_sync_from_update(updated_id):
    """Queue one changed managed guide for relationship synchronization."""
    try:
        updated_id = getattr(updated_id, "original", updated_id)
    except (AttributeError, ReferenceError, RuntimeError):
        return False
    guides = ()
    if isinstance(updated_id, bpy.types.Object) and is_curve_guide(updated_id):
        guides = (updated_id,)
    elif isinstance(updated_id, bpy.types.Curve):
        guides = tuple(
            obj for obj in _data_objects()
            if is_curve_guide(obj) and getattr(obj, "data", None) == updated_id)
    if not guides:
        return False

    queued = False
    for guide in guides:
        _target, _modifier, controller = context_deform_from_helper(guide)
        pointer = _pointer(controller)
        if not pointer or pointer in _CURVE_RELATION_GUARD:
            continue
        signature = _curve_relation_signature(controller)
        if signature is None or _CURVE_RELATION_SNAPSHOTS.get(pointer) == signature:
            continue
        _CURVE_RELATION_QUEUE[pointer] = controller
        queued = True
    if not queued:
        return False
    try:
        if not bpy.app.timers.is_registered(_curve_relation_timer):
            bpy.app.timers.register(_curve_relation_timer, first_interval=0.0)
    except (AttributeError, RuntimeError, ValueError):
        return False
    return True


def clear_curve_relation_sync():
    try:
        if bpy.app.timers.is_registered(_curve_relation_timer):
            bpy.app.timers.unregister(_curve_relation_timer)
    except (AttributeError, RuntimeError, ValueError):
        pass
    _CURVE_RELATION_QUEUE.clear()
    _CURVE_RELATION_GUARD.clear()
    _CURVE_RELATION_SNAPSHOTS.clear()


def equalize_curve_points(guide, properties, count):
    """Resample the managed guide at equal arc-length intervals."""
    spline = curve_guide_spline(guide)
    if spline is None:
        return False
    closed = bool(spline.use_cyclic_u)
    count = min(max(
        int(count), 3 if closed else CURVE_POINT_MINIMUM),
        CURVE_POINT_MAXIMUM)
    resolution = max(
        int(getattr(properties, "curve_resolution", 24)) * 4, 64)
    samples, total_length = _local_curve_samples(spline, resolution)
    if len(samples) < 2:
        return False
    distances = (
        tuple(total_length * index / float(count) for index in range(count))
        if closed else
        tuple(
            total_length * index / float(max(count - 1, 1))
            for index in range(count))
    )
    values = tuple(_sample_local_curve(samples, value) for value in distances)

    data = guide.data
    data.splines.clear()
    rebuilt = data.splines.new("BEZIER")
    rebuilt.bezier_points.add(count - 1)
    rebuilt.use_cyclic_u = closed
    handle_span = total_length / float(count if closed else max(count - 1, 1))
    for point, value in zip(rebuilt.bezier_points, values):
        position, tangent, tilt, radius = value
        point.co = position
        point.handle_left_type = "FREE"
        point.handle_right_type = "FREE"
        point.tilt = tilt
        point.radius = radius
        point.select_control_point = False
        point.select_left_handle = False
        point.select_right_handle = False
        point.handle_left = position - tangent * handle_span / 3.0
        point.handle_right = position + tangent * handle_span / 3.0
    data.update_tag()

    ensure_curve_point_collection(properties, guide, reset=True)
    properties.curve_active_point = min(
        max(int(properties.curve_active_point), 0), count - 1)
    properties.curve_equalize_count = count
    controller = getattr(properties, "id_data", None)
    if _core().is_cage_controller(controller):
        apply_all_curve_point_handles(controller)
        target = _core().find_target(controller)
        if target is not None:
            target.update_tag()
        sync_curve_cage_relation(controller, force=True)
    return True


def _curve_object_edit_context(context=None):
    context = context or bpy.context
    for candidate in _data_objects():
        properties = getattr(candidate, "sdh_cage_deform", None)
        if (
                properties is None or
                str(getattr(properties, "cage_type", "")) != "CURVE" or
                not bool(getattr(properties, "curve_object_edit_active", False))
        ):
            continue
        target = _core().find_target(candidate)
        modifier = (
            _core().find_modifier(target, candidate) if target is not None else None)
        if target is not None and modifier is not None:
            return target, modifier, candidate
    return None, None, None


def _activate_curve_object_selection(context, target, controller, guide):
    try:
        target.select_set(True)
        for related in _core()._target_cage_controllers(target):
            set_helper_object_visible(
                related, True, getattr(context, "view_layer", None))
            related.select_set(True)
        set_helper_object_visible(
            guide, True, getattr(context, "view_layer", None))
        guide.hide_select = False
        guide.select_set(True)
        context.view_layer.objects.active = target
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return False


def remove_curve_draw_handlers():
    while _CURVE_DRAW_HANDLERS:
        handler = _CURVE_DRAW_HANDLERS.pop()
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handler, "WINDOW")
        except (ReferenceError, RuntimeError, TypeError, ValueError):
            pass


def finish_curve_object_edit_sessions(context=None, *, restore_target=False):
    finished = 0
    for operator in tuple(_CURVE_MODAL_OPERATORS):
        try:
            operator._finish_modal(
                context or bpy.context, restore_target=bool(restore_target))
            finished += 1
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            try:
                _CURVE_MODAL_OPERATORS.remove(operator)
            except ValueError:
                pass
    return finished


def _curve_billboard_matrix(context, world_location):
    region_data = getattr(context, "region_data", None) or getattr(
        getattr(context, "space_data", None), "region_3d", None)
    if region_data is None:
        return Matrix.Translation(world_location)
    rotation = region_data.view_matrix.inverted_safe().to_3x3().to_4x4()
    return Matrix.Translation(world_location) @ rotation


def _curve_connector_matrix(start, end):
    start = Vector(start)
    direction = Vector(end) - start
    if direction.length <= 1.0e-8:
        return Matrix.Translation(start)
    y_axis = direction.normalized()
    x_axis = y_axis.orthogonal().normalized()
    z_axis = x_axis.cross(y_axis).normalized()
    matrix = Matrix.Identity(4)
    matrix.translation = start
    matrix.col[0][0:3] = x_axis
    matrix.col[1][0:3] = direction
    matrix.col[2][0:3] = z_axis
    return matrix


def _curve_disc_triangles(segments=16, radius=0.72):
    vertices = []
    for index in range(segments):
        first = math.tau * index / float(segments)
        second = math.tau * (index + 1) / float(segments)
        vertices.extend((
            (0.0, 0.0, 0.0),
            (math.cos(first) * radius, math.sin(first) * radius, 0.0),
            (math.cos(second) * radius, math.sin(second) * radius, 0.0),
        ))
    return tuple(vertices)


def curve_moved_handle_values(
        co, left, right, kind, delta, *, independent=False):
    """Move one Bezier handle, mirroring the opposite side unless Alt is held."""
    co = Vector(co)
    left = Vector(left)
    right = Vector(right)
    delta = Vector(delta)
    kind = str(kind).upper()
    if kind == "LEFT":
        left = left + delta
        if not independent:
            right = co - (left - co)
    elif kind == "RIGHT":
        right = right + delta
        if not independent:
            left = co - (right - co)
    return co, left, right


def curve_blank_click_release_state(
        last_time, last_position, start, end, now, *,
        click_distance=8.0, click_interval=0.45):
    """Detect two nearby blank clicks without treating a drag as an exit."""
    start = Vector(start)
    end = Vector(end)
    if (end - start).length > float(click_distance):
        return False, -1.0, tuple(start)
    previous = Vector(last_position)
    double_click = (
        float(last_time) >= 0.0 and
        float(now) - float(last_time) <= float(click_interval) and
        (start - previous).length <= float(click_distance)
    )
    return double_click, float(now), tuple(start)


class SDHCurveControlGizmo(Gizmo):
    bl_idname = "SDH_GT_curve_control"
    bl_label = "Curve Point or Bezier Handle"
    bl_target_properties = (
        {"id": "tooltip", "type": "FLOAT", "array_length": 1},
    )

    __slots__ = (
        "point_shape", "handle_shape", "connector_shape",
        "point_index", "element_kind",
        "stage_target", "stage_modifier", "stage_controller",
        "_tooltip_kind", "_tooltip_owner",
    )

    def setup(self):
        self.point_shape = self.new_custom_shape("TRIS", (
            (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0),
            (0.0, 1.0, 0.0), (0.0, -1.0, 0.0), (-1.0, 0.0, 0.0),
        ))
        self.handle_shape = self.new_custom_shape(
            "TRIS", _curve_disc_triangles())
        self.connector_shape = self.new_custom_shape("LINES", (
            (0.0, 0.0, 0.0), (0.0, 1.0, 0.0),
        ))
        self.point_index = 0
        self.element_kind = "POINT"
        self.stage_target = None
        self.stage_modifier = None
        self.stage_controller = None
        self._tooltip_kind = ""
        self._tooltip_owner = 0
        self.use_tooltip = True
        self.use_draw_modal = False
        self.use_draw_value = False
        self.scale_basis = 0.12

    def _stage(self):
        target = getattr(self, "stage_target", None)
        modifier = getattr(self, "stage_modifier", None)
        controller = getattr(self, "stage_controller", None)
        if target is None or modifier is None or controller is None:
            return None, None, None
        try:
            live_modifier = next((
                item for item in _core().cage_modifiers(target)
                if item == modifier), None)
            live_controller = (
                _core().find_controller(target, live_modifier)
                if live_modifier is not None else None)
            if live_controller != controller:
                return None, None, None
            return target, live_modifier, live_controller
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            return None, None, None

    def _update(self, context):
        target, modifier, controller = self._stage()
        if target is None:
            return None
        properties = controller.sdh_cage_deform
        guide = curve_guide_object(target, modifier)
        spline = curve_guide_spline(guide)
        index = int(getattr(self, "point_index", 0))
        if (
                spline is None or index < 0 or
                index >= len(spline.bezier_points) or
                index >= len(properties.curve_points)
        ):
            return None
        point = spline.bezier_points[index]
        kind = str(getattr(self, "element_kind", "POINT"))
        local = {
            "LEFT": point.handle_left,
            "RIGHT": point.handle_right,
        }.get(kind, point.co)
        world = guide.matrix_world @ Vector(local)
        self.matrix_basis = _curve_billboard_matrix(context, world)
        self.scale_basis = 0.13 if kind == "POINT" else 0.09
        selected = bool(properties.curve_points[index].selected)
        active = int(properties.curve_active_point) == index
        if kind == "POINT":
            self.color = (
                (0.08, 0.86, 1.0) if selected else (0.24, 0.42, 0.5))
            self.color_highlight = (0.72, 1.0, 1.0)
        else:
            self.color = (
                (1.0, 0.45, 0.18) if active else (0.42, 0.32, 0.28))
            self.color_highlight = (1.0, 0.82, 0.42)
        self.alpha = 0.95 if selected or active else 0.62
        self.alpha_highlight = 1.0
        try:
            owner = int(properties.as_pointer())
        except (AttributeError, ReferenceError, TypeError, ValueError):
            owner = id(properties)
        if self._tooltip_kind != kind or self._tooltip_owner != owner:
            tooltip = (
                "tooltip_curve_point" if kind == "POINT" else
                "tooltip_curve_handle")
            self.target_set_prop("tooltip", properties, tooltip)
            self._tooltip_kind = kind
            self._tooltip_owner = owner
        return guide, point, world

    def draw(self, context):
        updated = self._update(context)
        if updated is None:
            return
        guide, point, world = updated
        kind = str(getattr(self, "element_kind", "POINT"))
        if kind != "POINT":
            control_world = guide.matrix_world @ Vector(point.co)
            connector = _curve_connector_matrix(world, control_world)
            draw_cage_custom_shape(
                self, self.connector_shape, matrix=connector)
        draw_cage_custom_shape(
            self,
            self.point_shape if kind == "POINT" else self.handle_shape,
        )

    def draw_select(self, context, select_id):
        target, _modifier, controller = self._stage()
        properties = getattr(controller, "sdh_cage_deform", None)
        if (
                target is None or properties is None or
                bool(getattr(properties, "curve_object_edit_active", False))
        ):
            return
        if self._update(context) is not None:
            draw_cage_custom_shape(
                self,
                self.point_shape if self.element_kind == "POINT" else
                self.handle_shape,
                select_id=select_id,
            )

    def invoke(self, context, event):
        target, modifier, controller = self._stage()
        if target is None:
            return {"CANCELLED"}
        try:
            target.modifiers.active = modifier
            guide = curve_guide_object(target, modifier)
            _activate_curve_object_selection(
                context, target, controller, guide)
            result = bpy.ops.sdh.edit_curve_cage_object(
                "INVOKE_DEFAULT",
                controller_uuid=str(controller.get(
                    _core().CONTROLLER_UUID, "")),
                toggle=False,
                start_drag=True,
                start_kind=str(self.element_kind),
                start_index=int(self.point_index),
                start_mouse_region_x=int(event.mouse_region_x),
                start_mouse_region_y=int(event.mouse_region_y),
                start_extend=bool(getattr(event, "shift", False)),
            )
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            return {"CANCELLED"}
        if "RUNNING_MODAL" not in result:
            return {"CANCELLED"}
        try:
            _core()._selection_sync_notify()
            _core()._queue_stage_selection_restore(target, modifier)
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            pass
        return {"FINISHED"}

    def modal(self, _context, _event, _tweak):
        # Blender only registers a custom Gizmo as an interactive target when
        # it exposes the complete invoke/modal contract. The persistent Curve
        # editor owns the actual drag after invoke() starts it.
        return {"FINISHED"}


class SDHCurveControlGizmoGroup(GizmoGroup):
    bl_idname = "SDH_GGT_curve_controls"
    bl_label = "Curve Cage Controls"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        target, modifier, controller = _core().resolve_context_deform(
            context, fallback=False)
        if target is None:
            target, modifier, controller = _curve_object_edit_context(context)
        properties = getattr(controller, "sdh_cage_deform", None)
        return bool(
            target is not None and modifier is not None and
            properties is not None and
            str(properties.cage_type) == "CURVE" and
            bool(getattr(modifier, "show_viewport", True)) and
            bool(getattr(properties, "show_cage", True)))

    def setup(self, _context):
        self.control_handles = ()

    def _ensure_count(self, count):
        handles = list(self.control_handles)
        for slot in range(len(handles), count * 3):
            handle = self.gizmos.new(SDHCurveControlGizmo.bl_idname)
            handle.point_index = slot // 3
            handle.element_kind = ("POINT", "LEFT", "RIGHT")[slot % 3]
            handle.hide = True
            handles.append(handle)
        self.control_handles = tuple(handles)

    def draw_prepare(self, context):
        target, modifier, controller = _core().resolve_context_deform(
            context, fallback=False)
        if target is None:
            target, modifier, controller = _curve_object_edit_context(context)
        properties = getattr(controller, "sdh_cage_deform", None)
        if properties is None:
            for handle in self.control_handles:
                handle.hide = True
            return
        guide = curve_guide_object(target, modifier)
        spline = curve_guide_spline(guide)
        if spline is None:
            for handle in self.control_handles:
                handle.hide = True
            return
        count = len(spline.bezier_points)
        # Gizmo drawing runs in Blender's restricted read-only context. Point
        # collections are synchronized by creation/edit/update entry points.
        if len(properties.curve_points) != count:
            for handle in self.control_handles:
                handle.hide = True
            return
        self._ensure_count(count)
        active = min(max(int(properties.curve_active_point), 0), count - 1)
        for slot, handle in enumerate(self.control_handles):
            index = slot // 3
            kind = ("POINT", "LEFT", "RIGHT")[slot % 3]
            visible = index < count and (
                kind == "POINT" or index == active or
                (index < len(properties.curve_points) and
                 properties.curve_points[index].selected))
            handle.hide = not visible
            if not visible:
                continue
            handle.point_index = index
            handle.element_kind = kind
            handle.stage_target = target
            handle.stage_modifier = modifier
            handle.stage_controller = controller


class SDH_OT_edit_curve_cage_object(Operator):
    bl_idname = "sdh.edit_curve_cage_object"
    bl_label = "Edit Curve Points"
    bl_description = (
        "Edit Curve cage points and Bezier handles persistently in Object Mode")
    bl_options = {"REGISTER", "INTERNAL"}

    controller_name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    controller_uuid: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    toggle: BoolProperty(default=True, options={"HIDDEN", "SKIP_SAVE"})
    start_drag: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})
    start_box_select: BoolProperty(
        default=False, options={"HIDDEN", "SKIP_SAVE"})
    arm_box_select: BoolProperty(
        default=False, options={"HIDDEN", "SKIP_SAVE"})
    start_kind: StringProperty(
        default="POINT", options={"HIDDEN", "SKIP_SAVE"})
    start_index: IntProperty(default=-1, options={"HIDDEN", "SKIP_SAVE"})
    start_mouse_region_x: IntProperty(
        default=0, options={"HIDDEN", "SKIP_SAVE"})
    start_mouse_region_y: IntProperty(
        default=0, options={"HIDDEN", "SKIP_SAVE"})
    start_extend: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})

    _MOUSE_EVENTS = {
        "LEFTMOUSE", "MIDDLEMOUSE", "RIGHTMOUSE", "MOUSEMOVE",
        "INBETWEEN_MOUSEMOVE", "WHEELUPMOUSE", "WHEELDOWNMOUSE",
        "WHEELINMOUSE", "WHEELOUTMOUSE", "TRACKPADPAN", "TRACKPADZOOM",
    }

    @classmethod
    def poll(cls, context):
        if not (
                getattr(context, "area", None) and
                context.area.type == "VIEW_3D"):
            return False
        if not tuple(getattr(context, "selected_objects", ()) or ()):
            # A stale Curve Workspace Tool must not swallow Blender's native
            # object box-select after the cage target was deselected.
            return True
        target, modifier, controller = _core().resolve_context_deform(context)
        properties = getattr(controller, "sdh_cage_deform", None)
        return bool(
            target is not None and modifier is not None and
            properties is not None and str(properties.cage_type) == "CURVE")

    def _controller(self):
        return controller_from_uuid(getattr(self, "_controller_uuid", ""))

    @staticmethod
    def _inside_region(region, event):
        return (
            region.x <= event.mouse_x <= region.x + region.width and
            region.y <= event.mouse_y <= region.y + region.height)

    def _inside_ui_region(self, context, event):
        area = getattr(self, "_area", None) or getattr(context, "area", None)
        if area is None:
            return False
        for candidate in tuple(getattr(area, "regions", ())):
            if candidate is getattr(self, "_window_region", None):
                continue
            if str(getattr(candidate, "type", "")) not in {
                    "UI", "TOOLS", "HEADER", "TOOL_HEADER", "FOOTER"}:
                continue
            if (
                    candidate.x <= event.mouse_x <= candidate.x + candidate.width and
                    candidate.y <= event.mouse_y <= candidate.y + candidate.height
            ):
                return True
        return False

    @staticmethod
    def _region_position(region, event):
        return Vector((
            float(event.mouse_x - region.x),
            float(event.mouse_y - region.y)))

    @staticmethod
    def _tool_settings(context):
        return _curve_tool_settings(context)

    @classmethod
    def _proportional_enabled(cls, context):
        return curve_proportional_enabled(context)

    def _proportional_weights(self, context, *, force_global=False):
        """Return transform weights, optionally spanning the whole guide.

        Point radius and roll are profile edits rather than spatial moves.  A
        user-enabled Full Curve Falloff must therefore bypass Blender's
        current proportional-edit toggle and derive a radius that reaches the
        farthest guide point.  Spatial G/R/S transforms keep the normal
        Blender falloff semantics.
        """
        force_global = bool(force_global)
        weights, radius = curve_proportional_weights(
            getattr(self, "_transform_world_points", {}),
            getattr(self, "_transform_selected_indices", ()),
            context,
            getattr(self, "_proportional_radius", None),
            force=force_global,
            cover_all=force_global,
        )
        self._proportional_radius = radius
        return weights

    def _initialize_proportional_radius(self, context):
        self._proportional_radius = _curve_proportional_radius(
            getattr(self, "_transform_world_points", {}),
            getattr(self, "_transform_selected_indices", ()),
            context,
            getattr(self, "_proportional_radius", None),
        )

    def _guide_context(self):
        controller = self._controller()
        target = _core().find_target(controller) if controller is not None else None
        modifier = (
            _core().find_modifier(target, controller) if target is not None else None)
        guide = curve_guide_object(target, modifier)
        spline = curve_guide_spline(guide)
        return target, modifier, controller, guide, spline

    def _set_header(self, context):
        area = getattr(self, "_area", None) or getattr(context, "area", None)
        if area is None:
            return
        translate = bpy.app.translations.pgettext_iface
        if self._state == "TRANSFORM":
            mode = translate({
                "MOVE": "Move",
                "ROTATE": "Rotate",
                "SCALE": "Scale",
                "RADIUS": "Radius",
                "TILT": "Twist",
            }.get(str(self._transform_mode), "Move"))
            hint = translate(
                "X/Y/Z Axis | Shift Precise | Ctrl Snap | "
                "Click/Enter Confirm | Esc/Right Mouse Cancel")
            if str(getattr(self, "_transform_kind", "POINT")) in {
                    "LEFT", "RIGHT"}:
                hint += "   |   " + translate("Alt Independent Handle")
            if self._proportional_enabled(context):
                settings = self._tool_settings(context)
                falloff = translate(str(getattr(
                    settings, "proportional_edit_falloff", "SMOOTH")).title())
                hint += translate(" | Proportional | Wheel Radius")
                hint += (
                    f" | {falloff} "
                    f"{float(getattr(self, '_proportional_radius', 0.0)):.3f}")
            area.header_text_set(
                f"{translate('Curve Edit Mode')}: {mode}   |   {hint}")
        elif self._state in {"BOX_READY", "DRAGGING"}:
            area.header_text_set(translate(
                "Curve Box Select: drag over points or handles | "
                "Shift Add | Ctrl Subtract | Esc cancels"))
        else:
            controls = translate(
                "Curve Edit Mode: G Move | R Rotate | S Scale | B Box Select | "
                "Shift Add | A Select All | Alt+A Clear | I Key | "
                "Double-click blank / Esc / Right Mouse exits")
            controls += "   |   " + translate(
                "Alt+S Radius | Ctrl+T Twist | O Proportional")
            area.header_text_set(controls)
        area.tag_redraw()

    def _element_world(self, guide, spline, kind, index):
        point = spline.bezier_points[index]
        local = {
            "LEFT": point.handle_left,
            "RIGHT": point.handle_right,
        }.get(kind, point.co)
        return guide.matrix_world @ Vector(local)

    def _hit_element(self, context, event):
        from bpy_extras import view3d_utils
        _target, _modifier, controller, guide, spline = self._guide_context()
        if controller is None or spline is None:
            return None
        properties = controller.sdh_cage_deform
        ensure_curve_point_collection(properties, guide)
        mouse = self._region_position(self._window_region, event)
        try:
            ui_scale = float(context.preferences.system.ui_scale)
        except (AttributeError, TypeError, ValueError):
            ui_scale = 1.0
        active = min(max(
            int(properties.curve_active_point), 0), len(spline.bezier_points) - 1)
        candidates = []
        for index, point in enumerate(spline.bezier_points):
            kinds = ["POINT"]
            if index == active or properties.curve_points[index].selected:
                kinds.extend(("LEFT", "RIGHT"))
            for kind in kinds:
                world = self._element_world(guide, spline, kind, index)
                screen = view3d_utils.location_3d_to_region_2d(
                    self._window_region, self._region_data, world)
                if screen is None:
                    continue
                radius = (12.0 if kind == "POINT" else 10.0) * ui_scale
                distance = (Vector(screen) - mouse).length
                if distance > radius:
                    continue
                depth = -float((self._region_data.view_matrix @ world).z)
                candidates.append((distance, depth, kind, index))
        if not candidates:
            return None
        _distance, _depth, kind, index = min(candidates)
        return kind, index

    def _over_other_gizmo(
            self, context, event, controller=None, *, include_picker=False):
        """Hit-test regular cage controls while Curve edit owns the pointer.

        Curve editing is a persistent modal session, so a blank click would
        otherwise be interpreted as the start of a Curve box selection even
        when it is over a top/bottom boundary or another cage handle.  Reuse
        the shared cage hit-test used by FFD editing; this keeps the screen
        projection and handle tolerances identical across cage types.
        """
        operator_type = getattr(
            _core(), "SDH_OT_box_select_ffd_points", None)
        checker = getattr(operator_type, "_over_other_gizmo", None)
        if not callable(checker):
            return False
        try:
            return bool(checker(
                self, context, event, controller or self._controller(),
                include_picker=bool(include_picker)))
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            return False

    def _other_stage_gizmo_at_event(self, context, event):
        """Return an inactive cage stage whose picker owns this press."""
        operator_type = getattr(
            _core(), "SDH_OT_box_select_ffd_points", None)
        checker = getattr(operator_type, "_other_stage_gizmo_at_event", None)
        if not callable(checker):
            return None
        try:
            return checker(self, context, event)
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            return None

    @staticmethod
    def _selected_indices(properties):
        return tuple(
            index for index, point in enumerate(properties.curve_points)
            if point.selected)

    def _set_selection(self, properties, spline, indices, *, active=None):
        selected = set(int(index) for index in indices)
        pointer = _pointer(getattr(properties, "id_data", None))
        if pointer:
            _POINT_SYNC_GUARD.add(pointer)
        try:
            for index, control in enumerate(properties.curve_points):
                value = index in selected
                control.selected = value
                if index < len(spline.bezier_points):
                    point = spline.bezier_points[index]
                    point.select_control_point = value
                    point.select_left_handle = False
                    point.select_right_handle = False
            if active is not None and 0 <= int(active) < len(properties.curve_points):
                properties.curve_active_point = int(active)
        finally:
            if pointer:
                _POINT_SYNC_GUARD.discard(pointer)

    def _select_for_pointer(self, properties, spline, index, extend):
        current = set(self._selected_indices(properties))
        selected, collapse_on_click = _core().ffd_pointer_selection_update(
            current, {int(index)}, extend=bool(extend))
        active = (
            index if index in selected else
            min(selected) if selected else None)
        self._set_selection(properties, spline, selected, active=active)
        return selected, collapse_on_click

    def _begin_transform(self, context, event, mode, *, kind="POINT", index=-1):
        _target, _modifier, controller, guide, spline = self._guide_context()
        if controller is None or spline is None:
            return False
        properties = controller.sdh_cage_deform
        selected = self._selected_indices(properties)
        if kind != "POINT":
            selected = (index,)
        if not selected:
            return False
        selected = tuple(sorted(set(int(item) for item in selected)))
        transform_indices = (
            tuple(range(len(spline.bezier_points)))
            if kind == "POINT" else selected)
        self._transform_mode = str(mode)
        self._transform_kind = str(kind)
        self._transform_index = int(index)
        self._transform_selected_indices = selected
        self._transform_axis = None
        self._transform_initial_mouse = Vector((
            float(getattr(event, "mouse_region_x", 0)),
            float(getattr(event, "mouse_region_y", 0))))
        self._transform_original = {
            point_index: (
                Vector(spline.bezier_points[point_index].co),
                Vector(spline.bezier_points[point_index].handle_left),
                Vector(spline.bezier_points[point_index].handle_right),
            )
            for point_index in transform_indices
        }
        self._transform_original_handle_types = {
            point_index: (
                str(spline.bezier_points[point_index].handle_left_type),
                str(spline.bezier_points[point_index].handle_right_type),
            )
            for point_index in transform_indices
        }
        self._transform_original_linked = {
            point_index: bool(
                properties.curve_points[point_index].handles_linked)
            for point_index in transform_indices
        }
        self._transform_original_radius = {
            point_index: float(spline.bezier_points[point_index].radius)
            for point_index in transform_indices
        }
        self._transform_original_tilt = {
            point_index: float(spline.bezier_points[point_index].tilt)
            for point_index in transform_indices
        }
        self._transform_cancel_state = {
            "controller_location": Vector(controller.location),
            "controller_scale": Vector(controller.scale),
            "size": Vector(properties.size),
            "points": tuple(
                (
                    Vector(point.co),
                    Vector(point.handle_left),
                    Vector(point.handle_right),
                    str(point.handle_left_type),
                    str(point.handle_right_type),
                    float(point.radius),
                    float(point.tilt),
                )
                for point in spline.bezier_points
            ),
        }
        pivot = sum(
            (self._transform_original[point_index][0]
             for point_index in selected),
            Vector((0.0, 0.0, 0.0))) / len(selected)
        self._transform_pivot_local = pivot
        self._transform_pivot_world = guide.matrix_world @ pivot
        self._transform_world_points = {
            point_index: guide.matrix_world @ values[0]
            for point_index, values in self._transform_original.items()
        }
        try:
            proportional_radius = float(getattr(
                self, "_proportional_radius", math.nan))
        except (TypeError, ValueError):
            proportional_radius = math.nan
        if not math.isfinite(proportional_radius):
            self._initialize_proportional_radius(context)
        self._transform_anchor_world = self._element_world(
            guide, spline, kind, index if index >= 0 else selected[0])
        self._pointer_click_indices = ()
        self._pointer_click_active = -1
        self._pointer_dragged = False
        self._state = "TRANSFORM"
        self._set_header(context)
        return True

    def _begin_pointer_transform(
            self, context, event, properties, spline, kind, index, extend):
        selected, collapse_on_click = self._select_for_pointer(
            properties, spline, index, extend)
        if index not in selected:
            return False
        if not self._begin_transform(
                context, event, "MOVE", kind=kind, index=index):
            return False
        if collapse_on_click:
            self._pointer_click_indices = (int(index),)
            self._pointer_click_active = int(index)
        return True

    def _local_move_delta(self, event, guide):
        from bpy_extras import view3d_utils
        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        if bool(getattr(event, "shift", False)):
            mouse = self._transform_initial_mouse + (
                mouse - self._transform_initial_mouse) * 0.1
        current = view3d_utils.region_2d_to_location_3d(
            self._window_region, self._region_data,
            mouse, self._transform_anchor_world)
        start = view3d_utils.region_2d_to_location_3d(
            self._window_region, self._region_data,
            self._transform_initial_mouse, self._transform_anchor_world)
        world_delta = Vector(current) - Vector(start)
        if self._transform_axis is not None:
            axis_world = Vector((0.0, 0.0, 0.0))
            axis_world[self._transform_axis] = 1.0
            world_delta = axis_world * world_delta.dot(axis_world)
        local_delta = guide.matrix_world.to_3x3().inverted_safe() @ world_delta
        if bool(getattr(event, "ctrl", False)):
            local_delta = Vector(
                round(float(value) * 10.0) / 10.0 for value in local_delta)
        return local_delta

    def _apply_transform(self, context, event):
        target, _modifier, controller, guide, spline = self._guide_context()
        if controller is None or spline is None:
            return False
        properties = controller.sdh_cage_deform
        current_mouse = Vector((
            float(getattr(event, "mouse_region_x", 0)),
            float(getattr(event, "mouse_region_y", 0))))
        if (
                getattr(self, "_pointer_click_indices", ()) and
                not bool(getattr(self, "_pointer_dragged", False))
        ):
            if (current_mouse - self._transform_initial_mouse).length < 3.0:
                return True
            self._pointer_dragged = True
        mode = self._transform_mode
        # Full Curve Falloff is intentionally limited to the four active
        # guide-point profile edits.  Moving/rotating/scaling the guide still
        # follows Blender's ordinary proportional-edit switch and radius.
        force_global = (
            str(getattr(self, "_transform_mode", "")) in {"RADIUS", "TILT"}
            and bool(getattr(properties, "curve_point_global_falloff", False))
        )
        weights = (
            self._proportional_weights(context, force_global=True)
            if force_global else
            self._proportional_weights(context)
        )
        values = {}
        scalar_values = {}
        unlink_indices = set()
        if mode == "MOVE":
            delta = self._local_move_delta(event, guide)
            for index, (co, left, right) in self._transform_original.items():
                weight = float(weights.get(index, 0.0))
                if weight <= 1.0e-8:
                    continue
                if self._transform_kind in {"LEFT", "RIGHT"}:
                    control = properties.curve_points[index]
                    alt_independent = bool(getattr(event, "alt", False))
                    values[index] = curve_moved_handle_values(
                        co, left, right, self._transform_kind,
                        delta * weight,
                        independent=(
                            alt_independent or
                            not bool(control.handles_linked)),
                    )
                    if alt_independent and bool(control.handles_linked):
                        unlink_indices.add(index)
                else:
                    weighted_delta = delta * weight
                    values[index] = (
                        co + weighted_delta,
                        left + weighted_delta,
                        right + weighted_delta,
                    )
        elif mode in {"RADIUS", "TILT"}:
            delta = (
                float(event.mouse_region_x) -
                float(self._transform_initial_mouse.x)) * 0.01
            if bool(getattr(event, "shift", False)):
                delta *= 0.1
            if bool(getattr(event, "ctrl", False)):
                if mode == "TILT":
                    step = math.radians(5.0)
                    delta = round(delta / step) * step
                else:
                    delta = round(delta * 10.0) / 10.0
            original = (
                self._transform_original_radius
                if mode == "RADIUS" else self._transform_original_tilt)
            attribute = "radius" if mode == "RADIUS" else "tilt"
            for index, initial in original.items():
                weight = float(weights.get(index, 0.0))
                if weight <= 1.0e-8:
                    continue
                updated = float(initial) + delta * weight
                if mode == "RADIUS":
                    updated = max(updated, 0.0)
                scalar_values[index] = (attribute, updated)
        else:
            from bpy_extras import view3d_utils
            center = view3d_utils.location_3d_to_region_2d(
                self._window_region, self._region_data,
                self._transform_pivot_world)
            if center is None:
                return False
            start = self._transform_initial_mouse - Vector(center)
            current = Vector((event.mouse_region_x, event.mouse_region_y)) - Vector(center)
            if mode == "ROTATE":
                if start.length <= 1.0e-6 or current.length <= 1.0e-6:
                    angle = 0.0
                else:
                    angle = math.atan2(
                        start.x * current.y - start.y * current.x,
                        start.dot(current))
                if bool(getattr(event, "shift", False)):
                    angle *= 0.1
                if bool(getattr(event, "ctrl", False)):
                    step = math.radians(5.0)
                    angle = round(angle / step) * step
                if self._transform_axis is None:
                    axis_world = (
                        self._region_data.view_matrix.inverted_safe().to_3x3() @
                        Vector((0.0, 0.0, 1.0)))
                else:
                    axis_world = Vector((0.0, 0.0, 0.0))
                    axis_world[self._transform_axis] = 1.0
                axis_local = (
                    guide.matrix_world.to_3x3().inverted_safe() @ axis_world)
                axis_local = _normalized_or(axis_local, (0.0, 0.0, 1.0))
            else:
                initial = max(start.length, 10.0)
                factor = max(current.length / initial, 0.001)
                if bool(getattr(event, "shift", False)):
                    factor = 1.0 + (factor - 1.0) * 0.1
                if bool(getattr(event, "ctrl", False)):
                    factor = max(round(factor * 10.0) / 10.0, 0.001)

            for index, triple in self._transform_original.items():
                weight = float(weights.get(index, 0.0))
                if weight <= 1.0e-8:
                    continue
                if mode == "ROTATE":
                    rotation = Matrix.Rotation(
                        angle * weight, 3, axis_local)
                    values[index] = tuple(
                        self._transform_pivot_local + rotation @ (
                            value - self._transform_pivot_local)
                        for value in triple)
                    continue
                weighted_factor = 1.0 + (factor - 1.0) * weight
                transformed = []
                for value in triple:
                    relative = value - self._transform_pivot_local
                    if self._transform_axis is None:
                        relative *= weighted_factor
                    else:
                        relative[self._transform_axis] *= weighted_factor
                    transformed.append(self._transform_pivot_local + relative)
                values[index] = tuple(transformed)

        changed_values = {}
        for index, triple in values.items():
            point = spline.bezier_points[index]
            current = (
                Vector(point.co), Vector(point.handle_left),
                Vector(point.handle_right))
            if any(
                    (Vector(requested) - existing).length > 1.0e-10
                    for requested, existing in zip(triple, current)
            ):
                changed_values[index] = triple
        changed_scalars = {
            index: (attribute, requested)
            for index, (attribute, requested) in scalar_values.items()
            if abs(
                float(getattr(spline.bezier_points[index], attribute)) -
                float(requested)
            ) > 1.0e-12
        }
        if not changed_values and not changed_scalars:
            return True
        _undo.begin(self, "Before Curve Control")
        for index in unlink_indices:
            if index in changed_values:
                properties.curve_points[index].handles_linked = False
        for index, (co, left, right) in changed_values.items():
            point = spline.bezier_points[index]
            point.co = co
            point.handle_left_type = "FREE"
            point.handle_right_type = "FREE"
            point.handle_left = left
            point.handle_right = right
        for index, (attribute, requested) in changed_scalars.items():
            setattr(spline.bezier_points[index], attribute, requested)
        guide.data.update_tag()
        target.update_tag()
        _relation_changed, relation_shift = sync_curve_cage_relation(
            controller, force=True)
        if abs(float(relation_shift)) > 1.0e-9:
            offset = Vector((0.0, float(relation_shift), 0.0))
            self._transform_original = {
                point_index: tuple(value - offset for value in triple)
                for point_index, triple in self._transform_original.items()
            }
            self._transform_pivot_local -= offset
        if self._area is not None:
            self._area.tag_redraw()
        return True

    def _finish_transform(self, context, *, cancel=False):
        target, modifier, controller, guide, spline = self._guide_context()
        if cancel and spline is not None:
            cancel_state = getattr(self, "_transform_cancel_state", None)
            if cancel_state is not None and controller is not None:
                properties = controller.sdh_cage_deform
                pointer = _pointer(controller)
                if pointer:
                    _core()._SYNCING.add(pointer)
                try:
                    properties.size = cancel_state["size"]
                    controller.location = cancel_state["controller_location"]
                    controller.scale = cancel_state["controller_scale"]
                finally:
                    if pointer:
                        _core()._SYNCING.discard(pointer)
                for point, values in zip(
                        spline.bezier_points, cancel_state["points"]):
                    (
                        co, left, right, left_type, right_type,
                        radius, tilt,
                    ) = values
                    point.co = co
                    point.handle_left_type = "FREE"
                    point.handle_right_type = "FREE"
                    point.handle_left = left
                    point.handle_right = right
                    point.handle_left_type = left_type
                    point.handle_right_type = right_type
                    point.radius = radius
                    point.tilt = tilt
                _set_curve_transform(guide, controller)
                station_object = curve_station_object(target, modifier)
                if station_object is not None:
                    _set_curve_transform(station_object, controller)
            else:
                for index, (co, left, right) in self._transform_original.items():
                    point = spline.bezier_points[index]
                    point.co = co
                    point.handle_left = left
                    point.handle_right = right
                    handle_types = getattr(
                        self, "_transform_original_handle_types", {}).get(index)
                    if handle_types is not None:
                        point.handle_left_type = handle_types[0]
                        point.handle_right_type = handle_types[1]
            for index, linked in getattr(
                    self, "_transform_original_linked", {}).items():
                properties = getattr(controller, "sdh_cage_deform", None)
                if properties is not None and index < len(properties.curve_points):
                    properties.curve_points[index].handles_linked = linked
            guide.data.update_tag()
            if target is not None:
                target.update_tag()
            if controller is not None:
                _core().sync_controller(
                    controller, pull_transform=False, sync_mode="push")
                record_curve_relation_snapshot(controller)
        elif (
                spline is not None and controller is not None and
                getattr(self, "_pointer_click_indices", ()) and
                not bool(getattr(self, "_pointer_dragged", False))
        ):
            self._set_selection(
                controller.sdh_cage_deform,
                spline,
                self._pointer_click_indices,
                active=getattr(self, "_pointer_click_active", None),
            )
        _undo.finish(self, cancel=cancel, message="Curve Control")
        self._pointer_click_indices = ()
        self._pointer_click_active = -1
        self._pointer_dragged = False
        self._transform_cancel_state = None
        self._state = "WAITING"
        self._set_header(context)

    def _draw_box(self):
        state = str(getattr(self, "_state", ""))
        if state not in {"DRAGGING", "TRANSFORM"}:
            return
        try:
            import gpu
            from gpu_extras.batch import batch_for_shader
            shader = gpu.shader.from_builtin("UNIFORM_COLOR")
            gpu.state.blend_set("ALPHA")
            shader.bind()
            if state == "DRAGGING":
                x0, y0 = self._box_start
                x1, y1 = self._box_end
                corners = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
                fill = (corners[0], corners[1], corners[2],
                        corners[0], corners[2], corners[3])
                border = (corners[0], corners[1], corners[1], corners[2],
                          corners[2], corners[3], corners[3], corners[0])
                shader.uniform_float("color", (0.08, 0.72, 1.0, 0.15))
                batch_for_shader(shader, "TRIS", {"pos": fill}).draw(shader)
                shader.uniform_float("color", (0.08, 0.82, 1.0, 0.95))
                gpu.state.line_width_set(1.5)
                batch_for_shader(shader, "LINES", {"pos": border}).draw(shader)
            elif self._proportional_enabled(bpy.context):
                from bpy_extras import view3d_utils
                region = getattr(self, "_window_region", None)
                region_data = getattr(self, "_region_data", None)
                pivot = Vector(getattr(
                    self, "_transform_pivot_world", Vector()))
                if region is not None and region_data is not None:
                    center = view3d_utils.location_3d_to_region_2d(
                        region, region_data, pivot)
                    view_right = (
                        region_data.view_matrix.inverted_safe().to_3x3() @
                        Vector((1.0, 0.0, 0.0)))
                    if center is not None and view_right.length > 1.0e-8:
                        view_right.normalize()
                        edge = view3d_utils.location_3d_to_region_2d(
                            region, region_data,
                            pivot + view_right * float(getattr(
                                self, "_proportional_radius", 0.0)))
                        if edge is not None:
                            radius = max(
                                (Vector(edge) - Vector(center)).length, 2.0)
                            circle = tuple(
                                (
                                    float(center.x) + math.cos(
                                        math.tau * index / 64.0) * radius,
                                    float(center.y) + math.sin(
                                        math.tau * index / 64.0) * radius,
                                )
                                for index in range(65)
                            )
                            shader.uniform_float(
                                "color", (0.95, 0.68, 0.12, 0.85))
                            gpu.state.line_width_set(1.5)
                            batch_for_shader(
                                shader, "LINE_STRIP", {"pos": circle}
                            ).draw(shader)
        except (ImportError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        finally:
            try:
                import gpu
                gpu.state.line_width_set(1.0)
                gpu.state.blend_set("NONE")
            except (ImportError, RuntimeError):
                pass

    def _apply_box_selection(self):
        from bpy_extras import view3d_utils
        _target, _modifier, controller, guide, spline = self._guide_context()
        if controller is None or spline is None:
            return False
        properties = controller.sdh_cage_deform
        minimum = Vector((
            min(self._box_start.x, self._box_end.x),
            min(self._box_start.y, self._box_end.y)))
        maximum = Vector((
            max(self._box_start.x, self._box_end.x),
            max(self._box_start.y, self._box_end.y)))
        boxed = set()
        for index, point in enumerate(spline.bezier_points):
            locations = (point.co, point.handle_left, point.handle_right)
            for local in locations:
                screen = view3d_utils.location_3d_to_region_2d(
                    self._window_region, self._region_data,
                    guide.matrix_world @ Vector(local))
                if screen is not None and all(
                        minimum[axis] <= screen[axis] <= maximum[axis]
                        for axis in range(2)):
                    boxed.add(index)
                    break
        self._last_boxed_indices = tuple(sorted(boxed))
        if bool(getattr(self, "_pre_edit_box_select", False)) and not boxed:
            return False
        current = set(self._selected_indices(properties))
        if self._selection_mode == "ADD":
            selected = current | boxed
        elif self._selection_mode == "SUBTRACT":
            selected = current - boxed
        else:
            selected = boxed
        active = min(boxed) if boxed else (
            min(selected) if selected else None)
        self._set_selection(properties, spline, selected, active=active)
        return bool(boxed)

    def _remove_draw_handler(self):
        handler = getattr(self, "_draw_handler", None)
        if handler is None:
            return
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handler, "WINDOW")
        except (ReferenceError, RuntimeError, TypeError):
            pass
        try:
            _CURVE_DRAW_HANDLERS.remove(handler)
        except ValueError:
            pass
        self._draw_handler = None

    def _finish_modal(self, context, *, restore_target=True):
        if bool(getattr(self, "_finished", False)):
            return
        target, _modifier, controller, guide, _spline = self._guide_context()
        if getattr(self, "_state", "") == "TRANSFORM":
            self._finish_transform(context, cancel=True)
            target, _modifier, controller, guide, _spline = self._guide_context()
        else:
            _undo.finish(self, cancel=True)
        self._finished = True
        if controller is not None:
            controller.sdh_cage_deform.curve_object_edit_active = False
        self._remove_draw_handler()
        if self._area is not None:
            self._area.header_text_set(None)
            self._area.tag_redraw()
        if guide is not None:
            guide.hide_select = True
        if restore_target and target is not None:
            _core()._activate(context, target)
        _core().refresh_controller_display(context, force=True)
        try:
            _CURVE_MODAL_OPERATORS.remove(self)
        except ValueError:
            pass

    def invoke(self, context, event):
        if not tuple(getattr(context, "selected_objects", ()) or ()):
            _core()._native_box_select_fallback(context, event)
            _core().refresh_controller_display(context, force=True)
            return {"FINISHED"}
        controller = controller_from_uuid(self.controller_uuid)
        if controller is None and self.controller_name:
            # Compatibility for operators invoked by an older keymap or
            # in-flight Gizmo instance during an extension update.
            controller = bpy.data.objects.get(str(self.controller_name))
        if controller is None:
            controller = _core().resolve_context_deform(context)[2]
        properties = getattr(controller, "sdh_cage_deform", None)
        if properties is None or str(properties.cage_type) != "CURVE":
            return {"CANCELLED"}
        if bool(self.toggle) and bool(properties.curve_object_edit_active):
            finish_curve_object_edit_sessions(context, restore_target=True)
            return {"FINISHED"}
        finish_curve_object_edit_sessions(context, restore_target=False)
        finish_curve_edit_sessions(context, restore_target=True)
        target = _core().find_target(controller)
        modifier = _core().find_modifier(target, controller) if target else None
        guide, _stations = ensure_curve_companions(
            target, modifier, controller)
        spline = curve_guide_spline(guide)
        if target is None or modifier is None or spline is None:
            return {"CANCELLED"}
        target.modifiers.active = modifier
        ensure_curve_point_collection(properties, guide)
        _core().activate_cage_workspace_tool(context, "CURVE")
        properties.curve_object_edit_active = True
        self._controller_uuid = str(controller.get(
            _core().CONTROLLER_UUID, ""))
        self._window_region = next((
            region for region in context.area.regions
            if region.type == "WINDOW"), None)
        if self._window_region is None:
            properties.curve_object_edit_active = False
            return {"CANCELLED"}
        self._region_data = context.space_data.region_3d
        self._area = context.area
        self._pre_edit_box_select = bool(
            self.start_box_select or self.arm_box_select)
        self._state = "BOX_READY" if bool(self.arm_box_select) else "WAITING"
        self._selection_mode = "SET"
        self._box_start = Vector((0.0, 0.0))
        self._box_end = Vector((0.0, 0.0))
        self._last_boxed_indices = ()
        self._blank_press_position = None
        self._last_blank_click_time = -1.0
        self._last_blank_click_position = (0.0, 0.0)
        self._proportional_radius = math.nan
        self._finished = False
        self._draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            lambda operator: operator._draw_box(), (self,),
            "WINDOW", "POST_PIXEL")
        _CURVE_DRAW_HANDLERS.append(self._draw_handler)
        _CURVE_MODAL_OPERATORS.append(self)
        _activate_curve_object_selection(context, target, controller, guide)
        if bool(self.start_box_select):
            press_x = getattr(event, "mouse_prev_press_x", None)
            press_y = getattr(event, "mouse_prev_press_y", None)
            if press_x is None or press_y is None:
                press_x = self._window_region.x + int(getattr(
                    event, "mouse_region_x", 0))
                press_y = self._window_region.y + int(getattr(
                    event, "mouse_region_y", 0))
            self._box_start = Vector((
                float(press_x - self._window_region.x),
                float(press_y - self._window_region.y),
            ))
            self._box_end = self._region_position(
                self._window_region, event)
            self._selection_mode = (
                "SUBTRACT" if bool(getattr(event, "ctrl", False)) else
                "ADD" if bool(getattr(event, "shift", False)) else "SET")
            self._state = "DRAGGING"
        elif bool(self.start_drag):
            synthetic = type("CurveStartEvent", (), {
                "mouse_region_x": int(self.start_mouse_region_x),
                "mouse_region_y": int(self.start_mouse_region_y),
            })()
            index = min(max(int(self.start_index), 0), len(spline.bezier_points) - 1)
            self._begin_pointer_transform(
                context, synthetic, properties, spline,
                str(self.start_kind), index, bool(self.start_extend))
        self._set_header(context)
        _core().refresh_controller_display(context, force=True)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        target, modifier, controller, guide, spline = self._guide_context()
        properties = getattr(controller, "sdh_cage_deform", None)
        if (
                properties is None or
                not bool(properties.curve_object_edit_active) or
                str(properties.cage_type) != "CURVE"):
            self._finish_modal(context)
            return {"FINISHED"}
        # Respect a real empty object selection.  Re-selecting the target on
        # every modal event prevents Blender's native Select Box from taking
        # over after the user leaves the Curve editor.
        if not tuple(getattr(context, "selected_objects", ()) or ()):
            self._finish_modal(context, restore_target=False)
            _core().activate_cage_workspace_tool(context, "")
            _core().refresh_controller_display(context, force=True)
            return {"FINISHED"}
        ensure_curve_point_collection(properties, guide)
        _activate_curve_object_selection(context, target, controller, guide)
        try:
            if getattr(event, "value", None) == "ANY":
                return {"PASS_THROUGH"}
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
        if (
                self._state != "DRAGGING" and
                self._inside_ui_region(context, event)
        ):
            return {"PASS_THROUGH"}
        if (
                self._state not in {"TRANSFORM", "DRAGGING"} and
                event.type in self._MOUSE_EVENTS and
                not self._inside_region(self._window_region, event)):
            return {"PASS_THROUGH"}

        if self._state == "TRANSFORM":
            if event.type in {
                    "WHEELUPMOUSE", "WHEELDOWNMOUSE",
                    "WHEELINMOUSE", "WHEELOUTMOUSE",
            } and self._proportional_enabled(context):
                factor = (
                    0.8 if event.type in {
                        "WHEELUPMOUSE", "WHEELINMOUSE"}
                    else 1.25)
                self._proportional_radius = max(
                    float(self._proportional_radius) * factor, 1.0e-8)
                settings = self._tool_settings(context)
                if settings is not None and hasattr(
                        settings, "proportional_size"):
                    try:
                        settings.proportional_size = self._proportional_radius
                    except (AttributeError, RuntimeError, TypeError, ValueError):
                        pass
                self._apply_transform(context, event)
                self._set_header(context)
                return {"RUNNING_MODAL"}
            if (
                    event.type == "O" and event.value == "PRESS" and
                    not bool(getattr(event, "shift", False))
            ):
                settings = self._tool_settings(context)
                if settings is not None:
                    object_mode = str(getattr(
                        getattr(context, "object", None),
                        "mode", "OBJECT")) == "OBJECT"
                    property_name = (
                        "use_proportional_edit_objects"
                        if object_mode and hasattr(
                            settings, "use_proportional_edit_objects")
                        else "use_proportional_edit"
                    )
                    if hasattr(settings, property_name):
                        setattr(settings, property_name, not bool(
                            getattr(settings, property_name, False)))
                self._apply_transform(context, event)
                self._set_header(context)
                return {"RUNNING_MODAL"}
            if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
                self._finish_transform(context, cancel=True)
                return {"RUNNING_MODAL"}
            if event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER", "SPACE"} and (
                    event.value == "PRESS" or
                    (event.type == "LEFTMOUSE" and event.value == "RELEASE")):
                self._finish_transform(context)
                return {"RUNNING_MODAL"}
            if (
                    self._transform_mode in {"MOVE", "ROTATE", "SCALE"} and
                    event.type in {"X", "Y", "Z"} and
                    event.value == "PRESS"
            ):
                self._transform_axis = {"X": 0, "Y": 1, "Z": 2}[event.type]
                self._apply_transform(context, event)
                return {"RUNNING_MODAL"}
            if event.type == "MOUSEMOVE":
                self._apply_transform(context, event)
                return {"RUNNING_MODAL"}
            return {"RUNNING_MODAL"}

        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            if self._state == "BOX_READY":
                if bool(getattr(self, "_pre_edit_box_select", False)):
                    self._finish_modal(context)
                    return {"FINISHED"}
                self._state = "WAITING"
                self._set_header(context)
                return {"RUNNING_MODAL"}
            self._finish_modal(context)
            return {"FINISHED"}
        if event.type == "A" and event.value == "PRESS":
            indices = () if bool(event.alt) else range(len(properties.curve_points))
            self._set_selection(
                properties, spline, indices,
                active=0 if properties.curve_points and not event.alt else None)
            return {"RUNNING_MODAL"}
        if event.type == "I" and event.value == "PRESS":
            count = _core()._keyframe_cage_paths(
                controller, delete=bool(event.alt))
            message = (
                "Removed {count} cage keyframe channels" if event.alt else
                "Inserted {count} cage keyframe channels")
            self.report({"INFO"}, iface_(message).format(count=count))
            return {"RUNNING_MODAL"}
        if event.type == "B" and event.value == "PRESS":
            self._state = "BOX_READY"
            self._set_header(context)
            return {"RUNNING_MODAL"}
        if (
                event.type == "S" and event.value == "PRESS" and
                bool(getattr(event, "alt", False)) and
                self._state == "WAITING"
        ):
            if self._begin_transform(context, event, "RADIUS"):
                return {"RUNNING_MODAL"}
            return {"PASS_THROUGH"}
        if (
                event.type == "T" and event.value == "PRESS" and
                bool(getattr(event, "ctrl", False)) and
                self._state == "WAITING"
        ):
            if self._begin_transform(context, event, "TILT"):
                return {"RUNNING_MODAL"}
            return {"PASS_THROUGH"}
        if (
                event.type in {"G", "R", "S"} and event.value == "PRESS" and
                self._state == "WAITING"):
            mode = {"G": "MOVE", "R": "ROTATE", "S": "SCALE"}[event.type]
            if self._begin_transform(context, event, mode):
                return {"RUNNING_MODAL"}
            return {"PASS_THROUGH"}
        if (
                event.type == "LEFTMOUSE" and event.value == "DOUBLE_CLICK" and
                self._state == "WAITING" and
                self._hit_element(context, event) is None):
            self._finish_modal(context)
            return {"FINISHED"}
        if (
                event.type == "LEFTMOUSE" and event.value == "PRESS" and
                self._state == "BOX_READY"):
            self._box_start = self._region_position(self._window_region, event)
            self._box_end = self._box_start.copy()
            self._selection_mode = (
                "SUBTRACT" if bool(event.ctrl) else
                "ADD" if bool(event.shift) else "SET")
            self._state = "DRAGGING"
            return {"RUNNING_MODAL"}
        if (
                event.type == "LEFTMOUSE" and event.value == "PRESS" and
                self._state == "WAITING"):
            hit = self._hit_element(context, event)
            if hit is None:
                if self._other_stage_gizmo_at_event(context, event) is not None:
                    # Stop owning the pointer before handing the same press
                    # back to an inactive stage picker or its cage Gizmo.
                    self._finish_modal(context, restore_target=False)
                    return {"PASS_THROUGH"}
                if self._over_other_gizmo(context, event):
                    # Boundary/end/axis controls must receive their normal
                    # Gizmo invoke instead of becoming a Curve box drag.
                    self._finish_modal(context, restore_target=False)
                    return {"PASS_THROUGH"}
                position = self._region_position(self._window_region, event)
                self._box_start = position
                self._box_end = position
                self._selection_mode = (
                    "SUBTRACT" if bool(event.ctrl) else
                    "ADD" if bool(event.shift) else "SET")
                self._state = "DRAGGING"
                self._set_header(context)
                return {"RUNNING_MODAL"}
            self._blank_press_position = None
            kind, index = hit
            self._begin_pointer_transform(
                context, event, properties, spline, kind, index,
                bool(event.shift))
            return {"RUNNING_MODAL"}
        if (
                self._state == "DRAGGING" and
                event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}
        ):
            self._box_end = self._region_position(self._window_region, event)
            self._area.tag_redraw()
            return {"RUNNING_MODAL"}
        if (
                self._state == "DRAGGING" and
                event.type == "LEFTMOUSE" and event.value == "RELEASE"):
            self._box_end = self._region_position(self._window_region, event)
            matched = self._apply_box_selection()
            if bool(getattr(self, "_pre_edit_box_select", False)):
                if not matched:
                    self._finish_modal(context)
                    return {"FINISHED"}
                self._pre_edit_box_select = False
            double_click, next_time, next_position = (
                curve_blank_click_release_state(
                    self._last_blank_click_time,
                    self._last_blank_click_position,
                    self._box_start,
                    self._box_end,
                    time.monotonic(),
                )
            )
            self._last_blank_click_time = next_time
            self._last_blank_click_position = next_position
            if double_click:
                self._finish_modal(context)
                return {"FINISHED"}
            self._state = "WAITING"
            self._set_header(context)
            return {"RUNNING_MODAL"}
        if self._state == "DRAGGING":
            return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}

    def cancel(self, context):
        self._finish_modal(context)


class SDH_UL_curve_stations(UIList):
    bl_idname = "SDH_UL_curve_stations"

    def draw_item(
            self, _context, layout, _data, item, _icon, _active_data,
            _active_property, _index=0, _flt_flag=0):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False, icon="MESH_CIRCLE")
        row.prop(item, "factor", text="")


class SDH_OT_edit_curve_cage(Operator):
    bl_idname = "sdh.edit_curve_cage"
    bl_label = "Edit Curve Cage"
    bl_description = (
        "Enter the managed guide's Curve Edit Mode; use Blender selection, "
        "G/R/S, handles, subdivide, extrude, and delete tools")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        target, modifier, controller = _core().resolve_context_deform(context)
        properties = getattr(controller, "sdh_cage_deform", None)
        return bool(properties and str(properties.cage_type) == "CURVE")

    def execute(self, context):
        target, modifier, controller = _core().resolve_context_deform(context)
        if controller is None:
            return {"CANCELLED"}
        finish_curve_object_edit_sessions(context, restore_target=True)
        guide, _stations = ensure_curve_companions(
            target, modifier, controller)
        if guide is None:
            return {"CANCELLED"}
        if getattr(guide, "mode", "OBJECT") == "EDIT":
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except RuntimeError:
                return {"CANCELLED"}
            properties = controller.sdh_cage_deform
            spline = curve_guide_spline(guide)
            if spline is not None:
                properties.curve_closed = bool(spline.use_cyclic_u)
                ensure_curve_point_collection(properties, guide)
                sync_curve_cage_relation(controller, force=True)
            properties.curve_edit_mode_active = False
            _core()._activate(context, target)
            _core().refresh_controller_display(context, force=True)
            return {"FINISHED"}
        try:
            if getattr(context, "mode", "OBJECT") != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            for selected in tuple(getattr(context, "selected_objects", ())):
                selected.select_set(False)
            target.select_set(True)
            for related_controller in _core()._target_cage_controllers(target):
                set_helper_object_visible(
                    related_controller, True,
                    getattr(context, "view_layer", None))
                related_controller.select_set(True)
            set_helper_object_visible(
                guide, True, getattr(context, "view_layer", None))
            guide.hide_select = False
            guide.select_set(True)
            context.view_layer.objects.active = guide
            bpy.ops.object.mode_set(mode="EDIT")
            controller.sdh_cage_deform.curve_edit_mode_active = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class SDH_OT_add_curve_station(Operator):
    bl_idname = "sdh.add_curve_station"
    bl_label = "Add Cross Section"
    bl_description = "Insert an interpolated cross-section station"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        controller = _core().resolve_context_deform(context)[2]
        properties = getattr(controller, "sdh_cage_deform", None)
        return bool(
            properties and str(properties.cage_type) == "CURVE" and
            len(properties.curve_stations) < CURVE_STATION_MAXIMUM)

    def execute(self, context):
        target, modifier, controller = _core().resolve_context_deform(context)
        properties = controller.sdh_cage_deform
        ensure_curve_station_collection(properties)
        index = min(
            max(int(properties.curve_active_station), 0),
            len(properties.curve_stations) - 1)
        insert_at = min(index + 1, len(properties.curve_stations) - 1)
        lower = properties.curve_stations[insert_at - 1]
        upper = properties.curve_stations[insert_at]
        values = (
            (float(lower.factor) + float(upper.factor)) * 0.5,
            tuple((float(a) + float(b)) * 0.5
                  for a, b in zip(lower.scale, upper.scale)),
            tuple((float(a) + float(b)) * 0.5
                  for a, b in zip(lower.offset, upper.offset)),
            (float(lower.radius) + float(upper.radius)) * 0.5,
            (float(lower.twist) + float(upper.twist)) * 0.5,
        )
        pointer = _pointer(controller)
        if pointer:
            _STATION_SYNC_GUARD.add(pointer)
        try:
            station = properties.curve_stations.add()
            station.name = iface_("Cross Section {index}").format(
                index=len(properties.curve_stations))
            (
                station.factor, station.scale, station.offset,
                station.radius, station.twist,
            ) = values
            properties.curve_stations.move(
                len(properties.curve_stations) - 1, insert_at)
            properties.curve_active_station = insert_at
        finally:
            if pointer:
                _STATION_SYNC_GUARD.discard(pointer)
        if bool(getattr(properties, "curve_even_stations", False)):
            _equalize_curve_station_factors(properties)
        update_curve_station_mesh(target, modifier, controller)
        return {"FINISHED"}


class SDH_OT_remove_curve_station(Operator):
    bl_idname = "sdh.remove_curve_station"
    bl_label = "Remove Cross Section"
    bl_description = "Remove the active interior cross-section station"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        controller = _core().resolve_context_deform(context)[2]
        properties = getattr(controller, "sdh_cage_deform", None)
        if properties is None or str(properties.cage_type) != "CURVE":
            return False
        index = int(properties.curve_active_station)
        return len(properties.curve_stations) > 2 and 0 < index < len(properties.curve_stations) - 1

    def execute(self, context):
        target, modifier, controller = _core().resolve_context_deform(context)
        properties = controller.sdh_cage_deform
        index = int(properties.curve_active_station)
        if not (0 < index < len(properties.curve_stations) - 1):
            return {"CANCELLED"}
        properties.curve_stations.remove(index)
        properties.curve_active_station = min(index, len(properties.curve_stations) - 1)
        if bool(getattr(properties, "curve_even_stations", False)):
            _equalize_curve_station_factors(properties)
        update_curve_station_mesh(target, modifier, controller)
        return {"FINISHED"}


class SDH_OT_equalize_curve_stations(Operator):
    bl_idname = "sdh.equalize_curve_stations"
    bl_label = "Equalize Cross Sections"
    bl_description = "Distribute every cross section evenly along the guide"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        controller = _core().resolve_context_deform(context)[2]
        properties = getattr(controller, "sdh_cage_deform", None)
        return bool(
            properties and str(properties.cage_type) == "CURVE" and
            len(properties.curve_stations) >= CURVE_STATION_MINIMUM)

    def execute(self, context):
        target, modifier, controller = _core().resolve_context_deform(context)
        if not equalize_curve_stations(target, modifier, controller):
            return {"CANCELLED"}
        return {"FINISHED"}


class SDH_OT_rebind_curve_reference(Operator):
    bl_idname = "sdh.rebind_curve_reference"
    bl_label = "Rebind Curve"
    bl_description = (
        "Capture the current guide as the zero-deformation reference for "
        "relative Curve binding")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        target, modifier, controller = _core().resolve_context_deform(context)
        properties = getattr(controller, "sdh_cage_deform", None)
        return bool(
            target is not None and modifier is not None and
            properties is not None and str(properties.cage_type) == "CURVE")

    def execute(self, context):
        target, modifier, controller = _core().resolve_context_deform(context)
        if rebind_curve_reference(target, modifier, controller) is None:
            self.report({"ERROR"}, iface_(
                "The Curve cage rest guide could not be created"))
            return {"CANCELLED"}
        _core().sync_controller(
            controller, pull_transform=False, sync_mode="push")
        _core().refresh_controller_display(context, force=True)
        self.report({"INFO"}, iface_("Rebound Curve reference guide"))
        return {"FINISHED"}


class SDH_OT_reset_curve_guide(Operator):
    bl_idname = "sdh.reset_curve_guide"
    bl_label = "Reset Curve Guide"
    bl_description = "Reset the guide to a straight path fitted to the cage"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        controller = _core().resolve_context_deform(context)[2]
        properties = getattr(controller, "sdh_cage_deform", None)
        return bool(properties and str(properties.cage_type) == "CURVE")

    def execute(self, context):
        target, modifier, controller = _core().resolve_context_deform(context)
        guide, _stations = ensure_curve_companions(
            target, modifier, controller, reset_guide=True)
        if guide is None:
            return {"CANCELLED"}
        sync_curve_cage_relation(controller, force=True)
        return {"FINISHED"}


class SDH_OT_equalize_curve_points(Operator):
    bl_idname = "sdh.equalize_curve_points"
    bl_label = "Equalize Curve Points"
    bl_description = "Redistribute guide points uniformly by curve arc length"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        target, modifier, controller = _core().resolve_context_deform(context)
        properties = getattr(controller, "sdh_cage_deform", None)
        return bool(
            target is not None and modifier is not None and
            properties is not None and
            str(properties.cage_type) == "CURVE")

    def execute(self, context):
        target, modifier, controller = _core().resolve_context_deform(context)
        guide, _stations = ensure_curve_companions(
            target, modifier, controller)
        if guide is None:
            return {"CANCELLED"}
        if _curve_data_has_point_animation(guide.data):
            self.report({"WARNING"}, iface_(
                "Remove guide shape keys, drivers, NLA, or point animation "
                "before equalizing points"))
            return {"CANCELLED"}
        properties = controller.sdh_cage_deform
        if not equalize_curve_points(
                guide, properties, properties.curve_equalize_count):
            return {"CANCELLED"}
        _core().sync_controller(
            controller, pull_transform=False, sync_mode="push")
        _core().refresh_controller_display(context, force=True)
        spline = curve_guide_spline(guide)
        self.report(
            {"INFO"},
            iface_("Equalized curve to {count} points").format(
                count=len(spline.bezier_points) if spline else 0),
        )
        return {"FINISHED"}


classes = (
    SDHCurveStation,
    SDHCurveControlGizmo,
    SDHCurveControlGizmoGroup,
    SDH_OT_edit_curve_cage_object,
    SDH_UL_curve_stations,
    SDH_OT_edit_curve_cage,
    SDH_OT_add_curve_station,
    SDH_OT_remove_curve_station,
    SDH_OT_equalize_curve_stations,
    SDH_OT_rebind_curve_reference,
    SDH_OT_reset_curve_guide,
    SDH_OT_equalize_curve_points,
)
