"""Profile cold and warm cage creation without changing production code."""

from __future__ import annotations

import importlib
import json
import os
import sys
import time
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))


def seconds(function):
    started = time.perf_counter()
    result = function()
    return time.perf_counter() - started, result


def make_target(name, location):
    bpy.ops.mesh.primitive_grid_add(
        x_subdivisions=41,
        y_subdivisions=41,
        size=4.0,
        location=location,
    )
    target = bpy.context.object
    target.name = name
    return target


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
core = importlib.import_module(f"{PACKAGE}.cage_deform.core")

strategy = os.environ.get("SDH_FIRST_CAGE_STRATEGY", "PACKAGED").upper()
if strategy == "PYTHON":
    core._load_packaged_node_group = lambda: None

for obj in tuple(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
for group in tuple(bpy.data.node_groups):
    if group.name == deform.GROUP_NAME or group.get(deform.MODIFIER_MARKER, False):
        bpy.data.node_groups.remove(group)

template_seconds, template = seconds(core.ensure_node_group)
copy_seconds, copy = seconds(template.copy)
bpy.data.node_groups.remove(copy)

records = []
for label, location in (("cold", (-3.0, 0.0, 0.0)), ("warm", (3.0, 0.0, 0.0))):
    target = make_target(f"{label.title()} Cage", location)
    create_seconds, _stage = seconds(
        lambda target=target: deform.create_deform_stage(
            bpy.context,
            target,
            node_group_template=template,
        )
    )
    update_seconds, _result = seconds(bpy.context.view_layer.update)
    records.append({
        "label": label,
        "create_seconds": round(create_seconds, 6),
        "update_seconds": round(update_seconds, 6),
        "total_seconds": round(create_seconds + update_seconds, 6),
    })

result = {
    "strategy": strategy,
    "template_load_seconds": round(template_seconds, 6),
    "template_copy_seconds": round(copy_seconds, 6),
    "records": records,
}
print("SDH_FIRST_CAGE_PROFILE::" + json.dumps(result, sort_keys=True))

addon.unregister()
