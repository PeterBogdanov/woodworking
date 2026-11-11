// === UNITS ===
// units: mm   (assumed — no dimensions or unit symbols are legible on the sketch)

// === PARAMETERS ===
stock_x = 120;        // overall stock size in X (left-right)
stock_y = 120;        // overall stock size in Y (front-back)
stock_z = 18;         // stock thickness (Z)

clover_cx = 60;       // clover centre X position on the stock
clover_cy = 62;       // clover centre Y position on the stock

lobe_r = 21;          // radius of each of the four round leaf lobes
lobe_dist = 27;       // distance from clover centre to each lobe centre
centre_r = 16;        // radius of the central hub that joins the lobes

lobe_a1 = 25;         // lobe 1 direction (right lobe)
lobe_a2 = 100;        // lobe 2 direction (top lobe)
lobe_a3 = 175;        // lobe 3 direction (left lobe)
lobe_a4 = 225;        // lobe 4 direction (lower-left lobe)
lobe_angles = [lobe_a1, lobe_a2, lobe_a3, lobe_a4];  // list of all lobe directions

stem_angle = -78;     // stem direction (down and slightly to the right)
stem_len = 52;        // stem length from clover centre to stem tip
stem_base_r = 8;      // stem half-width where it meets the clover centre
stem_tip_r = 1.5;     // stem half-width at the tip (nearly pointed)

overshoot = 1;        // extra depth so the profile cut clears the stock cleanly

// === ASSUMPTIONS ===
// - No dimensions or unit symbols are legible on the sketch; every value above
//   is a visual estimate taken from the drawing's proportions.
// - Units assumed to be mm (typical for a small decorative routed part).
// - Part is read as a 2.5D through-profile cut of the clover outline.
// - Stock size chosen to fully contain the clover with an even margin.
// - Lobe directions are approximate; the sketch is freehand and not symmetric.
// - The narrow V shape at the bottom is read as a tapered stem that merges
//   into the clover centre.
// - If a proper engineering drawing exists, all dimensions need verification.

// === MODEL ===
$fn = 64;

module lobe_2d(a) {
    rotate([0, 0, a])
        hull() {
            circle(r = centre_r);
            translate([lobe_dist, 0]) circle(r = lobe_r);
        }
}

module stem_2d() {
    rotate([0, 0, stem_angle])
        hull() {
            circle(r = stem_base_r);
            translate([stem_len, 0]) circle(r = stem_tip_r);
        }
}

module clover_2d() {
    for (a = lobe_angles) lobe_2d(a);
    stem_2d();
}

difference() {
    cube([stock_x, stock_y, stock_z]);
    translate([clover_cx, clover_cy, -overshoot])
        linear_extrude(height = stock_z + 2 * overshoot)
            clover_2d();
}
