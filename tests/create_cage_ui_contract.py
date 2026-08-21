"""Static contract for concise cage-creation labels and chain options."""
from __future__ import annotations

import ast
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1]
UI_SOURCE = (SOURCE / "cage_deform" / "ui.py").read_text(encoding="utf-8")
CHAIN_SOURCE = (SOURCE / "cage_deform" / "chain.py").read_text(encoding="utf-8")
TRANSLATION_SOURCE = (SOURCE / "translate.py").read_text(encoding="utf-8")


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def literal_mapping(name):
    tree = ast.parse(TRANSLATION_SOURCE)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name
               for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"translation mapping {name} is missing")


for label in (
        "Create Cage", "Standard", "Standard Chain", "Shear",
        "Shear Chain", "FFD", "FFD Chain", "Curve",
        "Simple Deform (Legacy)"):
    check(f'"{label}"' in UI_SOURCE, f"creation label is missing: {label}")
for old_label in (
        "Add Standard Cage", "Add Standard Chain", "Add Shear Cage",
        "Add Shear Chain", "Add FFD Cage", "Add FFD Chain",
        "Add Curve Cage", "Add Simple Deform (Legacy)"):
    check(f'"{old_label}"' not in UI_SOURCE,
          f"verbose creation label survived: {old_label}")
check('operator_context = "INVOKE_DEFAULT"' in UI_SOURCE,
      "chain creation buttons do not explicitly invoke their options")
check("invoke_props_dialog" in CHAIN_SOURCE,
      "standard chain creation no longer opens its option dialog")

expected = {
    "_CREATE_CAGE_UI_ZH": {
        "Create Cage": "创建笼", "Standard": "标准型",
        "Standard Chain": "标准型链式", "Shear": "斜切型",
        "Shear Chain": "斜切型链式", "FFD": "FFD型",
        "FFD Chain": "FFD型链式", "Curve": "曲线型",
        "Simple Deform (Legacy)": "简易形变（传统）",
    },
    "_CREATE_CAGE_UI_JA": {
        "Create Cage": "ケージを作成", "Standard": "標準型",
        "Standard Chain": "標準型チェーン", "Shear": "シアー型",
        "Shear Chain": "シアー型チェーン", "FFD": "FFD型",
        "FFD Chain": "FFD型チェーン", "Curve": "カーブ型",
        "Simple Deform (Legacy)": "Simple Deform（従来）",
    },
    "_CREATE_CAGE_UI_KO": {
        "Create Cage": "케이지 만들기", "Standard": "표준형",
        "Standard Chain": "표준형 체인", "Shear": "전단형",
        "Shear Chain": "전단형 체인", "FFD": "FFD형",
        "FFD Chain": "FFD형 체인", "Curve": "커브형",
        "Simple Deform (Legacy)": "Simple Deform(레거시)",
    },
}
for name, mapping in expected.items():
    check(literal_mapping(name) == mapping, f"{name} does not match the UI contract")

button_keys = (
    "Standard", "Standard Chain", "Shear", "Shear Chain", "FFD",
    "FFD Chain", "Curve", "Simple Deform (Legacy)")
for key in button_keys:
    check(not any(token in expected["_CREATE_CAGE_UI_ZH"][key]
                  for token in ("添加", "笼")),
          f"Chinese button remains verbose: {key}")
    check(not any(token in expected["_CREATE_CAGE_UI_JA"][key]
                  for token in ("追加", "ケージ")),
          f"Japanese button remains verbose: {key}")
    check(not any(token in expected["_CREATE_CAGE_UI_KO"][key]
                  for token in ("추가", "케이지")),
          f"Korean button remains verbose: {key}")

print("SDH_CREATE_CAGE_UI_CONTRACT::PASS")
