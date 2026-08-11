"""Inspect the downstream boundary identity for non-Bottom chain origins."""

from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))


def values(vector):
    return tuple(round(float(value), 8) for value in vector)


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
chain = deform.chain

mesh = bpy.data.meshes.new("SDH Boundary Identity")
mesh.from_pydata(tuple(
    (x, y, z)
    for y in (-3.0, 0.0, 3.0)
    for x, z in ((0.65, 0.0), (-0.65, 0.0),
                 (0.0, 0.65), (0.0, -0.65))
), (), ())
target = bpy.data.objects.new("SDH Boundary Identity", mesh)
bpy.context.collection.objects.link(target)
target.select_set(True)
bpy.context.view_layer.objects.active = target

assert bpy.ops.sdh.add_cage_chain(
    count=2, connection_mode="CHAINED", gap=0.0,
    auto_reconnect=True, sync_shared_end_scale=True,
    alignment="POS_Y", origin="TOP",
) == {"FINISHED"}
stages = chain.chain_stages(target)
controllers = tuple(deform.find_controller(target, stage) for stage in stages)
for index, controller in enumerate(controllers):
    properties = controller.sdh_cage_deform
    deform.core.set_deform_layers(properties, ("BEND", "TWIST"), bpy.context)
    properties.origin = "TOP"
    properties.bend_strength = math.radians((48.0, -37.0)[index])
    properties.bend_direction = math.radians((17.0, -29.0)[index])
    properties.twist_strength = math.radians((31.0, -46.0)[index])
    properties.top_scale = (1.0, 1.0)
    properties.bottom_scale = (1.0, 1.0)
    properties.top_offset = (0.0, 0.0)
    properties.bottom_offset = (0.0, 0.0)
    deform.sync_controller(controller, pull_transform=False)
deform.core.flush_pending_chain_updates(target)

source = Vector((0.65, 0.0, 0.0))
root_matrix = chain._stage_local_matrix(target, controllers[0])
root_local = root_matrix.inverted_safe() @ source
root_output = deform.deform_point_from_properties(
    root_local, controllers[0].sdh_cage_deform, evaluator=True)
incoming = root_matrix @ root_output

controller = controllers[1]
properties = controller.sdh_cage_deform
matrix = chain._stage_local_matrix(target, controller)
raw = matrix.inverted_safe() @ incoming
frame = deform.core.chain_input_frame_for_controller(
    controller, stages[1], properties)
adjusted = deform.core.chain_input_point_from_properties(raw, properties)
evaluated = deform.deform_point_from_properties(
    raw, properties, evaluator=True)
direct = deform.deform_point_from_properties(
    adjusted, properties, evaluator=True,
    apply_chain_input_offset=False)
half_y = float(properties.size[1]) * 0.5
lower = Vector((0.65, -half_y, 0.0))
lower_evaluated = deform.deform_point_from_properties(
    lower, properties, evaluator=True,
    apply_chain_input_offset=False)
root_top_frame = chain._stage_boundary_frame(target, controllers[0], "TOP")
downstream_bottom_frame = chain._stage_boundary_frame(target, controller, "BOTTOM")

print("SDH_BOUNDARY_IDENTITY::SOURCE", values(source))
print("SDH_BOUNDARY_IDENTITY::INCOMING", values(incoming))
print("SDH_BOUNDARY_IDENTITY::MATRIX", tuple(values(row) for row in matrix))
print("SDH_BOUNDARY_IDENTITY::RAW", values(raw))
print("SDH_BOUNDARY_IDENTITY::FRAME", tuple(values(item) for item in frame))
print("SDH_BOUNDARY_IDENTITY::ADJUSTED", values(adjusted))
print("SDH_BOUNDARY_IDENTITY::AUTHORED_LOWER", values(lower))
print("SDH_BOUNDARY_IDENTITY::LOWER_EVALUATED", values(lower_evaluated))
print("SDH_BOUNDARY_IDENTITY::ROOT_TOP_FRAME",
      tuple(values(item) for item in root_top_frame))
print("SDH_BOUNDARY_IDENTITY::DOWNSTREAM_BOTTOM_FRAME",
      tuple(values(item) for item in downstream_bottom_frame))
print("SDH_BOUNDARY_IDENTITY::DIRECT", values(direct))
print("SDH_BOUNDARY_IDENTITY::EVALUATED", values(evaluated))
print("SDH_BOUNDARY_IDENTITY::OUTPUT", values(matrix @ evaluated))
print("SDH_BOUNDARY_IDENTITY::DELTA", (matrix @ evaluated - incoming).length)

addon.unregister()
bpy.context.preferences.addons.remove(entry)
