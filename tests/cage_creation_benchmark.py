"""One-shot cage creation benchmark for Blender background validation."""
from __future__ import annotations

import importlib
import json
import os
import sys
import time
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
INSTALLED_PACKAGE = os.environ.get("SDH_TEST_MODULE")
PACKAGE = INSTALLED_PACKAGE or SOURCE.name
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(SOURCE.parent))
else:
    import addon_utils

    addon_utils.enable(INSTALLED_PACKAGE, default_set=False, persistent=False)


def timed(function):
    started = time.perf_counter()
    result = function()
    bpy.context.view_layer.update()
    return time.perf_counter() - started, result


def make_target(name, location):
    bpy.ops.mesh.primitive_grid_add(
        x_subdivisions=41,
        y_subdivisions=41,
        size=4.0,
        location=location,
    )
    target = bpy.context.object
    target.name = name
    return target


def activate(target):
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target


addon = importlib.import_module(PACKAGE)
if not INSTALLED_PACKAGE:
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")

for obj in tuple(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
for group in tuple(bpy.data.node_groups):
    if group.name == deform.GROUP_NAME or group.get(deform.MODIFIER_MARKER, False):
        bpy.data.node_groups.remove(group)

cold_target = make_target("Cold Standard Cage", (-5.0, 0.0, 0.0))
activate(cold_target)
cold_seconds, cold_result = timed(
    lambda: bpy.ops.sdh.add_cage_deform(cage_type="STANDARD"))
if cold_result != {"FINISHED"}:
    raise RuntimeError(f"cold Standard cage creation failed: {cold_result!r}")

warm_target = make_target("Warm Standard Cage", (0.0, 0.0, 0.0))
activate(warm_target)
warm_seconds, warm_result = timed(
    lambda: bpy.ops.sdh.add_cage_deform(cage_type="STANDARD"))
if warm_result != {"FINISHED"}:
    raise RuntimeError(f"warm Standard cage creation failed: {warm_result!r}")

chain_target = make_target("Four Stage Chain", (5.0, 0.0, 0.0))
activate(chain_target)
chain_seconds, chain_result = timed(
    lambda: bpy.ops.sdh.add_cage_chain(
        count=4,
        connection_mode="CHAINED",
        origin="BOTTOM",
        gap=0.0,
    ))
if chain_result != {"FINISHED"}:
    raise RuntimeError(f"four-stage chain creation failed: {chain_result!r}")
if cold_seconds > 2.0:
    raise RuntimeError(
        f"cold Standard cage creation exceeded 2 seconds: {cold_seconds:.3f}s")

result = {
    "cold_standard_seconds": round(cold_seconds, 6),
    "warm_standard_seconds": round(warm_seconds, 6),
    "four_stage_chain_seconds": round(chain_seconds, 6),
    "managed_groups": sum(
        1 for group in bpy.data.node_groups
        if group.get(deform.MODIFIER_MARKER, False)),
    "chain_stage_count": len(deform.cage_modifiers(chain_target)),
}
print("SDH_CAGE_CREATION_BENCHMARK::" + json.dumps(result, sort_keys=True))

if not INSTALLED_PACKAGE:
    addon.unregister()
