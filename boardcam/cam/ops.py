# -*- coding: utf-8 -*-
"""Операции: черновая выборка, чистовая, контур, торцовка, жёлоб.

Перенос op_* / cut_* / link_move из board_v3/generate_board.py. Изменения:
* параметры станка приходят объектом CamSettings, инструмент - словарём записи
  из библиотеки; глобальных переменных нет;
* контур (profile) идёт по ЛЮБОМУ замкнутому пути центра фрезы; табы расставлены
  по длине пути (для окружности это те же места, что и по углу);
* шапка и хвост файла пишутся постпроцессором (post.masso), здесь - только тело.
Все формулы врезания, связок и растра - без изменений.
"""

import math

from ..geometry.polyline import arc_points, circle_points
from .tabs import tab_distances


def link_move(pk, cur, p_next, Rt):
    """Безопасная связка конца дуги со следующей. None -> отвод."""
    if cur is None:
        return None
    x0, y0 = cur[0]
    x1, y1 = p_next
    L = math.hypot(x1 - x0, y1 - y0)
    n = max(2, int(L / 1.2))
    for i in range(n + 1):        # проверяем ВЕСЬ отрезок связки, а не только его конец
        p = (x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n)
        if not pk.inside(p) or pk.dist_fast(p) < Rt - 0.05:
            return None
    return [p_next]


def cut_contour(g, pk, z, tool, Rt, cfg):
    """Обход стенки на расстоянии Rt: только там, где фреза реально помещается."""
    runs, nbad = pk.contour_runs(Rt)
    g.c("(   contour pass at %.3f from wall: %d run(s), %d pts skipped (too narrow) )"
        % (Rt, len(runs), nbad))
    fc = tool.get('feed_contour', tool['feed'])
    for run in runs:
        nramp = max(2, min(int(len(run) * 0.08), len(run) - 1))
        closed = run[0] == run[-1]
        # хвост = добор участка врезания на полной глубине. Замкнутый проход: вперёд по
        # следующим точкам. Открытый: в board_v3 инструмент шёл с конца прохода ПРЯМО к
        # началу участка врезания одним рабочим ходом через карман - у зубчатых контуров
        # (STL) этот ход резал стенки. Теперь: подъём на z_link, рапид к точке, где рампа
        # уже вышла на глубину, врезание в готовый паз и добор участка рампы назад.
        path = run + (run[1:nramp + 1] if closed else [])
        g.go(z=cfg.z_retract, move='G0')
        g.go(x=path[0][0], y=path[0][1], move='G0')
        for i, (x, y) in enumerate(path[1:]):
            if i < nramp:
                g.go(x=x, y=y, z=cfg.z_link + (-z - cfg.z_link) * (i + 1) / nramp, f=tool['ramp'])
            else:
                g.go(x=x, y=y, f=fc)
        if not closed:
            g.go(z=cfg.z_link, move='G0')
            g.go(x=run[nramp][0], y=run[nramp][1], move='G0')
            g.go(z=-z, f=tool['plunge'])
            for (x, y) in reversed(run[:nramp]):
                g.go(x=x, y=y, f=fc)
        g.go(z=cfg.z_retract, move='G0')


def cut_raster(g, pk, raster, z, tool, allow, sag, Rt, cfg):
    """Растр дна на глубине -z со связками: дуги (polar) или строки (linear)."""
    if getattr(raster, 'kind', 'polar') == 'linear':
        return cut_raster_linear(g, pk, raster.rows, z, tool, sag, Rt, cfg)
    arcs = raster.rows if hasattr(raster, 'rows') else raster
    cur = None
    for k, (rho, ivs) in enumerate(arcs):
        fwd = (k % 2 == 0)
        seq = ivs if fwd else list(reversed(ivs))
        for (t0, t1, tag0, tag1) in seq:
            if not fwd:
                t0, t1, tag0, tag1 = t1, t0, tag1, tag0
            if abs(t1 - t0) * rho < 0.8:
                continue
            p0 = (rho * math.cos(t0), rho * math.sin(t0))
            p1 = (rho * math.cos(t1), rho * math.sin(t1))
            pts = arc_points((0.0, 0.0), rho, t0, t1, sag)
            if cur is None:
                g.go(z=cfg.z_retract, move='G0')
                g.go(x=p0[0], y=p0[1], move='G0')
                nramp = 1
                acc = 0.0
                for i in range(1, len(pts)):
                    acc += math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
                    nramp = i
                    if acc >= cfg.ramp_len:
                        break
                for i in range(1, len(pts)):
                    zz = -z * min(1.0, i / float(nramp))
                    g.go(x=pts[i][0], y=pts[i][1], z=zz, f=tool['ramp'] if i <= nramp else tool['feed'])
            else:
                link = link_move(pk, cur, p0, Rt)
                if link is None:
                    g.go(z=cfg.z_link, move='G0')
                    g.go(x=p0[0], y=p0[1], move='G0')
                    g.go(z=-z, f=tool['plunge'])
                else:
                    for (x, y) in link:
                        g.go(x=x, y=y, f=tool['ramp'])
                    g.go(z=-z, f=tool['plunge'])
                for p in pts[1:]:
                    g.go(x=p[0], y=p[1], f=tool['feed'])
            cur = (p1, tag1)
    if cur is not None:
        g.go(z=cfg.z_retract, move='G0')


def cut_raster_linear(g, pk, rows, z, tool, sag, Rt, cfg):
    """Строки вдоль X змейкой; связка между отрезками - как у дуг (весь отрезок связки
    проверяется на зазор), иначе подъём на z_link и врезание; первый вход - рампой
    вдоль отрезка на длине ramp_len."""
    cur = None
    for k, (y, segs) in enumerate(rows):
        fwd = (k % 2 == 0)
        seq = segs if fwd else list(reversed(segs))
        for (x0, x1) in seq:
            if not fwd:
                x0, x1 = x1, x0
            if abs(x1 - x0) < 0.8:
                continue
            p0, p1 = (x0, y), (x1, y)
            if cur is None:
                g.go(z=cfg.z_retract, move='G0')
                g.go(x=p0[0], y=p0[1], move='G0')
                L = abs(x1 - x0)
                ramp = min(L, cfg.ramp_len)
                n = max(2, int(math.ceil(ramp / 1.0)))
                for i in range(1, n + 1):
                    xx = x0 + (x1 - x0) * (ramp / L) * i / n
                    g.go(x=xx, y=y, z=-z * i / n, f=tool['ramp'])
                if ramp < L - 1e-9:
                    g.go(x=x1, y=y, f=tool['feed'])
            else:
                link = link_move(pk, cur, p0, Rt)
                if link is None:
                    g.go(z=cfg.z_link, move='G0')
                    g.go(x=p0[0], y=p0[1], move='G0')
                    g.go(z=-z, f=tool['plunge'])
                else:
                    for (lx, ly) in link:
                        g.go(x=lx, y=ly, f=tool['ramp'])
                    g.go(z=-z, f=tool['plunge'])
                g.go(x=p1[0], y=p1[1], f=tool['feed'])
            cur = (p1, 'bnd')
    if cur is not None:
        g.go(z=cfg.z_retract, move='G0')


def rough_levels(target, doc):
    nlev = max(1, int(math.ceil(target / doc)))
    return [target * i / nlev for i in range(1, nlev + 1)]


def fillet_offset(h, rc):
    """Отступ контура кармана внутрь на высоте h над чистовым дном в зоне скругления
    дно/стенка радиуса rc (след чашечной фрезы): rc - sqrt(rc^2 - (rc - h)^2)."""
    if rc <= 0.0 or h >= rc:
        return 0.0
    if h <= 0.0:
        return rc
    return rc - math.sqrt(max(0.0, rc * rc - (rc - h) ** 2))


def op_rough(g, pockets, tool, cfg):
    """Черновая: припуск cfg.wall_allow на стенки и cfg.floor_allow на дно.
    pockets - список (карман, глубина, радиус скругления дна).

    В зоне скругления дно/стенка контур на уровне z отступает от стенки ещё на
    fillet_offset(depth - z): прямая фреза иначе срезает материал, из которого
    чашечная фреза формирует радиус (контроль по карте высот показывал зарез до
    3 мм вдоль каждой стенки). Уровень режет полосу стенки от z - doc до z; на
    глубине z сечение замысла самое узкое, поэтому отступ уровня безопасен для
    всей полосы. Возвращает {fid: [(z, F_extra)]}."""
    g.c("( Припуск: стенки %.3f, дно %.3f; в зоне скругления дна отступ больше - см. уровни )"
        % (cfg.wall_allow, cfg.floor_allow))
    g.c()
    all_levels = {}
    for pk, depth, rc in pockets:
        target = depth - cfg.floor_allow
        levels = rough_levels(target, tool['doc'])
        lev = [(z, fillet_offset(depth - z, rc)) for z in levels]
        all_levels[pk.fid] = lev
        g.c("(--- POCKET %s axis %.1f deg | levels z/offset: %s ---)"
            % (pk.fid, math.degrees(pk.mid), " ".join("%.3f/%.2f" % (z, F) for z, F in lev)))
        for z, F in lev:
            ras = pk.plan_raster(tool['dia'] / 2.0, cfg.wall_allow, tool['stepover'], F_extra=F)
            g.c("(   level %.3f: %s raster, %d rows, wall offset %.3f )" % (z, ras.kind, len(ras.rows), ras.Rt))
            cut_contour(g, pk, z, tool, ras.Rt, cfg)
            cut_raster(g, pk, ras, z, tool, cfg.wall_allow, cfg.sag_rough, ras.Rt, cfg)
            g.c()
    g.c("G0 Z" + _f(cfg.z_retract + 8.0))
    g.c("M05")
    g.c("M30")
    return all_levels


def op_finish(g, pockets, tool, cfg):
    """Чистовая: стенки обходом, дно полярным растром, один проход по Z на всю глубину.
    pockets - список (карман, глубина)."""
    r = tool['dia'] / 2.0
    g.c("( Сначала обход стенок/скруглений, затем дно полярным растром.)")
    g.c("( Один проход по Z на полную глубину: фреза формирует радиус у дна.)")
    g.c()
    for pk, z in pockets:
        g.c("(--- POCKET %s axis %.1f : wall contour ---)" % (pk.fid, math.degrees(pk.mid)))
        cut_contour(g, pk, z, tool, r, cfg)
        ras = pk.plan_raster(r, 0.0, tool["stepover"], F_extra=0.0)
        g.c("(--- POCKET floor: %s raster, %d rows, stepover %.3f ---)" % (ras.kind, len(ras.rows), tool['stepover']))
        cut_raster(g, pk, ras, z, tool, 0.0, cfg.sag_finish, ras.Rt, cfg)
        g.c()
    g.c("G0 Z" + _f(cfg.z_retract + 8.0))
    g.c("M05")
    g.c("M30")


def op_profile(g, path, depth, tab_z, tool, cfg):
    """Контур по замкнутому пути центра фрезы (path - без повтора первой точки).
    tab_z = глубина от текущего Z0, на которой рез стоит над табом (None -> табов нет)."""
    g.c("( Глубина по Z от текущего нуля: %.2f мм )" % depth)
    if tab_z is not None:
        g.c("( Табы: %d x %.1f мм, рез над табом стоит на Z-%.2f )" % (cfg.tabs, cfg.tab_len, tab_z))
    else:
        g.c("( БЕЗ табов: материал под резом ещё не прорезан насквозь )")
    g.c()
    nlev = max(1, int(math.ceil(depth / tool['doc'])))
    levels = [depth * i / nlev for i in range(1, nlev + 1)]
    use_tabs = tab_z is not None
    tab_top = tab_z if use_tabs else depth
    dists, L = tab_distances(path, cfg.tabs)
    g.c("( Z-уровни: %s ; длина пути %.1f мм )" % (" ".join("%.2f" % z for z in levels), L))
    g.go(x=path[0][0], y=path[0][1], move='G0')
    nramp = max(3, int(len(path) * 0.05))
    for zi, zt in enumerate(levels):
        g.go(z=cfg.z_link, f=tool['plunge'])
        for i, (x, y) in enumerate(path):
            zc = -zt
            if use_tabs and zt > tab_top:
                dmin = dists[i]
                half_in = cfg.tab_len / 2.0
                if dmin <= half_in:
                    zc = -tab_top
                elif dmin < half_in + cfg.tab_ramp:       # плавный съезд, без вертикального ныряния
                    zc = -(tab_top + (zt - tab_top) * (dmin - half_in) / cfg.tab_ramp)
            if i < nramp:
                g.go(x=x, y=y, z=cfg.z_link + (zc - cfg.z_link) * (i + 1) / nramp, f=tool['ramp'])
            else:
                g.go(x=x, y=y, z=zc, f=tool['feed'])
        g.go(x=path[0][0], y=path[0][1], f=tool['feed'])
        g.c()
    g.c("G0 Z" + _f(cfg.z_retract + 8.0))
    g.c("M05")
    g.c("M30")
    return levels


def op_flatten(g, tool, blank_x, blank_y, total, cfg):
    """Торцовка верха змейкой; перешагивание на рабочей подаче, не G0 в материале."""
    g.c("( Снять %.2f мм. ШАГ %.1f мм - проверьте диаметр фрезы.)" % (tool['doc'], tool['stepover']))
    g.c()
    nlev = max(1, int(math.ceil(total / tool['doc']))) if total > 1e-9 else 0
    g.c("( Снять %.2f мм за %d проход(ов) )" % (total, nlev))
    if nlev == 0:
        g.c("( Снимать нечего: толщина заготовки равна высоте изделия )")
    half = blank_x / 2.0 - tool['dia'] / 2.0
    half_y = blank_y / 2.0 - tool['dia'] / 2.0
    g.go(z=cfg.z_retract, move='G0')
    for lev in range(1, nlev + 1):
        z = -total * lev / nlev
        g.c("( уровень %d/%d, Z%.2f )" % (lev, nlev, z))
        y = half_y
        fwd = True
        first = True
        while y >= -half_y - 1e-9:
            x0 = -half if fwd else half
            x1 = half if fwd else -half
            if first:
                g.go(z=cfg.z_retract, move='G0')
                g.go(x=x0, y=y, move='G0')
                g.go(z=cfg.z_link, move='G0')
                g.go(z=z, f=tool['plunge'])
                first = False
            else:
                g.go(y=y, f=tool['feed'])  # перешагивание на рабочей подаче, НЕ G0 в материале
            g.go(x=x1, y=y, f=tool['feed'])
            fwd = not fwd
            y -= tool['stepover']
        g.go(z=cfg.z_retract, move='G0')
    g.c("G0 Z" + _f(cfg.z_retract + 5.0))
    g.c("M05")
    g.c("M30")


def op_groove(g, tool, path, depth, cfg):
    """Жёлоб по замкнутому пути (окружность на бортике) шаровой фрезой, 3 витка вниз."""
    g.c("( Жёлоб: глубина %.1f мм, 3 витка )" % depth)
    g.c()
    g.go(x=path[0][0], y=path[0][1], move='G0')
    for zi in range(1, 4):
        zt = -depth * zi / 3.0
        if zi == 1:
            g.go(z=zt, f=tool['ramp'])
            for (x, y) in path[1:]:
                g.go(x=x, y=y, f=tool['feed'])
        else:
            for (x, y) in path:
                g.go(x=x, y=y, z=zt, f=tool['feed'])
        g.c()
    g.c("G0 Z" + _f(cfg.z_retract + 8.0))
    g.c("M05")
    g.c("M30")


def _f(v):
    from .gcode import fnum
    return fnum(v)


def circle_path(r, sag):
    return circle_points((0.0, 0.0), r, sag)
