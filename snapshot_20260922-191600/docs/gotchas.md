# Gotchas

## OpenSCAD

- **Preset beats `-D`.** `-p/-P` is applied after the `-D` text is parsed, so an override
  passed with `-D` loses to the preset. The runner writes the merged values into a temporary
  preset file; only `export` and `floor_style` travel by `-D` (a `[Hidden]` parameter is not
  applied from a preset either — checked on 2026.09.18).
- **Empty 2-D export** ends with `Current top level object is not a 2D object.` (or
  `… is empty`), exit code 1. The runner maps both to `FEATURE_EMPTY`.
- **Six significant digits** in SVG and echo. Contours are simplified (5 µm) with micro-edge
  merging (50 µm) in `design.from_echo`; scalars in the echo are fine (1 µm at board scale).
- **`minkowski()` costs ~10 s per render on Manifold and minutes on CGAL.** The script's
  default `floor_style = "steps"` keeps the F5 preview instant; the runner asks for `"exact"`
  only when Manifold is available. The cache (`out/.cache/<hash>/`) keys on script bytes,
  parameters and OpenSCAD version.
- `--backend=Manifold` is passed only for `.stl` output; 2-D exports go through Clipper anyway.

## Geometry and toolpaths

- **A polygon offset inward by `r` then outward by `r` rounds convex corners; a horn narrower
  than `2r` disappears and comes back as a round cap.** That is why the 5-pocket preset differs
  from the old generator (which shrank the fillet radius) by 3 % area.
- **Polar rasters are tangent to straight walls.** Use `linear` for anything that is not a
  disc (automatic when the outline is not a circle).
- **The rough wall offset grows near the floor** (`fillet_offset`). A clearance line in the
  report now says which level was worst; the deepest level runs 3.66 mm + allowance from the
  wall for R6.35 floors. This is not a bug.
- **Naive outward offsets loop at concave notches.** `offset_outward` snaps and removes local
  loops, and the run checks path length against perimeter + 2πr. If that check trips, look at
  the outline, not at the check.
- `snap_in` can move an offset point far along the wall; the full-chord check in
  `contour_runs` is what keeps such chords out of the walls.
- `Region` constructor normalises orientation. Feed it raw rings; do not pre-reverse.

## Heightmap

- Comparison is vertical, so steep surfaces are compared with the 3×3-neighbourhood min/max
  of the design map. Consequences: a wall over-cut narrower than one cell (1 mm) is invisible
  to the heightmap (the analytic clearance checks catch it), and a stepped fillet model passes.
- Only top-side operations in the Z0-of-the-part frame are stamped: `00` (before re-zero) and
  `03b` (flipped) are skipped.
- `machined.bin` is float32 row-major with a 24-byte header (`BCHM`, nx, ny, pitch, x0, y0);
  `viewer.js` reads exactly that.

## Runs and repo hygiene

- `out/` is not ignored by git (Claude may not edit `.gitignore`). Add it yourself, or every
  run and the cache show up as untracked files.
- `generate --out DIR` keeps verification runs out of the tree. The run directory is created
  as `<dir>.tmp` and renamed; a crash leaves a `.tmp` you can delete.
- `python3 -m boardcam` must run from the repo root or with `--root`; the package finds the
  project root as the parent of `boardcam/` otherwise.
- Never name a subpackage after a standard-library module: `select/` shadowed `select` and
  broke `subprocess` for any script run from inside `boardcam/` (renamed to `selection/`).

## Server and page

- Single-threaded: a generate blocks the page for 10–45 s; the page shows elapsed seconds.
- `/api/preview.svg` builds the design without STL (~1 s uncached); the page debounces and
  serialises requests.
- Run files are served only from a whitelist (`nc/*.nc`, `report.txt`, `job_sheet.md`,
  `preview.svg`, `model.stl`, `machined.bin`, `design.json`, `run.zip`).
- `curl` normalises `..` unless `--path-as-is` is given; without it a traversal test proves nothing.

## Timing (this machine, Python 3.11.9, OpenSCAD 2026.09.18 Manifold)

| step | time |
|---|---|
| shape render, cached | < 0.1 s |
| shape render, cold: 2-D exports | 0.1–0.2 s total |
| exact STL (minkowski) | 9–12 s, parallel with the rest |
| plan (rasters + contours for selection) | 5–10 s for 3–6 pockets |
| generate, pinwheel presets | 7–15 s with heightmap |
| generate, tray | 5–6 s |
| sweep pinwheel, 35 variants | 2 min |
