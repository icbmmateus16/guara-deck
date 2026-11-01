"""Voz do Guará: ouvir (Whisper na GPU), falar (Neural com prosódia dinâmica + Piper offline) e conversar.

O Whisper ocupa ~3 GB de VRAM, então só carrega quando você toca no microfone
e é descarregado depois de um minuto sem receber áudio, ou ao abrir um jogo.
Com o mãos livres ligado ele fica carregado (recarregar levava segundos a cada "Guará").
"""

import array
import ctypes
import gc
import json
import os
import sys
import asyncio
import io
import random
import re
import subprocess
import sys
import threading
import time
import unicodedata

import pc
import whatsapp
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
STT_IDLE_UNLOAD = 60      # libera a GPU depois de 1 min sem receber áudio
STT_IDLE_HANDSFREE = 900  # no mãos livres o "Guará" precisa de resposta rápida: só libera após 15 min de silêncio
WAKE_STALE = 5            # trecho do mãos livres que esperou mais que isso na fila já perdeu a vez
FOLLOWUP_WINDOW = 14      # segundos após uma pergunta do Guará em que o áudio é tratado como resposta
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

THINKING_LINES = (
    "Deixa eu conferir isso pra você.",
    "Já peguei seu pedido. Vou dar uma olhada.",
    "Boa! Deixa eu pensar nisso um instante.",
)

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
    "ABRIR SITES E APPS: você SEMPRE consegue, em qualquer sessão e sem rodar comando nenhum. Basta terminar a "
    "resposta com uma linha separada no formato ABRIR: seguido da URL https completa ou do nome do app como aparece "
    "na lista de apps do pedido (ex.: ABRIR: https://www.instagram.com ou ABRIR: VS Code). O painel abre na hora no Firefox, que é "
    "o navegador do usuário. WHATSAPP: você não abre o WhatsApp no navegador; o painel tem uma sessão própria dele. "
    "Para ler as mensagens novas de uma conversa termine com a linha WHATSAPP_LER: <nome do contato ou grupo>; "
    "para resumir o que falaram num grupo ou conversa grande, WHATSAPP_RESUMO: <nome do grupo ou contato>; "
    "para saber quem mandou mensagem nova, WHATSAPP_NOVAS; "
    "para mandar mensagem, WHATSAPP_ENVIAR: <contato ou RESPONDER> | <texto exato da mensagem, escrito como o usuário mandaria> "
    "(se o usuário disser 'responde ela/ele que...' sem repetir o nome após ler uma conversa, use RESPONDER no lugar do contato); "
    "quando o usuário ensinar como alguém está salvo no WhatsApp (ex.: 'o nome dela está como Amor', 'minha mãe está salva como Maria'), "
    "termine com WHATSAPP_APELIDO: <apelido> | <nome no WhatsApp>; "
    "para ativar aviso automático quando alguém importante mandar mensagem, WHATSAPP_VIP: <contato> (ou WHATSAPP_VIP_REMOVER: <contato>). "
    "O painel lê as mensagens em voz alta e sempre pede confirmação antes de enviar, então não peça confirmação você mesmo. "
    "Use o nome do contato do jeito que o usuário falou (esposa, mãe, Eduardo…): o painel conhece os apelidos e procura "
    "o contato sozinho, e se não achar ele mesmo pergunta como está salvo. Então nunca pergunte como o contato está salvo "
    "nem peça para repetir o texto: emita o comando direto. Para TOCAR uma música ou vídeo do YouTube, não invente endereço: termine com a linha "
    "TOCAR: seguida do que buscar (ex.: TOCAR: M83 Midnight City); o painel acha o vídeo certo e abre tocando. "
    "Nunca diga que está sem acesso para abrir algo. Para outras ações você também pode criar e editar arquivos, rodar comandos, scripts e testes nos projetos em "
    "~/Área de trabalho/PROJETOS, controlar o painel (http://127.0.0.1:47801). Limites: nunca use sudo; "
    "não apague, não sobrescreva, não faça git push nem instale nada se o pedido não disser isso com todas as "
    "letras; você não clica nem digita dentro de páginas do navegador, então não prometa isso. "
    "O usuário mora em Goiânia (GO): previsão do tempo e buscas locais são de lá, a menos que ele diga outra cidade. "
    "Se terminar a resposta com uma pergunta, o microfone do tablet abre sozinho para ele responder; "
    "o texto veio de um microfone e pode ter sido mal entendido, então pergunte só quando faltar algo de verdade "
    "e, se a frase parecer um pedaço de conversa com outra pessoa, responda só 'Tô por aqui.' sem perguntar nada."
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


WAKE_WORDS = ("guara", "guarah", "guaraa", "quara", "gwara")

try:
    _LIBC = ctypes.CDLL("libc.so.6")
except OSError:
    _LIBC = None


def release_memory():
    """Devolve ao sistema a memória que o Python/PyTorch já soltou. Cada áudio é tratado numa thread
    própria e o glibc guardava os buffers em dezenas de arenas: o servidor chegou a 14 GB de RAM."""
    if _LIBC is not None:
        try:
            _LIBC.malloc_trim(0)
        except Exception:
            pass


def after_wake_word(text):
    """Aceita o nome no início, opcionalmente após uma saudação curta."""
    words = list(re.finditer(r"[\wÀ-ú']+", text))
    normalized = [unicodedata.normalize('NFD', word.group().lower())
                  .encode('ascii', 'ignore').decode() for word in words]
    index = 1 if normalized and normalized[0] in ('ei', 'oi', 'ola', 'hey') else 0
    if len(words) > index and normalized[index] in WAKE_WORDS:
        return text[words[index].end():].strip(" ,.!?;:-…")
    return None


def reliable_speech(result, wake=True):
    """Descarta silêncio e os limiares de falha de decodificação do Whisper."""
    segments = result.get('segments') or []
    return bool(segments) and all(
        (segment.get('no_speech_prob', 1) <= (0.5 if wake else 0.6)
         or (not wake and segment.get('no_speech_prob', 1) <= 0.85
             and segment.get('avg_logprob', -float('inf')) >= -1.0))
        and segment.get('avg_logprob', -float('inf')) >= (-1.0 if wake else -1.5)
        and segment.get('compression_ratio', float('inf')) <= 2.4
        for segment in segments
    )


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
        self._stt_lock = threading.RLock()
        self.game_mode = False
        self.games = []
        self._stt_generation = 0
        self._capture_generation = 0
        self.handsfree_enabled = False
        self._manual_waiting = 0     # áudios do microfone de toque na fila: têm prioridade sobre o mãos livres
        self._queue_lock = threading.Lock()
        self.followup_until = 0.0    # o Guará acabou de perguntar algo: o próximo áudio é a resposta
        self._duck_lock = threading.Lock()
        self._ducked = None          # (volume original, volume baixado) enquanto o tablet escuta
        self._duck_until = 0.0
        self.stt_idle_seconds = max(10, float(config.get("voice_stt_idle_seconds", STT_IDLE_UNLOAD)))
        self._ack_cache = {}
        self._ack_lock = threading.Lock()
        self._ack_index = 0
        self.conversation = None     # {"engine", "id"}: conversa em andamento (para lembrar o contexto)
        self.conversation_at = 0.0
        self.wa = whatsapp.WhatsApp(on_vip=self._on_vip_message, vip_getter=self._vip_targets)
        self.wa_pending = None       # mensagem esperando o "sim" do usuário ou clique no tablet
        self.wa_last_chat = None     # última conversa lida/interagida ("responde ela que sim")
        self.wa_last_at = 0.0
        self.wa_failed_lookup = None # guarda tentativa quando o nome não foi achado ("o nome dela está como Amor")
        self.history = []            # últimas trocas (você, Guará): contexto quando a sessão expira ou a IA muda
        self.session_path = ROOT_DIR / 'server/voice-session.local.json'
        self._restore_conversation()
        threading.Thread(target=self._warm_voices, daemon=True).start()
        threading.Thread(target=self._unload_idle, daemon=True).start()

    def snapshot(self):
        return {"enabled": self.enabled, "game_mode": self.game_mode,
                "games": list(self.games), **self.voices()}

    def _restore_conversation(self):
        try:
            saved = json.loads(self.session_path.read_text())
            cutoff = time.time() - float(self.config.get('voice_history_hours', 48)) * 3600
            self.history = [entry for entry in saved.get('history', [])
                            if isinstance(entry, list) and len(entry) == 3
                            and isinstance(entry[0], (int, float)) and entry[0] >= cutoff
                            and all(isinstance(value, str) for value in entry[1:])][-6:]
            session = saved.get('conversation')
            if (isinstance(session, dict) and isinstance(session.get('engine'), str)
                    and isinstance(session.get('id'), str)):
                self.conversation = session
                self.conversation_at = float(saved.get('conversation_at', 0))
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def _save_conversation(self):
        if not hasattr(self, 'session_path'):
            return
        try:
            temporary = self.session_path.with_suffix('.tmp')
            with open(temporary, 'w', opener=lambda path, flags: os.open(path, flags, 0o600)) as out:
                json.dump({'history': self.history, 'conversation': self.conversation,
                           'conversation_at': self.conversation_at}, out, ensure_ascii=False)
            temporary.replace(self.session_path)
        except OSError:
            pass

    def set_games(self, games):
        games = list(games)
        blocked = bool(games)
        changed = self.games != games
        transition = blocked != self.game_mode
        self.games = games
        self.game_mode = blocked
        if transition:
            self._stt_generation += 1
        if changed or transition:
            self.hub.broadcast("voice", self.snapshot())
        if transition and blocked:
            # Bloqueia novos áudios antes de esperar uma transcrição já em andamento.
            threading.Thread(target=self._unload_stt, daemon=True).start()

    def _unload_stt(self):
        with self._stt_lock:
            self._stt = None
            gc.collect()
            torch = sys.modules.get("torch")
            if torch is not None:
                torch.cuda.empty_cache()
        release_memory()

    # ------------------------------------------------------------ falar

    def _warm_voices(self):
        if self.enabled:
            self._ack_audio('Pode falar.')
        if self.voice_id.startswith("piper:"):
            self._load_tts(self.voice_id.split(":", 1)[1])
        if self.enabled:
            for text in THINKING_LINES:
                self._ack_audio(text)

    def _ack_audio(self, text):
        """Frases curtas prontas em memória, separadas por voz."""
        voice_id = self.voice_id
        key = (voice_id, text)
        with self._ack_lock:
            if key not in self._ack_cache:
                try:
                    data = self._synth(text)
                except Exception:
                    return None  # o balão continua funcionando mesmo sem sintetizador disponível
                if not data or self.voice_id != voice_id:
                    return None
                self._ack_cache[key] = (data, *envelope(data))
            return self._ack_cache[key]

    def on_mission_start(self, mission):
        text = THINKING_LINES[self._ack_index % len(THINKING_LINES)]
        self._ack_index += 1
        self.hub.broadcast("thinking", {"id": mission["id"], "text": text})
        if self.enabled and not self.game_mode:
            threading.Thread(target=self._acknowledge, args=(mission, text), daemon=True).start()

    def prompt_to_listen(self):
        if self.game_mode:
            return
        audio = self._ack_audio('Pode falar.') if self.enabled else None
        if not audio:
            self.hub.broadcast('listen_ready', {})
            return
        data, env, dur = audio
        cid = uuid.uuid4().hex[:10]
        self.clips[cid] = data
        if len(self.clips) > 14:
            self.clips.pop(next(iter(self.clips)))
        self.hub.broadcast('say', {'id': cid, 'text': 'Pode falar.', 'env': env,
                                   'dur': dur, 'kind': 'listen_prompt'})

    def _acknowledge(self, mission, text):
        if self.game_mode:
            return
        audio = self._ack_audio(text)
        # A síntese pode demorar: nunca anunciar espera depois que a resposta ficou pronta.
        if (not audio or not self.enabled or self.game_mode or self.agent.mission is not mission
                or mission["status"] != "running"):
            return
        data, env, dur = audio
        cid = uuid.uuid4().hex[:10]
        self.clips[cid] = data
        if len(self.clips) > 14:
            self.clips.pop(next(iter(self.clips)))
        self.hub.broadcast("say", {"id": cid, "text": text, "env": env, "dur": dur,
                                   "kind": "ack", "mission_id": mission["id"]})

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
        threading.Thread(target=self._warm_voices, daemon=True).start()
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

    def say(self, text, kind="reply", limit=440, ask=False):
        """Sintetiza e manda o áudio para o tablet tocar (com o envelope da boca).
        ask=True: resposta de conversa que termina em pergunta; o tablet abre o microfone quando acabar."""
        clean = speakable(text, limit)
        if not clean or (not self.enabled and kind != "reply"):
            return
        if self.game_mode:
            self.hub.broadcast("reply", {"text": clean, "kind": kind})
            return
        data = self._synth(clean)
        if self.game_mode:
            self.hub.broadcast("reply", {"text": clean, "kind": kind})
            return
        if not data:
            return
        cid = uuid.uuid4().hex[:10]
        self.clips[cid] = data
        if len(self.clips) > 14:
            self.clips.pop(next(iter(self.clips)))
        env, dur = envelope(data)
        ask = bool(ask and self.config.get("voice_followup", True) and clean.rstrip(' "\'').endswith("?"))
        if ask:
            self.followup_until = time.time() + dur + FOLLOWUP_WINDOW
        self.hub.broadcast("say", {"id": cid, "text": clean, "env": env, "dur": dur, "kind": kind, "ask": ask})
        self.hub.broadcast("attention", {"reason": "say"})

    def answer(self, text, limit=440):
        """Resposta de conversa: se for uma pergunta, o microfone abre para você responder sem tocar."""
        return self.say(text, "reply", limit, ask=True)

    def say_async(self, text, kind="notify"):
        threading.Thread(target=self.say, args=(text, kind), daemon=True).start()

    def say_poke(self):
        self.say_async(random.choice(POKE_VOICE_LINES), "reply")

    # ------------------------------------------------------------ ouvir

    def warm(self):
        """Começa a carregar o Whisper enquanto você ainda está falando."""
        if not self.game_mode:
            threading.Thread(target=self._load_stt, daemon=True).start()
            threading.Thread(target=self.duck, daemon=True).start()

    def duck(self):
        """Abaixa o som do PC enquanto o tablet te escuta: com música alta o microfone não achava o fim da
        sua fala e o Whisper ouvia a música junto. Volta quando o áudio chega (ou em 25 s, por segurança)."""
        if not self.config.get("voice_duck", True):
            return
        with self._duck_lock:
            self._duck_until = time.time() + 25
            if self._ducked:
                return
            v = pc.volume_get()
            level = v.get("level")
            if level is None or v.get("muted") or level <= 20:
                return
            low = max(10, round(level * 0.3))
            pc.volume_set(low)
            self._ducked = (level, low)

    def unduck(self):
        lock = getattr(self, "_duck_lock", None)
        if lock is None:
            return
        with lock:
            ducked, self._ducked = self._ducked, None
            if ducked and pc.volume_get().get("level") == ducked[1]:   # se você mexeu no volume, fica o seu
                pc.volume_set(ducked[0])

    def _load_stt(self):
        with self._stt_lock:
            if self.game_mode:
                return None
            self._stt_used = time.time()
            if self._stt is None:
                import whisper
                self._stt = whisper.load_model(WHISPER_MODEL, device="cuda")
            return self._stt

    def _unload_if_idle(self):
        handsfree = getattr(self, 'handsfree_enabled', False)
        idle = max(self.stt_idle_seconds, STT_IDLE_HANDSFREE) if handsfree else self.stt_idle_seconds
        with self._stt_lock:
            if self._stt is not None and time.time() - self._stt_used >= idle:
                self._unload_stt()
                return True
        return False

    def _unload_idle(self):
        ticks = 0
        while True:
            time.sleep(5)
            ticks += 1
            if not self._unload_if_idle() and ticks % 12 == 0:
                release_memory()
            if self._ducked and time.time() > self._duck_until:
                self.unduck()                    # você não chegou a falar: o som volta mesmo assim

    def hear(self, wav_bytes, wake=False):
        if self.game_mode or (wake and not self.handsfree_enabled):
            return False
        generation = self._stt_generation
        capture_generation = self._capture_generation
        if not wake:
            with self._queue_lock:
                self._manual_waiting += 1
            threading.Thread(target=self.unduck, daemon=True).start()
        threading.Thread(target=self._hear, args=(wav_bytes, wake, generation, capture_generation, time.time()),
                         daemon=True).start()
        return True

    def cancel_listening(self):
        self._capture_generation += 1
        threading.Thread(target=self.unduck, daemon=True).start()

    def set_handsfree_mode(self, enabled):
        was = self.handsfree_enabled
        self.handsfree_enabled = bool(enabled)
        if not self.handsfree_enabled:
            self.cancel_listening()
        elif not was and not self.game_mode:
            # carrega já: senão o primeiro "Guará" depois de ligar (ou de reiniciar o servidor) esperava ~6 s
            threading.Thread(target=self._load_stt, daemon=True).start()

    def _manual_done(self):
        lock = getattr(self, '_queue_lock', None)
        if lock is None:
            return
        with lock:
            self._manual_waiting = max(0, self._manual_waiting - 1)

    def _hear(self, wav_bytes, wake=False, generation=None, capture_generation=None, arrived=None):
        """wake=True: trecho do mãos livres. Só segue se começar com Guará."""
        waiting = not wake and arrived is not None     # contado em hear(): sai da fila uma vez só
        try:
            self._hear_audio(wav_bytes, wake, generation, capture_generation, arrived)
        finally:
            if waiting:
                self._manual_done()
            release_memory()

    def _hear_audio(self, wav_bytes, wake, generation, capture_generation, arrived):
        if generation is None:
            generation = self._stt_generation
        if capture_generation is None:
            capture_generation = getattr(self, '_capture_generation', 0)
        def cancelled():
            return (self.game_mode or generation != self._stt_generation
                    or capture_generation != getattr(self, '_capture_generation', 0)
                    or (wake and not self.handsfree_enabled))
        if cancelled():
            return
        path = Path(f"/tmp/capi_ouvido_{uuid.uuid4().hex[:6]}.wav")
        try:
            # O mesmo lock protege carga, inferência e descarte; não sobra referência
            # local ao modelo segurando VRAM depois que o modo jogo pede a liberação.
            with self._stt_lock:
                if cancelled():
                    return
                # Ruído de fundo do mãos livres não pode atrasar quem tocou no microfone nem virar fila:
                # trecho antigo ou com pedido de toque esperando é descartado.
                if wake and (getattr(self, '_manual_waiting', 0) > 0
                             or (arrived and time.time() - arrived > WAKE_STALE)):
                    return
                if not wake:
                    self.hub.broadcast("heard", {"state": "transcrevendo"})
                path.write_bytes(wav_bytes)
                self._load_stt()
                if cancelled():
                    return
                result = self._stt.transcribe(str(path), language="pt", fp16=True,
                                             condition_on_previous_text=False)
                text = (result.get("text") or "").strip()
                self._stt_used = time.time()
        except Exception as e:
            if not wake and not cancelled():
                self.hub.broadcast("heard", {"state": "erro", "text": str(e)[:120]})
            return
        finally:
            path.unlink(missing_ok=True)
        if cancelled():
            return
        # Resposta a uma pergunta do Guará: o microfone abriu sozinho, então vale o critério rígido do
        # mãos livres (eco e conversa de fundo não podem virar pedido).
        answering = not wake and time.time() < getattr(self, 'followup_until', 0)
        if not wake:
            self.followup_until = 0.0
        if (not reliable_speech(result, wake=wake or answering) or len(text) < 2
                or any(h in text.lower() for h in HALLUCINATIONS)):
            if not wake:
                self.hub.broadcast("heard", {"state": "vazio"})
            return
        if wake:
            rest = after_wake_word(text)
            if rest is None:
                return                                  # não chamou o Guará: descarta sem guardar
            if len(rest.split()) < 2:
                self.hub.broadcast("wake", {})          # só "Guará": o tablet abre o microfone para o pedido
                return
            text = rest
        elif after_wake_word(text) == '':
            # Dizer apenas o nome é chamar, não é o pedido em si.
            self.hub.broadcast('heard', {'state': 'vazio'})
            self.hub.broadcast('wake', {})
            return
        self.hub.broadcast("heard", {"state": "ok", "text": text})
        self.agent.log("voice", f"Você: {text}")
        self.converse(text)

    def transcribe_bytes(self, audio_bytes):
        """Transcreve um áudio recebido no WhatsApp usando o mesmo modelo Whisper na GPU."""
        if not audio_bytes or self.game_mode:
            return ""
        generation = self._stt_generation
        path = Path(f"/tmp/capi_wa_audio_{uuid.uuid4().hex[:8]}.ogg")
        try:
            with self._stt_lock:
                if self.game_mode or generation != self._stt_generation:
                    return ""
                path.write_bytes(audio_bytes)
                self._load_stt()
                if self.game_mode or generation != self._stt_generation or self._stt is None:
                    return ""
                result = self._stt.transcribe(str(path), language="pt", fp16=True, condition_on_previous_text=False)
                self._stt_used = time.time()
                return (result.get("text") or "").strip()
        except Exception:
            return ""
        finally:
            path.unlink(missing_ok=True)
            release_memory()

    # ------------------------------------------------------------ conversar

    def converse(self, text):
        if self.wa_pending:
            handled = self._wa_answer(text)
            if handled:
                return True, "ok"
            text = "(A mensagem do WhatsApp NÃO foi enviada.) " + text
        # Atalho direto se o usuário ensinar um apelido logo após uma busca que falhou ("o nome dela está como Amor")
        learned = self._try_direct_alias_learn(text)
        if learned:
            return True, "ok"
        keep = self.config.get("voice_session_minutes", 30) * 60
        resume = self.conversation if time.time() - self.conversation_at < keep else None
        engines = self.agent.engines()
        if resume and engines and resume["engine"] != engines[0]:
            resume = None                               # a IA da conversa ficou sem limite: outra assume
        self._asked = text
        if not resume:
            # sessão nova (expirou ou trocou de IA): leva as últimas trocas para não perder o fio
            recent = [h for h in self.history
                      if time.time() - h[0] < float(self.config.get('voice_history_hours', 48)) * 3600][-6:]
            if recent:
                past = "\n".join(f"Usuário: {u}\nGuará: {r}" for _, u, r in recent)
                text = f"(Conversa recente, para contexto:\n{past})\n\nPedido agora: {text}"
        last_wa = f" Última conversa do WhatsApp: {self.wa_last_chat}." if self.wa_last_chat and time.time() - self.wa_last_at < 3600 else ""
        failed_wa = (f" Último apelido procurado e não achado: {self.wa_failed_lookup['alias']}."
                     if self.wa_failed_lookup and time.time() - self.wa_failed_lookup["at"] < 600 else "")
        aliases = "; ".join(f"{k} = {v}" for k, v in list((self.config.get("whatsapp_aliases") or {}).items())[:25])
        alias_hint = f" Apelidos já conhecidos: {aliases}." if aliases else ""
        apps = self._app_names()
        # lembrete em todo pedido: conversas retomadas guardam instruções antigas ("sem acesso")
        text = text + (
            f"\n\n(Para abrir site ou app termine com ABRIR: <url https ou nome do app>; para tocar música ou vídeo, TOCAR: <busca>; "
            + (f"apps do PC: {apps}; " if apps else "")
            + f"WhatsApp: WHATSAPP_LER: <contato>, WHATSAPP_RESUMO: <grupo ou contato>, WHATSAPP_NOVAS, "
            f"WHATSAPP_ENVIAR: <contato ou RESPONDER> | <texto>, WHATSAPP_APELIDO: <apelido> | <nome no WhatsApp>, "
            f"WHATSAPP_VIP: <contato> ou WHATSAPP_VIP_REMOVER: <contato>.{alias_hint}{last_wa}{failed_wa})"
        )
        ok, info = self.agent.mission_start(
            text, "Conversa", voice=True, resume=resume, write=self.config.get("voice_exec", True),
            tools=self.config.get("voice_exec_tools") if self.config.get("voice_exec", True) else self.config.get("mission_tools"),
            system_prompt=VOICE_PROMPT, model=self.config.get("voice_model"),
        )
        if not ok:
            self.say(f"Calma aí, {info.lower()}.", "reply")
        return ok, info

    def _app_names(self):
        """Nomes dos apps que o ABRIR aceita (fixados, mais usados e atalhos), guardados por 5 min."""
        cached = getattr(self, "_apps_cache", None)
        if cached and time.time() - cached[0] < 300:
            return cached[1]
        try:
            names = ", ".join(a["label"] for a in pc.apps_catalog(self.config.get("shortcuts", [])) if a.get("label"))
        except Exception:
            names = ""
        self._apps_cache = (time.time(), names)
        return names

    def on_mission_done(self, m):
        """Chamado pelo Agent quando uma missão termina."""
        if m.get("voice"):
            # linhas "ABRIR: …" viram ação no PC (validada: só https ou apps da dock) e não são faladas
            for target in re.findall(r"(?im)^\s*ABRIR:\s*(\S+)\s*$", m.get("text") or ""):
                ok = pc.open_target(target, self.config.get("shortcuts", []))
                self.agent.log("mission", ("Abri no PC: " if ok else "Recusei abrir: ") + target[:80])
            for query in re.findall(r"(?im)^\s*TOCAR:\s*(.+?)\s*$", m.get("text") or ""):
                found = pc.yt_search(query, 1)
                if found:
                    pc.open_target("https://www.youtube.com/watch?v=" + found[0]["id"], [])
                    self.agent.log("mission", "Tocando no YouTube: " + found[0]["title"][:70])
            wa = re.findall(
                r"(?im)^\s*(WHATSAPP_LER|WHATSAPP_RESUMO|WHATSAPP_NOVAS|WHATSAPP_ENVIAR|WHATSAPP_APELIDO|WHATSAPP_VIP|WHATSAPP_VIP_REMOVER)\b:?\s*(.*?)\s*$",
                m.get("text") or "",
            )
            m["text"] = re.sub(r"(?im)^\s*(ABRIR|TOCAR|WHATSAPP_\w+)\b.*$", "", m.get("text") or "").strip()
            if m.get("session"):
                self.conversation = {"engine": m["engine"], "id": m["session"]}
                self.conversation_at = time.time()
            if m["status"] == "done" and getattr(self, "_asked", None):
                self.history = (self.history + [(time.time(), self._asked[:300], speakable(m["text"], 300))])[-6:]
                self._save_conversation()
            if wa:
                self._wa_action(m["text"], *wa[0])
            else:
                self.answer(m["text"] or "Prontinho, tudo resolvido!")
        elif m["status"] == "done":
            self.say_async(f"Olha só, terminei a missão {m['title']}! {m['text']}", "notify")

    # ------------------------------------------------------------ WhatsApp

    def _save_config_key(self, key, value):
        cfg_path = ROOT_DIR / "server" / "config.json"
        try:
            user = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
            user[key] = value
            cfg_path.write_text(json.dumps(user, indent=2, ensure_ascii=False))
        except Exception:
            pass
        self.config[key] = value

    def _resolve_alias(self, name):
        raw = (name or "").strip()
        plain = whatsapp._plain(raw)
        for prefix in ("a minha ", "o meu ", "minha ", "meu ", "a ", "o ", "pro ", "pra ", "para ", "do ", "da "):
            if plain.startswith(prefix):
                plain = plain[len(prefix):].strip()
                break
        aliases = {whatsapp._plain(k): v for k, v in (self.config.get("whatsapp_aliases") or {}).items()}
        return aliases.get(plain, raw), plain

    def _vip_targets(self):
        """(nomes, palavras-chave) dos contatos que avisam sozinhos quando mandam mensagem."""
        names = []
        for v in self.config.get("whatsapp_vip") or []:
            resolved, _ = self._resolve_alias(v)
            if resolved:
                names.append(resolved)
        return names, list(self.config.get("whatsapp_vip_keywords") or [])

    def _on_vip_message(self, title, count):
        if not self.enabled or self.game_mode or self.wa_pending:
            return
        clean = re.sub(r"[^\w\sÀ-ÿ-]", "", title).strip() or title
        self.agent.log("mission", f"WhatsApp VIP: {title} ({count})")
        self.say(f"Olha só, chegou mensagem de {clean} no WhatsApp!", "notify")

    def _set_wa_pending(self, pending):
        self.wa_pending = pending
        self.hub.broadcast("wa_confirm", pending)
        if pending:
            self.hub.broadcast("attention", {"reason": "wa_confirm"})

    def _try_direct_alias_learn(self, text):
        """Detecta frases diretas como 'o nome dela está como Amor' ou 'salva o apelido mãe como Maria'."""
        m = re.search(
            r"(?i)\b(?:apelido\s+de\s+|chamo\s+(?:de\s+)?|salva\s+como\s+|nome\s+(?:dela|dele|d[oa]\s+[\wÀ-ÿ]+)\s+(?:tá|ta|está|esta|é|e)\s+(?:salvo\s+)?como\s+)"
            r"([A-Za-zÀ-ÿ0-9_ -]{2,35})$",
            text.strip().rstrip(".!"),
        )
        if not m:
            return False
        real_name = m.group(1).strip().strip("'\"")
        subj = re.search(r"(?i)\bnome\s+d[oa]\s+([\wÀ-ÿ]+)\s+(?:tá|ta|está|esta|é|e)", text)
        alias_key = subj.group(1) if subj else (self.wa_failed_lookup["alias"] if self.wa_failed_lookup else None)
        if not alias_key:
            return False
        threading.Thread(target=self._wa_action, args=("", "WHATSAPP_APELIDO", f"{alias_key} | {real_name}"), daemon=True).start()
        return True

    @staticmethod
    def _format_wa_msg(who, text, mine, chat_title):
        sender = "Você" if mine else (who or chat_title)
        if text.startswith("[áudio: ") and text.endswith("]"):
            transcript = text[len("[áudio: "):-1].strip()
            return f"{sender} mandou um áudio: '{transcript}'"
        if text == "[áudio]":
            return f"{sender} mandou um áudio."
        return f"{sender}: {text}"

    @staticmethod
    def _join_names(items):
        names = [f"{name} ({n})" if n > 1 else name for name, n in items]
        if not names:
            return ""
        if len(names) == 1:
            return names[0]
        return ", ".join(names[:-1]) + " e " + names[-1]

    def _wa_action(self, said, action, arg):
        """Executa o pedido do modelo. O conteúdo das mensagens só é falado (ou resumido por IA isolada sem
        ferramentas), nunca volta para a IA que tem acesso ao PC."""
        try:
            if action == "WHATSAPP_NOVAS":
                cat = self.wa.unread_categorized()
                people = cat["people"][:6]
                groups = cat["groups"][:5]
                if not people and not groups:
                    return self.answer("Nenhuma mensagem nova no WhatsApp.")
                parts = []
                if people:
                    parts.append("Tem mensagem de " + self._join_names(people) + ".")
                if groups:
                    prefix = "E nos grupos: " if people else "De pessoas não tem nada novo; nos grupos tem mensagem em "
                    parts.append(prefix + self._join_names(groups) + ".")
                return self.answer(" ".join(parts), limit=750)

            if action == "WHATSAPP_APELIDO":
                alias_raw, sep, real_raw = arg.partition("|")
                if not sep:
                    real_raw = alias_raw.strip()
                    alias_raw = (self.wa_failed_lookup or {}).get("alias") or ""
                _, alias_key = self._resolve_alias(alias_raw)
                real_name = real_raw.strip().strip("'\"")
                if not alias_key or not real_name:
                    return self.answer("Me diz qual apelido e como o nome está salvo no WhatsApp.")
                aliases = dict(self.config.get("whatsapp_aliases") or {})
                aliases[alias_key] = real_name
                self._save_config_key("whatsapp_aliases", aliases)
                self.agent.log("mission", f"Apelido WhatsApp salvo: {alias_key} → {real_name}")
                prev = self.wa_failed_lookup
                self.wa_failed_lookup = None
                if prev and time.time() - prev["at"] < 600 and prev.get("action") in ("WHATSAPP_LER", "WHATSAPP_RESUMO", "WHATSAPP_ENVIAR"):
                    prev_arg = f"{real_name} | {prev['body']}" if prev.get("body") else real_name
                    self.answer(f"Boa, anotei que {alias_key} é {real_name}! Deixa eu abrir aqui.")
                    return self._wa_action("", prev["action"], prev_arg)
                return self.answer(f"Prontinho! Guardei que {alias_key} está salvo como {real_name} no WhatsApp.")

            if action in ("WHATSAPP_VIP", "WHATSAPP_VIP_REMOVER"):
                target_raw = arg.strip()
                resolved, _ = self._resolve_alias(target_raw)
                vips = list(self.config.get("whatsapp_vip") or [])
                if action == "WHATSAPP_VIP":
                    if resolved and resolved not in vips:
                        vips.append(resolved)
                        self._save_config_key("whatsapp_vip", vips)
                    return self.answer(f"Combinado! Vou te avisar sempre que chegar mensagem de {resolved}.")
                else:
                    vips = [v for v in vips if whatsapp._key(v) != whatsapp._key(resolved) and whatsapp._key(v) != whatsapp._key(target_raw)]
                    self._save_config_key("whatsapp_vip", vips)
                    return self.answer(f"Beleza, desativei o aviso automático para {resolved}.")

            name, _, body = arg.partition("|")
            name = name.strip()
            plain_name = whatsapp._plain(name)
            pronouns = {"", "responder", "ela", "ele", "la", "lá", "essa", "esse", "mesma", "mesmo", "ultima", "ultimo", "conversa", "grupo", "pessoa", "contato"}
            if plain_name in pronouns and self.wa_last_chat:
                title = self.wa_last_chat
            else:
                resolved_name, alias_key = self._resolve_alias(name)
                title = self.wa.find(resolved_name)
                if not title:
                    self.wa_failed_lookup = {"alias": alias_key or name, "action": action, "body": body.strip(), "at": time.time()}
                    return self.answer(f"Não achei ninguém chamado {resolved_name.strip()} no WhatsApp. Como está salvo o nome nos contatos?")

            self.wa_last_chat = title
            self.wa_last_at = time.time()

            if action == "WHATSAPP_LER":
                msgs, already_seen = self.wa.read_new(title, n=6, only_new=True, transcribe=self.transcribe_bytes)
                if not msgs:
                    return self.answer(f"Não consegui ler a conversa com {title}.")
                lines = [self._format_wa_msg(who, text, mine, title) for who, text, mine in msgs]
                if already_seen:
                    return self.answer(f"Não chegou nada novo de {title}. A última foi. {lines[-1]}", limit=900)
                header = f"Mensagem nova de {title}. " if len(lines) == 1 else f"{len(lines)} mensagens de {title}. "
                return self.answer(header + " ".join(lines), limit=950)

            if action == "WHATSAPP_RESUMO":
                msgs, _ = self.wa.read_new(title, n=25, only_new=False, transcribe=self.transcribe_bytes)
                if not msgs:
                    return self.answer(f"Não consegui ler as mensagens de {title} para resumir.")
                lines = [self._format_wa_msg(who, text, mine, title) for who, text, mine in msgs]
                transcript_block = "\n".join(lines[-25:])
                summary = self.agent.summarize_safe(f"Conversa/Grupo: {title}\nMensagens recentes:\n{transcript_block}")
                if not summary:
                    return self.answer(f"Últimas em {title}. " + " ".join(lines[-4:]), limit=900)
                return self.answer(summary, limit=900)

            body = " ".join(body.split())[:600]
            if not body:
                return self.answer(f"O que você quer mandar para {title}?")
            self._set_wa_pending({"title": title, "text": body, "at": time.time()})
            self.answer(f"Vou mandar para {title}: {body}. Posso mandar?", limit=900)
        except whatsapp.NotLinked:
            self.answer("O WhatsApp do Guará não tá conectado. Roda o login dele no PC primeiro.")
        except Exception as e:
            self.agent.log("error", f"WhatsApp: {e}"[:160])
            self.answer("Deu algum problema no WhatsApp, não consegui agora.")

    def wa_decide(self, approve, custom_text=None):
        """Confirma ou cancela o envio pendente (chamado pelos botões Enviar/Cancelar do tablet ou pela voz)."""
        p = self.wa_pending
        if not p:
            return False
        self._set_wa_pending(None)
        if not approve:
            self.say_async("Beleza, não mandei.", "reply")
            return True
        msg_text = (custom_text or p["text"]).strip()[:600]

        def send():
            try:
                self.wa.send(p["title"], msg_text)
                self.agent.log("mission", f"WhatsApp enviado para {p['title']}")
                self.say(f"Mandei para {p['title']}!", "reply")
            except Exception as e:
                self.agent.log("error", f"WhatsApp: {e}"[:160])
                self.say("Não consegui mandar, deu problema no WhatsApp.", "reply")

        threading.Thread(target=send, daemon=True).start()
        return True

    def _wa_answer(self, text):
        """Resposta por voz à confirmação de envio. True se a fala era só sim/não."""
        p = self.wa_pending
        if not p:
            return False
        if time.time() - p["at"] > 180:
            self._set_wa_pending(None)
            return False
        plain = unicodedata.normalize("NFD", text.lower()).encode("ascii", "ignore").decode()
        words = re.findall(r"[a-z]+", plain)
        doubt = {"nao", "muda", "espera", "calma", "troca", "corrige", "mas", "cancela"}
        if words and len(words) <= 5 and not doubt & set(words) and words[0] in (
                "sim", "pode", "manda", "mande", "envia", "envie", "confirmo", "confirma", "isso", "ok", "beleza", "claro", "guara"):
            return self.wa_decide(True)
        if words and len(words) <= 3 and words[0] in ("nao", "cancela", "deixa", "esquece", "para"):
            return self.wa_decide(False)
        self._set_wa_pending(None)
        return False                                    # pediu mudança: segue para a IA, sem enviar

    # ------------------------------------------------------------ avisos falados

    def on_stop(self, project, summary, turn_seconds, pc_idle_ms):
        """Fala o fim de uma tarefa só se você saiu de perto do PC (na frente dele você já vê o aviso;
        falar a cada tarefa longa deixava o Guará falando sozinho enquanto você programava)."""
        if turn_seconds > 20 and pc_idle_ms > 60_000:
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
