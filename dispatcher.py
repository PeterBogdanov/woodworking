#!/usr/bin/env python3
"""
AI Task Dispatcher — woodworking project
Роли по AGENT.md (Ollama ПО МАКСИМУМУ, DeepSeek — контроль):
  - Ollama (qwen3-coder:30b): по умолчанию для всего, бесплатно
  - DeepSeek (deepseek-flash / deepseek-v4-pro): fallback при сбое Ollama, проверка, сложное — платно
  - Antigravity: диспетчер (контроль и архитектура)

Использование:
  python dispatcher.py "задача"              # Ollama; при сбое → DeepSeek
  python dispatcher.py "задача" --ollama     # принудительно в Ollama
  python dispatcher.py "задача" --deepseek   # принудительно в DeepSeek
  python dispatcher.py "задача" --strong     # принудительно DeepSeek v4-pro
  python dispatcher.py "задача" --verify     # Ollama → проверка DeepSeek
"""

import argparse
import json
import os
import sys
import textwrap
import urllib.request
import urllib.error

# ── Конфиг ──────────────────────────────────────────────────────────────────
def _load_env_fallback():
    for fpath in [os.path.expanduser("~/.zshrc"), os.path.expanduser("~/.bashrc")]:
        if os.path.exists(fpath):
            try:
                with open(fpath, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("export DEEPSEEK_API_KEY=") and not os.getenv("DEEPSEEK_API_KEY"):
                            v = line.split("=", 1)[1].strip("'\" ")
                            os.environ["DEEPSEEK_API_KEY"] = v
                        if line.startswith("export OLLAMA_HOST=") and not os.getenv("OLLAMA_HOST"):
                            v = line.split("=", 1)[1].strip("'\" ")
                            os.environ["OLLAMA_HOST"] = v
            except Exception:
                pass

_load_env_fallback()

OLLAMA_HOST  = os.getenv("OLLAMA_HOST", "http://dst-1600g-dst01.tail8aa093.ts.net:11434")
OLLAMA_MODEL = "qwen3-coder:30b"

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_HOST    = "https://api.deepseek.com"
DEEPSEEK_CHEAP   = "deepseek-flash"    # для проверки
DEEPSEEK_STRONG  = "deepseek-v4-pro"  # для сложных задач

# Слова-маркеры сложной задачи → сильная модель DeepSeek (когда DeepSeek уже выбран)
COMPLEX_KEYWORDS = [
    "архитектур", "рефактор", "новый модуль", "совместимост",
    "интерфейс", "дизайн", "ошибка непонятна", "не работает",
    "architecture", "refactor", "new module", "compatibility",
    "interface", "design", "unknown error",
]

# ── HTTP helpers ─────────────────────────────────────────────────────────────
def _post(url: str, payload: dict, headers=None) -> dict:
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(url, data=data,
                                   headers={"Content-Type": "application/json",
                                            **(headers or {})},
                                   method="POST")
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())

# ── Ollama ───────────────────────────────────────────────────────────────────
def ask_ollama(prompt: str, system: str = "") -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    print(f"[Ollama → {OLLAMA_MODEL}] отправляю...", flush=True)
    result = _post(f"{OLLAMA_HOST}/api/chat",
                   {"model": OLLAMA_MODEL, "messages": messages, "stream": False})
    pc, ec = result.get("prompt_eval_count"), result.get("eval_count")
    if pc is not None or ec is not None:
        print(f"[Ollama] токены: prompt={pc}, completion={ec}, всего={(pc or 0) + (ec or 0)}", flush=True)
    return result["message"]["content"]

# ── DeepSeek ─────────────────────────────────────────────────────────────────
def ask_deepseek(prompt: str, system: str = "", model: str = DEEPSEEK_CHEAP) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    print(f"[DeepSeek → {model}] отправляю...", flush=True)
    result = _post(f"{DEEPSEEK_HOST}/v1/chat/completions",
                   {"model": model, "messages": messages},
                   headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"})
    u = result.get("usage") or {}
    print(f"[DeepSeek {model}] токены: prompt={u.get('prompt_tokens')}, completion={u.get('completion_tokens')}, всего={u.get('total_tokens')}", flush=True)
    return result["choices"][0]["message"]["content"]

# ── Маршрутизатор ────────────────────────────────────────────────────────────
def is_complex(task: str) -> bool:
    low = task.lower()
    return any(kw in low for kw in COMPLEX_KEYWORDS)

def dispatch(task: str, force=None, verify: bool = False) -> None:
    print(f"\n{'='*60}")
    print(f"ЗАДАЧА: {textwrap.shorten(task, 120)}")
    print(f"{'='*60}\n")

    # Ollama по умолчанию; DeepSeek — только явно (--deepseek/--strong) или при неудаче Ollama.
    route = "deepseek" if force == "deepseek" else "ollama"

    system = (
        "Ты — помощник в проекте деревообработки (boardcam). "
        "Отвечай конкретно, пиши только код или объяснение — без лишних слов."
    )

    if route == "ollama":
        try:
            answer = ask_ollama(task, system)
        except Exception as e:
            print(f"[Ollama недоступна: {e}] → переключаюсь на DeepSeek")
            route = "deepseek"

    if route == "ollama":
        print(f"\n── Ответ Ollama ──────────────────────────────────────────")
        print(answer)

        if verify:
            print(f"\n── Проверка DeepSeek ({DEEPSEEK_CHEAP}) ─────────────────────")
            verify_prompt = (
                f"Вот задача:\n{task}\n\n"
                f"Вот ответ локальной модели:\n{answer}\n\n"
                "Проверь ответ: есть ли ошибки, неточности, что улучшить? "
                "Если ответ верный — скажи 'OK'. Иначе — укажи что исправить."
            )
            verdict = ask_deepseek(verify_prompt, model=DEEPSEEK_CHEAP)
            print(verdict)

    else:  # deepseek (явный выбор или fallback после неудачи Ollama)
        model = DEEPSEEK_STRONG if is_complex(task) else DEEPSEEK_CHEAP
        answer = ask_deepseek(task, system, model=model)
        print(f"\n── Ответ DeepSeek ({model}) ──────────────────────────────")
        print(answer)

    print(f"\n{'='*60}\n")

# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="AI Task Dispatcher")
    parser.add_argument("task", nargs="?", help="Задача (или читается из stdin)")
    parser.add_argument("--ollama",   action="store_true", help="Принудительно → Ollama")
    parser.add_argument("--deepseek", action="store_true", help="Принудительно → DeepSeek")
    parser.add_argument("--verify",   action="store_true",
                        help="Ollama выполняет, DeepSeek проверяет")
    parser.add_argument("--strong",   action="store_true",
                        help="Принудительно DeepSeek v4-pro")
    args = parser.parse_args()

    task = args.task or sys.stdin.read().strip()
    if not task:
        parser.print_help()
        sys.exit(1)

    force = None
    if args.ollama:   force = "ollama"
    if args.deepseek: force = "deepseek"
    if args.strong:
        force = "deepseek"
        global DEEPSEEK_CHEAP
        DEEPSEEK_CHEAP = DEEPSEEK_STRONG

    dispatch(task, force=force, verify=args.verify)

if __name__ == "__main__":
    main()
