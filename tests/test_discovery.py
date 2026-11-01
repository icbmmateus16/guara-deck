import socket
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'server'))
import discovery


class DiscoveryTests(unittest.TestCase):
    def test_announces_on_wifi_and_hotspot_when_one_interface_fails(self):
        address = lambda broadcast: SimpleNamespace(family=socket.AF_INET, broadcast=broadcast)
        interfaces = {'wifi': [address('192.168.1.255')],
                      'hotspot': [address('10.42.0.255')],
                      'disconnected': [address('172.16.0.255')]}
        states = {name: SimpleNamespace(isup=name != 'disconnected') for name in interfaces}
        sock = Mock()
        sock.sendto.side_effect = [OSError('network changed'), None]
        with patch.object(discovery.psutil, 'net_if_addrs', return_value=interfaces), \
             patch.object(discovery.psutil, 'net_if_stats', return_value=states):
            discovery.announce(sock, b'CAPI1 47801', 47800)
        self.assertEqual([call.args[1] for call in sock.sendto.call_args_list],
                         [('10.42.0.255', 47800), ('192.168.1.255', 47800)])


if __name__ == '__main__':
    unittest.main()
