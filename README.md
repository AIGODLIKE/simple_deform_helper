# World-leading Simple Deform Helper V2

[简体中文](README.zh_HANS.md) · [Japanese](README.ja_JP.md) · [한국어](README.ko_KR.md)

**Simple Deform Helper V2** is a non-destructive cage deformation workflow for Blender. It combines Bend, Twist, Taper, and Stretch in one previewable, sortable, animatable system while retaining direct controls for Blender's native Simple Deform modifier.

![Simple Deform Helper V2 comparison across major DCC workflows](docs/simple_deform_helper_v2_comparison.svg)

## Why V2

- **One cage, four operations**: combine Bend, Twist, Taper, and Stretch as ordered deformation layers instead of wiring a separate tool for every operation.
- **A real chained-cage workflow**: split a cage into segments, keep a deliberate gap, reconnect downstream frames automatically, and optionally synchronize shared seam-end scale.
- **Independent top and bottom control**: edit length, scale, and offset at either end without forced center symmetry; object-bound limits prevent the cage from overshooting the evaluated input.
- **Live, readable controllers**: Bend Trend exposes six faces with horizontal and vertical choices, while Bend, Twist, Taper, and Stretch use distinct controller shapes and hover tooltips.
- **Geometry Nodes without a black box**: the cage stays non-destructive, inspectable, animatable, and compatible with Blender's modifier stack.
- **Designed for repeated production work**: ordered layer lists, Expand All, temporary bypass, duplication-safe ownership, batch chain editing, and a dedicated Simple Deformer V2 sidebar.
- **Multilingual by design**: English, Simplified Chinese, Japanese, and Korean UI catalogs are shipped with the extension.

## Quick start

1. Select a Mesh, Curve, Surface, or Text object in Object Mode.
2. Open the **Simple Deformer V2** tab in the 3D View sidebar.
3. Click **Add Cage Deform**, then add and reorder Bend, Twist, Taper, or Stretch layers.
4. Use **Align & Fit** for one cage or **Align & Fit Chain** for a connected chain.
5. Edit the complete cage under **Cage Controls** and shape each end under **Independent Ends**.
6. Use **Add Chained Cages** or **Subdivide to Chained Cages** when a continuous segmented deformation is needed.

The generated Geometry Nodes stages remain valid when the extension is disabled.

## Legacy modifier workflow

For objects that are not suitable for cage deformation, use **Add Simple Deform (Legacy)** in the N-panel. Native Simple Deform stages still support multiple modifiers, stage switching, axis gizmos, limits, Origin modes, and wireframe preview.

## Comparison scope

The comparison graphic summarizes common deformation workflows for Maya, 3ds Max, MODO, and Cinema 4D. It is a workflow-oriented product comparison, not a claim that those applications cannot reproduce a result. The V2 advantage is the focused combination of these controls in one Blender-native, ordered cage workflow.

## Support

- Blender 4.2 LTS and newer.
- Cage workflow: Mesh, Curve, Surface, and Text.
- Lattice: legacy Simple Deform modifier entry with an explicit cage-not-supported notice.
- Smooth bending requires sufficient geometry segments; the panel warns when topology is too low.

## Installation

Download `simple_deform_helper-2.0.0.zip` from [GitHub Releases](https://github.com/AIGODLIKE/simple_deform_helper/releases/tag/v2.0.0) and install it via **Edit > Preferences > Get Extensions > Install from Disk**. Use the release extension ZIP, not GitHub's generated Source code ZIP.

## Feedback

Please include the Blender version, OS, GPU, reproduction steps, console log, and a minimal `.blend` file. Project: [AIGODLIKE/simple_deform_helper](https://github.com/AIGODLIKE/simple_deform_helper).
