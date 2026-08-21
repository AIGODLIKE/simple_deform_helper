"""Runtime contract for the four supported interface locales."""

import importlib
import re
import sys
from pathlib import Path

import bpy

SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def literal_ui_icons():
    pattern = re.compile(r'icon\s*=\s*["\']([A-Z][A-Z0-9_]+)["\']')
    icons = set()
    for path in SOURCE.rglob("*.py"):
        if any(part in {"tests", "validation_runtime", "outputs"}
               for part in path.parts):
            continue
        icons.update(pattern.findall(path.read_text(encoding="utf-8")))
    return icons


valid_icons = set(
    bpy.types.UILayout.bl_rna.functions["operator"].parameters[
        "icon"].enum_items.keys())
invalid_icons = sorted(literal_ui_icons() - valid_icons)
check(not invalid_icons,
      f"UI uses icons unavailable in this Blender version: {invalid_icons!r}")


translation = importlib.import_module(f"{PACKAGE}.translate")
catalogs = translation.SimpleDeform_CN.translations_dict
required_locales = {"zh_HANS", "ja_JP", "ko_KR", "en_US"}
check(required_locales <= set(catalogs),
      f"missing locale catalogs: {required_locales - set(catalogs)!r}")

ffd_modal_header = (
    "FFD Edit Mode: drag blank area to box select | G Move; G again "
    "Tangent Slide | R Rotate | S Scale | Shift Add | Ctrl Subtract | "
    "A Select All | Alt+A Clear | I Key | Alt+I Delete Key | Alt+R "
    "Reset | Double-click blank / Esc / Right Mouse exits"
)
ffd_box_select_header = (
    "FFD Box Select: drag a rectangle over FFD points, lines, or faces | "
    "Esc / Right Mouse cancels"
)
curve_modal_header = (
    "Curve Edit Mode: G Move | R Rotate | S Scale | B Box Select | "
    "Shift Add | A Select All | Alt+A Clear | I Key | "
    "Double-click blank / Esc / Right Mouse exits"
)
curve_box_select_header = (
    "Curve Box Select: drag over points or handles | "
    "Shift Add | Ctrl Subtract | Esc cancels"
)
curve_transform_header = (
    "X/Y/Z Axis | Shift Precise | Ctrl Snap | "
    "Click/Enter Confirm | Esc/Right Mouse Cancel"
)
curve_handle_hint = "Alt Independent Handle"
curve_handle_tooltip = (
    "Linked handles move symmetrically; Alt makes this handle independent"
)
view_preferences = bpy.context.preferences.view
original_language = view_preferences.language
original_translate_interface = view_preferences.use_translate_interface
translation.register()
try:
    view_preferences.use_translate_interface = True
    for locale in ("zh_HANS", "ja_JP", "ko_KR"):
        view_preferences.language = locale
        for source, label in (
                (ffd_modal_header, "FFD"),
                (curve_modal_header, "Curve")):
            actual = bpy.app.translations.pgettext_iface(source)
            expected = catalogs[locale][("*", source)]
            check(
                actual == expected,
                f"{locale} runtime {label} header translation mismatch: "
                f"{actual!r}",
            )
finally:
    view_preferences.language = original_language
    view_preferences.use_translate_interface = original_translate_interface
    translation.unregister()

chained_description = (
    "The chain root extends continuously beyond both boundaries; later cages "
    "preserve the upstream prefix and continue from the cage end"
)
visible = (
    "Traditional Simple Deform",
    "Viewport Display",
    "Lower Limit",
    "Upper Limit",
    "Insert Deformation Keyframes",
    "Delete Deformation Keyframes",
    "Key the active cage or traditional Simple Deform stage on the current frame",
    "Delete current-frame keys for the active cage or traditional Simple Deform stage",
    "Inserted {count} deformation keyframe channels",
    "Removed {count} deformation keyframe channels",
    "Could not create the managed lower-limit Origin",
    "Create a managed Origin and keep it at the lower limit while dragging",
    "Stage {stage_index} of {stage_count}: {modifier}",
    "Deform {stage_index}/{stage_count}",
    "Low topology on {axis}: {sample_count} levels",
    "Cage Deform",
    "Add Cage Chain",
    "Subdivide to Chained Cages",
    "Batch Edit Chain",
    "Show Other Cages",
    "Sync Shared End Scale",
    "Bottom (Recommended)",
    "Non-Bottom origin may introduce subdivision errors",
    "Drag Along Cage • Shift Precise • Ctrl Move Both • Alt Opposite",
    "Large orange direction ring: drag around its center",
    "Allow Approximate Mixed Bend",
    "Allow subdivision of stacks containing Bend with other types; the operations do not commute and the result may differ",
    "Mixed Bend stacks are protected because deformation order is non-commutative; enable Allow Approximate Mixed Bend to continue",
    "Cage Type",
    "Choose a standard layered cage or a dedicated single-operation cage",
    "Standard",
    "Standard Type",
    "Allow ordered Bend, Twist, Taper, Stretch, and Shear layers",
    "Add Standard Cage",
    "Add an independent Standard layered cage",
    "Add an independent Shear cage",
    "Add an independent FFD cage",
    "Added Standard Cage stage",
    "Added Shear Cage stage",
    "Added FFD Cage stage",
    "Add Standard Chain",
    "Add Shear Chain",
    "Add FFD Chain",
    "Create a layered Standard chain",
    "Create a Shear-only chain",
    "Create an FFD-only chain",
    "Create a layered deformation cage",
    "Create a dedicated shear cage",
    "Create a dedicated free-form cage",
    "Point",
    "Shear Cage",
    "Dedicated single-operation shear cage that can form a Shear chain",
    "FFD Cage",
    "Dedicated single-operation free-form cage that can form an FFD chain",
    "Add Shear Cage",
    "Add FFD Cage",
    "Subdivide does not yet preserve these layers: {layers}",
    "Show Twist",
    "Show FFD Handles",
    "Hollow FFD",
    "Use only the outside FFD control points; interior points are hidden and excluded from deformation",
    "Edit Mode",
    "FFD Edit",
    "Select and transform FFD points, lines, and faces",
    "Edit FFD Points",
    "Keep FFD point editing active; drag blank viewport space to box select and use Esc, right-click, or double-click blank space to exit",
    "FFD Edit Mode",
    "Whether persistent FFD point editing is active in the viewport",
    "Drag in View • Alt Cage Axis • Shift Precise • Ctrl Snap",
    ffd_modal_header,
    ffd_box_select_header,
    "Inserted {count} FFD control-point keyframe channels",
    "Removed {count} FFD control-point keyframe channels",
    "Subdivided FFD cage into {count} chained stages",
    "Could not subdivide FFD cage: {error}",
    "More than 3 cage stages may reduce viewport performance",
    "Mouse Transform | X/Y/Z Cage Axis | Shift Precise | Ctrl Snap | Click/Enter Confirm | Esc/Right Mouse Cancel",
    "Mouse Transform | X/Y/Z Global; Repeat for Cage Local | Shift Precise | Ctrl Snap | Click/Enter Confirm | Esc/Right Mouse Cancel",
    "Global",
    "Local",
    "Select at least one FFD control point",
    "Cyan shear handle: drag in the cage plane",
    "Shear End-Face Handle",
    "Drag the center freely or an arm along cage X/Z; Alt locks X, Shift locks Z, Ctrl snaps",
    "Center Free • Arm X/Z • Alt X • Shift Z • Ctrl Snap",
    "FFD corners: drag in view • Alt along cage axis",
    "Drag to scale; Alt moves screen X; Shift moves screen Y; Alt+Shift moves freely",
    "Drag this point to enter FFD Edit Mode; Shift toggles its selection; Alt moves along the cage axis",
    "FFD Corner",
    "FFD Bottom X- Z-",
    "FFD Bottom X+ Z-",
    "FFD Bottom X+ Z+",
    "FFD Bottom X- Z+",
    "FFD Top X- Z-",
    "FFD Top X+ Z-",
    "FFD Top X+ Z+",
    "FFD Top X- Z+",
    "FFD Controller Display",
    "FFD Line Length",
    "Visible FFD line-controller length as a percentage of its control line",
    "FFD Line Width",
    "Consistent viewport width for every FFD line controller",
    "FFD Face Size",
    "Visible FFD face-controller size as a percentage of its grid face",
    "How geometry outside the cage is handled",
    "Only points inside the cage are affected",
    "Continue deformation beyond the cage",
    "Deform inside; continue outside from the cage ends",
    "Within Box",
    "Unlimited",
    "U Interpolation",
    "V Interpolation",
    "W Interpolation",
    "Interpolation basis across the FFD cage U direction",
    "Interpolation basis along the FFD cage deformation axis",
    "Interpolation basis across the FFD cage W direction",
    "Linear",
    "Cardinal",
    "Catmull-Rom",
    "B-Spline",
    "Deformation Order",
    "Expanded Deformation Layers",
    "Deformation layers whose parameter rows are expanded",
    "Expand every deformation layer",
    "FFD Control Points",
    "FFD Selection Mode",
    "Choose whether picking an FFD control selects one point, one adjacent U/V/W control-line segment, or one UV/UW/VW grid face",
    "FFD Point",
    "Point",
    "Line",
    "Face",
    "Select one FFD control point",
    "Show and select FFD line-segment controllers",
    "Show and select U/V/W FFD line-segment controllers",
    "Select the line along the FFD deformation axis",
    "Select one FFD cross-section face",
    "Local displacement of this FFD control point",
    "Active FFD point index used by the compact control panel",
    "Number of control points across the cage X direction",
    "Number of control points along the cage deformation axis",
    "Number of control points across the cage Z direction",
    "Reset FFD",
    "Return every FFD corner to the undeformed cage",
    "Select all, none, or invert the dedicated FFD control points",
    "Show editable FFD control-point handles",
    "Show advanced Deform Axis, Independent Ends, and Numeric Controls",
    "With multiple objects, click creates one merged cage; Ctrl-click creates a separate cage for each object",
    "No selected objects support separate cage stages",
    "Added {count} separate cage stages",
    "Added {count} separate cage stages; skipped {skipped} selected objects",
    "Show editable FFD control-point, line, and face handles",
    "FFD Symmetry Axes",
    "Choose one or more FFD lattice center planes for mirrored editing",
    "Choose one FFD symmetry axis; hold Shift to enable or disable multiple axes",
    "Enable FFD handles in the add-on preferences first",
    "Auto Sync",
    "Keep this cage's frame synchronized with the preceding cage's live deformation",
    "Auto Reconnect",
    "Default Cage Auto Sync",
    "Automatically fit newly-created non-chain cages when an earlier cage changes",
    " | Proportional | Wheel Radius",
    "Show inline controls that edit several cages immediately",
    "Show the ring used to adjust the Bend direction",
    "X and Z scale applied to every affected cage end",
    "X and Z offset applied to every affected cage end",
    "Spacing before every affected downstream cage",
    "Make this cage stage active",
    "Deformation Stack",
    "Select Deformation Stage",
    "Make this cage or traditional Simple Deform stage active",
    "Move Deformation Stage",
    "Move before the previous deformation stage",
    "Move after the next deformation stage",
    "Chained cage segments keep their internal order",
    "Remove Deformation Stage",
    "Remove this deformation stage and any owned controls",
    "Remove Deformation Stack",
    "Remove every managed cage and traditional Simple Deform stage",
    "Click a merged part to switch source; double-click blank to return",
    "Merge Collection",
    "Merge Collection for Deform",
    "Collection needs at least two supported objects",
    "Merged {count} collection objects; skipped {skipped}",
    "Deform Merge Collection",
    "Combine ordered deformation layers in one cage.",
    "Legacy Mixed Bend Option",
    "Compatibility option retained for saved operator settings; mixed Bend stacks now use the analytic chain evaluator",
    "Legacy standard-cage XYZ offsets for the eight FFD corners",
    "Key the active cage parameters, end profiles, FFD control points, and cage transform on the current frame",
    "Bake Mesh Animation",
    "Bake the evaluated cage animation to absolute shape keys on a new mesh object",
    "Start Frame",
    "First scene frame to sample",
    "End Frame",
    "Last scene frame to sample",
    "Sample Step",
    "Number of scene frames between baked shape keys",
    "Result Name",
    "Name of the new independent mesh object",
    "Hide Source",
    "Hide the source object in the viewport and renders after a successful bake",
    "End Frame must not be earlier than Start Frame",
    "Sample Step must be at least 1",
    "The evaluated geometry has no vertices",
    "The evaluated object could not be converted to a mesh",
    "Topology changes at frame {frame}; shape-key baking requires stable topology",
    "Baked {count} frames to {name}",
    chained_description,
)
curve_visible = (
    "Curve Cage",
    "Curve",
    "Add Curve Cage",
    "Added Curve Cage stage",
    "Independent Bezier-guided cage with editable cross sections",
    "Deform geometry along an editable Bezier guide",
    "Temporarily bypass Curve",
    "Control Mode",
    "Choose whether the complete source maps to the guide or the guide endpoints stay inside the cage",
    "Curve Mode",
    "Map the complete source cage and controlled object to the complete guide; editing the guide changes deformation shape without changing source boundaries, cage length, or position",
    "Cage Mode",
    "Keep the guide endpoints constrained inside the cage",
    "Range Mode",
    "Curve Range Start",
    "Lower effect boundary inside the stable Curve cage mapping domain",
    "Curve Range End",
    "Upper effect boundary inside the stable Curve cage mapping domain",
    "Effect Range Length",
    "How the Curve cage affects geometry beyond its authored range",
    "Freeze the boundary frame and continue excluded geometry rigidly along its tangent",
    "Leave geometry outside the authored cage range unchanged",
    "Extend open endpoints or repeat around a closed guide",
    "Closed Curve",
    "Join the first and last guide points into a continuous loop",
    "Length Mode",
    "How cage-axis distance is mapped to the guide",
    "Preserve Length",
    "Map physical cage distance to guide arc length",
    "Stretch to Path",
    "Use the complete guide and stretch the source along it",
    "Fit Guide to Cage",
    "Scale the complete guide shape to the authored cage length",
    "Preserve Volume",
    "Compensate cross-section scale when stretching to the guide",
    "Guide Resolution",
    "Bezier evaluation resolution used by the Curve cage",
    "Guide Points",
    "Object-mode controls for the managed Bezier guide",
    "Guide Point {index}",
    "Point Count",
    "Number of evenly-spaced guide points after resampling",
    "Cross Sections",
    "Active Cross Section",
    "Editable U/W scale and offset stations along the Curve cage",
    "Cross Section {index}",
    "Curve Profile",
    "Curve Global Radius",
    "Global Radius",
    "Uniform radius multiplier composed with native guide-point and cross-section radius",
    "Curve Global Twist",
    "Global Twist",
    "Uniform rotation added to every cross-section around the guide",
    "Guide Preset",
    "Curve Preset",
    "Parametric guide shape previewed immediately on the cage",
    "Straight",
    "Create a straight guide along the cage axis",
    "Wave",
    "Create a two-plane flowing wave guide",
    "Sine",
    "Create a planar sine-wave guide",
    "Helix",
    "Create a helical guide around the cage axis",
    "Amplitude",
    "Radial size of the generated Curve preset",
    "Cycles",
    "Number of wave cycles or helix turns along the guide",
    "Phase",
    "Starting phase of the generated Curve preset",
    "Preset Points",
    "Number of editable Bezier points generated by the preset",
    "Presets are locked while guide points are animated",
    "Cross-section radius multiplier interpolated along the guide",
    "Cross-section rotation around the guide tangent, interpolated between stations",
    "Active Guide Point",
    "Radius",
    "Twist",
    "Point Roll",
    "Point Radius",
    "Station Radius",
    "Station Twist",
    "Bevel",
    "Blend this guide point from a sharp corner to a shared smooth tangent",
    "Tension",
    "Scale the Bezier handles around this guide point",
    "Curve Point",
    "Select and move this Curve cage guide point",
    "Bezier Handle",
    "Adjust this guide point's Bezier tangent handle",
    curve_handle_tooltip,
    "Curve Point or Bezier Handle",
    "Curve Cage Controls",
    "Show Curve control, binding, range, and profile settings",
    "Show parametric Curve guide preset controls",
    "Curve Edit",
    "Show guide editing and active-point controls",
    "Show editable Curve cross-section stations",
    "Select and transform Curve guide points and handles",
    "Edit Curve Points",
    "Edit Curve cage points and Bezier handles persistently in Object Mode",
    "Curve Edit Mode",
    curve_handle_hint,
    curve_transform_header,
    curve_box_select_header,
    curve_modal_header,
    "Object Edit",
    "Native Edit",
    "Edit Curve Cage",
    "Enter the managed guide's Curve Edit Mode; use Blender selection, G/R/S, handles, subdivide, extrude, and delete tools",
    "Equalize",
    "Equalize Curve Points",
    "Redistribute guide points uniformly by curve arc length",
    "Remove or bake guide-point animation before equalizing points",
    "Remove guide shape keys, drivers, NLA, or point animation before equalizing points",
    "Equalized curve to {count} points",
    "Apply Curve Preset",
    "Replace the managed guide with the selected editable Curve preset",
    "Preset",
    "Remove or bake guide-point animation before applying a preset",
    "Remove guide shape keys, drivers, NLA, or point animation before applying a preset",
    "Applied {preset} Curve preset",
    "Add Cross Section",
    "Insert an interpolated cross-section station",
    "Equalize Cross Sections",
    "Distribute every cross section evenly along the guide",
    "Alt+S Radius | Ctrl+T Twist | O Proportional",
    "Adjust selected guide-point radii with Blender proportional falloff",
    "Adjust selected guide-point roll with Blender proportional falloff",
    "Adjust selected guide-point bevel with Blender proportional falloff",
    "Adjust selected guide-point tension with Blender proportional falloff",
    "Adjust cross-section radii with Blender proportional falloff",
    "Adjust cross-section twist with Blender proportional falloff",
    "Full Curve Falloff",
    "Apply point roll, radius, bevel, and tension through the current proportional falloff across the complete guide",
    "Even Cross Sections",
    "Keep all cross sections evenly distributed when sections are added, removed, or adjusted",
    "Remove Cross Section",
    "Remove the active interior cross-section station",
    "Reset Curve Guide",
    "Reset the guide to a straight path fitted to the cage",
    "Curve cages do not support chained creation",
    "Curve cages cannot be subdivided into chains",
)
visible += curve_visible
visible += (
    "FFD Safety",
    "Prevent Foldover",
    "Prevent FFD cell foldover by using linear interpolation and clamping control-point edits to the last safe position",
    "Allow unrestricted FFD edits and the selected interpolation",
    "Use linear interpolation and stop edits before FFD cells invert",
)
placeholders = (
    "{stage_index}", "{stage_count}", "{modifier}", "{axis}",
    "{sample_count}", "{layers}", "{cage_type}", "{count}", "{skipped}",
    "{frame}", "{name}", "{preset}", "{controls}",
)

for locale in required_locales:
    catalog = catalogs[locale]
    for source in visible:
        translated = catalog.get(("*", source))
        check(translated, f"{locale} has no translation for {source!r}")
        for placeholder in placeholders:
            check(translated.count(placeholder) == source.count(placeholder),
                  f"{locale} changed {placeholder!r} in {source!r}")

translation_invariant_labels = {"Cardinal", "Catmull-Rom"}
for locale in ("zh_HANS", "ja_JP", "ko_KR"):
    for source in visible:
        # These are established interpolation basis names rather than
        # translatable prose; keeping the canonical spelling avoids changing
        # the algorithm terminology between locales.
        if source in translation_invariant_labels:
            continue
        check(catalogs[locale][("*", source)] != source,
              f"{locale} left visible text in English: {source!r}")

for source in visible:
    check(catalogs["en_US"][("*", source)] == source,
          f"English catalog changed native text: {source!r}")

tooltip_source = (
    "Drag to scale; Alt moves screen X; Shift moves screen Y; "
    "Alt+Shift moves freely"
)
view_preferences = bpy.context.preferences.view
original_language = view_preferences.language
original_translate_tooltips = view_preferences.use_translate_tooltips
translation.register()
try:
    view_preferences.use_translate_tooltips = True
    for locale in ("zh_HANS", "ja_JP", "ko_KR", "en_US"):
        view_preferences.language = locale
        expected = catalogs[locale][("*", tooltip_source)]
        actual = bpy.app.translations.pgettext_tip(tooltip_source)
        check(actual == expected,
              f"{locale} runtime tooltip mismatch: {actual!r}")
finally:
    view_preferences.language = original_language
    view_preferences.use_translate_tooltips = original_translate_tooltips
    translation.unregister()

expected_chained_descriptions = {
    "zh_HANS": "链根从两端边界连续延伸；后续笼保留上游前段并从笼末端继续",
    "ja_JP": "チェーンのルートは両端の境界を越えて連続し、後続ケージは上流部分を保持してケージ末端から続行します",
    "ko_KR": "체인 루트는 양쪽 경계를 넘어 계속 연장되고 후속 케이지는 상류 구간을 유지하며 케이지 끝에서 이어집니다",
    "en_US": chained_description,
}
expected_chained_descriptions = {
    "zh_HANS": "链根从两端边界连续延伸；后续笼保留上游前段并从笼末端继续",
    "ja_JP": "チェーンのルートは両端の境界を越えて連続し、後続ケージは上流部分を保持してケージ末端から続行します",
    "ko_KR": "체인 루트는 양쪽 경계를 넘어 계속 연장되고 후속 케이지는 상류 구간을 유지하며 케이지 끝에서 이어집니다",
    "en_US": chained_description,
}
for locale, expected in expected_chained_descriptions.items():
    check(catalogs[locale][("*", chained_description)] == expected,
          f"{locale} changed the Chained mode description contract")

expected_cage_type_names = {
    "zh_HANS": {"Shear Cage": "斜切型", "FFD Cage": "自由形变笼"},
    "ja_JP": {"Shear Cage": "シアー型", "FFD Cage": "自由変形ケージ"},
    "ko_KR": {"Shear Cage": "전단형", "FFD Cage": "자유 변형 케이지"},
    "en_US": {"Shear Cage": "Shear Cage", "FFD Cage": "FFD Cage"},
}
expected_cage_type_names = {
    "zh_HANS": {"Shear Cage": "斜切型笼", "FFD Cage": "FFD 型笼"},
    "ja_JP": {"Shear Cage": "シアー型ケージ", "FFD Cage": "FFD型ケージ"},
    "ko_KR": {"Shear Cage": "전단형 케이지", "FFD Cage": "FFD형 케이지"},
    "en_US": {"Shear Cage": "Shear Cage", "FFD Cage": "FFD Cage"},
}
for locale, expected_names in expected_cage_type_names.items():
    for source, expected in expected_names.items():
        check(catalogs[locale][("*", source)] == expected,
              f"{locale} changed the {source!r} naming contract")

print("SDH_TRANSLATION_LOCALE::SUMMARY::PASS")
