# -*- coding: utf-8 -*-
"""Настройки станка/стратегии для траекторий (из data/machine.json)."""


class CamSettings(object):
    def __init__(self, machine):
        m = machine or {}
        self.z_retract = float(m.get("z_safe", 9.0))
        self.z_link = float(m.get("z_link", 3.0))
        self.ramp_len = float(m.get("ramp_len", 25.0))
        self.sag_rough = float(m.get("sag_rough", 0.06))
        self.sag_finish = float(m.get("sag_finish", 0.01))
        self.profile_extra = float(m.get("profile_extra", 1.2))
        self.wall_allow = float(m.get("wall_allow", 0.6))
        self.floor_allow = float(m.get("floor_allow", 0.6))
        tabs = m.get("tabs", {})
        self.tabs = int(tabs.get("count", 5))
        self.tab_len = float(tabs.get("len", 23.0))
        self.tab_h = float(tabs.get("h", 4.0))
        self.tab_ramp = float(tabs.get("ramp", 13.0))
        self.min_wall = float(m.get("min_wall", 4.0))
        self.field = list(m.get("field", [812.0, 812.0]))
        sim = m.get("sim", {})
        self.coverage_step = float(sim.get("coverage_step", 3.0))
        self.heightmap_pitch = float(sim.get("heightmap_pitch", 1.0))
        self.gouge_tol = float(sim.get("gouge_tol", 0.10))
