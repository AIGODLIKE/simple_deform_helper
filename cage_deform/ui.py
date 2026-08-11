"""Cage deform sidebar panel."""
from __future__ import annotations

from bpy.app.translations import pgettext_iface as iface_
from bpy.types import Panel

from .core import (
    FFD_LATTICE_MARKER,
    FFD_NATIVE_EDIT_PROXY_MARKER,
    cage_axis_sample_count,
    cage_modifiers,
    deform_stack_modifiers,
    find_controller,
    is_cage_controller,
    is_cage_modifier,
    ordered_deform_types,
    resolve_context_deform,
    target_from_context,
    ffd_symmetry_axes,
)
from .merge import (
    eligible_selected_sources,
    is_deform_merge,
    live_merge_sources,
    merge_owner,
)
from .curve import (
    _curve_data_has_point_animation,
    active_curve_control,
    active_guide_point,
    curve_guide_object,
    curve_rest_guide_object,
)
from ..utils import GizmoUtils, get_pref

# Prefer literal bl_idnames so a stale/partial reload cannot NameError on
# operator class imports during Panel.draw.
_OP_ADD = "sdh.add_cage_deform"
_OP_ADD_CHAIN = "sdh.add_cage_chain"
_OP_ADD_LEGACY = "sdh.add_legacy_simple_deform"
_OP_SUBDIVIDE_CHAIN = "sdh.subdivide_cage_to_chain"
_OP_BATCH_CHAIN = "sdh.batch_edit_cage_chain"
_OP_RECONNECT_CHAIN = "sdh.reconnect_cage_chain"
_OP_FIT = "sdh.fit_cage_deform"
_OP_RESET_ENDS = "sdh.reset_cage_ends"
_OP_EDIT_FFD = "sdh.box_select_ffd_points"
_OP_EDIT_FFD_NATIVE = "sdh.edit_ffd_native"
_OP_SET_FFD_SELECTION_MODE = "sdh.set_ffd_selection_mode"
_OP_SET_FFD_SYMMETRY_AXES = "sdh.set_ffd_symmetry_axes"
_OP_RESET_FFD = "sdh.reset_cage_ffd"
_OP_EDIT_CURVE = "sdh.edit_curve_cage"
_OP_EDIT_CURVE_OBJECT = "sdh.edit_curve_cage_object"
_OP_EQUALIZE_CURVE = "sdh.equalize_curve_points"
_OP_ADD_CURVE_STATION = "sdh.add_curve_station"
_OP_REMOVE_CURVE_STATION = "sdh.remove_curve_station"
_OP_RESET_CURVE = "sdh.reset_curve_guide"
_OP_REBIND_CURVE = "sdh.rebind_curve_reference"
_OP_INSERT_KEYS = "sdh.insert_cage_keyframes"
_OP_DELETE_KEYS = "sdh.delete_cage_keyframes"
_OP_BAKE_ANIMATION = "sdh.bake_cage_animation"
_OP_SELECT_STAGE = "sdh.select_cage_stage"
_OP_SELECT_CONTROLLER = "sdh.select_cage_controller"
_OP_SELECT_TARGET = "sdh.select_cage_target"
_OP_TRANSFORM = "sdh.cage_transform"
_OP_SET_AXIS = "sdh.set_cage_axis"
_OP_DUPLICATE = "sdh.duplicate_cage_deform"
_OP_MOVE = "sdh.move_cage_deform"
_OP_REMOVE = "sdh.remove_cage_deform"
_OP_REMOVE_STACK = "sdh.remove_cage_stack"
_OP_ADD_DEFORM_LAYER = "sdh.add_deform_layer"
_OP_SELECT_DEFORM_LAYER = "sdh.select_deform_layer"
_OP_EXPAND_DEFORM_LAYERS = "sdh.expand_all_deform_layers"
_OP_REMOVE_DEFORM_LAYER = "sdh.remove_deform_layer"
_OP_TOGGLE_DEFORM_LAYER_MUTE = "sdh.toggle_deform_layer_mute"
_OP_MOVE_DEFORM_LAYER = "sdh.move_deform_layer"
_OP_CREATE_MERGE = "sdh.create_deform_merge"
_OP_CREATE_COLLECTION_MERGE = "sdh.create_collection_deform_merge"
_OP_SELECT_MERGE_SOURCE = "sdh.select_merge_source"
_OP_ADD_CAGE_TO_FINAL_SOURCE = "sdh.add_cage_to_merge_result"
_OP_RETURN_TO_MERGE = "sdh.return_to_deform_merge"
_OP_RELEASE_MERGE = "sdh.release_deform_merge"
_OP_SHOW_PREFERENCES = "preferences.addon_show"
_ADDON_MODULE = (
    __package__.rsplit(".", 1)[0]
    if "." in __package__ else __package__
)

# These values are passed to UILayout.operator(). Keep them in one table so
# the panel cannot accidentally use an Empty display enum as a UI icon enum.
STAGE_TYPE_ICONS = {
    "BEND": "EMPTY_SINGLE_ARROW",
    "TWIST": "FORCE_VORTEX",
    "TAPER": "FULLSCREEN_EXIT",
    "STRETCH": "EMPTY_ARROWS",
    "SHEAR": "MOD_WARP",
    "FFD": "MOD_LATTICE",
    "CURVE": "CURVE_DATA",
}

DEFORM_TYPE_ORDER = ("BEND", "TWIST", "TAPER", "STRETCH", "SHEAR")
DEFORM_TYPE_LABELS = {
    "BEND": "Bend",
    "TWIST": "Twist",
    "TAPER": "Taper",
    "STRETCH": "Stretch",
    "SHEAR": "Shear",
    "FFD": "FFD",
    "CURVE": "Curve",
}

_CHAIN_UUID = "_sdh_cage_chain_uuid"
_CHAIN_INDEX = "_sdh_cage_chain_index"
_CHAIN_COUNT = "_sdh_cage_chain_count"
_CHAIN_MODE = "_sdh_cage_chain_mode"


def _modifier_chain_metadata(modifier):
    group = getattr(modifier, "node_group", None)
    if group is None:
        return "", -1, 0, ""
    try:
        return (
            str(group.get(_CHAIN_UUID, "") or ""),
            int(group.get(_CHAIN_INDEX, -1)),
            int(group.get(_CHAIN_COUNT, 0)),
            str(group.get(_CHAIN_MODE, "") or "").upper(),
        )
    except (AttributeError, ReferenceError, TypeError, ValueError):
        return "", -1, 0, ""


def _enabled_deform_types(properties):
    """Return present layers in their user-authored execution order."""
    return tuple(ordered_deform_types(properties))


def _draw_curve_section_header(
        layout, properties, property_name, label, icon, *,
        action_property=None, action_icon="NONE"):
    """Draw one Curve-cage disclosure row with the common panel styling."""
    expanded = bool(getattr(properties, property_name, True))
    header = layout.row(align=True)
    header.prop(
        properties,
        property_name,
        text="",
        icon="TRIA_DOWN" if expanded else "TRIA_RIGHT",
        emboss=False,
    )
    header.label(text=label, icon=icon)
    if action_property:
        header.prop(
            properties,
            action_property,
            text="",
            icon=action_icon,
            toggle=True,
        )
    return expanded


def _draw_deform_layer(
        layout, properties, deform_type, index, count, active_index, muted,
        target=None, modifier=None, expanded=True, tree_controls=True):
    """Draw one compact tree row and the selected layer's parameters."""
    selected = index == active_index
    expanded = True if not tree_controls else bool(expanded)
    body = layout if expanded else None
    if tree_controls:
        # The selected blue row is the only disclosure control. Using
        # UILayout.panel here adds a redundant grey arrow beside it.
        header = layout.row(align=True)
        select = header.operator(
            _OP_SELECT_DEFORM_LAYER,
            text=DEFORM_TYPE_LABELS.get(deform_type, deform_type.title()),
            icon="TRIA_DOWN" if expanded else "TRIA_RIGHT",
            depress=selected,
        )
        select.index = index

        visibility = header.operator(
            _OP_TOGGLE_DEFORM_LAYER_MUTE,
            text="",
            icon="HIDE_ON" if muted else "HIDE_OFF",
            depress=muted,
        )
        visibility.deform_type = deform_type

        move_up_slot = header.row(align=True)
        move_up_slot.enabled = index > 0
        move_up = move_up_slot.operator(
            _OP_MOVE_DEFORM_LAYER, text="", icon="TRIA_UP")
        move_up.index = index
        move_up.direction = "UP"

        move_down_slot = header.row(align=True)
        move_down_slot.enabled = index < count - 1
        move_down = move_down_slot.operator(
            _OP_MOVE_DEFORM_LAYER, text="", icon="TRIA_DOWN")
        move_down.index = index
        move_down.direction = "DOWN"

        remove_slot = header.row(align=True)
        remove_slot.enabled = count > 1
        remove = remove_slot.operator(
            _OP_REMOVE_DEFORM_LAYER, text="", icon="X")
        remove.index = index

    if body is None:
        return

    if tree_controls:
        detail = (body or layout).split(factor=0.08, align=True)
        detail.column()
        parameters = detail.column(align=True)
    else:
        parameters = (body or layout).column(align=True)
    parameters.active = not muted
    if deform_type == "BEND":
        parameters.prop(properties, "bend_strength")
        parameters.prop(properties, "bend_direction")
    elif deform_type == "TWIST":
        parameters.prop(properties, "twist_strength")
    elif deform_type == "TAPER":
        parameters.prop(properties, "taper_factor")
    elif deform_type == "STRETCH":
        parameters.prop(properties, "stretch_factor")
        parameters.prop(properties, "preserve_volume")
    elif deform_type == "SHEAR":
        parameters.prop(properties, "shear_factors", text="X / Z")
    elif deform_type == "FFD":
        selection_row = parameters.row(align=True)
        selection_modes = set(properties.ffd_selection_modes)
        for mode, label, icon in (
                ("POINT", "Point", "VERTEXSEL"),
                ("LINE", "Line", "EDGESEL"),
                ("FACE", "Face", "FACESEL")):
            operator = selection_row.operator(
                _OP_SET_FFD_SELECTION_MODE,
                text=label,
                icon=icon,
                depress=mode in selection_modes,
            )
            operator.mode = mode
        symmetry_row = parameters.row(align=True)
        symmetry_row.prop(
            properties,
            "ffd_symmetry_enabled",
            text="Symmetry",
            toggle=True,
        )
        symmetry_axes_row = symmetry_row.row(align=True)
        symmetry_axes_row.enabled = bool(
            getattr(properties, "ffd_symmetry_enabled", False))
        enabled_axes = set(ffd_symmetry_axes(properties))
        for axis in ("U", "V", "W"):
            symmetry_axis = symmetry_axes_row.operator(
                _OP_SET_FFD_SYMMETRY_AXES,
                text=axis,
                depress=axis in enabled_axes,
            )
            symmetry_axis.axis = axis
        resolution_row = parameters.row(align=True)
        resolution_row.enabled = not bool(
            getattr(properties, "ffd_native_edit_mode_active", False))
        resolution_row.prop(properties, "ffd_resolution_u", text="U")
        resolution_row.prop(properties, "ffd_resolution_v", text="V")
        resolution_row.prop(properties, "ffd_resolution_w", text="W")
        interpolation_row = parameters.row(align=True)
        interpolation_row.enabled = resolution_row.enabled
        interpolation_row.prop(properties, "ffd_interpolation_u", text="U")
        interpolation_row.prop(properties, "ffd_interpolation_v", text="V")
        interpolation_row.prop(properties, "ffd_interpolation_w", text="W")
        guard_row = parameters.row(align=True)
        guard_row.prop(
            properties,
            "ffd_guard_mode",
            text="",
            icon="MOD_LATTICE",
        )
        points = getattr(properties, "ffd_points", ())
        if points:
            point_row = parameters.row(align=True)
            point_row.enabled = resolution_row.enabled
            point_row.prop(properties, "ffd_active_point", text="Point")
            active_index = min(max(
                int(getattr(properties, "ffd_active_point", 0)), 0),
                len(points) - 1,
            )
            point_row.prop(
                points[active_index], "edit_influence", text="Weight")
        select_row = parameters.row(align=True)
        edit = select_row.operator(
            _OP_EDIT_FFD,
            text="Object Edit",
            icon="EDITMODE_HLT",
            depress=bool(getattr(properties, "ffd_edit_mode_active", False)),
        )
        edit.toggle = True
        native = select_row.operator(
            _OP_EDIT_FFD_NATIVE,
            text="Native Edit",
            icon="LATTICE_DATA",
            depress=bool(getattr(
                properties, "ffd_native_edit_mode_active", False)),
        )
        select_row.prop(
            properties,
            "ffd_use_outside",
            text="Hollow FFD",
            icon="MOD_LATTICE",
            toggle=True,
        )
        select_row.operator(_OP_RESET_FFD, text="", icon="LOOP_BACK")
    elif deform_type == "CURVE":
        guide = curve_guide_object(target, modifier)

        if _draw_curve_section_header(
                parameters, properties, "show_curve_mapping_settings",
                "Curve Cage Controls", "CURVE_DATA"):
            mapping = parameters.column(align=True)
            mapping.prop(properties, "curve_control_mode", expand=True)
            binding_row = mapping.row(align=True)
            rest_guide = curve_rest_guide_object(target, modifier)
            if (
                    bool(getattr(properties, "curve_relative_binding", False)) and
                    rest_guide):
                binding_row.label(text="Rest Binding", icon="CHECKMARK")
                binding_row.operator(
                    _OP_REBIND_CURVE,
                    text="Rebind Curve",
                    icon="FILE_REFRESH",
                )
            else:
                binding_row.label(text="Absolute Guide", icon="CURVE_DATA")
                binding_row.operator(
                    _OP_REBIND_CURVE,
                    text="Bind Current Guide",
                    icon="LINKED",
                )
            mapping.prop(properties, "curve_mode", expand=True)
            behavior = mapping.row(align=True)
            behavior.prop(properties, "curve_closed")
            behavior.prop(properties, "curve_preserve_volume")
            mapping.prop(properties, "curve_resolution")
            profile_header = mapping.row(align=True)
            profile_header.label(
                text="Curve Profile",
                icon="DRIVER_ROTATIONAL_DIFFERENCE",
            )
            global_profile = mapping.row(align=True)
            global_profile.prop(
                properties, "curve_global_radius", text="Radius")
            global_profile.prop(
                properties, "curve_global_twist", text="Twist")

        if _draw_curve_section_header(
                parameters, properties, "show_curve_preset_settings",
                "Guide Preset", "CURVE_BEZCURVE"):
            preset = parameters.column(align=True)
            preset_locked = bool(
                guide is not None and
                _curve_data_has_point_animation(getattr(guide, "data", None)))
            preset_row = preset.row(align=True)
            preset_row.enabled = not preset_locked
            preset_row.prop(properties, "curve_preset", text="")
            preset_settings = preset.column(align=True)
            preset_settings.enabled = (
                not preset_locked and properties.curve_preset != "STRAIGHT")
            preset_shape = preset_settings.row(align=True)
            preset_shape.prop(properties, "curve_preset_amplitude")
            preset_shape.prop(properties, "curve_preset_cycles")
            preset_sampling = preset_settings.row(align=True)
            preset_sampling.prop(properties, "curve_preset_phase")
            preset_sampling.prop(properties, "curve_preset_points")
            if preset_locked:
                preset.label(
                    text="Presets are locked while guide points are animated",
                    icon="ERROR",
                )

        if _draw_curve_section_header(
                parameters, properties, "show_curve_edit_settings",
                "Curve Edit", "EDITMODE_HLT"):
            editing = parameters.column(align=True)
            edit_row = editing.row(align=True)
            edit_row.operator(
                _OP_EDIT_CURVE_OBJECT,
                text="Object Edit",
                icon="RESTRICT_SELECT_OFF",
                depress=bool(getattr(
                    properties, "curve_object_edit_active", False)),
            )
            edit_row.operator(
                _OP_EDIT_CURVE,
                text="Native Edit",
                icon="EDITMODE_HLT",
                depress=bool(getattr(
                    properties, "curve_edit_mode_active", False)),
            )
            edit_row.operator(_OP_RESET_CURVE, text="", icon="LOOP_BACK")
            equalize_row = editing.row(align=True)
            equalize_row.prop(properties, "curve_equalize_count")
            equalize_row.operator(
                _OP_EQUALIZE_CURVE,
                text="Equalize",
                icon="ARROW_LEFTRIGHT",
            )
            point = active_guide_point(guide)
            point_control = active_curve_control(
                getattr(properties, "id_data", None), guide)
            if point is not None and point_control is not None:
                point_header = editing.row(align=True)
                point_header.label(
                    text="Active Guide Point", icon="CURVE_BEZCIRCLE")
                point_header.prop(
                    properties,
                    "curve_point_global_falloff",
                    text="",
                    icon="WORLD",
                    toggle=True,
                )
                point_grid = editing.grid_flow(
                    row_major=True,
                    columns=2,
                    even_columns=True,
                    even_rows=True,
                    align=True,
                )
                point_grid.prop(
                    point_control, "edit_tilt", text="Point Roll")
                point_grid.prop(
                    point_control, "edit_radius", text="Point Radius")
                point_grid.prop(point_control, "edit_bevel", text="Bevel")
                point_grid.prop(point_control, "edit_tension", text="Tension")

        if _draw_curve_section_header(
                parameters, properties, "show_curve_cross_section_settings",
                "Cross Sections", "MESH_CIRCLE",
                action_property="curve_even_stations",
                action_icon="ARROW_LEFTRIGHT"):
            sections = parameters.column(align=True)
            station_row = sections.row()
            station_row.template_list(
                "SDH_UL_curve_stations", "",
                properties, "curve_stations",
                properties, "curve_active_station",
                rows=3,
            )
            station_actions = station_row.column(align=True)
            station_actions.operator(
                _OP_ADD_CURVE_STATION, text="", icon="ADD")
            station_actions.operator(
                _OP_REMOVE_CURVE_STATION, text="", icon="REMOVE")
            stations = properties.curve_stations
            if stations:
                index = min(max(
                    int(properties.curve_active_station), 0), len(stations) - 1)
                station = stations[index]
                factor_row = sections.row()
                factor_row.enabled = (
                    0 < index < len(stations) - 1 and
                    not bool(getattr(properties, "curve_even_stations", False)))
                factor_row.prop(station, "factor")
                scale_row = sections.row(align=True)
                scale_row.label(text="Scale")
                scale_row.prop(station, "scale", index=0, text="U")
                scale_row.prop(station, "scale", index=1, text="W")
                offset_row = sections.row(align=True)
                offset_row.label(text="Offset")
                offset_row.prop(station, "offset", index=0, text="U")
                offset_row.prop(station, "offset", index=1, text="W")
                station_profile = sections.row(align=True)
                station_profile.prop(station, "edit_radius", text="Radius")
                station_profile.prop(station, "edit_twist", text="Twist")


def _chain_info(target, modifier):
    """Return metadata for the active chain without relying on names/order."""
    group = getattr(modifier, "node_group", None) if modifier else None
    chain_uuid = str(group.get(_CHAIN_UUID, "")) if group else ""
    if not chain_uuid:
        return None
    stages = []
    for candidate in cage_modifiers(target):
        candidate_group = getattr(candidate, "node_group", None)
        if candidate_group and str(candidate_group.get(_CHAIN_UUID, "")) == chain_uuid:
            stages.append(candidate)
    if not stages:
        return None
    index = int(group.get(_CHAIN_INDEX, 0)) if group else 0
    count = int(group.get(_CHAIN_COUNT, len(stages))) if group else len(stages)
    mode = str(group.get(_CHAIN_MODE, "CONNECTED")) if group else "CONNECTED"
    return chain_uuid, index, max(count, len(stages)), mode, tuple(stages)


def _draw_topology_warning(layout, target, modifier, controller):
    """Explain sparse mesh bending without blocking the deformation workflow."""
    try:
        from ..utils import get_pref
        preferences = get_pref()
    except (ImportError, AttributeError, KeyError, RuntimeError, TypeError):
        preferences = None
    if preferences is None or not bool(getattr(preferences, "warn_low_topology", True)):
        return
    sample_count = cage_axis_sample_count(target, controller)
    if sample_count is None or sample_count >= 4:
        return
    try:
        active_index = tuple(target.modifiers).index(modifier)
    except (ValueError, TypeError):
        active_index = -1
    if active_index >= 0 and any(
            item.show_viewport and item.type in {"SUBSURF", "MULTIRES", "REMESH"}
            for item in tuple(target.modifiers)[:active_index]
    ):
        return
    warning = layout.box()
    warning.alert = True
    warning.label(
        text=iface_("Low topology on {axis}: {sample_count} levels").format(
            axis="Y", sample_count=sample_count),
        icon="ERROR",
    )
    warning.label(
        text=iface_("Simple Deform needs more segments to bend smoothly."),
    )


def _draw_deform_merge(layout, context, selected):
    """Draw the multi-object workflow before every cage control."""
    merge = selected if is_deform_merge(selected) else merge_owner(selected)
    box = layout.box()
    header = box.row(align=True)
    header.label(text="Multi-Object Deform", icon="NODETREE")

    if merge is None:
        eligible_count = len(eligible_selected_sources(context))
        create = box.row(align=True)
        create.enabled = eligible_count >= 2
        create.operator(
            _OP_CREATE_MERGE,
            text="Merge Selected for Deform",
            icon="NODETREE",
        )
        if eligible_count:
            count = create.row(align=True)
            count.alignment = "RIGHT"
            count.label(text=str(eligible_count))
        collection = box.row(align=True)
        collection.prop(
            context.scene,
            "sdh_deform_merge_collection",
            text="",
            icon="OUTLINER_COLLECTION",
        )
        collection.operator(
            _OP_CREATE_COLLECTION_MERGE,
            text="Merge Collection",
            icon="NODETREE",
        )
        return

    sources = live_merge_sources(merge)
    editing_source = selected if selected is not None and selected != merge else None
    source_header = box.row(align=True)
    source_header.label(
        text="Editing Source" if editing_source is not None else "Merged Sources",
        icon="OUTLINER_OB_MESH" if editing_source is not None
        else "OUTLINER_COLLECTION",
    )
    if editing_source is not None:
        source_header.label(text=editing_source.name)
    source_header.label(text=str(len(sources)))
    source_header.operator(
        _OP_RELEASE_MERGE,
        text="",
        icon="UNLINKED",
    )

    if editing_source is not None:
        edit_actions = box.row(align=True)
        edit_actions.operator(
            _OP_ADD_CAGE_TO_FINAL_SOURCE,
            text="Add Cage to Final Source",
            icon="MOD_SIMPLEDEFORM",
        )
        edit_actions.operator(
            _OP_RETURN_TO_MERGE,
            text="Return",
            icon="LOOP_BACK",
        )

    # A native UIList keeps the panel compact and scrollable for merges with
    # many source objects.  The active index is stored on the generated merge
    # object, so selecting a row remains stable while editing a source.
    list_row = box.row()
    list_row.template_list(
        "SDH_UL_merge_sources",
        "SDH_MERGE_SOURCES",
        merge,
        "sdh_deform_merge_sources",
        merge,
        "sdh_deform_merge_active_source_index",
        rows=4,
        type="DEFAULT",
    )


def _stack_viewport_controls(active_modifier, active_controller):
    """Return the matching header controls for the active stack stage."""
    if active_controller is not None:
        properties = active_controller.sdh_cage_deform
        return (
            properties,
            "show_axis_gizmo",
            "show_other_cages",
        )
    if (
            active_modifier is not None and
            active_modifier.type == "SIMPLE_DEFORM"
    ):
        preference = get_pref()
        if preference is not None:
            return (
                preference,
                "display_bend_axis_switch_gizmo",
                "show_other_stage_bounds",
            )
    return None


def _draw_deformation_stack(layout, target, active_modifier, active_controller):
    """Draw cages and native Simple Deform modifiers in evaluated order."""
    stages = deform_stack_modifiers(target)
    if not stages:
        return False

    stack = layout.box()
    stack_header = stack.row(align=True)
    stack_header.label(text="Deformation Stack", icon="MODIFIER")
    viewport_controls = _stack_viewport_controls(
        active_modifier, active_controller)
    if viewport_controls is not None:
        controls, axis_property, visibility_property = viewport_controls
        axis_toggle = stack_header.row(align=True)
        axis_toggle.alignment = "RIGHT"
        if active_controller is None:
            axis_toggle.enabled = active_modifier.deform_method == "BEND"
        axis_toggle.prop(
            controls,
            axis_property,
            text="",
            icon="ORIENTATION_GIMBAL",
            toggle=True,
        )
        stack_header.prop(
            controls,
            visibility_property,
            text="",
            icon=(
                "HIDE_OFF" if getattr(controls, visibility_property)
                else "HIDE_ON"
            ),
            toggle=True,
        )
    clear = stack_header.operator(
        _OP_REMOVE_STACK,
        text="",
        icon="TRASH",
    )
    clear.include_legacy = True

    for index, stage_modifier in enumerate(stages):
        row = stack.row(align=True)
        select = row.operator(
            _OP_SELECT_STAGE,
            text="",
            icon=(
                "RADIOBUT_ON" if stage_modifier == active_modifier
                else "RADIOBUT_OFF"),
        )
        select.index = index
        select.include_legacy = True
        row.prop(stage_modifier, "name", text="")

        cage_stage = is_cage_modifier(stage_modifier)
        stage_controller = (
            find_controller(target, stage_modifier) if cage_stage else None)
        stage_properties = getattr(
            stage_controller, "sdh_cage_deform", None)
        stage_types = (
            _enabled_deform_types(stage_properties)
            if stage_properties is not None else ())
        quick_select = row.operator(
            _OP_SELECT_STAGE,
            text="",
            icon=(
                STAGE_TYPE_ICONS.get(
                    stage_types[0] if stage_types else "BEND",
                    "EMPTY_AXIS",
                )
                if cage_stage else "MOD_SIMPLEDEFORM"),
        )
        quick_select.index = index
        quick_select.include_legacy = True

        if stage_properties is not None:
            row.prop(
                stage_properties,
                "stage_enabled",
                text="",
                icon=(
                    "RESTRICT_VIEW_OFF" if stage_properties.stage_enabled
                    else "RESTRICT_VIEW_ON"),
            )
        elif stage_modifier.type == "SIMPLE_DEFORM":
            row.prop(
                stage_modifier,
                "show_viewport",
                text="",
                icon=(
                    "RESTRICT_VIEW_OFF" if stage_modifier.show_viewport
                    else "RESTRICT_VIEW_ON"),
            )
        else:
            missing_state = row.row(align=True)
            missing_state.enabled = False
            missing_state.label(text="", icon="ERROR")

        chain_uuid, chain_index, chain_count, chain_mode = (
            _modifier_chain_metadata(stage_modifier)
            if cage_stage else ("", -1, 0, ""))
        connected_chain = bool(
            chain_uuid and chain_count > 1 and
            chain_mode in {"CHAINED", "CONNECTED"})
        order = row.row(align=True)
        order.enabled = len(stages) > 1
        earlier_slot = order.row(align=True)
        earlier_slot.enabled = bool(
            index > 0 and
            (not connected_chain or chain_index == 0))
        earlier = earlier_slot.operator(
            _OP_MOVE, text="", icon="TRIA_UP")
        earlier.index = index
        earlier.direction = "EARLIER"
        earlier.include_legacy = True
        later_slot = order.row(align=True)
        later_slot.enabled = bool(
            index < len(stages) - 1 and
            (not connected_chain or chain_index == chain_count - 1))
        later = later_slot.operator(
            _OP_MOVE, text="", icon="TRIA_DOWN")
        later.index = index
        later.direction = "LATER"
        later.include_legacy = True
        remove = row.operator(
            _OP_REMOVE,
            text="",
            icon="X",
        )
        remove.index = index
        remove.include_legacy = True
    return True


def _draw_legacy_deform_stage(layout, target, modifier):
    """Draw a native Simple Deform as a first-class unified stack stage."""
    if modifier is None or modifier.type != "SIMPLE_DEFORM":
        return False

    preference = get_pref()
    stage = layout.box()
    header = stage.row(align=True)
    header.label(text="Traditional Simple Deform", icon="MOD_SIMPLEDEFORM")
    if preference is not None:
        header.prop(
            preference,
            "show_gizmo",
            text="",
            icon="GIZMO",
            toggle=True,
        )

    operation = stage.column(align=True)
    operation.prop(modifier, "deform_method", expand=True)
    operation.prop(modifier, "deform_axis", expand=True)
    strength_path = (
        "angle" if modifier.deform_method in {"BEND", "TWIST"}
        else "factor")
    operation.prop(modifier, strength_path)

    limits = stage.column(align=True)
    limits.prop(modifier, "limits", index=0, text="Lower Limit")
    limits.prop(modifier, "limits", index=1, text="Upper Limit")

    origin = getattr(modifier, "origin", None)
    managed_origin = GizmoUtils.is_managed_origin(origin, target)
    origin_properties = (
        origin.SimpleDeformGizmo_PropertyGroup
        if origin is not None else target.SimpleDeformGizmo_PropertyGroup)
    origin_row = stage.row(align=True)
    origin_row.enabled = origin is None or managed_origin
    origin_row.prop(origin_properties, "origin_mode", text="Origin")
    if origin is not None and not managed_origin:
        protected = stage.box()
        protected.label(text="User Origin is protected", icon="LOCKED")
        protected.label(text="Follow-limit Origin modes are disabled.")

    if preference is not None:
        display = stage.column(align=True)
        display.label(text="Viewport Display", icon="GIZMO")
        display.prop(
            preference, "update_deform_wireframe", icon="MOD_WIREFRAME")
        display.prop(preference, "show_set_axis_button", icon="EMPTY_AXIS")
        display.prop(
            preference, "show_wireframe_in_front", icon="AXIS_FRONT")
        display.prop(preference, "modifiers_limits_tolerance")
        if preference.update_deform_wireframe:
            display.prop(preference, "wireframe_preview_fps")

    animation = stage.row(align=True)
    animation.operator(
        _OP_INSERT_KEYS, text="Insert Keys", icon="KEYFRAME")
    animation.operator(
        _OP_DELETE_KEYS, text="Delete Keys", icon="KEY_DEHLT")
    bake = stage.row(align=True)
    bake.enabled = target.type != "LATTICE"
    bake.operator(
        _OP_BAKE_ANIMATION,
        text="Bake Mesh Animation",
        icon="SHAPEKEY_DATA",
    )
    return True


class SDH_CAGE_PT_deform(Panel):
    bl_idname = "SDH_CAGE_PT_deform"
    bl_label = "Simple Deformer V2"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Simple Deformer V2"

    @classmethod
    def poll(cls, context):
        # Keep the category visible even when Blender starts with no active
        # object (or with a camera/light selected). Operators below still use
        # their own polls and remain disabled until a supported target exists.
        return True

    def draw_header(self, context):
        row = self.layout.row(align=True)
        professional = get_pref()
        if professional is not None:
            row.prop(
                professional,
                "professional_mode",
                text="",
                icon="TOOL_SETTINGS",
                toggle=True,
            )
        settings = row.operator(
            _OP_SHOW_PREFERENCES,
            text="",
            icon="PREFERENCES",
        )
        settings.module = _ADDON_MODULE

    def draw(self, context):
        layout = self.layout
        selected = getattr(context, "object", None)
        try:
            if selected not in tuple(getattr(context, "selected_objects", ())):
                selected = None
        except (ReferenceError, RuntimeError, TypeError):
            selected = None
        _draw_deform_merge(layout, context, selected)

        if (
                selected is not None and selected.type == "LATTICE" and
                not bool(selected.get(FFD_LATTICE_MARKER, False)) and
                not bool(selected.get(FFD_NATIVE_EDIT_PROXY_MARKER, False))
        ):
            add = layout.operator(
                _OP_ADD_LEGACY,
                text="Add Simple Deform (Legacy)",
                icon="MOD_SIMPLEDEFORM",
            )
            notice = layout.box()
            notice.label(
                text="Cage deformation is not supported for lattice objects",
                icon="INFO",
            )
            active_modifier = getattr(selected.modifiers, "active", None)
            _draw_deformation_stack(
                layout, selected, active_modifier, active_controller=None)
            _draw_legacy_deform_stage(layout, selected, active_modifier)
            return

        target = target_from_context(context)
        target_resolved, modifier, controller = resolve_context_deform(
            context, fallback=False)
        can_add_cage = target is not None

        for add_cage_type, cage_label, chain_label, icon in (
                ("STANDARD", "Add Standard Cage", "Add Standard Chain",
                 "MOD_SIMPLEDEFORM"),
                ("SHEAR", "Add Shear Cage", "Add Shear Chain",
                 STAGE_TYPE_ICONS["SHEAR"]),
                ("FFD", "Add FFD Cage", "Add FFD Chain",
                 STAGE_TYPE_ICONS["FFD"])):
            add_row = layout.row(align=True)
            add_row.enabled = can_add_cage
            add = add_row.operator(_OP_ADD, text=cage_label, icon=icon)
            add.cage_type = add_cage_type
            chain_add = add_row.operator(
                _OP_ADD_CHAIN, text=chain_label, icon="LINKED")
            chain_add.cage_type = add_cage_type
        curve_row = layout.row(align=True)
        curve_row.enabled = can_add_cage
        curve_add = curve_row.operator(
            _OP_ADD, text="Add Curve Cage", icon=STAGE_TYPE_ICONS["CURVE"])
        curve_add.cage_type = "CURVE"
        if target is None:
            box = layout.box()
            box.label(text="Select a supported target object first", icon="INFO")
            return

        legacy_row = layout.row(align=True)
        legacy_row.operator(
            _OP_ADD_LEGACY,
            text="Add Simple Deform (Legacy)",
            icon="MOD_SIMPLEDEFORM",
        )
        active_modifier = getattr(target.modifiers, "active", None)
        if not _draw_deformation_stack(
                layout, target, active_modifier, controller):
            box = layout.box()
            box.label(text="Independent cage deformation", icon="INFO")
            box.label(text="Combine ordered deformation layers in one cage.")
            return
        if active_modifier is not None and active_modifier.type == "SIMPLE_DEFORM":
            _draw_legacy_deform_stage(layout, target, active_modifier)
            return
        if (
                active_modifier is None or
                target_resolved is None or modifier is None or controller is None
        ):
            return

        properties = controller.sdh_cage_deform
        cage_type = str(getattr(properties, "cage_type", "STANDARD"))
        preference = get_pref()
        professional_mode = bool(
            getattr(preference, "professional_mode", False))

        _draw_topology_warning(layout, target, modifier, controller)

        chain = _chain_info(target, modifier)
        if chain is not None:
            chain_uuid, chain_index, chain_count, chain_mode, chain_stages = chain
            mode_label = {
                "CHAINED": "Chained",
                "CONNECTED": "Chained",
                "WITHIN_BOX": "Independent",
            }.get(chain_mode, chain_mode.replace("_", " ").title())
            chain_box = layout.box()
            chain_box.label(
                text=("Chained Cages" if chain_mode in {"CHAINED", "CONNECTED"}
                      else "Independent Cage Chain"),
                icon="LINKED",
            )
            if chain_mode in {"CHAINED", "CONNECTED"} and chain_count > 1:
                chain_box.label(
                    text="Chained cage segments keep their internal order",
                    icon="LOCKED",
                )
            segment_row = chain_box.row(align=True)
            segment_row.label(text="Segment", icon="LINKED")
            segment_row.label(text=f"{chain_index + 1} / {chain_count}")
            segment_row.label(text="|")
            segment_row.label(text=mode_label)
            if chain_mode in {"CHAINED", "CONNECTED"}:
                chain_box.prop(
                    properties,
                    "sync_shared_end_scale",
                    text="Sync Shared End Scale",
                    icon="LINKED",
                )
            if chain_index > 0:
                chain_box.prop(properties, "chain_gap", text="Gap Before")
            chain_action = chain_box.row(align=True)
            reconnect = chain_action.operator(
                _OP_RECONNECT_CHAIN,
                text="Reconnect Chain",
                icon="CONSTRAINT",
            )
            reconnect.chain_id = chain_uuid
            chain_action.prop(
                properties,
                "show_chain_batch_edit",
                text="Batch Edit",
                icon="PRESET",
                toggle=True,
            )
            if properties.show_chain_batch_edit:
                batch = chain_box.column(align=True)
                batch.prop(properties, "chain_batch_scope")
                batch.prop(properties, "chain_batch_operation")
                operation = properties.chain_batch_operation
                if operation in {"END_SCALE", "END_OFFSET"}:
                    batch.prop(
                        properties, "chain_batch_end_side", expand=True)
                    batch.prop(
                        properties,
                        "chain_batch_scale" if operation == "END_SCALE"
                        else "chain_batch_offset",
                    )
                elif operation == "GAP":
                    batch.prop(properties, "chain_batch_gap")
                    batch.prop(properties, "chain_batch_preserve_span")
                elif operation == "DEFORMATION":
                    batch.prop(properties, "chain_batch_deform_type")
                    deform_type = properties.chain_batch_deform_type
                    if deform_type in {"BEND", "BEND_DIRECTION", "TWIST"}:
                        batch.prop(properties, "chain_batch_angle")
                    elif deform_type == "SHEAR":
                        batch.prop(properties, "chain_batch_shear")
                    else:
                        batch.prop(properties, "chain_batch_factor")
                else:
                    batch.prop(properties, "chain_batch_stage_enabled")
        elif cage_type != "CURVE":
            layout.operator(
                _OP_SUBDIVIDE_CHAIN,
                text="Subdivide to Chained Cages",
                icon="MOD_ARRAY",
            )

        chain_locked = bool(
            chain is not None and chain[3] in {"CHAINED", "CONNECTED"})

        shape = layout.box()
        shape_header = shape.row(align=True)
        enabled_types = _enabled_deform_types(properties)
        layer_count = len(enabled_types)
        active_index = min(max(
            int(getattr(properties, "active_deform_layer", 0)), 0),
            max(layer_count - 1, 0),
        )
        muted_types = set(getattr(properties, "muted_deform_types", ()))
        if cage_type == "STANDARD":
            shape_header.label(
                text="Deformation Layers", icon="MOD_SIMPLEDEFORM")
            type_slot = shape_header.row(align=True)
            type_slot.enabled = (
                not chain_locked and not bool(getattr(
                    properties, "ffd_native_edit_mode_active", False)))
            type_slot.prop(properties, "cage_type", text="")
            expanded_types = set(getattr(
                properties, "expanded_deform_layers", enabled_types))
            if any(item not in expanded_types for item in enabled_types):
                shape_header.operator(
                    _OP_EXPAND_DEFORM_LAYERS,
                    text="",
                    icon="FULLSCREEN_ENTER",
                )
            for index, deform_type in enumerate(enabled_types):
                _draw_deform_layer(
                    shape, properties, deform_type, index, layer_count,
                    active_index, deform_type in muted_types,
                    target=target, modifier=modifier,
                    expanded=deform_type in expanded_types,
                )
        else:
            deform_type = enabled_types[0]
            cage_labels = {
                "SHEAR": "Shear Cage",
                "FFD": "FFD Cage",
                "CURVE": "Curve Cage",
            }
            shape_header.label(
                text=cage_labels.get(cage_type, "Cage"),
                icon=STAGE_TYPE_ICONS[deform_type],
            )
            type_slot = shape_header.row(align=True)
            type_slot.enabled = (
                not chain_locked and not bool(getattr(
                    properties, "ffd_native_edit_mode_active", False)))
            type_slot.prop(properties, "cage_type", text="")
            visibility = shape_header.operator(
                _OP_TOGGLE_DEFORM_LAYER_MUTE,
                text="",
                icon="HIDE_ON" if deform_type in muted_types else "HIDE_OFF",
                depress=deform_type in muted_types,
            )
            visibility.deform_type = deform_type
            _draw_deform_layer(
                shape, properties, deform_type, 0, 1, 0,
                deform_type in muted_types,
                target=target, modifier=modifier, tree_controls=False)

        missing_types = (() if cage_type != "STANDARD" else tuple(
            deform_type for deform_type in DEFORM_TYPE_ORDER
            if deform_type not in enabled_types))
        if missing_types:
            shape.separator()
            shape.label(text="Add Deformation", icon="ADD")
            add_grid = shape.grid_flow(
                row_major=True,
                columns=2,
                even_columns=True,
                even_rows=True,
                align=True,
            )
            for deform_type in missing_types:
                add = add_grid.operator(
                    _OP_ADD_DEFORM_LAYER,
                    text=DEFORM_TYPE_LABELS[deform_type],
                    icon=STAGE_TYPE_ICONS[deform_type],
                )
                add.deform_type = deform_type

        if cage_type != "CURVE":
            mode_row = shape.row()
            mode_row.enabled = (
                not chain_locked and not bool(getattr(
                    properties, "ffd_native_edit_mode_active", False)))
            mode_row.prop(properties, "mode", expand=True)
            if cage_type != "FFD":
                origin_row = shape.row()
                origin_row.prop(properties, "origin")

        cage = layout.box()
        cage_header = cage.row(align=True)
        cage_header.prop(
            properties,
            "show_cage_controls",
            text="",
            icon=("TRIA_DOWN" if properties.show_cage_controls
                  else "TRIA_RIGHT"),
            emboss=False,
        )
        cage_header.label(text="Cage Controls", icon="CUBE")
        if preference is not None:
            cage_header.prop(
                preference,
                "show_wireframe_in_front",
                text="",
                icon="AXIS_FRONT",
                toggle=True,
            )
        cage_header.prop(
            properties, "show_cage", text="",
            icon="HIDE_OFF" if properties.show_cage else "HIDE_ON",
            toggle=True)
        if properties.show_cage_controls:
            edit_row = cage.row(align=True)
            for tool, label, icon in (
                    ("MOVE", "Move", "ARROW_LEFTRIGHT"),
                    ("ROTATE", "Rotate", "DRIVER_ROTATIONAL_DIFFERENCE"),
                    ("SCALE", "Scale", "FULLSCREEN_ENTER")):
                operator = edit_row.operator(
                    _OP_TRANSFORM, text=label, icon=icon)
                operator.tool = tool

            fit_row = cage.row(align=True)
            fit_chain = bool(
                chain is not None and chain[3] in {"CHAINED", "CONNECTED"})
            fit_row.operator(
                _OP_FIT,
                text="Align & Fit Chain" if fit_chain else "Align & Fit",
                icon="FULLSCREEN_ENTER",
            )
            if not fit_chain:
                fit_row.prop(
                    properties,
                    "auto_sync_upstream",
                    text="Auto Sync",
                    icon="FILE_REFRESH",
                    toggle=True,
                )
            if is_cage_controller(context.object):
                fit_row.operator(
                    _OP_SELECT_TARGET,
                    text="Return to Object",
                    icon="OBJECT_DATA",
                )
            else:
                fit_row.operator(
                    _OP_SELECT_CONTROLLER,
                    text="Select Cage",
                    icon="EMPTY_AXIS",
                )

            if "BEND" in enabled_types:
                gizmo_row = cage.row(align=True)
                gizmo_row.prop(
                    properties, "show_direction_handle", text="Show Twist")

        # Compact mode keeps the common cage manipulation and action rows.
        # Professional mode continues into the less frequently used axis,
        # independent-end, and numeric sections below.
        if not professional_mode:
            actions = layout.row(align=True)
            actions.operator(
                _OP_DUPLICATE,
                text="Duplicate",
                icon="DUPLICATE",
            )
            actions.operator(
                _OP_REMOVE,
                text="Remove Stage",
                icon="TRASH",
            )
            animation = layout.row(align=True)
            animation.operator(
                _OP_INSERT_KEYS,
                text="Insert Keys",
                icon="KEYFRAME",
            )
            animation.operator(
                _OP_DELETE_KEYS,
                text="Delete Keys",
                icon="KEY_DEHLT",
            )
            layout.operator(
                _OP_BAKE_ANIMATION,
                text="Bake Mesh Animation",
                icon="SHAPEKEY_DATA",
            )
            return

        axis_header = cage.row(align=True)
        axis_header.prop(
            properties,
            "show_deform_axis",
            text="",
            icon=("TRIA_DOWN" if properties.show_deform_axis
                  else "TRIA_RIGHT"),
            emboss=False,
        )
        axis_header.label(text="Deform Axis", icon="EMPTY_AXIS")
        if properties.show_deform_axis:
            auto_axis = cage.row(align=True)
            operator = auto_axis.operator(
                _OP_SET_AXIS,
                text="Auto",
                depress=properties.alignment == "AUTO",
            )
            operator.alignment = "AUTO"
            axis_grid = cage.grid_flow(
                row_major=True, columns=3, even_columns=True, even_rows=True,
                align=True)
            for alignment, label in (
                    ("POS_X", "X+"), ("POS_Y", "Y+"), ("POS_Z", "Z+"),
                    ("NEG_X", "X-"), ("NEG_Y", "Y-"), ("NEG_Z", "Z-")):
                operator = axis_grid.operator(
                    _OP_SET_AXIS, text=label,
                    depress=properties.alignment == alignment)
                operator.alignment = alignment
        ends_header = cage.row(align=True)
        ends_header.prop(
            properties,
            "show_end_shape_settings",
            text="",
            icon=("TRIA_DOWN" if properties.show_end_shape_settings
                  else "TRIA_RIGHT"),
            emboss=False,
        )
        ends_header.label(text="Independent Ends", icon="FULLSCREEN_ENTER")
        if properties.show_end_shape_settings:
            ends = cage.box()
            ends.prop(properties, "limit_boundaries_to_object")
            ends.prop(properties, "show_boundary_handles")
            ends.prop(properties, "show_end_handles")
            for side, label in (("top", "Top"), ("bottom", "Bottom")):
                ends.label(text=label)
                scale_row = ends.row(align=True)
                scale_row.label(text="Scale")
                scale_row.prop(properties, f"{side}_scale", index=0, text="X")
                scale_row.prop(properties, f"{side}_scale", index=1, text="Z")
                offset_row = ends.row(align=True)
                offset_row.label(text="Offset")
                offset_row.prop(properties, f"{side}_offset", index=0, text="X")
                offset_row.prop(properties, f"{side}_offset", index=1, text="Z")
            ends.operator(
                _OP_RESET_ENDS,
                text="Reset Independent Ends",
                icon="LOOP_BACK",
            )

        numeric_header = cage.row(align=True)
        numeric_header.prop(
            properties,
            "show_numeric_controls",
            text="",
            icon=("TRIA_DOWN" if properties.show_numeric_controls
                  else "TRIA_RIGHT"),
            emboss=False,
        )
        numeric_header.label(text="Numeric Controls", icon="PRESET")
        if properties.show_numeric_controls:
            numeric = cage.column(align=True)
            numeric.prop(properties, "size")
            numeric.prop(controller, "location")
            numeric.prop(controller, "rotation_mode", text="Rotation Mode")
            rotation_property = {
                "QUATERNION": "rotation_quaternion",
                "AXIS_ANGLE": "rotation_axis_angle",
            }.get(getattr(controller, "rotation_mode", "XYZ"), "rotation_euler")
            numeric.prop(controller, rotation_property, text="Rotation")

        actions = layout.row(align=True)
        actions.operator(
            _OP_DUPLICATE,
            text="Duplicate",
            icon="DUPLICATE",
        )
        actions.operator(
            _OP_REMOVE,
            text="Remove Stage",
            icon="TRASH",
        )
        animation = layout.row(align=True)
        animation.operator(
            _OP_INSERT_KEYS,
            text="Insert Keys",
            icon="KEYFRAME",
        )
        animation.operator(
            _OP_DELETE_KEYS,
            text="Delete Keys",
            icon="KEY_DEHLT",
        )
        layout.operator(
            _OP_BAKE_ANIMATION,
            text="Bake Mesh Animation",
            icon="SHAPEKEY_DATA",
        )
