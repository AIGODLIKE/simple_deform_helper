import logging

import bpy

from .utils import get_language_list


_LOGGER = logging.getLogger(__name__)


def origin_text(a, b):
    return "Add an empty object origin as the rotation axis (if there is an " \
           "origin, " + a + \
        "), and set the origin position " + b + " during operation"


not_add = "do not add it"
translations_dict = {
    "Insert Cage Keyframes": "\u63d2\u5165\u7b3c\u5173\u952e\u5e27",
    "Subdivide does not yet preserve these layers: {layers}":
        "细分暂不保留这些层：{layers}",
    "Delete Cage Keyframes": "\u5220\u9664\u7b3c\u5173\u952e\u5e27",
    "Insert Keys": "\u63d2\u5165\u5173\u952e\u5e27",
    "Delete Keys": "\u5220\u9664\u5173\u952e\u5e27",
    "Inserted {count} FFD control-point keyframe channels":
        "\u5df2\u4e3a FFD \u63a7\u5236\u70b9\u63d2\u5165 {count} \u4e2a\u5173\u952e\u5e27\u901a\u9053",
    "Removed {count} FFD control-point keyframe channels":
        "\u5df2\u5220\u9664 FFD \u63a7\u5236\u70b9\u7684 {count} \u4e2a\u5f53\u524d\u5e27\u5173\u952e\u5e27\u901a\u9053",
    "Key the active cage parameters, end profiles, FFD control points, and cage transform on the current frame":
        "\u4e3a\u5f53\u524d\u7b3c\u7684\u53c2\u6570\u3001\u7aef\u9762\u5f62\u6001\u3001FFD \u63a7\u5236\u70b9\u548c\u7b3c\u53d8\u6362\u5728\u5f53\u524d\u5e27\u63d2\u5165\u5173\u952e\u5e27",
    "Delete the current-frame keys created for the active cage":
        "\u5220\u9664\u5f53\u524d\u7b3c\u5728\u5f53\u524d\u5e27\u521b\u5efa\u7684\u5173\u952e\u5e27",
    "Inserted {count} cage keyframe channels":
        "\u5df2\u63d2\u5165 {count} \u4e2a\u7b3c\u5173\u952e\u5e27\u901a\u9053",
    "Removed {count} cage keyframe channels":
        "\u5df2\u5220\u9664 {count} \u4e2a\u7b3c\u5173\u952e\u5e27\u901a\u9053",
    "Alt: Screen X | Shift: Screen Y | Alt+Shift: Free | Ctrl: Snap":
        "Alt\uff1a\u5c4f\u5e55 X | Shift\uff1a\u5c4f\u5e55 Y | Alt+Shift\uff1a\u81ea\u7531 | Ctrl\uff1a\u5438\u9644",
    "Added cage to the final state of {name}": "已向 {name} 的最终状态添加笼",
    "Rotation Mode": "\u65cb\u8f6c\u6a21\u5f0f",
    "Previous": "\u4e0a\u4e00\u4e2a",
    "Next": "\u4e0b\u4e00\u4e2a",
    "Select the previous Simple Deform modifier":
        "\u9009\u62e9\u4e0a\u4e00\u4e2a\u7b80\u6613\u5f62\u53d8\u4fee\u6539\u5668",
    "Select the next Simple Deform modifier":
        "\u9009\u62e9\u4e0b\u4e00\u4e2a\u7b80\u6613\u5f62\u53d8\u4fee\u6539\u5668",
    "Earlier": "\u66f4\u65e9",
    "Later": "\u66f4\u665a",
    "Tool Settings": "\u5de5\u5177\u8bbe\u7f6e",
    "In Front": "\u663e\u793a\u5728\u524d\u65b9",
    "Show Gizmo": "\u663e\u793a Gizmo",
    "Stage Index": "\u9636\u6bb5\u7d22\u5f15",
    "Active Deformation Layer": "\u6d3b\u52a8\u5f62\u53d8\u5c42",
    "Muted Deformations": "\u5df2\u9759\u97f3\u7684\u5f62\u53d8",
    "Original Origin": "\u539f\u59cb\u539f\u70b9",
    "Origin Object Rotate Angle": "\u539f\u70b9\u5bf9\u8c61\u65cb\u8f6c\u89d2\u5ea6",
    "Origin Object Rotate Axis": "\u539f\u70b9\u5bf9\u8c61\u65cb\u8f6c\u8f74",
    "Expand every deformation layer in the cage UI":
        "\u5728\u7b3c\u9762\u677f\u4e2d\u5c55\u5f00\u6240\u6709\u5f62\u53d8\u5c42",
    "Persistent execution order for the enabled deformation layers":
        "\u4fdd\u5b58\u5df2\u542f\u7528\u5f62\u53d8\u5c42\u7684\u6267\u884c\u987a\u5e8f",
    "Index of the deformation layer selected in the cage UI":
        "\u7b3c\u9762\u677f\u4e2d\u9009\u4e2d\u7684\u5f62\u53d8\u5c42\u7d22\u5f15",
    "Present deformation layers temporarily bypassed by this cage":
        "\u6b64\u7b3c\u4e34\u65f6\u8df3\u8fc7\u7684\u73b0\u6709\u5f62\u53d8\u5c42",
    "Temporarily bypass Bend": "\u4e34\u65f6\u8df3\u8fc7\u5f2f\u66f2",
    "Temporarily bypass Twist": "\u4e34\u65f6\u8df3\u8fc7\u626d\u8f6c",
    "Temporarily bypass Taper": "\u4e34\u65f6\u8df3\u8fc7\u9525\u5316",
    "Temporarily bypass Stretch": "\u4e34\u65f6\u8df3\u8fc7\u62c9\u4f38",
    "Move before the previous Cage Deform":
        "\u79fb\u52a8\u5230\u4e0a\u4e00\u4e2a\u7b3c\u5f0f\u5f62\u53d8\u4e4b\u524d",
    "Move after the next Cage Deform":
        "\u79fb\u52a8\u5230\u4e0b\u4e00\u4e2a\u7b3c\u5f0f\u5f62\u53d8\u4e4b\u540e",
    "Key the active strength, limits, and managed Origin controls":
        "\u4e3a\u6d3b\u52a8\u5f3a\u5ea6\u3001\u9650\u5236\u548c\u53d7\u7ba1\u7406\u539f\u70b9\u63a7\u5236\u63d2\u5165\u5173\u952e\u5e27",
    "Remove the current-frame keys created for the active Simple Deform":
        "\u5220\u9664\u6d3b\u52a8\u7b80\u6613\u5f62\u53d8\u521b\u5efa\u7684\u5f53\u524d\u5e27\u5173\u952e\u5e27",
    "Create a managed Origin and keep it at the upper limit while dragging":
        "\u521b\u5efa\u53d7\u7ba1\u7406\u7684\u539f\u70b9\uff0c\u5e76\u5728\u62d6\u52a8\u65f6\u5c06\u5176\u4fdd\u6301\u5728\u4e0a\u9650",
    "Create a managed Origin and keep it at the lower limit while dragging":
        "\u521b\u5efa\u53d7\u7ba1\u7406\u7684\u539f\u70b9\uff0c\u5e76\u5728\u62d6\u52a8\u65f6\u5c06\u5176\u4fdd\u6301\u5728\u4e0b\u9650",
    "Create a managed Origin between the upper and lower limits":
        "\u5728\u4e0a\u9650\u4e0e\u4e0b\u9650\u4e4b\u95f4\u521b\u5efa\u53d7\u7ba1\u7406\u7684\u539f\u70b9",
    "Create a managed Origin at the deformation bounds center":
        "\u5728\u5f62\u53d8\u8fb9\u754c\u6846\u4e2d\u5fc3\u521b\u5efa\u53d7\u7ba1\u7406\u7684\u539f\u70b9",
    "Middle": "\u4e2d\u95f4",
    "Stage {stage_index} of {stage_count}: {modifier}":
        "\u7b2c {stage_index} / {stage_count} \u4e2a\u9636\u6bb5\uff1a{modifier}",
    "Deform {stage_index}/{stage_count}":
        "\u5f62\u53d8 {stage_index}/{stage_count}",
    "Low topology on {axis}: {sample_count} levels":
        "{axis} \u8f74\u62d3\u6251\u5bc6\u5ea6\u8fc7\u4f4e\uff1a{sample_count} \u4e2a\u5c42\u7ea7",
    "Animated": "\u52a8\u753b",
    "Property": "\u5c5e\u6027",
    "01 Local Space": "01 \u5c40\u90e8\u7a7a\u95f4",
    "02 Cage Profile": "02 \u7b3c\u8f6e\u5ed3",
    "07 Mode and Output": "07 \u6a21\u5f0f\u4e0e\u8f93\u51fa",
    "Subdivide to Chained Cages": "\u7ec6\u5206\u4e3a\u94fe\u5f0f\u7b3c",
    "Split the active cage inside its current range and distribute its deformation across a chained cage stack":
        "\u5728\u5f53\u524d\u7b3c\u8303\u56f4\u5185\u8fdb\u884c\u7ec6\u5206\uff0c\u5e76\u5c06\u5f62\u53d8\u5206\u914d\u5230\u94fe\u5f0f\u7b3c\u5806\u6808",
    "Number of chained segments inside the current cage range":
        "\u5f53\u524d\u7b3c\u8303\u56f4\u5185\u7684\u94fe\u5f0f\u5206\u6bb5\u6570\u91cf",
    "Uniform spacing between segments; segment lengths shrink so the original total range is preserved":
        "\u5206\u6bb5\u4e4b\u95f4\u7684\u7edf\u4e00\u95f4\u9694\uff1b\u5206\u6bb5\u957f\u5ea6\u4f1a\u76f8\u5e94\u7f29\u77ed\uff0c\u4ee5\u4fdd\u6301\u539f\u59cb\u603b\u8303\u56f4",
    "Keep each newly-created shared cross-section continuous":
        "\u4fdd\u6301\u65b0\u5efa\u5171\u4eab\u622a\u9762\u8fde\u7eed",
    "The original cage boundaries stay fixed.":
        "\u539f\u7b3c\u7684\u9996\u5c3e\u8fb9\u754c\u4fdd\u6301\u4e0d\u53d8\u3002",
    "Bend and Twist angles are distributed across segments.":
        "\u5f2f\u66f2\u4e0e\u626d\u8f6c\u89d2\u5ea6\u4f1a\u5206\u914d\u5230\u5404\u4e2a\u5206\u6bb5\u3002",
    "Batch Edit": "\u6279\u91cf\u7f16\u8f91",
    "Batch Edit Chain": "\u6279\u91cf\u7f16\u8f91\u94fe\u5f0f\u7b3c",
    "Edit several cages in the active chain as one operation":
        "\u5728\u4e00\u6b21\u64cd\u4f5c\u4e2d\u7f16\u8f91\u5f53\u524d\u94fe\u4e2d\u7684\u591a\u4e2a\u7b3c",
    "Scope": "\u8303\u56f4",
    "Whole Chain": "\u6574\u6761\u94fe",
    "Edit every cage in this chain": "\u7f16\u8f91\u6b64\u94fe\u4e2d\u7684\u6240\u6709\u7b3c",
    "Start to Active": "\u8d77\u70b9\u5230\u5f53\u524d",
    "Edit the chain root through the active cage":
        "\u7f16\u8f91\u4ece\u94fe\u6839\u5230\u5f53\u524d\u7b3c",
    "Active to End": "\u5f53\u524d\u5230\u672b\u7aef",
    "Edit the active cage through the chain tip":
        "\u7f16\u8f91\u4ece\u5f53\u524d\u7b3c\u5230\u94fe\u672b\u7aef",
    "Operation": "\u64cd\u4f5c",
    "End Scale": "\u7aef\u90e8\u7f29\u653e",
    "Batch-edit top and bottom cross-section scale":
        "\u6279\u91cf\u7f16\u8f91\u9876\u90e8\u4e0e\u5e95\u90e8\u622a\u9762\u7f29\u653e",
    "End Offset": "\u7aef\u90e8\u504f\u79fb",
    "Batch-edit top and bottom cross-section offset":
        "\u6279\u91cf\u7f16\u8f91\u9876\u90e8\u4e0e\u5e95\u90e8\u622a\u9762\u504f\u79fb",
    "Set spacing before every cage in scope":
        "\u8bbe\u7f6e\u8303\u56f4\u5185\u6bcf\u4e2a\u7b3c\u4e4b\u524d\u7684\u95f4\u9694",
    "Batch-edit one deformation parameter":
        "\u6279\u91cf\u7f16\u8f91\u4e00\u4e2a\u5f62\u53d8\u53c2\u6570",
    "Deformation": "\u5f62\u53d8",
    "Stage Visibility": "\u5f62\u53d8\u6bb5\u542f\u7528\u72b6\u6001",
    "Apply or bypass every cage in scope":
        "\u5e94\u7528\u6216\u8df3\u8fc7\u8303\u56f4\u5185\u7684\u6bcf\u4e2a\u7b3c",
    "Ends": "\u7aef\u90e8",
    "Edit top ends": "\u7f16\u8f91\u9876\u90e8",
    "Edit bottom ends": "\u7f16\u8f91\u5e95\u90e8",
    "Both": "\u4e24\u7aef",
    "Edit both ends": "\u540c\u65f6\u7f16\u8f91\u4e24\u7aef",
    "Apply As": "\u5e94\u7528\u65b9\u5f0f",
    "Set Values": "\u8bbe\u7f6e",
    "Replace existing values": "\u66ff\u6362\u73b0\u6709\u503c",
    "Add Values": "\u53e0\u52a0",
    "Add to existing values": "\u4e0e\u73b0\u6709\u503c\u76f8\u52a0",
    "Multiply Values": "\u4e58\u7b97",
    "Multiply existing values": "\u4e0e\u73b0\u6709\u503c\u76f8\u4e58",
    "X and Z cross-section values": "\u622a\u9762 X \u4e0e Z \u503c",
    "X and Z cross-section offset values": "\u622a\u9762 X \u4e0e Z \u504f\u79fb\u503c",
    "Spacing before each affected downstream cage":
        "\u6bcf\u4e2a\u53d7\u5f71\u54cd\u4e0b\u6e38\u7b3c\u4e4b\u524d\u7684\u95f4\u9694",
    "Preserve Total Range": "\u4fdd\u6301\u603b\u8303\u56f4",
    "Shorten each cage as its incoming gap grows":
        "\u5728\u524d\u95f4\u9694\u589e\u5927\u65f6\u76f8\u5e94\u7f29\u77ed\u7b3c",
    "Parameter": "\u53c2\u6570",
    "Batch-edit Bend angle": "\u6279\u91cf\u7f16\u8f91\u5f2f\u66f2\u89d2\u5ea6",
    "Batch-edit Bend direction": "\u6279\u91cf\u7f16\u8f91\u626d\u8f6c\u89d2\u5ea6",
    "Batch-edit Twist angle": "\u6279\u91cf\u7f16\u8f91\u626d\u8f6c\u89d2\u5ea6",
    "Batch-edit Taper factor": "\u6279\u91cf\u7f16\u8f91\u9525\u5316\u7cfb\u6570",
    "Batch-edit Stretch factor": "\u6279\u91cf\u7f16\u8f91\u62c9\u4f38\u7cfb\u6570",
    "Enable Stages": "\u542f\u7528\u5f62\u53d8\u6bb5",
    "Apply the affected cage stages": "\u5e94\u7528\u53d7\u5f71\u54cd\u7684\u7b3c\u5f62\u53d8\u6bb5",
    "Linked shared boundaries are changed only once.":
        "\u5df2\u8054\u52a8\u7684\u5171\u4eab\u8fb9\u754c\u53ea\u4f1a\u66f4\u6539\u4e00\u6b21\u3002",
    "Cages without this deformation layer are skipped.":
        "\u4e0d\u542b\u6b64\u5f62\u53d8\u5c42\u7684\u7b3c\u4f1a\u88ab\u8df3\u8fc7\u3002",
    "Created {count} cage stages": "\u5df2\u521b\u5efa {count} \u4e2a\u7b3c\u9636\u6bb5",
    "More than 3 cage stages may reduce viewport performance":
        "\u8d85\u8fc7 3 \u4e2a\u7b3c\u9636\u6bb5\u53ef\u80fd\u4f1a\u964d\u4f4e\u89c6\u53e3\u6027\u80fd",
    "Could not create cage chain: {error}": "\u65e0\u6cd5\u521b\u5efa\u7b3c\u94fe\uff1a{error}",
    "Only a single cage can be subdivided": "\u53ea\u80fd\u7ec6\u5206\u5355\u4e2a\u7b3c",
    "Set the cage origin to Bottom before subdividing":
        "\u7ec6\u5206\u524d\u8bf7\u5c06\u7b3c\u7684\u8d77\u70b9\u8bbe\u4e3a\u5e95\u90e8",
    "Animated cage parameters cannot be subdivided safely":
        "\u5e26\u52a8\u753b\u7684\u7b3c\u53c2\u6570\u65e0\u6cd5\u5b89\u5168\u7ec6\u5206",
    "Taper collapses at an interior split boundary":
        "\u9525\u5316\u4f1a\u5728\u5185\u90e8\u5206\u5272\u8fb9\u754c\u5904\u584c\u9677",
    "Subdivided cage into {count} chained stages":
        "\u5df2\u5c06\u7b3c\u7ec6\u5206\u4e3a {count} \u4e2a\u94fe\u5f0f\u9636\u6bb5",
    "Subdivided cage into {count} chained stages (gap clamped to preserve range)":
        "\u5df2\u5c06\u7b3c\u7ec6\u5206\u4e3a {count} \u4e2a\u94fe\u5f0f\u9636\u6bb5\uff08\u95f4\u9694\u5df2\u9650\u5236\u4ee5\u4fdd\u6301\u8303\u56f4\uff09",
    "Could not subdivide cage: {error}": "\u65e0\u6cd5\u7ec6\u5206\u7b3c\uff1a{error}",
    "Could not batch edit chain: {error}": "\u65e0\u6cd5\u6279\u91cf\u7f16\u8f91\u7b3c\u94fe\uff1a{error}",
    "No matching cage values were changed": "\u6ca1\u6709\u7b26\u5408\u6761\u4ef6\u7684\u7b3c\u53c2\u6570\u88ab\u66f4\u6539",
    "Updated {count} cage stages": "\u5df2\u66f4\u65b0 {count} \u4e2a\u7b3c\u9636\u6bb5",
    "Fitted {count} cage stages to chain input":
        "\u5df2\u5c06 {count} \u4e2a\u7b3c\u9636\u6bb5\u9002\u914d\u5230\u7b3c\u94fe\u8f93\u5165",
    "No cage chain metadata was found": "\u672a\u627e\u5230\u7b3c\u94fe\u5143\u6570\u636e",
    "Missing cage stages: {indices}": "\u7f3a\u5c11\u7b3c\u9636\u6bb5\uff1a{indices}",
    "Duplicate cage stage indices: {indices}": "\u7b3c\u9636\u6bb5\u7d22\u5f15\u91cd\u590d\uff1a{indices}",
    "A non-cage modifier is inserted inside the chain":
        "\u7b3c\u94fe\u4e2d\u63d2\u5165\u4e86\u975e\u7b3c\u5f0f\u4fee\u6539\u5668",
    "A chain stage has no matching controller":
        "\u7b3c\u94fe\u9636\u6bb5\u7f3a\u5c11\u5339\u914d\u7684\u63a7\u5236\u5668",
    "Chain stages use different connection modes":
        "\u7b3c\u94fe\u9636\u6bb5\u4f7f\u7528\u4e86\u4e0d\u540c\u7684\u8fde\u63a5\u6a21\u5f0f",
    "Cage chain is broken": "\u7b3c\u94fe\u5df2\u65ad\u5f00",
    "No Cage Chain was found": "\u672a\u627e\u5230\u7b3c\u94fe",
    "Reconnected {count} cage stages": "\u5df2\u91cd\u65b0\u8fde\u63a5 {count} \u4e2a\u7b3c\u9636\u6bb5",
    "Reconnected {count} cage stages and released the subdivision baseline":
        "已重新连接 {count} 个笼阶段，并解除细分基线（旧文件修复）",
    "Add Cage Chain": "\u6dfb\u52a0\u7b3c\u94fe",
    "Number of segments to create": "\u8981\u521b\u5efa\u7684\u5206\u6bb5\u6570\u91cf",
    "Connection Mode": "\u8fde\u63a5\u6a21\u5f0f",
    "How neighboring cage segments handle their boundaries":
        "\u76f8\u90bb\u7b3c\u6bb5\u5982\u4f55\u5904\u7406\u8fb9\u754c",
    "The chain root extends continuously beyond both boundaries; later cages preserve the upstream prefix and continue from the cage end":
        "链根从两端边界连续外延；后续笼保留上游前段，并从笼末端继续",
    "Limit each segment to its own box":
        "\u5c06\u6bcf\u4e2a\u6bb5\u9650\u5236\u5728\u81ea\u8eab\u7b3c\u5185",
    "Gap": "\u95f4\u9694",
    "Gap Before": "前间隔",
    "Gap from Previous Cage": "与前一个笼的间隔",
    "Non-negative distance from the previous cage; changing it keeps the overall chain span when possible":
        "与前一个笼之间的非负距离；调整时会尽可能保持笼链总跨度不变",
    "Distance between this cage and the previous cage":
        "当前笼与前一个笼之间的距离",
    "Distance between neighboring cage frames in target units":
        "\u76f8\u90bb\u7b3c\u6846\u4e4b\u95f4\u7684\u8ddd\u79bb\uff08\u76ee\u6807\u7269\u4f53\u5355\u4f4d\uff09",
    "Cage Axis": "\u7b3c\u8f74\u5411",
    "Use the longest input dimension": "\u4f7f\u7528\u8f93\u5165\u51e0\u4f55\u7684\u6700\u957f\u5c3a\u5bf8",
    "Align cage Y to target +X": "\u5c06\u7b3c Y \u8f74\u5bf9\u9f50\u5230\u76ee\u6807 +X",
    "Align cage Y to target -X": "\u5c06\u7b3c Y \u8f74\u5bf9\u9f50\u5230\u76ee\u6807 -X",
    "Align cage Y to target +Y": "\u5c06\u7b3c Y \u8f74\u5bf9\u9f50\u5230\u76ee\u6807 +Y",
    "Align cage Y to target -Y": "\u5c06\u7b3c Y \u8f74\u5bf9\u9f50\u5230\u76ee\u6807 -Y",
    "Align cage Y to target +Z": "\u5c06\u7b3c Y \u8f74\u5bf9\u9f50\u5230\u76ee\u6807 +Z",
    "Align cage Y to target -Z": "\u5c06\u7b3c Y \u8f74\u5bf9\u9f50\u5230\u76ee\u6807 -Z",
    "Select a supported target object first": "\u8bf7\u5148\u9009\u62e9\u652f\u6301\u7684\u76ee\u6807\u5bf9\u8c61",
    "Add Simple Deform": "\u6dfb\u52a0\u7b80\u6613\u5f62\u53d8",
    "Add Simple Deform (Legacy)":
        "\u6dfb\u52a0\u7b80\u6613\u5f62\u53d8\u4fee\u6539\u5668\uff08\u4f20\u7edf\uff09",
    "Add a traditional Simple Deform modifier":
        "\u6dfb\u52a0\u4f20\u7edf\u7b80\u6613\u5f62\u53d8\u4fee\u6539\u5668",
    "Added legacy Simple Deform modifier":
        "\u5df2\u6dfb\u52a0\u4f20\u7edf\u7b80\u6613\u5f62\u53d8\u4fee\u6539\u5668",
    "Cage deformation is not supported for lattice objects":
        "\u6676\u683c\u7269\u4f53\u5f53\u524d\u4e0d\u652f\u6301\u7b3c\u5f0f\u5f62\u53d8",
    "The selected surface could not be converted for cage deformation":
        "\u9009\u4e2d\u7684\u66f2\u9762\u65e0\u6cd5\u8f6c\u6362\u4e3a\u7b3c\u5f0f\u53d8\u5f62\u6240\u9700\u7684\u7f51\u683c",
    "Surface cage deformation requires a mesh conversion":
        "\u66f2\u9762\u7b3c\u5f0f\u53d8\u5f62\u9700\u8981\u5148\u8f6c\u6362\u4e3a\u7f51\u683c",
    "Add Chained Cages": "\u6dfb\u52a0\u94fe\u5f0f\u7b3c",
    "Create Cage Chain": "\u521b\u5efa\u7b3c\u94fe",
    "Create several related deformation cages in one operation":
        "\u4e00\u6b21\u521b\u5efa\u591a\u4e2a\u76f8\u5173\u53d8\u5f62\u7b3c",
    "Cage Count": "\u7b3c\u6570\u91cf",
    "Use isolated boxes": "\u4ec5\u5f71\u54cd\u5404\u81ea\u7b3c\u6846\u5185\u7684\u51e0\u4f55\u4f53",
    "Number of chained cages to create": "\u8981\u521b\u5efa\u7684\u94fe\u5f0f\u7b3c\u6570\u91cf",
    "Connect Ends": "\u8fde\u63a5\u7aef\u90e8",
    "Align each cage bottom to the previous cage top":
        "\u5c06\u6bcf\u4e2a\u7b3c\u7684\u5e95\u90e8\u5bf9\u9f50\u5230\u524d\u4e00\u4e2a\u7b3c\u7684\u9876\u90e8",
    "Chain Mode": "\u7b3c\u94fe\u6a21\u5f0f",
    "Use forward continuation when available":
        "\u5c3d\u53ef\u80fd\u4f7f\u7528\u6cbf\u524d\u65b9\u8fde\u7eed\u5ef6\u4f38",
    "Create stages without automatic reconnection":
        "\u521b\u5efa\u5404\u9636\u6bb5\uff0c\u4e0d\u81ea\u52a8\u91cd\u65b0\u8fde\u63a5",
    "Chained": "\u94fe\u5f0f",
    "Independent": "\u72ec\u7acb",
    "Segment": "\u6bb5",
    "Enable Stage": "\u542f\u7528\u5f62\u53d8\u6bb5",
    "Temporarily apply or bypass this cage while preserving chained-stage flow":
        "\u4e34\u65f6\u5e94\u7528\u6216\u8df3\u8fc7\u6b64\u7b3c\uff0c\u540c\u65f6\u4fdd\u6301\u94fe\u5f0f\u5f62\u53d8\u6bb5\u7684\u4f20\u9012",
    "Show Other Cages": "\u663e\u793a\u5176\u4ed6\u7b3c",
    "Display inactive cages and make their viewport controls directly editable":
        "\u663e\u793a\u975e\u5f53\u524d\u7b3c\uff0c\u5e76\u53ef\u76f4\u63a5\u7f16\u8f91\u5176\u89c6\u53e3\u63a7\u5236\u5668",
    "Show Other Cage Controllers": "\u663e\u793a\u5176\u4ed6\u7b3c\u63a7\u5236\u5668",
    "Display all cage controllers except active one":
        "\u663e\u793a\u9664\u5f53\u524d\u7b3c\u5916\u7684\u6240\u6709\u7b3c\u63a7\u5236\u5668",
    "Active Cage": "\u5f53\u524d\u7b3c",
    "Inactive Cage": "\u975e\u6d3b\u52a8\u7b3c",
    "Active cage is highlighted; other cages are dimmed":
        "\u5f53\u524d\u7b3c\u9ad8\u4eae\u663e\u793a\uff1b\u5176\u4ed6\u7b3c\u53d8\u6697",
    "Select this cage stage and its controller":
        "\u9009\u62e9\u6b64\u7b3c\u9636\u6bb5\u53ca\u5176\u63a7\u5236\u5668",
    "Select Cage Stage": "\u9009\u62e9\u7b3c\u9636\u6bb5",
    "Select Deformation Stage": "选择形变阶段",
    "Make this cage or traditional Simple Deform stage active":
        "将此笼或传统 Simple Deform 阶段设为活动项",
    "Cage Deform Strength Handle": "\u7b3c\u5f0f\u53d8\u5f62\u5f3a\u5ea6\u624b\u67c4",
    "Cage End Shape": "\u7b3c\u7aef\u90e8\u5f62\u6001",
    "Cage Boundary": "\u7b3c\u8fb9\u754c",
    "Auto Reconnect Chain": "\u81ea\u52a8\u91cd\u65b0\u8fde\u63a5\u7b3c\u94fe",
    "Automatically refresh downstream cage frames after a chain parameter or controller transform changes":
        "\u94fe\u53c2\u6570\u6216\u63a7\u5236\u5668\u53d8\u6362\u540e\u81ea\u52a8\u5237\u65b0\u4e0b\u6e38\u7b3c\u6846",
    "Auto Reconnect": "\u81ea\u52a8\u91cd\u65b0\u8fde\u63a5",
    "Refresh downstream cage frames after upstream edits":
        "\u4e0a\u6e38\u7f16\u8f91\u540e\u5237\u65b0\u4e0b\u6e38\u7b3c\u6846",
    "Use one-sided continuation": "\u4f7f\u7528\u5355\u5411\u8fde\u7eed\u5ef6\u4f38",
    "Propagate each preceding cage output frame to the next cage":
        "\u5c06\u524d\u4e00\u4e2a\u7b3c\u7684\u8f93\u51fa\u6846\u4f20\u9012\u7ed9\u4e0b\u4e00\u4e2a\u7b3c",
    "Reconnect Broken Chain": "\u91cd\u65b0\u8fde\u63a5\u65ad\u88c2\u7b3c\u94fe",
    "Attempt contiguous stages even when a stack issue is detected":
        "\u5373\u4f7f\u5806\u6808\u5b58\u5728\u95ee\u9898\uff0c\u4e5f\u5c1d\u8bd5\u8fde\u7eed\u9636\u6bb5",
    "Cage Deform core is unavailable": "\u7b3c\u5f0f\u53d8\u5f62\u6838\u5fc3\u4e0d\u53ef\u7528",
    "Chained Cages": "\u94fe\u5f0f\u7b3c",
    "Independent Cage Chain": "\u72ec\u7acb\u7b3c\u94fe",
    "Reconnect Chain": "\u91cd\u65b0\u8fde\u63a5\u7b3c\u94fe",
    "Reconnect Cage Chain": "\u91cd\u65b0\u8fde\u63a5\u7b3c\u94fe",
    "Align each cage to the previous cage's output frame":
        "\u5c06\u6bcf\u4e2a\u7b3c\u5bf9\u9f50\u5230\u524d\u4e00\u4e2a\u7b3c\u7684\u8f93\u51fa\u6846",
    "Each stage keeps its own angle and length; reconnect updates the incoming frame.":
        "\u6bcf\u4e2a\u9636\u6bb5\u4fdd\u7559\u81ea\u8eab\u7684\u89d2\u5ea6\u548c\u957f\u5ea6\uff1b\u91cd\u65b0\u8fde\u63a5\u53ea\u66f4\u65b0\u8f93\u5165\u6846",
    "Each stage keeps its deformations, length, and incoming gap.":
        "每个阶段保留自身的形变、长度和前间隔。",
    "Sync Shared End Scale": "同步接缝端部缩放",
    "Allow Approximate Mixed Bend": "允许近似混合弯曲细分",
    "Allow subdivision of stacks containing Bend with other types; the operations do not commute and the result may differ":
        "允许将弯曲与其他类型混合的堆栈进行近似细分；这些操作不可交换，结果可能不同",
    "Mixed Bend stacks are protected because deformation order is non-commutative; enable Allow Approximate Mixed Bend to continue":
        "已保护混合弯曲堆栈，因为形变顺序不可交换；启用“允许近似混合弯曲细分”后继续",
    "Scale both sides of each shared cage seam together while keeping each outer end independent":
        "同步每个相邻笼接缝两侧的端部缩放，同时保持首尾外端独立",
    "Scale both sides of each shared cage seam together while keeping outer ends independent":
        "同步每个相邻笼接缝两侧的端部缩放，同时保持外端独立",
    "Only neighboring seam-end scales are synchronized.":
        "仅同步相邻笼接缝端部的缩放。",
    "Outer cage ends remain independent.": "首尾外端仍保持独立。",
    "Chained mode starts at the lower cage boundary.":
        "\u94fe\u5f0f\u6a21\u5f0f\u4ece\u7b3c\u7684\u5e95\u90e8\u8fb9\u754c\u5f00\u59cb",
    "Cage Chain mode is locked to Chained.":
        "\u7b3c\u94fe\u6a21\u5f0f\u5df2\u9501\u5b9a\u4e3a\u94fe\u5f0f",
    "Simple Deformer": "简易变形器",
    "Simple Deformer V2": "\u7b80\u6613\u53d8\u5f62\u5668V2",
    "Add New Cages to End": "\u5c06\u65b0\u7b3c\u6dfb\u52a0\u5230\u5806\u6808\u672b\u5c3e",
    "Place newly-created cage stages at the end of the modifier stack":
        "\u5c06\u65b0\u5efa\u7b3c\u9636\u6bb5\u653e\u5230\u4fee\u6539\u5668\u5806\u6808\u672b\u5c3e",
    "Cage Deform": "笼式形变",
    "Add Cage Deform": "添加笼式形变",
    "Add an independent cage deformation stage": "添加一个独立的笼式形变阶段",
    "Added Cage Deform stage": "已添加笼式形变阶段",
    "Deform axis changed; the user-supplied Origin was preserved":
        "形变轴已更改；已保留用户指定的原点",
    "Subdivision was added at the end; move it before Simple Deform":
        "细分已添加到末尾；请将其移动到简易形变之前",
    "Inserted {inserted} Simple Deform keyframe channels":
        "已插入 {inserted} 个简易形变关键帧通道",
    "Removed {removed} Simple Deform keyframe channels":
        "已删除 {removed} 个简易形变关键帧通道",
    "Independent cage deformation": "独立笼式形变",
    "Bend, Twist, Taper, and Stretch.": "支持弯曲、扭转、锥化和拉伸。",
    "Combine Bend, Twist, Taper, and Stretch in one cage.":
        "可在同一个笼中组合弯曲、扭曲、锥化和拉伸。",
    "Cage Stack": "笼式形变堆栈",
    "Deformation Stack": "形变堆栈",
    "Move Cage Stage": "移动笼式形变阶段",
    "Move Deformation Stage": "移动形变阶段",
    "Move before the previous deformation stage": "移到上一个形变阶段之前",
    "Move after the next deformation stage": "移到下一个形变阶段之后",
    "Move this deformation earlier or later in the modifier stack":
        "在修改器堆栈中前移或后移此形变",
    "Duplicate Cage Stage": "复制笼式形变阶段",
    "Duplicate": "复制",
    "Remove Cage Stage": "删除笼式形变阶段",
    "Remove Deformation Stage": "删除形变阶段",
    "Remove this deformation stage and any owned controls":
        "删除此形变阶段及其拥有的控制器",
    "Remove Stage": "删除阶段",
    "Remove Cage Stack": "删除笼式堆栈",
    "Remove Deformation Stack": "删除形变堆栈",
    "Remove every managed cage and traditional Simple Deform stage":
        "删除所有受管笼和传统 Simple Deform 阶段",
    "Remove": "删除",
    "Remove this managed deformation stage and its cage controller":
        "删除此形变阶段及其笼控制器",
    "Remove every managed cage stage and its owned controllers":
        "删除所有受管笼式阶段及其控制器",
    "Shape": "形态",
    "Deformation Layers": "形变层",
    "Expand All": "\u5168\u90e8\u5c55\u5f00",
    "Add Deformation": "添加形变",
    "Add Deformation Layer": "添加形变层",
    "Add one deformation operation to this cage": "向当前笼添加一个形变操作",
    "Select Deformation Layer": "选择形变层",
    "Select this deformation layer without changing its evaluation":
        "选择此形变层，但不改变其计算状态",
    "Remove Deformation Layer": "移除形变层",
    "Remove this deformation operation from the cage": "从当前笼移除此形变操作",
    "Toggle Deformation Layer": "切换形变层启用状态",
    "Temporarily bypass or restore this deformation without losing its settings":
        "临时旁路或恢复此形变，并保留其设置",
    "Move Deformation Layer": "移动形变层",
    "Move this deformation operation earlier or later": "将此形变操作前移或后移",
    "Up": "上移",
    "Down": "下移",
    "Execute this layer earlier": "让此形变层更早执行",
    "Execute this layer later": "让此形变层更晚执行",
    "This deformation is already enabled": "此形变已启用",
    "Deformation Type": "形变类型",
    "Deformation Types": "形变类型",
    "Deformations": "形变组合",
    "Shape operations combined by this cage": "由当前笼组合执行的形变操作",
    "Enable one or more deformation operations in this cage":
        "在此笼中启用一种或多种形变操作",
    "At least one deformation type must remain enabled":
        "必须至少保留一种已启用的形变类型",
    "Shape operation performed inside the cage": "在笼范围内执行的形态操作",
    "Bend": "弯曲",
    "Curve geometry along the cage axis": "沿笼轴线弯曲几何体",
    "Twist": "扭曲",
    "Rotate cross-sections around the cage axis": "让横截面围绕笼轴线旋转",
    "Taper": "锥化",
    "Scale cross-sections along the cage axis": "沿笼轴线缩放横截面",
    "Stretch": "拉伸",
    "Scale geometry along the cage axis": "沿笼轴线缩放几何体",
    "Angle": "角度",
    "Total Bend or Twist angle through the cage length": "贯穿笼长度的弯曲或扭转总角度",
    "Bend Strength": "弯曲角度",
    "Bend angle through the cage length": "贯穿笼长度的弯曲角度",
    "Bend Angle": "弯曲角度",
    "Total Bend angle through the cage length": "贯穿笼长度的弯曲总角度",
    "Twist Strength": "扭曲角度",
    "Twist angle through the cage length": "贯穿笼长度的扭曲角度",
    "Twist Angle": "扭曲角度",
    "Total Twist angle through the cage length": "贯穿笼长度的扭曲总角度",
    "Taper Factor": "锥化系数",
    "Amount of taper along the cage axis": "沿笼轴向的锥化量",
    "Cross-section scale change through the cage length":
        "贯穿笼长度的横截面缩放变化量",
    "Stretch Factor": "拉伸系数",
    "Amount of stretch along the cage axis": "沿笼轴向的拉伸量",
    "Length scale change through the cage": "贯穿笼长度的轴向缩放变化量",
    "Factor": "系数",
    "Amount used by Taper and Stretch": "锥化和拉伸所使用的形变量",
    "Direction": "方向",
    "Direction of Bend around the cage axis": "围绕笼轴线的扭转角度",
    "Mode": "范围模式",
    "How geometry outside the cage is handled": "决定如何处理笼外的几何体",
    "Limited": "受限",
    "Deform inside; continue outside from the cage ends":
        "笼内形变，笼外从两端延续末端趋势",
    "Within Box": "框内",
    "Only points inside the cage are affected": "只影响笼内的点",
    "Unlimited": "无限",
    "Continue deformation beyond the cage": "将形变连续延伸到笼外",
    "Origin": "起点",
    "Starting pattern of the deformation": "形变的起始方式",
    "Bottom": "底部",
    "Start at the lower cage boundary": "从笼的下边界开始",
    "Center": "中心",
    "Use signed distance from the cage center": "以笼中心的有符号距离作为起点",
    "Symmetric": "对称",
    "Mirror the deformation profile across the center": "让形变轮廓以中心镜像",
    "Top": "顶部",
    "Start at the upper cage boundary": "从笼的上边界开始",
    "Preserve Volume": "维持体积",
    "Compensate cross-section size while stretching": "拉伸时补偿横截面尺寸",
    "Cage Controls": "笼控制",
    "Deform Axis": "形变轴",
    "Target axis used when aligning and fitting the cage": "对齐和适配笼时使用的目标轴",
    "Size": "尺寸",
    "Dimensions of the independent deformation cage": "独立形变笼的尺寸",
    "Auto": "自动",
    "Use the longest local dimension": "使用最长的局部尺寸",
    "Align & Fit": "对齐并适配",
    "Align & Fit Chain": "对齐并适配链式笼",
    "Fit to Object": "适配物体",
    "Fit the active cage, or its entire connected chain, to the geometry entering the deformation":
        "将当前笼或其整条相连链式笼适配到进入形变的几何体",
    "Select Cage": "选择笼",
    "Select Cage Controller": "选择笼控制器",
    "Return to Object": "返回物体",
    "Select the object controlled by this deformation cage": "选择此形变笼所控制的物体",
    "Edit Cage": "编辑笼",
    "Select the cage controller and activate a transform tool":
        "选择笼控制器并启用变换工具",
    "Move": "移动",
    "Move the deformation cage": "移动形变笼",
    "Rotate": "旋转",
    "Rotate and aim the deformation cage": "旋转形变笼并确定朝向",
    "Scale": "缩放",
    "Resize the deformation cage": "调整形变笼尺寸",
    "Show Cage": "显示笼",
    "Draw the cyan cage and orange deformation guide": "显示青色笼和橙色形变引导线",
    "Show Axis Switch": "显示轴向切换",
    "Show bend-trend choices around the cage; the choices hide after selection unless Ctrl is held":
        "在笼体周围显示弯曲趋势选项；选择后自动隐藏，按住 Ctrl 可保持显示",
    "Show Bend Direction Handle": "显示扭转角度手柄",
    "Show a separate ring for adjusting the Bend direction":
        "显示用于调整扭转角度的独立圆环",
    "Axis Switch": "轴向切换",
    "Direction Ring": "方向圆环",
    "Bend Trend": "弯曲趋势",
    "Fine Direction": "精细方向",
    "Helper objects stay hidden until cage transform":
        "辅助物体默认隐藏，仅在变换笼时显示",
    "Numeric Controls": "数值控制",
    "Show exact cage size, location, and rotation values":
        "显示精确的笼尺寸、位置和旋转数值",
    "Independent Ends": "独立端部",
    "Show separate top and bottom cross-section controls":
        "显示顶部和底部的独立横截面控制",
    "Top Scale": "顶部缩放",
    "Scale the top cage cross-section without changing the bottom":
        "只缩放笼的顶部横截面，不改变底部",
    "Bottom Scale": "底部缩放",
    "Scale the bottom cage cross-section without changing the top":
        "只缩放笼的底部横截面，不改变顶部",
    "Top Offset": "顶部偏移",
    "Move the top cage cross-section without changing the bottom":
        "只移动笼的顶部横截面，不改变底部",
    "Bottom Offset": "底部偏移",
    "Move the bottom cage cross-section without changing the top":
        "只移动笼的底部横截面，不改变顶部",
    "Offset": "偏移",
    "Show Shape Handles": "显示端面塑形手柄",
    "Show separate top and bottom cross-section shaping handles":
        "显示顶部和底部的独立横截面塑形手柄",
    "Show Length Handles": "显示长度手柄",
    "Show handles that independently move a cage end or a Curve effect boundary":
        "显示可独立移动笼端部或曲线作用边界的手柄",
    "Show handles that move the top or bottom cage boundary independently":
        "显示可独立移动笼顶部或底部边界的手柄",
    "Limit to Object Bounds": "限制在物体边界内",
    "Prevent the top and bottom cage or Curve effect boundaries from moving beyond the input object's bounds":
        "防止顶部和底部笼边界或曲线作用边界超出输入物体范围",
    "Prevent the top and bottom cage boundaries from moving beyond the input object's bounds":
        "防止顶部和底部笼边界超出输入物体的边界",
    "Length handles stop at the object bounds":
        "长度手柄不会越过物体边界",
    "Outer length handles stop at the object bounds":
        "首尾长度手柄不会越过物体边界",
    "Reset Independent Ends": "重置独立端部",
    "Restore both cage ends to the fitted cross-section":
        "将笼的两个端部恢复为适配时的横截面",
    "Cyan top / green bottom: drag one end only":
        "青色顶部 / 绿色底部：仅拖动一个端部",
    "Top End Shape": "顶部端面形态",
    "Bottom End Shape": "底部端面形态",
    "Yellow top / amber bottom: move one boundary":
        "黄色顶部 / 琥珀色底部：仅移动一个边界",
    "Top Boundary": "顶部边界",
    "Bottom Boundary": "底部边界",
    "Shared Boundary": "共享边界",
    "Cage Length": "笼长度",
    "Effect Range Length": "作用范围长度",
    "Interior boundaries resize both neighboring cages":
        "内部边界会联动调整相邻两个笼的长度",
    "Interior boundaries adjust cage length and gap without overlap":
        "内部边界会调整笼长度和间隔，并避免相互交叉",
    "Drag Along Cage • Shift Precise • Ctrl Snap":
        "沿笼方向拖动 • Shift 精细调整 • Ctrl 吸附",
    "Alt Slide X • Shift Precise • Ctrl Snap":
        "Alt 沿 X 移动 • Shift 精细调整 • Ctrl 吸附",
    "Location": "位置",
    "Rotation": "旋转",
    "Orange handle: drag Angle": "橙色手柄：拖动角度",
    "Orange handle: drag Factor": "橙色手柄：拖动系数",
    "Alt Direction • Shift Precise • Ctrl Snap":
        "Alt 调整方向 • Shift 精细调整 • Ctrl 吸附",
    "Shift Precise • Ctrl Snap": "Shift 精细调整 • Ctrl 吸附",
    "Drag Around Ring • Shift Precise • Ctrl Snap":
        "环绕圆环拖动 • Shift 精细调整 • Ctrl 吸附",
    "Drag Along Axis • Shift Precise • Ctrl Snap":
        "沿轴向拖动 • Shift 精细调整 • Ctrl 吸附",
    "Bend Direction": "扭转角度",
    "Set Bend Trend": "设置弯曲趋势",
    "Choose Bend Trend": "选择弯曲趋势",
    "Choose a signed cage axis and one of its two perpendicular bend trends; hold Ctrl to keep all choices visible":
        "选择笼的正负轴向及对应的两种正交弯曲趋势；按住 Ctrl 可保持全部选项显示",
    "Switch Cage Axis": "切换笼轴向",
    "Axis switch: RGB is X/Y/Z; diamond is +, ring is -":
        "轴向切换：RGB 对应 X/Y/Z；菱形为正向，圆环为负向",
    "Orange double arrow: drag Bend angle":
        "橙色双向箭头：拖动弯曲角度",
    "Small orange double arrow: drag Bend direction":
        "小型橙色双向箭头：拖动扭转角度",
    "Large purple twist arc: drag around its center":
        "大型紫色扭转弧：围绕中心拖动",
    "Red / green arrows: horizontal / vertical bend trend":
        "红色 / 绿色箭头：横向 / 竖向弯曲趋势",
    "Click to choose and close • Ctrl keeps choices open":
        "点击选择并收起 • 按住 Ctrl 保持选项显示",
    "Amber taper handle: drag Factor": "琥珀色锥化手柄：拖动系数",
    "Green stretch handle: drag Factor": "绿色拉伸手柄：拖动系数",
    "Set Deform Axis": "设置形变轴",
    "Align the cage axis and fit it to the current stage input":
        "对齐笼轴线并适配当前阶段输入",
    "Show Toggle Bend Axis Gizmo": "显示切换弯曲轴向Gizmo",
    "AIGODLIKE Community:小萌新": "AIGODLIKE社区,小萌新",
    "AIGODLIKE": "辣椒出品",
    "Gizmo Property Show Location": "Gizmo属性显示位置",
    "You can press the following shortcut keys when dragging values":
        "拖动值时可以按以下快捷键",
    "    Wheel:   Switch Origin Ctrl Mode":
        "    滚轮:   切换原点控制模式",
    "    X,Y,Z:  Switch Modifier Deform Axis":
        "    X,Y,Z:  切换修改器型变轴",
    "    W:       Switch Deform Wireframe Show":
        "    W:       切换形变线框显示",

    "    A:       Switch To Select Bend Axis Mode(deform_method=='BEND')":
        "    A:       切换到选择弯曲轴模式(形变方法='弯曲')",
    "Show Set Axis Button": "显示设置轴向Gizmo",
    "Follow Upper Limit(Red)": "跟随上限(红色)",
    "Follow Lower Limit(Green)": "跟随下限(绿色)",
    "Lower limit(Green)": "下限(绿色)",
    "UP Limits(Red)": "上限(红色)",
    "Show Deform Wireframe": "显示形变线框",

    "Minimum value between upper and lower limits": "上限与下限之间的最小值",
    "Upper and lower limit tolerance": "上下限容差",

    "Draw Upper and lower limit Bound Box Color": "绘制网格上限下限边界线框的颜色",
    "Upper and lower limit Bound Box Color": "上限下限边界框颜色",
    "Draw Bound Box Color": "绘制网格边界框的颜色",
    "Bound Box": "边界框颜色",
    "Draw Deform Wireframe Color": "绘制网格形变形状线框的颜色",
    "Deform Wireframe": "形变线框颜色",

    "Simple Deform visualization adjustment tool": "简易形变可视化工具",

    "Select an object and the active modifier is Simple Deform":
        "选择物体并且活动修改器为简易形变",
    "Bound Middle": "边界框中心",
    origin_text(not_add, "as the lower limit"):
        "添加一个空物体原点作为旋转轴(如果已有原点则不添加),并在操作时设置原点位置为下限位置",
    origin_text(not_add, "as the upper limit"):
        "添加一个空物体原点作为旋转轴(如果已有原点则不添加),并在操作时设置原点位置为上限位置",
    origin_text("it will not be added",
                "between the upper and lower limits"):
        "添加一个空物体原点作为旋转轴(如果已有原点则不添加),并在操作时设置原点位置为上下限之间的位置",
    origin_text(not_add,
                "as the position between the bounding boxes"):
        "添加一个空物体原点作为旋转轴(如果已有原点则不添加),并在操作时设置原点位置为边界框之间的位置",
    "No origin operation": "不进行原点操作",
    "Origin control mode": "原点控制模式",
    "Down limit": "下限",
    "Coefficient": "系数",
    "Up limit": "上限",
    "Upper limit": "上限",

    "3D View -> Select an object and the active modifier is simple "
    "deformation": "3D视图 -> 选择一个物体,"
                   "并且活动修改器为简易形修改器",

    "3D View: Simple Deform Helper": "3D 视图: Simple Deform Helper 简易形变助手",
    "Simple Deform Helper": "简易形变助手",
    "Tool Options": "工具选项",
    "The scaling value of the object is not 1": "对象的缩放值不是1",

    "which will cause the deformation of the simple deformation "
    "modifier.": "这将导致简易形变修改器变形",
    "Please apply the scaling before deformation.": "请应用缩放",
    "Z Rotate": "Z扭转",
    "Simple Deform Animated": "简易形变动画",
    "Simple Deform Property": "简易形变属性",
    "Insert Keyframe": "插入关键帧",
    "Remove Keyframe": "删除关键帧",
    "Show Simple Deform Gizmo": "显示简易形变 Gizmo",
    "Simple Deform Stack": "简易形变堆栈",
    "Show Other Simple Deform Stages": "显示其它简易形变阶段",
    "Draw faint input bounds for other Simple Deform modifiers":
        "绘制其它简易形变修改器的低透明度输入边界",
    "Show Drag Shortcuts in Header": "在顶部显示拖动快捷键",
    "Warn About Low Topology": "低拓扑警告",
    "Warn when the active deformation axis has too few geometry points":
        "活动形变轴上的几何点过少时显示警告",
    "Wireframe Preview FPS": "线框预览帧率",
    "Maximum refresh rate for the optional deformed wireframe preview":
        "可选形变线框预览的最高刷新率",
    "User Origin is protected": "用户 Origin 已受保护",
    "Follow-limit Origin modes are disabled.": "已禁用跟随限制的 Origin 模式。",
    "Simple Deform needs more segments to bend smoothly.":
        "简易形变需要更多分段才能平滑弯曲。",
    "Add Subdivision Before Deform": "在形变前添加细分",
    "Add a Subdivision Surface modifier before the active deformation stage "
    "so bending has enough segments":
        "在当前形变阶段之前添加表面细分修改器，让弯曲有足够的分段",
    "Simple Subdivision": "简单型细分",
    "Add straight loop cuts without smoothing": "只添加环切，不做平滑",
    "Smooth while subdividing": "细分的同时进行平滑（Catmull-Clark）",
    "Subdivision was added at the end; move it before the deformation stage":
        "细分已添加到堆栈末尾；请手动移到形变阶段之前",
    "Current cage Geometry Nodes modifier is not selected":
        "当前笼几何节点未被选中",
    "Select a stage above to edit its cage controls.":
        "在上方形变堆栈中选择一个阶段，即可编辑它的笼控制。",
    "Create": "创建",
    "Add a non-destructive subdivision modifier before the active Simple Deform":
        "在活动简易形变之前添加非破坏性细分修改器",
    "Switch Simple Deform Stage": "切换简易形变阶段",
    "Make the previous or next Simple Deform modifier active":
        "将上一个或下一个简易形变修改器设为活动项",
    "Multi-Object Deform": "多物体形变",
    "Merge Selected for Deform": "合并选中对象用于形变",
    "Create one live mesh from selected objects; non-mesh sources are converted to meshes":
        "从选中对象创建一个实时合并网格；非网格来源会转换为网格",
    "Select at least two supported objects": "请至少选择两个受支持的对象",
    "One or more selected objects cannot be converted": "一个或多个选中对象无法转换",
    "Could not convert {name} to a mesh": "无法将 {name} 转换为网格",
    "{name} already belongs to a deformation merge": "{name} 已属于一个形变合并体",
    "Merged {count} objects for deformation": "已合并 {count} 个对象用于形变",
    "Edit Merged Source": "编辑合并来源",
    "Select the source under the pointer from a deformation merge":
        "从形变合并体中选择指针下方的来源对象",
    "Click a merged part to switch source | Double-click blank to return | Esc or Right Mouse exits":
        "单击合并体部件切换来源 | 双击空白处返回合并体 | Esc 或鼠标右键退出",
    "Editing merged source: {name}": "正在编辑合并来源：{name}",
    "Select this source while keeping the merged result visible":
        "选择此来源并保持合并结果可见",
    "Return to Merged Object": "返回合并体",
    "Hide the editable source and select its deformation merge":
        "隐藏正在编辑的来源并选择其形变合并体",
    "Unmerge and Restore Sources": "取消合并并恢复来源",
    "Restore source visibility and remove the generated merged object":
        "恢复来源对象的可见性并移除生成的合并体",
    "Restored sources from {name}": "已从 {name} 恢复来源对象",
    "Editing Source": "正在编辑来源",
    "Merged Sources": "合并来源",
    "Merged Geometry": "合并几何",
    "Join Sources": "合并来源",
    "World Transform": "世界变换",
    "Source Index": "来源索引",
    "Active Merged Source": "活动合并来源",
    "Active source row in the multi-object deformation list":
        "多物体形变列表中的活动来源行",
    "(Missing source)": "（来源缺失）",
    "Show Final Merged State While Editing Sources":
        "编辑来源时显示最终合并状态",
    "Display the selected source after the merged object's full modifier stack":
        "显示经过合并对象完整修改器堆栈后的所选来源",
    "Add Cage to Final Source": "向最终态来源添加笼",
    "Add a cage that affects only the selected source after the merged object's current modifier stack":
        "在合并对象当前修改器堆栈之后添加仅影响所选来源的笼",
    "The selected source has no evaluated surface geometry":
        "所选来源没有可求值的表面几何",
    "Could not configure the source cage filter": "无法配置来源笼遮罩",
    "{name} Final Cage": "{name} 最终态笼",
    "Final Source Filter": "最终态来源过滤",
    "Merged Source Index": "合并来源索引",
    "Source = {index}": "来源 = {index}",
    "Existing Source and Matching Index": "来源存在且索引匹配",
    "Return": "返回",
    "Click a merged part to edit or switch source":
        "单击合并体部件以编辑或切换来源",
    "Double-click blank to return | Esc or Right Mouse exits":
        "双击空白处返回 | Esc 或鼠标右键退出",
}


def _localized_catalog(overrides):
    """Use English source text for untranslated long-tail entries."""
    catalog = {source: source for source in translations_dict}
    catalog.update(overrides)
    return catalog


translations_ja_JP = _localized_catalog({
    "Insert Cage Keyframes": "\u30b1\u30fc\u30b8\u30ad\u30fc\u30d5\u30ec\u30fc\u30e0\u3092\u633f\u5165",
    "Delete Cage Keyframes": "\u30b1\u30fc\u30b8\u30ad\u30fc\u30d5\u30ec\u30fc\u30e0\u3092\u524a\u9664",
    "Insert Keys": "\u30ad\u30fc\u3092\u633f\u5165",
    "Delete Keys": "\u30ad\u30fc\u3092\u524a\u9664",
    "Inserted {count} FFD control-point keyframe channels":
        "FFD \u5236\u5fa1\u70b9\u306b {count} \u500b\u306e\u30ad\u30fc\u30d5\u30ec\u30fc\u30e0\u30c1\u30e3\u30f3\u30cd\u30eb\u3092\u633f\u5165",
    "Removed {count} FFD control-point keyframe channels":
        "FFD \u5236\u5fa1\u70b9\u306e {count} \u500b\u306e\u73fe\u5728\u30d5\u30ec\u30fc\u30e0\u30ad\u30fc\u3092\u524a\u9664",
    "Key the active cage parameters, end profiles, FFD control points, and cage transform on the current frame":
        "\u73fe\u5728\u306e\u30b1\u30fc\u30b8\u30d1\u30e9\u30e1\u30fc\u30bf\u3001\u7aef\u90e8\u5f62\u72b6\u3001FFD \u5236\u5fa1\u70b9\u3001\u30b1\u30fc\u30b8\u5909\u63db\u3092\u30ad\u30fc\u5316",
    "Delete the current-frame keys created for the active cage":
        "\u73fe\u5728\u306e\u30b1\u30fc\u30b8\u306b\u4f5c\u6210\u3057\u305f\u73fe\u5728\u30d5\u30ec\u30fc\u30e0\u306e\u30ad\u30fc\u3092\u524a\u9664",
    "Inserted {count} cage keyframe channels": "{count} \u500b\u306e\u30b1\u30fc\u30b8\u30ad\u30fc\u30d5\u30ec\u30fc\u30e0\u30c1\u30e3\u30f3\u30cd\u30eb\u3092\u633f\u5165",
    "Removed {count} cage keyframe channels": "{count} \u500b\u306e\u30b1\u30fc\u30b8\u30ad\u30fc\u30d5\u30ec\u30fc\u30e0\u30c1\u30e3\u30f3\u30cd\u30eb\u3092\u524a\u9664",
    "Alt: Screen X | Shift: Screen Y | Alt+Shift: Free | Ctrl: Snap":
        "Alt: \u753b\u9762 X | Shift: \u753b\u9762 Y | Alt+Shift: \u81ea\u7531 | Ctrl: \u30b9\u30ca\u30c3\u30d7",
    "Added cage to the final state of {name}": "{name} の最終状態にケージを追加しました",
    "Rotation Mode": "回転モード",
    "Previous": "前へ",
    "Next": "次へ",
    "Select the previous Simple Deform modifier": "前の Simple Deform 修正子を選択",
    "Select the next Simple Deform modifier": "次の Simple Deform 修正子を選択",
    "Earlier": "前に移動",
    "Later": "後に移動",
    "Tool Settings": "ツール設定",
    "In Front": "前面に表示",
    "Show Gizmo": "ギズモを表示",
    "Stage Index": "ステージ番号",
    "Active Deformation Layer": "アクティブな変形レイヤー",
    "Muted Deformations": "ミュートされた変形",
    "Original Origin": "元の原点",
    "Origin Object Rotate Angle": "原点オブジェクトの回転角度",
    "Origin Object Rotate Axis": "原点オブジェクトの回転軸",
    "Expand every deformation layer in the cage UI": "ケージ UI ですべての変形レイヤーを展開",
    "Persistent execution order for the enabled deformation layers": "有効な変形レイヤーの実行順を保持",
    "Index of the deformation layer selected in the cage UI": "ケージ UI で選択中の変形レイヤーのインデックス",
    "Present deformation layers temporarily bypassed by this cage": "このケージが一時的にバイパスしている既存の変形レイヤー",
    "Temporarily bypass Bend": "曲げを一時的にバイパス",
    "Temporarily bypass Twist": "ねじりを一時的にバイパス",
    "Temporarily bypass Taper": "テーパーを一時的にバイパス",
    "Temporarily bypass Stretch": "伸縮を一時的にバイパス",
    "Move before the previous Cage Deform": "前のケージ変形の前へ移動",
    "Move after the next Cage Deform": "次のケージ変形の後へ移動",
    "Key the active strength, limits, and managed Origin controls": "アクティブな強度・制限・管理原点のコントロールにキーを挿入",
    "Remove the current-frame keys created for the active Simple Deform": "アクティブな Simple Deform 用に作成した現在フレームのキーを削除",
    "Create a managed Origin and keep it at the upper limit while dragging": "管理原点を作成し、ドラッグ中は上限に固定",
    "Create a managed Origin and keep it at the lower limit while dragging": "管理原点を作成し、ドラッグ中は下限に固定",
    "Create a managed Origin between the upper and lower limits": "上限と下限の間に管理原点を作成",
    "Create a managed Origin at the deformation bounds center": "変形境界の中央に管理原点を作成",
    "Middle": "中央",
    "Stage {stage_index} of {stage_count}: {modifier}": "ステージ {stage_index}/{stage_count}: {modifier}",
    "Deform {stage_index}/{stage_count}": "変形 {stage_index}/{stage_count}",
    "Low topology on {axis}: {sample_count} levels": "{axis} 軸のトポロジーが低い: {sample_count} レベル",
    "Animated": "アニメーション",
    "Property": "プロパティ",
    "01 Local Space": "01 ローカル空間",
    "02 Cage Profile": "02 ケージプロファイル",
    "07 Mode and Output": "07 モードと出力",
    "Subdivide to Chained Cages": "チェーンケージへ細分化",
    "Split the active cage inside its current range and distribute its deformation across a chained cage stack": "現在の範囲内でアクティブケージを分割し、変形をチェーンケージスタックへ分配",
    "Number of chained segments inside the current cage range": "現在のケージ範囲内のチェーンセグメント数",
    "Uniform spacing between segments; segment lengths shrink so the original total range is preserved": "セグメント間隔を均一にします。元の総範囲を保つため、各セグメントの長さは短縮されます",
    "Keep each newly-created shared cross-section continuous": "新しく作成する共有断面を連続のまま保つ",
    "The original cage boundaries stay fixed.": "元のケージ境界は固定されたままです。",
    "Bend and Twist angles are distributed across segments.": "曲げとねじりの角度は各セグメントへ分配されます。",
    "Batch Edit": "一括編集",
    "Batch Edit Chain": "チェーンを一括編集",
    "Edit several cages in the active chain as one operation": "アクティブチェーン内の複数ケージを一度に編集",
    "Scope": "範囲",
    "Whole Chain": "チェーン全体",
    "Edit every cage in this chain": "このチェーン内のすべてのケージを編集",
    "Start to Active": "始点からアクティブまで",
    "Edit the chain root through the active cage": "チェーンのルートからアクティブケージまでを編集",
    "Active to End": "アクティブから末端まで",
    "Edit the active cage through the chain tip": "アクティブケージからチェーン末端までを編集",
    "Operation": "操作",
    "End Scale": "端部スケール",
    "Batch-edit top and bottom cross-section scale": "上下断面のスケールを一括編集",
    "End Offset": "端部オフセット",
    "Batch-edit top and bottom cross-section offset": "上下断面のオフセットを一括編集",
    "Set spacing before every cage in scope": "範囲内の各ケージ手前の間隔を設定",
    "Batch-edit one deformation parameter": "変形パラメータを 1 つ一括編集",
    "Deformation": "変形",
    "Stage Visibility": "ステージの表示状態",
    "Apply or bypass every cage in scope": "範囲内の各ケージを適用またはバイパス",
    "Ends": "端部",
    "Edit top ends": "上端部を編集",
    "Edit bottom ends": "下端部を編集",
    "Both": "両端",
    "Edit both ends": "両端を同時に編集",
    "Apply As": "適用方法",
    "Set Values": "値を設定",
    "Replace existing values": "既存の値を置き換え",
    "Add Values": "値を加算",
    "Add to existing values": "既存の値に加算",
    "Multiply Values": "値を乗算",
    "Multiply existing values": "既存の値に乗算",
    "X and Z cross-section values": "断面の X と Z の値",
    "X and Z cross-section offset values": "断面の X と Z のオフセット値",
    "Spacing before each affected downstream cage": "影響を受ける下流ケージ手前の間隔",
    "Preserve Total Range": "総範囲を保持",
    "Shorten each cage as its incoming gap grows": "手前の間隔が増えるにつれて各ケージを短縮",
    "Parameter": "パラメータ",
    "Batch-edit Bend angle": "曲げ角度を一括編集",
    "Batch-edit Bend direction": "曲げ方向を一括編集",
    "Batch-edit Twist angle": "ねじり角度を一括編集",
    "Batch-edit Taper factor": "テーパー係数を一括編集",
    "Batch-edit Stretch factor": "伸縮係数を一括編集",
    "Enable Stages": "ステージを有効化",
    "Apply the affected cage stages": "対象のケージステージを適用",
    "Linked shared boundaries are changed only once.": "連動している共有境界は一度だけ変更されます。",
    "Cages without this deformation layer are skipped.": "この変形レイヤーを持たないケージはスキップされます。",
    "Created {count} cage stages": "{count} 個のケージステージを作成しました",
    "More than 3 cage stages may reduce viewport performance":
        "4個以上のケージステージはビューポート性能を低下させる可能性があります",
    "Could not create cage chain: {error}": "ケージチェーンを作成できませんでした: {error}",
    "Only a single cage can be subdivided": "細分化できるのは単一ケージのみです",
    "Set the cage origin to Bottom before subdividing": "細分化の前にケージの原点を下部に設定してください",
    "Animated cage parameters cannot be subdivided safely": "アニメーション付きケージパラメータは安全に細分化できません",
    "Taper collapses at an interior split boundary": "テーパーは内側の分割境界で潰れてしまいます",
    "Subdivided cage into {count} chained stages": "ケージを {count} 個のチェーンステージへ細分化しました",
    "Subdivided cage into {count} chained stages (gap clamped to preserve range)": "ケージを {count} 個のチェーンステージへ細分化しました（範囲維持のため間隔を制限）",
    "Could not subdivide cage: {error}": "ケージを細分化できませんでした: {error}",
    "Could not batch edit chain: {error}": "チェーンを一括編集できませんでした: {error}",
    "No matching cage values were changed": "一致するケージ値が変更されませんでした",
    "Updated {count} cage stages": "{count} 個のケージステージを更新しました",
    "Fitted {count} cage stages to chain input": "{count} 個のケージステージをチェーン入力に合わせました",
    "No cage chain metadata was found": "ケージチェーンのメタデータが見つかりません",
    "Missing cage stages: {indices}": "不足しているケージステージ: {indices}",
    "Duplicate cage stage indices: {indices}": "重複しているケージステージ番号: {indices}",
    "A non-cage modifier is inserted inside the chain": "チェーン内にケージ以外の修正子が挿入されています",
    "A chain stage has no matching controller": "チェーンステージに対応するコントローラーがありません",
    "Chain stages use different connection modes": "チェーンステージの接続モードが一致しません",
    "Cage chain is broken": "ケージチェーンが切れています",
    "No Cage Chain was found": "ケージチェーンが見つかりません",
    "Reconnected {count} cage stages": "{count} 個のケージステージを再接続しました",
    "Reconnected {count} cage stages and released the subdivision baseline":
        "{count} 個のケージステージを再接続し、細分化ベースラインを解除しました",
    "Add Cage Chain": "ケージチェーンを追加",
    "Number of segments to create": "作成するセグメント数",
    "Connection Mode": "接続モード",
    "How neighboring cage segments handle their boundaries": "隣接ケージセグメントが境界をどう扱うか",
    "The chain root extends continuously beyond both boundaries; later cages preserve the upstream prefix and continue from the cage end": "チェーンのルートは両端境界から連続して延長し、後続ケージは上流側の前段を保持してケージ末端から継続",
    "Limit each segment to its own box": "各セグメントを自身のボックス内に制限",
    "Gap": "間隔",
    "Gap Before": "手前の間隔",
    "Gap from Previous Cage": "前のケージからの間隔",
    "Non-negative distance from the previous cage; changing it keeps the overall chain span when possible": "前のケージからの非負距離。変更時は可能な限りチェーン全体のスパンを維持します",
    "Distance between this cage and the previous cage": "このケージと前のケージの距離",
    "Distance between neighboring cage frames in target units": "隣接ケージフレーム間の距離（ターゲット単位）",
    "Cage Axis": "ケージ軸",
    "Use the longest input dimension": "入力の最長寸法を使用",
    "Align cage Y to target +X": "ケージ Y をターゲット +X に揃える",
    "Align cage Y to target -X": "ケージ Y をターゲット -X に揃える",
    "Align cage Y to target +Y": "ケージ Y をターゲット +Y に揃える",
    "Align cage Y to target -Y": "ケージ Y をターゲット -Y に揃える",
    "Align cage Y to target +Z": "ケージ Y をターゲット +Z に揃える",
    "Align cage Y to target -Z": "ケージ Y をターゲット -Z に揃える",
    "Select a supported target object first": "まず対応するターゲットオブジェクトを選択してください",
    "Add Simple Deform": "Simple Deform を追加",
    "Add Simple Deform (Legacy)": "Simple Deform を追加（従来）",
    "Add a traditional Simple Deform modifier": "従来の Simple Deform 修正子を追加",
    "Added legacy Simple Deform modifier": "従来の Simple Deform 修正子を追加しました",
    "Cage deformation is not supported for lattice objects": "ラティスオブジェクトではケージ変形に対応していません",
    "The selected surface could not be converted for cage deformation": "選択したサーフェスをケージ変形用に変換できませんでした",
    "Surface cage deformation requires a mesh conversion": "サーフェスのケージ変形にはメッシュへの変換が必要です",
    "Add Chained Cages": "チェーンケージを追加",
    "Create Cage Chain": "ケージチェーンを作成",
    "Create several related deformation cages in one operation": "関連する複数の変形ケージを一度に作成",
    "Cage Count": "ケージ数",
    "Use isolated boxes": "各ボックス内のジオメトリのみに影響",
    "Number of chained cages to create": "作成するチェーンケージ数",
    "Connect Ends": "端部を接続",
    "Align each cage bottom to the previous cage top": "各ケージの下端を前のケージの上端に揃える",
    "Chain Mode": "チェーンモード",
    "Use forward continuation when available": "可能な場合は前方への連続を使用",
    "Create stages without automatic reconnection": "自動再接続なしでステージを作成",
    "Chained": "チェーン",
    "Independent": "独立",
    "Segment": "セグメント",
    "Enable Stage": "ステージを有効化",
    "Temporarily apply or bypass this cage while preserving chained-stage flow": "チェーンステージの流れを保ったまま、このケージを一時的に適用またはバイパス",
    "Show Other Cages": "他のケージを表示",
    "Display inactive cages and make their viewport controls directly editable": "非アクティブケージを表示し、ビューポートコントロールを直接編集可能にする",
    "Show Other Cage Controllers": "他のケージコントローラーを表示",
    "Display all cage controllers except active one": "アクティブ以外のすべてのケージコントローラーを表示",
    "Active Cage": "アクティブケージ",
    "Inactive Cage": "非アクティブケージ",
    "Active cage is highlighted; other cages are dimmed": "アクティブケージは強調表示され、他のケージは暗くなります",
    "Select this cage stage and its controller": "このケージステージとそのコントローラーを選択",
    "Select Cage Stage": "ケージステージを選択",
    "Select Deformation Stage": "変形ステージを選択",
    "Make this cage or traditional Simple Deform stage active":
        "このケージまたは従来の Simple Deform ステージをアクティブにする",
    "Cage Deform Strength Handle": "ケージ変形の強度ハンドル",
    "Cage End Shape": "ケージ端部の形状",
    "Cage Boundary": "ケージ境界",
    "Auto Reconnect Chain": "チェーンを自動再接続",
    "Automatically refresh downstream cage frames after a chain parameter or controller transform changes": "チェーンパラメータやコントローラーのトランスフォーム変更後、下流のケージフレームを自動更新",
    "Auto Reconnect": "自動再接続",
    "Refresh downstream cage frames after upstream edits": "上流の編集後に下流ケージフレームを更新",
    "Use one-sided continuation": "片側連続を使用",
    "Propagate each preceding cage output frame to the next cage": "直前ケージの出力フレームを次のケージへ伝播",
    "Reconnect Broken Chain": "切れたチェーンを再接続",
    "Attempt contiguous stages even when a stack issue is detected": "スタックの問題が検出されても連続ステージを試行",
    "Cage Deform core is unavailable": "ケージ変形コアを利用できません",
    "Chained Cages": "チェーンケージ",
    "Independent Cage Chain": "独立ケージチェーン",
    "Reconnect Chain": "チェーンを再接続",
    "Reconnect Cage Chain": "ケージチェーンを再接続",
    "Align each cage to the previous cage's output frame": "各ケージを前のケージの出力フレームに揃える",
    "Each stage keeps its own angle and length; reconnect updates the incoming frame.": "各ステージは自身の角度と長さを保持します。再接続は入力フレームのみ更新します。",
    "Each stage keeps its deformations, length, and incoming gap.": "各ステージは自身の変形・長さ・手前の間隔を保持します。",
    "Sync Shared End Scale": "共有端部スケールを同期",
    "Allow Approximate Mixed Bend": "混在ベンドの近似細分化を許可",
    "Allow subdivision of stacks containing Bend with other types; the operations do not commute and the result may differ":
        "ベンドと他の種類を含むスタックの近似細分化を許可します。操作は可換ではないため結果が異なる場合があります",
    "Mixed Bend stacks are protected because deformation order is non-commutative; enable Allow Approximate Mixed Bend to continue":
        "変形順序が可換ではないため、ベンド混在スタックを保護しました。続行するには「混在ベンドの近似細分化を許可」を有効にしてください",
    "Scale both sides of each shared cage seam together while keeping each outer end independent": "各共有ケージ継ぎ目の両側スケールを同期し、外側端部はそれぞれ独立のままにする",
    "Scale both sides of each shared cage seam together while keeping outer ends independent": "各共有ケージ継ぎ目の両側スケールを同期し、外側端部は独立のままにする",
    "Only neighboring seam-end scales are synchronized.": "隣接する継ぎ目端部のスケールのみが同期されます。",
    "Outer cage ends remain independent.": "外側のケージ端部は独立したままです。",
    "Chained mode starts at the lower cage boundary.": "チェーンモードはケージ下端境界から開始します。",
    "Cage Chain mode is locked to Chained.": "ケージチェーンモードはチェーンに固定されています。",
    "Simple Deformer": "シンプル変形器",
    "Simple Deformer V2": "シンプル変形器 V2",
    "Add New Cages to End": "新規ケージをスタック末尾へ追加",
    "Place newly-created cage stages at the end of the modifier stack": "新規ケージステージを修正子スタックの末尾に配置",
    "Cage Deform": "ケージ変形",
    "Add Cage Deform": "ケージ変形を追加",
    "Add an independent cage deformation stage": "独立したケージ変形ステージを追加",
    "Added Cage Deform stage": "ケージ変形ステージを追加しました",
    "Deform axis changed; the user-supplied Origin was preserved": "変形軸を変更しました。ユーザー指定の原点は保持されています",
    "Subdivision was added at the end; move it before Simple Deform": "細分化が末尾に追加されました。Simple Deform の前へ移動してください",
    "Inserted {inserted} Simple Deform keyframe channels": "{inserted} 個の Simple Deform キーフレームチャンネルを挿入しました",
    "Removed {removed} Simple Deform keyframe channels": "{removed} 個の Simple Deform キーフレームチャンネルを削除しました",
    "Independent cage deformation": "独立ケージ変形",
    "Bend, Twist, Taper, and Stretch.": "曲げ、ねじり、テーパー、伸縮に対応。",
    "Combine Bend, Twist, Taper, and Stretch in one cage.": "1 つのケージで曲げ・ねじり・テーパー・伸縮を組み合わせられます。",
    "Cage Stack": "ケージスタック",
    "Deformation Stack": "変形スタック",
    "Move Cage Stage": "ケージステージを移動",
    "Move Deformation Stage": "変形ステージを移動",
    "Move before the previous deformation stage": "前の変形ステージより前へ移動",
    "Move after the next deformation stage": "次の変形ステージより後へ移動",
    "Move this deformation earlier or later in the modifier stack": "修正子スタック内でこの変形を前後に移動",
    "Duplicate Cage Stage": "ケージステージを複製",
    "Duplicate": "複製",
    "Remove Cage Stage": "ケージステージを削除",
    "Remove Deformation Stage": "変形ステージを削除",
    "Remove this deformation stage and any owned controls":
        "この変形ステージと所有するコントロールを削除",
    "Remove Stage": "ステージを削除",
    "Remove Cage Stack": "ケージスタックを削除",
    "Remove Deformation Stack": "変形スタックを削除",
    "Remove every managed cage and traditional Simple Deform stage":
        "すべての管理ケージと従来の Simple Deform ステージを削除",
    "Remove": "削除",
    "Remove this managed deformation stage and its cage controller": "この管理変形ステージとそのケージコントローラーを削除",
    "Remove every managed cage stage and its owned controllers": "すべての管理ケージステージと所有コントローラーを削除",
    "Shape": "形状",
    "Deformation Layers": "変形レイヤー",
    "Expand All": "すべて展開",
    "Add Deformation": "変形を追加",
    "Add Deformation Layer": "変形レイヤーを追加",
    "Add one deformation operation to this cage": "このケージに変形操作を 1 つ追加",
    "Select Deformation Layer": "変形レイヤーを選択",
    "Select this deformation layer without changing its evaluation": "評価状態を変えずにこの変形レイヤーを選択",
    "Remove Deformation Layer": "変形レイヤーを削除",
    "Remove this deformation operation from the cage": "このケージから変形操作を削除",
    "Toggle Deformation Layer": "変形レイヤーの有効状態を切替",
    "Temporarily bypass or restore this deformation without losing its settings": "設定を失わずにこの変形を一時バイパスまたは復元",
    "Move Deformation Layer": "変形レイヤーを移動",
    "Move this deformation operation earlier or later": "この変形操作を前後に移動",
    "Up": "上へ",
    "Down": "下へ",
    "Execute this layer earlier": "このレイヤーをより早く実行",
    "Execute this layer later": "このレイヤーをより遅く実行",
    "This deformation is already enabled": "この変形はすでに有効です",
    "Deformation Type": "変形タイプ",
    "Deformation Types": "変形タイプ",
    "Deformations": "変形",
    "Shape operations combined by this cage": "このケージが組み合わせる形状操作",
    "Enable one or more deformation operations in this cage": "このケージで 1 つ以上の変形操作を有効化",
    "At least one deformation type must remain enabled": "少なくとも 1 つの変形タイプを有効のままにする必要があります",
    "Shape operation performed inside the cage": "ケージ内で行う形状操作",
    "Bend": "曲げ",
    "Curve geometry along the cage axis": "ケージ軸に沿ってジオメトリを曲げる",
    "Twist": "ねじり",
    "Rotate cross-sections around the cage axis": "断面をケージ軸まわりに回転",
    "Taper": "テーパー",
    "Scale cross-sections along the cage axis": "ケージ軸に沿って断面をスケール",
    "Stretch": "伸縮",
    "Scale geometry along the cage axis": "ケージ軸に沿ってジオメトリをスケール",
    "Angle": "角度",
    "Total Bend or Twist angle through the cage length": "ケージ全長にわたる曲げまたはねじりの合計角度",
    "Bend Strength": "曲げの強さ",
    "Bend angle through the cage length": "ケージ全長にわたる曲げ角度",
    "Bend Angle": "曲げ角度",
    "Total Bend angle through the cage length": "ケージ全長にわたる曲げの合計角度",
    "Twist Strength": "ねじりの強さ",
    "Twist angle through the cage length": "ケージ全長にわたるねじり角度",
    "Twist Angle": "ねじり角度",
    "Total Twist angle through the cage length": "ケージ全長にわたるねじりの合計角度",
    "Taper Factor": "テーパー係数",
    "Amount of taper along the cage axis": "ケージ軸に沿ったテーパー量",
    "Cross-section scale change through the cage length": "ケージ全長にわたる断面スケールの変化量",
    "Stretch Factor": "伸縮係数",
    "Amount of stretch along the cage axis": "ケージ軸に沿った伸縮量",
    "Length scale change through the cage": "ケージにわたる長さスケールの変化量",
    "Factor": "係数",
    "Amount used by Taper and Stretch": "テーパーと伸縮で使う量",
    "Direction": "方向",
    "Direction of Bend around the cage axis": "ケージ軸まわりの曲げ方向",
    "Mode": "モード",
    "How geometry outside the cage is handled": "ケージ外ジオメトリの扱い方",
    "Limited": "制限",
    "Deform inside; continue outside from the cage ends": "内側を変形し、外側はケージ端部から継続",
    "Within Box": "ボックス内",
    "Only points inside the cage are affected": "ケージ内の点のみ影響を受けます",
    "Unlimited": "無制限",
    "Continue deformation beyond the cage": "ケージを超えて変形を継続",
    "Origin": "原点",
    "Starting pattern of the deformation": "変形の開始パターン",
    "Bottom": "下部",
    "Start at the lower cage boundary": "ケージ下端境界から開始",
    "Center": "中心",
    "Use signed distance from the cage center": "ケージ中心からの符号付き距離を使用",
    "Symmetric": "対称",
    "Mirror the deformation profile across the center": "変形プロファイルを中心でミラー",
    "Top": "上部",
    "Start at the upper cage boundary": "ケージ上端境界から開始",
    "Preserve Volume": "体積を維持",
    "Compensate cross-section size while stretching": "伸縮時に断面サイズを補正",
    "Cage Controls": "ケージコントロール",
    "Deform Axis": "変形軸",
    "Target axis used when aligning and fitting the cage": "ケージの整列とフィットに使うターゲット軸",
    "Size": "サイズ",
    "Dimensions of the independent deformation cage": "独立変形ケージの寸法",
    "Auto": "自動",
    "Use the longest local dimension": "最長のローカル寸法を使用",
    "Align & Fit": "整列してフィット",
    "Align & Fit Chain": "チェーンを整列してフィット",
    "Fit to Object": "オブジェクトに合わせる",
    "Fit the active cage, or its entire connected chain, to the geometry entering the deformation": "アクティブケージ、または接続されたチェーン全体を、変形へ入るジオメトリに合わせる",
    "Select Cage": "ケージを選択",
    "Select Cage Controller": "ケージコントローラーを選択",
    "Return to Object": "オブジェクトに戻る",
    "Select the object controlled by this deformation cage": "この変形ケージが制御するオブジェクトを選択",
    "Edit Cage": "ケージを編集",
    "Select the cage controller and activate a transform tool": "ケージコントローラーを選択し、トランスフォームツールを有効化",
    "Move": "移動",
    "Move the deformation cage": "変形ケージを移動",
    "Rotate": "回転",
    "Rotate and aim the deformation cage": "変形ケージを回転して向きを決める",
    "Scale": "スケール",
    "Resize the deformation cage": "変形ケージのサイズを変更",
    "Show Cage": "ケージを表示",
    "Draw the cyan cage and orange deformation guide": "シアンのケージとオレンジの変形ガイドを描画",
    "Show Axis Switch": "軸切替を表示",
    "Show bend-trend choices around the cage; the choices hide after selection unless Ctrl is held": "ケージ周囲に曲げ傾向の選択肢を表示。選択後は隠れますが、Ctrl を押している間は表示を維持",
    "Show Bend Direction Handle": "曲げ方向ハンドルを表示",
    "Show a separate ring for adjusting the Bend direction": "曲げ方向調整用の独立リングを表示",
    "Axis Switch": "軸切替",
    "Direction Ring": "方向リング",
    "Bend Trend": "曲げ傾向",
    "Fine Direction": "精密方向",
    "Helper objects stay hidden until cage transform": "ヘルパーオブジェクトはケージ変形時まで非表示",
    "Numeric Controls": "数値コントロール",
    "Show exact cage size, location, and rotation values": "ケージの正確なサイズ・位置・回転値を表示",
    "Independent Ends": "独立端部",
    "Show separate top and bottom cross-section controls": "上下断面の個別コントロールを表示",
    "Top Scale": "上部スケール",
    "Scale the top cage cross-section without changing the bottom": "下部を変えずに上部ケージ断面のみスケール",
    "Bottom Scale": "下部スケール",
    "Scale the bottom cage cross-section without changing the top": "上部を変えずに下部ケージ断面のみスケール",
    "Top Offset": "上部オフセット",
    "Move the top cage cross-section without changing the bottom": "下部を変えずに上部ケージ断面のみ移動",
    "Bottom Offset": "下部オフセット",
    "Move the bottom cage cross-section without changing the top": "上部を変えずに下部ケージ断面のみ移動",
    "Offset": "オフセット",
    "Show Shape Handles": "形状ハンドルを表示",
    "Show separate top and bottom cross-section shaping handles": "上下断面の個別整形ハンドルを表示",
    "Show Length Handles": "長さハンドルを表示",
    "Show handles that independently move a cage end or a Curve effect boundary": "ケージ端またはカーブ作用境界を個別に動かすハンドルを表示",
    "Show handles that move the top or bottom cage boundary independently": "上下ケージ境界を個別に動かすハンドルを表示",
    "Limit to Object Bounds": "オブジェクト境界内に制限",
    "Prevent the top and bottom cage or Curve effect boundaries from moving beyond the input object's bounds": "上下のケージ境界またはカーブ作用境界が入力オブジェクト範囲を超えないようにします",
    "Prevent the top and bottom cage boundaries from moving beyond the input object's bounds": "上下ケージ境界が入力オブジェクトの境界を超えないようにする",
    "Length handles stop at the object bounds": "長さハンドルはオブジェクト境界で止まります",
    "Outer length handles stop at the object bounds": "外側の長さハンドルはオブジェクト境界で止まります",
    "Reset Independent Ends": "独立端部をリセット",
    "Restore both cage ends to the fitted cross-section": "両ケージ端部をフィット時の断面へ戻す",
    "Cyan top / green bottom: drag one end only": "シアン上部 / 緑下部: 片方の端部のみドラッグ",
    "Top End Shape": "上端部の形状",
    "Bottom End Shape": "下端部の形状",
    "Yellow top / amber bottom: move one boundary": "黄上部 / 琥珀下部: 片方の境界のみ移動",
    "Top Boundary": "上境界",
    "Bottom Boundary": "下境界",
    "Shared Boundary": "共有境界",
    "Cage Length": "ケージ長さ",
    "Effect Range Length": "作用範囲の長さ",
    "Interior boundaries resize both neighboring cages": "内側境界は隣接する両ケージの長さを同時に変更します",
    "Interior boundaries adjust cage length and gap without overlap": "内側境界は重ならないようケージ長さと間隔を調整します",
    "Drag Along Cage • Shift Precise • Ctrl Snap": "ケージに沿ってドラッグ • Shift 精密 • Ctrl スナップ",
    "Alt Slide X • Shift Precise • Ctrl Snap": "Alt で X スライド • Shift 精密 • Ctrl スナップ",
    "Location": "位置",
    "Rotation": "回転",
    "Orange handle: drag Angle": "オレンジハンドル: 角度をドラッグ",
    "Orange handle: drag Factor": "オレンジハンドル: 係数をドラッグ",
    "Alt Direction • Shift Precise • Ctrl Snap": "Alt で方向 • Shift 精密 • Ctrl スナップ",
    "Shift Precise • Ctrl Snap": "Shift 精密 • Ctrl スナップ",
    "Drag Around Ring • Shift Precise • Ctrl Snap": "リング周囲をドラッグ • Shift 精密 • Ctrl スナップ",
    "Drag Along Axis • Shift Precise • Ctrl Snap": "軸に沿ってドラッグ • Shift 精密 • Ctrl スナップ",
    "Bend Direction": "曲げ方向",
    "Set Bend Trend": "曲げ傾向を設定",
    "Choose Bend Trend": "曲げ傾向を選択",
    "Choose a signed cage axis and one of its two perpendicular bend trends; hold Ctrl to keep all choices visible": "符号付きケージ軸とその直交する 2 つの曲げ傾向から選択。Ctrl を押すと選択肢を表示したままにできます",
    "Switch Cage Axis": "ケージ軸を切替",
    "Axis switch: RGB is X/Y/Z; diamond is +, ring is -": "軸切替: RGB は X/Y/Z、菱形は +、リングは -",
    "Orange double arrow: drag Bend angle": "オレンジの双方向矢印: 曲げ角度をドラッグ",
    "Small orange double arrow: drag Bend direction": "小さなオレンジ双方向矢印: 曲げ方向をドラッグ",
    "Large purple twist arc: drag around its center": "大きな紫のねじり弧: 中心まわりにドラッグ",
    "Red / green arrows: horizontal / vertical bend trend": "赤 / 緑の矢印: 水平 / 垂直の曲げ傾向",
    "Click to choose and close • Ctrl keeps choices open": "クリックで選択して閉じる • Ctrl で選択肢を開いたまま",
    "Amber taper handle: drag Factor": "琥珀のテーパーハンドル: 係数をドラッグ",
    "Green stretch handle: drag Factor": "緑の伸縮ハンドル: 係数をドラッグ",
    "Set Deform Axis": "変形軸を設定",
    "Align the cage axis and fit it to the current stage input": "ケージ軸を揃え、現在のステージ入力にフィット",
    "Show Toggle Bend Axis Gizmo": "曲げ軸切替ギズモを表示",
    "AIGODLIKE Community:小萌新": "AIGODLIKE Community: 小萌新",
    "AIGODLIKE": "AIGODLIKE",
    "Gizmo Property Show Location": "ギズモプロパティの表示位置",
    "You can press the following shortcut keys when dragging values": "値のドラッグ中に次のショートカットを使用できます",
    "    Wheel:   Switch Origin Ctrl Mode": "    Wheel:   原点 Ctrl モードを切替",
    "    X,Y,Z:  Switch Modifier Deform Axis": "    X,Y,Z:  修正子の変形軸を切替",
    "    W:       Switch Deform Wireframe Show": "    W:       変形ワイヤーフレーム表示を切替",
    "    A:       Switch To Select Bend Axis Mode(deform_method=='BEND')": "    A:       曲げ軸選択モードへ切替(deform_method=='BEND')",
    "Show Set Axis Button": "軸設定ギズモを表示",
    "Follow Upper Limit(Red)": "上限に追従(赤)",
    "Follow Lower Limit(Green)": "下限に追従(緑)",
    "Lower limit(Green)": "下限(緑)",
    "UP Limits(Red)": "上限(赤)",
    "Show Deform Wireframe": "変形ワイヤーフレームを表示",
    "Minimum value between upper and lower limits": "上限と下限の間の最小値",
    "Upper and lower limit tolerance": "上下限の許容差",
    "Draw Upper and lower limit Bound Box Color": "上下限バウンドボックスの描画色",
    "Upper and lower limit Bound Box Color": "上下限バウンドボックスの色",
    "Draw Bound Box Color": "バウンドボックスの描画色",
    "Bound Box": "バウンドボックス",
    "Draw Deform Wireframe Color": "変形ワイヤーフレームの描画色",
    "Deform Wireframe": "変形ワイヤーフレーム",
    "Simple Deform visualization adjustment tool": "Simple Deform 可視化調整ツール",
    "Select an object and the active modifier is Simple Deform": "オブジェクトを選択し、アクティブ修正子が Simple Deform であること",
    "Bound Middle": "バウンド中央",
    "Add an empty object origin as the rotation axis (if there is an origin, do not add it), and set the origin position as the lower limit during operation": "回転軸として空オブジェクトの原点を追加し（既にあれば追加しない）、操作中は原点位置を下限に設定",
    "Add an empty object origin as the rotation axis (if there is an origin, do not add it), and set the origin position as the upper limit during operation": "回転軸として空オブジェクトの原点を追加し（既にあれば追加しない）、操作中は原点位置を上限に設定",
    "Add an empty object origin as the rotation axis (if there is an origin, it will not be added), and set the origin position between the upper and lower limits during operation": "回転軸として空オブジェクトの原点を追加し（既にあれば追加しない）、操作中は原点位置を上下限の間に設定",
    "Add an empty object origin as the rotation axis (if there is an origin, do not add it), and set the origin position as the position between the bounding boxes during operation": "回転軸として空オブジェクトの原点を追加し（既にあれば追加しない）、操作中は原点位置をバウンドボックス間に設定",
    "No origin operation": "原点操作なし",
    "Origin control mode": "原点コントロールモード",
    "Down limit": "下限",
    "Coefficient": "係数",
    "Up limit": "上限",
    "Upper limit": "上限",
    "3D View -> Select an object and the active modifier is simple deformation": "3Dビュー -> オブジェクトを選択し、アクティブ修正子がシンプル変形であること",
    "3D View: Simple Deform Helper": "3Dビュー: Simple Deform Helper",
    "Simple Deform Helper": "シンプル変形ヘルパー",
    "Tool Options": "ツールオプション",
    "The scaling value of the object is not 1": "オブジェクトのスケール値が 1 ではありません",
    "which will cause the deformation of the simple deformation modifier.": "これによりシンプル変形修正子の変形結果が歪みます。",
    "Please apply the scaling before deformation.": "変形前にスケールを適用してください。",
    "Z Rotate": "Z 回転",
    "Simple Deform Animated": "Simple Deform アニメーション",
    "Simple Deform Property": "Simple Deform プロパティ",
    "Insert Keyframe": "キーフレームを挿入",
    "Remove Keyframe": "キーフレームを削除",
    "Show Simple Deform Gizmo": "Simple Deform ギズモを表示",
    "Simple Deform Stack": "Simple Deform スタック",
    "Show Other Simple Deform Stages": "他の Simple Deform ステージを表示",
    "Draw faint input bounds for other Simple Deform modifiers": "他の Simple Deform 修正子の入力境界を薄く描画",
    "Show Drag Shortcuts in Header": "ヘッダーにドラッグショートカットを表示",
    "Warn About Low Topology": "低トポロジーを警告",
    "Warn when the active deformation axis has too few geometry points": "アクティブ変形軸のジオメトリ点が少なすぎる場合に警告",
    "Wireframe Preview FPS": "ワイヤーフレームプレビュー FPS",
    "Maximum refresh rate for the optional deformed wireframe preview": "任意の変形ワイヤーフレームプレビューの最大更新レート",
    "User Origin is protected": "ユーザー原点は保護されています",
    "Follow-limit Origin modes are disabled.": "制限追従の原点モードは無効です。",
    "Simple Deform needs more segments to bend smoothly.": "Simple Deform を滑らかに曲げるには、さらにセグメントが必要です。",
    "Add Subdivision Before Deform": "変形前に細分化を追加",
    "Add a Subdivision Surface modifier before the active deformation stage "
    "so bending has enough segments":
        "アクティブな変形ステージの前にサブディビジョンサーフェスモディファイアーを追加します",
    "Simple Subdivision": "シンプル細分化",
    "Add straight loop cuts without smoothing": "スムージングせずにループカットを追加",
    "Smooth while subdividing": "細分化しながらスムージング（Catmull-Clark）",
    "Subdivision was added at the end; move it before the deformation stage":
        "細分化は末尾に追加されました。変形ステージの前に移動してください",
    "Current cage Geometry Nodes modifier is not selected":
        "現在のケージのジオメトリノードが選択されていません",
    "Select a stage above to edit its cage controls.":
        "上のスタックでステージを選択するとケージ操作を編集できます。",
    "Create": "作成",
    "Add a non-destructive subdivision modifier before the active Simple Deform": "アクティブな Simple Deform の前に非破壊の細分化修正子を追加",
    "Switch Simple Deform Stage": "Simple Deform ステージを切替",
    "Make the previous or next Simple Deform modifier active": "前または次の Simple Deform 修正子をアクティブにする",
    "Multi-Object Deform": "複数オブジェクト変形",
    "Merge Selected for Deform": "選択物を変形用に結合",
    "Create one live mesh from selected objects; non-mesh sources are converted to meshes": "選択物からライブ結合メッシュを作成し、非メッシュはメッシュへ変換します",
    "Select at least two supported objects": "対応するオブジェクトを2つ以上選択してください",
    "One or more selected objects cannot be converted": "選択物の一部を変換できません",
    "Could not convert {name} to a mesh": "{name} をメッシュに変換できません",
    "{name} already belongs to a deformation merge": "{name} はすでに変形結合に含まれています",
    "Merged {count} objects for deformation": "{count} 個のオブジェクトを変形用に結合しました",
    "Edit Merged Source": "結合元を編集",
    "Select the source under the pointer from a deformation merge": "変形結合からポインター下の元オブジェクトを選択します",
    "Click a merged part to switch source | Double-click blank to return | Esc or Right Mouse exits": "結合部分をクリックして元を切替 | 空白をダブルクリックして戻る | Esc または右クリックで終了",
    "Editing merged source: {name}": "結合元を編集中: {name}",
    "Select this source while keeping the merged result visible": "結合結果を表示したままこの元オブジェクトを選択します",
    "Return to Merged Object": "結合オブジェクトに戻る",
    "Hide the editable source and select its deformation merge": "編集中の元オブジェクトを隠して変形結合を選択します",
    "Unmerge and Restore Sources": "結合解除して元を復元",
    "Restore source visibility and remove the generated merged object": "元オブジェクトの表示を復元し、生成した結合オブジェクトを削除します",
    "Restored sources from {name}": "{name} から元オブジェクトを復元しました",
    "Editing Source": "元オブジェクトを編集中",
    "Merged Sources": "結合元",
    "Merged Geometry": "結合ジオメトリ",
    "Join Sources": "元を結合",
    "World Transform": "ワールド変換",
    "Source Index": "元インデックス",
    "Show Final Merged State While Editing Sources": "元を編集中に最終結合状態を表示",
    "Display the selected source after the merged object's full modifier stack": "結合オブジェクトの修正子スタック全体を適用した選択元を表示します",
    "Add Cage to Final Source": "最終状態の元にケージを追加",
    "Add a cage that affects only the selected source after the merged object's current modifier stack": "結合オブジェクトの現在の修正子スタック後で、選択した元だけに作用するケージを追加します",
    "The selected source has no evaluated surface geometry": "選択した元に評価済みサーフェスジオメトリがありません",
    "Could not configure the source cage filter": "元オブジェクト用ケージフィルターを設定できませんでした",
    "{name} Final Cage": "{name} 最終状態ケージ",
    "Final Source Filter": "最終状態の元フィルター",
    "Merged Source Index": "結合元インデックス",
    "Source = {index}": "元 = {index}",
    "Existing Source and Matching Index": "元が存在しインデックスが一致",
    "Return": "戻る",
    "Click a merged part to edit or switch source": "結合部分をクリックして元を編集または切替",
    "Double-click blank to return | Esc or Right Mouse exits": "空白をダブルクリックして戻る | Esc または右クリックで終了",
})


translations_ko_KR = _localized_catalog({
    "Insert Cage Keyframes": "\ucf00\uc774\uc9c0 \ud0a4\ud504\ub808\uc784 \uc0bd\uc785",
    "Delete Cage Keyframes": "\ucf00\uc774\uc9c0 \ud0a4\ud504\ub808\uc784 \uc0ad\uc81c",
    "Insert Keys": "\ud0a4 \uc0bd\uc785",
    "Delete Keys": "\ud0a4 \uc0ad\uc81c",
    "Inserted {count} FFD control-point keyframe channels":
        "FFD \uc81c\uc5b4\uc810\uc5d0 {count}\uac1c\uc758 \ud0a4\ud504\ub808\uc784 \ucc44\ub110\uc744 \uc0bd\uc785\ud588\uc2b5\ub2c8\ub2e4",
    "Removed {count} FFD control-point keyframe channels":
        "FFD \uc81c\uc5b4\uc810\uc758 \ud604\uc7ac \ud504\ub808\uc784 \ud0a4 \ucc44\ub110 {count}\uac1c\ub97c \uc0ad\uc81c\ud588\uc2b5\ub2c8\ub2e4",
    "Key the active cage parameters, end profiles, FFD control points, and cage transform on the current frame":
        "\ud604\uc7ac \ucf00\uc774\uc9c0 \ud30c\ub77c\ubbf8\ud130, \ub05d \ud615\uc0c1, FFD \uc81c\uc5b4\uc810, \ucf00\uc774\uc9c0 \ubcc0\ud658\uc744 \ud604\uc7ac \ud504\ub808\uc784\uc5d0 \ud0a4\ud654",
    "Delete the current-frame keys created for the active cage":
        "\ud604\uc7ac \ucf00\uc774\uc9c0\uc5d0 \uc0dd\uc131\ub41c \ud604\uc7ac \ud504\ub808\uc784 \ud0a4\ub97c \uc0ad\uc81c",
    "Inserted {count} cage keyframe channels": "{count}\uac1c \ucf00\uc774\uc9c0 \ud0a4\ud504\ub808\uc784 \ucc44\ub110 \uc0bd\uc785",
    "Removed {count} cage keyframe channels": "{count}\uac1c \ucf00\uc774\uc9c0 \ud0a4\ud504\ub808\uc784 \ucc44\ub110 \uc0ad\uc81c",
    "Alt: Screen X | Shift: Screen Y | Alt+Shift: Free | Ctrl: Snap":
        "Alt: \ud654\uba74 X | Shift: \ud654\uba74 Y | Alt+Shift: \uc790\uc720 | Ctrl: \uc2a4\ub0c5",
    "Added cage to the final state of {name}": "{name}의 최종 상태에 케이지를 추가했습니다",
    "Rotation Mode": "회전 모드",
    "Previous": "이전",
    "Next": "다음",
    "Select the previous Simple Deform modifier": "이전 Simple Deform 수정자 선택",
    "Select the next Simple Deform modifier": "다음 Simple Deform 수정자 선택",
    "Earlier": "앞으로",
    "Later": "뒤로",
    "Tool Settings": "도구 설정",
    "In Front": "앞에 표시",
    "Show Gizmo": "기즈모 표시",
    "Stage Index": "스테이지 인덱스",
    "Active Deformation Layer": "활성 변형 레이어",
    "Muted Deformations": "뮤트된 변형",
    "Original Origin": "원래 원점",
    "Origin Object Rotate Angle": "원점 오브젝트 회전 각도",
    "Origin Object Rotate Axis": "원점 오브젝트 회전 축",
    "Expand every deformation layer in the cage UI": "케이지 UI에서 모든 변형 레이어 펼치기",
    "Persistent execution order for the enabled deformation layers": "활성화된 변형 레이어의 실행 순서 유지",
    "Index of the deformation layer selected in the cage UI": "케이지 UI에서 선택된 변형 레이어 인덱스",
    "Present deformation layers temporarily bypassed by this cage": "이 케이지가 일시적으로 우회하는 기존 변형 레이어",
    "Temporarily bypass Bend": "구부리기 일시 우회",
    "Temporarily bypass Twist": "비틀기 일시 우회",
    "Temporarily bypass Taper": "테이퍼 일시 우회",
    "Temporarily bypass Stretch": "늘리기 일시 우회",
    "Move before the previous Cage Deform": "이전 케이지 변형 앞으로 이동",
    "Move after the next Cage Deform": "다음 케이지 변형 뒤로 이동",
    "Key the active strength, limits, and managed Origin controls": "활성 강도, 제한, 관리 원점 컨트롤에 키 삽입",
    "Remove the current-frame keys created for the active Simple Deform": "활성 Simple Deform용으로 만든 현재 프레임 키 제거",
    "Create a managed Origin and keep it at the upper limit while dragging": "관리 원점을 만들고 드래그 중에는 상한에 유지",
    "Create a managed Origin and keep it at the lower limit while dragging": "관리 원점을 만들고 드래그 중에는 하한에 유지",
    "Create a managed Origin between the upper and lower limits": "상한과 하한 사이에 관리 원점 만들기",
    "Create a managed Origin at the deformation bounds center": "변형 경계 중심에 관리 원점 만들기",
    "Middle": "중간",
    "Stage {stage_index} of {stage_count}: {modifier}": "스테이지 {stage_index}/{stage_count}: {modifier}",
    "Deform {stage_index}/{stage_count}": "변형 {stage_index}/{stage_count}",
    "Low topology on {axis}: {sample_count} levels": "{axis} 축 토폴로지가 낮음: {sample_count} 레벨",
    "Animated": "애니메이션",
    "Property": "속성",
    "01 Local Space": "01 로컬 공간",
    "02 Cage Profile": "02 케이지 프로파일",
    "07 Mode and Output": "07 모드와 출력",
    "Subdivide to Chained Cages": "체인 케이지로 세분",
    "Split the active cage inside its current range and distribute its deformation across a chained cage stack": "현재 범위 안에서 활성 케이지를 분할하고 변형을 체인 케이지 스택에 분배",
    "Number of chained segments inside the current cage range": "현재 케이지 범위 안의 체인 세그먼트 수",
    "Uniform spacing between segments; segment lengths shrink so the original total range is preserved": "세그먼트 간격을 균일하게 유지합니다. 원래 총 범위를 보존하도록 세그먼트 길이가 줄어듭니다",
    "Keep each newly-created shared cross-section continuous": "새로 만든 공유 단면을 연속으로 유지",
    "The original cage boundaries stay fixed.": "원래 케이지 경계는 고정된 채로 유지됩니다.",
    "Bend and Twist angles are distributed across segments.": "구부리기와 비틀기 각도는 각 세그먼트에 분배됩니다.",
    "Batch Edit": "일괄 편집",
    "Batch Edit Chain": "체인 일괄 편집",
    "Edit several cages in the active chain as one operation": "활성 체인의 여러 케이지를 한 번에 편집",
    "Scope": "범위",
    "Whole Chain": "전체 체인",
    "Edit every cage in this chain": "이 체인의 모든 케이지 편집",
    "Start to Active": "시작부터 활성까지",
    "Edit the chain root through the active cage": "체인 루트부터 활성 케이지까지 편집",
    "Active to End": "활성부터 끝까지",
    "Edit the active cage through the chain tip": "활성 케이지부터 체인 끝까지 편집",
    "Operation": "작업",
    "End Scale": "끝단 스케일",
    "Batch-edit top and bottom cross-section scale": "상·하 단면 스케일 일괄 편집",
    "End Offset": "끝단 오프셋",
    "Batch-edit top and bottom cross-section offset": "상·하 단면 오프셋 일괄 편집",
    "Set spacing before every cage in scope": "범위 내 각 케이지 앞 간격 설정",
    "Batch-edit one deformation parameter": "변형 매개변수 하나를 일괄 편집",
    "Deformation": "변형",
    "Stage Visibility": "스테이지 표시 상태",
    "Apply or bypass every cage in scope": "범위 내 각 케이지를 적용하거나 우회",
    "Ends": "끝단",
    "Edit top ends": "상단 편집",
    "Edit bottom ends": "하단 편집",
    "Both": "양쪽",
    "Edit both ends": "양쪽 끝단 동시 편집",
    "Apply As": "적용 방식",
    "Set Values": "값 설정",
    "Replace existing values": "기존 값 바꾸기",
    "Add Values": "값 더하기",
    "Add to existing values": "기존 값에 더하기",
    "Multiply Values": "값 곱하기",
    "Multiply existing values": "기존 값에 곱하기",
    "X and Z cross-section values": "단면 X와 Z 값",
    "X and Z cross-section offset values": "단면 X와 Z 오프셋 값",
    "Spacing before each affected downstream cage": "영향받는 각 하류 케이지 앞 간격",
    "Preserve Total Range": "총 범위 유지",
    "Shorten each cage as its incoming gap grows": "앞 간격이 커질수록 각 케이지를 짧게 조정",
    "Parameter": "매개변수",
    "Batch-edit Bend angle": "구부리기 각도 일괄 편집",
    "Batch-edit Bend direction": "구부리기 방향 일괄 편집",
    "Batch-edit Twist angle": "비틀기 각도 일괄 편집",
    "Batch-edit Taper factor": "테이퍼 계수 일괄 편집",
    "Batch-edit Stretch factor": "늘리기 계수 일괄 편집",
    "Enable Stages": "스테이지 활성화",
    "Apply the affected cage stages": "영향받는 케이지 스테이지 적용",
    "Linked shared boundaries are changed only once.": "연동된 공유 경계는 한 번만 변경됩니다.",
    "Cages without this deformation layer are skipped.": "이 변형 레이어가 없는 케이지는 건너뜁니다.",
    "Created {count} cage stages": "케이지 스테이지 {count}개를 만들었습니다",
    "More than 3 cage stages may reduce viewport performance":
        "케이지 스테이지가 3개를 초과하면 뷰포트 성능이 저하될 수 있습니다",
    "Could not create cage chain: {error}": "케이지 체인을 만들 수 없음: {error}",
    "Only a single cage can be subdivided": "단일 케이지만 세분할 수 있습니다",
    "Set the cage origin to Bottom before subdividing": "세분하기 전에 케이지 원점을 하단으로 설정하세요",
    "Animated cage parameters cannot be subdivided safely": "애니메이션이 있는 케이지 매개변수는 안전하게 세분할 수 없습니다",
    "Taper collapses at an interior split boundary": "테이퍼가 내부 분할 경계에서 붕괴됩니다",
    "Subdivided cage into {count} chained stages": "케이지를 체인 스테이지 {count}개로 세분했습니다",
    "Subdivided cage into {count} chained stages (gap clamped to preserve range)": "케이지를 체인 스테이지 {count}개로 세분했습니다(범위 유지를 위해 간격 제한)",
    "Could not subdivide cage: {error}": "케이지를 세분할 수 없음: {error}",
    "Could not batch edit chain: {error}": "체인을 일괄 편집할 수 없음: {error}",
    "No matching cage values were changed": "일치하는 케이지 값이 변경되지 않았습니다",
    "Updated {count} cage stages": "케이지 스테이지 {count}개를 업데이트했습니다",
    "Fitted {count} cage stages to chain input": "케이지 스테이지 {count}개를 체인 입력에 맞췄습니다",
    "No cage chain metadata was found": "케이지 체인 메타데이터를 찾지 못했습니다",
    "Missing cage stages: {indices}": "누락된 케이지 스테이지: {indices}",
    "Duplicate cage stage indices: {indices}": "중복된 케이지 스테이지 인덱스: {indices}",
    "A non-cage modifier is inserted inside the chain": "체인 안에 케이지가 아닌 수정자가 삽입되어 있습니다",
    "A chain stage has no matching controller": "체인 스테이지에 맞는 컨트롤러가 없습니다",
    "Chain stages use different connection modes": "체인 스테이지의 연결 모드가 서로 다릅니다",
    "Cage chain is broken": "케이지 체인이 끊어져 있습니다",
    "No Cage Chain was found": "케이지 체인을 찾지 못했습니다",
    "Reconnected {count} cage stages": "케이지 스테이지 {count}개를 다시 연결했습니다",
    "Reconnected {count} cage stages and released the subdivision baseline":
        "케이지 스테이지 {count}개를 다시 연결하고 세분 기준선을 해제했습니다",
    "Add Cage Chain": "케이지 체인 추가",
    "Number of segments to create": "만들 세그먼트 수",
    "Connection Mode": "연결 모드",
    "How neighboring cage segments handle their boundaries": "인접 케이지 세그먼트가 경계를 처리하는 방식",
    "The chain root extends continuously beyond both boundaries; later cages preserve the upstream prefix and continue from the cage end": "체인 루트는 양쪽 끝 경계에서 연속으로 확장되고, 이후 케이지는 상류 구간을 유지한 채 케이지 끝에서 이어집니다",
    "Limit each segment to its own box": "각 세그먼트를 자체 상자 안으로 제한",
    "Gap": "간격",
    "Gap Before": "앞 간격",
    "Gap from Previous Cage": "이전 케이지와의 간격",
    "Non-negative distance from the previous cage; changing it keeps the overall chain span when possible": "이전 케이지로부터의 음이 아닌 거리. 변경 시 가능하면 체인 전체 길이를 유지합니다",
    "Distance between this cage and the previous cage": "이 케이지와 이전 케이지 사이의 거리",
    "Distance between neighboring cage frames in target units": "인접 케이지 프레임 사이 거리(대상 단위)",
    "Cage Axis": "케이지 축",
    "Use the longest input dimension": "입력의 가장 긴 치수 사용",
    "Align cage Y to target +X": "케이지 Y를 대상 +X에 맞춤",
    "Align cage Y to target -X": "케이지 Y를 대상 -X에 맞춤",
    "Align cage Y to target +Y": "케이지 Y를 대상 +Y에 맞춤",
    "Align cage Y to target -Y": "케이지 Y를 대상 -Y에 맞춤",
    "Align cage Y to target +Z": "케이지 Y를 대상 +Z에 맞춤",
    "Align cage Y to target -Z": "케이지 Y를 대상 -Z에 맞춤",
    "Select a supported target object first": "먼저 지원되는 대상 오브젝트를 선택하세요",
    "Add Simple Deform": "Simple Deform 추가",
    "Add Simple Deform (Legacy)": "Simple Deform 추가(레거시)",
    "Add a traditional Simple Deform modifier": "기존 Simple Deform 수정자 추가",
    "Added legacy Simple Deform modifier": "레거시 Simple Deform 수정자를 추가했습니다",
    "Cage deformation is not supported for lattice objects": "래티스 오브젝트는 케이지 변형을 지원하지 않습니다",
    "The selected surface could not be converted for cage deformation": "선택한 서피스를 케이지 변형용으로 변환할 수 없습니다",
    "Surface cage deformation requires a mesh conversion": "서피스 케이지 변형에는 메시 변환이 필요합니다",
    "Add Chained Cages": "체인 케이지 추가",
    "Create Cage Chain": "케이지 체인 만들기",
    "Create several related deformation cages in one operation": "관련된 여러 변형 케이지를 한 번에 만들기",
    "Cage Count": "케이지 수",
    "Use isolated boxes": "각 상자 안의 지오메트리에만 영향",
    "Number of chained cages to create": "만들 체인 케이지 수",
    "Connect Ends": "끝단 연결",
    "Align each cage bottom to the previous cage top": "각 케이지 하단을 이전 케이지 상단에 맞춤",
    "Chain Mode": "체인 모드",
    "Use forward continuation when available": "가능하면 전방 연속 사용",
    "Create stages without automatic reconnection": "자동 재연결 없이 스테이지 만들기",
    "Chained": "체인",
    "Independent": "독립",
    "Segment": "세그먼트",
    "Enable Stage": "스테이지 활성화",
    "Temporarily apply or bypass this cage while preserving chained-stage flow": "체인 스테이지 흐름을 유지한 채 이 케이지를 일시 적용하거나 우회",
    "Show Other Cages": "다른 케이지 표시",
    "Display inactive cages and make their viewport controls directly editable": "비활성 케이지를 표시하고 뷰포트 컨트롤을 바로 편집할 수 있게 함",
    "Show Other Cage Controllers": "다른 케이지 컨트롤러 표시",
    "Display all cage controllers except active one": "활성 케이지를 제외한 모든 케이지 컨트롤러 표시",
    "Active Cage": "활성 케이지",
    "Inactive Cage": "비활성 케이지",
    "Active cage is highlighted; other cages are dimmed": "활성 케이지는 강조되고 다른 케이지는 어둡게 표시됩니다",
    "Select this cage stage and its controller": "이 케이지 스테이지와 컨트롤러 선택",
    "Select Cage Stage": "케이지 스테이지 선택",
    "Select Deformation Stage": "변형 스테이지 선택",
    "Make this cage or traditional Simple Deform stage active":
        "이 케이지 또는 기존 Simple Deform 스테이지를 활성화",
    "Cage Deform Strength Handle": "케이지 변형 강도 핸들",
    "Cage End Shape": "케이지 끝단 형태",
    "Cage Boundary": "케이지 경계",
    "Auto Reconnect Chain": "체인 자동 재연결",
    "Automatically refresh downstream cage frames after a chain parameter or controller transform changes": "체인 매개변수나 컨트롤러 변형이 바뀌면 하류 케이지 프레임을 자동 새로고침",
    "Auto Reconnect": "자동 재연결",
    "Refresh downstream cage frames after upstream edits": "상류 편집 후 하류 케이지 프레임 새로고침",
    "Use one-sided continuation": "단방향 연속 사용",
    "Propagate each preceding cage output frame to the next cage": "바로 앞 케이지의 출력 프레임을 다음 케이지로 전달",
    "Reconnect Broken Chain": "끊어진 체인 다시 연결",
    "Attempt contiguous stages even when a stack issue is detected": "스택 문제가 감지되어도 연속 스테이지를 시도",
    "Cage Deform core is unavailable": "케이지 변형 코어를 사용할 수 없습니다",
    "Chained Cages": "체인 케이지",
    "Independent Cage Chain": "독립 케이지 체인",
    "Reconnect Chain": "체인 다시 연결",
    "Reconnect Cage Chain": "케이지 체인 다시 연결",
    "Align each cage to the previous cage's output frame": "각 케이지를 이전 케이지의 출력 프레임에 맞춤",
    "Each stage keeps its own angle and length; reconnect updates the incoming frame.": "각 스테이지는 자체 각도와 길이를 유지합니다. 재연결은 입력 프레임만 갱신합니다.",
    "Each stage keeps its deformations, length, and incoming gap.": "각 스테이지는 자체 변형, 길이, 앞 간격을 유지합니다.",
    "Sync Shared End Scale": "공유 끝단 스케일 동기화",
    "Allow Approximate Mixed Bend": "혼합 굽힘 근사 세분화 허용",
    "Allow subdivision of stacks containing Bend with other types; the operations do not commute and the result may differ":
        "굽힘과 다른 유형이 포함된 스택의 근사 세분화를 허용합니다. 작업은 교환 가능하지 않아 결과가 달라질 수 있습니다",
    "Mixed Bend stacks are protected because deformation order is non-commutative; enable Allow Approximate Mixed Bend to continue":
        "변형 순서가 교환 가능하지 않아 혼합 굽힘 스택을 보호했습니다. 계속하려면 '혼합 굽힘 근사 세분화 허용'을 활성화하세요",
    "Scale both sides of each shared cage seam together while keeping each outer end independent": "각 공유 케이지 이음새 양쪽 스케일을 함께 맞추고 바깥 끝단은 각각 독립 유지",
    "Scale both sides of each shared cage seam together while keeping outer ends independent": "각 공유 케이지 이음새 양쪽 스케일을 함께 맞추고 바깥 끝단은 독립 유지",
    "Only neighboring seam-end scales are synchronized.": "인접 이음새 끝단 스케일만 동기화됩니다.",
    "Outer cage ends remain independent.": "바깥 케이지 끝단은 독립된 채로 유지됩니다.",
    "Chained mode starts at the lower cage boundary.": "체인 모드는 케이지 하단 경계에서 시작합니다.",
    "Cage Chain mode is locked to Chained.": "케이지 체인 모드는 체인으로 고정되어 있습니다.",
    "Simple Deformer": "심플 디포머",
    "Simple Deformer V2": "심플 디포머 V2",
    "Add New Cages to End": "새 케이지를 스택 끝에 추가",
    "Place newly-created cage stages at the end of the modifier stack": "새로 만든 케이지 스테이지를 수정자 스택 끝에 배치",
    "Cage Deform": "케이지 변형",
    "Add Cage Deform": "케이지 변형 추가",
    "Add an independent cage deformation stage": "독립 케이지 변형 스테이지 추가",
    "Added Cage Deform stage": "케이지 변형 스테이지를 추가했습니다",
    "Deform axis changed; the user-supplied Origin was preserved": "변형 축이 변경되었습니다. 사용자 지정 원점은 유지되었습니다",
    "Subdivision was added at the end; move it before Simple Deform": "세분이 끝에 추가되었습니다. Simple Deform 앞으로 옮기세요",
    "Inserted {inserted} Simple Deform keyframe channels": "Simple Deform 키프레임 채널 {inserted}개를 삽입했습니다",
    "Removed {removed} Simple Deform keyframe channels": "Simple Deform 키프레임 채널 {removed}개를 제거했습니다",
    "Independent cage deformation": "독립 케이지 변형",
    "Bend, Twist, Taper, and Stretch.": "구부리기, 비틀기, 테이퍼, 늘리기를 지원합니다.",
    "Combine Bend, Twist, Taper, and Stretch in one cage.": "한 케이지에서 구부리기, 비틀기, 테이퍼, 늘리기를 조합할 수 있습니다.",
    "Cage Stack": "케이지 스택",
    "Deformation Stack": "변형 스택",
    "Move Cage Stage": "케이지 스테이지 이동",
    "Move Deformation Stage": "변형 스테이지 이동",
    "Move before the previous deformation stage": "이전 변형 스테이지 앞으로 이동",
    "Move after the next deformation stage": "다음 변형 스테이지 뒤로 이동",
    "Move this deformation earlier or later in the modifier stack": "수정자 스택에서 이 변형을 앞이나 뒤로 이동",
    "Duplicate Cage Stage": "케이지 스테이지 복제",
    "Duplicate": "복제",
    "Remove Cage Stage": "케이지 스테이지 제거",
    "Remove Deformation Stage": "변형 스테이지 제거",
    "Remove this deformation stage and any owned controls":
        "이 변형 스테이지와 소유 컨트롤 제거",
    "Remove Stage": "스테이지 제거",
    "Remove Cage Stack": "케이지 스택 제거",
    "Remove Deformation Stack": "변형 스택 제거",
    "Remove every managed cage and traditional Simple Deform stage":
        "모든 관리 케이지와 기존 Simple Deform 스테이지 제거",
    "Remove": "제거",
    "Remove this managed deformation stage and its cage controller": "이 관리 변형 스테이지와 케이지 컨트롤러 제거",
    "Remove every managed cage stage and its owned controllers": "모든 관리 케이지 스테이지와 소유 컨트롤러 제거",
    "Shape": "형태",
    "Deformation Layers": "변형 레이어",
    "Expand All": "모두 펼치기",
    "Add Deformation": "변형 추가",
    "Add Deformation Layer": "변형 레이어 추가",
    "Add one deformation operation to this cage": "이 케이지에 변형 작업 하나 추가",
    "Select Deformation Layer": "변형 레이어 선택",
    "Select this deformation layer without changing its evaluation": "평가 상태를 바꾸지 않고 이 변형 레이어 선택",
    "Remove Deformation Layer": "변형 레이어 제거",
    "Remove this deformation operation from the cage": "이 케이지에서 변형 작업 제거",
    "Toggle Deformation Layer": "변형 레이어 활성 전환",
    "Temporarily bypass or restore this deformation without losing its settings": "설정을 잃지 않고 이 변형을 일시 우회하거나 복원",
    "Move Deformation Layer": "변형 레이어 이동",
    "Move this deformation operation earlier or later": "이 변형 작업을 앞이나 뒤로 이동",
    "Up": "위로",
    "Down": "아래로",
    "Execute this layer earlier": "이 레이어를 더 일찍 실행",
    "Execute this layer later": "이 레이어를 더 늦게 실행",
    "This deformation is already enabled": "이 변형은 이미 활성화되어 있습니다",
    "Deformation Type": "변형 유형",
    "Deformation Types": "변형 유형",
    "Deformations": "변형",
    "Shape operations combined by this cage": "이 케이지가 조합하는 형태 작업",
    "Enable one or more deformation operations in this cage": "이 케이지에서 하나 이상의 변형 작업 활성화",
    "At least one deformation type must remain enabled": "변형 유형은 최소 하나가 활성 상태로 남아 있어야 합니다",
    "Shape operation performed inside the cage": "케이지 안에서 수행하는 형태 작업",
    "Bend": "구부리기",
    "Curve geometry along the cage axis": "케이지 축을 따라 지오메트리를 구부림",
    "Twist": "비틀기",
    "Rotate cross-sections around the cage axis": "단면을 케이지 축 주위로 회전",
    "Taper": "테이퍼",
    "Scale cross-sections along the cage axis": "케이지 축을 따라 단면 스케일",
    "Stretch": "늘리기",
    "Scale geometry along the cage axis": "케이지 축을 따라 지오메트리 스케일",
    "Angle": "각도",
    "Total Bend or Twist angle through the cage length": "케이지 전체 길이에 걸친 구부리기 또는 비틀기 총 각도",
    "Bend Strength": "구부리기 강도",
    "Bend angle through the cage length": "케이지 전체 길이에 걸친 구부리기 각도",
    "Bend Angle": "구부리기 각도",
    "Total Bend angle through the cage length": "케이지 전체 길이에 걸친 구부리기 총 각도",
    "Twist Strength": "비틀기 강도",
    "Twist angle through the cage length": "케이지 전체 길이에 걸친 비틀기 각도",
    "Twist Angle": "비틀기 각도",
    "Total Twist angle through the cage length": "케이지 전체 길이에 걸친 비틀기 총 각도",
    "Taper Factor": "테이퍼 계수",
    "Amount of taper along the cage axis": "케이지 축을 따른 테이퍼 양",
    "Cross-section scale change through the cage length": "케이지 전체 길이에 걸친 단면 스케일 변화량",
    "Stretch Factor": "늘리기 계수",
    "Amount of stretch along the cage axis": "케이지 축을 따른 늘리기 양",
    "Length scale change through the cage": "케이지에 걸친 길이 스케일 변화량",
    "Factor": "계수",
    "Amount used by Taper and Stretch": "테이퍼와 늘리기에 사용하는 양",
    "Direction": "방향",
    "Direction of Bend around the cage axis": "케이지 축 주위 구부리기 방향",
    "Mode": "모드",
    "How geometry outside the cage is handled": "케이지 밖 지오메트리 처리 방식",
    "Limited": "제한",
    "Deform inside; continue outside from the cage ends": "안쪽은 변형하고, 바깥은 케이지 끝에서 이어감",
    "Within Box": "상자 안",
    "Only points inside the cage are affected": "케이지 안 점만 영향을 받습니다",
    "Unlimited": "무제한",
    "Continue deformation beyond the cage": "케이지를 넘어 변형을 계속",
    "Origin": "원점",
    "Starting pattern of the deformation": "변형 시작 패턴",
    "Bottom": "하단",
    "Start at the lower cage boundary": "케이지 하단 경계에서 시작",
    "Center": "중심",
    "Use signed distance from the cage center": "케이지 중심으로부터의 부호 있는 거리 사용",
    "Symmetric": "대칭",
    "Mirror the deformation profile across the center": "변형 프로파일을 중심 기준으로 미러",
    "Top": "상단",
    "Start at the upper cage boundary": "케이지 상단 경계에서 시작",
    "Preserve Volume": "부피 유지",
    "Compensate cross-section size while stretching": "늘릴 때 단면 크기 보정",
    "Cage Controls": "케이지 컨트롤",
    "Deform Axis": "변형 축",
    "Target axis used when aligning and fitting the cage": "케이지 정렬과 맞춤에 사용하는 대상 축",
    "Size": "크기",
    "Dimensions of the independent deformation cage": "독립 변형 케이지의 치수",
    "Auto": "자동",
    "Use the longest local dimension": "가장 긴 로컬 치수 사용",
    "Align & Fit": "정렬 및 맞춤",
    "Align & Fit Chain": "체인 정렬 및 맞춤",
    "Fit to Object": "오브젝트에 맞추기",
    "Fit the active cage, or its entire connected chain, to the geometry entering the deformation": "활성 케이지 또는 연결된 전체 체인을 변형으로 들어오는 지오메트리에 맞춤",
    "Select Cage": "케이지 선택",
    "Select Cage Controller": "케이지 컨트롤러 선택",
    "Return to Object": "오브젝트로 돌아가기",
    "Select the object controlled by this deformation cage": "이 변형 케이지가 제어하는 오브젝트 선택",
    "Edit Cage": "케이지 편집",
    "Select the cage controller and activate a transform tool": "케이지 컨트롤러를 선택하고 변형 도구 활성화",
    "Move": "이동",
    "Move the deformation cage": "변형 케이지 이동",
    "Rotate": "회전",
    "Rotate and aim the deformation cage": "변형 케이지를 회전하고 방향 지정",
    "Scale": "스케일",
    "Resize the deformation cage": "변형 케이지 크기 조정",
    "Show Cage": "케이지 표시",
    "Draw the cyan cage and orange deformation guide": "시안 케이지와 주황 변형 가이드 그리기",
    "Show Axis Switch": "축 전환 표시",
    "Show bend-trend choices around the cage; the choices hide after selection unless Ctrl is held": "케이지 주변에 구부리기 경향 선택지를 표시합니다. 선택 후에는 숨겨지며 Ctrl을 누르면 계속 표시됩니다",
    "Show Bend Direction Handle": "구부리기 방향 핸들 표시",
    "Show a separate ring for adjusting the Bend direction": "구부리기 방향 조정용 독립 링 표시",
    "Axis Switch": "축 전환",
    "Direction Ring": "방향 링",
    "Bend Trend": "구부리기 경향",
    "Fine Direction": "정밀 방향",
    "Helper objects stay hidden until cage transform": "헬퍼 오브젝트는 케이지 변형 시까지 숨김",
    "Numeric Controls": "수치 컨트롤",
    "Show exact cage size, location, and rotation values": "정확한 케이지 크기, 위치, 회전 값 표시",
    "Independent Ends": "독립 끝단",
    "Show separate top and bottom cross-section controls": "상·하 단면 개별 컨트롤 표시",
    "Top Scale": "상단 스케일",
    "Scale the top cage cross-section without changing the bottom": "하단은 그대로 두고 상단 케이지 단면만 스케일",
    "Bottom Scale": "하단 스케일",
    "Scale the bottom cage cross-section without changing the top": "상단은 그대로 두고 하단 케이지 단면만 스케일",
    "Top Offset": "상단 오프셋",
    "Move the top cage cross-section without changing the bottom": "하단은 그대로 두고 상단 케이지 단면만 이동",
    "Bottom Offset": "하단 오프셋",
    "Move the bottom cage cross-section without changing the top": "상단은 그대로 두고 하단 케이지 단면만 이동",
    "Offset": "오프셋",
    "Show Shape Handles": "형태 핸들 표시",
    "Show separate top and bottom cross-section shaping handles": "상·하 단면 개별 성형 핸들 표시",
    "Show Length Handles": "길이 핸들 표시",
    "Show handles that independently move a cage end or a Curve effect boundary": "케이지 끝 또는 커브 적용 경계를 독립적으로 이동하는 핸들 표시",
    "Show handles that move the top or bottom cage boundary independently": "상단 또는 하단 케이지 경계를 독립적으로 이동하는 핸들 표시",
    "Limit to Object Bounds": "오브젝트 경계 안으로 제한",
    "Prevent the top and bottom cage or Curve effect boundaries from moving beyond the input object's bounds": "상·하 케이지 경계 또는 커브 적용 경계가 입력 오브젝트 범위를 넘지 않도록 합니다",
    "Prevent the top and bottom cage boundaries from moving beyond the input object's bounds": "상·하 케이지 경계가 입력 오브젝트 경계를 넘지 않도록 함",
    "Length handles stop at the object bounds": "길이 핸들은 오브젝트 경계에서 멈춥니다",
    "Outer length handles stop at the object bounds": "바깥 길이 핸들은 오브젝트 경계에서 멈춥니다",
    "Reset Independent Ends": "독립 끝단 재설정",
    "Restore both cage ends to the fitted cross-section": "양쪽 케이지 끝단을 맞춤 시 단면으로 복원",
    "Cyan top / green bottom: drag one end only": "시안 상단 / 초록 하단: 한쪽 끝단만 드래그",
    "Top End Shape": "상단 끝 형태",
    "Bottom End Shape": "하단 끝 형태",
    "Yellow top / amber bottom: move one boundary": "노랑 상단 / 호박색 하단: 한쪽 경계만 이동",
    "Top Boundary": "상단 경계",
    "Bottom Boundary": "하단 경계",
    "Shared Boundary": "공유 경계",
    "Cage Length": "케이지 길이",
    "Effect Range Length": "적용 범위 길이",
    "Interior boundaries resize both neighboring cages": "내부 경계는 인접한 두 케이지 길이를 함께 조정합니다",
    "Interior boundaries adjust cage length and gap without overlap": "내부 경계는 겹치지 않도록 케이지 길이와 간격을 조정합니다",
    "Drag Along Cage • Shift Precise • Ctrl Snap": "케이지를 따라 드래그 • Shift 정밀 • Ctrl 스냅",
    "Alt Slide X • Shift Precise • Ctrl Snap": "Alt로 X 이동 • Shift 정밀 • Ctrl 스냅",
    "Location": "위치",
    "Rotation": "회전",
    "Orange handle: drag Angle": "주황 핸들: 각도 드래그",
    "Orange handle: drag Factor": "주황 핸들: 계수 드래그",
    "Alt Direction • Shift Precise • Ctrl Snap": "Alt로 방향 • Shift 정밀 • Ctrl 스냅",
    "Shift Precise • Ctrl Snap": "Shift 정밀 • Ctrl 스냅",
    "Drag Around Ring • Shift Precise • Ctrl Snap": "링 주위로 드래그 • Shift 정밀 • Ctrl 스냅",
    "Drag Along Axis • Shift Precise • Ctrl Snap": "축을 따라 드래그 • Shift 정밀 • Ctrl 스냅",
    "Bend Direction": "구부리기 방향",
    "Set Bend Trend": "구부리기 경향 설정",
    "Choose Bend Trend": "구부리기 경향 선택",
    "Choose a signed cage axis and one of its two perpendicular bend trends; hold Ctrl to keep all choices visible": "부호 있는 케이지 축과 그에 수직인 두 구부리기 경향 중 하나를 선택합니다. Ctrl을 누르면 선택지를 계속 표시합니다",
    "Switch Cage Axis": "케이지 축 전환",
    "Axis switch: RGB is X/Y/Z; diamond is +, ring is -": "축 전환: RGB는 X/Y/Z, 마름모는 +, 링은 -",
    "Orange double arrow: drag Bend angle": "주황 양방향 화살표: 구부리기 각도 드래그",
    "Small orange double arrow: drag Bend direction": "작은 주황 양방향 화살표: 구부리기 방향 드래그",
    "Large purple twist arc: drag around its center": "큰 보라 비틀기 호: 중심 주위로 드래그",
    "Red / green arrows: horizontal / vertical bend trend": "빨강 / 초록 화살표: 가로 / 세로 구부리기 경향",
    "Click to choose and close • Ctrl keeps choices open": "클릭하여 선택 후 닫기 • Ctrl로 선택지 유지",
    "Amber taper handle: drag Factor": "호박색 테이퍼 핸들: 계수 드래그",
    "Green stretch handle: drag Factor": "초록 늘리기 핸들: 계수 드래그",
    "Set Deform Axis": "변형 축 설정",
    "Align the cage axis and fit it to the current stage input": "케이지 축을 맞추고 현재 스테이지 입력에 맞춤",
    "Show Toggle Bend Axis Gizmo": "구부리기 축 전환 기즈모 표시",
    "AIGODLIKE Community:小萌新": "AIGODLIKE Community: 小萌新",
    "AIGODLIKE": "AIGODLIKE",
    "Gizmo Property Show Location": "기즈모 속성 표시 위치",
    "You can press the following shortcut keys when dragging values": "값을 드래그하는 동안 다음 단축키를 사용할 수 있습니다",
    "    Wheel:   Switch Origin Ctrl Mode": "    Wheel:   원점 Ctrl 모드 전환",
    "    X,Y,Z:  Switch Modifier Deform Axis": "    X,Y,Z:  수정자 변형 축 전환",
    "    W:       Switch Deform Wireframe Show": "    W:       변형 와이어프레임 표시 전환",
    "    A:       Switch To Select Bend Axis Mode(deform_method=='BEND')": "    A:       구부리기 축 선택 모드로 전환(deform_method=='BEND')",
    "Show Set Axis Button": "축 설정 기즈모 표시",
    "Follow Upper Limit(Red)": "상한 따라가기(빨강)",
    "Follow Lower Limit(Green)": "하한 따라가기(초록)",
    "Lower limit(Green)": "하한(초록)",
    "UP Limits(Red)": "상한(빨강)",
    "Show Deform Wireframe": "변형 와이어프레임 표시",
    "Minimum value between upper and lower limits": "상한과 하한 사이의 최솟값",
    "Upper and lower limit tolerance": "상·하한 허용 오차",
    "Draw Upper and lower limit Bound Box Color": "상·하한 바운드 박스 그리기 색",
    "Upper and lower limit Bound Box Color": "상·하한 바운드 박스 색",
    "Draw Bound Box Color": "바운드 박스 그리기 색",
    "Bound Box": "바운드 박스",
    "Draw Deform Wireframe Color": "변형 와이어프레임 그리기 색",
    "Deform Wireframe": "변형 와이어프레임",
    "Simple Deform visualization adjustment tool": "Simple Deform 시각화 조정 도구",
    "Select an object and the active modifier is Simple Deform": "오브젝트를 선택하고 활성 수정자가 Simple Deform인지 확인",
    "Bound Middle": "바운드 중앙",
    "Add an empty object origin as the rotation axis (if there is an origin, do not add it), and set the origin position as the lower limit during operation": "회전축으로 빈 오브젝트 원점을 추가하고(이미 있으면 추가하지 않음), 조작 중 원점 위치를 하한으로 설정",
    "Add an empty object origin as the rotation axis (if there is an origin, do not add it), and set the origin position as the upper limit during operation": "회전축으로 빈 오브젝트 원점을 추가하고(이미 있으면 추가하지 않음), 조작 중 원점 위치를 상한으로 설정",
    "Add an empty object origin as the rotation axis (if there is an origin, it will not be added), and set the origin position between the upper and lower limits during operation": "회전축으로 빈 오브젝트 원점을 추가하고(이미 있으면 추가하지 않음), 조작 중 원점 위치를 상한과 하한 사이로 설정",
    "Add an empty object origin as the rotation axis (if there is an origin, do not add it), and set the origin position as the position between the bounding boxes during operation": "회전축으로 빈 오브젝트 원점을 추가하고(이미 있으면 추가하지 않음), 조작 중 원점 위치를 바운딩 박스 사이로 설정",
    "No origin operation": "원점 작업 없음",
    "Origin control mode": "원점 컨트롤 모드",
    "Down limit": "하한",
    "Coefficient": "계수",
    "Up limit": "상한",
    "Upper limit": "상한",
    "3D View -> Select an object and the active modifier is simple deformation": "3D 뷰 -> 오브젝트를 선택하고 활성 수정자가 단순 변형인지 확인",
    "3D View: Simple Deform Helper": "3D 뷰: Simple Deform Helper",
    "Simple Deform Helper": "심플 디폼 헬퍼",
    "Tool Options": "도구 옵션",
    "The scaling value of the object is not 1": "오브젝트 스케일 값이 1이 아닙니다",
    "which will cause the deformation of the simple deformation modifier.": "이로 인해 단순 변형 수정자의 결과가 왜곡될 수 있습니다.",
    "Please apply the scaling before deformation.": "변형 전에 스케일을 적용하세요.",
    "Z Rotate": "Z 회전",
    "Simple Deform Animated": "Simple Deform 애니메이션",
    "Simple Deform Property": "Simple Deform 속성",
    "Insert Keyframe": "키프레임 삽입",
    "Remove Keyframe": "키프레임 제거",
    "Show Simple Deform Gizmo": "Simple Deform 기즈모 표시",
    "Simple Deform Stack": "Simple Deform 스택",
    "Show Other Simple Deform Stages": "다른 Simple Deform 스테이지 표시",
    "Draw faint input bounds for other Simple Deform modifiers": "다른 Simple Deform 수정자의 입력 경계를 옅게 그리기",
    "Show Drag Shortcuts in Header": "헤더에 드래그 단축키 표시",
    "Warn About Low Topology": "낮은 토폴로지 경고",
    "Warn when the active deformation axis has too few geometry points": "활성 변형 축의 지오메트리 점이 너무 적을 때 경고",
    "Wireframe Preview FPS": "와이어프레임 미리보기 FPS",
    "Maximum refresh rate for the optional deformed wireframe preview": "선택적 변형 와이어프레임 미리보기의 최대 새로고침 속도",
    "User Origin is protected": "사용자 원점이 보호되어 있습니다",
    "Follow-limit Origin modes are disabled.": "제한 추종 원점 모드가 비활성화되어 있습니다.",
    "Simple Deform needs more segments to bend smoothly.": "Simple Deform을 부드럽게 구부리려면 세그먼트가 더 필요합니다.",
    "Add Subdivision Before Deform": "변형 전에 세분 추가",
    "Add a Subdivision Surface modifier before the active deformation stage "
    "so bending has enough segments":
        "활성 변형 스테이지 앞에 섭디비전 서피스 모디파이어를 추가합니다",
    "Simple Subdivision": "단순 세분",
    "Add straight loop cuts without smoothing": "스무딩 없이 루프 컷만 추가",
    "Smooth while subdividing": "세분하면서 스무딩(Catmull-Clark)",
    "Subdivision was added at the end; move it before the deformation stage":
        "세분이 스택 끝에 추가되었습니다. 변형 스테이지 앞으로 이동하세요",
    "Current cage Geometry Nodes modifier is not selected":
        "현재 케이지 지오메트리 노드가 선택되지 않았습니다",
    "Select a stage above to edit its cage controls.":
        "위 스택에서 스테이지를 선택하면 케이지 컨트롤을 편집할 수 있습니다.",
    "Create": "만들기",
    "Add a non-destructive subdivision modifier before the active Simple Deform": "활성 Simple Deform 앞에 비파괴 세분 수정자 추가",
    "Switch Simple Deform Stage": "Simple Deform 스테이지 전환",
    "Make the previous or next Simple Deform modifier active": "이전 또는 다음 Simple Deform 수정자를 활성으로 설정",
    "Multi-Object Deform": "다중 오브젝트 변형",
    "Merge Selected for Deform": "선택 항목을 변형용으로 병합",
    "Create one live mesh from selected objects; non-mesh sources are converted to meshes": "선택한 오브젝트로 실시간 병합 메시를 만들며 비메시 원본은 메시로 변환합니다",
    "Select at least two supported objects": "지원되는 오브젝트를 두 개 이상 선택하세요",
    "One or more selected objects cannot be converted": "선택한 오브젝트 중 일부를 변환할 수 없습니다",
    "Could not convert {name} to a mesh": "{name}을(를) 메시로 변환할 수 없습니다",
    "{name} already belongs to a deformation merge": "{name}은(는) 이미 변형 병합에 포함되어 있습니다",
    "Merged {count} objects for deformation": "변형을 위해 {count}개 오브젝트를 병합했습니다",
    "Edit Merged Source": "병합 원본 편집",
    "Select the source under the pointer from a deformation merge": "변형 병합에서 포인터 아래의 원본 오브젝트를 선택합니다",
    "Click a merged part to switch source | Double-click blank to return | Esc or Right Mouse exits": "병합 부분을 클릭해 원본 전환 | 빈 곳을 두 번 클릭해 돌아가기 | Esc 또는 오른쪽 클릭으로 종료",
    "Editing merged source: {name}": "병합 원본 편집 중: {name}",
    "Select this source while keeping the merged result visible": "병합 결과를 표시한 채 이 원본을 선택합니다",
    "Return to Merged Object": "병합 오브젝트로 돌아가기",
    "Hide the editable source and select its deformation merge": "편집 중인 원본을 숨기고 변형 병합을 선택합니다",
    "Unmerge and Restore Sources": "병합 해제 및 원본 복원",
    "Restore source visibility and remove the generated merged object": "원본 표시를 복원하고 생성된 병합 오브젝트를 제거합니다",
    "Restored sources from {name}": "{name}에서 원본 오브젝트를 복원했습니다",
    "Editing Source": "원본 편집 중",
    "Merged Sources": "병합 원본",
    "Merged Geometry": "병합 지오메트리",
    "Join Sources": "원본 결합",
    "World Transform": "월드 변환",
    "Source Index": "원본 인덱스",
    "Show Final Merged State While Editing Sources": "원본 편집 중 최종 병합 상태 표시",
    "Display the selected source after the merged object's full modifier stack": "병합 오브젝트의 전체 수정자 스택이 적용된 선택 원본을 표시합니다",
    "Add Cage to Final Source": "최종 상태 원본에 케이지 추가",
    "Add a cage that affects only the selected source after the merged object's current modifier stack": "병합 오브젝트의 현재 수정자 스택 뒤에서 선택한 원본에만 적용되는 케이지를 추가합니다",
    "The selected source has no evaluated surface geometry": "선택한 원본에 평가된 표면 지오메트리가 없습니다",
    "Could not configure the source cage filter": "원본 케이지 필터를 설정할 수 없습니다",
    "{name} Final Cage": "{name} 최종 상태 케이지",
    "Final Source Filter": "최종 상태 원본 필터",
    "Merged Source Index": "병합 원본 인덱스",
    "Source = {index}": "원본 = {index}",
    "Existing Source and Matching Index": "원본이 존재하고 인덱스가 일치함",
    "Return": "돌아가기",
    "Click a merged part to edit or switch source": "병합 부분을 클릭해 원본 편집 또는 전환",
    "Double-click blank to return | Esc or Right Mouse exits": "빈 곳을 두 번 클릭해 돌아가기 | Esc 또는 오른쪽 클릭으로 종료",
})


# Dedicated cage types and the additional layer controls were introduced
# after the original catalogs. Keep these additions grouped so every locale
# receives the same visible vocabulary without rewriting the historical table.
_CAGE_TYPES_ZH = {
    "Cage Type": "笼类型",
    "Choose a standard layered cage or a dedicated single-operation cage":
        "选择标准多层笼或单一操作专用笼",
    "Standard": "标准",
    "Standard Type": "标准型",
    "Point": "点",
    "Create a layered deformation cage": "创建多层形变笼",
    "Allow ordered Bend, Twist, Taper, and Stretch layers":
        "允许有序组合弯曲、扭转、锥化和拉伸层",
    "Shear Cage": "斜切型",
    "Create a dedicated shear cage": "创建专用斜切型笼",
    "Dedicated single-operation shear cage; cannot be chained or subdivided":
        "专用单一斜切型笼；不能链式创建或细分",
    "FFD Cage": "自由形变笼",
    "Create a dedicated free-form cage": "创建专用自由形变笼",
    "Dedicated single-operation free-form cage; cannot be chained or subdivided":
        "专用单一自由形态笼；不能链式创建或细分",
    "Shear": "斜切",
    "Slide cross-sections sideways along the cage axis":
        "沿笼轴横向滑动横截面",
    "Cage-local X and Z shear per unit of axial distance":
        "每单位轴向距离的笼局部 X 和 Z 剪切量",
    "FFD": "FFD",
    "Edit the eight corners of a trilinear free-form cage":
        "编辑三线性自由形态笼的八个角点",
    "FFD Corner Offsets": "FFD 角点偏移",
    "Eight cage-local XYZ offsets for the 2x2x2 FFD corners":
        "2x2x2 FFD 角点的八组笼局部 XYZ 偏移",
    "Temporarily bypass Shear": "临时跳过剪切",
    "Temporarily bypass FFD": "临时跳过 FFD",
    "Add Shear Cage": "添加斜切型",
    "Add FFD Cage": "添加自由形变笼",
    "Dedicated cage: one operation; chaining and subdivision are disabled.":
        "独立笼：单一操作；已禁用链式和细分。",
    "Dedicated cages cannot be subdivided; use a standard cage":
        "专用笼不能细分，请使用标准笼",
    "Dedicated {cage_type} cages cannot be chained":
        "专用 {cage_type} 笼不能链式创建",
    "Subdivide does not yet preserve these layers: {layers}":
        "细分暂不保留这些层：{layers}",
    "Show Twist": "显示扭转",
    "Show FFD Handles": "显示 FFD 手柄",
    "Show the eight editable free-form cage corner handles":
        "显示八个可编辑的自由形态笼角点手柄",
    "Cyan shear handle: drag in the cage plane":
        "青色剪切手柄：在笼平面内拖动",
    "Shear End-Face Handle": "剪切端面手柄",
    "Drag the center freely or an arm along cage X/Z; Alt locks X, Shift locks Z, Ctrl snaps":
        "拖动中心可自由剪切，拖动轴臂可沿笼 X/Z 限制；Alt 锁定 X，Shift 锁定 Z，Ctrl 吸附",
    "Center Free • Arm X/Z • Alt X • Shift Z • Ctrl Snap":
        "中心自由 • 轴臂 X/Z • Alt 锁定 X • Shift 锁定 Z • Ctrl 吸附",
    "FFD corners: drag in view • Alt along cage axis":
        "FFD 角点：在视图中拖动 • Alt 沿笼轴",
}
_CAGE_TYPES_JA = {
    "Cage Type": "ケージタイプ",
    "Choose a standard layered cage or a dedicated single-operation cage":
        "標準の多層ケージまたは単一操作専用ケージを選択",
    "Standard": "標準",
    "Standard Type": "標準型",
    "Point": "ポイント",
    "Create a layered deformation cage": "多層変形ケージを作成",
    "Allow ordered Bend, Twist, Taper, and Stretch layers":
        "曲げ、ねじり、テーパー、伸縮を順序付きで使用",
    "Shear Cage": "シアー型",
    "Create a dedicated shear cage": "専用シアーケージを作成",
    "Dedicated single-operation shear cage; cannot be chained or subdivided":
        "単一シアー専用ケージ。チェーン化・細分化不可",
    "FFD Cage": "自由変形ケージ",
    "Create a dedicated free-form cage": "専用フリーフォームケージを作成",
    "Dedicated single-operation free-form cage; cannot be chained or subdivided":
        "単一フリーフォーム専用ケージ。チェーン化・細分化不可",
    "Shear": "シアー",
    "Slide cross-sections sideways along the cage axis":
        "ケージ軸に沿って断面を横へスライド",
    "Cage-local X and Z shear per unit of axial distance":
        "軸方向距離あたりのケージローカル X/Z シアー",
    "FFD": "FFD",
    "Edit the eight corners of a trilinear free-form cage":
        "三線形フリーフォームケージの 8 つの角点を編集",
    "FFD Corner Offsets": "FFD 角点オフセット",
    "Eight cage-local XYZ offsets for the 2x2x2 FFD corners":
        "2x2x2 FFD 角点の 8 個のケージローカル XYZ オフセット",
    "Temporarily bypass Shear": "シアーを一時バイパス",
    "Temporarily bypass FFD": "FFD を一時バイパス",
    "Add Shear Cage": "シアー型を追加",
    "Add FFD Cage": "自由変形ケージを追加",
    "Dedicated cage: one operation; chaining and subdivision are disabled.":
        "専用ケージ: 単一操作。チェーン化と細分化は無効です。",
    "Dedicated cages cannot be subdivided; use a standard cage":
        "専用ケージは細分化できません。標準ケージを使用してください",
    "Dedicated {cage_type} cages cannot be chained":
        "専用 {cage_type} ケージはチェーン化できません",
    "Subdivide does not yet preserve these layers: {layers}":
        "細分化では次のレイヤーをまだ保持できません: {layers}",
    "Show Twist": "ねじりを表示",
    "Show FFD Handles": "FFD ハンドルを表示",
    "Show the eight editable free-form cage corner handles":
        "編集可能な 8 個のフリーフォーム角点ハンドルを表示",
    "Cyan shear handle: drag in the cage plane":
        "シアンのシアーハンドル: ケージ平面内をドラッグ",
    "Shear End-Face Handle": "シアー端面ハンドル",
    "Drag the center freely or an arm along cage X/Z; Alt locks X, Shift locks Z, Ctrl snaps":
        "中心は自由ドラッグ、アームはケージ X/Z に沿ってドラッグ。Alt で X、Shift で Z、Ctrl でスナップ",
    "Center Free • Arm X/Z • Alt X • Shift Z • Ctrl Snap":
        "中心は自由 • アーム X/Z • Alt X • Shift Z • Ctrl スナップ",
    "FFD corners: drag in view • Alt along cage axis":
        "FFD 角点: ビュー内をドラッグ • Alt でケージ軸方向",
}
_CAGE_TYPES_KO = {
    "Cage Type": "케이지 유형",
    "Choose a standard layered cage or a dedicated single-operation cage":
        "표준 다층 케이지 또는 단일 작업 전용 케이지 선택",
    "Standard": "표준",
    "Standard Type": "표준형",
    "Point": "포인트",
    "Create a layered deformation cage": "다층 변형 케이지 생성",
    "Allow ordered Bend, Twist, Taper, and Stretch layers":
        "구부리기, 비틀기, 테이퍼, 늘리기 레이어를 순서대로 사용",
    "Shear Cage": "전단형",
    "Create a dedicated shear cage": "전용 전단 케이지 생성",
    "Dedicated single-operation shear cage; cannot be chained or subdivided":
        "단일 전단 전용 케이지입니다. 체인화하거나 세분화할 수 없습니다",
    "FFD Cage": "자유 변형 케이지",
    "Create a dedicated free-form cage": "전용 자유형 케이지 생성",
    "Dedicated single-operation free-form cage; cannot be chained or subdivided":
        "단일 자유형 전용 케이지입니다. 체인화하거나 세분화할 수 없습니다",
    "Shear": "전단",
    "Slide cross-sections sideways along the cage axis":
        "케이지 축을 따라 단면을 옆으로 이동",
    "Cage-local X and Z shear per unit of axial distance":
        "축 방향 거리 단위의 케이지 로컬 X/Z 전단",
    "FFD": "FFD",
    "Edit the eight corners of a trilinear free-form cage":
        "삼선형 자유형 케이지의 8개 코너 편집",
    "FFD Corner Offsets": "FFD 코너 오프셋",
    "Eight cage-local XYZ offsets for the 2x2x2 FFD corners":
        "2x2x2 FFD 코너의 8개 케이지 로컬 XYZ 오프셋",
    "Temporarily bypass Shear": "전단 일시 우회",
    "Temporarily bypass FFD": "FFD 일시 우회",
    "Add Shear Cage": "전단형 추가",
    "Add FFD Cage": "자유 변형 케이지 추가",
    "Dedicated cage: one operation; chaining and subdivision are disabled.":
        "전용 케이지: 단일 작업만 제공하며 체인화와 세분화가 비활성화됩니다.",
    "Dedicated cages cannot be subdivided; use a standard cage":
        "전용 케이지는 세분화할 수 없습니다. 표준 케이지를 사용하세요",
    "Dedicated {cage_type} cages cannot be chained":
        "전용 {cage_type} 케이지는 체인화할 수 없습니다",
    "Subdivide does not yet preserve these layers: {layers}":
        "세분화에서 다음 레이어는 아직 보존되지 않습니다: {layers}",
    "Show Twist": "비틀기 표시",
    "Show FFD Handles": "FFD 핸들 표시",
    "Show the eight editable free-form cage corner handles":
        "편집 가능한 8개 자유형 케이지 코너 핸들 표시",
    "Cyan shear handle: drag in the cage plane":
        "시안 전단 핸들: 케이지 평면에서 드래그",
    "Shear End-Face Handle": "전단 끝면 핸들",
    "Drag the center freely or an arm along cage X/Z; Alt locks X, Shift locks Z, Ctrl snaps":
        "중앙은 자유 드래그, 축 핸들은 케이지 X/Z로 드래그합니다. Alt는 X, Shift는 Z, Ctrl은 스냅입니다",
    "Center Free • Arm X/Z • Alt X • Shift Z • Ctrl Snap":
        "중앙 자유 • 축 핸들 X/Z • Alt X • Shift Z • Ctrl 스냅",
    "FFD corners: drag in view • Alt along cage axis":
        "FFD 코너: 화면에서 드래그 • Alt로 케이지 축 방향 이동",
}
translations_dict.update(_CAGE_TYPES_ZH)
translations_ja_JP.update(_CAGE_TYPES_JA)
translations_ko_KR.update(_CAGE_TYPES_KO)


# Chained Origin was added after the original locale catalogs were authored.
# Keep the four visible labels in one small update block so all supported
# locales expose the same operator and panel vocabulary.
_CHAIN_ORIGIN_ZH = {
    "Origin": "起点",
    "Bottom": "底部",
    "Bottom (Recommended)": "\u5e95\u90e8\uff08\u63a8\u8350\uff09",
    "Top": "顶部",
    "Center": "中心",
    "Symmetric": "对称",
    "Non-Bottom origin may introduce subdivision errors":
        "\u975e\u5e95\u90e8\u8d77\u70b9\u7ec6\u5206\u53ef\u80fd\u4ea7\u751f\u8bef\u5dee",
    "Drag Along Cage • Shift Precise • Ctrl Move Both • Alt Opposite":
        "\u6cbf\u7b3c\u65b9\u5411\u62d6\u52a8 • Shift \u7cbe\u7ec6 • Ctrl \u540c\u5411\u79fb\u52a8\u4e24\u7aef • Alt \u53cd\u5411\u79fb\u52a8\u4e24\u7aef",
    "Large orange direction ring: drag around its center":
        "\u5927\u578b\u6a59\u8272\u65b9\u5411\u73af\uff1a\u56f4\u7ed5\u4e2d\u5fc3\u62d6\u52a8",
    "Deformation reference used by every cage in the chain":
        "链中每个笼使用的形变参考点",
    "Origin controls each chained cage's deformation reference.":
        "起点控制每个链式笼的形变参考点。",
}
_CHAIN_ORIGIN_JA = {
    "Origin": "原点",
    "Bottom": "下",
    "Bottom (Recommended)": "\u4e0b\u90e8\uff08\u63a8\u5968\uff09",
    "Top": "上",
    "Center": "中央",
    "Symmetric": "対称",
    "Non-Bottom origin may introduce subdivision errors":
        "\u4e0b\u90e8\u4ee5\u5916\u306e\u539f\u70b9\u3067\u306f\u7d30\u5206\u5316\u306b\u8aa4\u5dee\u304c\u751f\u3058\u308b\u5834\u5408\u304c\u3042\u308a\u307e\u3059",
    "Drag Along Cage • Shift Precise • Ctrl Move Both • Alt Opposite":
        "\u30b1\u30fc\u30b8\u306b\u6cbf\u3063\u3066\u30c9\u30e9\u30c3\u30b0 • Shift \u7cbe\u5bc6 • Ctrl \u4e21\u7aef\u3092\u540c\u65b9\u5411 • Alt \u4e21\u7aef\u3092\u9006\u65b9\u5411",
    "Large orange direction ring: drag around its center":
        "\u5927\u304d\u306a\u30aa\u30ec\u30f3\u30b8\u306e\u65b9\u5411\u30ea\u30f3\u30b0\uff1a\u4e2d\u5fc3\u306e\u5468\u308a\u3092\u30c9\u30e9\u30c3\u30b0",
    "Deformation reference used by every cage in the chain":
        "チェーン内の各ケージが使用する変形基準",
    "Origin controls each chained cage's deformation reference.":
        "原点は各チェーンケージの変形基準を制御します。",
}
_CHAIN_ORIGIN_KO = {
    "Origin": "원점",
    "Bottom": "하단",
    "Bottom (Recommended)": "\ud558\ub2e8(\uad8c\uc7a5)",
    "Top": "상단",
    "Center": "중앙",
    "Symmetric": "대칭",
    "Non-Bottom origin may introduce subdivision errors":
        "\ud558\ub2e8 \uc774\uc678\uc758 \uc6d0\uc810\uc740 \uc138\ubd84 \uc624\ucc28\ub97c \uc720\ubc1c\ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4",
    "Drag Along Cage • Shift Precise • Ctrl Move Both • Alt Opposite":
        "\ucf00\uc774\uc9c0\ub97c \ub530\ub77c \ub4dc\ub798\uadf8 • Shift \uc815\ubc00 • Ctrl \uc591 \ub05d \ud568\uaed8 \uc774\ub3d9 • Alt \uc591 \ub05d \ubc18\ub300\ub85c \uc774\ub3d9",
    "Large orange direction ring: drag around its center":
        "\ud070 \uc8fc\ud669\uc0c9 \ubc29\ud5a5 \ub9c1: \uc911\uc2ec \uc8fc\uc704\ub85c \ub4dc\ub798\uadf8",
    "Deformation reference used by every cage in the chain":
        "체인의 각 케이지가 사용하는 변형 기준",
    "Origin controls each chained cage's deformation reference.":
        "원점은 각 체인 케이지의 변형 기준을 제어합니다.",
}
translations_dict.update(_CHAIN_ORIGIN_ZH)
translations_ja_JP.update(_CHAIN_ORIGIN_JA)
translations_ko_KR.update(_CHAIN_ORIGIN_KO)


# Dedicated multi-point FFD controls. Keep these short labels translated so
# the compact N-panel remains readable in all supported locales.
_FFD_MULTI_ZH = {
    "Drag in View • Alt Cage Axis • Shift Precise • Ctrl Snap":
        "在视图中拖动 • Alt 沿笼轴 • Shift 精细 • Ctrl 吸附",
    "Show axis choices around the cage; the choices hide after selection unless Ctrl is held":
        "\u5728\u7b3c\u5468\u56f4\u663e\u793a\u8f74\u5411\u9009\u9879\uff1b\u9009\u62e9\u540e\u81ea\u52a8\u9690\u85cf\uff0c\u6309\u4f4f Ctrl \u53ef\u4fdd\u6301\u663e\u793a",
    "FFD Keyframe Scope": "FFD \u5173\u952e\u5e27\u8303\u56f4",
    "FFD Selection Mode": "FFD \u9009\u62e9\u6a21\u5f0f",
    "FFD Selection Modes": "FFD \u63a7\u5236\u5668\u7c7b\u578b",
    "Choose whether picking an FFD control selects one point, one adjacent U/V/W control-line segment, or one UV/UW/VW grid face":
        "\u9009\u62e9 FFD \u63a7\u5236\u5668\u65f6\uff0c\u9009\u62e9\u5355\u4e2a\u70b9\u3001\u76f8\u90bb\u7684 U/V/W \u63a7\u5236\u7ebf\u6bb5\u6216 UV/UW/VW \u7f51\u683c\u9762",
    "Point": "\u70b9",
    "Line": "\u7ebf",
    "Face": "\u9762",
    "FFD Control Line": "FFD \u63a7\u5236\u7ebf",
    "Drag this segment to move its two adjacent FFD control points":
        "\u62d6\u52a8\u6b64\u7ebf\u6bb5\u4ee5\u79fb\u52a8\u76f8\u90bb\u7684\u4e24\u4e2a FFD \u63a7\u5236\u70b9",
    "FFD Control Face": "FFD \u63a7\u5236\u9762",
    "Select one FFD control point": "\u9009\u62e9\u4e00\u4e2a FFD \u63a7\u5236\u70b9",
    "Select the line along the FFD deformation axis":
        "\u9009\u62e9\u6cbf FFD \u5f62\u53d8\u8f74\u7684\u6574\u6761\u7ebf",
    "Select one FFD cross-section face": "\u9009\u62e9\u4e00\u4e2a FFD \u6a2a\u622a\u9762",
    "Select any U, V, or W FFD control-line segment":
        "\u9009\u62e9\u4efb\u610f U\u3001V \u6216 W FFD \u63a7\u5236\u7ebf\u6bb5",
    "Show and select U/V/W FFD line-segment controllers":
        "\u663e\u793a\u5e76\u9009\u62e9 U/V/W FFD \u63a7\u5236\u7ebf\u6bb5",
    "Show and select FFD line-segment controllers":
        "\u663e\u793a\u5e76\u9009\u62e9 FFD \u63a7\u5236\u7ebf\u6bb5",
    "Select any UV, UW, or VW FFD grid face":
        "\u9009\u62e9\u4efb\u610f UV\u3001UW \u6216 VW FFD \u7f51\u683c\u9762",
    "Choose whether FFD I/Alt-I keys affect every visible point or only the selected points":
        "\u9009\u62e9 FFD I/Alt-I \u662f\u5426\u5f71\u54cd\u6240\u6709\u53ef\u89c1\u70b9\u6216\u4ec5\u5f53\u524d\u9009\u4e2d\u70b9",
    "All Visible Points": "\u6240\u6709\u53ef\u89c1\u70b9",
    "Key every visible FFD point; hidden hollow points are excluded":
        "\u4e3a\u6240\u6709\u53ef\u89c1 FFD \u70b9\u63d2\u5165\u5173\u952e\u5e27\uff1b\u4e2d\u7a7a\u6a21\u5f0f\u4e2d\u7684\u9690\u85cf\u70b9\u4f1a\u88ab\u6392\u9664",
    "Selected Points": "\u9009\u4e2d\u7684\u70b9",
    "Key only the selected FFD points": "\u4ec5\u4e3a\u9009\u4e2d\u7684 FFD \u70b9\u63d2\u5165\u5173\u952e\u5e27",
    "FFD U Points": "FFD U 点数",
    "FFD V Points": "FFD V 点数",
    "FFD W Points": "FFD W 点数",
    "Select FFD Points": "选择 FFD 控制点",
    "Selection": "选择",
    "Select every FFD control point": "选择全部 FFD 控制点",
    "Clear the FFD point selection": "取消选择 FFD 控制点",
    "Invert the FFD point selection": "反选 FFD 控制点",
    "Selected": "已选中",
    "Include this control point in the next viewport edit": "将此控制点加入下一次视图编辑",
    "Viewport handles edit selected points together.": "视图手柄会同时编辑已选控制点。",
    "FFD Control Point": "FFD 控制点",
    "Hollow FFD": "中空 FFD",
    "Use only the outside FFD control points; interior points are hidden and excluded from deformation":
        "仅使用 FFD 外表面控制点；内部点会隐藏且不参与形变",
    "Edit Mode": "编辑模式",
    "Edit FFD Points": "编辑 FFD 控制点",
    "Keep FFD point editing active; drag blank viewport space to box select and use Esc, right-click, or double-click blank space to exit":
        "保持 FFD 控制点编辑；在视口空白处拖动以框选，按 Esc、鼠标右键或双击空白处退出",
    "FFD Edit Mode": "FFD 编辑模式",
    "Whether persistent FFD point editing is active in the viewport":
        "是否在视口中启用持续 FFD 控制点编辑",
    "FFD Edit Mode: drag blank area to box select | G Move; G again Tangent Slide | R Rotate | S Scale | Shift Add | Ctrl Subtract | A Select All | Alt+A Clear | I Key | Alt+I Delete Key | Alt+R Reset | Double-click blank / Esc / Right Mouse exits":
        "FFD 编辑模式：拖动空白处框选 | G 移动；再次按 G 沿切向滑移 | R 旋转 | S 缩放 | Shift 加选 | Ctrl 减选 | A 全选 | Alt+A 清空 | I 插帧 | Alt+I 删除关键帧 | Alt+R 重置 | 双击空白 / Esc / 右键退出",
    "FFD Edit Mode: drag blank area to box select | G Move; G again Tangent Slide | R Rotate | S Scale | Shift Add | Ctrl Subtract | A Select All | Alt+A Clear | Double-click blank / Esc / Right Mouse exits":
        "FFD 编辑模式：拖动空白处框选 | G 移动；再次按 G 沿切向滑移 | R 旋转 | S 缩放 | Shift 加选 | Ctrl 减选 | A 全选 | Alt+A 清空 | 双击空白 / Esc / 右键退出",
    "Tangent Slide": "切向滑移",
    "Mouse Transform | G Tangent Slide | X/Y/Z Global; Repeat for Cage Local | Shift Precise | Ctrl Snap | Click/Enter Confirm | Esc/Right Mouse Cancel":
        "鼠标变换 | G 切向滑移 | X/Y/Z 全局轴；重复按同一轴切换笼局部轴 | Shift 精确 | Ctrl 吸附 | 单击/Enter 确认 | Esc/右键取消",
    "Mouse Slide Along Tangent | G Return to Move | Shift Precise | Ctrl Snap | Click/Enter Confirm | Esc/Right Mouse Cancel":
        "鼠标沿切向滑移 | G 返回移动 | Shift 精确 | Ctrl 吸附 | 单击/Enter 确认 | Esc/右键取消",
    "Mouse Transform | X/Y/Z Cage Axis | Shift Precise | Ctrl Snap | Click/Enter Confirm | Esc/Right Mouse Cancel":
        "鼠标变换 | X/Y/Z 笼局部轴 | Shift 精细 | Ctrl 吸附 | 单击/回车确认 | Esc/右键取消",
    "Select at least one FFD control point": "请至少选择一个 FFD 控制点",
    "Edit a multi-point free-form cage": "编辑多点自由形变笼",
    "Multi-point control data used by a dedicated FFD cage; values are edited in the viewport and can be keyed":
        "独立 FFD 笼使用的多点控制数据；可在视图中编辑并设置关键帧",
}
_FFD_MULTI_JA = {
    "Drag in View • Alt Cage Axis • Shift Precise • Ctrl Snap":
        "ビューでドラッグ • Alt ケージ軸方向 • Shift 精密 • Ctrl スナップ",
    "Show axis choices around the cage; the choices hide after selection unless Ctrl is held":
        "\u30b1\u30fc\u30b8\u5468\u56f2\u306b\u8ef8\u306e\u9078\u629e\u80a2\u3092\u8868\u793a\u3057\u307e\u3059\u3002\u9078\u629e\u5f8c\u306f\u975e\u8868\u793a\u306b\u306a\u308a\u3001Ctrl \u3092\u62bc\u3057\u3066\u3044\u308b\u9593\u306f\u8868\u793a\u3092\u7dad\u6301\u3057\u307e\u3059",
    "FFD Keyframe Scope": "FFD \u30ad\u30fc\u30d5\u30ec\u30fc\u30e0\u7bc4\u56f2",
    "FFD Selection Mode": "FFD \u9078\u629e\u30e2\u30fc\u30c9",
    "FFD Selection Modes": "FFD \u30b3\u30f3\u30c8\u30ed\u30fc\u30e9\u30fc\u30bf\u30a4\u30d7",
    "Choose whether picking an FFD control selects one point, one adjacent U/V/W control-line segment, or one UV/UW/VW grid face":
        "FFD \u30b3\u30f3\u30c8\u30ed\u30fc\u30eb\u3092\u9078\u629e\u3057\u305f\u3068\u304d\u3001\u70b9 1 \u3064\u3001\u96a3\u63a5\u3059\u308b U/V/W \u5236\u5fa1\u7dda\u5206 1 \u3064\u3001\u307e\u305f\u306f UV/UW/VW \u30b0\u30ea\u30c3\u30c9\u9762 1 \u3064\u3092\u9078\u629e\u3057\u307e\u3059",
    "Point": "\u70b9",
    "Line": "\u7dda",
    "Face": "\u9762",
    "FFD Control Line": "FFD \u5236\u5fa1\u7dda",
    "Drag this segment to move its two adjacent FFD control points":
        "\u3053\u306e\u7dda\u5206\u3092\u30c9\u30e9\u30c3\u30b0\u3057\u3066\u3001\u96a3\u63a5\u3059\u308b 2 \u3064\u306e FFD \u5236\u5fa1\u70b9\u3092\u79fb\u52d5",
    "FFD Control Face": "FFD \u5236\u5fa1\u9762",
    "Select one FFD control point": "FFD \u5236\u5fa1\u70b9\u3092 1 \u3064\u9078\u629e",
    "Select the line along the FFD deformation axis":
        "FFD \u5909\u5f62\u8ef8\u306b\u6cbf\u3063\u305f\u7dda\u3092\u9078\u629e",
    "Select one FFD cross-section face": "FFD \u6a2a\u65ad\u9762\u3092 1 \u3064\u9078\u629e",
    "Select any U, V, or W FFD control-line segment":
        "U\u3001V\u3001W \u306e\u4efb\u610f\u306e FFD \u5236\u5fa1\u7dda\u5206\u3092\u9078\u629e",
    "Show and select U/V/W FFD line-segment controllers":
        "U/V/W FFD \u5236\u5fa1\u7dda\u5206\u3092\u8868\u793a\u3057\u3066\u9078\u629e",
    "Show and select FFD line-segment controllers":
        "FFD \u7dda\u5206\u30b3\u30f3\u30c8\u30ed\u30fc\u30e9\u30fc\u3092\u8868\u793a\u3057\u3066\u9078\u629e",
    "Select any UV, UW, or VW FFD grid face":
        "UV\u3001UW\u3001VW \u306e\u4efb\u610f\u306e FFD \u30b0\u30ea\u30c3\u30c9\u9762\u3092\u9078\u629e",
    "Choose whether FFD I/Alt-I keys affect every visible point or only the selected points":
        "FFD I/Alt-I \u30ad\u30fc\u3067\u3059\u3079\u3066\u306e\u8868\u793a\u70b9\u3092\u5bfe\u8c61\u306b\u3059\u308b\u304b\u3001\u9078\u629e\u70b9\u3060\u3051\u3092\u5bfe\u8c61\u306b\u3059\u308b\u304b\u3092\u9078\u3076",
    "All Visible Points": "\u3059\u3079\u3066\u306e\u8868\u793a\u70b9",
    "Key every visible FFD point; hidden hollow points are excluded":
        "\u8868\u793a\u3055\u308c\u3066\u3044\u308b FFD \u30dd\u30a4\u30f3\u30c8\u3059\u3079\u3066\u306b\u30ad\u30fc\u3092\u8a2d\u5b9a\u3057\u3001\u4e2d\u7a7a\u30e2\u30fc\u30c9\u306e\u975e\u8868\u793a\u70b9\u306f\u9664\u5916\u3057\u307e\u3059",
    "Selected Points": "\u9078\u629e\u3057\u305f\u30dd\u30a4\u30f3\u30c8",
    "Key only the selected FFD points": "\u9078\u629e\u3057\u305f FFD \u30dd\u30a4\u30f3\u30c8\u3060\u3051\u306b\u30ad\u30fc\u3092\u8a2d\u5b9a\u3057\u307e\u3059",
    "FFD U Points": "FFD U 点数",
    "FFD V Points": "FFD V 点数",
    "FFD W Points": "FFD W 点数",
    "Select FFD Points": "FFD 制御点を選択",
    "Selection": "選択",
    "Select every FFD control point": "すべての FFD 制御点を選択",
    "Clear the FFD point selection": "FFD 制御点の選択を解除",
    "Invert the FFD point selection": "FFD 制御点の選択を反転",
    "Selected": "選択済み",
    "Include this control point in the next viewport edit": "次のビューポート編集にこの制御点を含める",
    "Viewport handles edit selected points together.": "ビューポートのハンドルで選択点をまとめて編集します。",
    "FFD Control Point": "FFD 制御点",
    "Hollow FFD": "中空 FFD",
    "Use only the outside FFD control points; interior points are hidden and excluded from deformation":
        "FFD の外側の制御点のみを使用し、内部点は非表示で変形から除外します",
    "Edit Mode": "編集モード",
    "Edit FFD Points": "FFD 制御点を編集",
    "Keep FFD point editing active; drag blank viewport space to box select and use Esc, right-click, or double-click blank space to exit":
        "FFD 制御点編集を継続し、ビューポートの空白をドラッグしてボックス選択します。Esc、右クリック、または空白のダブルクリックで終了します",
    "FFD Edit Mode": "FFD 編集モード",
    "Whether persistent FFD point editing is active in the viewport":
        "ビューポートで継続的な FFD 制御点編集が有効かどうか",
    "FFD Edit Mode: drag blank area to box select | G Move; G again Tangent Slide | R Rotate | S Scale | Shift Add | Ctrl Subtract | A Select All | Alt+A Clear | I Key | Alt+I Delete Key | Alt+R Reset | Double-click blank / Esc / Right Mouse exits":
        "FFD 編集モード：空白をドラッグしてボックス選択 | G 移動；もう一度 G で接線スライド | R 回転 | S スケール | Shift 追加 | Ctrl 除外 | A 全選択 | Alt+A 解除 | I キー挿入 | Alt+I キー削除 | Alt+R リセット | 空白をダブルクリック / Esc / 右クリックで終了",
    "FFD Edit Mode: drag blank area to box select | G Move; G again Tangent Slide | R Rotate | S Scale | Shift Add | Ctrl Subtract | A Select All | Alt+A Clear | Double-click blank / Esc / Right Mouse exits":
        "FFD 編集モード：空白をドラッグしてボックス選択 | G 移動；もう一度 G で接線スライド | R 回転 | S スケール | Shift 追加 | Ctrl 除外 | A 全選択 | Alt+A 解除 | 空白をダブルクリック / Esc / 右クリックで終了",
    "Tangent Slide": "接線スライド",
    "Mouse Transform | G Tangent Slide | X/Y/Z Global; Repeat for Cage Local | Shift Precise | Ctrl Snap | Click/Enter Confirm | Esc/Right Mouse Cancel":
        "マウス変形 | G 接線スライド | X/Y/Z グローバル軸；同じ軸を再入力でケージローカル | Shift 精密 | Ctrl スナップ | クリック/Enter 確定 | Esc/右クリック キャンセル",
    "Mouse Slide Along Tangent | G Return to Move | Shift Precise | Ctrl Snap | Click/Enter Confirm | Esc/Right Mouse Cancel":
        "マウスで接線方向にスライド | G で移動に戻る | Shift 精密 | Ctrl スナップ | クリック/Enter 確定 | Esc/右クリック キャンセル",
    "Mouse Transform | X/Y/Z Cage Axis | Shift Precise | Ctrl Snap | Click/Enter Confirm | Esc/Right Mouse Cancel":
        "マウスで変形 | X/Y/Z ケージローカル軸 | Shift 精密 | Ctrl スナップ | クリック/Enter 確定 | Esc/右クリック キャンセル",
    "Select at least one FFD control point": "FFD 制御点を1つ以上選択してください",
    "Edit a multi-point free-form cage": "多点自由形状ケージを編集",
    "Multi-point control data used by a dedicated FFD cage; values are edited in the viewport and can be keyed":
        "専用 FFD ケージの多点制御データ。ビューポートで編集してキーを設定できます",
}
_FFD_MULTI_KO = {
    "Drag in View • Alt Cage Axis • Shift Precise • Ctrl Snap":
        "뷰에서 드래그 • Alt 케이지 축 방향 • Shift 정밀 • Ctrl 스냅",
    "Show axis choices around the cage; the choices hide after selection unless Ctrl is held":
        "\ucf00\uc774\uc9c0 \uc8fc\ubcc0\uc5d0 \ucd95 \uc120\ud0dd \ud56d\ubaa9\uc744 \ud45c\uc2dc\ud569\ub2c8\ub2e4. \uc120\ud0dd \ud6c4\uc5d0\ub294 \uc228\uaca8\uc9c0\uba70 Ctrl\uc744 \ub204\ub974\ub294 \ub3d9\uc548\uc5d0\ub294 \ud45c\uc2dc\ub97c \uc720\uc9c0\ud569\ub2c8\ub2e4",
    "FFD Keyframe Scope": "FFD \ud0a4\ud504\ub808\uc784 \ubc94\uc704",
    "FFD Selection Mode": "FFD \uc120\ud0dd \ubaa8\ub4dc",
    "FFD Selection Modes": "FFD \uc81c\uc5b4\uae30 \uc720\ud615",
    "Choose whether picking an FFD control selects one point, one adjacent U/V/W control-line segment, or one UV/UW/VW grid face":
        "FFD \uc81c\uc5b4\ub97c \uc120\ud0dd\ud560 \ub54c \ud558\ub098\uc758 \uc810, \uc778\uc811\ud55c U/V/W \uc81c\uc5b4\uc120\ubd84 \ud558\ub098, \ub610\ub294 UV/UW/VW \uadf8\ub9ac\ub4dc \uba74 \ud558\ub098\ub97c \uc120\ud0dd\ud560\uc9c0 \uc120\ud0dd\ud569\ub2c8\ub2e4",
    "Point": "\uc810",
    "Line": "\uc120",
    "Face": "\uba74",
    "FFD Control Line": "FFD \uc81c\uc5b4\uc120",
    "Drag this segment to move its two adjacent FFD control points":
        "\uc774 \uc120\ubd84\uc744 \ub4dc\ub798\uadf8\ud574 \uc778\uc811\ud55c FFD \uc81c\uc5b4\uc810 \ub450 \uac1c\ub97c \uc774\ub3d9",
    "FFD Control Face": "FFD \uc81c\uc5b4\uba74",
    "Select one FFD control point": "FFD \uc81c\uc5b4\uc810 \ud558\ub098\ub97c \uc120\ud0dd",
    "Select the line along the FFD deformation axis":
        "FFD \ubcc0\ud615 \ucd95\uc744 \ub530\ub77c \uc120\uc744 \uc120\ud0dd",
    "Select one FFD cross-section face": "FFD \ud6a1\ub2e8\uba74 \ud558\ub098\ub97c \uc120\ud0dd",
    "Select any U, V, or W FFD control-line segment":
        "U\u3001V\u3001W FFD \uc81c\uc5b4\uc120\ubd84 \uc911 \ud558\ub098\ub97c \uc120\ud0dd",
    "Show and select U/V/W FFD line-segment controllers":
        "U/V/W FFD \uc81c\uc5b4\uc120\ubd84 \ucee8\ud2b8\ub864\ub7ec\ub97c \ud45c\uc2dc\ud558\uace0 \uc120\ud0dd",
    "Show and select FFD line-segment controllers":
        "FFD \uc81c\uc5b4\uc120\ubd84 \ucee8\ud2b8\ub864\ub7ec\ub97c \ud45c\uc2dc\ud558\uace0 \uc120\ud0dd",
    "Select any UV, UW, or VW FFD grid face":
        "UV\u3001UW\u3001VW FFD \uadf8\ub9ac\ub4dc \uba74 \uc911 \ud558\ub098\ub97c \uc120\ud0dd",
    "Choose whether FFD I/Alt-I keys affect every visible point or only the selected points":
        "FFD I/Alt-I \ud0a4\uac00 \ubaa8\ub4e0 \ud45c\uc2dc \ud3ec\uc778\ud2b8\ub97c \ub300\uc0c1\uc73c\ub85c \ud560\uc9c0, \uc120\ud0dd\ud55c \ud3ec\uc778\ud2b8\ub9cc \ub300\uc0c1\uc73c\ub85c \ud560\uc9c0 \uc120\ud0dd\ud569\ub2c8\ub2e4",
    "All Visible Points": "\ubaa8\ub4e0 \ud45c\uc2dc \ud3ec\uc778\ud2b8",
    "Key every visible FFD point; hidden hollow points are excluded":
        "\ud45c\uc2dc\ub41c \ubaa8\ub4e0 FFD \ud3ec\uc778\ud2b8\uc5d0 \ud0a4\ub97c \uc0bd\uc785\ud558\uba70, \uc911\uacf5 \ubaa8\ub4dc\uc758 \uc228\uaca8\uc9c4 \ud3ec\uc778\ud2b8\ub294 \uc81c\uc678\ud569\ub2c8\ub2e4",
    "Selected Points": "\uc120\ud0dd\ud55c \ud3ec\uc778\ud2b8",
    "Key only the selected FFD points": "\uc120\ud0dd\ud55c FFD \ud3ec\uc778\ud2b8\ub9cc \ud0a4\ub97c \uc0bd\uc785\ud569\ub2c8\ub2e4",
    "FFD U Points": "FFD U 포인트 수",
    "FFD V Points": "FFD V 포인트 수",
    "FFD W Points": "FFD W 포인트 수",
    "Select FFD Points": "FFD 제어점 선택",
    "Selection": "선택",
    "Select every FFD control point": "모든 FFD 제어점 선택",
    "Clear the FFD point selection": "FFD 제어점 선택 해제",
    "Invert the FFD point selection": "FFD 제어점 선택 반전",
    "Selected": "선택됨",
    "Include this control point in the next viewport edit": "다음 뷰포트 편집에 이 제어점 포함",
    "Viewport handles edit selected points together.": "뷰포트 핸들로 선택한 점을 함께 편집합니다.",
    "FFD Control Point": "FFD 제어점",
    "Hollow FFD": "중공 FFD",
    "Use only the outside FFD control points; interior points are hidden and excluded from deformation":
        "FFD 외부 제어점만 사용하며 내부 점은 숨겨지고 변형에서 제외됩니다",
    "Edit Mode": "편집 모드",
    "Edit FFD Points": "FFD 제어점 편집",
    "Keep FFD point editing active; drag blank viewport space to box select and use Esc, right-click, or double-click blank space to exit":
        "FFD 제어점 편집을 유지하고 뷰포트 빈 공간을 드래그하여 상자 선택합니다. Esc, 오른쪽 클릭 또는 빈 공간 두 번 클릭으로 종료합니다",
    "FFD Edit Mode": "FFD 편집 모드",
    "Whether persistent FFD point editing is active in the viewport":
        "뷰포트에서 지속적인 FFD 제어점 편집을 활성화할지 여부",
    "FFD Edit Mode: drag blank area to box select | G Move; G again Tangent Slide | R Rotate | S Scale | Shift Add | Ctrl Subtract | A Select All | Alt+A Clear | I Key | Alt+I Delete Key | Alt+R Reset | Double-click blank / Esc / Right Mouse exits":
        "FFD 편집 모드: 빈 공간 드래그로 상자 선택 | G 이동; G를 다시 눌러 접선 슬라이드 | R 회전 | S 크기 조절 | Shift 추가 | Ctrl 제외 | A 전체 선택 | Alt+A 선택 해제 | I 키 삽입 | Alt+I 키 삭제 | Alt+R 초기화 | 빈 공간 두 번 클릭 / Esc / 오른쪽 클릭으로 종료",
    "FFD Edit Mode: drag blank area to box select | G Move; G again Tangent Slide | R Rotate | S Scale | Shift Add | Ctrl Subtract | A Select All | Alt+A Clear | Double-click blank / Esc / Right Mouse exits":
        "FFD 편집 모드: 빈 공간 드래그로 상자 선택 | G 이동; G를 다시 눌러 접선 슬라이드 | R 회전 | S 크기 조절 | Shift 추가 | Ctrl 제외 | A 전체 선택 | Alt+A 선택 해제 | 빈 공간 두 번 클릭 / Esc / 오른쪽 클릭으로 종료",
    "Tangent Slide": "접선 슬라이드",
    "Mouse Transform | G Tangent Slide | X/Y/Z Global; Repeat for Cage Local | Shift Precise | Ctrl Snap | Click/Enter Confirm | Esc/Right Mouse Cancel":
        "마우스 변형 | G 접선 슬라이드 | X/Y/Z 전역 축; 같은 축을 다시 눌러 케이지 로컬 | Shift 정밀 | Ctrl 스냅 | 클릭/Enter 확인 | Esc/오른쪽 클릭 취소",
    "Mouse Slide Along Tangent | G Return to Move | Shift Precise | Ctrl Snap | Click/Enter Confirm | Esc/Right Mouse Cancel":
        "마우스로 접선을 따라 슬라이드 | G로 이동 모드 복귀 | Shift 정밀 | Ctrl 스냅 | 클릭/Enter 확인 | Esc/오른쪽 클릭 취소",
    "Mouse Transform | X/Y/Z Cage Axis | Shift Precise | Ctrl Snap | Click/Enter Confirm | Esc/Right Mouse Cancel":
        "마우스 변형 | X/Y/Z 케이지 로컬 축 | Shift 정밀 | Ctrl 스냅 | 클릭/Enter 확인 | Esc/오른쪽 클릭 취소",
    "Select at least one FFD control point": "FFD 제어점을 하나 이상 선택하세요",
    "Edit a multi-point free-form cage": "다중점 자유 변형 케이지 편집",
    "Multi-point control data used by a dedicated FFD cage; values are edited in the viewport and can be keyed":
        "전용 FFD 케이지의 다중점 제어 데이터입니다. 뷰포트에서 편집하고 키를 지정할 수 있습니다",
}
translations_dict.update(_FFD_MULTI_ZH)
translations_ja_JP.update(_FFD_MULTI_JA)
translations_ko_KR.update(_FFD_MULTI_KO)


_FFD_BOX_SELECT_HEADER = (
    "FFD Box Select: drag a rectangle over FFD points, lines, or faces | "
    "Esc / Right Mouse cancels"
)
_FFD_BOX_SELECT_ZH = {
    _FFD_BOX_SELECT_HEADER:
        "FFD \u6846\u9009\uff1a\u5728 FFD \u70b9\u3001\u7ebf\u6216\u9762\u4e0a\u62d6\u52a8\u7ed8\u5236\u77e9\u5f62 | Esc / \u53f3\u952e\u53d6\u6d88",
}
_FFD_BOX_SELECT_JA = {
    _FFD_BOX_SELECT_HEADER:
        "FFD \u30dc\u30c3\u30af\u30b9\u9078\u629e: FFD \u306e\u70b9\u3001\u7dda\u3001\u9762\u3092\u56f2\u3080\u3088\u3046\u306b\u30c9\u30e9\u30c3\u30b0 | Esc / \u53f3\u30af\u30ea\u30c3\u30af\u3067\u30ad\u30e3\u30f3\u30bb\u30eb",
}
_FFD_BOX_SELECT_KO = {
    _FFD_BOX_SELECT_HEADER:
        "FFD \uc0c1\uc790 \uc120\ud0dd: FFD \uc810, \uc120 \ub610\ub294 \uba74\uc744 \ub458\ub7ec\uc2f8\ub3c4\ub85d \ub4dc\ub798\uadf8 | Esc / \uc624\ub978\ucabd \ub9c8\uc6b0\uc2a4 \ubc84\ud2bc\uc73c\ub85c \ucde8\uc18c",
}
translations_dict.update(_FFD_BOX_SELECT_ZH)
translations_ja_JP.update(_FFD_BOX_SELECT_JA)
translations_ko_KR.update(_FFD_BOX_SELECT_KO)

_FFD_SYMMETRY_ZH = {
    "Symmetry": "\u5bf9\u79f0\u7f16\u8f91",
    "FFD Symmetry": "FFD \u5bf9\u79f0\u7f16\u8f91",
    "FFD Symmetry Axis": "FFD \u5bf9\u79f0\u8f74",
    "Mirror selected FFD points, lines, and faces across the chosen U, V, or W center plane":
        "\u5c06\u9009\u4e2d\u7684 FFD \u70b9\u3001\u7ebf\u548c\u9762\u955c\u50cf\u5230\u9009\u5b9a U\u3001V \u6216 W \u4e2d\u5fc3\u5e73\u9762",
    "FFD lattice axis whose center plane is used for mirrored editing":
        "\u7528\u4e8e\u955c\u50cf\u7f16\u8f91\u7684 FFD \u7b3c\u5c40\u90e8\u8f74\u4e2d\u5fc3\u5e73\u9762",
    "Mirror across the cage-local U center plane": "\u955c\u50cf\u5230\u7b3c\u5c40\u90e8 U \u4e2d\u5fc3\u5e73\u9762",
    "Mirror across the cage-local V center plane": "\u955c\u50cf\u5230\u7b3c\u5c40\u90e8 V \u4e2d\u5fc3\u5e73\u9762",
    "Mirror across the cage-local W center plane": "\u955c\u50cf\u5230\u7b3c\u5c40\u90e8 W \u4e2d\u5fc3\u5e73\u9762",
}
_FFD_SYMMETRY_JA = {
    "Symmetry": "\u5bfe\u79f0\u7de8\u96c6",
    "FFD Symmetry": "FFD \u5bfe\u79f0\u7de8\u96c6",
    "FFD Symmetry Axis": "FFD \u5bfe\u79f0\u8ef8",
    "Mirror selected FFD points, lines, and faces across the chosen U, V, or W center plane":
        "\u9078\u629e\u3057\u305f FFD \u306e\u70b9\u3001\u7dda\u3001\u9762\u3092\u9078\u629e\u3057\u305f U\u3001V\u3001W \u306e\u4e2d\u5fc3\u5e73\u9762\u3067\u30df\u30e9\u30fc\u7de8\u96c6",
    "FFD lattice axis whose center plane is used for mirrored editing":
        "\u30df\u30e9\u30fc\u7de8\u96c6\u306b\u4f7f\u7528\u3059\u308b FFD \u30b1\u30fc\u30b8\u30ed\u30fc\u30ab\u30eb\u8ef8",
    "Mirror across the cage-local U center plane": "\u30b1\u30fc\u30b8\u30ed\u30fc\u30ab\u30eb U \u306e\u4e2d\u5fc3\u5e73\u9762\u3067\u30df\u30e9\u30fc",
    "Mirror across the cage-local V center plane": "\u30b1\u30fc\u30b8\u30ed\u30fc\u30ab\u30eb V \u306e\u4e2d\u5fc3\u5e73\u9762\u3067\u30df\u30e9\u30fc",
    "Mirror across the cage-local W center plane": "\u30b1\u30fc\u30b8\u30ed\u30fc\u30ab\u30eb W \u306e\u4e2d\u5fc3\u5e73\u9762\u3067\u30df\u30e9\u30fc",
}
_FFD_SYMMETRY_KO = {
    "Symmetry": "\ub300\uce6d \ud3b8\uc9d1",
    "FFD Symmetry": "FFD \ub300\uce6d \ud3b8\uc9d1",
    "FFD Symmetry Axis": "FFD \ub300\uce6d \ucd95",
    "Mirror selected FFD points, lines, and faces across the chosen U, V, or W center plane":
        "\uc120\ud0dd\ud55c FFD \uc810\u3001\uc120\u3001\uba74\uc744 \uc120\ud0dd\ud55c U\u3001V\u3001W \uc911\uc2ec \ud3c9\uba74\uc5d0 \ub300\uce6d\ud574 \ud3b8\uc9d1\ud569\ub2c8\ub2e4",
    "FFD lattice axis whose center plane is used for mirrored editing":
        "\ub300\uce6d \ud3b8\uc9d1\uc5d0 \uc0ac\uc6a9\ud560 FFD \ucf00\uc774\uc9c0 \ub85c\uceec \ucd95",
    "Mirror across the cage-local U center plane": "\ucf00\uc774\uc9c0 \ub85c\uceec U \uc911\uc2ec \ud3c9\uba74\uc5d0 \ub300\uce6d",
    "Mirror across the cage-local V center plane": "\ucf00\uc774\uc9c0 \ub85c\uceec V \uc911\uc2ec \ud3c9\uba74\uc5d0 \ub300\uce6d",
    "Mirror across the cage-local W center plane": "\ucf00\uc774\uc9c0 \ub85c\uceec W \uc911\uc2ec \ud3c9\uba74\uc5d0 \ub300\uce6d",
}
translations_dict.update(_FFD_SYMMETRY_ZH)
translations_ja_JP.update(_FFD_SYMMETRY_JA)
translations_ko_KR.update(_FFD_SYMMETRY_KO)


_FFD_GUARD_ZH = {
    "FFD Safety": "FFD 安全保护",
    "Prevent Foldover": "防止翻折",
    "Prevent FFD cell foldover by using linear interpolation and clamping control-point edits to the last safe position":
        "使用线性插值，并将控制点编辑限制在 FFD 单元翻折前的最后安全位置",
    "Allow unrestricted FFD edits and the selected interpolation":
        "允许无限制 FFD 编辑和使用当前插值方式",
    "Use linear interpolation and stop edits before FFD cells invert":
        "使用线性插值，在 FFD 单元翻转前停止编辑",
}
_FFD_GUARD_JA = {
    "FFD Safety": "FFD 安全保護",
    "Prevent Foldover": "折れ防止",
    "Prevent FFD cell foldover by using linear interpolation and clamping control-point edits to the last safe position":
        "線形補間を使用し、FFD セルが反転する前の最後の安全位置に制限します",
    "Allow unrestricted FFD edits and the selected interpolation":
        "FFD 編集と選択した補間を制限しません",
    "Use linear interpolation and stop edits before FFD cells invert":
        "線形補間を使用し、FFD セルが反転する前で編集を停止します",
}
_FFD_GUARD_KO = {
    "FFD Safety": "FFD 안전 보호",
    "Prevent Foldover": "접힘 방지",
    "Prevent FFD cell foldover by using linear interpolation and clamping control-point edits to the last safe position":
        "선형 삽입을 사용하고 FFD 셀이 반전되기 전의 최종 안전 위치로 제어점 편집을 제한합니다",
    "Allow unrestricted FFD edits and the selected interpolation":
        "FFD 편집과 선택한 삽입을 제한하지 않습니다",
    "Use linear interpolation and stop edits before FFD cells invert":
        "선형 삽입을 사용하고 FFD 셀이 반전되기 전에 편집을 중지합니다",
}
translations_dict.update(_FFD_GUARD_ZH)
translations_ja_JP.update(_FFD_GUARD_JA)
translations_ko_KR.update(_FFD_GUARD_KO)


# Tooltips and compact controls added after the original locale catalogs.
_RECENT_UI_ZH = {
    "Professional Mode": "\u4e13\u4e1a\u6a21\u5f0f",
    "Hide Cage Controls, Deform Axis, Independent Ends, and Numeric Controls":
        "\u9690\u85cf\u7b3c\u63a7\u5236\u3001\u5f62\u53d8\u8f74\u3001\u72ec\u7acb\u7aef\u90e8\u548c\u6570\u503c\u63a7\u5236",
    "Show transform, fit, and cage-selection controls":
        "\u663e\u793a\u53d8\u6362\u3001\u5bf9\u9f50\u9002\u914d\u548c\u9009\u62e9\u7b3c\u7684\u63a7\u5236\u9879",
    "Show axis alignment controls for the active cage":
        "\u663e\u793a\u5f53\u524d\u7b3c\u7684\u8f74\u5411\u5bf9\u9f50\u63a7\u5236\u9879",
    "Drag to scale; Alt moves screen X; Shift moves screen Y; Alt+Shift moves freely":
        "拖动以缩放；Alt 沿屏幕 X 移动；Shift 沿屏幕 Y 移动；Alt+Shift 自由移动",
    "Drag this point to enter FFD Edit Mode; Shift toggles its selection; Alt moves along the cage axis":
        "拖动此控制点进入 FFD 编辑模式；Shift 切换其选择；Alt 沿笼轴移动",
    "FFD Corner": "FFD 角点",
    "FFD Bottom X- Z-": "FFD 底部 X- Z-",
    "FFD Bottom X+ Z-": "FFD 底部 X+ Z-",
    "FFD Bottom X+ Z+": "FFD 底部 X+ Z+",
    "FFD Bottom X- Z+": "FFD 底部 X- Z+",
    "FFD Top X- Z-": "FFD 顶部 X- Z-",
    "FFD Top X+ Z-": "FFD 顶部 X+ Z-",
    "FFD Top X+ Z+": "FFD 顶部 X+ Z+",
    "FFD Top X- Z+": "FFD 顶部 X- Z+",
    "Deformation Order": "形变顺序",
    "Expanded Deformation Layers": "已展开的形变层",
    "Deformation layers whose parameter rows are expanded":
        "参数行当前处于展开状态的形变层",
    "Expand every deformation layer": "展开全部形变层",
    "FFD Control Points": "FFD 控制点",
    "FFD Point": "FFD 控制点",
    "Local displacement of this FFD control point": "此 FFD 控制点的局部位移",
    "Active FFD point index used by the compact control panel":
        "紧凑控制面板使用的活动 FFD 控制点索引",
    "Number of control points across the cage X direction": "笼 X 方向的控制点数量",
    "Number of control points along the cage deformation axis": "沿笼形变轴的控制点数量",
    "Number of control points across the cage Z direction": "笼 Z 方向的控制点数量",
    "Reset FFD": "重置 FFD",
    "Return every FFD corner to the undeformed cage": "将所有 FFD 角点恢复到未变形笼",
    "Select all, none, or invert the dedicated FFD control points":
        "全选、取消全选或反选专用 FFD 控制点",
    "Show editable FFD control-point handles": "显示可编辑的 FFD 控制点手柄",
    "Show inline controls that edit several cages immediately":
        "显示可实时编辑多个笼的行内控件",
    "Show the ring used to adjust the Bend direction": "显示用于调整扭转角度的圆环",
    "X and Z scale applied to every affected cage end": "应用到每个受影响笼端部的 X、Z 缩放",
    "X and Z offset applied to every affected cage end": "应用到每个受影响笼端部的 X、Z 偏移",
    "Spacing before every affected downstream cage": "每个受影响下游笼之前的间隔",
    "Make this cage stage active": "激活此笼阶段",
    "Click a merged part to switch source; double-click blank to return":
        "单击合并体部件以切换源对象；双击空白处返回",
    "Combine ordered deformation layers in one cage.": "在一个笼中组合有序形变层。",
    "Legacy Mixed Bend Option": "旧版混合弯曲选项",
    "Compatibility option retained for saved operator settings; mixed Bend stacks now use the analytic chain evaluator":
        "为已保存的操作设置保留的兼容选项；混合弯曲堆栈现使用解析链求值器",
    "Legacy standard-cage XYZ offsets for the eight FFD corners":
        "旧版标准笼八个 FFD 角点的 XYZ 偏移",
}
_RECENT_UI_JA = {
    "Professional Mode": "\u30d7\u30ed\u30d5\u30a7\u30c3\u30b7\u30e7\u30ca\u30eb\u30e2\u30fc\u30c9",
    "Hide Cage Controls, Deform Axis, Independent Ends, and Numeric Controls":
        "\u30b1\u30fc\u30b8\u30b3\u30f3\u30c8\u30ed\u30fc\u30eb\u3001\u5909\u5f62\u8ef8\u3001\u500b\u5225\u7aef\u90e8\u3001\u6570\u5024\u30b3\u30f3\u30c8\u30ed\u30fc\u30eb\u3092\u975e\u8868\u793a\u306b\u3057\u307e\u3059",
    "Show transform, fit, and cage-selection controls":
        "\u5909\u63db\u3001\u30d5\u30a3\u30c3\u30c8\u3001\u30b1\u30fc\u30b8\u9078\u629e\u306e\u30b3\u30f3\u30c8\u30ed\u30fc\u30eb\u3092\u8868\u793a",
    "Show axis alignment controls for the active cage":
        "\u30a2\u30af\u30c6\u30a3\u30d6\u30b1\u30fc\u30b8\u306e\u8ef8\u5408\u308f\u305b\u30b3\u30f3\u30c8\u30ed\u30fc\u30eb\u3092\u8868\u793a",
    "Drag to scale; Alt moves screen X; Shift moves screen Y; Alt+Shift moves freely":
        "ドラッグで拡縮；Alt で画面 X 方向に移動；Shift で画面 Y 方向に移動；Alt+Shift で自由移動",
    "Drag this point to enter FFD Edit Mode; Shift toggles its selection; Alt moves along the cage axis":
        "この制御点をドラッグして FFD 編集モードに入り、Shift で選択を切替、Alt でケージ軸に沿って移動",
    "FFD Corner": "FFD コーナー",
    "FFD Bottom X- Z-": "FFD 下部 X- Z-",
    "FFD Bottom X+ Z-": "FFD 下部 X+ Z-",
    "FFD Bottom X+ Z+": "FFD 下部 X+ Z+",
    "FFD Bottom X- Z+": "FFD 下部 X- Z+",
    "FFD Top X- Z-": "FFD 上部 X- Z-",
    "FFD Top X+ Z-": "FFD 上部 X+ Z-",
    "FFD Top X+ Z+": "FFD 上部 X+ Z+",
    "FFD Top X- Z+": "FFD 上部 X- Z+",
    "Deformation Order": "変形順序",
    "Expanded Deformation Layers": "展開中の変形レイヤー",
    "Deformation layers whose parameter rows are expanded":
        "パラメータ行が展開されている変形レイヤー",
    "Expand every deformation layer": "すべての変形レイヤーを展開",
    "FFD Control Points": "FFD 制御点",
    "FFD Point": "FFD 制御点",
    "Local displacement of this FFD control point": "この FFD 制御点のローカル変位",
    "Active FFD point index used by the compact control panel":
        "コンパクト操作パネルで使用するアクティブ FFD 制御点のインデックス",
    "Number of control points across the cage X direction": "ケージ X 方向の制御点数",
    "Number of control points along the cage deformation axis": "ケージ変形軸方向の制御点数",
    "Number of control points across the cage Z direction": "ケージ Z 方向の制御点数",
    "Reset FFD": "FFD をリセット",
    "Return every FFD corner to the undeformed cage": "すべての FFD コーナーを未変形ケージに戻す",
    "Select all, none, or invert the dedicated FFD control points":
        "専用 FFD 制御点を全選択、全解除、または反転選択",
    "Show editable FFD control-point handles": "編集可能な FFD 制御点ハンドルを表示",
    "Show inline controls that edit several cages immediately":
        "複数ケージをリアルタイム編集するインライン操作を表示",
    "Show the ring used to adjust the Bend direction": "曲げ方向を調整するリングを表示",
    "X and Z scale applied to every affected cage end": "対象ケージ端部すべてに適用する X/Z スケール",
    "X and Z offset applied to every affected cage end": "対象ケージ端部すべてに適用する X/Z オフセット",
    "Spacing before every affected downstream cage": "対象となる下流ケージの前の間隔",
    "Make this cage stage active": "このケージステージをアクティブにする",
    "Click a merged part to switch source; double-click blank to return":
        "結合部分をクリックしてソースを切替；空白をダブルクリックして戻る",
    "Combine ordered deformation layers in one cage.": "順序付き変形レイヤーを 1 つのケージで組み合わせます。",
    "Legacy Mixed Bend Option": "旧式混合曲げオプション",
    "Compatibility option retained for saved operator settings; mixed Bend stacks now use the analytic chain evaluator":
        "保存済みオペレーター設定用の互換オプション；混合曲げスタックは解析チェーン評価を使用します",
    "Legacy standard-cage XYZ offsets for the eight FFD corners":
        "旧式標準ケージの 8 個の FFD コーナー用 XYZ オフセット",
}
_RECENT_UI_KO = {
    "Professional Mode": "\ud504\ub85c\ud398\uc154\ub110 \ubaa8\ub4dc",
    "Hide Cage Controls, Deform Axis, Independent Ends, and Numeric Controls":
        "\ucf00\uc774\uc9c0 \ucee8\ud2b8\ub864, \ubcc0\ud615 \ucd95, \ub3c5\ub9bd \ub05d\ubd80, \uc218\uce58 \ucee8\ud2b8\ub864 \ud45c\uc2dc \uc228\uae40",
    "Show transform, fit, and cage-selection controls":
        "\ubcc0\ud658, \ub9de\ucda4, \ucf00\uc774\uc9c0 \uc120\ud0dd \ucee8\ud2b8\ub864 \ud45c\uc2dc",
    "Show axis alignment controls for the active cage":
        "\ud65c\uc131 \ucf00\uc774\uc9c0\uc758 \ucd95 \uc815\ub82c \ucee8\ud2b8\ub864 \ud45c\uc2dc",
    "Drag to scale; Alt moves screen X; Shift moves screen Y; Alt+Shift moves freely":
        "드래그하여 크기 조절; Alt로 화면 X 이동; Shift로 화면 Y 이동; Alt+Shift로 자유 이동",
    "Drag this point to enter FFD Edit Mode; Shift toggles its selection; Alt moves along the cage axis":
        "이 제어점을 드래그하여 FFD 편집 모드로 진입; Shift로 선택 전환; Alt로 케이지 축을 따라 이동",
    "FFD Corner": "FFD 모서리점",
    "FFD Bottom X- Z-": "FFD 하단 X- Z-",
    "FFD Bottom X+ Z-": "FFD 하단 X+ Z-",
    "FFD Bottom X+ Z+": "FFD 하단 X+ Z+",
    "FFD Bottom X- Z+": "FFD 하단 X- Z+",
    "FFD Top X- Z-": "FFD 상단 X- Z-",
    "FFD Top X+ Z-": "FFD 상단 X+ Z-",
    "FFD Top X+ Z+": "FFD 상단 X+ Z+",
    "FFD Top X- Z+": "FFD 상단 X- Z+",
    "Deformation Order": "변형 순서",
    "Expanded Deformation Layers": "펼쳐진 변형 레이어",
    "Deformation layers whose parameter rows are expanded":
        "매개변수 행이 펼쳐진 변형 레이어",
    "Expand every deformation layer": "모든 변형 레이어 펼치기",
    "FFD Control Points": "FFD 제어점",
    "FFD Point": "FFD 제어점",
    "Local displacement of this FFD control point": "이 FFD 제어점의 로컬 변위",
    "Active FFD point index used by the compact control panel":
        "간단 제어 패널에서 사용하는 활성 FFD 제어점 인덱스",
    "Number of control points across the cage X direction": "케이지 X 방향 제어점 수",
    "Number of control points along the cage deformation axis": "케이지 변형 축 방향 제어점 수",
    "Number of control points across the cage Z direction": "케이지 Z 방향 제어점 수",
    "Reset FFD": "FFD 초기화",
    "Return every FFD corner to the undeformed cage": "모든 FFD 모서리점을 변형 전 케이지로 복원",
    "Select all, none, or invert the dedicated FFD control points":
        "전용 FFD 제어점을 모두 선택, 선택 해제 또는 반전 선택",
    "Show editable FFD control-point handles": "편집 가능한 FFD 제어점 핸들 표시",
    "Show inline controls that edit several cages immediately":
        "여러 케이지를 실시간 편집하는 인라인 컨트롤 표시",
    "Show the ring used to adjust the Bend direction": "굽힘 방향 조정 링 표시",
    "X and Z scale applied to every affected cage end": "영향받는 모든 케이지 끝에 적용할 X/Z 크기",
    "X and Z offset applied to every affected cage end": "영향받는 모든 케이지 끝에 적용할 X/Z 오프셋",
    "Spacing before every affected downstream cage": "영향받는 각 하류 케이지 앞의 간격",
    "Make this cage stage active": "이 케이지 단계를 활성화",
    "Click a merged part to switch source; double-click blank to return":
        "병합된 부분을 클릭하여 소스 전환; 빈 공간을 두 번 클릭하여 돌아가기",
    "Combine ordered deformation layers in one cage.": "정렬된 변형 레이어를 하나의 케이지에서 결합합니다.",
    "Legacy Mixed Bend Option": "이전 혼합 굽힘 옵션",
    "Compatibility option retained for saved operator settings; mixed Bend stacks now use the analytic chain evaluator":
        "저장된 작업 설정을 위한 호환 옵션; 혼합 굽힘 스택은 해석적 체인 평가기를 사용합니다",
    "Legacy standard-cage XYZ offsets for the eight FFD corners":
        "이전 표준 케이지의 8개 FFD 모서리점 XYZ 오프셋",
}
translations_dict.update(_RECENT_UI_ZH)
translations_ja_JP.update(_RECENT_UI_JA)
translations_ko_KR.update(_RECENT_UI_KO)


_FFD_DISPLAY_ZH = {
    "FFD Controller Display": "FFD \u63a7\u5236\u5668\u663e\u793a",
    "FFD Line Length": "FFD \u7ebf\u957f\u5ea6",
    "Visible FFD line-controller length as a percentage of its control line":
        "\u4ee5\u63a7\u5236\u7ebf\u957f\u5ea6\u7684\u767e\u5206\u6bd4\u663e\u793a FFD \u7ebf\u63a7\u5236\u5668",
    "FFD Line Width": "FFD \u7ebf\u5bbd",
    "Consistent viewport width for every FFD line controller":
        "\u6240\u6709 FFD \u7ebf\u63a7\u5236\u5668\u4fdd\u6301\u4e00\u81f4\u7684\u89c6\u56fe\u5bbd\u5ea6",
    "FFD Face Size": "FFD \u9762\u5c3a\u5bf8",
    "Visible FFD face-controller size as a percentage of its grid face":
        "\u4ee5\u7f51\u683c\u9762\u5c3a\u5bf8\u7684\u767e\u5206\u6bd4\u663e\u793a FFD \u9762\u63a7\u5236\u5668",
}

_FFD_DISPLAY_JA = {
    "FFD Controller Display": "FFD \u30b3\u30f3\u30c8\u30ed\u30fc\u30e9\u30fc\u8868\u793a",
    "FFD Line Length": "FFD \u7dda\u306e\u9577\u3055",
    "Visible FFD line-controller length as a percentage of its control line":
        "\u30b3\u30f3\u30c8\u30ed\u30fc\u30eb\u7dda\u306e\u9577\u3055\u306b\u5bfe\u3059\u308b\u5272\u5408\u3067 FFD \u7dda\u30b3\u30f3\u30c8\u30ed\u30fc\u30e9\u30fc\u3092\u8868\u793a",
    "FFD Line Width": "FFD \u7dda\u5e45",
    "Consistent viewport width for every FFD line controller":
        "\u3059\u3079\u3066\u306e FFD \u7dda\u30b3\u30f3\u30c8\u30ed\u30fc\u30e9\u30fc\u3067\u4e00\u5b9a\u306e\u30d3\u30e5\u30fc\u30dd\u30fc\u30c8\u5e45\u3092\u4f7f\u7528",
    "FFD Face Size": "FFD \u9762\u30b5\u30a4\u30ba",
    "Visible FFD face-controller size as a percentage of its grid face":
        "\u30b0\u30ea\u30c3\u30c9\u9762\u306e\u5927\u304d\u3055\u306b\u5bfe\u3059\u308b\u5272\u5408\u3067 FFD \u9762\u30b3\u30f3\u30c8\u30ed\u30fc\u30e9\u30fc\u3092\u8868\u793a",
}

_FFD_DISPLAY_KO = {
    "FFD Controller Display": "FFD \ucee8\ud2b8\ub864\ub7ec \ud45c\uc2dc",
    "FFD Line Length": "FFD \uc120 \uae38\uc774",
    "Visible FFD line-controller length as a percentage of its control line":
        "\uc81c\uc5b4\uc120 \uae38\uc774\uc5d0 \ub300\ud55c \ube44\uc728\ub85c FFD \uc120 \ucee8\ud2b8\ub864\ub7ec\ub97c \ud45c\uc2dc",
    "FFD Line Width": "FFD \uc120 \ub108\ube44",
    "Consistent viewport width for every FFD line controller":
        "\ubaa8\ub4e0 FFD \uc120 \ucee8\ud2b8\ub864\ub7ec\uc5d0 \uc77c\uad00\ub41c \ubdf0\ud3ec\ud2b8 \ub108\ube44 \uc0ac\uc6a9",
    "FFD Face Size": "FFD \uba74 \ud06c\uae30",
    "Visible FFD face-controller size as a percentage of its grid face":
        "\uadf8\ub9ac\ub4dc \uba74 \ud06c\uae30\uc5d0 \ub300\ud55c \ube44\uc728\ub85c FFD \uba74 \ucee8\ud2b8\ub864\ub7ec\ub97c \ud45c\uc2dc",
}

translations_dict.update(_FFD_DISPLAY_ZH)
translations_ja_JP.update(_FFD_DISPLAY_JA)
translations_ko_KR.update(_FFD_DISPLAY_KO)


_LATEST_UI_EN = {
    "FFD Edit": "FFD Edit",
    "Select and transform FFD points, lines, and faces":
        "Select and transform FFD points, lines, and faces",
    "Hide Deform Axis, Independent Ends, and Numeric Controls":
        "Hide Deform Axis, Independent Ends, and Numeric Controls",
    "FFD Symmetry Axes": "FFD Symmetry Axes",
    "Choose one or more FFD lattice center planes for mirrored editing":
        "Choose one or more FFD lattice center planes for mirrored editing",
    "Choose one FFD symmetry axis; hold Shift to enable or disable multiple axes":
        "Choose one FFD symmetry axis; hold Shift to enable or disable multiple axes",
    "Show editable FFD control-point, line, and face handles":
        "Show editable FFD control-point, line, and face handles",
    "Enable FFD handles in the add-on preferences first":
        "Enable FFD handles in the add-on preferences first",
    "Auto Sync": "Auto Sync",
    "Keep this cage's frame synchronized with the preceding cage's live deformation":
        "Keep this cage's frame synchronized with the preceding cage's live deformation",
    "Default Chain Auto Sync": "Default Chain Auto Sync",
    "Enable live downstream frame synchronization for newly-created cage chains":
        "Enable live downstream frame synchronization for newly-created cage chains",
}
_LATEST_UI_ZH = {
    "FFD Edit": "FFD \u7f16\u8f91",
    "Select and transform FFD points, lines, and faces":
        "\u9009\u62e9\u5e76\u53d8\u6362 FFD \u70b9\u3001\u7ebf\u548c\u9762",
    "Hide Deform Axis, Independent Ends, and Numeric Controls":
        "隐藏形变轴、独立端部和数值控制",
    "FFD Symmetry Axes": "FFD 对称轴",
    "Choose one or more FFD lattice center planes for mirrored editing":
        "选择一个或多个 FFD 笼中心平面进行镜像编辑",
    "Choose one FFD symmetry axis; hold Shift to enable or disable multiple axes":
        "选择一个 FFD 对称轴；按住 Shift 可启用或停用多个轴",
    "Show editable FFD control-point, line, and face handles":
        "显示可编辑的 FFD 点、线和面手柄",
    "Enable FFD handles in the add-on preferences first":
        "请先在插件首选项中启用 FFD 手柄",
    "Auto Sync": "自动同步",
    "Keep this cage's frame synchronized with the preceding cage's live deformation":
        "让此笼的框架实时跟随上一级笼的形变",
    "Default Chain Auto Sync": "链式笼默认自动同步",
    "Enable live downstream frame synchronization for newly-created cage chains":
        "为新创建的链式笼默认启用下游框架实时同步",
}
_LATEST_UI_JA = {
    "FFD Edit": "FFD \u7de8\u96c6",
    "Select and transform FFD points, lines, and faces":
        "FFD \u306e\u70b9\u3001\u7dda\u3001\u9762\u3092\u9078\u629e\u3057\u3066\u5909\u5f62",
    "Hide Deform Axis, Independent Ends, and Numeric Controls":
        "変形軸、個別端部、数値コントロールを非表示にします",
    "FFD Symmetry Axes": "FFD 対称軸",
    "Choose one or more FFD lattice center planes for mirrored editing":
        "ミラー編集に使用する FFD ラティスの中心平面を 1 つ以上選択",
    "Choose one FFD symmetry axis; hold Shift to enable or disable multiple axes":
        "FFD 対称軸を 1 つ選択。Shift を押しながら複数軸を切り替えます",
    "Show editable FFD control-point, line, and face handles":
        "編集可能な FFD の点・線・面ハンドルを表示",
    "Enable FFD handles in the add-on preferences first":
        "先にアドオン設定で FFD ハンドルを有効にしてください",
    "Auto Sync": "自動同期",
    "Keep this cage's frame synchronized with the preceding cage's live deformation":
        "このケージのフレームを前のケージの変形にリアルタイムで同期",
    "Default Chain Auto Sync": "チェーンの自動同期（デフォルト）",
    "Enable live downstream frame synchronization for newly-created cage chains":
        "新しく作成するケージチェーンで下流フレームのリアルタイム同期を有効化",
}
_LATEST_UI_KO = {
    "FFD Edit": "FFD \ud3b8\uc9d1",
    "Select and transform FFD points, lines, and faces":
        "FFD \uc810, \uc120, \uba74\uc744 \uc120\ud0dd\ud558\uace0 \ubcc0\ud615",
    "Hide Deform Axis, Independent Ends, and Numeric Controls":
        "변형 축, 독립 끝부분 및 수치 컨트롤을 숨깁니다",
    "FFD Symmetry Axes": "FFD 대칭 축",
    "Choose one or more FFD lattice center planes for mirrored editing":
        "미러 편집에 사용할 FFD 래티스 중심 평면을 하나 이상 선택합니다",
    "Choose one FFD symmetry axis; hold Shift to enable or disable multiple axes":
        "FFD 대칭 축을 하나 선택합니다. Shift를 누르면 여러 축을 켜거나 끌 수 있습니다",
    "Show editable FFD control-point, line, and face handles":
        "편집 가능한 FFD 점, 선, 면 핸들을 표시합니다",
    "Enable FFD handles in the add-on preferences first":
        "먼저 애드온 환경설정에서 FFD 핸들을 활성화하세요",
    "Auto Sync": "자동 동기화",
    "Keep this cage's frame synchronized with the preceding cage's live deformation":
        "이 케이지의 프레임을 이전 케이지의 실시간 변형에 동기화합니다",
    "Default Chain Auto Sync": "체인 기본 자동 동기화",
    "Enable live downstream frame synchronization for newly-created cage chains":
        "새로 만든 케이지 체인에서 하류 프레임 실시간 동기화를 활성화합니다",
}
_STACK_AUTO_SYNC_EN = {
    "Auto Reconnect": "Auto Reconnect",
    "Default Cage Auto Sync": "Default Cage Auto Sync",
    "Automatically fit newly-created non-chain cages when an earlier cage changes":
        "Automatically fit newly-created non-chain cages when an earlier cage changes",
    "Refit this ordinary cage to live geometry entering it after an earlier cage changes":
        "Refit this ordinary cage to live geometry entering it after an earlier cage changes",
    " | Proportional | Wheel Radius": " | Proportional | Wheel Radius",
}
_STACK_AUTO_SYNC_ZH = {
    "Auto Reconnect": "\u81ea\u52a8\u91cd\u65b0\u8fde\u63a5",
    "Default Cage Auto Sync": "\u7b3c\u9ed8\u8ba4\u81ea\u52a8\u540c\u6b65",
    "Automatically fit newly-created non-chain cages when an earlier cage changes":
        "\u5f53\u4e0a\u4e00\u7ea7\u7b3c\u53d8\u5316\u65f6\uff0c\u81ea\u52a8\u9002\u914d\u65b0\u5efa\u7684\u975e\u94fe\u5f0f\u7b3c",
    "Refit this ordinary cage to live geometry entering it after an earlier cage changes":
        "\u4e0a\u4e00\u7ea7\u7b3c\u53d8\u5316\u540e\uff0c\u8ba9\u6b64\u666e\u901a\u7b3c\u81ea\u52a8\u5bf9\u9f50\u5e76\u9002\u914d\u8f93\u5165\u5f62\u6001",
    " | Proportional | Wheel Radius": " | \u6bd4\u4f8b\u7f16\u8f91 | \u6eda\u8f6e\u8c03\u6574\u534a\u5f84",
}
_STACK_AUTO_SYNC_JA = {
    "Auto Reconnect": "\u81ea\u52d5\u518d\u63a5\u7d9a",
    "Default Cage Auto Sync": "\u30b1\u30fc\u30b8\u306e\u81ea\u52d5\u540c\u671f\uff08\u30c7\u30d5\u30a9\u30eb\u30c8\uff09",
    "Automatically fit newly-created non-chain cages when an earlier cage changes":
        "\u524d\u6bb5\u30b1\u30fc\u30b8\u306e\u5909\u66f4\u6642\u306b\u3001\u65b0\u898f\u306e\u975e\u30c1\u30a7\u30fc\u30f3\u30b1\u30fc\u30b8\u3092\u81ea\u52d5\u30d5\u30a3\u30c3\u30c8",
    "Refit this ordinary cage to live geometry entering it after an earlier cage changes":
        "\u524d\u6bb5\u30b1\u30fc\u30b8\u5909\u5f62\u5f8c\u306b\u3001\u3053\u306e\u901a\u5e38\u30b1\u30fc\u30b8\u3092\u5165\u529b\u5f62\u72b6\u3078\u81ea\u52d5\u30d5\u30a3\u30c3\u30c8",
    " | Proportional | Wheel Radius": " | \u30d7\u30ed\u30dd\u30fc\u30b7\u30e7\u30ca\u30eb | \u30db\u30a4\u30fc\u30eb\u534a\u5f84",
}
_STACK_AUTO_SYNC_KO = {
    "Auto Reconnect": "\uc790\ub3d9 \uc7ac\uc5f0\uacb0",
    "Default Cage Auto Sync": "\ucf00\uc774\uc9c0 \uae30\ubcf8 \uc790\ub3d9 \ub3d9\uae30\ud654",
    "Automatically fit newly-created non-chain cages when an earlier cage changes":
        "\uc774\uc804 \ucf00\uc774\uc9c0\uac00 \ubcc0\uacbd\ub418\uba74 \uc0c8\ub85c \ub9cc\ub4e0 \ube44\uccb4\uc778 \ucf00\uc774\uc9c0\ub97c \uc790\ub3d9\uc73c\ub85c \ub9de\ucda5\ub2c8\ub2e4",
    "Refit this ordinary cage to live geometry entering it after an earlier cage changes":
        "\uc774\uc804 \ucf00\uc774\uc9c0 \ubcc0\ud615 \ud6c4 \uc774 \uc77c\ubc18 \ucf00\uc774\uc9c0\ub97c \uc785\ub825 \ud615\uc0c1\uc5d0 \uc790\ub3d9\uc73c\ub85c \ub9de\ucda5\ub2c8\ub2e4",
    " | Proportional | Wheel Radius": " | \ube44\ub840 \ud3b8\uc9d1 | \ud720 \ubc18\uacbd",
}
translations_dict.update(_STACK_AUTO_SYNC_EN)
translations_dict.update(_STACK_AUTO_SYNC_ZH)
translations_ja_JP.update(_STACK_AUTO_SYNC_JA)
translations_ko_KR.update(_STACK_AUTO_SYNC_KO)

translations_dict.update(_LATEST_UI_EN)
translations_dict.update(_LATEST_UI_ZH)
translations_ja_JP.update(_LATEST_UI_JA)
translations_ko_KR.update(_LATEST_UI_KO)


# Same-type cage chains and multi-point FFD modes added in 2.4.32.
_CHAIN_FFD_FEATURE_ZH = {
    "Add Standard Cage": "添加标准型笼",
    "Add Standard Chain": "添加标准型链式笼",
    "Add Shear Chain": "添加斜切型链式笼",
    "Add FFD Chain": "添加 FFD 型链式笼",
    "Create a layered Standard chain": "创建由标准型笼组成的链式笼",
    "Create a Shear-only chain": "创建仅包含斜切型笼的链式笼",
    "Create an FFD-only chain": "创建仅包含 FFD 笼的链式笼",
    "Subdivided FFD cage into {count} chained stages":
        "已将 FFD 笼细分为 {count} 个链式阶段",
    "Could not subdivide FFD cage: {error}":
        "无法细分 FFD 笼：{error}",
    "U Interpolation": "U 插值",
    "V Interpolation": "V 插值",
    "W Interpolation": "W 插值",
    "Interpolation basis across the FFD cage U direction":
        "FFD 笼 U 方向的插值方式",
    "Interpolation basis along the FFD cage deformation axis":
        "FFD 笼形变轴方向的插值方式",
    "Interpolation basis across the FFD cage W direction":
        "FFD 笼 W 方向的插值方式",
    "Linear": "线性",
    "Cardinal": "Cardinal",
    "Catmull-Rom": "Catmull-Rom",
    "B-Spline": "B 样条",
    "Only points inside the cage are affected": "仅影响笼框内部的点",
    "Continue deformation beyond the cage": "将形变延伸到笼框之外",
    "The chain root extends continuously beyond both boundaries; later cages preserve the upstream prefix and continue from the cage end":
        "链根从两端边界连续延伸；后续笼保留上游前段并从笼末端继续",
    "Dedicated single-operation shear cage that can form a Shear chain":
        "可组成斜切型链式笼的单一斜切专用笼",
    "Dedicated single-operation free-form cage that can form an FFD chain":
        "可组成 FFD 链式笼的单一自由形变专用笼",
}
_CHAIN_FFD_FEATURE_JA = {
    "Add Standard Cage": "標準ケージを追加",
    "Add Standard Chain": "標準ケージチェーンを追加",
    "Add Shear Chain": "シアーケージチェーンを追加",
    "Add FFD Chain": "FFDケージチェーンを追加",
    "Create a layered Standard chain": "標準ケージで構成されたチェーンを作成",
    "Create a Shear-only chain": "シアー専用チェーンを作成",
    "Create an FFD-only chain": "FFD専用チェーンを作成",
    "Subdivided FFD cage into {count} chained stages":
        "FFDケージを {count} 個のチェーンステージに細分化しました",
    "Could not subdivide FFD cage: {error}":
        "FFDケージを細分化できませんでした: {error}",
    "U Interpolation": "U 補間",
    "V Interpolation": "V 補間",
    "W Interpolation": "W 補間",
    "Interpolation basis across the FFD cage U direction":
        "FFDケージ U 方向の補間方式",
    "Interpolation basis along the FFD cage deformation axis":
        "FFDケージ変形軸方向の補間方式",
    "Interpolation basis across the FFD cage W direction":
        "FFDケージ W 方向の補間方式",
    "Linear": "リニア",
    "Cardinal": "カーディナル",
    "Catmull-Rom": "Catmull-Rom",
    "B-Spline": "Bスプライン",
    "Only points inside the cage are affected": "ケージ内部の点だけを変形",
    "Continue deformation beyond the cage": "ケージの外側にも変形を継続",
    "The chain root extends continuously beyond both boundaries; later cages preserve the upstream prefix and continue from the cage end":
        "チェーンのルートは両端の境界を越えて連続し、後続ケージは上流部分を保持してケージ末端から続行します",
    "Dedicated single-operation shear cage that can form a Shear chain":
        "シアーチェーンを作成できるシアー専用ケージ",
    "Dedicated single-operation free-form cage that can form an FFD chain":
        "FFDチェーンを作成できる自由変形専用ケージ",
}
_CHAIN_FFD_FEATURE_KO = {
    "Add Standard Cage": "표준형 케이지 추가",
    "Add Standard Chain": "표준형 체인 케이지 추가",
    "Add Shear Chain": "전단형 체인 케이지 추가",
    "Add FFD Chain": "FFD 체인 케이지 추가",
    "Create a layered Standard chain": "표준형 케이지로 구성된 체인 생성",
    "Create a Shear-only chain": "전단 전용 체인 생성",
    "Create an FFD-only chain": "FFD 전용 체인 생성",
    "Subdivided FFD cage into {count} chained stages":
        "FFD 케이지를 체인 스테이지 {count}개로 세분했습니다",
    "Could not subdivide FFD cage: {error}":
        "FFD 케이지를 세분할 수 없음: {error}",
    "U Interpolation": "U 보간",
    "V Interpolation": "V 보간",
    "W Interpolation": "W 보간",
    "Interpolation basis across the FFD cage U direction":
        "FFD 케이지 U 방향 보간 방식",
    "Interpolation basis along the FFD cage deformation axis":
        "FFD 케이지 변형 축 방향 보간 방식",
    "Interpolation basis across the FFD cage W direction":
        "FFD 케이지 W 방향 보간 방식",
    "Linear": "선형",
    "Cardinal": "카디널",
    "Catmull-Rom": "Catmull-Rom",
    "B-Spline": "B 스플라인",
    "Only points inside the cage are affected": "케이지 내부의 점만 영향을 받음",
    "Continue deformation beyond the cage": "케이지 바깥까지 변형을 계속함",
    "The chain root extends continuously beyond both boundaries; later cages preserve the upstream prefix and continue from the cage end":
        "체인 루트는 양쪽 경계를 넘어 계속 연장되고 후속 케이지는 상류 구간을 유지하며 케이지 끝에서 이어집니다",
    "Dedicated single-operation shear cage that can form a Shear chain":
        "전단 체인을 만들 수 있는 전단 전용 케이지",
    "Dedicated single-operation free-form cage that can form an FFD chain":
        "FFD 체인을 만들 수 있는 자유 변형 전용 케이지",
}
translations_dict.update(_CHAIN_FFD_FEATURE_ZH)
translations_ja_JP.update(_CHAIN_FFD_FEATURE_JA)
translations_ko_KR.update(_CHAIN_FFD_FEATURE_KO)

# Override the early development strings above with clean UTF-8 catalog
# entries.  Those entries were once generated through a mismatched Windows
# code page and must not leak mojibake into the shipped interface.
_CHAIN_FFD_FEATURE_FIXED_ZH = {
    "Add Standard Cage": "添加标准型笼",
    "Add Standard Chain": "添加标准型链式笼",
    "Add Shear Cage": "添加斜切型笼",
    "Add Shear Chain": "添加斜切型链式笼",
    "Add FFD Cage": "添加 FFD 型笼",
    "Add FFD Chain": "添加 FFD 型链式笼",
    "Add an independent Standard layered cage": "添加一个独立的标准型分层笼",
    "Add an independent Shear cage": "添加一个独立的斜切型笼",
    "Add an independent FFD cage": "添加一个独立的 FFD 型笼",
    "Added Standard Cage stage": "已添加标准型笼阶段",
    "Added Shear Cage stage": "已添加斜切型笼阶段",
    "Added FFD Cage stage": "已添加 FFD 型笼阶段",
    "Create a layered deformation cage": "创建可分层组合形变的标准型笼",
    "Create a dedicated shear cage": "创建斜切专用笼",
    "Create a dedicated free-form cage": "创建自由形变专用笼",
    "Create a layered Standard chain": "创建仅由标准型笼组成的链式笼",
    "Create a Shear-only chain": "创建仅由斜切型笼组成的链式笼",
    "Create an FFD-only chain": "创建仅由 FFD 型笼组成的链式笼",
    "Standard Type": "标准型",
    "Shear Cage": "斜切型笼",
    "FFD Cage": "FFD 型笼",
    "Subdivided FFD cage into {count} chained stages":
        "已将 FFD 笼细分为 {count} 个链式阶段",
    "Could not subdivide FFD cage: {error}":
        "无法细分 FFD 笼：{error}",
    "U Interpolation": "U 插值",
    "V Interpolation": "V 插值",
    "W Interpolation": "W 插值",
    "Interpolation basis across the FFD cage U direction":
        "FFD 笼 U 方向使用的插值基函数",
    "Interpolation basis along the FFD cage deformation axis":
        "FFD 笼形变轴方向使用的插值基函数",
    "Interpolation basis across the FFD cage W direction":
        "FFD 笼 W 方向使用的插值基函数",
    "Linear": "线性",
    "Cardinal": "Cardinal",
    "Catmull-Rom": "Catmull-Rom",
    "B-Spline": "B 样条",
    "How geometry outside the cage is handled": "如何处理笼外几何体",
    "Deform inside; continue outside from the cage ends":
        "笼内发生形变，笼外从端面连续延伸",
    "Only points inside the cage are affected": "仅影响笼框内部的点",
    "Continue deformation beyond the cage": "将形变继续延伸到笼框之外",
    "Within Box": "框内",
    "Unlimited": "无限",
    "The chain root extends continuously beyond both boundaries; later cages preserve the upstream prefix and continue from the cage end":
        "链根从两端边界连续延伸；后续笼保留上游前段并从笼末端继续",
    "Dedicated single-operation shear cage that can form a Shear chain":
        "可组成斜切型链式笼的单一斜切专用笼",
    "Dedicated single-operation free-form cage that can form an FFD chain":
        "可组成 FFD 链式笼的单一自由形变专用笼",
}
_CHAIN_FFD_FEATURE_FIXED_JA = {
    "Add Standard Cage": "標準型ケージを追加",
    "Add Standard Chain": "標準型チェーンケージを追加",
    "Add Shear Cage": "シアー型ケージを追加",
    "Add Shear Chain": "シアー型チェーンケージを追加",
    "Add FFD Cage": "FFD型ケージを追加",
    "Add FFD Chain": "FFD型チェーンケージを追加",
    "Add an independent Standard layered cage": "独立した標準型レイヤーケージを追加",
    "Add an independent Shear cage": "独立したシアー型ケージを追加",
    "Add an independent FFD cage": "独立した FFD 型ケージを追加",
    "Added Standard Cage stage": "標準型ケージステージを追加しました",
    "Added Shear Cage stage": "シアー型ケージステージを追加しました",
    "Added FFD Cage stage": "FFD型ケージステージを追加しました",
    "Create a layered deformation cage": "変形を重ねられる標準型ケージを作成",
    "Create a dedicated shear cage": "シアー専用ケージを作成",
    "Create a dedicated free-form cage": "自由変形専用ケージを作成",
    "Create a layered Standard chain": "標準型ケージのみのチェーンを作成",
    "Create a Shear-only chain": "シアー型ケージのみのチェーンを作成",
    "Create an FFD-only chain": "FFD型ケージのみのチェーンを作成",
    "Standard Type": "標準型",
    "Shear Cage": "シアー型ケージ",
    "FFD Cage": "FFD型ケージ",
    "Subdivided FFD cage into {count} chained stages":
        "FFDケージを {count} 個のチェーンステージに細分しました",
    "Could not subdivide FFD cage: {error}":
        "FFDケージを細分できませんでした：{error}",
    "U Interpolation": "U 補間",
    "V Interpolation": "V 補間",
    "W Interpolation": "W 補間",
    "Interpolation basis across the FFD cage U direction":
        "FFDケージの U 方向で使用する補間基底",
    "Interpolation basis along the FFD cage deformation axis":
        "FFDケージの変形軸方向で使用する補間基底",
    "Interpolation basis across the FFD cage W direction":
        "FFDケージの W 方向で使用する補間基底",
    "Linear": "線形",
    "Cardinal": "Cardinal",
    "Catmull-Rom": "Catmull-Rom",
    "B-Spline": "Bスプライン",
    "How geometry outside the cage is handled": "ケージ外のジオメトリの処理方法",
    "Deform inside; continue outside from the cage ends":
        "ケージ内を変形し、外側は端面から連続させます",
    "Only points inside the cage are affected": "ケージ内の点だけに影響します",
    "Continue deformation beyond the cage": "ケージ外まで変形を延長します",
    "Within Box": "ケージ内",
    "Unlimited": "無制限",
    "The chain root extends continuously beyond both boundaries; later cages preserve the upstream prefix and continue from the cage end":
        "チェーンのルートは両端の境界を越えて連続し、後続ケージは上流部分を保持してケージ末端から続行します",
    "Dedicated single-operation shear cage that can form a Shear chain":
        "シアー型チェーンを構成できる単一操作のシアー専用ケージ",
    "Dedicated single-operation free-form cage that can form an FFD chain":
        "FFD型チェーンを構成できる単一操作の自由変形専用ケージ",
}
_CHAIN_FFD_FEATURE_FIXED_KO = {
    "Add Standard Cage": "표준형 케이지 추가",
    "Add Standard Chain": "표준형 체인 케이지 추가",
    "Add Shear Cage": "전단형 케이지 추가",
    "Add Shear Chain": "전단형 체인 케이지 추가",
    "Add FFD Cage": "FFD형 케이지 추가",
    "Add FFD Chain": "FFD형 체인 케이지 추가",
    "Add an independent Standard layered cage": "독립 표준형 레이어 케이지 추가",
    "Add an independent Shear cage": "독립 전단형 케이지 추가",
    "Add an independent FFD cage": "독립 FFD형 케이지 추가",
    "Added Standard Cage stage": "표준형 케이지 단계를 추가했습니다",
    "Added Shear Cage stage": "전단형 케이지 단계를 추가했습니다",
    "Added FFD Cage stage": "FFD형 케이지 단계를 추가했습니다",
    "Create a layered deformation cage": "변형을 겹쳐 사용할 수 있는 표준형 케이지 생성",
    "Create a dedicated shear cage": "전단 전용 케이지 생성",
    "Create a dedicated free-form cage": "자유 변형 전용 케이지 생성",
    "Create a layered Standard chain": "표준형 케이지로만 구성된 체인 생성",
    "Create a Shear-only chain": "전단형 케이지로만 구성된 체인 생성",
    "Create an FFD-only chain": "FFD형 케이지로만 구성된 체인 생성",
    "Standard Type": "표준형",
    "Shear Cage": "전단형 케이지",
    "FFD Cage": "FFD형 케이지",
    "Subdivided FFD cage into {count} chained stages":
        "FFD 케이지를 {count}개의 체인 단계로 세분했습니다",
    "Could not subdivide FFD cage: {error}":
        "FFD 케이지를 세분할 수 없습니다: {error}",
    "U Interpolation": "U 보간",
    "V Interpolation": "V 보간",
    "W Interpolation": "W 보간",
    "Interpolation basis across the FFD cage U direction":
        "FFD 케이지 U 방향에 사용할 보간 기저",
    "Interpolation basis along the FFD cage deformation axis":
        "FFD 케이지 변형축 방향에 사용할 보간 기저",
    "Interpolation basis across the FFD cage W direction":
        "FFD 케이지 W 방향에 사용할 보간 기저",
    "Linear": "선형",
    "Cardinal": "Cardinal",
    "Catmull-Rom": "Catmull-Rom",
    "B-Spline": "B-스플라인",
    "How geometry outside the cage is handled": "케이지 밖 지오메트리 처리 방식",
    "Deform inside; continue outside from the cage ends":
        "케이지 내부를 변형하고 외부는 끝면에서 연속시킵니다",
    "Only points inside the cage are affected": "케이지 내부의 점에만 영향을 줍니다",
    "Continue deformation beyond the cage": "케이지 밖까지 변형을 연장합니다",
    "Within Box": "케이지 내부",
    "Unlimited": "무제한",
    "The chain root extends continuously beyond both boundaries; later cages preserve the upstream prefix and continue from the cage end":
        "체인 루트는 양쪽 경계를 넘어 계속 연장되고 후속 케이지는 상류 구간을 유지하며 케이지 끝에서 이어집니다",
    "Dedicated single-operation shear cage that can form a Shear chain":
        "전단형 체인을 구성할 수 있는 단일 작업 전단 전용 케이지",
    "Dedicated single-operation free-form cage that can form an FFD chain":
        "FFD형 체인을 구성할 수 있는 단일 작업 자유 변형 전용 케이지",
}
translations_dict.update(_CHAIN_FFD_FEATURE_FIXED_ZH)
translations_ja_JP.update(_CHAIN_FFD_FEATURE_FIXED_JA)
translations_ko_KR.update(_CHAIN_FFD_FEATURE_FIXED_KO)


# Standard cages can now order Shear alongside the existing deformation
# layers. Keep the new description key separate from the legacy key so saved
# UI strings remain readable across versions.
_SHEAR_LAYER_DESCRIPTION_ZH = {
    "Allow ordered Bend, Twist, Taper, Stretch, and Shear layers":
        "\u5141\u8bb8\u6709\u5e8f\u7ec4\u5408\u5f2f\u66f2\u3001\u626d\u8f6c\u3001\u9525\u5316\u3001\u62c9\u4f38\u548c\u659c\u5207\u5c42",
}
_SHEAR_LAYER_DESCRIPTION_JA = {
    "Allow ordered Bend, Twist, Taper, Stretch, and Shear layers":
        "\u66f2\u3052\u3001\u306d\u3058\u308a\u3001\u30c6\u30fc\u30d1\u30fc\u3001\u4f38\u7e2e\u3001\u30b7\u30a2\u30fc\u3092\u9806\u5e8f\u4ed8\u304d\u3067\u4f7f\u7528",
}
_SHEAR_LAYER_DESCRIPTION_KO = {
    "Allow ordered Bend, Twist, Taper, Stretch, and Shear layers":
        "\uad6c\ubd80\ub9ac\uae30, \ube44\ud2c0\uae30, \ud14c\uc774\ud37c, \ub298\ub9ac\uae30, \uc804\ub2e8 \ub808\uc774\uc5b4\ub97c \uc21c\uc11c\ub300\ub85c \uc0ac\uc6a9",
}
translations_dict.update(_SHEAR_LAYER_DESCRIPTION_ZH)
translations_ja_JP.update(_SHEAR_LAYER_DESCRIPTION_JA)
translations_ko_KR.update(_SHEAR_LAYER_DESCRIPTION_KO)


_COLLECTION_AND_AXIS_ZH = {
    "Global": "全局",
    "Local": "局部",
    "Mouse Transform | X/Y/Z Global; Repeat for Cage Local | Shift Precise | Ctrl Snap | Click/Enter Confirm | Esc/Right Mouse Cancel":
        "鼠标变换 | X/Y/Z 全局轴；重复按同一轴切换笼局部轴 | Shift 精确 | Ctrl 吸附 | 单击/Enter 确认 | Esc/右键取消",
    "Merge Collection": "合并集合",
    "Merge Collection for Deform": "合并集合用于形变",
    "Create one live deformation mesh from every supported object in the selected collection and its child collections":
        "从所选集合及其子集合中的所有受支持对象创建一个实时形变网格",
    "Collection needs at least two supported objects":
        "集合中至少需要两个受支持的对象",
    "Merged {count} collection objects; skipped {skipped}":
        "已合并集合中的 {count} 个对象；已跳过 {skipped} 个",
    "Merged {count} collection objects": "已合并集合中的 {count} 个对象",
    "Deform Merge Collection": "形变合并集合",
    "Collection whose supported objects and child collections will be merged for deformation":
        "集合中受支持的对象及其子集合将被合并用于形变",
}
_COLLECTION_AND_AXIS_JA = {
    "Global": "グローバル",
    "Local": "ローカル",
    "Mouse Transform | X/Y/Z Global; Repeat for Cage Local | Shift Precise | Ctrl Snap | Click/Enter Confirm | Esc/Right Mouse Cancel":
        "マウス変形 | X/Y/Z グローバル軸；同じ軸を再入力でケージローカル | Shift 精密 | Ctrl スナップ | クリック/Enter 確定 | Esc/右クリック キャンセル",
    "Merge Collection": "コレクションをマージ",
    "Merge Collection for Deform": "変形用にコレクションをマージ",
    "Create one live deformation mesh from every supported object in the selected collection and its child collections":
        "選択したコレクションと子コレクション内の対応オブジェクトからライブ変形メッシュを作成",
    "Collection needs at least two supported objects":
        "コレクションには対応オブジェクトが2つ以上必要です",
    "Merged {count} collection objects; skipped {skipped}":
        "コレクションの {count} 個をマージし、{skipped} 個をスキップしました",
    "Merged {count} collection objects":
        "コレクションの {count} 個をマージしました",
    "Deform Merge Collection": "変形マージ用コレクション",
    "Collection whose supported objects and child collections will be merged for deformation":
        "対応オブジェクトと子コレクションを変形用にマージするコレクション",
}
_COLLECTION_AND_AXIS_KO = {
    "Global": "전역",
    "Local": "로컬",
    "Mouse Transform | X/Y/Z Global; Repeat for Cage Local | Shift Precise | Ctrl Snap | Click/Enter Confirm | Esc/Right Mouse Cancel":
        "마우스 변형 | X/Y/Z 전역 축; 같은 축을 다시 눌러 케이지 로컬 | Shift 정밀 | Ctrl 스냅 | 클릭/Enter 확인 | Esc/오른쪽 클릭 취소",
    "Merge Collection": "컬렉션 병합",
    "Merge Collection for Deform": "변형용 컬렉션 병합",
    "Create one live deformation mesh from every supported object in the selected collection and its child collections":
        "선택한 컬렉션과 하위 컬렉션의 지원 객체로 실시간 변형 메시를 만듭니다",
    "Collection needs at least two supported objects":
        "컬렉션에 지원되는 객체가 두 개 이상 필요합니다",
    "Merged {count} collection objects; skipped {skipped}":
        "컬렉션 객체 {count}개를 병합하고 {skipped}개를 건너뛰었습니다",
    "Merged {count} collection objects":
        "컬렉션 객체 {count}개를 병합했습니다",
    "Deform Merge Collection": "변형 병합 컬렉션",
    "Collection whose supported objects and child collections will be merged for deformation":
        "변형을 위해 지원 객체와 하위 컬렉션을 병합할 컬렉션",
}
translations_dict.update(_COLLECTION_AND_AXIS_ZH)
translations_ja_JP.update(_COLLECTION_AND_AXIS_JA)
translations_ko_KR.update(_COLLECTION_AND_AXIS_KO)


_MESH_ANIMATION_BAKE_ZH = {
    "Bake Mesh Animation": "烘焙网格动画",
    "Bake the evaluated cage animation to absolute shape keys on a new mesh object":
        "将求值后的笼动画烘焙为新网格物体上的绝对形态键",
    "Start Frame": "开始帧",
    "First scene frame to sample": "要采样的第一个场景帧",
    "End Frame": "结束帧",
    "Last scene frame to sample": "要采样的最后一个场景帧",
    "Sample Step": "采样步长",
    "Number of scene frames between baked shape keys":
        "每个烘焙形态键之间的场景帧数",
    "Result Name": "结果名称",
    "Name of the new independent mesh object": "新建独立网格物体的名称",
    "Hide Source": "隐藏源物体",
    "Hide the source object in the viewport and renders after a successful bake":
        "烘焙成功后在视图和渲染中隐藏源物体",
    "End Frame must not be earlier than Start Frame": "结束帧不能早于开始帧",
    "Sample Step must be at least 1": "采样步长至少为 1",
    "The evaluated geometry has no vertices": "求值后的几何体没有顶点",
    "The evaluated object could not be converted to a mesh":
        "无法将求值后的物体转换为网格",
    "Topology changes at frame {frame}; shape-key baking requires stable topology":
        "第 {frame} 帧的拓扑发生变化；形态键烘焙需要稳定拓扑",
    "Baked {count} frames to {name}": "已将 {count} 帧烘焙到 {name}",
}
_MESH_ANIMATION_BAKE_JA = {
    "Bake Mesh Animation": "メッシュアニメーションをベイク",
    "Bake the evaluated cage animation to absolute shape keys on a new mesh object":
        "評価済みのケージアニメーションを新しいメッシュオブジェクトの絶対シェイプキーにベイク",
    "Start Frame": "開始フレーム",
    "First scene frame to sample": "サンプリングする最初のシーンフレーム",
    "End Frame": "終了フレーム",
    "Last scene frame to sample": "サンプリングする最後のシーンフレーム",
    "Sample Step": "サンプル間隔",
    "Number of scene frames between baked shape keys":
        "ベイクするシェイプキー間のシーンフレーム数",
    "Result Name": "結果名",
    "Name of the new independent mesh object": "新しい独立メッシュオブジェクトの名前",
    "Hide Source": "ソースを非表示",
    "Hide the source object in the viewport and renders after a successful bake":
        "ベイク成功後にソースオブジェクトをビューポートとレンダーで非表示",
    "End Frame must not be earlier than Start Frame":
        "終了フレームを開始フレームより前にはできません",
    "Sample Step must be at least 1": "サンプル間隔は1以上にしてください",
    "The evaluated geometry has no vertices": "評価済みジオメトリに頂点がありません",
    "The evaluated object could not be converted to a mesh":
        "評価済みオブジェクトをメッシュに変換できません",
    "Topology changes at frame {frame}; shape-key baking requires stable topology":
        "フレーム {frame} でトポロジーが変化しました。シェイプキーのベイクには安定したトポロジーが必要です",
    "Baked {count} frames to {name}":
        "{count} フレームを {name} にベイクしました",
}
_MESH_ANIMATION_BAKE_KO = {
    "Bake Mesh Animation": "메시 애니메이션 베이크",
    "Bake the evaluated cage animation to absolute shape keys on a new mesh object":
        "평가된 케이지 애니메이션을 새 메시 오브젝트의 절대 셰이프 키로 베이크",
    "Start Frame": "시작 프레임",
    "First scene frame to sample": "샘플링할 첫 번째 장면 프레임",
    "End Frame": "종료 프레임",
    "Last scene frame to sample": "샘플링할 마지막 장면 프레임",
    "Sample Step": "샘플 간격",
    "Number of scene frames between baked shape keys":
        "베이크된 셰이프 키 사이의 장면 프레임 수",
    "Result Name": "결과 이름",
    "Name of the new independent mesh object": "새 독립 메시 오브젝트의 이름",
    "Hide Source": "원본 숨기기",
    "Hide the source object in the viewport and renders after a successful bake":
        "베이크 성공 후 원본 오브젝트를 뷰포트와 렌더에서 숨김",
    "End Frame must not be earlier than Start Frame":
        "종료 프레임은 시작 프레임보다 빠를 수 없습니다",
    "Sample Step must be at least 1": "샘플 간격은 1 이상이어야 합니다",
    "The evaluated geometry has no vertices": "평가된 지오메트리에 정점이 없습니다",
    "The evaluated object could not be converted to a mesh":
        "평가된 오브젝트를 메시로 변환할 수 없습니다",
    "Topology changes at frame {frame}; shape-key baking requires stable topology":
        "{frame} 프레임에서 토폴로지가 변경되었습니다. 셰이프 키 베이크에는 안정적인 토폴로지가 필요합니다",
    "Baked {count} frames to {name}":
        "{count}개 프레임을 {name}에 베이크했습니다",
}
translations_dict.update(_MESH_ANIMATION_BAKE_ZH)
translations_ja_JP.update(_MESH_ANIMATION_BAKE_JA)
translations_ko_KR.update(_MESH_ANIMATION_BAKE_KO)


_CURVE_CAGE_ZH = {
    "Control Mode": "\u63a7\u5236\u6a21\u5f0f",
    "Choose whether the complete source maps to the guide or the guide endpoints stay inside the cage":
        "选择将完整源笼与受控物体映射到曲线，或将曲线端点限制在笼内",
    "Map the complete source cage and controlled object to the complete guide; editing the guide changes deformation shape without changing source boundaries, cage length, or position":
        "将完整源笼与受控物体映射到整条引导曲线；编辑曲线只改变形变形状，不改变源边界、笼长度或位置",
    "Cage Mode": "\u7b3c\u6a21\u5f0f",
    "Keep the guide endpoints constrained inside the cage":
        "\u5c06\u66f2\u7ebf\u7aef\u70b9\u9650\u5236\u5728\u7b3c\u8303\u56f4\u5185",
    "Range Mode": "\u8303\u56f4\u6a21\u5f0f",
    "Curve Range Start": "曲线作用范围起点",
    "Lower effect boundary inside the stable Curve cage mapping domain":
        "稳定曲线笼映射域内的下方作用边界",
    "Curve Range End": "曲线作用范围终点",
    "Upper effect boundary inside the stable Curve cage mapping domain":
        "稳定曲线笼映射域内的上方作用边界",
    "Curve Cage": "曲线型笼",
    "Curve": "曲线",
    "Add Curve Cage": "添加曲线型笼",
    "Added Curve Cage stage": "已添加曲线型笼阶段",
    "Independent Bezier-guided cage with editable cross sections":
        "带有可编辑截面的独立贝塞尔引导笼",
    "Deform geometry along an editable Bezier guide":
        "沿可编辑的贝塞尔引导线形变几何体",
    "Temporarily bypass Curve": "临时关闭曲线形变",
    "Length Mode": "长度模式",
    "How cage-axis distance is mapped to the guide":
        "笼轴向距离映射到引导线的方式",
    "Preserve Length": "保持长度",
    "Map physical cage distance to guide arc length":
        "按实际笼距离映射到引导线弧长",
    "Stretch to Path": "拉伸至路径",
    "Use the complete guide and stretch the source along it":
        "使用完整引导线并沿路径拉伸源物体",
    "Fit Guide to Cage": "引导线适配笼",
    "Scale the complete guide shape to the authored cage length":
        "将完整引导线形状缩放到笼长度",
    "Boundary Mode": "边界模式",
    "How points beyond the Curve cage ends are handled":
        "曲线型笼端点外部顶点的处理方式",
    "Extend Tangents": "沿切线延伸",
    "Continue beyond each guide end along its endpoint tangent":
        "沿两端的端点切线继续延伸",
    "Clamp": "钳制",
    "Hold points beyond the mapped range at the guide endpoints":
        "将映射范围外的顶点保持在引导线端点",
    "Cage Only": "仅笼内",
    "Leave points outside the authored cage range unchanged":
        "保持笼范围外的顶点不变",
    "Compensate cross-section scale when stretching to the guide":
        "拉伸到引导线时补偿截面缩放",
    "Guide Resolution": "引导线分辨率",
    "Bezier evaluation resolution used by the Curve cage":
        "曲线型笼使用的贝塞尔求值分辨率",
    "Edit Guide": "编辑引导线",
    "Edit Curve Cage": "编辑曲线型笼",
    "Enter the managed guide's Curve Edit Mode; use Blender selection, G/R/S, handles, subdivide, extrude, and delete tools":
        "进入受管理引导线的曲线编辑模式；支持选择、G/R/S、手柄、细分、挤出和删除",
    "Cross Sections": "截面",
    "Cross Section {index}": "截面 {index}",
    "Active Guide Point": "活动引导点",
    "Roll": "滚转",
    "Radius": "半径",
    "Position": "位置",
    "Normalized position of this cross-section along the guide":
        "此截面沿引导线的归一化位置",
    "U / W Scale": "U / W 缩放",
    "Independent cross-section scale along the guide U and W axes":
        "沿引导线 U 和 W 轴的独立截面缩放",
    "U / W Offset": "U / W 偏移",
    "Cross-section center offset along the guide U and W axes":
        "截面中心沿引导线 U 和 W 轴的偏移",
    "Add Cross Section": "添加截面",
    "Insert an interpolated cross-section station": "插入一个插值截面站点",
    "Remove Cross Section": "移除截面",
    "Remove the active interior cross-section station": "移除活动的内部截面站点",
    "Reset Curve Guide": "重置曲线引导线",
    "Reset the guide to a straight path fitted to the cage":
        "将引导线重置为适配笼的直线路径",
    "Curve cages do not support chained creation": "曲线型笼暂不支持链式创建",
    "Curve cages cannot be subdivided into chains": "曲线型笼不能细分为链式笼",
    "Key the active cage parameters, end profiles, FFD controls, Curve guide and cross sections, and cage transform on the current frame":
        "在当前帧记录活动笼参数、端部形态、FFD 控制、曲线引导线与截面以及笼变换",
    "Curve Mode": "曲线模式",
    "How the Curve cage affects geometry beyond its authored range":
        "曲线型笼如何影响其设定范围之外的几何体",
    "Hold geometry beyond the range at the guide endpoints":
        "将超出范围的几何体保持在引导线端点",
    "Freeze the boundary frame and continue excluded geometry rigidly along its tangent":
        "冻结边界截面，并让范围外几何沿边界切线刚性延续",
    "Leave geometry outside the authored cage range unchanged":
        "保持设定笼范围外的几何体不变",
    "Extend open endpoints or repeat around a closed guide":
        "开放曲线沿端点延伸，闭合曲线则循环重复",
    "Closed Curve": "闭合曲线",
    "Join the first and last guide points into a continuous loop":
        "将首尾引导点连接成连续闭环",
    "Guide Points": "引导点",
    "Object-mode controls for the managed Bezier guide":
        "受管理贝塞尔引导线的物体模式控制",
    "Guide Point {index}": "引导点 {index}",
    "Point Count": "点数",
    "Number of evenly-spaced guide points after resampling":
        "等分重采样后的引导点数量",
    "Active Cross Section": "活动截面",
    "Editable U/W scale and offset stations along the Curve cage":
        "沿曲线型笼可编辑的 U/W 缩放与偏移截面",
    "Native Curve Edit Mode": "原生曲线编辑模式",
    "Curve Object Edit Mode": "曲线物体编辑模式",
    "Whether persistent object-mode guide editing is active":
        "是否在视图中保持物体模式引导线编辑",
    "Curve Point": "曲线点",
    "Select and move this Curve cage guide point":
        "选择并移动此曲线型笼引导点",
    "Bezier Handle": "贝塞尔手柄",
    "Adjust this guide point's Bezier tangent handle":
        "调整此引导点的贝塞尔切线手柄",
    "Linked Handles": "联动手柄",
    "Keep both Bezier handles mirrored until Alt makes one side independent":
        "保持两侧贝塞尔手柄镜像联动，直到按住 Alt 将一侧改为独立调整",
    "Linked handles move symmetrically; Alt makes this handle independent":
        "联动手柄会对称移动；按住 Alt 可将当前手柄改为独立调整",
    "Bevel": "倒角",
    "Blend this guide point from a sharp corner to a shared smooth tangent":
        "在尖角与共享平滑切线之间混合此引导点",
    "Tension": "张力",
    "Scale the Bezier handles around this guide point":
        "缩放此引导点周围的贝塞尔手柄",
    "Curve Point or Bezier Handle": "曲线点或贝塞尔手柄",
    "Curve Cage Controls": "曲线型笼控制器",
    "Edit Curve Points": "编辑曲线点",
    "Edit Curve cage points and Bezier handles persistently in Object Mode":
        "在物体模式下持续编辑曲线型笼点和贝塞尔手柄",
    "Curve Edit Mode": "曲线编辑模式",
    "Alt Independent Handle": "Alt 独立调整手柄",
    "X/Y/Z Axis | Shift Precise | Ctrl Snap | Click/Enter Confirm | Esc/Right Mouse Cancel":
        "X/Y/Z 轴 | Shift 精调 | Ctrl 吸附 | 单击/Enter 确认 | Esc/右键取消",
    "Curve Box Select: drag over points or handles | Shift Add | Ctrl Subtract | Esc cancels":
        "曲线框选：拖过点或手柄 | Shift 添加 | Ctrl 减选 | Esc 取消",
    "Curve Edit Mode: G Move | R Rotate | S Scale | B Box Select | Shift Add | A Select All | Alt+A Clear | I Key | Double-click blank / Esc / Right Mouse exits":
        "曲线编辑模式：G 移动 | R 旋转 | S 缩放 | B 框选 | Shift 添加 | A 全选 | Alt+A 清除 | I 插帧 | 双击空白/Esc/右键退出",
    "Object Edit": "物体编辑",
    "Native Edit": "原生编辑",
    "Equalize": "等分",
    "Equalize Curve Points": "等分曲线点",
    "Redistribute guide points uniformly by curve arc length":
        "按曲线弧长均匀重排引导点",
    "Remove or bake guide-point animation before equalizing points":
        "等分前请移除或烘焙引导点动画",
    "Equalized curve to {count} points": "已将曲线等分为 {count} 个点",
}

_CURVE_CAGE_JA = {
    "Control Mode": "\u5236\u5fa1\u30e2\u30fc\u30c9",
    "Choose whether the complete source maps to the guide or the guide endpoints stay inside the cage":
        "ソースケージ全体と制御対象をガイドへマッピングするか、ガイド端点をケージ内に制限するかを選択",
    "Map the complete source cage and controlled object to the complete guide; editing the guide changes deformation shape without changing source boundaries, cage length, or position":
        "ソースケージ全体と制御対象をガイド全体へマッピングします。ガイド編集は変形形状のみを変更し、ソース境界、ケージの長さ、位置は変更しません",
    "Cage Mode": "\u30b1\u30fc\u30b8\u30e2\u30fc\u30c9",
    "Keep the guide endpoints constrained inside the cage":
        "\u30ac\u30a4\u30c9\u306e\u7aef\u70b9\u3092\u30b1\u30fc\u30b8\u5185\u306b\u5236\u9650",
    "Range Mode": "\u7bc4\u56f2\u30e2\u30fc\u30c9",
    "Curve Range Start": "カーブ作用範囲の開始",
    "Lower effect boundary inside the stable Curve cage mapping domain":
        "安定したカーブケージのマッピング領域内にある下側の作用境界",
    "Curve Range End": "カーブ作用範囲の終了",
    "Upper effect boundary inside the stable Curve cage mapping domain":
        "安定したカーブケージのマッピング領域内にある上側の作用境界",
    "Curve Cage": "カーブケージ",
    "Curve": "カーブ",
    "Add Curve Cage": "カーブケージを追加",
    "Added Curve Cage stage": "カーブケージステージを追加しました",
    "Independent Bezier-guided cage with editable cross sections":
        "編集可能な断面を持つ独立ベジェガイドケージ",
    "Deform geometry along an editable Bezier guide":
        "編集可能なベジェガイドに沿ってジオメトリを変形",
    "Temporarily bypass Curve": "カーブ変形を一時的に無効化",
    "Length Mode": "長さモード",
    "How cage-axis distance is mapped to the guide":
        "ケージ軸距離をガイドへ割り当てる方法",
    "Preserve Length": "長さを維持",
    "Map physical cage distance to guide arc length":
        "実際のケージ距離をガイドの弧長へ割り当てます",
    "Stretch to Path": "パスへストレッチ",
    "Use the complete guide and stretch the source along it":
        "ガイド全体を使用してソースを沿わせて伸縮します",
    "Fit Guide to Cage": "ガイドをケージへ適合",
    "Scale the complete guide shape to the authored cage length":
        "ガイド形状全体をケージ長へ拡縮します",
    "Boundary Mode": "境界モード",
    "How points beyond the Curve cage ends are handled":
        "カーブケージ端の外側にある点の処理方法",
    "Extend Tangents": "接線方向へ延長",
    "Continue beyond each guide end along its endpoint tangent":
        "各端点の接線に沿ってガイド外へ延長します",
    "Clamp": "クランプ",
    "Hold points beyond the mapped range at the guide endpoints":
        "範囲外の点をガイド端点に固定します",
    "Cage Only": "ケージ内のみ",
    "Leave points outside the authored cage range unchanged":
        "ケージ範囲外の点を変更しません",
    "Compensate cross-section scale when stretching to the guide":
        "ガイドへ伸縮するとき断面スケールを補正します",
    "Guide Resolution": "ガイド解像度",
    "Bezier evaluation resolution used by the Curve cage":
        "カーブケージで使用するベジェ評価解像度",
    "Edit Guide": "ガイドを編集",
    "Edit Curve Cage": "カーブケージを編集",
    "Enter the managed guide's Curve Edit Mode; use Blender selection, G/R/S, handles, subdivide, extrude, and delete tools":
        "管理ガイドのカーブ編集モードに入り、選択、G/R/S、ハンドル、細分化、押し出し、削除を使用します",
    "Cross Sections": "断面",
    "Cross Section {index}": "断面 {index}",
    "Active Guide Point": "アクティブガイド点",
    "Roll": "ロール",
    "Radius": "半径",
    "Position": "位置",
    "Normalized position of this cross-section along the guide":
        "ガイドに沿った断面の正規化位置",
    "U / W Scale": "U / W スケール",
    "Independent cross-section scale along the guide U and W axes":
        "ガイドの U/W 軸に沿う独立断面スケール",
    "U / W Offset": "U / W オフセット",
    "Cross-section center offset along the guide U and W axes":
        "ガイドの U/W 軸に沿う断面中心オフセット",
    "Add Cross Section": "断面を追加",
    "Insert an interpolated cross-section station": "補間断面ステーションを挿入します",
    "Remove Cross Section": "断面を削除",
    "Remove the active interior cross-section station": "アクティブな内部断面を削除します",
    "Reset Curve Guide": "カーブガイドをリセット",
    "Reset the guide to a straight path fitted to the cage":
        "ガイドをケージに合う直線へリセットします",
    "Curve cages do not support chained creation": "カーブケージはチェーン作成に未対応です",
    "Curve cages cannot be subdivided into chains": "カーブケージはチェーンへ細分化できません",
    "Key the active cage parameters, end profiles, FFD controls, Curve guide and cross sections, and cage transform on the current frame":
        "現在のフレームにケージパラメータ、端部形状、FFD、カーブガイド、断面、ケージ変換を記録します",
    "Curve Mode": "カーブモード",
    "How the Curve cage affects geometry beyond its authored range":
        "カーブケージが設定範囲外のジオメトリに与える影響",
    "Hold geometry beyond the range at the guide endpoints":
        "範囲外のジオメトリをガイド端点に固定します",
    "Freeze the boundary frame and continue excluded geometry rigidly along its tangent":
        "境界フレームを固定し、範囲外のジオメトリを接線方向へ剛体的に延長します",
    "Leave geometry outside the authored cage range unchanged":
        "設定したケージ範囲外のジオメトリを変更しません",
    "Extend open endpoints or repeat around a closed guide":
        "開いた端点では延長し、閉じたガイドでは周回を繰り返します",
    "Closed Curve": "閉じたカーブ",
    "Join the first and last guide points into a continuous loop":
        "最初と最後のガイド点を連続したループとして接続します",
    "Guide Points": "ガイド点",
    "Object-mode controls for the managed Bezier guide":
        "管理されたベジェガイドのオブジェクトモード操作",
    "Guide Point {index}": "ガイド点 {index}",
    "Point Count": "点数",
    "Number of evenly-spaced guide points after resampling":
        "再サンプリング後の等間隔ガイド点数",
    "Active Cross Section": "アクティブ断面",
    "Editable U/W scale and offset stations along the Curve cage":
        "カーブケージに沿った編集可能な U/W スケールとオフセット断面",
    "Native Curve Edit Mode": "ネイティブカーブ編集モード",
    "Curve Object Edit Mode": "カーブオブジェクト編集モード",
    "Whether persistent object-mode guide editing is active":
        "ビューポートでオブジェクトモードのガイド編集を継続するか",
    "Curve Point": "カーブ点",
    "Select and move this Curve cage guide point":
        "このカーブケージのガイド点を選択して移動します",
    "Bezier Handle": "ベジェハンドル",
    "Adjust this guide point's Bezier tangent handle":
        "このガイド点のベジェ接線ハンドルを調整します",
    "Linked Handles": "連動ハンドル",
    "Keep both Bezier handles mirrored until Alt makes one side independent":
        "Alt で片側を独立させるまで、両方のベジェハンドルを鏡像連動させます",
    "Linked handles move symmetrically; Alt makes this handle independent":
        "連動ハンドルは対称に移動し、Alt で現在のハンドルを独立させます",
    "Bevel": "ベベル",
    "Blend this guide point from a sharp corner to a shared smooth tangent":
        "このガイド点を鋭角から共有スムーズ接線へ補間します",
    "Tension": "テンション",
    "Scale the Bezier handles around this guide point":
        "このガイド点の周囲のベジェハンドルを拡縮します",
    "Curve Point or Bezier Handle": "カーブ点またはベジェハンドル",
    "Curve Cage Controls": "カーブケージコントロール",
    "Edit Curve Points": "カーブ点を編集",
    "Edit Curve cage points and Bezier handles persistently in Object Mode":
        "オブジェクトモードでカーブケージの点とベジェハンドルを継続的に編集します",
    "Curve Edit Mode": "カーブ編集モード",
    "Alt Independent Handle": "Alt ハンドルを個別調整",
    "X/Y/Z Axis | Shift Precise | Ctrl Snap | Click/Enter Confirm | Esc/Right Mouse Cancel":
        "X/Y/Z 軸 | Shift 精密 | Ctrl スナップ | クリック/Enter 確定 | Esc/右クリック キャンセル",
    "Curve Box Select: drag over points or handles | Shift Add | Ctrl Subtract | Esc cancels":
        "カーブボックス選択：点またはハンドルをドラッグ | Shift 追加 | Ctrl 除外 | Esc キャンセル",
    "Curve Edit Mode: G Move | R Rotate | S Scale | B Box Select | Shift Add | A Select All | Alt+A Clear | I Key | Double-click blank / Esc / Right Mouse exits":
        "カーブ編集モード：G 移動 | R 回転 | S 拡縮 | B ボックス選択 | Shift 追加 | A 全選択 | Alt+A 解除 | I キー | 空白をダブルクリック/Esc/右クリックで終了",
    "Object Edit": "オブジェクト編集",
    "Native Edit": "ネイティブ編集",
    "Equalize": "等間隔化",
    "Equalize Curve Points": "カーブ点を等間隔化",
    "Redistribute guide points uniformly by curve arc length":
        "カーブの弧長に沿ってガイド点を均等に再配置します",
    "Remove or bake guide-point animation before equalizing points":
        "等間隔化する前にガイド点アニメーションを削除またはベイクしてください",
    "Equalized curve to {count} points":
        "カーブを {count} 点に等間隔化しました",
}

_CURVE_CAGE_KO = {
    "Control Mode": "\uc81c\uc5b4 \ubaa8\ub4dc",
    "Choose whether the complete source maps to the guide or the guide endpoints stay inside the cage":
        "전체 소스 케이지와 제어 대상 물체를 가이드에 매핑할지, 가이드 끝점을 케이지 안에 제한할지 선택",
    "Map the complete source cage and controlled object to the complete guide; editing the guide changes deformation shape without changing source boundaries, cage length, or position":
        "전체 소스 케이지와 제어 대상 물체를 전체 가이드에 매핑합니다. 가이드를 편집하면 변형 형태만 바뀌며 소스 경계, 케이지 길이 및 위치는 바뀌지 않습니다",
    "Cage Mode": "\ucf00\uc774\uc9c0 \ubaa8\ub4dc",
    "Keep the guide endpoints constrained inside the cage":
        "\uac00\uc774\ub4dc \ub05d\uc810\uc744 \ucf00\uc774\uc9c0 \ub0b4\ubd80\ub85c \uc81c\ud55c",
    "Range Mode": "\ubc94\uc704 \ubaa8\ub4dc",
    "Curve Range Start": "커브 적용 범위 시작",
    "Lower effect boundary inside the stable Curve cage mapping domain":
        "안정된 커브 케이지 매핑 영역 안의 하단 적용 경계",
    "Curve Range End": "커브 적용 범위 끝",
    "Upper effect boundary inside the stable Curve cage mapping domain":
        "안정된 커브 케이지 매핑 영역 안의 상단 적용 경계",
    "Curve Cage": "커브 케이지",
    "Curve": "커브",
    "Add Curve Cage": "커브 케이지 추가",
    "Added Curve Cage stage": "커브 케이지 단계를 추가했습니다",
    "Independent Bezier-guided cage with editable cross sections":
        "편집 가능한 단면이 있는 독립 베지어 가이드 케이지",
    "Deform geometry along an editable Bezier guide":
        "편집 가능한 베지어 가이드를 따라 지오메트리 변형",
    "Temporarily bypass Curve": "커브 변형 임시 비활성화",
    "Length Mode": "길이 모드",
    "How cage-axis distance is mapped to the guide":
        "케이지 축 거리를 가이드에 매핑하는 방식",
    "Preserve Length": "길이 유지",
    "Map physical cage distance to guide arc length":
        "실제 케이지 거리를 가이드 호 길이에 매핑",
    "Stretch to Path": "경로에 맞게 늘이기",
    "Use the complete guide and stretch the source along it":
        "전체 가이드를 사용해 소스를 경로를 따라 늘입니다",
    "Fit Guide to Cage": "가이드를 케이지에 맞춤",
    "Scale the complete guide shape to the authored cage length":
        "전체 가이드 모양을 케이지 길이에 맞게 조정",
    "Boundary Mode": "경계 모드",
    "How points beyond the Curve cage ends are handled":
        "커브 케이지 끝 바깥의 점을 처리하는 방식",
    "Extend Tangents": "접선 방향 연장",
    "Continue beyond each guide end along its endpoint tangent":
        "각 끝점의 접선을 따라 가이드 밖으로 연장",
    "Clamp": "고정",
    "Hold points beyond the mapped range at the guide endpoints":
        "매핑 범위 밖의 점을 가이드 끝점에 고정",
    "Cage Only": "케이지 내부만",
    "Leave points outside the authored cage range unchanged":
        "케이지 범위 밖의 점을 변경하지 않음",
    "Compensate cross-section scale when stretching to the guide":
        "가이드에 맞게 늘일 때 단면 스케일 보정",
    "Guide Resolution": "가이드 해상도",
    "Bezier evaluation resolution used by the Curve cage":
        "커브 케이지의 베지어 평가 해상도",
    "Edit Guide": "가이드 편집",
    "Edit Curve Cage": "커브 케이지 편집",
    "Enter the managed guide's Curve Edit Mode; use Blender selection, G/R/S, handles, subdivide, extrude, and delete tools":
        "관리 가이드의 커브 편집 모드에서 선택, G/R/S, 핸들, 세분화, 돌출 및 삭제를 사용합니다",
    "Cross Sections": "단면",
    "Cross Section {index}": "단면 {index}",
    "Active Guide Point": "활성 가이드 점",
    "Roll": "롤",
    "Radius": "반경",
    "Position": "위치",
    "Normalized position of this cross-section along the guide":
        "가이드를 따른 단면의 정규화 위치",
    "U / W Scale": "U / W 스케일",
    "Independent cross-section scale along the guide U and W axes":
        "가이드 U/W 축의 독립 단면 스케일",
    "U / W Offset": "U / W 오프셋",
    "Cross-section center offset along the guide U and W axes":
        "가이드 U/W 축의 단면 중심 오프셋",
    "Add Cross Section": "단면 추가",
    "Insert an interpolated cross-section station": "보간 단면 스테이션 삽입",
    "Remove Cross Section": "단면 제거",
    "Remove the active interior cross-section station": "활성 내부 단면 스테이션 제거",
    "Reset Curve Guide": "커브 가이드 재설정",
    "Reset the guide to a straight path fitted to the cage":
        "가이드를 케이지에 맞는 직선 경로로 재설정",
    "Curve cages do not support chained creation": "커브 케이지는 체인 생성을 지원하지 않습니다",
    "Curve cages cannot be subdivided into chains": "커브 케이지는 체인으로 세분화할 수 없습니다",
    "Key the active cage parameters, end profiles, FFD controls, Curve guide and cross sections, and cage transform on the current frame":
        "현재 프레임에 케이지 매개변수, 끝 형상, FFD, 커브 가이드, 단면 및 케이지 변환을 기록합니다",
    "Curve Mode": "커브 모드",
    "How the Curve cage affects geometry beyond its authored range":
        "작성된 범위 밖의 지오메트리에 커브 케이지가 영향을 주는 방식",
    "Hold geometry beyond the range at the guide endpoints":
        "범위 밖 지오메트리를 가이드 끝점에 고정",
    "Freeze the boundary frame and continue excluded geometry rigidly along its tangent":
        "경계 프레임을 고정하고 범위 밖 지오메트리를 접선 방향으로 강체 연장",
    "Leave geometry outside the authored cage range unchanged":
        "작성된 케이지 범위 밖 지오메트리를 변경하지 않음",
    "Extend open endpoints or repeat around a closed guide":
        "열린 끝점에서는 연장하고 닫힌 가이드에서는 반복 순환",
    "Closed Curve": "닫힌 커브",
    "Join the first and last guide points into a continuous loop":
        "첫 가이드 점과 마지막 가이드 점을 연속 루프로 연결",
    "Guide Points": "가이드 점",
    "Object-mode controls for the managed Bezier guide":
        "관리되는 베지어 가이드의 오브젝트 모드 컨트롤",
    "Guide Point {index}": "가이드 점 {index}",
    "Point Count": "점 개수",
    "Number of evenly-spaced guide points after resampling":
        "재샘플링 후 균등 간격 가이드 점 개수",
    "Active Cross Section": "활성 단면",
    "Editable U/W scale and offset stations along the Curve cage":
        "커브 케이지를 따라 편집 가능한 U/W 스케일 및 오프셋 단면",
    "Native Curve Edit Mode": "네이티브 커브 편집 모드",
    "Curve Object Edit Mode": "커브 오브젝트 편집 모드",
    "Whether persistent object-mode guide editing is active":
        "뷰포트에서 오브젝트 모드 가이드 편집을 유지할지 여부",
    "Curve Point": "커브 점",
    "Select and move this Curve cage guide point":
        "이 커브 케이지의 가이드 점 선택 및 이동",
    "Bezier Handle": "베지어 핸들",
    "Adjust this guide point's Bezier tangent handle":
        "이 가이드 점의 베지어 접선 핸들 조정",
    "Linked Handles": "연결 핸들",
    "Keep both Bezier handles mirrored until Alt makes one side independent":
        "Alt로 한쪽을 독립시키기 전까지 두 베지어 핸들을 대칭 연결",
    "Linked handles move symmetrically; Alt makes this handle independent":
        "연결 핸들은 대칭 이동하며 Alt를 누르면 현재 핸들이 독립됨",
    "Bevel": "베벨",
    "Blend this guide point from a sharp corner to a shared smooth tangent":
        "날카로운 모서리에서 공유 부드러운 접선으로 가이드 점 혼합",
    "Tension": "장력",
    "Scale the Bezier handles around this guide point":
        "이 가이드 점 주변의 베지어 핸들 크기 조절",
    "Curve Point or Bezier Handle": "커브 점 또는 베지어 핸들",
    "Curve Cage Controls": "커브 케이지 컨트롤",
    "Edit Curve Points": "커브 점 편집",
    "Edit Curve cage points and Bezier handles persistently in Object Mode":
        "오브젝트 모드에서 커브 케이지 점과 베지어 핸들을 지속적으로 편집",
    "Curve Edit Mode": "커브 편집 모드",
    "Alt Independent Handle": "Alt 핸들 개별 조정",
    "X/Y/Z Axis | Shift Precise | Ctrl Snap | Click/Enter Confirm | Esc/Right Mouse Cancel":
        "X/Y/Z 축 | Shift 정밀 | Ctrl 스냅 | 클릭/Enter 확인 | Esc/오른쪽 클릭 취소",
    "Curve Box Select: drag over points or handles | Shift Add | Ctrl Subtract | Esc cancels":
        "커브 박스 선택: 점 또는 핸들 위로 드래그 | Shift 추가 | Ctrl 제외 | Esc 취소",
    "Curve Edit Mode: G Move | R Rotate | S Scale | B Box Select | Shift Add | A Select All | Alt+A Clear | I Key | Double-click blank / Esc / Right Mouse exits":
        "커브 편집 모드: G 이동 | R 회전 | S 크기 조절 | B 박스 선택 | Shift 추가 | A 전체 선택 | Alt+A 해제 | I 키 | 빈 공간 더블 클릭/Esc/오른쪽 클릭 종료",
    "Object Edit": "오브젝트 편집",
    "Native Edit": "네이티브 편집",
    "Equalize": "균등 배치",
    "Equalize Curve Points": "커브 점 균등 배치",
    "Redistribute guide points uniformly by curve arc length":
        "커브 호 길이를 따라 가이드 점을 균등하게 재배치",
    "Remove or bake guide-point animation before equalizing points":
        "균등 배치 전에 가이드 점 애니메이션을 제거하거나 베이크하십시오",
    "Equalized curve to {count} points":
        "커브를 {count}개 점으로 균등 배치했습니다",
}

translations_dict.update(_CURVE_CAGE_ZH)
translations_ja_JP.update(_CURVE_CAGE_JA)
translations_ko_KR.update(_CURVE_CAGE_KO)

_CURVE_PROFILE_PRESET_ZH = {
    "Curve Profile": "曲线截面",
    "Rest Binding": "\u9759\u6b62\u6001\u7ed1\u5b9a",
    "Absolute Guide": "\u7edd\u5bf9\u5f15\u5bfc\u7ebf",
    "Bind Current Guide": "\u7ed1\u5b9a\u5f53\u524d\u5f15\u5bfc\u7ebf",
    "Rebind Curve": "\u91cd\u65b0\u7ed1\u5b9a\u66f2\u7ebf",
    "Capture the current guide as the zero-deformation reference for relative Curve binding":
        "\u5c06\u5f53\u524d\u5f15\u5bfc\u7ebf\u8bb0\u5f55\u4e3a\u76f8\u5bf9\u66f2\u7ebf\u7ed1\u5b9a\u7684\u96f6\u5f62\u53d8\u53c2\u8003",
    "The Curve cage rest guide could not be created":
        "\u65e0\u6cd5\u521b\u5efa\u66f2\u7ebf\u7b3c\u7684\u9759\u6b62\u6001\u5f15\u5bfc\u7ebf",
    "Rebound Curve reference guide": "\u5df2\u91cd\u65b0\u7ed1\u5b9a\u66f2\u7ebf\u53c2\u8003\u5f15\u5bfc\u7ebf",
    "Curve Global Radius": "曲线全局半径",
    "Global Radius": "全局半径",
    "Uniform radius multiplier composed with native guide-point and cross-section radius":
        "与原生引导点半径和截面半径相乘的统一半径系数",
    "Curve Global Twist": "曲线全局扭转",
    "Global Twist": "全局扭转",
    "Uniform rotation added to every cross-section around the guide":
        "为所有截面绕引导线统一增加的旋转量",
    "Guide Preset": "引导线预设",
    "Curve Preset": "曲线预设",
    "Parametric guide shape to create when Apply Preset is used":
        "使用“应用预设”时要创建的参数化引导线形状",
    "Straight": "直线",
    "Create a straight guide along the cage axis":
        "沿笼轴创建直线引导线",
    "Wave": "波浪",
    "Create a two-plane flowing wave guide":
        "创建双平面流动波浪引导线",
    "Sine": "正弦波",
    "Create a planar sine-wave guide": "创建平面正弦波引导线",
    "Helix": "螺旋",
    "Create a helical guide around the cage axis":
        "围绕笼轴创建螺旋引导线",
    "Amplitude": "振幅",
    "Radial size of the generated Curve preset":
        "生成的曲线预设的径向尺寸",
    "Cycles": "周期",
    "Number of wave cycles or helix turns along the guide":
        "沿引导线的波浪周期数或螺旋圈数",
    "Phase": "相位",
    "Starting phase of the generated Curve preset":
        "生成的曲线预设的起始相位",
    "Preset Points": "预设点数",
    "Number of editable Bezier points generated by the preset":
        "预设生成的可编辑贝塞尔点数量",
    "Point Roll": "点滚转",
    "Point Radius": "点半径",
    "Station Radius": "截面站半径",
    "Station Twist": "截面站扭转",
    "Cross-section radius multiplier interpolated along the guide":
        "沿引导线插值的截面半径系数",
    "Cross-section rotation around the guide tangent, interpolated between stations":
        "截面绕引导线切线的旋转量，并在截面站之间插值",
    "Apply Curve Preset": "应用曲线预设",
    "Replace the managed guide with the selected editable Curve preset":
        "使用所选的可编辑曲线预设替换受管理的引导线",
    "Preset": "预设",
    "Remove or bake guide-point animation before applying a preset":
        "应用预设前请移除或烘焙引导点动画",
    "Remove guide shape keys, drivers, NLA, or point animation before applying a preset":
        "应用预设前请移除引导线形态键、驱动器、NLA 或控制点动画",
    "Remove guide shape keys, drivers, NLA, or point animation before equalizing points":
        "等距重采样前请移除引导线形态键、驱动器、NLA 或控制点动画",
    "Applied {preset} Curve preset": "已应用 {preset} 曲线预设",
}

_CURVE_PROFILE_PRESET_JA = {
    "Curve Profile": "カーブ断面",
    "Rest Binding": "\u30ec\u30b9\u30c8\u30d0\u30a4\u30f3\u30c9",
    "Absolute Guide": "\u7d76\u5bfe\u30ac\u30a4\u30c9",
    "Bind Current Guide": "\u73fe\u5728\u306e\u30ac\u30a4\u30c9\u3092\u30d0\u30a4\u30f3\u30c9",
    "Rebind Curve": "\u30ab\u30fc\u30d6\u3092\u518d\u30d0\u30a4\u30f3\u30c9",
    "Capture the current guide as the zero-deformation reference for relative Curve binding":
        "\u73fe\u5728\u306e\u30ac\u30a4\u30c9\u3092\u3001\u76f8\u5bfe\u30ab\u30fc\u30d6\u30d0\u30a4\u30f3\u30c9\u306e\u30bc\u30ed\u5909\u5f62\u53c2\u7167\u3068\u3057\u3066\u8a18\u9332",
    "The Curve cage rest guide could not be created":
        "\u30ab\u30fc\u30d6\u30b1\u30fc\u30b8\u306e\u30ec\u30b9\u30c8\u30ac\u30a4\u30c9\u3092\u4f5c\u6210\u3067\u304d\u307e\u305b\u3093",
    "Rebound Curve reference guide":
        "\u30ab\u30fc\u30d6\u53c2\u7167\u30ac\u30a4\u30c9\u3092\u518d\u30d0\u30a4\u30f3\u30c9\u3057\u307e\u3057\u305f",
    "Curve Global Radius": "カーブ全体半径",
    "Global Radius": "全体半径",
    "Uniform radius multiplier composed with native guide-point and cross-section radius":
        "元のガイドポイント半径と断面半径に乗算する一様な半径倍率",
    "Curve Global Twist": "カーブ全体ツイスト",
    "Global Twist": "全体ツイスト",
    "Uniform rotation added to every cross-section around the guide":
        "すべての断面にガイド周りの一様な回転を追加",
    "Guide Preset": "ガイドプリセット",
    "Curve Preset": "カーブプリセット",
    "Parametric guide shape to create when Apply Preset is used":
        "「プリセットを適用」で作成するパラメトリックガイド形状",
    "Straight": "直線",
    "Create a straight guide along the cage axis":
        "ケージ軸に沿って直線ガイドを作成",
    "Wave": "ウェーブ",
    "Create a two-plane flowing wave guide":
        "2平面で流れるウェーブガイドを作成",
    "Sine": "正弦波",
    "Create a planar sine-wave guide": "平面の正弦波ガイドを作成",
    "Helix": "らせん",
    "Create a helical guide around the cage axis":
        "ケージ軸の周囲にらせんガイドを作成",
    "Amplitude": "振幅",
    "Radial size of the generated Curve preset":
        "生成するカーブプリセットの半径方向サイズ",
    "Cycles": "周期",
    "Number of wave cycles or helix turns along the guide":
        "ガイドに沿った波の周期数またはらせんの回転数",
    "Phase": "位相",
    "Starting phase of the generated Curve preset":
        "生成するカーブプリセットの開始位相",
    "Preset Points": "プリセットポイント数",
    "Number of editable Bezier points generated by the preset":
        "プリセットが生成する編集可能なベジェポイント数",
    "Point Roll": "ポイントロール",
    "Point Radius": "ポイント半径",
    "Station Radius": "断面ステーション半径",
    "Station Twist": "断面ステーションツイスト",
    "Cross-section radius multiplier interpolated along the guide":
        "ガイドに沿って補間される断面半径の倍率",
    "Cross-section rotation around the guide tangent, interpolated between stations":
        "ガイド接線を中心とする断面の回転をステーション間で補間",
    "Apply Curve Preset": "カーブプリセットを適用",
    "Replace the managed guide with the selected editable Curve preset":
        "管理ガイドを選択した編集可能なカーブプリセットで置き換え",
    "Preset": "プリセット",
    "Remove or bake guide-point animation before applying a preset":
        "プリセットを適用する前にガイドポイントのアニメーションを削除またはベイクしてください",
    "Remove guide shape keys, drivers, NLA, or point animation before applying a preset":
        "プリセット適用前にガイドのシェイプキー、ドライバー、NLA、ポイントアニメーションを削除してください",
    "Remove guide shape keys, drivers, NLA, or point animation before equalizing points":
        "均等化前にガイドのシェイプキー、ドライバー、NLA、ポイントアニメーションを削除してください",
    "Applied {preset} Curve preset":
        "{preset} カーブプリセットを適用しました",
}

_CURVE_PROFILE_PRESET_KO = {
    "Curve Profile": "커브 단면",
    "Rest Binding": "\ub808\uc2a4\ud2b8 \ubc14\uc778\ub529",
    "Absolute Guide": "\uc808\ub300 \uac00\uc774\ub4dc",
    "Bind Current Guide": "\ud604\uc7ac \uac00\uc774\ub4dc \ubc14\uc778\ub529",
    "Rebind Curve": "\ucee4\ube0c \uc7ac\ubc14\uc778\ub529",
    "Capture the current guide as the zero-deformation reference for relative Curve binding":
        "\ud604\uc7ac \uac00\uc774\ub4dc\ub97c \uc0c1\ub300 \ucee4\ube0c \ubc14\uc778\ub529\uc758 \uc601 \ud615\ubcc0 \ucc38\uc870\ub85c \uae30\ub85d",
    "The Curve cage rest guide could not be created":
        "\ucee4\ube0c \ucf00\uc774\uc9c0\uc758 \ub808\uc2a4\ud2b8 \uac00\uc774\ub4dc\ub97c \ub9cc\ub4e4 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4",
    "Rebound Curve reference guide":
        "\ucee4\ube0c \ucc38\uc870 \uac00\uc774\ub4dc\ub97c \uc7ac\ubc14\uc778\ub529\ud588\uc2b5\ub2c8\ub2e4",
    "Curve Global Radius": "커브 전체 반지름",
    "Global Radius": "전체 반지름",
    "Uniform radius multiplier composed with native guide-point and cross-section radius":
        "기본 가이드 포인트 반지름 및 단면 반지름에 곱하는 균일 반지름 배율",
    "Curve Global Twist": "커브 전체 비틀기",
    "Global Twist": "전체 비틀기",
    "Uniform rotation added to every cross-section around the guide":
        "모든 단면에 가이드 둘레의 균일한 회전을 추가",
    "Guide Preset": "가이드 프리셋",
    "Curve Preset": "커브 프리셋",
    "Parametric guide shape to create when Apply Preset is used":
        "'프리셋 적용'을 사용할 때 생성할 매개변수형 가이드 모양",
    "Straight": "직선",
    "Create a straight guide along the cage axis":
        "케이지 축을 따라 직선 가이드 생성",
    "Wave": "물결",
    "Create a two-plane flowing wave guide":
        "두 평면으로 흐르는 물결 가이드 생성",
    "Sine": "사인파",
    "Create a planar sine-wave guide": "평면 사인파 가이드 생성",
    "Helix": "나선",
    "Create a helical guide around the cage axis":
        "케이지 축 둘레에 나선 가이드 생성",
    "Amplitude": "진폭",
    "Radial size of the generated Curve preset":
        "생성할 커브 프리셋의 반지름 방향 크기",
    "Cycles": "주기",
    "Number of wave cycles or helix turns along the guide":
        "가이드를 따르는 물결 주기 수 또는 나선 회전 수",
    "Phase": "위상",
    "Starting phase of the generated Curve preset":
        "생성할 커브 프리셋의 시작 위상",
    "Preset Points": "프리셋 포인트 수",
    "Number of editable Bezier points generated by the preset":
        "프리셋이 생성하는 편집 가능한 베지어 포인트 수",
    "Point Roll": "포인트 롤",
    "Point Radius": "포인트 반지름",
    "Station Radius": "단면 스테이션 반지름",
    "Station Twist": "단면 스테이션 비틀기",
    "Cross-section radius multiplier interpolated along the guide":
        "가이드를 따라 보간되는 단면 반지름 배율",
    "Cross-section rotation around the guide tangent, interpolated between stations":
        "가이드 접선을 중심으로 한 단면 회전을 스테이션 사이에서 보간",
    "Apply Curve Preset": "커브 프리셋 적용",
    "Replace the managed guide with the selected editable Curve preset":
        "관리 가이드를 선택한 편집 가능한 커브 프리셋으로 교체",
    "Preset": "프리셋",
    "Remove or bake guide-point animation before applying a preset":
        "프리셋을 적용하기 전에 가이드 포인트 애니메이션을 제거하거나 베이크하세요",
    "Remove guide shape keys, drivers, NLA, or point animation before applying a preset":
        "프리셋 적용 전에 가이드 셰이프 키, 드라이버, NLA 또는 포인트 애니메이션을 제거하세요",
    "Remove guide shape keys, drivers, NLA, or point animation before equalizing points":
        "균등화 전에 가이드 셰이프 키, 드라이버, NLA 또는 포인트 애니메이션을 제거하세요",
    "Applied {preset} Curve preset":
        "{preset} 커브 프리셋을 적용했습니다",
}

translations_dict.update(_CURVE_PROFILE_PRESET_ZH)
translations_ja_JP.update(_CURVE_PROFILE_PRESET_JA)
translations_ko_KR.update(_CURVE_PROFILE_PRESET_KO)


_CURVE_LIVE_PRESET_ZH = {
    "Parametric guide shape previewed immediately on the cage":
        "\u5728\u7b3c\u4e0a\u7acb\u5373\u9884\u89c8\u7684\u53c2\u6570\u5316\u5f15\u5bfc\u7ebf\u5f62\u72b6",
    "Presets are locked while guide points are animated":
        "\u5f15\u5bfc\u70b9\u5b58\u5728\u52a8\u753b\u65f6\u9884\u8bbe\u5df2\u9501\u5b9a",
}

_CURVE_LIVE_PRESET_JA = {
    "Parametric guide shape previewed immediately on the cage":
        "\u30b1\u30fc\u30b8\u4e0a\u3067\u3059\u3050\u306b\u30d7\u30ec\u30d3\u30e5\u30fc\u3055\u308c\u308b\u30d1\u30e9\u30e1\u30c8\u30ea\u30c3\u30af\u30ac\u30a4\u30c9\u5f62\u72b6",
    "Presets are locked while guide points are animated":
        "\u30ac\u30a4\u30c9\u30dd\u30a4\u30f3\u30c8\u304c\u30a2\u30cb\u30e1\u30fc\u30b7\u30e7\u30f3\u3055\u308c\u3066\u3044\u308b\u9593\u3001\u30d7\u30ea\u30bb\u30c3\u30c8\u306f\u30ed\u30c3\u30af\u3055\u308c\u307e\u3059",
}

_CURVE_LIVE_PRESET_KO = {
    "Parametric guide shape previewed immediately on the cage":
        "\ucf00\uc774\uc9c0\uc5d0\uc11c \uc989\uc2dc \ubbf8\ub9ac \ubcf4\ub294 \ud30c\ub77c\uba54\ud2b8\ub9ad \uac00\uc774\ub4dc \ud615\ud0dc",
    "Presets are locked while guide points are animated":
        "\uac00\uc774\ub4dc \ud3ec\uc778\ud2b8\uc5d0 \uc560\ub2c8\uba54\uc774\uc158\uc774 \uc788\ub294 \ub3d9\uc548 \ud504\ub9ac\uc14b\uc774 \uc7a0\uae41\ub2c8\ub2e4",
}

translations_dict.update(_CURVE_LIVE_PRESET_ZH)
translations_ja_JP.update(_CURVE_LIVE_PRESET_JA)
translations_ko_KR.update(_CURVE_LIVE_PRESET_KO)


_TRADITIONAL_STACK_ZH = {
    "Traditional Simple Deform": "传统简易形变",
    "Viewport Display": "视图显示",
    "Lower Limit": "下限",
    "Upper Limit": "上限",
    "Origin": "原点",
    "Insert Deformation Keyframes": "插入形变关键帧",
    "Delete Deformation Keyframes": "删除形变关键帧",
    "Key the active cage or traditional Simple Deform stage on the current frame":
        "在当前帧为活动笼或传统简易形变阶段插入关键帧",
    "Delete current-frame keys for the active cage or traditional Simple Deform stage":
        "删除活动笼或传统简易形变阶段在当前帧的关键帧",
    "Inserted {count} deformation keyframe channels":
        "已插入 {count} 个形变关键帧通道",
    "Removed {count} deformation keyframe channels":
        "已删除 {count} 个形变关键帧通道",
    "Could not create the managed lower-limit Origin":
        "无法创建跟随下限的托管原点",
}

_TRADITIONAL_STACK_JA = {
    "Traditional Simple Deform": "従来型シンプル変形",
    "Viewport Display": "ビューポート表示",
    "Lower Limit": "下限",
    "Upper Limit": "上限",
    "Origin": "原点",
    "Insert Deformation Keyframes": "変形キーフレームを挿入",
    "Delete Deformation Keyframes": "変形キーフレームを削除",
    "Key the active cage or traditional Simple Deform stage on the current frame":
        "現在のフレームでアクティブなケージまたは従来型シンプル変形ステージにキーを設定",
    "Delete current-frame keys for the active cage or traditional Simple Deform stage":
        "アクティブなケージまたは従来型シンプル変形ステージの現在フレームのキーを削除",
    "Inserted {count} deformation keyframe channels":
        "{count} 個の変形キーフレームチャンネルを挿入しました",
    "Removed {count} deformation keyframe channels":
        "{count} 個の変形キーフレームチャンネルを削除しました",
    "Could not create the managed lower-limit Origin":
        "下限に追従する管理原点を作成できませんでした",
}

_TRADITIONAL_STACK_KO = {
    "Traditional Simple Deform": "기존 단순 변형",
    "Viewport Display": "뷰포트 표시",
    "Lower Limit": "하한",
    "Upper Limit": "상한",
    "Origin": "원점",
    "Insert Deformation Keyframes": "변형 키프레임 삽입",
    "Delete Deformation Keyframes": "변형 키프레임 삭제",
    "Key the active cage or traditional Simple Deform stage on the current frame":
        "현재 프레임에서 활성 케이지 또는 기존 단순 변형 단계에 키 삽입",
    "Delete current-frame keys for the active cage or traditional Simple Deform stage":
        "활성 케이지 또는 기존 단순 변형 단계의 현재 프레임 키 삭제",
    "Inserted {count} deformation keyframe channels":
        "변형 키프레임 채널 {count}개를 삽입했습니다",
    "Removed {count} deformation keyframe channels":
        "변형 키프레임 채널 {count}개를 삭제했습니다",
    "Could not create the managed lower-limit Origin":
        "하한을 따르는 관리 원점을 만들 수 없습니다",
}

translations_dict.update(_TRADITIONAL_STACK_ZH)
translations_ja_JP.update(_TRADITIONAL_STACK_JA)
translations_ko_KR.update(_TRADITIONAL_STACK_KO)


_CURVE_PROPORTIONAL_ZH = {
    "Curve Edit": "曲线编辑",
    "Select and transform Curve guide points and handles":
        "选择并变换曲线引导点和手柄",
    "Equalize Cross Sections": "均分截面",
    "Distribute every cross section evenly along the guide":
        "沿引导线均匀分布所有截面",
    "Alt+S Radius | Ctrl+T Twist | O Proportional":
        "Alt+S 半径 | Ctrl+T 扭转 | O 比例编辑",
    "Adjust selected guide-point radii with Blender proportional falloff":
        "使用 Blender 比例衰减调整所选引导点的半径",
    "Adjust selected guide-point roll with Blender proportional falloff":
        "使用 Blender 比例衰减调整所选引导点的滚转",
    "Adjust selected guide-point bevel with Blender proportional falloff":
        "使用 Blender 比例衰减调整所选引导点的倒角",
    "Adjust selected guide-point tension with Blender proportional falloff":
        "使用 Blender 比例衰减调整所选引导点的张力",
    "Adjust cross-section radii with Blender proportional falloff":
        "使用 Blender 比例衰减调整截面半径",
    "Adjust cross-section twist with Blender proportional falloff":
        "使用 Blender 比例衰减调整截面扭转",
    "Full Curve Falloff": "全域衰减",
    "Apply point roll, radius, bevel, and tension through the current proportional falloff across the complete guide":
        "使用当前比例衰减将点滚转、半径、倒角和张力作用于整条引导曲线",
    "Even Cross Sections": "自动均分截面",
    "Keep all cross sections evenly distributed when sections are added, removed, or adjusted":
        "添加、移除或调整截面时，始终保持所有截面均匀分布",
}

_CURVE_PROPORTIONAL_JA = {
    "Curve Edit": "カーブ編集",
    "Select and transform Curve guide points and handles":
        "カーブのガイドポイントとハンドルを選択して変形",
    "Equalize Cross Sections": "断面を等間隔化",
    "Distribute every cross section evenly along the guide":
        "すべての断面をガイドに沿って均等に配置",
    "Alt+S Radius | Ctrl+T Twist | O Proportional":
        "Alt+S 半径 | Ctrl+T ツイスト | O プロポーショナル編集",
    "Adjust selected guide-point radii with Blender proportional falloff":
        "Blender のプロポーショナル減衰で選択したガイドポイントの半径を調整",
    "Adjust selected guide-point roll with Blender proportional falloff":
        "Blender のプロポーショナル減衰で選択したガイドポイントのロールを調整",
    "Adjust selected guide-point bevel with Blender proportional falloff":
        "Blender のプロポーショナル減衰で選択したガイドポイントのベベルを調整",
    "Adjust selected guide-point tension with Blender proportional falloff":
        "Blender のプロポーショナル減衰で選択したガイドポイントのテンションを調整",
    "Adjust cross-section radii with Blender proportional falloff":
        "Blender のプロポーショナル減衰で断面半径を調整",
    "Adjust cross-section twist with Blender proportional falloff":
        "Blender のプロポーショナル減衰で断面ツイストを調整",
    "Full Curve Falloff": "カーブ全域減衰",
    "Apply point roll, radius, bevel, and tension through the current proportional falloff across the complete guide":
        "現在のプロポーショナル減衰でポイントのロール、半径、ベベル、テンションをガイド全体に適用",
    "Even Cross Sections": "断面を自動等間隔化",
    "Keep all cross sections evenly distributed when sections are added, removed, or adjusted":
        "断面の追加、削除、調整時にすべての断面を常に均等配置",
}

_CURVE_PROPORTIONAL_KO = {
    "Curve Edit": "커브 편집",
    "Select and transform Curve guide points and handles":
        "커브 가이드 포인트와 핸들을 선택하고 변형",
    "Equalize Cross Sections": "단면 균등 배치",
    "Distribute every cross section evenly along the guide":
        "모든 단면을 가이드를 따라 균등하게 배치",
    "Alt+S Radius | Ctrl+T Twist | O Proportional":
        "Alt+S 반지름 | Ctrl+T 비틀기 | O 비례 편집",
    "Adjust selected guide-point radii with Blender proportional falloff":
        "Blender 비례 감쇠로 선택한 가이드 포인트 반지름 조정",
    "Adjust selected guide-point roll with Blender proportional falloff":
        "Blender 비례 감쇠로 선택한 가이드 포인트 롤 조정",
    "Adjust selected guide-point bevel with Blender proportional falloff":
        "Blender 비례 감쇠로 선택한 가이드 포인트 베벨 조정",
    "Adjust selected guide-point tension with Blender proportional falloff":
        "Blender 비례 감쇠로 선택한 가이드 포인트 장력 조정",
    "Adjust cross-section radii with Blender proportional falloff":
        "Blender 비례 감쇠로 단면 반지름 조정",
    "Adjust cross-section twist with Blender proportional falloff":
        "Blender 비례 감쇠로 단면 비틀기 조정",
    "Full Curve Falloff": "전체 커브 감쇠",
    "Apply point roll, radius, bevel, and tension through the current proportional falloff across the complete guide":
        "현재 비례 감쇠로 포인트 롤, 반지름, 베벨, 장력을 전체 가이드에 적용",
    "Even Cross Sections": "단면 자동 균등 배치",
    "Keep all cross sections evenly distributed when sections are added, removed, or adjusted":
        "단면을 추가, 제거 또는 조정할 때 모든 단면을 항상 균등하게 배치",
}

translations_dict.update(_CURVE_PROPORTIONAL_ZH)
translations_ja_JP.update(_CURVE_PROPORTIONAL_JA)
translations_ko_KR.update(_CURVE_PROPORTIONAL_KO)


_CURVE_UI_SECTIONS_ZH = {
    "Show Curve control, binding, range, and profile settings":
        "显示曲线控制、绑定、范围和截面设置",
    "Show parametric Curve guide preset controls":
        "显示参数化曲线引导预设控制",
    "Show guide editing and active-point controls":
        "显示引导编辑和活动点控制",
    "Show editable Curve cross-section stations":
        "显示可编辑的曲线截面站点",
}

_CURVE_UI_SECTIONS_JA = {
    "Show Curve control, binding, range, and profile settings":
        "カーブ制御、バインド、範囲、断面設定を表示",
    "Show parametric Curve guide preset controls":
        "パラメトリックカーブガイドのプリセット制御を表示",
    "Show guide editing and active-point controls":
        "ガイド編集とアクティブポイント制御を表示",
    "Show editable Curve cross-section stations":
        "編集可能なカーブ断面ステーションを表示",
}

_CURVE_UI_SECTIONS_KO = {
    "Show Curve control, binding, range, and profile settings":
        "커브 제어, 바인딩, 범위 및 단면 설정 표시",
    "Show parametric Curve guide preset controls":
        "파라메트릭 커브 가이드 프리셋 제어 표시",
    "Show guide editing and active-point controls":
        "가이드 편집 및 활성 포인트 제어 표시",
    "Show editable Curve cross-section stations":
        "편집 가능한 커브 단면 스테이션 표시",
}

translations_dict.update(_CURVE_UI_SECTIONS_ZH)
translations_ja_JP.update(_CURVE_UI_SECTIONS_JA)
translations_ko_KR.update(_CURVE_UI_SECTIONS_KO)


_CHAIN_REORDER_UI_ZH = {
    "Chained cage segments keep their internal order":
        "链式笼分段保持内部顺序",
}

_CHAIN_REORDER_UI_JA = {
    "Chained cage segments keep their internal order":
        "チェーンケージのセグメントは内部順序を維持します",
}

_CHAIN_REORDER_UI_KO = {
    "Chained cage segments keep their internal order":
        "체인 케이지 세그먼트는 내부 순서를 유지합니다",
}

translations_dict.update(_CHAIN_REORDER_UI_ZH)
translations_ja_JP.update(_CHAIN_REORDER_UI_JA)
translations_ko_KR.update(_CHAIN_REORDER_UI_KO)


translations_en_US = {source: source for source in translations_dict}


class TranslationHelper:
    def __init__(self, name: str, data: dict, lang="zh_CN"):
        self.name = name
        self.translations_dict = dict()
        self._registered = False

        catalogs = (
            data if all(isinstance(value, dict) for value in data.values())
            else {lang: data}
        )
        for locale, catalog in catalogs.items():
            for src, src_trans in catalog.items():
                key = ("Operator", src)
                self.translations_dict.setdefault(locale, {})[key] = src_trans
                key = ("*", src)
                self.translations_dict.setdefault(locale, {})[key] = src_trans

    def register(self):
        if self._registered:
            return
        try:
            bpy.app.translations.register(self.name, self.translations_dict)
        except ValueError as e:
            _LOGGER.debug("Register Translation failed: %s", e)
        else:
            self._registered = True

    def unregister(self):
        if not self._registered:
            return
        try:
            bpy.app.translations.unregister(self.name)
        except ValueError as error:
            _LOGGER.debug("Unregister Translation failed: %s", error)
        finally:
            self._registered = False


all_language = get_language_list()


def get_language(language):
    if language not in all_language:
        if bpy.app.version < (4, 0, 0):
            return "zh_CN"
        else:
            return "zh_HANS"
    return language


_PROFESSIONAL_MULTI_CAGE_EN = {
    "Show advanced Deform Axis, Independent Ends, and Numeric Controls":
        "Show advanced Deform Axis, Independent Ends, and Numeric Controls",
    "With multiple objects, click creates one merged cage; Ctrl-click creates a separate cage for each object":
        "With multiple objects, click creates one merged cage; Ctrl-click creates a separate cage for each object",
    "No selected objects support separate cage stages":
        "No selected objects support separate cage stages",
    "Added {count} separate cage stages":
        "Added {count} separate cage stages",
    "Added {count} separate cage stages; skipped {skipped} selected objects":
        "Added {count} separate cage stages; skipped {skipped} selected objects",
}
_PROFESSIONAL_MULTI_CAGE_ZH = {
    "Show advanced Deform Axis, Independent Ends, and Numeric Controls":
        "显示高级形变轴、独立端部和数值控制",
    "With multiple objects, click creates one merged cage; Ctrl-click creates a separate cage for each object":
        "选择多个物体时，单击创建一个合并笼；Ctrl+单击为每个物体分别创建笼",
    "No selected objects support separate cage stages":
        "所选物体均不支持独立笼阶段",
    "Added {count} separate cage stages":
        "已添加 {count} 个独立笼阶段",
    "Added {count} separate cage stages; skipped {skipped} selected objects":
        "已添加 {count} 个独立笼阶段；跳过 {skipped} 个所选物体",
}
_PROFESSIONAL_MULTI_CAGE_JA = {
    "Show advanced Deform Axis, Independent Ends, and Numeric Controls":
        "高度な変形軸、独立した端部、数値コントロールを表示",
    "With multiple objects, click creates one merged cage; Ctrl-click creates a separate cage for each object":
        "複数選択時はクリックで結合ケージを作成し、Ctrl+クリックで各オブジェクトに個別のケージを作成",
    "No selected objects support separate cage stages":
        "選択したオブジェクトは個別のケージステージをサポートしていません",
    "Added {count} separate cage stages":
        "{count} 個の個別ケージステージを追加しました",
    "Added {count} separate cage stages; skipped {skipped} selected objects":
        "{count} 個の個別ケージステージを追加し、{skipped} 個の選択物をスキップしました",
}
_PROFESSIONAL_MULTI_CAGE_KO = {
    "Show advanced Deform Axis, Independent Ends, and Numeric Controls":
        "고급 변형 축, 독립 끝 및 수치 컨트롤 표시",
    "With multiple objects, click creates one merged cage; Ctrl-click creates a separate cage for each object":
        "여러 오브젝트 선택 시 클릭하면 병합 케이지를 만들고 Ctrl+클릭하면 각각 별도 케이지를 만듭니다",
    "No selected objects support separate cage stages":
        "선택한 오브젝트는 개별 케이지 스테이지를 지원하지 않습니다",
    "Added {count} separate cage stages":
        "개별 케이지 스테이지 {count}개를 추가했습니다",
    "Added {count} separate cage stages; skipped {skipped} selected objects":
        "개별 케이지 스테이지 {count}개를 추가하고 선택한 오브젝트 {skipped}개를 건너뛰었습니다",
}

_FFD_NATIVE_WEIGHT_EN = {
    "Weight": "Weight",
    "Influence": "Influence",
    "Native Lattice Edit": "Native Lattice Edit",
    "Native FFD Edit Mode": "Native FFD Edit Mode",
    "How strongly this control point contributes to the FFD field":
        "How strongly this control point contributes to the FFD field",
    "Set the active and selected FFD point influences together":
        "Set the active and selected FFD point influences together",
    "Whether the companion Blender Lattice is being edited":
        "Whether the companion Blender Lattice is being edited",
    "Edit this FFD through Blender's native Lattice Edit Mode":
        "Edit this FFD through Blender's native Lattice Edit Mode",
    "Native Lattice Edit is unavailable for Unlimited FFD":
        "Native Lattice Edit is unavailable for Unlimited FFD",
}
_FFD_NATIVE_WEIGHT_ZH = {
    "Weight": "\u6743\u91cd",
    "Influence": "\u5f71\u54cd\u529b",
    "Native Lattice Edit": "\u539f\u751f\u6676\u683c\u7f16\u8f91",
    "Native FFD Edit Mode": "\u539f\u751f FFD \u7f16\u8f91\u6a21\u5f0f",
    "How strongly this control point contributes to the FFD field":
        "\u6b64\u63a7\u5236\u70b9\u5bf9 FFD \u5f62\u53d8\u573a\u7684\u5f71\u54cd\u5f3a\u5ea6",
    "Set the active and selected FFD point influences together":
        "\u540c\u65f6\u8bbe\u7f6e\u6d3b\u52a8\u70b9\u548c\u6240\u9009 FFD \u70b9\u7684\u6743\u91cd",
    "Whether the companion Blender Lattice is being edited":
        "\u662f\u5426\u6b63\u5728\u7f16\u8f91\u914d\u5957\u7684 Blender \u6676\u683c",
    "Edit this FFD through Blender's native Lattice Edit Mode":
        "\u4f7f\u7528 Blender \u539f\u751f\u6676\u683c\u7f16\u8f91\u6a21\u5f0f\u7f16\u8f91\u6b64 FFD",
    "Native Lattice Edit is unavailable for Unlimited FFD":
        "\u65e0\u9650 FFD \u4e0d\u652f\u6301\u539f\u751f\u6676\u683c\u7f16\u8f91",
}
_FFD_NATIVE_WEIGHT_JA = {
    "Weight": "\u30a6\u30a7\u30a4\u30c8",
    "Influence": "\u5f71\u97ff\u5ea6",
    "Native Lattice Edit": "\u30cd\u30a4\u30c6\u30a3\u30d6\u30e9\u30c6\u30a3\u30b9\u7de8\u96c6",
    "Native FFD Edit Mode": "\u30cd\u30a4\u30c6\u30a3\u30d6 FFD \u7de8\u96c6\u30e2\u30fc\u30c9",
    "How strongly this control point contributes to the FFD field":
        "\u3053\u306e\u5236\u5fa1\u70b9\u304c FFD \u30d5\u30a3\u30fc\u30eb\u30c9\u306b\u4e0e\u3048\u308b\u5f71\u97ff\u5ea6",
    "Set the active and selected FFD point influences together":
        "\u30a2\u30af\u30c6\u30a3\u30d6\u3068\u9078\u629e\u4e2d\u306e FFD \u70b9\u306e\u30a6\u30a7\u30a4\u30c8\u3092\u540c\u6642\u306b\u8a2d\u5b9a",
    "Whether the companion Blender Lattice is being edited":
        "\u30b3\u30f3\u30d1\u30cb\u30aa\u30f3 Blender \u30e9\u30c6\u30a3\u30b9\u304c\u7de8\u96c6\u4e2d\u304b",
    "Edit this FFD through Blender's native Lattice Edit Mode":
        "Blender \u306e\u30cd\u30a4\u30c6\u30a3\u30d6\u30e9\u30c6\u30a3\u30b9\u7de8\u96c6\u3067\u3053\u306e FFD \u3092\u7de8\u96c6",
    "Native Lattice Edit is unavailable for Unlimited FFD":
        "Unlimited FFD \u3067\u306f\u30cd\u30a4\u30c6\u30a3\u30d6\u30e9\u30c6\u30a3\u30b9\u7de8\u96c6\u3092\u4f7f\u7528\u3067\u304d\u307e\u305b\u3093",
}
_FFD_NATIVE_WEIGHT_KO = {
    "Weight": "\uac00\uc911\uce58",
    "Influence": "\uc601\ud5a5\ub3c4",
    "Native Lattice Edit": "\ub124\uc774\ud2f0\ube0c \ub798\ud2f0\uc2a4 \ud3b8\uc9d1",
    "Native FFD Edit Mode": "\ub124\uc774\ud2f0\ube0c FFD \ud3b8\uc9d1 \ubaa8\ub4dc",
    "How strongly this control point contributes to the FFD field":
        "\uc774 \uc81c\uc5b4\uc810\uc774 FFD \ud544\ub4dc\uc5d0 \uae30\uc5ec\ud558\ub294 \uc601\ud5a5\ub3c4",
    "Set the active and selected FFD point influences together":
        "\ud65c\uc131 \ubc0f \uc120\ud0dd\ub41c FFD \ud3ec\uc778\ud2b8\uc758 \uac00\uc911\uce58\ub97c \ud568\uaed8 \uc124\uc815",
    "Whether the companion Blender Lattice is being edited":
        "\ub3d9\ubc18 Blender \ub798\ud2f0\uc2a4\ub97c \ud3b8\uc9d1 \uc911\uc778\uc9c0 \uc5ec\ubd80",
    "Edit this FFD through Blender's native Lattice Edit Mode":
        "Blender \ub124\uc774\ud2f0\ube0c \ub798\ud2f0\uc2a4 \ud3b8\uc9d1 \ubaa8\ub4dc\ub85c \uc774 FFD\ub97c \ud3b8\uc9d1",
    "Native Lattice Edit is unavailable for Unlimited FFD":
        "Unlimited FFD\uc5d0\uc11c\ub294 \ub124\uc774\ud2f0\ube0c \ub798\ud2f0\uc2a4 \ud3b8\uc9d1\uc744 \uc0ac\uc6a9\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4",
}

translations_en_US.update(_PROFESSIONAL_MULTI_CAGE_EN)
translations_dict.update(_PROFESSIONAL_MULTI_CAGE_ZH)
translations_ja_JP.update(_PROFESSIONAL_MULTI_CAGE_JA)
translations_ko_KR.update(_PROFESSIONAL_MULTI_CAGE_KO)
translations_en_US.update(_FFD_NATIVE_WEIGHT_EN)
translations_dict.update(_FFD_NATIVE_WEIGHT_ZH)
translations_ja_JP.update(_FFD_NATIVE_WEIGHT_JA)
translations_ko_KR.update(_FFD_NATIVE_WEIGHT_KO)


# 2.7.50: apply/collapse, mirrored stages, stack presets, bake outputs,
# layer keyframes, influence weights, and arc-length station resampling.
_STACK_TOOLS_ZH = {
    "Apply Stage": "应用此阶段",
    "Apply All Stages": "应用全部阶段",
    "Apply this deformation stage to the mesh and remove its cage controls":
        "将此形变阶段应用到网格，并移除其笼控制",
    "Apply every managed cage and traditional Simple Deform stage to the mesh, in stack order, and remove their controls":
        "按堆栈顺序将所有受管笼与传统简易形变阶段应用到网格，并移除其控制",
    "Applied deformation stage": "已应用形变阶段",
    "Applied {count} deformation stages": "已应用 {count} 个形变阶段",
    "Applied {count} stages before stopping": "中止前已应用 {count} 个阶段",
    "Apply requires a mesh target": "应用需要网格类型的目标物体",
    "Could not apply modifier {name}": "无法应用修改器 {name}",
    "Partially applied stage; {name} could not be applied":
        "阶段仅部分应用；{name} 未能应用",
    "Mirror": "镜像",
    "Mirror Cage Stage": "镜像笼阶段",
    "Mirror Axis": "镜像轴",
    "Target-local axis to mirror across": "以目标局部轴为镜像平面法向",
    "Duplicate this cage stage mirrored across a target-local axis":
        "沿目标局部轴镜像复制此笼阶段",
    "Mirrored cage stage across {axis}": "已沿 {axis} 轴镜像笼阶段",
    "Guide point animation is not mirrored; remove it and mirror again for an exact result":
        "引导线点动画未被镜像；移除动画后重新镜像可获得精确结果",
    "Save Preset": "保存预设",
    "Load Preset": "加载预设",
    "Save Stack Preset": "保存堆栈预设",
    "Load Stack Preset": "加载堆栈预设",
    "Delete Stack Preset": "删除堆栈预设",
    "Save every managed cage stage on this object as a reusable preset":
        "将该物体上所有受管笼阶段保存为可复用预设",
    "Append a saved cage stack preset to the active object":
        "将已保存的笼堆栈预设追加到活动物体",
    "Delete one saved cage stack preset": "删除一个已保存的笼堆栈预设",
    "Preset Name": "预设名称",
    "Saved cage stack preset": "已保存的笼堆栈预设",
    "No presets saved": "没有已保存的预设",
    "No managed cage stages found": "未找到受管笼阶段",
    "Not a cage stack preset file": "不是笼堆栈预设文件",
    "The preset contains no cage stages": "该预设不包含任何笼阶段",
    "Preset chains could not be reconnected": "预设中的链无法重新连接",
    "Saved {count} stages to preset {name}":
        "已将 {count} 个阶段保存到预设 {name}",
    "Added {count} stages from preset {name}":
        "已从预设 {name} 添加 {count} 个阶段",
    "Deleted preset {name}": "已删除预设 {name}",
    "Key Active Layer": "键帧当前层",
    "Delete Layer Keys": "删除当前层键帧",
    "Active Layer Only": "仅当前层",
    "Key only the active deformation layer's parameters":
        "只为当前形变层的参数插入关键帧",
    "Delete keys only for the active deformation layer's parameters":
        "只删除当前形变层参数的关键帧",
    "Output": "输出方式",
    "New Object": "新建物体",
    "Replace Source": "替换源物体",
    "Alembic File": "Alembic 文件",
    "Alembic Path": "Alembic 路径",
    "Bake absolute shape keys onto a new independent mesh object":
        "烘焙为新独立网格物体上的绝对形态键",
    "Bake to a new mesh, remove the managed deformation stack and the source object, and take over the source name":
        "烘焙到新网格，移除受管形变堆栈与源物体，并接管源物体名称",
    "Export the evaluated animation to an Alembic (.abc) cache without creating shape keys":
        "将求值后的动画导出为 Alembic (.abc) 缓存，不创建形态键",
    "Bake the evaluated cage animation to shape keys, replace the source in place, or export an Alembic file":
        "将求值后的笼动画烘焙为形态键、原地替换源物体或导出 Alembic 文件",
    "Scene frames between baked samples; values below 1.0 add subframe samples":
        "烘焙采样之间的场景帧数；小于 1.0 时增加子帧采样",
    "Sample Step must be at least 0.01": "采样步长不能小于 0.01",
    "Exported Alembic cache to {path}": "已导出 Alembic 缓存到 {path}",
    "Choose an Alembic output path first": "请先选择 Alembic 输出路径",
    "Alembic export did not finish": "Alembic 导出未完成",
    "Replace Source is unavailable for multi-object merges; bake to a new object instead":
        "多物体合并不支持替换源物体；请烘焙到新物体",
    "Baked, but the source could not be replaced: {error}":
        "已烘焙，但源物体无法替换：{error}",
    "Even Stations by Arc Length": "按弧长均匀分布站点",
    "Redistribute the existing cross-section stations evenly along the guide's arc length":
        "将现有横截面站点沿引导线弧长均匀重新分布",
    "Stations redistributed by arc length": "站点已按弧长重新分布",
    "Influence Weight": "影响权重",
    "Influence Vertex Group": "影响顶点组",
    "Blend between the original and deformed positions for this stage; combine with a vertex group for painted falloff":
        "在原始与形变位置之间混合此阶段的结果；配合顶点组可实现绘制衰减",
    "Limit this stage to a vertex group; weights scale the Influence Weight per point":
        "将此阶段限制在顶点组内；权重逐点缩放影响权重",
    "Shortcut Cheat Sheet": "快捷键速查",
    "Animated stages cannot be mirrored yet; bake or remove their animation first":
        "暂不支持镜像带动画的阶段；请先烘焙或移除动画",
    "Replace Source requires a mesh target; bake to a new object instead":
        "替换源物体需要网格目标；请改为烘焙到新物体",
    "The baked result has no mesh data": "烘焙结果不包含网格数据",
    "Source replacement failed: {error}": "替换源物体失败：{error}",
    "Unsupported cage stack preset version": "不支持的笼堆栈预设版本",
    "Preset stage {index} is invalid": "预设阶段 {index} 无效",
    "Preset stage {index} has no properties": "预设阶段 {index} 缺少属性",
    "Preset stage {index} contains unknown properties: {names}":
        "预设阶段 {index} 包含未知属性：{names}",
    "Preset stage {index} has an unsupported cage type":
        "预设阶段 {index} 使用了不支持的笼类型",
    "Preset stage {index} exceeds the FFD 6 x 6 x 6 limit":
        "预设阶段 {index} 超出 FFD 6 x 6 x 6 上限",
    "Preset stage {index} has an invalid FFD point count":
        "预设阶段 {index} 的 FFD 点数量无效",
    "Link U/V/W": "联动 U/V/W",
    "Adjust FFD point counts and interpolation together; disable to edit U, V, and W independently":
        "同时调整 FFD 的点数与插值；关闭后可分别编辑 U、V、W",
    "FFD Points": "FFD 点数",
    "Number of control points on all linked FFD axes":
        "所有联动 FFD 轴的控制点数量",
    "Interpolation": "插值",
    "Interpolation basis on all linked FFD axes":
        "所有联动 FFD 轴使用的插值基函数",
}
_STACK_TOOLS_JA = {
    "Apply Stage": "ステージを適用",
    "Apply All Stages": "全ステージを適用",
    "Applied deformation stage": "変形ステージを適用しました",
    "Applied {count} deformation stages": "{count} 個の変形ステージを適用しました",
    "Apply requires a mesh target": "適用にはメッシュターゲットが必要です",
    "Mirror": "ミラー",
    "Mirror Cage Stage": "ケージステージをミラー",
    "Mirror Axis": "ミラー軸",
    "Mirrored cage stage across {axis}": "{axis} 軸でケージステージをミラーしました",
    "Save Preset": "プリセットを保存",
    "Load Preset": "プリセットを読み込み",
    "Save Stack Preset": "スタックプリセットを保存",
    "Load Stack Preset": "スタックプリセットを読み込み",
    "Delete Stack Preset": "スタックプリセットを削除",
    "Preset Name": "プリセット名",
    "No presets saved": "保存されたプリセットはありません",
    "Saved {count} stages to preset {name}": "{count} 個のステージをプリセット {name} に保存しました",
    "Added {count} stages from preset {name}": "プリセット {name} から {count} 個のステージを追加しました",
    "Deleted preset {name}": "プリセット {name} を削除しました",
    "Key Active Layer": "アクティブレイヤーをキー",
    "Delete Layer Keys": "レイヤーキーを削除",
    "Output": "出力",
    "New Object": "新規オブジェクト",
    "Replace Source": "ソースを置き換え",
    "Alembic File": "Alembic ファイル",
    "Alembic Path": "Alembic パス",
    "Exported Alembic cache to {path}": "Alembic キャッシュを {path} に書き出しました",
    "Even Stations by Arc Length": "弧長で断面を均等配置",
    "Stations redistributed by arc length": "断面を弧長で再配置しました",
    "Influence Weight": "影響ウェイト",
    "Influence Vertex Group": "影響頂点グループ",
    "Shortcut Cheat Sheet": "ショートカット早見表",
    "Animated stages cannot be mirrored yet; bake or remove their animation first":
        "アニメーション付きステージはまだミラーできません。先にベイクまたはアニメーションを削除してください",
    "Applied {count} stages before stopping": "停止前に {count} ステージを適用しました",
    "Choose an Alembic output path first": "先に Alembic 出力パスを選択してください",
    "Alembic export did not finish": "Alembic の書き出しが完了しませんでした",
    "Could not apply modifier {name}": "モディファイアー {name} を適用できませんでした",
    "Guide point animation is not mirrored; remove it and mirror again for an exact result":
        "ガイドポイントのアニメーションはミラーされません。削除して再度ミラーしてください",
    "No managed cage stages found": "管理対象のケージステージが見つかりません",
    "Not a cage stack preset file": "ケージスタックプリセットではありません",
    "Partially applied stage; {name} could not be applied":
        "ステージの一部のみ適用され、{name} は適用できませんでした",
    "Replace Source is unavailable for multi-object merges; bake to a new object instead":
        "複数オブジェクトの結合ではソース置換を使用できません。新規オブジェクトへベイクしてください",
    "Replace Source requires a mesh target; bake to a new object instead":
        "ソース置換にはメッシュターゲットが必要です。新規オブジェクトへベイクしてください",
    "Sample Step must be at least 0.01": "サンプル間隔は 0.01 以上にしてください",
    "Saved cage stack preset": "保存済みケージスタックプリセット",
    "Source replacement failed: {error}": "ソースの置換に失敗しました: {error}",
    "The baked result has no mesh data": "ベイク結果にメッシュデータがありません",
    "The preset contains no cage stages": "プリセットにケージステージがありません",
    "Unsupported cage stack preset version": "未対応のケージスタックプリセットバージョンです",
    "Preset stage {index} is invalid": "プリセットステージ {index} が無効です",
    "Preset stage {index} has no properties": "プリセットステージ {index} にプロパティがありません",
    "Preset stage {index} contains unknown properties: {names}":
        "プリセットステージ {index} に未知のプロパティがあります: {names}",
    "Preset stage {index} has an unsupported cage type":
        "プリセットステージ {index} のケージタイプは未対応です",
    "Preset stage {index} exceeds the FFD 6 x 6 x 6 limit":
        "プリセットステージ {index} が FFD 6 x 6 x 6 の上限を超えています",
    "Preset stage {index} has an invalid FFD point count":
        "プリセットステージ {index} の FFD ポイント数が無効です",
    "Link U/V/W": "U/V/W を連動",
    "Adjust FFD point counts and interpolation together; disable to edit U, V, and W independently":
        "FFD のポイント数と補間をまとめて調整します。無効にすると U、V、W を個別に編集できます",
    "FFD Points": "FFD ポイント数",
    "Number of control points on all linked FFD axes":
        "連動するすべての FFD 軸の制御ポイント数",
    "Interpolation": "補間",
    "Interpolation basis on all linked FFD axes":
        "連動するすべての FFD 軸で使用する補間方式",
}
_STACK_TOOLS_KO = {
    "Apply Stage": "스테이지 적용",
    "Apply All Stages": "모든 스테이지 적용",
    "Applied deformation stage": "변형 스테이지를 적용했습니다",
    "Applied {count} deformation stages": "{count}개의 변형 스테이지를 적용했습니다",
    "Apply requires a mesh target": "적용하려면 메시 대상이 필요합니다",
    "Mirror": "미러",
    "Mirror Cage Stage": "케이지 스테이지 미러",
    "Mirror Axis": "미러 축",
    "Mirrored cage stage across {axis}": "{axis} 축으로 케이지 스테이지를 미러했습니다",
    "Save Preset": "프리셋 저장",
    "Load Preset": "프리셋 불러오기",
    "Save Stack Preset": "스택 프리셋 저장",
    "Load Stack Preset": "스택 프리셋 불러오기",
    "Delete Stack Preset": "스택 프리셋 삭제",
    "Preset Name": "프리셋 이름",
    "No presets saved": "저장된 프리셋이 없습니다",
    "Saved {count} stages to preset {name}": "{count}개의 스테이지를 프리셋 {name}에 저장했습니다",
    "Added {count} stages from preset {name}": "프리셋 {name}에서 {count}개의 스테이지를 추가했습니다",
    "Deleted preset {name}": "프리셋 {name}을(를) 삭제했습니다",
    "Key Active Layer": "활성 레이어 키",
    "Delete Layer Keys": "레이어 키 삭제",
    "Output": "출력",
    "New Object": "새 오브젝트",
    "Replace Source": "소스 교체",
    "Alembic File": "Alembic 파일",
    "Alembic Path": "Alembic 경로",
    "Exported Alembic cache to {path}": "Alembic 캐시를 {path}에 내보냈습니다",
    "Even Stations by Arc Length": "호 길이로 단면 균등 배치",
    "Stations redistributed by arc length": "호 길이에 따라 단면을 재배치했습니다",
    "Influence Weight": "영향 가중치",
    "Influence Vertex Group": "영향 버텍스 그룹",
    "Shortcut Cheat Sheet": "단축키 참고표",
    "Animated stages cannot be mirrored yet; bake or remove their animation first":
        "애니메이션이 있는 스테이지는 아직 미러할 수 없습니다. 먼저 베이크하거나 애니메이션을 제거하세요",
    "Applied {count} stages before stopping": "중지 전 {count}개 스테이지를 적용했습니다",
    "Choose an Alembic output path first": "먼저 Alembic 출력 경로를 선택하세요",
    "Alembic export did not finish": "Alembic 내보내기가 완료되지 않았습니다",
    "Could not apply modifier {name}": "모디파이어 {name}을 적용할 수 없습니다",
    "Guide point animation is not mirrored; remove it and mirror again for an exact result":
        "가이드 포인트 애니메이션은 미러되지 않습니다. 제거한 뒤 다시 미러하세요",
    "No managed cage stages found": "관리되는 케이지 스테이지를 찾지 못했습니다",
    "Not a cage stack preset file": "케이지 스택 프리셋 파일이 아닙니다",
    "Partially applied stage; {name} could not be applied":
        "스테이지가 일부만 적용되었으며 {name}은 적용하지 못했습니다",
    "Replace Source is unavailable for multi-object merges; bake to a new object instead":
        "다중 오브젝트 병합에서는 소스 교체를 사용할 수 없습니다. 새 오브젝트로 베이크하세요",
    "Replace Source requires a mesh target; bake to a new object instead":
        "소스 교체에는 메시 대상이 필요합니다. 새 오브젝트로 베이크하세요",
    "Sample Step must be at least 0.01": "샘플 간격은 0.01 이상이어야 합니다",
    "Saved cage stack preset": "저장된 케이지 스택 프리셋",
    "Source replacement failed: {error}": "소스 교체 실패: {error}",
    "The baked result has no mesh data": "베이크 결과에 메시 데이터가 없습니다",
    "The preset contains no cage stages": "프리셋에 케이지 스테이지가 없습니다",
    "Unsupported cage stack preset version": "지원하지 않는 케이지 스택 프리셋 버전입니다",
    "Preset stage {index} is invalid": "프리셋 스테이지 {index}이(가) 올바르지 않습니다",
    "Preset stage {index} has no properties": "프리셋 스테이지 {index}에 속성이 없습니다",
    "Preset stage {index} contains unknown properties: {names}":
        "프리셋 스테이지 {index}에 알 수 없는 속성이 있습니다: {names}",
    "Preset stage {index} has an unsupported cage type":
        "프리셋 스테이지 {index}의 케이지 유형은 지원되지 않습니다",
    "Preset stage {index} exceeds the FFD 6 x 6 x 6 limit":
        "프리셋 스테이지 {index}이(가) FFD 6 x 6 x 6 제한을 초과합니다",
    "Preset stage {index} has an invalid FFD point count":
        "프리셋 스테이지 {index}의 FFD 포인트 수가 올바르지 않습니다",
    "Link U/V/W": "U/V/W 연동",
    "Adjust FFD point counts and interpolation together; disable to edit U, V, and W independently":
        "FFD 포인트 수와 보간을 함께 조정합니다. 끄면 U, V, W를 개별 편집할 수 있습니다",
    "FFD Points": "FFD 포인트 수",
    "Number of control points on all linked FFD axes":
        "연동된 모든 FFD 축의 제어 포인트 수",
    "Interpolation": "보간",
    "Interpolation basis on all linked FFD axes":
        "연동된 모든 FFD 축에 사용할 보간 방식",
}
translations_dict.update(_STACK_TOOLS_ZH)
translations_ja_JP.update(_STACK_TOOLS_JA)
translations_ko_KR.update(_STACK_TOOLS_KO)
translations_en_US.update({source: source for source in _STACK_TOOLS_ZH})

_STANDARD_INITIAL_DEFORM_ZH = {
    "Other Deformation": "其他形变",
    "Initial Deformation": "初始形变",
    "Create the Standard cage with a Bend layer":
        "创建以弯曲层初始化的标准型笼",
    "Create the Standard cage with a Twist layer":
        "创建以扭曲层初始化的标准型笼",
    "Create the Standard cage with a Taper layer":
        "创建以锥化层初始化的标准型笼",
    "Create the Standard cage with a Stretch layer":
        "创建以拉伸层初始化的标准型笼",
    "Create the Standard cage with a Shear layer":
        "创建以斜切层初始化的标准型笼",
    "Create every Standard chain stage with a Bend layer":
        "使用弯曲层初始化每个标准型链式阶段",
    "Create every Standard chain stage with a Twist layer":
        "使用扭曲层初始化每个标准型链式阶段",
    "Create every Standard chain stage with a Taper layer":
        "使用锥化层初始化每个标准型链式阶段",
    "Create every Standard chain stage with a Stretch layer":
        "使用拉伸层初始化每个标准型链式阶段",
    "Create every Standard chain stage with a Shear layer":
        "使用斜切层初始化每个标准型链式阶段",
}
_STANDARD_INITIAL_DEFORM_JA = {
    "Other Deformation": "その他の変形",
    "Initial Deformation": "初期変形",
    "Create the Standard cage with a Bend layer":
        "ベンドレイヤーで標準型ケージを作成",
    "Create the Standard cage with a Twist layer":
        "ツイストレイヤーで標準型ケージを作成",
    "Create the Standard cage with a Taper layer":
        "テーパーレイヤーで標準型ケージを作成",
    "Create the Standard cage with a Stretch layer":
        "ストレッチレイヤーで標準型ケージを作成",
    "Create the Standard cage with a Shear layer":
        "シアーレイヤーで標準型ケージを作成",
    "Create every Standard chain stage with a Bend layer":
        "各標準型チェーンステージをベンドレイヤーで初期化",
    "Create every Standard chain stage with a Twist layer":
        "各標準型チェーンステージをツイストレイヤーで初期化",
    "Create every Standard chain stage with a Taper layer":
        "各標準型チェーンステージをテーパーレイヤーで初期化",
    "Create every Standard chain stage with a Stretch layer":
        "各標準型チェーンステージをストレッチレイヤーで初期化",
    "Create every Standard chain stage with a Shear layer":
        "各標準型チェーンステージをシアーレイヤーで初期化",
}
_STANDARD_INITIAL_DEFORM_KO = {
    "Other Deformation": "다른 변형",
    "Initial Deformation": "초기 변형",
    "Create the Standard cage with a Bend layer":
        "벤드 레이어로 표준형 케이지 생성",
    "Create the Standard cage with a Twist layer":
        "트위스트 레이어로 표준형 케이지 생성",
    "Create the Standard cage with a Taper layer":
        "테이퍼 레이어로 표준형 케이지 생성",
    "Create the Standard cage with a Stretch layer":
        "스트레치 레이어로 표준형 케이지 생성",
    "Create the Standard cage with a Shear layer":
        "전단 레이어로 표준형 케이지 생성",
    "Create every Standard chain stage with a Bend layer":
        "각 표준형 체인 단계를 벤드 레이어로 초기화",
    "Create every Standard chain stage with a Twist layer":
        "각 표준형 체인 단계를 트위스트 레이어로 초기화",
    "Create every Standard chain stage with a Taper layer":
        "각 표준형 체인 단계를 테이퍼 레이어로 초기화",
    "Create every Standard chain stage with a Stretch layer":
        "각 표준형 체인 단계를 스트레치 레이어로 초기화",
    "Create every Standard chain stage with a Shear layer":
        "각 표준형 체인 단계를 전단 레이어로 초기화",
}
translations_dict.update(_STANDARD_INITIAL_DEFORM_ZH)
translations_ja_JP.update(_STANDARD_INITIAL_DEFORM_JA)
translations_ko_KR.update(_STANDARD_INITIAL_DEFORM_KO)
translations_en_US.update({
    source: source for source in _STANDARD_INITIAL_DEFORM_ZH
})


_CREATE_CAGE_UI_ZH = {
    "Create Cage": "创建笼",
    "Standard": "标准型",
    "Standard Chain": "标准型链式",
    "Shear": "斜切型",
    "Shear Chain": "斜切型链式",
    "FFD": "FFD型",
    "FFD Chain": "FFD型链式",
    "Curve": "曲线型",
    "Simple Deform (Legacy)": "简易形变（传统）",
}
_CREATE_CAGE_UI_JA = {
    "Create Cage": "ケージを作成",
    "Standard": "標準型",
    "Standard Chain": "標準型チェーン",
    "Shear": "シアー型",
    "Shear Chain": "シアー型チェーン",
    "FFD": "FFD型",
    "FFD Chain": "FFD型チェーン",
    "Curve": "カーブ型",
    "Simple Deform (Legacy)": "Simple Deform（従来）",
}
_CREATE_CAGE_UI_KO = {
    "Create Cage": "케이지 만들기",
    "Standard": "표준형",
    "Standard Chain": "표준형 체인",
    "Shear": "전단형",
    "Shear Chain": "전단형 체인",
    "FFD": "FFD형",
    "FFD Chain": "FFD형 체인",
    "Curve": "커브형",
    "Simple Deform (Legacy)": "Simple Deform(레거시)",
}
translations_dict.update(_CREATE_CAGE_UI_ZH)
translations_ja_JP.update(_CREATE_CAGE_UI_JA)
translations_ko_KR.update(_CREATE_CAGE_UI_KO)
translations_en_US.update({source: source for source in _CREATE_CAGE_UI_ZH})


SimpleDeform_CN = TranslationHelper(
    "SimpleDeform_CN",
    {
        "zh_HANS": translations_dict,
        "ja_JP": translations_ja_JP,
        "ko_KR": translations_ko_KR,
        "en_US": translations_en_US,
    },
)

# Blender owns common labels such as "Top" in several translation contexts.
# A dedicated cage-origin context prevents its built-in default-context entry
# from masking the add-on's Korean enum translation at runtime.
_CAGE_ORIGIN_TRANSLATION_CONTEXT = "SDH_Cage_Origin"
_CAGE_ORIGIN_CONTEXT_SOURCES = (
    "Origin",
    "Starting pattern of the deformation",
    "Deformation reference used by every cage in the chain",
    "Bottom",
    "Bottom (Recommended)",
    "Start at the lower cage boundary",
    "Reference the lower end of each cage",
    "Center",
    "Use signed distance from the cage center",
    "Reference the center of each cage",
    "Symmetric",
    "Mirror the deformation profile across the center",
    "Mirror the profile around each cage center",
    "Top",
    "Start at the upper cage boundary",
    "Reference the upper end of each cage",
)
for _locale, _catalog in (
        ("zh_HANS", translations_dict),
        ("ja_JP", translations_ja_JP),
        ("ko_KR", translations_ko_KR),
        ("en_US", translations_en_US)):
    _registered_catalog = SimpleDeform_CN.translations_dict[_locale]
    for _source in _CAGE_ORIGIN_CONTEXT_SOURCES:
        if _source in _catalog:
            _registered_catalog[
                (_CAGE_ORIGIN_TRANSLATION_CONTEXT, _source)] = _catalog[_source]


def register():
    SimpleDeform_CN.register()


def unregister():
    SimpleDeform_CN.unregister()
