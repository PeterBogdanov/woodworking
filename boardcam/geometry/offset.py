# -*- coding: utf-8 -*-
"""Эквидистанты.

* ``offset_ring`` — наивный эквидистант по биссектрисам нормалей (бывший
  Pocket.offset_poly). В узких местах самопересекается; годится только вместе с
  ``snap_in`` и проверкой каждой точки (см. cam.pocket.Pocket.contour_runs).
* ``snap_in`` — вернуть точку на расстояние R от ближайшей стенки области.
* ``offset_outward`` — путь центра фрезы СНАРУЖИ замкнутого контура на расстоянии
  r: выпуклые вершины обходятся дугой радиуса r, вогнутые — пересечением
  смещённых рёбер. Каждая точка результата затем проверяется вызывающим кодом
  (расстояние до контура >= r − допуск), иначе рез уйдёт в деталь.
"""

import math

from .polyline import arc_points, poly_area, point_in_region, closest_on_rings, closest_on_poly, point_inside, ang


def offset_ring(ring, r, inward=True):
    """Сдвиг кольца на r внутрь (inward=True) или наружу.

    Направление определяется ориентацией кольца, поэтому одинаково работает для
    внешнего контура и для отверстий."""
    sign = 1.0 if poly_area(ring) > 0 else -1.0
    if not inward:
        sign = -sign
    pts = ring
    n = len(pts)
    out = []
    for i in range(n):
        p = pts[i]
        a = pts[(i - 1) % n]
        b = pts[(i + 1) % n]
        ti = (p[0] - a[0], p[1] - a[1])
        Li = math.hypot(*ti)
        to = (b[0] - p[0], b[1] - p[1])
        Lo = math.hypot(*to)
        if Li < 1e-12 or Lo < 1e-12:
            continue
        nx = -(ti[1] / Li + to[1] / Lo)
        ny = ti[0] / Li + to[0] / Lo
        L = math.hypot(nx, ny)
        if L < 1e-12:
            continue
        out.append((p[0] + sign * r * nx / L, p[1] + sign * r * ny / L))
    return out


def snap_in(inside, dist, rings, p, R):
    """Вернуть точку обратно на расстояние R от стенки (наивный эквидистант
    на углах уезжает наружу). None - если в этом месте фреза не помещается.

    inside(p) -> bool, dist(p) -> расстояние до ближайшей стенки области."""
    for _ in range(6):
        ins = inside(p)
        if ins and dist(p) >= R - 0.05:
            return p
        q, d = closest_on_rings(p, rings)
        vx, vy = p[0] - q[0], p[1] - q[1]
        L = math.hypot(vx, vy)
        if L < 1e-9:
            return None
        sgn = 1.0 if ins else -1.0
        p = (q[0] + sgn * vx / L * R, q[1] + sgn * vy / L * R)
    return p if (inside(p) and dist(p) >= R - 0.1) else None


def offset_outward(ring, r, sag, small_turn_deg=2.0):
    """Замкнутый путь центра фрезы радиуса r снаружи контура ring (без первой точки в конце)."""
    pts = list(ring)
    if poly_area(pts) < 0:
        pts.reverse()                       # работаем с контуром против часовой стрелки
    n = len(pts)
    # внешняя нормаль ребра i (p_i -> p_{i+1}) для контура против часовой: (ty, -tx)
    normals = []
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        tx, ty = b[0] - a[0], b[1] - a[1]
        L = math.hypot(tx, ty)
        if L < 1e-12:
            normals.append(None)
        else:
            normals.append((ty / L, -tx / L))
    out = []
    for i in range(n):
        p = pts[i]
        n_in = normals[(i - 1) % n]
        n_out = normals[i]
        if n_in is None or n_out is None:
            continue
        cross = n_in[0] * n_out[1] - n_in[1] * n_out[0]     # >0: поворот влево = выпуклая вершина
        dot = max(-1.0, min(1.0, n_in[0] * n_out[0] + n_in[1] * n_out[1]))
        turn = math.degrees(math.acos(dot))
        if cross > 0 and turn > small_turn_deg:
            arc = arc_points(p, r, ang(n_in), ang(n_out), sag)
            for q in arc:
                if not out or math.hypot(q[0] - out[-1][0], q[1] - out[-1][1]) > 1e-9:
                    out.append(q)
        else:
            denom = 1.0 + dot
            if denom < 1e-6:                # разворот на 180°: игла, обходим как дугу
                arc = arc_points(p, r, ang(n_in), ang(n_out), sag)
                out.extend(arc)
                continue
            q = (p[0] + r * (n_in[0] + n_out[0]) / denom, p[1] + r * (n_in[1] + n_out[1]) / denom)
            if not out or math.hypot(q[0] - out[-1][0], q[1] - out[-1][1]) > 1e-9:
                out.append(q)
    if len(out) > 1 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) < 1e-9:
        out.pop()
    # у зубчатого контура дуги соседних выпуклых вершин пересекаются петлями; точки петель
    # оказываются ближе r к контуру (или внутри него) - возвращаем их на расстояние r
    # наружу от ближайшей точки контура, безнадёжные выбрасываем
    fixed = []
    for q in out:
        cq, dq = closest_on_poly(q, pts)
        ins = point_inside(q, pts)
        if not ins and dq >= r - 1e-6:
            fixed.append(q)
            continue
        vx, vy = q[0] - cq[0], q[1] - cq[1]
        L = math.hypot(vx, vy)
        if L < 1e-9:
            continue
        sgn = -1.0 if ins else 1.0
        q2 = (cq[0] + sgn * vx / L * r, cq[1] + sgn * vy / L * r)
        if not point_inside(q2, pts) and closest_on_poly(q2, pts)[1] >= r - 1e-3:
            fixed.append(q2)
    out = []
    for q in fixed:
        if not out or math.hypot(q[0] - out[-1][0], q[1] - out[-1][1]) > 1e-6:
            out.append(q)
    return remove_loops(out)


def _seg_intersect(a, b, c, d):
    """Точка пересечения отрезков ab и cd или None."""
    r = (b[0] - a[0], b[1] - a[1])
    s_ = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s_[1] - r[1] * s_[0]
    if abs(den) < 1e-12:
        return None
    t = ((c[0] - a[0]) * s_[1] - (c[1] - a[1]) * s_[0]) / den
    u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
    if 1e-9 < t < 1 - 1e-9 and 1e-9 < u < 1 - 1e-9:
        return (a[0] + t * r[0], a[1] + t * r[1])
    return None


def remove_loops(path, window=120, passes=3):
    """Убрать локальные петли замкнутого пути: если отрезок i пересекает отрезок j (j в
    пределах window точек вперёд), точки между ними заменяются точкой пересечения. Петли
    наружного эквидистанта локальны (дуги соседних вершин), поэтому окно небольшое."""
    pts = list(path)
    for _ in range(passes):
        n = len(pts)
        if n < 4:
            return pts
        changed = False
        i = 0
        while i < n:
            a, b = pts[i], pts[(i + 1) % n]
            hit = None
            for k in range(2, min(window, n - 1)):
                j = (i + k) % n
                c, d = pts[j], pts[(j + 1) % n]
                x = _seg_intersect(a, b, c, d)
                if x is not None:
                    hit = (k, x)
                    break
            if hit is None:
                i += 1
                continue
            k, x = hit
            # выбросить pts[i+1 .. i+k] (по кольцу), вставить x
            idx = [(i + m) % n for m in range(1, k + 1)]
            keep = [p for m, p in enumerate(pts) if m not in set(idx)]
            pos = i + 1 if i + 1 <= len(keep) else len(keep)
            # позиция вставки: после точки i в новом списке (индексы < i не сдвинулись, если петля не пересекает 0)
            if all(m > i for m in idx):
                keep.insert(i + 1, x)
            else:
                keep.insert(0, x)
            pts = keep
            n = len(pts)
            changed = True
        if not changed:
            break
    return pts
