// =============================================================================
//  Поднос (лоток) с отсеками — вторая фигура boardcam, первая с некруглым контуром
// =============================================================================
//  Прямоугольная доска со скруглёнными углами, бортиком и сеткой отсеков
//  n_x x n_y, разделённых перегородками. Дно отсеков со скруглением bowl_r
//  (след чашечной фрезы). Всё в миллиметрах. Контракт с boardcam - как у
//  pinwheel.scad: echo(boardcam_design = [...]), export="" / "outline" / "pocket:N".
// =============================================================================

/* [Заготовка] */
// Заготовка по X, мм
blank_x = 400;         // [200:5:800]
// Заготовка по Y, мм
blank_y = 300;         // [150:5:800]
// Толщина заготовки, мм
blank_thick = 22;      // [12:1:60]

/* [Изделие] */
// Длина (по X), мм
length = 360;          // [150:2:760]
// Ширина (по Y), мм
width = 260;           // [100:2:760]
// Высота, мм
thick = 22;            // [12:1:60]
// Радиус наружных углов, мм
corner_r = 25;         // [5:1:120]
// Ширина бортика, мм
rim_w = 18;            // [8:1:60]
// Глубина отсеков, мм
pocket_depth = 12;     // [4:0.5:15.5]

/* [Отсеки] */
// Отсеков по X
n_x = 3;               // [1:1:4]
// Отсеков по Y
n_y = 2;               // [1:1:4]
// Толщина перегородок, мм
divider_w = 10;        // [5:0.5:30]
// Скругление углов отсеков в плане, мм (больше радиуса чистовой фрезы 9.53)
pocket_r = 14;         // [10:0.5:40]

/* [Hidden] */
export = "";
seg_2d = 0.5;
seg_3d = 2.0;
floor_style = "steps";
floor_steps = 12;
bowl_r = 6.35;

// ---------------------------------------------------------------- геометрия ---

function n_features() = n_x * n_y;
function cell_w() = (length - 2 * rim_w - (n_x - 1) * divider_w) / n_x;
function cell_h() = (width - 2 * rim_w - (n_y - 1) * divider_w) / n_y;
function cell_x(i) = -length / 2 + rim_w + i * (cell_w() + divider_w);      // левый край отсека i
function cell_y(j) = -width / 2 + rim_w + j * (cell_h() + divider_w);       // нижний край отсека j

module rounded_rect(w, h, r, seg) {
    fn = max(16, ceil(2 * PI * r / seg));
    offset(r = r, $fn = fn) square([w - 2 * r, h - 2 * r], center = true);
}

module outline_region(seg) { rounded_rect(length, width, corner_r, seg); }

module feature_region(k, seg) {               // k = 1..n_x*n_y, по строкам снизу вверх
    i = (k - 1) % n_x;
    j = floor((k - 1) / n_x);
    r = min(pocket_r, cell_w() / 2 - 0.01, cell_h() / 2 - 0.01);
    translate([cell_x(i) + cell_w() / 2, cell_y(j) + cell_h() / 2]) rounded_rect(cell_w(), cell_h(), r, seg);
}

module feature_cut(k, seg) {
    eps = 0.01;
    if (floor_style == "exact") {
        minkowski() {
            translate([0, 0, -pocket_depth + bowl_r])
                linear_extrude(pocket_depth + 2) offset(delta = -bowl_r) feature_region(k, seg);
            sphere(r = bowl_r, $fn = 32);
        }
    } else {
        for (s = [0 : floor_steps - 1]) {
            h0 = bowl_r * (1 - cos(90 * s / floor_steps));
            h1 = bowl_r * (1 - cos(90 * (s + 1) / floor_steps));
            d  = bowl_r * (1 - sin(90 * (s + 0.5) / floor_steps));
            if (h0 < pocket_depth)
                translate([0, 0, -pocket_depth + h0 - eps])
                    linear_extrude(min(h1, pocket_depth + 1) - h0 + 2 * eps)
                        offset(delta = -d) feature_region(k, seg);
        }
        if (pocket_depth > bowl_r)
            translate([0, 0, -pocket_depth + bowl_r - eps])
                linear_extrude(pocket_depth - bowl_r + 1 + eps) feature_region(k, seg);
    }
}

module model() {
    $fa = 2;
    difference() {
        translate([0, 0, -thick]) linear_extrude(thick) outline_region(seg_3d);
        for (k = [1 : n_features()]) feature_cut(k, seg_3d);
    }
}

// ------------------------------------------------------------- контракт boardcam ---

function messages() = concat(
    (cell_w() < 2 * bowl_r + 2 || cell_h() < 2 * bowl_r + 2)
        ? [["error", "CELL_TOO_SMALL",
            str("отсек ", cell_w(), " x ", cell_h(), " мм слишком мал для чашечной фрезы: меньше отсеков, тоньше перегородки или бортик")]] : [],
    (pocket_depth > thick - 3)
        ? [["error", "TOO_DEEP", str("глубина отсека ", pocket_depth, " оставляет дну меньше 3 мм при высоте ", thick)]] : [],
    (corner_r > min(length, width) / 2)
        ? [["error", "CORNER_R", str("радиус угла ", corner_r, " больше половины меньшей стороны")]] : []
);
function has_error() = len([for (m = messages()) if (m[0] == "error") m]) > 0;

echo(boardcam_design = [
    ["schema", 1], ["shape", "tray"], ["variant", str(n_x, "x", n_y)], ["units", "mm"],
    ["blank", [blank_x, blank_y, blank_thick]], ["origin", "corner"],
    ["thick", thick],
    ["outline", ["svg", "outline"]],
    ["features", [for (k = [1 : n_features()])
                     ["pocket", k, ["svg", str("pocket:", k)], pocket_depth, bowl_r]]],
    ["derived", [["wall_min", min(divider_w, rim_w)], ["cell_w", cell_w()], ["cell_h", cell_h()]]],
    ["messages", messages()]
]);

if (!has_error()) {
    if (export == "") {
        model();
    } else if (export == "outline") {
        outline_region(seg_2d);
    } else {
        for (k = [1 : n_features()])
            if (export == str("pocket:", k)) feature_region(k, seg_2d);
    }
}
