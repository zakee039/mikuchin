"""Isolated Native Worker concurrency regression: no third-party paid requests.

All provider calls are in-process stubs on a disposable SQLite image store.
The test verifies the REAL independent worker loop, not only config parsing.
"""
from __future__ import annotations

import hashlib
import io
import tempfile
import threading
import time
import unittest
from collections import Counter
from pathlib import Path

from PIL import Image

from backend.gateway import image_providers
from backend.gateway.image_jobs import ImageJobStore
from backend.gateway.worker import ImageWorker


class ConcurrentApiWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.jobs=ImageJobStore(self.root/"images")
        self.worker=ImageWorker(self.root/"images",poll=.025)
        self.started=Counter()
        self.running=Counter()
        self.max_running=Counter()
        self.total_running=0
        self.max_total_running=0
        self.provider_calls=[]
        self.release=threading.Event()
        self.gate=threading.Lock()

        def provider(store,req,*,on_status,diagnostic_id,**_):
            key=req["strata_image_profile"]
            with self.gate:
                self.started[key]+=1
                self.running[key]+=1
                self.total_running+=1
                self.provider_calls.append(diagnostic_id)
                self.max_running[key]=max(self.max_running[key],self.running[key])
                self.max_total_running=max(self.max_total_running,self.total_running)
            try:
                on_status("stub provider active")
                if not self.release.wait(12):
                    raise TimeoutError("mock provider unexpectedly held too long")
                target=store.root/"generated-images"
                target.mkdir(parents=True,exist_ok=True)
                file=hashlib.sha256(diagnostic_id.encode()).hexdigest()[:32]+".png"
                out=io.BytesIO()
                Image.new("RGB",(16,16),"white").save(out,"PNG")
                (target/file).write_bytes(out.getvalue())
                return {"strata":{"image_file":file},"model":"mock","size":req["size"]}
            finally:
                with self.gate:
                    self.running[key]-=1
                    self.total_running-=1

        self.worker.store._provider=provider
        self.thread=threading.Thread(target=self.worker.run_forever,
                                     daemon=True,name="concurrent-image-test")
        self.thread.start()
        self.wait_for(lambda:self.jobs.worker_healthy(),timeout=5)

    def tearDown(self):
        self.release.set()
        self.worker.stop.set()
        self.thread.join(timeout=18)
        self.assertFalse(self.thread.is_alive(),"worker must drain started tasks")
        self.temp.cleanup()

    def wait_for(self,predicate,timeout=5):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            if predicate():return
            time.sleep(.025)
        self.fail("timed out waiting for expected concurrency")

    def add_service(self,concurrency):
        return image_providers.save_service(self.jobs,{
            "name":f"Mock service {concurrency}",
            "base_url":"http://127.0.0.1:19231/v1",
            "model":"test-image","api_key":"LOCAL_MOCK_ONLY",
            "concurrency":concurrency,"sizes":"standard"})["id"]

    def enqueue(self,profile,number):
        return [self.jobs.submit({"request":{
            "strata_image_profile":profile,
            "size":"1024x1024","prompt":f"image {i}",
            "strata_upscale":"off"}})["id"] for i in range(number)]

    def test_per_provider_limit_and_other_service_skip_head_of_line(self):
        first=self.add_service(2)
        other=self.add_service(1)
        first_jobs=self.enqueue(first,4)
        other_jobs=self.enqueue(other,2)
        self.wait_for(lambda:self.started[first]>=2 and self.started[other]>=1)
        time.sleep(.18)
        with self.gate:
            self.assertEqual(self.started[first],2)
            self.assertEqual(self.started[other],1)
            self.assertEqual(self.max_running[first],2)
            self.assertEqual(self.max_running[other],1)
            self.assertEqual(self.max_total_running,3)
        pending=[self.jobs.listing(i) for i in first_jobs+other_jobs]
        self.assertEqual(sum(x["started_at"] is None for x in pending),3)
        self.assertEqual(sum(x["started_at"] is not None for x in pending),3)
        self.release.set()
        self.wait_for(lambda:all(self.jobs.listing(i)["state"]=="success"
                             for i in first_jobs+other_jobs),timeout=10)
        self.assertEqual(len(self.provider_calls),6)
        self.assertEqual(len(set(self.provider_calls)),6)
        self.assertLessEqual(self.max_running[first],2)
        self.assertLessEqual(self.max_running[other],1)
        self.assertLessEqual(self.max_total_running,3)

    def test_local_lane_is_serial_and_never_blocks_api_capacity(self):
        profile=self.add_service(3)
        fake_active={object():("some-job",("local","gpu"))}
        self.assertFalse(self.worker._eligible(
            {"strata_image_profile":"local-sdxl"},fake_active))
        self.assertFalse(self.worker._eligible({"kind":"upscale"},fake_active))
        self.assertTrue(self.worker._eligible(
            {"strata_image_profile":profile},fake_active))
        for _ in range(3):
            fake_active[object()]=("api-job",("api",profile))
        self.assertFalse(self.worker._eligible(
            {"strata_image_profile":profile},fake_active))

    def test_configured_five_starts_five_and_queues_sixth(self):
        profile=self.add_service(5)
        jobs=self.enqueue(profile,6)
        self.wait_for(lambda:self.started[profile]==5)
        time.sleep(.12)
        with self.gate:
            self.assertEqual(self.running[profile],5)
            self.assertEqual(self.started[profile],5)
        records=[self.jobs.listing(j) for j in jobs]
        self.assertEqual(sum(r["started_at"] is not None for r in records),5)
        self.assertEqual(sum(r["started_at"] is None for r in records),1)
        self.release.set()
        self.wait_for(lambda:all(self.jobs.listing(j)["state"]=="success"
                                 for j in jobs),timeout=10)
        self.assertEqual(self.started[profile],6)
        self.assertEqual(self.max_running[profile],5)

    def test_no_claim_or_new_api_call_after_stop(self):
        profile=self.add_service(1)
        jobs=self.enqueue(profile,3)
        self.wait_for(lambda:self.started[profile]==1)
        self.worker.stop.set()
        self.release.set()
        self.thread.join(timeout=6)
        self.assertFalse(self.thread.is_alive())
        self.assertEqual(self.started[profile],1)
        self.assertEqual(self.jobs.listing(jobs[0])["state"],"success")
        # Queued jobs are not submitted; after a non-graceful restart the
        # existing conservative uncertainty handling remains unchanged.
        for ident in jobs[1:]:
            record=self.jobs.listing(ident)
            self.assertEqual(record["state"],"running")
            self.assertIsNone(record["started_at"])


if __name__=="__main__":
    unittest.main()
