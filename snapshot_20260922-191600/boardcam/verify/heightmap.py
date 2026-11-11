# -*- coding: utf-8 -*-
"""Контроль по карте высот: STL фигуры (замысел) против траекторий (что снимет фреза).

Карта замысла: z-буфер треугольников STL с шагом pitch (верхняя поверхность = max z).
Карта обработки: заготовка z=0, каждый рабочий ход штампуется отпечатком фрезы
(плоская, чашечная с радиусом corner_r, шаровая). Сравнение по ячейкам внутри
контура детали:
  * обработка ниже замысла больше чем на gouge_tol -> ЗАРЕЗ, прогон не принят;
  * обработка выше замысла внутри кармана -> остаток: «фреза не входит» (ни одно
    допустимое положение чистовой фрезы не накрывает ячейку) или «дыра в
    траектории» (фреза могла пройти и не прошла - ошибка генератора).
Учитываются только операции верхней стороны в системе Z0 = верх готовой детали
(торцовка 00 и нижний контур 03b идут в других системах координат).
Ловит также расхождение echo и геометрии фигуры: STL строится из геометрии,
траектории - из описания.
"""

import math
import struct
from array import array

MAGIC = b"BCHM"


class HeightMap(object):
    def __init__(self, x0, y0, nx, ny, pitch, fill):
        self.x0, self.y0, self.nx, self.ny, self.pitch = x0, y0, nx, ny, pitch
        self.z = array("f", [fill]) * (nx * ny)

    def cell_center(self, i, j):
        return (self.x0 + (i + 0.5) * self.pitch, self.y0 + (j + 0.5) * self.pitch)

    def cell_of(self, x, y):
        return int(math.floor((x - self.x0) / self.pitch)), int(math.floor((y - self.y0) / self.pitch))

    def save(self, path):
        with open(path, "wb") as f:
            f.write(MAGIC)
            f.write(struct.pack("<IIfff", self.nx, self.ny, self.pitch, self.x0, self.y0))
            f.write(self.z.tobytes())

    @classmethod
    def load(cls, path):
        with open(path, "rb") as f:
            data = f.read()
        if data[:4] != MAGIC:
            raise ValueError("не карта высот boardcam")
        nx, ny, pitch, x0, y0 = struct.unpack_from("<IIfff", data, 4)
        hm = cls(x0, y0, nx, ny, pitch, 0.0)
        hm.z = array("f")
        hm.z.frombytes(data[4 + 20:4 + 20 + 4 * nx * ny])
        return hm


NO_MATERIAL = -1e9


def grid_for_blank(blank, pitch):
    nx = int(math.ceil(blank.size_x / pitch))
    ny = int(math.ceil(blank.size_y / pitch))
    return -blank.size_x / 2.0, -blank.size_y / 2.0, nx, ny


def design_map(tris, blank, pitch):
    """z-буфер STL: в каждой ячейке максимальный z поверхности; NO_MATERIAL - где детали нет."""
    x0, y0, nx, ny = grid_for_blank(blank, pitch)
    hm = HeightMap(x0, y0, nx, ny, pitch, NO_MATERIAL)
    z = hm.z
    for (a, b, c) in tris:
        ax, ay, az = a
        bx, by, bz = b
        cx, cy, cz = c
        det = (bx - ax) * (cy - ay) - (cx - ax) * (by - ay)
        if abs(det) < 1e-9:                      # вертикальная или вырожденная грань
            continue
        i0 = max(0, int(math.floor((min(ax, bx, cx) - x0) / pitch - 0.5)))
        i1 = min(nx - 1, int(math.ceil((max(ax, bx, cx) - x0) / pitch - 0.5)))
        j0 = max(0, int(math.floor((min(ay, by, cy) - y0) / pitch - 0.5)))
        j1 = min(ny - 1, int(math.ceil((max(ay, by, cy) - y0) / pitch - 0.5)))
        inv = 1.0 / det
        for j in range(j0, j1 + 1):
            py = y0 + (j + 0.5) * pitch
            row = j * nx
            for i in range(i0, i1 + 1):
                px = x0 + (i + 0.5) * pitch
                l1 = ((bx - ax) * (py - ay) - (px - ax) * (by - ay)) * inv    # барицентрические
                l2 = ((px - ax) * (cy - ay) - (cx - ax) * (py - ay)) * inv
                # l1 = вес c, l2 = вес b (по формуле выше), l0 = вес a
                if l1 < -1e-9 or l2 < -1e-9 or l1 + l2 > 1.0 + 1e-9:
                    continue
                l0 = 1.0 - l1 - l2
                zz = l0 * az + l2 * bz + l1 * cz
                if zz > z[row + i]:
                    z[row + i] = zz
    return hm


def tool_profile(tool):
    """-> функция d (расстояние от оси) -> подъём кромки над остриём; r - радиус фрезы."""
    r = tool["dia"] / 2.0
    rc = float(tool.get("corner_r", 0.0) or 0.0)
    typ = tool.get("type", "flat")
    if typ in ("flat", "surfacing", "vee") or rc <= 1e-9:
        return (lambda d: 0.0), r
    rc = min(rc, r)
    flat = r - rc

    def prof(d):
        if d <= flat:
            return 0.0
        u = d - flat
        return rc - math.sqrt(max(0.0, rc * rc - u * u))
    return prof, r


def stamp_moves(hm, moves, tool, dz_step=0.05):
    """Отштамповать рабочие ходы (в координатах детали) отпечатком фрезы на карте."""
    prof, r = tool_profile(tool)
    x0, y0, nx, ny, pitch = hm.x0, hm.y0, hm.nx, hm.ny, hm.pitch
    z = hm.z
    rr = r + 1e-9
    for (xa, ya, za, xb, yb, zb, cutting) in moves:
        if not cutting:
            continue
        if za >= 0.0 and zb >= 0.0:
            continue
        L = math.hypot(xb - xa, yb - ya)
        if L < 1e-9:
            pieces = [(xa, ya, xa, ya, min(za, zb))]
        elif abs(zb - za) < 1e-9:
            pieces = [(xa, ya, xb, yb, za)]
        else:
            n = max(1, int(math.ceil(abs(zb - za) / dz_step)))
            pieces = []
            for k in range(n):
                t0, t1 = k / float(n), (k + 1) / float(n)
                pieces.append((xa + (xb - xa) * t0, ya + (yb - ya) * t0, xa + (xb - xa) * t1, ya + (yb - ya) * t1,
                               min(za + (zb - za) * t0, za + (zb - za) * t1)))
        for (px0, py0, px1, py1, zc) in pieces:
            if zc >= 0.0:
                continue
            i0 = max(0, int(math.floor((min(px0, px1) - r - x0) / pitch)))
            i1 = min(nx - 1, int(math.floor((max(px0, px1) + r - x0) / pitch)))
            j0 = max(0, int(math.floor((min(py0, py1) - r - y0) / pitch)))
            j1 = min(ny - 1, int(math.floor((max(py0, py1) + r - y0) / pitch)))
            vx, vy = px1 - px0, py1 - py0
            L2 = vx * vx + vy * vy
            for j in range(j0, j1 + 1):
                cy = y0 + (j + 0.5) * pitch
                row = j * nx
                for i in range(i0, i1 + 1):
                    cx = x0 + (i + 0.5) * pitch
                    wx, wy = cx - px0, cy - py0
                    if L2 < 1e-18:
                        d = math.hypot(wx, wy)
                    else:
                        t = (wx * vx + wy * vy) / L2
                        if t < 0.0:
                            t = 0.0
                        elif t > 1.0:
                            t = 1.0
                        d = math.hypot(wx - t * vx, wy - t * vy)
                    if d <= rr:
                        zt = zc + prof(d)
                        if zt < z[row + i]:
                            z[row + i] = zt
    return hm


def machined_map(blank, pitch, ops_moves):
    """ops_moves: [(tool, moves)] верхней стороны в системе Z0 = верх детали."""
    x0, y0, nx, ny = grid_for_blank(blank, pitch)
    hm = HeightMap(x0, y0, nx, ny, pitch, 0.0)
    for tool, moves in ops_moves:
        stamp_moves(hm, moves, tool)
    return hm


class Compare(object):
    def __init__(self):
        self.cells = 0
        self.gouge_cells = 0
        self.gouge_max = 0.0
        self.gouge_where = None
        self.gouge_outside_pockets = 0
        self.per_pocket = {}       # fid -> dict(cells, cannot_cells, cannot_max, gap_cells, gap_max)
        self.leftover_outside = 0
        self.leftover_outside_max = 0.0
        self.edge_cells = 0          # остаток в полосе у стенок (контур смещён внутрь намеренно)
        self.edge_max = 0.0
        self.samples = {"gouge": [], "gap": [], "cannot": [], "outside": []}   # (x, y, dz) для отладки


def compare(design_hm, machined_hm, outline, pockets, finish_r, gouge_tol, pitch, edge_band=0.0):
    """Сравнить карты в ячейках внутри контура детали. edge_band > 0: остаток ближе edge_band к
    контуру кармана считается ожидаемой полосой (дизайн из STL с намеренно суженными карманами)."""
    res = Compare()
    nx, ny = design_hm.nx, design_hm.ny
    dz_arr, mz_arr = design_hm.z, machined_hm.z
    for pk in pockets:
        res.per_pocket[pk.fid] = {"cells": 0, "cannot_cells": 0, "cannot_max": 0.0, "gap_cells": 0, "gap_max": 0.0}
        pk.build_grid()
    # Сравнение по вертикали у крутых поверхностей плохо обусловлено: сдвиг ступеньки или
    # стенки на долю ячейки даёт "перепад" в миллиметры. Поэтому зарез считается от
    # минимума замысла в окрестности 3x3 (сдвиг до одной ячейки прощается), остаток - от
    # максимума. Зарезы стенок тоньше шага ловят аналитические проверки зазоров.
    def neigh(i, j, fn):
        best = None
        for dj in (-1, 0, 1):
            jj = j + dj
            if jj < 0 or jj >= ny:
                continue
            for di in (-1, 0, 1):
                ii = i + di
                if ii < 0 or ii >= nx:
                    continue
                v = dz_arr[jj * nx + ii]
                if v <= NO_MATERIAL / 2:
                    continue
                best = v if best is None else fn(best, v)
        return best

    for j in range(ny):
        row = j * nx
        for i in range(nx):
            dz = dz_arr[row + i]
            if dz <= NO_MATERIAL / 2:
                continue
            p = design_hm.cell_center(i, j)
            if not outline.contains(p):
                continue
            res.cells += 1
            mz = mz_arr[row + i]
            diff = mz - dz
            if diff < -gouge_tol:
                lo = neigh(i, j, min)
                if mz >= lo - gouge_tol:
                    continue
                diff = mz - lo
                res.gouge_cells += 1
                if len(res.samples["gouge"]) < 200:
                    res.samples["gouge"].append((p[0], p[1], diff))
                if -diff > res.gouge_max:
                    res.gouge_max = -diff
                    res.gouge_where = p
                if not any(pk.inside(p) for pk in pockets):
                    res.gouge_outside_pockets += 1
            elif diff > gouge_tol:
                hi = neigh(i, j, max)
                if mz <= hi + gouge_tol:
                    continue
                diff = mz - hi
                for pk in pockets:
                    if pk.inside(p):
                        st = res.per_pocket[pk.fid]
                        st["cells"] += 1
                        if edge_band > 0 and pk.dist_fast(p) < edge_band:
                            res.edge_cells += 1
                            res.edge_max = max(res.edge_max, diff)
                            break
                        if pk.reachable(p, finish_r):
                            st["gap_cells"] += 1
                            st["gap_max"] = max(st["gap_max"], diff)
                            if len(res.samples["gap"]) < 200:
                                res.samples["gap"].append((p[0], p[1], diff))
                        else:
                            st["cannot_cells"] += 1
                            st["cannot_max"] = max(st["cannot_max"], diff)
                            if len(res.samples["cannot"]) < 200:
                                res.samples["cannot"].append((p[0], p[1], diff))
                        break
                else:
                    res.leftover_outside += 1
                    res.leftover_outside_max = max(res.leftover_outside_max, diff)
                    if len(res.samples["outside"]) < 200:
                        res.samples["outside"].append((p[0], p[1], diff))
    return res


def verify_run(rep, design, plan, pockets, files, res, stl_path):
    """Секция отчёта КОНТРОЛЬ ПО КАРТЕ ВЫСОТ. Зарез -> вердикт «есть замечания»."""
    from ..scad.stl import load_stl
    import time
    cfg = plan.cfg
    t0 = time.time()
    tris = load_stl(stl_path)
    dmap = design_map(tris, design.blank, cfg.heightmap_pitch)
    ops_moves = []
    for fn, g, tool, title, side in files:
        if fn.startswith("00") or side == "bottom":
            continue
        ops_moves.append((tool, g.moves))
    mmap = machined_map(design.blank, cfg.heightmap_pitch, ops_moves)
    tf = plan.tools.get("finish") or plan.tools.get("rough")
    finish_r = tf["dia"] / 2.0 if tf else 3.0
    edge_band = float(design.derived.get("edge_band", 0.0) or 0.0)
    cmp = compare(dmap, mmap, design.outline, pockets, finish_r, cfg.gouge_tol, cfg.heightmap_pitch, edge_band)
    res.heightmap = mmap
    res.heightmap_cmp = cmp
    a = cfg.heightmap_pitch ** 2 / 100.0      # см2 на ячейку
    rep.section("КОНТРОЛЬ ПО КАРТЕ ВЫСОТ (STL фигуры против траекторий, шаг %.1f мм, допуск %.2f мм; %d треуг., %.1f с)"
                % (cfg.heightmap_pitch, cfg.gouge_tol, len(tris), time.time() - t0))
    rep.line("  ячеек внутри контура ....... %d (%.0f см2)" % (cmp.cells, cmp.cells * a))
    if cmp.gouge_cells:
        rep.line("  !!! ЗАРЕЗ: %d ячеек (%.1f см2) ниже замысла, максимум %.2f мм у X%.1f Y%.1f%s"
                 % (cmp.gouge_cells, cmp.gouge_cells * a, cmp.gouge_max, cmp.gouge_where[0], cmp.gouge_where[1],
                    ", из них вне карманов %d" % cmp.gouge_outside_pockets if cmp.gouge_outside_pockets else ""))
        rep.ok = False
    else:
        rep.line("  зарезов нет ................ обработка нигде не глубже замысла более чем на %.2f мм OK" % cfg.gouge_tol)
    for pk in pockets:
        st = cmp.per_pocket[pk.fid]
        if st["gap_cells"]:
            rep.line("  карман %-3s: !!! ДЫРА В ТРАЕКТОРИИ - %d ячеек (%.1f см2) фреза могла снять и не сняла, до %.2f мм"
                     % (pk.fid, st["gap_cells"], st["gap_cells"] * a, st["gap_max"]))
            rep.ok = False
        if st["cannot_cells"]:
            rep.line("  карман %-3s: фреза не входит - остаток %.1f см2 до %.2f мм (рожки/узкие места, снять вручную)"
                     % (pk.fid, st["cannot_cells"] * a, st["cannot_max"]))
        if not st["gap_cells"] and not st["cannot_cells"]:
            rep.line("  карман %-3s: снято всё, что задумано OK" % pk.fid)
    if cmp.edge_cells:
        rep.line("  полоса у стенок ............ %.1f см2 до %.2f мм не снято: контуры карманов из STL сужены на %.2f мм, "
                 "чтобы не зарезать стенки - снять вручную" % (cmp.edge_cells * a, cmp.edge_max, edge_band))
    if cmp.leftover_outside:
        rep.line("  вне карманов не снято %d ячеек (до %.2f мм): замысел ниже верха, а операции на это нет"
                 % (cmp.leftover_outside, cmp.leftover_outside_max))
        rep.ok = False
    return cmp
