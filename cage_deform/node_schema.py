"""Stable Geometry Nodes names and persistence keys for cage deformation."""
from __future__ import annotations

from .deform_contract import DEFORM_ORDER


GROUP_MARKER = "_sdh_cage_deform_group"
# Version 41 adds ordered global chain baselines around Shear and Bend.
GROUP_VERSION = 41

_LEGACY_CHAIN_CORRECTION_ATTRIBUTE = "_sdh_chain_correction_attribute"
_LEGACY_CHAIN_CORRECTION_ACTIVE = "_sdh_chain_correction_active"

DEFORM_ORDER_SIGNATURE = "_sdh_cage_deform_order_signature"
_INTERFACE_CACHE_TOKEN = "_sdh_cage_interface_cache_token"
DEFORM_ORDER_START_NODE = "SDH Deform Order Start"
DEFORM_ORDER_END_NODE = "SDH Deform Order End"
DEFORM_CHAIN_OUTPUT_INPUT_NODE = "SDH Chain Output Input"
DEFORM_CHAIN_OUTPUT_NODE = "SDH Chain Output"
DEFORM_BLOCK_INPUT_NODE = {
    name: f"SDH {name.title()} Input" for name in DEFORM_ORDER
}
DEFORM_BLOCK_OUTPUT_NODE = {
    name: f"SDH {name.title()} Output" for name in DEFORM_ORDER
}
NODE_FRAME_LOCAL = "SDH Frame Local Space"
NODE_FRAME_PROFILE = "SDH Frame Cage Profile"
NODE_FRAME_MODE_OUTPUT = "SDH Frame Mode Output"
DEFORM_BLOCK_FRAME_NODE = {
    name: f"SDH Frame {name.title()}" for name in DEFORM_ORDER
}
DEFORM_FRAME_MIN_WIDTH = {
    "BEND": 1500.0,
    "TWIST": 900.0,
    "TAPER": 700.0,
    "STRETCH": 1100.0,
    "SHEAR": 800.0,
    "FFD": 1800.0,
    "CURVE": 2100.0,
}
DEFORM_FRAME_START_X = 500.0
DEFORM_FRAME_Y = 600.0
DEFORM_FRAME_GAP = 180.0
