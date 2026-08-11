"""Regression for offset-profile chained cage previews.

Run with:
    blender --background --factory-startup --python-exit-code 1 \
        --python tests/chain_global_profile_preview_regression.py
"""

from __future__ import annotations

import importlib
import json
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Euler, Vector


SOURCE = Path(__file__).resolve().parents[1]
INSTALLED_PACKAGE = os.environ.get("SDH_TEST_MODULE")
PACKAGE = INSTALLED_PACKAGE or SOURCE.name
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(SOURCE.parent))

BOUNDARIES = (-3.0, -1.0, 1.0, 3.0)
SECTION = (
    (0.0, 0.0),
    (-1.1, -0.9),
    (-1.1, 0.9),
    (1.1, 0.9),
    (1.1, -0.9),
    (1.1, 0.0),
)
CAGE_ROTATION = Euler((math.pi * 0.5, 0.0, 0.0), "XYZ").to_matrix()
VERTICES = tuple(
    tuple(CAGE_ROTATION @ Vector((x, y, z)))
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

mesh = bpy.data.meshes.new("SDH Global Profile Preview Mesh")
mesh.from_pydata(VERTICES, (), ())
target = bpy.data.objects.new("SDH Global Profile Preview", mesh)
bpy.context.collection.objects.link(target)
activate(target)

modifier, controller, _previous = deform.create_deform_stage(
    bpy.context, target, show_other_default=True)
properties = controller.sdh_cage_deform
properties.size = (2.2, 6.0, 1.8)
properties.mode = "LIMITED"
properties.origin = "BOTTOM"
properties.alignment = "POS_Z"
properties.preserve_volume = True
properties.bend_strength = math.radians(33.0)
properties.bottom_offset = (-0.38, 0.24)
properties.top_offset = (0.64, -0.31)
controller.location = (0.0, 0.0, 0.0)
controller.rotation_euler = (math.pi * 0.5, 0.0, 0.0)
deform.core.set_deform_layers(properties, ("BEND",), bpy.context)
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
wire_preview_error = 0.0
parameter_handle_error = 0.0
boundary_handle_error = 0.0
end_shape_handle_error = 0.0
local_socket_offset_max = 0.0

for stage_index, (stage, stage_controller) in enumerate(
        zip(stages, controllers)):
    stage_properties = stage_controller.sdh_cage_deform
    domain = deform.core._chain_domain_input_values(stage_controller, stage)
    if not bool(domain.get("Chain Global Profile Active", False)):
        raise AssertionError(f"stage {stage_index} did not use global profile")
    # Bend is retained as a source-frame baseline when an end profile is
    # authored.  This keeps the changing section frame exact; the regression
    # contract is that the profile is active once and its local offsets are
    # not applied a second time.
    if not bool(domain.get("Chain Global Prefix Active", False)):
        raise AssertionError(f"stage {stage_index} lost Bend baseline")
    if not int(domain.get("Chain Global Prefix Types", 0)) & deform.core.DEFORM_BITS["BEND"]:
        raise AssertionError(f"stage {stage_index} lost Bend baseline mask")
    for socket_name in ("Bottom Offset", "Top Offset"):
        local_socket_offset_max = max(
            local_socket_offset_max,
            Vector(deform.modifier_input(stage, socket_name)).length,
        )

    stage_matrix = chain._stage_local_matrix(target, stage_controller)
    wire = deform.gizmos.cage_preview_wire_vertices(
        stage_properties, steps=8, ring_positions=(0.0, 1.0))
    for rail_index, section_index in enumerate(range(1, 5)):
        for endpoint_offset, boundary_index in (
                (0, stage_index), (15, stage_index + 1)):
            displayed = stage_matrix @ Vector(
                wire[rail_index * 16 + endpoint_offset])
            expected = after[boundary_index * len(SECTION) + section_index]
            wire_preview_error = max(
                wire_preview_error, (displayed - expected).length)

    top_center_expected = after[(stage_index + 1) * len(SECTION)]
    handle_world = deform.gizmos.parameter_handle_world(
        bpy.context, target, stage_controller, "BEND", separate=False)
    handle_target = target.matrix_world.inverted_safe() @ handle_world
    parameter_handle_error = max(
        parameter_handle_error,
        (handle_target - top_center_expected).length,
    )

    for side, boundary_index in (
            ("BOTTOM", stage_index), ("TOP", stage_index + 1)):
        boundary_local, _handle_local = deform.cage_boundary_points_local(
            stage_properties, side)
        boundary_expected = after[boundary_index * len(SECTION)]
        boundary_handle_error = max(
            boundary_handle_error,
            (stage_matrix @ Vector(boundary_local) - boundary_expected).length,
        )

        end_shape_world = deform.core.end_shape_handle_world(
            target, stage_controller, side)
        end_shape_target = (
            target.matrix_world.inverted_safe() @ end_shape_world)
        end_shape_expected = after[
            boundary_index * len(SECTION) + 5]
        end_shape_handle_error = max(
            end_shape_handle_error,
            (end_shape_target - end_shape_expected).length,
        )

metrics = {
    "subdivision_error": subdivision_error,
    "wire_preview_error": wire_preview_error,
    "parameter_handle_error": parameter_handle_error,
    "boundary_handle_error": boundary_handle_error,
    "end_shape_handle_error": end_shape_handle_error,
    "local_socket_offset_max": local_socket_offset_max,
}
print("SDH_CHAIN_GLOBAL_PROFILE_PREVIEW::" + json.dumps(metrics))

if subdivision_error > 4.0e-3:
    raise AssertionError(
        f"subdivision changed evaluated geometry by {subdivision_error:.6f}")
for name, value in metrics.items():
    if name in {"subdivision_error", "local_socket_offset_max"}:
        continue
    if value > 4.0e-3:
        raise AssertionError(f"{name} differs from geometry by {value:.6f}")

print("SDH_CHAIN_GLOBAL_PROFILE_PREVIEW::PASS")

if not INSTALLED_PACKAGE:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
