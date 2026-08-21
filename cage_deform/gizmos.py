"""Cage deform viewport gizmos and shape helpers."""
from __future__ import annotations

import math
from time import monotonic

import bpy
from bpy.props import FloatProperty
from bpy.types import Gizmo, GizmoGroup
from mathutils import Euler, Matrix, Vector

from ..stages import _object_fallback_bounds
from ..utils import GizmoUtils, get_pref
from . import core as _core_module
from . import undo as _undo
from .ffd_batch import draw_ffd_line_face_batches
from .chain import (
    apply_shared_boundary_edit,
    capture_chain_boundary_state,
    chain_stages,
    restore_shared_boundary_edit,
    stage_chain_mode,
    stage_chain_uuid,
)
from .core import (
    DEFORM_ORDER,
    EPSILON,
    FFD_CORNERS,
    FFD_COMPONENT_COUNT,
    SDH_OT_set_bend_trend,
    SDH_OT_set_cage_axis,
    SDHCageControllerProperties,
    _alignment_rotation,
    _arc_arrow_triangles,
    _modifier_input_bounds,
    _ring_triangles,
    cage_boundary_handle_world,
    cage_boundary_points_local,
    cage_input_axis_limits,
    curve_effect_range,
    cage_modifier_uuid,
    CONTROLLER_STYLES,
    cage_local_matrix,
    chain_global_stretch_value,
    deform_point_for_display,
    end_shape_handle_world,
    flush_pending_chain_updates,
    cage_modifiers,
    find_controller,
    move_cage_boundary,
    resolve_context_deform,
    ffd_point_coordinates,
    ffd_point_count,
    ffd_grid_corner_indices,
    ffd_point_index,
    ffd_point_is_surface,
    ffd_point_offset,
    ffd_point_effective_offset,
    ffd_resolution,
    ffd_selection_entities,
    ffd_screen_selection_entity,
    ffd_selection_modes,
    ffd_selected_indices,
    ffd_selection_indices,
    ffd_set_selection,
    ensure_ffd_point_collection,
    ffd_handles_enabled,
    sync_chain_global_stretch_from_stage,
)
from .viewport import (
    gizmo_depth_test,
    draw_gizmo_custom_shape as draw_cage_custom_shape,
)


def _ffd_projected_entity_cache_info():
    return _core_module.ffd_projected_entity_cache_info()

# Blender's Gizmo type does not register arbitrary bpy.props annotations.
# Hidden controller properties give target-bound tooltips stable, translated
# descriptions without changing what the custom modal handles edit.
SDHCageControllerProperties.__annotations__.update({
    "tooltip_top_end_shape": FloatProperty(
        name="Top End Shape",
        description=(
            "Drag to scale; Alt moves screen X; Shift moves screen Y; "
            "Alt+Shift moves freely"
        ),
        options={"HIDDEN", "SKIP_SAVE"},
    ),
    "tooltip_bottom_end_shape": FloatProperty(
        name="Bottom End Shape",
        description=(
            "Drag to scale; Alt moves screen X; Shift moves screen Y; "
            "Alt+Shift moves freely"
        ),
        options={"HIDDEN", "SKIP_SAVE"},
    ),
    "tooltip_top_boundary": FloatProperty(
        name="Top Boundary",
        description="Top Boundary",
        options={"HIDDEN", "SKIP_SAVE"},
    ),
    "tooltip_bottom_boundary": FloatProperty(
        name="Bottom Boundary",
        description="Bottom Boundary",
        options={"HIDDEN", "SKIP_SAVE"},
    ),
    "tooltip_shared_boundary": FloatProperty(
        name="Shared Boundary",
        description="Shared Boundary",
        options={"HIDDEN", "SKIP_SAVE"},
    ),
})
for _ffd_index, (_ffd_label, *_ffd_signs) in enumerate(FFD_CORNERS):
    SDHCageControllerProperties.__annotations__[
        f"tooltip_ffd_corner_{_ffd_index}"] = FloatProperty(
            name=f"FFD {_ffd_label}",
            description=f"FFD {_ffd_label}",
            options={"HIDDEN", "SKIP_SAVE"},
        )
SDHCageControllerProperties.__annotations__["tooltip_ffd_point"] = FloatProperty(
    name="FFD Control Point",
    description=(
        "Drag this point to enter FFD Edit Mode; Shift toggles its selection; "
        "Alt moves along the cage axis"
    ),
    options={"HIDDEN", "SKIP_SAVE"},
)
SDHCageControllerProperties.__annotations__["tooltip_ffd_line"] = FloatProperty(
    name="FFD Control Line",
    description="Drag this segment to move its two adjacent FFD control points",
    options={"HIDDEN", "SKIP_SAVE"},
)
SDHCageControllerProperties.__annotations__["tooltip_ffd_face"] = FloatProperty(
    name="FFD Control Face",
    description=(
        "Drag this face to move every FFD point in the selected UV, UW, or VW "
        "grid face"
    ),
    options={"HIDDEN", "SKIP_SAVE"},
)
SDHCageControllerProperties.__annotations__["tooltip_shear_plane"] = FloatProperty(
    name="Shear End-Face Handle",
    description=(
        "Drag the center freely or an arm along cage X/Z; Alt locks X, "
        "Shift locks Z, Ctrl snaps"
    ),
    options={"HIDDEN", "SKIP_SAVE"},
)

# draw_prepare → draw 同周期去重（避免 __slots__ 动态属性问题）
_MATRIX_FRESH_IDS = set()
_CAGE_WIRE_GEOMETRY_CACHE = {}
_CAGE_WIRE_INDEX_CACHE = {}
_CAGE_GUIDE_GEOMETRY_CACHE = {}
_BEND_TREND_LOCAL_FRAME_CACHE = {}
_CHAIN_DISPLAY_BY_PREVIEW_SIGNATURE = {}
_GEOMETRY_CACHE_LIMIT = 64
_GIZMO_UNDO_ACTIVE = _undo.ACTIVE_TRANSACTIONS

# Interactive drags change the cage signature on every mouse event, so the
# signature-keyed geometry caches never hit and each event pays a full Python
# re-tessellation for every affected stage.  Wire rebuilds and inactive-stage
# handle matrices are therefore rate limited: within the window the previous
# shape/matrix is reused and one deferred redraw guarantees convergence after
# the burst ends.  Active-stage handles are exempt so dragging stays 1:1.
_WIRE_THROTTLE_WINDOW = 1.0 / 30.0
_BUNDLE_MATRIX_THROTTLE_WINDOW = 0.05
_WIRE_THROTTLE_STATE = {}
_WIRE_THROTTLE_LIMIT = 128
_THROTTLE_REDRAW_PENDING = []
_END_SHAPE_DRAG_STATE = {}


def _rna_pointer(value):
    try:
        return int(value.as_pointer()) if value is not None else 0
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return id(value) if value is not None else 0


def _begin_end_shape_preview_drag(target, modifier, controller, side):
    """Keep only the edited seam live while an end-scale drag is active."""
    _END_SHAPE_DRAG_STATE.clear()
    chain_uuid = stage_chain_uuid(modifier)
    stages = tuple(chain_stages(target, chain_uuid))
    if (
            not chain_uuid or len(stages) < 2 or
            str(stage_chain_mode(stages[0], "")).upper() not in
            {"CHAINED", "CONNECTED"}
    ):
        return
    try:
        index = stages.index(modifier)
    except ValueError:
        return
    live_pointers = {_rna_pointer(controller)}
    peer_index = index + (1 if str(side).upper() == "TOP" else -1)
    if 0 <= peer_index < len(stages):
        peer = find_controller(target, stages[peer_index])
        if peer is not None:
            live_pointers.add(_rna_pointer(peer))
    _END_SHAPE_DRAG_STATE.update({
        "target": _rna_pointer(target),
        "controllers": frozenset(live_pointers),
    })


def _end_shape_preview_drag():
    _END_SHAPE_DRAG_STATE.clear()
    # The next redraw is the committed state, so it must not inherit the
    # in-burst 30 Hz wire throttle and briefly retain a stale picker shape.
    _WIRE_THROTTLE_STATE.clear()


def _freeze_for_end_shape_drag(target, controller):
    return bool(
        _END_SHAPE_DRAG_STATE and
        _END_SHAPE_DRAG_STATE.get("target") == _rna_pointer(target) and
        _rna_pointer(controller) not in
        _END_SHAPE_DRAG_STATE.get("controllers", ())
    )


def _push_gizmo_undo(message):
    """Create one Blender undo boundary for a committed cage drag.

    Cage controls edit RNA from Gizmo callbacks rather than from an Operator.
    Blender therefore has no automatic per-drag undo step; without an explicit
    boundary the next undo can jump past the parameter edit and remove the
    newly-created cage.  Keep this helper defensive because draw/select passes
    and background contexts may not have an undo-capable window.
    """
    return _undo.push(message)


def _begin_gizmo_undo(gizmo, message="Before Cage Control"):
    """Start a transaction immediately before the first drag write."""
    return _undo.begin(gizmo, message)


def _finish_gizmo_undo(gizmo, *, cancel=False, message="Cage Control"):
    """Commit a completed drag; cancelled drags only restore their snapshot."""
    return _undo.finish(gizmo, cancel=cancel, message=message)


def _flush_invoked_chain_updates(gizmo):
    """Commit deferred chain state before a direct Gizmo edit closes."""
    target = getattr(gizmo, "invoke_target", None)
    if target is None:
        return False
    try:
        flush_pending_chain_updates(target)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False
    return True


def _mark_matrix_fresh(gizmo):
    _MATRIX_FRESH_IDS.add(id(gizmo))


def _invalidate_matrix_fresh(gizmo):
    """Allow the next prepare pass to rebuild a gizmo matrix."""
    _MATRIX_FRESH_IDS.discard(id(gizmo))


def _consume_matrix_fresh(gizmo):
    """Check the prepare-pass cache without consuming it.

    Blender can draw a gizmo and its selection mask with different context
    objects. Keeping the prepared matrix for both passes prevents a
    screen-space handle offset from being recalculated into a different
    world-space position during hit testing.
    """
    key = id(gizmo)
    return key in _MATRIX_FRESH_IDS


def _tag_view3d_redraw():
    """Deferred redraw so throttled shapes settle after an input burst."""
    _THROTTLE_REDRAW_PENDING.clear()
    try:
        windows = bpy.context.window_manager.windows
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return None
    for window in windows:
        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", ()) or ():
            if area.type == "VIEW_3D":
                area.tag_redraw()
    return None


def _request_throttled_redraw():
    if _THROTTLE_REDRAW_PENDING:
        return
    _THROTTLE_REDRAW_PENDING.append(True)
    try:
        bpy.app.timers.register(
            _tag_view3d_redraw, first_interval=_WIRE_THROTTLE_WINDOW)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _THROTTLE_REDRAW_PENDING.clear()


def clear_throttled_redraw():
    """Cancel deferred redraw ownership before the extension unregisters."""
    try:
        if bpy.app.timers.is_registered(_tag_view3d_redraw):
            bpy.app.timers.unregister(_tag_view3d_redraw)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    _THROTTLE_REDRAW_PENDING.clear()
    _WIRE_THROTTLE_STATE.clear()
    _CHAIN_DISPLAY_BY_PREVIEW_SIGNATURE.clear()
    _END_SHAPE_DRAG_STATE.clear()


def _throttled_wire_shape(key):
    """Return ``(use_stale, shape)`` for one rate-limited wire consumer.

    ``settled`` state (two consecutive identical signatures) bypasses the
    throttle entirely, so idle redraws keep the exact signature-cache path
    and never schedule timers.
    """
    state = _WIRE_THROTTLE_STATE.get(key)
    if state is None or state[3] or state[2] is None:
        return False, None
    if monotonic() - state[0] < _WIRE_THROTTLE_WINDOW:
        _request_throttled_redraw()
        return True, state[2]
    return False, None


def _store_wire_shape(key, signature, shape, *, rebuilt):
    previous = _WIRE_THROTTLE_STATE.get(key)
    settled = previous is not None and previous[1] == signature
    stamp = (
        monotonic() if rebuilt or previous is None else previous[0])
    if len(_WIRE_THROTTLE_STATE) > _WIRE_THROTTLE_LIMIT:
        _WIRE_THROTTLE_STATE.clear()
    _WIRE_THROTTLE_STATE[key] = (stamp, signature, shape, settled)


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
    if name in {"STRETCH", "DIRECTION"}:
        # Slim double-arrow along Y (face normal +Z). DIRECTION reuses the same
        # mark; bend-bias orients it horizontally via matrix.
        return (
            (-0.07, -0.55, 0.0), (0.07, -0.55, 0.0), (0.07, 0.55, 0.0),
            (-0.07, -0.55, 0.0), (0.07, 0.55, 0.0), (-0.07, 0.55, 0.0),
            (-0.36, 0.48, 0.0), (0.36, 0.48, 0.0), (0.0, 1.0, 0.0),
            (-0.36, -0.48, 0.0), (0.0, -1.0, 0.0), (0.36, -0.48, 0.0),
        )
    if name == "SHEAR":
        # End-face grip with two positive axis arms.  Clicking the center gives
        # free planar motion; clicking an arm constrains the drag to cage X/Z.
        # This reads as sliding the free face, instead of a generic four-way
        # move icon covering the entire section.
        return (
            # Center face grip.
            (0.0, 0.24, 0.0), (0.24, 0.0, 0.0), (0.0, -0.24, 0.0),
            (0.0, 0.24, 0.0), (0.0, -0.24, 0.0), (-0.24, 0.0, 0.0),
            # Cage X arm.
            (0.18, -0.065, 0.0), (0.76, -0.065, 0.0), (0.76, 0.065, 0.0),
            (0.18, -0.065, 0.0), (0.76, 0.065, 0.0), (0.18, 0.065, 0.0),
            (0.68, -0.25, 0.0), (1.12, 0.0, 0.0), (0.68, 0.25, 0.0),
            # Cage Z arm (drawn on the shape's second planar axis).
            (-0.065, 0.18, 0.0), (0.065, 0.18, 0.0), (0.065, 0.76, 0.0),
            (-0.065, 0.18, 0.0), (0.065, 0.76, 0.0), (-0.065, 0.76, 0.0),
            (-0.25, 0.68, 0.0), (0.25, 0.68, 0.0), (0.0, 1.12, 0.0),
        )
    if name == "AXIS_POSITIVE":
        return (
            (0.0, 1.0, 0.0), (0.9, 0.0, 0.0), (0.0, -1.0, 0.0),
            (0.0, 1.0, 0.0), (0.0, -1.0, 0.0), (-0.9, 0.0, 0.0),
        )
    if name == "AXIS_NEGATIVE":
        return _ring_triangles(0.0, math.tau, 20, 0.48, 0.92)
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


def _view_to_camera(context, world_location):
    """World vector from ``world_location`` toward the view/camera, or None."""
    region_data = getattr(context, "region_data", None)
    if region_data is None:
        region_data = getattr(
            getattr(context, "space_data", None), "region_3d", None)
    if region_data is None:
        return None
    cam_matrix = region_data.view_matrix.inverted_safe()
    to_camera = Vector(cam_matrix.translation) - Vector(world_location)
    if to_camera.length < EPSILON:
        to_camera = cam_matrix.to_3x3() @ Vector((0.0, 0.0, 1.0))
    if to_camera.length < EPSILON:
        return None
    return to_camera


def _axis_facing_matrix(context, world_location, y_axis):
    """XY-plane icon: lock local +Y to ``y_axis``, roll so +Z faces the view.

    Primary axis stays locked (not a full billboard); only twist around that
    axis so the flat face remains readable.
    """
    y_axis = Vector(y_axis)
    if y_axis.length < EPSILON:
        y_axis = Vector((0.0, 1.0, 0.0))
    else:
        y_axis.normalize()

    to_camera = _view_to_camera(context, world_location)
    if to_camera is not None:
        z_axis = to_camera - to_camera.dot(y_axis) * y_axis
    else:
        z_axis = Vector((0.0, 0.0, 0.0))

    if z_axis.length < EPSILON:
        # View along the locked axis — pick any stable perpendicular.
        z_axis = y_axis.orthogonal()
    z_axis.normalize()

    x_axis = y_axis.cross(z_axis)
    if x_axis.length < EPSILON:
        x_axis = y_axis.orthogonal()
    else:
        x_axis.normalize()
    z_axis = x_axis.cross(y_axis)
    if z_axis.length < EPSILON:
        z_axis = y_axis.orthogonal()
    else:
        z_axis.normalize()

    rotation = Matrix.Identity(4)
    rotation.col[0][0:3] = x_axis
    rotation.col[1][0:3] = y_axis
    rotation.col[2][0:3] = z_axis
    return Matrix.Translation(world_location) @ rotation


def _polyline_midpoint_tangent(points):
    """Return the arc midpoint and local tangent for a deformed FFD line."""
    points = tuple(Vector(point) for point in points)
    if len(points) < 2:
        center = points[0] if points else Vector((0.0, 0.0, 0.0))
        return center, Vector((0.0, 1.0, 0.0)), 0.0
    segments = tuple(
        (points[index + 1] - points[index])
        for index in range(len(points) - 1))
    lengths = tuple(segment.length for segment in segments)
    total = sum(lengths)
    if total < EPSILON:
        return (
            sum(points, Vector((0.0, 0.0, 0.0))) / len(points),
            Vector((0.0, 1.0, 0.0)),
            total,
        )
    distance = total * 0.5
    traversed = 0.0
    for point, segment, length in zip(points, segments, lengths):
        if length < EPSILON:
            continue
        if traversed + length >= distance:
            factor = (distance - traversed) / length
            return point + segment * factor, segment.normalized(), total
        traversed += length
    return points[-1], segments[-1].normalized(), total


def _cage_rotation_matrix(cage_matrix):
    """Cage orientation without object/parent scale (avoids huge gizmos)."""
    return cage_matrix.to_quaternion().to_matrix().to_4x4()


def _normalized_cage_basis_matrix(cage_matrix, local_rotation):
    """Transform each handle axis with the cage while removing axis lengths.

    A target with non-uniform or negative scale can shear or reflect the cage
    after the controller rotation is applied.  Quaternion extraction discards
    both effects, so trend arrows visibly drift from the reference frame.  By
    normalizing the fully transformed columns independently, the gizmo keeps a
    stable screen size while following the same edge directions and handedness
    as the cage.
    """
    local_basis = local_rotation.to_3x3()
    transformed = cage_matrix.to_3x3() @ local_basis
    fallback = _cage_rotation_matrix(cage_matrix).to_3x3() @ local_basis
    result = Matrix.Identity(4)
    for index in range(3):
        axis = Vector(transformed.col[index])
        if axis.length <= EPSILON:
            axis = Vector(fallback.col[index])
        if axis.length <= EPSILON:
            axis = Vector((1.0 if index == 0 else 0.0,
                           1.0 if index == 1 else 0.0,
                           1.0 if index == 2 else 0.0))
        axis.normalize()
        result.col[index][0:3] = axis
    return result


def _twist_view_sign(context, world_location, cage_y):
    """Screen-drag handedness vs cage +Y.

    Looking from the +Y end of the twist axis, screen CCW matches one world
    spin; from the -Y end (bottom-up) the same screen motion is mirrored, so
    the drag delta must flip.
    """
    to_camera = _view_to_camera(context, world_location)
    if to_camera is None:
        return 1.0
    axis = Vector(cage_y)
    if axis.length < EPSILON:
        return 1.0
    axis.normalize()
    return 1.0 if float(to_camera.dot(axis)) >= 0.0 else -1.0


def _twist_ring_matrix(cage_matrix, world_location, strength=0.0,
                       frame_matrix=None):
    """Place the twist ring parallel to the cage end face.

    The custom ring is authored in the XY plane with its normal on local +Z.
    A cage end face is the XZ plane (normal local +Y), so convert the glyph to
    that plane first and then spin around the cage's local Y.  The glyph uses
    the inverse visual spin so its arrows agree with the evaluated twist.
    """
    if frame_matrix is not None:
        # The sampled frame already includes the current Twist value. Applying
        # the strength a second time would rotate the ring away from the final
        # cage end face after Bend -> Twist stacks.
        return frame_matrix
    strength = float(strength)
    orient = (
        Matrix.Rotation(-strength, 4, "Y") @
        Matrix.Rotation(-math.pi / 2.0, 4, "X")
    )
    return (
        Matrix.Translation(world_location) @
        _cage_rotation_matrix(cage_matrix) @
        orient
    )


def _deformed_section_frame(cage_matrix, properties, local_y, direction=0.0):
    """Return a world frame sampled from the evaluated cage section."""
    size = Vector(properties.size)
    half = size * 0.5
    y = min(max(float(local_y), -half.y), half.y)
    step = max(
        min(abs(size.y) * 0.01, min(abs(size.x), abs(size.z)) * 0.08),
        EPSILON * 10.0,
    )
    if y >= half.y - step:
        y0, y1 = y - step, y
    elif y <= -half.y + step:
        y0, y1 = y, y + step
    else:
        y0, y1 = y - step, y + step
    u_local = Vector((
        math.cos(float(direction)), 0.0, math.sin(float(direction))))
    v_local = Vector((-u_local.z, 0.0, u_local.x))
    cross_step = max(
        min(abs(size.x), abs(size.z)) * 0.08,
        abs(size.y) * 0.002,
        EPSILON * 10.0,
    )

    chain_stretch_state = (
        _core_module.chain_global_stretch_preview_state(properties))
    chain_prefix_state = (
        _core_module.chain_global_prefix_preview_state(properties))

    def sample(point):
        return Vector(deform_point_for_display(
            point, properties,
            chain_prefix_state=chain_prefix_state,
            chain_stretch_state=chain_stretch_state))

    center_local = sample((0.0, y, 0.0))
    center = Vector((0.0, y, 0.0))
    u_vector = sample(center + u_local * cross_step) - sample(
        center - u_local * cross_step)
    tangent = sample((0.0, y1, 0.0)) - sample((0.0, y0, 0.0))
    transform = cage_matrix.to_3x3()
    tangent_axis = transform @ tangent
    if tangent_axis.length < EPSILON:
        tangent_axis = transform @ Vector((0.0, 1.0, 0.0))
    if tangent_axis.length < EPSILON:
        tangent_axis = Vector((0.0, 1.0, 0.0))
    tangent_axis.normalize()
    u_axis = transform @ u_vector
    u_axis = u_axis - tangent_axis * u_axis.dot(tangent_axis)
    if u_axis.length < EPSILON:
        u_axis = transform @ u_local
        u_axis = u_axis - tangent_axis * u_axis.dot(tangent_axis)
    if u_axis.length < EPSILON:
        u_axis = tangent_axis.orthogonal()
    u_axis.normalize()
    # The ring's local XY face uses +Z as its normal.  tangent x u gives the
    # matching in-plane Y axis and preserves the cage's handedness.
    ring_y = tangent_axis.cross(u_axis)
    if ring_y.length < EPSILON:
        ring_y = tangent_axis.orthogonal()
    ring_y.normalize()
    rotation = Matrix.Identity(4)
    rotation.col[0][0:3] = u_axis
    rotation.col[1][0:3] = ring_y
    rotation.col[2][0:3] = tangent_axis
    cross_extent = max(abs(size.x), abs(size.z)) * 0.5
    u_end = sample(center + u_local * cross_extent) - center_local
    v_end = sample(center + v_local * cross_extent) - center_local
    cross_radius = max(
        (transform @ u_end).length,
        (transform @ v_end).length,
        EPSILON,
    )
    return Matrix.Translation(cage_matrix @ center_local) @ rotation, cross_radius


def _deformed_cross_section_frame(cage_matrix, properties, local_y):
    """Return the evaluated X/Z section plane without forcing it to the tangent.

    Shear translates cross-sections while keeping each section parallel to its
    authored X/Z plane.  A tangent-aligned frame would tilt the handle away
    from the visible end face, so sample the two in-plane directions directly.
    """
    size = Vector(properties.size)
    half = size * 0.5
    y = min(max(float(local_y), -half.y), half.y)
    step = max(
        min(abs(size.x), abs(size.z)) * 0.08,
        abs(size.y) * 0.002,
        EPSILON * 10.0,
    )

    chain_stretch_state = (
        _core_module.chain_global_stretch_preview_state(properties))
    chain_prefix_state = (
        _core_module.chain_global_prefix_preview_state(properties))

    def sample(point):
        return Vector(deform_point_for_display(
            point, properties,
            chain_prefix_state=chain_prefix_state,
            chain_stretch_state=chain_stretch_state))

    center = sample((0.0, y, 0.0))
    x_vector = sample((step, y, 0.0)) - sample((-step, y, 0.0))
    z_vector = sample((0.0, y, step)) - sample((0.0, y, -step))
    transform = cage_matrix.to_3x3()
    x_axis = transform @ x_vector
    z_axis = transform @ z_vector
    if x_axis.length <= EPSILON:
        x_axis = transform @ Vector((1.0, 0.0, 0.0))
    if x_axis.length <= EPSILON:
        x_axis = Vector((1.0, 0.0, 0.0))
    x_axis.normalize()
    z_axis -= x_axis * z_axis.dot(x_axis)
    if z_axis.length <= EPSILON:
        z_axis = transform @ Vector((0.0, 0.0, 1.0))
        z_axis -= x_axis * z_axis.dot(x_axis)
    if z_axis.length <= EPSILON:
        z_axis = x_axis.orthogonal()
    z_axis.normalize()
    normal = x_axis.cross(z_axis)
    if normal.length <= EPSILON:
        normal = x_axis.orthogonal()
    normal.normalize()

    rotation = Matrix.Identity(4)
    rotation.col[0][0:3] = x_axis
    rotation.col[1][0:3] = z_axis
    rotation.col[2][0:3] = normal
    x_edge = sample((half.x, y, 0.0)) - center
    z_edge = sample((0.0, y, half.z)) - center
    cross_radius = max(
        (transform @ x_edge).length,
        (transform @ z_edge).length,
        EPSILON,
    )
    return Matrix.Translation(cage_matrix @ center) @ rotation, cross_radius


def _stretch_arrow_matrix(context, cage_matrix, world_location, origin):
    """STRETCH strength mark: +Y toward the deform handle endpoint along cage Y."""
    handle_sign = -1.0 if origin == "TOP" else 1.0
    axis = cage_matrix.to_3x3() @ Vector((0.0, handle_sign, 0.0))
    return _axis_facing_matrix(context, world_location, axis)


# Shared with STRETCH strength handle — bend copies this exactly.
STRENGTH_ARROW_SCALE = 0.30
COMPACT_PARAMETER_SCALE = 0.18
SHEAR_HANDLE_FACE_OFFSET = 0.035


def _bend_open_axis_world(cage_matrix, properties):
    """World axis along bend ±u on the free end after deformation.

    Samples the free-end face along local u so the strength arrow faces the
    bend opening direction while still tracking the deformed end plane.
    """
    half = Vector(properties.size) * 0.5
    handle_y = -half.y if properties.origin == "TOP" else half.y
    direction = float(properties.bend_direction)
    local_u = Vector((math.cos(direction), 0.0, math.sin(direction)))
    span = max(min(half.x, half.z) * 0.35, EPSILON)
    chain_stretch_state = (
        _core_module.chain_global_stretch_preview_state(properties))
    chain_prefix_state = (
        _core_module.chain_global_prefix_preview_state(properties))
    center = Vector(deform_point_for_display(
        (0.0, handle_y, 0.0), properties,
        chain_prefix_state=chain_prefix_state,
        chain_stretch_state=chain_stretch_state))
    offset = local_u * span
    plus = Vector(deform_point_for_display(
        (offset.x, handle_y, offset.z), properties,
        chain_prefix_state=chain_prefix_state,
        chain_stretch_state=chain_stretch_state))
    axis_local = plus - center
    if axis_local.length < EPSILON:
        axis_local = local_u.copy()
    else:
        # Keep the signed tangent produced by the evaluator.  Forcing this
        # back onto authored +u made the strength arrow point opposite the
        # visible bend opening whenever the bend angle crossed zero.
        axis_local.normalize()

    axis = cage_matrix.to_3x3() @ axis_local
    if axis.length < EPSILON:
        axis = cage_matrix.to_3x3() @ local_u
    return axis


def _bend_strength_arrow_matrix(
        context, cage_matrix, world_location, properties):
    """Bend strength mark: stretch double-arrow toward bend open (±u)."""
    axis = _bend_open_axis_world(cage_matrix, properties)
    return _axis_facing_matrix(context, world_location, axis)


def _bend_direction_arrow_matrix(
        context, cage_matrix, world_location, direction=0.0):
    """Twist-direction ring in the evaluated Bend frame."""
    local_u = Vector((
        math.cos(float(direction)), 0.0, math.sin(float(direction))))
    axis = cage_matrix.to_3x3() @ local_u
    return _axis_facing_matrix(context, world_location, axis)


# Draw-face arrow → cage (alignment, direction) via shaft/lateral geometry.
# Glyph SimpleDeform_Bend_Direction_ extends along -X; lateral uses -Z so
# NEG_Y green (variant 1) → POS_Z @ -90°. Cage mode does not flip strength
# (unlike classic Is_Positive). Draw face and result alignment are decoupled.
_BEND_TREND_ALIGNMENTS = (
    "POS_X", "NEG_X", "POS_Y", "NEG_Y", "POS_Z", "NEG_Z",
)
BEND_TREND_BASES = _BEND_TREND_ALIGNMENTS
_BEND_TREND_DIRECTION_SNAPS = (
    0.0, math.pi * 0.5, -math.pi * 0.5, math.pi,
)
# Bounds unused for named alignments; satisfy _alignment_rotation signature.
_BEND_TREND_ALIGN_BOUNDS = (
    Vector((0.0, 0.0, 0.0)).freeze(),
    Vector((1.0, 1.0, 1.0)).freeze(),
)


def _snap_bend_trend_direction(raw):
    return min(
        _BEND_TREND_DIRECTION_SNAPS,
        key=lambda snap: abs(((raw - snap + math.pi) % math.tau) - math.pi),
    )


def resolve_bend_trend(draw_face, variant, frame_rotation=None):
    """Geometric map: draw-face/variant → (alignment, direction).

    1. R = draw Euler from _BEND_TREND_FACE_ROTATIONS
    2. shaft = normalize(Q @ R @ (-1,0,0)); lat = normalize(Q @ R @ (0,0,-1))
    3. alignment maximizes dot(shaft, cage_y)
    4. project lat onto cage XZ; direction = atan2(lat·z, lat·x) snapped

    Q is the current cage orientation.  The chooser is drawn in that frame,
    so resolving without it after the cage has rotated would make the clicked
    glyph and the resulting deformation point in different directions.
    """
    key = (draw_face, int(variant))
    euler = _BEND_TREND_FACE_ROTATIONS.get(key)
    if euler is None:
        direction = 0.0 if int(variant) == 0 else math.pi * 0.5
        return draw_face, direction

    rotation = Euler(euler, "XYZ").to_matrix()
    if frame_rotation is not None:
        try:
            rotation = frame_rotation.to_3x3() @ rotation
        except AttributeError:
            rotation = frame_rotation.to_matrix() @ rotation
    shaft = (rotation @ Vector((-1.0, 0.0, 0.0))).normalized()
    lat = (rotation @ Vector((0.0, 0.0, -1.0))).normalized()

    best_alignment = draw_face
    best_score = float("-inf")
    for alignment in _BEND_TREND_ALIGNMENTS:
        cage_rot = _alignment_rotation(
            alignment, _BEND_TREND_ALIGN_BOUNDS).to_matrix()
        cage_y = (cage_rot @ Vector((0.0, 1.0, 0.0))).normalized()
        score = float(shaft.dot(cage_y))
        if score > best_score:
            best_score = score
            best_alignment = alignment

    cage_rot = _alignment_rotation(
        best_alignment, _BEND_TREND_ALIGN_BOUNDS).to_matrix()
    cage_x = (cage_rot @ Vector((1.0, 0.0, 0.0))).normalized()
    cage_y = (cage_rot @ Vector((0.0, 1.0, 0.0))).normalized()
    cage_z = (cage_rot @ Vector((0.0, 0.0, 1.0))).normalized()
    latp = lat - cage_y * float(lat.dot(cage_y))
    if latp.length > EPSILON:
        latp.normalize()
    raw = math.atan2(float(latp.dot(cage_z)), float(latp.dot(cage_x)))
    direction = _snap_bend_trend_direction(raw)
    return best_alignment, direction


def bend_trend_target(draw_face, variant, *, controller=None):
    """Return (alignment, direction) for a bend-trend arrow click."""
    frame_rotation = (
        _core_module._controller_rotation_xyz(controller).to_matrix()
        if controller is not None else None)
    return resolve_bend_trend(draw_face, variant, frame_rotation)


def bend_trend_direction(target, alignment, variant, bounds=None):
    """Compatibility helper: direction only for a draw-face/variant pair."""
    _alignment, direction = resolve_bend_trend(alignment, variant)
    return direction


def _project_world(context, world_location):
    try:
        from bpy_extras import view3d_utils
        return view3d_utils.location_3d_to_region_2d(
            context.region, context.space_data.region_3d, world_location)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


def _screen_axis_from_segment(context, world_a, world_b):
    """Project a 3D segment to the region; return (dir_2d, length_px) or (None, 0)."""
    a = _project_world(context, world_a)
    b = _project_world(context, world_b)
    if a is None or b is None:
        return None, 0.0
    delta = Vector(b) - Vector(a)
    if delta.length < 2.0:
        return None, 0.0
    return tuple(delta.normalized()), float(delta.length)


def _line_progress_2d(point, a, b):
    """Parametric progress of ``point`` on segment a→b (0 at a, 1 at b)."""
    ab = Vector(b) - Vector(a)
    length_sq = ab.length_squared
    if length_sq < 1e-8:
        return 0.0
    return float((Vector(point) - Vector(a)).dot(ab) / length_sq)


def _wrapped_angle_delta(previous, current):
    return (current - previous + math.pi) % math.tau - math.pi


def _event_mod_flags(event, tweak=()):
    """Return raw Shift/Ctrl/Alt state for the active gizmo to interpret."""
    tweak = tweak or ()
    return (
        bool(event.shift) or "PRECISE" in tweak,
        bool(event.ctrl) or "SNAP" in tweak,
        bool(getattr(event, "alt", False)),
    )


def _same_rna_value(first, second):
    """Compare Blender RNA values without relying on wrapper identity.

    Blender can hand a modal operator a fresh Python wrapper for the same
    datablock after a dependency-graph update.  ``is`` would then report a
    false context change, while ordinary equality is not consistently
    implemented across RNA types.  Pointer identity is stable for the modal
    lifetime and the fallback keeps this helper usable with lightweight test
    doubles.
    """
    if first is second:
        return True
    if first is None or second is None:
        return False
    try:
        first_pointer = int(first.as_pointer())
        second_pointer = int(second.as_pointer())
        return bool(first_pointer and second_pointer and
                    first_pointer == second_pointer)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _gizmo_stage_context(gizmo, context):
    """Resolve an explicitly bound stage before consulting active context."""
    bound = (
        getattr(gizmo, "stage_target", None),
        getattr(gizmo, "stage_modifier", None),
        getattr(gizmo, "stage_controller", None),
    )
    live_bound = (
        _live_gizmo_stage(*bound)
        if all(value is not None for value in bound)
        else (None, None, None)
    )
    selected_objects = getattr(context, "selected_objects", None)
    if selected_objects is not None:
        selected = getattr(context, "object", None)
        try:
            if selected is None or selected not in tuple(selected_objects):
                # Blender may briefly leave only the native controller selected
                # while a FFD gizmo consumes a click.  An active FFD edit
                # session owns its bound stage, so do not tear down the gizmo
                # group just because the transient selection is incomplete.
                if all(value is not None for value in live_bound):
                    bound_properties = getattr(
                        live_bound[2], "sdh_cage_deform", None)
                    if bool(getattr(
                            bound_properties, "ffd_edit_mode_active", False)):
                        return live_bound
                fallback = _ffd_edit_stage_context(context)
                return fallback if fallback[0] is not None else (None, None, None)
        except (ReferenceError, RuntimeError, TypeError):
            return (None, None, None)
    if all(value is not None for value in live_bound):
        return live_bound
    return resolve_context_deform(context, fallback=False)


def _live_gizmo_stage(target, modifier, controller):
    """Return current RNA wrappers for a bound stage, or an empty context."""
    if target is None or modifier is None or controller is None:
        return (None, None, None)
    try:
        live_modifier = next((
            candidate for candidate in cage_modifiers(target)
            if _same_rna_value(candidate, modifier)
        ), None)
        if live_modifier is None:
            return (None, None, None)
        live_controller = find_controller(target, live_modifier)
        if not _same_rna_value(live_controller, controller):
            return (None, None, None)
        return target, live_modifier, live_controller
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return (None, None, None)


def _ffd_edit_stage_context(context):
    """Find the one FFD stage that currently owns the edit modal.

    GizmoGroup.poll() has no instance from which to read ``stage_*`` bindings.
    If Blender's normal object selection is temporarily changed by a gizmo
    click, scan only controllers explicitly marked as being in FFD edit mode.
    This keeps ordinary empty-space scenes free of helper gizmos while making
    an active FFD session resilient to selection churn.
    """
    try:
        objects = _core_module._data_objects_snapshot()
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return (None, None, None)
    for candidate in objects:
        properties = getattr(candidate, "sdh_cage_deform", None)
        if (
                properties is None or
                str(getattr(properties, "cage_type", "")) != "FFD" or
                not bool(getattr(properties, "ffd_edit_mode_active", False))
        ):
            continue
        try:
            target = _core_module.find_target(candidate)
            modifier = (
                _core_module.find_modifier(target, candidate)
                if target is not None else None
            )
            if (
                    target is not None and modifier is not None and
                    bool(getattr(modifier, "show_viewport", True)) and
                    bool(getattr(properties, "show_cage", True))
            ):
                return target, modifier, candidate
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return (None, None, None)


def _invoked_gizmo_stage(gizmo):
    """Keep one stage as modal owner even when another controller is active."""
    return _live_gizmo_stage(
        getattr(gizmo, "invoke_target", None),
        getattr(gizmo, "invoke_modifier", None),
        getattr(gizmo, "invoke_controller", None),
    )


def _bind_gizmo_stage(gizmo, target, modifier, controller):
    if (
            getattr(gizmo, "stage_target", None) is target and
            getattr(gizmo, "stage_modifier", None) is modifier and
            getattr(gizmo, "stage_controller", None) is controller
    ):
        return
    gizmo.stage_target = target
    gizmo.stage_modifier = modifier
    gizmo.stage_controller = controller


def _clear_gizmo_stage(gizmo):
    _bind_gizmo_stage(gizmo, None, None, None)


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
    "SHEAR": ((0.08, 0.78, 0.82), (0.62, 1.0, 1.0)),
    "FFD": ((1.0, 0.22, 0.5), (1.0, 0.72, 0.84)),
}

BEND_DIRECTION_MIN_SEPARATION_PX = 36.0
# The Bend strength arrow and Stretch handle share an end section with the
# Twist ring. Keep them on opposite sides of that ring when the operations are
# enabled instead of relying on the small generic operation lanes.
BEND_ANGLE_TWIST_SEPARATION_PX = 120.0
STRETCH_HANDLE_TWIST_SEPARATION_PX = 120.0
SHEAR_TWIST_SEPARATION_PX = 64.0
# Keep the Bend direction ring inside the evaluated cross-section. The custom
# arrow reaches 1.10 authored units, so a 0.82 radius ratio leaves visible
# clearance even at strongly deformed sections.
BEND_DIRECTION_RING_SCALE = 0.82
BEND_DIRECTION_RING_SHAPE_EXTENT = 1.10


def bend_direction_ring_scale(cross_radius):
    """Return a usable direction-ring scale capped by the cage section."""
    radius = max(abs(float(cross_radius)), EPSILON)
    maximum = radius / BEND_DIRECTION_RING_SHAPE_EXTENT
    preferred = radius * BEND_DIRECTION_RING_SCALE
    # Retain the old usability floor where the section has room for it, but a
    # tiny cage always wins over that floor and can never be overdrawn.
    minimum = min(0.32, maximum)
    return min(max(preferred, minimum), maximum)


def _enabled_deform_types(properties):
    """Return present operations that are not temporarily muted."""
    active = getattr(_core_module, "active_deform_types", None)
    if callable(active):
        try:
            return set(active(properties)).intersection(DEFORM_ORDER)
        except (AttributeError, ReferenceError, TypeError, ValueError):
            pass
    try:
        selected = set(properties.deform_types)
    except (AttributeError, TypeError, ValueError):
        return set()
    try:
        muted = set(properties.muted_deform_types)
    except (AttributeError, TypeError, ValueError):
        muted = set()
    return selected.difference(muted).intersection(DEFORM_ORDER)


def _primary_enabled_type(properties):
    ordered = _ordered_enabled_deform_types(properties)
    return ordered[0] if ordered else "BEND"


def _screen_offset_world(context, world_location, x_pixels):
    """Move a world point horizontally in the viewport at the same depth."""
    if abs(float(x_pixels)) < EPSILON:
        return Vector(world_location)
    try:
        from bpy_extras import view3d_utils
        screen = view3d_utils.location_3d_to_region_2d(
            context.region, context.space_data.region_3d, world_location)
        if screen is None:
            return None
        return view3d_utils.region_2d_to_location_3d(
            context.region,
            context.space_data.region_3d,
            Vector((screen.x + float(x_pixels), screen.y)),
            world_location,
        )
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


def _screen_point_with_clearance(point, avoid, min_distance):
    """Move ``point`` only enough to clear ``avoid`` in screen pixels."""
    point = Vector(point)
    avoid = Vector(avoid)
    delta = point - avoid
    minimum = max(float(min_distance), 0.0)
    if delta.length >= minimum:
        return point
    if delta.length <= EPSILON:
        delta = Vector((1.0, 0.0))
    else:
        delta.normalize()
    return avoid + delta * minimum


def _screen_separate_world(
        context, world_location, avoid_location, min_distance):
    """Keep two world anchors independently targetable in the viewport."""
    point = _project_world(context, world_location)
    avoid = _project_world(context, avoid_location)
    if point is None or avoid is None:
        return None
    separated = _screen_point_with_clearance(point, avoid, min_distance)
    if (separated - Vector(point)).length <= EPSILON:
        return Vector(world_location)
    try:
        from bpy_extras import view3d_utils
        return view3d_utils.region_2d_to_location_3d(
            context.region,
            context.space_data.region_3d,
            separated,
            world_location,
        )
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


def _parameter_handle_lane(properties, deform_type):
    """Return the operation's logical lane and horizontal pixel offset."""
    enabled = _ordered_enabled_deform_types(properties)
    if len(enabled) <= 1 or deform_type not in enabled:
        return None

    lane = float(enabled.index(deform_type)) - (len(enabled) - 1.0) * 0.5
    lane_offset = lane * 42.0
    if deform_type == "BEND" and "TWIST" in enabled:
        # Put the angle arrow fully to the left of the Twist ring. Keeping the
        # side stable makes the control predictable when the stack is reordered.
        lane_offset = -BEND_ANGLE_TWIST_SEPARATION_PX
    elif deform_type == "STRETCH" and "TWIST" in enabled:
        # Stretch uses the opposite side so it remains independently selectable
        # when Bend, Twist, and Stretch are enabled together.
        lane_offset = STRETCH_HANDLE_TWIST_SEPARATION_PX
    elif deform_type == "SHEAR" and "TWIST" in enabled:
        # Twist remains centered on the deformation axis; Shear sits to its
        # right so both compact controls keep independent click regions.
        lane_offset = SHEAR_TWIST_SEPARATION_PX
    return lane, lane_offset


def _separate_parameter_handle_world(
        context, target, controller, deform_type, world_point):
    """Apply one operation lane to an already evaluated world anchor."""
    lane_data = _parameter_handle_lane(
        controller.sdh_cage_deform, deform_type)
    if lane_data is None:
        return Vector(world_point)
    lane, lane_offset = lane_data
    separated = _screen_offset_world(context, world_point, lane_offset)
    if separated is not None:
        return separated
    # A cage-axis fallback keeps headless/tests deterministic.
    properties = controller.sdh_cage_deform
    enabled = _ordered_enabled_deform_types(properties)
    cage_matrix = cage_local_matrix(target, controller)
    axis = cage_matrix.to_3x3() @ Vector((1.0, 0.0, 0.0))
    if axis.length <= EPSILON:
        axis = Vector((1.0, 0.0, 0.0))
    else:
        axis.normalize()
    spacing = max(min(abs(float(properties.size[0])),
                      abs(float(properties.size[2]))) * 0.28, EPSILON)
    if deform_type == "BEND" and "TWIST" in enabled:
        return world_point - axis * (spacing * 2.0)
    if deform_type == "STRETCH" and "TWIST" in enabled:
        return world_point + axis * (spacing * 2.0)
    if deform_type == "SHEAR" and "TWIST" in enabled:
        return world_point + axis * spacing
    return world_point + axis * lane * spacing


def parameter_handle_world(context, target, controller, deform_type, *,
                           separate=True):
    """Return a stable handle anchor for one operation in a combined cage."""
    properties = controller.sdh_cage_deform
    half = Vector(properties.size) * 0.5
    if properties.origin in {"CENTER", "SYMMETRIC"}:
        handle_y = 0.0
    elif deform_type == "TAPER":
        handle_y = half.y if properties.origin == "TOP" else -half.y
    else:
        handle_y = -half.y if properties.origin == "TOP" else half.y
    handle_x = half.x * 0.55 if deform_type == "TAPER" else 0.0

    cage_matrix = cage_local_matrix(target, controller)
    local_point = deform_point_for_display(
        (handle_x, handle_y, 0.0), properties)
    world_point = cage_matrix @ Vector(local_point)
    if not separate:
        return world_point
    return _separate_parameter_handle_world(
        context, target, controller, deform_type, world_point)


def _ordered_enabled_deform_types(properties):
    """Read the public ordered-operation API with a legacy fallback."""
    enabled = _enabled_deform_types(properties)
    ordered = getattr(_core_module, "ordered_deform_types", None)
    if callable(ordered):
        try:
            return tuple(name for name in ordered(properties) if name in enabled)
        except (AttributeError, ReferenceError, TypeError, ValueError):
            pass
    return tuple(name for name in DEFORM_ORDER if name in enabled)


def cage_picker_geometry_signature(properties):
    """Return an exact, hashable signature for deformed cage geometry."""
    def floats(values):
        return tuple(float(value).hex() for value in values)

    curve_signature = ()
    if str(getattr(properties, "cage_type", "STANDARD")) == "CURVE":
        try:
            from .curve import curve_preview_signature
            curve_signature = curve_preview_signature(properties)
        except (AttributeError, ImportError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            curve_signature = ("SDH_CURVE_PREVIEW_UNAVAILABLE",)

    return (
        "SDH_CAGE_WIRE_V2",
        floats(properties.size),
        _ordered_enabled_deform_types(properties),
        float(properties.bend_strength).hex(),
        float(properties.bend_direction).hex(),
        float(properties.twist_strength).hex(),
        float(properties.taper_factor).hex(),
        float(properties.stretch_factor).hex(),
        floats(getattr(properties, "shear_factors", (0.0, 0.0))),
        floats(getattr(properties, "ffd_offsets", (0.0,) * 24)),
        str(properties.mode),
        str(properties.origin),
        bool(properties.preserve_volume),
        floats(properties.top_scale),
        floats(properties.bottom_scale),
        floats(properties.top_offset),
        floats(properties.bottom_offset),
        curve_signature,
    )


def cage_preview_geometry_state(properties):
    """Return the full preview signature and its precomputed post-frame."""
    controller = getattr(properties, "id_data", None)
    chain_display_state = _core_module.chain_display_preview_state(properties)
    if chain_display_state:
        current_index = int(chain_display_state["current_index"])
        input_frame, output_frame = chain_display_state["frames"][current_index]
    else:
        input_frame, output_frame = (
            _core_module.chain_conjugation_frames_for_controller(
                controller, properties=properties))
    prefix_state = _core_module.chain_global_prefix_preview_state(properties)
    stretch_state = _core_module.chain_global_stretch_preview_state(
        properties)
    input_frame_signature = tuple(
        float(component).hex()
        for vector in input_frame
        for component in vector
    )
    frame_signature = tuple(
        float(component).hex()
        for vector in output_frame
        for component in vector
    )
    signature = (
        cage_picker_geometry_signature(properties),
        input_frame_signature,
        frame_signature,
        _core_module.chain_global_prefix_preview_signature(prefix_state),
        _core_module.chain_global_stretch_preview_signature(
            stretch_state),
        _core_module.chain_display_preview_signature(
            chain_display_state),
    )
    _cache_geometry(
        _CHAIN_DISPLAY_BY_PREVIEW_SIGNATURE, signature,
        chain_display_state)
    return signature, output_frame


def _cache_geometry(cache, key, value):
    """Bound redraw caches while retaining the current drag state."""
    if len(cache) >= _GEOMETRY_CACHE_LIMIT:
        cache.clear()
    cache[key] = value
    return value


def cage_preview_ring_vertices(
        properties, ring_positions=(0.0, 0.25, 0.5, 0.75, 1.0),
        *, preview_state=None, _chain_display_state=None):
    """Return structural cage rings without duplicating longitudinal rails.

    Curve effect boundaries use this lightweight path so their colored caps
    remain visually separate from the stable full-source cage.  Keeping the
    rings independent also avoids rebuilding all sampled rails while a user
    drags only the top or bottom effect boundary.
    """
    ring_positions = tuple(float(value) for value in ring_positions)
    preview_signature, preview_output_frame = (
        cage_preview_geometry_state(properties)
        if preview_state is None else preview_state)
    signature = (
        "SDH_CAGE_RINGS_V1",
        preview_signature,
        tuple(value.hex() for value in ring_positions),
    )
    cached = _CAGE_WIRE_GEOMETRY_CACHE.get(signature)
    if cached is not None:
        return cached

    half = Vector(properties.size) * 0.5
    size_y = float(properties.size[1])
    chain_stretch_state = (
        _core_module.chain_global_stretch_preview_state(properties))
    chain_prefix_state = (
        _core_module.chain_global_prefix_preview_state(properties))
    chain_display_state = (
        _CHAIN_DISPLAY_BY_PREVIEW_SIGNATURE.get(preview_signature)
        if _chain_display_state is None else _chain_display_state)
    if chain_display_state is None:
        chain_display_state = _core_module.chain_display_preview_state(properties)
    curve_deformer = None
    if str(getattr(properties, "cage_type", "STANDARD")) == "CURVE":
        try:
            from .curve import curve_preview_deformer
            curve_deformer = curve_preview_deformer(
                properties, apply_effect_range=False)
        except (AttributeError, ImportError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            curve_deformer = None
    corner_signs = ((-1, -1), (-1, 1), (1, 1), (1, -1))
    vertices = []
    for ring_t in ring_positions:
        ring_y = -half.y + size_y * ring_t
        ring = tuple(
            tuple(deform_point_for_display(
                (x_sign * half.x, ring_y, z_sign * half.z), properties,
                chain_prefix_state=chain_prefix_state,
                chain_stretch_state=chain_stretch_state,
                chain_display_state=chain_display_state,
                curve_deformer_override=curve_deformer,
                preview_output_frame=preview_output_frame))
            for x_sign, z_sign in corner_signs
        )
        for index, next_index in ((0, 1), (1, 2), (2, 3), (3, 0)):
            vertices.extend((ring[index], ring[next_index]))
    return _cache_geometry(
        _CAGE_WIRE_GEOMETRY_CACHE, signature, tuple(vertices))


def cage_preview_wire_vertices(
        properties, steps=24, ring_positions=(0.0, 0.25, 0.5, 0.75, 1.0),
        *, preview_state=None, throttle_key=None):
    """Return cached deformed cage rails/rings as independent line pairs.

    Active cage drawing, the bend-trend chooser, and inactive cage selection
    all use this sampler.  Every point is evaluated through the core property
    path, so a user-defined operation order is reflected without viewport-only
    deformation logic.

    ``throttle_key`` opts one draw consumer into rate-limited rebuilds: while
    its content keeps changing (an interactive drag), at most one rebuild per
    throttle window runs and the previous shape is reused in between.
    """
    if throttle_key is not None:
        use_stale, stale = _throttled_wire_shape(throttle_key)
        if use_stale:
            return stale
    steps = max(int(steps), 1)
    ring_positions = tuple(float(value) for value in ring_positions)
    preview_signature, preview_output_frame = (
        cage_preview_geometry_state(properties)
        if preview_state is None else preview_state)
    signature = (
        preview_signature,
        steps,
        tuple(value.hex() for value in ring_positions),
    )
    cached = _CAGE_WIRE_GEOMETRY_CACHE.get(signature)
    if cached is not None:
        if throttle_key is not None:
            _store_wire_shape(throttle_key, signature, cached, rebuilt=False)
        return cached

    half = Vector(properties.size) * 0.5
    size_y = float(properties.size[1])
    chain_stretch_state = (
        _core_module.chain_global_stretch_preview_state(properties))
    chain_prefix_state = (
        _core_module.chain_global_prefix_preview_state(properties))
    chain_display_state = _CHAIN_DISPLAY_BY_PREVIEW_SIGNATURE.get(
        preview_signature)
    if chain_display_state is None:
        chain_display_state = _core_module.chain_display_preview_state(properties)
    curve_deformer = None
    if str(getattr(properties, "cage_type", "STANDARD")) == "CURVE":
        try:
            from .curve import curve_preview_deformer
            curve_deformer = curve_preview_deformer(
                properties, apply_effect_range=False)
        except (AttributeError, ImportError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            curve_deformer = None
    corner_signs = ((-1, -1), (-1, 1), (1, 1), (1, -1))
    vertices = []

    for x_sign, z_sign in corner_signs:
        rail = tuple(
            tuple(deform_point_for_display((
                x_sign * half.x,
                -half.y + size_y * index / steps,
                z_sign * half.z,
            ), properties,
                chain_prefix_state=chain_prefix_state,
                chain_stretch_state=chain_stretch_state,
                chain_display_state=chain_display_state,
                curve_deformer_override=curve_deformer,
                preview_output_frame=preview_output_frame))
            for index in range(steps + 1)
        )
        for index in range(steps):
            vertices.extend((rail[index], rail[index + 1]))

    vertices.extend(cage_preview_ring_vertices(
        properties,
        ring_positions,
        preview_state=(preview_signature, preview_output_frame),
        _chain_display_state=chain_display_state,
    ))
    result = _cache_geometry(
        _CAGE_WIRE_GEOMETRY_CACHE, signature, tuple(vertices))
    if throttle_key is not None:
        _store_wire_shape(throttle_key, signature, result, rebuilt=True)
    return result


def cage_preview_wire_indices(
        steps=24, ring_positions=(0.0, 0.25, 0.5, 0.75, 1.0)):
    """Return cached rail/ring indices for :func:`cage_preview_wire_vertices`."""
    steps = max(int(steps), 1)
    ring_count = len(tuple(ring_positions))
    key = (steps, ring_count)
    cached = _CAGE_WIRE_INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    rail_vertex_count = 4 * steps * 2
    rail_indices = tuple(
        (index, index + 1) for index in range(0, rail_vertex_count, 2))
    total_vertex_count = rail_vertex_count + ring_count * 4 * 2
    ring_indices = tuple(
        (index, index + 1)
        for index in range(rail_vertex_count, total_vertex_count, 2))
    return _cache_geometry(
        _CAGE_WIRE_INDEX_CACHE, key, (rail_indices, ring_indices))


def cage_preview_guide_geometry(
        properties, rail_offsets, steps=24, *, preview_state=None):
    """Return cached combined guide rails and their endpoint indices."""
    steps = max(int(steps), 1)
    rail_offsets = tuple(
        (float(rail_x), float(rail_z))
        for rail_x, rail_z in rail_offsets)
    preview_signature, preview_output_frame = (
        cage_preview_geometry_state(properties)
        if preview_state is None else preview_state)
    signature = (
        "SDH_CAGE_GUIDES_V1",
        preview_signature,
        tuple(
            (rail_x.hex(), rail_z.hex())
            for rail_x, rail_z in rail_offsets),
        steps,
    )
    cached = _CAGE_GUIDE_GEOMETRY_CACHE.get(signature)
    if cached is not None:
        return cached

    half = Vector(properties.size) * 0.5
    size_y = float(properties.size[1])
    chain_stretch_state = (
        _core_module.chain_global_stretch_preview_state(properties))
    chain_prefix_state = (
        _core_module.chain_global_prefix_preview_state(properties))
    chain_display_state = _CHAIN_DISPLAY_BY_PREVIEW_SIGNATURE.get(
        preview_signature)
    if chain_display_state is None:
        chain_display_state = _core_module.chain_display_preview_state(properties)
    curve_deformer = None
    if str(getattr(properties, "cage_type", "STANDARD")) == "CURVE":
        try:
            from .curve import curve_preview_deformer
            curve_deformer = curve_preview_deformer(
                properties, apply_effect_range=False)
        except (AttributeError, ImportError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            curve_deformer = None
    vertices = []
    indices = []
    endpoints = []
    for rail_x, rail_z in rail_offsets:
        start = len(vertices)
        vertices.extend(
            tuple(deform_point_for_display(
                (
                    rail_x,
                    -half.y + size_y * index / steps,
                    rail_z,
                ),
                properties,
                chain_prefix_state=chain_prefix_state,
                chain_stretch_state=chain_stretch_state,
                chain_display_state=chain_display_state,
                curve_deformer_override=curve_deformer,
                preview_output_frame=preview_output_frame,
            ))
            for index in range(steps + 1)
        )
        indices.extend(
            (start + index, start + index + 1)
            for index in range(steps))
        endpoints.append(start + steps)
    return _cache_geometry(
        _CAGE_GUIDE_GEOMETRY_CACHE,
        signature,
        (tuple(vertices), tuple(indices), tuple(endpoints)),
    )


CAGE_STAGE_PICKER_SCALE = 0.30


def cage_picker_wire_vertices(properties, steps=12, *, preview_state=None):
    """Build a compact picker centered on the evaluated cage midpoint."""
    preview_signature, preview_output_frame = (
        cage_preview_geometry_state(properties)
        if preview_state is None else preview_state)
    signature = (
        "SDH_CAGE_PICKER_COMPACT_V1",
        preview_signature,
        int(steps),
        float(CAGE_STAGE_PICKER_SCALE).hex(),
    )
    cached = _CAGE_WIRE_GEOMETRY_CACHE.get(signature)
    if cached is not None:
        return cached

    full_vertices = cage_preview_wire_vertices(
        properties, steps=steps, ring_positions=(0.0, 0.5, 1.0),
        preview_state=(preview_signature, preview_output_frame))
    chain_stretch_state = (
        _core_module.chain_global_stretch_preview_state(properties))
    chain_prefix_state = (
        _core_module.chain_global_prefix_preview_state(properties))
    chain_display_state = _CHAIN_DISPLAY_BY_PREVIEW_SIGNATURE.get(
        preview_signature)
    if chain_display_state is None:
        chain_display_state = _core_module.chain_display_preview_state(properties)
    curve_deformer = None
    if str(getattr(properties, "cage_type", "STANDARD")) == "CURVE":
        try:
            from .curve import curve_preview_deformer
            curve_deformer = curve_preview_deformer(
                properties, apply_effect_range=False)
        except (AttributeError, ImportError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            curve_deformer = None
    center = Vector(deform_point_for_display(
        (0.0, 0.0, 0.0), properties,
        chain_prefix_state=chain_prefix_state,
        chain_stretch_state=chain_stretch_state,
        chain_display_state=chain_display_state,
        curve_deformer_override=curve_deformer,
        preview_output_frame=preview_output_frame))
    vertices = tuple(
        tuple(center + (Vector(vertex) - center) * CAGE_STAGE_PICKER_SCALE)
        for vertex in full_vertices
    )
    return _cache_geometry(_CAGE_WIRE_GEOMETRY_CACHE, signature, vertices)


class SDHCageStagePickerGizmo(Gizmo):
    """Compact, non-editing handle for selecting an inactive cage stage."""

    bl_idname = "SDH_GT_cage_stage_picker"
    bl_label = "Select Cage Stage"
    bl_target_properties = ()

    __slots__ = (
        "custom_shape",
        "geometry_signature",
        "target",
        "controller",
        "modifier_uuid",
        "stage_operator",
    )

    def setup(self):
        self.custom_shape = None
        self.geometry_signature = None
        # Vertices are authored in real cage units. Blender's default Gizmo
        # scale would otherwise magnify the deformed local offset around the
        # controller origin and detach the picker from its preview wire.
        self.use_draw_scale = False
        self.scale_basis = 1.0
        self.use_tooltip = True
        self.use_select_background = True
        self.use_draw_modal = False
        # Keep the compact handle easy to select without covering the cage.
        self.line_width = 6.0
        self.select_bias = 0.05
        self.hide = True
        self.target = None
        self.controller = None
        self.modifier_uuid = ""
        self.stage_operator = None

    def configure(self, target, modifier, controller):
        previously_bound = (
            _rna_pointer(getattr(self, "target", None)) ==
            _rna_pointer(target) and
            _rna_pointer(getattr(self, "controller", None)) ==
            _rna_pointer(controller))
        self.target = target
        self.controller = controller
        self.modifier_uuid = str(cage_modifier_uuid(modifier) or "")
        properties = controller.sdh_cage_deform
        freeze_preview = bool(
            previously_bound and self.custom_shape is not None and
            _freeze_for_end_shape_drag(target, controller))
        if freeze_preview:
            _request_throttled_redraw()
        else:
            signature, output_frame = cage_preview_geometry_state(properties)
            picker_signature = ("SDH_CAGE_PICKER_COMPACT_V1", signature)
            if getattr(self, "geometry_signature", None) != picker_signature:
                throttle_key = ("PICKER", id(self))
                use_stale, _stale = _throttled_wire_shape(throttle_key)
                if use_stale and self.custom_shape is not None:
                    # Keep the previous picker wire during a drag burst; the
                    # deferred redraw scheduled above rebuilds it when idle.
                    pass
                else:
                    vertices = cage_picker_wire_vertices(
                        properties, preview_state=(signature, output_frame))
                    shape_factory = getattr(self, "new_custom_shape", None)
                    self.custom_shape = (
                        shape_factory("LINES", vertices)
                        if callable(shape_factory) else vertices)
                    self.geometry_signature = picker_signature
                    _store_wire_shape(
                        throttle_key, picker_signature, True, rebuilt=True)
            self.matrix_basis = cage_local_matrix(target, controller)
        style = CONTROLLER_STYLES.get(
            _primary_enabled_type(properties),
            CONTROLLER_STYLES["BEND"],
        )
        rgb = tuple(style[1][:3])
        self.color = rgb
        self.color_highlight = tuple(min(1.0, channel * 1.45) for channel in rgb)
        self.alpha = 0.10
        self.alpha_highlight = 0.42
        # Picker geometry is an interactive control, so it must stay
        # selectable even when the cage preview itself is depth-tested.
        self.use_select_background = gizmo_depth_test() == "ALWAYS"
        if self.stage_operator is not None:
            self.stage_operator.modifier_uuid = self.modifier_uuid
        self.hide = False

    def draw(self, _context):
        if not self.hide and self.custom_shape is not None:
            draw_cage_custom_shape(self, self.custom_shape)

    def draw_select(self, _context, select_id):
        if not self.hide and self.custom_shape is not None:
            draw_cage_custom_shape(
                self, self.custom_shape, select_id=select_id)


class _SDHCageParameterGizmo(Gizmo):
    """Shared modal mechanics for one independently stored cage operation."""

    bl_target_properties = ()

    DEFORM_TYPE = ""
    PROPERTY_NAME = ""
    SHAPE_NAME = ""

    __slots__ = (
        "custom_shape",
        "initial_value",
        "initial_direction",
        "original_value",
        "original_direction",
        "initial_mouse",
        "axis_screen",
        "axis_scale",
        "line_world_a",
        "line_world_b",
        "line_t0",
        "line_span",
        "twist_center",
        "twist_last_angle",
        "twist_delta",
        "twist_axis",
        "twist_handle",
        "stage_target",
        "stage_modifier",
        "stage_controller",
        "invoke_target",
        "invoke_modifier",
        "invoke_controller",
        "_mod_flags",
    )

    def setup(self):
        self.custom_shape = self.new_custom_shape(
            "TRIS", _shape_vertices(getattr(self, "SHAPE_NAME", "STRETCH")))
        self.use_tooltip = True
        self.use_draw_modal = True
        self.use_draw_value = False
        self.use_draw_scale = True
        # Avoid Blender's default scale_basis=1.0 flash on first draw.
        self.scale_basis = COMPACT_PARAMETER_SCALE
        self.initial_value = 0.0
        self.initial_direction = 0.0
        self.original_value = 0.0
        self.original_direction = 0.0
        self.stage_target = None
        self.stage_modifier = None
        self.stage_controller = None
        self.invoke_target = None
        self.invoke_modifier = None
        self.invoke_controller = None

    def _update_matrix(self, context):
        if _consume_matrix_fresh(self):
            return True
        aggregate_context = getattr(self, "aggregate_stage_context", None)
        if aggregate_context is None:
            target, _modifier, controller = _gizmo_stage_context(self, context)
        else:
            target, _modifier, controller = aggregate_context
        if target is None or controller is None:
            return False
        properties = controller.sdh_cage_deform
        if self.DEFORM_TYPE not in _enabled_deform_types(properties):
            return False
        handle = parameter_handle_world(
            context, target, controller, self.DEFORM_TYPE,
            separate=self.DEFORM_TYPE != "TWIST")
        cage_matrix = cage_local_matrix(target, controller)
        if self.DEFORM_TYPE == "TWIST":
            half_y = float(properties.size[1]) * 0.5
            section_y = (
                0.0 if properties.origin in {"CENTER", "SYMMETRIC"}
                else -half_y if properties.origin == "TOP" else half_y)
            frame, _cross_radius = _deformed_section_frame(
                cage_matrix, properties, section_y, 0.0)
            self.matrix_basis = _twist_ring_matrix(
                cage_matrix, frame.translation, properties.twist_strength,
                frame_matrix=frame)
            self.use_draw_scale = True
            self.scale_basis = COMPACT_PARAMETER_SCALE
        elif self.DEFORM_TYPE == "STRETCH":
            self.matrix_basis = _stretch_arrow_matrix(
                context, cage_matrix, handle, properties.origin)
            self.scale_basis = STRENGTH_ARROW_SCALE
        elif self.DEFORM_TYPE == "BEND":
            self.matrix_basis = _bend_strength_arrow_matrix(
                context, cage_matrix, handle, properties)
            self.scale_basis = STRENGTH_ARROW_SCALE
        elif self.DEFORM_TYPE == "TAPER":
            self.matrix_basis = _billboard_matrix(context, handle)
            self.scale_basis = COMPACT_PARAMETER_SCALE
        else:
            self.matrix_basis = _billboard_matrix(context, handle)
            self.scale_basis = COMPACT_PARAMETER_SCALE
        self.color, self.color_highlight = TYPE_HANDLE_COLORS[self.DEFORM_TYPE]
        return True

    def draw(self, context):
        if self._update_matrix(context):
            draw_cage_custom_shape(self, self.custom_shape)

    def draw_select(self, context, select_id):
        if self._update_matrix(context):
            draw_cage_custom_shape(
                self, self.custom_shape, select_id=select_id)

    def invoke(self, context, event):
        try:
            target, modifier, controller = _gizmo_stage_context(self, context)
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            return {"CANCELLED"}
        if target is None or modifier is None or controller is None:
            return {"CANCELLED"}
        properties = controller.sdh_cage_deform
        if self.DEFORM_TYPE not in _enabled_deform_types(properties):
            return {"CANCELLED"}
        self.invoke_target = target
        self.invoke_modifier = modifier
        self.invoke_controller = controller
        shared_stretch = (
            chain_global_stretch_value(controller, modifier)
            if self.DEFORM_TYPE == "STRETCH" else None
        )
        if shared_stretch is not None:
            sync_chain_global_stretch_from_stage(controller, shared_stretch)
        self.initial_value = (
            float(shared_stretch) if shared_stretch is not None else
            float(getattr(properties, self.PROPERTY_NAME))
        )
        self.initial_direction = float(properties.bend_direction)
        self.original_value = self.initial_value
        self.original_direction = self.initial_direction
        self.initial_mouse = (event.mouse_region_x, event.mouse_region_y)
        # Fallback: horizontal screen drag (legacy left/right).
        self.axis_screen = (1.0, 0.0)
        self.axis_scale = 0.01
        self.line_world_a = None
        self.line_world_b = None
        self.line_t0 = 0.0
        self.line_span = 1.0
        self.twist_center = None
        self.twist_last_angle = None
        self.twist_delta = 0.0
        self.twist_axis = None
        self.twist_handle = None
        self._mod_flags = _event_mod_flags(event)
        cage_matrix = cage_local_matrix(target, controller)
        handle = parameter_handle_world(
            context, target, controller, self.DEFORM_TYPE,
            separate=self.DEFORM_TYPE != "TWIST")
        if self.DEFORM_TYPE == "TWIST":
            half_y = float(properties.size[1]) * 0.5
            section_y = (
                0.0 if properties.origin in {"CENTER", "SYMMETRIC"}
                else -half_y if properties.origin == "TOP" else half_y)
            frame, _radius = _deformed_section_frame(
                cage_matrix, properties, section_y, 0.0)
            self.twist_handle = frame.translation.copy()
            axis = frame.to_3x3() @ Vector((0.0, 0.0, 1.0))
            if axis.length > EPSILON:
                axis.normalize()
            self.twist_axis = axis
            self.twist_center = _project_world(context, self.twist_handle)
            self.twist_last_angle = _mouse_angle(self.twist_center, event)
        else:
            # Classic limits style: undeformed cage axis → 2D, value from
            # mouse progress on that line (not raw left/right pixels).
            half_y = float(properties.size[1]) * 0.5
            if self.DEFORM_TYPE == "BEND":
                axis3 = _bend_open_axis_world(cage_matrix, properties)
                if axis3.length > EPSILON:
                    axis3.normalize()
                ref = max(float(min(properties.size)) * 0.5, 0.25)
                world_a = handle - axis3 * ref
                world_b = handle + axis3 * ref
                self.line_span = math.pi
            else:
                # STRETCH / TAPER: origin end → free end along cage Y.
                if properties.origin == "TOP":
                    a_local = Vector((0.0, half_y, 0.0))
                    b_local = Vector((0.0, -half_y, 0.0))
                else:
                    a_local = Vector((0.0, -half_y, 0.0))
                    b_local = Vector((0.0, half_y, 0.0))
                world_a = cage_matrix @ a_local
                world_b = cage_matrix @ b_local
                self.line_span = 1.0
            a2d = _project_world(context, world_a)
            b2d = _project_world(context, world_b)
            if a2d is not None and b2d is not None and (
                    Vector(b2d) - Vector(a2d)).length >= 2.0:
                self.line_world_a = Vector(world_a).freeze()
                self.line_world_b = Vector(world_b).freeze()
                mouse = Vector((event.mouse_region_x, event.mouse_region_y))
                self.line_t0 = _line_progress_2d(mouse, a2d, b2d)
                axis_2d, _pixels = _screen_axis_from_segment(
                    context, world_a, world_b)
                if axis_2d is not None:
                    self.axis_screen = axis_2d
        return {"RUNNING_MODAL"}

    def _axis_line_delta(self, context, event):
        """Value delta from classic 3D→2D line progress (a→b)."""
        if self.line_world_a is None or self.line_world_b is None:
            mouse_delta = Vector((
                event.mouse_region_x - self.initial_mouse[0],
                event.mouse_region_y - self.initial_mouse[1],
            ))
            return mouse_delta.dot(Vector(self.axis_screen)) * self.axis_scale
        a2d = _project_world(context, self.line_world_a)
        b2d = _project_world(context, self.line_world_b)
        if a2d is None or b2d is None or (
                Vector(b2d) - Vector(a2d)).length < 2.0:
            mouse_delta = Vector((
                event.mouse_region_x - self.initial_mouse[0],
                event.mouse_region_y - self.initial_mouse[1],
            ))
            return mouse_delta.dot(Vector(self.axis_screen)) * self.axis_scale
        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        t = _line_progress_2d(mouse, a2d, b2d)
        return (t - self.line_t0) * self.line_span

    def _set_float_if_changed(self, properties, name, value, context=None):
        """Avoid RNA callbacks when a high-frequency event changes nothing."""
        try:
            current = float(getattr(properties, name))
            requested = float(value)
        except (AttributeError, TypeError, ValueError):
            return False
        if abs(current - requested) <= EPSILON:
            return False
        _begin_gizmo_undo(self)
        setattr(properties, name, requested)
        return True

    def modal(self, context, event, _tweak):
        try:
            target, modifier, controller = _invoked_gizmo_stage(self)
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            return {"CANCELLED"}
        if (
                target is None or modifier is None or controller is None
        ):
            return {"CANCELLED"}
        properties = controller.sdh_cage_deform
        flags = _event_mod_flags(event, _tweak)
        event_type = str(getattr(event, "type", ""))
        motion_event = event_type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}
        # Rebase when Shift/Ctrl/Alt change so precision/snap never jumps the
        # value (or cage transform) from the full mouse travel so far.
        if flags != self._mod_flags:
            self.initial_value = float(getattr(properties, self.PROPERTY_NAME))
            self.initial_direction = float(properties.bend_direction)
            self.initial_mouse = (event.mouse_region_x, event.mouse_region_y)
            self.twist_delta = 0.0
            if self.twist_center is not None:
                self.twist_last_angle = _mouse_angle(self.twist_center, event)
            if self.line_world_a is not None and self.line_world_b is not None:
                a2d = _project_world(context, self.line_world_a)
                b2d = _project_world(context, self.line_world_b)
                if a2d is not None and b2d is not None:
                    mouse = Vector((
                        event.mouse_region_x, event.mouse_region_y))
                    self.line_t0 = _line_progress_2d(mouse, a2d, b2d)
            self._mod_flags = flags
            # Modifier transitions are bookkeeping events.  Do not also apply
            # their mouse position; trackpad/Windows input can deliver the
            # transition without a corresponding motion sample.
            return {"RUNNING_MODAL"}
        # Gizmo modal callbacks also receive timer, tweak, button-release and
        # other events.  Only motion can change a drag value; filtering the
        # rest prevents repeated RNA writes and downstream chain reconnects.
        if not motion_event:
            return {"RUNNING_MODAL"}
        precise, snap, alt = flags

        if self.DEFORM_TYPE == "TWIST" and self.twist_last_angle is not None:
            current_angle = _mouse_angle(self.twist_center, event)
            if current_angle is not None:
                # Base negate matches top-down (+Y) view; flip when looking
                # from the opposite end of the twist axis (bottom-up).
                view_sign = 1.0
                if self.twist_axis is not None and self.twist_handle is not None:
                    view_sign = _twist_view_sign(
                        context, self.twist_handle, self.twist_axis)
                self.twist_delta += view_sign * (-_wrapped_angle_delta(
                    self.twist_last_angle, current_angle))
                self.twist_last_angle = current_angle
            delta = self.twist_delta * (0.1 if precise else 1.0)
            if snap:
                step = math.radians(5.0)
                delta = round(delta / step) * step
            value = self.initial_value + delta
            self._set_float_if_changed(
                properties, self.PROPERTY_NAME, value, context)
            value_label = bpy.app.translations.pgettext_iface(
                getattr(self, "bl_label", self.DEFORM_TYPE.title()))
            label = f"{value_label}: {math.degrees(value):.1f}°"
        else:
            delta = _SDHCageParameterGizmo._axis_line_delta(
                self, context, event)
            if precise:
                delta *= 0.1
            if self.DEFORM_TYPE == "BEND":
                # The bend glyph is authored toward the opening, while the
                # positive bend angle advances the opposite tangent in the
                # evaluator.  Invert only this straight-line drag mapping so
                # dragging the handle to the right increases the displayed
                # bend value instead of decreasing it.
                # Both normal bend-angle dragging and Alt direction dragging
                # use the same screen-to-cage orientation.  Keeping Alt on
                # the old sign made the two controls feel mirrored.
                delta = -delta
                if snap:
                    step = math.radians(5.0)
                    delta = round(delta / step) * step
                if alt:
                    value = self.initial_direction + delta
                    self._set_float_if_changed(
                        properties, "bend_direction", value, context)
                    value_label = bpy.app.translations.pgettext_iface(
                        "Bend Direction")
                else:
                    value = self.initial_value + delta
                    self._set_float_if_changed(
                        properties, self.PROPERTY_NAME, value, context)
                    value_label = bpy.app.translations.pgettext_iface(
                        getattr(self, "bl_label", self.DEFORM_TYPE.title()))
                label = f"{value_label}: {math.degrees(value):.1f}°"
            else:
                if snap:
                    delta = round(delta * 10.0) / 10.0
                value = self.initial_value + delta
                self._set_float_if_changed(
                    properties, self.PROPERTY_NAME, value, context)
                value_label = bpy.app.translations.pgettext_iface(
                    getattr(self, "bl_label", self.DEFORM_TYPE.title()))
                label = f"{value_label}: {value:.3f}"
        if context.area:
            shortcut = (
                "Drag Around Ring • Shift Precise • Ctrl Snap"
                if self.DEFORM_TYPE == "TWIST"
                else (
                    "Alt Direction \u2022 Shift Precise \u2022 Ctrl Snap"
                    if self.DEFORM_TYPE == "BEND"
                    else "Drag Along Axis • Shift Precise • Ctrl Snap"
                )
            )
            context.area.header_text_set(
                label + "   |   " + bpy.app.translations.pgettext_iface(shortcut))
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def exit(self, context, cancel):
        controller = getattr(self, "invoke_controller", None)
        if cancel and controller:
            try:
                properties = controller.sdh_cage_deform
                setattr(
                    properties, self.PROPERTY_NAME,
                    getattr(self, "original_value", self.initial_value))
                if self.DEFORM_TYPE == "BEND":
                    properties.bend_direction = getattr(
                        self, "original_direction", self.initial_direction)
            except (AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError):
                pass
        _finish_gizmo_undo(
            self, cancel=cancel,
            message=f"Cage {getattr(self, 'bl_label', 'Parameter')}")
        if context.area:
            context.area.header_text_set(None)
            context.area.tag_redraw()


class SDHCageBendStrengthGizmo(_SDHCageParameterGizmo):
    bl_idname = "SDH_GT_cage_bend_strength"
    bl_label = "Bend Angle"
    DEFORM_TYPE = "BEND"
    PROPERTY_NAME = "bend_strength"
    SHAPE_NAME = "STRETCH"


class SDHCageTwistStrengthGizmo(_SDHCageParameterGizmo):
    bl_idname = "SDH_GT_cage_twist_strength"
    bl_label = "Twist Angle"
    DEFORM_TYPE = "TWIST"
    PROPERTY_NAME = "twist_strength"
    SHAPE_NAME = "TWIST"


class SDHCageTaperFactorGizmo(_SDHCageParameterGizmo):
    bl_idname = "SDH_GT_cage_taper_factor"
    bl_label = "Taper Factor"
    DEFORM_TYPE = "TAPER"
    PROPERTY_NAME = "taper_factor"
    SHAPE_NAME = "TAPER"


class SDHCageStretchFactorGizmo(_SDHCageParameterGizmo):
    bl_idname = "SDH_GT_cage_stretch_factor"
    bl_label = "Stretch Factor"
    DEFORM_TYPE = "STRETCH"
    PROPERTY_NAME = "stretch_factor"
    SHAPE_NAME = "STRETCH"


def _screen_drag_location(context, depth_location, start_mouse, event, precise=False):
    """Unproject one mouse drag onto the view plane at a stable depth."""
    try:
        from bpy_extras import view3d_utils
        scale = 0.1 if precise else 1.0
        screen = Vector((
            start_mouse[0] + (event.mouse_region_x - start_mouse[0]) * scale,
            start_mouse[1] + (event.mouse_region_y - start_mouse[1]) * scale,
        ))
        return view3d_utils.region_2d_to_location_3d(
            context.region, context.space_data.region_3d,
            screen, depth_location)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return Vector(depth_location)


def _screen_plane_location(context, plane_point, plane_normal, mouse):
    """Intersect a viewport mouse ray with a stable world-space plane."""
    try:
        from bpy_extras import view3d_utils
        coordinate = Vector(mouse)
        ray_origin = view3d_utils.region_2d_to_origin_3d(
            context.region, context.space_data.region_3d, coordinate)
        ray_direction = view3d_utils.region_2d_to_vector_3d(
            context.region, context.space_data.region_3d, coordinate)
        normal = Vector(plane_normal)
        denominator = normal.dot(ray_direction)
        if abs(denominator) <= 1.0e-6:
            return None
        distance = normal.dot(Vector(plane_point) - ray_origin) / denominator
        return ray_origin + ray_direction * distance
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


def shear_handle_local_y(properties):
    """Return the endpoint whose displacement exposes the Shear amount."""
    half_y = float(properties.size[1]) * 0.5
    return -half_y if properties.origin == "TOP" else half_y


def shear_profile_distance(properties):
    """Return the authored displacement distance exposed by the handle."""
    length = max(abs(float(properties.size[1])), EPSILON)
    if properties.origin == "TOP":
        return -length
    if properties.origin in {"CENTER", "SYMMETRIC"}:
        return length * 0.5
    return length


def shear_drag_response_vectors(target, controller):
    """Return frozen world-space handle motion for unit X/Z Shear edits."""
    properties = controller.sdh_cage_deform
    distance = shear_profile_distance(properties)
    cage_linear = cage_local_matrix(target, controller).to_3x3()
    output_linear = Matrix.Identity(3)
    try:
        if str(getattr(properties, "mode", "")) == "CHAINED":
            _offset, row_x, row_y, row_z = (
                _core_module.chain_output_frame_for_controller(
                    controller, properties=properties))
            output_linear = Matrix((row_x, row_y, row_z))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        output_linear = Matrix.Identity(3)
    response_x = cage_linear @ (
        output_linear @ Vector((distance, 0.0, 0.0)))
    response_z = cage_linear @ (
        output_linear @ Vector((0.0, 0.0, distance)))
    return response_x, response_z


def shear_factor_delta_from_world(world_delta, response_x, response_z):
    """Solve a two-axis world drag against a possibly skewed response basis."""
    delta = Vector(world_delta)
    response_x = Vector(response_x)
    response_z = Vector(response_z)
    xx = response_x.dot(response_x)
    xz = response_x.dot(response_z)
    zz = response_z.dot(response_z)
    determinant = xx * zz - xz * xz
    if determinant <= EPSILON * EPSILON:
        return Vector((
            delta.dot(response_x) / max(xx, EPSILON),
            0.0,
            delta.dot(response_z) / max(zz, EPSILON),
        ))
    dx = delta.dot(response_x)
    dz = delta.dot(response_z)
    return Vector((
        (dx * zz - dz * xz) / determinant,
        0.0,
        (dz * xx - dx * xz) / determinant,
    ))


def shear_handle_world(target, controller):
    properties = controller.sdh_cage_deform
    handle_y = shear_handle_local_y(properties)
    point = deform_point_for_display(
        (0.0, handle_y, 0.0), properties)
    return cage_local_matrix(target, controller) @ Vector(point)


def shear_handle_frame(target, controller):
    """Return a Shear handle frame parallel to the evaluated free-end face."""
    properties = controller.sdh_cage_deform
    return _deformed_cross_section_frame(
        cage_local_matrix(target, controller), properties,
        shear_handle_local_y(properties))


def shear_gizmo_frame(target, controller, context=None):
    """Lift the interactive grip just outside the evaluated end section."""
    frame, cross_radius = shear_handle_frame(target, controller)
    handle_y = shear_handle_local_y(controller.sdh_cage_deform)
    outward_sign = -1.0 if handle_y >= 0.0 else 1.0
    frame.translation += (
        Vector(frame.to_3x3().col[2]) * outward_sign * cross_radius *
        SHEAR_HANDLE_FACE_OFFSET
    )
    if context is not None:
        frame.translation = _separate_parameter_handle_world(
            context, target, controller, "SHEAR", frame.translation)
    return frame, cross_radius


def _screen_segment_distance(point, start, end):
    point = Vector(point)
    start = Vector(start)
    segment = Vector(end) - start
    length_squared = segment.length_squared
    if length_squared <= EPSILON:
        return (point - start).length
    factor = min(max((point - start).dot(segment) / length_squared, 0.0), 1.0)
    return (point - (start + segment * factor)).length


def shear_drag_axis_from_screen(mouse, center, x_end, z_end):
    """Resolve whether the center grip or one of its two arms was pressed."""
    mouse = Vector(mouse)
    center = Vector(center)
    x_end = Vector(x_end)
    z_end = Vector(z_end)
    center_radius = max(
        min((x_end - center).length, (z_end - center).length) * 0.26,
        6.0,
    )
    if (mouse - center).length <= center_radius:
        return "FREE"
    x_distance = _screen_segment_distance(mouse, center, x_end)
    z_distance = _screen_segment_distance(mouse, center, z_end)
    return "X" if x_distance <= z_distance else "Z"


def shear_drag_axis(context, visual_matrix, mouse):
    """Pick a Shear arm from the Gizmo's final screen-scaled matrix."""
    center = _project_world(context, visual_matrix.translation)
    x_end = _project_world(
        context,
        visual_matrix.translation +
        Vector(visual_matrix.to_3x3().col[0]) * 1.12,
    )
    z_end = _project_world(
        context,
        visual_matrix.translation +
        Vector(visual_matrix.to_3x3().col[1]) * 1.12,
    )
    if center is None or x_end is None or z_end is None:
        return "FREE"
    return shear_drag_axis_from_screen(mouse, center, x_end, z_end)


def constrain_shear_delta(
        local_delta, *, axis="FREE", alt=False, shift=False):
    """Constrain a cage-plane Shear drag by picked arm or modifier key."""
    delta = Vector(local_delta)
    if alt and shift:
        axis = "FREE"
    elif alt:
        axis = "X"
    elif shift:
        axis = "Z"
    if axis == "X":
        delta.z = 0.0
    elif axis == "Z":
        delta.x = 0.0
    return delta


class SDHCageShearGizmo(Gizmo):
    bl_idname = "SDH_GT_cage_shear"
    bl_label = "Shear End-Face Handle"
    bl_target_properties = (
        {"id": "tooltip", "type": "FLOAT", "array_length": 1},
    )
    DEFORM_TYPE = "SHEAR"

    __slots__ = (
        "custom_shape", "initial_values", "original_values",
        "initial_mouse", "initial_world", "initial_plane_hit",
        "drag_plane_normal", "profile_distance", "drag_axis",
        "drag_response_x", "drag_response_z",
        "stage_target", "stage_modifier", "stage_controller",
        "invoke_target", "invoke_modifier", "invoke_controller",
        "_mod_flags", "_tooltip_owner_pointer",
    )

    def setup(self):
        self.custom_shape = self.new_custom_shape(
            "TRIS", _shape_vertices("SHEAR"))
        self.use_tooltip = True
        self.use_draw_modal = True
        self.use_draw_value = False
        self.use_draw_scale = True
        self.scale_basis = COMPACT_PARAMETER_SCALE
        self.initial_values = (0.0, 0.0)
        self.original_values = self.initial_values
        self.initial_mouse = (0.0, 0.0)
        self.initial_world = Vector((0.0, 0.0, 0.0))
        self.initial_plane_hit = Vector((0.0, 0.0, 0.0))
        self.drag_plane_normal = Vector((0.0, 1.0, 0.0))
        self.profile_distance = 1.0
        self.drag_response_x = Vector((1.0, 0.0, 0.0))
        self.drag_response_z = Vector((0.0, 0.0, 1.0))
        self.drag_axis = "FREE"
        self.stage_target = None
        self.stage_modifier = None
        self.stage_controller = None
        self.invoke_target = None
        self.invoke_modifier = None
        self.invoke_controller = None
        self._mod_flags = (False, False, False)
        self._tooltip_owner_pointer = 0

    def _set_tooltip_target(self, properties):
        try:
            owner_pointer = int(properties.as_pointer())
        except (AttributeError, ReferenceError, TypeError, ValueError):
            owner_pointer = id(properties)
        if self._tooltip_owner_pointer == owner_pointer:
            return
        self.target_set_prop(
            "tooltip", properties, "tooltip_shear_plane")
        self._tooltip_owner_pointer = owner_pointer

    def _update_matrix(self, context):
        if _consume_matrix_fresh(self):
            return True
        target, _modifier, controller = _gizmo_stage_context(self, context)
        if target is None or controller is None:
            return False
        properties = controller.sdh_cage_deform
        if "SHEAR" not in _enabled_deform_types(properties):
            return False
        frame, _cross_radius = shear_gizmo_frame(
            target, controller, context=context)
        self.matrix_basis = frame
        self.use_draw_scale = True
        self.scale_basis = COMPACT_PARAMETER_SCALE
        self.color, self.color_highlight = TYPE_HANDLE_COLORS["SHEAR"]
        return True

    def draw(self, context):
        if self._update_matrix(context):
            draw_cage_custom_shape(self, self.custom_shape)

    def draw_select(self, context, select_id):
        if self._update_matrix(context):
            draw_cage_custom_shape(
                self, self.custom_shape, select_id=select_id)

    def invoke(self, context, event):
        target, modifier, controller = _gizmo_stage_context(self, context)
        if target is None or modifier is None or controller is None:
            return {"CANCELLED"}
        properties = controller.sdh_cage_deform
        self.invoke_target = target
        self.invoke_modifier = modifier
        self.invoke_controller = controller
        self.initial_values = tuple(properties.shear_factors)
        self.original_values = self.initial_values
        self.initial_mouse = (event.mouse_region_x, event.mouse_region_y)
        frame, _cross_radius = shear_gizmo_frame(
            target, controller, context=context)
        self.initial_world = frame.translation.copy()
        self.drag_axis = shear_drag_axis(
            context, self.matrix_world, self.initial_mouse)
        self.drag_plane_normal = Vector(frame.to_3x3().col[2])
        plane_hit = _screen_plane_location(
            context, self.initial_world, self.drag_plane_normal,
            self.initial_mouse)
        self.initial_plane_hit = (
            Vector(plane_hit) if plane_hit is not None
            else self.initial_world.copy())
        self.profile_distance = shear_profile_distance(properties)
        self.drag_response_x, self.drag_response_z = (
            shear_drag_response_vectors(target, controller))
        self._mod_flags = (
            bool(getattr(event, "alt", False)),
            bool(getattr(event, "shift", False)),
            bool(getattr(event, "ctrl", False)),
        )
        return {"RUNNING_MODAL"}

    def modal(self, context, event, _tweak):
        target, modifier, controller = _invoked_gizmo_stage(self)
        if target is None or modifier is None or controller is None:
            return {"CANCELLED"}
        tweak = _tweak or ()
        flags = (
            bool(getattr(event, "alt", False)),
            bool(getattr(event, "shift", False)),
            bool(getattr(event, "ctrl", False)) or "SNAP" in tweak,
        )
        if flags != self._mod_flags:
            self.initial_values = tuple(controller.sdh_cage_deform.shear_factors)
            self.initial_mouse = (event.mouse_region_x, event.mouse_region_y)
            frame, _cross_radius = shear_gizmo_frame(
                target, controller, context=context)
            self.initial_world = frame.translation.copy()
            self.drag_plane_normal = Vector(frame.to_3x3().col[2])
            plane_hit = _screen_plane_location(
                context, self.initial_world, self.drag_plane_normal,
                self.initial_mouse)
            self.initial_plane_hit = (
                Vector(plane_hit) if plane_hit is not None
                else self.initial_world.copy())
            self.profile_distance = shear_profile_distance(
                controller.sdh_cage_deform)
            self.drag_response_x, self.drag_response_z = (
                shear_drag_response_vectors(target, controller))
            self._mod_flags = flags
        alt, shift, snap = flags
        dragged = _screen_plane_location(
            context, self.initial_world, self.drag_plane_normal,
            (event.mouse_region_x, event.mouse_region_y))
        if dragged is None:
            dragged = _screen_drag_location(
                context, self.initial_world, self.initial_mouse, event, False)
            world_delta = Vector(dragged) - self.initial_world
        else:
            world_delta = Vector(dragged) - self.initial_plane_hit
        factor_delta = shear_factor_delta_from_world(
            world_delta, self.drag_response_x, self.drag_response_z)
        factor_delta = constrain_shear_delta(
            factor_delta, axis=self.drag_axis, alt=alt, shift=shift)
        value = (
            self.initial_values[0] + factor_delta.x,
            self.initial_values[1] + factor_delta.z,
        )
        if snap:
            value = tuple(round(component * 10.0) / 10.0 for component in value)
        if any(
                abs(float(current) - float(requested)) > EPSILON
                for current, requested in zip(
                    controller.sdh_cage_deform.shear_factors, value)
        ):
            _begin_gizmo_undo(self)
            controller.sdh_cage_deform.shear_factors = value
        if context.area:
            label = bpy.app.translations.pgettext_iface("Shear")
            shortcuts = bpy.app.translations.pgettext_iface(
                "Center Free • Arm X/Z • Alt X • Shift Z • Ctrl Snap")
            context.area.header_text_set(
                f"{label} X: {value[0]:.3f}, Z: {value[1]:.3f}   |   "
                f"{shortcuts}")
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def exit(self, context, cancel):
        controller = getattr(self, "invoke_controller", None)
        if cancel and controller is not None:
            controller.sdh_cage_deform.shear_factors = self.original_values
        _finish_gizmo_undo(self, cancel=cancel, message="Cage Shear")
        if context.area:
            context.area.header_text_set(None)
            context.area.tag_redraw()


def ffd_corner_source_point(properties, corner_index):
    _label, x_sign, y_sign, z_sign = FFD_CORNERS[int(corner_index)]
    half = Vector(properties.size) * 0.5
    return Vector((x_sign * half.x, y_sign * half.y, z_sign * half.z))


def ffd_corner_world(target, controller, corner_index, offsets_override=None):
    properties = controller.sdh_cage_deform
    local = deform_point_for_display(
        ffd_corner_source_point(properties, corner_index),
        properties,
        ffd_offsets_override=offsets_override,
    )
    return cage_local_matrix(target, controller) @ Vector(local)


def is_dedicated_ffd(properties):
    return str(getattr(properties, "cage_type", "STANDARD")) == "FFD"


def ffd_display_corner_indices(properties):
    """Return visible corner handles for traditional or dedicated FFD."""
    if is_dedicated_ffd(properties):
        return ffd_grid_corner_indices(properties)
    return tuple(range(len(FFD_CORNERS)))


def ffd_point_source_local(properties, point_index):
    """Return one native-lattice point in the authored cage frame."""
    if is_dedicated_ffd(properties):
        resolution = ffd_resolution(properties)
        u, v, w = ffd_point_coordinates(point_index, resolution)
        size = Vector(properties.size)
        return Vector((
            -size.x * 0.5 + size.x * u / max(resolution[0] - 1, 1),
            -size.y * 0.5 + size.y * v / max(resolution[1] - 1, 1),
            -size.z * 0.5 + size.z * w / max(resolution[2] - 1, 1),
        ))
    return ffd_corner_source_point(properties, point_index)


def ffd_point_world(target, controller, point_index):
    properties = controller.sdh_cage_deform
    if is_dedicated_ffd(properties):
        return cage_local_matrix(target, controller) @ (
            ffd_point_source_local(properties, point_index) +
            ffd_point_offset(properties, point_index))
    return ffd_corner_world(target, controller, point_index)


def ffd_wire_geometry(properties, *, effective=False):
    """Return the authored cage or its weighted runtime result."""
    resolution = ffd_resolution(properties)
    surface_only = bool(getattr(properties, "ffd_use_outside", False))
    offset_for = (
        ffd_point_effective_offset if effective else ffd_point_offset)
    vertices = tuple(
        ffd_point_source_local(properties, index) +
        offset_for(properties, index)
        for index in range(math.prod(resolution))
    )
    edges = []
    for w in range(resolution[2]):
        for v in range(resolution[1]):
            for u in range(resolution[0]):
                index = ffd_point_index(u, v, w, resolution)
                if u + 1 < resolution[0]:
                    neighbor = ffd_point_index(u + 1, v, w, resolution)
                    if (
                            not surface_only or
                            ffd_point_is_surface(index, resolution) and
                            ffd_point_is_surface(neighbor, resolution)
                    ):
                        edges.append((index, neighbor))
                if v + 1 < resolution[1]:
                    neighbor = ffd_point_index(u, v + 1, w, resolution)
                    if (
                            not surface_only or
                            ffd_point_is_surface(index, resolution) and
                            ffd_point_is_surface(neighbor, resolution)
                    ):
                        edges.append((index, neighbor))
                if w + 1 < resolution[2]:
                    neighbor = ffd_point_index(u, v, w + 1, resolution)
                    if (
                            not surface_only or
                            ffd_point_is_surface(index, resolution) and
                            ffd_point_is_surface(neighbor, resolution)
                    ):
                        edges.append((index, neighbor))
    return vertices, tuple(edges)


class SDHCageFFDCornerGizmo(Gizmo):
    bl_idname = "SDH_GT_cage_ffd_corner"
    bl_label = "FFD Corner"
    bl_target_properties = (
        {"id": "tooltip", "type": "FLOAT", "array_length": 1},
    )

    __slots__ = (
        "custom_shape", "line_shape", "face_shape", "selection_mode",
        "selection_axis",
        "ffd_line_length_ratio", "ffd_line_width", "ffd_face_size_ratio",
        "corner_index", "initial_offsets", "original_offsets",
        "initial_point_offsets", "original_point_offsets",
        "initial_mouse", "initial_world", "jacobian_inverse",
        "stage_target", "stage_modifier", "stage_controller",
        "invoke_target", "invoke_modifier", "invoke_controller",
        "_tooltip_index", "_tooltip_owner_pointer", "_tooltip_mode",
    )

    def setup(self):
        self.custom_shape = self.new_custom_shape("TRIS", (
            (0.0, 0.92, 0.0), (0.92, 0.0, 0.0), (0.0, -0.92, 0.0),
            (0.0, 0.92, 0.0), (0.0, -0.92, 0.0), (-0.92, 0.0, 0.0),
        ))
        self.line_shape = self.new_custom_shape("LINES", (
            (0.0, -1.0, 0.0), (0.0, 1.0, 0.0),
        ))
        self.face_shape = self.new_custom_shape("TRIS", (
            (-0.85, 0.0, -0.85), (0.85, 0.0, -0.85), (0.85, 0.0, 0.85),
            (-0.85, 0.0, -0.85), (0.85, 0.0, 0.85), (-0.85, 0.0, 0.85),
        ))
        self.use_tooltip = True
        # Blender 5.2 sends an internal Tweak event to every FFD handle while
        # one point is dragged. The modal-draw pass tries to convert that
        # internal numeric event type and emits repeated RNA warnings. FFD
        # handles remain drawn in the regular viewport pass and keep their
        # custom modal transform logic; disabling only this optional pass
        # avoids the warning without changing selection or movement.
        self.use_draw_modal = False
        self.use_draw_value = False
        self.scale_basis = 0.13
        self.ffd_line_length_ratio = 0.60
        self.ffd_line_width = 2.0
        self.ffd_face_size_ratio = 0.35
        self.selection_mode = "POINT"
        self.selection_axis = "POINT"
        self.corner_index = 0
        self.initial_offsets = (0.0,) * FFD_COMPONENT_COUNT
        self.original_offsets = self.initial_offsets
        self.initial_point_offsets = {}
        self.original_point_offsets = {}
        self.initial_mouse = (0.0, 0.0)
        self.initial_world = Vector((0.0, 0.0, 0.0))
        self.jacobian_inverse = Matrix.Identity(3)
        self.stage_target = None
        self.stage_modifier = None
        self.stage_controller = None
        self.invoke_target = None
        self.invoke_modifier = None
        self.invoke_controller = None
        self._tooltip_index = -1
        self._tooltip_owner_pointer = 0
        self._tooltip_mode = "POINT"

    def _set_tooltip_target(self, properties):
        maximum = (
            ffd_point_count(properties) - 1
            if is_dedicated_ffd(properties) else 7)
        index = min(max(int(getattr(self, "corner_index", 0)), 0), maximum)
        try:
            owner_pointer = int(properties.as_pointer())
        except (AttributeError, ReferenceError, TypeError, ValueError):
            owner_pointer = id(properties)
        if (
                self._tooltip_index == index and
                self._tooltip_owner_pointer == owner_pointer and
                self._tooltip_mode == str(getattr(self, "selection_mode", "POINT"))
        ):
            return
        mode = str(getattr(self, "selection_mode", "POINT"))
        tooltip = (
            {"LINE": "tooltip_ffd_line", "FACE": "tooltip_ffd_face"}.get(
                mode, "tooltip_ffd_point")
            if is_dedicated_ffd(properties) else f"tooltip_ffd_corner_{index}")
        self.target_set_prop("tooltip", properties, tooltip)
        self._tooltip_index = index
        self._tooltip_owner_pointer = owner_pointer
        self._tooltip_mode = str(getattr(self, "selection_mode", "POINT"))

    def _update_matrix(self, context):
        if _consume_matrix_fresh(self):
            return True
        target, _modifier, controller = _gizmo_stage_context(self, context)
        if target is None or controller is None:
            return False
        properties = controller.sdh_cage_deform
        if (
                "FFD" not in _enabled_deform_types(properties) or
                not ffd_handles_enabled()
        ):
            return False
        dedicated = is_dedicated_ffd(properties)
        mode = str(getattr(self, "selection_mode", "POINT")) if dedicated else "POINT"
        self.use_draw_scale = mode == "POINT"
        self.line_width = self.ffd_line_width if mode == "LINE" else 1.0
        point_count = ffd_point_count(properties) if dedicated else len(FFD_CORNERS)
        index = int(getattr(self, "corner_index", 0))
        if index >= point_count:
            return False
        if (
                dedicated and bool(getattr(properties, "ffd_use_outside", False)) and
                not ffd_point_is_surface(index, ffd_resolution(properties))
        ):
            return False
        if dedicated:
            orientation = getattr(self, "selection_axis", None)
            entity = (index, mode, str(orientation))
            group_cache = getattr(self, "aggregate_groups", None)
            group = (
                group_cache.get(entity, ())
                if group_cache is not None else
                tuple(ffd_selection_indices(
                    properties, index, mode,
                    axis=None if orientation == "POINT" else orientation,
                    ensure=False))
            )
            if not group:
                return False
            world_cache = getattr(self, "aggregate_world_points", None)
            world_points = tuple(
                world_cache[point_index]
                if world_cache is not None and point_index < len(world_cache)
                else ffd_point_world(target, controller, point_index)
                for point_index in group)
            center = sum(world_points, Vector((0.0, 0.0, 0.0))) / len(world_points)
        else:
            group = (index,)
            center = ffd_corner_world(target, controller, index)
        if dedicated and mode == "LINE" and len(world_points) > 1:
            # A bent or tapered line is not straight.  Using the arithmetic
            # point average can place the handle outside the visible wire and
            # using the end-to-end chord can point it away from the local
            # segment.  Put the controller at the arc midpoint and align it
            # to the tangent at that exact position.
            center, line_axis, line_length = _polyline_midpoint_tangent(world_points)
            basis = _axis_facing_matrix(context, center, line_axis)
            # The visual uses a one-dimensional line. Its Y scale carries the
            # user-selected length percentage; its pixel width is independent
            # of the FFD line length so every controller stays equally thin.
            line_scale = max(
                line_length * self.ffd_line_length_ratio / 2.0, EPSILON)
            basis.col[1][0:3] = Vector(basis.col[1][0:3]) * line_scale
            self.matrix_basis = basis
            self.use_draw_scale = False
        elif dedicated and mode == "FACE" and len(world_points) > 3:
            coordinates = {
                point_index: ffd_point_coordinates(
                    point_index, ffd_resolution(properties))
                for point_index in group
            }
            plane = str(getattr(self, "selection_axis", "UW"))
            dimensions = {"U": 0, "V": 1, "W": 2}
            first_dim, second_dim = (
                dimensions.get(plane[0], 0), dimensions.get(plane[1], 2))
            first_min = min(value[first_dim] for value in coordinates.values())
            first_max = max(value[first_dim] for value in coordinates.values())
            second_min = min(value[second_dim] for value in coordinates.values())
            second_max = max(value[second_dim] for value in coordinates.values())
            first_low = sum(
                (Vector(world_points[offset]) for offset, point_index in
                 enumerate(group)
                 if coordinates[point_index][first_dim] == first_min),
                Vector((0.0, 0.0, 0.0)),
            )
            first_high = sum(
                (Vector(world_points[offset]) for offset, point_index in
                 enumerate(group)
                 if coordinates[point_index][first_dim] == first_max),
                Vector((0.0, 0.0, 0.0)),
            )
            second_low = sum(
                (Vector(world_points[offset]) for offset, point_index in
                 enumerate(group)
                 if coordinates[point_index][second_dim] == second_min),
                Vector((0.0, 0.0, 0.0)),
            )
            second_high = sum(
                (Vector(world_points[offset]) for offset, point_index in
                 enumerate(group)
                 if coordinates[point_index][second_dim] == second_max),
                Vector((0.0, 0.0, 0.0)),
            )
            first_axis = first_high / max(sum(
                coordinates[point_index][first_dim] == first_max
                for point_index in group), 1)
            first_axis -= first_low / max(sum(
                coordinates[point_index][first_dim] == first_min
                for point_index in group), 1)
            second_axis = second_high / max(sum(
                coordinates[point_index][second_dim] == second_max
                for point_index in group), 1)
            second_axis -= second_low / max(sum(
                coordinates[point_index][second_dim] == second_min
                for point_index in group), 1)
            first_span = first_axis.length
            second_span = second_axis.length
            if first_span > EPSILON and second_span > EPSILON:
                first_axis.normalize()
                second_axis = (
                    second_axis - first_axis * second_axis.dot(first_axis)
                ).normalized()
                normal = first_axis.cross(second_axis)
                if normal.length > EPSILON:
                    normal.normalize()
                    second_axis = normal.cross(first_axis).normalized()
                    basis = Matrix.Identity(4)
                    basis.col[0][0:3] = first_axis
                    basis.col[1][0:3] = normal
                    basis.col[2][0:3] = second_axis
                    # The face icon spans 1.7 units on each local plane axis.
                    # Match both dimensions to the user-selected proportion of
                    # the evaluated grid face.
                    basis.col[0][0:3] = (
                        Vector(basis.col[0][0:3]) * first_span *
                        self.ffd_face_size_ratio / 1.70)
                    basis.col[2][0:3] = (
                        Vector(basis.col[2][0:3]) * second_span *
                        self.ffd_face_size_ratio / 1.70)
                    self.matrix_basis = Matrix.Translation(center) @ basis
                    self.use_draw_scale = False
                else:
                    self.matrix_basis = _billboard_matrix(context, center)
            else:
                self.matrix_basis = _billboard_matrix(context, center)
        else:
            self.matrix_basis = _billboard_matrix(context, center)
        if mode == "POINT":
            self.use_draw_scale = True
        self.scale_basis = 0.13 if mode == "POINT" else 1.0
        if dedicated:
            _u, v, _w = ffd_point_coordinates(index, ffd_resolution(properties))
            top = v >= ffd_resolution(properties)[1] - 1
            selected = all(
                point_index < len(getattr(properties, "ffd_points", ())) and
                bool(properties.ffd_points[point_index].selected)
                for point_index in group
            )
        else:
            top = index >= 4
            selected = True
        if selected:
            self.color = (1.0, 0.26, 0.52) if top else (0.18, 0.78, 1.0)
            self.color_highlight = (1.0, 0.78, 0.88) if top else (0.72, 1.0, 1.0)
        else:
            self.color = (0.32, 0.36, 0.42)
            self.color_highlight = (0.8, 0.86, 0.94)
        return True

    def draw(self, context):
        if self._update_matrix(context):
            shape = {
                "LINE": self.line_shape,
                "FACE": self.face_shape,
            }.get(getattr(self, "selection_mode", "POINT"), self.custom_shape)
            draw_cage_custom_shape(self, shape)

    def draw_select(self, context, select_id):
        # ``hide_select`` is applied during draw preparation.  Blender can
        # still reuse a selection buffer from the frame that opened FFD edit
        # mode, so keep the persistent FFD modal as the sole point/line/face
        # picker even for that first viewport click.
        _target, _modifier, controller = _gizmo_stage_context(self, context)
        properties = getattr(controller, "sdh_cage_deform", None)
        if (
                properties is not None and
                is_dedicated_ffd(properties) and
                bool(getattr(properties, "ffd_edit_mode_active", False))
        ):
            return
        if self._update_matrix(context):
            shape = {
                "LINE": self.line_shape,
                "FACE": self.face_shape,
            }.get(getattr(self, "selection_mode", "POINT"), self.custom_shape)
            if getattr(self, "selection_mode", "POINT") == "LINE":
                visible_width = self.line_width
                try:
                    # Keep the visible controller thin while retaining a
                    # practical click target for the selection pass.
                    self.line_width = max(visible_width, 8.0)
                    draw_cage_custom_shape(
                        self, shape, select_id=select_id)
                finally:
                    self.line_width = visible_width
            else:
                draw_cage_custom_shape(
                    self, shape, select_id=select_id)

    def invoke(self, context, event):
        target, modifier, controller = _gizmo_stage_context(self, context)
        if target is None or modifier is None or controller is None:
            return {"CANCELLED"}
        properties = controller.sdh_cage_deform
        dedicated = is_dedicated_ffd(properties)
        mode = str(getattr(self, "selection_mode", "POINT")) if dedicated else "POINT"
        if dedicated:
            ensure_ffd_point_collection(properties)
        point_count = ffd_point_count(properties) if dedicated else len(FFD_CORNERS)
        index = min(max(int(getattr(self, "corner_index", 0)), 0), point_count - 1)
        try:
            properties.ffd_active_point = index
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            pass
        self.invoke_target = target
        self.invoke_modifier = modifier
        self.invoke_controller = controller
        if dedicated:
            orientation = str(getattr(self, "selection_axis", "POINT") or "POINT")
            if not bool(getattr(properties, "ffd_edit_mode_active", False)):
                # The editor operator polls the target's active cage before its
                # invoke callback can resolve ``controller_name``.  Switch the
                # stage at the Gizmo entry point so a point on an inactive FFD
                # can start editing while Standard or Shear is currently active.
                try:
                    target.modifiers.active = modifier
                    _core_module._activate_ffd_edit_selection(
                        context, target, controller)
                except (AttributeError, ReferenceError, RuntimeError, TypeError,
                        ValueError):
                    return {"CANCELLED"}
                try:
                    result = bpy.ops.sdh.box_select_ffd_points(
                        "INVOKE_DEFAULT",
                        controller_name=controller.name,
                        toggle=False,
                        start_drag=True,
                        start_anchor=index,
                        start_selection_mode=mode,
                        start_selection_axis=orientation,
                        start_mouse_region_x=int(event.mouse_region_x),
                        start_mouse_region_y=int(event.mouse_region_y),
                        start_extend=bool(getattr(event, "shift", False)),
                    )
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    result = {"CANCELLED"}
                if "RUNNING_MODAL" in result:
                    try:
                        _core_module._selection_sync_notify()
                    except (AttributeError, RuntimeError, TypeError, ValueError):
                        pass
                    return {"FINISHED"}
            # Gizmo picking can run after Blender has made the controller the
            # sole selected object. Restore the edit-session selection before
            # consuming the point hit so the target remains selected and the
            # display pass does not hide the FFD handles on the next redraw.
            try:
                _core_module._activate_ffd_edit_selection(
                    context, target, controller)
            except (AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError):
                pass
        if dedicated:
            group = set(ffd_selection_indices(
                properties, index, mode,
                axis=None if orientation == "POINT" else orientation))
            group = _core_module.ffd_symmetry_expand_indices(
                properties, group)
            current = {
                point_index for point_index, point in enumerate(
                    properties.ffd_points) if point.selected
            }
            selected, _collapse_on_click = (
                _core_module.ffd_pointer_selection_update(
                    current,
                    group,
                    extend=bool(getattr(event, "shift", False)),
                ))
            active = (
                index if index in selected else
                min(selected) if selected else None)
            ffd_set_selection(properties, selected, active=active)
            # Blender applies the final Gizmo pick selection after invoke()
            # returns. Defer one synchronization pass so that transient
            # controller-only selection cannot hide the target-bound FFD cage
            # before the persistent editor receives another event.
            try:
                _core_module._selection_sync_notify()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            # Dedicated FFD points are edited by the persistent FFD edit
            # modal. The selection pass has already updated the point set.
            # Finish this per-gizmo invocation after consuming the hit.
            # Returning CANCELLED would let Blender reuse the mouse event for
            # normal object selection; on release that can clear the
            # target/controller pair and close FFD edit mode.
            return {"FINISHED"}
        self.initial_offsets = tuple(properties.ffd_offsets)
        self.original_offsets = self.initial_offsets
        self.initial_point_offsets = {
            point_index: tuple(properties.ffd_points[point_index].offset)
            for point_index in ffd_selected_indices(properties)
            if point_index < len(properties.ffd_points)
        }
        self.original_point_offsets = dict(self.initial_point_offsets)
        self.initial_mouse = (event.mouse_region_x, event.mouse_region_y)
        if dedicated:
            selected_world = tuple(
                ffd_point_world(target, controller, point_index)
                for point_index in ffd_selection_indices(
                        properties, index, mode,
                        axis=None if orientation == "POINT" else orientation)
            )
            self.initial_world = (
                sum(selected_world, Vector((0.0, 0.0, 0.0))) /
                len(selected_world)
                if selected_world else
                Vector(ffd_point_world(target, controller, index))
            )
        else:
            self.initial_world = Vector(ffd_point_world(target, controller, index))
        epsilon = max(min(abs(float(value)) for value in properties.size) * 1e-4, 1e-5)
        jacobian = Matrix.Identity(3)
        if dedicated:
            frame = cage_local_matrix(target, controller).to_3x3()
            jacobian = frame
        else:
            component_start = index * 3
            for axis in range(3):
                perturbed = list(self.initial_offsets)
                perturbed[component_start + axis] += epsilon
                moved = Vector(ffd_corner_world(
                    target, controller, index, perturbed))
                jacobian.col[axis] = (moved - self.initial_world) / epsilon
        self.jacobian_inverse = jacobian.inverted_safe()
        return {"RUNNING_MODAL"}

    def modal(self, context, event, _tweak):
        target, modifier, controller = _invoked_gizmo_stage(self)
        if target is None or modifier is None or controller is None:
            return {"CANCELLED"}
        precise = bool(event.shift) or "PRECISE" in (_tweak or ())
        snap = bool(event.ctrl) or "SNAP" in (_tweak or ())
        properties = controller.sdh_cage_deform
        dedicated = is_dedicated_ffd(properties)
        mode = str(getattr(self, "selection_mode", "POINT")) if dedicated else "POINT"
        point_count = ffd_point_count(properties) if dedicated else len(FFD_CORNERS)
        index = min(max(int(getattr(self, "corner_index", 0)), 0), point_count - 1)
        if bool(getattr(event, "alt", False)):
            scale = 0.1 if precise else 1.0
            local_delta = Vector((
                0.0,
                (event.mouse_region_y - self.initial_mouse[1]) *
                max(abs(float(controller.sdh_cage_deform.size[1])), EPSILON) *
                0.005 * scale,
                0.0,
            ))
        else:
            dragged = _screen_drag_location(
                context, self.initial_world, self.initial_mouse, event, precise)
            local_delta = self.jacobian_inverse @ (
                Vector(dragged) - self.initial_world)
        if dedicated:
            edited_indices = tuple(ffd_selected_indices(properties))
            pointer = int(controller.as_pointer())
            _core_module._FFD_POINT_GUARD.add(pointer)
            try:
                for point_index in edited_indices:
                    if point_index >= len(properties.ffd_points):
                        continue
                    start = self.initial_point_offsets.get(
                        point_index, tuple(properties.ffd_points[point_index].offset))
                    value = [start[axis] + local_delta[axis] for axis in range(3)]
                    if snap:
                        value = [round(component * 10.0) / 10.0 for component in value]
                    properties.ffd_points[point_index].offset = tuple(value)
            finally:
                _core_module._FFD_POINT_GUARD.discard(pointer)
            _core_module._controller_update(properties, context)
            edited = tuple(properties.ffd_points[index].offset)
            label_name = {
                "LINE": "FFD Line",
                "FACE": "FFD Face",
            }.get(mode, "FFD Point")
            label = (
                bpy.app.translations.pgettext_iface(label_name) +
                f" {index:03d}"
            )
        else:
            values = list(self.initial_offsets)
            component_start = index * 3
            for axis in range(3):
                value = values[component_start + axis] + local_delta[axis]
                values[component_start + axis] = (
                    round(value * 10.0) / 10.0 if snap else value)
            if any(
                    abs(float(current) - float(requested)) > EPSILON
                    for current, requested in zip(
                        properties.ffd_offsets, values)
            ):
                _begin_gizmo_undo(self)
                properties.ffd_offsets = tuple(values)
            edited = values[component_start:component_start + 3]
            label = f"FFD {FFD_CORNERS[index][0]}"
        if context.area:
            if not dedicated:
                label = bpy.app.translations.pgettext_iface(label)
            shortcuts = bpy.app.translations.pgettext_iface(
                "Drag in View • Alt Cage Axis • Shift Precise • Ctrl Snap")
            context.area.header_text_set(
                f"{label}: {edited[0]:.3f}, {edited[1]:.3f}, "
                f"{edited[2]:.3f}   |   {shortcuts}")
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def exit(self, context, cancel):
        controller = getattr(self, "invoke_controller", None)
        # Dedicated FFD clicks are selection-only; their transforms belong to
        # the persistent edit modal. Keep any defensive ``exit`` callback from
        # restoring the legacy eight-corner buffer on a native FFD stage.
        properties = (
            getattr(controller, "sdh_cage_deform", None)
            if controller is not None else None)
        if cancel and controller is not None and not is_dedicated_ffd(properties):
            properties.ffd_offsets = self.original_offsets
            pointer = int(controller.as_pointer())
            _core_module._FFD_POINT_GUARD.add(pointer)
            try:
                for point_index, value in self.original_point_offsets.items():
                    if point_index < len(getattr(properties, "ffd_points", ())):
                        properties.ffd_points[point_index].offset = value
            finally:
                _core_module._FFD_POINT_GUARD.discard(pointer)
            _core_module._controller_update(properties, context)
        _finish_gizmo_undo(self, cancel=cancel, message="Cage FFD")
        if context.area:
            if bool(getattr(properties, "ffd_edit_mode_active", False)):
                context.area.header_text_set(
                    bpy.app.translations.pgettext_iface(
                        "FFD Edit Mode: drag blank area to box select | "
                        "G Move; G again Tangent Slide | R Rotate | S Scale | "
                        "Shift Add | "
                        "Ctrl Subtract | A Select All | Alt+A Clear | "
                        "Double-click blank / Esc / Right Mouse exits"))
            else:
                context.area.header_text_set(None)
            context.area.tag_redraw()


class SDHCageFFDAggregateGizmo(Gizmo):
    """Draw and pick every active FFD entity through one Blender Gizmo."""
    bl_idname = "SDH_GT_cage_ffd_aggregate"
    bl_label = "FFD Controls"
    bl_target_properties = SDHCageFFDCornerGizmo.bl_target_properties

    __slots__ = (
        *SDHCageFFDCornerGizmo.__slots__,
        "ffd_entities", "picked_entity",
        "aggregate_stage_context", "aggregate_world_points",
        "aggregate_groups", "last_batch_counts",
    )

    _set_tooltip_target = SDHCageFFDCornerGizmo._set_tooltip_target
    _update_matrix = SDHCageFFDCornerGizmo._update_matrix
    modal = SDHCageFFDCornerGizmo.modal
    exit = SDHCageFFDCornerGizmo.exit

    def setup(self):
        SDHCageFFDCornerGizmo.setup(self)
        self.ffd_entities = ()
        self.picked_entity = None
        self.aggregate_stage_context = None
        self.aggregate_world_points = None
        self.aggregate_groups = None
        self.last_batch_counts = {"LINE": 0, "FACE": 0}

    def _set_entity(self, entity):
        anchor, mode, orientation = entity
        self.corner_index = int(anchor)
        self.selection_mode = str(mode)
        self.selection_axis = str(orientation)

    @staticmethod
    def _entity_color(properties, entity, group, highlighted):
        """Return the selected/hover palette for one batched entity."""
        anchor, _mode, _orientation = entity
        selected = bool(group) and all(
            index < len(getattr(properties, "ffd_points", ())) and
            bool(properties.ffd_points[index].selected)
            for index in group
        )
        _u, v, _w = ffd_point_coordinates(
            int(anchor), ffd_resolution(properties))
        top = v >= ffd_resolution(properties)[1] - 1
        if selected:
            normal = (1.0, 0.26, 0.52) if top else (0.18, 0.78, 1.0)
            hover = (1.0, 0.78, 0.88) if top else (0.72, 1.0, 1.0)
        else:
            normal = (0.32, 0.36, 0.42)
            hover = (0.8, 0.86, 0.94)
        return (*tuple(hover if highlighted else normal), 1.0)

    def draw(self, context):
        entities = tuple(getattr(self, "ffd_entities", ()))
        if not entities:
            return
        picked = getattr(self, "picked_entity", None)
        if picked not in entities:
            picked = None
            self.picked_entity = None
        restore_entity = picked or entities[0]
        target, modifier, controller = _gizmo_stage_context(self, context)
        if target is None or modifier is None or controller is None:
            return
        properties = controller.sdh_cage_deform
        hover = _core_module.ffd_hover_entity(controller)
        if hover not in entities:
            hover = picked if self.is_highlight and picked in entities else None
        picked = hover
        self.aggregate_stage_context = (target, modifier, controller)
        self.aggregate_world_points = tuple(
            ffd_point_world(target, controller, index)
            for index in range(ffd_point_count(properties))
        )
        self.aggregate_groups = {
            tuple(entity): tuple(ffd_selection_indices(
                properties,
                int(entity[0]),
                str(entity[1]),
                axis=(
                    None if str(entity[2]) == "POINT" else str(entity[2])),
                ensure=False,
            ))
            for entity in entities
        }
        batch_ok = False
        try:
            self.last_batch_counts = draw_ffd_line_face_batches(
                self,
                entities,
                picked,
                self.aggregate_world_points,
                self.aggregate_groups,
                lambda anchor, orientation, group:
                    _core_module._ffd_face_winding_indices(
                        properties, anchor, orientation, group),
                color_for=lambda entity, group, highlighted: self._entity_color(
                    properties, entity, group,
                    bool(highlighted or entity == hover)),
            )
            batch_ok = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            self.last_batch_counts = {"LINE": 0, "FACE": 0}
        # One aggregate owns many matrices, so a matrix marked fresh for one
        # entity must never be consumed after switching to another entity.
        _invalidate_matrix_fresh(self)
        try:
            for entity in entities:
                self._set_entity(entity)
                if batch_ok and self.selection_mode in {"LINE", "FACE"}:
                    continue
                if not self._update_matrix(context):
                    continue
                shape = {
                    "LINE": self.line_shape,
                    "FACE": self.face_shape,
                }.get(self.selection_mode, self.custom_shape)
                highlight = tuple(self.color_highlight)
                if self.is_highlight and entity != picked:
                    self.color_highlight = tuple(self.color)
                try:
                    draw_cage_custom_shape(self, shape)
                finally:
                    self.color_highlight = highlight
        finally:
            self._set_entity(restore_entity)
            self.aggregate_stage_context = None
            self.aggregate_world_points = None
            self.aggregate_groups = None

    def invoke(self, context, event):
        picked = getattr(self, "picked_entity", None)
        if picked is None:
            return {"CANCELLED"}
        self._set_entity(picked)
        return SDHCageFFDCornerGizmo.invoke(self, context, event)

    def test_select(self, context, location):
        # Keep ``draw_select`` undefined on this aggregate. Blender's 3D Gizmo
        # router only calls ``test_select`` when no GPU selection callback is
        # registered; even an empty draw_select method disables this fast
        # screen-space picker and lets the click fall through to Object Select.
        target, modifier, controller = _gizmo_stage_context(self, context)
        if target is None or modifier is None or controller is None:
            self.picked_entity = None
            return -1
        properties = controller.sdh_cage_deform
        if bool(getattr(properties, "ffd_edit_mode_active", False)):
            self.picked_entity = None
            return -1
        try:
            from bpy_extras import view3d_utils
            region = context.region
            region_data = context.space_data.region_3d
        except (AttributeError, ImportError):
            self.picked_entity = None
            return -1
        projected_points = {}

        def projected(index):
            if index not in projected_points:
                world = Vector(ffd_point_world(target, controller, index))
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
        try:
            ui_scale = float(context.preferences.system.ui_scale)
        except (AttributeError, TypeError, ValueError):
            ui_scale = 1.0
        picked = ffd_screen_selection_entity(
            properties,
            projected,
            location,
            line_ratio=float(getattr(
                preferences, "ffd_line_handle_length", 0.60)),
            face_ratio=float(getattr(
                preferences, "ffd_face_handle_size", 0.35)),
            point_radius=max(10.0 * ui_scale, 8.0),
            line_radius=max(8.0 * ui_scale, 6.0),
            face_margin=max(4.0 * ui_scale, 3.0),
        )
        if picked is None:
            self.picked_entity = None
            return -1
        self.picked_entity = tuple(picked)
        self._set_entity(self.picked_entity)
        self._set_tooltip_target(properties)
        return 0


# Kept as a Python import alias for older tests/scripts. The registered Gizmos
# include the operation-specific subclasses above.
SDHCageStrengthGizmo = SDHCageBendStrengthGizmo


def bend_direction_handle_world(target, controller, context=None):
    properties = controller.sdh_cage_deform
    cage_matrix = cage_local_matrix(target, controller)
    if "BEND" not in _enabled_deform_types(properties):
        return cage_matrix.translation
    frame, _radius = _deformed_section_frame(
        cage_matrix, properties, 0.0, properties.bend_direction)
    return frame.translation


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
        "original_direction",
        "stage_target",
        "stage_modifier",
        "stage_controller",
        "invoke_target",
        "invoke_modifier",
        "invoke_controller",
        "_mod_flags",
    )

    def setup(self):
        # Direction ring contained by the evaluated cage section.
        self.custom_shape = self.new_custom_shape(
            "TRIS", _arc_arrow_triangles(-math.pi * 0.95, math.pi * 0.95, 40))
        self.use_tooltip = True
        self.use_draw_modal = True
        self.use_draw_value = False
        # Avoid Blender's default 1.0-scale flash before the first update.
        self.scale_basis = 0.32
        self.original_direction = 0.0
        self.stage_target = None
        self.stage_modifier = None
        self.stage_controller = None
        self.invoke_target = None
        self.invoke_modifier = None
        self.invoke_controller = None

    def _update_matrix(self, context):
        if _consume_matrix_fresh(self):
            return True
        target, _modifier, controller = _gizmo_stage_context(self, context)
        if target is None or controller is None:
            return False
        properties = controller.sdh_cage_deform
        if ("BEND" not in _enabled_deform_types(properties) or
                not properties.show_direction_handle):
            return False
        frame, cross_radius = _deformed_section_frame(
            cage_local_matrix(target, controller), properties,
            0.0, properties.bend_direction)
        self.matrix_basis = frame
        self.scale_basis = bend_direction_ring_scale(cross_radius)
        self.color, self.color_highlight = TYPE_HANDLE_COLORS["BEND"]
        return True

    def draw(self, context):
        if self._update_matrix(context):
            draw_cage_custom_shape(self, self.custom_shape)

    def draw_select(self, context, select_id):
        if self._update_matrix(context):
            draw_cage_custom_shape(
                self, self.custom_shape, select_id=select_id)

    def invoke(self, context, event):
        target, modifier, controller = _gizmo_stage_context(self, context)
        if target is None or modifier is None or controller is None:
            return {"CANCELLED"}
        self.invoke_target = target
        self.invoke_modifier = modifier
        self.invoke_controller = controller
        self.initial_direction = controller.sdh_cage_deform.bend_direction
        self.original_direction = self.initial_direction
        self.initial_mouse_x = event.mouse_region_x
        self.center = _project_world(
            context, bend_direction_handle_world(target, controller, context))
        self.last_angle = _mouse_angle(self.center, event)
        self.angle_delta = 0.0
        self._mod_flags = _event_mod_flags(event)
        return {"RUNNING_MODAL"}

    def modal(self, context, event, _tweak):
        _target, _modifier, controller = _invoked_gizmo_stage(self)
        if _target is None or _modifier is None or controller is None:
            return {"CANCELLED"}
        properties = controller.sdh_cage_deform
        flags = _event_mod_flags(event, _tweak)
        if flags != self._mod_flags:
            self.initial_direction = properties.bend_direction
            self.initial_mouse_x = event.mouse_region_x
            self.angle_delta = 0.0
            self.last_angle = _mouse_angle(self.center, event)
            self._mod_flags = flags
        precise, snap, _alt = flags

        current_angle = _mouse_angle(self.center, event)
        if current_angle is not None and self.last_angle is not None:
            # Match the right-handed X/Z bend direction from either side of
            # the cage. Front/back views mirror screen rotation, so include
            # the same view sign used by the twist ring.
            cage_matrix = cage_local_matrix(_target, controller)
            frame, _radius = _deformed_section_frame(
                cage_matrix, properties, 0.0, properties.bend_direction)
            axis = frame.to_3x3() @ Vector((0.0, 0.0, 1.0))
            view_sign = _twist_view_sign(
                context,
                bend_direction_handle_world(_target, controller, context),
                axis,
            )
            self.angle_delta += view_sign * -_wrapped_angle_delta(
                self.last_angle, current_angle)
            self.last_angle = current_angle
            delta = self.angle_delta
        else:
            # Linear fallback: invert once vs original (current-init; +).
            delta = (event.mouse_region_x - self.initial_mouse_x) * 0.01
            delta = -delta
        if precise:
            delta *= 0.1
        if snap:
            step = math.radians(5.0)
            delta = round(delta / step) * step
        requested_direction = self.initial_direction + delta
        if abs(
                float(properties.bend_direction) -
                float(requested_direction)
        ) > EPSILON:
            _begin_gizmo_undo(self)
            properties.bend_direction = requested_direction
        if context.area:
            label = bpy.app.translations.pgettext_iface("Bend Direction")
            shortcuts = bpy.app.translations.pgettext_iface(
                "Drag Around Ring • Shift Precise • Ctrl Snap")
            context.area.header_text_set(
                f"{label}: {math.degrees(properties.bend_direction):.1f}°   |   "
                f"{shortcuts}")
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def exit(self, context, cancel):
        controller = getattr(self, "invoke_controller", None)
        if cancel and controller:
            controller.sdh_cage_deform.bend_direction = self.original_direction
        _finish_gizmo_undo(
            self, cancel=cancel, message="Cage Bend Direction")
        if context.area:
            context.area.header_text_set(None)
            context.area.tag_redraw()


BEND_TREND_COLORS = {
    0: ((0.95, 0.12, 0.1), (1.0, 0.72, 0.65)),
    1: ((0.12, 0.88, 0.22), (0.68, 1.0, 0.7)),
}

# Match classic bend-axis switch: six faces of the original bound box, each
# with two perpendicular trend arrows (red / green). Rotations come from the
# old BendAxiSwitchGizmoGroup.draw_prepare layout.
_BEND_TREND_FACE_ROTATIONS = {
    ("POS_Z", 0): (0.0, 0.0, 0.0),
    ("POS_Z", 1): (0.0, 0.0, math.radians(90)),
    ("NEG_Z", 0): (0.0, math.radians(180), 0.0),
    ("NEG_Z", 1): (0.0, math.radians(180), math.radians(90)),
    ("NEG_X", 0): (math.radians(-90), 0.0, math.radians(90)),
    ("NEG_X", 1): (0.0, math.radians(-90), 0.0),
    ("POS_X", 0): (math.radians(90), 0.0, math.radians(90)),
    ("POS_X", 1): (0.0, math.radians(90), 0.0),
    ("NEG_Y", 0): (math.radians(90), 0.0, 0.0),
    ("NEG_Y", 1): (math.radians(90), math.radians(90), 0.0),
    ("POS_Y", 0): (math.radians(-90), 0.0, 0.0),
    ("POS_Y", 1): (math.radians(-90), math.radians(-90), 0.0),
}

BEND_TREND_SCALE = 0.2
# Inactive / active opacity for red/green trend arcs (kept separate from
# strength/direction/limits handles).
BEND_TREND_ALPHA = 0.9
BEND_TREND_ALPHA_ACTIVE = 1.0


def _resolved_alignment(alignment, bounds):
    if alignment != "AUTO":
        return alignment
    extents = bounds[1] - bounds[0]
    return ("POS_X", "POS_Y", "POS_Z")[
        max(range(3), key=lambda index: extents[index])]


def bend_trend_reference_bounds(context, target, modifier):
    """Legacy input bounds for AUTO alignment and bounds-only callers."""
    if target is None:
        return _freeze_empty_bounds()
    if modifier is not None and context is not None:
        try:
            return _modifier_input_bounds(context, target, modifier)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return _object_fallback_bounds(target)


def _freeze_empty_bounds():
    zero = Vector((0.0, 0.0, 0.0))
    return zero.copy().freeze(), zero.copy().freeze()


_BEND_TREND_FACE_AXES = {
    "POS_X": (0, 1.0),
    "NEG_X": (0, -1.0),
    "POS_Y": (1, 1.0),
    "NEG_Y": (1, -1.0),
    "POS_Z": (2, 1.0),
    "NEG_Z": (2, -1.0),
}


def _deformation_jacobian(
        properties, point, half, preview_output_frame=None):
    """Finite-difference the configured deformation at a cage face point.

    Face-normal samples are one-sided toward the cage interior.  This keeps
    WITHIN_BOX mode on the deformed branch instead of sampling an unchanged
    point immediately outside the limit.
    """
    chain_stretch_state = (
        _core_module.chain_global_stretch_preview_state(properties))
    chain_prefix_state = (
        _core_module.chain_global_prefix_preview_state(properties))

    def preview(value):
        return Vector(deform_point_for_display(
            value, properties,
            chain_prefix_state=chain_prefix_state,
            chain_stretch_state=chain_stretch_state,
            preview_output_frame=preview_output_frame))

    point = Vector(point)
    center = preview(point)
    jacobian = Matrix.Identity(3)
    for axis in range(3):
        step = max(abs(float(properties.size[axis])) * 1.0e-4, 1.0e-5)
        lower = -float(half[axis])
        upper = float(half[axis])
        coordinate = float(point[axis])
        if coordinate <= lower + step * 0.5:
            sample = point.copy()
            sample[axis] = min(coordinate + step, upper)
            span = max(float(sample[axis]) - coordinate, EPSILON)
            derivative = (preview(sample) - center) / span
        elif coordinate >= upper - step * 0.5:
            sample = point.copy()
            sample[axis] = max(coordinate - step, lower)
            span = max(coordinate - float(sample[axis]), EPSILON)
            derivative = (center - preview(sample)) / span
        else:
            before = point.copy()
            after = point.copy()
            before[axis] = coordinate - step
            after[axis] = coordinate + step
            derivative = (
                preview(after) - preview(before)) / (2.0 * step)
        if derivative.length <= EPSILON:
            derivative = Vector((
                1.0 if axis == 0 else 0.0,
                1.0 if axis == 1 else 0.0,
                1.0 if axis == 2 else 0.0,
            ))
        jacobian.col[axis] = derivative
    return center, jacobian


def _bend_trend_local_frames(properties):
    """Cache deformed face anchors and local Jacobians for all selectors."""
    signature, preview_output_frame = cage_preview_geometry_state(properties)
    cached = _BEND_TREND_LOCAL_FRAME_CACHE.get(signature)
    if cached is not None:
        return cached

    half = Vector(properties.size) * 0.5
    gap = max(min(abs(float(value)) for value in half) * 0.035, 0.02)
    frames = {}
    for alignment, (normal_axis, normal_sign) in _BEND_TREND_FACE_AXES.items():
        face_point = Vector((0.0, 0.0, 0.0))
        face_point[normal_axis] = normal_sign * half[normal_axis]
        center, jacobian = _deformation_jacobian(
            properties, face_point, half, preview_output_frame)

        tangent_axes = tuple(index for index in range(3)
                             if index != normal_axis)
        normal = Vector(jacobian.col[tangent_axes[0]]).cross(
            Vector(jacobian.col[tangent_axes[1]]))
        expected = Vector(jacobian.col[normal_axis]) * normal_sign
        if normal.length <= EPSILON:
            normal = expected
        elif normal.dot(expected) < 0.0:
            normal.negate()
        if normal.length <= EPSILON:
            normal = Vector((
                normal_sign if normal_axis == 0 else 0.0,
                normal_sign if normal_axis == 1 else 0.0,
                normal_sign if normal_axis == 2 else 0.0,
            ))
        normal.normalize()
        center = center + normal * gap
        frames[alignment] = (
            center.freeze(),
            jacobian.copy().freeze(),
        )
    return _cache_geometry(
        _BEND_TREND_LOCAL_FRAME_CACHE, signature, frames)


def bend_trend_deformed_face_frame(properties, alignment):
    """Return the cached deformed local anchor/Jacobian for one trend face."""
    return _bend_trend_local_frames(properties)[alignment]


def _deformed_trend_basis_matrix(cage_matrix, jacobian, local_rotation):
    """Transform a selector basis through both deformation and cage space."""
    local_basis = local_rotation.to_3x3()
    transformed = cage_matrix.to_3x3() @ jacobian @ local_basis
    fallback = cage_matrix.to_3x3() @ local_basis
    result = Matrix.Identity(4)
    for index in range(3):
        axis = Vector(transformed.col[index])
        if axis.length <= EPSILON:
            axis = Vector(fallback.col[index])
        if axis.length <= EPSILON:
            axis = Vector((
                1.0 if index == 0 else 0.0,
                1.0 if index == 1 else 0.0,
                1.0 if index == 2 else 0.0,
            ))
        axis.normalize()
        result.col[index][0:3] = axis
    return result


def bend_trend_handle_matrix(
        target, alignment, variant, bounds=None, *, controller=None):
    """Place a bend-trend arrow in the active cage's local frame.

    Older versions used the target object's input bounds and ``matrix_world``
    rotation directly.  That made the chooser drift as soon as the controller
    was moved or rotated, and non-uniform object scale made the drift worse.
    When a controller is available, both the face center and the arrow basis
    now come from the same cage matrix used by the editable cage wireframe.
    The old bounds-only path remains for callers that only need the legacy
    reference-box behavior.
    """
    euler = _BEND_TREND_FACE_ROTATIONS[(alignment, int(variant))]
    local_rotation = Euler(euler, "XYZ").to_matrix().to_4x4()

    if controller is not None and target is not None:
        properties = controller.sdh_cage_deform
        half = Vector(properties.size) * 0.5
        face_point, jacobian = bend_trend_deformed_face_frame(
            properties, alignment)
        cage_matrix = cage_local_matrix(target, controller)
        matrix = _deformed_trend_basis_matrix(
            cage_matrix, jacobian, local_rotation)
        matrix.translation = cage_matrix @ Vector(face_point)
        cage_bounds = ((-half).freeze(), half.freeze())
        return matrix, BEND_TREND_SCALE, cage_bounds

    if bounds is None:
        bounds = _object_fallback_bounds(target)
    top, bottom, left, right, front, back = GizmoUtils.co_to_direction(
        Matrix(), bounds)
    face_points = {
        "POS_Z": top,
        "NEG_Z": bottom,
        "NEG_X": left,
        "POS_X": right,
        "NEG_Y": front,
        "POS_Y": back,
    }
    point = face_points[alignment]
    world = target.matrix_world
    matrix = world.to_euler().to_matrix().to_4x4() @ local_rotation
    matrix.translation = world @ Vector(point)
    return matrix, BEND_TREND_SCALE, bounds


class SDHCageBendTrendGizmo(Gizmo):
    bl_idname = "SDH_GT_cage_bend_trend"
    bl_label = "Choose Bend Trend"
    bl_target_properties = ()

    __slots__ = ("custom_shape", "alignment", "variant")

    def setup(self):
        # Use the classic bend-direction mesh. Its local axes match the Euler
        # layout from BendAxiSwitchGizmoGroup; the flat XY arc did not.
        from ..src.shape import __shape__
        self.custom_shape = self.new_custom_shape(
            "TRIS", __shape__["SimpleDeform_Bend_Direction_"])
        self.use_tooltip = True
        self.use_draw_modal = True
        self.use_draw_value = False
        # Fixed size like classic bend-axis arrows; avoids the large→small flash
        # when face-proportional scaling was applied on the first redraw.
        self.scale_basis = BEND_TREND_SCALE
        self.alpha = BEND_TREND_ALPHA
        self.alpha_highlight = 1.0

    def _update_matrix(self, context):
        if _consume_matrix_fresh(self):
            return True
        target, _modifier, controller = _gizmo_stage_context(self, context)
        if target is None or controller is None:
            return False
        properties = controller.sdh_cage_deform
        if ("BEND" not in _enabled_deform_types(properties) or
                not properties.show_axis_gizmo):
            return False

        alignment = getattr(self, "alignment", "POS_Y")
        variant = int(getattr(self, "variant", 0))
        self.matrix_basis, scale, bounds = bend_trend_handle_matrix(
            target, alignment, variant, controller=controller)
        self.scale_basis = scale
        active_alignment = _resolved_alignment(properties.alignment, bounds)
        # Use resolve (no log spam); click path logs via operator + bend_trend_target.
        frame_rotation = _core_module._controller_rotation_xyz(
            controller).to_matrix()
        result_alignment, target_direction = resolve_bend_trend(
            alignment, variant, frame_rotation)
        direction_delta = abs((
            properties.bend_direction - target_direction + math.pi) %
            math.tau - math.pi)
        active = (
            active_alignment == result_alignment and
            direction_delta < math.radians(2.0))
        normal, highlight = BEND_TREND_COLORS[variant]
        self.color = highlight if active else normal
        self.color_highlight = highlight
        self.alpha = (
            BEND_TREND_ALPHA_ACTIVE if active else BEND_TREND_ALPHA)
        return True

    def draw(self, context):
        if self._update_matrix(context):
            draw_cage_custom_shape(self, self.custom_shape)

    def draw_select(self, context, select_id):
        if self._update_matrix(context):
            draw_cage_custom_shape(
                self, self.custom_shape, select_id=select_id)


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
        self.use_tooltip = True
        self.use_draw_modal = True
        self.use_draw_value = False
        self.scale_basis = 0.14

    def _update_matrix(self, context):
        if _consume_matrix_fresh(self):
            return True
        target, _modifier, controller = resolve_context_deform(
            context, fallback=False)
        if target is None or controller is None:
            return False
        properties = controller.sdh_cage_deform
        if (not properties.show_axis_gizmo or
                "BEND" in _enabled_deform_types(properties)):
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
            draw_cage_custom_shape(self, self._shape())

    def draw_select(self, context, select_id):
        if self._update_matrix(context):
            draw_cage_custom_shape(
                self, self._shape(), select_id=select_id)


def boundary_tooltip_key(target, modifier, side):
    """Return TOP, BOTTOM, or SHARED for one visible boundary handle."""
    side = str(side or "").upper()
    if side not in {"TOP", "BOTTOM"}:
        side = "TOP"
    chain_uuid = stage_chain_uuid(modifier)
    stages = chain_stages(target, chain_uuid)
    if (
            not chain_uuid or len(stages) < 2 or
            stage_chain_mode(stages[0], "").upper() not in {
                "CHAINED", "CONNECTED"
            }
    ):
        return side
    try:
        index = stages.index(modifier)
    except ValueError:
        return side
    shared = index < len(stages) - 1 if side == "TOP" else index > 0
    return "SHARED" if shared else side


class SDHCageEndShapeGizmo(Gizmo):
    bl_idname = "SDH_GT_cage_end_shape"
    bl_label = "Cage End Shape"
    bl_target_properties = (
        {"id": "tooltip", "type": "FLOAT", "array_length": 1},
    )

    __slots__ = (
        "custom_shape",
        "top_shape",
        "bottom_shape",
        "side",
        "initial_scale",
        "initial_offset",
        "original_scale",
        "original_offset",
        "initial_mouse_x",
        "initial_mouse_y",
        "stage_target",
        "stage_modifier",
        "stage_controller",
        "invoke_target",
        "invoke_modifier",
        "invoke_controller",
        "_mod_flags",
        "_tooltip_key",
        "_tooltip_owner_pointer",
    )

    def setup(self):
        # Use distinct silhouettes for the two independently editable ends.
        # The top handle is a crown/chevron and the bottom handle is a tray;
        # this remains readable even when both handles project close together.
        self.top_shape = self.new_custom_shape("TRIS", (
            (-0.82, -0.38, 0.0), (0.0, 0.76, 0.0), (0.82, -0.38, 0.0),
            (-0.52, -0.20, 0.0), (0.0, 0.38, 0.0), (0.52, -0.20, 0.0),
            (-0.62, -0.58, 0.0), (0.62, -0.58, 0.0), (0.0, -0.28, 0.0),
        ))
        self.bottom_shape = self.new_custom_shape("TRIS", (
            (-0.82, 0.38, 0.0), (0.0, -0.76, 0.0), (0.82, 0.38, 0.0),
            (-0.52, 0.20, 0.0), (0.0, -0.38, 0.0), (0.52, 0.20, 0.0),
            (-0.62, 0.58, 0.0), (0.62, 0.58, 0.0), (0.0, 0.28, 0.0),
        ))
        self.use_tooltip = True
        self.use_draw_modal = True
        self.use_draw_value = False
        self.scale_basis = 0.14
        self.stage_target = None
        self.stage_modifier = None
        self.stage_controller = None
        self.initial_scale = (1.0, 1.0)
        self.initial_offset = (0.0, 0.0)
        self.original_scale = self.initial_scale
        self.original_offset = self.initial_offset
        self.initial_mouse_x = 0.0
        self.initial_mouse_y = 0.0
        self.invoke_target = None
        self.invoke_modifier = None
        self.invoke_controller = None
        self._tooltip_key = ""
        self._tooltip_owner_pointer = 0

    def _set_tooltip_target(self, properties, side):
        key = "TOP" if str(side).upper() == "TOP" else "BOTTOM"
        try:
            owner_pointer = int(properties.as_pointer())
        except (AttributeError, ReferenceError, TypeError, ValueError):
            owner_pointer = id(properties)
        if (
                self._tooltip_key == key and
                self._tooltip_owner_pointer == owner_pointer
        ):
            return
        self.target_set_prop(
            "tooltip", properties,
            f"tooltip_{key.lower()}_end_shape")
        self._tooltip_key = key
        self._tooltip_owner_pointer = owner_pointer

    def _update_matrix(self, context):
        if _consume_matrix_fresh(self):
            return True
        target, _modifier, controller = _gizmo_stage_context(self, context)
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
            shape = (
                self.top_shape if getattr(self, "side", "TOP") == "TOP"
                else self.bottom_shape)
            draw_cage_custom_shape(self, shape)

    def draw_select(self, context, select_id):
        if self._update_matrix(context):
            shape = (
                self.top_shape if getattr(self, "side", "TOP") == "TOP"
                else self.bottom_shape)
            draw_cage_custom_shape(self, shape, select_id=select_id)

    def invoke(self, context, event):
        try:
            target, modifier, controller = _gizmo_stage_context(self, context)
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            return {"CANCELLED"}
        if target is None or modifier is None or controller is None:
            return {"CANCELLED"}
        self.invoke_target = target
        self.invoke_modifier = modifier
        self.invoke_controller = controller
        properties = controller.sdh_cage_deform
        prefix = "top" if getattr(self, "side", "TOP") == "TOP" else "bottom"
        self.initial_scale = tuple(getattr(properties, f"{prefix}_scale"))
        self.initial_offset = tuple(getattr(properties, f"{prefix}_offset"))
        self.original_scale = self.initial_scale
        self.original_offset = self.initial_offset
        self.initial_mouse_x = event.mouse_region_x
        self.initial_mouse_y = event.mouse_region_y
        self._mod_flags = (
            bool(getattr(event, "shift", False)),
            bool(getattr(event, "ctrl", False)),
            bool(getattr(event, "alt", False)),
        )
        _begin_end_shape_preview_drag(
            target, modifier, controller, getattr(self, "side", "TOP"))
        return {"RUNNING_MODAL"}

    def modal(self, context, event, _tweak):
        try:
            target, modifier, controller = _invoked_gizmo_stage(self)
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            _end_shape_preview_drag()
            return {"CANCELLED"}
        if (
                target is None or modifier is None or controller is None
        ):
            _end_shape_preview_drag()
            return {"CANCELLED"}
        properties = controller.sdh_cage_deform
        side = getattr(self, "side", "TOP")
        prefix = "top" if side == "TOP" else "bottom"
        side_label = bpy.app.translations.pgettext_iface(side.title())
        tweak = _tweak or ()
        flags = (
            bool(getattr(event, "shift", False)),
            bool(getattr(event, "ctrl", False)) or "SNAP" in tweak,
            bool(getattr(event, "alt", False)),
        )
        if flags != self._mod_flags:
            self.initial_scale = tuple(getattr(properties, f"{prefix}_scale"))
            self.initial_offset = tuple(getattr(properties, f"{prefix}_offset"))
            self.initial_mouse_x = event.mouse_region_x
            self.initial_mouse_y = event.mouse_region_y
            self._mod_flags = flags
        shift, snap, alt = flags

        mouse_delta_x = event.mouse_region_x - self.initial_mouse_x
        mouse_delta_y = event.mouse_region_y - self.initial_mouse_y

        # End offsets are stored in the cage cross-section as X/Z.  The
        # interaction intentionally exposes screen-space names: Alt locks to
        # screen X, Shift locks to screen Y, and Alt+Shift enables both axes.
        free_offset = alt and shift
        x_offset = alt or free_offset
        z_offset = shift or free_offset
        if x_offset or z_offset:
            delta_x = mouse_delta_x * 0.005 if x_offset else 0.0
            delta_z = mouse_delta_y * 0.005 if z_offset else 0.0
            if snap:
                delta_x = round(delta_x * 10.0) / 10.0
                delta_z = round(delta_z * 10.0) / 10.0
            value = (
                self.initial_offset[0] + delta_x,
                self.initial_offset[1] + delta_z,
            )
            if any(
                    abs(float(current) - float(requested)) > EPSILON
                    for current, requested in zip(
                        getattr(properties, f"{prefix}_offset"), value)
            ):
                _begin_gizmo_undo(self)
                setattr(properties, f"{prefix}_offset", value)
            offset_label = bpy.app.translations.pgettext_iface("Offset")
            if free_offset:
                label = (
                    f"{side_label} {offset_label} X: {value[0]:.3f}, "
                    f"Y: {value[1]:.3f}")
            elif alt:
                label = f"{side_label} {offset_label} X: {value[0]:.3f}"
            else:
                label = f"{side_label} {offset_label} Y: {value[1]:.3f}"
        else:
            delta = mouse_delta_x * 0.01
            if snap:
                delta = round(delta * 10.0) / 10.0
            value = (
                max(0.05, self.initial_scale[0] + delta),
                max(0.05, self.initial_scale[1] + delta),
            )
            if any(
                    abs(float(current) - float(requested)) > EPSILON
                    for current, requested in zip(
                        getattr(properties, f"{prefix}_scale"), value)
            ):
                _begin_gizmo_undo(self)
                setattr(properties, f"{prefix}_scale", value)
            scale_label = bpy.app.translations.pgettext_iface("Scale")
            label = f"{side_label} {scale_label}: {value[0]:.3f}, {value[1]:.3f}"

        if context.area:
            shortcuts = bpy.app.translations.pgettext_iface(
                "Alt: Screen X | Shift: Screen Y | Alt+Shift: Free | Ctrl: Snap")
            context.area.header_text_set(
                label + "   |   " + shortcuts)
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def exit(self, context, cancel):
        controller = getattr(self, "invoke_controller", None)
        if cancel and controller:
            try:
                properties = controller.sdh_cage_deform
                prefix = (
                    "top" if getattr(self, "side", "TOP") == "TOP"
                    else "bottom")
                setattr(properties, f"{prefix}_scale", self.original_scale)
                setattr(properties, f"{prefix}_offset", self.original_offset)
            except (AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError):
                pass
        _flush_invoked_chain_updates(self)
        _end_shape_preview_drag()
        _finish_gizmo_undo(self, cancel=cancel, message="Cage End Shape")
        if context.area:
            context.area.header_text_set(None)
            context.area.tag_redraw()


class SDHCageBoundaryGizmo(Gizmo):
    bl_idname = "SDH_GT_cage_boundary"
    bl_label = "Cage Boundary"
    bl_target_properties = (
        {"id": "tooltip", "type": "FLOAT", "array_length": 1},
    )

    __slots__ = (
        "custom_shape",
        "side",
        "initial_size",
        "initial_location",
        "original_size",
        "original_location",
        "initial_curve_range",
        "original_curve_range",
        "initial_mouse",
        "axis_screen",
        "units_per_pixel",
        "boundary_limits",
        "shared_edit_state",
        "chain_edit_state",
        "original_shared_edit_state",
        "original_chain_state",
        "stage_target",
        "stage_modifier",
        "stage_controller",
        "invoke_target",
        "invoke_modifier",
        "invoke_controller",
        "_mod_flags",
        "_tooltip_key",
        "_tooltip_owner_pointer",
    )

    def setup(self):
        from ..src.shape import __shape__
        self.custom_shape = self.new_custom_shape(
            "TRIS", __shape__["Sphere_GizmoGroup_"])
        self.use_tooltip = True
        self.use_draw_modal = True
        self.use_draw_value = False
        # Avoid Blender default scale_basis=1.0 flash before first update.
        self.scale_basis = 0.17
        # Initialize modal state so an invoke cancelled during a depsgraph
        # rebuild can still pass through Blender's exit callback cleanly.
        self.stage_target = None
        self.stage_modifier = None
        self.stage_controller = None
        self.invoke_target = None
        self.invoke_modifier = None
        self.invoke_controller = None
        self.shared_edit_state = None
        self.chain_edit_state = None
        self.original_shared_edit_state = None
        self.original_chain_state = None
        self.initial_curve_range = (0.0, 1.0)
        self.original_curve_range = (0.0, 1.0)
        self._tooltip_key = ""
        self._tooltip_owner_pointer = 0

    def _set_tooltip_target(self, properties, key):
        key = str(key or "").upper()
        if key not in {"TOP", "BOTTOM", "SHARED"}:
            key = "TOP"
        try:
            owner_pointer = int(properties.as_pointer())
        except (AttributeError, ReferenceError, TypeError, ValueError):
            owner_pointer = id(properties)
        if (
                self._tooltip_key == key and
                self._tooltip_owner_pointer == owner_pointer
        ):
            return
        self.target_set_prop(
            "tooltip", properties, f"tooltip_{key.lower()}_boundary")
        self._tooltip_key = key
        self._tooltip_owner_pointer = owner_pointer

    def _update_matrix(self, context):
        if _consume_matrix_fresh(self):
            return True
        target, _modifier, controller = _gizmo_stage_context(self, context)
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
            draw_cage_custom_shape(self, self.custom_shape)

    def draw_select(self, context, select_id):
        if self._update_matrix(context):
            draw_cage_custom_shape(
                self, self.custom_shape, select_id=select_id)

    def invoke(self, context, event):
        try:
            target, modifier, controller = _gizmo_stage_context(self, context)
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            return {"CANCELLED"}
        if target is None or controller is None:
            return {"CANCELLED"}

        # A direct Empty transform can be queued for the next dependency-graph
        # tick.  Consume it before taking the modal snapshot so the boundary
        # edit starts from the frame the user can currently see.
        try:
            flush_pending_chain_updates(target)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            # A file reload or an in-flight depsgraph rebuild may temporarily
            # reject the flush.  The context and snapshot checks below still
            # prevent an unsafe cross-object edit.
            pass

        # The flush can trigger a redraw and, in unusual cases, replace the
        # stage wrapper. Refuse to begin if the bound stage no longer exists.
        try:
            refreshed_target, refreshed_modifier, refreshed_controller = (
                _live_gizmo_stage(target, modifier, controller))
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            return {"CANCELLED"}
        if (
                not _same_rna_value(target, refreshed_target) or
                not _same_rna_value(modifier, refreshed_modifier) or
                not _same_rna_value(controller, refreshed_controller)
        ):
            return {"CANCELLED"}
        target, modifier, controller = (
            refreshed_target, refreshed_modifier, refreshed_controller)

        # Keep the invoke context for the entire modal lifetime.  Looking up
        # the current active object in ``modal``/``exit`` is unsafe when the
        # user clicks another controller while a drag is still being closed.
        self.invoke_target = target
        self.invoke_modifier = modifier
        self.invoke_controller = controller
        properties = controller.sdh_cage_deform
        side = getattr(self, "side", "TOP")
        self.initial_size = tuple(properties.size)
        self.initial_location = tuple(controller.location)
        self.original_size = self.initial_size
        self.original_location = self.initial_location
        self.initial_curve_range = curve_effect_range(properties)
        self.original_curve_range = self.initial_curve_range
        self.initial_mouse = (event.mouse_region_x, event.mouse_region_y)
        self.axis_screen = (0.0, 1.0)
        self.units_per_pixel = max(properties.size[1] / 250.0, EPSILON)
        self.boundary_limits = None
        try:
            self.original_chain_state = capture_chain_boundary_state(
                target, modifier, controller, side)
            self.shared_edit_state = (
                self.original_chain_state
                if self.original_chain_state is not None and
                self.original_chain_state.get("shared")
                else None
            )
            self.chain_edit_state = self.original_chain_state
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            return {"CANCELLED"}
        self.original_shared_edit_state = self.shared_edit_state
        self._mod_flags = _event_mod_flags(event)
        if (
                self.shared_edit_state is None and
                properties.limit_boundaries_to_object
        ):
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
            is_curve = str(getattr(properties, "cage_type", "")) == "CURVE"
            if is_curve:
                # Convert screen motion from the actual local source-to-guide
                # derivative.  A fixed output-space handle length feels much
                # too fast or slow when the guide is heavily stretched.
                from .curve import curve_preview_deformer
                range_start, range_end = curve_effect_range(properties)
                boundary_factor = range_end if side == "TOP" else range_start
                source_length = max(abs(float(properties.size[1])), EPSILON)
                source_step = max(source_length * 0.01, 1.0e-5)
                boundary_y = -source_length * 0.5 + (
                    source_length * boundary_factor)
                neighbor_y = boundary_y + (
                    -source_step if side == "TOP" else source_step)
                structural_mapper = curve_preview_deformer(
                    properties, apply_effect_range=False)
                neighbor = deform_point_for_display(
                    (0.0, neighbor_y, 0.0), properties,
                    curve_deformer_override=structural_mapper)
                neighbor_2d = view3d_utils.location_3d_to_region_2d(
                    context.region, context.space_data.region_3d,
                    matrix @ Vector(neighbor))
                projected = (
                    boundary_2d - neighbor_2d
                    if side == "TOP" else neighbor_2d - boundary_2d)
                local_offset = source_step
            else:
                handle_2d = view3d_utils.location_3d_to_region_2d(
                    context.region, context.space_data.region_3d,
                    matrix @ handle)
                projected = (
                    handle_2d - boundary_2d
                    if handle_2d is not None and boundary_2d is not None else
                    None)
                if projected is not None and side == "BOTTOM":
                    projected.negate()
                local_offset = (handle - boundary).length
            if boundary_2d is not None and projected is not None:
                if projected.length > 2.0:
                    self.axis_screen = tuple(projected.normalized())
                    self.units_per_pixel = max(
                        local_offset / projected.length, EPSILON)
        except (AttributeError, ImportError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            pass
        return {"RUNNING_MODAL"}

    def modal(self, context, event, _tweak):
        try:
            target, modifier, controller = _invoked_gizmo_stage(self)
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            return {"CANCELLED"}
        if (
                target is None or modifier is None or controller is None
        ):
            return {"CANCELLED"}
        properties = controller.sdh_cage_deform
        flags = _event_mod_flags(event, _tweak)
        # Critical: Shift/Ctrl must not re-scale the full drag against the
        # original click position — that jumps controller.location.
        if flags != self._mod_flags:
            self.initial_size = tuple(properties.size)
            self.initial_location = tuple(controller.location)
            self.initial_curve_range = curve_effect_range(properties)
            previous_chain_state = self.chain_edit_state
            try:
                next_chain_state = capture_chain_boundary_state(
                    target, modifier, controller,
                    getattr(self, "side", "TOP"))
            except (AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError):
                return {"CANCELLED"}
            if ((previous_chain_state is None) !=
                    (next_chain_state is None)):
                # A drag cannot switch between an outer one-cage boundary and
                # an interior two-controller seam.  Either transition means
                # the chain topology changed underneath the modal operation.
                return {"CANCELLED"}
            self.chain_edit_state = next_chain_state
            self.shared_edit_state = (
                next_chain_state
                if next_chain_state is not None and
                next_chain_state.get("shared")
                else None
            )
            self.initial_mouse = (event.mouse_region_x, event.mouse_region_y)
            self._mod_flags = flags
        precise, ctrl, alt = flags

        mouse_delta = Vector((
            event.mouse_region_x - self.initial_mouse[0],
            event.mouse_region_y - self.initial_mouse[1],
        ))
        axis_delta = mouse_delta.dot(Vector(self.axis_screen)) * self.units_per_pixel
        if precise:
            axis_delta *= 0.1
        boundary_mode = (
            "SYMMETRIC" if alt else "TRANSLATE" if ctrl else "SINGLE")
        if abs(float(axis_delta)) > EPSILON:
            _begin_gizmo_undo(self)

        side = getattr(self, "side", "TOP")
        if (
                self.chain_edit_state is not None and
                (boundary_mode != "SINGLE" or
                 self.shared_edit_state is not None)
        ):
            try:
                shared_result = apply_shared_boundary_edit(
                    self.chain_edit_state, axis_delta, boundary_mode)
            except (AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError):
                return {"CANCELLED"}
            if shared_result is None:
                # The chain topology/frame changed while dragging.  Cancelling
                # is the only safe result; a normal single-cage move would
                # leave the neighboring stage disconnected or overlapping.
                return {"CANCELLED"}
            applied = shared_result["applied_delta"]
            new_length = shared_result["active_length"]
        else:
            shared_result = None
            try:
                applied, new_length = move_cage_boundary(
                    controller,
                    side,
                    axis_delta,
                    self.initial_size,
                    self.initial_location,
                    self.boundary_limits,
                    boundary_mode=boundary_mode,
                    initial_curve_range=self.initial_curve_range,
                )
            except (AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError):
                return {"CANCELLED"}
        if context.area:
            boundary_label = bpy.app.translations.pgettext_iface(
                "Shared Boundary" if shared_result is not None
                else f"{side.title()} Boundary")
            length_label = bpy.app.translations.pgettext_iface(
                "Effect Range Length"
                if str(getattr(properties, "cage_type", "")) == "CURVE"
                else "Cage Length")
            shortcuts = bpy.app.translations.pgettext_iface(
                "Drag Along Cage • Shift Precise • Ctrl Move Both • Alt Opposite")
            context.area.header_text_set(
                f"{boundary_label}: {applied:+.3f}   |   "
                f"{length_label}: {new_length:.3f}   |   {shortcuts}")
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def exit(self, context, cancel):
        # Always use the controller captured by invoke.  The active context
        # may point at another stage by the time Blender asks us to exit.
        controller = getattr(self, "invoke_controller", None)
        original_shared_state = getattr(
            self, "original_shared_edit_state", None)
        original_chain_state = getattr(self, "original_chain_state", None)
        if cancel:
            try:
                restored = restore_shared_boundary_edit(
                    original_chain_state or original_shared_state)
            except (AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError):
                restored = False
            if (
                    not restored and
                    original_shared_state is None and
                    controller
            ):
                try:
                    move_cage_boundary(
                        controller,
                        getattr(self, "side", "TOP"),
                        0.0,
                        getattr(self, "original_size", ()),
                        getattr(self, "original_location", ()),
                        getattr(self, "boundary_limits", None),
                        initial_curve_range=getattr(
                            self, "original_curve_range", (0.0, 1.0)),
                    )
                except (AttributeError, ReferenceError, RuntimeError, TypeError,
                        ValueError):
                    pass
        _flush_invoked_chain_updates(self)
        _finish_gizmo_undo(self, cancel=cancel, message="Cage Boundary")
        if context.area:
            context.area.header_text_set(None)
            context.area.tag_redraw()


_OTHER_STAGE_PARAMETER_GIZMOS = (
    SDHCageBendStrengthGizmo,
    SDHCageTwistStrengthGizmo,
    SDHCageTaperFactorGizmo,
    SDHCageStretchFactorGizmo,
    SDHCageShearGizmo,
)
_MAX_OTHER_STAGE_EDIT_BUNDLES = 7


def _new_other_stage_edit_bundle():
    """Return an empty inactive-stage bundle that grows only when visible."""
    return {
        "parameter_handles": {},
        "ffd_handles": [],
        "direction_handle": None,
        "end_handles": [],
        "boundary_handles": [],
        "bound_stage": (None, None, None),
        "unbound_handles": [],
    }


def _other_stage_bundle_handles(bundle):
    direction = bundle["direction_handle"]
    return (
        *bundle["parameter_handles"].values(),
        *bundle["ffd_handles"],
        *((direction,) if direction is not None else ()),
        *bundle["end_handles"],
        *bundle["boundary_handles"],
    )


def _register_other_stage_handle(bundle, handle):
    handle.hide = True
    bundle["unbound_handles"].append(handle)
    return handle


def _ensure_other_stage_bundle(gizmos, bundle, properties):
    """Allocate only controls that this inactive stage can currently show."""
    enabled_types = _enabled_deform_types(properties)
    parameter_handles = bundle["parameter_handles"]
    for gizmo_type in _OTHER_STAGE_PARAMETER_GIZMOS:
        deform_type = gizmo_type.DEFORM_TYPE
        if deform_type not in enabled_types or deform_type in parameter_handles:
            continue
        handle = _register_other_stage_handle(
            bundle, gizmos.new(gizmo_type.bl_idname))
        handle.color = TYPE_HANDLE_COLORS[deform_type][0]
        handle.color_highlight = TYPE_HANDLE_COLORS[deform_type][1]
        handle.alpha = 0.48
        handle.alpha_highlight = 1.0
        handle.scale_basis = 0.18
        parameter_handles[deform_type] = handle

    if (
            "BEND" in enabled_types and properties.show_direction_handle and
            bundle["direction_handle"] is None
    ):
        direction = _register_other_stage_handle(
            bundle, gizmos.new(SDHCageDirectionGizmo.bl_idname))
        direction.color = (0.88, 0.32, 1.0)
        direction.color_highlight = (1.0, 0.78, 1.0)
        direction.alpha = 0.48
        direction.alpha_highlight = 1.0
        direction.scale_basis = 0.14
        bundle["direction_handle"] = direction

    if "FFD" in enabled_types and ffd_handles_enabled():
        corner_indices = ffd_display_corner_indices(properties)
        while len(bundle["ffd_handles"]) < len(corner_indices):
            handle = _register_other_stage_handle(
                bundle, gizmos.new(SDHCageFFDCornerGizmo.bl_idname))
            handle.alpha = 0.48
            handle.alpha_highlight = 1.0
            handle.scale_basis = 0.13
            bundle["ffd_handles"].append(handle)
        for handle, corner_index in zip(
                bundle["ffd_handles"], corner_indices):
            handle.corner_index = corner_index

    if properties.show_end_handles and not bundle["end_handles"]:
        for side, color, highlight in (
                ("TOP", (0.0, 0.85, 1.0), (0.65, 1.0, 1.0)),
                ("BOTTOM", (0.0, 1.0, 0.55), (0.65, 1.0, 0.8))):
            handle = _register_other_stage_handle(
                bundle, gizmos.new(SDHCageEndShapeGizmo.bl_idname))
            handle.side = side
            handle.color = color
            handle.color_highlight = highlight
            handle.alpha = 0.52
            handle.alpha_highlight = 1.0
            handle.scale_basis = 0.14
            bundle["end_handles"].append(handle)

    if properties.show_boundary_handles and not bundle["boundary_handles"]:
        for side, color, highlight in (
                ("TOP", (1.0, 0.82, 0.05), (1.0, 1.0, 0.45)),
                ("BOTTOM", (1.0, 0.55, 0.02), (1.0, 0.9, 0.35))):
            handle = _register_other_stage_handle(
                bundle, gizmos.new(SDHCageBoundaryGizmo.bl_idname))
            handle.side = side
            handle.color = color
            handle.color_highlight = highlight
            handle.alpha = 0.55
            handle.alpha_highlight = 1.0
            handle.scale_basis = 0.17
            bundle["boundary_handles"].append(handle)


def _hide_other_stage_bundle(bundle):
    for handle in _other_stage_bundle_handles(bundle):
        if not handle.hide:
            handle.hide = True


def _same_bound_stage(bound_stage, target, modifier, controller):
    return all(_same_rna_value(first, second) for first, second in zip(
        bound_stage, (target, modifier, controller)))


def _prepare_other_stage_bundle(
        bundle, context, target, modifier, controller):
    properties = controller.sdh_cage_deform
    enabled_types = _enabled_deform_types(properties)
    binding_changed = not _same_bound_stage(
        bundle["bound_stage"], target, modifier, controller)
    if binding_changed:
        for handle in _other_stage_bundle_handles(bundle):
            _bind_gizmo_stage(handle, target, modifier, controller)
        bundle["bound_stage"] = (target, modifier, controller)
        bundle["unbound_handles"].clear()
    elif bundle["unbound_handles"]:
        for handle in bundle["unbound_handles"]:
            _bind_gizmo_stage(handle, target, modifier, controller)
        bundle["unbound_handles"].clear()

    for handle in bundle["parameter_handles"].values():
        handle.hide = handle.DEFORM_TYPE not in enabled_types
        if not handle.hide and handle.DEFORM_TYPE == "SHEAR":
            handle._set_tooltip_target(properties)

    for handle in bundle["ffd_handles"]:
        handle.hide = (
            "FFD" not in enabled_types or not ffd_handles_enabled() or
            bool(getattr(properties, "ffd_native_edit_mode_active", False)))
        # Once the persistent FFD editor is running, it owns point/line/face
        # picking and transforms. Keep the controller visible but remove this
        # parallel Gizmo hit target so Blender cannot cancel the editor while
        # dispatching the same click to both interaction systems.
        handle.hide_select = bool(
            not handle.hide and
            getattr(properties, "ffd_edit_mode_active", False))
        if not handle.hide:
            handle._set_tooltip_target(properties)

    direction = bundle["direction_handle"]
    if direction is not None:
        direction.hide = (
            "BEND" not in enabled_types or
            not properties.show_direction_handle)

    for handle in bundle["end_handles"]:
        handle.hide = not properties.show_end_handles
        if not handle.hide:
            handle._set_tooltip_target(
                properties, getattr(handle, "side", "TOP"))

    for handle in bundle["boundary_handles"]:
        handle.hide = not properties.show_boundary_handles
        if not handle.hide:
            handle._set_tooltip_target(
                properties,
                boundary_tooltip_key(
                    target, modifier, getattr(handle, "side", "TOP")),
            )

    try:
        stage_pointer = int(controller.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError,
            ValueError):
        stage_pointer = id(controller)
    visible_handles = tuple(
        handle for handle in _other_stage_bundle_handles(bundle)
        if not handle.hide and hasattr(handle, "_update_matrix"))
    visible_ids = tuple(id(handle) for handle in visible_handles)
    if (
            not binding_changed and
            _freeze_for_end_shape_drag(target, controller)
    ):
        for handle in visible_handles:
            _mark_matrix_fresh(handle)
        _request_throttled_redraw()
        return
    now = monotonic()
    if (
            bundle.get("_matrix_stage") == stage_pointer and
            bundle.get("_matrix_visible") == visible_ids and
            now - bundle.get("_matrix_time", 0.0) <
            _BUNDLE_MATRIX_THROTTLE_WINDOW
    ):
        # Inactive-stage handles keep their previously prepared matrices
        # during an input burst; the active stage stays per-event exact.
        _request_throttled_redraw()
        return
    bundle["_matrix_stage"] = stage_pointer
    bundle["_matrix_visible"] = visible_ids
    bundle["_matrix_time"] = now
    for handle in visible_handles:
        _invalidate_matrix_fresh(handle)
        handle._update_matrix(context)
        _mark_matrix_fresh(handle)


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
        if target is None or modifier is None or controller is None:
            target, modifier, controller = _ffd_edit_stage_context(context)
        return bool(
            target and modifier and controller and
            modifier.show_viewport and controller.sdh_cage_deform.show_cage
        )

    def setup(self, _context):
        # Set scale_basis immediately on every child. Blender defaults to 1.0
        # until Gizmo.setup/_update_matrix, which flashes huge handles.
        parameter_handles = []
        for gizmo_type in (
                SDHCageBendStrengthGizmo,
                SDHCageTwistStrengthGizmo,
                SDHCageTaperFactorGizmo,
                SDHCageStretchFactorGizmo,
                SDHCageShearGizmo):
            handle = self.gizmos.new(gizmo_type.bl_idname)
            handle.color = TYPE_HANDLE_COLORS[gizmo_type.DEFORM_TYPE][0]
            handle.alpha = 0.85
            handle.color_highlight = TYPE_HANDLE_COLORS[
                gizmo_type.DEFORM_TYPE][1]
            handle.alpha_highlight = 1.0
            handle.scale_basis = 0.18
            handle.hide = True
            parameter_handles.append(handle)
        self.parameter_handles = tuple(parameter_handles)

        # FFD point/line/face handles can greatly outnumber standard controls.
        # A non-FFD cage should not pay that allocation cost at group setup.
        self.ffd_handles = ()

        direction = self.gizmos.new(SDHCageDirectionGizmo.bl_idname)
        direction.color = (0.88, 0.32, 1.0)
        direction.alpha = 0.9
        direction.color_highlight = (1.0, 0.78, 1.0)
        direction.alpha_highlight = 1.0
        direction.scale_basis = 0.14
        direction.hide = True
        self.direction_handle = direction

        bend_trend_handles = []
        for alignment in (
                "POS_X", "NEG_X", "POS_Y", "NEG_Y", "POS_Z", "NEG_Z"):
            for variant in (0, 1):
                trend_handle = self.gizmos.new(
                    SDHCageBendTrendGizmo.bl_idname)
                trend_handle.alignment = alignment
                trend_handle.variant = variant
                trend_handle.scale_basis = BEND_TREND_SCALE
                trend_handle.alpha = BEND_TREND_ALPHA
                trend_handle.alpha_highlight = 1.0
                trend_handle.hide = True
                operator = trend_handle.target_set_operator(
                    SDH_OT_set_bend_trend.bl_idname)
                operator.alignment = alignment
                operator.variant = variant
                bend_trend_handles.append(trend_handle)
        self.bend_trend_handles = bend_trend_handles

        axis_handles = []
        for alignment in (
                "POS_X", "NEG_X", "POS_Y", "NEG_Y", "POS_Z", "NEG_Z"):
            axis_handle = self.gizmos.new(SDHCageAxisGizmo.bl_idname)
            axis_handle.axis = alignment
            axis_handle.scale_basis = 0.14
            axis_handle.alpha_highlight = 1.0
            axis_handle.hide = True
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
        top.scale_basis = 0.14
        top.hide = True
        self.top_handle = top

        bottom = self.gizmos.new(SDHCageEndShapeGizmo.bl_idname)
        bottom.side = "BOTTOM"
        bottom.color = (0.0, 1.0, 0.55)
        bottom.alpha = 0.9
        bottom.color_highlight = (0.65, 1.0, 0.8)
        bottom.alpha_highlight = 1.0
        bottom.scale_basis = 0.14
        bottom.hide = True
        self.bottom_handle = bottom

        top_boundary = self.gizmos.new(SDHCageBoundaryGizmo.bl_idname)
        top_boundary.side = "TOP"
        top_boundary.color = (1.0, 0.82, 0.05)
        top_boundary.alpha = 0.95
        top_boundary.color_highlight = (1.0, 1.0, 0.45)
        top_boundary.alpha_highlight = 1.0
        top_boundary.scale_basis = 0.17
        top_boundary.hide = True
        self.top_boundary_handle = top_boundary

        bottom_boundary = self.gizmos.new(SDHCageBoundaryGizmo.bl_idname)
        bottom_boundary.side = "BOTTOM"
        bottom_boundary.color = (1.0, 0.55, 0.02)
        bottom_boundary.alpha = 0.95
        bottom_boundary.color_highlight = (1.0, 0.9, 0.35)
        bottom_boundary.alpha_highlight = 1.0
        bottom_boundary.scale_basis = 0.17
        bottom_boundary.hide = True
        self.bottom_boundary_handle = bottom_boundary

        # The active stage uses the handles above. Inactive-stage bundles grow
        # lazily according to the visible stages and their enabled operations.
        self.other_stage_handle_bundles = []

    def _ensure_ffd_handle_count(self, count):
        if int(count) <= 0:
            return
        handles = list(self.ffd_handles)
        if not handles:
            handle = self.gizmos.new(SDHCageFFDAggregateGizmo.bl_idname)
            handle.alpha = 0.9
            handle.alpha_highlight = 1.0
            handle.scale_basis = 0.13
            handle.hide = True
            handles.append(handle)
        self.ffd_handles = tuple(handles)

    def draw_prepare(self, context):
        other_stage_handle_bundles = getattr(
            self, "other_stage_handle_bundles", ())
        target, modifier, controller = resolve_context_deform(
            context, fallback=False)
        if target is None or modifier is None or controller is None:
            target, modifier, controller = _ffd_edit_stage_context(context)
        if target is None or modifier is None or controller is None:
            for bundle in other_stage_handle_bundles:
                _hide_other_stage_bundle(bundle)
            return
        properties = controller.sdh_cage_deform
        enabled_types = _enabled_deform_types(properties)
        dedicated_ffd = str(getattr(properties, "cage_type", "")) == "FFD"
        native_ffd_edit = bool(getattr(
            properties, "ffd_native_edit_mode_active", False))
        if dedicated_ffd and native_ffd_edit:
            # Blender's native Lattice Edit Mode must be the only control
            # surface in the viewport. Hiding just the aggregate FFD entities
            # still leaves boundary/axis controls over the native points.
            for handle in (
                    *self.parameter_handles, *self.ffd_handles,
                    self.direction_handle,
                    self.top_handle, self.bottom_handle,
                    self.top_boundary_handle, self.bottom_boundary_handle,
                    *self.bend_trend_handles, *self.axis_handles):
                handle.hide = True
            for handle in self.ffd_handles:
                handle.ffd_entities = ()
                handle.picked_entity = None
            for bundle in other_stage_handle_bundles:
                _hide_other_stage_bundle(bundle)
            return
        ffd_entities = []
        if (
                "FFD" in enabled_types and ffd_handles_enabled() and
                dedicated_ffd and not native_ffd_edit
        ):
            for selection_mode in ffd_selection_modes(properties):
                ffd_entities.extend(
                    (anchor, selection_mode, orientation)
                    for anchor, orientation in ffd_selection_entities(
                        properties, selection_mode, ensure=False))
        elif (
                "FFD" in enabled_types and ffd_handles_enabled() and
                not native_ffd_edit
        ):
            ffd_entities = [
                (index, "POINT", "POINT")
                for index in range(len(FFD_CORNERS))]
        self._ensure_ffd_handle_count(len(ffd_entities))
        preferences = get_pref() if self.ffd_handles else None
        line_length_ratio = float(getattr(
            preferences, "ffd_line_handle_length", 0.60))
        line_width = float(getattr(preferences, "ffd_line_handle_width", 2.0))
        face_size_ratio = float(getattr(
            preferences, "ffd_face_handle_size", 0.35))
        for handle in self.ffd_handles:
            handle.ffd_line_length_ratio = min(max(line_length_ratio, 0.10), 1.0)
            handle.ffd_line_width = min(max(line_width, 1.0), 8.0)
            handle.ffd_face_size_ratio = min(max(face_size_ratio, 0.10), 1.0)
            handle.ffd_entities = tuple(ffd_entities)
            if getattr(handle, "picked_entity", None) not in handle.ffd_entities:
                handle.picked_entity = None
            if handle.ffd_entities and handle.picked_entity is None:
                handle._set_entity(handle.ffd_entities[0])
        bend_trend_mode = (
            "BEND" in enabled_types and properties.show_axis_gizmo)
        axis_switch_mode = (
            "BEND" not in enabled_types and bool(enabled_types) and
            properties.show_axis_gizmo)
        chooser_mode = bend_trend_mode or axis_switch_mode

        for handle in (
                *self.parameter_handles, *self.ffd_handles,
                self.direction_handle,
                self.top_handle, self.bottom_handle,
                self.top_boundary_handle, self.bottom_boundary_handle):
            _bind_gizmo_stage(handle, target, modifier, controller)

        # Classic axis-switch / bend-trend mode only shows the face arrows.
        for handle in self.parameter_handles:
            handle.hide = (
                chooser_mode or handle.DEFORM_TYPE not in enabled_types)
            if not handle.hide and handle.DEFORM_TYPE == "SHEAR":
                handle._set_tooltip_target(properties)
        for handle in self.ffd_handles:
            handle.hide = (
                chooser_mode or "FFD" not in enabled_types or
                not ffd_handles_enabled() or
                not ffd_entities)
            # The persistent editor performs the same hit tests while active.
            # Drawing remains enabled, but only that modal owns the click.
            handle.hide_select = bool(
                not handle.hide and dedicated_ffd and
                getattr(properties, "ffd_edit_mode_active", False))
            if not handle.hide:
                handle._set_tooltip_target(properties)
        self.direction_handle.hide = chooser_mode or (
            "BEND" not in enabled_types or
            not properties.show_direction_handle)
        self.top_handle.hide = chooser_mode or not properties.show_end_handles
        self.bottom_handle.hide = (
            chooser_mode or not properties.show_end_handles)
        for handle in (self.top_handle, self.bottom_handle):
            if not handle.hide:
                handle._set_tooltip_target(
                    properties, getattr(handle, "side", "TOP"))
        self.top_boundary_handle.hide = (
            chooser_mode or not properties.show_boundary_handles)
        self.bottom_boundary_handle.hide = (
            chooser_mode or not properties.show_boundary_handles)
        for handle in (
                self.top_boundary_handle, self.bottom_boundary_handle):
            if not handle.hide:
                handle._set_tooltip_target(
                    properties,
                    boundary_tooltip_key(
                        target, modifier, getattr(handle, "side", "TOP")),
                )

        # Refresh matrix/scale before draw so the first visible frame is correct.
        # Mark fresh so draw()/draw_select skip a duplicate rebuild this cycle.
        for gizmo in (
                *self.parameter_handles, *self.ffd_handles,
                self.direction_handle,
                self.top_handle, self.bottom_handle,
                self.top_boundary_handle, self.bottom_boundary_handle):
            if isinstance(gizmo, SDHCageFFDAggregateGizmo):
                continue
            if not gizmo.hide and hasattr(gizmo, "_update_matrix"):
                _invalidate_matrix_fresh(gizmo)
                gizmo._update_matrix(context)
                _mark_matrix_fresh(gizmo)

        for trend_handle in self.bend_trend_handles:
            visible = bend_trend_mode
            trend_handle.hide = not visible
            if not visible:
                continue
            _invalidate_matrix_fresh(trend_handle)
            trend_handle._update_matrix(context)
            _mark_matrix_fresh(trend_handle)

        for axis_handle in self.axis_handles:
            axis_handle.hide = not axis_switch_mode
            if not axis_handle.hide and hasattr(axis_handle, "_update_matrix"):
                _invalidate_matrix_fresh(axis_handle)
                axis_handle._update_matrix(context)
                _mark_matrix_fresh(axis_handle)

        if chooser_mode or not properties.show_other_cages:
            for bundle in other_stage_handle_bundles:
                _hide_other_stage_bundle(bundle)
            return

        visible_stages = []
        for stage_modifier in cage_modifiers(target):
            if len(visible_stages) >= _MAX_OTHER_STAGE_EDIT_BUNDLES:
                break
            if (
                    _same_rna_value(stage_modifier, modifier) or
                    not stage_modifier.show_viewport
            ):
                continue
            stage_controller = find_controller(target, stage_modifier)
            stage_properties = getattr(
                stage_controller, "sdh_cage_deform", None)
            if (
                    stage_controller is None or stage_properties is None or
                    not stage_properties.show_cage
            ):
                continue
            visible_stages.append((
                stage_modifier, stage_controller, stage_properties))

        while len(other_stage_handle_bundles) < len(visible_stages):
            other_stage_handle_bundles.append(
                _new_other_stage_edit_bundle())

        for bundle, (
                stage_modifier, stage_controller, stage_properties
        ) in zip(other_stage_handle_bundles, visible_stages):
            _ensure_other_stage_bundle(
                self.gizmos, bundle, stage_properties)
            _prepare_other_stage_bundle(
                bundle,
                context, target, stage_modifier, stage_controller)

        for bundle in other_stage_handle_bundles[len(visible_stages):]:
            _hide_other_stage_bundle(bundle)


class SDHCageStagePickerGizmoGroup(GizmoGroup):
    """Viewport picker for inactive cage stages.

    The picker is separate from the active edit-handle group so it remains
    available when the active cage preview is muted, while never competing
    with the active cage's bend/twist/end/boundary handles. An inactive stage
    that hides its own cage preview is not given an invisible hit area.
    """

    bl_idname = "SDH_GGT_cage_stage_picker"
    bl_label = "Select Cage Stage"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    _MAX_PICKERS = 32

    @classmethod
    def poll(cls, context):
        target, active_modifier, active_controller = resolve_context_deform(
            context, fallback=False)
        if target is None or active_modifier is None or active_controller is None:
            return False
        properties = getattr(active_controller, "sdh_cage_deform", None)
        if (
                properties is None or not properties.show_other_cages or
                bool(getattr(
                    properties, "ffd_native_edit_mode_active", False))
        ):
            return False
        for modifier in cage_modifiers(target):
            if modifier == active_modifier or not modifier.show_viewport:
                continue
            controller = find_controller(target, modifier)
            if controller is None:
                continue
            stage_properties = getattr(controller, "sdh_cage_deform", None)
            if stage_properties is None or not stage_properties.show_cage:
                continue
            return True
        return False

    def setup(self, _context):
        self.pickers = []

    def _ensure_picker_count(self, count):
        count = min(max(int(count), 0), self._MAX_PICKERS)
        while len(self.pickers) < count:
            picker = self.gizmos.new(SDHCageStagePickerGizmo.bl_idname)
            picker.hide = True
            operator = picker.target_set_operator(
                "sdh.select_cage_stage")
            picker.stage_operator = operator
            self.pickers.append(picker)

    def draw_prepare(self, context):
        target, active_modifier, active_controller = resolve_context_deform(
            context, fallback=False)
        if target is None or active_modifier is None or active_controller is None:
            for picker in self.pickers:
                picker.hide = True
            return
        active_properties = getattr(active_controller, "sdh_cage_deform", None)
        if (
                active_properties is None or
                not active_properties.show_other_cages or
                bool(getattr(
                    active_properties, "ffd_native_edit_mode_active", False))
        ):
            for picker in self.pickers:
                picker.hide = True
            return

        visible_stages = []
        for modifier in cage_modifiers(target):
            if len(visible_stages) >= self._MAX_PICKERS:
                break
            if modifier == active_modifier or not modifier.show_viewport:
                continue
            controller = find_controller(target, modifier)
            if controller is None:
                continue
            stage_properties = getattr(controller, "sdh_cage_deform", None)
            if stage_properties is None or not stage_properties.show_cage:
                continue
            visible_stages.append((modifier, controller))

        self._ensure_picker_count(len(visible_stages))
        for picker, (modifier, controller) in zip(
                self.pickers, visible_stages):
            picker.configure(target, modifier, controller)

        for picker in self.pickers[len(visible_stages):]:
            picker.hide = True
