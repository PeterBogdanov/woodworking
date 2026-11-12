# -*- coding: utf-8 -*-
"""Маленький локальный сервер: JSON API + статическая страница ui/.

Слушает только 127.0.0.1. Однопоточный: генерация - блокирующий запрос (решение
из PLAN.md board_v3). Ошибки уходят клиенту как JSON {"error": ...} без трейсбека.

  GET  /                          страница ui/index.html ({{VERSION}} подставляется)
  GET  /ui/<file>                 статика из ui/
  GET  /api/doctor                OpenSCAD, версия, фигуры, наборы
  GET  /api/library               {tools, materials, machine}
  POST /api/library/tools         запись фрезы (добавить/заменить)      -> {ok, errors}
  POST /api/library/materials     запись материала
  POST /api/library/machine       весь объект станка
  DELETE /api/library/<kind>/<id> удалить (отказ, если запись используется заданием)
  GET  /api/shapes                [{name, presets, params}]
  GET  /api/jobs, /api/jobs/<name>; POST /api/jobs (сохранить); DELETE /api/jobs/<name>
  POST /api/plan                  тело = задание -> {design, plan}
  POST /api/generate              тело = задание -> {ok, verdict, report, files, run}
  GET  /api/runs                  список прогонов (новые первыми)
  GET  /api/runs/<job>/<stamp>    design.json прогона
  GET  /runs/<job>/<stamp>/<file> файлы прогона (nc/*.nc, report.txt, job_sheet.md, preview.svg,
                                  model.stl, machined.bin, design.json, run.zip)
  GET  /api/preview.svg?shape=&preset=&<param>=...   быстрый вид сверху без траекторий
"""

import http.server
import io
import json
import os
import re
import sys
import time
import traceback
import urllib.parse

from . import VERSION
from .library import store
from .jobs import jobfile
from .jobs import run as runmod

SAFE = re.compile(r"^[A-Za-z0-9_.\-]{1,80}$")
RUN_FILES = re.compile(r"^(nc/[A-Za-z0-9_.\-]+\.nc|report\.txt|job_sheet\.md|preview\.svg|model\.stl|machined\.bin|design\.json|run\.zip)$")
UI_EXT = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
          ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}
FILE_TYPES = {".nc": "text/plain; charset=utf-8", ".txt": "text/plain; charset=utf-8", ".md": "text/markdown; charset=utf-8",
              ".svg": "image/svg+xml", ".stl": "application/octet-stream", ".bin": "application/octet-stream",
              ".json": "application/json; charset=utf-8", ".zip": "application/zip"}


class ApiError(Exception):
    def __init__(self, code, text):
        Exception.__init__(self, text)
        self.code = code


def make_handler(root):
    ui_dir = os.path.join(root, "ui")
    out_dir = os.path.join(root, "out")
    jobs_dir = os.path.join(root, "jobs")
    data_dir = os.path.join(root, "data")
    shapes_dir = os.path.join(root, "shapes")

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "boardcam/" + VERSION

        def log_message(self, *a):
            pass

        # ---------------------------------------------------------------- helpers
        def _send(self, code, ctype, body, extra=None):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False))

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 4 * 1024 * 1024:
                raise ApiError(413, "слишком большое тело запроса")
            raw = self.rfile.read(n) if n else b""
            if not raw:
                return {}
            try:
                return json.loads(raw.decode("utf-8"))
            except ValueError as e:
                raise ApiError(400, "тело запроса не JSON: %s" % e)

        def _route(self, method):
            parsed = urllib.parse.urlparse(self.path)
            q = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
            path = parsed.path
            parts = [p for p in path.split("/") if p]
            try:
                if any(p in (".", "..") or not SAFE.match(p) for p in parts):
                    raise ApiError(404, "not found")
                self._dispatch(method, path, parts, q)
            except ApiError as e:
                if e.code == 404:
                    self._send(404, "text/plain; charset=utf-8", "not found")
                else:
                    self._json({"error": str(e)}, e.code)
            except Exception as e:      # noqa: BLE001 - любую ошибку показываем клиенту текстом
                print("[boardcam.server] %s %s: %s" % (method, self.path, e), file=sys.stderr)
                traceback.print_exc()
                self._json({"error": "%s: %s" % (type(e).__name__, e)}, 500)

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

        def do_DELETE(self):
            self._route("DELETE")

        # ---------------------------------------------------------------- routes
        def _dispatch(self, method, path, parts, q):
            if method == "GET" and (path == "/" or path == "/index.html"):
                return self._page()
            if method == "GET" and len(parts) == 2 and parts[0] == "ui":
                return self._static(os.path.join(ui_dir, parts[1]), UI_EXT)
            if method == "GET" and parts[:2] == ["api", "doctor"]:
                return self._json(self._doctor())
            if parts[:2] == ["api", "library"]:
                return self._library(method, parts[2:])
            if method == "GET" and parts == ["api", "shapes"]:
                return self._json(self._shapes())
            if parts[:2] == ["api", "jobs"]:
                return self._jobs(method, parts[2:])
            if method == "POST" and parts == ["api", "plan"]:
                return self._plan()
            if method == "POST" and parts == ["api", "generate"]:
                return self._generate()
            if method == "POST" and parts == ["api", "surface"]:
                return self._surface()
            if method == "GET" and parts == ["api", "surface", "download"]:
                return self._surface_download()
            if method == "GET" and parts[:2] == ["api", "runs"]:
                return self._runs(parts[2:])
            if method == "GET" and parts[:1] == ["runs"] and len(parts) in (4, 5):
                return self._run_file(parts[1:])
            if method == "GET" and parts == ["api", "preview.svg"]:
                return self._preview(q)
            raise ApiError(404, "not found")

        def _page(self):
            p = os.path.join(ui_dir, "index.html")
            if not os.path.isfile(p):
                raise ApiError(404, "not found")
            with io.open(p, encoding="utf-8") as f:
                page = f.read().replace("{{VERSION}}", VERSION)
            self._send(200, "text/html; charset=utf-8", page)

        def _static(self, full, types):
            ext = os.path.splitext(full)[1].lower()
            if ext not in types or not os.path.isfile(full):
                raise ApiError(404, "not found")
            with open(full, "rb") as f:
                self._send(200, types[ext], f.read())

        def _lib(self):
            return store.load(data_dir)

        def _doctor(self):
            from .scad import runner
            p = runner.find_openscad()
            osc = None
            if p:
                try:
                    o = runner.OpenScad(p)
                    osc = {"path": p, "version": o.version, "manifold": o.manifold}
                except Exception as e:  # noqa: BLE001
                    osc = {"path": p, "error": str(e)}
            lib_err = None
            try:
                self._lib()
            except Exception as e:  # noqa: BLE001
                lib_err = str(e)
            return {"version": VERSION, "openscad": osc, "openscad_missing": None if osc else runner.MISSING_TEXT,
                    "library_error": lib_err, "shapes": self._shapes(), "root": root}

        def _shapes(self):
            from .scad import runner
            from .sweep import customizer_params
            out = []
            if not os.path.isdir(shapes_dir):
                return out
            for fn in sorted(os.listdir(shapes_dir)):
                if not fn.endswith(".scad"):
                    continue
                name = fn[:-5]
                params = [{"name": n, "default": d, "values": v} for n, d, v in customizer_params(os.path.join(shapes_dir, fn))]
                out.append({"name": name, "file": "shapes/" + fn,
                            "presets": runner.read_presets(os.path.join(shapes_dir, name + ".json")),
                            "params": params})
            return out

        def _library(self, method, rest):
            lib = self._lib()
            if method == "GET" and not rest:
                return self._json({"tools": lib.tools, "materials": lib.materials, "machine": lib.machine})
            if method == "POST" and len(rest) == 1 and rest[0] in ("tools", "materials"):
                errors = store.upsert(lib, rest[0], self._body())
                if not errors:
                    store.save(lib)
                return self._json({"ok": not errors, "errors": errors})
            if method == "POST" and rest == ["machine"]:
                m = self._body()
                errors = store.validate_machine(m)
                if not errors:
                    lib.machine = m
                    store.save(lib)
                return self._json({"ok": not errors, "errors": errors})
            if method == "DELETE" and len(rest) == 2 and rest[0] in ("tools", "materials"):
                errors = store.remove(lib, rest[0], rest[1], jobs_dir)
                if not errors:
                    store.save(lib)
                return self._json({"ok": not errors, "errors": errors})
            raise ApiError(404, "not found")

        def _jobs(self, method, rest):
            if method == "GET" and not rest:
                return self._json(jobfile.list_jobs(jobs_dir))
            if method == "GET" and len(rest) == 1:
                p = os.path.join(jobs_dir, rest[0] + ".json")
                if not os.path.isfile(p):
                    raise ApiError(404, "not found")
                return self._json(jobfile.load_job(p))
            if method == "POST" and not rest:
                try:
                    job = jobfile.validate_job(self._body())
                except jobfile.JobError as e:
                    raise ApiError(400, str(e))
                os.makedirs(jobs_dir, exist_ok=True)
                jobfile.save_job(job, jobs_dir)
                return self._json({"ok": True, "name": job["name"]})
            if method == "DELETE" and len(rest) == 1:
                p = os.path.join(jobs_dir, rest[0] + ".json")
                if not os.path.isfile(p):
                    raise ApiError(404, "not found")
                os.remove(p)
                return self._json({"ok": True})
            raise ApiError(404, "not found")

        def _job_from_body(self):
            body = self._body()
            if set(body.keys()) <= {"name"} and body.get("name"):
                p = os.path.join(jobs_dir, body["name"] + ".json")
                if not os.path.isfile(p):
                    raise ApiError(404, "not found")
                return jobfile.load_job(p)
            try:
                return jobfile.validate_job(body)
            except jobfile.JobError as e:
                raise ApiError(400, str(e))

        def _plan(self):
            from .selection import rules
            job = self._job_from_body()
            lib = self._lib()
            design, _stl = runmod.design_for_job(job, root, lib, want_stl=False)
            plan = rules.plan(design, lib, job.get("material"), job.get("tools"), job.get("options"))
            d = design.to_dict()
            d.pop("outline", None)
            d["pockets"] = [{"id": p.id, "area_cm2": round(p.area / 100.0, 1), "depth": p.depth,
                             "floor_fillet_r": p.floor_fillet_r, "parts": len(p.regions)} for p in design.pockets]
            return self._json({"design": d, "plan": plan.to_dict()})

        def _generate(self):
            job = self._job_from_body()
            lib = self._lib()
            design, plan, res = runmod.run_job(job, root, lib)
            if res is None:
                return self._json({"ok": False, "refused": True, "plan": plan.to_dict(),
                                   "design_messages": [m.to_dict() for m in design.messages]})
            base = "/runs/%s/%s/" % (job["name"], res.stamp)
            files = [dict(f, url=base + "nc/" + f["name"]) for f in res.files]
            return self._json({"ok": res.ok, "verdict": res.verdict, "report": res.report, "files": files,
                               "run": {"job": job["name"], "stamp": res.stamp, "url": base},
                               "plan": plan.to_dict()})

        def _surface(self):
            from .surface import generate, _Blank
            from .post.masso import render
            body = self._body()
            try:
                width = float(body.get("width", 200.0))
                height = float(body.get("height", 200.0))
                depth = float(body.get("depth", 1.0))
                step = float(body.get("step", 0.5))
                overlap = float(body.get("overlap", 0.4))
            except (ValueError, TypeError) as e:
                raise ApiError(400, "Некорректные параметры: %s" % e)

            lib = self._lib()
            tools = lib.tools
            tool_id = body.get("tool")
            tool = None
            if tool_id:
                for t in tools:
                    if t.get("id") == tool_id:
                        tool = t
                        break
            if not tool:
                surf_tools = [t for t in tools if "surface" in t.get("roles", [])]
                tool = surf_tools[0] if surf_tools else (tools[0] if tools else None)
            if not tool:
                tool = {"id": "dummy", "name": "12mm flat endmill", "dia": 12.0, "shank": 12.0,
                        "rpm": 18000, "feed": 2000, "plunge": 500, "ramp": 800}

            machine = lib.machine
            gcode, z_safe = generate(width, height, depth, step, overlap, tool, machine)
            blank = _Blank(width, height, depth)
            ctx = {
                "z_safe": z_safe,
                "blank": blank,
                "machine": machine,
                "shape": "surface",
                "preset": None,
                "job": "surface",
                "stamp": time.strftime("%Y%m%d-%H%M%S"),
                "zero": "X0 Y0 = ЛЕВЫЙ БЛИЖНИЙ УГОЛ заготовки, Z0 = верх",
                "openscad_version": "-",
                "material": "-",
            }
            title = "Торцовка %.0f x %.0f мм, глубина %.1f мм" % (width, height, depth)
            nc_text = render(title, tool, ctx, gcode)

            os.makedirs(out_dir, exist_ok=True)
            out_file = os.path.join(out_dir, "surface.nc")
            with open(out_file, "w", encoding="utf-8") as f:
                f.write(nc_text)

            preview_lines = nc_text.splitlines()[:60]
            return self._json({
                "ok": True,
                "filename": "surface.nc",
                "lines": len(nc_text.splitlines()),
                "size_bytes": len(nc_text.encode("utf-8")),
                "tool": tool["name"],
                "download_url": "/api/surface/download",
                "preview": "\n".join(preview_lines)
            })

        def _surface_download(self):
            out_file = os.path.join(out_dir, "surface.nc")
            if not os.path.isfile(out_file):
                raise ApiError(404, "surface.nc ещё не сгенерирован")
            with open(out_file, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="surface.nc"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _runs(self, rest):
            if not rest:
                out = []
                if os.path.isdir(out_dir):
                    for job in sorted(os.listdir(out_dir)):
                        jd = os.path.join(out_dir, job)
                        if job.startswith(".") or not os.path.isdir(jd) or not SAFE.match(job):
                            continue
                        for stamp in sorted(os.listdir(jd), reverse=True):
                            meta = os.path.join(jd, stamp, "design.json")
                            if not SAFE.match(stamp) or stamp.endswith(".tmp") or not os.path.isfile(meta):
                                continue
                            try:
                                with open(meta, encoding="utf-8") as f:
                                    m = json.load(f)
                            except (OSError, ValueError):
                                continue
                            out.append({"job": job, "stamp": stamp, "verdict": m.get("verdict"), "ok": m.get("ok"),
                                        "files": m.get("files", []), "seconds": m.get("seconds"),
                                        "shape": (m.get("design") or {}).get("shape"),
                                        "preset": ((m.get("design") or {}).get("source") or {}).get("preset"),
                                        "url": "/runs/%s/%s/" % (job, stamp),
                                        "has_stl": os.path.isfile(os.path.join(jd, stamp, "model.stl")),
                                        "has_heightmap": os.path.isfile(os.path.join(jd, stamp, "machined.bin"))})
                out.sort(key=lambda r: r["stamp"], reverse=True)
                return self._json(out)
            if len(rest) == 2:
                meta = os.path.join(out_dir, rest[0], rest[1], "design.json")
                if not os.path.isfile(meta):
                    raise ApiError(404, "not found")
                with open(meta, encoding="utf-8") as f:
                    return self._send(200, "application/json; charset=utf-8", f.read())
            raise ApiError(404, "not found")

        def _run_file(self, parts):
            job, stamp = parts[0], parts[1]
            rel = "/".join(parts[2:])
            if not RUN_FILES.match(rel):
                raise ApiError(404, "not found")
            full = os.path.realpath(os.path.join(out_dir, job, stamp, rel))
            if not full.startswith(os.path.realpath(out_dir) + os.sep) or not os.path.isfile(full):
                raise ApiError(404, "not found")
            ext = os.path.splitext(full)[1].lower()
            with open(full, "rb") as f:
                data = f.read()
            extra = {}
            if ext in (".nc", ".zip"):
                extra["Content-Disposition"] = 'attachment; filename="%s"' % os.path.basename(full)
            self._send(200, FILE_TYPES.get(ext, "application/octet-stream"), data, extra)

        def _preview(self, q):
            from .preview.topview import topview_svg
            from .selection.rules import cam_pockets_for
            shape = q.pop("shape", None)
            preset = q.pop("preset", None) or None
            if not shape or not SAFE.match(shape):
                raise ApiError(400, "нужен параметр shape")
            overrides = {k: v for k, v in q.items() if SAFE.match(k)}
            design, res = runmod.build_design(root, shape, preset, overrides, want_stl=False)
            pockets = [pk for pk, dp in cam_pockets_for(design)]
            self._send(200, "image/svg+xml", topview_svg(design, pockets, []))

    return Handler


def serve(root, port=8000):
    handler = make_handler(root)
    httpd = http.server.HTTPServer(("127.0.0.1", port), handler)
    print("boardcam v%s: http://127.0.0.1:%d/  (Ctrl+C - стоп; корень %s)" % (VERSION, port, root))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
