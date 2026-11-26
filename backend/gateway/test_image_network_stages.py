"""Offline tests for real socket-level image API phases (never a paid request)."""
import base64
import io
import json
import socket
import socketserver
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from backend.gateway import image_providers as providers


@contextmanager
def running(server):
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)


class ImageNetworkStageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SimpleNamespace(root=Path(self.temp.name))
        self.events = []
        self.calls = []
        self.waiting = threading.Event()
        self.allow_response = threading.Event()
        self.allow_response.set()
        self.redirect = False
        self.delay = 0
        output = io.BytesIO()
        Image.new('RGB', (16, 16)).save(output, format='PNG')
        self.body = json.dumps({'data': [{'b64_json': base64.b64encode(output.getvalue()).decode()}]}).encode()

    def server(self):
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args): pass
            def do_POST(self):
                owner.calls.append(self.path)
                self.rfile.read(int(self.headers['Content-Length']))
                owner.waiting.set()
                owner.allow_response.wait(2)
                time.sleep(owner.delay)
                if owner.redirect:
                    self.send_response(307)
                    self.send_header('Location', '/redirected')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header('Content-Length', str(len(owner.body)))
                self.end_headers()
                try: self.wfile.write(owner.body)
                except OSError: pass
        return ThreadingHTTPServer(('127.0.0.1', 0), Handler)

    def service(self, port, proxy=None):
        return dict(id='api-offline-test', api_key='OFFLINE', base_url=f'http://127.0.0.1:{port}/v1',
                    model='fake-image', sizes='standard', reference_mode='none', negative=False,
                    seed=False, steps=False, proxy=bool(proxy), proxy_url=proxy,
                    connect_timeout_seconds=1, timeout_seconds=1)

    def generate(self, service, callback=None):
        with patch.object(providers, 'get', return_value=service):
            return providers.generate(self.store, {'prompt':'offline test','size':'1024x1024'},
                                      on_status=callback or self.events.append)

    def test_delayed_headers_show_waiting_only_after_request_write(self):
        self.allow_response.clear()
        with running(self.server()) as port:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self.generate, self.service(port))
                try:
                    self.assertTrue(self.waiting.wait(1))
                    deadline = time.monotonic()+1
                    while len(self.events)<3 and time.monotonic()<deadline: time.sleep(.005)
                    self.assertEqual(self.events, ['正在建立 API 连接','正在发送生图请求','等待服务商响应'])
                finally:
                    self.allow_response.set()
                future.result(timeout=3)
        self.assertEqual(self.events[3:], ['正在接收 API 响应体','正在处理生成图片','正在保存图片'])
        self.assertEqual(len(self.calls), 1)

    def test_http_proxy_real_request(self):
        # The local server acts as an HTTP forward proxy and replies itself.
        with running(self.server()) as port:
            self.generate(self.service(80, f'http://127.0.0.1:{port}'))
        self.assertEqual(self.events[:3], ['正在建立 API 连接','正在发送生图请求','等待服务商响应'])
        self.assertTrue(self.calls[0].startswith('http://'))

    def test_socks_proxy_real_request(self):
        # A minimal local SOCKS5 tunnel, with the target fixed to loopback.
        with running(self.server()) as target_port:
            class SocksHandler(socketserver.BaseRequestHandler):
                def handle(self):
                    sock = self.request
                    reader = sock.makefile('rb', buffering=0)
                    def read_exact(n):
                        data = b''
                        while len(data)<n:
                            chunk=reader.read(n-len(data))
                            if not chunk: raise EOFError()
                            data+=chunk
                        return data
                    head=read_exact(2); read_exact(head[1]); sock.sendall(b'\x05\x00')
                    head=read_exact(4)
                    if head[3]==1: read_exact(4)
                    elif head[3]==3: read_exact(read_exact(1)[0])
                    elif head[3]==4: read_exact(16)
                    read_exact(2)
                    with socket.create_connection(('127.0.0.1', target_port), timeout=2) as upstream:
                        sock.sendall(b'\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00')
                        def relay():
                            try:
                                while data:=sock.recv(65536): upstream.sendall(data)
                            except OSError: pass
                        t=threading.Thread(target=relay,daemon=True); t.start()
                        try:
                            while data:=upstream.recv(65536): sock.sendall(data)
                        except OSError: pass
            with running(socketserver.ThreadingTCPServer(('127.0.0.1',0),SocksHandler)) as proxy_port:
                self.generate(self.service(target_port,f'socks5h://127.0.0.1:{proxy_port}'))
        self.assertEqual(self.events[:3], ['正在建立 API 连接','正在发送生图请求','等待服务商响应'])
        self.assertEqual(len(self.calls),1)

    def test_timeout_after_request_sent_is_distinguished(self):
        self.delay=.35
        with running(self.server()) as port:
            service=self.service(port); service['timeout_seconds']=.1
            with self.assertRaisesRegex(providers.ImageProviderError,'本地请求写入完成'):
                self.generate(service)
        self.assertEqual(self.events[-1], '等待服务商响应')
        self.assertEqual(len(self.calls),1)

    def test_connection_failure_does_not_claim_request_sent(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
            with self.assertRaisesRegex(providers.ImageProviderError,'网络连接异常|连接建立超时'):
                self.generate(self.service(port))
        self.assertEqual(self.events,['正在建立 API 连接'])

    def test_status_db_failure_does_not_interrupt_request(self):
        def bad_status(value):
            self.events.append(value)
            raise sqlite3.OperationalError('locked')
        with running(self.server()) as port:
            self.generate(self.service(port), bad_status)
        self.assertEqual(len(self.calls),1)
        self.assertIn('等待服务商响应',self.events)

    def test_redirect_does_not_replay_generation_post(self):
        self.redirect=True
        with running(self.server()) as port:
            with self.assertRaisesRegex(providers.ImageProviderError, "HTTP 307: redirect refused"):
                self.generate(self.service(port))
        self.assertEqual(len(self.calls),1)
