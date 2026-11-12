# -*- coding: utf-8 -*-
"""Торцовка (surfacing/facing) прямоугольной заготовки.

Генерирует G-code растра строками (змейка) для выравнивания поверхности.

Запуск:
  python3 -m boardcam.surface --width 200 --height 300 --depth 2 --step 0.5
  python3 -m boardcam.surface --width 200 --height 300 --depth 2 --tool t1 --out out/face.nc

Параметры:
  --width   мм  — ширина заготовки (ось X)        [обязательно]
  --height  мм  — длина заготовки  (ось Y)        [обязательно]
  --depth   мм  — сколько срезать                 [обязательно]
  --step    мм  — глубина за один проход  (0.5)
  --overlap доля от диаметра, перекрытие строк (0.4)
  --tool    id  — фреза из data/tools.json (если не задан — первая в списке)
  --out     путь к .nc файлу  (out/surface.nc)
"""

import argparse
import json
import math
import os
import sys

from .cam.gcode import GCode
from .post.masso import render
from .jobs.run import project_root


# ── Загрузка данных ──────────────────────────────────────────────────────────

def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def _load_tools(root):
    raw = _load_json(os.path.join(root, "data", "tools.json"), [])
    # файл может быть списком или {"tools": [...]}
    if isinstance(raw, dict):
        return raw.get("tools", [])
    return raw if isinstance(raw, list) else []


def _load_machine(root):
    return _load_json(os.path.join(root, "data", "machine.json"), {})


def _get_tool(tools, tool_id):
    if not tools:
        # заглушка когда библиотека пустая
        return {"id": "dummy", "name": "12mm flat endmill",
                "dia": 12.0, "shank": 12.0,
                "rpm": 18000, "feed": 2000, "plunge": 500, "ramp": 800}
    if not tool_id:
        return tools[0]
    for t in tools:
        if t.get("id") == tool_id:
            return t
    sys.exit("Фреза '%s' не найдена в data/tools.json" % tool_id)


# ── Простой объект-заглушка чтобы masso.render мог читать blank.size_x ──────

class _Blank:
    def __init__(self, w, h, thick):
        self.size_x = w
        self.size_y = h
        self.thick  = thick
        self.origin = "corner"


# ── Генерация G-code ─────────────────────────────────────────────────────────

def generate(width, height, depth, step, overlap, tool, machine):
    """Возвращает объект GCode с телом торцовки."""
    dia    = float(tool["dia"])
    feed   = float(tool["feed"])
    plunge = float(tool["plunge"])

    z_safe = float(machine.get("z_safe", 5.0))
    z_link = float(machine.get("z_link", 3.0))

    row_step = dia * (1.0 - overlap)        # шаг строки по Y
    n_layers = math.ceil(depth / step)      # кол-во слоёв

    g = GCode()
    g.c("(Торцовка %.0f x %.0f мм, глубина %.2f мм, фреза D%.1f)" %
        (width, height, depth, dia))
    g.c("(Слоёв: %d x %.2f мм, строк: %d, шаг %.2f мм)" %
        (n_layers, step, math.ceil(height / row_step) + 1, row_step))

    # Поднять перед началом
    g.go(z=z_safe, move="G0")

    for layer in range(n_layers):
        z = -step * (layer + 1)
        # не глубже заданной глубины
        if z < -depth:
            z = -depth

        g.c("( --- слой %d / %d  Z=%.3f --- )" % (layer + 1, n_layers, z))

        # Строки: Y от 0 до height с шагом row_step, + финальная строка на Y=height
        y_values = []
        y = 0.0
        while y <= height + 1e-6:
            y_values.append(min(y, height))
            y += row_step
        if not y_values or abs(y_values[-1] - height) > 1e-6:
            y_values.append(height)

        for row_idx, y in enumerate(y_values):
            # Змейка: чётные слева направо, нечётные справа налево
            if row_idx % 2 == 0:
                x_start, x_end = 0.0, width
            else:
                x_start, x_end = width, 0.0

            # Позиционирование: подъём → рапид → опускание
            g.go(z=z_safe, move="G0")
            g.go(x=x_start, y=y, move="G0")
            g.go(z=z, f=plunge)          # врезание

            # Рабочий ход по X
            g.go(x=x_end, y=y, f=feed)

    # Финал
    g.go(z=z_safe, move="G0")
    g.go(x=0.0, y=0.0, move="G0")
    g.c("M05")
    g.c("M30")

    return g, z_safe


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Генерация G-code торцовки прямоугольной заготовки",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--width",   type=float, required=True, help="Ширина заготовки, мм (X)")
    p.add_argument("--height",  type=float, required=True, help="Длина заготовки, мм (Y)")
    p.add_argument("--depth",   type=float, required=True, help="Сколько срезать, мм")
    p.add_argument("--step",    type=float, default=0.5,   help="Глубина за проход, мм (0.5)")
    p.add_argument("--overlap", type=float, default=0.4,   help="Перекрытие строк 0..1 (0.4)")
    p.add_argument("--tool",    type=str,   default=None,  help="ID фрезы из data/tools.json")
    p.add_argument("--out",     type=str,   default="out/surface.nc", help="Выходной .nc файл")
    args = p.parse_args()

    root    = project_root()
    tools   = _load_tools(root)
    machine = _load_machine(root)
    tool    = _get_tool(tools, args.tool)

    print("Фреза   : %s  D=%.1f мм  feed=%d  plunge=%d" %
          (tool["name"], tool["dia"], tool["feed"], tool["plunge"]))
    print("Заготовка: %.0f x %.0f мм, срезать %.2f мм (шаг %.2f мм)" %
          (args.width, args.height, args.depth, args.step))

    gcode, z_safe = generate(
        width=args.width, height=args.height,
        depth=args.depth, step=args.step,
        overlap=args.overlap, tool=tool, machine=machine,
    )

    blank = _Blank(args.width, args.height, args.depth)
    ctx = {
        "z_safe":   z_safe,
        "blank":    blank,
        "machine":  machine,
        "shape":    "surface",
        "preset":   None,
        "job":      "surface",
        "stamp":    "-",
        "zero":     "X0 Y0 = ЛЕВЫЙ БЛИЖНИЙ УГОЛ заготовки, Z0 = верх",
        "openscad_version": "-",
        "material": "-",
    }

    title = "Торцовка %.0f x %.0f мм, глубина %.1f мм" % (args.width, args.height, args.depth)
    nc_text = render(title, tool, ctx, gcode)

    out = args.out
    if not os.path.isabs(out):
        out = os.path.join(root, out)
    os.makedirs(os.path.dirname(out), exist_ok=True)

    with open(out, "w", encoding="utf-8") as f:
        f.write(nc_text)

    lines = nc_text.count("\n")
    print("Записано: %s  (%d строк G-code)" % (out, lines))


if __name__ == "__main__":
    main()
