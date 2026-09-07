"""Verify owned traditional Origins can be released without a parent."""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
INSTALLED_PACKAGE = os.environ.get("SDH_TEST_MODULE")
PACKAGE = INSTALLED_PACKAGE or SOURCE.name
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(SOURCE.parent))


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def target_object(kind, name):
    if kind == "LATTICE":
        data = bpy.data.lattices.new(name)
    else:
        data = bpy.data.meshes.new(name)
        data.from_pydata(((-1, -1, -1), (1, 1, 1)), (), ())
    target = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(target)
    return target


def activate(target):
    for selected in tuple(bpy.context.selected_objects):
        selected.select_set(False)
    target.select_set(True)
    bpy.context.view_layer.objects.active = target


def managed_stage(kind, name):
    target = target_object(kind, name)
    activate(target)
    check(bpy.ops.sdh.add_legacy_simple_deform() == {"FINISHED"},
          "could not add traditional stage")
    modifier = target.modifiers.active
    origin = modifier.origin
    check(utils.GizmoUtils.is_managed_origin(origin, target),
          "stage did not create its owned Origin")
    return target, modifier, origin


def user_origin(name):
    origin = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(origin)
    return origin


addon = importlib.import_module(PACKAGE)
entry = None
if not INSTALLED_PACKAGE:
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon.register()
utils = importlib.import_module(f"{PACKAGE}.utils")
cases = []

try:
    for kind in ("MESH", "LATTICE"):
        for restore_source in (False, True):
            name = f"Release{kind}{restore_source}"
            target, modifier, origin = managed_stage(kind, name)
            check((origin.parent is None) == (kind == "LATTICE"),
                  "unexpected managed Origin parenting")
            source = user_origin(name + "Source") if restore_source else None
            origin.SimpleDeformGizmo_PropertyGroup.source_origin = source
            origin_name = origin.name
            origin.SimpleDeformGizmo_PropertyGroup.origin_mode = "NOT"
            check(modifier.origin == source, "original Origin was not restored")
            check(bpy.data.objects.get(origin_name) is None,
                  "released managed Origin survived")
            check(target.SimpleDeformGizmo_PropertyGroup.origin_mode == "NOT",
                  "target kept its old Origin mode")
            if source is not None:
                check(bpy.data.objects.get(source.name) == source,
                      "source Origin was removed")
            cases.append(name)

    target = target_object("MESH", "UserOwned")
    activate(target)
    origin = user_origin("UserOrigin")
    origin.parent = target
    origin.location = (1.0, 2.0, 3.0)
    modifier = target.modifiers.new("UserModifier", "SIMPLE_DEFORM")
    modifier.origin = origin
    origin.SimpleDeformGizmo_PropertyGroup.origin_mode = "UP_LIMITS"
    origin.SimpleDeformGizmo_PropertyGroup.origin_mode = "NOT"
    check(modifier.origin == origin and origin.parent == target and
          tuple(origin.location) == (1.0, 2.0, 3.0),
          "user-owned Origin was changed or removed")
    cases.append("UserOwnedOriginPreserved")

    target, modifier, origin = managed_stage("LATTICE", "NonActiveOwner")
    unrelated, unrelated_modifier, unrelated_origin = managed_stage(
        "MESH", "UnrelatedTarget")
    origin.SimpleDeformGizmo_PropertyGroup.origin_mode = "NOT"
    check(modifier.origin is None, "non-active owner did not release its Origin")
    check(unrelated_modifier.origin == unrelated_origin and
          unrelated.SimpleDeformGizmo_PropertyGroup.origin_mode == "DOWN_LIMITS",
          "release changed the active unrelated target")
    cases.append("NonActiveOwnerOnly")

    target, modifier, origin = managed_stage("LATTICE", "WrongOwnerUuid")
    origin[utils.PublicData.G_OWNER_UUID_PROP] = "unrelated-owner"
    origin_name = origin.name
    origin.SimpleDeformGizmo_PropertyGroup.origin_mode = "NOT"
    check(modifier.origin == origin and bpy.data.objects.get(origin_name) == origin,
          "mismatched ownership released an Origin")
    cases.append("MismatchedOwnershipPreserved")

    target, modifier, origin = managed_stage("LATTICE", "AmbiguousOwner")
    duplicate = target_object("LATTICE", "DuplicateOwner")
    duplicate[utils.PublicData.G_OBJECT_UUID_PROP] = target[
        utils.PublicData.G_OBJECT_UUID_PROP]
    duplicate_modifier = duplicate.modifiers.new("DuplicateStage", "SIMPLE_DEFORM")
    duplicate_modifier.origin = origin
    origin.SimpleDeformGizmo_PropertyGroup.origin_mode = "NOT"
    check(modifier.origin == origin and duplicate_modifier.origin == origin,
          "ambiguous UUID selected an arbitrary owner")
    cases.append("AmbiguousOwnerPreserved")

    target, modifier, origin = managed_stage("MESH", "SharedOriginOwner")
    unrelated = target_object("MESH", "SharedOriginUser")
    unrelated_modifier = unrelated.modifiers.new("SharedStage", "SIMPLE_DEFORM")
    unrelated_modifier.origin = origin
    origin_name = origin.name
    origin.SimpleDeformGizmo_PropertyGroup.origin_mode = "NOT"
    addon.cage_deform.core.cleanup_orphan_deform_helpers()
    check(modifier.origin == origin and unrelated_modifier.origin == origin and
          bpy.data.objects.get(origin_name) == origin,
          "release deleted an Origin still used by another object")
    cases.append("OtherObjectReferencePreserved")

    print("LEGACY_LATTICE_ORIGIN_REGRESSION=" + json.dumps({
        "blender": bpy.app.version_string, "cases": cases,
    }))
finally:
    if not INSTALLED_PACKAGE:
        addon.unregister()
        bpy.context.preferences.addons.remove(entry)
