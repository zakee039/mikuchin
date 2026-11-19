"""Transport and concurrency regression tests. No real HTTP or paid image requests.

Run: python -m serve.test_mikuchin_image_api_transport
"""
from __future__ import annotations

import base64
import io
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import requests
from PIL import Image

from serve import image_api_services as api


def png(rgb=(20, 30, 40)):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), rgb).save(buffer, format="PNG")
    return buffer.getvalue()


class Reply:
    def __init__(self, chunks, status=200):
        self.chunks = chunks
        self.status_code = status
        self.ok = status < 400
        self.reason = "test"
        self.closed = False

    def iter_content(self, chunk_size=65536):
        for chunk in self.chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    def close(self):
        self.closed = True


class TransportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.svc = SimpleNamespace(session_v1=SimpleNamespace(root=Path(self.temp.name)))
        self.service = {
            "id": "api-test1234", "api_key": "NEVER_LOG_THIS_SECRET", "proxy": False,
            "proxy_url": "", "base_url": "https://example.org/v1", "model": "test-image",
            "reference_mode": "none", "sizes": "square", "negative": False,
            "seed": False, "steps": False, "timeout_seconds": 1200,
            "connect_timeout_seconds": 15,
        }
        self.patched_service = mock.patch.object(api, "get", return_value=self.service)
        self.patched_service.start()
        self.addCleanup(self.patched_service.stop)

    def generate(self, prompt="test", *, diagnostic_id=None, **kwargs):
        return api.generate(self.svc, {"prompt": prompt, "size": "1024x1024"},
                            diagnostic_id=diagnostic_id or "img-" + "a"*24, **kwargs)

    def _with_session(self, make_session):
        @contextmanager
        def factory(_service):
            session = make_session()
            yield session
        return mock.patch.object(api, "_session", factory)

    def test_connect_timeout_reports_short_connection_stage_not_1200_seconds_wait(self):
        class Session:
            def post(self, _url, **_kwargs):
                raise requests.ConnectTimeout("test connect failure")
        with self._with_session(Session), self.assertRaises(api.ImageProviderError) as error:
            self.generate()
        self.assertIn("连接建立超时", str(error.exception))
        self.assertIn("连接上限 15s", str(error.exception))
        self.assertNotIn("1200s per socket read", str(error.exception))

    def test_tls_handshake_can_raise_read_timeout_before_response_headers(self):
        class Session:
            def post(self, _url, **_kwargs):
                raise requests.ReadTimeout("test TLS timeout")
        with self._with_session(Session), self.assertRaises(api.ImageProviderError) as error:
            self.generate()
        message = str(error.exception)
        self.assertIn("阶段 request_headers", message)
        self.assertIn("连接上限 15s", message)
        self.assertIn("读取上限 1200s", message)
        self.assertIn("不能仅凭 requests.ReadTimeout", message)

    def test_truncated_response_identifies_body_phase_and_bytes(self):
        reply = Reply([b'{"data":', requests.ConnectionError(
            "Connection broken: IncompleteRead(8 bytes read, 100 more expected)")])
        class Session:
            def post(self, _url, **_kwargs):
                return reply
        with self._with_session(Session), self.assertRaises(api.ImageProviderError) as error:
            self.generate()
        self.assertIn("响应体不完整", str(error.exception))
        self.assertIn("阶段 response_body", str(error.exception))
        self.assertIn("已接收 8 字节", str(error.exception))
        self.assertTrue(reply.closed)

    def test_valid_streaming_json_and_independent_timeouts(self):
        value = png()
        raw = json.dumps({"data": [{"b64_json": base64.b64encode(value).decode()}]}).encode()
        reply = Reply([raw[:15], raw[15:]])
        observed = []
        class Session:
            def post(self, _url, **kwargs):
                observed.append(kwargs)
                return reply
        self.service["connect_timeout_seconds"] = 30
        self.service["timeout_seconds"] = 700
        with self._with_session(Session):
            result = self.generate()
        self.assertEqual(observed[0]["timeout"], (30, 700))
        self.assertIs(observed[0]["stream"], True)
        self.assertTrue(reply.closed)
        self.assertEqual(result["strata"]["provider"], "api")
        self.assertEqual((Path(self.temp.name)/"generated-images"/
                          result["strata"]["image_file"]).read_bytes(),
                         base64.b64decode(result["data"][0]["b64_json"]))

    def test_upstream_http_error_keeps_status_and_does_not_retry(self):
        response = Reply([b'{"error":{"message":"rate limited"}}'], 429)
        calls = []
        class Session:
            def post(self, _url, **_kwargs):
                calls.append(1)
                return response
        with self._with_session(Session), self.assertRaises(api.ImageProviderError) as error:
            self.generate()
        self.assertEqual(len(calls), 1)
        self.assertIn("HTTP 429", str(error.exception))
        self.assertTrue(response.closed)

    def test_parallel_requests_have_separate_sessions_prompts_and_output_files(self):
        barrier = threading.Barrier(4)
        sessions = []
        lock = threading.Lock()
        colors = {"red": (220, 0, 0), "green": (0, 220, 0),
                  "blue": (0, 0, 220), "purple": (160, 0, 160)}

        class Session:
            def post(self, _url, **kwargs):
                name = kwargs["json"]["prompt"]
                barrier.wait(timeout=5)
                body = json.dumps({"data": [{"b64_json": base64.b64encode(
                    png(colors[name])).decode()}]}).encode()
                return Reply([body])

        @contextmanager
        def factory(_service):
            session = Session()
            with lock:
                sessions.append(session)
            yield session

        diagnostic_ids = {name:"img-" + f"{i+1:024x}" for i,name in enumerate(colors)}
        traces = []
        original_trace = api._network_trace
        def capture_trace(job_id, route, phase, elapsed, **kwargs):
            with lock:
                traces.append((job_id,phase))
            return original_trace(job_id,route,phase,elapsed,**kwargs)
        with mock.patch.object(api, "_session", factory), \
             mock.patch.object(api, "_network_trace", side_effect=capture_trace):
            with ThreadPoolExecutor(max_workers=4) as executor:
                output = list(executor.map(lambda name:
                    (name, self.generate(name,diagnostic_id=diagnostic_ids[name])),colors))
        self.assertEqual(len(set(map(id, sessions))), 4)
        for ident in diagnostic_ids.values():
            phases = {phase for job_id,phase in traces if job_id == ident}
            self.assertEqual(phases,{"request_start","response_headers","response_body_complete"})
        filenames = [item[1]["strata"]["image_file"] for item in output]
        self.assertEqual(len(set(filenames)), 4)
        for name, response in output:
            file_path = Path(self.temp.name) / "generated-images" / response["strata"]["image_file"]
            with Image.open(file_path) as picture:
                self.assertEqual(picture.convert("RGB").getpixel((0, 0)), colors[name])


if __name__ == "__main__":
    unittest.main()
