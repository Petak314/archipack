# -*- coding:utf-8 -*-

# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110- 1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

# <pep8 compliant>

# ----------------------------------------------------------
# Author: Stephen Leger (s-leger)
#
# ----------------------------------------------------------
# noinspection PyUnresolvedReferences
import bpy
# noinspection PyUnresolvedReferences
from bpy.types import Operator, PropertyGroup, Mesh, Panel, Menu
from bpy.props import (
    FloatProperty, BoolProperty, IntProperty, CollectionProperty,
    StringProperty, EnumProperty, FloatVectorProperty
    )
from .bmesh_utils import BmeshEdit as bmed
from .materialutils import MaterialUtils
from .panel import Panel as Lofter
from mathutils import Vector, Matrix
from mathutils.geometry import interpolate_bezier
from math import sin, cos, pi, acos, atan2
from .archipack_manipulator import Manipulable, archipack_manipulator
from .archipack_2d import Line, Arc
from .archipack_preset import ArchipackPreset


class Fence():

    def __init__(self):
        # total distance from start
        self.dist = 0
        self.t_start = 0
        self.t_end = 0
        self.dz = 0
        self.z0 = 0
        self.a0 = 0

    def set_offset(self, offset):
        self.line = self.offset(offset)

    @property
    def t_diff(self):
        return self.t_end - self.t_start

    def straight_fence(self, a0, length):
        s = self.straight(length).rotate(a0)
        return StraightFence(s.p, s.v)

    def curved_fence(self, a0, da, radius):
        n = self.normal(1)
        n.v = radius * n.v.normalized()
        if da < 0:
            n.v = -n.v
        a0 = n.angle
        c = n.p - n.v
        return CurvedFence(c, radius, a0, da)


class StraightFence(Fence, Line):
    def __str__(self):
        return "t_start:{} t_end:{} dist:{}".format(self.t_start, self.t_end, self.dist)

    def __init__(self, p, v):
        Fence.__init__(self)
        Line.__init__(self, p, v)


class CurvedFence(Fence, Arc):
    def __str__(self):
        return "t_start:{} t_end:{} dist:{}".format(self.t_start, self.t_end, self.dist)

    def __init__(self, c, radius, a0, da):
        Fence.__init__(self)
        Arc.__init__(self, c, radius, a0, da)


class FenceSegment():
    def __str__(self):
        return "t_start:{} t_end:{} n_step:{}  t_step:{} i_start:{} i_end:{}".format(
            self.t_start, self.t_end, self.n_step, self.t_step, self.i_start, self.i_end)

    def __init__(self, t_start, t_end, n_step, t_step, i_start, i_end):
        self.t_start = t_start
        self.t_end = t_end
        self.n_step = n_step
        self.t_step = t_step
        self.i_start = i_start
        self.i_end = i_end


class FenceGenerator():

    def __init__(self, parts):
        self.parts = parts
        self.segs = []
        self.length = 0
        self.user_defined_post = None
        self.user_defined_uvs = None
        self.user_defined_mat = None

    def add_part(self, type, radius, a0, da, length):

        if len(self.segs) < 1:
            s = None
        else:
            s = self.segs[-1]

        # start a new fence
        if s is None:
            if type == 'S_FENCE':
                p = Vector((0, 0))
                v = length * Vector((cos(a0), sin(a0)))
                s = StraightFence(p, v)
            elif type == 'C_FENCE':
                if da < 0:
                    c = Vector((radius, 0))
                else:
                    c = Vector((-radius, 0))
                s = CurvedFence(c, radius, 0, da)
        else:
            if type == 'S_FENCE':
                s = s.straight_fence(a0, length)
            elif type == 'C_FENCE':
                s = s.curved_fence(a0, da, radius)

        s.dist = self.length
        self.length += s.length
        self.segs.append(s)
        self.last_type = type

    def set_offset(self, offset):
        # @TODO:
        # re-evaluate length of offset line here
        for seg in self.segs:
            seg.set_offset(offset)

    def param_t(self, angle_limit, post_spacing):
        """
            setup corners and fences dz
            compute index of fences wich belong to each group of fences between corners
            compute t of each fence
        """
        self.segments = []
        i_start = 0
        f0 = self.segs[0]
        z = 0
        for i, f in enumerate(self.segs):
            if f.dist > 0:
                f.t_start = f.dist / self.length
            else:
                f.t_start = 0
            f.t_end = (f.dist + f.length) / self.length
            dz = self.parts[i].dz
            f.z0 = z
            f.dz = dz
            z += dz
            if i > 0 and abs(self.parts[i].a0) >= angle_limit:
                l_seg = f.dist - f0.dist
                t_seg = f.t_start - f0.t_start
                n_fences = max(1, int(l_seg / post_spacing))
                t_fence = t_seg / n_fences
                segment = FenceSegment(f0.t_start, f.t_start, n_fences, t_fence, i_start, i - 1)
                i_start = i
                f0 = self.segs[i_start]
                self.segments.append(segment)

            manipulators = self.parts[i].manipulators
            p0 = f.lerp(0).to_3d()
            p1 = f.lerp(1).to_3d()
            # angle from last to current segment
            if i > 0:
                v0 = self.segs[i - 1].straight(-1, 1).v.to_3d()
                v1 = f.straight(1, 0).v.to_3d()
                manipulators[0].set_pts([p0, v0, v1])

            if type(f).__name__ == "StraightFence":
                # segment length
                manipulators[1].type = 'SIZE'
                manipulators[1].prop1_name = "length"
                manipulators[1].set_pts([p0, p1, (1, 0, 0)])
            else:
                # segment radius + angle
                v0 = (f.lerp(0) - f.c).to_3d()
                v1 = (f.lerp(1) - f.c).to_3d()
                manipulators[1].type = 'ARC_ANGLE_RADIUS'
                manipulators[1].prop1_name = "da"
                manipulators[1].prop2_name = "radius"
                manipulators[1].set_pts([f.c.to_3d(), v0, v1])

            # snap manipulator, dont change index !
            manipulators[2].set_pts([p0, p1, (1, 0, 0)])

        f = self.segs[-1]
        l_seg = f.dist + f.length - f0.dist
        t_seg = f.t_end - f0.t_start
        n_fences = max(1, int(l_seg / post_spacing))
        t_fence = t_seg / n_fences
        segment = FenceSegment(f0.t_start, f.t_end, n_fences, t_fence, i_start, len(self.segs) - 1)
        self.segments.append(segment)

    def setup_user_defined_post(self, o, post_x, post_y, post_z):
        self.user_defined_post = o
        x = o.bound_box[6][0] - o.bound_box[0][0]
        y = o.bound_box[6][1] - o.bound_box[0][1]
        z = o.bound_box[6][2] - o.bound_box[0][2]
        self.user_defined_post_scale = Vector((post_x / x, post_y / y, post_z / z))
        m = o.data
        # create vertex group lookup dictionary for names
        vgroup_names = {vgroup.index: vgroup.name for vgroup in o.vertex_groups}
        # create dictionary of vertex group assignments per vertex
        self.vertex_groups = [[vgroup_names[g.group] for g in v.groups] for v in m.vertices]
        # uvs
        uv_act = m.uv_layers.active
        if uv_act is not None:
            uv_layer = uv_act.data
            self.user_defined_uvs = [[uv_layer[li].uv for li in p.loop_indices] for p in m.polygons]
        else:
            self.user_defined_uvs = [[(0, 0) for i in p.vertices] for p in m.polygons]
        # material ids
        self.user_defined_mat = [p.material_index for p in m.polygons]

    def get_user_defined_post(self, tM, z0, z1, z2, slope, post_z, verts, faces, matids, uvs):
        f = len(verts)
        m = self.user_defined_post.data
        for i, g in enumerate(self.vertex_groups):
            co = m.vertices[i].co.copy()
            co.x *= self.user_defined_post_scale.x
            co.y *= self.user_defined_post_scale.y
            co.z *= self.user_defined_post_scale.z
            if 'Slope' in g:
                co.z += co.y * slope
            verts.append(tM * co)
        matids += self.user_defined_mat
        faces += [tuple([i + f for i in p.vertices]) for p in m.polygons]
        uvs += self.user_defined_uvs

    def get_post(self, post, post_x, post_y, post_z, post_alt, sub_offset_x,
            id_mat, verts, faces, matids, uvs):

        n, dz, zl = post
        slope = dz * post_y

        if self.user_defined_post is not None:
            x, y = -n.v.normalized()
            tM = Matrix([
                [x, y, 0, n.p.x],
                [-y, x, 0, n.p.y],
                [0, 0, 1, zl + post_alt],
                [0, 0, 0, 1]
            ])
            self.get_user_defined_post(tM, zl, 0, 0, dz, post_z, verts, faces, matids, uvs)
            return

        z3 = zl + post_z + post_alt - slope
        z4 = zl + post_z + post_alt + slope
        z0 = zl + post_alt - slope
        z1 = zl + post_alt + slope
        vn = n.v.normalized()
        dx = post_x * vn
        dy = post_y * Vector((vn.y, -vn.x))
        oy = sub_offset_x * vn
        x0, y0 = n.p - dx + dy + oy
        x1, y1 = n.p - dx - dy + oy
        x2, y2 = n.p + dx - dy + oy
        x3, y3 = n.p + dx + dy + oy
        f = len(verts)
        verts.extend([(x0, y0, z0), (x0, y0, z3),
                    (x1, y1, z1), (x1, y1, z4),
                    (x2, y2, z1), (x2, y2, z4),
                    (x3, y3, z0), (x3, y3, z3)])
        faces.extend([(f, f + 1, f + 3, f + 2),
                    (f + 2, f + 3, f + 5, f + 4),
                    (f + 4, f + 5, f + 7, f + 6),
                    (f + 6, f + 7, f + 1, f),
                    (f, f + 2, f + 4, f + 6),
                    (f + 7, f + 5, f + 3, f + 1)])
        matids.extend([id_mat, id_mat, id_mat, id_mat, id_mat, id_mat])
        x = [(0, 0), (0, post_z), (post_x, post_z), (post_x, 0)]
        y = [(0, 0), (0, post_z), (post_y, post_z), (post_y, 0)]
        z = [(0, 0), (post_x, 0), (post_x, post_y), (0, post_y)]
        uvs.extend([x, y, x, y, z, z])

    def get_panel(self, subs, altitude, panel_x, panel_z, sub_offset_x, idmat, verts, faces, matids, uvs):
        n_subs = len(subs)
        if n_subs < 1:
            return
        f = len(verts)
        x0 = sub_offset_x - 0.5 * panel_x
        x1 = sub_offset_x + 0.5 * panel_x
        z0 = 0
        z1 = panel_z
        profile = [Vector((x0, z0)), Vector((x1, z0)), Vector((x1, z1)), Vector((x0, z1))]
        user_path_uv_v = []
        n_sections = n_subs - 1
        n, dz, zl = subs[0]
        p0 = n.p
        v0 = n.v.normalized()
        for s, section in enumerate(subs):
            n, dz, zl = section
            p1 = n.p
            if s < n_sections:
                v1 = subs[s + 1][0].v.normalized()
            dir = (v0 + v1).normalized()
            scale = 1 / cos(0.5 * acos(min(1, max(-1, v0 * v1))))
            for p in profile:
                x, y = n.p + scale * p.x * dir
                z = zl + p.y + altitude
                verts.append((x, y, z))
            if s > 0:
                user_path_uv_v.append((p1 - p0).length)
            p0 = p1
            v0 = v1

        # build faces using Panel
        lofter = Lofter(
            # closed_shape, index, x, y, idmat
            True,
            [i for i in range(len(profile))],
            [p.x for p in profile],
            [p.y for p in profile],
            [idmat for i in range(len(profile))],
            closed_path=False,
            user_path_uv_v=user_path_uv_v,
            user_path_verts=n_subs
            )
        faces += lofter.faces(16, offset=f, path_type='USER_DEFINED')
        matids += lofter.mat(16, idmat, idmat, path_type='USER_DEFINED')
        v = Vector((0, 0))
        uvs += lofter.uv(16, v, v, v, v, 0, v, 0, 0, path_type='USER_DEFINED')

    def make_subs(self, x, y, z, post_y, altitude,
            sub_spacing, sub_offset_x, mat, verts, faces, matids, uvs):

        self.set_offset(sub_offset_x)

        t_post = (0.5 * post_y - y) / self.length
        t_spacing = sub_spacing / self.length

        for segment in self.segments:
            t_step = segment.t_step
            t_start = segment.t_start + t_post
            s = 0
            s_sub = t_step - 2 * t_post
            n_sub = int(s_sub / t_spacing)
            if n_sub > 0:
                t_sub = s_sub / n_sub
            else:
                t_sub = 1 / self.line.length
            i = segment.i_start
            while s < segment.n_step:
                t_cur = t_start + s * t_step
                for j in range(1, n_sub):
                    t_s = t_cur + t_sub * j
                    while self.segs[i].t_end < t_s:
                        i += 1
                    f = self.segs[i]
                    t = (t_s - f.t_start) / f.t_diff
                    n = f.line.normal(t)
                    post = (n, f.dz / f.length, f.z0 + f.dz * t)
                    self.get_post(post, x, y, z, altitude, 0, mat, verts, faces, matids, uvs)
                s += 1

    def make_post(self, x, y, z, altitude, x_offset, mat, verts, faces, matids, uvs):

        self.set_offset(x_offset)

        for segment in self.segments:
            t_step = segment.t_step
            t_start = segment.t_start
            s = 0
            i = segment.i_start
            while s < segment.n_step:
                t_cur = t_start + s * t_step
                while self.segs[i].t_end < t_cur:
                    i += 1
                f = self.segs[i]
                t = (t_cur - f.t_start) / f.t_diff
                n = f.line.normal(t)
                post = (n, f.dz / f.length, f.z0 + f.dz * t)
                self.get_post(post, x, y, z, altitude, 0, mat, verts, faces, matids, uvs)
                s += 1
            if segment.i_end + 1 == len(self.segs):
                f = self.segs[segment.i_end]
                n = f.line.normal(1)
                post = (n, f.dz / f.length, f.z0 + f.dz)
                self.get_post(post, x, y, z, altitude, 0, mat, verts, faces, matids, uvs)

    def make_panels(self, x, z, post_y, altitude, panel_dist,
            sub_offset_x, idmat, verts, faces, matids, uvs):

        self.set_offset(sub_offset_x)

        t_post = (0.5 * post_y + panel_dist) / self.length
        for segment in self.segments:
            t_step = segment.t_step
            t_start = segment.t_start
            s = 0
            i = segment.i_start
            while s < segment.n_step:
                subs = []
                t_cur = t_start + s * t_step + t_post
                t_end = t_start + (s + 1) * t_step - t_post
                # find first section
                while self.segs[i].t_end < t_cur:
                    i += 1
                f = self.segs[i]
                t = (t_cur - f.t_start) / f.t_diff
                n = f.line.normal(t)
                subs.append((n, f.dz / f.length, f.z0 + f.dz * t))
                # crossing sections
                while i < segment.i_end:
                    f = self.segs[i]
                    if f.t_end < t_end:
                        n = f.line.normal(1)
                        subs.append((n, f.dz / f.length, f.z0 + f.dz))
                    if f.t_start + f.t_diff >= t_end:
                        break
                    elif f.t_start < t_end:
                        i += 1

                f = self.segs[i]
                # last section
                t = (t_end - f.t_start) / f.t_diff
                n = f.line.normal(t)
                subs.append((n, f.dz / f.length, f.z0 + f.dz * t))
                self.get_panel(subs, altitude, x, z, 0, idmat, verts, faces, matids, uvs)
                s += 1

    def make_profile(self, profile, idmat,
            x_offset, z_offset, extend, verts, faces, matids, uvs):

        self.set_offset(x_offset)

        n_fences = len(self.segs) - 1

        if n_fences < 0:
            return

        sections = []

        f = self.segs[0]

        # first step
        if extend != 0:
            t = -extend / self.segs[0].line.length
            n = f.line.normal(t)
            sections.append((n, f.dz / f.length, f.z0 + f.dz * t))

        # add first section
        n = f.line.normal(0)
        sections.append((n, f.dz / f.length, f.z0))

        for s, f in enumerate(self.segs):
            n = f.line.normal(1)
            sections.append((n, f.dz / f.length, f.z0 + f.dz))

        if extend != 0:
            t = 1 + extend / self.segs[-1].line.length
            n = f.line.normal(t)
            sections.append((n, f.dz / f.length, f.z0 + f.dz * t))

        user_path_verts = len(sections)
        f = len(verts)
        if user_path_verts > 0:
            user_path_uv_v = []
            n, dz, z0 = sections[-1]
            sections[-1] = (n, dz, z0)
            n_sections = user_path_verts - 1
            n, dz, zl = sections[0]
            p0 = n.p
            v0 = n.v.normalized()
            for s, section in enumerate(sections):
                n, dz, zl = section
                p1 = n.p
                if s < n_sections:
                    v1 = sections[s + 1][0].v.normalized()
                dir = (v0 + v1).normalized()
                scale = 1 / cos(0.5 * acos(min(1, max(-1, v0 * v1))))
                for p in profile:
                    x, y = n.p + scale * p.x * dir
                    z = zl + p.y + z_offset
                    verts.append((x, y, z))
                if s > 0:
                    user_path_uv_v.append((p1 - p0).length)
                p0 = p1
                v0 = v1

            # build faces using Panel
            lofter = Lofter(
                # closed_shape, index, x, y, idmat
                True,
                [i for i in range(len(profile))],
                [p.x for p in profile],
                [p.y for p in profile],
                [idmat for i in range(len(profile))],
                closed_path=False,
                user_path_uv_v=user_path_uv_v,
                user_path_verts=user_path_verts
                )
            faces += lofter.faces(16, offset=f, path_type='USER_DEFINED')
            matids += lofter.mat(16, idmat, idmat, path_type='USER_DEFINED')
            v = Vector((0, 0))
            uvs += lofter.uv(16, v, v, v, v, 0, v, 0, 0, path_type='USER_DEFINED')


def update(self, context):
    self.update(context)


def update_manipulators(self, context):
    self.update(context, manipulable_refresh=True)


def update_path(self, context):
    self.update_path(context)


materials_enum = (
            ('0', 'Ceiling', '', 0),
            ('1', 'White', '', 1),
            ('2', 'Concrete', '', 2),
            ('3', 'Wood', '', 3),
            ('4', 'Metal', '', 4),
            ('5', 'Glass', '', 5)
            )


class archipack_fence_material(PropertyGroup):
    index = EnumProperty(
        items=materials_enum,
        default='4',
        update=update
        )

    def find_in_selection(self, context):
        """
            find witch selected object this instance belongs to
            provide support for "copy to selected"
        """
        selected = [o for o in context.selected_objects]
        for o in selected:
            props = ARCHIPACK_PT_fence.params(o)
            if props:
                for part in props.rail_mat:
                    if part == self:
                        return props
        return None

    def update(self, context):
        props = self.find_in_selection(context)
        if props is not None:
            props.update(context)


class archipack_fence_part(PropertyGroup):
    type = EnumProperty(
            items=(
                ('S_FENCE', 'Straight fence', '', 0),
                ('C_FENCE', 'Curved fence', '', 1),
                ),
            default='S_FENCE',
            update=update_manipulators
            )
    length = FloatProperty(
            name="length",
            min=0.01,
            max=1000.0,
            default=2.0,
            update=update
            )
    radius = FloatProperty(
            name="radius",
            min=0.5,
            max=100.0,
            default=0.7,
            update=update
            )
    da = FloatProperty(
            name="angle",
            min=-pi,
            max=pi,
            default=pi / 2,
            subtype='ANGLE', unit='ROTATION',
            update=update
            )
    a0 = FloatProperty(
            name="angle",
            min=-2 * pi,
            max=2 * pi,
            default=0,
            subtype='ANGLE', unit='ROTATION',
            update=update
            )
    dz = FloatProperty(
            name="delta z",
            default=0
            )

    manipulators = CollectionProperty(type=archipack_manipulator)

    def find_in_selection(self, context):
        """
            find witch selected object this instance belongs to
            provide support for "copy to selected"
        """
        selected = [o for o in context.selected_objects]
        for o in selected:
            props = ARCHIPACK_PT_fence.params(o)
            if props:
                for part in props.parts:
                    if part == self:
                        return props
        return None

    def update(self, context, manipulable_refresh=False):
        props = self.find_in_selection(context)
        if props is not None:
            props.update(context, manipulable_refresh)

    def draw(self, layout, context, index):
        box = layout.box()
        row = box.row()
        row.prop(self, "type", text="")
        if self.type in ['C_FENCE']:
            row = box.row()
            row.prop(self, "radius")
            row = box.row()
            row.prop(self, "da")
        else:
            row = box.row()
            row.prop(self, "length")
        row.prop(self, "a0")


class archipack_fence(Manipulable, PropertyGroup):

    parts = CollectionProperty(type=archipack_fence_part)
    user_defined_path = StringProperty(
            name="user defined",
            update=update_path
            )
    user_defined_resolution = IntProperty(
            name="resolution",
            min=1,
            max=128,
            default=12, update=update_path
            )
    n_parts = IntProperty(
            name="parts",
            min=1,
            max=512,
            default=1, update=update_manipulators
            )
    x_offset = FloatProperty(
            name="x offset",
            min=-1000, max=1000,
            default=0.0, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )

    radius = FloatProperty(
            name="radius",
            min=0.5,
            max=100.0,
            default=0.7,
            update=update
            )
    da = FloatProperty(
            name="angle",
            min=-pi,
            max=pi,
            default=pi / 2,
            subtype='ANGLE', unit='ROTATION',
            update=update
            )
    angle_limit = FloatProperty(
            name="angle",
            min=0,
            max=2 * pi,
            default=pi / 2,
            subtype='ANGLE', unit='ROTATION',
            update=update_manipulators
            )
    shape = EnumProperty(
            items=(
                ('RECTANGLE', 'Straight', '', 0),
                ('CIRCLE', 'Curved ', '', 1)
                ),
            default='RECTANGLE',
            update=update
            )
    post = BoolProperty(
            name='enable',
            default=True,
            update=update
            )
    post_spacing = FloatProperty(
            name="spacing",
            min=0.1, max=1000,
            default=1.0, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    post_x = FloatProperty(
            name="width",
            min=0.001, max=1000,
            default=0.04, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    post_y = FloatProperty(
            name="length",
            min=0.001, max=1000,
            default=0.04, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    post_z = FloatProperty(
            name="height",
            min=0.001, max=1000,
            default=1, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    post_alt = FloatProperty(
            name="altitude",
            min=-100, max=1000,
            default=0, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    user_defined_post_enable = BoolProperty(
            name="User",
            update=update,
            default=True
            )
    user_defined_post = StringProperty(
            name="user defined",
            update=update
            )
    idmat_post = EnumProperty(
            name="Post",
            items=materials_enum,
            default='4',
            update=update
            )
    subs = BoolProperty(
            name='enable',
            default=False,
            update=update
            )
    subs_spacing = FloatProperty(
            name="spacing",
            min=0.05, max=1000,
            default=0.10, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    subs_x = FloatProperty(
            name="width",
            min=0.001, max=1000,
            default=0.02, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    subs_y = FloatProperty(
            name="length",
            min=0.001, max=1000,
            default=0.02, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    subs_z = FloatProperty(
            name="height",
            min=0.001, max=1000,
            default=1, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    subs_alt = FloatProperty(
            name="altitude",
            min=-100, max=1000,
            default=0, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    subs_offset_x = FloatProperty(
            name="offset",
            min=-100.0, max=100,
            default=0.0, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    subs_bottom = EnumProperty(
            name="Bottom",
            items=(
                ('STEP', 'Follow step', '', 0),
                ('LINEAR', 'Linear', '', 1),
                ),
            default='STEP',
            update=update
            )
    user_defined_subs_enable = BoolProperty(
            name="User",
            update=update,
            default=True
            )
    user_defined_subs = StringProperty(
            name="user defined",
            update=update
            )
    idmat_subs = EnumProperty(
            name="Subs",
            items=materials_enum,
            default='4',
            update=update
            )
    panel = BoolProperty(
            name='enable',
            default=True,
            update=update
            )
    panel_alt = FloatProperty(
            name="altitude",
            min=-100, max=1000,
            default=0.25, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    panel_x = FloatProperty(
            name="width",
            min=0.001, max=1000,
            default=0.01, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    panel_z = FloatProperty(
            name="height",
            min=0.001, max=1000,
            default=0.6, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    panel_dist = FloatProperty(
            name="space",
            min=0.001, max=1000,
            default=0.05, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    panel_offset_x = FloatProperty(
            name="offset",
            min=-100.0, max=100,
            default=0.0, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    idmat_panel = EnumProperty(
            name="Panels",
            items=materials_enum,
            default='5',
            update=update
            )
    rail = BoolProperty(
            name="enable",
            update=update,
            default=False
            )
    rail_n = IntProperty(
            name="number",
            default=1,
            min=0,
            max=31,
            update=update
            )
    rail_x = FloatVectorProperty(
            name="width",
            default=[
                0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05,
                0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05,
                0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05,
                0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05
            ],
            size=31,
            min=0.001, max=1000,
            precision=2, step=1,
            unit='LENGTH',
            update=update
            )
    rail_z = FloatVectorProperty(
            name="height",
            default=[
                0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05,
                0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05,
                0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05,
                0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05
            ],
            size=31,
            min=0.001, max=1000,
            precision=2, step=1,
            unit='LENGTH',
            update=update
            )
    rail_offset = FloatVectorProperty(
            name="offset",
            default=[
                0, 0, 0, 0, 0, 0, 0, 0,
                0, 0, 0, 0, 0, 0, 0, 0,
                0, 0, 0, 0, 0, 0, 0, 0,
                0, 0, 0, 0, 0, 0, 0
            ],
            size=31,
            min=-100, max=100,
            precision=2, step=1,
            unit='LENGTH',
            update=update
            )
    rail_alt = FloatVectorProperty(
            name="altitude",
            default=[
                1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0,
                1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0,
                1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0,
                1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0
            ],
            size=31,
            min=-100, max=100,
            precision=2, step=1,
            unit='LENGTH',
            update=update
            )
    rail_mat = CollectionProperty(type=archipack_fence_material)

    handrail = BoolProperty(
            name="enable",
            update=update,
            default=True
            )
    handrail_offset = FloatProperty(
            name="offset",
            min=-100.0, max=100,
            default=0.0, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    handrail_alt = FloatProperty(
            name="altitude",
            min=-100, max=1000,
            default=1.0, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    handrail_extend = FloatProperty(
            name="extend",
            min=0, max=10,
            default=0.1, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    handrail_slice = BoolProperty(
            name='slice',
            default=True,
            update=update
            )
    handrail_slice_right = BoolProperty(
            name='slice',
            default=True,
            update=update
            )
    handrail_profil = EnumProperty(
            name="Profil",
            items=(
                ('SQUARE', 'Square', '', 0),
                ('CIRCLE', 'Circle', '', 1),
                ('COMPLEX', 'Circle over square', '', 2)
                ),
            default='SQUARE',
            update=update
            )
    handrail_x = FloatProperty(
            name="width",
            min=0.001, max=100,
            default=0.04, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    handrail_y = FloatProperty(
            name="height",
            min=0.001, max=100,
            default=0.04, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    handrail_radius = FloatProperty(
            name="radius",
            min=0.001, max=100,
            default=0.02, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    idmat_handrail = EnumProperty(
            name="Handrail",
            items=materials_enum,
            default='3',
            update=update
            )

    # UI layout related
    parts_expand = BoolProperty(
            default=False
            )
    rail_expand = BoolProperty(
            default=False
            )
    idmats_expand = BoolProperty(
            default=False
            )
    handrail_expand = BoolProperty(
            default=False
            )
    post_expand = BoolProperty(
            default=False
            )
    panel_expand = BoolProperty(
            default=False
            )
    subs_expand = BoolProperty(
            default=False
            )

    # Flag to prevent mesh update while making bulk changes over variables
    # use :
    # .auto_update = False
    # bulk changes
    # .auto_update = True
    auto_update = BoolProperty(
            options={'SKIP_SAVE'},
            default=True,
            update=update_manipulators
            )

    def find_in_selection(self, context):
        """
            find witch selected object this instance belongs to
            provide support for "copy to selected"
        """
        active = context.active_object
        selected = [o for o in context.selected_objects]
        for o in selected:
            if ARCHIPACK_PT_fence.params(o) == self:
                return active, selected, o
        return active, selected, None

    def update_parts(self):

        # remove rails materials
        for i in range(len(self.rail_mat), self.rail_n, -1):
            self.rail_mat.remove(i - 1)

        # add rails
        for i in range(len(self.rail_mat), self.rail_n):
            self.rail_mat.add()

        # remove parts
        for i in range(len(self.parts), self.n_parts, -1):
            self.parts.remove(i - 1)

        # add parts
        for i in range(len(self.parts), self.n_parts):
            p = self.parts.add()
            s = p.manipulators.add()
            s.type_key = "ANGLE"
            s.prop1_name = "a0"
            s = p.manipulators.add()
            s.type_key = "SIZE"
            s.prop1_name = "length"
            s = p.manipulators.add()
            # s.type_key = 'SNAP_POINT'
            s.type_key = 'WALL_SNAP'
            s.prop1_name = str(i)
            s.prop2_name = 'post_z'

    def interpolate_bezier(self, pts, wM, p0, p1, resolution):
        # straight segment, worth testing here
        # since this can lower points count by a resolution factor
        # use normalized to handle non linear t
        if resolution == 0:
            pts.append(wM * p0.co.to_3d())
        else:
            v = (p1.co - p0.co).normalized()
            d1 = (p0.handle_right - p0.co).normalized()
            d2 = (p1.co - p1.handle_left).normalized()
            if d1 == v and d2 == v:
                pts.append(wM * p0.co.to_3d())
            else:
                seg = interpolate_bezier(wM * p0.co,
                    wM * p0.handle_right,
                    wM * p1.handle_left,
                    wM * p1.co,
                    resolution + 1)
                for i in range(resolution):
                    pts.append(seg[i].to_3d())

    def from_spline(self, wM, resolution, spline):
        pts = []
        if spline.type == 'POLY':
            pts = [wM * p.co.to_3d() for p in spline.points]
            if spline.use_cyclic_u:
                pts.append(pts[0])
        elif spline.type == 'BEZIER':
            points = spline.bezier_points
            for i in range(1, len(points)):
                p0 = points[i - 1]
                p1 = points[i]
                self.interpolate_bezier(pts, wM, p0, p1, resolution)
            pts.append(wM * points[-1].co)
            if spline.use_cyclic_u:
                p0 = points[-1]
                p1 = points[0]
                self.interpolate_bezier(pts, wM, p0, p1, resolution)
                pts.append(pts[0])

        self.n_parts = len(pts) - 1
        self.update_parts()

        p0 = pts.pop(0)
        a0 = 0
        for i, p1 in enumerate(pts):
            dp = p1 - p0
            da = atan2(dp.y, dp.x) - a0
            if da > pi:
                da -= 2 * pi
            if da < -pi:
                da += 2 * pi
            p = self.parts[i]
            p.length = dp.to_2d().length
            p.dz = dp.z
            p.a0 = da
            a0 += da
            p0 = p1

    def update_path(self, context):
        user_def_path = context.scene.objects.get(self.user_defined_path)
        if user_def_path is not None and user_def_path.type == 'CURVE':
            self.auto_update = False
            self.from_spline(user_def_path.matrix_world, self.user_defined_resolution, user_def_path.data.splines[0])
            self.auto_update = True

    def get_generator(self):
        g = FenceGenerator(self.parts)
        for part in self.parts:
            # type, radius, da, length
            g.add_part(part.type, part.radius, part.a0, part.da, part.length)

        # param_t(da, part_length)
        g.param_t(self.angle_limit, self.post_spacing)
        return g

    def update(self, context, manipulable_refresh=False):

        active, selected, o = self.find_in_selection(context)

        if o is None or not self.auto_update:
            return

        # clean up manipulators before any data model change
        if manipulable_refresh:
            self.manipulable_disable(context)

        self.update_parts()

        verts = []
        faces = []
        matids = []
        uvs = []

        g = self.get_generator()

        # depth at bottom
        # self.manipulators[1].set_pts([(0, 0, 0), (0, 0, self.height), (1, 0, 0)])

        if self.user_defined_post_enable:
            # user defined posts
            user_def_post = context.scene.objects.get(self.user_defined_post)
            if user_def_post is not None and user_def_post.type == 'MESH':
                g.setup_user_defined_post(user_def_post, self.post_x, self.post_y, self.post_z)

        if self.post:
            g.make_post(0.5 * self.post_x, 0.5 * self.post_y, self.post_z,
                    self.post_alt, self.x_offset,
                    int(self.idmat_post), verts, faces, matids, uvs)

        # reset user def posts
        g.user_defined_post = None

        # user defined subs
        if self.user_defined_subs_enable:
            user_def_subs = context.scene.objects.get(self.user_defined_subs)
            if user_def_subs is not None and user_def_subs.type == 'MESH':
                g.setup_user_defined_post(user_def_subs, self.subs_x, self.subs_y, self.subs_z)

        if self.subs:
            g.make_subs(0.5 * self.subs_x, 0.5 * self.subs_y, self.subs_z,
                    self.post_y, self.subs_alt, self.subs_spacing,
                    self.x_offset - self.subs_offset_x, int(self.idmat_subs), verts, faces, matids, uvs)

        g.user_defined_post = None

        if self.panel:
            g.make_panels(0.5 * self.panel_x, self.panel_z, self.post_y,
                    self.panel_alt, self.panel_dist, self.x_offset - self.panel_offset_x,
                    int(self.idmat_panel), verts, faces, matids, uvs)

        if self.rail:
            for i in range(self.rail_n):
                x = 0.5 * self.rail_x[i]
                y = self.rail_z[i]
                rail = [Vector((-x, y)), Vector((-x, 0)), Vector((x, 0)), Vector((x, y))]
                g.make_profile(rail, int(self.rail_mat[i].index), self.x_offset - self.rail_offset[i],
                        self.rail_alt[i], 0, verts, faces, matids, uvs)

        if self.handrail_profil == 'COMPLEX':
            sx = self.handrail_x
            sy = self.handrail_y
            handrail = [Vector((sx * x, sy * y)) for x, y in [
            (-0.28, 1.83), (-0.355, 1.77), (-0.415, 1.695), (-0.46, 1.605), (-0.49, 1.51), (-0.5, 1.415),
            (-0.49, 1.315), (-0.46, 1.225), (-0.415, 1.135), (-0.355, 1.06), (-0.28, 1.0), (-0.255, 0.925),
            (-0.33, 0.855), (-0.5, 0.855), (-0.5, 0.0), (0.5, 0.0), (0.5, 0.855), (0.33, 0.855), (0.255, 0.925),
            (0.28, 1.0), (0.355, 1.06), (0.415, 1.135), (0.46, 1.225), (0.49, 1.315), (0.5, 1.415),
            (0.49, 1.51), (0.46, 1.605), (0.415, 1.695), (0.355, 1.77), (0.28, 1.83), (0.19, 1.875),
            (0.1, 1.905), (0.0, 1.915), (-0.095, 1.905), (-0.19, 1.875)]]

        elif self.handrail_profil == 'SQUARE':
            x = 0.5 * self.handrail_x
            y = self.handrail_y
            handrail = [Vector((-x, y)), Vector((-x, 0)), Vector((x, 0)), Vector((x, y))]
        elif self.handrail_profil == 'CIRCLE':
            r = self.handrail_radius
            handrail = [Vector((r * sin(0.1 * -a * pi), r * (0.5 + cos(0.1 * -a * pi)))) for a in range(0, 20)]

        if self.handrail:
            g.make_profile(handrail, int(self.idmat_handrail), self.x_offset - self.handrail_offset,
                self.handrail_alt, self.handrail_extend, verts, faces, matids, uvs)

        bmed.buildmesh(context, o, verts, faces, matids=matids, uvs=uvs, weld=True, clean=True)

        # enable manipulators rebuild
        if manipulable_refresh:
            self.manipulable_refresh = True

        # restore context
        try:
            for o in selected:
                o.select = True
        except:
            pass

        active.select = True
        context.scene.objects.active = active

    def manipulable_setup(self, context):
        """
            TODO: Implement the setup part as per parent object basis

            self.manipulable_disable(context)
            o = context.active_object
            for m in self.manipulators:
                self.manip_stack.append(m.setup(context, o, self))

        """
        self.manipulable_disable(context)
        o = context.active_object
        d = self

        for i, part in enumerate(d.parts):
            if i >= d.n_parts:
                break

            if i > 0:
                # start angle
                self.manip_stack.append(part.manipulators[0].setup(context, o, part))

            # length / radius + angle
            self.manip_stack.append(part.manipulators[1].setup(context, o, part))

            # snap point
            self.manip_stack.append(part.manipulators[2].setup(context, o, self))

        for m in self.manipulators:
            self.manip_stack.append(m.setup(context, o, self))


class ARCHIPACK_PT_fence(Panel):
    bl_idname = "ARCHIPACK_PT_fence"
    bl_label = "Fence"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'ArchiPack'

    def draw(self, context):
        o = context.object
        scene = context.scene
        prop = ARCHIPACK_PT_fence.params(o)
        if prop is None:
            return
        layout = self.layout
        row = layout.row(align=True)
        row.operator('archipack.fence_manipulate')
        box = layout.box()
        # box.label(text="Styles")
        row = box.row(align=True)
        row.menu("ARCHIPACK_MT_fence_preset", text=bpy.types.ARCHIPACK_MT_fence_preset.bl_label)
        row.operator("archipack.fence_preset", text="", icon='ZOOMIN')
        row.operator("archipack.fence_preset", text="", icon='ZOOMOUT').remove_active = True
        row = layout.row(align=True)
        box = layout.box()
        row.prop_search(prop, "user_defined_path", scene, "objects", text="", icon='OUTLINER_OB_CURVE')
        box.prop(prop, 'user_defined_resolution')
        box.prop(prop, 'x_offset')
        box.prop(prop, 'angle_limit')
        box = layout.box()
        row = box.row()
        if prop.parts_expand:
            row.prop(prop, 'parts_expand', icon="TRIA_DOWN", icon_only=True, text="Parts", emboss=False)
            box.prop(prop, 'n_parts')
            for i, part in enumerate(prop.parts):
                part.draw(layout, context, i)
        else:
            row.prop(prop, 'parts_expand', icon="TRIA_RIGHT", icon_only=True, text="Parts", emboss=False)

        box = layout.box()
        row = box.row(align=True)
        if prop.handrail_expand:
            row.prop(prop, 'handrail_expand', icon="TRIA_DOWN", icon_only=True, text="Handrail", emboss=False)
        else:
            row.prop(prop, 'handrail_expand', icon="TRIA_RIGHT", icon_only=True, text="Handrail", emboss=False)

        row.prop(prop, 'handrail')

        if prop.handrail_expand:
            box.prop(prop, 'handrail_alt')
            box.prop(prop, 'handrail_offset')
            box.prop(prop, 'handrail_extend')
            box.prop(prop, 'handrail_profil')
            if prop.handrail_profil != 'CIRCLE':
                box.prop(prop, 'handrail_x')
                box.prop(prop, 'handrail_y')
            else:
                box.prop(prop, 'handrail_radius')
            row = box.row(align=True)
            row.prop(prop, 'handrail_slice')

        box = layout.box()
        row = box.row(align=True)
        if prop.post_expand:
            row.prop(prop, 'post_expand', icon="TRIA_DOWN", icon_only=True, text="Post", emboss=False)
        else:
            row.prop(prop, 'post_expand', icon="TRIA_RIGHT", icon_only=True, text="Post", emboss=False)
        row.prop(prop, 'post')
        if prop.post_expand:
            box.prop(prop, 'post_spacing')
            box.prop(prop, 'post_x')
            box.prop(prop, 'post_y')
            box.prop(prop, 'post_z')
            box.prop(prop, 'post_alt')
            row = box.row(align=True)
            row.prop(prop, 'user_defined_post_enable', text="")
            row.prop_search(prop, "user_defined_post", scene, "objects", text="")

        box = layout.box()
        row = box.row(align=True)
        if prop.subs_expand:
            row.prop(prop, 'subs_expand', icon="TRIA_DOWN", icon_only=True, text="Subs", emboss=False)
        else:
            row.prop(prop, 'subs_expand', icon="TRIA_RIGHT", icon_only=True, text="Subs", emboss=False)

        row.prop(prop, 'subs')
        if prop.subs_expand:
            box.prop(prop, 'subs_spacing')
            box.prop(prop, 'subs_x')
            box.prop(prop, 'subs_y')
            box.prop(prop, 'subs_z')
            box.prop(prop, 'subs_alt')
            box.prop(prop, 'subs_offset_x')
            row = box.row(align=True)
            row.prop(prop, 'user_defined_subs_enable', text="")
            row.prop_search(prop, "user_defined_subs", scene, "objects", text="")

        box = layout.box()
        row = box.row(align=True)
        if prop.panel_expand:
            row.prop(prop, 'panel_expand', icon="TRIA_DOWN", icon_only=True, text="Panels", emboss=False)
        else:
            row.prop(prop, 'panel_expand', icon="TRIA_RIGHT", icon_only=True, text="Panels", emboss=False)
        row.prop(prop, 'panel')
        if prop.panel_expand:
            box.prop(prop, 'panel_dist')
            box.prop(prop, 'panel_x')
            box.prop(prop, 'panel_z')
            box.prop(prop, 'panel_alt')
            box.prop(prop, 'panel_offset_x')

        box = layout.box()
        row = box.row(align=True)
        if prop.rail_expand:
            row.prop(prop, 'rail_expand', icon="TRIA_DOWN", icon_only=True, text="Rails", emboss=False)
        else:
            row.prop(prop, 'rail_expand', icon="TRIA_RIGHT", icon_only=True, text="Rails", emboss=False)
        row.prop(prop, 'rail')
        if prop.rail_expand:
            box.prop(prop, 'rail_n')
            for i in range(prop.rail_n):
                box = layout.box()
                box.label(text="Rail " + str(i + 1))
                box.prop(prop, 'rail_x', index=i)
                box.prop(prop, 'rail_z', index=i)
                box.prop(prop, 'rail_alt', index=i)
                box.prop(prop, 'rail_offset', index=i)
                box.prop(prop.rail_mat[i], 'index', text="")

        box = layout.box()
        row = box.row()

        if prop.idmats_expand:
            row.prop(prop, 'idmats_expand', icon="TRIA_DOWN", icon_only=True, text="Materials", emboss=False)
            box.prop(prop, 'idmat_handrail')
            box.prop(prop, 'idmat_panel')
            box.prop(prop, 'idmat_post')
            box.prop(prop, 'idmat_subs')
        else:
            row.prop(prop, 'idmats_expand', icon="TRIA_RIGHT", icon_only=True, text="Materials", emboss=False)

    @classmethod
    def params(cls, o):
        try:
            if 'archipack_fence' not in o.data:
                return False
            else:
                return o.data.archipack_fence[0]
        except:
            return False

    @classmethod
    def filter(cls, o):
        try:
            if 'archipack_fence' not in o.data:
                return False
            else:
                return True
        except:
            return False

    @classmethod
    def poll(cls, context):
        o = context.object
        if o is None:
            return False
        return cls.filter(o)

# ------------------------------------------------------------------
# Define operator class to create object
# ------------------------------------------------------------------


class ARCHIPACK_OT_fence(Operator):
    bl_idname = "archipack.fence"
    bl_label = "Fence"
    bl_description = "Fence"
    bl_category = 'Archipack'
    bl_options = {'REGISTER', 'UNDO'}

    auto_manipulate = BoolProperty(default=True)

    # -----------------------------------------------------
    # Draw (create UI interface)
    # -----------------------------------------------------
    # noinspection PyUnusedLocal
    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.label("Use Properties panel (N) to define parms", icon='INFO')

    def create(self, context):
        m = bpy.data.meshes.new("Fence")
        o = bpy.data.objects.new("Fence", m)
        d = m.archipack_fence.add()
        s = d.manipulators.add()
        s.prop1_name = "width"
        s = d.manipulators.add()
        s.prop1_name = "height"
        s.normal = Vector((0, 1, 0))
        context.scene.objects.link(o)
        o.select = True
        context.scene.objects.active = o
        d.update(context)
        # MaterialUtils.add_fence_materials(o)
        o.location = bpy.context.scene.cursor_location
        o.select = True
        context.scene.objects.active = o
        return o

    # -----------------------------------------------------
    # Execute
    # -----------------------------------------------------
    def execute(self, context):
        if context.mode == "OBJECT":
            bpy.ops.object.select_all(action="DESELECT")
            o = self.create(context)
            o.location = bpy.context.scene.cursor_location
            if self.auto_manipulate:
                bpy.ops.archipack.fence_manipulate('INVOKE_DEFAULT')
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, "Archipack: Option only valid in Object mode")
            return {'CANCELLED'}


# ------------------------------------------------------------------
# Define operator class to create object
# ------------------------------------------------------------------


class ARCHIPACK_OT_fence_from_curve(Operator):
    bl_idname = "archipack.fence_from_curve"
    bl_label = "Fence curve"
    bl_description = "Create a fence from a curve"
    bl_category = 'Archipack'
    bl_options = {'REGISTER', 'UNDO'}

    auto_manipulate = BoolProperty(default=True)

    @classmethod
    def poll(self, context):
        return context.active_object is not None and context.active_object.type == 'CURVE'
    # -----------------------------------------------------
    # Draw (create UI interface)
    # -----------------------------------------------------
    # noinspection PyUnusedLocal

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.label("Use Properties panel (N) to define parms", icon='INFO')

    def create(self, context):
        curve = context.active_object
        m = bpy.data.meshes.new("Fence")
        o = bpy.data.objects.new("Fence", m)
        d = m.archipack_fence.add()
        s = d.manipulators.add()
        s.prop1_name = "width"
        s = d.manipulators.add()
        s.prop1_name = "height"
        s.normal = Vector((0, 1, 0))
        d.user_defined_path = curve.name
        context.scene.objects.link(o)
        o.select = True
        context.scene.objects.active = o
        d.update_path(context)
        MaterialUtils.add_stair_materials(o)
        spline = curve.data.splines[0]
        if spline.type == 'POLY':
            pt = spline.points[0].co
        elif spline.type == 'BEZIER':
            pt = spline.bezier_points[0].co
        else:
            pt = Vector((0, 0, 0))
        # pretranslate
        o.matrix_world = curve.matrix_world * Matrix([
            [1, 0, 0, pt.x],
            [0, 1, 0, pt.y],
            [0, 0, 1, pt.z],
            [0, 0, 0, 1]
            ])
        o.select = True
        context.scene.objects.active = o
        return o

    # -----------------------------------------------------
    # Execute
    # -----------------------------------------------------
    def execute(self, context):
        if context.mode == "OBJECT":
            bpy.ops.object.select_all(action="DESELECT")
            self.create(context)
            if self.auto_manipulate:
                bpy.ops.archipack.fence_manipulate('INVOKE_DEFAULT')
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, "Archipack: Option only valid in Object mode")
            return {'CANCELLED'}

# ------------------------------------------------------------------
# Define operator class to manipulate object
# ------------------------------------------------------------------


class ARCHIPACK_OT_fence_manipulate(Operator):
    bl_idname = "archipack.fence_manipulate"
    bl_label = "Manipulate"
    bl_description = "Manipulate"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(self, context):
        return ARCHIPACK_PT_fence.filter(context.active_object)

    def modal(self, context, event):
        return self.d.manipulable_modal(context, event)

    def invoke(self, context, event):
        if context.space_data.type == 'VIEW_3D':
            o = context.active_object
            self.d = o.data.archipack_fence[0]
            if self.d.manipulable_invoke(context):
                context.window_manager.modal_handler_add(self)
                return {'RUNNING_MODAL'}
            else:
                return {'FINISHED'}
        else:
            self.report({'WARNING'}, "Active space must be a View3d")
            return {'CANCELLED'}


# ------------------------------------------------------------------
# Define operator class to load / save presets
# ------------------------------------------------------------------


class ARCHIPACK_MT_fence_preset(Menu):
    bl_label = "Fence Styles"
    preset_subdir = "archipack_fence"
    preset_operator = "script.execute_preset"
    draw = Menu.draw_preset


class ARCHIPACK_OT_fence_preset(ArchipackPreset, Operator):
    """Add a Fence Styles"""
    bl_idname = "archipack.fence_preset"
    bl_label = "Add Fence Style"
    preset_menu = "ARCHIPACK_MT_fence_preset"

    datablock_name = StringProperty(
        name="Datablock",
        default='archipack_fence',
        maxlen=64,
        options={'HIDDEN', 'SKIP_SAVE'},
        )

    @property
    def blacklist(self):
        return ['n_parts', 'parts', 'manipulators', 'user_defined_path']


bpy.utils.register_class(archipack_fence_material)
bpy.utils.register_class(archipack_fence_part)
bpy.utils.register_class(archipack_fence)
Mesh.archipack_fence = CollectionProperty(type=archipack_fence)
bpy.utils.register_class(ARCHIPACK_MT_fence_preset)
bpy.utils.register_class(ARCHIPACK_PT_fence)
bpy.utils.register_class(ARCHIPACK_OT_fence)
bpy.utils.register_class(ARCHIPACK_OT_fence_preset)
bpy.utils.register_class(ARCHIPACK_OT_fence_manipulate)
bpy.utils.register_class(ARCHIPACK_OT_fence_from_curve)
