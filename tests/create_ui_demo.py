"""Create a small multi-stage scene for interactive viewport QA."""

import math
import sys
from pathlib import Path

import bpy


output = Path(sys.argv[sys.argv.index("--") + 1]).resolve()

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)

vertices = []
faces = []
for index in range(25):
    z = -3.0 + index * 0.25
    vertices.extend(((-0.65, 0.0, z), (0.65, 0.0, z)))
    if index:
        base = index * 2
        faces.append((base - 2, base, base + 1, base - 1))

mesh = bpy.data.meshes.new("Multi Deform Demo")
mesh.from_pydata(vertices, (), faces)
obj = bpy.data.objects.new("Multi Deform Demo", mesh)
bpy.context.collection.objects.link(obj)
obj.select_set(True)
bpy.context.view_layer.objects.active = obj

bend = obj.modifiers.new("01 Bend", "SIMPLE_DEFORM")
bend.deform_method = "BEND"
bend.deform_axis = "Z"
bend.angle = math.radians(70.0)
solidify = obj.modifiers.new("Between Solidify", "SOLIDIFY")
solidify.thickness = 0.18
twist = obj.modifiers.new("02 Twist", "SIMPLE_DEFORM")
twist.deform_method = "TWIST"
twist.deform_axis = "Z"
twist.angle = math.radians(110.0)
obj.modifiers.active = twist

for addon in bpy.context.preferences.addons:
    if addon.module.endswith(".simple_deform_helper"):
        addon.preferences.show_other_stage_bounds = True
        addon.preferences.update_deform_wireframe = True
        addon.preferences.wireframe_preview_fps = 30
        break

bpy.context.view_layer.update()
bpy.ops.wm.save_as_mainfile(filepath=str(output))
print(f"SDH::UI_DEMO::{output}")
