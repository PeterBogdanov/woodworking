// === UNITS ===
// units: mm
// All dimensions are converted to millimeters; no inch markings on sketch.

// === SKETCH TRANSCRIPTION ===
//   "200 mm" (bottom horizontal) -> overall board width -> stock_x
//   "200 mm" (right vertical) -> overall board height -> stock_y
//   "pocket" -> central pocket offset inward from outer profile -> pocket_inset, pocket_depth
//   (no thickness or pocket depth shown) -> stock_z, pocket_depth estimated -> TODO

// === PARAMETERS ===
stock_x = 200;                 // overall width of board (mm)
stock_y = 200;                 // overall height of board (mm)
stock_z = 20;                  // overall stock thickness (mm) TODO: verify — not dimensioned on sketch
outer_max_r = stock_x / 2;     // outer profile maximum radius (mm)
outer_base_r = 75;             // rose-curve base radius (mm)
outer_amp_r = outer_max_r - outer_base_r; // rose-curve petal amplitude (mm)
petal_count = 4;               // number of outer lobes / rose frequency
outline_pts = 180;             // polygon segments for outer profile
pocket_inset = 18;             // pocket inward offset from outer edge (mm) TODO: verify — not dimensioned
pocket_depth = stock_z * 0.5;  // pocket depth (mm) TODO: verify — no depth on sketch
eps = 0.1;                     // cutter overshoot (mm)
min_wall = 6;                  // minimum wall thickness (mm)

// === ASSUMPTIONS ===
// Units: no unit symbols, magnitude 200x200 -> mm assumed.
// Board thickness not shown; 20 mm assumed (typical serving-board stock).
// Pocket depth not shown; 0.5 * stock_z = 10 mm assumed.
// Pocket shape assumed to be a uniform inward offset of the outer profile.
// Outer profile approximated as a 4-petal rose curve; exact hand-drawn curve not dimensioned.
// The two 200 mm dimensions are taken as overall width and height, not conflicting.
// Tool diameter default 6.35 mm used for inside-corner feasibility checks.

// === MODEL ===
$fn = 64;

function rose_pt(i, n, base, amp, lobes) =
    [ (base + amp * cos(lobes * i * 360 / n)) * cos(i * 360 / n),
      (base + amp * cos(lobes * i * 360 / n)) * sin(i * 360 / n) ];

module outer_2d() {
    translate([stock_x / 2, stock_y / 2])
        polygon(points = [
            for (i = [0 : outline_pts - 1])
                rose_pt(i, outline_pts, outer_base_r, outer_amp_r, petal_count)
        ]);
}

module pocket_2d() {
    offset(delta = -pocket_inset, $fn = 64) outer_2d();
}

module board() {
    difference() {
        linear_extrude(height = stock_z) outer_2d();
        translate([0, 0, stock_z - pocket_depth])
            linear_extrude(height = pocket_depth + eps) pocket_2d();
    }
}

board();

// === CHECKS ===
// Outer profile max radius 100 mm centered in 200x200 stock; all points inside stock: OK
// Pocket is inward offset 18 mm from outer profile; minimum wall >= 6 mm: OK
// Pocket depth 10 mm leaves 10 mm floor = 50% of stock_z; >= 30% required: OK
// No sharp inside corners on outer or pocket curves; tool radius not violated: OK
// All cuts are from top face at z = stock_z and extend eps above: OK
