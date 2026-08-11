"""Compare the managed orthogonal chain frame with a full boundary Jacobian."""

from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))

ORIGINS = ("BOTTOM", "TOP", "CENTER", "SYMMETRIC")
CONFIGS = ("BEND", "BEND_TWIST")
RADIUS = 0.65


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def apply_without_input_frame(deform, point, properties):
    return Vector(deform.deform_point_from_properties(
        point,
        properties,
        evaluator=True,
        chain_eligible=True,
        apply_chain_input_offset=False,
    ))


def full_jacobian_frame(deform, properties):
    half_y = max(abs(float(properties.size[1])) * 0.5, deform.core.EPSILON)
    lower = Vector((0.0, -half_y, 0.0))

    def evaluate(point):
        return apply_without_input_frame(deform, point, properties)

    pivot = evaluate(lower)
    basis_x = (
        evaluate(lower + Vector((1.0, 0.0, 0.0))) -
        evaluate(lower - Vector((1.0, 0.0, 0.0)))
    ) * 0.5
    basis_z = (
        evaluate(lower + Vector((0.0, 0.0, 1.0))) -
        evaluate(lower - Vector((0.0, 0.0, 1.0)))
    ) * 0.5
    delta_y = max(min(half_y * 0.001, 0.001), deform.core.EPSILON)
    basis_y = (
        evaluate(lower + Vector((0.0, delta_y, 0.0))) - pivot
    ) / delta_y
    basis = Matrix((
        (basis_x.x, basis_y.x, basis_z.x),
        (basis_x.y, basis_y.y, basis_z.y),
        (basis_x.z, basis_y.z, basis_z.z),
    ))
    check(abs(basis.determinant()) > deform.core.EPSILON,
          "candidate boundary Jacobian is singular")
    inverse = basis.inverted()
    return pivot, Vector(inverse[0]), Vector(inverse[1]), Vector(inverse[2])


def mapped_point(raw, frame, half_y):
    delta = Vector(raw) - Vector(frame[0])
    return Vector((
        delta.dot(Vector(frame[1])),
        delta.dot(Vector(frame[2])) - half_y,
        delta.dot(Vector(frame[3])),
    ))


def reconstruction_error(deform, properties, frame, axial_offset):
    half_y = float(properties.size[1]) * 0.5
    maximum = 0.0
    for side in range(16):
        angle = math.tau * side / 16
        source = Vector((
            RADIUS * math.cos(angle),
            -half_y + axial_offset,
            RADIUS * math.sin(angle),
        ))
        deformed = apply_without_input_frame(deform, source, properties)
        recovered = mapped_point(deformed, frame, half_y)
        reconstructed = apply_without_input_frame(
            deform, recovered, properties)
        maximum = max(maximum, (reconstructed - deformed).length)
    return maximum


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
chain = deform.chain

mesh = bpy.data.meshes.new("SDH Frame Candidate")
mesh.from_pydata(((-0.65, -3.0, 0.0), (0.65, 3.0, 0.0)), (), ())
target = bpy.data.objects.new("SDH Frame Candidate", mesh)
bpy.context.collection.objects.link(target)
target.select_set(True)
bpy.context.view_layer.objects.active = target

records = []
try:
    check(bpy.ops.sdh.add_cage_chain(
        count=2,
        connection_mode="CHAINED",
        gap=0.0,
        auto_reconnect=True,
        sync_shared_end_scale=True,
        alignment="POS_Y",
        origin="BOTTOM",
    ) == {"FINISHED"}, "could not create probe chain")
    stages = chain.chain_stages(target)
    controllers = tuple(deform.find_controller(target, stage)
                        for stage in stages)
    check(len(stages) == 2 and all(controllers), "probe chain is incomplete")
    controller = controllers[1]
    properties = controller.sdh_cage_deform

    for config in CONFIGS:
        layers = ("BEND",) if config == "BEND" else ("BEND", "TWIST")
        deform.core.set_deform_layers(properties, layers, bpy.context)
        properties.bend_strength = math.radians(-37.0)
        properties.bend_direction = math.radians(-29.0)
        properties.twist_strength = (
            0.0 if config == "BEND" else math.radians(-46.0))
        properties.taper_factor = 0.0
        properties.stretch_factor = 0.0
        for origin in ORIGINS:
            properties.origin = origin
            deform.sync_controller(controller, pull_transform=False)
            deform.core.flush_pending_chain_updates(target)
            current = deform.core.chain_input_frame_for_controller(
                controller, stages[1], properties)
            candidate = full_jacobian_frame(deform, properties)
            errors = {}
            for axial_offset in (0.0, 0.001, 0.005):
                errors[axial_offset] = {
                    "current": reconstruction_error(
                        deform, properties, current, axial_offset),
                    "candidate": reconstruction_error(
                        deform, properties, candidate, axial_offset),
                }
            record = {
                "config": config,
                "origin": origin,
                "errors": errors,
            }
            records.append(record)
            print(f"SDH_CHAIN_FRAME::CASE::{record!r}")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)

summary = {
    "cases": len(records),
    "current_lower_max": max(
        record["errors"][0.0]["current"] for record in records),
    "candidate_lower_max": max(
        record["errors"][0.0]["candidate"] for record in records),
    "current_near_max": max(
        record["errors"][0.005]["current"] for record in records),
    "candidate_near_max": max(
        record["errors"][0.005]["candidate"] for record in records),
}
print(f"SDH_CHAIN_FRAME::SUMMARY::{summary!r}")
check(summary["candidate_lower_max"] < 1.0e-5,
      f"candidate frame does not preserve its lower section: {summary!r}")
check(summary["candidate_near_max"] < summary["current_near_max"] * 0.05,
      f"candidate frame did not materially improve near-boundary reconstruction: {summary!r}")
print("SDH_CHAIN_FRAME::PASS")
