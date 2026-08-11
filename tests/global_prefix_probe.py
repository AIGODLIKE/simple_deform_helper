"""Inspect analytic pre-Bend subdivision metadata and socket deltas."""

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


def evaluated_points(obj):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return tuple(vertex.co.copy() for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
chain = deform.chain

vertices = tuple(
    (0.55 * math.cos(math.tau * side / 8), y,
     0.35 * math.sin(math.tau * side / 8))
    for y in (-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0)
    for side in range(8)
)
mesh = bpy.data.meshes.new("SDH Prefix Probe Mesh")
mesh.from_pydata(vertices, (), ())
target = bpy.data.objects.new("SDH Prefix Probe", mesh)
bpy.context.collection.objects.link(target)
activate(target)

modifier, controller, _previous = deform.create_deform_stage(
    bpy.context, target)
properties = controller.sdh_cage_deform
properties.size = (2.2, 6.0, 1.8)
properties.mode = "LIMITED"
properties.origin = "BOTTOM"
properties.bend_direction = math.radians(23.0)
properties.bend_strength = math.radians(74.0)
properties.twist_strength = math.radians(-39.0)
deform.core.set_deform_layers(
    properties, ("TWIST", "BEND"), bpy.context)
deform.sync_controller(controller, pull_transform=False)
before = evaluated_points(target)

target.modifiers.active = modifier
result = bpy.ops.sdh.subdivide_cage_to_chain(
    count=3, gap=0.0, auto_reconnect=True,
    sync_shared_end_scale=True,
    allow_mixed_bend_approximation=True,
)
deform.core.flush_pending_chain_updates(target)
stages = tuple(chain.chain_stages(target))
controllers = tuple(deform.find_controller(target, stage) for stage in stages)

print("SDH_PREFIX::OPERATOR", result)
for index, (stage, item) in enumerate(zip(stages, controllers)):
    values = deform.core._chain_domain_input_values(item, stage)
    print("SDH_PREFIX::STAGE", index, {
        "properties_twist": item.sdh_cage_deform.twist_strength,
        "base_twist": values["Chain Prefix Base Twist"],
        "socket_twist": deform.core.modifier_input(stage, "Twist Angle"),
        "prefix_active": values["Chain Global Prefix Active"],
        "prefix_mask": values["Chain Global Prefix Types"],
        "prefix_twist": values["Chain Global Prefix Twist"],
        "prefix_socket_active": deform.core.modifier_input(
            stage, "Chain Global Prefix Active"),
        "prefix_socket_mask": deform.core.modifier_input(
            stage, "Chain Global Prefix Types"),
        "prefix_socket_twist": deform.core.modifier_input(
            stage, "Chain Global Prefix Twist"),
        "input_frame": tuple(tuple(value) for value in
                             deform.core.chain_input_frame_for_controller(
                                 item, stage, item.sdh_cage_deform)),
        "output_frame": tuple(tuple(value) for value in
                              deform.core.chain_output_frame_for_controller(
                                  item, stage, item.sdh_cage_deform)),
    })

after = evaluated_points(target)
python_after = []
matrices = tuple(chain._stage_local_matrix(target, item)
                 for item in controllers)
starts = tuple(
    deform.core._chain_domain_input_values(item, stage)["Chain Source Start"]
    for item, stage in zip(controllers, stages)
)
for source in vertices:
    point = Vector(source)
    source_coordinate = (matrices[0].inverted_safe() @ point).y
    for index, (stage, item, matrix, start) in enumerate(
            zip(stages, controllers, matrices, starts)):
        local = matrix.inverted_safe() @ point
        point = matrix @ deform.deform_point_from_properties(
            local, item.sdh_cage_deform, evaluator=True,
            chain_eligible=(index == 0 or source_coordinate >= start - 1.0e-5),
            chain_source_coordinate=source_coordinate,
            chain_source_start=start,
        )
    python_after.append(point)

print("SDH_PREFIX::MAX_GN", max(
    (actual - expected).length for actual, expected in zip(after, before)))
print("SDH_PREFIX::MAX_PYTHON", max(
    (actual - expected).length
    for actual, expected in zip(python_after, before)))
print("SDH_PREFIX::MAX_PARITY", max(
    (actual - expected).length
    for actual, expected in zip(python_after, after)))
for ring, y in enumerate((-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0)):
    start = ring * 8
    print("SDH_PREFIX::RING", y, max(
        (actual - expected).length
        for actual, expected in zip(
            after[start:start + 8], before[start:start + 8])))

addon.unregister()
bpy.context.preferences.addons.remove(entry)
