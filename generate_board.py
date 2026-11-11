#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
 Круглая доска-менажница (3 отсека) - параметрический генератор G-code
==============================================================================
 Постпроцессор : MASSO G3 Touch (Onefinity Elite 2, Woodworker 32x32)
 Единицы       : МИЛЛИМЕТРЫ (G21), абсолютные координаты (G90)
 Нули          : X0 Y0 = ЛЕВЫЙ БЛИЖНИЙ УГОЛ квадратной заготовки (ORIGIN='corner'),
                 Z0 = верх заготовки; все рабочие Z отрицательные = в материал
------------------------------------------------------------------------------
 Геометрия: круглый диск, наружный бортик, 3 кармана с плоским дном и
           скруглением "стенка-дно" R6.35 мм (след фрезы Whiteside 1372),
           разделённые тремя Y-образными перемычками.
------------------------------------------------------------------------------
 Запуск: python3 generate_board.py    ->  nc/*.nc, preview.svg, report.txt
         python3 serve.py              ->  ползунки в браузере
==============================================================================
"""

VERSION = "3.1.3-mm"  # 3.0 = дюймовая, 3.1 = метрическая; патч растёт при каждой правке
# 3.1.1  раскладки: фикс выброшенных колец растра, 360-градусная дуга, толщина
#        стенки у прямых секторов, texts.json подключён, min=0 у закрутки
# 3.1.2  превью рисует карман таким, каким его оставит фреза 1372 (R9.53)
# 3.1.3  скругления считаются по самой стенке, а не по касательной к ней:
#        ушли иглы на контуре и съеденный корень стенки; радиус ужимается,
#        если не влезает; отрисовка вернулась к номинальному контуру

import json
import math
import os
import re

# =============================================================================
# 1. РАЗМЕРЫ ИЗДЕЛИЯ
# =============================================================================
# ВСЕ РАЗМЕРЫ - В МИЛЛИМЕТРАХ, подачи - в мм/мин.
BOARD_DIA     = 406.4      # диаметр готового изделия (406.4 = 16")
THICK         = 25.0       # ВЫСОТА/толщина менажницы - меняйте свободно
POCKET_DEPTH  = 12.0       # глубина карманов (<= 15.8 - режущая часть 1372)
RIM_W         = 25.0       # ширина наружного бортика
SPIRAL_SWEEP  = 200.0      # градус, на который каждая стенка-спираль закручена от втулки к бортику
HUB_R         = 30.0       # радиус центральной втулки, вокруг которой закручены стенки
WALL_W        = 12.0       # ТОЛЩИНА СТЕНКИ (постоянна по всей длине)
CORNER_F      = 14.0       # скругление стенка/бортик и стенка/втулка в плане (> 9.53 = R фрезы 1372)
N_POCKETS     = 3          # количество отсеков «вертушки»

WALL_ALLOW    = 0.6        # припуск на стенки (черновой проход)
FLOOR_ALLOW   = 0.6        # припуск на дно

# ЗАГОТОВКА (исходный щит)
BLANK_SIZE    = 430.0      # сторона КВАДРАТНОЙ заготовки (доска центрируется в ней)
BLANK_THICK   = 25.0       # толщина заготовки как есть; излишек над THICK снимается торцовкой
ORIGIN        = 'corner'   # 'corner' = X0Y0 в левом ближнем углу заготовки | 'center'
PROFILE_EXTRA = 1.2        # заглубление контура в жертвенник
TABS          = 5
TAB_LEN       = 23.0
TAB_H         = 4.0
TAB_RAMP      = 13.0       # длина плавного съезда/выезда на таб (без вертикального ныряния)

Z_RETRACT     = 9.0
Z_LINK        = 3.0
SAG_ROUGH     = 0.06       # допуск линеаризации дуг (черновая)
SAG_FINISH    = 0.01       # то же для чистовой
RAMP_LEN      = 25.0       # длина плавного входа по дуге

JUICE_GROOVE  = False      # True -> жёлоб фрезой 1406 (нужен бортик >= 32 мм)
FLATTEN       = False      # True -> файл 00 (нужна торцовочная фреза, её нет в наборе)
PROFILE_MODE  = 'auto'     # 'auto' = сам решит full/flip по длине режущей части
# Скругления наружной кромки НЕТ: ни 1372 (bowl&tray), ни 1406 (round nose) не делают
# наружный roundover - у обеих плоское/вогнутое дно, они срежут бортик. Кромку - вручную
# (фреза-roundover с подшипником в ручном фрезере) или шлифовкой.
WOOD          = 'maple'    # порода: масштабирует подачи/обороты (см. WOODS ниже)
COVERAGE_STEP = 3.0        # шаг сетки контроля покрытия дна

# =============================================================================
# 2. ИНСТРУМЕНТ (базовые режимы для ТВЁРДОГО КЛЁНА)
# =============================================================================
BITS = [
    {
        "id": "em",
        "role": "rough",
        "title": 'Molly Mill 1/4" (черновая)',
        "name": 'IDC/Cadence "Molly Mill" 8675309-250MM, 1/4" drilling endmill',
        "dia": 6.35, "rpm": 16000, "rpm_max": 24000, "loc": 19.0,
        "feed": 2300.0, "plunge": 300.0, "ramp": 1270.0, "feed_contour": 1400.0,
        "stepover": 3.2, "doc": 3.8, "num": 1, "color": "#ff3b30"
    },
    {
        "id": "bowl",
        "role": "finish",
        "title": 'Whiteside 1372 (чистовая)',
        "name": 'Whiteside 1372 Bowl & Tray, D19.05 / R6.35',
        "dia": 19.05, "rpm": 16000, "rpm_max": 18000, "loc": 15.8,
        "feed": 2000.0, "plunge": 450.0, "ramp": 1140.0,
        "stepover": 5.6, "doc": 12.7, "num": 2, "color": "#0a84ff"
    },
    {
        "id": "profile",
        "role": "profile",
        "title": 'Molly Mill 1/4" (контур)',
        "name": 'IDC/Cadence "Molly Mill" 8675309-250MM, 1/4" (контур)',
        "dia": 6.35, "rpm": 16000, "rpm_max": 24000, "loc": 19.0,
        "feed": 1270.0, "plunge": 250.0, "ramp": 1000.0,
        "stepover": 0.0, "doc": 3.8, "num": 1, "color": "#22a04a"
    },
    {
        "id": "surf",
        "role": "surf",
        "title": 'Торцовочная фреза',
        "name": 'Surfacing bit (торцовочная)',
        "dia": 38.1, "rpm": 12000, "rpm_max": 14000, "loc": 12.7,
        "feed": 3000.0, "plunge": 500.0, "ramp": 1500.0,
        "stepover": 12.7, "doc": 0.5, "num": 3, "color": "#999"
    }
]

# Для обратной совместимости, пока не переписаны все вызовы:
def get_tool(role):
    for b in BITS:
        if b['role'] == role:
            return b
    return BITS[0]

TOOL_EM = get_tool('rough')
TOOL_BOWL = get_tool('finish')
TOOL_PROFILE = get_tool('profile')
TOOL_SURF = get_tool('surf')

# Подачи выше - базовые для ТВЁРДОГО КЛЁНА. Под другую породу масштабируются
# множителем scale. Чем мягче дерево (меньше Janka) - тем быстрее можно резать.
WOODS = {
    'maple':   dict(scale=1.00, rpm=16000, dial=3, note='клён твёрдый (Janka ~1450)'),
    'walnut':  dict(scale=1.10, rpm=16000, dial=3, note='орех чёрный (Janka ~1010)'),
    'cherry':  dict(scale=1.10, rpm=16000, dial=3, note='вишня (Janka ~950)'),
    'birch':   dict(scale=1.00, rpm=16000, dial=3, note='берёза жёлтая (Janka ~1260)'),
    'oak':     dict(scale=1.00, rpm=16000, dial=3, note='дуб белый (Janka ~1360)'),
    'ash':     dict(scale=1.00, rpm=16000, dial=3, note='ясень (Janka ~1320)'),
    'hickory': dict(scale=0.85, rpm=16000, dial=3, note='гикори (Janka ~1820)'),
    'jatoba':  dict(scale=0.70, rpm=19000, dial=4, note='ятоба (Janka ~2350)'),
    'soft':    dict(scale=1.30, rpm=16000, dial=3, note='мягкое (липа/ольха/сосна)'),
}

# Описания для UI: texts.json (необязателен). note остаётся как есть - он идёт
# в шапку G-кода и в отчёт; для интерфейса добавляем title / janka / hint.
try:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'texts.json'),
              encoding='utf-8') as _f:
        _TEXTS = json.load(_f)
except (OSError, ValueError):
    _TEXTS = {}
for _k, _w in WOODS.items():
    _parts = _w['note'].split(' (Janka ~')
    _w['title'] = _parts[0]
    _w['janka'] = int(_parts[1].rstrip(')')) if len(_parts) > 1 else None
    _w['hint'] = _TEXTS.get('woods', {}).get(_k, '')
for _b in BITS:
    _b['note'] = _TEXTS.get('bits', {}).get(_b['id'], '')

# =============================================================================
# 3. МАТЕМАТИКА
# =============================================================================
TWO_PI = 2.0 * math.pi


def solve2(n1, k1, n2, k2):
    """Пересечение прямых dot(p,n1)=k1 и dot(p,n2)=k2 (правило Крамера)."""
    det = n1[0] * n2[1] - n1[1] * n2[0]
    return ((k1 * n2[1] - n1[1] * k2) / det, (n1[0] * k2 - k1 * n2[0]) / det)


def ang(v):
    return math.atan2(v[1], v[0])


def pt(rho, t):
    return (rho * math.cos(t), rho * math.sin(t))


def chord_for(radius, sag):
    return max(2.0 * math.sqrt(max(2.0 * radius * sag, 1e-12)), 0.0025)


def circle_points(c, r, sag):
    """Полная окружность (замкнутая, без дублирования первой точки)."""
    n = max(8, int(math.ceil(TWO_PI * r / chord_for(r, sag))))
    return [(c[0] + r * math.cos(TWO_PI * i / n),
             c[1] + r * math.sin(TWO_PI * i / n)) for i in range(n)]


def arc_points(c, r, a0, a1, sag):
    d = (a1 - a0 + math.pi) % TWO_PI - math.pi
    if abs(d) < 1e-12:
        return [(c[0] + r * math.cos(a0), c[1] + r * math.sin(a0))]
    n = max(2, int(math.ceil(abs(d) * r / chord_for(r, sag))))
    return [(c[0] + r * math.cos(a0 + d * i / n),
             c[1] + r * math.sin(a0 + d * i / n)) for i in range(n + 1)]


def poly_area(pts):
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return 0.5 * s


def dist_point_seg(p, a, b):
    vx, vy = b[0] - a[0], b[1] - a[1]
    wx, wy = p[0] - a[0], p[1] - a[1]
    L2 = vx * vx + vy * vy
    if L2 < 1e-18:
        return math.hypot(wx, wy)
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / L2))
    return math.hypot(wx - t * vx, wy - t * vy)


def dist_to_poly(p, poly):
    return min(dist_point_seg(p, poly[i], poly[(i + 1) % len(poly)])
               for i in range(len(poly)))


# =============================================================================
# 4. КАРМАН С СУЖЕННЫМИ (РАСШИРЯЮЩИМИСЯ К БОРТИКУ) ПЕРЕМЫЧКАМИ
# =============================================================================
# Стена кармана - прямая от втулки к бортику. Скругления - точные
# аналитические: "линия-линия" у втулки и "линия-окружность" у бортика.
# Перемычка между соседними карманами сама получается узкой у втулки и
# широкой у бортика.
# =============================================================================

def u(a):
    return (math.cos(a), math.sin(a))


# =============================================================================
# СПИРАЛЬНАЯ «ВЕРТУШКА»: 3 тонкие изогнутые стенки, закрученные в одну сторону
# =============================================================================
# Каждая стенка — логарифмическая спираль от втулки (HUB_R) до бортика (R_p),
# закрученная на SPIRAL_SWEEP. Стенка = две спирали, смещённые по углу на
# WALL_ANG. Отсек — область между стенкой i (задняя кромка) и стенкой i+1
# (передняя кромка) + дуга бортика + дуга втулки, со скруглениями CORNER_F.
# =============================================================================

def spiral_edge(i, off_w, R_p, r_h, delta, N=200):
    """Логарифмическая спираль r_h->R_p за угол delta.

    Стартовый угол сектора = i * 360° / N_POCKETS.

    При SPIRAL_SWEEP == 0 делаем прямые «радиальные» стенки: стены идут
    ровными лучами от HUB_R к R_p, без закрутки. В этом режиме off_w
    трактуем как физическое смещение стенки (толщина) в миллиметрах.
    """
    base = i * math.radians(360.0 / max(1, N_POCKETS))

    # ----- РЕЖИМ ПРЯМЫХ СЕКТОРОВ (SPIRAL_SWEEP == 0) -----
    if abs(delta) < 1e-9:
        # Центральная ось сектора идёт под углом base.
        # Для смещённой стенки считаем постоянный угловой сдвиг Δθ так,
        # чтобы толщина по дуге на среднем радиусе примерно равнялась off_w.
        out = []
        for j in range(N + 1):
            t = j / float(N)
            r = r_h + (R_p - r_h) * t
            a = base + math.asin(min(1.0, off_w / r))   # ровно off_w мм по нормали
            out.append((r * math.cos(a), r * math.sin(a)))
        return out

    # ----- ОБЫЧНАЯ ЛОГАРИФМИЧЕСКАЯ СПИРАЛЬ (вертушка) -----
    k = math.log(R_p / r_h) / delta
    out = []
    for j in range(N + 1):
        t = delta * j / N
        r = r_h * math.exp(k * t)
        # off_w здесь — смещение в дюймах вдоль дуги спирали (как было изначально)
        a = base + t + off_w / r
        out.append((r * math.cos(a), r * math.sin(a)))
    return out

def wall_thickness():
    """Сколько дерева реально остаётся в стенке: минимальное расстояние между
    двумя кромками одной стенки. У прямых секторов = WALL_W, у спирали меньше -
    off_w в spiral_edge отложен по дуге, а не по нормали к кромке."""
    R_p = BOARD_DIA / 2.0 - RIM_W
    d = math.radians(SPIRAL_SWEEP)
    A = spiral_edge(0, 0.0, R_p, HUB_R, d)
    B = spiral_edge(0, WALL_W, R_p, HUB_R, d)
    return min(min(dist_point_seg(b, A[j], A[j + 1]) for j in range(len(A) - 1))
               for b in B[:-1])


def min_corner_angle(pts):
    """Самый острый угол контура, градусы. 180 = гладко, 0 = игла."""
    n, best = len(pts), 180.0
    for i in range(n):
        a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
        v1 = (a[0] - b[0], a[1] - b[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        L = math.hypot(*v1) * math.hypot(*v2)
        if L < 1e-12:
            continue
        best = min(best, math.degrees(math.acos(
            max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / L)))))
    return best


def wall_span(w, p_hub, p_rim):
    """Вершины стенки строго между точками касания скруглений у втулки и у
    бортика. Радиус вдоль стенки монотонен, поэтому отбор по радиусу точен -
    поиск ближайшей вершины промахивался за точку касания и оставлял иглу."""
    r0, r1 = math.hypot(*p_hub), math.hypot(*p_rim)
    return [q for q in w if r0 < math.hypot(*q) < r1]


def curve_circle_fillet(w, other, R, f, inside):
    """Скругление радиуса f между СТЕНКОЙ w (полилиния) и окружностью |p|=R.

    Предшественник считал стенку прямой - касательной в её конце. У втулки
    спираль загибается так круто, что точки касания промахивались мимо стенки,
    дуги перелетали друг друга и на контуре оставались иглы, а корень стенки
    съедался соседним карманом. Здесь центр скругления ищется по самой кривой:
    он лежит на окружности |c| = R -/+ f, и от него до стенки должно быть ровно f.
    Функция расстояния монотонна по углу - хватает сканирования и деления пополам.

    Возвращает (центр, точка касания на стенке, точка касания на окружности)
    или None, если скругление такого радиуса в угол не вписывается.
    """
    Rc = R - f if inside else R + f
    end = w[-1] if inside else w[0]
    opp = other[-1] if inside else other[0]     # тот же конец противоположной стенки:
    th0 = ang(end)                              # карман лежит между ними
    side = 1.0 if (ang(opp) - th0 + math.pi) % TWO_PI - math.pi > 0 else -1.0

    def gap(phi):
        th = th0 + side * phi
        c = (Rc * math.cos(th), Rc * math.sin(th))
        return min(dist_point_seg(c, w[i], w[i + 1]) for i in range(len(w) - 1)) - f

    lo, hi, N = 0.0, None, 400
    for i in range(1, N + 1):
        phi = math.pi / 2.0 * i / N
        if gap(phi) >= 0.0:
            hi = phi
            break
        lo = phi
    if hi is None:
        return None
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if gap(mid) < 0.0:
            lo = mid
        else:
            hi = mid
    th = th0 + side * hi
    c = (Rc * math.cos(th), Rc * math.sin(th))
    j = min(range(len(w) - 1), key=lambda i: dist_point_seg(c, w[i], w[i + 1]))
    a0, b0 = w[j], w[j + 1]
    vx, vy = b0[0] - a0[0], b0[1] - a0[1]
    t = max(0.0, min(1.0, ((c[0] - a0[0]) * vx + (c[1] - a0[1]) * vy) / (vx * vx + vy * vy)))
    wc = (a0[0] + t * vx, a0[1] + t * vy)
    cc = (R * c[0] / math.hypot(*c), R * c[1] / math.hypot(*c))
    return c, wc, cc


class Pocket:
    """Отсек «вертушки» между двумя спиральными стенками."""

    def __init__(self, wR, wL, R_p, r_h, fillet, sag):
        self.R = R_p
        self.r_h = r_h
        j = len(wR) // 2
        ref = ((wR[j][0] + wL[j][0]) / 2.0, (wR[j][1] + wL[j][1]) / 2.0)

        def build(f):
            """Контур кармана со скруглением радиуса f. None - f не влезает."""
            cs = [curve_circle_fillet(wR, wL, R_p, f, True),
                  curve_circle_fillet(wL, wR, R_p, f, True),
                  curve_circle_fillet(wR, wL, r_h, f, False),
                  curve_circle_fillet(wL, wR, r_h, f, False)]
            if any(c is None for c in cs):
                return None
            (c_rR, pr_R, prR_rim), (c_rL, pr_L, prL_rim) = cs[0], cs[1]
            (c_hR, ph_R, phR_hub), (c_hL, ph_L, phL_hub) = cs[2], cs[3]
            spanR, spanL = wall_span(wR, ph_R, pr_R), wall_span(wL, ph_L, pr_L)
            if not spanR or not spanL:      # скругления съели стенку целиком
                return None
            pts = []

            def add(pl):
                for q in pl:
                    if not pts or math.hypot(q[0] - pts[-1][0], q[1] - pts[-1][1]) > 1e-9:
                        pts.append(q)

            def fa(c, a, b):                # дуга скругления от a до b вокруг c
                return arc_points(c, f, ang((a[0] - c[0], a[1] - c[1])),
                                  ang((b[0] - c[0], b[1] - c[1])), sag)

            add(arc_points((0, 0), R_p, ang(prL_rim), ang(prR_rim), sag))
            add(fa(c_rR, prR_rim, pr_R))
            add([pr_R] + list(reversed(spanR)) + [ph_R])
            add(fa(c_hR, ph_R, phR_hub))
            add(arc_points((0, 0), r_h, ang(phR_hub), ang(phL_hub), sag))
            add(fa(c_hL, phL_hub, ph_L))
            add([ph_L] + spanL + [pr_L])
            add(fa(c_rL, pr_L, prL_rim))
            if math.hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1]) < 1e-6:
                pts = pts[:-1]
            return pts

        # Скругление, которое не влезает в угол, даёт перехлёст дуг и иглу на
        # контуре. Ужимаем радиус до влезающего и говорим об этом в отчёте.
        SMOOTH = 60.0
        pts = build(fillet)
        used = fillet
        if not pts or min_corner_angle(pts) < SMOOTH:
            lo, hi = 0.0, fillet
            for _ in range(12):
                mid = 0.5 * (lo + hi)
                q = build(mid)
                if q and min_corner_angle(q) >= SMOOTH:
                    lo, pts, used = mid, q, mid
                else:
                    hi = mid
        if used < fillet - 0.05:
            WARN.append("скругление %.1f мм в угол не влезает, взято %.1f мм%s"
                        % (fillet, used,
                           " - меньше радиуса фрезы 1372 (9.53), угол останется чистовым припуском"
                           if used < TOOL_BOWL['dia'] / 2.0 else ""))
        self.poly = pts
        self.area = abs(poly_area(pts))
        self.sign = 1.0 if poly_area(pts) > 0 else -1.0
        self.r_min = min(math.hypot(x, y) for (x, y) in pts)
        self.mid = ang(ref)
        self.R_p = R_p
        self._grid, self._cell = None, 12.0

    @classmethod
    def from_poly(cls, pts):
        """Создать карман из готового полигона (например, центральный карман)."""
        self = cls.__new__(cls)
        self.poly = pts
        self.area = abs(poly_area(pts))
        self.sign = 1.0 if poly_area(pts) > 0 else -1.0
        self.r_min = min(math.hypot(x, y) for (x, y) in pts)
        self.R = max(math.hypot(x, y) for (x, y) in pts)
        self.R_p = self.R
        self.mid = 0.0
        self._grid, self._cell = None, 12.0
        return self

    def offset_poly(self, r):
        pts = self.poly
        n = len(pts)
        out = []
        for i in range(n):
            p = pts[i]
            a = pts[(i - 1) % n]
            b = pts[(i + 1) % n]
            ti = (p[0] - a[0], p[1] - a[1])
            Li = math.hypot(*ti)
            to = (b[0] - p[0], b[1] - p[1])
            Lo = math.hypot(*to)
            if Li < 1e-12 or Lo < 1e-12:
                continue
            nx = -(ti[1] / Li + to[1] / Lo)
            ny = ti[0] / Li + to[0] / Lo
            L = math.hypot(nx, ny)
            if L < 1e-12:
                continue
            out.append((p[0] + self.sign * r * nx / L, p[1] + self.sign * r * ny / L))
        return out

    def build_grid(self, cell=12.0):
        g = {}
        n = len(self.poly)
        for i in range(n):
            a, b = self.poly[i], self.poly[(i + 1) % n]
            x0 = int(math.floor(min(a[0], b[0]) / cell))
            x1 = int(math.floor(max(a[0], b[0]) / cell))
            y0 = int(math.floor(min(a[1], b[1]) / cell))
            y1 = int(math.floor(max(a[1], b[1]) / cell))
            for cx in range(x0, x1 + 1):
                for cy in range(y0, y1 + 1):
                    g.setdefault((cx, cy), []).append((a, b))
        self._grid, self._cell = g, cell
        return g

    def dist_fast(self, p):
        cell = self._cell
        best = 1e9
        bx = int(math.floor(p[0] / cell))
        by = int(math.floor(p[1] / cell))
        for ring in range(0, 8):
            for cx in range(bx - ring, bx + ring + 1):
                for cy in range(by - ring, by + ring + 1):
                    if ring and max(abs(cx - bx), abs(cy - by)) != ring:
                        continue
                    for (a, b) in self._grid.get((cx, cy), ()):
                        d = dist_point_seg(p, a, b)
                        if d < best:
                            best = d
            if best <= ring * cell:
                break
        return best

    def raster_intervals(self, rho, Rt):
        lo, hi = self.mid - math.pi, self.mid + math.pi
        n = max(24, int((hi - lo) * rho / 2.0))
        ok = []
        for i in range(n + 1):
            t = lo + (hi - lo) * i / n
            p = (rho * math.cos(t), rho * math.sin(t))
            ok.append(point_inside(p, self.poly) and self.dist_fast(p) >= Rt - 0.025)
        if not any(ok):
            return []

        def refine(t_yes, t_no):
            for _ in range(18):
                tm = 0.5 * (t_yes + t_no)
                p = (rho * math.cos(tm), rho * math.sin(tm))
                if point_inside(p, self.poly) and self.dist_fast(p) >= Rt - 0.025:
                    t_yes = tm
                else:
                    t_no = tm
            return t_yes

        ivs = []
        i = 0
        while i <= n:
            if not ok[i]:
                i += 1
                continue
            j = i
            while j + 1 <= n and ok[j + 1]:
                j += 1
            a0 = lo + (hi - lo) * i / n
            a1 = lo + (hi - lo) * j / n
            t0 = a0 if i == 0 else refine(a0, lo + (hi - lo) * (i - 1) / n)
            t1 = a1 if j == n else refine(a1, lo + (hi - lo) * (j + 1) / n)
            if (t1 - t0) * rho > 0.5:
                if t1 - t0 > TWO_PI - 1e-9:     # полный круг: 360-градусная дуга невыразима
                    tm = 0.5 * (t0 + t1)        # в arc_points, режем на два полукольца
                    ivs.append((t0, tm, 'bnd', 'bnd'))
                    ivs.append((tm, t1, 'bnd', 'bnd'))
                else:
                    ivs.append((t0, t1, 'bnd', 'bnd'))
            i = j + 1
        return ivs

    def raster(self, r_tool, allow, stepover, F_extra=0.0):
        Rt = r_tool + allow + F_extra
        self.build_grid()
        rmax = self.R - Rt
        # Если карман накрывает центр, rmin = 0, иначе self.r_min - Rt
        if point_inside((0, 0), self.poly):
            rmin = 0.0
        else:
            rmin = max(2.5, self.r_min - Rt)
        out = []
        rho = rmax
        empty = 0
        while rho >= rmin and empty < 4:
            ivs = self.raster_intervals(rho, Rt)
            if ivs:
                out.append((rho, ivs))
                empty = 0
            else:
                empty += 1
            rho -= stepover
        return out, Rt, rmin


def build_pockets():
    layout_name = globals().get('LAYOUT', 'spiral')
    R_p = BOARD_DIA / 2.0 - RIM_W
    delta = math.radians(SPIRAL_SWEEP)
    pockets = []

    if layout_name in ('spiral', 'sectors'):
        leads = [spiral_edge(i, 0.0, R_p, HUB_R, delta) for i in range(N_POCKETS)]
        trails = [spiral_edge(i, WALL_W, R_p, HUB_R, delta) for i in range(N_POCKETS)]
        pockets = [Pocket(trails[i], leads[(i + 1) % N_POCKETS], R_p, HUB_R, CORNER_F, SAG_FINISH)
                   for i in range(N_POCKETS)]
    elif layout_name == 'spiral_center':
        # Те же отсеки, но HUB_R имеет смысл радиуса центрального кармана + WALL_W
        hub_r_with_wall = HUB_R
        center_r = hub_r_with_wall - WALL_W
        leads = [spiral_edge(i, 0.0, R_p, hub_r_with_wall, delta) for i in range(N_POCKETS)]
        trails = [spiral_edge(i, WALL_W, R_p, hub_r_with_wall, delta) for i in range(N_POCKETS)]
        pockets = [Pocket(trails[i], leads[(i + 1) % N_POCKETS], R_p, hub_r_with_wall, CORNER_F, SAG_FINISH)
                   for i in range(N_POCKETS)]
        # Добавляем центральный карман
        center_poly = circle_points((0, 0), center_r, SAG_FINISH)
        pockets.append(Pocket.from_poly(center_poly))
    else:
        raise ValueError("неизвестная раскладка LAYOUT=%r" % (layout_name,))

    return pockets


LAYOUTS = [
    {"id": "spiral", "title": "Вертушка (3 отсека)", "n_pockets": 3, "center": False,
     "defaults": {"N_POCKETS": 3, "SPIRAL_SWEEP": 200, "LAYOUT": "spiral"}},
    {"id": "spiral_center", "title": "Вертушка с центром (5)", "n_pockets": 5, "center": True,
     "defaults": {"N_POCKETS": 5, "SPIRAL_SWEEP": 160, "LAYOUT": "spiral_center"}},
    {"id": "sectors", "title": "Прямые сектора (4)", "n_pockets": 4, "center": False,
     "defaults": {"N_POCKETS": 4, "SPIRAL_SWEEP": 0, "LAYOUT": "sectors"}},
]
LAYOUT = 'spiral'


def point_inside(p, poly):
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xin:
                inside = not inside
    return inside


def build_seg_grid(segs, cell=12.0):
    grid = {}
    for (a, b) in segs:
        cx0 = int(math.floor(min(a[0], b[0]) / cell))
        cx1 = int(math.floor(max(a[0], b[0]) / cell))
        cy0 = int(math.floor(min(a[1], b[1]) / cell))
        cy1 = int(math.floor(max(a[1], b[1]) / cell))
        for cx in range(cx0, cx1 + 1):
            for cy in range(cy0, cy1 + 1):
                grid.setdefault((cx, cy), []).append((a, b))
    return grid


def reachable(pk, p, r_tool):
    """Существует ли допустимое положение центра фрезы, накрывающее точку p."""
    for k in range(1, 4):
        rad = r_tool * k / 3.0
        for i in range(16):
            a = TWO_PI * i / 16.0
            c = (p[0] + rad * math.cos(a), p[1] + rad * math.sin(a))
            if point_inside(c, pk.poly) and pk.dist_fast(c) >= r_tool:
                return True
    return point_inside(p, pk.poly) and pk.dist_fast(p) >= r_tool


def coverage_check(pk, segs, r_tool, min_bound_dist, step, cell=12.0):
    """Все точки кармана, удалённые от контура не менее min_bound_dist,
    должны попадать в диск радиуса r_tool от траектории."""
    grid = build_seg_grid(segs, cell)
    xs = [p[0] for p in pk.poly]
    ys = [p[1] for p in pk.poly]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    tested = missed = hard = 0
    worst = 0.0
    nx = int((xmax - xmin) / step)
    ny = int((ymax - ymin) / step)
    for i in range(nx + 1):
        for j in range(ny + 1):
            p = (xmin + i * step, ymin + j * step)
            if not point_inside(p, pk.poly):
                continue
            if dist_to_poly(p, pk.poly) < min_bound_dist:
                continue
            tested += 1
            best = 1e9
            cx, cy = int(math.floor(p[0] / cell)), int(math.floor(p[1] / cell))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for (a, b) in grid.get((cx + dx, cy + dy), ()):
                        d = dist_point_seg(p, a, b)
                        if d < best:
                            best = d
            if best > r_tool + 0.25:
                missed += 1
                if reachable(pk, p, r_tool):      # фреза сюда физически влезает - это дыра
                    hard += 1
                    worst = max(worst, best - r_tool)
    return tested, missed, hard, worst


def add(pts, new):
    for p in new:
        if not pts or math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) > 1e-9:
            pts.append(p)


def off():
    """Смещение детали в координаты станка: ноль в углу заготовки или в центре."""
    h = BLANK_SIZE / 2.0 if ORIGIN == 'corner' else 0.0
    return h, h


def zero_note():
    if ORIGIN == 'corner':
        return ("X0 Y0 = ЛЕВЫЙ БЛИЖНИЙ УГОЛ квадрата %.1f мм, Z0 = верх заготовки"
                % BLANK_SIZE)
    return "X0 Y0 = центр заготовки, Z0 = верх заготовки"


# Регулятор оборотов Makita RT0701C: по замерам тахометром на позициях 2..5
# зависимость линейна, rpm ~ 5000*dial + 2000. ЭТО КАЛИБРОВКА - проверьте
# своим тахометром и при необходимости поправьте два числа ниже.
DIAL_K, DIAL_B = 5000.0, 2000.0


def dial_for(rpm):
    return max(1.0, min(6.0, (rpm - DIAL_B) / DIAL_K))


WARN = []


def fnum(v):
    s = "%.3f" % v
    s = s.rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


class GCode:
    def __init__(self):
        self.L = []
        self.xy = (0.0, 0.0)
        self.z = 0.0
        self.cut_len = 0.0
        self.path = []
        self.segs = []

    def c(self, s=''):
        self.L.append(s)

    def go(self, x=None, y=None, z=None, f=None, move='G1'):
        nx = self.xy[0] if x is None else x
        ny = self.xy[1] if y is None else y
        nz = self.z if z is None else z
        if f is not None:
            self.cut_len += math.hypot(nx - self.xy[0], ny - self.xy[1])
            self.path.append((nx, ny))
            self.segs.append((self.xy, (nx, ny)))
        ox, oy = off()
        line = move
        if x is not None:
            line += " X" + fnum(x + ox)
        if y is not None:
            line += " Y" + fnum(y + oy)
        if z is not None:
            line += " Z" + fnum(z)
        if f is not None:
            line += " F" + fnum(f)
        self.L.append(line)
        self.xy = (nx, ny)
        self.z = nz

    def text(self):
        return "\n".join(self.L) + "\n"


def header(g, title, tool, zero_note):
    g.c("(" + "=" * 68 + ")")
    g.c("( " + title)
    g.c("( generate_board.py v%s  |  единицы: МИЛЛИМЕТРЫ (G21)" % VERSION)
    g.c("( " + "=" * 68 + ")")
    g.c("( TOOL     : %s" % tool['name'])
    g.c("( DIA      : %.2f мм, хвостовик 6.35 мм" % tool['dia'])
    g.c("( RPM      : S%d  (Makita RT0701C регулятор ~%.1f)" % (tool['rpm'], dial_for(tool['rpm'])))
    g.c("( FEEDS    : рабочая %.0f / врезание %.0f / рампа %.0f мм/мин"
        % (tool['feed'], tool['plunge'], tool['ramp']))
    g.c("( ZERO     : %s" % zero_note)
    g.c("( STOCK    : квадрат %.1f x %.1f мм, доска центрирована в нём" % (BLANK_SIZE, BLANK_SIZE))
    g.c("( WOOD     : %s" % WOODS.get(WOOD, WOODS['maple'])['note'])
    g.c("( CONTROL  : MASSO G3 - Onefinity Elite 2 Woodworker, поле 812 x 812 мм")
    g.c("(" + "=" * 68 + ")")
    g.c("G21 G17 G90 G94")
    g.c("G54")
    g.c("M05")
    g.c("S%d M03" % tool['rpm'])
    g.c("G0 Z" + fnum(Z_RETRACT))


def link_move(pk, cur, p_next, tag_next, Rt, r_tool, allow):
    """Безопасная связка конца дуги со следующей. None -> отвод."""
    if cur is None:
        return None
    x0, y0 = cur[0]
    x1, y1 = p_next
    L = math.hypot(x1 - x0, y1 - y0)
    n = max(2, int(L / 1.2))
    for i in range(n + 1):        # проверяем ВЕСЬ отрезок связки, а не только его конец
        p = (x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n)
        if not point_inside(p, pk.poly) or pk.dist_fast(p) < Rt - 0.05:
            return None
    return [p_next]


def _closest_on_poly(p, poly):
    """Ближайшая точка на контуре кармана."""
    best, bq = 1e18, None
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        vx, vy = b[0] - a[0], b[1] - a[1]
        L2 = vx * vx + vy * vy
        t = 0.0 if L2 < 1e-18 else max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L2))
        q = (a[0] + t * vx, a[1] + t * vy)
        d = math.hypot(p[0] - q[0], p[1] - q[1])
        if d < best:
            best, bq = d, q
    return bq, best


def _snap_in(pk, p, R):
    """Вернуть точку обратно на расстояние R от стенки (наивный эквидистант
    на углах уезжает наружу). None - если в этом месте фреза не помещается."""
    for _ in range(6):
        ins = point_inside(p, pk.poly)
        if ins and pk.dist_fast(p) >= R - 0.05:
            return p
        q, d = _closest_on_poly(p, pk.poly)
        vx, vy = p[0] - q[0], p[1] - q[1]
        L = math.hypot(vx, vy)
        if L < 1e-9:
            return None
        sgn = 1.0 if ins else -1.0
        p = (q[0] + sgn * vx / L * R, q[1] + sgn * vy / L * R)
    return p if (point_inside(p, pk.poly) and pk.dist_fast(p) >= R - 0.1) else None


def contour_runs(pk, R, tol=0.1):
    """Обход стенки на расстоянии R центром фрезы.

    Наивный эквидистант (offset_poly) в узких местах самопересекается и вылезает
    ЗА карман - по нему фреза 3/4" срезала бы бортик и стенки. Поэтому каждую
    точку проверяем (внутри кармана и до стенки не ближе R) и режем только
    непрерывные годные куски. Возвращает (список проходов, сколько точек выброшено).
    """
    pk.build_grid()
    raw = pk.offset_poly(R)
    pts = [_snap_in(pk, p, R) or p for p in raw]
    good = [point_inside(p, pk.poly) and pk.dist_fast(p) >= R - tol for p in pts]
    # середина хорды между соседними точками тоже не должна резать стенку
    n = len(pts)
    for i in range(n):
        if not (good[i] and good[(i + 1) % n]):
            continue
        a, b = pts[i], pts[(i + 1) % n]
        m = (0.5 * (a[0] + b[0]), 0.5 * (a[1] + b[1]))
        if not point_inside(m, pk.poly) or pk.dist_fast(m) < R - tol:
            good[(i + 1) % n] = False
    if all(good):
        return [pts + [pts[0]]], 0
    if not any(good):
        return [], n
    k0 = good.index(False)                     # старт с плохой точки -> ни один кусок не рвётся на шве
    runs, cur = [], []
    for i in range(n):
        k = (k0 + i) % n
        if good[k]:
            cur.append(pts[k])
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return [r for r in runs if len(r) >= 4], good.count(False)


def cut_contour(g, pk, z, tool, Rt):
    """Обход стенки на расстоянии Rt: только там, где фреза реально помещается."""
    runs, nbad = contour_runs(pk, Rt)
    g.c("(   contour pass at %.3f from wall: %d run(s), %d pts skipped (too narrow) )"
        % (Rt, len(runs), nbad))
    fc = tool.get('feed_contour', tool['feed'])
    for run in runs:
        nramp = max(2, int(len(run) * 0.08))
        closed = run[0] == run[-1]
        # хвост = добор участка врезания на полной глубине (замкнутый - вперёд, открытый - назад)
        path = run + (run[1:nramp + 1] if closed else list(reversed(run[:nramp])))
        g.go(z=Z_RETRACT, move='G0')
        g.go(x=path[0][0], y=path[0][1], move='G0')
        for i, (x, y) in enumerate(path[1:]):
            if i < nramp:
                g.go(x=x, y=y, z=Z_LINK + (-z - Z_LINK) * (i + 1) / nramp, f=tool['ramp'])
            else:
                g.go(x=x, y=y, f=fc)
        g.go(z=Z_RETRACT, move='G0')


def cut_raster(g, pk, arcs, z, tool, allow, sag, Rt):
    """Полярный растор на глубине -z со связками."""
    r_tool = tool['dia'] / 2.0
    cur = None
    for k, (rho, ivs) in enumerate(arcs):
        fwd = (k % 2 == 0)
        seq = ivs if fwd else list(reversed(ivs))
        for (t0, t1, tag0, tag1) in seq:
            if not fwd:
                t0, t1, tag0, tag1 = t1, t0, tag1, tag0
            if abs(t1 - t0) * rho < 0.8:
                continue
            p0 = (rho * math.cos(t0), rho * math.sin(t0))
            p1 = (rho * math.cos(t1), rho * math.sin(t1))
            pts = arc_points((0.0, 0.0), rho, t0, t1, sag)
            if cur is None:
                g.go(z=Z_RETRACT, move='G0')
                g.go(x=p0[0], y=p0[1], move='G0')
                nramp = 1
                acc = 0.0
                for i in range(1, len(pts)):
                    acc += math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
                    nramp = i
                    if acc >= RAMP_LEN:
                        break
                for i in range(1, len(pts)):
                    zz = -z * min(1.0, i / float(nramp))
                    g.go(x=pts[i][0], y=pts[i][1], z=zz, f=tool['ramp'] if i <= nramp else tool['feed'])
            else:
                link = link_move(pk, cur, p0, tag0, Rt, r_tool, allow)
                if link is None:
                    g.go(z=Z_LINK, move='G0')
                    g.go(x=p0[0], y=p0[1], move='G0')
                    g.go(z=-z, f=tool['plunge'])
                else:
                    for (x, y) in link:
                        g.go(x=x, y=y, f=tool['ramp'])
                    g.go(z=-z, f=tool['plunge'])
                for p in pts[1:]:
                    g.go(x=p[0], y=p[1], f=tool['feed'])
            cur = (p1, tag1)
    if cur is not None:
        g.go(z=Z_RETRACT, move='G0')


def op_flatten():
    tool = TOOL_SURF
    g = GCode()
    header(g, "00 ТОРЦОВКА ВЕРХА - снять излишек заготовки", tool, zero_note() + " (ДО торцовки)")
    g.c("( Снять %.2f мм. ШАГ %.1f мм - проверьте диаметр фрезы.)" % (tool['doc'], tool['stepover']))
    g.c()
    total = max(0.0, BLANK_THICK - THICK)
    nlev = max(1, int(math.ceil(total / tool['doc']))) if total > 1e-9 else 0
    g.c("( Заготовка %.1f -> изделие %.1f : снять %.2f мм за %d проход(ов) )"
        % (BLANK_THICK, THICK, total, nlev))
    if nlev == 0:
        g.c("( Снимать нечего: BLANK_THICK == THICK )")
    half = BLANK_SIZE / 2.0 - tool['dia'] / 2.0
    g.go(z=Z_RETRACT, move='G0')
    for lev in range(1, nlev + 1):
        z = -total * lev / nlev
        g.c("( уровень %d/%d, Z%.2f )" % (lev, nlev, z))
        y = half
        fwd = True
        first = True
        while y >= -half - 1e-9:
            x0 = -half if fwd else half
            x1 = half if fwd else -half
            if first:
                g.go(z=Z_RETRACT, move='G0')
                g.go(x=x0, y=y, move='G0')
                g.go(z=Z_LINK, move='G0')
                g.go(z=z, f=tool['plunge'])
                first = False
            else:
                g.go(y=y, f=tool['feed'])  # перешагивание на рабочей подаче, НЕ G0 в материале
            g.go(x=x1, y=y, f=tool['feed'])
            fwd = not fwd
            y -= tool['stepover']
        g.go(z=Z_RETRACT, move='G0')
    g.c("G0 Z" + fnum(Z_RETRACT + 5.0))
    g.c("M05")
    g.c("M30")
    return g


def op_rough(pockets):
    tool = TOOL_EM
    g = GCode()
    header(g, "01 ROUGH POCKETS - %d compartments" % len(pockets), tool, zero_note())
    g.c("( Припуск: стенки %.3f, дно %.3f)" % (WALL_ALLOW, FLOOR_ALLOW))
    g.c()
    target = POCKET_DEPTH - FLOOR_ALLOW
    nlev = max(1, int(math.ceil(target / tool['doc'])))
    levels = [target * i / nlev for i in range(1, nlev + 1)]
    for pk in pockets:
        arcs, Rt, rmin = pk.raster(tool['dia'] / 2.0, WALL_ALLOW, tool['stepover'])
        g.c("(--- POCKET axis %.1f deg | %d arcs/level | levels: %s ---)"
            % (math.degrees(pk.mid), len(arcs), " ".join("%.3f" % z for z in levels)))
        for z in levels:
            cut_contour(g, pk, z, tool, Rt)
            cut_raster(g, pk, arcs, z, tool, WALL_ALLOW, SAG_ROUGH, Rt)
            g.c()
    g.c("G0 Z" + fnum(Z_RETRACT + 8.0))
    g.c("M05")
    g.c("M30")
    return g


def op_finish(pockets):
    tool = TOOL_BOWL
    r = tool['dia'] / 2.0
    g = GCode()
    header(g, "02 FINISH POCKETS - walls + floor (Whiteside 1372)", tool, zero_note())
    g.c("( Сначала обход стенок/скруглений, затем дно полярным растром.)")
    g.c("( Один проход по Z на полную глубину: фреза формирует R6.35 у дна.)")
    g.c()
    z = POCKET_DEPTH
    for pk in pockets:
        g.c("(--- POCKET axis %.1f : wall contour ---)" % math.degrees(pk.mid))
        cut_contour(g, pk, z, tool, r)
        arcs, Rt, rmin = pk.raster(r, 0.0, tool["stepover"], F_extra=0.0)
        g.c("(--- POCKET floor: %d arcs, stepover %.3f ---)" % (len(arcs), tool['stepover']))
        cut_raster(g, pk, arcs, z, tool, 0.0, SAG_FINISH, Rt)
        g.c()
    g.c("G0 Z" + fnum(Z_RETRACT + 8.0))
    g.c("M05")
    g.c("M30")
    return g


def op_profile(depth, tab_z, title, note):
    """Контур наружу. tab_z = глубина от текущего Z0, на которой рез стоит над табом
    (None -> табов нет)."""
    tool = TOOL_PROFILE
    r = tool['dia'] / 2.0
    g = GCode()
    header(g, title, tool, note)
    g.c("( Глубина по Z от текущего нуля: %.2f мм )" % depth)
    if tab_z is not None:
        g.c("( Табы: %d x %.1f мм, рез над табом стоит на Z-%.2f )" % (TABS, TAB_LEN, tab_z))
    else:
        g.c("( БЕЗ табов: материал под резом ещё не прорезан насквозь )")
    g.c()
    Rc = BOARD_DIA / 2.0 - r
    nlev = max(1, int(math.ceil(depth / tool['doc'])))
    levels = [depth * i / nlev for i in range(1, nlev + 1)]
    use_tabs = tab_z is not None
    tab_top = tab_z if use_tabs else depth
    tab_half = math.degrees(TAB_LEN / Rc / 2.0)
    centers = [360.0 * i / TABS + 180.0 / TABS for i in range(TABS)]
    circle = circle_points((0.0, 0.0), Rc, SAG_FINISH)
    g.c("( Z-уровни: %s )" % " ".join("%.2f" % z for z in levels))
    g.go(x=circle[0][0], y=circle[0][1], move='G0')
    nramp = max(3, int(len(circle) * 0.05))
    for zi, zt in enumerate(levels):
        g.go(z=Z_LINK, f=tool['plunge'])
        for i, (x, y) in enumerate(circle):
            t = math.degrees(math.atan2(y, x)) % 360.0
            zc = -zt
            if use_tabs and zt > tab_top:
                dmin = min(abs(((t - c + 180.0) % 360.0) - 180.0) for c in centers)
                dmin *= math.pi / 180.0 * Rc          # в миллиметры по дуге
                half_in = TAB_LEN / 2.0
                if dmin <= half_in:
                    zc = -tab_top
                elif dmin < half_in + TAB_RAMP:       # плавный съезд, без вертикального ныряния
                    zc = -(tab_top + (zt - tab_top) * (dmin - half_in) / TAB_RAMP)
            if i < nramp:
                g.go(x=x, y=y, z=Z_LINK + (zc - Z_LINK) * (i + 1) / nramp, f=tool['ramp'])
            else:
                g.go(x=x, y=y, z=zc, f=tool['feed'])
        g.go(x=circle[0][0], y=circle[0][1], f=tool['feed'])
        g.c()
    g.c("G0 Z" + fnum(Z_RETRACT + 8.0))
    g.c("M05")
    g.c("M30")
    return g


def op_juice_groove():
    tool = dict(TOOL_BOWL)
    tool.update(name='Whiteside 1406 Round Nose, D19.05 / R9.53 / реж.часть 11.1 мм', rpm=16000,
                feed=1780.0, plunge=380.0, ramp=1000.0)
    g = GCode()
    header(g, "05 JUICE GROOVE (OPTION) - round nose 1406B", tool, zero_note())
    depth = 4.8
    g.c("( Жёлоб по центру бортика: R=%.1f, глубина %.1f мм )" % (BOARD_DIA / 2 - RIM_W / 2, depth))
    g.c()
    Rg = BOARD_DIA / 2.0 - RIM_W / 2.0
    circle = circle_points((0.0, 0.0), Rg, SAG_FINISH)
    g.go(x=circle[0][0], y=circle[0][1], move='G0')
    for zi in range(1, 4):
        zt = -depth * zi / 3.0
        if zi == 1:
            g.go(z=zt, f=tool['ramp'])
            for (x, y) in circle[1:]:
                g.go(x=x, y=y, f=tool['feed'])
        else:
            for (x, y) in circle:
                g.go(x=x, y=y, z=zt, f=tool['feed'])
        g.c()
    g.c("G0 Z" + fnum(Z_RETRACT + 8.0))
    g.c("M05")
    g.c("M30")
    return g


def png_write(fname, w, h, buf):
    import zlib
    import struct
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += buf[y * w * 3:(y + 1) * w * 3]

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 6))
    png += chunk(b"IEND", b"")
    with open(fname, "wb") as f:
        f.write(png)


def png_preview(pockets, paths, fname):
    scale = 1.8
    W = H = int(BOARD_DIA * scale + 60)
    cx = cy = W / 2.0
    buf = bytearray(b"\xf7\xf2\xe8" * (W * H))

    def put(x, y, col, rad=1):
        for dx in range(-rad, rad + 1):
            for dy in range(-rad, rad + 1):
                xx, yy = int(x) + dx, int(y) + dy
                if 0 <= xx < W and 0 <= yy < H:
                    i = (yy * W + xx) * 3
                    buf[i], buf[i + 1], buf[i + 2] = col

    def T(p):
        return (cx + p[0] * scale, cy - p[1] * scale)

    def line(a, b, col, rad=1):
        ax, ay = T(a)
        bx, by = T(b)
        n = max(2, int(math.hypot(bx - ax, by - ay) / (scale * 0.8)))
        for i in range(n + 1):
            t = i / n
            put(ax + (bx - ax) * t, ay + (by - ay) * t, col, rad)

    rpx = BOARD_DIA / 2 * scale
    for yy in range(H):
        for xx in range(W):
            if math.hypot(xx - cx, yy - cy) <= rpx:
                q = ((xx - cx) / scale, (cy - yy) / scale)
                col = (0xA9, 0x7E, 0x4C) if any(point_inside(q, pk.poly) for pk in pockets) \
                    else (0xC9, 0xA2, 0x71)
                i = (yy * W + xx) * 3
                buf[i], buf[i + 1], buf[i + 2] = col
    for pk in pockets:
        for i in range(len(pk.poly)):
            line(pk.poly[i - 1], pk.poly[i], (0x6F, 0x51, 0x27), 0)
    cols = {'rough': (0xFF, 0x3B, 0x30), 'finish': (0x0A, 0x84, 0xFF), 'profile': (0x22, 0xA0, 0x4A)}
    for kind, pts in paths:
        if len(pts) < 2:
            continue
        ss = pts[::max(1, len(pts) // 4000)]
        for i in range(1, len(ss)):
            line(ss[i - 1], ss[i], cols[kind], 0)
    png_write(fname, W, H, buf)


def svg_preview(pockets, paths, fname):
    scale = 1.7
    W = H = BLANK_SIZE * scale + 120
    cx = cy = W / 2.0 + 10

    def T(p):
        return (cx + p[0] * scale, cy - p[1] * scale)

    o = ['<svg xmlns="http://www.w3.org/2000/svg" width="%.0f" height="%.0f" viewBox="0 0 %.0f %.0f">'
         % (W, H, W, H),
         '<rect width="100%" height="100%" fill="#f7f2e8"/>',
         '<circle cx="%.1f" cy="%.1f" r="%.1f" fill="#c9a271" stroke="#8a6a42" stroke-width="1.5"/>'
         % (cx, cy, BOARD_DIA / 2 * scale)]
    b = BLANK_SIZE / 2.0
    o.insert(2, '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="none" stroke="#999" '
                'stroke-dasharray="6,4"/>' % (cx - b * scale, cy - b * scale, 2 * b * scale, 2 * b * scale))
    if ORIGIN == 'corner':
        o.append('<circle cx="%.1f" cy="%.1f" r="5" fill="#d00"/>' % (cx - b * scale, cy + b * scale))
        o.append('<text x="%.1f" y="%.1f" font-family="monospace" font-size="12" fill="#d00">'
                 'X0Y0</text>' % (cx - b * scale + 8, cy + b * scale - 8))
    for pk in pockets:
        d = "M " + " L ".join("%.2f,%.2f" % T(p) for p in pk.poly) + " Z"
        o.append('<path d="%s" fill="#a97e4c" stroke="#6f5127" stroke-width="1"/>' % d)
    col = {'rough': '#ff3b30', 'finish': '#0a84ff', 'profile': '#22a04a'}
    for kind, pts in paths:
        if len(pts) < 2:
            continue
        step = max(1, len(pts) // 3000)
        d = "M " + " L ".join("%.2f,%.2f" % T(p) for p in pts[::step])
        o.append('<path d="%s" fill="none" stroke="%s" stroke-width="0.5" opacity="0.8"/>' % (d, col[kind]))
    o += ['<text x="14" y="22" font-family="monospace" font-size="13" fill="#222">'
          'v%s   D=%.1f  H=%.1f  карман=%.1f мм</text>'
          % (VERSION, BOARD_DIA, THICK, POCKET_DEPTH),
          '<text x="14" y="40" font-family="monospace" font-size="11" fill="#ff3b30">01 черновая - Molly Mill D6.35</text>',
          '<text x="14" y="55" font-family="monospace" font-size="11" fill="#0a84ff">02 чистовая - Whiteside 1372 D19.05</text>',
          '<text x="14" y="70" font-family="monospace" font-size="11" fill="#22a04a">03 profile</text>',
          '</svg>']
    with open(fname, 'w') as f:
        f.write("\n".join(o))


def set_params(d):
    """Применить параметры из словаря {key: value} к глобальным константам."""
    g = globals()
    for k, v in d.items():
        kk = k.upper()
        if kk in ('BOARD_DIA', 'THICK', 'POCKET_DEPTH', 'RIM_W', 'SPIRAL_SWEEP',
                  'HUB_R', 'WALL_W', 'CORNER_F', 'BLANK_SIZE', 'BLANK_THICK', 'N_POCKETS'):
            g[kk] = float(v) if kk != 'N_POCKETS' else int(v)
        elif kk == 'LAYOUT':
            g[kk] = v
        elif kk == 'WOOD':
            g[kk] = v


def shape_svg(d=None):
    """Быстрая отрисовка формы доски в заготовке (без траекторий) -> SVG-строка."""
    if d:
        set_params(d)
    pockets = build_pockets()
    B = BLANK_SIZE
    size = 680.0
    scale = size / (B * 1.06)
    c = size / 2.0

    def T(p):
        return (c + p[0] * scale, c - p[1] * scale)

    half = B / 2.0 * scale
    o = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">'
         % (size, size, size, size),
         '<rect width="100%" height="100%" fill="#ece7dd"/>',
         '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#e2d6c0" stroke="#999" '
         'stroke-dasharray="7,5"/>' % (c - half, c - half, 2 * half, 2 * half),
         '<circle cx="%.1f" cy="%.1f" r="%.1f" fill="#c9a271" stroke="#8a6a42" stroke-width="1.5"/>'
         % (c, c, BOARD_DIA / 2.0 * scale)]
    for pk in pockets:
        o.append('<path d="M %s Z" fill="#a97e4c" stroke="#6f5127" stroke-width="0.8"/>'
                 % (" L ".join("%.2f,%.2f" % T(p) for p in pk.poly)))
    if ORIGIN == 'corner':
        o.append('<circle cx="%.1f" cy="%.1f" r="6" fill="#d00"/>' % (c - half, c + half))
        o.append('<text x="%.1f" y="%.1f" font-family="monospace" font-size="13" fill="#d00">X0 Y0</text>'
                 % (c - half + 10, c + half - 10))
    o.append('<text x="12" y="22" font-family="monospace" font-size="13" fill="#333">'
             'v%s  заготовка %.0fx%.0fx%.0f  доска D%.0f H%.0f  отсек %.1f мм</text>'
             % (VERSION, B, B, BLANK_THICK, BOARD_DIA, THICK, POCKET_DEPTH))
    o.append('</svg>')
    return "\n".join(o)


def check_nc(path):
    """Проверка готового файла: рапиды в материале, выход за заготовку, глубина."""
    ox, oy = off()
    lo = -0.02 if ORIGIN == 'corner' else -BLANK_SIZE / 2.0 - 0.02
    hi = BLANK_SIZE + 0.02 if ORIGIN == 'corner' else BLANK_SIZE / 2.0 + 0.02
    zmin = -(THICK + PROFILE_EXTRA + 0.5)
    x = y = 0.0
    z = Z_RETRACT
    mode = None
    feed_seen = False
    probs = []
    for ln, line in enumerate(open(path), 1):
        line = line.split('(')[0].strip()
        if not line:
            continue
        m = re.match(r'G0*([013])\b', line)
        if m:
            mode = int(m.group(1))
        nx, ny, nz = x, y, z
        for ax, val in re.findall(r'([XYZF])(-?\d*\.?\d+)', line):
            v = float(val)
            if ax == 'X':
                nx = v
            elif ax == 'Y':
                ny = v
            elif ax == 'Z':
                nz = v
            elif ax == 'F':
                feed_seen = v > 0
        moved_xy = abs(nx - x) > 1e-6 or abs(ny - y) > 1e-6
        if mode == 0 and moved_xy and min(z, nz) < -0.02:
            probs.append("стр.%d: G0 в материале (Z%.2f)" % (ln, min(z, nz)))
        if mode == 1 and not feed_seen:
            probs.append("стр.%d: G1 без подачи" % ln)
        if not (lo <= nx <= hi and lo <= ny <= hi):
            probs.append("стр.%d: X%.2f Y%.2f вне заготовки" % (ln, nx, ny))
        if nz < zmin:
            probs.append("стр.%d: Z%.2f глубже %.2f" % (ln, nz, zmin))
        if nz > Z_RETRACT + 15.0:
            probs.append("стр.%d: Z%.2f подозрительно высоко" % (ln, nz))
        x, y, z = nx, ny, nz
    return probs


def selftest():
    """Проверка самого линтера: он обязан поймать рапид в материале и выход за край."""
    import tempfile
    p = os.path.join(tempfile.gettempdir(), "_lint_selftest.nc")
    with open(p, "w") as f:
        f.write("G21 G90\nG0 X10 Y10\nG1 Z-5 F250\nG0 X50 Y50\nG0 Z9\nG0 X99999 Y10\n")
    probs = check_nc(p)
    os.remove(p)
    assert any("G0 в материале" in t for t in probs), probs
    assert any("вне заготовки" in t for t in probs), probs

    # карман, накрывающий центр, должен фрезероваться до середины:
    # 360-градусная дуга режется пополам (arc_points её не выражает),
    # а фильтр длины в cut_raster не должен выбрасывать кольца обратного хода.
    pk = Pocket.from_poly(circle_points((0, 0), 18.0, SAG_FINISH))
    arcs, Rt, _ = pk.raster(3.175, WALL_ALLOW, 3.2)
    gg = GCode()
    cut_raster(gg, pk, arcs, 5.0, TOOL_EM, WALL_ALLOW, SAG_ROUGH, Rt)
    assert min(math.hypot(*p) for sg in gg.segs for p in sg) < 4.0, "дыра в центре кармана"
    assert len({round(r, 2) for r, _ in arcs} -
               {round(math.hypot(*p), 2) for sg in gg.segs for p in sg}) == 0, "выброшены кольца"

    # контур кармана не должен иметь игл: скругления обязаны стыковаться
    # со стенкой и с дугами втулки/бортика по касательной
    assert min_corner_angle(build_pockets()[0].poly) > 60.0, "игла на контуре кармана"

    # прямые сектора: стенка одной толщины у втулки и у бортика
    _sw = globals()['SPIRAL_SWEEP']
    globals()['SPIRAL_SWEEP'] = 0.0
    try:
        assert abs(wall_thickness() - WALL_W) < 0.05, wall_thickness()
    finally:
        globals()['SPIRAL_SWEEP'] = _sw


def main():
    selftest()
    del WARN[:]                               # иначе копятся между вызовами из serve.py
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "nc")
    os.makedirs(out, exist_ok=True)
    for f in os.listdir(out):                 # чистый каталог от старых версий
        if f.endswith('.nc'):
            os.remove(os.path.join(out, f))
    _w = WOODS.get(WOOD, WOODS['maple'])
    for _t in BITS:
        _t.setdefault('_base', {k: _t[k] for k in ('feed', 'plunge', 'ramp', 'feed_contour') if k in _t})
        for _k, _v in _t['_base'].items():      # от базы, иначе при повторном вызове (serve.py) копится
            _t[_k] = _v * _w['scale']
        _t['rpm'] = min(_w['rpm'], _t.get('rpm_max', 24000))
        _t['dial'] = dial_for(_t['rpm'])

    # Для совместимости со старыми вызовами (op_rough и т.д.)
    global TOOL_EM, TOOL_PROFILE, TOOL_BOWL, TOOL_SURF
    TOOL_EM = get_tool('rough')
    TOOL_BOWL = get_tool('finish')
    TOOL_PROFILE = get_tool('profile')
    TOOL_SURF = get_tool('surf')

    pockets = build_pockets()

    g_rough = op_rough(pockets)
    g_fin = op_finish(pockets)
    ops = []
    if FLATTEN:
        ops.append(("00_flatten_top_OPTIONAL.nc", op_flatten(), TOOL_SURF))
    ops.append(("01_rough_pockets_MollyMill.nc", g_rough, TOOL_EM))
    ops.append(("02_finish_pockets_1372_bowl.nc", g_fin, TOOL_BOWL))
    loc = TOOL_PROFILE.get('loc', 19.0)
    # после торцовки высота = THICK; если торцовки нет, режем всю заготовку насквозь
    need = (THICK if FLATTEN else max(THICK, BLANK_THICK)) + PROFILE_EXTRA
    mode = PROFILE_MODE
    if mode == 'auto':
        mode = 'full' if need <= loc - 1.2 else 'flip'
    if mode == 'full':
        ops.append(("03_profile_full.nc",
                    op_profile(need, THICK - TAB_H,
                               "03 PROFILE - контур насквозь за одну установку + табы",
                               zero_note()), TOOL_PROFILE))
    else:
        d_top = min(loc - 1.2, need - 4.0)
        d_bot = need - d_top + 2.5                      # перекрытие 0.10 по стыку
        WARN.append("режущая часть контурной фрезы %.1f мм < реза %.1f мм -> контур в ДВЕ "
                    "установки (03a сверху, переворот, 03b снизу)" % (loc, need))
        if d_bot > loc - 1.2:
            WARN.append("!! даже с переворотом не хватает: снизу надо резать %.1f мм при "
                        "режущей части %.1f мм. Уменьшите THICK или возьмите фрезу длиннее"
                        % (d_bot, loc))
        ops.append(("03a_profile_top.nc",
                    op_profile(d_top, None,
                               "03a PROFILE - ВЕРХНЯЯ сторона, рез %.1f мм (насквозь НЕ идёт)" % d_top,
                               zero_note()), TOOL_PROFILE))
        ops.append(("03b_profile_bottom_FLIP.nc",
                    op_profile(d_bot, THICK - d_top - TAB_H,
                               "03b PROFILE - ПОСЛЕ ПЕРЕВОРОТА, рез %.1f мм + табы" % d_bot,
                               zero_note() + " (НОВЫЙ верх после переворота!)"), TOOL_PROFILE))
    if JUICE_GROOVE and RIM_W >= 32.0:
        ops.append(("05_juice_groove_OPTIONAL.nc", op_juice_groove(), TOOL_BOWL))

    rep = []
    ok = True
    rep.append("ПАРАМЕТРЫ ИЗДЕЛИЯ (generate_board.py v%s, всё в миллиметрах)" % VERSION)
    rep.append("  диаметр .................... %.1f мм (%.1f см)" % (BOARD_DIA, BOARD_DIA / 10.0))
    rep.append("  заготовка .................. %.1f x %.1f x %.1f мм, ноль: %s"
               % (BLANK_SIZE, BLANK_SIZE, BLANK_THICK,
                  "ЛЕВЫЙ БЛИЖНИЙ УГОЛ" if ORIGIN == 'corner' else "центр"))
    rep.append("  центр доски в коорд. станка  X%.1f Y%.1f" % off())
    rep.append("  толщина (высота) ........... %.1f мм (%.1f см)" % (THICK, THICK / 10.0))
    rep.append("  глубина кармана ............ %.1f мм" % POCKET_DEPTH)
    rep.append("  порода / подачи ............ %s (множитель %.2f)"
               % (WOODS.get(WOOD, WOODS['maple'])['note'], WOODS.get(WOOD, WOODS['maple'])['scale']))
    rep.append("  бортик ..................... %.1f мм" % RIM_W)
    rep.append("  закрутка стенки ............ %.1f град (вертушка)" % SPIRAL_SWEEP)
    rep.append("  втулка / толщина стенки .... R%.1f / %.1f мм" % (HUB_R, WALL_W))
    rep.append("  R поля карманов ............ %.1f мм" % (BOARD_DIA / 2 - RIM_W))
    rep.append("  скругление (план) .......... %.1f мм" % CORNER_F)
    rep.append("  площадь карманов ........... %.0f см2" % (sum(p.area for p in pockets) / 100.0))
    rep.append("")
    rep.append("ПРОВЕРКИ ГЕОМЕТРИИ")
    rep.append("  реальная толщина стенки .... %.1f мм (WALL_W %.1f - это смещение по дуге,"
               " у спирали оно даёт меньше дерева)" % (wall_thickness(), WALL_W))
    if CORNER_F <= TOOL_BOWL['dia'] / 2.0:
        rep.append("  !! скругление в плане должно быть > радиуса фрезы 1372 (9.53 мм)"); ok = False
    for _t in (TOOL_EM, TOOL_PROFILE, TOOL_BOWL):
        if _t['rpm'] > _t.get('rpm_max', 24000):
            rep.append("  !! %s: %d об/мин > паспортных %d" % (_t['name'], _t['rpm'], _t['rpm_max']))
            ok = False
    if POCKET_DEPTH > TOOL_BOWL['loc']:
        rep.append("  !! глубина кармана %.1f > режущей части 1372 (%.1f мм)"
                   % (POCKET_DEPTH, TOOL_BOWL['loc'])); ok = False
    if BOARD_DIA + 12.0 > BLANK_SIZE:
        rep.append("  !! доска %.1f не влезает в заготовку %.1f (нужен запас >= 6 мм на сторону)"
                   % (BOARD_DIA, BLANK_SIZE)); ok = False
    if BLANK_SIZE > 800.0:
        rep.append("  !! квадрат заготовки не влезает в поле станка 812x812 мм"); ok = False
    if BLANK_THICK < THICK - 1e-9:
        rep.append("  !! заготовка %.1f тоньше изделия %.1f мм" % (BLANK_THICK, THICK)); ok = False
    elif BLANK_THICK > THICK + 1e-9:
        d = BLANK_THICK - THICK
        if FLATTEN:
            rep.append("  торцовка снимет %.2f мм; Z0 для файлов 01..03 ставить ПО НОВОЙ "
                       "плоскости после файла 00" % d)
        else:
            WARN.append("заготовка толще изделия на %.2f мм, а торцовка выключена: "
                        "строгайте рейсмусом до %.1f мм либо FLATTEN=True (нужна торцовочная фреза). "
                        "Контур сейчас режется на всю толщину заготовки" % (d, THICK))
    for w in WARN:
        rep.append("  ** " + w)
    if JUICE_GROOVE and RIM_W < 32.0:
        rep.append("  !! жёлоб запрошен, но бортик %.1f < 32 мм - операция не создана" % RIM_W)
    for pk in pockets:
        rep.append("  отсек ось %6.1f : площадь %5.0f см2, R min по контуру %.1f мм"
                   % (math.degrees(pk.mid), pk.area / 100.0, pk.r_min))

    rep.append("")
    rep.append("КОНТРОЛЬ ЗАЗОРОВ")
    r = TOOL_EM['dia'] / 2.0
    for pk in pockets:
        arcs, Rt, rmin = pk.raster(r, WALL_ALLOW, TOOL_EM['stepover'])
        worst = min(dist_to_poly(pt(rho, t), pk.poly)
                    for (rho, ivs) in arcs for (t0, t1, _a, _b) in ivs
                    for t in (t0, 0.5 * (t0 + t1), t1))
        rep.append("  черновой %6.1f: мин. центр-контур = %.3f (нужно >= %.3f мм) %s"
                   % (math.degrees(pk.mid), worst, r + WALL_ALLOW - 0.05,
                      "OK" if worst >= r + WALL_ALLOW - 0.05 else "!!! НАРУШЕНИЕ"))
        if worst < r + WALL_ALLOW - 0.05:
            ok = False
    r = TOOL_BOWL['dia'] / 2.0
    for pk in pockets:
        runs, nbad = contour_runs(pk, r)
        allp = [p for rn in runs for p in rn]
        worst = min(dist_to_poly(p, pk.poly) for p in allp) if allp else 0.0
        rep.append("  чистовой обход %6.1f: %d проход(ов), мин. центр-стенка %.3f (нужно >= %.3f мм) %s"
                   % (math.degrees(pk.mid), len(runs), worst, r - 0.25,
                      "OK" if worst >= r - 0.25 else "!!! ВРЕЗАНИЕ В СТЕНКУ"))
        rep.append("     фрезе 19 мм недоступно %d точек обхода из %d (узко у втулки) - "
                   "там остаётся черновой припуск %.1f мм, снять вручную"
                   % (nbad, nbad + len(allp), WALL_ALLOW))
        if worst < r - 0.25:
            ok = False

    rep.append("")
    rep.append("КОНТРОЛЬ ПОКРЫТИЯ (сетка %.1f мм; \"недоступных\" узлов - острые рожки карманов,"
               " туда фреза не входит по геометрии, там дерево остаётся)" % COVERAGE_STEP)
    tot_m = 0
    for pk in pockets:
        t, m, hd, w = coverage_check(pk, g_rough.segs, TOOL_EM['dia'] / 2.0,
                                     WALL_ALLOW + 0.010, COVERAGE_STEP)
        rep.append("  черновой %6.1f: узлов %5d, не снято %d (из них доступных фрезе %d, "
                   "остаток %.2f мм) %s"
                   % (math.degrees(pk.mid), t, m, hd, w,
                      "OK" if hd == 0 else ("норма: %.2f мм доберёт чистовая" % w
                                            if w <= 2.0 * WALL_ALLOW else "!!! ДЫРА В ТРАЕКТОРИИ")))
        tot_m += hd if w > 2.0 * WALL_ALLOW else 0   # чистовая снимает WALL_ALLOW, двойной - предел
    for pk in pockets:
        t, m, hd, w = coverage_check(pk, g_fin.segs, TOOL_BOWL['dia'] / 2.0, 0.0, COVERAGE_STEP)
        rep.append("  чистовой %6.1f: узлов %5d, не снято %d (из них доступных фрезе %d, "
                   "остаток %.2f мм) %s"
                   % (math.degrees(pk.mid), t, m, hd, w,
                      "OK" if hd == 0 else "!!! ДЫРА В ТРАЕКТОРИИ"))
        tot_m += hd
    if tot_m:
        ok = False

    rep.append("")
    rep.append("ФАЙЛЫ И ОЦЕНКА ВРЕМЕНИ (подача + 35% на разгоны/переезды)")
    total = 0.0
    for fn, g, tool in ops:
        with open(os.path.join(out, fn), 'w') as f:
            f.write(g.text())
        mins = g.cut_len / max(tool['feed'], 1.0) * 1.35
        total += mins
        rep.append("  %-32s %6d строк %6.1f КБ  путь %6.1f м  ~%4.0f мин"
                   % (fn, g.text().count("\n"), len(g.text()) / 1024.0, g.cut_len / 1000.0, mins))
    rep.append("  ИТОГО ~%.0f мин машинного времени (+ смена фрез, настройка, шлифовка)" % total)
    rep.append("")
    rep.append("")
    rep.append("ЛИНТЕР G-КОДА (читает записанные .nc)")
    lint_bad = 0
    for fn, _g, _t in ops:
        probs = check_nc(os.path.join(out, fn))
        lint_bad += len(probs)
        rep.append("  %-32s %s" % (fn, "OK" if not probs else "!! " + "; ".join(probs[:3])))
    if lint_bad:
        ok = False
    rep.append("")
    rep.append("ИТОГ: %s" % ("ГЕОМЕТРИЯ И ТРАЕКТОРИИ В ПОРЯДКЕ" if ok else "ЕСТЬ ЗАМЕЧАНИЯ - СМ. ВЫШЕ"))

    txt = "\n".join(rep)
    with open(os.path.join(here, "report.txt"), 'w') as f:
        f.write(txt + "\n")
    print(txt)

    # превью
    paths = []                      # каждая дуга/проход - отдельной линией, без ложных хорд
    for pk in pockets:
        for (rho, ivs) in pk.raster(TOOL_EM['dia'] / 2, WALL_ALLOW, TOOL_EM['stepover'])[0]:
            for (t0, t1, _a, _b) in ivs:
                paths.append(('rough', arc_points((0, 0), rho, t0, t1, 0.05)))
        for (rho, ivs) in pk.raster(TOOL_BOWL['dia'] / 2, 0.0, TOOL_BOWL['stepover'])[0]:
            for (t0, t1, _a, _b) in ivs:
                paths.append(('finish', arc_points((0, 0), rho, t0, t1, 0.05)))
        for run in contour_runs(pk, TOOL_BOWL['dia'] / 2.0)[0]:
            paths.append(('finish', run))
    paths.append(('profile', circle_points((0, 0), BOARD_DIA / 2 - TOOL_PROFILE['dia'] / 2, 0.05)
                  + [circle_points((0, 0), BOARD_DIA / 2 - TOOL_PROFILE['dia'] / 2, 0.05)[0]]))
    svg_preview(pockets, paths, os.path.join(here, "preview.svg"))
    png_preview(pockets, paths, os.path.join(here, "preview.png"))
    print("\npreview.svg / preview.png записаны")


def paths_svg(tags=None, d=None):
    """Траектории фрез поверх формы -> SVG-строка (для эндпоинта /paths.svg).

    Новая функция, существующие не трогает. tags - множество тегов
    ('rough','finish','profile') или None = все. Параметры формы - через d
    (как в set_params). Считается 4-5 секунд: здесь гоняется тот же растр,
    что и в main().
    """
    if d:
        set_params(d)
    pockets = build_pockets()
    paths = []                      # каждая дуга/проход - отдельной линией
    for pk in pockets:
        for (rho, ivs) in pk.raster(TOOL_EM['dia'] / 2, WALL_ALLOW, TOOL_EM['stepover'])[0]:
            for (t0, t1, _a, _b) in ivs:
                paths.append(('rough', arc_points((0, 0), rho, t0, t1, 0.05)))
        for (rho, ivs) in pk.raster(TOOL_BOWL['dia'] / 2, 0.0, TOOL_BOWL['stepover'])[0]:
            for (t0, t1, _a, _b) in ivs:
                paths.append(('finish', arc_points((0, 0), rho, t0, t1, 0.05)))
        for run in contour_runs(pk, TOOL_BOWL['dia'] / 2.0)[0]:
            paths.append(('finish', run))
    paths.append(('profile', circle_points((0, 0), BOARD_DIA / 2 - TOOL_PROFILE['dia'] / 2, 0.05)
                  + [circle_points((0, 0), BOARD_DIA / 2 - TOOL_PROFILE['dia'] / 2, 0.05)[0]]))
    if tags is not None:
        paths = [(k, p) for (k, p) in paths if k in tags]

    scale = 1.7
    W = H = BLANK_SIZE * scale + 120
    cx = cy = W / 2.0 + 10

    def T(p):
        return (cx + p[0] * scale, cy - p[1] * scale)

    o = ['<svg xmlns="http://www.w3.org/2000/svg" width="%.0f" height="%.0f" viewBox="0 0 %.0f %.0f">'
         % (W, H, W, H),
         '<rect width="100%" height="100%" fill="#f7f2e8"/>']
    b = BLANK_SIZE / 2.0
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="none" stroke="#999" '
             'stroke-dasharray="6,4"/>' % (cx - b * scale, cy - b * scale, 2 * b * scale, 2 * b * scale))
    o.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="#c9a271" stroke="#8a6a42" stroke-width="1.5"/>'
             % (cx, cy, BOARD_DIA / 2 * scale))
    if ORIGIN == 'corner':
        o.append('<circle cx="%.1f" cy="%.1f" r="5" fill="#d00"/>' % (cx - b * scale, cy + b * scale))
        o.append('<text x="%.1f" y="%.1f" font-family="monospace" font-size="12" fill="#d00">X0Y0</text>'
                 % (cx - b * scale + 8, cy + b * scale - 8))
    for pk in pockets:
        o.append('<path d="M %s Z" fill="#a97e4c" stroke="#6f5127" stroke-width="1"/>'
                 % (" L ".join("%.2f,%.2f" % T(p) for p in pk.poly)))
    col = {'rough': '#ff3b30', 'finish': '#0a84ff', 'profile': '#22a04a'}
    for kind, pts in paths:
        if len(pts) < 2:
            continue
        step = max(1, len(pts) // 3000)
        o.append('<path d="M %s" fill="none" stroke="%s" stroke-width="0.5" opacity="0.8"/>'
                 % (" L ".join("%.2f,%.2f" % T(p) for p in pts[::step]), col[kind]))
    o.append('</svg>')
    return "\n".join(o)


if __name__ == "__main__":
    main()
