"""Save and re-apply complete cage deformation stacks as JSON presets.

A preset stores every managed stage on the target in stack order: cage
type, layer order and parameters, end shapes, FFD point grids, Curve
guide splines with stations, controller transforms, and chain grouping.
Loading appends the stages to the active target and rebuilds chains
with fresh UUIDs.
"""
from __future__ import annotations

import json
import math
import re
import uuid
from pathlib import Path

import bpy
from bpy.app.translations import pgettext_iface as iface_
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator

from . import core


_PRESET_VERSION = 1
_PRESET_ENUM_CACHE = []


def _top_package():
    return __package__.rsplit(".", 1)[0]


def _preset_directory(create=True):
    try:
        path = bpy.utils.extension_path_user(
            _top_package(), path="stack_presets", create=create)
        if path:
            return Path(path)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    path = bpy.utils.user_resource(
        "CONFIG", path="simple_deform_helper/stack_presets", create=create)
    return Path(path)


def _sanitize_name(name):
    cleaned = re.sub(r"[^\w\- ]+", "", str(name or "")).strip()
    return cleaned or "Cage Stack"


def _preset_path(name):
    return _preset_directory() / f"{_sanitize_name(name)}.json"


def list_presets():
    try:
        directory = _preset_directory(create=False)
        return tuple(sorted(
            path.stem for path in directory.glob("*.json")))
    except (OSError, RuntimeError, TypeError, ValueError):
        return ()


def _json_safe(value):
    if isinstance(value, set):
        return {"__set__": sorted(str(item) for item in value)}
    if isinstance(value, str):
        return value
    if hasattr(value, "__len__"):
        return [
            item if isinstance(item, (bool, int, str)) else float(item)
            for item in value
        ]
    if isinstance(value, (bool, int, float)):
        return value
    return str(value)


def _serialize_curve_guide(target, modifier):
    try:
        from . import curve
        guide = curve.curve_guide_object(target, modifier)
    except (ImportError, AttributeError, ReferenceError, RuntimeError,
            TypeError):
        return None
    data = getattr(guide, "data", None)
    if data is None or not data.splines:
        return None
    spline = data.splines[0]
    if spline.type != "BEZIER":
        return None
    points = []
    for point in spline.bezier_points:
        points.append({
            "co": [float(v) for v in point.co],
            "handle_left": [float(v) for v in point.handle_left],
            "handle_right": [float(v) for v in point.handle_right],
            "handle_left_type": str(point.handle_left_type),
            "handle_right_type": str(point.handle_right_type),
            "tilt": float(point.tilt),
            "radius": float(point.radius),
        })
    return {"cyclic": bool(spline.use_cyclic_u), "points": points}


def _serialize_stage(target, modifier, controller):
    properties = controller.sdh_cage_deform
    values = {}
    for name in core.CONTROLLER_STATE_PROPERTIES:
        value = (
            core.curve_control_mode_identifier(properties)
            if name == "curve_control_mode" else getattr(properties, name))
        values[name] = _json_safe(value)
    node_group = getattr(modifier, "node_group", None)
    chain_uuid = str(
        node_group.get("_sdh_cage_chain_uuid", "")) if node_group else ""
    stage = {
        "name": str(modifier.name),
        "properties": values,
        "location": [float(v) for v in controller.location],
        "rotation_euler": [
            float(v) for v in core._controller_rotation_xyz(controller)],
        "ffd_points": [
            {
                "name": str(point.name),
                "offset": [float(v) for v in point.offset],
                "influence": float(getattr(point, "influence", 1.0)),
                "selected": bool(point.selected),
            }
            for point in getattr(properties, "ffd_points", ())
        ],
        "curve_points": [
            {
                "name": str(point.name),
                "selected": bool(point.selected),
                "handles_linked": bool(point.handles_linked),
                "bevel": float(point.bevel),
                "tension": float(point.tension),
            }
            for point in getattr(properties, "curve_points", ())
        ],
        "curve_stations": [
            {
                "name": str(station.name),
                "factor": float(station.factor),
                "scale": [float(v) for v in station.scale],
                "offset": [float(v) for v in station.offset],
                "radius": float(station.radius),
                "twist": float(station.twist),
                "selected": bool(station.selected),
            }
            for station in getattr(properties, "curve_stations", ())
        ],
    }
    if str(getattr(properties, "cage_type", "STANDARD")) == "CURVE":
        guide = _serialize_curve_guide(target, modifier)
        if guide is not None:
            stage["curve_guide"] = guide
    if chain_uuid:
        try:
            from .chain import stage_chain_index
            stage_index = int(stage_chain_index(modifier))
        except (ImportError, AttributeError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            stage_index = 0
        stage["chain"] = {
            "uuid": chain_uuid,
            "index": stage_index,
            "mode": str(
                node_group.get("_sdh_cage_chain_mode", "") or "CHAINED"),
        }
    return stage


def serialize_stack(target):
    stages = []
    for modifier in core.cage_modifiers(target):
        controller = core.find_controller(target, modifier)
        if controller is None:
            continue
        stages.append(_serialize_stage(target, modifier, controller))
    return {
        "format": "sdh_cage_stack_preset",
        "version": _PRESET_VERSION,
        "stages": stages,
    }


def _restore_value(value):
    if isinstance(value, dict) and "__set__" in value:
        return set(value["__set__"])
    if isinstance(value, list):
        return tuple(value)
    return value


def _apply_stage_properties(controller, data):
    properties = controller.sdh_cage_deform
    values = dict(data.get("properties", {}))
    pointer = core._pointer(controller)
    core._SYNCING.add(pointer)
    try:
        # Cage type first: its update callback creates FFD/Curve companions
        # that later property writes depend on.
        ordered_names = ("cage_type",) + tuple(
            name for name in core.CONTROLLER_STATE_PROPERTIES
            if name != "cage_type")
        for name in ordered_names:
            if name not in values:
                continue
            try:
                setattr(properties, name, _restore_value(values[name]))
            except (AttributeError, TypeError, ValueError):
                continue
        if hasattr(properties, "ffd_points"):
            properties.ffd_points.clear()
        for entry in data.get("ffd_points", ()):
            point = properties.ffd_points.add()
            point.name = str(entry.get("name", ""))
            point.offset = tuple(entry.get("offset", (0.0, 0.0, 0.0)))
            point.influence = min(max(
                float(entry.get("influence", 1.0)), 0.0), 1.0)
            point.selected = bool(entry.get("selected", False))
        if data.get("ffd_points"):
            core.ensure_ffd_point_collection(properties)
        if hasattr(properties, "curve_stations"):
            properties.curve_stations.clear()
            for entry in data.get("curve_stations", ()):
                station = properties.curve_stations.add()
                station.name = str(entry.get("name", ""))
                station.factor = float(entry.get("factor", 0.5))
                station.scale = tuple(entry.get("scale", (1.0, 1.0)))
                station.offset = tuple(entry.get("offset", (0.0, 0.0)))
                station.radius = float(entry.get("radius", 1.0))
                station.twist = float(entry.get("twist", 0.0))
                station.selected = bool(entry.get("selected", False))
        try:
            controller.rotation_mode = "XYZ"
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            pass
        controller.location = tuple(data.get("location", (0.0, 0.0, 0.0)))
        controller.rotation_euler = tuple(
            data.get("rotation_euler", (0.0, 0.0, 0.0)))
        size = values.get("size")
        if size:
            controller.scale = tuple(
                max(float(value), core.EPSILON) * 0.5 for value in size)
    finally:
        core._SYNCING.discard(pointer)


def _apply_curve_guide(target, modifier, controller, data):
    guide_data = data.get("curve_guide")
    if not guide_data:
        return
    try:
        from . import curve
        guide, _stations = curve.ensure_curve_companions(
            target, modifier, controller)
    except (ImportError, AttributeError, ReferenceError, RuntimeError,
            TypeError, ValueError):
        return
    if guide is None or getattr(guide, "data", None) is None:
        return
    points = tuple(guide_data.get("points", ()))
    if len(points) < 2:
        return
    data_block = guide.data
    data_block.splines.clear()
    spline = data_block.splines.new("BEZIER")
    spline.bezier_points.add(len(points) - 1)
    spline.use_cyclic_u = bool(guide_data.get("cyclic", False))
    for point, entry in zip(spline.bezier_points, points):
        point.co = tuple(entry.get("co", (0.0, 0.0, 0.0)))
        point.handle_left = tuple(entry.get("handle_left", point.co))
        point.handle_right = tuple(entry.get("handle_right", point.co))
        point.handle_left_type = str(entry.get("handle_left_type", "AUTO"))
        point.handle_right_type = str(entry.get("handle_right_type", "AUTO"))
        point.tilt = float(entry.get("tilt", 0.0))
        point.radius = float(entry.get("radius", 1.0))
    data_block.update_tag()
    properties = controller.sdh_cage_deform
    try:
        curve.ensure_curve_point_collection(
            properties, guide,
            reset=len(properties.curve_points) != len(points))
        stored_points = tuple(data.get("curve_points", ()))
        if len(stored_points) == len(properties.curve_points):
            for point, entry in zip(properties.curve_points, stored_points):
                point.name = str(entry.get("name", point.name))
                point.selected = bool(entry.get("selected", False))
                point.handles_linked = bool(
                    entry.get("handles_linked", point.handles_linked))
                point.bevel = float(entry.get("bevel", point.bevel))
                point.tension = float(entry.get("tension", point.tension))
        curve.apply_all_curve_point_handles(controller)
        curve.sync_curve_cage_relation(controller, force=True)
    except (AttributeError, ReferenceError, RuntimeError, TypeError,
            ValueError):
        pass


def _preflight_preset(payload):
    """Validate the complete payload before creating any Blender data."""
    if not isinstance(payload, dict):
        raise RuntimeError(iface_("Not a cage stack preset file"))
    if str(payload.get("format")) != "sdh_cage_stack_preset":
        raise RuntimeError(iface_("Not a cage stack preset file"))
    if int(payload.get("version", 0)) != _PRESET_VERSION:
        raise RuntimeError(iface_("Unsupported cage stack preset version"))
    stages = payload.get("stages")
    if not isinstance(stages, list) or not stages:
        raise RuntimeError(iface_("The preset contains no cage stages"))
    allowed_properties = set(core.CONTROLLER_STATE_PROPERTIES)
    for index, stage in enumerate(stages, start=1):
        if not isinstance(stage, dict):
            raise RuntimeError(iface_(
                "Preset stage {index} is invalid").format(index=index))
        values = stage.get("properties")
        if not isinstance(values, dict):
            raise RuntimeError(iface_(
                "Preset stage {index} has no properties").format(index=index))
        unknown = set(values) - allowed_properties
        if unknown:
            raise RuntimeError(iface_(
                "Preset stage {index} contains unknown properties: "
                "{names}").format(index=index, names=", ".join(sorted(unknown))))
        cage_type = str(values.get("cage_type", "STANDARD"))
        if cage_type not in core.CAGE_TYPES:
            raise RuntimeError(iface_(
                "Preset stage {index} has an unsupported cage type").format(
                    index=index))
        resolution = tuple(int(values.get(
            f"ffd_resolution_{axis}", core.FFD_DEFAULT_RESOLUTION[position]))
            for position, axis in enumerate("uvw"))
        limits = (
            core.FFD_MAX_RESOLUTION_U,
            core.FFD_MAX_RESOLUTION_V,
            core.FFD_MAX_RESOLUTION_W,
        )
        if any(
                value < core.FFD_MIN_RESOLUTION or value > maximum
                for value, maximum in zip(resolution, limits)):
            raise RuntimeError(iface_(
                "Preset stage {index} exceeds the FFD 6 x 6 x 6 limit").format(
                    index=index))
        if stage.get("ffd_points") and (
                len(stage["ffd_points"]) != math.prod(resolution)):
            raise RuntimeError(iface_(
                "Preset stage {index} has an invalid FFD point count").format(
                    index=index))
    return tuple(stages)


def _rollback_created_stages(target, created):
    """Remove every helper and datablock owned by a failed preset load."""
    for modifier, controller in reversed(tuple(created)):
        node_group = getattr(modifier, "node_group", None)
        if modifier in tuple(getattr(target, "modifiers", ())):
            core.remove_ffd_lattice(target, modifier)
            try:
                from .curve import remove_curve_companions
                remove_curve_companions(target, modifier)
            except (ImportError, ReferenceError, RuntimeError):
                pass
            target.modifiers.remove(modifier)
        if controller is not None and core.is_cage_controller(controller):
            try:
                bpy.data.objects.remove(controller, do_unlink=True)
            except (ReferenceError, RuntimeError):
                pass
        if (
                node_group is not None and node_group.users == 0 and
                node_group.get(core.MODIFIER_MARKER, False)):
            try:
                bpy.data.node_groups.remove(node_group)
            except (ReferenceError, RuntimeError):
                pass
    core.remove_unused_control_collections()


def apply_stack_preset(context, target, payload, report=None):
    """Append every stage stored in ``payload`` to ``target``."""
    stages = _preflight_preset(payload)
    chain_groups = {}
    created = []
    previous_active = getattr(getattr(target, "modifiers", None), "active", None)
    try:
        for data in stages:
            modifier, controller, _previous = core.create_deform_stage(
                context, target, name=str(data.get("name") or "Cage Deform"))
            created.append((modifier, controller))
            _apply_stage_properties(controller, data)
            _apply_curve_guide(target, modifier, controller, data)
            core.sync_controller(
                controller, pull_transform=False, sync_mode="push")
            chain_info = data.get("chain")
            if chain_info and chain_info.get("uuid"):
                chain_groups.setdefault(
                    str(chain_info["uuid"]),
                    {"mode": str(chain_info.get("mode", "CHAINED")),
                     "members": []},
                )["members"].append(
                    (int(chain_info.get("index", 0)), modifier, controller))
        core.ensure_ffd_companion_order(target)
        from .chain import reconnect_chain, set_stage_metadata
        for group in chain_groups.values():
            members = sorted(group["members"], key=lambda item: item[0])
            new_uuid = str(uuid.uuid4())
            for order, (_index, modifier, controller) in enumerate(members):
                set_stage_metadata(
                    modifier, controller, new_uuid, order, len(members),
                    group["mode"] or "CHAINED")
            if len(members) >= 2 and group["mode"] in {
                    "CHAINED", "CONNECTED"}:
                reconnect_chain(target, new_uuid)
    except Exception:
        _rollback_created_stages(target, created)
        if previous_active in tuple(getattr(target, "modifiers", ())):
            target.modifiers.active = previous_active
        core._activate(context, target)
        core.refresh_controller_display(context, force=True)
        raise
    if created:
        target.modifiers.active = created[-1][0]
        core._activate(context, created[-1][1])
    core.refresh_controller_display(context, force=True)
    return len(created)


def _preset_enum_items(_self, _context):
    global _PRESET_ENUM_CACHE
    names = list_presets()
    _PRESET_ENUM_CACHE = [
        (name, name, iface_("Saved cage stack preset")) for name in names
    ] or [("NONE", iface_("No presets saved"), "")]
    return _PRESET_ENUM_CACHE


class SDH_OT_save_cage_stack_preset(Operator):
    bl_idname = "sdh.save_cage_stack_preset"
    bl_label = "Save Stack Preset"
    bl_description = (
        "Save every managed cage stage on this object as a reusable preset")
    bl_options = {"REGISTER"}

    preset_name: StringProperty(
        name="Preset Name",
        default="Cage Stack",
    )

    @classmethod
    def poll(cls, context):
        target = core.deform_stack_target_from_context(context)
        return bool(target and core.cage_modifiers(target))

    def invoke(self, context, _event):
        target = core.deform_stack_target_from_context(context)
        if target is not None:
            self.preset_name = f"{target.name} Stack"
        return context.window_manager.invoke_props_dialog(self, width=320)

    def execute(self, context):
        target = core.deform_stack_target_from_context(context)
        if target is None:
            return {"CANCELLED"}
        payload = serialize_stack(target)
        if not payload["stages"]:
            self.report({"WARNING"}, iface_("No managed cage stages found"))
            return {"CANCELLED"}
        path = _preset_path(self.preset_name)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(payload, indent=1, sort_keys=True),
                encoding="utf-8")
        except (OSError, TypeError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            iface_("Saved {count} stages to preset {name}").format(
                count=len(payload["stages"]), name=path.stem),
        )
        return {"FINISHED"}


class SDH_OT_load_cage_stack_preset(Operator):
    bl_idname = "sdh.load_cage_stack_preset"
    bl_label = "Load Stack Preset"
    bl_description = (
        "Append a saved cage stack preset to the active object")
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "preset"

    preset: EnumProperty(
        name="Preset",
        items=_preset_enum_items,
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        target = core.target_from_context(context)
        return bool(
            target and target.type in core.SUPPORTED_TYPES and
            list_presets())

    def invoke(self, context, _event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if self.preset in {"", "NONE"}:
            return {"CANCELLED"}
        target = core.target_from_context(context)
        if target is None:
            return {"CANCELLED"}
        path = _preset_path(self.preset)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        if str(payload.get("format")) != "sdh_cage_stack_preset":
            self.report({"ERROR"}, iface_("Not a cage stack preset file"))
            return {"CANCELLED"}
        try:
            count = apply_stack_preset(context, target, payload, self.report)
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            iface_("Added {count} stages from preset {name}").format(
                count=count, name=self.preset),
        )
        return {"FINISHED"}


class SDH_OT_delete_cage_stack_preset(Operator):
    bl_idname = "sdh.delete_cage_stack_preset"
    bl_label = "Delete Stack Preset"
    bl_description = "Delete one saved cage stack preset"
    bl_options = {"REGISTER"}
    bl_property = "preset"

    preset: EnumProperty(
        name="Preset",
        items=_preset_enum_items,
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, _context):
        return bool(list_presets())

    def invoke(self, context, _event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, _context):
        if self.preset in {"", "NONE"}:
            return {"CANCELLED"}
        path = _preset_path(self.preset)
        try:
            path.unlink()
        except OSError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            iface_("Deleted preset {name}").format(name=self.preset),
        )
        return {"FINISHED"}


classes = (
    SDH_OT_save_cage_stack_preset,
    SDH_OT_load_cage_stack_preset,
    SDH_OT_delete_cage_stack_preset,
)
