"""Measure Blender's cold Geometry Nodes initialization without the add-on."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
ASSET = SOURCE / "cage_deform" / "assets" / "cage_deform_core.blend"
GROUP_NAME = "SDH Cage Deform Core"
ORDER = os.environ.get("SDH_GN_PROBE_ORDER", "EMPTY_FIRST").upper()


def timed(function):
    started = time.perf_counter()
    result = function()
    return time.perf_counter() - started, result


def create_empty():
    return bpy.data.node_groups.new("SDH Cold Probe", "GeometryNodeTree")


def load_packaged():
    with bpy.data.libraries.load(str(ASSET), link=False) as (source, destination):
        assert GROUP_NAME in source.node_groups
        destination.node_groups = [GROUP_NAME]
    return destination.node_groups[0]


operations = (
    (("empty", create_empty), ("packaged", load_packaged))
    if ORDER == "EMPTY_FIRST" else
    (("packaged", load_packaged), ("empty", create_empty))
)
records = []
for label, function in operations:
    elapsed, group = timed(function)
    records.append({
        "label": label,
        "seconds": round(elapsed, 6),
        "schema_version": int(group.get("_sdh_cage_deform_group", 0)),
        "node_count": len(group.nodes),
    })
    if group is not None and group.users == 0:
        bpy.data.node_groups.remove(group)

print("SDH_GN_COLD_START::" + json.dumps({
    "order": ORDER,
    "records": records,
}, sort_keys=True))
