"""Batch creation and frame propagation for related cage stages.

The regular cage implementation owns Geometry Nodes and controller syncing.
This module only owns the relationship between stages.  A chain is identified
by a UUID stored on both the controller Empty and its node group; modifier
names and collection order are deliberately never used as identity.
"""
from __future__ import annotations

import math
import uuid

import bpy
from bpy.app.translations import pgettext_iface as iface_
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Operator
from mathutils import Euler, Matrix, Vector

from .ffd_resolution import (
    invert_dense_matrix as _invert_dense_matrix,
    native_axis_weights as _native_ffd_axis_weights,
)



EPSILON = 1.0e-5
CHAIN_VERSION = 4

# Public keys.  Keep these stable: files and duplicated objects use them to
# recover a chain after a reload or after a user renames a modifier.
CHAIN_UUID = "_sdh_cage_chain_uuid"
CHAIN_INDEX = "_sdh_cage_chain_index"
CHAIN_COUNT = "_sdh_cage_chain_count"
CHAIN_MODE = "_sdh_cage_chain_mode"
CHAIN_ROLE = "_sdh_cage_chain_role"
CHAIN_GAP = "_sdh_cage_chain_gap"
CHAIN_AUTO_RECONNECT = "_sdh_cage_chain_auto_reconnect"
CHAIN_SYNC_SHARED_END_SCALE = "_sdh_cage_chain_sync_shared_end_scale"
CHAIN_ROOT_OUTPUT_AFFINE = "_sdh_cage_chain_root_output_affine"
CHAIN_SOURCE_FRAME_MODE = "_sdh_cage_chain_source_frame_mode"
CHAIN_GLOBAL_STRETCH_ACTIVE = "_sdh_cage_chain_global_stretch_active"
CHAIN_GLOBAL_STRETCH_FACTOR = "_sdh_cage_chain_global_stretch_factor"
CHAIN_GLOBAL_STRETCH_CENTER = "_sdh_cage_chain_global_stretch_center"
CHAIN_GLOBAL_STRETCH_ROTATION = "_sdh_cage_chain_global_stretch_rotation"
CHAIN_GLOBAL_STRETCH_OFFSET = "_sdh_cage_chain_global_stretch_offset"
CHAIN_GLOBAL_STRETCH_LENGTH = "_sdh_cage_chain_global_stretch_length"
CHAIN_GLOBAL_STRETCH_ORIGIN = "_sdh_cage_chain_global_stretch_origin"
CHAIN_GLOBAL_PREFIX_ACTIVE = "_sdh_cage_chain_global_prefix_active"
CHAIN_GLOBAL_PREFIX_MASK = "_sdh_cage_chain_global_prefix_mask"
CHAIN_GLOBAL_BASELINE_MASK = "_sdh_cage_chain_global_baseline_mask"
CHAIN_GLOBAL_PREFIX_PRE_SHEAR_MASK = (
    "_sdh_cage_chain_global_prefix_pre_shear_mask")
CHAIN_GLOBAL_PREFIX_POST_SHEAR_MASK = (
    "_sdh_cage_chain_global_prefix_post_shear_mask")
CHAIN_GLOBAL_PREFIX_SHEAR = "_sdh_cage_chain_global_prefix_shear"
CHAIN_GLOBAL_PREFIX_BEND = "_sdh_cage_chain_global_prefix_bend"
CHAIN_GLOBAL_PREFIX_DIRECTION = "_sdh_cage_chain_global_prefix_direction"
CHAIN_GLOBAL_PREFIX_TWIST = "_sdh_cage_chain_global_prefix_twist"
CHAIN_GLOBAL_PREFIX_TAPER = "_sdh_cage_chain_global_prefix_taper"
CHAIN_GLOBAL_PREFIX_STRETCH = "_sdh_cage_chain_global_prefix_stretch"
CHAIN_GLOBAL_PREFIX_CENTER = "_sdh_cage_chain_global_prefix_center"
CHAIN_GLOBAL_PREFIX_ROTATION = "_sdh_cage_chain_global_prefix_rotation"
CHAIN_GLOBAL_PREFIX_OFFSET = "_sdh_cage_chain_global_prefix_offset"
CHAIN_GLOBAL_PREFIX_LENGTH = "_sdh_cage_chain_global_prefix_length"
CHAIN_GLOBAL_PREFIX_ORIGIN = "_sdh_cage_chain_global_prefix_origin"
CHAIN_GLOBAL_SUFFIX_ACTIVE = "_sdh_cage_chain_global_suffix_active"
CHAIN_GLOBAL_SUFFIX_MASK = "_sdh_cage_chain_global_suffix_mask"
CHAIN_GLOBAL_SUFFIX_PRE_SHEAR_MASK = (
    "_sdh_cage_chain_global_suffix_pre_shear_mask")
CHAIN_GLOBAL_SUFFIX_POST_SHEAR_MASK = (
    "_sdh_cage_chain_global_suffix_post_shear_mask")
CHAIN_GLOBAL_SUFFIX_TWIST = "_sdh_cage_chain_global_suffix_twist"
CHAIN_GLOBAL_SUFFIX_TAPER = "_sdh_cage_chain_global_suffix_taper"
CHAIN_GLOBAL_SUFFIX_SHEAR = "_sdh_cage_chain_global_suffix_shear"
CHAIN_GLOBAL_PROFILE_ACTIVE = "_sdh_cage_chain_global_profile_active"
CHAIN_GLOBAL_PROFILE_BOTTOM_SCALE = (
    "_sdh_cage_chain_global_profile_bottom_scale")
CHAIN_GLOBAL_PROFILE_TOP_SCALE = "_sdh_cage_chain_global_profile_top_scale"
CHAIN_GLOBAL_PROFILE_BOTTOM_OFFSET = (
    "_sdh_cage_chain_global_profile_bottom_offset")
CHAIN_GLOBAL_PROFILE_TOP_OFFSET = "_sdh_cage_chain_global_profile_top_offset"
CHAIN_PREFIX_BASE_BEND = "_sdh_cage_chain_prefix_base_bend"
CHAIN_PREFIX_BASE_TWIST = "_sdh_cage_chain_prefix_base_twist"
CHAIN_PREFIX_BASE_TAPER = "_sdh_cage_chain_prefix_base_taper"
CHAIN_PREFIX_BASE_STRETCH = "_sdh_cage_chain_prefix_base_stretch"
CHAIN_PREFIX_BASE_SHEAR = "_sdh_cage_chain_prefix_base_shear"
CHAIN_VERSION_KEY = "_sdh_cage_chain_version"

# Compatibility aliases used by an early prototype.  Reading them lets an
# existing file be upgraded without making the old spelling the source of
# truth for newly-created chains.
LEGACY_CHAIN_ID = "_sdh_cage_chain_id"
LEGACY_CHAIN_BROKEN = "_sdh_cage_chain_broken"
CHAIN_ID = CHAIN_UUID


def _core():
    from . import core
    return core


def _pointer(value):
    try:
        return int(value.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return 0


def _call(name, *args, default=None, **kwargs):
    function = getattr(_core(), name, None)
    return function(*args, **kwargs) if function is not None else default


def _target_from_context(context):
    target = _call("target_from_context", context)
    if target is not None:
        return target
    obj = getattr(context, "object", None)
    supported = getattr(_core(), "SUPPORTED_TYPES", {"MESH", "CURVE", "FONT"})
    return obj if obj is not None and obj.type in supported else None


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


def _is_cage_modifier(modifier):
    return bool(_call("is_cage_modifier", modifier, default=False))


def _cage_modifiers(target):
    return tuple(_call("cage_modifiers", target, default=()) or ())


def _find_controller(target, modifier):
    return _call("find_controller", target, modifier)


def _modifier_uuid(modifier):
    return str(_call("cage_modifier_uuid", modifier, default="") or "")


def _target_uuid(target):
    key = getattr(_core(), "TARGET_UUID", "_sdh_cage_deform_target_uuid")
    return str(target.get(key, "")) if target is not None else ""


def _safe_inverse(matrix):
    try:
        return matrix.inverted_safe()
    except (AttributeError, RuntimeError, ValueError):
        return matrix.inverted()


def _metadata_value(owner, key, default=None):
    if owner is None:
        return default
    try:
        value = owner.get(key, None)
        if value not in (None, ""):
            return value
        # Old files used CHAIN_ID for the UUID.
        if key == CHAIN_UUID:
            return owner.get(LEGACY_CHAIN_ID, default)
    except (AttributeError, ReferenceError, TypeError):
        pass
    return default


def _stage_metadata_value(modifier, key, default=None):
    """Read stage metadata from the group/modifier/controller owners."""
    group = getattr(modifier, "node_group", None)
    value = _metadata_value(group, key, None)
    if value is not None:
        return value
    value = _metadata_value(modifier, key, None)
    if value is not None:
        return value
    target = getattr(modifier, "id_data", None)
    for controller in getattr(target, "children", ()):
        if (
                getattr(controller, "name", "") ==
                f"{getattr(modifier, 'name', '')} Controller"
        ):
            return _metadata_value(controller, key, default)
    return default


def stage_chain_uuid(modifier):
    """Return a stage UUID from its node group (or a legacy modifier key)."""
    value = _stage_metadata_value(modifier, CHAIN_UUID, "")
    return str(value or "")


def stage_chain_index(modifier, default=-1):
    value = _stage_metadata_value(modifier, CHAIN_INDEX, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def stage_chain_count(modifier, default=0):
    value = _stage_metadata_value(modifier, CHAIN_COUNT, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def stage_chain_mode(modifier, default=""):
    value = _stage_metadata_value(modifier, CHAIN_MODE, default)
    return str(value or default)


def stage_chain_gap(modifier, default=0.0):
    """Return the non-negative incoming gap owned by ``modifier``.

    Stage zero has no incoming boundary, while every later stage stores the
    authored distance from the preceding cage on its own metadata owners.
    """
    value = _stage_metadata_value(modifier, CHAIN_GAP, default)
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = float(default)
    if not math.isfinite(value):
        value = float(default)
    return max(value, 0.0)


def stage_chain_auto_reconnect(modifier, default=True):
    """Return the persisted automatic frame propagation preference.

    The value is mirrored on the node group, modifier (when supported), and
    controller.  Reading the group first keeps the preference stable on
    Blender versions that reject custom properties on ``NodesModifier``.
    Files created before this preference existed intentionally default to
    enabled so their connected chains retain the previous expected behavior.
    """
    value = _stage_metadata_value(modifier, CHAIN_AUTO_RECONNECT, None)
    if value is None:
        return bool(default)
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "off", "no"}
    return bool(value)


def stage_chain_sync_shared_end_scale(modifier, default=False):
    """Return the persisted shared-seam cross-section preference.

    This option did not exist in earlier files, so an absent value must stay
    disabled.  That preserves independently authored top and bottom profiles
    until the user explicitly opts into linked seam scaling.
    """
    value = _stage_metadata_value(modifier, CHAIN_SYNC_SHARED_END_SCALE, None)
    if value is None:
        return bool(default)
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "off", "no"}
    return bool(value)


def _stage_role(index, count):
    if index <= 0:
        return "ROOT"
    if index >= max(count - 1, 0):
        return "TIP"
    return "MIDDLE"


def _write_owner_metadata(owner, chain_uuid, index, count, mode, role, gap,
                          broken=False, auto_reconnect=True,
                          sync_shared_end_scale=False):
    if owner is None:
        return
    # Blender 5.2's ``NodesModifier`` deliberately disallows custom ID
    # properties, while GeometryNodeTree and Object still support them.  A
    # chain is therefore stored redundantly on the node group and controller,
    # with the modifier write treated as an optional compatibility mirror.
    # Keep each assignment isolated so an unsupported owner cannot prevent the
    # remaining owners from receiving the relationship metadata.
    values = (
        (CHAIN_UUID, str(chain_uuid)),
        # Keep the legacy key as a read-only compatibility breadcrumb.
        (LEGACY_CHAIN_ID, str(chain_uuid)),
        (CHAIN_INDEX, int(index)),
        (CHAIN_COUNT, int(count)),
        (CHAIN_MODE, str(mode)),
        (CHAIN_ROLE, str(role)),
        (CHAIN_GAP, float(gap)),
        (CHAIN_AUTO_RECONNECT, bool(auto_reconnect)),
        (CHAIN_SYNC_SHARED_END_SCALE, bool(sync_shared_end_scale)),
        (CHAIN_VERSION_KEY, int(CHAIN_VERSION)),
        (LEGACY_CHAIN_BROKEN, bool(broken)),
    )
    for key, value in values:
        try:
            owner[key] = value
        except (TypeError, AttributeError, ReferenceError, RuntimeError):
            # Unsupported RNA structs are expected on newer Blender builds;
            # metadata on the node group/controller remains authoritative.
            continue


def sync_chain_domain_inputs(controller, modifier):
    """Atomically mirror chain ownership metadata into hidden GN inputs."""
    if modifier is None:
        return False
    values = _call(
        "_chain_domain_input_values", controller, modifier, default={}) or {}
    changed = False
    for name in (
            "Chain Domain Attribute", "Chain Root Stage", "Chain Tip Stage",
            "Chain Source Start", "Chain Source End",
    ):
        if name not in values:
            continue
        value = values[name]
        old = _call("modifier_input", modifier, name)
        if isinstance(value, str) or isinstance(old, str):
            different = str(old or "") != str(value or "")
        elif isinstance(value, bool):
            different = old is None or bool(old) != value
        else:
            try:
                different = old is None or abs(
                    float(old) - float(value)) > EPSILON
            except (TypeError, ValueError):
                different = True
        if not different:
            continue
        _call("set_modifier_input", modifier, name, value)
        changed = True
    if changed:
        target = getattr(modifier, "id_data", None)
        try:
            target.update_tag()
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
    return changed


def set_stage_metadata(modifier, controller, chain_uuid, index, count,
                       mode, *, gap=0.0, broken=False, auto_reconnect=None,
                       sync_shared_end_scale=None):
    """Write relationship metadata to modifier, node group, and controller."""
    role = _stage_role(int(index), int(count))
    group = getattr(modifier, "node_group", None)
    if auto_reconnect is None:
        auto_reconnect = stage_chain_auto_reconnect(modifier, True)
        properties = getattr(controller, "sdh_cage_deform", None)
        if properties is not None:
            try:
                auto_reconnect = bool(properties.auto_reconnect)
            except (AttributeError, ReferenceError, TypeError):
                pass
    if sync_shared_end_scale is None:
        sync_shared_end_scale = stage_chain_sync_shared_end_scale(
            modifier, False)
        group_value = _metadata_value(
            group, CHAIN_SYNC_SHARED_END_SCALE, None)
        if group_value is None:
            properties = getattr(controller, "sdh_cage_deform", None)
            if properties is not None:
                try:
                    sync_shared_end_scale = bool(
                        properties.sync_shared_end_scale)
                except (AttributeError, ReferenceError, TypeError):
                    pass
    _write_owner_metadata(
        group, chain_uuid, index, count, mode, role, gap, broken,
        auto_reconnect, sync_shared_end_scale)
    _write_owner_metadata(
        modifier, chain_uuid, index, count, mode, role, gap, broken,
        auto_reconnect, sync_shared_end_scale)
    _write_owner_metadata(
        controller, chain_uuid, index, count, mode, role, gap, broken,
        auto_reconnect, sync_shared_end_scale)
    _call("invalidate_chain_domain_cache")
    sync_chain_domain_inputs(controller, modifier)


def _set_source_frame_mode(modifier, controller, enabled):
    """Persist whether a subdivided Bend stack stays in its source frame."""
    value = bool(enabled)
    for owner in (getattr(modifier, "node_group", None), modifier, controller):
        if owner is None:
            continue
        try:
            if value:
                owner[CHAIN_SOURCE_FRAME_MODE] = True
            elif CHAIN_SOURCE_FRAME_MODE in owner:
                del owner[CHAIN_SOURCE_FRAME_MODE]
        except (AttributeError, KeyError, ReferenceError, RuntimeError, TypeError):
            pass


def stage_uses_source_frame(modifier, controller=None):
    """Return true for a subdivision whose calculation frame stays raw."""
    for owner in (modifier, getattr(modifier, "node_group", None), controller):
        if bool(_metadata_value(owner, CHAIN_SOURCE_FRAME_MODE, False)):
            return True
    return False


def _set_global_stretch_mode(
        modifier, controller, *, active=False, factor=0.0, center=(0.0, 0.0, 0.0),
        rotation=(0.0, 0.0, 0.0), source_offset=0.0, length=2.0,
        origin="BOTTOM"):
    values = {
        CHAIN_GLOBAL_STRETCH_ACTIVE: bool(active),
        CHAIN_GLOBAL_STRETCH_FACTOR: float(factor),
        CHAIN_GLOBAL_STRETCH_CENTER: tuple(float(value) for value in center),
        CHAIN_GLOBAL_STRETCH_ROTATION: tuple(
            float(value) for value in rotation),
        CHAIN_GLOBAL_STRETCH_OFFSET: float(source_offset),
        CHAIN_GLOBAL_STRETCH_LENGTH: max(float(length), EPSILON),
        CHAIN_GLOBAL_STRETCH_ORIGIN: str(origin),
    }
    for owner in (getattr(modifier, "node_group", None), modifier, controller):
        if owner is None:
            continue
        for key, value in values.items():
            try:
                owner[key] = value
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
    _call("invalidate_chain_domain_cache")


def _set_global_prefix_mode(
        modifier, controller, *, active=False, deform_types=(),
        baseline_types=(), pre_shear_types=(), post_shear_types=(),
        bend=0.0, direction=0.0, twist=0.0, taper=0.0, stretch=0.0,
        shear=(0.0, 0.0),
        center=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0),
        source_offset=0.0, length=2.0, origin="BOTTOM",
        profile_active=False, bottom_scale=(1.0, 1.0),
        top_scale=(1.0, 1.0), bottom_offset=(0.0, 0.0),
        top_offset=(0.0, 0.0),
        base_bend=0.0, base_twist=0.0, base_taper=0.0,
        base_stretch=0.0, base_shear=(0.0, 0.0)):
    """Persist the analytic source-frame baseline used by a subdivision."""
    mask = int(_call("deform_type_mask", deform_types, None, default=0) or 0)
    baseline_mask = int(
        _call("deform_type_mask", baseline_types, None, default=mask) or 0)
    pre_shear_mask = int(
        _call("deform_type_mask", pre_shear_types, None, default=0) or 0)
    post_shear_mask = int(
        _call("deform_type_mask", post_shear_types, None, default=0) or 0)
    values = {
        CHAIN_GLOBAL_PREFIX_ACTIVE: bool(active),
        CHAIN_GLOBAL_PREFIX_MASK: mask,
        CHAIN_GLOBAL_BASELINE_MASK: baseline_mask,
        CHAIN_GLOBAL_PREFIX_PRE_SHEAR_MASK: pre_shear_mask,
        CHAIN_GLOBAL_PREFIX_POST_SHEAR_MASK: post_shear_mask,
        CHAIN_GLOBAL_PREFIX_SHEAR: (
            float(shear[0]), 0.0, float(shear[1])),
        CHAIN_GLOBAL_PREFIX_BEND: float(bend),
        CHAIN_GLOBAL_PREFIX_DIRECTION: float(direction),
        CHAIN_GLOBAL_PREFIX_TWIST: float(twist),
        CHAIN_GLOBAL_PREFIX_TAPER: float(taper),
        CHAIN_GLOBAL_PREFIX_STRETCH: float(stretch),
        CHAIN_GLOBAL_PREFIX_CENTER: tuple(float(value) for value in center),
        CHAIN_GLOBAL_PREFIX_ROTATION: tuple(
            float(value) for value in rotation),
        CHAIN_GLOBAL_PREFIX_OFFSET: float(source_offset),
        CHAIN_GLOBAL_PREFIX_LENGTH: max(float(length), EPSILON),
        CHAIN_GLOBAL_PREFIX_ORIGIN: str(origin),
        CHAIN_GLOBAL_PROFILE_ACTIVE: bool(profile_active),
        CHAIN_GLOBAL_PROFILE_BOTTOM_SCALE: (
            float(bottom_scale[0]), 1.0, float(bottom_scale[1])),
        CHAIN_GLOBAL_PROFILE_TOP_SCALE: (
            float(top_scale[0]), 1.0, float(top_scale[1])),
        CHAIN_GLOBAL_PROFILE_BOTTOM_OFFSET: (
            float(bottom_offset[0]), 0.0, float(bottom_offset[1])),
        CHAIN_GLOBAL_PROFILE_TOP_OFFSET: (
            float(top_offset[0]), 0.0, float(top_offset[1])),
        CHAIN_PREFIX_BASE_BEND: float(base_bend),
        CHAIN_PREFIX_BASE_TWIST: float(base_twist),
        CHAIN_PREFIX_BASE_TAPER: float(base_taper),
        CHAIN_PREFIX_BASE_STRETCH: float(base_stretch),
        CHAIN_PREFIX_BASE_SHEAR: (
            float(base_shear[0]), 0.0, float(base_shear[1])),
    }
    for owner in (getattr(modifier, "node_group", None), modifier, controller):
        if owner is None:
            continue
        for key, value in values.items():
            try:
                owner[key] = value
            except (AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError):
                pass
    _call("invalidate_chain_domain_cache")


def _set_global_suffix_mode(
        modifier, controller, *, active=False, deform_types=(),
        pre_shear_types=(), post_shear_types=(), twist=0.0, taper=0.0,
        shear=(0.0, 0.0)):
    """Persist operations evaluated once after the complete local chain."""
    mask = int(_call("deform_type_mask", deform_types, None, default=0) or 0)
    pre_shear_mask = int(
        _call("deform_type_mask", pre_shear_types, None, default=0) or 0)
    post_shear_mask = int(
        _call("deform_type_mask", post_shear_types, None, default=0) or 0)
    values = {
        CHAIN_GLOBAL_SUFFIX_ACTIVE: bool(active),
        CHAIN_GLOBAL_SUFFIX_MASK: mask,
        CHAIN_GLOBAL_SUFFIX_PRE_SHEAR_MASK: pre_shear_mask,
        CHAIN_GLOBAL_SUFFIX_POST_SHEAR_MASK: post_shear_mask,
        CHAIN_GLOBAL_SUFFIX_TWIST: float(twist),
        CHAIN_GLOBAL_SUFFIX_TAPER: float(taper),
        CHAIN_GLOBAL_SUFFIX_SHEAR: (
            float(shear[0]), 0.0, float(shear[1])),
    }
    for owner in (getattr(modifier, "node_group", None), modifier, controller):
        if owner is None:
            continue
        for key, value in values.items():
            try:
                owner[key] = value
            except (AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError):
                pass
    _call("invalidate_chain_domain_cache")


def _write_stage_gap(modifier, controller, gap):
    """Update only the incoming-gap mirrors without rewriting chain IDs."""
    try:
        gap = max(float(gap), 0.0)
    except (TypeError, ValueError):
        gap = 0.0
    if not math.isfinite(gap):
        gap = 0.0
    for owner in (getattr(modifier, "node_group", None), modifier, controller):
        if owner is None:
            continue
        try:
            owner[CHAIN_GAP] = gap
        except (TypeError, AttributeError, ReferenceError, RuntimeError):
            continue
    _call("invalidate_chain_domain_cache")
    return gap


def _resolve_chain_uuid(target, chain_uuid=""):
    if chain_uuid:
        return str(chain_uuid)
    active = getattr(getattr(target, "modifiers", None), "active", None)
    value = stage_chain_uuid(active)
    if value:
        return value
    for modifier in _cage_modifiers(target):
        value = stage_chain_uuid(modifier)
        if value:
            return value
    obj = getattr(bpy.context, "object", None)
    # Never use an unrelated active object as a fallback for an explicitly
    # supplied target.  Chain identity is target-scoped; a context fallback is
    # only safe when it refers to that same target.
    if obj is target:
        return str(_metadata_value(obj, CHAIN_UUID, ""))
    return ""


def chain_stages(target, chain_uuid=""):
    """Return matching managed stages in their actual modifier-stack order."""
    chain_uuid = _resolve_chain_uuid(target, chain_uuid)
    if target is None or not chain_uuid:
        return ()
    return tuple(
        modifier for modifier in tuple(target.modifiers)
        if _is_cage_modifier(modifier) and stage_chain_uuid(modifier) == chain_uuid
    )


def chain_auto_reconnect(target, chain_uuid="", default=True):
    """Return the chain-wide automatic reconnect preference."""
    stages = chain_stages(target, chain_uuid)
    if not stages:
        return bool(default)
    return stage_chain_auto_reconnect(stages[0], default)


def set_chain_auto_reconnect(target, chain_uuid="", enabled=True,
                             *, sync_properties=True):
    """Set one automatic reconnect preference for every live chain stage.

    Controller properties are mirrored as a convenience for the UI, while
    the node-group metadata remains authoritative across Blender versions.
    The core-owned guard prevents the mirrored assignments from recursively
    scheduling the same chain while it is being normalized.
    """
    chain_uuid = _resolve_chain_uuid(target, chain_uuid)
    stages = chain_stages(target, chain_uuid)
    if not stages:
        return ()
    enabled = bool(enabled)
    core = _core()
    guard = getattr(core, "_CHAIN_AUTO_GUARD", set())
    for modifier in stages:
        controller = _find_controller(target, modifier)
        pointer = _pointer(controller)
        if sync_properties and controller is not None:
            properties = getattr(controller, "sdh_cage_deform", None)
            if properties is not None and hasattr(properties, "auto_reconnect"):
                if pointer:
                    guard.add(pointer)
                try:
                    if bool(properties.auto_reconnect) != enabled:
                        properties.auto_reconnect = enabled
                except (AttributeError, ReferenceError, RuntimeError, TypeError):
                    pass
                finally:
                    if pointer:
                        guard.discard(pointer)
        index = stage_chain_index(modifier, 0)
        count = stage_chain_count(modifier, len(stages))
        mode = stage_chain_mode(modifier, "CONNECTED")
        group = getattr(modifier, "node_group", None)
        gap = stage_chain_gap(modifier)
        broken = bool(_metadata_value(group, LEGACY_CHAIN_BROKEN, False))
        set_stage_metadata(
            modifier, controller, chain_uuid, index, count, mode,
            gap=gap, broken=broken, auto_reconnect=enabled)
    return stages


def chain_sync_shared_end_scale(target, chain_uuid="", default=False):
    """Return the chain-wide shared-seam scale preference."""
    stages = chain_stages(target, chain_uuid)
    if not stages:
        return bool(default)
    return stage_chain_sync_shared_end_scale(stages[0], default)


def set_chain_sync_shared_end_scale(target, chain_uuid="", enabled=False,
                                    *, sync_properties=True,
                                    reconcile=True):
    """Mirror one shared-seam scale preference across every chain stage.

    Enabling the option reconciles existing seams deterministically from the
    upstream TOP profile into the downstream BOTTOM profile.  Outer ends and
    all offset/gap values remain independently authored.
    """
    chain_uuid = _resolve_chain_uuid(target, chain_uuid)
    stages = chain_stages(target, chain_uuid)
    if not stages:
        return ()
    enabled = bool(enabled)
    core = _core()
    guard = getattr(core, "_CHAIN_SHARED_SCALE_GUARD", set())
    for modifier in stages:
        controller = _find_controller(target, modifier)
        pointer = _pointer(controller)
        if sync_properties and controller is not None:
            properties = getattr(controller, "sdh_cage_deform", None)
            if (
                    properties is not None and
                    hasattr(properties, "sync_shared_end_scale")
            ):
                if pointer:
                    guard.add(pointer)
                try:
                    if bool(properties.sync_shared_end_scale) != enabled:
                        properties.sync_shared_end_scale = enabled
                except (AttributeError, ReferenceError, RuntimeError, TypeError):
                    pass
                finally:
                    if pointer:
                        guard.discard(pointer)
        index = stage_chain_index(modifier, 0)
        count = stage_chain_count(modifier, len(stages))
        mode = stage_chain_mode(modifier, "CONNECTED")
        group = getattr(modifier, "node_group", None)
        gap = stage_chain_gap(modifier)
        broken = bool(_metadata_value(group, LEGACY_CHAIN_BROKEN, False))
        set_stage_metadata(
            modifier, controller, chain_uuid, index, count, mode,
            gap=gap, broken=broken,
            auto_reconnect=stage_chain_auto_reconnect(modifier, True),
            sync_shared_end_scale=enabled,
        )
    if enabled and reconcile:
        for upstream in stages[:-1]:
            sync_chain_shared_end_scale(
                target, upstream, "TOP", propagate=False)
    # Switching the option changes the meaning of downstream Top/Bottom Scale
    # sockets. Push every controller immediately so a timer cannot pull stale
    # relative values back as authored absolute profiles after disabling.
    sync = getattr(core, "sync_controller", None)
    if sync is not None:
        for modifier in stages:
            controller = _find_controller(target, modifier)
            if controller is not None:
                sync(controller, pull_transform=False, sync_mode="push")
    return stages


def _end_scale_tuple(value):
    try:
        values = tuple(float(component) for component in value)
    except (TypeError, ValueError):
        return None
    if len(values) != 2 or not all(math.isfinite(component) for component in values):
        return None
    return tuple(max(component, 0.05) for component in values)


def _end_scales_match(first, second):
    first = _end_scale_tuple(first)
    second = _end_scale_tuple(second)
    return bool(
        first is not None and second is not None and
        all(abs(a - b) <= EPSILON for a, b in zip(first, second))
    )


def sync_chain_shared_end_scale(
        target, modifier, side, scale=None, *, propagate=True):
    """Synchronize one shared TOP/BOTTOM cross-section atomically.

    ``stage i TOP`` is paired with ``stage i + 1 BOTTOM``.  Editing either
    participant copies only its two X/Z scale components to the other side;
    opposite ends, end offsets, controller transforms, and chain gaps are not
    changed.  The dedicated core transaction suppresses recursive reconnect
    requests without discarding unrelated work that was already queued.
    """
    side = str(side or "").upper()
    if target is None or modifier is None or side not in {"TOP", "BOTTOM"}:
        return False
    chain_uuid = stage_chain_uuid(modifier)
    report = validate_chain(target, chain_uuid)
    stages = tuple(report["stages"])
    if report["broken"] or len(stages) < 2:
        return False
    mode = stage_chain_mode(stages[0], "").upper()
    if mode not in {"CHAINED", "CONNECTED"}:
        return False
    if not chain_sync_shared_end_scale(target, chain_uuid, False):
        return False
    try:
        source_index = stages.index(modifier)
    except ValueError:
        return False
    peer_index = source_index + (1 if side == "TOP" else -1)
    if peer_index < 0 or peer_index >= len(stages):
        return False

    source_controller = _find_controller(target, modifier)
    peer_modifier = stages[peer_index]
    peer_controller = _find_controller(target, peer_modifier)
    if source_controller is None or peer_controller is None:
        return False
    source_properties = source_controller.sdh_cage_deform
    peer_properties = peer_controller.sdh_cage_deform
    source_name = "top_scale" if side == "TOP" else "bottom_scale"
    peer_name = "bottom_scale" if side == "TOP" else "top_scale"
    value = _end_scale_tuple(
        getattr(source_properties, source_name) if scale is None else scale)
    if value is None:
        return False

    core = _core()
    guard = getattr(core, "_CHAIN_SHARED_SCALE_GUARD", set())
    pointers = tuple(filter(None, (
        _pointer(source_controller), _pointer(peer_controller))))
    sync = getattr(core, "sync_controller", None)

    def apply_scale():
        guard.update(pointers)
        try:
            if not _end_scales_match(getattr(source_properties, source_name), value):
                setattr(source_properties, source_name, value)
            if not _end_scales_match(getattr(peer_properties, peer_name), value):
                setattr(peer_properties, peer_name, value)
            if sync is not None:
                sync(source_controller, pull_transform=False)
                sync(peer_controller, pull_transform=False)
            try:
                target.update_tag()
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                pass
        finally:
            for pointer in pointers:
                guard.discard(pointer)

    dirty_index = min(source_index, peer_index)
    pending_index = getattr(
        core, "pending_chain_reconnect_start_index", None)
    if pending_index is not None:
        dirty_index = pending_index(target, chain_uuid, dirty_index)
    should_propagate = bool(
        propagate and chain_auto_reconnect(target, chain_uuid, True))

    if should_propagate:
        transaction = getattr(core, "chain_reconnect_transaction", None)
        if transaction is None:
            apply_scale()
            reconnect_chain(
                target,
                chain_uuid,
                start_index=dirty_index,
                runtime_only=True,
            )
        else:
            with transaction(target, chain_uuid) as commit:
                apply_scale()
                reconnect_chain(
                    target,
                    chain_uuid,
                    start_index=dirty_index,
                    runtime_only=True,
                )
                commit()
    else:
        transaction = getattr(core, "chain_atomic_property_update", None)
        if transaction is None:
            apply_scale()
        else:
            with transaction(target, chain_uuid):
                apply_scale()
    return True


def set_stage_chain_gap(target, stage_or_index, gap, *, preserve_span=True,
                        allow_broken=False):
    """Set one stage's incoming gap and optionally preserve the chain span.

    The gap is owned by the downstream stage.  With ``preserve_span`` enabled
    (the default), the downstream cage length is adjusted by the opposite
    amount, clamped to :data:`EPSILON`, so its top boundary remains fixed
    after reconnecting.  The returned value is the actual non-negative gap
    after clamping.  ``None`` means the requested stage is not part of a
    valid connected chain.
    """
    chain_uuid = (
        _resolve_chain_uuid(target)
        if isinstance(stage_or_index, int)
        else stage_chain_uuid(stage_or_index)
    )
    stages = chain_stages(target, chain_uuid)
    if target is None or not stages:
        return None
    if isinstance(stage_or_index, int):
        index = int(stage_or_index)
        if index < 0 or index >= len(stages):
            return None
        modifier = stages[index]
    else:
        modifier = stage_or_index
        try:
            index = stages.index(modifier)
        except ValueError:
            return None
    # The root has no incoming seam.  Silently normalizing it to zero keeps
    # old files with stale root-gap metadata from introducing a leading gap.
    if index <= 0:
        _write_stage_gap(modifier, _find_controller(target, modifier), 0.0)
        return 0.0
    report = validate_chain(target, chain_uuid)
    if report["broken"] and not allow_broken:
        return None
    try:
        requested = max(float(gap), 0.0)
    except (TypeError, ValueError):
        requested = 0.0
    if not math.isfinite(requested):
        requested = 0.0
    controller = _find_controller(target, modifier)
    if controller is None:
        return None
    properties = getattr(controller, "sdh_cage_deform", None)
    if properties is None:
        return None
    old_gap = stage_chain_gap(modifier)
    old_length = max(float(properties.size[1]), EPSILON)
    if preserve_span:
        span = old_gap + old_length
        new_length = max(span - requested, EPSILON)
        actual_gap = max(span - new_length, 0.0)
    else:
        new_length = old_length
        actual_gap = requested
    core = _core()
    transaction = getattr(core, "chain_reconnect_transaction", None)
    context = transaction(target, chain_uuid) if transaction is not None else None

    def _apply():
        pointer = _pointer(controller)
        syncing = getattr(core, "_SYNCING", set())
        if pointer:
            syncing.add(pointer)
        try:
            properties.size = (
                float(properties.size[0]), new_length,
                float(properties.size[2]))
            controller.scale = (
                float(properties.size[0]) * 0.5,
                new_length * 0.5,
                float(properties.size[2]) * 0.5)
        finally:
            if pointer:
                syncing.discard(pointer)
        _write_stage_gap(modifier, controller, actual_gap)
        sync = getattr(core, "sync_controller", None)
        if sync is not None:
            sync(controller, pull_transform=False)
        reconnect_chain(target, chain_uuid, allow_broken=allow_broken)

    if context is None:
        _apply()
    else:
        with context as commit:
            _apply()
            commit()
    return float(actual_gap)


# Short public alias used by panel/operator callers.
set_chain_gap = set_stage_chain_gap


def chain_ids(target):
    """Return unique chain UUIDs owned by a target, in stack order."""
    values = []
    for modifier in _cage_modifiers(target):
        value = stage_chain_uuid(modifier)
        if value and value not in values:
            values.append(value)
    return tuple(values)


def normalize_all_chain_metadata():
    """Upgrade saved chains that predate current chain preferences."""
    normalized = 0
    for target in tuple(getattr(bpy.data, "objects", ())):
        for chain_uuid in chain_ids(target):
            stages = chain_stages(target, chain_uuid)
            if not stages:
                continue
            missing_preference = any(
                any(
                    _metadata_value(getattr(stage, "node_group", None), key,
                                    None) is None
                    for key in (
                        CHAIN_AUTO_RECONNECT,
                        CHAIN_SYNC_SHARED_END_SCALE,
                    )
                )
                for stage in stages
            )
            if missing_preference:
                _normalize_metadata(target, chain_uuid)
                normalized += 1
    return normalized


def _chain_stage_records(target, chain_uuid=""):
    records = []
    for modifier in chain_stages(target, chain_uuid):
        controller = _find_controller(target, modifier)
        records.append((modifier, controller, stage_chain_index(modifier),
                        stage_chain_count(modifier), stage_chain_mode(modifier)))
    return tuple(records)


def validate_chain(target, chain_uuid=""):
    """Inspect chain integrity without changing the scene.

    The returned dictionary is intentionally plain data so operators, panels,
    and background regression scripts can consume it without a Blender UI.
    """
    chain_uuid = _resolve_chain_uuid(target, chain_uuid)
    records = _chain_stage_records(target, chain_uuid)
    stages = tuple(record[0] for record in records)
    expected_counts = tuple(record[3] for record in records if record[3] > 0)
    expected_count = max(expected_counts) if expected_counts else len(stages)
    actual_indices = tuple(record[2] for record in records)
    # The modifier stack, rather than persisted metadata, is the execution
    # order used by Blender.  Native Modifier-panel drag-reordering can leave
    # the old indices on each node group, so detect that state explicitly
    # before any caller trusts the root/tip flags or stage ownership.
    index_mismatch = bool(
        len(actual_indices) != len(stages) or
        actual_indices != tuple(range(len(stages)))
    )
    missing_indices = tuple(
        index for index in range(max(expected_count, 0))
        if index not in actual_indices
    )
    duplicate_indices = tuple(sorted({
        index for index in set(actual_indices) if actual_indices.count(index) > 1
    }))
    modifier_order = tuple(getattr(target, "modifiers", ())) if target else ()
    def managed_ffd_companion(candidate):
        if getattr(candidate, "type", None) != "LATTICE":
            return False
        lattice = getattr(candidate, "object", None)
        try:
            owner_uuid = str(lattice.get(
                "_sdh_ffd_lattice_modifier", "")) if lattice else ""
        except (AttributeError, ReferenceError, TypeError):
            return False
        return bool(owner_uuid and any(
            _modifier_uuid(stage) == owner_uuid for stage in stages))

    ordinary_between = ()
    if stages:
        positions = [modifier_order.index(stage) for stage in stages
                     if stage in modifier_order]
        if positions:
            first, last = min(positions), max(positions)
            ordinary_between = tuple(
                modifier for modifier in modifier_order[first:last + 1]
                if modifier not in stages and not managed_ffd_companion(modifier)
            )
    missing_controllers = tuple(
        modifier for modifier, controller, *_rest in records if controller is None
    )
    modes = tuple(record[4] for record in records if record[4])
    mode_mismatch = len(set(modes)) > 1
    cage_types = tuple(
        str(getattr(controller.sdh_cage_deform, "cage_type", "STANDARD"))
        for _modifier, controller, *_rest in records
        if controller is not None
    )
    cage_type_mismatch = len(set(cage_types)) > 1
    broken = bool(
        not chain_uuid or not stages or expected_count != len(stages) or
        index_mismatch or missing_indices or duplicate_indices or ordinary_between or
        missing_controllers or mode_mismatch or cage_type_mismatch
    )
    messages = []
    if not chain_uuid:
        messages.append(iface_("No cage chain metadata was found"))
    if missing_indices:
        messages.append(iface_("Missing cage stages: {indices}").format(
            indices=", ".join(map(str, missing_indices))))
    if duplicate_indices:
        messages.append(iface_("Duplicate cage stage indices: {indices}").format(
            indices=", ".join(map(str, duplicate_indices))))
    if ordinary_between:
        messages.append(iface_(
            "A non-cage modifier is inserted inside the chain"))
    if missing_controllers:
        messages.append(iface_(
            "A chain stage has no matching controller"))
    if mode_mismatch:
        messages.append(iface_(
            "Chain stages use different connection modes"))
    if cage_type_mismatch:
        messages.append(iface_(
            "Chain stages use different cage types"))
    return {
        "chain_uuid": chain_uuid,
        "stages": stages,
        "records": records,
        "expected_count": expected_count,
        "actual_count": len(stages),
        "index_mismatch": index_mismatch,
        "missing_indices": missing_indices,
        "duplicate_indices": duplicate_indices,
        "ordinary_between": ordinary_between,
        "missing_controllers": missing_controllers,
        "mode_mismatch": mode_mismatch,
        "cage_type_mismatch": cage_type_mismatch,
        "broken": broken,
        "messages": tuple(messages),
    }


def _normalize_metadata(target, chain_uuid="", *, broken=None):
    chain_uuid = _resolve_chain_uuid(target, chain_uuid)
    stages = chain_stages(target, chain_uuid)
    if not stages:
        return ()
    count_values = [stage_chain_count(stage) for stage in stages if stage_chain_count(stage) > 0]
    count = max(count_values) if count_values else len(stages)
    count = max(count, len(stages))
    mode = next((stage_chain_mode(stage) for stage in stages if stage_chain_mode(stage)), "CONNECTED")
    auto_reconnect = stage_chain_auto_reconnect(stages[0], True)
    sync_shared_end_scale = stage_chain_sync_shared_end_scale(stages[0], False)
    if broken is None:
        broken = bool(validate_chain(target, chain_uuid)["broken"])
    for index, modifier in enumerate(stages):
        controller = _find_controller(target, modifier)
        # The first stage owns the chain origin and therefore cannot retain an
        # incoming gap left over from a previous stack position.
        gap = stage_chain_gap(modifier) if index > 0 else 0.0
        set_stage_metadata(modifier, controller, chain_uuid, index, count, mode,
                           gap=gap, broken=broken,
                           auto_reconnect=auto_reconnect,
                           sync_shared_end_scale=sync_shared_end_scale)
    return stages


def compact_chain(target, chain_uuid=""):
    """Renumber a live chain after an intentional stage removal.

    A deleted stage is not treated as a broken hole: the remaining stages
    become a shorter chain and retain their authored shape settings.
    """
    chain_uuid = _resolve_chain_uuid(target, chain_uuid)
    stages = chain_stages(target, chain_uuid)
    if not stages:
        return ()
    # A user deletion is allowed to close an expected index hole, but it must
    # not hide an unrelated stack fault (for example a Subdivision modifier
    # inserted between two chain stages).
    integrity = validate_chain(target, chain_uuid)
    preserve_broken = bool(
        integrity["ordinary_between"] or integrity["missing_controllers"] or
        integrity["duplicate_indices"] or integrity["mode_mismatch"]
    )
    mode = next(
        (stage_chain_mode(stage) for stage in stages if stage_chain_mode(stage)),
        "CONNECTED",
    )
    auto_reconnect = stage_chain_auto_reconnect(stages[0], True)
    sync_shared_end_scale = stage_chain_sync_shared_end_scale(stages[0], False)
    count = len(stages)
    for index, modifier in enumerate(stages):
        controller = _find_controller(target, modifier)
        gap = stage_chain_gap(modifier)
        set_stage_metadata(
            modifier, controller, chain_uuid, index, count, mode,
            gap=gap if index > 0 else 0.0, broken=preserve_broken,
            auto_reconnect=auto_reconnect,
            sync_shared_end_scale=sync_shared_end_scale,
        )
    # A removal or stack reorder changes which end profiles share a seam.
    # Metadata must be valid before the regular synchronizer can resolve those
    # new neighbors.  The tuple above already follows the live modifier stack,
    # so upstream TOP is the deterministic source for every downstream BOTTOM.
    if sync_shared_end_scale and not preserve_broken:
        for upstream in stages[:-1]:
            sync_chain_shared_end_scale(
                target, upstream, "TOP", propagate=False)
    return stages


def restore_chain_modifier_order(target, chain_uuid=""):
    """Restore persisted segment order and keep chain members contiguous."""
    chain_uuid = _resolve_chain_uuid(target, chain_uuid)
    stages = chain_stages(target, chain_uuid)
    if target is None or len(stages) < 2:
        return stages
    indexed = tuple(
        sorted(stages, key=lambda stage: stage_chain_index(stage, -1)))
    indices = tuple(stage_chain_index(stage, -1) for stage in indexed)
    if indices != tuple(range(len(indexed))):
        return ()
    modifier_stack = tuple(getattr(target, "modifiers", ()))
    positions = tuple(
        modifier_stack.index(stage) for stage in indexed
        if stage in modifier_stack)
    if len(positions) != len(indexed):
        return ()
    anchor = min(positions)
    changed = False
    for offset, stage in enumerate(indexed):
        current = tuple(target.modifiers).index(stage)
        desired = anchor + offset
        if current != desired:
            target.modifiers.move(current, desired)
            changed = True
    if changed:
        _call("ensure_ffd_companion_order", target)
        _call("invalidate_chain_affine_cache", target)
        try:
            target.update_tag()
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
    return indexed


def remap_target_chains(target):
    """Give a duplicated target fresh chain UUIDs.

    Blender copies custom properties when an object is duplicated.  Core
    ownership migration already gives the duplicate fresh target and modifier
    UUIDs, but the chain relationship lives on copied node groups as well. If
    it were left unchanged, reconnecting either object could resolve the
    other's stages.  Shape properties and stage indices are preserved; only
    the per-target chain UUID is replaced.
    """
    mapping = {}
    stages = _cage_modifiers(target)
    for modifier in stages:
        old_uuid = stage_chain_uuid(modifier)
        if not old_uuid:
            continue
        new_uuid = mapping.setdefault(old_uuid, str(uuid.uuid4()))
        group = getattr(modifier, "node_group", None)
        controller = _find_controller(target, modifier)
        index = stage_chain_index(modifier, 0)
        count = stage_chain_count(modifier, len(stages))
        mode = stage_chain_mode(modifier, "CONNECTED")
        gap = stage_chain_gap(modifier)
        metadata_owner = group if group is not None else controller
        broken = bool(_metadata_value(
            metadata_owner, LEGACY_CHAIN_BROKEN, False))
        set_stage_metadata(
            modifier, controller, new_uuid, index, count, mode,
            gap=gap, broken=broken,
            auto_reconnect=stage_chain_auto_reconnect(modifier, True),
            sync_shared_end_scale=stage_chain_sync_shared_end_scale(
                modifier, False),
        )
    return mapping


def _bounds_fallback(target):
    function = getattr(_core(), "_object_fallback_bounds", None)
    if function is not None:
        return function(target)
    points = tuple(Vector(point) for point in getattr(target, "bound_box", ()))
    if not points:
        zero = Vector((0.0, 0.0, 0.0))
        return zero, zero.copy()
    return (
        Vector(tuple(min(point[i] for point in points) for i in range(3))),
        Vector(tuple(max(point[i] for point in points) for i in range(3))),
    )


def _input_bounds(context, target, modifier):
    function = getattr(_core(), "_modifier_input_bounds", None)
    if function is not None:
        try:
            return function(context, target, modifier)
        except (RuntimeError, ReferenceError, ValueError, TypeError):
            pass
    return _bounds_fallback(target)


def _bounds_after_modifier(context, target, modifier):
    """Return bounds after ``modifier`` and before any following stage.

    ``core._modifier_input_bounds`` intentionally reports the input *before*
    a modifier.  A batch inserted after an existing active stage needs the
    opposite boundary, so evaluate a short-lived clone with modifiers through
    the requested stage enabled.  This also keeps the operation correct when
    the target already has a non-cage modifier below the active stage.
    """
    if modifier is None:
        return _bounds_fallback(target)
    core = _core()
    fallback = _bounds_fallback(target)
    try:
        stack_index = tuple(target.modifiers).index(modifier)
    except (ValueError, TypeError):
        return fallback
    clone = None
    try:
        clone = target.copy()
        clone.name = f"{target.name}_SDH_CHAIN_BOUNDS"
        marker = getattr(core, "RUNTIME_EVALUATOR", "_sdh_cage_deform_runtime_evaluator")
        clone[marker] = True
        clone.hide_render = True
        clone.hide_select = True
        clone.display_type = "BOUNDS"
        try:
            clone.animation_data_clear()
        except (AttributeError, RuntimeError):
            pass
        users_collection = tuple(getattr(target, "users_collection", ()))
        collection = users_collection[0] if users_collection else getattr(context, "collection", None)
        if collection is None:
            collection = getattr(getattr(context, "scene", None), "collection", None)
        if collection is None:
            return fallback
        collection.objects.link(clone)
        hide = getattr(core, "hide_runtime_object", None)
        if hide is not None:
            try:
                hide(clone, getattr(context, "scene", None))
            except (AttributeError, RuntimeError, TypeError):
                pass
        original = tuple(target.modifiers)
        for index, clone_modifier in enumerate(tuple(clone.modifiers)):
            clone_modifier.show_viewport = (
                index <= stack_index and
                index < len(original) and original[index].show_viewport
            )
        context.view_layer.update()
        evaluated = clone.evaluated_get(context.evaluated_depsgraph_get())
        points = tuple(Vector(point) for point in evaluated.bound_box)
        if points:
            return (
                Vector(tuple(min(point[i] for point in points) for i in range(3))),
                Vector(tuple(max(point[i] for point in points) for i in range(3))),
            )
    except (AttributeError, RuntimeError, ReferenceError, ValueError, TypeError,
            IndexError):
        return fallback
    finally:
        if clone is not None:
            try:
                bpy.data.objects.remove(clone, do_unlink=True)
            except (AttributeError, RuntimeError, ReferenceError):
                pass
    return fallback


def _alignment_rotation(alignment, bounds):
    function = getattr(_core(), "_alignment_rotation", None)
    if function is not None:
        try:
            return function(alignment, bounds)
        except (RuntimeError, ValueError, TypeError):
            pass
    if alignment == "AUTO":
        minimum, maximum = bounds
        extent = Vector(maximum) - Vector(minimum)
        alignment = ("POS_X", "POS_Y", "POS_Z")[max(range(3), key=lambda i: extent[i])]
    return {
        "POS_X": Euler((0.0, 0.0, -math.pi * 0.5)),
        "NEG_X": Euler((0.0, 0.0, math.pi * 0.5)),
        "POS_Y": Euler((0.0, 0.0, 0.0)),
        "NEG_Y": Euler((math.pi, 0.0, 0.0)),
        "POS_Z": Euler((math.pi * 0.5, 0.0, 0.0)),
        "NEG_Z": Euler((-math.pi * 0.5, 0.0, 0.0)),
    }.get(alignment, Euler((0.0, 0.0, 0.0)))


def _bounds_corners(bounds):
    minimum, maximum = Vector(bounds[0]), Vector(bounds[1])
    for x in (minimum.x, maximum.x):
        for y in (minimum.y, maximum.y):
            for z in (minimum.z, maximum.z):
                yield Vector((x, y, z))


def _stage_local_matrix(target, controller):
    """Controller frame in target-local coordinates."""
    cage_matrix = _call("cage_local_matrix", target, controller)
    if cage_matrix is None:
        rotation = getattr(_core(), "_controller_rotation_xyz", None)
        if rotation is not None:
            rotation = rotation(controller)
        else:
            rotation = controller.rotation_euler
        return Matrix.Translation(Vector(controller.location)) @ rotation.to_matrix().to_4x4()
    return _safe_inverse(target.matrix_world) @ cage_matrix


def _deform_point(point, properties, *, end_scales=None):
    core = _core()
    property_function = getattr(core, "deform_point_from_properties", None)
    if property_function is not None and end_scales is None:
        return Vector(property_function(point, properties, evaluator=True))
    function = getattr(core, "deform_point_local", None)
    if function is None:
        return Vector(point)
    legacy_type = getattr(properties, "deform_type", "BEND")
    legacy_strength = float(getattr(properties, "strength", 0.0))
    legacy_factor = float(getattr(properties, "factor", 0.0))
    legacy_direction = float(getattr(properties, "direction", 0.0))
    active_function = getattr(core, "active_deform_types", None)
    if active_function is not None:
        enabled_types = active_function(properties)
    else:
        try:
            enabled_types = set(getattr(properties, "deform_types"))
            enabled_types -= set(getattr(properties, "muted_deform_types", ()))
        except (AttributeError, TypeError):
            enabled_types = {legacy_type}
    ordered_function = getattr(core, "ordered_deform_types", None)
    operation_order = (
        tuple(name for name in ordered_function(properties)
              if name in enabled_types)
        if ordered_function is not None else None
    )
    scale_function = getattr(core, "evaluator_end_scales", None)
    if end_scales is not None:
        top_scale, bottom_scale = end_scales
    elif scale_function is not None:
        top_scale, bottom_scale = scale_function(properties)
    else:
        top_scale = properties.top_scale
        bottom_scale = properties.bottom_scale
    return Vector(function(
        point,
        size=properties.size,
        deform_type=legacy_type,
        strength=legacy_strength,
        factor=legacy_factor,
        direction=legacy_direction,
        mode=properties.mode,
        origin=properties.origin,
        preserve_volume=properties.preserve_volume,
        top_scale=top_scale,
        bottom_scale=bottom_scale,
        top_offset=properties.top_offset,
        bottom_offset=properties.bottom_offset,
        stage_enabled=bool(getattr(properties, "stage_enabled", True)),
        deform_types=enabled_types,
        bend_strength=float(getattr(
            properties, "bend_strength",
            legacy_strength if legacy_type == "BEND" else 0.0)),
        bend_direction=float(getattr(
            properties, "bend_direction", legacy_direction)),
        twist_strength=float(getattr(
            properties, "twist_strength",
            legacy_strength if legacy_type == "TWIST" else 0.0)),
        taper_factor=float(getattr(
            properties, "taper_factor",
            legacy_factor if legacy_type == "TAPER" else 0.0)),
        stretch_factor=float(getattr(
            properties, "stretch_factor",
            legacy_factor if legacy_type == "STRETCH" else 0.0)),
        shear_factors=tuple(getattr(
            properties, "shear_factors", (0.0, 0.0))),
        ffd_offsets=tuple(getattr(properties, "ffd_offsets", ())),
        # Boundary-frame sampling must evaluate the authored F(bottom), not
        # the compensated incoming sample.  The actual chained evaluator uses
        # the offset through deform_point_from_properties(evaluator=True).
        chain_input_offset=(0.0, 0.0, 0.0),
        deform_order=operation_order,
    ))


def _raw_boundary_affine(
        properties, side="BOTTOM", operation_order_override=None):
    """Return the full local affine sampled at an authored cage end."""
    core = _core()
    sample = getattr(core, "_sample_chain_affine", None)
    deform = getattr(core, "deform_point_from_properties", None)
    if sample is None or deform is None:
        raise RuntimeError("Cage Deform boundary-affine helpers are unavailable")
    half_y = max(abs(float(properties.size[1])) * 0.5, EPSILON)
    boundary_y = half_y if str(side).upper() == "TOP" else -half_y

    def raw(point):
        return deform(
            point,
            properties,
            evaluator=True,
            chain_eligible=True,
            apply_chain_input_offset=False,
            operation_order_override=operation_order_override,
        )

    # Geometry Nodes stores the resulting frame inputs as single-precision
    # values. A pure Bend stack needs a short one-sided sample to preserve
    # curvature at a split boundary. Mixed and linear stacks use a wider
    # sample, which is less sensitive to float32 quantization at a seam. Both
    # stay inside the authored cage and do not read the exterior continuation.
    try:
        enabled_types = set(_call("active_deform_types", properties) or ())
    except (TypeError, ValueError, RuntimeError):
        enabled_types = set()
    sample_fraction = 0.001 if enabled_types == {"BEND"} else 0.01
    return sample(
        raw,
        boundary_y,
        half_y,
        sample_fraction=sample_fraction,
    )


def _boundary_mapping_affine(
        target, controller, side="BOTTOM", operation_order_override=None):
    """Return a target-local input-to-output affine at one cage end."""
    frame = _stage_local_matrix(target, controller)
    local = _raw_boundary_affine(
        controller.sdh_cage_deform,
        side,
        operation_order_override=operation_order_override,
    )
    return frame @ local @ frame.inverted_safe()


def _tail_value_affine(properties, side, operation_order,
                       value_overrides=None):
    """Return the fixed-profile affine for operations after Bend.

    A boundary Jacobian includes the derivative of Twist/Taper with respect
    to Y.  Factoring that Jacobian out of a mixed Bend stack introduces shear
    into the constant chain frame.  At a split, the tail must instead be
    sampled at one fixed authored profile, matching the actual value-level
    composition used by the deformation blocks.
    """
    order = tuple(operation_order or ())
    if "BEND" not in order:
        return Matrix.Identity(4)
    tail = order[order.index("BEND") + 1:]
    if not tail:
        return Matrix.Identity(4)

    length = max(abs(float(properties.size[1])), EPSILON)
    half_y = length * 0.5
    boundary_y = half_y if str(side).upper() == "TOP" else -half_y
    origin = str(getattr(properties, "origin", "BOTTOM"))
    origin_y = {
        "BOTTOM": -half_y,
        "CENTER": 0.0,
        "SYMMETRIC": 0.0,
        "TOP": half_y,
    }.get(origin, -half_y)
    distance = boundary_y - origin_y
    lower = -half_y - origin_y
    upper = half_y - origin_y
    evaluated = min(max(distance, lower), upper)
    profile_distance = abs(evaluated) if origin == "SYMMETRIC" else evaluated
    profile = profile_distance / length

    result = Matrix.Identity(4)
    value_overrides = value_overrides or {}

    def parameter(name, fallback):
        value = value_overrides.get(name, fallback)
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            return float(fallback)

    twist_strength = parameter(
        "twist_strength", getattr(properties, "twist_strength", 0.0))
    taper_factor = parameter(
        "taper_factor", getattr(properties, "taper_factor", 0.0))
    stretch_factor = parameter(
        "stretch_factor", getattr(properties, "stretch_factor", 0.0))
    shear_values = value_overrides.get(
        "shear_factors", getattr(properties, "shear_factors", (0.0, 0.0)))
    try:
        shear_values = tuple(float(value) for value in shear_values)
    except (TypeError, ValueError, OverflowError):
        shear_values = (0.0, 0.0)
    shear_x = shear_values[0] if shear_values else 0.0
    shear_z = (
        shear_values[2] if len(shear_values) > 2 else
        shear_values[1] if len(shear_values) > 1 else 0.0)
    preserve_volume = bool(getattr(properties, "preserve_volume", True))
    for operation in tail:
        transform = Matrix.Identity(4)
        if operation == "TWIST":
            angle = twist_strength * profile
            cosine = math.cos(angle)
            sine = math.sin(angle)
            transform[0][0] = cosine
            transform[0][2] = -sine
            transform[2][0] = sine
            transform[2][2] = cosine
        elif operation == "TAPER":
            scale = 1.0 + taper_factor * profile
            transform[0][0] = scale
            transform[2][2] = scale
        elif operation == "STRETCH":
            scale = 1.0 + stretch_factor
            volume = (
                max(abs(scale), EPSILON) ** -0.5
                if preserve_volume else 1.0)
            transform[0][0] = volume
            transform[2][2] = volume
            transform.translation.y = (
                origin_y + evaluated * scale - boundary_y)
        elif operation == "SHEAR":
            transform.translation.x = shear_x * profile_distance
            transform.translation.z = shear_z * profile_distance
        result = transform @ result
    return result


def _root_output_alignment_affine(
        target, controller, desired_mapping, side="BOTTOM",
        operation_order_override=None, desired_pre_mapping=None,
        desired_post_mapping=None):
    """Map a split root's raw end frame onto the original cage end frame."""
    frame = _stage_local_matrix(target, controller)
    properties = controller.sdh_cage_deform
    if operation_order_override is None:
        active = set(_call("active_deform_types", properties) or ())
        order = tuple(
            name for name in _call(
                "ordered_deform_types", properties, default=())
            if name in active)
    else:
        order = tuple(operation_order_override)
    pre_order = (
        order[:order.index("BEND") + 1] if "BEND" in order else order)
    full = _raw_boundary_affine(
        properties, side, operation_order_override=order)
    pre = (
        full if pre_order == order else
        _raw_boundary_affine(
            properties, side, operation_order_override=pre_order))
    desired_local = frame.inverted_safe() @ desired_mapping @ frame
    if (
            "BEND" in order and desired_pre_mapping is not None and
            desired_post_mapping is not None
    ):
        desired_pre_local = (
            frame.inverted_safe() @ desired_pre_mapping @ frame)
        desired_post_local = (
            frame.inverted_safe() @ desired_post_mapping @ frame)
        stage_post = _tail_value_affine(properties, side, order)
        return (
            stage_post.inverted_safe() @ desired_post_local @
            desired_pre_local @ pre.inverted_safe()
        )
    post = full @ pre.inverted_safe()
    return post.inverted_safe() @ desired_local @ pre.inverted_safe()


def _safe_normalized(value, fallback):
    result = Vector(value)
    if result.length <= EPSILON or not all(math.isfinite(v) for v in result):
        result = Vector(fallback)
    if result.length <= EPSILON:
        result = Vector((0.0, 1.0, 0.0))
    return result.normalized()


def _rotation_from_axes(x_axis, y_axis, z_axis):
    # Columns are the local cage axes expressed in target-local space.
    matrix = Matrix((
        (x_axis.x, y_axis.x, z_axis.x),
        (x_axis.y, y_axis.y, z_axis.y),
        (x_axis.z, y_axis.z, z_axis.z),
    ))
    return matrix.to_euler("XYZ")


def _local_boundary_frame(properties, side, *, chain_preview=False,
                          extension=0.0):
    """Return a deformed cage-boundary frame in cage-local coordinates.

    The chain always progresses along increasing local Y.  For a bottom
    boundary that means sampling into the cage; for a top boundary it means
    sampling beyond the cage.  Sampling the evaluated boundary instead of the
    undeformed box is what keeps TOP/CENTER/SYMMETRIC origins seam-continuous.
    """
    half = Vector(properties.size) * 0.5
    scale_function = getattr(_core(), "evaluator_end_scales", None)
    end_scales = (
        scale_function(properties)
        if scale_function is not None else
        (properties.top_scale, properties.bottom_scale)
    )

    preview_output_frame = None
    if chain_preview:
        controller = getattr(properties, "id_data", None)
        preview_output_frame = _call(
            "chain_output_frame_for_controller", controller,
            properties=properties)

    def deformed(point):
        if chain_preview:
            function = getattr(_core(), "deform_point_for_display", None)
            if function is not None:
                return Vector(function(
                    point, properties,
                    preview_output_frame=preview_output_frame))
        return _deform_point(point, properties, end_scales=end_scales)

    extension = max(float(extension), 0.0)
    y = (
        half.y + extension
        if str(side).upper() == "TOP" else
        -half.y - extension
    )
    delta = max(min(abs(half.y) * 0.001, 0.001), EPSILON)
    endpoint = deformed((0.0, y, 0.0))
    forward = deformed((0.0, y + delta, 0.0))
    backward = deformed((0.0, y - delta, 0.0))
    tangent = forward - endpoint
    if tangent.length <= EPSILON:
        tangent = endpoint - backward
    y_axis = _safe_normalized(tangent, (0.0, 1.0, 0.0))

    x_positive = deformed((half.x, y, 0.0))
    x_negative = deformed((-half.x, y, 0.0))
    z_positive = deformed((0.0, y, half.z))
    z_negative = deformed((0.0, y, -half.z))
    x_raw = x_positive - x_negative
    z_raw = z_positive - z_negative
    x_axis = x_raw - y_axis * x_raw.dot(y_axis)
    if x_axis.length <= EPSILON:
        x_axis = y_axis.cross(z_raw)
    x_axis = _safe_normalized(x_axis, (1.0, 0.0, 0.0))
    # Keep a right-handed frame: local X cross local Y is local Z.
    z_axis = _safe_normalized(x_axis.cross(y_axis), (0.0, 0.0, 1.0))
    # Keep the cross-section roll stable when a bend approaches 180 degrees.
    if z_axis.dot(_safe_normalized(z_raw, z_axis)) < 0.0:
        x_axis.negate()
        z_axis.negate()
    return endpoint, x_axis, y_axis, z_axis


def _stage_boundary_frame(target, controller, side, *, extension=0.0):
    """Return a deformed boundary and frame in target-local coordinates."""
    properties = controller.sdh_cage_deform
    endpoint, local_x, local_y, local_z = _local_boundary_frame(
        properties, side, chain_preview=True, extension=extension)
    matrix = _stage_local_matrix(target, controller)
    linear = matrix.to_3x3()
    endpoint = matrix @ endpoint
    x_axis = _safe_normalized(linear @ local_x, linear @ Vector((1.0, 0.0, 0.0)))
    y_axis = _safe_normalized(linear @ local_y, linear @ Vector((0.0, 1.0, 0.0)))
    z_axis = _safe_normalized(x_axis.cross(y_axis), linear @ Vector((0.0, 0.0, 1.0)))
    if z_axis.dot(_safe_normalized(linear @ local_z, z_axis)) < 0.0:
        x_axis.negate()
        z_axis.negate()
    return endpoint, x_axis, y_axis, z_axis


def _stage_top_frame(target, controller, *, extension=0.0):
    """Return a top frame, optionally translated through a rigid gap."""
    if extension <= EPSILON:
        return _stage_boundary_frame(target, controller, "TOP")
    # The gap has no deformation owner.  Translate along the outgoing tangent
    # and retain the exact terminal frame instead of sampling a Bend/Twist/
    # Taper profile beyond the authored cage boundary.
    top_endpoint, top_x, top_y, top_z = _stage_boundary_frame(
        target, controller, "TOP")
    return (
        top_endpoint + top_y * float(extension),
        top_x,
        top_y,
        top_z,
    )


def _set_controller_frame(target, controller, endpoint, x_axis, y_axis, z_axis,
                          gap=0.0):
    properties = controller.sdh_cage_deform
    boundary, local_x, local_y, local_z = _local_boundary_frame(properties, "BOTTOM")
    desired = Matrix((
        (x_axis.x, y_axis.x, z_axis.x),
        (x_axis.y, y_axis.y, z_axis.y),
        (x_axis.z, y_axis.z, z_axis.z),
    ))
    local_frame = Matrix((
        (local_x.x, local_y.x, local_z.x),
        (local_x.y, local_y.y, local_z.y),
        (local_x.z, local_y.z, local_z.z),
    ))
    rotation_matrix = desired @ local_frame.inverted_safe()
    rotation = rotation_matrix.to_euler("XYZ")
    # Reconnected stages must use the same rotation order regardless of how a
    # user last edited an Empty.  Assign the mode before Euler values so
    # Blender does not reinterpret the frame through a stale quaternion or
    # axis-angle representation.
    try:
        controller.rotation_mode = "XYZ"
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    controller.rotation_euler = rotation
    controller.location = (
        Vector(endpoint) + y_axis * float(gap) - rotation_matrix @ boundary)
    return rotation


def reconnect_chain(
        target, chain_uuid="", *, allow_broken=False, start_index=0,
        runtime_only=False):
    """Propagate every upstream top frame into the next stage.

    Returns the number of downstream stages updated.  No shape property is
    touched here: segment length, angle, taper, offsets, and all other stage
    parameters remain exactly as authored by the user.
    """
    report = validate_chain(target, chain_uuid)
    chain_uuid = report["chain_uuid"]
    stages = tuple(report["stages"])
    if len(stages) < 2:
        return 0
    _call("invalidate_chain_affine_cache", target)
    # Chain indices describe physical segments. Restore them after a native
    # modifier drag instead of promoting an arbitrary middle cage to the root.
    recoverable_stack_reorder = bool(
        (report.get("index_mismatch") or report.get("ordinary_between")) and
        not any(
            report.get(name)
            for name in (
                "missing_indices", "duplicate_indices",
                "missing_controllers", "mode_mismatch", "cage_type_mismatch",
            )
        )
    )
    if recoverable_stack_reorder and not allow_broken:
        restore_chain_modifier_order(target, chain_uuid)
        report = validate_chain(target, chain_uuid)
        stages = tuple(report["stages"])
        start_index = 0
    if report["broken"] and not allow_broken:
        _normalize_metadata(target, chain_uuid, broken=True)
        return 0
    sync = getattr(_core(), "sync_controller", None)
    # The root output frame is meaningful even after a native stack repair and
    # must be synchronized before downstream propagation.
    # Resolve ownership once for this reconnect.  The previous loop performed
    # the same collection scan for both sides of every seam; on long chains
    # that amplified the Python portion of a mouse drag without changing the
    # resulting frames.
    controllers = tuple(_find_controller(target, stage) for stage in stages)
    root_controller = controllers[0] if controllers else None
    if any(controller is None for controller in controllers):
        return 0
    try:
        start_index = min(max(int(start_index), 0), len(stages) - 1)
    except (TypeError, ValueError):
        start_index = 0
    if report["broken"]:
        start_index = 0
    if sync is not None and root_controller is not None and start_index == 0:
        sync(root_controller, pull_transform=False)
    source_frame_mode = bool(
        root_controller is not None and
        stage_uses_source_frame(stages[0], root_controller))
    source_rotation = None
    source_rotation_matrix = None
    source_bottom = None
    source_cursor = 0.0
    if source_frame_mode:
        source_rotation = getattr(
            _core(), "_controller_rotation_xyz",
            lambda value: value.rotation_euler,
        )(root_controller).copy()
        source_rotation_matrix = source_rotation.to_matrix()
        root_length = max(
            abs(float(root_controller.sdh_cage_deform.size[1])), EPSILON)
        source_bottom = (
            Vector(root_controller.location) -
            source_rotation_matrix @ Vector((0.0, root_length * 0.5, 0.0)))
        source_cursor = root_length
        if start_index > 0:
            source_cursor += sum(
                max(stage_chain_gap(stages[index]), 0.0) +
                max(abs(float(
                    controllers[index].sdh_cage_deform.size[1])), EPSILON)
                for index in range(1, start_index + 1)
            )
    updated = 0
    for index in range(start_index, len(stages) - 1):
        previous = stages[index]
        current = stages[index + 1]
        previous_controller = controllers[index]
        current_controller = controllers[index + 1]
        gap = stage_chain_gap(current)
        if source_frame_mode:
            current_length = max(
                abs(float(current_controller.sdh_cage_deform.size[1])), EPSILON)
            source_cursor += gap
            current_controller.rotation_mode = "XYZ"
            current_controller.rotation_euler = source_rotation
            current_controller.location = (
                source_bottom + source_rotation_matrix @ Vector((
                    0.0, source_cursor + current_length * 0.5, 0.0)))
            source_cursor += current_length
        else:
            endpoint, x_axis, y_axis, z_axis = _stage_top_frame(
                target, previous_controller, extension=gap)
            _set_controller_frame(
                target, current_controller, endpoint, x_axis, y_axis, z_axis,
                gap=0.0)
        updated += 1
    frame_map = {}
    precompute = getattr(
        _core(), "precompute_chain_conjugation_frames", None)
    if sync is not None and callable(precompute):
        frame_map = precompute(controllers, stages)
    fast_sync = getattr(_core(), "sync_chain_runtime_inputs", None)
    if sync is not None:
        for stage, controller in zip(
                stages[start_index + 1:],
                controllers[start_index + 1:]):
            frames = frame_map.get(_pointer(controller))
            if runtime_only and frames is not None and callable(fast_sync):
                fast_sync(target, stage, controller, frames)
            elif frames is None:
                sync(controller, pull_transform=False)
            else:
                sync(
                    controller, pull_transform=False,
                    chain_frames=frames)
    # Reconnecting a valid chain changes frames, not topology. Rewriting every
    # metadata owner here made each drag perform dozens of redundant ID writes
    # (and unsupported modifier writes on Blender 5.2). Broken chains still
    # need their diagnostic metadata normalized.
    if report["broken"]:
        _normalize_metadata(target, chain_uuid, broken=True)
    try:
        target.update_tag()
    except (AttributeError, RuntimeError, TypeError):
        pass
    return updated


def redirect_chain_frame(
        target, chain_uuid="", anchor_modifier=None, alignment="POS_Z",
        bend_direction=0.0, *, context=None, fit=True):
    """Re-aim a connected chain as one rigid frame operation.

    A trend click on a middle stage used to redirect that Empty and then let
    the normal reconnect pass overwrite it from its unchanged predecessor.
    Compute one target-local rotation delta from the clicked stage and apply
    it to the whole chain. With ``fit`` enabled, the root input bounds become
    the new overall range and existing stage lengths/gaps are redistributed
    proportionally. The chain is then reconnected once, so seam tangents,
    authored end profiles, and per-stage deformation values remain intact.
    """
    report = validate_chain(target, chain_uuid)
    chain_uuid = report.get("chain_uuid", "")
    stages = tuple(report.get("stages", ()))
    if (
            report.get("broken") or len(stages) < 2 or
            stage_chain_mode(stages[0], "").upper() not in
            {"CHAINED", "CONNECTED"}
    ):
        return 0
    try:
        anchor_index = stages.index(anchor_modifier)
    except ValueError:
        anchor_index = 0
    controllers = tuple(_find_controller(target, stage) for stage in stages)
    if any(controller is None for controller in controllers):
        return 0
    anchor = controllers[anchor_index]
    root = controllers[0]
    core = _core()
    rotation_function = getattr(core, "_controller_rotation_xyz", None)
    alignment_function = getattr(core, "_alignment_rotation", None)
    if rotation_function is None or alignment_function is None:
        return 0
    try:
        old_anchor = rotation_function(anchor).to_matrix()
        desired = alignment_function(
            str(alignment or "POS_Z"),
            (Vector((0.0, 0.0, 0.0)), Vector((1.0, 1.0, 1.0))),
        ).to_matrix()
        delta = desired @ old_anchor.inverted_safe()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return 0
    fit_data = None
    if fit:
        try:
            bounds = _input_bounds(context or bpy.context, target, stages[0])
            minimum, maximum = Vector(bounds[0]), Vector(bounds[1])
            center = (minimum + maximum) * 0.5
            inverse = desired.inverted_safe()
            local_points = tuple(
                inverse @ (point - center)
                for point in _bounds_corners((minimum, maximum))
            )
            local_min = Vector(tuple(
                min(point[index] for point in local_points)
                for index in range(3)))
            local_max = Vector(tuple(
                max(point[index] for point in local_points)
                for index in range(3)))
            total_length = max(float(local_max.y - local_min.y), EPSILON)
            old_lengths = tuple(max(
                float(controller.sdh_cage_deform.size[1]), EPSILON)
                for controller in controllers)
            old_gaps = tuple(
                0.0 if index == 0 else max(stage_chain_gap(stage), 0.0)
                for index, stage in enumerate(stages))
            authored_span = sum(old_lengths) + sum(old_gaps[1:])
            if authored_span <= EPSILON:
                new_lengths = tuple(
                    total_length / len(stages) for _stage in stages)
                new_gaps = tuple(0.0 for _stage in stages)
            else:
                ratio = total_length / authored_span
                new_lengths = tuple(max(length * ratio, EPSILON)
                                    for length in old_lengths)
                new_gaps = tuple(
                    0.0 if index == 0 else gap * ratio
                    for index, gap in enumerate(old_gaps))
                measured = sum(new_lengths) + sum(new_gaps[1:])
                if measured > EPSILON:
                    correction = total_length / measured
                    new_lengths = tuple(max(
                        length * correction, EPSILON)
                        for length in new_lengths)
                    new_gaps = tuple(
                        0.0 if index == 0 else gap * correction
                        for index, gap in enumerate(new_gaps))
            cross_size = (
                max(float(local_max.x - local_min.x), EPSILON),
                max(float(local_max.z - local_min.z), EPSILON),
            )
            root_location = center + desired @ Vector((
                (local_min.x + local_max.x) * 0.5,
                local_min.y + new_lengths[0] * 0.5,
                (local_min.z + local_max.z) * 0.5,
            ))
            fit_data = {
                "lengths": new_lengths,
                "gaps": new_gaps,
                "cross_size": cross_size,
                "root_location": root_location,
            }
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            return 0
    snapshots = tuple(
        (_capture_controller_state(controller), stage_chain_gap(stage))
        for stage, controller in zip(stages, controllers)
    )
    pointers = tuple(
        pointer for pointer in (_pointer(controller) for controller in controllers)
        if pointer
    )
    syncing = getattr(core, "_SYNCING", set())
    transaction = getattr(core, "chain_reconnect_transaction", None)
    transaction_context = (
        transaction(target, chain_uuid) if transaction is not None else None)
    pivot = Vector(root.location)

    def restore():
        syncing.update(pointers)
        try:
            for stage, controller, (snapshot, old_gap) in zip(
                    stages, controllers, snapshots):
                _write_stage_gap(stage, controller, old_gap)
                _restore_controller_state(controller, snapshot, sync=False)
        finally:
            for pointer in pointers:
                syncing.discard(pointer)
        sync = getattr(core, "sync_controller", None)
        if sync is not None:
            for controller in controllers:
                sync(controller, pull_transform=False)

    def apply(commit=None):
        syncing.update(pointers)
        try:
            for index, (stage, controller) in enumerate(zip(stages, controllers)):
                controller.rotation_mode = "XYZ"
                properties = controller.sdh_cage_deform
                properties.alignment = str(alignment)
                properties.bend_direction = float(bend_direction)
                properties.direction = float(bend_direction)
                if fit_data is None:
                    local = Vector(controller.location)
                    rotation = rotation_function(controller).to_matrix()
                    controller.rotation_euler = (
                        delta @ rotation).to_euler("XYZ")
                    controller.location = pivot + delta @ (local - pivot)
                else:
                    cross_x, cross_z = fit_data["cross_size"]
                    length = fit_data["lengths"][index]
                    properties.size = (cross_x, length, cross_z)
                    controller.scale = (
                        cross_x * 0.5, length * 0.5, cross_z * 0.5)
                    _write_stage_gap(
                        stage, controller, fit_data["gaps"][index])
                    if index == 0:
                        controller.rotation_euler = desired.to_euler("XYZ")
                        controller.location = fit_data["root_location"]
        finally:
            for pointer in pointers:
                syncing.discard(pointer)
        sync = getattr(core, "sync_controller", None)
        if sync is not None:
            for controller in controllers:
                sync(controller, pull_transform=False)
        reconnect_chain(target, chain_uuid)
        try:
            target.update_tag()
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
        if commit is not None:
            commit()

    try:
        if transaction_context is None:
            apply()
        else:
            with transaction_context as commit:
                apply(commit)
    except Exception:
        try:
            if transaction is None:
                restore()
            else:
                with transaction(target, chain_uuid) as commit:
                    restore()
                    commit()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        raise
    return len(controllers)


def capture_chain_boundary_state(target, modifier, controller, side):
    """Capture every stage affected by a connected-chain boundary edit."""
    side = str(side or "").upper()
    if (
            side not in {"TOP", "BOTTOM"} or target is None or
            modifier is None or controller is None
    ):
        return None
    chain_uuid = stage_chain_uuid(modifier)
    report = validate_chain(target, chain_uuid)
    stages = tuple(report["stages"])
    if report["broken"] or len(stages) < 2:
        return None
    mode = stage_chain_mode(stages[0], "").upper()
    if mode not in {"CHAINED", "CONNECTED"}:
        return None
    try:
        active_index = stages.index(modifier)
    except ValueError:
        return None
    upstream_index = active_index if side == "TOP" else active_index - 1
    shared = 0 <= upstream_index and upstream_index + 1 < len(stages)

    records = []
    for stage in stages:
        stage_controller = _find_controller(target, stage)
        if stage_controller is None:
            return None
        properties = stage_controller.sdh_cage_deform
        records.append({
            "modifier": stage,
            "controller": stage_controller,
            "size": tuple(float(value) for value in properties.size),
            "location": tuple(float(value) for value in stage_controller.location),
            "rotation_euler": tuple(
                float(value) for value in stage_controller.rotation_euler),
            # Keep the complete local transform.  Writing ``rotation_euler``
            # while an Empty is in QUATERNION or AXIS_ANGLE mode does not
            # reliably update the active rotation channel on every Blender
            # version, so a cancel snapshot must not depend on Euler alone.
            "matrix_basis": tuple(
                tuple(float(value) for value in row)
                for row in stage_controller.matrix_basis),
            "rotation_quaternion": tuple(
                float(value) for value in stage_controller.rotation_quaternion),
            "rotation_axis_angle": tuple(
                float(value) for value in stage_controller.rotation_axis_angle),
            "rotation_mode": str(
                getattr(stage_controller, "rotation_mode", "XYZ") or "XYZ"),
            "scale": tuple(float(value) for value in stage_controller.scale),
            "gap": stage_chain_gap(stage),
        })
    if records[active_index]["controller"] != controller:
        return None
    return {
        "target": target,
        "chain_uuid": chain_uuid,
        "side": side,
        "active_index": active_index,
        "upstream_index": upstream_index,
        "shared": shared,
        "records": tuple(records),
    }


def capture_shared_boundary_edit(target, modifier, controller, side):
    """Capture a valid interior seam for a deterministic modal edit.

    The modifier-stack order is authoritative.  Metadata indices are useful
    for diagnostics, but a shared boundary must always join the two stages
    that are actually adjacent in the live stack.  Outer boundaries retain
    ordinary one-cage movement, but ``capture_chain_boundary_state`` can still
    snapshot them so cancel restores every frame changed by auto reconnect.
    """
    state = capture_chain_boundary_state(target, modifier, controller, side)
    return state if state is not None and state.get("shared") else None


def _assign_boundary_record(record):
    """Restore one captured controller without scheduling a partial sync."""
    core = _core()
    controller = record["controller"]
    properties = controller.sdh_cage_deform
    pointer = _pointer(controller)
    syncing = getattr(core, "_SYNCING", set())
    if pointer:
        syncing.add(pointer)
    try:
        properties.size = record["size"]
        # Boundary transactions may temporarily normalize a controller to the
        # stable XYZ mode used by reconnect_chain.  Restore the original mode
        # and complete matrix first.  This is important for QUATERNION and
        # AXIS_ANGLE controllers: assigning rotation_euler alone can leave the
        # active rotation channel unchanged.
        rotation_mode = str(record.get("rotation_mode", "XYZ") or "XYZ")
        try:
            controller.rotation_mode = rotation_mode
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            rotation_mode = "XYZ"
            try:
                controller.rotation_mode = rotation_mode
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        matrix_values = record.get("matrix_basis")
        if matrix_values:
            try:
                controller.matrix_basis = Matrix(tuple(
                    tuple(float(value) for value in row)
                    for row in matrix_values))
                return
            except (AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError):
                pass
        controller.location = record["location"]
        if rotation_mode == "QUATERNION" and record.get("rotation_quaternion"):
            controller.rotation_quaternion = record["rotation_quaternion"]
        elif rotation_mode == "AXIS_ANGLE" and record.get("rotation_axis_angle"):
            controller.rotation_axis_angle = record["rotation_axis_angle"]
        else:
            controller.rotation_euler = record["rotation_euler"]
        controller.scale = record["scale"]
    finally:
        if pointer:
            syncing.discard(pointer)


def apply_shared_boundary_edit(state, axis_delta, boundary_mode="SINGLE"):
    """Edit a chain boundary while preserving frames and non-negative gaps.

    ``SINGLE`` is the original seam behavior. ``TRANSLATE`` moves the active
    stage without changing its length, and ``SYMMETRIC`` expands/contracts it
    around its center.  Neighboring incoming-gap metadata is updated in the
    same transaction so reconnecting the chain cannot reintroduce overlap.
    """
    if not state:
        return None
    target = state.get("target")
    chain_uuid = str(state.get("chain_uuid", "") or "")
    records = tuple(state.get("records", ()))
    active_index = int(state.get("active_index", -1))
    side = str(state.get("side", "")).upper()
    boundary_mode = str(boundary_mode or "SINGLE").upper()
    if boundary_mode not in {"SINGLE", "TRANSLATE", "SYMMETRIC"}:
        boundary_mode = "SINGLE"
    if (
            target is None or not chain_uuid or side not in {"TOP", "BOTTOM"} or
            active_index < 0 or active_index >= len(records)
    ):
        return None
    live_stages = chain_stages(target, chain_uuid)
    if (
            len(live_stages) != len(records) or
            any(stage != record["modifier"]
                for stage, record in zip(live_stages, records))
    ):
        return None

    stage_count = len(records)
    upstream_index = active_index if side == "TOP" else active_index - 1
    shared = bool(state.get("shared", False))
    try:
        requested = float(axis_delta)
    except (TypeError, ValueError):
        requested = 0.0
    if not math.isfinite(requested):
        requested = 0.0
    core = _core()
    move_boundary = getattr(core, "move_cage_boundary", None)
    transaction = getattr(core, "chain_reconnect_transaction", None)
    if move_boundary is None or transaction is None:
        return None

    active_record = records[active_index]
    active_controller = active_record["controller"]
    active_length = max(float(active_record["size"][1]), EPSILON)
    gaps = [max(float(record.get("gap", 0.0)), 0.0)
            for record in records]

    # Resolve the requested amount from the immutable modal snapshot.  This
    # makes each mouse sample independent of event frequency and keeps the
    # chain constraints easy to reason about.
    if boundary_mode == "SINGLE":
        if not shared or upstream_index < 0 or upstream_index + 1 >= stage_count:
            return None
        upstream = records[upstream_index]
        downstream = records[upstream_index + 1]
        upstream_length = max(float(upstream["size"][1]), EPSILON)
        downstream_length = max(float(downstream["size"][1]), EPSILON)
        current_gap = max(float(downstream.get("gap", 0.0)), 0.0)
        if side == "TOP":
            applied = max(
                EPSILON - upstream_length,
                min(requested, current_gap),
            )
            move_controller = upstream["controller"]
            move_side = "TOP"
        else:
            applied = max(
                -current_gap,
                min(requested, downstream_length - EPSILON),
            )
            move_controller = downstream["controller"]
            move_side = "BOTTOM"
    elif boundary_mode == "TRANSLATE":
        # Translation of a downstream stage is represented by transferring
        # length between the incoming and outgoing gaps.  The root is free to
        # translate directly; reconnect then carries the whole chain with it.
        lower = -gaps[active_index] if active_index > 0 else -math.inf
        upper = gaps[active_index + 1] if active_index + 1 < stage_count else math.inf
        applied = min(max(requested, lower), upper)
        move_controller = active_controller
        move_side = side
    else:  # SYMMETRIC
        side_sign = 1.0 if side == "TOP" else -1.0
        q = side_sign * requested
        q_upper = min(
            gaps[active_index] if active_index > 0 else math.inf,
            gaps[active_index + 1] if active_index + 1 < stage_count else math.inf,
        )
        q_lower = (EPSILON - active_length) * 0.5
        q = min(max(q, q_lower), q_upper)
        applied = side_sign * q
        move_controller = active_controller
        move_side = side

    with transaction(target, chain_uuid) as commit:
        # Rebase the participant before every modal sample.  This keeps the
        # result independent of event rate and avoids cumulative float drift.
        for record in records:
            _assign_boundary_record(record)
        if boundary_mode == "SINGLE":
            applied, _new_length = move_boundary(
                move_controller,
                move_side,
                applied,
                (upstream if side == "TOP" else downstream)["size"],
                (upstream if side == "TOP" else downstream)["location"],
                None,
            )
            next_gap = (
                current_gap - applied if side == "TOP"
                else current_gap + applied)
            next_gap = _write_stage_gap(
                downstream["modifier"], downstream["controller"], next_gap)
        elif boundary_mode == "TRANSLATE":
            if active_index == 0:
                applied, _new_length = move_boundary(
                    active_controller, move_side, applied,
                    active_record["size"], active_record["location"], None,
                    boundary_mode="TRANSLATE")
            else:
                _new_length = active_length
            if active_index > 0:
                gaps[active_index] += applied
                _write_stage_gap(
                    records[active_index]["modifier"],
                    records[active_index]["controller"],
                    gaps[active_index])
            if active_index + 1 < stage_count:
                gaps[active_index + 1] -= applied
                _write_stage_gap(
                    records[active_index + 1]["modifier"],
                    records[active_index + 1]["controller"],
                    gaps[active_index + 1])
            next_gap = gaps[active_index]
        else:
            applied, _new_length = move_boundary(
                active_controller, move_side, applied,
                active_record["size"], active_record["location"], None,
                boundary_mode="SYMMETRIC")
            q_applied = (1.0 if side == "TOP" else -1.0) * applied
            if active_index > 0:
                gaps[active_index] -= q_applied
                _write_stage_gap(
                    records[active_index]["modifier"],
                    records[active_index]["controller"],
                    gaps[active_index])
            if active_index + 1 < stage_count:
                gaps[active_index + 1] -= q_applied
                _write_stage_gap(
                    records[active_index + 1]["modifier"],
                    records[active_index + 1]["controller"],
                    gaps[active_index + 1])
            next_gap = gaps[active_index]
        reconnect_chain(target, chain_uuid)
        try:
            target.update_tag()
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
        # The immediate reconnect supersedes the deferred request that was
        # present when this edit started.  Mark the transaction committed only
        # after both participants and all downstream frames are valid.
        commit()

    return {
        "applied_delta": float(applied),
        "active_length": float(active_controller.sdh_cage_deform.size[1]),
        "gap": float(next_gap),
        "upstream_index": upstream_index,
        "downstream_index": upstream_index + 1,
    }


def restore_shared_boundary_edit(state):
    """Restore every frame and incoming gap captured for a chain drag."""
    if not state:
        return False
    target = state.get("target")
    chain_uuid = str(state.get("chain_uuid", "") or "")
    records = tuple(state.get("records", ()))
    core = _core()
    transaction = getattr(core, "chain_reconnect_transaction", None)
    sync = getattr(core, "sync_controller", None)
    if target is None or not chain_uuid or not records or transaction is None:
        return False
    live_stages = chain_stages(target, chain_uuid)
    if (
            len(live_stages) != len(records) or
            any(stage != record["modifier"]
                for stage, record in zip(live_stages, records))
    ):
        return False
    with transaction(target, chain_uuid) as commit:
        for record in records:
            _assign_boundary_record(record)
            _write_stage_gap(
                record["modifier"], record["controller"],
                record.get("gap", stage_chain_gap(record["modifier"])))
        if sync is not None:
            for record in records:
                sync(record["controller"], pull_transform=False)
        # Restore the captured pair first, then derive every downstream frame
        # from the restored upstream stages before committing the transaction.
        reconnect_chain(target, chain_uuid)
        # reconnect_chain deliberately normalizes generated frames to XYZ.  A
        # cancelled modal edit must still restore an Empty's original rotation
        # order and exact frame, including Quaternion/Axis Angle controllers.
        # Reapply the complete capture after propagation, then push it once to
        # the node groups so the visible and evaluated state agree.
        for record in records:
            _assign_boundary_record(record)
        if sync is not None:
            for record in records:
                sync(record["controller"], pull_transform=False)
        try:
            target.update_tag()
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
        commit()
    return True


def _copy_template(destination, source, *, mode):
    if source is not None:
        copier = getattr(_core(), "_copy_controller_state", None)
        if copier is not None:
            copier(destination, source)
        else:
            src = source.sdh_cage_deform
            dst = destination.sdh_cage_deform
            for name in (
                "deform_order", "active_deform_layer", "stage_enabled",
                "deform_types",
                "muted_deform_types",
                "bend_strength", "bend_direction",
                "twist_strength", "taper_factor", "stretch_factor",
                "shear_factors", "ffd_offsets",
                "deform_type", "strength", "factor", "direction", "size",
                "mode", "origin", "alignment", "preserve_volume",
                "auto_reconnect", "auto_sync_upstream",
                "sync_shared_end_scale",
                "top_scale", "bottom_scale", "top_offset", "bottom_offset"):
                if hasattr(src, name):
                    value = getattr(src, name)
                    setattr(dst, name, tuple(value) if hasattr(value, "__len__") and not isinstance(value, str) else value)
            destination.location = source.location
            rotation = getattr(_core(), "_controller_rotation_xyz", None)
            source_rotation = (
                rotation(source) if rotation is not None else source.rotation_euler)
            try:
                destination.rotation_mode = "XYZ"
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
            destination.rotation_euler = source_rotation
            destination.scale = source.scale
    properties = destination.sdh_cage_deform
    # Connected chains preserve the source Origin on every stage; independent
    # segments are isolated boxes and do not affect geometry outside them.
    if mode == "CHAINED":
        properties.mode = "CHAINED"
    else:
        properties.mode = "WITHIN_BOX"
    return properties


def _cleanup_created(target, created):
    for modifier, controller in reversed(tuple(created)):
        group = getattr(modifier, "node_group", None)
        remove_ffd = getattr(_core(), "remove_ffd_lattice", None)
        if remove_ffd is not None:
            try:
                remove_ffd(target, modifier)
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                pass
        try:
            if modifier in tuple(target.modifiers):
                target.modifiers.remove(modifier)
        except (ReferenceError, RuntimeError):
            pass
        if controller is not None:
            try:
                bpy.data.objects.remove(controller, do_unlink=True)
            except (ReferenceError, RuntimeError):
                pass
        if group is not None:
            try:
                if group.users == 0:
                    bpy.data.node_groups.remove(group)
            except (ReferenceError, RuntimeError):
                pass
    cleanup = getattr(_core(), "remove_unused_control_collections", None)
    if cleanup is not None:
        cleanup()


def _ffd_grid_offset(properties, u, v, w, offsets=None):
    """Sample a source FFD field with trilinear control-point interpolation.

    Blender's native lattice interpolation can be higher order, but linear
    resampling is deterministic and gives subdivided stages the same boundary
    values for every supported Blender version.  The authored interpolation
    mode remains copied to each stage for subsequent edits.
    """
    core = _core()
    resolution = tuple(core.ffd_resolution(properties))
    for axis, value in enumerate((u, v, w)):
        if resolution[axis] <= 1:
            continue
        if not math.isfinite(float(value)):
            value = 0.0
        if axis == 0:
            u = min(max(float(value), 0.0), 1.0)
        elif axis == 1:
            v = min(max(float(value), 0.0), 1.0)
        else:
            w = min(max(float(value), 0.0), 1.0)

    def axis_pair(value, count):
        scaled = min(max(float(value), 0.0), 1.0) * max(count - 1, 1)
        lower = min(int(math.floor(scaled)), max(count - 2, 0))
        return lower, min(lower + 1, count - 1), scaled - lower

    u0, u1, fu = axis_pair(u, resolution[0])
    v0, v1, fv = axis_pair(v, resolution[1])
    w0, w1, fw = axis_pair(w, resolution[2])
    result = Vector((0.0, 0.0, 0.0))
    for uu, wu in ((u0, 1.0 - fu), (u1, fu)):
        for vv, wv in ((v0, 1.0 - fv), (v1, fv)):
            for ww, wwgt in ((w0, 1.0 - fw), (w1, fw)):
                index = core.ffd_point_index(uu, vv, ww, resolution)
                value = (
                    offsets[index] if offsets is not None else
                    core.ffd_point_effective_offset(properties, index))
                result += Vector(value) * (
                    wu * wv * wwgt)
    return result


def _ffd_resampled_offsets(properties, start, end, resolution, offsets=None):
    """Return native-basis control offsets for one physical FFD slice."""
    core = _core()
    ru, rv, rw = (int(value) for value in resolution)
    source_resolution = tuple(core.ffd_resolution(properties))
    source_v = source_resolution[1]
    interpolation = getattr(
        properties, "ffd_interpolation_v", "KEY_BSPLINE")
    local_samples = tuple(
        value / max(rv - 1, 1) for value in range(rv))
    span = max(float(end) - float(start), 0.0)
    global_samples = tuple(
        float(start) + span * value for value in local_samples)
    source_weights = _native_ffd_axis_weights(
        source_v, interpolation, global_samples)
    stage_weights = _native_ffd_axis_weights(
        rv, interpolation, local_samples)
    inverse = _invert_dense_matrix(stage_weights)
    if inverse is None:
        # A malformed legacy lattice should still be subdividable.  The
        # linear fallback is deterministic and matches the pre-2.4 path.
        values = []
        for w in range(rw):
            w_t = w / max(rw - 1, 1)
            for v in range(rv):
                local_t = local_samples[v]
                source_t = float(start) + span * local_t
                for u in range(ru):
                    u_t = u / max(ru - 1, 1)
                    values.append(tuple(_ffd_grid_offset(
                        properties, u_t, source_t, w_t, offsets=offsets)))
        return tuple(values)

    def source_value(u, v, w):
        index = core.ffd_point_index(u, v, w, source_resolution)
        return Vector(
            offsets[index] if offsets is not None else
            core.ffd_point_effective_offset(properties, index))

    values_by_v = {}
    for w in range(rw):
        source_w = w / max(rw - 1, 1) * max(source_resolution[2] - 1, 1)
        w0 = min(max(int(math.floor(source_w)), 0), source_resolution[2] - 1)
        w1 = min(w0 + 1, source_resolution[2] - 1)
        fw = source_w - w0
        for u in range(ru):
            source_u = u / max(ru - 1, 1) * max(source_resolution[0] - 1, 1)
            u0 = min(max(int(math.floor(source_u)), 0), source_resolution[0] - 1)
            u1 = min(u0 + 1, source_resolution[0] - 1)
            fu = source_u - u0
            desired = []
            for row_weights in source_weights:
                value = Vector((0.0, 0.0, 0.0))
                for source_index, weight in enumerate(row_weights):
                    # The native V basis is solved exactly; U/W retain their
                    # authored grid and are bilinearly sampled only when a
                    # capped legacy resolution differs from the source.
                    value += (
                        source_value(u0, source_index, w0) *
                        (1.0 - fu) * (1.0 - fw) * weight
                    )
                    if u1 != u0:
                        value += source_value(u1, source_index, w0) * fu * (
                            1.0 - fw) * weight
                    if w1 != w0:
                        value += source_value(u0, source_index, w1) * (
                            1.0 - fu) * fw * weight
                        if u1 != u0:
                            value += source_value(u1, source_index, w1) * (
                                fu * fw * weight)
                desired.append(value)
            controls = []
            for control_index in range(rv):
                value = Vector((0.0, 0.0, 0.0))
                for sample_index, weight in enumerate(inverse[control_index]):
                    value += desired[sample_index] * weight
                controls.append(tuple(value))
            values_by_v[(u, w)] = tuple(controls)

    values = []
    for w in range(rw):
        for v in range(rv):
            for u in range(ru):
                values.append(values_by_v[(u, w)][v])
    return tuple(values)


def _set_ffd_stage_offsets(
        properties, values, resolution, influences=None):
    """Resize and assign a dedicated FFD point collection atomically."""
    core = _core()
    pointer = _pointer(getattr(properties, "id_data", None))
    syncing = getattr(core, "_SYNCING", set())
    if pointer:
        syncing.add(pointer)
    try:
        properties.ffd_resolution_u = int(resolution[0])
        properties.ffd_resolution_v = int(resolution[1])
        properties.ffd_resolution_w = int(resolution[2])
        core.ensure_ffd_point_collection(properties, preserve=False)
        if influences is None:
            influences = (1.0,) * len(values)
        for point, value, influence in zip(
                properties.ffd_points, values, influences):
            point.offset = tuple(float(component) for component in value)
            if hasattr(point, "influence"):
                point.influence = min(max(float(influence), 0.0), 1.0)
            point.selected = False
    finally:
        if pointer:
            syncing.discard(pointer)


def _capture_ffd_selection(properties):
    """Capture FFD selection in normalized UVW coordinates, not raw indices."""
    core = _core()
    resolution = tuple(core.ffd_resolution(properties))
    selected = tuple(
        index for index, point in enumerate(getattr(properties, "ffd_points", ()))
        if bool(getattr(point, "selected", False))
    )
    coordinates = tuple(
        tuple(
            float(axis) / max(int(size) - 1, 1)
            for axis, size in zip(core.ffd_point_coordinates(index, resolution), resolution)
        )
        for index in selected
    )
    active = int(getattr(properties, "ffd_active_point", 0))
    active_coordinate = None
    if 0 <= active < math.prod(resolution):
        active_coordinate = tuple(
            float(axis) / max(int(size) - 1, 1)
            for axis, size in zip(core.ffd_point_coordinates(active, resolution), resolution)
        )
    return coordinates, active_coordinate


def _restore_ffd_selection(properties, snapshot):
    """Restore selected/active FFD points after a chain stage rebuild."""
    if not snapshot:
        return
    core = _core()
    resolution = tuple(core.ffd_resolution(properties))
    count = math.prod(resolution)

    def nearest(coordinate):
        if coordinate is None:
            return None
        return min(
            range(count),
            key=lambda index: sum(
                (
                    float(axis) / max(int(size) - 1, 1) - float(value)
                ) ** 2
                for axis, size, value in zip(
                    core.ffd_point_coordinates(index, resolution),
                    resolution,
                    coordinate,
                )
            ),
        )

    selected = {
        index for coordinate in snapshot[0]
        if (index := nearest(coordinate)) is not None
    }
    active = nearest(snapshot[1])
    core.ffd_set_selection(properties, selected, active=active)


def _ffd_selection_for_stage(
        snapshot, stage_range, *, stage_index=0, all_ranges=()):
    """Map global normalized FFD selection into one chained stage domain.

    A non-zero chain gap is not owned by any stage.  A selected source point
    that lands in such a gap is assigned to the nearest segment boundary so a
    segment-count change cannot silently clear it.
    """
    if not snapshot:
        return (), None
    start, end = (float(value) for value in stage_range)
    span = max(end - start, EPSILON)

    def localize(coordinate):
        if coordinate is None:
            return None
        value = float(coordinate[1])
        if value < start - 1.0e-6 or value > end + 1.0e-6:
            ranges = tuple(all_ranges or ())
            if not ranges:
                return None
            distances = tuple(
                0.0 if lower - 1.0e-6 <= value <= upper + 1.0e-6
                else min(abs(value - lower), abs(value - upper))
                for lower, upper in ranges
            )
            nearest = min(
                range(len(distances)),
                key=lambda index: (distances[index], index),
            )
            if nearest != int(stage_index):
                return None
            value = min(max(value, start), end)
        return (
            float(coordinate[0]),
            min(max((value - start) / span, 0.0), 1.0),
            float(coordinate[2]),
        )

    selected = tuple(
        local for coordinate in snapshot[0]
        if (local := localize(coordinate)) is not None
    )
    active = localize(snapshot[1])
    return selected, active


def _subdivide_ffd_cage_to_chain(context, target, source_modifier,
                                  source_controller, operator):
    """Split a dedicated FFD into same-type chained native lattices."""
    core = _core()
    source_properties = source_controller.sdh_cage_deform
    source_ffd_selection = _capture_ffd_selection(source_properties)
    source_snapshot = _capture_controller_state(source_controller)
    source_metadata = tuple(
        (owner, _capture_owner_metadata(owner))
        for owner in (
            source_modifier,
            getattr(source_modifier, "node_group", None),
            source_controller,
        )
    )
    source_origin = str(getattr(source_properties, "origin", "BOTTOM"))
    if source_origin != "BOTTOM":
        operator.report(
            {"WARNING"},
            iface_("Non-Bottom origin may introduce subdivision errors"),
        )
    flush = getattr(core, "flush_pending_chain_updates", None)
    if flush is not None:
        flush(target)
    sync = getattr(core, "sync_controller", None)
    if sync is not None:
        sync(source_controller, pull_transform=True, sync_mode="timer")
    source_properties = source_controller.sdh_cage_deform
    original_size = tuple(
        max(float(value), EPSILON) for value in source_properties.size)
    total_length = original_size[1]
    count = max(int(getattr(operator, "count", 3)), 2)
    requested_gap = max(float(getattr(operator, "gap", 0.0)), 0.0)
    gap = min(
        requested_gap,
        max((total_length - count * EPSILON) / max(count - 1, 1), 0.0),
    )
    segment_length = max(
        (total_length - gap * max(count - 1, 0)) / count, EPSILON)
    ranges = []
    cursor = 0.0
    for index in range(count):
        cursor += gap if index else 0.0
        ranges.append((cursor / total_length,
                       (cursor + segment_length) / total_length))
        cursor += segment_length
    ranges = tuple(ranges)
    source_resolution = tuple(core.ffd_resolution(source_properties))
    # Each restricted spline segment needs enough native degrees of freedom
    # to reproduce the source basis.  Retaining the source V resolution (with
    # four controls for cubic modes) avoids the old two-layer linear collapse.
    stage_resolution_v = min(
        int(getattr(core, "FFD_MAX_RESOLUTION_V", 6)),
        max(4, int(source_resolution[1])),
    )
    stage_resolution = (
        source_resolution[0], stage_resolution_v, source_resolution[2])
    rotation_function = getattr(core, "_controller_rotation_xyz", None)
    base_rotation = (
        rotation_function(source_controller).copy()
        if rotation_function is not None else
        source_controller.rotation_euler.copy())
    rotation_matrix = base_rotation.to_matrix()
    base_location = Vector(source_controller.location)
    original_bottom = base_location + rotation_matrix @ Vector((
        0.0, -total_length * 0.5, 0.0))
    source_offsets = tuple(
        tuple(core.ffd_point_offset(source_properties, index))
        for index in range(math.prod(source_resolution))
    )
    source_influences = tuple(
        float(getattr(source_properties.ffd_points[index], "influence", 1.0))
        if index < len(getattr(source_properties, "ffd_points", ())) else 1.0
        for index in range(math.prod(source_resolution))
    )
    source_effective_offsets = tuple(
        tuple(Vector(offset) * influence)
        for offset, influence in zip(source_offsets, source_influences)
    )
    source_influence_vectors = tuple(
        (influence, 0.0, 0.0) for influence in source_influences)
    # Resample every slice before mutating the source stage.  A low-resolution
    # source (the default 2x2x2 FFD) is promoted to at least four V controls
    # for the chained spline.  Once the first stage is resized, reading
    # ``source_properties`` again would describe the promoted grid while
    # ``source_offsets`` still contains the original eight points, causing the
    # second slice to index beyond that immutable snapshot.
    stage_effective_offsets = tuple(
        _ffd_resampled_offsets(
            source_properties,
            *stage_range,
            stage_resolution,
            offsets=source_effective_offsets,
        )
        for stage_range in ranges
    )
    stage_influence_vectors = tuple(
        _ffd_resampled_offsets(
            source_properties,
            *stage_range,
            stage_resolution,
            offsets=source_influence_vectors,
        )
        for stage_range in ranges
    )
    stage_raw_offsets = []
    stage_influences = []
    for effective_values, influence_values in zip(
            stage_effective_offsets, stage_influence_vectors):
        raw_values = []
        weights = []
        for effective, influence_vector in zip(
                effective_values, influence_values):
            influence = min(max(float(influence_vector[0]), 0.0), 1.0)
            weights.append(influence)
            if influence > EPSILON:
                raw_values.append(tuple(
                    float(component) / influence for component in effective))
            else:
                raw_values.append((0.0, 0.0, 0.0))
        stage_raw_offsets.append(tuple(raw_values))
        stage_influences.append(tuple(weights))
    stage_raw_offsets = tuple(stage_raw_offsets)
    stage_influences = tuple(stage_influences)
    previous_active_modifier = getattr(target.modifiers, "active", None)
    previous_active_object = getattr(context.view_layer.objects, "active", None)
    previous_selected = tuple(getattr(context, "selected_objects", ()))
    created = []
    stages = [(source_modifier, source_controller)]
    creator = getattr(core, "create_deform_stage", None)
    if creator is None:
        operator.report({"ERROR"}, iface_("Cage Deform core is unavailable"))
        return {"CANCELLED"}
    template = getattr(core, "ensure_node_group", lambda: None)()
    chain_uuid = str(uuid.uuid4())
    try:
        after = source_modifier
        for index in range(1, count):
            modifier, controller, _old_active = creator(
                context,
                target,
                name=f"{source_modifier.name} {index + 1:02d}",
                after_modifier=after,
                show_other_default=True,
                node_group_template=template,
                skip_stage_maintenance=True,
                fit_stage=False,
                cage_type="FFD",
            )
            created.append((modifier, controller))
            stages.append((modifier, controller))
            _copy_template(controller, source_controller, mode="CHAINED")
            after = modifier

        syncing = getattr(core, "_SYNCING", set())
        pointers = tuple(
            pointer for _modifier, controller in stages
            if (pointer := _pointer(controller)))
        syncing.update(pointers)
        try:
            for index, (modifier, controller) in enumerate(stages):
                properties = controller.sdh_cage_deform
                properties.mode = "CHAINED"
                properties.origin = "BOTTOM"
                properties.auto_reconnect = bool(
                    getattr(operator, "auto_reconnect", True))
                properties.sync_shared_end_scale = bool(
                    getattr(operator, "sync_shared_end_scale", True))
                properties.show_other_cages = True
                properties.size = (
                    original_size[0], segment_length, original_size[2])
                _set_ffd_stage_offsets(
                    properties,
                    stage_raw_offsets[index],
                    stage_resolution,
                    stage_influences[index],
                )
                _restore_ffd_selection(
                    properties,
                    _ffd_selection_for_stage(
                        source_ffd_selection,
                        ranges[index],
                        stage_index=index,
                        all_ranges=ranges,
                    ),
                )
                controller.rotation_mode = "XYZ"
                controller.rotation_euler = base_rotation
                controller.location = original_bottom + rotation_matrix @ Vector((
                    0.0,
                    ranges[index][0] * total_length + segment_length * 0.5,
                    0.0,
                ))
                controller.scale = tuple(
                    max(float(value), EPSILON) * 0.5
                    for value in properties.size)
                set_stage_metadata(
                    modifier,
                    controller,
                    chain_uuid,
                    index,
                    count,
                    "CHAINED",
                    gap=gap if index else 0.0,
                    auto_reconnect=bool(getattr(
                        operator, "auto_reconnect", True)),
                    sync_shared_end_scale=bool(getattr(
                        operator, "sync_shared_end_scale", True)),
                )
        finally:
            for pointer in pointers:
                syncing.discard(pointer)
        if sync is not None:
            for _modifier, controller in stages:
                sync(controller, pull_transform=False)
        reconnect_chain(target, chain_uuid)
        # Reconnect updates downstream controller frames after the initial
        # native lattices were built. Flush those final frames immediately so
        # the operator returns with matching scope groups and does not rely on
        # the next runtime timer tick.
        try:
            context.view_layer.update()
        except (AttributeError, ReferenceError, RuntimeError):
            pass
        if sync is not None:
            for _modifier, controller in stages:
                sync(
                    controller,
                    pull_transform=False,
                    sync_mode="timer",
                )
        _normalize_metadata(target, chain_uuid, broken=False)
        show_all = getattr(core, "_sync_target_show_other_cages", None)
        if show_all is not None:
            show_all(target, True)
        target.modifiers.active = source_modifier
        _activate(context, source_controller)
        refresh = getattr(core, "refresh_controller_display", None)
        if refresh is not None:
            refresh(context, force=True)
        operator.report(
            {"INFO"},
            iface_("Subdivided FFD cage into {count} chained stages").format(
                count=count),
        )
        _report_chain_performance_warning(operator, count)
        return {"FINISHED"}
    except Exception as error:
        _cleanup_created(target, created)
        for owner, snapshot in source_metadata:
            _restore_owner_metadata(owner, snapshot)
        _restore_controller_state(source_controller, source_snapshot)
        try:
            target.modifiers.active = previous_active_modifier
        except (AttributeError, ReferenceError, RuntimeError):
            pass
        for selected in tuple(getattr(context, "selected_objects", ())):
            try:
                selected.select_set(False)
            except (ReferenceError, RuntimeError):
                pass
        for selected in previous_selected:
            try:
                selected.select_set(True)
            except (ReferenceError, RuntimeError):
                pass
        try:
            context.view_layer.objects.active = previous_active_object
        except (AttributeError, ReferenceError, RuntimeError):
            pass
        operator.report(
            {"WARNING"},
            iface_("Could not subdivide FFD cage: {error}").format(
                error=error),
        )
        return {"CANCELLED"}


_CHAIN_METADATA_KEYS = (
    CHAIN_UUID,
    CHAIN_INDEX,
    CHAIN_COUNT,
    CHAIN_MODE,
    CHAIN_ROLE,
    CHAIN_GAP,
    CHAIN_AUTO_RECONNECT,
    CHAIN_SYNC_SHARED_END_SCALE,
    CHAIN_ROOT_OUTPUT_AFFINE,
    CHAIN_VERSION_KEY,
    LEGACY_CHAIN_ID,
    LEGACY_CHAIN_BROKEN,
)


def _copied_value(value):
    if isinstance(value, set):
        return set(value)
    if isinstance(value, (str, bytes, bool, int, float)) or value is None:
        return value
    try:
        return tuple(value)
    except TypeError:
        return value


def _capture_controller_state(controller):
    core = _core()
    properties = controller.sdh_cage_deform
    names = getattr(core, "CONTROLLER_STATE_PROPERTIES", ())
    return {
        "properties": {
            name: _copied_value(getattr(properties, name))
            for name in names if hasattr(properties, name)
        },
        "matrix_basis": tuple(
            tuple(float(component) for component in row)
            for row in controller.matrix_basis
        ),
        "rotation_mode": str(getattr(controller, "rotation_mode", "XYZ")),
        # Keep the authored transform channels as well as the evaluated matrix.
        # Reassigning matrix_basis makes Blender decompose it and can perturb a
        # quaternion by a few ULPs, which means a cancelled transaction is no
        # longer truly side-effect free.
        "location": tuple(float(value) for value in controller.location),
        "scale": tuple(float(value) for value in controller.scale),
        "rotation_euler": tuple(
            float(value) for value in controller.rotation_euler),
        "rotation_quaternion": tuple(
            float(value) for value in controller.rotation_quaternion),
        "rotation_axis_angle": tuple(
            float(value) for value in controller.rotation_axis_angle),
        "delta_location": tuple(
            float(value) for value in controller.delta_location),
        "delta_scale": tuple(float(value) for value in controller.delta_scale),
        "delta_rotation_euler": tuple(
            float(value) for value in controller.delta_rotation_euler),
        "delta_rotation_quaternion": tuple(
            float(value) for value in controller.delta_rotation_quaternion),
    }


def _restore_controller_state(controller, snapshot, *, sync=True):
    core = _core()
    pointer = _pointer(controller)
    syncing = getattr(core, "_SYNCING", set())
    if pointer:
        syncing.add(pointer)
    try:
        properties = controller.sdh_cage_deform
        for name, value in snapshot.get("properties", {}).items():
            setattr(properties, name, value)
        rotation_mode = snapshot.get("rotation_mode", "XYZ")
        try:
            controller.rotation_mode = rotation_mode
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            rotation_mode = "XYZ"
            controller.rotation_mode = rotation_mode

        if "location" not in snapshot:
            controller.matrix_basis = Matrix(snapshot["matrix_basis"])
        else:
            controller.location = snapshot["location"]
            controller.scale = snapshot["scale"]
            controller.delta_location = snapshot["delta_location"]
            controller.delta_scale = snapshot["delta_scale"]
            if rotation_mode == "QUATERNION":
                controller.rotation_quaternion = snapshot["rotation_quaternion"]
                controller.delta_rotation_quaternion = snapshot[
                    "delta_rotation_quaternion"]
            elif rotation_mode == "AXIS_ANGLE":
                controller.rotation_axis_angle = snapshot["rotation_axis_angle"]
                # Delta rotation has no axis-angle channel in Blender RNA.
                controller.delta_rotation_euler = snapshot[
                    "delta_rotation_euler"]
            else:
                controller.rotation_euler = snapshot["rotation_euler"]
                controller.delta_rotation_euler = snapshot[
                    "delta_rotation_euler"]
    finally:
        if pointer:
            syncing.discard(pointer)
    if sync:
        sync_controller = getattr(core, "sync_controller", None)
        if sync_controller is not None:
            sync_controller(controller, pull_transform=False)


def _capture_owner_metadata(owner):
    if owner is None:
        return None
    result = {}
    for key in _CHAIN_METADATA_KEYS:
        try:
            result[key] = (key in owner, _copied_value(owner.get(key)))
        except (AttributeError, ReferenceError, TypeError):
            result[key] = (False, None)
    return result


def _restore_owner_metadata(owner, snapshot):
    if owner is None or snapshot is None:
        return
    for key, (present, value) in snapshot.items():
        try:
            if present:
                owner[key] = value
            elif key in owner:
                del owner[key]
        except (AttributeError, KeyError, ReferenceError, RuntimeError, TypeError):
            pass


def _safe_collection(owner, attribute):
    """Read an RNA collection without letting version-specific access fail."""
    if owner is None:
        return ()
    try:
        value = getattr(owner, attribute, ())
        return tuple(value) if value is not None else ()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ()


def _iter_action_fcurves(action):
    """Yield F-Curves from legacy and layered Blender Actions.

    Blender 4.2 exposes ``Action.fcurves`` directly.  Newer releases can store
    curves in ``Action.layers[*].strips[*].channelbags[*].fcurves`` instead;
    some releases expose a singular ``channelbag`` accessor.  The guarded,
    de-duplicated traversal keeps this add-on usable across both layouts.
    """
    if action is None:
        return
    seen = set()

    def emit(curves):
        for curve in curves:
            try:
                marker = _pointer(curve) or id(curve)
            except Exception:
                marker = id(curve)
            if marker in seen:
                continue
            seen.add(marker)
            yield curve

    yield from emit(_safe_collection(action, "fcurves"))
    for layer in _safe_collection(action, "layers"):
        for strip in _safe_collection(layer, "strips"):
            # A few development builds exposed strip-level curves directly.
            yield from emit(_safe_collection(strip, "fcurves"))
            channelbags = _safe_collection(strip, "channelbags")
            if not channelbags:
                channelbag = getattr(strip, "channelbag", None)
                if callable(channelbag):
                    # ``channelbag`` may require an ActionSlot in layered
                    # Actions.  Calling it without one is only a probe; the
                    # normal collection path above handles supported builds.
                    try:
                        channelbag = channelbag()
                    except (AttributeError, ReferenceError, RuntimeError,
                            TypeError, ValueError):
                        channelbag = None
                channelbags = (channelbag,) if channelbag is not None else ()
            for channelbag in channelbags:
                yield from emit(_safe_collection(channelbag, "fcurves"))


def _iter_nla_actions(animation):
    """Yield Actions referenced by NLA strips, including nested meta strips."""
    if animation is None:
        return
    seen = set()

    def walk_strip(strip):
        marker = _pointer(strip) or id(strip)
        if marker in seen:
            return
        seen.add(marker)
        action = getattr(strip, "action", None)
        if action is not None:
            yield action
        for nested in _safe_collection(strip, "strips"):
            yield from walk_strip(nested)

    for track in _safe_collection(animation, "nla_tracks"):
        for strip in _safe_collection(track, "strips"):
            yield from walk_strip(strip)


def _iter_owner_animation_fcurves(owner):
    """Yield Action/NLA curves and drivers owned by an RNA ID."""
    animation = getattr(owner, "animation_data", None)
    if animation is None:
        return
    action = getattr(animation, "action", None)
    if action is not None:
        yield from _iter_action_fcurves(action)
    for action in _iter_nla_actions(animation):
        yield from _iter_action_fcurves(action)
    for curve in _safe_collection(animation, "drivers"):
        yield curve


def _owner_has_animation(owner):
    """Return whether ``owner`` contains any animated channels or drivers."""
    return any(True for _curve in _iter_owner_animation_fcurves(owner))


def _source_has_split_animation(target, modifier, controller):
    """Return whether one stage owns animation that cannot be divided safely."""
    # Controller and node-group animation can target the authored stage's
    # absolute parameters.  Splitting those curves would require keyframe
    # remapping, so reject the operation conservatively.
    for owner in (
            controller,
            modifier,
            getattr(modifier, "node_group", None),
    ):
        if _owner_has_animation(owner):
            return True

    # Object animation is safe unless it explicitly addresses this modifier.
    # Check Action, NLA and layered Action curves through the same iterator.
    animation = getattr(target, "animation_data", None)
    if animation is None:
        return False
    marker_tokens = {
        f'modifiers["{getattr(modifier, "name", "")}"]',
        f"modifiers['{getattr(modifier, 'name', '')}']",
    }
    for curve in _iter_owner_animation_fcurves(target):
        path = str(getattr(curve, "data_path", ""))
        if any(token and token in path for token in marker_tokens):
            return True
    return False


def _lerp_pair(first, second, factor):
    factor = min(max(float(factor), 0.0), 1.0)
    return tuple(
        float(a) + (float(b) - float(a)) * factor
        for a, b in zip(first, second)
    )


def _chain_mode(operator):
    value = getattr(operator, "connection_mode", "CHAINED")
    # Keep old callers working: mode/connected used the CONNECTED spelling.
    legacy = getattr(operator, "mode", "")
    # ``connection_mode`` is the public property.  Only let the hidden legacy
    # value override its default; otherwise an explicit INDEPENDENT selection
    # would be masked by the legacy property's CONNECTED default.
    if value == "CHAINED" and legacy in {"CONNECTED", "CHAINED", "INDEPENDENT"}:
        value = legacy
    if getattr(operator, "connected", True) is False:
        value = "INDEPENDENT"
    return "CHAINED" if value in {"CHAINED", "CONNECTED"} else "WITHIN_BOX"


CHAIN_PERFORMANCE_WARNING_THRESHOLD = 3
CHAIN_PERFORMANCE_WARNING = (
    "More than 3 cage stages may reduce viewport performance")


def _draw_chain_performance_warning(layout, count):
    """Show the non-blocking chain cost warning as soon as count exceeds 3."""
    if int(count) <= CHAIN_PERFORMANCE_WARNING_THRESHOLD:
        return False
    warning = layout.box()
    warning.alert = True
    warning.label(
        text=iface_(
            "More than 3 cage stages may reduce viewport performance"),
        icon="ERROR",
    )
    return True


def _report_chain_performance_warning(operator, count):
    """Report the same warning for direct EXEC_DEFAULT/scripted callers."""
    if int(count) <= CHAIN_PERFORMANCE_WARNING_THRESHOLD:
        return False
    operator.report(
        {"WARNING"},
        iface_("More than 3 cage stages may reduce viewport performance"),
    )
    return True


class SDH_OT_add_cage_chain(Operator):
    bl_idname = "sdh.add_cage_chain"
    bl_label = "Add Cage Chain"
    bl_description = "Create several related deformation cages in one operation"
    bl_options = {"REGISTER", "UNDO"}

    count: IntProperty(
        name="Cage Count",
        description="Number of segments to create",
        default=3,
        min=2,
        max=8,
    )
    cage_type: EnumProperty(
        name="Cage Type",
        description="Create a chain whose stages all use this cage type",
        items=(
            ("STANDARD", "Standard Type", "Create a layered Standard chain"),
            ("SHEAR", "Shear Cage", "Create a Shear-only chain"),
            ("FFD", "FFD Cage", "Create an FFD-only chain"),
        ),
        default="STANDARD",
    )
    connection_mode: EnumProperty(
        name="Connection Mode",
        description="How neighboring cage segments handle their boundaries",
        items=(
            (
                "CHAINED",
                "Chained",
                "The chain root extends continuously beyond both boundaries; later cages preserve the upstream prefix and continue from the cage end",
            ),
            ("INDEPENDENT", "Independent", "Limit each segment to its own box"),
        ),
        default="CHAINED",
    )
    # Aliases are intentionally hidden from the normal dialog but make the
    # operator compatible with early scripts and saved redo panels.
    mode: EnumProperty(
        name="Mode",
        items=(
            ("CONNECTED", "Chained", "Use one-sided continuation"),
            ("CHAINED", "Chained", "Use one-sided continuation"),
            ("INDEPENDENT", "Independent", "Use isolated boxes"),
        ),
        default="CONNECTED",
        options={"HIDDEN"},
    )
    connected: BoolProperty(
        name="Connect Ends",
        default=True,
        options={"HIDDEN"},
    )
    gap: FloatProperty(
        name="Gap",
        description="Distance between neighboring cage frames in target units",
        default=0.0,
        min=0.0,
        soft_max=10.0,
    )
    auto_reconnect: BoolProperty(
        name="Auto Reconnect",
        description="Refresh downstream cage frames after upstream edits",
        default=True,
    )
    sync_shared_end_scale: BoolProperty(
        name="Sync Shared End Scale",
        description=(
            "Scale both sides of each shared cage seam together while "
            "keeping outer ends independent"
        ),
        default=True,
    )
    origin: EnumProperty(
        name="Origin",
        description="Deformation reference used by every cage in the chain",
        items=(
            ("BOTTOM", "Bottom (Recommended)", "Reference the lower end of each cage"),
            ("TOP", "Top", "Reference the upper end of each cage"),
            ("CENTER", "Center", "Reference the center of each cage"),
            ("SYMMETRIC", "Symmetric", "Mirror the profile around each cage center"),
        ),
        default="BOTTOM",
    )
    alignment: EnumProperty(
        name="Cage Axis",
        items=(
            ("AUTO", "Auto", "Use the longest input dimension"),
            ("POS_X", "+X", "Align cage Y to target +X"),
            ("NEG_X", "-X", "Align cage Y to target -X"),
            ("POS_Y", "+Y", "Align cage Y to target +Y"),
            ("NEG_Y", "-Y", "Align cage Y to target -Y"),
            ("POS_Z", "+Z", "Align cage Y to target +Z"),
            ("NEG_Z", "-Z", "Align cage Y to target -Z"),
        ),
        default="POS_Z",
    )

    @classmethod
    def poll(cls, context):
        target = _call("target_from_context", context)
        supported = getattr(_core(), "SUPPORTED_TYPES", {"MESH", "CURVE", "FONT"})
        return bool(target and target.type in supported)

    def invoke(self, context, event):
        target = _call("target_from_context", context)
        if target is None:
            return {"CANCELLED"}
        active = getattr(target, "modifiers", None)
        active = getattr(active, "active", None)
        source = (_find_controller(target, active)
                  if _is_cage_modifier(active) else None)
        try:
            explicit_type = self.is_property_set("cage_type")
        except (AttributeError, TypeError):
            explicit_type = False
        if source is not None and not explicit_type:
            source_type = str(getattr(
                source.sdh_cage_deform, "cage_type", "STANDARD"))
            if source_type == "CURVE":
                self.report(
                    {"INFO"},
                    iface_("Curve cages do not support chained creation"))
                return {"CANCELLED"}
            self.cage_type = source_type
        if source is not None:
            self.origin = str(getattr(source.sdh_cage_deform, "origin", "BOTTOM"))
            self.auto_reconnect = bool(getattr(
                source.sdh_cage_deform, "auto_reconnect", True))
        else:
            self.auto_reconnect = True
        return context.window_manager.invoke_props_dialog(self, width=380)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "cage_type")
        layout.prop(self, "count")
        _draw_chain_performance_warning(layout, self.count)
        layout.prop(self, "origin")
        layout.prop(self, "gap")
        layout.prop(self, "auto_reconnect", text="Auto Reconnect")
        layout.prop(self, "sync_shared_end_scale")

    def execute(self, context):
        target = _call("target_from_context", context)
        if target is None:
            self.report(
                {"WARNING"}, iface_("Select a supported target object first"))
            return {"CANCELLED"}
        mode = _chain_mode(self)
        requested_cage_type = str(self.cage_type or "STANDARD")
        if requested_cage_type not in {"STANDARD", "SHEAR", "FFD"}:
            requested_cage_type = "STANDARD"
        active = getattr(target.modifiers, "active", None)
        previous = active if active in tuple(target.modifiers) else None
        source = _find_controller(target, active) if _is_cage_modifier(active) else None
        if source is not None:
            source_type = str(getattr(
                source.sdh_cage_deform, "cage_type", "STANDARD"))
            if source_type != requested_cage_type:
                source = None
        bounds_modifier = previous
        if bounds_modifier is None:
            existing_modifiers = tuple(getattr(target, "modifiers", ()))
            bounds_modifier = existing_modifiers[-1] if existing_modifiers else None
        bounds = _bounds_after_modifier(context, target, bounds_modifier)
        minimum, maximum = Vector(bounds[0]), Vector(bounds[1])
        center = (minimum + maximum) * 0.5
        if source is not None:
            rotation = getattr(_core(), "_controller_rotation_xyz", None)
            try:
                base_rotation = (
                    rotation(source).copy()
                    if rotation is not None else source.rotation_euler.copy())
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                base_rotation = source.rotation_euler.copy()
        else:
            base_rotation = _alignment_rotation(self.alignment, (minimum, maximum))
        rotation_matrix = base_rotation.to_matrix()
        inverse_rotation = rotation_matrix.inverted()
        local_points = [inverse_rotation @ (point - center)
                        for point in _bounds_corners((minimum, maximum))]
        local_min = Vector(tuple(min(point[i] for point in local_points) for i in range(3)))
        local_max = Vector(tuple(max(point[i] for point in local_points) for i in range(3)))
        total_length = max(float(local_max.y - local_min.y), EPSILON)
        count = max(int(self.count), 1)
        gap_count = max(count - 1, 0)
        requested_gap = max(float(self.gap), 0.0)
        max_gap = (
            max((total_length - count * EPSILON) / gap_count, 0.0)
            if gap_count else 0.0)
        gap = min(requested_gap, max_gap)
        usable_length = total_length - gap * gap_count
        segment_length = max(usable_length / count, EPSILON)
        cross_size = (
            max(float(local_max.x - local_min.x), EPSILON),
            max(float(local_max.z - local_min.z), EPSILON),
        )
        local_center_x = (local_min.x + local_max.x) * 0.5
        local_center_z = (local_min.z + local_max.z) * 0.5
        chain_uuid = str(uuid.uuid4())
        created = []
        insertion_anchor = getattr(
            _core(), "cage_stage_insertion_anchor", None)
        after = (
            insertion_anchor(target, previous)
            if insertion_anchor is not None else previous
        )
        creator = getattr(_core(), "create_deform_stage", None)
        if creator is None:
            self.report({"ERROR"}, iface_("Cage Deform core is unavailable"))
            return {"CANCELLED"}
        template = getattr(_core(), "ensure_node_group", lambda: None)()
        try:
            for index in range(count):
                modifier, controller, _old_active = creator(
                    context, target,
                    name=(
                        f"{requested_cage_type.title()} Chain "
                        f"{index + 1:02d}"
                    ),
                    after_modifier=after,
                    show_other_default=True,
                    node_group_template=template,
                    skip_stage_maintenance=index > 0,
                    fit_stage=False,
                    cage_type=requested_cage_type,
                )
                created.append((modifier, controller))
                properties = _copy_template(controller, source, mode=mode)
                if mode == "CHAINED":
                    properties.origin = self.origin
                properties.auto_reconnect = bool(self.auto_reconnect)
                if hasattr(properties, "auto_sync_upstream"):
                    properties.auto_sync_upstream = False
                properties.sync_shared_end_scale = bool(
                    self.sync_shared_end_scale)
                properties.size = (cross_size[0], segment_length, cross_size[1])
                # Keep user-authored shape settings on copied stages, but use
                # neutral end profiles for a newly partitioned chain.
                properties.top_scale = (1.0, 1.0)
                properties.bottom_scale = (1.0, 1.0)
                properties.top_offset = (0.0, 0.0)
                properties.bottom_offset = (0.0, 0.0)
                local_y = local_min.y + segment_length * (index + 0.5) + gap * index
                try:
                    controller.rotation_mode = "XYZ"
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
                controller.rotation_euler = base_rotation
                controller.location = center + rotation_matrix @ Vector((
                    local_center_x, local_y, local_center_z))
                controller.scale = tuple(max(float(value), EPSILON) * 0.5
                                          for value in properties.size)
                set_stage_metadata(
                    modifier, controller, chain_uuid, index, count, mode,
                    gap=gap if index > 0 else 0.0,
                    auto_reconnect=bool(self.auto_reconnect),
                    sync_shared_end_scale=bool(self.sync_shared_end_scale),
                )
                sync = getattr(_core(), "sync_controller", None)
                if sync is not None:
                    sync(controller, pull_transform=False)
                after = modifier
            target.modifiers.active = created[0][0]
            _activate(context, target)
            if mode == "CHAINED":
                reconnect_chain(target, chain_uuid)
            _normalize_metadata(target, chain_uuid, broken=False)
            refresh = getattr(_core(), "refresh_controller_display", None)
            if refresh is not None:
                refresh(context, force=True)
            tool_action = getattr(
                _core(),
                ("activate_ffd_workspace_tool" if requested_cage_type == "FFD"
                 else "deactivate_ffd_workspace_tool"),
                None,
            )
            if tool_action is not None:
                tool_action(context)
            if getattr(context, "area", None):
                context.area.tag_redraw()
            self.report(
                {"INFO"},
                iface_("Created {count} cage stages").format(
                    count=len(created)),
            )
            _report_chain_performance_warning(self, len(created))
            return {"FINISHED"}
        except Exception as error:
            _cleanup_created(target, created)
            self.report(
                {"ERROR"},
                iface_("Could not create cage chain: {error}").format(
                    error=error),
            )
            return {"CANCELLED"}


class SDH_OT_subdivide_cage_to_chain(Operator):
    bl_idname = "sdh.subdivide_cage_to_chain"
    bl_label = "Subdivide to Chained Cages"
    bl_description = (
        "Split the active cage inside its current range and distribute its "
        "deformation across a chained cage stack"
    )
    bl_options = {"REGISTER", "UNDO"}

    count: IntProperty(
        name="Cage Count",
        description="Number of chained segments inside the current cage range",
        default=3,
        min=2,
        max=8,
    )
    gap: FloatProperty(
        name="Gap",
        description=(
            "Uniform spacing between segments; segment lengths shrink so the "
            "original total range is preserved"
        ),
        default=0.0,
        min=0.0,
        soft_max=10.0,
    )
    auto_reconnect: BoolProperty(
        name="Auto Reconnect",
        description="Refresh downstream cage frames after upstream edits",
        default=True,
    )
    sync_shared_end_scale: BoolProperty(
        name="Sync Shared End Scale",
        description="Keep each newly-created shared cross-section continuous",
        default=True,
    )
    allow_mixed_bend_approximation: BoolProperty(
        name="Legacy Mixed Bend Option",
        description=(
            "Compatibility option retained for saved operator settings; "
            "mixed Bend stacks now use the analytic chain evaluator"
        ),
        default=False,
    )

    @classmethod
    def poll(cls, context):
        target, modifier, controller = _call(
            "resolve_context_deform", context, default=(None, None, None))
        if target is None or modifier is None or controller is None:
            return False
        chain_uuid = stage_chain_uuid(modifier)
        return not chain_uuid or len(chain_stages(target, chain_uuid)) <= 1

    def invoke(self, context, event):
        _target, _modifier, controller = _call(
            "resolve_context_deform", context, default=(None, None, None))
        if controller is not None:
            properties = controller.sdh_cage_deform
            self.auto_reconnect = bool(
                getattr(properties, "auto_reconnect", True))
        else:
            self.auto_reconnect = True
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "count")
        _draw_chain_performance_warning(layout, self.count)
        layout.prop(self, "gap")
        layout.prop(self, "auto_reconnect", text="Auto Reconnect")
        layout.prop(self, "sync_shared_end_scale")
        note = layout.column(align=True)
        note.label(text="The original cage boundaries stay fixed.", icon="INFO")
        note.label(text="Bend and Twist angles are distributed across segments.")

    def execute(self, context):
        core = _core()
        target, source_modifier, source_controller = _call(
            "resolve_context_deform", context, default=(None, None, None))
        if target is None or source_modifier is None or source_controller is None:
            return {"CANCELLED"}

        existing_uuid = stage_chain_uuid(source_modifier)
        if existing_uuid and len(chain_stages(target, existing_uuid)) > 1:
            self.report(
                {"WARNING"}, iface_("Only a single cage can be subdivided"))
            return {"CANCELLED"}

        source_properties = source_controller.sdh_cage_deform
        source_cage_type = str(
            getattr(source_properties, "cage_type", "STANDARD") or "STANDARD")
        if source_cage_type == "CURVE":
            self.report(
                {"INFO"},
                iface_("Curve cages cannot be subdivided into chains"))
            return {"CANCELLED"}
        if source_cage_type == "FFD":
            return _subdivide_ffd_cage_to_chain(
                context, target, source_modifier, source_controller, self)
        unsupported_layers = set(
            getattr(source_properties, "deform_types", ())).intersection(
                {"FFD"})
        if unsupported_layers:
            labels = ", ".join(sorted(unsupported_layers))
            self.report(
                {"WARNING"},
                iface_(
                    "Subdivide does not yet preserve these layers: {layers}"
                ).format(layers=labels),
            )
            return {"CANCELLED"}
        source_origin = str(getattr(source_properties, "origin", "BOTTOM"))
        if source_origin != "BOTTOM":
            self.report(
                {"WARNING"},
                iface_("Non-Bottom origin may introduce subdivision errors"),
            )
        if _source_has_split_animation(
                target, source_modifier, source_controller):
            self.report(
                {"WARNING"},
                iface_("Animated cage parameters cannot be subdivided safely"),
            )
            return {"CANCELLED"}

        # Capture before flushing timer-side state. A later construction
        # failure must restore even legacy mirror fields that the flush may
        # legitimately normalize on the success path.
        source_snapshot = _capture_controller_state(source_controller)
        source_metadata = tuple(
            (owner, _capture_owner_metadata(owner))
            for owner in (
                source_modifier,
                getattr(source_modifier, "node_group", None),
                source_controller,
            )
        )

        flush = getattr(core, "flush_pending_chain_updates", None)
        if flush is not None:
            flush(target)
        sync = getattr(core, "sync_controller", None)
        if sync is not None:
            sync(source_controller, pull_transform=True, sync_mode="timer")
        # A direct Geometry Nodes socket edit can become authoritative during
        # the explicit flush above. Preserve the authored Origin when it is
        # changed through the modifier rather than silently reverting it.
        source_properties = source_controller.sdh_cage_deform
        source_origin = str(getattr(source_properties, "origin", source_origin))
        count = max(int(self.count), 2)
        original_size = tuple(
            max(float(value), EPSILON) for value in source_properties.size)
        total_length = original_size[1]
        requested_gap = max(float(self.gap), 0.0)
        # An even Symmetric split puts its pivot in the central gap. No stage
        # would own the point where Bend/Twist/Taper reverse direction, so an
        # exact subdivision is impossible while that particular gap remains
        # open. Close only the pivot gap; all other requested gaps remain.
        close_symmetric_pivot_gap = (
            source_origin == "SYMMETRIC" and count % 2 == 0)
        gap_slot_count = max(
            count - 1 - int(close_symmetric_pivot_gap), 0)
        max_gap = max(
            (total_length - count * EPSILON) / max(gap_slot_count, 1), 0.0
        ) if gap_slot_count else 0.0
        gap = min(requested_gap, max_gap)
        stage_gaps = tuple(
            0.0
            if (
                index == 0 or
                (close_symmetric_pivot_gap and index == count // 2)
            ) else gap
            for index in range(count)
        )
        has_authored_gaps = any(
            value > EPSILON for value in stage_gaps[1:])
        segment_length = max(
            (total_length - sum(stage_gaps)) / count, EPSILON)
        gap_was_adjusted = (
            requested_gap > gap + EPSILON or
            (close_symmetric_pivot_gap and requested_gap > EPSILON)
        )

        present_types = set(getattr(source_properties, "deform_types", ()))
        source_order = tuple(
            name for name in _call(
                "ordered_deform_types", source_properties, default=())
            if name in present_types
        )
        profile_bottom_scale = tuple(source_properties.bottom_scale)
        profile_top_scale = tuple(source_properties.top_scale)
        profile_bottom_offset = tuple(source_properties.bottom_offset)
        profile_top_offset = tuple(source_properties.top_offset)
        global_profile_mode = not has_authored_gaps and any(
            abs(float(value) - reference) > EPSILON
            for values, references in (
                (profile_bottom_scale, (1.0, 1.0)),
                (profile_top_scale, (1.0, 1.0)),
                (profile_bottom_offset, (0.0, 0.0)),
                (profile_top_offset, (0.0, 0.0)),
            )
            for value, reference in zip(values, references)
        )
        bend_index = (
            source_order.index("BEND") if "BEND" in source_order else -1)
        shear_index = (
            source_order.index("SHEAR") if "SHEAR" in source_order else -1)
        primary_index = bend_index if bend_index >= 0 else shear_index
        # With no Bend/Shear pivot, keep the complete linear stack in the
        # source frame.  The global baseline is still subtracted from each
        # stage, so later per-stage edits remain local deltas.
        global_prefix_order = (
            source_order[:primary_index + 1]
            if primary_index >= 0 else
            source_order if not has_authored_gaps else ())
        global_suffix_order = (
            source_order[primary_index + 1:]
            if primary_index >= 0 else ())
        global_prefix_operations = (
            bool(global_prefix_order) and
            not has_authored_gaps)
        global_suffix_operations = (
            bool(global_suffix_order) and global_prefix_operations)

        def split_around_shear(order):
            order = tuple(order)
            if "SHEAR" not in order:
                return (
                    tuple(name for name in order if name != "BEND"),
                    (),
                )
            index = order.index("SHEAR")
            return (
                tuple(name for name in order[:index] if name != "BEND"),
                tuple(name for name in order[index + 1:] if name != "BEND"),
            )

        prefix_pre_shear_order, prefix_post_shear_order = (
            split_around_shear(global_prefix_order))
        suffix_pre_shear_order, suffix_post_shear_order = (
            split_around_shear(global_suffix_order))
        subdivision_source_frame = (
            "BEND" in present_types and not global_prefix_operations)
        # Disjoint chain stages do not compose axial Stretch
        # multiplicatively: their physical lengths add.  Splitting the scale
        # with an Nth root therefore shortens every Stretch-only, Twist,
        # Taper, or Shear combination.  Evaluate Stretch once in the original
        # root frame whenever it is not an authored pre-Bend operation.  A
        # pre-Bend Stretch remains owned by the existing global-prefix path so
        # operation order is preserved.
        global_stretch_mode = bool(
            not has_authored_gaps and
            "STRETCH" in present_types and
            (
                (
                    global_prefix_operations and
                    "STRETCH" in global_suffix_order
                ) or
                not global_prefix_operations
            )
        )
        # Boundary alignment must describe the same operation sequence;
        # otherwise the root frame already contains the authored axial scale
        # and the chain-tip pass applies it a second time.
        chain_stage_order = tuple(
            name for name in source_order
            if not (global_stretch_mode and name == "STRETCH")
        )
        global_baseline_order = tuple(
            name for name in source_order
            if global_prefix_operations and
            not (global_stretch_mode and name == "STRETCH")
        )
        alignment_order = (
            source_order if global_prefix_operations else chain_stage_order)
        source_bottom_mapping = _boundary_mapping_affine(
            target,
            source_controller,
            "BOTTOM",
            operation_order_override=alignment_order,
        )
        source_pre_order = (
            alignment_order[:alignment_order.index("BEND") + 1]
            if "BEND" in alignment_order else alignment_order)
        source_pre_mapping = _boundary_mapping_affine(
            target,
            source_controller,
            "BOTTOM",
            operation_order_override=source_pre_order,
        )
        # A non-identity end profile is evaluated once in the root frame
        # before the ordered deformation stack.  Keep the desired boundary
        # mapping in that same authored space; removing the profile here
        # would make the root output correction cancel the profile that the
        # node group has already applied.
        source_frame = _stage_local_matrix(target, source_controller)
        source_post_mapping = (
            source_frame @ _tail_value_affine(
                source_properties, "BOTTOM", alignment_order) @
            source_frame.inverted_safe()
        )
        symmetric_profile_partition = (
            source_origin == "SYMMETRIC" and
            gap <= EPSILON
        )
        symmetric_stage_factor = segment_length / total_length

        def source_profile(position):
            position = min(max(float(position), 0.0), 1.0)
            if source_origin == "BOTTOM":
                return position
            if source_origin == "TOP":
                return position - 1.0
            if source_origin == "SYMMETRIC":
                return abs(position - 0.5)
            return position - 0.5

        # With a non-zero gap, a stage does not own the whole equal-width
        # partition. Sample every physical stage start/end so each local cage
        # receives only its authored portion; the skipped interval remains a
        # rigid continuation instead of being evaluated by a global baseline.
        stage_ranges = []
        source_cursor = 0.0
        for index in range(count):
            source_cursor += stage_gaps[index]
            stage_ranges.append((
                source_cursor,
                source_cursor + segment_length,
            ))
            source_cursor += segment_length
        stage_ranges = tuple(stage_ranges)
        stage_profile_pairs = tuple(
            (
                source_profile(start / total_length),
                source_profile(end / total_length),
            )
            for start, end in stage_ranges
        )
        taper_factor = float(source_properties.taper_factor)
        if "TAPER" in present_types:
            for profile in tuple(
                    value for pair in stage_profile_pairs for value in pair):
                if abs(1.0 + taper_factor * profile) <= EPSILON:
                    _restore_controller_state(
                        source_controller, source_snapshot)
                    self.report(
                        {"WARNING"},
                        iface_("Taper collapses at an interior split boundary"),
                    )
                    return {"CANCELLED"}

        rotation_function = getattr(core, "_controller_rotation_xyz", None)
        base_rotation = (
            rotation_function(source_controller).copy()
            if rotation_function is not None else
            source_controller.rotation_euler.copy()
        )
        rotation_matrix = base_rotation.to_matrix()
        base_location = Vector(source_controller.location)
        original_bottom = base_location + rotation_matrix @ Vector((
            0.0, -total_length * 0.5, 0.0))

        source_values = {
            "bend_strength": float(source_properties.bend_strength),
            "twist_strength": float(source_properties.twist_strength),
            "taper_factor": taper_factor,
            "stretch_factor": float(source_properties.stretch_factor),
            "shear_factors": tuple(
                float(value) for value in getattr(
                    source_properties, "shear_factors", (0.0, 0.0))),
            "bottom_scale": profile_bottom_scale,
            "top_scale": profile_top_scale,
            "bottom_offset": profile_bottom_offset,
            "top_offset": profile_top_offset,
        }
        # Stretch composes multiplicatively across a chain.  Factor the
        # authored axial scale across the stages instead of applying the full
        # source factor once per stage.  A non-positive scale has no stable
        # real root for every segment count and cannot preserve the source
        # mapping during subdivision.
        source_stretch_scale = 1.0 + source_values["stretch_factor"]
        if "STRETCH" in present_types and source_stretch_scale <= EPSILON:
            _restore_controller_state(source_controller, source_snapshot)
            self.report(
                {"WARNING"},
                iface_(
                    "Stretch scale must be greater than zero to subdivide"),
            )
            return {"CANCELLED"}
        stage_scale_pairs = tuple(
            (
                _lerp_pair(
                    source_values["bottom_scale"],
                    source_values["top_scale"],
                    start / total_length,
                ),
                _lerp_pair(
                    source_values["bottom_scale"],
                    source_values["top_scale"],
                    end / total_length,
                ),
            )
            for start, end in stage_ranges
        )
        stage_offset_pairs = tuple(
            (
                _lerp_pair(
                    source_values["bottom_offset"],
                    source_values["top_offset"],
                    start / total_length,
                ),
                _lerp_pair(
                    source_values["bottom_offset"],
                    source_values["top_offset"],
                    end / total_length,
                ),
            )
            for start, end in stage_ranges
        )

        previous_active_modifier = getattr(target.modifiers, "active", None)
        previous_active_object = getattr(context.view_layer.objects, "active", None)
        previous_selected = tuple(getattr(context, "selected_objects", ()))
        created = []
        stages = [(source_modifier, source_controller)]
        source_mutated = False
        creator = getattr(core, "create_deform_stage", None)
        if creator is None:
            self.report({"ERROR"}, iface_("Cage Deform core is unavailable"))
            return {"CANCELLED"}
        template = getattr(core, "ensure_node_group", lambda: None)()

        chain_uuid = str(uuid.uuid4())
        try:
            after = source_modifier
            for index in range(1, count):
                modifier, controller, _old_active = creator(
                    context,
                    target,
                    name=f"{source_modifier.name} {index + 1:02d}",
                    after_modifier=after,
                    show_other_default=True,
                    node_group_template=template,
                    skip_stage_maintenance=True,
                    fit_stage=False,
                    cage_type=source_cage_type,
                )
                created.append((modifier, controller))
                stages.append((modifier, controller))
                _copy_template(controller, source_controller, mode="CHAINED")
                after = modifier

            transaction = getattr(core, "chain_reconnect_transaction", None)
            transaction_context = (
                transaction(target, chain_uuid) if transaction is not None else None)

            def configure(commit=None):
                nonlocal source_mutated
                source_mutated = True
                syncing = getattr(core, "_SYNCING", set())
                pointers = tuple(
                    pointer for pointer in (
                        _pointer(controller) for _modifier, controller in stages)
                    if pointer
                )
                syncing.update(pointers)
                try:
                    for index, (modifier, controller) in enumerate(stages):
                        properties = controller.sdh_cage_deform
                        properties.mode = "CHAINED"
                        properties.auto_reconnect = bool(self.auto_reconnect)
                        if hasattr(properties, "auto_sync_upstream"):
                            properties.auto_sync_upstream = False
                        stage_origin = source_origin
                        stage_profile_start, stage_profile_end = (
                            stage_profile_pairs[index])
                        stage_profile_delta = (
                            stage_profile_end - stage_profile_start)
                        stage_bend_strength = (
                            source_values["bend_strength"] *
                            stage_profile_delta)
                        stage_twist_strength = (
                            source_values["twist_strength"] *
                            stage_profile_delta)
                        shear_slope = (
                            stage_profile_delta * total_length /
                            max(segment_length, EPSILON))
                        stage_shear_factors = tuple(
                            value * shear_slope
                            for value in source_values["shear_factors"])
                        if symmetric_profile_partition:
                            lower = -total_length * 0.5 + index * segment_length
                            upper = lower + segment_length
                            if upper <= EPSILON:
                                stage_origin = "BOTTOM"
                            elif lower >= -EPSILON:
                                stage_origin = "BOTTOM"
                            else:
                                # With an equal zero-gap split, only the odd
                                # count's center stage crosses the global pivot.
                                stage_origin = "SYMMETRIC"
                                stage_bend_strength = (
                                    source_values["bend_strength"] *
                                    symmetric_stage_factor)
                                stage_twist_strength = (
                                    source_values["twist_strength"] *
                                    symmetric_stage_factor)
                                stage_shear_factors = tuple(
                                    value * (-1.0 if upper <= EPSILON else 1.0)
                                    for value in source_values["shear_factors"])
                        elif source_origin == "SYMMETRIC":
                            # With gaps, only a stage that actually crosses
                            # the global pivot can use the symmetric local
                            # profile.  Stages wholly below/above it need a
                            # one-sided profile with the signed physical
                            # delta; keeping SYMMETRIC on those stages makes
                            # Twist/Taper reverse or cancel at every stage.
                            lower = stage_ranges[index][0] - total_length * 0.5
                            upper = stage_ranges[index][1] - total_length * 0.5
                            if upper <= EPSILON or lower >= -EPSILON:
                                stage_origin = "BOTTOM"
                            else:
                                stage_origin = "SYMMETRIC"
                                stage_bend_strength = (
                                    source_values["bend_strength"] *
                                    symmetric_stage_factor)
                                stage_twist_strength = (
                                    source_values["twist_strength"] *
                                    symmetric_stage_factor)
                                stage_shear_factors = tuple(
                                    value * (-1.0 if upper <= EPSILON else 1.0)
                                    for value in source_values["shear_factors"])
                        if stage_origin == "SYMMETRIC":
                            # The local symmetric profile already measures
                            # physical distance from its own center.
                            stage_shear_factors = source_values["shear_factors"]
                        properties.origin = stage_origin
                        properties.auto_reconnect = bool(self.auto_reconnect)
                        properties.sync_shared_end_scale = bool(
                            self.sync_shared_end_scale)
                        properties.show_other_cages = True
                        properties.size = (
                            original_size[0], segment_length, original_size[2])
                        properties.bend_strength = stage_bend_strength
                        properties.twist_strength = stage_twist_strength
                        properties.shear_factors = stage_shear_factors
                        q0 = (
                            1.0 + source_values["taper_factor"] *
                            stage_profile_start)
                        q1 = (
                            1.0 + source_values["taper_factor"] *
                            stage_profile_end)
                        if stage_origin == "SYMMETRIC":
                            properties.taper_factor = (
                                source_values["taper_factor"] *
                                symmetric_stage_factor)
                        else:
                            ratio = q1 / q0 if abs(q0) > EPSILON else 1.0
                            local_profile = {
                                "BOTTOM": (0.0, 1.0),
                                "TOP": (-1.0, 0.0),
                                "CENTER": (-0.5, 0.5),
                            }.get(stage_origin, (0.0, 1.0))
                            phi0, phi1 = local_profile
                            denominator = phi1 - ratio * phi0
                            properties.taper_factor = (
                                (ratio - 1.0) / denominator
                                if abs(denominator) > EPSILON else 0.0)
                        # Axial stretch is uniform in the source cage.  Equal
                        # chained stages therefore receive equal logarithmic
                        # portions of the authored scale, so their product is
                        # exactly the original scale.  Use the physical owned
                        # segment fraction rather than a signed deformation
                        # profile; a symmetric center-crossing segment still
                        # needs its full axial share.
                        stage_stretch_exponent = max(
                            segment_length / total_length, EPSILON)
                        stage_stretch_scale = (
                            source_stretch_scale ** stage_stretch_exponent
                            if "STRETCH" in present_types else 1.0)
                        properties.stretch_factor = (
                            source_values["stretch_factor"]
                            if global_stretch_mode else
                            stage_stretch_scale - 1.0
                            if "STRETCH" in present_types else
                            source_values["stretch_factor"])
                        stage_bottom_scale, stage_top_scale = (
                            stage_scale_pairs[index])
                        stage_bottom_offset, stage_top_offset = (
                            stage_offset_pairs[index])
                        # Keep the authored interpolation visible on every
                        # chain stage.  When a non-identity source profile is
                        # present, the node group evaluates it once through
                        # the root's global profile inputs; the local values
                        # are ignored by the evaluator (below), but retaining
                        # them keeps the stage editable and keyframeable.
                        properties.bottom_scale = stage_bottom_scale
                        properties.top_scale = stage_top_scale
                        properties.bottom_offset = stage_bottom_offset
                        properties.top_offset = stage_top_offset

                        local_y = stage_ranges[index][0] + segment_length * 0.5
                        try:
                            controller.rotation_mode = "XYZ"
                        except (AttributeError, ReferenceError, RuntimeError,
                                TypeError, ValueError):
                            pass
                        controller.rotation_euler = base_rotation
                        controller.location = (
                            original_bottom + rotation_matrix @ Vector((
                                0.0, local_y, 0.0)))
                        controller.scale = (
                            original_size[0] * 0.5,
                            segment_length * 0.5,
                            original_size[2] * 0.5,
                        )
                        legacy = getattr(core, "_legacy_values_for_primary", None)
                        if legacy is not None:
                            strength, factor, direction = legacy(properties)
                            properties.strength = strength
                            properties.factor = factor
                            properties.direction = direction
                        set_stage_metadata(
                            modifier,
                            controller,
                            chain_uuid,
                            index,
                            count,
                            "CHAINED",
                            gap=stage_gaps[index],
                            auto_reconnect=bool(self.auto_reconnect),
                            sync_shared_end_scale=bool(
                                self.sync_shared_end_scale),
                        )
                        _set_source_frame_mode(
                            modifier, controller, subdivision_source_frame)
                        _set_global_stretch_mode(
                            modifier,
                            controller,
                            active=global_stretch_mode,
                            factor=source_values["stretch_factor"],
                            center=base_location,
                            rotation=base_rotation,
                            source_offset=-total_length * 0.5 +
                            segment_length * 0.5,
                            length=total_length,
                            origin=source_origin,
                        )
                        _set_global_prefix_mode(
                            modifier,
                            controller,
                            active=global_prefix_operations,
                            deform_types=(
                                global_prefix_order
                                if global_prefix_operations else ()),
                            baseline_types=global_baseline_order,
                            pre_shear_types=prefix_pre_shear_order,
                            post_shear_types=prefix_post_shear_order,
                            bend=source_values["bend_strength"],
                            direction=float(source_properties.bend_direction),
                            twist=source_values["twist_strength"],
                            taper=source_values["taper_factor"],
                            stretch=source_values["stretch_factor"],
                            shear=source_values["shear_factors"],
                            center=base_location,
                            rotation=base_rotation,
                            source_offset=-total_length * 0.5 +
                            segment_length * 0.5,
                            length=total_length,
                            origin=source_origin,
                            profile_active=global_profile_mode,
                            bottom_scale=source_values["bottom_scale"],
                            top_scale=source_values["top_scale"],
                            bottom_offset=source_values["bottom_offset"],
                            top_offset=source_values["top_offset"],
                            base_bend=(
                                properties.bend_strength
                                if "BEND" in global_baseline_order else 0.0),
                            base_twist=(
                                properties.twist_strength
                                if "TWIST" in global_baseline_order else 0.0),
                            base_taper=(
                                properties.taper_factor
                                if "TAPER" in global_baseline_order else 0.0),
                            base_stretch=(
                                properties.stretch_factor
                                if "STRETCH" in global_baseline_order else 0.0),
                            base_shear=(
                                properties.shear_factors
                                if "SHEAR" in global_baseline_order else
                                (0.0, 0.0)),
                        )
                        _set_global_suffix_mode(
                            modifier,
                            controller,
                            active=global_suffix_operations,
                            deform_types=(
                                global_suffix_order
                                if global_suffix_operations else ()),
                            pre_shear_types=suffix_pre_shear_order,
                            post_shear_types=suffix_post_shear_order,
                            twist=source_values["twist_strength"],
                            taper=source_values["taper_factor"],
                            shear=source_values["shear_factors"],
                        )
                finally:
                    for pointer in pointers:
                        syncing.discard(pointer)

                if sync is not None:
                    for _modifier, controller in stages:
                        sync(controller, pull_transform=False)

                # End offsets are additive in the current evaluator. Keep the
                # root values absolute and express downstream changes in each
                # reconnected local frame so an offset is not applied twice.
                for index, (modifier, controller) in enumerate(stages):
                    if index > 0:
                        previous_controller = stages[index - 1][1]
                        stage_gap = stage_chain_gap(modifier)
                        endpoint, x_axis, y_axis, z_axis = _stage_top_frame(
                            target, previous_controller, extension=stage_gap)
                        if not stage_uses_source_frame(modifier, controller):
                            _set_controller_frame(
                                target, controller, endpoint, x_axis, y_axis,
                                z_axis, gap=0.0,
                            )
                    properties = controller.sdh_cage_deform
                    pointer = _pointer(controller)
                    if pointer:
                        syncing.add(pointer)
                    try:
                        stage_bottom_scale, stage_top_scale = (
                            stage_scale_pairs[index])
                        stage_bottom_offset, stage_top_offset = (
                            stage_offset_pairs[index])
                        if index == 0:
                            properties.bottom_scale = stage_bottom_scale
                            properties.top_scale = stage_top_scale
                            properties.bottom_offset = stage_bottom_offset
                            properties.top_offset = stage_top_offset
                        else:
                            # Keep each downstream stage's authored
                            # interpolation visible.  The global profile
                            # branch in GN/Python owns the actual evaluation.
                            properties.bottom_scale = stage_bottom_scale
                            properties.top_scale = stage_top_scale
                            # Offsets are authored in the shared seam frame:
                            # downstream stages start at a zero local offset,
                            # while their terminal offset remains visible for
                            # editing and animation.
                            properties.bottom_offset = (0.0, 0.0)
                            properties.top_offset = stage_top_offset
                    finally:
                        if pointer:
                            syncing.discard(pointer)
                    if sync is not None:
                        sync(controller, pull_transform=False)
                    if index == 0:
                        setter = getattr(
                            core, "set_chain_root_output_affine", None)
                        if setter is None:
                            raise RuntimeError(
                                "Cage Deform root-frame support is unavailable")
                        correction = (
                            Matrix.Identity(4)
                            if global_prefix_operations or (
                                global_profile_mode and
                                all(
                                    abs(float(value)) <= EPSILON
                                    for value in (
                                        source_values["bend_strength"],
                                        source_values["twist_strength"],
                                        source_values["taper_factor"],
                                        source_values["stretch_factor"],
                                        *source_values["shear_factors"],
                                    )
                                )
                            ) else
                            _root_output_alignment_affine(
                                target,
                                controller,
                                source_bottom_mapping,
                                "BOTTOM",
                                operation_order_override=alignment_order,
                                desired_pre_mapping=source_pre_mapping,
                                desired_post_mapping=source_post_mapping,
                            )
                        )
                        setter(controller, modifier, correction)
                        if sync is not None:
                            sync(controller, pull_transform=False)

                reconnect_chain(target, chain_uuid)
                _normalize_metadata(target, chain_uuid, broken=False)
                if commit is not None:
                    commit()

            if transaction_context is None:
                configure()
            else:
                with transaction_context as commit:
                    configure(commit)

            show_all = getattr(core, "_sync_target_show_other_cages", None)
            if show_all is not None:
                show_all(target, True)
            target.modifiers.active = source_modifier
            _activate(context, source_controller)
            refresh = getattr(core, "refresh_controller_display", None)
            if refresh is not None:
                refresh(context, force=True)
            if gap_was_adjusted:
                message = iface_(
                    "Subdivided cage into {count} chained stages "
                    "(gap clamped to preserve range)"
                ).format(count=count)
            else:
                message = iface_(
                    "Subdivided cage into {count} chained stages"
                ).format(count=count)
            self.report({"INFO"}, message)
            _report_chain_performance_warning(self, count)
            return {"FINISHED"}
        except Exception as error:
            _cleanup_created(target, created)
            # Metadata controls both forced CHAINED properties and hidden GN
            # domain inputs. Restore it before syncing the controller, or the
            # failed chain state becomes authoritative during rollback.
            for owner, snapshot in source_metadata:
                _restore_owner_metadata(owner, snapshot)
            _restore_controller_state(source_controller, source_snapshot)
            sync_chain_domain_inputs(source_controller, source_modifier)
            try:
                target.modifiers.active = previous_active_modifier
            except (AttributeError, ReferenceError, RuntimeError):
                pass
            for selected in tuple(getattr(context, "selected_objects", ())):
                try:
                    selected.select_set(False)
                except (ReferenceError, RuntimeError):
                    pass
            for selected in previous_selected:
                try:
                    selected.select_set(True)
                except (ReferenceError, RuntimeError):
                    pass
            try:
                context.view_layer.objects.active = previous_active_object
            except (AttributeError, ReferenceError, RuntimeError):
                pass
            # The source stage and every newly-created datablock have already
            # been restored. A warning keeps Python callers on the normal
            # CANCELLED path instead of raising after a successful rollback.
            self.report(
                {"WARNING"},
                iface_("Could not subdivide cage: {error}").format(
                    error=error),
            )
            return {"CANCELLED"}


def resolve_chain_batch_scope(target, active_modifier, scope="ALL", chain_uuid=""):
    """Resolve one transient batch range from the live modifier stack."""
    chain_uuid = chain_uuid or stage_chain_uuid(active_modifier)
    report = validate_chain(target, chain_uuid)
    stages = tuple(report["stages"])
    if report["broken"] or len(stages) < 2:
        return report, (), -1
    try:
        active_index = stages.index(active_modifier)
    except ValueError:
        return report, (), -1
    scope = str(scope or "ALL").upper()
    if scope == "TO_ACTIVE":
        indices = tuple(range(0, active_index + 1))
    elif scope == "FROM_ACTIVE":
        indices = tuple(range(active_index, len(stages)))
    else:
        indices = tuple(range(len(stages)))
    return report, indices, active_index


def _assigned_number(old, authored, assignment):
    old = float(old)
    authored = float(authored)
    if not math.isfinite(old) or not math.isfinite(authored):
        raise ValueError("Batch values must be finite")
    assignment = str(assignment or "SET").upper()
    if assignment == "ADD":
        return old + authored
    if assignment == "MULTIPLY":
        return old * authored
    return authored


def _assigned_pair(old, authored, assignment, *, minimum=None):
    try:
        old_values = tuple(float(value) for value in old)
        authored_values = tuple(float(value) for value in authored)
    except (TypeError, ValueError) as error:
        raise ValueError("Batch values must be numeric") from error
    if len(old_values) != 2 or len(authored_values) != 2:
        raise ValueError("Batch end values must contain X and Z")
    result = tuple(
        _assigned_number(old_value, authored_value, assignment)
        for old_value, authored_value in zip(old_values, authored_values)
    )
    if minimum is not None:
        result = tuple(max(float(minimum), value) for value in result)
    return result


def _batch_values_equal(old, new):
    """Return whether one authored batch value is already in place."""
    if isinstance(old, (str, bytes)) or isinstance(new, (str, bytes)):
        return old == new
    if isinstance(old, bool) or isinstance(new, bool):
        return bool(old) == bool(new)
    try:
        old_values = tuple(old)
        new_values = tuple(new)
    except TypeError:
        try:
            return abs(float(old) - float(new)) <= EPSILON
        except (TypeError, ValueError):
            return old == new
    if len(old_values) != len(new_values):
        return False
    try:
        return all(
            abs(float(old_value) - float(new_value)) <= EPSILON
            for old_value, new_value in zip(old_values, new_values)
        )
    except (TypeError, ValueError):
        return old_values == new_values


def apply_chain_batch_edit(
        target, active_modifier, *, chain_uuid="", scope="ALL",
        operation="END_SCALE", end_side="BOTH", assignment="SET",
        scale=(1.0, 1.0), offset=(0.0, 0.0), gap=0.0,
        deform_type="BEND", angle_value=0.0, factor_value=0.0,
        shear_value=(0.0, 0.0),
        stage_enabled=True, preserve_span=True):
    """Apply one de-duplicated edit to a chain and reconnect it once."""
    core = _core()
    flush = getattr(core, "flush_pending_chain_updates", None)
    if flush is not None:
        flush(target)

    report, indices, _active_index = resolve_chain_batch_scope(
        target, active_modifier, scope, chain_uuid)
    stages = tuple(report.get("stages", ()))
    chain_uuid = str(report.get("chain_uuid", "") or "")
    if report.get("broken") or len(stages) < 2 or not indices:
        return 0
    controllers = tuple(_find_controller(target, stage) for stage in stages)
    if any(controller is None for controller in controllers):
        return 0

    # A batch command can be invoked immediately after an Empty transform or a
    # direct GN socket edit, before the normal timer has observed it. Settle all
    # live authoring state first so the command never pushes stale values back.
    sync = getattr(core, "sync_controller", None)
    if sync is not None:
        for controller in controllers:
            sync(controller, pull_transform=True, sync_mode="timer")
    if flush is not None:
        flush(target)

    report, indices, _active_index = resolve_chain_batch_scope(
        target, active_modifier, scope, chain_uuid)
    stages = tuple(report.get("stages", ()))
    chain_uuid = str(report.get("chain_uuid", "") or "")
    if report.get("broken") or len(stages) < 2 or not indices:
        return 0
    controllers = tuple(_find_controller(target, stage) for stage in stages)
    if any(controller is None for controller in controllers):
        return 0

    operation = str(operation or "END_SCALE").upper()
    end_side = str(end_side or "BOTH").upper()
    if end_side not in {"TOP", "BOTTOM", "BOTH"}:
        raise ValueError("Unknown cage end selection")
    property_mutations = {}
    gap_mutations = {}

    def set_property(index, name, value):
        property_mutations[(int(index), str(name))] = value

    if operation == "END_SCALE":
        linked = chain_sync_shared_end_scale(target, chain_uuid, False)
        if linked:
            boundaries = set()
            for index in indices:
                if end_side in {"BOTTOM", "BOTH"}:
                    boundaries.add(index)
                if end_side in {"TOP", "BOTH"}:
                    boundaries.add(index + 1)
            for boundary in sorted(boundaries):
                if boundary <= 0:
                    old = tuple(controllers[0].sdh_cage_deform.bottom_scale)
                else:
                    old = tuple(
                        controllers[boundary - 1].sdh_cage_deform.top_scale)
                value = _assigned_pair(
                    old, scale, assignment, minimum=0.05)
                if boundary > 0:
                    set_property(boundary - 1, "top_scale", value)
                if boundary < len(stages):
                    set_property(boundary, "bottom_scale", value)
        else:
            for index in indices:
                properties = controllers[index].sdh_cage_deform
                if end_side in {"TOP", "BOTH"}:
                    set_property(
                        index, "top_scale",
                        _assigned_pair(
                            properties.top_scale, scale, assignment,
                            minimum=0.05),
                    )
                if end_side in {"BOTTOM", "BOTH"}:
                    set_property(
                        index, "bottom_scale",
                        _assigned_pair(
                            properties.bottom_scale, scale, assignment,
                            minimum=0.05),
                    )
    elif operation == "END_OFFSET":
        for index in indices:
            properties = controllers[index].sdh_cage_deform
            if end_side in {"TOP", "BOTH"}:
                set_property(
                    index, "top_offset",
                    _assigned_pair(properties.top_offset, offset, assignment),
                )
            if end_side in {"BOTTOM", "BOTH"}:
                set_property(
                    index, "bottom_offset",
                    _assigned_pair(properties.bottom_offset, offset, assignment),
                )
    elif operation == "GAP":
        for index in indices:
            if index <= 0:
                continue
            properties = controllers[index].sdh_cage_deform
            old_gap = stage_chain_gap(stages[index])
            requested = max(
                _assigned_number(old_gap, gap, assignment), 0.0)
            old_length = max(float(properties.size[1]), EPSILON)
            if preserve_span:
                span = old_gap + old_length
                new_length = max(span - requested, EPSILON)
                actual_gap = max(span - new_length, 0.0)
            else:
                new_length = old_length
                actual_gap = requested
            gap_mutations[index] = (actual_gap, new_length)
    elif operation == "DEFORMATION":
        deform_type = str(deform_type or "BEND").upper()
        definitions = {
            "BEND": ("BEND", "bend_strength", angle_value),
            "BEND_DIRECTION": ("BEND", "bend_direction", angle_value),
            "TWIST": ("TWIST", "twist_strength", angle_value),
            "TAPER": ("TAPER", "taper_factor", factor_value),
            "STRETCH": ("STRETCH", "stretch_factor", factor_value),
        }
        if deform_type == "SHEAR":
            for index in indices:
                properties = controllers[index].sdh_cage_deform
                if "SHEAR" not in set(properties.deform_types):
                    continue
                set_property(
                    index,
                    "shear_factors",
                    _assigned_pair(
                        properties.shear_factors, shear_value, assignment),
                )
        elif deform_type not in definitions:
            raise ValueError("Unknown deformation parameter")
        else:
            required_layer, attribute, authored = definitions[deform_type]
            for index in indices:
                properties = controllers[index].sdh_cage_deform
                if required_layer not in set(properties.deform_types):
                    continue
                set_property(
                    index,
                    attribute,
                    _assigned_number(
                        getattr(properties, attribute), authored, assignment),
                )
    elif operation == "STAGE_ENABLED":
        for index in indices:
            set_property(index, "stage_enabled", bool(stage_enabled))
    else:
        raise ValueError("Unknown batch operation")

    property_mutations = {
        (index, name): value
        for (index, name), value in property_mutations.items()
        if not _batch_values_equal(
            getattr(controllers[index].sdh_cage_deform, name), value)
    }
    gap_mutations = {
        index: (new_gap, new_length)
        for index, (new_gap, new_length) in gap_mutations.items()
        if (
            abs(stage_chain_gap(stages[index]) - new_gap) > EPSILON or
            abs(float(controllers[index].sdh_cage_deform.size[1]) -
                new_length) > EPSILON
        )
    }
    if not property_mutations and not gap_mutations:
        return 0

    snapshots = tuple(
        (_capture_controller_state(controller), stage_chain_gap(stage))
        for stage, controller in zip(stages, controllers)
    )
    syncing = getattr(core, "_SYNCING", set())
    pointers = tuple(
        pointer for pointer in (_pointer(controller) for controller in controllers)
        if pointer
    )
    transaction = getattr(core, "chain_reconnect_transaction", None)
    transaction_context = (
        transaction(target, chain_uuid) if transaction is not None else None)
    chain_mode = stage_chain_mode(stages[0], "").upper()
    should_reconnect = bool(
        chain_mode in {"CHAINED", "CONNECTED"} and
        chain_auto_reconnect(target, chain_uuid, True)
    )

    def apply():
        syncing.update(pointers)
        try:
            for (index, name), value in property_mutations.items():
                setattr(controllers[index].sdh_cage_deform, name, value)
            for index, (new_gap, new_length) in gap_mutations.items():
                properties = controllers[index].sdh_cage_deform
                properties.size = (
                    float(properties.size[0]),
                    float(new_length),
                    float(properties.size[2]),
                )
                controllers[index].scale = (
                    float(properties.size[0]) * 0.5,
                    float(new_length) * 0.5,
                    float(properties.size[2]) * 0.5,
                )
                _write_stage_gap(stages[index], controllers[index], new_gap)

            legacy = getattr(core, "_legacy_values_for_primary", None)
            if operation == "DEFORMATION" and legacy is not None:
                for index in indices:
                    properties = controllers[index].sdh_cage_deform
                    strength, factor, direction = legacy(properties)
                    properties.strength = strength
                    properties.factor = factor
                    properties.direction = direction
        finally:
            for pointer in pointers:
                syncing.discard(pointer)

        if sync is not None:
            # Relative seam scales and disabled-stage baselines can change
            # downstream even when only one authored controller was edited.
            for controller in controllers:
                sync(controller, pull_transform=False)
        if should_reconnect:
            reconnect_chain(target, chain_uuid)
        try:
            target.update_tag()
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass

    def rollback():
        syncing.update(pointers)
        try:
            for index, (_snapshot, old_gap) in enumerate(snapshots):
                _write_stage_gap(stages[index], controllers[index], old_gap)
        finally:
            for pointer in pointers:
                syncing.discard(pointer)
        for controller, (snapshot, _old_gap) in zip(controllers, snapshots):
            _restore_controller_state(controller, snapshot)
        try:
            target.update_tag()
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass

    def run(commit=None):
        try:
            apply()
        except Exception:
            try:
                rollback()
            finally:
                # The restored snapshots are authoritative. Discard reconnect
                # requests produced by the failed half-transaction.
                if commit is not None:
                    commit()
            raise
        if commit is not None:
            commit()

    if transaction_context is None:
        run()
    else:
        with transaction_context as commit:
            run(commit)
    return len(set(index for index, _name in property_mutations) |
               set(gap_mutations))


def _capture_batch_preview_snapshot(target, active_modifier, chain_uuid=""):
    """Capture a stable, fully synchronized state for the batch dialog.

    A batch dialog can receive dozens of property updates while it is open.
    Keeping the snapshot at the dialog boundary makes every preview edit an
    independent transaction instead of applying ADD/MULTIPLY against the
    previous preview result.
    """
    if target is None:
        return None
    core = _core()
    flush = getattr(core, "flush_pending_chain_updates", None)
    if flush is not None:
        flush(target)
    chain_uuid = str(chain_uuid or stage_chain_uuid(active_modifier) or "")
    stages = tuple(chain_stages(target, chain_uuid))
    if (
            not chain_uuid or len(stages) < 2 or
            active_modifier not in stages
    ):
        return None
    controllers = tuple(_find_controller(target, stage) for stage in stages)
    if any(controller is None for controller in controllers):
        return None
    sync = getattr(core, "sync_controller", None)
    if sync is not None:
        for controller in controllers:
            sync(controller, pull_transform=True, sync_mode="timer")
    if flush is not None:
        flush(target)
    # Resolve the live stack again after timer-side synchronization. A stale
    # modifier or controller reference must never be used to restore a dialog.
    stages = tuple(chain_stages(target, chain_uuid))
    controllers = tuple(_find_controller(target, stage) for stage in stages)
    if (
            len(stages) < 2 or active_modifier not in stages or
            any(controller is None for controller in controllers)
    ):
        return None
    return {
        "target": target,
        "chain_uuid": chain_uuid,
        "stages": stages,
        "active_modifier": active_modifier,
        "records": tuple({
            "controller": controller,
            "state": _capture_controller_state(controller),
            "gap": stage_chain_gap(stage),
        } for stage, controller in zip(stages, controllers)),
    }


def _restore_batch_preview_snapshot(snapshot):
    """Restore a batch dialog snapshot without forcing chain reconnection."""
    if not snapshot:
        return False
    target = snapshot.get("target")
    chain_uuid = str(snapshot.get("chain_uuid", "") or "")
    stages = tuple(snapshot.get("stages", ()))
    records = tuple(snapshot.get("records", ()))
    if target is None or not chain_uuid or len(stages) != len(records):
        return False
    live_stages = tuple(chain_stages(target, chain_uuid))
    if (
            live_stages != stages or
            any(record.get("controller") is None for record in records)
    ):
        return False
    core = _core()
    sync = getattr(core, "sync_controller", None)
    transaction = getattr(core, "chain_reconnect_transaction", None)

    def restore():
        # Restore every authoring channel first, then push all node groups.
        # This avoids a partially restored relative seam being observed by a
        # neighboring stage during cancellation or the next preview sample.
        for stage, record in zip(stages, records):
            controller = record["controller"]
            _write_stage_gap(stage, controller, record.get("gap", 0.0))
            _restore_controller_state(
                controller, record.get("state", {}), sync=False)
        if sync is not None:
            for record in records:
                sync(record["controller"], pull_transform=False)
        try:
            target.update_tag()
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass

    if transaction is None:
        restore()
    else:
        # Committing the restore clears any reconnect request generated by the
        # temporary preview while preserving the authored downstream frames.
        with transaction(target, chain_uuid) as commit:
            restore()
            commit()
    return True


def _batch_preview_values(operator):
    """Build one immutable argument set from the dialog's current values."""
    return {
        "scope": str(operator.scope),
        "operation": str(operator.operation),
        "end_side": str(operator.end_side),
        "assignment": str(operator.assignment),
        "scale": tuple(float(value) for value in operator.scale),
        "offset": tuple(float(value) for value in operator.offset),
        "gap": float(operator.gap),
        "deform_type": str(operator.deform_type),
        "angle_value": float(operator.angle_value),
        "factor_value": float(operator.factor_value),
        "stage_enabled": bool(operator.stage_enabled),
        "preserve_span": bool(operator.preserve_span),
    }


def _apply_batch_preview(operator):
    """Restore the dialog baseline and apply exactly one current edit."""
    snapshot = getattr(operator, "_batch_preview_snapshot", None)
    if not snapshot or not _restore_batch_preview_snapshot(snapshot):
        return 0
    target = snapshot.get("target")
    modifier = snapshot.get("active_modifier")
    values = _batch_preview_values(operator)
    return apply_chain_batch_edit(
        target, modifier, chain_uuid=snapshot.get("chain_uuid", ""),
        **values)


def _batch_preview_property_update(operator, context):
    """Apply a non-cumulative preview when a dialog property changes."""
    if not getattr(operator, "_batch_preview_ready", False):
        return
    if getattr(operator, "_batch_preview_guard", False):
        return
    snapshot = getattr(operator, "_batch_preview_snapshot", None)
    if not snapshot:
        return
    operator._batch_preview_guard = True
    try:
        _apply_batch_preview(operator)
        operator._batch_preview_active = True
        operator._batch_preview_error = ""
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as error:
        # An invalid combination should leave the scene at the last authored
        # state and keep the dialog usable for another choice.
        try:
            _restore_batch_preview_snapshot(snapshot)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        operator._batch_preview_error = str(error)
    finally:
        operator._batch_preview_guard = False


class SDH_OT_batch_edit_cage_chain(Operator):
    bl_idname = "sdh.batch_edit_cage_chain"
    bl_label = "Batch Edit Chain"
    bl_description = "Edit several cages in the active chain as one operation"
    bl_options = {"REGISTER", "UNDO"}

    chain_id: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})
    scope: EnumProperty(
        name="Scope",
        items=(
            ("ALL", "Whole Chain", "Edit every cage in this chain"),
            ("TO_ACTIVE", "Start to Active", "Edit the chain root through the active cage"),
            ("FROM_ACTIVE", "Active to End", "Edit the active cage through the chain tip"),
        ),
        default="ALL",
        update=_batch_preview_property_update,
    )
    operation: EnumProperty(
        name="Operation",
        items=(
            ("END_SCALE", "End Scale", "Batch-edit top and bottom cross-section scale"),
            ("END_OFFSET", "End Offset", "Batch-edit top and bottom cross-section offset"),
            ("GAP", "Gap", "Set spacing before every cage in scope"),
            ("DEFORMATION", "Deformation", "Batch-edit one deformation parameter"),
            ("STAGE_ENABLED", "Stage Visibility", "Apply or bypass every cage in scope"),
        ),
        default="END_SCALE",
        update=_batch_preview_property_update,
    )
    end_side: EnumProperty(
        name="Ends",
        items=(
            ("TOP", "Top", "Edit top ends"),
            ("BOTTOM", "Bottom", "Edit bottom ends"),
            ("BOTH", "Both", "Edit both ends"),
        ),
        default="BOTH",
        update=_batch_preview_property_update,
    )
    assignment: EnumProperty(
        name="Apply As",
        items=(
            ("SET", "Set Values", "Replace existing values"),
            ("ADD", "Add Values", "Add to existing values"),
            ("MULTIPLY", "Multiply Values", "Multiply existing values"),
        ),
        default="SET",
        update=_batch_preview_property_update,
    )
    scale: FloatVectorProperty(
        name="Scale",
        description="X and Z cross-section values",
        size=2,
        default=(1.0, 1.0),
        soft_min=-10.0,
        soft_max=10.0,
        update=_batch_preview_property_update,
    )
    offset: FloatVectorProperty(
        name="Offset",
        description="X and Z cross-section offset values",
        size=2,
        default=(0.0, 0.0),
        soft_min=-10.0,
        soft_max=10.0,
        update=_batch_preview_property_update,
    )
    gap: FloatProperty(
        name="Gap",
        description="Spacing before each affected downstream cage",
        default=0.0,
        soft_min=-10.0,
        soft_max=10.0,
        update=_batch_preview_property_update,
    )
    preserve_span: BoolProperty(
        name="Preserve Total Range",
        description="Shorten each cage as its incoming gap grows",
        default=True,
        update=_batch_preview_property_update,
    )
    deform_type: EnumProperty(
        name="Parameter",
        items=(
            ("BEND", "Bend Angle", "Batch-edit Bend angle"),
            ("BEND_DIRECTION", "Bend Direction", "Batch-edit Bend direction"),
            ("TWIST", "Twist Angle", "Batch-edit Twist angle"),
            ("TAPER", "Taper Factor", "Batch-edit Taper factor"),
            ("STRETCH", "Stretch Factor", "Batch-edit Stretch factor"),
        ),
        default="BEND",
        update=_batch_preview_property_update,
    )
    angle_value: FloatProperty(
        name="Angle",
        subtype="ANGLE",
        default=0.0,
        soft_min=-math.tau,
        soft_max=math.tau,
        update=_batch_preview_property_update,
    )
    factor_value: FloatProperty(
        name="Factor",
        default=0.0,
        soft_min=-2.0,
        soft_max=2.0,
        update=_batch_preview_property_update,
    )
    stage_enabled: BoolProperty(
        name="Enable Stages",
        description="Apply the affected cage stages",
        default=True,
        update=_batch_preview_property_update,
    )

    @classmethod
    def poll(cls, context):
        target, modifier, _controller = _call(
            "resolve_context_deform", context, default=(None, None, None))
        chain_uuid = stage_chain_uuid(modifier) if modifier is not None else ""
        return bool(target and chain_uuid and len(chain_stages(target, chain_uuid)) >= 2)

    def invoke(self, context, event):
        target, modifier, controller = _call(
            "resolve_context_deform", context, default=(None, None, None))
        if target is None or modifier is None or controller is None:
            return {"CANCELLED"}
        # Property callbacks are enabled only after the baseline is captured;
        # assigning the initial dialog values must never count as a preview.
        self._batch_preview_ready = False
        self._batch_preview_active = False
        self._batch_preview_guard = False
        self._batch_preview_error = ""
        chain_uuid = stage_chain_uuid(modifier)
        snapshot = _capture_batch_preview_snapshot(
            target, modifier, chain_uuid)
        if snapshot is None:
            return {"CANCELLED"}
        self.chain_id = chain_uuid
        properties = controller.sdh_cage_deform
        self.scale = tuple(properties.top_scale)
        self.offset = tuple(properties.top_offset)
        self.gap = stage_chain_gap(modifier)
        self.angle_value = float(properties.bend_strength)
        self.factor_value = float(properties.taper_factor)
        self.stage_enabled = bool(properties.stage_enabled)
        self._batch_preview_snapshot = snapshot
        self._batch_preview_ready = True
        return context.window_manager.invoke_props_dialog(self, width=440)

    def cancel(self, context):
        snapshot = getattr(self, "_batch_preview_snapshot", None)
        if snapshot is not None:
            self._batch_preview_guard = True
            try:
                _restore_batch_preview_snapshot(snapshot)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
            finally:
                self._batch_preview_guard = False
        self._batch_preview_ready = False
        self._batch_preview_active = False
        self._batch_preview_snapshot = None

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "scope")
        layout.prop(self, "operation")
        if self.operation in {"END_SCALE", "END_OFFSET"}:
            layout.prop(self, "end_side", expand=True)
            layout.prop(self, "assignment", expand=True)
            layout.prop(
                self,
                "scale" if self.operation == "END_SCALE" else "offset",
            )
            if self.operation == "END_SCALE":
                layout.label(
                    text="Linked shared boundaries are changed only once.",
                    icon="LINKED",
                )
        elif self.operation == "GAP":
            layout.prop(self, "assignment", expand=True)
            layout.prop(self, "gap")
            layout.prop(self, "preserve_span")
        elif self.operation == "DEFORMATION":
            layout.prop(self, "deform_type")
            layout.prop(self, "assignment", expand=True)
            if self.deform_type in {"BEND", "BEND_DIRECTION", "TWIST"}:
                layout.prop(self, "angle_value")
            else:
                layout.prop(self, "factor_value")
            layout.label(
                text="Cages without this deformation layer are skipped.",
                icon="INFO",
            )
        else:
            layout.prop(self, "stage_enabled")

    def execute(self, context):
        snapshot = getattr(self, "_batch_preview_snapshot", None)
        target, modifier, _controller = _call(
            "resolve_context_deform", context, default=(None, None, None))
        if snapshot is not None:
            target = snapshot.get("target")
            modifier = snapshot.get("active_modifier")
        if target is None or modifier is None:
            return {"CANCELLED"}
        chain_uuid = self.chain_id or stage_chain_uuid(modifier)
        self._batch_preview_guard = True
        try:
            # A preview has already mutated the live chain. Rebase on the
            # original snapshot before committing the final dialog values so
            # ADD and MULTIPLY are evaluated exactly once.
            if snapshot is not None and getattr(
                    self, "_batch_preview_active", False):
                if not _restore_batch_preview_snapshot(snapshot):
                    raise RuntimeError("Batch preview state is no longer valid")
            changed = apply_chain_batch_edit(
                target,
                modifier,
                chain_uuid=chain_uuid,
                scope=self.scope,
                operation=self.operation,
                end_side=self.end_side,
                assignment=self.assignment,
                scale=self.scale,
                offset=self.offset,
                gap=self.gap,
                deform_type=self.deform_type,
                angle_value=self.angle_value,
                factor_value=self.factor_value,
                stage_enabled=self.stage_enabled,
                preserve_span=self.preserve_span,
            )
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError) as error:
            if snapshot is not None:
                try:
                    _restore_batch_preview_snapshot(snapshot)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
            self.report(
                {"ERROR"},
                iface_("Could not batch edit chain: {error}").format(
                    error=error),
            )
            self._batch_preview_guard = False
            self._batch_preview_ready = False
            self._batch_preview_active = False
            self._batch_preview_snapshot = None
            return {"CANCELLED"}
        self._batch_preview_guard = False
        if changed <= 0:
            self.report(
                {"WARNING"}, iface_("No matching cage values were changed"))
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            iface_("Updated {count} cage stages").format(count=changed),
        )
        self._batch_preview_ready = False
        self._batch_preview_active = False
        self._batch_preview_snapshot = None
        return {"FINISHED"}


class SDH_OT_reconnect_cage_chain(Operator):
    bl_idname = "sdh.reconnect_cage_chain"
    bl_label = "Reconnect Cage Chain"
    bl_description = "Propagate each preceding cage output frame to the next cage"
    bl_options = {"REGISTER", "UNDO"}

    chain_id: StringProperty(name="Chain UUID", default="", options={"HIDDEN"})
    allow_broken: BoolProperty(
        name="Reconnect Broken Chain",
        description="Attempt contiguous stages even when a stack issue is detected",
        default=False,
        options={"HIDDEN"},
    )

    @classmethod
    def poll(cls, context):
        target = _target_from_context(context)
        if target is None:
            return False
        chain_uuid = cls._resolve_chain_id(context, target)
        if len(chain_stages(target, chain_uuid)) >= 2:
            return True
        # A caller may provide ``chain_id`` from a panel while another stage
        # is active.  Polling cannot see the instance property, so accept any
        # target that owns at least one reconnectable chain.
        return any(len(chain_stages(target, value)) >= 2 for value in chain_ids(target))

    @staticmethod
    def _resolve_chain_id(context, target):
        return _resolve_chain_uuid(target)

    def execute(self, context):
        target = _target_from_context(context)
        if target is None:
            return {"CANCELLED"}
        chain_uuid = self.chain_id or _resolve_chain_uuid(target)
        report = validate_chain(target, chain_uuid)
        if report["broken"] and not self.allow_broken:
            self.report(
                {"WARNING"},
                "; ".join(report["messages"]) or iface_("Cage chain is broken"),
            )
            _normalize_metadata(target, chain_uuid, broken=True)
            return {"CANCELLED"}
        updated = reconnect_chain(target, chain_uuid, allow_broken=self.allow_broken)
        if updated <= 0:
            self.report(
                {"WARNING"},
                "; ".join(report["messages"]) or iface_(
                    "No Cage Chain was found"),
            )
            return {"CANCELLED"}
        _activate(context, target)
        self.report(
            {"INFO"},
            iface_("Reconnected {count} cage stages").format(
                count=updated + 1),
        )
        return {"FINISHED"}


class SDH_OT_create_cage_chain(SDH_OT_add_cage_chain):
    """Compatibility alias for files/scripts using the prototype operator."""
    bl_idname = "sdh.create_cage_chain"
    bl_label = "Create Cage Chain"


# Do not register an operator subclass that inherits the callbacks of another
# registered operator.  Blender's RNA callback lookup treats the inherited
# ``poll``/``execute`` functions as belonging to the last registered RNA
# struct, which makes ``bpy.ops.sdh.add_cage_chain`` lose its callbacks.  The
# compatibility class remains available to Python callers, while the public
# operator surface uses the two canonical IDs below.
classes = (
    SDH_OT_add_cage_chain,
    SDH_OT_subdivide_cage_to_chain,
    SDH_OT_batch_edit_cage_chain,
    SDH_OT_reconnect_cage_chain,
)


def register():
    for item in classes:
        bpy.utils.register_class(item)


def unregister():
    for item in reversed(classes):
        bpy.utils.unregister_class(item)
