"""Real subprocess boundary: fake localhost provider, no paid requests."""
from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

from backend.gateway import gallery, image_providers
from backend.gateway.image_jobs import ImageJobStore


class ExternalWorkerTests(unittest.TestCase):
    def test_separate_process_only_charges_when_explicitly_submitted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jobs = ImageJobStore(root / "images")
            buf = io.BytesIO()
            Image.new("RGB", (32, 24), "white").save(buf, "PNG")
            png = buf.getvalue()
            calls = []

            class FakeProvider(BaseHTTPRequestHandler):
                def log_message(self, *_args): pass

                def do_POST(self):
                    payload=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    calls.append((self.headers["Authorization"],payload))
                    body=json.dumps({"data":[{"b64_json":base64.b64encode(png).decode()}]}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeProvider)
            server = threading.Thread(target=fake.serve_forever, daemon=True)
            server.start()
            worker = None
            duplicate = None
            try:
                service = image_providers.save_service(jobs,{
                    "name":"Isolated subprocess image API",
                    "base_url":f"http://127.0.0.1:{fake.server_address[1]}/v1",
                    "model":"test-image","api_key":"SUBPROCESS_TEST_SECRET",
                    "sizes":"standard"})
                request={"prompt":"One local call","size":"1536x1536",
                         "strata_image_profile":service["id"],"strata_upscale":"off"}
                draft=jobs.submit({"action":"draft","request":request})
                self.assertEqual(len(calls),0)
                with self.assertRaisesRegex(ValueError,"Worker"):
                    jobs.submit({"action":"activate","id":draft["id"]})

                worker=subprocess.Popen([
                    sys.executable,"-B","-m","backend.gateway.worker","--data-dir",str(root)],
                    cwd=str(Path(__file__).resolve().parents[2]),
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                deadline=time.monotonic()+14
                while not jobs.worker_healthy() and time.monotonic()<deadline:
                    self.assertIsNone(worker.poll(),"Worker subprocess exited during startup")
                    time.sleep(.1)
                self.assertTrue(jobs.worker_healthy(),"Worker subprocess did not heartbeat")

                # A second worker process must fail before it invalidates or
                # replays any live provider request.
                duplicate=subprocess.run([
                    sys.executable,"-B","-m","backend.gateway.worker","--data-dir",str(root)],
                    cwd=str(Path(__file__).resolve().parents[2]),
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=6)
                self.assertNotEqual(duplicate.returncode,0)

                queued=jobs.submit({"action":"activate","id":draft["id"]})
                self.assertEqual(queued["id"],draft["id"])
                deadline=time.monotonic()+18
                while jobs.listing(draft["id"])["state"]=="running" and time.monotonic()<deadline:
                    time.sleep(.15)
                completed=jobs.listing(draft["id"])
                self.assertEqual(completed["state"],"success",completed["error"])
                self.assertEqual(len(calls),1)
                self.assertEqual(calls[0][0],"Bearer SUBPROCESS_TEST_SECRET")
                self.assertEqual(calls[0][1]["size"],"1536x1536")
                self.assertEqual(len(gallery.listing(jobs)["items"]),1)
                self.assertIsNone(jobs.thread,"Gateway must never start paid worker threads")
                self.assertIsNone(jobs.queue,"Gateway must not have a local work queue")
            finally:
                if worker is not None:
                    worker.terminate()
                    try:worker.wait(timeout=6)
                    except subprocess.TimeoutExpired:
                        worker.kill();worker.wait(timeout=5)
                fake.shutdown()
                fake.server_close()
                server.join(timeout=3)


if __name__=="__main__":
    unittest.main()
