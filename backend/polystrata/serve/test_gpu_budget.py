"""Tests for the read-only WDDM local VRAM budget API and native protocol."""
import io
import http.client
import json
import queue
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

from serve.server import ByteTokenizer, MockEngine, StrataEngine, Service, serve
from serve.frontend import ChatTemplate


class NativeBudgetProtocol(unittest.TestCase):
    def make_engine(self, reply):
        e = StrataEngine.__new__(StrataEngine)
        e.info = {"budget_query": 1}
        e.proc = SimpleNamespace(stdin=io.StringIO())
        e.lines = queue.Queue()
        if reply is not None:
            e.lines.put(reply)
        return e

    def test_parses_budget_and_writes_only_readonly_command(self):
        e = self.make_engine("BUDGET supported=1 gpu_index=0 local_budget_mib=6837 local_usage_mib=1520\n")
        with patch.object(StrataEngine, "alive", return_value=True):
            result = e.budget()
        self.assertEqual(result, {"supported": True, "gpu_index": 0,
                                  "local_budget_mib": 6837, "local_usage_mib": 1520})
        self.assertEqual(e.proc.stdin.getvalue(), "BUDGET\n")

    def test_reports_unsupported_and_refuses_legacy_binary(self):
        e = self.make_engine("BUDGET supported=0\n")
        with patch.object(StrataEngine, "alive", return_value=True):
            self.assertIs(e.budget()["supported"], False)
            e.info = {}
            self.assertIs(e.budget()["supported"], False)
        self.assertEqual(e.proc.stdin.getvalue(), "BUDGET\n")

    def test_does_not_accept_unexpected_or_malformed_reply(self):
        for reply in ("VRAM reserve_mib=512\n", "BUDGET supported=1 local_budget_mib=10\n"):
            with self.subTest(reply=reply):
                e = self.make_engine(reply)
                with patch.object(StrataEngine, "alive", return_value=True), self.assertRaises(ValueError):
                    e.budget()


class BudgetService(unittest.TestCase):
    @staticmethod
    def make_service():
        svc = Service.__new__(Service)
        svc.fifo = threading.Lock()
        svc.engine = SimpleNamespace(info={"budget_query": 1}, batch=0,
                                     budget=lambda timeout: {"supported": True, "gpu_index": 0,
                                                            "local_budget_mib": 7000,
                                                            "local_usage_mib": 1800})
        svc.loaded = lambda: True
        return svc

    def test_sample_cached_for_five_seconds(self):
        svc = self.make_service()
        self.assertEqual(svc.gpu_budget()["local_budget_mib"], 7000)
        svc.engine.budget = lambda timeout: self.fail("cached reading must not re-query engine")
        self.assertEqual(svc.gpu_budget()["local_usage_mib"], 1800)

    def test_engine_restart_invalidates_cached_budget(self):
        svc = self.make_service()
        svc.engine.gen = 1
        self.assertEqual(svc.gpu_budget()["local_budget_mib"], 7000)
        svc.engine.gen = 2
        svc.engine.budget = lambda timeout: {"supported": True, "gpu_index": 0,
                                            "local_budget_mib": 6800, "local_usage_mib": 900}
        self.assertEqual(svc.gpu_budget()["local_budget_mib"], 6800)

    def test_never_waits_for_busy_inference(self):
        svc = self.make_service()
        svc.fifo.acquire()
        try:
            before = time.perf_counter()
            result = svc.gpu_budget()
            self.assertLess(time.perf_counter() - before, 0.1)
            self.assertIs(result["supported"], False)
            self.assertEqual(result["reason"], "inference is busy")
        finally:
            svc.fifo.release()

    def test_parallel_control_lock_is_not_stolen(self):
        svc = self.make_service()
        ctl = threading.Lock()
        svc.engine.ctl, svc.engine.batch = ctl, 2
        ctl.acquire()
        try:
            self.assertEqual(svc.gpu_budget()["reason"], "inference is busy")
            self.assertTrue(svc.fifo.acquire(blocking=False))
            svc.fifo.release()
        finally:
            ctl.release()
        self.assertTrue(svc.gpu_budget()["supported"])

    def test_unloaded_and_old_binary_do_not_issue_commands(self):
        svc = self.make_service()
        svc.engine.info = {}
        self.assertIs(svc.gpu_budget()["supported"], False)
        svc.engine.info = {"budget_query": 1}
        svc.loaded = lambda: False
        self.assertIs(svc.gpu_budget()["supported"], False)


class BudgetHttp(unittest.TestCase):
    def test_read_only_endpoint_is_authenticated_and_gracefully_handles_old_engine(self):
        tok = ByteTokenizer()
        eng = MockEngine(tok, "hello", max_context=1024)
        template = ChatTemplate(Path(__file__).parent / "chat_template.jinja")
        svc = Service(eng, tok, template)
        httpd = serve(svc, port=0)
        try:
            def get(headers=None):
                conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
                try:
                    conn.request("GET", "/v1/strata/gpu-budget", headers=headers or {})
                    resp = conn.getresponse()
                    return resp.status, json.loads(resp.read())
                finally:
                    conn.close()
            status, info = get()
            self.assertEqual(status, 200)
            self.assertFalse(info["supported"])
            self.assertEqual(get({"Origin": "https://foreign.example"})[0], 403)
            svc.api_key = "local-secret"
            self.assertEqual(get()[0], 401)
            self.assertEqual(get({"Authorization": "Bearer local-secret"})[0], 200)
            # Existing /v1/ policy allows authenticated cross-site SDK calls.
            self.assertEqual(get({"Authorization": "Bearer local-secret",
                                  "Origin": "https://foreign.example"})[0], 200)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
