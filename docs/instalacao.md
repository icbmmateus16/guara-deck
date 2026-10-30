# Instalação

## PC e primeiro teste

O alvo atual é Linux com GNOME, Python 3.10+ e PipeWire/WirePlumber. Não execute o servidor como root. Windows e macOS não têm suporte às ações do desktop.

No Ubuntu:

```bash
sudo apt install python3-venv python3-gi gir1.2-gtk-3.0 curl
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements.txt
cp server/config.example.json server/config.json
.venv/bin/python server/capi_server.py
```

Execute dentro da pasta clonada. Se já tem `server/config.json`, mantenha o seu. O servidor gera o token ao iniciar; abra a URL impressa no terminal. Não cole essa URL em issues nem em prints.

O navegador permite testar o painel. Microfone e reprodução PCM do tablet dependem do app nativo. Sem as CLIs de IA, os recursos que dependem delas não estarão disponíveis.

## App do tablet

O build usa JDK 17, Android SDK Platform 34 e Build Tools 34.0.0. Instale esses componentes pelo gerenciador do Android SDK. Não precisa de Gradle.

1. Inicie o servidor uma vez para gerar `server/config.json`.
2. Configure o SDK e o Java. O script assume `$HOME/Android/Sdk` e `$HOME/Android/jdk-17` se as variáveis não estiverem definidas.
3. Conecte o tablet por USB, ative depuração USB e confirme a autorização ADB.

```bash
export ANDROID_HOME="$HOME/Android/Sdk"
export JAVA_HOME="/caminho/para/jdk-17"
bash tablet/build.sh
"$ANDROID_HOME/platform-tools/adb" devices
"$ANDROID_HOME/platform-tools/adb" -s SEU_SERIAL install -r tablet/build/capi.apk
```

Substitua `SEU_SERIAL` pelo aparelho correto da lista. O APK é assinado com uma chave de desenvolvimento criada localmente. Ele inclui token, porta e um IP inicial do PC; não distribua o APK nem a chave. Se o token mudar, recompile e reinstale.

Mantenha PC e tablet na mesma rede. O app usa UDP `47800` para descoberta e TCP `47801` para o painel. Se o firewall bloquear, libere apenas a sua sub-rede de confiança nessas portas. Redes de convidados com isolamento entre dispositivos impedem a conexão.

Android 4.4 é o alvo mínimo do manifesto. O aparelho testado é o Genesis GT-7305; em versões mais recentes do Android, permissões e instalação podem exigir adaptações.

## Integrações opcionais

**GNOME e mídia:** `python3-gi` permite ler os players via D-Bus/MPRIS. Volume depende de `wpctl`; Docker, de uma instalação local com acesso do usuário; GPU NVIDIA, de `nvidia-smi`. Recursos ausentes podem ficar vazios ou indisponíveis.

**Agentes:** instale e autentique as CLIs desejadas separadamente. Claude Code e Codex são detectados por hooks e arquivos de sessão. As missões e a conversa usam a ordem em `engines`. A integração `agy` depende de uma CLI compatível disponível no `PATH`; não é requisito para o painel.

Para instalar os hooks do Claude Code:

```bash
.venv/bin/python server/install_hooks.py
# Para remover depois:
.venv/bin/python server/install_hooks.py --remover
```

O instalador modifica `~/.claude/settings.json` e faz backup antes. Revise as alterações. Na implementação atual, hooks e barra de status usam a porta fixa `47801`.

**Voz e YouTube:** instale `ffmpeg` e `mpv` no sistema e os pacotes opcionais:

```bash
.venv/bin/python -m pip install -r requirements-voice.txt
```

O reconhecimento atual usa Whisper com `device="cuda"`; requer GPU NVIDIA, drivers e PyTorch com CUDA compatíveis. Não há fallback de transcrição para CPU. O modelo é baixado no primeiro uso. O `edge-tts` depende de internet; o Piper precisa dos modelos de voz instalados em `~/.local/share/piper`. Busca e áudio do YouTube dependem de `yt-dlp`; disponibilidade varia conforme o serviço. Ative `voice_enabled` na configuração quando o ambiente estiver pronto.

## Iniciar junto com a sessão

Gere uma unidade com os caminhos da sua cópia, sem editar o arquivo de exemplo nem usar caminhos de outra pessoa:

```bash
.venv/bin/python scripts/install_service.py
systemctl --user daemon-reload
systemctl --user enable --now capi.service
```

Para acompanhar e parar:

```bash
journalctl --user -u capi.service -f
systemctl --user disable --now capi.service
```

O log de inicialização contém a URL com token. Não o publique inteiro.

## Ajustes do Genesis

Os scripts em `tablet/setup/` alteram aplicativos e partes do sistema Android; alguns exigem root e foram escritos para uma ROM específica. Não são necessários para experimentar o painel. Leia cada script antes de usar em qualquer aparelho. Não execute a limpeza em seu celular principal.

## Se não conectar

- Confirme que a URL abre no próprio PC e que o processo está ativo.
- Confira rede, isolamento do Wi-Fi e firewall.
- Erro 403 costuma indicar token antigo no APK: gere e instale novamente.
- Se apenas uma ação falha, confira a ferramenta correspondente no PC.
- Depois de editar `web/`, recarregue o painel. Depois de editar Python, reinicie o servidor.
