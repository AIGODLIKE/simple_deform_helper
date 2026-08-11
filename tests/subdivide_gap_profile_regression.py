"""Verify physical source-coordinate partitioning for gapped subdivision.

Gaps are intentionally unowned intervals, so this check validates the
parameters assigned to each cage rather than requiring the mesh inside a gap
to be deformed by a stage that does not own it.

Run with:
    blender --background --factory-startup --python-exit-code 1 \
        --python tests/subdivide_gap_profile_regression.py
"""

from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))

COUNT = 3
TOTAL_LENGTH = 6.0
GAP = 0.4
SEGMENT_LENGTH = (TOTAL_LENGTH - GAP * (COUNT - 1)) / COUNT
SOURCE_TWIST = math.radians(-67.0)
SOURCE_TAPER = 0.48
SOURCE_BOTTOM_SCALE = (0.8, 0.9)
SOURCE_TOP_SCALE = (1.6, 1.4)
SOURCE_BOTTOM_OFFSET = (-0.2, 0.1)
SOURCE_TOP_OFFSET = (0.35, -0.25)
EPSILON = 2.0e-4


def fail(message):
    raise AssertionError(message)


def assert_close(actual, expected, label):
    if abs(float(actual) - float(expected)) > EPSILON:
        fail(f"{label}: {actual!r} != {expected!r}")


def assert_pair(actual, expected, label, tolerance=EPSILON):
    if len(actual) != len(expected):
        fail(f"{label}: wrong length")
    for index, (value, reference) in enumerate(zip(actual, expected)):
        if abs(float(value) - float(reference)) > tolerance:
            fail(f"{label}[{index}]: {value!r} != {reference!r}")


def lerp_pair(lower, upper, factor):
    return tuple(
        low + (high - low) * factor
        for low, high in zip(lower, upper)
    )


def activate(target):
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
chain = deform.chain

mesh = bpy.data.meshes.new("SDH Gap Profile Regression Mesh")
mesh.from_pydata(
    ((-0.5, -3.0, -0.5), (0.5, -3.0, -0.5),
     (0.5, 3.0, -0.5), (-0.5, 3.0, -0.5)),
    (), ((0, 1, 2, 3),),
)
target = bpy.data.objects.new("SDH Gap Profile Regression", mesh)
bpy.context.collection.objects.link(target)
activate(target)

try:
    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, target)
    properties = controller.sdh_cage_deform
    properties.size = (2.0, TOTAL_LENGTH, 2.0)
    properties.mode = "LIMITED"
    properties.origin = "BOTTOM"
    properties.bend_strength = 0.0
    properties.twist_strength = SOURCE_TWIST
    properties.taper_factor = SOURCE_TAPER
    properties.bottom_scale = SOURCE_BOTTOM_SCALE
    properties.top_scale = SOURCE_TOP_SCALE
    properties.bottom_offset = SOURCE_BOTTOM_OFFSET
    properties.top_offset = SOURCE_TOP_OFFSET
    deform.core.set_deform_layers(properties, ("TWIST", "TAPER"), bpy.context)
    deform.sync_controller(controller, pull_transform=False)
    target.modifiers.active = modifier
    activate(target)

    result = bpy.ops.sdh.subdivide_cage_to_chain(
        count=COUNT,
        gap=GAP,
        auto_reconnect=True,
        sync_shared_end_scale=True,
        allow_mixed_bend_approximation=True,
    )
    if result != {"FINISHED"}:
        fail(f"subdivision returned {result!r}")
    deform.core.flush_pending_chain_updates(target)
    bpy.context.view_layer.update()

    stages = tuple(chain.chain_stages(target))
    controllers = tuple(deform.find_controller(target, stage) for stage in stages)
    if len(stages) != COUNT or not all(controllers):
        fail("subdivision did not create the expected stages")

    for index, (stage, item) in enumerate(zip(stages, controllers)):
        start = index * (SEGMENT_LENGTH + GAP)
        end = start + SEGMENT_LENGTH
        start_t = start / TOTAL_LENGTH
        end_t = end / TOTAL_LENGTH
        stage_properties = item.sdh_cage_deform

        expected_twist = SOURCE_TWIST * (end_t - start_t)
        assert_close(
            stage_properties.twist_strength,
            expected_twist,
            f"stage {index} twist",
        )

        q0 = 1.0 + SOURCE_TAPER * start_t
        q1 = 1.0 + SOURCE_TAPER * end_t
        expected_taper = (q1 / q0 - 1.0) / (1.0 - 0.0 * q1 / q0)
        assert_close(
            stage_properties.taper_factor,
            expected_taper,
            f"stage {index} taper",
        )

        assert_pair(
            stage_properties.bottom_scale,
            lerp_pair(SOURCE_BOTTOM_SCALE, SOURCE_TOP_SCALE, start_t),
            f"stage {index} bottom scale",
        )
        assert_pair(
            stage_properties.top_scale,
            lerp_pair(SOURCE_BOTTOM_SCALE, SOURCE_TOP_SCALE, end_t),
            f"stage {index} top scale",
        )
        expected_bottom_offset = (
            lerp_pair(SOURCE_BOTTOM_OFFSET, SOURCE_TOP_OFFSET, start_t)
            if index == 0 else (0.0, 0.0)
        )
        assert_pair(
            stage_properties.bottom_offset,
            expected_bottom_offset,
            f"stage {index} bottom offset",
        )
        if index == 0:
            assert_pair(
                stage_properties.top_offset,
                lerp_pair(SOURCE_BOTTOM_OFFSET, SOURCE_TOP_OFFSET, end_t),
                f"stage {index} top offset",
            )
        elif not all(math.isfinite(float(value))
                     for value in stage_properties.top_offset):
            fail(f"stage {index} top offset is not finite")
        expected_gap = 0.0 if index == 0 else GAP
        assert_close(chain.stage_chain_gap(stage), expected_gap,
                     f"stage {index} gap")

    print("SDH_SUBDIVIDE_GAP_PROFILE::PASS")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
