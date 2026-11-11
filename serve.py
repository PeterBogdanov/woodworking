#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Локальный сервер интерактивного дизайна доски.

Запуск:
    python3 serve.py            # или: python3 serve.py 8000

Откройте http://127.0.0.1:8000/ — ползунки + живое превью + генерация G-code.

Эндпоинты (контракт в tasks/00_ОБЩЕЕ.md):
    GET /layouts            [{id, title, n_pockets, center, defaults}]
    GET /woods              [{id, title, janka, scale, rpm, dial, note}]
    GET /bits               [{id, title, role, dia, rpm, ...}]
    GET /preview.svg?<...>  форма, быстро (<0.1 с)
    GET /paths.svg?bits=...&<...>   траектории выбранных фрез (4-5 с)
    GET /generate?<...>     -> {ok, report, files:[{name,size,minutes,url}]}
    GET /nc/<имя>.nc        скачивание одного файла
    GET /nc.zip             все файлы архивом
"""

import contextlib
import http.server
import io
import json
import os
import re
import sys
import urllib.parse
import zipfile

import generate_board as G

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

# Ключ фрезы -> теги её траекторий в превью. Пока G.BITS (с полем role) не
# заведён, маппинг живёт здесь; когда появится BITS — можно брать role оттуда.
BIT_TAGS = {
    'em':        ('rough', 'profile'),   # Molly Mill: черновая + контур
    'bowl':      ('finish',),            # Whiteside 1372: чистовая
    'roundnose': (),                     # 1406: жёлоб (в превью траекторий нет)
    'surf':      (),                     # торцовка (в превью траекторий нет)
    # синонимы на случай, если пришлют тег вместо ключа
    'rough':     ('rough',),
    'finish':    ('finish',),
    'profile':   ('profile',),
}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # тихо

    def _send(self, code, ctype, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, "application/json; charset=utf-8",
                   json.dumps(obj, ensure_ascii=False))

    def _error(self, e):
        print("[serve.py] %s: %s" % (self.path, e), file=sys.stderr)
        self._send(500, "text/plain; charset=utf-8", "Внутренняя ошибка: %s" % e)

    # ------------------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        path = parsed.path
        try:
            if path in ("/", "/index.html"):
                self._page()
            elif path == "/layouts":
                ls = getattr(G, "LAYOUTS", None)
                self._json(200, ls if isinstance(ls, list) else [])
            elif path == "/woods":
                ws = getattr(G, "WOODS", None)
                if isinstance(ws, dict):
                    self._json(200, [{"id": k, **v} for k, v in ws.items()])
                else:
                    self._json(200, ws if isinstance(ws, list) else [])
            elif path == "/bits":
                bs = getattr(G, "BITS", None)
                self._json(200, bs if isinstance(bs, list) else [])
            elif path == "/preview.svg":
                self._send(200, "image/svg+xml", G.shape_svg(q))
            elif path == "/paths.svg":
                tags = self._bits_to_tags(q.get("bits", ""))
                self._send(200, "image/svg+xml", G.paths_svg(tags, q))
            elif path == "/generate":
                self._generate(q)
            elif path == "/nc.zip":
                self._nc_zip()
            elif path.startswith("/nc/"):
                self._nc_file(os.path.basename(path))
            else:
                self._send(404, "text/plain", "not found")
        except Exception as e:
            self._error(e)

    # ------------------------------------------------------------------
    def _page(self):
        try:
            with io.open("interactive.html", encoding="utf-8") as f:
                page = f.read().replace("{{VERSION}}", G.VERSION)
            self._send(200, "text/html; charset=utf-8", page)
        except FileNotFoundError:
            self._send(404, "text/plain", "interactive.html not found")

    def _bits_to_tags(self, bits):
        """'em,bowl' -> {'rough','profile','finish'}. Неизвестные ключи игнорируем."""
        tags, any_bit = set(), False
        for b in bits.split(","):
            b = b.strip()
            if b:
                tags.update(BIT_TAGS.get(b, ()))
                any_bit = True
        # пустой набор при заданных фрезах = у них нет траекторий, показать нечего;
        # None (параметр не пришёл) = показать всё
        return tags if any_bit else None

    def _generate(self, q):
        # WOOD — строковая глобальная; set_params числовые не трогает
        if "WOOD" in q:
            G.WOOD = q["WOOD"]
        G.set_params(q)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            G.main()
        report = buf.getvalue()
        files = self._report_files(report)
        self._json(200, {
            "ok": "В ПОРЯДКЕ" in report,
            "report": report,
            "files": files,
        })

    def _report_files(self, report):
        """Достать из отчёта строки 'файл ... ~N мин' и собрать список файлов."""
        files = []
        for line in report.splitlines():
            m = re.search(r"^\s*(\S+\.nc)\s.*?~\s*(\d+)\s+мин", line)
            if not m:
                continue
            name = m.group(1)
            minutes = int(m.group(2))
            try:
                size = os.path.getsize(os.path.join("nc", name))
            except OSError:
                size = 0
            files.append({"name": name, "size": size, "minutes": minutes,
                          "url": "/nc/" + name})
        return files

    def _nc_file(self, name):
        # basename уже применён в do_GET; здесь ещё раз - защита от выхода из nc/
        name = os.path.basename(name)
        if not name.endswith(".nc"):
            self._send(404, "text/plain", "not found")
            return
        full = os.path.join("nc", name)
        if not os.path.isfile(full):
            self._send(404, "text/plain", "not found")
            return
        with open(full, "rb") as f:
            self._send(200, "application/octet-stream", f.read())

    def _nc_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name in sorted(os.listdir("nc")):
                if name.endswith(".nc"):
                    z.write(os.path.join("nc", name), name)
        self._send(200, "application/zip", buf.getvalue())


if __name__ == "__main__":
    print("Дизайн доски v%s (мм): http://127.0.0.1:%d/  (Ctrl+C — стоп)" % (G.VERSION, PORT))
    http.server.HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
