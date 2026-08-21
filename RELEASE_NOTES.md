# Simple Deform Helper 2.7.50

## Responsive Chained Cage Scaling and Creation UI

- Limited top and bottom scale dragging to the active chained cage and its
  shared-edge neighbor, while keeping the visible cages synchronized with the
  controlled geometry through the cumulative chain evaluation path.
- Optimized interactive chain previews with bounded deformation-plan caches,
  dedicated shared-scale socket updates, and deferred rebuilding of unrelated
  cage previews. Six-segment drag benchmarks improved by about 30x on Blender
  5.0.1 and 5.2.0.
- Clamped chained-cage gap values to `0.00-0.99` across properties, operators,
  metadata reads, and internal writes.
- Restored the Standard and Standard Chained quick-create menus for Bend,
  Twist, Taper, Stretch, and Shear, and kept dedicated Standard, Standard
  Chained, Shear, Shear Chained, FFD, FFD Chained, and Curve creation choices.
- Simplified localized creation labels and added regression coverage for scale
  locality, object/cage synchronization, drag settling, UI contracts, and
  translated labels.

# Simple Deform Helper 2.7.48

## Animated Cage Recovery After File Load

- Kept a lightweight persistent load-discovery handler active even when
  Blender starts on an empty scene, so subsequently opened files can discover
  their managed cages without reloading the extension.
- Rebuilt load-cleared timers and message-bus subscriptions, then immediately
  synchronized controller animation into Geometry Nodes modifier inputs.
- Added a cold-start regression that opens an animated cage file after an empty
  startup and verifies distinct frame values reach the controlled object.

# Simple Deform Helper 2.7.47

## Optional FFD Foldover Guard

- Added an opt-in `FFD Safety` control with `Prevent Foldover` mode. It uses
  linear runtime interpolation and clamps point, line, face, Object Edit, and
  Native Edit changes to the last non-inverted lattice field.
- Kept `Unlimited` FFD range semantics independent: geometry may still be
  evaluated beyond the authored cage domain, while the cage itself cannot be
  folded by the safety guard.
- Cached the last valid Jacobian and limited interactive checks to cells touched
  by the current edit, keeping the guard responsive at the supported 6x6x6
  resolution.
- Increased each checked cell from corner/center samples to a 5x5x5 grid so
  interior trilinear foldovers cannot pass the coarse sampling check.

# Simple Deform Helper 2.7.46

## Reliable and Faster FFD Scope Refresh

- Merged the manual FFD scope repair: source-mesh coordinates and membership
  masks are cached per managed stage and recomputed with Blender's bundled
  NumPy, avoiding repeated dense vertex walks during point edits.
- Refreshes cached scope membership after real mesh geometry changes while
  suppressing the dependency-graph echo caused by the add-on's own vertex
  group writes, preventing stale or drifting FFD influence regions.
- Clears and prunes transient scope state across undo/redo, stage removal, and
  controller cleanup; verified with Blender 5.0.1 and 5.2.0 FFD regressions.

# Simple Deform Helper 2.7.45

## Spaced Twist and Shear Controls

- Kept the Twist ring centered on its deformation axis while moving the Shear
  handle into a stable screen-space lane 64 pixels to the right.
- Reused the same offset frame for Shear drawing, axis picking, modal start,
  and modifier-key restarts so dragging no longer jumps back to the section.
- Added Blender 5.0/5.2 viewport checks for Bend/Twist/Shear spacing, compact
  size, X/Z arm picking, and twelvefold object-scale changes.

# Simple Deform Helper 2.7.44

## Bend-Sized Twist and Shear Controls

- Made Twist and Shear use compact fixed screen-space Gizmo sizing comparable
  to the Bend angle handle, independent of object or cage dimensions.
- Updated Shear X/Z arm picking to use the final screen-scaled Gizmo matrix so
  its visual controls and click regions remain aligned at every zoom level.
- Added Blender 5.0/5.2 real-viewport coverage that compares Bend, Twist, and
  Shear across a twelvefold object-scale change.

# Simple Deform Helper 2.7.43

## Stable Twist and Shear Gizmo Sizing

- Moved cage-relative Twist and Shear control sizing into their world-space
  matrices instead of multiplying Blender's screen-space Gizmo scale.
- Preserved section-relative placement and Shear axis hit testing while
  preventing unapplied or non-uniform object scale from inflating the controls.
- Added Blender 5.0/5.2 headless and real-viewport regression coverage for
  large object scales.

# Simple Deform Helper 2.7.42

## Responsive Weighted FFD Controls

- Decoupled authored FFD control positions from weighted runtime evaluation,
  so Point, Line, and Face handles remain under the pointer at every weight.
- Made modal FFD writes absolute to the transform-start snapshot, preventing
  repeated mouse events from accumulating displacement as positive feedback.
- Added a quiet weighted-result ghost cage while the cyan authored cage stays
  fully editable; inactive FFD stages continue to show their evaluated result.
- Reworked Native Lattice Edit to use a temporary authored proxy that never
  participates in the modifier stack, eliminating low-weight division and
  making zero-weight points editable without affecting the controlled object.
- Derived Native Edit basis coordinates from U/V/W topology instead of the
  unstable edit-mode `LatticePoint.co` RNA view, and protected the live proxy
  from global orphan cleanup while preserving stale-proxy recovery.
- Added Blender 5.0/5.2 regressions for weighted Point/Line/Face dragging,
  idempotent pointer updates, zero-weight native editing, and ghost rendering.

# Simple Deform Helper 2.7.41

## FFD Native Editing, Influence Weights, and Reliable Hover State

- Restored distinct selected and hovered colors for batched FFD LINE and FACE
  controls, including the persistent FFD editor's modal hover path.
- Added controlled Blender-native Lattice Edit Mode for finite FFD cages;
  edits, selection, direct Tab exits, and companion visibility are synchronized
  back to the public cage state. Unlimited FFD keeps the existing Object Edit
  workflow because its expanded runtime grid is not losslessly reversible.
- Added per-point 0-1 influence weights with multi-selected numeric editing,
  effective-field evaluation, resolution resampling, chained subdivision,
  duplication, reset, and keyframe coverage.
- Added Blender 5.0/5.2 native-edit, weighted-resolution, and LINE/FACE real
  event regressions.

# Simple Deform Helper 2.7.40

## First-Click FFD Controls and Empty-Selection UI

- Restored the aggregate FFD Gizmo's fast screen-space hit testing so a newly
  created point highlights and starts dragging on the first click instead of
  falling through to Blender Object Select.
- Kept the target/controller selection authoritative through the initial FFD
  press-drag-release transaction, including Blender's late native pick pass.
- Disabled merge-selected, cage, and chained-cage creation controls when no
  supported target is selected, and aligned chained creation polling with the
  same selected-target rule.
- Added Blender 5.0/5.2 real-event and empty-selection UI regressions.

# Simple Deform Helper 2.7.39

## Persistent FFD Resolution Controls

- Kept the public Cage Deform stage active while rebuilding the hidden native
  Lattice companion for U/V/W resolution changes, so the sidebar and viewport
  Gizmos no longer disappear after editing a point count.
- Added Blender 5.0/5.2 headless matrices and real-sidebar redraw coverage for
  continuous U/V/W edits from 2 through 6 points.

# Simple Deform Helper 2.7.38

## Stable FFD Resolution Editing

- Preserved FFD offsets with cached native-basis resampling when U/V/W point
  counts change instead of copying one old point into many new points.
- Kept the active point and multi-selection stable, including symmetry across
  an odd-to-even resolution change and files missing the saved topology marker.
- Fixed inactive high-resolution FFD previews and hit testing to use the real
  eight grid endpoints rather than raw indices 0 through 7.
- Added Blender 5.0/5.2 coverage for 2-to-6 resolution edits, all four native
  interpolation modes, chain compatibility, and selection remapping.

# Simple Deform Helper 2.7.37

## Fast First Cage and Chain Performance Guidance

- Rebuilt the packaged Geometry Nodes template for schema 41 so the first
  cage no longer falls back to rebuilding the complete 844-node graph in
  Python.
- Reduced measured first-cage creation from roughly 6-7 seconds to about
  0.04 seconds on Blender 5.0 and 5.2.
- Added a non-blocking viewport-performance warning whenever chained creation
  or Standard/FFD subdivision requests more than three cage stages.
- Added direct packaged-template schema, cold/warm creation, warning-path, and
  four-locale regression coverage.

# Simple Deform Helper 2.7.36

## Complete Chained Profile Verification

- Kept non-Bend linear stacks in the source-frame global baseline path so
  Twist/Taper/Stretch/Shear combinations preserve asymmetric end profiles.
- Verified all 325 ordered Standard stacks for scale, offset, and combined
  profiles on Blender 5.0 and 5.2, including default and POS_Y alignment.
- Added physical seam, gap, preview, and named viewport evidence for the
  repaired chain behavior.

# Simple Deform Helper 2.7.35

## Offset-Profile Chained Cage Preview

- Evaluated subdivided end-scale and end-offset profiles through the same
  root-frame path used by Geometry Nodes.
- Kept cage wires, parameter controls, boundary handles, and end-shape handles
  synchronized with offset Standard cages after chained subdivision.
- Added Blender 5.0 and 5.2 regression coverage for offset profiles combined
  with Bend and the default +Z alignment.

# Simple Deform Helper 2.7.34

## Twist-First Chained Cage Preview

- Rebuilt subdivided pre-Bend cage previews from the original full-cage source
  domain, matching the Geometry Nodes global-prefix evaluation order.
- Kept cage wires, Bend/Twist controls, boundary handles, end-shape handles,
  and chained reconnection frames synchronized when Twist is above Bend.
- Added Blender 5.0 and 5.2 regression coverage for the default +Z alignment.

# Simple Deform Helper 2.7.33

## Chained End-Scale Propagation

- Propagate a shared end-scale edit through every affected downstream chain
  stage in the same atomic property update.
- Prevent upper stages from retaining stale Chain Input/Output frames until a
  second interaction with the affected cage.
- Added Blender 5.0 and 5.2 regression coverage for root end-scale edits.

# Simple Deform Helper 2.7.32

## Immediate Chained Boundary Refresh

- Flush queued chained-controller updates immediately after a direct root
  Top Offset or Bottom Offset property edit, including edits from the N-panel.
- Keep downstream Chain Input/Output frames and controller transforms in sync
  without requiring a second interaction with the affected cage.
- Added Blender 5.0 and 5.2 regression coverage for direct end-offset edits.

# Simple Deform Helper 2.7.31

## Chained Boundary Refresh

- Committed deferred downstream chain metadata when a root boundary or end
  shape Gizmo drag closes, instead of waiting for another cage interaction.
- Kept the refresh inside the same Gizmo undo transaction so the displayed
  chain and evaluated deformation remain in sync after one drag.
- Added Blender 5.0 and 5.2 regression coverage for the stale-root-boundary
  state and the formerly required second interaction.

# Simple Deform Helper 2.7.30

## Explicit Cage Dependencies

- Replaced the runtime `globals().update()` bindings between the cage core,
  deformation math, and Geometry Nodes builder with explicit imports.
- Split stable deformation semantics, node schema keys, and process-local node
  caches into dependency-neutral modules while preserving the existing core API.
- Added a standard-library dependency contract and CI gate for unresolved
  globals or a reintroduction of dynamic core binding.

## Validation

- Restored static undefined-name checking for the extracted cage modules; the
  previous 145 runtime-injected references now resolve statically.
- Covered Blender 5.0 and 5.2 runtime, cage, stack, chain, FFD, Curve, and
  register/unregister lifecycle paths after the refactor.

# Simple Deform Helper 2.7.29

## First External Box Selection

- Kept the controlled object active after creating an FFD or Curve cage while
  selecting its controllers as Timeline companions.
- Prevented deferred selection synchronization from restoring Blender's native
  tool before the first pre-edit box drag.
- Added a real-window regression for the first FFD and Curve pre-edit session.

# Simple Deform Helper 2.7.28

## FFD Resolution

- Limited FFD U, V, and W resolution to 6 points per axis (up to 6x6x6),
  including runtime clamping and chained FFD subdivision.
- Kept FFD axis changes aligned to the controller's current authored transform
  instead of a stale evaluated matrix.

## Chained Cage Stability

- Restored the deformation-name dependency used by extracted chain math.
- Reduced non-Bottom Origin and gap alignment error while preserving mixed Bend
  subdivision behavior.
- Refreshed chained global Stretch geometry, preview, sockets, and metadata
  immediately during live editing.

## Validation

- Added the FFD resolution/runtime regression and maximum-grid Gizmo draw smoke
  to the supported Blender CI matrix.

# Simple Deform Helper 2.7.27

## Curve Cross Sections

- Enabled Even Cross Sections by default for newly-created Curve cages.
- Preserved explicitly saved on/off states when opening existing projects.

# Simple Deform Helper 2.7.26

## Compact Panel and Multi-Object Cage Creation

- Made the default Professional Mode state show the compact cage panel;
  enabling it now reveals Deform Axis, Independent Ends, and Numeric Controls.
- A normal Add Cage click with multiple supported objects now creates one live
  deformation merge and adds the cage to that combined result.
- Ctrl-clicking Add Cage creates an independent cage on each selected supported
  object and keeps the original active object's cage active.
- Added translated tooltips and status messages for the new interaction.

# Simple Deform Helper 2.7.25

## Traditional Gizmo Undo

- Added explicit undo boundaries to traditional angle, factor, limit, and
  managed-Origin rotation Gizmos.
- Made the X/Y/Z axis buttons, keyboard axis switching, and bend-direction
  controls undo as one edit while keeping the Simple Deform modifier intact.
- Restored both limits when a limit drag is cancelled and prevented native
  Gizmo undo flags from adding duplicate undo steps.

# Simple Deform Helper 2.7.24

## FFD and Curve Control Undo

- Added per-transform undo boundaries to FFD point, line, and face editing.
- Added per-transform undo boundaries to Curve point and Bezier-handle editing.
- The first undo now restores the control edit while keeping its cage stage.
- Motionless clicks and zero-distance transforms do not add an undo record.

# Simple Deform Helper 2.7.23

## Cage Gizmo Undo Boundaries

- Added an undo transaction around viewport cage Gizmo edits so the first
  undo restores the value before the drag while keeping the cage stage.
- A second undo still removes the cage creation action.
- A click or an otherwise motionless drag does not create an extra undo step.
- Covered bend, twist, taper, stretch, shear, FFD, bend direction, end-shape,
  and boundary controls without changing N-panel actions.

# Simple Deform Helper 2.7.22

## Chain Stack Ordering

- Kept connected chain segments in their authored physical order instead of
  allowing a middle segment to become the chain root after a stack drag.
- Reordered connected chains as one modifier-stack block when moving them past
  an unrelated deformation stage.
- Restored accidental native Modifier-panel drags from persisted segment
  indices before reconnecting controller frames.
- Made internal deformation-layer reordering reconnect a chain atomically so
  downstream frames never remain stale for a redraw.
- Added regression coverage for Blender 5.0 and 5.2, including mixed layers,
  shared seam scale, gaps, and native stack drags.

# Simple Deform Helper 2.7.21

## Curve Cage Sidebar

- Grouped Curve cage controls into collapsible sections for mapping, guide
  presets, guide editing, and cross sections.
- Moved the Even Cross Sections toggle into the Cross Sections section header
  so its state stays visible without adding a separate utility row.
- Preserved per-cage disclosure state when a cage is duplicated.
- Added Chinese, Japanese, and Korean translations for the new section
  descriptions.

# Simple Deform Helper 2.7.20

## Curve Modal Handoff

- Exited persistent Curve point editing before handing a mouse press to cage
  boundary, end-shape, axis, parameter, or inactive-stage controls.
- Prevented top/bottom boundary drags from being misinterpreted as Curve box
  selection while preserving ordinary blank-space selection.

# Simple Deform Helper 2.7.19

## Viewport Depth Consistency

- Kept cage wireframe and inactive cage previews controlled by the `In Front`
  preference, so they can be naturally occluded by the controlled object.
- Kept interactive cage controls, including curve points and handles, FFD
  controls, and stage selectors, always visible and selectable above scene
  geometry.
- Applied the same front-most depth policy to the traditional angle, limits,
  bend-axis, and rotation controls.
- Enabled `In Front` by default for new installations.

# Simple Deform Helper 2.7.18

# Simple Deform Helper 2.7.17

## Interactive Performance

- Debounced chain-domain metadata reads and invalidate them only when chain
  metadata, gaps, root frames, or authored controller sizes change.
- Added an empty-selection fast path to the persistent selection watcher. It
  now returns without switching tools or scanning controllers while the user
  is simply moving the pointer over an empty viewport.
- Added chain interaction and idle selection performance probes covering
  Blender 5.0 and 5.2.

Benchmark reference (21x21 grid, six edits): 8-stage reconnect median is about
48 ms on Blender 5.0.1 and 53 ms on Blender 5.2.0 (roughly half of the
101/111 ms baseline); idle selection watching is about 0.0005 ms per tick with
zero reconciliation calls.

# Simple Deform Helper 2.7.16

## Interactive Chain Performance

- Skipped no-op parameter RNA writes and filtered non-motion Gizmo events so
  high-frequency trackpad/mouse samples do not repeatedly schedule the same
  chain reconnect.
- Cached immutable Geometry Nodes socket identifiers and verified deformation
  order links once per managed node group instead of scanning the interface and
  link collections on every controller sync.
- Reused the chain's controller map during a reconnect and removed the hot-path
  full-object snapshot used only as a restricted-data availability check.
- Scoped FFD and Curve `B` box-selection bindings to their active Workspace
  Tools, leaving Blender's native Select Box input untouched with no selection.
- Selection reconciliation now treats empty selection as authoritative, ignores
  stale edit flags without a live modal session, and retries coalesced message
  bus notifications.
- Full Curve Falloff also applies to modal point-radius/roll edits and merges
  native Bezier multi-selection with the controller selection.
- Empty-selection events now hand B/drag gestures back to Blender's native
  Select Box, while an explicitly chosen native transform tool remains active
  until the target or cage stage changes.

Benchmark reference (21x21 grid, six edits): 8-stage reconnect median dropped
from about 227/250 ms to 100/108 ms on Blender 5.0/5.2 respectively; forced
Geometry Nodes evaluation remained about 8-9 ms.

# Simple Deform Helper 2.7.15

## Deterministic FFD and Curve Selection Tools

- Reworked FFD and Curve Workspace Tool switching as an idempotent selection
  state: a selected controlled object follows its active FFD/Curve stage,
  while empty, unsupported, ordinary-object, Standard, and Shear states restore
  Blender's native tool.
- Tool switching now resolves a real 3D View context from app timers and
  verifies the resulting tool before treating the selection as synchronized.
- Activity changes that do not change the selected objects, including switching
  between FFD, Curve, and Standard stages, now update the tool immediately.
- Selection polling is persistent and its message-bus subscriptions are rebuilt
  after loading a `.blend`, preventing tool synchronization from silently
  stopping after a file change.
- Added an asynchronous Blender regression covering repeated selection cycles,
  active-but-unselected targets, ordinary objects, stage changes, and file load.

# Simple Deform Helper 2.7.14

## Full-Guide Falloff and Persistent Cross Sections

- Added a compact Full Curve Falloff toggle for guide-point Roll, Radius,
  Bevel, and Tension. It uses Blender's current falloff shape and automatically
  expands the influence to cover the complete guide, including multi-selection.
- Changed Equalize Cross Sections into a persistent state that immediately
  distributes existing sections and keeps them even after edits, insertion,
  or removal.
- FFD and Curve Workspace Tools now release blank-drag input when the scene has
  no selected object, restoring Blender's native box selection; selecting the
  controlled object reactivates the appropriate cage tool.
- Added Chinese, Japanese, Korean, and English coverage for the new controls.

# Simple Deform Helper 2.7.13

## Reliable Curve Box Selection

- Blank viewport presses in Curve Object Edit now enter box selection
  immediately, matching FFD instead of waiting in a non-drawing click state.
- Curve selection rectangles remain alive through intermediate mouse events
  and update for both regular and in-between mouse movement.
- Releasing a box drag outside the viewport, including over the N-panel, now
  completes the selection instead of leaving the modal stuck in Dragging.
- External Workspace Tool boxes and internal direct/B-key boxes now share the
  same press, move, release, selection, and double-click handling.

# Simple Deform Helper 2.7.12

## Curve Selection Clearing

- Clicking blank viewport space now clears the Curve point selection without
  leaving Curve Object Edit; double-clicking blank space still exits it.
- Clicking one point inside an existing multi-selection now collapses to that
  point when released without dragging.
- Dragging an already selected point keeps the complete multi-selection and
  moves the group after the pointer crosses the same threshold used by FFD.
- Shift-click deselection no longer starts an unintended transform on the
  remaining selected points.

# Simple Deform Helper 2.7.11

## Curve Selection and Falloff Feedback

- Added a scoped Curve Workspace Tool so point and handle box selection can
  start outside Curve Object Edit, matching the existing FFD workflow.
- Direct Curve control clicks and drags now enter the persistent editor while
  preserving multi-selection; blank external boxes leave the current object
  selection unchanged.
- Active Guide Point Bevel and Tension now edit every selected point, and use
  Blender's proportional falloff for nearby points when it is enabled.
- Curve Move, Rotate, Scale, Radius, and Twist now display the same orange
  proportional-influence circle used by FFD transforms.
- Added Chinese, Japanese, Korean, and English text for the Curve edit tool and
  multi-point profile controls.

# Simple Deform Helper 2.7.10

## Curve Proportional Editing

- Moved Active Guide Point controls above Cross Sections so the currently
  edited guide point is available before its downstream profile controls.
- Added one-click equal spacing for every Curve cross section while preserving
  each section's scale, offset, radius, twist, and animation data.
- Curve Object Edit now uses Blender's proportional-edit toggle, falloff type,
  and influence radius for guide-point Move, Rotate, Scale, Radius, and Twist.
- Radius and Twist fields for active guide points and cross sections now apply
  the same proportional falloff to neighboring controls.
- Added Chinese, Japanese, Korean, and English UI coverage for the new controls.

# Simple Deform Helper 2.7.9

## Cage Object Occlusion

- Cage previews, Curve controls, FFD controls, deformation handles, and stage
  pickers now respect scene depth by default, so the controlled object can
  occlude controls behind its surface.
- Added the existing In Front toggle to Cage Controls. Enabling it restores
  the previous always-visible overlay behavior for both previews and handles.
- Hidden inactive-stage pickers no longer accept background selection while
  object occlusion is active.

# Simple Deform Helper 2.7.8

## Correct Traditional Header Controls

- The stack-header axis button now opens the traditional Bend-axis direction
  Gizmo, matching the cage axis-switch control.
- The stack-header eye now shows or hides the bounds of other traditional
  deformation stages instead of toggling the deformed mesh wireframe.
- Restored the separate wireframe-preview and X/Y/Z axis-button settings to the
  expanded Viewport Display section.
- New traditional stages now start in neutral Bend mode on local +Y.

# Simple Deform Helper 2.7.7

## Unified Traditional Viewport Toggles

- Traditional Simple Deform now places its axis-switch and deformed-wireframe
  visibility buttons in the deformation-stack header, matching cage stages.
- The two controls use the same compact icons and toggle interaction as cage
  stages, without duplicating them in the expanded viewport-display section.
- Renamed the traditional axis control to `Show Axis Switch` so its tooltip is
  consistent with the equivalent cage control.

# Simple Deform Helper 2.7.6

## Traditional Viewport Controls

- Restored the compact traditional Simple Deform controls in the 3D View
  header: method, axis, strength, and the managed Origin rotation value.
- Kept the unified deformation stack as the only Tool-tab panel for traditional
  stages.
- Fixed the bend-direction rotation ring disappearing after a small drag.
  Managed Origin bounds now use its complete local coordinate frame, so
  arbitrary rotation angles remain valid instead of only 0/90-degree poses.
- Invalidated the traditional boundary cache around Origin rotation updates so
  the ring, limit handles, and preview follow the new frame immediately.
- Added Blender 5.0/5.2 regression coverage for arbitrary-angle bounds and
  real traditional Gizmo interaction.

# Simple Deform Helper 2.7.5

## Unified Traditional Deformation

- Traditional Simple Deform now starts in neutral Bend mode on local +Z.
- New traditional stages create a managed Origin that follows the lower limit,
  matching the assistant's cage workflow.
- Traditional stages expose method, axis, strength, limits, Origin behavior,
  display options, and animation controls in the unified deformation stack.
- Unified Insert Keys, Delete Keys, and Bake Mesh Animation support native
  Simple Deform stages as well as cage stages.
- Traditional controls no longer register in Blender's Tool tab or tool header.

## Runtime Lifecycle and Compatibility

- Deleting a controlled target now removes owned cage, FFD, Curve, Origin, and
  unused node-group helpers on the next safe runtime pass.
- Merge preview handlers are enabled only while a merge exists.
- Curve modal lookup uses the stable controller UUID instead of a mutable name.
- Lattice Origins stay detached to avoid Blender dependency cycles and follow
  target transforms through a safe deferred synchronization queue.
- Added Blender 5.0/5.2 coverage for defaults, mixed stack animation, helper
  cleanup, lazy handlers, UI registration, and translation contracts.

# Simple Deform Helper 2.7.4

## Unified Deformation Stack

- Native Simple Deform modifiers now appear alongside cage stages in their
  evaluated modifier order.
- Traditional and cage stages can be selected, renamed, reordered, disabled,
  removed, or cleared from the same compact stack.
- Lattice objects receive the same traditional-modifier stack management while
  continuing to show that cage deformation is unsupported.

# Simple Deform Helper 2.7.3

## Selected-Edge Workflow Removal

- Removed the From Selected Edges UI entry and its dedicated operator.
- Removed the edge-path extraction, simplification, centering, and endpoint
  alignment implementation that was used only by that workflow.
- Ordinary Curve cage creation, guide editing, presets, and deformation remain
  available and unchanged.

# Simple Deform Helper 2.7.2

## Extracted Guide Boundary Alignment

- Open mesh-edge guides now extend along their endpoint tangents until they
  reach the cage bottom and top. The selected interior path is not scaled.
- Endpoint continuation limits transverse slope and falls back to axial
  extension for degenerate tangents, preventing remote intersection points.
- Added an Align Guide Ends redo option for workflows that intentionally keep
  a selected path shorter than the controlled object.
- Added Blender 5.0/5.2 coverage for a connected surface edge selected only
  across the middle half of a full-height mesh. The test verifies exact cage
  boundary alignment, neutral binding, editable interior controls, and
  continuous geometry above and below the selected path.

# Simple Deform Helper 2.7.1

## Stable Surface-Edge Guides

- Mesh-edge Curve extraction now centers the selected path across the cage
  while preserving its complete shape and axial range. A surface edge can
  therefore drive the object without becoming a long off-center lever arm.
- Added a Center Extracted Guide redo option. Disable it only when the
  original edge position is intentionally used as a hinge or pivot.
- Extracted current/rest guides now use a deterministic local-Z up frame,
  reducing cross-section roll changes after small point edits.
- Added a connected wide-ribbon regression that extracts an outside mesh edge
  and verifies neutral binding, centered controls, stable frames, and
  continuous geometry after a small edit on Blender 5.0 and 5.2.

# Simple Deform Helper 2.7.0

## Live Curve Presets

- Curve presets now update immediately when the preset, amplitude, cycles,
  phase, or control count changes. The Curve panel no longer requires an
  Apply action.
- Continuous preset edits update existing Bezier controls in place whenever
  the point count is unchanged, reducing viewport churn while dragging a
  numeric control.
- Preset controls are locked when guide points use shape keys, drivers, NLA,
  or point animation so live previews cannot overwrite animated topology.

## Simplified Edge Guides

- Curve cages extracted from dense mesh-edge paths now simplify automatically
  to at most 12 controls while retaining endpoints and important turns.
- The redo panel can disable simplification or adjust its control budget and
  geometric tolerance for paths that need more or less detail.
- Open and closed dense-path regressions verify the control budget, endpoint
  preservation, and unchanged rest-bound geometry.

# Simple Deform Helper 2.6.2

## Extracted Curve Continuity

- Mesh-edge Curve extraction now creates continuous guide tangents instead of
  a hard frame break at every selected vertex. Small guide edits therefore no
  longer pull adjacent cross-sections through different rotation frames and
  make the controlled surface appear split.
- The smoothed guide still passes through every selected edge vertex, while
  the hidden rest guide keeps the object unchanged at bind time.
- Added a dense, finite-width ribbon regression so future tests measure
  transverse frame continuity rather than checking only centerline vertices.

# Simple Deform Helper 2.6.1

## Curve Panel Fix

- Fixed a Curve cage panel draw error that could occur when opening the N-panel
  after installing version 2.6.0.

# Simple Deform Helper 2.6.0

## Relative Edge Curve Binding

- Creating a Curve cage from a selected mesh-edge path now captures that path
  as a hidden rest guide. The source mesh therefore remains unchanged at the
  moment of extraction, while later edits to the visible guide deform it
  relative to the captured shape.
- Added clear binding status and Bind Current Guide / Rebind Curve actions to
  the Curve cage panel. Rebinding makes the edited guide the new zero-shape
  reference without discarding its editable control curve.
- Kept ordinary Curve cages and presets on their existing absolute-guide
  behavior, so the new rest binding only affects the edge-extraction workflow.
- If edge-based Curve stage creation fails after leaving Mesh Edit Mode, the
  source object is restored to Edit Mode before the operation reports failure.

# Simple Deform Helper 2.5.0

## Curve Cage Profiles and Creation

- Added non-destructive global radius and twist controls. Both compose with
  each guide point's native radius and roll instead of overwriting authored
  point animation.
- Extended cross-section stations with animatable radius and twist values, so
  the profile can vary continuously anywhere along the guide.
- Added Straight, Wave, Sine, and Helix guide presets with amplitude, cycles,
  phase, and editable point-count controls.
- Added direct Curve cage creation from one continuous mesh edge path or
  closed edge loop in Edit Mode, preserving the selected world-space path.
- Updated the packaged Geometry Nodes template and English, Simplified
  Chinese, Japanese, and Korean interface text for the new workflow.

# Simple Deform Helper 2.4.64

- Clarified the Curve cage viewport so one volumetric cage no longer reads as
  two nested cages: far-side structural lines now receive depth fading while
  remaining visible through the controlled object.
- Separated movable Curve effect boundaries from the blue structural cage.
  Inset bottom and top limits now draw as orange and yellow cap loops without
  duplicating longitudinal rails or over-drawing the default cage ends.

# Simple Deform Helper 2.4.63

- Separated the Curve cage's stable full-source mapping from its editable top
  and bottom effect range. Moving either boundary no longer re-parameterizes
  or compresses the geometry that remains inside the range.
- Limited mode now keeps excluded cross-sections intact and continues them
  rigidly along the nearest boundary tangent instead of collapsing them onto a
  single guide endpoint.
- Kept the complete cage preview aligned to the complete guide, added explicit
  range caps, and preserved Ctrl/Alt paired-boundary editing, animation,
  duplication, migration, and four-language feedback for the new range data.

# Simple Deform Helper 2.4.62

- Restored independent top and bottom effect boundaries in Curve Mode. The
  complete source still follows the complete guide by default, while inward
  boundaries now correctly drive Limited, Within Box, and Unlimited behavior.
- Kept the editable Bezier guide; mesh-to-curve conversion was unnecessary
  because the fault was in the source-range mapping rather than guide topology.

# Simple Deform Helper 2.4.61

- Curve Mode now maps the controlled object's complete longitudinal range to
  the complete guide, matching the cage after guide-driven fitting.

## Curve and Cage Relationship Modes

- Added Curve Mode, where the complete cage follows the full guide and guide
  edits drive cage length and placement without moving the authored path.
- Added Cage Mode, where guide endpoints stay inside the cage and single-end
  boundary edits no longer rescale the whole guide.
- Kept Limited, Within Box, and Unlimited as an independent Range Mode, with
  legacy length settings migrated to the matching relationship behavior.
- Added Simplified Chinese, Japanese, and Korean interface text and focused
  Blender 5.0/5.2 regression coverage for both relationship modes.

# Simple Deform Helper 2.4.59

## Curve Cage Interaction Fixes

- Completed the custom Gizmo event contract so a real click on a Curve guide
  point or Bezier handle enters the persistent Object Mode editor immediately.
- `Alt` now permanently separates the dragged Bezier handle from its mirrored
  partner; later ordinary drags preserve the authored asymmetric shape.
- Added real Blender window-event coverage for Curve Gizmo click activation in
  Blender 5.0 and 5.2.

# Simple Deform Helper 2.4.58

## Curve Cage Interaction

- Clicking a Curve guide point or Bezier handle now enters the persistent
  Object Mode editor immediately; double-clicking empty viewport space exits.
- Bezier handle drags are mirrored by default, with `Alt` available for
  independent one-sided adjustment.
- Moving one open Curve cage boundary now resizes the managed guide around the
  stationary opposite end instead of translating the whole cage and result.
- Closed Curve cages keep their linked top/bottom scale, offset, cross-section,
  and boundary controls synchronized across the seam.
- Added Simplified Chinese, Japanese, and Korean text for the new handle
  interaction.

# Simple Deform Helper 2.4.57

## Curve Cage Editing

- Added explicit Limited, Within Box, and Unlimited Curve modes. Open guides
  extend along endpoint tangents in Unlimited mode; closed guides repeat
  continuously around the loop without a frame twist at the seam.
- Added a persistent Object Mode editor for guide points and Bezier handles,
  including direct drag, Shift multi-select, box select, G/R/S transforms,
  animation keying, and transform cancel without leaving the editor.
- Added per-point Bevel and Tension controls, closed guides, and arc-length
  point equalization. Equalization is blocked when guide-point animation would
  make point-index remapping unsafe.
- Preserved Curve guides, cross sections, and animation through duplication,
  deletion, node-schema migration, and Blender 5.0/5.2 registration cycles.
- Updated the packaged Geometry Nodes template so first Curve cage creation
  uses the prebuilt graph without a Python cold rebuild.
- Completed English, Simplified Chinese, Japanese, and Korean UI and viewport
  header translations for the new workflow.

# Simple Deform Helper 2.4.56

## Curve Cage

- Added a dedicated Curve Cage that deforms geometry along an editable open
  Bezier guide using arc-length sampling and a stable minimum-twist frame.
- Added Preserve Length, Stretch to Path, and Fit Guide to Cage mappings;
  tangent extension, clamping, and cage-only boundary modes; plus optional
  volume preservation.
- Added animatable guide-point tilt and radius, and cross-section stations with
  independent U/W scale and offset controls.
- The viewport cage now follows the evaluated guide, roll, radius, and section
  profile. Curve stages inherit upstream geometry, duplicate independently,
  clean up their helper data, and can be baked to mesh shape-key animation.
- Added complete English, Simplified Chinese, Japanese, and Korean UI coverage
  and Curve Cage regressions for Blender 5.0 and 5.2.

# Simple Deform Helper 2.4.55

## Fixes

- Fixed adding an independent FFD cage after a Standard cage chain: the new
  FFD stage no longer inherits the active chain's Standard type.

# Simple Deform Helper 2.4.54

- Removed the first-cage startup stall by updating the packaged Geometry Nodes
  template to the current graph version instead of rebuilding it in Python.
- Reduced multi-cage viewport overhead with lazy inactive-stage controls,
  on-demand stage pickers, cached guide geometry, and merged preview batches.
  All visible cages remain selectable and directly editable.

# Simple Deform Helper 2.4.53

- Fixed direct clicks on inactive FFD points clearing the controlled-object
  selection and hiding every cage. Entering FFD edit now activates the clicked
  stage before the modal poll and repairs Blender's delayed Gizmo selection
  before the next event.

# Simple Deform Helper 2.4.52

- Fixed chained and stacked inactive FFD cages losing most or all of their
  viewport frame after switching stages. Inactive FFD stages now retain their
  complete lattice grid with a dimmed color distinct from the active cage.
- Kept the controlled object selected when Blender applies a late inactive-FFD
  picker result, preventing the entire cage stack from disappearing.

# Simple Deform Helper 2.4.51

- Fixed inactive FFD cage selection dropping the controlled object and hiding
  the cage stack. FFD editing now keeps the target active while controller
  objects remain selected for animation, and late Blender object-pick results
  are repaired after the FFD Workspace Tool is activated.

# Simple Deform Helper 2.4.50

- Replaced active-keyconfig and built-in Select Box keymap injection with a
  dedicated FFD Edit Workspace Tool registered through Blender's public tool
  API. Adding or selecting an FFD stage activates the scoped tool, so blank
  viewport drags remain available while native and user keymaps stay untouched.
- Kept `B` as an add-on-owned shortcut and added English, Chinese, Japanese,
  and Korean labels for the FFD Workspace Tool.

# Simple Deform Helper 2.4.49

- Directly dragging a rectangle from empty viewport space now uses the same
  active-keymap priority as the `B` shortcut, including Blender's Select Box
  toolbar-tool keymap. With an active FFD cage, either gesture selects visible
  FFD controls and enters the persistent editor; other objects continue to use
  Blender's native drag selection.

# Simple Deform Helper 2.4.48

- Fixed a naming collision between the temporary FFD box picker's selection-
  restore flag and cleanup method. Cancelling or exiting the pre-edit picker no
  longer raises a `TypeError`.

# Simple Deform Helper 2.4.47

- Added a reliable pre-edit FFD box-selection entry: press `B`, then drag a
  rectangle over visible FFD point, line, or face handles. The persistent FFD
  editor starts only after a handle is selected; empty rectangles and cancel
  gestures leave the normal viewport selection unchanged.
- Retained the direct mouse-drag entry as a secondary shortcut and added
  Chinese, Japanese, and Korean viewport-header translations for the new
  box-selection state.

# Simple Deform Helper 2.4.46

- Viewport box selection now works before FFD Edit Mode is entered. Drag a
  rectangle over visible FFD point, line, or face controllers to select them
  and enter the persistent editor in one action. A rectangle that hits no FFD
  controller leaves the editor closed and preserves the prior selection.

# Simple Deform Helper 2.4.45

- Fixed FFD edit mode closing after canceling a Move, Rotate, or Scale with
  `Esc` or right mouse. The cancel now restores the point transform and keeps
  the persistent FFD editor active; a subsequent fresh `Esc`/right-click exits
  it as intended.
- Added a regression for the `PRESS`/`RELEASE` sequence used by both cancel
  inputs, preserving the normal explicit editor-exit behavior.

# Simple Deform Helper 2.4.44

- Deferred clone-based cage Auto Sync and chain maintenance until Blender has
  completed its new-frame dependency-graph evaluation, preventing a native
  access violation after inserting cage keyframes with Auto Sync enabled.
- Runtime geometry-evaluator copies are now excluded from dependency-graph
  synchronization so a removed temporary object can never remain queued.
- Fit-generated dependency updates are suppressed for one event-loop pass,
  allowing Auto Sync to settle instead of continuously refitting itself.
- Added an animated ordinary-stack regression covering repeated cage keying,
  upstream Bend animation, deferred refits, and repeated frame changes.

# Simple Deform Helper 2.4.43

- Added mesh-animation baking for complete evaluated cage stacks. The result is
  an independent mesh driven by absolute shape keys with linear frame timing.
- Added controls for frame range, sample step, result name, and source-object
  visibility, with topology validation and four-language UI coverage.

# Simple Deform Helper 2.4.42

- Fixed direct duplication of cage-controlled objects when the sidebar first
  resolves the copy from Blender's read-only panel draw context.
- Copied cage stacks now defer ownership repair safely, then receive independent
  target UUIDs, node groups, controllers, and chain ownership.

# Simple Deform Helper 2.4.41

- Fixed the Stretch factor control in subdivided Bend + Stretch chains so a
  panel or Gizmo edit updates the model, every cage stage, and every Geometry
  Nodes input immediately.
- Global chain Stretch now uses one shared visible factor and bypasses chain
  reconnection while dragging, eliminating the main source of interaction lag.
- Added modal-drag and cancel regressions that verify live deformation, final
  cage/control alignment, shared values, and zero reconnect calls.

# Simple Deform Helper 2.4.40

- Fixed Standard chained cages whose layer order applies Stretch after Bend:
  active and inactive cage wires, stage pickers, parameter controls, end-shape
  controls, and boundary controls now display the same final global Stretch
  pass as the evaluated model.
- Added an exact three-stage Bend 15 degrees + Stretch 0.14 regression that
  compares cage sections and boundary controls against Geometry Nodes output.

# Simple Deform Helper 2.4.39

- Fixed cross-FFD edit switching by comparing Blender RNA datablocks through
  stable pointers, preventing a modal `NameError` when clicking another FFD.
- Added a real View3D modal regression for FFD-to-FFD switching and automatic
  exit when a different cage type is operated.
- Added a normalized-error gate for mixed Stretch subdivision diagnostics.

# Simple Deform Helper 2.4.38

- Fixed default 2x2x2 FFD subdivision by resampling every chain slice before
  any stage changes the source control-grid resolution.
- Stretch in mixed subdivided stacks now evaluates once over the original cage
  domain, reducing the previously visible Taper/Twist combination mismatch.
- FFD transforms now use a global axis on the first X/Y/Z press and cage-local
  space on a repeated press for Move, Rotate, and Scale.
- Active FFD editing can switch directly to controls on another visible FFD
  stage; selecting another stage from the panel cleanly ends the old modal.
- Multi-object deformation can now merge a selected collection recursively,
  skip unsupported objects, and derive low-topology warnings from merge sources.
- Added Chinese, Japanese, Korean, and English coverage for the new controls.

# Simple Deform Helper 2.4.37

- Pure Shear cage chains now preserve every stage's authored X/Z displacement
  instead of cancelling the deformation on downstream stages.
- Downstream Shear handles now follow the evaluated cage section and retain a
  stable drag basis while automatic chain reconnection updates controller
  frames, eliminating reversed motion and top-stage jumps.

# Simple Deform Helper 2.4.36

- Standard chained-cage gaps are now rigid, unowned intervals. They inherit
  the preceding cage's terminal position, orientation, and cross-section
  without accumulating Bend, Twist, Taper, Stretch, or Shear inside the gap.
- Reconnected downstream cages now retain the preceding terminal frame while
  being offset along its tangent, keeping cage previews aligned with geometry.

# Simple Deform Helper 2.4.35

- Direct Standard cage chains now preview synchronized shared-end scales as
  relative downstream profiles, preventing the incoming seam scale from being
  applied twice while retaining subdivided global-profile cages.
- Added +Y and +Z scaled-seam continuity coverage for bent cage previews.

# Simple Deform Helper 2.4.34

- Restored the Standard cage deformation-layer tree after the cage-creation
  button loop incorrectly leaked the FFD type into the active-stage UI branch.
- Restored the Standard Shear-layer add action and made the UI smoke test fail
  on interrupted panel draws instead of accepting a partial layout.

# Simple Deform Helper 2.4.33

- New Standard, Shear, FFD, and chained cages now persist the explicit +Z
  deformation axis by default. Existing cages retain their previous axis.

# Simple Deform Helper 2.4.32

- FFD cages now expose Limited, Within Box, Unlimited, and Chained outside
  behavior together with independent U, V, and W interpolation bases.
- Standard, Shear, and FFD cages now create and subdivide only into matching
  cage chains, preserving their authored range and FFD control shape.
- Standard cages can place Shear anywhere in their ordered deformation-layer
  stack; dedicated FFD cages now evaluate Curve and Surface targets.
- New cages default to the explicit +Y deformation axis instead of Auto.
- Rebuilt native FFD topology now follows edited resolution and interpolation
  reliably, including high-resolution and downstream chained FFD stages.

# Simple Deform Helper 2.4.31

- Restored chain Auto Reconnect as an independent, enabled-by-default chain
  behavior. The new Auto Sync control now belongs only to ordinary Standard,
  Shear, and FFD stack cages and refits them to changed upstream cage output.
- FFD point, line, and face transforms now honor Blender Object proportional
  editing, falloff modes, and mouse-wheel radius adjustment.
- An FFD cage can enter box selection directly from a viewport drag without
  first opening its persistent edit session from the panel.

# Simple Deform Helper 2.4.30

- Made FFD handle visibility a global preference (enabled by default), with
  U/V/W multi-axis symmetry buttons and depth-penetrating box selection.
- FFD edit sessions now close before a new cage is created, preventing stale
  modal input from competing with the new stack item.
- Added an optional chain Auto Sync control beside Align & Fit, with a
  preference for the default state of newly-created chains. Professional mode
  now keeps essential Cage Controls visible while hiding only advanced panels.

- FFD Line mode now creates one controller for every adjacent U, V, and W
  control-point segment instead of one controller for a complete grid line.
- Clicking, dragging, and box-selecting a line controller affects only its two
  endpoint control points; subdivided cage edges expose every segment.
- Hollow FFD hides a segment whenever either endpoint is an interior point,
  preventing partial line controls from floating inside the cage.

# Simple Deform Helper 2.4.28

- Added optional FFD symmetry editing with selectable cage-local U, V, or W
  center planes.
- Point, line, face, box, and Shift-toggle selections now include their
  visible mirrored control points while respecting Hollow FFD.
- Move, rotate, and scale edits reflect the active side's local displacement
  onto its counterpart instead of translating both sides in one direction.
- Duplicated FFD cages retain their symmetry switch and selected axis.
- Added Chinese, Japanese, and Korean labels and tooltips for FFD symmetry.

# Simple Deform Helper 2.4.27

- Dragging an FFD point, line, or face outside FFD Edit Mode now enters the
  persistent editor and starts moving from the original mouse-down position.
- Directly dragging any member of an existing FFD multi-selection now moves
  the complete selection. A stationary click still selects only the clicked
  point, line, or face.

# Simple Deform Helper 2.4.26

- FFD edit mode now suppresses the stale pre-edit Gizmo selection buffer as
  well as the normal Gizmo hit target. Point, line, and face clicks are owned
  exclusively by the persistent FFD editor from the first click, preventing a
  direct control click from ending the session.

# Simple Deform Helper 2.4.25

- FFD point, line, and face clicks now schedule a post-pick selection repair,
  keeping both the controlled object and its controller selected after Blender
  finishes its own Gizmo selection pass.
- FFD editing no longer appears to close when a control is clicked without a
  later modal mouse event to trigger the normal selection watcher.
- While FFD editing is active, the persistent editor is now the sole owner of
  point, line, and face clicks. The visible controllers no longer compete with
  it as independent Blender Gizmos.
- Non-FFD cage-handle hit testing inside FFD edit mode now uses viewport-local
  mouse coordinates, matching Blender's projected Gizmo coordinates.

# Simple Deform Helper 2.4.24

- FFD box selection now hits the visible point, line, and face controller
  geometry instead of expanding whichever lattice points happen to lie inside
  the rectangle.
- Mixed Point, Line, and Face display remains supported. Box selection follows
  the same Point, then Line, then Face hit priority as direct clicks and falls
  through when the higher-priority type has no visible hit.
- Completing a box drag now clears the blank-click exit history, so an
  immediate second box refreshes the selection instead of closing FFD edit
  mode. Shift-add and Ctrl-subtract use the same repeatable selection path.

# Simple Deform Helper 2.4.23

- FFD edit sessions now retain their bound cage stage through Blender's
  transient object-selection changes, so clicking a point, line, or face no
  longer closes the FFD editor or hides its handles.
- FFD controller clicks restore the target/controller selection pair used by
  the Timeline before the event returns to Blender.
- Box selection now uses one deterministic controller mode when Point, Line,
  and Face handles are shown together; Point mode no longer expands a small
  box into the complete lattice.

# Simple Deform Helper 2.4.22

- FFD point, line, and face mode buttons now show both icons and translated labels.
- Point, Line, and Face now switch exclusively on a normal click; Shift-click
  enables or disables multiple controller types without allowing an empty mode.
- A normal FFD controller click now replaces the current selection; Shift-click continues to add or remove controller groups.
- FFD box-selection draw handlers are now removed during extension cleanup and
  ignore stale modal instances, preventing repeated `StructRNA ... has been
  removed` errors after reload or modal exit.
- FFD edit mode now passes through Blender's internal Tweak events without
  reading their unavailable numeric `Event.type` enum, removing the warning
  spam seen while dragging an FFD controller in Blender 5.2.
- Disabled Blender's optional modal-draw pass for FFD handles. Their normal
  viewport draw and custom drag behavior remain active, while Blender no
  longer dispatches the unsupported Tweak event to all eight handles.
- Dedicated FFD point dragging now runs through the persistent FFD edit modal
  instead of the per-handle Gizmo modal, eliminating the Blender 5.2 Tweak
  event warning at its source while preserving click, Shift-select, and drag.
- FFD point clicks no longer pass through to the default viewport, preventing
  a click on a point from immediately closing FFD edit mode.

## Evaluated cage creation

- New cages now fit to evaluated upstream geometry vertices rather than the
  potentially stale object bound-box cache. Adding a Standard cage after a
  Shear, FFD, or other enabled cage type now inherits the visible result.

# Simple Deform Helper 2.4.14

## FFD controller display

- Replaced the FFD line controller arrow with a thin single-line handle.
  Visual line width is constant across every U, V, and W controller, while
  its length remains a percentage of the evaluated control line.
- Added Preferences for FFD line length, FFD line width, and FFD face size.
  Face handles now default to a smaller 35% coverage for easier inspection.

# Simple Deform Helper 2.4.13

## FFD multi-selection controllers

- Point, Line, and Face selection modes are now compact icon toggles and can
  be enabled together, so all selected controller types remain visible.
- Line controllers follow the evaluated FFD polyline midpoint and local
  tangent, keeping their position and orientation aligned after deformation.

# Simple Deform Helper 2.4.12

## FFD line and face controllers

- Point mode keeps individual point handles; Line mode exposes one draggable
  controller for every U, V, and W control line; Face mode exposes one
  controller for every UV, UW, and VW grid face.
- The line and face handles select and transform their complete point groups,
  including click, box selection, and hollow-FFD visibility filtering.
- New cage creation synchronizes all upstream cage controllers before fitting,
  so a new cage inherits the currently evaluated deformation rather than the
  original object bounds.

# Simple Deform Helper 2.4.11

## FFD selection workflow

- Added Point, Line, and Face selection modes for dedicated FFD cages.
- Line selection follows the cage deformation axis; Face selection selects a
  complete cross-section. Box selection and viewport transforms use the same
  selection expansion.
- Localized FFD modal status text and point labels for Chinese, Japanese,
  Korean, and English interfaces.

- Restored target-to-cage selection for legacy controller Empties such as
  `Cage Deform Controller` when older files are missing ownership markers.
  Matching requires the stage parent/name or modifier UUID, then repairs the
  current controller metadata so Timeline selection, active-stage switching,
  animation, and cleanup use the same controller.
- Added active/selected-layer callbacks plus a low-frequency selection watcher
  so direct viewport and Outliner selection also add the controller Empty;
  panel operators are no longer required to expose the controller's keyframes.
- Fixed an FFD edit-mode NameError when the modal checks whether the mouse is
  over another cage handle. FFD point movement now uses the current active
  deformation-layer resolver.

# Simple Deform Helper 2.4.6

- Added complete Simplified Chinese, Japanese, and Korean translations for
  recently introduced cage, FFD, layer-order, batch-edit, and viewport-handle
  tooltips. Runtime tests now verify Blender tooltip translation in all four
  supported interface locales.
- Fixed cage-preview discontinuities after subdividing a cage with asymmetric
  end scaling or offsets. Geometry evaluation keeps relative shared-end scale,
  while visible cages and Gizmos preserve each segment's authored end profile.

# Simple Deform Helper 2.4.5

- Increased the compact inactive-cage switching handle from 18% to 30% of its
  cage size, including the matching mouse hit area.

# Simple Deform Helper 2.4.4

- Restored compact inactive-cage switching handles without reintroducing the
  earlier deformation-alignment offset. Both drawing and mouse hit testing now
  use the same miniature cage centered on the evaluated cage midpoint.

# Simple Deform Helper 2.4.3

- Boundary handles and their connector lines now follow each cage's evaluated
  end position and tangent after Bend or combined deformation.
- Disabled Blender's automatic draw scaling for inactive-stage picker cages,
  keeping their visible and selectable geometry aligned with deformed cages.
- Restored per-layer disclosure controls, replaced the old global collapse
  toggle with a conditional Expand All command, and moved Remove Cage Stack to
  a compact trash button in the stack header.

# Simple Deform Helper 2.4.2

- Fixed repeated viewport errors after subdividing a cage into a chain by
  declaring the inactive-stage picker's custom shape in its Blender Gizmo
  slots.
- Extended the controlled UI smoke test to subdivide a cage into three stages
  and exercise the inactive-stage picker group during real viewport redraws.

# Simple Deform Helper 2.4.1

- Replaced two unavailable animation-button icons with Blender 5.0/5.2
  compatible keyframe icons so the Cage Deform N-panel draws normally.
- Added a runtime contract that rejects unavailable literal UI icons before a
  release package is built.

# Simple Deform Helper 2.4.0

- Dedicated **FFD Cage** now uses a native multi-point lattice with U/W
  resolutions from 2-6 and V resolution from 2-16 (up to 6x16x6 points).
  The compact panel provides point selection actions, and selected points can
  be moved together from the viewport.
- The native lattice is hidden and owned by its cage stage, follows cage
  transforms, survives save/reopen, and is removed with the stage.
- Replaced the generic Shear control with an evaluated end-face grip: the
  center drags freely in the cage plane and the X/Z arms constrain directly.
- Bundled the validated Geometry Nodes template and retained the Python graph
  builder as a fallback. In the reference Blender 5.0 benchmark, first-cage
  creation dropped from about 2.84 seconds to 0.027 seconds.
- Raised the extension version while keeping the stable ID
  `simple_deform_helper`; Blender 5.0.0+ is the supported range.

# Simple Deform Helper 2.3.0

- Raised the supported minimum to Blender 5.0 to match the Geometry Nodes
  interface used by the managed cage graph.
- Added dedicated **Shear Cage** and **FFD Cage** entry points. Standard Type
  cages keep the ordered Bend, Twist, Taper, and Stretch stack. Dedicated
  cages intentionally remain single-operation and cannot be chained or
  subdivided.
- Preserved interpolated end profiles on every subdivided chain stage while
  evaluating a non-identity source profile once in the root frame.
- Completed the English, Simplified Chinese, Japanese, and Korean release
  documentation and aligned CI, package metadata, and issue templates on 5.0+.

# Simple Deform Helper 2.2.0

- Added cage keyframe controls for deformation parameters, independent end
  profiles, Shear, 2x2x2 FFD corners, cage size, location, and rotation.
- Fixed FFD Geometry Nodes scale weighting and prevented animated cage size from
  being overwritten by the controller's derived Empty scale.
- Kept managed Empty objects hidden during normal object editing while retaining
  visible custom cages, inactive-stage controls, and stage switching. Native
  Move/Rotate/Scale commands still reveal only the controller being edited.
- Clarified end-shape shortcuts as screen-space X/Y controls and refreshed the
  Chinese, English, Japanese, and Korean interface catalogs.

# Simple Deform Helper 2.1.17

- Fixed moved Bend and Stretch handles being selectable only at their old
  positions. Draw and selection passes now share the prepared gizmo matrix,
  even when Blender supplies different viewport contexts.
- Moved the Bend angle and Stretch handles away from the Twist ring when the
  corresponding operations are enabled. Bend uses the left side and Stretch
  uses the right side so all three controls remain independently selectable.
- Enlarged the Bend fine-direction ring for easier viewport selection.

- Boundary handles now support `Ctrl` to translate both ends and `Alt` to
  move the ends in opposite directions, including constrained chain gaps.
- Twist and fine Bend Direction controls use the evaluated cage section frame,
  so their size and orientation follow a preceding Bend operation.
- Removed the pre-deform subdivision button; chained subdivision now warns
  when the source origin is not Bottom.
- Legacy Simple Deform starts at zero strength for merged targets and refreshes
  the optional wireframe preview immediately.


## Chained subdivision fidelity

- Preserved mixed deformation stacks when subdividing a cage, including
  operations authored before Bend such as Twist, Taper, and Stretch.
- Replaced the previous vertex-residual experiment with an analytic full-cage
  baseline plus editable per-stage parameter deltas.
- Kept chained gaps on the authored deformation profile and corrected
  Symmetric segment weighting, including even segment counts.
- Reduced tested pre-Bend mixed-stack subdivision drift from object-scale
  errors to approximately `0.00008` across Bottom, Top, Center, and Symmetric
  origins.

# Simple Deform Helper 2.1.10

## Chained subdivision and multi-deform preservation

- Non-Bend stacks now distribute Twist, Taper, and Stretch using each
  physical cage interval, preserving the authored profile across Bottom, Top,
  Center, and Symmetric origins.
- Stretch uses multiplicative per-stage factors and constant chained volume
  compensation, avoiding cumulative seam scaling when several deformation
  layers are enabled together.
- Subdivision protects mixed stacks that include Bend by default because the
  operations are order-dependent. An explicit approximate-mode option remains
  available for users who accept a non-identical result.
- Added a diagnostic matrix covering single, pairwise, and four-layer stacks
  across origins and chain counts, plus regression coverage for authored gaps.

## Fixed

- Moving the first chained cage's lower boundary inward now carries exposed
  geometry from the deformed lower section instead of restoring the source
  mesh below the cage.
- Root cages continue rigidly from both outer boundaries while downstream
  cages still preserve their incoming prefix and authored gaps.
- Geometry Nodes and the Python viewport/reference evaluator now share the
  same lower-boundary continuation rules.
- Managed node groups automatically rebuild to graph version 21.

## Chained subdivision

- Subdividing a single cage now preserves the initial Bend result for Bottom,
  Top, Center, and Symmetric origins without changing the authored range.
- Top and Center stages retain their origin reference through a persisted root
  output frame; Symmetric stages are factored around the original global center
  instead of mirroring every short segment independently.
- Root output correction is applied only when non-identity, so ordinary chains
  keep their previous evaluation precision.
- Mixed stacks made from Twist, Taper, and Stretch remain editable and are
  distributed in the authored order. Stacks that include Bend are protected
  by default because their operations do not commute; an explicit option is
  required to request an approximate split.

## 2.1.8

## 2.1.7

### Fixed

- Chained cages now support Bottom, Top, Center, Symmetric, and mixed Origin
  modes without position or cross-section breaks between stages.
- Added full-affine seam normalization for combined Bend and Twist stages,
  retaining upstream scale and shear instead of reducing the boundary to an
  Empty rotation.
- Preserved stable source-domain ownership across non-zero chain gaps, so
  later cages affect only their authored source interval.
- Cage wires, inactive cage previews, Bend Trend guides, and parameter handles
  now use the same physical output frame as Geometry Nodes.
- Managed node groups automatically rebuild to graph version 19 while keeping
  saved stage parameters and chain metadata.
- Cached unchanged chain frames to keep repeated viewport redraws responsive.

## 2.1.6

### Fixed

- Fixed chained Geometry Nodes ownership incorrectly reversing for Top Origin,
  which left most geometry outside the first cage unchanged like Within Box.
- Chain order now always propagates Bottom to Top while Origin controls only
  each stage's local deformation reference.
- Rebuilt managed node groups at version 15 and added a dense 37-ring geometry
  regression for all four Origin modes.
- Added a non-blocking V2 panel warning for sparse mesh topology, with an
  optional non-destructive Simple subdivision before the active cage stage.

## Chained cage Origin modes

- Chained cages now support Bottom, Top, Center, and Symmetric Origin modes.
- Origin is preserved during chain creation, synchronization, and subdivision.
- Geometry Nodes and the Python reference evaluator use the same Origin semantics.
- Existing chain connection, gap, automatic reconnect, and shared-seam scale behavior remains unchanged.
- Added localized Origin labels and descriptions for Simplified Chinese, Japanese, and Korean.


- Corrected the bend strength and Alt-direction drag sign so moving the handle right increases the corresponding value consistently.

- Preserve each source object's active/render UV layout when creating a multi-object deform merge, and restore it on release.
- Source-edit sessions now switch source with a single click; double-clicking blank space, `Esc`, or right-click returns to the merge.
- Bend and twist handles follow the cage's local frame more closely; twist rings are larger and parallel to cage end faces.

## Multi-object final-state editing

- Added a compact, scrollable source list for live multi-object deformation.
- Source editing now shows a transient, non-selectable preview of the source
  after the merged object's complete modifier stack, including cage stages.
- Added a preference to show or hide that final-state preview (enabled by
  default), with immediate refresh when changed.
- Added **Add Cage to Final Source** so a cage can be fitted after the current
  merged stack while affecting only the selected source index.
- Source picking is a modal session: double-click another merged part to
  switch, double-click empty space to return, or press `Esc`/right mouse to
  exit. Normal viewport and sidebar events pass through during the session.

## Fixed

- Restored the extension-list display name to **Simple Deform Helper** while retaining the existing `simple_deform_helper` extension ID.
- Documented the one-time removal of the old **Blender Extensions** repository copy before upgrading the existing **User Default / Simple Deform Helper V2 2.1.0** test installation.
- Detects a second enabled installation from another Blender extension repository and reports the conflicting module clearly.
- Registration now rolls back completed modules when a later module fails, preventing leftover Preferences classes and menu callbacks.
- Preference-dependent polls safely stop drawing while an extension registration is incomplete.
- Translation unregister now removes only catalogs owned by the current module instance.

## 2.1.0

## Highlights

- Added a live **Multi-Object Deform** workflow at the top of the N-panel.
- Selected Mesh, Curve, Surface, Text, Metaball, Curves, and Point Cloud objects can be consolidated into one Geometry Nodes deformation target; non-mesh sources are converted to meshes.
- Each source remains independently editable, and source modifier changes update the merged result in real time.
- Double-clicking a visible part of the final merged geometry selects its source, including after cage deformation, through a persistent face-domain source identifier.
- Source objects switch to an in-front wire display while editing and are hidden again when returning to the merged object.
- Added an undoable unmerge action that restores the sources' original viewport and render visibility.
- Added Simplified Chinese, Japanese, Korean, and English UI text for the complete merge workflow.

## Validation

- Blender 4.2 LTS and Blender 5.2 headless merge, conversion, live modifier, source identity, cage compatibility, visibility round-trip, and registration lifecycle regressions.
- Python compilation, translation contracts, existing cage/chain regressions, extension validation, and built-archive verification.

## 2.0.0

## Highlights

- Renamed the product presentation to **Simple Deform Helper V2** with the Chinese title **世界领先的简易变形器 V2**.
- One cage can combine Bend, Twist, Taper, and Stretch through an ordered deformation-layer list.
- Added chained-cage workflows with segment subdivision, seam reconnection, gaps, batch editing, and optional shared seam-end scaling.
- Added independent top/bottom length, scale, and offset controls with object-bound limits.
- Added six-face Bend Trend selection, shape-specific controllers, hover tooltips, and a dedicated Simple Deformer V2 N-panel.
- Added separate English, Simplified Chinese, Japanese, and Korean workflow overview and comparison SVGs under `docs/`, with each README selecting its matching language asset.
- Fixed copied-target ownership so selecting the source does not detach its working cage stack before the copy is initialized.
- Fixed animated independent cage parameters being overwritten by stale Geometry Nodes inputs during frame and render synchronization.
- Release metadata, documentation, and install archive are aligned on version `2.0.0`.

## Validation

- Python bytecode compilation, translated-report contracts, and extension manifest validation.
- Blender headless register/unregister, native multi-stage, cage, multi-layer, chained-cage, subdivision, batch-edit, animation, and installed-archive lifecycle regressions.
- Runtime translation checks for Simplified Chinese, Japanese, Korean, and English, plus XML and README-reference checks for all eight language-specific SVGs.

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
