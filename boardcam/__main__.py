# -*- coding: utf-8 -*-
"""Командная строка boardcam.

  python3 -m boardcam doctor
  python3 -m boardcam build <shape> [--preset NAME] [--set k=v ...]
  python3 -m boardcam plan jobs/<job>.json
  python3 -m boardcam generate jobs/<job>.json [--out DIR] [--no-heightmap]
  python3 -m boardcam library list [tools|materials|machine]
  python3 -m boardcam library add tools '<json>'   |  remove tools <id>
  python3 -m boardcam sweep <shape> [--samples N]
  python3 -m boardcam serve [port]
"""

import argparse
import json
import os
import sys
import time

from . import VERSION
from .jobs import run as runmod


def _root(args):
    return os.path.abspath(args.root) if args.root else runmod.project_root()


def _lib(root):
    from .library import store
    return store.load(os.path.join(root, "data"))


def cmd_doctor(args):
    from .scad import runner
    root = _root(args)
    print("boardcam v%s, Python %s" % (VERSION, sys.version.split()[0]))
    print("корень проекта: %s" % root)
    p = runner.find_openscad()
    if not p:
        print("OpenSCAD: НЕ НАЙДЕН. " + runner.MISSING_TEXT)
        rc = 1
    else:
        osc = runner.OpenScad(p)
        print("OpenSCAD: %s (версия %s, Manifold: %s)" % (p, osc.version, "да" if osc.manifold else "нет - будет медленно"))
        rc = 0
    try:
        lib = _lib(root)
        print("библиотека: %d фрез, %d материалов, станок %s" % (len(lib.tools), len(lib.materials), lib.machine.get("name")))
    except Exception as e:
        print("библиотека: ОШИБКА %s" % e)
        rc = 1
    shapes = [f[:-5] for f in sorted(os.listdir(os.path.join(root, "shapes"))) if f.endswith(".scad")]
    print("фигуры: %s" % (", ".join(shapes) or "нет"))
    for s in shapes:
        sets = runner.read_presets(os.path.join(root, "shapes", s + ".json"))
        print("  %s: наборы %s" % (s, ", ".join(sorted(sets)) or "нет"))
    return rc


def _overrides(pairs):
    out = {}
    for kv in pairs or []:
        if "=" not in kv:
            raise SystemExit("--set ожидает имя=значение, получено %r" % kv)
        k, v = kv.split("=", 1)
        try:
            v = json.loads(v)
        except ValueError:
            pass
        out[k] = v
    return out


def cmd_build(args):
    root = _root(args)
    t0 = time.time()
    if args.stl:
        from .design.from_mesh import from_mesh
        design = from_mesh(args.stl, pitch=args.pitch, library=_lib(root))
        res = None
        print("дизайн из STL %s: %.2f с" % (args.stl, time.time() - t0))
    else:
        design, res = runmod.build_design(root, args.shape, args.preset, _overrides(args.set), want_stl=not args.no_stl)
        print("фигура %s / %s: %.2f с%s" % (design.shape, args.preset or "-", time.time() - t0, " (кэш)" if res.cached else ""))
    print("  заготовка %.0fx%.0fx%.1f, толщина %.1f, контур %s" % (
        design.blank.size_x, design.blank.size_y, design.blank.thick, design.thick,
        "D%.1f" % design.outline.dia if design.outline.kind == "circle" else "многоугольник"))
    for p in design.pockets:
        print("  карман %s: %d област., площадь %.1f см2, глубина %.1f, R дна %.2f" % (
            p.id, len(p.regions), p.area / 100.0, p.depth, p.floor_fillet_r))
    for g in design.grooves:
        print("  жёлоб %s: глубина %.1f, R %.2f" % (g.id, g.depth, g.tool_corner_r))
    for k, v in design.derived.items():
        print("  %s = %s" % (k, v))
    for m in design.messages:
        print("  [%s] %s: %s" % (m.level, m.code, m.text))
    if res is not None and res.stl_path:
        print("  STL: %s (%d байт)" % (res.stl_path, os.path.getsize(res.stl_path)))
    if args.json:
        from .design import io
        io.dump(design, args.json)
        print("  design.json -> %s" % args.json)
    return 1 if design.errors() else 0


def _print_plan(plan):
    if plan.ok:
        print("план: ОК")
        for role, t in plan.tools.items():
            print("  %-8s %s  - %s" % (role, t["id"], plan.reasons.get(role, "")))
        for op in plan.ops:
            print("  файл %s" % op.filename)
    else:
        print("план: ОТКАЗ")
        for m in plan.refusals:
            print("  - [%s] %s" % (m.code, m.text))
    for m in plan.notes:
        print("  * %s" % m.text)


def cmd_plan(args):
    from .jobs.jobfile import load_job
    from .selection import rules
    root = _root(args)
    lib = _lib(root)
    job = load_job(args.job)
    design, _stl = runmod.design_for_job(job, root, lib, want_stl=False)
    plan = rules.plan(design, lib, job.get("material"), job.get("tools"), job.get("options"))
    _print_plan(plan)
    return 0 if plan.ok else 2


def cmd_generate(args):
    from .jobs.jobfile import load_job
    root = _root(args)
    lib = _lib(root)
    job = load_job(args.job)
    t0 = time.time()
    design, plan, res = runmod.run_job(job, root, lib, out_root=args.out, heightmap=not args.no_heightmap)
    if res is None:
        _print_plan(plan)
        return 2
    print(res.report)
    print("каталог прогона: %s   (%.1f с)" % (res.dir, time.time() - t0))
    return 0 if res.ok else 1


def cmd_library(args):
    from .library import store
    root = _root(args)
    lib = _lib(root)
    if args.action == "list":
        what = args.what or "all"
        if what in ("tools", "all"):
            for t in lib.tools:
                print("фреза   %-24s %-6s D%-6.2f R%-5.2f loc %-5.1f roles %s" % (
                    t["id"], t["type"], t["dia"], t.get("corner_r", 0), t["loc"], ",".join(t["roles"])))
        if what in ("materials", "all"):
            for m in lib.materials:
                print("материал %-23s %-28s x%.2f  S%d dial %s%s" % (
                    m["id"], m["title"], m["feed_scale"], m["rpm"], m["dial"], "  (эталон)" if m.get("reference") else ""))
        if what in ("machine", "all"):
            print(json.dumps(lib.machine, ensure_ascii=False, indent=1))
        return 0
    if args.action == "add":
        rec = json.loads(args.what)
        errors = store.upsert(lib, args.kind, rec)
    elif args.action == "remove":
        errors = store.remove(lib, args.kind, args.what, os.path.join(root, "jobs"))
    else:
        raise SystemExit("library: list | add <kind> <json> | remove <kind> <id>")
    if errors:
        print("\n".join(errors))
        return 1
    store.save(lib)
    print("библиотека сохранена")
    return 0


def cmd_sweep(args):
    from .sweep import sweep
    root = _root(args)
    return sweep(root, args.shape, _lib(root), samples=args.samples, material=args.material, budget=args.budget)


def cmd_serve(args):
    from .server import serve
    return serve(_root(args), args.port)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="boardcam", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="корень проекта (где shapes/, data/, jobs/, out/)")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("doctor")
    b = sub.add_parser("build")
    b.add_argument("shape", nargs="?")
    b.add_argument("--stl", help="восстановить дизайн из STL вместо фигуры OpenSCAD")
    b.add_argument("--pitch", type=float, default=0.5, help="шаг карты высот для --stl, мм")
    b.add_argument("--preset")
    b.add_argument("--set", action="append", metavar="k=v")
    b.add_argument("--json")
    b.add_argument("--no-stl", action="store_true")
    p = sub.add_parser("plan")
    p.add_argument("job")
    g = sub.add_parser("generate")
    g.add_argument("job")
    g.add_argument("--out")
    g.add_argument("--no-heightmap", action="store_true")
    l = sub.add_parser("library")
    l.add_argument("action", choices=["list", "add", "remove"])
    l.add_argument("kind", nargs="?")
    l.add_argument("what", nargs="?")
    s = sub.add_parser("sweep")
    s.add_argument("shape")
    s.add_argument("--samples", type=int, default=40)
    s.add_argument("--material")
    s.add_argument("--budget", type=float, default=2.0, help="секунд на построение одного варианта")
    v = sub.add_parser("serve")
    v.add_argument("port", nargs="?", type=int, default=8000)
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 0
    if args.cmd == "library" and args.action == "list":
        args.what = args.kind
    return {"doctor": cmd_doctor, "build": cmd_build, "plan": cmd_plan, "generate": cmd_generate,
            "library": cmd_library, "sweep": cmd_sweep, "serve": cmd_serve}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
