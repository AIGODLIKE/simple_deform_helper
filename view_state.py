"""Per-viewport display state for Simple Deform Helper.

The native Blender overlay and Gizmo switches are already scoped to one
3D View, but they cannot express the add-on's cage/guide distinction.  Keep
those switches in a small runtime table keyed by Window, Area, and the active
SpaceView3D.  Nothing is written to a blend file or to a shared controller.
"""
from __future__ import annotations

from time import monotonic

import bpy
from bpy.app.translations import pgettext_iface as iface_
from bpy.props import EnumProperty
from bpy.types import Operator


VIEW_DISPLAY_KINDS = ("cage", "gizmo", "guides")
_DEFAULTS = {kind: True for kind in VIEW_DISPLAY_KINDS}
_VIEW_STATES = {}
_LAST_PRUNE = 0.0
_PRUNE_INTERVAL = 1.0
_PANEL_CALLBACKS = []
_OPERATOR_REGISTERED = False


def _pointer(value):
    """Return a stable RNA pointer, with a safe Python fallback for tests."""
    if value is None:
        return 0
    try:
        return int(value.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return id(value)


def _space_from_context(context):
    context = context or getattr(bpy, "context", None)
    space = getattr(context, "space_data", None)
    if getattr(space, "type", None) != "VIEW_3D":
        return None
    return space


def view_key(context=None):
    """Return the Window/Area/Space key for a 3D View context."""
    context = context or getattr(bpy, "context", None)
    space = _space_from_context(context)
    if space is None:
        return None
    window = getattr(context, "window", None)
    area = getattr(context, "area", None)
    key = (_pointer(window), _pointer(area), _pointer(space))
    # A context made by a unit test may not expose any RNA objects.  Do not
    # retain a synthetic all-zero entry; the default state is equivalent.
    return key if any(key) else None


def _live_view_keys():
    """Collect active 3D View keys so closed/switching areas can be purged."""
    try:
        windows = tuple(bpy.context.window_manager.windows)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return set()
    keys = set()
    for window in windows:
        screen = getattr(window, "screen", None)
        for area in tuple(getattr(screen, "areas", ()) or ()):
            if getattr(area, "type", None) != "VIEW_3D":
                continue
            spaces = getattr(area, "spaces", None)
            space = getattr(spaces, "active", None)
            if getattr(space, "type", None) != "VIEW_3D":
                continue
            key = (_pointer(window), _pointer(area), _pointer(space))
            if any(key):
                keys.add(key)
    return keys


def prune_view_states(context=None, *, force=False):
    """Drop state belonging to areas that no longer exist."""
    global _LAST_PRUNE
    now = monotonic()
    if not force and now - _LAST_PRUNE < _PRUNE_INTERVAL:
        return
    _LAST_PRUNE = now
    live = _live_view_keys()
    current = view_key(context)
    if current is not None:
        live.add(current)
    if not live:
        return
    for key in tuple(_VIEW_STATES):
        if key not in live:
            _VIEW_STATES.pop(key, None)


def is_view_display_enabled(context, kind):
    """Return one add-on display switch; unknown/non-3D contexts default on."""
    kind = str(kind).lower()
    if kind not in _DEFAULTS:
        return True
    prune_view_states(context)
    key = view_key(context)
    if key is None:
        return _DEFAULTS[kind]
    return bool(_VIEW_STATES.get(key, _DEFAULTS)[kind])


def set_view_display_enabled(context, kind, enabled):
    """Set one switch and redraw every open 3D View."""
    kind = str(kind).lower()
    if kind not in _DEFAULTS:
        return False
    key = view_key(context)
    if key is None:
        return False
    state = _VIEW_STATES.setdefault(key, dict(_DEFAULTS))
    enabled = bool(enabled)
    changed = state.get(kind) != enabled
    state[kind] = enabled
    tag_all_view3d_redraw()
    return changed


def reset_view_display(context=None):
    """Restore defaults for the current 3D View only."""
    key = view_key(context)
    if key is None:
        return False
    changed = key in _VIEW_STATES and _VIEW_STATES[key] != _DEFAULTS
    _VIEW_STATES.pop(key, None)
    tag_all_view3d_redraw()
    return changed


def clear_view_states():
    """Release all runtime references during unregister/reload."""
    _VIEW_STATES.clear()


def tag_all_view3d_redraw():
    """Request an immediate redraw without assuming a particular context."""
    try:
        windows = tuple(bpy.context.window_manager.windows)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        windows = ()
    for window in windows:
        screen = getattr(window, "screen", None)
        for area in tuple(getattr(screen, "areas", ()) or ()):
            if getattr(area, "type", None) != "VIEW_3D":
                continue
            try:
                area.tag_redraw()
            except (ReferenceError, RuntimeError, TypeError):
                pass


def viewport_cage_overlay_enabled(context=None):
    """Whether cage preview geometry may be drawn in this 3D View."""
    if not is_view_display_enabled(context, "cage"):
        return False
    space = _space_from_context(context)
    overlay = getattr(space, "overlay", None)
    return bool(getattr(overlay, "show_overlays", True))


def viewport_cage_guides_enabled(context=None):
    """Whether auxiliary guide geometry may be drawn in this 3D View."""
    if not viewport_cage_overlay_enabled(context):
        return False
    return is_view_display_enabled(context, "guides")


def viewport_cage_gizmos_enabled(context=None):
    """Whether add-on Gizmos may be shown in this 3D View."""
    if not is_view_display_enabled(context, "gizmo"):
        return False
    space = _space_from_context(context)
    return bool(getattr(space, "show_gizmo", True))


class SDH_OT_toggle_view_display(Operator):
    """Toggle one display category for the invoking 3D View."""

    bl_idname = "sdh.toggle_view_display"
    bl_label = "Toggle Simple Deform View Display"
    bl_options = {"INTERNAL"}

    kind: EnumProperty(
        name="Display",
        items=(
            ("cage", "Cage", "Toggle cage preview in this view"),
            ("gizmo", "Gizmos", "Toggle SDH Gizmos in this view"),
            ("guides", "Guides", "Toggle guide geometry in this view"),
        ),
        default="cage",
        options={"HIDDEN", "SKIP_SAVE"},
    )

    def execute(self, context):
        kind = str(self.kind).lower()
        set_view_display_enabled(
            context, kind, not is_view_display_enabled(context, kind))
        return {"FINISHED"}


class SDH_OT_reset_view_display(Operator):
    """Restore all Simple Deform display switches in this 3D View."""

    bl_idname = "sdh.reset_view_display"
    bl_label = "Reset Simple Deform View Display"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        reset_view_display(context)
        return {"FINISHED"}


def _draw_toggle(layout, context, kind, label, icon):
    enabled = is_view_display_enabled(context, kind)
    operator = layout.operator(
        SDH_OT_toggle_view_display.bl_idname,
        text=iface_(label),
        icon=icon,
        depress=enabled,
    )
    operator.kind = kind


def draw_overlay_panel(panel, context):
    """Prepend SDH cage/guide switches to Blender's Overlay popover."""
    if _space_from_context(context) is None:
        return
    layout = panel.layout
    box = layout.box()
    box.label(text=iface_("Simple Deform Helper"), icon="MOD_SIMPLEDEFORM")
    row = box.row(align=True)
    _draw_toggle(row, context, "cage", "Cage", "MOD_SIMPLEDEFORM")
    _draw_toggle(row, context, "gizmo", "Gizmos", "GIZMO")
    _draw_toggle(row, context, "guides", "Guides", "CURVE_DATA")
    box.operator(
        SDH_OT_reset_view_display.bl_idname,
        text=iface_("Reset SDH View"),
        icon="FILE_REFRESH",
    )


def draw_gizmo_panel(panel, context):
    """Prepend the SDH per-view Gizmo switch to Blender's Gizmo popover."""
    if _space_from_context(context) is None:
        return
    layout = panel.layout
    box = layout.box()
    box.label(text=iface_("Simple Deform Helper"), icon="MOD_SIMPLEDEFORM")
    _draw_toggle(box, context, "gizmo", "Gizmos", "GIZMO")
    box.operator(
        SDH_OT_reset_view_display.bl_idname,
        text=iface_("Reset SDH View"),
        icon="FILE_REFRESH",
    )


def register():
    global _OPERATOR_REGISTERED
    if not _OPERATOR_REGISTERED:
        bpy.utils.register_class(SDH_OT_toggle_view_display)
        bpy.utils.register_class(SDH_OT_reset_view_display)
        _OPERATOR_REGISTERED = True
    callbacks = (
        ("VIEW3D_PT_overlay", draw_overlay_panel),
        ("VIEW3D_PT_gizmo_display", draw_gizmo_panel),
    )
    for panel_name, callback in callbacks:
        panel = getattr(bpy.types, panel_name, None)
        if panel is None or callback in _PANEL_CALLBACKS:
            continue
        try:
            panel.prepend(callback)
            _PANEL_CALLBACKS.append(callback)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass


def unregister():
    global _OPERATOR_REGISTERED
    for callback in reversed(tuple(_PANEL_CALLBACKS)):
        for panel_name in ("VIEW3D_PT_overlay", "VIEW3D_PT_gizmo_display"):
            panel = getattr(bpy.types, panel_name, None)
            if panel is None:
                continue
            try:
                panel.remove(callback)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
    _PANEL_CALLBACKS.clear()
    if _OPERATOR_REGISTERED:
        for item in (SDH_OT_reset_view_display, SDH_OT_toggle_view_display):
            try:
                bpy.utils.unregister_class(item)
            except (RuntimeError, ValueError):
                pass
        _OPERATOR_REGISTERED = False
    clear_view_states()
