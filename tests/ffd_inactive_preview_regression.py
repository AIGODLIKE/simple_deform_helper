"""Verify that every inactive FFD chain stage keeps its full lattice wire."""
from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
RESULT = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))


def finish(value):
    RESULT.write_text(value, encoding="utf-8")

    def quit_blender():
        bpy.ops.wm.quit_blender()
        return None

    bpy.app.timers.register(quit_blender, first_interval=0.05)


try:
    addon = importlib.import_module(PACKAGE)
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon.register()
    cage = importlib.import_module(f"{PACKAGE}.cage_deform")
    core = importlib.import_module(f"{PACKAGE}.cage_deform.core")
    draw_module = importlib.import_module(f"{PACKAGE}.draw")
    gizmos = importlib.import_module(f"{PACKAGE}.cage_deform.gizmos")

    bpy.ops.mesh.primitive_cube_add()
    target = bpy.context.object
    result = bpy.ops.sdh.add_cage_chain(count=3, cage_type="FFD")
    if result != {"FINISHED"}:
        raise RuntimeError(f"could not create FFD chain: {result!r}")

    modifiers = tuple(cage.cage_modifiers(target))
    if len(modifiers) != 3:
        raise RuntimeError(f"expected three FFD stages, got {len(modifiers)}")
    controllers = tuple(
        cage.find_controller(target, modifier) for modifier in modifiers)
    if any(controller is None for controller in controllers):
        raise RuntimeError("could not resolve every FFD chain controller")
    for controller in controllers:
        properties = controller.sdh_cage_deform
        properties.ffd_resolution_u = 2
        properties.ffd_resolution_v = 4
        properties.ffd_resolution_w = 2
        core.ensure_ffd_point_collection(properties, preserve=False)

    active_modifier = modifiers[0]
    active_controller = controllers[0]
    target.modifiers.active = active_modifier
    active_controller.sdh_cage_deform.show_other_cages = True

    calls = []
    renderer = draw_module.Draw3D()
    renderer.draw_smooth_3d_shader_colors = (
        lambda vertices, indices, colors: calls.append(
            (tuple(vertices), tuple(indices), tuple(colors))))
    renderer._draw_other_cage_previews(
        bpy.context, target, active_modifier, active_controller)

    expected = tuple(
        gizmos.ffd_wire_geometry(
            controller.sdh_cage_deform, effective=True)
        for controller in controllers[1:])
    if len(calls) != 1:
        raise RuntimeError(
            f"expected one merged inactive FFD batch, got {len(calls)} draws")
    vertices, indices, colors = calls[0]
    expected_vertex_count = sum(len(local) for local, _edges in expected)
    expected_edge_count = sum(len(edges) for _local, edges in expected)
    if (
            len(vertices) != expected_vertex_count or
            len(indices) != expected_edge_count or
            len(colors) != expected_vertex_count
    ):
        raise RuntimeError(
            "merged FFD preview used incomplete geometry: "
            f"vertices={len(vertices)}/{expected_vertex_count}, "
            f"edges={len(indices)}/{expected_edge_count}, "
            f"colors={len(colors)}/{expected_vertex_count}")
    if any(not 0.0 < color[3] < 0.5 for color in colors):
        raise RuntimeError("merged FFD preview did not use inactive alpha")

    addon.unregister()
    finish("PASS::INACTIVE_FFD_CHAIN_GRIDS::3_STAGES")
except Exception:
    finish("FAIL:\n" + traceback.format_exc())
