"""Keep weighted FFD controls responsive while weighting only evaluation."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))

entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")


def check_vector(actual, expected, message, tolerance=1.0e-6):
    actual = Vector(actual)
    expected = Vector(expected)
    if (actual - expected).length > tolerance:
        raise AssertionError(f"{message}: {tuple(actual)} != {tuple(expected)}")


mesh = bpy.data.meshes.new("SDH Weighted Drag Mesh")
mesh.from_pydata(
    (
        (-1.0, -1.0, -1.0), (1.0, -1.0, -1.0),
        (1.0, 1.0, -1.0), (-1.0, 1.0, -1.0),
        (-1.0, -1.0, 1.0), (1.0, -1.0, 1.0),
        (1.0, 1.0, 1.0), (-1.0, 1.0, 1.0),
    ), (), ()
)
target = bpy.data.objects.new("SDH Weighted Drag", mesh)
bpy.context.collection.objects.link(target)
bpy.context.view_layer.objects.active = target
target.select_set(True)

try:
    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, target)
    properties = controller.sdh_cage_deform
    properties.cage_type = "FFD"
    properties.ffd_resolution_u = 3
    properties.ffd_resolution_v = 3
    properties.ffd_resolution_w = 3
    deform.core.ensure_ffd_point_collection(properties)

    first = properties.ffd_points[0]
    second = properties.ffd_points[1]
    first.offset = (0.8, 0.2, -0.4)
    first.influence = 0.25
    second.offset = (-0.2, 0.1, 0.3)
    second.influence = 0.75
    deform.sync_controller(controller, pull_transform=False)

    operator_type = deform.core.SDH_OT_box_select_ffd_points
    first_source = operator_type._point_source_local(properties, 0)
    first_authored = first_source + Vector(first.offset)
    check_vector(
        operator_type._point_local(properties, 0),
        first_authored,
        "weighted FFD handle did not use the authored point position",
    )

    world = deform.gizmos.ffd_point_world(target, controller, 0)
    local = deform.cage_local_matrix(target, controller).inverted_safe() @ world
    check_vector(
        local,
        first_authored,
        "weighted FFD Gizmo did not follow the authored point position",
    )
    authored_wire, _edges = deform.gizmos.ffd_wire_geometry(properties)
    effective_wire, _edges = deform.gizmos.ffd_wire_geometry(
        properties, effective=True)
    check_vector(
        authored_wire[0],
        first_authored,
        "FFD wire did not show the authored cage",
    )
    check_vector(
        effective_wire[0],
        first_source + Vector(first.offset) * first.influence,
        "FFD ghost wire did not show the weighted result",
    )

    sources = {
        index: operator_type._point_source_local(properties, index)
        for index in (0, 1)
    }
    initial_offsets = {
        index: Vector(properties.ffd_points[index].offset)
        for index in (0, 1)
    }
    operator = SimpleNamespace(
        _controller=lambda: controller,
        _transform_source_points=sources,
        _transform_initial_offsets=initial_offsets,
        _transform_initial_effective_offsets={
            index: deform.core.ffd_point_effective_offset(properties, index)
            for index in (0, 1)
        },
        _area=None,
    )
    delta = Vector((0.45, -0.15, 0.25))
    requested_points = {
        index: sources[index] + initial_offsets[index] + delta
        for index in (0, 1)
    }

    writer = operator_type._write_transform_points
    if not writer(operator, bpy.context, properties, requested_points):
        raise AssertionError("weighted FFD drag write failed")
    first_result = {
        index: Vector(properties.ffd_points[index].offset)
        for index in (0, 1)
    }
    if not writer(operator, bpy.context, properties, requested_points):
        raise AssertionError("repeated weighted FFD drag write failed")
    second_result = {
        index: Vector(properties.ffd_points[index].offset)
        for index in (0, 1)
    }

    for index in (0, 1):
        expected = initial_offsets[index] + delta
        check_vector(
            first_result[index], expected,
            f"weighted FFD point {index} did not follow the drag",
        )
        check_vector(
            second_result[index], expected,
            f"weighted FFD point {index} accumulated the same drag twice",
        )
        check_vector(
            deform.core.ffd_point_effective_offset(properties, index),
            expected * properties.ffd_points[index].influence,
            f"weighted FFD point {index} did not attenuate evaluation",
        )

    for mode, axis in (("LINE", "U"), ("FACE", "UW")):
        group = tuple(deform.core.ffd_selection_indices(
            properties, 0, mode, axis=axis))
        if len(group) < 2:
            raise AssertionError(f"weighted FFD {mode} group is incomplete")
        sources = {
            index: operator_type._point_source_local(properties, index)
            for index in group
        }
        for order, index in enumerate(group):
            properties.ffd_points[index].offset = (
                order * 0.07, -order * 0.03, order * 0.05)
            properties.ffd_points[index].influence = (
                0.0 if order == 0 else min(0.2 + order * 0.2, 1.0))
        initial_offsets = {
            index: Vector(properties.ffd_points[index].offset)
            for index in group
        }
        operator = SimpleNamespace(
            _controller=lambda: controller,
            _transform_source_points=sources,
            _transform_initial_offsets=initial_offsets,
            _area=None,
        )
        delta = Vector((0.25, 0.35, -0.15))
        requested_points = {
            index: sources[index] + initial_offsets[index] + delta
            for index in group
        }
        if not writer(operator, bpy.context, properties, requested_points):
            raise AssertionError(f"weighted FFD {mode} drag write failed")
        first_pass = {
            index: Vector(properties.ffd_points[index].offset)
            for index in group
        }
        if not writer(operator, bpy.context, properties, requested_points):
            raise AssertionError(f"repeated weighted FFD {mode} drag failed")
        for index in group:
            expected = initial_offsets[index] + delta
            check_vector(
                first_pass[index], expected,
                f"weighted FFD {mode} point {index} did not follow the group",
            )
            check_vector(
                properties.ffd_points[index].offset, expected,
                f"weighted FFD {mode} point {index} accumulated group drag",
            )
            check_vector(
                deform.core.ffd_point_effective_offset(properties, index),
                expected * properties.ffd_points[index].influence,
                f"weighted FFD {mode} point {index} ignored its mask",
            )

    print("SDH_FFD_WEIGHT_DRAG::PASS")
finally:
    if target.name in bpy.data.objects:
        bpy.data.objects.remove(target, do_unlink=True)
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
