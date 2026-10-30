# Contribuir com o Guará Deck

Mudanças pequenas e fáceis de testar ajudam bastante. Para um recurso maior, abra uma issue explicando o uso antes de preparar tudo.

1. Faça um fork e crie uma branch com um nome curto: `fix/audio-tablet`, por exemplo.
2. Rode o projeto conforme o [guia de instalação](docs/instalacao.md).
3. Mantenha JavaScript compatível com ES5. O WebView do Android 4.4 não entende recursos modernos.
4. Confira os arquivos antes de commitar e execute as verificações abaixo.
5. No pull request, explique o problema, a mudança e em qual ambiente testou.

```bash
python3 scripts/check_public_files.py
python3 -m compileall -q server scripts
bash -n tablet/build.sh
```

A verificação de publicação examina os arquivos rastreados e os adicionados ao índice do Git; ela é uma barreira adicional, não uma garantia de ausência de segredos. Revise também `git diff --cached` e as imagens. Configuração local, APK, chaves e backups ficam fora do Git.

Relatos de bugs devem informar distribuição, desktop, modelo do tablet, Android e passos para reproduzir. Remova token, IP local, nome de usuário, caminhos pessoais e conteúdo de conversas de qualquer log ou captura.

O layout foi pensado para 1024 × 600. Em mudanças visuais, teste esse tamanho e, se possível, o tablet real. Para o restante, descreva quais funções você conseguiu verificar sem hardware.
