#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Точка запуска CamStudio — автономного Next-Gen CAM приложения."""

import os
import sys

# Добавляем родительский каталог в PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cam_studio.server import run_server

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    sys.exit(run_server(port))
