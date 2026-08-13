<div align="center">

# Simple Deform Helper V2

### Easy to Deform, Easy to Animate

**The first cage builds in about 0.04 seconds; one Insert Keys records
dozens of animation channels.**

[![Download 2.7.48](https://img.shields.io/badge/Download-2.7.48-2ea44f?style=for-the-badge)](https://github.com/AIGODLIKE/simple_deform_helper/releases)
[![Blender 5.0+](https://img.shields.io/badge/Blender-5.0%2B-F5792A?style=for-the-badge&logo=blender&logoColor=white)](https://www.blender.org/download/)
[![Validation](https://img.shields.io/github/actions/workflow/status/AIGODLIKE/simple_deform_helper/validate.yml?branch=master&style=for-the-badge&label=validation)](https://github.com/AIGODLIKE/simple_deform_helper/actions/workflows/validate.yml)

[简体中文](README.zh_HANS.md) · [日本語](README.ja_JP.md) · [한국어](README.ko_KR.md) · [Releases](https://github.com/AIGODLIKE/simple_deform_helper/releases) · [Report a bug](https://github.com/AIGODLIKE/simple_deform_helper/issues/new?template=bug_report.yml)

</div>

<!-- Suggested here: a 3-5 second looping demo (dragging the Bend handle / two keyframes playing back / a chained tail swinging). A moving first screen sells better than any text. -->

Anyone who has used the native Simple Deform modifier knows the routine:
guess the axis, build an empty and move it around just to control the origin,
then key modifier properties one at a time to animate. This extension folds
all of that into a visible deformation cage. The deformation happens where
the cage sits, every parameter has a handle that responds the moment you drag
it, and when it is time to animate, one button records the entire current
state.

![Simple Deform Helper V2 workflow: select, fit, layer, and chain](docs/workflow_overview.en.svg)

Take "make a tail swing" as an example:

| | The usual way | With this extension |
|---|---|---|
| Setup | Build an armature and paint weights, or set up a lattice plus its modifier | Select the tail, click **Add Standard Chain** |
| Posing | Rotate bones one by one | Drag the Bend handle |
| Keying | Insert keyframes property by property | Click **Insert Keys** once |
| Handoff | The next person needs the same rig or add-on setup | The cage is a plain Geometry Nodes modifier; the file plays without the extension |

## Why it saves you time

- Every deformation parameter has its own viewport handle. Bend, Twist,
  Taper, Stretch, Shear, FFD points, and curve guides each get their own set
  in a distinct color, with names on hover. You never dig through the
  modifier panel to change a value.
- **Insert Keys** records the whole state of the active cage on the current
  frame: layer strengths, end profiles, FFD point offsets and influence,
  curve guides, cage size, and the controller transform. Dozens of channels,
  one button. **Delete Keys** removes exactly those channels and leaves the
  rest of your action alone.
- When a shot is approved, **Bake Mesh Animation** turns the deformation into
  an independent mesh with absolute shape keys. Export it or send it to a
  render farm; nobody downstream needs the extension.
- Cages are plain Geometry Nodes modifiers. They stay visible in the stack,
  reorder like any other modifier, and keep evaluating with the extension
  disabled.
- Each handle drag is one undo step, and a motionless click records nothing.
  Files with animated cages play right after opening.
- The first cage builds in about 0.04 seconds, and an 8-segment chain
  reconnects in roughly 50 milliseconds during a drag, so posing never
  stutters.

![Workflow comparison with Maya, 3ds Max, MODO, and Cinema 4D](docs/simple_deform_helper_v2_comparison.en.svg)

The comparison is about how much of this control sits in one Blender
workflow, not about whether another application can reproduce an individual
result. Product names are used only to identify the compared workflows.

## Your first deform in 60 seconds

1. In **Object Mode**, select a Mesh, Curve, Surface, or Text object.
2. Press `N`, open the **Simple Deformer V2** tab, and click
   **Add Standard Cage**.
3. Under **Deformation Layers**, keep **Bend** selected and drag the orange
   Bend handle in the viewport. Hold `Shift` for precision, `Ctrl` for
   snapping.
4. Wrong direction? Pick **Auto** or an explicit
   `X+ / X- / Y+ / Y- / Z+ / Z-` axis and click **Align & Fit**, or enable
   **Bend Trend** and click a red or green arrow on any face to choose where
   the bend goes.
5. Click **Return to Object** when you are done.

If the bend looks faceted, add geometry along the deform axis before the
cage stage. The panel warns about low topology but never adds subdivisions
behind your back.

## Thirty more seconds to make it move

1. On your start frame, pose the handles and click **Insert Keys**.
2. Move a few frames ahead, pose again, click again.
3. Press play. Cage parameters interpolate like any other Blender animation;
   ease and loop them in the Graph Editor as usual.

Standard, chained, Shear, FFD, and Curve cages, plus legacy Simple Deform
modifiers, all key through the same buttons.

Once the shot is locked, click **Bake Mesh Animation**, choose the frame
range, sample step, and name, and you get a clean shape-key mesh. The source
object can hide itself after the bake.

## Pick a cage for the shot

| You are animating | Start with | What you get |
|---|---|---|
| One local bend/twist/taper/stretch, or several stacked | **Add Standard Cage** | One cage with ordered, reorderable **Bend / Twist / Taper / Stretch** layers. |
| A tail, tentacle, cable, antenna, or spine | **Add Standard Chain** | 2–8 connected segments with automatic downstream reconnection and synced seams. |
| Motion along a drawable path, like snakes, vines, or banners | **Add Curve Cage** | An editable Bezier guide with live **Straight / Wave / Sine / Helix** presets and animatable cross-sections. |
| Soft squash, bulges, dents, cartoon smears | **Add FFD Cage** | A lattice cage from `2x2x2` up to `6x6x6` points with per-point influence, symmetry editing, and a foldover guard. |
| A planar slide, like an italic lean | **Add Shear Cage** | A dedicated cyan end-plane handle for free sliding in the plane. |
| An existing file that already uses Simple Deform | **Add Simple Deform (Legacy)** | Blender's native modifier plus stage-aware gizmos, limits, Origin control, and the same key/bake buttons. |
| A Lattice object | **Add Simple Deform (Legacy)** | Native modifier support only; cage deformation is intentionally unavailable for Lattice. |

Shear and FFD have chain buttons too (**Add Shear Chain**,
**Add FFD Chain**); Curve cages are single-stage by design.

With several objects selected, an Add Cage click builds one live merge and
deforms the combined result; `Ctrl`-click gives each selected object its own
cage instead.

## The animation toolbox

| Tool | What it does |
|---|---|
| **Insert Keys** | Records the active stage's complete deformation state on the current frame: layer strengths and direction, Shear factors, every FFD point offset and influence, Curve guide points plus global radius/twist and range, end scale/offset, cage size, stage visibility, and controller location/rotation. |
| **Delete Keys** | Removes only those channels on the current frame; the rest of the action is untouched. |
| **Bake Mesh Animation** | Samples the evaluated result over a frame range (start, end, and step are configurable) into a new independent mesh with absolute shape keys, optionally hiding the source object. |
| **Stage visibility keys** | `stage_enabled` is an animatable channel, so a cage can switch on mid-shot. |
| **Undo boundaries** | Each handle drag, layer edit, and traditional gizmo interaction is one undo step; a cancelled drag restores the previous state. |
| **File-load recovery** | Files with animated cages resynchronize automatically on open, including after Blender started on an empty scene. |

Everything Insert Keys writes is a plain F-Curve in the
**Simple Deform Helper** channel group. Edit it in the Graph Editor, Dope
Sheet, or NLA, or put drivers on it, like any hand-keyed animation.

## Working with the cages

### Standard cage layers

A Standard cage evaluates its enabled layers from top to bottom, so order
changes the result:

```text
Object input -> Bend -> Twist -> Taper -> Stretch -> independent end profile -> output
```

- **Add Deformation** appends a layer; the arrows reorder it; the eye mutes
  it while keeping its value; `X` removes it; **Expand All** opens every
  layer for side-by-side tuning.
- Selecting a layer shows its matching viewport handle.
- Useful orders: Bend before Twist for a twisted pipe, Taper before Bend for
  horns and nozzles, Stretch before Bend for elastic motion. Muting a layer
  is the fastest way to compare two versions.
- **Independent ends**: top and bottom length, X/Z scale, and X/Z offset are
  all separate, with no forced center symmetry. **Reset Independent Ends**
  restores the fitted cross-section.
- **Spatial mode** controls what happens outside the cage: **Limited**
  (continue from the cage ends), **Within Box** (inside only), **Unlimited**
  (continue everywhere), **Chained** (keep the incoming prefix stable).
- **Origin** picks where the deformation starts: **Bottom**, **Center**,
  **Symmetric**, or **Top**.
- The compact panel covers daily work. The wrench icon in the panel header
  enables **Professional Mode**, which adds the deform axis, independent
  ends, and numeric controls.

### Chained cages

- Create 2–8 segments at once, **Chained** (continuous) or **Independent**
  (each in its own box), with optional gaps.
- **Auto Reconnect** propagates upstream changes downstream.
  **Sync Shared End Scale** scales both sides of a seam together so it never
  splits, while the two outer chain ends stay free.
- **Subdivide to Chained Cages** splits one authored Standard cage into a
  chain without changing its total range; Bend and Twist values are
  distributed across the segments.
- **Batch Edit** adjusts the whole chain (or start-to-active,
  active-to-end) in one live-preview dialog: end scale, end offset, gaps,
  one deformation parameter, or stage visibility. Cancel restores
  everything.
- Dragging the modifier stack around does not scramble segment order, and
  creating more than three stages shows a viewport-performance note without
  blocking you.

### Curve cages

- The guide is a real Bezier curve edited directly in the viewport: click
  and box-select points; Move, Rotate, Scale, Radius, and Twist all respect
  Blender's proportional editing. **Full Curve Falloff** spreads one edit
  across the entire guide.
- **Live presets** (Straight, Wave, Sine, Helix) update instantly while you
  drag amplitude, cycles, phase, or point count, and the result stays a
  fully editable curve.
- **Cross-sections** add animatable radius and twist stations anywhere along
  the guide; **Even Cross Sections** keeps them evenly spaced. Global radius
  and global twist stack on top without overwriting per-point values.
- Guide deformation is computed against the rest shape captured at binding.
  To make the current shape the new rest state, click **Rebind Curve**.

### FFD cages

- Resolution is `2–6` points per axis (up to `6x6x6`), changeable at any
  time without losing authored offsets.
- Point, line, and face selection modes, box select, All/None/Invert, and
  group dragging; **Hollow FFD** hides and excludes interior points.
- **Symmetry** mirrors edits across the cage-local U/V/W center planes.
- Per-point **Influence** (0–1) sets how strongly each control point moves
  the mesh. Influence itself can be keyed, so the affected region can change
  over time.
- The optional **Prevent Foldover** mode under **FFD Safety** clamps edits
  to the last non-inverted lattice state, so fast posing cannot turn the
  mesh inside out.
- **Native Lattice Edit** opens Blender's own lattice Edit Mode on a proxy
  for anyone who prefers the native tools; edits and selection synchronize
  back to the cage.

### Merge several objects, deform them once

- **Merge Selected for Deform** (or **Merge Collection for Deform**) builds
  a live merged object from Mesh, Curve, Surface, Text, Metaball, Curves,
  and Point Cloud sources. The originals stay linked and keep updating the
  merge.
- Double-click any part of the merged result to edit that source object. A
  blue preview shows the source after the full modifier stack while you
  work.
- **Add Cage to Final Source** fits a source-masked cage after the merge's
  current stack, deforming one character part without touching the rest.
- **Return to Merged Object** ends the session; unlinking removes the merge
  and restores the sources.

## Viewport handle reference

| Handle | Meaning | Interaction |
|---|---|---|
| Orange double arrow | Bend angle | Drag; `Shift` precision; `Ctrl` snap. |
| Large orange ring | Bend direction | Enable **Show Twist**, then drag. |
| Large purple arc | Twist angle | Drag around its center; continues cleanly across the seam. |
| Amber handle | Taper factor | Drag; `Shift` precision; `Ctrl` snap. |
| Green handle | Stretch factor | Drag; `Shift` precision; `Ctrl` snap. |
| Yellow top / amber bottom | Move one cage boundary | Drag along the cage axis; respects **Limit to Object Bounds**. |
| Cyan crown / green tray | Shape one end only | Drag to scale; `Alt` screen X; `Shift` screen Y; `Alt+Shift` free; `Ctrl` snap. |
| Cyan four-way plane | Shear end-plane slide | Drag in the end plane; `Alt` locks cage X; `Shift` locks cage Z; `Ctrl` snap. |
| Pink/cyan lattice points | FFD control points | Drag selected groups; box select or All/None/Invert. |
| White curve points and handles | Curve guide | Click, box-select, drag; proportional editing applies. |
| Red / green arrows | Bend trend on each face | Click to choose; hold `Ctrl` to keep all choices visible. |
| RGB diamond / ring | Positive / negative X, Y, Z axis | Diamond is positive, ring is negative. |

Hover any handle to see its name. Helper objects live in the
**Simple Deform Controls** collection and appear only when needed. Whether
cage wireframes draw through the object is controlled by the **In Front**
toggle.

## Install

1. Download `simple_deform_helper-2.7.48.zip` from the
   [Releases page](https://github.com/AIGODLIKE/simple_deform_helper/releases).
   Do not use GitHub's automatically generated Source code ZIP.
2. In Blender, open **Edit > Preferences > Get Extensions**, choose
   **Install from Disk**, and select the ZIP.
3. Enable **Simple Deform Helper** if Blender does not enable it
   automatically.
4. In the 3D View, press `N` and open the **Simple Deformer V2** tab.

Keep a single installed copy. If another repository still carries the same
extension ID, this version refuses to enable and names the duplicate: remove
the old copy, restart Blender, then enable again. Once this version is
published on the Blender Extensions listing, prefer Blender's built-in
**Update**. Save a versioned `.blend` copy before updating important
production files.

## Compatibility

| Item | Support |
|---|---|
| Blender | **5.0.0 and newer**; CI validates the minimum and current supported releases. |
| Cage targets | Mesh, Curve, Surface, and Text. |
| Merge sources | Mesh, Curve, Surface, Text, Metaball, Curves, and Point Cloud. |
| Lattice | Legacy Simple Deform only, with an explicit notice. |
| Engine | Geometry Nodes for cages; Blender's native Simple Deform for legacy mode. |
| Languages | English, Simplified Chinese, Japanese, and Korean. |
| Animation | Layer values, FFD points and influence, Curve guides and sections, end profiles, cage size, transforms, stage visibility, and legacy modifier properties. |
| Saved results | Generated node stages keep evaluating without the extension; the custom UI and controller maintenance require it. |

## Troubleshooting

| Symptom | Check |
|---|---|
| No **Simple Deformer V2** tab | Confirm the extension is enabled and press `N` in a 3D View; restart Blender once after replacing an older build. |
| Adding a cage does nothing | Select a supported object in Object Mode. If a copied object lost its node stage, remove the stale stage and add a new cage. |
| Playback does not move the mesh | Make sure the cage parameters actually carry keys (**Insert Keys** on at least two frames). Animated files resynchronize automatically on open. |
| Bend looks faceted | Add segments along the deform axis before the cage stage. |
| Cage no longer matches the object | Select the stage, set its axis, then click **Align & Fit** or **Align & Fit Chain**. |
| Chain shows a seam | Enable **Auto Reconnect**, click **Reconnect Chain**, and check **Gap Before** and the shared end scale. |
| A handle is missing | Select the target or cage and the relevant layer, then enable the matching Bend Trend / Show Twist / end / length option. |
| Lattice cannot add a cage | Intentional; use **Add Simple Deform (Legacy)**. |

## Data and removal

Removing a cage stage deletes the managed Geometry Nodes modifier and its
helper objects. Uninstalling the extension does **not** strip generated node
groups from existing `.blend` files: run **Remove Deformation Stack** first,
then save a copy.

## Feedback and contributions

Use the [bug report form](https://github.com/AIGODLIKE/simple_deform_helper/issues/new?template=bug_report.yml)
and include: extension and Blender versions, OS/GPU/input device, exact
reproduction steps and modifier order, console output, and a minimal
privacy-safe `.blend` or short video.

Pull requests should keep the extension compatible with Blender 5.0+, avoid
third-party runtime dependencies, update all four translation catalogs for
user-facing text, and pass the repository validation workflow.

## License

Simple Deform Helper V2 is distributed under **GPL-3.0-or-later**, as
declared in [`blender_manifest.toml`](blender_manifest.toml). Maya, 3ds Max,
MODO, Cinema 4D, Blender, and their marks belong to their respective owners
and are mentioned only for identification and workflow comparison.
