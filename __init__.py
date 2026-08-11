from . import (
    ops,
    ui,
    gizmo,
    props,
    update,
    msgbus,
    translate,
    preferences,
    cage_deform,
)

import logging

import bpy


_LOGGER = logging.getLogger(__name__)
_EXTENSION_ID = "simple_deform_helper"
module_tuple = (
    translate,
    preferences,
    props,
    cage_deform,
    ops,
    update,
    msgbus,
    gizmo,
    ui,
)

_registered_modules = []


def _duplicate_installations():
    """Return other enabled repositories carrying this extension ID."""
    try:
        entries = tuple(bpy.context.preferences.addons)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return ()
    current = __package__
    return tuple(
        entry.module for entry in entries
        if entry.module != current and
        entry.module.rsplit(".", 1)[-1] == _EXTENSION_ID
    )


def _validate_registration_environment():
    duplicates = _duplicate_installations()
    if duplicates:
        raise RuntimeError(
            "Another Simple Deform Helper installation is enabled: "
            f"{duplicates[0]}. Disable or uninstall the duplicate, restart "
            "Blender, then enable this extension."
        )
    if hasattr(bpy.types.Object, "SimpleDeformGizmo_PropertyGroup"):
        raise RuntimeError(
            "A previous Simple Deform Helper registration is still loaded. "
            "Restart Blender, then enable this extension again."
        )


def _rollback_modules(modules):
    for item in reversed(tuple(modules)):
        try:
            item.unregister()
        except Exception:
            _LOGGER.exception(
                "Failed to roll back module %s", getattr(item, "__name__", item))


def register():
    if _registered_modules:
        return
    _validate_registration_environment()
    completed = []
    try:
        for item in module_tuple:
            item.register()
            completed.append(item)
    except Exception:
        _rollback_modules(completed)
        raise
    _registered_modules.extend(completed)


def unregister():
    if not _registered_modules:
        return
    _rollback_modules(tuple(_registered_modules))
    _registered_modules.clear()
