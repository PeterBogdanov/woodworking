# -*- coding: utf-8 -*-
"""run.zip - всё содержимое каталога прогона, кроме самого архива."""

import os
import zipfile


def zip_run(run_dir, name="run.zip"):
    out = os.path.join(run_dir, name)
    tmp = out + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(run_dir):
            for fn in sorted(files):
                p = os.path.join(root, fn)
                if os.path.abspath(p) in (os.path.abspath(out), os.path.abspath(tmp)):
                    continue
                z.write(p, os.path.relpath(p, run_dir))
    os.replace(tmp, out)
    return out
