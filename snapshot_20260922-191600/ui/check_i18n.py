# -*- coding: utf-8 -*-
"""Проверка перевода страницы: каждая русская строка index.html и app.js
должна быть ключом словаря в i18n.js, а в app.js - ещё и обёрнута в t().

    python3 ui/check_i18n.py      # молчит и возвращает 0, если всё на месте
"""
import io
import os
import re
import sys
from html.parser import HTMLParser

UI = os.path.dirname(os.path.abspath(__file__))
CYR = re.compile(u"[А-яЁё]")
IGNORE = (u"Language / Язык", u"Русский")  # переключатель языка


def read(name):
    with io.open(os.path.join(UI, name), encoding="utf-8") as f:
        return f.read()


class Page(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self.found = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        for a, v in attrs:
            if a in ("placeholder", "title", "alt") and v:
                self.found.append(v)

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.found.append(data.strip())


def main():
    keys = set(re.findall(r"^  '((?:[^'\\]|\\.)*)':", read("i18n.js"), re.M))
    bad = []

    page = Page()
    page.feed(read("index.html"))
    for s in page.found:
        if s and CYR.search(s) and s not in keys and s not in IGNORE:
            bad.append("index.html: нет в словаре: %r" % s)

    app = read("app.js")
    for m in re.finditer(r"'((?:[^'\\]|\\.)*)'", app):
        s = m.group(1)
        if not CYR.search(s):
            continue
        if not app[:m.start()].endswith("t("):
            bad.append("app.js:%d: строка без t(): %r" % (app[:m.start()].count("\n") + 1, s))
        elif s not in keys:
            bad.append("app.js:%d: нет в словаре: %r" % (app[:m.start()].count("\n") + 1, s))

    for line in bad:
        print(line)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
