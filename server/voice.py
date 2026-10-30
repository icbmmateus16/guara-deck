"""Voz do Guará: ouvir (Whisper na GPU), falar (Neural com prosódia dinâmica + Piper offline) e conversar.

O Whisper ocupa ~3 GB de VRAM, então só carrega quando você toca no microfone
e é descarregado depois de alguns minutos sem uso.
"""

import array
import asyncio
import io
import random
import re
import subprocess
import sys
import threading
import time
import uuid
import wave
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
for _sp in (ROOT_DIR / ".venv/lib").glob("python*/site-packages"):
    if str(_sp) not in sys.path:
        sys.path.insert(0, str(_sp))

try:
    import edge_tts  # type: ignore
except Exception:
    edge_tts = None

PIPER_DIR = Path.home() / ".local/share/piper"
EDGE_TTS_BIN = ROOT_DIR / ".venv/bin/edge-tts"

# Vozes do Guará: as neurais usam prosódia dinâmica por frase + masterização de áudio (EQ quente e compressor);
# se o PC estiver sem internet, cai automaticamente para o Piper local.
VOICES = [
    {
        "id": "edge:guara-agente",
        "name": "Guará Agente",
        "desc": "personagem · grave de bicho grande com brilho de IA · neural",
        "backend": "edge",
        "voice": "pt-BR-AntonioNeural",
        "pitch": 0,
        "rate": 7,
        "eq": "agente",
    },
    {
        "id": "edge:guara-desenho",
        "name": "Guará Desenho",
        "desc": "personagem · mais agudo e expressivo, de desenho animado · neural",
        "backend": "edge",
        "voice": "pt-BR-AntonioNeural",
        "pitch": 0,
        "rate": 10,
        "eq": "desenho",
    },
    {
        "id": "edge:guara-fera",
        "name": "Guará Fera",
        "desc": "personagem · mais grave e encorpado, mais bicho · neural",
        "backend": "edge",
        "voice": "pt-BR-AntonioNeural",
        "pitch": 0,
        "rate": 6,
        "eq": "fera",
    },
    {
        "id": "edge:guara-sintetico",
        "name": "Guará Sintético",
        "desc": "personagem · timbre de agente de IA, metálico leve · neural",
        "backend": "edge",
        "voice": "pt-BR-AntonioNeural",
        "pitch": 0,
        "rate": 8,
        "eq": "sintetico",
    },
    {
        "id": "edge:guara",
        "name": "Guará",
        "desc": "oficial · grave suave, ágil e expressiva · neural",
        "backend": "edge",
        "voice": "pt-BR-AntonioNeural",
        "pitch": -5,
        "rate": 8,
        "eq": "guara",
    },
    {
        "id": "edge:noturno",
        "name": "Noturno",
        "desc": "conversacional · entonação super natural · neural",
        "backend": "edge",
        "voice": "en-US-AndrewMultilingualNeural",
        "pitch": -3,
        "rate": 5,
        "eq": "warm",
    },
    {
        "id": "edge:cerrado",
        "name": "Cerrado",
        "desc": "descontraída · jovem e parceira · neural",
        "backend": "edge",
        "voice": "en-US-BrianMultilingualNeural",
        "pitch": -2,
        "rate": 6,
        "eq": "warm",
    },
    {
        "id": "edge:pt-BR-AntonioNeural",
        "name": "Antônio",
        "desc": "masculina clara · pt-BR · neural",
        "backend": "edge",
        "voice": "pt-BR-AntonioNeural",
        "pitch": -1,
        "rate": 4,
        "eq": "clean",
    },
    {
        "id": "edge:pt-BR-ThalitaMultilingualNeural",
        "name": "Thalita",
        "desc": "feminina expressiva · multilíngue · neural",
        "backend": "edge",
        "voice": "pt-BR-ThalitaMultilingualNeural",
        "pitch": 0,
        "rate": 5,
        "eq": "clean",
    },
    {
        "id": "edge:pt-BR-FranciscaNeural",
        "name": "Francisca",
        "desc": "feminina suave · pt-BR · neural",
        "backend": "edge",
        "voice": "pt-BR-FranciscaNeural",
        "pitch": 0,
        "rate": 4,
        "eq": "clean",
    },
    {
        "id": "piper:pt_BR-cadu-medium",
        "name": "Cadu",
        "desc": "masculina local · funciona sem internet",
        "backend": "piper",
        "model": "pt_BR-cadu-medium",
        "eq": "warm",
    },
    {
        "id": "piper:pt_BR-faber-medium",
        "name": "Faber",
        "desc": "reserva local · funciona sem internet",
        "backend": "piper",
        "model": "pt_BR-faber-medium",
        "eq": "warm",
    },
]
VOICE_BY_ID = {v["id"]: v for v in VOICES}
DEFAULT_VOICE = "edge:guara"
OFFLINE_FALLBACK = "pt_BR-cadu-medium"
WHISPER_MODEL = "large-v3-turbo"
STT_IDLE_UNLOAD = 600     # libera a GPU depois de 10 min sem ouvir nada
ENV_FRAME = 0.06          # envelope da boca: um valor a cada 60 ms
SAMPLE_RATE = 24000
# Frases que o Whisper "inventa" quando o áudio é só ruído.
HALLUCINATIONS = ("amara.org", "legendas pela comunidade", "obrigado por assistir", "inscreva-se", "subtitles by")

# Cadeias de masterização FFmpeg pensadas para o alto-falante do tablet:
# tira graves embolados (<85 Hz), dá corpo de peito (~180 Hz), presença clara (~3.2 kHz) e nivela o volume.
EQ_CHAINS = {
    "guara": (
        "highpass=f=85,"
        "equalizer=f=180:t=q:w=1.1:g=3.4,"
        "equalizer=f=430:t=q:w=1.4:g=-1.6,"
        "equalizer=f=3200:t=q:w=1.3:g=2.2,"
        "acompressor=threshold=-18dB:ratio=2.4:attack=10:release=130:makeup=2.2dB,"
        "alimiter=limit=0.95"
    ),
    "warm": (
        "highpass=f=85,"
        "equalizer=f=190:t=q:w=1.2:g=2.4,"
        "equalizer=f=3300:t=q:w=1.4:g=1.8,"
        "acompressor=threshold=-18dB:ratio=2.2:attack=12:release=140:makeup=2.0dB,"
        "alimiter=limit=0.95"
    ),
    # Vozes de personagem: o rubberband abaixa o tom junto com os formantes (soa como um corpo maior, de bicho),
    # uma sombra uma oitava abaixo dá peito, e um eco curtíssimo (5-8 ms) dá o brilho metálico de "visor" de IA.
    "agente": (
        "rubberband=pitch=0.92:formant=shifted,asplit=2[v][s];"
        "[s]rubberband=pitch=0.5:formant=shifted,lowpass=f=700,volume=0.22[sub];"
        "[v][sub]amix=inputs=2:normalize=0,"
        "aecho=0.9:0.7:7:0.16,volume=1.5,"
        "highpass=f=70,equalizer=f=170:t=q:w=1.1:g=2.6,equalizer=f=430:t=q:w=1.4:g=-1.8,equalizer=f=3000:t=q:w=1.3:g=2.6,acompressor=threshold=-18dB:ratio=2.6:attack=8:release=120:makeup=2.4dB,alimiter=limit=0.95"
    ),
    "fera": (
        "rubberband=pitch=0.86:formant=shifted,asplit=2[v][s];"
        "[s]rubberband=pitch=0.5:formant=shifted,lowpass=f=600,volume=0.32[sub];"
        "[v][sub]amix=inputs=2:normalize=0,"
        "aecho=0.9:0.6:9:0.1,volume=1.5,"
        "highpass=f=70,equalizer=f=170:t=q:w=1.1:g=2.6,equalizer=f=430:t=q:w=1.4:g=-1.8,equalizer=f=3000:t=q:w=1.3:g=2.6,acompressor=threshold=-18dB:ratio=2.6:attack=8:release=120:makeup=2.4dB,alimiter=limit=0.95"
    ),
    "sintetico": (
        "rubberband=pitch=0.94:formant=shifted,asplit=2[v][s];"
        "[s]rubberband=pitch=0.5:formant=shifted,lowpass=f=800,volume=0.14[sub];"
        "[v][sub]amix=inputs=2:normalize=0,"
        "aecho=0.9:0.8:5:0.3,chorus=0.8:0.9:18:0.22:0.4:1.6,volume=1.5,"
        "highpass=f=70,equalizer=f=170:t=q:w=1.1:g=2.6,equalizer=f=430:t=q:w=1.4:g=-1.8,equalizer=f=3000:t=q:w=1.3:g=2.6,acompressor=threshold=-18dB:ratio=2.6:attack=8:release=120:makeup=2.4dB,alimiter=limit=0.95"
    ),
    # Personagem de desenho: tom e formantes um pouco acima (corpo menor, mais expressivo), brilho de IA leve
    "desenho": (
        "rubberband=pitch=1.14:formant=shifted,"
        "aecho=0.9:0.8:5:0.18,volume=1.3,"
        "highpass=f=90,equalizer=f=2600:t=q:w=1.3:g=2.4,equalizer=f=6000:t=q:w=1.5:g=1.2,"
        "acompressor=threshold=-18dB:ratio=2.6:attack=8:release=120:makeup=2.4dB,alimiter=limit=0.95"
    ),
    "clean": (
        "highpass=f=80,"
        "equalizer=f=3200:t=q:w=1.4:g=1.4,"
        "acompressor=threshold=-19dB:ratio=2.0:attack=12:release=140:makeup=1.8dB,"
        "alimiter=limit=0.95"
    ),
}

VOICE_SAMPLES = {
    "edge:guara-agente": "Opa! Aqui é o Guará. Tô de olho nos seus agentes e no PC. Bora construir alguma coisa boa hoje?",
    "edge:guara-desenho": "Opa! Aqui é o Guará. Tô de olho nos seus agentes e no PC. Bora construir alguma coisa boa hoje?",
    "edge:guara-fera": "Opa! Aqui é o Guará. Tô de olho nos seus agentes e no PC. Bora construir alguma coisa boa hoje?",
    "edge:guara-sintetico": "Opa! Aqui é o Guará. Tô de olho nos seus agentes e no PC. Bora construir alguma coisa boa hoje?",
    "edge:guara": "Opa! Aqui é o Guará, de orelha em pé vigiando o cerrado. Bora construir alguma coisa boa hoje?",
    "edge:noturno": "Fala, parceiro! Tô de olho nos seus projetos e nos agentes aqui no PC. Precisando, é só chamar!",
    "edge:cerrado": "E aí, beleza? Tudo tranquilo por aqui! Só tocar no microfone que a gente troca uma ideia.",
    "edge:pt-BR-AntonioNeural": "Oi! Agora eu falo com a voz do Antônio, clara e direta. O que você achou?",
    "edge:pt-BR-ThalitaMultilingualNeural": "Oi! Agora eu tô falando com a voz da Thalita, bem expressiva e natural. Gostou?",
    "edge:pt-BR-FranciscaNeural": "Oi! Agora eu falo com a voz da Francisca, suave e tranquila. Ficou boa assim?",
}

POKE_VOICE_LINES = [
    "Opa! Tô acordado aqui no cerrado, de orelha em pé!",
    "Hehe, valeu pelo carinho! Se precisar de ajuda no código, é só falar.",
    "Tô de olho em tudo por aqui, parceiro. Pode mandar ver!",
    "Auuu… quer dizer, opa! Tudo tranquilo na noite do cerrado!",
    "Firme e forte por aqui! Quer que eu dê uma olhada em algum projeto?",
]

VOICE_PROMPT = (
    "Você é o Guará, parceiro de código do desenvolvedor: um lobo-guará esperto, leal, observador e "
    "bem-humorado na medida certa, que vive num painel na mesa dele num cenário de noite no cerrado. "
    "Sua resposta será FALADA em voz alta por uma voz neural expressiva: escreva exatamente como "
    "alguém conversa em português do Brasil falado, com ritmo natural, fluido e vivo. "
    "Use contrações naturais quando couber (tô, tá, pra, beleza, olha só, deixa eu ver, prontinho!) "
    "e capriche na pontuação oral — vírgulas para dar pausa de respiração, exclamação quando algo for "
    "positivo, interrogação direta quando perguntar. Responda em 1 a 3 frases curtas e conversacionais, "
    "sem markdown, listas, emojis, blocos de código nem caminhos longos. Se precisar consultar algo no "
    "PC, consulte e conte o resultado de um jeito natural, como um parceiro sentado ao lado. "
    "Nunca altere, mova nem apague arquivos a menos que o pedido diga isso explicitamente."
)

# Adaptações fonéticas só para o sintetizador soar 100% natural em termos técnicos em pt-BR.
_SPEECH_SUBS = [
    (re.compile(r"(?:~|/\w+)/[\w./-]+/([\w.-]+)"), r"\1"),          # /caminho/longo/app.py -> app.py
    (re.compile(r"\b(\d+)\s*h\b", re.I), r"\1 horas"),
    (re.compile(r"\b(\d+)\s*min\b", re.I), r"\1 minutos"),
    (re.compile(r"\b(\d+)\s*s\b"), r"\1 segundos"),
    (re.compile(r"\b(\d+(?:[.,]\d+)?)\s*GB\b", re.I), r"\1 gigas"),
    (re.compile(r"\b(\d+(?:[.,]\d+)?)\s*MB/s\b", re.I), r"\1 megas por segundo"),
    (re.compile(r"\b(\d+(?:[.,]\d+)?)\s*KB/s\b", re.I), r"\1 kilobytes por segundo"),
    (re.compile(r"\bCPU\b"), "cê-pê-u"),
    (re.compile(r"\bGPU\b"), "gê-pê-u"),
    (re.compile(r"\bVRAM\b", re.I), "vê-ram"),
    (re.compile(r"\bRAM\b"), "memória ram"),
    (re.compile(r"\bAPI\b"), "a-pê-i"),
    (re.compile(r"\bURL\b"), "u-érre-éle"),
    (re.compile(r"\bSSH\b"), "ésse-ésse-agá"),
    (re.compile(r"\bCLI\b"), "linha de comando"),
    (re.compile(r"\bPRs?\b"), "pull request"),
    (re.compile(r"\bpt[-_]BR\b", re.I), "português"),
    (re.compile(r"\b([\w-]+)\.(py|js|ts|tsx|json|md|css|html|sh)\b"), r"\1 ponto \2"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*°C"), r"\1 graus"),
    (re.compile(r"(?<=[A-Za-zÀ-ú])/(?=[A-Za-zÀ-ú])"), " ou "),       # Claude/Codex -> Claude ou Codex
]

# A voz é brasileira e lê inglês com fonética de português ("Cláu-de", "dê-ploi"). Aqui cada termo de dev
# vem escrito como um brasileiro fala no dia a dia. Os mais longos primeiro (Claude Code antes de Claude).
_PRONOUNCE = [
    ("Claude Code", "Clóde Côud"), ("VS Code", "vê-ésse Côud"), ("ChatGPT", "Chat gê-pê-tê"), ("GitHub", "Guít-rãb"),
    ("Claude", "Clóde"), ("Codex", "Códex"), ("GPT", "gê-pê-tê"), ("Gemini", "Djêmini"), ("Antigravity", "Anti-grávity"),
    ("Firefox", "Fáier-fóx"), ("Docker", "Dóquer"), ("YouTube", "Iú-túbi"), ("Wi-Fi", "uái-fái"), ("Bluetooth", "Blú-túf"),
    ("Python", "Páiton"), ("JavaScript", "Djava-scrípt"), ("TypeScript", "Taipe-scrípt"), ("Node", "Nôude"),
    ("React", "Riéct"), ("Supabase", "Súpa-bêis"), ("Ollama", "Olâma"), ("localhost", "lôcal-rôst"), ("npm", "ene-pê-ême"),
    ("deploy", "diplói"), ("run", "rân"), ("commits", "comítis"), ("commit", "comíti"), ("push", "púche"), ("pull", "púl"),
    ("merge", "mêrdji"), ("build", "bíldi"), ("branch", "brântch"), ("bugs", "bâgues"), ("bug", "bâgui"),
    ("frontend", "front-ênd"), ("backend", "béc-ênd"), ("hooks", "rúques"), ("hook", "rúqui"), ("prompt", "prômpti"),
    ("tokens", "tôquens"), ("token", "tôquen"), ("debug", "di-bâgui"), ("online", "on-láin"), ("offline", "óf-láin"),
    ("ok", "oquêi"), ("OK", "oquêi"), ("app", "ép"), ("apps", "éps"), ("web", "uéb"), ("site", "sáiti"),
]
_PRONOUNCE_RE = [(re.compile(r"(?<![\w-])" + re.escape(a) + r"(?![\w-])", 0 if a.isupper() or a == "ok" else re.I), b)
                 for a, b in _PRONOUNCE]
_ACRONYMS = {"CPU", "GPU", "RAM", "VRAM", "API", "URL", "SSH", "CLI", "HTTP", "JSON", "HTML", "SQL", "USB", "HDMI", "PC", "IA", "GPT", "VS"}
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]+")


def speakable(text, limit=440):
    """Limpa o texto para exibir no balão e falar: tira markdown, links e corta em frase completa."""
    text = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    text = re.sub(r"https?://\S+", "um link", text)
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.M)
    text = re.sub(r"\n+", " ", text)
    text = re.sub(r"[*_`#>|\[\]]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind("… "))
    return cut[: end + 1] if end > 80 else cut.rsplit(" ", 1)[0] + "…"


def for_speech(text):
    """Ajusta siglas, unidades e caminhos para o TTS pronunciar com naturalidade."""
    out = _EMOJI.sub(" ", text)
    # NOMES EM CAIXA ALTA (pastas, projetos) seriam soletrados: viram "Meu Portfólio"; siglas conhecidas ficam
    out = re.sub(r"\b[A-ZÀ-Ú]{2,}(?:\s+[A-ZÀ-Ú]{2,})+\b|\b[A-ZÀ-Ú]{4,}\b",
                 lambda m: " ".join(w if w in _ACRONYMS else w.capitalize() for w in m.group(0).split()), out)
    for pat, rep in _SPEECH_SUBS:
        out = pat.sub(rep, out)
    for pat, rep in _PRONOUNCE_RE:
        out = pat.sub(rep, out)
    out = out.replace(" — ", ", ").replace(" – ", ", ").replace(" · ", ", ")
    out = re.sub(r"\s*\(([^)]*)\)", r", \1,", out)              # (comentário) vira uma pausa natural
    out = re.sub(r",\s*([.!?])", r"\1", out)
    return re.sub(r"\s+", " ", out).strip()


def _fmt_hz(v):
    return f"{v:+d}Hz"


def _fmt_pct(v):
    return f"{v:+d}%"


def _trim_pcm_s16(pcm_bytes, rate=SAMPLE_RATE, lead_ms=40, trail_ms=130, thresh=180):
    """Remove o silêncio exagerado (~0.8 s) que o TTS deixa nas pontas, mantendo pausa de respiração natural."""
    samples = array.array("h")
    samples.frombytes(pcm_bytes[: len(pcm_bytes) - (len(pcm_bytes) % 2)])
    if not samples:
        return pcm_bytes
    n = len(samples)
    first = 0
    while first < n and abs(samples[first]) < thresh:
        first += 1
    if first >= n:
        return b""
    last = n - 1
    while last > first and abs(samples[last]) < thresh:
        last -= 1
    start = max(0, first - int(rate * lead_ms / 1000))
    end = min(n, last + int(rate * trail_ms / 1000))
    return samples[start:end].tobytes()


def _pcm_to_wav(pcm_bytes, rate=SAMPLE_RATE):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm_bytes)
    return buf.getvalue()


def _master_pcm(pcm_in, in_rate, eq_name="guara"):
    """Passa o áudio cru por EQ + compressor suave e devolve WAV 24 kHz mono canônico."""
    af = EQ_CHAINS.get(eq_name, EQ_CHAINS["warm"])
    try:
        p = subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "s16le", "-ar", str(in_rate), "-ac", "1", "-i", "pipe:0",
                "-af", af,
                "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1",
            ],
            input=pcm_in, capture_output=True, timeout=15, check=True,
        )
        if p.stdout:
            return _pcm_to_wav(p.stdout, SAMPLE_RATE)
    except Exception:
        pass
    return _pcm_to_wav(pcm_in, in_rate)


class Voice:
    def __init__(self, hub, agent, config):
        self.hub = hub
        self.agent = agent
        self.config = config
        self.enabled = bool(config.get("voice_enabled", True))
        saved = config.get("voice")
        self.voice_id = saved if saved in VOICE_BY_ID else DEFAULT_VOICE
        self.clips = {}
        self._tts = {}
        self._stt = None
        self._stt_used = 0.0
        self._tts_lock = threading.Lock()
        self._stt_lock = threading.Lock()
        self.conversation = None     # {"engine", "id"}: conversa em andamento (para lembrar o contexto)
        self.conversation_at = 0.0
        threading.Thread(target=self._warm_voices, daemon=True).start()
        threading.Thread(target=self._unload_idle, daemon=True).start()

    # ------------------------------------------------------------ falar

    def _warm_voices(self):
        if self.voice_id.startswith("piper:"):
            self._load_tts(self.voice_id.split(":", 1)[1])

    def _load_tts(self, model=None):
        profile = VOICE_BY_ID.get(self.voice_id) or {}
        model = model or profile.get("model") or OFFLINE_FALLBACK
        with self._tts_lock:
            for candidate in (model, "pt_BR-faber-medium"):
                path = PIPER_DIR / f"{candidate}.onnx"
                if candidate in self._tts:
                    return self._tts[candidate]
                if path.exists():
                    from piper import PiperVoice
                    self._tts[candidate] = PiperVoice.load(str(path))
                    return self._tts[candidate]
            return None

    def voices(self):
        return {
            "current": self.voice_id,
            "list": [{"id": v["id"], "name": v["name"], "desc": v["desc"]} for v in VOICES],
        }

    def set_voice(self, vid):
        if vid not in VOICE_BY_ID:
            raise ValueError("voz desconhecida")
        self.voice_id = vid
        if vid.startswith("piper:"):
            threading.Thread(target=self._load_tts, daemon=True).start()
        name = VOICE_BY_ID[vid]["name"]
        sample = VOICE_SAMPLES.get(vid, f"Oi! Agora eu falo com a voz {name}. Me diz o que achou da entonação!")
        self.say_async(sample, "reply")

    def _synth_edge(self, text, profile):
        """Uma chamada só para o texto inteiro: a voz neural entoa o parágrafo como um todo, com as pausas
        naturais entre as frases (sintetizar frase por frase e colar soava como leituras soltas)."""
        if not text:
            return None
        vname, pitch, rate = profile["voice"], _fmt_hz(profile.get("pitch", 0)), _fmt_pct(profile.get("rate", 4))
        if edge_tts is not None:
            async def _fetch():
                buf = bytearray()
                async for ch in edge_tts.Communicate(text, voice=vname, pitch=pitch, rate=rate).stream():
                    if ch["type"] == "audio":
                        buf.extend(ch["data"])
                return bytes(buf)

            mp3_parts = [asyncio.run(_fetch())]
        elif EDGE_TTS_BIN.exists():
            res = subprocess.run(
                [str(EDGE_TTS_BIN), "--voice", vname, f"--pitch={pitch}", f"--rate={rate}", "--text", text, "--write-media", "/dev/stdout"],
                capture_output=True, timeout=22, check=True,
            )
            mp3_parts = [res.stdout]
        else:
            return None

        pcm_chunks = []
        for idx, mp3 in enumerate(mp3_parts):
            if not mp3:
                continue
            dec = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-f", "mp3", "-i", "pipe:0",
                 "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1"],
                input=mp3, capture_output=True, timeout=12, check=True,
            )
            trimmed = _trim_pcm_s16(
                dec.stdout,
                rate=SAMPLE_RATE,
                lead_ms=35 if idx == 0 else 45,
                trail_ms=135 if idx < len(mp3_parts) - 1 else 160,
            )
            if trimmed:
                pcm_chunks.append(trimmed)
        if not pcm_chunks:
            return None
        return _master_pcm(b"".join(pcm_chunks), SAMPLE_RATE, profile.get("eq", "guara"))

    def _synth_piper(self, text, profile=None):
        model_name = (profile or {}).get("model")
        tts = self._load_tts(model_name)
        if tts is None:
            return None
        buf = io.BytesIO()
        syn_cfg = None
        try:
            from piper.config import SynthesisConfig
            syn_cfg = SynthesisConfig(length_scale=0.95, noise_scale=0.76, noise_w_scale=0.86)
        except Exception:
            pass
        with self._tts_lock, wave.open(buf, "wb") as w:
            if syn_cfg is not None:
                tts.synthesize_wav(text, w, syn_config=syn_cfg)
            else:
                tts.synthesize_wav(text, w)
        with wave.open(io.BytesIO(buf.getvalue())) as r:
            raw_pcm = r.readframes(r.getnframes())
            in_rate = r.getframerate()
        return _master_pcm(raw_pcm, in_rate, (profile or {}).get("eq", "warm"))

    def _synth(self, text):
        """Gera o WAV na voz escolhida; se a voz neural falhar (sem internet), cai para o Piper local."""
        speech = for_speech(text)
        profile = VOICE_BY_ID.get(self.voice_id) or VOICE_BY_ID[DEFAULT_VOICE]
        if profile.get("backend") == "edge":
            try:
                wav_bytes = self._synth_edge(speech, profile)
                if wav_bytes:
                    return wav_bytes
            except Exception:
                pass
        return self._synth_piper(speech, profile if profile.get("backend") == "piper" else None)

    def say(self, text, kind="reply"):
        """Sintetiza e manda o áudio para o tablet tocar (com o envelope da boca)."""
        clean = speakable(text)
        if not clean or (not self.enabled and kind != "reply"):
            return
        data = self._synth(clean)
        if not data:
            return
        cid = uuid.uuid4().hex[:10]
        self.clips[cid] = data
        if len(self.clips) > 14:
            self.clips.pop(next(iter(self.clips)))
        env, dur = envelope(data)
        self.hub.broadcast("say", {"id": cid, "text": clean, "env": env, "dur": dur, "kind": kind})
        self.hub.broadcast("attention", {"reason": "say"})

    def say_async(self, text, kind="notify"):
        threading.Thread(target=self.say, args=(text, kind), daemon=True).start()

    def say_poke(self):
        self.say_async(random.choice(POKE_VOICE_LINES), "reply")

    # ------------------------------------------------------------ ouvir

    def warm(self):
        """Começa a carregar o Whisper enquanto você ainda está falando."""
        threading.Thread(target=self._load_stt, daemon=True).start()

    def _load_stt(self):
        with self._stt_lock:
            self._stt_used = time.time()
            if self._stt is None:
                import whisper
                self._stt = whisper.load_model(WHISPER_MODEL, device="cuda")
            return self._stt

    def _unload_idle(self):
        while True:
            time.sleep(30)
            if self._stt is not None and time.time() - self._stt_used > STT_IDLE_UNLOAD:
                with self._stt_lock:
                    self._stt = None
                    import torch
                    torch.cuda.empty_cache()

    def hear(self, wav_bytes):
        threading.Thread(target=self._hear, args=(wav_bytes,), daemon=True).start()

    def _hear(self, wav_bytes):
        self.hub.broadcast("heard", {"state": "transcrevendo"})
        path = Path(f"/tmp/capi_ouvido_{uuid.uuid4().hex[:6]}.wav")
        try:
            path.write_bytes(wav_bytes)
            model = self._load_stt()
            result = model.transcribe(str(path), language="pt", fp16=True, condition_on_previous_text=False)
            text = (result.get("text") or "").strip()
        except Exception as e:
            self.hub.broadcast("heard", {"state": "erro", "text": str(e)[:120]})
            return
        finally:
            path.unlink(missing_ok=True)
            self._stt_used = time.time()
        if len(text) < 2 or any(h in text.lower() for h in HALLUCINATIONS):
            self.hub.broadcast("heard", {"state": "vazio"})
            self.say("Hmm, não peguei direito o que você falou. Pode repetir?", "reply")
            return
        self.hub.broadcast("heard", {"state": "ok", "text": text})
        self.agent.log("voice", f"Você: {text}")
        self.converse(text)

    # ------------------------------------------------------------ conversar

    def converse(self, text):
        keep = self.config.get("voice_session_minutes", 10) * 60
        resume = self.conversation if time.time() - self.conversation_at < keep else None
        ok, info = self.agent.mission_start(
            text, "Conversa", tools=self.config.get("mission_tools"), voice=True, resume=resume,
            system_prompt=VOICE_PROMPT, model=self.config.get("voice_model"),
        )
        if not ok:
            self.say(f"Calma aí, {info.lower()}.", "reply")
        return ok, info

    def on_mission_done(self, m):
        """Chamado pelo Agent quando uma missão termina."""
        if m.get("voice"):
            if m.get("session"):
                self.conversation = {"engine": m["engine"], "id": m["session"]}
                self.conversation_at = time.time()
            self.say(m["text"] or "Prontinho, tudo resolvido!", "reply")
        elif m["status"] == "done":
            self.say_async(f"Olha só, terminei a missão {m['title']}! {m['text']}", "notify")

    # ------------------------------------------------------------ avisos falados

    def on_stop(self, project, summary, turn_seconds, pc_idle_ms):
        """Fala o fim de uma tarefa só se foi longa ou se você saiu de perto do PC."""
        if turn_seconds > 45 or pc_idle_ms > 60_000:
            first = re.split(r"(?<=[.!?])\s", speakable(summary, 200))[0] if summary else ""
            self.say_async(f"Opa, prontinho! Terminei lá no {project}. {first}")

    def on_permission(self, tool, project, pc_idle_ms):
        if pc_idle_ms > 20_000:
            what = "rodar um comando" if tool == "Bash" else f"usar {tool}"
            self.say_async(f"Ei, dá uma olhada aqui! Preciso da sua aprovação pra {what} no {project}.")


def envelope(wav_bytes):
    """Volume perceptual da fala a cada 60 ms (0 a 9): abre a boca do Guará no ritmo das sílabas."""
    with wave.open(io.BytesIO(wav_bytes)) as w:
        rate = w.getframerate()
        samples = array.array("h", w.readframes(w.getnframes()))
    step = max(1, int(rate * ENV_FRAME))
    levels = []
    for i in range(0, len(samples), step):
        chunk = samples[i : i + step]
        if not chunk:
            break
        rms = (sum(s * s for s in chunk) / len(chunk)) ** 0.5
        levels.append(rms)
    peak = max(levels) or 1
    out = []
    for v in levels:
        norm = v / peak
        out.append(0 if norm < 0.06 else min(9, max(1, round((norm ** 0.65) * 9))))
    return out, round(len(samples) / rate, 2)
