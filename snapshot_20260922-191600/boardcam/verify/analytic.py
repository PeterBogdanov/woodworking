# -*- coding: utf-8 -*-
"""Аналитические проверки траекторий: зазоры до стенок, покрытие дна, контур снаружи детали.

Перенос из board_v3 (main(): КОНТРОЛЬ ЗАЗОРОВ, coverage_check). Пороги
(-0.05 / -0.25 / +0.25, 2*wall_allow) - контракт, не трогать.
"""

import math

from ..geometry.polyline import pt, dist_to_poly, dist_to_rings, point_inside, min_corner_angle
from ..geometry.distance import build_seg_grid, seg_grid_dist


def clearance_rough(pk, raster):
    """Минимальное расстояние центра фрезы до контура по концам и серединам проходов растра."""
    pts = raster.samples()
    if not pts:
        return 0.0
    return min(dist_to_rings(p, pk.rings) for p in pts)


def clearance_finish(pk, runs):
    allp = [p for rn in runs for p in rn]
    return (min(dist_to_rings(p, pk.rings) for p in allp) if allp else 0.0), len(allp)


def coverage_check(pk, segs, r_tool, min_bound_dist, step, cell=12.0):
    """Все точки кармана, удалённые от контура не менее min_bound_dist,
    должны попадать в диск радиуса r_tool от траектории.
    -> (проверено, не снято, из них доступных фрезе, худший остаток)."""
    grid = build_seg_grid(segs, cell)
    xs = [p[0] for p in pk.outer]
    ys = [p[1] for p in pk.outer]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    tested = missed = hard = 0
    worst = 0.0
    nx = int((xmax - xmin) / step)
    ny = int((ymax - ymin) / step)
    for i in range(nx + 1):
        for j in range(ny + 1):
            p = (xmin + i * step, ymin + j * step)
            if not pk.inside(p):
                continue
            if dist_to_rings(p, pk.rings) < min_bound_dist:
                continue
            tested += 1
            best = seg_grid_dist(grid, p, cell)
            if best > r_tool + 0.25:
                missed += 1
                if pk.reachable(p, r_tool):      # фреза сюда физически влезает - это дыра
                    hard += 1
                    worst = max(worst, best - r_tool)
    return tested, missed, hard, worst


def profile_clearance(path, outline_ring, r):
    """Контур снаружи детали: каждая точка пути и середина каждой хорды должны быть
    вне контура и не ближе r к нему. -> (минимальное расстояние, число точек внутри детали)."""
    worst = 1e9
    inside = 0
    n = len(path)
    for i in range(n):
        a, b = path[i], path[(i + 1) % n]
        for p in (a, (0.5 * (a[0] + b[0]), 0.5 * (a[1] + b[1]))):
            d = dist_to_poly(p, outline_ring)
            worst = min(worst, d)
            if point_inside(p, outline_ring):
                inside += 1
    return worst, inside


def sharpest_corner(pk):
    return min_corner_angle(pk.outer)
