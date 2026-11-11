# -*- coding: utf-8 -*-
"""Плоская геометрия на полилиниях: дуги, площади, расстояния, принадлежность.

Перенесено из board_v3/generate_board.py (разделы 3 «МАТЕМАТИКА» и проверки)
без изменения формул. Всё в миллиметрах, углы в радианах.
"""

import math

TWO_PI = 2.0 * math.pi


def ang(v):
    return math.atan2(v[1], v[0])


def pt(rho, t):
    return (rho * math.cos(t), rho * math.sin(t))


def chord_for(radius, sag):
    return max(2.0 * math.sqrt(max(2.0 * radius * sag, 1e-12)), 0.0025)


def circle_points(c, r, sag):
    """Полная окружность (замкнутая, без дублирования первой точки)."""
    n = max(8, int(math.ceil(TWO_PI * r / chord_for(r, sag))))
    return [(c[0] + r * math.cos(TWO_PI * i / n),
             c[1] + r * math.sin(TWO_PI * i / n)) for i in range(n)]


def arc_points(c, r, a0, a1, sag):
    d = (a1 - a0 + math.pi) % TWO_PI - math.pi
    if abs(d) < 1e-12:
        return [(c[0] + r * math.cos(a0), c[1] + r * math.sin(a0))]
    n = max(2, int(math.ceil(abs(d) * r / chord_for(r, sag))))
    return [(c[0] + r * math.cos(a0 + d * i / n),
             c[1] + r * math.sin(a0 + d * i / n)) for i in range(n + 1)]


def poly_area(pts):
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return 0.5 * s


def dist_point_seg(p, a, b):
    vx, vy = b[0] - a[0], b[1] - a[1]
    wx, wy = p[0] - a[0], p[1] - a[1]
    L2 = vx * vx + vy * vy
    if L2 < 1e-18:
        return math.hypot(wx, wy)
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / L2))
    return math.hypot(wx - t * vx, wy - t * vy)


def dist_to_poly(p, poly):
    return min(dist_point_seg(p, poly[i], poly[(i + 1) % len(poly)])
               for i in range(len(poly)))


def dist_to_rings(p, rings):
    return min(dist_to_poly(p, r) for r in rings)


def point_inside(p, poly):
    """Чёт-нечет по одному кольцу."""
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xin:
                inside = not inside
    return inside


def point_in_region(p, outer, holes):
    if not point_inside(p, outer):
        return False
    for h in holes:
        if point_inside(p, h):
            return False
    return True


def closest_on_poly(p, poly):
    """Ближайшая точка на контуре и расстояние до неё."""
    best, bq = 1e18, None
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        vx, vy = b[0] - a[0], b[1] - a[1]
        L2 = vx * vx + vy * vy
        t = 0.0 if L2 < 1e-18 else max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L2))
        q = (a[0] + t * vx, a[1] + t * vy)
        d = math.hypot(p[0] - q[0], p[1] - q[1])
        if d < best:
            best, bq = d, q
    return bq, best


def closest_on_rings(p, rings):
    best, bq = 1e18, None
    for r in rings:
        q, d = closest_on_poly(p, r)
        if d < best:
            best, bq = d, q
    return bq, best


def add_pts(pts, new):
    """Дописать точки без дублирования соседних."""
    for p in new:
        if not pts or math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) > 1e-9:
            pts.append(p)


def path_length(pts, closed=False):
    L = 0.0
    for i in range(1, len(pts)):
        L += math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
    if closed and len(pts) > 1:
        L += math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1])
    return L


def bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def centroid(ring):
    """Центроид многоугольника (по площади)."""
    A = poly_area(ring)
    if abs(A) < 1e-12:
        return (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))
    cx = cy = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        w = x1 * y2 - x2 * y1
        cx += (x1 + x2) * w
        cy += (y1 + y2) * w
    return (cx / (6.0 * A), cy / (6.0 * A))


def min_corner_angle(pts):
    """Самый острый угол контура, градусы. 180 = гладко, 0 = игла."""
    n, best = len(pts), 180.0
    for i in range(n):
        a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
        v1 = (a[0] - b[0], a[1] - b[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        L = math.hypot(*v1) * math.hypot(*v2)
        if L < 1e-12:
            continue
        best = min(best, math.degrees(math.acos(
            max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / L)))))
    return best


def simplify_ring(ring, tol, merge_eps=0.05):
    """Упростить замкнутый контур (Дуглас-Пекер) с допуском tol: убирает лишние точки на
    дугах. Контур меняется не более чем на tol. Перед этим сливаются микрорёбра короче
    merge_eps: две вершины в 16 мкм друг от друга (артефакт Clipper при печати координат
    с шестью значащими цифрами) дают ложный угол 90°, а по хорде их не отсеять."""
    if len(ring) < 8 or tol <= 0:
        return list(ring)
    merged = []
    for p in ring:
        if merged and math.hypot(p[0] - merged[-1][0], p[1] - merged[-1][1]) < merge_eps:
            continue
        merged.append(p)
    if len(merged) > 1 and math.hypot(merged[0][0] - merged[-1][0], merged[0][1] - merged[-1][1]) < merge_eps:
        merged.pop()
    ring = merged
    n = len(ring)
    if n < 8:
        return list(ring)
    c = centroid(ring)
    i0 = max(range(n), key=lambda i: math.hypot(ring[i][0] - c[0], ring[i][1] - c[1]))
    pts = ring[i0:] + ring[:i0]
    i1 = max(range(n), key=lambda i: math.hypot(pts[i][0] - pts[0][0], pts[i][1] - pts[0][1]))
    a = _dp(pts[:i1 + 1], tol)
    b = _dp(pts[i1:] + [pts[0]], tol)
    out = a + b[1:-1]
    return out if len(out) >= 3 else list(ring)


def _dp(pts, tol):
    if len(pts) < 3:
        return list(pts)
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = pts[i], pts[j]
        worst, k = -1.0, -1
        for m in range(i + 1, j):
            d = dist_point_seg(pts[m], a, b)
            if d > worst:
                worst, k = d, m
        if worst > tol:
            keep[k] = True
            stack.append((i, k))
            stack.append((k, j))
    return [p for p, kf in zip(pts, keep) if kf]
