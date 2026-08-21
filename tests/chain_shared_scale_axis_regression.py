"""Keep direct-chain cage previews continuous at synchronized scaled seams."""
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
TOLERANCE = 5.0e-4


def fail(message):
    raise AssertionError(message)


def activate(target):
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target


def make_target(name, alignment):
    mesh = bpy.data.meshes.new(f"{name} Mesh")
    vertices = []
    for longitudinal in (-3.0, -1.0, 1.0, 3.0):
        for first, second in (
                (-0.6, -0.4), (-0.6, 0.4),
                (0.6, -0.4), (0.6, 0.4)):
            vertices.append(
                (first, longitudinal, second)
                if alignment == "POS_Y" else
                (first, second, longitudinal)
            )
    mesh.from_pydata(vertices, (), ())
    target = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(target)
    activate(target)
    return target


def preview_corner(deform, target, controller, side, x_sign, z_sign):
    properties = controller.sdh_cage_deform
    half = Vector(properties.size) * 0.5
    preview_state = deform.gizmos.cage_preview_geometry_state(properties)
    local = deform.core.deform_point_for_display(
        (
            x_sign * half.x,
            half.y if side == "TOP" else -half.y,
            z_sign * half.z,
        ),
        properties,
        preview_output_frame=preview_state[1],
    )
    return deform.cage_local_matrix(target, controller) @ Vector(local)


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")

targets = []
try:
    reports = {}
    for alignment in ("POS_Y", "POS_Z"):
        target = make_target(
            f"SDH Shared Scale {alignment} Regression", alignment)
        targets.append(target)
        result = bpy.ops.sdh.add_cage_chain(
            count=3,
            connection_mode="CHAINED",
            gap=0.0,
            auto_reconnect=True,
            sync_shared_end_scale=True,
            alignment=alignment,
            origin="BOTTOM",
        )
        if result != {"FINISHED"}:
            fail(f"{alignment} chain creation failed: {result!r}")
        stages = tuple(deform.chain.chain_stages(target))
        controllers = tuple(
            deform.find_controller(target, stage) for stage in stages)
        if len(controllers) != 3 or not all(controllers):
            fail(f"{alignment} chain is incomplete")

        for controller in controllers:
            properties = controller.sdh_cage_deform
            properties.bend_strength = math.radians(15.0)
            properties.bend_direction = 0.0
            deform.sync_controller(controller, pull_transform=False)
        controllers[0].sdh_cage_deform.top_scale = (1.45, 0.75)
        controllers[1].sdh_cage_deform.top_scale = (0.85, 1.35)
        controllers[2].sdh_cage_deform.top_scale = (0.85, 1.35)
        deform.core.flush_pending_chain_updates(target)

        maximum = 0.0
        for index in range(1, len(controllers)):
            previous = controllers[index - 1]
            current = controllers[index]
            for x_sign, z_sign in (
                    (-1.0, -1.0), (-1.0, 1.0),
                    (1.0, -1.0), (1.0, 1.0)):
                upstream = preview_corner(
                    deform, target, previous, "TOP", x_sign, z_sign)
                downstream = preview_corner(
                    deform, target, current, "BOTTOM", x_sign, z_sign)
                maximum = max(maximum, (upstream - downstream).length)
        reports[alignment] = maximum
        if maximum > TOLERANCE:
            fail(
                f"{alignment} synchronized cage previews separate at the "
                f"shared seam: {maximum}")

    print(f"SDH_CHAIN_SHARED_SCALE_AXIS::{reports!r}::PASS")
finally:
    for target in targets:
        if target.name in bpy.data.objects:
            mesh = target.data
            bpy.data.objects.remove(target, do_unlink=True)
            if mesh is not None and mesh.name in bpy.data.meshes:
                bpy.data.meshes.remove(mesh)
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
