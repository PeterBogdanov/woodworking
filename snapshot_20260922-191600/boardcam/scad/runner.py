# -*- coding: utf-8 -*-
"""Запуск OpenSCAD: поиск исполняемого файла, экспорт STL и плоских SVG, чтение echo, кэш.

Параметры передаются ВРЕМЕННЫМ файлом набора (-p/-P), а не -D: в OpenSCAD набор
применяется после разбора текста и перекрыл бы значения из -D. Через -D идёт
только export (его в наборах не бывает, а из набора скрытый параметр не
применяется - проверено на 2026.09.18).
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile

from .echo import parse_echo, EchoError
from .svg import parse_rings, group_regions, SvgError

CANDIDATES = [
    "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD",
    os.path.expanduser("~/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD"),
    "/opt/homebrew/bin/openscad",
    "/usr/local/bin/openscad",
    "/usr/bin/openscad",
    "/snap/bin/openscad",
    "C:\\Program Files\\OpenSCAD\\openscad.exe",
]


class OpenScadMissing(RuntimeError):
    pass


class OpenScadError(RuntimeError):
    pass


def find_openscad():
    env = os.environ.get("BOARDCAM_OPENSCAD")
    if env and os.path.isfile(env) and os.access(env, os.X_OK):
        return env
    p = shutil.which("openscad")
    if p:
        return p
    for c in CANDIDATES:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


MISSING_TEXT = ("OpenSCAD не найден. Установите его (macOS: brew install --cask openscad@snapshot; "
                "Linux: пакет openscad или AppImage с openscad.org) или укажите путь к исполняемому "
                "файлу в переменной окружения BOARDCAM_OPENSCAD.")


class OpenScad(object):
    def __init__(self, path=None):
        self.path = path or find_openscad()
        if not self.path:
            raise OpenScadMissing(MISSING_TEXT)
        self.version = self._version()
        self.manifold = "Manifold" in self._help()

    def _version(self):
        p = subprocess.run([self.path, "--version"], capture_output=True, text=True)
        m = re.search(r"OpenSCAD version (\S+)", (p.stdout or "") + (p.stderr or ""))
        return m.group(1) if m else "?"

    def _help(self):
        p = subprocess.run([self.path, "--help"], capture_output=True, text=True)
        return (p.stdout or "") + (p.stderr or "")

    def cmd(self, script, out, preset_file, export=None, fmt=None, backend=True):
        c = [self.path, "-o", out]
        if fmt:
            c += ["--export-format", fmt]
        if out.lower().endswith(".stl"):
            if backend and self.manifold:
                c += ["--backend=Manifold"]
            # точный след фрезы (minkowski) - только с Manifold; на CGAL это минуты
            c += ["-D", 'floor_style="%s"' % ("exact" if self.manifold else "steps")]
        if export is not None:
            c += ["-D", 'export="%s"' % export]
        c += ["-p", preset_file, "-P", "boardcam", script]
        return c


def read_presets(path):
    """Файл наборов OpenSCAD -> {имя: {параметр: строка}}."""
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return d.get("parameterSets", {})


def write_presets(path, sets):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"fileFormatVersion": "1", "parameterSets": sets}, f, ensure_ascii=False, indent=1)


def to_scad_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v) if isinstance(v, float) else str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(to_scad_value(x) for x in v) + "]"
    return str(v)


def merged_params(script, preset=None, overrides=None):
    """Значения набора preset из <script>.json плюс overrides -> {имя: строка}."""
    params = {}
    if preset:
        sets = read_presets(os.path.splitext(script)[0] + ".json")
        if preset not in sets:
            raise OpenScadError("в %s нет набора параметров %r (есть: %s)"
                                % (os.path.basename(os.path.splitext(script)[0] + ".json"), preset,
                                   ", ".join(sorted(sets)) or "ни одного"))
        params.update({k: str(v) for k, v in sets[preset].items()})
    for k, v in (overrides or {}).items():
        params[str(k)] = to_scad_value(v)
    return params


class BuildResult(object):
    def __init__(self):
        self.echo = None
        self.regions = {}
        self.stl_path = None
        self.log = []
        self.errors = []
        self.timings = {}
        self.cache_key = None
        self.cached = False


def _hash(script, params, version):
    h = hashlib.sha256()
    with open(script, "rb") as f:
        h.update(f.read())
    h.update(json.dumps(params, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    h.update(version.encode("utf-8"))
    return h.hexdigest()[:24]


def build(script, params, cache_dir, openscad=None, want_stl=True, jobs=None):
    """Отрисовать фигуру: echo (описание), SVG областей, STL. Возвращает BuildResult."""
    import time
    osc = openscad or OpenScad()
    res = BuildResult()
    key = _hash(script, params, osc.version)
    res.cache_key = key
    cdir = os.path.join(cache_dir, key)
    meta = os.path.join(cdir, "meta.json")
    if os.path.isfile(meta):
        with open(meta, encoding="utf-8") as f:
            m = json.load(f)
        if (not want_stl) or m.get("stl"):
            res.echo = m["echo"]
            res.log = m.get("log", [])
            res.errors = m.get("errors", [])
            empty = {e.get("ref") for e in res.errors}
            for ref in m.get("refs", []):
                svg = os.path.join(cdir, _svg_name(ref))
                res.regions[ref] = [] if (ref in empty or not os.path.isfile(svg)) else _load_regions(svg)
            if m.get("stl"):
                res.stl_path = os.path.join(cdir, "model.stl")
            res.cached = True
            return res
    os.makedirs(cdir, exist_ok=True)
    preset_file = os.path.join(cdir, "params.json")
    write_presets(preset_file, {"boardcam": params})

    def run(cmd):
        p = subprocess.run(cmd, capture_output=True, text=True)
        return p.returncode, (p.stdout or "") + (p.stderr or "")

    # 1) быстрый экспорт контура ради echo (echo печатается при любом export)
    t0 = time.time()
    code, out = run(osc.cmd(script, os.path.join(cdir, "outline.svg"), preset_file, export="outline"))
    res.timings["echo"] = time.time() - t0
    try:
        echo, other = parse_echo(out)
    except EchoError as e:
        raise OpenScadError("описание фигуры не читается: %s" % e)
    res.log = other
    if echo is None:
        raise OpenScadError("фигура не напечатала boardcam_design; вывод OpenSCAD:\n%s" % out[-2000:])
    res.echo = echo
    from ..design.model import geometry_refs
    refs = geometry_refs(echo)
    has_error = any(isinstance(m, list) and m and m[0] == "error" for m in (echo.get("messages") or []))
    if has_error:
        _save_meta(meta, res, [], False)
        return res
    # 2) параллельно: области и STL
    t0 = time.time()
    procs = []
    for ref in refs:
        out_svg = os.path.join(cdir, _svg_name(ref))
        if ref == "outline" and os.path.isfile(out_svg) and code == 0:
            continue
        procs.append((ref, subprocess.Popen(osc.cmd(script, out_svg, preset_file, export=ref),
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)))
    stl_proc = None
    if want_stl:
        stl_proc = subprocess.Popen(osc.cmd(script, os.path.join(cdir, "model.stl"), preset_file,
                                            export=None, fmt="binstl"),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for ref, p in procs:
        o, e = p.communicate()
        if p.returncode != 0:
            msg = (o + e).strip().splitlines()
            tail = msg[-1] if msg else "?"
            if "empty" in tail.lower() or "not a 2d object" in tail.lower():
                # пустая область: после offset() от кармана ничего не осталось
                res.errors.append({"ref": ref, "code": "FEATURE_EMPTY", "text": tail})
                res.regions[ref] = []
            else:
                raise OpenScadError("OpenSCAD не смог отрисовать %r: %s" % (ref, tail))
    if code == 0 and "outline" in refs:
        pass
    for ref in refs:
        if ref in res.regions:
            continue
        res.regions[ref] = _load_regions(os.path.join(cdir, _svg_name(ref)))
    res.timings["svg"] = time.time() - t0
    if stl_proc is not None:
        o, e = stl_proc.communicate()
        res.timings["stl"] = time.time() - t0
        if stl_proc.returncode != 0:
            raise OpenScadError("OpenSCAD не смог отрисовать 3-D модель: %s" % (o + e).strip()[-800:])
        res.stl_path = os.path.join(cdir, "model.stl")
    _save_meta(meta, res, refs, want_stl)
    return res


def _svg_name(ref):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", ref) + ".svg"


def _load_regions(path):
    try:
        with open(path, encoding="utf-8") as f:
            return group_regions(parse_rings(f.read()))
    except SvgError as e:
        raise OpenScadError("SVG %s: %s" % (os.path.basename(path), e))


def _save_meta(path, res, refs, stl):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"echo": res.echo, "refs": refs, "stl": bool(stl and res.stl_path), "log": res.log,
                   "errors": res.errors, "timings": res.timings}, f, ensure_ascii=False)


def design_from_build(res, script, preset, params, osc):
    """BuildResult -> Design (с источником)."""
    from ..design.model import from_echo, Message
    src = {"script": os.path.relpath(script) if not os.path.isabs(script) else script,
           "preset": preset, "params": params, "openscad_version": osc.version,
           "cache_key": res.cache_key}
    design = from_echo(res.echo, res.regions, src)   # пустые области -> FEATURE_EMPTY уже там
    return design
