"""Native image jobs: no network or paid generation is ever performed."""
import base64
import io
import sqlite3
import tempfile
import threading
import time
import unittest
import json
from unittest import mock
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
        self.jobs = ImageJobStore(self.root, embedded_worker=True)
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

    def test_queue_and_worker_claim_do_not_start_execution_clock(self):
        # The browser may submit before an older paid job releases a slot.
        # Neither HTTP submission nor the Worker claiming it counts as model time.
        store=ImageJobStore(self.root)
        with mock.patch.object(store,"worker_healthy",return_value=True):
            created=store.submit({"request":self.request,
                "client_started_at":time.time()-180})
        self.assertIsNone(created["started_at"])
        self.assertIsNone(created["elapsed_s"])
        claimed=store.take_pending()
        self.assertEqual(claimed[0],created["id"])
        self.assertIsNone(store.listing(created["id"])["started_at"])
        store._provider=self.jobs._provider
        store.execute_claimed(*claimed)
        finished=store.listing(created["id"])
        self.assertEqual(finished["state"],"success")
        self.assertIsNotNone(finished["started_at"])
        self.assertLess(time.time()-finished["started_at"],5)
        self.assertLess(finished["elapsed_s"],5)
        self.assertEqual(len(self.calls),1)

    def test_gallery_manual_upscale_is_single_offline_job_and_keeps_original(self):
        created=self.jobs.submit({"request":self.request})
        self.jobs.queue.join()
        self.assertEqual(self.jobs.listing(created["id"])["state"],"success")
        def fake_upscale(_store,raw,*,on_status=None):
            if on_status: on_status("Real-ESRGAN 4x upscale")
            image=Image.open(io.BytesIO(raw))
            out=io.BytesIO()
            image.resize((image.width*4,image.height*4)).save(out,"PNG")
            return out.getvalue()
        with (mock.patch("backend.gateway.image_jobs.local_images.upscaler_ready",return_value=True),
              mock.patch("backend.gateway.image_jobs.local_images._settings",
                         return_value={"upscaler":{"max_output_side":3072}}),
              mock.patch("backend.gateway.image_jobs.local_images.upscale",
                         side_effect=fake_upscale) as upscale):
            submitted=self.jobs.submit_upscale("a"*32)
            self.jobs.queue.join()
            repeated=self.jobs.submit_upscale("a"*32)
            self.assertTrue(repeated["already_submitted"])
            self.assertEqual(repeated["id"],submitted["id"])
            upscale.assert_called_once()
        record=self.jobs.listing(submitted["id"])
        self.assertEqual(record["kind"],"upscale")
        self.assertEqual(record["state"],"success")
        self.assertIsNotNone(record["started_at"])
        self.assertEqual(record["source_id"],"a"*32)
        self.assertEqual(self.jobs.listing(kind="upscale")["jobs"][0]["id"],submitted["id"])
        self.assertEqual(len(self.calls),1,"4x must not call the image provider again")
        group=gallery.detail(self.jobs,"a"*32)
        self.assertEqual(group["variants"]["original"],"a"*32)
        self.assertEqual(group["variant_count"],2)
        self.assertEqual(group["width"],80)
        self.assertEqual(group["height"],48)

    def test_gallery_manual_upscale_requires_config_and_size_limit(self):
        self.jobs.submit({"request":self.request})
        self.jobs.queue.join()
        with self.assertRaises(ValueError):
            self.jobs.submit_upscale("../bad")
        with mock.patch("backend.gateway.image_jobs.local_images.upscaler_ready",return_value=False):
            with self.assertRaisesRegex(ValueError,"尚未配置"):
                self.jobs.submit_upscale("a"*32)
        with (mock.patch("backend.gateway.image_jobs.local_images.upscaler_ready",return_value=True),
              mock.patch("backend.gateway.image_jobs.local_images._settings",
                         return_value={"upscaler":{"max_output_side":40}})):
            with self.assertRaisesRegex(ValueError,"输出尺寸"):
                self.jobs.submit_upscale("a"*32)
        self.assertEqual(self.jobs.listing(kind="upscale")["jobs"],[])
        self.assertEqual(len(self.calls),1)

    def test_chat_image_idempotency_survives_restart_without_paid_replay(self):
        """A lost HTTP response cannot create a second chargeable request."""
        session="a"*32
        request_id="b"*32
        # Disable the embedded worker: this is a pure SQLite/protocol test.
        store=ImageJobStore(self.root)
        with mock.patch.object(store,"worker_healthy",return_value=True):
            first=store.chat_submit(session,request_id,self.request)
            retry=store.chat_submit(session,request_id,{**self.request,
                                                       "prompt":"DIFFERENT PROMPT"})
        self.assertFalse(first["already_submitted"])
        self.assertTrue(retry["already_submitted"])
        self.assertEqual(first["id"],retry["id"])
        self.assertEqual(retry["request"]["prompt"],self.request["prompt"])
        self.assertEqual(len(store.listing(session_id=session)["jobs"]),1)
        self.assertEqual(store.listing(session_id="c"*32)["jobs"],[])
        self.assertEqual(self.calls,[])
        reopened=ImageJobStore(self.root)
        reopened.fail_uncertain_on_worker_restart()
        again=reopened.chat_submit(session,request_id,self.request)
        self.assertTrue(again["already_submitted"])
        self.assertEqual(again["id"],first["id"])
        self.assertEqual(again["state"],"failed")
        self.assertEqual(self.calls,[])

    def test_chat_image_success_is_indexed_as_chat_and_linked_to_session(self):
        session="1"*32
        submitted=self.jobs.chat_submit(session,"2"*32,self.request)
        self.jobs.queue.join()
        job=self.jobs.listing(submitted["id"],session_id=session)
        self.assertEqual(job["state"],"success")
        self.assertEqual(len(self.calls),1)
        images=gallery.listing(self.jobs,source="chat")
        entries=images["items"]
        record=next(x for x in entries if x["id"]=="a"*32)
        self.assertEqual(record["source"],"chat")
        self.assertEqual(record["session_id"],session)
        self.assertEqual(self.jobs.listing(session_id="3"*32)["jobs"],[])

    def test_chat_edit_uses_only_last_successful_same_session_image(self):
        first=self.jobs.chat_submit("1"*32,"2"*32,self.request)
        self.jobs.queue.join()
        with self.assertRaisesRegex(ValueError,"尚无可编辑"):
            self.jobs.chat_submit("3"*32,"4"*32,{**self.request,"prompt":"Edit eyes"},
                                  edit_previous=True)
        edited=self.jobs.chat_submit("1"*32,"5"*32,{**self.request,"prompt":"Edit eyes"},
                                    edit_previous=True)
        self.assertEqual(edited["source_id"],first["id"])
        self.assertEqual(len(edited["request"]["strata_reference_assets"]),1)
        image_id=edited["request"]["strata_reference_assets"][0]["id"]
        self.assertEqual(self.jobs.reference_bytes(image_id)[0],image_bytes())
        self.jobs.queue.join()
        self.assertEqual(self.jobs.listing(edited["id"])["state"],"success")
        self.assertTrue(self.jobs.listing(edited["id"])["result"]["edited_previous"])
        again=self.jobs.chat_submit("1"*32,"5"*32,self.request,edit_previous=False)
        self.assertTrue(again["already_submitted"])
        self.assertEqual(again["id"],edited["id"])
        with self.assertRaisesRegex(ValueError,"server-side chat image"):
            self.jobs.chat_submit("1"*32,"6"*32,{
                **self.request,"strata_reference_assets":[{"id":image_id}]},
                edit_previous=True)
        with self.assertRaisesRegex(ValueError,"boolean"):
            self.jobs.chat_submit("1"*32,"7"*32,self.request,edit_previous="true")

    def test_chat_edit_deleted_previous_image_fails_without_submitting(self):
        first=self.jobs.chat_submit("1"*32,"2"*32,self.request)
        self.jobs.queue.join()
        (self.root/"generated-images"/("a"*32+".png")).unlink()
        with self.assertRaisesRegex(ValueError,"已删除或不可读取"):
            self.jobs.chat_submit("1"*32,"3"*32,{**self.request,"prompt":"edit"},
                                  edit_previous=True)
        self.assertEqual(len(self.jobs.listing(session_id="1"*32)["jobs"]),1)
        self.assertEqual(len(self.calls),1)

    def test_chat_cancel_only_before_worker_claim_and_no_resubmit(self):
        store=ImageJobStore(self.root)
        with mock.patch.object(store,"worker_healthy",return_value=True):
            first=store.chat_submit("a"*32,"d"*32,self.request)
        canceled=store.chat_cancel("a"*32,"d"*32)
        self.assertEqual(canceled["state"],"failed")
        self.assertIn("取消",canceled["phase"])
        with self.assertRaises(ValueError):
            store.chat_cancel("a"*32,"d"*32)
        again=store.chat_submit("a"*32,"d"*32,self.request)
        self.assertTrue(again["already_submitted"])
        self.assertEqual(again["id"],first["id"])
        self.assertEqual(again["state"],"failed")
        with mock.patch.object(store,"worker_healthy",return_value=True):
            second=store.chat_submit("a"*32,"e"*32,self.request)
        with store._db() as db:
            db.execute("UPDATE jobs SET phase='准备请求提供商' WHERE id=?",
                       (second["id"],))
        with self.assertRaisesRegex(ValueError,"无法撤回"):
            store.chat_cancel("a"*32,"e"*32)
        with self.assertRaises(ValueError):
            store.chat_submit("../invalid", "f"*32, self.request)
        self.assertEqual(self.calls,[])

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
        reopened.fail_uncertain_on_worker_restart()
        self.assertEqual(reopened.listing(draft["id"])["state"],"failed")
        self.assertIn("可能已经计费",reopened.listing(draft["id"])["error"])
        self.assertEqual(self.calls,[])
        self.assertIsNone(reopened.queue)

    def test_gallery_index_error_does_not_mislabel_a_paid_success_as_failed(self):
        with mock.patch.object(gallery,"register",side_effect=OSError("gallery unavailable")):
            task=self.jobs.submit({"request":self.request})
            self.jobs.queue.join()
        record=self.jobs.listing(task["id"])
        self.assertEqual(record["state"],"success")
        self.assertIn("gallery_warning",record["result"])
        self.assertEqual(record["result"]["gallery_error_type"],"OSError")
        self.assertTrue((self.root/"generated-images"/("a"*32+".png")).is_file())

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
