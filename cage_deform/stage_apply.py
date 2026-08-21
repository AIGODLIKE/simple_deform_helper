"""Destructive apply (collapse) for managed cage and legacy stages.

Applying a stage writes its evaluated deformation into the mesh with
Blender's native ``modifier_apply`` and then removes every helper the
stage owned: controller Empty, FFD lattice + companion modifier + scope
vertex group, Curve guide/rest/station objects, and the orphaned node
group. Chained stages compact and reconnect exactly like stage removal.
"""
from __future__ import annotations

import bpy
from bpy.app.translations import pgettext_iface as iface_
from bpy.props import BoolProperty, IntProperty
from bpy.types import Operator

from . import core
from ..stages import StageCache
from ..utils import GizmoUtils


def _stage_helper_objects(target, modifier):
    """Collect helper objects owned by one stage before it is applied."""
    helpers = []
    try:
        lattice = core.ffd_lattice_object(target, modifier)
        if lattice is not None:
            helpers.append(lattice)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    try:
        from . import curve
        for finder in (
                curve.curve_guide_object,
                curve.curve_rest_guide_object,
                curve.curve_station_object,
        ):
            try:
                companion = finder(target, modifier)
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                companion = None
            if companion is not None:
                helpers.append(companion)
    except (ImportError, ReferenceError, RuntimeError):
        pass
    return tuple(dict.fromkeys(helpers))


def _stage_modifier_names_in_order(target, modifier):
    """Return this stage's modifier names (GN + FFD companion) stack-ordered."""
    lattice = None
    try:
        lattice = core.ffd_lattice_object(target, modifier)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        lattice = None
    modifier_uuid = core.cage_modifier_uuid(modifier)
    names = []
    for candidate in tuple(getattr(target, "modifiers", ())):
        if candidate == modifier:
            names.append(str(candidate.name))
            continue
        if (
                getattr(candidate, "type", None) == "LATTICE" and
                lattice is not None and
                getattr(candidate, "object", None) == lattice and
                str(lattice.get(
                    core.FFD_LATTICE_MODIFIER_MARKER, "")) == modifier_uuid
        ):
            names.append(str(candidate.name))
    return tuple(names)


def _remove_helper_object(helper):
    data = getattr(helper, "data", None)
    try:
        bpy.data.objects.remove(helper, do_unlink=True)
    except (ReferenceError, RuntimeError, TypeError):
        return
    if data is None or getattr(data, "users", 1) != 0:
        return
    for collection_name in ("lattices", "curves"):
        collection = getattr(bpy.data, collection_name, None)
        if collection is None:
            continue
        try:
            collection.remove(data)
            return
        except (ReferenceError, RuntimeError, TypeError):
            continue


def _finish_edit_sessions(context):
    core.finish_ffd_edit_sessions(context, restore_target=False)
    try:
        from .curve import (
            finish_curve_edit_sessions,
            finish_curve_object_edit_sessions,
        )
        finish_curve_object_edit_sessions(context, restore_target=False)
        finish_curve_edit_sessions(context, restore_target=False)
    except (ImportError, ReferenceError, RuntimeError):
        pass


def apply_cage_stage(context, target, modifier, report=None):
    """Apply one managed cage stage destructively; return True on success."""
    controller = core.find_controller(target, modifier)
    node_group = getattr(modifier, "node_group", None)
    chain_uuid = str(
        node_group.get("_sdh_cage_chain_uuid", "")) if node_group else ""
    chain_mode = str(
        node_group.get("_sdh_cage_chain_mode", "")) if node_group else ""
    helpers = _stage_helper_objects(target, modifier)
    scope_group_name = ""
    try:
        scope_group_name = core._ffd_scope_vertex_group_name(modifier)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        scope_group_name = ""
    modifier_names = _stage_modifier_names_in_order(target, modifier)

    core._activate(context, target)
    applied = []
    for name in modifier_names:
        try:
            result = bpy.ops.object.modifier_apply(modifier=name)
        except RuntimeError as error:
            if report is not None:
                report({"ERROR"}, str(error).strip())
            if applied and report is not None:
                report(
                    {"WARNING"},
                    iface_(
                        "Partially applied stage; {name} could not be "
                        "applied").format(name=name),
                )
            return False
        if "FINISHED" not in result:
            if report is not None:
                report(
                    {"ERROR"},
                    iface_("Could not apply modifier {name}").format(
                        name=name),
                )
            return False
        applied.append(name)

    for helper in helpers:
        _remove_helper_object(helper)
    if scope_group_name and getattr(target, "type", None) == "MESH":
        groups = getattr(target, "vertex_groups", None)
        group = (
            groups.get(scope_group_name)
            if groups is not None and hasattr(groups, "get") else None)
        if group is not None:
            try:
                groups.remove(group)
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                pass
    if controller is not None and core.is_cage_controller(controller):
        try:
            bpy.data.objects.remove(controller, do_unlink=True)
        except (ReferenceError, RuntimeError):
            pass
    if (
            node_group is not None and node_group.users == 0 and
            node_group.get(core.MODIFIER_MARKER, False)
    ):
        try:
            bpy.data.node_groups.remove(node_group)
        except (ReferenceError, RuntimeError):
            pass
    if chain_uuid:
        try:
            from .chain import compact_chain, reconnect_chain
            live_chain = compact_chain(target, chain_uuid)
            if len(live_chain) >= 2 and chain_mode == "CHAINED":
                reconnect_chain(target, chain_uuid)
        except (ImportError, AttributeError, ReferenceError, RuntimeError):
            pass
    return True


def apply_legacy_stage(context, target, modifier, report=None):
    """Apply one traditional Simple Deform stage and clean its origin."""
    origin = getattr(modifier, "origin", None)
    core._activate(context, target)
    try:
        result = bpy.ops.object.modifier_apply(modifier=modifier.name)
    except RuntimeError as error:
        if report is not None:
            report({"ERROR"}, str(error).strip())
        return False
    if "FINISHED" not in result:
        return False
    if origin is not None and GizmoUtils.is_managed_origin(origin, target):
        still_used = any(
            getattr(other, "origin", None) == origin
            for other in getattr(target, "modifiers", ())
            if other.type == "SIMPLE_DEFORM"
        )
        if not still_used:
            try:
                bpy.data.objects.remove(origin, do_unlink=True)
            except (ReferenceError, RuntimeError):
                pass
    return True


def _post_apply_refresh(context, target):
    core.remove_unused_control_collections()
    StageCache.rebuild(context, target)
    remaining = core.deform_stack_modifiers(target)
    if remaining:
        target.modifiers.active = remaining[0]
    next_modifier = getattr(target.modifiers, "active", None)
    next_controller = (
        core.find_controller(target, next_modifier)
        if core.is_cage_modifier(next_modifier) else None)
    core._activate(context, next_controller or target)
    core.activate_cage_workspace_tool(
        context,
        getattr(
            getattr(next_controller, "sdh_cage_deform", None),
            "cage_type", ""),
    )
    core.refresh_controller_display(context, force=True)


def _applicable_target(context):
    target = core.deform_stack_target_from_context(context)
    if target is None or getattr(target, "type", None) != "MESH":
        return None
    return target


class SDH_OT_apply_cage_stage(Operator):
    bl_idname = "sdh.apply_cage_stage"
    bl_label = "Apply Stage"
    bl_description = (
        "Apply this deformation stage to the mesh and remove its cage "
        "controls"
    )
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(default=-1, min=-1, options={"SKIP_SAVE"})
    include_legacy: BoolProperty(
        default=False, options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        target = _applicable_target(context)
        return bool(target and core.deform_stack_modifiers(target))

    def execute(self, context):
        target = _applicable_target(context)
        if target is None:
            self.report(
                {"ERROR"},
                iface_("Apply requires a mesh target"),
            )
            return {"CANCELLED"}
        stages = (
            core.deform_stack_modifiers(target)
            if self.include_legacy else core.cage_modifiers(target))
        if self.index >= 0:
            if self.index >= len(stages):
                return {"CANCELLED"}
            modifier = stages[self.index]
        else:
            _target, modifier, _controller = core.resolve_context_deform(
                context)
            if modifier is None:
                modifier = getattr(target.modifiers, "active", None)
            if modifier not in core.deform_stack_modifiers(target):
                return {"CANCELLED"}
        _finish_edit_sessions(context)
        applied = (
            apply_legacy_stage(context, target, modifier, self.report)
            if modifier.type == "SIMPLE_DEFORM"
            else apply_cage_stage(context, target, modifier, self.report))
        if not applied:
            return {"CANCELLED"}
        _post_apply_refresh(context, target)
        self.report({"INFO"}, iface_("Applied deformation stage"))
        return {"FINISHED"}


class SDH_OT_apply_cage_stack(Operator):
    bl_idname = "sdh.apply_cage_stack"
    bl_label = "Apply All Stages"
    bl_description = (
        "Apply every managed cage and traditional Simple Deform stage to "
        "the mesh, in stack order, and remove their controls"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        target = _applicable_target(context)
        return bool(target and core.deform_stack_modifiers(target))

    def execute(self, context):
        target = _applicable_target(context)
        if target is None:
            self.report({"ERROR"}, iface_("Apply requires a mesh target"))
            return {"CANCELLED"}
        _finish_edit_sessions(context)
        applied = 0
        while True:
            stages = core.deform_stack_modifiers(target)
            if not stages:
                break
            modifier = stages[0]
            success = (
                apply_legacy_stage(context, target, modifier, self.report)
                if modifier.type == "SIMPLE_DEFORM"
                else apply_cage_stage(context, target, modifier, self.report))
            if not success:
                if applied:
                    _post_apply_refresh(context, target)
                self.report(
                    {"WARNING"},
                    iface_(
                        "Applied {count} stages before stopping").format(
                        count=applied),
                )
                return {"CANCELLED"}
            applied += 1
        _post_apply_refresh(context, target)
        self.report(
            {"INFO"},
            iface_("Applied {count} deformation stages").format(
                count=applied),
        )
        return {"FINISHED"}


classes = (
    SDH_OT_apply_cage_stage,
    SDH_OT_apply_cage_stack,
)
