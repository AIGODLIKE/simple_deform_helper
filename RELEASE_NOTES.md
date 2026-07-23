# Simple Deform Helper 2.0.0

## Highlights

- Renamed the product presentation to **Simple Deform Helper V2** with the Chinese title **世界领先的简易变形器 V2**.
- One cage can combine Bend, Twist, Taper, and Stretch through an ordered deformation-layer list.
- Added chained-cage workflows with segment subdivision, seam reconnection, gaps, batch editing, and optional shared seam-end scaling.
- Added independent top/bottom length, scale, and offset controls with object-bound limits.
- Added six-face Bend Trend selection, shape-specific controllers, hover tooltips, and a dedicated Simple Deformer V2 N-panel.
- Added a multilingual workflow comparison graphic covering Maya, 3ds Max, MODO, and Cinema 4D at `docs/simple_deform_helper_v2_comparison.svg`.
- Release metadata, documentation, and install archive are aligned on version `2.0.0`.

## Validation

- Python bytecode compilation and extension manifest validation.
- Blender headless register/unregister smoke tests on the supported build matrix.
- Runtime translation checks for Simplified Chinese, Japanese, Korean, and English.

## 0.8.2

## Added in 0.8.2

- Independent top and bottom length handles are now constrained to the evaluated input object's bounds by default.
- Added a translated **Limit to Object Bounds** option for workflows that intentionally need to extend the cage.
- Boundary limits follow the selected cage axis and the geometry entering the current stack stage.

## 0.8.1

## Added in 0.8.1

- A six-face Bend Trend palette with two perpendicular curved-arrow choices on every face. Red and green distinguish the horizontal and vertical trend.
- Click-to-close Bend Trend choices, with Ctrl-click available when several directions need to be compared.
- Per-stage trash buttons plus a **Remove Cage Stack** action in the N-panel.
- A dedicated **Simple Deformer** N-panel tab, translated as **简易变形器** in Simplified Chinese.

## Fixed in 0.8.1

- Twist now uses a large ring that scales with the cage cross-section instead of a fixed-size icon.
- Duplicated objects now detach cage ownership, node groups, and controllers from the source object before editing.
- Re-adding Cage Deform after removing copied Geometry Nodes modifiers now creates a working, independently owned stage.

## 0.8.0

## Added in 0.8.0

- A six-way RGB viewport axis switch for +X/-X, +Y/-Y, and +Z/-Z. Diamonds represent positive directions and rings represent negative directions.
- A dedicated Bend Direction ring instead of requiring a hidden modifier gesture.
- A circular Twist controller whose drag follows the ring and crosses the angle seam continuously.
- Distinct Bend, Twist, Taper, and Stretch handle shapes, colors, and revealed Empty display styles.
- Complete English and Simplified Chinese labels, tooltips, viewport hints, and documentation for the new controls.

## Changed in 0.8.0

- Cage controllers and managed Origin helpers are consolidated in a **Simple Deform Controls** collection and hidden by default.
- Move, Rotate, Scale, and Select Cage reveal only the active controller; Return to Object hides it again.
- Flat custom handles now face the viewport, improving legibility and reducing view-angle flicker.
- The Twist handle is separated from the top end-shape handle to avoid overlap.

## 0.7.0

## Added in 0.7.0

- Independent top and bottom cage-length handles.
- Screen-projected dragging along the visible cage direction, with Shift precision and Ctrl snapping.
- Automatic cage-center compensation that keeps the opposite boundary fixed.
- Yellow/amber boundary connectors and complete English/Simplified Chinese guidance.

## Changed in 0.7.0

- Separated longitudinal boundary adjustment from cyan/green cross-section shaping.
- Clarified the Independent Ends panel and viewport color language.

## 0.6.0

## Added in 0.6.0

- Separate Top and Bottom X/Z Scale and Offset controls for asymmetric cage shaping.
- Cyan top and green bottom viewport handles that reshape only the selected end, with Alt slide, Shift precision, and Ctrl snapping.
- A one-click Reset Independent Ends action.
- Automatic in-place upgrade of saved 0.5 Cage Deform node groups.

## Changed in 0.6.0

- The cyan cage now follows the actual final Bend, Twist, Taper, Stretch, and end-profile result.
- Cage controllers use compact axes instead of an undeformed cube display.
- Generated Geometry Nodes groups now include the independent-end profile, while Within Box keeps outside points unchanged.
- Updated English and Simplified Chinese panel labels, tooltips, hints, usage documentation, and regression coverage.

## Added in 0.5.0

- A generalized Cage Deform system with Bend, Twist, Taper, and Stretch shapes.
- Shape-aware Angle, Factor, Direction, and Preserve Volume controls.
- Direct Auto/+X/-X/+Y/-Y/+Z/-Z orientation buttons that align and fit the cage immediately.
- Move, Rotate, and Scale cage actions using Blender's standard transform tools.
- Multi-rail orange viewport guides for Twist, Taper, and Stretch.
- Full Simplified Chinese translations for the Cage Deform panel, operators, modes, tooltips, and viewport hints.
- Silent migration of prototype cage stages, ownership markers, settings, and animation paths to the 0.5 data model.

## Changed in 0.5.0

- Reorganized the sidebar into Shape, Cage Stack, and Cage Controls sections.
- Replaced prototype terminology throughout the interface, source package, tests, metadata, and documentation.
- Renamed the generated node groups and controller data to the generic Cage Deform vocabulary.

## Retained from 0.4.0

- Geometry Nodes-powered, independent transformable cages.
- Limited, Within Box, and Unlimited spatial modes.
- Multiple cage stages, duplication, stage ordering, animation synchronization, and render synchronization.
- Persistent cyan cage and orange deformation guide.
- Mesh, Curve, and Text targets on Blender 4.2 LTS and newer.

## 0.3.2 fixes

- Prevented transient stage-evaluation and wireframe-preview objects from flashing as gray bounds.
- Kept the last complete wireframe frame visible between rate-limited updates.
- Refreshed previews after numeric, keyframe, driver, and script changes.

## 0.3.0–0.3.1 highlights

- True stage-aware support for multiple native Simple Deform modifiers.
- Previous, next, and named-stage selection.
- Optional translucent bounds for non-active stages.
- Low-topology guidance and one-click non-destructive subdivision.
- Safe UUID ownership for managed Origin objects.
- Focused animation tools, throttled preview evaluation, and clean timer/GPU lifecycle handling.
