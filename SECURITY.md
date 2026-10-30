# Segurança e dados locais

Este é um painel pessoal que executa ações no computador. Use em uma rede local de confiança, sem expor as portas na internet. HTTP e Android 4.4 fazem parte das limitações atuais; o projeto não foi projetado para operar como serviço público.

O `.gitignore` exclui configuração, ambientes, backups, APKs, chaves e dados de execução. Arquivos já rastreados não são protegidos só por adicionar uma regra. Antes de publicar, revise o índice e execute `python3 scripts/check_public_files.py`.

Nunca anexe `server/config.json`, APK gerado, chave de assinatura, URL com `?t=`, histórico dos agentes ou logs completos numa issue.

Se encontrar uma vulnerabilidade, use a opção **Report a vulnerability** na aba Security do GitHub, se estiver disponível. Caso não esteja, abra uma issue apenas solicitando um canal privado, sem publicar detalhes exploráveis, credenciais ou dados pessoais. Não há prazo de resposta garantido.
