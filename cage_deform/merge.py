"""Live multi-object Geometry Nodes merge used as a deformation target."""
from __future__ import annotations

import uuid
import time

import bpy
from bpy.app.handlers import persistent
from bpy.app.translations import pgettext_iface as iface_
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, PropertyGroup, UIList
from bpy_extras import view3d_utils
from mathutils import Matrix, Vector

from ..stages import hide_runtime_object


MERGE_MARKER = "_sdh_deform_merge"
MERGE_UUID = "_sdh_deform_merge_uuid"
MERGE_GROUP_MARKER = "_sdh_deform_merge_group"
SOURCE_MARKER = "_sdh_deform_merge_source"
SOURCE_PREVIEW_MARKER = "_sdh_deform_merge_source_preview"
SOURCE_PREVIEW_GROUP_MARKER = "_sdh_deform_merge_source_preview_group"
SOURCE_INDEX_ATTRIBUTE = "sdh_merge_source_index"
FINAL_SOURCE_STAGE_MARKER = "_sdh_deform_merge_final_source_stage"
FINAL_SOURCE_INDEX = "_sdh_deform_merge_final_source_index"
MERGE_UV_LAYER_PREFIX = "SDH Merge UV"
GROUP_VERSION = 1
PREVIEW_REFRESH_INTERVAL = 1.0 / 30.0

CONVERTIBLE_TYPES = {
    "MESH",
    "CURVE",
    "SURFACE",
    "FONT",
    "META",
    "CURVES",
    "POINTCLOUD",
}

_addon_keymaps = []
_preview_pending = set()
_preview_refresh_running = False
_preview_last_refresh = 0.0
_preview_handlers_registered = False
_merge_registry = {}
_preview_registry = {}

# Kept as a source string so Blender's translation system can expose the
# interaction in the status bar and the sidebar with the same wording.
MERGE_EDIT_HINT = (
    "Click a merged part to switch source | "
    "Double-click blank to return | Esc or Right Mouse exits"
)


class SDHMergeSource(PropertyGroup):
    """Persistent source pointer and its pre-merge viewport state."""

    object: PointerProperty(type=bpy.types.Object)
    original_hide: BoolProperty(default=False)
    original_hide_viewport: BoolProperty(default=False)
    original_hide_render: BoolProperty(default=False)
    original_hide_select: BoolProperty(default=False)
    original_show_in_front: BoolProperty(default=False)
    original_display_type: StringProperty(default="TEXTURED")
    # Joining Geometry Nodes inputs exposes one global active/render UV layer.
    # Keep the source metadata so the temporary common layer can be removed
    # and the exact pre-merge UV selection restored on release.
    original_mesh_data: PointerProperty(type=bpy.types.Mesh)
    original_uv_active: StringProperty(default="")
    original_uv_render: StringProperty(default="")
    merge_uv_name: StringProperty(default="")
    merge_uv_owned: BoolProperty(default=False)
    # A transient evaluated result used only while this source is being edited.
    # Keeping the pointer on the entry makes cleanup deterministic when the
    # source, merge, or file is removed during an active edit session.
    final_preview: PointerProperty(
        type=bpy.types.Object,
        options={"SKIP_SAVE"},
    )


class SDH_UL_merge_sources(UIList):
    """Compact, scrollable source list used by the multi-object panel.

    The source collection is kept on the generated merge object so the list
    follows the live Geometry Nodes input order.  Each row remains an edit
    action, preserving the previous one-click source workflow while Blender's
    native list supplies scrolling and an active-row highlight.
    """

    bl_idname = "SDH_UL_merge_sources"
    bl_label = "Merged Sources"

    def filter_items(self, _context, data, property_name):
        items = getattr(data, property_name, ())
        # Keep every row visible, including stale entries whose source pointer
        # is missing.  The latter are rendered with an error marker so users
        # can diagnose a broken merge instead of silently losing a list row.
        return [self.bitflag_filter_item] * len(items), []

    def draw_item(
            self, _context, layout, data, item, _icon, _active_data,
            _active_propname, index, _flt_flag=0):
        source = getattr(item, "object", None)
        row = layout.row(align=True)
        if source is None:
            row.label(text="(Missing source)", icon="ERROR")
            return
        # Once a modal source-edit session is active, list clicks only switch
        # its source.  Invoking another operator here would stack modal
        # handlers every time the user selected a different row.
        row.operator_context = (
            "EXEC_DEFAULT" if _active_source_index(data) >= 0
            else "INVOKE_DEFAULT"
        )
        edit = row.operator(
            "sdh.select_merge_source",
            text=source.name,
            icon="OUTLINER_OB_MESH",
        )
        edit.index = index


def _selected_object(context):
    obj = getattr(context, "object", None)
    if obj is None:
        return None
    try:
        return obj if obj in tuple(context.selected_objects) else None
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return None


def is_deform_merge(obj):
    try:
        return bool(obj and obj.type == "MESH" and obj.get(MERGE_MARKER, False))
    except (AttributeError, ReferenceError, TypeError):
        return False


def _register_merge(merge):
    """Register one live merge by its persistent UUID."""
    if not is_deform_merge(merge):
        return ""
    try:
        identifier = str(merge.get(MERGE_UUID, "") or "")
    except (AttributeError, ReferenceError, TypeError):
        return ""
    if identifier:
        _merge_registry[identifier] = merge
    return identifier


def _unregister_merge(merge_or_identifier):
    try:
        identifier = (
            str(merge_or_identifier)
            if isinstance(merge_or_identifier, str) else
            str(merge_or_identifier.get(MERGE_UUID, "") or "")
        )
    except (AttributeError, ReferenceError, TypeError):
        identifier = ""
    if identifier:
        _merge_registry.pop(identifier, None)


def _registered_merges(*, active_only=False):
    """Return live registered merges without scanning ``bpy.data.objects``."""
    result = []
    for identifier, merge in tuple(_merge_registry.items()):
        try:
            if (not is_deform_merge(merge) or
                    str(merge.get(MERGE_UUID, "") or "") != identifier):
                raise ReferenceError
            if active_only and _active_source_index(merge) < 0:
                continue
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            _merge_registry.pop(identifier, None)
            continue
        result.append(merge)
    return tuple(result)


def _track_preview(preview):
    pointer = _rna_pointer(preview)
    if pointer:
        _preview_registry[pointer] = preview


def _untrack_preview(preview):
    pointer = _rna_pointer(preview)
    if pointer:
        _preview_registry.pop(pointer, None)


def _rebuild_preview_registry():
    """Rebuild runtime indices once after load, undo, or registration."""
    _merge_registry.clear()
    _preview_registry.clear()
    try:
        objects = tuple(bpy.data.objects)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return 0
    for obj in objects:
        try:
            if is_deform_merge(obj):
                _register_merge(obj)
            elif obj.get(SOURCE_PREVIEW_MARKER, False):
                _track_preview(obj)
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            continue
    return len(_merge_registry)


def merge_owner(obj):
    if obj is None or is_deform_merge(obj):
        return None
    try:
        owner = obj.sdh_deform_merge_owner
    except (AttributeError, ReferenceError, RuntimeError):
        return None
    return owner if is_deform_merge(owner) else None


def merge_from_context(context):
    obj = _selected_object(context)
    if is_deform_merge(obj):
        return obj
    return merge_owner(obj)


def live_merge_sources(merge):
    if not is_deform_merge(merge):
        return ()
    sources = []
    try:
        entries = tuple(merge.sdh_deform_merge_sources)
    except (AttributeError, ReferenceError, RuntimeError):
        return ()
    for index, entry in enumerate(entries):
        try:
            source = entry.object
        except (AttributeError, ReferenceError):
            source = None
        if source is not None:
            sources.append((index, entry, source))
    return tuple(sources)


def eligible_selected_sources(context):
    try:
        selected = tuple(context.selected_objects)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return ()
    return tuple(
        obj for obj in selected
        if obj is not None and obj.type in CONVERTIBLE_TYPES and
        not is_deform_merge(obj)
    )


def collection_merge_sources(collection):
    """Return recursively collected merge sources and the skipped count."""
    if collection is None:
        return (), 0
    try:
        objects = tuple(collection.all_objects)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return (), 0
    eligible = tuple(sorted(
        (
            obj for obj in objects
            if obj is not None and obj.type in CONVERTIBLE_TYPES and
            not is_deform_merge(obj) and merge_owner(obj) is None
        ),
        key=lambda obj: str(getattr(obj, "name_full", obj.name)),
    ))
    return eligible, max(len(objects) - len(eligible), 0)


def _activate_only(context, obj):
    try:
        for selected in tuple(context.selected_objects):
            selected.select_set(False)
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    obj.hide_set(False)
    obj.hide_viewport = False
    obj.hide_select = False
    obj.select_set(True)
    context.view_layer.objects.active = obj


def _convert_sources_to_mesh(context, sources):
    converted = []
    for source in sources:
        if source.type == "MESH":
            converted.append(source)
            continue
        source_name = source.name
        _activate_only(context, source)
        try:
            result = bpy.ops.object.convert(target="MESH", keep_original=False)
        except (AttributeError, RuntimeError, TypeError) as error:
            raise RuntimeError(
                iface_("Could not convert {name} to a mesh").format(
                    name=source_name)
            ) from error
        candidate = getattr(context, "object", None)
        if "FINISHED" not in result or candidate is None or candidate.type != "MESH":
            raise RuntimeError(
                iface_("Could not convert {name} to a mesh").format(
                    name=source_name)
            )
        converted.append(candidate)
    return tuple(converted)


def _new_geometry_socket(node_group, name, in_out):
    node_group.interface.new_socket(
        name=name,
        in_out=in_out,
        socket_type="NodeSocketGeometry",
    )


def _input_socket(node, name, fallback_index):
    socket = node.inputs.get(name)
    return socket if socket is not None else node.inputs[fallback_index]


def _typed_input(node, name, socket_type):
    candidates = [socket for socket in node.inputs if socket.name == name]
    typed = [socket for socket in candidates
             if socket.bl_idname == socket_type]
    if typed:
        return typed[0]
    if candidates:
        return candidates[0]
    raise KeyError(name)


def configure_final_source_stage(modifier, source_index):
    """Restrict a cage stage to one source in the evaluated merge geometry."""
    node_group = getattr(modifier, "node_group", None)
    if node_group is None:
        return False
    try:
        nodes = node_group.nodes
        set_position = next(
            node for node in nodes
            if node.bl_idname == "GeometryNodeSetPosition" and
            node.label == "Apply Deformed Position"
        )
    except (AttributeError, ReferenceError, RuntimeError, StopIteration):
        return False

    # Reconfiguration is idempotent, which also lets a saved stage recover if
    # a user removed its filter helper nodes manually.
    for node in tuple(nodes):
        if node.get("_sdh_final_source_filter", False):
            nodes.remove(node)

    frame = nodes.new("NodeFrame")
    frame.name = "SDH Final Source Filter"
    frame.label = iface_("Final Source Filter")
    frame.use_custom_color = True
    frame.color = (0.12, 0.32, 0.48)
    frame["_sdh_final_source_filter"] = True

    named = nodes.new("GeometryNodeInputNamedAttribute")
    named.name = "SDH Final Source Index"
    named.label = iface_("Merged Source Index")
    named.data_type = "INT"
    named.parent = frame
    _input_socket(named, "Name", 0).default_value = SOURCE_INDEX_ATTRIBUTE
    named["_sdh_final_source_filter"] = True

    compare = nodes.new("FunctionNodeCompare")
    compare.name = "SDH Final Source Compare"
    compare.label = iface_("Source = {index}").format(
        index=int(source_index) + 1)
    compare.data_type = "INT"
    compare.operation = "EQUAL"
    compare.parent = frame
    _typed_input(compare, "B", "NodeSocketInt").default_value = int(source_index)
    compare["_sdh_final_source_filter"] = True

    both = nodes.new("FunctionNodeBooleanMath")
    both.name = "SDH Final Source Selection"
    both.label = iface_("Existing Source and Matching Index")
    both.operation = "AND"
    both.parent = frame
    both["_sdh_final_source_filter"] = True

    links = node_group.links
    links.new(named.outputs["Attribute"], _typed_input(compare, "A", "NodeSocketInt"))
    links.new(named.outputs["Exists"], both.inputs[0])
    links.new(compare.outputs["Result"], both.inputs[1])
    selection = set_position.inputs.get("Selection")
    if selection is None:
        return False
    links.new(both.outputs["Boolean"], selection)

    node_group[FINAL_SOURCE_STAGE_MARKER] = True
    node_group[FINAL_SOURCE_INDEX] = int(source_index)
    return True


def create_merge_node_group(sources):
    """Create a readable node tree and tag every source face for picking."""
    node_group = bpy.data.node_groups.new(
        name=f"SDH Deform Merge {str(uuid.uuid4())[:8]}",
        type="GeometryNodeTree",
    )
    node_group[MERGE_GROUP_MARKER] = True
    node_group["sdh_version"] = GROUP_VERSION
    try:
        node_group.is_modifier = True
        node_group.color_tag = "GEOMETRY"
    except (AttributeError, TypeError):
        pass
    _new_geometry_socket(node_group, "Geometry", "OUTPUT")

    nodes = node_group.nodes
    links = node_group.links
    output = nodes.new("NodeGroupOutput")
    output.name = "SDH Merge Output"
    output.label = iface_("Merged Geometry")
    output.location = (520.0, 0.0)
    join = nodes.new("GeometryNodeJoinGeometry")
    join.name = "SDH Join Sources"
    join.label = iface_("Join Sources")
    join.location = (250.0, 0.0)
    links.new(join.outputs["Geometry"], output.inputs["Geometry"])

    count = max(len(sources), 1)
    for index, source in enumerate(sources):
        y = (count - 1) * 120.0 - index * 240.0
        frame = nodes.new("NodeFrame")
        frame.name = f"SDH Source {index + 1:02d}"
        frame.label = f"{index + 1:02d}  {source.name}"
        frame.label_size = 20

        object_info = nodes.new("GeometryNodeObjectInfo")
        object_info.name = f"SDH Object Info {index + 1:02d}"
        object_info.label = source.name
        object_info.location = (-760.0, y)
        object_info.parent = frame
        try:
            object_info.transform_space = "ORIGINAL"
        except (AttributeError, TypeError, ValueError):
            pass
        _input_socket(object_info, "Object", 0).default_value = source
        as_instance = object_info.inputs.get("As Instance")
        if as_instance is not None:
            as_instance.default_value = False

        transform = nodes.new("GeometryNodeTransform")
        transform.name = f"SDH Source Transform {index + 1:02d}"
        transform.label = iface_("World Transform")
        transform.location = (-460.0, y)
        transform.parent = frame

        store = nodes.new("GeometryNodeStoreNamedAttribute")
        store.name = f"SDH Source Index {index + 1:02d}"
        store.label = iface_("Source Index")
        store.location = (-150.0, y)
        store.parent = frame
        store.data_type = "INT"
        store.domain = "FACE"
        _input_socket(store, "Selection", 1).default_value = True
        _input_socket(store, "Name", 2).default_value = SOURCE_INDEX_ATTRIBUTE
        _input_socket(store, "Value", 3).default_value = index

        links.new(object_info.outputs["Geometry"], transform.inputs["Geometry"])
        links.new(object_info.outputs["Location"], transform.inputs["Translation"])
        links.new(object_info.outputs["Rotation"], transform.inputs["Rotation"])
        links.new(object_info.outputs["Scale"], transform.inputs["Scale"])
        links.new(transform.outputs["Geometry"], store.inputs["Geometry"])
        links.new(store.outputs["Geometry"], join.inputs["Geometry"])
    return node_group


def _capture_source_state(entry, source):
    entry.object = source
    try:
        entry.original_hide = bool(source.hide_get())
    except (AttributeError, ReferenceError, RuntimeError):
        entry.original_hide = False
    entry.original_hide_viewport = bool(source.hide_viewport)
    entry.original_hide_render = bool(source.hide_render)
    entry.original_hide_select = bool(source.hide_select)
    entry.original_show_in_front = bool(source.show_in_front)
    entry.original_display_type = str(source.display_type)
    try:
        entry.original_mesh_data = source.data if source.type == "MESH" else None
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        entry.original_mesh_data = None
    entry.original_uv_active = ""
    entry.original_uv_render = ""
    entry.merge_uv_name = ""
    entry.merge_uv_owned = False


def _uv_layer_name(mesh, *, render=False):
    """Return the mesh's active/render UV name across Blender versions."""
    layers = getattr(mesh, "uv_layers", None)
    if layers is None or len(layers) == 0:
        return ""
    index_name = "active_render_index" if render else "active_index"
    if not render or hasattr(layers, index_name):
        try:
            index = int(getattr(layers, index_name))
            if 0 <= index < len(layers):
                return str(layers[index].name)
        except (AttributeError, IndexError, RuntimeError, TypeError, ValueError):
            pass
    flag = "active_render" if render else "active"
    for layer in layers:
        try:
            if bool(getattr(layer, flag)):
                return str(layer.name)
        except (AttributeError, ReferenceError, RuntimeError):
            continue
    try:
        return str(layers[0].name)
    except (IndexError, ReferenceError, RuntimeError):
        return ""


def _set_uv_layer_selection(mesh, active_name="", render_name=""):
    layers = getattr(mesh, "uv_layers", None)
    if layers is None or len(layers) == 0:
        return
    active = layers.get(active_name) if active_name else None
    render = layers.get(render_name) if render_name else None
    if active is None:
        active = layers[0]
    if render is None:
        render = active
    try:
        layers.active_index = layers.values().index(active)
    except (AttributeError, ValueError, RuntimeError, TypeError):
        try:
            layers.active_index = next(
                index for index, layer in enumerate(layers) if layer == active)
        except (AttributeError, StopIteration, RuntimeError, TypeError):
            pass
    if hasattr(layers, "active_render_index"):
        try:
            layers.active_render_index = layers.values().index(render)
        except (AttributeError, ValueError, RuntimeError, TypeError):
            try:
                layers.active_render_index = next(
                    index for index, layer in enumerate(layers) if layer == render)
            except (AttributeError, StopIteration, RuntimeError, TypeError):
                pass
    else:
        # Blender 4.2 stores the render choice on each layer instead of an
        # index property. Clear the old flags before setting the requested one.
        for layer in layers:
            try:
                layer.active_render = (layer == render)
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                pass


def _copy_uv_layer(mesh, source_name, destination_name):
    """Copy loop UV coordinates into one deterministic common layer."""
    layers = getattr(mesh, "uv_layers", None)
    if layers is None:
        return False
    source = layers.get(source_name) if source_name else None
    if source is None and len(layers):
        source = layers[0]
    destination = layers.get(destination_name)
    created = destination is None
    if destination is None:
        try:
            destination = layers.new(name=destination_name, do_init=False)
        except TypeError:
            destination = layers.new(name=destination_name)
    if source is not None:
        for source_loop, destination_loop in zip(source.data, destination.data):
            destination_loop.uv = source_loop.uv
    _set_uv_layer_selection(mesh, destination_name, destination_name)
    return created


def _prepare_source_uv(entry, source, merge_uv_name):
    """Give one source the common UV layer consumed by the joined result."""
    if source.type != "MESH":
        return
    mesh = source.data
    entry.original_uv_active = _uv_layer_name(mesh)
    entry.original_uv_render = _uv_layer_name(mesh, render=True)
    # A shared mesh datablock must not be mutated for the other users.
    try:
        if int(mesh.users) > 1:
            entry.original_mesh_data = mesh
            source.data = mesh.copy()
            mesh = source.data
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    preferred = entry.original_uv_render or entry.original_uv_active
    entry.merge_uv_name = merge_uv_name
    entry.merge_uv_owned = _copy_uv_layer(mesh, preferred, merge_uv_name)
    # If a stale layer with this generated name already existed, it is still
    # private to this merge name and must be restored/removed on release.
    if not entry.merge_uv_owned:
        entry.merge_uv_owned = True


def _restore_source_uv(entry):
    source = getattr(entry, "object", None)
    if source is None or getattr(source, "type", None) != "MESH":
        return
    current_mesh = getattr(source, "data", None)
    original_mesh = getattr(entry, "original_mesh_data", None)
    if original_mesh is not None and current_mesh is not original_mesh:
        source.data = original_mesh
        if current_mesh is not None:
            try:
                if current_mesh.users == 0:
                    bpy.data.meshes.remove(current_mesh)
            except (ReferenceError, RuntimeError, TypeError):
                pass
        current_mesh = original_mesh
    if current_mesh is None:
        return
    layer_name = str(getattr(entry, "merge_uv_name", "") or "")
    if layer_name and getattr(entry, "merge_uv_owned", False):
        layers = getattr(current_mesh, "uv_layers", None)
        try:
            layer = layers.get(layer_name) if layers is not None else None
            if layer is not None:
                layers.remove(layer)
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
    _set_uv_layer_selection(
        current_mesh,
        str(getattr(entry, "original_uv_active", "") or ""),
        str(getattr(entry, "original_uv_render", "") or ""),
    )


def ensure_merge_uv_layout(merge):
    """Migrate a merge created before common UV metadata was introduced."""
    if not is_deform_merge(merge):
        return False
    entries = tuple(live_merge_sources(merge))
    if not entries:
        return False
    needs_migration = any(
        not str(getattr(entry, "merge_uv_name", "") or "")
        for _index, entry, source in entries if source.type == "MESH"
    )
    if not needs_migration:
        return False
    identifier = str(merge.get(MERGE_UUID, ""))
    merge_uv_name = (
        f"{MERGE_UV_LAYER_PREFIX} {identifier[:8]}"
        if identifier else f"{MERGE_UV_LAYER_PREFIX} migrated")
    for _index, entry, source in entries:
        if source.type != "MESH":
            continue
        # Old entries did not save their original UV selection. At migration
        # time the source's active/render layers are the best available record.
        if not entry.original_uv_active:
            entry.original_uv_active = _uv_layer_name(source.data)
        if not entry.original_uv_render:
            entry.original_uv_render = _uv_layer_name(source.data, render=True)
        if not entry.original_mesh_data:
            entry.original_mesh_data = source.data
        _prepare_source_uv(entry, source, merge_uv_name)
    return True


def _set_source_merged(entry):
    source = entry.object
    if source is None:
        return
    source.display_type = entry.original_display_type
    source.show_in_front = entry.original_show_in_front
    source.hide_select = entry.original_hide_select
    # Collection/object viewport exclusion can prevent Object Info evaluation.
    # Per-view-layer hiding keeps the source out of the viewport without
    # disabling the live Geometry Nodes dependency.
    source.hide_viewport = False
    source.hide_render = True
    try:
        source.hide_set(True)
    except (AttributeError, ReferenceError, RuntimeError):
        pass


def _restore_source(entry):
    source = entry.object
    if source is None:
        return
    source.display_type = entry.original_display_type
    source.show_in_front = entry.original_show_in_front
    source.hide_select = entry.original_hide_select
    source.hide_viewport = entry.original_hide_viewport
    source.hide_render = entry.original_hide_render
    try:
        source.hide_set(entry.original_hide)
    except (AttributeError, ReferenceError, RuntimeError):
        pass


def _select_only(context, obj):
    try:
        for selected in tuple(context.selected_objects):
            selected.select_set(False)
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    obj.select_set(True)
    context.view_layer.objects.active = obj


def create_deform_merge(context, sources):
    """Convert sources, create the live merge object, and hide originals."""
    sources = tuple(sources)
    if len(sources) < 2:
        raise RuntimeError(iface_("Select at least two supported objects"))
    unsupported = tuple(obj for obj in sources if obj.type not in CONVERTIBLE_TYPES)
    if unsupported:
        raise RuntimeError(iface_("One or more selected objects cannot be converted"))
    owned = tuple(obj for obj in sources if merge_owner(obj) is not None)
    if owned:
        raise RuntimeError(
            iface_("{name} already belongs to a deformation merge").format(
                name=owned[0].name)
        )

    sources = _convert_sources_to_mesh(context, sources)
    merge_uuid = str(uuid.uuid4())
    # Geometry Nodes joins expose a single active/render UV layer. Normalize
    # every mesh input to a private common layer before constructing the node
    # tree so each source keeps the UV set it was actually displaying.
    merge_uv_name = f"{MERGE_UV_LAYER_PREFIX} {merge_uuid[:8]}"
    node_group = create_merge_node_group(sources)
    mesh = bpy.data.meshes.new("Deform Merge")
    merge = bpy.data.objects.new("Deform Merge", mesh)
    collection = getattr(context, "collection", None) or context.scene.collection
    collection.objects.link(merge)
    merge.matrix_world = Matrix.Identity(4)
    merge[MERGE_MARKER] = True
    merge[MERGE_UUID] = merge_uuid

    modifier = merge.modifiers.new(name="Deform Merge", type="NODES")
    modifier.node_group = node_group
    merge.modifiers.active = modifier

    try:
        for source in sources:
            entry = merge.sdh_deform_merge_sources.add()
            _capture_source_state(entry, source)
            _prepare_source_uv(entry, source, merge_uv_name)
            source.sdh_deform_merge_owner = merge
            source[SOURCE_MARKER] = True
            _set_source_merged(entry)
    except Exception:
        # UV preparation can fail on protected/read-only datablocks. Restore
        # every entry already captured before removing the half-built merge.
        for _index, entry, source in live_merge_sources(merge):
            _restore_source_uv(entry)
            _restore_source(entry)
            try:
                source.sdh_deform_merge_owner = None
                if SOURCE_MARKER in source:
                    del source[SOURCE_MARKER]
            except (AttributeError, KeyError, ReferenceError, RuntimeError):
                pass
        bpy.data.objects.remove(merge, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        if node_group.users == 0:
            bpy.data.node_groups.remove(node_group)
        raise

    _select_only(context, merge)
    context.view_layer.update()
    _register_merge(merge)
    enable_preview_handlers()
    return merge


def _entry_by_index(merge, index):
    try:
        if 0 <= index < len(merge.sdh_deform_merge_sources):
            return merge.sdh_deform_merge_sources[index]
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return None
    return None


def _active_source_index(merge):
    if not is_deform_merge(merge):
        return -1
    try:
        return int(merge.get("_sdh_deform_merge_active_source", -1))
    except (AttributeError, ReferenceError, TypeError, ValueError):
        return -1


def _final_preview_enabled():
    try:
        from ..utils import get_pref
        preferences = get_pref()
        if preferences is not None:
            return bool(preferences.show_merge_final_state_preview)
    except (AttributeError, ImportError, KeyError, ReferenceError, RuntimeError,
            TypeError):
        pass
    return True


def _remove_preview_object(preview):
    if preview is None:
        return
    _untrack_preview(preview)
    try:
        mesh = preview.data if preview.type == "MESH" else None
    except (AttributeError, ReferenceError):
        mesh = None
    try:
        bpy.data.objects.remove(preview, do_unlink=True)
    except (ReferenceError, RuntimeError):
        pass
    if mesh is not None:
        try:
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        except (ReferenceError, RuntimeError):
            pass


def cleanup_final_previews(merge=None):
    """Remove transient evaluated source previews owned by one/all merges."""
    merge_uuid = ""
    if merge is not None:
        try:
            merge_uuid = str(merge.get(MERGE_UUID, ""))
        except (AttributeError, ReferenceError, TypeError):
            return 0

    previews = set()
    merges = (merge,) if merge is not None else _registered_merges()
    for owner in merges:
        for _index, entry, _source in live_merge_sources(owner):
            try:
                preview = entry.final_preview
            except (AttributeError, ReferenceError, RuntimeError):
                preview = None
            if preview is not None:
                previews.add(preview)
            try:
                entry.final_preview = None
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                pass

    # A merge with no UUID is an old/corrupt file; only its explicit pointer
    # entries are safe to remove. Never let it sweep another merge's preview.
    scan_marked = merge is None or bool(merge_uuid)
    for obj in tuple(_preview_registry.values()):
        try:
            if not obj.get(SOURCE_PREVIEW_MARKER, False):
                continue
            if not scan_marked:
                continue
            if merge_uuid and str(obj.get(MERGE_UUID, "")) != merge_uuid:
                continue
            previews.add(obj)
        except (AttributeError, ReferenceError, TypeError):
            continue
    for preview in previews:
        _remove_preview_object(preview)
    if previews:
        try:
            from ..utils import remove_unused_control_collections
            remove_unused_control_collections()
        except (AttributeError, ImportError, ReferenceError, RuntimeError,
                TypeError):
            pass
    return len(previews)


def cleanup_orphan_final_previews():
    """Remove previews whose merge or source entry no longer exists."""
    merges = _registered_merges()
    valid = set()
    for merge in merges:
        for _index, entry, _source in live_merge_sources(merge):
            try:
                preview = entry.final_preview
            except (AttributeError, ReferenceError, RuntimeError):
                preview = None
            if preview is not None:
                valid.add(preview)
    removed = 0
    for obj in tuple(_preview_registry.values()):
        try:
            if obj.get(SOURCE_PREVIEW_MARKER, False) and obj not in valid:
                _remove_preview_object(obj)
                removed += 1
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            continue
    return removed


def _evaluated_source_geometry(evaluated_merge, source_index):
    """Extract one tagged source from the merge's fully evaluated mesh."""
    # Accept either an evaluated Object or a temporary mesh returned by
    # Object.to_mesh(), which keeps custom face attributes available across
    # Blender 4.2 through 5.x.
    mesh = getattr(evaluated_merge, "data", evaluated_merge)
    attributes = getattr(mesh, "attributes", None)
    if mesh is None or attributes is None:
        return None
    attribute = attributes.get(SOURCE_INDEX_ATTRIBUTE)
    if attribute is None or attribute.domain != "FACE":
        return None

    polygons = []
    used_vertices = set()
    try:
        for polygon in mesh.polygons:
            if int(attribute.data[polygon.index].value) != int(source_index):
                continue
            vertices = tuple(int(vertex) for vertex in polygon.vertices)
            if len(vertices) < 3:
                continue
            polygons.append(vertices)
            used_vertices.update(vertices)
    except (AttributeError, IndexError, ReferenceError, TypeError, ValueError):
        return None
    if not polygons:
        return None

    ordered_vertices = tuple(sorted(used_vertices))
    remap = {old: new for new, old in enumerate(ordered_vertices)}
    try:
        vertices = tuple(mesh.vertices[index].co.copy()
                         for index in ordered_vertices)
    except (AttributeError, IndexError, ReferenceError, TypeError):
        return None
    faces = tuple(tuple(remap[index] for index in polygon)
                  for polygon in polygons)
    return vertices, faces


def evaluated_source_bounds(
        context, merge, source_index, depsgraph=None, modifier=None):
    """Return local-space bounds for one source at a merge stack position."""
    if not is_deform_merge(merge):
        return None
    target = merge
    clone = None
    evaluated = None
    evaluated_mesh = None
    try:
        if modifier is not None:
            stack_index = tuple(merge.modifiers).index(modifier)
            clone = merge.copy()
            clone.name = f"{merge.name}_SDH_SOURCE_BOUNDS"
            clone["_sdh_merge_source_bounds_evaluator"] = True
            collection = merge.users_collection[0] if merge.users_collection else None
            if collection is None:
                collection = getattr(context, "collection", None)
            if collection is None:
                collection = context.scene.collection
            collection.objects.link(clone)
            original_modifiers = tuple(merge.modifiers)
            for index, clone_modifier in enumerate(tuple(clone.modifiers)):
                clone_modifier.show_viewport = (
                    index < stack_index and
                    original_modifiers[index].show_viewport)
            hide_runtime_object(clone, getattr(context, "scene", None))
            target = clone
        depsgraph = depsgraph or context.evaluated_depsgraph_get()
        evaluated = target.evaluated_get(depsgraph)
        evaluated_mesh = evaluated.to_mesh(
            preserve_all_data_layers=True, depsgraph=depsgraph)
        geometry = _evaluated_source_geometry(evaluated_mesh, source_index)
        if geometry is None:
            return None
        vertices, _faces = geometry
        if not vertices:
            return None
        minimum = Vector(vertices[0])
        maximum = Vector(vertices[0])
        for vertex in vertices[1:]:
            point = Vector(vertex)
            minimum.x = min(minimum.x, point.x)
            minimum.y = min(minimum.y, point.y)
            minimum.z = min(minimum.z, point.z)
            maximum.x = max(maximum.x, point.x)
            maximum.y = max(maximum.y, point.y)
            maximum.z = max(maximum.z, point.z)
        return minimum, maximum
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None
    finally:
        if evaluated is not None:
            try:
                evaluated.to_mesh_clear()
            except (AttributeError, RuntimeError):
                pass
        if clone is not None:
            try:
                bpy.data.objects.remove(clone, do_unlink=True)
            except (ReferenceError, RuntimeError):
                pass


def refresh_final_preview(context, merge, source_index=None, depsgraph=None):
    """Show one source after the merge object's complete modifier stack."""
    global _preview_refresh_running
    if not is_deform_merge(merge):
        return False
    if source_index is None:
        source_index = _active_source_index(merge)
    entry = _entry_by_index(merge, source_index)
    source = getattr(entry, "object", None) if entry is not None else None
    if source is None or not _final_preview_enabled():
        cleanup_final_previews(merge)
        return False

    _preview_refresh_running = True
    try:
        depsgraph = depsgraph or context.evaluated_depsgraph_get()
        evaluated = merge.evaluated_get(depsgraph)
        evaluated_mesh = None
        try:
            evaluated_mesh = evaluated.to_mesh(
                preserve_all_data_layers=True, depsgraph=depsgraph)
        except (AttributeError, TypeError):
            evaluated_mesh = getattr(evaluated, "data", None)
        try:
            geometry = _evaluated_source_geometry(evaluated_mesh, source_index)
        finally:
            try:
                evaluated.to_mesh_clear()
            except (AttributeError, RuntimeError):
                pass
        if geometry is None:
            cleanup_final_previews(merge)
            return False
        vertices, faces = geometry

        preview = getattr(entry, "final_preview", None)
        if preview is None or preview.name not in bpy.data.objects:
            preview_mesh = bpy.data.meshes.new(
                f".SDH {source.name} Final Preview")
            preview = bpy.data.objects.new(
                f".SDH {source.name} Final Preview", preview_mesh)
            preview[SOURCE_PREVIEW_MARKER] = True
            preview[MERGE_UUID] = str(merge.get(MERGE_UUID, ""))
            preview.hide_render = True
            preview.hide_select = True
            preview.show_in_front = True
            preview.display_type = "WIRE"
            preview.color = (0.08, 0.65, 1.0, 1.0)
            collection = merge.users_collection[0] if merge.users_collection else None
            if collection is None:
                collection = getattr(context, "collection", None)
            if collection is None:
                collection = context.scene.collection
            collection.objects.link(preview)
            entry.final_preview = preview

        _track_preview(preview)

        old_mesh = preview.data
        preview_mesh = bpy.data.meshes.new(
            f".SDH {source.name} Final Preview Mesh")
        preview_mesh[SOURCE_PREVIEW_GROUP_MARKER] = True
        preview_mesh[MERGE_UUID] = str(merge.get(MERGE_UUID, ""))
        preview_mesh.from_pydata(vertices, (), faces)
        preview_mesh.update()
        preview.data = preview_mesh
        preview.matrix_world = evaluated.matrix_world.copy()
        try:
            preview.hide_set(False, view_layer=context.view_layer)
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
        if old_mesh is not None and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        cleanup_final_previews(merge)
        return False
    finally:
        _preview_refresh_running = False


def _queue_preview_refresh(merge):
    if (not is_deform_merge(merge) or _active_source_index(merge) < 0 or
            not _final_preview_enabled()):
        return
    try:
        identifier = str(merge.get(MERGE_UUID, ""))
    except (AttributeError, ReferenceError, TypeError):
        return
    if not identifier:
        return
    _preview_pending.add(identifier)
    try:
        if not bpy.app.timers.is_registered(_preview_refresh_timer):
            # Let the cage controller sync timer publish changed node inputs
            # before taking the evaluated mesh snapshot.
            bpy.app.timers.register(_preview_refresh_timer, first_interval=0.01)
    except (AttributeError, RuntimeError, ValueError):
        pass


def _preview_refresh_timer():
    global _preview_last_refresh
    if not _preview_pending:
        return None
    elapsed = time.monotonic() - _preview_last_refresh
    if elapsed < PREVIEW_REFRESH_INTERVAL:
        return max(PREVIEW_REFRESH_INTERVAL - elapsed, 0.001)
    pending = tuple(_preview_pending)
    _preview_pending.clear()
    context = bpy.context
    for identifier in pending:
        merge = _merge_by_uuid(identifier)
        if merge is None or _active_source_index(merge) < 0:
            continue
        refresh_final_preview(context, merge)
    _preview_last_refresh = time.monotonic()
    return PREVIEW_REFRESH_INTERVAL if _preview_pending else None


def sync_final_preview_preference(context, enabled):
    """Apply the preference immediately to every active source edit."""
    if not enabled:
        _preview_pending.clear()
        cleanup_final_previews()
        return
    for merge in _registered_merges():
        if _active_source_index(merge) >= 0:
            refresh_final_preview(context or bpy.context, merge)


def _rna_pointer(value):
    try:
        return int(value.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return 0


def _preview_dependency_pointers(merge):
    """Return original datablock pointers that can change the preview."""
    pointers = set()

    def add(value):
        pointer = _rna_pointer(value)
        if pointer:
            pointers.add(pointer)

    add(merge)
    add(getattr(merge, "data", None))
    try:
        modifiers = tuple(merge.modifiers)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        modifiers = ()
    for modifier in modifiers:
        add(getattr(modifier, "node_group", None))
    for _index, _entry, source in live_merge_sources(merge):
        add(source)
        add(getattr(source, "data", None))
        try:
            source_modifiers = tuple(source.modifiers)
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            source_modifiers = ()
        for modifier in source_modifiers:
            add(getattr(modifier, "node_group", None))
    # Controller objects are identified by marker instead of importing core;
    # this keeps the handler safe while Blender is registering the extension.
    try:
        children = tuple(merge.children)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        children = ()
    for child in children:
        try:
            if (child.parent == merge and
                    child.get("_sdh_cage_deform_controller", False)):
                add(child)
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            continue
    return pointers


@persistent
def _preview_depsgraph_sync(_scene, depsgraph):
    if (depsgraph is None or _preview_refresh_running or
            not _final_preview_enabled()):
        return
    active_merges = _registered_merges(active_only=True)
    if not active_merges:
        schedule_preview_runtime_maintenance()
        return
    try:
        updates = tuple(depsgraph.updates)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return
    dependencies = {
        _rna_pointer(merge): _preview_dependency_pointers(merge)
        for merge in active_merges
    }
    for update in updates:
        try:
            if not (update.is_updated_geometry or update.is_updated_transform):
                continue
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            continue
        try:
            updated = getattr(update.id, "original", update.id)
            if updated.get(SOURCE_PREVIEW_MARKER, False):
                continue
            if updated.get(SOURCE_PREVIEW_GROUP_MARKER, False):
                continue
        except (AttributeError, ReferenceError, TypeError):
            pass
        pointer = _rna_pointer(updated)
        if not pointer:
            continue
        for merge in active_merges:
            if pointer in dependencies.get(_rna_pointer(merge), ()):
                _queue_preview_refresh(merge)


@persistent
def _preview_frame_change_post(_scene, *_args):
    if not _final_preview_enabled():
        return
    for merge in _registered_merges(active_only=True):
        _queue_preview_refresh(merge)


def _preview_undo_redo_post(_scene=None):
    """Reconcile transient objects after Blender swaps the undo data tree."""
    _preview_pending.clear()
    _rebuild_preview_registry()
    cleanup_final_previews()
    for merge in _registered_merges():
        if _active_source_index(merge) >= 0:
            _queue_preview_refresh(merge)
    schedule_preview_runtime_maintenance()


@persistent
def _preview_load_post(_unused):
    """A saved modal edit cannot resume, so restore a neutral merge state."""
    _preview_pending.clear()
    _rebuild_preview_registry()
    cleanup_final_previews()
    for merge in _registered_merges():
        merge["_sdh_deform_merge_active_source"] = -1
        try:
            ensure_merge_uv_layout(merge)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        for _index, entry, _source in live_merge_sources(merge):
            _set_source_merged(entry)
    schedule_preview_runtime_maintenance()


def enter_source_edit(context, merge, source_index):
    entry = _entry_by_index(merge, source_index)
    source = getattr(entry, "object", None) if entry is not None else None
    if source is None:
        return False
    ensure_merge_uv_layout(merge)
    cleanup_final_previews(merge)
    for _index, candidate_entry, _source in live_merge_sources(merge):
        _set_source_merged(candidate_entry)
    source.hide_viewport = False
    source.hide_select = False
    source.hide_render = True
    source.display_type = "WIRE"
    source.show_in_front = True
    try:
        source.hide_set(False)
    except (AttributeError, ReferenceError, RuntimeError):
        return False
    _select_only(context, source)
    merge["_sdh_deform_merge_active_source"] = int(source_index)
    try:
        merge.sdh_deform_merge_active_source_index = int(source_index)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    context.view_layer.update()
    refresh_final_preview(context, merge, source_index)
    return True


def return_to_merge(context, merge):
    if not is_deform_merge(merge):
        return False
    merge["_sdh_deform_merge_active_source"] = -1
    cleanup_final_previews(merge)
    for _index, entry, _source in live_merge_sources(merge):
        _set_source_merged(entry)
    try:
        merge.sdh_deform_merge_active_source_index = 0
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    _select_only(context, merge)
    context.view_layer.update()
    _status_text(context, None)
    return True


def _source_index_from_hit(evaluated_merge, face_index):
    mesh = getattr(evaluated_merge, "data", None)
    attributes = getattr(mesh, "attributes", None)
    if attributes is None or face_index < 0:
        return None
    attribute = attributes.get(SOURCE_INDEX_ATTRIBUTE)
    if attribute is None or attribute.domain != "FACE":
        return None
    try:
        return int(attribute.data[face_index].value)
    except (AttributeError, IndexError, TypeError, ValueError):
        return None


def _ray_region_for_event(context, event=None):
    """Resolve a 3D-window region even when the modal started in the sidebar."""
    region = getattr(context, "region", None)
    region_data = getattr(context, "region_data", None)
    if (region is not None and region_data is not None and
            getattr(region, "type", None) == "WINDOW"):
        return region, region_data, None
    screen = getattr(context, "screen", None)
    if screen is None:
        return None, None, None
    mouse_x = getattr(event, "mouse_x", None) if event is not None else None
    mouse_y = getattr(event, "mouse_y", None) if event is not None else None
    for area in tuple(getattr(screen, "areas", ())):
        if getattr(area, "type", None) != "VIEW_3D":
            continue
        spaces = getattr(area, "spaces", None)
        active_space = getattr(spaces, "active", None)
        candidate_region_data = getattr(active_space, "region_3d", None)
        if candidate_region_data is None:
            continue
        for candidate in tuple(getattr(area, "regions", ())):
            if getattr(candidate, "type", None) != "WINDOW":
                continue
            if (mouse_x is not None and mouse_y is not None and
                    not (candidate.x <= mouse_x < candidate.x + candidate.width and
                         candidate.y <= mouse_y < candidate.y + candidate.height)):
                continue
            event_xy = None
            if mouse_x is not None and mouse_y is not None:
                event_xy = (mouse_x - candidate.x, mouse_y - candidate.y)
            return candidate, candidate_region_data, event_xy
    return None, None, None


def ray_pick_merge_source(context, region_xy=None, event=None):
    """Return the nearest visible merge and its tagged source index."""
    region, region_data, event_xy = _ray_region_for_event(context, event)
    if region is None or region_data is None:
        return None, None
    if event_xy is not None:
        region_xy = event_xy
    if region_xy is None:
        return None, None
    origin_world = view3d_utils.region_2d_to_origin_3d(
        region, region_data, region_xy)
    direction_world = view3d_utils.region_2d_to_vector_3d(
        region, region_data, region_xy).normalized()
    depsgraph = context.evaluated_depsgraph_get()
    nearest = None
    try:
        candidates = tuple(context.view_layer.objects)
    except (AttributeError, ReferenceError, RuntimeError):
        candidates = ()
    for merge in candidates:
        if not is_deform_merge(merge):
            continue
        try:
            if merge.hide_get() or not merge.visible_get(view_layer=context.view_layer):
                continue
            evaluated = merge.evaluated_get(depsgraph)
            matrix = evaluated.matrix_world.copy()
            inverse = matrix.inverted_safe()
            local_origin = inverse @ origin_world
            local_direction = (inverse.to_3x3() @ direction_world).normalized()
            hit, location, _normal, face_index = evaluated.ray_cast(
                local_origin, local_direction)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
        if not hit:
            continue
        source_index = _source_index_from_hit(evaluated, face_index)
        entry = _entry_by_index(merge, source_index) if source_index is not None else None
        if entry is None or getattr(entry, "object", None) is None:
            continue
        distance = (matrix @ location - origin_world).length
        if nearest is None or distance < nearest[0]:
            nearest = (distance, merge, source_index)
    if nearest is None:
        return None, None
    return nearest[1], nearest[2]


def _merge_by_uuid(identifier):
    """Resolve a merge without keeping a fragile RNA pointer on an operator."""
    if not identifier:
        return None
    candidate = _merge_registry.get(str(identifier))
    try:
        if (candidate is not None and is_deform_merge(candidate) and
                str(candidate.get(MERGE_UUID, "")) == str(identifier)):
            return candidate
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    _merge_registry.pop(str(identifier), None)
    # Older files can call an operator before the post-load maintenance timer;
    # recover once, then keep subsequent lookups on the registry fast path.
    try:
        objects = tuple(bpy.data.objects)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return None
    for candidate in objects:
        if is_deform_merge(candidate) and str(candidate.get(MERGE_UUID, "")) == identifier:
            _register_merge(candidate)
            return candidate
    return None


def _status_text(context, text=None):
    """Set/clear Blender's workspace status text without breaking older APIs."""
    workspace = getattr(context, "workspace", None)
    setter = getattr(workspace, "status_text_set", None)
    if not callable(setter):
        return
    try:
        setter(text)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass


def release_deform_merge(context, merge):
    """Restore sources and remove the generated merge container."""
    if not is_deform_merge(merge):
        return False
    cleanup_final_previews(merge)
    restored_sources = []
    for _index, entry, source in live_merge_sources(merge):
        _restore_source_uv(entry)
        _restore_source(entry)
        try:
            source.sdh_deform_merge_owner = None
            del source[SOURCE_MARKER]
        except (AttributeError, KeyError, ReferenceError, RuntimeError):
            pass
        restored_sources.append(source)

    # Remove cage controllers owned by the merge before deleting their parent.
    remove_control_collections = None
    try:
        from .core import CONTROLLER_MARKER
        from ..utils import PublicData, remove_unused_control_collections
        remove_control_collections = remove_unused_control_collections
        controllers = tuple(
            obj for obj in tuple(getattr(merge, "children", ()))
            if obj.parent == merge and (
                obj.get(CONTROLLER_MARKER, False) or
                obj.get(PublicData.G_OWNER_PROP, False)
            )
        )
    except (AttributeError, ImportError, ReferenceError, RuntimeError):
        controllers = ()
    for controller in controllers:
        bpy.data.objects.remove(controller, do_unlink=True)
    if remove_control_collections is not None:
        try:
            remove_control_collections()
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass

    node_groups = tuple(
        modifier.node_group for modifier in merge.modifiers
        if modifier.type == "NODES" and modifier.node_group is not None
    )
    mesh = merge.data
    _unregister_merge(merge)
    bpy.data.objects.remove(merge, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)
    for node_group in node_groups:
        if node_group.users == 0 and (
                node_group.get(MERGE_GROUP_MARKER, False) or
                node_group.get("_sdh_cage_deform_group", False)):
            bpy.data.node_groups.remove(node_group)
    visible_sources = tuple(
        source for source in restored_sources
        if not source.hide_viewport and not source.hide_get()
    )
    if visible_sources:
        for source in visible_sources:
            source.select_set(True)
        context.view_layer.objects.active = visible_sources[0]
    context.view_layer.update()
    schedule_preview_runtime_maintenance()
    return True


class SDH_OT_create_deform_merge(Operator):
    bl_idname = "sdh.create_deform_merge"
    bl_label = "Merge Selected for Deform"
    bl_description = (
        "Create one live mesh from selected objects; non-mesh sources are "
        "converted to meshes"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (
            getattr(context, "mode", "OBJECT") == "OBJECT" and
            len(eligible_selected_sources(context)) >= 2
        )

    def execute(self, context):
        sources = eligible_selected_sources(context)
        try:
            merge = create_deform_merge(context, sources)
        except RuntimeError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            iface_("Merged {count} objects for deformation").format(
                count=len(live_merge_sources(merge)))
        )
        return {"FINISHED"}


class SDH_OT_create_collection_deform_merge(Operator):
    bl_idname = "sdh.create_collection_deform_merge"
    bl_label = "Merge Collection for Deform"
    bl_description = (
        "Create one live deformation mesh from every supported object in the "
        "selected collection and its child collections"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if getattr(context, "mode", "OBJECT") != "OBJECT":
            return False
        collection = getattr(
            getattr(context, "scene", None),
            "sdh_deform_merge_collection", None)
        sources, _skipped = collection_merge_sources(collection)
        return len(sources) >= 2

    def execute(self, context):
        collection = getattr(
            getattr(context, "scene", None),
            "sdh_deform_merge_collection", None)
        sources, skipped = collection_merge_sources(collection)
        if len(sources) < 2:
            self.report({"ERROR"}, iface_(
                "Collection needs at least two supported objects"))
            return {"CANCELLED"}
        try:
            merge = create_deform_merge(context, sources)
        except RuntimeError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        count = len(live_merge_sources(merge))
        if skipped:
            message = iface_(
                "Merged {count} collection objects; skipped {skipped}").format(
                    count=count, skipped=skipped)
        else:
            message = iface_(
                "Merged {count} collection objects").format(count=count)
        self.report({"INFO"}, message)
        return {"FINISHED"}


class _MergeSourceModalMixin:
    """Shared modal session for viewport and UIList source entry points."""

    def _start_source_modal(self, context, merge, source_index):
        entry = _entry_by_index(merge, source_index)
        source = getattr(entry, "object", None) if entry is not None else None
        if source is None or not enter_source_edit(context, merge, source_index):
            return {"PASS_THROUGH"}
        self.merge_uuid = str(merge.get(MERGE_UUID, ""))
        self._last_click_time = 0.0
        self._last_click_xy = None
        try:
            context.window_manager.modal_handler_add(self)
        except (AttributeError, RuntimeError, TypeError):
            return {"FINISHED"}
        _status_text(context, iface_(MERGE_EDIT_HINT))
        self.report(
            {"INFO"},
            iface_("Editing merged source: {name}").format(name=source.name),
        )
        return {"RUNNING_MODAL"}

    def _clear_source_modal(self, context):
        _status_text(context, None)
        try:
            context.area.tag_redraw()
        except (AttributeError, ReferenceError, RuntimeError):
            pass

    def _double_click(self, event):
        """Support Blender's DOUBLE_CLICK value and modal PRESS pairs."""
        if event.value == "DOUBLE_CLICK":
            return True
        if event.value != "PRESS":
            return False
        now = time.monotonic()
        point = (float(getattr(event, "mouse_region_x", 0.0)),
                 float(getattr(event, "mouse_region_y", 0.0)))
        previous = getattr(self, "_last_click_xy", None)
        previous_time = float(getattr(self, "_last_click_time", 0.0))
        self._last_click_time = now
        self._last_click_xy = point
        if previous is None or now - previous_time > 0.35:
            return False
        return ((point[0] - previous[0]) ** 2 +
                (point[1] - previous[1]) ** 2) <= 16.0 ** 2

    def _modal_source_session(self, context, event):
        merge = _merge_by_uuid(getattr(self, "merge_uuid", ""))
        if merge is None:
            self._clear_source_modal(context)
            return {"CANCELLED"}
        # A panel action (return/add cage) may end the edit while this modal
        # operator is still in Blender's event queue. Release cleanly on the
        # next event instead of trapping the rest of the viewport.
        if _active_source_index(merge) < 0:
            self._clear_source_modal(context)
            return {"FINISHED"}

        if event.type in {"ESC", "RIGHTMOUSE", "CANCEL"} and event.value in {
                "PRESS", "CLICK", "RELEASE"}:
            return_to_merge(context, merge)
            self._clear_source_modal(context)
            return {"FINISHED"}

        if event.type != "LEFTMOUSE" or event.value not in {"PRESS", "DOUBLE_CLICK"}:
            # Keep N-panel buttons, selection and navigation available while
            # the session is active. The modal remains registered.
            return {"PASS_THROUGH"}

        is_double = self._double_click(event)
        hit_merge, source_index = ray_pick_merge_source(
            context, (event.mouse_region_x, event.mouse_region_y), event=event)
        if hit_merge is merge and source_index is not None:
            # A single click switches the visible/editable source immediately.
            # This is deliberately consumed so Blender does not select the
            # hidden source or start a second modal handler.
            if enter_source_edit(context, merge, source_index):
                source = _entry_by_index(merge, source_index).object
                self.report(
                    {"INFO"},
                    iface_("Editing merged source: {name}").format(
                        name=source.name),
                )
            return {"RUNNING_MODAL"}

        if hit_merge is None and is_double:
            return_to_merge(context, merge)
            self._clear_source_modal(context)
            return {"FINISHED"}
        return {"PASS_THROUGH"}


class SDH_OT_pick_merge_source(_MergeSourceModalMixin, Operator):
    bl_idname = "sdh.pick_merge_source"
    bl_label = "Edit Merged Source"
    bl_description = (
        "Click a merged part to switch source; "
        "double-click blank to return"
    )
    bl_options = {"INTERNAL", "UNDO"}

    # The UUID survives source renames and keeps the modal session scoped to
    # the merge that launched it.  The active source itself is resolved from
    # the tagged evaluated geometry on every double-click.
    merge_uuid: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return (
            getattr(context, "area", None) is not None and
            context.area.type == "VIEW_3D" and
            getattr(context, "mode", "OBJECT") == "OBJECT"
        )

    def invoke(self, context, event):
        merge, source_index = ray_pick_merge_source(
            context, (event.mouse_region_x, event.mouse_region_y), event=event)
        if merge is None:
            return {"PASS_THROUGH"}
        return self._start_source_modal(context, merge, source_index)

    def modal(self, context, event):
        return self._modal_source_session(context, event)


class SDH_OT_select_merge_source(_MergeSourceModalMixin, Operator):
    bl_idname = "sdh.select_merge_source"
    bl_label = "Edit Merged Source"
    bl_description = "Select this source while keeping the merged result visible"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    index: IntProperty(default=-1, options={"HIDDEN", "SKIP_SAVE"})
    merge_uuid: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return merge_from_context(context) is not None

    def execute(self, context):
        merge = merge_from_context(context)
        if merge is None or not enter_source_edit(context, merge, self.index):
            return {"CANCELLED"}
        return {"FINISHED"}

    def invoke(self, context, _event):
        merge = merge_from_context(context)
        if merge is None:
            return {"CANCELLED"}
        return self._start_source_modal(context, merge, self.index)

    def modal(self, context, event):
        return self._modal_source_session(context, event)


class SDH_OT_return_to_deform_merge(Operator):
    bl_idname = "sdh.return_to_deform_merge"
    bl_label = "Return to Merged Object"
    bl_description = "Hide the editable source and select its deformation merge"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return merge_owner(_selected_object(context)) is not None

    def execute(self, context):
        merge = merge_owner(_selected_object(context))
        return {"FINISHED"} if return_to_merge(context, merge) else {"CANCELLED"}


class SDH_OT_add_cage_to_merge_result(Operator):
    bl_idname = "sdh.add_cage_to_merge_result"
    bl_label = "Add Cage to Final Source"
    bl_description = (
        "Add a cage that affects only the selected source after the merged "
        "object's current modifier stack"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        merge = merge_from_context(context)
        return merge is not None and _active_source_index(merge) >= 0

    def execute(self, context):
        merge = merge_from_context(context)
        source_index = _active_source_index(merge)
        entry = _entry_by_index(merge, source_index)
        source = getattr(entry, "object", None) if entry is not None else None
        bounds = evaluated_source_bounds(context, merge, source_index)
        if source is None or bounds is None:
            self.report({"ERROR"}, iface_(
                "The selected source has no evaluated surface geometry"))
            return {"CANCELLED"}
        source_name = source.name
        if not return_to_merge(context, merge):
            return {"CANCELLED"}
        modifier = None
        controller = None
        try:
            from .core import (
                _activate,
                create_deform_stage,
                fit_controller_to_bounds,
                refresh_controller_display,
            )
            # Place the source-scoped stage after every existing modifier even
            # when the general "append new cages" preference is disabled.
            insertion_anchor = (
                tuple(merge.modifiers)[-1] if tuple(merge.modifiers) else None)
            modifier, controller, _previous = create_deform_stage(
                context, merge,
                name=iface_("{name} Final Cage").format(name=source_name),
                after_modifier=insertion_anchor)
            if not configure_final_source_stage(modifier, source_index):
                raise RuntimeError(iface_(
                    "Could not configure the source cage filter"))
            fit_controller_to_bounds(
                context, merge, modifier, controller, bounds)
            merge.modifiers.active = modifier
            _activate(context, controller)
            refresh_controller_display(context)
        except (AttributeError, ImportError, KeyError, ReferenceError,
                RuntimeError, TypeError) as error:
            node_group = getattr(modifier, "node_group", None)
            if controller is not None:
                try:
                    bpy.data.objects.remove(controller, do_unlink=True)
                except (ReferenceError, RuntimeError):
                    pass
            if modifier is not None:
                try:
                    merge.modifiers.remove(modifier)
                except (ReferenceError, RuntimeError):
                    pass
            if node_group is not None and node_group.users == 0:
                try:
                    bpy.data.node_groups.remove(node_group)
                except (ReferenceError, RuntimeError):
                    pass
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            iface_("Added cage to the final state of {name}").format(
                name=source_name),
        )
        return {"FINISHED"}


class SDH_OT_release_deform_merge(Operator):
    bl_idname = "sdh.release_deform_merge"
    bl_label = "Unmerge and Restore Sources"
    bl_description = "Restore source visibility and remove the generated merged object"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return merge_from_context(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        merge = merge_from_context(context)
        if merge is None:
            return {"CANCELLED"}
        name = merge.name
        if not release_deform_merge(context, merge):
            return {"CANCELLED"}
        self.report(
            {"INFO"}, iface_("Restored sources from {name}").format(name=name))
        return {"FINISHED"}


classes = (
    SDHMergeSource,
    SDH_UL_merge_sources,
    SDH_OT_create_deform_merge,
    SDH_OT_create_collection_deform_merge,
    SDH_OT_pick_merge_source,
    SDH_OT_select_merge_source,
    SDH_OT_return_to_deform_merge,
    SDH_OT_add_cage_to_merge_result,
    SDH_OT_release_deform_merge,
)


def _active_preview_handler_specs():
    return (
        (bpy.app.handlers.frame_change_post, _preview_frame_change_post),
        (bpy.app.handlers.depsgraph_update_post, _preview_depsgraph_sync),
        (bpy.app.handlers.undo_post, _preview_undo_redo_post),
        (bpy.app.handlers.redo_post, _preview_undo_redo_post),
    )


def enable_preview_handlers():
    """Enable high-frequency preview callbacks only while merges exist."""
    global _preview_handlers_registered
    if _preview_handlers_registered:
        return
    for handler_list, callback in _active_preview_handler_specs():
        while callback in handler_list:
            handler_list.remove(callback)
        handler_list.append(callback)
    _preview_handlers_registered = True


def disable_preview_handlers():
    """Remove preview callbacks that are unnecessary without merge objects."""
    global _preview_handlers_registered
    _preview_pending.clear()
    try:
        if bpy.app.timers.is_registered(_preview_refresh_timer):
            bpy.app.timers.unregister(_preview_refresh_timer)
    except (AttributeError, RuntimeError, ValueError):
        pass
    for handler_list, callback in _active_preview_handler_specs():
        while callback in handler_list:
            try:
                handler_list.remove(callback)
            except (RuntimeError, ValueError):
                break
    _preview_handlers_registered = False


def _preview_runtime_maintenance_timer():
    """Synchronize lazy preview handlers after registration or object removal."""
    if not hasattr(bpy.types.Object, "sdh_deform_merge_sources"):
        return None
    if _rebuild_preview_registry():
        enable_preview_handlers()
    else:
        disable_preview_handlers()
    return None


def schedule_preview_runtime_maintenance():
    try:
        if not bpy.app.timers.is_registered(_preview_runtime_maintenance_timer):
            bpy.app.timers.register(
                _preview_runtime_maintenance_timer, first_interval=0.0)
    except (AttributeError, RuntimeError, ValueError):
        pass


def preview_handlers_registered():
    """Expose lazy handler state for lifecycle regression tests."""
    return bool(_preview_handlers_registered)


def register_runtime():
    if not hasattr(bpy.types.Scene, "sdh_deform_merge_collection"):
        bpy.types.Scene.sdh_deform_merge_collection = PointerProperty(
            name="Deform Merge Collection",
            description=(
                "Collection whose supported objects and child collections "
                "will be merged for deformation"),
            type=bpy.types.Collection,
        )
    if not hasattr(bpy.types.Object, "sdh_deform_merge_sources"):
        bpy.types.Object.sdh_deform_merge_sources = CollectionProperty(
            type=SDHMergeSource)
    if not hasattr(bpy.types.Object, "sdh_deform_merge_owner"):
        bpy.types.Object.sdh_deform_merge_owner = PointerProperty(
            type=bpy.types.Object)
    if not hasattr(bpy.types.Object, "sdh_deform_merge_active_source_index"):
        bpy.types.Object.sdh_deform_merge_active_source_index = IntProperty(
            name="Active Merged Source",
            description="Active source row in the multi-object deformation list",
            default=0,
            min=0,
        )
    while _preview_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_preview_load_post)
    bpy.app.handlers.load_post.append(_preview_load_post)
    schedule_preview_runtime_maintenance()
    window_manager = getattr(bpy.context, "window_manager", None)
    keyconfigs = getattr(window_manager, "keyconfigs", None)
    addon_keyconfig = getattr(keyconfigs, "addon", None)
    if addon_keyconfig is None or _addon_keymaps:
        return
    keymap = addon_keyconfig.keymaps.new(name="3D View", space_type="VIEW_3D")
    keymap_item = keymap.keymap_items.new(
        SDH_OT_pick_merge_source.bl_idname,
        type="LEFTMOUSE",
        value="DOUBLE_CLICK",
    )
    _addon_keymaps.append((keymap, keymap_item))


def unregister_runtime():
    disable_preview_handlers()
    try:
        if bpy.app.timers.is_registered(_preview_runtime_maintenance_timer):
            bpy.app.timers.unregister(_preview_runtime_maintenance_timer)
    except (AttributeError, RuntimeError, ValueError):
        pass
    while _preview_load_post in bpy.app.handlers.load_post:
        try:
            bpy.app.handlers.load_post.remove(_preview_load_post)
        except (RuntimeError, ValueError):
            break
    try:
        cleanup_final_previews()
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    _merge_registry.clear()
    _preview_registry.clear()
    for keymap, keymap_item in reversed(_addon_keymaps):
        try:
            keymap.keymap_items.remove(keymap_item)
        except (ReferenceError, RuntimeError, ValueError):
            pass
    _addon_keymaps.clear()
    if hasattr(bpy.types.Scene, "sdh_deform_merge_collection"):
        try:
            del bpy.types.Scene.sdh_deform_merge_collection
        except (AttributeError, RuntimeError):
            pass
    for property_name in (
            "sdh_deform_merge_active_source_index",
            "sdh_deform_merge_owner", "sdh_deform_merge_sources"):
        if hasattr(bpy.types.Object, property_name):
            try:
                delattr(bpy.types.Object, property_name)
            except (AttributeError, RuntimeError):
                pass
