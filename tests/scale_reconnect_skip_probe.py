"""Probe how much a shared end-scale edit depends on reconnect frames."""
from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))


def evaluated_points(target):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    obj = target.evaluated_get(depsgraph)
    return tuple(Vector(v.co) for v in obj.data.vertices)


def frame(stage, deform):
    names = (
        "Chain Input Pivot", "Chain Input Inverse X",
        "Chain Input Inverse Y", "Chain Input Inverse Z",
        "Chain Output Offset", "Chain Output X", "Chain Output Y",
        "Chain Output Z")
    return tuple(tuple(deform.modifier_input(stage, name)) for name in names)


def frame_affines(row):
    inp = row[:4]
    out = row[4:]
    pivot = Vector(inp[0])
    inv = __import__("mathutils").Matrix((Vector(inp[1]), Vector(inp[2]), Vector(inp[3])))
    lin = inv.inverted()
    ain = lin.to_4x4(); ain.translation = pivot - lin @ Vector((0.0, -1.0, 0.0))
    aout = __import__("mathutils").Matrix((Vector(out[1]), Vector(out[2]), Vector(out[3]))).to_4x4(); aout.translation = Vector(out[0])
    return ain, aout


addon = importlib.import_module(PACKAGE)
entry = bpy.context.preferences.addons.new(); entry.module = PACKAGE
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
chain = deform.chain
try:
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=17, y_subdivisions=33, size=4.0)
    target = bpy.context.object
    if bpy.ops.sdh.add_cage_chain(
            count=8, connection_mode="CHAINED", gap=0.15,
            auto_reconnect=True, sync_shared_end_scale=True,
            alignment="POS_Y", origin="BOTTOM") != {"FINISHED"}:
        raise RuntimeError("creation failed")
    stages = tuple(chain.chain_stages(target))
    controllers = tuple(deform.find_controller(target, s) for s in stages)
    for i, c in enumerate(controllers):
        p = c.sdh_cage_deform
        p.bend_strength = math.radians(18.0 - i * 3.0)
        p.bend_direction = math.radians(11.0)
        # Keep the baseline to the common single-Bend path for this probe.
        deform.core.set_deform_layers(p, ("BEND",), bpy.context)
        deform.sync_controller(c, pull_transform=False)
    deform.core.flush_pending_chain_updates(target)
    initial = tuple(Vector(v) for v in evaluated_points(target))
    initial_frames = tuple(frame(s, deform) for s in stages)
    root = controllers[0]
    root.sdh_cage_deform.top_scale = (2.4, 0.35)
    full = evaluated_points(target)
    full_frames = tuple(frame(s, deform) for s in stages)
    # Restore using the normal path before testing the no-reconnect variant.
    root.sdh_cage_deform.top_scale = (1.0, 1.0)
    deform.core.flush_pending_chain_updates(target)
    original = chain.reconnect_chain
    try:
        chain.reconnect_chain = lambda *args, **kwargs: 0
        root.sdh_cage_deform.top_scale = (2.4, 0.35)
        skipped = evaluated_points(target)
        skipped_frames = tuple(frame(s, deform) for s in stages)
    finally:
        chain.reconnect_chain = original
    geom_error = max((a - b).length for a, b in zip(full, skipped))
    frame_errors = [
        max((Vector(a) - Vector(b)).length for a, b in zip(full_row, skip_row))
        for full_row, skip_row in zip(full_frames, skipped_frames)]
    frame_error = max(frame_errors, default=0.0)
    print("SDH_SCALE_SKIP_PROBE::", {
        "geom_error": geom_error,
        "frame_error": frame_error,
        "frame_errors": frame_errors,
        "initial_count": len(initial),
        "full_count": len(full),
    })
    for i, (before, after) in enumerate(zip(initial_frames, full_frames)):
        bi, bo = frame_affines(before); ai, ao = frame_affines(after)
        din = bi.inverted_safe() @ ai; dout = bo.inverted_safe() @ ao
        print("FRAME_DELTA", i, "in", [round(float(din[j][j]), 6) for j in range(3)], "out", [round(float(dout[j][j]), 6) for j in range(3)])
finally:
    try:
        addon.unregister()
    except Exception:
        pass
    try:
        bpy.context.preferences.addons.remove(entry)
    except Exception:
        pass
