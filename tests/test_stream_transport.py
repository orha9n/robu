"""Ollama'nın gerçek HTTP NDJSON tüketimi: UTF-8, parçalı TCP ve hata sınırları."""
import http.server
import json
import threading
import unittest
from unittest.mock import patch
from robu import cekirdek as c
from robu.cekirdek import Ollama


class TransportRegression(unittest.TestCase):
    def serve(self, payload):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200)
                self.send_header('Content-Type', 'application/x-ndjson')
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()
                # Her UTF-8 karakteri ve JSON anahtarı ağda parçalara bölünür.
                for byte in payload:
                    self.wfile.write(b'1\r\n' + bytes([byte]) + b'\r\n')
                self.wfile.write(b'0\r\n\r\n'); self.wfile.flush()
            def log_message(self, *args): pass
        server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.handle_request, daemon=True); thread.start()
        self.addCleanup(server.server_close)
        return Ollama('http://127.0.0.1:'+str(server.server_port))

    def test_fragmented_utf8_and_tool_object(self):
        messages = [{'message': {'content': 'Türkçe: ığüşöç.'}},
                    {'message': {'tool_calls': [{'function': {'name': 'komut', 'arguments': {'cmd': 'printf x'}}}]}},
                    {'done': True}]
        payload = b''.join(json.dumps(m, ensure_ascii=False).encode()+b'\n' for m in messages)
        self.assertEqual(list(self.serve(payload).sohbet_akisi({'model':'synthetic'})), messages)

    def test_stream_error_is_not_success(self):
        client = self.serve(b'{"error":"synthetic failure"}\n')
        with self.assertRaises(RuntimeError): list(client.sohbet_akisi({'model':'synthetic'}))

    def test_partial_json_is_not_yielded(self):
        client = self.serve(b'{"message":{"tool_calls":[')
        with self.assertRaises(ValueError): list(client.sohbet_akisi({'model':'synthetic'}))

    def test_cancel_before_response_headers(self):
        entered, release = threading.Event(), threading.Event()
        class Waiting(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                entered.set(); release.wait(3)
            def log_message(self, *args): pass
        server = http.server.HTTPServer(('127.0.0.1', 0), Waiting)
        serving = threading.Thread(target=server.handle_request, daemon=True); serving.start()
        events = []
        with patch.object(c, 'sistem_istemi', return_value='Sentetik sistem.'):
            a = c.Ajan(dict(c.VARSAYILAN_AYARLAR, model='synthetic',
                           ollama='http://127.0.0.1:'+str(server.server_port)),
                       lambda *e: events.append(e), lambda *args: False)
            thread = threading.Thread(target=a.calistir, args=('Sentetik soru.',), daemon=True)
            try:
                thread.start(); self.assertTrue(entered.wait(2))
                a.durdur(); thread.join(1)
                self.assertFalse(thread.is_alive())
                self.assertIn(('durduruldu',), events)
                self.assertFalse(any(e[0] == 'hata' for e in events))
            finally:
                release.set(); serving.join(1); server.server_close()

if __name__ == '__main__': unittest.main()
