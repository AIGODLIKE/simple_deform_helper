"""Keep unrelated picker previews stable only while an end-scale drag runs."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))


class PickerProbe:
    def __init__(self):
        self.target = None
        self.controller = None
        self.custom_shape = None
        self.geometry_signature = None
        self.modifier_uuid = ""
        self.stage_operator = None
        self.matrix_basis = None
        self.hide = True

    def new_custom_shape(self, _kind, vertices):
        return tuple(vertices)


addon = importlib.import_module(PACKAGE)
entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
gizmos = importlib.import_module(f"{PACKAGE}.cage_deform.gizmos")

try:
    bpy.ops.mesh.primitive_cube_add()
    target = bpy.context.object
    result = bpy.ops.sdh.add_cage_chain(
        count=4,
        cage_type="STANDARD",
        connection_mode="CHAINED",
        alignment="POS_Y",
        origin="BOTTOM",
    )
    if result != {"FINISHED"}:
        raise AssertionError(f"chain creation failed: {result!r}")
    stages = tuple(deform.chain.chain_stages(target))
    controllers = tuple(deform.find_controller(target, stage) for stage in stages)
    probe = PickerProbe()
    configure = gizmos.SDHCageStagePickerGizmo.configure
    configure(probe, target, stages[3], controllers[3])
    initial_signature = probe.geometry_signature
    if initial_signature is None or probe.custom_shape is None:
        raise AssertionError("picker probe did not build its initial preview")

    gizmos._begin_end_shape_preview_drag(
        target, stages[1], controllers[1], "TOP")
    frozen = tuple(
        gizmos._freeze_for_end_shape_drag(target, controller)
        for controller in controllers)
    if frozen != (True, False, False, True):
        raise AssertionError(f"unexpected live seam membership: {frozen!r}")
    controllers[3].sdh_cage_deform.bend_strength = 0.35
    configure(probe, target, stages[3], controllers[3])
    if probe.geometry_signature != initial_signature:
        raise AssertionError("unrelated picker rebuilt during the end-scale drag")

    gizmos._end_shape_preview_drag()
    configure(probe, target, stages[3], controllers[3])
    if probe.geometry_signature == initial_signature:
        raise AssertionError("unrelated picker did not converge after drag exit")
    if any(gizmos._freeze_for_end_shape_drag(target, item)
           for item in controllers):
        raise AssertionError("end-scale drag state survived exit")
    print(f"SDH_END_SHAPE_PREVIEW_FREEZE::{frozen!r}::PASS")
finally:
    gizmos._end_shape_preview_drag()
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
