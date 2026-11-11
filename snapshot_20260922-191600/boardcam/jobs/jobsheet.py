# -*- coding: utf-8 -*-
"""Карта работы (job_sheet.md): что положить на станок, в каком порядке, чем и с каким нулём."""

from .. import VERSION


def job_sheet(design, plan, files, verdict, ctx):
    L = []
    L.append("# Карта работы: %s" % (ctx.get("job") or "%s / %s" % (design.shape, design.source.get("preset"))))
    L.append("")
    L.append("boardcam v%s · OpenSCAD %s · прогон %s · **%s**" % (VERSION, ctx.get("openscad_version", "?"), ctx.get("stamp"), verdict))
    L.append("")
    b = design.blank
    L.append("## Заготовка и ноль")
    L.append("")
    L.append("- Заготовка **%.0f × %.0f × %.1f мм**, деталь центрирована в ней." % (b.size_x, b.size_y, b.thick))
    L.append("- %s." % ctx["zero"])
    L.append("- Центр детали в координатах станка: X%.1f Y%.1f." % (b.size_x / 2.0 if b.origin == "corner" else 0.0,
                                                                    b.size_y / 2.0 if b.origin == "corner" else 0.0))
    if design.outline.kind == "circle":
        L.append("- Изделие: круг Ø%.1f мм, высота %.1f мм." % (design.outline.dia, design.thick))
    else:
        x0, y0, x1, y1 = design.outline.bbox()
        L.append("- Изделие: контур %.1f × %.1f мм, высота %.1f мм." % (x1 - x0, y1 - y0, design.thick))
    L.append("- Материал: %s." % ctx.get("material", "-"))
    L.append("")
    L.append("## Инструмент")
    L.append("")
    L.append("| роль | фреза | Ø, мм | S об/мин | регулятор | подача / врезание / рампа, мм/мин |")
    L.append("|---|---|---|---|---|---|")
    for role in ("surface", "rough", "finish", "profile", "groove"):
        t = plan.tools.get(role)
        if t:
            L.append("| %s | %s | %.2f | %d | ~%.1f | %.0f / %.0f / %.0f |" % (
                role, t["name"], t["dia"], t["rpm"], t.get("dial", 0), t["feed"], t["plunge"], t["ramp"]))
    L.append("")
    L.append("## Порядок")
    L.append("")
    n = 0
    for fn, g, tool, title, side, minutes in files:
        n += 1
        note = ""
        if fn.startswith("00"):
            note = " **После торцовки заново обнулить Z по новой плоскости.**"
        if side == "bottom":
            note = (" **Перед этим файлом перевернуть заготовку вокруг оси X (ближний край остаётся ближним, "
                    "верх становится низом), снова обнулить X/Y в том же углу и Z по новому верху.** "
                    "Табы %d × %.0f мм держат деталь." % (plan.cfg.tabs, plan.cfg.tab_len))
        elif fn.startswith("03") and "FLIP" not in fn and plan.profile.get("mode") == "full":
            note = " Насквозь за одну установку, табы %d × %.0f мм." % (plan.cfg.tabs, plan.cfg.tab_len)
        L.append("%d. `%s` — %s — ~%.0f мин.%s" % (n, fn, tool["name"], minutes, note))
    L.append("")
    L.append("## Замечания")
    L.append("")
    notes = [m for m in plan.notes] + [m for m in design.messages if m.level != "error"]
    if not notes:
        L.append("- нет")
    for m in notes:
        L.append("- %s" % m.text)
    L.append("")
    L.append("Отчёт проверки: `report.txt`. Если в нём не «%s» — на станок не нести." % "ГЕОМЕТРИЯ И ТРАЕКТОРИИ В ПОРЯДКЕ")
    return "\n".join(L) + "\n"
