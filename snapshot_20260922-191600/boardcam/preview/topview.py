# -*- coding: utf-8 -*-
"""Плоское превью сверху (SVG): заготовка, контур, карманы, траектории по ролям."""

from .. import VERSION

COLORS = {'rough': '#ff3b30', 'finish': '#0a84ff', 'profile': '#22a04a', 'groove': '#b060d0', 'surface': '#999'}


def topview_svg(design, pockets, paths, scale=1.7, title=None):
    """pockets - карманы CAM (с .rings); paths - [(роль, [(x,y),...]), ...]."""
    blank = design.blank
    W = blank.size_x * scale + 120
    H = blank.size_y * scale + 120
    cx, cy = W / 2.0 + 10, H / 2.0 + 10

    def T(p):
        return (cx + p[0] * scale, cy - p[1] * scale)

    o = ['<svg xmlns="http://www.w3.org/2000/svg" width="%.0f" height="%.0f" viewBox="0 0 %.0f %.0f">' % (W, H, W, H),
         '<rect width="100%" height="100%" fill="#f7f2e8"/>']
    bx, by = blank.size_x / 2.0, blank.size_y / 2.0
    o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="none" stroke="#999" stroke-dasharray="6,4"/>'
             % (cx - bx * scale, cy - by * scale, 2 * bx * scale, 2 * by * scale))
    if design.outline.kind == 'circle':
        o.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="#c9a271" stroke="#8a6a42" stroke-width="1.5"/>'
                 % (cx, cy, design.outline.dia / 2 * scale))
    else:
        d = "M " + " L ".join("%.2f,%.2f" % T(p) for p in design.outline.region.outer) + " Z"
        o.append('<path d="%s" fill="#c9a271" stroke="#8a6a42" stroke-width="1.5"/>' % d)
    if blank.origin == 'corner':
        o.append('<circle cx="%.1f" cy="%.1f" r="5" fill="#d00"/>' % (cx - bx * scale, cy + by * scale))
        o.append('<text x="%.1f" y="%.1f" font-family="monospace" font-size="12" fill="#d00">X0Y0</text>'
                 % (cx - bx * scale + 8, cy + by * scale - 8))
    for pk in pockets:
        d = " ".join("M " + " L ".join("%.2f,%.2f" % T(p) for p in ring) + " Z" for ring in pk.rings)
        o.append('<path d="%s" fill="#a97e4c" stroke="#6f5127" stroke-width="1" fill-rule="evenodd"/>' % d)
    for kind, pts in paths:
        if len(pts) < 2:
            continue
        step = max(1, len(pts) // 3000)
        d = "M " + " L ".join("%.2f,%.2f" % T(p) for p in pts[::step])
        o.append('<path d="%s" fill="none" stroke="%s" stroke-width="0.5" opacity="0.8"/>' % (d, COLORS.get(kind, '#000')))
    o.append('<text x="14" y="22" font-family="monospace" font-size="13" fill="#222">boardcam v%s   %s</text>'
             % (VERSION, title or "%s / %s" % (design.shape, design.source.get("preset") or "")))
    y = 40
    for role, col in COLORS.items():
        if any(k == role for k, _ in paths):
            o.append('<text x="14" y="%d" font-family="monospace" font-size="11" fill="%s">%s</text>' % (y, col, role))
            y += 15
    o.append('</svg>')
    return "\n".join(o)


def preview_paths(plan, pockets, design, cfg):
    """Траектории для превью: дуги растра и обходы - каждая отдельной линией."""
    from ..geometry.polyline import arc_points
    paths = []
    tr, tf = plan.tools.get('rough'), plan.tools.get('finish')
    for pk in pockets:
        if tr:
            for pl in pk.plan_raster(tr['dia'] / 2, cfg.wall_allow, tr['stepover']).paths(0.05):
                paths.append(('rough', pl))
        if tf:
            for pl in pk.plan_raster(tf['dia'] / 2, 0.0, tf['stepover']).paths(0.05):
                paths.append(('finish', pl))
            for run in pk.contour_runs(tf['dia'] / 2.0)[0]:
                paths.append(('finish', run))
    return paths
