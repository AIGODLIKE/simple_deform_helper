"""Probe actual point continuity when a downstream CHAINED stage uses TOP."""
import importlib
import math
import sys
from pathlib import Path

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
mesh = bpy.data.meshes.new("SDH Origin Seam Probe")
source = tuple(
    Vector((x, y, z))
    for y in (-3.0, -1.5, 0.0, 1.5, 3.0)
    for x, z in ((-0.4, -0.4), (0.0, 0.0), (0.4, 0.4))
)
mesh.from_pydata(source, (), ())
target = bpy.data.objects.new("SDH Origin Seam Probe", mesh)
bpy.context.collection.objects.link(target)
bpy.ops.object.select_all(action="DESELECT")
target.select_set(True)
bpy.context.view_layer.objects.active = target
assert bpy.ops.sdh.add_cage_chain(
    count=2, connection_mode="CHAINED", gap=0.0,
    auto_reconnect=True, sync_shared_end_scale=True,
    alignment="POS_Y", origin="BOTTOM",
) == {"FINISHED"}
stages = deform.chain.chain_stages(target)
controllers = tuple(deform.find_controller(target, stage) for stage in stages)
for controller in controllers:
    props = controller.sdh_cage_deform
    props.bend_strength = 0.0
    props.twist_strength = 0.0
    props.taper_factor = 0.0
    props.stretch_factor = 0.0
    deform.sync_controller(controller, pull_transform=False)
second = controllers[1].sdh_cage_deform
second.origin = "TOP"
second.bend_strength = math.radians(60.0)
deform.sync_controller(controllers[1], pull_transform=False)
deform.core.flush_pending_chain_updates(target)
bpy.context.view_layer.update()
stage = stages[1]
modifier = stage
props = controllers[1].sdh_cage_deform
matrix = deform.chain._stage_local_matrix(target, controllers[1])
half = Vector(props.size) * 0.5
raw_local = matrix.inverted_safe() @ Vector((0.0, 0.0, 0.0))
socket_frame = tuple(Vector(deform.modifier_input(modifier, name)) for name in (
    "Chain Input Pivot", "Chain Input Inverse X",
    "Chain Input Inverse Y", "Chain Input Inverse Z",
))
delta = raw_local - socket_frame[0]
adjusted = Vector((
    delta.dot(socket_frame[1]), delta.dot(socket_frame[2]) - half.y,
    delta.dot(socket_frame[3]),
))
reference = deform.deform_point_from_properties(
    raw_local, props, evaluator=True, chain_eligible=True)
lower = Vector((0.0, -half.y, 0.0))
lower_deformed = deform.deform_point_from_properties(
    lower, props, evaluator=True, chain_eligible=True,
    apply_chain_input_offset=False)
previous_top, previous_x, previous_y, previous_z = deform.chain._stage_top_frame(
    target, controllers[0])
boundary_frame = deform.chain._local_boundary_frame(props, "BOTTOM")
print("SDH_ORIGIN_PROBE::debug", {
    "size": tuple(round(v, 6) for v in props.size),
    "pivot": tuple(round(v, 6) for v in socket_frame[0]),
    "inverse": tuple(tuple(round(v, 6) for v in row) for row in socket_frame[1:]),
    "raw_local": tuple(round(v, 6) for v in raw_local),
    "adjusted": tuple(round(v, 6) for v in adjusted),
    "reference": tuple(round(v, 6) for v in reference),
    "world_reference": tuple(round(v, 6) for v in (matrix @ reference)),
    "lower_deformed": tuple(round(v, 6) for v in lower_deformed),
    "world_lower_deformed": tuple(round(v, 6) for v in (matrix @ lower_deformed)),
    "world_lower": tuple(round(v, 6) for v in (matrix @ lower)),
    "previous_top": tuple(round(v, 6) for v in previous_top),
    "controller_location": tuple(round(v, 6) for v in controllers[1].location),
    "controller_rotation": tuple(round(v, 6) for v in controllers[1].rotation_euler),
    "frame_endpoint": tuple(round(v, 6) for v in boundary_frame[0]),
})
for sample in (Vector((-0.4, 0.0, -0.4)), Vector((0.4, 0.0, 0.4))):
    sample_raw = matrix.inverted_safe() @ sample
    sample_delta = sample_raw - socket_frame[0]
    sample_adjusted = Vector((
        sample_delta.dot(socket_frame[1]),
        sample_delta.dot(socket_frame[2]) - half.y,
        sample_delta.dot(socket_frame[3]),
    ))
    sample_out = deform.deform_point_from_properties(
        sample_adjusted, props, evaluator=True, chain_eligible=True,
        apply_chain_input_offset=False)
    print("SDH_ORIGIN_PROBE::sample", {
        "source": tuple(round(v, 6) for v in sample),
        "raw": tuple(round(v, 6) for v in sample_raw),
        "adjusted": tuple(round(v, 6) for v in sample_adjusted),
        "out": tuple(round(v, 6) for v in sample_out),
        "world_out": tuple(round(v, 6) for v in (matrix @ sample_out)),
    })
evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
try:
    actual = tuple(vertex.co.copy() for vertex in evaluated.vertices)
finally:
    target.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh_clear()
print("SDH_ORIGIN_PROBE::stages", tuple(tuple(round(v, 6) for v in c.location) for c in controllers))
seam_errors = []
for index, (before, after) in enumerate(zip(source, actual)):
    if abs(before.y) < 1.0e-6:
        seam_errors.append((after - before).length)
        print("SDH_ORIGIN_PROBE::seam", index, tuple(round(v, 6) for v in before), tuple(round(v, 6) for v in after))
maximum = max(seam_errors, default=0.0)
assert maximum < 3.0e-4, f"actual seam moved by {maximum}"
print(f"SDH_ORIGIN_PROBE::PASS::{maximum:.8f}")
addon.unregister()
bpy.data.objects.remove(target, do_unlink=True)
bpy.context.preferences.addons.remove(entry)
