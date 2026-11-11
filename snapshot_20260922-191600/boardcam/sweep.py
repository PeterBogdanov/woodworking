# -*- coding: utf-8 -*-
"""Прогон по диапазонам Customizer: фигура не должна падать ни на одной комбинации.

Диапазоны читаются из аннотаций .scad (// [min:step:max], // [a, b], // [a:Label, ...]).
Варианты: значения по умолчанию, каждый параметр по одному на краях диапазона,
плюс случайные комбинации (seed фиксирован). Для каждого - построение дизайна
(без STL) и план. Исключение = провал; отказ плана или ошибка фигуры = норма,
считается и печатается.
"""

import os
import random
import re
import time

_PARAM = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*([^;]+);\s*//\s*\[([^\]]*)\]")


def customizer_params(script):
    """-> [(имя, значение по умолчанию (строка), список вариантов (строки))]. Только до первого module/function."""
    out = []
    hidden = False
    with open(script, encoding="utf-8") as f:
        for line in f:
            if re.match(r"^\s*(module|function)\b", line):
                break
            m = re.match(r"^\s*/\*\s*\[(.*?)\]\s*\*/", line)
            if m:
                hidden = m.group(1).strip().lower() == "hidden"
                continue
            if hidden:
                continue
            m = _PARAM.match(line)
            if not m:
                continue
            name, default, spec = m.group(1), m.group(2).strip().strip('"'), m.group(3)
            if ":" in spec and "," not in spec:
                parts = [p.strip() for p in spec.split(":")]
                if len(parts) == 3:
                    lo, step, hi = (float(x) for x in parts)
                elif len(parts) == 2:
                    lo, hi = (float(x) for x in parts)
                    step = 1.0
                else:
                    continue
                n = int(round((hi - lo) / step))
                vals = [lo + step * k for k in range(n + 1)]
                out.append((name, default, [_fmt(v) for v in vals]))
            else:
                vals = []
                for item in spec.split(","):
                    item = item.strip()
                    if not item:
                        continue
                    vals.append(item.split(":")[0].strip())
                out.append((name, default, vals))
    return out


def _fmt(v):
    return ("%.6g" % v)


def sweep(root, shape, lib, samples=40, material=None, budget=2.0, seed=1):
    from .jobs.run import build_design
    from .selection import rules
    from .scad import runner
    script = os.path.join(root, "shapes", shape + ".scad")
    params = customizer_params(script)
    if not params:
        print("в %s нет параметров Customizer" % script)
        return 1
    osc = runner.OpenScad()
    base = {n: d for n, d, v in params}
    cases = [("default", dict(base))]
    for n, d, vals in params:
        for v in (vals[0], vals[-1]):
            if v != d:
                c = dict(base)
                c[n] = v
                cases.append(("%s=%s" % (n, v), c))
    rnd = random.Random(seed)
    for k in range(samples):
        c = {n: rnd.choice(vals) for n, d, vals in params}
        cases.append(("random%d" % k, c))
    print("фигура %s: %d параметров, %d вариантов" % (shape, len(params), len(cases)))
    fails = refusals = errors = slow = 0
    worst = 0.0
    t_all = time.time()
    for label, c in cases:
        t0 = time.time()
        try:
            design, res = build_design(root, shape, None, c, openscad=osc, want_stl=False)
            plan = rules.plan(design, lib, material)
            dt = time.time() - t0
            worst = max(worst, dt)
            if design.errors():
                errors += 1
                status = "фигура: " + "; ".join(m.code for m in design.errors())
            elif not plan.ok:
                refusals += 1
                status = "отказ: " + "; ".join(m.code for m in plan.refusals)
            else:
                status = "ок (%s)" % ", ".join(o.filename for o in plan.ops)
            if dt > budget:
                slow += 1
                status += "  МЕДЛЕННО %.1f с" % dt
        except Exception as e:      # noqa: BLE001 - именно исключения и ищем
            fails += 1
            dt = time.time() - t0
            status = "ИСКЛЮЧЕНИЕ %s: %s" % (type(e).__name__, e)
        print("  %-40s %5.2f с  %s" % (label, dt, status))
    print("итого: %d вариантов за %.0f с; исключений %d, отказов плана %d, ошибок фигуры %d, дольше %.1f с: %d, худшее %.1f с"
          % (len(cases), time.time() - t_all, fails, refusals, errors, budget, slow, worst))
    return 1 if fails else 0
