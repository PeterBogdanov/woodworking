# Implementation plan for `DESIGN.md`

Written 2026-09-22 before starting; the **Progress log** at the end is updated as phases land.
`DESIGN.md` stays the reference for *what* is built; this file records *how*, in what order,
with which checks, and what was found on the way.

## 0. Constraints discovered before starting

| finding | consequence for the plan |
|---|---|
| `openscad` is not installed on this machine (no PATH binary, no `/Applications/OpenSCAD.app`, Homebrew cask not installed) | D10 makes it a hard requirement. Installing an application system-wide is the user's decision (`brew install --cask openscad@snapshot`, 2026.09.18, Manifold backend). For verification during implementation the official snapshot `.dmg` is downloaded into the session scratch directory, checksum-verified against the cask, and used through `BOARDCAM_OPENSCAD`. Nothing is installed outside the scratch directory. |
| The spike gate says ".nc diffs clean against `board_v3` except headers" | Not achievable byte-for-byte and not desirable: pocket outlines now come from OpenSCAD `offset()` (exact fillets, different discretisation, horns capped instead of fillet radius shrunk), and the profile geometry is corrected (next row). The gate is restated as: same file set, verdict `В ПОРЯДКЕ`, pocket areas within 1 % of `board_v3`, cut length per file within 3 %, heightmap check clean. Recorded in `DESIGN.md §8`. |
| `op_profile` in `board_v3` runs the tool centre at `BOARD_DIA/2 − r_tool`, i.e. the 6.35 mm bit removes the outer 6.35 mm of the board: a Ø394 setting yields a Ø381.3 disc and a 6.35 mm narrower rim (verified on the committed `03a_profile_top.nc`: max X = 408.825 = 215 + 193.825). The `BOARD_DIA + 12 ≤ BLANK_SIZE` check in the same file assumes the tool runs *outside* the disc. | The new `cam.ops.profile` offsets the outline **outward** by the tool radius (tool-centre path outside the part). Profile files therefore differ from `board_v3` deliberately. The blank check becomes `outline bbox + 2·(2·r_profile) ≤ blank`. Reported to the user as a finding. |
| `.gitignore` may not be edited by Claude (`~/CLAUDE.md §2`) | `out/` and the runner cache are written under `out/`; the user adds `out/` to `.gitignore`. Verification runs during implementation write to the scratch directory (`--out`). |
| Vendoring three.js / Online3DViewer needs the user's approval (D4, phase 3 gate) and the user is not available during this run | The 3-D viewer is written in plain WebGL (no library, ~300 lines) so phase 3 can complete offline with zero dependencies. Switching to a vendored library stays a one-line proposal. |
| Neither JetBrains IDE has this project open | CLI file tools are used (allowed fallback). |

## 1. Phase S: spike

Goal: prove the OpenSCAD → sidecar → engine → G-code chain on the pinwheel.

1. `shapes/pinwheel.scad`
   - Customizer groups: Заготовка, Изделие, Вертушка (same parameters and ranges as the
     current UI sliders plus `layout`), `[Hidden]`: `export`, `seg_2d`, `seg_3d`,
     `floor_steps`, `bowl_r`.
   - `function spiral_edge(i, off_w, R_p, r_h, delta, N)` ported 1:1 (arc-length wall offset,
     straight branch for `delta == 0`), `function pocket_raw(i)` = polygon rim arc → wall
     L → hub arc → wall R, `module pocket_region(i)` = `offset(r=f) offset(delta=-f)` of it,
     `module center_region()` for `spiral_center`, `module outline_region()` = circle.
   - 3-D `model()`: cylinder (top at Z0) minus pocket volumes; a pocket volume is a stack of
     `floor_steps` extruded inward offsets following the bowl-bit quarter circle (radius
     `bowl_r` 6.35) plus the straight wall above it. This is the "stepped torus" variant of
     the floor fillet; max radial deviation from the true fillet with 12 steps is 0.014 mm.
   - `echo(boardcam_design = [...])` per §4.2; `messages` gets `error` entries for
     infeasible parameter combinations that can be detected analytically (hub smaller than
     wall, rim wider than radius, fillet larger than half the pocket mouth).
   - `if (export == "") model(); else region_for(export);`
2. `shapes/pinwheel.json` presets `spiral-3`, `spiral-center-5`, `sectors-4` (= the three
   `LAYOUTS` defaults) and `committed-4` (= the parameter set behind the committed
   `board_v3/nc`).
3. `boardcam/scad/`: `runner.py` (find binary, version, temp preset file with the merged
   parameters, one process per export, cache keyed by hash of script + params + version),
   `svg.py` (paths → rings, Y flipped back, rings grouped into regions by containment),
   `echo.py` (`ECHO: boardcam_design = …` → dict; `undef` → `null`), `stl.py` (binary and
   ASCII).
   - Parameters go through a temporary preset file, **not** `-D`, because `-p/-P` is
     applied after `-D` text is parsed and would win over overrides. `export` goes through
     `-D` (it is never in a preset).
4. `boardcam/design/model.py`: `Design`, `Blank`, `Outline`, `Pocket`, `Hole`, `Groove`,
   `Message`; `io.py` JSON round trip.
5. Adapter feeding the moved engine (phase 1 does the move, the spike uses the same code).
6. Comparison script (scratch): pocket areas and outline distances against
   `board_v3.build_pockets()` for the four presets.

Gate S: the four presets build; areas within 1 %; echo parses; STL loads; runner time
per preset recorded.

## 2. Phase 1: package, runner, library, selection, generate

1. `boardcam/geometry/`: `polyline.py` (arc/circle points, area, `point_inside` for rings,
   segment distance), `distance.py` (`SegGrid` spatial hash = `build_grid`/`dist_fast`/
   `build_seg_grid`), `offset.py` (`offset_ring`, `_snap_in`, outward offset with round
   joins for the profile).
2. `boardcam/cam/`: `pocket.py` (`Pocket` with holes: outer + holes, `raster`,
   `raster_intervals`, `contour_runs`), `ops.py` (`rough`, `finish`, `profile`, `flatten`,
   `groove`, `cut_raster`, `cut_contour`, `link_move`), `tabs.py` (tabs by arc length),
   `plan.py` (operation list from `Plan`), `gcode.py` (`GCode` buffer, `fnum`).
   Moved verbatim where possible; every change is listed in the progress log with its
   geometric reason.
3. `boardcam/post/masso.py`: header with generator + OpenSCAD versions, shape, preset,
   job, stamp, tool, material; preamble/footer unchanged.
4. `boardcam/library/`: `store.py` (load/save/validate `data/tools.json`,
   `data/materials.json`, `data/machine.json`), `tools.py`/`materials.py`/`machine.py`
   schemas, referential checks (`roles`, exactly one reference material, ids unique).
5. `boardcam/select/rules.py`: FINISH_FILLET, FINISH_DEPTH, FINISH_FITS, ROUGH_FITS,
   ROUGH_DEPTH, PROFILE, WALL_MIN, BLANK, RPM as in §5.4; `messages.py` Russian templates.
   Output `Plan(tools per role, ops, profile mode, depths, refusals, notes)`.
6. `boardcam/verify/`: `analytic.py` (clearance checks + `coverage_check` moved verbatim,
   used until phase 3), `lint.py` (`check_nc` + linter self-test), `report.py` (Russian
   report; verdict strings unchanged).
7. `boardcam/jobs/run.py`: `generate(design, plan, lib, out_dir)` → run directory; feeds
   scaled from the tool record by material.
8. `boardcam/__main__.py`: `doctor`, `build`, `plan`, `generate`, `library`, `sweep`.
9. Comparison against phase S/`board_v3` baselines; then delete `board_v3/generate_board.py`
   and the files that only exist to drive it (`serve.py`, `interactive.html`, `texts.json`,
   generated `nc/`, `report.txt`, `preview.*`). The author's markdown stays.

Gate 1: `python3 -m boardcam generate jobs/<x>.json` for the four presets ends with
`ИТОГ: ГЕОМЕТРИЯ И ТРАЕКТОРИИ В ПОРЯДКЕ`, every `.nc` `OK` in the linter; areas and cut
lengths within the stated tolerances; `sweep` over Customizer ranges raises no exception.

## 3. Phase 2: persistence and page

1. `jobs/<name>.json` schema §6.2 with validation; `boardcam/jobs/jobsheet.py`
   (`job_sheet.md`: blank, zero, files in order, tools with dial, flip instructions with axis,
   tabs), `package.py` (`run.zip`), atomic run directory.
2. `boardcam/server.py`: `GET /`, `/api/doctor`, `/api/library`, `POST /api/library/<kind>`,
   `DELETE /api/library/<kind>/<id>`, `/api/shapes`, `/api/jobs`, `POST /api/jobs`,
   `POST /api/plan`, `POST /api/generate`, `/api/runs`, `/runs/<job>/<stamp>/<file>`,
   `/runs/<job>/<stamp>/run.zip`; localhost only; 404 for any path escaping `out/`.
3. `ui/index.html`, `ui/app.js`, `ui/styles.css`: tabs Библиотека / Задания / Прогоны.

Gate 2: `curl` every endpoint; `--path-as-is '/runs/../../etc/passwd'` and the `nc`
variant return 404; a job saved from the page generates from the CLI and vice versa.

## 4. Phase 3: heightmap and viewer

1. `boardcam/verify/heightmap.py`: design map from the STL (z-buffer, 1 mm), machined map
   from toolpaths stamped with tool footprints (flat, bowl, ball), gouge > 0.10 mm fails,
   leftover split into "tool cannot enter" and "toolpath gap". Replaces `coverage_check`
   in the report.
2. `boardcam/preview/mesh.py` (heightmap → `machined.bin` float32 grid) and
   `preview/topview.py` (SVG top view as today).
3. `ui/viewer.js`: WebGL, orbit, layers (design STL, machined surface, toolpaths per
   role, blank, origin marker).

Gate 3: presets unchanged in verdict; a toolpath deliberately lowered by 0.3 mm in a
scratch run is reported as a gouge and fails the run.

## 5. Phase 4: generalise and second shape

1. `cam.ops.profile` on any closed outline (outward offset, self-check that every path
   point keeps ≥ `r − 0.05` from the outline), tabs by arc length, flip = mirrored design
   (`y → −y`) with the axis named in the job sheet.
2. `shapes/tray.scad`: rounded rectangle tray with one pocket (first non-round outline).
3. `boardcam/design/from_mesh.py`: z-buffer, level clustering, marching squares, fillet
   estimate; secondary CLI entry `build --stl`.

Gate 4: verdict on the tray; `from_mesh` on the pinwheel STL recovers the pocket count
and areas within 5 %; docs reconciled.

## 6. Documentation

`DESIGN.md` (status per phase, restated gate, decided open questions), `CLAUDE.md`
(layout, commands, definition of done), `docs/*.md` (architecture, geometry, gcode-safety,
parameters, status, gotchas) rewritten for `boardcam/`, `README.md` at the root for the
user (install OpenSCAD, design in the Customizer, run).

## Progress log (2026-09-22)

All phases executed in one session; OpenSCAD 2026.09.18 (Manifold) from a scratch copy,
Python 3.11.9, macOS arm64. Verification runs went to the scratch directory (`--out`).

### Phase S — spike

- `shapes/pinwheel.scad` + `shapes/pinwheel.json`; `boardcam/scad/{runner,svg,echo,stl}.py`.
- Preset application checked empirically: a `[Hidden]` parameter (`export`) is **not** applied
  from a preset, `-D` is; a preset wins over `-D` for shape parameters → merged values go via a
  temporary preset file, `export`/`floor_style` via `-D`.
- SVG format: `<path d="M x,-y L … z">` with Y negated, one path per export; echo format as designed.
- Outline comparison against `board_v3.build_pockets()` (Hausdorff, sampled every 5th point):

  | preset | area Δ | Hausdorff | note |
  |---|---|---|---|
  | spiral-3 | −0.01 % | 0.077 mm | |
  | sectors-4 | −0.01 % | 0.076 mm | |
  | committed-4 | −0.00 % | 0.063 mm | |
  | spiral-center-5 | −2.79 % | 13.0 mm | `board_v3` shrank the 14 mm fillet to 10.9 in five corners; OpenSCAD caps the horn with R14 — the intended change |

- Timings: all 2-D exports in parallel 0.09–0.16 s; stepped STL 0.4–0.7 s; exact (minkowski) STL 9–12 s.

### Phase 1 — package

- `geometry/`, `cam/`, `post/`, `verify/analytic,lint,report`, `library/`, `selection/`,
  `design/`, `jobs/run`, `__main__`; `data/*.json` from `BITS`/`WOODS`/constants + `texts.json`.
- `select/` renamed `selection/` after the stdlib shadowing bug surfaced.
- Cut-length comparison with `board_v3` (same presets, before the roughing change):
  01 −0.6 / −4.0 / +0.1 / −0.5 %, 02 +0.0 / −4.8 / +0.0 / −1.9 %, 03a/03b +3.2 % (tool outside the disc).
- Raster memoised per pocket; contours simplified (5 µm) → `.nc` sizes back to `board_v3` level.

### Phase 3 — heightmap (done before phase 2's page, because it changed the CAM)

- First heightmap run on `spiral-3`: gouge 2.56 mm over 77 cm² along every wall → traced to the
  flat roughing bit cutting into the R6.35 fillet zone (`board_v3` behaviour). Fixed with
  fillet-aware rough levels (`fillet_offset`). Also: 3×3-neighbourhood rule for steep surfaces;
  profile path circumscribed (`+ sag`) after a 0.01 mm undercut showed up as a 17.8 mm gouge on
  two rim cells of the Ø394 preset.
- Tray (phase 4 shape) showed 2.16 mm scallops where polar arcs are tangent to straight walls →
  linear raster strategy for non-circular outlines.

### Phase 2 — page and server

- `server.py` with the routes in its docstring; smoke-tested on a scratch project copy: all
  endpoints 200, four traversal probes (`/runs/../../etc/passwd`, `/runs/x/y/../../../data/…`,
  `/ui/../…`, `/nc/../…`) 404, library validation errors returned as JSON, deletion of a
  material referenced by a job refused.
- `ui/` written by a subagent from the API spec (index.html 198 lines, app.js 926, viewer.js 373,
  styles.css 177; `node --check` clean); verified in Chrome against the server: job list, editor
  with preset values, preview, План result, runs list, report, WebGL viewer with the STL and
  machined surface; no console errors.

### Phase 4 — generalisation

- `tray.scad` (rounded rectangle, `n_x × n_y` pockets): verdict `В ПОРЯДКЕ`, profile clearance
  3.185, heightmap clean after the linear raster.
- `from_mesh`: pixel-boundary contours → marching squares → Chaikin smoothing → DP → biased
  (pockets inward, outline outward by half a cell + tolerance). Findings on the way: the outward
  offset of a jagged contour loops (added snapping + local loop removal + a path-length check),
  `contour_runs` chord check extended from the midpoint to the whole chord, open-run tail
  made safe. Pinwheel STL recovered: areas within 1.7 % (biased), depth 11.95, fillet 6.11 →
  snapped to the 1372's 6.35. The example still ends `ЕСТЬ ЗАМЕЧАНИЯ` with four 0.15 mm cells;
  left as an honest limitation of ±1 mm contours.

### Final verification

| job | verdict | run time | files (rough / finish / 03a / 03b, min) |
|---|---|---|---|
| spiral-3-maple | В ПОРЯДКЕ, зарезов нет, all pockets "снято всё" | 13.1 s | 64 / 10 / 7 / 4 |
| spiral-center-5-walnut | same | 14.6 s | 55 / 8 / 6 / 4 |
| sectors-4-maple | same | 7.5 s | 65 / 10 / 7 / 4 |
| committed-4-maple | same | 10.7 s | 49 / 10 / 7 / 4 |
| tray-3x2-walnut | same | 5.5 s | 42 / 7 / 6 / 4 |

Sweeps: pinwheel 35 variants (default, every parameter at both ends, 12 random) — 0 exceptions,
15 plan refusals, 3 shape errors, worst 7.7 s; tray 37 variants — 0 exceptions.

### Not done / for the user

- Install OpenSCAD system-wide; add `out/` to `.gitignore`; decide on vendoring three.js.
- `hole` features have no operation; one floor-fillet radius per design.
- `board_v3` code and generated outputs removed; its markdown kept.
