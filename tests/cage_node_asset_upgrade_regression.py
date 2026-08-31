"""Ensure old managed stages migrate from one packaged GN template load."""
from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))


def check(condition, message):
    if not condition:
        raise AssertionError(message)


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
core = deform.core

for obj in tuple(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
for group in tuple(bpy.data.node_groups):
    bpy.data.node_groups.remove(group)

build_calls = 0
load_calls = 0
original_build = core.build_node_group
original_load = core._load_packaged_node_group


def tracked_build(node_group):
    global build_calls
    build_calls += 1
    return original_build(node_group)


def tracked_load():
    global load_calls
    load_calls += 1
    return original_load()


core.build_node_group = tracked_build
core._load_packaged_node_group = tracked_load
try:
    template = core.ensure_node_group()
    check(build_calls == 0, "current packaged asset fell back to Python build")
    check(load_calls == 1, f"initial template loaded {load_calls} times")
    check(int(template.get(core.GROUP_MARKER, 0)) == core.GROUP_VERSION,
          "packaged template has the wrong schema")
    check(core.ensure_node_group() == template and load_calls == 1,
          "warm template lookup reloaded the packaged asset")

    bpy.ops.mesh.primitive_cube_add()
    target = bpy.context.object
    previous = None
    records = []
    for index in range(4):
        modifier, controller, _old_previous = deform.create_deform_stage(
            bpy.context,
            target,
            name=f"Asset Upgrade {index + 1}",
            after_modifier=previous,
            node_group_template=template,
        )
        properties = controller.sdh_cage_deform
        properties.bend_strength = 0.2 + index * 0.11
        properties.top_offset = (index * 0.03, -index * 0.02)
        deform.sync_controller(controller, pull_transform=False)
        group = modifier.node_group
        marker = f"stage-{index}"
        group["_sdh_asset_upgrade_probe"] = marker
        records.append((
            modifier,
            str(group.get(core.MODIFIER_UUID, "")),
            marker,
            float(core.modifier_input(modifier, "Bend Angle")),
            tuple(core.modifier_input(modifier, "Top Offset")),
        ))
        group[core.GROUP_MARKER] = core.GROUP_VERSION - 1
        previous = modifier

    # Reproduce a saved file that contains an obsolete hidden template beside
    # its old stage groups. The new template will receive a numeric name suffix;
    # subsequent lookups must still find it without another library load.
    bpy.data.node_groups.remove(template)
    stale_template = bpy.data.node_groups.new(
        core.GROUP_RUNTIME_NAME, "GeometryNodeTree")
    stale_template[core.GROUP_MARKER] = core.GROUP_VERSION - 1
    stale_template.use_fake_user = True
    load_calls = 0

    started = time.perf_counter()
    upgraded = core.upgrade_managed_stages()
    elapsed = time.perf_counter() - started
    check(upgraded == len(records),
          f"upgraded {upgraded} stages, expected {len(records)}")
    check(build_calls == 0,
          f"stage migration called Python graph builder {build_calls} times")
    check(load_calls == 1,
          f"stage migration loaded packaged asset {load_calls} times")

    for modifier, expected_uuid, marker, bend, top_offset in records:
        group = modifier.node_group
        check(int(group.get(core.GROUP_MARKER, 0)) == core.GROUP_VERSION,
              f"{modifier.name} kept an obsolete schema")
        check(str(group.get(core.MODIFIER_UUID, "")) == expected_uuid,
              f"{modifier.name} lost its UUID")
        check(str(group.get("_sdh_asset_upgrade_probe", "")) == marker,
              f"{modifier.name} lost persistent group metadata")
        check(abs(float(core.modifier_input(
            modifier, "Bend Angle")) - bend) < 1.0e-6,
            f"{modifier.name} lost its Bend input")
        restored_offset = tuple(core.modifier_input(modifier, "Top Offset"))
        check(max(abs(float(a) - float(b))
                  for a, b in zip(restored_offset, top_offset)) < 1.0e-6,
              f"{modifier.name} lost its Top Offset input")

    warm_template = core.ensure_node_group()
    check(int(warm_template.get(core.GROUP_MARKER, 0)) == core.GROUP_VERSION,
          "warm lookup returned the obsolete runtime template")
    check(core.ensure_node_group() == warm_template and load_calls == 1,
          "suffixed runtime template caused repeated packaged loads")
    print(
        "SDH_CAGE_NODE_ASSET_UPGRADE::PASS::"
        f"stages={upgraded}::loads={load_calls}::builds={build_calls}::"
        f"seconds={elapsed:.6f}")
finally:
    core.build_node_group = original_build
    core._load_packaged_node_group = original_load
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
