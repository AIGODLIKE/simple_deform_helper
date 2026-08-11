"""Verify installed extension state across isolated Blender restarts."""
from __future__ import annotations

import importlib
import os
import tomllib
from pathlib import Path

import bpy


REPO_MODULE = os.environ.get("SDH_TEST_REPO", "sdh_test")
PACKAGE_ID = "simple_deform_helper"
MODULE = os.environ.get(
    "SDH_TEST_MODULE", f"bl_ext.{REPO_MODULE}.{PACKAGE_ID}")
EXPECTED_VERSION = os.environ["SDH_EXPECTED_VERSION"]
ACTION = os.environ["SDH_LIFECYCLE_ACTION"]


def enabled():
    return MODULE in {
        entry.module for entry in bpy.context.preferences.addons
    }


def installed_manifest():
    repository = next(
        (
            item for item in bpy.context.preferences.extensions.repos
            if item.module == REPO_MODULE
        ),
        None,
    )
    if repository is None:
        raise RuntimeError(f"isolated repository {REPO_MODULE!r} is missing")
    path = Path(repository.directory) / PACKAGE_ID / "blender_manifest.toml"
    with path.open("rb") as stream:
        return path, tomllib.load(stream)


path, manifest = installed_manifest()
if manifest.get("id") != PACKAGE_ID:
    raise RuntimeError(f"installed manifest has wrong ID: {manifest!r}")
if manifest.get("version") != EXPECTED_VERSION:
    raise RuntimeError(
        "installed manifest has wrong version: "
        f"{manifest.get('version')!r} != {EXPECTED_VERSION!r}")

if ACTION == "check_enabled":
    if not enabled():
        raise RuntimeError("extension is disabled after an enabled restart")
    imported = importlib.import_module(MODULE)
    if imported.__name__ != MODULE:
        raise RuntimeError("enabled extension imported under the wrong module")
elif ACTION == "disable":
    if not enabled():
        raise RuntimeError("extension was already disabled")
    if bpy.ops.preferences.addon_disable(module=MODULE) != {"FINISHED"}:
        raise RuntimeError("could not disable the installed extension")
    bpy.ops.wm.save_userpref()
elif ACTION == "check_disabled":
    if enabled():
        raise RuntimeError("extension was enabled after a disabled restart")
elif ACTION == "reenable":
    if enabled():
        raise RuntimeError("extension was already enabled")
    if bpy.ops.preferences.addon_enable(module=MODULE) != {"FINISHED"}:
        raise RuntimeError("could not re-enable the installed extension")
    bpy.ops.wm.save_userpref()
else:
    raise RuntimeError(f"unknown lifecycle action: {ACTION!r}")

print(
    "SDH_INSTALLED_STATE::PASS::"
    f"action={ACTION}::enabled={int(enabled())}::"
    f"version={manifest['version']}::path={path}")
