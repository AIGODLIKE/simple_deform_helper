"""Regression coverage for Curve cage version-33 state migration."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import bpy
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))


def check(condition, message):
    if not condition:
        raise AssertionError(message)


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
curve = importlib.import_module(f"{PACKAGE}.cage_deform.curve")

try:
    bpy.ops.mesh.primitive_cube_add()
    target = bpy.context.object
    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, target, cage_type="CURVE")
    properties = controller.sdh_cage_deform
    guide = curve.curve_guide_object(target, modifier)
    spline = curve.curve_guide_spline(guide)
    spline.bezier_points[1].co += Vector((0.65, 0.0, 0.3))
    authored_points = tuple(
        tuple(float(value) for value in point.co)
        for point in spline.bezier_points)

    properties.curve_length_mode = "PRESERVE"
    properties.curve_mode = "UNLIMITED"
    properties.curve_preserve_volume = True
    deform.sync_controller(
        controller, pull_transform=False, sync_mode="push")
    check(
        int(deform.modifier_input(modifier, "Curve Boundary Mode", -1)) == 0,
        "Legacy Curve boundary socket was not authored as Extend")

    # A version-33 file has no stored curve_mode property. Its compatible
    # boundary socket must remain authoritative while the node group upgrades.
    properties.property_unset("curve_mode")
    properties.property_unset("curve_boundary_mode")
    properties.property_unset("curve_length_mode")
    properties.property_unset("curve_preserve_volume")
    check(properties.curve_mode == "LIMITED", "Migration fixture is not legacy-like")
    modifier.node_group[deform.core.GROUP_MARKER] = 33

    migrated = deform.core.upgrade_managed_stages()
    check(migrated == 1, f"Expected one upgraded Curve stage, got {migrated}")
    check(
        int(modifier.node_group[deform.core.GROUP_MARKER]) ==
        deform.core.GROUP_VERSION,
        "Curve node group version was not upgraded")
    check(properties.curve_mode == "UNLIMITED", "Extend did not migrate to Unlimited")
    check(
        properties.curve_boundary_mode == "EXTEND",
        "Compatible Curve boundary enum was not restored")
    check(
        properties.curve_length_mode == "PRESERVE",
        "Curve length mode was lost during node-group upgrade")
    check(
        properties.curve_control_mode == "CAGE",
        "Legacy Preserve Length did not migrate to Cage mode")
    check(
        properties.curve_preserve_volume,
        "Curve volume preservation was lost during node-group upgrade")

    upgraded_guide = curve.curve_guide_object(target, modifier)
    check(upgraded_guide == guide, "Curve guide ownership changed during migration")
    upgraded_points = tuple(
        tuple(float(value) for value in point.co)
        for point in curve.curve_guide_spline(upgraded_guide).bezier_points)
    check(
        upgraded_points == authored_points,
        "Authored Curve guide shape changed during migration")
    print("SDH_CURVE_CAGE_MIGRATION::PASS")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
