"""Regression coverage for duplicate-install and partial-register cleanup."""
from __future__ import annotations

import importlib
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import bpy
from bpy.props import BoolProperty


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))


def check(condition, message):
    if not condition:
        raise AssertionError(message)


addon_entry = bpy.context.preferences.addons.new()
addon_entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
preferences = importlib.import_module(f"{PACKAGE}.preferences")
props = importlib.import_module(f"{PACKAGE}.props")
translate = importlib.import_module(f"{PACKAGE}.translate")
utils = importlib.import_module(f"{PACKAGE}.utils")


manifest = tomllib.loads((SOURCE / "blender_manifest.toml").read_text(
    encoding="utf-8"))
check(manifest["id"] == "simple_deform_helper",
      "extension ID changed and would create a separate add-on")
check(manifest["name"] == "Simple Deform Helper",
      "extension-list name changed and may route disk installs to another repository")
check(not hasattr(addon, "bl_info"),
      "legacy bl_info was reintroduced into the Blender Extension")


duplicate_entry = bpy.context.preferences.addons.new()
duplicate_entry.module = "bl_ext.blender_org.simple_deform_helper"
try:
    addon.register()
except RuntimeError as error:
    check("Another Simple Deform Helper installation" in str(error),
          f"duplicate error is not actionable: {error}")
else:
    raise AssertionError("duplicate repository installation was accepted")
finally:
    bpy.context.preferences.addons.remove(duplicate_entry)

check(not addon._registered_modules, "duplicate check registered modules")
check(not preferences._PREFERENCES_REGISTERED,
      "duplicate check registered preferences")
check(not translate.SimpleDeform_CN._registered,
      "duplicate check registered translations")


bpy.types.Object.SimpleDeformGizmo_PropertyGroup = BoolProperty(default=False)
try:
    addon.register()
except RuntimeError as error:
    check("previous Simple Deform Helper registration" in str(error),
          f"stale-registration error is not actionable: {error}")
    addon.unregister()
    check(hasattr(bpy.types.Object, "SimpleDeformGizmo_PropertyGroup"),
          "failed instance removed another installation's Object property")
else:
    raise AssertionError("stale Object property was accepted")
finally:
    del bpy.types.Object.SimpleDeformGizmo_PropertyGroup

check(not addon._registered_modules, "stale check registered modules")
check(not preferences._HEADER_ATTACHED, "stale check attached a header callback")


original_props_register = props.register


def fail_props_register():
    raise RuntimeError("intentional registration failure")


props.register = fail_props_register
try:
    addon.register()
except RuntimeError as error:
    check(str(error) == "intentional registration failure",
          f"unexpected transaction error: {error}")
else:
    raise AssertionError("intentional module failure was swallowed")
finally:
    props.register = original_props_register

check(not addon._registered_modules, "failed transaction kept module ownership")
check(not preferences._PREFERENCES_REGISTERED,
      "failed transaction kept preferences registered")
check(not preferences._HEADER_ATTACHED,
      "failed transaction kept the menu callback")
check(not translate.SimpleDeform_CN._registered,
      "failed transaction kept translations registered")
check(not hasattr(bpy.types.Object, "SimpleDeformGizmo_PropertyGroup"),
      "failed transaction left the Object property")


addon.register()
check(hasattr(bpy.types.Object, "SimpleDeformGizmo_PropertyGroup"),
      "clean registration did not add Object properties")
check(preferences._HEADER_ATTACHED,
      "clean registration did not attach traditional header controls")
addon.unregister()
check(not hasattr(bpy.types.Object, "SimpleDeformGizmo_PropertyGroup"),
      "clean unregister left Object properties")
check(not preferences._HEADER_ATTACHED,
      "clean unregister left traditional header controls attached")

bpy.context.preferences.addons.remove(addon_entry)
check(utils.get_pref() is None, "missing preferences did not return None")
context = SimpleNamespace(
    object=None,
    space_data=SimpleNamespace(type="VIEW_3D", show_gizmo=True),
)
check(not utils.GizmoUtils.poll_simple_deform_public(context),
      "poll stayed active without an AddonPreferences entry")

print("SDH_REGISTRATION_CONFLICT::SUMMARY::PASS")
