# -*- coding: utf-8 -*-
"""Линтер готового .nc: рапиды в материале, выход за заготовку, глубина, подача.

Перенос check_nc из board_v3 (границы - из заготовки дизайна). Пороги не менять:
это сигнализация, а не настройка.
"""

import os
import re
import tempfile


def check_nc(path, blank, thick, profile_extra, z_retract):
    """Список проблем (пустой = OK)."""
    if blank.origin == 'corner':
        lox, hix = -0.02, blank.size_x + 0.02
        loy, hiy = -0.02, blank.size_y + 0.02
    else:
        lox, hix = -blank.size_x / 2.0 - 0.02, blank.size_x / 2.0 + 0.02
        loy, hiy = -blank.size_y / 2.0 - 0.02, blank.size_y / 2.0 + 0.02
    zmin = -(thick + profile_extra + 0.5)
    x = y = 0.0
    z = z_retract
    mode = None
    feed_seen = False
    probs = []
    with open(path, encoding='utf-8') as fh:
        for ln, line in enumerate(fh, 1):
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
            if not (lox <= nx <= hix and loy <= ny <= hiy):
                probs.append("стр.%d: X%.2f Y%.2f вне заготовки" % (ln, nx, ny))
            if nz < zmin:
                probs.append("стр.%d: Z%.2f глубже %.2f" % (ln, nz, zmin))
            if nz > z_retract + 15.0:
                probs.append("стр.%d: Z%.2f подозрительно высоко" % (ln, nz))
            x, y, z = nx, ny, nz
    return probs


def selftest(blank, thick, profile_extra, z_retract):
    """Линтер обязан поймать рапид в материале и выход за край на заведомо плохом файле."""
    p = os.path.join(tempfile.gettempdir(), "_boardcam_lint_selftest.nc")
    with open(p, "w") as f:
        f.write("G21 G90\nG0 X10 Y10\nG1 Z-5 F250\nG0 X50 Y50\nG0 Z9\nG0 X99999 Y10\n")
    probs = check_nc(p, blank, thick, profile_extra, z_retract)
    os.remove(p)
    assert any("G0 в материале" in t for t in probs), probs
    assert any("вне заготовки" in t for t in probs), probs
