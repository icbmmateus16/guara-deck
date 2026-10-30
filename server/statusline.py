#!/usr/bin/env python3
"""Barra de status do Claude Code: mostra modelo, pasta e limites, e repassa os limites ao Guará.

O Claude Code chama este script a cada atualização, com um JSON no stdin
(rate_limits.five_hour / seven_day: used_percentage 0-100 e resets_at em epoch).
Precisa ser rápido: o envio ao Guará tem timeout curto e nunca quebra a barra.
"""

import json
import sys
import time
import urllib.request


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    try:
        req = urllib.request.Request("http://127.0.0.1:47801/hook/statusline", data=json.dumps(data).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=0.3).close()
    except Exception:
        pass

    parts = [(data.get("model") or {}).get("display_name") or "Claude"]
    cwd = (data.get("workspace") or {}).get("current_dir") or data.get("cwd") or ""
    if cwd:
        parts.append(cwd.rstrip("/").rsplit("/", 1)[-1])
    rl = data.get("rate_limits") or {}
    for key, label in (("five_hour", "5h"), ("seven_day", "semana")):
        b = rl.get(key) or {}
        if b.get("used_percentage") is None:
            continue
        txt = f"{label} {round(float(b['used_percentage']))}%"
        if key == "five_hour" and b.get("resets_at"):
            txt += " ↻" + time.strftime("%H:%M", time.localtime(int(b["resets_at"])))
        parts.append(txt)
    print(" │ ".join(parts))


if __name__ == "__main__":
    main()
