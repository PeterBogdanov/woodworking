# Geometry engine

All toolpath geometry is 2-D in the plane of the part, origin at the blank centre,
millimetres, radians internally. Depth is handled by the operations (`gcode-safety.md`).

## Where shapes come from

The shape script (`shapes/<name>.scad`) owns the geometry. For the pinwheel:

- `spiral_edge(i, off_w, R_p, r_h, delta_deg)` is the 1:1 port of the old `spiral_edge`:
  logarithmic spiral `r = r_h·e^{kt}`, `k = ln(R_p/r_h)/δ`, angle `base + t + off_w/r`
  (arc-length wall offset, so a spiral wall is thinner than `wall_w`; `wall_min` in the echo
  is the true minimum), or a radial line with `asin(off_w/r)` for straight sectors.
- `pocket_raw(i)` = wall R (hub→rim) + rim arc + wall L (rim→hub) + hub arc.
- `pocket_region(i)` = `offset(r = corner_f) offset(delta = -corner_f) polygon(pocket_raw(i))`:
  shrink sharp, grow round → every convex corner of the pocket gets the fillet `corner_f`
  exactly; a horn too narrow for the fillet disappears in the shrink and comes back as a
  round cap of radius `corner_f`. (The old code shrank the fillet radius instead and warned.)
- 2-D exports use `$fs = seg_2d = 0.5 mm` (chord sag 2 µm on R14, 0.2 µm on R178).

`from_echo` simplifies every ring with `SIMPLIFY_TOL = 0.005 mm` after merging micro-edges
shorter than 50 µm. OpenSCAD prints six significant digits, so two vertices 16 µm apart do
occur and read as a 90° corner; the simplification also brings a 1674-point pocket down to
~520 points (like the old sag-based outline) and halves the `.nc` size.

## `cam.pocket.Pocket`

Built from a `Region` (outer ring CCW + holes CW). `inside(p)` is the even-odd test over
all rings; `dist_fast(p)` uses a 12 mm spatial hash over all ring segments (`RingGrid`,
ring-by-ring outward search). `r_min`/`R` are the min/max radius over **all** rings
(a hole around the centre would otherwise stop the polar raster early). `mid` = angle of
the centroid (only the seam of a full-circle interval depends on it). `fid` is the design
pocket id, with a letter suffix when one design pocket split into several regions.

### Polar raster (`raster`, strategy `polar`)

Concentric arcs about the origin from `R − Rt` inward by `stepover`, stops after 4 empty
radii or below `rmin` (`0` if the pocket contains the origin, else `max(2.5, r_min − Rt)`).
`raster_intervals` samples ~2 mm along the ring, keeps samples inside with
`dist ≥ Rt − 0.025`, bisects the ends 18 times, drops intervals < 0.5 mm, splits a full
circle in two. Unchanged from `board_v3`, memoised per `(r_tool, allow, stepover, F_extra)`.

### Linear raster (`raster_linear`, strategy `linear`)

Rows along X from `ymax − Rt` down by `stepover`, plus a final row at `ymin + Rt` if the
last step left more than 0.5 mm. Row intervals use the same criteria and refinement as
the polar version. Chosen when the outline is not a circle: arcs about the centre are
tangent to straight walls and leave 2 mm scallops between rings (found by the heightmap on
the tray). `options.raster = polar|linear` forces either.

`plan_raster()` returns a `Raster(kind, rows, Rt, rmin)` with `samples()` (ends and
midpoints for clearance checks) and `paths(sag)` (for the preview).

### Wall contour (`contour_runs(R, tol=0.1)`)

Per ring: naive equidistant `offset_ring` (inward for the outer ring, away from the hole
for holes) → `snap_in` (≤ 6 projections back to distance `R`) → a point is good if inside
and `dist ≥ R − tol` **and the whole chord to the next point** (sampled every 1.2 mm) is
good — the old code checked only the chord midpoint, which is not enough when consecutive
offset points are far apart (jagged STL-derived contours). Good points form closed runs
(all good) or open runs split at bad points (runs < 4 points dropped). Returns
`(runs, n_bad)`; `n_bad` is the "фрезе недоступно N точек" line.

### `reachable(p, r)`

Some legal tool-centre position (inside, clearance ≥ `r`) on 3 rings × 16 directions around
`p` covers `p`. Used by the heightmap to split leftover into "tool cannot enter" and
"toolpath gap".

## Profile path (`jobs.run.profile_path`)

Circle outline: `circle_points(R + r + sag)`. Polygon outline: `geometry.offset.offset_outward`:
edges offset by `r + sag`, convex vertices joined by arcs (miter when the turn is < 2°),
concave vertices by the intersection of the offset lines; then every point closer than `r`
to the outline is projected back to `r`, and local loops (segment `i` crossing segment `j`
within 120 points) are cut at the intersection. `+ sag` because an inscribed polygon's
chords lie `sag` closer to the part than the arc; with it the part is at most `sag` larger.
The run then checks: min distance ≥ `r − 0.05`, no path point or chord midpoint inside the
outline, and path length ≤ perimeter + 2πr (+2 % + 1 mm) — a longer path means loops.

## Tabs (`cam.tabs`)

`tab_distances(path, n)`: arc-length position of each path point and its distance to the
nearest of `n` tab centres at `L·(k+0.5)/n`. For a circle starting at angle 0 this is the
old `360·i/TABS + 180/TABS` placement.

## Fillet-aware roughing (`cam.ops.fillet_offset`)

At rough level `z` (depth of cut), the height above the finished floor is `h = depth − z`.
Inside the wall-floor fillet zone (`h < rc`, `rc` = pocket `floor_fillet_r`, 6.35 for the
1372) the design cross-section is narrower than the pocket outline by
`rc − sqrt(rc² − (rc − h)²)`; the rough level uses `Rt = r + wall_allow + that` for both its
contour and its raster. A level cuts the wall band from `z − doc` to `z`; the section is
narrowest at `z`, so the level's offset is safe for the whole band. Without this the flat
bit cut up to 3 mm into the fillet zone along every wall (`board_v3` behaviour, found by
the heightmap check).

## Invariants worth asserting mentally before any change

- Every point a bit centre visits inside a pocket is inside the region and ≥ `Rt − small`
  from every ring; every chord between consecutive contour points too.
- The profile path is outside the outline, ≥ `r − 0.05` from it, and has no loops.
- A rough level never enters the fillet zone deeper than the design section allows.
- `Region` rings are oriented (outer CCW, holes CW); `offset_ring` derives direction from
  orientation, so a reversed ring would offset the wrong way.
- `corner_f > finish tool radius` is no longer a static rule: `FINISH_FITS` and `n_bad`
  report what the bowl bit cannot reach, and the heightmap counts the leftover.
