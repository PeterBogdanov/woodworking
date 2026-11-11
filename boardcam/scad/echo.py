# -*- coding: utf-8 -*-
"""Разбор строки ``ECHO: boardcam_design = [...]`` из stderr OpenSCAD.

OpenSCAD печатает векторы в синтаксисе, совместимом с JSON, кроме ``undef``
(-> null), ``inf``/``nan`` (ошибка: таких чисел в описании быть не должно).
Верхний уровень и блок ``derived`` — списки пар ["ключ", значение] -> dict.
"""

import json
import re

ECHO_PREFIX = "ECHO: boardcam_design = "
_UNDEF = re.compile(r"\bundef\b")


class EchoError(ValueError):
    pass


def _replace_outside_strings(text, pattern, repl):
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    break
                j += 1
            out.append(text[i:j + 1])
            i = j + 1
        else:
            j = text.find('"', i)
            if j < 0:
                j = n
            out.append(pattern.sub(repl, text[i:j]))
            i = j
    return "".join(out)


def pairs_to_dict(pairs, what):
    if not isinstance(pairs, list):
        raise EchoError("%s: ожидался список пар, получено %r" % (what, type(pairs).__name__))
    d = {}
    for item in pairs:
        if not (isinstance(item, list) and len(item) == 2 and isinstance(item[0], str)):
            raise EchoError("%s: элемент %r не является парой [\"ключ\", значение]" % (what, item))
        d[item[0]] = item[1]
    return d


def parse_echo(stderr_text):
    """-> (dict описания фигуры или None, остальные строки ECHO/WARNING/ERROR)."""
    design = None
    other = []
    for line in stderr_text.splitlines():
        line = line.rstrip("\r")
        if line.startswith(ECHO_PREFIX):
            if design is not None:
                raise EchoError("boardcam_design напечатан дважды")
            body = line[len(ECHO_PREFIX):].strip()
            body = _replace_outside_strings(body, _UNDEF, "null")
            if re.search(r"\b(inf|nan)\b", _replace_outside_strings(body, re.compile(r'"[^"]*"'), '""')):
                raise EchoError("в boardcam_design есть inf/nan: %s" % body[:200])
            try:
                raw = json.loads(body)
            except ValueError as e:
                raise EchoError("boardcam_design не разбирается как JSON: %s" % e)
            design = pairs_to_dict(raw, "boardcam_design")
            if "derived" in design and design["derived"] is not None:
                design["derived"] = pairs_to_dict(design["derived"], "derived")
        elif line.strip():
            other.append(line)
    return design, other
