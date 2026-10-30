"""Ações e leituras do PC (GNOME/Wayland): mídia, volume, atalhos, monitor, ociosidade."""

import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import psutil

try:
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
except Exception:  # sem PyGObject a mídia fica desativada, o resto funciona
    Gio = GLib = None


def _run(args, timeout=4):
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return out.stdout.strip()
    except Exception:
        return ""


def _spawn(args, cwd=None):
    """Abre um programa desacoplado do servidor (sobrevive a reinícios do serviço)."""
    subprocess.Popen(
        args,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


# ---------------------------------------------------------------- volume

def volume_get():
    out = _run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
    m = re.search(r"([\d.]+)", out)
    return {"level": round(float(m.group(1)) * 100) if m else None, "muted": "MUTED" in out}


def volume_step(delta):
    sign = "+" if delta > 0 else "-"
    _run(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{abs(delta)}%{sign}"])
    return volume_get()


def volume_set(level):
    level = max(0, min(100, int(level)))
    _run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{level}%"])
    return volume_get()


def volume_mute():
    _run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])
    return volume_get()


# ---------------------------------------------------------------- mídia (MPRIS)

MPRIS_PATH = "/org/mpris/MediaPlayer2"
MPRIS_PLAYER = "org.mpris.MediaPlayer2.Player"
_bus_lock = threading.Lock()
_bus = None


def _session_bus():
    global _bus
    with _bus_lock:
        if _bus is None and Gio is not None:
            _bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        return _bus


def _players():
    bus = _session_bus()
    if bus is None:
        return []
    names = bus.call_sync(
        "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
        "ListNames", None, GLib.VariantType("(as)"), 0, 1000, None,
    ).unpack()[0]
    players = []
    for name in names:
        if not name.startswith("org.mpris.MediaPlayer2."):
            continue
        try:
            props = bus.call_sync(
                name, MPRIS_PATH, "org.freedesktop.DBus.Properties", "GetAll",
                GLib.Variant("(s)", (MPRIS_PLAYER,)), GLib.VariantType("(a{sv})"), 0, 1000, None,
            ).unpack()[0]
        except Exception:
            continue
        players.append((name, props))
    order = {"Playing": 0, "Paused": 1}
    players.sort(key=lambda p: order.get(p[1].get("PlaybackStatus"), 2))
    return players


def media_now():
    yt = _yt_media_now()
    if yt and yt.get("status") == "Playing":
        return yt
    try:
        players = _players()
    except Exception:
        players = []
    if players:
        name, props = players[0]
        if props.get("PlaybackStatus") == "Playing" or not yt:
            meta = props.get("Metadata", {}) or {}
            artist = meta.get("xesam:artist") or []
            return {
                "player": name.split(".")[3] if name.count(".") >= 3 else name,
                "status": props.get("PlaybackStatus"),
                "title": meta.get("xesam:title") or "",
                "artist": ", ".join(artist) if isinstance(artist, list) else str(artist),
                "art": meta.get("mpris:artUrl") or "",
            }
    if yt:
        return yt
    return {"player": None}


def media_cmd(method):
    cur = media_now()
    if cur.get("player") in ("youtube-pc", "youtube-tablet"):
        return yt_control(method)
    players = _players()
    if not players:
        return media_now()
    bus = _session_bus()
    bus.call_sync(players[0][0], MPRIS_PATH, MPRIS_PLAYER, method, None, None, 0, 2000, None)
    time.sleep(0.25)
    return media_now()


_art_cache = {}


def media_art(url):
    """Busca a capa no PC (o Android 4.4 não confia nos certificados HTTPS atuais)."""
    if not url:
        return None
    if url in _art_cache:
        return _art_cache[url]
    data = None
    try:
        if url.startswith("file://"):
            data = Path(urllib.request.url2pathname(url[7:])).read_bytes()
        elif url.startswith(("http://", "https://")):
            with urllib.request.urlopen(url, timeout=4) as r:
                data = r.read(2_000_000)
    except Exception:
        data = None
    if len(_art_cache) > 20:
        _art_cache.clear()
    _art_cache[url] = data
    return data


# ---------------------------------------------------------------- atalhos

DESKTOP_DIRS = [
    Path.home() / ".local/share/applications",
    Path("/var/lib/snapd/desktop/applications"),
    Path("/var/lib/flatpak/exports/share/applications"),
    Path("/usr/share/applications"),
]


def find_desktop(app_id):
    for d in DESKTOP_DIRS:
        p = d / f"{app_id}.desktop"
        if p.exists():
            return p
    return None


def run_shortcut(sc):
    kind, target = sc.get("kind"), sc.get("target", "")
    if kind == "app":
        path = find_desktop(target)
        if not path:
            return False, f"app {target} não encontrado"
        _spawn(["gio", "launch", str(path)])
    elif kind == "open":
        _spawn(["gio", "open", os.path.expanduser(target)])
    elif kind == "cmd":
        _spawn(["bash", "-lc", target], cwd=str(Path.home()))
    elif kind == "lock":
        _spawn(["loginctl", "lock-session"])
    elif kind == "screenshot":
        _spawn(["gnome-screenshot"])
    else:
        return False, f"tipo {kind} desconhecido"
    return True, ""


def shortcut_available(sc):
    if sc.get("kind") == "app":
        return find_desktop(sc.get("target", "")) is not None
    return True


# ---------------------------------------------------------------- apps do PC (aba Apps do tablet)

ICON_CACHE = Path.home() / ".cache" / "guara" / "icons"
ICON_BASES = [Path.home() / ".local/share/icons", Path.home() / ".icons", Path("/usr/share/icons"),
              Path("/var/lib/flatpak/exports/share/icons")]
ICON_SIZES = ["64x64", "scalable", "512x512", "256x256", "128x128", "96x96", "48x48"]
# Nomes curtos em português para os apps cujo .desktop só traz o nome em inglês ou longo demais
APP_LABELS = {
    "org.gnome.Nautilus": "Arquivos", "org.gnome.Settings": "Ajustes", "org.gnome.baobab": "Uso do disco",
    "code_code": "VS Code", "dbeaver-ce": "DBeaver", "microsoft-edge": "Edge", "org.gnome.Ptyxis": "Terminal",
    "com.blackmagicdesign.resolve": "DaVinci Resolve", "davinci-resolve-ai": "DaVinci + Claude",
    "davinci-resolve-codex": "DaVinci + Codex", "maestro": "Maestro", "com.teamviewer.TeamViewer": "TeamViewer",
    "com.obsproject.Studio": "OBS", "waydroid.br.com.intelbras.guardian": "Guardian", "org.gnome.TextEditor": "Editor de texto",
    "beekeeper-studio": "Beekeeper", "github-desktop": "GitHub", "docker-desktop": "Docker", "minilab-studio": "MiniLab",
}


def desktop_entry(app_id):
    """Nome (em português, se houver) e ícone do .desktop do app."""
    path = find_desktop(app_id)
    if not path:
        return None
    out, inside = {}, False
    for line in path.read_text(errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("["):
            inside = line == "[Desktop Entry]"
            continue
        if inside and "=" in line:
            k, v = line.split("=", 1)
            out.setdefault(k.strip(), v.strip())
    if out.get("NoDisplay") == "true" and app_id not in favorite_ids():
        return None
    name = APP_LABELS.get(app_id) or out.get("Name[pt_BR]") or out.get("Name[pt]") or out.get("Name") or app_id
    return {"name": name, "icon": out.get("Icon", "")}


def icon_file(name):
    """Arquivo do ícone: caminho absoluto do .desktop, ou procurado no tema do GNOME (Papirus) e no hicolor."""
    if not name:
        return None
    if os.path.isabs(name):
        return Path(name) if os.path.exists(name) else None
    theme = (_run(["gsettings", "get", "org.gnome.desktop.interface", "icon-theme"]).strip("'\n ") or "hicolor")
    themes = [theme, theme.split("-")[0], "hicolor", "Adwaita"]
    for t in themes:
        for base in ICON_BASES:
            for size in ICON_SIZES:
                for cat in ("apps", "places"):
                    for ext in (".svg", ".png"):
                        p = base / t / size / cat / f"{name}{ext}"
                        if p.exists():
                            return p
    for p in (Path("/var/lib/snapd/desktop/icons") / f"{name}.png", Path("/usr/share/pixmaps") / f"{name}.png",
              Path("/usr/share/pixmaps") / f"{name}.svg"):
        if p.exists():
            return p
    return None


def app_icon(key, size=128):
    """PNG do ícone (de um app pelo id do .desktop, ou de um nome do tema), guardado em cache."""
    out = ICON_CACHE / f"{key}-{size}.png"
    if out.exists():
        return out.read_bytes()
    entry = desktop_entry(key)
    f = icon_file(entry["icon"] if entry else key)
    if not f:
        return None
    try:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(f), size, size, True)
        ICON_CACHE.mkdir(parents=True, exist_ok=True)
        pb.savev(str(out), "png", [], [])
        return out.read_bytes()
    except Exception:
        return None


def favorite_ids():
    raw = _run(["gsettings", "get", "org.gnome.shell", "favorite-apps"])
    return re.findall(r"'([^']+)\.desktop'", raw)


def apps_catalog(extra):
    """Os apps da dock do GNOME (o que você mais usa, na sua ordem) e depois os atalhos extras da config."""
    items, seen = [], set()
    for app_id in favorite_ids():
        e = desktop_entry(app_id)
        if e and app_id not in seen:
            seen.add(app_id)
            items.append({"id": app_id, "label": e["name"], "kind": "app", "img": f"/api/appicon/{app_id}.png"})
    for sc in extra:
        key = sc.get("target") if sc.get("kind") == "app" else sc["id"]
        if key in seen or not shortcut_available(sc) or sc.get("kind") in ("lock", "screenshot"):
            continue
        seen.add(key)
        items.append({"id": sc["id"], "label": sc["label"], "kind": "shortcut", "img": shortcut_img(sc),
                      "icon": sc.get("icon", ""), "color": sc.get("color", "")})
    return items


def shortcut_img(sc):
    key = sc.get("target") if sc.get("kind") == "app" else sc.get("theme_icon")
    return f"/api/appicon/{key}.png" if key else ""


def open_target(item, shortcuts):
    """Ponte segura da voz: abre um site http(s) ou um app da dock/atalho. Qualquer outra coisa é recusada."""
    item = item.strip().strip("<>\"'`")
    if re.fullmatch(r"https?://[^\s'\"<>`]+", item):
        _spawn(["gio", "open", item])
        return True
    if item in favorite_ids():
        return launch_app(item)[0]
    low = item.lower()
    sc = next((s for s in shortcuts if low in (s["id"], s["label"].lower(), s.get("target", "").lower())), None)
    if sc and sc.get("kind") in ("app", "open"):
        return run_shortcut(sc)[0]
    return False


def launch_app(app_id):
    if app_id not in favorite_ids():
        return False, "app fora da dock"
    path = find_desktop(app_id)
    if not path:
        return False, f"app {app_id} não encontrado"
    _spawn(["gio", "launch", str(path)])
    return True, ""


# ---------------------------------------------------------------- monitor

class Stats:
    def __init__(self):
        psutil.cpu_percent(interval=None)
        self._net = psutil.net_io_counters()
        self._t = time.time()
        self._gpu = {}
        self._gpu_t = 0
        self.has_nvidia = shutil.which("nvidia-smi") is not None

    def _gpu_read(self):
        if not self.has_nvidia or time.time() - self._gpu_t < 4:
            return self._gpu
        self._gpu_t = time.time()
        out = _run([
            "nvidia-smi",
            "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total,name",
            "--format=csv,noheader,nounits",
        ])
        try:
            util, temp, used, total, name = [x.strip() for x in out.splitlines()[0].split(",")]
            self._gpu = {"util": int(util), "temp": int(temp), "mem_used": int(used),
                         "mem_total": int(total), "name": name}
        except Exception:
            self._gpu = {}
        return self._gpu

    @staticmethod
    def _cpu_temp():
        try:
            temps = psutil.sensors_temperatures()
        except Exception:
            return None
        for key in ("coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz"):
            for t in temps.get(key, []):
                if key != "coretemp" or t.label.startswith(("Package", "Tctl")) or not t.label:
                    return round(t.current)
        return None

    def read(self):
        now = time.time()
        net = psutil.net_io_counters()
        dt = max(0.5, now - self._t)
        down = (net.bytes_recv - self._net.bytes_recv) / dt
        up = (net.bytes_sent - self._net.bytes_sent) / dt
        self._net, self._t = net, now
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(str(Path.home()))
        return {
            "cpu": round(psutil.cpu_percent(interval=None)),
            "cpu_temp": self._cpu_temp(),
            "cores": psutil.cpu_count(),
            "mem_used": round(mem.used / 2**30, 1),
            "mem_total": round(mem.total / 2**30, 1),
            "mem": round(mem.percent),
            "disk": round(disk.percent),
            "disk_free": round(disk.free / 2**30),
            "down": round(down),
            "up": round(up),
            "gpu": self._gpu_read(),
            "uptime": int(now - psutil.boot_time()),
        }


def pc_idle_ms():
    out = _run([
        "gdbus", "call", "--session", "--dest", "org.gnome.Mutter.IdleMonitor",
        "--object-path", "/org/gnome/Mutter/IdleMonitor/Core",
        "--method", "org.gnome.Mutter.IdleMonitor.GetIdletime",
    ], timeout=2)
    m = re.search(r"(\d+)", out)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- dev: projetos git

PROJECTS_DIR = Path.home() / "Área de trabalho" / "PROJETOS"
EXTRA_PATH = f"{Path.home()}/.local/bin:/snap/bin:/usr/local/bin:/usr/bin:/bin"
_projects_cache = {"t": 0, "data": []}


def _git(path, *args):
    return _run(["git", "-C", str(path), *args], timeout=4)


def projects(force=False):
    if not force and time.time() - _projects_cache["t"] < 15:
        return _projects_cache["data"]
    out = []
    for d in sorted(PROJECTS_DIR.iterdir()) if PROJECTS_DIR.exists() else []:
        if not d.is_dir() or d.name.startswith("."):
            continue
        item = {"name": d.name, "path": str(d), "git": (d / ".git").exists(), "ts": int(d.stat().st_mtime)}
        if item["git"]:
            status = _git(d, "status", "--porcelain=v1", "-b").splitlines()
            head = status[0] if status else ""
            item["branch"] = re.sub(r"^## (No commits yet on )?", "", head).split("...")[0]
            item["changes"] = max(0, len(status) - 1)
            m = re.search(r"ahead (\d+)", head)
            item["ahead"] = int(m.group(1)) if m else 0
            item["remote"] = github_url(_git(d, "remote", "get-url", "origin"))
            log = _git(d, "log", "-1", "--format=%ct|%s")
            if "|" in log:
                ts, subject = log.split("|", 1)
                item["ts"] = max(item["ts"], int(ts))
                item["last"] = subject[:80]
        out.append(item)
    out.sort(key=lambda p: (not p["git"], -p["ts"]))
    _projects_cache.update(t=time.time(), data=out)
    return out


def github_url(remote):
    """git@github.com:dono/repo.git ou https://github.com/dono/repo.git → página do repositório."""
    m = re.search(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", remote or "")
    return f"https://github.com/{m.group(1)}/{m.group(2)}" if m else ""


def _terminal(path, command=None):
    """Abre o Ptyxis numa pasta (opcionalmente já rodando um comando, ex.: claude)."""
    args = ["ptyxis", "--new-window", "-d", str(path)]
    if command:
        args += ["-x", f"env PATH={EXTRA_PATH}:$PATH bash -lc {shlex.quote(command + '; exec bash')}"]
    _spawn(args)


def project_action(path, action, extra=""):
    p = Path(path).resolve()
    if PROJECTS_DIR.resolve() not in p.parents or not p.is_dir():
        raise ValueError("pasta fora de PROJETOS")
    if action == "code":
        _spawn([shutil.which("code", path=EXTRA_PATH) or "code", str(p)])
    elif action == "term":
        _terminal(p)
    elif action == "claude":
        _terminal(p, "claude")
    elif action == "codex":
        _terminal(p, "codex" + (" " + shlex.quote(extra) if extra else ""))
    elif action == "folder":
        _spawn(["gio", "open", str(p)])
    elif action == "github":
        url = next((x.get("remote") for x in projects() if x["path"] == str(p)), "")
        if not url:
            raise ValueError("projeto sem repositório no GitHub")
        _spawn(["xdg-open", url])
    else:
        raise ValueError(f"ação {action} desconhecida")


# ---------------------------------------------------------------- dev: docker, portas, ollama

def docker_containers():
    out = _run(["docker", "ps", "-a", "--format", "{{json .}}"], timeout=6)
    items = []
    for line in out.splitlines():
        try:
            c = json.loads(line)
        except Exception:
            continue
        labels = dict(kv.split("=", 1) for kv in (c.get("Labels") or "").split(",") if "=" in kv)
        group = labels.get("com.docker.compose.project") or labels.get("com.supabase.cli.project") or ""
        if group and labels.get("com.supabase.cli.project"):
            group = "supabase · " + group
        items.append({"name": c.get("Names", ""), "image": c.get("Image", "").split("/")[-1],
                      "state": c.get("State", ""), "status": c.get("Status", ""), "group": group or "avulsos"})
    items.sort(key=lambda c: (c["group"] == "avulsos", c["group"], c["state"] != "running", c["name"]))
    return items


def docker_action(names, action):
    if action not in ("start", "stop", "restart") or not names:
        raise ValueError("ação inválida")
    known = {c["name"] for c in docker_containers()}
    names = [n for n in names if n in known]
    if not names:
        raise ValueError("container não encontrado")
    _run(["docker", action, *names], timeout=60)


KNOWN_PORTS = {11434: "Ollama", 54321: "Supabase API", 54322: "Supabase DB", 54323: "Supabase Studio",
               54324: "Supabase Mail", 5173: "Vite", 3000: "Dev server", 8000: "Servidor", 8080: "Servidor",
               5432: "Postgres", 6379: "Redis", 47801: "Guará"}
HIDE_PORTS = {53, 111, 631, 47801}


def listening_ports():
    out = _run(["ss", "-ltnpH"])
    seen = {}
    for line in out.splitlines():
        cols = line.split()
        if len(cols) < 4:
            continue
        addr = cols[3]
        try:
            port = int(addr.rsplit(":", 1)[1])
        except ValueError:
            continue
        if port in HIDE_PORTS or port in seen or "tailscale" in addr:
            continue
        m = re.search(r'\(\("([^"]+)"', line)
        proc = m.group(1) if m else ""
        if proc in ("code", "agy", "antigravity") and port not in KNOWN_PORTS:
            continue  # portas internas do editor
        seen[port] = {"port": port, "proc": proc, "label": KNOWN_PORTS.get(port, proc or "serviço"),
                      "local": addr.startswith(("127.", "[::1]"))}
    return sorted(seen.values(), key=lambda p: p["port"])


def open_port(port):
    _spawn(["xdg-open", f"http://localhost:{int(port)}"])


def ollama_loaded():
    out = _run(["ollama", "ps"])
    models = []
    for line in out.splitlines()[1:]:
        cols = re.split(r"\s{2,}", line.strip())
        if len(cols) >= 4:
            models.append({"name": cols[0], "size": cols[2], "processor": cols[3]})
    return models


def ollama_unload(name):
    if name not in {m["name"] for m in ollama_loaded()}:
        raise ValueError("modelo não está carregado")
    _run(["ollama", "stop", name], timeout=30)


# ---------------------------------------------------------------- ajustes rápidos do sistema

_inhibitor = {"proc": None}


def _gs_get(schema, key):
    return _run(["gsettings", "get", schema, key])


def toggles():
    src = _run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"])
    inh = _inhibitor["proc"]
    return {
        "dnd": _gs_get("org.gnome.desktop.notifications", "show-banners") == "false",
        "night": _gs_get("org.gnome.settings-daemon.plugins.color", "night-light-enabled") == "true",
        "dark": "dark" in _gs_get("org.gnome.desktop.interface", "color-scheme"),
        "micmute": "MUTED" in src,
        "awake": inh is not None and inh.poll() is None,
        "mute": volume_get()["muted"],
    }


def toggle(name):
    cur = toggles()
    if name == "dnd":
        _run(["gsettings", "set", "org.gnome.desktop.notifications", "show-banners", "true" if cur["dnd"] else "false"])
    elif name == "night":
        _run(["gsettings", "set", "org.gnome.settings-daemon.plugins.color", "night-light-enabled",
              "false" if cur["night"] else "true"])
    elif name == "dark":
        _run(["gsettings", "set", "org.gnome.desktop.interface", "color-scheme",
              "'default'" if cur["dark"] else "'prefer-dark'"])
    elif name == "micmute":
        _run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"])
    elif name == "mute":
        volume_mute()
    elif name == "awake":
        if cur["awake"]:
            _inhibitor["proc"].terminate()
            _inhibitor["proc"] = None
        else:
            _inhibitor["proc"] = subprocess.Popen(
                ["systemd-inhibit", "--what=idle:sleep", "--who=Guará", "--why=Manter acordado pelo tablet",
                 "sleep", "infinity"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        raise ValueError(f"ajuste {name} desconhecido")
    return toggles()


def power(action):
    if action == "lock":
        _spawn(["loginctl", "lock-session"])
    elif action == "suspend":
        _spawn(["systemctl", "suspend"])
    elif action == "screenshot":
        _spawn(["gnome-screenshot"])
    else:
        raise ValueError(f"ação {action} desconhecida")


# ---------------------------------------------------------------- controles do PC (no tablet)

def _backlight():
    devs = sorted(Path("/sys/class/backlight").glob("*"))
    return devs[0] if devs else None


def _graphical_session():
    """Sessão do logind deste usuário no seat0: é ela que pode mudar o brilho sem root."""
    me = os.environ.get("USER") or Path.home().name
    for line in _run(["loginctl", "list-sessions", "--no-legend"]).splitlines():
        cols = line.split()
        if len(cols) >= 4 and cols[2] == me and cols[3] == "seat0":
            return cols[0]
    return None


def pc_brightness():
    b = _backlight()
    if not b:
        return None
    try:
        cur, mx = int((b / "brightness").read_text()), int((b / "max_brightness").read_text())
        return round(cur * 100 / mx)
    except Exception:
        return None


def set_pc_brightness(pct):
    b, sid = _backlight(), _graphical_session()
    if not b or not sid:
        raise ValueError("brilho da tela indisponível")
    mx = int((b / "max_brightness").read_text())
    value = max(1, round(mx * max(1, min(100, int(pct))) / 100))
    _run(["busctl", "call", "org.freedesktop.login1", f"/org/freedesktop/login1/session/{sid}",
          "org.freedesktop.login1.Session", "SetBrightness", "ssu", "backlight", b.name, str(value)])
    return pc_brightness()


def power_profile():
    return _run(["powerprofilesctl", "get"]) or None


def set_power_profile(name):
    if name not in ("power-saver", "balanced", "performance"):
        raise ValueError("perfil inválido")
    _run(["powerprofilesctl", "set", name])
    return power_profile()


def bluetooth_on():
    out = _run(["bluetoothctl", "show"])
    return "Powered: yes" in out if out else None


def set_bluetooth(on):
    _run(["bluetoothctl", "power", "on" if on else "off"], timeout=8)
    return bluetooth_on()


def battery():
    dev = next((d for d in _run(["upower", "-e"]).splitlines() if "BAT" in d), None)
    if not dev:
        return None
    info = _run(["upower", "-i", dev])
    pct = re.search(r"percentage:\s+(\d+)", info)
    state = re.search(r"state:\s+(\S+)", info)
    left = re.search(r"time to (?:empty|full):\s+([\d.,]+)\s+(\w+)", info)
    return {"pct": int(pct.group(1)) if pct else None, "state": state.group(1) if state else "",
            "left": _eta(left)}


def _eta(m):
    """'1,5 hours' vira '1 h 30 min'. Estimativa acima de um dia (carga lenta) não ajuda e some."""
    if not m:
        return ""
    mins = float(m.group(1).replace(",", ".")) * {"seconds": 1 / 60, "minutes": 1, "hours": 60, "days": 1440}.get(m.group(2), 0)
    if not 0 < mins <= 1440:
        return ""
    h, mi = divmod(int(round(mins)), 60)
    return (f"{h} h {mi} min" if mi else f"{h} h") if h else f"{mi} min"


def mic_volume():
    out = _run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"])
    m = re.search(r"([\d.]+)", out)
    return {"level": round(float(m.group(1)) * 100) if m else None, "muted": "MUTED" in out}


def set_mic_volume(level):
    _run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SOURCE@", f"{max(0, min(100, int(level)))}%"])
    return mic_volume()


def sinks():
    try:
        items = json.loads(_run(["pactl", "-f", "json", "list", "sinks"]) or "[]")
    except Exception:
        items = []
    default = _run(["pactl", "get-default-sink"])
    out = []
    for s in items:
        props = s.get("properties") or {}
        names = [s.get("description"), props.get("device.description"), props.get("alsa.card_name")]
        name = next((n for n in names if n and n != "(null)"), None)
        if not name:
            name = "Alto-falantes do PC" if "analog" in (s.get("name") or "") else "Saída de som"
        out.append({"id": s.get("name"), "name": name,
                    "default": s.get("name") == default})
    return out


def set_sink(sink_id):
    if sink_id not in {s["id"] for s in sinks()}:
        raise ValueError("saída de som não encontrada")
    _run(["pactl", "set-default-sink", sink_id])
    return sinks()


def pc_controls():
    return {"brightness": pc_brightness(), "profile": power_profile(), "bluetooth": bluetooth_on(),
            "battery": battery(), "mic": mic_volume(), "sinks": sinks()}


def pc_set(what, value):
    if what == "brightness":
        set_pc_brightness(value)
    elif what == "profile":
        set_power_profile(value)
    elif what == "bluetooth":
        set_bluetooth(bool(value))
    elif what == "mic":
        set_mic_volume(value)
    elif what == "sink":
        set_sink(value)
    else:
        raise ValueError(f"controle {what} desconhecido")
    return pc_controls()


# ---------------------------------------------------------------- de onde vem cada agente

ENTRYPOINTS = {"claude-vscode": "VS Code", "cli": "terminal", "claude-desktop": "app", "sdk-cli": "script",
               "sdk-ts": "script", "sdk-py": "script"}


def claude_source(cwd):
    """VS Code, terminal…: lê CLAUDE_CODE_ENTRYPOINT do processo claude que trabalha nessa pasta
    (ou numa pasta acima dela; o Claude muda de subpasta durante a sessão)."""
    near, interactive = None, []
    for proc in psutil.process_iter(["pid", "name", "exe", "cwd"]):
        try:
            if "claude" not in (proc.info["name"] or "") and "claude" not in (proc.info["exe"] or ""):
                continue
            entry = proc.environ().get("CLAUDE_CODE_ENTRYPOINT", "")
        except (psutil.Error, OSError):
            continue
        source = ENTRYPOINTS.get(entry, entry or "terminal")
        if source == "script":   # claude -p (missões do Guará, scripts): nunca é a sessão que você vê
            continue
        interactive.append(source)
        pcwd = proc.info["cwd"] or ""
        if cwd and pcwd and (cwd == pcwd or cwd.startswith(pcwd.rstrip("/") + "/")):
            near = source
    if near:
        return near
    return interactive[0] if len(set(interactive)) == 1 else ""


# ---------------------------------------------------------------- YouTube (busca + player no PC ou Tablet)

YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,16}$")
MPV_SOCK = "/tmp/guara-mpv.sock"
_yt_lock = threading.Lock()
_yt_search_cache = {}
_yt_thumb_cache = {}
_mpv_proc = None
_yt_state = {"mode": None, "queue": [], "idx": 0, "paused": False}


def _node_bin():
    n = shutil.which("node")
    if n:
        return n
    nvm = Path.home() / ".nvm/versions/node"
    if nvm.is_dir():
        bins = sorted(nvm.glob("*/bin/node"))
        if bins:
            return str(bins[-1])
    return ""


def _fmt_dur(sec):
    if not sec:
        return "AO VIVO"
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def yt_search(query, limit=8):
    q = re.sub(r"\s+", " ", (query or "").strip())[:100]
    if not q:
        return []
    key = q.lower()
    now = time.time()
    cached = _yt_search_cache.get(key)
    if cached and now - cached[0] < 600:
        return cached[1]
    cmd = ["yt-dlp", "--no-update", "--flat-playlist", "-J", f"ytsearch{int(limit)}:{q}"]
    node = _node_bin()
    if node:
        cmd[2:2] = ["--js-runtimes", f"node:{node}"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        data = json.loads(r.stdout or "{}")
    except Exception:
        return []
    items = []
    for e in data.get("entries") or []:
        vid = e.get("id") or ""
        if not YT_ID_RE.match(vid):
            continue
        title = (e.get("title") or "").strip()
        if not title or title == "[Private video]" or title == "[Deleted video]":
            continue
        ch = (e.get("channel") or e.get("uploader") or "YouTube").strip()
        dur = _fmt_dur(e.get("duration")) if e.get("live_status") != "is_live" else "AO VIVO"
        items.append({
            "id": vid,
            "title": title,
            "channel": ch,
            "duration": dur,
        })
    if items:
        if len(_yt_search_cache) > 24:
            _yt_search_cache.clear()
        _yt_search_cache[key] = (now, items)
    return items


def yt_thumb(vid):
    if not YT_ID_RE.match(vid or ""):
        return None
    if vid in _yt_thumb_cache:
        return _yt_thumb_cache[vid]
    data = None
    for q in ("mqdefault.jpg", "hqdefault.jpg"):
        try:
            with urllib.request.urlopen(f"https://i.ytimg.com/vi/{vid}/{q}", timeout=4) as r:
                data = r.read(600_000)
                if data:
                    break
        except Exception:
            continue
    if data:
        if len(_yt_thumb_cache) > 48:
            _yt_thumb_cache.clear()
        _yt_thumb_cache[vid] = data
    return data


def _mpv_ipc(command_list):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.4)
        s.connect(MPV_SOCK)
        s.sendall((json.dumps({"command": command_list}) + "\n").encode())
        resp = s.recv(4096).decode("utf-8", "ignore")
        s.close()
        for line in resp.splitlines():
            d = json.loads(line)
            if "data" in d or "error" in d:
                return d.get("data")
    except Exception:
        return None
    return None


def yt_stop():
    global _mpv_proc
    with _yt_lock:
        _yt_state["mode"] = None
        _yt_state["paused"] = False
        if _mpv_proc is not None:
            try:
                _mpv_proc.terminate()
                _mpv_proc.wait(timeout=1.5)
            except Exception:
                try:
                    _mpv_proc.kill()
                except Exception:
                    pass
            _mpv_proc = None
        try:
            os.unlink(MPV_SOCK)
        except OSError:
            pass


def _pause_other_mpris():
    try:
        bus = _session_bus()
        for name, props in _players():
            if props.get("PlaybackStatus") == "Playing":
                bus.call_sync(name, MPRIS_PATH, MPRIS_PLAYER, "Pause", None, None, 0, 1000, None)
    except Exception:
        pass


def yt_play(vid, title="", channel="", mode="tablet", queue=None):
    """Inicia reprodução do YouTube: 'tablet' (som direto no tablet), 'pc_audio' (mpv no PC) ou 'pc_video' (Chrome no PC)."""
    global _mpv_proc
    if not YT_ID_RE.match(vid or ""):
        raise ValueError("vídeo inválido")
    q_clean = []
    if isinstance(queue, list):
        for it in queue[:12]:
            if isinstance(it, dict) and YT_ID_RE.match(it.get("id") or ""):
                q_clean.append({
                    "id": it["id"],
                    "title": (it.get("title") or "YouTube")[:120],
                    "channel": (it.get("channel") or "YouTube")[:80],
                })
    if not any(x["id"] == vid for x in q_clean):
        q_clean.insert(0, {"id": vid, "title": (title or "YouTube")[:120], "channel": (channel or "YouTube")[:80]})
    idx = next((i for i, x in enumerate(q_clean) if x["id"] == vid), 0)

    yt_stop()
    if mode == "pc_video":
        _pause_other_mpris()
        _spawn(["gio", "open", f"https://www.youtube.com/watch?v={vid}"])
        return {"mode": "pc_video", "id": vid}

    if mode == "pc_audio":
        _pause_other_mpris()
        node = _node_bin()
        ordered = q_clean[idx:] + q_clean[:idx]
        args = [
            "mpv", "--no-video", "--ytdl-format=bestaudio/best",
            f"--input-ipc-server={MPV_SOCK}", "--really-quiet",
        ]
        if node:
            args.append(f"--ytdl-raw-options=js-runtimes=node:{node},no-update=")
        args.extend(f"https://www.youtube.com/watch?v={x['id']}" for x in ordered)
        with _yt_lock:
            _mpv_proc = subprocess.Popen(
                args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            _yt_state.update({"mode": "pc_audio", "queue": ordered, "idx": 0, "paused": False})
        return {"mode": "pc_audio", "id": vid, "media": _yt_media_now()}

    # mode == "tablet": áudio tocado direto no alto-falante do tablet
    with _yt_lock:
        _yt_state.update({"mode": "tablet", "queue": q_clean, "idx": idx, "paused": False})
    return {"mode": "tablet", "id": vid, "media": _yt_media_now()}


def _yt_media_now():
    with _yt_lock:
        mode = _yt_state.get("mode")
        if not mode:
            return None
        q = _yt_state.get("queue") or []
        if not q:
            return None
        if mode == "pc_audio":
            if _mpv_proc is None or _mpv_proc.poll() is not None:
                _yt_state["mode"] = None
                return None
            pos = _mpv_ipc(["get_property", "playlist-pos"])
            paused = _mpv_ipc(["get_property", "pause"])
            if isinstance(pos, int) and 0 <= pos < len(q):
                _yt_state["idx"] = pos
            if isinstance(paused, bool):
                _yt_state["paused"] = paused
            cur = q[_yt_state["idx"] % len(q)]
            return {
                "player": "youtube-pc",
                "status": "Paused" if _yt_state["paused"] else "Playing",
                "title": cur["title"],
                "artist": cur["channel"] + " · YouTube no PC",
                "art": f"https://i.ytimg.com/vi/{cur['id']}/mqdefault.jpg",
                "yt_id": cur["id"],
                "yt_mode": "pc_audio",
            }
        if mode == "tablet":
            cur = q[_yt_state["idx"] % len(q)]
            return {
                "player": "youtube-tablet",
                "status": "Paused" if _yt_state["paused"] else "Playing",
                "title": cur["title"],
                "artist": cur["channel"] + " · Tocando no Tablet",
                "art": f"https://i.ytimg.com/vi/{cur['id']}/mqdefault.jpg",
                "yt_id": cur["id"],
                "yt_mode": "tablet",
            }
    return None


def yt_control(method):
    with _yt_lock:
        mode = _yt_state.get("mode")
        q = _yt_state.get("queue") or []
        if not mode or not q:
            return {"player": None}
        if mode == "pc_audio":
            if method == "PlayPause":
                _mpv_ipc(["cycle", "pause"])
                _yt_state["paused"] = not _yt_state["paused"]
            elif method == "Next":
                _mpv_ipc(["playlist-next", "weak"])
                _yt_state["idx"] = (_yt_state["idx"] + 1) % len(q)
                _yt_state["paused"] = False
            elif method == "Previous":
                _mpv_ipc(["playlist-prev", "weak"])
                _yt_state["idx"] = (_yt_state["idx"] - 1) % len(q)
                _yt_state["paused"] = False
            elif method == "Stop":
                pass
        elif mode == "tablet":
            if method == "PlayPause":
                _yt_state["paused"] = not _yt_state["paused"]
            elif method == "Next":
                _yt_state["idx"] = (_yt_state["idx"] + 1) % len(q)
                _yt_state["paused"] = False
            elif method == "Previous":
                _yt_state["idx"] = (_yt_state["idx"] - 1) % len(q)
                _yt_state["paused"] = False
    if method == "Stop":
        yt_stop()
        return {"player": None}
    time.sleep(0.12)
    return media_now()


def yt_stream_url(vid):
    """Resolve URL direta de áudio do YouTube para transcodificação PCM ao vivo pro tablet."""
    if not YT_ID_RE.match(vid or ""):
        return ""
    cmd = ["yt-dlp", "--no-update", "-f", "bestaudio/best", "--get-url", f"https://www.youtube.com/watch?v={vid}"]
    node = _node_bin()
    if node:
        cmd[2:2] = ["--js-runtimes", f"node:{node}"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=14)
        for line in (r.stdout or "").splitlines():
            if line.strip().startswith("http"):
                return line.strip()
    except Exception:
        pass
    return ""
