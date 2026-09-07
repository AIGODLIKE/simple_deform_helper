"""Migrate old cage animation without changing other Action slot users."""
import importlib
import os
import sys
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = os.environ.get("SDH_TEST_MODULE") or SOURCE.name
entry = None
if not os.environ.get("SDH_TEST_MODULE"):
    sys.path.insert(0, str(SOURCE.parent))
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
if entry is not None:
    addon.register()
core = importlib.import_module(f"{PACKAGE}.cage_deform.core")
OLD = "sdh_review_legacy"


class SDHReviewLegacyProperties(bpy.types.PropertyGroup):
    strength: bpy.props.FloatProperty(default=0.0)
    direction: bpy.props.FloatProperty(default=0.0)


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def make_owner(name):
    owner = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(owner)
    return owner


def animate(owner, property_name="strength"):
    for frame, value in ((1, 0.15), (10, 0.85)):
        setattr(getattr(owner, OLD), property_name, value)
        owner.keyframe_insert(f"{OLD}.{property_name}", frame=frame)
    return owner.animation_data.action, owner.animation_data.action_slot


def paths(action, slot):
    return {
        curve.data_path
        for layer in action.layers
        for strip in layer.strips
        for bag in (strip.channelbag(slot),)
        if bag is not None
        for curve in bag.fcurves
    }


def nla_binding(owner, action, slot, name="Legacy NLA"):
    track = owner.animation_data.nla_tracks.new()
    strip = track.strips.new(name, 1, action)
    strip.action_slot = slot
    owner.animation_data.action = None
    return strip


def add_property_driver(owner, index, target):
    curve = owner.driver_add("location", index)
    variable = curve.driver.variables.new()
    variable.name = "value"
    variable.type = "SINGLE_PROP"
    variable.targets[0].id = target
    variable.targets[0].data_path = f"{OLD}.strength"
    curve.driver.expression = "value"
    return variable.targets[0]


def direct_action_and_drivers():
    owner = make_owner("Migration Action Owner")
    action, slot = animate(owner)
    owner.keyframe_insert("location", frame=1)
    driver = owner.driver_add(f"{OLD}.direction")
    owner['label.' + OLD + '.strength'] = 1.0
    unrelated_path = '["label.' + OLD + '.strength"]'
    owner.keyframe_insert(unrelated_path, frame=1)
    core._migrate_animation_paths(owner, OLD)
    check(paths(action, slot) == {
        "sdh_cage_deform.bend_strength", "location", unrelated_path,
    }, "active Action migration changed unrelated paths or missed strength")
    check(driver.data_path == "sdh_cage_deform.bend_direction",
          "owned driver path was not migrated")
    other = make_owner("Unrelated Driver Source")
    other_target = add_property_driver(owner, 0, other)
    core._migrate_animation_paths(owner, OLD)
    check(other_target.data_path == f"{OLD}.strength",
          "driver variable targeting another object was changed")
    check(len(paths(action, slot)) == 3, "second migration was not idempotent")


def nla_only():
    owner = make_owner("Migration NLA Owner")
    action, slot = animate(owner)
    strip = nla_binding(owner, action, slot)
    core._migrate_animation_paths(owner, OLD)
    check(owner.animation_data.action is None,
          "NLA migration activated an Action")
    check(paths(strip.action, strip.action_slot) == {"sdh_cage_deform.bend_strength"},
          "NLA-only Action path was not migrated")


def shared_action_slots():
    owner = make_owner("Migration First Slot")
    other = make_owner("Migration Other Slot")
    action, first_slot = animate(owner)
    other.animation_data_create().action = action
    second_slot = action.slots.new("OBJECT", "Other Owner")
    other.animation_data.action_slot = second_slot
    animate(other)
    core._migrate_animation_paths(owner, OLD)
    check(owner.animation_data.action == action,
          "distinct shared slots unnecessarily duplicated the Action")
    check(paths(action, first_slot) == {"sdh_cage_deform.bend_strength"},
          "first slot was not migrated")
    check(paths(action, second_slot) == {f"{OLD}.strength"},
          "another owner's slot was modified")


def shared_slot():
    owner = make_owner("Migration Shared Slot")
    other = make_owner("Migration Shared Slot Other")
    action, slot = animate(owner)
    other.animation_data_create().action = action
    other.animation_data.action_slot = slot
    track = owner.animation_data.nla_tracks.new()
    strip = track.strips.new("Same Slot NLA", 20, action)
    strip.action_slot = slot
    core._migrate_animation_paths(owner, OLD)
    copied = owner.animation_data.action
    check(copied != action, "shared slot was not isolated before migration")
    check(strip.action == copied,
          "the same owner's active and NLA bindings used different copies")
    check(paths(copied, owner.animation_data.action_slot) == {
        "sdh_cage_deform.bend_strength"}, "copied Action slot was not migrated")
    check(other.animation_data.action == action,
          "another owner's Action binding was changed")
    check(paths(action, slot) == {f"{OLD}.strength"},
          "another shared-slot user lost its original path")


def prototype_stage_playback():
    for use_nla in (False, True):
        bpy.ops.mesh.primitive_cube_add()
        target = bpy.context.object
        modifier, controller, _previous = core.create_deform_stage(
            bpy.context, target)
        old_group = modifier.node_group
        base = f"_{OLD}_"
        old_group[base + "stage"] = True
        old_group[base + "modifier_uuid"] = core.cage_modifier_uuid(modifier)
        target[base + "target_uuid"] = str(target[core.TARGET_UUID])
        controller[base + "controller"] = True
        controller[base + "target_uuid"] = str(target[core.TARGET_UUID])
        controller[base + "modifier_uuid"] = core.cage_modifier_uuid(modifier)
        action, slot = animate(controller)
        self_target = add_property_driver(controller, 0, controller)
        if use_nla:
            nla_binding(controller, action, slot)
        check(core.migrate_legacy_stages(bpy.context) == 1,
              "prototype stage was not recognized and migrated")
        check(modifier.node_group != old_group,
              "migration did not replace the legacy node group")
        check(self_target.data_path == "sdh_cage_deform.bend_strength",
              "self-target driver variable was not migrated")
        values = []
        for frame, expected in ((1, 0.15), (10, 0.85)):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            core.sync_controller(controller, sync_mode="timer")
            value = float(core.modifier_input(modifier, "Bend Angle"))
            check(abs(value - expected) < 1.0e-5,
                  f"migrated {'NLA' if use_nla else 'Action'} frame {frame}: "
                  f"expected {expected}, got {value}")
            check(abs(controller.location.x - expected) < 1.0e-5,
                  f"migrated self-target driver froze at frame {frame}")
            values.append(value)
        check(abs(values[1] - values[0]) > 0.5,
              "migrated cage animation remained frozen")


bpy.utils.register_class(SDHReviewLegacyProperties)
setattr(bpy.types.Object, OLD, bpy.props.PointerProperty(
    type=SDHReviewLegacyProperties))
try:
    for case in (direct_action_and_drivers, nla_only, shared_action_slots,
                 shared_slot, prototype_stage_playback):
        case()
        print(f"SDH_LEGACY_ANIMATION::{case.__name__}::PASS")
    print("SDH_LEGACY_ANIMATION::SUMMARY::PASS")
finally:
    delattr(bpy.types.Object, OLD)
    bpy.utils.unregister_class(SDHReviewLegacyProperties)
    if entry is not None:
        addon.unregister()
        bpy.context.preferences.addons.remove(entry)
