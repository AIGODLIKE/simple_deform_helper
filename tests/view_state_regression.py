"""Regression coverage for per-3D-View Simple Deform display switches."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))


def check(condition, message):
    if not condition:
        raise AssertionError(message)


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
state = importlib.import_module(f"{PACKAGE}.view_state")


class Overlay:
    show_overlays = True


def view_context(tag):
    space = SimpleNamespace(
        type="VIEW_3D",
        show_gizmo=True,
        overlay=Overlay(),
    )
    return SimpleNamespace(
        window=SimpleNamespace(tag=f"window-{tag}"),
        area=SimpleNamespace(tag=f"area-{tag}"),
        space_data=space,
    )


first = view_context("first")
second = view_context("second")
try:
    check(state.viewport_cage_overlay_enabled(first),
          "first view did not default to cage visible")
    check(state.viewport_cage_gizmos_enabled(first),
          "first view did not default to Gizmos visible")
    state.set_view_display_enabled(first, "cage", False)
    state.set_view_display_enabled(first, "guides", False)
    state.set_view_display_enabled(first, "gizmo", False)
    check(not state.viewport_cage_overlay_enabled(first),
          "first view cage switch did not hide the overlay")
    check(not state.viewport_cage_guides_enabled(first),
          "first view guide switch did not hide guides")
    check(not state.viewport_cage_gizmos_enabled(first),
          "first view Gizmo switch did not hide controls")
    check(state.viewport_cage_overlay_enabled(second),
          "second view inherited first view cage state")
    check(state.viewport_cage_gizmos_enabled(second),
          "second view inherited first view Gizmo state")
    second.space_data.overlay.show_overlays = False
    check(not state.viewport_cage_overlay_enabled(second),
          "native Overlay toggle was ignored")
    second.space_data.overlay.show_overlays = True
    state.reset_view_display(first)
    check(state.viewport_cage_overlay_enabled(first),
          "reset did not restore cage state")
    check(state.viewport_cage_guides_enabled(first),
          "reset did not restore guide state")
    check(state.viewport_cage_gizmos_enabled(first),
          "reset did not restore Gizmo state")
    check(hasattr(bpy.types, "SDH_OT_toggle_view_display"),
          "view display operator was not registered")
    check(len(state._PANEL_CALLBACKS) == 2,
          f"expected two native panel callbacks, got {state._PANEL_CALLBACKS!r}")
    print("SDH_VIEW_STATE::PASS")
finally:
    addon.unregister()
    check(not state._VIEW_STATES, "view state survived unregister")
    check(not hasattr(bpy.types, "SDH_OT_toggle_view_display"),
          "view display operator survived unregister")
    bpy.context.preferences.addons.remove(entry)
