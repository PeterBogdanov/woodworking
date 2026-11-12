// =============================================================================
//  Менажница-«вертушка» — форма для boardcam
// =============================================================================
//  Круглая доска с бортиком и отсеками, стенки которых закручены спиралью от
//  центральной втулки к бортику. Все размеры в миллиметрах, углы в градусах.
//
//  Как пользоваться: откройте файл в OpenSCAD, Window → Customizer, крутите
//  параметры, нажмите «+» (Save preset) — набор параметров сохраняется в
//  pinwheel.json рядом с этим файлом. Этот json и есть файл дизайна: boardcam
//  читает его по имени набора (-P) и строит траектории.
//
//  Контракт с boardcam (DESIGN.md §4): echo(boardcam_design = [...]) — описание
//  фигуры; export="" — 3-D модель; export="outline" / "pocket:N" — плоские
//  области для экспорта в SVG. Z0 = верх готовой доски, начало координат —
//  центр доски.
// =============================================================================

/* [Заготовка] */
// Сторона квадратной заготовки, мм
blank_size = 430;      // [250:5:800]
// Толщина заготовки, мм
blank_thick = 25;      // [15:1:60]

/* [Изделие] */
// Диаметр готовой доски, мм (406.4 = 16")
board_dia = 406.4;     // [250:0.2:500]
// Высота доски, мм
thick = 25;            // [15:1:60]
// Глубина отсеков, мм
pocket_depth = 12;     // [5:0.5:15.5]
// Ширина бортика, мм
rim_w = 25;            // [10:1:60]
// Число отсеков
n_pockets = 3;         // [3:1:8]

/* [Вертушка] */
// Раскладка
layout = "spiral";     // [spiral:Вертушка, spiral_center:Вертушка с центральным карманом, sectors:Прямые сектора]
// Закрутка стенки от втулки к бортику, ° (0 = прямые сектора)
sweep_deg = 200;       // [0:2:260]
// Радиус втулки, мм (с центральным карманом: радиус кармана + толщина стенки)
hub_r = 30;            // [15:1:60]
// Толщина стенки, мм (у спирали — смещение по дуге, дерева остаётся меньше)
wall_w = 12;           // [6:0.5:30]
// Скругление стыков стенка/бортик и стенка/втулка в плане, мм
corner_f = 14;         // [10:0.5:25]

/* [Hidden] */
export = "";           // "" = 3-D модель; "outline" | "pocket:N" = плоская область
seg_2d = 0.5;          // длина сегмента дуг для плоского экспорта, мм
seg_3d = 2.0;          // то же для 3-D модели
wall_n = 200;          // сегментов на кромке стенки
floor_style = "steps"; // "steps" = ступени (мгновенный предпросмотр F5); "exact" = minkowski, его ставит boardcam при экспорте STL
floor_steps = 12;      // ступеней в скруглении дно/стенка при floor_style = "steps"
bowl_r = 6.35;         // радиус скругления дно/стенка (след чашечной фрезы Whiteside 1372)

// ---------------------------------------------------------------- геометрия ---

function polar(r, a) = [r * cos(a), r * sin(a)];
function ang(p) = atan2(p[1], p[0]);
function deg(rad) = rad * 180 / PI;
function sub(v, a, b) = [for (j = [a : 1 : b]) v[j]];
function rev(v) = [for (j = [len(v) - 1 : -1 : 0]) v[j]];

function field_r() = board_dia / 2 - rim_w;                  // внешняя граница карманов
function straight() = (layout == "sectors") || (abs(sweep_deg) < 1e-9);
function eff_sweep() = straight() ? 0 : sweep_deg;
function center_r() = hub_r - wall_w;                        // радиус центрального кармана
function n_features() = n_pockets + (layout == "spiral_center" ? 1 : 0);

// Кромка стенки i (0..n-1), смещённая на off_w вдоль дуги; wall_n+1 точек от втулки к бортику.
// Спираль: логарифмическая r = r_h·e^{k·t}, k = ln(R_p/r_h)/delta. Прямые сектора:
// луч под углом base, смещённый так, чтобы стенка была ровно off_w толщиной.
function spiral_edge(i, off_w, R_p, r_h, delta_deg) =
    let (base = i * 360 / n_pockets)
    (abs(delta_deg) < 1e-9)
      ? [for (j = [0 : wall_n]) let (r = r_h + (R_p - r_h) * j / wall_n,
                                     a = base + asin(min(1, off_w / r))) polar(r, a)]
      : let (delta = delta_deg * PI / 180, k = ln(R_p / r_h) / delta)
        [for (j = [0 : wall_n]) let (t = delta * j / wall_n, r = r_h * exp(k * t),
                                     a = base + deg(t + off_w / r)) polar(r, a)];

// Дуга радиуса r от угла a0 к a1 кратчайшим путём (со знаком), сегменты не длиннее seg.
function arc_pts(r, a0, a1, seg) =
    let (d = ((a1 - a0 + 180) % 360 + 360) % 360 - 180,
         n = max(2, ceil(abs(d) * PI / 180 * r / seg)))
    [for (j = [0 : n]) polar(r, a0 + d * j / n)];

// Сырой (без скруглений) контур отсека i: задняя кромка стенки i от втулки к бортику,
// дуга бортика, передняя кромка стенки i+1 от бортика к втулке, дуга втулки.
function pocket_raw(i, seg) =
    let (R_p = field_r(), r_h = hub_r, d = eff_sweep(),
         wR = spiral_edge(i, wall_w, R_p, r_h, d),
         wL = spiral_edge(i + 1, 0, R_p, r_h, d),
         rim = arc_pts(R_p, ang(wR[wall_n]), ang(wL[wall_n]), seg),
         hub = arc_pts(r_h, ang(wL[0]), ang(wR[0]), seg))
    concat(wR, sub(rim, 1, len(rim) - 1), sub(rev(wL), 1, wall_n), sub(hub, 1, len(hub) - 2));

// Минимальная реальная толщина стенки: расстояние между двумя кромками одной стенки.
function dist_seg(p, a, b) =
    let (v = b - a, w = p - a, L2 = v * v,
         t = (L2 < 1e-18) ? 0 : max(0, min(1, (w * v) / L2)))
    norm(w - t * v);
function wall_min() =
    let (R_p = field_r(), d = eff_sweep(),
         A = spiral_edge(0, 0, R_p, hub_r, d), B = spiral_edge(0, wall_w, R_p, hub_r, d))
    min([for (jb = [0 : 4 : wall_n - 1])
            min([for (ja = [0 : wall_n - 1]) dist_seg(B[jb], A[ja], A[ja + 1])])]);

// ------------------------------------------------------------- плоские области ---

module pocket_region(i, seg) {
    // Скругление выпуклых углов области (стыки стенка/бортик, стенка/втулка) радиусом
    // corner_f: сжать на f с острыми углами, затем расширить на f с круглыми.
    offset(r = corner_f) offset(delta = -corner_f) polygon(pocket_raw(i, seg));
}

module center_region(seg) {
    circle(r = center_r(), $fn = max(24, ceil(2 * PI * center_r() / seg)));
}

module feature_region(k, seg) {          // k = 1..n_features()
    if (k <= n_pockets) pocket_region(k - 1, seg);
    else center_region(seg);
}

module outline_region(seg) {
    circle(d = board_dia, $fn = max(64, ceil(PI * board_dia / seg)));
}

// ------------------------------------------------------------------ 3-D модель ---

// Объём отсека k: стенки вертикальные, у дна скругление bowl_r - след чашечной фрезы.
// "exact": призма области, сжатой на bowl_r, раздутая сферой bowl_r (minkowski) - ровно та
// поверхность, которую оставит фреза с радиусом bowl_r; на бэкенде Manifold считается за
// доли секунды, на старом CGAL - минуты. "steps": floor_steps ступеней по четверти
// окружности, ступень сужена на отступ в середине своего угла (для OpenSCAD 2021.01).
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
    (layout == "spiral_center" && center_r() < 8)
        ? [["error", "CENTER_TOO_SMALL",
            str("центральный карман радиусом ", center_r(), " мм слишком мал (нужно >= 8): ",
                "увеличьте радиус втулки или уменьшите толщину стенки")]] : [],
    (field_r() - hub_r < 20)
        ? [["error", "NO_ROOM",
            str("между втулкой R", hub_r, " и бортиком остаётся ", field_r() - hub_r,
                " мм: карманам нет места (уменьшите бортик или втулку)")]] : [],
    (pocket_depth > thick - 3)
        ? [["error", "TOO_DEEP",
            str("глубина отсека ", pocket_depth, " оставляет дну меньше 3 мм при высоте ", thick)]] : []
);
function has_error() = len([for (m = messages()) if (m[0] == "error") m]) > 0;

echo(boardcam_design = [
    ["schema", 1], ["shape", "pinwheel"], ["variant", layout], ["units", "mm"],
    ["blank", [blank_size, blank_size, blank_thick]], ["origin", "corner"],
    ["thick", thick],
    ["outline", ["circle", board_dia]],
    ["features", [for (k = [1 : n_features()])
                     ["pocket", k, ["svg", str("pocket:", k)], pocket_depth, bowl_r]]],
    ["derived", [["wall_min", wall_min()], ["field_r", field_r()],
                 ["center_r", layout == "spiral_center" ? center_r() : undef]]],
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
