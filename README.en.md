# World-leading Simple Deform Helper V2

[简体中文](README.zh_HANS.md) · [日本語](README.ja_JP.md) · [한국어](README.ko_KR.md)

**Simple Deform Helper V2** is a non-destructive cage deformation workflow for Blender. It combines Bend, Twist, Taper, and Stretch in one previewable, sortable, animatable system while retaining direct controls for Blender's native Simple Deform modifier.

![Simple Deform Helper V2 feature comparison](docs/simple_deform_helper_v2_comparison.svg)

## Highlights

- Combine Bend, Twist, Taper, and Stretch in one cage, then reorder deformation layers by drag and drop.
- Create independent cage stages or connected chained cages with gaps, automatic reconnection, and synchronized seam-end scaling.
- Edit top and bottom length, scale, and offset independently; keep cage boundaries inside the evaluated stage input bounds.
- Choose horizontal or vertical Bend Trend directions on all six cage faces; the cage aligns and fits after a choice.
- Shape-specific controller colors and forms for Bend, Twist, Taper, and Stretch, with hover tooltips.
- Geometry Nodes driven workflow for Mesh, Curve, Surface, and Text; Lattice objects expose a legacy Simple Deform entry point.
- A dedicated Simple Deformer V2 N-panel with Expand All, per-stage mute/remove, chain batch editing, and full cage-stack removal.
- Duplication-safe ownership, hidden helper collections, animation/render synchronization, and stable real-time previews.
- UI translations for Simplified Chinese, Japanese, Korean, and English.

## Quick start

1. Select a Mesh, Curve, Surface, or Text object in Object Mode.
2. Open the **Simple Deformer V2** tab in the 3D View sidebar.
3. Click **Add Cage Deform**, then add and reorder Bend, Twist, Taper, or Stretch layers.
4. Use **Align & Fit** for one cage or **Align & Fit Chain** for a connected chain.
5. Edit the full cage under **Cage Controls** and shape each end under **Independent Ends**.
6. Use **Add Chained Cages** or **Subdivide to Chained Cages** when a continuous segmented deformation is needed.

The generated Geometry Nodes stages remain valid when the extension is disabled.

## Comparison scope

The comparison graphic summarizes common deformation workflows for Maya, 3ds Max, MODO, and Cinema 4D. It is workflow-oriented rather than a claim that those applications cannot reproduce a result; V2's advantage is the focused combination of these controls in one Blender-native, ordered cage workflow.

## Legacy modifier workflow

For objects that are not suitable for cage deformation, use **Add Simple Deform (Legacy)** in the N-panel. Native Simple Deform stages still support multiple modifiers, stage switching, axis gizmos, limits, Origin modes, and wireframe preview.

## Support

- Blender 4.2 LTS and newer.
- Cage workflow: Mesh, Curve, Surface, and Text.
- Lattice: legacy Simple Deform modifier entry with an explicit cage-not-supported notice.
- Smooth bending requires sufficient geometry segments; the panel warns when topology is too low.

## Installation

Download `simple_deform_helper-2.0.0.zip` from GitHub Releases and install it via **Edit > Preferences > Get Extensions > Install from Disk**. Use the release extension ZIP, not GitHub's generated Source code ZIP.

## Feedback

Please include the Blender version, OS, GPU, reproduction steps, console log, and a minimal `.blend` file. Project: [AIGODLIKE/simple_deform_helper](https://github.com/AIGODLIKE/simple_deform_helper).
