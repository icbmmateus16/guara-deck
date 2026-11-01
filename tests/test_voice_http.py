"""Testa o roteamento real sem iniciar os serviços e threads do servidor."""
import ast
import io
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse


class VoiceHTTPTests(unittest.TestCase):
    def handler(self, path, voice):
        source = Path(__file__).resolve().parents[1] / 'server/capi_server.py'
        tree = ast.parse(source.read_text())
        handler_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Handler')
        namespace = {'BaseHTTPRequestHandler': BaseHTTPRequestHandler, 'urlparse': urlparse,
                     'parse_qs': parse_qs, 'VOICE': voice}
        exec(compile(ast.Module(body=[handler_class], type_ignores=[]), str(source), 'exec'), namespace)
        handler = namespace['Handler'].__new__(namespace['Handler'])
        handler.path = path
        handler._authorized = lambda: True
        handler._send = Mock()
        handler.headers = {'Content-Length': '1001'}
        handler.rfile = io.BytesIO(b'0' * 1001)
        return handler

    def test_wake_flag_is_forwarded_instead_of_treating_background_audio_as_a_request(self):
        for query, wake in [('?wake=1', True), ('?wake=0', False), ('', False)]:
            with self.subTest(query=query):
                voice = Mock()
                handler = self.handler('/api/voice' + query, voice)
                handler.do_POST()
                voice.hear.assert_called_once_with(b'0' * 1001, wake=wake)

    def test_mode_endpoint_selects_manual_mode(self):
        voice = Mock(handsfree_enabled=False)
        handler = self.handler('/api/voice/mode', voice)
        handler._body = lambda: {'handsfree': False}
        handler.do_POST()
        voice.set_handsfree_mode.assert_called_once_with(False)
        handler._send.assert_called_once_with(200, {'ok': True, 'handsfree': False})


if __name__ == '__main__': unittest.main()
