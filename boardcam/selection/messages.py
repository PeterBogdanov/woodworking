# -*- coding: utf-8 -*-
"""Тексты отказов и пояснений выбора инструмента (по-русски, с числами и ближайшей записью)."""


def tool_short(t):
    return "%s (%s, D%.2f%s)" % (t["id"], t.get("title") or t["name"], t["dia"],
                                 ", R%.2f" % t["corner_r"] if t.get("corner_r") else "")


def nearest(tools, key, target):
    best = None
    for t in tools:
        v = t.get(key)
        if v is None:
            continue
        if best is None or abs(v - target) < abs(best.get(key) - target):
            best = t
    return best


MSG = {
    "FINISH_FILLET": "карман %(fid)s требует чашечную фрезу (bowl) с радиусом скругления %(r).2f мм и ролью finish; "
                     "в библиотеке такой нет%(nearest)s",
    "FINISH_FLAT": "карман %(fid)s с плоским дном без скругления требует прямую фрезу с ролью finish; в библиотеке такой нет",
    "FINISH_DEPTH": "глубина кармана %(fid)s %(depth).1f мм больше режущей части чистовой фрезы %(tool)s (%(loc).1f мм)",
    "FINISH_FITS": "чистовая фреза %(tool)s D%(dia).2f не входит в карман %(fid)s: нет места ни для дна, ни для обхода стенок",
    "ROUGH_FITS": "в карман %(fid)s не входит ни одна черновая (flat, rough) фреза: самая тонкая - %(smallest)s",
    "ROUGH_NONE": "в библиотеке нет прямой фрезы с ролью rough",
    "ROUGH_DEPTH": "черновая фреза %(tool)s: режущая часть %(loc).1f мм меньше глубины выборки %(depth).1f мм",
    "PROFILE_NONE": "в библиотеке нет прямой фрезы с ролью profile",
    "PROFILE_LOC": "даже с переворотом не хватает длины: снизу надо резать %(d_bot).1f мм при режущей части %(loc).1f мм "
                   "(фреза %(tool)s). Уменьшите толщину или возьмите фрезу длиннее",
    "WALL_MIN": "стенки между карманами %(wall).1f мм тоньше минимума %(min).1f мм",
    "BLANK_FIT": "изделие %(need).1f x %(need_y).1f мм (с запасом на контурную фрезу 2 x %(margin).2f) не влезает в заготовку %(bx).1f x %(by).1f мм",
    "BLANK_FIELD": "заготовка %(bx).1f x %(by).1f мм не влезает в поле станка %(fx).0f x %(fy).0f мм",
    "BLANK_THIN": "заготовка %(bt).1f мм тоньше изделия %(t).1f мм",
    "FLATTEN_NONE": "заготовка толще изделия на %(d).2f мм, торцовка запрошена, но в библиотеке нет фрезы с ролью surface",
    "FLOOR_MIN": "карман %(fid)s глубиной %(depth).1f оставляет дну %(floor).1f мм при минимуме %(min).1f",
    "GROOVE_TOOL": "жёлоб %(fid)s требует шаровую фрезу (ball) с радиусом %(r).2f мм и ролью groove; в библиотеке такой нет%(nearest)s",
    "GROOVE_DEPTH": "жёлоб %(fid)s глубиной %(depth).1f мм: у фрезы %(tool)s режущая часть %(loc).1f мм",
    "OVERRIDE_UNKNOWN": "в задании для роли %(role)s указана фреза %(tid)r, которой нет в библиотеке",
    "OVERRIDE_ROLE": "фреза %(tid)s не имеет роли %(role)s в библиотеке (roles: %(roles)s)",
    "MATERIAL_UNKNOWN": "материала %(mid)r нет в библиотеке (есть: %(have)s)",
    "SHAPE_ERROR": "фигура сообщает об ошибке %(code)s: %(text)s",
}


def text(key, **kw):
    return MSG[key] % kw
