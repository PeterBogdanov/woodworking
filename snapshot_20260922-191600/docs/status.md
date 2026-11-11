# Status, history, decisions

Snapshot 2026-09-22. Code: `boardcam/` v4.0.0. Previous generator `board_v3/generate_board.py`
v3.1.3-mm removed the same day (its docs stay in `board_v3/*.md`).

## Version history

| version | change |
|---|---|
| v1 (not in repo) | first inch-based script; see `board_v3/README.md` last table |
| 3.0 – 3.1.3-mm | metric, corner zero, layouts, texts, curve fillets (`board_v3/README.md`, `PLAN.md`) |
| **4.0.0** | `boardcam` package per `DESIGN.md`: OpenSCAD shapes + echo contract, runner with cache, library JSON with CRUD, bit selection with refusals, moved CAM with fillet-aware roughing and outside profile, heightmap verification, job files, runs, job sheet, zip, server + page + WebGL viewer, linear raster, tray shape, STL recovery |

## `DESIGN.md` phases vs reality

| phase | state |
|---|---|
| S spike | done; outlines match `board_v3` within 0.08 mm / 0.01 % area on the three presets; the gate was restated (no byte diff possible), see `DESIGN.md §13` |
| 1 package | done; `board_v3` code deleted |
| 2 persistence + page | done; every endpoint curl-tested, traversal probes 404, page exercised in a browser |
| 3 heightmap + viewer | done; in-house WebGL viewer instead of a vendored library (approval pending) |
| 4 generalise + second shape | done: any-outline profile with self-checks, tabs by length, mirrored flip, `tray.scad`, `from_mesh` |

Verification at the end of the build (details in `IMPLEMENTATION.md`): five jobs
`В ПОРЯДКЕ` with clean heightmaps, sweeps of both shapes with 0 exceptions.

## Findings about the old engine (fixed in `boardcam`, documented so nobody reintroduces them)

1. Profile tool centre at `BOARD_DIA/2 − r`: the disc came out 12.7 mm smaller than set.
2. Flat roughing 0.6 mm from the wall down to 0.6 mm above the floor destroyed the R6.35
   wall-floor fillet zone (up to 3 mm gouge along every wall).
3. Open contour runs fed straight across the pocket from end to start.
4. The coverage check assumed a flat footprint for the bowl bit; scallops it cannot see are
   now caught by the heightmap.

## Decisions taken (do not reopen unless the user does)

- Generate is a blocking request; no background jobs (from `board_v3/PLAN.md`).
- No new dependencies; the only external program is `openscad`.
- Polar raster for circular outlines, linear rows otherwise; forced by `options.raster`.
- Rough levels are fillet-aware; the bowl bit removes the stepped fillet zone.
- Checks are never loosened; the verdict fails honestly (e.g. the STL example).
- The spiral wall's `wall_w` stays an arc-length offset (as the author defined it); the true
  minimum is echoed as `wall_min` and checked against `machine.min_wall`.

## Open items

- Install OpenSCAD system-wide (`brew install --cask openscad@snapshot`) — the build used a
  copy in the session scratch directory.
- Add `out/` to `.gitignore` (the run directory and the OpenSCAD cache live there).
- Approve or decline vendoring three.js; the in-house viewer works without it.
- Measure `loc` of the Molly Mill and the 1372; verify the Makita dial calibration.
- `hole` features are parsed but have no operation yet.
- STL path: contours ±1 mm; expect a wall band and possibly a failed verdict on wavy contours.
- Q5 of `DESIGN.md §12` (embed an OpenSCAD WASM configurator) untouched.

## Non-goals

DXF/AI/CDR/PDF export; photoreal previews (the top view is a flat SVG, the viewer is plain
WebGL); outer edge roundover (impossible with the bit set).
