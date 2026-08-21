"""Keep a shared end-scale Gizmo edit local to its two neighboring cages."""
from __future__ import annotations

import importlib
import math
import os
import sys
import traceback
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
INSTALLED_PACKAGE = os.environ.get("SDH_TEST_MODULE")
PACKAGE = INSTALLED_PACKAGE or SOURCE.name
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(SOURCE.parent))


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def make_target(name):
    vertices = []
    source_y = []
    for ring in range(33):
        y = -4.0 + 8.0 * ring / 32.0
        for side in range(8):
            angle = math.tau * side / 8.0
            vertices.append((0.65 * math.cos(angle), y, 0.65 * math.sin(angle)))
            source_y.append(y)
    mesh = bpy.data.meshes.new(f"{name} Mesh")
    mesh.from_pydata(vertices, (), ())
    target = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(target)
    activate(target)
    return target, tuple(source_y)


def evaluated_points(target):
    bpy.context.view_layer.update()
    evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return tuple(vertex.co.copy() for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def scale_state(controllers):
    return tuple(
        {
            "bottom": tuple(round(float(value), 6) for value in controller.sdh_cage_deform.bottom_scale),
            "top": tuple(round(float(value), 6) for value in controller.sdh_cage_deform.top_scale),
        }
        for controller in controllers
    )


def max_delta_by_stage(before, after, source_y):
    maxima = [0.0, 0.0, 0.0, 0.0]
    for first, second, y in zip(before, after, source_y):
        index = min(max(int((y + 4.0) // 2.0), 0), 3)
        maxima[index] = max(maxima[index], (second - first).length)
    return tuple(maxima)


addon = importlib.import_module(PACKAGE)
entry = None
if not INSTALLED_PACKAGE:
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")


def run_case(side):
    target, source_y = make_target(f"SDH End Scale {side} Scope")
    result = bpy.ops.sdh.add_cage_chain(
        count=4,
        cage_type="STANDARD",
        connection_mode="CHAINED",
        gap=0.0,
        auto_reconnect=True,
        sync_shared_end_scale=True,
        alignment="POS_Y",
        origin="BOTTOM",
    )
    check(result == {"FINISHED"}, f"{side} chain creation failed")
    stages = tuple(deform.chain.chain_stages(target))
    controllers = tuple(deform.find_controller(target, stage) for stage in stages)
    check(len(controllers) == 4 and all(controllers), f"{side} chain is incomplete")

    for controller, bend in zip(controllers, (28.0, -22.0, 17.0, -11.0)):
        controller.sdh_cage_deform.bend_strength = math.radians(bend)
        deform.sync_controller(controller, pull_transform=False)
    controllers[0].sdh_cage_deform.bottom_scale = (0.9, 1.1)
    controllers[0].sdh_cage_deform.top_scale = (1.15, 0.85)
    controllers[1].sdh_cage_deform.top_scale = (0.8, 1.2)
    controllers[2].sdh_cage_deform.top_scale = (1.3, 0.7)
    controllers[3].sdh_cage_deform.top_scale = (1.05, 0.95)
    deform.core.flush_pending_chain_updates(target)

    before_state = scale_state(controllers)
    before_points = evaluated_points(target)
    if side == "BOTTOM":
        controllers[1].sdh_cage_deform.bottom_scale = (1.55, 0.65)
        expected_properties = ["0.top", "1.bottom"]
        affected = (0, 1)
        unrelated = (2, 3)
    else:
        controllers[1].sdh_cage_deform.top_scale = (1.48, 0.62)
        expected_properties = ["1.top", "2.bottom"]
        affected = (1, 2)
        unrelated = (0, 3)
    immediate_state = scale_state(controllers)
    immediate_points = evaluated_points(target)

    deform.sync_controller(controllers[-1], pull_transform=False)
    deform.core.flush_pending_chain_updates(target)
    settled_state = scale_state(controllers)
    settled_points = evaluated_points(target)

    changed = []
    for index, (before, after) in enumerate(zip(before_state, immediate_state)):
        for end in ("bottom", "top"):
            if before[end] != after[end]:
                changed.append(f"{index}.{end}")
    source_delta = max_delta_by_stage(before_points, immediate_points, source_y)
    settle_delta = max_delta_by_stage(immediate_points, settled_points, source_y)
    check(changed == expected_properties,
          f"{side} edit changed unrelated properties: {changed!r}")
    check(all(source_delta[index] > 1.0e-3 for index in affected),
          f"{side} edit did not affect both seam participants: {source_delta!r}")
    check(all(source_delta[index] < 5.0e-5 for index in unrelated),
          f"{side} edit leaked into unrelated cages: {source_delta!r}")
    check(max(settle_delta) < 5.0e-5,
          f"{side} edit left a delayed downstream update: {settle_delta!r}")
    check(immediate_state == settled_state,
          f"{side} properties changed after the callback settled")
    check(not deform.core._CHAIN_RECONNECT_QUEUE,
          f"{side} edit left a pending reconnect")
    return {
        "changed": changed,
        "source_delta": tuple(round(value, 7) for value in source_delta),
        "settle_delta": tuple(round(value, 7) for value in settle_delta),
    }


try:
    reports = {side: run_case(side) for side in ("BOTTOM", "TOP")}
    print(f"SDH_CHAIN_END_SCALE_SCOPE::{reports!r}::PASS")
except Exception:
    traceback.print_exc()
    raise
finally:
    if entry is not None:
        addon.unregister()
        bpy.context.preferences.addons.remove(entry)
