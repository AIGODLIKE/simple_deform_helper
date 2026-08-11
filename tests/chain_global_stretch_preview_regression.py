"""Regression for final-state Bend + Stretch chain cage previews.

Run with:
    blender --background --factory-startup --python-exit-code 1 \
        --python tests/chain_global_stretch_preview_regression.py
"""

from __future__ import annotations

import importlib
import json
import math
import os
import sys
import time
from pathlib import Path
from types import MethodType, SimpleNamespace

import bpy
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
INSTALLED_PACKAGE = os.environ.get("SDH_TEST_MODULE")
PACKAGE = INSTALLED_PACKAGE or SOURCE.name
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(SOURCE.parent))

BOUNDARIES = (-3.0, -1.0, 1.0, 3.0)
SECTION = (
    (0.0, 0.0),
    (-1.0, -1.0),
    (-1.0, 1.0),
    (1.0, 1.0),
    (1.0, -1.0),
    (1.0, 0.0),
)
VERTICES = tuple(
    (x, y, z)
    for y in BOUNDARIES
    for x, z in SECTION
)


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def evaluated_points(obj):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return tuple(vertex.co.copy() for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


addon = importlib.import_module(PACKAGE)
if not INSTALLED_PACKAGE:
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
chain = deform.chain

mesh = bpy.data.meshes.new("SDH Global Stretch Preview Mesh")
mesh.from_pydata(VERTICES, (), ())
target = bpy.data.objects.new("SDH Global Stretch Preview", mesh)
bpy.context.collection.objects.link(target)
activate(target)

modifier, controller, _previous = deform.create_deform_stage(
    bpy.context, target, show_other_default=True)
properties = controller.sdh_cage_deform
properties.size = (2.0, 6.0, 2.0)
properties.mode = "LIMITED"
properties.origin = "BOTTOM"
properties.preserve_volume = True
properties.bend_strength = math.radians(15.0)
properties.bend_direction = 0.0
properties.stretch_factor = 0.14
controller.location = (0.0, 0.0, 0.0)
controller.rotation_euler = (0.0, 0.0, 0.0)
if not deform.core.set_deform_layers(
        properties, ("BEND", "STRETCH"), bpy.context):
    raise AssertionError("could not create Bend + Stretch stack")
deform.sync_controller(controller, pull_transform=False)
bpy.context.view_layer.update()
before = evaluated_points(target)

target.modifiers.active = modifier
result = bpy.ops.sdh.subdivide_cage_to_chain(
    count=3,
    gap=0.0,
    auto_reconnect=True,
    sync_shared_end_scale=True,
)
if result != {"FINISHED"}:
    raise AssertionError(f"subdivide returned {result!r}")
deform.core.flush_pending_chain_updates(target)
bpy.context.view_layer.update()

stages = tuple(chain.chain_stages(target))
controllers = tuple(deform.find_controller(target, stage) for stage in stages)
if len(stages) != 3 or not all(controllers):
    raise AssertionError("subdivision did not create three complete stages")
after = evaluated_points(target)

subdivision_error = max(
    (current - source).length for current, source in zip(after, before))
preview_error = 0.0
wire_preview_error = 0.0
parameter_handle_error = 0.0
end_shape_handle_error = 0.0
legacy_preview_error = 0.0
boundary_handle_error = 0.0

for stage_index, (stage, stage_controller) in enumerate(
        zip(stages, controllers)):
    stage_properties = stage_controller.sdh_cage_deform
    state = deform.core.chain_global_stretch_preview_state(stage_properties)
    if state is None:
        raise AssertionError(
            f"stage {stage_index} has no global Stretch preview state")
    stage_matrix = chain._stage_local_matrix(target, stage_controller)
    half_y = float(stage_properties.size[1]) * 0.5
    wire = deform.gizmos.cage_preview_wire_vertices(
        stage_properties, steps=8, ring_positions=(0.0, 1.0))
    first_rail_endpoints = (wire[0], wire[15])
    for endpoint, boundary_index in zip(
            first_rail_endpoints, (stage_index, stage_index + 1)):
        expected = after[boundary_index * len(SECTION) + 1]
        wire_preview_error = max(
            wire_preview_error,
            (stage_matrix @ Vector(endpoint) - expected).length,
        )
    top_center_expected = after[(stage_index + 1) * len(SECTION)]
    for deform_type in ("BEND", "STRETCH"):
        parameter_world = deform.gizmos.parameter_handle_world(
            bpy.context, target, stage_controller, deform_type,
            separate=False)
        parameter_handle_error = max(
            parameter_handle_error,
            (target.matrix_world.inverted_safe() @ parameter_world -
             top_center_expected).length,
        )
    for side, sign, boundary_index in (
            ("BOTTOM", -1.0, stage_index),
            ("TOP", 1.0, stage_index + 1)):
        boundary_local, _handle_local = deform.cage_boundary_points_local(
            stage_properties, side)
        center_expected = after[boundary_index * len(SECTION)]
        boundary_handle_error = max(
            boundary_handle_error,
            (stage_matrix @ Vector(boundary_local) - center_expected).length,
        )
        end_shape_world = deform.core.end_shape_handle_world(
            target, stage_controller, side)
        end_shape_expected = after[
            boundary_index * len(SECTION) + 5]
        end_shape_handle_error = max(
            end_shape_handle_error,
            (target.matrix_world.inverted_safe() @ end_shape_world -
             end_shape_expected).length,
        )
        for section_index, (x, z) in enumerate(SECTION):
            source_local = Vector((x, sign * half_y, z))
            expected = after[
                boundary_index * len(SECTION) + section_index]
            displayed = stage_matrix @ deform.core.deform_point_for_display(
                source_local,
                stage_properties,
                chain_stretch_state=state,
            )
            legacy = stage_matrix @ deform.deform_point_from_properties(
                source_local, stage_properties, chain_preview=True)
            preview_error = max(
                preview_error, (Vector(displayed) - expected).length)
            legacy_preview_error = max(
                legacy_preview_error, (Vector(legacy) - expected).length)

metrics = {
    "subdivision_error": subdivision_error,
    "preview_error": preview_error,
    "wire_preview_error": wire_preview_error,
    "parameter_handle_error": parameter_handle_error,
    "end_shape_handle_error": end_shape_handle_error,
    "boundary_handle_error": boundary_handle_error,
    "legacy_preview_error": legacy_preview_error,
}
print("SDH_CHAIN_GLOBAL_STRETCH_PREVIEW::" + json.dumps(metrics))

if subdivision_error > 4.0e-3:
    raise AssertionError(
        f"subdivision changed evaluated geometry by {subdivision_error:.6f}")
if preview_error > 4.0e-3:
    raise AssertionError(
        f"final cage preview differs from geometry by {preview_error:.6f}")
if wire_preview_error > 4.0e-3:
    raise AssertionError(
        f"wire preview differs from geometry by {wire_preview_error:.6f}")
if parameter_handle_error > 4.0e-3:
    raise AssertionError(
        f"parameter handle differs from geometry by {parameter_handle_error:.6f}")
if end_shape_handle_error > 4.0e-3:
    raise AssertionError(
        f"end-shape handle differs from geometry by {end_shape_handle_error:.6f}")
if boundary_handle_error > 4.0e-3:
    raise AssertionError(
        f"boundary handle differs from geometry by {boundary_handle_error:.6f}")
if legacy_preview_error < 2.0e-2:
    raise AssertionError("fixture no longer exposes the pre-fix preview drift")

# A global Stretch chain exposes one shared editable factor. Exercise the same
# RNA callback used by the panel and viewport Gizmo, then prove it updates the
# evaluator immediately without rebuilding any chain frames during the drag.
original_factor = float(
    deform.core.chain_global_stretch_value(controllers[0], stages[0]))
edited_factor = 0.30
reconnect_calls = []
original_reconnect = chain.reconnect_chain


def counted_reconnect(*args, **kwargs):
    reconnect_calls.append((args, kwargs))
    return original_reconnect(*args, **kwargs)


chain.reconnect_chain = counted_reconnect
edit_started = time.perf_counter()
try:
    drag = SimpleNamespace(
        DEFORM_TYPE="STRETCH",
        PROPERTY_NAME="stretch_factor",
        invoke_target=target,
        invoke_modifier=stages[1],
        invoke_controller=controllers[1],
        initial_value=original_factor,
        initial_direction=0.0,
        original_value=original_factor,
        original_direction=0.0,
        initial_mouse=(100, 100),
        axis_screen=(1.0, 0.0),
        axis_scale=0.01,
        line_world_a=None,
        line_world_b=None,
        line_t0=0.0,
        line_span=1.0,
        twist_center=None,
        twist_last_angle=None,
        twist_delta=0.0,
        twist_axis=None,
        twist_handle=None,
        _mod_flags=(False, False, False),
    )
    drag._set_float_if_changed = MethodType(
        deform.gizmos._SDHCageParameterGizmo._set_float_if_changed,
        drag,
    )
    for step in range(16):
        event = SimpleNamespace(
            type="MOUSEMOVE",
            mouse_region_x=101 + step,
            mouse_region_y=100,
            shift=False,
            ctrl=False,
            alt=False,
        )
        result = deform.gizmos.SDHCageStretchFactorGizmo.modal(
            drag, bpy.context, event, None)
        if result != {"RUNNING_MODAL"}:
            raise AssertionError(f"Stretch Gizmo modal returned {result!r}")
    edit_elapsed = time.perf_counter() - edit_started
    deform.core.flush_pending_chain_updates(target)
finally:
    chain.reconnect_chain = original_reconnect
bpy.context.view_layer.update()
edited = evaluated_points(target)

geometry_edit_delta = max(
    (current - source).length for current, source in zip(edited, after))
edited_preview_error = 0.0
edited_handle_error = 0.0
metadata_error = 0.0
socket_error = 0.0
property_error = 0.0
for stage_index, (stage, stage_controller) in enumerate(
        zip(stages, controllers)):
    stage_properties = stage_controller.sdh_cage_deform
    property_error = max(
        property_error,
        abs(float(stage_properties.stretch_factor) - edited_factor),
    )
    for owner in (stage.node_group, stage_controller):
        owner_factor = owner.get(
            chain.CHAIN_GLOBAL_STRETCH_FACTOR, edited_factor)
        metadata_error = max(
            metadata_error,
            abs(float(owner_factor) - edited_factor),
        )
    socket_error = max(
        socket_error,
        abs(float(deform.modifier_input(
            stage, "Chain Global Stretch Factor")) - edited_factor),
    )
    resolved_factor = deform.core.chain_global_stretch_value(
        stage_controller, stage)
    if resolved_factor is None:
        raise AssertionError(
            f"stage {stage_index} lost global Stretch while editing")
    metadata_error = max(
        metadata_error, abs(float(resolved_factor) - edited_factor))

    stage_matrix = chain._stage_local_matrix(target, stage_controller)
    wire = deform.gizmos.cage_preview_wire_vertices(
        stage_properties, steps=8, ring_positions=(0.0, 1.0))
    expected_top = edited[(stage_index + 1) * len(SECTION) + 1]
    edited_preview_error = max(
        edited_preview_error,
        (stage_matrix @ Vector(wire[15]) - expected_top).length,
    )
    handle_world = deform.gizmos.parameter_handle_world(
        bpy.context, target, stage_controller, "STRETCH", separate=False)
    expected_center = edited[(stage_index + 1) * len(SECTION)]
    edited_handle_error = max(
        edited_handle_error,
        (target.matrix_world.inverted_safe() @ handle_world -
         expected_center).length,
    )

metrics.update({
    "edit_elapsed": edit_elapsed,
    "geometry_edit_delta": geometry_edit_delta,
    "edited_preview_error": edited_preview_error,
    "edited_handle_error": edited_handle_error,
    "metadata_error": metadata_error,
    "socket_error": socket_error,
    "property_error": property_error,
    "reconnect_calls": len(reconnect_calls),
})
print("SDH_CHAIN_GLOBAL_STRETCH_EDIT::" + json.dumps(metrics))

if reconnect_calls:
    raise AssertionError(
        f"Stretch drag rebuilt the chain {len(reconnect_calls)} times")
if geometry_edit_delta < 0.2:
    raise AssertionError("edited Stretch factor did not deform the model")
if property_error > 1.0e-5:
    raise AssertionError(
        f"stage properties did not share Stretch: {property_error:.6f}")
if metadata_error > 1.0e-5 or socket_error > 1.0e-5:
    raise AssertionError(
        "global Stretch metadata/socket did not update immediately: "
        f"metadata={metadata_error:.6f}, socket={socket_error:.6f}")
if edited_preview_error > 4.0e-3 or edited_handle_error > 4.0e-3:
    raise AssertionError(
        "edited Stretch display differs from geometry: "
        f"wire={edited_preview_error:.6f}, handle={edited_handle_error:.6f}")

# Cancel through the real Gizmo exit implementation.
deform.gizmos.SDHCageStretchFactorGizmo.exit(drag, bpy.context, True)
deform.core.flush_pending_chain_updates(target)
bpy.context.view_layer.update()
restored = evaluated_points(target)
cancel_restore_error = max(
    (current - source).length for current, source in zip(restored, after))
if cancel_restore_error > 4.0e-3:
    raise AssertionError(
        f"cancel did not restore global Stretch: {cancel_restore_error:.6f}")

if not INSTALLED_PACKAGE:
    addon.unregister()
print("SDH_CHAIN_GLOBAL_STRETCH_PREVIEW_OK")
