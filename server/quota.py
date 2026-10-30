"""Créditos das IAs: quanto resta de cada limite (Claude, GPT/Codex, Gemini/Antigravity).

Fontes, da mais fresca para a mais velha:
- Claude: evento `rate_limit_event` que o `claude -p` emite a cada chamada; barra de status do
  Claude Code (terminal); cache `cachedUsageUtilization` do ~/.claude.json (atualizado pelo /usage).
- GPT: `rate_limits` que o Codex grava nos arquivos de sessão (~/.codex/sessions).
- Antigravity: não publica limite; contamos só o uso feito pelo Guará.
"""

import json
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

CLAUDE_JSON = Path.home() / ".claude.json"
PROBE_DIR = Path("/tmp/guara-consulta")   # a consulta de limite roda aqui e não aparece como sessão
CODEX_SESSIONS = Path.home() / ".codex" / "sessions"
STATE_FILE = Path.home() / ".cache" / "guara" / "quota.json"   # última leitura, para sobreviver a reinícios
PROBE_EVERY = 1800   # com o tablet ligado, consulta o Claude a cada 30 min (custa quase nada)


def _iso(ts):
    try:
        return int(datetime.fromisoformat(ts).timestamp())
    except Exception:
        return 0


class Quota:
    def __init__(self, engine_path):
        self.engine_path = engine_path
        self.lock = threading.Lock()
        self.data = {"claude": {}, "codex": {}, "agy": {"uses": 0, "day": time.strftime("%Y-%m-%d")}}
        self.last_probe = 0.0
        try:
            saved = json.loads(STATE_FILE.read_text())
            self.data["claude"] = saved.get("claude") or {}
        except Exception:
            pass
        self.read_claude_cache()
        self.read_codex()

    # ------------------------------------------------------------ Claude

    def _set_claude(self, five, five_reset, week, week_reset, src):
        with self.lock:
            c = self.data["claude"]
            if five is not None:
                c["five_hour"] = {"pct": round(five), "resets": int(five_reset or 0)}
            if week is not None:
                c["seven_day"] = {"pct": round(week), "resets": int(week_reset or 0)}
            c["src"], c["at"] = src, int(time.time())
            try:
                STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
                STATE_FILE.write_text(json.dumps({"claude": c}))
            except Exception:
                pass

    def from_claude_event(self, info):
        """rate_limit_info do stream-json: utilization 0-1 por janela."""
        win = info.get("unifiedWindows") or {}
        f, w = win.get("five_hour") or {}, win.get("seven_day") or {}
        self._set_claude(
            f["utilization"] * 100 if f.get("utilization") is not None else None, f.get("resetsAt"),
            w["utilization"] * 100 if w.get("utilization") is not None else None, w.get("resetsAt"), "ao vivo")

    def from_statusline(self, rate_limits):
        f, w = rate_limits.get("five_hour") or {}, rate_limits.get("seven_day") or {}
        if f.get("used_percentage") is None and w.get("used_percentage") is None:
            return False
        self._set_claude(f.get("used_percentage"), f.get("resets_at"), w.get("used_percentage"), w.get("resets_at"), "ao vivo")
        return True

    def read_claude_cache(self):
        try:
            cache = json.loads(CLAUDE_JSON.read_text()).get("cachedUsageUtilization") or {}
        except Exception:
            return
        at = int((cache.get("fetchedAtMs") or 0) / 1000)
        if at <= (self.data["claude"].get("at") or 0):
            return
        u = cache.get("utilization") or {}
        f, w = u.get("five_hour") or {}, u.get("seven_day") or {}
        self._set_claude(f.get("utilization"), _iso(f.get("resets_at")), w.get("utilization"), _iso(w.get("resets_at")), "cache")
        self.data["claude"]["at"] = at

    def probe_claude(self):
        """Chamada mínima (modelo leve, prompt "ok") só para ler o limite oficial."""
        claude = shutil.which("claude", path=self.engine_path)
        if not claude:
            return
        self.last_probe = time.time()
        PROBE_DIR.mkdir(exist_ok=True)
        try:
            out = subprocess.run([claude, "-p", "ok", "--model", "haiku", "--output-format", "stream-json", "--verbose"],
                                 capture_output=True, text=True, timeout=90, cwd=str(PROBE_DIR)).stdout
        except Exception:
            return
        for line in out.splitlines():
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("type") == "rate_limit_event":
                self.from_claude_event(d.get("rate_limit_info") or {})

    # ------------------------------------------------------------ GPT (Codex)

    def probe_codex(self):
        """Chamada mínima ao Codex: ele grava o limite atualizado no arquivo da sessão."""
        codex = shutil.which("codex", path=self.engine_path)
        if not codex:
            return
        PROBE_DIR.mkdir(exist_ok=True)
        try:
            subprocess.run([codex, "exec", "--skip-git-repo-check", "-c", 'sandbox_mode="read-only"', "--json", "Responda só: ok"],
                           capture_output=True, text=True, timeout=90, cwd=str(PROBE_DIR))
        except Exception:
            return
        self.read_codex()

    def read_codex(self):
        files = sorted(CODEX_SESSIONS.glob("*/*/*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]
        for f in files:
            try:
                lines = f.read_text(errors="ignore").splitlines()
            except Exception:
                continue
            for line in reversed(lines):
                if '"rate_limits"' not in line:
                    continue
                try:
                    rl = _find_key(json.loads(line), "rate_limits")
                except Exception:
                    continue
                if not rl:
                    continue
                p, s = rl.get("primary") or {}, rl.get("secondary") or {}
                with self.lock:
                    self.data["codex"] = {
                        "five_hour": {"pct": round(p.get("used_percent", 0)), "resets": int(p.get("resets_at") or 0)},
                        "seven_day": {"pct": round(s.get("used_percent", 0)), "resets": int(s.get("resets_at") or 0)},
                        "src": "ao vivo", "at": int(f.stat().st_mtime),
                    }
                return

    # ------------------------------------------------------------ Antigravity

    def note_use(self, engine):
        if engine != "agy":
            return
        with self.lock:
            a = self.data["agy"]
            today = time.strftime("%Y-%m-%d")
            if a.get("day") != today:
                a.update(uses=0, day=today)
            a["uses"] += 1
            a["at"] = int(time.time())

    # ------------------------------------------------------------ visão

    def claude_exhausted(self):
        now = time.time()
        for key in ("five_hour", "seven_day"):
            b = self.data["claude"].get(key) or {}
            if b.get("pct", 0) >= 100 and b.get("resets", 0) > now:
                return b["resets"]
        return 0

    def view(self):
        now = time.time()
        out = {}
        with self.lock:
            for eng in ("claude", "codex"):
                d = self.data[eng]
                v = {"src": d.get("src"), "at": d.get("at")}
                for key in ("five_hour", "seven_day"):
                    b = d.get(key)
                    if not b:
                        continue
                    if b.get("resets") and b["resets"] < now:
                        # janela renovou. Se a última leitura é posterior à renovação e não trouxe uso
                        # dessa janela, ela está intacta; se é anterior, o uso novo é desconhecido.
                        fresh = (d.get("at") or 0) >= b["resets"]
                        v[key] = {"left": 100 if fresh else None, "resets": 0, "renewed": True}
                    else:
                        v[key] = {"left": max(0, 100 - b["pct"]), "resets": b.get("resets", 0)}
                out[eng] = v
            out["agy"] = dict(self.data["agy"])
        return out

    def maybe_probe(self, tablet_connected):
        if tablet_connected and time.time() - self.last_probe > PROBE_EVERY:
            threading.Thread(target=self.probe_claude, daemon=True).start()
            self.last_probe = time.time()


def _find_key(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = _find_key(v, key)
            if r:
                return r
    return None
