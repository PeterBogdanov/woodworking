# Parameters, library, jobs

## Shape parameters (Customizer)

The `.scad` file is the schema: every parameter before the first `module`/`function` with a
`// [min:step:max]` or `// [a:Label, …]` annotation. `sweep.customizer_params()` parses them
for the sweep and the page; `/api/shapes` returns them. Values in presets are strings.

### `shapes/pinwheel.scad`

| group | name | default | range | meaning |
|---|---|---|---|---|
| Заготовка | `blank_size` | 430 | 250–800 step 5 | square blank side |
| | `blank_thick` | 25 | 15–60 | stock thickness |
| Изделие | `board_dia` | 406.4 | 250–500 step 0.2 | finished diameter |
| | `thick` | 25 | 15–60 | finished height |
| | `pocket_depth` | 12 | 5–15.5 step 0.5 | pocket depth |
| | `rim_w` | 25 | 10–60 | rim width |
| | `n_pockets` | 3 | 3–8 | compartments |
| Вертушка | `layout` | `spiral` | `spiral` / `spiral_center` / `sectors` | `sectors` forces straight walls; `spiral_center` adds a round centre pocket of radius `hub_r − wall_w` |
| | `sweep_deg` | 200 | 0–260 step 2 | spiral sweep; 0 = straight |
| | `hub_r` | 30 | 15–60 | hub radius (with centre pocket: pocket radius + wall) |
| | `wall_w` | 12 | 6–30 step 0.5 | arc-length wall offset (true thickness is less for spirals; `wall_min` in the echo) |
| | `corner_f` | 14 | 10–25 step 0.5 | in-plan fillet at wall/rim and wall/hub |
| Hidden | `export`, `seg_2d` 0.5, `seg_3d` 2.0, `wall_n` 200, `floor_style` steps, `floor_steps` 12, `bowl_r` 6.35 | | | runner and model detail; `bowl_r` is the floor fillet radius echoed per pocket |

Shape errors (echo `["error", …]`, turned into refusals): `CENTER_TOO_SMALL` (centre pocket
radius < 8), `NO_ROOM` (field − hub < 20 mm), `TOO_DEEP` (floor thinner than 3 mm),
`FEATURE_EMPTY` (a pocket vanished in the fillet offset; detected by the runner).

### `shapes/tray.scad`

`blank_x`, `blank_y`, `blank_thick`, `length`, `width`, `thick`, `corner_r` (outer corners),
`rim_w`, `pocket_depth`, `n_x`, `n_y` (1–4 each), `divider_w`, `pocket_r` (in-plan pocket
corner radius). Errors: `CELL_TOO_SMALL`, `TOO_DEEP`, `CORNER_R`. Outline is a polygon
(`["svg", "outline"]`), so the raster strategy is `linear`.

### Presets

`shapes/pinwheel.json`: `spiral-3`, `spiral-center-5`, `sectors-4` (the three old layouts),
`committed-4` (the parameter set behind the old committed `board_v3/nc`). `shapes/tray.json`:
`tray-3x2`, `tray-1x1`. OpenSCAD writes the same file when you save a preset.

## Echo contract

See `DESIGN.md §4.2`. Implemented feature kinds: `pocket` (id, `["svg", ref]`, depth,
floor fillet r), `hole` (id, centre, dia, through, [depth]) — parsed, not yet machined,
`groove` (id, `["circle", dia]` or `["svg", ref]`, depth, tool corner r). Outline:
`["circle", dia]` or `["svg", "outline"]`. `derived.wall_min` feeds the `WALL_MIN` rule.

## Library (`data/`)

### `tools.json` record

```json
{"id": "whiteside_1372", "title": "Whiteside 1372 (чистовая)", "name": "Whiteside 1372 Bowl & Tray, D19.05 / R6.35",
 "type": "bowl", "dia": 19.05, "corner_r": 6.35, "loc": 15.8, "shank": 6.35,
 "rpm": 16000, "rpm_max": 18000, "feed": 2000.0, "plunge": 450.0, "ramp": 1140.0,
 "stepover": 5.6, "doc": 12.7, "roles": ["finish"], "num": 2, "color": "#0a84ff", "notes": "", "hint": "…UI text…"}
```

`type ∈ flat | bowl | ball | vee | surfacing`; `roles ⊂ rough | finish | profile | groove | surface`;
`feed_contour` optional (used by `cut_contour`); feeds are for the reference material and are
scaled by `material.feed_scale`; `rpm = min(material.rpm, rpm_max)`; `dial` from
`machine.dial` (`rpm = k·dial + b`). Validation: `library/store.py` (`validate_tool`).
Shipped: `molly_mill_250` (rough), `molly_mill_250_profile` (profile, same bit at contour
feeds), `whiteside_1372` (finish, bowl R6.35), `whiteside_1406` (groove, ball R9.525),
`surfacing_38` (surface, not owned).

### `materials.json` record

`{"id", "title", "janka", "feed_scale", "rpm", "dial", "reference", "notes", "hint"}`; exactly one
`reference: true` (maple). Nine woods as before.

### `machine.json`

`name`, `controller`, `router`, `field [812, 812]`, `max_blank 800`, `z_safe 9`, `z_link 3`,
`ramp_len 25`, `sag_rough 0.06`, `sag_finish 0.01`, `profile_extra 1.2`, `wall_allow 0.6`,
`floor_allow 0.6`, `tabs {count 5, len 23, h 4, ramp 13}`, `min_wall 4.0`, `min_floor 3.0`,
`dial {k 5000, b 2000}`, `sim {heightmap_pitch 1.0, coverage_step 3.0, gouge_tol 0.10}`.
Read into `cam.settings.CamSettings`.

## Jobs (`jobs/<name>.json`)

```json
{"schema": 1, "name": "spiral-3-maple", "shape": "pinwheel", "preset": "spiral-3",
 "overrides": {"n_pockets": 4}, "material": "maple", "tools": {"finish": "whiteside_1372"},
 "options": {"flatten": "auto|on|off", "profile_mode": "auto|full|flip", "raster": "auto|polar|linear"},
 "notes": ""}
```

Alternative input: `"mesh": "path/to/part.stl"` instead of `shape`/`preset`, with optional
`options.blank = [x, y, thick]` and `options.mesh_pitch` (0.5). `name` must match
`[A-Za-z0-9_.-]`. `jobs/jobfile.py` validates.

## Selection rules (`selection/rules.py`)

`DESIGN.md §5.4`, plus: `FLOOR_MIN` (depth ≤ thick − min_floor), `ROUGH_FLOOR` note when the
deepest rough level has no room because of the fillet-zone offset, `BLANK_FIT` uses the
outline bbox + 2·(2·r_profile) (the profile tool runs outside the part), `RPM` note when
the material rpm exceeds the tool's `rpm_max`. Overrides per role must exist and carry the
role, or the plan refuses.
