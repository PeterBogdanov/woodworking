# Design: shape configurator on OpenSCAD with a CAM backend library

Status: **chosen 2026-09-22, implemented the same day (phases S–4), see §13.** Supersedes the
earlier custom-UI plan. `boardcam/` is the code; `board_v3/` keeps only the previous
generator's documents. This document is the reference for what was built; §13 lists where the
implementation deviates from §1–§12 and why. Alternatives and why they lost: §10 and
`docs/options.md`. How it was built and what was found on the way: `IMPLEMENTATION.md`.

## 1. Goal

A home-shop tool that turns **a catalogue of specific wooden objects** (round pinwheel
boards today; trays, paddles and similar later) into **machine-ready, verified G-code** for a
3-axis router, with **no drawing and no CAM decisions by the user**. The user:

1. picks a shape and sets its parameters in a stable, widely used 3-D configurator,
2. picks a material and, if they want, overrides the automatically chosen bits,
3. gets `.nc` files, a report with a single verdict, a job sheet and a 3-D preview,
   or a plain-language explanation of why the shape cannot be machined with the tools they own.

Tools and materials are the user's own, editable lists. Designs persist as small files. The
backend is usable as a Python library and CLI without any UI.

## 2. Decisions

| # | decision | consequence |
|---|---|---|
| D1 | Tools and materials are first-class, user-editable | `data/tools.json`, `data/materials.json`; CLI and a small web page for CRUD; designs reference ids; runs snapshot the records |
| D2 | Design persistence without databases | OpenSCAD preset files (`shapes/<shape>.json`) hold shape parameters; `jobs/<name>.json` adds material and tool choices; runs live in `out/` |
| D3 | 3-D previews | OpenSCAD's own viewer while designing; a vendored browser viewer for the machined result |
| D4 | Vendored offline viewer library is acceptable | `ui/vendor/` with license and version pin; a proposal to the user whenever it changes |
| D5 | No test suite yet | gates are the acceptance verdict, output diffs between phases, and a sweep smoke command |
| D6 | Restructure into a package; architecture in a top-level document | this file; package `boardcam/` (placeholder name) |
| **D7** | **Front end is OpenSCAD's Customizer; shapes are `.scad` scripts** | zero UI code for shape editing; shapes carry their own parameter schema; presets are OpenSCAD's format |
| **D8** | **Exchange is a semantic sidecar + exact 2-D contours + STL**, all produced by one OpenSCAD script | no feature recognition on meshes in the main path; the STL is for viewing and for the heightmap check |
| **D9** | **Backend chooses bits automatically from the library and explains failures** | `select/` module with explicit rules and message templates; user overrides per role |
| D10 | Python standard library only, plus the `openscad` executable invoked as a subprocess, plus the vendored viewer | OpenSCAD is installed by the user (Homebrew/apt/installer); the tool refuses to run without it and says so |

Carried over from `board_v3/PLAN.md`: generation is a blocking call, no background jobs. Revoked:
"round outer contour only" — any closed outline is allowed.

## 3. System overview

```
              ┌──────────────── user ────────────────┐
              │  OpenSCAD (Customizer, 3-D view)     │   boardcam serve (small page) / CLI
              │  shapes/pinwheel.scad + presets.json │   library CRUD · jobs · runs · viewer
              └────────────┬─────────────────────────┘
                           │ preset name / -D overrides
                           ▼
   ┌──────────────────────── boardcam.scad.run ───────────────────────────┐
   │  openscad -o model.stl  -p shape.json -P preset shape.scad           │  → STL
   │  openscad -o outline.svg -D 'export="outline"' …                     │  → exact 2-D contours
   │  openscad -o pocket_N.svg -D 'export="pocket:N"' …   (one per feature)│
   │  stderr: ECHO: boardcam_design = [...]                               │  → semantic sidecar
   └───────────────────────────────┬──────────────────────────────────────┘
                                   ▼
                          boardcam.design.Design
                                   │
        ┌──────────────────────────┼───────────────────────────┐
        ▼                          ▼                           ▼
  select: bits per role     cam: toolpaths            verify.analytic: constraints
  (or a refusal with why)   raster · contour · tabs   clearance, wall thickness…
        └──────────────────────────┼───────────────────────────┘
                                   ▼
                       post: MASSO G-code files
                                   ▼
        verify.heightmap (STL vs toolpaths) · verify.lint (.nc files) · report + verdict
                                   ▼
        out/<job>/<stamp>/  nc/ report.txt job_sheet.md model.stl machined.bin design.json
```

Two coordinate systems as today: shapes are modelled **board-centred** (origin at the
blank centre, Z0 = top of the finished part); the machine offset to the blank corner is
applied once, in `post`.

## 4. Shapes as OpenSCAD scripts

### 4.1 File conventions

One file per shape family in `shapes/`, e.g. `shapes/pinwheel.scad`, with:

- **Customizer annotations** for every user parameter: `/* [Group] */` sections, a
  description comment line, and `// [min:step:max]` or `// [a:Label, b:Label]` ranges.
  Units in the label (`мм`, `°`). These are the schema; there is no second copy in Python.
- A hidden section `/* [Hidden] */` with `export = "";` (used by the runner) and constants.
- Pure **functions** for point lists (spirals, arcs) and **modules** for 2-D regions
  (`module pocket_region(i)`, `module outline_region()`), so the same region is used three
  times: extruded into the 3-D model, exported as 2-D SVG, and, where useful, measured.
- In-plan fillets with `offset(r = +f) offset(delta = -f)` (rounds concave corners
  exactly); pocket floors with the bowl radius by `minkowski()` with a sphere or by a
  `rotate_extrude`d profile, so the STL shows what the finishing bit will leave.
- A single `echo(boardcam_design = [...])` at top level with the **semantic sidecar** (§4.2).
- `if (export == "") { model(); } else { region_for(export); }` at the end.

The Customizer dropdowns for material and tool are **not** in the script; those belong to the
job (§6.2), because the backend chooses tools and the library changes without editing shapes.

### 4.2 Semantic sidecar (echo contract)

OpenSCAD prints vectors in JSON-compatible syntax, so the sidecar is an OpenSCAD vector of
`["key", value]` pairs that the runner turns into JSON by wrapping in `{}` after replacing
`undef` with `null`. Schema version 1:

```
boardcam_design = [
  ["schema", 1], ["shape", "pinwheel"], ["variant", "spiral_center"], ["units", "mm"],
  ["blank", [430, 430, 25]], ["origin", "corner"],
  ["thick", 25],
  ["outline", ["circle", 406.4]],            or ["svg", "outline"]
  ["features", [
     ["pocket", 1, ["svg", "pocket:1"], 12, 6.35],    id, geometry ref, depth, floor fillet r
     ["pocket", 2, ["svg", "pocket:2"], 12, 6.35],
     ["hole",   1, [0, 0], 12, true],                  centre, dia, through
     ["groove", 1, ["svg", "groove:1"], 4.8, 9.53]     path ref, depth, tool corner r
  ]],
  ["derived", [["wall_min", 5.5], ["pocket_area_cm2", 296]]],   optional readouts
  ["messages", [["warn", "F_SHRUNK", "fillet 14 → 11.2 mm at hub"]]]   optional
]
```

Numbers are printed with six significant digits (1 µm at board scale); geometry never goes
through the echo, only scalars. Geometry references name an `export` value the runner
renders to SVG. A shape that cannot build a valid region for the given parameters echoes an
`["error", CODE, text]` message and renders nothing; the runner turns that into a refusal.

### 4.3 Runner (`boardcam/scad/`)

- Finds `openscad` (PATH, then common install locations, then `BOARDCAM_OPENSCAD`); records
  its version in every run. Refuses clearly if absent.
- Runs the 3-D export once and one 2-D export per geometry reference, in parallel processes,
  with `--backend=Manifold` when the version supports it. Typical total: 1–3 s.
- Parses the SVG: paths of straight segments (`M/L/Z`), Y axis flipped back, multiple
  subpaths = outer ring plus holes. Arc chord tolerance is controlled by `$fn/$fa/$fs` set
  in the export branch (`$fs = 0.2` for 2-D exports).
- Parses `ECHO: boardcam_design = …` from stderr into `Design`. Any other `ECHO:` lines are
  kept as shape log output.
- Caches all outputs by hash of (script bytes, preset values, `-D` overrides, OpenSCAD version).
- Loads the STL (binary or ASCII) into a triangle list for the heightmap and the viewer.

## 5. Backend library (`boardcam/`)

Python 3.11+, standard library only. Public API:

```python
lib = boardcam.library.load("data/")                        # tools, materials, machine
design = boardcam.scad.build("shapes/pinwheel.scad", preset="party-5")   # or params={...}
plan = boardcam.select.plan(design, lib, material="maple", overrides={"finish": "whiteside_1372"})
#   plan.ok False → plan.refusals: [Message(code, text, feature_id)]
run = boardcam.jobs.generate(design, plan, lib, out_dir="out/party-5/")
#   run.verdict, run.report, run.files, run.messages
```

### 5.1 Package layout

```
boardcam/
  __init__.py, __main__.py      VERSION; CLI: library · build · plan · generate · sweep · serve · doctor
  scad/    runner.py svg.py echo.py stl.py cache.py
  design/  model.py (Design, Blank, Pocket, Hole, Groove, Outline, Message), io.py (JSON), from_mesh.py (heightmap recovery, secondary entry point)
  library/ tools.py materials.py machine.py store.py   (JSON files, validation, CRUD, referential checks)
  select/  rules.py messages.py                          (bit selection, feasibility, explanations)
  geometry/ polyline.py distance.py offset.py            (moved from generate_board.py; fillet search no longer needed)
  cam/     plan.py ops.py raster.py linking.py tabs.py   (moved; profile works on any outline; flip = mirrored design)
  post/    gcode.py masso.py
  verify/  analytic.py heightmap.py lint.py report.py
  preview/ topview.py mesh.py                            (SVG top view; heightmap → mesh/STL/viewer buffer)
  jobs/    run.py jobsheet.py package.py
  server.py                                              (small JSON API + static page)
ui/        index.html app.js styles.css vendor/          (library CRUD, jobs, runs, 3-D viewer)
shapes/    pinwheel.scad pinwheel.json  <next>.scad …    (scripts + OpenSCAD preset files)
data/      tools.json materials.json machine.json
jobs/      <name>.json                                   (preset + material + tool overrides)
out/       <job>/<stamp>/                                (generated; git-ignored)
```

Dependency direction downward only: `scad` → `design`; `select`, `cam`, `verify` know
`design` and `library`; `post` knows only toolpaths; `jobs` orchestrates; `server` is thin.
No module-level mutable state; a run is a pure function of its inputs.

### 5.2 Design model

```
Design: schema, shape, variant, units, blank(size_x, size_y, thick, origin), thick,
        outline: Polygon, features: [Pocket(id, poly: Polygon with holes, depth, floor_fillet_r),
        Hole(id, center, dia, through), Groove(id, path, depth, tool_corner_r)],
        derived: dict, messages: [Message], source: {script, preset, params, openscad_version, hashes}
```

`from_mesh(stl)` is the secondary entry point: z-buffer the triangles at 0.5 mm, cluster
planar levels, extract contours (marching squares), estimate floor fillets from the edge
slope band. It exists so shapes drawn in any CAD can be tried, and it reports every
assumption it had to make. Exactness is lower and the report says so.

### 5.3 Tool library (`data/tools.json`)

```json
{"id": "whiteside_1372", "name": "Whiteside 1372 Bowl & Tray", "type": "bowl",
 "dia": 19.05, "corner_r": 6.35, "loc": 15.8, "shank": 6.35, "rpm": 16000, "rpm_max": 18000,
 "feed": 2000, "plunge": 450, "ramp": 1140, "stepover": 5.6, "doc": 12.7,
 "roles": ["finish"], "color": "#0a84ff", "notes": "…"}
```

`type ∈ {flat, bowl, ball, vee, surfacing}`; `footprint(d)` derived from type, `dia`,
`corner_r` drives both the heightmap stamping and the floor-fillet match. Feeds are for the
reference material. `roles` lists what the tool may be used for (`rough`, `finish`,
`profile`, `groove`, `surface`). Materials: `{"id","title","janka","feed_scale","rpm","dial","reference","notes"}`,
exactly one `reference: true`. Machine: field, `z_safe`, `z_link`, spindle dial calibration,
tab defaults, `profile_extra`, controller id, simulation pitches.

### 5.4 Bit selection and feasibility (`select/`)

Deterministic rules, evaluated per feature and per role, producing a `Plan` (tool per role,
operation list with depths, flip decision) or **refusals** with codes and sentences.

| rule | check | on failure |
|---|---|---|
| FINISH_FILLET | pocket `floor_fillet_r > 0` → a `bowl` tool with `corner_r == floor_fillet_r` (±0.1) and `roles ∋ finish` | "Pocket 2 needs a bowl bit with 6.35 mm corner radius; library has none (closest: …)" |
| FINISH_DEPTH | `depth ≤ finish.loc` (single full-depth pass keeps the fillet correct) | "Pocket depth 16 mm exceeds the 1372's 15.8 mm cutting length" |
| FINISH_FITS | `offset(pocket, −finish.r)` non-empty and covers the floor except concave corners with radius `< finish.r` (reported as leftover, not failure) | "Finishing bit 19 mm cannot enter pocket 3 (narrowest channel 14 mm)" |
| ROUGH_FITS | a `flat` tool with `roles ∋ rough` whose `offset(pocket, −(r + allowance))` is non-empty; prefer the largest that fits | "No roughing bit fits pocket 3's 4 mm channel; smallest flat bit is 6.35 mm" |
| ROUGH_DEPTH | `(depth − floor_allow) ≤ n·doc` with `loc ≥ depth` | as above |
| PROFILE | `flat` tool with `roles ∋ profile`; `need = thick + profile_extra`; full if `need ≤ loc − 1.2`, else flip with `d_top/d_bot` as today; refuse if `d_bot > loc − 1.2` | "Even with a flip the bottom cut needs 21 mm; longest profile bit has 19 mm" |
| WALL_MIN | `design.derived.wall_min ≥ machine.min_wall` (default 4 mm) | "Walls are 2.9 mm thick between pockets 1 and 2; minimum is 4 mm" |
| BLANK | outline bbox + 12 mm ≤ blank; blank ≤ machine field; `blank.thick ≥ thick` (surfacing if greater and a `surfacing` tool exists) | "Board 406 mm does not fit blank 400 mm" |
| RPM | effective rpm ≤ `rpm_max` per tool | adjust down and warn |

Overrides: `{"finish": "<tool id>"}` forces a tool; rules still run and may refuse.
Every refusal names the feature, the number, and the nearest library entry so the user knows
whether to buy a bit, change a parameter, or edit the library.

### 5.5 CAM, post, verification

Moved from `board_v3/generate_board.py` with these changes:

- `cam/plan.py` builds operations from `Plan`; ops take polygons with holes (central pocket
  becomes an ordinary pocket; hub is just material left between polygons).
- `cam/ops.profile()` follows any closed outline; `cam/tabs.py` places tabs by arc length.
  The flip file is generated from the **mirrored design** (`y → −y` in board coordinates).
- Fillet search (`curve_circle_fillet`, radius shrinking) is **removed**: contours come from
  OpenSCAD already filleted. `offset_poly` + `_snap_in` + `contour_runs` stay for tool-centre
  paths.
- `verify/heightmap.py`: **design map from the STL** (z-buffer, 1 mm), machined map from
  toolpaths stamped with the tool footprint. Gouge (machined below design by > 0.10 mm) fails
  the run; leftover inside features is warned with area and depth, split into "tool cannot
  enter" and "toolpath gap". Also catches a shape whose echo and geometry disagree, since
  the STL comes from the geometry and the toolpaths from the echo.
- `verify/analytic.py`: clearance checks as today; static constraints move to `select/`.
- `verify/lint.py`: `check_nc` unchanged in spirit, bounds from the blank in the design.
- `post/masso.py`: headers carry generator version, OpenSCAD version, shape, preset, job,
  run stamp, tool record, material, zero note.

## 6. Persistence

### 6.1 Shape presets — OpenSCAD's own format

`shapes/pinwheel.json`:

```json
{"fileFormatVersion": "1",
 "parameterSets": {
   "party-5": {"board_dia": "406.4", "n_pockets": "5", "sweep_deg": "160", "hub_r": "30", "...": "..."},
   "classic-3": {"...": "..."}}}
```

Written by OpenSCAD when the user saves a preset, read by the CLI (`-p file -P name`) and by
`boardcam`. This is the design file. Shipped presets are committed.

### 6.2 Jobs — what OpenSCAD does not know

`jobs/<name>.json`:

```json
{"schema": 1, "name": "party-5-walnut", "shape": "pinwheel", "preset": "party-5",
 "overrides": {"n_pockets": 6},                 optional -D values on top of the preset
 "material": "walnut",
 "tools": {"finish": "whiteside_1372"},         optional; empty = automatic
 "options": {"flatten": "auto", "juice_groove": false, "profile_mode": "auto"},
 "notes": ""}
```

### 6.3 Runs

`out/<job>/<YYYYMMDD-HHMMSS>/`: `design.json` (the resolved `Design` with inlined tool and
material records, versions, hashes), `nc/*.nc`, `report.txt`, `job_sheet.md`, `model.stl`,
`machined.bin`, `preview.svg`, `run.zip`. Atomic directory creation (write to `.tmp`, rename).

## 7. User interface

- **Shape design: OpenSCAD.** Open `shapes/<shape>.scad`, use the Customizer panel, save a
  preset. The 3-D view shows the finished part including bowl-bit floors.
- **Everything else: CLI or the small page** (`boardcam serve`, `127.0.0.1:8000`):
  - Library: tables for tools, materials, machine with add/edit/delete and referential guards.
  - Jobs: pick shape → preset (read from the preset file) → material → tool overrides
    (defaults show the automatic choice and its reason) → **Generate**. Refusals are shown
    as a list with the sentence per feature.
  - Runs: verdict banner, report, files, zip, job sheet, and a **3-D viewer** (vendored
    three.js as previously agreed, or Online3DViewer which loads STL directly) with layers:
    design STL, machined surface, toolpaths per role, blank and origin marker.
- CLI mirrors every action: `boardcam library …`, `boardcam build shape --preset`,
  `boardcam plan job.json`, `boardcam generate job.json`, `boardcam sweep shape`, `boardcam doctor`.

## 8. Phases and gates

| phase | content | gate |
|---|---|---|
| **S — spike (2 days)** | `pinwheel.scad` with Customizer and echo; runner (STL, SVG, echo); adapter feeding today's engine; heightmap prototype from STL | pocket outlines match `board_v3` within 0.1 mm / 0.01 % area for the three presets (restated: a byte-diff is impossible once fillets come from `offset()`, see §13); Customizer judged usable by the user |
| 1 — package + runner + library | `boardcam/` skeleton; move geometry/cam/post/verify verbatim; `scad/`; `library/` with JSON + CLI CRUD; `select/` rules; `jobs.generate`; delete `board_v3/generate_board.py` | verdict on presets; same `.nc` as spike |
| 2 — persistence + page | jobs files, runs layout, job sheet, zip; `serve` page with library, jobs, runs | curl every endpoint incl. path traversal probe |
| 3 — heightmap + viewer | `verify/heightmap.py` replaces coverage check; `preview/mesh.py`; vendored viewer (user approves files) | presets unchanged; a forced gouge is caught |
| 4 — generalise + second shape | any-outline profile, tabs by length, mirrored flip; first non-round shape in SCAD; `from_mesh` entry point | verdict on the new shape; docs reconciled |

Gates without a test suite (D5): acceptance verdict, `.nc` diff against the previous phase,
`boardcam sweep` (all Customizer ranges, no exceptions, time budget), endpoint smoke.

## 9. Packaging and requirements

- Python 3.11+ standard library.
- OpenSCAD: 2021.01 works; a 2024+ development snapshot with the Manifold backend is
  recommended (minkowski floors render in well under a second instead of tens of seconds).
  `boardcam doctor` prints the detected version and backend.
- Vendored viewer files under `ui/vendor/` with license and version.
- Git: commit `shapes/`, `data/`, `jobs/` examples; ignore `out/` and the runner cache.
- Licensing: OpenSCAD (GPL-2) is invoked as a separate program, not linked; if the WASM
  build is ever vendored for a browser configurator, its source offer obligations apply.

## 10. Alternatives considered and why B

Six architectures were evaluated in `docs/options.md` (scores out of 55):

| option | score | why not |
|---|---|---|
| **B — OpenSCAD Customizer + semantic sidecar + our engine** | **52** | chosen |
| A — custom schema-driven UI + custom engine (the previous plan) | 47 | every UI and viewer line is ours; in-plan fillets needed a slow 400-step search that OpenSCAD's `offset` does exactly and instantly; no reuse of a stable configurator |
| C — mesh-only backend, any CAD in front | 41 | recovering features from triangles is fragile and loses exact arcs; kept as the secondary `from_mesh` entry point |
| D — build123d + STEP + FreeCAD CAM via `ocp-freecad-cam` | 38 | gigabyte-class dependencies, experimental glue layer, parameter UI still ours |
| F — buy MeshCAM ($250) or DeskProto (€145–248) | 36 | manual CAM per part, no bit selection, no verification against intent |
| E — Kiri:Moto as CAM engine | 35 | no bull-nose tool, so the bowl-bit finish pass cannot be expressed; Node runtime; verification still ours |

B wins because it reuses the one stable, widely used parametric configurator that exists,
makes the geometry simpler and exact, keeps the differentiating part (bit selection,
safety verdict, bowl-bit correctness) in a small Python library, and improves stability
(text scripts and tiny preset files under version control, every run self-describing).

## 11. Risks and mitigations

| risk | mitigation |
|---|---|
| Echo and geometry drift apart in a shape script | heightmap check compares STL (geometry) with toolpaths (echo-derived); disagreement fails the run |
| OpenSCAD version differences (export flags, Manifold, SVG format) | `doctor` command; version recorded per run; runner tolerates both `M/L` SVG styles; minimum version pinned in docs |
| Echo number precision (6 significant digits) | scalars only; geometry via SVG; sub-µm never needed |
| Users unfamiliar with OpenSCAD | they only touch the Customizer panel and Save Preset; a one-page guide with screenshots; shapes hide everything else in `[Hidden]` |
| Slow renders with heavy `minkowski` on 2021.01 | recommend snapshot with Manifold; export branch uses coarser `$fn` for the 3-D model than for the 2-D contours |
| Sweep of Customizer ranges produces invalid shapes | shapes echo `error` messages for infeasible combinations; `boardcam sweep` reports them; ranges tightened in annotations |
| GPL obligations if the WASM front end is later vendored | documented in §9; desktop OpenSCAD avoids the issue entirely |

## 12. Open questions

1. Package name (`boardcam` placeholder).
2. Viewer: three.js (already agreed in principle) or Online3DViewer (loads STL directly, one bundle).
3. First non-round shape for phase 4.
4. Minimum wall thickness default and other `machine.json` limits.
5. Whether the small page should also embed an OpenSCAD WASM configurator later, or OpenSCAD
   desktop stays the only design UI.

## 13. Implementation status (2026-09-22)

All five phases landed in one pass; details, measurements and the findings are in
`IMPLEMENTATION.md`. Deviations from the sections above, each with its reason:

| item | design said | built | why |
|---|---|---|---|
| package name | `boardcam` placeholder (Q1) | `boardcam` | kept |
| selection module | `select/` | `boardcam/selection/` | a package directory named `select` shadows the standard-library `select` module for any script run from inside `boardcam/` (breaks `subprocess`) |
| spike gate | `.nc` diff clean except headers | outlines within 0.08 mm / 0.01 % area; rough/finish cut length within ±1 %; verdict `В ПОРЯДКЕ` on every preset | fillets now come from OpenSCAD `offset()` (exact, different discretisation, horns capped instead of the fillet radius shrunk), and two toolpath corrections below change the files on purpose |
| profile | "follows any closed outline" | tool centre **outside** the outline at `r + sag`; self-checks: clearance ≥ `r − 0.05`, no path point inside, path length ≤ perimeter + 2πr (+2 %) | `board_v3` ran the tool at `BOARD_DIA/2 − r`, removing the outer 6.35 mm of the disc (a Ø394 setting produced Ø381.3); an inscribed polygon path undercuts by `sag`, hence `+ sag` |
| roughing | "moved verbatim" | **fillet-aware**: at rough level `z` the wall offset grows by `rc − sqrt(rc² − (rc − h)²)`, `h = depth − z`, inside the floor-fillet zone | the heightmap check showed the flat roughing bit removing up to 3 mm of the wood the R6.35 wall-floor fillet needs; `board_v3` had the `F_extra` hook but never used it |
| open contour runs | "moved verbatim" | tail of an open run: retract to `z_link`, rapid to the point where the ramp reached depth, plunge into the cut, retrace backwards | `board_v3` fed straight from the run's end to its start across the pocket (harmless for the pinwheel's closed runs, cut walls on jagged STL-derived contours) |
| contour chord check | midpoint of each chord | whole chord sampled every 1.2 mm | jagged contours have long chords whose midpoint is fine and whose ends are not |
| floor raster | polar arcs about the centre | polar for circular outlines, **rows along X** otherwise (`options.raster` can force either) | arcs are tangent to straight pocket walls and leave 2 mm scallops between rings (heightmap on the tray) |
| coverage check | replaced by heightmap in phase 3 | replaced; comparison uses the 3×3-cell min/max of the design map | vertical comparison at steep surfaces is ill-conditioned (a step or wall moving by a fraction of a cell reads as millimetres); wall over-cuts finer than a cell are the analytic clearance checks' job |
| STL floor fillet | `minkowski()` or `rotate_extrude` | both in the script: `floor_style = "steps"` (12 stepped offsets, instant F5 preview) for the Customizer; the runner passes `-D floor_style="exact"` (minkowski) for the STL when Manifold is available, ~10 s per render, cached | minkowski in the GUI preview costs 10 s per parameter change; on CGAL it costs minutes |
| parameters to OpenSCAD | `-p preset -P name` plus `-D` overrides | a temporary preset file with the merged values; only `export` and `floor_style` go through `-D` | the preset is applied after the `-D` text is parsed and would win over overrides; a hidden parameter is not applied from a preset (checked on 2026.09.18) |
| SVG contours | as exported | simplified with 5 µm tolerance, micro-edges < 50 µm merged | six-significant-digit coordinates give 16 µm jogs that read as 90° corners and triple the `.nc` size |
| viewer | vendored three.js / Online3DViewer, user approves | `ui/viewer.js`, plain WebGL, no library | approval could not be obtained during the run; zero-dependency viewer keeps the offline promise; vendoring stays a one-line proposal |
| `from_mesh` | z-buffer, level clustering, marching squares, fillet estimate | as designed, plus Chaikin smoothing, contours biased inward (pockets) / outward (outline) by half a cell + tolerance, fillet radius snapped to the nearest bowl tool, a wall band reported as expected leftover | pixel contours are jagged; their outward offset self-intersects and their inward offset breaks the finish contour; biasing errs toward leaving wood |
| groove | job option `juice_groove` | a shape feature (`["groove", …]`) chosen by the shape, tool selected by role `groove` and corner radius | the shape knows whether the rim is wide enough; the library decides the tool |
| `.gitignore` | ignore `out/` | not edited (out of Claude's authority) | the user adds `out/` |

Open questions from §12: Q1 kept `boardcam`; Q2 in-house WebGL (see above); Q3 the second
shape is `shapes/tray.scad` (rounded-rectangle tray with an `n_x × n_y` grid of pockets);
Q4 `machine.json` has `min_wall 4.0`, `min_floor 3.0`, field 812×812, max blank 800; Q5 open.

Known limitations: the bare-STL path leaves a ~1 mm band along walls (reported, not failed)
and can end with a handful of 0.1–0.2 mm "gap" cells on wavy contours, which fails the verdict
honestly; the polar raster is chosen only for circular outlines; one floor-fillet radius per
design; tabs and flip assume a blank symmetric about the X axis.
