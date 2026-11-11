# -*- coding: utf-8 -*-
"""Второй вход: дизайн из голого STL (карта высот -> уровни -> контуры -> радиус дна).

Точность ниже, чем у описания из OpenSCAD, и каждое допущение попадает в
сообщения дизайна (уровень info/warn):
  * верх детали = максимальный Z; Z0 переносится туда, XY - в центр габарита;
  * карман = связная область ячеек ниже верха; его глубина = модальный Z дна;
  * контуры - границы ячеек (шаг pitch), упрощённые с допуском 0.6*pitch;
  * радиус скругления дно/стенка оценивается по ширине наклонной полосы вдоль
    стенки и округляется к радиусу ближайшей чашечной фрезы в библиотеке (если
    библиотека передана), иначе - как есть;
  * всё, что не плоскость и не полоса скругления, помечается предупреждением.
"""

import math
from collections import Counter

from ..geometry.polyline import simplify_ring, poly_area, dist_to_poly
from ..geometry.offset import offset_ring
from ..geometry.region import Region
from ..scad.stl import load_stl, bounds
from ..verify.heightmap import design_map, NO_MATERIAL
from .model import Design, Blank, Outline, Pocket, Message


class _Blank(object):
    def __init__(self, sx, sy):
        self.size_x, self.size_y = sx, sy


def _components(mask, nx, ny):
    """Связные компоненты (4-соседство) битовой маски -> список списков индексов."""
    seen = bytearray(nx * ny)
    comps = []
    for start in range(nx * ny):
        if not mask[start] or seen[start]:
            continue
        stack = [start]
        seen[start] = 1
        comp = []
        while stack:
            c = stack.pop()
            comp.append(c)
            i, j = c % nx, c // nx
            for ii, jj in ((i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1)):
                if 0 <= ii < nx and 0 <= jj < ny:
                    k = jj * nx + ii
                    if mask[k] and not seen[k]:
                        seen[k] = 1
                        stack.append(k)
        comps.append(comp)
    return comps


def _boundary_loops(cells, nx, ny, x0, y0, pitch):
    """Границы множества ячеек по «шагающим квадратам»: вершины на серединах рёбер между
    ячейкой внутри и ячейкой снаружи, диагонали в углах. Даёт ломаную с поворотами <= 45°
    вместо лестницы по рёбрам ячеек (лестницу не сглаживает упрощение, а её наружный
    эквидистант самопересекается)."""
    inset = set(cells)

    def inside(i, j):
        return 0 <= i < nx and 0 <= j < ny and (j * nx + i) in inset

    # узлы решётки - центры ячеек; квадрат (i, j) образован центрами (i,j),(i+1,j),(i+1,j+1),(i,j+1)
    def cx(i):
        return x0 + (i + 0.5) * pitch

    def cy(j):
        return y0 + (j + 0.5) * pitch

    # рёбра квадрата: 0 = низ (между (i,j) и (i+1,j)), 1 = право, 2 = верх, 3 = лево
    def mid(i, j, e):
        if e == 0:
            return (cx(i) + 0.5 * pitch, cy(j))
        if e == 1:
            return (cx(i + 1), cy(j) + 0.5 * pitch)
        if e == 2:
            return (cx(i) + 0.5 * pitch, cy(j + 1))
        return (cx(i), cy(j) + 0.5 * pitch)

    # таблица: для кода углов (a=(i,j), b=(i+1,j), c=(i+1,j+1), d=(i,j+1)) - отрезки (ребро_из, ребро_в),
    # ориентированные так, чтобы область оставалась слева
    TABLE = {
        1: [(3, 0)], 2: [(0, 1)], 3: [(3, 1)], 4: [(1, 2)], 6: [(0, 2)], 7: [(3, 2)], 8: [(2, 3)],
        9: [(2, 0)], 11: [(2, 1)], 12: [(1, 3)], 13: [(1, 0)], 14: [(0, 3)],
        5: [(3, 0), (1, 2)], 10: [(0, 1), (2, 3)],
    }
    edges = {}
    for j in range(-1, ny):
        for i in range(-1, nx):
            code = (1 if inside(i, j) else 0) | (2 if inside(i + 1, j) else 0) | \
                   (4 if inside(i + 1, j + 1) else 0) | (8 if inside(i, j + 1) else 0)
            if code in (0, 15):
                continue
            segs = TABLE[code]
            if code in (5, 10):          # неоднозначность: соединяем так, чтобы диагональные ячейки не сливались
                segs = [(3, 2), (1, 0)] if code == 5 else [(0, 3), (2, 1)]
            for (ea, eb) in segs:
                edges[(i, j, ea)] = (i, j, eb)
    # ключи рёбер квадрата -> общий ключ ребра решётки, чтобы сшить соседние квадраты
    def gkey(i, j, e):
        if e == 0:
            return ('h', i, j)
        if e == 2:
            return ('h', i, j + 1)
        if e == 3:
            return ('v', i, j)
        return ('v', i + 1, j)

    starts = {}
    for (i, j, ea), (i2, j2, eb) in edges.items():
        starts[gkey(i, j, ea)] = ((i, j, ea), (i2, j2, eb))
    loops = []
    used = set()
    for k0 in list(starts):
        if k0 in used:
            continue
        loop = []
        k = k0
        while k in starts and k not in used:
            used.add(k)
            (i, j, ea), (i2, j2, eb) = starts[k]
            loop.append(mid(i, j, ea))
            k = gkey(i2, j2, eb)
        if len(loop) >= 3:
            loops.append(loop)
    return loops


def _chaikin(ring):
    """Сглаживание Чайкина (срезание углов) замкнутого контура: ломаная шагающих квадратов
    зубчатая (повороты до 45°), а настоящие стенки гладкие; сглаживание не уводит контур
    дальше четверти ребра от исходного."""
    out = []
    n = len(ring)
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        out.append((0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]))
        out.append((0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]))
    return out


def _region_from_cells(cells, nx, ny, x0, y0, pitch, tol, shrink=0.0):
    """Область по ячейкам; shrink > 0 сдвигает контур внутрь области (у карманов - лучше
    недорез в полшага, чем зарез стенки: граница ячеек лежит до полшага снаружи истинной)."""
    loops = _boundary_loops(cells, nx, ny, x0, y0, pitch)
    if not loops:
        return None
    # сгладить -> упростить -> снова сгладить: после упрощения остаются углы ~30°, а по ним
    # эквидистант обхода стенок рвётся на куски и чистовая не доходит до стенки
    loops = [_chaikin(_chaikin(simplify_ring(_chaikin(_chaikin(l)), tol))) for l in loops]
    loops = [l for l in loops if len(l) >= 3]
    loops.sort(key=lambda l: -abs(poly_area(l)))
    reg = Region(loops[0], loops[1:])
    if abs(shrink) > 1e-9:
        inward = shrink > 0
        outer = offset_ring(reg.outer, abs(shrink), inward=inward)
        holes = [offset_ring(h, abs(shrink), inward=not inward) for h in reg.holes]
        if len(outer) >= 3:
            reg = Region(outer, [h for h in holes if len(h) >= 3])
    return reg


def from_mesh(stl_path, pitch=0.5, blank=None, level_tol=0.15, min_area_cm2=1.0, library=None):
    tris = load_stl(stl_path)
    if not tris:
        raise ValueError("STL пуст")
    bx0, by0, bz0, bx1, by1, bz1 = bounds(tris)
    cx, cy = 0.5 * (bx0 + bx1), 0.5 * (by0 + by1)
    top = bz1
    msgs = [Message("info", "MESH_ORIGIN", "STL: начало координат перенесено в центр габарита (сдвиг %.2f, %.2f), "
                    "Z0 = верх модели (%.2f)" % (cx, cy, top))]
    tris = [tuple((p[0] - cx, p[1] - cy, p[2] - top) for p in t) for t in tris]
    thick = top - bz0
    sx, sy = (bx1 - bx0) + 2 * pitch, (by1 - by0) + 2 * pitch
    hm = design_map(tris, _Blank(sx, sy), pitch)
    nx, ny, z = hm.nx, hm.ny, hm.z
    have = [v > NO_MATERIAL / 2 for v in z]
    n_have = sum(have)
    if not n_have:
        raise ValueError("STL не даёт поверхности сверху")
    # контур детали
    outline_cells = [k for k in range(nx * ny) if have[k]]
    comps = _components(bytearray(have), nx, ny)
    comps.sort(key=len, reverse=True)
    if len(comps) > 1:
        msgs.append(Message("warn", "MESH_PARTS", "в STL %d отдельных тел сверху; взято самое большое" % len(comps)))
    # контур детали - наружу на полшага + допуск упрощения: деталь выйдет чуть больше,
    # но контурная фреза не зайдёт в неё; карманы - на столько же внутрь
    bias = 0.5 * pitch + 0.6 * pitch
    outline_region = _region_from_cells(comps[0], nx, ny, hm.x0, hm.y0, pitch, 0.6 * pitch, shrink=-bias)
    outline = Outline("polygon", region=outline_region)
    # уровни: верх = 0 (в пределах допуска); карман = связная область ниже верха
    below = bytearray(nx * ny)
    for k in comps[0]:
        if z[k] < -level_tol:
            below[k] = 1
    pockets = []
    fid = 0
    min_cells = int(min_area_cm2 * 100.0 / (pitch * pitch))
    for comp in sorted(_components(below, nx, ny), key=lambda c: -len(c)):
        if len(comp) < min_cells:
            continue
        # дно = модальный Z (округлённо до 0.05) среди ячеек компоненты
        cnt = Counter(round(z[k] / 0.05) * 0.05 for k in comp)
        floor_z, _ = cnt.most_common(1)[0]
        depth = -floor_z
        floor_cells = [k for k in comp if abs(z[k] - floor_z) <= level_tol]
        fid += 1
        region = _region_from_cells(comp, nx, ny, hm.x0, hm.y0, pitch, 0.6 * pitch, shrink=bias)
        if region is None:
            continue
        # полоса скругления: ячейки между дном и верхом; её ширина у стенки ~ радиус
        band = [k for k in comp if z[k] > floor_z + level_tol]
        rc = 0.0
        if band and floor_cells:
            floor_region = _region_from_cells(floor_cells, nx, ny, hm.x0, hm.y0, pitch, 0.6 * pitch)
            if floor_region is not None:
                ring = region.outer
                ds = sorted(dist_to_poly(p, ring) for p in floor_region.outer[::max(1, len(floor_region.outer) // 200)])
                if ds:
                    # граница «плоского» дна проходит там, где скругление поднялось на level_tol:
                    # d = R - sqrt(R^2 - (R - tol)^2)  =>  R = d + tol + sqrt(2 d tol)
                    d_flat = ds[len(ds) // 2]
                    rc = d_flat + level_tol + math.sqrt(2.0 * d_flat * level_tol)
                # проверка формы полосы: точки полосы должны лежать на четверти окружности
                bad = 0
                for k in band[::max(1, len(band) // 400)]:
                    i, j = k % nx, k // nx
                    p = hm.cell_center(i, j)
                    d = dist_to_poly(p, ring)
                    h = z[k] - floor_z
                    if rc > 0 and d < rc:
                        h_exp = rc - math.sqrt(max(0.0, rc * rc - (rc - d) ** 2))
                        if abs(h - h_exp) > 0.3 + pitch:
                            bad += 1
                if bad > 0.2 * max(1, len(band[::max(1, len(band) // 400)])):
                    msgs.append(Message("warn", "MESH_NOT_FILLET",
                                        "карман %d: наклонная поверхность у стенок не похожа на скругление R%.1f "
                                        "(деталь не 2.5-D или радиус переменный)" % (fid, rc), str(fid)))
        if library is not None and rc > 0:
            bowls = [t for t in library.tools if t.get("type") == "bowl" and t.get("corner_r")]
            if bowls:
                near = min(bowls, key=lambda t: abs(float(t["corner_r"]) - rc))
                if abs(float(near["corner_r"]) - rc) <= 1.0:
                    msgs.append(Message("info", "MESH_FILLET", "карман %d: радиус дна оценён как %.2f, принят R%.2f "
                                        "фрезы %s" % (fid, rc, float(near["corner_r"]), near["id"]), str(fid)))
                    rc = float(near["corner_r"])
        else:
            msgs.append(Message("info", "MESH_FILLET", "карман %d: радиус дна оценён по полосе у стенки как %.2f мм"
                                % (fid, rc), str(fid)))
        pockets.append(Pocket(fid, [region], round(depth, 2), round(rc, 3), ref=["mesh", fid]))
    if not pockets:
        msgs.append(Message("warn", "MESH_NO_POCKETS", "в STL не найдено карманов глубже %.2f мм" % level_tol))
    if blank is None:
        bsx = math.ceil(((bx1 - bx0) + 24.0) / 5.0) * 5.0
        bsy = math.ceil(((by1 - by0) + 24.0) / 5.0) * 5.0
        blank = Blank(bsx, bsy, round(thick, 2))
        msgs.append(Message("info", "MESH_BLANK", "заготовка принята %.0f x %.0f x %.1f (габарит + 12 мм на сторону)"
                            % (bsx, bsy, thick)))
    msgs.append(Message("info", "MESH_RES", "шаг карты %.2f мм: контуры точны до ~%.2f мм, дуги - ломаные; контур детали "
                        "сдвинут наружу, контуры карманов - внутрь на %.2f мм, чтобы не зарезать стенки"
                        % (pitch, 0.6 * pitch, bias)))
    d = Design("mesh", None, blank, round(thick, 2), outline, pockets, [], [],
               {"cells": n_have, "edge_band": round(2 * bias + 0.5, 3)},   # контур из STL точен до ~2*bias
               msgs, {"stl": stl_path, "pitch": pitch, "shift": [cx, cy, top]})
    return d
