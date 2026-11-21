"""Detached desktop image queue and indexed on-demand 4x gallery tests.

Run with: python -m serve.test_mikuchin_image_jobs
"""
import io
import os
import base64
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image

from serve import gallery, image_jobs, image_api_services
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
        override = mock.patch.dict(os.environ, {
            "MIKUCHIN_IMAGE_SERVICES_FILE": str(root / "test-api-services.json")})
        override.start()
        self.addCleanup(override.stop)
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
            if status["state"] not in ("queued", "working", "running"):
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
            self.assertEqual(self._wait(job["id"])["state"], "success")

    def test_generation_timer_starts_when_worker_executes_and_ignores_queue(self):
        """A second task may wait in the queue without its timer advancing."""
        entered=threading.Event()
        release=threading.Event()
        def fake_generate(svc, req, job_id):
            image_jobs._mark(svc,job_id,"调用模型",start=True)
            if req["prompt"] == "block first":
                entered.set()
                self.assertTrue(release.wait(timeout=4))
            return {"image_ids":[self.original_id]}
        with mock.patch.object(image_jobs,"_generate",side_effect=fake_generate):
            try:
                first=image_jobs.submit(self.svc,{"kind":"generate","request":{"prompt":"block first"}})
                self.assertTrue(entered.wait(3))
                queued=image_jobs.submit(self.svc,{"kind":"generate","request":{"prompt":"second"},
                    "client_started_at":time.time()-120})
                self.assertIsNone(queued["started_at"])
                self.assertIsNone(queued["elapsed_s"])
                time.sleep(.08)
                self.assertIsNone(image_jobs.snapshot(self.svc,queued["id"])["started_at"])
            finally:
                release.set()
            self.assertEqual(self._wait(first["id"])["state"],"success")
            finished=self._wait(queued["id"])
        self.assertEqual(finished["state"],"success")
        self.assertIsNotNone(finished["started_at"])
        self.assertIsNotNone(finished["finished_at"])
        self.assertLess(finished["elapsed_s"],5)
        frozen=image_jobs.snapshot(self.svc,queued["id"])
        self.assertEqual(frozen["elapsed_s"],finished["elapsed_s"])
    def test_failed_and_retried_jobs_have_independent_start_finish_timestamps(self):
        def fake_failure(svc,req,job_id):
            image_jobs._mark(svc,job_id,"调用 API",start=True)
            raise RuntimeError("upstream broke")
        def fake_success(svc,req,job_id):
            image_jobs._mark(svc,job_id,"调用 API",start=True)
            return {"image_ids":[self.original_id]}
        with mock.patch.object(image_jobs, "_generate", side_effect=fake_failure):
            failed_id = image_jobs.submit(self.svc, {"kind":"generate",
                "request":{"prompt":"try again"}})["id"]
            failed = self._wait(failed_id)
        self.assertEqual(failed["state"], "failed")
        self.assertIsNotNone(failed["started_at"])
        self.assertIsNotNone(failed["finished_at"])
        clicked = time.time() - 1.0
        with mock.patch.object(image_jobs, "_generate", side_effect=fake_success):
            retried = image_jobs.submit(self.svc, {"action":"retry", "id":failed_id,
                "client_started_at":clicked})
            done = self._wait(retried["id"])
        self.assertNotEqual(done["id"], failed_id)
        self.assertEqual(retried["deleted_original_id"], failed_id)
        self.assertGreater(done["started_at"], clicked)
        self.assertLess(done["elapsed_s"],5)
        self.assertIsNotNone(done["finished_at"])
        self.assertEqual(image_jobs.snapshot(self.svc, failed_id)["state"], "unknown")
        self.assertNotIn(failed_id, [job["id"] for job in
                          image_jobs.snapshot(self.svc,kind="generate")["jobs"]])
        with self.assertRaises(ValueError):
            image_jobs.submit(self.svc, {"action":"retry", "id":failed_id})

    def test_failed_retry_is_atomic_and_preserves_reference_assets(self):
        """Never destroy the source on invalid retry; keep all referenced bytes."""
        photo = base64.b64encode(png((12, 8))).decode("ascii")
        original = {"prompt":"image with a reference", "size":"768x768",
                    "strata_reference_assets":[{"data_url":"data:image/png;base64,"+photo,
                                               "name":"attached.png"}]}
        with mock.patch.object(image_jobs, "_generate", side_effect=RuntimeError("provider down")):
            failed_id = image_jobs.submit(self.svc,{"kind":"generate","request":original})["id"]
            failed = self._wait(failed_id)
        self.assertEqual(failed["state"], "failed")
        refs = failed["request"]["strata_reference_assets"]
        self.assertEqual(len(refs), 1)
        ref_id = refs[0]["id"]
        old_bytes = image_jobs.reference_bytes(self.svc,ref_id)[0]

        # Validation failure cannot delete the original or lose its references.
        with mock.patch.object(image_jobs, "_prepare_request", side_effect=ValueError("invalid")):
            with self.assertRaises(ValueError):
                image_jobs.submit(self.svc,{"action":"retry", "id":failed_id})
        self.assertEqual(image_jobs.snapshot(self.svc,failed_id)["state"], "failed")
        self.assertEqual(image_jobs.reference_bytes(self.svc,ref_id)[0],old_bytes)

        with mock.patch.object(image_jobs,"_generate",return_value={"image_ids":[self.original_id]}):
            retried = image_jobs.submit(self.svc,{"action":"retry","id":failed_id})
            self.assertEqual(retried["deleted_original_id"],failed_id)
            self.assertEqual(image_jobs.snapshot(self.svc,failed_id)["state"], "unknown")
            self.assertEqual(image_jobs.reference_bytes(self.svc,ref_id)[0],old_bytes)
            self.assertEqual(self._wait(retried["id"])["state"], "success")
        self.assertEqual(image_jobs.snapshot(self.svc,retried["id"])["request"]["strata_reference_assets"],refs)

    def test_old_job_does_not_fabricate_a_click_timestamp(self):
        image_jobs._initialize(self.svc)
        with image_jobs._db(self.svc) as db:
            db.execute("INSERT INTO jobs(id,kind,state,phase,created,updated) VALUES(?,?,?,?,?,?)",
                ("img-" + "a"*24, "generate", "success", "done", 123.0, 900.0))
        legacy = image_jobs.snapshot(self.svc, "img-" + "a"*24)
        self.assertIsNone(legacy["started_at"])
        self.assertIsNone(legacy["finished_at"])
        self.assertIsNone(legacy["elapsed_s"])
        self.assertTrue(legacy["legacy_timer_unknown"])

    def test_api_pool_honors_per_service_concurrency_without_blocking_local(self):
        active, peak = 0, 0
        lock = threading.Lock()
        provider = "api-abcdef0011223344"
        def fake_generate(_svc, request, _id):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                time.sleep(.20)
                return {"image_ids": [self.original_id], "model": "fake"}
            finally:
                with lock:
                    active -= 1

        with mock.patch.object(image_jobs.api_images, "get", return_value={"concurrency":2}), \
             mock.patch.object(image_jobs, "_generate", side_effect=fake_generate):
            ids = [image_jobs.submit(self.svc, {"kind":"generate",
                    "request":{"strata_image_profile":provider,
                               "prompt":f"image {i}", "size":"1024x1024"}})["id"] for i in range(4)]
            results = [self._wait(i) for i in ids]
        self.assertTrue(all(r["state"] == "success" for r in results), results)
        self.assertEqual(peak, 2, "per-service concurrency must never exceed the configured cap")
        self.assertTrue(all(r["profile_id"] == provider for r in results))
        self.assertTrue(all(r["requested_size"] == "1024x1024" for r in results))
        self.assertTrue(all(r["prompt_summary"].startswith("image ") for r in results))

    def test_twenty_api_requests_can_run_concurrently(self):
        """Regression: the old global 12-job cap made the 20 setting fake."""
        provider = "api-abcdef0011223344"
        barrier = threading.Barrier(20)
        active = peak = 0
        lock = threading.Lock()

        def fake_generate(_svc, _request, _id):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                barrier.wait(timeout=7)
                time.sleep(.02)
                return {"image_ids": [self.original_id]}
            finally:
                with lock:
                    active -= 1

        with mock.patch.object(image_jobs.api_images, "get", return_value={"concurrency":20}), \
             mock.patch.object(image_jobs, "_generate", side_effect=fake_generate):
            ids = [image_jobs.submit(self.svc, {"kind":"generate", "request":{
                "strata_image_profile":provider, "prompt":f"test image {i}"}})["id"]
                   for i in range(20)]
            results = [self._wait(i) for i in ids]
        self.assertTrue(all(r["state"] == "success" for r in results), results)
        self.assertEqual(peak, 20)

    def test_separate_api_profiles_do_not_block_each_other(self):
        """A slow provider at its limit must not stall a different provider."""
        profiles = ("api-abcdef0011223344", "api-1234567890abcdef")
        barrier = threading.Barrier(2)
        started = set()
        lock = threading.Lock()

        def fake_generate(_svc, request, _id):
            with lock:
                started.add(request["strata_image_profile"])
            barrier.wait(timeout=5)
            return {"image_ids": [self.original_id]}

        with mock.patch.object(image_jobs.api_images, "get", return_value={"concurrency":1}), \
             mock.patch.object(image_jobs, "_generate", side_effect=fake_generate):
            job_ids = [image_jobs.submit(self.svc, {"kind":"generate", "request":{
                "strata_image_profile":profile, "prompt":"isolated task"}})["id"]
                for profile in profiles]
            results = [self._wait(ident) for ident in job_ids]
        self.assertEqual(started, set(profiles))
        self.assertTrue(all(item["state"] == "success" for item in results), results)

    def test_studio_only_listing_and_safe_record_cleanup(self):
        """Filtering must not let chat/4x records evict 40 studio rows."""
        image_jobs._initialize(self.svc)
        now = time.time()
        entries = [
            ("img-" + "b"*24, "generate", "success"),
            ("img-" + "c"*24, "generate", "failed"),
            ("img-" + "d"*24, "chat", "done"),
            ("img-" + "e"*24, "upscale", "done"),
            ("img-" + "f"*24, "generate", "running"),
        ]
        with image_jobs._db(self.svc) as db:
            db.executemany("INSERT INTO jobs(id,kind,state,phase,created,updated) "
                           "VALUES(?,?,?,?,?,?)",
                           [(ident,kind,state,state,now,now) for ident,kind,state in entries])
        self.assertEqual(len(image_jobs.snapshot(self.svc,kind="generate")["jobs"]), 3)
        self.assertEqual(image_jobs.delete_records(self.svc,job_id=entries[4][0])["deleted"],0)
        self.assertEqual(image_jobs.delete_records(self.svc,job_id=entries[1][0])["deleted"],1)
        self.assertEqual(image_jobs.delete_records(self.svc,clear_completed=True)["deleted"],1)
        self.assertEqual(len(image_jobs.snapshot(self.svc,kind="generate")["jobs"]),1)
        self.assertEqual(len(image_jobs.snapshot(self.svc,kind="chat")["jobs"]),1)
        self.assertEqual(len(image_jobs.snapshot(self.svc,kind="upscale")["jobs"]),1)
        self.assertTrue((self.svc.session_v1.root / "generated-images" /
                         (self.original_id + ".png")).is_file())
        with self.assertRaises(ValueError):
            image_jobs.snapshot(self.svc,kind="nonsense")

    def test_older_active_request_stays_in_list_past_recent_forty(self):
        image_jobs._initialize(self.svc)
        with image_jobs._db(self.svc) as db:
            active_id = "img-" + "b"*24
            db.execute("INSERT INTO jobs(id,kind,state,phase,created,updated) "
                       "VALUES(?,?,?,?,?,?)",
                       (active_id,"generate","queued","queued",1,1))
            for i in range(45):
                db.execute("INSERT INTO jobs(id,kind,state,phase,created,updated) "
                           "VALUES(?,?,?,?,?,?)",
                           ("img-"+f"{i+1:024x}","generate","success","done",i+2,i+2))
        jobs = image_jobs.snapshot(self.svc,kind="generate")["jobs"]
        self.assertEqual(len(jobs),46)
        self.assertIn(active_id, {job["id"] for job in jobs})

    def test_service_concurrency_bounds_and_default(self):
        base = {"name":"test", "base_url":"https://img.example.net/v1",
                "model":"test-image", "api_key":"test", "reference_mode":"none",
                "sizes":"square"}
        self.assertEqual(image_api_services.save_service(self.svc,base)["concurrency"],1)
        for count in (1,20):
            self.assertEqual(image_api_services.save_service(self.svc,{
                **base,"concurrency":count})["concurrency"],count)
        for count in (0,21,1.5,True,"20"):
            with self.subTest(concurrency=count), self.assertRaises(image_api_services.ImageServiceError):
                image_api_services.save_service(self.svc,{**base,"concurrency":count})

    def test_draft_edit_same_id_non_draft_edit_copies_and_retry_creates_another(self):
        """Exact final UI contract, including immutable original tasks."""
        photo = base64.b64encode(png((12,8))).decode("ascii")
        request = {"prompt":"original full prompt", "natural_prompt":"中文原文",
                   "negative_prompt":"negative test", "steps":9, "seed":21,
                   "size":"768x1024", "strata_upscale":"off",
                   "strata_image_profile":"default", "strata_reference_mode":"single",
                   "strata_reference_assets":[{"data_url":"data:image/png;base64,"+photo,
                                               "name":"reference one.png"}]}
        drafted = image_jobs.submit(self.svc,{"action":"draft","request":request})
        self.assertEqual(drafted["state"],"draft")
        self.assertEqual(drafted["request"]["negative_prompt"],"negative test")
        ref = drafted["request"]["strata_reference_assets"][0]
        self.assertNotIn("data_url",ref)
        self.assertEqual(ref["name"],"reference one.png")
        self.assertEqual(image_jobs.reference_bytes(self.svc,ref["id"])[0],png((12,8)))
        self.assertNotIn(photo[:80],str(drafted))
        created_at = drafted["created"]
        time.sleep(.018)
        touched = image_jobs.submit(self.svc,{"action":"draft","id":drafted["id"]})
        self.assertEqual(touched["id"],drafted["id"])
        self.assertGreater(touched["updated"],drafted["updated"])
        self.assertEqual(touched["created"],created_at)
        changed = {**drafted["request"],"prompt":"edited once", "seed":33}
        saved = image_jobs.submit(self.svc,{"action":"save_draft", "id":drafted["id"],
                                            "request":changed})
        self.assertEqual(saved["id"],drafted["id"])
        self.assertEqual(saved["request"]["seed"],33)
        with mock.patch.object(image_jobs,"_generate",return_value={"image_ids":[self.original_id]}):
            executing = image_jobs.submit(self.svc,{"action":"activate","id":drafted["id"]})
            self.assertEqual(executing["id"],drafted["id"])
            self.assertEqual(executing["state"],"running")
            completed = self._wait(drafted["id"])
        self.assertEqual(completed["state"],"success")
        self.assertEqual(completed["request"]["seed"],33)
        with self.assertRaises(ValueError):
            image_jobs.submit(self.svc,{"action":"save_draft","id":completed["id"],"request":changed})
        source_bytes = image_jobs.reference_bytes(self.svc,ref["id"])[0]
        copy = image_jobs.submit(self.svc,{"action":"draft","copy_id":completed["id"]})
        self.assertNotEqual(copy["id"],completed["id"])
        self.assertEqual(copy["state"],"draft")
        self.assertEqual(copy["request"],completed["request"])
        image_jobs.submit(self.svc,{"action":"save_draft","id":copy["id"],
            "request":{**copy["request"],"prompt":"copied then modified"}})
        self.assertEqual(image_jobs.snapshot(self.svc,completed["id"])["request"]["prompt"],"edited once")
        self.assertEqual(image_jobs.reference_bytes(self.svc,ref["id"])[0],source_bytes)
        with mock.patch.object(image_jobs,"_generate",return_value={"image_ids":[self.original_id]}):
            retried = image_jobs.submit(self.svc,{"action":"retry","id":completed["id"]})
            self.assertEqual(retried["state"],"running")
            self.assertNotIn("deleted_original_id",retried)
            self.assertNotIn(retried["id"],(copy["id"],completed["id"]))
            self.assertEqual(self._wait(retried["id"])["state"],"success")
        self.assertEqual(image_jobs.snapshot(self.svc,completed["id"])["request"],completed["request"])

    def test_active_task_edit_copies_without_mutation_or_retry(self):
        original = image_jobs.submit(self.svc,{"action":"draft","request":{
            "prompt":"keep active","size":"768x768"}})
        with mock.patch.object(image_jobs,"_generate",side_effect=lambda *_: (time.sleep(.16) or
                                                            {"image_ids":[self.original_id]})):
            running=image_jobs.submit(self.svc,{"action":"activate","id":original["id"]})
            copy=image_jobs.submit(self.svc,{"action":"draft","copy_id":original["id"]})
            self.assertEqual(copy["state"],"draft")
            self.assertNotEqual(copy["id"],running["id"])
            with self.assertRaises(ValueError):
                image_jobs.submit(self.svc,{"action":"retry","id":running["id"]})
            self.assertEqual(self._wait(running["id"])["state"],"success")

    def test_limit_100_preserves_drafts_and_running(self):
        image_jobs._initialize(self.svc)
        with image_jobs._db(self.svc) as db:
            for i in range(100):
                db.execute("INSERT INTO jobs(id,kind,state,phase,created,updated) "
                    "VALUES(?,?,?,?,?,?)", ("img-"+f"{i+1:024x}","generate",
                    "draft" if i==0 else "running" if i==1 else "success",
                    "historical",i+1,i+1))
        fresh=image_jobs.submit(self.svc,{"action":"draft","request":{"prompt":"new"}})
        self.assertEqual(fresh["state"],"draft")
        records=image_jobs.snapshot(self.svc,kind="generate")["jobs"]
        self.assertEqual(len(records),100)
        self.assertIn("img-"+f"{1:024x}",{row["id"] for row in records})
        self.assertIn("img-"+f"{2:024x}",{row["id"] for row in records})
        self.assertNotIn("img-"+f"{3:024x}",{row["id"] for row in records})

    def test_full_capacity_never_trims_the_edit_or_retry_source(self):
        original = image_jobs.submit(self.svc,{"action":"draft","request":{"prompt":"valuable original"}})
        with mock.patch.object(image_jobs,"_generate",return_value={"image_ids":[self.original_id]}):
            image_jobs.submit(self.svc,{"action":"activate","id":original["id"]})
            self.assertEqual(self._wait(original["id"])["state"],"success")
        # One eligible success source plus 99 protected drafts fills 100 slots.
        with image_jobs._db(self.svc) as db:
            for i in range(99):
                db.execute("INSERT INTO jobs(id,kind,state,phase,created,updated) VALUES(?,?,?,?,?,?)",
                           ("img-"+f"{i+2:024x}","generate","draft","saved",i+2,i+2))
        with self.assertRaisesRegex(ValueError,"100"):
            image_jobs.submit(self.svc,{"action":"draft","copy_id":original["id"]})
        with self.assertRaisesRegex(ValueError,"100"):
            image_jobs.submit(self.svc,{"action":"retry","id":original["id"]})
        self.assertEqual(image_jobs.snapshot(self.svc,original["id"])["state"],"success")
        self.assertEqual(image_jobs.snapshot(self.svc,original["id"])["request"]["prompt"],
                         "valuable original")

    def test_api_service_timeout_and_key_are_independent_and_private(self):
        service = image_api_services.save_service(self.svc, {
            "name":"test provider", "base_url":"https://img.example.net/v1",
            "model":"test-image", "api_key":"secret-for-test-only",
            "reference_mode":"none", "sizes":"square", "proxy":False,
            "concurrency":2, "timeout_seconds":710,
        })
        self.assertEqual(service["concurrency"], 2)
        self.assertEqual(service["timeout_seconds"], 710)
        self.assertEqual(service["connect_timeout_seconds"], 15)
        self.assertNotIn("api_key", service)
        recorded = []
        @contextmanager
        def fake_session(_service):
            class Session:
                def post(self, url, **kwargs):
                    recorded.append(kwargs["timeout"])
                    return SimpleNamespace(ok=True, json=lambda:{"data":[{
                        "b64_json":base64.b64encode(png((12,8))).decode("ascii")}]})
            yield Session()
        with mock.patch.object(image_api_services,"_session", fake_session):
            out = image_api_services.generate(self.svc, {
                "prompt":"tiny image", "size":"1024x1024", "strata_image_profile":service["id"]})
        self.assertEqual(recorded, [(15,710)])
        self.assertTrue(out["strata"]["image_file"])
        updated = image_api_services.save_service(self.svc, {
            "id":service["id"], "name":"test provider",
            "base_url":"https://img.example.net/v1", "model":"test-image",
            "reference_mode":"none", "sizes":"square", "proxy":False,
            "concurrency":2, "timeout_seconds":710,
            "connect_timeout_seconds":30,
        })
        self.assertEqual(updated["connect_timeout_seconds"], 30)
        self.assertTrue(updated["has_key"], "updating timeout must preserve the API secret")
        for invalid in (4,61,True,"30"):
            with self.subTest(connect_timeout=invalid), self.assertRaises(image_api_services.ImageServiceError):
                image_api_services.save_service(self.svc, {
                    "id":service["id"], "name":"test provider",
                    "base_url":"https://img.example.net/v1", "model":"test-image",
                    "reference_mode":"none", "sizes":"square", "proxy":False,
                    "concurrency":2, "timeout_seconds":710,
                    "connect_timeout_seconds":invalid,
                })
        with self.assertRaises(image_api_services.ImageServiceError):
            image_api_services.save_service(self.svc, {
                "name":"test", "base_url":"https://img.example.net/v1",
                "model":"test-image", "api_key":"secret", "reference_mode":"none",
                "sizes":"square", "concurrency":21, "timeout_seconds":710})

    def test_interrupted_service_job_becomes_interrupted_not_fake_running(self):
        path = self.svc.session_v1.root / "image-jobs.sqlite3"
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY,kind TEXT,source_id TEXT,"
                       "state TEXT,phase TEXT,result TEXT,error TEXT,created REAL,updated REAL)")
            db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)",
                       ("img-" + "b"*24, "generate", "", "working", "running", "{}", "", 1, 1))
        db.close()
        self.assertEqual(image_jobs.snapshot(self.svc, "img-" + "b"*24)["state"], "failed")


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
