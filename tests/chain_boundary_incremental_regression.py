"""Compare incremental modal boundary propagation with the safe full path."""
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


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def make_target(name):
    vertices = []
    for ring in range(33):
        y = -4.0 + 8.0 * ring / 32.0
        for side in range(8):
            angle = math.tau * side / 8.0
            vertices.append((0.7 * math.cos(angle), y,
                             0.7 * math.sin(angle)))
    mesh = bpy.data.meshes.new(f"{name} Mesh")
    mesh.from_pydata(vertices, (), ())
    target = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(target)
    activate(target)
    return target


def numeric_state(target, chain, deform):
    stages = tuple(chain.chain_stages(target))
    values = []
    for stage in stages:
        controller = deform.find_controller(target, stage)
        props = controller.sdh_cage_deform
        values.extend(tuple(float(value) for value in props.size))
        values.extend(tuple(float(value) for value in controller.location))
        rotation = controller.matrix_basis.to_3x3()
        values.extend(
            float(rotation[row][column])
            for row in range(3) for column in range(3)
        )
        values.extend((float(chain.stage_chain_gap(stage)),))
    return tuple(values)


def labeled_state(target, chain, deform):
    stages = tuple(chain.chain_stages(target))
    result = []
    for index, stage in enumerate(stages):
        controller = deform.find_controller(target, stage)
        props = controller.sdh_cage_deform
        result.append({
            "index": index,
            "location": tuple(float(value) for value in controller.location),
            "rotation": tuple(float(value) for value in controller.rotation_euler),
            "size": tuple(float(value) for value in props.size),
            "gap": float(chain.stage_chain_gap(stage)),
        })
    return result


def mesh_state(target):
    evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return tuple(tuple(float(value) for value in vertex.co) for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def max_delta(first, second):
    return max(
        (Vector(a) - Vector(b)).length
        if isinstance(a, (tuple, list)) else abs(float(a) - float(b))
        for a, b in zip(first, second)
    ) if first else 0.0


addon = importlib.import_module(PACKAGE)
entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
chain = importlib.import_module(f"{PACKAGE}.cage_deform.chain")
core = importlib.import_module(f"{PACKAGE}.cage_deform.core")

failures = []


def check_case(side, mode, active_index=2):
    fast_target = make_target(f"SDH Boundary Fast {side} {mode}")
    safe_target = make_target(f"SDH Boundary Safe {side} {mode}")
    # Create one chain at a time because the operator uses the active target.
    for target in (fast_target, safe_target):
        activate(target)
        result = bpy.ops.sdh.add_cage_chain(
            count=5,
            cage_type="STANDARD",
            connection_mode="CHAINED",
            gap=0.35,
            auto_reconnect=True,
            alignment="POS_Y",
            origin="BOTTOM",
        )
        if result != {"FINISHED"}:
            raise AssertionError(f"chain creation failed: {result!r}")
        stages = tuple(chain.chain_stages(target))
        for index, stage in enumerate(stages):
            controller = deform.find_controller(target, stage)
            props = controller.sdh_cage_deform
            props.origin = ("BOTTOM", "CENTER", "TOP", "SYMMETRIC")[index % 4]
            props.bend_strength = math.radians(12.0 - index * 1.5)
            props.bend_direction = math.radians(8.0)
            props.twist_strength = math.radians(index * 3.0)
            deform.sync_controller(controller, pull_transform=False)
        core.flush_pending_chain_updates(target)
    fast_stages = tuple(chain.chain_stages(fast_target))
    safe_stages = tuple(chain.chain_stages(safe_target))
    fast_controller = deform.find_controller(fast_target, fast_stages[active_index])
    safe_controller = deform.find_controller(safe_target, safe_stages[active_index])
    fast_state = chain.capture_chain_boundary_state(
        fast_target, fast_stages[active_index], fast_controller, side)
    safe_state = chain.capture_chain_boundary_state(
        safe_target, safe_stages[active_index], safe_controller, side)
    if not fast_state or not safe_state:
        raise AssertionError("boundary snapshot unavailable")
    fast_uuid = chain.stage_chain_uuid(fast_stages[0])
    core.begin_chain_interaction(fast_target, fast_uuid)
    try:
        for requested in (-0.12, 0.0, 0.08, 0.18, -0.04):
            fast_result = chain.apply_shared_boundary_edit(
                fast_state, requested, mode)
            safe_result = chain.apply_shared_boundary_edit(
                safe_state, requested, mode)
            if fast_result is None or safe_result is None:
                raise AssertionError(
                    f"{side}/{mode}: edit returned None at {requested}")
            bpy.context.view_layer.update()
            fast_values = numeric_state(fast_target, chain, deform)
            safe_values = numeric_state(safe_target, chain, deform)
            if max_delta(fast_values, safe_values) > TOLERANCE:
                diffs = sorted(
                    ((abs(float(a) - float(b)), index, a, b)
                     for index, (a, b) in enumerate(zip(fast_values, safe_values))),
                    reverse=True,
                )[:5]
                raise AssertionError(
                    f"{side}/{mode}: controller mismatch at {requested}: "
                    f"{max_delta(fast_values, safe_values):.8g} {diffs} "
                    f"fast={labeled_state(fast_target, chain, deform)} "
                    f"safe={labeled_state(safe_target, chain, deform)}")
            fast_mesh = mesh_state(fast_target)
            safe_mesh = mesh_state(safe_target)
            if len(fast_mesh) != len(safe_mesh):
                raise AssertionError(f"{side}/{mode}: mesh length mismatch")
            mesh_error = max(
                (Vector(a) - Vector(b)).length
                for a, b in zip(fast_mesh, safe_mesh)
            ) if fast_mesh else 0.0
            if mesh_error > TOLERANCE:
                mesh_diffs = sorted(
                    ((
                        (Vector(a) - Vector(b)).length,
                        index,
                        a,
                        b,
                    ) for index, (a, b) in enumerate(zip(fast_mesh, safe_mesh))),
                    reverse=True,
                )[:3]
                raise AssertionError(
                    f"{side}/{mode}: mesh mismatch at {requested}: "
                    f"{mesh_error:.8g} {mesh_diffs}")
    finally:
        core.end_chain_interaction(fast_target, fast_uuid)
    if core._CHAIN_RECONNECT_QUEUE:
        raise AssertionError(f"{side}/{mode}: unexpected reconnect queue")
    # A cancelled modal edit must still restore the exact captured state.
    if not chain.restore_shared_boundary_edit(fast_state):
        raise AssertionError(f"{side}/{mode}: restore failed")
    bpy.context.view_layer.update()
    restored = numeric_state(fast_target, chain, deform)
    baseline = []
    for record in fast_state["records"]:
        baseline.extend(record["size"])
        baseline.extend(record["location"])
        matrix = record["matrix_basis"]
        baseline.extend(
            float(matrix[row][column])
            for row in range(3) for column in range(3)
        )
        baseline.extend((record["gap"],))
    if max_delta(restored, tuple(baseline)) > TOLERANCE:
        raise AssertionError(
            f"{side}/{mode}: cancel restore mismatch "
            f"{max_delta(restored, tuple(baseline)):.8g}")
    return True


def topology_change_cancels_fast_path():
    """A native modifier reorder must cancel an in-flight fast edit."""
    target = make_target("SDH Boundary Topology Change")
    activate(target)
    if bpy.ops.sdh.add_cage_chain(
            count=3,
            cage_type="STANDARD",
            connection_mode="CHAINED",
            gap=0.2,
            auto_reconnect=True,
            alignment="POS_Y",
            origin="BOTTOM",
    ) != {"FINISHED"}:
        raise AssertionError("topology-change chain creation failed")
    stages = tuple(chain.chain_stages(target))
    controller = deform.find_controller(target, stages[1])
    state = chain.capture_chain_boundary_state(
        target, stages[1], controller, "TOP")
    if state is None:
        raise AssertionError("topology-change boundary snapshot unavailable")
    chain_uuid = chain.stage_chain_uuid(stages[0])
    core.begin_chain_interaction(target, chain_uuid)
    try:
        activate(target)
        target.modifiers.active = stages[0]
        result = bpy.ops.object.modifier_move_to_index(
            modifier=stages[0].name,
            index=len(tuple(target.modifiers)) - 1,
        )
        if result != {"FINISHED"}:
            raise AssertionError(f"topology reorder failed: {result!r}")
        if chain.apply_shared_boundary_edit(state, 0.1, "SINGLE") is not None:
            raise AssertionError(
                "reordered chain was accepted by the incremental path")
    finally:
        core.end_chain_interaction(target, chain_uuid)
        core._CHAIN_RECONNECT_QUEUE.clear()
    return True


try:
    for side in ("TOP", "BOTTOM"):
        check_case(side, "SINGLE")
    for mode in ("TRANSLATE", "SYMMETRIC"):
        check_case("TOP", mode)
    topology_change_cancels_fast_path()
    print("SDH_CHAIN_BOUNDARY_INCREMENTAL::PASS")
except Exception as exc:
    failures.append(str(exc))
    print(f"SDH_CHAIN_BOUNDARY_INCREMENTAL::FAIL::{type(exc).__name__}::{exc}")
finally:
    try:
        addon.unregister()
    except Exception:
        pass
    try:
        bpy.context.preferences.addons.remove(entry)
    except Exception:
        pass
    if failures:
        raise SystemExit(1)
