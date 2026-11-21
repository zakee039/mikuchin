import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

try:
    from .request_monitor import RequestMonitor
except ImportError:
    from request_monitor import RequestMonitor


class RequestMonitorTest(unittest.TestCase):
    def test_only_fixed_fields_survive_and_snapshots_are_bounded(self):
        monitor = RequestMonitor()
        with self.assertRaises(ValueError):
            monitor.begin("private/tenant-42")
        token = monitor.begin("chat")
        self.assertEqual(monitor.snapshot()["active"], 1)
        monitor.finish(token, status=200, response_bytes=42)
        for _ in range(45):
            ticket = monitor.begin("messages")
            monitor.finish(ticket, status=502, outcome="upstream_error")
        data = monitor.snapshot()
        self.assertEqual(data["total"], 46)
        self.assertEqual(data["failed"], 45)
        self.assertEqual(data["active"], 0)
        self.assertEqual(data["by_kind"]["chat"], 1)
        self.assertEqual(data["by_kind"]["messages"], 45)
        self.assertLessEqual(len(data["recent"]), 30)
        self.assertEqual(data["recent"][0]["outcome"], "upstream_error")
        self.assertEqual(data["persistence"], "memory_only")
        self.assertEqual(data["token_usage"], "not_available_per_request")
        self.assertEqual(set(data["recent"][0]),
            {"kind","status","outcome","duration_ms","response_bytes","completed_at"})
        self.assertNotIn("Authorization",json.dumps(data))

    def test_threadsafe_inflight_and_no_negative_counters(self):
        monitor = RequestMonitor()
        def simulate(i):
            t=monitor.begin("chat")
            time.sleep(.0005)
            monitor.finish(t,status=200 if i % 3 else 429)
        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(simulate,range(100)))
        data=monitor.snapshot()
        self.assertEqual(data["total"],100)
        self.assertEqual(data["failed"],34)
        self.assertEqual(data["active"],0)

if __name__ == "__main__":
    unittest.main()
