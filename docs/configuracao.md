# Configuração

`server/config.example.json` é público e não contém token. `server/config.json` é da sua instalação e nunca deve ser versionado. O servidor gera um token aleatório quando ele falta. Valores não definidos usam `DEFAULT_CONFIG` em `server/capi_server.py`.

| Chave | Uso |
| --- | --- |
| `port`, `discovery_port` | HTTP/SSE e anúncio UDP. Padrões: 47801 e 47800. Os hooks usam 47801 fixo. |
| `assistant_name` | Nome exibido do assistente. |
| `shortcuts` | Lista de atalhos. Veja os exemplos em `DEFAULT_CONFIG`; alvos são locais à sua máquina. |
| `lat`, `lon` | Coordenadas enviadas ao Open-Meteo para o clima. Se omitidas, usa Goiânia como exemplo. |
| `voice_enabled` | Ativa avisos falados. O exemplo público começa com `false`. |
| `voice_exec` | Permite ações nas conversas por voz; padrão atual `true`. Use `false` para pedir o modo de leitura das integrações. |
| `voice_exec_tools` | Ferramentas liberadas para conversas com execução; inclui edição, escrita e comandos. Revise antes de usar. |
| `engines` | Ordem das CLIs usadas para conversa e missões, por exemplo `["codex", "claude"]`. |
| `voice_model`, `mission_model` | Modelo usado pela integração Claude. |
| `codex_model`, `agy_model` | Modelos das outras CLIs, quando suportados por elas. |
| `mission_cwd` | Diretório de trabalho das missões. |
| `missions`, `mission_tools` | Prompts e ferramentas das missões. Revise antes de liberar ferramentas adicionais. |
| `permission_timeout` | Tempo para responder uma aprovação no tablet, em segundos. |

Reinicie o servidor depois de editar o arquivo. Mudanças no token ou porta também exigem reconstruir o APK. A aba Projetos usa `PROJECTS_DIR` em `server/pc.py`; mudar só `mission_cwd` não altera essa lista.

## Luz da logo Genesis

No Genesis original, a ponte nativa versão 8 anima a logo conforme a conversa:
respira enquanto ouve, pulsa enquanto processa e acompanha o volume da fala.
Há efeitos curtos para chamada, notificação, conclusão e erro; pedidos de
aprovação usam uma batida dupla e o repouso usa uma respiração lenta.
Em espera, a logo fica acesa. É uma luz de uma só cor; não há controle RGB
exposto pelo aparelho.

Os valores de `brightness` entre 1 e 255 acendem o LED com a mesma intensidade.
A versão atual simula intensidades com os intervalos rápidos do gatilho
`timer` do kernel, variando a proporção de tempo aceso e apagado. Este recurso
é experimental e específico do tablet original.

Esse recurso é opcional e exige autorização de Superuser para o app, pois os
arquivos de controle do LED são protegidos. Sem o LED ou sem autorização, o
restante do painel continua funcionando. A página envia um sinal periódico;
sem esse sinal por quatro segundos, o controle volta à luz fixa. A autorização
de root ocorre ao iniciar o controle; depois, o app escreve diretamente nos
arquivos de ritmo, sem manter um processo de shell em execução. Ao fechar
normalmente, o app restaura a luz fixa.

O recurso usa `/sys/class/leds/genesis-led` e mantém a configuração persistente
de habilitação da logo. Não altera o brilho da tela.

O LED frontal de carga não possui controle independente exposto nesta
instalação. O driver de bateria contém suporte genérico a vermelho e verde,
mas a configuração de GPIO correspondente está ausente. O projeto não altera
esse LED nem os pinos do carregador.

## Wi-Fi e hotspot para o tablet

O botão **Hotspot ACESSO** das configurações rápidas do GNOME 50 fica em
`scripts/gnome-hotspot`. Instale os dois arquivos em
`~/.local/share/gnome-shell/extensions/acesso-hotspot@tablet-control/` e habilite
a extensão. Uma extensão nova exige sair e entrar na sessão para ser descoberta.
O botão observa o perfil salvo com SSID `ACESSO` e modo AP; só o clique liga ou
desliga a rede, sem criar perfis ou mudar a conexão automática. O perfil deve ter
`connection.autoconnect no`. Nesse modo, o hotspot usa a placa Wi-Fi e substitui
a conexão Wi-Fi atual enquanto estiver ligado.

`scripts/setup_tablet_hotspot.py` configura um hotspot de ativação manual usando o nome
e a senha de um perfil já salvo no NetworkManager. Requer Linux com systemd,
`hostapd`, `dnsmasq`, `iw`, `iptables` e uma placa que aceite cliente + AP no mesmo
canal. O PC usa a internet em 2,4 GHz, compatível com o tablet antigo.

Consulte os UUIDs com `nmcli connection show` e execute:

```bash
sudo python3 scripts/setup_tablet_hotspot.py --wifi INTERFACE --upstream UUID_WIFI --hotspot UUID_HOTSPOT
```

O serviço `guara-hotspot.service` fica desabilitado na inicialização e desligado
após a instalação. Ligue somente quando quiser com
`sudo systemctl start guara-hotspot.service` e desligue com
`sudo systemctl stop guara-hotspot.service`. Ele não reinicia sozinho em caso de
falha. Antes de ligá-lo, conecte o PC a uma rede de 2,4 GHz. O serviço mantém o
hotspot separado da conexão de internet, acompanha o canal e compartilha a internet.
O painel fica em `10.42.0.1:47801`; a descoberta anuncia o PC nas duas redes.
A chave é guardada somente em arquivos de root, fora do projeto. Para parar e
desativar o hotspot: `sudo systemctl disable --now guara-hotspot.service`.

## Privacidade no uso

O painel mostra nomes de projetos, atividade dos agentes, estado do desktop e informações da máquina. Voz e missões podem enviar texto, transcrições ou uma captura de tela aos serviços escolhidos. O modo de leitura limita ações de algumas integrações, mas não impede o envio de conteúdo. Confira o que você pede ao assistente.

O Open-Meteo recebe as coordenadas configuradas. Voz neural e YouTube também usam serviços externos. O painel é local, mas essas funções não são inteiramente offline.

O token é uma credencial de controle do PC. Ele aparece na URL, no arquivo local, no APK e no log inicial do servidor. Não compartilhe esses itens; se houver exposição, pare o servidor, remova o token da configuração, reinicie e recompile o app com o novo token.

## Confirmação enquanto prepara a resposta

Ao enviar uma pergunta por texto ou depois de transcrever a fala, o Guará mostra uma confirmação curta no balão. Com os avisos falados ligados, ele também usa uma frase de abertura, como “Deixa eu conferir isso pra você”. Essas frases são preparadas em memória para a voz selecionada, sem consultar uma IA.

Em pedidos demorados, o balão renova o aviso a cada dez segundos enquanto aguarda, sem repetir áudios de espera. A resposta final substitui esse aviso. Uma confirmação cujo áudio terminou de ser preparado tarde demais é descartada. Se o sintetizador estiver indisponível ou os avisos falados estiverem desligados, o balão continua funcionando.

## Mãos livres e ações por voz

Ligue **Mãos livres** no botão de orelha para chamar pelo nome; a escolha é salva.
O botão permanece verde durante pausas temporárias enquanto esse modo está
selecionado. Ao desligá-lo, o painel cancela a captura e a confirmação pendentes;
o Android bloqueia a abertura automática do microfone, e o servidor descarta
áudios de chamada pelo nome e transcrições anteriores ao cancelamento. No modo
manual, é preciso tocar no microfone para começar a gravar.
Ao dizer apenas “Guará”, ele responde **“Pode falar”** e só depois abre o microfone
para o pedido. O microfone aguarda dois segundos de silêncio antes de transcrever.
Você também pode tocar no microfone para gravar diretamente. Uma resposta
terminada em pergunta não reabre o microfone: toque para responder. Silêncio e
transcrições de baixa confiança são descartados sem gerar resposta falada.
O app também espera 1,5 segundo após reproduzir áudio antes de retomar a escuta
do Mãos livres, para reduzir a captura do próprio eco.

As últimas seis trocas e a referência da sessão ficam em
`server/voice-session.local.json` (arquivo local, fora do Git, com acesso restrito).
O contexto recente continua disponível após reiniciar o servidor por até 48 horas;
`voice_history_hours` ajusta esse prazo. A sessão da IA é retomada diretamente
durante o intervalo `voice_session_minutes`.

O app Android com ponte nativa versão 6 inclui o botão **Mãos livres**. Quando ligado, o microfone aguarda falas e envia trechos de áudio ao PC para transcrição e identificação do chamado “Guará”. A identificação acontece no PC, não no tablet: trechos de conversa de fundo também podem ser enviados pela rede local antes de serem descartados pelo servidor. A transcrição atual usa Whisper local; pedidos aceitos seguem para a CLI de IA selecionada.

O modo pausa durante a gravação manual e a reprodução nativa de fala ou música. Desative no botão quando não quiser escuta contínua. Para receber essa função, compile e reinstale o app; só atualizar a interface web não acrescenta a ponte nativa. Não distribua o APK com o token da sua instalação.

As respostas de voz podem solicitar abertura de sites HTTP(S), apps da dock ou atalhos configurados, além de busca e reprodução no YouTube. O código valida os alvos antes de abri-los. `voice_exec: false` seleciona o modo de leitura das CLIs, mas não desativa essa ponte de abertura de sites e apps. Instruções no prompt não substituem as permissões efetivas de cada integração.

## Voz em espera e modo jogo

O reconhecimento de voz libera o modelo Whisper e sua memória na GPU depois de
**60 segundos sem receber áudio** (a verificação ocorre a cada 5 segundos). Ele volta
a carregar sob demanda ao tocar no microfone ou ao receber um trecho do mãos livres.
A opção `voice_stt_idle_seconds` permite ajustar esse intervalo em `server/config.json`.
Sons enviados pelo mãos livres também contam como uso, mesmo sem um pedido aceito.

Jogos Steam/Proton são detectados automaticamente a cada 2 segundos, inclusive
quando já estavam abertos ao iniciar o servidor. Enquanto houver um jogo aberto,
o painel mostra **Modo jogo**, esconde microfone e mãos livres e mantém as conversas
e respostas por texto. O servidor recusa novos áudios e libera o modelo da GPU
assim que uma eventual transcrição em andamento terminar. Minimizar o jogo não
reativa a voz; é preciso encerrar todos os jogos detectados.

Ao fechar o último jogo, o microfone volta a ficar disponível e a preferência
anterior de mãos livres é restaurada. O modelo só volta à GPU quando houver uso
de voz. A preferência de avisos falados não é alterada pelo modo jogo.

A detecção ignora Steam, EA e outros auxiliares conhecidos, para eles não manterem
o modo jogo após a saída do jogo. Para jogos fora da Steam, cadastre nomes exatos
de executáveis em `game_processes`, por exemplo `["meujogo.exe", "meujogo"]`.
