/* Guará — lobo-guará em pixel art no cerrado à noite. ES5 puro: roda no WebView do Android 4.4.
 * Grade de blocos inteiros (cada bloco = U px). O fundo estático fica num canvas separado; aqui só o que é vivo. */
(function (global) {
  'use strict';

  var GW = 65, GH = 40, U = 6;
  var OX = 0;                       // deslocamento do cenário conforme a largura
  var OY = 0;                       // na tela cheia o céu cresce para cima e sobra uma faixa de chão embaixo
  var SX = 15, SY = 3;              // canto do sprite do Guará na grade
  var FULL = false;
  var GROUND = 36;

  var PAL = {
    K: '#1c120c', R: '#cc622c', r: '#9c451e', H: '#eb8f50', M: '#241813', W: '#f3eadc',
    I: '#f3d4b8', N: '#0e0906', E: '#f3b63a', P: '#eb6b82', X: '#5a1d1d',
    S: '#3d4352', s: '#262a35', O: '#e3562e', T: '#7ee787', Q: '#efe6d8', q: '#b3aa9c',
    A: '#7cc4ff', Z: '#c9d4ff', F: '#d6f36b', Y: '#ffd166', B: '#ff6b6b', V: '#2b2f3d'
  };

  var EAR_L = ['...K.....', '..KRK....', '..KRK....', '..KRIK...', '.KRRIK...', '.KRRIIK..', '.KRRIIK..', '.KRRRIIK.'];
  var EAR_R = ['.....K...', '....KRK..', '....KRK..', '...KIRK..', '...KIRRK.', '..KIIRRK.', '..KIIRRK.', '.KIIRRRK.'];
  var EAR_L_FLICK = ['.........', '.KK......', 'KRK......', '.KRIK....', '.KRRIK...', '.KRRIIK..', '.KRRIIK..', '.KRRRIIK.'];
  var EAR_R_FLICK = ['.........', '......KK.', '......KRK', '....KIRK.', '...KIRRK.', '..KIIRRK.', '..KIIRRK.', '.KIIRRRK.'];
  var BODY = [
    '...KRRRIIKKKKKKKKKKIIRRRK...',
    '...KRRRRRRRRRRRRRRRRRRRRK...',
    '...KRRRHRRRRRRRRRRRRHRRRK...',
    '...KRRRRRRRRRRRRRRRRRRRRK...',
    '....KRRRRRRRRRRRRRRRRRRK....',
    '.....KRRRRRRMMMMRRRRRRK.....',
    '.....KWRRRRMMMMMMRRRRWK.....',
    '......KWRRRMMMMMMRRRWK......',
    '......KWWRRMNNNNMRRWWK......',
    '.......KWWWRMMMMRWWWK.......',
    '........KWWWWWWWWWWK........',
    '.......KMMMWWWWWWMMMK.......',
    '......KMMMMMWWWWMMMMMK......',
    '......KMMMMRRWWRRMMMMK......',
    '......KRMMRRRWWRRRMMRK......',
    '......KRRRRRRRRRRRRRRK......',
    '.....KRRRRRRRRRRRRRRRRK.....',
    '.....KRRRKMMKRRKMMKRRRK.....',
    '....KRRRrKMMK..KMMKrRRRK....',
    '....KRRrrKMMK..KMMKrrRRK....',
    '....KRRrrKMMK..KMMKrrRRK....',
    '....KRrrrKMMK..KMMKrrrRK....',
    '....KMMMMKMMK..KMMKMMMMK....',
    '....KMMMMKMMK..KMMKMMMMK....',
    '....KKKKKMMMMKKMMMMKKKKK....',
    '.........KKKKKKKKKKK........'
  ];
  var TAIL = ['...KKK.', '..KWWWK', '..KWWWK', '..KRRRK', '.KRRRRK', '.KRRRRK', '.KRRRrK', 'KRRRrK.', 'KRRrK..', 'KRrK...', 'KKK....'];
  var TAIL_WAG = ['....KKK', '...KWWW', '...KWWW', '..KRRRK', '.KRRRRK', '.KRRRRK', '.KRRRrK', 'KRRRrK.', 'KRRrK..', 'KRrK...', 'KKK....'];
  var LAPTOP = ['ssssssssssssss', 'sSSSSSSSSSSSSs', 'sSSSSSSSSSSSSs', 'sSSSSSOOSSSSSs', 'sSSSSSSSSSSSSs', 'sSSSSSSSSSSSSs', 'ssssssssssssss'];
  var PAPER = ['QQQQQQQQQQ', 'QqqqqqqQQQ', 'QQQQQQQQQQ', 'QqqqqqqqqQ', 'QQQQQQQQQQ', 'QqqqqqQQQQ'];
  var GLASS = ['..KKKK..', '.KAAAAK.', 'KAAZAAAK', 'KAAAAAAK', 'KAAAAAAK', '.KAAAAK.', '..KKKKKK', '......KKK', '.......KK'];
  var SIGN = ['KKKKKKKKKKKK', 'KQQQQQBBQQQK', 'KQQQQQBBQQQK', 'KQQQQQBBQQQK', 'KQQQQQQQQQQK', 'KQQQQQBBQQQK', 'KKKKKKKKKKKK'];
  var HEART = ['.PP.PP.', 'PPPPPPP', 'PPPPPPP', '.PPPPP.', '..PPP..', '...P...'];
  var ZED = ['ZZZ', '.Z.', 'ZZZ'];

  var canvas, ctx, bodyImg, timer = null;
  var st = {
    mood: 'idle', subagents: 0, t: 0, blinkAt: 1500, flickAt: 3000, wagUntil: 0, petUntil: 0,
    lookAt: 0, lookDir: 0, jump: 0, sparks: [], awake: true, lastFrame: 0,
    talk: 0, listening: false, level: 0, meteor: null, meteorAt: 18000, actAt: 25000, actUntil: 0
  };
  var ambient = [
    { a: 0.3, r: 0.8, x: 5, y: 24 },
    { a: 2.4, r: 1.1, x: 48, y: 23 },
    { a: 4.1, r: 0.9, x: 34, y: 27 }
  ];
  var TWINKLES = [[17, 3], [38, 2], [52, 4], [27, 8], [60, 7]];
  var TWINKLES_WIDE = [[-15, 9], [-8, 19], [44, 17], [70, 3], [76, 14], [8, 21]];

  function px(x, y, c) { ctx.fillStyle = c; ctx.fillRect(x * U, y * U, U, U); }

  function sprite(rows, x, y) {
    for (var r = 0; r < rows.length; r++) {
      for (var c = 0; c < rows[r].length; c++) {
        var ch = rows[r].charAt(c);
        if (ch !== '.') px(x + c, y + r, PAL[ch]);
      }
    }
  }

  function prerender(rows) {
    var off = document.createElement('canvas');
    off.width = rows[0].length * U;
    off.height = rows.length * U;
    var g = off.getContext('2d');
    for (var r = 0; r < rows.length; r++) {
      for (var c = 0; c < rows[r].length; c++) {
        var ch = rows[r].charAt(c);
        if (ch === '.') continue;
        g.fillStyle = PAL[ch];
        g.fillRect(c * U, r * U, U, U);
      }
    }
    return off;
  }

  function rnd(a, b) { return a + Math.random() * (b - a); }

  // ------------------------------------------------------------ rosto

  function eyes(kind, x, y, look) {
    var pts = [[x + 8, y + 11], [x + 17, y + 11]];
    for (var i = 0; i < 2; i++) {
      var ex = pts[i][0], ey = pts[i][1];
      if (kind === 'closed') {
        px(ex, ey + 1, PAL.K); px(ex + 1, ey + 1, PAL.K); px(ex + 2, ey + 1, PAL.K);
      } else if (kind === 'happy') {
        px(ex, ey + 1, PAL.K); px(ex + 1, ey, PAL.K); px(ex + 2, ey + 1, PAL.K);
      } else if (kind === 'dizzy') {
        px(ex, ey - 1, PAL.K); px(ex + 2, ey - 1, PAL.K); px(ex + 1, ey, PAL.K); px(ex, ey + 1, PAL.K); px(ex + 2, ey + 1, PAL.K);
      } else if (kind === 'wide') {
        px(ex, ey - 1, PAL.E); px(ex + 1, ey - 1, PAL.E); px(ex + 2, ey - 1, PAL.E);
        px(ex, ey, PAL.E); px(ex + 1, ey, PAL.N); px(ex + 2, ey, PAL.E);
        px(ex, ey + 1, PAL.K); px(ex + 1, ey + 1, PAL.E); px(ex + 2, ey + 1, PAL.K);
      } else {
        var down = kind === 'down';
        px(ex, ey, PAL.E); px(ex + 1, ey, PAL.E); px(ex + 2, ey, PAL.E);
        px(ex, ey + 1, PAL.K); px(ex + 1, ey + 1, PAL.E); px(ex + 2, ey + 1, PAL.K);
        var pxx = ex + 1 + look;
        px(pxx, down ? ey + 1 : ey, PAL.N);
        if (kind === 'up') px(ex + 1, ey - 1, PAL.E);
      }
    }
  }

  function mouth(kind, x, y) {
    var mx = x + 13, my = y + 17;
    if (kind === 'talk1') {
      px(mx, my, PAL.X); px(mx + 1, my, PAL.X);
    } else if (kind === 'talk2') {
      px(mx, my, PAL.X); px(mx + 1, my, PAL.X); px(mx, my + 1, PAL.P); px(mx + 1, my + 1, PAL.P);
    } else if (kind === 'talk3') {
      px(mx - 1, my, PAL.X); px(mx, my, PAL.X); px(mx + 1, my, PAL.X); px(mx + 2, my, PAL.X);
      px(mx, my + 1, PAL.X); px(mx + 1, my + 1, PAL.X); px(mx, my + 2, PAL.P); px(mx + 1, my + 2, PAL.P);
    } else if (kind === 'tongue') {
      px(mx, my, PAL.X); px(mx + 1, my, PAL.X); px(mx, my + 1, PAL.P); px(mx + 1, my + 1, PAL.P); px(mx + 1, my + 2, PAL.P);
    } else if (kind === 'open') {
      px(mx, my, PAL.X); px(mx + 1, my, PAL.X); px(mx, my + 1, PAL.X); px(mx + 1, my + 1, PAL.X);
    } else if (kind === 'yawn') {
      px(mx - 1, my, PAL.X); px(mx, my, PAL.X); px(mx + 1, my, PAL.X); px(mx + 2, my, PAL.X);
      px(mx - 1, my + 1, PAL.X); px(mx, my + 1, PAL.P); px(mx + 1, my + 1, PAL.P); px(mx + 2, my + 1, PAL.X);
      px(mx, my + 2, PAL.X); px(mx + 1, my + 2, PAL.X);
    }
  }

  // ------------------------------------------------------------ adereços

  function thought(x, y, t) {
    x = Math.max(1, x);
    ctx.fillStyle = 'rgba(243,234,220,0.95)';
    ctx.fillRect((x + 1) * U, y * U, 11 * U, 5 * U);
    ctx.fillRect(x * U, (y + 1) * U, 13 * U, 3 * U);
    ctx.fillRect((x + 11) * U, (y + 6) * U, 2 * U, 2 * U);
    ctx.fillRect((x + 13) * U, (y + 8) * U, U, U);
    var n = Math.floor(t / 320) % 4;
    for (var i = 0; i < 3; i++) px(x + 3 + i * 3, y + 2, i < n ? PAL.O : PAL.q);
  }

  function terminal(x, y, t) {
    ctx.fillStyle = '#0b0f19';
    ctx.fillRect(x * U, y * U, 13 * U, 9 * U);
    ctx.fillStyle = '#252d44';
    ctx.fillRect(x * U, y * U, 13 * U, U);
    px(x + 1, y, PAL.B); px(x + 2, y, PAL.Y); px(x + 3, y, PAL.T);
    var lines = 3 + Math.floor(t / 300) % 4;
    for (var i = 0; i < lines && i < 6; i++) {
      var w = 3 + ((i * 7 + Math.floor(t / 1200)) % 7);
      ctx.fillStyle = i === lines - 1 ? PAL.T : '#546185';
      ctx.fillRect((x + 1) * U, (y + 2 + i) * U, w * U, Math.max(2, U - 2));
    }
    if (Math.floor(t / 400) % 2) px(x + 11, y + 7, PAL.T);
  }

  function firefly(fx, fy, bright, col) {
    var c = col || PAL.F;
    ctx.globalAlpha = 0.22 * bright;
    ctx.fillStyle = c;
    ctx.fillRect((fx - 1) * U, fy * U, 3 * U, U);
    ctx.fillRect(fx * U, (fy - 1) * U, U, 3 * U);
    ctx.globalAlpha = bright;
    px(fx, fy, c);
    ctx.globalAlpha = 1;
  }

  // ------------------------------------------------------------ quadro

  function frame() {
    var t = st.t, mood = st.mood, dt = Math.min(0.5, Math.max(0, (t - (st.prevT || t)) / 1000));
    var night = (1 - LT.L) * (1 - LT.G * 0.85);
    st.prevT = t;
    ctx.clearRect(0, 0, GW * U, GH * U);

    // estrelas cintilando suavemente (só de noite e com céu aberto)
    var twk = FULL ? TWINKLES.concat(TWINKLES_WIDE) : TWINKLES;
    for (var tw = 0; tw < twk.length && night > 0.1; tw++) {
      var sx0 = twk[tw][0] + OX, sy0 = twk[tw][1];
      if (sx0 > 0 && sx0 < GW - 1) {
        ctx.globalAlpha = night * (0.25 + 0.55 * (0.5 + 0.5 * Math.sin(t / 650 + tw * 1.9)));
        ctx.fillStyle = '#fff6e5';
        ctx.fillRect(sx0 * U, sy0 * U, Math.max(2, Math.round(U * 0.6)), Math.max(2, Math.round(U * 0.6)));
      }
    }
    ctx.globalAlpha = 1;

    // estrela cadente ocasional na tela cheia
    if (FULL && !st.meteor && t > st.meteorAt && night > 0.6) {
      st.meteor = { x: rnd(14, GW - 18), y: rnd(2, 7 + OY / 2), life: 1 };
      st.meteorAt = t + rnd(20000, 42000);
    }
    if (st.meteor) {
      var m = st.meteor;
      m.x += 1.6; m.y += 0.65; m.life -= 0.14;
      if (m.life <= 0) st.meteor = null;
      else {
        ctx.globalAlpha = m.life;
        px(Math.round(m.x), Math.round(m.y), '#ffffff');
        ctx.globalAlpha = m.life * 0.55;
        px(Math.round(m.x - 1), Math.round(m.y - 0.5), PAL.Z);
        px(Math.round(m.x - 2), Math.round(m.y - 1), PAL.A);
        ctx.globalAlpha = 1;
      }
    }

    // nuvens passando devagar (as do fundo, mais apagadas)
    for (var cl = 0; cl < clouds.length; cl++) {
      var cd = clouds[cl], rows = CLOUD_ROWS[cd.k];
      cd.x += cd.v * dt;
      if (cd.x > GW + 2) { cd.x = -rows[0].length - rnd(0, 8); cd.y = Math.round(rnd(1, 8 + OY * 0.7)); }
      ctx.globalAlpha = cd.far ? 0.7 : 0.95;
      for (var cr = 0; cr < rows.length; cr++) {
        for (var cc = 0; cc < rows[cr].length; cc++) {
          var ch = rows[cr].charAt(cc);
          if (ch !== '.') px(Math.round(cd.x) + cc, cd.y + cr, ch === 'C' ? LT.cloud : LT.cloudShade);
        }
      }
    }
    ctx.globalAlpha = 1;

    // de dia, de vez em quando, um bando de pássaros cruza o céu
    if (!birds && t > birdsAt && LT.L > 0.6 && !SKY.rain) {
      birds = { x: -6, y: Math.round(rnd(4, 9 + OY * 0.5)), n: 2 + Math.floor(rnd(0, 3)) };
      birdsAt = t + rnd(40000, 90000);
    }
    if (birds) {
      birds.x += 4.5 * dt;
      if (birds.x > GW + 16 || LT.L < 0.5 || SKY.rain) birds = null;
      else {
        for (var bd = 0; bd < birds.n; bd++) {
          sprite(Math.floor(t / 230 + bd) % 2 ? BIRD_UP : BIRD_DOWN, Math.round(birds.x) - bd * 5, birds.y + (bd % 2) * 2);
        }
      }
    }

    // vagalumes do cerrado (só no escuro)
    var ffCount = (1 - LT.L) > 0.4 ? (FULL ? 3 : 2) : 0;
    for (var a = 0; a < ffCount; a++) {
      var f = ambient[a], ang = t / 3800 * f.r + f.a;
      firefly(
        Math.round(OX + f.x + Math.sin(ang) * 4),
        Math.round(f.y + OY + Math.cos(ang * 1.3) * 4),
        0.42 + 0.38 * Math.sin(t / 680 + a * 1.7)
      );
    }

    var petted = t < st.petUntil;
    var bob = 0, shakeX = 0, look = 0;
    var period = mood === 'sleeping' ? 1700 : (mood === 'typing' || mood === 'running' ? 420 : 900);
    if (st.talk > 4) bob = (Math.floor(t / 180) % 2) ? 0 : -1;
    else if (Math.floor(t / period) % 2) bob = 1;
    if (mood === 'error') shakeX = (Math.floor(t / 90) % 2) ? 1 : 0;
    if (st.jump > 0) {
      bob = -Math.round(Math.sin((1 - st.jump) * Math.PI) * 3);
      st.jump = Math.max(0, st.jump - 0.11);
    }
    if (mood === 'idle' && !st.listening && t > st.lookAt) {
      st.lookDir = st.lookDir ? 0 : (Math.random() < 0.5 ? -1 : 1);
      st.lookAt = t + (st.lookDir ? rnd(800, 1600) : rnd(3000, 6800));
    }
    if ((mood === 'idle' || petted) && !st.listening) look = st.lookDir;
    if (mood === 'running' || mood === 'searching') look = 1;
    if (mood === 'done' || st.talk > 0 || petted) st.wagUntil = Math.max(st.wagUntil, t + 400);

    // de vez em quando, à toa, ele boceja; na tela cheia acompanha a estrela cadente com os olhos
    var calm = mood === 'idle' && !st.listening && !petted && st.talk === 0;
    if (calm && t > st.actAt) { st.actUntil = t + 1700; st.actAt = t + rnd(30000, 70000); }
    var yawning = calm && t < st.actUntil;
    var gazing = FULL && (st.meteor || birds) && mood !== 'sleeping' && !st.listening;
    if (gazing) look = 1;

    var x = SX + shakeX, y = SY + bob;

    // sombra no chão
    ctx.fillStyle = 'rgba(6,8,18,0.42)';
    var sw = 22 + Math.min(0, bob) * 2;
    ctx.fillRect((SX + 14 - sw / 2) * U, GROUND * U, sw * U, U);

    // cauda
    if (t > st.wagUntil + rnd(6000, 12000) && mood === 'idle') st.wagUntil = t + 1300;
    var wag = t < st.wagUntil && Math.floor(t / (petted ? 110 : 155)) % 2;
    sprite(wag ? TAIL_WAG : TAIL, x + 23, y + 20);

    // orelhas
    var flickL = mood !== 'sleeping' && !st.listening && ((t > st.flickAt && t < st.flickAt + 220) || (petted && Math.floor(t / 220) % 2 === 0));
    var flickR = petted && Math.floor(t / 220) % 2 === 1;
    if (t > st.flickAt + 4200 + rnd(0, 5500)) st.flickAt = t;
    if (st.listening) {
      sprite(EAR_L, x + 2, y - 1);
      sprite(EAR_R, x + 17, y - 1);
    }
    sprite(flickL ? EAR_L_FLICK : EAR_L, x + 2, y);
    sprite(flickR ? EAR_R_FLICK : EAR_R, x + 17, y);

    ctx.drawImage(bodyImg, x * U, (y + 8) * U);

    // olhos
    var blinking = t > st.blinkAt && t < st.blinkAt + 140;
    if (t > st.blinkAt + 140) st.blinkAt = t + rnd(2200, 5200);
    var eyeKind = 'open';
    if (st.listening) eyeKind = 'wide';
    else if (petted || mood === 'done' || st.sparks.length > 8) eyeKind = 'happy';
    else if (mood === 'sleeping') eyeKind = 'closed';
    else if (mood === 'error') eyeKind = 'dizzy';
    else if (mood === 'waiting') eyeKind = 'wide';
    else if (mood === 'thinking') eyeKind = 'up';
    else if (mood === 'typing' || mood === 'reading') eyeKind = 'down';
    if (gazing && eyeKind === 'open') eyeKind = 'up';
    if (yawning) eyeKind = 'closed';
    if (blinking && (eyeKind === 'open' || eyeKind === 'up' || eyeKind === 'down')) eyeKind = 'closed';
    eyes(eyeKind, x, y, look);

    var mouthKind = '';
    if (st.talk > 0) mouthKind = st.talk > 6 ? 'talk3' : (st.talk > 3 ? 'talk2' : 'talk1');
    else if (petted || mood === 'done') mouthKind = 'tongue';
    else if (mood === 'waiting') mouthKind = 'open';
    else if (yawning) mouthKind = 'yawn';
    mouth(mouthKind, x, y);

    // adereços por estado
    if (mood === 'waiting') {
      var up = Math.floor(t / 300) % 2;
      ctx.fillStyle = PAL.M;
      ctx.fillRect((x + 29) * U, (y + 6 - up) * U, U, 15 * U);
      sprite(SIGN, x + 24, y - 1 - up);
    } else if (mood === 'typing') {
      sprite(LAPTOP, x + 7, y + 26);
      var tap = Math.floor(t / 150) % 2;
      sprite(['MM', 'MM'], x + 9, y + 24 + tap);
      sprite(['MM', 'MM'], x + 16, y + 25 - tap);
    } else if (mood === 'reading') {
      sprite(PAPER, x + 9, y + 26 + (Math.floor(t / 1500) % 2));
      sprite(['MM'], x + 8, y + 27);
      sprite(['MM'], x + 18, y + 27);
    } else if (mood === 'searching') {
      sprite(GLASS, x + 29 + Math.round(Math.sin(t / 500) * 2), y + 10);
    } else if (mood === 'running') {
      terminal(x + 29, y + 7, t);
    } else if (mood === 'thinking') {
      thought(x - 11, y + 2, t);
    } else if (mood === 'error') {
      px(x + 24, y + 9, PAL.A); px(x + 24, y + 10, PAL.A); px(x + 23, y + 10, PAL.A);
    }

    // ajudantes (subagentes) = vagalumes em órbita
    for (var i = 0; i < Math.min(st.subagents, 6); i++) {
      var ang2 = t / 900 + i * (Math.PI * 2 / Math.min(st.subagents, 6));
      firefly(Math.round(x + 14 + Math.cos(ang2) * 17), Math.round(y + 15 + Math.sin(ang2) * 9), 0.9);
    }
    if (st.subagents > 6) {
      ctx.fillStyle = PAL.F;
      ctx.font = '700 ' + (U * 3) + 'px Barlow, sans-serif';
      ctx.fillText('+' + (st.subagents - 6), (x + 30) * U, (y + 3) * U);
    }

    // ondas de som ao redor das duas orelhas quando está ouvindo você
    if (st.listening) {
      var waves = 1 + Math.min(3, Math.round(st.level / 2.6));
      for (var wv = 0; wv < waves; wv++) {
        var h2 = 1 + wv;
        var col = wv % 2 ? PAL.A : PAL.Z;
        for (var wy = -h2; wy <= h2; wy++) {
          px(x + 27 + wv * 2, y + 4 + wy, col);
          if (x - 1 - wv * 2 > 0) px(x - 1 - wv * 2, y + 4 + wy, col);
        }
      }
    }

    if (mood === 'sleeping' && !st.listening && !petted) {
      for (var z = 0; z < 3; z++) {
        var phase = ((t / 2400) + z / 3) % 1;
        ctx.globalAlpha = 1 - phase;
        sprite(ZED, x + 25 + z * 2, Math.round(y + 6 - phase * 9));
        ctx.globalAlpha = 1;
      }
    }

    // partículas: brilhos, corações de carinho e vagalumes de toque
    if (mood === 'done' && st.sparks.length < 10 && Math.random() < 0.3) spark();
    for (var sIdx = st.sparks.length - 1; sIdx >= 0; sIdx--) {
      var sp = st.sparks[sIdx];
      sp.life -= sp.decay || 0.05;
      if (sp.vy) sp.y += sp.vy;
      if (sp.vx) sp.x += sp.vx;
      if (sp.life <= 0) { st.sparks.splice(sIdx, 1); continue; }
      var rx = Math.round(sp.x), ry = Math.round(sp.y);
      ctx.globalAlpha = Math.min(1, sp.life * 1.15);
      if (sp.kind === 'heart') {
        sprite(HEART, rx - 3, ry - 3);
      } else if (sp.kind === 'fly') {
        ctx.globalAlpha = 1;
        firefly(rx, ry, Math.min(1, sp.life * 1.2), PAL.F);
      } else {
        px(rx, ry, PAL.Y);
        if (sp.life > 0.5) { px(rx - 1, ry, PAL.Y); px(rx + 1, ry, PAL.Y); px(rx, ry - 1, PAL.Y); px(rx, ry + 1, PAL.Y); }
      }
      ctx.globalAlpha = 1;
    }

    // chuva: fraca ou forte, um pouco inclinada pelo vento, com respingos no chão
    if (drops.length) {
      var dw = Math.max(1, Math.round(U * 0.22)), dh = Math.round(U * (SKY.rain > 1 ? 1.9 : 1.3));
      ctx.fillStyle = LT.L > 0.4 ? 'rgba(225,233,245,0.55)' : 'rgba(165,182,225,0.5)';
      for (var dr = 0; dr < drops.length; dr++) {
        var d = drops[dr];
        d.y += d.v * dt;
        d.x -= d.v * dt * 0.14;
        if (d.y > GROUND) {
          if (Math.random() < 0.35) ctx.fillRect(Math.round(d.x * U) - dw, GROUND * U - dw, dw * 3, dw);
          d.y = rnd(-6, 0);
          d.x = rnd(0, GW + 8);
        }
        ctx.fillRect(Math.round(d.x * U), Math.round(d.y * U), dw, dh);
      }
    }
    if (SKY.storm && t > flashAt) { flashUntil = t + 170; flashAt = t + rnd(7000, 16000); }
    if (t < flashUntil) {
      ctx.fillStyle = 'rgba(235,240,255,0.3)';
      ctx.fillRect(0, 0, GW * U, GH * U);
    }
  }

  function spark(gx, gy, kind) {
    st.sparks.push({
      x: gx != null ? gx : Math.round(SX + rnd(-3, 30)),
      y: gy != null ? gy : Math.round(SY + rnd(0, 19)),
      vy: kind === 'heart' ? -0.22 : (kind === 'fly' ? -0.14 : -0.05),
      vx: kind === 'fly' ? rnd(-0.12, 0.12) : 0,
      decay: kind === 'fly' ? 0.028 : (kind === 'heart' ? 0.04 : 0.055),
      life: 1,
      kind: kind || 'spark'
    });
  }

  function fps() {
    if (st.talk > 0 || st.listening || st.t < st.petUntil) return 16;
    if (!st.awake || st.mood === 'sleeping') return 4;
    if (st.mood === 'done' || st.jump > 0 || st.sparks.length || st.meteor || drops.length || SKY.storm) return 14;
    if (st.mood === 'idle') return 8;
    return 10;
  }

  var paused = false;   // tela "apagada": a animação para de vez

  function loop() {
    if (paused) { timer = null; return; }
    var now = Date.now();
    st.t += Math.min(400, now - (st.lastFrame || now));
    st.lastFrame = now;
    if (now > skyCheckAt) {   // a luz do dia muda devagar: repinta o fundo só quando ela mudou de fato
      skyCheckAt = now + 30000;
      var before = LT.key;
      computeLight();
      if (LT.key !== before && bgCanvas) paintScene(bgCanvas);
    }
    frame();
    timer = setTimeout(loop, 1000 / fps());
  }

  // ------------------------------------------------------------ céu do momento: hora do dia e tempo lá fora
  // Igual ao projeto MINHA TV: o sol nasce e se põe na hora certa (Open-Meteo, Goiânia), nublado acinzenta,
  // chuva fraca ou forte cai na frente de tudo e trovoada relampeja. Sem dados, segue o relógio com 6h/18h.

  var SKY = { rise: 360, set: 1080, cloud: 15, rain: 0, storm: false, overcast: false, fog: false };
  var LT = { L: 0, W: 0, G: 0, e: -1, p: -1, key: '' };
  var forcedMin = null;             // prévia: força a hora do dia (minutos desde a meia-noite)
  var clouds = [], drops = [], flashUntil = 0, flashAt = 9000, birds = null, birdsAt = 20000, skyCheckAt = 0;

  var SKY_NIGHT = ['#0d1129', '#19224a', '#2b2d58', '#3d3356'];
  var SKY_DAY = ['#2c6cc2', '#4a8dd8', '#86bce8', '#c6e2f1'];
  var SKY_WARM = ['#2a3672', '#6a4d8c', '#dc785c', '#f6b26b'];
  var SKY_GRAY_DAY = ['#66727f', '#7c8895', '#97a2ad', '#b0b9c1'];
  var SKY_GRAY_NIGHT = ['#121520', '#181c28', '#1f2330', '#272a36'];
  var CLOUD_ROWS = [
    ['....CCCC......', '..CCCCCCCC.CC.', '.CCCCCCCCCCCCC', '.cccccccccccc.'],
    ['...CCC....', '.CCCCCCC..', 'CCCCCCCCCC', '.cccccccc.'],
    ['.....CCC.......', '..CCCCCCCC.....', '.CCCCCCCCCCCC..', 'CCCCCCCCCCCCCCC', '.ccccccccccccc.']
  ];
  var BIRD_UP = ['V...V', '.V.V.', '..V..'], BIRD_DOWN = ['.....', 'VV.VV', '..V..'];

  function rgb(h) { var n = parseInt(h.slice(1), 16); return [n >> 16 & 255, n >> 8 & 255, n & 255]; }
  function mix(a, b, k) {
    var x = rgb(a), y = rgb(b), o = '#';
    k = Math.max(0, Math.min(1, k));
    for (var i = 0; i < 3; i++) {
      var v = Math.round(x[i] + (y[i] - x[i]) * k);
      o += (v < 16 ? '0' : '') + v.toString(16);
    }
    return o;
  }

  function nowMin() {
    if (forcedMin != null) return forcedMin;
    var d = new Date();
    return d.getHours() * 60 + d.getMinutes() + d.getSeconds() / 60;
  }

  // L = luz do dia (0 noite, 1 dia claro); W = brasa do amanhecer/entardecer; G = quanto o céu está cinza
  function computeLight() {
    var now = nowMin(), rise = SKY.rise, set = SKY.set, p = (now - rise) / (set - rise), e;
    if (p >= 0 && p <= 1) e = Math.sin(p * Math.PI);
    else e = -Math.min(1, (now < rise ? rise - now : now - set) / 70);
    LT.e = e; LT.p = p;
    LT.G = SKY.overcast ? 0.8 : (SKY.rain ? (SKY.rain > 1 ? 0.9 : 0.72) : SKY.cloud / 100 * 0.35);
    LT.L = Math.max(0, Math.min(1, (e + 0.3) / 0.55));
    LT.W = Math.max(0, 1 - Math.abs(e - 0.03) / 0.3) * (1 - LT.G * 0.7);
    var b = LT.L, cw = LT.W * 0.6, cg = LT.G * 0.8;
    LT.cloud = mix(mix(mix('#2c3354', '#f3f6fa', b), '#f6b59a', cw), mix('#20242f', '#a9b3bd', b), cg);
    LT.cloudShade = mix(mix(mix('#20263f', '#c8d4e2', b), '#c98a86', cw), mix('#181b25', '#87929e', b), cg);
    LT.key = [Math.round(LT.L * 20), Math.round(LT.W * 20), Math.round(LT.G * 10), Math.round(Math.max(0, Math.min(1, p)) * 50)].join();
  }

  function skyStop(i) {
    var c = mix(SKY_NIGHT[i], SKY_DAY[i], LT.L);
    c = mix(c, SKY_WARM[i], LT.W * 0.85);
    return mix(c, mix(SKY_GRAY_NIGHT[i], SKY_GRAY_DAY[i], LT.L), LT.G);
  }

  function landC(night, day) {
    return mix(mix(night, day, LT.L * (1 - LT.G * 0.35)), '#c98058', LT.W * 0.18);
  }

  function makeWeather() {
    var n = Math.round(SKY.cloud / 100 * (FULL ? 7 : 4));
    if (SKY.overcast || SKY.rain) n = FULL ? 9 : 6;
    clouds = [];
    for (var i = 0; i < n; i++) {
      clouds.push({ k: i % 3, x: rnd(-14, GW), y: Math.round(rnd(1, 8 + OY * 0.7)), v: rnd(0.25, 0.6), far: i % 2 === 1 });
    }
    var d = !SKY.rain ? 0 : (SKY.rain > 1 ? (FULL ? 150 : 70) : (FULL ? 55 : 26));
    drops = [];
    for (var j = 0; j < d; j++) drops.push({ x: rnd(0, GW + 6), y: rnd(-GH, GROUND), v: rnd(26, 38) });
  }

  function paintScene(c) {
    computeLight();
    var g = c.getContext('2d'), W = GW * U, H = GH * U, N = 1 - LT.L, vis = 1 - LT.G * 0.8;
    c.width = W; c.height = H;
    var sky = g.createLinearGradient(0, 0, 0, H);
    sky.addColorStop(0, skyStop(0));
    sky.addColorStop(0.45, skyStop(1));
    sky.addColorStop(0.78, skyStop(2));
    sky.addColorStop(1, skyStop(3));
    g.fillStyle = sky;
    g.fillRect(0, 0, W, H);

    function blk(x, y, w, h, col) { g.fillStyle = col; g.fillRect((x + OX) * U, y * U, w * U, h * U); }
    function land(x, y, w, h, col) { blk(x, y + OY, w, h, col); }

    // noite: halo da lua, estrelas e lua crescente (somem no amanhecer e atrás das nuvens)
    if (N > 0.04) {
      g.globalAlpha = N * Math.max(0.2, vis);
      var glow = g.createRadialGradient((9 + OX) * U, 6 * U, 2 * U, (9 + OX) * U, 6 * U, 18 * U);
      glow.addColorStop(0, 'rgba(248,234,202,0.24)');
      glow.addColorStop(0.5, 'rgba(248,234,202,0.07)');
      glow.addColorStop(1, 'rgba(248,234,202,0)');
      g.fillStyle = glow;
      g.fillRect(0, 0, W, H);
      var stars = [[3, 2], [14, 5], [24, 1], [31, 5], [44, 7], [55, 3], [58, 10], [48, 13], [35, 10], [21, 9], [2, 12],
        [-3, 6], [-2, 15], [62, 4], [64, 12], [66, 6]];
      for (var i = 0; i < stars.length; i++) {
        g.fillStyle = i % 3 ? 'rgba(255,255,255,0.32)' : 'rgba(255,248,232,0.82)';
        g.fillRect((stars[i][0] + OX) * U, stars[i][1] * U, Math.max(2, Math.round(U * 0.5)), Math.max(2, Math.round(U * 0.5)));
      }
      if (FULL) {   // céu largo: mais estrelas, sempre nas mesmas posições
        var seed = 11, sz = Math.max(2, Math.round(U * 0.35));
        for (var k = 0; k < 48; k++) {
          seed = (seed * 9301 + 49297) % 233280;
          var ex = Math.floor(seed / 233280 * GW);
          seed = (seed * 9301 + 49297) % 233280;
          var ey = Math.floor(seed / 233280 * (20 + OY));
          g.fillStyle = k % 5 ? 'rgba(255,255,255,0.2)' : 'rgba(255,248,232,0.62)';
          g.fillRect(ex * U, ey * U, sz, sz);
        }
      }
      blk(7, 3, 4, 4, '#f7e8c8');
      blk(8, 2, 2, 1, '#f7e8c8');
      blk(9, 3, 2, 2, skyStop(0));
      g.globalAlpha = 1;
    }

    // sol: arco da esquerda (nascente) para a direita (poente); baixo e alaranjado nas pontas do dia
    if (LT.p > -0.08 && LT.p < 1.08) {
      var sp = Math.max(0, Math.min(1, LT.p)), hz = 27 + OY;
      var scx = 5 + sp * (GW - 10), scy = (LT.p < 0 || LT.p > 1) ? hz + 2 : hz - Math.sin(sp * Math.PI) * (hz - 5);
      var sc = mix('#fff2c0', '#ffa94d', LT.W), sr = LT.W > 0.4 ? 3 : 2, cr = rgb(sc);
      var sg = g.createRadialGradient(scx * U, scy * U, sr * U, scx * U, scy * U, (sr + 13) * U);
      sg.addColorStop(0, 'rgba(' + cr.join(',') + ',' + ((0.3 + LT.W * 0.25) * vis).toFixed(3) + ')');
      sg.addColorStop(1, 'rgba(' + cr.join(',') + ',0)');
      g.fillStyle = sg;
      g.fillRect(0, 0, W, H);
      g.globalAlpha = vis * vis;   // atrás das nuvens o disco quase some; na chuva forte, some
      g.fillStyle = sc;
      for (var dy = -sr; dy <= sr; dy++) {
        for (var dx = -sr; dx <= sr; dx++) {
          if (dx * dx + dy * dy <= sr * sr + sr) g.fillRect(Math.round(scx + dx) * U, Math.round(scy + dy) * U, U, U);
        }
      }
      g.globalAlpha = 1;
    }

    var C = {
      far: landC('#191f3d', '#7d9a95'), near: landC('#22294a', '#5d8156'),
      trunk: landC('#2b1d17', '#5b3a28'), leafA: landC('#203c2e', '#3d7046'), leafB: landC('#264833', '#4b8550'),
      leafC: landC('#1e382b', '#356640'), leafHi: landC('#356341', '#6aa35d'),
      flowA: landC('#d99b38', '#f0bf2e'), flowB: landC('#f3b23c', '#ffd84a'),
      mound: landC('#6b4a2f', '#b07a4c'), moundD: landC('#4f3622', '#865733'),
      sil: landC('#221a1c', '#4a3a30'), silA: landC('#1a2c26', '#3b6548'), silB: landC('#1d3029', '#477455'),
      bush: landC('#1c2a22', '#3f6a45'), berry: landC('#b0563a', '#e0704a'),
      grd: landC('#384624', '#7d9a3c'), grdD: landC('#2b361b', '#62802e'), grassA: landC('#7b7c3c', '#b7b65a'), grassB: landC('#58662c', '#8fa046')
    };

    // chapadas ao fundo (duas camadas de profundidade)
    var farHills = [28, 27, 27, 26, 26, 27, 28, 29, 29, 28, 27, 26, 26, 25, 26, 27, 28, 28, 27, 28, 29, 28];
    for (var fx = -Math.ceil(OX / 3) - 1; fx * 3 < GW - OX + 3; fx++) {
      var fh = farHills[((fx % 22) + 22) % 22];
      land(fx * 3, fh, 3, 36 - fh, C.far);
    }
    var nearHills = [31, 30, 30, 29, 29, 30, 31, 31, 32, 31, 30, 29, 29, 28, 29, 30, 31, 30, 30, 31];
    for (var hx = -Math.ceil(OX / 3) - 1; hx * 3 < GW - OX + 3; hx++) {
      var nh = nearHills[((hx % 20) + 20) % 20];
      land(hx * 3, nh, 3, 36 - nh, C.near);
    }

    // ipê retorcido do cerrado (à esquerda: na zona sem botões)
    land(5, 25, 2, 11, C.trunk); land(4, 29, 1, 3, C.trunk); land(7, 22, 1, 4, C.trunk); land(3, 22, 2, 3, C.trunk);
    land(0, 18, 8, 4, C.leafA); land(2, 16, 9, 3, C.leafB); land(6, 19, 6, 4, C.leafC); land(-1, 21, 4, 2, C.leafC);
    land(3, 17, 3, 1, C.leafHi); land(8, 17, 2, 1, C.leafHi);
    land(2, 17, 1, 1, C.flowA); land(5, 16, 1, 1, C.flowB); land(9, 19, 1, 1, C.flowA);

    // cupinzeiro (direita)
    var rx = FULL ? 55 : 52;
    land(rx, 28, 4, 8, C.mound); land(rx - 1, 31, 6, 5, C.mound); land(rx + 1, 26, 2, 2, C.mound);
    land(rx + 1, 29, 1, 2, C.moundD); land(rx + 3, 32, 1, 2, C.moundD); land(rx, 33, 1, 2, C.moundD);

    if (FULL) {   // tela larga: um pé de pequi e um arbusto nas pontas, mais ao fundo
      var px0 = GW - OX - 13;
      land(px0 + 4, 27, 2, 9, C.sil); land(px0 + 2, 25, 3, 2, C.sil);
      land(px0, 21, 10, 4, C.silA); land(px0 + 1, 19, 8, 2, C.silB); land(px0 + 3, 18, 4, 1, C.silB);
      land(-OX + 3, 32, 6, 4, C.bush); land(-OX + 4, 31, 4, 1, C.bush); land(-OX + 5, 30, 1, 1, C.berry);
    }

    // chão do cerrado e capim dourado
    blk(-OX - 2, GROUND, GW + 4, GH - GROUND, C.grd);
    blk(-OX - 2, GROUND + 2, GW + 4, GH - GROUND - 2, C.grdD);
    for (var gx = -OX; gx < GW - OX + 2; gx += 2) {
      blk(gx, GROUND - ((gx * 7 + 70) % 3 === 0 ? 1 : 0), 1, 1, (gx % 4) ? C.grassA : C.grassB);
    }

    // neblina rente ao chão
    if (SKY.fog) {
      var fg = g.createLinearGradient(0, (GROUND - 16) * U, 0, GROUND * U);
      fg.addColorStop(0, 'rgba(205,210,218,0)');
      fg.addColorStop(1, 'rgba(205,210,218,0.5)');
      g.fillStyle = fg;
      g.fillRect(0, (GROUND - 16) * U, W, 16 * U);
    }
  }

  var bgCanvas = null;

  function layout(unit, gw, fullMode, gh) {
    U = unit;
    GW = gw || 65;
    GH = gh || 40;
    FULL = !!fullMode;
    OX = Math.floor((GW - 60) / 2);
    // Tela cheia: Guará no centro, céu alto em cima e uma faixa de chão embaixo para a linha de status
    OY = FULL ? Math.max(0, GH - 46) : 0;
    GROUND = 36 + OY;
    SY = 3 + OY;
    SX = FULL ? Math.floor(GW / 2) - 14 : (13 + OX);
    Guara.unit = U;
    Guara.size = { w: GW * U, h: GH * U };
    canvas.width = GW * U;
    canvas.height = GH * U;
    bodyImg = prerender(BODY);
    makeWeather();
    if (bgCanvas) paintScene(bgCanvas);
  }

  function toGrid(clientX, clientY) {
    if (!canvas) return { x: SX + 14, y: SY + 15 };
    var r = canvas.getBoundingClientRect();
    return {
      x: Math.floor((clientX - r.left) / U),
      y: Math.floor((clientY - r.top) / U)
    };
  }

  var Guara = {
    init: function (el, bg, unit, gw) {
      canvas = el;
      bgCanvas = bg;
      ctx = canvas.getContext('2d');
      layout(unit || U, gw || 65, false);
      if (!timer) loop();
    },
    resize: function (unit, gw, fullMode, gh) { layout(unit, gw, fullMode, gh); },
    setMood: function (mood, subagents) {
      if (mood !== st.mood) {
        st.mood = mood;
        if (mood === 'done') { st.jump = 1; for (var i = 0; i < 6; i++) spark(); }
      }
      st.subagents = subagents || 0;
    },
    setAwake: function (awake) { st.awake = awake; },
    setSky: function (d) {
      d = d || {};
      SKY.rise = d.rise || 360; SKY.set = d.set || 1080;
      SKY.cloud = d.cloud || 0; SKY.rain = d.rain || 0;
      SKY.storm = !!d.storm; SKY.overcast = !!d.overcast; SKY.fog = !!d.fog;
      forcedMin = d.force != null ? d.force : null;
      makeWeather();
      if (bgCanvas) paintScene(bgCanvas);
    },
    pause: function (on) {
      paused = !!on;
      if (!paused && !timer) { st.lastFrame = Date.now(); loop(); }
    },
    setTalk: function (v) { st.talk = v; },
    setListening: function (on, level) { st.listening = on; st.level = level || 0; },
    hitTest: function (clientX, clientY) {
      var g = toGrid(clientX, clientY);
      return g.x >= SX && g.x <= SX + 29 && g.y >= SY && g.y <= SY + 34;
    },
    pet: function () {
      st.jump = 1;
      st.wagUntil = st.t + 2600;
      st.petUntil = st.t + 2200;
      spark(SX + 8, SY + 2, 'heart');
      spark(SX + 20, SY + 1, 'heart');
      for (var i = 0; i < 5; i++) spark();
    },
    poke: function () {
      Guara.pet();
    },
    tapSky: function (clientX, clientY) {
      var g = toGrid(clientX, clientY);
      st.lookDir = g.x < SX + 14 ? -1 : 1;
      st.lookAt = st.t + 2200;
      st.flickAt = st.t;
      for (var i = 0; i < 3; i++) {
        spark(g.x + rnd(-2, 2), g.y + rnd(-2, 2), 'fly');
      }
    },
    mood: function () { return st.mood; },
    unit: U,
    size: { w: GW * U, h: GH * U }
  };

  global.Guara = Guara;
})(window);
