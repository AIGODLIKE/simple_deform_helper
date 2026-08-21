"""Cage deform core: nodes, sync, properties, operators, geometry."""
from __future__ import annotations

import hashlib
import math
import time
import uuid
from array import array
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import bpy
import numpy as np
from bpy.app.handlers import persistent
from bpy.app.translations import pgettext_iface as iface_
from bpy.props import (
    BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
    FloatVectorProperty, IntProperty, IntVectorProperty, StringProperty,
)
from bpy.types import Operator, PropertyGroup, WorkSpaceTool
from mathutils import Euler, Matrix, Quaternion, Vector

from .curve import SDHCurvePoint, SDHCurveStation
from .deform_contract import (  # noqa: F401 - compatibility exports
    CHAIN_BOUNDARY_EPSILON,
    CHAIN_GAP_MAX,
    CURVE_LENGTH_VALUES,
    CURVE_MODE_VALUES,
    DEFORM_BITS,
    DEFORM_MASK_ALL,
    DEFORM_ORDER,
    EPSILON,
    FFD_COMPONENT_COUNT,
    FFD_CORNERS,
    FFD_SOCKET_NAMES,
    MODE_VALUES,
    ORIGIN_VALUES,
    _deform_name,
    _full_deform_order,
    deform_order_signature,
    normalize_deform_order,
)
from .ffd_projection import projected_entity_cache
from .ffd_guard import (
    MIN_JACOBIAN_RATIO,
    SAFE_INTERPOLATION,
    clamp_offsets,
)
from .ffd_resolution import (
    remap_index,
    remap_indices,
    resample_offsets,
    resample_values,
)
from .node_runtime import (
    cache_interface_identifiers,
    cached_interface_identifiers,
    clear_runtime_state as clear_node_runtime_state,
    rna_pointer as _pointer,
)
from .node_schema import (  # noqa: F401 - compatibility exports
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
from . import undo as _undo

from ..stages import (
    StageCache,
    _bounds_from_points,
    _object_fallback_bounds,
    hide_runtime_object,
    render_job_running,
)
from ..utils import (
    GizmoUtils,
    PublicData,
    control_collection,
    get_pref,
    move_object_to_control_collection,
    remove_unused_control_collections,
    set_helper_object_visible,
)


GROUP_NAME = "SDH Cage Deform Core"
# Runtime copies take a leading dot so Blender hides managed groups from the
# node-group search list and the Geometry Nodes modifier dropdown, keeping
# user files uncluttered.  The packaged asset keeps the visible name.
GROUP_RUNTIME_NAME = ".SDH Cage Deform Core"
STAGE_GROUP_NAME_PREFIX = ".SDH Cage Deform "
GROUP_LIBRARY_PATH = (
    Path(__file__).resolve().parent / "assets" / "cage_deform_core.blend")
MODIFIER_MARKER = "_sdh_cage_deform_stage"
MODIFIER_UUID = "_sdh_cage_deform_modifier_uuid"
CONTROLLER_MARKER = "_sdh_cage_deform_controller"
CONTROLLER_UUID = "_sdh_cage_deform_controller_uuid"
TARGET_UUID = "_sdh_cage_deform_target_uuid"
TARGET_SHOW_OTHER_CAGES = "_sdh_cage_show_other_cages"
TARGET_CONVERTED_SOURCE_TYPE = "_sdh_cage_converted_source_type"
RUNTIME_EVALUATOR = "_sdh_cage_deform_runtime_evaluator"
CONTROLLER_ACTIVE_DISPLAY = "_sdh_cage_active_display"
AUTHORED_TOP_SCALE = "_sdh_cage_authored_top_scale"
AUTHORED_BOTTOM_SCALE = "_sdh_cage_authored_bottom_scale"
_LEGACY_CHAIN_CORRECTION_PREFIX = "SDH_CHAIN_CORRECTION_"

# POST_PIXEL handlers outlive an operator instance when an extension is
# reloaded while FFD edit mode is active. Keep their tokens at module scope so
# registration cleanup can remove them before Blender unregisters the class.
_FFD_DRAW_HANDLERS = []
_FFD_MODAL_OPERATORS = []
_FFD_KEYMAPS = []
_CURVE_KEYMAPS = []
_FFD_WORKSPACE_TOOL_ID = "sdh.ffd_edit"
_CURVE_WORKSPACE_TOOL_ID = "sdh.curve_edit"
_FFD_WORKSPACE_TOOL_REGISTERED = False
_CURVE_WORKSPACE_TOOL_REGISTERED = False
_FFD_PREVIOUS_WORKSPACE_TOOLS = {}
_CURVE_PREVIOUS_WORKSPACE_TOOLS = {}
_FFD_HOVER_ENTITIES = {}


def _ffd_hover_key(controller):
    try:
        return int(controller.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return id(controller) if controller is not None else 0


def ffd_hover_entity(controller):
    """Return the transient entity under the FFD editor pointer."""
    key = _ffd_hover_key(controller)
    return _FFD_HOVER_ENTITIES.get(key) if key else None


def set_ffd_hover_entity(controller, entity):
    key = _ffd_hover_key(controller)
    if not key:
        return
    if entity is None:
        _FFD_HOVER_ENTITIES.pop(key, None)
    else:
        _FFD_HOVER_ENTITIES[key] = tuple(entity)


def clear_ffd_hover_entity(controller=None):
    if controller is None:
        _FFD_HOVER_ENTITIES.clear()
    else:
        _FFD_HOVER_ENTITIES.pop(_ffd_hover_key(controller), None)


def ffd_handles_enabled():
    """Return the global FFD handle visibility preference.

    ``show_ffd_handles`` used to live on every cage controller and remains on
    the property group for file compatibility.  The viewport display switch is
    now an add-on preference, so all drawing and modal paths must consult one
    source of truth instead of diverging per controller.
    """
    try:
        preference = get_pref()
        if preference is not None:
            return bool(getattr(preference, "show_ffd_handles", True))
    except (AttributeError, KeyError, ReferenceError, RuntimeError, TypeError):
        pass
    return True


def _ffd_edit_session_live(controller):
    """Return whether one controller owns a live persistent FFD modal."""
    if controller is None:
        return False
    for operator in tuple(_FFD_MODAL_OPERATORS):
        try:
            if (
                    not bool(getattr(operator, "_ffd_modal_finished", False)) and
                    operator._controller() == controller
            ):
                return True
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            continue
    return False


def _reconcile_ffd_edit_session_flags():
    """Clear undo/load-restored edit flags that have no modal owner."""
    changed = 0
    for controller in _data_objects_snapshot():
        try:
            if not is_cage_controller(controller):
                continue
            properties = controller.sdh_cage_deform
            if (
                    str(getattr(properties, "cage_type", "")) == "FFD" and
                    bool(getattr(properties, "ffd_edit_mode_active", False)) and
                    not _ffd_edit_session_live(controller)
            ):
                properties.ffd_edit_mode_active = False
                clear_ffd_hover_entity(controller)
                changed += 1
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            continue
    return changed


def finish_ffd_edit_sessions(
        context=None, *, restore_target=False, include_native=True):
    """Finish every live FFD editor owned by this extension.

    Blender keeps modal operators alive independently from the panel that
    started them.  Explicitly ending the sessions before a new cage is added
    prevents the old modal from consuming the next click or leaving stale draw
    handlers behind.  The operation is idempotent and safe during unregister.
    """
    sessions = tuple(_FFD_MODAL_OPERATORS)
    finished = 0
    for operator in sessions:
        try:
            operator._finish_modal(
                context or bpy.context,
                restore_target=bool(restore_target),
            )
            finished += 1
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            try:
                _FFD_MODAL_OPERATORS.remove(operator)
            except ValueError:
                pass
    if include_native:
        try:
            from .ffd_native_edit import finish_native_edit_sessions
            finished += finish_native_edit_sessions(
                context or bpy.context,
                restore_target=bool(restore_target),
            )
        except (ImportError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            pass
    _reconcile_ffd_edit_session_flags()
    return finished


def remove_ffd_draw_handlers():
    """Remove every FFD box-selection draw callback owned by this module."""
    while _FFD_DRAW_HANDLERS:
        handler = _FFD_DRAW_HANDLERS.pop()
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handler, "WINDOW")
        except (ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    _FFD_MODAL_OPERATORS.clear()
    clear_ffd_hover_entity()


def _safe_ffd_box_draw(operator):
    """Ignore stale modal callbacks after an operator class is unregistered."""
    try:
        operator._draw_box()
    except (ReferenceError, RuntimeError, TypeError, ValueError):
        pass


def register_ffd_keymaps():
    """Keep cage shortcuts scoped to their active Workspace Tool.

    Older releases injected two unconditional ``B`` bindings into Blender's
    global 3D View keymap.  That made native box select unreliable whenever a
    cage had ever been created, including with an empty selection.  B is now
    declared in each ``WorkSpaceTool.bl_keymap`` below, so Blender's own
    Select Box binding remains authoritative outside the cage editor.
    """
    _FFD_KEYMAPS.clear()
    _CURVE_KEYMAPS.clear()


def unregister_ffd_keymaps():
    """Remove cage-editor keymap entries during reload/unregister."""
    for keymap, item in reversed(tuple(_CURVE_KEYMAPS)):
        try:
            keymap.keymap_items.remove(item)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    _CURVE_KEYMAPS.clear()
    for keymap, item in reversed(tuple(_FFD_KEYMAPS)):
        try:
            keymap.keymap_items.remove(item)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    _FFD_KEYMAPS.clear()


def register_ffd_workspace_tool():
    """Register scoped FFD and Curve editors without changing keyconfigs."""
    global _CURVE_WORKSPACE_TOOL_REGISTERED, _FFD_WORKSPACE_TOOL_REGISTERED
    if not _FFD_WORKSPACE_TOOL_REGISTERED:
        bpy.utils.register_tool(
            SDH_WST_ffd_edit,
            after={"builtin.select_box"},
            separator=True,
            group=False,
        )
        _FFD_WORKSPACE_TOOL_REGISTERED = True
    if not _CURVE_WORKSPACE_TOOL_REGISTERED:
        bpy.utils.register_tool(
            SDH_WST_curve_edit,
            after={_FFD_WORKSPACE_TOOL_ID},
            separator=False,
            group=False,
        )
        _CURVE_WORKSPACE_TOOL_REGISTERED = True
    register_ffd_keymaps()


def unregister_ffd_workspace_tool():
    """Remove cage editors and every add-on-owned shortcut."""
    global _CURVE_WORKSPACE_TOOL_REGISTERED, _FFD_WORKSPACE_TOOL_REGISTERED
    try:
        if bpy.app.timers.is_registered(_runtime_bootstrap_timer):
            bpy.app.timers.unregister(_runtime_bootstrap_timer)
    except (AttributeError, RuntimeError, ValueError):
        pass
    unregister_ffd_keymaps()
    if _CURVE_WORKSPACE_TOOL_REGISTERED:
        try:
            bpy.utils.unregister_tool(SDH_WST_curve_edit)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        _CURVE_WORKSPACE_TOOL_REGISTERED = False
    _CURVE_PREVIOUS_WORKSPACE_TOOLS.clear()
    if not _FFD_WORKSPACE_TOOL_REGISTERED:
        _FFD_PREVIOUS_WORKSPACE_TOOLS.clear()
        return
    try:
        bpy.utils.unregister_tool(SDH_WST_ffd_edit)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    _FFD_WORKSPACE_TOOL_REGISTERED = False
    _FFD_PREVIOUS_WORKSPACE_TOOLS.clear()


def _active_workspace_tool_id(context):
    """Return the active Object-mode 3D View tool without creating one."""
    try:
        workspace = context.workspace
        tool = workspace.tools.from_space_view3d_mode(
            "OBJECT", create=False)
        return str(getattr(tool, "idname", ""))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ""


def _workspace_tool_key(context):
    try:
        return int(context.workspace.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return 0


def _set_workspace_tool(context, tool_id):
    """Set a 3D View tool across Blender API variants."""
    try:
        bpy.ops.wm.tool_set_by_id(
            name=str(tool_id), space_type="VIEW_3D")
        return True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        try:
            # Some 5.x builds reject ``space_type`` from a temporary window
            # override even though the operator is otherwise executable.
            bpy.ops.wm.tool_set_by_id(name=str(tool_id))
            return True
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False


@contextmanager
def _view3d_workspace_context(context):
    """Yield a usable 3D View context for operators called by app timers."""
    if getattr(getattr(context, "area", None), "type", "") == "VIEW_3D":
        yield context
        return
    workspace = getattr(context, "workspace", None)
    window_manager = getattr(context, "window_manager", None)
    windows = tuple(getattr(window_manager, "windows", ()) or ())
    preferred = getattr(context, "window", None)
    if preferred in windows:
        windows = (preferred,) + tuple(
            window for window in windows if window != preferred)
    candidate = None
    # Prefer the context's workspace, but do not leave a dedicated cage tool
    # stranded when a timer callback has no area/workspace context (or when a
    # second Blender window became active).  A second pass over all windows is
    # safe because the operation is scoped to a concrete 3D View override.
    for same_workspace_only in (True, False):
        for window in windows:
            if (
                    same_workspace_only and workspace is not None and
                    getattr(window, "workspace", None) != workspace
            ):
                continue
            screen = getattr(window, "screen", None)
            for area in tuple(getattr(screen, "areas", ()) or ()):
                if getattr(area, "type", "") != "VIEW_3D":
                    continue
                region = next((
                    item for item in tuple(getattr(area, "regions", ()) or ())
                    if getattr(item, "type", "") == "WINDOW"
                ), None)
                if region is not None:
                    candidate = (window, area, region)
                    break
            if candidate is not None:
                break
        if candidate is not None:
            break
    if candidate is None:
        yield None
        return
    window, area, region = candidate
    with bpy.context.temp_override(
            window=window, area=area, region=region,
            space_data=area.spaces.active):
        yield bpy.context


def activate_ffd_workspace_tool(context):
    """Make blank drags use the scoped FFD tool after editing starts."""
    if not _FFD_WORKSPACE_TOOL_REGISTERED:
        return False
    with _view3d_workspace_context(context) as tool_context:
        if tool_context is None:
            return False
        current_tool = _active_workspace_tool_id(tool_context)
        if current_tool == _FFD_WORKSPACE_TOOL_ID:
            return True
        if current_tool:
            _FFD_PREVIOUS_WORKSPACE_TOOLS[
                _workspace_tool_key(tool_context)] = current_tool
        if not _set_workspace_tool(tool_context, _FFD_WORKSPACE_TOOL_ID):
            return False
        return _active_workspace_tool_id(tool_context) == _FFD_WORKSPACE_TOOL_ID


def activate_curve_workspace_tool(context):
    """Make blank drags re-enter Curve Object Edit after editing starts."""
    if not _CURVE_WORKSPACE_TOOL_REGISTERED:
        return False
    with _view3d_workspace_context(context) as tool_context:
        if tool_context is None:
            return False
        current_tool = _active_workspace_tool_id(tool_context)
        if current_tool == _CURVE_WORKSPACE_TOOL_ID:
            return True
        if current_tool:
            _CURVE_PREVIOUS_WORKSPACE_TOOLS[
                _workspace_tool_key(tool_context)] = current_tool
        if not _set_workspace_tool(tool_context, _CURVE_WORKSPACE_TOOL_ID):
            return False
        return _active_workspace_tool_id(tool_context) == _CURVE_WORKSPACE_TOOL_ID


def deactivate_ffd_workspace_tool(context):
    """Restore the prior tool when an explicit cage action leaves FFD."""
    with _view3d_workspace_context(context) as tool_context:
        if tool_context is None:
            return False
        if _active_workspace_tool_id(tool_context) != _FFD_WORKSPACE_TOOL_ID:
            return True
        previous = _FFD_PREVIOUS_WORKSPACE_TOOLS.pop(
            _workspace_tool_key(tool_context), "builtin.select_box")
        if not _set_workspace_tool(tool_context, previous):
            if not _set_workspace_tool(tool_context, "builtin.select_box"):
                return False
        return _active_workspace_tool_id(tool_context) != _FFD_WORKSPACE_TOOL_ID


def deactivate_curve_workspace_tool(context):
    """Restore the tool that preceded the scoped Curve editor."""
    with _view3d_workspace_context(context) as tool_context:
        if tool_context is None:
            return False
        if _active_workspace_tool_id(tool_context) != _CURVE_WORKSPACE_TOOL_ID:
            return True
        previous = _CURVE_PREVIOUS_WORKSPACE_TOOLS.pop(
            _workspace_tool_key(tool_context), "builtin.select_box")
        if not _set_workspace_tool(tool_context, previous):
            if not _set_workspace_tool(tool_context, "builtin.select_box"):
                return False
        return _active_workspace_tool_id(tool_context) != _CURVE_WORKSPACE_TOOL_ID


def activate_cage_workspace_tool(context, cage_type):
    """Activate the scoped editor owned by a dedicated cage type."""
    cage_type = str(cage_type).upper()
    if cage_type == "FFD":
        if not deactivate_curve_workspace_tool(context):
            return False
        return activate_ffd_workspace_tool(context)
    if cage_type == "CURVE":
        if not deactivate_ffd_workspace_tool(context):
            return False
        return activate_curve_workspace_tool(context)
    return bool(
        deactivate_ffd_workspace_tool(context) and
        deactivate_curve_workspace_tool(context)
    )


def _native_box_select_fallback(context, event=None):
    """Hand an empty-selection drag back to Blender's object Select Box."""
    with _view3d_workspace_context(context) as tool_context:
        if tool_context is None:
            return False
        # Use the built-in tool explicitly.  The previous tool may be Move or
        # Rotate, while the user's current gesture is unambiguously a box
        # selection after the cage editor has released ownership.
        if not _set_workspace_tool(tool_context, "builtin.select_box"):
            return False
        if event is None or str(getattr(event, "type", "")) != "LEFTMOUSE":
            return True
        try:
            result = bpy.ops.view3d.select_box("INVOKE_DEFAULT")
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return True
        return bool(
            "RUNNING_MODAL" in result or "FINISHED" in result)


def _live_workspace_cage_type(target):
    """Preserve a dedicated tool during Blender's transient modal selection."""
    if target is None:
        return ""

    def live_curve(controller):
        try:
            from . import curve as curve_module
            sessions = tuple(curve_module._CURVE_MODAL_OPERATORS)
        except (AttributeError, ImportError, ReferenceError, RuntimeError,
                TypeError):
            sessions = ()
        for operator in sessions:
            try:
                if (
                        not bool(getattr(operator, "_finished", False)) and
                        operator._controller() == controller
                ):
                    return True
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                continue
        return False

    for modifier in cage_modifiers(target):
        controller = find_controller(target, modifier)
        properties = getattr(controller, "sdh_cage_deform", None)
        cage_type = str(getattr(properties, "cage_type", "")).upper()
        if (
                cage_type == "FFD" and
                bool(getattr(properties, "ffd_edit_mode_active", False)) and
                _ffd_edit_session_live(controller)
        ):
            return "FFD"
        if (
                cage_type == "CURVE" and
                bool(getattr(properties, "curve_object_edit_active", False)) and
                live_curve(controller)
        ):
            return "CURVE"
    return ""


def _workspace_target_from_active(active):
    """Resolve a possible target without requiring Blender's selected flag."""
    if active is None:
        return None
    lattice_target, _lattice_modifier, _lattice_controller = (
        _ffd_lattice_context_from_object(active))
    if lattice_target is not None:
        return lattice_target
    if is_cage_controller(active):
        return _controller_owner_target(active)
    try:
        from .curve import target_from_helper
        helper_target = target_from_helper(active)
        if helper_target is not None:
            return helper_target
    except (ImportError, ReferenceError, RuntimeError, TypeError):
        pass
    return active if getattr(active, "type", None) in SUPPORTED_TYPES else None


def _desired_cage_workspace_type(context):
    """Derive the viewport tool solely from the current selected cage state."""
    if str(getattr(context, "mode", "OBJECT")) != "OBJECT":
        return None
    selected_objects = tuple(getattr(context, "selected_objects", ()) or ())
    # Empty selection belongs to Blender's native Select Box.  Do not let a
    # stale persistent-editor flag resurrect a cage tool in this state.
    if not selected_objects:
        return ""
    active = getattr(getattr(context, "view_layer", None), "objects", None)
    active = getattr(active, "active", None)
    target = _workspace_target_from_active(active)
    if (
            active is not None and active in selected_objects and
            target is not None and target in selected_objects
    ):
        _target, _modifier, controller = resolve_context_deform(context)
        properties = getattr(controller, "sdh_cage_deform", None)
        cage_type = str(getattr(properties, "cage_type", "")).upper()
        return cage_type if cage_type in {"FFD", "CURVE"} else ""
    return _live_workspace_cage_type(target)


def _reconcile_cage_workspace_tool(context, desired=None, *, force=False):
    """Idempotently align the Workspace Tool without fighting user tools."""
    if desired is None:
        desired = _desired_cage_workspace_type(context)
    if desired is None:
        return True
    expected = {
        "FFD": _FFD_WORKSPACE_TOOL_ID,
        "CURVE": _CURVE_WORKSPACE_TOOL_ID,
    }.get(desired, "")
    workspace_key = _workspace_tool_key(context)
    current = _active_workspace_tool_id(context)
    override = _WORKSPACE_TOOL_OVERRIDES.get(workspace_key)
    if not expected:
        _WORKSPACE_TOOL_OVERRIDES.pop(workspace_key, None)
    elif not force and override is not None:
        override_signature, override_tool = override
        if (
                override_signature == _selection_signature(context) and
                current == override_tool
        ):
            return True
        _WORKSPACE_TOOL_OVERRIDES.pop(workspace_key, None)
    if expected:
        if current == expected:
            _WORKSPACE_TOOL_OVERRIDES.pop(workspace_key, None)
            return True
        if not force and current not in {
                _FFD_WORKSPACE_TOOL_ID, _CURVE_WORKSPACE_TOOL_ID
        }:
            # A native tool change is an explicit user choice. Preserve it
            # until the target or active cage selection actually changes.
            _WORKSPACE_TOOL_OVERRIDES[workspace_key] = (
                _selection_signature(context), current)
            return True
    elif current not in {_FFD_WORKSPACE_TOOL_ID, _CURVE_WORKSPACE_TOOL_ID}:
        return True
    if not activate_cage_workspace_tool(context, desired):
        return False
    current = _active_workspace_tool_id(context)
    return (
        current == expected if expected else
        current not in {_FFD_WORKSPACE_TOOL_ID, _CURVE_WORKSPACE_TOOL_ID}
    )


def _sync_workspace_tool_selection_state(context):
    """Apply selection transitions, then confirm briefly without locking tools."""
    global _SELECTION_SYNC_SIGNATURE, _SELECTION_SYNC_DIRTY
    signature = _selection_signature(context)
    workspace_key = _workspace_tool_key(context)
    signature_changed = signature != _SELECTION_SYNC_SIGNATURE
    changed = (
        bool(_SELECTION_SYNC_DIRTY) or
        signature_changed)
    if changed:
        desired = _desired_cage_workspace_type(context)
        # A real selection/stage change is the explicit hand-off point where
        # the add-on may reclaim its dedicated editor after a native tool was
        # chosen by the user.
        if signature_changed:
            _WORKSPACE_TOOL_OVERRIDES.pop(workspace_key, None)
        if not _reconcile_cage_workspace_tool(
                context, desired, force=signature_changed):
            return False, True
        _SELECTION_SYNC_SIGNATURE = signature
        _SELECTION_SYNC_DIRTY = False
        _WORKSPACE_TOOL_CONFIRMATIONS[workspace_key] = (
            signature, desired, _WORKSPACE_TOOL_CONFIRM_PASSES)
        return True, True
    pending = _WORKSPACE_TOOL_CONFIRMATIONS.get(workspace_key)
    if pending is None or pending[0] != signature:
        _WORKSPACE_TOOL_CONFIRMATIONS.pop(workspace_key, None)
        return True, False
    _pending_signature, desired, passes_left = pending
    if not _reconcile_cage_workspace_tool(context, desired):
        return False, False
    if passes_left <= 1:
        _WORKSPACE_TOOL_CONFIRMATIONS.pop(workspace_key, None)
    else:
        _WORKSPACE_TOOL_CONFIRMATIONS[workspace_key] = (
            signature, desired, passes_left - 1)
    return True, False


CONTROLLER_STYLES = {
    "BEND": ("SINGLE_ARROW", (0.05, 0.72, 1.0, 0.85)),
    "TWIST": ("CIRCLE", (0.72, 0.22, 1.0, 0.85)),
    "TAPER": ("CONE", (1.0, 0.62, 0.05, 0.85)),
    "STRETCH": ("ARROWS", (0.15, 0.9, 0.42, 0.85)),
    "SHEAR": ("SINGLE_ARROW", (0.1, 0.82, 0.82, 0.85)),
    "FFD": ("CUBE", (1.0, 0.28, 0.52, 0.85)),
    "CURVE": ("CIRCLE", (0.12, 0.78, 1.0, 0.9)),
}

STANDARD_DEFORM_ORDER = ("BEND", "TWIST", "TAPER", "STRETCH", "SHEAR")
DEFORM_VALUES = {name: index for index, name in enumerate(DEFORM_ORDER)}
CAGE_TYPES = ("STANDARD", "SHEAR", "FFD", "CURVE")
CAGE_TYPE_DEFORM = {"SHEAR": "SHEAR", "FFD": "FFD", "CURVE": "CURVE"}
_CAGE_TYPE_GUARD = set()
NODE_FRAME_NAMES = (
    NODE_FRAME_LOCAL,
    NODE_FRAME_PROFILE,
    *(DEFORM_BLOCK_FRAME_NODE[name] for name in DEFORM_ORDER),
    NODE_FRAME_MODE_OUTPUT,
)
CONTROLLER_INACTIVE_FACTOR = 0.42
CONTROLLER_INACTIVE_ALPHA = 0.34
CURVE_CONTROL_LENGTH_MODE = {"CURVE": "STRETCH", "CAGE": "PRESERVE"}
CURVE_BOUNDARY_VALUES = {"EXTEND": 0, "CLAMP": 1, "CAGE_ONLY": 2}
CURVE_MODE_BOUNDARY = {
    "UNLIMITED": "EXTEND",
    "LIMITED": "CLAMP",
    "WITHIN_BOX": "CAGE_ONLY",
}
CURVE_BOUNDARY_MODE = {
    value: key for key, value in CURVE_MODE_BOUNDARY.items()
}
# Dedicated FFD cages use Blender's native Lattice data. Keeping every axis
# bounded to six points keeps viewport interaction predictable.
FFD_MIN_RESOLUTION = 2
FFD_MAX_RESOLUTION_U = 6
FFD_MAX_RESOLUTION_V = 6
FFD_MAX_RESOLUTION_W = 6
FFD_DEFAULT_RESOLUTION = (2, 2, 2)
FFD_MAX_POINT_COUNT = (
    FFD_MAX_RESOLUTION_U * FFD_MAX_RESOLUTION_V * FFD_MAX_RESOLUTION_W)
FFD_SELECTION_MODE_ORDER = ("POINT", "LINE", "FACE")
FFD_SYMMETRY_AXIS_ORDER = ("U", "V", "W")
FFD_INTERPOLATION_ORDER = (
    "KEY_LINEAR", "KEY_CARDINAL", "KEY_CATMULL_ROM", "KEY_BSPLINE")
FFD_MAX_LINE_ENTITY_COUNT = (
    (FFD_MAX_RESOLUTION_U - 1) * FFD_MAX_RESOLUTION_V *
    FFD_MAX_RESOLUTION_W +
    FFD_MAX_RESOLUTION_U * (FFD_MAX_RESOLUTION_V - 1) *
    FFD_MAX_RESOLUTION_W +
    FFD_MAX_RESOLUTION_U * FFD_MAX_RESOLUTION_V *
    (FFD_MAX_RESOLUTION_W - 1))
FFD_MAX_FACE_ENTITY_COUNT = (
    FFD_MAX_RESOLUTION_W * (FFD_MAX_RESOLUTION_U - 1) *
    (FFD_MAX_RESOLUTION_V - 1) +
    FFD_MAX_RESOLUTION_V * (FFD_MAX_RESOLUTION_U - 1) *
    (FFD_MAX_RESOLUTION_W - 1) +
    FFD_MAX_RESOLUTION_U * (FFD_MAX_RESOLUTION_V - 1) *
    (FFD_MAX_RESOLUTION_W - 1))
FFD_MAX_SELECTION_HANDLE_COUNT = (
    FFD_MAX_POINT_COUNT + FFD_MAX_LINE_ENTITY_COUNT +
    FFD_MAX_FACE_ENTITY_COUNT)
FFD_LATTICE_MARKER = "_sdh_ffd_lattice"
FFD_LATTICE_MODIFIER_MARKER = "_sdh_ffd_lattice_modifier"
FFD_LATTICE_TOPOLOGY_TOKEN = "_sdh_ffd_lattice_topology_token"
FFD_NATIVE_EDIT_PROXY_MARKER = "_sdh_ffd_native_edit_proxy"
FFD_AXES_LINKED_KEY = "_sdh_ffd_axes_linked"
FFD_VERTEX_GROUP_PREFIX = "_SDH_FFD_SCOPE_"
FFD_RESOLUTION_PROP = "_sdh_ffd_resolution"
CAGE_TYPE_MARKER = "_sdh_cage_type"
SUPPORTED_TYPES = {"MESH", "CURVE", "FONT", "SURFACE"}
NATIVE_EMPTY_DISPLAY_SIZE = float(
    bpy.types.Object.bl_rna.properties["empty_display_size"].hard_min)


def _data_objects_snapshot():
    """Return scene objects only when Blender's unrestricted data API is live.

    Extension registration temporarily replaces ``bpy.data`` with
    ``_RestrictData``. Blender can evaluate persistent Gizmo and panel polls
    before registration has returned, especially while updating an enabled
    extension in a file that already contains cages. Treat that interval as
    an empty scene and let the next redraw resolve the saved cages normally.
    """
    try:
        return tuple(bpy.data.objects)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return ()


def _data_objects_available():
    """Check whether Blender's data API is usable without copying objects.

    Gizmo and panel polls call :func:`resolve_context_deform` very frequently.
    The old restricted-data guard materialized ``tuple(bpy.data.objects)`` on
    every poll, which is needlessly expensive in large scenes.  Accessing the
    collection itself is enough to detect Blender's registration-time
    ``_RestrictData`` proxy; callers that need objects still use the snapshot
    helper above.
    """
    try:
        return getattr(bpy.data, "objects", None) is not None
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return False

_SYNCING = set()
_FFD_AXES_LINK_SYNCING = set()
# Curve presets can update several helper datablocks from one RNA callback.
# Keep their re-entry guard separate from controller/modifier synchronization
# so the final modifier push is not suppressed.
_CURVE_PRESET_UPDATE_GUARD = set()
# Property mirroring and frame propagation use separate guards.  The former
# prevents a chain-wide preference change from recursively invoking its own
# update callback; the latter prevents downstream transforms written during a
# reconnect from immediately queuing the same chain again.
_CHAIN_AUTO_GUARD = set()
# Shared-seam option mirroring and paired TOP/BOTTOM assignments use one
# dedicated guard so neither controller recursively edits the other.
_CHAIN_SHARED_SCALE_GUARD = set()
_CHAIN_GLOBAL_STRETCH_GUARD = set()
_CHAIN_RECONNECTING = set()
_CHAIN_RECONNECT_QUEUE = {}
_CHAIN_AFFINE_FRAME_CACHE = {}
# A wire rebuild samples dozens of points from the same chained stage. Cache
# the immutable chain traversal plan so those points share controller lookup,
# matrices, domains, relative end scales, and conjugation frames.
_CHAIN_DISPLAY_STATE_CACHE = {}
_CHAIN_DISPLAY_STATE_CACHE_LIMIT = 64
# Hidden chain-domain inputs are read by every stage synchronisation and by
# the affine-frame solver.  Their values only change when chain metadata,
# gaps, global chain options, or a controller's authored size changes.  Keep
# one short-lived cache for those reads instead of rescanning all owners and
# all preceding stages for every boundary sample.
_CHAIN_DOMAIN_INPUT_CACHE = {}
_CHAIN_DOMAIN_INPUT_CACHE_VERSION = 0
_CONTROLLER_SIZE_SNAPSHOTS = {}
_CONTROLLER_TRANSFORM_QUEUE = {}
_CONTROLLER_TRANSFORM_SNAPSHOTS = {}
# FFD scope membership is expensive to derive from a dense target mesh but is
# independent of control-point offsets and weights. Cache source coordinates
# once per mesh and the resulting membership signature once per stage so the
# common point-edit path never walks or rewrites the target's vertex groups.
_FFD_SCOPE_MESH_CACHE = {}
_FFD_SCOPE_STAGE_CACHE = {}
_FFD_SCOPE_MESH_DIRTY = set()
_FFD_SCOPE_REFRESH_QUEUE = {}
# Vertex-group writes tag their owning Mesh as geometry-updated. Suppress that
# delayed dependency-graph echo so an authoritative scope rebuild does not
# immediately invalidate itself and schedule another pass.
_FFD_SCOPE_MESH_WRITE_GUARD = set()
_FFD_GUARD_VALID_OFFSETS = {}
# Lattice targets cannot parent a managed Origin without forming a dependency
# cycle. Queue their world-space Origin refreshes after the depsgraph returns.
_LATTICE_ORIGIN_QUEUE = {}
_LATTICE_ORIGIN_SIGNATURES = {}
# Ordinary stack cages can opt into refitting their frame to the evaluated
# output entering the stage.  The queue is keyed by target and stores the
# earliest modifier index that needs propagation.
_STACK_AUTO_FIT_QUEUE = {}
_STACK_AUTO_FIT_RUNNING = set()
_STACK_AUTO_FIT_SIGNATURES = {}
# Targets written by an evaluated fit can emit one delayed geometry update
# after the fit returns. Suppress only that dependency-graph echo until the
# next event-loop timer pass; direct property requests remain unaffected.
_STACK_AUTO_FIT_DEPSGRAPH_GUARD = set()
# A connected chain owns its one-sided mode. Origin remains user-authored and
# is intentionally not normalized here: Bottom, Top, Center and Symmetric all
# have meaningful chained evaluations.
_CHAIN_MODE_GUARD = set()
_CHAIN_GAP_GUARD = set()
_CHAIN_BATCH_PANEL_GUARD = set()
_FFD_POINT_GUARD = set()
_LEGACY_MIGRATION_PENDING = True
_CONTROLLER_DISPLAY_SIGNATURE = None
_CONTROLLER_DISPLAY_GUARD = set()
_TARGET_SELECTION_SYNC_GUARD = set()
_TARGET_OWNERSHIP_REPAIR_QUEUE = {}
_TARGET_OWNERSHIP_REPAIRING = set()
_SELECTION_SYNC_MSG_OWNER = object()
_SELECTION_SYNC_SIGNATURE = None
_SELECTION_SYNC_DIRTY = False
_WORKSPACE_TOOL_CONFIRMATIONS = {}
# Preserve an intentional native-tool choice while the selected cage remains
# unchanged. The selection signature invalidates this entry automatically.
_WORKSPACE_TOOL_OVERRIDES = {}
_WORKSPACE_TOOL_CONFIRM_PASSES = 2
# A stage picker can be followed by Blender's late object-pick pass.  Keep the
# intended target for two event-loop passes so that pass cannot leave the
# target active-but-unselected (the N-panel treats that as no target).
_PENDING_STAGE_SELECTION_RESTORE = None
_SELECTION_WATCH_INTERVAL = 0.12
_ORPHAN_HELPER_OBJECT_COUNT = -1
_ORPHAN_HELPER_CLEANUP_RUNNING = False
_RELATIONSHIP_OVERLAY_STATES = {}
_RUNTIME_HANDLERS_REGISTERED = False

_CONTROLLER_ACTIVE_INTERVAL = 0.04
_CONTROLLER_IDLE_INTERVAL = 0.5


class _TraditionalGizmoContext(GizmoUtils):
    """GizmoUtils view bound to a target/modifier outside the active context."""

    def __init__(self, target, modifier):
        self._traditional_target = target
        self._traditional_modifier = modifier

    @property
    def obj(self):
        return self._traditional_target

    @property
    def modifier(self):
        return self._traditional_modifier

CHAIN_UUID_PROP = "_sdh_cage_chain_uuid"
CHAIN_INDEX_PROP = "_sdh_cage_chain_index"
CHAIN_COUNT_PROP = "_sdh_cage_chain_count"
CHAIN_MODE_PROP = "_sdh_cage_chain_mode"
CHAIN_ROOT_OUTPUT_AFFINE_PROP = "_sdh_cage_chain_root_output_affine"
CHAIN_DOMAIN_ATTRIBUTE_PREFIX = ".sdh_chain_domain_"


def invalidate_chain_affine_cache(target=None):
    """Invalidate cached physical chain frames after an authored change."""
    if target is None:
        _CHAIN_AFFINE_FRAME_CACHE.clear()
        return
    pointer = _pointer(target)
    for key in tuple(_CHAIN_AFFINE_FRAME_CACHE):
        if key[0] == pointer:
            _CHAIN_AFFINE_FRAME_CACHE.pop(key, None)


def invalidate_chain_domain_cache():
    """Invalidate cached chain ownership/domain values.

    This is intentionally a separate cache from the physical affine cache:
    changing a gap or chain metadata does not necessarily change a sampled
    frame, while a size change can invalidate both.  The chain module calls
    this helper after writing any mirrored ownership metadata.
    """
    global _CHAIN_DOMAIN_INPUT_CACHE_VERSION
    _CHAIN_DOMAIN_INPUT_CACHE_VERSION += 1
    _CHAIN_DOMAIN_INPUT_CACHE.clear()
    projected_entity_cache.clear()


def deform_type_mask(deform_types, fallback="BEND") -> int:
    """Return the stable operation bit mask used by Geometry Nodes."""
    if isinstance(deform_types, str):
        deform_types = {deform_types}
    try:
        enabled = set(deform_types)
    except (TypeError, ValueError):
        enabled = {fallback} if fallback in DEFORM_BITS else set()
    return sum(DEFORM_BITS[name] for name in DEFORM_ORDER if name in enabled)


def apply_chain_global_stretch(
        point, source_coordinate, *, factor=0.0, center=(0.0, 0.0, 0.0),
        rotation=(0.0, 0.0, 0.0), source_offset=0.0, length=2.0,
        origin="BOTTOM", preserve_volume=True):
    """Apply the analytic root-frame Stretch used by chained GN stages.

    Mixed Bend stacks cannot split a post-Bend axial stretch into independent
    local cages without changing the result.  This helper is the scalar/vector
    reference for the one global pass performed by the chain tip, and is also
    useful to diagnostics and non-GN preview code.
    """
    point = Vector(point)
    center = Vector(center)
    try:
        factor = float(factor)
    except (TypeError, ValueError):
        factor = 0.0
    try:
        source_y = float(source_coordinate) + float(source_offset)
    except (TypeError, ValueError):
        source_y = float(source_offset)
    try:
        half = max(abs(float(length)) * 0.5, EPSILON)
    except (TypeError, ValueError):
        half = EPSILON
    origin_key = origin
    if isinstance(origin_key, str):
        origin_key = ORIGIN_VALUES.get(origin_key.upper(), ORIGIN_VALUES["BOTTOM"])
    try:
        origin_key = int(origin_key)
    except (TypeError, ValueError):
        origin_key = ORIGIN_VALUES["BOTTOM"]
    if origin_key == ORIGIN_VALUES["TOP"]:
        origin_y = half
    elif origin_key == ORIGIN_VALUES["CENTER"]:
        origin_y = 0.0
    elif origin_key == ORIGIN_VALUES["SYMMETRIC"]:
        origin_y = 0.0
    else:
        origin_y = -half
    distance = min(max(source_y - origin_y, -half - origin_y), half - origin_y)
    scale = 1.0 + factor
    safe_scale = max(abs(scale), EPSILON)
    volume = safe_scale ** -0.5 if preserve_volume else 1.0
    try:
        rotation_matrix = Euler(tuple(float(value) for value in rotation), "XYZ").to_matrix()
    except (TypeError, ValueError):
        rotation_matrix = Euler((0.0, 0.0, 0.0), "XYZ").to_matrix()
    local = rotation_matrix.inverted() @ (point - center)
    local.x *= volume
    local.z *= volume
    local.y += distance * factor
    return rotation_matrix @ local + center


def apply_chain_global_prefix(
        point, source_coordinate, *, deform_mask=0, bend=0.0,
        direction=0.0, twist=0.0, taper=0.0, stretch=0.0,
        shear=(0.0, 0.0, 0.0), pre_shear_mask=0, post_shear_mask=0,
        center=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0),
        source_offset=0.0, length=2.0, origin="BOTTOM",
        profile_active=False, bottom_scale=(1.0, 1.0, 1.0),
        top_scale=(1.0, 1.0, 1.0), bottom_offset=(0.0, 0.0, 0.0),
        top_offset=(0.0, 0.0, 0.0),
        preserve_volume=True):
    """Evaluate the original pre-Bend profile once in the full-cage frame."""
    point = Vector(point)
    center = Vector(center)
    try:
        source_y = float(source_coordinate) + float(source_offset)
    except (TypeError, ValueError):
        source_y = float(source_offset)
    try:
        half = max(abs(float(length)) * 0.5, EPSILON)
    except (TypeError, ValueError):
        half = EPSILON
    origin_key = origin
    if isinstance(origin_key, str):
        origin_key = ORIGIN_VALUES.get(
            origin_key.upper(), ORIGIN_VALUES["BOTTOM"])
    try:
        origin_key = int(origin_key)
    except (TypeError, ValueError):
        origin_key = ORIGIN_VALUES["BOTTOM"]
    if origin_key == ORIGIN_VALUES["TOP"]:
        origin_y = half
    elif origin_key in {
            ORIGIN_VALUES["CENTER"], ORIGIN_VALUES["SYMMETRIC"]}:
        origin_y = 0.0
    else:
        origin_y = -half
    raw_distance = source_y - origin_y
    distance = min(
        max(raw_distance, -half - origin_y),
        half - origin_y,
    )
    outside_distance = raw_distance - distance
    profile_distance = (
        abs(distance)
        if origin_key == ORIGIN_VALUES["SYMMETRIC"] else distance)
    profile = profile_distance / max(half * 2.0, EPSILON)
    try:
        mask = int(deform_mask)
    except (TypeError, ValueError):
        mask = 0
    try:
        rotation_matrix = Euler(
            tuple(float(value) for value in rotation), "XYZ").to_matrix()
    except (TypeError, ValueError):
        rotation_matrix = Euler((0.0, 0.0, 0.0), "XYZ").to_matrix()
    local = rotation_matrix.inverted() @ (point - center)
    if profile_active:
        profile_t = min(max((source_y + half) / max(half * 2.0, EPSILON), 0.0), 1.0)
        lower_scale = Vector(bottom_scale)
        upper_scale = Vector(top_scale)
        lower_offset = Vector(bottom_offset)
        upper_offset = Vector(top_offset)
        section_scale = lower_scale.lerp(upper_scale, profile_t)
        section_offset = lower_offset.lerp(upper_offset, profile_t)
        local.x = local.x * section_scale.x + section_offset.x
        local.z = local.z * section_scale.z + section_offset.z
    linear_mask = (
        DEFORM_BITS["TWIST"] | DEFORM_BITS["TAPER"] |
        DEFORM_BITS["STRETCH"])
    try:
        pre_mask = int(pre_shear_mask)
        post_mask = int(post_shear_mask)
    except (TypeError, ValueError):
        pre_mask = post_mask = 0
    if not (pre_mask or post_mask or mask & DEFORM_BITS["SHEAR"]):
        pre_mask = mask & linear_mask

    def apply_linear_stack(value, stack_mask):
        value = Vector(value)
        if stack_mask & DEFORM_BITS["TWIST"]:
            angle = float(twist) * profile
            cosine = math.cos(angle)
            sine = math.sin(angle)
            value.x, value.z = (
                cosine * value.x - sine * value.z,
                sine * value.x + cosine * value.z,
            )
        if stack_mask & DEFORM_BITS["TAPER"]:
            scale = 1.0 + float(taper) * profile
            value.x *= scale
            value.z *= scale
        if stack_mask & DEFORM_BITS["STRETCH"]:
            scale = 1.0 + float(stretch)
            volume = (
                max(abs(scale), EPSILON) ** -0.5
                if preserve_volume else 1.0)
            value.x *= volume
            value.y += distance * float(stretch)
            value.z *= volume
        return value

    local = apply_linear_stack(local, pre_mask)
    if mask & DEFORM_BITS["SHEAR"]:
        shear_values = tuple(float(value) for value in shear)
        local.x += (shear_values[0] if shear_values else 0.0) * profile_distance
        local.z += (
            shear_values[2] if len(shear_values) > 2 else
            shear_values[1] if len(shear_values) > 1 else 0.0
        ) * profile_distance
    local = apply_linear_stack(local, post_mask)
    if mask & DEFORM_BITS["BEND"] and abs(float(bend)) >= EPSILON:
        bend_direction = float(direction)
        cos_direction = math.cos(bend_direction)
        sin_direction = math.sin(bend_direction)
        u = cos_direction * local.x + sin_direction * local.z
        v = -sin_direction * local.x + cos_direction * local.z
        curvature = float(bend) / max(half * 2.0, EPSILON)
        if (
                origin_key == ORIGIN_VALUES["SYMMETRIC"] and
                source_y < 0.0
        ):
            curvature = -curvature
        radius = 1.0 / curvature
        theta = curvature * distance
        cosine = math.cos(theta)
        sine = math.sin(theta)
        radial = radius + u
        deformed_u = (
            radial * cosine - radius - sine * outside_distance)
        authored_y = (
            origin_y + radial * sine + cosine * outside_distance)
        local = Vector((
            cos_direction * deformed_u - sin_direction * v,
            local.y + authored_y - source_y,
            sin_direction * deformed_u + cos_direction * v,
        ))
    return rotation_matrix @ local + center


def apply_chain_global_suffix(
        point, source_coordinate, *, deform_mask=0, twist=0.0, taper=0.0,
        stretch=0.0, shear=(0.0, 0.0, 0.0), pre_shear_mask=0,
        post_shear_mask=0, center=(0.0, 0.0, 0.0),
        rotation=(0.0, 0.0, 0.0), source_offset=0.0, length=2.0,
        origin="BOTTOM", preserve_volume=True):
    """Evaluate the source-frame operations authored after the chain pivot."""
    return apply_chain_global_prefix(
        point,
        source_coordinate,
        deform_mask=deform_mask,
        twist=twist,
        taper=taper,
        stretch=stretch,
        shear=shear,
        pre_shear_mask=pre_shear_mask,
        post_shear_mask=post_shear_mask,
        center=center,
        rotation=rotation,
        source_offset=source_offset,
        length=length,
        origin=origin,
        preserve_volume=preserve_volume,
    )


def deform_types_from_mask(mask, fallback=None):
    """Decode a node input mask into an EnumProperty-compatible set."""
    try:
        mask = int(mask) & DEFORM_MASK_ALL
    except (TypeError, ValueError):
        mask = 0
    enabled = {name for name in DEFORM_ORDER if mask & DEFORM_BITS[name]}
    if not enabled and fallback in DEFORM_BITS:
        enabled.add(fallback)
    return enabled


def encode_deform_order(values, enabled=None, fallback="BEND"):
    """Encode an active order as the fixed persistent integer vector."""
    ordered = normalize_deform_order(values, enabled, fallback)
    slot_count = len(DEFORM_ORDER)
    encoded = [DEFORM_VALUES[name] for name in ordered[:slot_count]]
    return tuple(encoded + [-1] * (slot_count - len(encoded)))


def ordered_deform_types(properties, deform_types=None, fallback="BEND"):
    """Return every present deformation layer in its authored order."""
    if hasattr(properties, "deform_order"):
        return normalize_deform_order(properties, deform_types, fallback)
    return normalize_deform_order(properties, deform_types, fallback)


def active_deform_types(properties):
    """Return present deformation layers that are not temporarily muted."""
    legacy_type = getattr(properties, "deform_type", "BEND")
    try:
        present = set(properties.deform_types)
    except (AttributeError, TypeError, ValueError):
        present = {legacy_type} if legacy_type in DEFORM_BITS else {"BEND"}
    try:
        muted = set(properties.muted_deform_types)
    except (AttributeError, TypeError, ValueError):
        muted = set()
    return {
        name for name in DEFORM_ORDER
        if name in present and name not in muted
    }


def deform_order_from_signature(signature, enabled=None, fallback="BEND"):
    values = str(signature or "").split(",")
    return normalize_deform_order(values, enabled, fallback)


def _same_rna_value(first, second):
    """Compare Blender RNA values across dependency-graph wrapper refreshes."""
    if first is second:
        return True
    first_pointer = _pointer(first)
    return bool(first_pointer and first_pointer == _pointer(second))


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


def _set_controller_style(controller, deform_type=None, *, active=None):
    if controller is None:
        return
    if deform_type is None:
        properties = controller.sdh_cage_deform
        try:
            deform_type = ordered_deform_types(properties)[0]
        except (AttributeError, IndexError, TypeError, ValueError):
            deform_type = getattr(properties, "deform_type", "BEND")
    display_type, color = CONTROLLER_STYLES.get(
        deform_type, CONTROLLER_STYLES["BEND"])
    if active is None:
        # Controllers created before the display-state feature have no marker;
        # keep their original bright appearance until the next organization
        # pass determines the actual active stage.
        active = bool(controller.get(CONTROLLER_ACTIVE_DISPLAY, True))
    if not active:
        color = tuple(
            value * CONTROLLER_INACTIVE_FACTOR for value in color[:3]
        ) + (CONTROLLER_INACTIVE_ALPHA,)
    if controller.empty_display_type != display_type:
        controller.empty_display_type = display_type
    # The Empty remains as the persistent transform owner, while the custom
    # Gizmos provide the visible controller. Keep Blender's native Empty
    # marker hidden so it does not duplicate or obscure those handles.
    if abs(controller.empty_display_size - NATIVE_EMPTY_DISPLAY_SIZE) > EPSILON:
        controller.empty_display_size = NATIVE_EMPTY_DISPLAY_SIZE
    if any(abs(controller.color[index] - color[index]) > EPSILON for index in range(4)):
        controller.color = color


def _controller_owner_target(controller):
    """Resolve a controller's target without changing selection state."""
    try:
        return find_target(controller)
    except (ReferenceError, RuntimeError):
        return None


def _selected_context_object(context):
    """Return the active object only while it is actually selected."""
    obj = getattr(context, "object", None)
    if obj is None:
        return None
    selected_objects = getattr(context, "selected_objects", None)
    if selected_objects is None:
        return obj
    try:
        return obj if obj in tuple(selected_objects) else None
    except (ReferenceError, RuntimeError, TypeError):
        return None


def _target_cage_controllers(target):
    """Resolve every controller belonging to one target's cage stack."""
    if target is None:
        return ()
    controllers = []
    for modifier in cage_modifiers(target):
        controller = find_controller(target, modifier)
        if controller is not None and controller not in controllers:
            controllers.append(controller)
    return tuple(controllers)


def _sync_target_cage_selection(context, target):
    """Select cage controllers alongside an actively selected target.

    Cage animation channels live on controller objects rather than on the
    deformed target. Selecting all related controllers keeps standard,
    shear, FFD, and every stage of a chain visible in the Timeline while the
    target remains the active object for object-level and panel operations.
    """
    if target is None:
        return ()
    selected = getattr(context, "selected_objects", None)
    if selected is None or target not in tuple(selected):
        return ()
    if _selected_context_object(context) is not target:
        return ()
    pointer = _pointer(target)
    if pointer and pointer in _TARGET_SELECTION_SYNC_GUARD:
        return ()
    controllers = _target_cage_controllers(target)
    if not controllers:
        return ()
    if pointer:
        _TARGET_SELECTION_SYNC_GUARD.add(pointer)
    try:
        view_layer = getattr(context, "view_layer", None)
        for controller in controllers:
            set_helper_object_visible(controller, True, view_layer)
            controller.select_set(True)
        active_modifier = getattr(
            getattr(target, "modifiers", None), "active", None)
        if is_cage_modifier(active_modifier):
            active_controller = find_controller(target, active_modifier)
            active_properties = getattr(
                active_controller, "sdh_cage_deform", None)
            if (
                    active_properties is not None and
                    str(active_properties.cage_type) == "CURVE"
            ):
                try:
                    from .curve import ensure_curve_companions
                    guide, _stations = ensure_curve_companions(
                        target, active_modifier, active_controller)
                    set_helper_object_visible(guide, True, view_layer)
                    guide.hide_select = False
                    guide.select_set(True)
                except (AttributeError, ImportError, ReferenceError,
                        RuntimeError, TypeError, ValueError):
                    pass
        # Keep the target as the active object. The selected controllers are
        # still included by Blender's Timeline/Dope Sheet filters.
        context.view_layer.objects.active = target
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    finally:
        if pointer:
            _TARGET_SELECTION_SYNC_GUARD.discard(pointer)
    return controllers


def _sync_controller_relationship_lines(context, hide):
    """Temporarily hide viewport relationship lines while cage controls are active.

    Blender exposes this as a View3D overlay setting rather than an object
    property, so the setting is scoped to each open 3D view and restored as
    soon as no cage target is selected.  This avoids changing the user's
    preference permanently while removing the parent-child dotted lines that
    otherwise compete with the cage handles.
    """
    screen = getattr(context, "screen", None)
    areas = tuple(getattr(screen, "areas", ())) if screen is not None else ()
    active_overlays = set()
    for area in areas:
        if getattr(area, "type", None) != "VIEW_3D":
            continue
        spaces = getattr(area, "spaces", None)
        space = getattr(spaces, "active", None) if spaces is not None else None
        overlay = getattr(space, "overlay", None)
        if overlay is None or not hasattr(overlay, "show_relationship_lines"):
            continue
        key = _pointer(overlay)
        if not key:
            continue
        active_overlays.add(key)
        try:
            if hide:
                if key not in _RELATIONSHIP_OVERLAY_STATES:
                    _RELATIONSHIP_OVERLAY_STATES[key] = (
                        overlay, bool(overlay.show_relationship_lines))
                overlay.show_relationship_lines = False
            elif key in _RELATIONSHIP_OVERLAY_STATES:
                _overlay, previous = _RELATIONSHIP_OVERLAY_STATES.pop(key)
                _overlay.show_relationship_lines = previous
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            _RELATIONSHIP_OVERLAY_STATES.pop(key, None)

    if hide:
        return
    # Restore views that are no longer present in the current screen when
    # possible; stale RNA pointers are discarded defensively.
    for key, (overlay, previous) in tuple(_RELATIONSHIP_OVERLAY_STATES.items()):
        if key in active_overlays:
            continue
        try:
            overlay.show_relationship_lines = previous
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
        _RELATIONSHIP_OVERLAY_STATES.pop(key, None)


def restore_controller_relationship_lines():
    """Restore overlays captured by the temporary relationship-line policy."""
    for key, (overlay, previous) in tuple(_RELATIONSHIP_OVERLAY_STATES.items()):
        try:
            overlay.show_relationship_lines = previous
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
        _RELATIONSHIP_OVERLAY_STATES.pop(key, None)


def _active_controller_for_target(target, context=None):
    """Return the controller represented by the current selection/stage."""
    if target is None:
        return None
    context = context or bpy.context
    selected = _selected_context_object(context)
    if is_cage_controller(selected) and _controller_owner_target(selected) == target:
        return selected
    active_modifier = getattr(getattr(target, "modifiers", None), "active", None)
    if not is_cage_modifier(active_modifier):
        stages = cage_modifiers(target)
        active_modifier = stages[0] if stages else None
    return find_controller(target, active_modifier) if active_modifier else None


def _target_show_other_cages(target, fallback=True):
    """Return the target-wide inactive-cage visibility preference."""
    if target is None:
        return bool(fallback)
    try:
        value = target.get(TARGET_SHOW_OTHER_CAGES, None)
    except (AttributeError, ReferenceError, TypeError):
        value = None
    return bool(fallback) if value is None else bool(value)


def _target_has_show_other_cages(target):
    if target is None:
        return False
    try:
        return target.get(TARGET_SHOW_OTHER_CAGES, None) is not None
    except (AttributeError, ReferenceError, TypeError):
        return False


def _sync_target_show_other_cages(target, enabled):
    """Persist and mirror one visibility value across every target stage."""
    if target is None:
        return
    enabled = bool(enabled)
    try:
        target[TARGET_SHOW_OTHER_CAGES] = enabled
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    for modifier in cage_modifiers(target):
        controller = find_controller(target, modifier)
        properties = getattr(controller, "sdh_cage_deform", None)
        if properties is None or not hasattr(properties, "show_other_cages"):
            continue
        pointer = 0
        try:
            if bool(properties.show_other_cages) == enabled:
                continue
            pointer = _pointer(controller)
            if pointer:
                _CONTROLLER_DISPLAY_GUARD.add(pointer)
            properties.show_other_cages = enabled
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
        finally:
            if pointer:
                _CONTROLLER_DISPLAY_GUARD.discard(pointer)


def refresh_controller_display(context=None, *, hide_controllers=False, force=False):
    """Refresh visibility and active/inactive colors for owned controllers.

    The active controller keeps its type-specific bright color.  Other stages
    of the active target remain selectable when ``show_other_cages`` is on and
    use a dimmed version of the same type color.  Controllers owned by other
    targets are always hidden to avoid scene-wide Empty clutter.
    """
    context = context or bpy.context
    scene = getattr(context, "scene", None)
    selected = _selected_context_object(context)
    target = (
        _controller_owner_target(selected)
        if is_cage_controller(selected) else None
    )
    if target is None:
        try:
            from .curve import target_from_helper
            target = target_from_helper(selected)
        except (ImportError, ReferenceError, RuntimeError):
            target = None
    if target is None and selected is not None and selected.type in SUPPORTED_TYPES:
        target = selected
    _sync_target_cage_selection(context, target)
    selected_objects = tuple(getattr(context, "selected_objects", ()) or ())
    _sync_controller_relationship_lines(context, target is not None)
    active_controller = _active_controller_for_target(target, context)
    selected_controllers = tuple(
        obj for obj in selected_objects
        if is_cage_controller(obj) and _controller_owner_target(obj) == target
    )
    editing_controller = (
        selected
        if (
                is_cage_controller(selected) and
                _controller_owner_target(selected) == target
        ) else None
    )
    if editing_controller is None and selected_controllers:
        editing_controller = selected_controllers[0]
    # Mirror once when upgrading an older file. Normal timer refreshes read the
    # target value directly; scanning every stage here would turn a 12.5 Hz
    # display check into repeated scene-wide controller searches.
    if target is not None and not _target_has_show_other_cages(target):
        # New targets show every cage by default. A user who disables the
        # preference still gets the persisted target-wide value on refresh.
        show_other = True
        _sync_target_show_other_cages(target, show_other)
    else:
        show_other = _target_show_other_cages(target, True)

    # Viewport selection can change without an add-on operator being invoked.
    # A compact signature lets the timer notice that transition without
    # repeatedly rewriting every Empty on every tick.
    view_layer = getattr(context, "view_layer", None)
    # Snapshot once per refresh.  Apart from avoiding a second scene-wide
    # traversal below, this keeps the display pass safe during Blender's
    # restricted registration window.
    data_objects = _data_objects_snapshot()
    managed_controllers = tuple(
        obj for obj in data_objects if is_cage_controller(obj))
    display_signature = (
        _pointer(selected), _pointer(target), _pointer(active_controller),
        _pointer(editing_controller),
        bool(show_other), bool(hide_controllers), _pointer(view_layer),
        tuple(
            (
                _pointer(obj),
                str(getattr(getattr(obj, "sdh_cage_deform", None), "deform_type", "")),
                tuple(getattr(
                    getattr(obj, "sdh_cage_deform", None),
                    "deform_order", (),
                )),
                bool(obj.hide_get(view_layer=view_layer))
                if view_layer is not None else False,
            )
            for obj in managed_controllers
        ),
    )
    global _CONTROLLER_DISPLAY_SIGNATURE
    if not force and display_signature == _CONTROLLER_DISPLAY_SIGNATURE:
        return False
    _CONTROLLER_DISPLAY_SIGNATURE = display_signature

    # Clicking a visible Empty controller should also switch the modifier
    # stack, so the N-panel and modifier tab describe the same stage.
    if target is not None and is_cage_controller(selected) and selected == active_controller:
        selected_modifier = find_modifier(target, selected)
        if selected_modifier is not None:
            try:
                target.modifiers.active = selected_modifier
            except (AttributeError, RuntimeError):
                pass

    for obj in data_objects:
        managed_origin = bool(
            obj.type == "EMPTY" and obj.get(PublicData.G_OWNER_PROP, False))
        if not is_cage_controller(obj) and not managed_origin:
            continue
        object_scenes = tuple(getattr(obj, "users_scene", ()))
        move_object_to_control_collection(
            obj, object_scenes[0] if object_scenes else scene)
        if is_cage_controller(obj):
            owner = _controller_owner_target(obj)
            is_active = bool(obj == active_controller and owner == target)
            obj[CONTROLLER_ACTIVE_DISPLAY] = is_active
            _set_controller_style(obj, active=is_active)
            # Custom cage drawings and Gizmos remain visible while the native
            # Empty stays hidden. Reveal only the controller that the user
            # explicitly entered for Blender's Move/Rotate/Scale tools.
            visible = bool(
                (obj == editing_controller or obj in selected_controllers) and
                not hide_controllers)
            obj.show_name = False
            set_helper_object_visible(obj, visible, view_layer)
        else:
            set_helper_object_visible(obj, False)
    try:
        from .curve import set_curve_guide_display
        active_modifier = (
            getattr(target.modifiers, "active", None)
            if target is not None else None)
        set_curve_guide_display(
            target,
            active_modifier if is_cage_modifier(active_modifier) else None,
            show_other,
            view_layer=view_layer,
        )
    except (AttributeError, ImportError, ReferenceError, RuntimeError,
            TypeError, ValueError):
        pass


def organize_helper_objects(context=None, hide_controllers=False):
    """Move owned Empty objects into one collection and refresh their display."""
    refresh_controller_display(context, hide_controllers=hide_controllers)


def cage_modifiers(obj):
    result = []
    for modifier in getattr(obj, "modifiers", ()):
        if not is_cage_modifier(modifier):
            continue
        result.append(modifier)
    return tuple(result)


def deform_stack_modifiers(obj):
    """Return managed cages and native Simple Deform modifiers in stack order."""
    return tuple(
        modifier for modifier in getattr(obj, "modifiers", ())
        if is_cage_modifier(modifier) or modifier.type == "SIMPLE_DEFORM"
    )


def remove_legacy_simple_deform(target, modifier):
    """Remove one native stage and its now-unused managed Origin helper."""
    if (
            target is None or modifier is None or
            modifier.type != "SIMPLE_DEFORM"):
        return False
    origin = getattr(modifier, "origin", None)
    managed_origin = GizmoUtils.is_managed_origin(origin, target)
    target.modifiers.remove(modifier)
    if managed_origin and origin is not None:
        in_use = any(
            candidate.type == "SIMPLE_DEFORM" and
            getattr(candidate, "origin", None) == origin
            for candidate in target.modifiers
        )
        if not in_use:
            try:
                bpy.data.objects.remove(origin, do_unlink=True)
            except (ReferenceError, RuntimeError):
                pass
    StageCache.clear(target)
    return True


def cage_axis_sample_count(target, controller):
    """Count editable mesh levels along a controller's local cage axis.

    The count is intentionally a lightweight warning heuristic. It reads the
    source meshes rather than evaluating the full modifier stack, so drawing
    the N-panel never allocates a temporary evaluated mesh. A generated merge
    has an empty container mesh, so its live source objects are sampled instead.
    Only the warning threshold matters; stop as soon as four levels are found.
    """
    if (
            target is None or controller is None or
            getattr(target, "type", None) != "MESH"
    ):
        return None
    sources = (target,)
    try:
        from .merge import is_deform_merge, live_merge_sources
        if is_deform_merge(target):
            sources = tuple(
                source for _index, _entry, source in live_merge_sources(target)
                if getattr(source, "type", None) == "MESH")
    except (AttributeError, ImportError, ReferenceError, RuntimeError, TypeError):
        pass
    if not sources:
        return None
    values = set()
    try:
        controller_inverse = controller.matrix_world.inverted_safe()
        for source in sources:
            transform = controller_inverse @ source.matrix_world
            for vertex in source.data.vertices:
                values.add(round(float((transform @ vertex.co).y), 5))
                if len(values) >= 4:
                    return 4
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None
    return len(values)


def cage_modifier_uuid(modifier):
    node_group = getattr(modifier, "node_group", None)
    if node_group:
        return str(node_group.get(MODIFIER_UUID, ""))
    for controller in _data_objects_snapshot():
        if (
                is_cage_controller(controller) and
                controller.name == f"{getattr(modifier, 'name', '')} Controller"
        ):
            return str(controller.get(MODIFIER_UUID, ""))
    try:
        return str(modifier.get(MODIFIER_UUID, "")) if modifier else ""
    except (AttributeError, ReferenceError, TypeError):
        return ""


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
    for obj in _data_objects_snapshot():
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


def _normalized_controller_name(value):
    """Normalize Blender's duplicate suffix for controller name matching."""
    value = str(value or "").strip()
    if not value:
        return ""
    head, separator, suffix = value.rpartition(".")
    if separator and suffix.isdigit():
        value = head
    return value.casefold()


def _controller_name_matches_stage(obj, modifier):
    """Return whether an Empty has the generated name for one stage.

    Older files can contain the generated Empty (for example ``Cage Deform
    Controller``) without the current custom-property markers.  The name is
    only accepted together with a parent/UUID check by ``find_controller``;
    this helper deliberately does not classify arbitrary scene Empties as
    cages on its own.
    """
    if obj is None or modifier is None:
        return False
    stage_name = str(getattr(modifier, "name", "") or "")
    expected_names = {f"{stage_name} Controller"}
    # A duplicated modifier can gain a numeric suffix while its old
    # controller keeps the pre-duplication name.  Accept that exact base name
    # only in addition to the UUID/parent checks performed by the caller.
    head, separator, suffix = stage_name.rpartition(".")
    if separator and suffix.isdigit():
        expected_names.add(f"{head} Controller")
    normalized = _normalized_controller_name(getattr(obj, "name", ""))
    return normalized in {
        _normalized_controller_name(name) for name in expected_names}


def _adopt_controller_metadata(target, modifier, controller):
    """Repair ownership markers on a confidently matched legacy controller."""
    if target is None or modifier is None or controller is None:
        return controller
    try:
        target_uuid = str(target.get(TARGET_UUID, "")) or ensure_unique_target_uuid(target)
        modifier_uuid = str(cage_modifier_uuid(modifier) or "")
        controller[CONTROLLER_MARKER] = True
        controller[CONTROLLER_UUID] = str(
            controller.get(CONTROLLER_UUID, "")) or str(uuid.uuid4())
        if target_uuid:
            controller[TARGET_UUID] = target_uuid
        if modifier_uuid:
            controller[MODIFIER_UUID] = modifier_uuid
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return controller


def _fallback_controller_candidates(target, modifier):
    """Yield legacy/partially marked controller candidates for one stage."""
    target_uuid = str(target.get(TARGET_UUID, "")) if target else ""
    modifier_uuid = str(cage_modifier_uuid(modifier) or "")
    expected_name = _controller_name_matches_stage
    candidates = []
    for obj in _data_objects_snapshot():
        try:
            if obj.type != "EMPTY" or getattr(obj, "parent", None) != target:
                continue
            obj_target_uuid = str(obj.get(TARGET_UUID, ""))
            obj_modifier_uuid = str(obj.get(MODIFIER_UUID, ""))
            marked = bool(obj.get(CONTROLLER_MARKER, False))
            # A matching UUID is stronger than a legacy name.  Name matching
            # is intentionally restricted to a direct child of the target so
            # unrelated helper Empties cannot be selected accidentally.
            uuid_match = bool(
                modifier_uuid and obj_modifier_uuid == modifier_uuid and
                (not target_uuid or not obj_target_uuid or
                 obj_target_uuid == target_uuid))
            name_match = expected_name(obj, modifier)
            if not (uuid_match or name_match):
                continue
            score = (0 if marked else 4) + (0 if uuid_match else 2)
            if name_match:
                score -= 1
            candidates.append((score, getattr(obj, "name", ""), obj))
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            continue
    candidates.sort(key=lambda item: (item[0], str(item[1]).casefold()))
    return tuple(item[2] for item in candidates)


def find_controller(target, modifier):
    if target is None or modifier is None:
        return None
    target_uuid = str(target.get(TARGET_UUID, ""))
    modifier_uuid = cage_modifier_uuid(modifier)
    try:
        scenes = tuple(getattr(target, "users_scene", ()))
        controls = control_collection(
            scenes[0] if scenes else None, create=False)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        controls = None
    if controls is not None:
        for obj in controls.objects:
            if (
                    getattr(obj, "parent", None) == target and
                    is_cage_controller(obj) and
                    str(obj.get(TARGET_UUID, "")) == target_uuid and
                    str(obj.get(MODIFIER_UUID, "")) == modifier_uuid
            ):
                return obj
    fallback = None
    for obj in _data_objects_snapshot():
        if (
                is_cage_controller(obj) and
                str(obj.get(TARGET_UUID, "")) == target_uuid and
                str(obj.get(MODIFIER_UUID, "")) == modifier_uuid
        ):
            if getattr(obj, "parent", None) == target:
                return obj
            if fallback is None:
                fallback = obj
    if fallback is not None:
        return fallback

    # Repair controllers saved by builds that predate the ownership markers,
    # or files where a custom-property copy was incomplete.  This keeps all
    # downstream paths (selection, active-stage display, animation and stack
    # removal) on the same canonical controller object.
    legacy = _fallback_controller_candidates(target, modifier)
    if legacy:
        return _adopt_controller_metadata(target, modifier, legacy[0])
    return None


def _ffd_lattice_context_from_object(obj):
    """Resolve a managed FFD stage while its companion is active."""
    try:
        managed = bool(obj.get(FFD_LATTICE_MARKER, False))
        edit_proxy = bool(obj.get(FFD_NATIVE_EDIT_PROXY_MARKER, False))
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        managed = False
        edit_proxy = False
    if (
            getattr(obj, "type", None) != "LATTICE" or
            not (managed or edit_proxy)
    ):
        return None, None, None
    target = getattr(obj, "parent", None)
    if target is None:
        return None, None, None
    modifier_uuid = str(obj.get(FFD_LATTICE_MODIFIER_MARKER, ""))
    for modifier in cage_modifiers(target):
        if edit_proxy:
            if not modifier_uuid or cage_modifier_uuid(modifier) != modifier_uuid:
                continue
        elif ffd_lattice_object(target, modifier) != obj:
            continue
        controller = find_controller(target, modifier)
        properties = getattr(controller, "sdh_cage_deform", None)
        if (
                controller is not None and properties is not None and
                str(getattr(properties, "cage_type", "")) == "FFD"
        ):
            return target, modifier, controller
    return None, None, None


def target_from_context(context):
    obj = _selected_context_object(context)
    lattice_target, _lattice_modifier, _lattice_controller = (
        _ffd_lattice_context_from_object(obj))
    if lattice_target is not None:
        return lattice_target
    if is_cage_controller(obj):
        return find_target(obj)
    try:
        from .curve import target_from_helper
        helper_target = target_from_helper(obj)
        if helper_target is not None:
            return helper_target
    except (ImportError, ReferenceError, RuntimeError):
        pass
    if obj and obj.type in SUPPORTED_TYPES:
        return obj
    return None


def resolve_context_deform(context, fallback=True):
    # UI and Gizmo polls may run while extension registration exposes
    # ``_RestrictData``. Hide cage controls for that brief frame; the next
    # redraw resolves the saved stages after the normal data API is restored.
    if not _data_objects_available():
        return None, None, None
    selected = _selected_context_object(context)
    lattice_context = _ffd_lattice_context_from_object(selected)
    if lattice_context[0] is not None:
        return lattice_context
    try:
        from .curve import context_deform_from_helper
        helper_target, helper_modifier, helper_controller = (
            context_deform_from_helper(selected))
    except (ImportError, ReferenceError, RuntimeError):
        helper_target, helper_modifier, helper_controller = (None, None, None)
    if helper_target is not None and helper_modifier is not None:
        return helper_target, helper_modifier, helper_controller
    if is_cage_controller(selected):
        target = find_target(selected)
        if target is not None:
            ensure_target_stage_ownership(context, target)
        if target_ownership_repair_pending(target):
            return target, None, None
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
    controller = (
        find_controller(target, modifier)
        if modifier and not target_ownership_repair_pending(target) else None
    )
    return target, modifier, controller


def _interface_socket(node_group, name, in_out="INPUT"):
    if node_group is None:
        return None
    try:
        managed = bool(
            node_group.get(GROUP_MARKER, False) or
            node_group.get(MODIFIER_MARKER, False))
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        managed = False
    # Only cache graphs owned by this add-on.  An external node group may be
    # edited by the user at any time, so preserving the old linear scan there
    # is the safer compatibility behaviour.
    if not managed:
        for item in node_group.interface.items_tree:
            if (
                    getattr(item, "name", None) == name and
                    getattr(item, "in_out", None) == in_out
            ):
                return item
        return None
    pointer = _pointer(node_group)
    try:
        token = str(node_group.get(_INTERFACE_CACHE_TOKEN, ""))
        item_count = len(node_group.interface.items_tree)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        token = ""
        item_count = -1
    cache_key = (pointer, token, item_count)
    cached = cached_interface_identifiers(cache_key)
    if cached is None:
        # Keep only immutable identifiers.  Retaining RNA interface-socket
        # wrappers across a modifier update can dereference freed Blender 5.0
        # structs (and caused an access violation during a property callback).
        mapping = {}
        for item in node_group.interface.items_tree:
            item_name = getattr(item, "name", None)
            item_direction = getattr(item, "in_out", None)
            identifier = getattr(item, "identifier", None)
            if (
                    item_name is not None and
                    item_direction is not None and
                    identifier is not None
            ):
                mapping[(item_name, item_direction)] = str(identifier)
        cache_interface_identifiers(cache_key, mapping)
        cached = mapping
    return cached.get((name, in_out))


def modifier_input_identifier(modifier, name):
    node_group = getattr(modifier, "node_group", None)
    socket = _interface_socket(node_group, name) if node_group else None
    if isinstance(socket, str):
        return socket
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


from . import node_graph as _node_graph

_feed = _node_graph._feed
_socket_by_type = _node_graph._socket_by_type
_deform_order_link_pairs = _node_graph._deform_order_link_pairs
_deform_order_links_match = _node_graph._deform_order_links_match
_layout_deform_order_frames = _node_graph._layout_deform_order_frames
relink_deform_order = _node_graph.relink_deform_order
ensure_modifier_deform_order = _node_graph.ensure_modifier_deform_order
build_node_group = _node_graph.build_node_group


def _load_packaged_node_group():
    """Load the versioned node template without rebuilding it in Python."""
    if not GROUP_LIBRARY_PATH.is_file():
        return None
    loaded = ()
    try:
        with bpy.data.libraries.load(
                str(GROUP_LIBRARY_PATH), link=False) as (source, destination):
            if GROUP_NAME not in source.node_groups:
                return None
            destination.node_groups = [GROUP_NAME]
            loaded = destination.node_groups
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    node_group = next(
        (group for group in loaded if group is not None), None)
    if (
            node_group is not None and
            node_group.bl_idname == "GeometryNodeTree" and
            int(node_group.get(GROUP_MARKER, 0)) == GROUP_VERSION
    ):
        node_group.name = GROUP_RUNTIME_NAME
        return node_group
    if node_group is not None and node_group.users == 0:
        bpy.data.node_groups.remove(node_group)
    return None


def ensure_node_group():
    node_group = (
        bpy.data.node_groups.get(GROUP_RUNTIME_NAME) or
        bpy.data.node_groups.get(GROUP_NAME))
    if node_group is None:
        node_group = _load_packaged_node_group()
    if node_group is None or node_group.bl_idname != "GeometryNodeTree":
        node_group = bpy.data.node_groups.new(
            GROUP_RUNTIME_NAME, "GeometryNodeTree")
    if int(node_group.get(GROUP_MARKER, 0)) != GROUP_VERSION:
        build_node_group(node_group)
    elif not node_group.get(_INTERFACE_CACHE_TOKEN, ""):
        # Packaged templates from 2.7.15 and older files may not carry the
        # cache token yet.  Stamp them once without rebuilding the graph.
        node_group[_INTERFACE_CACHE_TOKEN] = str(uuid.uuid4())
    return node_group


def create_stage_node_group(template=None):
    """Copy one validated template into an independent stage group.

    Batch creation passes the already-built template so repeated stages do not
    perform redundant data-block lookup/version checks. The returned group is
    always a deep Blender node-tree copy and is never shared between stages.
    """
    stage_uuid = str(uuid.uuid4())
    template = template or ensure_node_group()
    node_group = template.copy()
    node_group.name = f"{STAGE_GROUP_NAME_PREFIX}{stage_uuid[:8]}"
    node_group[MODIFIER_MARKER] = True
    node_group[MODIFIER_UUID] = stage_uuid
    return node_group


from . import deform_math as _deform_math

normalized_ffd_offsets = _deform_math.normalized_ffd_offsets
deform_point_local = _deform_math.deform_point_local


def deform_point_from_properties(
        point, properties, *, evaluator=False, chain_eligible=True,
        apply_chain_input_offset=True, chain_preview=False,
        chain_frame_sampling=False,
        preview_output_frame=None, chain_profile_after_end=False,
        chain_profile_gap_distance=None, chain_source_coordinate=None,
        chain_source_start=None, operation_order_override=None,
        ffd_offsets_override=None, curve_deformer_override=None,
        ignore_chain_stage_profile=False, chain_frames_override=None,
        chain_domain_values_override=None,
        evaluator_end_scales_override=None,
        chain_stage_index_override=None):
    """Evaluate a point from controller state.

    Standalone cages and subdivided global-profile previews use authored end
    profiles. Modifier evaluation and direct linked-chain previews use
    relative downstream profiles so the incoming seam scale is not applied
    twice.
    """
    enabled = active_deform_types(properties)
    active_order = tuple(
        name for name in ordered_deform_types(properties)
        if name in enabled
    )
    if operation_order_override is not None:
        active_order = tuple(
            name for name in normalize_deform_order(
                operation_order_override, operation_order_override)
            if name in enabled
        )
        enabled = set(active_order)
    top_scale = tuple(properties.top_scale)
    bottom_scale = tuple(properties.bottom_scale)
    is_chained = str(getattr(properties, "mode", "")) == "CHAINED"
    is_non_root_chain = bool(
        is_chained and (
            int(chain_stage_index_override) > 0
            if chain_stage_index_override is not None else
            _is_non_root_chain_stage(properties)))
    controller = getattr(properties, "id_data", None)
    modifier = None
    has_root_output = False
    domain_values = {}
    global_stretch_active = False
    global_prefix_active = False
    global_profile_active = False
    global_prefix_mask = 0
    global_baseline_mask = 0
    global_suffix_active = False
    prefix_base_bend = 0.0
    prefix_base_twist = 0.0
    prefix_base_taper = 0.0
    prefix_base_stretch = 0.0
    prefix_base_shear = (0.0, 0.0, 0.0)
    resolved_profile_gap_distance = 0.0
    if is_chained:
        if chain_domain_values_override is None:
            target = find_target(controller)
            modifier = find_modifier(target, controller)
            has_root_output = (
                not is_non_root_chain and
                chain_root_output_active(controller, modifier)
            )
            domain_values = _chain_domain_input_values(controller, modifier)
        else:
            domain_values = chain_domain_values_override
        # The hidden source interval metadata describes the physical spacing
        # before the next cage.  Use that spacing only for profile continuation
        # in the gap; once the next stage owns the source interval, the current
        # stage must hold its terminal Twist/Taper value.
        try:
            global_stretch_active = bool(
                domain_values.get("Chain Global Stretch Active", False))
            global_prefix_active = bool(
                domain_values.get("Chain Global Prefix Active", False))
            global_profile_active = bool(
                domain_values.get("Chain Global Profile Active", False))
            global_prefix_mask = int(
                domain_values.get("Chain Global Prefix Types", 0))
            global_baseline_mask = int(domain_values.get(
                "Chain Global Baseline Types", global_prefix_mask))
            global_suffix_active = bool(
                domain_values.get("Chain Global Suffix Active", False))
            prefix_base_bend = float(
                domain_values.get("Chain Prefix Base Bend", 0.0))
            prefix_base_twist = float(
                domain_values.get("Chain Prefix Base Twist", 0.0))
            prefix_base_taper = float(
                domain_values.get("Chain Prefix Base Taper", 0.0))
            prefix_base_stretch = float(
                domain_values.get("Chain Prefix Base Stretch", 0.0))
            prefix_base_shear = tuple(float(value) for value in
                domain_values.get(
                    "Chain Prefix Base Shear", (0.0, 0.0, 0.0)))
            source_start = float(domain_values.get("Chain Source Start", 0.0))
            source_end = float(domain_values.get("Chain Source End", 0.0))
            stage_length = max(abs(float(properties.size[1])), EPSILON)
            resolved_profile_gap_distance = max(
                source_end - (source_start + stage_length), 0.0)
        except (AttributeError, TypeError, ValueError, RuntimeError):
            resolved_profile_gap_distance = 0.0
    if evaluator or (
            chain_preview and is_chained and not global_profile_active
    ):
        if evaluator_end_scales_override is None:
            top_scale, bottom_scale = evaluator_end_scales(properties)
        else:
            top_scale, bottom_scale = evaluator_end_scales_override
    if global_stretch_active:
        # Stretch is represented by the single root-frame pass at the chain
        # tip.  Keep the Python reference and viewport frame sampler aligned
        # with the GN mask, which removes it from every local stage.
        enabled.discard("STRETCH")
        active_order = tuple(
            name for name in active_order if name != "STRETCH")
    local_bend_strength = float(properties.bend_strength)
    local_twist_strength = float(properties.twist_strength)
    local_taper_factor = float(properties.taper_factor)
    local_stretch_factor = float(properties.stretch_factor)
    local_shear_factors = tuple(float(value) for value in
        getattr(properties, "shear_factors", (0.0, 0.0)))
    if (
            (global_prefix_active or global_suffix_active) and
            evaluator and (not chain_preview or chain_frame_sampling)
    ):
        if global_baseline_mask & DEFORM_BITS["BEND"]:
            local_bend_strength -= prefix_base_bend
        if global_baseline_mask & DEFORM_BITS["TWIST"]:
            local_twist_strength -= prefix_base_twist
        if global_baseline_mask & DEFORM_BITS["TAPER"]:
            local_taper_factor -= prefix_base_taper
        if global_baseline_mask & DEFORM_BITS["STRETCH"]:
            local_stretch_factor -= prefix_base_stretch
        if global_baseline_mask & DEFORM_BITS["SHEAR"]:
            base_shear_x = (
                float(prefix_base_shear[0]) if prefix_base_shear else 0.0)
            base_shear_z = (
                float(prefix_base_shear[2]) if len(prefix_base_shear) > 2 else
                float(prefix_base_shear[1])
                if len(prefix_base_shear) > 1 else 0.0)
            local_shear_factors = (
                local_shear_factors[0] - base_shear_x,
                local_shear_factors[1] - base_shear_z,
            )
    if chain_profile_gap_distance is not None:
        try:
            resolved_profile_gap_distance = max(
                float(chain_profile_gap_distance), 0.0)
        except (TypeError, ValueError):
            resolved_profile_gap_distance = 0.0
    apply_chain_frames = bool(
        chain_frames_override is not None or
        is_non_root_chain or has_root_output)
    point = Vector(point)
    if (
            evaluator and (not chain_preview or chain_frame_sampling) and
            is_chained and not is_non_root_chain and
            (global_prefix_active or global_profile_active) and
            bool(getattr(properties, "stage_enabled", True))
    ):
        try:
            source_value = (
                float(chain_source_coordinate)
                if chain_source_coordinate is not None else float(point.y))
            stage_matrix = (
                Matrix.Translation(Vector(controller.location)) @
                _controller_rotation_xyz(controller).to_matrix().to_4x4()
            )
            target_point = stage_matrix @ point
            target_point = apply_chain_global_prefix(
                target_point,
                source_value,
                deform_mask=global_prefix_mask,
                bend=domain_values.get("Chain Global Prefix Bend", 0.0),
                direction=domain_values.get(
                    "Chain Global Prefix Direction", 0.0),
                twist=domain_values.get("Chain Global Prefix Twist", 0.0),
                taper=domain_values.get("Chain Global Prefix Taper", 0.0),
                stretch=domain_values.get("Chain Global Prefix Stretch", 0.0),
                shear=domain_values.get(
                    "Chain Global Prefix Shear", (0.0, 0.0, 0.0)),
                pre_shear_mask=domain_values.get(
                    "Chain Global Prefix Pre Shear Types", 0),
                post_shear_mask=domain_values.get(
                    "Chain Global Prefix Post Shear Types", 0),
                center=domain_values.get(
                    "Chain Global Prefix Center", (0.0, 0.0, 0.0)),
                rotation=domain_values.get(
                    "Chain Global Prefix Rotation", (0.0, 0.0, 0.0)),
                source_offset=domain_values.get(
                    "Chain Global Prefix Source Offset", 0.0),
                length=domain_values.get("Chain Global Prefix Length", 2.0),
                origin=domain_values.get(
                    "Chain Global Prefix Origin", ORIGIN_VALUES["BOTTOM"]),
                profile_active=global_profile_active,
                bottom_scale=domain_values.get(
                    "Chain Global Profile Bottom Scale", (1.0, 1.0, 1.0)),
                top_scale=domain_values.get(
                    "Chain Global Profile Top Scale", (1.0, 1.0, 1.0)),
                bottom_offset=domain_values.get(
                    "Chain Global Profile Bottom Offset", (0.0, 0.0, 0.0)),
                top_offset=domain_values.get(
                    "Chain Global Profile Top Offset", (0.0, 0.0, 0.0)),
                preserve_volume=bool(properties.preserve_volume),
            )
            point = stage_matrix.inverted_safe() @ target_point
        except (
                AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError, OverflowError,
        ):
            pass
    # A subdivided source profile is stored on each stage for editing and
    # animation, but a chain-global profile is evaluated exactly once in the
    # root frame. Do not apply the visible per-stage values a second time to
    # evaluated geometry. Linked previews already receive the upstream affine
    # frame and therefore use the same relative scales as the evaluator.
    effective_top_offset = tuple(properties.top_offset)
    effective_bottom_offset = tuple(properties.bottom_offset)
    ignore_local_end_scale = bool(
        evaluator and ignore_chain_stage_profile)
    ignore_global_profile = bool(
        evaluator and global_profile_active and
        (ignore_chain_stage_profile or not chain_preview))
    if ignore_local_end_scale or ignore_global_profile:
        top_scale = (1.0, 1.0)
        bottom_scale = (1.0, 1.0)
    if ignore_global_profile:
        effective_top_offset = (0.0, 0.0)
        effective_bottom_offset = (0.0, 0.0)

    curve_deformer = curve_deformer_override
    if curve_deformer is None and "CURVE" in enabled:
        try:
            from .curve import curve_preview_deformer
            curve_deformer = curve_preview_deformer(properties)
        except (AttributeError, ImportError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            curve_deformer = None

    kwargs = dict(
        size=properties.size,
        deform_type=properties.deform_type,
        strength=properties.strength,
        factor=properties.factor,
        direction=properties.direction,
        mode=properties.mode,
        origin=properties.origin,
        preserve_volume=properties.preserve_volume,
        top_scale=top_scale,
        bottom_scale=bottom_scale,
        top_offset=effective_top_offset,
        bottom_offset=effective_bottom_offset,
        stage_enabled=bool(getattr(properties, "stage_enabled", True)),
        chain_eligible=chain_eligible,
        chain_root_stage=is_chained and not is_non_root_chain,
        deform_types=enabled,
        bend_strength=local_bend_strength,
        bend_direction=properties.bend_direction,
        twist_strength=local_twist_strength,
        taper_factor=local_taper_factor,
        stretch_factor=local_stretch_factor,
        shear_factors=local_shear_factors,
        ffd_offsets=(
            getattr(properties, "ffd_offsets", ())
            if ffd_offsets_override is None else ffd_offsets_override),
        curve_deformer=curve_deformer,
        deform_order=active_order,
        chain_profile_gap_distance=resolved_profile_gap_distance,
        chain_source_coordinate=chain_source_coordinate,
        chain_source_start=chain_source_start,
    )
    chain_input_frame = None
    chain_output_frame = None
    if (
            evaluator and apply_chain_input_offset and
            apply_chain_frames
    ):
        if chain_frames_override is None:
            chain_input_frame, chain_output_frame = (
                chain_conjugation_frames_for_controller(
                    controller, modifier, properties))
        else:
            chain_input_frame, chain_output_frame = chain_frames_override
    elif (
            chain_preview and
            apply_chain_frames
    ):
        if chain_frames_override is not None:
            _chain_input_frame, chain_output_frame = chain_frames_override
        elif preview_output_frame is None:
            _input_frame, chain_output_frame = (
                chain_conjugation_frames_for_controller(
                    controller, modifier, properties))
        else:
            chain_output_frame = preview_output_frame
    return deform_point_local(
        point,
        chain_input_frame=chain_input_frame,
        chain_output_frame=chain_output_frame,
        chain_profile_after_end=chain_profile_after_end,
        **kwargs,
    )


_CHAIN_PREFIX_PREVIEW_UNSET = object()
_CHAIN_STRETCH_PREVIEW_UNSET = object()
_CHAIN_DISPLAY_PREVIEW_UNSET = object()


def chain_global_prefix_preview_state(properties):
    """Resolve the real modifier path for a global chain baseline preview.

    A Twist/Taper/Stretch authored before Bend is evaluated once in the
    original full-cage frame.  The visible per-stage values remain editable,
    but Geometry Nodes subtracts their stored baseline before evaluating each
    local stage.  Rebuild that original source point here so viewport cages
    use the same path instead of repeating each stage's baseline deformation.
    The same root-frame path owns a subdivided scale/offset profile even when
    there is no pre-Bend operation, so either global mode activates it.
    """
    if str(getattr(properties, "mode", "")) != "CHAINED":
        return None
    controller = getattr(properties, "id_data", None)
    if controller is None or not is_cage_controller(controller):
        return None
    target = find_target(controller)
    modifier = find_modifier(target, controller)
    if target is None or modifier is None:
        return None
    try:
        domain = _chain_domain_input_values(controller, modifier)
        if not (
                bool(domain.get("Chain Global Prefix Active", False)) or
                bool(domain.get("Chain Global Profile Active", False))
        ):
            return None

        from . import chain as chain_module

        chain_uuid = chain_module.stage_chain_uuid(modifier)
        stages = tuple(chain_module.chain_stages(target, chain_uuid))
        stage_index = stages.index(modifier)
        stages = stages[:stage_index + 1]
        controllers = tuple(
            find_controller(target, stage) for stage in stages)
        if any(item is None for item in controllers):
            return None
        matrices = tuple(
            chain_module._stage_local_matrix(target, item)
            for item in controllers)
        inverses = tuple(matrix.inverted_safe() for matrix in matrices)
        domains = tuple(
            _chain_domain_input_values(item, stage)
            for item, stage in zip(controllers, stages))
        source_starts = tuple(
            float(values.get("Chain Source Start", 0.0))
            for values in domains)
        half_y = max(abs(float(properties.size[1])) * 0.5, EPSILON)
        center = Vector(domain.get(
            "Chain Global Prefix Center", (0.0, 0.0, 0.0)))
        rotation = tuple(float(value) for value in domain.get(
            "Chain Global Prefix Rotation", (0.0, 0.0, 0.0)))
        prefix_matrix = (
            Matrix.Translation(center) @
            Euler(rotation, "XYZ").to_matrix().to_4x4()
        )

        signature_keys = (
            "Chain Global Prefix Active",
            "Chain Global Prefix Types",
            "Chain Global Baseline Types",
            "Chain Global Prefix Pre Shear Types",
            "Chain Global Prefix Post Shear Types",
            "Chain Global Prefix Shear",
            "Chain Global Prefix Bend",
            "Chain Global Prefix Direction",
            "Chain Global Prefix Twist",
            "Chain Global Prefix Taper",
            "Chain Global Prefix Stretch",
            "Chain Global Prefix Center",
            "Chain Global Prefix Rotation",
            "Chain Global Prefix Source Offset",
            "Chain Global Prefix Length",
            "Chain Global Prefix Origin",
            "Chain Global Profile Active",
            "Chain Global Profile Bottom Scale",
            "Chain Global Profile Top Scale",
            "Chain Global Profile Bottom Offset",
            "Chain Global Profile Top Offset",
            "Chain Prefix Base Bend",
            "Chain Prefix Base Twist",
            "Chain Prefix Base Taper",
            "Chain Prefix Base Stretch",
            "Chain Prefix Base Shear",
        )

        def signature_value(value):
            if isinstance(value, (tuple, list, Vector)):
                return tuple(float(component).hex() for component in value)
            if isinstance(value, float):
                return value.hex()
            return value

        signature = (
            "SDH_CHAIN_GLOBAL_PREFIX_PREVIEW_V1",
            stage_index,
            tuple(
                tuple(float(value).hex() for row in matrix for value in row)
                for matrix in matrices),
            tuple(value.hex() for value in source_starts),
            tuple(
                tuple(
                    (key, signature_value(values.get(key)))
                    for key in signature_keys)
                for values in domains),
        )
        return {
            "signature": signature,
            "controllers": controllers,
            "stages": stages,
            "matrices": matrices,
            "inverses": inverses,
            "source_starts": source_starts,
            "source_start": source_starts[stage_index],
            "source_offset": float(domain.get(
                "Chain Global Prefix Source Offset", 0.0)),
            "half_y": half_y,
            "prefix_matrix": prefix_matrix,
            "target_to_current": inverses[stage_index],
            "current_controller": controllers[stage_index],
        }
    except (
            AttributeError, ImportError, IndexError, KeyError, ReferenceError,
            RuntimeError, TypeError, ValueError, OverflowError,
    ):
        return None


def chain_global_prefix_preview_signature(state):
    """Return an immutable cache key for a global-prefix cage preview."""
    return state.get("signature", ()) if state else ()


def _deform_point_with_chain_global_prefix_preview(
        point, state, *, ffd_offsets_override=None,
        curve_deformer_override=None):
    """Evaluate one authored stage point through its real modifier prefix."""
    source_point = Vector(point)
    source_coordinate = (
        float(state["source_start"]) + float(source_point.y) +
        float(state["half_y"])
    )
    source_local = Vector((
        source_point.x,
        source_coordinate + float(state["source_offset"]),
        source_point.z,
    ))
    target_point = state["prefix_matrix"] @ source_local
    current_controller = state["current_controller"]
    for index, (stage, controller, matrix, inverse, source_start) in enumerate(
            zip(
                state["stages"], state["controllers"], state["matrices"],
                state["inverses"], state["source_starts"])):
        local = inverse @ target_point
        target_point = matrix @ Vector(deform_point_from_properties(
            local,
            controller.sdh_cage_deform,
            evaluator=True,
            chain_eligible=(
                index == 0 or
                source_coordinate >= float(source_start) - EPSILON * 10.0),
            chain_source_coordinate=source_coordinate,
            chain_source_start=source_start,
            ffd_offsets_override=(
                ffd_offsets_override
                if controller == current_controller else None),
            curve_deformer_override=(
                curve_deformer_override
                if controller == current_controller else None),
        ))
    return state["target_to_current"] @ target_point


def chain_global_stretch_value(controller, modifier=None):
    """Return the shared Stretch factor for a global-Stretch chain stage."""
    if controller is None or not is_cage_controller(controller):
        return None
    if modifier is None:
        target = find_target(controller)
        modifier = find_modifier(target, controller)
    if modifier is None:
        return None
    try:
        domain = _chain_domain_input_values(controller, modifier)
        if not bool(domain.get("Chain Global Stretch Active", False)):
            return None
        return float(domain.get("Chain Global Stretch Factor", 0.0))
    except (
            AttributeError, ReferenceError, RuntimeError, TypeError,
            ValueError, OverflowError,
    ):
        return None


def sync_chain_global_stretch_from_stage(controller, value):
    """Edit a chain-global Stretch pass without rebuilding chain frames.

    A subdivided Bend -> Stretch stack evaluates Stretch once for the whole
    chain.  Its visible stage properties therefore represent one shared value,
    not independent local factors.  Write that value directly to every owner
    and Geometry Nodes input; global Stretch does not alter chain connection
    frames, so queuing ``reconnect_chain`` here only causes drag latency.
    """
    if controller is None or not is_cage_controller(controller):
        return False
    target = find_target(controller)
    modifier = find_modifier(target, controller)
    if target is None or modifier is None:
        return False
    if chain_global_stretch_value(controller, modifier) is None:
        return False
    try:
        factor = float(value)
        if not math.isfinite(factor):
            return True
        from . import chain as chain_module
        chain_uuid = chain_module.stage_chain_uuid(modifier)
        stages = chain_module.chain_stages(target, chain_uuid)
        if not chain_uuid or not stages:
            return False
        metadata_key = chain_module.CHAIN_GLOBAL_STRETCH_FACTOR
    except (
            ImportError, AttributeError, ReferenceError, RuntimeError,
            TypeError, ValueError, OverflowError,
    ):
        return False

    changed = False
    for stage in stages:
        stage_controller = find_controller(target, stage)
        if stage_controller is None:
            continue
        for owner in (getattr(stage, "node_group", None), stage_controller):
            if owner is None:
                continue
            try:
                previous = owner.get(metadata_key, None)
                if previous is None or abs(float(previous) - factor) > EPSILON:
                    owner[metadata_key] = factor
                    changed = True
            except (
                    AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError, OverflowError,
            ):
                continue

        properties = getattr(stage_controller, "sdh_cage_deform", None)
        stage_pointer = _pointer(stage_controller)
        if properties is not None and stage_pointer:
            _CHAIN_GLOBAL_STRETCH_GUARD.add(stage_pointer)
            try:
                if abs(float(properties.stretch_factor) - factor) > EPSILON:
                    properties.stretch_factor = factor
                    changed = True
                if (
                        str(properties.deform_type) == "STRETCH" and
                        abs(float(properties.factor) - factor) > EPSILON
                ):
                    properties.factor = factor
                    changed = True
            finally:
                _CHAIN_GLOBAL_STRETCH_GUARD.discard(stage_pointer)

        for socket_name in (
                "Chain Global Stretch Factor",
                "Stretch Factor",
        ):
            if modifier_input_identifier(stage, socket_name) is None:
                continue
            old = modifier_input(stage, socket_name)
            try:
                differs = old is None or abs(float(old) - factor) > EPSILON
            except (TypeError, ValueError, OverflowError):
                differs = True
            if differs:
                set_modifier_input(stage, socket_name, factor)
                changed = True
        if (
                properties is not None and
                str(properties.deform_type) == "STRETCH" and
                modifier_input_identifier(stage, "Factor") is not None
        ):
            old = modifier_input(stage, "Factor")
            try:
                differs = old is None or abs(float(old) - factor) > EPSILON
            except (TypeError, ValueError, OverflowError):
                differs = True
            if differs:
                set_modifier_input(stage, "Factor", factor)
                changed = True

    if changed:
        # Preview state and shared-value reads use the cached chain-domain
        # payload. The sockets above are live immediately, so invalidate the
        # matching metadata cache without scheduling a full reconnect.
        invalidate_chain_domain_cache()
        target.update_tag()
        _tag_view3d_redraw()
    return True


def chain_global_stretch_preview_state(properties):
    """Resolve the final global Stretch pass for one chained cage preview.

    Geometry Nodes evaluates post-Bend Stretch once at the chain tip.  Local
    chain frames intentionally omit that pass, so viewport controls need this
    separate state to display the same final result without changing chain
    reconnection or applying Stretch twice to evaluated geometry.
    """
    if str(getattr(properties, "mode", "")) != "CHAINED":
        return None
    controller = getattr(properties, "id_data", None)
    if controller is None or not is_cage_controller(controller):
        return None
    target = find_target(controller)
    modifier = find_modifier(target, controller)
    if target is None or modifier is None:
        return None
    try:
        domain = _chain_domain_input_values(controller, modifier)
        suffix_active = bool(
            domain.get("Chain Global Suffix Active", False))
        stretch_active = bool(
            domain.get("Chain Global Stretch Active", False))
        if not (suffix_active or stretch_active):
            return None
        local_to_target = (
            Matrix.Translation(Vector(controller.location)) @
            _controller_rotation_xyz(controller).to_matrix().to_4x4()
        )
        return {
            "suffix_active": suffix_active,
            "suffix_mask": int(domain.get(
                "Chain Global Suffix Types", 0)),
            "suffix_pre_shear_mask": int(domain.get(
                "Chain Global Suffix Pre Shear Types", 0)),
            "suffix_post_shear_mask": int(domain.get(
                "Chain Global Suffix Post Shear Types", 0)),
            "suffix_twist": float(domain.get(
                "Chain Global Suffix Twist", 0.0)),
            "suffix_taper": float(domain.get(
                "Chain Global Suffix Taper", 0.0)),
            "suffix_shear": tuple(float(value) for value in domain.get(
                "Chain Global Suffix Shear", (0.0, 0.0, 0.0))),
            "factor": float(domain.get("Chain Global Stretch Factor", 0.0)),
            "center": tuple(float(value) for value in domain.get(
                "Chain Global Stretch Center", (0.0, 0.0, 0.0))),
            "rotation": tuple(float(value) for value in domain.get(
                "Chain Global Stretch Rotation", (0.0, 0.0, 0.0))),
            "source_offset": float(domain.get(
                "Chain Global Stretch Source Offset", 0.0)),
            "length": max(float(domain.get(
                "Chain Global Stretch Length", 2.0)), EPSILON),
            "origin": domain.get(
                "Chain Global Stretch Origin", ORIGIN_VALUES["BOTTOM"]),
            "source_start": float(domain.get("Chain Source Start", 0.0)),
            "half_y": max(abs(float(properties.size[1])) * 0.5, EPSILON),
            "preserve_volume": bool(properties.preserve_volume),
            "local_to_target": local_to_target,
            "target_to_local": local_to_target.inverted_safe(),
        }
    except (
            AttributeError, ReferenceError, RuntimeError, TypeError,
            ValueError, OverflowError,
    ):
        return None


def chain_global_stretch_preview_signature(state):
    """Return an immutable cache key for final chained Stretch display."""
    if not state:
        return ()

    def floats(values):
        return tuple(float(value).hex() for value in values)

    matrix = state["local_to_target"]
    return (
        bool(state["suffix_active"]),
        int(state["suffix_mask"]),
        int(state["suffix_pre_shear_mask"]),
        int(state["suffix_post_shear_mask"]),
        float(state["suffix_twist"]).hex(),
        float(state["suffix_taper"]).hex(),
        floats(state["suffix_shear"]),
        float(state["factor"]).hex(),
        floats(state["center"]),
        floats(state["rotation"]),
        float(state["source_offset"]).hex(),
        float(state["length"]).hex(),
        str(state["origin"]),
        float(state["source_start"]).hex(),
        float(state["half_y"]).hex(),
        bool(state["preserve_volume"]),
        tuple(float(value).hex() for row in matrix for value in row),
    )


def chain_display_preview_state(properties, *, through_current=False):
    """Build one reusable cumulative-chain plan for viewport point samples."""
    controller = getattr(properties, "id_data", None)
    if not is_cage_controller(controller):
        return None
    target = find_target(controller)
    modifier = find_modifier(target, controller)
    if (
            target is None or modifier is None or
            _managed_chain_mode(controller, modifier) not in
            {"CHAINED", "CONNECTED"}
    ):
        return None
    try:
        from . import chain as chain_module

        chain_uuid = chain_module.stage_chain_uuid(modifier)
        stages = tuple(chain_module.chain_stages(target, chain_uuid))
        current_index = stages.index(modifier)
        if through_current:
            stages = stages[:current_index + 1]
        controllers = tuple(
            find_controller(target, stage) for stage in stages)
        if any(item is None for item in controllers):
            return None
        matrices = tuple(
            cage_local_matrix(target, item) for item in controllers)
        domains = tuple(
            _chain_domain_input_values(item, stage)
            for item, stage in zip(controllers, stages))
        source_starts = tuple(
            float(values.get("Chain Source Start", 0.0))
            for values in domains)
        stage_orders = tuple(
            tuple(ordered_deform_types(item.sdh_cage_deform))
            for item in controllers)

        def freeze(value):
            if isinstance(value, float):
                return value.hex()
            if isinstance(value, (bool, int, str)) or value is None:
                return value
            try:
                components = tuple(value)
            except TypeError:
                components = None
            if components is not None:
                return tuple(freeze(component) for component in components)
            try:
                return float(value).hex()
            except (TypeError, ValueError, OverflowError):
                return repr(value)

        stage_signatures = []
        for index, (item, stage, matrix, domain) in enumerate(zip(
                controllers, stages, matrices, domains)):
            item_properties = item.sdh_cage_deform
            stage_signatures.append((
                _pointer(item),
                tuple(float(value).hex() for row in matrix for value in row),
                freeze(item_properties.size),
                stage_orders[index],
                tuple(sorted(active_deform_types(item_properties))),
                float(item_properties.bend_strength).hex(),
                float(item_properties.bend_direction).hex(),
                float(item_properties.twist_strength).hex(),
                float(item_properties.taper_factor).hex(),
                float(item_properties.stretch_factor).hex(),
                freeze(item_properties.shear_factors),
                str(item_properties.mode),
                str(item_properties.origin),
                str(getattr(item_properties, "cage_type", "STANDARD")),
                bool(item_properties.preserve_volume),
                bool(getattr(item_properties, "stage_enabled", True)),
                freeze(item_properties.top_scale),
                freeze(item_properties.bottom_scale),
                freeze(item_properties.top_offset),
                freeze(item_properties.bottom_offset),
                freeze(getattr(item_properties, "ffd_offsets", ())),
                tuple((str(key), freeze(value))
                      for key, value in sorted(domain.items())),
                bool(getattr(stage, "show_viewport", True)),
            ))
        plan_signature = (
            "SDH_CHAIN_DISPLAY_PLAN_V2",
            _pointer(target),
            tuple(stage_signatures),
        )

        def stage_view(plan):
            state = dict(plan)
            state.update({
                "signature": (
                    "SDH_CHAIN_DISPLAY_PREVIEW_V2",
                    plan_signature,
                    current_index,
                ),
                "controller": controller,
                "current_index": current_index,
                "current_half_y": max(
                    abs(float(properties.size[1])) * 0.5, EPSILON),
            })
            return state

        cached = _CHAIN_DISPLAY_STATE_CACHE.get(plan_signature)
        if cached is not None:
            return stage_view(cached)

        inverses = tuple(matrix.inverted_safe() for matrix in matrices)
        frame_map = precompute_chain_conjugation_frames(controllers, stages)
        frames = tuple(
            frame_map.get(_pointer(item)) or
            chain_conjugation_frames_for_controller(
                item, stage, item.sdh_cage_deform)
            for item, stage in zip(controllers, stages))
        end_scales = tuple(
            evaluator_end_scales(item.sdh_cage_deform, item, stage)
            for item, stage in zip(controllers, stages))
        prepared_stages = []
        for index, (item, domain, item_frames, item_end_scales) in enumerate(
                zip(controllers, domains, frames, end_scales)):
            item_properties = item.sdh_cage_deform
            enabled = set(active_deform_types(item_properties))
            has_global_path = any(bool(domain.get(key, False)) for key in (
                "Chain Global Stretch Active",
                "Chain Global Prefix Active",
                "Chain Global Profile Active",
                "Chain Global Suffix Active",
            ))
            if has_global_path or "CURVE" in enabled:
                prepared_stages.append(None)
                continue
            source_start = source_starts[index]
            source_end = float(domain.get("Chain Source End", source_start))
            stage_length = max(
                abs(float(item_properties.size[1])), EPSILON)
            prepared_stages.append({
                "size": tuple(item_properties.size),
                "deform_type": str(item_properties.deform_type),
                "strength": float(item_properties.strength),
                "factor": float(item_properties.factor),
                "direction": float(item_properties.direction),
                "mode": str(item_properties.mode),
                "origin": str(item_properties.origin),
                "preserve_volume": bool(item_properties.preserve_volume),
                "top_scale": tuple(item_end_scales[0]),
                "bottom_scale": tuple(item_end_scales[1]),
                "top_offset": tuple(item_properties.top_offset),
                "bottom_offset": tuple(item_properties.bottom_offset),
                "stage_enabled": bool(getattr(
                    item_properties, "stage_enabled", True)),
                "chain_root_stage": index == 0,
                "chain_input_frame": item_frames[0],
                "chain_output_frame": item_frames[1],
                "chain_source_start": source_start,
                "chain_profile_gap_distance": max(
                    source_end - (source_start + stage_length), 0.0),
                "deform_types": tuple(enabled),
                "bend_strength": float(item_properties.bend_strength),
                "bend_direction": float(item_properties.bend_direction),
                "twist_strength": float(item_properties.twist_strength),
                "taper_factor": float(item_properties.taper_factor),
                "stretch_factor": float(item_properties.stretch_factor),
                "shear_factors": tuple(item_properties.shear_factors),
                "ffd_offsets": tuple(getattr(
                    item_properties, "ffd_offsets", ())),
                "deform_order": stage_orders[index],
                "curve_deformer": None,
                "_prepared": True,
            })
        prepared_stages = tuple(prepared_stages)
        plan = {
            "controllers": controllers,
            "stages": stages,
            "matrices": matrices,
            "inverses": inverses,
            "domains": domains,
            "source_starts": source_starts,
            "stage_orders": stage_orders,
            "frames": frames,
            "end_scales": end_scales,
            "prepared_stages": prepared_stages,
            "root_half_y": max(
                abs(float(controllers[0].sdh_cage_deform.size[1])) * 0.5,
                EPSILON,
            ),
        }
        if len(_CHAIN_DISPLAY_STATE_CACHE) >= _CHAIN_DISPLAY_STATE_CACHE_LIMIT:
            _CHAIN_DISPLAY_STATE_CACHE.clear()
        _CHAIN_DISPLAY_STATE_CACHE[plan_signature] = plan
        return stage_view(plan)
    except (
            AttributeError, ImportError, IndexError, KeyError, ReferenceError,
            RuntimeError, TypeError, ValueError, OverflowError,
    ):
        return None


def chain_display_preview_signature(state):
    """Return the exact cache key for one cumulative-chain display plan."""
    return state.get("signature", ()) if state else ()


def _chained_point_for_display(
        point, properties, *, ffd_offsets_override=None,
        curve_deformer_override=None, chain_display_state=None):
    """Evaluate one visible cage point through the real cumulative chain."""
    controller = getattr(properties, "id_data", None)
    if not is_cage_controller(controller):
        return None
    state = (
        chain_display_preview_state(properties)
        if chain_display_state is None else chain_display_state)
    if not state or state.get("controller") != controller:
        return None
    try:
        source_point = Vector(point)
        controllers = state["controllers"]
        matrices = state["matrices"]
        inverses = state["inverses"]
        domains = state["domains"]
        source_starts = state["source_starts"]
        stage_index = int(state["current_index"])
        source_coordinate = (
            source_starts[stage_index] + float(source_point.y) +
            float(state["current_half_y"]))
        source_local = Vector((
            float(source_point.x),
            source_coordinate - source_starts[0] -
            float(state["root_half_y"]),
            float(source_point.z),
        ))
        target_point = matrices[0] @ source_local
        for index, (
                stage_controller, stage_matrix, inverse, source_start,
                domain, frames, end_scales, stage_order,
        ) in (
                enumerate(zip(
                    controllers, matrices, inverses, source_starts,
                    domains, state["frames"], state["end_scales"],
                    state["stage_orders"],
                ))):
            chain_eligible = bool(
                index == 0 or
                source_coordinate >= source_start - CHAIN_BOUNDARY_EPSILON)
            stage_properties = stage_controller.sdh_cage_deform
            local = inverse @ target_point
            if not chain_eligible:
                # Preserve the evaluator's matrix round-trip for downstream
                # ineligible stages without paying the full property path.
                target_point = stage_matrix @ local
                continue
            active_stage = stage_controller == controller
            prepared = state["prepared_stages"][index]
            active_override = bool(
                active_stage and (
                    ffd_offsets_override is not None or
                    curve_deformer_override is not None))
            if prepared is not None and not active_override:
                deformed = deform_point_local(
                    local,
                    chain_eligible=chain_eligible,
                    chain_source_coordinate=source_coordinate,
                    **prepared,
                )
            else:
                deformed = deform_point_from_properties(
                    local,
                    stage_properties,
                    evaluator=True,
                    chain_eligible=chain_eligible,
                    chain_source_coordinate=source_coordinate,
                    chain_source_start=source_start,
                    operation_order_override=stage_order,
                    ffd_offsets_override=(
                        ffd_offsets_override if active_stage else None),
                    curve_deformer_override=(
                        curve_deformer_override if active_stage else None),
                    chain_frames_override=frames,
                    chain_domain_values_override=domain,
                    evaluator_end_scales_override=end_scales,
                    chain_stage_index_override=index,
                )
            target_point = stage_matrix @ Vector(deformed)
        return inverses[stage_index] @ target_point
    except (
            AttributeError, ImportError, ReferenceError, RuntimeError,
            TypeError, ValueError, OverflowError,
    ):
        return None


def deform_point_for_display(
        point, properties, *, preview_output_frame=None,
        chain_prefix_state=_CHAIN_PREFIX_PREVIEW_UNSET,
        chain_stretch_state=_CHAIN_STRETCH_PREVIEW_UNSET,
        chain_display_state=_CHAIN_DISPLAY_PREVIEW_UNSET,
        ffd_offsets_override=None, curve_deformer_override=None):
    """Evaluate one cage-local point in the final viewport display state."""
    source_point = Vector(point)
    prefix_state = chain_prefix_state
    if prefix_state is _CHAIN_PREFIX_PREVIEW_UNSET:
        prefix_state = chain_global_prefix_preview_state(properties)
    if prefix_state:
        try:
            result = Vector(_deform_point_with_chain_global_prefix_preview(
                source_point,
                prefix_state,
                ffd_offsets_override=ffd_offsets_override,
                curve_deformer_override=curve_deformer_override,
            ))
        except (
                AttributeError, KeyError, ReferenceError, RuntimeError,
                TypeError, ValueError, OverflowError,
        ):
            prefix_state = None
    if not prefix_state:
        display_state = chain_display_state
        if display_state is _CHAIN_DISPLAY_PREVIEW_UNSET:
            display_state = chain_display_preview_state(properties)
        chained_result = _chained_point_for_display(
            source_point,
            properties,
            ffd_offsets_override=ffd_offsets_override,
            curve_deformer_override=curve_deformer_override,
            chain_display_state=display_state,
        )
        if chained_result is not None:
            return Vector(chained_result)
        result = Vector(deform_point_from_properties(
            source_point,
            properties,
            chain_preview=True,
            preview_output_frame=preview_output_frame,
            ffd_offsets_override=ffd_offsets_override,
            curve_deformer_override=curve_deformer_override,
        ))
    state = chain_stretch_state
    if state is _CHAIN_STRETCH_PREVIEW_UNSET:
        state = chain_global_stretch_preview_state(properties)
    if not state:
        return result
    try:
        source_coordinate = (
            float(state["source_start"]) + float(source_point.y) +
            float(state["half_y"])
        )
        target_point = state["local_to_target"] @ result
        if state["suffix_active"]:
            target_point = apply_chain_global_suffix(
                target_point,
                source_coordinate,
                deform_mask=state["suffix_mask"],
                twist=state["suffix_twist"],
                taper=state["suffix_taper"],
                stretch=state["factor"],
                shear=state["suffix_shear"],
                pre_shear_mask=state["suffix_pre_shear_mask"],
                post_shear_mask=state["suffix_post_shear_mask"],
                center=state["center"],
                rotation=state["rotation"],
                source_offset=state["source_offset"],
                length=state["length"],
                origin=state["origin"],
                preserve_volume=state["preserve_volume"],
            )
        else:
            target_point = apply_chain_global_stretch(
                target_point,
                source_coordinate,
                factor=state["factor"],
                center=state["center"],
                rotation=state["rotation"],
                source_offset=state["source_offset"],
                length=state["length"],
                origin=state["origin"],
                preserve_volume=state["preserve_volume"],
            )
        return state["target_to_local"] @ target_point
    except (
            AttributeError, KeyError, RuntimeError, TypeError, ValueError,
            OverflowError,
    ):
        return result


def _managed_chain_mode(controller, modifier=None):
    """Return the persisted chain mode for a controller, if it has one."""
    if controller is None or not is_cage_controller(controller):
        return ""
    if modifier is None:
        target = find_target(controller)
        modifier = find_modifier(target, controller)
    group = getattr(modifier, "node_group", None) if modifier else None

    # A stage's relationship is mirrored on the node group and controller.
    # Node-group replacement (for example when reordering deformation layers)
    # can briefly leave the controller copy as the only surviving owner.  Do
    # not silently drop the chain lock during that interval: doing so sends an
    # empty domain name to Geometry Nodes and makes later stages appear to
    # affect only their visible cage.  Prefer a complete pair from one owner,
    # then fall back to the other mirrored owners for older files.
    owners = tuple(owner for owner in (group, modifier, controller) if owner is not None)
    chain_uuid = ""
    mode = ""
    for owner in owners:
        try:
            candidate_uuid = str(owner.get(CHAIN_UUID_PROP, "") or "")
            candidate_mode = str(owner.get(CHAIN_MODE_PROP, "") or "").upper()
        except (AttributeError, ReferenceError, TypeError):
            continue
        if candidate_uuid and candidate_mode in {"CHAINED", "CONNECTED"}:
            chain_uuid = candidate_uuid
            mode = candidate_mode
            break
        if candidate_uuid and not chain_uuid:
            chain_uuid = candidate_uuid
        if candidate_mode in {"CHAINED", "CONNECTED"} and not mode:
            mode = candidate_mode
    if not chain_uuid or not mode:
        return ""
    # CONNECTED was the spelling used by the first chain prototype. Treat it
    # as the same locked one-sided mode for files upgraded from that version.
    return mode if mode in {"CHAINED", "CONNECTED"} else ""


def _is_non_root_chain_stage(properties):
    """Return whether ``properties`` belongs to a downstream chain stage."""
    controller = getattr(properties, "id_data", None)
    if not is_cage_controller(controller):
        return False
    target = find_target(controller)
    modifier = find_modifier(target, controller)
    if (
            target is None or modifier is None or
            _managed_chain_mode(controller, modifier) not in
            {"CHAINED", "CONNECTED"}
    ):
        return False
    try:
        from . import chain as chain_module
        return chain_module.stage_chain_index(modifier, 0) > 0
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError,
            ValueError):
        return False


def _identity_chain_input_frame(half_y=0.0):
    return (
        Vector((0.0, -abs(float(half_y)), 0.0)),
        Vector((1.0, 0.0, 0.0)),
        Vector((0.0, 1.0, 0.0)),
        Vector((0.0, 0.0, 1.0)),
    )


def _identity_chain_output_frame():
    return _identity_chain_input_frame(0.0)


def _finite_affine(matrix):
    try:
        linear = matrix.to_3x3()
        return (
            all(math.isfinite(float(value)) for row in matrix for value in row) and
            abs(float(linear.determinant())) > EPSILON
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _stored_chain_root_output_affine(owner):
    """Read one valid affine mirror, returning ``None`` when unavailable."""
    if owner is None:
        return None
    try:
        values = tuple(float(value) for value in owner.get(
            CHAIN_ROOT_OUTPUT_AFFINE_PROP, ()))
        if len(values) != 16:
            return None
        matrix = Matrix(tuple(
            values[index:index + 4] for index in range(0, 16, 4)))
    except (
            AttributeError, ReferenceError, RuntimeError, TypeError,
            ValueError,
    ):
        return None
    return matrix if _finite_affine(matrix) else None


def _chain_root_output_owners(controller, modifier=None):
    if modifier is None and controller is not None:
        target = find_target(controller)
        modifier = find_modifier(target, controller)
    group = getattr(modifier, "node_group", None) if modifier else None
    return tuple(
        owner for owner in (group, modifier, controller) if owner is not None)


def chain_root_output_affine(controller, modifier=None):
    """Return the persisted root-stage output frame, or identity."""
    for owner in _chain_root_output_owners(controller, modifier):
        matrix = _stored_chain_root_output_affine(owner)
        if matrix is not None:
            return matrix
    return Matrix.Identity(4)


def chain_root_output_active(controller, modifier=None):
    """Return whether a root stage carries a non-identity output frame."""
    matrix = chain_root_output_affine(controller, modifier)
    return any(
        abs(float(matrix[row][column]) - float(row == column)) > EPSILON
        for row in range(4)
        for column in range(4)
    )


def set_chain_root_output_affine(controller, modifier=None, matrix=None):
    """Persist a finite root output frame on every supported metadata owner."""
    # Keep the original two-argument form convenient for internal callers:
    # ``set_chain_root_output_affine(controller, matrix)``.
    if (
            matrix is None and modifier is not None and
            not hasattr(modifier, "node_group")
    ):
        matrix = modifier
        modifier = None
    try:
        candidate = (
            Matrix.Identity(4) if matrix is None else Matrix(matrix))
        if len(candidate) != 4 or any(len(row) != 4 for row in candidate):
            return False
        if not _finite_affine(candidate):
            return False
    except (
            AttributeError, ReferenceError, RuntimeError, TypeError,
            ValueError,
    ):
        return False

    owners = _chain_root_output_owners(controller, modifier)
    if not owners:
        return False
    previous = chain_root_output_affine(controller, modifier)
    changed = any(
        abs(float(previous[row][column]) - float(candidate[row][column])) >
        EPSILON
        for row in range(4)
        for column in range(4)
    )
    is_identity = all(
        abs(float(candidate[row][column]) - float(row == column)) <= EPSILON
        for row in range(4)
        for column in range(4)
    )
    serialized = [float(value) for row in candidate for value in row]
    wrote_owner = False
    for owner in owners:
        stored = _stored_chain_root_output_affine(owner)
        mirror_matches = stored is not None and all(
            abs(float(stored[row][column]) - float(candidate[row][column])) <=
            EPSILON
            for row in range(4)
            for column in range(4)
        )
        try:
            if is_identity:
                if CHAIN_ROOT_OUTPUT_AFFINE_PROP in owner:
                    del owner[CHAIN_ROOT_OUTPUT_AFFINE_PROP]
                    changed = True
                wrote_owner = True
            else:
                owner[CHAIN_ROOT_OUTPUT_AFFINE_PROP] = serialized
                changed = changed or not mirror_matches
                wrote_owner = True
        except (
                AttributeError, KeyError, ReferenceError, RuntimeError,
                TypeError, ValueError,
        ):
            continue
    if not wrote_owner:
        return False

    if changed:
        target = find_target(controller)
        invalidate_chain_affine_cache(target)
        invalidate_chain_domain_cache()
        for owner in (controller, target):
            if owner is None:
                continue
            try:
                owner.update_tag()
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                pass
    return changed


def _sample_chain_affine(
        function, bottom_y, half_y, *, sample_fraction=0.01,
        linear_cross_section=False):
    """Sample a full affine section frame, retaining scale and shear.

    The one-sided axial sample stays inside the authored cage. A wider step
    keeps its tangent above Geometry Nodes' single-precision quantization;
    this matters because frame sockets are stored as float32 and errors can
    compound through downstream chain stages.
    """
    authored = Vector((0.0, float(bottom_y), 0.0))
    center = Vector(function(authored))
    if linear_cross_section:
        # Standard chain deformations are affine across a fixed section, so a
        # one-sided sample is exact and avoids two redundant evaluations. FFD
        # keeps the central difference because its trilinear cross terms can
        # make the one-sided derivative asymmetric.
        basis_x = Vector(
            function(authored + Vector((1.0, 0.0, 0.0)))) - center
        basis_z = Vector(
            function(authored + Vector((0.0, 0.0, 1.0)))) - center
    else:
        basis_x = (
            Vector(function(authored + Vector((1.0, 0.0, 0.0)))) -
            Vector(function(authored - Vector((1.0, 0.0, 0.0))))
        ) * 0.5
        basis_z = (
            Vector(function(authored + Vector((0.0, 0.0, 1.0)))) -
            Vector(function(authored - Vector((0.0, 0.0, 1.0))))
        ) * 0.5
    try:
        sample_fraction = min(max(float(sample_fraction), 1.0e-4), 0.05)
    except (TypeError, ValueError):
        sample_fraction = 0.01
    delta_y = max(
        min(abs(float(half_y)) * sample_fraction, sample_fraction), EPSILON)
    basis_y = (
        Vector(function(authored + Vector((0.0, delta_y, 0.0)))) - center
    ) / delta_y
    linear = Matrix((
        (basis_x.x, basis_y.x, basis_z.x),
        (basis_x.y, basis_y.y, basis_z.y),
        (basis_x.z, basis_y.z, basis_z.z),
    ))
    affine = linear.to_4x4()
    affine.translation = center - linear @ authored
    if not _finite_affine(affine):
        raise ValueError("singular chain boundary frame")
    return affine


def _sample_chain_section_affine(function, bottom_y):
    """Sample a boundary section without absorbing its axial derivative.

    A pure Shear is affine over the whole stage.  Using its full Jacobian as
    ``B_current`` would therefore cancel the stage completely in the chained
    conjugation.  The section frame keeps the mapped lower face (position,
    X, and Z) while extending it along the face normal, so the lower seam is
    normalized without removing the authored Shear slope.
    """
    authored = Vector((0.0, float(bottom_y), 0.0))
    center = Vector(function(authored))
    basis_x = Vector(
        function(authored + Vector((1.0, 0.0, 0.0)))) - center
    basis_z = Vector(
        function(authored + Vector((0.0, 0.0, 1.0)))) - center
    basis_y = basis_z.cross(basis_x)
    if basis_y.length <= EPSILON:
        raise ValueError("singular chain section frame")
    basis_y.normalize()
    linear = Matrix((
        (basis_x.x, basis_y.x, basis_z.x),
        (basis_x.y, basis_y.y, basis_z.y),
        (basis_x.z, basis_y.z, basis_z.z),
    ))
    affine = linear.to_4x4()
    affine.translation = center - linear @ authored
    if not _finite_affine(affine):
        raise ValueError("singular chain section frame")
    return affine


def _raw_chain_deform(
        point, properties, *, profile_after_end=False,
        profile_gap_distance=0.0, chain_source_coordinate=None,
        chain_source_start=None, chain_output_frame=None,
        operation_order_override=None):
    return Vector(deform_point_from_properties(
        point, properties, evaluator=True, chain_eligible=True,
        apply_chain_input_offset=False,
        chain_preview=chain_output_frame is not None,
        chain_frame_sampling=True,
        preview_output_frame=chain_output_frame,
        chain_profile_after_end=profile_after_end,
        chain_profile_gap_distance=profile_gap_distance,
        chain_source_coordinate=chain_source_coordinate,
        chain_source_start=chain_source_start,
        operation_order_override=operation_order_override,
        ignore_chain_stage_profile=True))


def _chain_input_tuple(affine, half_y):
    inverse = affine.to_3x3().inverted()
    pivot = affine @ Vector((0.0, -float(half_y), 0.0))
    return (
        Vector(pivot),
        Vector(inverse[0]),
        Vector(inverse[1]),
        Vector(inverse[2]),
    )


def _chain_output_tuple(affine):
    linear = affine.to_3x3()
    return (
        Vector(affine.translation),
        Vector(linear[0]),
        Vector(linear[1]),
        Vector(linear[2]),
    )


def _chain_input_affine(frame, half_y):
    pivot, inverse_x, inverse_y, inverse_z = (
        Vector(value) for value in frame)
    inverse = Matrix((inverse_x, inverse_y, inverse_z))
    linear = inverse.inverted()
    affine = linear.to_4x4()
    affine.translation = (
        pivot - linear @ Vector((0.0, -float(half_y), 0.0)))
    return affine


def _chain_output_affine(frame):
    offset, row_x, row_y, row_z = (Vector(value) for value in frame)
    affine = Matrix((row_x, row_y, row_z)).to_4x4()
    affine.translation = offset
    return affine


def chain_conjugation_frames_for_controller(
        controller, modifier=None, properties=None):
    """Return the persisted root output or downstream conjugation frames.

    A previous stage can deliver a scaled or sheared section that an Empty's
    rotation cannot represent.  For a downstream authored deformation ``F``,
    evaluate ``B_in * inverse(B_current) * F * inverse(B_in)``.  This makes
    the physical lower section an exact identity while preserving the full
    incoming section frame for Bend, Twist, Taper, Stretch, and mixed origins.
    """
    if properties is None:
        properties = getattr(controller, "sdh_cage_deform", None)
    try:
        identity_half_y = max(
            abs(float(properties.size[1])) * 0.5, EPSILON)
    except (AttributeError, TypeError, ValueError):
        identity_half_y = 0.0
    identity = (
        _identity_chain_input_frame(identity_half_y),
        _identity_chain_output_frame(),
    )
    if properties is None or str(getattr(properties, "mode", "")) != "CHAINED":
        return identity
    if not is_cage_controller(controller):
        return identity
    target = find_target(controller)
    if modifier is None:
        modifier = find_modifier(target, controller)
    if (
            target is None or modifier is None or
            _managed_chain_mode(controller, modifier) not in
            {"CHAINED", "CONNECTED"}
    ):
        return identity
    try:
        from . import chain as chain_module
        chain_uuid = chain_module.stage_chain_uuid(modifier)
        stages = tuple(chain_module.chain_stages(target, chain_uuid))
        stage_index = stages.index(modifier)
        if stage_index == 0:
            return (
                identity[0],
                _chain_output_tuple(chain_root_output_affine(
                    controller, modifier)),
            )
        controllers = tuple(
            find_controller(target, stage) for stage in stages[:stage_index + 1])
        if any(item is None for item in controllers):
            return identity
        matrices = tuple(
            chain_module._stage_local_matrix(target, item)
            for item in controllers)
        inverses = tuple(matrix.inverted_safe() for matrix in matrices)
        source_starts = tuple(float(
            _chain_domain_input_values(item, stage)["Chain Source Start"])
            for item, stage in zip(controllers, stages))
        source_ends = tuple(float(
            _chain_domain_input_values(item, stage)["Chain Source End"])
            for item, stage in zip(controllers, stages))

        # A mixed Bend -> Stretch subdivision evaluates Stretch once at the
        # chain tip.  The affine frame sampler must use the same per-stage
        # operation sequence as Geometry Nodes; retaining Stretch here would
        # make downstream controller frames contain a second axial scale.
        stage_orders = []
        stage_global_modes = []
        stage_tail_values = []
        for item, stage in zip(controllers, stages):
            item_properties = item.sdh_cage_deform
            active = set(active_deform_types(item_properties) or ())
            authored_order = tuple(
                name for name in ordered_deform_types(item_properties)
                if name in active)
            domain = _chain_domain_input_values(item, stage)
            global_active = bool(
                domain.get("Chain Global Stretch Active", False))
            stage_orders.append(tuple(
                name for name in authored_order
                if not (global_active and name == "STRETCH")))
            stage_global_modes.append(global_active)
            baseline_mask = int(domain.get("Chain Global Baseline Types", 0))

            def baseline_value(bit, property_name, domain_name):
                value = float(getattr(item_properties, property_name, 0.0))
                if baseline_mask & DEFORM_BITS[bit]:
                    try:
                        value -= float(domain.get(domain_name, 0.0))
                    except (TypeError, ValueError, OverflowError):
                        pass
                return value

            shear = tuple(getattr(
                item_properties, "shear_factors", (0.0, 0.0)))
            try:
                shear = tuple(float(value) for value in shear)
            except (TypeError, ValueError, OverflowError):
                shear = (0.0, 0.0)
            shear_x = shear[0] if shear else 0.0
            shear_z = shear[1] if len(shear) > 1 else 0.0
            if baseline_mask & DEFORM_BITS["SHEAR"]:
                base_shear = domain.get(
                    "Chain Prefix Base Shear", (0.0, 0.0, 0.0))
                try:
                    base_shear = tuple(float(value) for value in base_shear)
                except (TypeError, ValueError, OverflowError):
                    base_shear = (0.0, 0.0, 0.0)
                shear_x -= base_shear[0] if base_shear else 0.0
                shear_z -= (
                    base_shear[2] if len(base_shear) > 2 else
                    base_shear[1] if len(base_shear) > 1 else 0.0)
            stage_tail_values.append({
                "twist_strength": baseline_value(
                    "TWIST", "twist_strength", "Chain Prefix Base Twist"),
                "taper_factor": baseline_value(
                    "TAPER", "taper_factor", "Chain Prefix Base Taper"),
                "stretch_factor": baseline_value(
                    "STRETCH", "stretch_factor", "Chain Prefix Base Stretch"),
                "shear_factors": (shear_x, shear_z),
            })
        stage_orders = tuple(stage_orders)
        stage_global_modes = tuple(stage_global_modes)
        stage_tail_values = tuple(stage_tail_values)

        def floats(values):
            return tuple(float(value).hex() for value in values)

        state = []
        for item, stage, matrix, source_start in zip(
                controllers, stages, matrices, source_starts):
            item_properties = item.sdh_cage_deform
            state.append((
                _pointer(item),
                tuple(float(value).hex() for row in matrix for value in row),
                floats(item_properties.size),
                tuple(ordered_deform_types(item_properties)),
                tuple(sorted(active_deform_types(item_properties))),
                float(item_properties.bend_strength).hex(),
                float(item_properties.bend_direction).hex(),
                float(item_properties.twist_strength).hex(),
                float(item_properties.taper_factor).hex(),
                float(item_properties.stretch_factor).hex(),
                floats(item_properties.shear_factors),
                str(item_properties.mode),
                str(item_properties.origin),
                bool(item_properties.preserve_volume),
                bool(item_properties.stage_enabled),
                floats(item_properties.top_scale),
                floats(item_properties.bottom_scale),
                floats(item_properties.top_offset),
                floats(item_properties.bottom_offset),
                tuple(stage_orders[len(state)]),
                bool(stage_global_modes[len(state)]),
                tuple(
                    (key, float(value).hex())
                    for key, value in sorted(
                        stage_tail_values[len(state)].items()
                    )
                    if key != "shear_factors"
                ),
                tuple(
                    float(value).hex()
                    for value in stage_tail_values[len(state)][
                        "shear_factors"]
                ),
                float(source_start).hex(),
                float(source_ends[len(state)]).hex(),
                bool(getattr(stage, "show_viewport", True)),
                floats(
                    value
                    for row in chain_root_output_affine(item, stage)
                    for value in row
                ),
            ))
        target_pointer = _pointer(target)
        cache_keys = tuple(
            (target_pointer, _pointer(stages[index]), tuple(state[:index + 1]))
            for index in range(stage_index + 1)
        )
        cache_key = cache_keys[stage_index]
        cached = _CHAIN_AFFINE_FRAME_CACHE.get(cache_key)
        if cached is not None:
            return tuple(
                tuple(Vector(value) for value in frame)
                for frame in cached)

        if len(_CHAIN_AFFINE_FRAME_CACHE) >= 128:
            _CHAIN_AFFINE_FRAME_CACHE.clear()
        incoming_affines = [Matrix.Identity(4)] * (stage_index + 1)
        output_affines = [Matrix.Identity(4)] * (stage_index + 1)
        output_affines[0] = chain_root_output_affine(
            controllers[0], stages[0])

        def frame_sample_fraction(_item):
            """Sample above float32 noise without crossing cage curvature."""
            return 0.0015

        for index in range(1, stage_index + 1):
            current_properties = controllers[index].sdh_cage_deform
            half_y = max(
                abs(float(current_properties.size[1])) * 0.5, EPSILON)
            bottom_y = -half_y
            cached_stage = _CHAIN_AFFINE_FRAME_CACHE.get(cache_keys[index])
            if cached_stage is not None:
                incoming_affines[index] = _chain_input_affine(
                    cached_stage[0], half_y)
                output_affines[index] = _chain_output_affine(
                    cached_stage[1])
                continue

            def incoming(local_authored, current=index, half=half_y):
                local_authored = Vector(local_authored)
                source = local_authored.copy()
                source.y = (
                    source_starts[current] + local_authored.y + half)
                result = matrices[0] @ source
                for prior in range(current):
                    # Build the incoming frame from the upstream terminal
                    # continuation.  The evaluated modifier stack stops a
                    # non-tip stage at ``source_end``; the next stage still
                    # needs the preceding stage's tangent and cross-section
                    # at that seam.  Continuing the reference stage while
                    # sampling avoids a finite-difference discontinuity at
                    # the owned/unowned boundary.
                    local = inverses[prior] @ result
                    if prior > 0:
                        local = incoming_affines[prior].inverted_safe() @ local
                    prior_properties = controllers[prior].sdh_cage_deform
                    prior_length = max(
                        abs(float(prior_properties.size[1])), EPSILON)
                    prior_gap = max(
                        source_ends[prior] -
                        (source_starts[prior] + prior_length),
                        0.0,
                    )
                    deformed = _raw_chain_deform(
                        local,
                        prior_properties,
                        profile_gap_distance=prior_gap,
                        chain_source_coordinate=source.y,
                        chain_source_start=source_starts[prior],
                        chain_output_frame=_chain_output_tuple(
                            output_affines[prior]),
                        operation_order_override=stage_orders[prior],
                    )
                    result = matrices[prior] @ deformed
                return inverses[current] @ result

            current_order = stage_orders[index]
            incoming_fraction = 0.001 if any(
                frame_sample_fraction(item) <= 0.001
                for item in controllers[:index]
            ) else 0.01
            incoming_affine = (
                _sample_chain_section_affine(incoming, bottom_y)
                if current_order == ("SHEAR",) else
                _sample_chain_affine(
                    incoming, bottom_y, half_y,
                    sample_fraction=incoming_fraction,
                    linear_cross_section=not any(
                        "FFD" in order for order in stage_orders[:index]),
                )
            )
            if "BEND" in current_order:
                pre_order = current_order[:current_order.index("BEND") + 1]
            else:
                pre_order = current_order

            def current_deform(value, *, order=None):
                return _raw_chain_deform(
                    value,
                    current_properties,
                    chain_source_coordinate=float(source_starts[index]) +
                    float(Vector(value).y) + float(half_y),
                    chain_source_start=source_starts[index],
                    operation_order_override=order,
                )

            current_affine = (
                _sample_chain_section_affine(current_deform, bottom_y)
                if current_order == ("SHEAR",) else
                _sample_chain_affine(
                    current_deform,
                    bottom_y,
                    half_y,
                    sample_fraction=frame_sample_fraction(
                        controllers[index]),
                    linear_cross_section="FFD" not in current_order,
                )
            )
            pre_affine = (
                current_affine
                if pre_order == current_order else
                _sample_chain_affine(
                    lambda value: current_deform(value, order=pre_order),
                    bottom_y,
                    half_y,
                    sample_fraction=frame_sample_fraction(
                        controllers[index]),
                    linear_cross_section="FFD" not in pre_order,
                )
            )
            if "BEND" in current_order:
                # The full boundary Jacobian contains Twist/Taper profile
                # derivatives.  Those derivatives are supplied by the
                # current stage itself and must not become permanent shear in
                # the seam frame.  Factor only the fixed-profile value tail,
                # matching the root subdivision alignment.
                post_affine = chain_module._tail_value_affine(
                    current_properties,
                    "BOTTOM",
                    current_order,
                    value_overrides=stage_tail_values[index],
                )
            else:
                post_affine = current_affine @ pre_affine.inverted()
            output_affine = (
                post_affine.inverted() @ incoming_affine @
                pre_affine.inverted())
            if not _finite_affine(output_affine):
                return identity
            incoming_affines[index] = incoming_affine
            output_affines[index] = output_affine
            stage_result = (
                _chain_input_tuple(incoming_affine, half_y),
                _chain_output_tuple(output_affine),
            )
            _CHAIN_AFFINE_FRAME_CACHE[cache_keys[index]] = tuple(
                tuple(tuple(value) for value in frame)
                for frame in stage_result)

        half_y = max(abs(float(properties.size[1])) * 0.5, EPSILON)
        result = (
            _chain_input_tuple(incoming_affines[stage_index], half_y),
            _chain_output_tuple(output_affines[stage_index]),
        )
        return result
    except (
            AttributeError, ImportError, IndexError, KeyError, ReferenceError,
            RuntimeError, TypeError, ValueError,
    ):
        return identity


def precompute_chain_conjugation_frames(controllers, modifiers):
    """Resolve every chain frame once after all controller transforms settle.

    The tip request builds and caches every prefix. Walking the remaining
    stages in reverse then performs cache hits, and callers can pass the
    resulting frames into ``sync_controller`` without repeating chain scans
    during the same reconnect transaction.
    """
    pairs = tuple(zip(tuple(controllers), tuple(modifiers)))
    frames = {}
    for controller, modifier in reversed(pairs):
        if controller is None or modifier is None:
            continue
        frames[_pointer(controller)] = chain_conjugation_frames_for_controller(
            controller, modifier, controller.sdh_cage_deform)
    return frames


def sync_chain_runtime_inputs(target, modifier, controller, frames):
    """Write only the downstream inputs changed by a live chain reconnect."""
    if target is None or modifier is None or controller is None or frames is None:
        return False
    properties = getattr(controller, "sdh_cage_deform", None)
    if properties is None:
        return False
    input_frame, output_frame = frames
    values = {
        "Center": tuple(controller.location),
        "Rotation": tuple(_controller_rotation_xyz(controller)),
        "Size": tuple(properties.size),
        "Mode": MODE_VALUES["CHAINED"],
        **_chain_domain_input_values(controller, modifier),
    }
    values.update(dict(zip(
        (
            "Chain Input Pivot", "Chain Input Inverse X",
            "Chain Input Inverse Y", "Chain Input Inverse Z",
            "Chain Output Offset", "Chain Output X",
            "Chain Output Y", "Chain Output Z",
        ),
        (*input_frame, *output_frame),
    )))

    def different(old, value):
        if isinstance(value, str) or isinstance(old, str):
            return str(old or "") != str(value)
        if isinstance(value, bool) or isinstance(old, bool):
            return old is None or bool(old) != bool(value)

        def numeric_sequence(item):
            if item is None or isinstance(item, (str, bytes)):
                return None
            try:
                return tuple(item)
            except (TypeError, ValueError):
                return None

        value_tuple = numeric_sequence(value)
        old_tuple = numeric_sequence(old)
        if value_tuple is not None:
            if old_tuple is None:
                return True
            return len(old_tuple) != len(value_tuple) or any(
                abs(float(first) - float(second)) > EPSILON
                for first, second in zip(old_tuple, value_tuple))
        if old_tuple is not None:
            return True
        return old is None or abs(float(old) - float(value)) > EPSILON

    changed = False
    for name, value in values.items():
        if modifier_input_identifier(modifier, name) is None:
            continue
        old = modifier_input(modifier, name)
        if different(old, value):
            set_modifier_input(modifier, name, value)
            changed = True
    pointer = _pointer(controller)
    if pointer:
        _CONTROLLER_TRANSFORM_SNAPSHOTS[pointer] = (
            _controller_transform_signature(controller))
    if changed:
        try:
            target.update_tag()
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
    return changed


def chain_input_frame_for_controller(controller, modifier=None, properties=None):
    """Return ``B_in`` as a pivot plus inverse-basis rows."""
    return chain_conjugation_frames_for_controller(
        controller, modifier, properties)[0]


def chain_output_frame_for_controller(controller, modifier=None, properties=None):
    """Return ``B_in * inverse(B_current)`` as offset plus basis rows."""
    return chain_conjugation_frames_for_controller(
        controller, modifier, properties)[1]


def chain_input_offset_for_controller(controller, modifier=None, properties=None):
    """Compatibility helper returning only the lower-boundary translation."""
    frame = chain_input_frame_for_controller(controller, modifier, properties)
    if properties is None:
        properties = getattr(controller, "sdh_cage_deform", None)
    try:
        half_y = max(abs(float(properties.size[1])) * 0.5, EPSILON)
    except (AttributeError, TypeError, ValueError):
        return Vector((0.0, 0.0, 0.0))
    return Vector(frame[0]) - Vector((0.0, -half_y, 0.0))


def chain_input_point_from_properties(point, properties):
    """Map one raw local point into a downstream chain stage's input frame."""
    raw = Vector(point)
    if (
            str(getattr(properties, "mode", "")) != "CHAINED" or
            not _is_non_root_chain_stage(properties)
    ):
        return raw
    controller = getattr(properties, "id_data", None)
    target = find_target(controller)
    modifier = find_modifier(target, controller)
    frame = chain_input_frame_for_controller(
        controller, modifier, properties)
    try:
        half_y = max(abs(float(properties.size[1])) * 0.5, EPSILON)
        delta = raw - Vector(frame[0])
        return Vector((
            delta.dot(Vector(frame[1])),
            delta.dot(Vector(frame[2])) - half_y,
            delta.dot(Vector(frame[3])),
        ))
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return raw


def _chain_domain_input_values(controller, modifier):
    """Return hidden GN inputs that carry stable point ownership down a chain."""
    cache_key = (_pointer(controller), _pointer(modifier))
    cache_version = _CHAIN_DOMAIN_INPUT_CACHE_VERSION
    if cache_key != (0, 0):
        cached = _CHAIN_DOMAIN_INPUT_CACHE.get(cache_key)
        if cached is not None and cached[0] == cache_version:
            return cached[1]

    def finish(values):
        if cache_key != (0, 0):
            _CHAIN_DOMAIN_INPUT_CACHE[cache_key] = (cache_version, values)
        return values

    group = getattr(modifier, "node_group", None) if modifier else None
    # Keep this lookup in lockstep with ``_managed_chain_mode``.  A rebuilt or
    # copied node group may have lost custom ID properties while its controller
    # still carries the authoritative chain mirror.  Falling back here avoids
    # clearing the point-domain token on every stage during that transition.
    owners = tuple(owner for owner in (group, modifier, controller) if owner is not None)
    chain_uuid = ""
    mode = ""
    for owner in owners:
        try:
            candidate_uuid = str(owner.get(CHAIN_UUID_PROP, "") or "")
            candidate_mode = str(owner.get(CHAIN_MODE_PROP, "") or "").upper()
        except (AttributeError, ReferenceError, TypeError):
            continue
        if candidate_uuid and candidate_mode in {"CHAINED", "CONNECTED"}:
            chain_uuid = candidate_uuid
            mode = candidate_mode
            break
        if candidate_uuid and not chain_uuid:
            chain_uuid = candidate_uuid
        if candidate_mode in {"CHAINED", "CONNECTED"} and not mode:
            mode = candidate_mode
    if not chain_uuid or mode not in {"CHAINED", "CONNECTED"}:
        try:
            source_start = -abs(
                float(controller.sdh_cage_deform.size[1])) * 0.5
        except (AttributeError, ReferenceError, TypeError, ValueError):
            source_start = 0.0
        return finish({
            "Chain Domain Attribute": "",
            "Chain Root Stage": True,
            "Chain Tip Stage": True,
            "Chain Source Start": source_start,
            "Chain Source End": 1.0e20,
            "Chain Root Output Active": False,
            "Chain Global Stretch Active": False,
            "Chain Global Stretch Factor": 0.0,
            "Chain Global Stretch Center": (0.0, 0.0, 0.0),
            "Chain Global Stretch Rotation": (0.0, 0.0, 0.0),
            "Chain Global Stretch Source Offset": 0.0,
            "Chain Global Stretch Length": 2.0,
            "Chain Global Stretch Origin": ORIGIN_VALUES["BOTTOM"],
            "Chain Global Prefix Active": False,
            "Chain Global Prefix Types": 0,
            "Chain Global Baseline Types": 0,
            "Chain Global Prefix Pre Shear Types": 0,
            "Chain Global Prefix Post Shear Types": 0,
            "Chain Global Prefix Shear": (0.0, 0.0, 0.0),
            "Chain Global Prefix Bend": 0.0,
            "Chain Global Prefix Direction": 0.0,
            "Chain Global Prefix Twist": 0.0,
            "Chain Global Prefix Taper": 0.0,
            "Chain Global Prefix Stretch": 0.0,
            "Chain Global Prefix Center": (0.0, 0.0, 0.0),
            "Chain Global Prefix Rotation": (0.0, 0.0, 0.0),
            "Chain Global Prefix Source Offset": 0.0,
            "Chain Global Prefix Length": 2.0,
            "Chain Global Prefix Origin": ORIGIN_VALUES["BOTTOM"],
            "Chain Global Suffix Active": False,
            "Chain Global Suffix Types": 0,
            "Chain Global Suffix Pre Shear Types": 0,
            "Chain Global Suffix Post Shear Types": 0,
            "Chain Global Suffix Twist": 0.0,
            "Chain Global Suffix Taper": 0.0,
            "Chain Global Suffix Shear": (0.0, 0.0, 0.0),
            "Chain Global Profile Active": False,
            "Chain Global Profile Bottom Scale": (1.0, 1.0, 1.0),
            "Chain Global Profile Top Scale": (1.0, 1.0, 1.0),
            "Chain Global Profile Bottom Offset": (0.0, 0.0, 0.0),
            "Chain Global Profile Top Offset": (0.0, 0.0, 0.0),
            "Chain Prefix Base Bend": 0.0,
            "Chain Prefix Base Twist": 0.0,
            "Chain Prefix Base Taper": 0.0,
            "Chain Prefix Base Stretch": 0.0,
            "Chain Prefix Base Shear": (0.0, 0.0, 0.0),
        })
    index = 0
    count = 1
    # Index/count are mirrored independently, so read each from the first
    # owner that actually contains a valid value instead of assuming that the
    # owner which supplied the mode also has every field.
    for key, fallback in ((CHAIN_INDEX_PROP, 0), (CHAIN_COUNT_PROP, 1)):
        value = None
        for owner in owners:
            try:
                candidate = owner.get(key, None)
            except (AttributeError, ReferenceError, TypeError):
                candidate = None
            if candidate not in (None, ""):
                value = candidate
                break
        try:
            parsed = int(value) if value is not None else fallback
        except (TypeError, ValueError):
            parsed = fallback
        if key == CHAIN_INDEX_PROP:
            index = parsed
        else:
            count = parsed
    token = "".join(character for character in chain_uuid if character.isalnum())
    count = max(count, index + 1, 1)
    global_stretch_active = False
    global_stretch_factor = 0.0
    global_stretch_center = (0.0, 0.0, 0.0)
    global_stretch_rotation = (0.0, 0.0, 0.0)
    global_stretch_offset = 0.0
    global_stretch_length = 2.0
    global_stretch_origin = ORIGIN_VALUES["BOTTOM"]
    global_prefix_active = False
    global_prefix_mask = 0
    global_baseline_mask = 0
    global_prefix_pre_shear_mask = 0
    global_prefix_post_shear_mask = 0
    global_prefix_shear = (0.0, 0.0, 0.0)
    global_prefix_bend = 0.0
    global_prefix_direction = 0.0
    global_prefix_twist = 0.0
    global_prefix_taper = 0.0
    global_prefix_stretch = 0.0
    global_prefix_center = (0.0, 0.0, 0.0)
    global_prefix_rotation = (0.0, 0.0, 0.0)
    global_prefix_offset = 0.0
    global_prefix_length = 2.0
    global_prefix_origin = ORIGIN_VALUES["BOTTOM"]
    global_suffix_active = False
    global_suffix_mask = 0
    global_suffix_pre_shear_mask = 0
    global_suffix_post_shear_mask = 0
    global_suffix_twist = 0.0
    global_suffix_taper = 0.0
    global_suffix_shear = (0.0, 0.0, 0.0)
    global_profile_active = False
    global_profile_bottom_scale = (1.0, 1.0, 1.0)
    global_profile_top_scale = (1.0, 1.0, 1.0)
    global_profile_bottom_offset = (0.0, 0.0, 0.0)
    global_profile_top_offset = (0.0, 0.0, 0.0)
    prefix_base_bend = 0.0
    prefix_base_twist = 0.0
    prefix_base_taper = 0.0
    prefix_base_stretch = 0.0
    prefix_base_shear = (0.0, 0.0, 0.0)
    try:
        from . import chain as chain_module
        global_keys = (
            ("CHAIN_GLOBAL_STRETCH_ACTIVE", False),
            ("CHAIN_GLOBAL_STRETCH_FACTOR", 0.0),
            ("CHAIN_GLOBAL_STRETCH_CENTER", (0.0, 0.0, 0.0)),
            ("CHAIN_GLOBAL_STRETCH_ROTATION", (0.0, 0.0, 0.0)),
            ("CHAIN_GLOBAL_STRETCH_OFFSET", 0.0),
            ("CHAIN_GLOBAL_STRETCH_LENGTH", 2.0),
            ("CHAIN_GLOBAL_STRETCH_ORIGIN", "BOTTOM"),
            ("CHAIN_GLOBAL_PREFIX_ACTIVE", False),
            ("CHAIN_GLOBAL_PREFIX_MASK", 0),
            ("CHAIN_GLOBAL_BASELINE_MASK", 0),
            ("CHAIN_GLOBAL_PREFIX_PRE_SHEAR_MASK", 0),
            ("CHAIN_GLOBAL_PREFIX_POST_SHEAR_MASK", 0),
            ("CHAIN_GLOBAL_PREFIX_SHEAR", (0.0, 0.0, 0.0)),
            ("CHAIN_GLOBAL_PREFIX_BEND", 0.0),
            ("CHAIN_GLOBAL_PREFIX_DIRECTION", 0.0),
            ("CHAIN_GLOBAL_PREFIX_TWIST", 0.0),
            ("CHAIN_GLOBAL_PREFIX_TAPER", 0.0),
            ("CHAIN_GLOBAL_PREFIX_STRETCH", 0.0),
            ("CHAIN_GLOBAL_PREFIX_CENTER", (0.0, 0.0, 0.0)),
            ("CHAIN_GLOBAL_PREFIX_ROTATION", (0.0, 0.0, 0.0)),
            ("CHAIN_GLOBAL_PREFIX_OFFSET", 0.0),
            ("CHAIN_GLOBAL_PREFIX_LENGTH", 2.0),
            ("CHAIN_GLOBAL_PREFIX_ORIGIN", "BOTTOM"),
            ("CHAIN_GLOBAL_SUFFIX_ACTIVE", False),
            ("CHAIN_GLOBAL_SUFFIX_MASK", 0),
            ("CHAIN_GLOBAL_SUFFIX_PRE_SHEAR_MASK", 0),
            ("CHAIN_GLOBAL_SUFFIX_POST_SHEAR_MASK", 0),
            ("CHAIN_GLOBAL_SUFFIX_TWIST", 0.0),
            ("CHAIN_GLOBAL_SUFFIX_TAPER", 0.0),
            ("CHAIN_GLOBAL_SUFFIX_SHEAR", (0.0, 0.0, 0.0)),
            ("CHAIN_GLOBAL_PROFILE_ACTIVE", False),
            ("CHAIN_GLOBAL_PROFILE_BOTTOM_SCALE", (1.0, 1.0, 1.0)),
            ("CHAIN_GLOBAL_PROFILE_TOP_SCALE", (1.0, 1.0, 1.0)),
            ("CHAIN_GLOBAL_PROFILE_BOTTOM_OFFSET", (0.0, 0.0, 0.0)),
            ("CHAIN_GLOBAL_PROFILE_TOP_OFFSET", (0.0, 0.0, 0.0)),
            ("CHAIN_PREFIX_BASE_BEND", 0.0),
            ("CHAIN_PREFIX_BASE_TWIST", 0.0),
            ("CHAIN_PREFIX_BASE_TAPER", 0.0),
            ("CHAIN_PREFIX_BASE_STRETCH", 0.0),
            ("CHAIN_PREFIX_BASE_SHEAR", (0.0, 0.0, 0.0)),
        )
        stored = {}
        for attribute, fallback in global_keys:
            key = getattr(chain_module, attribute)
            for owner in owners:
                try:
                    value = owner.get(key, None)
                except (AttributeError, ReferenceError, TypeError):
                    value = None
                if value is not None:
                    stored[attribute] = value
                    break
            if attribute not in stored:
                stored[attribute] = fallback
        global_stretch_active = bool(stored["CHAIN_GLOBAL_STRETCH_ACTIVE"])
        global_stretch_factor = float(stored["CHAIN_GLOBAL_STRETCH_FACTOR"])
        global_stretch_center = tuple(
            float(value) for value in stored["CHAIN_GLOBAL_STRETCH_CENTER"])
        global_stretch_rotation = tuple(
            float(value) for value in stored["CHAIN_GLOBAL_STRETCH_ROTATION"])
        global_stretch_offset = float(stored["CHAIN_GLOBAL_STRETCH_OFFSET"])
        global_stretch_length = max(
            float(stored["CHAIN_GLOBAL_STRETCH_LENGTH"]), EPSILON)
        global_stretch_origin = ORIGIN_VALUES.get(
            str(stored["CHAIN_GLOBAL_STRETCH_ORIGIN"]),
            ORIGIN_VALUES["BOTTOM"],
        )
        global_prefix_active = bool(stored["CHAIN_GLOBAL_PREFIX_ACTIVE"])
        global_prefix_mask = int(stored["CHAIN_GLOBAL_PREFIX_MASK"])
        global_baseline_mask = int(
            stored["CHAIN_GLOBAL_BASELINE_MASK"] or global_prefix_mask)
        global_prefix_pre_shear_mask = int(
            stored["CHAIN_GLOBAL_PREFIX_PRE_SHEAR_MASK"])
        global_prefix_post_shear_mask = int(
            stored["CHAIN_GLOBAL_PREFIX_POST_SHEAR_MASK"])
        global_prefix_shear = tuple(
            float(value) for value in stored["CHAIN_GLOBAL_PREFIX_SHEAR"])
        global_prefix_bend = float(stored["CHAIN_GLOBAL_PREFIX_BEND"])
        global_prefix_direction = float(
            stored["CHAIN_GLOBAL_PREFIX_DIRECTION"])
        global_prefix_twist = float(stored["CHAIN_GLOBAL_PREFIX_TWIST"])
        global_prefix_taper = float(stored["CHAIN_GLOBAL_PREFIX_TAPER"])
        global_prefix_stretch = float(stored["CHAIN_GLOBAL_PREFIX_STRETCH"])
        global_prefix_center = tuple(
            float(value) for value in stored["CHAIN_GLOBAL_PREFIX_CENTER"])
        global_prefix_rotation = tuple(
            float(value) for value in stored["CHAIN_GLOBAL_PREFIX_ROTATION"])
        global_prefix_offset = float(stored["CHAIN_GLOBAL_PREFIX_OFFSET"])
        global_prefix_length = max(
            float(stored["CHAIN_GLOBAL_PREFIX_LENGTH"]), EPSILON)
        global_prefix_origin = ORIGIN_VALUES.get(
            str(stored["CHAIN_GLOBAL_PREFIX_ORIGIN"]),
            ORIGIN_VALUES["BOTTOM"],
        )
        global_suffix_active = bool(stored["CHAIN_GLOBAL_SUFFIX_ACTIVE"])
        global_suffix_mask = int(stored["CHAIN_GLOBAL_SUFFIX_MASK"])
        global_suffix_pre_shear_mask = int(
            stored["CHAIN_GLOBAL_SUFFIX_PRE_SHEAR_MASK"])
        global_suffix_post_shear_mask = int(
            stored["CHAIN_GLOBAL_SUFFIX_POST_SHEAR_MASK"])
        global_suffix_twist = float(stored["CHAIN_GLOBAL_SUFFIX_TWIST"])
        global_suffix_taper = float(stored["CHAIN_GLOBAL_SUFFIX_TAPER"])
        global_suffix_shear = tuple(
            float(value) for value in stored["CHAIN_GLOBAL_SUFFIX_SHEAR"])
        global_profile_active = bool(stored["CHAIN_GLOBAL_PROFILE_ACTIVE"])
        global_profile_bottom_scale = tuple(
            float(value)
            for value in stored["CHAIN_GLOBAL_PROFILE_BOTTOM_SCALE"])
        global_profile_top_scale = tuple(
            float(value)
            for value in stored["CHAIN_GLOBAL_PROFILE_TOP_SCALE"])
        global_profile_bottom_offset = tuple(
            float(value)
            for value in stored["CHAIN_GLOBAL_PROFILE_BOTTOM_OFFSET"])
        global_profile_top_offset = tuple(
            float(value)
            for value in stored["CHAIN_GLOBAL_PROFILE_TOP_OFFSET"])
        prefix_base_bend = float(stored["CHAIN_PREFIX_BASE_BEND"])
        prefix_base_twist = float(stored["CHAIN_PREFIX_BASE_TWIST"])
        prefix_base_taper = float(stored["CHAIN_PREFIX_BASE_TAPER"])
        prefix_base_stretch = float(stored["CHAIN_PREFIX_BASE_STRETCH"])
        prefix_base_shear = tuple(
            float(value) for value in stored["CHAIN_PREFIX_BASE_SHEAR"])
        if not (
                global_prefix_pre_shear_mask or
                global_prefix_post_shear_mask or
                global_prefix_mask & DEFORM_BITS["SHEAR"]
        ):
            global_prefix_pre_shear_mask = (
                global_prefix_mask &
                (DEFORM_BITS["TWIST"] | DEFORM_BITS["TAPER"] |
                 DEFORM_BITS["STRETCH"])
            )
    except (AttributeError, ImportError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        from . import chain as chain_module
        target = find_target(controller)
        stages = tuple(chain_module.chain_stages(target, chain_uuid))
        if not stages:
            raise ValueError("chain has no stages")
        root_controller = find_controller(target, stages[0])
        source_start = -abs(float(
            root_controller.sdh_cage_deform.size[1])) * 0.5
        for stage_index, stage in enumerate(stages[:index]):
            stage_controller = find_controller(target, stage)
            source_start += abs(float(
                stage_controller.sdh_cage_deform.size[1]))
            next_index = stage_index + 1
            if next_index < len(stages):
                source_start += max(
                    float(chain_module.stage_chain_gap(stages[next_index])),
                    0.0,
                )
        source_end = 1.0e20
        if index + 1 < len(stages):
            next_stage = stages[index + 1]
            next_controller = find_controller(target, next_stage)
            if next_controller is None:
                raise ValueError("chain stage controller is missing")
            source_end = source_start + abs(float(
                controller.sdh_cage_deform.size[1])) + max(
                    float(chain_module.stage_chain_gap(next_stage)), 0.0)
    except (
            AttributeError, ImportError, ReferenceError, RuntimeError,
            TypeError, ValueError,
    ):
        try:
            source_start = -abs(
                float(controller.sdh_cage_deform.size[1])) * 0.5
        except (AttributeError, ReferenceError, TypeError, ValueError):
            source_start = 0.0
        source_end = 1.0e20
    return finish({
        "Chain Domain Attribute": (
            f"{CHAIN_DOMAIN_ATTRIBUTE_PREFIX}{token}" if token else ""),
        "Chain Root Stage": index <= 0,
        "Chain Tip Stage": index >= count - 1,
        "Chain Source Start": source_start,
        "Chain Source End": source_end,
        "Chain Root Output Active": (
            index <= 0 and chain_root_output_active(controller, modifier)),
        "Chain Global Stretch Active": global_stretch_active,
        "Chain Global Stretch Factor": global_stretch_factor,
        "Chain Global Stretch Center": global_stretch_center,
        "Chain Global Stretch Rotation": global_stretch_rotation,
        "Chain Global Stretch Source Offset": global_stretch_offset,
        "Chain Global Stretch Length": global_stretch_length,
        "Chain Global Stretch Origin": global_stretch_origin,
        "Chain Global Prefix Active": global_prefix_active,
        "Chain Global Prefix Types": global_prefix_mask,
        "Chain Global Baseline Types": global_baseline_mask,
        "Chain Global Prefix Pre Shear Types": (
            global_prefix_pre_shear_mask),
        "Chain Global Prefix Post Shear Types": (
            global_prefix_post_shear_mask),
        "Chain Global Prefix Shear": global_prefix_shear,
        "Chain Global Prefix Bend": global_prefix_bend,
        "Chain Global Prefix Direction": global_prefix_direction,
        "Chain Global Prefix Twist": global_prefix_twist,
        "Chain Global Prefix Taper": global_prefix_taper,
        "Chain Global Prefix Stretch": global_prefix_stretch,
        "Chain Global Prefix Center": global_prefix_center,
        "Chain Global Prefix Rotation": global_prefix_rotation,
        "Chain Global Prefix Source Offset": global_prefix_offset,
        "Chain Global Prefix Length": global_prefix_length,
        "Chain Global Prefix Origin": global_prefix_origin,
        "Chain Global Suffix Active": global_suffix_active,
        "Chain Global Suffix Types": global_suffix_mask,
        "Chain Global Suffix Pre Shear Types": (
            global_suffix_pre_shear_mask),
        "Chain Global Suffix Post Shear Types": (
            global_suffix_post_shear_mask),
        "Chain Global Suffix Twist": global_suffix_twist,
        "Chain Global Suffix Taper": global_suffix_taper,
        "Chain Global Suffix Shear": global_suffix_shear,
        "Chain Global Profile Active": global_profile_active,
        "Chain Global Profile Bottom Scale": global_profile_bottom_scale,
        "Chain Global Profile Top Scale": global_profile_top_scale,
        "Chain Global Profile Bottom Offset": global_profile_bottom_offset,
        "Chain Global Profile Top Offset": global_profile_top_offset,
        "Chain Prefix Base Bend": prefix_base_bend,
        "Chain Prefix Base Twist": prefix_base_twist,
        "Chain Prefix Base Taper": prefix_base_taper,
        "Chain Prefix Base Stretch": prefix_base_stretch,
        "Chain Prefix Base Shear": prefix_base_shear,
    })


def _finite_end_scale(value):
    """Return a finite two-axis end scale honoring the RNA lower bound."""
    try:
        values = tuple(float(component) for component in value)
    except (TypeError, ValueError):
        values = ()
    if len(values) != 2:
        return (1.0, 1.0)
    return tuple(
        max(component, 0.05) if math.isfinite(component) else 1.0
        for component in values
    )


def _stored_authored_end_scales(modifier):
    """Return absolute end profiles persisted beside managed GN inputs."""
    group = getattr(modifier, "node_group", None)
    if group is None:
        return None

    def read(key):
        try:
            values = tuple(float(component) for component in group.get(key, ()))
        except (AttributeError, ReferenceError, TypeError, ValueError):
            return None
        if len(values) != 2 or not all(math.isfinite(value) for value in values):
            return None
        return _finite_end_scale(values)

    top = read(AUTHORED_TOP_SCALE)
    bottom = read(AUTHORED_BOTTOM_SCALE)
    return (top, bottom) if top is not None and bottom is not None else None


def _store_authored_end_scales(modifier, properties):
    """Persist absolute profiles that relative downstream sockets cannot hold."""
    group = getattr(modifier, "node_group", None)
    if group is None:
        return False
    changed = False
    for key, value in (
            (AUTHORED_TOP_SCALE, _finite_end_scale(properties.top_scale)),
            (AUTHORED_BOTTOM_SCALE, _finite_end_scale(properties.bottom_scale))):
        try:
            old = tuple(float(component) for component in group.get(key, ()))
        except (AttributeError, ReferenceError, TypeError, ValueError):
            old = ()
        if len(old) == 2 and all(
                abs(a - b) <= EPSILON for a, b in zip(old, value)):
            continue
        try:
            group[key] = list(value)
            changed = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
    return changed


def evaluator_end_scales(properties, controller=None, modifier=None, *,
                         include_relative=False):
    """Return Top/Bottom Scale values used by the actual stage evaluator.

    Linked seam properties are authored as absolute cross-section targets.
    Geometry entering a downstream stage has already reached the last enabled
    upstream stage's authored top target, so that stage evaluates from an
    identity bottom to ``top / effective incoming``. Disabled stages keep
    their interval but contribute no profile scale. Standalone, root,
    independent, and unlinked stages retain their local-multiplier semantics.
    """
    authored_top = _finite_end_scale(getattr(properties, "top_scale", (1.0, 1.0)))
    authored_bottom = _finite_end_scale(
        getattr(properties, "bottom_scale", (1.0, 1.0)))

    def result(top, bottom, relative=False):
        values = (top, bottom)
        return (*values, bool(relative)) if include_relative else values

    if controller is None:
        controller = getattr(properties, "id_data", None)
    if not is_cage_controller(controller):
        return result(authored_top, authored_bottom)
    target = find_target(controller)
    if modifier is None:
        modifier = find_modifier(target, controller)
    if (
            target is None or modifier is None or
            _managed_chain_mode(controller, modifier) not in
            {"CHAINED", "CONNECTED"}
    ):
        return result(authored_top, authored_bottom)
    try:
        from . import chain as chain_module
        if not chain_module.stage_chain_sync_shared_end_scale(modifier, False):
            return result(authored_top, authored_bottom)
        chain_uuid = chain_module.stage_chain_uuid(modifier)
        stages = chain_module.chain_stages(target, chain_uuid)
        try:
            stage_index = stages.index(modifier)
        except ValueError:
            stage_index = chain_module.stage_chain_index(modifier, 0)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError,
            ValueError):
        return result(authored_top, authored_bottom)
    if stage_index <= 0:
        return result(authored_top, authored_bottom)
    effective_incoming = (1.0, 1.0)
    # The forward scan's final qualifying stage is exactly the first match in
    # reverse order. Stop there instead of searching every earlier controller.
    for upstream in reversed(stages[:stage_index]):
        upstream_controller = find_controller(target, upstream)
        upstream_properties = getattr(
            upstream_controller, "sdh_cage_deform", None)
        if upstream_properties is not None:
            if not bool(getattr(upstream_properties, "stage_enabled", True)):
                continue
            effective_incoming = _finite_end_scale(
                getattr(upstream_properties, "top_scale", (1.0, 1.0)))
            break
        stored_scales = _stored_authored_end_scales(upstream)
        if stored_scales is not None:
            effective_incoming = stored_scales[0]
            break
    relative_top = []
    for top, incoming in zip(authored_top, effective_incoming):
        ratio = top / max(incoming, 0.05)
        relative_top.append(ratio if math.isfinite(ratio) else 1.0)
    relative_top = tuple(relative_top)
    return result(relative_top, (1.0, 1.0), True)


def sync_end_scale_inputs(controller, modifier=None):
    """Push only end-profile inputs during a live shared-seam drag.

    A shared scale edit cannot change operation order, cage ownership, FFD
    companions, or any transform input. Keeping this path focused avoids two
    complete controller synchronizations per mouse event while preserving the
    absolute authored profiles stored beside downstream relative GN sockets.
    ``None`` means the focused path was unavailable and the caller should use
    the full synchronizer.
    """
    if not is_cage_controller(controller):
        return None
    target = find_target(controller)
    if modifier is None:
        modifier = find_modifier(target, controller)
    properties = getattr(controller, "sdh_cage_deform", None)
    if target is None or modifier is None or properties is None:
        return None
    try:
        top_scale, bottom_scale = evaluator_end_scales(
            properties, controller, modifier)
        values = {
            "Top Scale": (top_scale[0], 1.0, top_scale[1]),
            "Bottom Scale": (bottom_scale[0], 1.0, bottom_scale[1]),
        }
        changed = _store_authored_end_scales(modifier, properties)
        for name, value in values.items():
            if modifier_input_identifier(modifier, name) is None:
                return None
            old = modifier_input(modifier, name)
            try:
                old_values = tuple(old) if old is not None else ()
            except (ReferenceError, RuntimeError, TypeError, ValueError):
                old_values = ()
            if len(old_values) == len(value) and all(
                    abs(float(first) - float(second)) <= EPSILON
                    for first, second in zip(old_values, value)
            ):
                continue
            set_modifier_input(modifier, name, value)
            changed = True
        if changed:
            target.update_tag()
        return changed
    except (
            AttributeError, ReferenceError, RuntimeError, TypeError,
            ValueError, OverflowError,
    ):
        return None


def _enforce_chain_properties(controller, properties, modifier=None):
    """Keep a connected stage's mode/origin compatible with its chain frame."""
    if _managed_chain_mode(controller, modifier) not in {"CHAINED", "CONNECTED"}:
        return False
    pointer = _pointer(controller)
    if not pointer or pointer in _CHAIN_MODE_GUARD:
        return False
    needs_mode = properties.mode != "CHAINED"
    if not needs_mode:
        return False
    _CHAIN_MODE_GUARD.add(pointer)
    try:
        if needs_mode:
            properties.mode = "CHAINED"
    finally:
        _CHAIN_MODE_GUARD.discard(pointer)
    return True


def _controller_transform_signature(controller):
    """Return a stable transform snapshot for timer-side change detection."""
    try:
        # ``matrix_basis`` is independent of whether an Empty is currently
        # using XYZ, quaternion, or axis-angle rotation.  Reading only
        # ``rotation_euler`` misses real quaternion edits on some Blender
        # versions and leaves a connected chain one event behind.
        matrix = controller.matrix_basis
        matrix_values = tuple(
            round(float(value), 7)
            for row in matrix for value in row
        )
        return (matrix_values, str(getattr(controller, "rotation_mode", "XYZ")))
    except (AttributeError, ReferenceError, TypeError, ValueError):
        try:
            return tuple(
                tuple(round(float(value), 7) for value in getattr(controller, name))
                for name in ("location", "rotation_euler", "scale")
            )
        except (AttributeError, ReferenceError, TypeError, ValueError):
            return None


def _controller_rotation_xyz(controller):
    """Return the controller's active orientation as an XYZ Euler value.

    ``rotation_euler`` is a derived/inactive RNA channel while an Empty uses
    Quaternion or Axis Angle mode and can remain stale after a direct edit.
    Read the active channel first so negative/non-uniform Empty scale cannot
    turn a mirrored basis into a different rotation.  The normalized basis is
    a compatibility fallback for lightweight test doubles/older data.
    """
    try:
        mode = str(getattr(controller, "rotation_mode", "XYZ") or "XYZ")
        if mode == "QUATERNION":
            return controller.rotation_quaternion.to_euler("XYZ")
        if mode == "AXIS_ANGLE":
            angle, axis_x, axis_y, axis_z = tuple(
                float(value) for value in controller.rotation_axis_angle)
            axis = Vector((axis_x, axis_y, axis_z))
            if axis.length > EPSILON:
                return Quaternion(axis.normalized(), angle).to_euler("XYZ")
            return Euler((0.0, 0.0, 0.0), "XYZ")
        else:
            # Preserve non-XYZ Euler orders by converting their orientation,
            # not by reinterpreting the same three channel values as XYZ.
            return controller.rotation_euler.to_matrix().to_euler("XYZ")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        matrix = controller.matrix_basis.to_3x3().normalized()
        return matrix.to_euler("XYZ")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        try:
            return Euler(tuple(
                float(value) for value in controller.rotation_euler), "XYZ")
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return Euler((0.0, 0.0, 0.0), "XYZ")


def _chain_request_key(target, chain_uuid):
    pointer = _pointer(target) or id(target)
    return pointer, str(chain_uuid or "")


def pending_chain_reconnect_start_index(target, chain_uuid, fallback=0):
    """Merge one immediate edit with an older queued chain dirty index."""
    try:
        dirty_index = max(int(fallback), 0)
    except (TypeError, ValueError):
        dirty_index = 0
    request = _CHAIN_RECONNECT_QUEUE.get(
        _chain_request_key(target, chain_uuid))
    if request is None or len(request) < 3:
        return dirty_index
    try:
        return min(dirty_index, max(int(request[2]), 0))
    except (TypeError, ValueError):
        return dirty_index


@contextmanager
def chain_reconnect_transaction(target, chain_uuid):
    """Suppress deferred reconnects while a chain edit reconnects immediately.

    Shared-boundary drags update two controllers in one mouse event.  Letting
    either controller enqueue the usual timer would expose a half-updated cage
    for one frame and then repeat the same reconnect on the next event cycle.
    """
    key = _chain_request_key(target, chain_uuid)
    already_active = key in _CHAIN_RECONNECTING
    pending_request = _CHAIN_RECONNECT_QUEUE.pop(key, None)
    committed = False

    def commit():
        nonlocal committed
        committed = True

    _CHAIN_RECONNECTING.add(key)
    try:
        yield commit
    finally:
        # A request that existed before the transaction, or one generated by
        # an unrelated callback while it was active, belongs to an external
        # edit. Keep the newest request unless the caller explicitly commits
        # the immediate result; an exception or an aborted edit must not lose
        # either source of work.
        generated_request = _CHAIN_RECONNECT_QUEUE.pop(key, None)
        if not committed:
            restored_request = generated_request or pending_request
            if restored_request is not None:
                _CHAIN_RECONNECT_QUEUE[key] = restored_request
        if not already_active:
            _CHAIN_RECONNECTING.discard(key)


@contextmanager
def chain_atomic_property_update(target, chain_uuid):
    """Suppress reconnect callbacks during one synchronous chain property edit.

    Unlike :func:`chain_reconnect_transaction`, this guard deliberately keeps
    an older queued reconnect intact. Shared end-scale edits use it to copy the
    paired values and propagate the affected suffix exactly once without
    discarding unrelated bend or transform work that is already queued.
    """
    key = _chain_request_key(target, chain_uuid)
    already_active = key in _CHAIN_RECONNECTING
    _CHAIN_RECONNECTING.add(key)
    try:
        yield
    finally:
        if not already_active:
            _CHAIN_RECONNECTING.discard(key)


def flush_pending_chain_updates(target=None):
    """Synchronize queued controller transforms before a modal edit starts."""
    pending = tuple(_CONTROLLER_TRANSFORM_QUEUE.items())
    keep = {}
    for pointer, controller in pending:
        try:
            if target is not None and find_target(controller) != target:
                keep[pointer] = controller
                continue
            if is_cage_controller(controller):
                sync_controller(controller, pull_transform=True, sync_mode="timer")
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    _CONTROLLER_TRANSFORM_QUEUE.clear()
    _CONTROLLER_TRANSFORM_QUEUE.update(keep)
    _drain_ffd_scope_refresh_queue()
    _drain_chain_reconnect_queue()
    _drain_stack_auto_fit_queue()


def _chain_for_controller(controller):
    """Resolve ``(target, uuid)`` for a managed controller, if any."""
    if controller is None or not is_cage_controller(controller):
        return None, ""
    target = find_target(controller)
    if target is None:
        return None, ""
    modifier = find_modifier(target, controller)
    group = getattr(modifier, "node_group", None) if modifier else None
    chain_uuid = ""
    try:
        chain_uuid = str(group.get(CHAIN_UUID_PROP, "") or "") if group else ""
    except (AttributeError, ReferenceError, TypeError):
        chain_uuid = ""
    if not chain_uuid:
        try:
            from .chain import _resolve_chain_uuid
            chain_uuid = _resolve_chain_uuid(target)
        except (ImportError, AttributeError, ReferenceError, RuntimeError):
            chain_uuid = ""
    return target, chain_uuid


def _is_chain_stage(controller, modifier):
    """Return whether a cage belongs to a live connected/chained stack."""
    if controller is None or modifier is None:
        return False
    try:
        return str(_managed_chain_mode(controller, modifier)).upper() in {
            "CHAINED", "CONNECTED",
        }
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _stack_auto_fit_enabled(controller, modifier=None):
    """Return whether an ordinary cage opts into upstream frame fitting."""
    if controller is None or not is_cage_controller(controller):
        return False
    if modifier is None:
        target = find_target(controller)
        modifier = find_modifier(target, controller) if target is not None else None
    if modifier is None or _is_chain_stage(controller, modifier):
        return False
    properties = getattr(controller, "sdh_cage_deform", None)
    return bool(getattr(properties, "auto_sync_upstream", False))


def _stack_auto_fit_signature(controller, bounds):
    """Build a stable cache token for the result of an Align & Fit action."""
    if bounds is None or len(bounds) != 2:
        return None
    properties = getattr(controller, "sdh_cage_deform", None)
    if properties is None:
        return None
    try:
        values = tuple(
            round(float(component), 7)
            for point in bounds for component in point
        )
    except (TypeError, ValueError, AttributeError):
        return None
    return (str(getattr(properties, "alignment", "AUTO")), values)


def _stack_auto_fit_has_candidate(target, start_index=0):
    """Avoid scheduling a target that has no enabled ordinary downstream cage."""
    try:
        modifiers = tuple(target.modifiers)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return False
    for index, modifier in enumerate(modifiers):
        if index < int(start_index) or not is_cage_modifier(modifier):
            continue
        controller = find_controller(target, modifier)
        if _stack_auto_fit_enabled(controller, modifier):
            return True
    return False


def request_stack_auto_fit(
        controller_or_target, source_modifier=None, *,
        include_current=False, force=False):
    """Queue ordinary downstream cages for an evaluated frame refit.

    A request is deliberately deferred to a timer.  ``fit_controller`` creates
    a temporary evaluated clone and writes RNA transforms, both of which are
    unsafe while Blender is inside a dependency-graph callback.
    """
    target = controller_or_target
    if is_cage_controller(controller_or_target):
        target = find_target(controller_or_target)
        if source_modifier is None and target is not None:
            source_modifier = find_modifier(target, controller_or_target)
    if target is None:
        return False
    try:
        if bool(target.get(RUNTIME_EVALUATOR, False)):
            return False
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return False
    try:
        modifiers = tuple(target.modifiers)
        if source_modifier in modifiers:
            source_index = modifiers.index(source_modifier)
            start_index = source_index if include_current else source_index + 1
        else:
            start_index = 0
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False
    if not _stack_auto_fit_has_candidate(target, start_index):
        return False
    key = _pointer(target)
    if not key:
        return False
    # Measuring evaluated input bounds creates and removes a temporary clone,
    # which emits dependency-graph updates for the same target.  Ignore those
    # self-generated requests while this target is already being fitted;
    # otherwise every drain schedules another zero-delay drain indefinitely.
    if key in _STACK_AUTO_FIT_RUNNING:
        return False
    previous = _STACK_AUTO_FIT_QUEUE.get(key)
    if previous is None:
        _STACK_AUTO_FIT_QUEUE[key] = (target, start_index, bool(force))
    else:
        old_target, old_start, old_force = previous
        _STACK_AUTO_FIT_QUEUE[key] = (
            old_target,
            min(int(old_start), int(start_index)),
            bool(old_force or force),
        )
    _schedule_chain_reconnect()
    return True


def _drain_stack_auto_fit_queue(context=None):
    """Apply queued ordinary-cage fits in modifier-stack order."""
    if not _STACK_AUTO_FIT_QUEUE:
        return 0
    pending = tuple(_STACK_AUTO_FIT_QUEUE.values())
    _STACK_AUTO_FIT_QUEUE.clear()
    context = context or bpy.context
    fitted = 0
    for target, start_index, force in pending:
        key = _pointer(target)
        if not key or key in _STACK_AUTO_FIT_RUNNING:
            continue
        _STACK_AUTO_FIT_RUNNING.add(key)
        _STACK_AUTO_FIT_DEPSGRAPH_GUARD.add(key)
        try:
            modifiers = tuple(target.modifiers)
            for index, modifier in enumerate(modifiers):
                if index < int(start_index) or not is_cage_modifier(modifier):
                    continue
                controller = find_controller(target, modifier)
                if not _stack_auto_fit_enabled(controller, modifier):
                    if controller is not None:
                        _STACK_AUTO_FIT_SIGNATURES.pop(
                            _pointer(controller), None)
                    continue
                bounds = _modifier_input_bounds(context, target, modifier)
                signature = _stack_auto_fit_signature(controller, bounds)
                pointer = _pointer(controller)
                if (
                        not force and pointer and
                        _STACK_AUTO_FIT_SIGNATURES.get(pointer) == signature
                ):
                    continue
                if fit_controller_to_bounds(
                        context, target, modifier, controller, bounds) is None:
                    continue
                if pointer:
                    _STACK_AUTO_FIT_SIGNATURES[pointer] = signature
                fitted += 1
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
        finally:
            # View-layer updates used to sample upstream geometry can dispatch
            # their dependency notifications near the end of this synchronous
            # fit. They only describe the temporary evaluator and RNA writes
            # performed above, so do not carry that self-request into another
            # zero-delay timer cycle.
            _STACK_AUTO_FIT_QUEUE.pop(key, None)
            _STACK_AUTO_FIT_RUNNING.discard(key)
    if _STACK_AUTO_FIT_DEPSGRAPH_GUARD:
        try:
            if not bpy.app.timers.is_registered(
                    _clear_stack_auto_fit_depsgraph_guard):
                bpy.app.timers.register(
                    _clear_stack_auto_fit_depsgraph_guard,
                    first_interval=0.0,
                )
        except (AttributeError, RuntimeError, ValueError):
            pass
    return fitted


def _clear_stack_auto_fit_depsgraph_guard():
    """Release suppression after Blender dispatches fit-generated updates."""
    _STACK_AUTO_FIT_DEPSGRAPH_GUARD.clear()
    return None


def _schedule_chain_reconnect():
    """Schedule one low-latency queue drain on Blender's next event cycle."""
    try:
        if not bpy.app.timers.is_registered(_chain_reconnect_timer):
            bpy.app.timers.register(_chain_reconnect_timer, first_interval=0.0)
    except (RuntimeError, ValueError):
        # The periodic controller timer remains a fallback while Blender is
        # loading a file or shutting down and temporarily rejects new timers.
        return False
    return True


def _lattice_origin_signature(target):
    """Return a cheap signature for detached Origins owned by a Lattice."""
    try:
        transform = tuple(
            round(float(value), 8)
            for row in target.matrix_world
            for value in row)
        stages = tuple(
            (
                _pointer(modifier),
                tuple(round(float(value), 8) for value in modifier.limits),
                str(modifier.deform_axis),
                str(modifier.deform_method),
                _pointer(getattr(modifier, "origin", None)),
            )
            for modifier in getattr(target, "modifiers", ())
            if (
                modifier.type == "SIMPLE_DEFORM" and
                GizmoUtils.is_managed_origin(
                    getattr(modifier, "origin", None), target)
            )
        )
        return transform, stages
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


def request_lattice_origin_sync(target):
    """Queue detached traditional Origins for a safe world-space refresh."""
    if target is None or getattr(target, "type", None) != "LATTICE":
        return False
    signature = _lattice_origin_signature(target)
    if signature is None or signature == _LATTICE_ORIGIN_SIGNATURES.get(
            _pointer(target)):
        return False
    pointer = _pointer(target)
    if not pointer:
        return False
    if pointer in _LATTICE_ORIGIN_QUEUE:
        return True
    _LATTICE_ORIGIN_QUEUE[pointer] = (target, signature)
    _schedule_chain_reconnect()
    return True


def _drain_lattice_origin_sync_queue():
    if not _LATTICE_ORIGIN_QUEUE:
        return 0
    pending = tuple(_LATTICE_ORIGIN_QUEUE.values())
    _LATTICE_ORIGIN_QUEUE.clear()
    updated = 0
    for target, signature in pending:
        try:
            for modifier in tuple(getattr(target, "modifiers", ())):
                if modifier.type != "SIMPLE_DEFORM":
                    continue
                origin = getattr(modifier, "origin", None)
                if not GizmoUtils.is_managed_origin(origin, target):
                    continue
                helper = _TraditionalGizmoContext(target, modifier)
                helper.clear_point_cache()
                helper.update_object_origin_matrix()
                updated += 1
            _LATTICE_ORIGIN_SIGNATURES[_pointer(target)] = signature
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return updated


def request_chain_reconnect(
        controller_or_target, chain_uuid="", *, force=False,
        start_index=None, include_stage=False):
    """Queue one chain for debounced automatic frame propagation.

    Calls are intentionally cheap and idempotent.  Property callbacks and the
    controller timer can both request the same chain during one interaction;
    the timer drains the dictionary once after all controllers have synced.
    """
    source_controller = (
        controller_or_target if is_cage_controller(controller_or_target)
        else None)
    target = controller_or_target
    if source_controller is not None:
        target, resolved_uuid = _chain_for_controller(controller_or_target)
        chain_uuid = chain_uuid or resolved_uuid
    if target is None:
        return False
    try:
        from . import chain as chain_module
        stages = chain_module.chain_stages(target, chain_uuid)
        if len(stages) < 2:
            return False
        chain_uuid = chain_module._resolve_chain_uuid(target, chain_uuid)
        mode = chain_module.stage_chain_mode(stages[0], "")
        if mode not in {"CHAINED", "CONNECTED"}:
            return False
        if not force and not chain_module.chain_auto_reconnect(target, chain_uuid, True):
            return False
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError):
        return False
    if not chain_uuid:
        return False
    if start_index is None:
        dirty_index = 0
        if source_controller is not None:
            try:
                dirty_modifier = find_modifier(target, source_controller)
                dirty_index = stages.index(dirty_modifier)
            except (AttributeError, ValueError):
                dirty_index = 0
            if include_stage and dirty_index > 0:
                dirty_index -= 1
    else:
        try:
            dirty_index = int(start_index)
        except (TypeError, ValueError):
            dirty_index = 0
    dirty_index = min(max(dirty_index, 0), len(stages) - 1)
    key = _chain_request_key(target, chain_uuid)
    first_request = key not in _CHAIN_RECONNECT_QUEUE
    previous = _CHAIN_RECONNECT_QUEUE.get(key)
    if previous is not None:
        previous_index = int(previous[2]) if len(previous) > 2 else 0
        dirty_index = min(dirty_index, previous_index)
    _CHAIN_RECONNECT_QUEUE[key] = (target, str(chain_uuid), dirty_index)
    if first_request:
        _schedule_chain_reconnect()
    return True


def _drain_chain_reconnect_queue():
    """Reconnect each queued chain once, then discard stale requests."""
    if not _CHAIN_RECONNECT_QUEUE:
        return 0
    pending = tuple(_CHAIN_RECONNECT_QUEUE.values())
    _CHAIN_RECONNECT_QUEUE.clear()
    updated = 0
    try:
        from . import chain as chain_module
    except ImportError:
        return 0
    for request in pending:
        target, chain_uuid = request[:2]
        start_index = int(request[2]) if len(request) > 2 else 0
        key = _chain_request_key(target, chain_uuid)
        if key in _CHAIN_RECONNECTING:
            continue
        try:
            if not chain_module.chain_auto_reconnect(target, chain_uuid, True):
                continue
            _CHAIN_RECONNECTING.add(key)
            updated += int(chain_module.reconnect_chain(
                target, chain_uuid, start_index=start_index,
                runtime_only=True) or 0)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            # A deleted target or an invalidated node group can leave a stale
            # request behind while Blender is rebuilding its dependency graph.
            continue
        finally:
            _CHAIN_RECONNECTING.discard(key)
    return updated


def _chain_reconnect_timer():
    """Sync direct transforms, then drain chains in one safe timer callback."""
    pending_controllers = tuple(_CONTROLLER_TRANSFORM_QUEUE.values())
    _CONTROLLER_TRANSFORM_QUEUE.clear()
    for controller in pending_controllers:
        try:
            pointer = _pointer(controller)
            if not pointer or not is_cage_controller(controller):
                continue
            signature = _controller_transform_signature(controller)
            if _CONTROLLER_TRANSFORM_SNAPSHOTS.get(pointer) == signature:
                continue
            sync_controller(
                controller, pull_transform=True, sync_mode="timer")
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            continue
    _drain_ffd_scope_refresh_queue()
    _drain_chain_reconnect_queue()
    _drain_stack_auto_fit_queue()
    _drain_lattice_origin_sync_queue()
    # A callback triggered during the drain is kept for one more event cycle.
    return 0.0 if (
        _CONTROLLER_TRANSFORM_QUEUE or _CHAIN_RECONNECT_QUEUE or
        _STACK_AUTO_FIT_QUEUE or _LATTICE_ORIGIN_QUEUE or
        _FFD_SCOPE_REFRESH_QUEUE) else None


def clear_chain_reconnect_state():
    """Drop pending reconnects and snapshots during unregister/load cleanup."""
    global _CONTROLLER_DISPLAY_SIGNATURE, _SELECTION_SYNC_DIRTY
    try:
        if bpy.app.timers.is_registered(_chain_reconnect_timer):
            bpy.app.timers.unregister(_chain_reconnect_timer)
        if bpy.app.timers.is_registered(
                _clear_stack_auto_fit_depsgraph_guard):
            bpy.app.timers.unregister(_clear_stack_auto_fit_depsgraph_guard)
    except (RuntimeError, ValueError):
        pass
    _CHAIN_RECONNECT_QUEUE.clear()
    clear_node_runtime_state()
    _CONTROLLER_TRANSFORM_QUEUE.clear()
    _CHAIN_RECONNECTING.clear()
    clear_ffd_scope_cache()
    _FFD_GUARD_VALID_OFFSETS.clear()
    _CHAIN_AFFINE_FRAME_CACHE.clear()
    _CHAIN_DISPLAY_STATE_CACHE.clear()
    _CHAIN_DOMAIN_INPUT_CACHE.clear()
    _CONTROLLER_SIZE_SNAPSHOTS.clear()
    _CONTROLLER_TRANSFORM_SNAPSHOTS.clear()
    _STACK_AUTO_FIT_QUEUE.clear()
    _STACK_AUTO_FIT_RUNNING.clear()
    _STACK_AUTO_FIT_SIGNATURES.clear()
    _STACK_AUTO_FIT_DEPSGRAPH_GUARD.clear()
    _LATTICE_ORIGIN_QUEUE.clear()
    _LATTICE_ORIGIN_SIGNATURES.clear()
    _TARGET_OWNERSHIP_REPAIR_QUEUE.clear()
    _TARGET_OWNERSHIP_REPAIRING.clear()
    _CHAIN_AUTO_GUARD.clear()
    _CHAIN_SHARED_SCALE_GUARD.clear()
    _CHAIN_GLOBAL_STRETCH_GUARD.clear()
    _CHAIN_MODE_GUARD.clear()
    _CURVE_PRESET_UPDATE_GUARD.clear()
    _SYNCING.clear()
    _CONTROLLER_DISPLAY_GUARD.clear()
    _CONTROLLER_DISPLAY_SIGNATURE = None
    _SELECTION_SYNC_DIRTY = False
    _WORKSPACE_TOOL_OVERRIDES.clear()


def _auto_reconnect_update(properties, _context):
    """Mirror the legacy chain reconnect preference and queue a refresh."""
    controller = getattr(properties, "id_data", None)
    if not is_cage_controller(controller):
        return
    pointer = _pointer(controller)
    if pointer and (pointer in _CHAIN_AUTO_GUARD or pointer in _SYNCING):
        return
    target, chain_uuid = _chain_for_controller(controller)
    if target is None or not chain_uuid:
        return
    try:
        from . import chain as chain_module
        chain_module.set_chain_auto_reconnect(
            target, chain_uuid, bool(properties.auto_reconnect),
            sync_properties=True)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError):
        return
    if properties.auto_reconnect:
        request_chain_reconnect(controller, start_index=0)


def _auto_sync_upstream_update(properties, _context):
    """Queue an ordinary stack cage for an immediate evaluated frame fit."""
    controller = getattr(properties, "id_data", None)
    if not is_cage_controller(controller):
        return
    pointer = _pointer(controller)
    if pointer and (pointer in _CHAIN_AUTO_GUARD or pointer in _SYNCING):
        return
    target, modifier = _target_and_modifier(controller)
    if target is None or modifier is None or _is_chain_stage(controller, modifier):
        # The control is intentionally unavailable for chain stages. Keep a
        # stale value from an intermediate release from affecting reconnect.
        return
    if bool(getattr(properties, "auto_sync_upstream", False)):
        request_stack_auto_fit(
            controller,
            modifier,
            include_current=True,
            force=True,
        )
    else:
        _STACK_AUTO_FIT_SIGNATURES.pop(pointer, None)


def _sync_shared_end_scale_update(properties, _context):
    """Mirror the shared-seam scale preference to the whole live chain."""
    controller = getattr(properties, "id_data", None)
    if not is_cage_controller(controller):
        return
    pointer = _pointer(controller)
    if pointer and (pointer in _CHAIN_SHARED_SCALE_GUARD or pointer in _SYNCING):
        return
    target, chain_uuid = _chain_for_controller(controller)
    if target is None or not chain_uuid:
        return
    try:
        from . import chain as chain_module
        chain_module.set_chain_sync_shared_end_scale(
            target, chain_uuid, bool(properties.sync_shared_end_scale),
            sync_properties=True, reconcile=True)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError):
        return


def _sync_closed_curve_end_value(
        properties, side, top_attribute, bottom_attribute):
    """Mirror one authored end value across the seam of a closed Curve cage."""
    if (
            str(getattr(properties, "cage_type", "")) != "CURVE" or
            not bool(getattr(properties, "curve_closed", False))
    ):
        return False
    pointer = _pointer(getattr(properties, "id_data", None))
    if pointer and pointer in _SYNCING:
        return False
    source_attribute = top_attribute if str(side).upper() == "TOP" else bottom_attribute
    target_attribute = bottom_attribute if str(side).upper() == "TOP" else top_attribute
    source_value = tuple(getattr(properties, source_attribute))
    if tuple(getattr(properties, target_attribute)) == source_value:
        return False
    if pointer:
        _SYNCING.add(pointer)
    try:
        setattr(properties, target_attribute, source_value)
    finally:
        if pointer:
            _SYNCING.discard(pointer)
    return True


def _end_scale_update(properties, context, side):
    """Push one end scale, pairing it with a shared chain seam when enabled."""
    controller = getattr(properties, "id_data", None)
    if not is_cage_controller(controller):
        return
    pointer = _pointer(controller)
    if pointer and (
            pointer in _CHAIN_SHARED_SCALE_GUARD or pointer in _SYNCING
    ):
        return
    _sync_closed_curve_end_value(
        properties, side, "top_scale", "bottom_scale")
    target, modifier = _target_and_modifier(controller)
    if target is not None and modifier is not None:
        try:
            from . import chain as chain_module
            if chain_module.sync_chain_shared_end_scale(
                    target, modifier, side):
                return
        except (ImportError, AttributeError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            pass
    _controller_update(properties, context)


def _top_scale_update(properties, context):
    _end_scale_update(properties, context, "TOP")


def _bottom_scale_update(properties, context):
    _end_scale_update(properties, context, "BOTTOM")


def _end_offset_update(properties, context, side):
    controller = getattr(properties, "id_data", None)
    if not is_cage_controller(controller):
        return
    pointer = _pointer(controller)
    if pointer and pointer in _SYNCING:
        return
    _sync_closed_curve_end_value(
        properties, side, "top_offset", "bottom_offset")
    _controller_update(properties, context)
    # End offsets change the evaluated terminal frame of a chain stage. The
    # normal controller update intentionally debounces reconnects, but a
    # direct panel/RNA edit can be redrawn before that timer runs. Commit the
    # queued chain refresh here so downstream stages never render one frame
    # against the old seam. Gizmo exits still call the same flush as a
    # defensive fallback for modal writes.
    _flush_chain_end_offset_update(controller)


def _flush_chain_end_offset_update(controller):
    """Synchronously settle a chain after a direct end-offset property edit."""
    target, modifier = _target_and_modifier(controller)
    if target is None or modifier is None:
        return False
    if not _CHAIN_RECONNECT_QUEUE:
        return False
    try:
        from . import chain as chain_module
        chain_uuid = chain_module.stage_chain_uuid(modifier)
        if not chain_uuid or not chain_module.chain_auto_reconnect(
                target, chain_uuid, True):
            return False
    except (ImportError, AttributeError, ReferenceError, RuntimeError,
            TypeError, ValueError):
        return False
    flush_pending_chain_updates(target)
    return True


def _top_offset_update(properties, context):
    _end_offset_update(properties, context, "TOP")


def _bottom_offset_update(properties, context):
    _end_offset_update(properties, context, "BOTTOM")


def _controller_update(properties, _context):
    controller = getattr(properties, "id_data", None)
    if is_cage_controller(controller):
        pointer = _pointer(controller)
        if pointer and (
                pointer in _CHAIN_AUTO_GUARD or pointer in _CHAIN_MODE_GUARD or
                pointer in _CHAIN_SHARED_SCALE_GUARD or pointer in _SYNCING
        ):
            return
        # Origin is a discrete frame reference rather than a continuously
        # dragged parameter.  Writing it to the active stage immediately
        # changes that stage's terminal frame, so leaving downstream frames
        # in the debounce queue exposes a visibly misaligned chain until the
        # next timer tick.  Capture the old socket value before the regular
        # sync, then commit one synchronous reconnect when Origin changed.
        origin_before = None
        target_before = None
        modifier_before = None
        chain_uuid_before = ""
        try:
            target_before, modifier_before = _target_and_modifier(controller)
            if target_before is not None and modifier_before is not None:
                origin_before = modifier_input(modifier_before, "Origin")
                if _managed_chain_mode(controller, modifier_before) in {
                        "CHAINED", "CONNECTED"}:
                    from . import chain as chain_module
                    # Resolve from this controller's modifier instead of the
                    # target's active/first cage; a target may contain more
                    # than one independent chain in its native stack.
                    chain_uuid_before = chain_module.stage_chain_uuid(
                        modifier_before)
        except (ImportError, AttributeError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            target_before = modifier_before = None
            chain_uuid_before = ""
        try:
            origin_before_value = (
                None if origin_before is None else int(origin_before))
        except (TypeError, ValueError, OverflowError):
            origin_before_value = None
        _enforce_chain_properties(controller, properties)
        sync_controller(controller, pull_transform=False)
        if (
                origin_before_value is not None and target_before is not None and
                modifier_before is not None and chain_uuid_before and
                origin_before_value != ORIGIN_VALUES.get(
                    str(getattr(properties, "origin", "BOTTOM")), 0)
        ):
            try:
                from . import chain as chain_module
                key = _chain_request_key(target_before, chain_uuid_before)
                auto_reconnect = chain_module.chain_auto_reconnect(
                    target_before, chain_uuid_before, True)
                if auto_reconnect and key not in _CHAIN_RECONNECTING:
                    with chain_reconnect_transaction(
                            target_before, chain_uuid_before) as commit:
                        chain_module.reconnect_chain(
                            target_before, chain_uuid_before)
                        commit()
            except (ImportError, AttributeError, ReferenceError, RuntimeError,
                    TypeError, ValueError):
                # The normal timer queue remains the fallback while Blender
                # is loading, undoing, or rebuilding the dependency graph.
                pass


def _stage_enabled_update(properties, context):
    """Apply a chain stage toggle without exposing stale downstream inputs."""
    controller = getattr(properties, "id_data", None)
    if not is_cage_controller(controller):
        return
    pointer = _pointer(controller)
    if pointer and pointer in _SYNCING:
        return

    target, chain_uuid = _chain_for_controller(controller)
    try:
        from . import chain as chain_module
        stages = chain_module.chain_stages(target, chain_uuid)
        connected = bool(
            target is not None and chain_uuid and len(stages) >= 2 and
            chain_module.stage_chain_mode(stages[0], "").upper() in
            {"CHAINED", "CONNECTED"}
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError,
            TypeError, ValueError):
        connected = False

    if not connected:
        _controller_update(properties, context)
        return

    # Enabling or bypassing an upstream stage changes both its terminal frame
    # and the effective shared-scale baseline of every downstream stage.  Do
    # both writes in this RNA event so the dependency graph never evaluates a
    # mixture of the old chain and the new Stage Enabled value.
    with chain_reconnect_transaction(target, chain_uuid) as commit:
        sync_controller(controller, pull_transform=False)
        chain_module.reconnect_chain(target, chain_uuid)
        commit()


def _tag_view3d_redraw():
    """Invalidate every open 3D viewport after load or display changes."""
    window_manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(window_manager, "windows", ()):
        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", ()):
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _controller_display_update(properties, context):
    """Apply visibility changes immediately when the panel toggle changes."""
    controller = getattr(properties, "id_data", None)
    if not is_cage_controller(controller):
        return
    pointer = _pointer(controller)
    if pointer and pointer in _CONTROLLER_DISPLAY_GUARD:
        return
    target = find_target(controller)
    _sync_target_show_other_cages(target, bool(properties.show_other_cages))
    refresh_controller_display(context or bpy.context, force=True)
    # A property update may happen outside a normal viewport redraw (for
    # example from a driver or a script), so request a redraw opportunistically.
    _tag_view3d_redraw()


def _property_update_guarded(properties):
    controller = getattr(properties, "id_data", None)
    pointer = _pointer(controller) if is_cage_controller(controller) else 0
    return pointer, bool(pointer and (
        pointer in _SYNCING or pointer in _CHAIN_GLOBAL_STRETCH_GUARD
    ))


def _legacy_values_for_primary(properties):
    deform_type = properties.deform_type
    strength = {
        "BEND": properties.bend_strength,
        "TWIST": properties.twist_strength,
    }.get(deform_type, 0.0)
    factor = {
        "TAPER": properties.taper_factor,
        "STRETCH": properties.stretch_factor,
    }.get(deform_type, 0.0)
    direction = properties.bend_direction if deform_type == "BEND" else 0.0
    return float(strength), float(factor), float(direction)


def _mirror_primary_to_legacy(properties, pointer):
    """Keep old scripts and gizmos useful while independent values are stored."""
    strength, factor, direction = _legacy_values_for_primary(properties)
    if pointer:
        _SYNCING.add(pointer)
    try:
        properties.strength = strength
        properties.factor = factor
        properties.direction = direction
    finally:
        if pointer:
            _SYNCING.discard(pointer)


def set_deform_layers(properties, order, context=None):
    """Atomically replace one cage's unique, non-empty deformation layers."""
    fallback = getattr(properties, "deform_type", "BEND")
    normalized = normalize_deform_order(order, fallback=fallback)
    cage_type = str(getattr(properties, "cage_type", "STANDARD") or "STANDARD")
    locked_type = CAGE_TYPE_DEFORM.get(cage_type)
    if locked_type is not None and normalized != (locked_type,):
        return False
    if locked_type is None:
        normalized = tuple(
            deform_type for deform_type in normalized
            if deform_type in STANDARD_DEFORM_ORDER)
        if not normalized:
            normalized = ("BEND",)
    encoded = encode_deform_order(normalized, fallback=fallback)
    enabled = set(normalized)
    current_order = ordered_deform_types(properties)
    current_enabled = set(getattr(properties, "deform_types", ()))
    current_muted = set(getattr(properties, "muted_deform_types", ()))
    muted = current_muted & enabled
    current_primary = getattr(properties, "deform_type", fallback)
    primary = current_primary if current_primary in enabled else normalized[0]
    current_index = min(max(
        int(getattr(properties, "active_deform_layer", 0)), 0),
        max(len(current_order) - 1, 0))
    selected_type = current_order[current_index] if current_order else None
    active_index = (
        normalized.index(selected_type)
        if selected_type in normalized else
        min(current_index, len(normalized) - 1)
    )
    if (
            current_order == normalized and current_enabled == enabled and
            current_muted == muted and
            current_primary == primary and
            int(getattr(properties, "active_deform_layer", 0)) == active_index and
            tuple(getattr(properties, "deform_order", ())) == encoded
    ):
        return False

    controller = getattr(properties, "id_data", None)
    pointer = _pointer(controller) if is_cage_controller(controller) else 0
    if pointer:
        _SYNCING.add(pointer)
    try:
        properties.deform_order = encoded
        properties.deform_types = enabled
        properties.muted_deform_types = muted
        properties.deform_type = primary
        properties.active_deform_layer = active_index
    finally:
        if pointer:
            _SYNCING.discard(pointer)
    _mirror_primary_to_legacy(properties, pointer)
    _controller_update(properties, context)
    return True


def add_deform_layer(properties, deform_type, index=-1, context=None):
    """Add one unique layer. Duplicate or invalid additions are rejected."""
    if deform_type not in STANDARD_DEFORM_ORDER:
        return False
    if str(getattr(properties, "cage_type", "STANDARD")) != "STANDARD":
        return False
    ordered = list(ordered_deform_types(properties))
    if deform_type in ordered:
        return False
    try:
        index = int(index)
    except (TypeError, ValueError, OverflowError):
        index = -1
    if index < 0 or index > len(ordered):
        index = len(ordered)
    ordered.insert(index, deform_type)
    if not set_deform_layers(properties, ordered, context):
        return False
    try:
        expanded = set(properties.expanded_deform_layers)
        expanded.add(deform_type)
        properties.expanded_deform_layers = expanded
    except (AttributeError, TypeError, ValueError):
        pass
    return True


def remove_deform_layer(properties, index, context=None):
    """Remove one layer by list index while preserving the final layer."""
    if str(getattr(properties, "cage_type", "STANDARD")) != "STANDARD":
        return False
    ordered = list(ordered_deform_types(properties))
    if len(ordered) <= 1:
        return False
    try:
        index = int(index)
    except (TypeError, ValueError, OverflowError):
        return False
    if not 0 <= index < len(ordered):
        return False
    del ordered[index]
    return set_deform_layers(properties, ordered, context)


def move_deform_layer(properties, index, direction, context=None):
    """Move one layer one slot UP or DOWN without intermediate syncs.

    A connected chain stores the boundary frame for every stage.  Reordering
    a layer changes the active stage's mapping, so leaving the normal deferred
    reconnect queue to settle later exposes stale downstream frames for one or
    more redraws.  Wrap this structural edit in the same transaction used by
    boundary drags and reconnect the complete chain before the edit returns.
    """
    if str(getattr(properties, "cage_type", "STANDARD")) != "STANDARD":
        return False
    ordered = list(ordered_deform_types(properties))
    try:
        index = int(index)
    except (TypeError, ValueError, OverflowError):
        return False
    delta = {"UP": -1, "DOWN": 1}.get(str(direction).upper())
    destination = index + delta if delta is not None else -1
    if not 0 <= index < len(ordered) or not 0 <= destination < len(ordered):
        return False
    ordered[index], ordered[destination] = (
        ordered[destination], ordered[index])

    controller = getattr(properties, "id_data", None)
    target = modifier = None
    chain_uuid = ""
    chain_module = None
    if is_cage_controller(controller):
        try:
            target, modifier = _target_and_modifier(controller)
            from . import chain as chain_module
            chain_uuid = chain_module.stage_chain_uuid(modifier)
            chain_mode = chain_module.stage_chain_mode(modifier, "").upper()
            if not (
                    target is not None and modifier is not None and
                    chain_uuid and chain_mode in {"CHAINED", "CONNECTED"} and
                    len(chain_module.chain_stages(target, chain_uuid)) >= 2
            ):
                target = modifier = None
                chain_uuid = ""
                chain_module = None
        except (ImportError, AttributeError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            target = modifier = None
            chain_uuid = ""
            chain_module = None

    if chain_module is None:
        return set_deform_layers(properties, ordered, context)

    transaction = chain_reconnect_transaction(target, chain_uuid)
    with transaction as commit:
        changed = set_deform_layers(properties, ordered, context)
        if changed:
            chain_module.reconnect_chain(target, chain_uuid)
            commit()
    return changed


def set_deform_layer_muted(properties, deform_type, muted, context=None):
    """Temporarily enable or mute one present layer without losing its state."""
    deform_type = _deform_name(deform_type)
    present = set(getattr(properties, "deform_types", ()))
    if deform_type is None or deform_type not in present:
        return False
    current = set(getattr(properties, "muted_deform_types", ())) & present
    updated = set(current)
    if muted:
        updated.add(deform_type)
    else:
        updated.discard(deform_type)
    if updated == current:
        return False

    controller = getattr(properties, "id_data", None)
    pointer = _pointer(controller) if is_cage_controller(controller) else 0
    if pointer:
        _SYNCING.add(pointer)
    try:
        properties.muted_deform_types = updated
    finally:
        if pointer:
            _SYNCING.discard(pointer)
    _controller_update(properties, context)
    return True


def _deform_type_update(properties, context):
    """Treat writes to the legacy selector as an intentional single choice."""
    pointer, guarded = _property_update_guarded(properties)
    if guarded:
        return
    locked_type = CAGE_TYPE_DEFORM.get(
        str(getattr(properties, "cage_type", "STANDARD")))
    if locked_type is not None and properties.deform_type != locked_type:
        pointer = _pointer(getattr(properties, "id_data", None))
        if pointer:
            _SYNCING.add(pointer)
        try:
            properties.deform_type = locked_type
        finally:
            if pointer:
                _SYNCING.discard(pointer)
        return
    if pointer:
        _SYNCING.add(pointer)
    try:
        properties.deform_types = {properties.deform_type}
        properties.muted_deform_types = set()
        properties.deform_order = encode_deform_order(
            (properties.deform_type,), {properties.deform_type},
            properties.deform_type)
        properties.active_deform_layer = 0
    finally:
        if pointer:
            _SYNCING.discard(pointer)
    _mirror_primary_to_legacy(properties, pointer)
    _controller_update(properties, context)


def _deform_types_update(properties, context):
    pointer, guarded = _property_update_guarded(properties)
    if guarded:
        return
    enabled = set(properties.deform_types)
    locked_type = CAGE_TYPE_DEFORM.get(
        str(getattr(properties, "cage_type", "STANDARD")))
    if locked_type is not None:
        enabled = {locked_type}
        if set(properties.deform_types) != enabled:
            if pointer:
                _SYNCING.add(pointer)
            try:
                properties.deform_types = enabled
            finally:
                if pointer:
                    _SYNCING.discard(pointer)
    if not enabled:
        fallback = (
            properties.deform_type
            if properties.deform_type in DEFORM_BITS else "BEND")
        if pointer:
            _SYNCING.add(pointer)
        try:
            properties.deform_types = {fallback}
        finally:
            if pointer:
                _SYNCING.discard(pointer)
        enabled = {fallback}
    if enabled and properties.deform_type not in enabled:
        if pointer:
            _SYNCING.add(pointer)
        try:
            properties.deform_type = next(
                name for name in DEFORM_ORDER if name in enabled)
        finally:
            if pointer:
                _SYNCING.discard(pointer)
    muted = set(getattr(properties, "muted_deform_types", ())) & enabled
    if muted != set(getattr(properties, "muted_deform_types", ())):
        if pointer:
            _SYNCING.add(pointer)
        try:
            properties.muted_deform_types = muted
        finally:
            if pointer:
                _SYNCING.discard(pointer)
    normalized = normalize_deform_order(
        properties.deform_order, enabled, properties.deform_type)
    encoded = encode_deform_order(
        normalized, enabled, properties.deform_type)
    if tuple(properties.deform_order) != encoded:
        if pointer:
            _SYNCING.add(pointer)
        try:
            properties.deform_order = encoded
        finally:
            if pointer:
                _SYNCING.discard(pointer)
    active_index = min(
        max(int(getattr(properties, "active_deform_layer", 0)), 0),
        len(normalized) - 1)
    if int(getattr(properties, "active_deform_layer", 0)) != active_index:
        properties.active_deform_layer = active_index
    _mirror_primary_to_legacy(properties, pointer)
    _controller_update(properties, context)


def _cage_type_update(properties, context):
    """Keep dedicated cages single-operation and every chain type-homogeneous."""
    controller = getattr(properties, "id_data", None)
    pointer = _pointer(controller)
    if pointer and pointer in _SYNCING:
        return
    if pointer and pointer in _CAGE_TYPE_GUARD:
        return
    cage_type = str(getattr(properties, "cage_type", "STANDARD") or "STANDARD")
    if cage_type not in CAGE_TYPES:
        cage_type = "STANDARD"
    target = find_target(controller) if is_cage_controller(controller) else None
    modifier = find_modifier(target, controller) if target is not None else None
    if target is not None and modifier is not None:
        try:
            from . import chain as chain_module
            chain_uuid = chain_module.stage_chain_uuid(modifier)
            # An independent stage has no chain UUID while it is being
            # initialized.  ``chain_stages(target, "")`` intentionally falls
            # back to the active/first chain, which would incorrectly make a
            # newly-added FFD inherit the active Standard chain's type.
            stages = (
                tuple(chain_module.chain_stages(target, chain_uuid))
                if chain_uuid else ()
            )
        except (ImportError, AttributeError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            stages = ()
        if len(stages) > 1:
            group = getattr(modifier, "node_group", None)
            stored_type = str(
                group.get(CAGE_TYPE_MARKER, "") if group is not None else "")
            sibling_type = next((
                str(getattr(
                    getattr(find_controller(target, stage),
                            "sdh_cage_deform", None),
                    "cage_type", ""))
                for stage in stages if stage != modifier
                if find_controller(target, stage) is not None
            ), "")
            chain_type = (
                stored_type if stored_type in CAGE_TYPES else sibling_type)
            if chain_type in CAGE_TYPES and cage_type != chain_type:
                if pointer:
                    _CAGE_TYPE_GUARD.add(pointer)
                    _SYNCING.add(pointer)
                try:
                    properties.cage_type = chain_type
                finally:
                    if pointer:
                        _SYNCING.discard(pointer)
                        _CAGE_TYPE_GUARD.discard(pointer)
                cage_type = chain_type
    locked_type = CAGE_TYPE_DEFORM.get(cage_type)
    if locked_type is None:
        if target is not None and modifier is not None:
            remove_ffd_lattice(target, modifier)
            try:
                from .curve import remove_curve_companions
                remove_curve_companions(target, modifier)
            except (ImportError, ReferenceError, RuntimeError):
                pass
        standard_order = tuple(
            deform_type for deform_type in ordered_deform_types(properties)
            if deform_type in STANDARD_DEFORM_ORDER)
        if not set_deform_layers(
                properties, standard_order or ("BEND",), context):
            _controller_update(properties, context)
        return
    if pointer:
        _CAGE_TYPE_GUARD.add(pointer)
        _SYNCING.add(pointer)
    try:
        properties.deform_type = locked_type
        properties.deform_types = {locked_type}
        properties.muted_deform_types = set()
        properties.deform_order = encode_deform_order(
            (locked_type,), {locked_type}, locked_type)
        properties.active_deform_layer = 0
    finally:
        if pointer:
            _SYNCING.discard(pointer)
            _CAGE_TYPE_GUARD.discard(pointer)
    _mirror_primary_to_legacy(properties, pointer)
    if cage_type == "FFD":
        ensure_ffd_point_collection(properties)
        if target is not None and modifier is not None:
            try:
                ensure_ffd_lattice(target, modifier, controller)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
    elif target is not None and modifier is not None:
        remove_ffd_lattice(target, modifier)
    if target is not None and modifier is not None:
        try:
            from .curve import ensure_curve_companions, remove_curve_companions
            if cage_type == "CURVE":
                ensure_curve_companions(target, modifier, controller)
            else:
                remove_curve_companions(target, modifier)
        except (AttributeError, ImportError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            pass
    _controller_update(properties, context)


def _muted_deform_types_update(properties, context):
    pointer, guarded = _property_update_guarded(properties)
    if guarded:
        return
    present = set(getattr(properties, "deform_types", ()))
    muted = set(properties.muted_deform_types) & present
    if muted != set(properties.muted_deform_types):
        if pointer:
            _SYNCING.add(pointer)
        try:
            properties.muted_deform_types = muted
        finally:
            if pointer:
                _SYNCING.discard(pointer)
    _controller_update(properties, context)


def _deform_order_update(properties, context):
    pointer, guarded = _property_update_guarded(properties)
    if guarded:
        return
    normalized = ordered_deform_types(properties)
    encoded = encode_deform_order(
        normalized, properties.deform_types, properties.deform_type)
    if tuple(properties.deform_order) != encoded:
        if pointer:
            _SYNCING.add(pointer)
        try:
            properties.deform_order = encoded
        finally:
            if pointer:
                _SYNCING.discard(pointer)
    _mirror_primary_to_legacy(properties, pointer)
    _controller_update(properties, context)


def _legacy_strength_update(properties, context):
    pointer, guarded = _property_update_guarded(properties)
    if guarded:
        return
    if pointer:
        _SYNCING.add(pointer)
    try:
        if properties.deform_type == "TWIST":
            properties.twist_strength = properties.strength
        elif properties.deform_type == "BEND":
            properties.bend_strength = properties.strength
    finally:
        if pointer:
            _SYNCING.discard(pointer)
    _controller_update(properties, context)


def _legacy_factor_update(properties, context):
    pointer, guarded = _property_update_guarded(properties)
    if guarded:
        return
    if pointer:
        _SYNCING.add(pointer)
    try:
        if properties.deform_type == "STRETCH":
            properties.stretch_factor = properties.factor
        elif properties.deform_type == "TAPER":
            properties.taper_factor = properties.factor
    finally:
        if pointer:
            _SYNCING.discard(pointer)
    controller = getattr(properties, "id_data", None)
    if (
            properties.deform_type == "STRETCH" and
            sync_chain_global_stretch_from_stage(
                controller, properties.stretch_factor)
    ):
        return
    _controller_update(properties, context)


def _legacy_direction_update(properties, context):
    pointer, guarded = _property_update_guarded(properties)
    if guarded:
        return
    if pointer:
        _SYNCING.add(pointer)
    try:
        if properties.deform_type == "BEND":
            properties.bend_direction = properties.direction
    finally:
        if pointer:
            _SYNCING.discard(pointer)
    _controller_update(properties, context)


def _independent_parameter_update(properties, context):
    pointer, guarded = _property_update_guarded(properties)
    if guarded:
        return
    _mirror_primary_to_legacy(properties, pointer)
    _controller_update(properties, context)


def _curve_settings_update(properties, context):
    """Push curve options and refresh the managed helper data."""
    pointer, guarded = _property_update_guarded(properties)
    if guarded:
        return
    _controller_update(properties, context)
    controller = getattr(properties, "id_data", None)
    target = find_target(controller) if is_cage_controller(controller) else None
    modifier = find_modifier(target, controller) if target is not None else None
    if target is None or modifier is None:
        return
    try:
        from .curve import curve_rest_guide_object, ensure_curve_companions
        guide, _stations = ensure_curve_companions(
            target, modifier, controller)
        rest_guide = curve_rest_guide_object(target, modifier)
        resolution = int(getattr(properties, "curve_resolution", 24))
        for curve_object in (guide, rest_guide):
            if curve_object is None:
                continue
            curve_object.data.resolution_u = resolution
            curve_object.data.render_resolution_u = resolution
    except (AttributeError, ImportError, ReferenceError, RuntimeError, TypeError,
            ValueError):
        pass


def _curve_even_stations_update(properties, context):
    """Apply even spacing immediately when persistent station spacing starts."""
    pointer, guarded = _property_update_guarded(properties)
    if guarded or not bool(getattr(properties, "curve_even_stations", False)):
        return
    controller = getattr(properties, "id_data", None)
    target = find_target(controller) if is_cage_controller(controller) else None
    modifier = find_modifier(target, controller) if target is not None else None
    if target is None or modifier is None:
        return
    try:
        from .curve import equalize_curve_stations
        equalize_curve_stations(target, modifier, controller)
    except (AttributeError, ImportError, ReferenceError, RuntimeError, TypeError,
            ValueError):
        pass


def _curve_preset_update(properties, context):
    """Regenerate the selected parametric guide while its controls change."""
    pointer, guarded = _property_update_guarded(properties)
    if guarded or (pointer and pointer in _CURVE_PRESET_UPDATE_GUARD):
        return
    controller = getattr(properties, "id_data", None)
    if (
            not is_cage_controller(controller) or
            str(getattr(properties, "cage_type", "STANDARD")) != "CURVE"
    ):
        return
    target = find_target(controller)
    modifier = find_modifier(target, controller) if target is not None else None
    if target is None or modifier is None:
        return
    try:
        from .curve import (
            _curve_data_has_point_animation,
            curve_guide_object,
        )
        from .curve_presets import apply_curve_preset

        guide = curve_guide_object(target, modifier)
        data = getattr(guide, "data", None)
        if guide is None or _curve_data_has_point_animation(data):
            return
        if pointer:
            _CURVE_PRESET_UPDATE_GUARD.add(pointer)
        try:
            changed = apply_curve_preset(
                guide, properties, properties.curve_preset)
        finally:
            if pointer:
                _CURVE_PRESET_UPDATE_GUARD.discard(pointer)
        if changed:
            _tag_view3d_redraw()
    except (AttributeError, ImportError, ReferenceError, RuntimeError,
            TypeError, ValueError):
        if pointer:
            _CURVE_PRESET_UPDATE_GUARD.discard(pointer)


def curve_control_mode_identifier(properties):
    """Return the relationship mode, deriving it for legacy Curve cages."""
    explicit = False
    try:
        explicit = bool(properties.is_property_set("curve_control_mode"))
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    value = str(getattr(properties, "curve_control_mode", "CURVE") or "CURVE")
    if explicit and value in CURVE_CONTROL_LENGTH_MODE:
        return value
    legacy = str(getattr(properties, "curve_length_mode", "STRETCH") or "STRETCH")
    return "CAGE" if legacy == "PRESERVE" else "CURVE"


def _curve_control_mode_update(properties, context):
    """Map the new relationship choice onto the compatible evaluator input."""
    pointer, guarded = _property_update_guarded(properties)
    if guarded:
        return
    mode = str(getattr(properties, "curve_control_mode", "CURVE") or "CURVE")
    desired_length_mode = CURVE_CONTROL_LENGTH_MODE.get(mode, "STRETCH")
    if pointer:
        _SYNCING.add(pointer)
    try:
        properties.curve_length_mode = desired_length_mode
    finally:
        if pointer:
            _SYNCING.discard(pointer)
    _curve_settings_update(properties, context)
    controller = getattr(properties, "id_data", None)
    if not is_cage_controller(controller):
        return
    try:
        from .curve import sync_curve_cage_relation
        sync_curve_cage_relation(controller, force=True)
    except (AttributeError, ImportError, ReferenceError, RuntimeError, TypeError,
            ValueError):
        pass


def _curve_mode_update(properties, context):
    """Mirror the user-facing Curve mode to the legacy node input enum."""
    pointer, guarded = _property_update_guarded(properties)
    if guarded:
        return
    boundary = CURVE_MODE_BOUNDARY.get(
        str(getattr(properties, "curve_mode", "UNLIMITED")), "EXTEND")
    if pointer:
        _SYNCING.add(pointer)
    try:
        properties.curve_boundary_mode = boundary
    finally:
        if pointer:
            _SYNCING.discard(pointer)
    _curve_settings_update(properties, context)


def _curve_boundary_mode_update(properties, context):
    """Keep older files/scripts changing Boundary Mode compatible."""
    pointer, guarded = _property_update_guarded(properties)
    if guarded:
        return
    mode = CURVE_BOUNDARY_MODE.get(
        str(getattr(properties, "curve_boundary_mode", "EXTEND")),
        "UNLIMITED")
    if pointer:
        _SYNCING.add(pointer)
    try:
        properties.curve_mode = mode
    finally:
        if pointer:
            _SYNCING.discard(pointer)
    _curve_settings_update(properties, context)


def _curve_closed_update(properties, context):
    """Apply the closed state to the managed native Bezier spline."""
    pointer, guarded = _property_update_guarded(properties)
    if guarded:
        return
    controller = getattr(properties, "id_data", None)
    target = find_target(controller) if is_cage_controller(controller) else None
    modifier = find_modifier(target, controller) if target is not None else None
    if bool(getattr(properties, "curve_closed", False)):
        # The lower end is the authored start of the managed guide.  Make it
        # the deterministic seam source when an existing open cage is closed.
        _sync_closed_curve_end_value(
            properties, "BOTTOM", "top_scale", "bottom_scale")
        _sync_closed_curve_end_value(
            properties, "BOTTOM", "top_offset", "bottom_offset")
    try:
        from .curve import (
            _apply_curve_point_handles,
            curve_guide_spline,
            ensure_curve_companions,
            sync_closed_curve_station_ends,
            update_curve_station_mesh,
        )
        guide, _stations = ensure_curve_companions(
            target, modifier, controller)
        spline = curve_guide_spline(guide)
        if spline is not None:
            spline.use_cyclic_u = bool(properties.curve_closed)
            if len(spline.bezier_points) >= 2:
                _apply_curve_point_handles(controller, 0)
                _apply_curve_point_handles(
                    controller, len(spline.bezier_points) - 1)
            guide.data.update_tag()
        if (
                bool(getattr(properties, "curve_closed", False)) and
                sync_closed_curve_station_ends(properties, 0)
        ):
            update_curve_station_mesh(target, modifier, controller)
    except (AttributeError, ImportError, ReferenceError, RuntimeError, TypeError,
            ValueError):
        pass
    _curve_settings_update(properties, context)


def _stretch_factor_update(properties, context):
    """Route a global chain Stretch edit to its shared evaluator input."""
    pointer, guarded = _property_update_guarded(properties)
    if guarded:
        return
    controller = getattr(properties, "id_data", None)
    if sync_chain_global_stretch_from_stage(
            controller, properties.stretch_factor):
        return
    _mirror_primary_to_legacy(properties, pointer)
    _controller_update(properties, context)


def _chain_gap_get(properties):
    controller = getattr(properties, "id_data", None)
    if not is_cage_controller(controller):
        return 0.0
    try:
        target = find_target(controller)
        modifier = find_modifier(target, controller)
        if target is None or modifier is None:
            return 0.0
        from . import chain as chain_module
        if chain_module.stage_chain_index(modifier, 0) <= 0:
            return 0.0
        return float(chain_module.stage_chain_gap(modifier, 0.0))
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return 0.0


def _chain_gap_set(properties, value):
    controller = getattr(properties, "id_data", None)
    if not is_cage_controller(controller):
        return
    pointer = _pointer(controller)
    if pointer and (pointer in _CHAIN_GAP_GUARD or pointer in _SYNCING):
        return
    try:
        target = find_target(controller)
        modifier = find_modifier(target, controller)
        if target is None or modifier is None:
            return
        from . import chain as chain_module
        if chain_module.stage_chain_index(modifier, 0) <= 0:
            return
        if pointer:
            _CHAIN_GAP_GUARD.add(pointer)
        chain_module.set_stage_chain_gap(
            target, modifier, max(float(value), 0.0), preserve_span=True)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return
    finally:
        if pointer:
            _CHAIN_GAP_GUARD.discard(pointer)


def _chain_batch_panel_values(properties):
    """Return the active stage values used to seed inline chain editing."""
    controller = getattr(properties, "id_data", None)
    target = find_target(controller) if is_cage_controller(controller) else None
    modifier = find_modifier(target, controller) if target is not None else None
    gap = 0.0
    if modifier is not None:
        try:
            from . import chain as chain_module
            gap = float(chain_module.stage_chain_gap(modifier, 0.0))
        except (ImportError, AttributeError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            gap = 0.0
    return {
        "chain_batch_scale": tuple(properties.top_scale),
        "chain_batch_offset": tuple(properties.top_offset),
        "chain_batch_gap": gap,
        "chain_batch_angle": float(properties.bend_strength),
        "chain_batch_factor": float(properties.taper_factor),
        "chain_batch_shear": tuple(properties.shear_factors),
        "chain_batch_stage_enabled": bool(properties.stage_enabled),
    }


def _chain_batch_panel_toggle_update(properties, _context):
    if not bool(properties.show_chain_batch_edit):
        return
    controller = getattr(properties, "id_data", None)
    pointer = _pointer(controller) if is_cage_controller(controller) else 0
    if not pointer or pointer in _CHAIN_BATCH_PANEL_GUARD:
        return
    _CHAIN_BATCH_PANEL_GUARD.add(pointer)
    try:
        for name, value in _chain_batch_panel_values(properties).items():
            setattr(properties, name, value)
    finally:
        _CHAIN_BATCH_PANEL_GUARD.discard(pointer)


def _chain_batch_deform_type_update(properties, _context):
    controller = getattr(properties, "id_data", None)
    pointer = _pointer(controller) if is_cage_controller(controller) else 0
    if not pointer or pointer in _CHAIN_BATCH_PANEL_GUARD:
        return
    deform_type = str(properties.chain_batch_deform_type)
    _CHAIN_BATCH_PANEL_GUARD.add(pointer)
    try:
        if deform_type == "BEND":
            properties.chain_batch_angle = float(properties.bend_strength)
        elif deform_type == "BEND_DIRECTION":
            properties.chain_batch_angle = float(properties.bend_direction)
        elif deform_type == "TWIST":
            properties.chain_batch_angle = float(properties.twist_strength)
        elif deform_type == "TAPER":
            properties.chain_batch_factor = float(properties.taper_factor)
        elif deform_type == "STRETCH":
            properties.chain_batch_factor = float(properties.stretch_factor)
        elif deform_type == "SHEAR":
            properties.chain_batch_shear = tuple(properties.shear_factors)
    finally:
        _CHAIN_BATCH_PANEL_GUARD.discard(pointer)


def _chain_batch_value_update(properties, context):
    if not bool(getattr(properties, "show_chain_batch_edit", False)):
        return
    controller = getattr(properties, "id_data", None)
    pointer = _pointer(controller) if is_cage_controller(controller) else 0
    if not pointer or pointer in _CHAIN_BATCH_PANEL_GUARD or pointer in _SYNCING:
        return
    target = find_target(controller)
    modifier = find_modifier(target, controller) if target is not None else None
    if target is None or modifier is None:
        return
    try:
        from . import chain as chain_module
        chain_uuid = chain_module.stage_chain_uuid(modifier)
        if not chain_uuid or len(
                chain_module.chain_stages(target, chain_uuid)) < 2:
            return
        _CHAIN_BATCH_PANEL_GUARD.add(pointer)
        chain_module.apply_chain_batch_edit(
            target,
            modifier,
            chain_uuid=chain_uuid,
            scope=properties.chain_batch_scope,
            operation=properties.chain_batch_operation,
            end_side=properties.chain_batch_end_side,
            assignment="SET",
            scale=tuple(properties.chain_batch_scale),
            offset=tuple(properties.chain_batch_offset),
            gap=float(properties.chain_batch_gap),
            deform_type=properties.chain_batch_deform_type,
            angle_value=float(properties.chain_batch_angle),
            factor_value=float(properties.chain_batch_factor),
            shear_value=tuple(properties.chain_batch_shear),
            stage_enabled=bool(properties.chain_batch_stage_enabled),
            preserve_span=bool(properties.chain_batch_preserve_span),
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError,
            TypeError, ValueError):
        return
    finally:
        _CHAIN_BATCH_PANEL_GUARD.discard(pointer)
    if context is not None and getattr(context, "area", None):
        context.area.tag_redraw()


def ffd_resolution(properties):
    """Return a clamped ``(U, V, W)`` resolution for a dedicated FFD cage."""
    values = (
        getattr(properties, "ffd_resolution_u", FFD_DEFAULT_RESOLUTION[0]),
        getattr(properties, "ffd_resolution_v", FFD_DEFAULT_RESOLUTION[1]),
        getattr(properties, "ffd_resolution_w", FFD_DEFAULT_RESOLUTION[2]),
    )
    limits = (
        FFD_MAX_RESOLUTION_U, FFD_MAX_RESOLUTION_V, FFD_MAX_RESOLUTION_W)
    return tuple(
        min(max(int(value), FFD_MIN_RESOLUTION), limit)
        for value, limit in zip(values, limits)
    )


def ffd_point_count(properties):
    u, v, w = ffd_resolution(properties)
    return u * v * w


def ffd_point_index(u, v, w, resolution):
    """Map lattice coordinates to Blender's point collection order."""
    points_u, points_v, _points_w = resolution
    return int(w) * points_u * points_v + int(v) * points_u + int(u)


def ffd_point_coordinates(index, resolution):
    """Return integer ``(u, v, w)`` coordinates for one point index."""
    points_u, points_v, points_w = resolution
    index = min(max(int(index), 0), points_u * points_v * points_w - 1)
    plane = points_u * points_v
    w, remainder = divmod(index, plane)
    v, u = divmod(remainder, points_u)
    return u, v, w


def ffd_grid_corner_indices(properties):
    """Return the eight actual endpoint indices of a dedicated FFD grid."""
    resolution = ffd_resolution(properties)
    return tuple(
        ffd_point_index(
            resolution[0] - 1 if x_sign > 0.0 else 0,
            resolution[1] - 1 if y_sign > 0.0 else 0,
            resolution[2] - 1 if z_sign > 0.0 else 0,
            resolution,
        )
        for _label, x_sign, y_sign, z_sign in FFD_CORNERS
    )


def ffd_point_is_surface(index, resolution):
    """Return whether a point lies on the outside shell of an FFD grid."""
    u, v, w = ffd_point_coordinates(index, resolution)
    return (
        u in {0, resolution[0] - 1} or
        v in {0, resolution[1] - 1} or
        w in {0, resolution[2] - 1}
    )


@lru_cache(maxsize=250)
def _ffd_visible_topology(resolution, outside_only):
    """Return immutable visible indices for one FFD topology."""
    resolution = tuple(int(value) for value in resolution)
    indices = tuple(range(math.prod(resolution)))
    if not outside_only:
        return indices
    return tuple(
        index for index in indices
        if ffd_point_is_surface(index, resolution)
    )


def ffd_visible_indices(properties):
    """Return editable FFD indices, respecting the native hollow mode."""
    return _ffd_visible_topology(
        ffd_resolution(properties),
        bool(getattr(properties, "ffd_use_outside", False)),
    )


def ffd_symmetry_enabled(properties):
    return bool(getattr(properties, "ffd_symmetry_enabled", False))


def ffd_symmetry_axes(properties):
    """Return the enabled cage-local symmetry planes in stable U/V/W order."""
    raw = getattr(properties, "ffd_symmetry_axes", None)
    try:
        axes = set(raw or ())
    except (TypeError, ValueError):
        axes = set()
    axes.intersection_update(FFD_SYMMETRY_AXIS_ORDER)
    legacy = str(getattr(properties, "ffd_symmetry_axis", "U")).upper()
    if legacy not in FFD_SYMMETRY_AXIS_ORDER:
        legacy = "U"
    # Files written before multi-axis symmetry had only the legacy enum.  The
    # new collection starts at U, so use the saved legacy value until the user
    # touches the new toggle row.
    if (
            not bool(getattr(properties, "ffd_symmetry_axes_initialized", False)) and
            axes == {"U"} and legacy != "U"
    ):
        axes = {legacy}
    return tuple(axis for axis in FFD_SYMMETRY_AXIS_ORDER if axis in axes) or ("U",)


def ffd_symmetry_axis(properties):
    return ffd_symmetry_axes(properties)[0]


def ffd_mirror_point_index(properties, index, axis=None):
    """Return the control-point index mirrored through an FFD center plane."""
    resolution = ffd_resolution(properties)
    coordinates = list(ffd_point_coordinates(index, resolution))
    axis_index = {
        "U": 0,
        "V": 1,
        "W": 2,
    }.get(str(axis or ffd_symmetry_axis(properties)).upper(), 0)
    coordinates[axis_index] = (
        resolution[axis_index] - 1 - coordinates[axis_index])
    return ffd_point_index(*coordinates, resolution)


def ffd_symmetry_expand_indices(properties, indices, *, visible=True):
    """Expand point indices with their selected FFD symmetry counterparts."""
    selected = {int(index) for index in indices}
    if not ffd_symmetry_enabled(properties):
        return selected
    expanded = set(selected)
    # Expand one plane at a time. Each pass mirrors the points introduced by
    # the previous pass, producing the complete U/V/W symmetry orbit when
    # multiple planes are enabled (up to eight points per source point).
    for axis in ffd_symmetry_axes(properties):
        for index in tuple(expanded):
            expanded.add(ffd_mirror_point_index(properties, index, axis))
    if visible:
        expanded.intersection_update(ffd_visible_indices(properties))
    return expanded


FFD_PROPORTIONAL_FALLOFFS = (
    "SMOOTH", "SPHERE", "ROOT", "INVERSE_SQUARE", "SHARP", "LINEAR",
    "CONSTANT", "RANDOM",
)


def ffd_proportional_weight(distance, radius, falloff="SMOOTH", index=0):
    """Return a Blender-style proportional-edit weight in ``[0, 1]``."""
    try:
        distance = max(float(distance), 0.0)
        radius = max(float(radius), EPSILON)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(distance) or not math.isfinite(radius):
        return 0.0
    if distance >= radius:
        return 0.0
    normalized = max(min(1.0 - distance / radius, 1.0), 0.0)
    mode = str(falloff or "SMOOTH").upper()
    if mode == "CONSTANT":
        return 1.0
    if mode == "SPHERE":
        return math.sqrt(max(2.0 * normalized - normalized * normalized, 0.0))
    if mode == "ROOT":
        return math.sqrt(normalized)
    if mode == "INVERSE_SQUARE":
        return normalized * (2.0 - normalized)
    if mode == "SHARP":
        return normalized * normalized
    if mode == "LINEAR":
        return normalized
    if mode == "RANDOM":
        # Blender's random falloff is deterministic for a given element during
        # one transform. A small integer hash keeps repeated redraws stable.
        seed = (int(index) * 1664525 + 1013904223) & 0xFFFFFFFF
        random_value = ((seed >> 8) & 0x00FFFFFF) / 16777215.0
        return normalized * random_value
    return normalized * normalized * (3.0 - 2.0 * normalized)


def ffd_symmetry_transform_values(
        properties, initial_points, values, *, driver_index=None):
    """Mirror transformed FFD point positions across the active center plane.

    Selection mirroring alone would move both sides in the same direction,
    which translates the pair instead of preserving the user's symmetry
    intent.  Transform one member of each selected pair and reflect its local
    displacement for the counterpart.  Existing offsets are retained, so
    enabling symmetry does not unexpectedly reset an already asymmetric cage.
    """
    if not ffd_symmetry_enabled(properties) or not values:
        return values
    resolution = ffd_resolution(properties)
    axes = ffd_symmetry_axes(properties)
    axis_indices = {
        axis: {"U": 0, "V": 1, "W": 2}[axis]
        for axis in axes
    }
    transformed = dict(values)
    selected = set(values).intersection(initial_points)
    if not selected:
        return transformed
    try:
        driver_index = int(driver_index)
    except (TypeError, ValueError):
        driver_index = -1
    processed = set()
    for index in sorted(selected):
        orbit = {index}
        for axis in axes:
            orbit.update(
                ffd_mirror_point_index(properties, member, axis)
                for member in tuple(orbit)
            )
        orbit.intersection_update(selected)
        if len(orbit) < 2:
            continue
        orbit_key = frozenset(orbit)
        if orbit_key in processed:
            continue
        processed.add(orbit_key)
        if driver_index in orbit:
            driver = driver_index
        else:
            driver_coordinates = (
                ffd_point_coordinates(driver_index, resolution)
                if driver_index in selected else None)
            if driver_coordinates is not None:
                def same_driver_side(candidate):
                    coordinates = ffd_point_coordinates(candidate, resolution)
                    return all(
                        (
                            coordinates[axis_index] -
                            (resolution[axis_index] - 1) * 0.5
                        ) * (
                            driver_coordinates[axis_index] -
                            (resolution[axis_index] - 1) * 0.5
                        ) >= -EPSILON
                        for axis_index in axis_indices.values()
                    )
                side_candidates = tuple(
                    candidate for candidate in sorted(orbit)
                    if same_driver_side(candidate)
                )
                driver = side_candidates[0] if side_candidates else min(orbit)
            else:
                driver = min(orbit)
        source = Vector(initial_points[driver])
        value = Vector(values[driver])
        delta = value - source
        driver_coordinates = ffd_point_coordinates(driver, resolution)
        for counterpart in orbit:
            if counterpart == driver:
                continue
            counterpart_coordinates = ffd_point_coordinates(
                counterpart, resolution)
            reflected_delta = delta.copy()
            for axis_index in axis_indices.values():
                driver_distance = (
                    driver_coordinates[axis_index] -
                    (resolution[axis_index] - 1) * 0.5)
                counterpart_distance = (
                    counterpart_coordinates[axis_index] -
                    (resolution[axis_index] - 1) * 0.5)
                if (
                        abs(driver_distance) > EPSILON and
                        abs(counterpart_distance) > EPSILON and
                        driver_distance * counterpart_distance < 0.0
                ):
                    reflected_delta[axis_index] *= -1.0
            transformed[counterpart] = (
                Vector(initial_points[counterpart]) + reflected_delta)
    return transformed


def _ffd_point_update(point, context):
    """Flush a point edit through its owning controller without recursion."""
    owner = getattr(point, "id_data", None)
    properties = getattr(owner, "sdh_cage_deform", None)
    if properties is None:
        return
    pointer = _pointer(owner)
    if pointer and pointer in _FFD_POINT_GUARD:
        return
    _controller_update(properties, context)


class SDHFFDPoint(PropertyGroup):
    """One compact, animatable local offset in a dedicated FFD cage."""

    offset: FloatVectorProperty(
        name="Offset",
        description="Local displacement of this FFD control point",
        size=3,
        default=(0.0, 0.0, 0.0),
        soft_min=-10.0,
        soft_max=10.0,
        update=_ffd_point_update,
    )
    selected: BoolProperty(
        name="Selected",
        description="Include this control point in the next viewport edit",
        default=False,
    )
    influence: FloatProperty(
        name="Influence",
        description=(
            "How strongly this control point contributes to the FFD field"
        ),
        default=1.0,
        min=0.0,
        max=1.0,
        soft_min=0.0,
        soft_max=1.0,
        update=_ffd_point_update,
    )

    # ``weight`` is a readable API alias for scripts and UI code that use the
    # terminology from the FFD panel.  ``influence`` remains the stored RNA
    # field so animation paths have one canonical name.
    def _weight_get(self):
        return float(getattr(self, "influence", 1.0))

    def _weight_set(self, value):
        self.influence = min(max(float(value), 0.0), 1.0)

    weight: FloatProperty(
        name="Weight",
        description="Alias for the FFD point influence",
        min=0.0,
        max=1.0,
        get=_weight_get,
        set=_weight_set,
    )

    def _edit_influence_get(self):
        return self._weight_get()

    def _edit_influence_set(self, value):
        owner = getattr(self, "id_data", None)
        properties = getattr(owner, "sdh_cage_deform", None)
        if properties is None:
            self._weight_set(value)
            return
        visible = set(ffd_visible_indices(properties))
        selected = {
            index for index, point in enumerate(properties.ffd_points)
            if bool(getattr(point, "selected", False)) and index in visible
        }
        self_pointer = _pointer(self)
        active = next(
            (index for index, point in enumerate(properties.ffd_points)
             if _pointer(point) == self_pointer),
            -1,
        )
        if active not in visible:
            return
        selected.add(active)
        delta = float(value) - self._weight_get()
        pointer = _pointer(owner)
        if pointer:
            _FFD_POINT_GUARD.add(pointer)
        try:
            for index in selected:
                point = properties.ffd_points[index]
                point.influence = min(
                    max(float(point.influence) + delta, 0.0), 1.0)
        finally:
            if pointer:
                _FFD_POINT_GUARD.discard(pointer)
        _controller_update(properties, bpy.context)

    edit_influence: FloatProperty(
        name="Weight",
        description=(
            "Set the active and selected FFD point influences together"
        ),
        min=0.0,
        max=1.0,
        options={"SKIP_SAVE"},
        get=_edit_influence_get,
        set=_edit_influence_set,
    )


def _ensure_ffd_point_collection_impl(
        properties, *, preserve=True, previous_resolution=None):
    """Resize the dedicated FFD point collection while retaining authored data."""
    if properties is None or not hasattr(properties, "ffd_points"):
        return 0
    resolution = ffd_resolution(properties)
    count = resolution[0] * resolution[1] * resolution[2]
    collection = properties.ffd_points
    old = tuple(
        (
            tuple(point.offset),
            bool(point.selected),
            min(max(float(getattr(point, "influence", 1.0)), 0.0), 1.0),
        )
        for point in collection
    )
    old_active = int(getattr(properties, "ffd_active_point", 0))
    if previous_resolution is None:
        owner = getattr(properties, "id_data", None)
        try:
            stored = tuple(int(value) for value in owner.get(
                FFD_RESOLUTION_PROP, ())) if owner is not None else ()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            stored = ()
        previous_resolution = stored if len(stored) == 3 else resolution
    previous_resolution = tuple(int(value) for value in previous_resolution)
    old_count = math.prod(previous_resolution) if len(previous_resolution) == 3 else 0
    if old_count != len(old):
        previous_resolution = resolution
    if len(old) == count and previous_resolution == resolution:
        if count:
            properties.ffd_active_point = min(max(
                int(getattr(properties, "ffd_active_point", 0)), 0), count - 1)
        owner = getattr(properties, "id_data", None)
        if owner is not None:
            try:
                owner[FFD_RESOLUTION_PROP] = list(resolution)
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                pass
        return count
    if preserve and old:
        raw_offsets = tuple(
            value for value, _selected, _influence in old)
        raw_influences = tuple(
            influence for _value, _selected, influence in old)
        effective_offsets = tuple(
            tuple(component * influence for component in value)
            for value, influence in zip(raw_offsets, raw_influences)
        )
        offsets = resample_offsets(
            effective_offsets,
            previous_resolution,
            resolution,
            tuple(str(getattr(
                properties, f"ffd_interpolation_{axis}", "KEY_BSPLINE"))
                for axis in ("u", "v", "w")),
        )
        selected = remap_indices(
            (index for index, (_value, is_selected, _influence) in enumerate(old)
             if is_selected),
            previous_resolution,
            resolution,
        )
        selected = frozenset(ffd_symmetry_expand_indices(
            properties, selected, visible=False))
        active = remap_index(
            old_active, previous_resolution, resolution)
        influences = resample_values(
            raw_influences,
            previous_resolution,
            resolution,
            tuple(str(getattr(
                properties, f"ffd_interpolation_{axis}", "KEY_BSPLINE"))
                for axis in ("u", "v", "w")),
        )
        raw_fallback = resample_offsets(
            raw_offsets,
            previous_resolution,
            resolution,
            tuple(str(getattr(
                properties, f"ffd_interpolation_{axis}", "KEY_BSPLINE"))
                for axis in ("u", "v", "w")),
        )
        offsets = tuple(
            tuple(component / influence for component in effective)
            if influence > EPSILON else tuple(fallback)
            for effective, influence, fallback in zip(
                offsets, influences, raw_fallback)
        )
    else:
        offsets = ((0.0, 0.0, 0.0),) * count
        influences = (1.0,) * count
        active = min(max(old_active, 0), max(count - 1, 0))
        selected = frozenset((active,)) if count else frozenset()
    while len(collection) > count:
        collection.remove(len(collection) - 1)
    while len(collection) < count:
        collection.add()
    for index, point in enumerate(collection):
        point.name = f"P{index:03d}"
        point.offset = offsets[index]
        point.influence = min(max(float(influences[index]), 0.0), 1.0)
        point.selected = index in selected
    if count:
        properties.ffd_active_point = min(max(active, 0), count - 1)
    owner = getattr(properties, "id_data", None)
    if owner is not None:
        try:
            owner[FFD_RESOLUTION_PROP] = list(resolution)
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
    return count


def ensure_ffd_point_collection(
        properties, *, preserve=True, previous_resolution=None):
    owner = getattr(properties, "id_data", None)
    pointer = _pointer(owner)
    guarded = bool(pointer and pointer in _FFD_POINT_GUARD)
    if pointer and not guarded:
        _FFD_POINT_GUARD.add(pointer)
    try:
        return _ensure_ffd_point_collection_impl(
            properties,
            preserve=preserve,
            previous_resolution=previous_resolution,
        )
    finally:
        if pointer and not guarded:
            _FFD_POINT_GUARD.discard(pointer)


def ffd_selection_modes(properties):
    """Return the active FFD point/line/face modes in stable UI order."""
    raw = getattr(properties, "ffd_selection_modes", None)
    if isinstance(raw, str):
        modes = {raw}
    else:
        try:
            modes = set(raw or ())
        except (TypeError, ValueError):
            modes = set()
    modes.intersection_update(FFD_SELECTION_MODE_ORDER)
    legacy = str(getattr(properties, "ffd_selection_mode", "POINT"))
    # Files created before multi-select was introduced have the new property
    # at its POINT default while retaining a saved LINE/FACE legacy value.
    # Once the new UI is touched, the marker prevents the old value from
    # overriding a deliberate POINT-only selection.
    if (
            not bool(getattr(properties, "ffd_selection_modes_initialized", False)) and
            modes == {"POINT"} and legacy in {"LINE", "FACE"}
    ):
        modes = {legacy}
    return tuple(mode for mode in FFD_SELECTION_MODE_ORDER if mode in modes) or ("POINT",)


def _ffd_selection_modes_update(properties, context):
    try:
        properties.ffd_selection_modes_initialized = True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        modes = set(properties.ffd_selection_modes)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        modes = {"POINT"}
    modes.intersection_update(FFD_SELECTION_MODE_ORDER)
    if not modes:
        try:
            properties.ffd_selection_modes = {"POINT"}
            return
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            modes = {"POINT"}
    if len(modes) == 1:
        selected = next(iter(modes))
        try:
            if str(properties.ffd_selection_mode) != selected:
                properties.ffd_selection_mode = selected
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            pass
    _controller_update(properties, context)


def _ffd_selection_mode_update(properties, context):
    selected = str(getattr(properties, "ffd_selection_mode", "POINT"))
    if selected not in FFD_SELECTION_MODE_ORDER:
        selected = "POINT"
    try:
        properties.ffd_selection_modes_initialized = True
        modes = set(getattr(properties, "ffd_selection_modes", ()))
        if modes != {selected}:
            properties.ffd_selection_modes = {selected}
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    _controller_update(properties, context)


def _ffd_symmetry_update(properties, context):
    """Refresh the active selection when FFD symmetry settings change."""
    try:
        axis = str(properties.ffd_symmetry_axis).upper()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        axis = "U"
    if axis not in FFD_SYMMETRY_AXIS_ORDER:
        try:
            properties.ffd_symmetry_axis = "U"
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            pass
    points = getattr(properties, "ffd_points", None)
    if points is not None and len(points):
        selected = {
            index for index, point in enumerate(points) if point.selected
        }
        ffd_set_selection(properties, selected)
    _controller_update(properties, context)


def _ffd_symmetry_axes_update(properties, context):
    """Keep multi-axis symmetry non-empty and refresh the selected orbit."""
    try:
        axes = set(properties.ffd_symmetry_axes)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        axes = {"U"}
    axes.intersection_update(FFD_SYMMETRY_AXIS_ORDER)
    try:
        properties.ffd_symmetry_axes_initialized = True
        if not axes:
            properties.ffd_symmetry_axes = {"U"}
            return
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    points = getattr(properties, "ffd_points", None)
    if points is not None and len(points):
        selected = {
            index for index, point in enumerate(points) if point.selected
        }
        ffd_set_selection(properties, selected)
    _controller_update(properties, context)


def _finish_native_ffd_edit(properties, context):
    if not bool(getattr(properties, "ffd_native_edit_mode_active", False)):
        return False
    try:
        from .ffd_native_edit import finish_native_edit_sessions
        return bool(finish_native_edit_sessions(
            context or bpy.context, restore_target=True))
    except (ImportError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _ffd_resolution_update(properties, context):
    pointer = _pointer(getattr(properties, "id_data", None))
    if pointer and (
            pointer in _SYNCING or pointer in _FFD_AXES_LINK_SYNCING):
        return
    if (
            bool(getattr(properties, "ffd_axes_linked", True)) and
            len({
                int(properties.ffd_resolution_u),
                int(properties.ffd_resolution_v),
                int(properties.ffd_resolution_w),
            }) != 1
    ):
        # Direct RNA/script edits to one axis are an explicit request for an
        # asymmetric grid. Reflect that intent in the panel instead of showing
        # a linked value that no longer represents the runtime lattice.
        properties[FFD_AXES_LINKED_KEY] = False
    _finish_native_ffd_edit(properties, context)
    ensure_ffd_point_collection(properties)
    controller = getattr(properties, "id_data", None)
    if not is_cage_controller(controller):
        return
    target = find_target(controller)
    modifier = find_modifier(target, controller) if target is not None else None
    if target is not None and modifier is not None:
        try:
            ensure_ffd_lattice(target, modifier, controller)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    _controller_update(properties, context)


def _ffd_use_outside_update(properties, context):
    """Apply native hollow-lattice evaluation and hide interior handles."""
    _finish_native_ffd_edit(properties, context)
    ensure_ffd_point_collection(properties)
    visible = set(ffd_visible_indices(properties))
    for index, point in enumerate(properties.ffd_points):
        if index not in visible:
            point.selected = False
    if visible and int(properties.ffd_active_point) not in visible:
        properties.ffd_active_point = min(visible)
    controller = getattr(properties, "id_data", None)
    if is_cage_controller(controller):
        target = find_target(controller)
        modifier = find_modifier(target, controller) if target is not None else None
        if target is not None and modifier is not None:
            try:
                ensure_ffd_lattice(target, modifier, controller)
            except (AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError):
                pass
    _controller_update(properties, context)


def _ffd_interpolation_update(properties, context):
    """Mirror the authored U/V/W basis into the native lattice data."""
    pointer = _pointer(getattr(properties, "id_data", None))
    if pointer and (
            pointer in _SYNCING or pointer in _FFD_AXES_LINK_SYNCING):
        return
    if (
            bool(getattr(properties, "ffd_axes_linked", True)) and
            len({
                str(properties.ffd_interpolation_u),
                str(properties.ffd_interpolation_v),
                str(properties.ffd_interpolation_w),
            }) != 1
    ):
        properties[FFD_AXES_LINKED_KEY] = False
    _finish_native_ffd_edit(properties, context)
    controller = getattr(properties, "id_data", None)
    if is_cage_controller(controller):
        target = find_target(controller)
        modifier = find_modifier(target, controller) if target is not None else None
        if target is not None and modifier is not None:
            try:
                ensure_ffd_lattice(target, modifier, controller)
            except (AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError):
                pass
    _controller_update(properties, context)


def _ffd_axes_linked_get(properties):
    """Default equal grids to linked while preserving asymmetric old files."""
    if FFD_AXES_LINKED_KEY in properties:
        return bool(properties[FFD_AXES_LINKED_KEY])
    return (
        len({
            int(properties.ffd_resolution_u),
            int(properties.ffd_resolution_v),
            int(properties.ffd_resolution_w),
        }) == 1 and
        len({
            str(properties.ffd_interpolation_u),
            str(properties.ffd_interpolation_v),
            str(properties.ffd_interpolation_w),
        }) == 1
    )


def _ffd_axes_linked_set(properties, value):
    properties[FFD_AXES_LINKED_KEY] = bool(value)


def _ffd_linked_resolution_get(properties):
    return int(properties.ffd_resolution_u)


def _ffd_linked_resolution_set(properties, value):
    pointer = _pointer(getattr(properties, "id_data", None))
    _FFD_AXES_LINK_SYNCING.add(pointer)
    try:
        value = min(max(int(value), FFD_MIN_RESOLUTION), FFD_MAX_RESOLUTION_U)
        properties.ffd_resolution_u = value
        properties.ffd_resolution_v = value
        properties.ffd_resolution_w = value
    finally:
        _FFD_AXES_LINK_SYNCING.discard(pointer)


def _ffd_linked_interpolation_get(properties):
    identifier = str(properties.ffd_interpolation_u)
    try:
        return FFD_INTERPOLATION_ORDER.index(identifier)
    except ValueError:
        return FFD_INTERPOLATION_ORDER.index("KEY_BSPLINE")


def _ffd_linked_interpolation_set(properties, value):
    pointer = _pointer(getattr(properties, "id_data", None))
    _FFD_AXES_LINK_SYNCING.add(pointer)
    try:
        if isinstance(value, str):
            identifier = value
        else:
            index = min(max(int(value), 0), len(FFD_INTERPOLATION_ORDER) - 1)
            identifier = FFD_INTERPOLATION_ORDER[index]
        properties.ffd_interpolation_u = identifier
        properties.ffd_interpolation_v = identifier
        properties.ffd_interpolation_w = identifier
    finally:
        _FFD_AXES_LINK_SYNCING.discard(pointer)


def _ffd_axes_linked_update(properties, context):
    """Link point count and interpolation, using U as the shared source."""
    if not properties.ffd_axes_linked:
        area = getattr(context, "area", None) if context else None
        if area is not None:
            area.tag_redraw()
        return
    pointer = _pointer(getattr(properties, "id_data", None))
    _FFD_AXES_LINK_SYNCING.add(pointer)
    try:
        resolution = int(properties.ffd_resolution_u)
        interpolation = str(properties.ffd_interpolation_u)
        properties.ffd_resolution_v = resolution
        properties.ffd_resolution_w = resolution
        properties.ffd_interpolation_v = interpolation
        properties.ffd_interpolation_w = interpolation
    finally:
        _FFD_AXES_LINK_SYNCING.discard(pointer)
    _ffd_resolution_update(properties, context)


def _ffd_guard_update(properties, context):
    """Refresh the native FFD after changing its safety mode."""
    _finish_native_ffd_edit(properties, context)
    controller = getattr(properties, "id_data", None)
    if str(getattr(properties, "ffd_guard_mode", "OFF")).upper() != "SAFE":
        _FFD_GUARD_VALID_OFFSETS.pop(_pointer(controller), None)
    if is_cage_controller(controller):
        target = find_target(controller)
        modifier = find_modifier(target, controller) if target is not None else None
        if target is not None and modifier is not None:
            try:
                ensure_ffd_lattice(target, modifier, controller)
            except (AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError):
                pass
    _controller_update(properties, context)


def ffd_point_offset(properties, index):
    """Read one dedicated FFD point offset, falling back to legacy corners."""
    index = int(index)
    points = getattr(properties, "ffd_points", None)
    if points is not None and len(points) > index >= 0:
        try:
            return Vector(points[index].offset)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    values = normalized_ffd_offsets(getattr(properties, "ffd_offsets", ()))
    return values[min(max(index, 0), len(values) - 1)]


def ffd_point_influence(properties, index):
    """Read one point's clamped authored influence in the FFD field."""
    points = getattr(properties, "ffd_points", None)
    if points is not None and len(points) > int(index) >= 0:
        try:
            return min(max(float(getattr(points[int(index)], "influence", 1.0)),
                           0.0), 1.0)
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            pass
    return 1.0


def ffd_point_effective_offset(properties, index):
    """Return the displacement actually contributed by one FFD point."""
    return ffd_point_offset(properties, index) * ffd_point_influence(
        properties, index)


def ffd_runtime_interpolations(properties):
    """Return the native basis, using linear interpolation for safe FFDs."""
    if str(getattr(properties, "ffd_guard_mode", "OFF")).upper() == "SAFE":
        return (SAFE_INTERPOLATION,) * 3
    values = []
    for axis in ("u", "v", "w"):
        interpolation = str(getattr(
            properties, f"ffd_interpolation_{axis}", "KEY_BSPLINE"))
        if interpolation not in {
                "KEY_LINEAR", "KEY_CARDINAL", "KEY_CATMULL_ROM",
                "KEY_BSPLINE"}:
            interpolation = "KEY_BSPLINE"
        values.append(interpolation)
    return tuple(values)


def _ffd_guard_offsets_snapshot(properties):
    points = getattr(properties, "ffd_points", ())
    return tuple(tuple(float(value) for value in point.offset) for point in points)


def ffd_guard_offsets(properties, candidate_offsets, *, baseline_offsets=None):
    """Return a safe raw-offset field for the active FFD guard mode."""
    candidate = tuple(tuple(float(value) for value in offset)
                      for offset in candidate_offsets)
    if str(getattr(properties, "ffd_guard_mode", "OFF")).upper() != "SAFE":
        return candidate, 1.0, math.inf, math.inf
    resolution = tuple(ffd_resolution(properties))
    count = math.prod(resolution)
    if len(candidate) != count:
        return candidate, 1.0, -math.inf, -math.inf
    cached = None
    cached_baseline_ratio = None
    influences = tuple(
        ffd_point_influence(properties, index) for index in range(count))
    size = tuple(float(value) for value in properties.size)
    if baseline_offsets is None:
        baseline_offsets = None
        owner = getattr(properties, "id_data", None)
        cached = _FFD_GUARD_VALID_OFFSETS.get(_pointer(owner))
        if (
                cached is not None and
                _same_rna_value(cached.get("controller"), owner) and
                tuple(cached.get("resolution", ())) == resolution
        ):
            baseline_offsets = cached.get("offsets")
        if baseline_offsets is None:
            baseline_offsets = ((0.0, 0.0, 0.0),) * count
    baseline = tuple(tuple(float(value) for value in offset)
                     for offset in baseline_offsets)
    if cached is None:
        owner = getattr(properties, "id_data", None)
        cached = _FFD_GUARD_VALID_OFFSETS.get(_pointer(owner))
    if (
            cached is not None and
            tuple(cached.get("resolution", ())) == resolution and
            tuple(cached.get("offsets", ())) == baseline and
            tuple(cached.get("size", ())) == size and
            tuple(cached.get("influences", ())) == influences
    ):
        try:
            cached_baseline_ratio = float(cached.get("ratio"))
        except (TypeError, ValueError, OverflowError):
            cached_baseline_ratio = None
    return clamp_offsets(
        size, resolution, baseline, candidate, influences,
        threshold=MIN_JACOBIAN_RATIO, baseline_ratio=cached_baseline_ratio,
    )


def _apply_ffd_guard(properties, controller=None):
    """Clamp authored offsets before rebuilding the native lattice."""
    if str(getattr(properties, "ffd_guard_mode", "OFF")).upper() != "SAFE":
        if controller is not None:
            _FFD_GUARD_VALID_OFFSETS.pop(_pointer(controller), None)
        return False
    candidate = _ffd_guard_offsets_snapshot(properties)
    safe, fraction, baseline_ratio, candidate_ratio = ffd_guard_offsets(
        properties, candidate)
    changed = safe != candidate
    pointer = _pointer(controller or getattr(properties, "id_data", None))
    if changed:
        if pointer:
            _FFD_POINT_GUARD.add(pointer)
        try:
            for point, value in zip(properties.ffd_points, safe):
                point.offset = value
        finally:
            if pointer:
                _FFD_POINT_GUARD.discard(pointer)
    if baseline_ratio >= MIN_JACOBIAN_RATIO:
        influences = tuple(
            ffd_point_influence(properties, index)
            for index in range(len(safe)))
        cached_ratio = (
            min(float(baseline_ratio), float(candidate_ratio))
            if float(fraction) >= 1.0 else
            float(MIN_JACOBIAN_RATIO)
        )
        _FFD_GUARD_VALID_OFFSETS[pointer] = {
            "controller": controller,
            "resolution": tuple(ffd_resolution(properties)),
            "offsets": tuple(safe),
            "ratio": cached_ratio,
            "size": tuple(float(value) for value in properties.size),
            "influences": influences,
        }
    return changed


def ffd_selected_indices(properties):
    points = getattr(properties, "ffd_points", None)
    if points is None or not len(points):
        return (min(max(int(getattr(properties, "ffd_active_point", 0)), 0), 7),)
    visible = set(ffd_visible_indices(properties))
    selected = tuple(
        index for index, point in enumerate(points)
        if point.selected and index in visible)
    active = min(max(
        int(getattr(properties, "ffd_active_point", 0)), 0),
        len(points) - 1)
    if active not in visible and visible:
        active = min(visible)
    return selected or (active,)


@lru_cache(maxsize=8192)
def _ffd_selection_group_topology(
        resolution, outside_only, anchor_index, mode, axis):
    """Return one point/line/face group for an immutable FFD topology."""
    resolution = tuple(int(value) for value in resolution)
    count = math.prod(resolution)
    if count <= 0:
        return ()
    anchor_index = min(max(int(anchor_index), 0), count - 1)
    mode = str(mode or "POINT")
    visible = set(_ffd_visible_topology(resolution, bool(outside_only)))
    if anchor_index not in visible:
        return ()
    if mode == "LINE":
        anchor_u, anchor_v, anchor_w = ffd_point_coordinates(
            anchor_index, resolution)
        line_axis = str(axis or "V").upper()
        if line_axis == "U":
            if anchor_u >= resolution[0] - 1:
                return ()
            indices = {
                ffd_point_index(anchor_u, anchor_v, anchor_w, resolution),
                ffd_point_index(anchor_u + 1, anchor_v, anchor_w, resolution),
            }
        elif line_axis == "W":
            if anchor_w >= resolution[2] - 1:
                return ()
            indices = {
                ffd_point_index(anchor_u, anchor_v, anchor_w, resolution),
                ffd_point_index(anchor_u, anchor_v, anchor_w + 1, resolution),
            }
        else:
            if anchor_v >= resolution[1] - 1:
                return ()
            indices = {
                ffd_point_index(anchor_u, anchor_v, anchor_w, resolution),
                ffd_point_index(anchor_u, anchor_v + 1, anchor_w, resolution),
            }
    elif mode == "FACE":
        anchor_u, anchor_v, anchor_w = ffd_point_coordinates(
            anchor_index, resolution)
        plane = str(axis or "UW").upper()
        if plane == "UV":
            indices = {
                ffd_point_index(u, v, anchor_w, resolution)
                for v in (anchor_v, anchor_v + 1)
                for u in (anchor_u, anchor_u + 1)
            }
        elif plane == "VW":
            indices = {
                ffd_point_index(anchor_u, v, w, resolution)
                for v in (anchor_v, anchor_v + 1)
                for w in (anchor_w, anchor_w + 1)
            }
        else:
            indices = {
                ffd_point_index(u, anchor_v, w, resolution)
                for w in (anchor_w, anchor_w + 1)
                for u in (anchor_u, anchor_u + 1)
            }
    else:
        indices = {anchor_index}
    return tuple(sorted(indices.intersection(visible)))


def ffd_selection_indices(
        properties, anchor_index, mode=None, *, axis=None, ensure=True):
    """Return the visible FFD selection represented by one picked point.

    ``axis`` identifies the selected line-segment direction (U/V/W) or face
    plane (UV/UW/VW). Keeping the expansion in the core makes viewport
    picking, box selection, transforms, and keyframe scope agree on the same
    selection.
    """
    if ensure:
        ensure_ffd_point_collection(properties)
    resolved_mode = str(mode or ffd_selection_modes(properties)[0])
    return _ffd_selection_group_topology(
        ffd_resolution(properties),
        bool(getattr(properties, "ffd_use_outside", False)),
        int(anchor_index),
        resolved_mode,
        str(axis or ("V" if resolved_mode == "LINE" else "UW")).upper(),
    )


@lru_cache(maxsize=750)
def _ffd_selection_entity_topology(resolution, outside_only, mode):
    """Return every selectable entity for one immutable FFD topology."""
    resolution = tuple(int(value) for value in resolution)
    visible = set(_ffd_visible_topology(resolution, bool(outside_only)))
    mode = str(mode or "POINT")
    if mode == "LINE":
        entities = []
        for axis in ("U", "V", "W"):
            varying = {"U": 0, "V": 1, "W": 2}[axis]
            fixed_axes = tuple(index for index in range(3) if index != varying)
            for first in range(resolution[fixed_axes[0]]):
                for second in range(resolution[fixed_axes[1]]):
                    for segment in range(resolution[varying] - 1):
                        coordinates = [0, 0, 0]
                        coordinates[fixed_axes[0]] = first
                        coordinates[fixed_axes[1]] = second
                        coordinates[varying] = segment
                        anchor = ffd_point_index(*coordinates, resolution)
                        group = _ffd_selection_group_topology(
                            resolution, outside_only, anchor, mode, axis)
                        # Hollow FFD does not expose a partial edge that
                        # would leave a one-point line handle floating inside
                        # the cage.
                        if len(group) == 2 and set(group).issubset(visible):
                            entities.append((anchor, axis))
        return tuple(entities)
    if mode == "FACE":
        entities = []
        for plane in ("UV", "UW", "VW"):
            varying = tuple({"U": 0, "V": 1, "W": 2}[letter]
                            for letter in plane)
            fixed = ({0, 1, 2} - set(varying)).pop()
            for fixed_value in range(resolution[fixed]):
                for first in range(resolution[varying[0]] - 1):
                    for second in range(resolution[varying[1]] - 1):
                        coordinates = [0, 0, 0]
                        coordinates[fixed] = fixed_value
                        coordinates[varying[0]] = first
                        coordinates[varying[1]] = second
                        anchor = ffd_point_index(*coordinates, resolution)
                        group = _ffd_selection_group_topology(
                            resolution, outside_only, anchor, mode, plane)
                        # Hollow FFD must not expose a partial face whose
                        # missing interior vertices make drawing and picking
                        # disagree. Only complete visible grid quads are
                        # selectable.
                        if len(group) == 4 and set(group).issubset(visible):
                            entities.append((anchor, plane))
        return tuple(entities)
    return tuple((index, "POINT") for index in sorted(visible))


def ffd_selection_entities(properties, mode=None, *, ensure=True):
    """Return entries for every adjacent FFD line segment or grid face."""
    if ensure:
        ensure_ffd_point_collection(properties)
    return _ffd_selection_entity_topology(
        ffd_resolution(properties),
        bool(getattr(properties, "ffd_use_outside", False)),
        str(mode or ffd_selection_modes(properties)[0]),
    )


def ffd_selection_anchor_indices(properties, mode=None, *, ensure=True):
    """Return one native point index for each visible line or face control.

    Line entities cover every adjacent segment in all U/V/W directions. Face
    entities cover every UV, UW, and VW grid cell. Keeping the anchor as a real
    point index lets the existing point-offset and animation paths remain
    unchanged.
    """
    if ensure:
        ensure_ffd_point_collection(properties)
    return tuple(anchor for anchor, _orientation in ffd_selection_entities(
        properties, mode, ensure=False))


def ffd_expand_selection(properties, indices, mode=None):
    """Expand a picked set for one explicit point/line/face operation.

    Multiple modes control which gizmos are visible together. A single box
    selection still needs deterministic semantics, so its first visible mode
    owns the operation unless the caller identifies a mode explicitly.
    """
    expanded = set()
    selected = set(indices)
    modes = (
        (str(mode),) if mode is not None else
        (ffd_selection_modes(properties)[0],)
    )
    for active_mode in modes:
        for anchor, orientation in ffd_selection_entities(properties, active_mode):
            group = ffd_selection_indices(
                properties, anchor, active_mode,
                axis=None if orientation == "POINT" else orientation,
            )
            # A point controller represents exactly its anchor. The previous
            # unconditional POINT branch expanded every point whenever point
            # mode was enabled alongside LINE/FACE, so even a tiny box around
            # one point selected the complete lattice. Lines and faces still
            # expand when the box intersects any of their constituent points.
            if (
                    (active_mode == "POINT" and anchor in selected) or
                    (active_mode != "POINT" and selected.intersection(group))
            ):
                expanded.update(group)
    return tuple(sorted(expanded))


def _screen_point_in_box(point, bounds):
    left, right, bottom, top = bounds
    return left <= point.x <= right and bottom <= point.y <= top


def _screen_segment_intersects_box(first, second, bounds):
    """Return whether one projected segment intersects an axis-aligned box."""
    first = Vector((float(first[0]), float(first[1])))
    second = Vector((float(second[0]), float(second[1])))
    if (
            _screen_point_in_box(first, bounds) or
            _screen_point_in_box(second, bounds)
    ):
        return True
    left, right, bottom, top = bounds
    delta = second - first
    minimum = 0.0
    maximum = 1.0
    for direction, distance in (
            (-delta.x, first.x - left),
            (delta.x, right - first.x),
            (-delta.y, first.y - bottom),
            (delta.y, top - first.y)):
        if abs(direction) <= EPSILON:
            if distance < 0.0:
                return False
            continue
        factor = distance / direction
        if direction < 0.0:
            minimum = max(minimum, factor)
        else:
            maximum = min(maximum, factor)
        if minimum > maximum:
            return False
    return True


def _trim_screen_polyline(points, ratio):
    """Keep the centered visible percentage of a projected control line."""
    points = tuple(Vector((float(point[0]), float(point[1]))) for point in points)
    if len(points) < 2:
        return points
    lengths = tuple(
        (points[index + 1] - points[index]).length
        for index in range(len(points) - 1))
    total = sum(lengths)
    if total <= EPSILON:
        return (sum(points, Vector((0.0, 0.0))) / len(points),)
    ratio = min(max(float(ratio), 0.10), 1.0)
    start_distance = total * (1.0 - ratio) * 0.5
    end_distance = total - start_distance

    def sample(distance):
        traversed = 0.0
        for first, second, length in zip(points, points[1:], lengths):
            if length <= EPSILON:
                continue
            if traversed + length >= distance:
                factor = (distance - traversed) / length
                return first.lerp(second, min(max(factor, 0.0), 1.0))
            traversed += length
        return points[-1].copy()

    trimmed = [sample(start_distance)]
    traversed = 0.0
    for point, length in zip(points[1:], lengths):
        traversed += length
        if start_distance < traversed < end_distance:
            trimmed.append(point.copy())
    trimmed.append(sample(end_distance))
    return tuple(trimmed)


def _screen_polyline_intersects_box(points, bounds):
    if not points:
        return False
    if len(points) == 1:
        return _screen_point_in_box(points[0], bounds)
    return any(
        _screen_segment_intersects_box(first, second, bounds)
        for first, second in zip(points, points[1:]))


def _screen_convex_hull(points):
    unique = sorted({(float(point[0]), float(point[1])) for point in points})
    if len(unique) <= 1:
        return tuple(Vector(point) for point in unique)

    def cross(origin, first, second):
        return (
            (first[0] - origin[0]) * (second[1] - origin[1]) -
            (first[1] - origin[1]) * (second[0] - origin[0]))

    lower = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0.0:
            lower.pop()
        lower.append(point)
    upper = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0.0:
            upper.pop()
        upper.append(point)
    return tuple(Vector(point) for point in lower[:-1] + upper[:-1])


def _screen_point_in_polygon(point, polygon):
    inside = False
    previous = polygon[-1]
    for current in polygon:
        crosses = (current.y > point.y) != (previous.y > point.y)
        if crosses:
            denominator = previous.y - current.y
            boundary_x = (
                (previous.x - current.x) * (point.y - current.y) /
                denominator + current.x)
            if point.x < boundary_x:
                inside = not inside
        previous = current
    return inside


def _screen_polygon_intersects_box(points, bounds):
    polygon = _screen_convex_hull(points)
    if not polygon:
        return False
    if len(polygon) == 1:
        return _screen_point_in_box(polygon[0], bounds)
    if len(polygon) == 2:
        return _screen_segment_intersects_box(polygon[0], polygon[1], bounds)
    if any(_screen_point_in_box(point, bounds) for point in polygon):
        return True
    if any(
            _screen_segment_intersects_box(first, second, bounds)
            for first, second in zip(polygon, (*polygon[1:], polygon[0]))
    ):
        return True
    left, right, bottom, top = bounds
    return any(
        _screen_point_in_polygon(Vector(corner), polygon)
        for corner in (
            (left, bottom), (right, bottom),
            (right, top), (left, top))
    )


def _ffd_screen_value(value):
    """Return one projected point and optional view depth from a callback value."""
    if value is None:
        return None, None
    try:
        screen = Vector((float(value[0]), float(value[1])))
    except (IndexError, KeyError, TypeError, ValueError):
        return None, None
    try:
        depth = float(value[2]) if len(value) >= 3 else None
        if depth is not None and not math.isfinite(depth):
            depth = None
    except (IndexError, KeyError, TypeError, ValueError):
        depth = None
    return screen, depth


def _ffd_face_winding_indices(properties, anchor, orientation, group):
    """Return one grid face in perimeter order for screen-space hit tests."""
    resolution = ffd_resolution(properties)
    group = set(group)
    if not group:
        return ()
    u, v, w = ffd_point_coordinates(anchor, resolution)
    plane = str(orientation or "UW").upper()
    if plane == "UV":
        coordinates = (
            (u, v, w), (u + 1, v, w),
            (u + 1, v + 1, w), (u, v + 1, w),
        )
    elif plane == "VW":
        coordinates = (
            (u, v, w), (u, v + 1, w),
            (u, v + 1, w + 1), (u, v, w + 1),
        )
    else:
        coordinates = (
            (u, v, w), (u + 1, v, w),
            (u + 1, v, w + 1), (u, v, w + 1),
        )
    ordered = tuple(
        ffd_point_index(*coordinate, resolution)
        for coordinate in coordinates)
    visible = tuple(index for index in ordered if index in group)
    return visible or tuple(sorted(group))


def _build_ffd_projected_selection_entities(
        properties, project_point, mode, *, line_ratio=0.60, face_ratio=0.35):
    """Build the same projected point, line, and face shapes shown by FFD."""
    entities = []
    for order, (anchor, orientation) in enumerate(
            ffd_selection_entities(properties, mode, ensure=False)):
        group = tuple(ffd_selection_indices(
            properties, anchor, mode,
            axis=None if orientation == "POINT" else orientation,
            ensure=False,
        ))
        if not group:
            continue
        display_indices = (
            _ffd_face_winding_indices(properties, anchor, orientation, group)
            if mode == "FACE" else group)
        screen_points = []
        depths = []
        for index in display_indices:
            screen, depth = _ffd_screen_value(project_point(index))
            if screen is None:
                screen_points = []
                break
            screen_points.append(screen)
            if depth is not None:
                depths.append(depth)
        if not screen_points:
            continue
        if mode == "LINE":
            geometry = _trim_screen_polyline(screen_points, line_ratio)
        elif mode == "FACE":
            center = sum(screen_points, Vector((0.0, 0.0))) / len(screen_points)
            ratio = min(max(float(face_ratio), 0.10), 1.0)
            geometry = tuple(
                center + (point - center) * ratio
                for point in screen_points)
        else:
            geometry = tuple(screen_points)
        entities.append({
            "anchor": anchor,
            "orientation": orientation,
            "group": group,
            "geometry": geometry,
            "depth": (sum(depths) / len(depths)) if depths else None,
            "order": order,
        })
    return tuple(entities)


def _ffd_projected_selection_entities(
        properties, project_point, mode, *, line_ratio=0.60, face_ratio=0.35):
    return projected_entity_cache.get(
        properties,
        project_point,
        mode,
        builder=_build_ffd_projected_selection_entities,
        resolution_function=ffd_resolution,
        point_index_function=ffd_point_index,
        screen_value_function=_ffd_screen_value,
        line_ratio=line_ratio,
        face_ratio=face_ratio,
    )


def ffd_projected_entity_cache_info():
    return projected_entity_cache.info()


def _screen_polyline_distance(point, points, *, closed=False):
    """Return the shortest screen-space distance from a point to a polyline."""
    point = Vector(point)
    points = tuple(Vector(item) for item in points)
    if not points:
        return math.inf
    if len(points) == 1:
        return (point - points[0]).length
    pairs = tuple(zip(points, points[1:]))
    if closed:
        pairs += ((points[-1], points[0]),)
    nearest = math.inf
    for first, second in pairs:
        edge = second - first
        denominator = edge.length_squared
        factor = (
            max(0.0, min(1.0, edge.dot(point - first) / denominator))
            if denominator > EPSILON else 0.0)
        nearest = min(nearest, (point - (first + edge * factor)).length)
    return nearest


def _ffd_projected_entities_overlap(mode, first, second, *, tolerance=4.0):
    """Identify controls that are visually coincident from the current view."""
    first_geometry = tuple(first["geometry"])
    second_geometry = tuple(second["geometry"])
    if not first_geometry or not second_geometry:
        return False
    if mode == "POINT":
        return (first_geometry[0] - second_geometry[0]).length <= tolerance
    if mode == "LINE":
        if len(first_geometry) < 2 or len(second_geometry) < 2:
            return False
        forward = max(
            (first_geometry[0] - second_geometry[0]).length,
            (first_geometry[-1] - second_geometry[-1]).length)
        reverse = max(
            (first_geometry[0] - second_geometry[-1]).length,
            (first_geometry[-1] - second_geometry[0]).length)
        return min(forward, reverse) <= tolerance
    first_polygon = _screen_convex_hull(first_geometry)
    second_polygon = _screen_convex_hull(second_geometry)
    if len(first_polygon) < 3 or len(second_polygon) < 3:
        return False
    first_center = sum(first_polygon, Vector((0.0, 0.0))) / len(first_polygon)
    second_center = sum(second_polygon, Vector((0.0, 0.0))) / len(second_polygon)
    return (
        _screen_point_in_polygon(first_center, second_polygon) and
        _screen_point_in_polygon(second_center, first_polygon))


def _ffd_front_visible_entities(mode, candidates):
    """Drop only controls hidden behind an identical projected controller."""
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            candidate["depth"] is None,
            candidate["depth"] if candidate["depth"] is not None else 0.0,
            candidate["order"],
        ),
    )
    visible = []
    for candidate in ordered:
        depth = candidate["depth"]
        if depth is not None and any(
                previous["depth"] is not None and
                previous["depth"] <= depth + EPSILON and
                _ffd_projected_entities_overlap(mode, previous, candidate)
                for previous in visible):
            continue
        visible.append(candidate)
    return tuple(visible)


def ffd_screen_selection_entity(
        properties, project_point, position, *, line_ratio=0.60,
        face_ratio=0.35, point_radius=8.0, line_radius=8.0,
        face_margin=4.0):
    """Pick the front-most visible FFD controller under one screen position."""
    position = Vector((float(position[0]), float(position[1])))
    for mode in ffd_selection_modes(properties):
        candidates = []
        for candidate in _ffd_projected_selection_entities(
                properties, project_point, mode,
                line_ratio=line_ratio, face_ratio=face_ratio):
            geometry = candidate["geometry"]
            if mode == "POINT":
                distance = (position - geometry[0]).length
                hit = distance <= point_radius
            elif mode == "LINE":
                distance = _screen_polyline_distance(position, geometry)
                hit = distance <= line_radius
            else:
                polygon = _screen_convex_hull(geometry)
                distance = _screen_polyline_distance(
                    position, polygon, closed=True)
                hit = (
                    len(polygon) >= 3 and
                    (_screen_point_in_polygon(position, polygon) or
                     distance <= face_margin))
            if hit:
                candidate = dict(candidate)
                candidate["distance"] = distance
                candidates.append(candidate)
        visible = _ffd_front_visible_entities(mode, candidates)
        if visible:
            picked = min(
                visible,
                key=lambda candidate: (
                    candidate["distance"],
                    candidate["depth"] is None,
                    candidate["depth"] if candidate["depth"] is not None else 0.0,
                    candidate["order"],
                ),
            )
            return picked["anchor"], mode, picked["orientation"]
    return None


def ffd_box_selection_indices(
        properties, project_point, bounds, *,
        line_ratio=0.60, face_ratio=0.35):
    """Select projected FFD handles using the same priority as direct clicks.

    Point, line, and face controls may be shown together. The first enabled
    controller type with a hit owns one box operation, so a point box never
    expands through line or face groups.  Unlike a direct click, a box select
    is intentionally depth-penetrating: every controller whose projected
    geometry intersects the rectangle is selected, including controls behind
    the front layer.  The front-most hit still becomes the active controller
    for predictable subsequent transforms.
    """
    left, right = sorted((float(bounds[0]), float(bounds[1])))
    bottom, top = sorted((float(bounds[2]), float(bounds[3])))
    normalized_bounds = (left, right, bottom, top)
    for active_mode in ffd_selection_modes(properties):
        candidates = []
        for candidate in _ffd_projected_selection_entities(
                properties, project_point, active_mode,
                line_ratio=line_ratio, face_ratio=face_ratio):
            geometry = candidate["geometry"]
            if active_mode == "POINT":
                hit = _screen_point_in_box(geometry[0], normalized_bounds)
            elif active_mode == "LINE":
                hit = _screen_polyline_intersects_box(
                    geometry, normalized_bounds)
            else:
                hit = _screen_polygon_intersects_box(
                    geometry, normalized_bounds)
            if hit:
                candidates.append(candidate)
        if candidates:
            visible = _ffd_front_visible_entities(active_mode, candidates)
            selected = set()
            for candidate in candidates:
                selected.update(candidate["group"])
            active = visible[0]["anchor"] if visible else candidates[0]["anchor"]
            return (
                tuple(sorted(selected)),
                active,
                active_mode,
            )
    return (), None, None


def ffd_box_selection_update(current, boxed, operation="SET"):
    """Apply one repeatable SET/ADD/SUBTRACT box-selection operation."""
    current = {int(index) for index in current}
    boxed = {int(index) for index in boxed}
    operation = str(operation)
    if operation == "ADD":
        return current | boxed
    if operation == "SUBTRACT":
        return current - boxed
    return boxed


def ffd_pointer_selection_update(current, group, *, extend=False):
    """Resolve an FFD controller press without breaking a pending group drag.

    A press on an already selected point, line, or face keeps the complete
    selection available for dragging.  ``collapse_on_click`` tells the modal
    to restore ordinary single-click behavior if the pointer is released
    without crossing the drag threshold.
    """
    current = {int(index) for index in current}
    group = {int(index) for index in group}
    if extend:
        selected = (
            current - group if group.issubset(current)
            else current | group)
        return selected, False
    if group and group.issubset(current):
        return current, current != group
    return group, False


def _ffd_blank_box_release_state(
        last_time, last_position, start, end, now, *,
        click_distance=8.0, click_interval=0.45):
    """Track only blank clicks; completed drags must not arm modal exit."""
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


def ffd_keyframe_indices(properties):
    """Return the FFD points affected by the current keyframe preference."""
    visible = tuple(ffd_visible_indices(properties))
    if not visible:
        return ()
    preference = get_pref()
    scope = str(getattr(preference, "ffd_keyframe_scope", "ALL_VISIBLE"))
    if scope == "SELECTED":
        return ffd_selected_indices(properties)
    return visible


def ffd_set_selection(properties, indices, *, active=None):
    points = getattr(properties, "ffd_points", None)
    if points is None:
        return
    selected = ffd_symmetry_expand_indices(properties, indices)
    for index, point in enumerate(points):
        point.selected = index in selected
    if active is not None and len(points):
        properties.ffd_active_point = min(max(int(active), 0), len(points) - 1)


def ffd_lattice_object(target, modifier):
    """Resolve the hidden native lattice belonging to one FFD stage."""
    group = getattr(modifier, "node_group", None)
    name = str(group.get(FFD_LATTICE_MARKER, "")) if group else ""
    modifier_uuid = cage_modifier_uuid(modifier)
    try:
        obj = bpy.data.objects.get(name) if name else None
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        obj = None
    if (
            getattr(obj, "type", None) == "LATTICE" and
            getattr(obj, "parent", None) == target and
            str(obj.get(FFD_LATTICE_MODIFIER_MARKER, "") or modifier_uuid) ==
            modifier_uuid
    ):
        return obj
    for candidate in _data_objects_snapshot():
        try:
            if (
                    candidate.type == "LATTICE" and
                    candidate.parent == target and
                    candidate.get(FFD_LATTICE_MARKER, False) and
                    str(candidate.get(FFD_LATTICE_MODIFIER_MARKER, "")) ==
                    modifier_uuid
            ):
                if group is not None:
                    group[FFD_LATTICE_MARKER] = candidate.name
                return candidate
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            continue
    return None


def _ffd_lattice_modifier(target, modifier, lattice, *, create=True):
    marker = f"{getattr(modifier, 'name', '')} FFD"
    for candidate in getattr(target, "modifiers", ()):
        if (
                getattr(candidate, "type", None) == "LATTICE" and
                getattr(candidate, "object", None) == lattice
        ):
            break
    else:
        if not create:
            return None
        candidate = target.modifiers.new(name=marker, type="LATTICE")
        candidate.object = lattice
        candidate.strength = 1.0
    candidate.name = marker
    if getattr(target, "type", None) in {"CURVE", "FONT"}:
        try:
            candidate.use_apply_on_spline = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
    stage_index = tuple(target.modifiers).index(modifier)
    candidate_index = tuple(target.modifiers).index(candidate)
    desired_index = stage_index if candidate_index < stage_index else stage_index + 1
    if candidate_index != desired_index:
        try:
            target.modifiers.move(candidate_index, desired_index)
        except (AttributeError, RuntimeError, TypeError):
            pass
    return candidate


def _ffd_scope_vertex_group_name(modifier):
    """Return a collision-resistant managed vertex-group name."""
    identifier = str(cage_modifier_uuid(modifier) or
                    getattr(modifier, "name", "stage"))
    return f"{FFD_VERTEX_GROUP_PREFIX}{identifier}"


def _ffd_base_matrix(controller, size):
    """Return the authored FFD box matrix before Unlimited extension."""
    target = getattr(controller, "parent", None)
    frame = (
        cage_local_matrix(target, controller)
        if target is not None else
        Matrix.Translation(Vector(controller.location)) @
        _controller_rotation_xyz(controller).to_matrix().to_4x4()
    )
    # RNA transform components update immediately, while matrix_world can lag
    # until the next depsgraph evaluation. Build from the authored components
    # so an axis switch updates the native lattice in the same interaction.
    rotation = frame.to_3x3().normalized()
    basis = rotation @ Matrix.Diagonal(Vector((
        max(abs(float(size[0])), EPSILON),
        max(abs(float(size[1])), EPSILON),
        max(abs(float(size[2])), EPSILON),
    )))
    matrix = basis.to_4x4()
    matrix.translation = frame.translation
    return matrix


def _ffd_bound_box_in_base(target, base_matrix):
    """Return target bound-box extents in the authored FFD coordinates."""
    try:
        transform = base_matrix.inverted_safe() @ target.matrix_world
        points = tuple(transform @ Vector(point) for point in target.bound_box)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        points = ()
    if not points:
        return Vector((-0.5, -0.5, -0.5)), Vector((0.5, 0.5, 0.5))
    minimum = Vector((
        min(point.x for point in points),
        min(point.y for point in points),
        min(point.z for point in points),
    ))
    maximum = Vector((
        max(point.x for point in points),
        max(point.y for point in points),
        max(point.z for point in points),
    ))
    return minimum, maximum


def _ffd_unlimited_layout(target, controller, properties, resolution, size):
    """Build a hidden grid that continues the authored FFD beyond its box.

    Blender's native Lattice modifier holds its terminal control layers for
    geometry outside the lattice object.  Unlimited needs the opposite: the
    boundary slope must continue.  The hidden lattice therefore gains evenly
    spaced control layers until it covers the target bounds.  Original grid
    locations remain aligned to those hidden layers whenever the native
    64-point axis limit permits it.
    """
    base_matrix = _ffd_base_matrix(controller, size)
    if str(getattr(properties, "mode", "LIMITED")) != "UNLIMITED":
        return resolution, Vector((-0.5,) * 3), Vector((0.5,) * 3), base_matrix

    target_minimum, target_maximum = _ffd_bound_box_in_base(
        target, base_matrix)
    layout_resolution = []
    domain_minimum = []
    domain_maximum = []
    for axis, count in enumerate(resolution):
        count = max(int(count), 2)
        step = 1.0 / float(count - 1)
        target_min = float(target_minimum[axis])
        target_max = float(target_maximum[axis])
        lower = max(int(math.ceil(
            max(-0.5 - target_min, 0.0) / step - EPSILON)), 0)
        upper = max(int(math.ceil(
            max(target_max - 0.5, 0.0) / step - EPSILON)), 0)
        # Keep the evaluated target just inside the hidden field so its outer
        # vertices receive the extrapolated slope rather than another native
        # terminal hold at the expanded boundary.
        if lower:
            lower += 1
        if upper:
            upper += 1
        total = count + lower + upper
        if total > 64:
            # Preserve coverage when an exceptionally small authored cage is
            # used on a very large object.  The capped grid becomes a dense
            # linear sample of the same extrapolated source field.
            domain_min = min(-0.5, target_min - step)
            domain_max = max(0.5, target_max + step)
            total = 64
        else:
            domain_min = -0.5 - lower * step
            domain_max = 0.5 + upper * step
        layout_resolution.append(total)
        domain_minimum.append(domain_min)
        domain_maximum.append(domain_max)

    minimum = Vector(domain_minimum)
    maximum = Vector(domain_maximum)
    span = maximum - minimum
    center = (minimum + maximum) * 0.5
    rotation = controller.matrix_world.to_3x3().normalized()
    basis = rotation @ Matrix.Diagonal(Vector((
        max(abs(float(size[0]) * span.x), EPSILON),
        max(abs(float(size[1]) * span.y), EPSILON),
        max(abs(float(size[2]) * span.z), EPSILON),
    )))
    matrix = basis.to_4x4()
    matrix.translation = (
        controller.matrix_world.translation +
        rotation @ Vector((
            float(size[0]) * center.x,
            float(size[1]) * center.y,
            float(size[2]) * center.z,
        ))
    )
    return tuple(layout_resolution), minimum, maximum, matrix


def _ffd_axis_sample_weights(coordinate, count):
    """Return linear source-grid weights, including endpoint extrapolation."""
    count = max(int(count), 2)
    last = count - 1
    coordinate = float(coordinate)
    if coordinate <= 0.0:
        return ((0, 1.0 - coordinate), (1, coordinate))
    if coordinate >= float(last):
        distance = coordinate - float(last)
        return ((last - 1, -distance), (last, 1.0 + distance))
    left = min(max(int(math.floor(coordinate)), 0), last - 1)
    factor = coordinate - float(left)
    return ((left, 1.0 - factor), (left + 1, factor))


def _ffd_extended_offset(properties, source_resolution, source_coordinate):
    """Evaluate one separable linear extension of the authored offset grid."""
    axis_weights = tuple(
        _ffd_axis_sample_weights(coordinate, count)
        for coordinate, count in zip(source_coordinate, source_resolution)
    )
    hollow = bool(getattr(properties, "ffd_use_outside", False))
    result = Vector((0.0, 0.0, 0.0))
    for u, weight_u in axis_weights[0]:
        for v, weight_v in axis_weights[1]:
            for w, weight_w in axis_weights[2]:
                index = ffd_point_index(u, v, w, source_resolution)
                if hollow and not ffd_point_is_surface(index, source_resolution):
                    continue
                result += (
                    ffd_point_effective_offset(properties, index) *
                    weight_u * weight_v * weight_w
                )
    return result


def _ffd_scope_stage_key(target, modifier):
    return (_pointer(target), _pointer(modifier))


def clear_ffd_scope_cache(target=None, modifier=None):
    """Clear transient FFD membership state without touching authored data."""
    if target is None and modifier is None:
        _FFD_SCOPE_MESH_CACHE.clear()
        _FFD_SCOPE_STAGE_CACHE.clear()
        _FFD_SCOPE_MESH_DIRTY.clear()
        _FFD_SCOPE_REFRESH_QUEUE.clear()
        _FFD_SCOPE_MESH_WRITE_GUARD.clear()
        return

    target_pointer = _pointer(target)
    modifier_pointer = _pointer(modifier)
    removed_controller_pointers = set()
    for key, cached in tuple(_FFD_SCOPE_STAGE_CACHE.items()):
        if target_pointer and key[0] != target_pointer:
            continue
        if modifier_pointer and key[1] != modifier_pointer:
            continue
        controller_pointer = int(cached.get("controller_pointer", 0) or 0)
        if controller_pointer:
            removed_controller_pointers.add(controller_pointer)
        _FFD_SCOPE_STAGE_CACHE.pop(key, None)

    for mesh_pointer, cached in tuple(_FFD_SCOPE_MESH_CACHE.items()):
        controllers = cached.get("controllers", {})
        for pointer, pair in tuple(controllers.items()):
            cached_target = pair[0] if pair else None
            if pointer in removed_controller_pointers or (
                    not modifier_pointer and target_pointer and
                    _pointer(cached_target) == target_pointer):
                controllers.pop(pointer, None)
                _FFD_SCOPE_REFRESH_QUEUE.pop(pointer, None)
        if not controllers:
            _FFD_SCOPE_MESH_CACHE.pop(mesh_pointer, None)
            _FFD_SCOPE_MESH_DIRTY.discard(mesh_pointer)
            _FFD_SCOPE_MESH_WRITE_GUARD.discard(mesh_pointer)


def _prune_ffd_scope_cache(live_controller_pointers):
    """Release coordinate arrays after their managed stages disappear."""
    live = set(live_controller_pointers)
    for key, cached in tuple(_FFD_SCOPE_STAGE_CACHE.items()):
        if int(cached.get("controller_pointer", 0) or 0) not in live:
            _FFD_SCOPE_STAGE_CACHE.pop(key, None)
    for mesh_pointer, cached in tuple(_FFD_SCOPE_MESH_CACHE.items()):
        controllers = cached.get("controllers", {})
        for pointer in tuple(controllers):
            if pointer not in live:
                controllers.pop(pointer, None)
                _FFD_SCOPE_REFRESH_QUEUE.pop(pointer, None)
        if not controllers:
            _FFD_SCOPE_MESH_CACHE.pop(mesh_pointer, None)
            _FFD_SCOPE_MESH_DIRTY.discard(mesh_pointer)
            _FFD_SCOPE_MESH_WRITE_GUARD.discard(mesh_pointer)


def _ffd_scope_mesh_coordinates(target, controller):
    """Return one shared float32 coordinate array and its cache generation."""
    mesh = getattr(target, "data", None)
    mesh_pointer = _pointer(mesh)
    if mesh is None or not mesh_pointer:
        return None, 0, None
    cached = _FFD_SCOPE_MESH_CACHE.get(mesh_pointer)
    if cached is None or not _same_rna_value(cached.get("mesh"), mesh):
        cached = {
            "mesh": mesh,
            "coordinates": None,
            "generation": 0,
            "controllers": {},
        }
        _FFD_SCOPE_MESH_CACHE[mesh_pointer] = cached
    controller_pointer = _pointer(controller)
    if controller_pointer:
        for other_pointer, other_cache in tuple(
                _FFD_SCOPE_MESH_CACHE.items()):
            if other_pointer == mesh_pointer:
                continue
            other_cache.get("controllers", {}).pop(controller_pointer, None)
            if not other_cache.get("controllers"):
                _FFD_SCOPE_MESH_CACHE.pop(other_pointer, None)
                _FFD_SCOPE_MESH_DIRTY.discard(other_pointer)
                _FFD_SCOPE_MESH_WRITE_GUARD.discard(other_pointer)
        cached["controllers"][controller_pointer] = (target, controller)

    vertex_count = len(getattr(mesh, "vertices", ()))
    coordinates = cached.get("coordinates")
    dirty = mesh_pointer in _FFD_SCOPE_MESH_DIRTY
    if (
            dirty or coordinates is None or
            int(getattr(coordinates, "shape", (0,))[0]) != vertex_count
    ):
        flat = np.empty(vertex_count * 3, dtype=np.float32)
        if vertex_count:
            mesh.vertices.foreach_get("co", flat)
        coordinates = flat.reshape((vertex_count, 3))
        cached["coordinates"] = coordinates
        cached["generation"] = int(cached.get("generation", 0)) + 1
        _FFD_SCOPE_MESH_DIRTY.discard(mesh_pointer)
    return coordinates, int(cached["generation"]), cached


def _ffd_scope_membership_digest(indices):
    values = np.ascontiguousarray(indices, dtype=np.int32)
    return hashlib.blake2b(
        memoryview(values).cast("B"), digest_size=16).digest()


def _mark_ffd_scope_mesh_dirty(mesh):
    """Invalidate one source mesh and queue its live FFD stages for refresh."""
    mesh_pointer = _pointer(mesh)
    if not mesh_pointer or mesh_pointer in _FFD_SCOPE_MESH_WRITE_GUARD:
        return False
    cached = _FFD_SCOPE_MESH_CACHE.get(mesh_pointer)
    if cached is None:
        return False
    _FFD_SCOPE_MESH_DIRTY.add(mesh_pointer)
    queued = False
    for controller_pointer, pair in tuple(
            cached.get("controllers", {}).items()):
        target, controller = pair
        try:
            if (
                    target is None or controller is None or
                    not is_cage_controller(controller) or
                    getattr(target, "data", None) != mesh
            ):
                cached["controllers"].pop(controller_pointer, None)
                continue
            _FFD_SCOPE_REFRESH_QUEUE[controller_pointer] = controller
            queued = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            cached["controllers"].pop(controller_pointer, None)
    if queued:
        _schedule_chain_reconnect()
    return queued


def _mark_ffd_scope_target_dirty(target):
    """Queue every dedicated FFD stage after a target data-block change."""
    mesh = getattr(target, "data", None)
    mesh_pointer = _pointer(mesh)
    if not isinstance(mesh, bpy.types.Mesh) or not mesh_pointer:
        return False
    _FFD_SCOPE_MESH_DIRTY.add(mesh_pointer)
    queued = False
    for modifier in cage_modifiers(target):
        try:
            controller = find_controller(target, modifier)
            properties = getattr(controller, "sdh_cage_deform", None)
            pointer = _pointer(controller)
            if (
                    not pointer or properties is None or
                    str(getattr(properties, "cage_type", "")) != "FFD"
            ):
                continue
            _FFD_SCOPE_REFRESH_QUEUE[pointer] = controller
            queued = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            continue
    if queued:
        _schedule_chain_reconnect()
    return queued


def _ffd_scope_tracks_target(target):
    """Return whether the target already contributes to its mesh cache."""
    mesh_pointer = _pointer(getattr(target, "data", None))
    cached = _FFD_SCOPE_MESH_CACHE.get(mesh_pointer)
    if cached is None:
        return False
    for pair in cached.get("controllers", {}).values():
        try:
            if pair and _same_rna_value(pair[0], target):
                return True
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            continue
    return False


def _drain_ffd_scope_refresh_queue():
    """Refresh invalidated memberships outside dependency-graph evaluation."""
    if not _FFD_SCOPE_REFRESH_QUEUE:
        return 0
    pending = tuple(_FFD_SCOPE_REFRESH_QUEUE.values())
    _FFD_SCOPE_REFRESH_QUEUE.clear()
    refreshed = 0
    for controller in pending:
        try:
            target, modifier = _target_and_modifier(controller)
            properties = getattr(controller, "sdh_cage_deform", None)
            if (
                    target is None or modifier is None or properties is None or
                    str(getattr(properties, "cage_type", "")) != "FFD"
            ):
                continue
            ensure_ffd_lattice(target, modifier, controller)
            refreshed += 1
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            continue
    return refreshed


def _configure_ffd_scope(target, modifier, controller, lattice,
                          lattice_modifier):
    """Apply a cached point-domain mask for Within Box and Chained FFD."""
    properties = getattr(controller, "sdh_cage_deform", None)
    if properties is None or lattice_modifier is None:
        return None
    mode = str(getattr(properties, "mode", "LIMITED") or "LIMITED")
    needs_scope = mode in {"WITHIN_BOX", "CHAINED"}
    if getattr(target, "type", None) != "MESH":
        try:
            lattice_modifier.vertex_group = ""
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
        clear_ffd_scope_cache(target, modifier)
        return None
    groups = getattr(target, "vertex_groups", None)
    if groups is None:
        return None
    name = _ffd_scope_vertex_group_name(modifier)
    group = groups.get(name) if hasattr(groups, "get") else None
    if not needs_scope:
        try:
            lattice_modifier.vertex_group = ""
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
        if group is not None:
            try:
                groups.remove(group)
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                pass
        clear_ffd_scope_cache(target, modifier)
        return None

    group_created = group is None
    if group_created:
        try:
            group = groups.new(name=name)
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            return None
    try:
        relative_matrix = lattice.matrix_world.inverted_safe() @ target.matrix_world
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None
    lattice_points = tuple(getattr(lattice.data, "points", ()))
    if lattice_points:
        lattice_minimum = Vector((
            min(float(point.co.x) for point in lattice_points),
            min(float(point.co.y) for point in lattice_points),
            min(float(point.co.z) for point in lattice_points),
        ))
        lattice_maximum = Vector((
            max(float(point.co.x) for point in lattice_points),
            max(float(point.co.y) for point in lattice_points),
            max(float(point.co.z) for point in lattice_points),
        ))
    else:
        lattice_minimum = Vector((-0.5, -0.5, -0.5))
        lattice_maximum = Vector((0.5, 0.5, 0.5))

    coordinates, generation, mesh_cache = _ffd_scope_mesh_coordinates(
        target, controller)
    if coordinates is None or mesh_cache is None:
        return None
    stage_key = _ffd_scope_stage_key(target, modifier)
    cached = _FFD_SCOPE_STAGE_CACHE.get(stage_key)
    try:
        group_token = (_pointer(group), str(group.name), int(group.index))
        topology_token = str(lattice.get(FFD_LATTICE_TOPOLOGY_TOKEN, ""))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        group_token = (0, name, -1)
        topology_token = ""
    signature = (
        _pointer(getattr(target, "data", None)),
        len(coordinates),
        generation,
        mode,
        tuple(round(float(value), 8)
              for row in relative_matrix for value in row),
        tuple(round(float(value), 8)
              for value in (*lattice_minimum, *lattice_maximum)),
        topology_token,
        group_token,
    )
    group_bound = str(getattr(lattice_modifier, "vertex_group", "")) == name
    if (
            not group_created and group_bound and cached is not None and
            cached.get("signature") == signature
    ):
        return group

    matrix_values = np.asarray(relative_matrix, dtype=np.float32)
    minimum = np.asarray(tuple(lattice_minimum), dtype=np.float32)
    maximum = np.asarray(tuple(lattice_maximum), dtype=np.float32)
    epsilon = np.float32(CHAIN_BOUNDARY_EPSILON)
    linear = matrix_values[:3, :3]
    translation = matrix_values[:3, 3]
    if mode == "CHAINED":
        local_y = coordinates @ linear[1] + translation[1]
        mask = (
            (local_y >= minimum[1] - epsilon) &
            (local_y <= maximum[1] + epsilon))
    else:
        local = coordinates @ linear.T + translation
        mask = np.all(
            (local >= minimum - epsilon) &
            (local <= maximum + epsilon),
            axis=1,
        )
    indices = np.asarray(np.flatnonzero(mask), dtype=np.int32)
    digest = _ffd_scope_membership_digest(indices)
    mesh_pointer = _pointer(getattr(target, "data", None))
    force_apply = bool(
        group_created or not group_bound or cached is None or
        int(cached.get("mesh_pointer", 0) or 0) != mesh_pointer or
        int(cached.get("applied_generation", -1)) != generation)
    membership_changed = bool(
        cached is None or cached.get("member_digest") != digest or
        int(cached.get("member_count", -1)) != len(indices))

    if force_apply or membership_changed:
        if mesh_pointer:
            _FFD_SCOPE_MESH_WRITE_GUARD.add(mesh_pointer)
        try:
            group.remove(range(len(coordinates)))
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            pass
        if len(indices):
            try:
                group.add(indices.tolist(), 1.0, "REPLACE")
            except (AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError):
                return None
    try:
        lattice_modifier.vertex_group = group.name
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return None
    _FFD_SCOPE_STAGE_CACHE[stage_key] = {
        "signature": signature,
        "member_digest": digest,
        "member_count": len(indices),
        "mesh_pointer": mesh_pointer,
        "applied_generation": generation,
        "controller_pointer": _pointer(controller),
    }
    return group


def ensure_ffd_companion_order(target):
    """Repair every dedicated FFD companion and keep each pair adjacent."""
    repaired = 0
    for stage in cage_modifiers(target):
        controller = find_controller(target, stage)
        properties = getattr(controller, "sdh_cage_deform", None)
        if properties is None or str(properties.cage_type) != "FFD":
            continue
        if ensure_ffd_lattice(target, stage, controller) is not None:
            repaired += 1
    return repaired


def _ensure_ffd_lattice_topology(
        target, modifier, lattice, resolution, interpolations):
    """Return a hidden lattice whose native evaluation cache matches RNA.

    Blender can retain the previous basis after changing either point counts or
    interpolation on an already-referenced Lattice object. Replacing only the
    data block is not sufficient on every 5.x build, so topology changes rebuild
    this hidden runtime object. Authored points and animation remain on the cage
    controller and are reapplied immediately below.
    """
    data = lattice.data
    resolution = tuple(int(value) for value in resolution)
    interpolations = tuple(str(value) for value in interpolations)
    current = tuple(
        str(getattr(data, f"interpolation_type_{axis}", ""))
        for axis in ("u", "v", "w")
    )
    if (
            (data.points_u, data.points_v, data.points_w) == resolution and
            current == interpolations
    ):
        return lattice

    companion = next((
        candidate for candidate in tuple(getattr(target, "modifiers", ()))
        if (
            getattr(candidate, "type", None) == "LATTICE" and
            getattr(candidate, "object", None) == lattice
        )
    ), None)
    if companion is not None:
        try:
            target.modifiers.remove(companion)
        except (ReferenceError, RuntimeError):
            companion = None
    old_object_name = str(lattice.name)
    old_data_name = str(data.name)
    old_matrix = lattice.matrix_world.copy()
    collections = tuple(getattr(lattice, "users_collection", ()))

    replacement_data = bpy.data.lattices.new(f"{old_data_name} Runtime")
    replacement_data.points_u = resolution[0]
    replacement_data.points_v = resolution[1]
    replacement_data.points_w = resolution[2]
    for axis, interpolation in zip(("u", "v", "w"), interpolations):
        setattr(replacement_data, f"interpolation_type_{axis}", interpolation)

    replacement = bpy.data.objects.new(
        f"{old_object_name} Runtime", replacement_data)
    collection = collections[0] if collections else _collection_for(
        bpy.context, target)
    if collection is not None:
        collection.objects.link(replacement)
    else:
        bpy.context.collection.objects.link(replacement)
    replacement.parent = target
    replacement.matrix_parent_inverse = Matrix.Identity(4)
    replacement.matrix_world = old_matrix
    replacement[FFD_LATTICE_MARKER] = True
    replacement[FFD_LATTICE_MODIFIER_MARKER] = cage_modifier_uuid(modifier)
    # RNA data pointers can be recycled when U/V/W are edited one after
    # another. Keep a stable, observable generation token for diagnostics and
    # migration code without exposing runtime helper objects to the user.
    replacement[FFD_LATTICE_TOPOLOGY_TOKEN] = uuid.uuid4().hex
    replacement.hide_render = True
    replacement.hide_select = True
    replacement.display_type = "WIRE"
    try:
        replacement.hide_set(True)
    except (AttributeError, RuntimeError):
        pass

    group = getattr(modifier, "node_group", None)
    if group is not None:
        group[FFD_LATTICE_MARKER] = replacement.name
    try:
        bpy.data.objects.remove(lattice, do_unlink=True)
    except (ReferenceError, RuntimeError):
        pass
    try:
        if data.users == 0:
            bpy.data.lattices.remove(data)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    try:
        replacement.name = old_object_name
        replacement_data.name = old_data_name
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    if group is not None:
        group[FFD_LATTICE_MARKER] = replacement.name
    _ffd_lattice_modifier(target, modifier, replacement)
    return replacement


def _ffd_lattice_data_span(data):
    """Return the authored coordinate span of each native lattice axis."""
    points = tuple(getattr(data, "points", ()))
    if not points:
        return Vector((1.0, 1.0, 1.0))
    minimum = Vector((
        min(float(point.co.x) for point in points),
        min(float(point.co.y) for point in points),
        min(float(point.co.z) for point in points),
    ))
    maximum = Vector((
        max(float(point.co.x) for point in points),
        max(float(point.co.y) for point in points),
        max(float(point.co.z) for point in points),
    ))
    return Vector(tuple(
        max(abs(float(value)), EPSILON)
        for value in (maximum - minimum)
    ))


def _ffd_runtime_matrix(matrix, data):
    """Scale a logical cage matrix to Blender's native point coordinates."""
    logical_scale = Vector(tuple(
        max(abs(float(value)), EPSILON) for value in matrix.to_scale()))
    data_span = _ffd_lattice_data_span(data)
    rotation = matrix.to_3x3().normalized()
    result = rotation @ Matrix.Diagonal(Vector(tuple(
        max(abs(value / span), EPSILON)
        for value, span in zip(logical_scale, data_span)
    )))
    result = result.to_4x4()
    result.translation = matrix.translation
    return result


def ensure_ffd_lattice(target, modifier, controller):
    """Create/update the native multi-point lattice for a dedicated FFD stage."""
    properties = getattr(controller, "sdh_cage_deform", None)
    if properties is None or str(getattr(properties, "cage_type", "")) != "FFD":
        return None
    ensure_ffd_point_collection(properties)
    group = getattr(modifier, "node_group", None)
    if group is None:
        return None
    lattice = ffd_lattice_object(target, modifier)
    if (
            lattice is not None and
            bool(getattr(properties, "ffd_native_edit_mode_active", False)) and
            str(getattr(lattice, "mode", "OBJECT")) == "EDIT"
    ):
        # Native Lattice Edit is authoritative until its session is finalized;
        # a depsgraph sync must not push stale controller values over edits.
        return lattice
    previous_active_modifier = getattr(
        getattr(target, "modifiers", None), "active", None)
    if (
            previous_active_modifier is not None and
            getattr(previous_active_modifier, "type", None) == "LATTICE" and
            getattr(previous_active_modifier, "object", None) == lattice
    ):
        # Older builds could leave the internal companion active after a
        # topology rebuild. Treat the public cage stage as its UI owner.
        previous_active_modifier = modifier
    if lattice is not None and getattr(lattice, "parent", None) != target:
        lattice = None
    if lattice is None:
        data = bpy.data.lattices.new(f"{modifier.name} FFD Data")
        lattice = bpy.data.objects.new(f"{modifier.name} FFD Lattice", data)
        lattice[FFD_LATTICE_MARKER] = True
        lattice[FFD_LATTICE_TOPOLOGY_TOKEN] = uuid.uuid4().hex
        lattice.hide_render = True
        lattice.hide_select = True
        lattice.display_type = "WIRE"
        collection = _collection_for(
            bpy.context, target) if target is not None else None
        if collection is not None:
            collection.objects.link(lattice)
        else:
            bpy.context.collection.objects.link(lattice)
        lattice.parent = target
        lattice.matrix_parent_inverse = Matrix.Identity(4)
        try:
            lattice.hide_set(True)
        except (AttributeError, RuntimeError):
            pass
        group[FFD_LATTICE_MARKER] = lattice.name
    lattice[FFD_LATTICE_MARKER] = True
    lattice[FFD_LATTICE_MODIFIER_MARKER] = cage_modifier_uuid(modifier)
    if not lattice.get(FFD_LATTICE_TOPOLOGY_TOKEN):
        lattice[FFD_LATTICE_TOPOLOGY_TOKEN] = uuid.uuid4().hex
    # Do not mirror TARGET_UUID onto helpers: target ownership migration treats
    # every non-controller carrying that UUID as a duplicated deformation target.
    if TARGET_UUID in lattice:
        del lattice[TARGET_UUID]
    group[FFD_LATTICE_MARKER] = lattice.name
    source_resolution = ffd_resolution(properties)
    size = Vector(properties.size)
    resolution, domain_minimum, domain_maximum, lattice_matrix = (
        _ffd_unlimited_layout(
            target, controller, properties, source_resolution, size))
    unlimited = str(getattr(properties, "mode", "LIMITED")) == "UNLIMITED"
    # Native ``use_outside`` means a hollow control lattice, not unlimited
    # geometry.  The expanded Unlimited grid has its own sampled shell, so it
    # must evaluate every hidden layer while authored interior offsets are
    # explicitly excluded by ``_ffd_extended_offset``.
    _apply_ffd_guard(properties, controller)
    interpolations = ffd_runtime_interpolations(properties)
    lattice = _ensure_ffd_lattice_topology(
        target, modifier, lattice, resolution, interpolations)
    data = lattice.data
    data.use_outside = bool(
        getattr(properties, "ffd_use_outside", False) and not unlimited)
    for axis, interpolation in zip(("u", "v", "w"), interpolations):
        setattr(data, f"interpolation_type_{axis}", interpolation)
    # Lattice base coordinates are read-only. Blender expands their native
    # span with resolution (for example six V points occupy -2.5..2.5), while
    # the public cage must retain the same authored size. Scale the hidden
    # object by that actual span, then express physical point offsets in the
    # resulting local basis.
    domain_span = domain_maximum - domain_minimum
    lattice_matrix = _ffd_runtime_matrix(lattice_matrix, data)
    runtime_scale = Vector(tuple(
        max(abs(float(value)), EPSILON)
        for value in lattice_matrix.to_scale()
    ))
    for index, point in enumerate(data.points):
        base = Vector(point.co)
        if unlimited:
            u, v, w = ffd_point_coordinates(index, resolution)
            source_coordinate = tuple(
                (
                    domain_minimum[axis] +
                    coordinate / max(resolution[axis] - 1, 1) *
                    domain_span[axis] + 0.5
                ) * max(source_resolution[axis] - 1, 1)
                for axis, coordinate in enumerate((u, v, w))
            )
            offset = _ffd_extended_offset(
                properties, source_resolution, source_coordinate)
        else:
            offset = ffd_point_effective_offset(properties, index)
        normalized = Vector((
            offset.x / runtime_scale.x,
            offset.y / runtime_scale.y,
            offset.z / runtime_scale.z,
        ))
        point.co_deform = base + normalized
    try:
        lattice.matrix_world = lattice_matrix
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    lattice_modifier = _ffd_lattice_modifier(target, modifier, lattice)
    try:
        modifiers = tuple(target.modifiers)
        if previous_active_modifier in modifiers:
            target.modifiers.active = previous_active_modifier
        elif modifier in modifiers:
            target.modifiers.active = modifier
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    if lattice_modifier is not None:
        lattice_modifier.object = lattice
        lattice_modifier.strength = 1.0
        enabled = (
            bool(modifier.show_viewport) and
            bool(getattr(properties, "stage_enabled", True)) and
            "FFD" in active_deform_types(properties)
        )
        lattice_modifier.show_viewport = enabled
        lattice_modifier.show_render = (
            bool(modifier.show_render) and
            bool(getattr(properties, "stage_enabled", True)) and
            "FFD" in active_deform_types(properties)
        )
        _configure_ffd_scope(
            target, modifier, controller, lattice, lattice_modifier)
    return lattice


def remove_ffd_lattice(target, modifier):
    """Remove the native lattice and its companion modifier for one stage."""
    clear_ffd_scope_cache(target, modifier)
    modifier_uuid = cage_modifier_uuid(modifier)
    lattice = ffd_lattice_object(target, modifier)
    companion = (
        _ffd_lattice_modifier(target, modifier, lattice, create=False)
        if lattice is not None else None)
    if (
            companion is not None and
            str(lattice.get(FFD_LATTICE_MODIFIER_MARKER, "")) ==
            modifier_uuid
    ):
        try:
            target.modifiers.remove(companion)
        except (ReferenceError, RuntimeError):
            pass
    if lattice is not None:
        try:
            bpy.data.objects.remove(lattice, do_unlink=True)
        except (ReferenceError, RuntimeError):
            pass
    if getattr(target, "type", None) == "MESH":
        groups = getattr(target, "vertex_groups", None)
        group = groups.get(_ffd_scope_vertex_group_name(modifier)) \
            if groups is not None and hasattr(groups, "get") else None
        if group is not None:
            try:
                groups.remove(group)
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                pass
    group = getattr(modifier, "node_group", None)
    if group is not None:
        try:
            if FFD_LATTICE_MARKER in group:
                del group[FFD_LATTICE_MARKER]
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass


class SDHCageControllerProperties(PropertyGroup):
    cage_type: EnumProperty(
        name="Cage Type",
        description=(
            "Choose a standard layered cage or a dedicated single-operation "
            "cage"
        ),
        items=(
            (
                "STANDARD", "Standard Type",
                "Allow ordered Bend, Twist, Taper, Stretch, and Shear layers",
            ),
            (
                "SHEAR", "Shear Cage",
                "Dedicated single-operation shear cage that can form a Shear chain",
            ),
            (
                "FFD", "FFD Cage",
                "Dedicated single-operation free-form cage that can form an FFD chain",
            ),
            (
                "CURVE", "Curve Cage",
                "Independent Bezier-guided cage with editable cross sections",
            ),
        ),
        default="STANDARD",
        update=_cage_type_update,
    )
    deform_order: IntVectorProperty(
        name="Deformation Order",
        description="Persistent execution order for the enabled deformation layers",
        size=len(DEFORM_ORDER),
        default=(0, -1, -1, -1, -1, -1, -1),
        min=-1,
        max=len(DEFORM_ORDER) - 1,
        options={"HIDDEN"},
        update=_deform_order_update,
    )
    active_deform_layer: IntProperty(
        name="Active Deformation Layer",
        description="Index of the deformation layer selected in the cage UI",
        default=0,
        min=0,
        max=len(DEFORM_ORDER) - 1,
        options={"HIDDEN"},
    )
    expanded_deform_layers: EnumProperty(
        name="Expanded Deformation Layers",
        description="Deformation layers whose parameter rows are expanded",
        items=(
            ("BEND", "Bend", "", DEFORM_BITS["BEND"]),
            ("TWIST", "Twist", "", DEFORM_BITS["TWIST"]),
            ("TAPER", "Taper", "", DEFORM_BITS["TAPER"]),
            ("STRETCH", "Stretch", "", DEFORM_BITS["STRETCH"]),
            ("SHEAR", "Shear", "", DEFORM_BITS["SHEAR"]),
            ("FFD", "FFD", "", DEFORM_BITS["FFD"]),
            ("CURVE", "Curve", "", DEFORM_BITS["CURVE"]),
        ),
        options={"ENUM_FLAG", "HIDDEN"},
        default=set(DEFORM_ORDER),
    )
    # Kept for loading controller state written by 2.2-2.4.2. The UI now uses
    # per-layer expansion and a one-way Expand All command.
    expand_all_deform_layers: BoolProperty(
        name="Expand All",
        description="Expand every deformation layer in the cage UI",
        default=True,
    )
    stage_enabled: BoolProperty(
        name="Enable Stage",
        description=(
            "Temporarily apply or bypass this cage while preserving "
            "chained-stage flow"
        ),
        default=True,
        update=_stage_enabled_update,
    )
    deform_types: EnumProperty(
        name="Deformations",
        description="Shape operations combined by this cage",
        items=(
            ("BEND", "Bend", "Curve geometry along the cage axis", "MOD_SIMPLEDEFORM", DEFORM_BITS["BEND"]),
            ("TWIST", "Twist", "Rotate cross-sections around the cage axis", "FORCE_VORTEX", DEFORM_BITS["TWIST"]),
            ("TAPER", "Taper", "Scale cross-sections along the cage axis", "FULLSCREEN_EXIT", DEFORM_BITS["TAPER"]),
            ("STRETCH", "Stretch", "Scale geometry along the cage axis", "EMPTY_ARROWS", DEFORM_BITS["STRETCH"]),
            ("SHEAR", "Shear", "Slide cross-sections sideways along the cage axis", "MOD_WARP", DEFORM_BITS["SHEAR"]),
            ("FFD", "FFD", "Edit a multi-point free-form cage", "MOD_LATTICE", DEFORM_BITS["FFD"]),
            ("CURVE", "Curve", "Deform geometry along an editable Bezier guide", "CURVE_DATA", DEFORM_BITS["CURVE"]),
        ),
        options={"ENUM_FLAG"},
        default={"BEND"},
        update=_deform_types_update,
    )
    muted_deform_types: EnumProperty(
        name="Muted Deformations",
        description="Present deformation layers temporarily bypassed by this cage",
        items=(
            ("BEND", "Bend", "Temporarily bypass Bend", "MOD_SIMPLEDEFORM", DEFORM_BITS["BEND"]),
            ("TWIST", "Twist", "Temporarily bypass Twist", "FORCE_VORTEX", DEFORM_BITS["TWIST"]),
            ("TAPER", "Taper", "Temporarily bypass Taper", "FULLSCREEN_EXIT", DEFORM_BITS["TAPER"]),
            ("STRETCH", "Stretch", "Temporarily bypass Stretch", "EMPTY_ARROWS", DEFORM_BITS["STRETCH"]),
            ("SHEAR", "Shear", "Temporarily bypass Shear", "MOD_WARP", DEFORM_BITS["SHEAR"]),
            ("FFD", "FFD", "Temporarily bypass FFD", "MOD_LATTICE", DEFORM_BITS["FFD"]),
            ("CURVE", "Curve", "Temporarily bypass Curve", "CURVE_DATA", DEFORM_BITS["CURVE"]),
        ),
        options={"ENUM_FLAG", "HIDDEN"},
        default=set(),
        update=_muted_deform_types_update,
    )
    deform_type: EnumProperty(
        name="Deformation Type",
        description="Shape operation performed inside the cage",
        items=(
            ("BEND", "Bend", "Curve geometry along the cage axis", "MOD_SIMPLEDEFORM", 0),
            ("TWIST", "Twist", "Rotate cross-sections around the cage axis", "FORCE_VORTEX", 1),
            ("TAPER", "Taper", "Scale cross-sections along the cage axis", "FULLSCREEN_EXIT", 2),
            ("STRETCH", "Stretch", "Scale geometry along the cage axis", "EMPTY_ARROWS", 3),
            ("SHEAR", "Shear", "Slide cross-sections sideways along the cage axis", "MOD_WARP", 4),
            ("FFD", "FFD", "Edit a multi-point free-form cage", "MOD_LATTICE", 5),
            ("CURVE", "Curve", "Deform geometry along an editable Bezier guide", "CURVE_DATA", 6),
        ),
        default="BEND",
        update=_deform_type_update,
    )
    bend_strength: FloatProperty(
        name="Bend Angle",
        description="Total Bend angle through the cage length",
        subtype="ANGLE",
        default=math.radians(45.0),
        soft_min=-math.tau,
        soft_max=math.tau,
        update=_independent_parameter_update,
    )
    bend_direction: FloatProperty(
        name="Bend Direction",
        description="Direction of Bend around the cage axis",
        subtype="ANGLE",
        default=0.0,
        soft_min=-math.pi,
        soft_max=math.pi,
        update=_independent_parameter_update,
    )
    twist_strength: FloatProperty(
        name="Twist Angle",
        description="Total Twist angle through the cage length",
        subtype="ANGLE",
        default=math.radians(45.0),
        soft_min=-math.tau,
        soft_max=math.tau,
        update=_independent_parameter_update,
    )
    taper_factor: FloatProperty(
        name="Taper Factor",
        description="Cross-section scale change through the cage length",
        default=0.5,
        soft_min=-2.0,
        soft_max=2.0,
        update=_independent_parameter_update,
    )
    stretch_factor: FloatProperty(
        name="Stretch Factor",
        description="Length scale change through the cage",
        default=0.5,
        soft_min=-2.0,
        soft_max=2.0,
        update=_stretch_factor_update,
    )
    shear_factors: FloatVectorProperty(
        name="Shear",
        description="Cage-local X and Z shear per unit of axial distance",
        size=2,
        default=(0.0, 0.0),
        soft_min=-2.0,
        soft_max=2.0,
        update=_independent_parameter_update,
    )
    ffd_offsets: FloatVectorProperty(
        name="FFD Corner Offsets",
        description="Legacy standard-cage XYZ offsets for the eight FFD corners",
        size=FFD_COMPONENT_COUNT,
        default=(0.0,) * FFD_COMPONENT_COUNT,
        soft_min=-10.0,
        soft_max=10.0,
        update=_independent_parameter_update,
    )
    ffd_points: CollectionProperty(
        name="FFD Control Points",
        description=(
            "Multi-point control data used by a dedicated FFD cage; values "
            "are edited in the viewport and can be keyed"
        ),
        type=SDHFFDPoint,
    )
    ffd_axes_linked: BoolProperty(
        name="Link U/V/W",
        description=(
            "Adjust FFD point counts and interpolation together; disable to "
            "edit U, V, and W independently"
        ),
        default=True,
        get=_ffd_axes_linked_get,
        set=_ffd_axes_linked_set,
        update=_ffd_axes_linked_update,
    )
    ffd_resolution_linked: IntProperty(
        name="FFD Points",
        description="Number of control points on all linked FFD axes",
        min=FFD_MIN_RESOLUTION,
        max=FFD_MAX_RESOLUTION_U,
        get=_ffd_linked_resolution_get,
        set=_ffd_linked_resolution_set,
        update=_ffd_resolution_update,
    )
    ffd_resolution_u: IntProperty(
        name="FFD U Points",
        description="Number of control points across the cage X direction",
        default=FFD_DEFAULT_RESOLUTION[0],
        min=FFD_MIN_RESOLUTION,
        max=FFD_MAX_RESOLUTION_U,
        update=_ffd_resolution_update,
    )
    ffd_resolution_v: IntProperty(
        name="FFD V Points",
        description="Number of control points along the cage deformation axis",
        default=FFD_DEFAULT_RESOLUTION[1],
        min=FFD_MIN_RESOLUTION,
        max=FFD_MAX_RESOLUTION_V,
        update=_ffd_resolution_update,
    )
    ffd_resolution_w: IntProperty(
        name="FFD W Points",
        description="Number of control points across the cage Z direction",
        default=FFD_DEFAULT_RESOLUTION[2],
        min=FFD_MIN_RESOLUTION,
        max=FFD_MAX_RESOLUTION_W,
        update=_ffd_resolution_update,
    )
    ffd_use_outside: BoolProperty(
        name="Hollow FFD",
        description=(
            "Use only the outside FFD control points; interior points are "
            "hidden and excluded from deformation"
        ),
        default=False,
        update=_ffd_use_outside_update,
    )
    ffd_interpolation_u: EnumProperty(
        name="U Interpolation",
        description="Interpolation basis across the FFD cage U direction",
        items=(
            ("KEY_LINEAR", "Linear", "Linear interpolation"),
            ("KEY_CARDINAL", "Cardinal", "Cardinal spline interpolation"),
            ("KEY_CATMULL_ROM", "Catmull-Rom", "Catmull-Rom spline interpolation"),
            ("KEY_BSPLINE", "B-Spline", "B-Spline interpolation"),
        ),
        default="KEY_BSPLINE",
        update=_ffd_interpolation_update,
    )
    ffd_interpolation_v: EnumProperty(
        name="V Interpolation",
        description="Interpolation basis along the FFD cage deformation axis",
        items=(
            ("KEY_LINEAR", "Linear", "Linear interpolation"),
            ("KEY_CARDINAL", "Cardinal", "Cardinal spline interpolation"),
            ("KEY_CATMULL_ROM", "Catmull-Rom", "Catmull-Rom spline interpolation"),
            ("KEY_BSPLINE", "B-Spline", "B-Spline interpolation"),
        ),
        default="KEY_BSPLINE",
        update=_ffd_interpolation_update,
    )
    ffd_interpolation_w: EnumProperty(
        name="W Interpolation",
        description="Interpolation basis across the FFD cage W direction",
        items=(
            ("KEY_LINEAR", "Linear", "Linear interpolation"),
            ("KEY_CARDINAL", "Cardinal", "Cardinal spline interpolation"),
            ("KEY_CATMULL_ROM", "Catmull-Rom", "Catmull-Rom spline interpolation"),
            ("KEY_BSPLINE", "B-Spline", "B-Spline interpolation"),
        ),
        default="KEY_BSPLINE",
        update=_ffd_interpolation_update,
    )
    ffd_interpolation_linked: EnumProperty(
        name="Interpolation",
        description="Interpolation basis on all linked FFD axes",
        items=(
            ("KEY_LINEAR", "Linear", "Linear interpolation"),
            ("KEY_CARDINAL", "Cardinal", "Cardinal spline interpolation"),
            ("KEY_CATMULL_ROM", "Catmull-Rom", "Catmull-Rom spline interpolation"),
            ("KEY_BSPLINE", "B-Spline", "B-Spline interpolation"),
        ),
        get=_ffd_linked_interpolation_get,
        set=_ffd_linked_interpolation_set,
        update=_ffd_interpolation_update,
    )
    ffd_guard_mode: EnumProperty(
        name="FFD Safety",
        description=(
            "Prevent FFD cell foldover by using linear interpolation and "
            "clamping control-point edits to the last safe position"
        ),
        items=(
            (
                "OFF", "Off",
                "Allow unrestricted FFD edits and the selected interpolation",
            ),
            (
                "SAFE", "Prevent Foldover",
                "Use linear interpolation and stop edits before FFD cells invert",
            ),
        ),
        default="OFF",
        update=_ffd_guard_update,
    )
    ffd_symmetry_enabled: BoolProperty(
        name="FFD Symmetry",
        description=(
            "Mirror selected FFD points, lines, and faces across the chosen "
            "U, V, or W center plane"
        ),
        default=False,
        update=_ffd_symmetry_update,
    )
    ffd_symmetry_axis: EnumProperty(
        name="FFD Symmetry Axis",
        description=(
            "FFD lattice axis whose center plane is used for mirrored editing"
        ),
        items=(
            ("U", "U", "Mirror across the cage-local U center plane"),
            ("V", "V", "Mirror across the cage-local V center plane"),
            ("W", "W", "Mirror across the cage-local W center plane"),
        ),
        default="U",
        update=_ffd_symmetry_update,
    )
    ffd_symmetry_axes: EnumProperty(
        name="FFD Symmetry Axes",
        description=(
            "Choose one or more FFD lattice center planes for mirrored editing"
        ),
        items=(
            ("U", "U", "Mirror across the cage-local U center plane"),
            ("V", "V", "Mirror across the cage-local V center plane"),
            ("W", "W", "Mirror across the cage-local W center plane"),
        ),
        options={"ENUM_FLAG"},
        default={"U"},
        update=_ffd_symmetry_axes_update,
    )
    ffd_symmetry_axes_initialized: BoolProperty(
        name="FFD Symmetry Axes Initialized",
        default=False,
        options={"HIDDEN"},
    )
    ffd_active_point: IntProperty(
        name="FFD Point",
        description="Active FFD point index used by the compact control panel",
        default=0,
        min=0,
        max=FFD_MAX_POINT_COUNT - 1,
    )
    ffd_selection_mode: EnumProperty(
        name="FFD Selection Mode",
        description=(
            "Choose whether picking an FFD control selects one point, one "
            "adjacent U/V/W control-line segment, or one UV/UW/VW grid face"
        ),
        items=(
            ("POINT", "Point", "Select one FFD control point"),
            ("LINE", "Line", "Select any U, V, or W FFD control-line segment"),
            ("FACE", "Face", "Select any UV, UW, or VW FFD grid face"),
        ),
        default="POINT",
        update=_ffd_selection_mode_update,
        options={"HIDDEN"},
    )
    ffd_selection_modes: EnumProperty(
        name="FFD Selection Modes",
        description="Select one or more FFD point, line, and face controller types",
        items=(
            ("POINT", "Point", "Show and select FFD point controllers", "VERTEXSEL", 1),
            ("LINE", "Line", "Show and select U/V/W FFD line-segment controllers", "EDGESEL", 2),
            ("FACE", "Face", "Show and select UV/UW/VW FFD face controllers", "FACESEL", 4),
        ),
        options={"ENUM_FLAG"},
        default={"POINT"},
        update=_ffd_selection_modes_update,
    )
    ffd_selection_modes_initialized: BoolProperty(
        name="FFD Selection Modes Initialized",
        default=False,
        options={"HIDDEN"},
    )
    ffd_edit_mode_active: BoolProperty(
        name="FFD Edit Mode",
        description="Whether persistent FFD point editing is active in the viewport",
        default=False,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    ffd_native_edit_mode_active: BoolProperty(
        name="Native FFD Edit Mode",
        description="Whether the companion Blender Lattice is being edited",
        default=False,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    curve_points: CollectionProperty(
        name="Guide Points",
        description="Object-mode controls for the managed Bezier guide",
        type=SDHCurvePoint,
    )
    curve_active_point: IntProperty(
        name="Active Guide Point",
        default=0,
        min=0,
        max=127,
        options={"HIDDEN"},
    )
    curve_point_global_falloff: BoolProperty(
        name="Full Curve Falloff",
        description=(
            "Apply point roll, radius, bevel, and tension through the current "
            "proportional falloff across the complete guide"),
        default=False,
    )
    curve_equalize_count: IntProperty(
        name="Point Count",
        description="Number of evenly-spaced guide points after resampling",
        default=3,
        min=2,
        max=128,
    )
    curve_stations: CollectionProperty(
        name="Cross Sections",
        description="Editable U/W scale and offset stations along the Curve cage",
        type=SDHCurveStation,
    )
    curve_active_station: IntProperty(
        name="Active Cross Section",
        default=0,
        min=0,
        max=31,
        options={"HIDDEN"},
    )
    curve_even_stations: BoolProperty(
        name="Even Cross Sections",
        description=(
            "Keep all cross sections evenly distributed when sections are "
            "added, removed, or adjusted"),
        default=True,
        update=_curve_even_stations_update,
    )
    curve_global_radius: FloatProperty(
        name="Global Radius",
        description=(
            "Uniform radius multiplier composed with native guide-point and "
            "cross-section radius"),
        default=1.0,
        min=0.0,
        soft_max=4.0,
        update=_curve_settings_update,
    )
    curve_global_twist: FloatProperty(
        name="Global Twist",
        description=(
            "Uniform rotation added to every cross-section around the guide"),
        subtype="ANGLE",
        default=0.0,
        soft_min=-math.tau,
        soft_max=math.tau,
        update=_curve_settings_update,
    )
    curve_relative_binding: BoolProperty(
        name="Rest Binding",
        description=(
            "Apply the editable Curve as a change from its captured rest "
            "guide so binding does not deform the object"),
        default=False,
        update=_curve_settings_update,
    )
    curve_preset: EnumProperty(
        name="Curve Preset",
        description="Parametric guide shape previewed immediately on the cage",
        items=(
            ("STRAIGHT", "Straight", "Create a straight guide along the cage axis"),
            ("WAVE", "Wave", "Create a two-plane flowing wave guide"),
            ("SINE", "Sine", "Create a planar sine-wave guide"),
            ("HELIX", "Helix", "Create a helical guide around the cage axis"),
        ),
        default="STRAIGHT",
        update=_curve_preset_update,
    )
    curve_preset_amplitude: FloatProperty(
        name="Amplitude",
        description="Radial size of the generated Curve preset",
        default=0.5,
        min=0.0,
        soft_max=10.0,
        update=_curve_preset_update,
    )
    curve_preset_cycles: FloatProperty(
        name="Cycles",
        description="Number of wave cycles or helix turns along the guide",
        default=1.0,
        min=0.01,
        soft_max=8.0,
        update=_curve_preset_update,
    )
    curve_preset_phase: FloatProperty(
        name="Phase",
        description="Starting phase of the generated Curve preset",
        subtype="ANGLE",
        default=0.0,
        soft_min=-math.tau,
        soft_max=math.tau,
        update=_curve_preset_update,
    )
    curve_preset_points: IntProperty(
        name="Preset Points",
        description="Number of editable Bezier points generated by the preset",
        default=9,
        min=3,
        max=128,
        update=_curve_preset_update,
    )
    curve_length_mode: EnumProperty(
        name="Length Mode",
        description="How cage-axis distance is mapped to the guide",
        items=(
            (
                "PRESERVE", "Preserve Length",
                "Map physical cage distance to guide arc length",
            ),
            (
                "STRETCH", "Stretch to Path",
                "Use the complete guide and stretch the source along it",
            ),
            (
                "FIT_GUIDE", "Fit Guide to Cage",
                "Scale the complete guide shape to the authored cage length",
            ),
        ),
        default="STRETCH",
        update=_curve_settings_update,
    )
    curve_control_mode: EnumProperty(
        name="Control Mode",
        description=(
            "Choose whether the complete source maps to the guide or the "
            "guide endpoints stay inside the cage"),
        items=(
            (
                "CURVE", "Curve Mode",
                "Map the complete source cage and controlled object to the "
                "complete guide; editing the guide changes deformation shape "
                "without changing source boundaries, cage length, or position",
            ),
            (
                "CAGE", "Cage Mode",
                "Keep the guide endpoints constrained inside the cage",
            ),
        ),
        default="CURVE",
        update=_curve_control_mode_update,
    )
    curve_mode: EnumProperty(
        name="Range Mode",
        description="How the Curve cage affects geometry beyond its authored range",
        items=(
            (
                "LIMITED", "Limited",
                "Freeze the boundary frame and continue excluded geometry "
                "rigidly along its tangent",
            ),
            (
                "WITHIN_BOX", "Within Box",
                "Leave geometry outside the authored cage range unchanged",
            ),
            (
                "UNLIMITED", "Unlimited",
                "Extend open endpoints or repeat around a closed guide",
            ),
        ),
        default="LIMITED",
        update=_curve_mode_update,
    )
    curve_boundary_mode: EnumProperty(
        name="Boundary Mode",
        description="How points beyond the Curve cage ends are handled",
        items=(
            (
                "EXTEND", "Extend Tangents",
                "Continue beyond each guide end along its endpoint tangent",
            ),
            (
                "CLAMP", "Clamp",
                "Freeze the boundary frame and continue excluded geometry "
                "rigidly along its tangent",
            ),
            (
                "CAGE_ONLY", "Cage Only",
                "Leave points outside the authored cage range unchanged",
            ),
        ),
        default="CLAMP",
        options={"HIDDEN", "ANIMATABLE"},
        update=_curve_boundary_mode_update,
    )
    curve_range_start: FloatProperty(
        name="Curve Range Start",
        description=(
            "Lower effect boundary inside the stable Curve cage mapping "
            "domain"),
        default=0.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        options={"HIDDEN", "ANIMATABLE"},
        update=_curve_settings_update,
    )
    curve_range_end: FloatProperty(
        name="Curve Range End",
        description=(
            "Upper effect boundary inside the stable Curve cage mapping "
            "domain"),
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        options={"HIDDEN", "ANIMATABLE"},
        update=_curve_settings_update,
    )
    curve_closed: BoolProperty(
        name="Closed Curve",
        description="Join the first and last guide points into a continuous loop",
        default=False,
        update=_curve_closed_update,
    )
    curve_preserve_volume: BoolProperty(
        name="Preserve Volume",
        description="Compensate cross-section scale when stretching to the guide",
        default=False,
        update=_curve_settings_update,
    )
    curve_resolution: IntProperty(
        name="Guide Resolution",
        description="Bezier evaluation resolution used by the Curve cage",
        default=24,
        min=4,
        max=64,
        update=_curve_settings_update,
    )
    # Persistent disclosure state for the Curve cage sidebar.  These are UI
    # preferences only; keeping them on the controller makes every Curve
    # stage remember the user's working layout without changing deformation.
    show_curve_mapping_settings: BoolProperty(
        name="Curve Cage Controls",
        description="Show Curve control, binding, range, and profile settings",
        default=True,
    )
    show_curve_preset_settings: BoolProperty(
        name="Guide Preset",
        description="Show parametric Curve guide preset controls",
        default=False,
    )
    show_curve_edit_settings: BoolProperty(
        name="Curve Edit",
        description="Show guide editing and active-point controls",
        default=True,
    )
    show_curve_cross_section_settings: BoolProperty(
        name="Cross Sections",
        description="Show editable Curve cross-section stations",
        default=False,
    )
    curve_edit_mode_active: BoolProperty(
        name="Native Curve Edit Mode",
        default=False,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    curve_object_edit_active: BoolProperty(
        name="Curve Object Edit Mode",
        description="Whether persistent object-mode guide editing is active",
        default=False,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    tooltip_curve_point: FloatProperty(
        name="Curve Point",
        description="Select and move this Curve cage guide point",
        default=0.0,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    tooltip_curve_handle: FloatProperty(
        name="Bezier Handle",
        description=(
            "Linked handles move symmetrically; Alt makes this handle "
            "independent"),
        default=0.0,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    strength: FloatProperty(
        name="Angle",
        description="Total Bend or Twist angle through the cage length",
        subtype="ANGLE",
        default=math.radians(45.0),
        soft_min=-math.tau,
        soft_max=math.tau,
        update=_legacy_strength_update,
    )
    factor: FloatProperty(
        name="Factor",
        description="Amount used by Taper and Stretch",
        default=0.5,
        soft_min=-2.0,
        soft_max=2.0,
        update=_legacy_factor_update,
    )
    direction: FloatProperty(
        name="Direction",
        description="Direction of Bend around the cage axis",
        subtype="ANGLE",
        default=0.0,
        soft_min=-math.pi,
        soft_max=math.pi,
        update=_legacy_direction_update,
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
            (
                "CHAINED",
                "Chained",
                "The chain root extends continuously beyond both boundaries; later cages preserve the upstream prefix and continue from the cage end",
            ),
        ),
        default="LIMITED",
        update=_controller_update,
    )
    origin: EnumProperty(
        name="Origin",
        description="Starting pattern of the deformation",
        translation_context="SDH_Cage_Origin",
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
        # Preserve the implicit +Y value used by cages saved before 2.4.33.
        # New stages explicitly store +Z before their first fit.
        default="POS_Y",
    )
    show_cage: BoolProperty(
        name="Show Cage",
        description="Draw the cyan cage and orange deformation guide",
        default=True,
    )
    auto_reconnect: BoolProperty(
        name="Auto Reconnect Chain",
        description=(
            "Automatically refresh downstream cage frames after a chain "
            "parameter or controller transform changes"
        ),
        default=True,
        update=_auto_reconnect_update,
    )
    auto_sync_upstream: BoolProperty(
        name="Auto Sync",
        description=(
            "Keep this cage's frame synchronized with the preceding cage's "
            "live deformation"
        ),
        default=False,
        update=_auto_sync_upstream_update,
    )
    sync_shared_end_scale: BoolProperty(
        name="Sync Shared End Scale",
        description=(
            "Scale both sides of each shared cage seam together while "
            "keeping each outer end independent"
        ),
        default=False,
        update=_sync_shared_end_scale_update,
    )
    chain_gap: FloatProperty(
        name="Gap from Previous Cage",
        description=(
            "Non-negative distance from the previous cage; changing it keeps "
            "the overall chain span when possible"
        ),
        default=0.0,
        min=0.0,
        max=CHAIN_GAP_MAX,
        soft_max=CHAIN_GAP_MAX,
        get=_chain_gap_get,
        set=_chain_gap_set,
    )
    show_chain_batch_edit: BoolProperty(
        name="Batch Edit",
        description="Show inline controls that edit several cages immediately",
        default=False,
        update=_chain_batch_panel_toggle_update,
    )
    chain_batch_scope: EnumProperty(
        name="Scope",
        items=(
            ("ALL", "Whole Chain", "Edit every cage in this chain"),
            ("TO_ACTIVE", "Start to Active", "Edit the root through the active cage"),
            ("FROM_ACTIVE", "Active to End", "Edit the active cage through the tip"),
        ),
        default="ALL",
    )
    chain_batch_operation: EnumProperty(
        name="Operation",
        items=(
            ("END_SCALE", "End Scale", "Edit cage-end cross-section scales"),
            ("END_OFFSET", "End Offset", "Edit cage-end cross-section offsets"),
            ("GAP", "Gap", "Edit spacing before downstream cages"),
            ("DEFORMATION", "Deformation", "Edit one deformation parameter"),
            ("STAGE_ENABLED", "Stage Visibility", "Apply or bypass cage stages"),
        ),
        default="END_SCALE",
    )
    chain_batch_end_side: EnumProperty(
        name="Ends",
        items=(
            ("TOP", "Top", "Edit top ends"),
            ("BOTTOM", "Bottom", "Edit bottom ends"),
            ("BOTH", "Both", "Edit both ends"),
        ),
        default="BOTH",
    )
    chain_batch_scale: FloatVectorProperty(
        name="Scale",
        description="X and Z scale applied to every affected cage end",
        size=2,
        default=(1.0, 1.0),
        min=0.05,
        soft_max=4.0,
        update=_chain_batch_value_update,
    )
    chain_batch_offset: FloatVectorProperty(
        name="Offset",
        description="X and Z offset applied to every affected cage end",
        size=2,
        default=(0.0, 0.0),
        soft_min=-10.0,
        soft_max=10.0,
        update=_chain_batch_value_update,
    )
    chain_batch_gap: FloatProperty(
        name="Gap",
        description="Spacing before every affected downstream cage",
        default=0.0,
        min=0.0,
        max=CHAIN_GAP_MAX,
        soft_max=CHAIN_GAP_MAX,
        update=_chain_batch_value_update,
    )
    chain_batch_preserve_span: BoolProperty(
        name="Preserve Total Range",
        description="Shorten each cage as its incoming gap grows",
        default=True,
        update=_chain_batch_value_update,
    )
    chain_batch_deform_type: EnumProperty(
        name="Parameter",
        items=(
            ("BEND", "Bend Angle", "Edit Bend angle"),
            ("BEND_DIRECTION", "Bend Direction", "Edit Bend direction"),
            ("TWIST", "Twist Angle", "Edit Twist angle"),
            ("TAPER", "Taper Factor", "Edit Taper factor"),
            ("STRETCH", "Stretch Factor", "Edit Stretch factor"),
        ),
        default="BEND",
        update=_chain_batch_deform_type_update,
    )
    chain_batch_angle: FloatProperty(
        name="Angle",
        subtype="ANGLE",
        default=0.0,
        soft_min=-math.tau,
        soft_max=math.tau,
        update=_chain_batch_value_update,
    )
    chain_batch_factor: FloatProperty(
        name="Factor",
        default=0.0,
        soft_min=-2.0,
        soft_max=2.0,
        update=_chain_batch_value_update,
    )
    chain_batch_shear: FloatVectorProperty(
        name="Shear",
        size=2,
        default=(0.0, 0.0),
        soft_min=-2.0,
        soft_max=2.0,
        update=_chain_batch_value_update,
    )
    chain_batch_stage_enabled: BoolProperty(
        name="Enable Stages",
        description="Apply the affected cage stages",
        default=True,
        update=_chain_batch_value_update,
    )
    show_other_cages: BoolProperty(
        name="Show Other Cages",
        description=(
            "Display inactive cages and make their viewport controls "
            "directly editable"
        ),
        default=True,
        update=_controller_display_update,
    )
    show_axis_gizmo: BoolProperty(
        name="Show Axis Switch",
        description=(
            "Show axis choices around the cage; the choices hide after "
            "selection unless Ctrl is held"
        ),
        default=False,
    )
    show_direction_handle: BoolProperty(
        name="Show Twist",
        description="Show the ring used to adjust the Bend direction",
        default=False,
    )
    show_ffd_handles: BoolProperty(
        name="Show FFD Handles",
        description="Show editable FFD control-point handles",
        default=True,
    )
    show_numeric_controls: BoolProperty(
        name="Numeric Controls",
        description="Show exact cage size, location, and rotation values",
        default=False,
    )
    show_cage_controls: BoolProperty(
        name="Cage Controls",
        description="Show transform, fit, and cage-selection controls",
        default=False,
    )
    show_deform_axis: BoolProperty(
        name="Deform Axis",
        description="Show axis alignment controls for the active cage",
        default=False,
    )
    top_scale: FloatVectorProperty(
        name="Top Scale",
        description="Scale the top cage cross-section without changing the bottom",
        size=2,
        default=(1.0, 1.0),
        min=0.05,
        soft_max=4.0,
        update=_top_scale_update,
    )
    bottom_scale: FloatVectorProperty(
        name="Bottom Scale",
        description="Scale the bottom cage cross-section without changing the top",
        size=2,
        default=(1.0, 1.0),
        min=0.05,
        soft_max=4.0,
        update=_bottom_scale_update,
    )
    top_offset: FloatVectorProperty(
        name="Top Offset",
        description="Move the top cage cross-section without changing the bottom",
        size=2,
        default=(0.0, 0.0),
        soft_min=-10.0,
        soft_max=10.0,
        update=_top_offset_update,
    )
    bottom_offset: FloatVectorProperty(
        name="Bottom Offset",
        description="Move the bottom cage cross-section without changing the top",
        size=2,
        default=(0.0, 0.0),
        soft_min=-10.0,
        soft_max=10.0,
        update=_bottom_offset_update,
    )
    show_end_handles: BoolProperty(
        name="Show Shape Handles",
        description="Show separate top and bottom cross-section shaping handles",
        default=True,
    )
    show_boundary_handles: BoolProperty(
        name="Show Length Handles",
        description=(
            "Show handles that independently move a cage end or a Curve "
            "effect boundary"),
        default=True,
    )
    limit_boundaries_to_object: BoolProperty(
        name="Limit to Object Bounds",
        description=(
            "Prevent the top and bottom cage or Curve effect boundaries from "
            "moving beyond the input object's bounds"
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
    influence_weight: FloatProperty(
        name="Influence Weight",
        description=(
            "Blend between the original and deformed positions for this "
            "stage; combine with a vertex group for painted falloff"
        ),
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        update=_controller_update,
    )
    influence_vertex_group: StringProperty(
        name="Influence Vertex Group",
        description=(
            "Limit this stage to a vertex group; weights scale the "
            "Influence Weight per point"
        ),
        default="",
        # NOTE: must stay a plain named reference. With PEP 563 (`from
        # __future__ import annotations`) Blender re-evaluates annotation
        # strings at registration; a lambda would be rebuilt with eval
        # globals that cannot resolve this module's names at call time.
        update=_influence_vertex_group_update,
    )


def _target_and_modifier(controller):
    target = find_target(controller)
    return target, find_modifier(target, controller)


def _influence_socket_identifier(modifier):
    """Return the interface identifier of the Influence Weight input."""
    group = getattr(modifier, "node_group", None)
    interface = getattr(group, "interface", None)
    for item in tuple(getattr(interface, "items_tree", ()) or ()):
        if (
                getattr(item, "item_type", "") == "SOCKET" and
                getattr(item, "in_out", "") == "INPUT" and
                str(getattr(item, "name", "")) == "Influence Weight"
        ):
            return str(item.identifier)
    return ""


def apply_influence_vertex_group(controller):
    """Bind the stage's Influence Weight input to a named vertex group."""
    properties = getattr(controller, "sdh_cage_deform", None)
    if properties is None:
        return False
    target, modifier = _target_and_modifier(controller)
    if modifier is None:
        return False
    identifier = _influence_socket_identifier(modifier)
    if not identifier:
        return False
    name = str(getattr(properties, "influence_vertex_group", "") or "")
    socket = _modifier_input_property(modifier, identifier)
    if socket is not None and hasattr(socket, "attribute_name"):
        # Blender 5.2+ interface: the input switches between VALUE and
        # ATTRIBUTE modes through the wrapper's ``type`` enum.
        try:
            socket.attribute_name = name
            if hasattr(socket, "type"):
                socket.type = "ATTRIBUTE" if name else "VALUE"
            if hasattr(socket, "use_attribute"):
                socket.use_attribute = bool(name)
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            return False
    else:
        try:
            # Blender 5.0/5.1 keep Boolean IDProperty keys; assigning an
            # int raises TypeError there.
            modifier[f"{identifier}_use_attribute"] = bool(name)
            modifier[f"{identifier}_attribute_name"] = name
        except (AttributeError, KeyError, ReferenceError, RuntimeError,
                TypeError):
            return False
    if target is not None:
        target.update_tag()
    return True


def _influence_vertex_group_update(properties, context):
    controller = getattr(properties, "id_data", None)
    if controller is not None:
        apply_influence_vertex_group(controller)
    area = getattr(context, "area", None) if context else None
    if area is not None:
        area.tag_redraw()


def _animation_paths(owner):
    """Return data paths driven by the owner's Action, NLA, or drivers."""
    animation = getattr(owner, "animation_data", None)
    if animation is None:
        return frozenset()

    paths = set()

    def collect_action(action):
        if action is None:
            return
        curves = getattr(action, "fcurves", None)
        if curves is not None:
            paths.update(str(curve.data_path) for curve in curves)
            return
        for layer in getattr(action, "layers", ()):
            for strip in getattr(layer, "strips", ()):
                for channelbag in getattr(strip, "channelbags", ()):
                    paths.update(
                        str(curve.data_path)
                        for curve in getattr(channelbag, "fcurves", ()))

    collect_action(getattr(animation, "action", None))
    for track in getattr(animation, "nla_tracks", ()):
        for strip in getattr(track, "strips", ()):
            collect_action(getattr(strip, "action", None))
    paths.update(
        str(curve.data_path)
        for curve in getattr(animation, "drivers", ()))
    return frozenset(paths)


def sync_controller(
        controller, pull_transform=True, *, sync_mode="push",
        chain_frames=None):
    """Keep controller Empty and Geometry Nodes modifier inputs aligned.

    sync_mode:
      - \"push\": controller → modifier (property updates / explicit writes)
      - \"timer\": push Empty transform; if deform params differ, pull modifier →
        controller so manual node edits are not overwritten every tick
    """
    pointer = _pointer(controller)
    if not pointer or pointer in _SYNCING:
        return False
    target, modifier = _target_and_modifier(controller)
    if target is None or modifier is None:
        return False

    # Domain source ranges are derived from every preceding stage's authored
    # size and incoming gaps.  A size edit is uncommon compared with a bend
    # drag, so invalidate the shared read cache only when that size actually
    # changes; ordinary controller edits then reuse one decoded domain record.
    try:
        size_snapshot = tuple(round(float(value), 7)
                              for value in controller.sdh_cage_deform.size)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        size_snapshot = None
    previous_size = _CONTROLLER_SIZE_SNAPSHOTS.get(pointer)
    if size_snapshot is not None:
        if previous_size is not None and previous_size != size_snapshot:
            invalidate_chain_domain_cache()

    previous_transform = _CONTROLLER_TRANSFORM_SNAPSHOTS.get(pointer)
    pending_shared_scale_sync = []
    _SYNCING.add(pointer)
    try:
        properties = controller.sdh_cage_deform
        if str(getattr(properties, "cage_type", "STANDARD")) == "CURVE":
            try:
                control_mode_explicit = bool(
                    properties.is_property_set("curve_control_mode"))
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                control_mode_explicit = False
            if control_mode_explicit:
                control_mode = curve_control_mode_identifier(properties)
                desired_length_mode = CURVE_CONTROL_LENGTH_MODE[control_mode]
                if str(properties.curve_length_mode) != desired_length_mode:
                    properties.curve_length_mode = desired_length_mode
        if str(getattr(properties, "cage_type", "STANDARD")) == "STANDARD":
            current_order = ordered_deform_types(properties)
            standard_order = tuple(
                deform_type for deform_type in current_order
                if deform_type in STANDARD_DEFORM_ORDER) or ("BEND",)
            if standard_order != current_order:
                enabled = set(standard_order)
                properties.deform_order = encode_deform_order(
                    standard_order, enabled, standard_order[0])
                properties.deform_types = enabled
                properties.muted_deform_types = (
                    set(properties.muted_deform_types) & enabled)
                if properties.deform_type not in enabled:
                    properties.deform_type = standard_order[0]
                properties.active_deform_layer = min(
                    int(properties.active_deform_layer),
                    len(standard_order) - 1)
        animated_paths = _animation_paths(controller) if sync_mode == "timer" else frozenset()
        animated_size = "sdh_cage_deform.size" in animated_paths
        chain_mode = _managed_chain_mode(controller, modifier)
        chain_locked = chain_mode in {"CHAINED", "CONNECTED"}
        # Mirror chain-level preferences into each controller. The temporary
        # 2.4.30 build incorrectly reused ``auto_sync_upstream`` for chains;
        # if that property was explicitly stored, restore the legacy default
        # reconnect metadata once and remove the alias from the chain stage.
        persisted_auto = None
        persisted_shared_scale = None
        if chain_locked or getattr(modifier, "node_group", None) is not None:
            try:
                from . import chain as chain_module
                group = getattr(modifier, "node_group", None)
                has_chain_metadata = bool(
                    group and str(group.get(CHAIN_UUID_PROP, "") or ""))
                if chain_locked or has_chain_metadata:
                    alias_was_saved = False
                    try:
                        alias_was_saved = bool(
                            properties.is_property_set("auto_sync_upstream"))
                    except (AttributeError, ReferenceError, RuntimeError, TypeError):
                        alias_was_saved = False
                    if alias_was_saved:
                        try:
                            chain_module.set_chain_auto_reconnect(
                                target,
                                chain_module.stage_chain_uuid(modifier),
                                True,
                                sync_properties=True,
                            )
                            properties.property_unset("auto_sync_upstream")
                        except (AttributeError, ReferenceError, RuntimeError,
                                TypeError, ValueError):
                            pass
                    persisted_auto = chain_module.stage_chain_auto_reconnect(
                        modifier, True)
                    persisted_shared_scale = (
                        chain_module.stage_chain_sync_shared_end_scale(
                            modifier, False))
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError):
                persisted_auto = None
        if persisted_auto is not None and hasattr(properties, "auto_reconnect"):
            if bool(getattr(properties, "auto_reconnect", persisted_auto)) != bool(
                    persisted_auto):
                _CHAIN_AUTO_GUARD.add(pointer)
                try:
                    properties.auto_reconnect = bool(persisted_auto)
                finally:
                    _CHAIN_AUTO_GUARD.discard(pointer)
        if (
                persisted_shared_scale is not None and
                hasattr(properties, "sync_shared_end_scale") and
                bool(properties.sync_shared_end_scale) !=
                bool(persisted_shared_scale)
        ):
            _CHAIN_SHARED_SCALE_GUARD.add(pointer)
            try:
                properties.sync_shared_end_scale = bool(
                    persisted_shared_scale)
            finally:
                _CHAIN_SHARED_SCALE_GUARD.discard(pointer)
        if chain_locked:
            _enforce_chain_properties(controller, properties, modifier)
        _set_controller_style(controller)
        desired_order = ordered_deform_types(properties)
        desired_active = active_deform_types(properties)
        (
            evaluator_top_scale,
            evaluator_bottom_scale,
            derived_end_scales,
        ) = evaluator_end_scales(
            properties, controller, modifier, include_relative=True)
        desired_encoded = encode_deform_order(
            desired_order, properties.deform_types, properties.deform_type)
        if tuple(properties.deform_order) != desired_encoded:
            properties.deform_order = desired_encoded
        order_links_changed = ensure_modifier_deform_order(
            target, modifier, desired_order)
        if pull_transform and not animated_size:
            size = tuple(max(abs(value) * 2.0, EPSILON) for value in controller.scale)
            if any(abs(properties.size[index] - size[index]) > EPSILON
                   for index in range(3)):
                properties.size = size
        else:
            controller.scale = tuple(max(value, EPSILON) * 0.5 for value in properties.size)

        # A direct Empty scale edit can author ``properties.size`` above,
        # after the initial snapshot was read.  Invalidate before decoding
        # chain domains so the same timer pass uses the new source range.
        try:
            size_snapshot_after = tuple(
                round(float(value), 7) for value in properties.size)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            size_snapshot_after = size_snapshot
        if (
                size_snapshot_after is not None and
                size_snapshot is not None and
                size_snapshot_after != size_snapshot
        ):
            invalidate_chain_domain_cache()
        if size_snapshot_after is not None:
            _CONTROLLER_SIZE_SNAPSHOTS[pointer] = size_snapshot_after

        curve_guide = None
        curve_rest_guide = None
        curve_station_object = None
        if str(getattr(properties, "cage_type", "STANDARD")) == "CURVE":
            try:
                from .curve import (
                    curve_guide_spline,
                    curve_rest_guide_object,
                    ensure_curve_companions,
                    ensure_curve_point_collection,
                )
                native_was_editing = bool(properties.curve_edit_mode_active)
                curve_guide, curve_station_object = ensure_curve_companions(
                    target, modifier, controller)
                native_is_editing = bool(
                    curve_guide and
                    getattr(curve_guide, "mode", "OBJECT") == "EDIT")
                spline = curve_guide_spline(curve_guide)
                if spline is not None:
                    if native_was_editing or native_is_editing:
                        properties.curve_closed = bool(spline.use_cyclic_u)
                    elif bool(spline.use_cyclic_u) != bool(properties.curve_closed):
                        spline.use_cyclic_u = bool(properties.curve_closed)
                        curve_guide.data.update_tag()
                ensure_curve_point_collection(properties, curve_guide)
                curve_rest_guide = curve_rest_guide_object(target, modifier)
                properties.curve_edit_mode_active = native_is_editing
            except (AttributeError, ImportError, ReferenceError, RuntimeError,
                    TypeError, ValueError):
                curve_guide = None
                curve_rest_guide = None
                curve_station_object = None
        transform_values = {
            "Center": tuple(controller.location),
            "Rotation": tuple(_controller_rotation_xyz(controller)),
            "Size": tuple(properties.size),
        }
        if curve_guide is not None and curve_station_object is not None:
            transform_values.update({
                "Curve Guide Object": curve_guide,
                "Curve Station Object": curve_station_object,
            })
            if curve_rest_guide is not None:
                transform_values["Curve Rest Guide Object"] = curve_rest_guide
        domain_values = _chain_domain_input_values(controller, modifier)
        shared_stretch = (
            float(domain_values.get("Chain Global Stretch Factor", 0.0))
            if bool(domain_values.get("Chain Global Stretch Active", False))
            else None
        )
        if (
                shared_stretch is not None and
                abs(float(properties.stretch_factor) - shared_stretch) > EPSILON
        ):
            _CHAIN_GLOBAL_STRETCH_GUARD.add(pointer)
            try:
                properties.stretch_factor = shared_stretch
                if str(properties.deform_type) == "STRETCH":
                    properties.factor = shared_stretch
            finally:
                _CHAIN_GLOBAL_STRETCH_GUARD.discard(pointer)
        prefix_active = bool(
            domain_values.get("Chain Global Prefix Active", False))
        prefix_mask = int(
            domain_values.get("Chain Global Prefix Types", 0))
        suffix_active = bool(
            domain_values.get("Chain Global Suffix Active", False))
        baseline_mask = int(domain_values.get(
            "Chain Global Baseline Types", prefix_mask))
        baseline_active = prefix_active or suffix_active
        socket_bend_strength = float(properties.bend_strength)
        socket_twist_strength = float(properties.twist_strength)
        socket_taper_factor = float(properties.taper_factor)
        socket_stretch_factor = float(properties.stretch_factor)
        socket_shear = tuple(float(value) for value in properties.shear_factors)
        if baseline_active:
            if baseline_mask & DEFORM_BITS["BEND"]:
                socket_bend_strength -= float(
                    domain_values.get("Chain Prefix Base Bend", 0.0))
            if baseline_mask & DEFORM_BITS["TWIST"]:
                socket_twist_strength -= float(
                    domain_values.get("Chain Prefix Base Twist", 0.0))
            if baseline_mask & DEFORM_BITS["TAPER"]:
                socket_taper_factor -= float(
                    domain_values.get("Chain Prefix Base Taper", 0.0))
            if baseline_mask & DEFORM_BITS["STRETCH"]:
                socket_stretch_factor -= float(
                    domain_values.get("Chain Prefix Base Stretch", 0.0))
            if baseline_mask & DEFORM_BITS["SHEAR"]:
                base_shear = tuple(float(value) for value in domain_values.get(
                    "Chain Prefix Base Shear", (0.0, 0.0, 0.0)))
                socket_shear = (
                    socket_shear[0] - base_shear[0],
                    socket_shear[1] - (
                        base_shear[2] if len(base_shear) > 2 else
                        base_shear[1]),
                )
        param_values = {
            "Strength": properties.strength,
            "Factor": properties.factor,
            "Direction": properties.direction,
            "Deform Type": DEFORM_VALUES[properties.deform_type],
            "Deform Types": deform_type_mask(
                desired_active - ({"STRETCH"} if domain_values.get(
                    "Chain Global Stretch Active", False) else set()),
                None),
            "Bend Angle": socket_bend_strength,
            "Bend Direction": properties.bend_direction,
            "Twist Angle": socket_twist_strength,
            "Taper Factor": socket_taper_factor,
            "Stretch Factor": socket_stretch_factor,
            "Stage Enabled": bool(properties.stage_enabled),
            "Influence Weight": float(properties.influence_weight),
            "Mode": MODE_VALUES[properties.mode],
            "Origin": ORIGIN_VALUES[properties.origin],
            "Preserve Volume": properties.preserve_volume,
            "Curve Length Mode": CURVE_LENGTH_VALUES[
                properties.curve_length_mode],
            "Curve Boundary Mode": CURVE_MODE_VALUES[
                properties.curve_mode],
            "Curve Preserve Volume": bool(properties.curve_preserve_volume),
            "Curve Closed": bool(properties.curve_closed),
            "Curve Range Start": float(properties.curve_range_start),
            "Curve Range End": float(properties.curve_range_end),
            "Curve Global Radius": float(properties.curve_global_radius),
            "Curve Global Twist": float(properties.curve_global_twist),
            "Curve Relative Binding": bool(
                properties.curve_relative_binding),
            "Top Scale": (
                evaluator_top_scale[0], 1.0, evaluator_top_scale[1]),
            "Bottom Scale": (
                evaluator_bottom_scale[0], 1.0, evaluator_bottom_scale[1]),
            "Top Offset": (
                properties.top_offset[0], 0.0, properties.top_offset[1]),
            "Bottom Offset": (
                properties.bottom_offset[0], 0.0, properties.bottom_offset[1]),
            "Chain Global Stretch Active": domain_values.get(
                "Chain Global Stretch Active", False),
            "Chain Global Stretch Factor": domain_values.get(
                "Chain Global Stretch Factor", 0.0),
            "Chain Global Stretch Center": domain_values.get(
                "Chain Global Stretch Center", (0.0, 0.0, 0.0)),
            "Chain Global Stretch Rotation": domain_values.get(
                "Chain Global Stretch Rotation", (0.0, 0.0, 0.0)),
            "Chain Global Stretch Source Offset": domain_values.get(
                "Chain Global Stretch Source Offset", 0.0),
            "Chain Global Stretch Length": domain_values.get(
                "Chain Global Stretch Length", 2.0),
            "Chain Global Stretch Origin": domain_values.get(
                "Chain Global Stretch Origin", ORIGIN_VALUES["BOTTOM"]),
            "Chain Global Prefix Active": prefix_active,
            "Chain Global Prefix Types": prefix_mask,
            "Chain Global Prefix Bend": domain_values.get(
                "Chain Global Prefix Bend", 0.0),
            "Chain Global Prefix Direction": domain_values.get(
                "Chain Global Prefix Direction", 0.0),
            "Chain Global Prefix Twist": domain_values.get(
                "Chain Global Prefix Twist", 0.0),
            "Chain Global Prefix Taper": domain_values.get(
                "Chain Global Prefix Taper", 0.0),
            "Chain Global Prefix Stretch": domain_values.get(
                "Chain Global Prefix Stretch", 0.0),
            "Chain Global Prefix Center": domain_values.get(
                "Chain Global Prefix Center", (0.0, 0.0, 0.0)),
            "Chain Global Prefix Rotation": domain_values.get(
                "Chain Global Prefix Rotation", (0.0, 0.0, 0.0)),
            "Chain Global Prefix Source Offset": domain_values.get(
                "Chain Global Prefix Source Offset", 0.0),
            "Chain Global Prefix Length": domain_values.get(
                "Chain Global Prefix Length", 2.0),
            "Chain Global Prefix Origin": domain_values.get(
                "Chain Global Prefix Origin", ORIGIN_VALUES["BOTTOM"]),
            "Chain Global Profile Active": domain_values.get(
                "Chain Global Profile Active", False),
            "Chain Global Profile Bottom Scale": domain_values.get(
                "Chain Global Profile Bottom Scale", (1.0, 1.0, 1.0)),
            "Chain Global Profile Top Scale": domain_values.get(
                "Chain Global Profile Top Scale", (1.0, 1.0, 1.0)),
            "Chain Global Profile Bottom Offset": domain_values.get(
                "Chain Global Profile Bottom Offset", (0.0, 0.0, 0.0)),
            "Chain Global Profile Top Offset": domain_values.get(
                "Chain Global Profile Top Offset", (0.0, 0.0, 0.0)),
        }
        param_values["Shear"] = (
            float(socket_shear[0]), 0.0, float(socket_shear[1]))
        for socket_name, offset in zip(
                FFD_SOCKET_NAMES,
                normalized_ffd_offsets(properties.ffd_offsets)):
            param_values[socket_name] = tuple(offset)

        def _different(old, value):
            if isinstance(value, bpy.types.ID) or isinstance(old, bpy.types.ID):
                return not _same_rna_value(old, value)
            if isinstance(value, tuple):
                old_tuple = tuple(old) if old is not None else ()
                return len(old_tuple) != len(value) or any(
                    abs(float(a) - float(b)) > EPSILON
                    for a, b in zip(old_tuple, value))
            if isinstance(value, str) or isinstance(old, str):
                return str(old or "") != str(value)
            if isinstance(value, bool) or isinstance(old, bool):
                return old is None or bool(old) != bool(value)
            return old is None or abs(float(old) - float(value)) > EPSILON

        changed = bool(order_links_changed)
        # Transform always follows the Empty (viewport / fit).
        for name, value in (*transform_values.items(), *domain_values.items()):
            if modifier_input_identifier(modifier, name) is None:
                continue
            old = modifier_input(modifier, name)
            if _different(old, value):
                set_modifier_input(modifier, name, value)
                changed = True

        if sync_mode == "timer":
            # Prefer Geometry Nodes values when they diverge so node edits stick.
            # Animated controller properties are the exception: frame/NLA
            # evaluation has just authored their current values, so push those
            # sockets before reading the remaining manual node edits back.
            animated_inputs = (
                ("Strength", "strength"),
                ("Factor", "factor"),
                ("Direction", "direction"),
                ("Bend Angle", "bend_strength"),
                ("Bend Direction", "bend_direction"),
                ("Twist Angle", "twist_strength"),
                ("Taper Factor", "taper_factor"),
                ("Stretch Factor", "stretch_factor"),
                ("Shear", "shear_factors"),
                ("Stage Enabled", "stage_enabled"),
                ("Influence Weight", "influence_weight"),
                ("Preserve Volume", "preserve_volume"),
                ("Curve Preserve Volume", "curve_preserve_volume"),
                ("Curve Length Mode", "curve_control_mode"),
                ("Curve Length Mode", "curve_length_mode"),
                ("Curve Boundary Mode", "curve_mode"),
                ("Curve Closed", "curve_closed"),
                ("Curve Range Start", "curve_range_start"),
                ("Curve Range End", "curve_range_end"),
                ("Curve Global Radius", "curve_global_radius"),
                ("Curve Global Twist", "curve_global_twist"),
                ("Curve Relative Binding", "curve_relative_binding"),
                ("Top Scale", "top_scale"),
                ("Bottom Scale", "bottom_scale"),
                ("Top Offset", "top_offset"),
                ("Bottom Offset", "bottom_offset"),
                ("Size", "size"),
            )
            for input_name, property_name in animated_inputs:
                if f"sdh_cage_deform.{property_name}" not in animated_paths:
                    continue
                value = param_values.get(
                    input_name, transform_values.get(input_name))
                if value is None:
                    continue
                old = modifier_input(modifier, input_name)
                if _different(old, value):
                    set_modifier_input(modifier, input_name, value)
                    changed = True
            if "sdh_cage_deform.ffd_offsets" in animated_paths:
                for socket_name in FFD_SOCKET_NAMES:
                    value = param_values[socket_name]
                    old = modifier_input(modifier, socket_name)
                    if _different(old, value):
                        set_modifier_input(modifier, socket_name, value)
                        changed = True
            pulled = {}
            legacy_strength_input = float(modifier_input(
                modifier, "Strength", properties.strength))
            legacy_factor_input = float(modifier_input(
                modifier, "Factor", properties.factor))
            legacy_direction_input = float(modifier_input(
                modifier, "Direction", properties.direction))
            deform_type_value = int(modifier_input(
                modifier, "Deform Type", DEFORM_VALUES[properties.deform_type]))
            deform_mask_value = int(modifier_input(
                modifier, "Deform Types",
                deform_type_mask(desired_active, None)))
            bend_strength = float(modifier_input(
                modifier, "Bend Angle", param_values["Bend Angle"]))
            bend_direction = float(modifier_input(
                modifier, "Bend Direction", properties.bend_direction))
            twist_strength = float(modifier_input(
                modifier, "Twist Angle", param_values["Twist Angle"]))
            taper_factor = float(modifier_input(
                modifier, "Taper Factor", param_values["Taper Factor"]))
            stretch_factor = float(modifier_input(
                modifier, "Stretch Factor", param_values["Stretch Factor"]))
            shear_input = tuple(modifier_input(
                modifier, "Shear", param_values["Shear"]))
            ffd_input_values = tuple(
                tuple(modifier_input(
                    modifier, socket_name, param_values[socket_name]))
                for socket_name in FFD_SOCKET_NAMES
            )
            if baseline_active:
                if baseline_mask & DEFORM_BITS["BEND"]:
                    bend_strength += float(
                        domain_values.get("Chain Prefix Base Bend", 0.0))
                if baseline_mask & DEFORM_BITS["TWIST"]:
                    twist_strength += float(
                        domain_values.get("Chain Prefix Base Twist", 0.0))
                if baseline_mask & DEFORM_BITS["TAPER"]:
                    taper_factor += float(
                        domain_values.get("Chain Prefix Base Taper", 0.0))
                if baseline_mask & DEFORM_BITS["STRETCH"]:
                    stretch_factor += float(
                        domain_values.get("Chain Prefix Base Stretch", 0.0))
                if baseline_mask & DEFORM_BITS["SHEAR"]:
                    base_shear = tuple(float(value) for value in
                        domain_values.get(
                            "Chain Prefix Base Shear", (0.0, 0.0, 0.0)))
                    shear_input = (
                        float(shear_input[0]) + base_shear[0],
                        0.0,
                        float(shear_input[2]) + (
                            base_shear[2] if len(base_shear) > 2 else
                            base_shear[1]),
                    )
            stage_enabled = bool(modifier_input(
                modifier, "Stage Enabled", properties.stage_enabled))
            influence_weight = float(modifier_input(
                modifier, "Influence Weight",
                param_values.get("Influence Weight", 1.0)))
            # The legacy sockets remain editable for old files and scripts.
            # When only an old socket diverged, route that edit into the
            # independent parameter owned by the current single/primary type.
            # If both old and new sockets changed, the new dedicated input wins.
            if (
                    abs(legacy_strength_input - properties.strength) > EPSILON and
                    properties.deform_type == "BEND" and
                    abs(bend_strength - properties.bend_strength) <= EPSILON
            ):
                bend_strength = legacy_strength_input
            elif (
                    abs(legacy_strength_input - properties.strength) > EPSILON and
                    properties.deform_type == "TWIST" and
                    abs(twist_strength - properties.twist_strength) <= EPSILON
            ):
                twist_strength = legacy_strength_input
            if (
                    abs(legacy_factor_input - properties.factor) > EPSILON and
                    properties.deform_type == "TAPER" and
                    abs(taper_factor - properties.taper_factor) <= EPSILON
            ):
                taper_factor = legacy_factor_input
            elif (
                    abs(legacy_factor_input - properties.factor) > EPSILON and
                    properties.deform_type == "STRETCH" and
                    abs(stretch_factor - properties.stretch_factor) <= EPSILON
            ):
                stretch_factor = legacy_factor_input
            if (
                    abs(legacy_direction_input - properties.direction) > EPSILON and
                    abs(bend_direction - properties.bend_direction) <= EPSILON
            ):
                bend_direction = legacy_direction_input
            mode_value = int(modifier_input(
                modifier, "Mode", MODE_VALUES[properties.mode]))
            origin_value = int(modifier_input(
                modifier, "Origin", ORIGIN_VALUES[properties.origin]))
            if chain_locked:
                # A user can edit a node group's exposed sockets directly;
                # connected stages still keep the chained mode contract while
                # preserving the authored Origin.
                mode_value = MODE_VALUES["CHAINED"]
            preserve = bool(modifier_input(
                modifier, "Preserve Volume", properties.preserve_volume))
            top_scale = tuple(modifier_input(
                modifier, "Top Scale",
                (properties.top_scale[0], 1.0, properties.top_scale[1])))
            bottom_scale = tuple(modifier_input(
                modifier, "Bottom Scale",
                (properties.bottom_scale[0], 1.0, properties.bottom_scale[1])))
            top_offset = tuple(modifier_input(
                modifier, "Top Offset",
                (properties.top_offset[0], 0.0, properties.top_offset[1])))
            bottom_offset = tuple(modifier_input(
                modifier, "Bottom Offset",
                (properties.bottom_offset[0], 0.0, properties.bottom_offset[1])))

            deform_type_names = {
                value: key for key, value in DEFORM_VALUES.items()}
            modes = {value: key for key, value in MODE_VALUES.items()}
            origins = {value: key for key, value in ORIGIN_VALUES.items()}

            def _set_if_changed(attr, new_value, log_name):
                nonlocal changed
                old_value = getattr(properties, attr)
                if isinstance(old_value, set) or isinstance(
                        new_value, (set, frozenset)):
                    differs = set(old_value) != set(new_value)
                elif hasattr(old_value, "__len__") and not isinstance(old_value, str):
                    old_cmp = tuple(old_value)
                    new_cmp = tuple(new_value)
                    differs = any(
                        abs(float(a) - float(b)) > EPSILON
                        for a, b in zip(old_cmp, new_cmp)
                    ) or len(old_cmp) != len(new_cmp)
                elif isinstance(new_value, bool) or isinstance(old_value, bool):
                    differs = bool(old_value) != bool(new_value)
                elif isinstance(new_value, str):
                    differs = old_value != new_value
                else:
                    differs = abs(float(old_value) - float(new_value)) > EPSILON
                if differs:
                    setattr(properties, attr, new_value)
                    pulled[log_name] = True
                    changed = True
                return differs

            node_active = deform_types_from_mask(deform_mask_value)
            present_types = set(properties.deform_types) | node_active
            if not present_types:
                fallback = (
                    properties.deform_type
                    if properties.deform_type in DEFORM_BITS else "BEND")
                present_types = {fallback}
            muted_types = present_types - node_active
            pulled_order = normalize_deform_order(
                properties.deform_order,
                present_types,
                properties.deform_type,
            )
            node_primary = deform_type_names.get(
                deform_type_value, properties.deform_type)
            pulled_primary = (
                node_primary if node_primary in present_types else
                properties.deform_type
                if properties.deform_type in present_types else
                pulled_order[0]
            )
            _set_if_changed(
                "deform_types", present_types,
                "Deform Types")
            _set_if_changed(
                "muted_deform_types", muted_types, "Muted Deformations")
            pulled_encoded = encode_deform_order(
                pulled_order, present_types, pulled_primary)
            _set_if_changed(
                "deform_order", pulled_encoded, "Deformation Order")
            _set_if_changed(
                "deform_type", pulled_primary, "Deform Type")
            if ensure_modifier_deform_order(target, modifier, pulled_order):
                changed = True
            _set_if_changed(
                "bend_strength", bend_strength, "Bend Angle")
            _set_if_changed(
                "bend_direction", bend_direction, "Bend Direction")
            _set_if_changed(
                "twist_strength", twist_strength, "Twist Angle")
            _set_if_changed(
                "taper_factor", taper_factor, "Taper Factor")
            _set_if_changed(
                "stretch_factor", stretch_factor, "Stretch Factor")
            _set_if_changed(
                "shear_factors",
                (float(shear_input[0]), float(shear_input[2])),
                "Shear")
            _set_if_changed(
                "ffd_offsets",
                tuple(
                    float(component)
                    for offset in ffd_input_values
                    for component in offset[:3]),
                "FFD Corner Offsets")
            _set_if_changed(
                "stage_enabled", stage_enabled, "Stage Enabled")
            _set_if_changed(
                "influence_weight", influence_weight, "Influence Weight")
            legacy_strength, legacy_factor, legacy_direction = (
                _legacy_values_for_primary(properties))
            _set_if_changed("strength", legacy_strength, "Strength")
            _set_if_changed("factor", legacy_factor, "Factor")
            _set_if_changed("direction", legacy_direction, "Direction")
            for name, value in (
                    ("Strength", legacy_strength),
                    ("Factor", legacy_factor),
                    ("Direction", legacy_direction)):
                old = modifier_input(modifier, name)
                if _different(old, value):
                    set_modifier_input(modifier, name, value)
                    changed = True
            _set_if_changed(
                "mode", modes.get(mode_value, properties.mode), "Mode")
            _set_if_changed(
                "origin", origins.get(origin_value, properties.origin), "Origin")
            _set_if_changed("preserve_volume", preserve, "Preserve Volume")
            if derived_end_scales:
                # These inputs are a managed relative representation of the
                # absolute controller values.  Never pull them back into RNA,
                # or every timer tick would turn the authored seam into 1 and
                # reintroduce the cumulative scale on the next push.
                for name in ("Top Scale", "Bottom Scale"):
                    expected = param_values[name]
                    old = modifier_input(modifier, name)
                    if _different(old, expected):
                        set_modifier_input(modifier, name, expected)
                        changed = True
            else:
                top_scale_changed = _set_if_changed(
                    "top_scale", (float(top_scale[0]), float(top_scale[2])),
                    "Top Scale")
                bottom_scale_changed = _set_if_changed(
                    "bottom_scale",
                    (float(bottom_scale[0]), float(bottom_scale[2])),
                    "Bottom Scale")
                if bool(getattr(properties, "sync_shared_end_scale", False)):
                    if top_scale_changed:
                        pending_shared_scale_sync.append(
                            ("TOP", tuple(properties.top_scale)))
                    if bottom_scale_changed:
                        pending_shared_scale_sync.append(
                            ("BOTTOM", tuple(properties.bottom_scale)))
            _set_if_changed(
                "top_offset", (float(top_offset[0]), float(top_offset[2])),
                "Top Offset")
            _set_if_changed(
                "bottom_offset",
                (float(bottom_offset[0]), float(bottom_offset[2])),
                "Bottom Offset")
        else:
            for name, value in param_values.items():
                old = modifier_input(modifier, name)
                if _different(old, value):
                    set_modifier_input(modifier, name, value)
                    changed = True

        if chain_locked:
            for name in (
                    "Deform Types", "Chain Global Stretch Active",
                    "Chain Global Stretch Factor", "Chain Global Stretch Center",
                    "Chain Global Stretch Rotation",
                    "Chain Global Stretch Source Offset",
                    "Chain Global Stretch Length", "Chain Global Stretch Origin",
                    "Chain Global Prefix Active", "Chain Global Prefix Types",
                    "Chain Global Prefix Bend", "Chain Global Prefix Direction",
                    "Chain Global Prefix Twist", "Chain Global Prefix Taper",
                    "Chain Global Prefix Stretch", "Chain Global Prefix Center",
                    "Chain Global Prefix Rotation",
                    "Chain Global Prefix Source Offset",
                    "Chain Global Prefix Length", "Chain Global Prefix Origin",
                    "Chain Global Profile Active",
                    "Chain Global Profile Bottom Scale",
                    "Chain Global Profile Top Scale",
                    "Chain Global Profile Bottom Offset",
                    "Chain Global Profile Top Offset"):
                value = param_values.get(name)
                if value is None:
                    continue
                old = modifier_input(modifier, name)
                if _different(old, value):
                    set_modifier_input(modifier, name, value)
                    changed = True

        if chain_locked:
            for name, value in (("Mode", MODE_VALUES["CHAINED"]),):
                old = modifier_input(modifier, name)
                if _different(old, value):
                    set_modifier_input(modifier, name, value)
                    changed = True
            # Derive both affine frames only after transform and parameter
            # pulls. Writing an earlier snapshot made one timer cycle expose
            # stale frames during interactive chain edits.
            expected_input_frame, expected_output_frame = (
                chain_frames if chain_frames is not None else
                chain_conjugation_frames_for_controller(
                    controller, modifier, properties))
            for name, value in zip(
                    (
                        "Chain Input Pivot", "Chain Input Inverse X",
                        "Chain Input Inverse Y", "Chain Input Inverse Z",
                        "Chain Output Offset", "Chain Output X",
                        "Chain Output Y", "Chain Output Z",
                    ),
                    (*expected_input_frame, *expected_output_frame),
            ):
                old = modifier_input(modifier, name)
                if _different(old, tuple(value)):
                    set_modifier_input(modifier, name, tuple(value))
                    changed = True

        if _store_authored_end_scales(modifier, properties):
            changed = True
        group = getattr(modifier, "node_group", None)
        cage_type = str(getattr(properties, "cage_type", "STANDARD"))
        if group is not None and str(group.get(CAGE_TYPE_MARKER, "")) != cage_type:
            group[CAGE_TYPE_MARKER] = cage_type
        if str(getattr(properties, "cage_type", "STANDARD")) == "FFD":
            try:
                ensure_ffd_lattice(target, modifier, controller)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                # A controller can be evaluated while its stage is being
                # removed. The regular GN stage remains usable and the next
                # timer pass will recreate the native lattice if needed.
                pass
        elif str(getattr(properties, "cage_type", "STANDARD")) == "CURVE":
            try:
                from .curve import ensure_curve_companions
                ensure_curve_companions(target, modifier, controller)
            except (AttributeError, ImportError, ReferenceError, RuntimeError,
                    TypeError, ValueError):
                pass
        if changed:
            target.update_tag()
        # Parameter edits arrive through the RNA callback, while Empty
        # transforms can change without one.  Cover both paths here and let
        # the timer coalesce repeated requests into one reconnect operation.
        latest_transform = _controller_transform_signature(controller)
        transform_changed = (
            previous_transform is not None and
            latest_transform is not None and
            previous_transform != latest_transform
        )
        chain_target, chain_uuid = _chain_for_controller(controller)
        internal_reconnect = bool(
            chain_target is not None and chain_uuid and
            _chain_request_key(chain_target, chain_uuid) in _CHAIN_RECONNECTING
        )
        if (changed or transform_changed) and not internal_reconnect:
            request_chain_reconnect(
                controller, include_stage=transform_changed)
            request_stack_auto_fit(controller, modifier)
        _CONTROLLER_TRANSFORM_SNAPSHOTS[pointer] = latest_transform
        return changed
    finally:
        _SYNCING.discard(pointer)
        if pointer not in _CONTROLLER_TRANSFORM_SNAPSHOTS:
            _CONTROLLER_TRANSFORM_SNAPSHOTS[pointer] = (
                _controller_transform_signature(controller))
        if pending_shared_scale_sync:
            try:
                from . import chain as chain_module
                for side, scale in pending_shared_scale_sync:
                    chain_module.sync_chain_shared_end_scale(
                        target, modifier, side, scale)
            except (ImportError, AttributeError, ReferenceError, RuntimeError,
                    TypeError, ValueError):
                pass


def sync_all_controllers(pull_transform=True, *, sync_mode="push"):
    """Sync every cage controller. Returns the number of controllers found."""
    count = 0
    live_pointers = set()
    orphan_targets = set()
    for obj in _data_objects_snapshot():
        if is_cage_controller(obj):
            target = find_target(obj)
            if target is not None and find_modifier(target, obj) is None:
                orphan_targets.add(target)
                continue
            count += 1
            live_pointers.add(_pointer(obj))
            sync_controller(
                obj, pull_transform=pull_transform, sync_mode=sync_mode)
    for target in orphan_targets:
        remove_orphan_cage_controllers(target)
    for pointer in tuple(_CONTROLLER_TRANSFORM_SNAPSHOTS):
        if pointer not in live_pointers:
            _CONTROLLER_TRANSFORM_SNAPSHOTS.pop(pointer, None)
            _CONTROLLER_SIZE_SNAPSHOTS.pop(pointer, None)
    for pointer in tuple(_FFD_GUARD_VALID_OFFSETS):
        if pointer not in live_pointers:
            _FFD_GUARD_VALID_OFFSETS.pop(pointer, None)
    _prune_ffd_scope_cache(live_pointers)
    return count


def _remove_legacy_chain_correction_data(target, modifier):
    """Delete vertex residual data left by releases before the analytic chain.

    Only attributes using the add-on's generated prefix are touched.  User
    mesh attributes and all authored cage parameters remain unchanged.
    """
    group = getattr(modifier, "node_group", None)
    controller = find_controller(target, modifier)
    owners = tuple(
        owner for owner in (group, modifier, controller) if owner is not None)
    attribute_names = set()
    for owner in owners:
        for key in (
                _LEGACY_CHAIN_CORRECTION_ATTRIBUTE,
                _LEGACY_CHAIN_CORRECTION_ACTIVE,
        ):
            try:
                value = owner.get(key, None)
                if key == _LEGACY_CHAIN_CORRECTION_ATTRIBUTE and value:
                    attribute_names.add(str(value))
                if key in owner:
                    del owner[key]
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                continue

    if getattr(target, "type", "") != "MESH":
        return
    attributes = getattr(getattr(target, "data", None), "attributes", None)
    if attributes is None:
        return
    # Old files can lose the owner property when a modifier is duplicated;
    # fall back to the generated prefix in that case.
    if not attribute_names:
        attribute_names.update(
            attribute.name for attribute in tuple(attributes)
            if str(attribute.name).startswith(_LEGACY_CHAIN_CORRECTION_PREFIX)
        )
    for name in tuple(attribute_names):
        try:
            attribute = attributes.get(name)
            if attribute is not None:
                attributes.remove(attribute)
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            continue


def upgrade_managed_stages():
    """Rebuild older groups without discarding saved modifier parameters."""
    input_names = (
        "Center", "Rotation", "Size", "Strength", "Factor", "Direction",
        "Deform Type", "Mode", "Origin", "Preserve Volume", "Top Scale",
        "Bottom Scale", "Top Offset", "Bottom Offset", "Deform Types",
        "Bend Angle", "Bend Direction", "Twist Angle", "Taper Factor",
        "Stretch Factor", "Shear", "Influence Weight", *FFD_SOCKET_NAMES,
        "Chain Domain Attribute", "Chain Root Stage",
        "Chain Tip Stage", "Stage Enabled", "Chain Input Pivot",
        "Chain Input Inverse X", "Chain Input Inverse Y",
        "Chain Input Inverse Z", "Chain Output Offset", "Chain Output X",
        "Chain Output Y", "Chain Output Z", "Chain Source Start",
        "Chain Source End", "Chain Root Output Active",
        "Chain Global Profile Active", "Chain Global Profile Bottom Scale",
        "Chain Global Profile Top Scale", "Chain Global Profile Bottom Offset",
        "Chain Global Profile Top Offset",
        "Curve Guide Object", "Curve Station Object", "Curve Length Mode",
        "Curve Boundary Mode", "Curve Preserve Volume", "Curve Closed",
        "Curve Range Start", "Curve Range End",
        "Curve Global Radius", "Curve Global Twist",
        "Curve Rest Guide Object", "Curve Relative Binding",
    )

    def snapshot_value(value):
        if hasattr(value, "__len__") and not isinstance(value, str):
            return tuple(value)
        return value

    records = []
    groups = []
    for target in _data_objects_snapshot():
        for modifier in tuple(getattr(target, "modifiers", ())):
            node_group = getattr(modifier, "node_group", None)
            if not is_cage_modifier(modifier) or node_group is None:
                continue
            _remove_legacy_chain_correction_data(target, modifier)
            # Hide managed stage groups from node searches in older files.
            try:
                if not node_group.name.startswith("."):
                    node_group.name = f".{node_group.name}"
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                pass
            if int(node_group.get(GROUP_MARKER, 0)) == GROUP_VERSION:
                continue
            values = {
                name: snapshot_value(modifier_input(modifier, name))
                for name in input_names
                if _interface_socket(node_group, name) is not None
            }
            records.append((
                target, modifier, node_group, values,
                bool(modifier.show_viewport),
            ))
            if node_group not in groups:
                groups.append(node_group)

    # Snapshot every modifier first.  Multiple object copies can temporarily
    # share a stage group while retaining independent modifier input values.
    for node_group in groups:
        build_node_group(node_group)

    reverse_types = {value: key for key, value in DEFORM_VALUES.items()}
    curve_lengths = {value: key for key, value in CURVE_LENGTH_VALUES.items()}
    curve_modes = {value: key for key, value in CURVE_MODE_VALUES.items()}
    curve_boundaries = {
        value: key for key, value in CURVE_BOUNDARY_VALUES.items()}
    for target, modifier, _node_group, values, viewport_enabled in records:
        for name, value in values.items():
            if _interface_socket(modifier.node_group, name) is not None:
                set_modifier_input(modifier, name, value)

        legacy_type = reverse_types.get(
            int(values.get("Deform Type", 0)), "BEND")
        legacy_strength = float(values.get(
            "Strength", math.radians(45.0)))
        legacy_factor = float(values.get("Factor", 0.5))
        legacy_direction = float(values.get("Direction", 0.0))
        enabled = deform_types_from_mask(
            values.get("Deform Types", DEFORM_BITS[legacy_type]))
        migrated_values = {
            "Deform Types": deform_type_mask(enabled, legacy_type),
            "Bend Angle": float(values.get(
                "Bend Angle", legacy_strength)),
            "Bend Direction": float(values.get(
                "Bend Direction", legacy_direction)),
            "Twist Angle": float(values.get(
                "Twist Angle", legacy_strength)),
            "Taper Factor": float(values.get(
                "Taper Factor", legacy_factor)),
            "Stretch Factor": float(values.get(
                "Stretch Factor", legacy_factor)),
            "Stage Enabled": bool(values.get(
                "Stage Enabled", viewport_enabled)),
        }
        for name, value in migrated_values.items():
            set_modifier_input(modifier, name, value)

        controller = find_controller(target, modifier)
        if controller is not None:
            pointer = _pointer(controller)
            if pointer:
                _SYNCING.add(pointer)
            try:
                properties = controller.sdh_cage_deform
                properties.deform_type = legacy_type
                properties.deform_types = enabled
                properties.muted_deform_types = set()
                properties.deform_order = encode_deform_order(
                    properties.deform_order, enabled, legacy_type)
                properties.strength = legacy_strength
                properties.factor = legacy_factor
                properties.direction = legacy_direction
                properties.bend_strength = migrated_values["Bend Angle"]
                properties.bend_direction = migrated_values["Bend Direction"]
                properties.twist_strength = migrated_values["Twist Angle"]
                properties.taper_factor = migrated_values["Taper Factor"]
                properties.stretch_factor = migrated_values["Stretch Factor"]
                properties.shear_factors = tuple(
                    values.get("Shear", (0.0, 0.0, 0.0)))[::2]
                properties.ffd_offsets = tuple(
                    float(component)
                    for socket_name in FFD_SOCKET_NAMES
                    for component in tuple(values.get(
                        socket_name, (0.0, 0.0, 0.0)))[:3]
                )
                properties.stage_enabled = migrated_values["Stage Enabled"]
                properties.curve_length_mode = curve_lengths.get(
                    int(values.get(
                        "Curve Length Mode", CURVE_LENGTH_VALUES["STRETCH"])),
                    "STRETCH",
                )
                properties.curve_control_mode = (
                    "CAGE"
                    if properties.curve_length_mode == "PRESERVE" else
                    "CURVE")
                curve_mode_value = int(values.get(
                    "Curve Boundary Mode", CURVE_MODE_VALUES["LIMITED"]))
                properties.curve_mode = curve_modes.get(
                    curve_mode_value, "LIMITED")
                properties.curve_boundary_mode = curve_boundaries.get(
                    curve_mode_value,
                    CURVE_MODE_BOUNDARY[properties.curve_mode],
                )
                properties.curve_preserve_volume = bool(values.get(
                    "Curve Preserve Volume", False))
                properties.curve_closed = bool(values.get(
                    "Curve Closed", False))
                properties.curve_range_start = float(values.get(
                    "Curve Range Start", 0.0))
                properties.curve_range_end = float(values.get(
                    "Curve Range End", 1.0))
                properties.curve_global_radius = float(values.get(
                    "Curve Global Radius", 1.0))
                properties.curve_global_twist = float(values.get(
                    "Curve Global Twist", 0.0))
                properties.curve_relative_binding = bool(values.get(
                    "Curve Relative Binding", False))
                properties.show_axis_gizmo = False
                properties.show_direction_handle = False
            finally:
                if pointer:
                    _SYNCING.discard(pointer)
            _set_controller_style(controller)
            sync_controller(controller, pull_transform=False)
        # Before version 13 the stack eye wrote show_viewport directly. Move
        # that saved UI state into the internal bypass so a disabled upstream
        # stage can keep forwarding the chain domain to later cages.
        if "Stage Enabled" not in values and not viewport_enabled:
            modifier.show_viewport = True
        target.update_tag()
    return len(records)


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
    for obj in _data_objects_snapshot():
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
    for target in _data_objects_snapshot():
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
                properties.deform_types = {"BEND"}
                properties.muted_deform_types = set()
                properties.deform_order = encode_deform_order(("BEND",))
                properties.size = tuple(values["Size"])
                properties.strength = float(values["Strength"])
                properties.direction = float(values["Direction"])
                properties.bend_strength = float(values["Strength"])
                properties.twist_strength = float(values["Strength"])
                properties.bend_direction = float(values["Direction"])
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
    _drain_target_ownership_repairs()
    if _LEGACY_MIGRATION_PENDING:
        migrate_legacy_stages()
        upgrade_managed_stages()
        try:
            from . import chain as chain_module
            chain_module.normalize_all_chain_metadata()
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
        organize_helper_objects()
        _LEGACY_MIGRATION_PENDING = False
    _cleanup_orphans_after_object_count_change(force=True)
    # sync_all_controllers performs the single scene snapshot used by the
    # maintenance pass; its count is only useful to direct callers.
    sync_all_controllers(pull_transform=True, sync_mode="timer")
    _drain_ffd_scope_refresh_queue()
    refresh_controller_display()
    _drain_chain_reconnect_queue()
    _drain_stack_auto_fit_queue()
    _drain_lattice_origin_sync_queue()
    # This is a one-shot maintenance pass.  Property callbacks and the
    # dependency-graph handler schedule later work only when something changed.
    if _TARGET_OWNERSHIP_REPAIR_QUEUE:
        return 0.05
    return 0.0 if (_STACK_AUTO_FIT_QUEUE or _LATTICE_ORIGIN_QUEUE) else None


def _selection_signature(context):
    """Return every source field that can change the expected cage tool."""
    try:
        selected = tuple(getattr(context, "selected_objects", ()) or ())
        view_layer = getattr(context, "view_layer", None)
        active = getattr(view_layer, "objects", None)
        active = getattr(active, "active", None)
        target = _workspace_target_from_active(active)
        modifier = (
            getattr(getattr(target, "modifiers", None), "active", None)
            if target is not None else None)
        controller = (
            find_controller(target, modifier)
            if target is not None and is_cage_modifier(modifier) else None)
        cage_type = str(getattr(
            getattr(controller, "sdh_cage_deform", None),
            "cage_type", ""))
        return (
            _pointer(getattr(context, "workspace", None)),
            _pointer(getattr(context, "window", None)),
            _pointer(view_layer),
            str(getattr(context, "mode", "OBJECT")),
            _pointer(active),
            tuple(sorted(_pointer(obj) for obj in selected)),
            _pointer(modifier),
            cage_type,
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return (0, 0, 0, "OBJECT", 0, (), 0, "")


def _selection_sync_timer():
    """Apply target-to-controller selection after Blender finishes selecting."""
    global _PENDING_STAGE_SELECTION_RESTORE
    if not _RUNTIME_HANDLERS_REGISTERED:
        return None
    tool_synced = False
    try:
        context = bpy.context
        pending = _PENDING_STAGE_SELECTION_RESTORE
        if pending is not None:
            pending_target, pending_modifier_uuid, passes_left = pending
            if passes_left > 0:
                _PENDING_STAGE_SELECTION_RESTORE = (
                    pending_target, pending_modifier_uuid, passes_left - 1)
                return 0.01
            _PENDING_STAGE_SELECTION_RESTORE = None
            try:
                pending_modifier = find_modifier(
                    pending_target, modifier_uuid=pending_modifier_uuid)
                current_modifier = getattr(
                    getattr(pending_target, "modifiers", None), "active", None)
                if (
                        pending_target is not None and
                        pending_modifier is not None and
                        current_modifier == pending_modifier
                ):
                    _activate(context, pending_target)
                    refresh_controller_display(context, force=True)
                    tool_synced, _changed = (
                        _sync_workspace_tool_selection_state(context))
                    return None if tool_synced else 0.05
            except (AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError):
                pass
        selected_objects = tuple(
            getattr(context, "selected_objects", ()) or ())
        if not selected_objects and _PENDING_STAGE_SELECTION_RESTORE is None:
            # A real deselection takes precedence over persistent editor
            # flags. End live sessions before switching tools; otherwise their
            # next mouse event would immediately reselect the target.
            finish_ffd_edit_sessions(context, restore_target=False)
            try:
                from . import curve as curve_module
                curve_module.finish_curve_edit_sessions(
                    context, restore_target=False)
            except (AttributeError, ImportError, ReferenceError, RuntimeError,
                    TypeError):
                pass
            activate_cage_workspace_tool(context, "")
            # The selection watcher can run after Blender has already changed
            # the active tool.  Refresh visibility in the same safe timer pass
            # so stale cage Gizmos/controllers cannot keep consuming the next
            # native box-select gesture.
            refresh_controller_display(context, force=True)
        tool_synced, selection_changed = (
            _sync_workspace_tool_selection_state(context))
        if not selection_changed:
            return None if tool_synced else 0.05
        active = getattr(getattr(context, "view_layer", None),
                         "objects", None)
        active = getattr(active, "active", None)
        if active is None:
            return None if tool_synced else 0.05
        target = (
            _controller_owner_target(active)
            if is_cage_controller(active) else
            active if getattr(active, "type", None) in SUPPORTED_TYPES else
            None
        )
        selected_objects = tuple(
            getattr(context, "selected_objects", ()) or ())
        # A direct click on an inactive FFD handle starts its modal before
        # Blender applies the Gizmo's final object-pick result. That late pass
        # can leave the controlled target active but unselected, so neither
        # the controller-only repair below nor the regular selected-target
        # path can retain the cage stack. A live FFD edit flag is authoritative
        # in this transient state: restore the target and all of its cage
        # controllers without waiting for another pointer event.
        if target is not None and target not in selected_objects:
            editing_controller = None
            for candidate_modifier in cage_modifiers(target):
                candidate_controller = find_controller(
                    target, candidate_modifier)
                candidate_properties = getattr(
                    candidate_controller, "sdh_cage_deform", None)
                if (
                        candidate_properties is not None and
                        str(getattr(
                            candidate_properties, "cage_type", "")) ==
                        "FFD" and
                        bool(getattr(
                            candidate_properties,
                            "ffd_edit_mode_active", False))
                ):
                    editing_controller = candidate_controller
                    break
            if (
                    editing_controller is not None and
                    _live_workspace_cage_type(target) == "FFD"
            ):
                if _activate_ffd_edit_selection(
                        context, target, editing_controller):
                    refresh_controller_display(context, force=True)
                    tool_synced, _changed = (
                        _sync_workspace_tool_selection_state(context))
                return None if tool_synced else 0.05
        # Blender may apply its normal Gizmo selection result after an FFD
        # point click.  During the persistent editor the controller can then
        # briefly become the only selected object, which hides the target-bound
        # cage and makes the editor appear to have closed.  Restore the pair
        # from the stable edit-session flag as soon as the selection watcher
        # observes that transient state; no extra mouse event is required.
        active_properties = getattr(active, "sdh_cage_deform", None)
        if (
                target is not None and
                active_properties is not None and
                str(getattr(active_properties, "cage_type", "")) == "FFD" and
                bool(getattr(active_properties, "ffd_edit_mode_active", False)) and
                _live_workspace_cage_type(target) == "FFD"
        ):
            if _activate_ffd_edit_selection(context, target, active):
                refresh_controller_display(context, force=True)
                tool_synced, _changed = (
                    _sync_workspace_tool_selection_state(context))
            return None if tool_synced else 0.05
        # Activating the FFD Workspace Tool from an inactive-cage picker can
        # make Blender apply a late object-pick result after the stage operator
        # has already restored the target.  In that transient frame only a
        # helper Empty remains active, which drops the panel/Gizmo target and
        # makes every cage appear to vanish.  The FFD tool never performs
        # native Object transforms, so restore the controlled object here;
        # Move/Rotate/Scale tools keep their controller-only selection intact.
        if (
                target is not None and is_cage_controller(active) and
                _active_workspace_tool_id(context) == _FFD_WORKSPACE_TOOL_ID
        ):
            _activate(context, target)
            refresh_controller_display(context, force=True)
            tool_synced, _changed = (
                _sync_workspace_tool_selection_state(context))
            return None if tool_synced else 0.05
        if target is not None and target in selected_objects:
            # Force the display pass so a selection-only change is not hidden
            # by the normal display signature cache.  The target remains
            # active; all stage controllers are added as secondary selection.
            refresh_controller_display(context, force=True)
        tool_synced, _changed = _sync_workspace_tool_selection_state(context)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return None if tool_synced else 0.05


def _selection_watch_timer():
    """Fallback watcher for viewport selection paths without RNA notifications."""
    if not _RUNTIME_HANDLERS_REGISTERED:
        return None
    object_count_changed = _cleanup_orphans_after_object_count_change()
    if object_count_changed:
        if not _runtime_has_managed_deformation():
            finish_ffd_edit_sessions(bpy.context, restore_target=False)
            try:
                from . import curve as curve_module
                curve_module.finish_curve_edit_sessions(
                    bpy.context, restore_target=False)
            except (AttributeError, ImportError, ReferenceError, RuntimeError,
                    TypeError):
                pass
            activate_cage_workspace_tool(bpy.context, "")
            refresh_controller_display(bpy.context, force=True)
            disable_runtime_handlers()
            return None
    # Once an empty selection has been handed back to Blender, there is no
    # cage state to reconcile on every watch tick.  The selection msgbus marks
    # ``_SELECTION_SYNC_DIRTY`` when a real selection/active-object change
    # arrives, so keep the 120 ms watcher cheap while the user is simply
    # moving the pointer over an empty viewport.  This is especially important
    # for macOS, where repeatedly switching tools or scanning a large chain can
    # stall the main event loop without showing high CPU usage.
    try:
        selected_objects = tuple(
            getattr(bpy.context, "selected_objects", ()) or ())
        if (
                not selected_objects and
                not _SELECTION_SYNC_DIRTY and
                _SELECTION_SYNC_SIGNATURE is not None and
                len(_SELECTION_SYNC_SIGNATURE) > 5 and
                not _SELECTION_SYNC_SIGNATURE[5]
        ):
            return _SELECTION_WATCH_INTERVAL
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    _selection_sync_timer()
    return _SELECTION_WATCH_INTERVAL


def _selection_sync_notify():
    """Defer selection synchronization out of Blender's RNA callback."""
    global _SELECTION_SYNC_DIRTY
    if not _RUNTIME_HANDLERS_REGISTERED:
        return
    _SELECTION_SYNC_DIRTY = True
    try:
        if not bpy.app.timers.is_registered(_selection_sync_timer):
            bpy.app.timers.register(_selection_sync_timer, first_interval=0.0)
    except (AttributeError, RuntimeError, ValueError, TypeError):
        pass


def _queue_stage_selection_restore(target, modifier=None):
    """Restore a stage-picker target after Blender's late selection pass."""
    global _PENDING_STAGE_SELECTION_RESTORE
    if target is None:
        return
    _PENDING_STAGE_SELECTION_RESTORE = (
        target, str(cage_modifier_uuid(modifier) or ""), 1)
    _selection_sync_notify()


def _subscribe_selection_sync():
    """Listen for both active-object and multi-selection changes."""
    try:
        bpy.msgbus.clear_by_owner(_SELECTION_SYNC_MSG_OWNER)
        layer_objects = getattr(bpy.types, "LayerObjects", None)
        if layer_objects is None:
            return
        for property_name in ("active", "selected"):
            if property_name not in layer_objects.bl_rna.properties:
                continue
            bpy.msgbus.subscribe_rna(
                key=(layer_objects, property_name),
                owner=_SELECTION_SYNC_MSG_OWNER,
                args=(),
                notify=_selection_sync_notify,
            )
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass


def _unsubscribe_selection_sync():
    """Remove selection callbacks and any deferred one-shot timer."""
    global _SELECTION_SYNC_SIGNATURE, _SELECTION_SYNC_DIRTY
    global _PENDING_STAGE_SELECTION_RESTORE
    try:
        bpy.msgbus.clear_by_owner(_SELECTION_SYNC_MSG_OWNER)
        if bpy.app.timers.is_registered(_selection_sync_timer):
            bpy.app.timers.unregister(_selection_sync_timer)
    except (AttributeError, RuntimeError, ValueError, TypeError):
        pass
    _SELECTION_SYNC_SIGNATURE = None
    _SELECTION_SYNC_DIRTY = False
    _PENDING_STAGE_SELECTION_RESTORE = None
    _WORKSPACE_TOOL_CONFIRMATIONS.clear()
    _WORKSPACE_TOOL_OVERRIDES.clear()


def _ensure_selection_sync_runtime():
    """Restore load-cleared selection subscriptions and the persistent watch."""
    global _SELECTION_SYNC_SIGNATURE, _SELECTION_SYNC_DIRTY
    if not _RUNTIME_HANDLERS_REGISTERED:
        return False
    _SELECTION_SYNC_SIGNATURE = None
    _SELECTION_SYNC_DIRTY = True
    _WORKSPACE_TOOL_CONFIRMATIONS.clear()
    _WORKSPACE_TOOL_OVERRIDES.clear()
    _subscribe_selection_sync()
    try:
        if not bpy.app.timers.is_registered(_selection_watch_timer):
            bpy.app.timers.register(
                _selection_watch_timer,
                first_interval=_SELECTION_WATCH_INTERVAL,
                persistent=True,
            )
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False
    _selection_sync_notify()
    return True


def _runtime_bootstrap_timer():
    """Discover and synchronize cages after registration or file loading."""
    if not hasattr(bpy.types.Object, "sdh_cage_deform"):
        return None
    register_ffd_workspace_tool()
    try:
        _cleanup_orphans_after_object_count_change(force=True)
        has_deformation = _runtime_has_managed_deformation()
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        # Registration can briefly expose ``_RestrictData``. Retry once the
        # normal data API is available, without keeping a polling timer alive.
        return 0.1
    if has_deformation:
        enable_runtime_handlers()
        # A controller animation is stored on the controller while Geometry
        # Nodes evaluates the mirrored modifier inputs.  Synchronize once now;
        # waiting for the next user event leaves a freshly loaded file frozen
        # at the socket values saved on disk.
        _load_sync(None)
    elif _RUNTIME_HANDLERS_REGISTERED:
        disable_runtime_handlers()
    return None


def schedule_runtime_bootstrap():
    """Defer cage discovery until Blender exposes its normal data API."""
    try:
        if not bpy.app.timers.is_registered(_runtime_bootstrap_timer):
            bpy.app.timers.register(_runtime_bootstrap_timer, first_interval=0.0)
    except (AttributeError, RuntimeError, ValueError):
        pass


@persistent
def _runtime_load_discovery(_unused):
    """Always discover managed cages after opening another Blender file."""
    schedule_runtime_bootstrap()


@persistent
def _runtime_undo_discovery(_unused):
    """Rediscover cages even after the heavy undo handler was disabled."""
    schedule_runtime_bootstrap()


def register_runtime_discovery_handler():
    """Install lightweight discovery hooks even when no cage currently exists."""
    callbacks = (
        (bpy.app.handlers.load_post, _runtime_load_discovery),
        (bpy.app.handlers.undo_post, _runtime_undo_discovery),
        (bpy.app.handlers.redo_post, _runtime_undo_discovery),
    )
    for handler_list, callback in callbacks:
        while callback in handler_list:
            handler_list.remove(callback)
        handler_list.append(callback)


def unregister_runtime_discovery_handler():
    """Remove permanent discovery hooks during add-on shutdown or reload."""
    for handler_list, callback in (
            (bpy.app.handlers.load_post, _runtime_load_discovery),
            (bpy.app.handlers.undo_post, _runtime_undo_discovery),
            (bpy.app.handlers.redo_post, _runtime_undo_discovery)):
        while callback in handler_list:
            try:
                handler_list.remove(callback)
            except (RuntimeError, ValueError):
                break


def enable_runtime_handlers():
    """Enable cage synchronization only while managed cages are in use."""
    global _RUNTIME_HANDLERS_REGISTERED
    # File loading clears timers and message-bus subscriptions even when the
    # Python module and persistent handlers survive. Reconcile every callback
    # instead of trusting the previous-file flag.
    callbacks = (
        (bpy.app.handlers.frame_change_post, _frame_change_sync),
        (bpy.app.handlers.render_pre, _render_sync),
        (bpy.app.handlers.undo_post, _undo_redo_sync),
        (bpy.app.handlers.redo_post, _undo_redo_sync),
        (bpy.app.handlers.depsgraph_update_post, _depsgraph_sync),
    )
    for handler_list, callback in callbacks:
        while callback in handler_list:
            handler_list.remove(callback)
        handler_list.append(callback)
    _RUNTIME_HANDLERS_REGISTERED = True
    _ensure_selection_sync_runtime()
    try:
        if not bpy.app.timers.is_registered(_controller_timer):
            bpy.app.timers.register(_controller_timer, first_interval=0.01)
    except (RuntimeError, ValueError):
        # Blender may reject a timer during shutdown.  The handlers remain
        # useful and the next property/depsgraph event can retry the pass.
        pass


def disable_runtime_handlers():
    """Remove cage handlers and any pending maintenance callback."""
    global _ORPHAN_HELPER_OBJECT_COUNT, _RUNTIME_HANDLERS_REGISTERED
    try:
        if bpy.app.timers.is_registered(_runtime_bootstrap_timer):
            bpy.app.timers.unregister(_runtime_bootstrap_timer)
        if bpy.app.timers.is_registered(_controller_timer):
            bpy.app.timers.unregister(_controller_timer)
        if bpy.app.timers.is_registered(_selection_watch_timer):
            bpy.app.timers.unregister(_selection_watch_timer)
    except (AttributeError, RuntimeError, ValueError):
        pass
    _unsubscribe_selection_sync()
    for handler_list, callback in (
            (bpy.app.handlers.frame_change_post, _frame_change_sync),
            (bpy.app.handlers.render_pre, _render_sync),
            (bpy.app.handlers.undo_post, _undo_redo_sync),
            (bpy.app.handlers.redo_post, _undo_redo_sync),
            (bpy.app.handlers.depsgraph_update_post, _depsgraph_sync)):
        while callback in handler_list:
            try:
                handler_list.remove(callback)
            except (ValueError, RuntimeError):
                break
    _RUNTIME_HANDLERS_REGISTERED = False
    _ORPHAN_HELPER_OBJECT_COUNT = -1


@persistent
def _depsgraph_sync(_scene, depsgraph):
    """Queue controller transforms and recoverable chain stack edits.

    Object-mode G/R/S does not invoke PropertyGroup callbacks.  Restricting
    this handler to managed controllers, or to the updated target itself,
    avoids a global object scan.  Native Modifier-panel drag-reordering
    updates the target object's geometry instead of a controller; in that
    case a persisted stage-index mismatch is recoverable and is queued for
    the same zero-delay timer.  RNA writes remain outside dependency-graph
    evaluation, where they could recursively trigger this handler.
    """
    if depsgraph is None:
        return
    if render_job_running():
        return
    queued = False
    try:
        updates = tuple(depsgraph.updates)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return
    # Updating one hidden FFD lattice also reports its evaluated target Mesh as
    # geometry-updated even though the source vertex coordinates did not
    # change. Recognize that paired update before walking the list so ordinary
    # point drags keep the scope-coordinate cache hot. A real source-mesh edit
    # reports the Mesh without a managed lattice object and remains invalid.
    internal_ffd_mesh_updates = set()
    for candidate_update in updates:
        try:
            candidate = getattr(
                candidate_update.id, "original", candidate_update.id)
            if not (
                    isinstance(candidate, bpy.types.Object) and
                    getattr(candidate, "type", None) == "LATTICE" and
                    bool(candidate.get(FFD_LATTICE_MARKER, False)) and
                    (
                        getattr(candidate_update, "is_updated_geometry", False) or
                        getattr(candidate_update, "is_updated_transform", False)
                    )
            ):
                continue
            owner = getattr(candidate, "parent", None)
            mesh = getattr(owner, "data", None)
            if isinstance(mesh, bpy.types.Mesh):
                internal_ffd_mesh_updates.add(_pointer(mesh))
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            continue
    for update in updates:
        try:
            updated_id = update.id
            try:
                from .curve import request_curve_relation_sync_from_update
                request_curve_relation_sync_from_update(updated_id)
            except (AttributeError, ImportError, ReferenceError, RuntimeError,
                    TypeError, ValueError):
                pass
            updated_id = getattr(updated_id, "original", updated_id)
            if isinstance(updated_id, bpy.types.Mesh):
                mesh_pointer = _pointer(updated_id)
                if mesh_pointer in internal_ffd_mesh_updates:
                    _FFD_SCOPE_MESH_WRITE_GUARD.discard(mesh_pointer)
                    continue
                if mesh_pointer in _FFD_SCOPE_MESH_WRITE_GUARD:
                    _FFD_SCOPE_MESH_WRITE_GUARD.discard(mesh_pointer)
                    continue
                if (
                        getattr(update, "is_updated_geometry", False) and
                        _mark_ffd_scope_mesh_dirty(updated_id)
                ):
                    queued = True
                continue
            if not isinstance(updated_id, bpy.types.Object):
                continue
            # Bounds sampling links a short-lived copy of the target so its
            # upstream modifier prefix can be evaluated.  That copy retains
            # the cage modifiers and therefore looks like another managed
            # target to this handler, but it is removed immediately after the
            # sample. Never queue a reference that is about to become invalid.
            if bool(updated_id.get(RUNTIME_EVALUATOR, False)):
                continue
            target_mesh = getattr(updated_id, "data", None)
            target_mesh_pointer = _pointer(target_mesh)
            if (
                    getattr(updated_id, "type", None) == "MESH" and
                    getattr(update, "is_updated_geometry", False) and
                    target_mesh_pointer not in internal_ffd_mesh_updates and
                    target_mesh_pointer not in _FFD_SCOPE_MESH_WRITE_GUARD and
                    not _ffd_scope_tracks_target(updated_id) and
                    _mark_ffd_scope_target_dirty(updated_id)
            ):
                queued = True
            if (
                    getattr(updated_id, "type", None) == "LATTICE" and
                    (
                        getattr(update, "is_updated_transform", False) or
                        getattr(update, "is_updated_geometry", False) or
                        getattr(update, "is_updated_shading", False)
                    ) and
                    request_lattice_origin_sync(updated_id)
            ):
                queued = True
            if is_cage_controller(updated_id):
                if not update.is_updated_transform:
                    continue
                controller = updated_id
                pointer = _pointer(controller)
                if not pointer:
                    continue
                signature = _controller_transform_signature(controller)
                if _CONTROLLER_TRANSFORM_SNAPSHOTS.get(pointer) == signature:
                    continue
                _CONTROLLER_TRANSFORM_QUEUE[pointer] = controller
                queued = True
                continue

            # A native modifier reorder is reported on the target Object as a
            # geometry update.  Inspect only this updated object and only its
            # managed chain UUIDs; never walk the scene from the depsgraph
            # callback.  Structural errors remain untouched and are still
            # surfaced to the panel/operator diagnostics.
            if not (
                    getattr(update, "is_updated_geometry", False) or
                    getattr(update, "is_updated_shading", False)):
                continue
            # Mesh/object edits and native upstream modifiers do not invoke a
            # cage PropertyGroup callback. Let ordinary opt-in cages refit on
            # the next safe timer pass; cached bounds prevent self-triggered
            # updates from forming a dependency-graph loop.
            target_pointer = _pointer(updated_id)
            if (
                    target_pointer not in _STACK_AUTO_FIT_DEPSGRAPH_GUARD and
                    request_stack_auto_fit(updated_id)
            ):
                queued = True
            try:
                from . import chain as chain_module
                chain_ids = tuple(chain_module.chain_ids(updated_id))
            except (ImportError, AttributeError, ReferenceError, RuntimeError,
                    TypeError, ValueError):
                continue
            for chain_uuid in chain_ids:
                try:
                    report = chain_module.validate_chain(
                        updated_id, chain_uuid)
                except (AttributeError, ReferenceError, RuntimeError, TypeError,
                        ValueError):
                    continue
                if not report.get("index_mismatch"):
                    continue
                # Only the order-only mismatch can be repaired safely.  A
                # missing/duplicate stage, an inserted ordinary modifier, or
                # a missing controller needs explicit user-facing recovery.
                if any(report.get(name) for name in (
                        "missing_indices", "duplicate_indices",
                        "ordinary_between", "missing_controllers",
                        "mode_mismatch")):
                    continue
                if request_chain_reconnect(updated_id, chain_uuid):
                    queued = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            continue
    if queued:
        _schedule_chain_reconnect()


@persistent
def _frame_change_sync(_scene, *_args):
    """Push animated values without mutating scene structure mid-evaluation.

    Auto fitting and chain reconnection can create, link, and remove temporary
    objects while measuring evaluated geometry.  ``frame_change_post`` still
    runs inside Blender's new-frame dependency-graph update, where those
    operations can invalidate an evaluated Base and crash Blender.  Property
    synchronization stays immediate; structural work is already coalesced by
    the normal zero-delay timer and runs after the frame update returns.
    """
    sync_all_controllers(pull_transform=True, sync_mode="timer")
    if (
            _CONTROLLER_TRANSFORM_QUEUE or _CHAIN_RECONNECT_QUEUE or
            _STACK_AUTO_FIT_QUEUE
    ):
        _schedule_chain_reconnect()


@persistent
def _render_sync(_scene, *_args):
    sync_all_controllers(pull_transform=True, sync_mode="timer")
    _drain_chain_reconnect_queue()
    _drain_stack_auto_fit_queue()


@persistent
def _load_sync(_unused):
    global _LEGACY_MIGRATION_PENDING
    clear_chain_reconnect_state()
    _cleanup_orphans_after_object_count_change(force=True)
    _reconcile_ffd_edit_session_flags()
    migrate_legacy_stages()
    upgrade_managed_stages()
    try:
        from . import chain as chain_module
        chain_module.normalize_all_chain_metadata()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    organize_helper_objects()
    sync_all_controllers(pull_transform=True, sync_mode="push")
    _drain_chain_reconnect_queue()
    _LEGACY_MIGRATION_PENDING = False
    _ensure_selection_sync_runtime()
    _tag_view3d_redraw()


@persistent
def _undo_redo_sync(_unused):
    """Repair helper ownership once after Blender restores an undo state."""
    clear_ffd_scope_cache()
    _cleanup_orphans_after_object_count_change(force=True)
    _reconcile_ffd_edit_session_flags()
    refresh_controller_display(force=True)


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
    if is_cage_controller(obj):
        # A controller is hidden whenever its target is not selected. Unhide it
        # before selecting so panel/gizmo stage switches can start a real edit
        # session instead of leaving Blender with an active-but-unselected Empty.
        set_helper_object_visible(obj, True, getattr(context, "view_layer", None))
    for selected in tuple(context.selected_objects):
        selected.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def _activate_ffd_edit_selection(context, target, controller):
    """Select the target and FFD controller while editing FFD points.

    FFD animation lives on the controller object. Keeping that controller
    selected makes its keyframes available in Blender's Timeline.  Keep the
    controlled object active so the N-panel and every cage GizmoGroup retain
    their target context while Blender finishes dispatching a Gizmo click.
    """
    if target is None or controller is None:
        return False
    set_helper_object_visible(
        controller, True, getattr(context, "view_layer", None))
    for selected in tuple(getattr(context, "selected_objects", ())):
        try:
            selected.select_set(False)
        except (ReferenceError, RuntimeError, TypeError):
            pass
    try:
        target.select_set(True)
        controller.select_set(True)
        context.view_layer.objects.active = target
        _sync_target_cage_selection(context, target)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return False
    return True


def _modifier_input_bounds(context, target, modifier):
    """Evaluate fresh geometry entering one cage stage.

    This is only used by discrete fit, boundary-invoke, and stage-creation
    operations. Mesh coordinates and arbitrary upstream modifier dependencies
    cannot be represented by a reliable cheap cache token.
    """
    try:
        node_group = getattr(modifier, "node_group", None)
        source_index = int(node_group.get(
            "_sdh_deform_merge_final_source_index", -1))
        if (
                source_index >= 0 and
                bool(node_group.get(
                    "_sdh_deform_merge_final_source_stage", False)) and
                bool(target.get("_sdh_deform_merge", False))):
            from .merge import evaluated_source_bounds
            filtered = evaluated_source_bounds(
                context, target, source_index, modifier=modifier)
            if filtered is not None:
                return filtered
    except (AttributeError, ImportError, KeyError, ReferenceError, RuntimeError,
            TypeError, ValueError):
        pass
    try:
        stack_index = tuple(target.modifiers).index(modifier)
    except ValueError:
        return _object_fallback_bounds(target)

    # A cage can be added immediately after a viewport drag, before the next
    # timer pass has copied controller RNA into its Geometry Nodes sockets.
    # Push every upstream managed controller first so the temporary evaluator
    # sees the same applied shape that the user sees in the viewport.
    try:
        upstream_modifiers = tuple(target.modifiers)[:stack_index]
        for upstream_modifier in upstream_modifiers:
            upstream_controller = find_controller(target, upstream_modifier)
            if upstream_controller is not None:
                sync_controller(
                    upstream_controller,
                    pull_transform=False,
                    sync_mode="push",
                )
        context.view_layer.update()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

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
        evaluated_mesh = None
        result = None
        try:
            # Object.bound_box can retain an earlier dependency-graph cache
            # while a freshly inserted stage is being fitted. Read evaluated
            # vertices instead: they are the actual geometry entering the new
            # cage and therefore include every enabled upstream cage type.
            evaluated_mesh = evaluated.to_mesh()
            result = _bounds_from_points(
                (vertex.co for vertex in evaluated_mesh.vertices),
            )
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            result = None
        finally:
            if evaluated_mesh is not None:
                evaluated.to_mesh_clear()
        if result is not None:
            return result
        # Keep a bound-box fallback for object types whose evaluated geometry
        # cannot be converted to a mesh in a particular Blender build.
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


def fit_controller_to_bounds(context, target, modifier, controller, bounds):
    """Fit a controller to an already evaluated local-space bounds pair.

    Most stages derive their bounds from the complete geometry entering the
    modifier.  Multi-object source stages can pass a filtered bounds pair so
    the controller follows only the selected source's final geometry.
    """
    if bounds is None or len(bounds) != 2:
        return None
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
        # All generated/reconnected frames use one explicit Euler order.  A
        # saved Empty can otherwise retain Quaternion or Axis Angle mode and
        # interpret the same three values differently on the next fit.
        try:
            controller.rotation_mode = "XYZ"
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        controller.location = center + rotation_matrix @ local_center
        controller.rotation_euler = rotation
        properties.size = size
        controller.scale = tuple(value * 0.5 for value in size)
    finally:
        _SYNCING.discard(pointer)
    sync_controller(controller, pull_transform=False)
    if _stack_auto_fit_enabled(controller, modifier) and pointer:
        _STACK_AUTO_FIT_SIGNATURES[pointer] = _stack_auto_fit_signature(
            controller, bounds)
    return bounds


def fit_controller(context, target, modifier, controller):
    bounds = _modifier_input_bounds(context, target, modifier)
    return fit_controller_to_bounds(context, target, modifier, controller, bounds)


def fit_controller_to_alignment(
        context, target, modifier, controller, alignment, *,
        bend_direction=None):
    """Set an axis/trend choice and fit one cage to its live stage input.

    Axis buttons are authoring commands, so they must update the frame and
    bounds together. End profiles and deformation strengths are deliberately
    left untouched; only the alignment, optional bend direction, transform,
    and size are changed.
    """
    if target is None or modifier is None or controller is None:
        return None
    properties = controller.sdh_cage_deform
    pointer = _pointer(controller)
    if pointer:
        _SYNCING.add(pointer)
    try:
        properties.alignment = str(alignment)
        if bend_direction is not None:
            direction = float(bend_direction)
            properties.bend_direction = direction
            properties.direction = direction
    finally:
        if pointer:
            _SYNCING.discard(pointer)
    return fit_controller(context, target, modifier, controller)


def redirect_controller_frame(context, target, modifier, controller, alignment,
                              *, bend_direction=None):
    """Aim the cage frame without fitting or rewriting its authored shape."""
    if target is None or modifier is None or controller is None:
        return None
    properties = controller.sdh_cage_deform
    bounds = (
        _modifier_input_bounds(context, target, modifier)
        if alignment == "AUTO" else
        (Vector((0.0, 0.0, 0.0)), Vector((1.0, 1.0, 1.0)))
    )
    rotation = _alignment_rotation(alignment, bounds)
    location = controller.location.copy()
    scale = controller.scale.copy()
    size = tuple(properties.size)

    pointer = _pointer(controller)
    _SYNCING.add(pointer)
    try:
        controller.rotation_mode = "XYZ"
        controller.rotation_euler = rotation
        controller.location = location
        controller.scale = scale
        properties.size = size
        properties.alignment = alignment
        if bend_direction is not None:
            direction = float(bend_direction)
            properties.bend_direction = direction
            properties.direction = direction
    finally:
        _SYNCING.discard(pointer)

    # Push the new frame and optional bend trend through the normal path so a
    # managed chain receives the same debounced reconnect request as a direct
    # controller transform.  Restore the authored scale because push sync uses
    # size/2 as its display representation and must not turn an axis choice
    # into an implicit resize.
    sync_controller(controller, pull_transform=False)
    _SYNCING.add(pointer)
    try:
        controller.location = location
        controller.scale = scale
        properties.size = size
    finally:
        _SYNCING.discard(pointer)
    _CONTROLLER_TRANSFORM_SNAPSHOTS[pointer] = (
        _controller_transform_signature(controller))
    return rotation


def _new_controller(context, target, modifier):
    target_uuid = ensure_unique_target_uuid(target)
    modifier_uuid = cage_modifier_uuid(modifier)
    controller = bpy.data.objects.new(f"{modifier.name} Controller", None)
    # Keep controller frames deterministic across Blender files and versions;
    # reconnect_chain writes XYZ Euler values as well.
    try:
        controller.rotation_mode = "XYZ"
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
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
    "cage_type", "deform_order", "active_deform_layer",
    "expanded_deform_layers", "expand_all_deform_layers",
    "stage_enabled", "deform_types",
    "muted_deform_types", "deform_type",
    "bend_strength", "bend_direction",
    "twist_strength", "taper_factor", "stretch_factor", "shear_factors",
    "ffd_offsets", "strength",
    "ffd_axes_linked", "ffd_resolution_u", "ffd_resolution_v",
    "ffd_resolution_w",
    "ffd_use_outside", "ffd_interpolation_u", "ffd_interpolation_v",
    "ffd_interpolation_w", "ffd_guard_mode", "ffd_active_point",
    "ffd_symmetry_enabled", "ffd_symmetry_axis",
    "ffd_symmetry_axes", "ffd_symmetry_axes_initialized",
    "ffd_selection_mode", "ffd_selection_modes",
    "ffd_selection_modes_initialized",
    "curve_active_point", "curve_equalize_count",
    "curve_point_global_falloff", "curve_active_station",
    "curve_even_stations",
    "curve_global_radius", "curve_global_twist",
    "curve_relative_binding",
    "curve_preset", "curve_preset_amplitude", "curve_preset_cycles",
    "curve_preset_phase", "curve_preset_points",
    "curve_control_mode", "curve_length_mode", "curve_mode",
    "curve_boundary_mode", "curve_closed",
    "curve_range_start", "curve_range_end",
    "curve_preserve_volume", "curve_resolution",
    "show_curve_mapping_settings", "show_curve_preset_settings",
    "show_curve_edit_settings", "show_curve_cross_section_settings",
    "factor", "direction", "size", "mode",
    "origin", "alignment", "preserve_volume",
    "influence_weight", "influence_vertex_group", "auto_reconnect",
    "auto_sync_upstream",
    "sync_shared_end_scale", "show_cage",
    "show_other_cages",
    "show_axis_gizmo", "show_direction_handle", "show_ffd_handles",
    "show_numeric_controls", "show_cage_controls", "show_deform_axis",
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
            value = (
                curve_control_mode_identifier(source)
                if name == "curve_control_mode" else getattr(source, name))
            if isinstance(value, set):
                value = set(value)
            elif hasattr(value, "__len__") and not isinstance(value, str):
                value = tuple(value)
            setattr(destination, name, value)
        if hasattr(destination, "ffd_points") and hasattr(source, "ffd_points"):
            destination.ffd_points.clear()
            for source_point in source.ffd_points:
                point = destination.ffd_points.add()
                point.name = source_point.name
                point.offset = tuple(source_point.offset)
                point.influence = min(max(float(
                    getattr(source_point, "influence", 1.0)), 0.0), 1.0)
                point.selected = bool(source_point.selected)
            ensure_ffd_point_collection(destination)
        if (
                hasattr(destination, "curve_points") and
                hasattr(source, "curve_points")
        ):
            destination.curve_points.clear()
            for source_point in source.curve_points:
                point = destination.curve_points.add()
                point.name = source_point.name
                point.selected = bool(source_point.selected)
                point.handles_linked = bool(source_point.handles_linked)
                point.bevel = float(source_point.bevel)
                point.tension = float(source_point.tension)
        if (
                hasattr(destination, "curve_stations") and
                hasattr(source, "curve_stations")
        ):
            destination.curve_stations.clear()
            for source_station in source.curve_stations:
                station = destination.curve_stations.add()
                station.name = source_station.name
                station.factor = float(source_station.factor)
                station.scale = tuple(source_station.scale)
                station.offset = tuple(source_station.offset)
                station.radius = float(source_station.radius)
                station.twist = float(source_station.twist)
                station.selected = bool(source_station.selected)
        destination_controller.location = source_controller.location
        # Convert the source orientation through its matrix so a source Empty
        # using Quaternion/Axis Angle mode is copied correctly into the stable
        # XYZ mode used by generated controllers.
        source_rotation = _controller_rotation_xyz(source_controller)
        try:
            destination_controller.rotation_mode = "XYZ"
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        destination_controller.rotation_euler = source_rotation
        destination_controller.scale = source_controller.scale
    finally:
        _SYNCING.discard(pointer)
    sync_controller(destination_controller, pull_transform=False)


def _restore_controller_from_modifier(controller, modifier):
    properties = controller.sdh_cage_deform
    deform_types = {value: key for key, value in DEFORM_VALUES.items()}
    modes = {value: key for key, value in MODE_VALUES.items()}
    origins = {value: key for key, value in ORIGIN_VALUES.items()}
    curve_lengths = {value: key for key, value in CURVE_LENGTH_VALUES.items()}
    curve_boundaries = {
        value: key for key, value in CURVE_BOUNDARY_VALUES.items()}
    curve_modes = {value: key for key, value in CURVE_MODE_VALUES.items()}
    pointer = _pointer(controller)
    _SYNCING.add(pointer)
    try:
        try:
            controller.rotation_mode = "XYZ"
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        controller.location = tuple(modifier_input(modifier, "Center", (0.0, 0.0, 0.0)))
        controller.rotation_euler = tuple(
            modifier_input(modifier, "Rotation", (0.0, 0.0, 0.0)))
        properties.size = tuple(modifier_input(modifier, "Size", (1.0, 1.0, 1.0)))
        controller.scale = tuple(max(value, EPSILON) * 0.5 for value in properties.size)
        legacy_strength = float(modifier_input(modifier, "Strength", 0.0))
        legacy_factor = float(modifier_input(modifier, "Factor", 0.0))
        legacy_direction = float(modifier_input(modifier, "Direction", 0.0))
        properties.strength = legacy_strength
        properties.factor = legacy_factor
        properties.direction = legacy_direction
        properties.deform_type = deform_types.get(
            int(modifier_input(modifier, "Deform Type", 0)), "BEND")
        restored_active = deform_types_from_mask(modifier_input(
            modifier, "Deform Types", DEFORM_BITS[properties.deform_type]))
        if restored_active:
            properties.deform_types = restored_active
            properties.muted_deform_types = set()
        else:
            properties.deform_types = {properties.deform_type}
            properties.muted_deform_types = {properties.deform_type}
        restored_order = deform_order_from_signature(
            modifier.node_group.get(DEFORM_ORDER_SIGNATURE, ""),
            properties.deform_types,
            properties.deform_type,
        )
        properties.deform_order = encode_deform_order(
            restored_order, properties.deform_types, properties.deform_type)
        properties.active_deform_layer = 0
        properties.stage_enabled = bool(
            modifier_input(modifier, "Stage Enabled", True))
        properties.influence_weight = float(modifier_input(
            modifier, "Influence Weight", 1.0))
        properties.bend_strength = float(modifier_input(
            modifier, "Bend Angle", legacy_strength))
        properties.bend_direction = float(modifier_input(
            modifier, "Bend Direction", legacy_direction))
        properties.twist_strength = float(modifier_input(
            modifier, "Twist Angle", legacy_strength))
        properties.taper_factor = float(modifier_input(
            modifier, "Taper Factor", legacy_factor))
        properties.stretch_factor = float(modifier_input(
            modifier, "Stretch Factor", legacy_factor))
        shear_input = tuple(modifier_input(
            modifier, "Shear", (0.0, 0.0, 0.0)))
        properties.shear_factors = (
            float(shear_input[0]), float(shear_input[2]))
        properties.ffd_offsets = tuple(
            float(component)
            for socket_name in FFD_SOCKET_NAMES
            for component in tuple(modifier_input(
                modifier, socket_name, (0.0, 0.0, 0.0)))[:3]
        )
        properties.mode = modes.get(int(modifier_input(modifier, "Mode", 0)), "LIMITED")
        properties.origin = origins.get(int(modifier_input(modifier, "Origin", 0)), "BOTTOM")
        properties.curve_length_mode = curve_lengths.get(int(modifier_input(
            modifier, "Curve Length Mode",
            CURVE_LENGTH_VALUES["STRETCH"])), "STRETCH")
        properties.curve_control_mode = (
            "CAGE" if properties.curve_length_mode == "PRESERVE" else "CURVE")
        curve_mode_value = int(modifier_input(
            modifier, "Curve Boundary Mode",
            CURVE_MODE_VALUES["LIMITED"]))
        properties.curve_mode = curve_modes.get(curve_mode_value, "LIMITED")
        properties.curve_boundary_mode = curve_boundaries.get(
            curve_mode_value,
            CURVE_MODE_BOUNDARY[properties.curve_mode])
        properties.curve_preserve_volume = bool(modifier_input(
            modifier, "Curve Preserve Volume", False))
        properties.curve_closed = bool(modifier_input(
            modifier, "Curve Closed", False))
        properties.curve_range_start = float(modifier_input(
            modifier, "Curve Range Start", 0.0))
        properties.curve_range_end = float(modifier_input(
            modifier, "Curve Range End", 1.0))
        properties.curve_global_radius = float(modifier_input(
            modifier, "Curve Global Radius", 1.0))
        properties.curve_global_twist = float(modifier_input(
            modifier, "Curve Global Twist", 0.0))
        properties.curve_relative_binding = bool(modifier_input(
            modifier, "Curve Relative Binding", False))
        stored_cage_type = str(
            getattr(modifier, "node_group", {}).get(
                CAGE_TYPE_MARKER, "STANDARD") or "STANDARD")
        if stored_cage_type in CAGE_TYPES:
            properties.cage_type = stored_cage_type
        properties.preserve_volume = bool(
            modifier_input(modifier, "Preserve Volume", True))
        stored_scales = _stored_authored_end_scales(modifier)
        if stored_scales is None:
            top_input = tuple(modifier_input(
                modifier, "Top Scale", (1.0, 1.0, 1.0)))
            bottom_input = tuple(modifier_input(
                modifier, "Bottom Scale", (1.0, 1.0, 1.0)))
            top_scale = (top_input[0], top_input[2])
            bottom_scale = (bottom_input[0], bottom_input[2])
        else:
            top_scale, bottom_scale = stored_scales
        top_offset = tuple(modifier_input(modifier, "Top Offset", (0.0, 0.0, 0.0)))
        bottom_offset = tuple(modifier_input(
            modifier, "Bottom Offset", (0.0, 0.0, 0.0)))
        properties.top_scale = top_scale
        properties.bottom_scale = bottom_scale
        properties.top_offset = (top_offset[0], top_offset[2])
        properties.bottom_offset = (bottom_offset[0], bottom_offset[2])
    finally:
        _SYNCING.discard(pointer)
    sync_controller(controller, pull_transform=False)


def _id_write_is_restricted(error):
    message = str(error).casefold()
    return "writing to id classes" in message and "not allowed" in message


def target_ownership_repair_pending(target):
    pointer = _pointer(target)
    return bool(pointer and pointer in _TARGET_OWNERSHIP_REPAIR_QUEUE)


def request_target_ownership_repair(target):
    """Defer copied-target writes requested from a read-only UI context."""
    pointer = _pointer(target)
    if not pointer or is_cage_controller(target):
        return False
    _TARGET_OWNERSHIP_REPAIR_QUEUE[pointer] = target
    try:
        if not bpy.app.timers.is_registered(_controller_timer):
            bpy.app.timers.register(_controller_timer, first_interval=0.0)
    except (AttributeError, RuntimeError, ValueError):
        return False
    return True


def _drain_target_ownership_repairs():
    """Repair queued copied cages after Blender leaves Panel.draw()."""
    if not _TARGET_OWNERSHIP_REPAIR_QUEUE:
        return 0
    pending = tuple(_TARGET_OWNERSHIP_REPAIR_QUEUE.items())
    _TARGET_OWNERSHIP_REPAIR_QUEUE.clear()
    keep = {}
    repaired = 0
    for pointer, target in pending:
        if not pointer or _pointer(target) != pointer:
            continue
        try:
            _TARGET_OWNERSHIP_REPAIRING.add(pointer)
            if ensure_target_stage_ownership(
                    bpy.context, target, defer_restricted=False):
                repaired += 1
        except (AttributeError, ReferenceError, RuntimeError, TypeError) as error:
            if _id_write_is_restricted(error):
                keep[pointer] = target
        finally:
            _TARGET_OWNERSHIP_REPAIRING.discard(pointer)
    _TARGET_OWNERSHIP_REPAIR_QUEUE.update(keep)
    if repaired:
        refresh_controller_display(bpy.context, force=True)
        _tag_view3d_redraw()
    return repaired


def ensure_target_stage_ownership(
        context, target, *, defer_restricted=True):
    """Detach copied cage stages from their source object's UUID ownership."""
    if target is None or is_cage_controller(target):
        return False
    target_uuid = str(target.get(TARGET_UUID, ""))
    data_objects = _data_objects_snapshot()
    conflicts = tuple(
        obj for obj in data_objects
        if obj != target and not is_cage_controller(obj) and
        target_uuid and str(obj.get(TARGET_UUID, "")) == target_uuid
    )
    if not conflicts:
        return False

    stages = cage_modifiers(target)
    # A copied target inherits the UUID and node groups, but an ordinary
    # object-only duplicate does not inherit the managed controller objects.
    # Preserve the object that still owns a complete parented controller set;
    # detach the copy when it is resolved instead. Without this distinction,
    # merely selecting the source after duplication can reassign the source
    # and make both stacks appear to swap ownership.
    owned_controller_uuids = {
        str(obj.get(MODIFIER_UUID, ""))
        for obj in data_objects
        if (is_cage_controller(obj) and obj.parent == target and
            str(obj.get(TARGET_UUID, "")) == target_uuid)
    }
    if stages and all(
            cage_modifier_uuid(modifier) in owned_controller_uuids
            for modifier in stages):
        return False

    # A duplicate made with the target and its controller empties selected can
    # carry a complete, correctly-parented controller set.  Matching ownership
    # therefore does not prove that this is the original target.  Detach the
    # target currently entering the resolver; the other object keeps the old
    # UUID and is isolated on its next access if necessary.

    source_controllers = tuple(find_controller(target, modifier) for modifier in stages)
    new_target_uuid = str(uuid.uuid4())
    try:
        target[TARGET_UUID] = new_target_uuid
    except (AttributeError, RuntimeError) as error:
        if defer_restricted and _id_write_is_restricted(error):
            request_target_ownership_repair(target)
            return False
        raise
    for modifier, source_controller in zip(stages, source_controllers):
        source_curve_guide = None
        if (
                source_controller is not None and
                str(getattr(
                    source_controller.sdh_cage_deform,
                    "cage_type", "STANDARD")) == "CURVE"
        ):
            try:
                from .curve import curve_guide_object
                source_target = getattr(source_controller, "parent", None)
                source_curve_guide = curve_guide_object(
                    source_target, modifier)
            except (AttributeError, ImportError, ReferenceError, RuntimeError,
                    TypeError, ValueError):
                source_curve_guide = None
        old_group = modifier.node_group
        new_group = old_group.copy()
        new_group.name = f"{STAGE_GROUP_NAME_PREFIX}{str(uuid.uuid4())[:8]}"
        new_group[MODIFIER_MARKER] = True
        new_group[MODIFIER_UUID] = str(uuid.uuid4())
        modifier.node_group = new_group

        if source_controller is not None and source_controller.parent == target:
            new_controller = source_controller
            new_controller[TARGET_UUID] = new_target_uuid
            new_controller[MODIFIER_UUID] = cage_modifier_uuid(modifier)
        else:
            new_controller = _new_controller(context, target, modifier)
        if source_controller is not None:
            _copy_controller_state(new_controller, source_controller)
        else:
            _restore_controller_from_modifier(new_controller, modifier)
        if source_curve_guide is not None:
            try:
                from .curve import copy_curve_guide_state
                copy_curve_guide_state(
                    source_curve_guide, target, modifier, new_controller)
            except (AttributeError, ImportError, ReferenceError, RuntimeError,
                    TypeError, ValueError):
                pass
    # Node groups carry chain metadata too.  Ownership migration above gives
    # the duplicate fresh target/modifier UUIDs; remap the copied chain UUIDs
    # so the source and duplicate cannot reconnect one another's stages.
    try:
        from .chain import remap_target_chains
        remap_target_chains(target)
    except (ImportError, AttributeError, ReferenceError, RuntimeError):
        pass
    return True


def prepare_target_for_cage(context, target):
    """Prepare object types that Blender cannot modify with Geometry Nodes.

    Curve and text objects accept a Geometry Nodes modifier directly.  Blender
    does not expose a modifier stack for Surface objects, so convert that
    object in place when the user explicitly adds a cage.  The source type is
    recorded for diagnostics and the operation remains undoable through the
    normal Blender operator transaction.
    """
    if target is None or getattr(target, "type", None) != "SURFACE":
        return target
    try:
        _activate(context, target)
        result = bpy.ops.object.convert(target="MESH", keep_original=False)
    except (AttributeError, RuntimeError, TypeError) as error:
        raise RuntimeError(
            iface_("The selected surface could not be converted for cage deformation")
        ) from error
    if "FINISHED" not in result or getattr(target, "type", None) != "MESH":
        raise RuntimeError(
            iface_("Surface cage deformation requires a mesh conversion")
        )
    try:
        target[TARGET_CONVERTED_SOURCE_TYPE] = "SURFACE"
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    return target


def remove_orphan_cage_controllers(target):
    """Remove owned controllers whose managed modifier was deleted directly."""
    if target is None:
        return 0
    live_modifier_uuids = {
        cage_modifier_uuid(modifier) for modifier in cage_modifiers(target)
    }
    removed_curve_helpers = 0
    try:
        from .curve import remove_orphan_curve_companions
        removed_curve_helpers = remove_orphan_curve_companions(
            target, live_modifier_uuids)
    except (AttributeError, ImportError, ReferenceError, RuntimeError,
            TypeError, ValueError):
        pass
    orphans = tuple(
        obj for obj in bpy.data.objects
        if is_cage_controller(obj) and obj.parent == target and
        str(obj.get(MODIFIER_UUID, "")) not in live_modifier_uuids
    )
    affected_chains = {}
    for controller in orphans:
        try:
            chain_uuid = str(controller.get(CHAIN_UUID_PROP, "") or "")
            chain_mode = str(controller.get(CHAIN_MODE_PROP, "") or "")
        except (AttributeError, ReferenceError, TypeError):
            continue
        if chain_uuid:
            affected_chains[chain_uuid] = chain_mode
    for controller in orphans:
        bpy.data.objects.remove(controller, do_unlink=True)
    if affected_chains:
        try:
            from .chain import compact_chain, reconnect_chain
            for chain_uuid, chain_mode in affected_chains.items():
                live_chain = compact_chain(target, chain_uuid)
                if len(live_chain) >= 2 and chain_mode in {"CHAINED", "CONNECTED"}:
                    reconnect_chain(target, chain_uuid)
        except (ImportError, AttributeError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            pass
    for node_group in tuple(bpy.data.node_groups):
        if node_group.users == 0 and node_group.get(MODIFIER_MARKER, False):
            bpy.data.node_groups.remove(node_group)
    if orphans or removed_curve_helpers:
        remove_unused_control_collections()
    return len(orphans)


def _remove_orphan_helper_object(obj, curve_module=None):
    """Remove one owned helper and its now-unused data block."""
    if obj is None:
        return False
    try:
        if curve_module is not None and curve_module.is_curve_helper(obj):
            return bool(curve_module._remove_curve_helper_object(obj))
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass

    data = getattr(obj, "data", None)
    parent = getattr(obj, "parent", None)
    try:
        if bool(obj.get(FFD_LATTICE_MARKER, False)) and parent is not None:
            for modifier in tuple(getattr(parent, "modifiers", ())):
                if (
                        getattr(modifier, "type", None) == "LATTICE" and
                        getattr(modifier, "object", None) == obj
                ):
                    parent.modifiers.remove(modifier)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except (ReferenceError, RuntimeError):
        return False
    if data is None or getattr(data, "users", 1) != 0:
        return True
    try:
        if isinstance(data, bpy.types.Lattice):
            bpy.data.lattices.remove(data)
        elif isinstance(data, bpy.types.Curve):
            bpy.data.curves.remove(data)
        elif isinstance(data, bpy.types.Mesh):
            bpy.data.meshes.remove(data)
    except (ReferenceError, RuntimeError, TypeError):
        pass
    return True


def cleanup_orphan_deform_helpers():
    """Remove helpers whose target or owning deformation stage no longer exists."""
    objects = _data_objects_snapshot()
    if not objects:
        return 0
    try:
        from . import curve as curve_module
    except ImportError:
        curve_module = None

    legacy_owners = {}
    for obj in objects:
        try:
            owner_uuid = str(obj.get(PublicData.G_OBJECT_UUID_PROP, ""))
            if owner_uuid and not obj.get(PublicData.G_OWNER_PROP, False):
                legacy_owners.setdefault(owner_uuid, []).append(obj)
        except (AttributeError, ReferenceError, TypeError):
            continue

    orphans = []
    for obj in objects:
        try:
            parent = getattr(obj, "parent", None)
            if is_cage_controller(obj):
                modifier_uuid = str(obj.get(MODIFIER_UUID, ""))
                if (
                        parent is None or not modifier_uuid or
                        find_modifier(parent, modifier_uuid=modifier_uuid) is None
                ):
                    orphans.append(obj)
                continue

            if bool(obj.get(FFD_NATIVE_EDIT_PROXY_MARKER, False)):
                # Keep the proxy only while its owning stage explicitly has
                # a live native-edit session. Stale proxies loaded from a
                # saved file have the flag reset and remain cleanup targets.
                modifier_uuid = str(obj.get(
                    FFD_LATTICE_MODIFIER_MARKER, ""))
                modifier = (
                    find_modifier(parent, modifier_uuid=modifier_uuid)
                    if parent is not None and modifier_uuid else None)
                controller = (
                    find_controller(parent, modifier)
                    if modifier is not None else None)
                properties = getattr(controller, "sdh_cage_deform", None)
                if bool(getattr(
                        properties, "ffd_native_edit_mode_active", False)):
                    continue
                orphans.append(obj)
                continue

            if bool(obj.get(FFD_LATTICE_MARKER, False)):
                modifier_uuid = str(obj.get(FFD_LATTICE_MODIFIER_MARKER, ""))
                if (
                        parent is None or not modifier_uuid or
                        find_modifier(parent, modifier_uuid=modifier_uuid) is None
                ):
                    orphans.append(obj)
                continue

            if curve_module is not None and curve_module.is_curve_helper(obj):
                modifier_uuid = str(obj.get(
                    curve_module.CURVE_HELPER_MODIFIER_UUID, ""))
                if (
                        parent is None or not modifier_uuid or
                        find_modifier(parent, modifier_uuid=modifier_uuid) is None
                ):
                    orphans.append(obj)
                continue

            if not GizmoUtils.is_managed_origin(obj):
                continue
            owner_uuid = str(obj.get(PublicData.G_OWNER_UUID_PROP, ""))
            owners = legacy_owners.get(owner_uuid, ())
            in_use = any(
                modifier.type == "SIMPLE_DEFORM" and
                getattr(modifier, "origin", None) == obj
                for owner in owners
                for modifier in getattr(owner, "modifiers", ())
            )
            if not owner_uuid or not in_use:
                orphans.append(obj)
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            continue

    removed = sum(
        int(_remove_orphan_helper_object(obj, curve_module))
        for obj in dict.fromkeys(orphans)
    )
    for node_group in tuple(getattr(bpy.data, "node_groups", ())):
        try:
            if node_group.users == 0 and node_group.get(MODIFIER_MARKER, False):
                bpy.data.node_groups.remove(node_group)
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            continue
    if removed:
        remove_unused_control_collections()
    return removed


def _cleanup_orphans_after_object_count_change(*, force=False):
    """Run the global orphan pass only after scene object membership changes."""
    global _ORPHAN_HELPER_OBJECT_COUNT, _ORPHAN_HELPER_CLEANUP_RUNNING
    if _ORPHAN_HELPER_CLEANUP_RUNNING:
        return False
    try:
        current_count = len(bpy.data.objects)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return False
    if not force and current_count == _ORPHAN_HELPER_OBJECT_COUNT:
        return False
    _ORPHAN_HELPER_CLEANUP_RUNNING = True
    try:
        cleanup_orphan_deform_helpers()
        try:
            _ORPHAN_HELPER_OBJECT_COUNT = len(bpy.data.objects)
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            _ORPHAN_HELPER_OBJECT_COUNT = current_count
    finally:
        _ORPHAN_HELPER_CLEANUP_RUNNING = False
    return True


def _runtime_has_managed_deformation():
    """Return whether any live cage or managed traditional Origin remains."""
    objects = _data_objects_snapshot()
    for obj in objects:
        try:
            if is_cage_controller(obj):
                target = find_target(obj)
                if target is not None and find_modifier(target, obj) is not None:
                    return True
            elif GizmoUtils.is_managed_origin(obj):
                owner_uuid = str(obj.get(PublicData.G_OWNER_UUID_PROP, ""))
                if not owner_uuid:
                    continue
                for owner in objects:
                    if str(owner.get(PublicData.G_OBJECT_UUID_PROP, "")) != owner_uuid:
                        continue
                    if any(
                            modifier.type == "SIMPLE_DEFORM" and
                            getattr(modifier, "origin", None) == obj
                            for modifier in getattr(owner, "modifiers", ())):
                        return True
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            continue
    return False


def refresh_runtime_handler_state():
    """Enable runtime callbacks only while a managed deformation needs them."""
    _cleanup_orphans_after_object_count_change(force=True)
    if _runtime_has_managed_deformation():
        enable_runtime_handlers()
        return True
    disable_runtime_handlers()
    return False


def create_deform_stage(context, target, *, name="Cage Deform", after_modifier=None,
                        show_other_default=True, node_group_template=None,
                        skip_stage_maintenance=False, fit_stage=True,
                        cage_type="STANDARD", initial_deform_type="BEND"):
    # A panel action can create another stage while the persistent FFD editor
    # still owns the viewport. End that session first so the new stage receives
    # the click and no stale box-selection handler survives the stack change.
    finish_ffd_edit_sessions(context, restore_target=False)
    try:
        from .curve import finish_curve_edit_sessions
        finish_curve_edit_sessions(context, restore_target=False)
    except (ImportError, ReferenceError, RuntimeError):
        pass
    target = prepare_target_for_cage(context, target)
    if not skip_stage_maintenance:
        ensure_target_stage_ownership(context, target)
        ensure_unique_target_uuid(target)
        remove_orphan_cage_controllers(target)
    node_group = create_stage_node_group(node_group_template)
    modifier = target.modifiers.new(name=name, type="NODES")
    modifier.node_group = node_group
    controller = _new_controller(context, target, modifier)
    had_show_other_preference = _target_has_show_other_cages(target)
    show_other = _target_show_other_cages(target, show_other_default)
    if not had_show_other_preference:
        _sync_target_show_other_cages(target, show_other)
    properties = getattr(controller, "sdh_cage_deform", None)
    pointer = _pointer(controller)
    if properties is not None:
        properties.alignment = "POS_Z"
    if properties is not None and bool(properties.show_other_cages) != show_other:
        if pointer:
            _CONTROLLER_DISPLAY_GUARD.add(pointer)
        try:
            properties.show_other_cages = show_other
        finally:
            if pointer:
                _CONTROLLER_DISPLAY_GUARD.discard(pointer)

    # Configure dedicated cage types before fitting. This makes the first
    # evaluation use the same operation the user requested, and avoids a
    # transient Standard/Bend frame being mistaken for the cage's input shape.
    requested_cage_type = str(cage_type or "STANDARD").upper()
    requested_initial_type = str(initial_deform_type or "BEND").upper()
    if properties is not None and requested_cage_type in CAGE_TYPES:
        if requested_cage_type == "STANDARD":
            if requested_initial_type not in STANDARD_DEFORM_ORDER:
                requested_initial_type = "BEND"
            set_deform_layers(properties, (requested_initial_type,), context)
            try:
                properties.expanded_deform_layers = {requested_initial_type}
            except (AttributeError, TypeError, ValueError):
                pass
        else:
            properties.cage_type = requested_cage_type
            set_deform_layers(
                properties,
                (CAGE_TYPE_DEFORM[requested_cage_type],),
                context,
            )

    previous_active = target.modifiers.active
    target.modifiers.active = modifier
    if after_modifier is not None and after_modifier in target.modifiers[:]:
        desired_index = tuple(target.modifiers).index(after_modifier) + 1
        _activate(context, target)
        try:
            bpy.ops.object.modifier_move_to_index(modifier=modifier.name, index=desired_index)
        except RuntimeError:
            pass
    # Inserting after an FFD owner can temporarily split its native Lattice
    # companion from the Geometry Nodes stage. Repair all pairs in one pass.
    ensure_ffd_companion_order(target)
    if properties is not None and hasattr(properties, "auto_sync_upstream"):
        try:
            default_auto_sync = bool(
                getattr(get_pref(), "default_cage_auto_sync", False))
        except (AttributeError, KeyError, ReferenceError, RuntimeError, TypeError):
            default_auto_sync = False
        if pointer:
            _SYNCING.add(pointer)
        try:
            properties.auto_sync_upstream = default_auto_sync
        finally:
            if pointer:
                _SYNCING.discard(pointer)
    if fit_stage:
        fit_controller(context, target, modifier, controller)
    if properties is not None and requested_cage_type == "CURVE":
        try:
            from .curve import ensure_curve_companions
            ensure_curve_companions(
                target, modifier, controller, reset_guide=True)
            sync_controller(controller, pull_transform=False, sync_mode="push")
        except (AttributeError, ImportError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            pass
    target.modifiers.active = modifier
    enable_runtime_handlers()
    return modifier, controller, previous_active


def cage_stage_insertion_anchor(target, active=None):
    """Choose where a newly-created cage stage should be inserted.

    The preference defaults to the end of the modifier stack. Keeping the
    lookup here lets the independent and chained creation operators share the
    same behavior while still falling back safely during registration or in a
    file created before the preference entry existed.
    """
    try:
        append_to_end = bool(get_pref().append_cage_stage_to_end)
    except (AttributeError, KeyError, ReferenceError, RuntimeError, TypeError):
        append_to_end = True
    if not append_to_end:
        return active
    modifiers = tuple(getattr(target, "modifiers", ())) if target else ()
    return modifiers[-1] if modifiers else None


def legacy_target_from_context(context):
    """Return a selected object accepted by the traditional Simple Deform path."""
    selected = _selected_context_object(context)
    if selected is None:
        return None
    if selected.type in (*SUPPORTED_TYPES, "LATTICE"):
        return selected
    return None


def deform_stack_target_from_context(context):
    """Resolve a target for the unified cage and traditional modifier list."""
    return target_from_context(context) or legacy_target_from_context(context)


def _selected_supported_cage_targets(context):
    """Return directly selected objects that can own independent cages."""
    try:
        selected = tuple(context.selected_objects)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return ()
    return tuple(
        obj for obj in selected
        if obj is not None and getattr(obj, "type", None) in SUPPORTED_TYPES
    )


def _create_cage_stage_for_target(
        context, target, cage_type, initial_deform_type="BEND"):
    active = target.modifiers.active
    insertion_anchor = cage_stage_insertion_anchor(target, active)
    modifier, controller, _previous = create_deform_stage(
        context,
        target,
        after_modifier=insertion_anchor,
        cage_type=cage_type,
        initial_deform_type=initial_deform_type,
    )
    target.modifiers.active = modifier
    return modifier, controller


def _activate_created_cage_stage(context, target, controller, cage_type):
    """Finish cage creation with a selection stable across deferred sync."""
    cage_type = str(cage_type).upper()
    if cage_type in {"FFD", "CURVE"}:
        # Activating a Workspace Tool can rebuild Blender's Gizmo map and
        # briefly touch selection. Set the dedicated tool first, then leave the
        # controlled object active with its controller(s) selected for the
        # Timeline. The deferred selection watcher now derives the same cage
        # type and cannot restore the native tool before the first blank drag.
        activate_cage_workspace_tool(context, cage_type)
        _activate(context, target)
        refresh_controller_display(context, force=True)
        _selection_sync_notify()
        return
    _activate(context, controller)
    refresh_controller_display(context)
    activate_cage_workspace_tool(context, cage_type)


class SDH_OT_add_cage_deform(Operator):
    bl_idname = "sdh.add_cage_deform"
    bl_label = "Add Standard Cage"
    bl_description = "Add an independent Standard layered cage"
    bl_options = {"REGISTER", "UNDO"}

    cage_type: EnumProperty(
        name="Cage Type",
        items=(
            ("STANDARD", "Standard Type", "Create a layered deformation cage"),
            ("SHEAR", "Shear Cage", "Create a dedicated shear cage"),
            ("FFD", "FFD Cage", "Create a dedicated free-form cage"),
            ("CURVE", "Curve Cage", "Create a Bezier-guided curve cage"),
        ),
        default="STANDARD",
    )

    initial_deform_type: EnumProperty(
        name="Initial Deformation",
        items=(
            ("BEND", "Bend", "Create the Standard cage with a Bend layer"),
            ("TWIST", "Twist", "Create the Standard cage with a Twist layer"),
            ("TAPER", "Taper", "Create the Standard cage with a Taper layer"),
            ("STRETCH", "Stretch", "Create the Standard cage with a Stretch layer"),
            ("SHEAR", "Shear", "Create the Standard cage with a Shear layer"),
        ),
        default="BEND",
        options={"HIDDEN", "SKIP_SAVE"},
    )

    individual_objects: BoolProperty(
        default=False,
        options={"HIDDEN", "SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        if _selected_supported_cage_targets(context):
            return True
        if (
                getattr(context, "mode", "OBJECT") == "OBJECT" and
                target_from_context(context) is not None
        ):
            return True
        try:
            from .merge import eligible_selected_sources
            return (
                getattr(context, "mode", "OBJECT") == "OBJECT" and
                len(eligible_selected_sources(context)) >= 2
            )
        except (ImportError, ReferenceError, RuntimeError, TypeError):
            return False

    @classmethod
    def description(cls, _context, properties):
        base = iface_({
            "SHEAR": "Add an independent Shear cage",
            "FFD": "Add an independent FFD cage",
        }.get(
            str(getattr(properties, "cage_type", "STANDARD")),
            "Add an independent Standard layered cage",
        ))
        multi = iface_(
            "With multiple objects, click creates one merged cage; "
            "Ctrl-click creates a separate cage for each object"
        )
        return f"{base}\n{multi}"

    def invoke(self, context, event):
        self.individual_objects = bool(event.ctrl)
        return self.execute(context)

    def execute(self, context):
        selected_targets = _selected_supported_cage_targets(context)
        if self.individual_objects and len(selected_targets) > 1:
            active_target = getattr(context.view_layer.objects, "active", None)
            preferred_target = (
                active_target if active_target in selected_targets
                else selected_targets[0]
            )
            created = []
            failures = []
            for target in selected_targets:
                try:
                    modifier, controller = _create_cage_stage_for_target(
                        context,
                        target,
                        self.cage_type,
                        self.initial_deform_type,
                    )
                except RuntimeError as error:
                    failures.append((target, error))
                    continue
                created.append((target, modifier, controller))
            if not created:
                message = str(failures[0][1]) if failures else iface_(
                    "No selected objects support separate cage stages")
                self.report({"ERROR"}, message)
                return {"CANCELLED"}
            preferred = next(
                (item for item in created if item[0] == preferred_target),
                created[0],
            )
            _activate_created_cage_stage(
                context, preferred[0], preferred[2], self.cage_type)
            skipped = len(selected_targets) - len(created)
            if skipped:
                self.report(
                    {"WARNING"},
                    iface_(
                        "Added {count} separate cage stages; skipped "
                        "{skipped} selected objects"
                    ).format(count=len(created), skipped=skipped),
                )
            else:
                self.report(
                    {"INFO"},
                    iface_("Added {count} separate cage stages").format(
                        count=len(created)),
                )
            return {"FINISHED"}

        merge_target = None
        try:
            if not self.individual_objects:
                from .merge import create_deform_merge, eligible_selected_sources
                merge_sources = eligible_selected_sources(context)
                if len(merge_sources) >= 2:
                    merge_target = create_deform_merge(context, merge_sources)
            target = merge_target or target_from_context(context)
            if target is None and len(selected_targets) == 1:
                target = selected_targets[0]
            if target is None:
                return {"CANCELLED"}
            modifier, controller = _create_cage_stage_for_target(
                context,
                target,
                self.cage_type,
                self.initial_deform_type,
            )
        except RuntimeError as error:
            if merge_target is not None:
                try:
                    from .merge import release_deform_merge
                    release_deform_merge(context, merge_target)
                except (ImportError, ReferenceError, RuntimeError, TypeError):
                    pass
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        _activate_created_cage_stage(
            context, target, controller, self.cage_type)
        self.report({"INFO"}, iface_({
            "SHEAR": "Added Shear Cage stage",
            "FFD": "Added FFD Cage stage",
            "CURVE": "Added Curve Cage stage",
        }.get(self.cage_type, "Added Standard Cage stage")))
        return {"FINISHED"}


class SDH_OT_add_legacy_simple_deform(Operator):
    bl_idname = "sdh.add_legacy_simple_deform"
    bl_label = "Add Simple Deform (Legacy)"
    bl_description = "Add a traditional Simple Deform modifier"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(legacy_target_from_context(context))

    def execute(self, context):
        target = legacy_target_from_context(context)
        if target is None:
            return {"CANCELLED"}
        try:
            target = prepare_target_for_cage(context, target)
            modifier = target.modifiers.new(
                name="Simple Deform", type="SIMPLE_DEFORM")
            # The assistant's traditional workflow starts neutral, bends on
            # local +Y, and pivots from the lower limit. This matches the
            # default viewport controls instead of Blender's native Twist
            # default, while remaining non-destructive at creation time.
            modifier.deform_method = "BEND"
            modifier.deform_axis = "Y"
            modifier.angle = 0.0
            modifier.factor = 0.0
            modifier.show_viewport = True
            modifier.show_render = True
            target.modifiers.active = modifier
            _activate(context, target)
            target.SimpleDeformGizmo_PropertyGroup.origin_mode = "DOWN_LIMITS"
            helper = GizmoUtils()
            origin = helper.new_origin_empty_object(force_managed=True)
            if origin is None:
                raise RuntimeError(iface_(
                    "Could not create the managed lower-limit Origin"))
            origin.SimpleDeformGizmo_PropertyGroup.origin_mode = "DOWN_LIMITS"
            helper.clear_point_cache()
            helper.update_object_origin_matrix()
        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        refresh_runtime_handler_state()
        try:
            context.view_layer.update()
            preferences = get_pref()
            if (
                    preferences is not None and
                    not preferences.update_deform_wireframe
            ):
                # The property callback performs the first cache/preview build.
                # Do not immediately repeat that expensive work below.
                preferences.update_deform_wireframe = True
            else:
                helper = GizmoUtils()
                helper.update_multiple_modifiers_data()
                helper.update_deform_wireframe(force=True)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        if context.area:
            context.area.tag_redraw()
        self.report({"INFO"}, iface_("Added legacy Simple Deform modifier"))
        return {"FINISHED"}


class SDH_OT_add_cage_topology(Operator):
    bl_idname = "sdh.add_cage_topology"
    bl_label = "Add Subdivision Before Deform"
    bl_description = (
        "Add a Subdivision Surface modifier before the active deformation "
        "stage so bending has enough segments"
    )
    bl_options = {"REGISTER", "UNDO"}

    subdivision_type: EnumProperty(
        name="Type",
        items=(
            (
                "SIMPLE", "Simple",
                "Add straight loop cuts without smoothing",
            ),
            (
                "CATMULL_CLARK", "Catmull-Clark",
                "Smooth while subdividing",
            ),
        ),
        default="SIMPLE",
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        target = deform_stack_target_from_context(context)
        active = getattr(getattr(target, "modifiers", None), "active", None)
        return bool(
            target is not None and target.type == "MESH" and
            active in deform_stack_modifiers(target))

    def execute(self, context):
        target = deform_stack_target_from_context(context)
        active = getattr(getattr(target, "modifiers", None), "active", None)
        if target is None or active not in deform_stack_modifiers(target):
            return {"CANCELLED"}
        try:
            stage_index = tuple(target.modifiers).index(active)
        except (TypeError, ValueError):
            stage_index = -1
        subdivision = target.modifiers.new("Deform Topology", "SUBSURF")
        subdivision.subdivision_type = self.subdivision_type
        subdivision.levels = 2
        subdivision.render_levels = 2
        _activate(context, target)
        moved = True
        if stage_index >= 0:
            try:
                bpy.ops.object.modifier_move_to_index(
                    modifier=subdivision.name, index=stage_index)
            except RuntimeError:
                moved = False
        if not moved:
            self.report(
                {"WARNING"},
                iface_(
                    "Subdivision was added at the end; move it before the "
                    "deformation stage"),
            )
        target.modifiers.active = active
        ensure_ffd_companion_order(target)
        if active.type == "SIMPLE_DEFORM":
            StageCache.rebuild(context, target)
        if context.area:
            context.area.tag_redraw()
        self.report({"INFO"}, iface_("Add Subdivision Before Deform"))
        return {"FINISHED"}


class SDH_OT_add_deform_layer(Operator):
    bl_idname = "sdh.add_deform_layer"
    bl_label = "Add Deformation Layer"
    bl_description = "Add one deformation operation to this cage"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    deform_type: EnumProperty(
        name="Deformation Type",
        items=(
            ("BEND", "Bend", "Curve geometry along the cage axis"),
            ("TWIST", "Twist", "Rotate cross-sections around the cage axis"),
            ("TAPER", "Taper", "Scale cross-sections along the cage axis"),
            ("STRETCH", "Stretch", "Scale geometry along the cage axis"),
            ("SHEAR", "Shear", "Slide cross-sections sideways along the cage axis"),
        ),
        default="BEND",
    )

    @classmethod
    def poll(cls, context):
        return bool(resolve_context_deform(context)[2])

    def execute(self, context):
        _target, _modifier, controller = resolve_context_deform(context)
        if controller is None:
            return {"CANCELLED"}
        if not add_deform_layer(
                controller.sdh_cage_deform, self.deform_type,
                context=context):
            self.report({"WARNING"}, iface_(
                "This deformation is already enabled"))
            return {"CANCELLED"}
        return {"FINISHED"}


class SDH_OT_select_deform_layer(Operator):
    bl_idname = "sdh.select_deform_layer"
    bl_label = "Select Deformation Layer"
    bl_description = "Select this deformation layer without changing its evaluation"
    bl_options = {"INTERNAL"}

    index: IntProperty(default=0, min=0, max=len(DEFORM_ORDER) - 1)

    @classmethod
    def poll(cls, context):
        return bool(resolve_context_deform(context)[2])

    def execute(self, context):
        _target, _modifier, controller = resolve_context_deform(context)
        if controller is None:
            return {"CANCELLED"}
        properties = controller.sdh_cage_deform
        ordered = ordered_deform_types(properties)
        if self.index >= len(ordered):
            return {"CANCELLED"}
        properties.active_deform_layer = self.index
        deform_type = ordered[self.index]
        expanded = set(getattr(properties, "expanded_deform_layers", ()))
        if deform_type in expanded:
            expanded.remove(deform_type)
        else:
            expanded.add(deform_type)
        properties.expanded_deform_layers = expanded
        if context.area:
            context.area.tag_redraw()
        return {"FINISHED"}


class SDH_OT_expand_all_deform_layers(Operator):
    bl_idname = "sdh.expand_all_deform_layers"
    bl_label = "Expand All"
    bl_description = "Expand every deformation layer"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return bool(resolve_context_deform(context)[2])

    def execute(self, context):
        _target, _modifier, controller = resolve_context_deform(context)
        if controller is None:
            return {"CANCELLED"}
        properties = controller.sdh_cage_deform
        properties.expanded_deform_layers = set(
            ordered_deform_types(properties))
        if context.area:
            context.area.tag_redraw()
        return {"FINISHED"}


class SDH_OT_remove_deform_layer(Operator):
    bl_idname = "sdh.remove_deform_layer"
    bl_label = "Remove Deformation Layer"
    bl_description = "Remove this deformation operation from the cage"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    index: IntProperty(default=0, min=0, max=len(DEFORM_ORDER) - 1)

    @classmethod
    def poll(cls, context):
        return bool(resolve_context_deform(context)[2])

    def execute(self, context):
        _target, _modifier, controller = resolve_context_deform(context)
        if controller is None:
            return {"CANCELLED"}
        if not remove_deform_layer(
                controller.sdh_cage_deform, self.index, context=context):
            self.report({"WARNING"}, iface_(
                "At least one deformation type must remain enabled"))
            return {"CANCELLED"}
        return {"FINISHED"}


class SDH_OT_toggle_deform_layer_mute(Operator):
    bl_idname = "sdh.toggle_deform_layer_mute"
    bl_label = "Toggle Deformation Layer"
    bl_description = (
        "Temporarily bypass or restore this deformation without losing its settings")
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    deform_type: EnumProperty(
        name="Deformation Type",
        items=tuple(
            (name, name.title(), f"Toggle {name.title()}")
            for name in DEFORM_ORDER
        ),
        default="BEND",
    )

    @classmethod
    def poll(cls, context):
        return bool(resolve_context_deform(context)[2])

    def execute(self, context):
        _target, _modifier, controller = resolve_context_deform(context)
        if controller is None:
            return {"CANCELLED"}
        properties = controller.sdh_cage_deform
        if self.deform_type not in set(properties.deform_types):
            return {"CANCELLED"}
        muted = self.deform_type not in set(properties.muted_deform_types)
        if not set_deform_layer_muted(
                properties, self.deform_type, muted, context=context):
            return {"CANCELLED"}
        return {"FINISHED"}


class SDH_OT_move_deform_layer(Operator):
    bl_idname = "sdh.move_deform_layer"
    bl_label = "Move Deformation Layer"
    bl_description = "Move this deformation operation earlier or later"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    index: IntProperty(default=0, min=0, max=len(DEFORM_ORDER) - 1)
    direction: EnumProperty(
        items=(
            ("UP", "Up", "Execute this layer earlier"),
            ("DOWN", "Down", "Execute this layer later"),
        ),
        default="UP",
    )

    @classmethod
    def poll(cls, context):
        return bool(resolve_context_deform(context)[2])

    def execute(self, context):
        _target, _modifier, controller = resolve_context_deform(context)
        if controller is None:
            return {"CANCELLED"}
        if not move_deform_layer(
                controller.sdh_cage_deform, self.index, self.direction,
                context=context):
            return {"CANCELLED"}
        return {"FINISHED"}


class SDH_OT_fit_cage_deform(Operator):
    bl_idname = "sdh.fit_cage_deform"
    bl_label = "Fit to Object"
    bl_description = (
        "Fit the active cage, or its entire connected chain, to the geometry "
        "entering the deformation"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        target, modifier, controller = resolve_context_deform(context)
        return bool(target and modifier and controller)

    def execute(self, context):
        target, modifier, controller = resolve_context_deform(context)
        if target is None or modifier is None or controller is None:
            return {"CANCELLED"}
        fitted_stages = 0
        try:
            from . import chain as chain_module
            chain_uuid = chain_module.stage_chain_uuid(modifier)
            chain_mode = chain_module.stage_chain_mode(modifier, "").upper()
            if chain_uuid and chain_mode in {"CHAINED", "CONNECTED"}:
                properties = controller.sdh_cage_deform
                fitted_stages = int(chain_module.redirect_chain_frame(
                    target,
                    chain_uuid,
                    modifier,
                    properties.alignment,
                    float(properties.bend_direction),
                    context=context,
                    fit=True,
                ) or 0)
        except (ImportError, AttributeError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            fitted_stages = 0
        if fitted_stages <= 0:
            fit_controller(context, target, modifier, controller)
            message = "Deformation cage fitted to stage input"
        else:
            message = iface_("Fitted {count} cage stages to chain input").format(
                count=fitted_stages)
        self.report({"INFO"}, message)
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


class SDH_OT_select_ffd_points(Operator):
    bl_idname = "sdh.select_ffd_points"
    bl_label = "Select FFD Points"
    bl_description = "Select all, none, or invert the dedicated FFD control points"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    action: EnumProperty(
        name="Selection",
        items=(
            ("ALL", "All", "Select every FFD control point"),
            ("NONE", "None", "Clear the FFD point selection"),
            ("INVERT", "Invert", "Invert the FFD point selection"),
        ),
        default="ALL",
    )

    @classmethod
    def poll(cls, context):
        controller = resolve_context_deform(context)[2]
        return bool(
            controller and
            str(getattr(controller.sdh_cage_deform, "cage_type", "")) == "FFD")

    def execute(self, context):
        controller = resolve_context_deform(context)[2]
        if controller is None:
            return {"CANCELLED"}
        properties = controller.sdh_cage_deform
        ensure_ffd_point_collection(properties)
        visible = set(ffd_visible_indices(properties))
        if self.action == "ALL":
            indices = visible
        elif self.action == "NONE":
            indices = ()
        else:
            indices = tuple(
                index for index, point in enumerate(properties.ffd_points)
                if index in visible and not point.selected)
        ffd_set_selection(properties, indices)
        if context.area:
            context.area.tag_redraw()
        return {"FINISHED"}


class SDH_OT_set_ffd_selection_mode(Operator):
    bl_idname = "sdh.set_ffd_selection_mode"
    bl_label = "Set FFD Selection Mode"
    bl_description = (
        "Choose one FFD controller type; hold Shift to enable or disable "
        "multiple controller types"
    )
    bl_options = {"INTERNAL"}

    mode: EnumProperty(
        name="Mode",
        items=(
            ("POINT", "Point", "Show and select FFD point controllers"),
            ("LINE", "Line", "Show and select FFD line-segment controllers"),
            ("FACE", "Face", "Show and select FFD face controllers"),
        ),
        default="POINT",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    extend: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        controller = resolve_context_deform(context)[2]
        return bool(
            controller and
            str(getattr(controller.sdh_cage_deform, "cage_type", "")) == "FFD")

    def invoke(self, context, event):
        self.extend = bool(getattr(event, "shift", False))
        return self.execute(context)

    def execute(self, context):
        controller = resolve_context_deform(context)[2]
        if controller is None:
            return {"CANCELLED"}
        properties = controller.sdh_cage_deform
        mode = str(self.mode)
        current = set(ffd_selection_modes(properties))
        if self.extend:
            if mode in current and len(current) > 1:
                current.remove(mode)
            else:
                current.add(mode)
        else:
            current = {mode}
        properties.ffd_selection_modes = current
        if context.area:
            context.area.tag_redraw()
        return {"FINISHED"}


class SDH_OT_set_ffd_symmetry_axes(Operator):
    bl_idname = "sdh.set_ffd_symmetry_axes"
    bl_label = "Set FFD Symmetry Axes"
    bl_description = (
        "Choose one FFD symmetry axis; hold Shift to enable or disable "
        "multiple axes"
    )
    bl_options = {"INTERNAL"}

    axis: EnumProperty(
        name="Axis",
        items=(
            ("U", "U", "Mirror across the cage-local U center plane"),
            ("V", "V", "Mirror across the cage-local V center plane"),
            ("W", "W", "Mirror across the cage-local W center plane"),
        ),
        default="U",
        options={"HIDDEN", "SKIP_SAVE"},
    )
    extend: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        controller = resolve_context_deform(context)[2]
        return bool(
            controller and
            str(getattr(controller.sdh_cage_deform, "cage_type", "")) == "FFD")

    def invoke(self, context, event):
        self.extend = bool(getattr(event, "shift", False))
        return self.execute(context)

    def execute(self, context):
        controller = resolve_context_deform(context)[2]
        if controller is None:
            return {"CANCELLED"}
        properties = controller.sdh_cage_deform
        axis = str(self.axis).upper()
        if axis not in FFD_SYMMETRY_AXIS_ORDER:
            return {"CANCELLED"}
        current = set(ffd_symmetry_axes(properties))
        if self.extend:
            if axis in current and len(current) > 1:
                current.remove(axis)
            else:
                current.add(axis)
        else:
            current = {axis}
        properties.ffd_symmetry_axes = current
        if context.area:
            context.area.tag_redraw()
        return {"FINISHED"}


def reset_ffd_offsets(controller, context):
    """Return every editable and legacy FFD point to its source position."""
    if controller is None:
        return False
    properties = getattr(controller, "sdh_cage_deform", None)
    if properties is None:
        return False
    properties.ffd_offsets = (0.0,) * FFD_COMPONENT_COUNT
    if hasattr(properties, "ffd_points"):
        pointer = _pointer(controller)
        if pointer:
            _FFD_POINT_GUARD.add(pointer)
        try:
            for point in properties.ffd_points:
                point.offset = (0.0, 0.0, 0.0)
        finally:
            if pointer:
                _FFD_POINT_GUARD.discard(pointer)
    _controller_update(properties, context)
    return True


def ffd_transform_axis_state(current_axis, current_space, requested_axis):
    """Return Blender-style repeated-axis constraint state for FFD edits."""
    requested_axis = int(requested_axis)
    if current_axis != requested_axis:
        return requested_axis, "GLOBAL"
    return requested_axis, (
        "LOCAL" if str(current_space).upper() == "GLOBAL" else "GLOBAL")


def ffd_transform_axis_world(cage_matrix, axis, space="GLOBAL"):
    """Resolve one FFD transform constraint in world space."""
    unit_axis = Vector((
        1.0 if axis == 0 else 0.0,
        1.0 if axis == 1 else 0.0,
        1.0 if axis == 2 else 0.0,
    ))
    if str(space).upper() == "GLOBAL":
        return unit_axis
    world_axis = Matrix(cage_matrix).to_3x3() @ unit_axis
    return world_axis.normalized() if world_axis.length > EPSILON else unit_axis


def ffd_point_tangent_local(
        properties, point_index, positions=None, *, axis="V"):
    """Return one current positive topology-axis tangent at an FFD point."""
    resolution = ffd_resolution(properties)
    count = math.prod(resolution)
    axis = str(axis or "V").upper()
    axis_index = {"U": 0, "V": 1, "W": 2}.get(axis)
    if axis_index is None:
        raise ValueError(f"Unsupported FFD tangent axis: {axis!r}")
    fallback = Vector(tuple(
        1.0 if component == axis_index else 0.0
        for component in range(3)))
    if count <= 0:
        return fallback
    point_index = min(max(int(point_index), 0), count - 1)
    coordinates = list(ffd_point_coordinates(point_index, resolution))

    def point_at(sample):
        sample_coordinates = coordinates.copy()
        sample_coordinates[axis_index] = sample
        index = ffd_point_index(*sample_coordinates, resolution)
        if positions is not None:
            try:
                return Vector(positions[index])
            except (KeyError, IndexError, TypeError):
                pass
        return (
            SDH_OT_box_select_ffd_points._point_source_local(properties, index) +
            ffd_point_offset(properties, index))

    coordinate = coordinates[axis_index]
    lower = max(coordinate - 1, 0)
    upper = min(coordinate + 1, resolution[axis_index] - 1)
    tangent = point_at(upper) - point_at(lower)
    if tangent.length <= EPSILON:
        tangent = fallback
    else:
        tangent.normalize()
    return tangent


def ffd_tangent_slide_field(
        properties, cage_matrix, selected_indices, positions=None, *, axis="V"):
    """Return one topology axis's representative and per-point tangents."""
    resolution = ffd_resolution(properties)
    count = math.prod(resolution)
    axis = str(axis or "V").upper()
    axis_index = {"U": 0, "V": 1, "W": 2}.get(axis)
    if axis_index is None:
        raise ValueError(f"Unsupported FFD tangent axis: {axis!r}")
    if positions is None:
        positions = {
            index: (
                SDH_OT_box_select_ffd_points._point_source_local(
                    properties, index) +
                ffd_point_offset(properties, index))
            for index in range(count)
        }
    indices = tuple(int(index) for index in positions)
    basis = Matrix(cage_matrix).to_3x3()
    fallback = basis @ Vector(tuple(
        1.0 if component == axis_index else 0.0
        for component in range(3)))
    fallback = (
        fallback.normalized() if fallback.length > EPSILON else
        Vector(tuple(
            1.0 if component == axis_index else 0.0
            for component in range(3))))
    field = {}
    for index in indices:
        tangent = basis @ ffd_point_tangent_local(
            properties, index, positions, axis=axis)
        field[index] = (
            tangent.normalized() if tangent.length > EPSILON else
            fallback.copy())
    selected = tuple(
        field[index] for index in selected_indices if index in field)
    representative = sum(selected, Vector((0.0, 0.0, 0.0)))
    if representative.length <= EPSILON:
        representative = fallback.copy()
    else:
        representative.normalize()
    if representative.dot(fallback) < 0.0:
        representative.negate()
    return representative, field


def ffd_tangent_slide_fields(
        properties, cage_matrix, selected_indices, positions=None,
        *, axes=("U", "V", "W")):
    """Return independent deformed tangent fields for each requested axis."""
    return {
        str(axis).upper(): ffd_tangent_slide_field(
            properties,
            cage_matrix,
            selected_indices,
            positions,
            axis=str(axis).upper(),
        )
        for axis in axes
    }


def ffd_tangent_slide_axis_from_screen(
        mouse_delta, screen_axes, *, current_axis=None, hysteresis=0.08):
    """Choose the topology tangent line best aligned with pointer motion."""
    mouse_delta = Vector(mouse_delta)
    if mouse_delta.length_squared <= 1.0e-8:
        return current_axis if current_axis in screen_axes else None
    mouse_direction = mouse_delta.normalized()
    scores = {}
    for axis, direction in screen_axes.items():
        direction = Vector(direction)
        if direction.length_squared <= 1.0e-8:
            continue
        # Both signs belong to the same topology line. The signed distance is
        # resolved separately after the line itself has been chosen.
        scores[str(axis).upper()] = abs(
            mouse_direction.dot(direction.normalized()))
    if not scores:
        return None
    best_axis = max(scores, key=scores.get)
    current_axis = str(current_axis).upper() if current_axis else None
    if (
            current_axis in scores and current_axis != best_axis and
            scores[current_axis] + max(float(hysteresis), 0.0) >=
            scores[best_axis]
    ):
        return current_axis
    return best_axis


def ffd_tangent_slide_values(
        base_points, world_tangents, cage_inverse, distance, weights):
    """Move each authored point along its own current world-space tangent."""
    inverse = Matrix(cage_inverse).to_3x3()
    distance = float(distance)
    result = {}
    for index, point in base_points.items():
        tangent = Vector(world_tangents.get(index, (0.0, 1.0, 0.0)))
        if tangent.length <= EPSILON:
            tangent = Vector((0.0, 1.0, 0.0))
        else:
            tangent.normalize()
        local_delta = inverse @ (tangent * distance)
        result[index] = (
            Vector(point) + local_delta * float(weights.get(index, 0.0)))
    return result


class SDH_WST_ffd_edit(WorkSpaceTool):
    bl_space_type = "VIEW_3D"
    bl_context_mode = "OBJECT"
    bl_idname = _FFD_WORKSPACE_TOOL_ID
    bl_label = "FFD Edit"
    bl_description = "Select and transform FFD points, lines, and faces"
    bl_icon = "ops.generic.select_box"
    bl_widget = None
    bl_keymap = (
        (
            "sdh.box_select_ffd_points",
            {"type": "B", "value": "PRESS"},
            {"properties": [
                ("arm_box_select", True), ("toggle", False)]},
        ),
        (
            "sdh.box_select_ffd_points",
            {"type": "LEFTMOUSE", "value": "CLICK_DRAG"},
            {"properties": [("start_box_select", True), ("toggle", False)]},
        ),
        (
            "sdh.box_select_ffd_points",
            {"type": "LEFTMOUSE", "value": "CLICK_DRAG", "shift": True},
            {"properties": [("start_box_select", True), ("toggle", False)]},
        ),
        (
            "sdh.box_select_ffd_points",
            {"type": "LEFTMOUSE", "value": "CLICK_DRAG", "ctrl": True},
            {"properties": [("start_box_select", True), ("toggle", False)]},
        ),
        (
            "sdh.box_select_ffd_points",
            {
                "type": "LEFTMOUSE",
                "value": "CLICK_DRAG",
                "shift": True,
                "ctrl": True,
            },
            {"properties": [("start_box_select", True), ("toggle", False)]},
        ),
    )


class SDH_WST_curve_edit(WorkSpaceTool):
    bl_space_type = "VIEW_3D"
    bl_context_mode = "OBJECT"
    bl_idname = _CURVE_WORKSPACE_TOOL_ID
    bl_label = "Curve Edit"
    bl_description = "Select and transform Curve guide points and handles"
    bl_icon = "ops.generic.select_box"
    bl_widget = None
    bl_keymap = (
        (
            "sdh.edit_curve_cage_object",
            {"type": "B", "value": "PRESS"},
            {"properties": [
                ("arm_box_select", True), ("toggle", False)]},
        ),
        (
            "sdh.edit_curve_cage_object",
            {"type": "LEFTMOUSE", "value": "CLICK_DRAG"},
            {"properties": [("start_box_select", True), ("toggle", False)]},
        ),
        (
            "sdh.edit_curve_cage_object",
            {"type": "LEFTMOUSE", "value": "CLICK_DRAG", "shift": True},
            {"properties": [("start_box_select", True), ("toggle", False)]},
        ),
        (
            "sdh.edit_curve_cage_object",
            {"type": "LEFTMOUSE", "value": "CLICK_DRAG", "ctrl": True},
            {"properties": [("start_box_select", True), ("toggle", False)]},
        ),
        (
            "sdh.edit_curve_cage_object",
            {
                "type": "LEFTMOUSE",
                "value": "CLICK_DRAG",
                "shift": True,
                "ctrl": True,
            },
            {"properties": [("start_box_select", True), ("toggle", False)]},
        ),
    )


class SDH_OT_box_select_ffd_points(Operator):
    bl_idname = "sdh.box_select_ffd_points"
    bl_label = "Edit FFD Points"
    bl_description = (
        "Keep FFD point editing active; drag blank viewport space to box "
        "select and use Esc, right-click, or double-click blank space to exit"
    )
    bl_options = {"REGISTER", "INTERNAL"}

    _MOUSE_EVENTS = {
        "LEFTMOUSE", "MIDDLEMOUSE", "RIGHTMOUSE",
        "BUTTON4MOUSE", "BUTTON5MOUSE", "BUTTON6MOUSE", "BUTTON7MOUSE",
        "WHEELUPMOUSE", "WHEELDOWNMOUSE", "WHEELINMOUSE", "WHEELOUTMOUSE",
        "MOUSEMOVE", "INBETWEEN_MOUSEMOVE", "TRACKPADPAN", "TRACKPADZOOM",
    }

    controller_name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    toggle: BoolProperty(default=True, options={"HIDDEN", "SKIP_SAVE"})
    start_drag: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})
    start_box_select: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})
    arm_box_select: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})
    start_anchor: IntProperty(default=-1, options={"HIDDEN", "SKIP_SAVE"})
    start_selection_mode: StringProperty(
        default="POINT", options={"HIDDEN", "SKIP_SAVE"})
    start_selection_axis: StringProperty(
        default="POINT", options={"HIDDEN", "SKIP_SAVE"})
    start_mouse_region_x: IntProperty(
        default=0, options={"HIDDEN", "SKIP_SAVE"})
    start_mouse_region_y: IntProperty(
        default=0, options={"HIDDEN", "SKIP_SAVE"})
    start_extend: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        if not (
                getattr(context, "area", None) and
                context.area.type == "VIEW_3D"
        ):
            return False
        # The scoped FFD tool can remain active for one event while Blender
        # clears the object selection. Let its keymap dispatch to the native
        # Select Box instead of making an empty viewport appear inert.
        if not tuple(getattr(context, "selected_objects", ()) or ()):
            return True
        if not ffd_handles_enabled():
            return False
        target, modifier, controller = resolve_context_deform(context)
        return bool(
            target and modifier and controller and
            str(getattr(controller.sdh_cage_deform, "cage_type", "")) == "FFD")

    def _controller(self):
        try:
            return bpy.data.objects.get(getattr(self, "_controller_name", ""))
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            return None

    @staticmethod
    def _inside_region(region, event):
        return (
            region.x <= event.mouse_x <= region.x + region.width and
            region.y <= event.mouse_y <= region.y + region.height)

    def _inside_ui_region(self, context, event):
        """Return True when a mouse event belongs to Blender UI, not the view.

        The sidebar is exposed as a separate ``UI`` region in some Blender
        layouts, while other layouts report its coordinates inside the main
        ``WINDOW`` region. Checking all non-window UI regions before the view
        hit-test keeps the FFD modal from consuming N-panel clicks in both
        cases.
        """
        area = getattr(self, "_area", None) or getattr(context, "area", None)
        if area is None:
            return False
        mouse_x = getattr(event, "mouse_x", None)
        mouse_y = getattr(event, "mouse_y", None)
        if mouse_x is None or mouse_y is None:
            previous = getattr(self, "_last_mouse_position", None)
            if previous is None:
                return False
            mouse_x, mouse_y = previous
        window_region = getattr(self, "_window_region", None)
        for candidate in tuple(getattr(area, "regions", ())):
            if candidate is window_region:
                continue
            if str(getattr(candidate, "type", "")) not in {
                    "UI", "TOOLS", "HEADER", "TOOL_HEADER", "FOOTER",
            }:
                continue
            if (
                    candidate.x <= mouse_x <= candidate.x + candidate.width and
                    candidate.y <= mouse_y <= candidate.y + candidate.height
            ):
                return True
        return False

    @staticmethod
    def _region_position(region, event):
        return (
            float(event.mouse_x - region.x),
            float(event.mouse_y - region.y),
        )

    @staticmethod
    def _tool_settings(context):
        scene = getattr(context, "scene", None)
        return getattr(scene, "tool_settings", None) or getattr(
            context, "tool_settings", None)

    @classmethod
    def _proportional_enabled(cls, context):
        settings = cls._tool_settings(context)
        return bool(
            getattr(settings, "use_proportional_edit_objects", False) or
            getattr(settings, "use_proportional_edit", False))

    def _proportional_weights(self, context):
        selected = set(getattr(self, "_transform_selected_indices", ()))
        if not self._proportional_enabled(context):
            return {
                index: 1.0 if index in selected else 0.0
                for index in getattr(self, "_transform_initial_points", {})
            }
        try:
            radius = max(float(getattr(
                self, "_proportional_radius", EPSILON)), EPSILON)
        except (TypeError, ValueError):
            radius = EPSILON
        settings = self._tool_settings(context)
        falloff = str(getattr(
            settings, "proportional_edit_falloff", "SMOOTH"))
        distances = getattr(self, "_transform_proportional_distances", {})
        return {
            index: (
                1.0 if index in selected else
                ffd_proportional_weight(
                    distances.get(index, math.inf), radius, falloff, index)
            )
            for index in getattr(self, "_transform_initial_points", {})
        }

    def _initialize_proportional_radius(self, context=None):
        """Use Blender's proportional radius, with a cage-sized fallback.

        ``ToolSettings.proportional_size`` is the same value Blender changes
        with the mouse wheel during G/R/S.  Reusing it makes FFD controls feel
        like native proportional editing and preserves the user's preferred
        radius between transforms.  Older Blender builds or synthetic test
        contexts may not expose the property, so the fallback is derived from
        the point cloud in linear time.
        """
        settings = self._tool_settings(context) if context is not None else None
        try:
            configured = float(getattr(settings, "proportional_size", math.nan))
        except (AttributeError, TypeError, ValueError):
            configured = math.nan
        if math.isfinite(configured) and configured > EPSILON:
            self._proportional_radius = configured
            return
        points = tuple(getattr(self, "_transform_world_points", {}).values())
        selected = set(getattr(self, "_transform_selected_indices", ()))
        distances = getattr(self, "_transform_proportional_distances", {})
        positive = tuple(
            distance for index, distance in distances.items()
            if index not in selected and distance > EPSILON and math.isfinite(distance)
        )
        if positive:
            radius = min(positive) * 2.5
        elif len(points) > 1:
            # The cage can contain thousands of points.  The old all-pairs
            # diameter calculation became quadratic and made entering FFD
            # edit mode noticeably slow at higher resolutions.
            minimum = Vector((
                min(point[axis] for point in points) for axis in range(3)))
            maximum = Vector((
                max(point[axis] for point in points) for axis in range(3)))
            diagonal = (maximum - minimum).length
            radius = diagonal * 0.35
        else:
            radius = 1.0
        self._proportional_radius = max(float(radius), EPSILON)

    def _set_header(self, context):
        area = getattr(self, "_area", None) or getattr(context, "area", None)
        if area is not None:
            translate = bpy.app.translations.pgettext_iface
            if getattr(self, "_state", "") == "TRANSFORM":
                mode = translate({
                    "MOVE": "Move",
                    "TANGENT_SLIDE": "Tangent Slide",
                    "ROTATE": "Rotate",
                    "SCALE": "Scale",
                }.get(getattr(self, "_transform_mode", ""), "Move"))
                transform_mode = getattr(self, "_transform_mode", "")
                axis = getattr(self, "_transform_axis", None)
                if transform_mode == "TANGENT_SLIDE":
                    slide_axis = getattr(self, "_transform_slide_axis", None)
                    axis_label = f" [{slide_axis}]" if slide_axis else ""
                elif axis is None:
                    axis_label = ""
                else:
                    axis_space = translate(str(getattr(
                        self, "_transform_axis_space", "GLOBAL")).title())
                    axis_label = f" [{('X', 'Y', 'Z')[axis]} {axis_space}]"
                controls = translate(
                    "Mouse Slide Along Tangent | G Return to Move | "
                    "Shift Precise | Ctrl Snap | Click/Enter Confirm | "
                    "Esc/Right Mouse Cancel"
                    if getattr(self, "_transform_mode", "") == "TANGENT_SLIDE"
                    else
                    "Mouse Transform | G Tangent Slide | X/Y/Z Global; "
                    "Repeat for Cage Local | Shift Precise | Ctrl Snap | "
                    "Click/Enter Confirm | Esc/Right Mouse Cancel")
                if self._proportional_enabled(context):
                    settings = self._tool_settings(context)
                    falloff = translate(str(getattr(
                        settings, "proportional_edit_falloff", "SMOOTH")).title())
                    controls += translate(
                        " | Proportional | Wheel Radius")
                    try:
                        radius = float(getattr(
                            self, "_proportional_radius", 0.0))
                    except (TypeError, ValueError):
                        radius = 0.0
                    controls += f" | {falloff} {radius:.3f}"
                area.header_text_set(f"FFD {mode}{axis_label}   |   {controls}")
            elif getattr(self, "_state", "") == "BOX_READY":
                area.header_text_set(translate(
                    "FFD Box Select: drag a rectangle over FFD points, lines, or faces | "
                    "Esc / Right Mouse cancels"))
            else:
                area.header_text_set(translate(
                    "FFD Edit Mode: drag blank area to box select | G Move; "
                    "G again Tangent Slide | "
                    "R Rotate | S Scale | Shift Add | Ctrl Subtract | "
                    "A Select All | Alt+A Clear | I Key | Alt+I Delete Key | "
                    "Alt+R Reset | "
                    "Double-click blank / Esc / Right Mouse exits"))
            area.tag_redraw()

    @staticmethod
    def _point_source_local(properties, point_index):
        resolution = ffd_resolution(properties)
        u, v, w = ffd_point_coordinates(point_index, resolution)
        size = Vector(properties.size)
        return Vector((
            -size.x * 0.5 + size.x * u / max(resolution[0] - 1, 1),
            -size.y * 0.5 + size.y * v / max(resolution[1] - 1, 1),
            -size.z * 0.5 + size.z * w / max(resolution[2] - 1, 1),
        ))

    @classmethod
    def _point_local(cls, properties, point_index):
        return (
            cls._point_source_local(properties, point_index) +
            ffd_point_offset(properties, point_index))

    @classmethod
    def _point_world(cls, target, controller, properties, point_index):
        """Match the authored cage coordinates used by the FFD Gizmos."""
        return cage_local_matrix(target, controller) @ (
            cls._point_local(properties, point_index))

    def _selected_transform_indices(self, properties):
        visible = set(ffd_visible_indices(properties))
        return tuple(
            index for index, point in enumerate(properties.ffd_points)
            if point.selected and index in visible)

    def _begin_transform(self, context, event, mode, *, initial_mouse=None):
        controller = self._controller()
        target = find_target(controller) if controller is not None else None
        if controller is None or target is None:
            return False
        properties = controller.sdh_cage_deform
        ensure_ffd_point_collection(properties)
        selected_indices = self._selected_transform_indices(properties)
        if not selected_indices:
            self.report({"INFO"}, "Select at least one FFD control point")
            return False
        cage_matrix = cage_local_matrix(target, controller)
        visible_indices = tuple(ffd_visible_indices(properties))
        all_initial_points = {
            index: self._point_local(properties, index)
            for index in range(ffd_point_count(properties))
        }
        initial_points = {
            index: all_initial_points[index]
            for index in visible_indices
        }
        pivot_local = Vector((0.0, 0.0, 0.0))
        for index in selected_indices:
            point = initial_points[index]
            pivot_local += point
        pivot_local /= len(selected_indices)
        self._transform_mode = mode
        self._transform_axis = None
        self._transform_axis_space = "GLOBAL"
        # Keep a stable snapshot of the editable points for the active
        # transform.  ``indices`` used to be an accidental reference left
        # from the old point-only path; it is not defined here and caused a
        # NameError as soon as a FFD handle was dragged.
        self._transform_indices = tuple(visible_indices)
        try:
            active_index = int(
                getattr(properties, "ffd_active_point", selected_indices[0]))
        except (AttributeError, TypeError, ValueError):
            active_index = selected_indices[0]
        self._transform_driver_index = (
            active_index if active_index in selected_indices else selected_indices[0])
        self._transform_selected_indices = tuple(selected_indices)
        self._transform_initial_offsets = {
            index: Vector(properties.ffd_points[index].offset)
            for index in visible_indices
        }
        if getattr(self, "_state", "") != "TRANSFORM":
            # G can rebase one live transform between free Move and Tangent
            # Slide. Keep the first snapshot as the cancel target for the
            # whole gesture instead of replacing it at every mode switch.
            self._transform_cancel_offsets = {
                index: value.copy()
                for index, value in self._transform_initial_offsets.items()
            }
        self._transform_source_points = {
            index: self._point_source_local(properties, index)
            for index in visible_indices
        }
        self._transform_initial_points = initial_points
        self._transform_cage_matrix = cage_matrix.copy()
        self._transform_cage_inverse = cage_matrix.inverted_safe()
        self._transform_pivot_local = pivot_local
        self._transform_pivot_world = cage_matrix @ pivot_local
        self._transform_world_points = {
            index: cage_matrix @ point
            for index, point in initial_points.items()
        }
        self._transform_proportional_distances = {
            index: min(
                (world - self._transform_world_points[selected]).length
                for selected in selected_indices
            )
            for index, world in self._transform_world_points.items()
        }
        try:
            proportional_radius = float(getattr(
                self, "_proportional_radius", math.nan))
        except (TypeError, ValueError):
            proportional_radius = math.nan
        if not math.isfinite(proportional_radius):
            self._initialize_proportional_radius(context)
        self._transform_initial_mouse = Vector(
            initial_mouse if initial_mouse is not None else
            self._region_position(self._window_region, event))
        self._pointer_click_group = ()
        self._pointer_click_active = -1
        self._pointer_dragged = False
        clear_ffd_hover_entity(controller)
        self._state = "TRANSFORM"
        self._set_header(context)
        return True

    def _begin_pointer_transform(
            self, context, properties, *, anchor, selection_mode,
            selection_axis, extend, initial_mouse):
        point_count = len(getattr(properties, "ffd_points", ()))
        if point_count <= 0 or not 0 <= int(anchor) < point_count:
            return False
        anchor = int(anchor)
        axis = None if selection_axis in {"", "POINT", "NONE"} else selection_axis
        group = set(ffd_selection_indices(
            properties, anchor, selection_mode, axis=axis))
        group = ffd_symmetry_expand_indices(properties, group)
        current = {
            index for index, point in enumerate(properties.ffd_points)
            if point.selected
        }
        selected, collapse_on_click = ffd_pointer_selection_update(
            current, group, extend=extend)
        active = (
            anchor if anchor in selected else
            min(selected) if selected else None)
        ffd_set_selection(properties, selected, active=active)
        if anchor not in selected:
            return False
        if not self._begin_transform(
                context, None, "MOVE", initial_mouse=initial_mouse):
            return False
        if collapse_on_click:
            self._pointer_click_group = tuple(sorted(group))
            self._pointer_click_active = anchor
        return True

    def _write_transform_points(self, context, properties, values):
        controller = self._controller()
        if controller is None:
            return False
        current_offsets = _ffd_guard_offsets_snapshot(properties)
        candidate_offsets = list(current_offsets)
        baseline_offsets = list(current_offsets)
        initial_points = getattr(self, "_transform_initial_points", {})
        if not initial_points:
            initial_points = {
                index: self._transform_source_points[index] + Vector(value)
                for index, value in getattr(
                    self, "_transform_initial_offsets", {}).items()
            }
        for index, point in initial_points.items():
            source = self._transform_source_points[index]
            baseline_offsets[index] = tuple(Vector(point) - source)
        for index, point in values.items():
            source = self._transform_source_points[index]
            candidate_offsets[index] = tuple(Vector(point) - source)
        safe_offsets, fraction, _baseline_ratio, _candidate_ratio = (
            ffd_guard_offsets(
                properties,
                tuple(candidate_offsets),
                baseline_offsets=tuple(baseline_offsets),
            )
        )
        self._ffd_guard_last_fraction = float(fraction)
        updates = {}
        for index, point in values.items():
            source = self._transform_source_points[index]
            # Transform values are absolute authored-cage positions captured
            # from the transform start. Writing the absolute raw offset keeps
            # every mouse event idempotent and leaves point influence solely
            # in the runtime lattice evaluation path.
            requested = Vector(safe_offsets[index])
            current = Vector(properties.ffd_points[index].offset)
            if (requested - current).length > EPSILON:
                updates[index] = requested
        if not updates:
            return True
        _undo.begin(self, "Before FFD Control")
        pointer = int(controller.as_pointer())
        _FFD_POINT_GUARD.add(pointer)
        try:
            for index, requested in updates.items():
                properties.ffd_points[index].offset = tuple(requested)
        finally:
            _FFD_POINT_GUARD.discard(pointer)
        _controller_update(properties, context)
        if self._area is not None:
            self._area.tag_redraw()
        return True

    def _restore_transform(self, context, properties):
        controller = self._controller()
        if controller is None:
            return
        pointer = int(controller.as_pointer())
        _FFD_POINT_GUARD.add(pointer)
        try:
            cancel_offsets = getattr(
                self, "_transform_cancel_offsets", None)
            if cancel_offsets is None:
                cancel_offsets = getattr(
                    self, "_transform_initial_offsets", {})
            for index, value in cancel_offsets.items():
                if index < len(properties.ffd_points):
                    properties.ffd_points[index].offset = tuple(value)
        finally:
            _FFD_POINT_GUARD.discard(pointer)
        _controller_update(properties, context)

    def _finish_transform(self, context, properties, *, cancel=False):
        controller_getter = getattr(self, "_controller", None)
        clear_ffd_hover_entity(
            controller_getter() if callable(controller_getter) else None)
        if cancel:
            self._restore_transform(context, properties)
        elif (
                getattr(self, "_pointer_click_group", ()) and
                not bool(getattr(self, "_pointer_dragged", False))
        ):
            ffd_set_selection(
                properties,
                self._pointer_click_group,
                active=getattr(self, "_pointer_click_active", None),
            )
        _undo.finish(self, cancel=cancel, message="FFD Control")
        self._transform_cancel_offsets = None
        self._pointer_click_group = ()
        self._pointer_click_active = -1
        self._pointer_dragged = False
        self._initial_pointer_selection_guard = False
        self._state = "WAITING"
        self._set_header(context)

    def _transform_axis_world(self, axis):
        return ffd_transform_axis_world(
            self._transform_cage_matrix,
            axis,
            getattr(self, "_transform_axis_space", "GLOBAL"),
        )

    def _begin_tangent_slide(self, context, event, properties):
        """Rebase the move onto mouse-selectable U/V/W cage tangents."""
        current_all = {
            index: self._point_local(properties, index)
            for index in range(ffd_point_count(properties))
        }
        current_visible = {
            index: current_all[index]
            for index in getattr(self, "_transform_indices", ())
            if index in current_all
        }
        selected = tuple(getattr(self, "_transform_selected_indices", ()))
        if not current_visible or not selected:
            return False
        fields = ffd_tangent_slide_fields(
            properties,
            self._transform_cage_matrix,
            selected,
            current_all,
        )
        selected_points = tuple(
            current_visible[index] for index in selected
            if index in current_visible)
        if not selected_points:
            return False
        pivot_local = (
            sum(selected_points, Vector((0.0, 0.0, 0.0))) /
            len(selected_points))
        self._transform_mode = "TANGENT_SLIDE"
        self._transform_axis = None
        self._transform_slide_base_points = current_visible
        self._transform_slide_world_axes = {
            axis: representative
            for axis, (representative, _tangents) in fields.items()
        }
        self._transform_slide_world_tangent_fields = {
            axis: {
                index: tangents[index]
                for index in current_visible if index in tangents
            }
            for axis, (_representative, tangents) in fields.items()
        }
        self._transform_slide_axis = None
        # Keep the previous single-field attributes available for callers that
        # inspect the live modal before the first directional mouse movement.
        fallback_axis = "V" if "V" in fields else next(iter(fields))
        self._transform_slide_world_axis = (
            self._transform_slide_world_axes[fallback_axis])
        self._transform_slide_world_tangents = (
            self._transform_slide_world_tangent_fields[fallback_axis])
        self._transform_slide_pivot_world = (
            self._transform_cage_matrix @ pivot_local)
        self._transform_slide_initial_mouse = Vector(
            self._region_position(self._window_region, event))
        self._set_header(context)
        return True

    def _tangent_slide_screen_axes(self):
        """Project every usable slide candidate into the current region."""
        from bpy_extras import view3d_utils

        pivot = Vector(self._transform_slide_pivot_world)
        pivot_screen = view3d_utils.location_3d_to_region_2d(
            self._window_region, self._region_data, pivot)
        if pivot_screen is None:
            return {}
        screen_axes = {}
        for axis, world_axis in getattr(
                self, "_transform_slide_world_axes", {}).items():
            tangent_screen = view3d_utils.location_3d_to_region_2d(
                self._window_region,
                self._region_data,
                pivot + Vector(world_axis),
            )
            if tangent_screen is None:
                continue
            screen_axis = Vector(tangent_screen) - Vector(pivot_screen)
            if screen_axis.length_squared > 1.0e-4:
                screen_axes[axis] = screen_axis
        return screen_axes

    def _select_tangent_slide_axis(self, context, current_mouse):
        """Update the active topology line from the current pointer intent."""
        mouse_delta = (
            Vector(current_mouse) -
            Vector(self._transform_slide_initial_mouse))
        current_axis = getattr(self, "_transform_slide_axis", None)
        if mouse_delta.length_squared < 4.0:
            return current_axis
        selected_axis = ffd_tangent_slide_axis_from_screen(
            mouse_delta,
            self._tangent_slide_screen_axes(),
            current_axis=current_axis,
        )
        if selected_axis is None:
            return current_axis
        self._transform_slide_axis = selected_axis
        self._transform_slide_world_axis = (
            self._transform_slide_world_axes[selected_axis])
        self._transform_slide_world_tangents = (
            self._transform_slide_world_tangent_fields[selected_axis])
        if selected_axis != current_axis:
            self._set_header(context)
        return selected_axis

    def _tangent_slide_distance(self, current_mouse, world_axis=None):
        """Map pointer motion to signed world distance along the slide tangent."""
        from bpy_extras import view3d_utils

        region = self._window_region
        region_data = self._region_data
        pivot = Vector(self._transform_slide_pivot_world)
        axis = Vector(
            world_axis if world_axis is not None else
            self._transform_slide_world_axis)
        initial_mouse = Vector(self._transform_slide_initial_mouse)
        pivot_screen = view3d_utils.location_3d_to_region_2d(
            region, region_data, pivot)
        tangent_screen = view3d_utils.location_3d_to_region_2d(
            region, region_data, pivot + axis)
        if pivot_screen is not None and tangent_screen is not None:
            screen_axis = Vector(tangent_screen) - Vector(pivot_screen)
            if screen_axis.length_squared > 1.0e-4:
                return (
                    (Vector(current_mouse) - initial_mouse).dot(screen_axis) /
                    screen_axis.length_squared)
        start_world = view3d_utils.region_2d_to_location_3d(
            region, region_data, initial_mouse, pivot)
        current_world = view3d_utils.region_2d_to_location_3d(
            region, region_data, current_mouse, pivot)
        distance = (Vector(current_world) - Vector(start_world)).dot(axis)
        if abs(distance) > EPSILON:
            return distance
        pixel_world = view3d_utils.region_2d_to_location_3d(
            region, region_data, initial_mouse + Vector((0.0, 1.0)), pivot)
        world_per_pixel = max(
            (Vector(pixel_world) - Vector(start_world)).length, EPSILON)
        return (Vector(current_mouse).y - initial_mouse.y) * world_per_pixel

    def _apply_transform(self, context, event, properties):
        from bpy_extras import view3d_utils

        region = self._window_region
        region_data = self._region_data
        current_mouse = Vector(self._region_position(region, event))
        if (
                getattr(self, "_pointer_click_group", ()) and
                not bool(getattr(self, "_pointer_dragged", False))
        ):
            if (current_mouse - self._transform_initial_mouse).length < 3.0:
                return True
            self._pointer_dragged = True
        precise = 0.1 if bool(getattr(event, "shift", False)) else 1.0
        snap = bool(getattr(event, "ctrl", False))
        axis = getattr(self, "_transform_axis", None)
        mode = getattr(self, "_transform_mode", "MOVE")
        weights = self._proportional_weights(context)
        values = {}
        if mode == "MOVE":
            start_world = view3d_utils.region_2d_to_location_3d(
                region, region_data, self._transform_initial_mouse,
                self._transform_pivot_world)
            current_world = view3d_utils.region_2d_to_location_3d(
                region, region_data, current_mouse,
                self._transform_pivot_world)
            world_delta = (current_world - start_world) * precise
            if axis is not None:
                world_axis = self._transform_axis_world(axis)
                distance = world_delta.dot(world_axis)
                if snap:
                    distance = round(distance * 10.0) / 10.0
                world_delta = world_axis * distance
            local_delta = (
                self._transform_cage_inverse.to_3x3() @ world_delta)
            if snap and axis is None:
                local_delta = Vector(tuple(
                    round(component * 10.0) / 10.0
                    for component in local_delta))
            values = {
                index: point + local_delta * weights.get(index, 0.0)
                for index, point in self._transform_initial_points.items()
            }
        elif mode == "TANGENT_SLIDE":
            slide_axis = self._select_tangent_slide_axis(
                context, current_mouse)
            world_axes = getattr(self, "_transform_slide_world_axes", {})
            tangent_fields = getattr(
                self, "_transform_slide_world_tangent_fields", {})
            world_axis = world_axes.get(slide_axis)
            distance = (
                self._tangent_slide_distance(
                    current_mouse, world_axis=world_axis) * precise
                if world_axis is not None else 0.0)
            if snap:
                distance = round(distance * 10.0) / 10.0
            base_points = getattr(self, "_transform_slide_base_points", {})
            tangents = tangent_fields.get(slide_axis, {})
            fallback = (
                world_axis if world_axis is not None else
                getattr(
                    self, "_transform_slide_world_axis", (0.0, 1.0, 0.0)))
            values = ffd_tangent_slide_values(
                base_points,
                {
                    index: tangents.get(index, fallback)
                    for index in base_points
                },
                self._transform_cage_inverse,
                distance,
                weights,
            )
        elif mode == "ROTATE":
            center = view3d_utils.location_3d_to_region_2d(
                region, region_data, self._transform_pivot_world)
            if center is None:
                return False
            initial = self._transform_initial_mouse - Vector(center)
            current = current_mouse - Vector(center)
            if initial.length <= EPSILON or current.length <= EPSILON:
                return False
            angle = (
                math.atan2(current.y, current.x) -
                math.atan2(initial.y, initial.x)) * precise
            if snap:
                step = math.radians(5.0)
                angle = round(angle / step) * step
            if axis is None:
                axis_world = (
                    region_data.view_matrix.inverted_safe().to_3x3() @
                    Vector((0.0, 0.0, 1.0)))
                axis_world.normalize()
            else:
                axis_world = self._transform_axis_world(axis)
            for index, point in self._transform_initial_points.items():
                world = self._transform_cage_matrix @ point
                weight = weights.get(index, 0.0)
                if weight <= EPSILON:
                    values[index] = point.copy()
                    continue
                weighted_rotation = Quaternion(axis_world, angle * weight)
                transformed = (
                    self._transform_pivot_world +
                    weighted_rotation @ (world - self._transform_pivot_world))
                values[index] = self._transform_cage_inverse @ transformed
        else:
            center = view3d_utils.location_3d_to_region_2d(
                region, region_data, self._transform_pivot_world)
            if center is None:
                return False
            center = Vector(center)
            initial_distance = max(
                (self._transform_initial_mouse - center).length, 10.0)
            factor = max((current_mouse - center).length / initial_distance, 0.001)
            factor = 1.0 + (factor - 1.0) * precise
            if snap:
                factor = max(round(factor * 10.0) / 10.0, 0.001)
            for index, point in self._transform_initial_points.items():
                relative = point - self._transform_pivot_local
                weight = weights.get(index, 0.0)
                weighted_factor = 1.0 + (factor - 1.0) * weight
                if axis is None:
                    relative *= weighted_factor
                elif str(getattr(
                        self, "_transform_axis_space", "GLOBAL")) == "GLOBAL":
                    world = self._transform_cage_matrix @ point
                    world_relative = world - self._transform_pivot_world
                    axis_world = self._transform_axis_world(axis)
                    transformed = (
                        world + axis_world * world_relative.dot(axis_world) *
                        (weighted_factor - 1.0))
                    values[index] = self._transform_cage_inverse @ transformed
                    continue
                else:
                    relative[axis] *= weighted_factor
                values[index] = self._transform_pivot_local + relative
        values = ffd_symmetry_transform_values(
            properties,
            self._transform_initial_points,
            values,
            driver_index=getattr(self, "_transform_driver_index", None),
        )
        return self._write_transform_points(context, properties, values)

    def _remove_draw_handler(self):
        handler = getattr(self, "_draw_handler", None)
        if handler is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(handler, "WINDOW")
            except (ReferenceError, RuntimeError, TypeError):
                pass
            try:
                _FFD_DRAW_HANDLERS.remove(handler)
            except ValueError:
                pass
            self._draw_handler = None

    def _restore_pre_edit_object_selection(self, context):
        """Restore object selection after a temporary FFD box picker exits."""
        if not bool(getattr(self, "_restore_pre_edit_selection", False)):
            return False
        self._restore_pre_edit_selection = False
        selected_names = tuple(getattr(
            self, "_pre_edit_selected_names", ()))
        active_name = str(getattr(self, "_pre_edit_active_name", ""))
        try:
            for selected in tuple(getattr(context, "selected_objects", ())):
                selected.select_set(False)
            restored = []
            for name in selected_names:
                obj = bpy.data.objects.get(name)
                if obj is not None:
                    obj.select_set(True)
                    restored.append(obj)
            active = bpy.data.objects.get(active_name)
            if active is None or active not in restored:
                active = restored[0] if restored else None
            if active is not None:
                context.view_layer.objects.active = active
            return True
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            return False

    def _finish_modal(self, context, *, restore_target=True):
        if bool(getattr(self, "_ffd_modal_finished", False)):
            return
        controller = self._controller()
        target = find_target(controller) if controller is not None else None
        properties = (
            getattr(controller, "sdh_cage_deform", None)
            if controller is not None else None)
        if getattr(self, "_state", "") == "TRANSFORM" and properties is not None:
            self._finish_transform(context, properties, cancel=True)
        else:
            _undo.finish(self, cancel=True)
        self._ffd_modal_finished = True
        if controller is not None:
            clear_ffd_hover_entity(controller)
            try:
                controller.sdh_cage_deform.ffd_edit_mode_active = False
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                pass
        self._remove_draw_handler()
        area = getattr(self, "_area", None) or getattr(context, "area", None)
        if area is not None:
            area.header_text_set(None)
            area.tag_redraw()
        try:
            context.window.cursor_modal_restore()
        except (AttributeError, RuntimeError):
            pass
        # FFD keys are stored on the controller. Once point editing ends,
        # return object-level focus to the controlled target and let the
        # normal display pass hide the helper again.
        restored_pre_edit_selection = self._restore_pre_edit_object_selection(context)
        if restore_target and not restored_pre_edit_selection and target is not None:
            _activate(context, target)
        refresh_controller_display(context)
        try:
            _FFD_MODAL_OPERATORS.remove(self)
        except ValueError:
            pass

    def _draw_box(self):
        try:
            state = getattr(self, "_state", "")
        except (ReferenceError, RuntimeError, TypeError):
            return
        if state not in {"DRAGGING", "TRANSFORM"}:
            return
        try:
            import gpu
            from gpu_extras.batch import batch_for_shader
            shader = gpu.shader.from_builtin("UNIFORM_COLOR")
            gpu.state.blend_set("ALPHA")
            shader.bind()
            if state == "DRAGGING":
                x0, y0 = self._start
                x1, y1 = self._end
                corners = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
                fill = (
                    corners[0], corners[1], corners[2],
                    corners[0], corners[2], corners[3],
                )
                border = (
                    corners[0], corners[1], corners[1], corners[2],
                    corners[2], corners[3], corners[3], corners[0],
                )
                color = {
                    "ADD": (0.18, 0.92, 0.42),
                    "SUBTRACT": (1.0, 0.28, 0.22),
                }.get(
                    getattr(self, "_selection_mode", "SET"),
                    (0.12, 0.72, 1.0),
                )
                shader.uniform_float("color", (*color, 0.16))
                batch_for_shader(shader, "TRIS", {"pos": fill}).draw(shader)
                shader.uniform_float("color", (*color, 0.95))
                gpu.state.line_width_set(1.5)
                batch_for_shader(shader, "LINES", {"pos": border}).draw(shader)
            elif self._proportional_enabled(bpy.context):
                from bpy_extras import view3d_utils
                region = getattr(self, "_window_region", None)
                region_data = getattr(self, "_region_data", None)
                if region is not None and region_data is not None:
                    center = view3d_utils.location_3d_to_region_2d(
                        region, region_data,
                        getattr(self, "_transform_pivot_world", Vector()),
                    )
                    view_right = (
                        region_data.view_matrix.inverted_safe().to_3x3() @
                        Vector((1.0, 0.0, 0.0)))
                    if center is not None and view_right.length > EPSILON:
                        view_right.normalize()
                        edge = view3d_utils.location_3d_to_region_2d(
                            region, region_data,
                            getattr(self, "_transform_pivot_world", Vector()) +
                            view_right * float(getattr(
                                self, "_proportional_radius", 0.0)),
                        )
                        if edge is not None:
                            radius = max((Vector(edge) - Vector(center)).length, 2.0)
                            circle = tuple(
                                (
                                    float(center.x) + math.cos(
                                        math.tau * index / 64.0) * radius,
                                    float(center.y) + math.sin(
                                        math.tau * index / 64.0) * radius,
                                )
                                for index in range(65)
                            )
                            shader.uniform_float("color", (0.95, 0.68, 0.12, 0.85))
                            gpu.state.line_width_set(1.5)
                            batch_for_shader(
                                shader, "LINE_STRIP", {"pos": circle}).draw(shader)
        except (ImportError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            pass
        finally:
            try:
                import gpu
                gpu.state.line_width_set(1.0)
                gpu.state.blend_set("NONE")
            except (ImportError, RuntimeError):
                pass

    def _selection_for_controller(self, context, event, controller):
        from bpy_extras import view3d_utils

        if controller is None:
            return None
        target = find_target(controller)
        modifier = find_modifier(target, controller) if target is not None else None
        if target is None or modifier is None:
            return None
        properties = controller.sdh_cage_deform
        ensure_ffd_point_collection(properties)
        region = getattr(self, "_window_region", None)
        region_data = getattr(self, "_region_data", None)
        if region is None or region_data is None:
            return None
        mouse = Vector(self._region_position(region, event))
        try:
            ui_scale = float(context.preferences.system.ui_scale)
        except (AttributeError, TypeError, ValueError):
            ui_scale = 1.0
        hit_radius = max(10.0 * ui_scale, 8.0)
        projected_points = {}

        def projected(index):
            if index not in projected_points:
                world = self._point_world(
                    target, controller, properties, index)
                screen = view3d_utils.location_3d_to_region_2d(
                    region, region_data, world)
                if screen is None:
                    projected_points[index] = None
                else:
                    try:
                        depth = -float((region_data.view_matrix @ world).z)
                    except (AttributeError, RuntimeError, TypeError, ValueError):
                        depth = None
                    projected_points[index] = (
                        float(screen.x), float(screen.y), depth)
            return projected_points[index]

        preferences = get_pref()
        return ffd_screen_selection_entity(
            properties,
            projected,
            mouse,
            line_ratio=float(getattr(
                preferences, "ffd_line_handle_length", 0.60)),
            face_ratio=float(getattr(
                preferences, "ffd_face_handle_size", 0.35)),
            point_radius=hit_radius,
            line_radius=max(8.0 * ui_scale, 6.0),
            face_margin=max(4.0 * ui_scale, 3.0),
        )

    def _selection_at_event(self, context, event):
        return self._selection_for_controller(
            context, event, self._controller())

    def _visible_other_ffd_point_selection(
            self, context, event, target, controller):
        """Hit only the eight point Gizmos actually drawn for inactive FFDs."""
        try:
            from bpy_extras import view3d_utils
            properties = controller.sdh_cage_deform
            ensure_ffd_point_collection(properties)
            region = self._window_region
            region_data = self._region_data
            mouse = Vector(self._region_position(region, event))
            ui_scale = float(context.preferences.system.ui_scale)
            visible = set(ffd_visible_indices(properties))
        except (AttributeError, ImportError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            return None
        hit_radius = max(10.0 * ui_scale, 8.0)
        candidates = []
        for index in ffd_grid_corner_indices(properties):
            if index not in visible:
                continue
            world = self._point_world(target, controller, properties, index)
            screen = view3d_utils.location_3d_to_region_2d(
                region, region_data, world)
            if screen is None:
                continue
            distance = (Vector(screen) - mouse).length
            if distance > hit_radius:
                continue
            try:
                depth = -float((region_data.view_matrix @ world).z)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                depth = math.inf
            candidates.append((distance, depth, index))
        if not candidates:
            return None
        return min(candidates)[2], "POINT", "POINT"

    def _other_ffd_selection_at_event(self, context, event):
        """Return a visible inactive FFD stage and its picked entity."""
        current = self._controller()
        target = find_target(current) if current is not None else None
        current_properties = getattr(current, "sdh_cage_deform", None)
        if (
                target is None or current_properties is None or
                not bool(getattr(
                    current_properties, "show_other_cages", False))
        ):
            return None
        for modifier in cage_modifiers(target):
            controller = find_controller(target, modifier)
            properties = getattr(controller, "sdh_cage_deform", None)
            if (
                    controller is None or _same_rna_value(controller, current) or
                    not bool(getattr(modifier, "show_viewport", True)) or
                    properties is None or
                    str(getattr(properties, "cage_type", "")) != "FFD" or
                    not bool(getattr(properties, "show_cage", True))
            ):
                continue
            selection = self._visible_other_ffd_point_selection(
                context, event, target, controller)
            if selection is not None:
                return modifier, controller, selection
        return None

    def _switch_ffd_stage_from_event(
            self, context, event, modifier, controller, selection):
        """Finish this editor and continue the same press on another FFD."""
        target = find_target(controller)
        if target is None or modifier is None:
            return False
        anchor, selection_mode, selection_axis = selection
        target.modifiers.active = modifier
        self._finish_modal(context, restore_target=False)
        # The operator poll resolves the active cage through the controlled
        # object. Make that target active before invoking the replacement
        # modal; its invoke callback then selects the requested FFD controller.
        _activate(context, target)
        try:
            result = bpy.ops.sdh.box_select_ffd_points(
                "INVOKE_DEFAULT",
                controller_name=controller.name,
                toggle=False,
                start_drag=True,
                start_anchor=int(anchor),
                start_selection_mode=str(selection_mode),
                start_selection_axis=str(selection_axis),
                start_mouse_region_x=int(event.mouse_region_x),
                start_mouse_region_y=int(event.mouse_region_y),
                start_extend=bool(getattr(event, "shift", False)),
            )
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            return False
        return "RUNNING_MODAL" in result

    def _point_at_event(self, context, event):
        selection = self._selection_at_event(context, event)
        return selection[0] if selection is not None else None

    def _over_other_gizmo(
            self, context, event, controller=None, *, include_picker=False):
        """Hit-test the active cage's non-FFD handles before box selection.

        The FFD edit modal owns blank-space box selection, but the regular
        cage handles still need to receive their own Gizmo modal events. A
        lightweight screen-space test avoids consuming those clicks while
        keeping the FFD point and blank-space behavior unchanged.
        """
        if controller is None:
            controller = self._controller()
        if controller is None:
            return False
        target = find_target(controller)
        if target is None:
            return False
        properties = getattr(controller, "sdh_cage_deform", None)
        if properties is None:
            return False
        region = getattr(self, "_window_region", None)
        region_data = getattr(self, "_region_data", None)
        if region is None or region_data is None:
            return False
        try:
            from bpy_extras import view3d_utils
            from . import gizmos as gizmo_module
            mouse = Vector(self._region_position(region, event))
            ui_scale = float(context.preferences.system.ui_scale)
        except (AttributeError, ImportError, RuntimeError, TypeError, ValueError):
            return False

        # Use the public active-layer resolver here.  The old private helper
        # was removed when ordered/muted deformation layers were introduced;
        # leaving this modal-only call behind caused FFD point clicks to raise
        # a NameError before the point selection could continue.
        enabled_types = set(active_deform_types(properties))
        anchors = []
        for deform_type in ("BEND", "TWIST", "TAPER", "STRETCH", "SHEAR"):
            if deform_type not in enabled_types:
                continue
            try:
                world = gizmo_module.parameter_handle_world(
                    context, target, controller, deform_type, separate=True)
            except (AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError):
                continue
            # The twist ring is larger than the arrow/face handles. Keeping a
            # generous hit radius preserves its drag area after cage bending.
            radius = 58.0 if deform_type == "TWIST" else 30.0
            anchors.append((world, radius * ui_scale))

        if "BEND" in enabled_types:
            if bool(getattr(properties, "show_direction_handle", False)):
                try:
                    anchors.append((
                        gizmo_module.bend_direction_handle_world(
                            target, controller, context),
                        72.0 * ui_scale,
                    ))
                except (AttributeError, ReferenceError, RuntimeError, TypeError,
                        ValueError):
                    pass
            if bool(getattr(properties, "show_axis_gizmo", False)):
                # Bend trend arrows are distributed around the six cage faces;
                # use their exact matrices so all visible directions remain
                # clickable while this modal is active.
                for alignment in (
                        "POS_X", "NEG_X", "POS_Y", "NEG_Y", "POS_Z", "NEG_Z"):
                    for variant in (0, 1):
                        try:
                            matrix, _scale, _bounds = (
                                gizmo_module.bend_trend_handle_matrix(
                                    target, alignment, variant,
                                    controller=controller))
                            anchors.append((matrix.translation, 34.0 * ui_scale))
                        except (AttributeError, ReferenceError, RuntimeError,
                                TypeError, ValueError):
                            break
        if bool(getattr(properties, "show_axis_gizmo", False)) and (
                "BEND" not in enabled_types):
            for alignment in (
                    "POS_X", "NEG_X", "POS_Y", "NEG_Y", "POS_Z", "NEG_Z"):
                try:
                    anchors.append((
                        gizmo_module.cage_axis_handle_world(
                            target, controller, alignment, context),
                        34.0 * ui_scale,
                    ))
                except (AttributeError, ReferenceError, RuntimeError, TypeError,
                        ValueError):
                    pass

        if bool(getattr(properties, "show_end_handles", False)):
            for side in ("TOP", "BOTTOM"):
                try:
                    anchors.append((
                        end_shape_handle_world(
                            target, controller, side),
                        30.0 * ui_scale,
                    ))
                except (AttributeError, ReferenceError, RuntimeError, TypeError,
                        ValueError):
                    pass
        if bool(getattr(properties, "show_boundary_handles", False)):
            for side in ("TOP", "BOTTOM"):
                try:
                    anchors.append((
                        cage_boundary_handle_world(
                            target, controller, side),
                        30.0 * ui_scale,
                    ))
                except (AttributeError, ReferenceError, RuntimeError, TypeError,
                        ValueError):
                    pass

        for world, radius in anchors:
            screen = view3d_utils.location_3d_to_region_2d(
                region, region_data, world)
            if screen is not None and (Vector(screen) - mouse).length <= radius:
                return True
        if include_picker:
            try:
                preview_state = gizmo_module.cage_preview_geometry_state(
                    properties)
                vertices = gizmo_module.cage_picker_wire_vertices(
                    properties, preview_state=preview_state)
                matrix = cage_local_matrix(target, controller)
                projected = tuple(
                    view3d_utils.location_3d_to_region_2d(
                        region, region_data, matrix @ Vector(vertex))
                    for vertex in vertices
                )
                hit_radius = max(8.0 * ui_scale, 6.0)
                for index in range(0, len(projected) - 1, 2):
                    start, end = projected[index:index + 2]
                    if (
                            start is not None and end is not None and
                            gizmo_module._screen_segment_distance(
                                mouse, start, end) <= hit_radius
                    ):
                        return True
            except (AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError):
                pass
        return False

    def _other_stage_gizmo_at_event(self, context, event):
        """Return the visible inactive stage whose Gizmo owns this press."""
        current = self._controller()
        target = find_target(current) if current is not None else None
        current_properties = getattr(current, "sdh_cage_deform", None)
        if (
                target is None or current_properties is None or
                not bool(getattr(
                    current_properties, "show_other_cages", False))
        ):
            return None
        for modifier in cage_modifiers(target):
            controller = find_controller(target, modifier)
            properties = getattr(controller, "sdh_cage_deform", None)
            if (
                    controller is None or _same_rna_value(controller, current) or
                    not bool(getattr(modifier, "show_viewport", True)) or
                    properties is None or
                    not bool(getattr(properties, "show_cage", True))
            ):
                continue
            if self._over_other_gizmo(
                    context, event, controller, include_picker=True):
                return modifier, controller
        return None

    def _apply_selection(self, context):
        from bpy_extras import view3d_utils

        controller = self._controller()
        if controller is None:
            return False
        target = find_target(controller)
        modifier = find_modifier(target, controller) if target is not None else None
        if target is None or modifier is None:
            return False
        properties = controller.sdh_cage_deform
        ensure_ffd_point_collection(properties)
        region = getattr(self, "_window_region", None)
        region_data = getattr(self, "_region_data", None)
        if region is None or region_data is None:
            return False
        x0, y0 = self._start
        x1, y1 = self._end
        left, right = sorted((x0, x1))
        bottom, top = sorted((y0, y1))
        projected = {}

        def project_point(index):
            if index not in projected:
                world = self._point_world(
                    target, controller, properties, index)
                screen = view3d_utils.location_3d_to_region_2d(
                    region, region_data, world)
                if screen is None:
                    projected[index] = None
                else:
                    try:
                        depth = -float((region_data.view_matrix @ world).z)
                    except (AttributeError, RuntimeError, TypeError, ValueError):
                        depth = None
                    projected[index] = (
                        float(screen.x), float(screen.y), depth)
            return projected[index]

        preferences = get_pref()
        boxed, boxed_active, _boxed_mode = ffd_box_selection_indices(
            properties,
            project_point,
            (left, right, bottom, top),
            line_ratio=float(getattr(
                preferences, "ffd_line_handle_length", 0.60)),
            face_ratio=float(getattr(
                preferences, "ffd_face_handle_size", 0.35)),
        )
        boxed = ffd_symmetry_expand_indices(properties, boxed)
        self._last_boxed_indices = tuple(sorted(boxed))
        # Before the persistent editor has started, a box that misses every
        # FFD controller should leave the existing point selection untouched
        # and return to normal viewport interaction.  Once in FFD edit mode,
        # the established behavior remains: a blank SET box clears selection.
        if bool(getattr(self, "_pre_edit_box_select", False)) and not boxed:
            return True
        current = {
            index for index, point in enumerate(properties.ffd_points)
            if point.selected
        }
        mode = getattr(self, "_selection_mode", "SET")
        selected = ffd_box_selection_update(current, boxed, mode)
        active = (
            boxed_active if boxed_active in selected else
            min(selected) if selected else None)
        ffd_set_selection(properties, selected, active=active)
        return True

    def invoke(self, context, _event):
        if not tuple(getattr(context, "selected_objects", ()) or ()):
            _native_box_select_fallback(context, _event)
            refresh_controller_display(context, force=True)
            return {"FINISHED"}
        controller = None
        requested_name = str(getattr(self, "controller_name", ""))
        if requested_name:
            try:
                controller = bpy.data.objects.get(requested_name)
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                controller = None
        if controller is None:
            controller = resolve_context_deform(context)[2]
        window_region = next(
            (region for region in context.area.regions
             if region.type == "WINDOW"), None)
        if (
                controller is None or window_region is None or
                str(getattr(controller.sdh_cage_deform, "cage_type", "")) !=
                "FFD"
        ):
            return {"CANCELLED"}
        properties = controller.sdh_cage_deform
        if bool(getattr(properties, "ffd_native_edit_mode_active", False)):
            try:
                from .ffd_native_edit import finish_native_edit_sessions
                finish_native_edit_sessions(context, restore_target=True)
            except (ImportError, ReferenceError, RuntimeError, TypeError):
                return {"CANCELLED"}
        if (
                bool(getattr(properties, "ffd_edit_mode_active", False)) and
                not _ffd_edit_session_live(controller)
        ):
            # Undo and saved files can restore the RNA flag, but Blender never
            # restores Python modal instances. Treat that state as inactive so
            # the first click can start a fresh editor without reloading.
            properties.ffd_edit_mode_active = False
            clear_ffd_hover_entity(controller)
        if bool(getattr(properties, "ffd_edit_mode_active", False)):
            if bool(getattr(self, "toggle", True)):
                finished = finish_ffd_edit_sessions(
                    context, restore_target=True)
                if not finished:
                    properties.ffd_edit_mode_active = False
                    target = find_target(controller)
                    if target is not None:
                        _activate(context, target)
                    refresh_controller_display(context)
                if context.area:
                    context.area.tag_redraw()
                return {"FINISHED"}
            return {"CANCELLED"}
        if not ffd_handles_enabled():
            self.report({"INFO"}, iface_(
                "Enable FFD handles in the add-on preferences first"))
            return {"CANCELLED"}
        target = find_target(controller)
        modifier = find_modifier(
            target, controller) if target is not None else None
        if target is None or modifier is None:
            return {"CANCELLED"}
        # Clicking a control on an inactive FFD is also a stage switch. Keep
        # the active modifier aligned with the modal owner so the N-panel and
        # active/inactive cage drawing agree from the first frame.
        try:
            target.modifiers.active = modifier
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            return {"CANCELLED"}
        # Once FFD editing is requested explicitly, keep its scoped Workspace
        # Tool active. Subsequent blank drags can re-enter the editor without
        # modifying Blender's active keyconfig or built-in Select Box tool.
        activate_cage_workspace_tool(context, "FFD")
        ensure_ffd_point_collection(properties)
        # A viewport CLICK_DRAG or the standard B shortcut starts as a
        # short-lived box picker. It only becomes a persistent FFD edit session
        # after the rectangle hits a visible point, line, or face controller.
        self._pre_edit_box_select = bool(
            getattr(self, "start_box_select", False) or
            getattr(self, "arm_box_select", False))
        self._box_select_armed = bool(getattr(self, "arm_box_select", False))
        self._restore_pre_edit_selection = self._pre_edit_box_select
        self._pre_edit_selected_names = tuple(
            obj.name for obj in getattr(context, "selected_objects", ())
        )
        view_layer = getattr(context, "view_layer", None)
        active_object = getattr(getattr(view_layer, "objects", None), "active", None)
        self._pre_edit_active_name = str(getattr(active_object, "name", ""))
        # Keep the target/controller pair selected while the temporary picker
        # is alive. Blender otherwise rejects a pre-edit modal before it sees
        # the first pointer event in some viewport/keymap configurations.
        _activate_ffd_edit_selection(context, target, controller)
        if not self._pre_edit_box_select:
            properties.ffd_edit_mode_active = True
        self._ffd_modal_finished = False
        self._controller_name = controller.name
        self._window_region = window_region
        self._region_data = getattr(
            getattr(context, "space_data", None), "region_3d", None)
        self._area = context.area
        self._initial_pointer_selection_guard = bool(
            getattr(self, "start_drag", False))
        self._state = "BOX_READY" if self._box_select_armed else "WAITING"
        self._start = (0.0, 0.0)
        self._end = (0.0, 0.0)
        self._selection_mode = "SET"
        self._last_boxed_indices = ()
        self._last_blank_click_time = -1.0
        self._last_blank_click_position = (0.0, 0.0)
        self._proportional_radius = math.nan
        self._last_mouse_position = (
            getattr(_event, "mouse_x", 0.0),
            getattr(_event, "mouse_y", 0.0),
        )
        self._draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            _safe_ffd_box_draw, (self,), "WINDOW", "POST_PIXEL")
        _FFD_DRAW_HANDLERS.append(self._draw_handler)
        if self not in _FFD_MODAL_OPERATORS:
            _FFD_MODAL_OPERATORS.append(self)
        try:
            context.window.cursor_modal_set("CROSSHAIR")
        except (AttributeError, RuntimeError):
            pass
        if bool(getattr(self, "start_box_select", False)):
            press_x = getattr(_event, "mouse_prev_press_x", None)
            press_y = getattr(_event, "mouse_prev_press_y", None)
            if press_x is None or press_y is None:
                press_x = window_region.x + int(getattr(
                    _event, "mouse_region_x", 0))
                press_y = window_region.y + int(getattr(
                    _event, "mouse_region_y", 0))
            self._start = (
                float(press_x - window_region.x),
                float(press_y - window_region.y),
            )
            self._end = self._region_position(window_region, _event)
            self._selection_mode = (
                "SUBTRACT" if bool(getattr(_event, "ctrl", False)) else
                "ADD" if bool(getattr(_event, "shift", False)) else "SET")
            self._state = "DRAGGING"
        elif bool(getattr(self, "start_drag", False)):
            self._begin_pointer_transform(
                context,
                properties,
                anchor=int(getattr(self, "start_anchor", -1)),
                selection_mode=str(getattr(
                    self, "start_selection_mode", "POINT")),
                selection_axis=str(getattr(
                    self, "start_selection_axis", "POINT")),
                extend=bool(getattr(self, "start_extend", False)),
                initial_mouse=(
                    int(getattr(self, "start_mouse_region_x", 0)),
                    int(getattr(self, "start_mouse_region_y", 0)),
                ),
            )
        self._set_header(context)
        refresh_controller_display(context)
        context.window_manager.modal_handler_add(self)
        if bool(getattr(self, "start_drag", False)):
            # Blender completes the inactive Gizmo's native selection after
            # this nested modal has started. Defer one target restoration pass
            # so the late result cannot blank the cage stack between events.
            _queue_stage_selection_restore(target, modifier)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        controller = self._controller()
        properties = (
            getattr(controller, "sdh_cage_deform", None)
            if controller is not None else None)
        pre_edit_box_select = bool(getattr(self, "_pre_edit_box_select", False))
        if (
                properties is None or
                (
                    not bool(getattr(properties, "ffd_edit_mode_active", False)) and
                    not pre_edit_box_select
                ) or
                str(getattr(properties, "cage_type", "")) != "FFD" or
                not ffd_handles_enabled()
        ):
            self._finish_modal(context)
            return {"FINISHED"}
        target = find_target(controller)
        selected_objects = tuple(
            getattr(context, "selected_objects", ()) or ())
        if not selected_objects:
            # Blender can apply a late native object-pick result after the
            # Workspace Tool has already started the first point drag. Keep
            # that one press-drag-release transaction authoritative; the guard
            # is cleared as soon as its transform finishes. Later genuine
            # deselection still exits the editor and restores native tools.
            guarded = bool(getattr(
                self, "_initial_pointer_selection_guard", False))
            if not (
                    guarded and target is not None and
                    _activate_ffd_edit_selection(
                        context, target, controller)
            ):
                self._finish_modal(context, restore_target=False)
                activate_cage_workspace_tool(context, "")
                refresh_controller_display(context, force=True)
                return {"FINISHED"}
            refresh_controller_display(context, force=True)
            selected_objects = tuple(
                getattr(context, "selected_objects", ()) or ())
        region = getattr(self, "_window_region", None)
        if region is None:
            self._finish_modal(context)
            return {"CANCELLED"}
        # Blender can apply its regular object-selection result after a FFD
        # Gizmo's invoke callback, leaving only the hidden controller selected.
        # Keep the edit-session pair authoritative for the lifetime of this
        # modal so the target-dependent GizmoGroup remains visible.
        if (
                target is not None and
                (target not in selected_objects or
                 controller not in selected_objects)
        ):
            if _activate_ffd_edit_selection(context, target, controller):
                refresh_controller_display(context, force=True)
        # Blender emits an internal TWEAK_L/TWEAK_R event while a Gizmo is
        # being dragged. Blender 5.2 exposes that event's numeric type without
        # a matching Python enum, so reading ``event.type`` produces repeated
        # RNA warnings. It is only an intermediate pass-through event; the
        # normal PRESS/MOUSEMOVE/RELEASE events still drive this modal.
        try:
            if getattr(event, "value", None) == "ANY":
                return {"PASS_THROUGH"}
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
        if hasattr(event, "mouse_x") and hasattr(event, "mouse_y"):
            self._last_mouse_position = (event.mouse_x, event.mouse_y)
        if self._state == "WAITING" and event.type in {
                "MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            hovered = None
            if (
                    self._inside_region(region, event) and
                    not self._inside_ui_region(context, event)
            ):
                hovered = self._selection_at_event(context, event)
            set_ffd_hover_entity(controller, hovered)
            if self._area is not None:
                self._area.tag_redraw()
        # Keep all events over Blender's UI available to the N-panel and its
        # property editors. This includes keyboard input after a numeric
        # field receives focus; otherwise modal G/R/S/I/A shortcuts steal it.
        if self._inside_ui_region(context, event):
            return {"PASS_THROUGH"}
        if (
                self._state != "TRANSFORM" and
                event.type in self._MOUSE_EVENTS and
                not self._inside_region(region, event)
        ):
            return {"PASS_THROUGH"}
        if self._state == "TRANSFORM":
            if event.type in {
                    "WHEELUPMOUSE", "WHEELDOWNMOUSE",
                    "WHEELINMOUSE", "WHEELOUTMOUSE",
            } and self._proportional_enabled(context):
                factor = (
                    0.8 if event.type in {"WHEELUPMOUSE", "WHEELINMOUSE"}
                    else 1.25)
                try:
                    current_radius = float(getattr(
                        self, "_proportional_radius", EPSILON))
                except (TypeError, ValueError):
                    current_radius = EPSILON
                self._proportional_radius = max(
                    current_radius * factor, EPSILON)
                settings = self._tool_settings(context)
                # Keep Blender's own proportional radius in sync so the next
                # FFD transform and the native transform tools start with the
                # same influence size.
                if settings is not None and hasattr(settings, "proportional_size"):
                    try:
                        settings.proportional_size = self._proportional_radius
                    except (AttributeError, RuntimeError, TypeError, ValueError):
                        pass
                self._apply_transform(context, event, properties)
                self._set_header(context)
                return {"RUNNING_MODAL"}
            if (
                    event.type == "O" and event.value == "PRESS" and
                    not bool(getattr(event, "shift", False))
            ):
                settings = self._tool_settings(context)
                if settings is not None:
                    # FFD edit runs in Object Mode, where Blender's toolbar
                    # uses ``use_proportional_edit_objects``.  Keep the edit
                    # mode property as a fallback for older versions and
                    # synthetic contexts used by regression tests.
                    object_mode = str(getattr(
                        getattr(context, "object", None), "mode", "OBJECT")) == "OBJECT"
                    property_name = (
                        "use_proportional_edit_objects"
                        if object_mode and hasattr(
                            settings, "use_proportional_edit_objects")
                        else "use_proportional_edit"
                    )
                    if hasattr(settings, property_name):
                        setattr(settings, property_name, not bool(
                            getattr(settings, property_name, False)))
                self._apply_transform(context, event, properties)
                self._set_header(context)
                return {"RUNNING_MODAL"}
            if (
                    event.type in {"ESC", "RIGHTMOUSE"} and
                    event.value == "PRESS"
            ):
                self._finish_transform(context, properties, cancel=True)
                return {"RUNNING_MODAL"}
            if (
                    event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER", "SPACE"} and
                    event.value == "PRESS"
            ):
                self._finish_transform(context, properties)
                return {"RUNNING_MODAL"}
            if (
                    event.type == "LEFTMOUSE" and
                    event.value == "RELEASE"
            ):
                self._finish_transform(context, properties)
                return {"RUNNING_MODAL"}
            if (
                    event.type == "G" and event.value == "PRESS" and
                    getattr(self, "_transform_mode", "") in {
                        "MOVE", "TANGENT_SLIDE"}
            ):
                if getattr(self, "_transform_mode", "") == "MOVE":
                    self._begin_tangent_slide(
                        context, event, properties)
                else:
                    self._begin_transform(
                        context, event, "MOVE",
                        initial_mouse=self._region_position(region, event))
                return {"RUNNING_MODAL"}
            if event.type in {"X", "Y", "Z"} and event.value == "PRESS":
                if getattr(self, "_transform_mode", "") == "TANGENT_SLIDE":
                    return {"RUNNING_MODAL"}
                requested_axis = {"X": 0, "Y": 1, "Z": 2}[event.type]
                self._transform_axis, self._transform_axis_space = (
                    ffd_transform_axis_state(
                        self._transform_axis,
                        getattr(self, "_transform_axis_space", "GLOBAL"),
                        requested_axis,
                    ))
                self._apply_transform(context, event, properties)
                self._set_header(context)
                return {"RUNNING_MODAL"}
            if event.type == "MOUSEMOVE":
                self._apply_transform(context, event, properties)
                return {"RUNNING_MODAL"}
            return {"RUNNING_MODAL"}
        # A transform cancel first restores this modal to WAITING. Blender then
        # delivers the matching RELEASE event. Treating that release as a
        # second cancel used to close FFD edit mode immediately after restoring
        # the points. Only a fresh press while already waiting exits the editor.
        if (
                event.type in {"ESC", "RIGHTMOUSE"} and
                event.value == "PRESS"
        ):
            self._finish_modal(context)
            return {"FINISHED"}
        if (
                self._state == "WAITING" and
                event.type == "A" and event.value == "PRESS"
        ):
            visible = tuple(ffd_visible_indices(properties))
            selected = () if bool(event.alt) else visible
            ffd_set_selection(
                properties,
                selected,
                active=min(visible) if visible and selected else None,
            )
            self._set_header(context)
            return {"RUNNING_MODAL"}
        if (
                self._state == "BOX_READY" and
                event.type == "LEFTMOUSE" and event.value == "PRESS" and
                self._inside_region(region, event)
        ):
            position = self._region_position(region, event)
            self._start = position
            self._end = position
            self._selection_mode = (
                "SUBTRACT" if bool(event.ctrl) else
                "ADD" if bool(event.shift) else "SET")
            self._state = "DRAGGING"
            self._set_header(context)
            return {"RUNNING_MODAL"}
        if self._state == "BOX_READY":
            # Blender delivers the shortcut's setup event through the modal
            # before the first pointer press. Returning PASS_THROUGH for that
            # event cancels the operator in some keymap configurations. Keep
            # the picker alive, while retaining ordinary view navigation.
            if event.type in {
                    "MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE",
                    "WHEELINMOUSE", "WHEELOUTMOUSE", "TRACKPADPAN",
                    "TRACKPADZOOM",
            }:
                return {"PASS_THROUGH"}
            return {"RUNNING_MODAL"}
        if (
                self._state == "WAITING" and
                event.type == "I" and event.value == "PRESS"
        ):
            delete = bool(event.alt)
            # Match the panel action: an FFD modal key records the complete
            # active cage stage, not just point offsets. This keeps viewport
            # shortcuts and the explicit Insert Keys button interchangeable.
            count = _keyframe_cage_paths(controller, delete=delete)
            message = (
                "Removed {count} cage keyframe channels" if delete else
                "Inserted {count} cage keyframe channels")
            self.report(
                {"INFO"},
                iface_(message).format(count=count),
            )
            self._set_header(context)
            return {"RUNNING_MODAL"}
        if (
                self._state == "WAITING" and
                event.type == "R" and event.value == "PRESS" and
                bool(event.alt)
        ):
            reset_ffd_offsets(controller, context)
            self._set_header(context)
            return {"RUNNING_MODAL"}
        if (
                self._state == "WAITING" and
                event.type in {"G", "R", "S"} and event.value == "PRESS"
        ):
            mode = {"G": "MOVE", "R": "ROTATE", "S": "SCALE"}[event.type]
            if self._begin_transform(context, event, mode):
                return {"RUNNING_MODAL"}
            return {"PASS_THROUGH"}
        if (
                self._state == "WAITING" and
                event.type == "LEFTMOUSE" and
                event.value == "DOUBLE_CLICK" and
                self._inside_region(region, event)
        ):
            if self._point_at_event(context, event) is None:
                self._finish_modal(context)
                return {"FINISHED"}
            return {"PASS_THROUGH"}
        if (
                self._state == "WAITING" and
                event.type == "LEFTMOUSE" and event.value == "PRESS" and
                self._inside_region(region, event)
        ):
            selection = self._selection_at_event(context, event)
            if selection is not None:
                anchor, selection_mode, selection_axis = selection
                self._begin_pointer_transform(
                    context,
                    properties,
                    anchor=anchor,
                    selection_mode=selection_mode,
                    selection_axis=selection_axis,
                    extend=bool(event.shift),
                    initial_mouse=self._region_position(region, event),
                )
                return {"RUNNING_MODAL"}
            other_ffd = self._other_ffd_selection_at_event(context, event)
            if other_ffd is not None:
                modifier, other_controller, other_selection = other_ffd
                if self._switch_ffd_stage_from_event(
                        context, event, modifier, other_controller,
                        other_selection):
                    return {"FINISHED"}
                return {"RUNNING_MODAL"}
            if self._other_stage_gizmo_at_event(context, event) is not None:
                # End the FFD editor before passing this same mouse press to
                # the inactive stage picker or its regular cage Gizmo.
                self._finish_modal(context, restore_target=False)
                return {"PASS_THROUGH"}
            if self._over_other_gizmo(context, event):
                return {"PASS_THROUGH"}
            position = self._region_position(region, event)
            self._start = position
            self._end = self._start
            self._selection_mode = (
                "SUBTRACT" if bool(event.ctrl) else
                "ADD" if bool(event.shift) else "SET")
            self._state = "DRAGGING"
            self._set_header(context)
            return {"RUNNING_MODAL"}
        if self._state == "DRAGGING" and event.type == "MOUSEMOVE":
            self._end = self._region_position(region, event)
            self._area.tag_redraw()
            return {"RUNNING_MODAL"}
        if (
                self._state == "DRAGGING" and
                event.type == "LEFTMOUSE" and event.value == "RELEASE"
        ):
            self._end = self._region_position(region, event)
            applied = self._apply_selection(context)
            if not applied:
                self._finish_modal(context)
                return {"CANCELLED"}
            if pre_edit_box_select:
                self._pre_edit_box_select = False
                if not bool(getattr(self, "_last_boxed_indices", ())):
                    self._finish_modal(context)
                    return {"CANCELLED"}
                self._restore_pre_edit_selection = False
                properties.ffd_edit_mode_active = True
                target = find_target(controller)
                _activate_ffd_edit_selection(context, target, controller)
                refresh_controller_display(context, force=True)
            double_click, next_time, next_position = (
                _ffd_blank_box_release_state(
                    getattr(self, "_last_blank_click_time", -1.0),
                    getattr(self, "_last_blank_click_position", self._start),
                    self._start,
                    self._end,
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
            # Keep the temporary rectangle alive through Blender's setup and
            # navigation events. Returning PASS_THROUGH here can make a
            # keymap-invoked pre-edit picker terminate before its release.
            return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}

    def cancel(self, context):
        self._finish_modal(context)


class SDH_OT_reset_ffd(Operator):
    bl_idname = "sdh.reset_cage_ffd"
    bl_label = "Reset FFD"
    bl_description = "Return every FFD corner to the undeformed cage"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        return bool(resolve_context_deform(context)[2])

    def execute(self, context):
        controller = resolve_context_deform(context)[2]
        if not reset_ffd_offsets(controller, context):
            return {"CANCELLED"}
        return {"FINISHED"}


# Keyframe channels and animation baking now live in `animation_io`.
# Import mid-file (after every helper above is defined) and re-export the
# stable names so existing scripts, tests, and siblings keep working.
from . import animation_io as _animation_io  # noqa: E402

_CAGE_ANIMATION_GROUP = _animation_io._CAGE_ANIMATION_GROUP
_BAKED_ANIMATION_GROUP = _animation_io._BAKED_ANIMATION_GROUP
_BAKED_ANIMATION_MARKER = _animation_io._BAKED_ANIMATION_MARKER
_BAKED_SOURCE_NAME = _animation_io._BAKED_SOURCE_NAME
_BAKED_FRAME_START = _animation_io._BAKED_FRAME_START
_BAKED_FRAME_END = _animation_io._BAKED_FRAME_END
_BAKED_FRAME_STEP = _animation_io._BAKED_FRAME_STEP
_CAGE_ANIMATED_PROPERTIES = _animation_io._CAGE_ANIMATED_PROPERTIES
_cage_animation_paths = _animation_io._cage_animation_paths
_keyframe_paths = _animation_io._keyframe_paths
_keyframe_ffd_points = _animation_io._keyframe_ffd_points
_keyframe_cage_paths = _animation_io._keyframe_cage_paths
_keyframe_layer_paths = _animation_io._keyframe_layer_paths
_bake_frame_samples = _animation_io._bake_frame_samples
_mesh_topology_signature = _animation_io._mesh_topology_signature
_mesh_vertex_coordinates = _animation_io._mesh_vertex_coordinates
_evaluated_mesh_snapshot = _animation_io._evaluated_mesh_snapshot
_iter_baked_action_fcurves = _animation_io._iter_baked_action_fcurves
_linearize_baked_eval_time = _animation_io._linearize_baked_eval_time
_prepare_bake_frame = _animation_io._prepare_bake_frame
bake_cage_animation_to_shape_keys = (
    _animation_io.bake_cage_animation_to_shape_keys)
SDH_OT_insert_cage_keyframes = _animation_io.SDH_OT_insert_cage_keyframes
SDH_OT_delete_cage_keyframes = _animation_io.SDH_OT_delete_cage_keyframes
SDH_OT_bake_cage_animation = _animation_io.SDH_OT_bake_cage_animation


class SDH_OT_select_cage_stage(Operator):
    bl_idname = "sdh.select_cage_stage"
    bl_label = "Select Deformation Stage"
    bl_description = "Make this cage or traditional Simple Deform stage active"
    bl_options = {"INTERNAL"}

    # Panel rows set ``index`` while viewport pickers set ``modifier_uuid``.
    # Keep both routing values transient so Blender cannot carry one surface's
    # target into the other surface's next operator instance.
    index: bpy.props.IntProperty(
        default=-1, min=-1, options={"SKIP_SAVE"})
    modifier_uuid: bpy.props.StringProperty(
        default="", options={"HIDDEN", "SKIP_SAVE"})
    include_legacy: BoolProperty(
        default=False, options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        target = deform_stack_target_from_context(context)
        return bool(target and deform_stack_modifiers(target))

    def execute(self, context):
        target = deform_stack_target_from_context(context)
        if target is None and is_cage_controller(context.object):
            target = find_target(context.object)
        modifiers = (
            deform_stack_modifiers(target)
            if self.include_legacy else cage_modifiers(target))
        modifier = None
        if 0 <= self.index < len(modifiers):
            modifier = modifiers[self.index]
        elif self.index >= 0:
            return {"CANCELLED"}
        elif self.modifier_uuid:
            modifier = next((
                candidate for candidate in modifiers
                if cage_modifier_uuid(candidate) == self.modifier_uuid
            ), None)
        elif modifiers:
            # Preserve the historical no-argument behavior.
            modifier = modifiers[0]
        if modifier is None:
            return {"CANCELLED"}
        finish_ffd_edit_sessions(context, restore_target=False)
        if modifier.type == "SIMPLE_DEFORM":
            try:
                from .curve import (
                    finish_curve_edit_sessions,
                    finish_curve_object_edit_sessions,
                )
                finish_curve_object_edit_sessions(
                    context, restore_target=False)
                finish_curve_edit_sessions(context, restore_target=False)
            except (ImportError, ReferenceError, RuntimeError):
                pass
        target.modifiers.active = modifier
        controller = (
            find_controller(target, modifier)
            if is_cage_modifier(modifier) else None)
        activate_cage_workspace_tool(
            context,
            getattr(
                getattr(controller, "sdh_cage_deform", None),
                "cage_type", ""),
        )
        # Stage selection changes the active custom cage without exposing its
        # implementation Empty. The dedicated cage-transform commands enter
        # the controller when native Move/Rotate/Scale editing is requested.
        # Apply this after changing Workspace Tools because Blender can update
        # selection while rebuilding the tool Gizmo map.
        _activate(context, target)
        if modifier.type == "SIMPLE_DEFORM":
            StageCache.rebuild(context, target)
        refresh_controller_display(context)
        if is_cage_modifier(modifier):
            _queue_stage_selection_restore(target, modifier)
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
        _activate(context, controller)
        refresh_controller_display(context)
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
        refresh_controller_display(context)
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
        _activate(context, controller)
        refresh_controller_display(context)
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
    bl_description = "Target axis used when aligning and fitting the cage"
    bl_options = {"INTERNAL", "UNDO"}

    alignment: EnumProperty(
        items=tuple((identifier, identifier, "") for identifier in (
            "AUTO", "POS_X", "NEG_X", "POS_Y", "NEG_Y", "POS_Z", "NEG_Z")),
        default="POS_Z",
    )
    keep_open: BoolProperty(default=False, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return bool(resolve_context_deform(context)[2])

    def invoke(self, context, event):
        # Match bend-trend selection: a normal click is a one-shot choice,
        # while Ctrl keeps the face controls visible for another selection.
        self.keep_open = bool(event.ctrl)
        return self.execute(context)

    def execute(self, context):
        target, modifier, controller = resolve_context_deform(context)
        if target is None or modifier is None or controller is None:
            return {"CANCELLED"}
        properties = controller.sdh_cage_deform
        redirected_chain = False
        try:
            from . import chain as chain_module
            chain_uuid = chain_module.stage_chain_uuid(modifier)
            chain_mode = chain_module.stage_chain_mode(modifier, "").upper()
            if chain_uuid and chain_mode in {"CHAINED", "CONNECTED"}:
                redirected_chain = bool(chain_module.redirect_chain_frame(
                    target,
                    chain_uuid,
                    modifier,
                    self.alignment,
                    float(properties.bend_direction),
                    context=context,
                    fit=True,
                ))
        except (ImportError, AttributeError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            redirected_chain = False
        if not redirected_chain:
            fit_controller_to_alignment(
                context, target, modifier, controller, self.alignment)
        if not self.keep_open:
            controller.sdh_cage_deform.show_axis_gizmo = False
        if context.area:
            context.area.tag_redraw()
        return {"FINISHED"}


class SDH_OT_set_bend_trend(Operator):
    bl_idname = "sdh.set_bend_trend"
    bl_label = "Set Bend Trend"
    bl_description = (
        "Choose a signed cage axis and one of its two perpendicular bend trends; "
        "hold Ctrl to keep all choices visible"
    )
    bl_options = {"INTERNAL", "UNDO"}

    alignment: EnumProperty(
        items=tuple((identifier, identifier, "") for identifier in (
            "POS_X", "NEG_X", "POS_Y", "NEG_Y", "POS_Z", "NEG_Z")),
        default="POS_Z",
    )
    variant: IntProperty(default=0, min=0, max=1, options={"SKIP_SAVE"})
    direction: FloatProperty(default=0.0, subtype="ANGLE")
    keep_open: BoolProperty(default=False, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        controller = resolve_context_deform(context)[2]
        if controller is None:
            return False
        properties = controller.sdh_cage_deform
        try:
            return "BEND" in set(properties.deform_types)
        except (AttributeError, TypeError, ValueError):
            return properties.deform_type == "BEND"

    def invoke(self, context, event):
        self.keep_open = bool(event.ctrl)
        return self.execute(context)

    def execute(self, context):
        target, modifier, controller = resolve_context_deform(context)
        if target is None or modifier is None or controller is None:
            return {"CANCELLED"}
        properties = controller.sdh_cage_deform
        # Lazy import: bend-trend helpers live with gizmos (avoid cycle).
        from .gizmos import (
            bend_trend_target,
        )
        draw_face = self.alignment
        result_alignment, computed_direction = bend_trend_target(
            draw_face, self.variant, controller=controller)
        # Keep strength sign: cage mode never applies classic Is_Positive flip.
        redirected_chain = False
        # A connected chain must be redirected as one frame operation. If the
        # active stage is not the root, the ordinary reconnect pass would
        # otherwise derive its frame from the unchanged upstream stage and
        # immediately erase the user's trend choice.
        try:
            from . import chain as chain_module
            chain_uuid = chain_module.stage_chain_uuid(modifier)
            chain_mode = chain_module.stage_chain_mode(modifier, "").upper()
            if chain_uuid and chain_mode in {"CHAINED", "CONNECTED"}:
                redirected_chain = bool(chain_module.redirect_chain_frame(
                    target,
                    chain_uuid,
                    modifier,
                    result_alignment,
                    computed_direction,
                    context=context,
                    fit=True,
                ))
        except (ImportError, AttributeError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            redirected_chain = False
        if not redirected_chain:
            fit_controller_to_alignment(
                context,
                target,
                modifier,
                controller,
                result_alignment,
                bend_direction=computed_direction,
            )
        self.direction = computed_direction
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
        source_group = getattr(source_modifier, "node_group", None)
        source_chain_uuid = str(
            source_group.get("_sdh_cage_chain_uuid", "")
        ) if source_group else ""
        source_chain_mode = str(
            source_group.get("_sdh_cage_chain_mode", "")
        ) if source_group else ""
        modifier, controller, _previous = create_deform_stage(
            context, target, name=f"{source_modifier.name} Copy",
            after_modifier=source_modifier)
        _copy_controller_state(controller, source_controller)
        try:
            from .curve import copy_curve_state
            if str(controller.sdh_cage_deform.cage_type) == "CURVE":
                copy_curve_state(
                    target, source_modifier, source_controller,
                    modifier, controller)
                sync_controller(
                    controller, pull_transform=False, sync_mode="push")
        except (AttributeError, ImportError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            pass
        ensure_ffd_companion_order(target)
        if source_chain_uuid:
            try:
                from .chain import (
                    compact_chain,
                    reconnect_chain,
                    set_stage_metadata,
                )
                set_stage_metadata(
                    modifier, controller, source_chain_uuid, 0, 1,
                    source_chain_mode or "CHAINED",
                )
                compact_chain(target, source_chain_uuid)
                if source_chain_mode == "CHAINED":
                    reconnect_chain(target, source_chain_uuid)
            except (ImportError, AttributeError, ReferenceError, RuntimeError):
                pass
        else:
            # create_deform_stage initially fits the new stage to its live
            # input, but copying the source state deliberately overwrites that
            # frame with the previous cage's size and transform. Repeat the
            # same Align & Fit action exposed by the panel after the copy so an
            # ordinary duplicated stage starts on its actual upstream result.
            copied_properties = controller.sdh_cage_deform
            fit_controller_to_alignment(
                context,
                target,
                modifier,
                controller,
                copied_properties.alignment,
            )
        target.modifiers.active = modifier
        _activate(context, controller)
        refresh_controller_display(context)
        return {"FINISHED"}


class SDH_OT_move_cage_deform(Operator):
    bl_idname = "sdh.move_cage_deform"
    bl_label = "Move Deformation Stage"
    bl_description = "Move this deformation earlier or later in the modifier stack"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    index: bpy.props.IntProperty(default=0, min=0)
    include_legacy: BoolProperty(
        default=False, options={"HIDDEN", "SKIP_SAVE"})
    direction: EnumProperty(
        items=(
            ("EARLIER", "Earlier", "Move before the previous deformation stage"),
            ("LATER", "Later", "Move after the next deformation stage"),
        ),
        default="EARLIER",
    )

    @classmethod
    def poll(cls, context):
        target = deform_stack_target_from_context(context)
        return bool(target and len(deform_stack_modifiers(target)) > 1)

    def execute(self, context):
        target = deform_stack_target_from_context(context)
        stages = (
            deform_stack_modifiers(target)
            if self.include_legacy else cage_modifiers(target))
        if not 0 <= self.index < len(stages):
            return {"CANCELLED"}

        modifier = stages[self.index]
        modifier_group = getattr(modifier, "node_group", None)
        chain_uuid = str(
            modifier_group.get("_sdh_cage_chain_uuid", "")
        ) if modifier_group else ""
        chain_mode = str(
            modifier_group.get("_sdh_cage_chain_mode", "")
        ) if modifier_group else ""
        _activate(context, target)
        target.modifiers.active = modifier

        moved_chain_block = False
        if chain_uuid and chain_mode.upper() in {"CHAINED", "CONNECTED"}:
            try:
                from . import chain as chain_module
                chain_module.restore_chain_modifier_order(target, chain_uuid)
                stages = (
                    deform_stack_modifiers(target)
                    if self.include_legacy else cage_modifiers(target))
                chain_members = tuple(
                    stage for stage in stages
                    if chain_module.stage_chain_uuid(stage) == chain_uuid)
                positions = tuple(stages.index(stage) for stage in chain_members)
                boundary = (
                    min(positions) if self.direction == "EARLIER"
                    else max(positions))
                external_index = boundary + (
                    -1 if self.direction == "EARLIER" else 1)
                if not 0 <= external_index < len(stages):
                    self.report(
                        {"WARNING"},
                        iface_("Chained cage segments keep their internal order"),
                    )
                    return {"CANCELLED"}
                neighbor = stages[external_index]
                if chain_module.stage_chain_uuid(neighbor) == chain_uuid:
                    self.report(
                        {"WARNING"},
                        iface_("Chained cage segments keep their internal order"),
                    )
                    return {"CANCELLED"}

                ordered_members = tuple(sorted(
                    chain_members,
                    key=lambda stage: chain_module.stage_chain_index(stage),
                ))
                moving_members = (
                    ordered_members if self.direction == "EARLIER"
                    else tuple(reversed(ordered_members)))
                for member in moving_members:
                    current_index = tuple(target.modifiers).index(member)
                    desired_index = tuple(target.modifiers).index(neighbor)
                    target.modifiers.move(current_index, desired_index)
                ensure_ffd_companion_order(target)
                chain_module.reconnect_chain(target, chain_uuid)
                moved_chain_block = True
            except (ImportError, AttributeError, ReferenceError, RuntimeError,
                    TypeError, ValueError) as error:
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}

        if not moved_chain_block:
            destination = self.index + (
                -1 if self.direction == "EARLIER" else 1)
            if not 0 <= destination < len(stages):
                return {"CANCELLED"}
            neighbor = stages[destination]
            desired_index = tuple(target.modifiers).index(neighbor)
            try:
                bpy.ops.object.modifier_move_to_index(
                    modifier=modifier.name, index=desired_index)
            except RuntimeError as error:
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}
            ensure_ffd_companion_order(target)
            if chain_uuid:
                try:
                    from .chain import compact_chain, reconnect_chain
                    compact_chain(target, chain_uuid)
                    if chain_mode.upper() in {"CHAINED", "CONNECTED"}:
                        reconnect_chain(target, chain_uuid)
                except (ImportError, AttributeError, ReferenceError,
                        RuntimeError):
                    pass
        target.modifiers.active = modifier
        if self.include_legacy:
            _activate(context, target)
        else:
            _activate(context, find_controller(target, modifier) or target)
        if self.include_legacy:
            StageCache.rebuild(context, target)
        controller = (
            find_controller(target, modifier)
            if is_cage_modifier(modifier) else None)
        activate_cage_workspace_tool(
            context,
            getattr(
                getattr(controller, "sdh_cage_deform", None),
                "cage_type", ""),
        )
        refresh_controller_display(context)
        if is_cage_modifier(modifier):
            _queue_stage_selection_restore(target, modifier)
        return {"FINISHED"}


class SDH_OT_remove_cage_deform(Operator):
    bl_idname = "sdh.remove_cage_deform"
    bl_label = "Remove Deformation Stage"
    bl_description = "Remove this deformation stage and any owned controls"
    bl_options = {"REGISTER", "UNDO"}

    index: bpy.props.IntProperty(default=-1, min=-1)
    include_legacy: BoolProperty(
        default=False, options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        target = deform_stack_target_from_context(context)
        return bool(target and deform_stack_modifiers(target))

    def execute(self, context):
        target = deform_stack_target_from_context(context)
        stages = (
            deform_stack_modifiers(target)
            if self.include_legacy else cage_modifiers(target))
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
        if modifier.type == "SIMPLE_DEFORM":
            finish_ffd_edit_sessions(context, restore_target=False)
            try:
                from .curve import (
                    finish_curve_edit_sessions,
                    finish_curve_object_edit_sessions,
                )
                finish_curve_object_edit_sessions(
                    context, restore_target=False)
                finish_curve_edit_sessions(context, restore_target=False)
            except (ImportError, ReferenceError, RuntimeError):
                pass
            if not remove_legacy_simple_deform(target, modifier):
                return {"CANCELLED"}
            remaining = deform_stack_modifiers(target)
            if remaining:
                next_index = min(max(self.index, 0), len(remaining) - 1)
                target.modifiers.active = remaining[next_index]
            StageCache.rebuild(context, target)
            active_stage = getattr(target.modifiers, "active", None)
            active_controller = (
                find_controller(target, active_stage)
                if is_cage_modifier(active_stage) else None)
            activate_cage_workspace_tool(
                context,
                getattr(
                    getattr(active_controller, "sdh_cage_deform", None),
                    "cage_type", ""),
            )
            remove_unused_control_collections()
            refresh_controller_display(context, force=True)
            return {"FINISHED"}
        node_group = getattr(modifier, "node_group", None)
        chain_uuid = str(
            node_group.get("_sdh_cage_chain_uuid", "")
        ) if node_group else ""
        chain_mode = str(
            node_group.get("_sdh_cage_chain_mode", "")
        ) if node_group else ""
        remove_ffd_lattice(target, modifier)
        try:
            from .curve import remove_curve_companions
            remove_curve_companions(target, modifier)
        except (ImportError, ReferenceError, RuntimeError):
            pass
        target.modifiers.remove(modifier)
        if controller and is_cage_controller(controller):
            bpy.data.objects.remove(controller, do_unlink=True)
        if node_group and node_group.users == 0 and node_group.get(MODIFIER_MARKER, False):
            bpy.data.node_groups.remove(node_group)
        remaining = (
            deform_stack_modifiers(target)
            if self.include_legacy else cage_modifiers(target))
        if remaining:
            target.modifiers.active = remaining[min(max(self.index, 0), len(remaining) - 1)]
        remove_unused_control_collections()
        if chain_uuid:
            # An intentional N-panel removal shortens the chain instead of
            # leaving stale indices that would make Reconnect refuse to run.
            try:
                from .chain import compact_chain, reconnect_chain
                live_chain = compact_chain(target, chain_uuid)
                if len(live_chain) >= 2 and chain_mode == "CHAINED":
                    reconnect_chain(target, chain_uuid)
            except (ImportError, AttributeError, ReferenceError, RuntimeError):
                pass
        next_modifier = getattr(target.modifiers, "active", None)
        if self.include_legacy:
            _activate(context, target)
            StageCache.rebuild(context, target)
        else:
            _activate(
                context,
                find_controller(target, next_modifier)
                if is_cage_modifier(next_modifier) else target,
            )
        next_controller = (
            find_controller(target, next_modifier)
            if is_cage_modifier(next_modifier) else None)
        activate_cage_workspace_tool(
            context,
            getattr(
                getattr(next_controller, "sdh_cage_deform", None),
                "cage_type", ""),
        )
        refresh_controller_display(context, force=True)
        return {"FINISHED"}


class SDH_OT_remove_cage_stack(Operator):
    bl_idname = "sdh.remove_cage_stack"
    bl_label = "Remove Deformation Stack"
    bl_description = (
        "Remove every managed cage and traditional Simple Deform stage")
    bl_options = {"REGISTER", "UNDO"}

    include_legacy: BoolProperty(
        default=False, options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        target = deform_stack_target_from_context(context)
        return bool(target and deform_stack_modifiers(target))

    def execute(self, context):
        target = deform_stack_target_from_context(context)
        stages = cage_modifiers(target)
        legacy_stages = tuple(
            modifier for modifier in getattr(target, "modifiers", ())
            if modifier.type == "SIMPLE_DEFORM") if target is not None else ()
        if target is None or not (stages or (self.include_legacy and legacy_stages)):
            return {"CANCELLED"}
        finish_ffd_edit_sessions(context, restore_target=False)
        try:
            from .curve import (
                finish_curve_edit_sessions,
                finish_curve_object_edit_sessions,
            )
            finish_curve_object_edit_sessions(context, restore_target=False)
            finish_curve_edit_sessions(context, restore_target=False)
        except (ImportError, ReferenceError, RuntimeError):
            pass
        _activate(context, target)
        modifier_uuids = {cage_modifier_uuid(modifier) for modifier in stages}
        node_groups = tuple(dict.fromkeys(
            getattr(modifier, "node_group", None) for modifier in stages))
        controllers = tuple(
            obj for obj in bpy.data.objects
            if is_cage_controller(obj) and getattr(obj, "parent", None) == target and
            str(obj.get(MODIFIER_UUID, "")) in modifier_uuids
        )
        for modifier in stages:
            remove_ffd_lattice(target, modifier)
            try:
                from .curve import remove_curve_companions
                remove_curve_companions(target, modifier)
            except (ImportError, ReferenceError, RuntimeError):
                pass
            target.modifiers.remove(modifier)
        for controller in controllers:
            bpy.data.objects.remove(controller, do_unlink=True)
        if self.include_legacy:
            for legacy_modifier in legacy_stages:
                remove_legacy_simple_deform(target, legacy_modifier)
        for node_group in node_groups:
            if (
                    node_group and node_group.users == 0 and
                    node_group.get(MODIFIER_MARKER, False)
            ):
                bpy.data.node_groups.remove(node_group)
        remove_unused_control_collections()
        StageCache.clear(target)
        activate_cage_workspace_tool(context, "")
        refresh_controller_display(context, force=True)
        return {"FINISHED"}


def cage_local_matrix(target, controller):
    return (
        target.matrix_world @
        Matrix.Translation(controller.location) @
        _controller_rotation_xyz(controller).to_matrix().to_4x4()
    )


def deform_handle_world(target, controller):
    properties = controller.sdh_cage_deform
    half = Vector(properties.size) * 0.5
    # Default: free end opposite the Origin. TAPER sits on the Origin end
    # (the other side of the cage length).
    if properties.deform_type == "TAPER":
        handle_y = half.y if properties.origin == "TOP" else -half.y
    else:
        handle_y = -half.y if properties.origin == "TOP" else half.y
    handle_x = {
        "TAPER": half.x * 0.55,
    }.get(properties.deform_type, 0.0)
    curve_deformer = None
    if str(getattr(properties, "cage_type", "")) == "CURVE":
        try:
            from .curve import curve_preview_deformer
            curve_deformer = curve_preview_deformer(
                properties, apply_effect_range=False)
        except (AttributeError, ImportError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            curve_deformer = None
    point = deform_point_for_display(
        (handle_x, handle_y, 0.0), properties,
        curve_deformer_override=curve_deformer)
    return cage_local_matrix(target, controller) @ point


def end_shape_handle_world(target, controller, side):
    properties = controller.sdh_cage_deform
    half = Vector(properties.size) * 0.5
    curve_deformer = None
    if str(getattr(properties, "cage_type", "")) == "CURVE":
        try:
            from .curve import curve_preview_deformer
            curve_deformer = curve_preview_deformer(
                properties, apply_effect_range=False)
        except (AttributeError, ImportError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            curve_deformer = None
    point = deform_point_for_display(
        (half.x, half.y if side == "TOP" else -half.y, 0.0), properties,
        curve_deformer_override=curve_deformer)
    return cage_local_matrix(target, controller) @ point


def cage_boundary_points_local(properties, side):
    """Return deformed end centers and tangent-aligned handle positions."""
    half = Vector(properties.size) * 0.5
    is_curve = str(getattr(properties, "cage_type", "")) == "CURVE"
    if is_curve:
        range_start, range_end = curve_effect_range(properties)
        boundary_factor = range_end if side == "TOP" else range_start
        boundary_y = -half.y + float(properties.size[1]) * boundary_factor
    else:
        boundary_y = half.y if side == "TOP" else -half.y
    outward_sign = 1.0 if side == "TOP" else -1.0
    raw_boundary = Vector((0.0, boundary_y, 0.0))
    handle_offset = max(
        min(properties.size[0], properties.size[2]) * 0.22,
        properties.size[1] * 0.025,
        0.08,
    )
    tangent_sample = max(
        min(abs(float(properties.size[1])) * 0.01, handle_offset),
        1.0e-5,
    )
    raw_inside = raw_boundary.copy()
    raw_inside.y -= outward_sign * tangent_sample
    preview_state = chain_global_stretch_preview_state(properties)
    prefix_state = chain_global_prefix_preview_state(properties)
    curve_deformer = None
    if is_curve:
        try:
            from .curve import curve_preview_deformer
            curve_deformer = curve_preview_deformer(
                properties, apply_effect_range=False)
        except (AttributeError, ImportError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            curve_deformer = None
    boundary = Vector(deform_point_for_display(
        raw_boundary, properties,
        chain_prefix_state=prefix_state,
        chain_stretch_state=preview_state,
        curve_deformer_override=curve_deformer))
    inside = Vector(deform_point_for_display(
        raw_inside, properties,
        chain_prefix_state=prefix_state,
        chain_stretch_state=preview_state,
        curve_deformer_override=curve_deformer))
    outward = boundary - inside
    if outward.length <= EPSILON:
        outward = Vector((0.0, outward_sign, 0.0))
    else:
        outward.normalize()
    return boundary, boundary + outward * handle_offset


def cage_boundary_handle_world(target, controller, side):
    _boundary, handle = cage_boundary_points_local(
        controller.sdh_cage_deform, side)
    return cage_local_matrix(target, controller) @ handle


def cage_input_axis_limits(context, target, modifier, controller):
    """Return the input geometry bounds projected onto the cage length axis."""
    bounds = _modifier_input_bounds(context, target, modifier)
    axis = _controller_rotation_xyz(controller).to_matrix() @ Vector((0.0, 1.0, 0.0))
    if axis.length < EPSILON:
        return None
    axis.normalize()
    positions = tuple(point.dot(axis) for point in _bounds_corners(bounds))
    if not positions or not all(math.isfinite(value) for value in positions):
        return None
    return min(positions), max(positions)


def curve_effect_range(properties):
    """Return the ordered normalized effect interval for a Curve cage."""
    try:
        start = min(max(float(properties.curve_range_start), 0.0), 1.0)
        end = min(max(float(properties.curve_range_end), 0.0), 1.0)
    except (AttributeError, ReferenceError, TypeError, ValueError):
        return 0.0, 1.0
    return (start, end) if start <= end else (end, start)


def move_curve_effect_boundary(
        controller, side, axis_delta, initial_range=None,
        axis_limits=None, boundary_mode="SINGLE"):
    """Move one Curve effect boundary without resizing its mapping domain."""
    if side not in {"TOP", "BOTTOM"}:
        raise ValueError(f"Unsupported Curve boundary: {side!r}")
    properties = controller.sdh_cage_deform
    length = max(abs(float(properties.size[1])), EPSILON)
    if initial_range is None:
        start, end = curve_effect_range(properties)
    else:
        try:
            start, end = (float(initial_range[0]), float(initial_range[1]))
        except (TypeError, ValueError, IndexError):
            start, end = curve_effect_range(properties)
        start = min(max(start, 0.0), 1.0)
        end = min(max(end, 0.0), 1.0)
        if start > end:
            start, end = end, start

    boundary_mode = str(boundary_mode or "SINGLE").upper()
    if boundary_mode not in {"SINGLE", "TRANSLATE", "SYMMETRIC"}:
        boundary_mode = "SINGLE"
    if (
            boundary_mode == "SINGLE" and
            bool(getattr(properties, "curve_closed", False))
    ):
        boundary_mode = "SYMMETRIC"

    allowed_start = 0.0
    allowed_end = 1.0
    if axis_limits is not None:
        try:
            lower_limit = float(axis_limits[0])
            upper_limit = float(axis_limits[1])
            if lower_limit > upper_limit:
                lower_limit, upper_limit = upper_limit, lower_limit
            axis = (
                _controller_rotation_xyz(controller).to_matrix() @
                Vector((0.0, 1.0, 0.0)))
            if axis.length > EPSILON:
                axis.normalize()
                center_axis = Vector(controller.location).dot(axis)
                source_bottom = center_axis - length * 0.5
                allowed_start = min(max(
                    (lower_limit - source_bottom) / length, 0.0), 1.0)
                allowed_end = min(max(
                    (upper_limit - source_bottom) / length, 0.0), 1.0)
                if allowed_start > allowed_end:
                    allowed_start, allowed_end = allowed_end, allowed_start
        except (AttributeError, ReferenceError, TypeError, ValueError,
                IndexError):
            allowed_start, allowed_end = 0.0, 1.0

    minimum_gap = min(max(EPSILON / length, 1.0e-6), 1.0)
    if allowed_end - allowed_start < minimum_gap:
        allowed_start, allowed_end = 0.0, 1.0
    start = min(max(start, allowed_start), allowed_end - minimum_gap)
    end = max(min(end, allowed_end), start + minimum_gap)
    factor_delta = float(axis_delta) / length

    if boundary_mode == "TRANSLATE":
        factor_delta = min(max(
            factor_delta, allowed_start - start), allowed_end - end)
        next_start = start + factor_delta
        next_end = end + factor_delta
        applied_factor = factor_delta
    elif boundary_mode == "SYMMETRIC":
        side_sign = 1.0 if side == "TOP" else -1.0
        q = side_sign * factor_delta
        q_lower = (minimum_gap - (end - start)) * 0.5
        q_upper = min(start - allowed_start, allowed_end - end)
        q = min(max(q, q_lower), q_upper)
        next_start = start - q
        next_end = end + q
        applied_factor = side_sign * q
    elif side == "TOP":
        next_start = start
        next_end = min(max(
            end + factor_delta, start + minimum_gap), allowed_end)
        applied_factor = next_end - end
    else:
        next_end = end
        next_start = min(max(
            start + factor_delta, allowed_start), end - minimum_gap)
        applied_factor = next_start - start

    pointer = _pointer(controller)
    _SYNCING.add(pointer)
    try:
        properties.curve_range_start = next_start
        properties.curve_range_end = next_end
    finally:
        _SYNCING.discard(pointer)
    sync_controller(controller, pull_transform=False)
    return applied_factor * length, (next_end - next_start) * length


def move_cage_boundary(controller, side, axis_delta,
                       initial_size=None, initial_location=None,
                       axis_limits=None, boundary_mode="SINGLE",
                       initial_curve_range=None):
    """Move a longitudinal cage boundary.

    ``SINGLE`` keeps the opposite end fixed. ``TRANSLATE`` moves both ends by
    the same amount, while ``SYMMETRIC`` moves the ends in opposite directions
    around the cage center. Closed Curve cages link their coincident ends, so
    a regular single-end drag becomes symmetric. The explicit mode keeps
    modifier keys out of the core evaluator and makes the same behavior
    available to chain editing.
    """
    if side not in {"TOP", "BOTTOM"}:
        raise ValueError(f"Unsupported cage boundary: {side!r}")
    properties = controller.sdh_cage_deform
    if str(getattr(properties, "cage_type", "")) == "CURVE":
        return move_curve_effect_boundary(
            controller, side, axis_delta,
            initial_range=initial_curve_range,
            axis_limits=axis_limits,
            boundary_mode=boundary_mode,
        )
    initial_size = Vector(
        properties.size if initial_size is None else initial_size)
    initial_location = Vector(
        controller.location if initial_location is None else initial_location)
    axis_delta = float(axis_delta)
    boundary_mode = str(boundary_mode or "SINGLE").upper()
    if boundary_mode not in {"SINGLE", "TRANSLATE", "SYMMETRIC"}:
        boundary_mode = "SINGLE"
    if (
            boundary_mode == "SINGLE" and
            str(getattr(properties, "cage_type", "")) == "CURVE" and
            bool(getattr(properties, "curve_closed", False))
    ):
        boundary_mode = "SYMMETRIC"

    axis = _controller_rotation_xyz(controller).to_matrix() @ Vector((0.0, 1.0, 0.0))
    if axis.length < EPSILON:
        axis = Vector((0.0, 1.0, 0.0))
    else:
        axis.normalize()
    center_axis = initial_location.dot(axis)
    initial_top = center_axis + initial_size.y * 0.5
    initial_bottom = center_axis - initial_size.y * 0.5

    lower_limit = None
    upper_limit = None
    if axis_limits is not None:
        try:
            lower_limit, upper_limit = (
                float(axis_limits[0]), float(axis_limits[1]))
        except (TypeError, ValueError, IndexError):
            lower_limit = upper_limit = None
        if lower_limit is not None and lower_limit > upper_limit:
            lower_limit, upper_limit = upper_limit, lower_limit

    if boundary_mode == "TRANSLATE":
        # Both boundaries share the same delta, so the cage length stays
        # unchanged and only its center moves along the local cage axis.
        lower_delta = (
            lower_limit - initial_bottom
            if lower_limit is not None else -math.inf)
        upper_delta = (
            upper_limit - initial_top
            if upper_limit is not None else math.inf)
        applied_axis_delta = min(max(axis_delta, lower_delta), upper_delta)
        new_bottom = initial_bottom + applied_axis_delta
        new_top = initial_top + applied_axis_delta
        new_length = max(new_top - new_bottom, EPSILON)
        center_shift_local = applied_axis_delta
    elif boundary_mode == "SYMMETRIC":
        # q is the signed half-length change.  TOP uses q=d; BOTTOM uses
        # q=-d, so the returned delta remains the movement of the dragged end.
        side_sign = 1.0 if side == "TOP" else -1.0
        q = side_sign * axis_delta
        q_lower = (EPSILON - initial_size.y) * 0.5
        q_upper = math.inf
        if lower_limit is not None:
            q_lower = max(q_lower, lower_limit - initial_top,
                          initial_bottom - upper_limit)
        if upper_limit is not None:
            q_upper = min(upper_limit - initial_top,
                          initial_bottom - lower_limit)
        q = min(max(q, q_lower), q_upper)
        applied_axis_delta = side_sign * q
        new_top = initial_top + q
        new_bottom = initial_bottom - q
        new_length = max(new_top - new_bottom, EPSILON)
        center_shift_local = 0.0
    elif side == "TOP":
        desired = max(initial_top + axis_delta, initial_bottom + EPSILON)
        if lower_limit is not None:
            desired = min(desired, upper_limit)
            desired = max(desired, initial_bottom + EPSILON)
        applied_axis_delta = desired - initial_top
        new_length = max(desired - initial_bottom, EPSILON)
        center_shift_local = applied_axis_delta * 0.5
    else:
        desired = min(initial_bottom + axis_delta, initial_top - EPSILON)
        if lower_limit is not None:
            desired = max(desired, lower_limit)
            desired = min(desired, initial_top - EPSILON)
        applied_axis_delta = desired - initial_bottom
        new_length = max(initial_top - desired, EPSILON)
        center_shift_local = applied_axis_delta * 0.5

    rotation_matrix = _controller_rotation_xyz(controller).to_matrix()
    center_shift = rotation_matrix @ Vector((0.0, center_shift_local, 0.0))
    previous_location = Vector(controller.location)
    next_location = initial_location + center_shift
    actual_shift_world = next_location - previous_location
    actual_shift_local = (
        rotation_matrix.inverted_safe() @ actual_shift_world).y
    pointer = _pointer(controller)
    _SYNCING.add(pointer)
    try:
        properties.size = (initial_size.x, new_length, initial_size.z)
        controller.scale = (
            initial_size.x * 0.5,
            new_length * 0.5,
            initial_size.z * 0.5,
        )
        controller.location = next_location
    finally:
        _SYNCING.discard(pointer)
    is_curve = str(getattr(properties, "cage_type", "")) == "CURVE"
    if is_curve:
        try:
            from .curve import (
                apply_curve_cage_boundary_relation,
                apply_curve_source_boundary_relation,
            )
            if curve_control_mode_identifier(properties) == "CURVE":
                apply_curve_source_boundary_relation(
                    controller, actual_shift_local)
            else:
                apply_curve_cage_boundary_relation(
                    controller, actual_shift_local, boundary_mode)
        except (AttributeError, ImportError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            pass
    sync_controller(controller, pull_transform=False)
    if is_curve:
        try:
            from .curve import record_curve_relation_snapshot
            record_curve_relation_snapshot(controller)
        except (AttributeError, ImportError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            pass
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
