// === UNITS ===
// units: mm
// 图纸无单位符号，按尺寸量级判定为 mm。

// === SKETCH TRANSCRIPTION ===
//   "200 mm" (vertical) -> outer overall Y extent -> stock_y
//   "200 mm" (horizontal) -> outer overall X extent -> stock_x
//   "pocket" (arrow to shaded interior) -> top-face recess -> pocket1
//   unlabeled freeform lobe outline -> outer freeform profile -> outer_2d
//   no side view / thickness label -> stock_z assumed

// === PARAMETERS ===
stock_x = 200;                 // overall X length, handwritten 200 mm
stock_y = 200;                 // overall Y width, handwritten 200 mm
stock_z = 20;                  // TODO: verify — no thickness dimension on sketch; assumed typical board thickness
eps = 0.1;                     // cutter overshoot
outer_n = 64;                  // number of points around freeform outline
lobe_min = 0.62;               // TODO: verify — estimated waist radius fraction of freeform outer profile
lobe_max = 1.00;               // TODO: verify — estimated tip radius fraction of freeform outer profile
pocket1_inset = 15;            // TODO: verify — estimated rim/wall between outer edge and pocket
pocket1_depth = stock_z * 0.5; // TODO: verify — blind pocket depth, no side view; assumed 50% stock_z
pocket1_corner_r = 12;         // TODO: verify — estimated pocket curve/tool radius; not directly used if smooth
tool_d = 6.35;                 // default 1/4 in end mill
min_wall = 6;                  // minimum wall between features / edge
min_inside_corner_r = tool_d / 2; // 3.175

pocket_hx = stock_x / 2 - pocket1_inset; // derived pocket half-extent X
pocket_hy = stock_y / 2 - pocket1_inset; // derived pocket half-extent Y

// === ASSUMPTIONS ===
// - Units: no unit symbols; 200-mm magnitudes are typical for a wooden serving board.
// - Thickness: no side view; stock_z = 20 mm assumed; TODO: verify.
// - Outer freeform profile is approximated by a four-lobed polar curve using
//   lobe_min / lobe_max; no vector outline was readable; TODO: verify.
// - "pocket" is a single blind recess; no pocket dimensions are written, so it is
//   modeled as an inward inset copy of the outer profile, rim = pocket1_inset;
//   TODO: verify actual pocket shape/position.
// - Pocket depth = 0.5 * stock_z; floor remains 10 mm (50% stock_z), OK.
// - No holes, slots, juice groove, handle, edge chamfer, or roundover are drawn.
// - Tool radius: pocket boundaries are approximated smooth; expected inside
//   corner radius >= min_inside_corner_r; TODO: verify toolpath.
// - Ambiguous freeform outline: right/left/top/bottom lobes are treated as
//   symmetric; any handle-like protrusion would need a separate sketch.

// === MODEL ===
$fn = 64;

function lobe_pt(a, hx, hy, lmin, lmax) =
    let(f = lmin + (lmax - lmin) * abs(cos(2 * a)))
    [ hx * cos(a) * f, hy * sin(a) * f ];

module outer_2d() {
    polygon(points = [
        for (i = [0 : outer_n - 1])
            lobe_pt(i * 360 / outer_n, stock_x / 2, stock_y / 2, lobe_min, lobe_max)
    ]);
}

module pocket1_2d() {
    polygon(points = [
        for (i = [0 : outer_n - 1])
            lobe_pt(i * 360 / outer_n, pocket_hx, pocket_hy, lobe_min, lobe_max)
    ]);
}

module board() {
    difference() {
        translate([stock_x / 2, stock_y / 2, 0])
            linear_extrude(height = stock_z, convexity = 10)
                outer_2d();

        translate([stock_x / 2, stock_y / 2, stock_z - pocket1_depth])
            linear_extrude(height = pocket1_depth + eps, convexity = 10)
                pocket1_2d();
    }
}

board();

// === CHECKS ===
// - outer profile touches stock edges at X=0/stock_x and Y=0/stock_y: OK
// - pocket wall to outer edge = pocket1_inset = 15 >= min_wall (6): OK
// - blind pocket floor = stock_z - pocket1_depth = 10 >= 0.3 * stock_z (6): OK
// - cutter radius: default tool_d = 6.35 (R=3.175); pocket curve is smooth,
//   no inside corner sharper than tool radius: OK (estimated)
// - all cuts are from top face; no through cuts: OK
