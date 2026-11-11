# -*- coding: utf-8 -*-
"""Выбор фрез и проверка выполнимости (DESIGN.md §5.4).

Правила детерминированные, считаются по каждому карману и каждой роли. Результат -
Plan: фреза на роль (с причиной) и список операций, либо отказы с кодами и
понятными фразами. Переопределения из задания ({"finish": "<id>"}) заставляют
взять конкретную фрезу; правила всё равно проверяются и могут отказать.
"""

import math

from ..cam.pocket import Pocket as CamPocket
from ..cam.settings import CamSettings
from ..design.model import Message
from . import messages as M


class OpSpec(object):
    """Одна операция = один файл .nc."""

    def __init__(self, kind, filename, role, title, **extra):
        self.kind, self.filename, self.role, self.title = kind, filename, role, title
        self.extra = extra

    def to_dict(self):
        d = {"kind": self.kind, "filename": self.filename, "role": self.role, "title": self.title}
        d.update({k: v for k, v in self.extra.items() if k not in ("pockets",)})
        return d


class Plan(object):
    def __init__(self, design, lib, material, cfg):
        self.design, self.lib, self.material, self.cfg = design, lib, material, cfg
        self.refusals = []       # Message(error)
        self.notes = []          # Message(warn/info)
        self.tools = {}          # роль -> запись фрезы (масштабированная под материал)
        self.reasons = {}        # роль -> почему выбрана
        self.ops = []            # OpSpec по порядку выполнения
        self.cam_pockets = []    # (CamPocket, design.Pocket)
        self.profile = {}
        self.flatten_total = 0.0

    @property
    def ok(self):
        return not self.refusals

    def refuse(self, code, feature=None, **kw):
        self.refusals.append(Message("error", code, M.text(code, **kw), feature))

    def note(self, code, text, feature=None, level="warn"):
        self.notes.append(Message(level, code, text, feature))

    def to_dict(self):
        return {"ok": self.ok,
                "refusals": [m.to_dict() for m in self.refusals],
                "notes": [m.to_dict() for m in self.notes],
                "tools": {r: {k: v for k, v in t.items()} for r, t in self.tools.items()},
                "reasons": self.reasons,
                "ops": [o.to_dict() for o in self.ops],
                "profile": self.profile,
                "raster": getattr(self, "raster_strategy", "polar"),
                "flatten_total": self.flatten_total,
                "material": self.material["id"] if self.material else None}


def cam_pockets_for(design):
    """Карманы дизайна -> карманы для траекторий (область может распасться на части)."""
    out = []
    for p in design.pockets:
        if len(p.regions) == 1:
            out.append((CamPocket(p.regions[0], p.id), p))
        else:
            for k, reg in enumerate(p.regions):
                out.append((CamPocket(reg, "%s%s" % (p.id, chr(ord('a') + k))), p))
    return out


def plan(design, lib, material=None, overrides=None, options=None):
    cfg = CamSettings(lib.machine)
    overrides = dict(overrides or {})
    options = dict(options or {})
    mat = lib.material(material) if material else lib.reference_material()
    pl = Plan(design, lib, mat, cfg)
    if mat is None:
        pl.refuse("MATERIAL_UNKNOWN", mid=material, have=", ".join(m["id"] for m in lib.materials))
        return pl
    for m in design.errors():
        pl.refusals.append(Message("error", m.code, M.text("SHAPE_ERROR", code=m.code, text=m.text), m.feature))
    if pl.refusals:
        return pl
    for m in design.messages:
        if m.level != "error":
            pl.notes.append(m)

    # переопределения из задания: фреза должна существовать и иметь роль
    forced = {}
    for role, tid in overrides.items():
        if not tid:
            continue
        t = lib.tool(tid)
        if t is None:
            pl.refuse("OVERRIDE_UNKNOWN", role=role, tid=tid)
        elif role not in t.get("roles", ()):
            pl.refuse("OVERRIDE_ROLE", tid=tid, role=role, roles=", ".join(t.get("roles", ())))
        else:
            forced[role] = t
    if pl.refusals:
        return pl

    def pick(role, tool):
        pl.tools[role] = lib.scaled_tool(tool, mat)
        if pl.tools[role]["rpm"] < min(mat["rpm"], 10 ** 9):
            pl.note("RPM", "%s: обороты снижены до паспортных %d об/мин" % (tool["id"], pl.tools[role]["rpm"]), level="info")

    pl.cam_pockets = cam_pockets_for(design)
    # стратегия растра: дуги вокруг центра только для круглых досок (стенки-дуги соосны кольцам);
    # у прямых стенок дуги касаются стенки и оставляют полосы - там строки вдоль X
    strategy = 'polar' if design.outline.kind == 'circle' and options.get("raster", "auto") == "auto" \
        else options.get("raster", "linear")
    if strategy not in ('polar', 'linear'):
        strategy = 'linear'
    for pk, dp in pl.cam_pockets:
        pk.strategy = strategy
    pl.raster_strategy = strategy
    blank, thick = design.blank, design.thick
    min_floor = float(lib.machine.get("min_floor", 3.0))

    # --- карманы: чистовая --------------------------------------------------------
    finish_tool = None
    fillets = sorted({round(p.floor_fillet_r, 2) for p in design.pockets})
    if design.pockets:
        if len(fillets) > 1:
            pl.refuse("FINISH_FILLET", fid=", ".join(p.id for p in design.pockets), r=fillets[0],
                      nearest=" (в карманах разные радиусы дна: %s - пока поддерживается один)" % fillets)
        else:
            fr = fillets[0]
            if fr > 0:
                cands = [t for t in lib.tools_for("finish", "bowl") if abs(float(t.get("corner_r", 0)) - fr) <= 0.1]
                if "finish" in forced:
                    ft = forced["finish"]
                    if ft["type"] != "bowl" or abs(float(ft.get("corner_r", 0)) - fr) > 0.1:
                        pl.refuse("FINISH_FILLET", fid=design.pockets[0].id, r=fr,
                                  nearest=" (задание требует %s с R%.2f)" % (ft["id"], float(ft.get("corner_r", 0))))
                    else:
                        finish_tool = ft
                        pl.reasons["finish"] = "задано в задании; радиус R%.2f совпадает с дном кармана" % fr
                elif cands:
                    finish_tool = max(cands, key=lambda t: t["dia"])
                    pl.reasons["finish"] = "единственная чашечная фреза с R%.2f = радиусу дна кармана" % fr \
                        if len(cands) == 1 else "самая большая чашечная фреза с R%.2f" % fr
                else:
                    near = M.nearest(lib.tools_for("finish"), "corner_r", fr)
                    pl.refuse("FINISH_FILLET", fid=", ".join(p.id for p in design.pockets), r=fr,
                              nearest=(" (ближайшая: %s)" % M.tool_short(near)) if near else "")
            else:
                cands = lib.tools_for("finish", "flat")
                if "finish" in forced:
                    finish_tool = forced["finish"]
                    pl.reasons["finish"] = "задано в задании"
                elif cands:
                    finish_tool = max(cands, key=lambda t: t["dia"])
                    pl.reasons["finish"] = "самая большая прямая фреза с ролью finish"
                else:
                    pl.refuse("FINISH_FLAT", fid=", ".join(p.id for p in design.pockets))
    if finish_tool is not None:
        pick("finish", finish_tool)
        r = finish_tool["dia"] / 2.0
        for pk, dp in pl.cam_pockets:
            if dp.depth > float(finish_tool["loc"]) + 1e-9:
                pl.refuse("FINISH_DEPTH", fid=pk.fid, depth=dp.depth, tool=finish_tool["id"], loc=float(finish_tool["loc"]))
            if dp.depth > thick - min_floor + 1e-9:
                pl.refuse("FLOOR_MIN", fid=pk.fid, depth=dp.depth, floor=thick - dp.depth, min=min_floor)
            ras = pk.plan_raster(r, 0.0, finish_tool["stepover"])
            runs, nbad = pk.contour_runs(r)
            if not ras and not runs:
                pl.refuse("FINISH_FITS", fid=pk.fid, tool=finish_tool["id"], dia=finish_tool["dia"])
            elif nbad:
                pl.note("FINISH_LEFTOVER", "карман %s: фрезе %s недоступно %d точек обхода стенок (узко) - "
                        "там останется черновой припуск %.1f мм, снять вручную"
                        % (pk.fid, finish_tool["id"], nbad, cfg.wall_allow), pk.fid, level="info")

    # --- карманы: черновая --------------------------------------------------------
    rough_tool = None
    if design.pockets:
        cands = sorted(lib.tools_for("rough", "flat"), key=lambda t: -t["dia"])
        if "rough" in forced:
            cands = [forced["rough"]]
        if not cands:
            pl.refuse("ROUGH_NONE")
        else:
            for t in cands:
                fits = True
                for pk, dp in pl.cam_pockets:
                    if not pk.plan_raster(t["dia"] / 2.0, cfg.wall_allow, t["stepover"]):
                        fits = False
                        bad = pk.fid
                        break
                if fits:
                    rough_tool = t
                    pl.reasons["rough"] = ("задано в задании" if "rough" in forced else
                                           "самая большая прямая фреза с ролью rough, входящая во все карманы")
                    break
            if rough_tool is None:
                pl.refuse("ROUGH_FITS", fid=bad, smallest=M.tool_short(min(cands, key=lambda t: t["dia"])))
    if rough_tool is not None:
        pick("rough", rough_tool)
        from ..cam.ops import fillet_offset
        for pk, dp in pl.cam_pockets:
            if dp.depth - cfg.floor_allow > float(rough_tool["loc"]) + 1e-9:
                pl.refuse("ROUGH_DEPTH", tool=rough_tool["id"], loc=float(rough_tool["loc"]), depth=dp.depth - cfg.floor_allow)
            F = fillet_offset(cfg.floor_allow, dp.floor_fillet_r)
            ras = pk.plan_raster(rough_tool["dia"] / 2.0, cfg.wall_allow, rough_tool["stepover"], F_extra=F)
            if not ras:
                pl.note("ROUGH_FLOOR", "карман %s: у дна (отступ %.1f мм за зону скругления) черновой фрезе места нет - "
                        "дно снимет чистовая на всю глубину" % (pk.fid, ras.Rt), pk.fid)

    # --- стенки ---------------------------------------------------------------------
    wall = design.derived.get("wall_min")
    if isinstance(wall, (int, float)) and wall < cfg.min_wall - 1e-9:
        pl.refuse("WALL_MIN", wall=wall, min=cfg.min_wall)

    # --- торцовка / толщина -----------------------------------------------------------
    flatten_opt = options.get("flatten", "auto")
    surf = forced.get("surface") or (max(lib.tools_for("surface"), key=lambda t: t["dia"]) if lib.tools_for("surface") else None)
    flatten = False
    if blank.thick < thick - 1e-9:
        pl.refuse("BLANK_THIN", bt=blank.thick, t=thick)
    elif blank.thick > thick + 1e-9:
        d = blank.thick - thick
        if flatten_opt == "off":
            pl.note("BLANK_THICKER", "заготовка толще изделия на %.2f мм, торцовка выключена: строгайте рейсмусом "
                    "до %.1f мм; контур сейчас режется на всю толщину заготовки" % (d, thick))
        elif surf is None:
            if flatten_opt == "on":
                pl.refuse("FLATTEN_NONE", d=d)
            else:
                pl.note("BLANK_THICKER", "заготовка толще изделия на %.2f мм, торцовочной фрезы в библиотеке нет: "
                        "строгайте до %.1f мм; контур режется на всю толщину заготовки" % (d, thick))
        else:
            flatten = True
            pl.flatten_total = d
            pick("surface", surf)
            pl.reasons["surface"] = "торцовка снимет %.2f мм; Z0 для остальных файлов ставить ПО НОВОЙ плоскости" % d

    # --- контур ---------------------------------------------------------------------
    prof_cands = lib.tools_for("profile", "flat")
    prof = forced.get("profile") or (max(prof_cands, key=lambda t: t["loc"]) if prof_cands else None)
    if prof is None:
        pl.refuse("PROFILE_NONE")
    else:
        pick("profile", prof)
        pl.reasons["profile"] = "задано в задании" if "profile" in forced else "прямая фреза с ролью profile с самой длинной режущей частью"
        loc = float(prof["loc"])
        need = (thick if flatten else max(thick, blank.thick)) + cfg.profile_extra
        mode = options.get("profile_mode", "auto")
        if mode == "auto":
            mode = "full" if need <= loc - 1.2 else "flip"
        pl.profile = {"mode": mode, "need": need, "loc": loc}
        if mode == "full":
            pl.profile["tab_z"] = thick - cfg.tab_h
        else:
            d_top = min(loc - 1.2, need - 4.0)
            d_bot = need - d_top + 2.5                      # перекрытие по стыку
            pl.profile.update({"d_top": d_top, "d_bot": d_bot, "tab_z_bot": thick - d_top - cfg.tab_h})
            pl.note("PROFILE_FLIP", "режущая часть контурной фрезы %.1f мм < реза %.1f мм -> контур в ДВЕ "
                    "установки (03a сверху, переворот вокруг оси X, 03b снизу)" % (loc, need))
            if d_bot > loc - 1.2:
                pl.refuse("PROFILE_LOC", d_bot=d_bot, loc=loc, tool=prof["id"])
        # заготовка: контур снаружи детали, фрезе нужен запас 2*r с каждой стороны
        x0, y0, x1, y1 = design.outline.bbox()
        margin = 2.0 * prof["dia"] / 2.0
        need_x, need_y = (x1 - x0) + 2 * margin, (y1 - y0) + 2 * margin
        if need_x > blank.size_x + 1e-6 or need_y > blank.size_y + 1e-6:
            pl.refuse("BLANK_FIT", need=need_x, need_y=need_y, margin=margin, bx=blank.size_x, by=blank.size_y)
    if blank.size_x > cfg.field[0] or blank.size_y > cfg.field[1] or blank.size_x > float(lib.machine.get("max_blank", 1e9)):
        pl.refuse("BLANK_FIELD", bx=blank.size_x, by=blank.size_y, fx=cfg.field[0], fy=cfg.field[1])

    # --- жёлоб ---------------------------------------------------------------------
    groove_tool = None
    if design.grooves:
        rr = design.grooves[0].tool_corner_r
        cands = [t for t in lib.tools_for("groove", "ball") if abs(float(t.get("corner_r", 0)) - rr) <= 0.1]
        if "groove" in forced:
            cands = [forced["groove"]]
        if not cands:
            near = M.nearest(lib.tools_for("groove"), "corner_r", rr)
            pl.refuse("GROOVE_TOOL", fid=design.grooves[0].id, r=rr,
                      nearest=(" (ближайшая: %s)" % M.tool_short(near)) if near else "")
        else:
            groove_tool = cands[0]
            pick("groove", groove_tool)
            pl.reasons["groove"] = "шаровая фреза с R%.2f = радиусу жёлоба" % rr
            for gv in design.grooves:
                if gv.depth > float(groove_tool["loc"]):
                    pl.refuse("GROOVE_DEPTH", fid=gv.id, depth=gv.depth, tool=groove_tool["id"], loc=float(groove_tool["loc"]))

    if pl.refusals:
        return pl

    # --- список операций -------------------------------------------------------------
    if flatten:
        pl.ops.append(OpSpec("flatten", "00_flatten_top.nc", "surface",
                             "00 ТОРЦОВКА ВЕРХА - снять излишек заготовки %.2f мм" % pl.flatten_total))
    if design.pockets:
        pl.ops.append(OpSpec("rough", "01_rough_%s.nc" % rough_tool["id"], "rough",
                             "01 ROUGH POCKETS - %d compartments (%s)" % (len(pl.cam_pockets), rough_tool["name"])))
        pl.ops.append(OpSpec("finish", "02_finish_%s.nc" % finish_tool["id"], "finish",
                             "02 FINISH POCKETS - walls + floor (%s)" % finish_tool["name"]))
    if pl.profile["mode"] == "full":
        pl.ops.append(OpSpec("profile", "03_profile_full.nc", "profile",
                             "03 PROFILE - контур насквозь за одну установку + табы",
                             depth=pl.profile["need"], tab_z=pl.profile["tab_z"], side="top"))
    else:
        pl.ops.append(OpSpec("profile", "03a_profile_top.nc", "profile",
                             "03a PROFILE - ВЕРХНЯЯ сторона, рез %.1f мм (насквозь НЕ идёт)" % pl.profile["d_top"],
                             depth=pl.profile["d_top"], tab_z=None, side="top"))
        pl.ops.append(OpSpec("profile", "03b_profile_bottom_FLIP.nc", "profile",
                             "03b PROFILE - ПОСЛЕ ПЕРЕВОРОТА, рез %.1f мм + табы" % pl.profile["d_bot"],
                             depth=pl.profile["d_bot"], tab_z=pl.profile["tab_z_bot"], side="bottom"))
    if groove_tool is not None:
        pl.ops.append(OpSpec("groove", "05_groove_%s.nc" % groove_tool["id"], "groove",
                             "05 GROOVE - жёлоб на бортике (%s)" % groove_tool["name"]))
    return pl
