"""Verify the >3-stage warning in dialogs and every creation path."""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
CHAIN_PATH = SOURCE / "cage_deform" / "chain.py"
sys.path.insert(0, str(SOURCE.parent))


chain = importlib.import_module(f"{PACKAGE}.cage_deform.chain")


class ReportProbe:
    def __init__(self):
        self.records = []

    def report(self, levels, message):
        self.records.append((set(levels), str(message)))


class LayoutProbe:
    def __init__(self):
        self.alert = False
        self.boxes = []
        self.labels = []

    def box(self):
        child = LayoutProbe()
        self.boxes.append(child)
        return child

    def label(self, *, text, icon="NONE"):
        self.labels.append((str(text), str(icon)))


operator = ReportProbe()
assert not chain._report_chain_performance_warning(operator, 3)
assert not operator.records
assert chain._report_chain_performance_warning(operator, 4)
assert operator.records == [
    ({"WARNING"}, chain.CHAIN_PERFORMANCE_WARNING),
]

layout = LayoutProbe()
assert not chain._draw_chain_performance_warning(layout, 3)
assert not layout.boxes
assert chain._draw_chain_performance_warning(layout, 4)
assert len(layout.boxes) == 1
assert layout.boxes[0].alert
assert layout.boxes[0].labels == [
    (chain.CHAIN_PERFORMANCE_WARNING, "ERROR"),
]


class CallCollector(ast.NodeVisitor):
    def __init__(self):
        self.classes = []
        self.functions = []
        self.calls = []

    def visit_ClassDef(self, node):
        self.classes.append(node.name)
        self.generic_visit(node)
        self.classes.pop()

    def visit_FunctionDef(self, node):
        self.functions.append(node.name)
        self.generic_visit(node)
        self.functions.pop()

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            self.calls.append((
                self.classes[-1] if self.classes else None,
                self.functions[-1] if self.functions else None,
                node.func.id,
            ))
        self.generic_visit(node)


collector = CallCollector()
collector.visit(ast.parse(CHAIN_PATH.read_text(encoding="utf-8")))

expected_calls = {
    ("SDH_OT_add_cage_chain", "draw", "_draw_chain_performance_warning"),
    ("SDH_OT_add_cage_chain", "execute", "_report_chain_performance_warning"),
    ("SDH_OT_subdivide_cage_to_chain", "draw", "_draw_chain_performance_warning"),
    ("SDH_OT_subdivide_cage_to_chain", "execute", "_report_chain_performance_warning"),
    (None, "_subdivide_ffd_cage_to_chain", "_report_chain_performance_warning"),
}
missing = expected_calls.difference(collector.calls)
assert not missing, f"missing warning integrations: {sorted(missing)!r}"


def new_cube(name, location):
    bpy.ops.object.select_all(action="DESELECT")
    bpy.ops.mesh.primitive_cube_add(location=location)
    target = bpy.context.object
    target.name = name
    return target


addon = importlib.import_module(PACKAGE)
entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon.register()

reported_counts = []
original_report_warning = chain._report_chain_performance_warning


def tracked_report_warning(operator, count):
    reported_counts.append(int(count))
    return original_report_warning(operator, count)


chain._report_chain_performance_warning = tracked_report_warning

new_cube("Warning Add Chain", (-4.0, 0.0, 0.0))
assert bpy.ops.sdh.add_cage_chain(count=4) == {"FINISHED"}

new_cube("Warning Standard Subdivide", (0.0, 0.0, 0.0))
assert bpy.ops.sdh.add_cage_deform(cage_type="STANDARD") == {"FINISHED"}
assert bpy.ops.sdh.subdivide_cage_to_chain(count=4) == {"FINISHED"}

new_cube("Warning FFD Subdivide", (4.0, 0.0, 0.0))
assert bpy.ops.sdh.add_cage_deform(cage_type="FFD") == {"FINISHED"}
assert bpy.ops.sdh.subdivide_cage_to_chain(count=4) == {"FINISHED"}

assert reported_counts == [4, 4, 4], reported_counts
chain._report_chain_performance_warning = original_report_warning
addon.unregister()

print("SDH_CHAIN_PERFORMANCE_WARNING::SUMMARY::PASS")
