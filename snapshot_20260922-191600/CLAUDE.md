# woodworking — project notes for Claude

Parametric CAM for wooden objects (today: round pinwheel serving boards, RU **менажница-«вертушка»**,
and a rounded-rectangle tray) machined on a 3-axis router. The shape is designed in **OpenSCAD**
(Customizer panel, presets on disk); the Python package **`boardcam/`** reads the shape's
description and geometry from OpenSCAD, chooses bits from the user's library, builds toolpaths,
verifies them (analytic checks + heightmap against the STL + G-code linter) and writes **MASSO G3**
G-code for an **Onefinity Elite 2 Woodworker** with a **Makita RT0701C**. Everything is in
**millimetres**. Standard library only; OpenSCAD is an external program invoked by subprocess.

The project's own language is Russian (comments, UI, reports, job sheets). The knowledge base in
`docs/` is in English with the Russian terms kept verbatim; see `docs/README.md`.
`DESIGN.md` is the design reference, `IMPLEMENTATION.md` records how it was built and what was found.

## Layout

| path | what |
|---|---|
| `shapes/<name>.scad`, `shapes/<name>.json` | shape scripts with Customizer annotations + OpenSCAD preset files (the design files). `pinwheel`, `tray`. |
| `boardcam/` | the package: `scad/` (runner, SVG, echo, STL), `design/` (model, `from_mesh`), `library/` (tools/materials/machine), `selection/` (bit choice, refusals), `geometry/`, `cam/` (pocket, ops, tabs), `post/` (MASSO), `verify/` (analytic, heightmap, lint, report), `preview/`, `jobs/` (run, job file, job sheet, zip), `server.py`, `sweep.py`, `__main__.py`. |
| `data/tools.json`, `materials.json`, `machine.json` | the user's library. Edited by CLI, page or hand. |
| `jobs/<name>.json` | jobs: shape + preset (+ overrides) + material + tool overrides + options. Or `mesh` = STL path. |
| `ui/` | offline page (vanilla JS, no deps): jobs, library, runs, WebGL viewer. |
| `out/<job>/<stamp>/` | runs (generated, **not committed**; add `out/` to `.gitignore`). `out/.cache/` = OpenSCAD render cache. |
| `board_v3/*.md` | the previous single-file generator's docs, kept as history; its code was removed in favour of `boardcam/`. |
| `docs/` | knowledge base (read first). |

## Commands

```bash
python3 -m boardcam doctor                              # OpenSCAD found? library valid? shapes and presets
python3 -m boardcam build pinwheel --preset spiral-3    # render + parse the shape (≈1 s, cached)
python3 -m boardcam plan jobs/spiral-3-maple.json       # bit selection and refusals, no G-code (≈5–10 s)
python3 -m boardcam generate jobs/spiral-3-maple.json [--out DIR]   # full run (10–45 s) → out/<job>/<stamp>/
python3 -m boardcam sweep pinwheel --samples 20         # every Customizer extreme + random combos: no exceptions allowed
python3 -m boardcam serve [8000]                        # http://127.0.0.1:8000
python3 -m boardcam library list                        # tools / materials / machine
```

OpenSCAD must be installed (`brew install --cask openscad@snapshot` on macOS; a 2024+ snapshot with
the Manifold backend is strongly recommended) or pointed to with `BOARDCAM_OPENSCAD=/path/to/openscad`.
Without it every command that needs a shape refuses with a clear message.

## Definition of done (project-specific)

Anything touching Python or a `.scad` must end with `generate` for **every job in `jobs/`** ending in

```
ИТОГ: ГЕОМЕТРИЯ И ТРАЕКТОРИИ В ПОРЯДКЕ
```

with every `.nc` `OK` in `ЛИНТЕР G-КОДА` and `зарезов нет` in `КОНТРОЛЬ ПО КАРТЕ ВЫСОТ`, plus
`sweep` for every shape with `исключений 0`. `ЕСТЬ ЗАМЕЧАНИЯ` means not done. Fix the cause;
**never loosen the checks** (clearance tolerances `-0.05/-0.25`, `gouge_tol 0.10`, the
`check_nc` bounds, the profile self-intersection test, `WALL_ALLOW`/`FLOOR_ALLOW`). That is
silencing an alarm, not a fix. Use `--out <scratch dir>` so runs do not land in the tree.

For `server.py` changes: start it on a scratch copy (`--root`), `curl` every endpoint you touched,
and re-check that `--path-as-is '/runs/../../etc/passwd'` (and the `/ui/..` and `/nc/..` variants)
return 404.

## Red lines

- This is not a test harness: a geometry or toolpath error ruins a real blank. `cam/pocket.py`,
  `cam/ops.py`, `cam/tabs.py`, `geometry/offset.py`, `verify/*`, `selection/rules.py` are
  safety-relevant: change them only when the task requires it and explain the geometric reasoning
  in the commit and in `docs/geometry.md` / `docs/gcode-safety.md`.
- Standard library only. No pip, no npm, no CDN, no web fonts. Everything runs offline. The only
  external program is `openscad`. Vendoring a JS library needs the user's approval first.
- Point edits. No whole-file reformatting, no renaming existing functions, no "while I'm here".
- Neither Whiteside 1372 (bowl & tray) nor 1406 (round nose) can do an outer edge roundover.
  Do not write text, code or UI that says otherwise.
- Bump `VERSION` in `boardcam/__init__.py` (patch digit) on every functional change; it is stamped
  into every `.nc` header, the report, `design.json` and the page.
- Shapes must keep the echo contract (`DESIGN.md §4.2`); a shape that changes geometry without
  changing its echo is caught by the heightmap check, not by a reviewer.

## Where to read more

- `docs/domain.md` — product, machine, bits, woods, shop workflow, glossary.
- `docs/architecture.md` — package layers, data flow of a run, server, page.
- `docs/geometry.md` — OpenSCAD regions, pockets, rasters (polar/linear), contour runs, profile offset.
- `docs/gcode-safety.md` — operations, fillet-aware roughing, tabs, flip, linter, heightmap, all `ok=False` conditions.
- `docs/parameters.md` — Customizer parameters, library schemas, job schema, machine settings.
- `docs/status.md` — versions, what is done, decisions, non-goals.
- `docs/gotchas.md` — traps (read before your first edit).
- `docs/landscape.md`, `docs/options.md` — the market and the architecture options that led to `DESIGN.md`.
