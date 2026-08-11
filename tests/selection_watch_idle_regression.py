"""Verify that an idle empty viewport does not re-enter cage reconciliation.

The selection watcher is intentionally persistent while a managed cage exists,
because Blender can miss a few native selection notifications.  Once the
empty-selection hand-off has completed, however, the normal 120 ms tick must
remain cheap until msgbus marks a real selection change as dirty.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
ARGS = sys.argv[sys.argv.index("--") + 1:]
RESULT = Path(ARGS[0]).resolve() if ARGS else (
    SOURCE / "audit" / "selection_watch_idle_regression.txt")
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))


def fail(message):
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(f"FAIL: {message}\n", encoding="utf-8")
    raise RuntimeError(message)


addon = importlib.import_module(PACKAGE)
entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon.register()
core = importlib.import_module(f"{PACKAGE}.cage_deform.core")

saved = {
    "runtime": core._RUNTIME_HANDLERS_REGISTERED,
    "dirty": core._SELECTION_SYNC_DIRTY,
    "signature": core._SELECTION_SYNC_SIGNATURE,
    "object_count": core._ORPHAN_HELPER_OBJECT_COUNT,
}
try:
    for selected in tuple(getattr(bpy.context, "selected_objects", ()) or ()):
        selected.select_set(False)
    bpy.context.view_layer.objects.active = None
    core._RUNTIME_HANDLERS_REGISTERED = True
    core._SELECTION_SYNC_SIGNATURE = None
    core._SELECTION_SYNC_DIRTY = True
    core._ORPHAN_HELPER_OBJECT_COUNT = len(bpy.data.objects)

    # Establish the completed native empty-selection hand-off.
    core._selection_sync_timer()
    signature = core._SELECTION_SYNC_SIGNATURE
    if signature is None or signature[5]:
        fail("empty selection did not establish a stable signature")

    original_sync = core._selection_sync_timer
    calls = []
    core._selection_sync_timer = lambda: calls.append("sync")
    core._SELECTION_SYNC_DIRTY = False
    core._selection_watch_timer()
    if calls:
        fail("idle empty tick called selection sync")

    # The persistent watcher remains a fallback when Blender omits the RNA
    # notification.  A direct selection must therefore wake it even while the
    # dirty bit is false.
    bpy.ops.mesh.primitive_cube_add()
    selected = bpy.context.object
    core._ORPHAN_HELPER_OBJECT_COUNT = len(bpy.data.objects)
    core._SELECTION_SYNC_DIRTY = False
    core._selection_watch_timer()
    if calls != ["sync"]:
        fail(f"selection without msgbus notification did not wake sync: {calls!r}")
    selected.select_set(False)
    bpy.context.view_layer.objects.active = None

    # A msgbus notification must wake the full reconciliation path again.
    calls.clear()
    core._SELECTION_SYNC_DIRTY = True
    core._selection_watch_timer()
    if calls != ["sync"]:
        fail(f"dirty selection did not wake sync: {calls!r}")
    core._selection_sync_timer = original_sync

    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text("PASS::SELECTION_WATCH_IDLE\n", encoding="utf-8")
    print("PASS::SELECTION_WATCH_IDLE")
finally:
    core._selection_sync_timer = original_sync if "original_sync" in locals() else core._selection_sync_timer
    core._RUNTIME_HANDLERS_REGISTERED = saved["runtime"]
    core._SELECTION_SYNC_DIRTY = saved["dirty"]
    core._SELECTION_SYNC_SIGNATURE = saved["signature"]
    core._ORPHAN_HELPER_OBJECT_COUNT = saved["object_count"]
    try:
        addon.unregister()
    except Exception:
        pass
