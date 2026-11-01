#!/usr/bin/env python3
"""Capi — servidor do painel do tablet.

Serve a interface (web/), manda o estado em tempo real por SSE, executa as ações
no PC e recebe os hooks do Claude Code. O tablet só desenha e envia toques.
"""

import json
import mimetypes
import os
import queue
import re
import secrets
import shlex
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pc  # noqa: E402
from agent import Agent  # noqa: E402
from voice import Voice  # noqa: E402
from discovery import announce  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
CONFIG_PATH = ROOT / "server" / "config.json"
SCREEN_SHOT = Path("/tmp/capi_tela.png")

DEFAULT_CONFIG = {
    "port": 47801,
    "discovery_port": 47800,
    "permission_timeout": 120,
    "mission_model": "sonnet",
    "mission_cwd": "~/Área de trabalho/PROJETOS",
    "mission_system_prompt": (
        "Você é o Guará, um assistente pessoal que roda no PC Ubuntu do usuário e responde "
        "numa telinha de tablet. Responda sempre em português do Brasil, em no máximo 8 linhas "
        "curtas de texto simples (sem tabelas nem markdown pesado). Não altere, mova nem apague "
        "arquivos a menos que o pedido diga isso explicitamente."
    ),
    "assistant_name": "Guará",
    "engines": ["codex", "agy", "claude"],  # GPT primeiro; o limite do Claude fica para programar
    "voice_enabled": True,
    "voice_model": "sonnet",
    "voice_session_minutes": 30,
    "whatsapp_aliases": {},
    "whatsapp_vip": ["Amor"],
    # Voz em modo execução: o Guará age no PC (abre apps, edita arquivos, roda comandos) com os limites do prompt
    "voice_exec": True,
    "voice_exec_tools": ["Read", "Glob", "Grep", "WebSearch", "WebFetch", "Edit", "Write", "Bash"],
    "mission_tools": [
        "Read", "Glob", "Grep", "WebSearch", "WebFetch",
        "Bash(ls:*)", "Bash(df:*)", "Bash(free:*)", "Bash(uptime:*)",
        "Bash(git log:*)", "Bash(git status:*)",
    ],
    "missions": [
        {"id": "dia", "title": "Resumo do dia", "icon": "sun", "color": "#ffb35c", "desc": "O que você fez hoje",
         "prompt": "Veja o que mudou hoje nos repositórios git dentro desta pasta (rode git log "
                   "--since=midnight --oneline em cada subpasta que for um repositório) e me dê um "
                   "resumo curto do que eu fiz hoje, por projeto.",
         "tools": ["Bash(ls:*)", "Bash(find:*)", "Bash(git -C:*)", "Bash(git log:*)", "Glob", "Read"]},
        {"id": "tela", "title": "Olha minha tela", "icon": "eye", "screenshot": True, "color": "#a78bfa",
         "desc": "Explica e dá uma dica",
         "prompt": "Leia a imagem {screenshot} (uma captura da minha tela agora). Diga em poucas "
                   "linhas o que estou fazendo e me dê uma dica útil sobre isso.",
         "tools": ["Read"]},
        {"id": "pc", "title": "Saúde do PC", "icon": "heart", "color": "#ff6b8b", "desc": "Check-up rápido",
         "prompt": "Faça um check-up rápido deste PC Ubuntu: disco, memória, processos que mais "
                   "consomem CPU e RAM, temperaturas e serviços com falha. Responda com um "
                   "diagnóstico curto e até 2 sugestões práticas.",
         "tools": ["Bash(df:*)", "Bash(free:*)", "Bash(uptime:*)", "Bash(ps:*)", "Bash(sensors:*)",
                   "Bash(nvidia-smi:*)", "Bash(systemctl --failed:*)", "Bash(systemctl --user --failed:*)"]},
        {"id": "ia", "title": "Novidades de IA", "icon": "spark", "color": "#5eead4", "desc": "3 notícias de hoje",
         "prompt": "Pesquise as 3 notícias mais importantes sobre inteligência artificial de hoje "
                   "e resuma cada uma em uma linha.",
         "tools": ["WebSearch", "WebFetch"]},
        {"id": "downloads", "title": "Arrumar Downloads", "icon": "box", "color": "#7cc4ff",
         "desc": "Sugestões, sem apagar nada",
         "prompt": "Analise minha pasta ~/Downloads: o que ocupa mais espaço, arquivos antigos e "
                   "duplicados. Sugira como organizar. Não mova nem apague nada, só sugira.",
         "tools": ["Bash(ls:*)", "Bash(du:*)", "Bash(find:*)", "Glob"]},
    ],
    "shortcuts": [
        {"id": "terminal", "color": "#5eead4", "label": "Terminal", "icon": "term", "kind": "app", "target": "org.gnome.Ptyxis"},
        {"id": "code", "color": "#7cc4ff", "label": "VS Code", "icon": "code", "kind": "app", "target": "code_code"},
        {"id": "firefox", "color": "#ffd166", "label": "Firefox", "icon": "web", "kind": "app", "target": "firefox_firefox"},
        {"id": "files", "color": "#ffb35c", "label": "Arquivos", "icon": "folder", "kind": "app", "target": "org.gnome.Nautilus"},
        {"id": "projetos", "color": "#ff9a3c", "label": "Projetos", "icon": "folder", "kind": "open", "target": "~/Área de trabalho/PROJETOS"},
        {"id": "discord", "color": "#a78bfa", "label": "Discord", "icon": "chat", "kind": "app", "target": "discord"},
        {"id": "obs", "color": "#ff6b6b", "label": "OBS", "icon": "rec", "kind": "app", "target": "com.obsproject.Studio"},
        {"id": "obsidian", "color": "#c4a5ff", "label": "Obsidian", "icon": "note", "kind": "app", "target": "obsidian"},
        {"id": "print", "color": "#7cc4ff", "label": "Print", "icon": "camera", "kind": "screenshot"},
        {"id": "settings", "color": "#9aa0b5", "label": "Ajustes", "icon": "gear", "kind": "app", "target": "org.gnome.Settings"},
        {"id": "lock", "color": "#ff6b8b", "label": "Bloquear", "icon": "lock", "kind": "lock"},
    ],
}


def load_config():
    """config.json guarda só o token e o que você quiser sobrescrever (ex.: "shortcuts")."""
    user = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    if not user.get("token"):
        user["token"] = secrets.token_urlsafe(12)
        CONFIG_PATH.write_text(json.dumps(user, indent=2, ensure_ascii=False))
        os.chmod(CONFIG_PATH, 0o600)
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(user)
    return cfg


def save_user_config(key, value):
    """Guarda uma escolha feita no tablet em config.json (só as chaves que você mudou)."""
    user = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    user[key] = value
    CONFIG_PATH.write_text(json.dumps(user, indent=2, ensure_ascii=False))
    CFG[key] = value


class Hub:
    """Distribui eventos para os tablets conectados (SSE)."""

    def __init__(self):
        self.clients = []
        self.lock = threading.Lock()
        self.last_seen = 0.0
        self._last = {}

    def add(self):
        q = queue.Queue(maxsize=300)
        with self.lock:
            self.clients.append(q)
        return q

    def remove(self, q):
        with self.lock:
            if q in self.clients:
                self.clients.remove(q)

    def seen(self):
        self.last_seen = time.time()

    def has_clients(self):
        return bool(self.clients) and time.time() - self.last_seen < 45

    def broadcast(self, event, data, only_if_changed=False):
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if only_if_changed:
            if self._last.get(event) == payload:
                return
            self._last[event] = payload
        with self.lock:
            for q in list(self.clients):
                try:
                    q.put_nowait((event, payload))
                except queue.Full:
                    self.clients.remove(q)


CFG = load_config()
HUB = Hub()
AGENT = Agent(HUB, CFG)
VOICE = AGENT.voice = Voice(HUB, AGENT, CFG)
STATS = pc.Stats()
STATE = {"stats": {}, "media": {}, "volume": {}, "toggles": {}, "pcctl": {}}


def shortcuts_view():
    return [{"id": s["id"], "label": s["label"], "icon": s.get("icon", ""), "color": s.get("color", ""),
             "img": pc.shortcut_img(s)}
            for s in CFG["shortcuts"] if pc.shortcut_available(s)]


def missions_view():
    return [{"id": m["id"], "title": m["title"], "icon": m.get("icon", ""), "desc": m.get("desc", ""),
             "color": m.get("color", "")} for m in CFG["missions"]]


def ui_ver():
    parts = []
    for name in ("index.html", "style.css", "app.js", "guara.js"):
        try:
            parts.append(str(int((WEB / name).stat().st_mtime)))
        except OSError:
            pass
    return "-".join(parts)


def full_state():
    return {
        "agent": AGENT.snapshot(),
        "stats": STATE["stats"],
        "media": STATE["media"],
        "volume": STATE["volume"],
        "shortcuts": shortcuts_view(),
        "missions": missions_view(),
        "mission": AGENT.mission_view(),
        "voice": {"enabled": VOICE.enabled, **VOICE.voices()},
        "wa_pending": VOICE.wa_pending,
        "activity": list(AGENT.activity),
        "toggles": STATE["toggles"],
        "pcctl": STATE["pcctl"],
        "quota": AGENT.quota_view(),
        "name": CFG.get("assistant_name", "Guará"),
        "guara_style": CFG.get("guara_style", "real"),
        "ui_ver": ui_ver(),
        "server_time": int(time.time()),
    }


def do_action(aid):
    if aid == "media.playpause":
        STATE["media"] = pc.media_cmd("PlayPause")
        return STATE["media"]
    if aid == "media.next":
        STATE["media"] = pc.media_cmd("Next")
        return STATE["media"]
    if aid == "media.prev":
        STATE["media"] = pc.media_cmd("Previous")
        return STATE["media"]
    if aid == "media.stop":
        STATE["media"] = pc.media_cmd("Stop")
        return STATE["media"]
    if aid == "vol.up":
        STATE["volume"] = pc.volume_step(5)
        return STATE["volume"]
    if aid == "vol.down":
        STATE["volume"] = pc.volume_step(-5)
        return STATE["volume"]
    if aid == "vol.mute":
        STATE["volume"] = pc.volume_mute()
        return STATE["volume"]
    for s in CFG["shortcuts"]:
        if s["id"] == aid:
            ok, err = pc.run_shortcut(s)
            if not ok:
                raise ValueError(err)
            return {"ok": True}
    raise ValueError(f"ação desconhecida: {aid}")


def handoff(session_id):
    """Abre o Codex (GPT) na pasta da sessão do Claude, com o resumo do que ele fazia."""
    s = next((v for v in AGENT.snapshot()["sessions"] if v["id"] == session_id), None)
    if not s or not os.path.isdir(s["cwd"]):
        return {"ok": False, "error": "sessão não encontrada"}
    prompt = ("Continue o trabalho que o Claude Code estava fazendo nesta pasta. "
              f"Último resumo dele: {s['summary'] or s['phrase']}. "
              "Antes de mudar algo, rode git status e git diff para ver o que já foi feito.")
    pc._terminal(s["cwd"], "codex " + shlex.quote(prompt))
    return {"ok": True}


def start_mission(body):
    preset = next((m for m in CFG["missions"] if m["id"] == body.get("preset")), None)
    if preset:
        prompt = preset["prompt"]
        if preset.get("screenshot"):
            SCREEN_SHOT.unlink(missing_ok=True)
            os.system(f"gnome-screenshot -f {SCREEN_SHOT} >/dev/null 2>&1")
            if not SCREEN_SHOT.exists():
                return False, "Não consegui capturar a tela"
            prompt = prompt.replace("{screenshot}", str(SCREEN_SHOT))
            return AGENT.mission_start(prompt, preset["title"], preset.get("tools"), images=[str(SCREEN_SHOT)])
        return AGENT.mission_start(prompt, preset["title"], preset.get("tools"))
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return False, "Pedido vazio"
    return AGENT.mission_start(prompt[:2000], "Pedido")


def guara_interact(kind):
    """Interações rápidas do modo Guará em tela cheia: carinho falado, status ao vivo ou olhar a tela."""
    if kind == "poke":
        VOICE.say_poke()
        return {"ok": True}
    if kind == "screen":
        SCREEN_SHOT.unlink(missing_ok=True)
        os.system(f"gnome-screenshot -f {SCREEN_SHOT} >/dev/null 2>&1")
        if not SCREEN_SHOT.exists():
            VOICE.say_async("Tentei olhar sua tela agora, mas não consegui capturar a imagem.", "reply")
            return {"ok": False, "info": "Não consegui capturar a tela"}
        from voice import VOICE_PROMPT
        prompt = (
            f"Leia a imagem {SCREEN_SHOT} (captura da tela do PC agora). "
            "Me diga em tom de conversa rápida o que eu estou fazendo e me dê uma dica esperta sobre isso."
        )
        ok, info = AGENT.mission_start(
            prompt, "Olhando a tela", tools=["Read"], voice=True,
            system_prompt=VOICE_PROMPT, images=[str(SCREEN_SHOT)],
        )
        if not ok:
            VOICE.say_async(f"Calma aí, {info.lower()}.", "reply")
        return {"ok": ok, "info": info}
    if kind == "status":
        st = STATE["stats"] or {}
        snap = AGENT.snapshot()
        qv = AGENT.quota_view()
        parts = []
        sessions = [s for s in snap.get("sessions", []) if s.get("mood") not in ("idle", "sleeping")]
        if sessions:
            top = sessions[0]
            who = "O Codex" if top["agent"] == "codex" else ("Eu mesmo tô" if top["agent"] == "guara" else "O Claude")
            if top["agent"] == "guara":
                parts.append(f"Olha só, {who} trabalhando em {top['project']} agora!")
            else:
                parts.append(f"Tô de olho aqui: {who.lower()} tá ativo lá em {top['project']}, {top['phrase'].lower()}.")
        else:
            parts.append("Por aqui tá tudo calmo, nenhum agente rodando tarefa agora.")

        cpu = st.get("cpu")
        mem = st.get("mem")
        gpu = (st.get("gpu") or {}).get("temp")
        if cpu is not None and mem is not None:
            clima = f" com a GPU em {gpu} graus" if gpu is not None else ""
            parts.append(f"O PC tá em {cpu}% de CPU e {mem}% de memória{clima}.")

        c5 = ((qv.get("meters") or {}).get("claude") or {}).get("five_hour") or {}
        if c5.get("left") is not None:
            parts.append(f"E ainda sobram {c5['left']}% do limite de 5 horas do Claude!")
        msg = " ".join(parts)
        VOICE.say_async(msg, "reply")
        return {"ok": True, "text": msg}
    raise ValueError("interação desconhecida")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "Capi/1"

    def log_message(self, fmt, *args):
        if "/events" not in self.path and "/api/ping" not in self.path:
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    # ------------------------------------------------ util

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body, ensure_ascii=False).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            if "Cache-Control" not in (extra or {}):
                self.send_header("Cache-Control", "no-cache")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _send_audio(self, data):
        """Responde a pedidos Range do Stagefright (Android 4.4) sem reenviar o WAV inteiro várias vezes."""
        total = len(data)
        rng = self.headers.get("Range") or ""
        if rng.startswith("bytes="):
            try:
                spec = rng[6:].split(",", 1)[0].strip()
                s_str, e_str = spec.split("-", 1)
                start = int(s_str) if s_str else 0
                end = int(e_str) if e_str else total - 1
                end = min(end, total - 1)
                if 0 <= start <= end:
                    chunk = data[start : end + 1]
                    return self._send(206, chunk, "audio/wav", {
                        "Accept-Ranges": "bytes",
                        "Content-Range": f"bytes {start}-{end}/{total}",
                    })
            except Exception:
                pass
        return self._send(200, data, "audio/wav", {"Accept-Ranges": "bytes"})

    def _query(self):
        return parse_qs(urlparse(self.path).query)

    def _authorized(self):
        t = (self._query().get("t") or [""])[0]
        ok = secrets.compare_digest(t, CFG["token"])
        if ok:
            HUB.seen()
        return ok

    def _local(self):
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw or b"{}")
        except Exception:
            return {}

    # ------------------------------------------------ GET

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/events":
            return self._events() if self._authorized() else self._send(403, {"error": "token"})
        if path.startswith("/api/"):
            if not self._authorized():
                return self._send(403, {"error": "token"})
            if path == "/api/state":
                return self._send(200, full_state())
            if path == "/api/apps":
                return self._send(200, {"apps": pc.apps_catalog(CFG["shortcuts"])})
            if path.startswith("/api/appicon/"):
                key = path.rsplit("/", 1)[-1][:-4] if path.endswith(".png") else ""
                data = pc.app_icon(key) if key and re.fullmatch(r"[\w.-]+", key) else None
                return self._send(200, data, "image/png") if data else self._send(404, {"error": "sem ícone"})
            if path == "/api/dev":
                return self._send(200, {"projects": pc.projects(), "docker": pc.docker_containers(),
                                        "ports": pc.listening_ports(), "ollama": pc.ollama_loaded()})
            if path == "/api/ping":
                return self._send(200, {"ok": True, "t": int(time.time())})
            if path.startswith("/api/say/"):
                data = VOICE.clips.get(path.rsplit("/", 1)[-1].replace(".wav", ""))
                if not data:
                    return self._send(404, {"error": "áudio expirou"})
                return self._send_audio(data)
            if path == "/api/art":
                data = pc.media_art(STATE["media"].get("art"))
                if not data:
                    return self._send(404, {"error": "sem capa"})
                return self._send(200, data, "image/jpeg", {"Cache-Control": "max-age=30"})
            if path == "/api/yt/search":
                q = (self._query().get("q") or [""])[0]
                return self._send(200, {"items": pc.yt_search(q)})
            if path.startswith("/api/yt/thumb/"):
                vid = path.rsplit("/", 1)[-1].replace(".jpg", "")
                data = pc.yt_thumb(vid)
                if not data:
                    return self._send(404, {"error": "sem miniatura"})
                return self._send(200, data, "image/jpeg", {"Cache-Control": "max-age=86400"})
            if path.startswith("/api/yt/pcm/"):
                vid = path.rsplit("/", 1)[-1].replace(".raw", "")
                return self._stream_yt_pcm(vid)
            return self._send(404, {"error": "não existe"})
        return self._static(path)

    def _stream_yt_pcm(self, vid):
        stream_url = pc.yt_stream_url(vid)
        if not stream_url:
            return self._send(404, {"error": "não consegui abrir este vídeo"})
        proc = subprocess.Popen(
            [
                "ffmpeg", "-nostdin", "-loglevel", "error",
                "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "4",
                "-i", stream_url, "-vn", "-f", "s16le", "-acodec", "pcm_s16le", "-ar", "24000", "-ac", "1", "pipe:1",
            ],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=1.5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def _static(self, path):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        f = (WEB / rel).resolve()
        if WEB.resolve() not in f.parents or not f.is_file():
            return self._send(404, {"error": "não existe"})
        ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        if rel.startswith("fonts/") or rel.endswith((".jpg", ".png")):
            cache = {"Cache-Control": "max-age=86400"}
        else:
            cache = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache"}
        return self._send(200, f.read_bytes(), ctype, cache)

    def _events(self):
        q = HUB.add()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            # O padding faz WebViews antigos liberarem o stream na hora.
            self.wfile.write(b"retry: 2000\n:" + b" " * 2048 + b"\n\n")
            hello = json.dumps(full_state(), ensure_ascii=False)
            self.wfile.write(f"event: hello\ndata: {hello}\n\n".encode())
            self.wfile.flush()
            while True:
                try:
                    event, payload = q.get(timeout=10)
                    self.wfile.write(f"event: {event}\ndata: {payload}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            HUB.remove(q)

    # ------------------------------------------------ POST

    def do_POST(self):
        path = urlparse(self.path).path
        if path.startswith("/hook/"):
            if not self._local():
                return self._send(403, {"error": "só local"})
            ev = self._body()
            if path == "/hook/claude":
                threading.Thread(target=AGENT.on_hook, args=(ev,), daemon=True).start()
                return self._send(200, {})
            if path == "/hook/permission":
                return self._send(200, AGENT.permission_request(ev, self.connection))
            if path == "/hook/statusline":
                AGENT.set_quota(ev)
                return self._send(200, {})
            return self._send(404, {})

        if not self._authorized():
            return self._send(403, {"error": "token"})
        if path == "/api/voice":
            n = int(self.headers.get("Content-Length") or 0)
            if not 1000 < n < 4_000_000:
                return self._send(400, {"error": "áudio inválido"})
            wake = (self._query().get('wake') or ['0'])[0] == '1'
            VOICE.hear(self.rfile.read(n), wake=wake)
            return self._send(200, {"ok": True})
        body = self._body()
        try:
            if path == "/api/reload":
                HUB.broadcast("reload", {"t": int(time.time())})
                return self._send(200, {"ok": True})
            if path == "/api/action":
                result = do_action(body.get("id", ""))
                if "level" in result or "status" in result or "player" in result:
                    HUB.broadcast("media" if "player" in result else "volume", result)
                return self._send(200, {"ok": True, "result": result})
            if path == "/api/app":
                ok, error = pc.launch_app(str(body.get("id", "")))
                return self._send(200 if ok else 400, {"ok": ok, "error": error})
            if path == "/api/volume":
                STATE["volume"] = pc.volume_set(body.get("level", 50))
                HUB.broadcast("volume", STATE["volume"])
                return self._send(200, {"ok": True})
            if path == "/api/permission":
                ok = AGENT.permission_decide(body.get("id"), body.get("behavior"), body.get("answers"))
                return self._send(200 if ok else 404, {"ok": ok})
            if path == "/api/mission":
                ok, info = start_mission(body)
                return self._send(200 if ok else 409, {"ok": ok, "info": info})
            if path == "/api/project":
                pc.project_action(body.get("path", ""), body.get("action", ""))
                return self._send(200, {"ok": True})
            if path == "/api/docker":
                pc.docker_action(body.get("names") or [], body.get("action", ""))
                return self._send(200, {"ok": True, "docker": pc.docker_containers()})
            if path == "/api/port/open":
                pc.open_port(body.get("port", 0))
                return self._send(200, {"ok": True})
            if path == "/api/ollama/unload":
                pc.ollama_unload(body.get("name", ""))
                return self._send(200, {"ok": True, "ollama": pc.ollama_loaded()})
            if path == "/api/toggle":
                STATE["toggles"] = pc.toggle(body.get("name", ""))
                HUB.broadcast("toggles", STATE["toggles"])
                return self._send(200, {"ok": True, "toggles": STATE["toggles"]})
            if path == "/api/pc":
                STATE["pcctl"] = pc.pc_set(body.get("what", ""), body.get("value"))
                HUB.broadcast("pcctl", STATE["pcctl"])
                return self._send(200, {"ok": True, "pcctl": STATE["pcctl"]})
            if path == "/api/quota/refresh":
                threading.Thread(target=AGENT.refresh_quota, kwargs={"probe": True}, daemon=True).start()
                return self._send(200, {"ok": True})
            if path == "/api/power":
                pc.power(body.get("action", ""))
                return self._send(200, {"ok": True})
            if path == "/api/handoff":
                return self._send(200, handoff(body.get("session", "")))
            if path == "/api/voice/warm":
                VOICE.warm()
                return self._send(200, {"ok": True})
            if path == "/api/voice/cancel":
                VOICE.cancel_listening()
                return self._send(200, {"ok": True})
            if path == "/api/voice/mode":
                VOICE.set_handsfree_mode(body.get('handsfree') is True)
                return self._send(200, {"ok": True, "handsfree": VOICE.handsfree_enabled})
            if path == "/api/voice/prompt":
                threading.Thread(target=VOICE.prompt_to_listen, daemon=True).start()
                return self._send(200, {"ok": True})
            if path == "/api/voice/set":
                VOICE.set_voice(body.get("id", ""))
                save_user_config("voice", VOICE.voice_id)
                HUB.broadcast("voice", {"enabled": VOICE.enabled, **VOICE.voices()})
                return self._send(200, {"ok": True})
            if path == "/api/voice/enable":
                VOICE.enabled = bool(body.get("on"))
                save_user_config("voice_enabled", VOICE.enabled)
                HUB.broadcast("voice", {"enabled": VOICE.enabled, **VOICE.voices()})
                return self._send(200, {"ok": True, "enabled": VOICE.enabled})
            if path == "/api/say":
                threading.Thread(target=VOICE.say, args=(str(body.get("text", ""))[:400], "reply"), daemon=True).start()
                return self._send(200, {"ok": True})
            if path == "/api/converse":
                text = str(body.get("text") or "").strip()[:800]
                if not text:
                    return self._send(400, {"ok": False, "error": "texto vazio"})
                HUB.broadcast("heard", {"state": "ok", "text": text})
                AGENT.log("voice", f"Você: {text}")
                ok, info = VOICE.converse(text)
                return self._send(200 if ok else 409, {"ok": ok, "info": info})
            if path == "/api/whatsapp/confirm":
                ok = VOICE.wa_decide(bool(body.get("send")), body.get("text"))
                return self._send(200 if ok else 404, {"ok": ok})
            if path == "/api/guara/interact":
                res = guara_interact(str(body.get("kind") or "poke"))
                return self._send(200 if res.get("ok", True) else 409, res)
            if path == "/api/yt/play":
                res = pc.yt_play(
                    str(body.get("id") or ""),
                    str(body.get("title") or ""),
                    str(body.get("channel") or ""),
                    str(body.get("mode") or "tablet"),
                    body.get("queue") or [],
                )
                STATE["media"] = pc.media_now()
                HUB.broadcast("media", STATE["media"])
                return self._send(200, {"ok": True, "result": res, "media": STATE["media"]})
            if path == "/api/yt/stop":
                pc.yt_stop()
                STATE["media"] = pc.media_now()
                HUB.broadcast("media", STATE["media"])
                return self._send(200, {"ok": True, "media": STATE["media"]})
            if path == "/api/style":
                st = "pixel" if body.get("style") == "pixel" else "real"
                CFG["guara_style"] = st
                save_user_config("guara_style", st)
                HUB.broadcast("style", {"style": st})
                return self._send(200, {"ok": True, "style": st})
            if path == "/api/mission/cancel":
                return self._send(200, {"ok": AGENT.mission_cancel()})
        except Exception as e:
            return self._send(500, {"ok": False, "error": str(e)})
        return self._send(404, {"error": "não existe"})


# ---------------------------------------------------------------- laços de fundo

def loop_stats():
    while True:
        try:
            STATE["stats"] = STATS.read()
            AGENT.pc_idle_ms = pc.pc_idle_ms() or 0
            if HUB.clients:
                HUB.broadcast("stats", STATE["stats"])
                # o painel só usa a ociosidade para apagar a tela (limiares de minutos): de 10 em 10 s e só se mudou
                HUB.broadcast("pc", {"idle_ms": AGENT.pc_idle_ms // 10000 * 10000}, only_if_changed=True)
            AGENT.tick()
        except Exception as e:
            sys.stderr.write(f"stats: {e}\n")
        time.sleep(2)


def loop_media():
    while True:
        try:
            STATE["media"] = pc.media_now()
            STATE["volume"] = pc.volume_get()
            HUB.broadcast("media", STATE["media"], only_if_changed=True)
            HUB.broadcast("volume", STATE["volume"], only_if_changed=True)
        except Exception as e:
            sys.stderr.write(f"media: {e}\n")
        time.sleep(2 if HUB.clients else 6)


def loop_toggles():
    while True:
        try:
            STATE["toggles"] = pc.toggles()
            HUB.broadcast("toggles", STATE["toggles"], only_if_changed=True)
            STATE["pcctl"] = pc.pc_controls()
            HUB.broadcast("pcctl", STATE["pcctl"], only_if_changed=True)
            AGENT.publish_quota()
        except Exception as e:
            sys.stderr.write(f"toggles: {e}\n")
        time.sleep(6 if HUB.clients else 30)


def loop_beacon():
    """Anuncia o PC na rede: o tablet acha o servidor mesmo se o IP mudar."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    msg = f"CAPI1 {CFG['port']}".encode()
    while True:
        announce(s, msg, CFG["discovery_port"])
        time.sleep(3)


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.0.1", 9))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    for fn in (loop_stats, loop_media, loop_toggles, loop_beacon):
        threading.Thread(target=fn, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", CFG["port"]), Handler)
    srv.daemon_threads = True
    print(f"Capi no ar: http://{lan_ip()}:{CFG['port']}/?t={CFG['token']}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
