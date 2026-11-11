#!/usr/bin/env python3
"""
sketch_to_scad.py — тест: фото карандашного эскиза -> OpenSCAD через DeepSeek.

Использование:
    export DEEPSEEK_API_KEY="sk-..."
    python sketch_to_scad.py photo.jpg [out.scad]

Результат: файл .scad со строгой структурой:
    // === UNITS ===        (mm или inch, определяется по эскизу)
    // === PARAMETERS ===   (все размеры — именованные переменные, легко парсить)
    // === ASSUMPTIONS ===  (все догадки модели — явно, комментариями)
    // === MODEL ===        (2.5D: заготовка-cube минус карманы/отверстия/пазы)

Посмотреть результат: openscad out.scad
"""

import base64
import mimetypes
import os
import re
import sys

from openai import OpenAI

MODEL = "deepseek-flash"
BASE_URL = "https://api.deepseek.com"

PROMPT = """You are a CAD assistant for a woodworker who cuts charcuterie / serving
boards on a 3-axis CNC router. You receive ONE photo of a hand-drawn pencil sketch
of a board with handwritten dimensions. Convert it into ONE valid OpenSCAD program.

THE PART
Flat wooden stock machined as 2.5D: an outer profile (rectangle, rounded rectangle,
oval or freeform) plus features cut from the top face: pockets (bowls, dips, nuts,
crackers; round, rectangular with corner radius, oval/stadium, or freeform), a juice
groove, a handle or hanging hole, slots, and optionally an edge chamfer or roundover.

HOW TO READ THE SKETCH
- The main drawing is a TOP VIEW: page-left = X 0, page-bottom = Y 0 (front).
  Side or section views, if present, give thickness and depths.
- Notation: "Ø" or "D" = diameter; "R" = radius; "THRU" = through cut;
  "typ", "x3", "EQ SP" = repeated features (use for() with count and pitch
  parameters); dashed lines = hidden features; centerlines = symmetry.
- Fractions such as 1 1/2" or 3/4 are valid; convert them to decimals.
- Written numbers ALWAYS override drawn proportions. If written numbers conflict
  (the parts do not sum to the total), keep the written value for each feature,
  and record the conflict in ASSUMPTIONS.
- For anything with no number, estimate from proportions relative to the nearest
  dimensioned feature.
- If the image is not a part sketch or is unusable, output only one line:
  // ERROR: <reason>

STRICT OUTPUT RULES
1. Output ONLY OpenSCAD code. No markdown fences, no prose. Everything you want to
   say goes into OpenSCAD comments.

2. The file has exactly these sections, in this order:

   // === UNITS ===
   // units: mm
   Always output millimeters. Convert inches (x 25.4), round to 0.1 mm, and keep
   the original value in the comment, e.g. // 3/4 in. If the sketch has no unit
   symbols, decide from magnitude (a board is ~300-600 mm long) and say so in
   ASSUMPTIONS.

   // === SKETCH TRANSCRIPTION ===
   One comment line per handwritten label or visible feature, in the form:
   //   "label as read" -> what it dimensions -> variable name
   Do this BEFORE writing parameters. Mark uncertain digits with (?).

   // === PARAMETERS ===
   One variable per line, with a trailing comment saying what it is. snake_case:
     stock_x, stock_y, stock_z                overall stock (length, width, thickness)
     corner_r                                 outer corner radius (omit if sharp)
     pocketN_x, pocketN_y, pocketN_d, pocketN_depth        round pocket
     pocketN_x, pocketN_y, pocketN_w, pocketN_l, pocketN_r, pocketN_depth,
       pocketN_rot                            rectangular pocket (w along X, l along Y,
                                              r = corner radius, rot in degrees)
     holeN_x, holeN_y, holeN_d (+ holeN_depth if blind)    through hole by default
     grooveN_inset, grooveN_w, grooveN_depth  groove following the outline at an
                                              inset from the edge
     slotN_*, edge_chamfer, edge_round_r      analogous
     eps                                      cutter overshoot, = 0.1
   Feature positions (x, y) are the feature CENTER measured from the stock origin
   corner, unless the sketch clearly dimensions from an edge (then convert).
   Derived values (e.g. pocket2_x = stock_x / 2) are allowed as parameters.

   // === ASSUMPTIONS ===
   One comment line per guess: unreadable digits, missing dimensions, unclear
   depths, assumed symmetry, assumed units, resolved conflicts, ambiguous readings.

   // === MODEL ===
   $fn = 64;
   One module per feature, one board() module, and a final top-level call board();
   Stock origin at [0,0,0], X right, Y away, Z up, top face at z = stock_z.
   Cuts are difference() operations from the TOP face; cutters extend eps above it.

   // === CHECKS ===
   Comment lines, each ending OK or WARNING: every feature lies inside the stock;
   wall between neighboring features and to the edge >= min_wall; inside corners
   respect the tool radius; floor under every blind cut >= 30% of stock_z.

3. Every number in the MODEL section references a PARAMETER variable. Only trivial
   arithmetic constants (1, 2, 0.5) are allowed in expressions.

4. Missing or unreadable dimension: still create the variable with your best visual
   estimate and append:  // TODO: verify — unreadable on sketch

5. Do NOT invent features that are not drawn. Do NOT omit features that are drawn.
   If a feature is ambiguous (pocket vs through-hole, groove vs plain line), pick
   the most likely reading and record it in ASSUMPTIONS.

MACHINING DEFAULTS (use ONLY for a drawn feature that lacks a value; mark TODO)
   tool_d = 6.35 (1/4 in end mill); min_inside_corner_r = tool_d / 2.
   A drawn sharp inside corner becomes a corner of radius min_inside_corner_r
   (record in ASSUMPTIONS). min_wall = 6.
   Pocket depth = 0.5 * stock_z, never more than 0.7 * stock_z unless THRU.
   Juice groove: width 8, depth 6, inset 15 from the edge.

MODELING STYLE
   Use only core OpenSCAD (works in 2021.01 and in Manifold snapshots): cube,
   cylinder, sphere, linear_extrude, offset, hull, for, translate, rotate, mirror,
   difference, union, intersection. No include/use/import and no libraries.
   Rounded corners: offset(r=...) or hull() of cylinders. Chamfer/roundover:
   hull() of a few offset slices (at most 8). Round-bottom (dish) pockets:
   only if the section view shows them; otherwise flat floor.
   Keep the code simple and readable rather than clever. It must compile:
   balanced brackets, semicolons, no undefined variables.

EXAMPLE OF THE EXPECTED SHAPE (not the answer; the real values come from the sketch)

// =============================================================================
//  Кленовый лист — поднос с одним отсеком по форме листа
// =============================================================================
//  Контур — стилизованный  лист (многоугольник, 
//  черешок внизу), вписанный в квадрат size x size. Острия скруглены tip_r
//  (не меньше, чем может обойти контурная фреза), выемки — notch_r (больше
//  радиуса контурной фрезы 3.175). Отсек — контур, сдвинутый внутрь на rim_w;
//  его выступы скруглены pocket_r (больше радиуса чистовой фрезы 9.53), так что
//  узкие лопасти и черешок остаются сплошными. Дно со скруглением bowl_r.
//  Отверстие для подвеса делается.
// 
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

"""


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    img_path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else "part.scad"

    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("MOONSHOT_API_KEY")
    if not api_key:
        sys.exit("DEEPSEEK_API_KEY не задан (export DEEPSEEK_API_KEY=sk-...)")

    mime = mimetypes.guess_type(img_path)[0] or "image/jpeg"
    with open(img_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    client = OpenAI(api_key=api_key, base_url=BASE_URL)

    print(f"-> {MODEL}: отправляю {img_path} ({mime}) ...")
    resp = client.chat.completions.create(
        model=MODEL,
        temperature=0.2,  # низкая: нужна точность, не креатив
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
    )

    code = resp.choices[0].message.content.strip()
    # на случай, если модель всё же обернула в ```-фенсы
    code = re.sub(r"^```[a-zA-Z]*\s*", "", code)
    code = re.sub(r"\s*```$", "", code)

    with open(out_path, "w") as f:
        f.write(code + "\n")

    u = resp.usage
    if u:
        print(f"   токены: prompt={u.prompt_tokens}, completion={u.completion_tokens}")
    print(f"   сохранено -> {out_path}")
    print(f"   просмотр:   openscad {out_path}")


if __name__ == "__main__":
    main()
