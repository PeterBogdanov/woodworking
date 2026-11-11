# -*- coding: utf-8 -*-
"""Карман для траекторий: область с отверстиями, полярный растр, обход стенок.

Перенос class Pocket из board_v3/generate_board.py. Изменения:
* контур приходит готовым (из OpenSCAD) - конструктор из области, без спиралей
  и поиска скруглений;
* область может иметь отверстия (островки): inside() учитывает их, обход стенок
  идёт по каждому кольцу, у отверстий эквидистант смещается от отверстия внутрь
  кармана; r_min берётся по всем кольцам, иначе кольцевой карман растрировался бы
  одной дугой;
* raster() запоминает результат по (r_tool, allow, stepover, F_extra): раньше он
  считался трижды за прогон.
Формулы растра, связок и обхода - без изменений.
"""

import math

from ..geometry.polyline import (TWO_PI, poly_area, point_in_region, ang, centroid)
from ..geometry.distance import RingGrid
from ..geometry.offset import offset_ring, snap_in


class Raster(object):
    """Результат разбиения дна на проходы.

    kind='polar': rows = [(rho, [(t0, t1, tag0, tag1), ...]), ...] - дуги вокруг центра детали;
    kind='linear': rows = [(y, [(x0, x1), ...]), ...] - отрезки вдоль X. Rt - отступ центра
    фрезы от контура, rmin - внутренняя граница сканирования (только polar)."""

    def __init__(self, kind, rows, Rt, rmin=0.0):
        self.kind, self.rows, self.Rt, self.rmin = kind, rows, Rt, rmin

    def __bool__(self):
        return bool(self.rows)

    __nonzero__ = __bool__

    def samples(self):
        """Точки для контроля зазора: концы и середины каждого прохода."""
        out = []
        if self.kind == 'polar':
            for rho, ivs in self.rows:
                for (t0, t1, _a, _b) in ivs:
                    for t in (t0, 0.5 * (t0 + t1), t1):
                        out.append((rho * math.cos(t), rho * math.sin(t)))
        else:
            for y, segs in self.rows:
                for (x0, x1) in segs:
                    out.extend([(x0, y), (0.5 * (x0 + x1), y), (x1, y)])
        return out

    def paths(self, sag):
        """Полилинии проходов (для превью)."""
        from ..geometry.polyline import arc_points
        out = []
        if self.kind == 'polar':
            for rho, ivs in self.rows:
                for (t0, t1, _a, _b) in ivs:
                    out.append(arc_points((0, 0), rho, t0, t1, sag))
        else:
            for y, segs in self.rows:
                for (x0, x1) in segs:
                    out.append([(x0, y), (x1, y)])
        return out


class Pocket(object):
    def __init__(self, region, fid="", mid=None):
        self.region = region
        self.outer = region.outer
        self.holes = list(region.holes)
        self.rings = [self.outer] + self.holes
        self.poly = self.outer                      # совместимость с отчётами
        self.fid = str(fid)
        self.area = region.area
        self.sign = 1.0 if poly_area(self.outer) > 0 else -1.0
        self.r_min = min(math.hypot(x, y) for ring in self.rings for (x, y) in ring)
        self.R = max(math.hypot(x, y) for (x, y) in self.outer)
        self.R_p = self.R
        self.mid = ang(centroid(self.outer)) if mid is None else mid
        self._grid, self._cell = None, 12.0
        self._raster_cache = {}
        self.strategy = 'polar'      # 'polar' - дуги вокруг центра детали (круглые доски); 'linear' - строки вдоль X

    # -- геометрия -----------------------------------------------------------
    def inside(self, p):
        return point_in_region(p, self.outer, self.holes)

    def build_grid(self, cell=12.0):
        if self._grid is None or self._cell != cell:
            self._grid = RingGrid(self.rings, cell)
            self._cell = cell
        return self._grid

    def dist_fast(self, p):
        if self._grid is None:
            self.build_grid()
        return self._grid.dist(p)

    # -- полярный растр --------------------------------------------------------
    def raster_intervals(self, rho, Rt):
        lo, hi = self.mid - math.pi, self.mid + math.pi
        n = max(24, int((hi - lo) * rho / 2.0))
        ok = []
        for i in range(n + 1):
            t = lo + (hi - lo) * i / n
            p = (rho * math.cos(t), rho * math.sin(t))
            ok.append(self.inside(p) and self.dist_fast(p) >= Rt - 0.025)
        if not any(ok):
            return []

        def refine(t_yes, t_no):
            for _ in range(18):
                tm = 0.5 * (t_yes + t_no)
                p = (rho * math.cos(tm), rho * math.sin(tm))
                if self.inside(p) and self.dist_fast(p) >= Rt - 0.025:
                    t_yes = tm
                else:
                    t_no = tm
            return t_yes

        ivs = []
        i = 0
        while i <= n:
            if not ok[i]:
                i += 1
                continue
            j = i
            while j + 1 <= n and ok[j + 1]:
                j += 1
            a0 = lo + (hi - lo) * i / n
            a1 = lo + (hi - lo) * j / n
            t0 = a0 if i == 0 else refine(a0, lo + (hi - lo) * (i - 1) / n)
            t1 = a1 if j == n else refine(a1, lo + (hi - lo) * (j + 1) / n)
            if (t1 - t0) * rho > 0.5:
                if t1 - t0 > TWO_PI - 1e-9:     # полный круг: 360-градусная дуга невыразима
                    tm = 0.5 * (t0 + t1)        # в arc_points, режем на два полукольца
                    ivs.append((t0, tm, 'bnd', 'bnd'))
                    ivs.append((tm, t1, 'bnd', 'bnd'))
                else:
                    ivs.append((t0, t1, 'bnd', 'bnd'))
            i = j + 1
        return ivs

    def raster(self, r_tool, allow, stepover, F_extra=0.0):
        key = (round(r_tool, 6), round(allow, 6), round(stepover, 6), round(F_extra, 6))
        if key in self._raster_cache:
            return self._raster_cache[key]
        Rt = r_tool + allow + F_extra
        self.build_grid()
        rmax = self.R - Rt
        # Если карман накрывает центр, rmin = 0, иначе self.r_min - Rt
        if self.inside((0, 0)):
            rmin = 0.0
        else:
            rmin = max(2.5, self.r_min - Rt)
        out = []
        rho = rmax
        empty = 0
        while rho >= rmin and empty < 4:
            ivs = self.raster_intervals(rho, Rt)
            if ivs:
                out.append((rho, ivs))
                empty = 0
            else:
                empty += 1
            rho -= stepover
        res = (out, Rt, rmin)
        self._raster_cache[key] = res
        return res

    def _good(self, p, Rt):
        return self.inside(p) and self.dist_fast(p) >= Rt - 0.025

    def linear_intervals(self, y, Rt, xmin, xmax):
        """Годные отрезки строки y: те же критерии и уточнение концов, что у raster_intervals."""
        n = max(24, int((xmax - xmin) / 2.0))
        ok = [self._good((xmin + (xmax - xmin) * i / n, y), Rt) for i in range(n + 1)]
        if not any(ok):
            return []

        def refine(x_yes, x_no):
            for _ in range(18):
                xm = 0.5 * (x_yes + x_no)
                if self._good((xm, y), Rt):
                    x_yes = xm
                else:
                    x_no = xm
            return x_yes

        segs = []
        i = 0
        while i <= n:
            if not ok[i]:
                i += 1
                continue
            j = i
            while j + 1 <= n and ok[j + 1]:
                j += 1
            a0 = xmin + (xmax - xmin) * i / n
            a1 = xmin + (xmax - xmin) * j / n
            x0 = a0 if i == 0 else refine(a0, xmin + (xmax - xmin) * (i - 1) / n)
            x1 = a1 if j == n else refine(a1, xmin + (xmax - xmin) * (j + 1) / n)
            if x1 - x0 > 0.5:
                segs.append((x0, x1))
            i = j + 1
        return segs

    def raster_linear(self, r_tool, allow, stepover, F_extra=0.0):
        """Строки вдоль X сверху вниз с шагом stepover; крайние строки на Rt от контура.
        Для карманов с прямыми стенками: полярные дуги касаются таких стенок и оставляют
        между соседними дугами непокрытые полосы (карта высот показывала до 2 мм остатка)."""
        key = ('lin', round(r_tool, 6), round(allow, 6), round(stepover, 6), round(F_extra, 6))
        if key in self._raster_cache:
            return self._raster_cache[key]
        Rt = r_tool + allow + F_extra
        self.build_grid()
        xs = [p[0] for p in self.outer]
        ys = [p[1] for p in self.outer]
        xmin, xmax = min(xs) - 1.0, max(xs) + 1.0
        ymax, ymin = max(ys) - Rt, min(ys) + Rt
        rows = []
        y = ymax
        while y >= ymin - 1e-9:
            segs = self.linear_intervals(y, Rt, xmin, xmax)
            if segs:
                rows.append((y, segs))
            y -= stepover
        if rows and ymax - ymin > 1e-6 and rows[-1][0] - ymin > 0.5:     # добить нижний край
            segs = self.linear_intervals(ymin, Rt, xmin, xmax)
            if segs:
                rows.append((ymin, segs))
        res = (rows, Rt)
        self._raster_cache[key] = res
        return res

    def plan_raster(self, r_tool, allow, stepover, F_extra=0.0):
        """Разбиение дна по выбранной стратегии -> Raster."""
        if self.strategy == 'linear':
            rows, Rt = self.raster_linear(r_tool, allow, stepover, F_extra)
            return Raster('linear', rows, Rt)
        arcs, Rt, rmin = self.raster(r_tool, allow, stepover, F_extra)
        return Raster('polar', arcs, Rt, rmin)

    # -- обход стенок ------------------------------------------------------------
    def contour_runs(self, R, tol=0.1):
        """Обход стенок на расстоянии R центром фрезы.

        Наивный эквидистант в узких местах самопересекается и вылезает ЗА карман -
        по нему фреза 3/4" срезала бы бортик и стенки. Поэтому каждую точку проверяем
        (внутри кармана и до стенки не ближе R) и режем только непрерывные годные
        куски. Возвращает (список проходов, сколько точек выброшено)."""
        self.build_grid()
        runs_all, nbad = [], 0
        for k, ring in enumerate(self.rings):
            raw = offset_ring(ring, R, inward=(k == 0))
            pts = [snap_in(self.inside, self.dist_fast, self.rings, p, R) or p for p in raw]
            good = [self.inside(p) and self.dist_fast(p) >= R - tol for p in pts]
            # хорда между соседними точками тоже не должна резать стенку - проверяем её целиком
            # с шагом 1.2 мм (у зубчатого контура из STL соседние точки эквидистанта далеко,
            # и одна середина хорды ничего не гарантирует)
            n = len(pts)
            for i in range(n):
                if not (good[i] and good[(i + 1) % n]):
                    continue
                a, b = pts[i], pts[(i + 1) % n]
                L = math.hypot(b[0] - a[0], b[1] - a[1])
                ns = max(2, int(L / 1.2))
                for k in range(1, ns):
                    m = (a[0] + (b[0] - a[0]) * k / ns, a[1] + (b[1] - a[1]) * k / ns)
                    if not self.inside(m) or self.dist_fast(m) < R - tol:
                        good[(i + 1) % n] = False
                        break
            if n == 0:
                continue
            if all(good):
                runs_all.append(pts + [pts[0]])
                continue
            if not any(good):
                nbad += n
                continue
            k0 = good.index(False)             # старт с плохой точки -> ни один кусок не рвётся на шве
            runs, cur = [], []
            for i in range(n):
                kk = (k0 + i) % n
                if good[kk]:
                    cur.append(pts[kk])
                elif cur:
                    runs.append(cur)
                    cur = []
            if cur:
                runs.append(cur)
            runs_all.extend(r for r in runs if len(r) >= 4)
            nbad += good.count(False)
        return runs_all, nbad

    def reachable(self, p, r_tool):
        """Существует ли допустимое положение центра фрезы, накрывающее точку p."""
        for k in range(1, 4):
            rad = r_tool * k / 3.0
            for i in range(16):
                a = TWO_PI * i / 16.0
                c = (p[0] + rad * math.cos(a), p[1] + rad * math.sin(a))
                if self.inside(c) and self.dist_fast(c) >= r_tool:
                    return True
        return self.inside(p) and self.dist_fast(p) >= r_tool
