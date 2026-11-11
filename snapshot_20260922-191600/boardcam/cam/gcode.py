# -*- coding: utf-8 -*-
"""Буфер G-code. Геометрия подаётся в координатах детали (центр доски = 0,0);
смещение в координаты станка прибавляется в ОДНОМ месте - в go()."""

import math


def fnum(v):
    s = "%.3f" % v
    s = s.rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


class GCode(object):
    def __init__(self, offset=(0.0, 0.0)):
        self.L = []
        self.xy = (0.0, 0.0)
        self.z = 0.0
        self.cut_len = 0.0
        self.path = []
        self.segs = []          # рабочие отрезки XY для контроля покрытия
        self.moves = []         # все перемещения (x0,y0,z0,x1,y1,z1,cutting) для карты высот
        self.ox, self.oy = offset

    def c(self, s=''):
        self.L.append(s)

    def go(self, x=None, y=None, z=None, f=None, move='G1'):
        nx = self.xy[0] if x is None else x
        ny = self.xy[1] if y is None else y
        nz = self.z if z is None else z
        if f is not None:
            self.cut_len += math.hypot(nx - self.xy[0], ny - self.xy[1])
            self.path.append((nx, ny))
            self.segs.append((self.xy, (nx, ny)))
        self.moves.append((self.xy[0], self.xy[1], self.z, nx, ny, nz, f is not None))
        line = move
        if x is not None:
            line += " X" + fnum(x + self.ox)
        if y is not None:
            line += " Y" + fnum(y + self.oy)
        if z is not None:
            line += " Z" + fnum(z)
        if f is not None:
            line += " F" + fnum(f)
        self.L.append(line)
        self.xy = (nx, ny)
        self.z = nz

    def text(self):
        return "\n".join(self.L) + "\n"
