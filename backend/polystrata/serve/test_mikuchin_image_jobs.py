"""Detached desktop image queue and indexed on-demand 4x gallery tests.

Run with: python -m serve.test_mikuchin_image_jobs
"""
import io
import sqlite3
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image

from serve import gallery, image_jobs
from serve.session_v1 import SessionV1


def png(size):
    buffer = io.BytesIO()
    Image.new("RGB", size, (10, 80, 140)).save(buffer, "PNG")
    return buffer.getvalue()


class DesktopJobsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root / "generated-images").mkdir()
        # This suite only checks newly indexed gallery files, not history imports.
        with sqlite3.connect(root / "gallery-index.sqlite3") as db:
            db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)")
            db.execute("INSERT INTO meta VALUES ('history_backfill_v1', 'test')")
        db.close()
        self.svc = SimpleNamespace(
            session_v1=SimpleNamespace(root=root),
            images=SimpleNamespace(cfg={"upscaler": {"enabled": True, "max_output_side": 6144}}),
            image_profiles={})
        self.original_id = "a" * 32
        (root / "generated-images" / (self.original_id + ".png")).write_bytes(png((12, 8)))
        gallery.register(self.svc, self.original_id, model="Test", prompt="hello")

    def _wait(self, ident):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = image_jobs.snapshot(self.svc, ident)
            if status["state"] not in ("queued", "working"):
                return status
            time.sleep(.025)
        self.fail("detached job did not complete")

    def test_detached_upscale_pair_and_result_recovery(self):
        @contextmanager
        def gpu_turn(*_args, **_kwargs):
            yield "keep"
        with mock.patch.object(image_jobs.images_api, "gpu_turn", gpu_turn), \
                mock.patch("serve.upscale._upscale_one", return_value=(png((48, 32)), .02)):
            submitted = image_jobs.submit(self.svc, {"kind": "upscale", "image_id": self.original_id})
            self.assertEqual(submitted["state"], "queued")
            result = self._wait(submitted["id"])
        self.assertEqual(result["state"], "done", result)
        self.assertEqual(result["result"]["original_id"], self.original_id)
        self.assertNotEqual(result["result"]["upscaled_id"], self.original_id)
        self.assertEqual(gallery.listing(self.svc)["total"], 1)
        artwork = gallery.detail(self.svc, self.original_id)
        self.assertEqual(artwork["variants"]["upscaled"], result["result"]["upscaled_id"])
        self.assertEqual(artwork["variants"]["original"], self.original_id)
        self.assertEqual(image_jobs.snapshot(self.svc)["jobs"][0]["state"], "done")
        self.assertTrue((self.svc.session_v1.root / "generated-images" /
                         (result["result"]["upscaled_id"] + ".png")).is_file())
        with self.assertRaises(ValueError):
            image_jobs.submit(self.svc, {"kind": "upscale", "image_id": self.original_id})

    def test_generation_submission_returns_before_work_finishes(self):
        def fake_generate(_svc, _request, _id):
            time.sleep(.12)
            return {"image_ids": [self.original_id]}
        with mock.patch.object(image_jobs, "_generate", side_effect=fake_generate):
            begun = time.monotonic()
            job = image_jobs.submit(self.svc, {"kind": "generate", "request": {"prompt": "a cat"}})
            self.assertLess(time.monotonic() - begun, .10)
            self.assertEqual(self._wait(job["id"])["state"], "done")

    def test_interrupted_service_job_becomes_interrupted_not_fake_running(self):
        path = self.svc.session_v1.root / "image-jobs.sqlite3"
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY,kind TEXT,source_id TEXT,"
                       "state TEXT,phase TEXT,result TEXT,error TEXT,created REAL,updated REAL)")
            db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)",
                       ("img-" + "b"*24, "generate", "", "working", "running", "{}", "", 1, 1))
        db.close()
        self.assertEqual(image_jobs.snapshot(self.svc, "img-" + "b"*24)["state"], "interrupted")


class DetachedChatRecoveryTest(unittest.TestCase):
    def test_browser_closes_and_later_stale_save_does_not_erase_image(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionV1(directory)
            session = "c" * 32
            store.store_web(session, [{"role": "user", "text": "Please draw a cat"}])
            svc = SimpleNamespace(session_v1=store, image_profiles={}, images=None)
            hub = SimpleNamespace(delivery_session_id=session)

            def execute(_name, _arguments):
                time.sleep(.18)
                return {"ok": True, "image_file": "e" * 32 + ".png",
                        "image_prompt": "a cat", "text": "Generated a cat"}
            hub._execute_image = execute
            hub.visual_followup = lambda *_args: iter([
                ("event", SimpleNamespace(kind="content", text="Look at this cat!"))])

            job = image_jobs.submit_chat(svc, hub, {"prompt": "a cat"}, "tool-call-xyz")
            self.assertIn(job["state"], ("queued", "working"))
            # A closed browser never saved the streamed assistant/tool result.
            self.assertTrue(any(m.get("_image_job_recovery") == job["id"]
                                for m in store.get(session)["web_messages"]))
            final = self._wait_chat(svc, job["id"])
            self.assertEqual(final["state"], "done", final)
            self.assertEqual(final["result"]["reply_text"], "Look at this cat!")
            saved = store.get(session)["web_messages"]
            tool = saved[-1]["tools"][0]
            self.assertEqual(tool["image_file"], "e" * 32 + ".png")
            self.assertEqual(saved[-1]["text"], "Look at this cat!")
            # Reconnecting client sends its old browser-only snapshot.
            store.store_web(session, [{"role": "user", "text": "Please draw a cat"}])
            stale_reconciled = store.get(session)["web_messages"]
            self.assertEqual(stale_reconciled[-1]["tools"][0]["image_file"], "e" * 32 + ".png")
            # If real stream tool content arrived later, it replaces the placeholder.
            real = [{"role": "user", "text": "Please draw a cat"},
                    {"role": "assistant", "text": "已提交桌面端后台生图任务。",
                     "tools": [{"id": "tool-call-xyz", "name": "polystrata__generate_image",
                                "round": 1, "state": "running", "image_job_id": job["id"]}]}]
            store.store_web(session, real)
            merged = store.get(session)["web_messages"]
            self.assertEqual(len(merged), 2)
            self.assertEqual(merged[1]["text"], "Look at this cat!")
            self.assertEqual(merged[1]["tools"][0]["state"], "done")

    @staticmethod
    def _wait_chat(svc, job_id):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            item = image_jobs.snapshot(svc, job_id)
            if item["state"] not in ("queued", "working"):
                return item
            time.sleep(.03)
        raise AssertionError("detached chat job exceeded test deadline")


if __name__ == "__main__":
    unittest.main()
