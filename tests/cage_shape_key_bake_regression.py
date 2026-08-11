"""Regression for baking evaluated cage animation to absolute shape keys."""
from __future__ import annotations

import importlib
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
INSTALLED_PACKAGE = os.environ.get("SDH_TEST_MODULE")
PACKAGE = INSTALLED_PACKAGE or SOURCE.name
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(SOURCE.parent))


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


def strip_mesh(name, ring_count=9):
    vertices = []
    faces = []
    for ring in range(ring_count):
        z = -2.0 + 4.0 * ring / (ring_count - 1)
        vertices.extend((
            (-0.5, -0.25, z),
            (0.5, -0.25, z),
            (0.5, 0.25, z),
            (-0.5, 0.25, z),
        ))
    faces.append((0, 3, 2, 1))
    for ring in range(ring_count - 1):
        first = ring * 4
        second = first + 4
        for side in range(4):
            next_side = (side + 1) % 4
            faces.append((
                first + side,
                first + next_side,
                second + next_side,
                second + side,
            ))
    last = (ring_count - 1) * 4
    faces.append((last, last + 1, last + 2, last + 3))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, (), faces)
    mesh.update()
    return mesh


addon = importlib.import_module(PACKAGE)
if not INSTALLED_PACKAGE:
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")

source = bpy.data.objects.new("SDH Bake Source", strip_mesh("SDH Bake Source"))
bpy.context.collection.objects.link(source)
activate(source)
if bpy.ops.sdh.add_cage_deform(cage_type="STANDARD") != {"FINISHED"}:
    raise AssertionError("could not add the source cage")
target, modifier, controller = deform.resolve_context_deform(bpy.context)
if target != source or modifier is None or controller is None:
    raise AssertionError("could not resolve the source cage")

properties = controller.sdh_cage_deform
properties.mode = "UNLIMITED"
properties.origin = "BOTTOM"
for frame, angle in ((1, 0.0), (4, 55.0), (8, 115.0)):
    properties.bend_strength = math.radians(angle)
    controller.keyframe_insert(
        data_path="sdh_cage_deform.bend_strength",
        frame=frame,
    )

scene = bpy.context.scene
scene.frame_start = 1
scene.frame_end = 8
expected_points = {}
for frame in range(scene.frame_start, scene.frame_end + 1):
    scene.frame_set(frame)
    deform.core._frame_change_sync(scene)
    expected_points[frame] = evaluated_points(source)
if max(
        (first - second).length
        for first, second in zip(expected_points[1], expected_points[8])) < 0.1:
    raise AssertionError("source fixture did not produce animated geometry")
scene.frame_set(3)
activate(source)
source.modifiers.active = modifier
result = bpy.ops.sdh.bake_cage_animation(
    frame_start=1,
    frame_end=8,
    step=1,
    result_name="SDH Baked Shape Animation",
    hide_source=False,
)
if result != {"FINISHED"}:
    raise AssertionError(f"bake operator failed: {result!r}")
if scene.frame_current != 3:
    raise AssertionError("bake did not restore the original scene frame")

baked = next(
    (obj for obj in bpy.data.objects
     if bool(obj.get("_sdh_baked_cage_animation", False))),
    None,
)
if baked is None:
    raise AssertionError("bake did not create a marked result object")
if baked.type != "MESH" or tuple(baked.modifiers):
    raise AssertionError("baked result is not an independent modifier-free mesh")
shape_keys = baked.data.shape_keys
if shape_keys is None or shape_keys.use_relative:
    raise AssertionError("baked result does not use absolute shape keys")
if len(shape_keys.key_blocks) != 8:
    raise AssertionError(
        f"expected 8 sampled shape keys, got {len(shape_keys.key_blocks)}")
if tuple(key.name for key in shape_keys.key_blocks) != (
        "Basis", "Frame 2", "Frame 3", "Frame 4",
        "Frame 5", "Frame 6", "Frame 7", "Frame 8"):
    raise AssertionError("baked shape-key names do not match sampled frames")

action = shape_keys.animation_data.action if shape_keys.animation_data else None
curves = tuple(deform.core._iter_baked_action_fcurves(action))
eval_curves = tuple(
    curve for curve in curves if curve.data_path == "eval_time")
if len(eval_curves) != 1 or len(eval_curves[0].keyframe_points) != 8:
    raise AssertionError("absolute shape-key evaluation curve is incomplete")
if any(
        point.interpolation != "LINEAR"
        for point in eval_curves[0].keyframe_points):
    raise AssertionError("absolute shape-key evaluation is not linear")

maximum_error = 0.0
for frame in (1, 2, 4, 6, 8):
    scene.frame_set(frame)
    source_points = expected_points[frame]
    baked_points = evaluated_points(baked)
    if len(source_points) != len(baked_points):
        raise AssertionError(f"vertex count changed at frame {frame}")
    maximum_error = max(
        maximum_error,
        max(
            (Vector(first) - Vector(second)).length
            for first, second in zip(source_points, baked_points)
        ),
    )
if maximum_error > 2.0e-5:
    raise AssertionError(
        f"baked geometry differs from source by {maximum_error:.8f}")

print(
    "SDH_CAGE_SHAPE_KEY_BAKE::PASS::"
    f"keys={len(shape_keys.key_blocks)}::error={maximum_error:.8f}"
)
if not INSTALLED_PACKAGE:
    addon.unregister()
