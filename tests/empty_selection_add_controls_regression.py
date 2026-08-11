"""Keep target-dependent sidebar actions disabled with an empty selection."""
from __future__ import annotations

import importlib
import os
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

import bpy


SOURCE = Path(__file__).resolve().parents[1]
INSTALLED_PACKAGE = os.environ.get("SDH_TEST_MODULE")
PACKAGE = INSTALLED_PACKAGE or SOURCE.name
RESULT = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(SOURCE.parent))


class LayoutRecorder:
    def __init__(self, records, parent=None):
        self.records = records
        self.parent = parent
        self._enabled = True
        self.alignment = "EXPAND"
        self.alert = False

    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = bool(value)

    def _effective_enabled(self):
        current = self
        while current is not None:
            if not current.enabled:
                return False
            current = current.parent
        return True

    def row(self, **_kwargs):
        return LayoutRecorder(self.records, parent=self)

    def box(self):
        return LayoutRecorder(self.records, parent=self)

    def operator(self, operator_id, *, text="", icon="NONE", **_kwargs):
        self.records.append({
            "operator": operator_id,
            "text": text,
            "icon": icon,
            "enabled": self._effective_enabled(),
        })
        return SimpleNamespace()

    def label(self, **_kwargs):
        return None

    def prop(self, *_args, **_kwargs):
        return None


def finish(value):
    RESULT.write_text(value, encoding="utf-8")
    bpy.ops.wm.quit_blender()


try:
    addon = importlib.import_module(PACKAGE)
    if not INSTALLED_PACKAGE:
        entry = bpy.context.preferences.addons.new()
        entry.module = PACKAGE
        addon.register()
    core = importlib.import_module(f"{PACKAGE}.cage_deform.core")
    chain = importlib.import_module(f"{PACKAGE}.cage_deform.chain")
    merge = importlib.import_module(f"{PACKAGE}.cage_deform.merge")
    ui = importlib.import_module(f"{PACKAGE}.cage_deform.ui")

    bpy.ops.mesh.primitive_cube_add()
    stale_active = bpy.context.object
    bpy.ops.object.select_all(action="DESELECT")
    if tuple(bpy.context.selected_objects):
        raise RuntimeError("test setup did not clear object selection")
    if bpy.context.view_layer.objects.active != stale_active:
        raise RuntimeError("test setup did not retain an unselected active object")

    if core.SDH_OT_add_cage_deform.poll(bpy.context):
        raise RuntimeError("Add Cage poll accepted an empty selection")
    if chain.SDH_OT_add_cage_chain.poll(bpy.context):
        raise RuntimeError("Add Chain poll accepted an unselected active object")
    if merge.SDH_OT_create_deform_merge.poll(bpy.context):
        raise RuntimeError("Merge Selected poll accepted an empty selection")

    records = []
    panel = SimpleNamespace(layout=LayoutRecorder(records))
    ui.SDH_CAGE_PT_deform.draw(panel, bpy.context)
    target_actions = tuple(
        record for record in records
        if record["operator"] in {
            ui._OP_ADD,
            ui._OP_ADD_CHAIN,
            ui._OP_CREATE_MERGE,
        }
    )
    expected_count = 8
    if len(target_actions) != expected_count:
        raise RuntimeError(
            f"expected {expected_count} target actions, got {target_actions!r}")
    enabled = tuple(record for record in target_actions if record["enabled"])
    if enabled:
        raise RuntimeError(
            f"empty-selection target actions remained enabled: {enabled!r}")

    finish("PASS::EMPTY_SELECTION_ADD_CONTROLS_DISABLED")
except Exception:
    finish("FAIL:\n" + traceback.format_exc())
