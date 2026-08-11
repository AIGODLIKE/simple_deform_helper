"""Shared depth-state helpers for cage previews and custom Gizmos."""
from __future__ import annotations

import gpu

from ..utils import get_pref


def cage_overlay_depth_test():
    """Return the depth mode selected by the shared In Front preference."""
    preference = get_pref()
    return (
        "ALWAYS"
        if preference is not None and preference.show_wireframe_in_front
        else "LESS_EQUAL"
    )


def gizmo_depth_test():
    """Return the depth mode for interactive controls.

    Custom cage Gizmos are interaction affordances rather than preview
    geometry.  They must remain visible and pickable when the cage wireframe
    is allowed to sit behind the controlled object, so their depth policy is
    intentionally independent of the ``In Front`` preference.
    """
    return "ALWAYS"


def _draw_custom_shape(
        gizmo, shape, *, depth_test, matrix=None, select_id=None):
    gpu.state.depth_test_set(depth_test)
    try:
        if matrix is not None and select_id is not None:
            gizmo.draw_custom_shape(
                shape, matrix=matrix, select_id=select_id)
        elif matrix is not None:
            gizmo.draw_custom_shape(shape, matrix=matrix)
        elif select_id is not None:
            gizmo.draw_custom_shape(shape, select_id=select_id)
        else:
            gizmo.draw_custom_shape(shape)
    finally:
        gpu.state.depth_test_set("NONE")


def draw_gizmo_custom_shape(
        gizmo, shape, *, matrix=None, select_id=None):
    """Draw an interactive cage Gizmo in front of scene geometry."""
    return _draw_custom_shape(
        gizmo, shape, depth_test=gizmo_depth_test(), matrix=matrix,
        select_id=select_id)


def draw_cage_custom_shape(
        gizmo, shape, *, matrix=None, select_id=None):
    """Draw a cage shape with the configurable preview depth policy.

    This compatibility helper is retained for callers that intentionally draw
    preview geometry.  Interactive controls should use
    :func:`draw_gizmo_custom_shape` instead.
    """
    return _draw_custom_shape(
        gizmo, shape, depth_test=cage_overlay_depth_test(), matrix=matrix,
        select_id=select_id)
