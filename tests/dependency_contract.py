"""Static contract for the cage package's explicit dependency boundaries."""
from __future__ import annotations

import ast
import builtins
import symtable
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAGE = ROOT / "cage_deform"
TARGETS = (
    CAGE / "core.py",
    CAGE / "deform_contract.py",
    CAGE / "deform_math.py",
    CAGE / "node_graph.py",
    CAGE / "node_runtime.py",
    CAGE / "node_schema.py",
)
RUNTIME_GLOBALS = {"__file__", "__name__", "__package__"}


def unresolved_globals(path):
    source = path.read_text(encoding="utf-8")
    table = symtable.symtable(source, str(path), "exec")
    bound = {
        symbol.get_name()
        for symbol in table.get_symbols()
        if symbol.is_assigned() or symbol.is_imported() or symbol.is_namespace()
    }
    required = set()

    def collect(scope):
        required.update(
            symbol.get_name()
            for symbol in scope.get_symbols()
            if symbol.is_referenced() and symbol.is_global()
        )
        for child in scope.get_children():
            collect(child)

    collect(table)
    return required - bound - set(dir(builtins)) - RUNTIME_GLOBALS


def globals_update_calls(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    matches = []
    for node in ast.walk(tree):
        function = getattr(node, "func", None)
        owner = getattr(function, "value", None)
        if not (
                isinstance(node, ast.Call) and
                isinstance(function, ast.Attribute) and
                function.attr == "update" and
                isinstance(owner, ast.Call) and
                isinstance(owner.func, ast.Name) and
                owner.func.id == "globals"
        ):
            continue
        matches.append(getattr(node, "lineno", 0))
    return matches


failures = []
for path in TARGETS:
    unresolved = sorted(unresolved_globals(path))
    if unresolved:
        failures.append(f"{path.name}: unresolved globals {unresolved!r}")

for path in CAGE.glob("*.py"):
    lines = globals_update_calls(path)
    if lines:
        failures.append(f"{path.name}: globals().update at lines {lines!r}")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    binders = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and
        node.name == "bind_core"
    ]
    if binders:
        failures.append(f"{path.name}: bind_core at lines {binders!r}")

if failures:
    raise AssertionError("\n".join(failures))

print("PASS::EXPLICIT_CAGE_DEPENDENCY_CONTRACT")
