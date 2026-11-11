# -*- coding: utf-8 -*-
"""Разбор SVG, который пишет ``openscad -o file.svg`` для плоской геометрии.

OpenSCAD выводит один или несколько ``<path d="M x,y L x,y ... z">`` c абсолютными
командами; ось Y перевёрнута (y записан со знаком минус), чтобы картинка в
просмотрщике не была зеркальной. Здесь Y возвращается на место, а замкнутые
кольца группируются в области «внешний контур + отверстия» по вложенности.
Дуги (A), кривые (C/Q) OpenSCAD не пишет; встретив их, поднимаем ошибку,
а не молча искажаем контур.
"""

import math
import re

from ..geometry.region import Region

_TOK = re.compile(r"([MmLlHhVvZzAaCcQqSsTt])|(-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")
_PATH_D = re.compile(r"<path[^>]*?\sd\s*=\s*\"([^\"]*)\"", re.S)


class SvgError(ValueError):
    pass


def ring_area(ring):
    """Знаковая площадь кольца (>0 = против часовой стрелки)."""
    s = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return 0.5 * s


def point_in_ring(p, ring):
    x, y = p
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


def parse_rings(text, flip_y=True, min_pts=3):
    """Все замкнутые кольца из всех <path> файла, в координатах модели."""
    rings = []
    for d in _PATH_D.findall(text):
        cmd = None
        nums = []
        cur = []
        start = None
        pos = (0.0, 0.0)

        def flush():
            if len(cur) >= min_pts:
                pts = list(cur)
                if pts[0] == pts[-1]:
                    pts.pop()
                if len(pts) >= min_pts:
                    rings.append(pts)
            del cur[:]

        for m in _TOK.finditer(d):
            if m.group(1):
                c = m.group(1)
                if c in "Zz":
                    flush()
                    if start is not None:
                        pos = start
                    cmd = None
                    continue
                if c in "AaCcQqSsTt":
                    raise SvgError("в SVG команда %r: кривые не поддерживаются" % c)
                cmd = c
                nums = []
                continue
            nums.append(float(m.group(2)))
            if cmd in ("M", "L", "m", "l") and len(nums) == 2:
                x, y = nums
                if cmd in "ml":
                    x, y = pos[0] + x, pos[1] + y
                if flip_y:
                    y = -y
                if cmd in "Mm":
                    flush()
                    start = (x, y)
                    cmd = "L" if cmd == "M" else "l"   # последующие пары = L
                pos = (x, y)
                cur.append(pos)
                nums = []
            elif cmd in ("H", "h") and len(nums) == 1:
                x = nums[0] + (pos[0] if cmd == "h" else 0.0)
                pos = (x, pos[1])
                cur.append(pos)
                nums = []
            elif cmd in ("V", "v") and len(nums) == 1:
                y = nums[0] + (pos[1] if cmd == "v" else 0.0)
                if flip_y and cmd == "V":
                    y = -y
                pos = (pos[0], y)
                cur.append(pos)
                nums = []
        flush()
    return [_dedupe(r) for r in rings if len(_dedupe(r)) >= min_pts]


def _dedupe(ring, eps=1e-9):
    out = []
    for p in ring:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > eps:
            out.append(p)
    if len(out) > 1 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) <= eps:
        out.pop()
    return out


def group_regions(rings):
    """Кольца -> области по чётности вложенности: глубина 0/2/4 = внешний контур,
    1/3/5 = отверстие ближайшего охватывающего внешнего кольца."""
    n = len(rings)
    depth = [0] * n
    parent = [None] * n
    areas = [abs(ring_area(r)) for r in rings]
    for i in range(n):
        containers = [j for j in range(n) if j != i and areas[j] > areas[i]
                      and point_in_ring(rings[i][0], rings[j])]
        depth[i] = len(containers)
        if containers:
            parent[i] = min(containers, key=lambda j: areas[j])
    regions = {}
    for i in range(n):
        if depth[i] % 2 == 0:
            regions[i] = Region(rings[i])
    for i in range(n):
        if depth[i] % 2 == 1:
            regions[parent[i]].holes.append(rings[i] if ring_area(rings[i]) < 0 else list(reversed(rings[i])))
    return sorted(regions.values(), key=lambda r: -r.area)


def load_regions(path):
    with open(path, encoding="utf-8") as f:
        return group_regions(parse_rings(f.read()))
