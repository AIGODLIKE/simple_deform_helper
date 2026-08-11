"""Static contract for translated Cage Chain operator reports."""

import ast
from pathlib import Path
from string import Formatter


SOURCE = Path(__file__).resolve().parents[1]
CHAIN_PATH = SOURCE / "cage_deform" / "chain.py"
TRANSLATION_PATH = SOURCE / "translate.py"

REPORT_TEMPLATES = {
    "Select a supported target object first",
    "Cage Deform core is unavailable",
    "Created {count} cage stages",
    "More than 3 cage stages may reduce viewport performance",
    "Could not create cage chain: {error}",
    "Only a single cage can be subdivided",
    "Animated cage parameters cannot be subdivided safely",
    "Taper collapses at an interior split boundary",
    "Subdivided cage into {count} chained stages",
    "Subdivided cage into {count} chained stages (gap clamped to preserve range)",
    "Could not subdivide cage: {error}",
    "Could not batch edit chain: {error}",
    "No matching cage values were changed",
    "Updated {count} cage stages",
    "No cage chain metadata was found",
    "Subdivide does not yet preserve these layers: {layers}",
    "Missing cage stages: {indices}",
    "Duplicate cage stage indices: {indices}",
    "A non-cage modifier is inserted inside the chain",
    "A chain stage has no matching controller",
    "Chain stages use different connection modes",
    "Cage chain is broken",
    "No Cage Chain was found",
    "Reconnected {count} cage stages",
}


def translation_entries():
    tree = ast.parse(TRANSLATION_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and
                   target.id == "translations_dict" for target in node.targets):
            continue
        if not isinstance(node.value, ast.Dict):
            break
        return {
            key.value: value.value
            for key, value in zip(node.value.keys, node.value.values)
            if (isinstance(key, ast.Constant) and isinstance(key.value, str) and
                isinstance(value, ast.Constant) and isinstance(value.value, str))
        }
    raise AssertionError("translations_dict was not found")


def format_fields(value):
    return {
        field_name
        for _literal, field_name, _format_spec, _conversion
        in Formatter().parse(value)
        if field_name is not None
    }


entries = translation_entries()
missing = sorted(REPORT_TEMPLATES - entries.keys())
if missing:
    raise AssertionError(f"missing translated report keys: {missing!r}")

for source in sorted(REPORT_TEMPLATES):
    translated = entries[source]
    if not translated or translated == source:
        raise AssertionError(f"Chinese report is not translated: {source!r}")
    if format_fields(source) != format_fields(translated):
        raise AssertionError(
            f"placeholder mismatch for {source!r}: {translated!r}")

chain_tree = ast.parse(CHAIN_PATH.read_text(encoding="utf-8"))
used_templates = set()
raw_reports = []
for node in ast.walk(chain_tree):
    if not isinstance(node, ast.Call):
        continue
    if (isinstance(node.func, ast.Name) and node.func.id == "iface_" and
            node.args and isinstance(node.args[0], ast.Constant)):
        used_templates.add(node.args[0].value)
    if (isinstance(node.func, ast.Attribute) and node.func.attr == "report" and
            len(node.args) >= 2 and
            isinstance(node.args[1], (ast.Constant, ast.JoinedStr))):
        raw_reports.append(node.lineno)

unused = sorted(REPORT_TEMPLATES - used_templates)
if unused:
    raise AssertionError(f"report templates do not use iface_: {unused!r}")
if raw_reports:
    raise AssertionError(
        f"report calls bypass pgettext_iface at lines {raw_reports!r}")

print("SDH_CHAIN_TRANSLATION::SUMMARY::PASS")
