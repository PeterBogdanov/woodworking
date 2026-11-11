# -*- coding: utf-8 -*-
"""Библиотека: фрезы, материалы, станок (data/*.json). Загрузка, проверка, CRUD.

Записи хранятся словарями - так их отдаёт API и редактирует страница.
"""

import json
import os

TOOL_TYPES = ("flat", "bowl", "ball", "vee", "surfacing")
ROLES = ("rough", "finish", "profile", "groove", "surface")
TOOL_REQUIRED = ("id", "name", "type", "dia", "loc", "rpm", "rpm_max", "feed", "plunge", "ramp",
                 "stepover", "doc", "roles")
TOOL_NUMERIC = ("dia", "loc", "rpm", "rpm_max", "feed", "plunge", "ramp", "stepover", "doc",
                "corner_r", "shank", "feed_contour")
MATERIAL_REQUIRED = ("id", "title", "feed_scale", "rpm", "dial")
MACHINE_REQUIRED = ("field", "z_safe", "z_link", "tabs", "profile_extra")


class LibraryError(ValueError):
    pass


def _num(rec, key, what, errors, required):
    if key not in rec:
        if required:
            errors.append("%s: нет поля %r" % (what, key))
        return
    v = rec[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        errors.append("%s: поле %r должно быть числом, а не %r" % (what, key, v))
    elif v < 0:
        errors.append("%s: поле %r отрицательное" % (what, key))


def validate_tool(rec):
    errors = []
    what = "фреза %r" % rec.get("id", "?")
    for k in TOOL_REQUIRED:
        if k not in rec:
            errors.append("%s: нет поля %r" % (what, k))
    if errors:
        return errors
    if not isinstance(rec["id"], str) or not rec["id"].strip():
        errors.append("фреза: пустой id")
    if rec["type"] not in TOOL_TYPES:
        errors.append("%s: тип %r, допустимы %s" % (what, rec["type"], "/".join(TOOL_TYPES)))
    for k in TOOL_NUMERIC:
        _num(rec, k, what, errors, required=(k in TOOL_REQUIRED))
    if not isinstance(rec["roles"], list) or not rec["roles"]:
        errors.append("%s: roles должен быть непустым списком" % what)
    else:
        for r in rec["roles"]:
            if r not in ROLES:
                errors.append("%s: роль %r, допустимы %s" % (what, r, "/".join(ROLES)))
    if not errors:
        if rec["type"] == "bowl" and not rec.get("corner_r"):
            errors.append("%s: у чашечной фрезы нужен corner_r (радиус скругления)" % what)
        if rec["type"] == "ball" and not rec.get("corner_r"):
            errors.append("%s: у шаровой фрезы нужен corner_r (= dia/2)" % what)
        if rec.get("corner_r", 0) > rec["dia"] / 2.0 + 1e-6:
            errors.append("%s: corner_r больше радиуса фрезы" % what)
        if rec["rpm"] > rec["rpm_max"]:
            errors.append("%s: rpm %s больше rpm_max %s" % (what, rec["rpm"], rec["rpm_max"]))
        if rec["doc"] <= 0:
            errors.append("%s: doc (глубина за проход) должна быть > 0" % what)
    return errors


def validate_material(rec):
    errors = []
    what = "материал %r" % rec.get("id", "?")
    for k in MATERIAL_REQUIRED:
        if k not in rec:
            errors.append("%s: нет поля %r" % (what, k))
    if errors:
        return errors
    for k in ("feed_scale", "rpm", "dial"):
        _num(rec, k, what, errors, True)
    if "janka" in rec and rec["janka"] is not None:
        _num(rec, "janka", what, errors, False)
    if not errors and not (0.2 <= rec["feed_scale"] <= 3.0):
        errors.append("%s: feed_scale %s вне разумного 0.2..3" % (what, rec["feed_scale"]))
    return errors


def validate_machine(rec):
    errors = []
    for k in MACHINE_REQUIRED:
        if k not in rec:
            errors.append("станок: нет поля %r" % k)
    if errors:
        return errors
    f = rec["field"]
    if not (isinstance(f, list) and len(f) == 2 and all(isinstance(x, (int, float)) for x in f)):
        errors.append("станок: field должен быть [X, Y] в мм")
    for k in ("z_safe", "z_link", "profile_extra"):
        _num(rec, k, "станок", errors, True)
    t = rec["tabs"]
    for k in ("count", "len", "h", "ramp"):
        if k not in t:
            errors.append("станок: tabs без поля %r" % k)
    return errors


class Library(object):
    def __init__(self, tools, materials, machine, data_dir=None):
        self.tools = list(tools)
        self.materials = list(materials)
        self.machine = dict(machine)
        self.data_dir = data_dir

    def validate(self):
        errors = []
        ids = set()
        for t in self.tools:
            errors += validate_tool(t)
            if t.get("id") in ids:
                errors.append("фреза %r встречается дважды" % t["id"])
            ids.add(t.get("id"))
        ids = set()
        refs = 0
        for m in self.materials:
            errors += validate_material(m)
            if m.get("id") in ids:
                errors.append("материал %r встречается дважды" % m["id"])
            ids.add(m.get("id"))
            refs += 1 if m.get("reference") else 0
        if self.materials and refs != 1:
            errors.append("ровно один материал должен быть отмечен reference: true (сейчас %d)" % refs)
        errors += validate_machine(self.machine)
        return errors

    def tool(self, tid):
        for t in self.tools:
            if t["id"] == tid:
                return t
        return None

    def material(self, mid):
        for m in self.materials:
            if m["id"] == mid:
                return m
        return None

    def reference_material(self):
        for m in self.materials:
            if m.get("reference"):
                return m
        return self.materials[0] if self.materials else None

    def tools_for(self, role, tool_type=None):
        return [t for t in self.tools if role in t.get("roles", ())
                and (tool_type is None or t["type"] == tool_type)]

    def dial_for(self, rpm):
        d = self.machine.get("dial", {})
        k, b = float(d.get("k", 5000.0)), float(d.get("b", 2000.0))
        return max(1.0, min(6.0, (rpm - b) / k))

    def scaled_tool(self, tool, material):
        """Копия записи фрезы с подачами под материал и оборотами не выше паспортных."""
        t = dict(tool)
        s = float(material.get("feed_scale", 1.0))
        for k in ("feed", "plunge", "ramp", "feed_contour"):
            if k in t:
                t[k] = float(t[k]) * s
        t["rpm"] = int(min(float(material.get("rpm", t["rpm"])), float(t["rpm_max"])))
        t["dial"] = self.dial_for(t["rpm"])
        t["material"] = material["id"]
        return t


def load(data_dir):
    def rd(name):
        p = os.path.join(data_dir, name)
        if not os.path.isfile(p):
            raise LibraryError("нет файла %s" % p)
        with open(p, encoding="utf-8") as f:
            try:
                return json.load(f)
            except ValueError as e:
                raise LibraryError("%s: не JSON (%s)" % (p, e))
    lib = Library(rd("tools.json"), rd("materials.json"), rd("machine.json"), data_dir)
    errors = lib.validate()
    if errors:
        raise LibraryError("библиотека %s:\n  " % data_dir + "\n  ".join(errors))
    return lib


def save(lib, data_dir=None):
    data_dir = data_dir or lib.data_dir
    errors = lib.validate()
    if errors:
        raise LibraryError("\n".join(errors))
    for name, obj in (("tools.json", lib.tools), ("materials.json", lib.materials), ("machine.json", lib.machine)):
        p = os.path.join(data_dir, name)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
            f.write("\n")
        os.replace(tmp, p)


def upsert(lib, kind, rec):
    """Добавить или заменить запись; kind = tools | materials. Возвращает список ошибок."""
    if kind == "tools":
        errors = validate_tool(rec)
        coll = lib.tools
    elif kind == "materials":
        errors = validate_material(rec)
        coll = lib.materials
    else:
        return ["неизвестный раздел библиотеки %r" % kind]
    if errors:
        return errors
    for i, r in enumerate(coll):
        if r["id"] == rec["id"]:
            coll[i] = rec
            break
    else:
        coll.append(rec)
    errors = lib.validate()
    return errors


def references_in_jobs(jobs_dir, kind, rid):
    """Какие задания ссылаются на запись (материал или фрезу)."""
    out = []
    if not jobs_dir or not os.path.isdir(jobs_dir):
        return out
    for fn in sorted(os.listdir(jobs_dir)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(jobs_dir, fn), encoding="utf-8") as f:
                j = json.load(f)
        except (OSError, ValueError):
            continue
        if kind == "materials" and j.get("material") == rid:
            out.append(fn)
        if kind == "tools" and rid in (j.get("tools") or {}).values():
            out.append(fn)
    return out


def remove(lib, kind, rid, jobs_dir=None):
    coll = lib.tools if kind == "tools" else lib.materials if kind == "materials" else None
    if coll is None:
        return ["неизвестный раздел библиотеки %r" % kind]
    if not any(r["id"] == rid for r in coll):
        return ["записи %r нет" % rid]
    used = references_in_jobs(jobs_dir, kind, rid)
    if used:
        return ["запись %r используется заданиями: %s" % (rid, ", ".join(used))]
    coll[:] = [r for r in coll if r["id"] != rid]
    return lib.validate()
