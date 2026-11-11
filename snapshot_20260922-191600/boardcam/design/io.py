# -*- coding: utf-8 -*-
"""JSON-сериализация Design (design.json в каталоге прогона)."""

import json

from .model import Design


def dump(design, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(design.to_dict(), f, ensure_ascii=False, indent=1)


def load(path):
    with open(path, encoding="utf-8") as f:
        return Design.from_dict(json.load(f))
