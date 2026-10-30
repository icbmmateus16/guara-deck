"""Estado do agente: sessões do Claude Code (via hooks), humor do Guará, aprovações e missões."""

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque

from pc import claude_source as pc_source

from quota import Quota
from pathlib import Path
from urllib.parse import urlparse

WORK_MOODS = ("reading", "typing", "running", "searching")
PRIORITY = {"waiting": 100, "error": 90, "running": 70, "typing": 70, "reading": 70,
            "searching": 70, "thinking": 60, "done": 50, "idle": 10}
DONE_HOLD = 15        # segundos comemorando depois de terminar
ERROR_HOLD = 8
STALE_WORK = 600      # sessão "trabalhando" sem eventos por 10 min volta a ociosa
SLEEP_AFTER = 300     # sem atividade do Claude nem do PC por 5 min, o Guará dorme
ENGINE_PATH = f"{Path.home()}/.local/bin:{Path.home()}/.nvm/versions/node/v24.16.0/bin:/usr/local/bin:/usr/bin:/bin"
CODEX_DIR = Path.home() / ".codex" / "sessions"
ENGINE_NAMES = {"claude": "Claude", "codex": "GPT (Codex)", "agy": "Gemini (Antigravity)", "gemini": "Gemini"}
# Mensagens de "acabou o limite" das CLIs (Claude: "usage limit reached… resets 3pm").
LIMIT_RE = re.compile(r"usage limit|rate.?limit|limit reached|limite|resets? (at|in|\d)|quota|exceeded your|429", re.I)


def _base(path):
    return os.path.basename(str(path or "").rstrip("/")) or str(path or "")


def _cut(text, n):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def tool_phrase(name, inp):
    """Traduz uma chamada de ferramenta para uma frase curta em português."""
    inp = inp or {}
    fp = inp.get("file_path") or inp.get("notebook_path") or inp.get("path")
    if name == "Read":
        return "reading", f"Lendo {_base(fp)}"
    if name in ("Edit", "MultiEdit"):
        return "typing", f"Editando {_base(fp)}"
    if name == "Write":
        return "typing", f"Escrevendo {_base(fp)}"
    if name == "NotebookEdit":
        return "typing", f"Editando notebook {_base(fp)}"
    if name == "Bash":
        what = inp.get("description") or inp.get("command")
        return "running", f"Rodando: {_cut(what, 70)}"
    if name == "Grep":
        return "searching", f"Procurando “{_cut(inp.get('pattern'), 40)}”"
    if name == "Glob":
        return "searching", f"Procurando arquivos {_cut(inp.get('pattern'), 40)}"
    if name == "WebSearch":
        return "searching", f"Pesquisando: {_cut(inp.get('query'), 60)}"
    if name == "WebFetch":
        return "searching", f"Lendo o site {urlparse(inp.get('url') or '').netloc}"
    if name in ("Task", "Agent"):
        return "running", f"Chamou um ajudante: {_cut(inp.get('description'), 50)}"
    if name == "TodoWrite":
        return "thinking", "Organizando a lista de tarefas"
    if name == "Skill":
        return "running", f"Usando a skill {inp.get('skill') or ''}"
    if name.startswith("mcp__"):
        parts = name.split("__")
        return "running", f"Usando {parts[1]}: {parts[-1]}" if len(parts) > 2 else f"Usando {name}"
    return "running", f"Usando {name}"


def permission_detail(name, inp):
    inp = inp or {}
    if name == "Bash":
        return inp.get("command") or ""
    if name in ("Edit", "MultiEdit", "Write", "Read", "NotebookEdit"):
        return inp.get("file_path") or inp.get("notebook_path") or ""
    if name == "WebFetch":
        return inp.get("url") or ""
    try:
        return json.dumps(inp, ensure_ascii=False)[:400]
    except Exception:
        return str(inp)[:400]


def last_assistant_text(transcript_path, limit=320):
    """Última fala do Claude na sessão (lê só o fim do arquivo .jsonl)."""
    try:
        p = Path(transcript_path)
        size = p.stat().st_size
        with p.open("rb") as f:
            f.seek(max(0, size - 400_000))
            lines = f.read().decode("utf-8", "ignore").splitlines()
    except Exception:
        return ""
    for line in reversed(lines):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") != "assistant":
            continue
        content = (d.get("message") or {}).get("content") or []
        texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
        text = " ".join(t for t in texts if t.strip())
        if text:
            text = re.sub(r"[*_`#>]+", "", text)
            return _cut(text, limit)
    return ""


class Agent:
    def __init__(self, hub, config):
        self.hub = hub
        self.config = config
        self.lock = threading.RLock()
        self.sessions = {}
        self.permissions = {}
        self.pc_idle_ms = 0
        self.mission = None
        self._mission_proc = None
        self._last_mood = None
        self.voice = None  # voice.Voice, ligado pelo servidor
        self.q = Quota(ENGINE_PATH)
        self._own_codex = deque(maxlen=50)   # conversas do Codex abertas pelo próprio Guará
        self._last_claude_used = 0
        self._quota_read_at = 0.0
        self.claude_blocked_until = 0.0
        self.activity = deque(maxlen=20)

    def log(self, kind, text):
        """Feed de atividade da tela: fim de tarefa, aprovações, missões, trocas de IA."""
        self.activity.appendleft({"t": int(time.time()), "kind": kind, "text": _cut(text, 110)})
        self.hub.broadcast("activity", list(self.activity))

    # ------------------------------------------------------------ hooks

    def on_hook(self, ev):
        name = ev.get("hook_event_name") or ""
        sid = ev.get("session_id") or "?"
        if (ev.get("cwd") or "").startswith("/tmp/guara-consulta"):
            return   # consulta de limite do próprio Guará: não é uma sessão sua
        now = time.time()
        with self.lock:
            s = self.sessions.get(sid)
            if s is None:
                if name == "SessionEnd":
                    return
                s = self.sessions[sid] = {
                    "id": sid, "cwd": ev.get("cwd") or "", "mood": "idle", "phrase": "", "agent": "claude",
                    "source": "" if self.mission and self.mission.get("session") == sid else pc_source(ev.get("cwd")),
                    "updated": now, "tools": {}, "done_tools": set(), "subagents": 0,
                    "mission": self.mission is not None and self.mission.get("session") == sid,
                    "summary": "",
                }
            s["updated"] = now
            if ev.get("cwd"):
                s["cwd"] = ev["cwd"]

            if name == "SessionStart":
                s["mood"], s["phrase"] = "idle", "Sessão aberta"
                if not s["mission"]:
                    self.log("start", f"Claude aberto em {_base(s['cwd'])}")
            elif name == "UserPromptSubmit":
                s["mood"], s["phrase"] = "thinking", "Pensando…"
                s["turn_at"] = now
                s["tools"].clear()
                s["subagents"] = 0
                prompt = _cut(ev.get("prompt"), 90)
                if prompt:
                    s["phrase"] = f"Pensando em: {prompt}"
            elif name == "PreToolUse":
                tid = ev.get("tool_use_id") or str(uuid.uuid4())
                if tid not in s["done_tools"]:  # hooks assíncronos podem chegar fora de ordem
                    tool = ev.get("tool_name") or ""
                    mood, phrase = tool_phrase(tool, ev.get("tool_input"))
                    s["tools"][tid] = tool
                    if tool in ("Task", "Agent"):
                        s["subagents"] += 1
                    s["mood"], s["phrase"] = mood, phrase
            elif name in ("PostToolUse", "PostToolUseFailure"):
                tid = ev.get("tool_use_id")
                tool = s["tools"].pop(tid, None) if tid else None
                if tid:
                    s["done_tools"].add(tid)
                    if len(s["done_tools"]) > 200:
                        s["done_tools"] = set(list(s["done_tools"])[-100:])
                if tool in ("Task", "Agent"):
                    s["subagents"] = max(0, s["subagents"] - 1)
                if name == "PostToolUseFailure":
                    s["mood"], s["phrase"] = "error", "Opa, uma ferramenta falhou"
                    s["error_at"] = now
                elif s["mood"] != "waiting" and not s["tools"]:
                    s["mood"] = "thinking"
            elif name == "Notification":
                ntype = ev.get("notification_type") or ""
                msg = ev.get("message") or ""
                if "permission" in ntype or "permission" in msg.lower():
                    if not any(p["session"] == sid for p in self.permissions.values()):
                        s["mood"], s["phrase"] = "waiting", "O Claude precisa de você no terminal"
                elif ntype == "idle_prompt":
                    s["mood"], s["phrase"] = "idle", "Esperando sua próxima mensagem"
            elif name == "Stop":
                s["tools"].clear()
                s["subagents"] = 0
                s["mood"], s["phrase"] = "done", "Pronto!"
                s["done_at"] = now
                summary = ev.get("last_assistant_message") or last_assistant_text(ev.get("transcript_path"))
                s["summary"] = _cut(summary, 320)
                self.hub.broadcast("attention", {"reason": "done"})
                took = now - s.get("turn_at", now)
                if not s["mission"]:
                    self.log("done", f"Claude terminou em {_base(s['cwd'])}" + (f" ({int(took // 60)} min)" if took >= 60 else ""))
                if self.voice and not s["mission"]:  # missões falam o resultado por conta própria
                    self.voice.on_stop(_base(s["cwd"]), summary, now - s.get("turn_at", now), self.pc_idle_ms)
            elif name == "StopFailure":
                self.log("error", f"Claude parou com erro em {_base(s['cwd'])}")
                s["tools"].clear()
                s["mood"], s["phrase"] = "error", _cut(ev.get("error") or "Algo deu errado", 80)
                s["error_at"] = now
            elif name == "SessionEnd":
                self.sessions.pop(sid, None)
        self.publish()

    # ------------------------------------------------------------ humor

    def _session_view(self, s, now):
        mood = s["mood"]
        if mood == "done" and now - s.get("done_at", 0) > DONE_HOLD:
            mood = "idle"
        if mood == "error" and now - s.get("error_at", 0) > ERROR_HOLD:
            mood = "idle"
        if mood in WORK_MOODS + ("thinking",) and now - s["updated"] > STALE_WORK:
            mood = "idle"
        if any(p["session"] == s["id"] for p in self.permissions.values()):
            mood = "waiting"
        return {
            "id": s["id"], "project": _base(s["cwd"]), "cwd": s["cwd"], "mood": mood, "phrase": s["phrase"],
            "agent": "guara" if s["mission"] else "claude", "source": s.get("source", ""),
            "summary": s["summary"], "ago": int(now - s["updated"]), "subagents": s["subagents"],
            "mission": s["mission"],
        }

    def snapshot(self):
        now = time.time()
        with self.lock:
            for sid in [k for k, v in self.sessions.items() if now - v["updated"] > 6 * 3600]:
                self.sessions.pop(sid)
            views = [self._session_view(s, now) for s in self.sessions.values()]
            mv = self._mission_as_session(now)
            if mv:
                views.append(mv)
            views.extend(self.codex_sessions(now))
            views.sort(key=lambda v: (-PRIORITY.get(v["mood"], 0), v["ago"]))
            top = views[0] if views else None
            mood = top["mood"] if top else "idle"
            last_activity = min((v["ago"] for v in views), default=10**9)
            if mood == "idle" and last_activity > SLEEP_AFTER and (self.pc_idle_ms or 0) > SLEEP_AFTER * 1000:
                mood = "sleeping"
            perms = [self._perm_view(p, now) for p in self.permissions.values()]
            phrase = top["phrase"] if top and mood != "sleeping" else ""
            project = top["project"] if top else ""
            if perms:  # pedido pendente vale mais que qualquer sessão (pode vir de uma sessão nova)
                mood = "waiting"
                phrase = "Preciso da sua aprovação!" if len(perms) == 1 else f"{len(perms)} pedidos esperando você"
                project = perms[0]["project"]
            return {
                "mood": mood,
                "phrase": phrase,
                "summary": top["summary"] if top and mood == "done" else "",
                "project": project,
                "subagents": sum(v["subagents"] for v in views),
                "sessions": views,
                "permissions": perms,
                "pc_idle_ms": self.pc_idle_ms,
            }

    def _mission_as_session(self, now):
        m = self.mission
        if not m or not m.get("engine") or m["engine"] == "claude":
            return None
        running = m["status"] == "running"
        if not running and now - m.get("ended", 0) > DONE_HOLD:
            return None
        name = ENGINE_NAMES.get(m["engine"], m["engine"])
        last = m["steps"][-1] if m["steps"] else ""
        if running:
            mood = "running" if last.startswith("Rodando") else "thinking"
            phrase = last or f"Pensando com {name}…"
        else:
            mood = "done" if m["status"] == "done" else "error"
            phrase = _cut(m["text"], 120)
        return {"id": "mission-" + m["id"], "project": m["title"], "agent": "guara", "source": name, "cwd": "", "mood": mood,
                "phrase": phrase, "summary": "" if running else _cut(m["text"], 320), "ago": 0,
                "subagents": 0, "mission": True}

    def publish(self):
        snap = self.snapshot()
        self.hub.broadcast("agent", snap)
        if snap["mood"] != self._last_mood:
            if snap["mood"] in ("waiting", "done", "error"):
                self.hub.broadcast("attention", {"reason": snap["mood"]})
            self._last_mood = snap["mood"]

    def tick(self):
        """Chamado a cada poucos segundos: expira estados temporários e relê o uso das IAs."""
        self.publish()
        if time.time() - self._quota_read_at > 60:
            self._quota_read_at = time.time()
            self.refresh_quota()
            self.q.maybe_probe(self.hub.has_clients())

    # ------------------------------------------------------------ aprovações

    def _perm_view(self, p, now):
        s = self.sessions.get(p["session"]) or {}
        return {"id": p["id"], "tool": p["tool"], "detail": p["detail"], "project": p["project"],
                "session": p["session"], "source": s.get("source", ""), "mission": bool(s.get("mission")),
                "age": int(now - p["created"]), "timeout": p["timeout"]}

    # ------------------------------------------------------------ Codex usado por você (fora do Guará)

    def codex_sessions(self, now):
        """Sessões do Codex ativas nos últimos minutos, lidas dos arquivos que ele mesmo grava."""
        own = {m_id for m_id in self._own_codex}
        out = []
        for f in sorted(CODEX_DIR.glob("*/*/*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:4]:
            age = now - f.stat().st_mtime
            if age > 600:
                break
            tid = f.stem[-36:]
            if tid in own:
                continue
            if "guara-consulta" in f.read_text(errors="ignore")[:4000]:
                continue   # consulta de limite do próprio Guará
            try:
                with f.open("rb") as fh:
                    fh.seek(max(0, f.stat().st_size - 60_000))
                    lines = fh.read().decode("utf-8", "ignore").splitlines()
            except Exception:
                continue
            cwd, mood, phrase = "", "idle", "Codex aberto"
            for line in lines:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                p = d.get("payload") or {}
                kind = p.get("type")
                if d.get("type") in ("session_meta", "turn_context") and p.get("cwd"):
                    cwd = p["cwd"]
                if kind == "reasoning":
                    mood, phrase = "thinking", "Pensando…"
                elif kind in ("function_call", "custom_tool_call", "local_shell_call"):
                    mood, phrase = "running", "Usando " + (p.get("name") or "ferramenta")
                elif kind == "message" and p.get("role") == "assistant":
                    mood, phrase = "typing", "Respondendo"
                elif kind in ("task_complete", "turn_complete"):
                    mood, phrase = "done", "Pronto"
            if age > 30 and mood not in ("done",):
                mood = "idle" if age > 120 else mood
            if mood == "done" and age > DONE_HOLD:
                mood, phrase = "idle", "Esperando você"
            out.append({"id": "codex-" + tid, "project": _base(cwd) or "Codex", "cwd": cwd, "mood": mood,
                        "phrase": phrase, "summary": "", "ago": int(age), "subagents": 0, "mission": False,
                        "agent": "codex", "source": "terminal"})
        return out

    def permission_request(self, ev, sock):
        """Bloqueia até o tablet decidir. Retorna o corpo JSON para o Claude Code."""
        if not self.hub.has_clients():
            return {}  # tablet desligado: a pergunta segue normal no terminal
        timeout = int(self.config.get("permission_timeout", 120))
        pid = uuid.uuid4().hex[:10]
        p = {
            "id": pid, "session": ev.get("session_id") or "?",
            "tool": ev.get("tool_name") or "?",
            "detail": _cut(permission_detail(ev.get("tool_name"), ev.get("tool_input")), 600),
            "project": _base(ev.get("cwd")), "created": time.time(), "timeout": timeout,
            "event": threading.Event(), "decision": None,
        }
        with self.lock:
            self.permissions[pid] = p
        self.hub.broadcast("attention", {"reason": "permission"})
        if self.voice:
            self.voice.on_permission(p["tool"], p["project"], self.pc_idle_ms)
        self.publish()
        try:
            deadline = time.time() + timeout
            while time.time() < deadline:
                if p["event"].wait(0.5):
                    break
                if _peer_closed(sock):  # respondeu no terminal, o Claude desistiu do hook
                    break
        finally:
            with self.lock:
                self.permissions.pop(pid, None)
            self.publish()
        decision = p["decision"]
        what = "comando" if p["tool"] == "Bash" else p["tool"]
        if decision in ("allow", "deny"):
            self.log(decision, f"Você {'aprovou' if decision == 'allow' else 'negou'} {what} em {p['project']}: {p['detail']}")
        if decision == "allow":
            return {"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                                           "decision": {"behavior": "allow"}}}
        if decision == "deny":
            return {"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                                           "decision": {"behavior": "deny",
                                                        "message": "Negado pelo tablet (Guará)."}}}
        return {}

    def permission_decide(self, pid, behavior):
        with self.lock:
            p = self.permissions.get(pid)
        if not p or behavior not in ("allow", "deny"):
            return False
        p["decision"] = behavior
        p["event"].set()
        return True

    # ------------------------------------------------------------ missões

    def mission_start(self, prompt, title="Missão", tools=None, cwd=None, voice=False, resume=None,
                      system_prompt=None, model=None, images=None):
        with self.lock:
            if self.mission and self.mission["status"] == "running":
                return False, "Já tem uma missão rodando"
            m = self.mission = {
                "id": uuid.uuid4().hex[:8], "title": title, "prompt": prompt, "status": "running",
                "steps": [], "text": "", "cost": None, "started": time.time(), "session": None, "voice": voice,
                "engine": None,
            }
        spec = {
            "prompt": prompt, "resume": resume or {}, "images": images or [],
            "tools": tools or self.config.get("mission_tools") or [],
            "system": system_prompt or self.config.get("mission_system_prompt", ""),
            "model": model or self.config.get("mission_model"),
            "cwd": os.path.expanduser(cwd or self.config.get("mission_cwd") or "~"),
        }
        threading.Thread(target=self._mission_run, args=(m, spec), daemon=True).start()
        self._mission_publish()
        return True, m["id"]

    def mission_cancel(self):
        proc = self._mission_proc
        if proc and proc.poll() is None:
            if self.mission:
                self.mission["status"] = "cancelled"
            proc.terminate()
            self._mission_publish()
            return True
        return False

    def mission_view(self):
        m = self.mission
        if not m:
            return None
        view = {k: m[k] for k in ("id", "title", "status", "steps", "text", "cost", "engine")}
        view["elapsed"] = int(time.time() - m["started"])
        return view

    def _mission_publish(self):
        view = self.mission_view()
        if view:
            self.hub.broadcast("mission", view)
            self.publish()

    # ------------------------------------------------------------ revezamento de IAs

    def set_quota(self, status):
        """Barra de status do Claude Code (terminal): uso das janelas de 5 h e semanal."""
        if self.q.from_statusline(status.get("rate_limits") or {}):
            self._after_claude_quota()

    def _after_claude_quota(self):
        five = (self.q.view().get("claude") or {}).get("five_hour") or {}
        used = 100 - five.get("left", 100)
        if self.voice and self._last_claude_used < 90 <= used < 100:
            self.voice.say_async("Atenção: o Claude já usou noventa por cento do limite de cinco horas.")
        self._last_claude_used = used
        self.publish_quota()

    def claude_limited(self):
        return time.time() < self.claude_blocked_until or bool(self.q.claude_exhausted())

    def quota_view(self):
        until = max(self.claude_blocked_until, self.q.claude_exhausted())
        limited = self.claude_limited()
        engines = self.engines()
        return {"limited": limited, "until": int(until) if limited else 0,
                "engine": engines[0] if engines else "claude",
                "order": self.config.get("engines") or ["codex", "agy", "claude"],
                "meters": self.q.view()}

    def publish_quota(self):
        self.hub.broadcast("quota", self.quota_view(), only_if_changed=True)

    def refresh_quota(self, probe=False):
        """Relê os arquivos de uso (barato); com probe=True também consulta o Claude."""
        self.q.read_claude_cache()
        self.q.read_codex()
        if probe:
            self.q.probe_claude()
            self.q.probe_codex()
        self._after_claude_quota()

    def engines(self):
        order = self.config.get("engines") or ["codex", "agy", "claude"]
        return [e for e in order if shutil.which(e, path=ENGINE_PATH) and not (e == "claude" and self.claude_limited())]

    def _mission_run(self, m, spec):
        status = "error"
        engines = self.engines() or ["claude"]
        for i, engine in enumerate(engines):
            m["engine"] = engine
            self._mission_publish()
            try:
                status = getattr(self, "_run_" + engine)(m, spec)
            except Exception as e:
                status, m["text"] = "error", f"{ENGINE_NAMES[engine]} falhou: {e}"
            if status != "limit" or m["status"] == "cancelled":
                break
            if engine == "claude":
                b = self.q.claude_exhausted()
                self.claude_blocked_until = b if b > time.time() else time.time() + 1800
                self.publish_quota()
                if self.voice:
                    self.voice.say_async("Seu limite do Claude acabou. Enquanto isso, eu uso outra inteligência.")
            nxt = ENGINE_NAMES[engines[i + 1]] if i + 1 < len(engines) else None
            self.log("switch", f"{ENGINE_NAMES[engine]} sem limite" + (f" → {nxt}" if nxt else ""))
            m["steps"].append(f"{ENGINE_NAMES[engine]} sem limite agora" + (f" → usando {nxt}" if nxt else ""))
        m["ended"] = time.time()
        if m["status"] != "cancelled":
            ok = status == "ok"
            self.log("mission" if ok else "error",
                     f"{m['title']} {'pronta' if ok else 'falhou'} · {ENGINE_NAMES.get(m['engine'], m['engine'])}")
        if m["status"] == "running":
            m["status"] = "done" if status == "ok" else "error"
            if status == "limit":
                m["text"] = "Todas as IAs estão sem limite agora. Tente mais tarde."
        self._mission_publish()
        self.hub.broadcast("attention", {"reason": "mission"})
        if self.voice and m["status"] in ("done", "error"):
            self.voice.on_mission_done(m)

    def _popen(self, args, cwd):
        env = dict(os.environ, PATH=ENGINE_PATH + ":" + os.environ.get("PATH", ""))
        proc = self._mission_proc = subprocess.Popen(
            args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, start_new_session=True, env=env,
        )
        return proc

    def _run_claude(self, m, spec):
        args = [shutil.which("claude", path=ENGINE_PATH) or "claude", "-p", spec["prompt"],
                "--output-format", "stream-json", "--verbose", "--append-system-prompt", spec["system"]]
        if spec["model"]:
            args += ["--model", spec["model"]]
        if spec["resume"].get("engine") == "claude":
            args += ["--resume", spec["resume"]["id"]]  # conversa por voz continua de onde parou
        if spec["tools"]:
            args += ["--allowedTools", ",".join(spec["tools"])]
        proc = self._popen(args, spec["cwd"])
        result, raw = None, []
        for line in proc.stdout:
            try:
                d = json.loads(line)
            except Exception:
                raw.append(line)
                continue
            t = d.get("type")
            if t == "system" and d.get("subtype") == "init":
                m["session"] = d.get("session_id")
                with self.lock:
                    if m["session"] in self.sessions:
                        self.sessions[m["session"]]["mission"] = True
            elif t == "assistant":
                for c in (d.get("message") or {}).get("content") or []:
                    if c.get("type") == "tool_use":
                        m["steps"].append(tool_phrase(c.get("name") or "", c.get("input"))[1])
                        m["steps"] = m["steps"][-8:]
                    elif c.get("type") == "text" and c.get("text", "").strip():
                        m["text"] = c["text"].strip()
                self._mission_publish()
            elif t == "rate_limit_event":
                self.q.from_claude_event(d.get("rate_limit_info") or {})
                self._after_claude_quota()
            elif t == "result":
                result = d
        proc.wait()
        text = ((result or {}).get("result") or m["text"] or "").strip()
        failed = proc.returncode != 0 or (result or {}).get("is_error")
        if failed and LIMIT_RE.search(text + " " + "".join(raw[-20:])):
            return "limit"
        m["text"] = text or "".join(raw[-5:]).strip()
        m["cost"] = (result or {}).get("total_cost_usd")
        return "error" if failed else "ok"

    def _run_codex(self, m, spec):
        codex = shutil.which("codex", path=ENGINE_PATH) or "codex"
        resume = spec["resume"].get("id") if spec["resume"].get("engine") == "codex" else None
        args = [codex, "exec"]
        if resume:
            args += ["resume"]
        for img in spec["images"]:            # ex.: captura de tela da missão "Olha minha tela"
            args += ["-i", img]
        args += ["--skip-git-repo-check", "-c", 'sandbox_mode="read-only"']
        if not resume:
            args += ["-C", spec["cwd"]]
        if self.config.get("codex_model"):
            args += ["-m", self.config["codex_model"]]
        args += ["--json"]
        prompt = spec["prompt"] if resume else spec["system"] + "\n\n" + spec["prompt"]
        args += [resume, prompt] if resume else [prompt]
        proc = self._popen(args, spec["cwd"])
        raw, text = [], ""
        for line in proc.stdout:
            raw.append(line)
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("type") == "thread.started":
                m["session"] = ev.get("thread_id")
                self._own_codex.append(m["session"])
            item = ev.get("item") or {}
            if item.get("type") == "command_execution" and item.get("command"):
                m["steps"].append("Rodando: " + _cut(item["command"], 70))
                m["steps"] = m["steps"][-8:]
                self._mission_publish()
            elif item.get("type") == "agent_message" and item.get("text"):
                text = item["text"].strip()
        proc.wait()
        self.q.read_codex()   # o Codex grava o limite atualizado no arquivo da sessão
        self.publish_quota()
        if proc.returncode != 0 and LIMIT_RE.search("".join(raw[-30:])):
            return "limit"
        m["text"] = text or _cut("".join(raw[-3:]), 300)
        return "ok" if proc.returncode == 0 and text else "error"

    def _run_agy(self, m, spec):
        """Antigravity CLI (Google): substitui o Gemini CLI, que não aceita mais contas pessoais."""
        args = [shutil.which("agy", path=ENGINE_PATH) or "agy", "-p", spec["system"] + "\n\n" + spec["prompt"],
                "--mode", "plan", "--output-format", "json", "--print-timeout", "300s"]
        if self.config.get("agy_model"):
            args += ["--model", self.config["agy_model"]]
        if spec["resume"].get("engine") == "agy":
            args += ["--conversation", spec["resume"]["id"]]
        proc = self._popen(args, spec["cwd"])
        raw = proc.stdout.read()
        proc.wait()
        try:
            d = json.loads(raw[raw.index("{"):])
        except Exception:
            d = {}
        m["session"] = d.get("conversation_id") or m["session"]
        self.q.note_use("agy")
        self.publish_quota()
        text = (d.get("response") or "").strip()
        if d.get("status") != "SUCCESS" and LIMIT_RE.search(raw[-3000:]):
            return "limit"
        m["text"] = text or _cut(raw[-300:], 300)
        return "ok" if d.get("status") == "SUCCESS" and text else "error"

    def _run_gemini(self, m, spec):
        """Gemini CLI: o Google desativou o plano gratuito pessoal nele; só serve com chave de API."""
        args = [shutil.which("gemini", path=ENGINE_PATH) or "gemini", "-p", spec["system"] + "\n\n" + spec["prompt"],
                "--approval-mode", "plan", "-o", "json"]
        proc = self._popen(args, spec["cwd"])
        raw = proc.stdout.read()
        proc.wait()
        try:
            text = (json.loads(raw[raw.index("{"):]).get("response") or "").strip()
        except Exception:
            text = ""
        if proc.returncode != 0 and LIMIT_RE.search(raw[-3000:]):
            return "limit"
        m["text"] = text or _cut(raw[-300:], 300)
        return "ok" if proc.returncode == 0 and text else "error"


def _peer_closed(sock):
    import select
    import socket

    try:
        r, _, _ = select.select([sock], [], [], 0)
        if not r:
            return False
        return sock.recv(1, socket.MSG_PEEK) == b""
    except Exception:
        return True
