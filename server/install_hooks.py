#!/usr/bin/env python3
"""Liga o Claude Code ao Guará (hooks em ~/.claude/settings.json).

    python3 server/install_hooks.py            instala (idempotente, faz backup antes)
    python3 server/install_hooks.py --remover  tira só os hooks do Guará

Eventos de estado: hook de comando assíncrono (não atrasa o Claude; se o servidor estiver
desligado, nada acontece). Aprovação: hook HTTP; sem tablet conectado a pergunta segue no terminal.
"""

import json
import shutil
import sys
import time
from pathlib import Path

SETTINGS = Path.home() / ".claude" / "settings.json"
PORT = 47801
STATE_URL = f"http://127.0.0.1:{PORT}/hook/claude"
PERMISSION_URL = f"http://127.0.0.1:{PORT}/hook/permission"
STATE_EVENTS = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure",
                "Notification", "Stop", "StopFailure", "SessionEnd"]
TOOL_EVENTS = {"PreToolUse", "PostToolUse", "PostToolUseFailure"}

STATE_HOOK = {
    "type": "command",
    "command": f"curl -s -m 2 -X POST -H 'Content-Type: application/json' --data-binary @- {STATE_URL} >/dev/null 2>&1 || true",
    "timeout": 5,
    "async": True,
}
PERMISSION_HOOK = {"type": "http", "url": PERMISSION_URL, "timeout": 130}
STATUSLINE = {"type": "command", "command": f"python3 {str(Path(__file__).resolve().parent / 'statusline.py')!r}"}


def is_capi(hook):
    return STATE_URL in hook.get("command", "") or hook.get("url") == PERMISSION_URL


def strip_capi(hooks):
    """Remove os hooks do Guará e descarta grupos que ficarem vazios."""
    for event in list(hooks):
        groups = []
        for group in hooks[event]:
            kept = [h for h in group.get("hooks", []) if not is_capi(h)]
            if kept:
                groups.append({**group, "hooks": kept})
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]


def main():
    remove = "--remover" in sys.argv
    settings = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
    backup = SETTINGS.with_name(f"settings.json.bak-capi-{time.strftime('%Y%m%d-%H%M%S')}")
    if SETTINGS.exists():
        shutil.copy2(SETTINGS, backup)

    hooks = settings.setdefault("hooks", {})
    strip_capi(hooks)
    if not remove:
        for event in STATE_EVENTS:
            group = {"hooks": [dict(STATE_HOOK)]}
            if event in TOOL_EVENTS:
                group = {"matcher": "*", **group}
            hooks.setdefault(event, []).append(group)
        hooks.setdefault("PermissionRequest", []).append({"matcher": "", "hooks": [dict(PERMISSION_HOOK)]})
    if not hooks:
        del settings["hooks"]

    # Barra de status: leva o uso do limite de 5 h ao tablet. Não substitui uma barra que já seja sua.
    current = settings.get("statusLine") or {}
    ours = "statusline.py" in current.get("command", "")
    if remove and ours:
        del settings["statusLine"]
    elif not remove and (not current or ours):
        settings["statusLine"] = STATUSLINE
    elif not remove:
        print("Aviso: você já tem uma statusLine própria; o medidor de limite do tablet não vai funcionar.")

    SETTINGS.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    print(("Hooks do Guará removidos." if remove else "Hooks do Guará instalados.") + f" Backup: {backup}")


if __name__ == "__main__":
    main()
