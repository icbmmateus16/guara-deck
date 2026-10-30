"""Tempo e luz do dia para o cenário do Guará: Open-Meteo (sem chave de API).

O tablet recebe só o essencial para pintar o céu: nascer e pôr do sol, nuvens, chuva (fraca/forte) e trovoada.
Fica em cache no disco: sem internet, o cenário segue com o último tempo conhecido e o sol calculado na hora.
"""
import json
import time
import urllib.request
from pathlib import Path

CACHE = Path.home() / ".cache" / "guara" / "weather.json"
DEFAULT = {"lat": -16.6869, "lon": -49.2648, "city": "Goiânia"}
URL = ("https://api.open-meteo.com/v1/forecast?latitude={lat:.4f}&longitude={lon:.4f}"
       "&current=temperature_2m,weather_code,precipitation,cloud_cover"
       "&daily=sunrise,sunset&timezone=auto&forecast_days=1")
HEAVY = {63, 65, 66, 67, 81, 82, 95, 96, 99}


def _minutes(iso):
    """'2026-10-30T05:41' vira 341."""
    t = iso.split("T")[-1]
    return int(t[:2]) * 60 + int(t[3:5])


def fetch(cfg):
    lat, lon = cfg.get("lat", DEFAULT["lat"]), cfg.get("lon", DEFAULT["lon"])
    with urllib.request.urlopen(URL.format(lat=lat, lon=lon), timeout=15) as r:
        raw = json.load(r)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"at": time.time(), "raw": raw}))
    return view(raw)


def cached():
    try:
        return view(json.loads(CACHE.read_text())["raw"])
    except (OSError, ValueError, KeyError):
        return None


def view(raw):
    cur, daily = raw.get("current", {}), raw.get("daily", {})
    code = int(cur.get("weather_code") or 0)
    precip = float(cur.get("precipitation") or 0)
    cloud = int(cur.get("cloud_cover") or 0)
    raining = (51 <= code <= 67) or (80 <= code <= 82) or code >= 95 or precip >= 0.2
    # A garoa mais fraca do modelo (51, abaixo de 0,2 mm) é, na prática, céu nublado.
    if code == 51 and precip < 0.2:
        raining = False
    rain = 0 if not raining else (2 if code in HEAVY or precip >= 2.5 else 1)
    rise = daily.get("sunrise") or ["T06:00"]
    sset = daily.get("sunset") or ["T18:00"]
    return {
        "rise": _minutes(rise[0]), "set": _minutes(sset[0]),
        "cloud": cloud, "rain": rain, "storm": code >= 95,
        "overcast": code in (3, 45, 48) or cloud >= 85,
        "fog": code in (45, 48),
        "temp": cur.get("temperature_2m"), "code": code,
    }
