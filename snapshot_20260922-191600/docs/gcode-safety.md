# G-code, operations and safety checks

## Conventions in every `.nc` (`post/masso.py`)

- Header: title, `boardcam v4.x | OpenSCAD <version> | единицы: МИЛЛИМЕТРЫ (G21)`, `SHAPE`
  (shape / preset / job / run stamp), `TOOL`, `DIA` + shank, `RPM` with the Makita dial,
  `FEEDS`, `ZERO`, `STOCK`, `WOOD`, `CONTROL`.
- Preamble `G21 G17 G90 G94` / `G54` / `M05` / `S<rpm> M03` / `G0 Z<z_safe>`.
- Footer written by the operation: `G0 Z<z_safe+8>` (`+5` for flatten), `M05`, `M30`.
- Only `G0` and `G1`; arcs are linearised with `sag_rough 0.06` / `sag_finish 0.01`.
- `fnum()`: 3 decimals, trailing zeros stripped, `-0` → `0`.
- X/Y are shifted by half the blank when `origin = corner`; done once in `GCode.go()`.

Z levels, relative to Z0 = top of the *current* face: `z_safe` (9) for rapids between
regions, `z_link` (3) for hops between raster passes, working Z negative.

Rule enforced by the linter: **no XY rapid while Z < −0.02**; every in-material move has `F`.

## Operations (`cam/ops.py`) and files

| file | op | tool role | notes |
|---|---|---|---|
| `00_flatten_top.nc` | `op_flatten` | `surface` | only when the blank is thicker than the part and a surfacing tool exists (or `options.flatten = on`); serpentine, step-over as a feed move; **re-zero Z after it** |
| `01_rough_<tool>.nc` | `op_rough` | `rough` | per pocket, levels of ≤ `doc` down to `depth − floor_allow`; each level: contour at `Rt` then raster; **`Rt = r + wall_allow + fillet_offset(depth − z)`**, i.e. the wall offset grows inside the floor-fillet zone (see `geometry.md`) |
| `02_finish_<tool>.nc` | `op_finish` | `finish` | one Z pass at full depth per pocket: wall contour at `r`, then floor raster with the tool's `stepover` |
| `03_profile_full.nc` | `op_profile` | `profile` | when `need ≤ loc − 1.2`: through cut with tabs |
| `03a_profile_top.nc`, `03b_profile_bottom_FLIP.nc` | `op_profile` | `profile` | otherwise: `d_top = min(loc − 1.2, need − 4)` without tabs, flip around the **X axis**, `d_bot = need − d_top + 2.5` with tabs at `thick − d_top − tab_h`; refusal if `d_bot > loc − 1.2` |
| `05_groove_<tool>.nc` | `op_groove` | `groove` | only if the shape declares a groove feature; 3 passes down |

`need = (thick if flatten else max(thick, blank.thick)) + profile_extra`.

### `cut_contour`

For each run from `contour_runs`: rapid to `z_safe`, rapid to the start, ramp over the
first 8 % of points (`z_link → −z` at `ramp` feed), then feed at `feed_contour` (or
`feed`). Closed runs re-cut the ramp section forward. **Open runs**: retract to `z_link`,
rapid to the point where the ramp reached full depth, plunge into the existing cut, feed
backwards over the ramp section. (`board_v3` fed straight from the run's end to its start;
on a jagged contour that chord crossed walls.)

### `cut_raster` / `cut_raster_linear`

Serpentine over rows (arcs or X-rows). First entry ramps along the first pass over
`ramp_len` (25 mm). Between passes: `link_move` samples the straight link every 1.2 mm;
all samples must be inside with clearance ≥ `Rt − 0.05`, otherwise hop to `z_link`, rapid,
plunge at `plunge` feed. Passes shorter than 0.8 mm are skipped.

### `op_profile`

Path = closed tool-centre path outside the outline (`jobs.run.profile_path`). Levels of
≤ `doc`; each level: `G1 Z z_link` at plunge feed, ramp along the first 5 % of the path,
feed around, return to the start point. On levels deeper than `tab_top`, Z is held at
`−tab_top` within `tab_len/2` of a tab centre and blended over `tab_ramp` on each side
(no vertical dives). Tabs are placed by arc length (`cam/tabs.py`).

## Acceptance: what sets the verdict to `ЕСТЬ ЗАМЕЧАНИЯ`

Before any G-code, `selection.plan` may **refuse** (no run directory is created); the
refusal codes and sentences are in `selection/messages.py` (`FINISH_FILLET`,
`FINISH_DEPTH`, `FINISH_FITS`, `ROUGH_FITS`, `ROUGH_NONE`, `ROUGH_DEPTH`, `PROFILE_NONE`,
`PROFILE_LOC`, `WALL_MIN`, `BLANK_FIT`, `BLANK_FIELD`, `BLANK_THIN`, `FLATTEN_NONE`,
`FLOOR_MIN`, `GROOVE_TOOL`, `GROOVE_DEPTH`, `OVERRIDE_*`, `MATERIAL_UNKNOWN`, `SHAPE_ERROR`).

In the report (`jobs/run.py`), `!!`/`!!!` lines fail the run:

- ПРОВЕРКИ ГЕОМЕТРИИ: `wall_min < machine.min_wall`; a pocket contour with a corner < 60°.
- КОНТРОЛЬ ЗАЗОРОВ: rough raster sample closer than `Rt − 0.05` to the contour on any level
  (`!!! НАРУШЕНИЕ`); finish contour point closer than `r − 0.25` (`!!! ВРЕЗАНИЕ В СТЕНКУ`);
  profile path point or chord midpoint closer than `r − 0.05` to the outline or inside it
  (`!!! КОНТУР РЕЖЕТ ДЕТАЛЬ`); profile path longer than perimeter + 2πr by more than 2 % + 1 mm
  (`!!! ЭКВИДИСТАНТ САМОПЕРЕСЕКАЕТСЯ`).
- КОНТРОЛЬ ПО КАРТЕ ВЫСОТ (`verify/heightmap.py`): design map = z-buffer of the STL at
  `sim.heightmap_pitch` (1 mm); machined map = blank top stamped by every cutting move of the
  top-side operations with the tool footprint (flat, bowl with `corner_r`, ball). A cell inside
  the outline is a **gouge** when machined is below the 3×3-neighbourhood minimum of the design
  by more than `gouge_tol` (0.10) → `!!! ЗАРЕЗ`, run fails. A cell above the 3×3 maximum is
  leftover: inside a pocket it is a `!!! ДЫРА В ТРАЕКТОРИИ` (fails) when `reachable()` says a
  legal tool position covers it, otherwise "фреза не входит" (reported with area and depth,
  does not fail); outside pockets it fails ("замысел ниже верха, а операции на это нет").
  For STL-derived designs a band of `derived.edge_band` along pocket walls is reported as
  expected leftover. The 3×3 rule exists because a vertical comparison at steep surfaces
  reads a sub-cell shift as millimetres; wall over-cuts finer than a cell are the analytic
  checks' job. Files `00` and `03b` are not stamped (other Z frames).
- КОНТРОЛЬ ПОКРЫТИЯ (only when no STL is available): the old grid coverage check with
  `coverage_step` 3 mm; hard misses fail (rough: worst gap > 2·wall_allow).
- ЛИНТЕР G-КОДА (`verify/lint.py`, `check_nc`): `G0` with XY motion while
  `min(z_before, z_after) < −0.02`; `G1` before any positive `F`; X or Y outside
  `[−0.02, blank + 0.02]`; Z below `−(thick + profile_extra + 0.5)`; Z above `z_safe + 15`.
  `lint.selftest` runs first and must catch a synthetic bad file.

Lines starting with `**` are warnings (flip needed, blank thicker than part, shape messages,
rough level empty near the floor). They do not fail the run.

Verdict strings (contract with the page and the operator):
`ИТОГ: ГЕОМЕТРИЯ И ТРАЕКТОРИИ В ПОРЯДКЕ` / `ИТОГ: ЕСТЬ ЗАМЕЧАНИЯ - СМ. ВЫШЕ`.

## Things the checks cannot catch

The verdict proves the toolpaths are *safe with respect to the shape's own intent*. A shape
whose echo and geometry agree but whose intent is silly (a 2 mm wall the shape declared as
fine) passes if it clears `min_wall`. Look at `preview.svg` and the viewer. Feeds and `loc`
values in `data/tools.json` are the user's responsibility; `loc` of the Molly Mill is a
conservative guess until measured.
