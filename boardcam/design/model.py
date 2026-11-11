# -*- coding: utf-8 -*-
"""Модель дизайна: что фигура сообщила о себе (echo) плюс плоская геометрия (SVG).

Координаты - в системе детали: центр заготовки = (0,0), Z0 = верх готового изделия.
"""

import math

from ..geometry.polyline import circle_points, bbox as _bbox, point_inside, simplify_ring
from ..geometry.region import Region

# Контуры из SVG упрощаются с этим допуском (мм): OpenSCAD печатает координаты с шестью
# значащими цифрами и режет дуги на короткие сегменты; микровершины дают ложные острые
# углы и втрое раздувают файлы G-code. 5 мкм много меньше любого допуска траекторий.
SIMPLIFY_TOL = 0.005


class DesignError(ValueError):
    pass


class Message(object):
    __slots__ = ("level", "code", "text", "feature")

    def __init__(self, level, code, text, feature=None):
        self.level, self.code, self.text, self.feature = level, code, text, feature

    def to_dict(self):
        return {"level": self.level, "code": self.code, "text": self.text, "feature": self.feature}

    @classmethod
    def from_dict(cls, d):
        return cls(d["level"], d["code"], d["text"], d.get("feature"))

    def __repr__(self):
        return "Message(%s %s: %s)" % (self.level, self.code, self.text)


class Blank(object):
    def __init__(self, size_x, size_y, thick, origin="corner"):
        self.size_x, self.size_y, self.thick, self.origin = float(size_x), float(size_y), float(thick), origin

    def to_dict(self):
        return {"size_x": self.size_x, "size_y": self.size_y, "thick": self.thick, "origin": self.origin}

    @classmethod
    def from_dict(cls, d):
        return cls(d["size_x"], d["size_y"], d["thick"], d.get("origin", "corner"))


class Outline(object):
    """Наружный контур: окружность (kind='circle', dia) или многоугольник (kind='polygon', region)."""

    def __init__(self, kind, dia=None, region=None):
        self.kind = kind
        self.dia = float(dia) if dia is not None else None
        self.region = region
        if kind == "circle" and not self.dia:
            raise DesignError("outline: окружность без диаметра")
        if kind == "polygon" and region is None:
            raise DesignError("outline: многоугольник без геометрии")

    def ring(self, sag):
        if self.kind == "circle":
            return circle_points((0.0, 0.0), self.dia / 2.0, sag)
        return list(self.region.outer)

    def bbox(self):
        if self.kind == "circle":
            r = self.dia / 2.0
            return (-r, -r, r, r)
        return self.region.bbox()

    def contains(self, p):
        if self.kind == "circle":
            return math.hypot(p[0], p[1]) <= self.dia / 2.0
        return self.region.contains(p)

    def mirrored_y(self):
        if self.kind == "circle":
            return self
        return Outline("polygon", region=self.region.mirrored_y())

    def to_dict(self):
        return {"kind": self.kind, "dia": self.dia,
                "region": self.region.to_dict() if self.region is not None else None}

    @classmethod
    def from_dict(cls, d):
        reg = Region.from_dict(d["region"]) if d.get("region") else None
        return cls(d["kind"], d.get("dia"), reg)


class Pocket(object):
    """Карман: одна или несколько областей (после скруглений область может распасться)."""

    def __init__(self, fid, regions, depth, floor_fillet_r, ref=None):
        self.id = str(fid)
        self.regions = list(regions)
        self.depth = float(depth)
        self.floor_fillet_r = float(floor_fillet_r or 0.0)
        self.ref = ref

    @property
    def area(self):
        return sum(r.area for r in self.regions)

    def to_dict(self):
        return {"id": self.id, "regions": [r.to_dict() for r in self.regions], "depth": self.depth,
                "floor_fillet_r": self.floor_fillet_r, "ref": self.ref}

    @classmethod
    def from_dict(cls, d):
        return cls(d["id"], [Region.from_dict(r) for r in d["regions"]], d["depth"],
                   d.get("floor_fillet_r", 0.0), d.get("ref"))


class Hole(object):
    def __init__(self, fid, center, dia, through, depth=None):
        self.id, self.center, self.dia, self.through = str(fid), (float(center[0]), float(center[1])), float(dia), bool(through)
        self.depth = None if depth is None else float(depth)

    def to_dict(self):
        return {"id": self.id, "center": list(self.center), "dia": self.dia, "through": self.through, "depth": self.depth}

    @classmethod
    def from_dict(cls, d):
        return cls(d["id"], d["center"], d["dia"], d["through"], d.get("depth"))


class Groove(object):
    """Жёлоб: путь центра (окружность dia или многоугольник), глубина, радиус сферы фрезы."""

    def __init__(self, fid, kind, dia=None, path=None, depth=0.0, tool_corner_r=0.0):
        self.id, self.kind, self.dia = str(fid), kind, (float(dia) if dia is not None else None)
        self.path = list(path) if path else None
        self.depth, self.tool_corner_r = float(depth), float(tool_corner_r)

    def centerline(self, sag):
        if self.kind == "circle":
            return circle_points((0.0, 0.0), self.dia / 2.0, sag)
        return list(self.path)

    def to_dict(self):
        return {"id": self.id, "kind": self.kind, "dia": self.dia,
                "path": [list(p) for p in self.path] if self.path else None,
                "depth": self.depth, "tool_corner_r": self.tool_corner_r}

    @classmethod
    def from_dict(cls, d):
        return cls(d["id"], d["kind"], d.get("dia"), d.get("path"), d["depth"], d.get("tool_corner_r", 0.0))


class Design(object):
    def __init__(self, shape, variant, blank, thick, outline, pockets=(), holes=(), grooves=(),
                 derived=None, messages=(), source=None, schema=1, units="mm"):
        self.schema, self.shape, self.variant, self.units = schema, shape, variant, units
        self.blank, self.thick, self.outline = blank, float(thick), outline
        self.pockets, self.holes, self.grooves = list(pockets), list(holes), list(grooves)
        self.derived = dict(derived or {})
        self.messages = list(messages)
        self.source = dict(source or {})

    def errors(self):
        return [m for m in self.messages if m.level == "error"]

    def features(self):
        return list(self.pockets) + list(self.holes) + list(self.grooves)

    def mirrored_y(self):
        """Дизайн после переворота заготовки вокруг оси X (y -> -y). Карманы для
        нижней стороны не нужны - только контур."""
        return Design(self.shape, self.variant, self.blank, self.thick, self.outline.mirrored_y(),
                      [], [], [], self.derived, self.messages, self.source, self.schema, self.units)

    def to_dict(self):
        return {"schema": self.schema, "shape": self.shape, "variant": self.variant, "units": self.units,
                "blank": self.blank.to_dict(), "thick": self.thick, "outline": self.outline.to_dict(),
                "pockets": [p.to_dict() for p in self.pockets], "holes": [h.to_dict() for h in self.holes],
                "grooves": [g.to_dict() for g in self.grooves], "derived": self.derived,
                "messages": [m.to_dict() for m in self.messages], "source": self.source}

    @classmethod
    def from_dict(cls, d):
        return cls(d["shape"], d.get("variant"), Blank.from_dict(d["blank"]), d["thick"],
                   Outline.from_dict(d["outline"]), [Pocket.from_dict(p) for p in d.get("pockets", [])],
                   [Hole.from_dict(h) for h in d.get("holes", [])], [Groove.from_dict(g) for g in d.get("grooves", [])],
                   d.get("derived"), [Message.from_dict(m) for m in d.get("messages", [])], d.get("source"),
                   d.get("schema", 1), d.get("units", "mm"))


# ---------------------------------------------------------------- из echo ---

def _need(d, key, what="boardcam_design"):
    if key not in d:
        raise DesignError("%s: нет поля %r" % (what, key))
    return d[key]


def geometry_refs(echo):
    """Имена export, которые нужно отрисовать в SVG для этого описания."""
    refs = []
    out = _need(echo, "outline")
    if isinstance(out, list) and out and out[0] == "svg":
        refs.append(out[1])
    for f in echo.get("features") or []:
        if not isinstance(f, list) or len(f) < 3:
            continue
        g = f[2]
        if isinstance(g, list) and len(g) == 2 and g[0] == "svg":
            refs.append(g[1])
    return refs


def from_echo(echo, regions_by_ref, source=None):
    """echo - dict из scad.echo.parse_echo; regions_by_ref - {имя export: [Region]}."""
    if _need(echo, "schema") != 1:
        raise DesignError("boardcam_design: схема %r не поддерживается (ожидается 1)" % echo["schema"])
    if echo.get("units", "mm") != "mm":
        raise DesignError("boardcam_design: единицы %r, поддерживаются только mm" % echo.get("units"))
    b = _need(echo, "blank")
    if not (isinstance(b, list) and len(b) == 3):
        raise DesignError("boardcam_design: blank должен быть [x, y, толщина]")
    blank = Blank(b[0], b[1], b[2], echo.get("origin", "corner"))
    messages = []
    for m in echo.get("messages") or []:
        if not (isinstance(m, list) and len(m) >= 3):
            raise DesignError("boardcam_design: сообщение %r не [уровень, код, текст]" % (m,))
        messages.append(Message(m[0], m[1], m[2], m[3] if len(m) > 3 else None))

    has_errors = any(m.level == "error" for m in messages)

    def region_of(ref, what):
        if not (isinstance(ref, list) and len(ref) == 2):
            raise DesignError("%s: ссылка на геометрию %r" % (what, ref))
        if ref[0] == "svg":
            if ref[1] not in regions_by_ref:
                if has_errors:          # фигура сообщила об ошибке и ничего не отрисовала
                    return []
                raise DesignError("%s: геометрия %r не отрисована" % (what, ref[1]))
            return [Region(simplify_ring(r.outer, SIMPLIFY_TOL), [simplify_ring(h, SIMPLIFY_TOL) for h in r.holes])
                    for r in regions_by_ref[ref[1]]]
        raise DesignError("%s: неизвестный вид геометрии %r" % (what, ref[0]))

    out = _need(echo, "outline")
    if isinstance(out, list) and out and out[0] == "circle":
        outline = Outline("circle", dia=out[1])
    else:
        regs = region_of(out, "outline")
        if len(regs) != 1:
            if has_errors and not regs:
                # фигура сообщила об ошибке и ничего не отрисовала; до плана дизайн не доживёт,
                # но объект нужен - ставим заглушку
                outline = Outline("polygon", region=Region([(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]))
            else:
                raise DesignError("outline: ожидалась одна область, получено %d" % len(regs))
        else:
            outline = Outline("polygon", region=regs[0])

    pockets, holes, grooves = [], [], []
    for f in echo.get("features") or []:
        if not (isinstance(f, list) and len(f) >= 2):
            raise DesignError("features: элемент %r" % (f,))
        kind, fid = f[0], f[1]
        if kind == "pocket":
            if len(f) < 5:
                raise DesignError("pocket %s: нужно [\"pocket\", id, геометрия, глубина, R дна]" % fid)
            regs = region_of(f[2], "pocket %s" % fid)
            regs = [r for r in regs if r.area > 1.0]
            if not regs and not has_errors:
                messages.append(Message("error", "FEATURE_EMPTY",
                                        "карман %s после скруглений не имеет площади: стенки сходятся "
                                        "или скругление больше самого кармана" % fid, str(fid)))
            pockets.append(Pocket(fid, regs, f[3], f[4], ref=f[2]))
        elif kind == "hole":
            if len(f) < 5:
                raise DesignError("hole %s: нужно [\"hole\", id, [x,y], диаметр, сквозное]" % fid)
            holes.append(Hole(fid, f[2], f[3], f[4], f[5] if len(f) > 5 else None))
        elif kind == "groove":
            if len(f) < 5:
                raise DesignError("groove %s: нужно [\"groove\", id, путь, глубина, R фрезы]" % fid)
            g = f[2]
            if isinstance(g, list) and g and g[0] == "circle":
                grooves.append(Groove(fid, "circle", dia=g[1], depth=f[3], tool_corner_r=f[4]))
            else:
                regs = region_of(g, "groove %s" % fid)
                if regs:
                    grooves.append(Groove(fid, "polygon", path=regs[0].outer, depth=f[3], tool_corner_r=f[4]))
        else:
            raise DesignError("features: неизвестный вид %r" % kind)
    derived = echo.get("derived") or {}
    return Design(_need(echo, "shape"), echo.get("variant"), blank, _need(echo, "thick"), outline,
                  pockets, holes, grooves, derived, messages, source, 1, "mm")
