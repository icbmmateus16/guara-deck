"""Descoberta em cada rede local, inclusive o hotspot simultâneo ao Wi-Fi."""
import socket

import psutil


def broadcast_targets():
    states = psutil.net_if_stats()
    targets = set()
    for name, addresses in psutil.net_if_addrs().items():
        if name not in states or not states[name].isup:
            continue
        for address in addresses:
            if address.family == socket.AF_INET and address.broadcast:
                targets.add(address.broadcast)
    return sorted(targets) or ['255.255.255.255']


def announce(sock, message, port):
    for target in broadcast_targets():
        try:
            sock.sendto(message, (target, port))
        except OSError:
            continue
