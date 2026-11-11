# -*- coding: utf-8 -*-
"""Пространственные сетки для быстрого расстояния до отрезков.

``RingGrid`` — сетка по сегментам контура (бывшие Pocket.build_grid/dist_fast):
ищет ближайший сегмент кольцами вокруг клетки, останавливается, когда лучшее
расстояние уже не превзойти. ``build_seg_grid`` — сетка по сегментам траектории
для контроля покрытия (окрестность 3x3). Формулы перенесены из board_v3 как есть.
"""

import math

from .polyline import dist_point_seg


class RingGrid(object):
    def __init__(self, rings, cell=12.0):
        g = {}
        for poly in rings:
            n = len(poly)
            for i in range(n):
                a, b = poly[i], poly[(i + 1) % n]
                x0 = int(math.floor(min(a[0], b[0]) / cell))
                x1 = int(math.floor(max(a[0], b[0]) / cell))
                y0 = int(math.floor(min(a[1], b[1]) / cell))
                y1 = int(math.floor(max(a[1], b[1]) / cell))
                for cx in range(x0, x1 + 1):
                    for cy in range(y0, y1 + 1):
                        g.setdefault((cx, cy), []).append((a, b))
        self._grid, self._cell = g, cell

    def dist(self, p):
        cell = self._cell
        best = 1e9
        bx = int(math.floor(p[0] / cell))
        by = int(math.floor(p[1] / cell))
        for ring in range(0, 8):
            for cx in range(bx - ring, bx + ring + 1):
                for cy in range(by - ring, by + ring + 1):
                    if ring and max(abs(cx - bx), abs(cy - by)) != ring:
                        continue
                    for (a, b) in self._grid.get((cx, cy), ()):
                        d = dist_point_seg(p, a, b)
                        if d < best:
                            best = d
            if best <= ring * cell:
                break
        return best


def build_seg_grid(segs, cell=12.0):
    grid = {}
    for (a, b) in segs:
        cx0 = int(math.floor(min(a[0], b[0]) / cell))
        cx1 = int(math.floor(max(a[0], b[0]) / cell))
        cy0 = int(math.floor(min(a[1], b[1]) / cell))
        cy1 = int(math.floor(max(a[1], b[1]) / cell))
        for cx in range(cx0, cx1 + 1):
            for cy in range(cy0, cy1 + 1):
                grid.setdefault((cx, cy), []).append((a, b))
    return grid


def seg_grid_dist(grid, p, cell=12.0):
    """Ближайший сегмент траектории в окрестности 3x3 клеток (как в coverage_check)."""
    best = 1e9
    cx, cy = int(math.floor(p[0] / cell)), int(math.floor(p[1] / cell))
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for (a, b) in grid.get((cx + dx, cy + dy), ()):
                d = dist_point_seg(p, a, b)
                if d < best:
                    best = d
    return best
