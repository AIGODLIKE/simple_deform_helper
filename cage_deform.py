from __future__ import annotations

import math
import uuid
from typing import Iterable

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty
from bpy.types import Gizmo, GizmoGroup, Operator, Panel, PropertyGroup
from mathutils import Euler, Matrix, Vector

from .stages import _bounds_from_points, _object_fallback_bounds, hide_runtime_object
from .utils import (
    PublicData,
    move_object_to_control_collection,
    remove_unused_control_collections,
    set_helper_object_visible,
)


GROUP_NAME = "SDH Cage Deform Core"
GROUP_MARKER = "_sdh_cage_deform_group"
GROUP_VERSION = 4
MODIFIER_MARKER = "_sdh_cage_deform_stage"
MODIFIER_UUID = "_sdh_cage_deform_modifier_uuid"
CONTROLLER_MARKER = "_sdh_cage_deform_controller"
CONTROLLER_UUID = "_sdh_cage_deform_controller_uuid"
TARGET_UUID = "_sdh_cage_deform_target_uuid"
RUNTIME_EVALUATOR = "_sdh_cage_deform_runtime_evaluator"

CONTROLLER_STYLES = {
    "BEND": ("SINGLE_ARROW", (0.05, 0.72, 1.0, 0.85)),
    "TWIST": ("CIRCLE", (0.72, 0.22, 1.0, 0.85)),
    "TAPER": ("CONE", (1.0, 0.62, 0.05, 0.85)),
    "STRETCH": ("ARROWS", (0.15, 0.9, 0.42, 0.85)),
}

DEFORM_VALUES = {"BEND": 0, "TWIST": 1, "TAPER": 2, "STRETCH": 3}
MODE_VALUES = {"LIMITED": 0, "WITHIN_BOX": 1, "UNLIMITED": 2}
ORIGIN_VALUES = {"BOTTOM": 0, "CENTER": 1, "SYMMETRIC": 2, "TOP": 3}
SUPPORTED_TYPES = {"MESH", "CURVE", "FONT"}
EPSILON = 1.0e-5

_SYNCING = set()
_LEGACY_MIGRATION_PENDING = True


def _pointer(value) -> int:
    try:
        return int(value.as_pointer())
    except (AttributeError, ReferenceError, TypeError):
        return 0


def _ensure_uuid(owner, key) -> str:
    value = str(owner.get(key, ""))
    if not value:
        value = str(uuid.uuid4())
        owner[key] = value
    return value


def ensure_unique_target_uuid(target) -> str:
    """Return an ownership UUID that belongs to this target only.

    Blender copies custom properties when duplicating an object. A copied cage
    target therefore initially carries the source UUID even when its managed
    modifiers have already been removed. Giving the selected target a fresh
    UUID before creating a new stage prevents its controller from resolving
    back to the source object.
    """
    target_uuid = str(target.get(TARGET_UUID, "")) if target else ""
    conflict = any(
        obj != target and not is_cage_controller(obj) and
        str(obj.get(TARGET_UUID, "")) == target_uuid
        for obj in bpy.data.objects
    ) if target_uuid else False
    if not target_uuid or conflict:
        target_uuid = str(uuid.uuid4())
        target[TARGET_UUID] = target_uuid
    return target_uuid


def is_cage_modifier(modifier) -> bool:
    try:
        node_group = getattr(modifier, "node_group", None)
        return bool(
            modifier and
            modifier.type == "NODES" and
            node_group and
            node_group.get(MODIFIER_MARKER, False)
        )
    except ReferenceError:
        return False


def is_cage_controller(obj) -> bool:
    try:
        return bool(obj and obj.get(CONTROLLER_MARKER, False))
    except ReferenceError:
        return False


def _set_controller_style(controller, deform_type=None):
    if controller is None:
        return
    if deform_type is None:
        deform_type = controller.sdh_cage_deform.deform_type
    display_type, color = CONTROLLER_STYLES.get(
        deform_type, CONTROLLER_STYLES["BEND"])
    if controller.empty_display_type != display_type:
        controller.empty_display_type = display_type
    if abs(controller.empty_display_size - 0.22) > EPSILON:
        controller.empty_display_size = 0.22
    if any(abs(controller.color[index] - color[index]) > EPSILON for index in range(4)):
        controller.color = color


def organize_helper_objects(context=None, hide_controllers=True):
    """Move owned Empty objects into one collection and hide visual clutter."""
    context = context or bpy.context
    scene = getattr(context, "scene", None)
    active = getattr(context, "object", None)
    for obj in tuple(bpy.data.objects):
        managed_origin = bool(
            obj.type == "EMPTY" and obj.get(PublicData.G_OWNER_PROP, False))
        if not is_cage_controller(obj) and not managed_origin:
            continue
        object_scenes = tuple(getattr(obj, "users_scene", ()))
        move_object_to_control_collection(
            obj, object_scenes[0] if object_scenes else scene)
        if is_cage_controller(obj):
            _set_controller_style(obj)
            obj.show_name = bool(obj == active and not hide_controllers)
            if hide_controllers or obj != active:
                set_helper_object_visible(obj, False)
        else:
            set_helper_object_visible(obj, False)


def cage_modifiers(obj):
    return tuple(mod for mod in getattr(obj, "modifiers", ()) if is_cage_modifier(mod))


def cage_modifier_uuid(modifier):
    node_group = getattr(modifier, "node_group", None)
    return str(node_group.get(MODIFIER_UUID, "")) if node_group else ""


def find_target(controller):
    target_uuid = str(controller.get(TARGET_UUID, "")) if controller else ""
    if not target_uuid:
        return None
    parent = getattr(controller, "parent", None)
    if (
            parent is not None and not is_cage_controller(parent) and
            str(parent.get(TARGET_UUID, "")) == target_uuid
    ):
        return parent
    for obj in bpy.data.objects:
        if str(obj.get(TARGET_UUID, "")) == target_uuid and not is_cage_controller(obj):
            return obj
    return None


def find_modifier(target, controller=None, modifier_uuid=None):
    if target is None:
        return None
    if modifier_uuid is None and controller is not None:
        modifier_uuid = str(controller.get(MODIFIER_UUID, ""))
    for modifier in target.modifiers:
        if (
                is_cage_modifier(modifier) and
                cage_modifier_uuid(modifier) == str(modifier_uuid or "")
        ):
            return modifier
    return None


def find_controller(target, modifier):
    if target is None or modifier is None:
        return None
    target_uuid = str(target.get(TARGET_UUID, ""))
    modifier_uuid = cage_modifier_uuid(modifier)
    matching = []
    for obj in bpy.data.objects:
        if (
                is_cage_controller(obj) and
                str(obj.get(TARGET_UUID, "")) == target_uuid and
                str(obj.get(MODIFIER_UUID, "")) == modifier_uuid
        ):
            matching.append(obj)
    return next(
        (obj for obj in matching if getattr(obj, "parent", None) == target),
        matching[0] if matching else None,
    )


def target_from_context(context):
    obj = getattr(context, "object", None)
    if is_cage_controller(obj):
        return find_target(obj)
    if obj and obj.type in SUPPORTED_TYPES:
        return obj
    return None


def resolve_context_deform(context, fallback=True):
    selected = getattr(context, "object", None)
    if is_cage_controller(selected):
        target = find_target(selected)
        if target is not None:
            ensure_target_stage_ownership(context, target)
        modifier = find_modifier(target, selected)
        return (target, modifier, selected) if target and modifier else (None, None, None)

    target = target_from_context(context)
    if target is None:
        return None, None, None
    ensure_target_stage_ownership(context, target)
    active = getattr(target.modifiers, "active", None)
    modifier = active if is_cage_modifier(active) else None
    if modifier is None and fallback:
        modifiers = cage_modifiers(target)
        modifier = modifiers[0] if modifiers else None
    controller = find_controller(target, modifier) if modifier else None
    return target, modifier, controller


def _interface_socket(node_group, name, in_out="INPUT"):
    for item in node_group.interface.items_tree:
        if getattr(item, "name", None) == name and getattr(item, "in_out", None) == in_out:
            return item
    return None


def modifier_input_identifier(modifier, name):
    node_group = getattr(modifier, "node_group", None)
    socket = _interface_socket(node_group, name) if node_group else None
    return socket.identifier if socket else None


def _modifier_input_property(modifier, identifier):
    interface = getattr(modifier, "properties", None)
    inputs = getattr(interface, "inputs", None)
    return getattr(inputs, identifier, None) if inputs else None


def modifier_input(modifier, name, default=None):
    identifier = modifier_input_identifier(modifier, name)
    if not identifier:
        return default
    socket = _modifier_input_property(modifier, identifier)
    if socket is not None and hasattr(socket, "value"):
        return socket.value
    try:
        return modifier.get(identifier, default)
    except TypeError:
        return default


def set_modifier_input(modifier, name, value):
    identifier = modifier_input_identifier(modifier, name)
    if not identifier:
        return False
    if isinstance(value, (Vector, Euler)):
        value = tuple(value)
    socket = _modifier_input_property(modifier, identifier)
    if socket is not None and hasattr(socket, "value"):
        socket.value = value
    else:
        modifier[identifier] = value
    return True


def _feed(node_group, value, socket):
    if hasattr(value, "node"):
        node_group.links.new(value, socket)
    else:
        socket.default_value = value


def _socket_by_type(sockets, name, socket_type=None):
    candidates = [socket for socket in sockets if socket.name == name]
    if socket_type:
        typed = [socket for socket in candidates if socket.bl_idname == socket_type]
        if typed:
            return typed[0]
    if not candidates:
        raise KeyError(name)
    return candidates[0]


def build_node_group(node_group):
    node_group.nodes.clear()
    node_group.interface.clear()

    output_geometry = node_group.interface.new_socket(
        name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    input_geometry = node_group.interface.new_socket(
        name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    center_socket = node_group.interface.new_socket(
        name="Center", in_out="INPUT", socket_type="NodeSocketVector")
    center_socket.subtype = "TRANSLATION"
    rotation_socket = node_group.interface.new_socket(
        name="Rotation", in_out="INPUT", socket_type="NodeSocketVector")
    rotation_socket.subtype = "EULER"
    size_socket = node_group.interface.new_socket(
        name="Size", in_out="INPUT", socket_type="NodeSocketVector")
    size_socket.default_value = (2.0, 2.0, 2.0)
    size_socket.min_value = EPSILON
    strength_socket = node_group.interface.new_socket(
        name="Strength", in_out="INPUT", socket_type="NodeSocketFloat")
    strength_socket.subtype = "ANGLE"
    strength_socket.default_value = math.radians(45.0)
    factor_socket = node_group.interface.new_socket(
        name="Factor", in_out="INPUT", socket_type="NodeSocketFloat")
    factor_socket.default_value = 0.5
    direction_socket = node_group.interface.new_socket(
        name="Direction", in_out="INPUT", socket_type="NodeSocketFloat")
    direction_socket.subtype = "ANGLE"
    deform_socket = node_group.interface.new_socket(
        name="Deform Type", in_out="INPUT", socket_type="NodeSocketInt")
    deform_socket.min_value = 0
    deform_socket.max_value = 3
    mode_socket = node_group.interface.new_socket(
        name="Mode", in_out="INPUT", socket_type="NodeSocketInt")
    mode_socket.min_value = 0
    mode_socket.max_value = 2
    origin_socket = node_group.interface.new_socket(
        name="Origin", in_out="INPUT", socket_type="NodeSocketInt")
    origin_socket.min_value = 0
    origin_socket.max_value = 3
    preserve_volume_socket = node_group.interface.new_socket(
        name="Preserve Volume", in_out="INPUT", socket_type="NodeSocketBool")
    preserve_volume_socket.default_value = True
    top_scale_socket = node_group.interface.new_socket(
        name="Top Scale", in_out="INPUT", socket_type="NodeSocketVector")
    top_scale_socket.default_value = (1.0, 1.0, 1.0)
    top_scale_socket.min_value = 0.05
    bottom_scale_socket = node_group.interface.new_socket(
        name="Bottom Scale", in_out="INPUT", socket_type="NodeSocketVector")
    bottom_scale_socket.default_value = (1.0, 1.0, 1.0)
    bottom_scale_socket.min_value = 0.05
    top_offset_socket = node_group.interface.new_socket(
        name="Top Offset", in_out="INPUT", socket_type="NodeSocketVector")
    top_offset_socket.subtype = "TRANSLATION"
    bottom_offset_socket = node_group.interface.new_socket(
        name="Bottom Offset", in_out="INPUT", socket_type="NodeSocketVector")
    bottom_offset_socket.subtype = "TRANSLATION"

    nodes = node_group.nodes
    links = node_group.links
    group_input = nodes.new("NodeGroupInput")
    group_input.label = "Cage Deform Parameters"
    group_input.location = (-1800, 300)
    group_output = nodes.new("NodeGroupOutput")
    group_output.location = (1900, 300)
    position = nodes.new("GeometryNodeInputPosition")
    position.location = (-1800, 700)
    set_position = nodes.new("GeometryNodeSetPosition")
    set_position.location = (1650, 300)

    def math_node(operation, first, second=None, label=None):
        node = nodes.new("ShaderNodeMath")
        node.operation = operation
        node.label = label or operation.title()
        _feed(node_group, first, node.inputs[0])
        if second is not None:
            _feed(node_group, second, node.inputs[1])
        return node.outputs[0]

    def vector_math(operation, first, second):
        node = nodes.new("ShaderNodeVectorMath")
        node.operation = operation
        _feed(node_group, first, node.inputs[0])
        _feed(node_group, second, node.inputs[1])
        return node.outputs[0]

    def compare(data_type, operation, first, second):
        node = nodes.new("FunctionNodeCompare")
        node.data_type = data_type
        node.operation = operation
        socket_type = "NodeSocketInt" if data_type == "INT" else "NodeSocketFloat"
        _feed(node_group, first, _socket_by_type(node.inputs, "A", socket_type))
        _feed(node_group, second, _socket_by_type(node.inputs, "B", socket_type))
        return node.outputs[0]

    def boolean(operation, first, second):
        node = nodes.new("FunctionNodeBooleanMath")
        node.operation = operation
        _feed(node_group, first, node.inputs[0])
        _feed(node_group, second, node.inputs[1])
        return node.outputs[0]

    def switch(input_type, condition, false_value, true_value):
        node = nodes.new("GeometryNodeSwitch")
        node.input_type = input_type
        _feed(node_group, condition, _socket_by_type(node.inputs, "Switch", "NodeSocketBool"))
        _feed(node_group, false_value, _socket_by_type(node.inputs, "False"))
        _feed(node_group, true_value, _socket_by_type(node.inputs, "True"))
        return node.outputs[0]

    def separate(vector):
        node = nodes.new("ShaderNodeSeparateXYZ")
        _feed(node_group, vector, node.inputs[0])
        return node.outputs[0], node.outputs[1], node.outputs[2]

    def combine(x, y, z):
        node = nodes.new("ShaderNodeCombineXYZ")
        _feed(node_group, x, node.inputs[0])
        _feed(node_group, y, node.inputs[1])
        _feed(node_group, z, node.inputs[2])
        return node.outputs[0]

    def rotate(vector, rotation, invert=False):
        node = nodes.new("ShaderNodeVectorRotate")
        node.rotation_type = "EULER_XYZ"
        node.invert = invert
        _feed(node_group, vector, node.inputs[0])
        _feed(node_group, rotation, _socket_by_type(node.inputs, "Rotation"))
        return node.outputs[0]

    geometry = group_input.outputs[input_geometry.identifier]
    center = group_input.outputs[center_socket.identifier]
    rotation = group_input.outputs[rotation_socket.identifier]
    size = group_input.outputs[size_socket.identifier]
    strength = group_input.outputs[strength_socket.identifier]
    factor = group_input.outputs[factor_socket.identifier]
    direction = group_input.outputs[direction_socket.identifier]
    deform_type = group_input.outputs[deform_socket.identifier]
    mode = group_input.outputs[mode_socket.identifier]
    origin = group_input.outputs[origin_socket.identifier]
    preserve_volume = group_input.outputs[preserve_volume_socket.identifier]
    top_scale = group_input.outputs[top_scale_socket.identifier]
    bottom_scale = group_input.outputs[bottom_scale_socket.identifier]
    top_offset = group_input.outputs[top_offset_socket.identifier]
    bottom_offset = group_input.outputs[bottom_offset_socket.identifier]

    relative = vector_math("SUBTRACT", position.outputs[0], center)
    local_position = rotate(relative, rotation, invert=True)
    x, y, z = separate(local_position)
    size_x, size_y, size_z = separate(size)

    half_x = math_node("MULTIPLY", math_node("ABSOLUTE", size_x), 0.5)
    half_y = math_node("MULTIPLY", math_node("ABSOLUTE", size_y), 0.5)
    half_z = math_node("MULTIPLY", math_node("ABSOLUTE", size_z), 0.5)
    length = math_node("MAXIMUM", math_node("ABSOLUTE", size_y), EPSILON)
    frame_t_raw = math_node(
        "DIVIDE", math_node("ADD", y, half_y), length)
    frame_t_clamped = math_node(
        "MINIMUM", math_node("MAXIMUM", frame_t_raw, 0.0), 1.0)
    is_unlimited = compare(
        "INT", "EQUAL", mode, MODE_VALUES["UNLIMITED"])
    frame_t = switch(
        "FLOAT", is_unlimited, frame_t_clamped, frame_t_raw)

    top_scale_x, _top_scale_y, top_scale_z = separate(top_scale)
    bottom_scale_x, _bottom_scale_y, bottom_scale_z = separate(bottom_scale)
    top_offset_x, _top_offset_y, top_offset_z = separate(top_offset)
    bottom_offset_x, _bottom_offset_y, bottom_offset_z = separate(bottom_offset)

    def interpolate(bottom, top):
        return math_node(
            "ADD", bottom,
            math_node("MULTIPLY", math_node("SUBTRACT", top, bottom), frame_t),
        )

    frame_scale_x = interpolate(bottom_scale_x, top_scale_x)
    frame_scale_z = interpolate(bottom_scale_z, top_scale_z)
    frame_offset_x = interpolate(bottom_offset_x, top_offset_x)
    frame_offset_z = interpolate(bottom_offset_z, top_offset_z)
    framed_x = math_node(
        "ADD", math_node("MULTIPLY", x, frame_scale_x), frame_offset_x)
    framed_z = math_node(
        "ADD", math_node("MULTIPLY", z, frame_scale_z), frame_offset_z)
    framed_position = combine(framed_x, y, framed_z)

    cos_direction = math_node("COSINE", direction)
    sin_direction = math_node("SINE", direction)
    negative_sin_direction = math_node("MULTIPLY", sin_direction, -1.0)
    u = math_node(
        "ADD",
        math_node("MULTIPLY", cos_direction, framed_x),
        math_node("MULTIPLY", sin_direction, framed_z),
    )
    v = math_node(
        "ADD",
        math_node("MULTIPLY", negative_sin_direction, framed_x),
        math_node("MULTIPLY", cos_direction, framed_z),
    )

    strength_is_zero = compare(
        "FLOAT", "LESS_THAN", math_node("ABSOLUTE", strength), EPSILON)
    safe_strength = switch("FLOAT", strength_is_zero, strength, 1.0)
    curvature = math_node("DIVIDE", strength, length)
    radius = math_node("DIVIDE", length, safe_strength)

    is_bottom = compare("INT", "EQUAL", origin, ORIGIN_VALUES["BOTTOM"])
    is_top = compare("INT", "EQUAL", origin, ORIGIN_VALUES["TOP"])
    is_symmetric = compare(
        "INT", "EQUAL", origin, ORIGIN_VALUES["SYMMETRIC"])
    negative_half_y = math_node("MULTIPLY", half_y, -1.0)
    origin_y = switch(
        "FLOAT", is_top,
        switch("FLOAT", is_bottom, 0.0, negative_half_y),
        half_y,
    )
    distance = math_node("SUBTRACT", y, origin_y)

    is_lower = compare("FLOAT", "LESS_THAN", y, 0.0)
    symmetric_lower = boolean("AND", is_symmetric, is_lower)
    negative_curvature = math_node("MULTIPLY", curvature, -1.0)
    effective_curvature = switch(
        "FLOAT", symmetric_lower, curvature, negative_curvature)
    negative_radius = math_node("MULTIPLY", radius, -1.0)
    effective_radius = switch(
        "FLOAT", symmetric_lower, radius, negative_radius)

    lower_distance = math_node("SUBTRACT", negative_half_y, origin_y)
    upper_distance = math_node("SUBTRACT", half_y, origin_y)
    clamped_distance = math_node(
        "MINIMUM",
        math_node("MAXIMUM", distance, lower_distance),
        upper_distance,
    )
    is_limited = compare("INT", "EQUAL", mode, MODE_VALUES["LIMITED"])
    is_within = compare("INT", "EQUAL", mode, MODE_VALUES["WITHIN_BOX"])
    evaluated_distance = switch(
        "FLOAT", is_limited, distance, clamped_distance)
    outside_distance = switch(
        "FLOAT", is_limited, 0.0,
        math_node("SUBTRACT", distance, clamped_distance),
    )

    theta = math_node("MULTIPLY", effective_curvature, evaluated_distance)
    cosine = math_node("COSINE", theta)
    sine = math_node("SINE", theta)
    radial = math_node("ADD", effective_radius, u)
    bent_u = math_node(
        "SUBTRACT",
        math_node("SUBTRACT", math_node("MULTIPLY", radial, cosine), effective_radius),
        math_node("MULTIPLY", sine, outside_distance),
    )
    bent_y = math_node(
        "ADD",
        math_node("ADD", origin_y, math_node("MULTIPLY", radial, sine)),
        math_node("MULTIPLY", cosine, outside_distance),
    )

    bent_x = math_node(
        "SUBTRACT",
        math_node("MULTIPLY", cos_direction, bent_u),
        math_node("MULTIPLY", sin_direction, v),
    )
    bent_z = math_node(
        "ADD",
        math_node("MULTIPLY", sin_direction, bent_u),
        math_node("MULTIPLY", cos_direction, v),
    )
    bent_raw = combine(bent_x, bent_y, bent_z)
    bent_local = switch(
        "VECTOR", strength_is_zero, bent_raw, framed_position)

    profile_distance = switch(
        "FLOAT", is_symmetric, evaluated_distance,
        math_node("ABSOLUTE", evaluated_distance),
    )
    profile = math_node("DIVIDE", profile_distance, length)

    twist_angle = math_node("MULTIPLY", strength, profile)
    twist_cosine = math_node("COSINE", twist_angle)
    twist_sine = math_node("SINE", twist_angle)
    twisted_x = math_node(
        "SUBTRACT",
        math_node("MULTIPLY", twist_cosine, framed_x),
        math_node("MULTIPLY", twist_sine, framed_z),
    )
    twisted_z = math_node(
        "ADD",
        math_node("MULTIPLY", twist_sine, framed_x),
        math_node("MULTIPLY", twist_cosine, framed_z),
    )
    twisted_local = combine(twisted_x, y, twisted_z)

    taper_scale = math_node(
        "ADD", 1.0, math_node("MULTIPLY", factor, profile))
    tapered_local = combine(
        math_node("MULTIPLY", framed_x, taper_scale),
        y,
        math_node("MULTIPLY", framed_z, taper_scale),
    )

    stretch_scale = math_node("ADD", 1.0, factor)
    stretched_y = math_node(
        "ADD",
        math_node(
            "ADD", origin_y,
            math_node("MULTIPLY", evaluated_distance, stretch_scale),
        ),
        outside_distance,
    )
    safe_stretch = math_node(
        "MAXIMUM", math_node("ABSOLUTE", stretch_scale), EPSILON)
    volume_scale = switch(
        "FLOAT", preserve_volume, 1.0,
        math_node("POWER", safe_stretch, -0.5),
    )
    stretched_local = combine(
        math_node("MULTIPLY", framed_x, volume_scale),
        stretched_y,
        math_node("MULTIPLY", framed_z, volume_scale),
    )

    is_twist = compare(
        "INT", "EQUAL", deform_type, DEFORM_VALUES["TWIST"])
    is_taper = compare(
        "INT", "EQUAL", deform_type, DEFORM_VALUES["TAPER"])
    is_stretch = compare(
        "INT", "EQUAL", deform_type, DEFORM_VALUES["STRETCH"])
    type_result = switch("VECTOR", is_twist, bent_local, twisted_local)
    type_result = switch("VECTOR", is_taper, type_result, tapered_local)
    type_result = switch("VECTOR", is_stretch, type_result, stretched_local)

    inside_x = compare("FLOAT", "LESS_EQUAL", math_node("ABSOLUTE", x), half_x)
    inside_y = compare("FLOAT", "LESS_EQUAL", math_node("ABSOLUTE", y), half_y)
    inside_z = compare("FLOAT", "LESS_EQUAL", math_node("ABSOLUTE", z), half_z)
    inside_box = boolean("AND", boolean("AND", inside_x, inside_y), inside_z)
    within_result = switch("VECTOR", inside_box, local_position, type_result)
    mode_result = switch("VECTOR", is_within, type_result, within_result)
    rotated_result = rotate(mode_result, rotation, invert=False)
    final_position = vector_math("ADD", rotated_result, center)

    links.new(geometry, set_position.inputs["Geometry"])
    links.new(final_position, set_position.inputs["Position"])
    links.new(set_position.outputs["Geometry"], group_output.inputs[output_geometry.identifier])

    node_group[GROUP_MARKER] = GROUP_VERSION
    node_group.description = "Independent cage deformation with bend, twist, taper, and stretch modes"
    node_group.is_modifier = True


def ensure_node_group():
    node_group = bpy.data.node_groups.get(GROUP_NAME)
    if node_group is None or node_group.bl_idname != "GeometryNodeTree":
        node_group = bpy.data.node_groups.new(GROUP_NAME, "GeometryNodeTree")
    if int(node_group.get(GROUP_MARKER, 0)) != GROUP_VERSION:
        build_node_group(node_group)
    return node_group


def create_stage_node_group():
    stage_uuid = str(uuid.uuid4())
    node_group = ensure_node_group().copy()
    node_group.name = f"SDH Cage Deform {stage_uuid[:8]}"
    node_group[MODIFIER_MARKER] = True
    node_group[MODIFIER_UUID] = stage_uuid
    return node_group


def deform_point_local(point, size, deform_type="BEND", strength=0.0,
                       factor=0.0, direction=0.0, mode="LIMITED",
                       origin="BOTTOM", preserve_volume=True,
                       top_scale=(1.0, 1.0), bottom_scale=(1.0, 1.0),
                       top_offset=(0.0, 0.0), bottom_offset=(0.0, 0.0)):
    """Reference implementation used by viewport drawing and regressions."""
    point = Vector(point)
    size = Vector((max(abs(value), EPSILON) for value in size))

    half = size * 0.5
    origin_y = {
        "BOTTOM": -half.y,
        "CENTER": 0.0,
        "SYMMETRIC": 0.0,
        "TOP": half.y,
    }[origin]
    distance = point.y - origin_y
    lower = -half.y - origin_y
    upper = half.y - origin_y

    inside = (
        abs(point.x) <= half.x and
        abs(point.y) <= half.y and
        abs(point.z) <= half.z
    )
    if mode == "WITHIN_BOX" and not inside:
        return point.copy()

    frame_t = (point.y + half.y) / size.y
    if mode != "UNLIMITED":
        frame_t = min(max(frame_t, 0.0), 1.0)
    scale_x = bottom_scale[0] + (top_scale[0] - bottom_scale[0]) * frame_t
    scale_z = bottom_scale[1] + (top_scale[1] - bottom_scale[1]) * frame_t
    offset_x = bottom_offset[0] + (top_offset[0] - bottom_offset[0]) * frame_t
    offset_z = bottom_offset[1] + (top_offset[1] - bottom_offset[1]) * frame_t
    framed = Vector((
        point.x * scale_x + offset_x,
        point.y,
        point.z * scale_z + offset_z,
    ))

    evaluated_distance = distance
    outside_distance = 0.0
    if mode == "LIMITED":
        evaluated_distance = min(max(distance, lower), upper)
        outside_distance = distance - evaluated_distance

    profile_distance = (
        abs(evaluated_distance)
        if origin == "SYMMETRIC" else evaluated_distance
    )
    profile = profile_distance / size.y

    if deform_type == "TWIST":
        theta = strength * profile
        cosine = math.cos(theta)
        sine = math.sin(theta)
        return Vector((
            cosine * framed.x - sine * framed.z,
            point.y,
            sine * framed.x + cosine * framed.z,
        ))

    if deform_type == "TAPER":
        scale = 1.0 + factor * profile
        return Vector((framed.x * scale, point.y, framed.z * scale))

    if deform_type == "STRETCH":
        scale = 1.0 + factor
        volume_scale = (
            max(abs(scale), EPSILON) ** -0.5
            if preserve_volume else 1.0
        )
        return Vector((
            framed.x * volume_scale,
            origin_y + evaluated_distance * scale + outside_distance,
            framed.z * volume_scale,
        ))

    if abs(strength) < EPSILON:
        return framed
    cos_direction = math.cos(direction)
    sin_direction = math.sin(direction)
    u = cos_direction * framed.x + sin_direction * framed.z
    v = -sin_direction * framed.x + cos_direction * framed.z
    curvature = strength / size.y
    if origin == "SYMMETRIC" and point.y < 0.0:
        curvature = -curvature
    radius = 1.0 / curvature
    theta = curvature * evaluated_distance
    cosine = math.cos(theta)
    sine = math.sin(theta)
    radial = radius + u
    deformed_u = radial * cosine - radius - sine * outside_distance
    deformed_y = origin_y + radial * sine + cosine * outside_distance
    deformed_x = cos_direction * deformed_u - sin_direction * v
    deformed_z = sin_direction * deformed_u + cos_direction * v
    return Vector((deformed_x, deformed_y, deformed_z))


def _controller_update(properties, _context):
    controller = getattr(properties, "id_data", None)
    if is_cage_controller(controller):
        sync_controller(controller, pull_transform=False)


class SDHCageControllerProperties(PropertyGroup):
    deform_type: EnumProperty(
        name="Deformation Type",
        description="Shape operation performed inside the cage",
        items=(
            ("BEND", "Bend", "Curve geometry along the cage axis", "MOD_SIMPLEDEFORM", 0),
            ("TWIST", "Twist", "Rotate cross-sections around the cage axis", "FORCE_VORTEX", 1),
            ("TAPER", "Taper", "Scale cross-sections along the cage axis", "FULLSCREEN_EXIT", 2),
            ("STRETCH", "Stretch", "Scale geometry along the cage axis", "EMPTY_ARROWS", 3),
        ),
        default="BEND",
        update=_controller_update,
    )
    strength: FloatProperty(
        name="Angle",
        description="Total Bend or Twist angle through the cage length",
        subtype="ANGLE",
        default=math.radians(45.0),
        soft_min=-math.tau,
        soft_max=math.tau,
        update=_controller_update,
    )
    factor: FloatProperty(
        name="Factor",
        description="Amount used by Taper and Stretch",
        default=0.5,
        soft_min=-2.0,
        soft_max=2.0,
        update=_controller_update,
    )
    direction: FloatProperty(
        name="Direction",
        description="Direction of Bend around the cage axis",
        subtype="ANGLE",
        default=0.0,
        soft_min=-math.pi,
        soft_max=math.pi,
        update=_controller_update,
    )
    size: FloatVectorProperty(
        name="Size",
        description="Dimensions of the independent deformation cage",
        subtype="XYZ",
        default=(2.0, 2.0, 2.0),
        min=EPSILON,
        soft_max=1000.0,
        update=_controller_update,
    )
    mode: EnumProperty(
        name="Mode",
        description="How geometry outside the cage is handled",
        items=(
            ("LIMITED", "Limited", "Deform inside; continue outside from the cage ends"),
            ("WITHIN_BOX", "Within Box", "Only points inside the cage are affected"),
            ("UNLIMITED", "Unlimited", "Continue deformation beyond the cage"),
        ),
        default="LIMITED",
        update=_controller_update,
    )
    origin: EnumProperty(
        name="Origin",
        description="Starting pattern of the deformation",
        items=(
            ("BOTTOM", "Bottom", "Start at the lower cage boundary"),
            ("CENTER", "Center", "Use signed distance from the cage center"),
            ("SYMMETRIC", "Symmetric", "Mirror the deformation profile across the center"),
            ("TOP", "Top", "Start at the upper cage boundary"),
        ),
        default="BOTTOM",
        update=_controller_update,
    )
    alignment: EnumProperty(
        name="Deform Axis",
        description="Target axis used when aligning and fitting the cage",
        items=(
            ("AUTO", "Auto", "Use the longest local dimension"),
            ("POS_X", "+X", "Align cage Y to target +X"),
            ("NEG_X", "-X", "Align cage Y to target -X"),
            ("POS_Y", "+Y", "Align cage Y to target +Y"),
            ("NEG_Y", "-Y", "Align cage Y to target -Y"),
            ("POS_Z", "+Z", "Align cage Y to target +Z"),
            ("NEG_Z", "-Z", "Align cage Y to target -Z"),
        ),
        default="AUTO",
    )
    show_cage: BoolProperty(
        name="Show Cage",
        description="Draw the cyan cage and orange deformation guide",
        default=True,
    )
    show_axis_gizmo: BoolProperty(
        name="Show Axis Switch",
        description=(
            "Show bend-trend choices around the cage; the choices hide after "
            "selection unless Ctrl is held"
        ),
        default=False,
    )
    show_direction_handle: BoolProperty(
        name="Show Bend Direction Handle",
        description="Show a separate ring for adjusting the Bend direction",
        default=False,
    )
    show_numeric_controls: BoolProperty(
        name="Numeric Controls",
        description="Show exact cage size, location, and rotation values",
        default=False,
    )
    top_scale: FloatVectorProperty(
        name="Top Scale",
        description="Scale the top cage cross-section without changing the bottom",
        size=2,
        default=(1.0, 1.0),
        min=0.05,
        soft_max=4.0,
        update=_controller_update,
    )
    bottom_scale: FloatVectorProperty(
        name="Bottom Scale",
        description="Scale the bottom cage cross-section without changing the top",
        size=2,
        default=(1.0, 1.0),
        min=0.05,
        soft_max=4.0,
        update=_controller_update,
    )
    top_offset: FloatVectorProperty(
        name="Top Offset",
        description="Move the top cage cross-section without changing the bottom",
        size=2,
        default=(0.0, 0.0),
        soft_min=-10.0,
        soft_max=10.0,
        update=_controller_update,
    )
    bottom_offset: FloatVectorProperty(
        name="Bottom Offset",
        description="Move the bottom cage cross-section without changing the top",
        size=2,
        default=(0.0, 0.0),
        soft_min=-10.0,
        soft_max=10.0,
        update=_controller_update,
    )
    show_end_handles: BoolProperty(
        name="Show Shape Handles",
        description="Show separate top and bottom cross-section shaping handles",
        default=True,
    )
    show_boundary_handles: BoolProperty(
        name="Show Length Handles",
        description="Show handles that move the top or bottom cage boundary independently",
        default=True,
    )
    limit_boundaries_to_object: BoolProperty(
        name="Limit to Object Bounds",
        description=(
            "Prevent the top and bottom cage boundaries from moving beyond "
            "the input object's bounds"
        ),
        default=True,
    )
    show_end_shape_settings: BoolProperty(
        name="Independent Ends",
        description="Show separate top and bottom cross-section controls",
        default=True,
    )
    preserve_volume: BoolProperty(
        name="Preserve Volume",
        description="Compensate cross-section size while stretching",
        default=True,
        update=_controller_update,
    )


def _target_and_modifier(controller):
    target = find_target(controller)
    return target, find_modifier(target, controller)


def sync_controller(controller, pull_transform=True):
    pointer = _pointer(controller)
    if not pointer or pointer in _SYNCING:
        return False
    target, modifier = _target_and_modifier(controller)
    if target is None or modifier is None:
        return False

    _SYNCING.add(pointer)
    try:
        properties = controller.sdh_cage_deform
        _set_controller_style(controller, properties.deform_type)
        if pull_transform:
            size = tuple(max(abs(value) * 2.0, EPSILON) for value in controller.scale)
            if any(abs(properties.size[index] - size[index]) > EPSILON
                   for index in range(3)):
                properties.size = size
        else:
            controller.scale = tuple(max(value, EPSILON) * 0.5 for value in properties.size)

        values = {
            "Center": tuple(controller.location),
            "Rotation": tuple(controller.rotation_euler),
            "Size": tuple(properties.size),
            "Strength": properties.strength,
            "Factor": properties.factor,
            "Direction": properties.direction,
            "Deform Type": DEFORM_VALUES[properties.deform_type],
            "Mode": MODE_VALUES[properties.mode],
            "Origin": ORIGIN_VALUES[properties.origin],
            "Preserve Volume": properties.preserve_volume,
            "Top Scale": (
                properties.top_scale[0], 1.0, properties.top_scale[1]),
            "Bottom Scale": (
                properties.bottom_scale[0], 1.0, properties.bottom_scale[1]),
            "Top Offset": (
                properties.top_offset[0], 0.0, properties.top_offset[1]),
            "Bottom Offset": (
                properties.bottom_offset[0], 0.0, properties.bottom_offset[1]),
        }
        changed = False
        for name, value in values.items():
            old = modifier_input(modifier, name)
            if isinstance(value, tuple):
                old_tuple = tuple(old) if old is not None else ()
                different = len(old_tuple) != len(value) or any(
                    abs(float(a) - float(b)) > EPSILON for a, b in zip(old_tuple, value))
            else:
                different = old is None or abs(float(old) - float(value)) > EPSILON
            if different:
                set_modifier_input(modifier, name, value)
                changed = True
        if changed:
            target.update_tag()
        return changed
    finally:
        _SYNCING.discard(pointer)


def sync_all_controllers(pull_transform=True):
    changed = False
    for obj in tuple(bpy.data.objects):
        if is_cage_controller(obj):
            changed = sync_controller(obj, pull_transform=pull_transform) or changed
    return changed


def upgrade_managed_stages():
    """Rebuild older managed node groups in place so saved scenes stay live."""
    upgraded = 0
    rebuilt = set()
    for target in tuple(bpy.data.objects):
        for modifier in tuple(getattr(target, "modifiers", ())):
            node_group = getattr(modifier, "node_group", None)
            if not is_cage_modifier(modifier) or node_group in rebuilt:
                continue
            if int(node_group.get(GROUP_MARKER, 0)) == GROUP_VERSION:
                continue
            rebuilt.add(node_group)
            build_node_group(node_group)
            controller = find_controller(target, modifier)
            if controller is not None:
                controller.sdh_cage_deform.show_axis_gizmo = False
                controller.sdh_cage_deform.show_direction_handle = False
                _set_controller_style(controller)
                sync_controller(controller, pull_transform=False)
            target.update_tag()
            upgraded += 1
    return upgraded


def _legacy_stage_info(node_group):
    if node_group is None:
        return None
    required_inputs = (
        "Geometry", "Center", "Rotation", "Size", "Strength",
        "Direction", "Mode", "Origin",
    )
    if not all(_interface_socket(node_group, name) for name in required_inputs):
        return None
    for key in node_group.keys():
        if (
                key != MODIFIER_MARKER and key.startswith("_sdh_") and
                key.endswith("_stage") and node_group.get(key, False)
        ):
            base = key[:-len("stage")]
            return {
                "base": base,
                "marker": key,
                "modifier_uuid": base + "modifier_uuid",
                "controller_marker": base + "controller",
                "controller_uuid": base + "controller_uuid",
                "target_uuid": base + "target_uuid",
                "property": base.lstrip("_").rstrip("_"),
            }
    return None


def _legacy_core_group(node_group):
    if node_group is None or node_group.users != 0:
        return False
    required_inputs = (
        "Geometry", "Center", "Rotation", "Size", "Strength",
        "Direction", "Mode", "Origin",
    )
    if not all(_interface_socket(node_group, name) for name in required_inputs):
        return False
    return any(
        key != GROUP_MARKER and key.startswith("_sdh_") and
        key.endswith("_group") and node_group.get(key, False)
        for key in node_group.keys()
    )


def _legacy_controller(target, modifier, info):
    target_uuid = str(target.get(info["target_uuid"], ""))
    modifier_uuid = str(modifier.node_group.get(info["modifier_uuid"], ""))
    for obj in bpy.data.objects:
        try:
            if (
                    obj.get(info["controller_marker"], False) and
                    str(obj.get(info["target_uuid"], "")) == target_uuid and
                    str(obj.get(info["modifier_uuid"], "")) == modifier_uuid
            ):
                return obj
        except ReferenceError:
            continue
    return None


def _migrate_animation_paths(controller, old_property):
    animation_data = getattr(controller, "animation_data", None)
    if animation_data is None:
        return
    old_prefix = old_property + "."
    new_prefix = "sdh_cage_deform."
    action = getattr(animation_data, "action", None)
    curves = tuple(getattr(action, "fcurves", ())) if action else ()
    curves += tuple(getattr(animation_data, "drivers", ()))
    for curve in curves:
        if old_prefix in curve.data_path:
            curve.data_path = curve.data_path.replace(old_prefix, new_prefix)


def migrate_legacy_stages(context=None):
    """Upgrade prototype cage stages without keeping legacy names visible."""
    migrated = 0
    context = context or bpy.context
    old_groups = set()
    for target in tuple(bpy.data.objects):
        for modifier in tuple(getattr(target, "modifiers", ())):
            old_group = getattr(modifier, "node_group", None)
            legacy = (
                _legacy_stage_info(old_group)
                if modifier.type == "NODES" else None
            )
            if legacy is None:
                continue

            old_groups.add(old_group)
            old_modifier_uuid = str(
                old_group.get(legacy["modifier_uuid"], "")) or str(uuid.uuid4())
            old_target_uuid = str(
                target.get(legacy["target_uuid"], "")) or str(uuid.uuid4())
            # Blender 4.2 may expose vector sockets as live RNA arrays whose
            # storage is invalidated when the node group is replaced below.
            # Snapshot every legacy value before changing modifier.node_group.
            values = {
                "Size": tuple(modifier_input(
                    modifier, "Size", (2.0, 2.0, 2.0))),
                "Strength": float(modifier_input(
                    modifier, "Strength", math.radians(45.0))),
                "Direction": float(modifier_input(
                    modifier, "Direction", 0.0)),
                "Mode": int(modifier_input(modifier, "Mode", 0)),
                "Origin": int(modifier_input(modifier, "Origin", 0)),
            }

            controller = _legacy_controller(target, modifier, legacy)
            new_group = create_stage_node_group()
            new_group[MODIFIER_UUID] = old_modifier_uuid
            modifier.node_group = new_group
            if controller is None:
                target[TARGET_UUID] = old_target_uuid
                controller = _new_controller(context, target, modifier)
            else:
                target[TARGET_UUID] = old_target_uuid
                controller[CONTROLLER_MARKER] = True
                controller[CONTROLLER_UUID] = str(
                    controller.get(legacy["controller_uuid"], "")) or str(uuid.uuid4())
                controller[TARGET_UUID] = old_target_uuid
                controller[MODIFIER_UUID] = old_modifier_uuid
                controller.hide_render = True
                controller.show_in_front = True
                _set_controller_style(controller, "BEND")
                _migrate_animation_paths(controller, legacy["property"])

            pointer = _pointer(controller)
            _SYNCING.add(pointer)
            try:
                properties = controller.sdh_cage_deform
                properties.deform_type = "BEND"
                properties.size = tuple(values["Size"])
                properties.strength = float(values["Strength"])
                properties.direction = float(values["Direction"])
                properties.mode = {
                    0: "LIMITED", 1: "WITHIN_BOX", 2: "UNLIMITED",
                }.get(int(values["Mode"]), "LIMITED")
                properties.origin = {
                    0: "BOTTOM", 1: "CENTER", 2: "SYMMETRIC", 3: "TOP",
                }.get(int(values["Origin"]), "BOTTOM")
                controller.scale = tuple(
                    max(abs(value), EPSILON) * 0.5 for value in properties.size)
            finally:
                _SYNCING.discard(pointer)

            if "Cage" not in modifier.name:
                modifier.name = "Cage Deform"
            controller.name = f"{modifier.name} Controller"
            for owner in (target, controller):
                for key in tuple(owner.keys()):
                    if key.startswith(legacy["base"]):
                        del owner[key]
            sync_controller(controller, pull_transform=False)
            move_object_to_control_collection(controller, getattr(context, "scene", None))
            set_helper_object_visible(controller, False)
            migrated += 1

    for node_group in old_groups:
        if node_group.users == 0:
            bpy.data.node_groups.remove(node_group)
    for node_group in tuple(bpy.data.node_groups):
        if _legacy_core_group(node_group):
            bpy.data.node_groups.remove(node_group)
    return migrated


def _controller_timer():
    global _LEGACY_MIGRATION_PENDING
    if _LEGACY_MIGRATION_PENDING:
        migrate_legacy_stages()
        upgrade_managed_stages()
        organize_helper_objects()
        _LEGACY_MIGRATION_PENDING = False
    sync_all_controllers(pull_transform=True)
    return 0.08 if any(is_cage_controller(obj) for obj in bpy.data.objects) else 0.5


@persistent
def _frame_change_sync(_scene, *_args):
    sync_all_controllers(pull_transform=True)


@persistent
def _render_sync(_scene, *_args):
    sync_all_controllers(pull_transform=True)


@persistent
def _load_sync(_unused):
    migrate_legacy_stages()
    upgrade_managed_stages()
    organize_helper_objects()
    sync_all_controllers(pull_transform=True)


def _collection_for(context, target):
    collection = getattr(context, "collection", None)
    if collection:
        return collection
    if target and target.users_collection:
        return target.users_collection[0]
    return context.scene.collection


def _activate(context, obj):
    if obj is None:
        return
    for selected in tuple(context.selected_objects):
        selected.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def _modifier_input_bounds(context, target, modifier):
    try:
        stack_index = tuple(target.modifiers).index(modifier)
    except ValueError:
        return _object_fallback_bounds(target)

    clone = None
    try:
        clone = target.copy()
        clone.name = f"{target.name}_SDH_BEND_FIT"
        clone[RUNTIME_EVALUATOR] = True
        clone.hide_render = True
        clone.hide_select = True
        clone.display_type = "BOUNDS"
        try:
            clone.animation_data_clear()
        except (AttributeError, RuntimeError):
            pass
        _collection_for(context, target).objects.link(clone)
        hide_runtime_object(clone, getattr(context, "scene", None))
        original_modifiers = tuple(target.modifiers)
        for index, clone_modifier in enumerate(tuple(clone.modifiers)):
            clone_modifier.show_viewport = (
                index < stack_index and original_modifiers[index].show_viewport)
        context.view_layer.update()
        evaluated = clone.evaluated_get(context.evaluated_depsgraph_get())
        return _bounds_from_points(
            evaluated.bound_box,
            fallback=_object_fallback_bounds(target),
        )
    finally:
        if clone is not None:
            try:
                bpy.data.objects.remove(clone, do_unlink=True)
            except (ReferenceError, RuntimeError):
                pass


def _alignment_rotation(alignment, bounds):
    if alignment == "AUTO":
        minimum, maximum = bounds
        extents = maximum - minimum
        alignment = ("POS_X", "POS_Y", "POS_Z")[max(range(3), key=lambda index: extents[index])]
    return {
        "POS_X": Euler((0.0, 0.0, -math.pi * 0.5)),
        "NEG_X": Euler((0.0, 0.0, math.pi * 0.5)),
        "POS_Y": Euler((0.0, 0.0, 0.0)),
        "NEG_Y": Euler((math.pi, 0.0, 0.0)),
        "POS_Z": Euler((math.pi * 0.5, 0.0, 0.0)),
        "NEG_Z": Euler((-math.pi * 0.5, 0.0, 0.0)),
    }[alignment]


def _bounds_corners(bounds) -> Iterable[Vector]:
    minimum, maximum = bounds
    for x in (minimum.x, maximum.x):
        for y in (minimum.y, maximum.y):
            for z in (minimum.z, maximum.z):
                yield Vector((x, y, z))


def fit_controller(context, target, modifier, controller):
    bounds = _modifier_input_bounds(context, target, modifier)
    properties = controller.sdh_cage_deform
    rotation = _alignment_rotation(properties.alignment, bounds)
    rotation_matrix = rotation.to_matrix()
    center = (bounds[0] + bounds[1]) * 0.5
    local_points = [rotation_matrix.inverted() @ (point - center)
                    for point in _bounds_corners(bounds)]
    minimum = Vector(tuple(min(point[index] for point in local_points) for index in range(3)))
    maximum = Vector(tuple(max(point[index] for point in local_points) for index in range(3)))
    local_center = (minimum + maximum) * 0.5
    size = tuple(max(maximum[index] - minimum[index], EPSILON) for index in range(3))

    pointer = _pointer(controller)
    _SYNCING.add(pointer)
    try:
        controller.location = center + rotation_matrix @ local_center
        controller.rotation_euler = rotation
        properties.size = size
        controller.scale = tuple(value * 0.5 for value in size)
    finally:
        _SYNCING.discard(pointer)
    sync_controller(controller, pull_transform=False)
    return bounds


def _new_controller(context, target, modifier):
    target_uuid = ensure_unique_target_uuid(target)
    modifier_uuid = cage_modifier_uuid(modifier)
    controller = bpy.data.objects.new(f"{modifier.name} Controller", None)
    controller[CONTROLLER_MARKER] = True
    controller[CONTROLLER_UUID] = str(uuid.uuid4())
    controller[TARGET_UUID] = target_uuid
    controller[MODIFIER_UUID] = modifier_uuid
    controller.show_in_front = True
    controller.show_name = False
    controller.hide_render = True
    _collection_for(context, target).objects.link(controller)
    move_object_to_control_collection(controller, getattr(context, "scene", None))
    controller.parent = target
    controller.matrix_parent_inverse = Matrix.Identity(4)
    _set_controller_style(controller, "BEND")
    set_helper_object_visible(controller, False)
    return controller


CONTROLLER_STATE_PROPERTIES = (
    "deform_type", "strength", "factor", "direction", "size", "mode",
    "origin", "alignment", "preserve_volume", "show_cage",
    "show_axis_gizmo", "show_direction_handle", "show_numeric_controls",
    "top_scale", "bottom_scale", "top_offset", "bottom_offset",
    "show_end_handles", "show_boundary_handles", "show_end_shape_settings",
    "limit_boundaries_to_object",
)


def _copy_controller_state(destination_controller, source_controller):
    destination = destination_controller.sdh_cage_deform
    source = source_controller.sdh_cage_deform
    pointer = _pointer(destination_controller)
    _SYNCING.add(pointer)
    try:
        for name in CONTROLLER_STATE_PROPERTIES:
            value = getattr(source, name)
            if hasattr(value, "__len__") and not isinstance(value, str):
                value = tuple(value)
            setattr(destination, name, value)
        destination_controller.location = source_controller.location
        destination_controller.rotation_euler = source_controller.rotation_euler
        destination_controller.scale = source_controller.scale
    finally:
        _SYNCING.discard(pointer)
    sync_controller(destination_controller, pull_transform=False)


def _restore_controller_from_modifier(controller, modifier):
    properties = controller.sdh_cage_deform
    deform_types = {value: key for key, value in DEFORM_VALUES.items()}
    modes = {value: key for key, value in MODE_VALUES.items()}
    origins = {value: key for key, value in ORIGIN_VALUES.items()}
    pointer = _pointer(controller)
    _SYNCING.add(pointer)
    try:
        controller.location = tuple(modifier_input(modifier, "Center", (0.0, 0.0, 0.0)))
        controller.rotation_euler = tuple(
            modifier_input(modifier, "Rotation", (0.0, 0.0, 0.0)))
        properties.size = tuple(modifier_input(modifier, "Size", (1.0, 1.0, 1.0)))
        controller.scale = tuple(max(value, EPSILON) * 0.5 for value in properties.size)
        properties.strength = float(modifier_input(modifier, "Strength", 0.0))
        properties.factor = float(modifier_input(modifier, "Factor", 0.0))
        properties.direction = float(modifier_input(modifier, "Direction", 0.0))
        properties.deform_type = deform_types.get(
            int(modifier_input(modifier, "Deform Type", 0)), "BEND")
        properties.mode = modes.get(int(modifier_input(modifier, "Mode", 0)), "LIMITED")
        properties.origin = origins.get(int(modifier_input(modifier, "Origin", 0)), "BOTTOM")
        properties.preserve_volume = bool(
            modifier_input(modifier, "Preserve Volume", True))
        top_scale = tuple(modifier_input(modifier, "Top Scale", (1.0, 1.0, 1.0)))
        bottom_scale = tuple(modifier_input(
            modifier, "Bottom Scale", (1.0, 1.0, 1.0)))
        top_offset = tuple(modifier_input(modifier, "Top Offset", (0.0, 0.0, 0.0)))
        bottom_offset = tuple(modifier_input(
            modifier, "Bottom Offset", (0.0, 0.0, 0.0)))
        properties.top_scale = (top_scale[0], top_scale[2])
        properties.bottom_scale = (bottom_scale[0], bottom_scale[2])
        properties.top_offset = (top_offset[0], top_offset[2])
        properties.bottom_offset = (bottom_offset[0], bottom_offset[2])
    finally:
        _SYNCING.discard(pointer)
    sync_controller(controller, pull_transform=False)


def ensure_target_stage_ownership(context, target):
    """Detach copied cage stages from their source object's UUID ownership."""
    if target is None or is_cage_controller(target):
        return False
    target_uuid = str(target.get(TARGET_UUID, ""))
    conflicts = tuple(
        obj for obj in bpy.data.objects
        if obj != target and not is_cage_controller(obj) and
        target_uuid and str(obj.get(TARGET_UUID, "")) == target_uuid
    )
    if not conflicts:
        return False

    stages = cage_modifiers(target)
    owned_controllers = tuple(
        next((
            obj for obj in bpy.data.objects
            if is_cage_controller(obj) and obj.parent == target and
            str(obj.get(TARGET_UUID, "")) == target_uuid and
            str(obj.get(MODIFIER_UUID, "")) == cage_modifier_uuid(modifier)
        ), None)
        for modifier in stages
    )
    # The target that already owns the correctly parented controllers is the
    # source of a normal object duplicate. Preserve it; the controller-less
    # copy will detach itself when it first becomes active.
    if stages and all(owned_controllers):
        return False

    source_controllers = tuple(find_controller(target, modifier) for modifier in stages)
    target[TARGET_UUID] = str(uuid.uuid4())
    for modifier, source_controller in zip(stages, source_controllers):
        old_group = modifier.node_group
        new_group = old_group.copy()
        new_group.name = f"SDH Cage Deform {str(uuid.uuid4())[:8]}"
        new_group[MODIFIER_MARKER] = True
        new_group[MODIFIER_UUID] = str(uuid.uuid4())
        modifier.node_group = new_group

        if source_controller is not None and source_controller.parent == target:
            new_controller = source_controller
            new_controller[TARGET_UUID] = str(target[TARGET_UUID])
            new_controller[MODIFIER_UUID] = cage_modifier_uuid(modifier)
        else:
            new_controller = _new_controller(context, target, modifier)
        if source_controller is not None:
            _copy_controller_state(new_controller, source_controller)
        else:
            _restore_controller_from_modifier(new_controller, modifier)
    return True


def remove_orphan_cage_controllers(target):
    """Remove owned controllers whose managed modifier was deleted directly."""
    if target is None:
        return 0
    live_modifier_uuids = {
        cage_modifier_uuid(modifier) for modifier in cage_modifiers(target)
    }
    orphans = tuple(
        obj for obj in bpy.data.objects
        if is_cage_controller(obj) and obj.parent == target and
        str(obj.get(MODIFIER_UUID, "")) not in live_modifier_uuids
    )
    for controller in orphans:
        bpy.data.objects.remove(controller, do_unlink=True)
    for node_group in tuple(bpy.data.node_groups):
        if node_group.users == 0 and node_group.get(MODIFIER_MARKER, False):
            bpy.data.node_groups.remove(node_group)
    if orphans:
        remove_unused_control_collections()
    return len(orphans)


def create_deform_stage(context, target, *, name="Cage Deform", after_modifier=None):
    ensure_target_stage_ownership(context, target)
    ensure_unique_target_uuid(target)
    remove_orphan_cage_controllers(target)
    node_group = create_stage_node_group()
    modifier = target.modifiers.new(name=name, type="NODES")
    modifier.node_group = node_group
    controller = _new_controller(context, target, modifier)

    previous_active = target.modifiers.active
    target.modifiers.active = modifier
    if after_modifier is not None and after_modifier in target.modifiers[:]:
        desired_index = tuple(target.modifiers).index(after_modifier) + 1
        _activate(context, target)
        try:
            bpy.ops.object.modifier_move_to_index(modifier=modifier.name, index=desired_index)
        except RuntimeError:
            pass
    fit_controller(context, target, modifier, controller)
    target.modifiers.active = modifier
    return modifier, controller, previous_active


class SDH_OT_add_cage_deform(Operator):
    bl_idname = "sdh.add_cage_deform"
    bl_label = "Add Cage Deform"
    bl_description = "Add an independent cage deformation stage"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        target = target_from_context(context)
        return bool(target and target.type in SUPPORTED_TYPES)

    def execute(self, context):
        target = target_from_context(context)
        active = target.modifiers.active
        modifier, _controller, _previous = create_deform_stage(
            context, target, after_modifier=active)
        target.modifiers.active = modifier
        _activate(context, target)
        self.report({"INFO"}, "Added Cage Deform stage")
        return {"FINISHED"}


class SDH_OT_fit_cage_deform(Operator):
    bl_idname = "sdh.fit_cage_deform"
    bl_label = "Fit to Object"
    bl_description = "Fit the cage to geometry entering this deformation stage"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        target, modifier, controller = resolve_context_deform(context)
        return bool(target and modifier and controller)

    def execute(self, context):
        target, modifier, controller = resolve_context_deform(context)
        fit_controller(context, target, modifier, controller)
        self.report({"INFO"}, "Deformation cage fitted to stage input")
        return {"FINISHED"}


class SDH_OT_reset_cage_ends(Operator):
    bl_idname = "sdh.reset_cage_ends"
    bl_label = "Reset Independent Ends"
    bl_description = "Restore both cage ends to the fitted cross-section"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(resolve_context_deform(context)[2])

    def execute(self, context):
        controller = resolve_context_deform(context)[2]
        properties = controller.sdh_cage_deform
        properties.top_scale = (1.0, 1.0)
        properties.bottom_scale = (1.0, 1.0)
        properties.top_offset = (0.0, 0.0)
        properties.bottom_offset = (0.0, 0.0)
        return {"FINISHED"}


class SDH_OT_select_cage_stage(Operator):
    bl_idname = "sdh.select_cage_stage"
    bl_label = "Select Cage Stage"
    bl_options = {"INTERNAL"}

    index: bpy.props.IntProperty(default=0, min=0)

    def execute(self, context):
        previous_controller = context.object if is_cage_controller(context.object) else None
        target = target_from_context(context)
        if target is None and is_cage_controller(context.object):
            target = find_target(context.object)
        modifiers = cage_modifiers(target)
        if self.index >= len(modifiers):
            return {"CANCELLED"}
        target.modifiers.active = modifiers[self.index]
        _activate(context, target)
        if previous_controller is not None:
            previous_controller.show_name = False
            set_helper_object_visible(previous_controller, False)
        return {"FINISHED"}


class SDH_OT_select_cage_controller(Operator):
    bl_idname = "sdh.select_cage_controller"
    bl_label = "Select Cage Controller"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return bool(resolve_context_deform(context)[2])

    def execute(self, context):
        controller = resolve_context_deform(context)[2]
        set_helper_object_visible(controller, True, context.view_layer)
        controller.show_name = True
        _activate(context, controller)
        return {"FINISHED"}


class SDH_OT_select_cage_target(Operator):
    bl_idname = "sdh.select_cage_target"
    bl_label = "Return to Object"
    bl_description = "Select the object controlled by this deformation cage"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return bool(resolve_context_deform(context)[0])

    def execute(self, context):
        target, _modifier, controller = resolve_context_deform(context)
        _activate(context, target)
        if controller is not None:
            controller.show_name = False
            set_helper_object_visible(controller, False)
        return {"FINISHED"}


class SDH_OT_cage_transform(Operator):
    bl_idname = "sdh.cage_transform"
    bl_label = "Edit Cage"
    bl_description = "Select the cage controller and activate a transform tool"
    bl_options = {"INTERNAL"}

    tool: EnumProperty(
        items=(
            ("MOVE", "Move", "Move the deformation cage"),
            ("ROTATE", "Rotate", "Rotate and aim the deformation cage"),
            ("SCALE", "Scale", "Resize the deformation cage"),
        ),
        default="MOVE",
    )

    @classmethod
    def poll(cls, context):
        return bool(resolve_context_deform(context)[2])

    def execute(self, context):
        controller = resolve_context_deform(context)[2]
        set_helper_object_visible(controller, True, context.view_layer)
        controller.show_name = True
        _activate(context, controller)
        if getattr(context, "area", None) and context.area.type == "VIEW_3D":
            tool_id = {
                "MOVE": "builtin.move",
                "ROTATE": "builtin.rotate",
                "SCALE": "builtin.scale",
            }[self.tool]
            try:
                bpy.ops.wm.tool_set_by_id(name=tool_id)
            except RuntimeError:
                pass
        return {"FINISHED"}


class SDH_OT_set_cage_axis(Operator):
    bl_idname = "sdh.set_cage_axis"
    bl_label = "Set Deform Axis"
    bl_description = "Align the cage axis and fit it to the current stage input"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    alignment: EnumProperty(
        items=tuple((identifier, identifier, "") for identifier in (
            "AUTO", "POS_X", "NEG_X", "POS_Y", "NEG_Y", "POS_Z", "NEG_Z")),
        default="AUTO",
    )

    @classmethod
    def poll(cls, context):
        return bool(resolve_context_deform(context)[2])

    def execute(self, context):
        target, modifier, controller = resolve_context_deform(context)
        controller.sdh_cage_deform.alignment = self.alignment
        fit_controller(context, target, modifier, controller)
        return {"FINISHED"}


class SDH_OT_set_bend_trend(Operator):
    bl_idname = "sdh.set_bend_trend"
    bl_label = "Set Bend Trend"
    bl_description = (
        "Choose a signed cage axis and one of its two perpendicular bend trends; "
        "hold Ctrl to keep all choices visible"
    )
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    alignment: EnumProperty(
        items=tuple((identifier, identifier, "") for identifier in (
            "POS_X", "NEG_X", "POS_Y", "NEG_Y", "POS_Z", "NEG_Z")),
        default="POS_Y",
    )
    direction: FloatProperty(default=0.0, subtype="ANGLE")
    keep_open: BoolProperty(default=False, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        controller = resolve_context_deform(context)[2]
        return bool(
            controller and controller.sdh_cage_deform.deform_type == "BEND")

    def invoke(self, context, event):
        self.keep_open = bool(event.ctrl)
        return self.execute(context)

    def execute(self, context):
        target, modifier, controller = resolve_context_deform(context)
        if target is None or modifier is None or controller is None:
            return {"CANCELLED"}
        properties = controller.sdh_cage_deform
        properties.direction = self.direction
        properties.alignment = self.alignment
        fit_controller(context, target, modifier, controller)
        if not self.keep_open:
            properties.show_axis_gizmo = False
        if context.area:
            context.area.tag_redraw()
        return {"FINISHED"}


class SDH_OT_duplicate_cage_deform(Operator):
    bl_idname = "sdh.duplicate_cage_deform"
    bl_label = "Duplicate Cage Stage"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(resolve_context_deform(context)[1])

    def execute(self, context):
        target, source_modifier, source_controller = resolve_context_deform(context)
        modifier, controller, _previous = create_deform_stage(
            context, target, name=f"{source_modifier.name} Copy",
            after_modifier=source_modifier)
        source = source_controller.sdh_cage_deform
        destination = controller.sdh_cage_deform
        pointer = _pointer(controller)
        _SYNCING.add(pointer)
        try:
            destination.deform_type = source.deform_type
            destination.strength = source.strength
            destination.factor = source.factor
            destination.direction = source.direction
            destination.size = tuple(source.size)
            destination.mode = source.mode
            destination.origin = source.origin
            destination.alignment = source.alignment
            destination.preserve_volume = source.preserve_volume
            destination.show_cage = source.show_cage
            destination.show_axis_gizmo = source.show_axis_gizmo
            destination.show_direction_handle = source.show_direction_handle
            destination.show_numeric_controls = source.show_numeric_controls
            destination.top_scale = tuple(source.top_scale)
            destination.bottom_scale = tuple(source.bottom_scale)
            destination.top_offset = tuple(source.top_offset)
            destination.bottom_offset = tuple(source.bottom_offset)
            destination.show_end_handles = source.show_end_handles
            destination.show_boundary_handles = source.show_boundary_handles
            destination.show_end_shape_settings = source.show_end_shape_settings
            controller.location = source_controller.location
            controller.rotation_euler = source_controller.rotation_euler
            controller.scale = source_controller.scale
        finally:
            _SYNCING.discard(pointer)
        sync_controller(controller, pull_transform=False)
        target.modifiers.active = modifier
        _activate(context, target)
        return {"FINISHED"}


class SDH_OT_move_cage_deform(Operator):
    bl_idname = "sdh.move_cage_deform"
    bl_label = "Move Cage Stage"
    bl_description = "Move this deformation earlier or later in the modifier stack"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    index: bpy.props.IntProperty(default=0, min=0)
    direction: EnumProperty(
        items=(
            ("EARLIER", "Earlier", "Move before the previous Cage Deform"),
            ("LATER", "Later", "Move after the next Cage Deform"),
        ),
        default="EARLIER",
    )

    @classmethod
    def poll(cls, context):
        target = target_from_context(context)
        return bool(target and len(cage_modifiers(target)) > 1)

    def execute(self, context):
        target = target_from_context(context)
        stages = cage_modifiers(target)
        if not 0 <= self.index < len(stages):
            return {"CANCELLED"}
        destination = self.index + (-1 if self.direction == "EARLIER" else 1)
        if not 0 <= destination < len(stages):
            return {"CANCELLED"}

        modifier = stages[self.index]
        neighbor = stages[destination]
        desired_index = tuple(target.modifiers).index(neighbor)
        _activate(context, target)
        target.modifiers.active = modifier
        try:
            bpy.ops.object.modifier_move_to_index(
                modifier=modifier.name, index=desired_index)
        except RuntimeError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        target.modifiers.active = modifier
        return {"FINISHED"}


class SDH_OT_remove_cage_deform(Operator):
    bl_idname = "sdh.remove_cage_deform"
    bl_label = "Remove Cage Stage"
    bl_description = "Remove this managed deformation stage and its cage controller"
    bl_options = {"REGISTER", "UNDO"}

    index: bpy.props.IntProperty(default=-1, min=-1)

    @classmethod
    def poll(cls, context):
        target = target_from_context(context)
        return bool(target and cage_modifiers(target))

    def execute(self, context):
        target = target_from_context(context)
        stages = cage_modifiers(target)
        if self.index >= 0:
            if self.index >= len(stages):
                return {"CANCELLED"}
            modifier = stages[self.index]
            controller = find_controller(target, modifier)
        else:
            _target, modifier, controller = resolve_context_deform(context)
            if modifier not in stages:
                return {"CANCELLED"}
        _activate(context, target)
        node_group = modifier.node_group
        target.modifiers.remove(modifier)
        if controller and is_cage_controller(controller):
            bpy.data.objects.remove(controller, do_unlink=True)
        if node_group and node_group.users == 0 and node_group.get(MODIFIER_MARKER, False):
            bpy.data.node_groups.remove(node_group)
        remaining = cage_modifiers(target)
        if remaining:
            target.modifiers.active = remaining[min(max(self.index, 0), len(remaining) - 1)]
        remove_unused_control_collections()
        return {"FINISHED"}


class SDH_OT_remove_cage_stack(Operator):
    bl_idname = "sdh.remove_cage_stack"
    bl_label = "Remove Cage Stack"
    bl_description = "Remove every managed cage stage and its owned controllers"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        target = target_from_context(context)
        return bool(target and cage_modifiers(target))

    def execute(self, context):
        target = target_from_context(context)
        stages = cage_modifiers(target)
        if target is None or not stages:
            return {"CANCELLED"}
        _activate(context, target)
        modifier_uuids = {cage_modifier_uuid(modifier) for modifier in stages}
        node_groups = tuple(dict.fromkeys(modifier.node_group for modifier in stages))
        controllers = tuple(
            obj for obj in bpy.data.objects
            if is_cage_controller(obj) and getattr(obj, "parent", None) == target and
            str(obj.get(MODIFIER_UUID, "")) in modifier_uuids
        )
        for modifier in stages:
            target.modifiers.remove(modifier)
        for controller in controllers:
            bpy.data.objects.remove(controller, do_unlink=True)
        for node_group in node_groups:
            if (
                    node_group and node_group.users == 0 and
                    node_group.get(MODIFIER_MARKER, False)
            ):
                bpy.data.node_groups.remove(node_group)
        remove_unused_control_collections()
        return {"FINISHED"}


def cage_local_matrix(target, controller):
    return (
        target.matrix_world @
        Matrix.Translation(controller.location) @
        controller.rotation_euler.to_matrix().to_4x4()
    )


def deform_handle_world(target, controller):
    properties = controller.sdh_cage_deform
    half = Vector(properties.size) * 0.5
    handle_y = -half.y if properties.origin == "TOP" else half.y
    handle_x = {
        "TAPER": half.x * 0.55,
    }.get(properties.deform_type, 0.0)
    point = deform_point_local(
        (handle_x, handle_y, 0.0), properties.size,
        properties.deform_type, properties.strength, properties.factor,
        properties.direction, properties.mode, properties.origin,
        properties.preserve_volume,
        properties.top_scale, properties.bottom_scale,
        properties.top_offset, properties.bottom_offset,
    )
    return cage_local_matrix(target, controller) @ point


def end_shape_handle_world(target, controller, side):
    properties = controller.sdh_cage_deform
    half = Vector(properties.size) * 0.5
    point = deform_point_local(
        (half.x, half.y if side == "TOP" else -half.y, 0.0),
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
    )
    return cage_local_matrix(target, controller) @ point


def cage_boundary_points_local(properties, side):
    """Return the deformed boundary center and an outward handle position."""
    half = Vector(properties.size) * 0.5
    boundary_y = half.y if side == "TOP" else -half.y
    inner_step = max(properties.size[1] * 0.04, EPSILON)
    inner_y = boundary_y - inner_step if side == "TOP" else boundary_y + inner_step

    def deform_center(y):
        return deform_point_local(
            (0.0, y, 0.0),
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
        )

    boundary = deform_center(boundary_y)
    inner = deform_center(inner_y)
    outward = boundary - inner
    if outward.length < EPSILON:
        outward = Vector((0.0, 1.0 if side == "TOP" else -1.0, 0.0))
    else:
        outward.normalize()
    handle_offset = max(
        min(properties.size[0], properties.size[2]) * 0.22,
        properties.size[1] * 0.025,
        0.08,
    )
    return boundary, boundary + outward * handle_offset


def cage_boundary_handle_world(target, controller, side):
    _boundary, handle = cage_boundary_points_local(
        controller.sdh_cage_deform, side)
    return cage_local_matrix(target, controller) @ handle


def cage_input_axis_limits(context, target, modifier, controller):
    """Return the input geometry bounds projected onto the cage length axis."""
    bounds = _modifier_input_bounds(context, target, modifier)
    axis = controller.rotation_euler.to_matrix() @ Vector((0.0, 1.0, 0.0))
    if axis.length < EPSILON:
        return None
    axis.normalize()
    positions = tuple(point.dot(axis) for point in _bounds_corners(bounds))
    if not positions or not all(math.isfinite(value) for value in positions):
        return None
    return min(positions), max(positions)


def move_cage_boundary(controller, side, axis_delta,
                       initial_size=None, initial_location=None,
                       axis_limits=None):
    """Move one longitudinal cage boundary while keeping the other fixed."""
    if side not in {"TOP", "BOTTOM"}:
        raise ValueError(f"Unsupported cage boundary: {side!r}")
    properties = controller.sdh_cage_deform
    initial_size = Vector(
        properties.size if initial_size is None else initial_size)
    initial_location = Vector(
        controller.location if initial_location is None else initial_location)
    axis_delta = float(axis_delta)

    axis = controller.rotation_euler.to_matrix() @ Vector((0.0, 1.0, 0.0))
    if axis.length < EPSILON:
        axis = Vector((0.0, 1.0, 0.0))
    else:
        axis.normalize()
    center_axis = initial_location.dot(axis)
    initial_top = center_axis + initial_size.y * 0.5
    initial_bottom = center_axis - initial_size.y * 0.5

    if side == "TOP":
        desired = max(initial_top + axis_delta, initial_bottom + EPSILON)
        if axis_limits is not None:
            desired = min(desired, float(axis_limits[1]))
            desired = max(desired, initial_bottom + EPSILON)
        applied_axis_delta = desired - initial_top
        new_length = max(desired - initial_bottom, EPSILON)
    else:
        desired = min(initial_bottom + axis_delta, initial_top - EPSILON)
        if axis_limits is not None:
            desired = max(desired, float(axis_limits[0]))
            desired = min(desired, initial_top - EPSILON)
        applied_axis_delta = desired - initial_bottom
        new_length = max(initial_top - desired, EPSILON)

    center_shift = controller.rotation_euler.to_matrix() @ Vector(
        (0.0, applied_axis_delta * 0.5, 0.0))
    pointer = _pointer(controller)
    _SYNCING.add(pointer)
    try:
        properties.size = (initial_size.x, new_length, initial_size.z)
        controller.scale = (
            initial_size.x * 0.5,
            new_length * 0.5,
            initial_size.z * 0.5,
        )
        controller.location = initial_location + center_shift
    finally:
        _SYNCING.discard(pointer)
    sync_controller(controller, pull_transform=False)
    return applied_axis_delta, new_length


def _ring_triangles(start_angle=0.0, end_angle=math.tau, segments=28,
                    inner=0.62, outer=1.0):
    vertices = []
    for index in range(segments):
        angle_a = start_angle + (end_angle - start_angle) * index / segments
        angle_b = start_angle + (end_angle - start_angle) * (index + 1) / segments
        inner_a = (math.cos(angle_a) * inner, math.sin(angle_a) * inner, 0.0)
        outer_a = (math.cos(angle_a) * outer, math.sin(angle_a) * outer, 0.0)
        inner_b = (math.cos(angle_b) * inner, math.sin(angle_b) * inner, 0.0)
        outer_b = (math.cos(angle_b) * outer, math.sin(angle_b) * outer, 0.0)
        vertices.extend((inner_a, outer_a, outer_b, inner_a, outer_b, inner_b))
    return vertices


def _arc_arrow_triangles(start_angle, end_angle, segments=22):
    vertices = _ring_triangles(start_angle, end_angle, segments, 0.64, 0.88)
    direction = Vector((math.cos(end_angle), math.sin(end_angle)))
    tangent = Vector((-direction.y, direction.x))
    center = direction * 0.76
    tip = center + tangent * 0.52
    wing = direction * 0.34
    vertices.extend((
        (tip.x, tip.y, 0.0),
        (center.x + wing.x, center.y + wing.y, 0.0),
        (center.x - wing.x, center.y - wing.y, 0.0),
    ))
    return vertices


def _shape_vertices(name):
    if name == "BEND":
        return _arc_arrow_triangles(-math.pi * 0.8, math.pi * 0.28, 18)
    if name == "TWIST":
        return _arc_arrow_triangles(-math.pi * 1.15, math.pi * 0.55, 30)
    if name == "TAPER":
        return (
            (-0.95, 0.8, 0.0), (0.95, 0.8, 0.0), (0.28, 0.08, 0.0),
            (-0.95, -0.8, 0.0), (0.95, -0.8, 0.0), (-0.28, -0.08, 0.0),
            (-0.28, -0.08, 0.0), (0.28, 0.08, 0.0), (-0.95, 0.8, 0.0),
            (0.28, 0.08, 0.0), (-0.28, -0.08, 0.0), (0.95, -0.8, 0.0),
        )
    if name == "STRETCH":
        return (
            (-0.18, -0.52, 0.0), (0.18, -0.52, 0.0), (0.18, 0.52, 0.0),
            (-0.18, -0.52, 0.0), (0.18, 0.52, 0.0), (-0.18, 0.52, 0.0),
            (-0.72, 0.42, 0.0), (0.72, 0.42, 0.0), (0.0, 1.0, 0.0),
            (-0.72, -0.42, 0.0), (0.0, -1.0, 0.0), (0.72, -0.42, 0.0),
        )
    if name == "AXIS_POSITIVE":
        return (
            (0.0, 1.0, 0.0), (0.9, 0.0, 0.0), (0.0, -1.0, 0.0),
            (0.0, 1.0, 0.0), (0.0, -1.0, 0.0), (-0.9, 0.0, 0.0),
        )
    if name == "AXIS_NEGATIVE":
        return _ring_triangles(0.0, math.tau, 20, 0.48, 0.92)
    if name == "DIRECTION":
        return _arc_arrow_triangles(-math.pi * 0.95, math.pi * 0.82, 30)
    if name == "BEND_TREND":
        return _arc_arrow_triangles(-math.pi * 0.72, math.pi * 0.12, 18)
    raise ValueError(f"Unsupported gizmo shape: {name}")


def _billboard_matrix(context, world_location):
    region_data = getattr(context, "region_data", None)
    if region_data is None:
        region_data = getattr(getattr(context, "space_data", None), "region_3d", None)
    if region_data is None:
        return Matrix.Translation(world_location)
    rotation = region_data.view_matrix.inverted_safe().to_3x3().to_4x4()
    return Matrix.Translation(world_location) @ rotation


def _project_world(context, world_location):
    try:
        from bpy_extras import view3d_utils
        return view3d_utils.location_3d_to_region_2d(
            context.region, context.space_data.region_3d, world_location)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


def _wrapped_angle_delta(previous, current):
    return (current - previous + math.pi) % math.tau - math.pi


def _mouse_angle(center, event):
    if center is None:
        return None
    offset = Vector((event.mouse_region_x - center.x, event.mouse_region_y - center.y))
    if offset.length < 3.0:
        return None
    return math.atan2(offset.y, offset.x)


TYPE_HANDLE_COLORS = {
    "BEND": ((1.0, 0.34, 0.03), (1.0, 0.86, 0.2)),
    "TWIST": ((0.72, 0.22, 1.0), (0.94, 0.72, 1.0)),
    "TAPER": ((1.0, 0.62, 0.05), (1.0, 0.9, 0.35)),
    "STRETCH": ((0.12, 0.88, 0.4), (0.66, 1.0, 0.76)),
}


class SDHCageStrengthGizmo(Gizmo):
    bl_idname = "SDH_GT_cage_deform_strength"
    bl_target_properties = ()

    __slots__ = (
        "custom_shapes",
        "initial_strength",
        "initial_factor",
        "initial_direction",
        "initial_mouse_x",
        "twist_center",
        "twist_last_angle",
        "twist_delta",
    )

    def setup(self):
        self.custom_shapes = {
            name: self.new_custom_shape("TRIS", _shape_vertices(name))
            for name in ("BEND", "TWIST", "TAPER", "STRETCH")
        }
        self.use_draw_modal = True
        self.use_draw_value = False

    def _update_matrix(self, context):
        target, _modifier, controller = resolve_context_deform(
            context, fallback=False)
        if target is None or controller is None:
            return False
        properties = controller.sdh_cage_deform
        self.matrix_basis = _billboard_matrix(
            context, deform_handle_world(target, controller))
        if properties.deform_type == "TWIST":
            # A twist is read most clearly as a rotation around the complete
            # cross-section. Scale the ring with the cage instead of leaving a
            # tiny, fixed-size icon at the end of large objects.
            cross_section = max(properties.size[0], properties.size[2])
            self.scale_basis = max(cross_section * 0.88, 0.55)
        else:
            self.scale_basis = 0.19
        self.color, self.color_highlight = TYPE_HANDLE_COLORS[properties.deform_type]
        return True

    def draw(self, context):
        if self._update_matrix(context):
            controller = resolve_context_deform(context, fallback=False)[2]
            self.draw_custom_shape(
                self.custom_shapes[controller.sdh_cage_deform.deform_type])

    def draw_select(self, context, select_id):
        if self._update_matrix(context):
            controller = resolve_context_deform(context, fallback=False)[2]
            self.draw_custom_shape(
                self.custom_shapes[controller.sdh_cage_deform.deform_type],
                select_id=select_id)

    def invoke(self, context, event):
        _target, _modifier, controller = resolve_context_deform(
            context, fallback=False)
        properties = controller.sdh_cage_deform
        self.initial_strength = properties.strength
        self.initial_factor = properties.factor
        self.initial_direction = properties.direction
        self.initial_mouse_x = event.mouse_region_x
        self.twist_center = None
        self.twist_last_angle = None
        self.twist_delta = 0.0
        if properties.deform_type == "TWIST":
            target = find_target(controller)
            self.twist_center = _project_world(
                context, deform_handle_world(target, controller))
            self.twist_last_angle = _mouse_angle(self.twist_center, event)
        return {"RUNNING_MODAL"}

    def modal(self, context, event, _tweak):
        _target, _modifier, controller = resolve_context_deform(
            context, fallback=False)
        if controller is None:
            return {"CANCELLED"}
        properties = controller.sdh_cage_deform
        if properties.deform_type == "TWIST" and self.twist_last_angle is not None:
            current_angle = _mouse_angle(self.twist_center, event)
            if current_angle is not None:
                self.twist_delta += _wrapped_angle_delta(
                    self.twist_last_angle, current_angle)
                self.twist_last_angle = current_angle
            delta = self.twist_delta * (0.1 if event.shift else 1.0)
        else:
            delta = (event.mouse_region_x - self.initial_mouse_x) * 0.01
            if event.shift:
                delta *= 0.1
        if event.alt and properties.deform_type == "BEND":
            if event.ctrl:
                step = math.radians(5.0)
                delta = round(delta / step) * step
            properties.direction = self.initial_direction + delta
            label = f"Direction: {math.degrees(properties.direction):.1f}°"
        elif properties.deform_type in {"BEND", "TWIST"}:
            if event.ctrl:
                step = math.radians(5.0)
                delta = round(delta / step) * step
            properties.strength = self.initial_strength + delta
            label = f"Angle: {math.degrees(properties.strength):.1f}°"
        else:
            if event.ctrl:
                delta = round(delta * 10.0) / 10.0
            properties.factor = self.initial_factor + delta
            label = f"Factor: {properties.factor:.3f}"
        if context.area:
            shortcut = (
                "Drag Around Ring • Shift Precise • Ctrl Snap"
                if properties.deform_type == "TWIST"
                else "Shift Precise • Ctrl Snap"
            )
            context.area.header_text_set(
                label + "   |   " + bpy.app.translations.pgettext_iface(shortcut))
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def exit(self, context, cancel):
        _target, _modifier, controller = resolve_context_deform(
            context, fallback=False)
        if cancel and controller:
            properties = controller.sdh_cage_deform
            properties.strength = self.initial_strength
            properties.factor = self.initial_factor
            properties.direction = self.initial_direction
        if context.area:
            context.area.header_text_set(None)
            context.area.tag_redraw()


def bend_direction_handle_world(target, controller):
    properties = controller.sdh_cage_deform
    half = Vector(properties.size) * 0.5
    point = Vector((half.x * 1.25, -half.y * 0.32, 0.0))
    return cage_local_matrix(target, controller) @ point


class SDHCageDirectionGizmo(Gizmo):
    bl_idname = "SDH_GT_cage_bend_direction"
    bl_label = "Bend Direction"
    bl_target_properties = ()

    __slots__ = (
        "custom_shape",
        "initial_direction",
        "initial_mouse_x",
        "center",
        "last_angle",
        "angle_delta",
    )

    def setup(self):
        self.custom_shape = self.new_custom_shape(
            "TRIS", _shape_vertices("DIRECTION"))
        self.use_draw_modal = True
        self.use_draw_value = False

    def _update_matrix(self, context):
        target, _modifier, controller = resolve_context_deform(
            context, fallback=False)
        if target is None or controller is None:
            return False
        properties = controller.sdh_cage_deform
        if properties.deform_type != "BEND" or not properties.show_direction_handle:
            return False
        self.matrix_basis = _billboard_matrix(
            context, bend_direction_handle_world(target, controller))
        self.scale_basis = 0.16
        return True

    def draw(self, context):
        if self._update_matrix(context):
            self.draw_custom_shape(self.custom_shape)

    def draw_select(self, context, select_id):
        if self._update_matrix(context):
            self.draw_custom_shape(self.custom_shape, select_id=select_id)

    def invoke(self, context, event):
        target, _modifier, controller = resolve_context_deform(
            context, fallback=False)
        if target is None or controller is None:
            return {"CANCELLED"}
        self.initial_direction = controller.sdh_cage_deform.direction
        self.initial_mouse_x = event.mouse_region_x
        self.center = _project_world(
            context, bend_direction_handle_world(target, controller))
        self.last_angle = _mouse_angle(self.center, event)
        self.angle_delta = 0.0
        return {"RUNNING_MODAL"}

    def modal(self, context, event, _tweak):
        _target, _modifier, controller = resolve_context_deform(
            context, fallback=False)
        if controller is None:
            return {"CANCELLED"}
        current_angle = _mouse_angle(self.center, event)
        if current_angle is not None and self.last_angle is not None:
            self.angle_delta += _wrapped_angle_delta(self.last_angle, current_angle)
            self.last_angle = current_angle
            delta = self.angle_delta
        else:
            delta = (event.mouse_region_x - self.initial_mouse_x) * 0.01
        if event.shift:
            delta *= 0.1
        if event.ctrl:
            step = math.radians(5.0)
            delta = round(delta / step) * step
        properties = controller.sdh_cage_deform
        properties.direction = self.initial_direction + delta
        if context.area:
            label = bpy.app.translations.pgettext_iface("Bend Direction")
            shortcuts = bpy.app.translations.pgettext_iface(
                "Drag Around Ring • Shift Precise • Ctrl Snap")
            context.area.header_text_set(
                f"{label}: {math.degrees(properties.direction):.1f}°   |   "
                f"{shortcuts}")
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def exit(self, context, cancel):
        controller = resolve_context_deform(context, fallback=False)[2]
        if cancel and controller:
            controller.sdh_cage_deform.direction = self.initial_direction
        if context.area:
            context.area.header_text_set(None)
            context.area.tag_redraw()


BEND_TREND_BASES = {
    # normal, horizontal face axis, vertical face axis. Each basis is
    # right-handed, so the arrow direction remains predictable on opposite
    # faces instead of appearing mirrored at random.
    "POS_X": (Vector((1.0, 0.0, 0.0)), Vector((0.0, 1.0, 0.0)), Vector((0.0, 0.0, 1.0))),
    "NEG_X": (Vector((-1.0, 0.0, 0.0)), Vector((0.0, 1.0, 0.0)), Vector((0.0, 0.0, -1.0))),
    "POS_Y": (Vector((0.0, 1.0, 0.0)), Vector((0.0, 0.0, 1.0)), Vector((1.0, 0.0, 0.0))),
    "NEG_Y": (Vector((0.0, -1.0, 0.0)), Vector((0.0, 0.0, 1.0)), Vector((-1.0, 0.0, 0.0))),
    "POS_Z": (Vector((0.0, 0.0, 1.0)), Vector((1.0, 0.0, 0.0)), Vector((0.0, 1.0, 0.0))),
    "NEG_Z": (Vector((0.0, 0.0, -1.0)), Vector((1.0, 0.0, 0.0)), Vector((0.0, -1.0, 0.0))),
}

BEND_TREND_COLORS = {
    0: ((0.95, 0.12, 0.1), (1.0, 0.72, 0.65)),
    1: ((0.12, 0.88, 0.22), (0.68, 1.0, 0.7)),
}


def _resolved_alignment(alignment, bounds):
    if alignment != "AUTO":
        return alignment
    extents = bounds[1] - bounds[0]
    return ("POS_X", "POS_Y", "POS_Z")[
        max(range(3), key=lambda index: extents[index])]


def bend_trend_handle_matrix(target, alignment, variant):
    bounds = _object_fallback_bounds(target)
    minimum, maximum = bounds
    center = (minimum + maximum) * 0.5
    extents = maximum - minimum
    normal, horizontal, vertical = BEND_TREND_BASES[alignment]
    normal_index = max(range(3), key=lambda index: abs(normal[index]))

    point = center.copy()
    point[normal_index] = (
        maximum[normal_index] if normal[normal_index] > 0.0
        else minimum[normal_index]
    )
    largest_extent = max(max(extents), EPSILON)
    point += normal * max(largest_extent * 0.035, 0.035)

    horizontal_index = max(
        range(3), key=lambda index: abs(horizontal[index]))
    vertical_index = max(
        range(3), key=lambda index: abs(vertical[index]))
    face_span = max(
        min(extents[horizontal_index], extents[vertical_index]), EPSILON)
    pair_separation = max(face_span * 0.18, largest_extent * 0.035, 0.07)
    point += horizontal * (-pair_separation if variant == 0 else pair_separation)

    if variant == 0:
        shape_x, shape_y = horizontal, vertical
    else:
        shape_x, shape_y = vertical, -horizontal
    local_rotation = Matrix((shape_x, shape_y, normal)).transposed()
    world_rotation = (
        target.matrix_world.to_quaternion().to_matrix() @ local_rotation)
    matrix = world_rotation.to_4x4()
    matrix.translation = target.matrix_world @ point

    world_horizontal = (
        (target.matrix_world.to_3x3() @ horizontal).length *
        extents[horizontal_index]
    )
    world_vertical = (
        (target.matrix_world.to_3x3() @ vertical).length *
        extents[vertical_index]
    )
    world_face_span = max(min(world_horizontal, world_vertical), EPSILON)
    world_largest = max(world_horizontal, world_vertical, EPSILON)
    scale = max(world_face_span * 0.145, world_largest * 0.035, 0.12)
    return matrix, scale, bounds


class SDHCageBendTrendGizmo(Gizmo):
    bl_idname = "SDH_GT_cage_bend_trend"
    bl_label = "Choose Bend Trend"
    bl_target_properties = ()

    __slots__ = ("custom_shape", "alignment", "variant")

    def setup(self):
        self.custom_shape = self.new_custom_shape(
            "TRIS", _shape_vertices("BEND_TREND"))
        self.use_draw_modal = True
        self.use_draw_value = False

    def _update_matrix(self, context):
        target, _modifier, controller = resolve_context_deform(
            context, fallback=False)
        if target is None or controller is None:
            return False
        properties = controller.sdh_cage_deform
        if properties.deform_type != "BEND" or not properties.show_axis_gizmo:
            return False

        alignment = getattr(self, "alignment", "POS_Y")
        variant = int(getattr(self, "variant", 0))
        self.matrix_basis, scale, bounds = bend_trend_handle_matrix(
            target, alignment, variant)
        active_alignment = _resolved_alignment(properties.alignment, bounds)
        target_direction = 0.0 if variant == 0 else math.pi * 0.5
        direction_delta = abs(
            (properties.direction - target_direction + math.pi * 0.5) %
            math.pi - math.pi * 0.5)
        active = active_alignment == alignment and direction_delta < math.radians(2.0)
        normal, highlight = BEND_TREND_COLORS[variant]
        self.color = highlight if active else normal
        self.color_highlight = highlight
        self.alpha = 1.0 if active else 0.72
        self.scale_basis = scale * (1.12 if active else 1.0)
        return True

    def draw(self, context):
        if self._update_matrix(context):
            self.draw_custom_shape(self.custom_shape)

    def draw_select(self, context, select_id):
        if self._update_matrix(context):
            self.draw_custom_shape(self.custom_shape, select_id=select_id)


AXIS_VECTORS = {
    "POS_X": Vector((1.0, 0.0, 0.0)),
    "NEG_X": Vector((-1.0, 0.0, 0.0)),
    "POS_Y": Vector((0.0, 1.0, 0.0)),
    "NEG_Y": Vector((0.0, -1.0, 0.0)),
    "POS_Z": Vector((0.0, 0.0, 1.0)),
    "NEG_Z": Vector((0.0, 0.0, -1.0)),
}

AXIS_COLORS = {
    "X": ((0.95, 0.12, 0.1), (1.0, 0.6, 0.55)),
    "Y": ((0.18, 0.78, 0.2), (0.62, 1.0, 0.6)),
    "Z": ((0.12, 0.42, 1.0), (0.58, 0.76, 1.0)),
}


def cage_axis_handle_world(target, controller, alignment, context=None):
    properties = controller.sdh_cage_deform
    radius = max(max(properties.size) * 0.45, 0.5)
    local_location = Vector(controller.location) + AXIS_VECTORS[alignment] * radius
    world_location = target.matrix_world @ local_location

    # Signed handles on an axis aimed at the camera would otherwise overlap in
    # orthographic views. Separate only that pair along the screen's X axis.
    if context is not None:
        center_world = target.matrix_world @ Vector(controller.location)
        center_2d = _project_world(context, center_world)
        handle_2d = _project_world(context, world_location)
        if center_2d is not None and handle_2d is not None:
            separation = max(
                0.0, 1.0 - (handle_2d - center_2d).length / 48.0)
            region_data = getattr(context, "region_data", None)
            if region_data is None:
                region_data = getattr(
                    getattr(context, "space_data", None), "region_3d", None)
            if region_data is not None and separation > 0.0:
                view_right = (
                    region_data.view_matrix.inverted_safe().to_3x3() @
                    Vector((1.0, 0.0, 0.0))
                ).normalized()
                sign = 1.0 if alignment.startswith("POS_") else -1.0
                world_location += view_right * radius * 0.32 * sign * separation
    return world_location


class SDHCageAxisGizmo(Gizmo):
    bl_idname = "SDH_GT_cage_axis_switch"
    bl_label = "Switch Cage Axis"
    bl_target_properties = ()

    __slots__ = ("positive_shape", "negative_shape", "axis")

    def setup(self):
        self.positive_shape = self.new_custom_shape(
            "TRIS", _shape_vertices("AXIS_POSITIVE"))
        self.negative_shape = self.new_custom_shape(
            "TRIS", _shape_vertices("AXIS_NEGATIVE"))
        self.use_draw_modal = True
        self.use_draw_value = False

    def _update_matrix(self, context):
        target, _modifier, controller = resolve_context_deform(
            context, fallback=False)
        if target is None or controller is None:
            return False
        properties = controller.sdh_cage_deform
        if not properties.show_axis_gizmo or properties.deform_type == "BEND":
            return False
        alignment = getattr(self, "axis", "POS_Y")
        self.matrix_basis = _billboard_matrix(
            context, cage_axis_handle_world(target, controller, alignment, context))
        active = properties.alignment == alignment
        self.scale_basis = 0.16 if active else 0.125
        normal, highlight = AXIS_COLORS[alignment[-1]]
        if alignment.startswith("NEG_"):
            normal = tuple(channel * 0.72 for channel in normal)
        self.color = highlight if active else normal
        self.color_highlight = highlight
        self.alpha = 1.0 if active else 0.82
        return True

    def _shape(self):
        return (
            self.positive_shape
            if getattr(self, "axis", "POS_Y").startswith("POS_")
            else self.negative_shape
        )

    def draw(self, context):
        if self._update_matrix(context):
            self.draw_custom_shape(self._shape())

    def draw_select(self, context, select_id):
        if self._update_matrix(context):
            self.draw_custom_shape(self._shape(), select_id=select_id)

class SDHCageEndShapeGizmo(Gizmo):
    bl_idname = "SDH_GT_cage_end_shape"
    bl_target_properties = ()

    __slots__ = (
        "custom_shape",
        "side",
        "initial_scale",
        "initial_offset",
        "initial_mouse_x",
    )

    def setup(self):
        from .src.shape import __shape__
        self.custom_shape = self.new_custom_shape(
            "TRIS", __shape__["Sphere_GizmoGroup_"])
        self.use_draw_modal = True
        self.use_draw_value = False

    def _update_matrix(self, context):
        target, _modifier, controller = resolve_context_deform(
            context, fallback=False)
        if (
                target is None or controller is None or
                not controller.sdh_cage_deform.show_end_handles
        ):
            return False
        side = getattr(self, "side", "TOP")
        self.matrix_basis = _billboard_matrix(
            context, end_shape_handle_world(target, controller, side))
        self.scale_basis = 0.14
        return True

    def draw(self, context):
        if self._update_matrix(context):
            self.draw_custom_shape(self.custom_shape)

    def draw_select(self, context, select_id):
        if self._update_matrix(context):
            self.draw_custom_shape(self.custom_shape, select_id=select_id)

    def invoke(self, context, event):
        _target, _modifier, controller = resolve_context_deform(
            context, fallback=False)
        if controller is None:
            return {"CANCELLED"}
        properties = controller.sdh_cage_deform
        prefix = "top" if getattr(self, "side", "TOP") == "TOP" else "bottom"
        self.initial_scale = tuple(getattr(properties, f"{prefix}_scale"))
        self.initial_offset = tuple(getattr(properties, f"{prefix}_offset"))
        self.initial_mouse_x = event.mouse_region_x
        return {"RUNNING_MODAL"}

    def modal(self, context, event, _tweak):
        _target, _modifier, controller = resolve_context_deform(
            context, fallback=False)
        if controller is None:
            return {"CANCELLED"}
        properties = controller.sdh_cage_deform
        side = getattr(self, "side", "TOP")
        prefix = "top" if side == "TOP" else "bottom"
        side_label = bpy.app.translations.pgettext_iface(side.title())
        mouse_delta = event.mouse_region_x - self.initial_mouse_x
        if event.shift:
            mouse_delta *= 0.1

        if event.alt:
            delta = mouse_delta * 0.005
            if event.ctrl:
                delta = round(delta * 10.0) / 10.0
            value = (self.initial_offset[0] + delta, self.initial_offset[1])
            setattr(properties, f"{prefix}_offset", value)
            offset_label = bpy.app.translations.pgettext_iface("Offset")
            label = f"{side_label} {offset_label} X: {value[0]:.3f}"
        else:
            delta = mouse_delta * 0.01
            if event.ctrl:
                delta = round(delta * 10.0) / 10.0
            value = (
                max(0.05, self.initial_scale[0] + delta),
                max(0.05, self.initial_scale[1] + delta),
            )
            setattr(properties, f"{prefix}_scale", value)
            scale_label = bpy.app.translations.pgettext_iface("Scale")
            label = f"{side_label} {scale_label}: {value[0]:.3f}, {value[1]:.3f}"

        if context.area:
            shortcuts = bpy.app.translations.pgettext_iface(
                "Alt Slide X • Shift Precise • Ctrl Snap")
            context.area.header_text_set(
                label + "   |   " + shortcuts)
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def exit(self, context, cancel):
        _target, _modifier, controller = resolve_context_deform(
            context, fallback=False)
        if cancel and controller:
            properties = controller.sdh_cage_deform
            prefix = "top" if getattr(self, "side", "TOP") == "TOP" else "bottom"
            setattr(properties, f"{prefix}_scale", self.initial_scale)
            setattr(properties, f"{prefix}_offset", self.initial_offset)
        if context.area:
            context.area.header_text_set(None)
            context.area.tag_redraw()


class SDHCageBoundaryGizmo(Gizmo):
    bl_idname = "SDH_GT_cage_boundary"
    bl_target_properties = ()

    __slots__ = (
        "custom_shape",
        "side",
        "initial_size",
        "initial_location",
        "initial_mouse",
        "axis_screen",
        "units_per_pixel",
        "boundary_limits",
    )

    def setup(self):
        from .src.shape import __shape__
        self.custom_shape = self.new_custom_shape(
            "TRIS", __shape__["Sphere_GizmoGroup_"])
        self.use_draw_modal = True
        self.use_draw_value = False

    def _update_matrix(self, context):
        target, _modifier, controller = resolve_context_deform(
            context, fallback=False)
        if (
                target is None or controller is None or
                not controller.sdh_cage_deform.show_boundary_handles
        ):
            return False
        side = getattr(self, "side", "TOP")
        self.matrix_basis = _billboard_matrix(
            context, cage_boundary_handle_world(target, controller, side))
        self.scale_basis = 0.17
        return True

    def draw(self, context):
        if self._update_matrix(context):
            self.draw_custom_shape(self.custom_shape)

    def draw_select(self, context, select_id):
        if self._update_matrix(context):
            self.draw_custom_shape(self.custom_shape, select_id=select_id)

    def invoke(self, context, event):
        target, modifier, controller = resolve_context_deform(
            context, fallback=False)
        if target is None or controller is None:
            return {"CANCELLED"}
        properties = controller.sdh_cage_deform
        side = getattr(self, "side", "TOP")
        self.initial_size = tuple(properties.size)
        self.initial_location = tuple(controller.location)
        self.initial_mouse = (event.mouse_region_x, event.mouse_region_y)
        self.axis_screen = (0.0, 1.0)
        self.units_per_pixel = max(properties.size[1] / 250.0, EPSILON)
        self.boundary_limits = None
        if properties.limit_boundaries_to_object:
            try:
                self.boundary_limits = cage_input_axis_limits(
                    context, target, modifier, controller)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                self.boundary_limits = None

        try:
            from bpy_extras import view3d_utils
            boundary, handle = cage_boundary_points_local(properties, side)
            matrix = cage_local_matrix(target, controller)
            boundary_2d = view3d_utils.location_3d_to_region_2d(
                context.region, context.space_data.region_3d, matrix @ boundary)
            handle_2d = view3d_utils.location_3d_to_region_2d(
                context.region, context.space_data.region_3d, matrix @ handle)
            if boundary_2d is not None and handle_2d is not None:
                projected = handle_2d - boundary_2d
                if side == "BOTTOM":
                    projected.negate()
                if projected.length > 2.0:
                    local_offset = (handle - boundary).length
                    self.axis_screen = tuple(projected.normalized())
                    self.units_per_pixel = max(
                        local_offset / projected.length, EPSILON)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        return {"RUNNING_MODAL"}

    def modal(self, context, event, _tweak):
        _target, _modifier, controller = resolve_context_deform(
            context, fallback=False)
        if controller is None:
            return {"CANCELLED"}
        mouse_delta = Vector((
            event.mouse_region_x - self.initial_mouse[0],
            event.mouse_region_y - self.initial_mouse[1],
        ))
        axis_delta = mouse_delta.dot(Vector(self.axis_screen)) * self.units_per_pixel
        if event.shift:
            axis_delta *= 0.1
        if event.ctrl:
            axis_delta = round(axis_delta * 10.0) / 10.0

        side = getattr(self, "side", "TOP")
        applied, new_length = move_cage_boundary(
            controller,
            side,
            axis_delta,
            self.initial_size,
            self.initial_location,
            self.boundary_limits,
        )
        if context.area:
            boundary_label = bpy.app.translations.pgettext_iface(
                f"{side.title()} Boundary")
            length_label = bpy.app.translations.pgettext_iface("Cage Length")
            shortcuts = bpy.app.translations.pgettext_iface(
                "Drag Along Cage • Shift Precise • Ctrl Snap")
            context.area.header_text_set(
                f"{boundary_label}: {applied:+.3f}   |   "
                f"{length_label}: {new_length:.3f}   |   {shortcuts}")
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def exit(self, context, cancel):
        _target, _modifier, controller = resolve_context_deform(
            context, fallback=False)
        if cancel and controller:
            move_cage_boundary(
                controller,
                getattr(self, "side", "TOP"),
                0.0,
                self.initial_size,
                self.initial_location,
                self.boundary_limits,
            )
        if context.area:
            context.area.header_text_set(None)
            context.area.tag_redraw()


class SDHCageDeformGizmoGroup(GizmoGroup):
    bl_idname = "SDH_GGT_cage_deform"
    bl_label = "Cage Deform Strength Handle"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        target, modifier, controller = resolve_context_deform(
            context, fallback=False)
        return bool(
            target and modifier and controller and
            modifier.show_viewport and controller.sdh_cage_deform.show_cage
        )

    def setup(self, _context):
        handle = self.gizmos.new(SDHCageStrengthGizmo.bl_idname)
        handle.color = TYPE_HANDLE_COLORS["BEND"][0]
        handle.alpha = 0.85
        handle.color_highlight = TYPE_HANDLE_COLORS["BEND"][1]
        handle.alpha_highlight = 1.0
        self.handle = handle

        direction = self.gizmos.new(SDHCageDirectionGizmo.bl_idname)
        direction.color = (0.88, 0.32, 1.0)
        direction.alpha = 0.9
        direction.color_highlight = (1.0, 0.78, 1.0)
        direction.alpha_highlight = 1.0
        self.direction_handle = direction

        bend_trend_handles = []
        for alignment in (
                "POS_X", "NEG_X", "POS_Y", "NEG_Y", "POS_Z", "NEG_Z"):
            for variant, bend_direction in (
                    (0, 0.0), (1, math.pi * 0.5)):
                trend_handle = self.gizmos.new(
                    SDHCageBendTrendGizmo.bl_idname)
                trend_handle.alignment = alignment
                trend_handle.variant = variant
                trend_handle.alpha_highlight = 1.0
                operator = trend_handle.target_set_operator(
                    SDH_OT_set_bend_trend.bl_idname)
                operator.alignment = alignment
                operator.direction = bend_direction
                bend_trend_handles.append(trend_handle)
        self.bend_trend_handles = bend_trend_handles

        axis_handles = []
        for alignment in (
                "POS_X", "NEG_X", "POS_Y", "NEG_Y", "POS_Z", "NEG_Z"):
            axis_handle = self.gizmos.new(SDHCageAxisGizmo.bl_idname)
            axis_handle.axis = alignment
            axis_handle.alpha_highlight = 1.0
            operator = axis_handle.target_set_operator(
                SDH_OT_set_cage_axis.bl_idname)
            operator.alignment = alignment
            axis_handles.append(axis_handle)
        self.axis_handles = axis_handles

        top = self.gizmos.new(SDHCageEndShapeGizmo.bl_idname)
        top.side = "TOP"
        top.color = (0.0, 0.85, 1.0)
        top.alpha = 0.9
        top.color_highlight = (0.65, 1.0, 1.0)
        top.alpha_highlight = 1.0
        self.top_handle = top

        bottom = self.gizmos.new(SDHCageEndShapeGizmo.bl_idname)
        bottom.side = "BOTTOM"
        bottom.color = (0.0, 1.0, 0.55)
        bottom.alpha = 0.9
        bottom.color_highlight = (0.65, 1.0, 0.8)
        bottom.alpha_highlight = 1.0
        self.bottom_handle = bottom

        top_boundary = self.gizmos.new(SDHCageBoundaryGizmo.bl_idname)
        top_boundary.side = "TOP"
        top_boundary.color = (1.0, 0.82, 0.05)
        top_boundary.alpha = 0.95
        top_boundary.color_highlight = (1.0, 1.0, 0.45)
        top_boundary.alpha_highlight = 1.0
        self.top_boundary_handle = top_boundary

        bottom_boundary = self.gizmos.new(SDHCageBoundaryGizmo.bl_idname)
        bottom_boundary.side = "BOTTOM"
        bottom_boundary.color = (1.0, 0.55, 0.02)
        bottom_boundary.alpha = 0.95
        bottom_boundary.color_highlight = (1.0, 0.9, 0.35)
        bottom_boundary.alpha_highlight = 1.0
        self.bottom_boundary_handle = bottom_boundary


class SDH_CAGE_PT_deform(Panel):
    bl_idname = "SDH_CAGE_PT_deform"
    bl_label = "Simple Deformer"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Simple Deformer"

    @classmethod
    def poll(cls, context):
        target = target_from_context(context)
        return bool(target and target.type in SUPPORTED_TYPES)

    def draw(self, context):
        layout = self.layout
        target = target_from_context(context)
        target_resolved, modifier, controller = resolve_context_deform(context)
        stages = cage_modifiers(target)

        add_row = layout.row(align=True)
        add_row.operator(
            SDH_OT_add_cage_deform.bl_idname,
            text="Add Cage Deform",
            icon="MOD_SIMPLEDEFORM",
        )
        if not stages:
            box = layout.box()
            box.label(text="Independent cage deformation", icon="INFO")
            box.label(text="Bend, Twist, Taper, and Stretch.")
            return

        stack = layout.box()
        stack.label(text="Cage Stack", icon="MODIFIER")
        for index, stage_modifier in enumerate(stages):
            row = stack.row(align=True)
            select = row.operator(
                SDH_OT_select_cage_stage.bl_idname,
                text="",
                icon="RADIOBUT_ON" if stage_modifier == modifier else "RADIOBUT_OFF",
            )
            select.index = index
            row.prop(stage_modifier, "name", text="")
            row.prop(
                stage_modifier, "show_viewport", text="",
                icon="RESTRICT_VIEW_OFF" if stage_modifier.show_viewport
                else "RESTRICT_VIEW_ON",
            )
            order = row.row(align=True)
            order.enabled = len(stages) > 1
            earlier_slot = order.row(align=True)
            earlier_slot.enabled = index > 0
            earlier = earlier_slot.operator(
                SDH_OT_move_cage_deform.bl_idname, text="", icon="TRIA_UP")
            earlier.index = index
            earlier.direction = "EARLIER"
            later_slot = order.row(align=True)
            later_slot.enabled = index < len(stages) - 1
            later = later_slot.operator(
                SDH_OT_move_cage_deform.bl_idname, text="", icon="TRIA_DOWN")
            later.index = index
            later.direction = "LATER"
            remove = row.operator(
                SDH_OT_remove_cage_deform.bl_idname,
                text="",
                icon="X",
            )
            remove.index = index

        stack.operator(
            SDH_OT_remove_cage_stack.bl_idname,
            text="Remove Cage Stack",
            icon="TRASH",
        )

        if target_resolved is None or modifier is None or controller is None:
            return

        properties = controller.sdh_cage_deform

        shape = layout.box()
        shape.label(text="Shape", icon="MOD_SIMPLEDEFORM")
        shape.prop(properties, "deform_type", expand=True)
        if properties.deform_type in {"BEND", "TWIST"}:
            shape.prop(properties, "strength")
        else:
            shape.prop(properties, "factor")
        if properties.deform_type == "BEND":
            shape.prop(properties, "direction")
        if properties.deform_type == "STRETCH":
            shape.prop(properties, "preserve_volume")
        shape.prop(properties, "mode", expand=True)
        shape.prop(properties, "origin")

        cage = layout.box()
        cage.label(text="Cage Controls", icon="CUBE")
        cage.label(
            text="Helper objects stay hidden until cage transform",
            icon="HIDE_ON",
        )
        edit_row = cage.row(align=True)
        for tool, label, icon in (
                ("MOVE", "Move", "ARROW_LEFTRIGHT"),
                ("ROTATE", "Rotate", "DRIVER_ROTATIONAL_DIFFERENCE"),
                ("SCALE", "Scale", "FULLSCREEN_ENTER")):
            operator = edit_row.operator(
                SDH_OT_cage_transform.bl_idname, text=label, icon=icon)
            operator.tool = tool

        cage.label(text="Deform Axis")
        auto_axis = cage.row(align=True)
        operator = auto_axis.operator(
            SDH_OT_set_cage_axis.bl_idname,
            text="Auto",
            depress=properties.alignment == "AUTO",
        )
        operator.alignment = "AUTO"
        axis_grid = cage.grid_flow(
            row_major=True, columns=3, even_columns=True, even_rows=True,
            align=True)
        for alignment, label in (
                ("POS_X", "X+"), ("POS_Y", "Y+"), ("POS_Z", "Z+"),
                ("NEG_X", "X-"), ("NEG_Y", "Y-"), ("NEG_Z", "Z-")):
            operator = axis_grid.operator(
                SDH_OT_set_cage_axis.bl_idname, text=label,
                depress=properties.alignment == alignment)
            operator.alignment = alignment

        fit_row = cage.row(align=True)
        fit_row.operator(
            SDH_OT_fit_cage_deform.bl_idname,
            text="Align & Fit",
            icon="FULLSCREEN_ENTER",
        )
        if is_cage_controller(context.object):
            fit_row.operator(
                SDH_OT_select_cage_target.bl_idname,
                text="Return to Object",
                icon="OBJECT_DATA",
            )
        else:
            fit_row.operator(
                SDH_OT_select_cage_controller.bl_idname,
                text="Select Cage",
                icon="EMPTY_AXIS",
            )

        cage.prop(properties, "show_cage")
        gizmo_row = cage.row(align=True)
        if properties.deform_type == "BEND":
            gizmo_row.prop(
                properties, "show_axis_gizmo", text="Bend Trend")
            gizmo_row.prop(
                properties, "show_direction_handle", text="Fine Direction")
        else:
            gizmo_row.prop(properties, "show_axis_gizmo", text="Axis Switch")
        ends_header = cage.row(align=True)
        ends_header.prop(
            properties, "show_end_shape_settings",
            text="Independent Ends",
            icon=("TRIA_DOWN" if properties.show_end_shape_settings else "TRIA_RIGHT"),
            emboss=False,
        )
        if properties.show_end_shape_settings:
            ends = cage.box()
            ends.prop(properties, "limit_boundaries_to_object")
            ends.prop(properties, "show_boundary_handles")
            ends.prop(properties, "show_end_handles")
            for side, label in (("top", "Top"), ("bottom", "Bottom")):
                ends.label(text=label)
                scale_row = ends.row(align=True)
                scale_row.label(text="Scale")
                scale_row.prop(properties, f"{side}_scale", index=0, text="X")
                scale_row.prop(properties, f"{side}_scale", index=1, text="Z")
                offset_row = ends.row(align=True)
                offset_row.label(text="Offset")
                offset_row.prop(properties, f"{side}_offset", index=0, text="X")
                offset_row.prop(properties, f"{side}_offset", index=1, text="Z")
            ends.operator(
                SDH_OT_reset_cage_ends.bl_idname,
                text="Reset Independent Ends",
                icon="LOOP_BACK",
            )

        numeric_header = cage.row(align=True)
        numeric_header.prop(
            properties, "show_numeric_controls",
            text="Numeric Controls",
            icon=("TRIA_DOWN" if properties.show_numeric_controls else "TRIA_RIGHT"),
            emboss=False,
        )
        if properties.show_numeric_controls:
            numeric = cage.column(align=True)
            numeric.prop(properties, "size")
            numeric.prop(controller, "location")
            numeric.prop(controller, "rotation_euler", text="Rotation")

        actions = layout.row(align=True)
        actions.operator(
            SDH_OT_duplicate_cage_deform.bl_idname,
            text="Duplicate",
            icon="DUPLICATE",
        )
        actions.operator(
            SDH_OT_remove_cage_deform.bl_idname,
            text="Remove Stage",
            icon="TRASH",
        )

        hint = layout.box()
        if properties.show_boundary_handles:
            hint.label(
                text="Yellow top / amber bottom: move one boundary",
                icon="MOUSE_LMB",
            )
            if properties.limit_boundaries_to_object:
                hint.label(
                    text="Length handles stop at the object bounds",
                    icon="LOCKED",
                )
            hint.label(text="Drag Along Cage • Shift Precise • Ctrl Snap")
        if properties.show_end_handles:
            hint.label(
                text="Cyan top / green bottom: drag one end only",
                icon="MOUSE_LMB",
            )
            hint.label(text="Alt Slide X • Shift Precise • Ctrl Snap")
        if properties.show_axis_gizmo:
            if properties.deform_type == "BEND":
                hint.label(
                    text="Red / green arrows: horizontal / vertical bend trend",
                    icon="ORIENTATION_GLOBAL",
                )
                hint.label(text="Click to choose and close • Ctrl keeps choices open")
            else:
                hint.label(
                    text="Axis switch: RGB is X/Y/Z; diamond is +, ring is -",
                    icon="ORIENTATION_GLOBAL",
                )
        if properties.deform_type == "BEND":
            hint.label(text="Orange arc: drag Bend angle", icon="MOUSE_LMB")
            if properties.show_direction_handle:
                hint.label(text="Purple ring: drag Bend direction")
        elif properties.deform_type == "TWIST":
            hint.label(text="Large purple twist ring: drag around its center", icon="MOUSE_LMB")
        elif properties.deform_type == "TAPER":
            hint.label(text="Amber taper handle: drag Factor", icon="MOUSE_LMB")
        else:
            hint.label(text="Green stretch handle: drag Factor", icon="MOUSE_LMB")
        hint.label(text="Shift Precise • Ctrl Snap")


classes = (
    SDHCageControllerProperties,
    SDH_OT_add_cage_deform,
    SDH_OT_fit_cage_deform,
    SDH_OT_reset_cage_ends,
    SDH_OT_select_cage_stage,
    SDH_OT_select_cage_controller,
    SDH_OT_select_cage_target,
    SDH_OT_cage_transform,
    SDH_OT_set_cage_axis,
    SDH_OT_set_bend_trend,
    SDH_OT_duplicate_cage_deform,
    SDH_OT_move_cage_deform,
    SDH_OT_remove_cage_deform,
    SDH_OT_remove_cage_stack,
    SDHCageStrengthGizmo,
    SDHCageDirectionGizmo,
    SDHCageBendTrendGizmo,
    SDHCageAxisGizmo,
    SDHCageEndShapeGizmo,
    SDHCageBoundaryGizmo,
    SDHCageDeformGizmoGroup,
    SDH_CAGE_PT_deform,
)


def register():
    global _LEGACY_MIGRATION_PENDING
    _LEGACY_MIGRATION_PENDING = True
    for item in classes:
        bpy.utils.register_class(item)
    bpy.types.Object.sdh_cage_deform = bpy.props.PointerProperty(
        type=SDHCageControllerProperties)
    if _frame_change_sync not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(_frame_change_sync)
    if _render_sync not in bpy.app.handlers.render_pre:
        bpy.app.handlers.render_pre.append(_render_sync)
    if _load_sync not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_sync)
    if not bpy.app.timers.is_registered(_controller_timer):
        # Extension activation runs under Blender's _RestrictData wrapper.
        # Defer the first data-block scan until normal context is restored.
        bpy.app.timers.register(
            _controller_timer, first_interval=0.01, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_controller_timer):
        bpy.app.timers.unregister(_controller_timer)
    if _load_sync in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_sync)
    if _render_sync in bpy.app.handlers.render_pre:
        bpy.app.handlers.render_pre.remove(_render_sync)
    if _frame_change_sync in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(_frame_change_sync)
    if hasattr(bpy.types.Object, "sdh_cage_deform"):
        del bpy.types.Object.sdh_cage_deform
    for item in reversed(classes):
        bpy.utils.unregister_class(item)
    for obj in tuple(bpy.data.objects):
        try:
            if obj.get(RUNTIME_EVALUATOR, False):
                bpy.data.objects.remove(obj, do_unlink=True)
        except ReferenceError:
            pass
