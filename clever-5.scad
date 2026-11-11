// === UNITS ===
// units: mm
// The sketch carries an explicit "MM" on the top dimension line, so every
// number below is millimetres. No inch fractions are present.

// === SKETCH TRANSCRIPTION ===
//   "200 MM"  (top dimension line, arrows to the box)  -> overall X extent of the
//                                                          freeform outline -> stock_x
//   "200"     (right dimension line, arrows to the box) -> overall Y extent of the
//                                                          freeform outline -> stock_y
//   freeform outline drawn inside the 200 x 200 box: a 5-lobe flower (rounded
//   lobes, rounded notches) with a tapered stem at the bottom
//                                                       -> petal_*, core_r, stem_*
//   "pocket"  (leader line pointing at the hatched inner flower) -> freeform
//   recess inset from the outline, flat floor            -> pocket1_*
//   (no side / section view is drawn -> no thickness and no pocket depth given)

// === PARAMETERS ===
stock_x = 200;               // overall part length (X), from "200 MM" top dimension
stock_y = 200;               // overall part width  (Y), from "200" right dimension
stock_z = 20;                // stock thickness            // TODO: verify - not shown on sketch

// --- outer freeform profile: 5-lobe flower with stem -------------------------
flower_cx = 100;             // flower centre X (centred in the 200 box)
flower_cy = 105;             // flower centre Y            // TODO: verify - estimated
petal_n     = 5;             // number of lobes            // TODO: verify - counted 5 on the sketch
petal_a0    = 36;            // angle of the first lobe, deg
petal_ring_r = 50;           // radius of the ring the lobes sit on
petal_r      = 40;           // lobe radius
core_r       = 45;           // central disc that ties the lobes together
notch_r      = 5;            // fillet radius of the notches between lobes (>= tool_r)

stem_base_x = 100;           // stem root X (inside the flower)
stem_base_y = 70;            // stem root Y
stem_base_r = 13;            // stem root half width
stem_tip_x  = 100;           // stem tip X                 // TODO: verify - sketch stem leans slightly left
stem_tip_y  = 13;            // stem tip Y
stem_tip_r  = 8;             // stem tip half width

// --- freeform pocket ----------------------------------------------------------
pocket1_rim      = 15;       // solid wall kept between the outline and the pocket
pocket1_depth    = 10;       // pocket depth = 0.5 * stock_z
pocket1_corner_r = 5;        // fillet of the pocket's inside corners (>= tool_r)

eps = 0.1;                   // cutter overshoot past the top face
tool_r = 3.175;              // 1/4 in end mill radius, used only for the checks

// === ASSUMPTIONS ===
// units: mm - the sketch says "MM" on the top dimension, so nothing is converted.
// The 200 x 200 square is read as the dimension box / bounding box around the
//   freeform flower, so the part outline is the FLOWER + stem, not the square.
//   (Alternative reading - a square board with a flower-shaped pocket - rejected
//   because the leader line marks only the hatched inner region as "pocket".)
// Thickness is not dimensioned anywhere (no side view) -> assumed 20 mm.
// Pocket depth is not dimensioned -> assumed 0.5 * stock_z = 10 mm (flat floor;
//   the sketch shows no rounded dish section).
// Rim width estimated at ~15 mm from the gap drawn between the two outlines.
// Lobe count read as 5; exact lobe radius / ring radius are estimates used to
//   fill the 200 x 200 box proportionally to the sketch.
// The stem is simplified to a straight tapered stub (the sketch shows it leaning
//   a few degrees to the left).
// Drawn inside corners are filleted up to notch_r / pocket1_corner_r so a
//   6.35 mm cutter can machine them (min inside corner radius = 3.175 mm).
// No juice groove, handle hole, slot or edge chamfer is drawn -> none modelled.

// === MODEL ===
$fn = 64;

// 5-lobe flower body, local coordinates around the flower centre
module flower_body_raw() {
    union() {
        circle(r = core_r);
        for (i = [0 : petal_n - 1])
            rotate(petal_a0 + i * 360 / petal_n)
                translate([petal_ring_r, 0]) circle(r = petal_r);
    }
}

// raw outline = flower body + tapered stem, in stock coordinates
module raw_outline() {
    union() {
        translate([flower_cx, flower_cy]) flower_body_raw();
        hull() {
            translate([stem_base_x, stem_base_y]) circle(r = stem_base_r);
            translate([stem_tip_x,  stem_tip_y ]) circle(r = stem_tip_r);
        }
    }
}

// outer profile: closing rounds the concave notches to notch_r
module outline2d() {
    offset(r = -notch_r) offset(delta = notch_r) raw_outline();
}

// pocket: flower body eroded by the rim, inside corners rounded
module pocket1_2d() {
    offset(r = -pocket1_corner_r) offset(delta = pocket1_corner_r)
        offset(delta = -pocket1_rim)
            translate([flower_cx, flower_cy]) flower_body_raw();
}

module board() {
    difference() {
        linear_extrude(height = stock_z) outline2d();
        translate([0, 0, stock_z - pocket1_depth])
            linear_extrude(height = pocket1_depth + eps) pocket1_2d();
    }
}

board();

// === CHECKS ===
// outline bbox X 10.0 .. 180.5, Y 5.0 .. 192.6 inside stock 200 x 200 -> OK
// pocket bbox X 25.0 .. 165.5, Y 32.5 .. 177.6 inside the outline -> OK
// min wall pocket-to-edge = pocket1_rim = 15.0 >= min_wall 6 -> OK
// inside corner radii: notch_r 5.0 and pocket1_corner_r 5.0 >= tool_r 3.175 -> OK
// material left under the blind pocket = stock_z - pocket1_depth = 10.0 = 50% of stock_z >= 30% -> OK
// pocket1_depth 10.0 <= 0.7 * stock_z = 14.0 -> OK
