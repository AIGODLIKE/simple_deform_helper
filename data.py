# SPDX-License-Identifier: GPL-2.0-or-later
from os.path import dirname, basename, realpath

G_MODIFIERS_PROPERTY = [  # copy modifier data
    'angle',
    'deform_axis',
    'deform_method',
    'factor',
    'invert_vertex_group',
    'limits',
    'lock_x',
    'lock_y',
    'lock_z',
    'origin',
    'show_expanded',
    'show_in_editmode',
    'vertex_group',
]

G_INDICES = (
    (0, 1), (0, 2), (1, 3), (2, 3),
    (4, 5), (4, 6), (5, 7), (6, 7),
    (0, 4), (1, 5), (2, 6), (3, 7))

G_NAME = 'ViewSimpleDeformGizmo_'  # Temporary use files
G_CON_LIMIT_NAME = G_NAME + 'constraints_limit_rotation'  # 约束名称
G_ADDON_NAME = basename(dirname(realpath(__file__)))  # "simple_deform_helper"


class Data:
    G_GizmoCustomShapeDict = {}
    G_SimpleDeformGizmoHandlerDit = {}

    @classmethod
    def load_gizmo_data(cls) -> None:
        import json
        import os
        json_path = os.path.join(os.path.dirname(__file__), "gizmo.json")
        with open(json_path, "r") as file:
            cls.G_GizmoCustomShapeDict = json.load(file)

    @staticmethod
    def from_bmesh_get_triangle_face_co(mesh: 'bpy.types.Mesh') -> list:
        """
        :param mesh: 输入一个网格数据
        :type mesh: bpy.data.meshes
        :return list: 反回顶点列表[[co1,co2,co3],[co1,co2,co3]...]
        """
        import bmesh

        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
        bm.verts.ensure_lookup_table()
        bmesh.ops.triangulate(bm, faces=bm.faces)
        co_list = [list(float(format(j, ".4f")) for j in vert.co) for face in bm.faces for vert in face.verts]
        bm.free()
        return co_list
