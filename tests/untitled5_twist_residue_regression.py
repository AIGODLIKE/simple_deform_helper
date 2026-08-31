"""Regression for a removed Twist layer leaving a chain-global Twist behind.

The supplied file contains only a BEND layer in RNA but retains the old
global-prefix mask and Twist angle in its chain metadata.  A normal controller
sync must reconcile those fields before Geometry Nodes evaluates the stage.
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
BLEND = Path(os.environ.get("SDH_BLEND", "")).resolve()
PACKAGE = ADDON_ROOT.name
sys.path.insert(0, str(ADDON_ROOT.parent))


def input_value(core, modifier, name):
    return core.modifier_input(modifier, name, None)


if not BLEND.is_file():
    print(f"SDH_TWIST_RESIDUE::SKIP fixture not found: {BLEND}")
    raise SystemExit(0)

bpy.ops.wm.open_mainfile(filepath=str(BLEND))
addon = importlib.import_module(PACKAGE)
entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
core = deform.core

try:
    target = bpy.data.objects.get("Cylinder")
    if target is None:
        raise AssertionError("fixture target Cylinder is missing")
    stages = tuple(deform.cage_modifiers(target))
    if len(stages) != 1:
        raise AssertionError(f"expected one cage stage, got {len(stages)}")
    modifier = stages[0]
    controller = deform.find_controller(target, modifier)
    if controller is None:
        raise AssertionError("fixture cage controller is missing")
    properties = controller.sdh_cage_deform
    if set(properties.deform_types) != {"BEND"}:
        raise AssertionError(
            f"fixture no longer represents the removed-Twist state: "
            f"{set(properties.deform_types)!r}")

    # File loading must reconcile stale chain metadata even when the user has
    # not touched the layer stack yet.  This is the path used by the runtime
    # bootstrap/load-post synchronization in the real UI.
    core._load_sync(None)
    bpy.context.view_layer.update()
    twist_bit = int(core.DEFORM_BITS["TWIST"])
    cold_prefix_mask = int(input_value(
        core, modifier, "Chain Global Prefix Types") or 0)
    cold_prefix_twist = float(input_value(
        core, modifier, "Chain Global Prefix Twist") or 0.0)
    if cold_prefix_mask & twist_bit:
        raise AssertionError(
            f"cold-load sync still enables global Twist: {cold_prefix_mask}")
    if abs(cold_prefix_twist) > 1.0e-6:
        raise AssertionError(
            f"cold-load sync still carries global Twist: {cold_prefix_twist}")

    # Recreate a valid two-layer chain and explicitly restore the old global
    # plan.  Prime the domain cache while TWIST is present, then replay the
    # structural edit that removes it.  The edit must invalidate that cache
    # before the controller callback reads the global plan again.
    if not core.set_deform_layers(
            properties, ("BEND", "TWIST"), bpy.context):
        raise AssertionError("could not restore the two-layer setup")
    deform.chain._set_global_prefix_mode(
        modifier,
        controller,
        active=True,
        deform_types=("BEND", "TWIST"),
        baseline_types=("BEND", "TWIST"),
        bend=float(properties.bend_strength),
        twist=float(properties.twist_strength),
    )
    cached_domain = core._chain_domain_input_values(controller, modifier)
    cached_prefix_mask = int(
        cached_domain.get("Chain Global Prefix Types", 0) or 0)
    if not cached_prefix_mask & twist_bit:
        raise AssertionError(
            f"test setup failed to prime a stale Twist cache: "
            f"{cached_prefix_mask}")
    if not core.remove_deform_layer(properties, 1, bpy.context):
        raise AssertionError("could not remove the Twist layer")
    core.sync_controller(controller, pull_transform=False)
    core.flush_pending_chain_updates(target)
    bpy.context.view_layer.update()

    prefix_mask = int(input_value(
        core, modifier, "Chain Global Prefix Types") or 0)
    prefix_twist = float(input_value(
        core, modifier, "Chain Global Prefix Twist") or 0.0)
    local_twist = float(input_value(core, modifier, "Twist Angle") or 0.0)
    domain = core._chain_domain_input_values(controller, modifier)
    group = modifier.node_group
    stored_mask = int(group.get(deform.chain.CHAIN_GLOBAL_PREFIX_MASK, 0) or 0)
    stored_twist = float(
        group.get(deform.chain.CHAIN_GLOBAL_PREFIX_TWIST, 0.0) or 0.0)

    if prefix_mask & twist_bit:
        raise AssertionError(f"modifier still enables global Twist: {prefix_mask}")
    if abs(prefix_twist) > 1.0e-6:
        raise AssertionError(f"modifier still carries global Twist: {prefix_twist}")
    deform_mask = int(input_value(core, modifier, "Deform Types") or 0)
    if deform_mask & twist_bit:
        raise AssertionError(f"modifier local mask still enables Twist: {deform_mask}")
    if stored_mask & twist_bit:
        raise AssertionError(f"node-group still enables global Twist: {stored_mask}")
    if abs(stored_twist) > 1.0e-6:
        raise AssertionError(f"node-group still carries global Twist: {stored_twist}")
    if int(domain.get("Chain Global Prefix Types", 0)) & twist_bit:
        raise AssertionError(f"decoded domain still enables global Twist: {domain}")
    if abs(float(domain.get("Chain Global Prefix Twist", 0.0))) > 1.0e-6:
        raise AssertionError(f"decoded domain still carries global Twist: {domain}")

    report = {
        "cold_prefix_mask": cold_prefix_mask,
        "cold_prefix_twist": cold_prefix_twist,
        "cached_prefix_mask": cached_prefix_mask,
        "prefix_mask": prefix_mask,
        "prefix_twist": prefix_twist,
        "local_twist": local_twist,
        "stored_mask": stored_mask,
        "stored_twist": stored_twist,
        "domain_prefix_mask": int(domain.get("Chain Global Prefix Types", 0)),
        "domain_prefix_twist": float(
            domain.get("Chain Global Prefix Twist", 0.0)),
    }
    print("SDH_TWIST_RESIDUE::" + json.dumps(report, sort_keys=True))
    print("SDH_TWIST_RESIDUE::PASS")
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
