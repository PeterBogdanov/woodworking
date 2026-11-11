// === UNITS ===
// units: mm (the sketch is annotated "200 MM"; all values below are millimetres)

// === SKETCH TRANSCRIPTION ===
//   "200 MM" (top dimension line) -> overall stock size along X -> stock_x
//   "200" (right dimension line, mm implied) -> overall stock size along Y -> stock_y
//   outer flower outline -> pocket rim in plan -> lobe_n / lobe_dist / lobe_r / pocket_hub_r
//   inner flower outline (boundary of the hatch) -> pocket floor edge, i.e. the rim
//     offset inward by the cutter radius -> tool_d
//   hatched area, leader line "pocket" -> freeform (flower-shaped) pocket cut from
//     the top face -> pocket_depth
//   no side view / no section view -> thickness and pocket depth not given

// === PARAMETERS ===
stock_x             = 200;            // overall stock length along X, mm
stock_y             = 200;            // overall stock width along Y, mm
stock_z             = 20;             // stock thickness, mm   // TODO: verify - no section view
eps                 = 0.1;            // cutter overshoot, mm
tool_d              = 6.35;           // assumed 1/4 in end mill, mm
min_inside_corner_r = tool_d / 2;     // smallest millable inside corner, mm
min_wall            = 6;              // minimum wall between feature and edge, mm
flower_cx           = stock_x / 2;    // flower pocket centre X, mm
flower_cy           = stock_y / 2;    // flower pocket centre Y, mm
lobe_n              = 6;              // number of petals of the flower pocket
lobe_dist           = 40;             // petal centre distance from pocket centre, mm
lobe_r              = 30;             // petal radius, mm
pocket_hub_r        = 30;             // centre hub radius of the flower pocket, mm
pocket_r_out        = lobe_dist + lobe_r;   // pocket outer radius (centre to petal tip), mm
pocket_depth        = stock_z * 0.5;  // pocket depth from top face, mm  // TODO: verify - unreadable on sketch

// === ASSUMPTIONS ===
// - Units are mm: the sketch carries an explicit "MM" on the horizontal dimension.
// - No section view is drawn, so stock thickness is assumed to be a typical 20 mm
//   for a serving board.                                   // TODO: verify
// - Pocket depth is not dimensioned; the machining default of 0.5 * stock_z
//   (10 mm) is used.                                       // TODO: verify
// - The flower is drawn freehand and slightly irregular; it is modelled as a
//   symmetric 6-petal flower (6 circles of r = 30 mm, centres 40 mm from the
//   pocket centre, unioned with a 30 mm hub). Petal count and size are estimated
//   from the drawing relative to the 200 mm square.        // TODO: verify
// - The sketch shows a double outline: the outer line is read as the pocket rim
//   and the inner line (edge of the hatching) as the floor edge left by the
//   6.35 mm cutter, NOT as a second feature. One pocket only.
// - The pointed lobe at the bottom of the sketch is modelled as an ordinary round
//   petal; no separate stem/handle is drawn, so none is modelled.
// - The square corners are drawn sharp -> left sharp (no corner_r).
// - The flower is assumed centred in the square stock.
// - No juice groove, slot or hanging hole is drawn -> none modelled.
// - min_inside_corner_r is only used as a limit check; the pocket outline is
//   made of large arcs, so no corner has to be falsified to the tool radius.

// === MODEL ===
$fn = 64;

module flower_profile() {
    union() {
        circle(r = pocket_hub_r);
        for (i = [0 : lobe_n - 1])
            rotate([0, 0, i * 360 / lobe_n])
                translate([lobe_dist, 0])
                    circle(r = lobe_r);
    }
}

module pocket_cut() {
    translate([flower_cx, flower_cy, stock_z - pocket_depth])
        linear_extrude(height = pocket_depth + eps)
            flower_profile();
}

module board() {
    difference() {
        cube([stock_x, stock_y, stock_z]);
        pocket_cut();
    }
}

board();

// === CHECKS ===
// - Pocket footprint X: 100 +/- 70 = 30 .. 170 inside 0 .. 200 -> OK
// - Pocket footprint Y: 100 +/- 70 = 30 .. 170 inside 0 .. 200 -> OK
// - Wall pocket rim to nearest stock edge = stock_x/2 - pocket_r_out = 30 mm
//   >= min_wall (6 mm) -> OK
// - Blind pocket: floor left = stock_z - pocket_depth = 10 mm = 50 % of stock_z
//   >= 30 % of stock_z (6 mm) -> OK
// - Pocket depth 10 mm <= 0.7 * stock_z (14 mm) -> OK
// - Inside corners: every pocket boundary curve is a circle arc of r = 30 mm or a
//   > 30 mm concave blend, both well above min_inside_corner_r (3.18 mm) -> OK
// - No neighbouring features, so no feature-to-feature wall to check -> OK
// - Cutter reaches the floor everywhere in the pocket (pocket is convex enough
//   at every lobe, hub is r = 30 mm > tool_d/2) -> OK
