"""Regression for atomic deformation-layer reordering in connected chains."""

from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))


def check(condition, message):
    if not condition:
        raise AssertionError(message)


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

vertices = []
for ring in range(49):
    y = -3.0 + 6.0 * ring / 48.0
    for side in range(8):
        angle = math.tau * side / 8.0
        vertices.append((
            0.7 * math.cos(angle),
            y,
            0.7 * math.sin(angle),
        ))

mesh = bpy.data.meshes.new("Chain Layer Reorder")
mesh.from_pydata(vertices, (), ())
target = bpy.data.objects.new("Chain Layer Reorder", mesh)
bpy.context.collection.objects.link(target)
activate(target)

check(
    bpy.ops.sdh.add_cage_chain(
        count=3,
        connection_mode="CHAINED",
        gap=0.0,
        auto_reconnect=True,
        sync_shared_end_scale=False,
        alignment="POS_Y",
        origin="BOTTOM",
    ) == {"FINISHED"},
    "could not create the connected test chain",
)

stages = chain.chain_stages(target)
controllers = tuple(deform.find_controller(target, stage) for stage in stages)
check(len(stages) == 3 and all(controllers), "test chain is incomplete")

for index, controller in enumerate(controllers):
    properties = controller.sdh_cage_deform
    check(
        deform.core.set_deform_layers(
            properties, ("BEND", "TWIST"), bpy.context),
        f"could not create the layer stack for stage {index}",
    )
    properties.bend_strength = math.radians(24.0 + index * 11.0)
    properties.twist_strength = math.radians(18.0 + index * 9.0)
    deform.sync_controller(controller, pull_transform=False)

chain_uuid = chain.stage_chain_uuid(stages[0])
chain.reconnect_chain(target, chain_uuid)
deform.core.flush_pending_chain_updates(target)

active = controllers[0]
activate(target)
target.modifiers.active = stages[0]
check(
    deform.core.move_deform_layer(
        active.sdh_cage_deform, 1, "UP", bpy.context),
    "root layer reorder was rejected",
)
immediate = evaluated_points(target)

chain.reconnect_chain(target, chain_uuid)
settled = evaluated_points(target)
maximum = max(
    ((before - after).length for before, after in zip(immediate, settled)),
    default=0.0,
)
check(
    maximum < 5.0e-4,
    f"layer reorder exposed stale downstream chain frames: {maximum}",
)

check(
    deform.core.ordered_deform_types(active.sdh_cage_deform) ==
    ("TWIST", "BEND"),
    "authored layer order was not retained",
)

addon.unregister()
print(f"SDH_CHAIN_LAYER_REORDER::PASS::{maximum:.7f}")
