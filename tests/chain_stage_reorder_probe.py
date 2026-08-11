"""Probe native and add-on chain-stage reorder paths."""
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


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def points(obj):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return tuple(vertex.co.copy() for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def maximum(first, second):
    return max(((a - b).length for a, b in zip(first, second)), default=0.0)


def reference_points(source_vertices, ordered_stages):
    ordered_controllers = tuple(
        deform.find_controller(target, stage) for stage in ordered_stages)
    result = []
    for source in source_vertices:
        point = Vector(source)
        eligible = True
        for controller in ordered_controllers:
            properties = controller.sdh_cage_deform
            matrix = chain._stage_local_matrix(target, controller)
            local = matrix.inverted_safe() @ point
            domain_local = deform.core.chain_input_point_from_properties(
                local, properties)
            half_y = float(properties.size[1]) * 0.5
            next_eligible = eligible and domain_local.y >= half_y - 1.0e-4
            local = deform.deform_point_from_properties(
                local, properties, evaluator=True, chain_eligible=eligible)
            point = matrix @ local
            eligible = next_eligible
        result.append(point)
    return tuple(result)


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
chain = deform.chain

vertices = []
for ring in range(37):
    y = -3.0 + 6.0 * ring / 36.0
    for side in range(8):
        angle = math.tau * side / 8.0
        vertices.append((0.7 * math.cos(angle), y, 0.7 * math.sin(angle)))
mesh = bpy.data.meshes.new("Chain Stage Reorder Probe")
mesh.from_pydata(vertices, (), ())
target = bpy.data.objects.new("Chain Stage Reorder Probe", mesh)
bpy.context.collection.objects.link(target)
activate(target)

assert bpy.ops.sdh.add_cage_chain(
    count=3, connection_mode="CHAINED", gap=0.15, auto_reconnect=True,
    sync_shared_end_scale=True, alignment="POS_Y", origin="BOTTOM",
) == {"FINISHED"}
stages = chain.chain_stages(target)
controllers = tuple(deform.find_controller(target, stage) for stage in stages)
for index, controller in enumerate(controllers):
    properties = controller.sdh_cage_deform
    deform.core.set_deform_layers(
        properties, ("BEND", "TWIST", "TAPER"), bpy.context)
    properties.bend_strength = math.radians(20.0 + index * 15.0)
    properties.twist_strength = math.radians(11.0 + index * 8.0)
    properties.taper_factor = 0.08 + index * 0.04
    properties.bottom_scale = (0.9 + index * 0.07, 1.05 - index * 0.04)
    properties.top_scale = (1.08 + index * 0.06, 0.92 + index * 0.05)
    properties.bottom_offset = (index * 0.03, -index * 0.02)
    properties.top_offset = (index * 0.05, index * 0.025)
    deform.sync_controller(controller, pull_transform=False)
chain_uuid = chain.stage_chain_uuid(stages[0])
chain.reconnect_chain(target, chain_uuid)
deform.core.flush_pending_chain_updates(target)

# Add-on stack buttons: chain members keep their physical internal order.
activate(target)
target.modifiers.active = stages[1]
assert bpy.ops.sdh.move_cage_deform(
    index=1, direction="EARLIER") == {"CANCELLED"}
operator_stages = chain.chain_stages(target, chain_uuid)
operator_report = chain.validate_chain(target, chain_uuid)
operator_before = points(target)
operator_reference = reference_points(vertices, operator_stages)
operator_reference_delta = maximum(operator_before, operator_reference)
operator_after = points(target)
print("SDH_STAGE_REORDER::OPERATOR", {
    "order": tuple(item.name for item in operator_stages),
    "indices": tuple(chain.stage_chain_index(item) for item in operator_stages),
    "broken": operator_report["broken"],
    "delta": maximum(operator_before, operator_after),
    "reference_delta": operator_reference_delta,
})
assert tuple(item.name for item in operator_stages) == tuple(
    item.name for item in stages)

# Add-on stack buttons move a connected chain as one block around an unrelated
# stage, preserving the segment order and all controller frames.
legacy = target.modifiers.new("External Legacy", "SIMPLE_DEFORM")
legacy.deform_method = "TWIST"
legacy.deform_axis = "Y"
target.modifiers.active = legacy
activate(target)
all_stages = deform.deform_stack_modifiers(target)
tip_index = all_stages.index(stages[-1])
assert bpy.ops.sdh.move_cage_deform(
    index=tip_index, direction="LATER", include_legacy=True) == {"FINISHED"}
all_after_block_move = deform.deform_stack_modifiers(target)
chain_positions = [all_after_block_move.index(stage) for stage in stages]
assert chain_positions == list(range(min(chain_positions), min(chain_positions) + 3))
assert all_after_block_move[-1] == stages[-1]

# Native modifier panel path: move the new root back after the next stage.
operator_stages = chain.chain_stages(target, chain_uuid)
root_stage = operator_stages[0]
next_stage = operator_stages[1]
activate(target)
target.modifiers.active = root_stage
print("SDH_STAGE_REORDER::MODIFIERS", tuple(
    (item.name, tuple(target.modifiers).index(item), item.type)
    for item in tuple(target.modifiers)))
native_move_result = bpy.ops.object.modifier_move_to_index(
    modifier=root_stage.name,
    index=tuple(target.modifiers).index(next_stage),
)
print("SDH_STAGE_REORDER::NATIVE_MOVE", native_move_result)
if native_move_result != {"FINISHED"}:
    addon.unregister()
    raise RuntimeError("native modifier move was rejected")
native_stages = chain.chain_stages(target, chain_uuid)
native_before = chain.validate_chain(target, chain_uuid)
deform.core._CHAIN_RECONNECT_QUEUE.clear()


class _Update:
    id = target
    is_updated_transform = False
    is_updated_geometry = True
    is_updated_shading = False


class _Depsgraph:
    updates = (_Update(),)


deform.core._depsgraph_sync(None, _Depsgraph())
deform.core._drain_chain_reconnect_queue()
native_after = chain.validate_chain(target, chain_uuid)
native_points = points(target)
chain.reconnect_chain(target, chain_uuid)
native_settled = points(target)
restored_names = tuple(
    item.name for item in chain.chain_stages(target, chain_uuid))
assert restored_names == tuple(item.name for item in stages)
print("SDH_STAGE_REORDER::NATIVE", {
    "order": tuple(item.name for item in native_stages),
    "restored_order": restored_names,
    "before_broken": native_before["broken"],
    "after_broken": native_after["broken"],
    "delta": maximum(native_points, native_settled),
})

addon.unregister()
print("SDH_STAGE_REORDER::PASS")
