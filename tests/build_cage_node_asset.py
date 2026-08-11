"""Rebuild the packaged Geometry Nodes template used by first cage creation."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
ASSET = SOURCE / "cage_deform" / "assets" / "cage_deform_core.blend"
sys.path.insert(0, str(SOURCE.parent))

core = importlib.import_module(f"{PACKAGE}.cage_deform.core")

for obj in tuple(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
for collection_name in (
        "meshes", "curves", "lattices", "cameras", "lights", "materials",
        "images", "brushes"):
    collection = getattr(bpy.data, collection_name, None)
    if collection is None:
        continue
    for datablock in tuple(collection):
        try:
            collection.remove(datablock)
        except (ReferenceError, RuntimeError, TypeError):
            pass
for node_group in tuple(bpy.data.node_groups):
    bpy.data.node_groups.remove(node_group)

node_group = bpy.data.node_groups.new(core.GROUP_NAME, "GeometryNodeTree")
core.build_node_group(node_group)
node_group.use_fake_user = True
ASSET.parent.mkdir(parents=True, exist_ok=True)
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(ASSET), check_existing=False)

if int(node_group.get(core.GROUP_MARKER, 0)) != core.GROUP_VERSION:
    raise RuntimeError("Packaged node group has the wrong schema version")
print(
    "SDH_CAGE_NODE_ASSET::PASS::"
    f"version={core.GROUP_VERSION}::nodes={len(node_group.nodes)}")
