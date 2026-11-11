# -*- coding: utf-8 -*-
"""Прогон: дизайн + план -> траектории, проверки, файлы .nc, отчёт, каталог out/<job>/<stamp>/.

Прогон - чистая функция своих входов: никакого состояния на уровне модуля.
"""

import json
import math
import os
import shutil
import time

from .. import VERSION
from ..cam import ops
from ..cam.gcode import GCode
from ..geometry.polyline import circle_points
from ..geometry.offset import offset_outward
from ..post import masso
from ..verify import lint, analytic
from ..verify.report import Report
from ..preview.topview import topview_svg, preview_paths
from ..design import io as design_io
from .jobsheet import job_sheet
from .package import zip_run


class RunResult(object):
    def __init__(self):
        self.ok = False
        self.verdict = ""
        self.report = ""
        self.files = []          # dict(name, size, minutes, url)
        self.dir = None
        self.stamp = None
        self.messages = []
        self.heightmap = None


def profile_path(design, r, sag):
    """Путь центра контурной фрезы: СНАРУЖИ контура на расстоянии r.

    Дуги линеаризуются вписанным многоугольником, чьи хорды лежат на sag ближе к
    детали, чем сама дуга; поэтому радиус берётся r + sag - тогда хорды не заходят
    внутрь линии контура, а деталь получается больше замысла не более чем на sag."""
    if design.outline.kind == 'circle':
        return circle_points((0.0, 0.0), design.outline.dia / 2.0 + r + sag, sag)
    return offset_outward(design.outline.region.outer, r + sag, sag)


def machine_offset(blank):
    if blank.origin == 'corner':
        return (blank.size_x / 2.0, blank.size_y / 2.0)
    return (0.0, 0.0)


def generate(design, plan, lib, run_dir, job_name=None, stl_path=None, verify_heightmap=None, stamp=None):
    """Полный прогон в каталог run_dir (создаётся атомарно: <run_dir>.tmp -> run_dir)."""
    if not plan.ok:
        raise ValueError("план содержит отказы: " + "; ".join(m.text for m in plan.refusals))
    t_start = time.time()
    cfg = plan.cfg
    blank = design.blank
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    off = machine_offset(blank)
    mat = plan.material
    ctx = {"openscad_version": design.source.get("openscad_version", "?"), "shape": design.shape,
           "preset": design.source.get("preset"), "job": job_name, "stamp": stamp, "blank": blank,
           "material": mat.get("notes") or mat.get("title"), "machine": lib.machine, "z_safe": cfg.z_retract,
           "router": lib.machine.get("router", "Makita RT0701C"), "zero": masso.zero_note(blank)}
    rep = Report()
    res = RunResult()
    res.stamp = stamp

    lint.selftest(blank, design.thick, cfg.profile_extra, cfg.z_retract)

    pockets = [pk for pk, dp in plan.cam_pockets]
    depths = {pk.fid: dp.depth for pk, dp in plan.cam_pockets}
    fillets = {pk.fid: dp.floor_fillet_r for pk, dp in plan.cam_pockets}

    # ---------------------------------------------------------------- траектории ---
    files = []                       # (fn, GCode, tool, title, side)
    g_rough = g_fin = None
    prof_paths = []                  # (side, path, r)
    for op in plan.ops:
        tool = plan.tools[op.role]
        g = GCode(off)
        side = op.extra.get("side", "top")
        if op.kind == "flatten":
            ops.op_flatten(g, tool, blank.size_x, blank.size_y, plan.flatten_total, cfg)
        elif op.kind == "rough":
            ops.op_rough(g, [(pk, depths[pk.fid], fillets[pk.fid]) for pk in pockets], tool, cfg)
            g_rough = g
        elif op.kind == "finish":
            ops.op_finish(g, [(pk, depths[pk.fid]) for pk in pockets], tool, cfg)
            g_fin = g
        elif op.kind == "profile":
            d = design if side == "top" else design.mirrored_y()
            path = profile_path(d, tool["dia"] / 2.0, cfg.sag_finish)
            prof_paths.append((side, path, tool["dia"] / 2.0, d))
            ops.op_profile(g, path, op.extra["depth"], op.extra["tab_z"], tool, cfg)
        elif op.kind == "groove":
            for gv in design.grooves:
                ops.op_groove(g, tool, gv.centerline(cfg.sag_finish), gv.depth, cfg)
        else:
            raise ValueError("неизвестная операция %r" % op.kind)
        files.append((op.filename, g, tool, op.title, side))

    # -------------------------------------------------------------------- отчёт ---
    rep.section("ПАРАМЕТРЫ ИЗДЕЛИЯ (boardcam v%s, OpenSCAD %s, всё в миллиметрах)" % (VERSION, ctx["openscad_version"]))
    rep.line("  фигура / набор ............. %s / %s%s" % (design.shape, design.source.get("preset") or "-",
                                                          ("   (задание %s)" % job_name) if job_name else ""))
    if design.outline.kind == 'circle':
        rep.line("  контур ..................... окружность D%.1f мм" % design.outline.dia)
    else:
        x0, y0, x1, y1 = design.outline.bbox()
        rep.line("  контур ..................... многоугольник %.1f x %.1f мм (%d вершин)" % (x1 - x0, y1 - y0, len(design.outline.region.outer)))
    rep.line("  заготовка .................. %.1f x %.1f x %.1f мм, ноль: %s"
             % (blank.size_x, blank.size_y, blank.thick, "ЛЕВЫЙ БЛИЖНИЙ УГОЛ" if blank.origin == 'corner' else "центр"))
    rep.line("  центр детали в коорд. станка X%.1f Y%.1f" % off)
    rep.line("  толщина (высота) ........... %.1f мм" % design.thick)
    if design.pockets:
        ds = sorted({p.depth for p in design.pockets})
        rep.line("  карманы .................... %d шт (%d областей), глубина %s мм, площадь %.0f см2"
                 % (len(design.pockets), len(pockets), "/".join("%.1f" % d for d in ds),
                    sum(p.area for p in design.pockets) / 100.0))
    if design.grooves:
        rep.line("  жёлоб ...................... %d шт, глубина %.1f мм" % (len(design.grooves), design.grooves[0].depth))
    rep.line("  материал / подачи .......... %s (множитель %.2f)" % (ctx["material"], float(mat.get("feed_scale", 1.0))))
    prm = design.source.get("params") or {}
    if prm:
        rep.line("  параметры фигуры ........... " + " ".join("%s=%s" % (k, v) for k, v in sorted(prm.items())))

    rep.line("  растр дна .................. %s" % ("дуги вокруг центра" if getattr(plan, "raster_strategy", "polar") == "polar" else "строки вдоль X"))

    rep.section("ВЫБОР ИНСТРУМЕНТА")
    for role in ("surface", "rough", "finish", "profile", "groove"):
        t = plan.tools.get(role)
        if t:
            rep.line("  %-8s %-24s D%.2f%s  S%d (регулятор ~%.1f)  подача %.0f" % (
                role, t["id"], t["dia"], (" R%.2f" % t["corner_r"]) if t.get("corner_r") else "",
                t["rpm"], t.get("dial", 0), t["feed"]))
            rep.line("           %s" % plan.reasons.get(role, ""))
    for m in plan.notes:
        if m.level == "info" and m.code == "RPM":
            rep.line("  " + m.text)

    rep.section("ПРОВЕРКИ ГЕОМЕТРИИ")
    wall = design.derived.get("wall_min")
    if isinstance(wall, (int, float)):
        rep.line("  реальная толщина стенки .... %.1f мм (минимум %.1f)" % (wall, cfg.min_wall))
        if wall < cfg.min_wall - 1e-9:
            rep.fail("стенка %.1f мм тоньше минимума %.1f мм" % (wall, cfg.min_wall))
    for m in plan.notes:
        if m.level != "info" or m.code not in ("RPM",):
            if m.code != "FINISH_LEFTOVER":
                rep.warn(m.text)
    for pk in pockets:
        ang = analytic.sharpest_corner(pk)
        rep.line("  отсек %-3s ось %6.1f : площадь %5.0f см2, R min по контуру %.1f мм, глубина %.1f, острейший угол %.0f°"
                 % (pk.fid, math.degrees(pk.mid), pk.area / 100.0, pk.r_min, depths[pk.fid], ang))
        if ang < 60.0:
            rep.fail("отсек %s: угол контура %.0f° острее 60° - игла на контуре" % (pk.fid, ang))
        for h in pk.holes:
            rep.line("      островок: %d вершин" % len(h))

    rep.section("КОНТРОЛЬ ЗАЗОРОВ")
    tr, tf = plan.tools.get("rough"), plan.tools.get("finish")
    if tr:
        r = tr['dia'] / 2.0
        for pk in pockets:
            levels = ops.rough_levels(depths[pk.fid] - cfg.floor_allow, tr['doc'])
            worst_margin, worst_txt = 1e9, ""
            for z in levels:
                F = ops.fillet_offset(depths[pk.fid] - z, fillets[pk.fid])
                ras = pk.plan_raster(r, cfg.wall_allow, tr['stepover'], F_extra=F)
                Rt = ras.Rt
                if not ras:
                    rep.warn("отсек %s, уровень %.2f: черновой растр пуст (узко с учётом зоны скругления %.2f) - "
                             "эту глубину снимет чистовая" % (pk.fid, z, F))
                    continue
                worst = analytic.clearance_rough(pk, ras)
                if worst - Rt < worst_margin:
                    worst_margin, worst_txt = worst - Rt, "z%.2f: мин. центр-контур = %.3f (нужно >= %.3f мм)" % (z, worst, Rt - 0.05)
            good = worst_margin >= -0.05
            rep.line("  черновой %-3s: %d уровней, худший %s %s"
                     % (pk.fid, len(levels), worst_txt, "OK" if good else "!!! НАРУШЕНИЕ"))
            if not good:
                rep.ok = False
    if tf:
        r = tf['dia'] / 2.0
        for pk in pockets:
            runs, nbad = pk.contour_runs(r)
            worst, npts = analytic.clearance_finish(pk, runs)
            good = worst >= r - 0.25
            rep.line("  чистовой обход %-3s: %d проход(ов), мин. центр-стенка %.3f (нужно >= %.3f мм) %s"
                     % (pk.fid, len(runs), worst, r - 0.25, "OK" if good else "!!! ВРЕЗАНИЕ В СТЕНКУ"))
            rep.line("     фрезе %s недоступно %d точек обхода из %d - там остаётся черновой припуск %.1f мм, снять вручную"
                     % (tf['id'], nbad, nbad + npts, cfg.wall_allow))
            if not good:
                rep.ok = False
    for side, path, r, d in prof_paths:
        ring = d.outline.ring(cfg.sag_finish)
        worst, inside = analytic.profile_clearance(path, ring, r)
        good = worst >= r - 0.05 and inside == 0
        rep.line("  контур (%s): мин. центр-деталь %.3f (нужно >= %.3f), точек внутри детали %d %s"
                 % ("верх" if side == "top" else "низ", worst, r - 0.05, inside, "OK" if good else "!!! КОНТУР РЕЖЕТ ДЕТАЛЬ"))
        if not good:
            rep.ok = False
        # наружный эквидистант зубчатого контура самопересекается петлями; петли лежат снаружи
        # своего контура, но могут заходить в деталь - ловим по длине пути
        from ..geometry.polyline import path_length
        L_path, L_ring = path_length(path, True), path_length(ring, True)
        limit = L_ring + 2 * math.pi * r
        rep.line("  контур (%s): длина пути %.1f мм при периметре %.1f + обход углов <= %.1f %s"
                 % ("верх" if side == "top" else "низ", L_path, L_ring, limit,
                    "OK" if L_path <= limit * 1.02 + 1.0 else "!!! ЭКВИДИСТАНТ САМОПЕРЕСЕКАЕТСЯ"))
        if L_path > limit * 1.02 + 1.0:
            rep.ok = False

    if verify_heightmap is not None:
        verify_heightmap(rep, design, plan, pockets, files, res)
    else:
        rep.section("КОНТРОЛЬ ПОКРЫТИЯ (сетка %.1f мм; \"недоступных\" узлов - острые рожки карманов,"
                    " туда фреза не входит по геометрии, там дерево остаётся)" % cfg.coverage_step)
        tot_m = 0
        if g_rough is not None and tr:
            for pk in pockets:
                t, m, hd, w = analytic.coverage_check(pk, g_rough.segs, tr['dia'] / 2.0, cfg.wall_allow + 0.010, cfg.coverage_step)
                rep.line("  черновой %-3s: узлов %5d, не снято %d (из них доступных фрезе %d, остаток %.2f мм) %s"
                         % (pk.fid, t, m, hd, w, "OK" if hd == 0 else ("норма: %.2f мм доберёт чистовая" % w
                                                                     if w <= 2.0 * cfg.wall_allow else "!!! ДЫРА В ТРАЕКТОРИИ")))
                tot_m += hd if w > 2.0 * cfg.wall_allow else 0
        if g_fin is not None and tf:
            for pk in pockets:
                t, m, hd, w = analytic.coverage_check(pk, g_fin.segs, tf['dia'] / 2.0, 0.0, cfg.coverage_step)
                rep.line("  чистовой %-3s: узлов %5d, не снято %d (из них доступных фрезе %d, остаток %.2f мм) %s"
                         % (pk.fid, t, m, hd, w, "OK" if hd == 0 else "!!! ДЫРА В ТРАЕКТОРИИ"))
                tot_m += hd
        if tot_m:
            rep.ok = False

    # -------------------------------------------------------------------- файлы ---
    tmp_dir = run_dir.rstrip("/\\") + ".tmp"
    if os.path.isdir(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(os.path.join(tmp_dir, "nc"))
    rep.section("ФАЙЛЫ И ОЦЕНКА ВРЕМЕНИ (подача + 35% на разгоны/переезды)")
    total = 0.0
    sheet_files = []
    for fn, g, tool, title, side in files:
        c = dict(ctx)
        c["zero"] = masso.zero_note(blank, side)
        if fn.startswith("00"):
            c["zero"] += " (ДО торцовки)"
        text = masso.render(title, tool, c, g)
        with open(os.path.join(tmp_dir, "nc", fn), "w", encoding="utf-8") as f:
            f.write(text)
        mins = g.cut_len / max(tool['feed'], 1.0) * 1.35
        total += mins
        rep.line("  %-36s %6d строк %6.1f КБ  путь %6.1f м  ~%4.0f мин"
                 % (fn, text.count("\n"), len(text.encode("utf-8")) / 1024.0, g.cut_len / 1000.0, mins))
        res.files.append({"name": fn, "size": len(text.encode("utf-8")), "minutes": int(round(mins)), "role": tool["id"]})
        sheet_files.append((fn, g, tool, title, side, mins))
    rep.line("  ИТОГО ~%.0f мин машинного времени (+ смена фрез, настройка, шлифовка)" % total)

    rep.section("ЛИНТЕР G-КОДА (читает записанные .nc)")
    for fn, g, tool, title, side in files:
        probs = lint.check_nc(os.path.join(tmp_dir, "nc", fn), blank, design.thick, cfg.profile_extra, cfg.z_retract)
        rep.line("  %-36s %s" % (fn, "OK" if not probs else "!! " + "; ".join(probs[:3])))
        if probs:
            rep.ok = False

    report = rep.finish()
    res.ok = rep.ok
    res.verdict = rep.verdict
    res.report = report
    with open(os.path.join(tmp_dir, "report.txt"), "w", encoding="utf-8") as f:
        f.write(report)
    with open(os.path.join(tmp_dir, "job_sheet.md"), "w", encoding="utf-8") as f:
        f.write(job_sheet(design, plan, sheet_files, rep.verdict, ctx))
    paths = preview_paths(plan, pockets, design, cfg)
    for side, path, r, d in prof_paths:
        paths.append(('profile', path + [path[0]]))
    with open(os.path.join(tmp_dir, "preview.svg"), "w", encoding="utf-8") as f:
        f.write(topview_svg(design, pockets, paths))
    if stl_path and os.path.isfile(stl_path):
        shutil.copyfile(stl_path, os.path.join(tmp_dir, "model.stl"))
    if res.heightmap is not None:
        res.heightmap.save(os.path.join(tmp_dir, "machined.bin"))
    meta = {"boardcam": VERSION, "stamp": stamp, "job": job_name, "verdict": rep.verdict, "ok": rep.ok,
            "files": res.files, "seconds": round(time.time() - t_start, 1),
            "design": design.to_dict(), "plan": plan.to_dict()}
    with open(os.path.join(tmp_dir, "design.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    zip_run(tmp_dir)
    if os.path.isdir(run_dir):
        shutil.rmtree(run_dir)
    os.rename(tmp_dir, run_dir)
    res.dir = run_dir
    return res


# ------------------------------------------------------------------ оркестрация ---

def project_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def build_design(root, shape, preset=None, overrides=None, openscad=None, want_stl=True):
    """Фигура shapes/<shape>.scad + набор + переопределения -> (Design, BuildResult)."""
    from ..scad import runner
    script = os.path.join(root, "shapes", shape + ".scad")
    if not os.path.isfile(script):
        raise runner.OpenScadError("нет файла фигуры %s" % script)
    osc = openscad or runner.OpenScad()
    params = runner.merged_params(script, preset, overrides)
    res = runner.build(script, params, os.path.join(root, "out", ".cache"), osc, want_stl=want_stl)
    design = runner.design_from_build(res, script, preset, params, osc)
    design.source["shape_file"] = os.path.relpath(script, root)
    return design, res


def design_for_job(job, root, lib, openscad=None, want_stl=True):
    """-> (Design, путь к STL или None). Фигура из OpenSCAD либо восстановление из STL (mesh)."""
    if job.get("mesh"):
        from ..design.from_mesh import from_mesh
        stl = os.path.join(root, job["mesh"])
        if not os.path.isfile(stl):
            raise ValueError("нет файла %s" % stl)
        blank = None
        b = (job.get("options") or {}).get("blank")
        if b:
            from ..design.model import Blank
            blank = Blank(b[0], b[1], b[2])
        design = from_mesh(stl, pitch=float((job.get("options") or {}).get("mesh_pitch", 0.5)), blank=blank, library=lib)
        return design, stl
    design, bres = build_design(root, job["shape"], job.get("preset"), job.get("overrides"), openscad, want_stl=want_stl)
    return design, bres.stl_path


def run_job(job, root, lib, out_root=None, openscad=None, heightmap=True, stamp=None):
    """Задание -> (design, plan, RunResult|None). RunResult=None при отказах плана."""
    from ..selection import rules
    design, stl_path = design_for_job(job, root, lib, openscad)
    plan = rules.plan(design, lib, job.get("material"), job.get("tools"), job.get("options"))
    if not plan.ok:
        return design, plan, None
    out_root = out_root or os.path.join(root, "out")
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    run_dir = os.path.join(out_root, job["name"], stamp)
    hm = None
    if heightmap and stl_path:
        import functools
        from ..verify.heightmap import verify_run
        hm = functools.partial(verify_run, stl_path=stl_path)
    res = generate(design, plan, lib, run_dir, job_name=job["name"], stl_path=stl_path,
                   verify_heightmap=hm, stamp=stamp)
    return design, plan, res
