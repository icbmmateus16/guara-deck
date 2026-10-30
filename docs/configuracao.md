# Configuração

`server/config.example.json` é público e não contém token. `server/config.json` é da sua instalação e nunca deve ser versionado. O servidor gera um token aleatório quando ele falta. Valores não definidos usam `DEFAULT_CONFIG` em `server/capi_server.py`.

| Chave | Uso |
| --- | --- |
| `port`, `discovery_port` | HTTP/SSE e anúncio UDP. Padrões: 47801 e 47800. Os hooks usam 47801 fixo. |
| `assistant_name` | Nome exibido do assistente. |
| `shortcuts` | Lista de atalhos. Veja os exemplos em `DEFAULT_CONFIG`; alvos são locais à sua máquina. |
| `lat`, `lon` | Coordenadas enviadas ao Open-Meteo para o clima. Se omitidas, usa Goiânia como exemplo. |
| `voice_enabled` | Ativa voz. O exemplo público começa com `false`. |
| `engines` | Ordem das CLIs usadas para conversa e missões, por exemplo `["codex", "claude"]`. |
| `voice_model`, `mission_model` | Modelo usado pela integração Claude. |
| `codex_model`, `agy_model` | Modelos das outras CLIs, quando suportados por elas. |
| `mission_cwd` | Diretório de trabalho das missões. |
| `missions`, `mission_tools` | Prompts e ferramentas das missões. Revise antes de liberar ferramentas adicionais. |
| `permission_timeout` | Tempo para responder uma aprovação no tablet, em segundos. |

Reinicie o servidor depois de editar o arquivo. Mudanças no token ou porta também exigem reconstruir o APK. A aba Projetos usa `PROJECTS_DIR` em `server/pc.py`; mudar só `mission_cwd` não altera essa lista.

## Privacidade no uso

O painel mostra nomes de projetos, atividade dos agentes, estado do desktop e informações da máquina. Voz e missões podem enviar texto, transcrições ou uma captura de tela aos serviços escolhidos. O modo de leitura limita ações de algumas integrações, mas não impede o envio de conteúdo. Confira o que você pede ao assistente.

O Open-Meteo recebe as coordenadas configuradas. Voz neural e YouTube também usam serviços externos. O painel é local, mas essas funções não são inteiramente offline.

O token é uma credencial de controle do PC. Ele aparece na URL, no arquivo local, no APK e no log inicial do servidor. Não compartilhe esses itens; se houver exposição, pare o servidor, remova o token da configuração, reinicie e recompile o app com o novo token.

## Confirmação enquanto prepara a resposta

Ao enviar uma pergunta por texto ou depois de transcrever a fala, o Guará mostra uma confirmação curta no balão. Com os avisos falados ligados, ele também usa uma frase de abertura, como “Deixa eu conferir isso pra você”. Essas frases são preparadas em memória para a voz selecionada, sem consultar uma IA.

Em pedidos demorados, o balão renova o aviso a cada dez segundos enquanto aguarda, sem repetir áudios de espera. A resposta final substitui esse aviso. Uma confirmação cujo áudio terminou de ser preparado tarde demais é descartada. Se o sintetizador estiver indisponível ou os avisos falados estiverem desligados, o balão continua funcionando.
