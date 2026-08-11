"""Regression for live FFD resolution edits with authored point offsets."""
from __future__ import annotations

import importlib
import itertools
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))


def evaluated_points(target):
    bpy.context.view_layer.update()
    evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return tuple(target.matrix_world @ vertex.co for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")

coordinates = (-1.0, -0.5, 0.0, 0.5, 1.0)
mesh = bpy.data.meshes.new("SDH FFD Resolution Regression Mesh")
mesh.from_pydata(tuple(itertools.product(coordinates, repeat=3)), (), ())
target = bpy.data.objects.new("SDH FFD Resolution Regression", mesh)
bpy.context.collection.objects.link(target)
bpy.context.view_layer.objects.active = target
target.select_set(True)

try:
    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, target)
    properties = controller.sdh_cage_deform
    properties.cage_type = "FFD"
    if tuple(deform.core.ffd_selected_indices(properties)) != (0,):
        raise AssertionError("new FFD did not select its active point")
    if deform.core.FFD_RESOLUTION_PROP in controller:
        del controller[deform.core.FFD_RESOLUTION_PROP]
    deform.core.ensure_ffd_point_collection(properties)
    if tuple(controller.get(deform.core.FFD_RESOLUTION_PROP, ())) != (2, 2, 2):
        raise AssertionError("FFD no-op resize did not restore its topology marker")

    interpolation = os.environ.get(
        "SDH_FFD_TEST_INTERPOLATION", "KEY_BSPLINE")
    initial_resolution = int(os.environ.get(
        "SDH_FFD_TEST_INITIAL_RESOLUTION", "2"))
    target_resolution = int(os.environ.get(
        "SDH_FFD_TEST_RESOLUTION", "3"))
    resize_axes = os.environ.get("SDH_FFD_TEST_AXES", "U").upper()
    weighted = os.environ.get("SDH_FFD_TEST_WEIGHTED", "0") == "1"
    old_resolution = (initial_resolution,) * 3
    new_resolution = tuple(
        int(os.environ.get(
            f"SDH_FFD_TEST_RESOLUTION_{axis}", str(target_resolution)))
        if axis in resize_axes else initial_resolution
        for axis in "UVW")
    properties.ffd_interpolation_u = interpolation
    properties.ffd_interpolation_v = interpolation
    properties.ffd_interpolation_w = interpolation
    properties.ffd_resolution_u = initial_resolution
    properties.ffd_resolution_v = initial_resolution
    properties.ffd_resolution_w = initial_resolution

    pointer = controller.as_pointer()
    deform.core._FFD_POINT_GUARD.add(pointer)
    try:
        for index, point in enumerate(properties.ffd_points):
            point.offset = (0.0, 0.0, 0.0)
            point.influence = (
                0.25 + 0.75 * index / max(len(properties.ffd_points) - 1, 1)
                if weighted else 1.0)
            point.selected = False
        properties.ffd_points[0].offset = (0.75, 0.0, 0.25)
        selected = deform.core.ffd_point_index(
            initial_resolution - 1,
            initial_resolution - 1,
            initial_resolution - 1,
            old_resolution,
        )
        properties.ffd_points[selected].selected = True
        properties.ffd_active_point = selected
    finally:
        deform.core._FFD_POINT_GUARD.discard(pointer)
    deform.sync_controller(controller, pull_transform=False)
    target.modifiers.active = modifier
    before = evaluated_points(target)

    resize_started = time.perf_counter()
    for axis, value in zip("uvw", new_resolution):
        if value != initial_resolution:
            setattr(properties, f"ffd_resolution_{axis}", value)
            if target.modifiers.active != modifier:
                active = target.modifiers.active
                raise AssertionError(
                    "FFD resolution edit replaced the active cage stage with "
                    f"{getattr(active, 'type', None)} "
                    f"{getattr(active, 'name', None)!r}")
    resize_ms = (time.perf_counter() - resize_started) * 1000.0
    after = evaluated_points(target)

    maximum_delta = max(
        (left - right).length for left, right in zip(before, after))
    selected_after = tuple(
        index for index, point in enumerate(properties.ffd_points)
        if point.selected)
    expected_corners = tuple(
        deform.core.ffd_point_index(
            new_resolution[0] - 1 if x_sign > 0.0 else 0,
            new_resolution[1] - 1 if y_sign > 0.0 else 0,
            new_resolution[2] - 1 if z_sign > 0.0 else 0,
            new_resolution,
        )
        for _label, x_sign, y_sign, z_sign in deform.core.FFD_CORNERS
    )
    if deform.core.ffd_grid_corner_indices(properties) != expected_corners:
        raise AssertionError("high-resolution FFD did not expose its true corners")
    if deform.gizmos.ffd_display_corner_indices(properties) != expected_corners:
        raise AssertionError("inactive FFD handles used low raw point indices")
    tolerance = (
        1.0e-5
        if interpolation == "KEY_LINEAR" and initial_resolution == 2 else
        (1.0e-1 if len(resize_axes) == 1 else 2.0e-1)
    )
    if maximum_delta > tolerance:
        raise AssertionError(
            f"FFD resolution edit changed deformation by {maximum_delta:.9f}")
    if len(selected_after) != 1:
        raise AssertionError(
            "FFD resolution edit expanded one selected point into "
            f"{len(selected_after)} points: {selected_after}")
    if properties.ffd_active_point != selected_after[0]:
        raise AssertionError("FFD resolution edit did not remap the active point")
    influences = tuple(
        float(point.influence) for point in properties.ffd_points)
    if any(value < 0.0 or value > 1.0 for value in influences):
        raise AssertionError("FFD resolution edit produced an invalid influence")
    if weighted and all(abs(value - 1.0) <= 1.0e-6 for value in influences):
        raise AssertionError("FFD resolution edit discarded authored influences")
    resolved_target, resolved_modifier, resolved_controller = (
        deform.resolve_context_deform(bpy.context))
    if (
            resolved_target != target or
            resolved_modifier != modifier or
            resolved_controller != controller
    ):
        raise AssertionError(
            "FFD resolution edit made the active cage unavailable to the panel")
    expected_selected = (new_resolution[0] * new_resolution[1] * new_resolution[2] - 1,)
    if selected_after != expected_selected:
        raise AssertionError(
            f"FFD corner selection remapped to {selected_after}, "
            f"expected {expected_selected}")

    class FakeGizmos:
        @staticmethod
        def new(_gizmo_type):
            return SimpleNamespace()

    bundle = deform.gizmos._new_other_stage_edit_bundle()
    deform.gizmos._ensure_other_stage_bundle(
        FakeGizmos(), bundle, properties)
    bundle_corners = tuple(
        handle.corner_index for handle in bundle["ffd_handles"])
    if bundle_corners != expected_corners:
        raise AssertionError(
            f"inactive FFD bundle used {bundle_corners}, expected {expected_corners}")

    if (
            old_resolution == (2, 2, 2) and
            new_resolution == (3, 2, 2)
    ):
        properties.ffd_symmetry_axes = {"U"}
        properties.ffd_symmetry_enabled = True
        pointer = controller.as_pointer()
        deform.core._FFD_POINT_GUARD.add(pointer)
        try:
            for point in properties.ffd_points:
                point.selected = False
            center = deform.core.ffd_point_index(1, 0, 0, (3, 2, 2))
            properties.ffd_points[center].selected = True
            properties.ffd_active_point = center
        finally:
            deform.core._FFD_POINT_GUARD.discard(pointer)
        properties.ffd_resolution_u = 4
        if target.modifiers.active != modifier:
            raise AssertionError(
                "odd-to-even FFD resize activated the internal Lattice")
        symmetric_selection = tuple(
            index for index, point in enumerate(properties.ffd_points)
            if point.selected)
        expected_symmetric = tuple(sorted((
            deform.core.ffd_point_index(1, 0, 0, (4, 2, 2)),
            deform.core.ffd_point_index(2, 0, 0, (4, 2, 2)),
        )))
        if symmetric_selection != expected_symmetric:
            raise AssertionError(
                f"odd-to-even FFD symmetry mapped to {symmetric_selection}, "
                f"expected {expected_symmetric}")
    print(
        "SDH_FFD_RESOLUTION_CHANGE::PASS::"
        f"resolution={old_resolution}->{new_resolution}::"
        f"axes={resize_axes}::"
        f"interpolation={interpolation}::"
        f"weighted={weighted}::"
        f"max_delta={maximum_delta:.9f}::"
        f"selected={selected_after[0]}::resize_ms={resize_ms:.3f}")
finally:
    if target.name in bpy.data.objects:
        bpy.data.objects.remove(target, do_unlink=True)
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
