"""Connected Cage Deform stages.

This module deliberately keeps chain bookkeeping and the batch operators out of
the core deformation implementation.  It works with both the historical
single-file ``cage_deform`` module and the newer ``cage_deform.core`` package.
The core module remains the source of truth for node groups and controller
ownership; this module only stores relationship metadata and positions stages.
"""
from __future__ import annotations

import math
import uuid

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator
from mathutils import Euler, Matrix, Vector


CHAIN_ID = "_sdh_cage_chain_id"
CHAIN_INDEX = "_sdh_cage_chain_index"
CHAIN_MODE = "_sdh_cage_chain_mode"
CHAIN_BROKEN = "_sdh_cage_chain_broken"
CHAIN_VERSION = 1
EPSILON = 1.0e-5


def _core():
    """Return the active cage implementation in either source layout."""
    from . import cage_deform

    return getattr(cage_deform, "core", cage_deform)


def _call(name, *args, default=None, **kwargs):
    function = getattr(_core(), name, None)
    if function is None:
        return default
    return function(*args, **kwargs)


def _pointer(value) -> int:
    return int(value.as_pointer()) if value is not None else 0


def _target_from_context(context):
    target = _call("target_from_context", context)
    if target is not None:
        return target
    obj = getattr(context, "object", None)
    supported = getattr(_core(), "SUPPORTED_TYPES", {"MESH", "CURVE", "FONT"})
    return obj if obj is not None and obj.type in supported else None


def _cage_modifiers(target):
    return tuple(_call("cage_modifiers", target, default=()))


def _is_cage_modifier(modifier):
    return bool(_call("is_cage_modifier", modifier, default=False))


def _find_controller(target, modifier):
    return _call("find_controller", target, modifier)


def _modifier_uuid(modifier):
    return str(_call("cage_modifier_uuid", modifier, default="") or "")


def _target_uuid(target):
    key = getattr(_core(), "TARGET_UUID", "_sdh_cage_deform_target_uuid")
    return str(target.get(key, "")) if target is not None else ""


def _activate(context, obj):
    function = getattr(_core(), "_activate", None)
    if function is not None:
        function(context, obj)
        return
    if obj is None:
        return
    for selected in tuple(getattr(context, "selected_objects", ())):
        selected.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def _sync(controller, *, pull_transform=False):
    function = getattr(_core(), "sync_controller", None)
    if function is not None:
        return function(controller, pull_transform=pull_transform)
    return False


def _bounds_fallback(target):
    function = getattr(_core(), "_object_fallback_bounds", None)
    if function is not None:
        return function(target)
    points = [Vector(point) for point in getattr(target, "bound_box", ())]
    if not points:
        zero = Vector((0.0, 0.0, 0.0))
        return zero, zero.copy()
    return (
        Vector(tuple(min(point[index] for point in points) for index in range(3))),
        Vector(tuple(max(point[index] for point in points) for index in range(3))),
    )


def _input_bounds(context, target, modifier):
    function = getattr(_core(), "_modifier_input_bounds", None)
    if function is not None and modifier is not None:
        try:
            return function(context, target, modifier)
        except (RuntimeError, ReferenceError, ValueError):
            pass
    return _bounds_fallback(target)


def _matrix_inverse(matrix):
    try:
        return matrix.inverted_safe()
    except (AttributeError, ValueError, RuntimeError):
        return matrix.inverted()


def _target_local_cage_matrix(target, controller):
    """Return a cage transform in target-local coordinates.

    Geometry Nodes works in the target object's local coordinates.  Keeping
    the chain math in that space avoids errors when the target has a rotated or
    non-uniformly scaled object transform.
    """
    cage_matrix = _call("cage_local_matrix", target, controller)
    if cage_matrix is None:
        return Matrix.Translation(Vector(controller.location)) @ controller.rotation_euler.to_matrix().to_4x4()
    return _matrix_inverse(target.matrix_world) @ cage_matrix


def _deform_point(point, properties):
    function = getattr(_core(), "deform_point_local", None)
    if function is None:
        return Vector(point)
    return Vector(function(
        point,
        properties.size,
        properties.deform_type,
        properties.strength,
        properties.factor,
        properties.direction,
        properties.mode,
        properties.origin,
        properties.preserve_volume,
        properties.top_scale,
        properties.bottom_scale,
        properties.top_offset,
        properties.bottom_offset,
    ))


def _safe_normalized(value, fallback):
    result = Vector(value)
    if result.length <= EPSILON or not all(math.isfinite(component) for component in result):
        result = Vector(fallback)
    if result.length <= EPSILON:
        result = Vector((0.0, 1.0, 0.0))
    return result.normalized()


def _rotation_from_axes(x_axis, y_axis, z_axis):
    """Build an Euler rotation whose columns are the local cage axes."""
    matrix = Matrix((
        (x_axis.x, y_axis.x, z_axis.x),
        (x_axis.y, y_axis.y, z_axis.y),
        (x_axis.z, y_axis.z, z_axis.z),
    ))
    return matrix.to_euler("XYZ")


def _stage_top_frame(target, controller):
    """Return (endpoint, tangent, x_axis, z_axis, width, depth) in target local."""
    properties = controller.sdh_cage_deform
    half = Vector(properties.size) * 0.5
    matrix = _target_local_cage_matrix(target, controller)
    y = half.y
    delta = max(min(abs(half.y) * 0.02, 0.05), 0.001)

    endpoint = matrix @ _deform_point((0.0, y, 0.0), properties)
    previous = matrix @ _deform_point((0.0, y - delta, 0.0), properties)
    forward = matrix @ _deform_point((0.0, y + delta, 0.0), properties)
    # A forward continuation mode has a meaningful tangent beyond the top;
    # Within Box has a clamped outside region, so use the interior derivative.
    mode = str(properties.mode)
    tangent = (forward - endpoint) if mode in {"LIMITED", "UNLIMITED", "CHAINED"} else (endpoint - previous)
    old_y = matrix.to_3x3() @ Vector((0.0, 1.0, 0.0))
    y_axis = _safe_normalized(tangent, old_y)

    x_positive = matrix @ _deform_point((half.x, y, 0.0), properties)
    x_negative = matrix @ _deform_point((-half.x, y, 0.0), properties)
    z_positive = matrix @ _deform_point((0.0, y, half.z), properties)
    z_negative = matrix @ _deform_point((0.0, y, -half.z), properties)
    x_raw = x_positive - x_negative
    z_raw = z_positive - z_negative

    x_axis = x_raw - y_axis * x_raw.dot(y_axis)
    if x_axis.length <= EPSILON:
        x_axis = z_raw.cross(y_axis)
    x_axis = _safe_normalized(x_axis, matrix.to_3x3() @ Vector((1.0, 0.0, 0.0)))
    z_axis = _safe_normalized(x_axis.cross(y_axis), matrix.to_3x3() @ Vector((0.0, 0.0, 1.0)))
    # Preserve the previous roll where possible.  This prevents a frame flip
    # when a bend crosses a view-independent 180-degree tangent seam.
    if z_axis.dot(_safe_normalized(z_raw, z_axis)) < 0.0:
        x_axis.negate()
        z_axis.negate()

    width = max(x_raw.length, EPSILON)
    depth = max(z_raw.length, EPSILON)
    return endpoint, y_axis, x_axis, z_axis, width, depth


def _set_chain_metadata(modifier, chain_id, index, mode="CONNECTED", broken=False):
    node_group = getattr(modifier, "node_group", None)
    if node_group is None:
        return
    node_group[CHAIN_ID] = str(chain_id)
    node_group[CHAIN_INDEX] = int(index)
    node_group[CHAIN_MODE] = str(mode)
    node_group[CHAIN_BROKEN] = bool(broken)
    node_group["_sdh_cage_chain_version"] = CHAIN_VERSION


def stage_chain_id(modifier):
    node_group = getattr(modifier, "node_group", None)
    return str(node_group.get(CHAIN_ID, "")) if node_group is not None else ""


def stage_chain_mode(modifier):
    node_group = getattr(modifier, "node_group", None)
    return str(node_group.get(CHAIN_MODE, "")) if node_group is not None else ""


def chain_stages(target, chain_id=""):
    stages = _cage_modifiers(target)
    if not chain_id:
        chain_id = stage_chain_id(getattr(target.modifiers, "active", None))
    if not chain_id:
        return ()
    return tuple(modifier for modifier in stages if stage_chain_id(modifier) == str(chain_id))


def _mark_chain_state(target, chain_id):
    stages = list(chain_stages(target, chain_id))
    if not stages:
        return ()
    modifier_order = tuple(target.modifiers)
    indices = [modifier_order.index(modifier) for modifier in stages]
    first, last = min(indices), max(indices)
    # A native/non-chain modifier between two chain stages makes the relation
    # ambiguous because its output changes the input frame.  Keep the metadata
    # but mark it so the UI can show a broken-chain warning.
    broken = any(
        not _is_cage_modifier(modifier) or stage_chain_id(modifier) != str(chain_id)
        for modifier in modifier_order[first:last + 1]
    )
    for index, modifier in enumerate(stages):
        _set_chain_metadata(modifier, chain_id, index, stage_chain_mode(modifier) or "CONNECTED", broken)
    return tuple(stages)


def normalize_chain(target, chain_id=""):
    """Normalize indices and return the chain stages in actual stack order."""
    if not chain_id:
        active = getattr(target.modifiers, "active", None)
        chain_id = stage_chain_id(active)
    return _mark_chain_state(target, chain_id) if chain_id else ()


def _set_properties_from_template(destination, source, *, connected=True):
    if source is not None:
        copier = getattr(_core(), "_copy_controller_state", None)
        if copier is not None:
            copier(destination, source)
        else:
            source_properties = source.sdh_cage_deform
            destination_properties = destination.sdh_cage_deform
            for name in (
                    "deform_type", "strength", "factor", "direction", "size",
                    "mode", "origin", "alignment", "preserve_volume",
                    "top_scale", "bottom_scale", "top_offset", "bottom_offset"):
                if hasattr(source_properties, name):
                    value = getattr(source_properties, name)
                    setattr(destination_properties, name, tuple(value) if hasattr(value, "__len__") and not isinstance(value, str) else value)
            destination.location = source.location
            destination.rotation_euler = source.rotation_euler
            destination.scale = source.scale
    properties = destination.sdh_cage_deform
    # A chain is entered at the lower boundary.  The core may not yet expose
    # CHAINED during a staged upgrade; fall back to Within Box in that case.
    if connected:
        try:
            properties.mode = "CHAINED"
        except (TypeError, ValueError):
            properties.mode = "WITHIN_BOX"
        try:
            properties.origin = "BOTTOM"
        except (TypeError, ValueError):
            pass
    return properties


def reconnect_chain(target, chain_id=""):
    """Align every stage's bottom frame to the previous stage's top frame."""
    stages = normalize_chain(target, chain_id)
    if len(stages) < 2:
        return 0
    updated = 0
    for previous, current in zip(stages, stages[1:]):
        previous_controller = _find_controller(target, previous)
        current_controller = _find_controller(target, current)
        if previous_controller is None or current_controller is None:
            continue
        endpoint, tangent, x_axis, z_axis, width, depth = _stage_top_frame(
            target, previous_controller)
        properties = current_controller.sdh_cage_deform
        size = Vector(properties.size)
        if size.y <= EPSILON:
            continue
        # Keep the current segment length, but match the incoming cross-section
        # at its bottom.  This makes an edited upstream end propagate without
        # destroying the downstream segment's length or angle.
        properties.bottom_scale = (
            max(width / max(size.x, EPSILON), 0.05),
            max(depth / max(size.z, EPSILON), 0.05),
        )
        properties.bottom_offset = (0.0, 0.0)
        rotation = _rotation_from_axes(x_axis, tangent, z_axis)
        half_length = size.y * 0.5
        current_controller.rotation_euler = rotation
        current_controller.location = endpoint + rotation.to_matrix() @ Vector((0.0, half_length, 0.0))
        current_controller.scale = tuple(max(value, EPSILON) * 0.5 for value in size)
        _sync(current_controller, pull_transform=False)
        updated += 1
    if stages:
        normalize_chain(target, stage_chain_id(stages[0]))
        target.update_tag()
    return updated


def _stage_cleanup(target, created):
    for modifier, controller in reversed(created):
        try:
            node_group = modifier.node_group
            target.modifiers.remove(modifier)
        except (ReferenceError, RuntimeError):
            node_group = None
        try:
            if controller is not None and controller.name in bpy.data.objects:
                bpy.data.objects.remove(controller, do_unlink=True)
        except (ReferenceError, RuntimeError):
            pass
        try:
            if node_group is not None and node_group.users == 0:
                bpy.data.node_groups.remove(node_group)
        except (ReferenceError, RuntimeError):
            pass


class SDH_OT_create_cage_chain(Operator):
    bl_idname = "sdh.create_cage_chain"
    bl_label = "Create Connected Cage Chain"
    bl_description = "Create several related deformation cages in one operation"
    bl_options = {"REGISTER", "UNDO"}

    count: IntProperty(
        name="Cage Count",
        description="Number of connected cages to create",
        default=3,
        min=2,
        max=16,
    )
    connected: BoolProperty(
        name="Connect Ends",
        description="Align each cage bottom to the previous cage top",
        default=True,
    )
    mode: EnumProperty(
        name="Chain Mode",
        items=(
            ("CONNECTED", "Connected", "Use forward continuation when available"),
            ("INDEPENDENT", "Independent", "Create stages without automatic reconnection"),
        ),
        default="CONNECTED",
    )

    @classmethod
    def poll(cls, context):
        target = _target_from_context(context)
        supported = getattr(_core(), "SUPPORTED_TYPES", {"MESH", "CURVE", "FONT"})
        return bool(target and target.type in supported)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def execute(self, context):
        target = _target_from_context(context)
        if target is None:
            return {"CANCELLED"}
        active = getattr(target.modifiers, "active", None)
        source_controller = _find_controller(target, active) if _is_cage_modifier(active) else None
        source_properties = getattr(source_controller, "sdh_cage_deform", None)
        after_modifier = active if active in tuple(target.modifiers) else None
        bounds = _input_bounds(context, target, after_modifier)
        minimum, maximum = Vector(bounds[0]), Vector(bounds[1])
        center = (minimum + maximum) * 0.5

        if source_controller is not None:
            base_rotation = source_controller.rotation_euler.copy()
        else:
            alignment = getattr(_core(), "_alignment_rotation", None)
            base_rotation = alignment("AUTO", (minimum, maximum)) if alignment else Euler((0.0, 0.0, 0.0))
        rotation_matrix = base_rotation.to_matrix()
        local_points = [rotation_matrix.inverted() @ (point - center) for point in (
            Vector((x, y, z))
            for x in (minimum.x, maximum.x)
            for y in (minimum.y, maximum.y)
            for z in (minimum.z, maximum.z)
        )]
        local_min = Vector(tuple(min(point[index] for point in local_points) for index in range(3)))
        local_max = Vector(tuple(max(point[index] for point in local_points) for index in range(3)))
        axis_length = max(local_max.y - local_min.y, EPSILON)
        segment_length = axis_length / max(int(self.count), 1)
        cross_size = (
            max(local_max.x - local_min.x, EPSILON),
            max(local_max.z - local_min.z, EPSILON),
        )
        chain_id = str(uuid.uuid4())
        created = []
        previous = after_modifier
        try:
            for index in range(int(self.count)):
                name = f"Cage Chain {index + 1:02d}"
                creator = getattr(_core(), "create_deform_stage", None)
                if creator is None:
                    raise RuntimeError("Cage Deform core does not expose create_deform_stage")
                modifier, controller, _previous_active = creator(
                    context, target, name=name, after_modifier=previous)
                created.append((modifier, controller))
                properties = _set_properties_from_template(
                    controller, source_controller, connected=(self.connected and self.mode == "CONNECTED"))
                properties.size = (cross_size[0], segment_length, cross_size[1])
                properties.top_scale = (1.0, 1.0)
                properties.bottom_scale = (1.0, 1.0)
                properties.top_offset = (0.0, 0.0)
                properties.bottom_offset = (0.0, 0.0)
                properties.alignment = getattr(properties, "alignment", "AUTO")
                midpoint = local_min.y + segment_length * (index + 0.5)
                controller.rotation_euler = base_rotation
                controller.location = center + rotation_matrix @ Vector((0.0, midpoint, 0.0))
                controller.scale = tuple(max(value, EPSILON) * 0.5 for value in properties.size)
                _set_chain_metadata(
                    modifier,
                    chain_id,
                    index,
                    self.mode if self.connected else "INDEPENDENT",
                )
                _sync(controller, pull_transform=False)
                previous = modifier
            target.modifiers.active = created[-1][0]
            _activate(context, target)
            if self.connected and self.mode == "CONNECTED":
                reconnect_chain(target, chain_id)
            normalize_chain(target, chain_id)
            self.report({"INFO"}, f"Created {len(created)} cage stages")
            return {"FINISHED"}
        except Exception as error:
            _stage_cleanup(target, created)
            self.report({"ERROR"}, f"Could not create cage chain: {error}")
            return {"CANCELLED"}


class SDH_OT_reconnect_cage_chain(Operator):
    bl_idname = "sdh.reconnect_cage_chain"
    bl_label = "Reconnect Cage Chain"
    bl_description = "Align each cage to the previous cage's output frame"
    bl_options = {"REGISTER", "UNDO"}

    chain_id: StringProperty(name="Chain ID", default="", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        target = _target_from_context(context)
        if target is None:
            return False
        chain_id = cls._resolve_chain_id(context, target)
        return len(chain_stages(target, chain_id)) >= 2

    @staticmethod
    def _resolve_chain_id(context, target):
        active = getattr(target.modifiers, "active", None)
        value = stage_chain_id(active)
        if value:
            return value
        for modifier in _cage_modifiers(target):
            value = stage_chain_id(modifier)
            if value:
                return value
        return ""

    def execute(self, context):
        target = _target_from_context(context)
        if target is None:
            return {"CANCELLED"}
        chain_id = self.chain_id or self._resolve_chain_id(context, target)
        count = reconnect_chain(target, chain_id)
        if count <= 0:
            self.report({"WARNING"}, "No connected cage chain was found")
            return {"CANCELLED"}
        _activate(context, target)
        self.report({"INFO"}, f"Reconnected {count + 1} cage stages")
        return {"FINISHED"}


classes = (
    SDH_OT_create_cage_chain,
    SDH_OT_reconnect_cage_chain,
)


def register():
    for item in classes:
        bpy.utils.register_class(item)


def unregister():
    for item in reversed(classes):
        bpy.utils.unregister_class(item)

