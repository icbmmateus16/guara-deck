#!/usr/bin/env python3
"""Serviço instalado como root: AP WPA2, DHCP e compartilhamento para o tablet."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

AP = 'guara-ap'
ADDRESS = '10.42.0.1'


def run(*args, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True).stdout.strip()


def channel(wifi):
    info = run('iw', 'dev', wifi, 'info')
    found = re.search(r'channel (\d+) \((\d+) MHz\)', info)
    if not found:
        return 1
    value = int(found[1])
    if int(found[2]) >= 2500:
        raise RuntimeError('A rede de internet precisa estar em 2,4 GHz para este tablet.')
    return value


def main():
    cfg = json.loads(Path('/etc/guara-hotspot/config.json').read_text())
    wifi = cfg['wifi']
    processes = []
    rules = [
        ['-t', 'nat', 'POSTROUTING', '-s', '10.42.0.0/24', '-o', wifi, '-j', 'MASQUERADE'],
        ['FORWARD', '-i', AP, '-o', wifi, '-j', 'ACCEPT'],
        ['FORWARD', '-i', wifi, '-o', AP, '-m', 'conntrack', '--ctstate', 'RELATED,ESTABLISHED', '-j', 'ACCEPT'],
    ]
    installed = []
    def stop(*_):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        if not Path('/sys/class/net/' + AP).exists():
            run('iw', 'dev', wifi, 'interface', 'add', AP, 'type', '__ap')
        run('nmcli', 'device', 'set', AP, 'managed', 'no')
        run('ip', 'link', 'set', AP, 'down')
        run('iw', 'dev', AP, 'set', 'type', '__ap')
        run('ip', 'address', 'replace', ADDRESS + '/24', 'dev', AP)
        run('sysctl', '-w', 'net.ipv4.ip_forward=1')
        for rule in rules:
            prefix = rule[:2] if rule[0] == '-t' else []
            body = rule[2:] if prefix else rule
            if subprocess.run(['iptables', *prefix, '-C', *body], capture_output=True).returncode:
                run('iptables', *prefix, '-I', *body)
                installed.append((prefix, body))
        runtime = Path('/run/guara-hotspot')
        runtime.mkdir(mode=0o700, exist_ok=True)
        dns = ['dnsmasq', '--keep-in-foreground', '--conf-file=/dev/null',
               '--interface=' + AP, '--bind-interfaces', '--listen-address=' + ADDRESS,
               '--dhcp-range=10.42.0.10,10.42.0.100,255.255.255.0,12h',
               '--dhcp-option=3,' + ADDRESS, '--dhcp-option=6,' + ADDRESS,
               '--dhcp-leasefile=' + str(runtime / 'leases'),
               '--pid-file=' + str(runtime / 'dnsmasq.pid')]
        resolver = Path('/run/systemd/resolve/resolv.conf')
        if resolver.exists():
            dns.append('--resolv-file=' + str(resolver))
        current = None
        host = None
        while True:
            selected = channel(wifi)
            if selected != current:
                if host:
                    host.terminate()
                    host.wait(timeout=10)
                conf = runtime / 'hostapd.conf'
                conf.write_text('interface=' + AP + '\ndriver=nl80211\nssid2=' + cfg['ssid_hex'] +
                                '\nhw_mode=g\nchannel=' + str(selected) +
                                '\nwmm_enabled=1\nauth_algs=1\nwpa=2\nwpa_key_mgmt=WPA-PSK\nrsn_pairwise=CCMP\nwpa_psk=' + cfg['psk'] + '\n')
                conf.chmod(0o600)
                host = subprocess.Popen(['hostapd', str(conf)])
                processes.append(host)
                current = selected
                if len(processes) == 1:
                    processes.append(subprocess.Popen(dns))
            if any(p.poll() is not None for p in processes):
                # Processos antigos de hostapd já substituídos não contam.
                if host.poll() is not None or processes[1].poll() is not None:
                    raise RuntimeError('O serviço de Wi-Fi ou DHCP encerrou; systemd tentará novamente.')
            time.sleep(5)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
        for prefix, body in reversed(installed):
            run('iptables', *prefix, '-D', *body, check=False)
        run('ip', 'link', 'set', AP, 'down', check=False)


if __name__ == '__main__':
    main()
