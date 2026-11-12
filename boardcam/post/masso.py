# -*- coding: utf-8 -*-
"""Постпроцессор MASSO G3: шапка и преамбула файла. Тело и хвост пишут операции."""

from .. import VERSION


def zero_note(blank, side="top"):
    if blank.origin == "corner":
        s = "X0 Y0 = ЛЕВЫЙ БЛИЖНИЙ УГОЛ квадрата %.1f x %.1f мм, Z0 = верх заготовки" % (blank.size_x, blank.size_y)
    else:
        s = "X0 Y0 = центр заготовки, Z0 = верх заготовки"
    if side == "bottom":
        s += " (НОВЫЙ верх после переворота!)"
    return s


def header_lines(title, tool, ctx):
    """ctx: dict(openscad_version, shape, preset, job, stamp, zero, blank, material, machine)."""
    L = []
    L.append("(" + "=" * 68 + ")")
    L.append("( " + title)
    L.append("( boardcam v%s  |  OpenSCAD %s  |  единицы: МИЛЛИМЕТРЫ (G21)" % (VERSION, ctx.get("openscad_version", "?")))
    L.append("( SHAPE    : %s / %s  |  job: %s  |  run: %s" % (ctx.get("shape"), ctx.get("preset") or "-",
                                                             ctx.get("job") or "-", ctx.get("stamp") or "-"))
    L.append("(" + "=" * 68 + ")")
    L.append("( TOOL     : %s" % tool["name"])
    L.append("( DIA      : %.2f мм, хвостовик %.2f мм" % (tool["dia"], float(tool.get("shank", 6.35))))
    L.append("( RPM      : S%d  (%s регулятор ~%.1f)" % (tool["rpm"], ctx.get("router", "Makita RT0701C"), tool.get("dial", 0.0)))
    L.append("( FEEDS    : рабочая %.0f / врезание %.0f / рампа %.0f мм/мин" % (tool["feed"], tool["plunge"], tool["ramp"]))
    L.append("( ZERO     : %s" % ctx["zero"])
    b = ctx["blank"]
    L.append("( STOCK    : %.1f x %.1f x %.1f мм, деталь центрирована" % (b.size_x, b.size_y, b.thick))
    L.append("( WOOD     : %s" % ctx.get("material", "-"))
    m = ctx.get("machine", {})
    L.append("( CONTROL  : %s - %s, поле %.0f x %.0f мм" % (m.get("controller", "MASSO G3"), m.get("name", ""),
                                                          m.get("field", [0, 0])[0], m.get("field", [0, 0])[1]))
    L.append("(" + "=" * 68 + ")")
    L.append("G21 G17 G90 G94")
    L.append("G54")
    L.append("G0 Z" + _fnum(ctx["z_safe"]))
    router_name = ctx.get("router", "Makita RT0701C")
    dial_val = tool.get("dial", 0.0)
    L.append("( MSG: ПРОВЕРЬТЕ ШПИНДЕЛЬ: %s ДИСК ~%.1f, S%d )" % (router_name, dial_val, tool["rpm"]))
    L.append("M05")
    L.append("S%d M03" % tool["rpm"])
    L.append("G4 P3.0 (ПАУЗА 3 СЕК НА РАСКРУТКУ ШПИНДЕЛЯ)")
    L.append("G0 Z" + _fnum(ctx["z_safe"]))
    return L


def _fnum(v):
    from ..cam.gcode import fnum
    return fnum(v)


def render(title, tool, ctx, body):
    """Полный текст файла .nc: шапка + тело (тело уже содержит M05/M30)."""
    return "\n".join(header_lines(title, tool, ctx) + body.L) + "\n"
