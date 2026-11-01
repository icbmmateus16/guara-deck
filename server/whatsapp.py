"""WhatsApp Web numa sessão própria do Guará (Chrome invisível, perfil separado do Firefox).

Vincular uma vez:  python3 whatsapp.py login   (abre o QR Code; leia com o celular)
"""

import base64
import json
import queue
import re
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path

PROFILE = Path.home() / ".local" / "share" / "guara" / "whatsapp"
SEEN_PATH = Path.home() / ".local" / "share" / "guara" / "whatsapp_seen.json"
URL = "https://web.whatsapp.com/"


def _user_agent():
    try:
        ver = subprocess.run(["google-chrome", "--version"], capture_output=True, text=True, timeout=5).stdout.split()[-1]
    except Exception:
        ver = "156.0.0.0"
    # o modo invisível se anuncia como "HeadlessChrome", que o WhatsApp recusa
    return f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ver.split('.')[0]}.0.0.0 Safari/537.36"


# Intercepta criação de Blobs de áudio (mensagens de voz / PTT) e pausa reprodução automática
_AUDIO_HOOK_JS = """
(() => {
  if (window.__guaraAudioHooked) return;
  window.__guaraAudioHooked = true;
  window.__guaraAudioBlobs = [];
  const origCreate = URL.createObjectURL.bind(URL);
  URL.createObjectURL = function(obj) {
    const url = origCreate(obj);
    try {
      if (obj && obj.type && (obj.type.includes('audio') || obj.type.includes('ogg') || obj.type.includes('opus') || obj.type.includes('mp4'))) {
        window.__guaraAudioBlobs.push({ blob: obj, url: url, type: obj.type, size: obj.size || 0, at: Date.now() });
        if (window.__guaraAudioBlobs.length > 30) window.__guaraAudioBlobs.shift();
      }
    } catch (e) {}
    return url;
  };
  const origPlay = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function() {
    try { this.muted = true; } catch (e) {}
    setTimeout(() => { try { this.pause(); } catch (e) {} }, 40);
    try {
      const p = origPlay.apply(this, arguments);
      if (p && p.catch) p.catch(() => {});
      return p;
    } catch (e) {
      return Promise.resolve();
    }
  };
})();
"""


def _launch(pw, headless):
    PROFILE.mkdir(parents=True, exist_ok=True)
    ctx = pw.chromium.launch_persistent_context(
        str(PROFILE), headless=headless, locale="pt-BR",
        user_agent=_user_agent(), viewport={"width": 1280, "height": 900},
    )
    if headless:
        try:
            ctx.add_init_script(_AUDIO_HOOK_JS)
        except Exception:
            pass
    return ctx


class NotLinked(Exception):
    pass


def _plain(s):
    return " ".join(unicodedata.normalize("NFD", (s or "").lower()).encode("ascii", "ignore").decode().split())


def _key(s):
    # o WhatsApp desenha emoji como <img> na conversa aberta: "Amor❤️" vira "Amor" no texto
    return "".join(c for c in _plain(s) if c.isalnum())


def vip_match(title, names, keywords=()):
    """Contato importante: o mesmo nome (emoji e pontuação não contam: "Mae❤️" = "Mae") ou uma palavra-chave
    em qualquer parte ("senac"). Só o começo não basta: "Mãe" não pode casar com "Mãe Armando"."""
    tk = _key(title)
    return (any(_key(n) and _key(n) == tk for n in names)
            or any(_key(k) and _key(k) in tk for k in keywords))


# Lê as mensagens visíveis na conversa aberta, identificando divisor de não lidas, IDs e botões de áudio.
_READ_MESSAGES_JS = """(maxRows) => {
  const allRows = [...document.querySelectorAll('#main [role=row]')];
  let dividerIdx = -1;
  for (let i = 0; i < allRows.length; i++) {
    const r = allRows[i];
    if (!r.querySelector('[data-id]')) {
      const txt = (r.innerText || '').toLowerCase();
      if (txt.includes('não lida') || txt.includes('nao lida') || txt.includes('unread')) {
        dividerIdx = i;
      }
    }
  }
  const msgRows = [];
  for (let i = 0; i < allRows.length; i++) {
    const row = allRows[i];
    const idEl = row.querySelector('[data-id]');
    const msgId = idEl ? idEl.getAttribute('data-id') : null;
    const pre = row.querySelector('[data-pre-plain-text]');
    const who = pre ? (pre.getAttribute('data-pre-plain-text').match(/\\] (.*?): $/) || [])[1] || null : null;
    const mine = !!row.querySelector('[data-icon="tail-out"], [aria-label="Você:"], [data-testid="msg-meta"] [aria-label]')
                 || (msgId ? msgId.startsWith('true_') : false);
    const t = row.querySelector('.copyable-text [data-testid~="selectable-text"], .copyable-text span.selectable-text');
    let text = t ? t.innerText.trim() : '';
    const audioBtn = row.querySelector(
      'button[aria-label*="mensagem de voz"], button[aria-label*="Reproduzir"], button[aria-label*="áudio"], ' +
      '[data-testid*="audio"], [data-testid*="ptt"], [data-icon*="audio"], [data-icon*="ptt"], audio'
    );
    const isAudio = !text && !!audioBtn;
    if (!text) {
      text = row.querySelector('[data-testid*="video"], [data-icon*="video"]') ? '[vídeo]'
        : isAudio ? '[áudio]'
        : row.querySelector('img[src^="blob:"], [data-testid*="image"]') ? '[foto]'
        : msgId ? '[anexo]' : '';
    }
    if (!text && !msgId) continue;
    msgRows.push({
      id: msgId || ('row_' + i),
      who: who,
      text: text,
      mine: mine,
      isAudio: isAudio,
      afterDivider: dividerIdx >= 0 && i > dividerIdx
    });
  }
  return {
    hasDivider: dividerIdx >= 0,
    messages: msgRows.slice(-Math.max(maxRows || 20, 20))
  };
}"""


# Extrai o último Blob de áudio criado após clicar no botão de reproduzir de uma mensagem específica.
_EXTRACT_AUDIO_B64_JS = """async (msgId) => {
  const rows = [...document.querySelectorAll('#main [role=row]')];
  let target = null;
  for (const r of rows) {
    const idEl = r.querySelector('[data-id]');
    if (idEl && idEl.getAttribute('data-id') === msgId) {
      target = r;
      break;
    }
  }
  if (!target) return null;
  const beforeLen = (window.__guaraAudioBlobs || []).length;
  const btn = target.querySelector(
    'button[aria-label*="mensagem de voz"], button[aria-label*="Reproduzir"], button[aria-label*="áudio"], ' +
    '[data-testid*="audio-play"], [data-icon*="audio-play"], [data-testid*="audio"], [data-testid*="ptt"]'
  );
  if (btn) btn.click();
  for (let i = 0; i < 16; i++) {
    await new Promise(r => setTimeout(r, 90));
    const list = window.__guaraAudioBlobs || [];
    if (list.length > beforeLen) {
      document.querySelectorAll('audio').forEach(a => { try { a.pause(); } catch(e) {} });
      const item = list[list.length - 1];
      const buf = await item.blob.arrayBuffer();
      const bytes = new Uint8Array(buf);
      let bin = '';
      for (let j = 0; j < bytes.length; j++) bin += String.fromCharCode(bytes[j]);
      return btoa(bin);
    }
  }
  return null;
}"""


# Inspeciona a lista lateral (#pane-side) identificando não lidas, silenciadas e grupos vs pessoas.
_UNREAD_LIST_JS = """() => {
  const rows = [...document.querySelectorAll('#pane-side [role="row"]')];
  const out = [];
  for (const row of rows) {
    const badge = row.querySelector('[aria-label*="não lida"], [data-testid="icon-unread-count"]');
    const nameEl = row.querySelector('[data-testid="cell-frame-title"] span[title]');
    if (!badge || !nameEl) continue;
    const title = nameEl.getAttribute('title') || '';
    if (!title) continue;
    const label = badge.getAttribute('aria-label') || badge.innerText || '1';
    const digits = (label.split(/\\s+/)[0] || '').replace(/\\D+/g, '');
    const count = parseInt(digits || '1', 10) || 1;
    const muted = !!row.querySelector('[aria-label*="silenciada"], [data-testid*="mute"], [data-icon*="muted"]');
    const sec = row.querySelector('[data-testid="cell-frame-secondary"]');
    const secText = sec ? (sec.innerText || '') : '';
    const hasSenderPrefix = /^~|\\n:\\s/.test(secText);
    const hasGroupMarker = !!row.querySelector(
      '[data-testid="subgroup-identity"], [data-testid^="subtype-"], [data-icon*="group"], [data-icon*="community"]'
    );
    const isGroup = hasGroupMarker || hasSenderPrefix || count >= 30;
    out.push({ title, count, group: isGroup, muted });
  }
  return out;
}"""


class WhatsApp:
    """Um Chrome invisível que só existe enquanto é usado (fecha após IDLE s parado, exceto se vigiando VIPs).
    Todas as chamadas rodam numa thread própria: o Playwright síncrono não aceita outras."""
    IDLE = 300
    VIP_POLL = 25
    VIP_REPEAT = 600
    REFRESH = 3600   # vigiando os importantes a página fica aberta direto; após 26 h ela parou de ver mensagens

    def __init__(self, on_vip=None, vip_getter=None):
        self._q = queue.Queue()
        self._pw = self._ctx = self._page = None
        self._used = 0.0
        self._opened_at = 0.0
        self._on_vip = on_vip
        self._vip_getter = vip_getter   # -> (nomes, palavras-chave)
        self._vip_notified = {}   # _key(title) -> último count anunciado
        self._vip_said = {}       # _key(title) -> quando avisou por último
        self._vip_seeded = False  # a 1ª leitura só anota o que já estava não lido: reiniciar não vira aviso
        self._seen_ids = self._load_seen()
        threading.Thread(target=self._loop, daemon=True).start()

    @staticmethod
    def _load_seen():
        try:
            if SEEN_PATH.exists():
                return json.loads(SEEN_PATH.read_text())
        except Exception:
            pass
        return {}

    def _save_seen(self):
        try:
            SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            SEEN_PATH.write_text(json.dumps(self._seen_ids, ensure_ascii=False))
        except Exception:
            pass

    def linked(self):
        return PROFILE.exists()

    def _call(self, fn, *args, **kwargs):
        box = queue.Queue(1)
        self._q.put((fn, args, kwargs, box))
        ok, val = box.get(timeout=180)
        if not ok:
            raise val
        return val

    def _loop(self):
        last_vip_check = 0.0
        while True:
            try:
                fn, args, kwargs, box = self._q.get(timeout=10)
            except queue.Empty:
                names, keywords = self._vip_getter() if self._vip_getter else ((), ())
                watching = bool(names or keywords)
                now = time.time()
                if watching and self.linked() and now - last_vip_check >= self.VIP_POLL:
                    last_vip_check = now
                    if self._ctx and now - self._opened_at > self.REFRESH:
                        self._close()                    # renova aqui, em segundo plano, e não num pedido seu
                    try:
                        self._poll_vips(names, keywords)
                    except Exception:
                        self._close()
                elif not watching and self._ctx and now - self._used > self.IDLE:
                    self._close()
                continue
            try:
                box.put((True, fn(*args, **kwargs)))
            except Exception as e:
                box.put((False, e))
            finally:
                self._used = time.time()
                try:
                    if self._page:
                        self._page.keyboard.press("Escape")   # fecha a conversa: aberta, tudo que chega vira "lida"
                        self._page.keyboard.press("Escape")
                except Exception:
                    self._close()

    def _poll_vips(self, names, keywords=()):
        """Verifica se chegou mensagem nova de algum contato importante."""
        items = self._unread_detailed()
        current_unread_keys = set()
        for it in items:
            tk = _key(it["title"])
            current_unread_keys.add(tk)
            if it.get("muted") or not vip_match(it["title"], names, keywords):
                continue
            prev = self._vip_notified.get(tk, 0)
            if it["count"] > prev:
                self._vip_notified[tk] = it["count"]
                # um grupo movimentado (Senac) avisaria a cada 25 s: no máximo um aviso por conversa a cada 10 min
                quiet = time.time() - self._vip_said.get(tk, 0) < self.VIP_REPEAT
                if self._on_vip and self._vip_seeded and not quiet:
                    self._vip_said[tk] = time.time()
                    threading.Thread(target=self._on_vip, args=(it["title"], it["count"]), daemon=True).start()
        self._vip_seeded = True
        for tk in list(self._vip_notified):
            if tk not in current_unread_keys:
                self._vip_notified.pop(tk, None)

    def _close(self):
        for stop in (self._ctx and self._ctx.close, self._pw and self._pw.stop):
            try:
                stop and stop()
            except Exception:
                pass
        self._pw = self._ctx = self._page = None

    def _open(self):
        if self._page and not self._page.is_closed():
            try:
                self._page.wait_for_selector("#pane-side", timeout=5000)
                return self._page
            except Exception:
                # aberta há horas pelo aviso dos importantes, a página pode recarregar ou travar sem a lista
                # de conversas; ler dela dava "nenhuma mensagem nova" com mensagens chegando. Abre de novo.
                self._close()
        if not self.linked():
            raise NotLinked()
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._ctx = _launch(self._pw, headless=True)
        page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        page.goto(URL)
        page.wait_for_selector("#pane-side, canvas", timeout=90_000)
        if not page.query_selector("#pane-side"):
            page.wait_for_timeout(4000)                  # o QR aparece antes da lista em sessões lentas
            if not page.query_selector("#pane-side"):
                self._close()
                raise NotLinked()
        page.wait_for_timeout(1500)
        try:
            page.evaluate(_AUDIO_HOOK_JS)
        except Exception:
            pass
        self._page = page
        self._opened_at = time.time()
        return page

    def _titles(self, page):
        return page.eval_on_selector_all('#pane-side [role="row"] [data-testid="cell-frame-title"] span[title]',
                                         "els => els.map(e => e.getAttribute('title'))")

    def _settled_titles(self, page):
        """Os resultados da busca chegam aos poucos (conversas antes dos contatos): espera a lista parar de mudar.
        Ler cedo demais trocou "Mãe" (Mae❤️) por "Mãe Matheus Face", a mãe de outra pessoa."""
        page.wait_for_timeout(1200)
        last = None
        for _ in range(8):
            titles = [t for t in self._titles(page) if t]
            if titles and titles == last:
                return titles
            last = titles
            page.wait_for_timeout(400)
        return last or []

    @staticmethod
    def _best_match(titles, name):
        q, k = _plain(name), _key(name)
        words = q.split()
        for test in (lambda t: _key(t) == k, lambda t: _plain(t).startswith(q),
                     lambda t: all(w in _plain(t) for w in words)):
            for t in titles:
                if test(t):
                    return t
        return None

    def _search(self, name):
        page = self._open()
        box = page.locator('input[data-tab="3"]')
        box.click()
        box.fill(name)
        found = self._best_match(self._settled_titles(page), name)
        if found and _key(found) != _key(name):
            page.wait_for_timeout(1500)                  # o nome exato pode ser o último a aparecer
            found = self._best_match(self._settled_titles(page), name) or found
        return page, found

    def _row_unread_count(self, page, title):
        """Lê quantas mensagens não lidas o badge da conversa indica antes de clicar nela."""
        try:
            return page.evaluate("""(targetTitle) => {
              for (const row of document.querySelectorAll('#pane-side [role="row"]')) {
                const nameEl = row.querySelector('[data-testid="cell-frame-title"] span[title]');
                if (!nameEl || nameEl.getAttribute('title') !== targetTitle) continue;
                const badge = row.querySelector('[aria-label*="não lida"], [data-testid="icon-unread-count"]');
                if (!badge) return 0;
                const label = badge.getAttribute('aria-label') || badge.innerText || '0';
                const digits = (label.split(/\\s+/)[0] || '').replace(/\\D+/g, '');
                return parseInt(digits || '0', 10) || 0;
              }
              return 0;
            }""", title) or 0
        except Exception:
            return 0

    def _go(self, title):
        page, found = self._search(title)
        if found != title:
            raise RuntimeError(f"conversa {title} sumiu da busca")
        unread_before = self._row_unread_count(page, title)
        page.locator('#pane-side [data-testid="cell-frame-title"]').get_by_title(title, exact=True).first.click()
        page.wait_for_selector("#main footer [contenteditable=true]", timeout=15_000)
        got = page.inner_text('[data-testid="conversation-info-header-chat-title"]').strip()
        if _key(got) != _key(title):
            raise RuntimeError(f"abriu {got} em vez de {title}")
        page.wait_for_timeout(1200)
        return page, unread_before

    def _find(self, name):
        page, found = self._search(name)
        try:
            box = page.locator('input[data-tab="3"]')
            box.fill("")
        except Exception:
            pass
        return found

    def _read_chat(self, title, n=5, only_new=True, transcribe=None):
        page, unread_before = self._go(title)
        fetch_n = max(n, min(unread_before + 4, 30), 15)
        seen = -1
        for _ in range(10):                              # as mensagens chegam aos poucos depois de abrir
            count = page.locator("#main [role=row]").count()
            if count == seen and count >= min(n, 2):
                break
            seen = count
            page.wait_for_timeout(700)

        data = page.evaluate(_READ_MESSAGES_JS, fetch_n)
        rows = data.get("messages") or []
        if not rows:
            return [], False

        tk = _key(title)
        last_seen_id = self._seen_ids.get(tk)
        already_seen = False

        if only_new:
            after_div = [r for r in rows if r.get("afterDivider")]
            if after_div:
                selected = after_div[-max(n, len(after_div)):]
            elif unread_before > 0:
                selected = rows[-min(unread_before, len(rows), 15):]
            elif last_seen_id:
                idx = next((i for i, r in enumerate(rows) if r.get("id") == last_seen_id), -1)
                if idx >= 0:
                    if idx == len(rows) - 1:
                        already_seen = True
                        selected = rows[-1:]
                    else:
                        selected = rows[idx + 1 :]
                else:
                    # não achou o ID antigo: pega o bloco final de mensagens recebidas ou as últimas n
                    trailing = []
                    for r in reversed(rows):
                        if r.get("mine"):
                            break
                        trailing.append(r)
                    selected = list(reversed(trailing)) if trailing else rows[-min(n, 3):]
            else:
                # Primeira leitura sem badge: se houver mensagens recebidas no fim, lê só esse bloco novo
                trailing = []
                for r in reversed(rows):
                    if r.get("mine"):
                        break
                    trailing.append(r)
                selected = list(reversed(trailing))[-n:] if trailing else rows[-min(n, 3):]
        else:
            selected = rows[-n:]

        self._seen_ids[tk] = rows[-1]["id"]
        self._vip_notified.pop(tk, None)
        self._save_seen()

        out = []
        for r in selected:
            who = r.get("who")
            text = r.get("text") or ""
            mine = bool(r.get("mine"))
            if r.get("isAudio") and transcribe and not already_seen:
                try:
                    b64 = page.evaluate(_EXTRACT_AUDIO_B64_JS, r.get("id"))
                    if b64:
                        audio_txt = (transcribe(base64.b64decode(b64)) or "").strip()
                        if audio_txt:
                            text = f"[áudio: {audio_txt}]"
                except Exception:
                    pass
            out.append([who, text, mine])
        return out, already_seen

    def _read(self, title, n=5):
        msgs, _ = self._read_chat(title, n=n, only_new=False, transcribe=None)
        return msgs

    def _send(self, title, text):
        page, _ = self._go(title)
        box = page.locator("#main footer [contenteditable=true]")
        box.click()
        page.keyboard.insert_text(text)
        page.keyboard.press("Enter")
        page.wait_for_timeout(2500)
        data = page.evaluate(_READ_MESSAGES_JS, 2)
        rows = data.get("messages") or []
        if not rows or not rows[-1].get("mine") or _key(rows[-1].get("text", "")) != _key(text):
            raise RuntimeError("a mensagem não apareceu como enviada")
        self._seen_ids[_key(title)] = rows[-1]["id"]
        self._save_seen()

    def _unread_detailed(self):
        page = self._open()
        try:
            box = page.locator('input[data-tab="3"]')
            if box.input_value():
                box.fill("")
                page.wait_for_timeout(600)
        except Exception:
            pass
        return page.evaluate(_UNREAD_LIST_JS) or []

    def _unread(self):
        items = self._unread_detailed()
        # Ignora conversas silenciadas e ordena primeiro pessoas, depois grupos
        active = [it for it in items if not it.get("muted")]
        people = [(it["title"], it["count"]) for it in active if not it.get("group")]
        groups = [(it["title"], it["count"]) for it in active if it.get("group")]
        return people + groups

    # API pública (qualquer thread)
    def find(self, name):
        return self._call(self._find, name)

    def read(self, title, n=5):
        return self._call(self._read, title, n)

    def read_new(self, title, n=5, only_new=True, transcribe=None):
        return self._call(self._read_chat, title, n, only_new, transcribe)

    def send(self, title, text):
        return self._call(self._send, title, text)

    def unread(self):
        return self._call(self._unread)

    def unread_categorized(self):
        items = self._call(self._unread_detailed)
        active = [it for it in items if not it.get("muted")]
        people = [(it["title"], it["count"]) for it in active if not it.get("group")]
        groups = [(it["title"], it["count"]) for it in active if it.get("group")]
        muted_count = sum(1 for it in items if it.get("muted"))
        return {"people": people, "groups": groups, "muted_skipped": muted_count}


def login():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = _launch(pw, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(URL)
        print("Leia o QR Code com o WhatsApp do celular (Aparelhos conectados → Conectar um aparelho).")
        page.wait_for_selector("#pane-side", timeout=300_000)
        print("Vinculado! Esperando sincronizar…")
        page.wait_for_timeout(20_000)
        ctx.close()
        print("Pronto.")


if __name__ == "__main__" and sys.argv[1:] == ["login"]:
    login()
