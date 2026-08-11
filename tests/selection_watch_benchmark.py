"""Measure idle selection-watch cost with a managed chain present.

This is diagnostic rather than a threshold test.  ``legacy_sync_ms_per_tick``
measures the full empty-selection reconciliation that the watcher used to run
on every tick; ``watch_ms_per_tick`` measures the new idle fast path.
"""
from __future__ import annotations

import importlib
import json
import statistics
import sys
import time
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
ARGS = sys.argv[sys.argv.index("--") + 1:]
RESULT = Path(ARGS[0]).resolve() if ARGS else (
    SOURCE / "audit" / "selection_watch_benchmark.json")
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))


def percentile(values, fraction):
    values = sorted(values)
    return values[min(int(round((len(values) - 1) * fraction)), len(values) - 1)]


def clear_scene():
    for obj in tuple(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


addon = importlib.import_module(PACKAGE)
entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon.register()
core = importlib.import_module(f"{PACKAGE}.cage_deform.core")

try:
    clear_scene()
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=17, y_subdivisions=17)
    target = bpy.context.object
    bpy.ops.sdh.add_cage_chain(
        count=8, connection_mode="CHAINED", origin="BOTTOM", gap=0.0)
    for selected in tuple(getattr(bpy.context, "selected_objects", ()) or ()):
        selected.select_set(False)
    bpy.context.view_layer.objects.active = None
    core._RUNTIME_HANDLERS_REGISTERED = True
    core._SELECTION_SYNC_DIRTY = True
    core._SELECTION_SYNC_SIGNATURE = None
    core._ORPHAN_HELPER_OBJECT_COUNT = len(bpy.data.objects)
    core._selection_sync_timer()

    # Warm Blender/RNA wrappers before measuring.
    for _index in range(8):
        core._selection_watch_timer()

    original_sync = core._selection_sync_timer
    calls = {"count": 0}

    def count_sync():
        calls["count"] += 1
        return original_sync()

    core._selection_sync_timer = count_sync
    watch_samples = []
    for _index in range(120):
        started = time.perf_counter()
        core._selection_watch_timer()
        watch_samples.append((time.perf_counter() - started) * 1000.0)
    idle_sync_calls = calls["count"]

    # Approximate the pre-optimization watcher by directly invoking the old
    # full reconciliation path for the same empty-selection state.
    legacy_samples = []
    core._selection_sync_timer = original_sync
    for _index in range(24):
        core._SELECTION_SYNC_DIRTY = True
        started = time.perf_counter()
        original_sync()
        legacy_samples.append((time.perf_counter() - started) * 1000.0)

    payload = {
        "blender": bpy.app.version_string,
        "chain_stages": 8,
        "watch_samples": len(watch_samples),
        "watch_ms_per_tick_median": round(statistics.median(watch_samples), 6),
        "watch_ms_per_tick_p95": round(percentile(watch_samples, 0.95), 6),
        "legacy_sync_samples": len(legacy_samples),
        "legacy_sync_ms_per_tick_median": round(
            statistics.median(legacy_samples), 6),
        "legacy_sync_ms_per_tick_p95": round(
            percentile(legacy_samples, 0.95), 6),
        "idle_sync_calls": idle_sync_calls,
    }
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("SDH_SELECTION_WATCH_BENCHMARK::" + json.dumps(payload, sort_keys=True))
finally:
    try:
        core._selection_sync_timer = original_sync
    except (NameError, AttributeError):
        pass
    try:
        addon.unregister()
    except Exception:
        pass
