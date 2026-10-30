/* Guará "suave 3D": mascote brilhante estilo brinquedo (como OpenClaw / ClawBot), com visor de olhos de luz.
 * Mesma interface do guara-pixel.js. ES5 puro para o WebView do Android 4.4.
 * Desempenho: tudo que tem degradê é pintado uma vez (em resize) em telas fora da página;
 * a cada quadro só reposicionamos essas peças e desenhamos olhos, boca e efeitos. */
(function (global) {
  'use strict';

  var GH = 40, GW = 65, U = 6;           // a página pede o tamanho em "blocos" (compatível com o pixel)
  var FULL = false;
  var canvas, ctx, bgCanvas, timer = null, paused = false;
  var W = 390, H = 240, S = 1, CX = 160, GY = 214;   // escala e posição do mascote (chão no meio dele)
  var parts = {};

  var C = {
    fur: ['#FF9A63', '#E8562A', '#A9361A'],
    cream: ['#FFF8EF', '#F1DAC4', '#D2B79E'],
    dark: ['#5A4234', '#26180F', '#120B07'],
    innerEar: '#FFC8AE',
    visor: ['#262E48', '#0C1020'],
    eye: { idle: '#62E4FF', work: '#7AB6FF', wait: '#FFC24B', done: '#7DF2A6', err: '#FF6B6B', sleep: '#2C6E80', listen: '#FF8A65' }
  };

  var st = {
    mood: 'idle', subagents: 0, t: 0, lastFrame: 0, awake: true, talk: 0, listening: false, level: 0,
    blinkAt: 1800, flickAt: 4000, flickSide: 0, lookX: 0, lookY: 0, lookAt: 0, jump: 0, wagUntil: 0, petUntil: 0, fx: []
  };

  function rnd(a, b) { return a + Math.random() * (b - a); }

  // ------------------------------------------------------------ desenho base (pintado uma vez)

  function mk(w, h, fn) {
    var c = document.createElement('canvas');
    c.width = Math.ceil(w); c.height = Math.ceil(h);
    fn(c.getContext('2d'));
    return c;
  }

  function rr(g, x, y, w, h, r) {
    g.beginPath();
    g.moveTo(x + r, y);
    g.arcTo(x + w, y, x + w, y + h, r);
    g.arcTo(x + w, y + h, x, y + h, r);
    g.arcTo(x, y + h, x, y, r);
    g.arcTo(x, y, x + w, y, r);
    g.closePath();
  }

  function ellipse(g, x, y, rx, ry) {
    g.save();
    g.translate(x, y);
    g.scale(rx, ry);
    g.beginPath();
    g.arc(0, 0, 1, 0, Math.PI * 2);
    g.restore();
  }

  // volume de brinquedo: luz forte no alto à esquerda, sombra embaixo à direita
  function shade(g, x, y, rx, ry, col) {
    var gr = g.createRadialGradient(x - rx * 0.35, y - ry * 0.45, Math.max(rx, ry) * 0.05, x, y, Math.max(rx, ry) * 1.15);
    gr.addColorStop(0, col[0]);
    gr.addColorStop(0.55, col[1]);
    gr.addColorStop(1, col[2]);
    g.fillStyle = gr;
  }

  function spec(g, x, y, rx, ry, a) {   // reflexo especular macio
    var gr = g.createRadialGradient(x, y, 0, x, y, Math.max(rx, ry));
    gr.addColorStop(0, 'rgba(255,255,255,' + a + ')');
    gr.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = gr;
    ellipse(g, x, y, rx, ry);
    g.fill();
  }

  // Coordenadas de desenho: unidades do mascote (1 = S px); origem no chão, centro do corpo.
  function buildParts() {
    var s = S, pad = 20 * s;
    // corpo, juba, pernas, cabeça, focinho e visor: um bloco só
    var cw = 150 * s, ch = 210 * s, ox = cw / 2, oy = ch - 4 * s;
    parts.core = { img: mk(cw, ch, function (g) {
      g.translate(ox, oy);
      g.scale(s, s);
      // pernas
      [-17, 17].forEach(function (lx) {
        var gr = g.createLinearGradient(lx - 8, 0, lx + 8, 0);
        gr.addColorStop(0, C.dark[0]); gr.addColorStop(1, C.dark[2]);
        g.fillStyle = gr;
        rr(g, lx - 8, -26, 16, 26, 7);
        g.fill();
      });
      // corpo
      shade(g, 0, -52, 46, 40, C.fur);
      ellipse(g, 0, -52, 46, 40);
      g.fill();
      spec(g, -16, -70, 18, 12, 0.22);
      // juba (golinha escura)
      shade(g, 0, -80, 44, 14, C.dark);
      ellipse(g, 0, -80, 44, 14);
      g.fill();
      // cabeça
      shade(g, 0, -122, 58, 50, C.fur);
      ellipse(g, 0, -122, 58, 50);
      g.fill();
      spec(g, -24, -152, 22, 13, 0.35);
      // focinho creme e nariz
      shade(g, 0, -88, 27, 16, C.cream);
      ellipse(g, 0, -88, 27, 16);
      g.fill();
      shade(g, 0, -97, 9, 6, C.dark);
      ellipse(g, 0, -97, 9, 6);
      g.fill();
      spec(g, -3, -99, 3.5, 2, 0.7);
      // visor de vidro
      var vg = g.createLinearGradient(0, -142, 0, -104);
      vg.addColorStop(0, C.visor[0]); vg.addColorStop(1, C.visor[1]);
      g.fillStyle = vg;
      rr(g, -42, -142, 84, 38, 19);
      g.fill();
      g.strokeStyle = 'rgba(0,0,0,0.35)';
      g.lineWidth = 1.5;
      g.stroke();
      g.fillStyle = 'rgba(255,255,255,0.10)';
      rr(g, -36, -139, 72, 12, 6);
      g.fill();
    }), ox: ox, oy: oy };

    // orelhas (giram para a "piscadinha" e ficam em pé quando ouve)
    function ear(sign) {
      var ew = 60 * s, eh = 80 * s;
      return { img: mk(ew, eh, function (g) {
        g.translate(ew / 2, eh - 6 * s);
        g.scale(s * sign, s);
        g.beginPath();
        g.moveTo(-16, 0);
        g.quadraticCurveTo(-14, -48, 4, -68);
        g.quadraticCurveTo(14, -40, 20, -4);
        g.closePath();
        shade(g, 0, -30, 20, 40, C.fur);
        g.fill();
        g.beginPath();
        g.moveTo(-8, -6);
        g.quadraticCurveTo(-6, -40, 4, -54);
        g.quadraticCurveTo(10, -32, 12, -8);
        g.closePath();
        g.fillStyle = C.innerEar;
        g.fill();
        spec(g, -6, -40, 4, 12, 0.25);
      }), ox: ew / 2, oy: eh - 6 * s };
    }
    parts.earL = ear(-1);
    parts.earR = ear(1);

    // cauda peluda com ponta branca (abana girando na base)
    var tw = 90 * s, th = 90 * s;
    parts.tail = { img: mk(tw, th, function (g) {
      g.translate(8 * s, th - 10 * s);
      g.scale(s, s);
      g.rotate(-0.75);
      [[10, 0, 16, 11], [28, 0, 18, 13], [48, 0, 18, 13]].forEach(function (p) {
        shade(g, p[0], p[1], p[2], p[3], C.fur);
        ellipse(g, p[0], p[1], p[2], p[3]);
        g.fill();
      });
      shade(g, 64, 0, 14, 11, C.cream);
      ellipse(g, 64, 0, 14, 11);
      g.fill();
      spec(g, 34, -6, 12, 4, 0.25);
    }), ox: 8 * s, oy: th - 10 * s };

    // sombra no chão
    var sw = 130 * s, sh = 24 * s;
    parts.shadow = { img: mk(sw, sh, function (g) {
      var gr = g.createRadialGradient(sw / 2, sh / 2, 0, sw / 2, sh / 2, sw / 2);
      gr.addColorStop(0, 'rgba(0,0,0,0.45)');
      gr.addColorStop(1, 'rgba(0,0,0,0)');
      g.fillStyle = gr;
      g.save();
      g.translate(sw / 2, sh / 2);
      g.scale(1, sh / sw);
      g.beginPath();
      g.arc(0, 0, sw / 2, 0, Math.PI * 2);
      g.fill();
      g.restore();
    }), ox: sw / 2, oy: sh / 2 };

    parts.glow = {};
  }

  function glow(color) {   // halo dos olhos, pintado uma vez por cor
    if (!parts.glow[color]) {
      var r = 26 * S;
      parts.glow[color] = mk(r * 2, r * 2, function (g) {
        var gr = g.createRadialGradient(r, r, 0, r, r, r);
        gr.addColorStop(0, color);
        gr.addColorStop(1, 'rgba(0,0,0,0)');
        g.fillStyle = gr;
        g.globalAlpha = 0.55;
        g.fillRect(0, 0, r * 2, r * 2);
      });
    }
    return parts.glow[color];
  }

  // ------------------------------------------------------------ fundo de estúdio (pintado uma vez)

  function paintScene(c) {
    c.width = W; c.height = H;
    var g = c.getContext('2d');
    var sky = g.createLinearGradient(0, 0, 0, H);
    sky.addColorStop(0, '#1B1D24');
    sky.addColorStop(1, '#0E0F13');
    g.fillStyle = sky;
    g.fillRect(0, 0, W, H);
    // foco de luz quente atrás do mascote
    var spot = g.createRadialGradient(CX, GY - 110 * S, 10, CX, GY - 110 * S, 190 * S);
    spot.addColorStop(0, 'rgba(255,170,120,0.30)');
    spot.addColorStop(1, 'rgba(255,170,120,0)');
    g.fillStyle = spot;
    g.fillRect(0, 0, W, H);
    // luzes desfocadas (bokeh)
    [[0.82, 0.22, 46, 'rgba(120,170,255,0.10)'], [0.92, 0.55, 30, 'rgba(255,190,140,0.08)'],
     [0.08, 0.18, 34, 'rgba(255,150,110,0.09)'], [0.62, 0.12, 18, 'rgba(255,255,255,0.07)']].forEach(function (b) {
      var x = b[0] * W, y = b[1] * H, r = b[2] * S;
      var gr = g.createRadialGradient(x, y, 0, x, y, r);
      gr.addColorStop(0, b[3]);
      gr.addColorStop(1, 'rgba(0,0,0,0)');
      g.fillStyle = gr;
      g.fillRect(x - r, y - r, r * 2, r * 2);
    });
    // lua macia
    var mx = W * (FULL ? 0.62 : 0.86), my = H * 0.2, mr = 14 * S;
    var mg = g.createRadialGradient(mx - mr * 0.3, my - mr * 0.3, 1, mx, my, mr);
    mg.addColorStop(0, '#FFF6E6'); mg.addColorStop(1, '#E9D9BE');
    g.fillStyle = mg;
    g.beginPath(); g.arc(mx, my, mr, 0, Math.PI * 2); g.fill();
    var mh = g.createRadialGradient(mx, my, mr, mx, my, mr * 3.2);
    mh.addColorStop(0, 'rgba(255,240,215,0.18)'); mh.addColorStop(1, 'rgba(255,240,215,0)');
    g.fillStyle = mh;
    g.fillRect(mx - mr * 4, my - mr * 4, mr * 8, mr * 8);
    // colinas suaves do cerrado
    function hill(x, y, rx, ry, a, b) {
      var gr = g.createLinearGradient(0, y - ry, 0, H);
      gr.addColorStop(0, a); gr.addColorStop(1, b);
      g.fillStyle = gr;
      ellipse(g, x, y, rx, ry);
      g.fill();
    }
    hill(W * 0.15, GY + 30 * S, W * 0.45, 70 * S, '#1F2A26', '#121614');
    hill(W * 0.85, GY + 34 * S, W * 0.5, 64 * S, '#1C2522', '#101311');
    // chão
    var fl = g.createLinearGradient(0, GY - 6 * S, 0, H);
    fl.addColorStop(0, '#24302A'); fl.addColorStop(1, '#141A17');
    g.fillStyle = fl;
    ellipse(g, W / 2, GY + 40 * S, W * 0.75, 48 * S);
    g.fill();
  }

  // ------------------------------------------------------------ olhos, boca e efeitos (a cada quadro)

  function eyeColor() {
    if (st.listening) return C.eye.listen;
    var m = st.mood;
    if (m === 'waiting') return C.eye.wait;
    if (m === 'done') return C.eye.done;
    if (m === 'error') return C.eye.err;
    if (m === 'sleeping' || !st.awake) return C.eye.sleep;
    if (m === 'thinking' || m === 'reading' || m === 'typing' || m === 'running' || m === 'searching') return C.eye.work;
    return C.eye.idle;
  }

  function drawEyes(x0, y0) {
    var m = st.mood, col = eyeColor(), t = st.t;
    var blink = t > st.blinkAt && t < st.blinkAt + 130;
    if (t > st.blinkAt + 130) st.blinkAt = t + rnd(2200, 5200);
    var lx = st.lookX, ly = st.lookY;
    if (m === 'thinking') { ly = -4; lx = 4; }
    if (m === 'typing' || m === 'reading') { ly = 4; lx = Math.sin(t / 600) * 5; }
    if (m === 'searching') { lx = Math.sin(t / 300) * 9; }
    if (m === 'running') { lx = 6; }
    var w = 13, h = 21;
    if (m === 'waiting') { w = 15; h = 25; }
    if (st.listening) { h = 23; }
    var g = ctx;
    for (var i = -1; i <= 1; i += 2) {
      var ex = x0 + (i * 19 + lx) * S, ey = y0 + (-123 + ly) * S;
      var gl = glow(col);
      g.drawImage(gl, ex - gl.width / 2, ey - gl.height / 2);
      g.fillStyle = col;
      g.strokeStyle = col;
      g.lineCap = 'round';
      g.lineWidth = 5 * S;
      if (m === 'done' || st.petUntil > t) {               // ^ ^ feliz
        g.beginPath();
        g.moveTo(ex - 8 * S, ey + 4 * S); g.lineTo(ex, ey - 5 * S); g.lineTo(ex + 8 * S, ey + 4 * S);
        g.stroke();
      } else if (m === 'error') {                          // x x tonto
        g.beginPath();
        g.moveTo(ex - 7 * S, ey - 7 * S); g.lineTo(ex + 7 * S, ey + 7 * S);
        g.moveTo(ex + 7 * S, ey - 7 * S); g.lineTo(ex - 7 * S, ey + 7 * S);
        g.stroke();
      } else if (blink || m === 'sleeping') {              // fechado
        g.beginPath();
        g.moveTo(ex - 7 * S, ey + 2 * S); g.lineTo(ex + 7 * S, ey + 2 * S);
        g.stroke();
      } else {                                             // cápsula de luz
        rr(g, ex - w * S / 2, ey - h * S / 2, w * S, h * S, w * S / 2);
        g.fill();
        g.fillStyle = 'rgba(255,255,255,0.75)';
        rr(g, ex - w * S / 2 + 3 * S, ey - h * S / 2 + 3 * S, 4 * S, 6 * S, 2 * S);
        g.fill();
      }
    }
  }

  function drawMouth(x0, y0) {
    var g = ctx, t = st.t, open = 0;
    if (st.talk > 0) open = 2 + st.talk * 1.1;
    else if (st.mood === 'waiting') open = 5;
    else if (st.mood === 'done' || st.petUntil > t) open = 3;
    var mx = x0, my = y0 - 80 * S;
    if (open > 0) {
      g.fillStyle = '#5A1F1F';
      rr(g, mx - 7 * S, my - 2 * S, 14 * S, (2 + open) * S, Math.min(7, 1 + open / 2) * S);
      g.fill();
      if (open > 6) {
        g.fillStyle = '#E36C7D';
        rr(g, mx - 4 * S, my + (open - 2) * S, 8 * S, 3 * S, 1.5 * S);
        g.fill();
      }
    } else {
      g.strokeStyle = '#7A4A36';
      g.lineWidth = 2 * S;
      g.lineCap = 'round';
      g.beginPath();
      g.moveTo(mx - 6 * S, my - 1 * S);
      g.quadraticCurveTo(mx, my + 3 * S, mx + 6 * S, my - 1 * S);
      g.stroke();
    }
  }

  function orb(x, y, r, col) {
    var g = ctx, gr = g.createRadialGradient(x - r * 0.35, y - r * 0.35, r * 0.1, x, y, r);
    gr.addColorStop(0, '#FFFFFF');
    gr.addColorStop(0.35, col);
    gr.addColorStop(1, 'rgba(0,0,0,0.25)');
    g.fillStyle = gr;
    g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill();
  }

  function holo(x, y, kind) {   // painel holográfico ao lado: código, texto ou terminal
    var g = ctx, t = st.t, w = 74 * S, h = 52 * S;
    g.fillStyle = 'rgba(80,140,255,0.16)';
    rr(g, x, y, w, h, 10 * S);
    g.fill();
    g.strokeStyle = 'rgba(140,190,255,0.55)';
    g.lineWidth = 1.5 * S;
    g.stroke();
    var lines = kind === 'running' ? 3 + Math.floor(t / 280) % 3 : 4;
    for (var i = 0; i < lines; i++) {
      var lw = kind === 'reading' ? 54 : 18 + ((i * 13 + Math.floor(t / 500)) % 34);
      g.fillStyle = i === lines - 1 && kind === 'running' ? 'rgba(125,242,166,0.95)' : 'rgba(170,205,255,0.8)';
      rr(g, x + 9 * S + (kind === 'typing' && i % 2 ? 8 * S : 0), y + (9 + i * 10) * S, lw * S, 4 * S, 2 * S);
      g.fill();
    }
    if (kind === 'typing' && Math.floor(t / 400) % 2) {
      g.fillStyle = '#FFFFFF';
      g.fillRect(x + w - 16 * S, y + h - 14 * S, 2 * S, 8 * S);
    }
  }

  function star(x, y, r, col, a) {
    var g = ctx;
    g.globalAlpha = a;
    g.fillStyle = col;
    g.beginPath();
    g.moveTo(x, y - r); g.quadraticCurveTo(x, y, x + r, y); g.quadraticCurveTo(x, y, x, y + r);
    g.quadraticCurveTo(x, y, x - r, y); g.quadraticCurveTo(x, y, x, y - r);
    g.fill();
    g.globalAlpha = 1;
  }

  function heart(x, y, r, a) {
    var g = ctx;
    g.globalAlpha = a;
    g.fillStyle = '#FF6F91';
    g.beginPath();
    g.moveTo(x, y + r * 0.9);
    g.bezierCurveTo(x - r * 1.4, y - r * 0.2, x - r * 0.6, y - r * 1.3, x, y - r * 0.45);
    g.bezierCurveTo(x + r * 0.6, y - r * 1.3, x + r * 1.4, y - r * 0.2, x, y + r * 0.9);
    g.fill();
    g.globalAlpha = 1;
  }

  function addFx(type, x, y) {
    st.fx.push({ type: type, x: x, y: y, vx: rnd(-0.6, 0.6) * S, vy: -rnd(0.6, 1.4) * S, life: 1 });
  }

  // ------------------------------------------------------------ quadro

  function frame() {
    var g = ctx, t = st.t, m = st.mood;
    g.clearRect(0, 0, W, H);

    var bob = Math.sin(t / (m === 'sleeping' ? 1400 : 700)) * 1.6 * S;
    var shakeX = m === 'error' ? Math.sin(t / 40) * 2.5 * S : 0;
    var hop = 0;
    if (st.jump > 0) { hop = Math.sin((1 - st.jump) * Math.PI) * 26 * S; st.jump = Math.max(0, st.jump - 0.07); }
    else if (m === 'done' && Math.floor(t / 1100) % 3 === 0) st.jump = 1;
    if (m === 'waiting') hop = Math.abs(Math.sin(t / 220)) * 6 * S;
    if (m === 'idle' && !st.listening && t > st.lookAt) {
      st.lookX = Math.random() < 0.5 ? 0 : rnd(-7, 7);
      st.lookY = rnd(-2, 2);
      st.lookAt = t + rnd(1500, 5000);
    }

    var x0 = CX + shakeX, y0 = GY - hop + bob * 0.3;
    var breath = 1 + Math.sin(t / 900) * 0.012;

    // sombra (encolhe no pulo)
    var sh = parts.shadow, sk = 1 - hop / (90 * S);
    g.drawImage(sh.img, CX - sh.ox * sk, GY - sh.oy * 0.6, sh.img.width * sk, sh.img.height * sk);

    // cauda
    var wagging = t < st.wagUntil || m === 'done' || st.talk > 0;
    if (!wagging && m === 'idle' && Math.random() < 0.003) st.wagUntil = t + 1400;
    var ang = wagging ? Math.sin(t / 90) * 0.35 : Math.sin(t / 1300) * 0.08;
    g.save();
    g.translate(x0 + 38 * S, y0 - 34 * S);
    g.rotate(ang);
    g.drawImage(parts.tail.img, -parts.tail.ox, -parts.tail.oy);
    g.restore();

    // orelhas (em pé quando ouve; piscadinha de vez em quando)
    if (t > st.flickAt + 5000 + rnd(0, 5000)) { st.flickAt = t; st.flickSide = Math.random() < 0.5 ? -1 : 1; }
    var flick = t > st.flickAt && t < st.flickAt + 260 ? 0.28 : 0;
    var perk = st.listening ? -6 * S : 0;
    [[-1, parts.earL, -34], [1, parts.earR, 34]].forEach(function (e) {
      var tilt = e[0] * 0.18 + (st.flickSide === e[0] ? e[0] * flick : 0) + (m === 'sleeping' ? e[0] * 0.25 : 0);
      g.save();
      g.translate(x0 + e[2] * S, y0 - 156 * S * breath + perk);
      g.rotate(tilt);
      g.drawImage(e[1].img, -e[1].ox, -e[1].oy);
      g.restore();
    });

    // corpo inteiro (respira esticando de leve)
    g.save();
    g.translate(x0, y0);
    g.scale(1, breath);
    g.drawImage(parts.core.img, -parts.core.ox, -parts.core.oy);
    g.restore();

    drawEyes(x0, y0 + (1 - breath) * 120 * S);
    drawMouth(x0, y0);
    if (m === 'done' || st.petUntil > t) {   // bochechas coradas
      g.fillStyle = 'rgba(255,120,140,0.35)';
      ellipse(g, x0 - 36 * S, y0 - 96 * S, 7 * S, 4 * S); g.fill();
      ellipse(g, x0 + 36 * S, y0 - 96 * S, 7 * S, 4 * S); g.fill();
    }

    // adereços por estado
    var hx = x0 + 70 * S, hy = y0 - 150 * S;
    if (m === 'thinking') {
      for (var i = 0; i < 3; i++) orb(x0 + (48 + i * 14) * S, y0 - (176 + i * 12) * S + Math.sin(t / 300 + i) * 3 * S, (4 + i * 1.5) * S, '#9CC4FF');
    } else if (m === 'typing' || m === 'reading' || m === 'running') {
      holo(hx, hy + Math.sin(t / 700) * 3 * S, m);
    } else if (m === 'searching') {
      var a = t / 500;
      g.strokeStyle = 'rgba(160,200,255,0.9)';
      g.lineWidth = 4 * S;
      g.beginPath(); g.arc(hx + 26 * S + Math.cos(a) * 10 * S, hy + 22 * S + Math.sin(a) * 6 * S, 13 * S, 0, Math.PI * 2); g.stroke();
    } else if (m === 'waiting') {
      var bx = x0 - 16 * S, by = y0 - 222 * S + Math.sin(t / 200) * 3 * S;
      g.fillStyle = '#FFC24B';
      rr(g, bx, by, 32 * S, 32 * S, 10 * S); g.fill();
      g.fillStyle = '#3A2A00';
      rr(g, bx + 13 * S, by + 6 * S, 6 * S, 13 * S, 3 * S); g.fill();
      g.beginPath(); g.arc(bx + 16 * S, by + 25 * S, 3.2 * S, 0, Math.PI * 2); g.fill();
    } else if (m === 'sleeping' && Math.random() < 0.03) {
      addFx('z', x0 + 40 * S, y0 - 170 * S);
    } else if (m === 'done' && Math.random() < 0.25) {
      addFx('star', x0 + rnd(-90, 90) * S, y0 - rnd(60, 200) * S);
    }

    // subagentes: orbes orbitando a cabeça
    var n = Math.min(st.subagents, 6);
    for (var k = 0; k < n; k++) {
      var ang2 = t / 800 + k * Math.PI * 2 / n;
      orb(x0 + Math.cos(ang2) * 86 * S, y0 - 126 * S + Math.sin(ang2) * 24 * S, 6 * S, '#62E4FF');
    }

    // ouvindo: ondas saindo da orelha
    if (st.listening) {
      var lv = Math.min(9, st.level);
      g.strokeStyle = 'rgba(255,138,101,0.8)';
      g.lineWidth = 3 * S;
      for (var w2 = 0; w2 < 1 + Math.round(lv / 3); w2++) {
        g.beginPath();
        g.arc(x0 + 54 * S, y0 - 186 * S, (10 + w2 * 9) * S, -0.9, 0.2);
        g.stroke();
      }
    }

    // partículas
    for (var p = st.fx.length - 1; p >= 0; p--) {
      var f = st.fx[p];
      f.x += f.vx; f.y += f.vy; f.life -= 0.022;
      if (f.life <= 0) { st.fx.splice(p, 1); continue; }
      if (f.type === 'heart') heart(f.x, f.y, 7 * S, f.life);
      else if (f.type === 'z') { g.globalAlpha = f.life; g.fillStyle = '#C9D4FF'; g.font = '700 ' + Math.round(16 * S) + 'px sans-serif'; g.fillText('z', f.x, f.y); g.globalAlpha = 1; }
      else star(f.x, f.y, (f.type === 'star' ? 6 : 4) * S, f.type === 'star' ? '#FFD66B' : '#FFFFFF', f.life);
    }
  }

  function fps() {
    if (st.talk > 0 || st.listening || st.jump > 0 || st.fx.length) return 20;
    if (!st.awake || st.mood === 'sleeping') return 6;
    return st.mood === 'idle' ? 12 : 15;
  }

  function loop() {
    if (paused) { timer = null; return; }
    var now = Date.now();
    st.t += Math.min(400, now - (st.lastFrame || now));
    st.lastFrame = now;
    frame();
    timer = setTimeout(loop, 1000 / fps());
  }

  function layout(unit, gw, fullMode) {
    U = unit || U;
    GW = gw || 65;
    FULL = !!fullMode;
    W = GW * U; H = GH * U;
    S = (H - (FULL ? 120 : 26)) / 236;
    CX = FULL ? W * 0.24 : W * 0.42;
    GY = H - (FULL ? 64 : 18);
    Guara.unit = U;
    Guara.size = { w: W, h: H };
    canvas.width = W;
    canvas.height = H;
    buildParts();
    if (bgCanvas) paintScene(bgCanvas);
  }

  function toCanvas(clientX, clientY) {
    var r = canvas.getBoundingClientRect();
    return { x: (clientX - r.left) * W / r.width, y: (clientY - r.top) * H / r.height };
  }

  var Guara = {
    init: function (el, bg, unit) {
      canvas = el;
      bgCanvas = bg;
      ctx = canvas.getContext('2d');
      layout(unit || U, 65, false);
      if (!timer) loop();
    },
    resize: function (unit, gw, fullMode) { layout(unit, gw, fullMode); },
    setMood: function (mood, subagents) {
      if (mood !== st.mood) {
        st.mood = mood;
        if (mood === 'done') { st.jump = 1; for (var i = 0; i < 6; i++) addFx('star', CX + rnd(-80, 80) * S, GY - rnd(80, 200) * S); }
      }
      st.subagents = subagents || 0;
    },
    setAwake: function (awake) { st.awake = awake; },
    pause: function (on) {
      paused = !!on;
      if (!paused && !timer) { st.lastFrame = Date.now(); loop(); }
    },
    setTalk: function (v) { st.talk = v; },
    setListening: function (on, level) { st.listening = on; st.level = level || 0; },
    hitTest: function (clientX, clientY) {
      var p = toCanvas(clientX, clientY);
      return p.x > CX - 80 * S && p.x < CX + 110 * S && p.y > GY - 210 * S && p.y < GY + 6 * S;
    },
    pet: function () {
      st.jump = 1;
      st.wagUntil = st.t + 2600;
      st.petUntil = st.t + 2200;
      for (var i = 0; i < 4; i++) addFx('heart', CX + rnd(-40, 40) * S, GY - rnd(150, 200) * S);
    },
    poke: function () { Guara.pet(); },
    tapSky: function (clientX, clientY) {
      var p = toCanvas(clientX, clientY);
      st.lookX = p.x < CX ? -7 : 7;
      st.lookAt = st.t + 2200;
      st.flickAt = st.t;
      for (var i = 0; i < 4; i++) addFx('spark', p.x + rnd(-10, 10), p.y + rnd(-10, 10));
    },
    mood: function () { return st.mood; },
    unit: U,
    size: { w: W, h: H }
  };

  global.Guara = Guara;
})(window);
