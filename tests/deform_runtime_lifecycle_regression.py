"""Lifecycle coverage for lazy handlers and owned deformation helpers."""
from __future__ import annotations

import importlib
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


def activate(*objects, active):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.hide_set(False)
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active


def cube(name, location=(0.0, 0.0, 0.0)):
    bpy.ops.mesh.primitive_cube_add(location=location)
    result = bpy.context.object
    result.name = name
    return result


addon = importlib.import_module(PACKAGE)
entry = None
if not INSTALLED_PACKAGE:
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon.register()

core = importlib.import_module(f"{PACKAGE}.cage_deform.core")
curve = importlib.import_module(f"{PACKAGE}.cage_deform.curve")
merge = importlib.import_module(f"{PACKAGE}.cage_deform.merge")

try:
    check(
        core._runtime_load_discovery in bpy.app.handlers.load_post,
        "the lightweight cage load-discovery handler was not registered",
    )
    merge._preview_runtime_maintenance_timer()
    check(
        not merge.preview_handlers_registered(),
        "merge preview handlers were active without a merge object",
    )
    check(
        merge._preview_load_post in bpy.app.handlers.load_post,
        "the lightweight merge load handler was not registered",
    )

    first = cube("Lazy Merge First", (-2.0, 0.0, 0.0))
    second = cube("Lazy Merge Second", (2.0, 0.0, 0.0))
    activate(first, second, active=first)
    check(
        bpy.ops.sdh.create_deform_merge() == {"FINISHED"},
        "could not create the lazy-handler merge",
    )
    merged = bpy.context.object
    check(
        merge.preview_handlers_registered(),
        "the first merge did not enable preview handlers",
    )
    check(
        merge.release_deform_merge(bpy.context, merged),
        "could not release the lazy-handler merge",
    )
    merge._preview_runtime_maintenance_timer()
    check(
        not merge.preview_handlers_registered(),
        "preview handlers survived after the last merge was released",
    )
    for source in (first, second):
        bpy.data.objects.remove(source, do_unlink=True)

    target = cube("Owned Helper Cleanup")
    for cage_type in ("STANDARD", "FFD", "CURVE"):
        activate(target, active=target)
        check(
            bpy.ops.sdh.add_cage_deform(cage_type=cage_type) == {"FINISHED"},
            f"could not create {cage_type} stage for helper cleanup",
        )
    activate(target, active=target)
    check(
        bpy.ops.sdh.add_legacy_simple_deform() == {"FINISHED"},
        "could not create traditional stage for helper cleanup",
    )

    controllers = tuple(
        obj for obj in bpy.data.objects
        if core.is_cage_controller(obj) and core.find_target(obj) == target)
    ffd_helpers = tuple(
        obj for obj in bpy.data.objects
        if bool(obj.get(core.FFD_LATTICE_MARKER, False)) and obj.parent == target)
    curve_helpers = tuple(
        obj for obj in bpy.data.objects
        if curve.is_curve_helper(obj) and obj.parent == target)
    managed_origins = tuple(
        obj for obj in bpy.data.objects
        if core.GizmoUtils.is_managed_origin(obj, target))
    check(len(controllers) == 3, "not every cage created an owned controller")
    check(ffd_helpers, "FFD helper lattice was not created")
    check(curve_helpers, "Curve guide helpers were not created")
    check(managed_origins, "traditional managed Origin was not created")

    curve_controller = next(
        controller for controller in controllers
        if controller.sdh_cage_deform.cage_type == "CURVE")
    controller_uuid = str(curve_controller.get(core.CONTROLLER_UUID, ""))
    curve_controller.name = "Renamed Stable Curve Controller"
    check(
        curve.controller_from_uuid(controller_uuid) == curve_controller,
        "Curve controller UUID lookup broke after a rename",
    )

    helper_names = {
        obj.name for obj in
        (*controllers, *ffd_helpers, *curve_helpers, *managed_origins)
    }
    helper_data = {
        (obj.data.__class__.__name__, obj.data.name)
        for obj in (*ffd_helpers, *curve_helpers)
        if getattr(obj, "data", None) is not None
    }
    node_group_names = {
        modifier.node_group.name
        for modifier in target.modifiers
        if core.is_cage_modifier(modifier)
    }

    core._ORPHAN_HELPER_OBJECT_COUNT = len(bpy.data.objects)
    bpy.data.objects.remove(target, do_unlink=True)
    check(
        core._cleanup_orphans_after_object_count_change(),
        "target deletion did not trigger object-count orphan cleanup",
    )
    check(
        not (helper_names & set(bpy.data.objects.keys())),
        "owned helper objects survived deletion of their target",
    )
    for data_type, name in helper_data:
        collection = {
            "Lattice": bpy.data.lattices,
            "Curve": bpy.data.curves,
            "Mesh": bpy.data.meshes,
        }.get(data_type)
        check(
            collection is None or collection.get(name) is None,
            f"orphan helper data survived: {data_type} {name}",
        )
    check(
        not (node_group_names & set(bpy.data.node_groups.keys())),
        "unused cage node groups survived target deletion",
    )
    check(
        not core.refresh_runtime_handler_state(),
        "runtime handler state still reported a managed deformation",
    )
    check(
        not core._RUNTIME_HANDLERS_REGISTERED,
        "cage runtime handlers survived after all managed stages disappeared",
    )
    check(
        not bpy.app.timers.is_registered(core._selection_watch_timer),
        "selection watcher survived after all managed stages disappeared",
    )
    check(
        core._runtime_load_discovery in bpy.app.handlers.load_post,
        "load discovery disappeared with the last managed stage",
    )
    print("SDH_DEFORM_RUNTIME_LIFECYCLE::PASS")
finally:
    if not INSTALLED_PACKAGE:
        addon.unregister()
        check(
            core._runtime_load_discovery not in bpy.app.handlers.load_post,
            "cage load discovery survived add-on unregister",
        )
        bpy.context.preferences.addons.remove(entry)
