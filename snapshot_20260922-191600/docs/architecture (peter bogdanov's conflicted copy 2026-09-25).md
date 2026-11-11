# Architecture

One Python package (`boardcam/`, standard library only), shape scripts for OpenSCAD
(`shapes/`), JSON data (`data/`, `jobs/`), a static page (`ui/`). OpenSCAD is the only
external program, run by subprocess. Dependencies point downward only:

```
scad ─► design ◄─ selection ◄─┐
                 ▲            │
   geometry ◄─ cam ◄──────────┼── jobs.run ──► post, verify, preview
   library ◄──────────────────┘        ▲
                                    server / __main__ (thin)
```

No module-level mutable state: a run is a function of (design, plan, library, output dir).

## Layers

| package | modules | does |
|---|---|---|
| `scad/` | `runner.py` | finds `openscad` (`BOARDCAM_OPENSCAD`, PATH, `/Applications/…`), records version and Manifold support; writes the merged parameters as a temporary preset file; runs one export per geometry reference plus the STL in parallel; caches by hash of script + params + version under `out/.cache/<key>/` |
| | `svg.py`, `echo.py`, `stl.py` | SVG paths → rings → `Region`s by containment parity; `ECHO: boardcam_design = […]` → dict (`undef`→`null`); binary/ASCII STL → triangles |
| `design/` | `model.py` | `Design`, `Blank`, `Outline` (circle or polygon), `Pocket` (regions, depth, floor fillet), `Hole`, `Groove`, `Message`; `from_echo()` builds a `Design` from the echo dict + regions, simplifying contours with 5 µm tolerance |
| | `io.py`, `from_mesh.py` | JSON round trip; the secondary entry: STL → z-buffer → components → marching squares → smoothed, biased contours → `Design` with `MESH_*` messages |
| `geometry/` | `polyline.py`, `region.py`, `distance.py`, `offset.py` | arcs, areas, point-in-region, DP simplification; `RingGrid` spatial hash; naive inward offset + `snap_in`; outward offset with round convex joins, snapping and local loop removal |
| `library/` | `store.py` | `data/*.json` load/validate/save, CRUD with referential checks against `jobs/`, feed scaling per material, dial calibration |
| `selection/` | `rules.py`, `messages.py` | `plan(design, lib, material, overrides, options)` → `Plan`: tool per role with a reason, operation list, profile mode, or refusals with Russian sentences (`DESIGN.md §5.4`) |
| `cam/` | `pocket.py` | `Pocket` for toolpaths (region with holes, memoised polar or linear raster, `contour_runs`, `reachable`) |
| | `ops.py`, `tabs.py`, `gcode.py`, `settings.py` | rough (fillet-aware levels), finish, profile (any closed path, tabs by arc length), flatten, groove; `GCode` buffer records every move for the heightmap |
| `post/` | `masso.py` | header (versions, shape, preset, job, stamp, tool, zero, stock, material, controller), preamble |
| `verify/` | `analytic.py`, `heightmap.py`, `lint.py`, `report.py` | clearance checks, profile clearance and self-intersection; STL z-buffer vs stamped toolpaths; `.nc` linter with self-test; report with the verdict strings |
| `preview/` | `topview.py` | SVG top view (outline, pockets, paths per role) |
| `jobs/` | `jobfile.py`, `run.py`, `jobsheet.py`, `package.py` | job schema; `generate()` and `run_job()`; `job_sheet.md`; `run.zip` |
| root | `server.py`, `sweep.py`, `__main__.py` | HTTP JSON API + static page; Customizer-range sweep; CLI |

## Data flow of a run (`jobs.run.run_job`)

```
job.json ──► design_for_job
              ├─ shape: runner.build(script, merged params)
              │     openscad -o outline.svg -D export="outline" -p params.json -P boardcam   → echo + outline
              │     openscad -o pocket_N.svg -D export="pocket:N" …  (parallel)              → regions
              │     openscad -o model.stl --export-format binstl [--backend=Manifold] -D floor_style="exact" …
              │     from_echo(echo, regions) → Design
              └─ mesh: from_mesh(stl) → Design
selection.plan(design, lib, material, tool overrides, options) → Plan (or refusals → stop)
generate(design, plan, lib, run_dir):
   lint.selftest
   for op in plan.ops: GCode(offset) ← ops.op_* (rough, finish, profile top / mirrored bottom, flatten, groove)
   report: ПАРАМЕТРЫ ИЗДЕЛИЯ · ВЫБОР ИНСТРУМЕНТА · ПРОВЕРКИ ГЕОМЕТРИИ · КОНТРОЛЬ ЗАЗОРОВ
           КОНТРОЛЬ ПО КАРТЕ ВЫСОТ (or КОНТРОЛЬ ПОКРЫТИЯ when no STL) · ФАЙЛЫ И ОЦЕНКА ВРЕМЕНИ
           ЛИНТЕР G-КОДА · ИТОГ
   write <run_dir>.tmp/: nc/*.nc (post.render), report.txt, job_sheet.md, preview.svg, model.stl,
                         machined.bin, design.json (design + plan + meta), run.zip → rename to run_dir
```

Coordinates: everything is board-centred (origin = blank centre, Z0 = top of the finished
part). The shift to machine coordinates (corner zero = half the blank) is applied once, in
`GCode.go()`. The flip file uses `design.mirrored_y()` (y → −y, flip around the X axis).
`check_nc` reads the written files, so it works in machine coordinates.

## Server (`server.py`)

`http.server.HTTPServer` on `127.0.0.1`, single-threaded (generate blocks, by decision).
Routes are listed in the module docstring. Safety: every path component must match
`[A-Za-z0-9_.-]{1,80}`, run files are whitelisted by name, the resolved path must stay
under `out/`; failures → JSON `{"error": …}` without traceback; `..` probes → 404.

## Page (`ui/`)

`index.html`, `app.js`, `styles.css`, `viewer.js`, `i18n.js`; Russian or English (dropdown in
the header), light/dark via `prefers-color-scheme`, works from 380 px. Tabs: Задания (job list, editor with preset values
and overrides, material, per-role tool overrides, options, План, Сгенерировать; preview via
`/api/preview.svg` debounced and serialised), Библиотека (tools, materials, machine JSON),
Прогоны (list, verdict, files, report, preview, WebGL viewer of `model.stl` + `machined.bin`
with blank and origin layers).

Language: `i18n.js` holds one dictionary `EN` keyed by the Russian string itself (Russian = the
keys), exposes `t(s)` and, on load, walks the text nodes and `placeholder`/`title`/`alt`
attributes of `index.html`. `app.js` wraps every Russian literal in `t()`; the two verdict
strings of `verify/report.py` are in the dictionary too, so a run's verdict reads in the chosen
language while the server keeps writing Russian to `report.txt` and `job_sheet.md` (those, the
refusal and geometry messages, and the CLI stay Russian). The choice lives in
`localStorage['boardcam.lang']` and switching reloads the page. `python3 ui/check_i18n.py`
fails if a Russian string is missing from the dictionary or is not wrapped in `t()`.

## Outputs and their consumers

| file | producer | consumer |
|---|---|---|
| `out/<job>/<stamp>/nc/*.nc` | `post.render` | MASSO via USB; `verify.lint`; page download |
| `report.txt` | `verify.report` | operator; page `<pre>`; the verdict line is the contract |
| `job_sheet.md` | `jobs.jobsheet` | operator at the machine |
| `design.json` | `jobs.run` | page (runs list), archaeology |
| `model.stl`, `machined.bin` | OpenSCAD / `verify.heightmap` | page viewer |
| `preview.svg` | `preview.topview` | page |
| `run.zip` | `jobs.package` | download |
| `out/.cache/<key>/` | `scad.runner` | next run with the same parameters |
