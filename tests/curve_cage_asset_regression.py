"""Verify Curve cages use the packaged node template without a cold rebuild."""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
INSTALLED_PACKAGE = os.environ.get("SDH_TEST_MODULE")
PACKAGE = INSTALLED_PACKAGE or SOURCE.name
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(SOURCE.parent))


addon = importlib.import_module(PACKAGE)
entry = None
if not INSTALLED_PACKAGE:
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
core = deform.core

for group in tuple(bpy.data.node_groups):
    if group.name == core.GROUP_NAME or group.get(core.MODIFIER_MARKER, False):
        bpy.data.node_groups.remove(group)

build_calls = 0
original_build = core.build_node_group


def tracked_build(node_group):
    global build_calls
    build_calls += 1
    return original_build(node_group)


core.build_node_group = tracked_build
try:
    bpy.ops.mesh.primitive_cube_add()
    target = bpy.context.object
    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, target, cage_type="CURVE")
    if build_calls:
        raise AssertionError(
            f"First Curve cage rebuilt Geometry Nodes {build_calls} time(s)")
    if int(modifier.node_group.get(core.GROUP_MARKER, 0)) != core.GROUP_VERSION:
        raise AssertionError("Curve stage did not copy the current packaged template")
    for input_name in (
            "Curve Closed", "Curve Range Start", "Curve Range End",
            "Curve Global Radius", "Curve Global Twist"):
        if core.modifier_input_identifier(modifier, input_name) is None:
            raise AssertionError(
                f"Packaged template is missing the {input_name} input")
    if str(controller.sdh_cage_deform.cage_type) != "CURVE":
        raise AssertionError("Packaged template created the wrong cage type")
    print("SDH_CURVE_CAGE_ASSET::PASS::build_calls=0")
finally:
    core.build_node_group = original_build
    if not INSTALLED_PACKAGE:
        addon.unregister()
        if entry is not None:
            bpy.context.preferences.addons.remove(entry)
