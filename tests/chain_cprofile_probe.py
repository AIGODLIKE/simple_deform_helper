"""Profile repeated chained-cage edits without changing add-on behavior."""
from __future__ import annotations

import cProfile
import importlib
import pstats
import sys
from io import StringIO
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))


def clear_scene():
    for obj in tuple(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


clear_scene()
bpy.ops.mesh.primitive_grid_add(x_subdivisions=21, y_subdivisions=21, size=4.0)
target = bpy.context.object
target.name = "SDH Chain Profile"
bpy.context.view_layer.objects.active = target
target.select_set(True)

addon = importlib.import_module(PACKAGE)
entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")

try:
    result = bpy.ops.sdh.add_cage_chain(
        count=8,
        connection_mode="CHAINED",
        origin="BOTTOM",
        gap=0.0,
    )
    if result != {"FINISHED"}:
        raise RuntimeError(f"chain creation failed: {result!r}")
    root = deform.find_controller(target, deform.cage_modifiers(target)[0])
    properties = root.sdh_cage_deform
    properties.bend_strength = 0.01
    bpy.context.view_layer.update()
    deform.core._drain_chain_reconnect_queue()
    bpy.context.view_layer.update()

    profile = cProfile.Profile()
    profile.enable()
    for index in range(6):
        properties.bend_strength = 0.03 + index * 0.01
        bpy.context.view_layer.update()
        deform.core._drain_chain_reconnect_queue()
        bpy.context.view_layer.update()
    profile.disable()

    stream = StringIO()
    pstats.Stats(profile, stream=stream).sort_stats("cumulative").print_stats(45)
    print("SDH_CHAIN_CPROFILE::BEGIN")
    print(stream.getvalue())
    print("SDH_CHAIN_CPROFILE::END")
finally:
    try:
        addon.unregister()
    except Exception:
        pass
