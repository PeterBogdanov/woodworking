# -*- coding: utf-8 -*-
"""Плоская область: внешнее кольцо (против часовой стрелки) и отверстия (по часовой)."""

from .polyline import poly_area, point_inside, bbox as _bbox


class Region(object):
    __slots__ = ("outer", "holes")

    def __init__(self, outer, holes=None):
        self.outer = list(outer) if poly_area(outer) > 0 else list(reversed(outer))
        self.holes = [list(h) if poly_area(h) < 0 else list(reversed(h)) for h in (holes or [])]

    @property
    def area(self):
        return abs(poly_area(self.outer)) - sum(abs(poly_area(h)) for h in self.holes)

    def rings(self):
        return [self.outer] + list(self.holes)

    def contains(self, p):
        if not point_inside(p, self.outer):
            return False
        return not any(point_inside(p, h) for h in self.holes)

    def bbox(self):
        return _bbox(self.outer)

    def mirrored_y(self):
        """Зеркало y -> -y (переворот заготовки вокруг оси X)."""
        return Region([(x, -y) for (x, y) in self.outer],
                      [[(x, -y) for (x, y) in h] for h in self.holes])

    def to_dict(self):
        return {"outer": [list(p) for p in self.outer], "holes": [[list(p) for p in h] for h in self.holes]}

    @classmethod
    def from_dict(cls, d):
        return cls([tuple(p) for p in d["outer"]], [[tuple(p) for p in h] for h in d.get("holes", [])])
