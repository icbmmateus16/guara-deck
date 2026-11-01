#!/usr/bin/env python3
"""Instala um hotspot de ativação manual, reutilizando o perfil e a senha."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def field(uuid, name, secrets=False):
    return run('nmcli', *(['--show-secrets'] if secrets else []), '-g', name,
               'connection', 'show', uuid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wifi', required=True, help='Interface física Wi-Fi')
    parser.add_argument('--upstream', required=True, help='UUID da rede de internet')
    parser.add_argument('--hotspot', required=True, help='UUID do hotspot já salvo')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Execute com sudo; criar a interface virtual exige administrador.')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,15}', args.wifi):
        parser.error('Nome de interface inválido.')
    for uuid in (args.upstream, args.hotspot):
        if not re.fullmatch(r'[a-fA-F0-9-]{36}', uuid):
            parser.error('UUID inválido.')
    for program in ['iw', 'hostapd', 'dnsmasq', 'iptables']:
        if not shutil.which(program):
            parser.error('Instale ' + program + ' antes de continuar.')
    if field(args.hotspot, '802-11-wireless.mode') != 'ap':
        parser.error('O perfil de hotspot deve estar em modo AP.')
    phy = (Path('/sys/class/net') / args.wifi / 'phy80211').resolve().name
    capabilities = run('iw', 'phy', phy, 'info')
    if not re.search(r'#\{ managed \}[^\n]*#\{ AP[, }]', capabilities):
        parser.error('A placa não anunciou suporte a cliente + AP simultâneos.')
    ssid = field(args.hotspot, '802-11-wireless.ssid')
    password = field(args.hotspot, '802-11-wireless-security.psk', secrets=True)
    if re.fullmatch(r'[a-fA-F0-9]{64}', password):
        psk = password
    elif 8 <= len(password) <= 63:
        psk = hashlib.pbkdf2_hmac('sha1', password.encode(), ssid.encode(), 4096, 32).hex()
    else:
        parser.error('O perfil precisa ter uma senha WPA2 salva.')
    directory = Path('/etc/guara-hotspot')
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    config = directory / 'config.json'
    config.write_text(json.dumps({'wifi': args.wifi, 'ssid_hex': ssid.encode().hex(), 'psk': psk}))
    config.chmod(0o600)
    helper = Path('/usr/local/lib/guara-hotspot/runtime.py')
    helper.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).with_name('tablet_hotspot_runtime.py'), helper)
    helper.chmod(0o755)
    nm = Path('/etc/NetworkManager/conf.d/90-guara-hotspot.conf')
    nm.write_text('[device-guara-hotspot]\nmatch-device=interface-name:guara-ap\nmanaged=0\n')
    run('nmcli', 'connection', 'modify', args.upstream,
        '802-11-wireless.band', 'bg', '802-11-wireless.bssid', '',
        'connection.autoconnect', 'yes')
    run('nmcli', 'connection', 'modify', args.hotspot, 'connection.autoconnect', 'no')
    # Substitui a primeira implementação pela interface controlada pelo hostapd.
    subprocess.run(['systemctl', 'disable', '--now', 'guara-hotspot-interface.service'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    unit = Path('/etc/systemd/system/guara-hotspot.service')
    unit.write_text('''# Gerado por setup_tablet_hotspot.py
[Unit]
Description=Wi-Fi fixo do tablet com internet compartilhada
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/local/lib/guara-hotspot/runtime.py
Restart=no
UMask=0077

[Install]
WantedBy=multi-user.target
''')
    run('systemctl', 'daemon-reload')
    run('systemctl', 'disable', '--now', 'guara-hotspot.service')
    print(f'Serviço instalado e desligado para a rede {ssid}, mantendo a senha anterior.')
    print('Ligue manualmente: sudo systemctl start guara-hotspot.service')
    print('Desligue: sudo systemctl stop guara-hotspot.service')


if __name__ == '__main__':
    main()
