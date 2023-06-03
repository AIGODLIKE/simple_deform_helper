# SPDX-License-Identifier: GPL-2.0-or-later

import bpy


def origin_text(a, b):
    return "Add an empty object origin as the rotation axis (if there is an origin, " + a + \
        "), and set the origin position " + b + " during operation"


translations_dict = {
    "zh_CN": {
        ("上下文", "原文"): "翻译文字",
        ("*", "Show Toggle Bend Axis Gizmo"): "显示切换弯曲轴向Gizmo",
        ("*", "Gizmo Property Show Location"): "Gizmo属性显示位置",
        ("*", "You can press the following shortcut keys when dragging values"):
            "拖动值时可以按以下快捷键",
        ("*", "    Wheel:   Switch Origin Ctrl Mode"):
            "    滚轮:   切换原点控制模式",
        ("*", "    X,Y,Z:  Switch Modifier Deform Axis"):
            "    X,Y,Z:  切换修改器型变轴",
        ("*", "    W:       Switch Deform Wireframe Show"):
            "    W:       切换形变线框显示",
        ("*",
         "    A:       Switch To Select Bend Axis Mode(deform_method=='BEND')"):
            "    A:       切换到选择弯曲轴模式(形变方法='弯曲')",
        ("*", "Show Set Axis Button"): "显示设置轴向Gizmo",
        ("*", "Follow Upper Limit(Red)"): "跟随上限(红色)",
        ("*", "Follow Lower Limit(Green)"): "跟随下限(绿色)",
        ("*", "Lower limit(Green)"): "下限(绿色)",
        ("*", "UP Limits(Red)"): "上限(红色)",
        ("*", "Down limit"): "下限",
        ("*", "Up limit"): "上限",
        ("*", "Show Deform Wireframe"): "显示形变线框",
        ("*", "Minimum value between upper and lower limits"): "上限与下限之间的最小值",
        ("*", "Upper and lower limit tolerance"): "上下限容差",
        ("*", "Draw Upper and lower limit Bound Box Color"): "绘制网格上限下限边界线框的颜色",
        ("*", "Upper and lower limit Bound Box Color"): "上限下限边界框颜色",
        ("*", "Draw Bound Box Color"): "绘制网格边界框的颜色",
        ("*", "Bound Box"): "边界框颜色",
        ("*", "Draw Deform Wireframe Color"): "绘制网格形变形状线框的颜色",
        ("*", "Deform Wireframe"): "形变线框颜色",
        ("*", "Simple Deform visualization adjustment tool"): "简易形变可视化工具",
        ("*", "Select an object and the active modifier is Simple Deform"): "选择物体并且活动修改器为简易形变",
        ("*", "Bound Middle"): "边界框中心",
        ("*", origin_text("do not add it", "as the lower limit")):
            "添加一个空物体原点作为旋转轴(如果已有原点则不添加),并在操作时设置原点位置为下限位置",
        ("*", origin_text("do not add it", "as the upper limit")):
            "添加一个空物体原点作为旋转轴(如果已有原点则不添加),并在操作时设置原点位置为上限位置",
        ("*", origin_text("it will not be added", "between the upper and lower limits")):
            "添加一个空物体原点作为旋转轴(如果已有原点则不添加),并在操作时设置原点位置为上下限之间的位置",
        ("*", origin_text("do not add it", "as the position between the bounding boxes")):
            "添加一个空物体原点作为旋转轴(如果已有原点则不添加),并在操作时设置原点位置为边界框之间的位置",
        ("*", "No origin operation"): "不进行原点操作",
        ("*", "Origin control mode"): "原点控制模式",
        ("*", "Down limit"): "下限",
        ("*", "Coefficient"): "系数",
        ("*", "Upper limit"): "上限",
        ("*", "3D View -> Select an object and the active modifier is simple deformation"): "3D视图 -> 选择一个物体,"
                                                                                            "并且活动修改器为简易形修改器",
        ("*", "3D View: Simple Deform Helper"): "3D 视图: Simple Deform Helper 简易形变助手",
        ("*", "Simple Deform Helper"): "简易形变助手",
        ("*", ""): "",
    }
}


def register():
    bpy.app.translations.register(__name__, translations_dict)


def unregister():
    bpy.app.translations.unregister(__name__)