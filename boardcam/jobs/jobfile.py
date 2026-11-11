# -*- coding: utf-8 -*-
"""Файл задания jobs/<name>.json (DESIGN.md §6.2): набор параметров + материал + фрезы."""

import json
import os
import re

_NAME = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


class JobError(ValueError):
    pass


def validate_job(j, name=None):
    if not isinstance(j, dict):
        raise JobError("задание должно быть JSON-объектом")
    out = {
        "schema": j.get("schema", 1),
        "name": j.get("name") or name or "job",
        "shape": j.get("shape"),
        "mesh": j.get("mesh"),
        "preset": j.get("preset"),
        "overrides": j.get("overrides") or {},
        "material": j.get("material"),
        "tools": j.get("tools") or {},
        "options": j.get("options") or {},
        "notes": j.get("notes") or "",
    }
    if out["schema"] != 1:
        raise JobError("схема задания %r не поддерживается" % out["schema"])
    if out["mesh"]:
        if not isinstance(out["mesh"], str) or ".." in out["mesh"].split("/") or out["mesh"].startswith("/"):
            raise JobError("mesh: путь к STL относительно корня проекта, без '..'")
    elif not out["shape"] or not _NAME.match(str(out["shape"])):
        raise JobError("в задании нет допустимого имени фигуры (shape) или файла mesh")
    if not _NAME.match(str(out["name"])):
        raise JobError("имя задания %r: буквы, цифры, точка, дефис, подчёркивание" % out["name"])
    if out["preset"] is not None and not isinstance(out["preset"], str):
        raise JobError("preset должен быть строкой")
    if not isinstance(out["overrides"], dict) or not isinstance(out["tools"], dict) or not isinstance(out["options"], dict):
        raise JobError("overrides, tools и options должны быть объектами")
    for k, v in out["tools"].items():
        if v is not None and not isinstance(v, str):
            raise JobError("tools.%s должен быть id фрезы (строкой)" % k)
    if out["options"].get("flatten", "auto") not in ("auto", "on", "off"):
        raise JobError("options.flatten: auto | on | off")
    if out["options"].get("profile_mode", "auto") not in ("auto", "full", "flip"):
        raise JobError("options.profile_mode: auto | full | flip")
    return out


def load_job(path):
    with open(path, encoding="utf-8") as f:
        try:
            j = json.load(f)
        except ValueError as e:
            raise JobError("%s: не JSON (%s)" % (path, e))
    return validate_job(j, os.path.splitext(os.path.basename(path))[0])


def save_job(job, jobs_dir):
    job = validate_job(job)
    p = os.path.join(jobs_dir, job["name"] + ".json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, p)
    return p


def list_jobs(jobs_dir):
    out = []
    if not os.path.isdir(jobs_dir):
        return out
    for fn in sorted(os.listdir(jobs_dir)):
        if fn.endswith(".json"):
            try:
                out.append(load_job(os.path.join(jobs_dir, fn)))
            except JobError as e:
                out.append({"name": fn[:-5], "error": str(e)})
    return out
