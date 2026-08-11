"""Create a saved chain scene with a caller-supplied historical add-on tree."""

from __future__ import annotations

import importlib
import math
import os
import sys
from pathlib import Path

import bpy


ADDON_ROOT = Path(os.environ["SDH_HISTORICAL_ADDON_ROOT"]).resolve()
OUTPUT = Path(os.environ["SDH_MIGRATION_FIXTURE_OUTPUT"]).resolve()
PACKAGE = ADDON_ROOT.name
sys.path.insert(0, str(ADDON_ROOT.parent))

SOURCE_MIN = -3.0
SOURCE_MAX = 3.0
SOURCE_RADIUS = 0.65
RING_SIDES = 12
DENSE_STEP = 0.05
LIMIT_STEP = 0.005

FIXTURES = (
    ("2 gap0 center bend", 2, 0.0, ("CENTER", "CENTER"), "BEND"),
    ("2 gap04 center bend", 2, 0.4, ("CENTER", "CENTER"), "BEND"),
    ("2 gap04 top bend", 2, 0.4, ("TOP", "TOP"), "BEND"),
    ("2 gap04 mixed bend twist", 2, 0.4,
     ("BOTTOM", "TOP"), "BEND_TWIST"),
    ("3 gap0 center bend", 3, 0.0,
     ("CENTER", "CENTER", "CENTER"), "BEND"),
    ("3 gap04 center bend", 3, 0.4,
     ("CENTER", "CENTER", "CENTER"), "BEND"),
    ("3 gap04 top bend", 3, 0.4,
     ("TOP", "TOP", "TOP"), "BEND"),
    ("3 gap04 mixed bend twist", 3, 0.4,
     ("BOTTOM", "TOP", "CENTER"), "BEND_TWIST"),
)


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def boundaries_for(count, gap):
    segment = ((SOURCE_MAX - SOURCE_MIN) - gap * (count - 1)) / count
    return tuple(
        SOURCE_MIN + index * segment + index * gap
        for index in range(1, count)
    )


def y_values(boundaries):
    steps = int(round((SOURCE_MAX - SOURCE_MIN) / DENSE_STEP))
    values = {
        round(SOURCE_MIN + (SOURCE_MAX - SOURCE_MIN) * index / steps, 10)
        for index in range(steps + 1)
    }
    for boundary in boundaries:
        for offset in range(-3, 4):
            values.add(round(boundary + offset * LIMIT_STEP, 10))
    return tuple(sorted(values))


def make_target(name, boundaries):
    vertices = []
    for y in y_values(boundaries):
        vertices.append((0.0, y, 0.0))
        for side in range(RING_SIDES):
            angle = math.tau * side / RING_SIDES
            vertices.append((
                SOURCE_RADIUS * math.cos(angle), y,
                SOURCE_RADIUS * math.sin(angle),
            ))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, (), ())
    target = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(target)
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    return target


def configure(deform, controllers, pattern, config):
    bend_angles = (math.radians(48.0), math.radians(-37.0), math.radians(55.0))
    bend_directions = (math.radians(17.0), math.radians(-29.0), math.radians(43.0))
    twist_angles = (math.radians(31.0), math.radians(-46.0), math.radians(27.0))
    layers = ("BEND",) if config == "BEND" else ("BEND", "TWIST")
    for index, (controller, origin) in enumerate(zip(controllers, pattern)):
        properties = controller.sdh_cage_deform
        deform.core.set_deform_layers(properties, layers, bpy.context)
        properties.origin = origin
        properties.bend_strength = bend_angles[index]
        properties.bend_direction = bend_directions[index]
        properties.twist_strength = (
            0.0 if config == "BEND" else twist_angles[index])
        properties.taper_factor = 0.0
        properties.stretch_factor = 0.0
        properties.top_scale = (1.0, 1.0)
        properties.bottom_scale = (1.0, 1.0)
        properties.top_offset = (0.0, 0.0)
        properties.bottom_offset = (0.0, 0.0)
        deform.sync_controller(controller, pull_transform=False)


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
chain = deform.chain

created = []
for label, count, gap, pattern, config in FIXTURES:
    boundaries = boundaries_for(count, gap)
    target = make_target(f"SDH Migration {label}", boundaries)
    result = bpy.ops.sdh.add_cage_chain(
        count=count,
        connection_mode="CHAINED",
        gap=gap,
        auto_reconnect=True,
        sync_shared_end_scale=True,
        alignment="POS_Y",
        origin=pattern[0],
    )
    check(result == {"FINISHED"}, f"could not create {label}")
    stages = chain.chain_stages(target)
    controllers = tuple(deform.find_controller(target, stage) for stage in stages)
    check(len(controllers) == count and all(controllers),
          f"incomplete fixture {label}")
    configure(deform, controllers, pattern, config)
    deform.core.flush_pending_chain_updates(target)
    target["_sdh_migration_fixture"] = True
    target["_sdh_probe_count"] = count
    target["_sdh_probe_gap"] = gap
    target["_sdh_probe_pattern"] = "|".join(pattern)
    target["_sdh_probe_config"] = config
    target["_sdh_probe_creation_origin"] = pattern[0]
    created.append(target)

bpy.context.view_layer.update()
markers = tuple(sorted({
    int(modifier.node_group.get(deform.GROUP_MARKER, -1))
    for target in created
    for modifier in target.modifiers
    if deform.is_cage_modifier(modifier)
}))
groups = tuple({
    modifier.node_group
    for target in created
    for modifier in target.modifiers
    if deform.is_cage_modifier(modifier)
})
print("SDH_MIGRATION_FIXTURE::SOURCE", str(ADDON_ROOT))
print("SDH_MIGRATION_FIXTURE::GROUP_VERSION", deform.GROUP_VERSION)
print("SDH_MIGRATION_FIXTURE::MARKERS", markers)
print("SDH_MIGRATION_FIXTURE::GROUPS", len(groups))
print("SDH_MIGRATION_FIXTURE::TARGETS", len(created))

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
result = bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT), check_existing=False)
check(result == {"FINISHED"}, f"could not save fixture to {OUTPUT}")
print("SDH_MIGRATION_FIXTURE::SAVED", str(OUTPUT))
