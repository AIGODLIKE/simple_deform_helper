<div align="center">

# Simple Deform Helper V2

### Easy to Deform, Easy to Animate

**Make object deformation and deformation animation easier.**

[![Download 2.7.48](https://img.shields.io/badge/Download-2.7.48-2ea44f?style=for-the-badge)](https://github.com/AIGODLIKE/simple_deform_helper/releases)
[![Blender 5.0+](https://img.shields.io/badge/Blender-5.0%2B-F5792A?style=for-the-badge&logo=blender&logoColor=white)](https://www.blender.org/download/)
[![Validation](https://img.shields.io/github/actions/workflow/status/AIGODLIKE/simple_deform_helper/validate.yml?branch=master&style=for-the-badge&label=validation)](https://github.com/AIGODLIKE/simple_deform_helper/actions/workflows/validate.yml)

[简体中文](README.zh_HANS.md) · [日本語](README.ja_JP.md) · [한국어](README.ko_KR.md) · [Releases](https://github.com/AIGODLIKE/simple_deform_helper/releases) · [Report an issue](https://github.com/AIGODLIKE/simple_deform_helper/issues/new?template=bug_report.yml)

</div>

If you still have not mastered object deformation and deformation animation, that is not your fault: the tools have not been easy enough to use. Trust me, this tool can give you the best deformation experience on Earth.

## Quick Start

1. **Install:** Download it from the [Releases page](https://github.com/AIGODLIKE/simple_deform_helper/releases). It may be available directly from Blender Extensions in the future; because so many people are already using it, I want to collect enough real-world samples and confirm its stability before publishing the official listing.
2. **Open:** Press `N` and find the **Simple Deformer V2** tab.
3. **Add:** Select the object you want to deform (multiple objects are supported, but do not select too many), then click **Add Standard Cage**.
4. **Control:** Drag the cage controls.
5. **Animate:** Click **Insert Keys** at the bottom to record the current state.
6. **Bake:** Click **Bake Mesh Animation** for a one-click bake. Bake when you need to export or improve animation performance.
7. Done. Go explore the other cage types.

## Detailed Manual

### Feature Definitions

#### Deformation Cages

Deformation cages make both the deformation and its range easier to see. The cage types differ, but they all follow the same idea: wrap the object, then deform it.

There are four types of deformation cage:

**Standard Cage:** Also called a multi-layer deformation cage. Combine Bend, Twist, Stretch, and Shear effects in any way to create a deformation.

**Shear Cage:** Deforms an object along any tangential direction.

**FFD Cage:** An upgraded lattice deformation system with point, edge, and face controls, influence fields, and even sliding.

**Curve Cage:** A more natural, human-friendly way to deform an object with a curve.

#### Chained Cages

Use a chained cage when you need several cage segments that remain related to one another, such as preventing intersections, coordinating boundary deformation, or passing deformation from one segment to the next. You can create a chain directly, or create a deformation cage first and subdivide it into chained cages.

### Standard Cage

A Standard Cage can combine Bend, Twist, Taper, Stretch, and Shear effects in any order. Effects are evaluated from top to bottom. Each type can appear only once per Standard Cage; add another Standard Cage if you need the same effect more than once.

#### Bend

Bends the object into an arc.

| Parameter | Description |
|---|---|
| Bend Angle | Controls the bend amount. At 360 degrees, the result forms a circle. |
| Twist Angle | Controls the twist of the bend. |

##### Important: Set the Correct Bend Direction in One Click

Is the bend going the wrong way? Enable the axis direction switch and choose a direction with the Bend Direction gizmo. Bend has the highest axis-display priority, so its direction is shown first even when other deformations are present.

<img width="2560" height="1380" alt="Bend direction controls" src="https://github.com/user-attachments/assets/eac08361-5d2f-424c-b59f-ff88a1302b4d" />

##### Important: Bend Origin

The bend start position depends on the cage origin. It defaults to the bottom, but you can choose Top, Center, or Symmetric. Symmetric starts from the center and bends in opposite directions.

<img width="2560" height="1380" alt="Bend origin controls" src="https://github.com/user-attachments/assets/21d91e03-0729-47b1-a6d9-c5883a246ed3" />

#### Twist

Twists the object from bottom to top, starting at the cage origin.

| Parameter | Description |
|---|---|
| Twist Angle | Controls the twist angle. Every 360 degrees is one full turn. |

#### Taper

Tapers the object.

| Parameter | Description |
|---|---|
| Taper Factor | Controls the taper strength. |

##### Note: Pointed Tips When Adjusting Boundaries

Certain taper values create a pointed tip: Bottom `-1`, Top `1`, Center `2` or `-2`, and Symmetric `-2`. The tip closes the mesh completely into a single point.

When you adjust the top or bottom boundary, depending on the tip position, the model may look compressed. This is not an algorithm error: there is no mesh above or below a closed tip, so do not be surprised when adjusting that boundary.

<img width="2560" height="1380" alt="Tapered tip and cage boundary" src="https://github.com/user-attachments/assets/08e81591-af50-4909-915c-9d94c8903a8d" />

#### Stretch

Stretches the object from bottom to top, starting at the cage origin.

| Parameter | Description |
|---|---|
| Stretch Factor | Controls the stretch strength. |
| Maintain Volume | Constrains the object's volume. Stretching makes it thinner, while compressing makes it flatter. |

#### Shear

Shears the object tangentially from bottom to top, starting at the cage origin.

| Parameter | Description |
|---|---|
| Shear Factor | Controls the shear amount along the cage-local X and Z directions. |

### Shear Cage

This works the same way as the Shear effect in a Standard Cage.

### FFD Cage

FFD is a more advanced and easier-to-control lattice deformation system. It supports points, edges, faces, influence fields, and sliding.

#### Points, Edges, and Faces

Blender's native lattice editing works with points. FFD adds edge and face controls, so you do not have to think only in terms of vertices.

#### Slide

Select points, edges, or faces and press `G` twice to enter Slide mode. The slide direction is determined by the adjacent edge or section under the pointer.

#### Symmetry

When enabled, selecting an axis also selects the matching symmetric points, edges, or faces.

#### FFD Point Count and Interpolation

Controls the lattice point count and interpolation. U, V, and W use unified settings by default; you can disable unification.

#### FFD Point Influence (Highly Recommended)

In almost every 3D application, FFD points have equal influence. That can make even simple animation awkward, such as deforming an object with FFD and then restoring it. Here you can animate the control-point influence instead of changing the lattice shape every time.

#### Edit Modes

**Object Edit:** Uses the cage controls and enters automatically when you select a control gizmo. Press `Esc`, double-click empty space, or right-click to exit.

**Native Edit:** Enters Blender's native Lattice Edit Mode. Click **Native Edit** again to exit.

#### Hollow FFD

When enabled, only the outer controls are shown and evaluated.

#### Reset

Restores the default FFD state. This is useful for reset animations or for returning to the original state.

### Curve Cage

Creates a guide curve fitted to the object, then uses it to control the deformation.

#### Mode Selection

| Mode | Description |
|---|---|
| Curve Mode | The guide curve takes priority. It can change the cage size, and the object stretches to align with the guide. |
| Cage Mode | The cage takes priority. The guide does not change the cage size, and the cage keeps the length it had along the guide when it was created. |

#### Bind Current Guide

Resets only the object's deformation state, then uses the guide's current shape as the basis for controlling the object again.

#### Cyclic Curve

Closes the guide curve when enabled.

#### Maintain Volume

When enabled, making the curve longer makes the object thinner, while making it shorter makes the object thicker.

#### Curve Control Parameters (Native)

| Parameter | Description |
|---|---|
| Guide Resolution | Controls the resolution of the source curve. |
| Radius | Controls the radius of the entire source curve. |
| Twist | Controls the twist of the entire source curve. |

#### Guide Presets

Switches the current curve to a preset type. Be aware that this may change the object's shape.

#### Curve Editing

**Object Edit:** Edit the guide curve with the easier-to-use gizmos.

**Native Edit:** Enter Blender's native curve Edit Mode for the guide.

**Reset:** Restore the original state.

#### Point Count and Even Spacing

Choose the required point count, then click **Evenly Space**. The curve adds gizmo control points while preserving its shape as closely as possible.

#### Curve Control Parameters (Active Guide Point)

| Parameter | Description |
|---|---|
| Point Twist | Sets the twist of the selected guide point. |
| Point Radius | Sets the radius of the selected guide point. |
| Twist | Sets the twist of the selected guide point. |
| Global Falloff | Uses Blender's proportional-editing settings to control which nearby points are affected and by how much. |

#### Cross Sections

In addition to the guide curve's point segments, the cage can have its own sections. This lets you add fine cage adjustments on top of the curve deformation, which is especially useful when the guide contains many points.

### Chained Cages

<img width="2560" height="1380" alt="Chained cage controls" src="https://github.com/user-attachments/assets/4b1cad97-8ff4-4728-8c81-92f229255472" />

#### General Properties

When an object needs several deformation segments, a chained cage is the first choice.

| Feature | Description |
|---|---|
| Deformation Inheritance | Passes deformation control forward from the first cage through each following segment. |
| Boundary Coordination | Coordinates the scale controls on adjacent boundaries. |
| Boundary Protection | Prevents neighboring cages from crossing each other's boundaries. |

#### Creation Methods

**Add Directly:** Creates a chained cage across the whole object.

**Subdivide (Recommended):** Select an existing cage and subdivide it. This is especially useful in the following situations:

| Situation | Method |
|---|---|
| You need several local deformers | 1. Create a normal deformation cage. 2. Adjust it. 3. Click **Subdivide to Chained Cages**. |
| You need multi-segment adjustments while preserving the current state | Click **Subdivide to Chained Cages** directly. The algorithm preserves the current shape. |

#### Notes

1. Do not create too many chained cages: performance will suffer. For more than four segments, consider using an armature.
2. When one object has several cages, hide the other cages to reduce viewport overhead.

### Convenience Tools

#### Copy

Creates a matching copy in the deformation stack based on the object's current shape.

#### Mirror

Creates a mirrored copy of the current shape along the selected axis.

### One-Click Animation

Animation can be tedious, so these three buttons make it easier:

| Button | Description |
|---|---|
| Insert Keys | Records the current state in one click. |
| Delete Keys | Deletes deformation-related animation keys at the current timeline frame. Check the current frame first. |
| Bake Mesh Animation | Bakes the current object's mesh animation in one click. Use it when exporting or when you want better animation performance. |

### Legacy Mode

The new version completely reimplements and surpasses the old feature set. However, because many users still prefer to avoid the complexity of Geometry Nodes, the legacy mode remains available.

Refer to the previous version for detailed usage.

### Working with Multiple Objects

1. **Create:** Select multiple objects and click **Add Cage**. The objects are merged into one deformation result.
2. **Edit:** Double-click the merged object to enter Edit Mode. While editing, you can add a cage to an individual object.
3. **Unmerge:** Unmerging deletes the merged object and its deformers.
4. **Apply and Bake:** Applying and baking a multi-object result do not affect the original objects.

## Compatibility

| Item | Support |
|---|---|
| Blender | **5.0.0 and newer** |
| Cage targets | Mesh, Curve, Surface, and Text. |
| Merge sources | Mesh, Curve, Surface, Text, Metaball, Curves, and Point Cloud. |
| Lattice | Legacy Simple Deform only, with an explicit notice. |
| Engine | Geometry Nodes for cages; Blender's native Simple Deform for legacy mode. |
| Languages | English, Simplified Chinese, Japanese, and Korean. |

## Troubleshooting

| Symptom | Check |
|---|---|
| Bend direction is wrong or Bend has no effect | Enable the axis direction switch and choose the bend direction. |
| No **Simple Deformer V2** tab | Confirm the extension is enabled and press `N` in a 3D View. Restart Blender once after replacing an older version. |
| Adding a cage has no effect | Make sure you are in Object Mode with a supported object selected. If a copied object lost its node stage, remove the invalid stage and add it again. |
| The mesh does not move during playback | Make sure the cage parameters have keyframes: click **Insert Keys** on at least two frames. Animated files resynchronize automatically when opened. |
| Bend looks faceted | Add geometry segments along the deformation axis before the cage stage. |
| The cage no longer matches the object | Select the stage, set the axis, then click **Align & Fit** or **Align & Fit Chain**. |
| A chain has a visible seam | Enable **Auto Reconnect**, click **Reconnect Chain**, and check **Gap Before** and the scale at the seam ends. |
| A handle is missing | Select the target or cage and the corresponding deformation layer, then enable the relevant Bend Trend, Show Twist, end, or length option. |
| A Lattice object cannot use a cage | This is intentional. Use **Add Simple Deform (Legacy)**. |

## Data and Removal

Removing a cage stage deletes the Geometry Nodes modifier and helper objects managed by that stage. Uninstalling the extension does **not** automatically remove generated node groups from existing `.blend` files. Run **Remove Deformation Stack** first, then save a copy.

## Feedback and Contributions

Use the [issue template](https://github.com/AIGODLIKE/simple_deform_helper/issues/new?template=bug_report.yml) and include the extension and Blender versions, OS/GPU/input device, exact reproduction steps and modifier order, console output, and a minimal privacy-safe `.blend` file or short video.

## Other Notes

- I only picked up a little English, Chinese, Japanese, and Korean while watching anime, so the documentation is mainly written in English. Please tell me when you find a mistake.
- There are many languages in the world. If you would like to contribute a translation in your native language, I will be happy to merge it.
- Please share good ideas, and code contributions are even better.
- This tool has never charged a fee, and there is no paid version.
- I hope everyone enjoys using [Blender](https://fund.blender.org/).
