# -*- coding: utf-8 -*-
"""Табы по длине пути: центры на равных расстояниях вдоль замкнутого контура."""

import math


def arc_positions(path):
    """Накопленная длина до каждой точки замкнутого пути и полная длина."""
    s = [0.0]
    for i in range(1, len(path)):
        s.append(s[-1] + math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]))
    L = s[-1] + math.hypot(path[0][0] - path[-1][0], path[0][1] - path[-1][1])
    return s, L


def tab_distances(path, n_tabs):
    """Для каждой точки пути - расстояние (по дуге) до ближайшего центра таба.
    Центры: L*(k+0.5)/n от начала пути, как 360*i/TABS + 180/TABS у окружности."""
    s, L = arc_positions(path)
    if n_tabs <= 0 or L <= 0:
        return [float('inf')] * len(path), L
    centers = [L * (k + 0.5) / n_tabs for k in range(n_tabs)]
    out = []
    for si in s:
        d = min(abs(((si - c + L / 2.0) % L) - L / 2.0) for c in centers)
        out.append(d)
    return out, L
