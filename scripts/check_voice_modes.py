#!/usr/bin/env python3
"""Regressão no navegador (requer Playwright); servidor Guará deve estar ativo."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
config = json.loads((root / 'server/config.json').read_text())
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1024, 'height': 600})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.add_init_script('''
      window.mic = {mode:false, active:false, manual:0, automatic:0, cancels:0};
      window.handlers={}; window.promptRequests=0; window.delayedInvite=null;
      window.logo={state:'idle',level:0,history:[]};
      window.CapiNative={version:function(){return '8'},setBrightness:function(){},
        setLogoState:function(state,level){logo.state=state;logo.level=level;logo.history.push([state,level])},
        setVoiceMode:function(on){mic.mode=on;if(!on)mic.active=false},
        setHandsFree:function(on){mic.active=on && mic.mode},
        cancelListen:function(){mic.cancels++},stopListen:function(){},stopAudio:function(){},
        listen:function(){mic.manual++},
        listenAfterWake:function(){if(mic.mode)mic.automatic++},playWav:function(){}};
      var OriginalES=window.EventSource;
      window.EventSource=function(url){var es=new OriginalES(url),add=es.addEventListener.bind(es);window.logoEventSource=es;
        es.addEventListener=function(name,fn){handlers[name]=fn;add(name,fn)};return es};
      var timeout=window.setTimeout;
      window.setTimeout=function(fn,delay){if(delay===20000)window.delayedInvite=fn;return timeout(fn,delay)};
      if(!sessionStorage.getItem('voice-test-seeded')){
        localStorage.removeItem('guara-hf-v3');localStorage.setItem('guara-hf-v2','1');
        sessionStorage.setItem('voice-test-seeded','1');
      }
    ''')
    for route in ('mode', 'cancel', 'warm', 'prompt'):
        page.route('**/api/voice/' + route + '?*',
                   lambda request: request.fulfill(status=200, content_type='application/json', body='{"ok":true}'))
    page.goto('http://127.0.0.1:' + str(config.get('port', 47801)) + '/?t=' + config['token'],
              wait_until='domcontentloaded')
    page.wait_for_selector('#conn.on', timeout=20000)

    def emit(name, data):
        page.evaluate('(args)=>handlers[args[0]]({data:JSON.stringify(args[1])})', [name, data])

    assert page.evaluate('!mic.mode && !mic.active')
    emit('wake', {})
    emit('listen_ready', {})
    assert page.evaluate('mic.manual===0 && mic.automatic===0')
    page.locator('#hfbtn').click()
    emit('wake', {})
    # O botão deve continuar ligado durante a pausa da confirmação.
    assert page.locator('#hfbtn').get_attribute('class').endswith(' on')
    assert page.evaluate('mic.mode && !mic.active')
    page.locator('#hfbtn').click()
    assert page.evaluate('!mic.mode && !mic.active')
    emit('say', {'id':'late-prompt','kind':'listen_prompt','text':'Pode falar.','dur':1,'env':[]})
    emit('listen_ready', {})
    emit('wake', {})
    page.evaluate("if(delayedInvite)delayedInvite();CapiVoice.playState('ended','late-prompt');CapiVoice.state('ouvindo')")
    assert page.evaluate('mic.manual===0 && mic.automatic===0')
    assert 'on' not in page.locator('#mic').get_attribute('class').split()
    print('OK: modo manual ignora chamada, confirmação, temporizador e estado atrasados.')

    page.locator('#mic').click()
    assert page.evaluate('mic.manual===1')
    page.evaluate("CapiVoice.state('nada')")
    page.locator('#hfbtn').click()
    emit('wake', {})
    emit('say', {'id':'valid-prompt','kind':'listen_prompt','text':'Pode falar.','dur':1,'env':[]})
    page.evaluate("CapiVoice.playState('ended','valid-prompt')")
    assert page.evaluate('mic.automatic===1')
    page.locator('#hfbtn').click()
    page.evaluate("CapiVoice.state('ouvindo');CapiVoice.level(8)")
    assert page.evaluate('!mic.mode && !mic.active && mic.automatic===1 && mic.cancels>=3')
    assert 'on' not in page.locator('#mic').get_attribute('class').split()
    page.reload(wait_until='domcontentloaded')
    page.wait_for_selector('#conn.on', timeout=20000)
    assert page.evaluate('!mic.mode && !mic.active')
    assert not errors, errors
    print('OK: toque manual funciona; automático funciona quando escolhido; cancelamento e modo manual sobrevivem ao reload.')

    page.locator('#mic').click()
    assert page.evaluate("logo.state==='listening'")
    page.evaluate("CapiVoice.state('enviando')")
    assert page.evaluate("logo.state==='thinking'")
    page.evaluate("CapiVoice.state('erro')")
    assert page.evaluate("logo.state==='idle'")
    emit('thinking', {'text': 'Teste da luz', 'id': 'logo-test'})
    assert page.evaluate("logo.state==='thinking'")
    emit('say', {'id':'logo-reply','kind':'reply','text':'Teste','dur':2,'env':[0,0,9,9,0,0,9,9] * 5})
    # Antes do aviso do AudioTrack, a fala ainda está carregando.
    assert page.evaluate("logo.state==='thinking'")
    page.evaluate("CapiVoice.playState('playing','logo-reply')")
    page.wait_for_function("logo.history.some(function(x){return x[0]==='speaking'&&x[1]===9})")
    page.wait_for_function("logo.history.some(function(x){return x[0]==='speaking'&&x[1]===0})")
    page.evaluate("CapiVoice.playState('ended','logo-reply')")
    assert page.evaluate("logo.state==='idle'")
    emit('thinking', {'id': 'logo-completed'})
    emit('mission', {'id':'logo-completed','status':'done','text':'Fim','steps':[]})
    page.wait_for_function("logo.state==='idle'")
    emit('thinking', {'id': 'logo-disconnect'})
    page.evaluate("window.logoEventSource.onerror()")
    assert page.evaluate("logo.state==='idle'")
    assert not errors, errors
    print('OK: logo acompanha escuta, processamento e envelope da fala; restaura em erro, fim e desconexão.')
    browser.close()
