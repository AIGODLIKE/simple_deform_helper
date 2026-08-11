"""Focused Blender 5+ smoke test for the native multi-point FFD cage."""
from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy
from mathutils import Matrix, Vector

SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))

entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")

mesh = bpy.data.meshes.new("SDH FFD Regression Mesh")
mesh.from_pydata(
    (
        (-1.0, -1.0, -1.0), (1.0, -1.0, -1.0),
        (1.0, 1.0, -1.0), (-1.0, 1.0, -1.0),
        (-1.0, -1.0, 1.0), (1.0, -1.0, 1.0),
        (1.0, 1.0, 1.0), (-1.0, 1.0, 1.0),
    ), (), ()
)
target = bpy.data.objects.new("SDH FFD Regression", mesh)
bpy.context.collection.objects.link(target)
bpy.context.view_layer.objects.active = target
target.select_set(True)

try:
    axis, space = deform.core.ffd_transform_axis_state(None, "LOCAL", 0)
    if (axis, space) != (0, "GLOBAL"):
        raise AssertionError("first FFD axis press did not use global space")
    axis, space = deform.core.ffd_transform_axis_state(axis, space, 0)
    if (axis, space) != (0, "LOCAL"):
        raise AssertionError("second FFD axis press did not use cage-local space")
    axis, space = deform.core.ffd_transform_axis_state(axis, space, 0)
    if (axis, space) != (0, "GLOBAL"):
        raise AssertionError("repeated FFD axis press did not toggle to global")
    axis, space = deform.core.ffd_transform_axis_state(axis, space, 2)
    if (axis, space) != (2, "GLOBAL"):
        raise AssertionError("changing FFD axis did not reset to global space")
    rotated = Matrix.Rotation(math.pi * 0.5, 4, "Z")
    global_x = deform.core.ffd_transform_axis_world(rotated, 0, "GLOBAL")
    local_x = deform.core.ffd_transform_axis_world(rotated, 0, "LOCAL")
    if (global_x - Vector((1.0, 0.0, 0.0))).length > 1.0e-6:
        raise AssertionError("FFD global X followed the cage rotation")
    if (local_x - Vector((0.0, 1.0, 0.0))).length > 1.0e-6:
        raise AssertionError("FFD local X ignored the cage rotation")

    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, target)
    properties = controller.sdh_cage_deform
    properties.cage_type = "FFD"
    maximum = (
        deform.core.FFD_MAX_RESOLUTION_U,
        deform.core.FFD_MAX_RESOLUTION_V,
        deform.core.FFD_MAX_RESOLUTION_W,
    )
    if maximum != (6, 6, 6):
        raise AssertionError(f"FFD maximum resolution is {maximum}, not 6x6x6")
    oversized = SimpleNamespace(
        ffd_resolution_u=99,
        ffd_resolution_v=99,
        ffd_resolution_w=99,
    )
    if deform.core.ffd_resolution(oversized) != (6, 6, 6):
        raise AssertionError("FFD runtime resolution did not clamp to 6x6x6")
    for property_name in (
            "ffd_resolution_u", "ffd_resolution_v", "ffd_resolution_w"):
        if properties.bl_rna.properties[property_name].hard_max != 6:
            raise AssertionError(f"{property_name} UI maximum is not 6")
    created_gizmo_types = []

    class FakeGizmos:
        @staticmethod
        def new(gizmo_type):
            created_gizmo_types.append(gizmo_type)
            return SimpleNamespace()

    aggregate_group = SimpleNamespace(ffd_handles=(), gizmos=FakeGizmos())
    deform.gizmos.SDHCageDeformGizmoGroup._ensure_ffd_handle_count(
        aggregate_group, deform.core.FFD_MAX_SELECTION_HANDLE_COUNT)
    if (
            len(aggregate_group.ffd_handles) != 1 or
            created_gizmo_types != [
                deform.gizmos.SDHCageFFDAggregateGizmo.bl_idname]
    ):
        raise AssertionError(
            "maximum FFD topology allocated more than one active-grid Gizmo")
    if deform.core.ffd_resolution(properties) != (2, 2, 2):
        raise AssertionError("dedicated FFD did not default to eight points")
    if len(properties.ffd_points) != 8:
        raise AssertionError("default FFD point collection is not 2x2x2")
    initial_lattice = deform.core.ffd_lattice_object(target, modifier)
    if initial_lattice is None:
        raise AssertionError("default FFD did not create its native lattice")
    if any(abs(float(getattr(point, "influence", -1.0)) - 1.0) > 1.0e-6
           for point in properties.ffd_points):
        raise AssertionError("new FFD points did not default to full influence")
    deform.core.ffd_set_selection(properties, (0, 1), active=0)
    properties.ffd_points[0].edit_influence = 0.5
    if any(abs(float(properties.ffd_points[index].influence) - 0.5) > 1.0e-6
           for index in (0, 1)):
        raise AssertionError("multi-selected FFD influence edit did not propagate")
    properties.ffd_points[1].influence = 1.0
    properties.ffd_points[0].offset = (0.8, 0.2, -0.4)
    properties.ffd_points[0].influence = 0.5
    deform.sync_controller(controller, pull_transform=False)
    weighted_lattice = deform.core.ffd_lattice_object(target, modifier)
    weighted_point = weighted_lattice.data.points[0]
    runtime_scale = Vector(tuple(
        max(abs(float(value)), 1.0e-8)
        for value in weighted_lattice.matrix_world.to_scale()))
    observed = Vector(weighted_point.co_deform) - Vector(weighted_point.co)
    expected = Vector((0.4, 0.1, -0.2))
    expected = Vector(tuple(
        component / scale
        for component, scale in zip(expected, runtime_scale)))
    if (observed - expected).length > 1.0e-5:
        raise AssertionError(
            f"FFD point influence was not applied: {observed} != {expected}")
    properties.ffd_points[0].influence = 0.0
    deform.sync_controller(controller, pull_transform=False)
    zero_point = deform.core.ffd_lattice_object(target, modifier).data.points[0]
    if (Vector(zero_point.co_deform) - Vector(zero_point.co)).length > 1.0e-6:
        raise AssertionError("zero FFD influence still deformed the lattice")
    properties.ffd_points[0].influence = 1.0
    properties.ffd_points[0].offset = (0.0, 0.0, 0.0)
    deform.sync_controller(controller, pull_transform=False)
    initial_topology_token = initial_lattice.get(
        deform.core.FFD_LATTICE_TOPOLOGY_TOKEN)
    if not initial_topology_token:
        raise AssertionError("FFD lattice did not record a topology token")
    properties.ffd_resolution_u = 4
    properties.ffd_resolution_v = 5
    properties.ffd_resolution_w = 3
    properties.ffd_use_outside = True
    deform.sync_controller(controller, pull_transform=False)
    lattice = deform.core.ffd_lattice_object(target, modifier)
    if lattice is None:
        raise AssertionError("dedicated FFD did not create a lattice object")
    lattice_name = lattice.name
    if len(lattice.data.points) != 4 * 5 * 3:
        raise AssertionError("FFD lattice point count does not match resolution")
    if lattice.get(deform.core.FFD_LATTICE_TOPOLOGY_TOKEN) == initial_topology_token:
        raise AssertionError(
            "FFD resolution reused its native lattice topology")
    if not lattice.data.use_outside:
        raise AssertionError("hollow FFD did not enable native outside-only mode")
    visible = set(deform.core.ffd_visible_indices(properties))
    if len(visible) != 54:
        raise AssertionError(f"hollow FFD exposed {len(visible)} points instead of 54")
    bpy.context.view_layer.objects.active = target
    target.modifiers.active = modifier
    if bpy.ops.sdh.select_ffd_points(action="ALL") != {"FINISHED"}:
        raise AssertionError("hollow FFD select-all failed")
    selected = {
        index for index, point in enumerate(properties.ffd_points)
        if point.selected
    }
    if selected != visible:
        raise AssertionError("hollow FFD selected hidden interior points")
    properties.ffd_selection_mode = "LINE"
    line = set(deform.core.ffd_selection_indices(properties, 0))
    expected_line = {
        deform.core.ffd_point_index(0, v, 0, (4, 5, 3))
        for v in (0, 1)
    }
    if line != expected_line:
        raise AssertionError("FFD line mode did not select one adjacent segment")
    for axis, expected in {
            "U": {
                deform.core.ffd_point_index(u, 0, 0, (4, 5, 3))
                for u in (0, 1)
            },
            "W": {
                deform.core.ffd_point_index(0, 0, w, (4, 5, 3))
                for w in (0, 1)
            },
    }.items():
        if set(deform.core.ffd_selection_indices(
                properties, 0, "LINE", axis=axis)) != expected:
            raise AssertionError(f"FFD {axis} line selection is incorrect")
    properties.ffd_selection_mode = "FACE"
    face = set(deform.core.ffd_selection_indices(properties, 0))
    expected_face = {
        deform.core.ffd_point_index(u, 0, w, (4, 5, 3))
        for w in (0, 1) for u in (0, 1)
    }
    if face != expected_face:
        raise AssertionError("FFD face mode did not select the UW grid face")
    for plane, expected in {
            "UV": {
                deform.core.ffd_point_index(u, v, 0, (4, 5, 3))
                for v in (0, 1) for u in (0, 1)
            },
            "VW": {
                deform.core.ffd_point_index(0, v, w, (4, 5, 3))
                for w in (0, 1) for v in (0, 1)
            },
    }.items():
        if set(deform.core.ffd_selection_indices(
                properties, 0, "FACE", axis=plane)) != expected:
            raise AssertionError(f"FFD {plane} face selection is incorrect")
    properties.ffd_selection_mode = "POINT"
    properties.ffd_use_outside = False
    properties.ffd_selection_modes = {"POINT", "LINE", "FACE"}
    if deform.core.ffd_selection_modes(properties) != ("POINT", "LINE", "FACE"):
        raise AssertionError("FFD multi-selection modes did not retain all types")
    # Mixed controller visibility must not make a point box expand every
    # lattice point. Explicit POINT mode remains a one-point selection, while
    # LINE/FACE entities may still expand when their geometry intersects the
    # box.
    point_only = set(deform.core.ffd_expand_selection(
        properties, (0,), mode="POINT"))
    if point_only != {0}:
        raise AssertionError("FFD point selection expanded beyond its anchor")
    mixed_probe = set(deform.core.ffd_expand_selection(properties, (0,)))
    if mixed_probe != {0}:
        raise AssertionError(
            "mixed FFD point/line/face box selection ignored point priority")

    # Screen-space box selection follows the visible controller geometry. In
    # mixed mode it uses click-compatible POINT > LINE > FACE priority, falling
    # through only when the higher-priority controller type has no hit.
    resolution = deform.core.ffd_resolution(properties)

    def projected_point(index):
        u, v, w = deform.core.ffd_point_coordinates(index, resolution)
        return Vector((u * 100.0 + w * 25.0, v * 100.0 + w * 15.0))

    point_box = (-3.0, 3.0, -3.0, 3.0)
    line_box = (48.0, 52.0, -2.0, 2.0)
    face_box = (61.0, 64.0, 6.0, 9.0)
    boxed, active, boxed_mode = deform.core.ffd_box_selection_indices(
        properties, projected_point, point_box)
    if set(boxed) != {0} or active != 0 or boxed_mode != "POINT":
        raise AssertionError("mixed FFD point box did not select one point")
    expected_line = set(deform.core.ffd_selection_indices(
        properties, 0, "LINE", axis="U"))
    boxed, active, boxed_mode = deform.core.ffd_box_selection_indices(
        properties, projected_point, line_box)
    if set(boxed) != expected_line or active != 0 or boxed_mode != "LINE":
        raise AssertionError("FFD line box did not hit the visible line handle")
    expected_face = set(deform.core.ffd_selection_indices(
        properties, 0, "FACE", axis="UW"))
    boxed, active, boxed_mode = deform.core.ffd_box_selection_indices(
        properties, projected_point, face_box)
    if set(boxed) != expected_face or active != 0 or boxed_mode != "FACE":
        raise AssertionError("FFD face box did not hit the visible face handle")

    properties.ffd_selection_modes = {"LINE"}
    boxed, _active, boxed_mode = deform.core.ffd_box_selection_indices(
        properties, projected_point, line_box)
    if set(boxed) != expected_line or boxed_mode != "LINE":
        raise AssertionError("single-mode FFD line box selection failed")
    properties.ffd_selection_modes = {"FACE"}
    boxed, _active, boxed_mode = deform.core.ffd_box_selection_indices(
        properties, projected_point, face_box)
    if set(boxed) != expected_face or boxed_mode != "FACE":
        raise AssertionError("single-mode FFD face box selection failed")

    first_selection = deform.core.ffd_box_selection_update(
        (), expected_line, "SET")
    refreshed_selection = deform.core.ffd_box_selection_update(
        first_selection, expected_face, "SET")
    if refreshed_selection != expected_face:
        raise AssertionError("a repeated FFD box did not refresh SET selection")
    added_selection = deform.core.ffd_box_selection_update(
        expected_line, expected_face, "ADD")
    if added_selection != expected_line | expected_face:
        raise AssertionError("Shift FFD box selection did not add")
    subtracted_selection = deform.core.ffd_box_selection_update(
        added_selection, expected_face, "SUBTRACT")
    if subtracted_selection != expected_line - expected_face:
        raise AssertionError("Ctrl FFD box selection did not subtract")

    # FFD symmetry mirrors point membership through the chosen cage-local
    # center plane. Lines and faces use the same point sets, so every picking
    # path and transform observes one consistent symmetry contract.
    properties.ffd_symmetry_enabled = True
    symmetry_probe = deform.core.ffd_point_index(0, 1, 2, resolution)
    expected_mirrors = {
        "U": deform.core.ffd_point_index(3, 1, 2, resolution),
        "V": deform.core.ffd_point_index(0, 3, 2, resolution),
        "W": deform.core.ffd_point_index(0, 1, 0, resolution),
    }
    for symmetry_axis, expected_mirror in expected_mirrors.items():
        properties.ffd_symmetry_axis = symmetry_axis
        if deform.core.ffd_mirror_point_index(
                properties, symmetry_probe) != expected_mirror:
            raise AssertionError(
                f"FFD {symmetry_axis} symmetry mapped the wrong point")
        deform.core.ffd_set_selection(
            properties, {symmetry_probe}, active=symmetry_probe)
        if set(deform.core.ffd_selected_indices(properties)) != {
                symmetry_probe, expected_mirror}:
            raise AssertionError(
                f"FFD {symmetry_axis} point selection lost its mirror")

    properties.ffd_symmetry_axis = "V"
    center_point = deform.core.ffd_point_index(1, 2, 1, resolution)
    if deform.core.ffd_mirror_point_index(
            properties, center_point) != center_point:
        raise AssertionError("odd-resolution FFD center layer did not mirror to itself")

    properties.ffd_symmetry_axis = "U"
    line_anchor = deform.core.ffd_point_index(0, 0, 0, resolution)
    line_group = set(deform.core.ffd_selection_indices(
        properties, line_anchor, "LINE", axis="V"))
    mirrored_line = {
        deform.core.ffd_mirror_point_index(properties, index)
        for index in line_group
    }
    deform.core.ffd_set_selection(properties, line_group, active=line_anchor)
    if set(deform.core.ffd_selected_indices(properties)) != (
            line_group | mirrored_line):
        raise AssertionError("FFD line selection did not include its mirror")

    face_anchor = deform.core.ffd_point_index(0, 0, 0, resolution)
    face_group = set(deform.core.ffd_selection_indices(
        properties, face_anchor, "FACE", axis="VW"))
    mirrored_face = {
        deform.core.ffd_mirror_point_index(properties, index)
        for index in face_group
    }
    deform.core.ffd_set_selection(properties, face_group, active=face_anchor)
    if set(deform.core.ffd_selected_indices(properties)) != (
            face_group | mirrored_face):
        raise AssertionError("FFD face selection did not include its mirror")
    toggled, collapse_on_click = deform.core.ffd_pointer_selection_update(
        face_group | mirrored_face,
        deform.core.ffd_symmetry_expand_indices(properties, face_group),
        extend=True,
    )
    if toggled or collapse_on_click:
        raise AssertionError("Shift FFD selection did not remove a mirror group")

    properties.ffd_use_outside = True
    hidden_point = deform.core.ffd_point_index(1, 1, 1, resolution)
    if deform.core.ffd_symmetry_expand_indices(
            properties, {hidden_point}):
        raise AssertionError("hollow FFD symmetry exposed hidden interior points")
    properties.ffd_use_outside = False

    left = deform.core.ffd_point_index(0, 0, 0, resolution)
    right = deform.core.ffd_point_index(3, 0, 0, resolution)
    initial_points = {
        index: deform.core.SDH_OT_box_select_ffd_points._point_source_local(
            properties, index)
        for index in (left, right)
    }
    drag_delta = Vector((0.25, 0.40, -0.10))
    candidate_values = {
        index: point + drag_delta
        for index, point in initial_points.items()
    }
    mirrored_values = deform.core.ffd_symmetry_transform_values(
        properties, initial_points, candidate_values, driver_index=left)
    expected_right = initial_points[right] + Vector((-0.25, 0.40, -0.10))
    if (
            Vector(mirrored_values[left]) - candidate_values[left]
    ).length > 1.0e-6 or (
            Vector(mirrored_values[right]) - expected_right
    ).length > 1.0e-6:
        raise AssertionError("FFD symmetry did not mirror the transform delta")
    mirrored_values = deform.core.ffd_symmetry_transform_values(
        properties, initial_points, candidate_values, driver_index=right)
    expected_left = initial_points[left] + Vector((-0.25, 0.40, -0.10))
    if (
            Vector(mirrored_values[right]) - candidate_values[right]
    ).length > 1.0e-6 or (
            Vector(mirrored_values[left]) - expected_left
    ).length > 1.0e-6:
        raise AssertionError("FFD symmetry ignored the active transform side")

    properties.ffd_symmetry_enabled = False
    properties.ffd_symmetry_axis = "U"

    # Pressing an already selected FFD entity must keep the whole selection
    # available for direct dragging. A stationary release can still collapse
    # to the clicked entity, preserving normal single-click behavior.
    pressed, collapse_on_click = deform.core.ffd_pointer_selection_update(
        {0, 1, 2}, {1})
    if pressed != {0, 1, 2} or not collapse_on_click:
        raise AssertionError("FFD pointer press discarded a multi-selection")
    pressed, collapse_on_click = deform.core.ffd_pointer_selection_update(
        {0, 1, 2}, {3})
    if pressed != {3} or collapse_on_click:
        raise AssertionError("FFD pointer press did not replace an unselected entity")
    pressed, collapse_on_click = deform.core.ffd_pointer_selection_update(
        {0, 1, 2}, {1}, extend=True)
    if pressed != {0, 2} or collapse_on_click:
        raise AssertionError("Shift FFD pointer selection did not toggle its group")

    required_handoff_properties = {
        "start_drag", "start_box_select", "arm_box_select", "start_anchor", "start_selection_mode",
        "start_selection_axis", "start_mouse_region_x",
        "start_mouse_region_y", "start_extend",
    }
    registered_handoff_properties = {
        item.identifier
        for item in bpy.ops.sdh.box_select_ffd_points.get_rna_type().properties
    }
    if not required_handoff_properties.issubset(registered_handoff_properties):
        missing = sorted(
            required_handoff_properties - registered_handoff_properties)
        raise AssertionError(
            "FFD Gizmo-to-modal drag handoff is not registered: "
            f"missing={missing}, registered={sorted(registered_handoff_properties)}, "
            f"annotations={sorted(deform.core.SDH_OT_box_select_ffd_points.__annotations__)}")

    b_picker_entries = [
        item for item in deform.core.SDH_WST_ffd_edit.bl_keymap
        if item[0] == "sdh.box_select_ffd_points" and
        item[1].get("type") == "B" and item[1].get("value") == "PRESS"
    ]
    if len(b_picker_entries) != 1:
        raise AssertionError(
            f"expected one scoped FFD B box-picker binding, got {b_picker_entries!r}")
    if (
            not any(
                name == "arm_box_select" and bool(value)
                for name, value in b_picker_entries[0][2]["properties"])
    ):
        raise AssertionError(
            "FFD B box-picker is not scoped to the FFD Workspace Tool")

    deform.core.ffd_set_selection(properties, {0, 1}, active=0)
    captured_pointer_drag = {}

    def capture_pointer_drag(_context, _event, mode, *, initial_mouse=None):
        captured_pointer_drag["mode"] = mode
        captured_pointer_drag["mouse"] = tuple(initial_mouse)
        captured_pointer_drag["selection"] = set(
            deform.core.ffd_selected_indices(properties))
        return True

    pointer_stub = SimpleNamespace(
        _begin_transform=capture_pointer_drag,
        _set_header=lambda _context: None,
    )
    if not deform.core.SDH_OT_box_select_ffd_points._begin_pointer_transform(
            pointer_stub,
            bpy.context,
            properties,
            anchor=0,
            selection_mode="POINT",
            selection_axis="POINT",
            extend=False,
            initial_mouse=(123, 456),
    ):
        raise AssertionError("FFD pointer drag handoff did not start")
    if (
            captured_pointer_drag != {
                "mode": "MOVE",
                "mouse": (123, 456),
                "selection": {0, 1},
            } or
            tuple(pointer_stub._pointer_click_group) != (0,)
    ):
        raise AssertionError("FFD pointer drag handoff lost selection or mouse origin")
    deform.core.SDH_OT_box_select_ffd_points._finish_transform(
        pointer_stub, bpy.context, properties)
    if set(deform.core.ffd_selected_indices(properties)) != {0}:
        raise AssertionError("stationary FFD pointer click did not collapse selection")
    deform.core.ffd_set_selection(properties, {0, 1}, active=0)
    pointer_stub._pointer_click_group = (0,)
    pointer_stub._pointer_click_active = 0
    pointer_stub._pointer_dragged = True
    deform.core.SDH_OT_box_select_ffd_points._finish_transform(
        pointer_stub, bpy.context, properties)
    if set(deform.core.ffd_selected_indices(properties)) != {0, 1}:
        raise AssertionError("completed FFD pointer drag discarded multi-selection")

    # Looking directly through a 2x2x2 FFD overlays the front and back point,
    # line, and face controllers. Box selection is depth-penetrating: it keeps
    # every projected controller in the rectangle while the front controller
    # remains the active anchor. Direct clicks below retain front-most picking.
    overlap_properties = SimpleNamespace(
        ffd_resolution_u=2,
        ffd_resolution_v=2,
        ffd_resolution_w=2,
        ffd_use_outside=False,
        ffd_selection_mode="POINT",
        ffd_selection_modes_initialized=True,
        ffd_selection_modes={"POINT"},
    )
    overlap_resolution = (2, 2, 2)

    def overlap_projection(index):
        u, v, w = deform.core.ffd_point_coordinates(
            index, overlap_resolution)
        # The view looks along V. V=1 is the front layer (smaller depth).
        return Vector((u * 100.0, w * 100.0, 10.0 - v))

    boxed, active, boxed_mode = deform.core.ffd_box_selection_indices(
        overlap_properties, overlap_projection, (-2.0, 2.0, -2.0, 2.0))
    if set(boxed) != {0, 2} or active != 2 or boxed_mode != "POINT":
        raise AssertionError("overlapping FFD point box did not penetrate depth")
    picked = deform.core.ffd_screen_selection_entity(
        overlap_properties, overlap_projection, (0.0, 0.0))
    if picked != (2, "POINT", "POINT"):
        raise AssertionError("overlapping FFD point click did not keep the front point")

    def spread_projection(index):
        u, v, w = deform.core.ffd_point_coordinates(
            index, overlap_resolution)
        return Vector((u * 100.0, v * 100.0 + w * 300.0, 1.0))

    boxed, _active, boxed_mode = deform.core.ffd_box_selection_indices(
        overlap_properties, spread_projection, (-2.0, 102.0, -2.0, 102.0))
    if set(boxed) != {0, 1, 2, 3} or boxed_mode != "POINT":
        raise AssertionError("FFD point box did not retain distinct multi-selection")

    overlap_properties.ffd_selection_modes = {"LINE"}
    boxed, active, boxed_mode = deform.core.ffd_box_selection_indices(
        overlap_properties, overlap_projection, (48.0, 52.0, -2.0, 2.0))
    if set(boxed) != {0, 1, 2, 3} or active != 2 or boxed_mode != "LINE":
        raise AssertionError("overlapping FFD line box did not penetrate depth")
    picked = deform.core.ffd_screen_selection_entity(
        overlap_properties, overlap_projection, (50.0, 0.0))
    if picked != (2, "LINE", "U"):
        raise AssertionError("overlapping FFD line click did not keep the front line")

    overlap_properties.ffd_selection_modes = {"FACE"}
    expected_front_face = set(range(8))
    boxed, active, boxed_mode = deform.core.ffd_box_selection_indices(
        overlap_properties, overlap_projection, (48.0, 52.0, 48.0, 52.0))
    if set(boxed) != expected_front_face or active != 2 or boxed_mode != "FACE":
        raise AssertionError("overlapping FFD face box did not penetrate depth")
    picked = deform.core.ffd_screen_selection_entity(
        overlap_properties, overlap_projection, (50.0, 50.0))
    if picked != (2, "FACE", "UW"):
        raise AssertionError("overlapping FFD face click did not keep the front face")

    overlap_properties.ffd_selection_modes = {"POINT", "LINE", "FACE"}
    if deform.core.ffd_selection_modes(overlap_properties) != (
            "POINT", "LINE", "FACE"):
        raise AssertionError("FFD controller modes no longer coexist")
    picked = deform.core.ffd_screen_selection_entity(
        overlap_properties, overlap_projection, (0.0, 0.0))
    if picked != (2, "POINT", "POINT"):
        raise AssertionError("mixed FFD click did not retain Point priority")

    # A finished drag clears the manual blank-click history, so a second box
    # starting at the same position cannot be mistaken for an exit double-click.
    double_click, last_time, last_position = (
        deform.core._ffd_blank_box_release_state(
            -1.0, (0.0, 0.0), (10.0, 10.0), (40.0, 40.0), 1.0))
    if double_click or last_time >= 0.0:
        raise AssertionError("FFD drag incorrectly armed blank double-click exit")
    double_click, last_time, last_position = (
        deform.core._ffd_blank_box_release_state(
            last_time, last_position,
            (10.0, 10.0), (45.0, 45.0), 1.1))
    if double_click or last_time >= 0.0:
        raise AssertionError("repeated FFD drag was treated as a double-click")
    double_click, last_time, last_position = (
        deform.core._ffd_blank_box_release_state(
            last_time, last_position,
            (10.0, 10.0), (10.0, 10.0), 2.0))
    if double_click or last_time != 2.0:
        raise AssertionError("first blank FFD click was not recorded")
    double_click, _last_time, _last_position = (
        deform.core._ffd_blank_box_release_state(
            last_time, last_position,
            (11.0, 11.0), (11.0, 11.0), 2.2))
    if not double_click:
        raise AssertionError("blank FFD double-click no longer exits")

    properties.ffd_selection_modes = {"POINT", "LINE", "FACE"}
    if bpy.ops.sdh.set_ffd_selection_mode(mode="LINE") != {"FINISHED"}:
        raise AssertionError("FFD mode click operator failed")
    if set(properties.ffd_selection_modes) != {"LINE"}:
        raise AssertionError("normal FFD mode click did not replace selection")
    if bpy.ops.sdh.set_ffd_selection_mode(
            mode="FACE", extend=True) != {"FINISHED"}:
        raise AssertionError("Shift FFD mode click operator failed")
    if set(properties.ffd_selection_modes) != {"LINE", "FACE"}:
        raise AssertionError("Shift FFD mode click did not add selection")
    if bpy.ops.sdh.set_ffd_selection_mode(
            mode="LINE", extend=True) != {"FINISHED"}:
        raise AssertionError("Shift FFD mode toggle operator failed")
    if set(properties.ffd_selection_modes) != {"FACE"}:
        raise AssertionError("Shift FFD mode click did not remove selection")
    if bpy.ops.sdh.set_ffd_selection_mode(
            mode="FACE", extend=True) != {"FINISHED"}:
        raise AssertionError("last FFD mode toggle operator failed")
    if set(properties.ffd_selection_modes) != {"FACE"}:
        raise AssertionError("FFD mode toggle allowed an empty selection")
    properties.ffd_selection_modes = {"POINT"}
    line_entities = deform.core.ffd_selection_entities(properties, "LINE")
    expected_line_entity_count = (
        (resolution[0] - 1) * resolution[1] * resolution[2] +
        resolution[0] * (resolution[1] - 1) * resolution[2] +
        resolution[0] * resolution[1] * (resolution[2] - 1)
    )
    if len(line_entities) != expected_line_entity_count:
        raise AssertionError(
            "FFD line mode did not expose every adjacent U/V/W segment")
    if len(set(line_entities)) != len(line_entities):
        raise AssertionError("FFD line mode exposed duplicate segment entities")
    axis_dimensions = {"U": 0, "V": 1, "W": 2}
    for anchor, orientation in line_entities:
        group = tuple(deform.core.ffd_selection_indices(
            properties, anchor, "LINE", axis=orientation))
        if len(group) != 2:
            raise AssertionError("an FFD line controller spans more than one segment")
        coordinates = tuple(
            deform.core.ffd_point_coordinates(index, resolution)
            for index in group)
        delta = tuple(abs(first - second) for first, second in zip(*coordinates))
        expected_delta = tuple(
            1 if dimension == axis_dimensions[orientation] else 0
            for dimension in range(3))
        if delta != expected_delta:
            raise AssertionError("an FFD line controller is not on adjacent points")
    u_edge_anchors = {
        anchor for anchor, orientation in line_entities
        if orientation == "U" and
        deform.core.ffd_point_coordinates(anchor, resolution)[1:] == (0, 0)
    }
    expected_u_edge_anchors = {
        deform.core.ffd_point_index(u, 0, 0, resolution)
        for u in range(resolution[0] - 1)
    }
    if u_edge_anchors != expected_u_edge_anchors:
        raise AssertionError("a subdivided FFD edge was collapsed to one controller")
    face_entities = deform.core.ffd_selection_entities(properties, "FACE")
    if len(face_entities) != 98:
        raise AssertionError("FFD face mode did not expose every UV/UW/VW grid face")
    properties.ffd_selection_modes = set()
    if set(properties.ffd_selection_modes) != {"POINT"}:
        raise AssertionError("FFD mode toggles allowed an empty selection")
    properties.ffd_selection_modes = {"POINT"}
    properties.ffd_use_outside = True
    hollow_visible = set(deform.core.ffd_visible_indices(properties))
    for mode, expected_size in (("LINE", 2), ("FACE", 4)):
        for anchor, orientation in deform.core.ffd_selection_entities(
                properties, mode):
            group = tuple(deform.core.ffd_selection_indices(
                properties, anchor, mode, axis=orientation))
            if (len(group) != expected_size or
                    not set(group).issubset(hollow_visible)):
                raise AssertionError(
                    f"hollow FFD exposed a partial {mode.lower()} controller")
    gizmos = importlib.import_module(f"{PACKAGE}.cage_deform.gizmos")
    _vertices, edges = gizmos.ffd_wire_geometry(properties)
    if any(left not in visible or right not in visible for left, right in edges):
        raise AssertionError("hollow FFD wire contains an interior edge")
    lattice_modifier = next(
        item for item in target.modifiers
        if item.type == "LATTICE" and item.object == lattice
    )
    stage_index = tuple(target.modifiers).index(modifier)
    if tuple(target.modifiers).index(lattice_modifier) != stage_index + 1:
        raise AssertionError("FFD companion is not adjacent to its owner stage")
    evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    before_mesh = evaluated.to_mesh()
    try:
        before = tuple(vertex.co.copy() for vertex in before_mesh.vertices)
    finally:
        evaluated.to_mesh_clear()
    properties.ffd_points[0].offset = (0.35, 0.0, 0.0)
    deform.sync_controller(controller, pull_transform=False)
    bpy.context.view_layer.update()
    evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    result = evaluated.to_mesh()
    try:
        after = tuple(vertex.co.copy() for vertex in result.vertices)
    finally:
        evaluated.to_mesh_clear()
    if not any((a - b).length > 1.0e-5 for a, b in zip(after, before)):
        raise AssertionError("FFD point offset did not affect evaluated geometry")

    properties.stage_enabled = False
    if lattice_modifier.show_viewport or lattice_modifier.show_render:
        raise AssertionError("disabled FFD stage left its companion enabled")
    properties.stage_enabled = True
    deform.core.set_deform_layer_muted(properties, "FFD", True, bpy.context)
    if lattice_modifier.show_viewport:
        raise AssertionError("muted FFD layer left its companion enabled")
    deform.core.set_deform_layer_muted(properties, "FFD", False, bpy.context)
    if not lattice_modifier.show_viewport:
        raise AssertionError("unmuted FFD layer did not restore its companion")

    original_frame = bpy.context.scene.frame_current
    addon_preferences = importlib.import_module(
        f"{PACKAGE}.utils").get_pref()
    original_keyframe_scope = getattr(
        addon_preferences, "ffd_keyframe_scope", "ALL_VISIBLE")
    deform.core.ffd_set_selection(properties, (0,), active=0)
    if getattr(addon_preferences, "ffd_keyframe_scope", "ALL_VISIBLE") != "ALL_VISIBLE":
        raise AssertionError("FFD keyframe scope is not all-visible by default")
    if set(deform.core.ffd_keyframe_indices(properties)) != visible:
        raise AssertionError("default FFD keyframe scope did not include all visible points")
    animation_paths = set(deform.core._cage_animation_paths(controller))
    if not all(
            f"sdh_cage_deform.ffd_points[{index}].offset" in animation_paths and
            f"sdh_cage_deform.ffd_points[{index}].influence" in animation_paths
            for index in visible
    ):
        raise AssertionError(
            "cage keyframe button did not include all visible FFD point data")
    addon_preferences.ffd_keyframe_scope = "SELECTED"
    if tuple(deform.core.ffd_keyframe_indices(properties)) != (0,):
        raise AssertionError("selected-only FFD keyframe preference was ignored")
    selected_paths = set(deform.core._cage_animation_paths(controller))
    if not {
            "sdh_cage_deform.ffd_points[0].offset",
            "sdh_cage_deform.ffd_points[0].influence",
    }.issubset(selected_paths) or any(
            f"sdh_cage_deform.ffd_points[{index}].offset" in selected_paths or
            f"sdh_cage_deform.ffd_points[{index}].influence" in selected_paths
            for index in visible if index != 0
    ):
        raise AssertionError("cage keyframe button ignored selected-only FFD preference")
    addon_preferences.ffd_keyframe_scope = "ALL_VISIBLE"
    bpy.context.scene.frame_set(1)
    properties.ffd_points[0].offset = (0.0, 0.0, 0.0)
    properties.ffd_points[0].influence = 0.25
    keyed = deform.core._keyframe_ffd_points(controller)
    bpy.context.scene.frame_set(10)
    properties.ffd_points[0].offset = (0.5, 0.0, 0.0)
    properties.ffd_points[0].influence = 0.75
    keyed += deform.core._keyframe_ffd_points(controller)
    animated_paths = deform.core._animation_paths(controller)
    if keyed <= 0 or not {
            "sdh_cage_deform.ffd_points[0].offset",
            "sdh_cage_deform.ffd_points[0].influence",
    }.issubset(animated_paths):
        raise AssertionError("dedicated FFD point animation was not keyed")
    bpy.context.scene.frame_set(1)
    deform.sync_controller(controller, pull_transform=False, sync_mode="timer")
    frame_one_x = lattice.data.points[0].co_deform.x
    bpy.context.scene.frame_set(10)
    deform.sync_controller(controller, pull_transform=False, sync_mode="timer")
    frame_ten_x = lattice.data.points[0].co_deform.x
    if frame_ten_x - frame_one_x <= 1.0e-4:
        raise AssertionError("animated FFD point did not update the native lattice")
    controller.animation_data_clear()
    bpy.context.scene.frame_set(original_frame)
    if addon_preferences is not None:
        addon_preferences.ffd_keyframe_scope = original_keyframe_scope
    properties.ffd_points[0].offset = (0.35, 0.0, 0.0)
    preserved_influence = float(properties.ffd_points[0].influence)
    deform.sync_controller(controller, pull_transform=False)
    if not deform.core.reset_ffd_offsets(controller, bpy.context):
        raise AssertionError("dedicated FFD reset helper failed")
    if Vector(properties.ffd_points[0].offset).length > 1.0e-6:
        raise AssertionError("dedicated FFD reset left a control-point offset")
    if abs(float(properties.ffd_points[0].influence) - preserved_influence) > 1.0e-6:
        raise AssertionError("dedicated FFD reset discarded point influence")
    if (Vector(lattice.data.points[0].co_deform) -
            Vector(lattice.data.points[0].co)).length > 1.0e-6:
        raise AssertionError("dedicated FFD reset did not refresh the native lattice")
    properties.ffd_points[0].offset = (0.35, 0.0, 0.0)
    deform.sync_controller(controller, pull_transform=False)

    # FFD animation is stored on the controller. Entering point-edit mode
    # must therefore keep the controller selected for Timeline keys while the
    # target stays active for the N-panel and cage GizmoGroups.
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    if not deform.core._activate_ffd_edit_selection(
            bpy.context, target, controller):
        raise AssertionError("FFD edit selection helper failed")
    if not target.select_get() or not controller.select_get():
        raise AssertionError("FFD edit mode did not select target and controller")
    if bpy.context.view_layer.objects.active != target:
        raise AssertionError("FFD edit mode did not keep the target active")
    deform.core._activate(bpy.context, target)
    if not target.select_get() or controller.select_get():
        raise AssertionError("FFD edit selection did not restore target selection")
    if bpy.context.view_layer.objects.active != target:
        raise AssertionError("FFD edit selection did not restore target activity")
    pre_edit_cleanup_stub = SimpleNamespace(
        _restore_pre_edit_selection=True,
        _pre_edit_selected_names=(target.name,),
        _pre_edit_active_name=target.name,
    )
    if not deform.core.SDH_OT_box_select_ffd_points._restore_pre_edit_object_selection(
            pre_edit_cleanup_stub, bpy.context):
        raise AssertionError("pre-edit FFD selection cleanup did not run")
    if pre_edit_cleanup_stub._restore_pre_edit_selection:
        raise AssertionError("pre-edit FFD selection cleanup did not clear its flag")
    if not target.select_get() or controller.select_get():
        raise AssertionError("pre-edit FFD selection cleanup restored the wrong objects")
    if bpy.context.view_layer.objects.active != target:
        raise AssertionError("pre-edit FFD selection cleanup restored the wrong active object")

    class PreEditFinishStub:
        _restore_pre_edit_object_selection = (
            deform.core.SDH_OT_box_select_ffd_points.
            _restore_pre_edit_object_selection)

        @staticmethod
        def _controller():
            return None

        @staticmethod
        def _remove_draw_handler():
            return None

    finish_stub = PreEditFinishStub()
    finish_stub._ffd_modal_finished = False
    finish_stub._restore_pre_edit_selection = True
    finish_stub._pre_edit_selected_names = (target.name,)
    finish_stub._pre_edit_active_name = target.name
    finish_stub._area = None
    deform.core.SDH_OT_box_select_ffd_points._finish_modal(
        finish_stub, bpy.context)
    if not finish_stub._ffd_modal_finished:
        raise AssertionError("pre-edit FFD modal cleanup did not finish")
    if finish_stub._restore_pre_edit_selection:
        raise AssertionError("pre-edit FFD modal cleanup did not restore selection")
    deform.core.refresh_controller_display(bpy.context, force=True)
    if not target.select_get() or not controller.select_get():
        raise AssertionError("target selection did not sync its FFD controller")
    if bpy.context.view_layer.objects.active != target:
        raise AssertionError("target selection sync changed the active object")

    properties.ffd_edit_mode_active = True
    properties.show_ffd_handles = True
    window_region = SimpleNamespace(x=0, y=0, width=100, height=100)
    modal_stub = SimpleNamespace(
        _state="WAITING",
        _window_region=window_region,
        _MOUSE_EVENTS=deform.core.SDH_OT_box_select_ffd_points._MOUSE_EVENTS,
        _controller=lambda: controller,
        _inside_region=deform.core.SDH_OT_box_select_ffd_points._inside_region,
        _inside_ui_region=None,
        _set_header=lambda _context: None,
        report=lambda *_args, **_kwargs: None,
    )
    # The production workspace reconciliation only treats a flag as live when
    # its modal operator is registered. Mirror that ownership in this synthetic
    # modal probe instead of relying on the old stale-flag shortcut.
    deform.core._FFD_MODAL_OPERATORS.append(modal_stub)
    modal_stub._inside_ui_region = lambda context, event: (
        deform.core.SDH_OT_box_select_ffd_points._inside_ui_region(
            modal_stub, context, event))
    sidebar_click = SimpleNamespace(
        type="LEFTMOUSE",
        value="PRESS",
        mouse_x=window_region.x + window_region.width + 8,
        mouse_y=window_region.y + window_region.height // 2,
    )
    # Reproduce Blender's post-Gizmo selection result: only the hidden
    # controller remains selected even though FFD edit mode is still active.
    target.select_set(False)
    controller.select_set(True)
    bpy.context.view_layer.objects.active = controller
    if deform.core.SDH_OT_box_select_ffd_points.modal(
            modal_stub, bpy.context, sidebar_click) != {"PASS_THROUGH"}:
        raise AssertionError("FFD modal blocked a sidebar mouse event")
    if not target.select_get() or not controller.select_get():
        raise AssertionError(
            "FFD modal did not restore target/controller selection")
    if bpy.context.view_layer.objects.active != target:
        raise AssertionError("FFD modal did not keep the controlled target active")

    # A Gizmo click can finish without delivering another event to the
    # persistent modal. The selection watcher must repair Blender's transient
    # controller-only result on its own so the FFD handles stay visible.
    target.select_set(False)
    controller.select_set(True)
    bpy.context.view_layer.objects.active = controller
    deform.core._SELECTION_SYNC_SIGNATURE = None
    deform.core._selection_sync_timer()
    if not target.select_get() or not controller.select_get():
        raise AssertionError(
            "FFD selection watcher did not restore target/controller selection")
    if bpy.context.view_layer.objects.active != target:
        raise AssertionError("FFD selection watcher did not restore target activity")

    # Some Blender layouts report the N-panel coordinates inside the WINDOW
    # region. The modal must still recognize the dedicated UI region and
    # pass the click through instead of starting a viewport box selection.
    ui_region = SimpleNamespace(
        type="UI", x=40, y=0, width=40, height=100)
    ui_area = SimpleNamespace(regions=(window_region, ui_region))
    modal_stub._area = ui_area
    embedded_sidebar_click = SimpleNamespace(
        type="LEFTMOUSE",
        value="PRESS",
        mouse_x=50,
        mouse_y=50,
    )
    if deform.core.SDH_OT_box_select_ffd_points.modal(
            modal_stub, bpy.context, embedded_sidebar_click) != {"PASS_THROUGH"}:
        raise AssertionError("FFD modal blocked an embedded N-panel click")

    # Keyboard shortcuts must also pass through while the pointer is over a
    # property editor; otherwise G/R/S/I/A are intercepted by the FFD modal.
    ui_keyboard_event = SimpleNamespace(
        type="G", value="PRESS", mouse_x=50, mouse_y=50)
    if deform.core.SDH_OT_box_select_ffd_points.modal(
            modal_stub, bpy.context, ui_keyboard_event) != {"PASS_THROUGH"}:
        raise AssertionError("FFD modal blocked N-panel keyboard input")

    # Cancelling G/R/S restores the persistent editor to WAITING. Blender then
    # sends the same key's RELEASE event; it must not be interpreted as a
    # second editor-level cancel. Both Esc and right mouse follow this sequence.
    modal_exit_calls = []
    modal_stub._finish_modal = lambda *_args, **_kwargs: modal_exit_calls.append(True)
    for cancel_event_type in ("ESC", "RIGHTMOUSE"):
        modal_stub._state = "WAITING"
        cancel_release = SimpleNamespace(
            type=cancel_event_type,
            value="RELEASE",
            mouse_x=10,
            mouse_y=10,
        )
        result = deform.core.SDH_OT_box_select_ffd_points.modal(
            modal_stub, bpy.context, cancel_release)
        if result != {"PASS_THROUGH"} or modal_exit_calls:
            raise AssertionError(
                f"FFD {cancel_event_type} transform cancel release exited edit mode")
    # A new press in WAITING remains the explicit way to leave FFD edit mode.
    exit_event = SimpleNamespace(
        type="ESC", value="PRESS", mouse_x=10, mouse_y=10)
    if deform.core.SDH_OT_box_select_ffd_points.modal(
            modal_stub, bpy.context, exit_event) != {"FINISHED"}:
        raise AssertionError("FFD editor did not exit on a fresh Esc press")
    if len(modal_exit_calls) != 1:
        raise AssertionError("FFD editor exit did not call its modal cleanup once")
    del modal_stub._finish_modal

    # Modal I must match the panel's complete cage-keyframe action.
    controller.animation_data_clear()
    full_key_event = SimpleNamespace(
        type="I", value="PRESS", alt=False, mouse_x=10, mouse_y=10)
    if deform.core.SDH_OT_box_select_ffd_points.modal(
            modal_stub, bpy.context, full_key_event) != {"RUNNING_MODAL"}:
        raise AssertionError("FFD modal full keyframe insertion failed")
    modal_paths = set(deform.core._animation_paths(controller))
    required_modal_paths = {
        "sdh_cage_deform.size",
        "location",
        "rotation_euler",
        "sdh_cage_deform.ffd_points[0].offset",
        "sdh_cage_deform.ffd_points[0].influence",
    }
    if not required_modal_paths.issubset(modal_paths):
        raise AssertionError(
            "FFD modal keyframe did not record the complete cage stage")
    controller.animation_data_clear()
    try:
        deform.core._FFD_MODAL_OPERATORS.remove(modal_stub)
    except ValueError:
        pass
    properties.ffd_edit_mode_active = False

    properties.ffd_symmetry_enabled = True
    properties.ffd_symmetry_axis = "W"
    bpy.context.view_layer.objects.active = target
    target.modifiers.active = modifier
    if bpy.ops.sdh.duplicate_cage_deform() != {"FINISHED"}:
        raise AssertionError("dedicated FFD stage duplication failed")
    copied_modifier = target.modifiers.active
    copied_controller = deform.find_controller(target, copied_modifier)
    copied_properties = copied_controller.sdh_cage_deform
    copied_lattice = deform.core.ffd_lattice_object(target, copied_modifier)
    if copied_properties.cage_type != "FFD":
        raise AssertionError("duplicated FFD stage lost its cage type")
    if deform.core.ffd_resolution(copied_properties) != (4, 5, 3):
        raise AssertionError("duplicated FFD stage lost its resolution")
    if not copied_properties.ffd_use_outside:
        raise AssertionError("duplicated FFD stage lost hollow mode")
    if (
            not copied_properties.ffd_symmetry_enabled or
            copied_properties.ffd_symmetry_axis != "W"
    ):
        raise AssertionError("duplicated FFD stage lost symmetry settings")
    if (Vector(copied_properties.ffd_points[0].offset) -
            Vector((0.35, 0.0, 0.0))).length > 1.0e-6:
        raise AssertionError("duplicated FFD stage lost point offsets")
    if copied_lattice is None or copied_lattice == lattice:
        raise AssertionError("duplicated FFD stage reused its source lattice")
    if tuple(target.modifiers).index(next(
            item for item in target.modifiers
            if item.type == "LATTICE" and item.object == copied_lattice
    )) != tuple(target.modifiers).index(copied_modifier) + 1:
        raise AssertionError("duplicated FFD companion is not adjacent")
    copied_index = deform.cage_modifiers(target).index(copied_modifier)
    if bpy.ops.sdh.remove_cage_deform(index=copied_index) != {"FINISHED"}:
        raise AssertionError("duplicated FFD stage cleanup failed")
    properties.ffd_symmetry_enabled = False

    properties.cage_type = "SHEAR"
    if lattice_name in bpy.data.objects:
        raise AssertionError("switching away from FFD left its lattice behind")
    if any(item.type == "LATTICE" for item in target.modifiers):
        raise AssertionError("switching away from FFD left a companion modifier")
    properties.cage_type = "FFD"
    deform.sync_controller(controller, pull_transform=False)
    lattice = deform.core.ffd_lattice_object(target, modifier)
    if lattice is None:
        raise AssertionError("switching back to FFD did not create a fresh lattice")
    lattice_name = lattice.name

    target.modifiers.active = modifier
    if bpy.ops.sdh.remove_cage_deform(index=0) != {"FINISHED"}:
        raise AssertionError("dedicated FFD removal failed")
    if lattice_name in bpy.data.objects:
        raise AssertionError("dedicated FFD lattice was left behind")
    print("SDH_FFD_LATTICE::PASS")
finally:
    if target.name in bpy.data.objects:
        bpy.data.objects.remove(target, do_unlink=True)
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
