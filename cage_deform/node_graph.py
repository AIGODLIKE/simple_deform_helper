"""Geometry Nodes construction and deformation-order wiring."""
from __future__ import annotations

import math
import uuid

from .deform_contract import (
    CHAIN_BOUNDARY_EPSILON,
    CURVE_LENGTH_VALUES,
    CURVE_MODE_VALUES,
    DEFORM_BITS,
    DEFORM_MASK_ALL,
    DEFORM_ORDER,
    EPSILON,
    FFD_CORNERS,
    FFD_SOCKET_NAMES,
    MODE_VALUES,
    ORIGIN_VALUES,
    _full_deform_order,
    deform_order_signature,
)
from .node_runtime import (
    clear_interface_cache,
    invalidate_deform_order,
    mark_deform_order,
    rna_pointer,
    verified_deform_order,
)
from .node_schema import (
    DEFORM_BLOCK_FRAME_NODE,
    DEFORM_BLOCK_INPUT_NODE,
    DEFORM_BLOCK_OUTPUT_NODE,
    DEFORM_CHAIN_OUTPUT_INPUT_NODE,
    DEFORM_CHAIN_OUTPUT_NODE,
    DEFORM_FRAME_GAP,
    DEFORM_FRAME_MIN_WIDTH,
    DEFORM_FRAME_START_X,
    DEFORM_FRAME_Y,
    DEFORM_ORDER_END_NODE,
    DEFORM_ORDER_SIGNATURE,
    DEFORM_ORDER_START_NODE,
    GROUP_MARKER,
    GROUP_VERSION,
    NODE_FRAME_LOCAL,
    NODE_FRAME_MODE_OUTPUT,
    NODE_FRAME_PROFILE,
    _INTERFACE_CACHE_TOKEN,
    _LEGACY_CHAIN_CORRECTION_ACTIVE,
    _LEGACY_CHAIN_CORRECTION_ATTRIBUTE,
)


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


def _deform_order_link_pairs(node_group, order):
    """Resolve the mutable links between operations and chain conjugation."""
    full_order = _full_deform_order(order)
    try:
        start = node_group.nodes[DEFORM_ORDER_START_NODE]
        end = node_group.nodes[DEFORM_ORDER_END_NODE]
        inputs = {
            name: node_group.nodes[DEFORM_BLOCK_INPUT_NODE[name]]
            for name in DEFORM_ORDER
        }
        outputs = {
            name: node_group.nodes[DEFORM_BLOCK_OUTPUT_NODE[name]]
            for name in DEFORM_ORDER
        }
        chain_input = node_group.nodes[DEFORM_CHAIN_OUTPUT_INPUT_NODE]
        chain_output = node_group.nodes[DEFORM_CHAIN_OUTPUT_NODE]
    except KeyError as error:
        raise RuntimeError(
            f"Cage deform order block is missing: {error.args[0]}") from error

    pipeline = list(full_order)
    chain_index = (
        pipeline.index("BEND") + 1 if "BEND" in pipeline else len(pipeline))
    pipeline.insert(chain_index, "CHAIN_OUTPUT")
    source_sockets = {
        **{name: outputs[name].outputs[0] for name in full_order},
        "CHAIN_OUTPUT": chain_output.outputs[0],
    }
    destination_sockets = {
        **{name: inputs[name].inputs[0] for name in full_order},
        "CHAIN_OUTPUT": chain_input.inputs[0],
    }
    sources = [start.outputs[0]] + [
        source_sockets[name] for name in pipeline]
    destinations = [
        destination_sockets[name] for name in pipeline
    ] + [end.inputs[0]]
    return tuple(zip(sources, destinations))


def _deform_order_links_match(node_group, order):
    try:
        pairs = _deform_order_link_pairs(node_group, order)
    except RuntimeError:
        return False
    for source, destination in pairs:
        links = tuple(destination.links)
        if len(links) != 1 or links[0].from_socket != source:
            return False
    return True


def _layout_deform_order_frames(node_group, order):
    """Place permanent operation frames in the authored pipeline order."""
    full_order = _full_deform_order(order)
    try:
        frames = {
            name: node_group.nodes[DEFORM_BLOCK_FRAME_NODE[name]]
            for name in DEFORM_ORDER
        }
        mode_frame = node_group.nodes[NODE_FRAME_MODE_OUTPUT]
    except KeyError:
        # Version migration rebuilds managed groups before normal use.  Keep
        # relinking usable for an externally-copied legacy group that has not
        # reached that migration path yet.
        return False

    changed = False
    x_location = DEFORM_FRAME_START_X
    for pipeline_index, name in enumerate(full_order, 3):
        frame = frames[name]
        location = (x_location, DEFORM_FRAME_Y)
        if tuple(frame.location) != location:
            frame.location = location
            changed = True
        label = f"{pipeline_index:02d} {name.title()}"
        if frame.label != label:
            frame.label = label
            changed = True
        x_location += max(
            float(frame.width), DEFORM_FRAME_MIN_WIDTH[name]) + DEFORM_FRAME_GAP

    mode_location = (x_location, DEFORM_FRAME_Y)
    if tuple(mode_frame.location) != mode_location:
        mode_frame.location = mode_location
        changed = True
    return changed


def relink_deform_order(node_group, order):
    """Relink only the five inter-block sockets; interface and blocks persist."""
    full_order = _full_deform_order(order)
    signature = deform_order_signature(full_order)
    pointer = rna_pointer(node_group)
    if (
            str(node_group.get(DEFORM_ORDER_SIGNATURE, "")) == signature and
            (
                verified_deform_order(pointer) == signature or
                _deform_order_links_match(node_group, full_order)
            )
    ):
        mark_deform_order(pointer, signature)
        return False

    pairs = _deform_order_link_pairs(node_group, full_order)
    for _source, destination in pairs:
        for link in tuple(destination.links):
            node_group.links.remove(link)
    for source, destination in pairs:
        node_group.links.new(source, destination)
    _layout_deform_order_frames(node_group, full_order)
    node_group[DEFORM_ORDER_SIGNATURE] = signature
    mark_deform_order(pointer, signature)
    return True


def ensure_modifier_deform_order(target, modifier, order):
    """Apply one stage order, first isolating a shared stage node group."""
    node_group = getattr(modifier, "node_group", None)
    if node_group is None:
        return False
    full_order = _full_deform_order(order)
    signature = deform_order_signature(full_order)
    pointer = rna_pointer(node_group)
    stored_signature = str(
        node_group.get(DEFORM_ORDER_SIGNATURE, ""))
    needs_relink = stored_signature != signature
    if not needs_relink and (
            not pointer or
            verified_deform_order(pointer) != signature
    ):
        # Validate each graph once per process (or after a known relink).  The
        # old implementation scanned every destination's ``links`` collection
        # on every controller sync, even when the stored order signature had
        # not changed.  Managed node groups are only mutated through the
        # relink/build paths below, which invalidate this token explicitly.
        needs_relink = not _deform_order_links_match(node_group, full_order)
        if not needs_relink:
            mark_deform_order(pointer, signature)
    if not needs_relink:
        return False

    copied = False
    if node_group.users > 1:
        original = node_group
        node_group = original.copy()
        node_group.name = f"{original.name} Order"
        modifier.node_group = node_group
        copied = True
    changed = relink_deform_order(node_group, full_order)
    if changed or copied:
        try:
            target.update_tag()
        except (AttributeError, ReferenceError, RuntimeError):
            pass
    return bool(changed or copied)


def build_node_group(node_group):
    # Any interface rebuild invalidates the Python-side socket map.  A unique
    # token also protects against stale entries if Blender reuses an RNA
    # pointer after an old node group is removed.
    clear_interface_cache()
    invalidate_deform_order(node_group)
    node_group.nodes.clear()
    node_group.interface.clear()
    # Remove bookkeeping written by the pre-2.1.12 residual implementation.
    # The rebuilt group has no correction sockets or nodes, so retaining these
    # properties would make an apparently live stage look partially enabled.
    for key in (
            _LEGACY_CHAIN_CORRECTION_ATTRIBUTE,
            _LEGACY_CHAIN_CORRECTION_ACTIVE,
    ):
        try:
            if key in node_group:
                del node_group[key]
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass

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
    deform_socket.max_value = len(DEFORM_ORDER) - 1
    mode_socket = node_group.interface.new_socket(
        name="Mode", in_out="INPUT", socket_type="NodeSocketInt")
    mode_socket.min_value = 0
    mode_socket.max_value = 3
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
    # Keep every legacy socket above in its original order.  Blender uses the
    # generated interface identifiers to persist modifier values, so appending
    # the multi-deform inputs makes in-place upgrades less disruptive.
    deform_mask_socket = node_group.interface.new_socket(
        name="Deform Types", in_out="INPUT", socket_type="NodeSocketInt")
    deform_mask_socket.default_value = DEFORM_BITS["BEND"]
    deform_mask_socket.min_value = 0
    deform_mask_socket.max_value = DEFORM_MASK_ALL
    bend_strength_socket = node_group.interface.new_socket(
        name="Bend Angle", in_out="INPUT", socket_type="NodeSocketFloat")
    bend_strength_socket.subtype = "ANGLE"
    bend_strength_socket.default_value = math.radians(45.0)
    bend_direction_socket = node_group.interface.new_socket(
        name="Bend Direction", in_out="INPUT", socket_type="NodeSocketFloat")
    bend_direction_socket.subtype = "ANGLE"
    twist_strength_socket = node_group.interface.new_socket(
        name="Twist Angle", in_out="INPUT", socket_type="NodeSocketFloat")
    twist_strength_socket.subtype = "ANGLE"
    twist_strength_socket.default_value = math.radians(45.0)
    taper_factor_socket = node_group.interface.new_socket(
        name="Taper Factor", in_out="INPUT", socket_type="NodeSocketFloat")
    taper_factor_socket.default_value = 0.5
    stretch_factor_socket = node_group.interface.new_socket(
        name="Stretch Factor", in_out="INPUT", socket_type="NodeSocketFloat")
    stretch_factor_socket.default_value = 0.5
    chain_domain_socket = node_group.interface.new_socket(
        name="Chain Domain Attribute", in_out="INPUT",
        socket_type="NodeSocketString")
    chain_root_socket = node_group.interface.new_socket(
        name="Chain Root Stage", in_out="INPUT",
        socket_type="NodeSocketBool")
    chain_root_socket.default_value = True
    chain_tip_socket = node_group.interface.new_socket(
        name="Chain Tip Stage", in_out="INPUT",
        socket_type="NodeSocketBool")
    chain_tip_socket.default_value = True
    stage_enabled_socket = node_group.interface.new_socket(
        name="Stage Enabled", in_out="INPUT",
        socket_type="NodeSocketBool")
    stage_enabled_socket.default_value = True
    chain_input_pivot_socket = node_group.interface.new_socket(
        name="Chain Input Pivot", in_out="INPUT",
        socket_type="NodeSocketVector")
    chain_input_pivot_socket.subtype = "TRANSLATION"
    chain_input_pivot_socket.default_value = (0.0, 0.0, 0.0)
    chain_input_inverse_x_socket = node_group.interface.new_socket(
        name="Chain Input Inverse X", in_out="INPUT",
        socket_type="NodeSocketVector")
    chain_input_inverse_x_socket.default_value = (1.0, 0.0, 0.0)
    chain_input_inverse_y_socket = node_group.interface.new_socket(
        name="Chain Input Inverse Y", in_out="INPUT",
        socket_type="NodeSocketVector")
    chain_input_inverse_y_socket.default_value = (0.0, 1.0, 0.0)
    chain_input_inverse_z_socket = node_group.interface.new_socket(
        name="Chain Input Inverse Z", in_out="INPUT",
        socket_type="NodeSocketVector")
    chain_input_inverse_z_socket.default_value = (0.0, 0.0, 1.0)
    chain_output_offset_socket = node_group.interface.new_socket(
        name="Chain Output Offset", in_out="INPUT",
        socket_type="NodeSocketVector")
    chain_output_offset_socket.subtype = "TRANSLATION"
    chain_output_offset_socket.default_value = (0.0, 0.0, 0.0)
    chain_output_x_socket = node_group.interface.new_socket(
        name="Chain Output X", in_out="INPUT",
        socket_type="NodeSocketVector")
    chain_output_x_socket.default_value = (1.0, 0.0, 0.0)
    chain_output_y_socket = node_group.interface.new_socket(
        name="Chain Output Y", in_out="INPUT",
        socket_type="NodeSocketVector")
    chain_output_y_socket.default_value = (0.0, 1.0, 0.0)
    chain_output_z_socket = node_group.interface.new_socket(
        name="Chain Output Z", in_out="INPUT",
        socket_type="NodeSocketVector")
    chain_output_z_socket.default_value = (0.0, 0.0, 1.0)
    chain_source_start_socket = node_group.interface.new_socket(
        name="Chain Source Start", in_out="INPUT",
        socket_type="NodeSocketFloat")
    chain_source_end_socket = node_group.interface.new_socket(
        name="Chain Source End", in_out="INPUT",
        socket_type="NodeSocketFloat")
    chain_source_end_socket.default_value = 1.0e20
    chain_root_output_active_socket = node_group.interface.new_socket(
        name="Chain Root Output Active", in_out="INPUT",
        socket_type="NodeSocketBool")
    chain_root_output_active_socket.default_value = False
    chain_global_stretch_active_socket = node_group.interface.new_socket(
        name="Chain Global Stretch Active", in_out="INPUT",
        socket_type="NodeSocketBool")
    chain_global_stretch_active_socket.default_value = False
    chain_global_stretch_factor_socket = node_group.interface.new_socket(
        name="Chain Global Stretch Factor", in_out="INPUT",
        socket_type="NodeSocketFloat")
    chain_global_stretch_factor_socket.default_value = 0.0
    chain_global_stretch_center_socket = node_group.interface.new_socket(
        name="Chain Global Stretch Center", in_out="INPUT",
        socket_type="NodeSocketVector")
    chain_global_stretch_center_socket.default_value = (0.0, 0.0, 0.0)
    chain_global_stretch_rotation_socket = node_group.interface.new_socket(
        name="Chain Global Stretch Rotation", in_out="INPUT",
        socket_type="NodeSocketVector")
    chain_global_stretch_rotation_socket.default_value = (0.0, 0.0, 0.0)
    chain_global_stretch_offset_socket = node_group.interface.new_socket(
        name="Chain Global Stretch Source Offset", in_out="INPUT",
        socket_type="NodeSocketFloat")
    chain_global_stretch_length_socket = node_group.interface.new_socket(
        name="Chain Global Stretch Length", in_out="INPUT",
        socket_type="NodeSocketFloat")
    chain_global_stretch_length_socket.default_value = 2.0
    chain_global_stretch_origin_socket = node_group.interface.new_socket(
        name="Chain Global Stretch Origin", in_out="INPUT",
        socket_type="NodeSocketInt")
    chain_global_stretch_origin_socket.default_value = ORIGIN_VALUES["BOTTOM"]
    chain_global_prefix_active_socket = node_group.interface.new_socket(
        name="Chain Global Prefix Active", in_out="INPUT",
        socket_type="NodeSocketBool")
    chain_global_prefix_active_socket.default_value = False
    chain_global_prefix_mask_socket = node_group.interface.new_socket(
        name="Chain Global Prefix Types", in_out="INPUT",
        socket_type="NodeSocketInt")
    chain_global_prefix_mask_socket.default_value = 0
    chain_global_prefix_mask_socket.min_value = 0
    chain_global_prefix_mask_socket.max_value = DEFORM_MASK_ALL
    chain_global_prefix_bend_socket = node_group.interface.new_socket(
        name="Chain Global Prefix Bend", in_out="INPUT",
        socket_type="NodeSocketFloat")
    chain_global_prefix_bend_socket.subtype = "ANGLE"
    chain_global_prefix_direction_socket = node_group.interface.new_socket(
        name="Chain Global Prefix Direction", in_out="INPUT",
        socket_type="NodeSocketFloat")
    chain_global_prefix_direction_socket.subtype = "ANGLE"
    chain_global_prefix_twist_socket = node_group.interface.new_socket(
        name="Chain Global Prefix Twist", in_out="INPUT",
        socket_type="NodeSocketFloat")
    chain_global_prefix_twist_socket.subtype = "ANGLE"
    chain_global_prefix_taper_socket = node_group.interface.new_socket(
        name="Chain Global Prefix Taper", in_out="INPUT",
        socket_type="NodeSocketFloat")
    chain_global_prefix_stretch_socket = node_group.interface.new_socket(
        name="Chain Global Prefix Stretch", in_out="INPUT",
        socket_type="NodeSocketFloat")
    chain_global_prefix_center_socket = node_group.interface.new_socket(
        name="Chain Global Prefix Center", in_out="INPUT",
        socket_type="NodeSocketVector")
    chain_global_prefix_center_socket.subtype = "TRANSLATION"
    chain_global_prefix_rotation_socket = node_group.interface.new_socket(
        name="Chain Global Prefix Rotation", in_out="INPUT",
        socket_type="NodeSocketVector")
    chain_global_prefix_rotation_socket.subtype = "EULER"
    chain_global_prefix_offset_socket = node_group.interface.new_socket(
        name="Chain Global Prefix Source Offset", in_out="INPUT",
        socket_type="NodeSocketFloat")
    chain_global_prefix_length_socket = node_group.interface.new_socket(
        name="Chain Global Prefix Length", in_out="INPUT",
        socket_type="NodeSocketFloat")
    chain_global_prefix_length_socket.default_value = 2.0
    chain_global_prefix_origin_socket = node_group.interface.new_socket(
        name="Chain Global Prefix Origin", in_out="INPUT",
        socket_type="NodeSocketInt")
    chain_global_prefix_origin_socket.default_value = ORIGIN_VALUES["BOTTOM"]
    # New operation inputs are appended after every legacy socket. Blender
    # persists modifier values by generated interface identifier, so changing
    # the historical order would detach values in existing files.
    shear_socket = node_group.interface.new_socket(
        name="Shear", in_out="INPUT", socket_type="NodeSocketVector")
    shear_socket.default_value = (0.0, 0.0, 0.0)
    ffd_sockets = []
    for socket_name in FFD_SOCKET_NAMES:
        socket = node_group.interface.new_socket(
            name=socket_name, in_out="INPUT", socket_type="NodeSocketVector")
        socket.subtype = "TRANSLATION"
        socket.default_value = (0.0, 0.0, 0.0)
        socket.hide_in_modifier = True
        ffd_sockets.append(socket)
    chain_global_profile_active_socket = node_group.interface.new_socket(
        name="Chain Global Profile Active", in_out="INPUT",
        socket_type="NodeSocketBool")
    chain_global_profile_active_socket.default_value = False
    chain_global_profile_bottom_scale_socket = node_group.interface.new_socket(
        name="Chain Global Profile Bottom Scale", in_out="INPUT",
        socket_type="NodeSocketVector")
    chain_global_profile_bottom_scale_socket.default_value = (1.0, 1.0, 1.0)
    chain_global_profile_top_scale_socket = node_group.interface.new_socket(
        name="Chain Global Profile Top Scale", in_out="INPUT",
        socket_type="NodeSocketVector")
    chain_global_profile_top_scale_socket.default_value = (1.0, 1.0, 1.0)
    chain_global_profile_bottom_offset_socket = node_group.interface.new_socket(
        name="Chain Global Profile Bottom Offset", in_out="INPUT",
        socket_type="NodeSocketVector")
    chain_global_profile_bottom_offset_socket.default_value = (0.0, 0.0, 0.0)
    chain_global_profile_top_offset_socket = node_group.interface.new_socket(
        name="Chain Global Profile Top Offset", in_out="INPUT",
        socket_type="NodeSocketVector")
    chain_global_profile_top_offset_socket.default_value = (0.0, 0.0, 0.0)
    # Curve-cage inputs are appended after every historical socket so existing
    # modifier identifiers and saved values remain stable during upgrades.
    curve_guide_socket = node_group.interface.new_socket(
        name="Curve Guide Object", in_out="INPUT",
        socket_type="NodeSocketObject")
    curve_station_socket = node_group.interface.new_socket(
        name="Curve Station Object", in_out="INPUT",
        socket_type="NodeSocketObject")
    curve_length_mode_socket = node_group.interface.new_socket(
        name="Curve Length Mode", in_out="INPUT",
        socket_type="NodeSocketInt")
    curve_length_mode_socket.min_value = 0
    curve_length_mode_socket.max_value = 2
    curve_boundary_mode_socket = node_group.interface.new_socket(
        name="Curve Boundary Mode", in_out="INPUT",
        socket_type="NodeSocketInt")
    curve_boundary_mode_socket.min_value = 0
    curve_boundary_mode_socket.max_value = 2
    curve_preserve_volume_socket = node_group.interface.new_socket(
        name="Curve Preserve Volume", in_out="INPUT",
        socket_type="NodeSocketBool")
    curve_preserve_volume_socket.default_value = False
    curve_closed_socket = node_group.interface.new_socket(
        name="Curve Closed", in_out="INPUT",
        socket_type="NodeSocketBool")
    curve_closed_socket.default_value = False
    # Appended after every 2.4.62 socket.  Blender persists modifier values by
    # generated interface identifiers, so these must never be inserted among
    # the historical Curve inputs above.
    curve_range_start_socket = node_group.interface.new_socket(
        name="Curve Range Start", in_out="INPUT",
        socket_type="NodeSocketFloat")
    curve_range_start_socket.default_value = 0.0
    curve_range_start_socket.min_value = 0.0
    curve_range_start_socket.max_value = 1.0
    curve_range_end_socket = node_group.interface.new_socket(
        name="Curve Range End", in_out="INPUT",
        socket_type="NodeSocketFloat")
    curve_range_end_socket.default_value = 1.0
    curve_range_end_socket.min_value = 0.0
    curve_range_end_socket.max_value = 1.0
    # Appended in schema 39. These compose non-destructively with native
    # Bezier point radius/tilt and the interpolated station profile.
    curve_global_radius_socket = node_group.interface.new_socket(
        name="Curve Global Radius", in_out="INPUT",
        socket_type="NodeSocketFloat")
    curve_global_radius_socket.default_value = 1.0
    curve_global_radius_socket.min_value = 0.0
    curve_global_twist_socket = node_group.interface.new_socket(
        name="Curve Global Twist", in_out="INPUT",
        socket_type="NodeSocketFloat")
    curve_global_twist_socket.default_value = 0.0
    curve_global_twist_socket.subtype = "ANGLE"
    # Rest-binding inputs are appended after the 2.6.0 Curve profile sockets.
    # Existing Curve cages leave this disabled and retain their absolute guide
    # mapping; edge-extracted cages opt into the differential transform.
    curve_rest_guide_socket = node_group.interface.new_socket(
        name="Curve Rest Guide Object", in_out="INPUT",
        socket_type="NodeSocketObject")
    curve_relative_binding_socket = node_group.interface.new_socket(
        name="Curve Relative Binding", in_out="INPUT",
        socket_type="NodeSocketBool")
    curve_relative_binding_socket.default_value = False
    # Schema 41 appends the analytic chain-baseline order contract.  Never
    # insert these among historical sockets because Blender persists modifier
    # values by generated interface identifier.
    chain_global_prefix_pre_shear_socket = node_group.interface.new_socket(
        name="Chain Global Prefix Pre Shear Types", in_out="INPUT",
        socket_type="NodeSocketInt")
    chain_global_prefix_pre_shear_socket.min_value = 0
    chain_global_prefix_pre_shear_socket.max_value = DEFORM_MASK_ALL
    chain_global_prefix_post_shear_socket = node_group.interface.new_socket(
        name="Chain Global Prefix Post Shear Types", in_out="INPUT",
        socket_type="NodeSocketInt")
    chain_global_prefix_post_shear_socket.min_value = 0
    chain_global_prefix_post_shear_socket.max_value = DEFORM_MASK_ALL
    chain_global_prefix_shear_socket = node_group.interface.new_socket(
        name="Chain Global Prefix Shear", in_out="INPUT",
        socket_type="NodeSocketVector")
    chain_global_suffix_active_socket = node_group.interface.new_socket(
        name="Chain Global Suffix Active", in_out="INPUT",
        socket_type="NodeSocketBool")
    chain_global_suffix_mask_socket = node_group.interface.new_socket(
        name="Chain Global Suffix Types", in_out="INPUT",
        socket_type="NodeSocketInt")
    chain_global_suffix_mask_socket.min_value = 0
    chain_global_suffix_mask_socket.max_value = DEFORM_MASK_ALL
    chain_global_suffix_pre_shear_socket = node_group.interface.new_socket(
        name="Chain Global Suffix Pre Shear Types", in_out="INPUT",
        socket_type="NodeSocketInt")
    chain_global_suffix_pre_shear_socket.min_value = 0
    chain_global_suffix_pre_shear_socket.max_value = DEFORM_MASK_ALL
    chain_global_suffix_post_shear_socket = node_group.interface.new_socket(
        name="Chain Global Suffix Post Shear Types", in_out="INPUT",
        socket_type="NodeSocketInt")
    chain_global_suffix_post_shear_socket.min_value = 0
    chain_global_suffix_post_shear_socket.max_value = DEFORM_MASK_ALL
    chain_global_suffix_twist_socket = node_group.interface.new_socket(
        name="Chain Global Suffix Twist", in_out="INPUT",
        socket_type="NodeSocketFloat")
    chain_global_suffix_twist_socket.subtype = "ANGLE"
    chain_global_suffix_taper_socket = node_group.interface.new_socket(
        name="Chain Global Suffix Taper", in_out="INPUT",
        socket_type="NodeSocketFloat")
    chain_global_suffix_shear_socket = node_group.interface.new_socket(
        name="Chain Global Suffix Shear", in_out="INPUT",
        socket_type="NodeSocketVector")
    # Appended last so older modifiers keep their persisted identifiers.
    # Left visible in the modifier so users can toggle its attribute input
    # (vertex group) directly on the Geometry Nodes modifier as well.
    influence_weight_socket = node_group.interface.new_socket(
        name="Influence Weight", in_out="INPUT",
        socket_type="NodeSocketFloat")
    influence_weight_socket.subtype = "FACTOR"
    influence_weight_socket.default_value = 1.0
    influence_weight_socket.min_value = 0.0
    influence_weight_socket.max_value = 1.0
    for socket in (
            chain_domain_socket, chain_root_socket, chain_tip_socket,
            stage_enabled_socket, chain_input_pivot_socket,
            chain_input_inverse_x_socket, chain_input_inverse_y_socket,
            chain_input_inverse_z_socket, chain_output_offset_socket,
            chain_output_x_socket, chain_output_y_socket,
            chain_output_z_socket, chain_source_start_socket,
            chain_source_end_socket,
            chain_root_output_active_socket,
            chain_global_stretch_active_socket,
            chain_global_stretch_factor_socket,
            chain_global_stretch_center_socket,
            chain_global_stretch_rotation_socket,
            chain_global_stretch_offset_socket,
            chain_global_stretch_length_socket,
            chain_global_stretch_origin_socket,
            chain_global_prefix_active_socket,
            chain_global_prefix_mask_socket,
            chain_global_prefix_bend_socket,
            chain_global_prefix_direction_socket,
            chain_global_prefix_twist_socket,
            chain_global_prefix_taper_socket,
            chain_global_prefix_stretch_socket,
            chain_global_prefix_center_socket,
            chain_global_prefix_rotation_socket,
            chain_global_prefix_offset_socket,
            chain_global_prefix_length_socket,
            chain_global_prefix_origin_socket,
            chain_global_profile_active_socket,
            chain_global_profile_bottom_scale_socket,
            chain_global_profile_top_scale_socket,
            chain_global_profile_bottom_offset_socket,
            chain_global_profile_top_offset_socket,
            curve_guide_socket, curve_station_socket,
            curve_length_mode_socket, curve_boundary_mode_socket,
            curve_preserve_volume_socket, curve_closed_socket,
            curve_range_start_socket, curve_range_end_socket,
            curve_global_radius_socket, curve_global_twist_socket,
            curve_rest_guide_socket, curve_relative_binding_socket,
            chain_global_prefix_pre_shear_socket,
            chain_global_prefix_post_shear_socket,
            chain_global_prefix_shear_socket,
            chain_global_suffix_active_socket,
            chain_global_suffix_mask_socket,
            chain_global_suffix_pre_shear_socket,
            chain_global_suffix_post_shear_socket,
            chain_global_suffix_twist_socket,
            chain_global_suffix_taper_socket,
            chain_global_suffix_shear_socket):
        socket.hide_in_modifier = True

    nodes = node_group.nodes
    links = node_group.links

    frame_specs = (
        ("LOCAL", NODE_FRAME_LOCAL, "01 Local Space",
         (0.18, 0.24, 0.32), (-3800.0, DEFORM_FRAME_Y), 1100.0),
        ("PROFILE", NODE_FRAME_PROFILE, "02 Cage Profile",
         (0.28, 0.30, 0.20), (-2500.0, DEFORM_FRAME_Y), 2800.0),
        ("BEND", DEFORM_BLOCK_FRAME_NODE["BEND"], "Bend",
         (0.18, 0.32, 0.45), (500.0, DEFORM_FRAME_Y),
         DEFORM_FRAME_MIN_WIDTH["BEND"]),
        ("TWIST", DEFORM_BLOCK_FRAME_NODE["TWIST"], "Twist",
         (0.36, 0.23, 0.42), (2200.0, DEFORM_FRAME_Y),
         DEFORM_FRAME_MIN_WIDTH["TWIST"]),
        ("TAPER", DEFORM_BLOCK_FRAME_NODE["TAPER"], "Taper",
         (0.22, 0.38, 0.27), (3300.0, DEFORM_FRAME_Y),
         DEFORM_FRAME_MIN_WIDTH["TAPER"]),
        ("STRETCH", DEFORM_BLOCK_FRAME_NODE["STRETCH"], "Stretch",
         (0.43, 0.31, 0.16), (4200.0, DEFORM_FRAME_Y),
         DEFORM_FRAME_MIN_WIDTH["STRETCH"]),
        ("SHEAR", DEFORM_BLOCK_FRAME_NODE["SHEAR"], "Shear",
         (0.12, 0.38, 0.38), (5200.0, DEFORM_FRAME_Y),
         DEFORM_FRAME_MIN_WIDTH["SHEAR"]),
        ("FFD", DEFORM_BLOCK_FRAME_NODE["FFD"], "FFD 2x2x2",
         (0.44, 0.16, 0.28), (6200.0, DEFORM_FRAME_Y),
         DEFORM_FRAME_MIN_WIDTH["FFD"]),
        ("CURVE", DEFORM_BLOCK_FRAME_NODE["CURVE"], "Curve Guide",
         (0.10, 0.34, 0.46), (8200.0, DEFORM_FRAME_Y),
         DEFORM_FRAME_MIN_WIDTH["CURVE"]),
        ("MODE", NODE_FRAME_MODE_OUTPUT, "09 Mode and Output",
         (0.28, 0.28, 0.30), (10500.0, DEFORM_FRAME_Y), 1700.0),
    )
    frames = {}
    for key, name, label, color, location, width in frame_specs:
        frame = nodes.new("NodeFrame")
        frame.name = name
        frame.label = label
        frame.label_size = 24
        frame.shrink = False
        frame.use_custom_color = True
        frame.color = color
        frame.location = location
        frame.width = width
        frame.height = 500.0
        frames[key] = frame

    class SectionRegistrar:
        """Parent generated nodes and lay each semantic section out as a DAG."""

        def __init__(self):
            self.active = None
            self.members = {key: [] for key in frames}

        def use(self, key):
            self.active = key

        def new(self, node_type):
            node = nodes.new(node_type)
            if self.active is not None:
                node.parent = frames[self.active]
                self.members[self.active].append(node)
            return node

        def layout(self, key, minimum_width):
            members = tuple(self.members[key])
            if not members:
                return
            pointers = {node.as_pointer() for node in members}
            depths = {}
            pending = list(members)
            while pending:
                progressed = False
                for node in tuple(pending):
                    sources = {
                        link.from_node.as_pointer()
                        for socket in node.inputs
                        for link in socket.links
                        if link.from_node.as_pointer() in pointers
                    }
                    if all(pointer in depths for pointer in sources):
                        depths[node.as_pointer()] = (
                            max((depths[pointer] for pointer in sources),
                                default=-1) + 1
                        )
                        pending.remove(node)
                        progressed = True
                if not progressed:
                    # Geometry Nodes graphs are acyclic.  Keep malformed or
                    # version-specific nodes visible instead of blocking build.
                    for node in pending:
                        depths[node.as_pointer()] = 0
                    break

            columns = {}
            for node in members:
                columns.setdefault(depths[node.as_pointer()], []).append(node)
            max_rows = max(len(column) for column in columns.values())
            for depth, column in columns.items():
                for row, node in enumerate(column):
                    node.location = (
                        60.0 + depth * 210.0,
                        -160.0 - row * 140.0,
                    )
            frame = frames[key]
            frame.width = max(
                float(minimum_width),
                180.0 + (max(columns) + 1) * 210.0,
            )
            frame.height = max(500.0, 240.0 + max_rows * 140.0)

    registrar = SectionRegistrar()
    group_input = nodes.new("NodeGroupInput")
    group_input.label = "Cage Deform Parameters"
    group_input.location = (-4400.0, DEFORM_FRAME_Y)
    group_output = nodes.new("NodeGroupOutput")
    registrar.use("LOCAL")
    position = registrar.new("GeometryNodeInputPosition")
    position.label = "Source Position"
    registrar.use("MODE")
    set_position = registrar.new("GeometryNodeSetPosition")
    set_position.label = "Apply Deformed Position"
    registrar.use("LOCAL")

    def math_node(operation, first, second=None, label=None):
        node = registrar.new("ShaderNodeMath")
        node.operation = operation
        node.label = label or operation.title()
        _feed(node_group, first, node.inputs[0])
        if second is not None:
            _feed(node_group, second, node.inputs[1])
        return node.outputs[0]

    def vector_math(operation, first, second):
        node = registrar.new("ShaderNodeVectorMath")
        node.operation = operation
        node.label = operation.title()
        _feed(node_group, first, node.inputs[0])
        if operation == "SCALE":
            _feed(node_group, second, _socket_by_type(
                node.inputs, "Scale", "NodeSocketFloat"))
        else:
            _feed(node_group, second, node.inputs[1])
        if operation == "DOT_PRODUCT":
            return _socket_by_type(
                node.outputs, "Value", "NodeSocketFloat")
        return node.outputs[0]

    def compare(data_type, operation, first, second):
        node = registrar.new("FunctionNodeCompare")
        node.data_type = data_type
        node.operation = operation
        node.label = f"{operation.title()} ({data_type.title()})"
        socket_type = "NodeSocketInt" if data_type == "INT" else "NodeSocketFloat"
        _feed(node_group, first, _socket_by_type(node.inputs, "A", socket_type))
        _feed(node_group, second, _socket_by_type(node.inputs, "B", socket_type))
        return node.outputs[0]

    def boolean(operation, first, second):
        node = registrar.new("FunctionNodeBooleanMath")
        node.operation = operation
        node.label = operation.title()
        _feed(node_group, first, node.inputs[0])
        # Unary Boolean Math operations (NOT) expose only one input on
        # Blender 5.2; older builds accepted a redundant second socket.
        # Keep the helper compatible with both layouts.
        if second is not None and len(node.inputs) > 1:
            _feed(node_group, second, node.inputs[1])
        return node.outputs[0]

    def switch(input_type, condition, false_value, true_value):
        node = registrar.new("GeometryNodeSwitch")
        node.input_type = input_type
        node.label = f"{input_type.title()} Switch"
        _feed(node_group, condition, _socket_by_type(node.inputs, "Switch", "NodeSocketBool"))
        _feed(node_group, false_value, _socket_by_type(node.inputs, "False"))
        _feed(node_group, true_value, _socket_by_type(node.inputs, "True"))
        return node.outputs[0]

    def separate(vector):
        node = registrar.new("ShaderNodeSeparateXYZ")
        node.label = "Separate XYZ"
        _feed(node_group, vector, node.inputs[0])
        return node.outputs[0], node.outputs[1], node.outputs[2]

    def combine(x, y, z):
        node = registrar.new("ShaderNodeCombineXYZ")
        node.label = "Combine XYZ"
        _feed(node_group, x, node.inputs[0])
        _feed(node_group, y, node.inputs[1])
        _feed(node_group, z, node.inputs[2])
        return node.outputs[0]

    def rotate(vector, rotation, invert=False):
        node = registrar.new("ShaderNodeVectorRotate")
        node.rotation_type = "EULER_XYZ"
        node.invert = invert
        node.label = "To Cage Space" if invert else "To Object Space"
        _feed(node_group, vector, node.inputs[0])
        _feed(node_group, rotation, _socket_by_type(node.inputs, "Rotation"))
        return node.outputs[0]

    def reroute(name, label, location):
        node = registrar.new("NodeReroute")
        node.name = name
        node.label = label
        node.location = location
        return node

    geometry = group_input.outputs[input_geometry.identifier]
    center = group_input.outputs[center_socket.identifier]
    rotation = group_input.outputs[rotation_socket.identifier]
    size = group_input.outputs[size_socket.identifier]
    mode = group_input.outputs[mode_socket.identifier]
    origin = group_input.outputs[origin_socket.identifier]
    preserve_volume = group_input.outputs[preserve_volume_socket.identifier]
    top_scale = group_input.outputs[top_scale_socket.identifier]
    bottom_scale = group_input.outputs[bottom_scale_socket.identifier]
    top_offset = group_input.outputs[top_offset_socket.identifier]
    bottom_offset = group_input.outputs[bottom_offset_socket.identifier]
    deform_mask = group_input.outputs[deform_mask_socket.identifier]
    bend_strength = group_input.outputs[bend_strength_socket.identifier]
    bend_direction = group_input.outputs[bend_direction_socket.identifier]
    twist_strength = group_input.outputs[twist_strength_socket.identifier]
    taper_factor = group_input.outputs[taper_factor_socket.identifier]
    stretch_factor = group_input.outputs[stretch_factor_socket.identifier]
    chain_domain_attribute = group_input.outputs[chain_domain_socket.identifier]
    chain_root_stage = group_input.outputs[chain_root_socket.identifier]
    chain_tip_stage = group_input.outputs[chain_tip_socket.identifier]
    stage_enabled = group_input.outputs[stage_enabled_socket.identifier]
    chain_input_pivot = group_input.outputs[
        chain_input_pivot_socket.identifier]
    chain_input_inverse_x = group_input.outputs[
        chain_input_inverse_x_socket.identifier]
    chain_input_inverse_y = group_input.outputs[
        chain_input_inverse_y_socket.identifier]
    chain_input_inverse_z = group_input.outputs[
        chain_input_inverse_z_socket.identifier]
    chain_output_offset = group_input.outputs[
        chain_output_offset_socket.identifier]
    chain_output_x = group_input.outputs[
        chain_output_x_socket.identifier]
    chain_output_y = group_input.outputs[
        chain_output_y_socket.identifier]
    chain_output_z = group_input.outputs[
        chain_output_z_socket.identifier]
    chain_source_start = group_input.outputs[
        chain_source_start_socket.identifier]
    chain_root_output_active = group_input.outputs[
        chain_root_output_active_socket.identifier]
    chain_global_stretch_active = group_input.outputs[
        chain_global_stretch_active_socket.identifier]
    chain_global_stretch_factor = group_input.outputs[
        chain_global_stretch_factor_socket.identifier]
    chain_global_stretch_center = group_input.outputs[
        chain_global_stretch_center_socket.identifier]
    chain_global_stretch_rotation = group_input.outputs[
        chain_global_stretch_rotation_socket.identifier]
    chain_global_stretch_offset = group_input.outputs[
        chain_global_stretch_offset_socket.identifier]
    chain_global_stretch_length = group_input.outputs[
        chain_global_stretch_length_socket.identifier]
    chain_global_stretch_origin = group_input.outputs[
        chain_global_stretch_origin_socket.identifier]
    chain_global_prefix_active = group_input.outputs[
        chain_global_prefix_active_socket.identifier]
    chain_global_prefix_mask = group_input.outputs[
        chain_global_prefix_mask_socket.identifier]
    chain_global_prefix_bend = group_input.outputs[
        chain_global_prefix_bend_socket.identifier]
    chain_global_prefix_direction = group_input.outputs[
        chain_global_prefix_direction_socket.identifier]
    chain_global_prefix_twist = group_input.outputs[
        chain_global_prefix_twist_socket.identifier]
    chain_global_prefix_taper = group_input.outputs[
        chain_global_prefix_taper_socket.identifier]
    chain_global_prefix_stretch = group_input.outputs[
        chain_global_prefix_stretch_socket.identifier]
    chain_global_prefix_center = group_input.outputs[
        chain_global_prefix_center_socket.identifier]
    chain_global_prefix_rotation = group_input.outputs[
        chain_global_prefix_rotation_socket.identifier]
    chain_global_prefix_offset = group_input.outputs[
        chain_global_prefix_offset_socket.identifier]
    chain_global_prefix_length = group_input.outputs[
        chain_global_prefix_length_socket.identifier]
    chain_global_prefix_origin = group_input.outputs[
        chain_global_prefix_origin_socket.identifier]
    chain_global_profile_active = group_input.outputs[
        chain_global_profile_active_socket.identifier]
    chain_global_profile_bottom_scale = group_input.outputs[
        chain_global_profile_bottom_scale_socket.identifier]
    chain_global_profile_top_scale = group_input.outputs[
        chain_global_profile_top_scale_socket.identifier]
    chain_global_profile_bottom_offset = group_input.outputs[
        chain_global_profile_bottom_offset_socket.identifier]
    chain_global_profile_top_offset = group_input.outputs[
        chain_global_profile_top_offset_socket.identifier]
    curve_guide_object_input = group_input.outputs[
        curve_guide_socket.identifier]
    curve_station_object_input = group_input.outputs[
        curve_station_socket.identifier]
    curve_length_mode = group_input.outputs[
        curve_length_mode_socket.identifier]
    curve_boundary_mode = group_input.outputs[
        curve_boundary_mode_socket.identifier]
    curve_preserve_volume = group_input.outputs[
        curve_preserve_volume_socket.identifier]
    curve_closed = group_input.outputs[curve_closed_socket.identifier]
    curve_range_start = group_input.outputs[
        curve_range_start_socket.identifier]
    curve_range_end = group_input.outputs[
        curve_range_end_socket.identifier]
    curve_global_radius = group_input.outputs[
        curve_global_radius_socket.identifier]
    curve_global_twist = group_input.outputs[
        curve_global_twist_socket.identifier]
    curve_rest_guide_object_input = group_input.outputs[
        curve_rest_guide_socket.identifier]
    curve_relative_binding = group_input.outputs[
        curve_relative_binding_socket.identifier]
    chain_global_prefix_pre_shear = group_input.outputs[
        chain_global_prefix_pre_shear_socket.identifier]
    chain_global_prefix_post_shear = group_input.outputs[
        chain_global_prefix_post_shear_socket.identifier]
    chain_global_prefix_shear = group_input.outputs[
        chain_global_prefix_shear_socket.identifier]
    chain_global_suffix_active = group_input.outputs[
        chain_global_suffix_active_socket.identifier]
    chain_global_suffix_mask = group_input.outputs[
        chain_global_suffix_mask_socket.identifier]
    chain_global_suffix_pre_shear = group_input.outputs[
        chain_global_suffix_pre_shear_socket.identifier]
    chain_global_suffix_post_shear = group_input.outputs[
        chain_global_suffix_post_shear_socket.identifier]
    chain_global_suffix_twist = group_input.outputs[
        chain_global_suffix_twist_socket.identifier]
    chain_global_suffix_taper = group_input.outputs[
        chain_global_suffix_taper_socket.identifier]
    chain_global_suffix_shear = group_input.outputs[
        chain_global_suffix_shear_socket.identifier]
    shear = group_input.outputs[shear_socket.identifier]
    ffd_offsets = tuple(
        group_input.outputs[socket.identifier] for socket in ffd_sockets)

    source_relative = vector_math("SUBTRACT", position.outputs[0], center)
    source_raw_local_position = rotate(
        source_relative, rotation, invert=True)
    is_chained = compare("INT", "EQUAL", mode, MODE_VALUES["CHAINED"])
    size_x, size_y, size_z = separate(size)

    registrar.use("PROFILE")
    half_x = math_node("MULTIPLY", math_node("ABSOLUTE", size_x), 0.5)
    half_y = math_node("MULTIPLY", math_node("ABSOLUTE", size_y), 0.5)
    half_z = math_node("MULTIPLY", math_node("ABSOLUTE", size_z), 0.5)
    non_root_chain = boolean(
        "AND", is_chained, boolean("NOT", chain_root_stage, False))
    _source_raw_x, source_raw_y, _source_raw_z = separate(
        source_raw_local_position)
    incoming_coordinate = registrar.new("GeometryNodeInputNamedAttribute")
    incoming_coordinate.name = "SDH Chain Coordinate Input"
    incoming_coordinate.label = "Original Chain Coordinate"
    incoming_coordinate.data_type = "FLOAT"
    _feed(
        node_group, chain_domain_attribute,
        incoming_coordinate.inputs["Name"])
    source_coordinate = switch(
        "FLOAT", chain_root_stage,
        incoming_coordinate.outputs["Attribute"], source_raw_y)

    def mask_has(mask, bit):
        quotient = math_node("DIVIDE", mask, float(bit))
        whole = math_node("FLOOR", quotient)
        remainder = math_node("MODULO", whole, 2.0)
        return compare("FLOAT", "GREATER_THAN", remainder, 0.5)

    # Operations authored before Bend cannot be interleaved once per segment:
    # P2*B2*P1*B1 is not the source stack B2*B1*P2*P1. Evaluate the immutable
    # source baseline once in the original full-cage frame, then let each cage
    # apply only its editable delta before the local Bend block.
    global_prefix_source_y = math_node(
        "ADD", source_coordinate, chain_global_prefix_offset)
    global_prefix_half_y = math_node(
        "MULTIPLY", math_node(
            "ABSOLUTE", chain_global_prefix_length), 0.5)
    global_prefix_negative_half_y = math_node(
        "MULTIPLY", global_prefix_half_y, -1.0)
    global_prefix_is_top = compare(
        "INT", "EQUAL", chain_global_prefix_origin, ORIGIN_VALUES["TOP"])
    global_prefix_is_bottom = compare(
        "INT", "EQUAL", chain_global_prefix_origin,
        ORIGIN_VALUES["BOTTOM"])
    global_prefix_is_symmetric = compare(
        "INT", "EQUAL", chain_global_prefix_origin,
        ORIGIN_VALUES["SYMMETRIC"])
    global_prefix_origin_y = switch(
        "FLOAT", global_prefix_is_top,
        switch(
            "FLOAT", global_prefix_is_bottom,
            0.0, global_prefix_negative_half_y),
        global_prefix_half_y,
    )
    global_prefix_distance = math_node(
        "SUBTRACT", global_prefix_source_y, global_prefix_origin_y)
    global_prefix_lower = math_node(
        "SUBTRACT", global_prefix_negative_half_y, global_prefix_origin_y)
    global_prefix_upper = math_node(
        "SUBTRACT", global_prefix_half_y, global_prefix_origin_y)
    global_prefix_evaluated = math_node(
        "MINIMUM",
        math_node("MAXIMUM", global_prefix_distance, global_prefix_lower),
        global_prefix_upper,
    )
    global_prefix_profile_distance = switch(
        "FLOAT", global_prefix_is_symmetric,
        global_prefix_evaluated,
        math_node("ABSOLUTE", global_prefix_evaluated),
    )
    global_prefix_profile = math_node(
        "DIVIDE", global_prefix_profile_distance,
        chain_global_prefix_length)
    global_prefix_relative = vector_math(
        "SUBTRACT", position.outputs[0], chain_global_prefix_center)
    global_prefix_local = rotate(
        global_prefix_relative, chain_global_prefix_rotation, invert=True)
    raw_prefix_x, raw_prefix_y, raw_prefix_z = separate(global_prefix_local)
    global_profile_t = math_node(
        "MINIMUM",
        math_node(
            "MAXIMUM",
            math_node(
                "DIVIDE",
                math_node(
                    "ADD", global_prefix_source_y, global_prefix_half_y),
                chain_global_prefix_length,
            ),
            0.0,
        ),
        1.0,
    )
    bottom_profile_x, _bottom_profile_y, bottom_profile_z = separate(
        chain_global_profile_bottom_scale)
    top_profile_x, _top_profile_y, top_profile_z = separate(
        chain_global_profile_top_scale)
    bottom_offset_x, _bottom_offset_y, bottom_offset_z = separate(
        chain_global_profile_bottom_offset)
    top_offset_x, _top_offset_y, top_offset_z = separate(
        chain_global_profile_top_offset)

    def profile_mix(lower, upper):
        return math_node(
            "ADD",
            lower,
            math_node(
                "MULTIPLY",
                math_node("SUBTRACT", upper, lower),
                global_profile_t,
            ),
        )

    global_profiled_local = combine(
        math_node(
            "ADD",
            math_node(
                "MULTIPLY", raw_prefix_x,
                profile_mix(bottom_profile_x, top_profile_x)),
            profile_mix(bottom_offset_x, top_offset_x),
        ),
        raw_prefix_y,
        math_node(
            "ADD",
            math_node(
                "MULTIPLY", raw_prefix_z,
                profile_mix(bottom_profile_z, top_profile_z)),
            profile_mix(bottom_offset_z, top_offset_z),
        ),
    )
    prefix_profiled = switch(
        "VECTOR", chain_global_profile_active,
        global_prefix_local, global_profiled_local)

    def ordered_linear_stack(
            value, operation_mask, profile_value, distance_value,
            twist_value, taper_value, stretch_value):
        value_x, value_y, value_z = separate(value)
        twist_angle = math_node("MULTIPLY", twist_value, profile_value)
        twist_cosine = math_node("COSINE", twist_angle)
        twist_sine = math_node("SINE", twist_angle)
        twisted = combine(
            math_node(
                "SUBTRACT",
                math_node("MULTIPLY", twist_cosine, value_x),
                math_node("MULTIPLY", twist_sine, value_z)),
            value_y,
            math_node(
                "ADD",
                math_node("MULTIPLY", twist_sine, value_x),
                math_node("MULTIPLY", twist_cosine, value_z)),
        )
        after_twist = switch(
            "VECTOR", mask_has(operation_mask, DEFORM_BITS["TWIST"]),
            value, twisted)
        taper_x, taper_y, taper_z = separate(after_twist)
        taper_scale = math_node(
            "ADD", 1.0,
            math_node("MULTIPLY", taper_value, profile_value))
        tapered = combine(
            math_node("MULTIPLY", taper_x, taper_scale),
            taper_y,
            math_node("MULTIPLY", taper_z, taper_scale),
        )
        after_taper = switch(
            "VECTOR", mask_has(operation_mask, DEFORM_BITS["TAPER"]),
            after_twist, tapered)
        stretch_x, stretch_y, stretch_z = separate(after_taper)
        stretch_scale = math_node("ADD", 1.0, stretch_value)
        stretch_safe = math_node(
            "MAXIMUM", math_node("ABSOLUTE", stretch_scale), EPSILON)
        stretch_volume = switch(
            "FLOAT", preserve_volume,
            1.0, math_node("POWER", stretch_safe, -0.5))
        stretched = combine(
            math_node("MULTIPLY", stretch_x, stretch_volume),
            math_node(
                "ADD", stretch_y,
                math_node("MULTIPLY", distance_value, stretch_value)),
            math_node("MULTIPLY", stretch_z, stretch_volume),
        )
        return switch(
            "VECTOR", mask_has(operation_mask, DEFORM_BITS["STRETCH"]),
            after_taper, stretched)

    prefix_before_shear = ordered_linear_stack(
        prefix_profiled,
        chain_global_prefix_pre_shear,
        global_prefix_profile,
        global_prefix_evaluated,
        chain_global_prefix_twist,
        chain_global_prefix_taper,
        chain_global_prefix_stretch,
    )
    prefix_shear_x, prefix_shear_y, prefix_shear_z = separate(
        prefix_before_shear)
    prefix_shear_factor_x, _prefix_shear_y, prefix_shear_factor_z = separate(
        chain_global_prefix_shear)
    prefix_sheared = combine(
        math_node(
            "ADD", prefix_shear_x,
            math_node(
                "MULTIPLY", prefix_shear_factor_x,
                global_prefix_profile_distance)),
        prefix_shear_y,
        math_node(
            "ADD", prefix_shear_z,
            math_node(
                "MULTIPLY", prefix_shear_factor_z,
                global_prefix_profile_distance)),
    )
    prefix_after_shear = switch(
        "VECTOR", mask_has(chain_global_prefix_mask, DEFORM_BITS["SHEAR"]),
        prefix_before_shear, prefix_sheared)
    prefix_before_bend = ordered_linear_stack(
        prefix_after_shear,
        chain_global_prefix_post_shear,
        global_prefix_profile,
        global_prefix_evaluated,
        chain_global_prefix_twist,
        chain_global_prefix_taper,
        chain_global_prefix_stretch,
    )
    prefix_bend_x, prefix_bend_y, prefix_bend_z = separate(
        prefix_before_bend)
    prefix_bend_cos_direction = math_node(
        "COSINE", chain_global_prefix_direction)
    prefix_bend_sin_direction = math_node(
        "SINE", chain_global_prefix_direction)
    prefix_bend_u = math_node(
        "ADD",
        math_node(
            "MULTIPLY", prefix_bend_cos_direction, prefix_bend_x),
        math_node(
            "MULTIPLY", prefix_bend_sin_direction, prefix_bend_z),
    )
    prefix_bend_v = math_node(
        "ADD",
        math_node(
            "MULTIPLY",
            math_node("MULTIPLY", prefix_bend_sin_direction, -1.0),
            prefix_bend_x),
        math_node(
            "MULTIPLY", prefix_bend_cos_direction, prefix_bend_z),
    )
    prefix_bend_is_zero = compare(
        "FLOAT", "LESS_THAN",
        math_node("ABSOLUTE", chain_global_prefix_bend), EPSILON)
    prefix_bend_safe_strength = switch(
        "FLOAT", prefix_bend_is_zero,
        chain_global_prefix_bend, EPSILON)
    prefix_bend_curvature = math_node(
        "DIVIDE", prefix_bend_safe_strength,
        chain_global_prefix_length)
    prefix_bend_negative_side = boolean(
        "AND", global_prefix_is_symmetric,
        compare(
            "FLOAT", "LESS_THAN", global_prefix_source_y, 0.0))
    prefix_bend_effective_curvature = switch(
        "FLOAT", prefix_bend_negative_side,
        prefix_bend_curvature,
        math_node("MULTIPLY", prefix_bend_curvature, -1.0),
    )
    prefix_bend_radius = math_node(
        "DIVIDE", 1.0, prefix_bend_effective_curvature)
    prefix_bend_theta = math_node(
        "MULTIPLY", prefix_bend_effective_curvature,
        global_prefix_evaluated)
    prefix_bend_cosine = math_node("COSINE", prefix_bend_theta)
    prefix_bend_sine = math_node("SINE", prefix_bend_theta)
    prefix_bend_radial = math_node(
        "ADD", prefix_bend_radius, prefix_bend_u)
    prefix_bend_outside = math_node(
        "SUBTRACT", global_prefix_distance, global_prefix_evaluated)
    prefix_bent_u = math_node(
        "SUBTRACT",
        math_node(
            "SUBTRACT",
            math_node(
                "MULTIPLY", prefix_bend_radial, prefix_bend_cosine),
            prefix_bend_radius),
        math_node(
            "MULTIPLY", prefix_bend_sine, prefix_bend_outside),
    )
    prefix_bent_authored_y = math_node(
        "ADD",
        math_node(
            "ADD", global_prefix_origin_y,
            math_node(
                "MULTIPLY", prefix_bend_radial, prefix_bend_sine)),
        math_node(
            "MULTIPLY", prefix_bend_cosine, prefix_bend_outside),
    )
    prefix_bent = combine(
        math_node(
            "SUBTRACT",
            math_node(
                "MULTIPLY", prefix_bend_cos_direction, prefix_bent_u),
            math_node(
                "MULTIPLY", prefix_bend_sin_direction, prefix_bend_v)),
        math_node(
            "ADD", prefix_bend_y,
            math_node(
                "SUBTRACT", prefix_bent_authored_y,
                global_prefix_source_y)),
        math_node(
            "ADD",
            math_node(
                "MULTIPLY", prefix_bend_sin_direction, prefix_bent_u),
            math_node(
                "MULTIPLY", prefix_bend_cos_direction, prefix_bend_v)),
    )
    prefix_bend_value = switch(
        "VECTOR", prefix_bend_is_zero,
        prefix_bent, prefix_before_bend)
    prefix_result_local = switch(
        "VECTOR",
        mask_has(chain_global_prefix_mask, DEFORM_BITS["BEND"]),
        prefix_before_bend,
        prefix_bend_value,
    )
    global_prefixed_position = vector_math(
        "ADD",
        rotate(
            prefix_result_local, chain_global_prefix_rotation, invert=False),
        chain_global_prefix_center,
    )
    global_prefix_apply = boolean(
        "AND",
        boolean("AND", is_chained, chain_root_stage),
        boolean(
            "AND",
            boolean(
                "OR", chain_global_prefix_active,
                chain_global_profile_active),
            stage_enabled,
        ),
    )
    stage_input_position = switch(
        "VECTOR", global_prefix_apply,
        position.outputs[0], global_prefixed_position)
    relative = vector_math("SUBTRACT", stage_input_position, center)
    raw_local_position = rotate(relative, rotation, invert=True)
    local_position = raw_local_position
    _raw_x, raw_y, _raw_z = separate(raw_local_position)
    chain_ownership_y = math_node(
        "SUBTRACT",
        math_node("SUBTRACT", source_coordinate, chain_source_start),
        half_y,
    )
    ownership_y = switch(
        "FLOAT", is_chained, raw_y, chain_ownership_y)
    chain_delta = vector_math(
        "SUBTRACT", raw_local_position, chain_input_pivot)
    chain_coordinate_x = vector_math(
        "DOT_PRODUCT", chain_delta, chain_input_inverse_x)
    chain_coordinate_y = math_node(
        "SUBTRACT",
        vector_math("DOT_PRODUCT", chain_delta, chain_input_inverse_y),
        half_y,
    )
    chain_coordinate_z = vector_math(
        "DOT_PRODUCT", chain_delta, chain_input_inverse_z)
    chain_adjusted_position = combine(
        chain_coordinate_x,
        chain_coordinate_y,
        chain_coordinate_z,
    )
    local_position = switch(
        "VECTOR", non_root_chain, raw_local_position,
        chain_adjusted_position)
    x, y, z = separate(local_position)
    # A downstream stage receives an already-deformed spatial Y.  For mixed
    # Bend stacks, carry the authored source coordinate so the profile does
    # not feed upstream lateral motion back into Twist/Taper/Stretch. Pure
    # Bend keeps the post-frame local Y path.
    bend_mask = compare(
        "FLOAT", "GREATER_THAN",
        math_node("MODULO", deform_mask, 2.0), 0.5)
    mixed_bend = boolean(
        "AND", bend_mask,
        compare("INT", "GREATER_THAN", deform_mask, 2))
    mixed_chain = boolean("AND", is_chained, mixed_bend)
    chain_authored_y = math_node(
        "SUBTRACT",
        source_coordinate,
        math_node("ADD", chain_source_start, half_y),
    )
    authored_y_input = switch(
        "FLOAT", mixed_chain, y, chain_authored_y)
    length = math_node("MAXIMUM", math_node("ABSOLUTE", size_y), EPSILON)
    frame_t_raw = math_node(
        "DIVIDE", math_node("ADD", authored_y_input, half_y), length)
    frame_t_clamped = math_node(
        "MINIMUM", math_node("MAXIMUM", frame_t_raw, 0.0), 1.0)
    is_unlimited = compare(
        "INT", "EQUAL", mode, MODE_VALUES["UNLIMITED"])
    frame_t = switch(
        "FLOAT", is_unlimited, frame_t_clamped, frame_t_raw)

    # Chain subdivision keeps per-stage profile values visible for authoring,
    # while the root's global profile inputs are the single source of truth
    # during evaluation.  Select identity local values whenever that global
    # path is active so GN cannot apply the profile twice.
    identity_profile = combine(1.0, 1.0, 1.0)
    identity_offset = combine(0.0, 0.0, 0.0)
    effective_top_scale = switch(
        "VECTOR", chain_global_profile_active, top_scale, identity_profile)
    effective_bottom_scale = switch(
        "VECTOR", chain_global_profile_active, bottom_scale, identity_profile)
    effective_top_offset = switch(
        "VECTOR", chain_global_profile_active, top_offset, identity_offset)
    effective_bottom_offset = switch(
        "VECTOR", chain_global_profile_active, bottom_offset, identity_offset)
    top_scale_x, _top_scale_y, top_scale_z = separate(effective_top_scale)
    bottom_scale_x, _bottom_scale_y, bottom_scale_z = separate(effective_bottom_scale)
    top_offset_x, _top_offset_y, top_offset_z = separate(effective_top_offset)
    bottom_offset_x, _bottom_offset_y, bottom_offset_z = separate(effective_bottom_offset)

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

    strength_is_zero = compare(
        "FLOAT", "LESS_THAN", math_node("ABSOLUTE", bend_strength), EPSILON)
    safe_strength = switch("FLOAT", strength_is_zero, bend_strength, 1.0)
    curvature = math_node("DIVIDE", bend_strength, length)
    radius = math_node("DIVIDE", length, safe_strength)

    is_bottom = compare("INT", "EQUAL", origin, ORIGIN_VALUES["BOTTOM"])
    is_top = compare("INT", "EQUAL", origin, ORIGIN_VALUES["TOP"])
    is_symmetric = compare(
        "INT", "EQUAL", origin, ORIGIN_VALUES["SYMMETRIC"])
    negative_half_y = math_node("MULTIPLY", half_y, -1.0)
    # Keep the GN frame identical to the Python reference evaluator. A chain
    # still connects its controllers from bottom to top, while Origin controls
    # the local deformation reference of each stage.
    configured_origin_y = switch(
        "FLOAT", is_top,
        switch("FLOAT", is_bottom, 0.0, negative_half_y),
        half_y,
    )
    origin_y = configured_origin_y
    distance = math_node("SUBTRACT", authored_y_input, origin_y)

    is_lower = compare("FLOAT", "LESS_THAN", authored_y_input, 0.0)
    symmetric_lower = boolean("AND", is_symmetric, is_lower)
    negative_curvature = math_node("MULTIPLY", curvature, -1.0)
    effective_curvature = switch(
        "FLOAT", symmetric_lower, curvature, negative_curvature)
    negative_radius = math_node("MULTIPLY", radius, -1.0)
    effective_radius = switch(
        "FLOAT", symmetric_lower, radius, negative_radius)

    lower_distance = math_node("SUBTRACT", negative_half_y, origin_y)
    upper_distance = math_node("SUBTRACT", half_y, origin_y)
    source_stage_eligible = compare(
        "FLOAT", "GREATER_EQUAL", source_coordinate,
        math_node(
            "SUBTRACT", chain_source_start, CHAIN_BOUNDARY_EPSILON))
    # Every upstream stage remains active for the complete downstream suffix.
    # Its clamped terminal profile carries the accumulated deformation into
    # the next cage; disabling it at the next source boundary would erase the
    # upstream contribution from later geometry.  Source-end metadata is kept
    # for diagnostics and future ownership work, but is not an eligibility
    # gate in the evaluator.
    stage_eligible = boolean(
        "OR", chain_root_stage, source_stage_eligible)
    clamped_distance = math_node(
        "MINIMUM",
        math_node("MAXIMUM", distance, lower_distance),
        upper_distance,
    )
    is_limited = compare("INT", "EQUAL", mode, MODE_VALUES["LIMITED"])
    is_within = compare("INT", "EQUAL", mode, MODE_VALUES["WITHIN_BOX"])
    normal_evaluated_distance = switch(
        "FLOAT", is_limited, distance, clamped_distance)
    boundary_outside_distance = math_node(
        "SUBTRACT", distance, clamped_distance)
    normal_outside_distance = switch(
        "FLOAT", is_limited, 0.0, boundary_outside_distance)
    downstream_outside_distance = math_node(
        "MAXIMUM",
        math_node("SUBTRACT", distance, upper_distance),
        0.0,
    )
    chained_outside_distance = switch(
        "FLOAT", chain_root_stage,
        downstream_outside_distance, boundary_outside_distance)
    evaluated_distance = switch(
        "FLOAT", is_chained, normal_evaluated_distance, clamped_distance)
    outside_distance = switch(
        "FLOAT", is_chained, normal_outside_distance,
        chained_outside_distance)

    # A chain gap is an unowned source interval.  Carry the preceding end
    # frame through it rigidly: Bend keeps its terminal tangent, while
    # Twist/Taper/Shear and end profiles keep their terminal values.  The next
    # cage starts deforming only at its own source boundary.
    profile_distance_input = evaluated_distance
    bend_evaluated_distance = profile_distance_input
    bend_outside_distance = outside_distance
    profile_distance = switch(
        "FLOAT", is_symmetric, profile_distance_input,
        math_node("ABSOLUTE", profile_distance_input),
    )
    profile = math_node("DIVIDE", profile_distance, length)

    def mask_enabled(bit):
        return mask_has(deform_mask, bit)

    bend_enabled = mask_enabled(DEFORM_BITS["BEND"])
    twist_enabled = mask_enabled(DEFORM_BITS["TWIST"])
    taper_enabled = mask_enabled(DEFORM_BITS["TAPER"])
    stretch_enabled = mask_enabled(DEFORM_BITS["STRETCH"])
    shear_enabled = mask_enabled(DEFORM_BITS["SHEAR"])
    ffd_enabled = mask_enabled(DEFORM_BITS["FFD"])
    curve_enabled = mask_enabled(DEFORM_BITS["CURVE"])

    registrar.use("PROFILE")
    order_start = reroute(
        DEFORM_ORDER_START_NODE, "Deform Order Start", (0.0, 0.0))
    registrar.use("MODE")
    order_end = reroute(
        DEFORM_ORDER_END_NODE, "Deform Order End", (0.0, 0.0))
    links.new(framed_position, order_start.inputs[0])

    block_inputs = {}
    block_outputs = {}
    for name in DEFORM_ORDER:
        registrar.use(name)
        block_inputs[name] = reroute(
            DEFORM_BLOCK_INPUT_NODE[name], f"{name.title()} Input",
            (0.0, 0.0))
        block_outputs[name] = reroute(
            DEFORM_BLOCK_OUTPUT_NODE[name], f"{name.title()} Output",
            (0.0, 0.0))
    # Blender 5.2 requires a dynamic reroute to receive a typed source before
    # its output can feed a VECTOR socket. These temporary links type every
    # input; relink_deform_order replaces them with the real pipeline links.
    for block_input in block_inputs.values():
        links.new(framed_position, block_input.inputs[0])

    # Bend is modular: transverse coordinates come from the preceding block,
    # while the authored axial delta remains tied to the original cage frame.
    registrar.use("BEND")
    bend_input = block_inputs["BEND"].outputs[0]
    bend_current_x, bend_current_y, bend_current_z = separate(bend_input)
    cos_direction = math_node("COSINE", bend_direction)
    sin_direction = math_node("SINE", bend_direction)
    negative_sin_direction = math_node("MULTIPLY", sin_direction, -1.0)
    bend_u = math_node(
        "ADD",
        math_node("MULTIPLY", cos_direction, bend_current_x),
        math_node("MULTIPLY", sin_direction, bend_current_z),
    )
    bend_v = math_node(
        "ADD",
        math_node("MULTIPLY", negative_sin_direction, bend_current_x),
        math_node("MULTIPLY", cos_direction, bend_current_z),
    )
    bend_theta = math_node(
        "MULTIPLY", effective_curvature, bend_evaluated_distance)
    bend_cosine = math_node("COSINE", bend_theta)
    bend_sine = math_node("SINE", bend_theta)
    bend_radial = math_node("ADD", effective_radius, bend_u)
    authored_bent_u = math_node(
        "SUBTRACT",
        math_node(
            "SUBTRACT",
            math_node("MULTIPLY", bend_radial, bend_cosine),
            effective_radius,
        ),
        math_node("MULTIPLY", bend_sine, bend_outside_distance),
    )
    authored_bent_y = math_node(
        "ADD",
        math_node(
            "ADD", origin_y,
            math_node("MULTIPLY", bend_radial, bend_sine),
        ),
        math_node("MULTIPLY", bend_cosine, bend_outside_distance),
    )
    bent_x = math_node(
        "SUBTRACT",
        math_node("MULTIPLY", cos_direction, authored_bent_u),
        math_node("MULTIPLY", sin_direction, bend_v),
    )
    bent_y = math_node(
        "ADD", bend_current_y,
        math_node("SUBTRACT", authored_bent_y, authored_y_input),
    )
    bent_z = math_node(
        "ADD",
        math_node("MULTIPLY", sin_direction, authored_bent_u),
        math_node("MULTIPLY", cos_direction, bend_v),
    )
    bent_raw = combine(bent_x, bent_y, bent_z)
    bent_local = switch(
        "VECTOR", strength_is_zero, bent_raw, bend_input)
    bend_result = switch(
        "VECTOR", bend_enabled, bend_input, bent_local)
    links.new(bend_result, block_outputs["BEND"].inputs[0])

    registrar.use("TWIST")
    twist_angle = math_node("MULTIPLY", twist_strength, profile)
    twist_cosine = math_node("COSINE", twist_angle)
    twist_sine = math_node("SINE", twist_angle)
    twist_input = block_inputs["TWIST"].outputs[0]
    twist_x, twist_y, twist_z = separate(twist_input)
    twisted_x = math_node(
        "SUBTRACT",
        math_node("MULTIPLY", twist_cosine, twist_x),
        math_node("MULTIPLY", twist_sine, twist_z),
    )
    twisted_z = math_node(
        "ADD",
        math_node("MULTIPLY", twist_sine, twist_x),
        math_node("MULTIPLY", twist_cosine, twist_z),
    )
    twisted_local = combine(twisted_x, twist_y, twisted_z)
    twist_result = switch(
        "VECTOR", twist_enabled, twist_input, twisted_local)
    links.new(twist_result, block_outputs["TWIST"].inputs[0])

    registrar.use("TAPER")
    taper_scale = math_node(
        "ADD", 1.0, math_node("MULTIPLY", taper_factor, profile))
    taper_input = block_inputs["TAPER"].outputs[0]
    taper_x, taper_y, taper_z = separate(taper_input)
    tapered_local = combine(
        math_node("MULTIPLY", taper_x, taper_scale),
        taper_y,
        math_node("MULTIPLY", taper_z, taper_scale),
    )
    taper_result = switch(
        "VECTOR", taper_enabled, taper_input, tapered_local)
    links.new(taper_result, block_outputs["TAPER"].inputs[0])

    registrar.use("STRETCH")
    stretch_scale = math_node("ADD", 1.0, stretch_factor)
    # Stretch is an axial scale, so preserve-volume compensation must use the
    # same constant scale at every point in a stage.  A profile-dependent
    # factor makes each chained stage change its transverse scale from one end
    # to the other, producing visible seams and cumulative drift after
    # subdivision.  The non-chained path already uses ``stretch_scale``;
    # keeping the chained path constant preserves the source cross-section.
    chained_volume_scale = stretch_scale
    volume_stretch_scale = switch(
        "FLOAT", is_chained, stretch_scale, chained_volume_scale)
    authored_stretched_y = math_node(
        "ADD",
        math_node(
            "ADD", origin_y,
            math_node("MULTIPLY", evaluated_distance, stretch_scale),
        ),
        # Geometry outside this cage keeps the endpoint displacement, but the
        # unowned gap itself is not stretched.
        outside_distance,
    )
    stretch_input = block_inputs["STRETCH"].outputs[0]
    stretch_x, stretch_y, stretch_z = separate(stretch_input)
    stretched_y = math_node(
        "ADD", stretch_y,
        math_node("SUBTRACT", authored_stretched_y, authored_y_input))
    safe_stretch = math_node(
        "MAXIMUM", math_node("ABSOLUTE", volume_stretch_scale), EPSILON)
    volume_scale = switch(
        "FLOAT", preserve_volume, 1.0,
        math_node("POWER", safe_stretch, -0.5),
    )
    stretched_local = combine(
        math_node("MULTIPLY", stretch_x, volume_scale),
        stretched_y,
        math_node("MULTIPLY", stretch_z, volume_scale),
    )
    stretch_result = switch(
        "VECTOR", stretch_enabled, stretch_input, stretched_local)
    links.new(stretch_result, block_outputs["STRETCH"].inputs[0])

    registrar.use("SHEAR")
    shear_x, _shear_y, shear_z = separate(shear)
    shear_input = block_inputs["SHEAR"].outputs[0]
    shear_input_x, shear_input_y, shear_input_z = separate(shear_input)
    sheared_local = combine(
        math_node(
            "ADD", shear_input_x,
            math_node("MULTIPLY", shear_x, profile_distance)),
        shear_input_y,
        math_node(
            "ADD", shear_input_z,
            math_node("MULTIPLY", shear_z, profile_distance)),
    )
    shear_result = switch(
        "VECTOR", shear_enabled, shear_input, sheared_local)
    links.new(shear_result, block_outputs["SHEAR"].inputs[0])

    registrar.use("FFD")
    ffd_input = block_inputs["FFD"].outputs[0]
    safe_size_x = math_node("MAXIMUM", math_node("ABSOLUTE", size_x), EPSILON)
    safe_size_z = math_node("MAXIMUM", math_node("ABSOLUTE", size_z), EPSILON)
    ffd_u_raw = math_node(
        "ADD", math_node("DIVIDE", x, safe_size_x), 0.5)
    ffd_w_raw = math_node(
        "ADD", math_node("DIVIDE", z, safe_size_z), 0.5)
    ffd_u_clamped = math_node(
        "MINIMUM", math_node("MAXIMUM", ffd_u_raw, 0.0), 1.0)
    ffd_w_clamped = math_node(
        "MINIMUM", math_node("MAXIMUM", ffd_w_raw, 0.0), 1.0)
    ffd_u = switch("FLOAT", is_unlimited, ffd_u_clamped, ffd_u_raw)
    ffd_v = frame_t
    ffd_w = switch("FLOAT", is_unlimited, ffd_w_clamped, ffd_w_raw)
    ffd_one_minus_u = math_node("SUBTRACT", 1.0, ffd_u)
    ffd_one_minus_v = math_node("SUBTRACT", 1.0, ffd_v)
    ffd_one_minus_w = math_node("SUBTRACT", 1.0, ffd_w)
    ffd_displacement = None
    for offset_socket, (_label, x_sign, y_sign, z_sign) in zip(
            ffd_offsets, FFD_CORNERS):
        x_weight = ffd_u if x_sign > 0.0 else ffd_one_minus_u
        y_weight = ffd_v if y_sign > 0.0 else ffd_one_minus_v
        z_weight = ffd_w if z_sign > 0.0 else ffd_one_minus_w
        weight = math_node(
            "MULTIPLY",
            math_node("MULTIPLY", x_weight, y_weight),
            z_weight,
        )
        weighted_offset = vector_math("SCALE", offset_socket, weight)
        ffd_displacement = (
            weighted_offset if ffd_displacement is None else
            vector_math("ADD", ffd_displacement, weighted_offset)
        )
    ffd_local = vector_math("ADD", ffd_input, ffd_displacement)
    ffd_result = switch("VECTOR", ffd_enabled, ffd_input, ffd_local)
    links.new(ffd_result, block_outputs["FFD"].inputs[0])

    # Curve cage: sample a managed Bezier guide and reconstruct each source
    # cross-section in its minimum-twist frame.  The guide and station objects
    # are authored in cage-local coordinates, so this operation remains fully
    # composable with the existing final cage-to-object transform.
    registrar.use("CURVE")
    curve_input = block_inputs["CURVE"].outputs[0]
    curve_input_x, _curve_input_y, curve_input_z = separate(curve_input)

    guide_info = registrar.new("GeometryNodeObjectInfo")
    guide_info.label = "Managed Bezier Guide"
    guide_info.transform_space = "ORIGINAL"
    _feed(node_group, curve_guide_object_input, guide_info.inputs["Object"])
    guide_geometry = guide_info.outputs["Geometry"]

    guide_length_node = registrar.new("GeometryNodeCurveLength")
    guide_length_node.label = "Guide Arc Length"
    _feed(node_group, guide_geometry, guide_length_node.inputs["Curve"])
    guide_length = guide_length_node.outputs["Length"]
    safe_guide_length = math_node(
        "MAXIMUM", math_node("ABSOLUTE", guide_length), EPSILON)

    # Cage size and center are the immutable source parameter domain.  The two
    # Curve Range inputs are only an effect mask within that domain: never
    # normalize the remaining interval back to 0..1, otherwise an inward
    # boundary compresses the remaining object across the complete guide.
    curve_distance = math_node("ADD", authored_y_input, half_y)
    curve_range_start_safe = math_node(
        "MINIMUM", math_node("MAXIMUM", curve_range_start, 0.0), 1.0,
        "Curve Range Start Clamped")
    curve_range_end_safe = math_node(
        "MINIMUM", math_node("MAXIMUM", curve_range_end, 0.0), 1.0,
        "Curve Range End Clamped")
    curve_range_lower = math_node(
        "MINIMUM", curve_range_start_safe, curve_range_end_safe,
        "Curve Range Lower")
    curve_range_upper = math_node(
        "MAXIMUM", curve_range_start_safe, curve_range_end_safe,
        "Curve Range Upper")
    curve_range_lower_distance = math_node(
        "MULTIPLY", curve_range_lower, length,
        "Curve Range Lower Distance")
    curve_range_upper_distance = math_node(
        "MULTIPLY", curve_range_upper, length,
        "Curve Range Upper Distance")
    curve_below_range = compare(
        "FLOAT", "LESS_THAN", curve_distance,
        curve_range_lower_distance)
    curve_above_range = compare(
        "FLOAT", "GREATER_THAN", curve_distance,
        curve_range_upper_distance)
    curve_outside_range = boolean(
        "OR", curve_below_range, curve_above_range)
    curve_limited = compare(
        "INT", "EQUAL", curve_boundary_mode,
        CURVE_MODE_VALUES["LIMITED"])
    curve_within_box = compare(
        "INT", "EQUAL", curve_boundary_mode,
        CURVE_MODE_VALUES["WITHIN_BOX"])
    curve_range_distance = math_node(
        "MINIMUM",
        math_node(
            "MAXIMUM", curve_distance, curve_range_lower_distance),
        curve_range_upper_distance,
        "Curve Range Distance")
    # Limited samples the nearest effect-boundary frame.  The original axial
    # residual is restored along that frame's tangent below; this is what
    # prevents all excluded cross-sections from collapsing onto one point.
    curve_sample_distance = switch(
        "FLOAT", curve_limited, curve_distance, curve_range_distance)
    curve_factor_raw = math_node(
        "DIVIDE", curve_sample_distance, length)
    curve_factor_clamped = math_node(
        "MINIMUM", math_node("MAXIMUM", curve_factor_raw, 0.0), 1.0)
    curve_factor_wrapped = math_node(
        "FLOORED_MODULO", curve_factor_raw, 1.0,
        "Wrapped Cage Factor")
    curve_unlimited = compare(
        "INT", "EQUAL", curve_boundary_mode,
        CURVE_MODE_VALUES["UNLIMITED"])
    curve_wraps = boolean("AND", curve_closed, curve_unlimited)
    curve_factor = switch(
        "FLOAT", curve_wraps, curve_factor_clamped, curve_factor_wrapped)
    guide_distance_clamped = math_node(
        "MINIMUM", math_node("MAXIMUM", curve_sample_distance, 0.0),
        safe_guide_length)
    guide_distance_wrapped = math_node(
        "FLOORED_MODULO", curve_sample_distance, safe_guide_length,
        "Wrapped Guide Distance")
    guide_distance = switch(
        "FLOAT", curve_wraps,
        guide_distance_clamped, guide_distance_wrapped)
    preserve_station_factor = math_node(
        "DIVIDE", guide_distance, safe_guide_length)
    curve_is_preserve = compare(
        "INT", "EQUAL", curve_length_mode,
        CURVE_LENGTH_VALUES["PRESERVE"])
    curve_is_fit = compare("INT", "EQUAL", curve_length_mode, 2)
    station_factor = switch(
        "FLOAT", curve_is_preserve, curve_factor, preserve_station_factor)

    guide_radius_attribute = registrar.new(
        "GeometryNodeInputNamedAttribute")
    guide_radius_attribute.label = "Guide Radius"
    guide_radius_attribute.data_type = "FLOAT"
    _feed(node_group, "radius", guide_radius_attribute.inputs["Name"])
    guide_radius_value = switch(
        "FLOAT", guide_radius_attribute.outputs["Exists"], 1.0,
        guide_radius_attribute.outputs["Attribute"])

    def sample_guide(sample_mode, coordinate, label):
        sample = registrar.new("GeometryNodeSampleCurve")
        sample.label = label
        sample.data_type = "FLOAT"
        sample.mode = sample_mode
        _feed(node_group, guide_geometry, sample.inputs["Curves"])
        _feed(node_group, guide_radius_value, sample.inputs["Value"])
        _feed(node_group, coordinate, sample.inputs[
            "Length" if sample_mode == "LENGTH" else "Factor"])
        return sample

    guide_by_factor = sample_guide(
        "FACTOR", curve_factor, "Sample Guide by Factor")
    guide_by_length = sample_guide(
        "LENGTH", guide_distance, "Sample Guide by Arc Length")
    guide_start = sample_guide("FACTOR", 0.0, "Guide Start Frame")

    # Edge extraction stores an immutable rest guide beside the editable
    # control guide. Sampling both at the same authored cage factor lets the
    # graph apply a differential frame transform: current * inverse(rest).
    # At bind time the frames are identical, so the source passes through
    # without the immediate jump caused by absolute curve mapping.
    rest_guide_info = registrar.new("GeometryNodeObjectInfo")
    rest_guide_info.label = "Curve Rest Guide"
    rest_guide_info.transform_space = "ORIGINAL"
    _feed(
        node_group, curve_rest_guide_object_input,
        rest_guide_info.inputs["Object"])
    rest_guide_geometry = rest_guide_info.outputs["Geometry"]
    rest_radius_attribute = registrar.new(
        "GeometryNodeInputNamedAttribute")
    rest_radius_attribute.label = "Rest Guide Radius"
    rest_radius_attribute.data_type = "FLOAT"
    _feed(node_group, "radius", rest_radius_attribute.inputs["Name"])
    rest_radius_value = switch(
        "FLOAT", rest_radius_attribute.outputs["Exists"], 1.0,
        rest_radius_attribute.outputs["Attribute"])

    rest_by_factor = registrar.new("GeometryNodeSampleCurve")
    rest_by_factor.label = "Sample Rest Guide by Factor"
    rest_by_factor.data_type = "FLOAT"
    rest_by_factor.mode = "FACTOR"
    _feed(node_group, rest_guide_geometry, rest_by_factor.inputs["Curves"])
    _feed(node_group, rest_radius_value, rest_by_factor.inputs["Value"])
    _feed(node_group, curve_factor, rest_by_factor.inputs["Factor"])

    sampled_position = switch(
        "VECTOR", curve_is_preserve,
        guide_by_factor.outputs["Position"],
        guide_by_length.outputs["Position"])
    sampled_tangent = switch(
        "VECTOR", curve_is_preserve,
        guide_by_factor.outputs["Tangent"],
        guide_by_length.outputs["Tangent"])
    sampled_normal = switch(
        "VECTOR", curve_is_preserve,
        guide_by_factor.outputs["Normal"],
        guide_by_length.outputs["Normal"])
    sampled_radius = switch(
        "FLOAT", curve_is_preserve,
        guide_by_factor.outputs["Value"],
        guide_by_length.outputs["Value"])

    fit_ratio = math_node("DIVIDE", length, safe_guide_length)
    fitted_position = vector_math(
        "ADD", guide_start.outputs["Position"],
        vector_math(
            "SCALE",
            vector_math(
                "SUBTRACT", guide_by_factor.outputs["Position"],
                guide_start.outputs["Position"]),
            fit_ratio))
    centerline = switch(
        "VECTOR", curve_is_fit, sampled_position, fitted_position)

    def normalized_vector(value, label):
        node = registrar.new("ShaderNodeVectorMath")
        node.operation = "NORMALIZE"
        node.label = label
        _feed(node_group, value, node.inputs[0])
        return node.outputs[0]

    curve_tangent = normalized_vector(sampled_tangent, "Guide Tangent")
    # Blender's minimum-twist curve normal starts on local +X for a straight
    # +Y guide. Treat that sampled normal as U, then derive W so the default
    # frame is exactly cage-local X/Y/Z instead of rotating the section 90°.
    curve_u_axis = normalized_vector(sampled_normal, "Guide U Axis")
    curve_w_axis = normalized_vector(
        vector_math("CROSS_PRODUCT", curve_u_axis, curve_tangent),
        "Guide W Axis")
    relative_current_tangent = normalized_vector(
        guide_by_factor.outputs["Tangent"], "Relative Current Tangent")
    relative_current_u_axis = normalized_vector(
        guide_by_factor.outputs["Normal"], "Relative Current U Axis")
    relative_current_w_axis = normalized_vector(
        vector_math(
            "CROSS_PRODUCT", relative_current_u_axis,
            relative_current_tangent),
        "Relative Current W Axis")
    relative_rest_tangent = normalized_vector(
        rest_by_factor.outputs["Tangent"], "Relative Rest Tangent")
    relative_rest_u_axis = normalized_vector(
        rest_by_factor.outputs["Normal"], "Relative Rest U Axis")
    relative_rest_w_axis = normalized_vector(
        vector_math(
            "CROSS_PRODUCT", relative_rest_u_axis, relative_rest_tangent),
        "Relative Rest W Axis")

    station_info = registrar.new("GeometryNodeObjectInfo")
    station_info.label = "Cross-section Stations"
    station_info.transform_space = "ORIGINAL"
    _feed(
        node_group, curve_station_object_input,
        station_info.inputs["Object"])
    station_curve = registrar.new("GeometryNodeMeshToCurve")
    station_curve.label = "Station Interpolation Curve"
    _feed(
        node_group, station_info.outputs["Geometry"],
        station_curve.inputs["Mesh"])

    def station_vector_attribute(name, default, label):
        attribute = registrar.new("GeometryNodeInputNamedAttribute")
        attribute.label = label
        attribute.data_type = "FLOAT_VECTOR"
        _feed(node_group, name, attribute.inputs["Name"])
        value = switch(
            "VECTOR", attribute.outputs["Exists"], default,
            attribute.outputs["Attribute"])
        sample = registrar.new("GeometryNodeSampleCurve")
        sample.label = f"Sample {label}"
        sample.data_type = "FLOAT_VECTOR"
        sample.mode = "FACTOR"
        _feed(
            node_group, station_curve.outputs["Curve"],
            sample.inputs["Curves"])
        _feed(node_group, value, sample.inputs["Value"])
        _feed(node_group, station_factor, sample.inputs["Factor"])
        return sample.outputs["Value"]

    def station_float_attribute(name, default, label):
        attribute = registrar.new("GeometryNodeInputNamedAttribute")
        attribute.label = label
        attribute.data_type = "FLOAT"
        _feed(node_group, name, attribute.inputs["Name"])
        value = switch(
            "FLOAT", attribute.outputs["Exists"], default,
            attribute.outputs["Attribute"])
        sample = registrar.new("GeometryNodeSampleCurve")
        sample.label = f"Sample {label}"
        sample.data_type = "FLOAT"
        sample.mode = "FACTOR"
        _feed(
            node_group, station_curve.outputs["Curve"],
            sample.inputs["Curves"])
        _feed(node_group, value, sample.inputs["Value"])
        _feed(node_group, station_factor, sample.inputs["Factor"])
        return sample.outputs["Value"]

    station_scale = station_vector_attribute(
        "sdh_scale", combine(1.0, 1.0, 1.0), "Station Scale")
    station_offset = station_vector_attribute(
        "sdh_offset", combine(0.0, 0.0, 0.0), "Station Offset")
    station_radius = station_float_attribute(
        "sdh_radius", 1.0, "Station Radius")
    station_twist = station_float_attribute(
        "sdh_twist", 0.0, "Station Twist")
    station_scale_u, _station_scale_y, station_scale_w = separate(
        station_scale)
    station_offset_u, _station_offset_y, station_offset_w = separate(
        station_offset)

    stretch_axial_scale = math_node(
        "DIVIDE", safe_guide_length, length)
    curve_axial_scale = switch(
        "FLOAT", curve_is_preserve, stretch_axial_scale, 1.0)
    curve_axial_scale = switch(
        "FLOAT", curve_is_fit, curve_axial_scale, 1.0)
    curve_volume_scale = math_node(
        "POWER",
        math_node("MAXIMUM", math_node(
            "ABSOLUTE", curve_axial_scale), EPSILON),
        -0.5)
    curve_cross_compensation = switch(
        "FLOAT", curve_preserve_volume, 1.0, curve_volume_scale)
    effective_curve_radius = math_node(
        "MULTIPLY",
        math_node(
            "MULTIPLY", sampled_radius,
            math_node("MAXIMUM", curve_global_radius, 0.0)),
        math_node(
            "MULTIPLY", math_node("MAXIMUM", station_radius, 0.0),
            curve_cross_compensation))
    effective_curve_twist = math_node(
        "ADD", curve_global_twist, station_twist)
    curve_twist_cosine = math_node("COSINE", effective_curve_twist)
    curve_twist_sine = math_node("SINE", effective_curve_twist)
    twisted_curve_u_axis = normalized_vector(
        vector_math(
            "SUBTRACT",
            vector_math("SCALE", curve_u_axis, curve_twist_cosine),
            vector_math("SCALE", curve_w_axis, curve_twist_sine)),
        "Twisted Guide U Axis")
    twisted_curve_w_axis = normalized_vector(
        vector_math("CROSS_PRODUCT", twisted_curve_u_axis, curve_tangent),
        "Twisted Guide W Axis")
    relative_twisted_u_axis = normalized_vector(
        vector_math(
            "SUBTRACT",
            vector_math(
                "SCALE", relative_current_u_axis, curve_twist_cosine),
            vector_math(
                "SCALE", relative_current_w_axis, curve_twist_sine)),
        "Relative Twisted Current U Axis")
    relative_twisted_w_axis = normalized_vector(
        vector_math(
            "CROSS_PRODUCT", relative_twisted_u_axis,
            relative_current_tangent),
        "Relative Twisted Current W Axis")
    relative_radius = math_node(
        "DIVIDE",
        guide_by_factor.outputs["Value"],
        math_node("MAXIMUM", rest_by_factor.outputs["Value"], EPSILON),
    )
    relative_effective_radius = math_node(
        "MULTIPLY",
        math_node(
            "MULTIPLY", relative_radius,
            math_node("MAXIMUM", curve_global_radius, 0.0)),
        math_node(
            "MULTIPLY", math_node("MAXIMUM", station_radius, 0.0),
            curve_cross_compensation))
    curve_u_coordinate = math_node(
        "ADD",
        math_node(
            "MULTIPLY", curve_input_x,
            math_node(
                "MULTIPLY", station_scale_u, effective_curve_radius)),
        station_offset_u)
    curve_w_coordinate = math_node(
        "ADD",
        math_node(
            "MULTIPLY", curve_input_z,
            math_node(
                "MULTIPLY", station_scale_w, effective_curve_radius)),
        station_offset_w)
    relative_rest_delta = vector_math(
        "SUBTRACT", curve_input, rest_by_factor.outputs["Position"])
    relative_rest_u_coordinate = vector_math(
        "DOT_PRODUCT", relative_rest_delta, relative_rest_u_axis)
    relative_rest_t_coordinate = vector_math(
        "DOT_PRODUCT", relative_rest_delta, relative_rest_tangent)
    relative_rest_w_coordinate = vector_math(
        "DOT_PRODUCT", relative_rest_delta, relative_rest_w_axis)
    relative_u_coordinate = math_node(
        "ADD",
        math_node(
            "MULTIPLY", relative_rest_u_coordinate,
            math_node(
                "MULTIPLY", station_scale_u, relative_effective_radius)),
        station_offset_u)
    relative_w_coordinate = math_node(
        "ADD",
        math_node(
            "MULTIPLY", relative_rest_w_coordinate,
            math_node(
                "MULTIPLY", station_scale_w, relative_effective_radius)),
        station_offset_w)
    relative_curve_local = vector_math(
        "ADD",
        vector_math(
            "ADD", guide_by_factor.outputs["Position"],
            vector_math(
                "SCALE", relative_twisted_u_axis, relative_u_coordinate)),
        vector_math(
            "ADD",
            vector_math(
                "SCALE", relative_twisted_w_axis, relative_w_coordinate),
            vector_math(
                "SCALE", relative_current_tangent,
                relative_rest_t_coordinate)))

    preserve_extension = math_node(
        "ADD",
        math_node("MINIMUM", curve_distance, 0.0),
        math_node(
            "MAXIMUM",
            math_node("SUBTRACT", curve_distance, safe_guide_length),
            0.0))
    cage_extension = math_node(
        "ADD",
        math_node("MINIMUM", curve_distance, 0.0),
        math_node(
            "MAXIMUM", math_node(
                "SUBTRACT", curve_distance, length), 0.0))
    non_preserve_extension = math_node(
        "MULTIPLY", cage_extension, curve_axial_scale)
    unrestricted_extension = switch(
        "FLOAT", curve_is_preserve,
        non_preserve_extension, preserve_extension)
    limited_preserve_extension = math_node(
        "ADD",
        math_node("MINIMUM", curve_sample_distance, 0.0),
        math_node(
            "MAXIMUM",
            math_node(
                "SUBTRACT", curve_sample_distance, safe_guide_length),
            0.0))
    limited_cage_extension = math_node(
        "ADD",
        math_node("MINIMUM", curve_sample_distance, 0.0),
        math_node(
            "MAXIMUM",
            math_node("SUBTRACT", curve_sample_distance, length),
            0.0))
    limited_non_preserve_extension = math_node(
        "MULTIPLY", limited_cage_extension, curve_axial_scale)
    limited_canonical_extension = switch(
        "FLOAT", curve_is_preserve,
        limited_non_preserve_extension, limited_preserve_extension)
    curve_open = boolean("NOT", curve_closed, None)
    open_unrestricted_extension = switch(
        "FLOAT", curve_open, 0.0, unrestricted_extension)
    limited_extension = math_node(
        "ADD", limited_canonical_extension,
        math_node(
            "SUBTRACT", curve_distance, curve_sample_distance),
        "Limited Rigid Continuation")
    endpoint_extension = switch(
        "FLOAT", curve_limited,
        open_unrestricted_extension, limited_extension)

    curve_local = vector_math(
        "ADD",
        vector_math(
            "ADD", centerline,
            vector_math("SCALE", twisted_curve_u_axis, curve_u_coordinate)),
        vector_math(
            "ADD",
            vector_math("SCALE", twisted_curve_w_axis, curve_w_coordinate),
            vector_math("SCALE", curve_tangent, endpoint_extension)))
    curve_bypass_outside = boolean(
        "AND", curve_within_box, curve_outside_range)
    curve_mapped = switch(
        "VECTOR", curve_relative_binding, curve_local, relative_curve_local)
    curve_scoped = switch(
        "VECTOR", curve_bypass_outside, curve_mapped, curve_input)
    curve_result = switch(
        "VECTOR", curve_enabled, curve_input, curve_scoped)
    links.new(curve_result, block_outputs["CURVE"].inputs[0])

    registrar.layout("LOCAL", 1100.0)
    registrar.layout("PROFILE", 2800.0)
    for name in DEFORM_ORDER:
        registrar.layout(name, DEFORM_FRAME_MIN_WIDTH[name])
    order_start.location = (frames["PROFILE"].width - 60.0, -70.0)
    order_end.location = (60.0, -70.0)
    for name in DEFORM_ORDER:
        block_inputs[name].location = (60.0, -70.0)
        block_outputs[name].location = (
            frames[name].width - 60.0, -70.0)
    registrar.use("MODE")
    chain_output_input = reroute(
        DEFORM_CHAIN_OUTPUT_INPUT_NODE, "Chain Output Input", (0.0, 0.0))
    output_offset_x, output_offset_y, output_offset_z = separate(
        chain_output_offset)
    conjugated_type_result = combine(
        math_node(
            "ADD",
            vector_math(
                "DOT_PRODUCT", chain_output_input.outputs[0], chain_output_x),
            output_offset_x,
        ),
        math_node(
            "ADD",
            vector_math(
                "DOT_PRODUCT", chain_output_input.outputs[0], chain_output_y),
            output_offset_y,
        ),
        math_node(
            "ADD",
            vector_math(
                "DOT_PRODUCT", chain_output_input.outputs[0], chain_output_z),
            output_offset_z,
        ),
    )
    apply_chain_output = boolean(
        "OR", non_root_chain, chain_root_output_active)
    chained_type_result = switch(
        "VECTOR", apply_chain_output,
        chain_output_input.outputs[0], conjugated_type_result)
    chain_output_result = reroute(
        DEFORM_CHAIN_OUTPUT_NODE, "Chain Output", (0.0, 0.0))
    links.new(chained_type_result, chain_output_result.inputs[0])
    relink_deform_order(node_group, DEFORM_ORDER)
    type_result = order_end.outputs[0]
    inside_x = compare("FLOAT", "LESS_EQUAL", math_node("ABSOLUTE", x), half_x)
    inside_y = compare(
        "FLOAT", "LESS_EQUAL",
        math_node("ABSOLUTE", authored_y_input), half_y)
    inside_z = compare("FLOAT", "LESS_EQUAL", math_node("ABSOLUTE", z), half_z)
    inside_box = boolean("AND", boolean("AND", inside_x, inside_y), inside_z)
    within_result = switch("VECTOR", inside_box, local_position, type_result)
    normal_mode_result = switch("VECTOR", is_within, type_result, within_result)
    # Chain ownership always follows stage order from local Bottom to Top.
    # Origin changes only the deformation pivot/profile; reversing ownership
    # for TOP makes the untouched prefix consume the whole downstream model.
    before_source_start = compare(
        "FLOAT", "LESS_THAN", ownership_y,
        math_node("SUBTRACT", negative_half_y, CHAIN_BOUNDARY_EPSILON))
    before_chain_start = boolean(
        "AND", non_root_chain, before_source_start)
    # Points in an authored gap have already inherited the upstream domain,
    # but they have not reached this stage's lower boundary.  A downstream
    # Origin can make ``local_position`` use the compensated input frame;
    # returning that value here would apply the inverse lower-boundary frame
    # inside the gap.  Keep the modifier identity there, matching the Python
    # evaluator's raw-point early return.
    spatial_chained_result = switch(
        "VECTOR", before_chain_start, type_result, raw_local_position)
    chained_result = switch(
        "VECTOR", stage_eligible, raw_local_position, spatial_chained_result)
    mode_result = switch(
        "VECTOR", is_chained, normal_mode_result, chained_result)
    enabled_mode_result = switch(
        "VECTOR", stage_enabled, raw_local_position, mode_result)
    rotated_result = rotate(enabled_mode_result, rotation, invert=False)
    final_position = vector_math("ADD", rotated_result, center)

    # A Stretch authored after Bend cannot be factored into per-cage local
    # stretches: each upstream continuation carries a bent-space Y shear.  A
    # mixed chain therefore evaluates that one operation once in the original
    # root frame, after the complete Bend chain, while preserving the source Y
    # attribute captured at the root.
    registrar.use("MODE")
    global_source_y = math_node(
        "ADD", source_coordinate, chain_global_stretch_offset)
    global_half_y = math_node(
        "MULTIPLY", math_node("ABSOLUTE", chain_global_stretch_length), 0.5)
    global_negative_half_y = math_node("MULTIPLY", global_half_y, -1.0)
    global_is_top = compare(
        "INT", "EQUAL", chain_global_stretch_origin, ORIGIN_VALUES["TOP"])
    global_is_bottom = compare(
        "INT", "EQUAL", chain_global_stretch_origin,
        ORIGIN_VALUES["BOTTOM"])
    global_origin_y = switch(
        "FLOAT", global_is_top,
        switch("FLOAT", global_is_bottom, 0.0, global_negative_half_y),
        global_half_y)
    global_distance = math_node(
        "SUBTRACT", global_source_y, global_origin_y)
    global_lower_distance = math_node(
        "SUBTRACT", global_negative_half_y, global_origin_y)
    global_upper_distance = math_node(
        "SUBTRACT", global_half_y, global_origin_y)
    global_evaluated_distance = math_node(
        "MINIMUM",
        math_node(
            "MAXIMUM", global_distance, global_lower_distance),
        global_upper_distance,
    )
    global_is_symmetric = compare(
        "INT", "EQUAL", chain_global_stretch_origin,
        ORIGIN_VALUES["SYMMETRIC"])
    global_profile_distance = switch(
        "FLOAT", global_is_symmetric,
        global_evaluated_distance,
        math_node("ABSOLUTE", global_evaluated_distance))
    global_profile = math_node(
        "DIVIDE", global_profile_distance,
        chain_global_stretch_length)
    global_root_relative = vector_math(
        "SUBTRACT", final_position, chain_global_stretch_center)
    global_root_local = rotate(
        global_root_relative, chain_global_stretch_rotation, invert=True)
    suffix_before_shear = ordered_linear_stack(
        global_root_local,
        chain_global_suffix_pre_shear,
        global_profile,
        global_evaluated_distance,
        chain_global_suffix_twist,
        chain_global_suffix_taper,
        chain_global_stretch_factor,
    )
    suffix_x, suffix_y, suffix_z = separate(suffix_before_shear)
    suffix_shear_x, _suffix_shear_y, suffix_shear_z = separate(
        chain_global_suffix_shear)
    suffix_sheared = combine(
        math_node(
            "ADD", suffix_x,
            math_node(
                "MULTIPLY", suffix_shear_x, global_profile_distance)),
        suffix_y,
        math_node(
            "ADD", suffix_z,
            math_node(
                "MULTIPLY", suffix_shear_z, global_profile_distance)),
    )
    suffix_after_shear = switch(
        "VECTOR", mask_has(chain_global_suffix_mask, DEFORM_BITS["SHEAR"]),
        suffix_before_shear, suffix_sheared)
    suffix_local = ordered_linear_stack(
        suffix_after_shear,
        chain_global_suffix_post_shear,
        global_profile,
        global_evaluated_distance,
        chain_global_suffix_twist,
        chain_global_suffix_taper,
        chain_global_stretch_factor,
    )
    suffix_position = vector_math(
        "ADD",
        rotate(
            suffix_local, chain_global_stretch_rotation, invert=False),
        chain_global_stretch_center,
    )
    global_suffix_apply = boolean(
        "AND", chain_tip_stage, chain_global_suffix_active)
    post_suffix_position = switch(
        "VECTOR", global_suffix_apply, final_position, suffix_position)

    global_scale = math_node(
        "ADD", 1.0, chain_global_stretch_factor)
    global_safe_scale = math_node(
        "MAXIMUM", math_node("ABSOLUTE", global_scale), EPSILON)
    global_volume_scale = switch(
        "FLOAT", preserve_volume,
        1.0,
        math_node("POWER", global_safe_scale, -0.5),
    )
    legacy_global_relative = vector_math(
        "SUBTRACT", post_suffix_position, chain_global_stretch_center)
    legacy_global_local = rotate(
        legacy_global_relative, chain_global_stretch_rotation, invert=True)
    global_x, global_y, global_z = separate(legacy_global_local)
    global_stretched_local = combine(
        math_node("MULTIPLY", global_x, global_volume_scale),
        math_node(
            "ADD", global_y,
            math_node(
                "MULTIPLY", global_evaluated_distance,
                chain_global_stretch_factor)),
        math_node("MULTIPLY", global_z, global_volume_scale),
    )
    global_stretched_position = vector_math(
        "ADD",
        rotate(
            global_stretched_local,
            chain_global_stretch_rotation,
            invert=False),
        chain_global_stretch_center,
    )
    global_stretch_apply = boolean(
        "AND",
        boolean("AND", chain_tip_stage, chain_global_stretch_active),
        boolean("NOT", chain_global_suffix_active, False))
    final_position = switch(
        "VECTOR", global_stretch_apply,
        post_suffix_position, global_stretched_position)

    # Per-stage influence: blend between the untouched input position and
    # the fully deformed position. The socket accepts a vertex-group
    # attribute on the modifier, giving painted per-point falloff.
    influence_weight = group_input.outputs[
        influence_weight_socket.identifier]
    influence_delta = vector_math(
        "SUBTRACT", final_position, position.outputs["Position"])
    influence_scaled = vector_math(
        "SCALE", influence_delta, influence_weight)
    final_position = vector_math(
        "ADD", position.outputs["Position"], influence_scaled)

    capture_domain = registrar.new("GeometryNodeCaptureAttribute")
    capture_domain.name = "SDH Chain Domain Capture"
    capture_domain.label = "Capture Original Chain Coordinate"
    capture_domain.domain = "POINT"
    capture_domain.capture_items.new("FLOAT", "Chain Coordinate")
    links.new(geometry, capture_domain.inputs["Geometry"])
    _feed(
        node_group, source_coordinate,
        capture_domain.inputs["Chain Coordinate"])

    # Capture source-interval ownership before Set Position, while leaving the
    # incoming named attribute unchanged for this stage's deformation fields.
    # A bend past 180 degrees can loop valid suffix points below the stage top,
    # so computing the next-stage value after deformation would lose them.
    links.new(capture_domain.outputs["Geometry"], set_position.inputs["Geometry"])
    links.new(final_position, set_position.inputs["Position"])

    store_domain = registrar.new("GeometryNodeStoreNamedAttribute")
    store_domain.name = "SDH Chain Domain Output"
    store_domain.label = "Pass Coordinate to Next Stage"
    store_domain.data_type = "FLOAT"
    store_domain.domain = "POINT"
    links.new(set_position.outputs["Geometry"], store_domain.inputs["Geometry"])
    _feed(node_group, is_chained, store_domain.inputs["Selection"])
    _feed(node_group, chain_domain_attribute, store_domain.inputs["Name"])
    links.new(
        capture_domain.outputs["Chain Coordinate"],
        store_domain.inputs["Value"])

    remove_domain = registrar.new("GeometryNodeRemoveAttribute")
    remove_domain.name = "SDH Chain Domain Cleanup"
    remove_domain.label = "Remove Domain at Chain Tip"
    links.new(store_domain.outputs["Geometry"], remove_domain.inputs["Geometry"])
    _feed(node_group, chain_domain_attribute, remove_domain.inputs["Name"])
    cleanup_domain = boolean("AND", is_chained, chain_tip_stage)
    output_result = switch(
        "GEOMETRY", cleanup_domain,
        store_domain.outputs["Geometry"], remove_domain.outputs["Geometry"])
    links.new(output_result, group_output.inputs[output_geometry.identifier])
    registrar.layout("MODE", 1700.0)
    order_end.location = (60.0, -70.0)
    mode_frame = frames["MODE"]
    group_output.location = (
        mode_frame.location.x + mode_frame.width + 300.0,
        DEFORM_FRAME_Y,
    )

    node_group[GROUP_MARKER] = GROUP_VERSION
    node_group[_INTERFACE_CACHE_TOKEN] = str(uuid.uuid4())
    node_group.description = (
        "Composable cage deformation with bend, twist, taper, stretch, "
        "shear, FFD, and curve-guide mapping")
    node_group.is_modifier = True
