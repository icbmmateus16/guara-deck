/* Guará — interface do tablet. ES5 puro (WebView do Android 4.4 não tem Promise, fetch nem let). */
(function () {
  'use strict';

  var TOKEN = (location.search.match(/[?&]t=([^&]+)/) || [])[1] || '';
  var NATIVE = window.CapiNative || null;
  var DIM_LEVEL = 0.02;
  var AMBIENT_MS = 120000;      // 2 min sem toque no painel: o Guará ocupa a tela toda
  var IDLE_DIM_MS = 600000;     // 10 min sem toque e nada acontecendo: escurece
  var AWAY_DIM_MS = 900000;     // PC parado há 15 min: escurece mesmo com agente trabalhando
  var ENGINE_NAMES = { claude: 'Claude', codex: 'GPT', agy: 'Gemini', gemini: 'Gemini' };
  var ENGINE_FULL = { claude: 'Claude', codex: 'GPT (Codex)', agy: 'Gemini (Antigravity)', gemini: 'Gemini' };

  function $(id) { return document.getElementById(id); }
  function show(el, on) { el.className = el.className.replace(/\s*hidden/g, '') + (on ? '' : ' hidden'); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function ago(ts) {
    var s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 3600) return 'há ' + Math.max(1, Math.round(s / 60)) + ' min';
    if (s < 86400) return 'há ' + Math.round(s / 3600) + ' h';
    return 'há ' + Math.round(s / 86400) + ' d';
  }
  function hhmm(ts) {
    var d = new Date(ts * 1000), h = d.getHours(), m = d.getMinutes();
    return (h < 10 ? '0' : '') + h + ':' + (m < 10 ? '0' : '') + m;
  }
  function when(ts) {
    var d = new Date(ts * 1000), today = new Date();
    if (d.toDateString() === today.toDateString()) return hhmm(ts);
    return ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb'][d.getDay()] + ' ' + hhmm(ts);
  }

  var S = {
    agent: { mood: 'idle', sessions: [], permissions: [], subagents: 0 },
    stats: {}, media: {}, volume: {}, shortcuts: [], missions: [], mission: null, toggles: {}, quota: {}, pc: {},
    dev: null, connected: false, lastEvent: 0, cpuHist: [], tab: 'inicio', missionClosed: null,
    pcIdle: 0, permShown: null, permSel: null, composeConversational: false
  };

  // ------------------------------------------------------------ rede

  function api(method, path, body, cb) {
    var x = new XMLHttpRequest();
    x.open(method, path + (path.indexOf('?') < 0 ? '?' : '&') + 't=' + TOKEN, true);
    x.setRequestHeader('Content-Type', 'application/json');
    x.timeout = 20000;
    x.onreadystatechange = function () {
      if (x.readyState !== 4) return;
      var data = null;
      try { data = JSON.parse(x.responseText); } catch (e) {}
      if (cb) cb(x.status, data);
    };
    x.send(body ? JSON.stringify(body) : null);
  }

  function act(path, body, okMsg, cb) {
    api('POST', path, body, function (code, d) {
      if (code === 200) { if (okMsg) toast(okMsg); if (cb) cb(d); }
      else toast('Não deu certo: ' + ((d && (d.error || d.info)) || 'erro ' + code));
    });
  }

  var es = null, lostTimer = null;

  function on(name, fn) { es.addEventListener(name, function (e) { fn(JSON.parse(e.data)); }); }

  function connect() {
    if (es) { try { es.close(); } catch (e) {} }
    es = new EventSource('/events?t=' + TOKEN);
    on('hello', function (d) {
      if (S.uiVer && d.ui_ver && S.uiVer !== d.ui_ver) { hardReload(); return; }
      S.uiVer = d.ui_ver || '';
      S.shortcuts = d.shortcuts; S.missions = d.missions;
      renderDock(); renderMissions();
      onAgent(d.agent); onStats(d.stats); onMedia(d.media); onVolume(d.volume);
      onToggles(d.toggles || {}); onQuota(d.quota || {}); onPC(d.pcctl || {});
      if (d.mission) onMission(d.mission);
      if (d.voice) onVoice(d.voice);
      if (d.sky && Guara.setSky) Guara.setSky(d.sky);
      renderActivity(d.activity || []);
      setConnected(true);
    });
    on('agent', function (d) { onAgent(d); alive(); });
    on('stats', function (d) { onStats(d); alive(); });
    on('pc', function (d) { S.pcIdle = d.idle_ms || 0; });
    on('media', onMedia);
    on('volume', onVolume);
    on('mission', onMission);
    on('toggles', onToggles);
    on('quota', onQuota);
    on('pcctl', onPC);
    on('attention', function () { Power.wake(); });
    on('say', function (d) { Voice.play(d); });
    on('thinking', function (d) { Voice.thinking(d.text, d.id); });
    on('heard', function (d) { Voice.heard(d); });
    on('voice', onVoice);
    on('activity', renderActivity);
    on('style', function () { location.reload(); });
    on('sky', function (d) { if (Guara.setSky) Guara.setSky(d); });
    on('reload', hardReload);
    es.onerror = function () {
      setConnected(false);
      if (es.readyState === 2) setTimeout(connect, 4000);
    };
  }

  function alive() { S.lastEvent = Date.now(); if (!S.connected) setConnected(true); }

  function setConnected(ok) {
    S.connected = ok;
    if (ok) S.lastEvent = Date.now();
    $('conn').className = ok ? 'on' : '';
    $('conn').lastChild.textContent = ok ? 'online' : 'offline';
    clearTimeout(lostTimer);
    if (ok) { show($('offline'), false); return; }
    lostTimer = setTimeout(function () {
      show($('offline'), true);
      if (NATIVE && NATIVE.lost) NATIVE.lost();
    }, 8000);
  }

  setInterval(function () {
    if (S.connected && Date.now() - S.lastEvent > 12000) setConnected(false);
    api('GET', '/api/ping', null, null);
  }, 15000);

  // ------------------------------------------------------------ ícones (SVG de linha)

  var ICONS = {
    home: '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
    git: '<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="8" r="2.5"/><path d="M6 8.5v7M18 10.5c0 4-6 3-11 6"/>',
    box: '<path d="M3 7l9-4 9 4v10l-9 4-9-4z"/><path d="M3 7l9 4 9-4M12 11v10"/>',
    spark: '<path d="M12 3l2.2 6.8L21 12l-6.8 2.2L12 21l-2.2-6.8L3 12l6.8-2.2z"/>',
    monitor: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 21h8M12 16v5"/>',
    tablet: '<rect x="2" y="5" width="20" height="14" rx="2.5"/><path d="M18 12h.01"/>',
    bell: '<path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 20a2 2 0 0 0 4 0M3 3l18 18"/>',
    micoff: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 11 4.6M12 17.5V21M3 3l18 18"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>',
    moon: '<path d="M20 14.5A8.5 8.5 0 1 1 9.5 4 6.5 6.5 0 0 0 20 14.5z"/>',
    coffee: '<path d="M4 9h13v5a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5z"/><path d="M17 10h1.5a2.5 2.5 0 0 1 0 5H17M8 3v3M12 3v3"/>',
    lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    camera: '<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
    contrast: '<circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor"/>',
    power: '<path d="M12 3v8M6.3 6.3a8 8 0 1 0 11.4 0"/>',
    bt: '<path d="M7 7l10 10-5 4V3l5 4L7 17"/>',
    code: '<path d="M16 18l6-6-6-6M8 6l-6 6 6 6"/>',
    term: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M7 9l3 3-3 3M13 15h4"/>',
    claude: '<path d="M12 2v6M12 16v6M2 12h6M16 12h6M5 5l4 4M15 15l4 4M19 5l-4 4M9 15l-4 4"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    web: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    chat: '<path d="M20 12a8 8 0 0 1-11.6 7.1L4 20l1-4.2A8 8 0 1 1 20 12z"/>',
    kbd: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M8 9h8M8 13h5"/>',
    rec: '<rect x="3" y="6" width="13" height="12" rx="3"/><path d="M16 10l5-3v10l-5-3"/>',
    note: '<path d="M6 3h8l5 5v13H6z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.9 4.9L7 7M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1L7 17M17 7l2.1-2.1"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    sundim: '<circle cx="12" cy="12" r="4"/><path d="M12 4v.01M12 20v.01M4 12h.01M20 12h.01M6.3 6.3h.01M17.7 17.7h.01M6.3 17.7h.01M17.7 6.3h.01"/>',
    eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    heart: '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8l1 1.1L12 21.3l7.8-7.8 1-1.1a5.5 5.5 0 0 0 0-7.8z"/>',
    bolt: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    expand: '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    play: '<path d="M8 5l11 7-11 7z" fill="currentColor"/>',
    pause: '<path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z" fill="currentColor"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/>',
    restart: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/>',
    next: '<path d="M5 5l10 7-10 7z" fill="currentColor"/><path d="M19 5v14"/>',
    prev: '<path d="M19 5L9 12l10 7z" fill="currentColor"/><path d="M5 5v14"/>',
    vol: '<path d="M4 9h4l5-4v14l-5-4H4z"/><path d="M16.5 9a4 4 0 0 1 0 6M19 6.5a8 8 0 0 1 0 11"/>',
    volx: '<path d="M4 9h4l5-4v14l-5-4H4z"/><path d="M17 9.5l5 5M22 9.5l-5 5"/>',
    send: '<path d="M21 3L10 14M21 3l-6.5 18-4.5-7-7-4.5z"/>',
    shield: '<path d="M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6z"/><path d="M12 8v4M12 16h.01"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>',
    music: '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
    gpt: '<circle cx="12" cy="12" r="9"/><path d="M8 12h8M12 8v8"/>',
    github: '<path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.4 5.4 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"/><path d="M9 18c-4.51 2-5-2-7-2"/>'
  };

  function svg(name, size) {
    return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"' +
      ' stroke-linecap="round" stroke-linejoin="round">' + (ICONS[name] || ICONS.spark) + '</svg>';
  }

  function setIcon(el, name, size) {
    var old = el.querySelector('svg');
    if (old) el.removeChild(old);
    var tmp = document.createElement('div');
    tmp.innerHTML = svg(name, size || 20);
    el.insertBefore(tmp.firstChild, el.firstChild);
  }

  function paintStaticIcons() {
    var els = document.querySelectorAll('[data-icon]');
    for (var i = 0; i < els.length; i++) {
      var c = els[i].className, id = els[i].id, size = 18;
      if (/\bnav\b/.test(c)) size = 21;
      else if (/\bbrk\b/.test(c)) size = 19;
      else if (/\bplay\b/.test(c)) size = 20;
      else if (/\bbadge\b/.test(c)) size = 24;
      else if (/\bico\b/.test(c)) size = 19;
      else if (/\bachip\b/.test(c)) size = 18;
      else if (/\bgic\b/.test(c)) size = 17;
      else if (/\broff\b/.test(c)) size = 20;
      else if (id === 'fullbtn') size = 13;
      else if (id === 'micicon') size = 22;
      else if (id === 'amb-micicon') size = 26;
      else if (id === 'noart') size = 20;
      setIcon(els[i], els[i].getAttribute('data-icon'), size);
    }
  }

  function tint(hex, alpha) {
    var n = parseInt((hex || '#E85D35').slice(1), 16);
    return 'rgba(' + (n >> 16 & 255) + ',' + (n >> 8 & 255) + ',' + (n & 255) + ',' + alpha + ')';
  }

  function ibtn(icon, actName, attrs, cls) {
    return '<div class="ibtn ' + (cls || '') + '" data-act="' + actName + '" ' + (attrs || '') + '>' + svg(icon, 17) + '</div>';
  }

  function whoLabel(s) {
    if (s.agent === 'guara') return 'Guará' + (s.source ? ' · ' + s.source : '');
    var name = s.agent === 'codex' ? 'Codex' : 'Claude';
    return s.source ? name + ' no ' + s.source : name;
  }
  function whoTag(s, extra) {
    return '<span class="who ' + (s.agent || 'claude') + (extra ? ' ' + extra : '') + '">' + esc(whoLabel(s)) + '</span>';
  }

  // ------------------------------------------------------------ agentes

  var MOOD_TAG = {
    sleeping: ['dormindo', ''], idle: ['de boa', ''], thinking: ['pensando', 'work'],
    reading: ['lendo', 'work'], typing: ['escrevendo', 'work'], running: ['rodando', 'work'],
    searching: ['procurando', 'work'], waiting: ['precisa de você', 'wait'], done: ['pronto', 'done'],
    error: ['erro', 'err']
  };
  var IDLE_LINES = [
    'Tudo calmo aqui no cerrado.',
    'De orelha em pé nos seus agentes.',
    'Toque no microfone pra trocar uma ideia comigo.',
    'Vigiando o PC enquanto você programa.'
  ];
  var FRUIT_LINES = ['Nham! Fruta-do-lobo, minha preferida!', 'Lobeira fresquinha! Valeu, parceiro!',
    'Hmm, essa tava docinha!', 'Combustível de guará: lobeira. Bora codar!'];
  var fruitCount = 0;
  var PET_LINES = [
    'Opa! Tô ligadão aqui no cerrado!',
    'Valeu pelo carinho! Bora mandar ver no código?',
    'De orelha em pé por aqui, parceiro!',
    'Hehe, tudo na paz por aqui! Precisa de algo?'
  ];
  var idleLine = IDLE_LINES[0], idleLineAt = 0, petCount = 0;

  function onAgent(a) {
    var before = S.agent.mood;
    S.agent = a;
    Guara.setMood(a.mood, a.subagents);
    var tag = MOOD_TAG[a.mood] || MOOD_TAG.idle;
    var top = (a.sessions || [])[0];
    $('moodtag').lastChild.textContent = top && a.mood !== 'idle' && a.mood !== 'sleeping' ? whoLabel(top) + ': ' + tag[0] : tag[0];
    $('moodtag').className = tag[1];

    var phrase = a.phrase, sub = top ? whoLabel(top) + ' · ' + (top.project || 'sessão') : '';
    if (a.mood === 'done' && a.summary) { phrase = 'Prontinho!'; sub = a.summary; }
    if (a.mood === 'sleeping') { phrase = 'Cochilando no cerrado…'; sub = 'Toque na tela ou fale comigo para acordar.'; }
    if (a.mood === 'idle' && !a.permissions.length) {
      if (Date.now() - idleLineAt > 30000) {
        idleLine = IDLE_LINES[Math.floor(Math.random() * IDLE_LINES.length)];
        idleLineAt = Date.now();
      }
      phrase = idleLine;
      sub = 'Toque no microfone ou em escrever.';
    }
    if (a.subagents) sub = a.subagents + (a.subagents > 1 ? ' subagentes em paralelo' : ' subagente em paralelo') + (sub ? ' · ' + sub : '');
    if (!Voice.holdBubble()) {
      $('clabel').textContent = 'GUARÁ';
      $('clabel').className = '';
      $('phrase').textContent = phrase || '';
      $('sub').textContent = sub;
    }
    if (before !== a.mood && (a.mood === 'waiting' || a.mood === 'done' || a.mood === 'error')) Power.wake();
    renderSessions();
    renderPermission();
    Ambient.update();
  }

  function renderSessions() {
    var list = S.agent.sessions || [], html = '';
    var limited = S.quota && S.quota.limited;
    for (var i = 0; i < list.length && i < 2; i++) {
      var s = list[i], tag = MOOD_TAG[s.mood] || MOOD_TAG.idle;
      var busy = tag[1] === 'work' ? 'live' : (tag[1] === 'wait' ? 'wait' : '');
      html += '<div class="agent">' + whoTag(s, busy) + '<div class="ainfo"><div class="aproj ellipsis">' + esc(s.project || 'sessão') +
        '</div><div class="awhat ellipsis">' + esc(s.mood === 'done' && s.summary ? s.summary : s.phrase || tag[0]) + '</div></div>' +
        (limited && s.agent === 'claude' ? '<div class="ho" data-act="handoff" data-id="' + esc(s.id) + '">Seguir no GPT</div>' : '') + '</div>';
    }
    $('sessions').innerHTML = html || '<div class="empty">Nenhum agente trabalhando agora.</div>';
    $('sesscount').textContent = list.length ? String(list.length) : '';
  }

  function renderPermission() {
    var perms = S.agent.permissions || [];
    var p = null;
    for (var i = 0; i < perms.length; i++) if (perms[i].id === S.permSel) p = perms[i];
    p = p || perms[0];
    show($('perm'), !!p);
    if (!p) { S.permShown = null; S.permSel = null; return; }
    ScreenOff.exit();  // pedido de aprovação acende a tela, como uma notificação
    Ambient.exit();   // aprovar precisa dos botões: sai da tela cheia automaticamente
    if (S.permShown !== p.id) {
      S.permShown = p.id;
      S.permStart = Date.now() - p.age * 1000;
      Power.wake();
    }
    var who = { agent: p.mission ? 'guara' : 'claude', source: p.source };
    $('perm-who').innerHTML = whoTag(who) + ' <span class="meta">em ' + esc(p.project || 'projeto') + '</span>';
    $('perm-tool').textContent = p.tool === 'Bash' ? 'Quer rodar este comando:' : (p.tool === 'Edit' || p.tool === 'Write' ? 'Quer alterar o arquivo:' : 'Quer usar ' + p.tool + ':');
    $('perm-detail').textContent = p.detail || '';
    var q = '';
    for (var j = 0; j < perms.length; j++) {
      if (perms[j].id === p.id) continue;
      var w = { agent: perms[j].mission ? 'guara' : 'claude', source: perms[j].source };
      q += '<div class="pq" data-act="perm-pick" data-id="' + esc(perms[j].id) + '">' + whoTag(w) +
        '<span class="code ellipsis">' + esc(perms[j].project + ': ' + perms[j].detail) + '</span></div>';
    }
    $('perm-queue').innerHTML = q ? '<div class="meta">Também esperando você:</div>' + q : '';
    S.permTimeout = p.timeout;
  }

  setInterval(function () {
    if (!S.permShown) return;
    var left = 1 - (Date.now() - S.permStart) / (S.permTimeout * 1000);
    $('perm-time').style.width = Math.max(0, left * 100) + '%';
  }, 500);

  function renderActivity(list) {
    var html = '', verbs = /^(Claude terminou|Você aprovou|Você negou|Claude aberto|Claude parou|Você:)/;
    for (var i = 0; i < list.length && i < 4; i++) {
      var text = esc(list[i].text).replace(verbs, '<b>$1</b>');
      html += '<div class="act ' + esc(list[i].kind) + '"><span class="when">' + hhmm(list[i].t) + '</span><span class="atext ellipsis">' + text + '</span></div>';
    }
    $('activity').innerHTML = html || '<div class="empty">Sem atividade ainda.</div>';
  }

  // ------------------------------------------------------------ créditos das IAs

  function remaining(w, label) {
    if (!w || w.left == null) {
      return '<div class="win"><b>—</b><div class="wl">' + label + (w && w.renewed ? ': renovou, toque em atualizar' : ': sem leitura') +
        '</div><i class="meter"><u></u></i></div>';
    }
    var left = w.left, cls = left <= 10 ? 'hot' : (left <= 30 ? 'warn' : '');
    var reset = w.renewed ? 'já renovou' : (w.resets ? 'renova ' + when(w.resets) : '');
    return '<div class="win"><b>' + left + '%<small>restam</small></b><div class="wl">' + label + (reset ? ', ' + reset : '') +
      '</div><i class="meter"><u class="' + cls + '" style="width:' + left + '%"></u></i></div>';
  }

  function onQuota(q) {
    S.quota = q || {};
    var order = q.order || [], meters = q.meters || {}, html = '';
    for (var i = 0; i < order.length; i++) {
      var e = order[i], m = meters[e] || {};
      var state = e === q.engine ? 'em uso agora' : (e === 'claude' && q.limited ? 'esgotado até ' + when(q.until) : 'reserva');
      html += '<div class="engine' + (e === q.engine ? ' cur' : '') + '"><div class="ehead"><span class="ename">' + esc(ENGINE_FULL[e] || e) +
        '</span><span class="order">' + (i + 1) + 'ª opção</span><span class="state">' + state + '</span></div>';
      if (e === 'agy') {
        html += '<div class="solo">O Antigravity não informa o limite. O Guará usou ' + ((m.uses || 0) === 1 ? '1 vez' : (m.uses || 0) + ' vezes') + ' hoje.</div>';
      } else {
        html += '<div class="wins">' + remaining(m.five_hour, '5 horas') + remaining(m.seven_day, 'semana') + '</div>';
        if (m.src === 'cache' && m.at) html += '<div class="solo">Leitura de ' + ago(m.at) + '. Toque em atualizar para ver agora.</div>';
      }
      html += '</div>';
    }
    $('quota').innerHTML = html;

    var mini = '';
    for (var k = 0; k < order.length; k++) {
      var en = order[k], mm = meters[en] || {}, f = mm.five_hour;
      var known = f && f.left != null;
      var val = en === 'agy' ? (mm.uses || 0) + '<small>usos hoje</small>' : (known ? f.left + '%<small>em 5 h</small>' : '—<small>sem leitura</small>');
      var pctLeft = en === 'agy' ? 100 : (known ? f.left : 0);
      mini += '<div class="credit"><div class="cn">' + esc(ENGINE_NAMES[en] || en) + (en === q.engine ? '<i>ativo</i>' : '') + '</div><b>' + val +
        '</b><i class="meter"><u class="' + (pctLeft <= 10 ? 'hot' : (pctLeft <= 30 ? 'warn' : '')) + '" style="width:' + pctLeft + '%"></u></i></div>';
    }
    $('credits').innerHTML = mini;
    $('q-note').textContent = 'Se a IA da vez esgotar, o Guará alterna para a próxima automaticamente.';
    renderSessions();
  }

  // ------------------------------------------------------------ missões

  function renderMissions() {
    var html = '';
    for (var i = 0; i < S.missions.length; i++) {
      var m = S.missions[i];
      html += '<div class="tile" data-act="mission" data-id="' + esc(m.id) + '"><div class="tic" style="background:' + tint(m.color, 0.16) +
        ';color:' + (m.color || '#E85D35') + '">' + svg(m.icon, 18) + '</div><div class="t ellipsis">' + esc(m.title) +
        '</div><div class="d ellipsis">' + esc(m.desc) + '</div></div>';
    }
    html += '<div class="tile ask" data-act="compose-mission"><div class="tic" style="background:rgba(232,93,53,0.2);color:#E85D35">' +
      svg('send', 18) + '</div><div class="t">Pedir algo</div><div class="d">Escreva qualquer tarefa</div></div>';
    $('missions').innerHTML = html;
  }

  function onMission(m) {
    S.mission = m;
    if (Voice.waiting && (!Voice.waiting.id || Voice.waiting.id === m.id)) {
      Voice.waiting.id = m.id;
      if (m.status !== 'running') {
        Voice.waiting = null;
        Voice.bubble(m.text || (m.status === 'cancelled' ? 'Tudo bem, parei por aqui.' : 'Prontinho!'), '', 15000, 'GUARÁ');
      }
    }
    if (Ambient.on && m.status === 'running' && !Voice.waiting) {
      var step = m.steps && m.steps.length ? m.steps[m.steps.length - 1] : 'Pensando com ' + (ENGINE_NAMES[m.engine] || 'a IA') + '…';
      Voice.bubble($('phrase').textContent, step, 8000, 'PENSANDO…');
    }
    if (S.missionClosed === m.id) return;
    show($('mission'), true);
    $('m-title').textContent = m.title + (m.engine ? ' · ' + (ENGINE_NAMES[m.engine] || m.engine) : '');
    var st = { running: ['rodando', 'run'], done: ['pronta', 'ok'], error: ['falhou', 'bad'], cancelled: ['parada', ''] }[m.status] || [m.status, ''];
    $('m-status').textContent = st[0];
    $('m-status').className = 'tag ' + st[1];
    var steps = '';
    var list = m.status === 'running' ? m.steps.slice(-4) : m.steps.slice(-2);
    for (var i = 0; i < list.length; i++) steps += '<div class="ellipsis">' + esc(list[i]) + '</div>';
    $('m-steps').innerHTML = steps;
    $('m-text').textContent = (m.text || (m.status === 'running' ? 'Trabalhando…' : '')).replace(/[*_`#]+/g, '');
    show($('m-cancel'), m.status === 'running');
    show($('m-close'), m.status !== 'running');
    if (m.status !== 'running') Power.wake();
    Ambient.update();
  }

  // ------------------------------------------------------------ início: mídia, volume, disjuntores, apps

  var lastArt = '';

  function onMedia(m) {
    S.media = m || {};
    var has = !!S.media.player;
    $('mtitle').textContent = has ? (S.media.title || 'Sem título') : 'Nada tocando';
    $('martist').textContent = has ? (S.media.artist || S.media.player) : 'Toque uma música ou vídeo no PC';
    setIcon($('pp'), S.media.status === 'Playing' ? 'pause' : 'play', 20);
    var art = has && S.media.art ? S.media.art : '';
    if (art !== lastArt) {
      lastArt = art;
      $('art').style.display = 'none';
      if (art) $('art').src = '/api/art?t=' + TOKEN + '&k=' + encodeURIComponent(art.slice(-40));
    }
    Ambient.update();
  }
  $('art').onload = function () { this.style.display = 'block'; };
  $('art').onerror = function () { this.style.display = 'none'; };

  function onVolume(v) {
    S.volume = v || {};
    var lvl = S.volume.level == null ? 0 : S.volume.level;
    if (!Slider.drag || Slider.drag.kind !== 'vol') paintSlider('vol', lvl);
    var fills = [$('vbar'), $('v2bar')];
    for (var i = 0; i < fills.length; i++) fills[i].firstChild.firstChild.className = 'fill' + (S.volume.muted ? ' muted' : '');
    $('vtxt').textContent = $('v2txt').textContent = S.volume.muted ? 'mudo' : lvl + '%';
    $('mute').className = 'ibtn ghost' + (S.volume.muted ? ' on' : '');
    setIcon($('mute'), S.volume.muted ? 'volx' : 'vol', 18);
  }

  function onToggles(t) {
    S.toggles = t || {};
    var tiles = document.querySelectorAll('#toggles .brk.tg');
    for (var i = 0; i < tiles.length; i++) {
      tiles[i].className = 'brk tg' + (S.toggles[tiles[i].getAttribute('data-name')] ? ' on' : '');
    }
  }

  // Ícone de verdade do app (o mesmo do menu do Ubuntu); sem ele, o desenho em linha da casa
  function appIcon(a, size) {
    if (a.img) return '<img class="aimg" src="' + a.img + '?t=' + TOKEN + '" width="' + size + '" height="' + size + '" alt="">';
    return '<i class="asvg" style="color:' + (a.color || '#C9CFE5') + '">' + svg(a.icon, Math.round(size * 0.55)) + '</i>';
  }

  // Início: os cinco mais usados, grandes, e "Todos" leva para a aba Apps
  function renderDock() {
    var html = '', n = 0;
    for (var k = 0; k < S.shortcuts.length && n < 5; k++) {
      var s = S.shortcuts[k];
      if (s.icon === 'lock' || s.icon === 'camera' || s.icon === 'gear') continue;
      n++;
      html += '<div class="app" data-act="shortcut" data-id="' + esc(s.id) + '" data-label="' + esc(s.label) + '">' +
        appIcon(s, 34) + '<div class="ellipsis">' + esc(s.label) + '</div></div>';
    }
    html += '<div class="app" data-act="tab" data-tab="apps"><i class="asvg">' + svg('grid', 22) + '</i><div>Todos</div></div>';
    $('dock').innerHTML = html;
  }

  function loadApps() {
    api('GET', '/api/apps', null, function (code, d) {
      if (code !== 200 || !d || !d.apps) { $('appgrid').innerHTML = '<div class="empty">Não consegui ler os apps do PC.</div>'; return; }
      var html = '';
      for (var i = 0; i < d.apps.length; i++) {
        var a = d.apps[i];
        html += '<div class="appt" data-act="' + (a.kind === 'app' ? 'app' : 'shortcut') + '" data-id="' + esc(a.id) +
          '" data-label="' + esc(a.label) + '">' + appIcon(a, 56) + '<span>' + esc(a.label) + '</span></div>';
      }
      $('appgrid').innerHTML = html;
    });
  }

  // ------------------------------------------------------------ PC: tela, som, energia

  function onPC(p) {
    S.pc = p || {};
    if (S.pc.brightness != null && !(Slider.drag && Slider.drag.kind === 'pcbright')) {
      paintSlider('pcbright', S.pc.brightness);
      $('ptxt').textContent = S.pc.brightness + '%';
    }
    if (S.pc.mic && !(Slider.drag && Slider.drag.kind === 'mic')) {
      paintSlider('mic', S.pc.mic.level || 0);
      $('mtxt').textContent = S.pc.mic.muted ? 'mudo' : (S.pc.mic.level || 0) + '%';
    }
    var segs = $('profiles').children;
    for (var i = 0; i < segs.length; i++) segs[i].className = segs[i].getAttribute('data-name') === S.pc.profile ? 'on' : '';
    $('bt').className = 'switch' + (S.pc.bluetooth ? ' on' : '');
    var b = S.pc.battery;
    if (b && b.pct != null) {
      var charging = b.state === 'charging' || b.state === 'fully-charged';
      $('g-bat').textContent = b.pct + '%';
      $('g-batl').textContent = 'BATERIA';
      $('d-bat').textContent = charging ? 'AC' : '';
      setBar('m-bat', 100 - b.pct, true);
      $('m-bat').style.width = b.pct + '%';
      $('batinfo').textContent = b.pct + '%' + (b.state === 'fully-charged' ? ' · carregada' :
        charging ? (b.left ? ' · cheia em ' + b.left : ' · carregando') : (b.left ? ' · ' + b.left + ' restantes' : ''));
    }
    show($('batrow'), !!(b && b.pct != null));
    var sinks = S.pc.sinks || [], html = '';
    var cur = '';
    for (var k = 0; k < sinks.length; k++) if (sinks[k].default) cur = sinks[k].name;
    if (sinks.length) {
      html = '<div class="gcell"><i class="gic gray">' + svg('music', 17) + '</i><span class="gname">Saída de som</span>' +
        '<span class="gval ellipsis">' + esc(sinks.length > 1 ? '' : sinks[0].name) + '</span></div>';
    }
    if (sinks.length > 1) {
      for (var j = 0; j < sinks.length; j++) {
        html += '<div class="gcell tap ind" data-act="sink" data-id="' + esc(sinks[j].id) + '"><span class="gname ellipsis">' +
          esc(sinks[j].name) + '</span>' + (sinks[j].default ? '<i class="gcheck">' + svg('check', 18) + '</i>' : '') + '</div>';
      }
    }
    $('sinks').innerHTML = html;
  }

  // ------------------------------------------------------------ projetos e dev

  var devTimer = null;

  function loadDev() {
    api('GET', '/api/dev', null, function (code, d) {
      if (code !== 200 || !d) return;
      S.dev = d;
      renderProjects(); renderDocker(); renderPorts(); renderOllama();
    });
  }

  function renderProjects() {
    var list = S.dev.projects, html = '', repos = 0, dirty = 0;
    for (var n = 0; n < list.length; n++) { if (list[n].git) { repos++; if (list[n].changes) dirty++; } }
    $('projsum').textContent = repos + ' repositórios · ' + dirty + ' com alterações';
    for (var i = 0; i < list.length && i < 30; i++) {
      var p = list[i], meta = '';
      if (p.git) {
        meta += '<span class="br">' + esc(p.branch || 'sem branch') + '</span>';
        if (p.changes) meta += '<span class="chg">' + p.changes + (p.changes > 1 ? ' alterações' : ' alteração') + '</span>';
        if (p.ahead) meta += '<span class="ahead">↑' + p.ahead + '</span>';
        meta += '<span>' + ago(p.ts) + '</span>';
      } else {
        meta += '<span>pasta local · ' + ago(p.ts) + '</span>';
      }
      var lastCommit = p.last ? '<div class="plast ellipsis">' + esc(p.last) + '</div>' : '';
      html += '<div class="proj"><div class="pinfo" data-act="proj" data-a="folder" data-path="' + esc(p.path) + '">' +
        '<div class="pname ellipsis">' + esc(p.name) + '</div><div class="pmeta ellipsis">' + meta + '</div>' + lastCommit + '</div>' +
        ibtn('code', 'proj', 'data-a="code" data-path="' + esc(p.path) + '"') +
        ibtn('term', 'proj', 'data-a="term" data-path="' + esc(p.path) + '"') +
        ibtn(S.quota.limited ? 'gpt' : 'claude', 'proj', 'data-a="' + (S.quota.limited ? 'codex' : 'claude') + '" data-path="' + esc(p.path) + '"', 'acc') +
        (p.remote ? ibtn('github', 'proj', 'data-a="github" data-path="' + esc(p.path) + '"') : '<div class="ibtn" style="visibility:hidden"></div>') +
        '</div>';
    }
    $('projects').innerHTML = html || '<div class="empty">Nenhuma pasta em ~/Área de trabalho/PROJETOS.</div>';
  }

  function renderDocker() {
    var groups = {}, order = [], list = S.dev.docker, total = 0, up = 0;
    for (var i = 0; i < list.length; i++) {
      var c = list[i];
      if (!groups[c.group]) { groups[c.group] = []; order.push(c.group); }
      groups[c.group].push(c);
      total++; if (c.state === 'running') up++;
    }
    $('dockersum').textContent = list.length ? up + ' de ' + total + ' rodando' : '';
    order.sort(function (a, b) { return running(groups[b]) - running(groups[a]); });
    var html = '';
    for (var g = 0; g < order.length; g++) {
      var items = groups[order[g]], n = running(items), names = [];
      for (var k = 0; k < items.length; k++) names.push(items[k].name);
      html += '<div class="dgroup"><div class="dhead"><div class="gname ellipsis">' + esc(order[g]) + '</div>' +
        '<span class="gcount">' + n + '/' + items.length + ' ativos</span>' +
        ibtn(n ? 'stop' : 'play', 'docker', 'data-a="' + (n ? 'stop' : 'start') + '" data-names="' + esc(names.join(' ')) + '"', n ? 'stop' : 'go') + '</div>';
      if (n) {
        for (var j = 0; j < items.length; j++) {
          var ct = items[j], isUp = ct.state === 'running';
          html += '<div class="ctr"><span class="dot' + (isUp ? ' up' : '') + '"></span><div class="cname">' +
            '<div class="ellipsis">' + esc(ct.name) + '</div><div class="cimg code ellipsis">' + esc(ct.image) + '</div></div>' +
            (isUp ? ibtn('restart', 'docker', 'data-a="restart" data-names="' + esc(ct.name) + '"') : '') +
            ibtn(isUp ? 'stop' : 'play', 'docker', 'data-a="' + (isUp ? 'stop' : 'start') + '" data-names="' + esc(ct.name) + '"', isUp ? 'stop' : 'go') + '</div>';
        }
      }
      html += '</div>';
    }
    $('docker').innerHTML = html || '<div class="empty">Nenhum container no Docker.</div>';
  }

  function running(items) {
    var n = 0;
    for (var i = 0; i < items.length; i++) if (items[i].state === 'running') n++;
    return n;
  }

  function renderPorts() {
    var html = '';
    for (var i = 0; i < S.dev.ports.length; i++) {
      var p = S.dev.ports[i];
      html += '<div class="port" data-act="port" data-port="' + p.port + '"><span class="code">:' + p.port + '</span>' + esc(p.label) + '</div>';
    }
    $('ports').innerHTML = html || '<div class="empty">Nenhum servidor escutando.</div>';
  }

  function renderOllama() {
    var html = '';
    for (var i = 0; i < S.dev.ollama.length; i++) {
      var m = S.dev.ollama[i];
      html += '<div class="dgroup"><div class="dhead"><span class="dot up" style="width:8px;height:8px;border-radius:50%;background:#C8E25E;margin-right:9px"></span>' +
        '<div class="gname">' + esc(m.name) + ' <span class="meta code">(' + esc(m.size + ' · ' + m.processor) + ')</span></div>' +
        '<div class="btn small" data-act="ollama-unload" data-name="' + esc(m.name) + '">Liberar VRAM</div></div></div>';
    }
    $('ollama').innerHTML = html || '<div class="empty">Nenhum modelo carregado na GPU.</div>';
  }

  // ------------------------------------------------------------ monitor

  function setBar(id, pct, invert) {
    var el = $(id);
    el.style.width = Math.min(100, pct || 0) + '%';
    var v = invert ? pct : pct;
    el.className = v > 90 ? 'hot' : (v > 75 ? 'warn' : '');
  }

  function gauge(id, val, detail) {
    $('g-' + id).textContent = val == null ? '—' : val + '%';
    if ($('d-' + id)) $('d-' + id).textContent = detail || '';
    setBar('m-' + id, val || 0);
  }

  function fmtRate(b) {
    if (b > 1048576) return (b / 1048576).toFixed(1).replace('.', ',') + ' MB/s';
    if (b > 1024) return Math.round(b / 1024) + ' KB/s';
    return Math.round(b) + ' B/s';
  }

  function onStats(s) {
    if (!s || s.cpu == null) return;
    S.stats = s;
    S.cpuHist.push(s.cpu);
    if (S.cpuHist.length > 90) S.cpuHist.shift();
    if (Power.dim) return;
    gauge('cpu', s.cpu, s.cpu_temp != null ? s.cpu_temp + '°C' : '');
    gauge('ram', s.mem, s.mem_used != null ? String(s.mem_used).replace('.', ',') + 'G' : '');
    gauge('gpu', s.gpu && s.gpu.util != null ? s.gpu.util : null, s.gpu && s.gpu.temp != null ? s.gpu.temp + '°C' : '');
    if (S.tab !== 'pc') return;
    $('cpunow').textContent = s.cpu + '%' + (s.cpu_temp != null ? ' · ' + s.cpu_temp + ' °C' : '');
    $('disk').textContent = s.disk_free + ' GB livres';
    setBar('diskb', s.disk);
    $('net').textContent = '↓ ' + fmtRate(s.down) + '\u2003↑ ' + fmtRate(s.up);
    var h = Math.floor(s.uptime / 3600), mi = Math.floor(s.uptime / 60) % 60;
    $('uptime').textContent = 'ligado há ' + (h ? h + ' h ' : '') + mi + ' min';
    drawSpark();
  }

  function drawSpark() {
    var c = $('spark'), g = c.getContext('2d'), h = S.cpuHist, w = c.width, ht = c.height;
    g.clearRect(0, 0, w, ht);
    g.strokeStyle = 'rgba(255,255,255,0.05)';
    g.lineWidth = 1;
    g.beginPath();
    g.moveTo(0, Math.round(ht * 0.5)); g.lineTo(w, Math.round(ht * 0.5));
    g.stroke();
    if (h.length < 2) return;
    var step = w / 89, x0 = w - (h.length - 1) * step;
    g.beginPath();
    for (var j = 0; j < h.length; j++) {
      var x = x0 + j * step, y = ht - 4 - h[j] / 100 * (ht - 9);
      if (j) g.lineTo(x, y); else g.moveTo(x, y);
    }
    g.strokeStyle = '#0A84FF';
    g.lineWidth = 2;
    g.stroke();
    g.lineTo(x0 + (h.length - 1) * step, ht);
    g.lineTo(x0, ht);
    g.closePath();
    var grad = g.createLinearGradient(0, 0, 0, ht);
    grad.addColorStop(0, 'rgba(10,132,255,0.30)');
    grad.addColorStop(1, 'rgba(10,132,255,0)');
    g.fillStyle = grad;
    g.fill();
  }

  function tabletBattery() {
    if (!NATIVE || !NATIVE.battery) return null;
    try {
      var b = String(NATIVE.battery()).split(',');
      return { pct: parseInt(b[0], 10), charging: b[1] === '1' };
    } catch (e) { return null; }
  }

  // ------------------------------------------------------------ energia do tablet (dormir/acordar)

  var Power = {
    dim: false, level: 1, lastTouch: Date.now(), panelTouch: Date.now(),
    apply: function (v) {
      if (NATIVE && NATIVE.setBrightness) NATIVE.setBrightness(v);
      else show($('veil'), v < 0.5);
    },
    wake: function () {
      Power.lastTouch = Date.now();
      if (!Power.dim) return;
      Power.dim = false;
      Power.apply(Power.level);
      Guara.setAwake(true);
      if (S.stats) onStats(S.stats);
    },
    sleep: function () {
      if (Power.dim) return;
      Power.dim = true;
      Power.apply(DIM_LEVEL);
      Guara.setAwake(false);
    },
    check: function () {
      if (ScreenOff.on || Power.dim || S.permShown || Voice.mic !== 'idle' || Voice.speaking) return;
      var idle = Date.now() - Power.lastTouch;
      var calm = S.agent.mood === 'idle' || S.agent.mood === 'sleeping';
      var away = S.pcIdle > AWAY_DIM_MS;
      if ((calm && idle > IDLE_DIM_MS && S.pcIdle > 60000) || (away && idle > IDLE_DIM_MS)) Power.sleep();
    }
  };
  setInterval(Power.check, 5000);

  // ------------------------------------------------------------ apagar a tela (o botão físico do tablet está ruim)
  // A tela não desliga de verdade: desligada, o Android também desliga o toque. Aqui ela fica preta,
  // o PC apaga a luz de fundo pelo ADB e o toque continua vivo: dois toques religam.

  var ScreenOff = {
    on: false, lastTap: 0, hintTimer: null,
    enter: function () {
      if (ScreenOff.on) return;
      if (Voice.mic !== 'idle' && NATIVE && NATIVE.stopListen) NATIVE.stopListen();
      ScreenOff.on = true;
      show($('screenoff'), true);
      Power.apply(0.01);                                  // mínimo que o Android aceita…
      api('POST', '/api/tablet/backlight', { on: false }, null);   // …e o PC apaga a luz de fundo de vez
      Guara.pause(true);
    },
    exit: function () {
      if (!ScreenOff.on) return;
      ScreenOff.on = false;
      show($('screenoff'), false);
      Power.dim = false;
      Power.apply(Power.level);                           // o Android reacende a luz de fundo
      Guara.pause(false);
      Power.lastTouch = Power.panelTouch = Date.now();
    },
    tap: function () {
      var now = Date.now();
      if (now - ScreenOff.lastTap < 500) { ScreenOff.lastTap = 0; ScreenOff.exit(); return; }
      ScreenOff.lastTap = now;
      $('so-hint').className = 'show';   // dica bem fraca, só para saber que o toque chegou
      clearTimeout(ScreenOff.hintTimer);
      ScreenOff.hintTimer = setTimeout(function () { $('so-hint').className = ''; }, 1500);
    }
  };

  // ------------------------------------------------------------ Modo Guará Vivo (tela cheia interativa)

  // Modo Guará: inspirado nos companheiros de mesa com ESP32 (Clawdmeter, desk-buddy, claude-desktop-buddy).
  // Um personagem só, no centro; o estado cabe numa linha (uma bolinha por sessão de agente); a fala vira um
  // balão de jogo; os botões só aparecem com um toque e somem sozinhos.
  var Ambient = {
    on: false, lastBgTap: 0, trayOpen: false, trayTimer: null, hintUntil: 0,
    enter: function () {
      if (Ambient.on || S.permShown) return;
      if ($('compose').className.indexOf('hidden') < 0) show($('compose'), false);
      Ambient.on = true;
      $('amb-stage').appendChild($('stage'));
      $('stage').className = 'full';
      Guara.resize(10, 102, true, 60);   // 102x60 blocos de 10 px = 1020x600: céu em cima, Guará no centro, chão embaixo
      show($('ambient'), true);
      Ambient.hintUntil = Date.now() + 6000;
      Ambient.tray(false);
    },
    exit: function () {
      if (!Ambient.on) return;
      Ambient.on = false;
      Ambient.tray(false);
      $('left').insertBefore($('stage'), $('left').firstChild);
      $('stage').className = '';
      Guara.resize(6, 65, false, 40);   // 65x40 blocos de 6 px = 390x240
      $('ambient').className = 'hidden';
      Power.lastTouch = Power.panelTouch = Date.now();
    },
    tray: function (on) {
      clearTimeout(Ambient.trayTimer);
      Ambient.trayOpen = on;
      if (on) {
        Ambient.trayTimer = setTimeout(function () {
          Ambient.tray(Voice.mic !== 'idle' || Voice.speaking);   // conversando, os botões ficam
        }, 8000);
      }
      Ambient.update();
    },
    update: function () {
      if (!Ambient.on) return;
      $('amb-clock').textContent = $('clock').textContent;

      var sessions = S.agent.sessions || [], top = sessions[0];
      var busy = top && S.agent.mood !== 'idle' && S.agent.mood !== 'sleeping';
      var dots = '', line = '', quiet = false, dim = false;
      for (var i = 0; i < sessions.length && i < 6; i++) dots += '<i class="' + (MOOD_TAG[sessions[i].mood] || MOOD_TAG.idle)[1] + '"></i>';
      if (!S.connected) {
        dots = '<i class="err"></i>'; line = 'Procurando o PC…'; dim = true;
      } else if (Voice.mic === 'ouvindo') {
        dots = '<i class="listen"></i>'; line = 'Ouvindo você…';
      } else if (Voice.mic !== 'idle') {
        dots = '<i class="work"></i>'; line = 'Entendendo o que você disse…';
      } else if (busy) {
        var name = top.agent === 'codex' ? 'Codex' : (top.agent === 'guara' ? 'Guará' : 'Claude');
        line = '<b>' + esc(name + (top.project ? ' em ' + top.project : '')) + '</b><span class="gap"></span>' +
          esc(top.phrase || (MOOD_TAG[top.mood] || MOOD_TAG.idle)[0]);
      } else if (Date.now() < Ambient.hintUntil) {
        line = 'Toque no céu para ver os botões, no chão para dar uma lobeira. Dois toques voltam ao painel.'; quiet = true;
      } else if (S.agent.mood === 'sleeping') {
        line = 'Cochilando'; quiet = true; dim = true;
      } else {
        line = sessions.length ? 'Agentes de boa, nada pendente' : 'Tudo calmo'; quiet = true;
      }
      $('amb-dots').innerHTML = dots;
      $('amb-line').innerHTML = line;
      $('amb-status').className = quiet ? 'quiet' : '';
      $('ambient').className = (Ambient.trayOpen ? 'tray' : '') + (dim ? ' dim' : '');
      show($('amb-tray'), Ambient.trayOpen);

      var say = Voice.holdBubble();
      $('amb-say').className = (Voice.mic === 'ouvindo' ? 'listen' : '') + (say ? '' : ' hidden');
      if (say) {
        $('amb-speaker').textContent = Voice.speaker || 'GUARÁ';
        $('amb-phrase').textContent = $('phrase').textContent;
        $('amb-sub').textContent = $('sub').textContent;
      }
    },
    action: function (el) {
      var kind = el.getAttribute('data-amb');
      if (kind === 'exit') { Ambient.exit(); return; }
      if (kind === 'screen-off') { ScreenOff.enter(); return; }
      Ambient.tray(true);
      if (kind === 'mic') {
        Voice.toggleMic();
      } else if (kind === 'pet') {
        Guara.pet();
        Voice.bubble(PET_LINES[petCount++ % PET_LINES.length], '', 6000, 'GUARÁ');
        api('POST', '/api/guara/interact', { kind: 'poke' }, null);
      } else if (kind === 'status') {
        Guara.poke();
        Voice.bubble('Deixa eu dar uma conferida no PC…', 'Lendo telemetria e agentes', 9000, 'PENSANDO…');
        api('POST', '/api/guara/interact', { kind: 'status' }, function (code, d) {
          if (code === 200 && d && d.text) Voice.bubble(d.text, '', 11000, 'GUARÁ');
        });
      } else if (kind === 'screen') {
        Voice.bubble('Espiando a tela do seu PC…', 'Capturando e analisando', 16000, 'OLHANDO A TELA…');
        api('POST', '/api/guara/interact', { kind: 'screen' }, function (code, d) {
          if (code !== 200) toast((d && d.info) || 'Não consegui ver a tela agora');
        });
      } else if (kind === 'ask') {
        openCompose(true);
      }
    },
    canvasTap: function (x, y) {
      var now = Date.now();
      if (now - Ambient.lastBgTap < 420) {
        Ambient.lastBgTap = 0;
        Ambient.exit();
        return;
      }
      Ambient.lastBgTap = now;
      if (Guara.hitTest(x, y)) {
        Guara.pet();
        if (!Voice.speaking && Voice.mic === 'idle') {
          Voice.bubble(PET_LINES[petCount++ % PET_LINES.length], '', 5000, 'GUARÁ');
          if (petCount % 3 === 0) api('POST', '/api/guara/interact', { kind: 'poke' }, null);
        }
      } else if (y > 440 && Guara.drop && Guara.drop(x, y)) {
        setTimeout(function () {
          if (!Voice.speaking && Voice.mic === 'idle') Voice.bubble(FRUIT_LINES[fruitCount++ % FRUIT_LINES.length], '', 4500, 'GUARÁ');
        }, 1700);
      } else {
        Guara.tapSky(x, y);
        Ambient.tray(!Ambient.trayOpen);
      }
    }
  };

  setInterval(function () {
    if (!ScreenOff.on && !Ambient.on && !S.permShown && Voice.mic === 'idle' && $('compose').className.indexOf('hidden') >= 0) {
      if (Date.now() - Power.panelTouch > AMBIENT_MS) Ambient.enter();
    }
    Ambient.update();
  }, 1000);

  // ------------------------------------------------------------ voz (ouvir e falar)

  var Voice = {
    mic: 'idle', audio: null, timer: null, bubbleUntil: 0, enabled: true, speaking: false, speaker: 'GUARÁ',
    clip: null, lastId: '', wait: null, waiting: null, thinkingIndex: 0,
    thinking: function (text, id) {
      if (id && S.mission && S.mission.id === id && S.mission.status !== 'running') return;
      Voice.waiting = { id: id || null, at: Date.now(), updated: Date.now() };
      Guara.setMood('thinking', 0);
      Voice.bubble(text || 'Deixa eu conferir isso pra você.', 'Preparando sua resposta…', 20000, 'PENSANDO…');
    },
    holdBubble: function () { return Voice.mic !== 'idle' || Voice.speaking || Date.now() < Voice.bubbleUntil; },
    bubble: function (phrase, sub, ms, speaker) {
      Voice.speaker = speaker || 'GUARÁ';
      $('clabel').textContent = Voice.speaker;
      $('clabel').className = Voice.mic === 'ouvindo' ? 'listen' : (speaker && speaker.indexOf('PENSANDO') >= 0 ? 'think' : '');
      $('phrase').textContent = phrase;
      $('sub').textContent = sub || '';
      Voice.bubbleUntil = Date.now() + (ms || 6000);
      Ambient.update();
    },
    toggleMic: function () {
      if (!NATIVE || !NATIVE.listen) {
        openCompose(true);
        toast('Sem microfone nativo: digite para falar com o Guará');
        return;
      }
      if (Voice.mic === 'ouvindo') { NATIVE.stopListen(); return; }
      if (Voice.mic !== 'idle') return;
      Voice.stop();
      Voice.setMic('ouvindo');
      api('POST', '/api/voice/warm', {}, null);
      NATIVE.listen();
    },
    setMic: function (st) {
      Voice.mic = st;
      var cls = st === 'ouvindo' ? 'on' : (st === 'idle' ? '' : 'busy');
      $('mic').className = cls;
      $('amb-mic').className = cls;
      Guara.setListening(st === 'ouvindo', 0);
      if (st !== 'ouvindo') {
        $('micring').style.webkitTransform = $('micring').style.transform = 'scale(1)';
        $('amb-micring').style.webkitTransform = $('amb-micring').style.transform = 'scale(1)';
      }
      Ambient.update();
    },
    stop: function () {
      if (Voice.audio) { try { Voice.audio.pause(); } catch (e) {} }
      else if (Voice.clip && NATIVE && NATIVE.stopAudio) NATIVE.stopAudio();
      Voice.audio = Voice.clip = null;
      Voice.speaking = false;
      clearInterval(Voice.timer);
      clearTimeout(Voice.wait);
      Guara.setTalk(0);
      Ambient.update();
    },
    // boca no ritmo da fala, contada a partir do momento em que o som começa de verdade
    lip: function (d) {
      var started = Date.now();
      clearInterval(Voice.timer);
      Voice.timer = setInterval(function () {
        var t = (Voice.audio && Voice.audio.currentTime) || (Date.now() - started) / 1000;
        var i = Math.floor(t / 0.06);
        if (i < d.env.length && t <= d.dur + 1) { Guara.setTalk(d.env[i]); return; }
        if (Voice.audio) { Voice.stop(); return; }
        clearInterval(Voice.timer);   // no nativo, quem encerra a fala é o aviso 'ended' do Java
        Guara.setTalk(0);
      }, 60);
    },
    play: function (d) {
      if (d.kind === 'ack' && (!Voice.waiting || Voice.waiting.id !== d.mission_id ||
          (S.mission && S.mission.id === d.mission_id && S.mission.status !== 'running'))) return;
      if (d.kind === 'reply') Voice.waiting = null;
      Power.wake();
      if (Voice.mic === 'ouvindo' || d.id === Voice.lastId) return;   // a mesma fala pode chegar duas vezes
      Voice.lastId = d.id;
      Voice.stop();
      Voice.speaking = true;
      Voice.clip = d;
      Voice.bubble(d.text, Ambient.on ? 'Toque no microfone para responder' : '', d.dur * 1000 + 5000, 'GUARÁ FALANDO');
      if (NATIVE && NATIVE.playWav) {
        // Um único AudioTrack no Java. O <audio> do WebView 4.4 demora para começar e não para
        // com pause() enquanto ainda carrega: duas falas seguidas viravam duas vozes com atraso.
        NATIVE.playWav(d.id);
        Voice.wait = setTimeout(function () { if (Voice.clip === d) Voice.stop(); }, 10000);   // o áudio nem chegou
        return;
      }
      var audio = new Audio('/api/say/' + d.id + '.wav?t=' + TOKEN);
      Voice.audio = audio;
      audio.onended = audio.onerror = function () { if (Voice.audio === audio) Voice.stop(); };
      try { audio.play(); } catch (e) {}
      Voice.lip(d);
    },
    heard: function (h) {
      if (h.state === 'transcrevendo') Voice.bubble('Entendendo o que você falou…', '', 15000, 'TRANSCREVENDO…');
      else if (h.state === 'ok') { Voice.setMic('idle'); Voice.thinking(); }
      else if (h.state === 'vazio') Voice.setMic('idle');
      else if (h.state === 'erro') { Voice.setMic('idle'); Voice.bubble('Não consegui entender o áudio.', h.text, 5000, 'GUARÁ'); }
    }
  };

  setInterval(function () {
    var pending = Voice.waiting;
    if (!pending || Voice.speaking || Voice.mic !== 'idle' || !S.connected) return;
    if (Date.now() - pending.updated < 10000) return;
    var lines = ['Tô por aqui, conferindo os detalhes.', 'Ainda tô preparando sua resposta.', 'Vou com calma pra te responder direitinho.'];
    var text = S.agent.mood === 'searching' ? 'Buscando as informações pra te responder.' : lines[Voice.thinkingIndex++ % lines.length];
    var steps = S.mission && S.mission.id === pending.id && S.mission.steps;
    Voice.bubble(text, steps && steps.length ? steps[steps.length - 1] : 'Seu pedido continua em andamento.', 20000, 'PENSANDO…');
    pending.updated = Date.now();
  }, 1000);

  window.CapiVoice = {
    state: function (st) {
      if (st === 'ouvindo') { Voice.setMic('ouvindo'); Voice.bubble('Pode falar, tô ouvindo…', 'Pauso sozinho quando você terminar.', 32000, 'OUVINDO VOCÊ…'); }
      else if (st === 'enviando' || st === 'enviado') { Voice.setMic('enviando'); Voice.bubble('Entendendo o que você disse…', '', 15000, 'PROCESSANDO…'); }
      else if (st === 'nada') { Voice.setMic('idle'); Voice.bubble('Não ouvi nada por aí.', 'Toque no microfone e fale comigo.', 4500, 'GUARÁ'); }
      else if (st === 'erro') { Voice.setMic('idle'); Voice.bubble('O microfone do tablet falhou.', 'Toque de novo para tentar.', 4500, 'GUARÁ'); }
    },
    // o player nativo avisa quando a fala começa e termina de tocar
    playState: function (st, id) {
      var d = Voice.clip;
      if (!d || d.id !== id) return;
      if (st === 'playing') { clearTimeout(Voice.wait); Voice.lip(d); }
      else if (st === 'ended') Voice.stop();
    },
    level: function (n) {
      Guara.setListening(Voice.mic === 'ouvindo', n);
      var s1 = 'scale(' + (1 + n * 0.045) + ')';
      $('micring').style.webkitTransform = $('micring').style.transform = s1;
      $('amb-micring').style.webkitTransform = $('amb-micring').style.transform = s1;
    }
  };

  function setVoiceEnabled(on) {
    Voice.enabled = on;
    $('voicebtn').className = 'btn small' + (on ? '' : ' off');
    $('voicebtn').lastChild.textContent = on ? 'Avisos falados ligados' : 'Avisos falados desligados';
    setIcon($('voicebtn'), on ? 'vol' : 'volx', 15);
  }

  function onVoice(v) {
    setVoiceEnabled(v.enabled);
    if (!v.list) return;
    var html = '';
    for (var i = 0; i < v.list.length; i++) {
      var o = v.list[i], cur = o.id === v.current;
      html += '<div class="voice' + (cur ? ' cur' : '') + '" data-act="voice-set" data-id="' + esc(o.id) + '">' +
        '<div class="vinfo"><span class="vn ellipsis">' + esc(o.name) + '</span><span class="vd ellipsis">' + esc(o.desc) + '</span></div>' +
        '<span class="vplay">' + svg(cur ? 'check' : 'play', 15) + '</span></div>';
    }
    $('voices').innerHTML = html;
  }

  // ------------------------------------------------------------ controles deslizantes

  var SLIDERS = { vol: ['vbar', 'v2bar'], mic: ['mbar'], pcbright: ['pbar'], bright: ['bbar'] };
  var Slider = { drag: null, sentAt: 0 };

  function paintSlider(kind, pct) {
    pct = Math.max(0, Math.min(100, pct));
    var ids = SLIDERS[kind];
    for (var i = 0; i < ids.length; i++) {
      var rail = $(ids[i]).firstChild;
      rail.firstChild.style.width = '-webkit-calc(' + pct + '% + 13px)';
      rail.firstChild.style.width = 'calc(' + pct + '% + 13px)';
      rail.lastChild.style.left = pct + '%';
    }
  }

  function sliderValue(el, x) {
    var r = el.getBoundingClientRect();
    return Math.round(Math.max(0, Math.min(1, (x - r.left - 13) / (r.width - 26))) * 100);
  }

  function sliderMove(x, final) {
    var d = Slider.drag, pct = sliderValue(d.el, x);
    paintSlider(d.kind, pct);
    var throttle = final || Date.now() - Slider.sentAt > 200;
    if (d.kind === 'vol') {
      $('vtxt').textContent = $('v2txt').textContent = pct + '%';
      if (throttle) { Slider.sentAt = Date.now(); api('POST', '/api/volume', { level: pct }, null); }
    } else if (d.kind === 'mic') {
      $('mtxt').textContent = pct + '%';
      if (throttle) { Slider.sentAt = Date.now(); api('POST', '/api/pc', { what: 'mic', value: pct }, null); }
    } else if (d.kind === 'pcbright') {
      pct = Math.max(5, pct);
      $('ptxt').textContent = pct + '%';
      if (throttle) { Slider.sentAt = Date.now(); api('POST', '/api/pc', { what: 'brightness', value: pct }, null); }
    } else {
      Power.level = Math.max(0.05, pct / 100);
      Power.apply(Power.level);
      $('btxt').textContent = pct + '%';
    }
  }

  function sliderStart(target, x) {
    var el = target;
    while (el && el !== document && !(el.getAttribute && el.getAttribute('data-slider'))) el = el.parentNode;
    if (!el || el === document) return false;
    Slider.drag = { el: el, kind: el.getAttribute('data-slider') };
    el.className = 'slider drag';
    sliderMove(x, false);
    return true;
  }

  function sliderEnd(x) {
    sliderMove(x, true);
    Slider.drag.el.className = 'slider';
    Slider.drag = null;
  }

  // ------------------------------------------------------------ caixa de mensagem (conversa ou missão)

  function openCompose(conversational) {
    S.composeConversational = !!conversational;
    $('compose-title').textContent = conversational ? 'Conversar com o Guará' : 'Pedir missão ao Guará';
    $('compose-meta').textContent = conversational
      ? 'Ele responde em voz alta e lembra o contexto da conversa.'
      : 'Ele usa a IA da vez no PC e mostra os passos na aba IA.';
    $('compose-btn').textContent = conversational ? 'Falar' : 'Executar';
    show($('compose'), true);
    $('ask').value = '';
    setTimeout(function () { $('ask').focus(); }, 50);
  }

  // ------------------------------------------------------------ toques e ações

  var armed = {};

  var ACT = {
    tab: function (el) {
      var t = el.getAttribute('data-tab');
      S.tab = t;
      var navs = document.querySelectorAll('.nav');
      for (var i = 0; i < navs.length; i++) navs[i].className = 'nav' + (navs[i].getAttribute('data-tab') === t ? ' on' : '');
      var panes = document.querySelectorAll('.pane');
      for (var j = 0; j < panes.length; j++) panes[j].className = 'pane' + (panes[j].id === 'p-' + t ? ' on' : '');
      clearInterval(devTimer);
      if (t === 'projetos' || t === 'dev') { loadDev(); devTimer = setInterval(loadDev, 15000); }
      if (t === 'pc') onStats(S.stats);
      if (t === 'apps') loadApps();
    },
    'ambient-enter': function () { Ambient.enter(); },
    'screen-off': function () { ScreenOff.enter(); },
    poke: function () {
      Guara.pet();
      if (S.agent.mood === 'idle' && !Voice.holdBubble()) {
        Voice.bubble(PET_LINES[petCount++ % PET_LINES.length], 'Toque em Modo Guará para tela cheia', 4500, 'GUARÁ');
      }
    },
    shortcut: function (el) {
      act('/api/action', { id: el.getAttribute('data-id') }, 'Abrindo ' + el.getAttribute('data-label') + ' no PC');
    },
    app: function (el) {
      act('/api/app', { id: el.getAttribute('data-id') }, 'Abrindo ' + el.getAttribute('data-label') + ' no PC');
    },
    toggle: function (el) {
      var name = el.getAttribute('data-name');
      S.toggles[name] = !S.toggles[name];
      onToggles(S.toggles);
      act('/api/toggle', { name: name }, null, function (d) { onToggles(d.toggles); });
    },
    power: function (el) {
      var name = el.getAttribute('data-name');
      if (name === 'suspend' && !armed.suspend) {
        armed.suspend = true;
        el.className = 'brk warn armed';
        el.lastChild.textContent = 'Confirmar?';
        setTimeout(function () { armed.suspend = false; el.className = 'brk warn'; el.lastChild.textContent = 'Suspender'; }, 3000);
        return;
      }
      act('/api/power', { action: name }, { lock: 'PC bloqueado', screenshot: 'Captura salva em Imagens', suspend: 'Suspendendo o PC' }[name]);
    },
    profile: function (el) {
      act('/api/pc', { what: 'profile', value: el.getAttribute('data-name') }, 'Perfil: ' + el.textContent, function (d) { onPC(d.pcctl); });
    },
    bluetooth: function () {
      var want = !S.pc.bluetooth;
      act('/api/pc', { what: 'bluetooth', value: want }, want ? 'Bluetooth ligado' : 'Bluetooth desligado', function (d) { onPC(d.pcctl); });
    },
    sink: function (el) {
      act('/api/pc', { what: 'sink', value: el.getAttribute('data-id') }, 'Saída de som trocada', function (d) { onPC(d.pcctl); });
    },
    'quota-refresh': function () { act('/api/quota/refresh', {}, 'Consultando os limites…'); },
    proj: function (el) {
      var a = el.getAttribute('data-a');
      var msg = { code: 'Abrindo no VS Code', term: 'Abrindo o terminal', claude: 'Abrindo o Claude Code no projeto',
        codex: 'Abrindo o Codex no projeto', folder: 'Abrindo a pasta', github: 'Abrindo no GitHub' }[a];
      act('/api/project', { path: el.getAttribute('data-path'), action: a }, msg);
    },
    docker: function (el) {
      var a = el.getAttribute('data-a');
      toast({ start: 'Iniciando…', stop: 'Parando…', restart: 'Reiniciando…' }[a]);
      act('/api/docker', { names: el.getAttribute('data-names').split(' '), action: a }, null, function (d) {
        S.dev.docker = d.docker; renderDocker();
      });
    },
    port: function (el) { act('/api/port/open', { port: +el.getAttribute('data-port') }, 'Abrindo no navegador do PC'); },
    'ollama-unload': function (el) {
      act('/api/ollama/unload', { name: el.getAttribute('data-name') }, 'VRAM liberada', function (d) { S.dev.ollama = d.ollama; renderOllama(); });
    },
    handoff: function (el) { act('/api/handoff', { session: el.getAttribute('data-id') }, 'Abrindo o Codex com o contexto'); },
    mission: function (el) { startMission({ preset: el.getAttribute('data-id') }); },
    'mission-cancel': function () { api('POST', '/api/mission/cancel', {}, null); },
    'mission-close': function () {
      if (S.mission) S.missionClosed = S.mission.id;
      show($('mission'), false);
    },
    compose: function () { openCompose(true); },
    'compose-mission': function () { openCompose(false); },
    'compose-cancel': function () { $('ask').blur(); show($('compose'), false); },
    'compose-send': function () {
      var text = $('ask').value.replace(/^\s+|\s+$/g, '');
      $('ask').blur();
      show($('compose'), false);
      if (!text) return;
      if (S.composeConversational || Ambient.on) {
        Voice.thinking();
        api('POST', '/api/converse', { text: text }, function (code, d) {
          if (code !== 200) {
            Voice.waiting = null;
            Voice.bubble((d && (d.info || d.error)) || 'Não consegui enviar o pedido. Tenta de novo?', '', 8000, 'GUARÁ');
          }
        });
      } else {
        startMission({ prompt: text });
      }
    },
    'perm-allow': function () { decide('allow'); },
    'perm-deny': function () { decide('deny'); },
    'perm-pick': function (el) { S.permSel = el.getAttribute('data-id'); S.permShown = null; renderPermission(); },
    sleep: function () { Power.sleep(); },
    mic: function () { Voice.toggleMic(); },
    'voice-set': function (el) {
      toast('Testando nova voz do Guará…');
      api('POST', '/api/voice/set', { id: el.getAttribute('data-id') }, null);
    },
    'voice-toggle': function () {
      api('POST', '/api/voice/enable', { on: !Voice.enabled }, function (code, d) { if (d) setVoiceEnabled(d.enabled); });
    }
  };

  function startMission(body) {
    toast('Missão enviada');
    S.missionClosed = null;
    ACT.tab(document.querySelector('[data-tab="ia"]'));
    api('POST', '/api/mission', body, function (code, d) {
      if (code !== 200) toast((d && (d.info || d.error)) || 'A missão não começou');
    });
  }

  function decide(behavior) {
    var p = null, perms = S.agent.permissions || [];
    for (var i = 0; i < perms.length; i++) if (perms[i].id === S.permShown) p = perms[i];
    if (!p) return;
    S.permShown = null;
    S.permSel = null;
    api('POST', '/api/permission', { id: p.id, behavior: behavior }, null);
    toast(behavior === 'allow' ? 'Aprovado' : 'Negado');
  }

  function media(el) {
    api('POST', '/api/action', { id: el.getAttribute('data-act') }, function (code, d) {
      if (d && d.result) {
        if (d.result.player !== undefined) onMedia(d.result);
        if (d.result.level !== undefined) onVolume(d.result);
      }
    });
  }

  function dispatch(el, ev) {
    var a = el.getAttribute('data-act');
    if (ACT[a]) ACT[a](el, ev);
    else if (/^(media|vol)\./.test(a)) media(el);
  }

  function findAttr(node, attr) {
    while (node && node !== document) {
      if (node.getAttribute && node.getAttribute(attr)) return node;
      node = node.parentNode;
    }
    return null;
  }

  function insideCompose(node) {
    if ($('compose').className.indexOf('hidden') >= 0) return false;
    while (node && node !== document) {
      if (node.id === 'compose') return true;
      node = node.parentNode;
    }
    return false;
  }

  var touch = null, lastTouchEnd = 0, swallow = false;

  document.addEventListener('touchstart', function (e) {
    if (ScreenOff.on) { touch = { so: true }; e.preventDefault(); return; }
    if (Power.dim) {
      swallow = true;
      Power.wake();
      e.preventDefault();
      return;
    }
    Power.lastTouch = Date.now();
    var t = e.touches[0];

    // Se a janela de escrever estiver aberta (mesmo sobre a tela cheia), ela recebe o toque normal
    if (insideCompose(e.target)) {
      var cEl = findAttr(e.target, 'data-act');
      touch = { x: t.clientX, y: t.clientY, el: cEl, at: Date.now() };
      if (cEl) cEl.className += ' pressed';
      return;
    }

    if (Ambient.on) {
      var ambEl = findAttr(e.target, 'data-amb');
      touch = { x: t.clientX, y: t.clientY, el: ambEl, at: Date.now(), amb: true };
      if (ambEl) ambEl.className += ' pressed';
      e.preventDefault();
      return;
    }

    Power.panelTouch = Date.now();
    if (sliderStart(e.target, t.clientX)) { e.preventDefault(); return; }
    var el = findAttr(e.target, 'data-act');
    touch = { x: t.clientX, y: t.clientY, el: el, at: Date.now() };
    if (el && el.id !== 'stage') el.className += ' pressed';
  }, true);

  document.addEventListener('touchmove', function (e) {
    if (ScreenOff.on) { e.preventDefault(); return; }
    if (Slider.drag) { sliderMove(e.touches[0].clientX, false); e.preventDefault(); return; }
    if (!touch) return;
    var t = e.touches[0], dx = Math.abs(t.clientX - touch.x), dy = Math.abs(t.clientY - touch.y);
    if (dx > 14 || dy > 14) clearPressed();
    if (touch.amb) { e.preventDefault(); return; }
    if (dx > dy || !canScrollY(e.target)) e.preventDefault();
  }, true);

  function canScrollY(node) {
    while (node && node !== document) {
      if (node.className && /\bpane\b/.test(node.className)) return node.scrollHeight > node.clientHeight + 2;
      node = node.parentNode;
    }
    return false;
  }

  document.addEventListener('touchend', function (e) {
    lastTouchEnd = Date.now();
    if (touch && touch.so) { touch = null; e.preventDefault(); ScreenOff.tap(); return; }
    if (swallow) { swallow = false; e.preventDefault(); return; }
    if (Slider.drag) { sliderEnd(e.changedTouches[0].clientX); e.preventDefault(); return; }
    var t = touch;
    clearPressed(true);
    touch = null;
    if (!t) return;

    var cx = e.changedTouches[0].clientX, cy = e.changedTouches[0].clientY;
    var moved = Math.abs(cx - t.x) + Math.abs(cy - t.y) > 22;

    if (t.amb) {
      e.preventDefault();
      if (moved || Date.now() - t.at > 900) return;
      if (t.el) Ambient.action(t.el);
      else Ambient.canvasTap(cx, cy);
      return;
    }

    if (!t.el || t.moved || moved || Date.now() - t.at > 900) return;
    if (t.el.tagName !== 'TEXTAREA') e.preventDefault();
    dispatch(t.el, { x: t.x, y: t.y });
  }, true);

  function clearPressed(keepTouch) {
    var p = document.querySelectorAll('.pressed');
    for (var i = 0; i < p.length; i++) p[i].className = p[i].className.replace(/\s*pressed/g, '');
    if (!keepTouch && touch) touch.moved = true;
  }

  document.addEventListener('mousedown', function (e) { if (!Ambient.on && sliderStart(e.target, e.clientX)) e.preventDefault(); });
  document.addEventListener('mousemove', function (e) { if (Slider.drag) sliderMove(e.clientX, false); });
  document.addEventListener('mouseup', function (e) { if (Slider.drag) { sliderEnd(e.clientX); lastTouchEnd = Date.now(); } });

  document.addEventListener('click', function (e) {
    if (Date.now() - lastTouchEnd < 600) return;
    if (ScreenOff.on) { ScreenOff.tap(); return; }
    if (Power.dim) { Power.wake(); return; }
    Power.lastTouch = Date.now();
    if (insideCompose(e.target)) {
      var cEl = findAttr(e.target, 'data-act');
      if (cEl) dispatch(cEl, { x: e.clientX, y: e.clientY });
      return;
    }
    if (Ambient.on) {
      var ambEl = findAttr(e.target, 'data-amb');
      if (ambEl) Ambient.action(ambEl);
      else Ambient.canvasTap(e.clientX, e.clientY);
      return;
    }
    Power.panelTouch = Date.now();
    var el = findAttr(e.target, 'data-act');
    if (el) dispatch(el, { x: e.clientX, y: e.clientY });
  });

  function hardReload() {
    if (NATIVE && NATIVE.reload) NATIVE.reload();
    else location.href = location.pathname + '?t=' + TOKEN + '&_=' + Date.now();
  }

  // segurar o relógio por 3 s (no painel ou no Modo Guará): menu do tablet
  var holdTimer = null;
  function bindHold(el) {
    if (!el) return;
    el.addEventListener('touchstart', function () {
      clearTimeout(holdTimer);
      holdTimer = setTimeout(function () { if (NATIVE && NATIVE.menu) NATIVE.menu(); else hardReload(); }, 3000);
    });
    el.addEventListener('touchend', function () { clearTimeout(holdTimer); });
    el.addEventListener('touchcancel', function () { clearTimeout(holdTimer); });
  }
  bindHold($('hold'));

  var toastTimer = null;
  function toast(msg) {
    if (!msg) return;
    $('toast').textContent = msg;
    show($('toast'), true);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { show($('toast'), false); }, 2000);
  }

  // ------------------------------------------------------------ relógio

  function tickClock() {
    var d = new Date(), h = d.getHours(), m = d.getMinutes();
    $('clock').textContent = (h < 10 ? '0' : '') + h + ':' + (m < 10 ? '0' : '') + m;
    var dias = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb'];
    var meses = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
    var bat = tabletBattery();
    $('date').textContent = dias[d.getDay()] + ', ' + d.getDate() + ' ' + meses[d.getMonth()];
    show($('tbat'), !!bat);
    if (bat) {
      $('tbat').className = bat.charging ? 'charging' : bat.pct <= 20 ? 'low' : '';
      $('tbatfill').style.width = Math.max(4, bat.pct) + '%';
      $('tbatpct').textContent = bat.pct + '%';
    }
    if (Ambient.on) Ambient.update();
  }

  Guara.init($('guara'), $('bg'), 6, 65);   // 65x40 blocos de 6 px = 390x240, pixel art exata sem escala
  paintStaticIcons();
  setTimeout(function () { paintSlider('bright', 100); }, 0);
  tickClock();
  setInterval(tickClock, 10000);
  if (NATIVE && NATIVE.setBrightness) NATIVE.setBrightness(1);
  var qTab = (location.search.match(/[?&]tab=([a-z]+)/) || [])[1];
  if (qTab && document.querySelector('[data-tab="' + qTab + '"]')) ACT.tab(document.querySelector('[data-tab="' + qTab + '"]'));
  if (/[?&]ambient=1/.test(location.search)) setTimeout(function () { Ambient.enter(); }, 180);
  setTimeout(connect, 60);
})();
