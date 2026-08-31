"""Read-only diagnostic for the supplied file's removed-Twist residue.

Set ``SDH_BLEND`` to the source .blend path.  The script opens the file under
factory startup, registers the checkout, and reports controller RNA state,
Geometry Nodes inputs, and evaluated mesh displacement without saving it.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(os.environ.get("SDH_ADDON_ROOT", SOURCE)).resolve()
BLEND = Path(os.environ["SDH_BLEND"]).resolve()
PACKAGE = ADDON_ROOT.name
sys.path.insert(0, str(ADDON_ROOT.parent))


def value(value):
    if value is None:
        return None
    if isinstance(value, (str, bool, int, float)):
        return value
    try:
        return tuple(value)
    except TypeError:
        return repr(value)


def modifier_inputs(core, modifier):
    names = (
        "Deform Type", "Deform Types", "Bend Angle", "Twist Angle",
        "Taper Factor", "Stretch Factor", "Shear", "Mode", "Origin",
        "Chain Global Prefix Active", "Chain Global Prefix Types",
        "Chain Global Prefix Twist", "Chain Global Profile Active",
    )
    result = {}
    for name in names:
        try:
            identifier = core.modifier_input_identifier(modifier, name)
            result[name] = {
                "identifier": identifier,
                "value": value(core.modifier_input(modifier, name, None)),
            }
        except Exception as exc:
            result[name] = {"error": repr(exc)}
    return result


if not BLEND.is_file():
    print(f"SDH_TWIST_RESIDUE::SKIP missing fixture: {BLEND}")
    raise SystemExit(0)

bpy.ops.wm.open_mainfile(filepath=str(BLEND))
addon = importlib.import_module(PACKAGE)
entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
core = deform.core

try:
    bpy.context.view_layer.update()
    records = []
    for target in tuple(bpy.data.objects):
        if getattr(target, "type", None) != "MESH":
            continue
        stages = tuple(deform.cage_modifiers(target))
        if not stages:
            continue
        target_record = {
            "target": target.name,
            "selected": bool(target.select_get()),
            "modifiers": [],
        }
        for stage in stages:
            controller = deform.find_controller(target, stage)
            properties = getattr(controller, "sdh_cage_deform", None)
            group = getattr(stage, "node_group", None)
            if properties is None:
                continue
            try:
                ordered = tuple(core.ordered_deform_types(properties))
                active = tuple(core.active_deform_types(properties))
            except Exception as exc:
                ordered = active = (f"ERROR: {exc!r}",)
            group_keys = {}
            if group is not None:
                for key in (
                        core.GROUP_MARKER,
                        core.DEFORM_ORDER_SIGNATURE,
                        core.CHAIN_UUID_PROP,
                        core.CHAIN_INDEX_PROP,
                        core.CHAIN_COUNT_PROP):
                    try:
                        group_keys[key] = value(group.get(key))
                    except Exception as exc:
                        group_keys[key] = f"ERROR: {exc!r}"
            target_record["modifiers"].append({
                "modifier": stage.name,
                "controller": controller.name if controller else None,
                "rna": {
                    "cage_type": str(properties.cage_type),
                    "deform_type": str(properties.deform_type),
                    "deform_types": tuple(properties.deform_types),
                    "muted_deform_types": tuple(properties.muted_deform_types),
                    "deform_order": tuple(properties.deform_order),
                    "ordered": ordered,
                    "active": active,
                    "bend_strength": float(properties.bend_strength),
                    "twist_strength": float(properties.twist_strength),
                    "taper_factor": float(properties.taper_factor),
                    "stage_enabled": bool(properties.stage_enabled),
                },
                "group": group_keys,
                "inputs": modifier_inputs(core, stage),
                "twist_nodes": tuple(
                    node.name for node in getattr(group, "nodes", ())
                    if "twist" in node.name.lower()
                ) if group is not None else (),
            })
        records.append(target_record)

    print("SDH_TWIST_RESIDUE::" + json.dumps(records, sort_keys=True, default=str))
    print("SDH_TWIST_RESIDUE::PASS")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
