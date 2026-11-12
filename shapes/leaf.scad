// =============================================================================
//  Кленовый лист — поднос с одним отсеком по форме листа
// =============================================================================
//  Контур — стилизованный кленовый лист (многоугольник, симметричный по оси Y,
//  черешок внизу), вписанный в квадрат size x size. Острия скруглены tip_r
//  (не меньше, чем может обойти контурная фреза), выемки — notch_r (больше
//  радиуса контурной фрезы 3.175). Отсек — контур, сдвинутый внутрь на rim_w;
//  его выступы скруглены pocket_r (больше радиуса чистовой фрезы 9.53), так что
//  узкие лопасти и черешок остаются сплошными. Дно со скруглением bowl_r.
//  Отверстие для подвеса не делается: у операций boardcam пока нет "hole".
//  Контракт с boardcam — как у tray.scad.
// =============================================================================

/* [Заготовка] */
// Заготовка по X, мм
blank_x = 340;         // [200:5:800]
// Заготовка по Y, мм
blank_y = 340;         // [200:5:800]
// Толщина заготовки, мм
blank_thick = 22;      // [12:1:60]

/* [Изделие] */
// Размер листа (вписан в квадрат), мм
size = 300;            // [180:2:760]
// Высота, мм
thick = 22;            // [12:1:60]
// Скругление остриёв, мм
tip_r = 5;             // [3:0.5:20]
// Скругление выемок между зубцами, мм (больше радиуса контурной фрезы 3.175)
notch_r = 5;           // [4:0.5:20]
// Ширина бортика, мм
rim_w = 15;            // [8:1:40]
// Глубина отсека, мм
pocket_depth = 12;     // [4:0.5:15.5]
// Скругление выступов отсека в плане, мм (больше радиуса чистовой фрезы 9.53)
pocket_r = 12;         // [10:0.5:40]

/* [Hidden] */
export = "";
seg_2d = 0.5;
seg_3d = 2.0;
floor_style = "steps";
floor_steps = 12;
bowl_r = 6.35;

// ---------------------------------------------------------------- геометрия ---

// правая половина листа, от верхнего острия по часовой стрелке до низа черешка
half = [
    [0, 150], [14, 118], [30, 128], [26, 96], [44, 104], [30, 45],                  // верхняя лопасть
    [70, 68], [74, 58], [112, 90], [104, 58], [150, 40], [116, 14], [122, 2],       // боковая лопасть
    [80, -10], [100, -50], [70, -48], [72, -62], [40, -70], [16, -82],              // нижняя лопасть
    [16, -138], [12, -148], [0, -150]                                               // черешок
];
raw = concat(half, [for (i = [len(half) - 2 : -1 : 1]) [-half[i][0], half[i][1]]]);
k_scale = size / 300;           // сырые точки лежат в квадрате 300 x 300
pts = [for (p = raw) p * k_scale];

function fn_for(r, seg) = max(16, ceil(2 * PI * r / seg));

module outline_region(seg) {
    offset(r = -notch_r, $fn = fn_for(notch_r, seg)) offset(delta = notch_r)          // выемки
        offset(r = tip_r, $fn = fn_for(tip_r, seg)) offset(delta = -tip_r)            // острия
            polygon(pts);
}

module feature_region(k, seg) {
    offset(r = -3, $fn = fn_for(3, seg)) offset(delta = 3)
        offset(r = pocket_r, $fn = fn_for(pocket_r, seg)) offset(delta = -(rim_w + pocket_r))
            outline_region(seg);
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
        feature_cut(1, seg_3d);
    }
}

// ------------------------------------------------------------- контракт boardcam ---

function messages() = concat(
    (pocket_depth > thick - 3)
        ? [["error", "TOO_DEEP", str("глубина отсека ", pocket_depth, " оставляет дну меньше 3 мм при высоте ", thick)]] : [],
    (rim_w + pocket_r > 45 * k_scale)
        ? [["error", "RIM_TOO_WIDE", str("бортик ", rim_w, " + скругление ", pocket_r, " не оставляют отсеку места в листе ", size, " мм")]] : [],
    (size + 20 > min(blank_x, blank_y))
        ? [["error", "BLANK_SMALL", str("лист ", size, " мм не помещается в заготовку ", blank_x, " x ", blank_y, " с полями 10 мм")]] : []
);
function has_error() = len([for (m = messages()) if (m[0] == "error") m]) > 0;

echo(boardcam_design = [
    ["schema", 1], ["shape", "leaf"], ["variant", "maple"], ["units", "mm"],
    ["blank", [blank_x, blank_y, blank_thick]], ["origin", "corner"],
    ["thick", thick],
    ["outline", ["svg", "outline"]],
    ["features", [["pocket", 1, ["svg", "pocket:1"], pocket_depth, bowl_r]]],
    ["derived", [["wall_min", rim_w], ["size", size]]],
    ["messages", messages()]
]);

if (!has_error()) {
    if (export == "") {
        model();
    } else if (export == "outline") {
        outline_region(seg_2d);
    } else if (export == "pocket:1") {
        feature_region(1, seg_2d);
    }
}
