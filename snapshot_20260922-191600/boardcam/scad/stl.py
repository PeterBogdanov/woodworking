# -*- coding: utf-8 -*-
"""Чтение STL (двоичного и текстового) в список треугольников."""

import struct


def load_stl(path):
    with open(path, "rb") as f:
        data = f.read()
    if len(data) >= 84:
        n = struct.unpack_from("<I", data, 80)[0]
        if 84 + 50 * n == len(data) and not data[:5].lower().startswith(b"solid"):
            return _binary(data, n)
        if 84 + 50 * n == len(data):
            return _binary(data, n)          # "solid" в заголовке двоичного файла бывает
    return _ascii(data.decode("ascii", "replace"))


def _binary(data, n):
    tris = []
    off = 84
    for _ in range(n):
        v = struct.unpack_from("<12f", data, off)
        tris.append(((v[3], v[4], v[5]), (v[6], v[7], v[8]), (v[9], v[10], v[11])))
        off += 50
    return tris


def _ascii(text):
    tris = []
    cur = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("vertex"):
            parts = s.split()
            cur.append((float(parts[1]), float(parts[2]), float(parts[3])))
            if len(cur) == 3:
                tris.append(tuple(cur))
                cur = []
    return tris


def bounds(tris):
    xs = [p[0] for t in tris for p in t]
    ys = [p[1] for t in tris for p in t]
    zs = [p[2] for t in tris for p in t]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))
