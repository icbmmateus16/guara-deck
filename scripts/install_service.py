#!/usr/bin/env python3
"""Gera a unidade systemd com os caminhos desta instalação, sem iniciá-la."""
import os
from pathlib import Path


def systemd_quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def main():
    root = Path(__file__).resolve().parent.parent
    # Não resolver o symlink do Python: o caminho do venv seleciona seus pacotes.
    python = root / '.venv/bin/python'
    if not python.exists():
        raise SystemExit('Crie .venv e instale requirements.txt antes de gerar o serviço.')
    config_home = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    target = config_home / 'systemd/user/capi.service'
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise SystemExit(f'{target} já existe. Revise a unidade existente antes de substituir.')
    unit = (root / 'server/capi.service.example').read_text()
    unit = unit.replace('ExecStart=@PYTHON@ @SERVER@',
                        f'ExecStart={systemd_quote(python)} {systemd_quote(root / "server/capi_server.py")}')
    target.write_text(unit)
    print(f'Unidade criada: {target}\nAtive com systemctl --user enable --now capi.service após daemon-reload.')


if __name__ == '__main__':
    main()
