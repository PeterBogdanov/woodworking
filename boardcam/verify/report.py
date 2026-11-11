# -*- coding: utf-8 -*-
"""Текстовый отчёт прогона. Строки-вердикты - контракт (их ищут люди и страница):
   ИТОГ: ГЕОМЕТРИЯ И ТРАЕКТОРИИ В ПОРЯДКЕ  /  ИТОГ: ЕСТЬ ЗАМЕЧАНИЯ - СМ. ВЫШЕ
"""

VERDICT_OK = "ГЕОМЕТРИЯ И ТРАЕКТОРИИ В ПОРЯДКЕ"
VERDICT_BAD = "ЕСТЬ ЗАМЕЧАНИЯ - СМ. ВЫШЕ"


class Report(object):
    def __init__(self):
        self.lines = []
        self.ok = True

    def section(self, title):
        if self.lines:
            self.lines.append("")
        self.lines.append(title)

    def line(self, text=""):
        self.lines.append(text)

    def fail(self, text):
        """Строка '!!' - ошибка, роняет вердикт."""
        self.lines.append("  !! " + text)
        self.ok = False

    def warn(self, text):
        self.lines.append("  ** " + text)

    def finish(self):
        self.lines.append("")
        self.lines.append("ИТОГ: %s" % (VERDICT_OK if self.ok else VERDICT_BAD))
        return "\n".join(self.lines) + "\n"

    @property
    def verdict(self):
        return VERDICT_OK if self.ok else VERDICT_BAD
