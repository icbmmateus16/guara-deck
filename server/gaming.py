"""Detecta jogos Steam/Proton sem confundir launchers com o jogo em execução."""

import os
from pathlib import Path

import psutil


HELPERS = {
    "steam", "steam.exe", "steamwebhelper", "steamwebhelper.exe", "steamservice.exe", "steamerrorreporter",
    "gameoverlayui", "gameoverlayui.exe", "steam-runtime-launcher-interface-0",
    "eadesktop.exe", "eabackgroundservice.exe", "ealocalhostsvc.exe",
    "easteamauthhelper.exe", "tabtip.exe", "pv-adverb",
    "easteamlauncher.exe", "ealauncher.exe", "origin.exe", "originwebhelperservice.exe",
    "epicgameslauncher.exe", "epicwebhelper.exe", "galaxyclient.exe", "galaxyclientservice.exe",
    "ubisoftconnect.exe", "upc.exe", "uplaywebcore.exe", "battle.net.exe", "agent.exe",
    "services.exe", "explorer.exe", "winedevice.exe", "plugplay.exe", "rpcss.exe",
    "svchost.exe", "conhost.exe", "start.exe", "cmd.exe", "rundll32.exe",
    "crashreportclient.exe", "crashpad_handler", "crashpad_handler.exe", "werfault.exe",
    "d3ddriverquery", "d3ddriverquery64", "d3ddriverquery.exe", "d3ddriverquery64.exe",
    "fossilize_replay", "vulkandriverquery", "igoproxy32.exe", "igoproxy64.exe",
    "igoproxy32", "igoproxy64",
    "steamclient_loader", "xalia.exe", "srt-bwrap", "bwrap", "reaper",
    "unitycrashhandler64.exe", "unitycrashhandler32.exe", "unrealcefsubprocess.exe",
    "crashhandler", "crashhandler64", "launcher.exe", "launch.exe", "msedgewebview2.exe",
    "proton", "bash", "sh", "dash", "env", "timeout", "gamemoderun",
}


def basename(value):
    return str(value or "").replace("\\", "/").rsplit("/", 1)[-1].casefold()


def game_name(info, env, configured=()):
    """Retorna o nome do jogo ou None. Só considera o programa, nunca argumentos de um launcher."""
    cmd = info.get("cmdline") or []
    program = cmd[0] if cmd else info.get("exe") or info.get("name") or ""
    name = basename(program)
    comm = basename(info.get("name"))
    if info.get("status") == psutil.STATUS_ZOMBIE:
        return None
    # Correspondências explícitas permitem também jogos fora da Steam.
    if name in configured or comm in configured:
        return Path(name).stem
    if (name in HELPERS or comm in HELPERS or name.startswith(("wine", "steam-runtime", "pressure-vessel"))
            or name.startswith(("python", "python3")) and len(cmd) > 1 and basename(cmd[1]) == "proton"):
        return None
    program_path = str(program).replace("\\", "/")
    # Serviços de um launcher herdam SteamGameId: isso sozinho não indica jogo.
    if any(part in program_path.casefold() for part in (
            ":/windows/", "/electronic arts/ea desktop/", "/epic games/launcher/",
            "/ubisoft game launcher/")):
        return None
    paths = [program_path, str(info.get("exe") or "").replace("\\", "/")]
    steam_id = env.get("SteamGameId") or env.get("SteamAppId") or env.get("STEAM_COMPAT_APP_ID") or ""
    if steam_id.isdigit() and int(steam_id) > 0:
        paths.append(str(info.get("cwd") or "").replace("\\", "/"))
    game_path = None
    for path in paths:
        if "/steamapps/common/" in path.casefold():
            index = path.casefold().index("/steamapps/common/") + len("/steamapps/common/")
            folder = path[index:].split("/", 1)[0]
            if folder.casefold().startswith(("proton", "steam", "scout", "soldier", "sniper")):
                continue
            game_path = folder
            break
    return game_path or None


class GameDetector:
    def __init__(self, configured=()):
        self.configured = {basename(s) for s in configured}
        self.uid = os.getuid()

    def scan(self):
        games = set()
        for proc in psutil.process_iter(["pid", "name", "exe", "cmdline", "cwd", "status", "uids"]):
            try:
                info = proc.info
                if info.get("uids") and info["uids"].real != self.uid:
                    continue
                # Não lê o ambiente dos auxiliares mais comuns.
                cmd = info.get("cmdline") or []
                name = basename(cmd[0] if cmd else info.get("name"))
                if name in HELPERS and name not in self.configured:
                    continue
                try:
                    env = proc.environ()
                except psutil.AccessDenied:
                    env = {}
                game = game_name(info, env, self.configured)
                if game:
                    games.add(game)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return sorted(games)
