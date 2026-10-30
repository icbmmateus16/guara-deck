#!/usr/bin/env python3
"""Verifica nomes e padrões de segredo nos arquivos rastreados, sem mostrar valores."""
import re
import subprocess
from pathlib import Path, PurePosixPath

BLOCKED_DIRS = {'.aws', '.ssh', '.codex', '.claude', '.agents', '.venv', 'venv',
                '__pycache__', 'backups', 'backup', 'build', 'dist', 'recordings', 'screenshots', 'secrets'}
BLOCKED_SUFFIXES = {'.apk', '.aab', '.keystore', '.jks', '.pem', '.key', '.p12', '.pfx',
                    '.pyc', '.log', '.db', '.sqlite', '.sqlite3', '.bak', '.jar', '.dex', '.class', '.idsig'}
PATTERNS = [
    re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})'),
    re.compile(rb'AKIA[0-9A-Z]{16}'),
    re.compile(rb'AIza[0-9A-Za-z_-]{35}'),
    re.compile(rb'sk-(?:proj-|ant-)?[A-Za-z0-9_-]{24,}'),
    re.compile(rb'[?&]t=[A-Za-z0-9_-]{12,}'),
    re.compile(rb'(?i)["\x27](?:token|api_key|password|secret)["\x27]\s*:\s*["\x27][A-Za-z0-9_+/=-]{12,}["\x27]'),
    re.compile(rb'/home/[a-zA-Z0-9_.-]+/'),
]


def main():
    root = Path(subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], text=True).strip())
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).split(b'\0')
    failures = []
    count = 0
    for raw in filter(None, names):
        name = raw.decode('utf-8')
        path = PurePosixPath(name)
        if (set(path.parts) & BLOCKED_DIRS or path.suffix.lower() in BLOCKED_SUFFIXES
                or path.name in {'config.json', 'capi.json', 'local.properties', 'capi.service'}
                or (path.name.startswith('.env') and path.name != '.env.example')
                or 'credentials' in path.name.lower() or 'service-account' in path.name.lower()):
            failures.append((name, 'arquivo privado ou gerado'))
            continue
        # Leia o índice: um arquivo sanitizado só no disco ainda pode conter segredo no commit.
        data = subprocess.check_output(['git', 'show', ':' + name], cwd=root)
        mode = subprocess.check_output(['git', 'ls-files', '-s', '--', name], cwd=root).split()[0]
        if mode == b'120000':
            failures.append((name, 'link simbólico: revise antes de publicar'))
            continue
        count += 1
        if any(pattern.search(data) for pattern in PATTERNS):
            failures.append((name, 'possível credencial ou caminho pessoal'))
    for name, reason in failures:
        print(f'BLOQUEADO: {name}: {reason}')
    if failures:
        raise SystemExit(1)
    print(f'OK: {count} arquivos revisados por nomes e padrões; revise imagens e conteúdo manualmente também.')


if __name__ == '__main__':
    main()
