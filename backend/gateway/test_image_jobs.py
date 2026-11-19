"""Native image jobs: no network or paid generation is ever performed."""
import base64
import io
import sqlite3
import tempfile
import threading
import time
import unittest
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

from backend.gateway.image_jobs import ImageJobStore
from backend.gateway import image_providers
from backend.gateway import gallery


def image_bytes():
    out = io.BytesIO()
    Image.new("RGB", (20, 12), "white").save(out, "PNG")
    return out.getvalue()


class ImageTaskTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.jobs = ImageJobStore(self.root)
        self.service = image_providers.save_service(self.jobs, {
            "name": "Offline test profile", "base_url": "http://127.0.0.1:19999/v1",
            "model": "fake-image", "api_key": "LOCAL_TEST_SECRET", "sizes": "standard",
            "reference_mode": "multi",
        })
        self.profile = self.service["id"]
        self.request = {"prompt": "Draw a square", "size": "1536x1536",
                        "strata_image_profile": self.profile, "strata_upscale": "off",
                        "strata_reference_assets": []}
        self.calls = []

        def fake_provider(svc, request, *, on_status, diagnostic_id, **_kwargs):
            self.calls.append((diagnostic_id, request))
            on_status("测试生成中")
            folder = self.root / "generated-images"
            folder.mkdir(exist_ok=True)
            name = "a" * 32 + ".png"
            (folder / name).write_bytes(image_bytes())
            return {"model": "fake-image", "size": request["size"],
                    "strata": {"image_file": name, "seconds": .01}}
        self.jobs._provider = fake_provider

    def tearDown(self):
        self.jobs.queue.join()
        self.temp.cleanup()

    def test_draft_never_calls_a_paid_provider(self):
        draft = self.jobs.submit({"action": "draft", "request": self.request})
        self.assertEqual(draft["state"], "draft")
        self.assertEqual(self.calls, [])
        saved = self.jobs.submit({"action": "save_draft", "id": draft["id"],
                                  "request": {**self.request,"prompt":"Updated offline"}})
        self.assertEqual(saved["id"], draft["id"])
        self.assertEqual(saved["request"]["prompt"], "Updated offline")
        self.assertEqual(self.calls, [])
        copy = self.jobs.submit({"action": "draft", "copy_id": draft["id"]})
        self.assertNotEqual(copy["id"], draft["id"])
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.jobs.listing()["jobs"]), 2)

    def test_activation_runs_only_once_and_keeps_success_record(self):
        draft = self.jobs.submit({"action":"draft","request":self.request})
        active = self.jobs.submit({"action":"activate","id":draft["id"]})
        self.assertEqual(active["id"],draft["id"])
        with self.assertRaises(ValueError):
            self.jobs.submit({"action":"activate","id":draft["id"]})
        self.jobs.queue.join()
        done=self.jobs.listing(draft["id"])
        self.assertEqual(done["state"],"success")
        self.assertEqual(done["result"]["image_ids"],["a"*32])
        self.assertEqual(len(self.calls),1)
        newer=self.jobs.submit({"action":"retry","id":draft["id"]})
        self.jobs.queue.join()
        self.assertEqual(self.jobs.listing(draft["id"])["state"],"success")
        self.assertNotIn("deleted_original_id",newer)
        self.assertEqual(self.jobs.listing(newer["id"])["state"],"success")

    def test_failed_retry_atomically_replaces_old_record_and_preserves_reference(self):
        raw=image_bytes()
        self.jobs._provider = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fake failure"))
        source={**self.request,"strata_reference_assets":[{
            "name":"example.png","data_url":"data:image/png;base64,"+base64.b64encode(raw).decode()}]}
        draft=self.jobs.submit({"action":"draft","request":source})
        ident=draft["request"]["strata_reference_assets"][0]["id"]
        self.assertEqual(self.jobs.reference_bytes(ident)[0],raw)
        self.jobs.submit({"action":"activate","id":draft["id"]})
        self.jobs.queue.join()
        self.assertEqual(self.jobs.listing(draft["id"])["state"],"failed")
        # A bad provider configuration must not destroy the failed source.
        with self.assertRaises(ValueError):
            self.jobs._prepare({**self.request,"steps":-1})
        self.assertEqual(self.jobs.listing(draft["id"])["state"],"failed")

        def accept(svc,request,**_kwargs):
            self.assertEqual(len(request["strata_reference_images"]),1)
            self.assertTrue(request["strata_reference_images"][0].startswith("data:image/png;base64,"))
            folder=self.root/"generated-images"
            folder.mkdir(exist_ok=True)
            (folder/("b"*32+".png")).write_bytes(raw)
            return {"strata":{"image_file":"b"*32+".png"},"size":"1536x1536"}
        self.jobs._provider=accept
        updated=self.jobs.submit({"action":"retry","id":draft["id"]})
        self.assertEqual(updated["deleted_original_id"],draft["id"])
        self.assertEqual(self.jobs.listing(draft["id"])["state"],"unknown")
        self.assertEqual(self.jobs.reference_bytes(ident)[0],raw)
        self.jobs.queue.join()
        self.assertEqual(self.jobs.listing(updated["id"])["state"],"success")

    def test_restart_marks_uncertain_running_job_failed_without_replaying(self):
        draft=self.jobs.submit({"action":"draft","request":self.request})
        with self.jobs._db() as db:
            db.execute("UPDATE jobs SET state='running' WHERE id=?",(draft["id"],))
        reopened=ImageJobStore(self.root)
        self.assertEqual(reopened.listing(draft["id"])["state"],"failed")
        self.assertIn("可能已经扣费",reopened.listing(draft["id"])["error"])
        self.assertEqual(self.calls,[])
        self.assertEqual(reopened.queue.qsize(),0)

    def test_validation_and_credential_privacy(self):
        self.assertNotIn("LOCAL_TEST_SECRET",str(image_providers.list_services(self.jobs)))
        self.assertTrue(self.service["has_key"])
        for change in ({"size":"1536x1536","strata_image_profile":"unknown"},
                       {"size":"1232x1024"}, {"strata_upscale":"4x"},
                       {"seed":True}, {"strata_reference_assets":[{"id":"bad"}]}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.jobs.submit({"action":"draft","request":{**self.request,**change}}) if \
                    change.keys() & {"strata_upscale","seed","strata_reference_assets"} else \
                    self.jobs.submit({"request":{**self.request,**change}})
        self.assertEqual(self.calls,[])

    def test_real_http_adapter_against_local_fake_provider_and_gallery(self):
        """Exercises actual HTTP and PNG parsing; never contacts a public provider."""
        png=image_bytes()
        received=[]
        class FakeImageAPI(BaseHTTPRequestHandler):
            def log_message(self,*_args): pass
            def do_POST(self):
                size=int(self.headers["Content-Length"])
                received.append((self.path,self.headers.get("Authorization"),
                                 json.loads(self.rfile.read(size))))
                body=json.dumps({"data":[{"b64_json":base64.b64encode(png).decode()}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type","application/json")
                self.send_header("Content-Length",str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        server=ThreadingHTTPServer(("127.0.0.1",0),FakeImageAPI)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            live=image_providers.save_service(self.jobs, {
                "name":"Private fake local image API","model":"fake-image",
                "base_url":f"http://127.0.0.1:{server.server_address[1]}/v1",
                "api_key":"OFFLINE_ONLY_KEY","sizes":"standard"})
            self.jobs._provider=image_providers.generate
            created=self.jobs.submit({"request":{**self.request,
                                  "strata_image_profile":live["id"]}})
            self.jobs.queue.join()
            completed=self.jobs.listing(created["id"])
            self.assertEqual(completed["state"],"success",completed["error"])
            self.assertEqual(len(received),1)
            endpoint,authorization,request=received[0]
            self.assertEqual(endpoint,"/v1/images/generations")
            self.assertEqual(authorization,"Bearer OFFLINE_ONLY_KEY")
            self.assertEqual(request["size"],"1536x1536")
            image_id=completed["result"]["image_ids"][0]
            indexed=gallery.detail(self.jobs,image_id)
            self.assertEqual(indexed["provider"],"api")
            self.assertEqual((indexed["width"],indexed["height"]),(20,12))
            self.assertTrue(gallery.thumbnail(self.jobs,image_id).startswith(b"\xff\xd8"))
            self.assertEqual(gallery.listing(self.jobs)["total"],1)
            gallery.set_nsfw(self.jobs,image_id,True)
            self.assertTrue(gallery.detail(self.jobs,image_id)["nsfw"])
            self.assertEqual(self.jobs.delete(created["id"])["deleted"],1)
            self.assertEqual(gallery.listing(self.jobs)["total"],1,
                             "deleting job metadata must not delete generated artwork")
            gallery.delete_many(self.jobs,[image_id])
            self.assertEqual(gallery.listing(self.jobs)["total"],0)
            self.assertFalse((self.root/"generated-images"/(image_id+".png")).exists())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
