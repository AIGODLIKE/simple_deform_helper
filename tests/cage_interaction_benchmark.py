"""Measure chain creation and repeated controller edits.

The script is intentionally standalone so the same probe can run against the
checked-out source and an archived release tree by setting ``SDH_BENCH_SOURCE``.
It records the expensive Python reconnect path separately from a forced
Geometry Nodes evaluation; values are diagnostic, not pass/fail thresholds.
"""
from __future__ import annotations

import importlib
import json
import os
import statistics
import sys
import time
from pathlib import Path

import bpy


SOURCE = Path(os.environ.get(
    "SDH_BENCH_SOURCE",
    str(Path(__file__).resolve().parents[1]),
)).resolve()
RESULT = Path(os.environ.get(
    "SDH_BENCH_RESULT",
    str(SOURCE / "audit" / "cage_interaction_benchmark.json"),
)).resolve()
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))


def percentile(values, fraction):
    values = sorted(float(value) for value in values)
    if not values:
        return 0.0
    index = min(int(round((len(values) - 1) * fraction)), len(values) - 1)
    return values[index]


def clear_scene():
    for obj in tuple(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def create_target(name):
    bpy.ops.mesh.primitive_grid_add(
        x_subdivisions=21,
        y_subdivisions=21,
        size=4.0,
    )
    target = bpy.context.object
    target.name = name
    for selected in tuple(bpy.context.selected_objects):
        selected.select_set(False)
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    return target


def measure(function):
    started = time.perf_counter()
    result = function()
    return (time.perf_counter() - started) * 1000.0, result


def run_case(deform, count):
    clear_scene()
    target = create_target(f"SDH Interaction {count}")
    creation_ms, result = measure(lambda: bpy.ops.sdh.add_cage_chain(
        count=count,
        connection_mode="CHAINED",
        origin="BOTTOM",
        gap=0.0,
    ))
    if result != {"FINISHED"}:
        raise RuntimeError(f"chain creation failed: {result!r}")
    bpy.context.view_layer.update()
    stages = tuple(deform.cage_modifiers(target))
    root = deform.find_controller(target, stages[0])
    if root is None:
        raise RuntimeError("root controller missing")
    properties = root.sdh_cage_deform
    # Warm the interface/order caches and the chain reconnect path.
    properties.bend_strength = 0.01
    bpy.context.view_layer.update()
    deform.core._drain_chain_reconnect_queue()
    bpy.context.view_layer.update()

    edit_times = []
    reconnect_times = []
    eval_times = []
    for index in range(6):
        value = 0.03 + index * 0.01
        started = time.perf_counter()
        properties.bend_strength = value
        set_ms = (time.perf_counter() - started) * 1000.0
        started = time.perf_counter()
        bpy.context.view_layer.update()
        deform.core._drain_chain_reconnect_queue()
        reconnect_ms = (time.perf_counter() - started) * 1000.0
        started = time.perf_counter()
        target.evaluated_get(bpy.context.evaluated_depsgraph_get())
        eval_ms = (time.perf_counter() - started) * 1000.0
        edit_times.append(set_ms)
        reconnect_times.append(reconnect_ms)
        eval_times.append(eval_ms)

    def summary(values):
        return {
            "median_ms": round(statistics.median(values), 4),
            "p95_ms": round(percentile(values, 0.95), 4),
            "samples": [round(value, 4) for value in values],
        }

    return {
        "stages": count,
        "creation_ms": round(creation_ms, 4),
        "property_set": summary(edit_times),
        "reconnect_and_update": summary(reconnect_times),
        "evaluated_get": summary(eval_times),
    }


addon = importlib.import_module(PACKAGE)
entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")

try:
    records = [run_case(deform, count) for count in (2, 4, 8)]
    payload = {
        "source": str(SOURCE),
        "blender": bpy.app.version_string,
        "records": records,
    }
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("SDH_CAGE_INTERACTION_BENCHMARK::" + json.dumps(payload, sort_keys=True))
finally:
    try:
        addon.unregister()
    except Exception:
        pass
